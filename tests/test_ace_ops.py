"""ops: staging changes on the byte-free model (spec §7)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import ops, scanner
from wowtools.tools.ace_profiles.ops import CopyOf, Original


class OpsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_ace_tree(Path(tmp.name) / "wow")
        self.scan = scanner.ScanResult([scanner.scan_flavor(WowInstall(root).flavor("_retail_"), account="ACCT1")])
        self.staging = ops.Staging.from_scan(self.scan)

    def key(self, sv_name):
        return next(k for k in self.staging.states if k.sv_name == sv_name)

    def st(self, sv_name):
        return self.staging.state(self.key(sv_name))

    def test_fresh_state_is_unchanged(self):
        state = self.st("KickCDDB")
        self.assertFalse(state.changed)
        self.assertEqual(state.names(), ["Default", "Backup"])
        self.assertEqual(state.leftovers, frozenset({"Gone - Realm1"}))
        self.assertEqual(self.staging.summary().total, 0)

    def test_delete_reassigns_users_to_target(self):
        k = self.key("ElvDB")
        result = self.staging.delete({k: ["Healer"]}, "Default")
        self.assertTrue(result.ok)
        state = self.st("ElvDB")
        self.assertEqual(state.names(), ["Default"])
        self.assertEqual(state.keys["Mierin - Khaz Modan"], "Default")
        self.assertEqual(state.lds[("Kaelys - Realm1", 2)], "Default")
        changes = state.changes()
        self.assertEqual(changes.deleted, ["Healer"])
        self.assertEqual(changes.reassigned, [("Mierin - Khaz Modan", "Healer", "Default")])
        self.assertEqual(changes.lds, [("Kaelys - Realm1", 2, "Healer", "Default")])

    def test_delete_refuses_target_in_selection(self):
        k = self.key("ElvDB")
        result = self.staging.delete({k: ["Default", "Healer"]}, "Default")
        self.assertFalse(result.ok)
        self.assertEqual(result.refused[0][0], k)
        self.assertFalse(self.st("ElvDB").changed)

    def test_delete_to_a_missing_target_notes_it(self):
        k = self.key("HandyNotesDB")
        result = self.staging.delete({k: ["Kaelys - Realm1"]}, "Default")
        self.assertTrue(result.ok)
        self.assertTrue(any("next login" in n for n in result.notes))
        self.assertTrue(self.st("HandyNotesDB").missing("Default"))

    def test_assign_and_noop(self):
        k = self.key("HandyNotesDB")
        self.staging.assign({k: ["Kaelys - Realm1"]}, "Unused - Realm1")
        state = self.st("HandyNotesDB")
        self.assertEqual(state.users("Unused - Realm1"), ["Kaelys - Realm1"])
        self.staging.assign({k: ["Kaelys - Realm1"]}, "Kaelys - Realm1")
        self.assertFalse(self.st("HandyNotesDB").changed)

    def test_rename_moves_users_and_keeps_order(self):
        k = self.key("ElvDB")
        self.assertTrue(self.staging.rename(k, "Healer", "Heals").ok)
        state = self.st("ElvDB")
        self.assertEqual(state.names(), ["Default", "Heals"])
        self.assertEqual(state.profiles["Heals"], Original("Healer"))
        self.assertEqual(state.keys["Mierin - Khaz Modan"], "Heals")
        self.assertEqual(state.lds[("Kaelys - Realm1", 2)], "Heals")
        self.assertEqual(state.changes().renamed, [("Healer", "Heals")])

    def test_rename_refusals(self):
        k = self.key("ElvDB")
        self.assertFalse(self.staging.rename(k, "Healer", "Default").ok)
        self.assertFalse(self.staging.rename(k, "Nope", "X").ok)
        self.assertFalse(self.staging.rename(k, "Healer", "").ok)
        self.assertFalse(self.staging.rename(k, "Healer", "bad\nname").ok)

    def test_rename_missing_profile_only_moves_users(self):
        k = self.key("StockDB")
        self.assertTrue(self.staging.rename(k, "Gone", "Default").ok)
        state = self.st("StockDB")
        self.assertEqual(state.keys["Kaelys - Realm1"], "Default")
        self.assertEqual(state.profiles, {})

    def test_copy_then_rename_then_delete_source(self):
        k = self.key("ElvDB")
        self.assertTrue(self.staging.copy(k, "Healer", "Healer copy").ok)
        self.assertTrue(self.staging.rename(k, "Healer copy", "Tank").ok)
        self.assertTrue(self.staging.delete({k: ["Healer"]}, "Tank").ok)
        state = self.st("ElvDB")
        self.assertEqual(state.profiles, {"Default": Original("Default"), "Tank": CopyOf("Healer")})
        self.assertEqual(state.keys["Mierin - Khaz Modan"], "Tank")
        changes = state.changes()
        self.assertEqual(changes.deleted, ["Healer"])
        self.assertEqual(changes.copied, [("Healer", "Tank")])

    def test_copy_refusals(self):
        k = self.key("StockDB")
        self.assertFalse(self.staging.copy(k, "Gone", "X").ok)  # missing: no data to copy
        k = self.key("ElvDB")
        self.assertFalse(self.staging.copy(k, "Healer", "Default").ok)

    def test_remove_leftovers_only_removes_leftovers(self):
        k = self.key("KickCDDB")
        result = self.staging.remove_leftovers({k: ["Gone - Realm1", "Kaelys - Realm1"]})
        state = self.st("KickCDDB")
        self.assertIsNone(state.keys["Gone - Realm1"])
        self.assertEqual(state.keys["Kaelys - Realm1"], "Default")
        self.assertEqual(state.changes().removed, ["Gone - Realm1"])
        self.assertTrue(result.notes)

    def test_quick_actions(self):
        keys = [self.key("HandyNotesDB"), self.key("ElvDB")]
        self.staging.everyone_to_default(keys)
        self.assertEqual(set(self.st("HandyNotesDB").keys.values()), {"Default"})
        self.staging.keep_only_default(keys)
        self.assertEqual(self.st("HandyNotesDB").names(), ["Default"])
        self.assertEqual(self.st("ElvDB").names(), ["Default"])

    def test_locked_addon_is_refused(self):
        staging = ops.Staging.from_scan(self.scan, locked=lambda addon: addon == "ElvUI")
        k = next(k for k in staging.states if k.sv_name == "ElvDB")
        result = staging.delete({k: ["Healer"]}, "Default")
        self.assertFalse(result.ok)
        self.assertIn("blacklisted", result.refused[0][1])

    def test_summary_and_discard(self):
        self.staging.delete({self.key("ElvDB"): ["Healer"]}, "Default")
        self.staging.remove_leftovers({self.key("KickCDDB"): ["Gone - Realm1"]})
        summary = self.staging.summary()
        self.assertEqual((summary.deleted, summary.reassigned, summary.removed, summary.lds, summary.files),
                         (1, 1, 1, 1, 2))
        self.assertEqual(summary.total, 4)
        self.staging.discard()
        self.assertEqual(self.staging.summary().total, 0)

    def test_change_lines(self):
        k = self.key("ElvDB")
        self.staging.rename(k, "Healer", "Heals")
        self.assertIn('rename profile "Healer" to "Heals"', self.st("ElvDB").changes().lines())

    def test_valid_name(self):
        self.assertIsNone(ops.valid_name("My \"Main\" - x"))
        for bad in ("", "   ", "a\tb", "x" * 101):
            with self.subTest(bad=bad):
                self.assertIsNotNone(ops.valid_name(bad))
