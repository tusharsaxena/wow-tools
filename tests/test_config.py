from __future__ import annotations

import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import (CONFIG_DIR, DEFAULT_CONFIG_PATH, LEGACY_CONFIG_PATH, Config, ConfigError,
                                  migrate_legacy_config, tool_config_path)
from wowtools.core.events import capture_events


class ConfigTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "wow-tools.cfg"

    def test_default_paths_are_in_the_config_folder_not_cwd(self):
        self.assertEqual(DEFAULT_CONFIG_PATH, REPO_ROOT / "config" / "wow-tools.cfg")
        self.assertEqual(tool_config_path("wtf-cleaner"), REPO_ROOT / "config" / "wtf-cleaner.cfg")
        self.assertEqual(LEGACY_CONFIG_PATH, REPO_ROOT / "wow-tools.cfg")
        self.assertEqual(CONFIG_DIR, REPO_ROOT / "config")

    def test_missing_file_gives_defaults(self):
        cfg = Config(self.path).load()
        self.assertFalse(cfg.exists)
        self.assertIsNone(cfg.wow_path)
        self.assertIsNone(cfg.last_flavor)
        self.assertTrue(cfg.check_for_updates)
        self.assertFalse(cfg.auto_update)
        self.assertFalse(cfg.allow_unverified_updates)
        self.assertEqual(cfg.log_level, "info")
        self.assertEqual(cfg.log_retention_days, 90)
        self.assertIsNone(cfg.last_update_check)

    def test_round_trip_preserves_unknown_keys_and_sections(self):
        self.path.write_text("[general]\nwow_path = /games/wow\nmystery = 42\n\n[other_tool]\nfoo = bar\n",
                             encoding="utf-8")
        cfg = Config(self.path).load()
        cfg.set("general", "last_flavor", "_retail_")
        cfg.save()
        again = Config(self.path).load()
        self.assertEqual(again.get("general", "mystery"), "42")
        self.assertEqual(again.get("other_tool", "foo"), "bar")
        self.assertEqual(again.last_flavor, "_retail_")
        self.assertEqual(again.wow_path, Path("/games/wow"))

    def test_bad_values_fall_back_to_defaults(self):
        self.path.write_text("[general]\ncheck_for_updates = maybe\nlog_level = loud\n"
                             "log_retention_days = soon\nlast_update_check = yesterday\n", encoding="utf-8")
        cfg = Config(self.path).load()
        self.assertTrue(cfg.check_for_updates)
        self.assertEqual(cfg.log_level, "info")
        self.assertEqual(cfg.log_retention_days, 90)
        self.assertIsNone(cfg.last_update_check)
        self.assertEqual(cfg.get_int("general", "log_retention_days", 7), 7)

    def test_retention_defaults_are_ten_and_ten(self):
        """Feedback round 1: retention is one global setting in [general]."""
        cfg = Config(self.path).load()
        self.assertEqual((cfg.keep_backups, cfg.keep_journals), (10, 10))

    def test_retention_bad_values_fall_back(self):
        cfg = Config(self.path)
        cfg.set("general", "keep_backups", "lots", log=False)
        cfg.set("general", "keep_journals", "few", log=False)
        self.assertEqual((cfg.keep_backups, cfg.keep_journals), (10, 10))
        cfg.set("general", "keep_backups", "-3", log=False)
        self.assertEqual(cfg.keep_backups, 10)
        cfg.set("general", "keep_backups", "0", log=False)  # 0 = keep all
        cfg.set("general", "keep_journals", "0", log=False)  # at least 1
        self.assertEqual((cfg.keep_backups, cfg.keep_journals), (0, 1))
        cfg.set("general", "keep_backups", "4", log=False)
        cfg.set("general", "keep_journals", "3", log=False)
        self.assertEqual((cfg.keep_backups, cfg.keep_journals), (4, 3))

    def test_parallelism_defaults_to_two_and_is_clamped(self):
        """D10: [general] parallelism, 1-8, default 2; out of range is clamped, unreadable gives the default."""
        cfg = Config(self.path)
        self.assertEqual(cfg.parallelism, 2)
        for raw, expected in (("1", 1), ("8", 8), ("0", 1), ("-4", 1), ("9", 8), ("64", 8), ("lots", 2), ("", 2)):
            cfg.set("general", "parallelism", raw, log=False)
            self.assertEqual(cfg.parallelism, expected, raw)

    def test_remove_drops_a_key_and_logs_it(self):
        cfg = Config(self.path)
        cfg.set("tool", "keep_backups", "3", log=False)
        cfg.set("tool", "other", "x", log=False)
        with capture_events() as records:
            cfg.remove("tool", "keep_backups")
            cfg.remove("tool", "keep_backups")  # gone already: nothing happens
            cfg.remove("nosuch", "key")
        self.assertIsNone(cfg.get("tool", "keep_backups"))
        self.assertEqual(cfg.get("tool", "other"), "x")
        changed = [r["data"] for r in records if r["event"] == "config.changed"]
        self.assertEqual([(c["key"], c["old"], c["new"]) for c in changed], [("keep_backups", "3", None)])

    def test_backup_dir_is_not_a_general_setting(self):
        cfg = Config(self.path)
        cfg.set("general", "wow_path", "/games/wow")
        self.assertFalse(hasattr(cfg, "backup_dir"))

    def test_set_logs_real_changes_only(self):
        cfg = Config(self.path)
        with capture_events() as records:
            cfg.set("wtf_cleaner", "max_age_days", 30, source="wizard")
            cfg.set("wtf_cleaner", "max_age_days", 30)
            cfg.set("general", "last_update_check", "x", log=False)
        changed = [r for r in records if r["event"] == "config.changed"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["data"], {"section": "wtf_cleaner", "key": "max_age_days",
                                              "old": None, "new": "30", "source": "wizard"})

    def test_bools_are_written_lowercase(self):
        cfg = Config(self.path)
        cfg.set("x", "flag", True)
        self.assertEqual(cfg.get("x", "flag"), "true")
        self.assertTrue(cfg.get_bool("x", "flag", False))

    def test_first_save_logs_created_once(self):
        with capture_events() as records:
            cfg = Config(self.path)
            cfg.save()
            cfg.save()
        self.assertEqual([r["event"] for r in records].count("config.created"), 1)
        self.assertTrue(self.path.exists())

    def test_save_if_exists_does_not_create(self):
        Config(self.path).save_if_exists()
        self.assertFalse(self.path.exists())

    def test_last_update_check_round_trip(self):
        cfg = Config(self.path)
        when = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
        cfg.set("general", "last_update_check", when.isoformat())
        self.assertEqual(cfg.last_update_check, when)
        cfg.set("general", "last_update_check", "2026-09-27T12:00:00")
        self.assertEqual(cfg.last_update_check, when)

    def test_save_is_atomic(self):
        cfg = Config(self.path)
        cfg.set("general", "wow_path", "/games/wow")
        cfg.save()
        before = self.path.read_bytes()
        cfg.set("general", "last_flavor", "_retail_")
        with patch("wowtools.core.fsutil.os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            cfg.save()
        self.assertEqual(self.path.read_bytes(), before)

    def test_save_leaves_no_partial_on_success(self):
        cfg = Config(self.path)
        cfg.set("general", "wow_path", "/games/wow")
        cfg.save()
        cfg.save()
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["wow-tools.cfg"])

    @unittest.skipIf(os.name == "nt", "Windows refuses to replace a file another thread has open; the app never "
                                      "reads its config while saving it")
    def test_concurrent_set_and_save_never_corrupts(self):
        """One thread keeps saving (as the UI thread does); another keeps loading. Every load must see a whole
        file: a truncate-and-rewrite save lets a reader see an empty or half-written file."""
        cfg = Config(self.path)
        cfg.set("general", "wow_path", "/games/wow", log=False)
        cfg.save()
        stop = threading.Event()
        bad: list[str] = []

        def reader():
            while not stop.is_set():
                try:
                    loaded = Config(self.path).load()
                except ConfigError as exc:
                    bad.append(str(exc))
                    continue
                if loaded.wow_path is None:
                    bad.append("empty or partial file")

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for n in range(1000):
                cfg.set("general", "counter", n, log=False)
                cfg.save()
        finally:
            stop.set()
            thread.join()
        self.assertEqual(bad, [])

    def test_unreadable_config_raises_config_error(self):
        self.path.write_text("this is not an ini file [[[", encoding="utf-8")
        with self.assertRaises(ConfigError):
            Config(self.path).load()


class MigrationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.legacy = self.tmp / "wow-tools.cfg"
        self.config_dir = self.tmp / "config"

    def test_splits_general_and_tool_sections_and_removes_the_old_file(self):
        self.legacy.write_text("[general]\nwow_path = G:\\WoW\nbackup_dir = \nlast_flavor = _retail_\n\n"
                               "[wtf_cleaner]\nmax_age_days = 30\nlast_account = \n\n[mystery]\nx = 1\n",
                               encoding="utf-8")
        written = migrate_legacy_config(self.legacy, self.config_dir, {"wtf_cleaner": "wtf-cleaner"})
        self.assertEqual(written, sorted([self.config_dir / "wow-tools.cfg", self.config_dir / "wtf-cleaner.cfg"]))
        self.assertFalse(self.legacy.exists())
        general = Config(self.config_dir / "wow-tools.cfg").load()
        self.assertEqual(general.get("general", "wow_path"), "G:\\WoW")
        self.assertEqual(general.last_flavor, "_retail_")
        self.assertIsNone(general.get("general", "backup_dir"))  # retired key dropped
        self.assertEqual(general.get("mystery", "x"), "1")  # unknown sections stay with [general]
        self.assertIsNone(general.get("wtf_cleaner", "max_age_days"))
        tool = Config(self.config_dir / "wtf-cleaner.cfg").load()
        self.assertEqual(tool.get("wtf_cleaner", "max_age_days"), "30")
        self.assertEqual(tool.get("wtf_cleaner", "last_account"), "")

    def test_nothing_to_do_when_new_config_exists_or_no_legacy(self):
        self.assertEqual(migrate_legacy_config(self.legacy, self.config_dir, {}), [])
        self.legacy.write_text("[general]\n", encoding="utf-8")
        self.config_dir.mkdir()
        (self.config_dir / "wow-tools.cfg").write_text("[general]\nlast_flavor = x\n", encoding="utf-8")
        self.assertEqual(migrate_legacy_config(self.legacy, self.config_dir, {}), [])
        self.assertTrue(self.legacy.exists())

    def test_unreadable_legacy_raises_and_keeps_it(self):
        self.legacy.write_text("not an ini", encoding="utf-8")
        with self.assertRaises(ConfigError):
            migrate_legacy_config(self.legacy, self.config_dir, {})
        self.assertTrue(self.legacy.exists())
