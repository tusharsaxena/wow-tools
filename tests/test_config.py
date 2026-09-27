import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import DEFAULT_CONFIG_PATH, Config, ConfigError
from wowtools.core.events import capture_events


class ConfigTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "wow-tools.cfg"

    def test_default_path_is_repo_root_not_cwd(self):
        self.assertEqual(DEFAULT_CONFIG_PATH, REPO_ROOT / "wow-tools.cfg")

    def test_missing_file_gives_defaults(self):
        cfg = Config(self.path).load()
        self.assertFalse(cfg.exists)
        self.assertIsNone(cfg.wow_path)
        self.assertIsNone(cfg.backup_dir)
        self.assertIsNone(cfg.last_flavor)
        self.assertTrue(cfg.check_for_updates)
        self.assertFalse(cfg.auto_update)
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

    def test_backup_dir_defaults_under_wow_path(self):
        cfg = Config(self.path)
        cfg.set("general", "wow_path", "/games/wow")
        self.assertEqual(cfg.backup_dir, Path("/games/wow") / "wow-tools-backups")
        cfg.set_path("general", "backup_dir", Path("/elsewhere/bk"))
        self.assertEqual(cfg.backup_dir, Path("/elsewhere/bk"))
        cfg.set_path("general", "backup_dir", None)
        self.assertEqual(cfg.backup_dir, Path("/games/wow") / "wow-tools-backups")

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

    def test_unreadable_config_raises_config_error(self):
        self.path.write_text("this is not an ini file [[[", encoding="utf-8")
        with self.assertRaises(ConfigError):
            Config(self.path).load()
