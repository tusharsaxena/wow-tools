from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import NOW, build_solo_tree, build_wow_tree
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.report import format_size
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
                    "older_than": {"OldAddon"}, "stray_copies": {"Auctionator", "Details"}}
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
                         {"not_installed": 3, "not_enabled": 1, "older_than": 2, "stray_copies": 2})
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
        self.assertEqual(Criteria().describe(), "not_installed, not_enabled, older_than(90d), stray_copies")
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


    def test_resolve_backup_dir_default(self):
        self.assertEqual(DEFAULT_BACKUP_SUBDIR, Path("wow-tools") / "wtf-cleaner")
        self.assertEqual(resolve_backup_dir(load_settings(Config(self.path)), Path("/games/wow")),
                         Path("/games/wow") / "wow-tools" / "wtf-cleaner")
        self.assertIsNone(resolve_backup_dir(CleanerSettings(), None))

    def test_resolve_backup_dir_setting(self):
        cfg = Config(self.path)
        cfg.set_path(SECTION, "backup_dir", Path("/elsewhere/bk"))
        self.assertEqual(resolve_backup_dir(load_settings(cfg), Path("/games/wow")), Path("/elsewhere/bk"))

    def test_keep_backups_round_trip_and_floor(self):
        cfg = Config(self.path)
        self.assertEqual(load_settings(cfg).keep_backups, 5)
        settings = load_settings(cfg)
        settings.keep_backups = 8
        save_settings(cfg, settings)
        self.assertEqual(load_settings(Config(self.path).load()).keep_backups, 8)
        cfg.set(SECTION, "keep_backups", "0")
        self.assertEqual(load_settings(cfg).keep_backups, 1)

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

    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1023), "1023 B")
        self.assertEqual(format_size(1536), "1.5 KB")
        self.assertEqual(format_size(5 * 1024 * 1024), "5.0 MB")
