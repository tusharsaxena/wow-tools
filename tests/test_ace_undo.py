"""undo_run and recover: put files back only when they are still what the run wrote (spec §10)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_ace_tree
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.core.journal import read_journal
from wowtools.tools.ace_profiles import editor, multi, ops, scanner, undo
from wowtools.tools.ace_profiles.journal import latest_undoable

WHEN = datetime(2026, 10, 4, 12, 0, 0)


class UndoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_ace_tree(self.tmp / "wow")
        self.flavor = WowInstall(self.wow).flavor("_retail_")
        self.root = self.tmp / "out"
        self.journals = self.tmp / "journal"
        scan = scanner.ScanResult([scanner.scan_flavor(self.flavor, account="ACCT1")])
        self.staging = ops.Staging.from_scan(scan)
        elv = next(k for k in self.staging.states if k.sv_name == "ElvDB")
        kick = next(k for k in self.staging.states if k.sv_name == "KickCDDB")
        self.elv, self.kick = elv.path, kick.path
        self.before = {p: p.read_bytes() for p in (self.elv, self.kick)}
        self.staging.delete({elv: ["Healer"]}, "Default")
        self.staging.remove_leftovers({kick: ["Gone - Realm1"]})
        multi.apply_flavors([(self.flavor, self.staging.changed())], root=self.root, journal_dir=self.journals,
                            keep_journals=10, keep_snapshots=2, dry_run=False, account="ACCT1", now=WHEN)
        self.journal = latest_undoable(self.journals)

    def undo(self, **kwargs):
        return undo.undo_run(self.journal, wow_root=self.wow, root=self.root, keep_snapshots=2, now=WHEN, **kwargs)

    def test_undo_restores_both_files(self):
        result = self.undo()
        self.assertEqual(len(result.restored), 2)
        self.assertEqual({p: p.read_bytes() for p in (self.elv, self.kick)}, self.before)
        self.assertIsNotNone(read_journal(self.journal).undone)
        self.assertIsNone(latest_undoable(self.journals))
        self.assertTrue(result.snapshots)

    def test_file_changed_since_is_skipped_not_overwritten(self):
        self.kick.write_bytes(self.kick.read_bytes() + b"-- saved by WoW\r\n")
        changed = self.kick.read_bytes()
        result = self.undo()
        self.assertEqual([o.rel.rsplit("/", 1)[-1] for o in result.skipped], ["KickCD.lua"])
        self.assertIn("changed since", result.skipped[0].detail)
        self.assertEqual(self.kick.read_bytes(), changed)
        self.assertEqual(self.elv.read_bytes(), self.before[self.elv])

    def test_refused_while_wow_runs(self):
        with self.assertRaises(undo.WowRunning):
            self.undo(wow_check=lambda: ["Wow.exe"])
        self.assertNotEqual(self.elv.read_bytes(), self.before[self.elv])

    def test_missing_zip_fails_and_journal_stays_undoable(self):
        for zip_path in (self.root / "edited").iterdir():
            zip_path.unlink()
        result = self.undo()
        self.assertEqual(len(result.failed), 2)
        self.assertEqual(latest_undoable(self.journals), self.journal)

    def test_destination_refuses_escapes(self):
        self.assertIsNone(undo.destination(self.wow, "_retail_", "../x.lua"))
        self.assertIsNone(undo.destination(self.wow, "_retail_", "Interface/AddOns/x.lua"))
        self.assertIsNone(undo.destination(self.wow, "_retail_", "WTF/Account/A/x.lua"))
        self.assertEqual(undo.destination(self.wow, "_retail_", "WTF/Account/A/SavedVariables/x.lua"),
                         self.wow / "_retail_" / "WTF" / "Account" / "A" / "SavedVariables" / "x.lua")


class RecoverTest(unittest.TestCase):
    def test_recover_puts_back_only_changed_files_and_clears_marker(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        wow = build_ace_tree(base / "wow")
        flavor = WowInstall(wow).flavor("_retail_")
        root = base / "out"
        scan = scanner.ScanResult([scanner.scan_flavor(flavor, account="ACCT1")])
        staging = ops.Staging.from_scan(scan)
        elv = next(k for k in staging.states if k.sv_name == "ElvDB")
        original = elv.path.read_bytes()
        staging.delete({elv: ["Healer"]}, "Default")
        editor.apply_flavor(flavor, staging.changed(), root=root, journal=None, dry_run=True, keep_snapshots=2)
        from wowtools.core.backup import BackupEntry, create_backup
        zip_path = create_backup([BackupEntry(elv.path)], flavor.path, root / "edited" / "edited-x.zip", {})
        elv.path.write_bytes(b"what the run wrote")
        rel = "WTF/Account/ACCT1/SavedVariables/ElvUI.lua"
        marker = editor.Marker("_retail_", flavor.path, zip_path, {rel: scanner.sha256_of(original)},
                               "now", 1, "1.0.0", {rel: scanner.sha256_of(b"what the run wrote")})
        editor.write_marker(root, marker)
        result = undo.recover(marker, root=root)
        self.assertEqual(len(result.restored), 1)
        self.assertEqual(elv.path.read_bytes(), original)
        self.assertIsNone(editor.read_marker(root))

    def test_recover_leaves_files_the_run_did_not_write(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        wow = build_ace_tree(base / "wow")
        flavor = WowInstall(wow).flavor("_retail_")
        root = base / "out"
        staging = ops.Staging.from_scan(scanner.ScanResult([scanner.scan_flavor(flavor, account="ACCT1")]))
        key = {k.sv_name: k for k in staging.states}
        staging.delete({key["ElvDB"]: ["Healer"]}, "Default")
        staging.remove_leftovers({key["KickCDDB"]: ["Gone - Realm1"]})
        staging.copy(key["HandyNotesDB"], "Unused - Realm1", "Spare")
        order = list(dict.fromkeys(s.file.path for s in staging.changed()))
        self.assertEqual(len(order), 3)
        first, victim, last = order
        originals = {p: p.read_bytes() for p in order}

        def write(path, data):
            if path == first:
                victim.write_bytes(victim.read_bytes() + b"-- WoW saved this\r\n")  # another program, mid-run
                atomic_write_bytes(path, data)
            else:
                raise OSError("disk full")
        journal = _journal(base)
        self.addCleanup(journal.close)
        with patch("wowtools.tools.ace_profiles.editor.restore_original", side_effect=OSError("no")), \
                self.assertRaises(editor.ApplyError):
            editor.apply_flavor(flavor, staging.changed(), root=root, journal=journal, dry_run=False,
                                keep_snapshots=2, now=WHEN, write=write)
        saved = victim.read_bytes()
        marker = editor.read_marker(root)
        self.assertIsNotNone(marker)
        first.write_bytes(first.read_bytes())  # unchanged: still what the run wrote
        result = undo.recover(marker, root=root)
        self.assertEqual(first.read_bytes(), originals[first])
        self.assertEqual(victim.read_bytes(), saved)  # the other program's save is kept
        self.assertEqual(last.read_bytes(), originals[last])
        self.assertEqual([o.rel.rsplit("/", 1)[-1] for o in result.restored], [first.name])
        self.assertEqual([o.rel.rsplit("/", 1)[-1] for o in result.skipped], [victim.name])
        self.assertIn("changed since", result.skipped[0].detail)

    def test_recover_leaves_a_file_wow_saved_after_the_run_wrote_it(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        wow = build_ace_tree(base / "wow")
        flavor = WowInstall(wow).flavor("_retail_")
        sv = flavor.path / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "ElvUI.lua"
        original = sv.read_bytes()
        from wowtools.core.backup import BackupEntry, create_backup
        zip_path = create_backup([BackupEntry(sv)], flavor.path, base / "out" / "edited" / "edited-x.zip", {})
        rel = "WTF/Account/ACCT1/SavedVariables/ElvUI.lua"
        marker = editor.Marker("_retail_", flavor.path, zip_path, {rel: scanner.sha256_of(original)}, "now", 1,
                               "1.0.0", {rel: scanner.sha256_of(b"what the run wrote")})
        sv.write_bytes(b"what WoW saved after that")
        result = undo.recover(marker, root=base / "out")
        self.assertEqual(sv.read_bytes(), b"what WoW saved after that")
        self.assertEqual(len(result.skipped), 1)

    def _torn(self):
        """A marker for ElvUI.lua, which holds what the run wrote."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        wow = build_ace_tree(base / "wow")
        flavor = WowInstall(wow).flavor("_retail_")
        sv = flavor.path / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "ElvUI.lua"
        original = sv.read_bytes()
        from wowtools.core.backup import BackupEntry, create_backup
        zip_path = create_backup([BackupEntry(sv)], flavor.path, base / "out" / "edited" / "edited-x.zip", {})
        rel = "WTF/Account/ACCT1/SavedVariables/ElvUI.lua"
        marker = editor.Marker("_retail_", flavor.path, zip_path, {rel: scanner.sha256_of(original)}, "now", 1,
                               "1.0.0", {rel: scanner.sha256_of(b"what the run wrote")})
        editor.write_marker(base / "out", marker)
        sv.write_bytes(b"what the run wrote")
        return base / "out", marker, sv, original

    def test_recover_refused_while_wow_runs(self):
        root, marker, sv, _original = self._torn()
        with self.assertRaises(undo.WowRunning):
            undo.recover(marker, root=root, wow_check=lambda: ["Wow.exe"])
        self.assertEqual(sv.read_bytes(), b"what the run wrote")
        self.assertIsNotNone(editor.read_marker(root))

    def test_recover_refused_when_a_file_is_locked(self):
        root, marker, sv, _original = self._torn()
        with patch("wowtools.tools.ace_profiles.undo.probe_lock", return_value="in use"), \
                self.assertRaises(undo.UndoError):
            undo.recover(marker, root=root, wow_check=list)
        self.assertEqual(sv.read_bytes(), b"what the run wrote")
        self.assertIsNotNone(editor.read_marker(root))

    def test_recover_backs_up_the_wtf_folder_first(self):
        root, marker, sv, original = self._torn()
        result = undo.recover(marker, root=root, wow_check=list, now=WHEN)
        self.assertEqual(sv.read_bytes(), original)
        self.assertEqual(len(result.snapshots), 1)
        self.assertTrue(result.snapshots[0].is_file())


def _journal(base):
    from wowtools.tools.ace_profiles.journal import ProfileJournal
    return ProfileJournal(base / "journal" / "journal-20261004-120000.jsonl", {"kind": "apply"})
