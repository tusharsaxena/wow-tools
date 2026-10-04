from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup import undo as undo_module
from wowtools.tools.interface_backup.backup import back_up
from wowtools.tools.interface_backup.journal import latest_undoable, read_restore_journal
from wowtools.tools.interface_backup.restore import RestoreError, RestoreStopped, open_backup, plan_restore, restore
from wowtools.tools.interface_backup.scanner import scan_flavor
from wowtools.tools.interface_backup.undo import undo_restore

NOW = datetime(2026, 10, 4, 15, 30, 12)


def _symlink(test, target, link):
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        test.skipTest("symlinks not permitted here")


class UndoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavor = next(f for f in WowInstall(self.wow).flavors() if f.folder == "_retail_")
        self.retail = self.wow / "_retail_"
        self.root = self.tmp / "bk" / "interface-backup"
        self.journal_dir = self.wow / "wow-tools" / "interface-backup" / "journal"
        with capture_events():
            self.backup = back_up(scan_flavor(self.flavor, with_stats=False), self.root, keep=10, now=NOW).path

    def do_restore(self, parts=("Interface", "WTF")):
        plan = plan_restore(open_backup(self.backup), scan_flavor(self.flavor, with_stats=True), parts)
        with capture_events():
            return restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10)

    def undo(self, journal_path, **kw):
        with capture_events() as events:
            result = undo_restore(journal_path, wow_root=self.wow, root=self.root, **kw)
        return result, events

    def assert_refused(self, journal_path):
        with capture_events() as events, self.assertRaises(RestoreError):
            undo_restore(journal_path, wow_root=self.wow, root=self.root)
        failed = [e for e in events if e["event"] == "ibackup.undo_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["level"], "error")
        self.assertNotIn("ibackup.undo_started", [e["event"] for e in events])

    def rewrite_journal(self, path, edit_header=None, edit_entry=None):
        lines = path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        if edit_header is not None:
            edit_header(records[0])
        if edit_entry is not None:
            for record in records[1:]:
                if "action" in record:
                    edit_entry(record)
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def assert_no_staging(self):
        self.assertFalse(list(self.retail.glob("*.restoring")) + list(self.retail.glob("*.replaced")))

    def test_undo_puts_both_parts_back(self):
        (self.retail / "Interface" / "after.txt").write_text("after", encoding="utf-8")
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"mine")
        result = self.do_restore()
        self.assertFalse((self.retail / "Interface" / "after.txt").exists())
        stages = []
        undone, events = self.undo(result.journal_path, progress=lambda stage, *rest: stages.append(stage))
        self.assertTrue(undone.undo)
        self.assertTrue(undone.ok)
        self.assertEqual([p.kind for p in undone.parts], ["restored", "restored"])
        self.assertEqual(sorted(p.part for p in undone.parts), ["Interface", "WTF"])
        self.assertEqual(undone.backup, result.safety_zip)
        self.assertEqual((self.retail / "Interface" / "after.txt").read_text(encoding="utf-8"), "after")
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"mine")
        self.assert_no_staging()
        self.assertIsNone(latest_undoable(self.journal_dir))  # never offered again
        self.assertIsNotNone(read_restore_journal(result.journal_path).undone)
        names = [e["event"] for e in events]
        self.assertEqual(names[0], "ibackup.undo_started")
        self.assertEqual(names[-1], "ibackup.undo_completed")
        self.assertEqual(names.count("ibackup.part_restored"), 2)
        self.assertTrue(all(e["data"]["undo"] for e in events if e["event"] == "ibackup.part_restored"))
        for stage in ("verify", "extract", "swap", "cleanup"):
            self.assertIn(stage, stages)

    def test_newest_part_first(self):
        result = self.do_restore()
        undone, _ = self.undo(result.journal_path)
        self.assertEqual([p.part for p in undone.parts], ["WTF", "Interface"])

    def test_part_that_did_not_exist_is_removed(self):
        shutil.rmtree(self.retail / "Interface")
        result = self.do_restore(("Interface",))
        self.assertTrue((self.retail / "Interface").exists())
        undone, _ = self.undo(result.journal_path)
        self.assertEqual([p.kind for p in undone.parts], ["restored"])
        self.assertFalse(os.path.lexists(self.retail / "Interface"))
        self.assert_no_staging()
        self.assertTrue((self.retail / "WTF" / "Config.wtf").exists())

    def test_part_that_did_not_exist_and_is_gone_again(self):
        shutil.rmtree(self.retail / "Interface")
        result = self.do_restore(("Interface",))
        shutil.rmtree(self.retail / "Interface")
        undone, _ = self.undo(result.journal_path)
        self.assertEqual([p.kind for p in undone.parts], ["restored"])
        self.assertFalse(os.path.lexists(self.retail / "Interface"))

    def test_created_part_turned_link_is_left_alone(self):
        shutil.rmtree(self.retail / "Interface")
        result = self.do_restore(("Interface",))
        repo = self.tmp / "repo"
        shutil.move(str(self.retail / "Interface"), str(repo))
        _symlink(self, repo, self.retail / "Interface")
        undone, _ = self.undo(result.journal_path)
        self.assertEqual(undone.parts[0].kind, "rolled_back")
        self.assertTrue(os.path.islink(self.retail / "Interface"))
        self.assertTrue((repo / "AddOns" / "Details" / "core.lua").exists())

    def test_kept_link_survives_undo(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "dev.lua").write_text("dev", encoding="utf-8")
        link = self.retail / "Interface" / "AddOns" / "Dev"
        _symlink(self, repo, link)
        result = self.do_restore(("Interface",))
        self.assertTrue(os.path.islink(link))
        undone, _ = self.undo(result.journal_path)
        self.assertTrue(undone.ok)
        self.assertTrue(os.path.islink(link))
        self.assertEqual((repo / "dev.lua").read_text(encoding="utf-8"), "dev")

    def replace_details_with_link(self):
        """AddOns/Details (real files in the backup) becomes a link to a dev checkout: the restore removes it."""
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "dev.lua").write_text("dev", encoding="utf-8")
        link = self.retail / "Interface" / "AddOns" / "Details"
        shutil.rmtree(link)
        _symlink(self, os.fspath(repo), link)
        return repo, link

    def test_link_removed_by_the_restore_comes_back_on_undo(self):
        repo, link = self.replace_details_with_link()
        result = self.do_restore(("Interface",))
        self.assertFalse(os.path.islink(link))  # the backup's real Details folder took its place
        entries = read_restore_journal(result.journal_path).entries
        removed = [e for e in entries if e.get("action") == "link_removed"]
        self.assertEqual(removed, [{"action": "link_removed", "part": "Interface", "rel": "AddOns/Details",
                                    "target": os.fspath(repo), "junction": False}])
        undone, _ = self.undo(result.journal_path)
        self.assertTrue(undone.ok)
        self.assertEqual([p.kind for p in undone.parts], ["restored"])
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), os.fspath(repo))
        self.assertEqual((link / "dev.lua").read_text(encoding="utf-8"), "dev")

    def test_link_that_cannot_be_made_again_fails_the_part(self):
        repo, link = self.replace_details_with_link()
        result = self.do_restore(("Interface",))

        def refuse(target, path, *, junction):
            raise PermissionError(1, "not allowed")

        with patch.object(undo_module, "make_link", refuse):
            undone, events = self.undo(result.journal_path)
        self.assertFalse(undone.ok)
        self.assertEqual(undone.parts[0].kind, "failed")
        self.assertIn("AddOns/Details", undone.parts[0].reason)
        self.assertIn(os.fspath(repo), undone.parts[0].reason)
        self.assertFalse(os.path.lexists(link))
        self.assertIsNone(latest_undoable(self.journal_dir))  # the folder was put back: undone
        self.assertTrue(any(e["event"] == "ibackup.undo_failed" for e in events))

    def test_damaged_link_entry_refused(self):
        self.replace_details_with_link()
        result = self.do_restore(("Interface",))

        def escape(entry):
            if entry["action"] == "link_removed":
                entry["rel"] = "../../outside"

        self.rewrite_journal(result.journal_path, edit_entry=escape)
        self.assert_refused(result.journal_path)

    def test_missing_safety_zip_refused(self):
        result = self.do_restore(("WTF",))
        result.safety_zip.unlink()
        self.assert_refused(result.journal_path)
        self.assertEqual(latest_undoable(self.journal_dir), result.journal_path)

    def test_damaged_safety_zip_refused_nothing_touched(self):
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"mine")
        result = self.do_restore(("WTF",))
        with zipfile.ZipFile(result.safety_zip) as zf:
            info = zf.getinfo("WTF/Config.wtf")
        data = bytearray(result.safety_zip.read_bytes())
        name_len, extra_len = struct.unpack("<HH", data[info.header_offset + 26:info.header_offset + 30])
        data[info.header_offset + 30 + name_len + extra_len] ^= 0xFF  # first data byte: open works, verify fails
        result.safety_zip.write_bytes(bytes(data))
        before = (self.retail / "WTF" / "Config.wtf").read_bytes()
        self.assert_refused(result.journal_path)
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), before)
        self.assertEqual(latest_undoable(self.journal_dir), result.journal_path)

    def test_journal_from_another_wow_folder_refused(self):
        result = self.do_restore(("WTF",))

        def elsewhere(header):
            header["flavor_path"] = to_stored(self.tmp / "Other" / "_retail_")

        self.rewrite_journal(result.journal_path, edit_header=elsewhere)
        self.assert_refused(result.journal_path)

    def test_journal_naming_an_unknown_flavor_refused(self):
        result = self.do_restore(("WTF",))

        def other(header):
            header["flavor"] = "_ptr_"

        self.rewrite_journal(result.journal_path, edit_header=other)
        self.assert_refused(result.journal_path)

    def test_safety_zip_outside_backup_root_refused(self):
        result = self.do_restore(("WTF",))
        moved = self.tmp / result.safety_zip.name
        shutil.copy2(result.safety_zip, moved)

        def point_elsewhere(entry):
            if entry["action"] == "safety_backup":
                entry["zip"] = to_stored(moved)

        self.rewrite_journal(result.journal_path, edit_entry=point_elsewhere)
        self.assert_refused(result.journal_path)

    def test_safety_zip_that_is_an_ordinary_backup_refused(self):
        result = self.do_restore(("WTF",))

        def point_at_backup(entry):
            if entry["action"] == "safety_backup":
                entry["zip"] = to_stored(self.backup)

        self.rewrite_journal(result.journal_path, edit_entry=point_at_backup)
        self.assert_refused(result.journal_path)

    def test_unknown_part_refused(self):
        result = self.do_restore(("WTF",))

        def rename_part(entry):
            if entry["action"] == "replaced":
                entry["part"] = "Cache"

        self.rewrite_journal(result.journal_path, edit_entry=rename_part)
        self.assert_refused(result.journal_path)
        self.assertTrue((self.wow / "_retail_" / "WTF").exists())

    def test_existed_part_missing_from_safety_zip_refused(self):
        shutil.rmtree(self.retail / "Interface")
        result = self.do_restore(("Interface",))

        def claim_existed(entry):
            if entry["action"] == "replaced":
                entry["existed"] = True

        self.rewrite_journal(result.journal_path, edit_entry=claim_existed)
        self.assert_refused(result.journal_path)
        self.assertTrue((self.retail / "Interface").exists())

    def test_already_undone_refused(self):
        result = self.do_restore(("WTF",))
        self.undo(result.journal_path)
        self.assert_refused(result.journal_path)

    def test_leftover_folder_refused(self):
        result = self.do_restore(("WTF",))
        (self.retail / "Interface.replaced").mkdir()
        (self.retail / "WTF" / "since.txt").write_text("s", encoding="utf-8")
        self.assert_refused(result.journal_path)
        self.assertTrue((self.retail / "WTF" / "since.txt").exists())

    def test_unreadable_journal_refused(self):
        self.assert_refused(self.journal_dir / "journal-20260101-000000.jsonl")

    def test_swap_failure_rolls_back_and_stays_undoable(self):
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"mine")
        result = self.do_restore(("WTF",))
        real = os.rename

        def flaky(src, dst):
            if str(src).endswith("WTF.restoring"):
                raise PermissionError(13, "locked by WoW")
            real(src, dst)

        undone, events = self.undo(result.journal_path, rename=flaky)
        self.assertEqual(undone.parts[0].kind, "rolled_back")
        self.assertFalse(undone.ok)
        self.assertIn("locked by WoW", undone.parts[0].reason)
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"SET a 1\n")
        self.assert_no_staging()
        self.assertIn("ibackup.undo_failed", [e["event"] for e in events])
        completed = next(e for e in events if e["event"] == "ibackup.undo_completed")
        self.assertEqual(completed["level"], "warning")
        # nothing changed: the same undo is offered again (WoW closed, try again)
        self.assertEqual(latest_undoable(self.journal_dir), result.journal_path)
        again, _ = self.undo(result.journal_path)
        self.assertTrue(again.ok)
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"mine")

    def test_one_part_failing_still_marks_undone(self):
        result = self.do_restore()
        real = os.rename

        def flaky(src, dst):
            if str(src).endswith("Interface.restoring"):
                raise PermissionError(13, "locked by WoW")
            real(src, dst)

        undone, _ = self.undo(result.journal_path, rename=flaky)
        self.assertEqual({p.part: p.kind for p in undone.parts}, {"WTF": "restored", "Interface": "rolled_back"})
        self.assertIsNone(latest_undoable(self.journal_dir))

    def test_unexpected_error_stops_with_the_finished_part(self):
        result = self.do_restore()
        real = undo_module.replace_part
        calls = []

        def second_fails(*args, **kwargs):
            calls.append(args[3])
            if len(calls) == 2:
                raise TypeError("boom")
            return real(*args, **kwargs)

        with patch.object(undo_module, "replace_part", second_fails), capture_events() as events, \
                self.assertRaises(RestoreStopped) as caught:
            undo_restore(result.journal_path, wow_root=self.wow, root=self.root)
        stopped = caught.exception.result
        self.assertTrue(stopped.undo)
        self.assertEqual([(p.part, p.kind) for p in stopped.parts], [("WTF", "restored")])
        self.assertIn("boom", str(caught.exception))
        failed = [e for e in events if e["event"] == "ibackup.undo_failed"]
        self.assertEqual(len(failed), 1)
        self.assertIs(failed[0]["data"]["stopped"], True)
        self.assertNotIn("ibackup.undo_completed", [e["event"] for e in events])

    def test_created_part_that_cannot_be_fully_deleted_is_replaced_left(self):
        shutil.rmtree(self.retail / "Interface")
        result = self.do_restore(("Interface",))
        real = undo_module.remove_tree_no_follow

        def refuse(path):
            if str(path).endswith("Interface.replaced"):
                raise PermissionError(13, "in use")
            real(path)

        with patch.object(undo_module, "remove_tree_no_follow", refuse):
            undone, events = self.undo(result.journal_path)
        self.assertEqual(undone.parts[0].kind, "replaced_left")
        self.assertIn("Interface.replaced", undone.parts[0].reason)
        self.assertTrue(undone.ok)
        self.assertFalse(os.path.lexists(self.retail / "Interface"))
        left = [e for e in events if e["event"] == "ibackup.replaced_left"]
        self.assertEqual(len(left), 1)
        self.assertIs(left[0]["data"]["undo"], True)
        self.assertIsNone(latest_undoable(self.journal_dir))


if __name__ == "__main__":
    unittest.main()
