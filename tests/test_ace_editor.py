"""editor.apply_flavor: guard, recheck, lock probe, snapshot, originals zip, atomic writes, roll-back (spec §9)."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_ace_tree
from wowtools.core.events import capture_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import editor, luasv, model, ops, scanner
from wowtools.tools.ace_profiles.journal import ProfileJournal, read_profile_journal

WHEN = datetime(2026, 10, 4, 12, 0, 0)


class EditorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_ace_tree(self.tmp / "wow")
        self.flavor = WowInstall(self.wow).flavor("_retail_")
        self.root = self.tmp / "out" / "ace-profiles"
        self.scan = scanner.ScanResult([scanner.scan_flavor(self.flavor, account="ACCT1")])
        self.staging = ops.Staging.from_scan(self.scan)

    def key(self, sv_name):
        return next(k for k in self.staging.states if k.sv_name == sv_name)

    def stage_two_files(self):
        self.staging.delete({self.key("ElvDB"): ["Healer"]}, "Default")
        self.staging.remove_leftovers({self.key("KickCDDB"): ["Gone - Realm1"]})

    def journal(self):
        journal = ProfileJournal(self.tmp / "journal" / "journal-20261004-120000.jsonl", {"kind": "apply"})
        self.addCleanup(journal.close)
        return journal

    def apply(self, *, dry_run=False, journal=None, **kwargs):
        return editor.apply_flavor(self.flavor, self.staging.changed(), root=self.root,
                                   journal=None if dry_run else (journal or self.journal()), dry_run=dry_run,
                                   keep_snapshots=2, account="ACCT1", now=WHEN, **kwargs)

    def test_dry_run_writes_nothing(self):
        self.stage_two_files()
        before = {p: p.read_bytes() for p in self.flavor.wtf_dir.rglob("*.lua")}
        result = self.apply(dry_run=True)
        self.assertEqual(len(result.would_edit), 2)
        self.assertEqual({p: p.read_bytes() for p in self.flavor.wtf_dir.rglob("*.lua")}, before)
        self.assertFalse(self.root.exists())

    def test_apply_writes_snapshots_backs_up_and_journals(self):
        self.stage_two_files()
        journal = self.journal()
        elv = self.key("ElvDB").path
        original = elv.read_bytes()
        result = self.apply(journal=journal)
        journal.finish()
        journal.close()
        self.assertEqual(len(result.edited), 2)
        self.assertNotIn(b'["Healer"]', elv.read_bytes())
        self.assertEqual(result.snapshot.parent, self.root / "snapshots")
        self.assertTrue(result.snapshot.name.startswith("snapshot-retail-20261004-120000"))
        self.assertEqual(result.backup_zip.name, "edited-retail-ACCT1-20261004-120000.zip")
        with zipfile.ZipFile(result.backup_zip) as zf:
            self.assertEqual(zf.read("WTF/Account/ACCT1/SavedVariables/ElvUI.lua"), original)
        entries = read_profile_journal(journal.path).entries
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["sha_before"], scanner.sha256_of(original))
        self.assertEqual(entries[0]["sha_after"], scanner.sha256_of(elv.read_bytes()))
        self.assertIsNone(editor.read_marker(self.root))

    def test_file_changed_since_scan_is_skipped_others_applied(self):
        self.stage_two_files()
        kick = self.key("KickCDDB").path
        kick.write_bytes(kick.read_bytes() + b"\r\n")
        with capture_events() as events:
            result = self.apply()
        self.assertEqual([o.file.addon for o in result.skipped], ["KickCD"])
        self.assertIn("changed since the scan", result.skipped[0].detail)
        self.assertEqual([o.file.addon for o in result.edited], ["ElvUI"])
        self.assertIn("ace.file_changed", [e["event"] for e in events])

    def test_failure_mid_run_rolls_back_written_files(self):
        self.stage_two_files()
        self.staging.copy(self.key("HandyNotesDB"), "Unused - Realm1", "Spare")
        paths = sorted({s.file.path for s in self.staging.changed()}, key=lambda p: p.name.casefold())
        before = {p: p.read_bytes() for p in paths}
        calls = []

        def flaky(path, data):
            calls.append(path)
            if len(calls) == 3:
                raise OSError("disk full")
            atomic_write_bytes(path, data)
        journal = self.journal()
        with self.assertRaises(editor.ApplyError) as caught:
            self.apply(journal=journal, write=flaky)
        journal.close()
        self.assertEqual({p: p.read_bytes() for p in paths}, before)
        self.assertEqual(len(caught.exception.rolled_back), 2)
        self.assertEqual(caught.exception.files_left, [])
        self.assertIsNone(editor.read_marker(self.root))
        self.assertEqual(read_profile_journal(journal.path).entries if journal.path.exists() else [], [])

    def test_verify_failure_stops_before_anything_is_written(self):
        self.stage_two_files()
        before = {p: p.read_bytes() for p in self.flavor.wtf_dir.rglob("*.lua")}
        with patch("wowtools.tools.ace_profiles.editor.verify_edit", return_value=["broken"]), \
                self.assertRaises(editor.ApplyError):
            self.apply()
        self.assertEqual({p: p.read_bytes() for p in self.flavor.wtf_dir.rglob("*.lua")}, before)
        self.assertFalse((self.root / "snapshots").exists())

    def test_locked_file_refuses_before_snapshot(self):
        self.stage_two_files()
        with patch("wowtools.tools.ace_profiles.editor.probe_lock", return_value="in use"), \
                self.assertRaises(editor.ApplyError) as caught:
            self.apply()
        self.assertIn("locked", str(caught.exception))
        self.assertFalse((self.root / "snapshots").exists())

    def test_marker_is_left_when_put_back_fails(self):
        self.stage_two_files()
        calls = []

        def broken(path, data):
            calls.append(path)
            if len(calls) == 1:
                atomic_write_bytes(path, data)
                return
            raise OSError("gone wrong")
        with patch("wowtools.tools.ace_profiles.editor.restore_original", side_effect=OSError("no")), \
                self.assertRaises(editor.ApplyError) as caught:
            self.apply(write=broken)
        self.assertTrue(caught.exception.files_left)
        marker = editor.read_marker(self.root)
        self.assertIsNotNone(marker)
        self.assertEqual(marker.flavor, "_retail_")
        self.assertTrue(marker.zip.exists())

    def test_guard_refuses_a_path_outside_saved_variables(self):
        self.stage_two_files()
        state = self.staging.changed()[0]
        moved = scanner.SvFile(self.flavor.account_dir / "ACCT1" / "x.lua", state.file.flavor, "ACCT1", None,
                               0, 0.0, "")
        bad = ops.DbState(state.key, moved, state.db, state.leftovers, state.keys, state.profiles, state.lds)
        with self.assertRaises(editor.ApplyError):
            editor.apply_flavor(self.flavor, [bad], root=self.root, journal=self.journal(), dry_run=False,
                                keep_snapshots=2, now=WHEN)

    def test_prunes_old_snapshots(self):
        folder = self.root / "snapshots"
        folder.mkdir(parents=True)
        for day in ("01", "02", "03"):
            (folder / f"snapshot-retail-202610{day}-000000.zip").write_bytes(b"x")
        self.stage_two_files()
        result = self.apply()
        self.assertEqual(len(result.pruned), 2)
        self.assertEqual(len(list(folder.iterdir())), 2)

    def test_written_file_reads_back_as_acedb(self):
        self.stage_two_files()
        self.apply()
        data = self.key("ElvDB").path.read_bytes()
        dbs, _ = model.find_dbs(luasv.parse(data, model.ace_descend), data)
        self.assertEqual([db.sv_name for db in dbs], ["ElvDB", "ElvPrivateDB"])

    @unittest.skipIf(os.name == "nt", "chmod read-only does not stop a rename on Windows")
    def test_nothing_staged_does_nothing(self):
        result = editor.apply_flavor(self.flavor, [], root=self.root, journal=self.journal(), dry_run=False,
                                     keep_snapshots=2, now=WHEN)
        self.assertEqual(result.outcomes, [])
        self.assertFalse(self.root.exists())
