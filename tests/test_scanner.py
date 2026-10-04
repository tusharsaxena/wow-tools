from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import NOW, build_solo_tree, build_wow_tree
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
        completed = next(r for r in records if r["event"] == "scan.completed")["data"]
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
        started = next(r for r in records if r["event"] == "scan.started")["data"]
        completed = next(r for r in records if r["event"] == "scan.completed")["data"]
        self.assertEqual((started["account"], completed["account"]), ("ACCT2", "ACCT2"))

    def test_scoped_scan_is_case_insensitive_and_unknown_raises(self):
        result = scan(self.retail, account="acct2")
        self.assertEqual(result.account, "ACCT2")
        self.assertEqual({g.account for g in result.groups}, {"ACCT2"})
        with self.assertRaises(ScanError) as ctx:
            scan(self.retail, account="nope")
        self.assertIn("Unknown account", str(ctx.exception))
        self.assertIn("available: ACCT1, ACCT2", str(ctx.exception))

    def test_account_without_characters_enables_every_installed_addon(self):
        solo = WowInstall(build_solo_tree(Path(self.install.root.parent) / "Solo WoW")).flavor("retail")
        with capture_events() as records:
            result = scan(solo, account="SOLO")
        self.assertEqual(result.enabled, {"details", "weakauras"})
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("no character folders", result.warnings[0].message)
        self.assertIn("SOLO", result.warnings[0].path)
        warned = [r for r in records if r["event"] == "scan.warning"]
        self.assertEqual(len(warned), 1)

    def test_lock_probe_leftover_is_not_a_stray_copy(self):
        sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        (sv / "Details.lua").rename(sv / "Details.lua.wowtools-lockcheck")  # a crash between the probe's renames
        result = scan(self.retail)
        names = [f.path.name for g in result.groups for f in g.files]
        self.assertNotIn("Details.lua.wowtools-lockcheck", names)
        leftovers = [w for w in result.warnings if w.path.endswith("Details.lua.wowtools-lockcheck")]
        self.assertEqual(len(leftovers), 1)
        self.assertIn("lock check", leftovers[0].message)
        proposal = evaluate(result, Criteria(), now=NOW)
        self.assertFalse(any(f.path.name.endswith(".wowtools-lockcheck")
                             for item in proposal.items for f in item.files))

    def test_all_accounts_unchanged(self):
        with capture_events() as records:
            result = scan(self.retail, account=None, progress=None)
        self.assertIsNone(result.account)
        self.assertEqual(result.enabled, {"auctionator", "details", "oldaddon"})
        self.assertEqual((len(result.groups), result.sv_files, result.accounts, result.characters), (9, 14, 2, 2))
        started = next(r for r in records if r["event"] == "scan.started")["data"]
        self.assertIsNone(started["account"])


class ScanProgressTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.install = WowInstall(build_wow_tree(Path(tmp.name) / "World of Warcraft"))
        self.retail = self.install.flavor("retail")

    def test_scan_progress_reports_every_folder(self):
        calls = []
        scan(self.retail, progress=lambda current, total, label: calls.append((current, total, label)))
        # Retail in the fixture: ACCT1, ACCT1 · Realm1/CharA, ACCT2, ACCT2 · Realm2/Chârb.
        self.assertEqual(calls[0], (0, 4, "Reading AddOns"))
        self.assertEqual([c[0] for c in calls], [0, 1, 2, 3, 4])
        self.assertTrue(all(c[1] == 4 for c in calls))
        self.assertEqual(calls[-1][0], calls[-1][1])
        self.assertEqual([c[2] for c in calls[1:]],
                         ["ACCT1", "ACCT1 · Realm1/CharA", "ACCT2", "ACCT2 · Realm2/Chârb"])

    def test_scan_progress_scoped_counts_only_that_account(self):
        calls = []
        scan(self.retail, account="ACCT2", progress=lambda *args: calls.append(args))
        self.assertEqual([(c[0], c[1]) for c in calls], [(0, 2), (1, 2), (2, 2)])

    def test_scan_progress_callback_errors_are_ignored(self):
        calls = []

        def boom(current, total, label):
            calls.append(current)
            raise RuntimeError("callback broke")

        result = scan(self.retail, progress=boom)
        self.assertEqual(calls, [0, 1, 2, 3, 4])
        self.assertEqual((len(result.groups), result.sv_files), (9, 14))
