from __future__ import annotations

import errno
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.fixtures import OLD_SHOT, build_screenshot_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.screenshot_organizer.journal import latest_undoable, prune_journals, read_journal
from wowtools.tools.screenshot_organizer.organizer import (ALREADY_FILED, CONFLICT_KEPT, COPIED, DUPLICATE_REMOVED,
                                                           FAILED, MOVED, REFUSED, SKIPPED, SOURCE_LEFT, WOULD_COPY,
                                                           WOULD_MOVE, WOULD_REMOVE_DUPLICATE, OrganizeError, execute)
from wowtools.tools.screenshot_organizer.planner import scan

A = "WoWScrnShot_073119_232713.jpg"
B = "WoWScrnShot_073119_232800.jpg"


def exdev(src, dst):
    raise OSError(errno.EXDEV, "Invalid cross-device link")


class OrganizerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("retail")
        self.era = self.install.flavor("classic_era")
        self.shots = self.root / "_retail_" / "Screenshots"
        self.dest = self.tmp / "arch"
        self.journals = self.tmp / "journal"

    def run_plan(self, dest=None, flavors=None, **kw):
        plan = scan(flavors or [self.retail], dest)
        kw.setdefault("copy", False)
        kw.setdefault("dry_run", False)
        return plan, execute(plan.selectable, dest_dir=dest, journal_dir=self.journals, keep_journals=10, **kw)

    def test_move_in_place(self):
        _, result = self.run_plan()
        self.assertEqual(result.count(MOVED), 4)
        self.assertTrue((self.shots / "2019" / "07" / "31" / A).is_file())
        self.assertFalse((self.shots / A).exists())
        self.assertTrue((self.shots / "notes.txt").exists())  # unrecognised: untouched
        journal = read_journal(result.journal_path)
        self.assertEqual(len(journal.entries), 4)
        self.assertIsNotNone(journal.finished)
        self.assertEqual(result.journal_path, latest_undoable(self.journals))

    def test_move_to_archive_keeps_foreign_files(self):
        self.dest.mkdir()
        (self.dest / "digikam4.db").write_bytes(b"db")
        _, result = self.run_plan(self.dest, [self.retail, self.era])
        self.assertEqual(result.count(MOVED), 6)
        self.assertTrue((self.dest / "_classic_era_" / "2020" / "12" / "05" / "WoWScrnShot_120520_111111.jpg").exists())
        self.assertEqual((self.dest / "digikam4.db").read_bytes(), b"db")

    def test_cross_device_move_verifies_and_keeps_mtime(self):
        _, result = self.run_plan(self.dest, rename=exdev)
        self.assertEqual(result.count(MOVED), 4)
        target = self.dest / "_retail_" / "2019" / "07" / "31" / A
        self.assertEqual(target.read_bytes(), b"shot-a")
        self.assertAlmostEqual(target.stat().st_mtime, OLD_SHOT, delta=2)
        self.assertFalse((self.shots / A).exists())
        self.assertEqual(list(self.dest.rglob("*.partial")), [])

    def test_cross_device_source_left_when_delete_fails(self):
        real_remove = os.remove

        def no_remove(path, *a, **k):
            if Path(path).parent == self.shots:
                raise PermissionError(errno.EACCES, "locked")
            return real_remove(path, *a, **k)

        with unittest.mock.patch("wowtools.tools.screenshot_organizer.organizer.os.remove", no_remove):
            _, result = self.run_plan(self.dest, rename=exdev)
        self.assertEqual(result.count(SOURCE_LEFT), 4)
        self.assertTrue((self.shots / A).exists())
        self.assertTrue((self.dest / "_retail_" / "2019" / "07" / "31" / A).exists())
        self.assertEqual(read_journal(result.journal_path).entries[0]["action"], "copied_source_left")

    def test_copy_mode(self):
        _, result = self.run_plan(self.dest, copy=True)
        self.assertEqual(result.count(COPIED), 4)
        self.assertTrue((self.shots / A).exists())
        self.assertTrue((self.dest / "_retail_" / "2019" / "07" / "31" / A).exists())

    def test_dry_run_changes_nothing(self):
        before = sorted(p for p in self.root.rglob("*"))
        with capture_events() as records:
            _, result = self.run_plan(self.dest, dry_run=True)
        self.assertEqual(result.count(WOULD_MOVE), 4)
        self.assertEqual(sorted(p for p in self.root.rglob("*")), before)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.journals.exists())
        self.assertIsNone(result.journal_path)
        self.assertIn("shots.would_file", [r["event"] for r in records])
        _, copy_result = self.run_plan(self.dest, dry_run=True, copy=True)
        self.assertEqual(copy_result.count(WOULD_COPY), 4)

    def test_duplicate_removed_and_conflict_kept(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / A).write_bytes(b"shot-a")   # identical
        (day / B).write_bytes(b"shot-X")   # same size, different content -> conflict at execute
        _plan, result = self.run_plan(self.dest)
        self.assertEqual(result.count(DUPLICATE_REMOVED), 1)
        self.assertEqual(result.count(CONFLICT_KEPT), 1)
        self.assertFalse((self.shots / A).exists())
        self.assertEqual((self.shots / B).read_bytes(), b"shot-b")
        self.assertEqual((day / B).read_bytes(), b"shot-X")

    def test_duplicate_in_copy_mode_and_dry_run(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / A).write_bytes(b"shot-a")
        _, dry = self.run_plan(self.dest, dry_run=True)
        self.assertEqual(dry.count(WOULD_REMOVE_DUPLICATE), 1)
        _, copied = self.run_plan(self.dest, copy=True)
        self.assertEqual(copied.count(ALREADY_FILED), 1)
        self.assertTrue((self.shots / A).exists())

    def test_changed_or_missing_since_scan_is_skipped(self):
        plan = scan([self.retail], self.dest)
        (self.shots / A).write_bytes(b"longer-now")
        (self.shots / B).unlink()
        result = execute(plan.selectable, dest_dir=self.dest, copy=False, dry_run=False,
                         journal_dir=self.journals, keep_journals=10)
        self.assertEqual(result.count(SKIPPED), 2)
        self.assertEqual(result.count(MOVED), 2)

    def test_target_appearing_after_scan_is_never_overwritten(self):
        plan = scan([self.retail], self.dest)
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / A).write_bytes(b"other!")  # same size as shot-a, different bytes
        result = execute(plan.selectable, dest_dir=self.dest, copy=False, dry_run=False,
                         journal_dir=self.journals, keep_journals=10)
        self.assertEqual(result.count(CONFLICT_KEPT), 1)
        self.assertEqual((day / A).read_bytes(), b"other!")

    def test_target_appearing_during_the_run_is_a_conflict(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"

        def sneaky(src, dst):
            if src.name == A:  # the day folder's listing is cached by now; B's target appears afterwards
                (day / B).write_bytes(b"late!!")
            os.rename(src, dst)

        _, result = self.run_plan(self.dest, rename=sneaky)
        self.assertEqual(result.count(CONFLICT_KEPT), 1)
        self.assertEqual(result.count(MOVED), 3)
        self.assertEqual((day / B).read_bytes(), b"late!!")
        self.assertEqual((self.shots / B).read_bytes(), b"shot-b")

    def test_target_created_between_check_and_rename_is_not_overwritten(self):
        """The last check before writing and the rename are two steps; a file that appears between them must not
        be replaced (on POSIX a plain rename would)."""
        target = self.dest / "_retail_" / "2019" / "07" / "31" / A
        real_lexists = os.path.lexists

        def racing_lexists(path):
            exists = real_lexists(path)
            if Path(path) == target and not exists:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"late!!")  # appears right after the check
            return exists

        plan = scan([self.retail], self.dest)
        with unittest.mock.patch("os.path.lexists", racing_lexists):
            result = execute(plan.selectable, dest_dir=self.dest, copy=False, dry_run=False,
                             journal_dir=self.journals, keep_journals=10)
        self.assertEqual(result.count(CONFLICT_KEPT), 1)
        self.assertEqual(target.read_bytes(), b"late!!")
        self.assertEqual((self.shots / A).read_bytes(), b"shot-a")

    def test_path_guard_refuses(self):
        plan = scan([self.retail], self.dest)
        item = plan.selectable[0]
        bad = [item.__class__(item.flavor, item.src, self.tmp / "elsewhere" / item.src.name, item.day,
                              item.size, item.mtime, item.state),
               item.__class__(item.flavor, self.tmp / item.src.name, item.dst, item.day, item.size, item.mtime,
                              item.state)]
        result = execute(bad, dest_dir=self.dest, copy=False, dry_run=False, journal_dir=self.journals,
                         keep_journals=10)
        self.assertEqual(result.count(REFUSED), 2)
        self.assertTrue(item.src.exists())

    def test_per_file_error_continues(self):
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 1:
                raise PermissionError(errno.EACCES, "denied")
            os.rename(src, dst)

        _, result = self.run_plan(self.dest, rename=flaky)
        self.assertEqual(result.count(FAILED), 1)
        self.assertEqual(result.count(MOVED), 3)

    def test_unexpected_error_stops_with_partial_journal(self):
        calls = []

        def boom(src, dst):
            calls.append(src)
            if len(calls) == 3:
                raise RuntimeError("boom")
            os.rename(src, dst)

        with capture_events() as records, self.assertRaises(OrganizeError) as ctx:
            self.run_plan(self.dest, rename=boom)
        self.assertEqual(ctx.exception.result.count(MOVED), 2)
        journal = read_journal(ctx.exception.result.journal_path)
        self.assertEqual(len(journal.entries), 2)
        self.assertIsNone(journal.finished)
        self.assertIn("shots.organize_stopped", [r["event"] for r in records])

    def test_stale_partial_is_replaced(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / (A + ".partial")).write_bytes(b"half")
        _, result = self.run_plan(self.dest, rename=exdev)
        self.assertEqual(result.count(MOVED), 4)
        self.assertEqual((day / A).read_bytes(), b"shot-a")
        self.assertFalse((day / (A + ".partial")).exists())

    def test_journal_pruning_logs_the_organizer_event(self):
        # The pruning itself is tested in tests/test_journal.py; the organizer logs its own event.
        self.journals.mkdir()
        for i in range(3):
            (self.journals / f"journal-2020010{i}-000000.jsonl").write_text('{"version": 1}\n')
        with capture_events() as records:
            removed = prune_journals(self.journals, 2)
        self.assertEqual(len(removed), 1)
        self.assertIn("shots.journal_pruned", [r["event"] for r in records])

    def test_progress_callback_errors_are_swallowed(self):
        def bad(*a):
            raise ValueError("ui gone")

        _, result = self.run_plan(self.dest, progress=bad)
        self.assertEqual(result.count(MOVED), 4)

    def test_unwritable_journal_stops_before_anything_moves(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("a file where the journal folder should go")
        plan = scan([self.retail], None)
        with self.assertRaises(OrganizeError) as ctx:
            execute(plan.selectable, dest_dir=None, copy=False, dry_run=False,
                    journal_dir=blocker / "journal", keep_journals=10)
        self.assertEqual(ctx.exception.result.outcomes, [])
        self.assertIsNone(ctx.exception.result.journal_path)
        self.assertTrue((self.shots / A).is_file())
        self.assertFalse((self.shots / "2019").exists())

    def test_run_that_changes_nothing_leaves_no_journal(self):
        plan = scan([self.retail], None)
        for item in plan.selectable:
            item.src.unlink()
        result = execute(plan.selectable, dest_dir=None, copy=False, dry_run=False,
                         journal_dir=self.journals, keep_journals=10)
        self.assertEqual(result.count(SKIPPED), 4)
        self.assertIsNone(result.journal_path)
        self.assertEqual(list(self.journals.iterdir()) if self.journals.exists() else [], [])

    def test_journal_write_failure_stops_the_run_and_reports_the_change(self):
        from wowtools.tools.screenshot_organizer import journal as journal_mod
        real_add = journal_mod.JournalWriter.add
        calls = []

        def failing_add(writer, *a, **k):
            calls.append(a)
            if len(calls) == 2:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_add(writer, *a, **k)

        with (
            unittest.mock.patch.object(journal_mod.JournalWriter, "add", failing_add),
            self.assertRaises(OrganizeError) as ctx,
        ):
            self.run_plan(self.dest)
        result = ctx.exception.result
        # The first file is moved and journaled; the second is moved but could not be journaled: it is reported
        # as moved (with the journal error) rather than failed, and the run stops there.
        self.assertEqual([o.kind for o in result.outcomes], [MOVED, MOVED])
        self.assertIn("journal", result.outcomes[1].reason)
        self.assertEqual(len(read_journal(result.journal_path).entries), 1)
        moved = [o for o in result.outcomes if not o.src.exists() and o.dst.is_file()]
        self.assertEqual(len(moved), 2)
        self.assertEqual(len(list((self.dest / "_retail_").rglob("WoWScrnShot*"))), 2)  # nothing after the stop
