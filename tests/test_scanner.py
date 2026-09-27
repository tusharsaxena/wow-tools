import tempfile
import unittest
from pathlib import Path

from tests.fixtures import NOW, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.rules import Criteria, evaluate
from wowtools.tools.wtf_cleaner.scanner import (ScanError, addon_name_for, installed_addons, is_canonical,
                                                parse_addons_txt, scan)


class NameTest(unittest.TestCase):
    def test_addon_name_for(self):
        cases = {"Auctionator.lua": "Auctionator", "Foo.LUA.bak": "Foo", "Foo.lua - Copy.bak": "Foo",
                 "!BugGrabber.lua": "!BugGrabber", "[Weird] Addon.lua": "[Weird] Addon",
                 "notes.txt": None, ".lua": None}
        for filename, expected in cases.items():
            with self.subTest(filename):
                self.assertEqual(addon_name_for(filename), expected)

    def test_is_canonical(self):
        self.assertTrue(is_canonical("Foo.lua", "Foo"))
        self.assertTrue(is_canonical("Foo.lua.bak", "Foo"))
        self.assertFalse(is_canonical("Foo.lua.pre-schema8-20260926-103400", "Foo"))
        self.assertFalse(is_canonical("Foo.lua - Copy.bak", "Foo"))


class ScannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.install = WowInstall(build_wow_tree(Path(tmp.name) / "World of Warcraft"))
        self.retail = self.install.flavor("retail")

    def test_installed_addons_needs_a_toc(self):
        self.assertEqual(installed_addons(self.retail.addons_dir), {
            "auctionator": "Auctionator", "details": "Details",
            "disabledaddon": "DisabledAddon", "oldaddon": "OldAddon"})

    def test_parse_addons_txt_warns_on_garbage(self):
        warnings = []
        path = self.retail.account_dir / "ACCT2" / "Realm2" / "Chârb" / "AddOns.txt"
        states = parse_addons_txt(path, warnings)
        self.assertFalse(states["details"])
        self.assertTrue(states["auctionator"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("garbage line", warnings[0].message)

    def test_enabled_is_global_union(self):
        self.assertEqual(scan(self.retail).enabled, {"auctionator", "details", "oldaddon"})

    def test_unlisted_installed_addon_counts_as_enabled(self):
        (self.retail.account_dir / "ACCT1" / "Realm1" / "CharA" / "AddOns.txt").write_text(
            "Auctionator: enabled\n", encoding="utf-8")
        self.assertIn("disabledaddon", scan(self.retail).enabled)

    def test_character_without_addons_txt_enables_everything(self):
        self.assertEqual(scan(self.install.flavor("classic_era")).enabled, {"questie"})

    def test_groups_counts_and_events(self):
        with capture_events() as records:
            result = scan(self.retail)
        self.assertCountEqual([(g.account, g.owner_label, g.addon) for g in result.groups], [
            ("ACCT1", "account-wide", "Auctionator"), ("ACCT1", "account-wide", "Details"),
            ("ACCT1", "account-wide", "DisabledAddon"), ("ACCT1", "account-wide", "OldAddon"),
            ("ACCT1", "account-wide", "Uninstalled"), ("ACCT1", "Realm1/CharA", "Auctionator"),
            ("ACCT1", "Realm1/CharA", "Uninstalled"), ("ACCT2", "account-wide", "Details"),
            ("ACCT2", "Realm2/Chârb", "Details")])
        self.assertEqual((result.sv_files, result.accounts, result.characters), (14, 2, 2))
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "scan.started")
        self.assertIn("scan.addons", names)
        self.assertIn("scan.warning", names)
        completed = [r for r in records if r["event"] == "scan.completed"][0]["data"]
        self.assertEqual((completed["groups"], completed["sv_files"], completed["installed"]), (9, 14, 4))

    def test_blizzard_and_non_sv_files_are_never_scanned(self):
        names = {f.name for g in scan(self.retail).groups for f in g.files}
        for never in ("Blizzard_Foo.lua", "notes.txt", "config-cache.wtf", "AddOns.txt"):
            self.assertNotIn(never, names)

    def test_stray_files_are_not_canonical(self):
        group = next(g for g in scan(self.retail).groups
                     if g.addon == "Auctionator" and g.character is None)
        self.assertEqual({f.name: f.canonical for f in group.files}, {
            "Auctionator.lua": True, "Auctionator.lua.bak": True,
            "Auctionator.lua.pre-schema8-20260926-103400": False})

    def test_empty_addons_folder_aborts(self):
        with self.assertRaises(ScanError):
            scan(self.install.flavor("anniversary"))


class AccountScopeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.install = WowInstall(build_wow_tree(Path(tmp.name) / "World of Warcraft"))
        self.retail = self.install.flavor("retail")

    def test_scoped_scan_uses_only_that_accounts_characters(self):
        with capture_events() as records:
            result = scan(self.retail, account="ACCT2")
        self.assertEqual(result.account, "ACCT2")
        self.assertEqual(result.enabled, {"auctionator"})
        self.assertCountEqual([(g.account, g.owner_label, g.addon) for g in result.groups], [
            ("ACCT2", "account-wide", "Details"), ("ACCT2", "Realm2/Chârb", "Details")])
        self.assertEqual((result.accounts, result.characters), (1, 1))
        proposal = evaluate(result, Criteria(), now=NOW)
        self.assertCountEqual([(i.owner_label, i.addon, i.reasons) for i in proposal.items], [
            ("account-wide", "Details", ["not_enabled"]), ("Realm2/Chârb", "Details", ["not_enabled"])])
        started = [r for r in records if r["event"] == "scan.started"][0]["data"]
        completed = [r for r in records if r["event"] == "scan.completed"][0]["data"]
        self.assertEqual((started["account"], completed["account"]), ("ACCT2", "ACCT2"))

    def test_scoped_scan_is_case_insensitive_and_unknown_raises(self):
        result = scan(self.retail, account="acct2")
        self.assertEqual(result.account, "ACCT2")
        self.assertEqual({g.account for g in result.groups}, {"ACCT2"})
        with self.assertRaises(ScanError) as ctx:
            scan(self.retail, account="nope")
        self.assertIn("Unknown account", str(ctx.exception))
        self.assertIn("available: ACCT1, ACCT2", str(ctx.exception))

    def test_all_accounts_unchanged(self):
        with capture_events() as records:
            result = scan(self.retail, account=None, progress=None)
        self.assertIsNone(result.account)
        self.assertEqual(result.enabled, {"auctionator", "details", "oldaddon"})
        self.assertEqual((len(result.groups), result.sv_files, result.accounts, result.characters), (9, 14, 2, 2))
        started = [r for r in records if r["event"] == "scan.started"][0]["data"]
        self.assertIsNone(started["account"])
