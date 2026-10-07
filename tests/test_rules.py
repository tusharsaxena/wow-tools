from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import NOW, build_solo_tree, build_wow_tree
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.text import human_size
from wowtools.tools.wtf_cleaner.rules import Criteria, criterion_counts, evaluate
from wowtools.tools.wtf_cleaner.scanner import scan
from wowtools.tools.wtf_cleaner.settings import (DEFAULT_BACKUP_SUBDIR, SECTION, CleanerSettings, load_settings,
                                                 resolve_backup_dir, save_settings)


class RulesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.retail = WowInstall(build_wow_tree(self.tmp / "World of Warcraft")).flavor("retail")
        self.sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        self.scan = scan(self.retail)

    def summary(self, proposal):
        return [(i.account, i.owner_label, i.addon, tuple(i.reasons), tuple(sorted(f.name for f in i.files)))
                for i in proposal.items]

    def test_default_criteria_flag_any_match(self):
        proposal = evaluate(self.scan, Criteria(), now=NOW)
        self.assertCountEqual(self.summary(proposal), [
            ("ACCT1", "account-wide", "Auctionator", ("stray_copies",), ("Auctionator.lua.pre-schema8-20260926-103400",)),
            ("ACCT1", "account-wide", "Details", ("stray_copies",), ("Details.lua - Copy.bak",)),
            ("ACCT1", "account-wide", "DisabledAddon", ("not_enabled",), ("DisabledAddon.lua",)),
            ("ACCT1", "account-wide", "OldAddon", ("older_than",), ("OldAddon.lua", "OldAddon.lua.bak")),
            ("ACCT1", "account-wide", "Uninstalled", ("not_installed",), ("Uninstalled.lua", "Uninstalled.lua.bak")),
            ("ACCT1", "Realm1/CharA", "Uninstalled", ("not_installed",), ("Uninstalled.lua",)),
        ])
        self.assertEqual(proposal.total_files, 8)
        self.assertEqual(proposal.by_reason(), {"not_installed": 2, "not_enabled": 1, "older_than": 1, "stray_copies": 2})

    def test_each_criterion_alone(self):
        expected = {"not_installed": {"Uninstalled"}, "not_enabled": {"DisabledAddon"},
                    "older_than": {"OldAddon"}, "stray_copies": {"Auctionator", "Details"}, "orphan_backups": set()}
        for name, addons in expected.items():
            with self.subTest(name):
                proposal = evaluate(self.scan, Criteria.from_names([name]), now=NOW)
                self.assertEqual({i.addon for i in proposal.items}, addons)

    def test_no_criteria_proposes_nothing(self):
        self.assertEqual(evaluate(self.scan, Criteria.from_names([]), now=NOW).items, [])

    def test_age_uses_newest_file_in_group(self):
        os.utime(self.sv / "OldAddon.lua", (NOW, NOW))
        proposal = evaluate(scan(self.retail), Criteria.from_names(["older_than"]), now=NOW)
        self.assertEqual(proposal.items, [])

    def test_max_age_threshold(self):
        proposal = evaluate(self.scan, Criteria.from_names(["older_than"], max_age_days=250), now=NOW)
        self.assertEqual(proposal.items, [])

    def test_flagged_group_with_strays_lists_both_reasons(self):
        (self.sv / "Uninstalled.lua.old").write_text("x")
        proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        item = next(i for i in proposal.items if i.addon == "Uninstalled" and i.character is None)
        self.assertEqual(item.reasons, ["not_installed", "stray_copies"])
        self.assertEqual(len(item.files), 3)

    def test_orphan_backup_alone_is_its_own_criterion(self):
        """A <Addon>.lua.bak with no <Addon>.lua next to it (any case) is an orphan backup, even when the addon is
        installed, enabled and fresh: only the backup is proposed."""
        char_sv = self.sv.parent / "Realm1" / "CharA" / "SavedVariables"
        (char_sv / "details.LUA.bak").write_text("x")
        (char_sv / "Auctionator.lua.bak").write_text("x")  # Auctionator.lua is there: not an orphan
        proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        orphans = [(i.owner_label, i.addon, tuple(i.reasons), tuple(f.name for f in i.files))
                   for i in proposal.items if "orphan_backups" in i.reasons]
        self.assertEqual(orphans, [("Realm1/CharA", "details", ("orphan_backups",), ("details.LUA.bak",))])
        alone = evaluate(scan(self.retail), Criteria.from_names(["orphan_backups"]), now=NOW)
        self.assertEqual([(i.addon, [f.name for f in i.files]) for i in alone.items], [("details", ["details.LUA.bak"])])
        self.assertEqual(criterion_counts(scan(self.retail), max_age_days=90, now=NOW)["orphan_backups"], 1)

    def test_a_backup_is_no_orphan_while_its_lua_is_renamed_by_a_lock_check_or_unreadable(self):
        """An interrupted lock check leaves <Addon>.lua renamed to <Addon>.lua<LOCK_PROBE_SUFFIX>; the next clean
        renames it back, so its .lua.bak is not an orphan. Neither is one whose .lua the scan could not read."""
        from wowtools.core.svfiles import LOCK_PROBE_SUFFIX
        (self.sv / "Auctionator.lua").rename(self.sv / f"Auctionator.lua{LOCK_PROBE_SUFFIX}")
        result = scan(self.retail)
        self.assertEqual(evaluate(result, Criteria.from_names(["orphan_backups"]), now=NOW).items, [])
        real_stat = Path.stat

        def failing_stat(path, *args, **kwargs):
            if path.name == "Details.lua" and path.parent == self.sv:
                raise PermissionError("denied")
            return real_stat(path, *args, **kwargs)

        (self.sv / "Details.lua.bak").write_text("x")
        with mock.patch.object(Path, "stat", failing_stat):
            result = scan(self.retail)
        self.assertEqual(evaluate(result, Criteria.from_names(["orphan_backups"]), now=NOW).items, [])

    def test_orphan_backup_of_a_flagged_addon_lists_both_reasons(self):
        (self.sv / "Gone.lua.bak").write_text("x")
        (self.sv / "Gone.lua.old").write_text("x")  # a stray copy in the same group
        proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        item = next(i for i in proposal.items if i.addon == "Gone")
        self.assertEqual(item.reasons, ["not_installed", "stray_copies", "orphan_backups"])
        self.assertEqual(sorted(f.name for f in item.files), ["Gone.lua.bak", "Gone.lua.old"])
        only = evaluate(scan(self.retail), Criteria.from_names(["orphan_backups"]), now=NOW)
        self.assertEqual([(i.addon, [f.name for f in i.files]) for i in only.items if i.addon == "Gone"],
                         [("Gone", ["Gone.lua.bak"])])

    def test_unknown_criterion_rejected(self):
        with self.assertRaises(ValueError):
            Criteria.from_names(["bogus"])

    def test_no_characters_proposes_only_not_installed(self):
        solo = WowInstall(build_solo_tree(self.tmp / "Solo WoW")).flavor("retail")
        proposal = evaluate(scan(solo), Criteria(), now=NOW)
        self.assertEqual([(i.addon, i.reasons) for i in proposal.items], [("Gone", ["not_installed"])])

    def test_criterion_counts(self):
        # Files each criterion proposes on its own (see the fixture docstring): Uninstalled.lua + .bak +
        # CharA/Uninstalled.lua; DisabledAddon.lua; OldAddon.lua + .bak; the two hand-made copies.
        self.assertEqual(criterion_counts(self.scan, max_age_days=90, now=NOW),
                         {"not_installed": 3, "not_enabled": 1, "older_than": 2, "stray_copies": 2,
                          "orphan_backups": 0})
        self.assertEqual(criterion_counts(self.scan, max_age_days=250, now=NOW)["older_than"], 0)

    def test_criterion_counts_emits_no_proposal_events(self):
        with capture_events() as records:
            criterion_counts(self.scan, max_age_days=90, now=NOW)
        self.assertEqual([r["event"] for r in records if r["event"].startswith("proposal.")], [])

    def test_proposal_events(self):
        with capture_events() as records:
            evaluate(self.scan, Criteria(), now=NOW)
        built = [r for r in records if r["event"] == "proposal.built"]
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["data"]["items"], 6)
        self.assertEqual(len([r for r in records if r["event"] == "proposal.item"]), 6)

    def test_describe(self):
        self.assertEqual(Criteria().describe(),
                         "not_installed, not_enabled, older_than(90d), stray_copies, orphan_backups")
        self.assertEqual(Criteria.from_names([]).describe(), "none")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "c.cfg"

    def test_defaults_and_round_trip(self):
        cfg = Config(self.path)
        settings = load_settings(cfg)
        self.assertEqual(settings.criteria, Criteria())
        self.assertTrue(settings.backup_before_delete)
        settings.criteria.not_enabled = False
        settings.criteria.max_age_days = 30
        save_settings(cfg, settings)
        again = load_settings(Config(self.path).load())
        self.assertFalse(again.criteria.not_enabled)
        self.assertEqual(again.criteria.max_age_days, 30)

    def test_last_flavor_choice(self):
        cfg = Config(self.path)
        self.assertIsNone(load_settings(cfg).last_flavor_choice)  # never chosen: the picker falls back
        save_settings(cfg, load_settings(cfg))
        self.assertIsNone(load_settings(Config(self.path).load()).last_flavor_choice)
        cfg.set(SECTION, "last_flavor_choice", "")
        self.assertEqual(load_settings(cfg).last_flavor_choice, "")  # All flavors
        cfg.set(SECTION, "last_flavor_choice", " _retail_ ")
        settings = load_settings(cfg)
        self.assertEqual(settings.last_flavor_choice, "_retail_")
        save_settings(cfg, settings)
        self.assertEqual(load_settings(Config(self.path).load()).last_flavor_choice, "_retail_")

    def test_bad_values_fall_back(self):
        cfg = Config(self.path)
        cfg.set(SECTION, "max_age_days", "0")
        cfg.set(SECTION, "criterion_older_than", "perhaps")
        settings = load_settings(cfg)
        self.assertEqual(settings.criteria.max_age_days, 1)
        self.assertTrue(settings.criteria.older_than)
        cfg.set(SECTION, "max_age_days", "soon")
        self.assertEqual(load_settings(cfg).criteria.max_age_days, 90)


    def test_keep_cleaned_round_trip_and_bad_values(self):
        """#4: the cleaned-files zips kept per flavor; 0 (the default) keeps all, and save keeps the key."""
        cfg = Config(self.path)
        self.assertEqual(load_settings(cfg).keep_cleaned, 0)
        settings = load_settings(cfg)
        settings.keep_cleaned = 5
        save_settings(cfg, settings)
        reloaded = Config(self.path).load()
        self.assertEqual(reloaded.get(SECTION, "keep_cleaned"), "5")  # remove_retired leaves it alone
        self.assertEqual(load_settings(reloaded).keep_cleaned, 5)
        for bad in ("-3", "lots"):
            cfg.set(SECTION, "keep_cleaned", bad)
            self.assertEqual(load_settings(cfg).keep_cleaned, 0)

    def test_resolve_backup_dir_default(self):
        self.assertEqual(DEFAULT_BACKUP_SUBDIR, Path("wow-tools") / "wtf-cleaner")
        self.assertEqual(resolve_backup_dir(load_settings(Config(self.path)), Path("/games/wow")),
                         Path("/games/wow") / "wow-tools" / "wtf-cleaner")
        self.assertIsNone(resolve_backup_dir(CleanerSettings(), None))

    def test_resolve_backup_dir_setting(self):
        cfg = Config(self.path)
        cfg.set_path(SECTION, "backup_dir", Path("/elsewhere/bk"))
        self.assertEqual(resolve_backup_dir(load_settings(cfg), Path("/games/wow")), Path("/elsewhere/bk"))

    def test_retention_is_global_and_stale_keys_go_on_save(self):
        """Feedback round 1: retention lives in [general]; the old per-tool keys are ignored, then removed."""
        cfg = Config(self.path)
        for key, value in (("keep_backups", "3"), ("keep_journals", "2"), ("keep_snapshots", "2")):
            cfg.set(SECTION, key, value, log=False)
        settings = load_settings(cfg)
        for name in ("keep_backups", "keep_journals", "keep_snapshots"):
            self.assertFalse(hasattr(settings, name), name)
        save_settings(cfg, settings)
        again = Config(self.path).load()
        for key in ("keep_backups", "keep_journals", "keep_snapshots"):
            self.assertIsNone(again.get(SECTION, key), key)

    def test_settings_round_trip_backup_dir(self):
        cfg = Config(self.path)
        settings = load_settings(cfg)
        self.assertIsNone(settings.backup_dir)
        settings.backup_dir = Path("/elsewhere/bk")
        save_settings(cfg, settings)
        self.assertEqual(load_settings(Config(self.path).load()).backup_dir, Path("/elsewhere/bk"))
        settings.backup_dir = None
        save_settings(cfg, settings)
        self.assertIsNone(load_settings(Config(self.path).load()).backup_dir)

    def test_settings_round_trip_last_account(self):
        cfg = Config(self.path)
        settings = load_settings(cfg)
        self.assertIsNone(settings.last_account)
        settings.last_account = "ACCT2"
        save_settings(cfg, settings)
        self.assertEqual(Config(self.path).load().get(SECTION, "last_account"), "ACCT2")
        self.assertEqual(load_settings(Config(self.path).load()).last_account, "ACCT2")
        settings.last_account = None
        save_settings(cfg, settings)
        self.assertEqual(Config(self.path).load().get(SECTION, "last_account"), "")
        self.assertIsNone(load_settings(Config(self.path).load()).last_account)


class ReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.retail = WowInstall(build_wow_tree(Path(tmp.name) / "World of Warcraft")).flavor("retail")

    def test_human_size(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(1023), "1023 B")
        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_size(5 * 1024 * 1024), "5.0 MB")
