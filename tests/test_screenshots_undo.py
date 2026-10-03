import errno
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.fixtures import build_screenshot_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.screenshots.journal import latest_undoable, read_journal
from wowtools.tools.screenshots.organizer import (COPY_REMOVED, RESTORED, UNDO_SKIPPED, OrganizeError, execute)
from wowtools.tools.screenshots.planner import scan
from wowtools.tools.screenshots.report import stopped_text
from wowtools.tools.screenshots.undo import undo

A = "WoWScrnShot_073119_232713.jpg"


def exdev(src, dst):
    raise OSError(errno.EXDEV, "Invalid cross-device link")


class UndoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.retail = WowInstall(self.root).flavor("retail")
        self.shots = self.root / "_retail_" / "Screenshots"
        self.dest = self.tmp / "arch"
        self.journals = self.tmp / "journal"
        self.before = {p.name: p.read_bytes() for p in self.shots.iterdir() if p.is_file()}

    def organize(self, dest=None, **kw):
        plan = scan([self.retail], dest)
        kw.setdefault("copy", False)
        return execute(plan.selectable, dest_dir=dest, dry_run=False, journal_dir=self.journals,
                       keep_journals=10, **kw)

    def assert_restored(self):
        now = {p.name: p.read_bytes() for p in self.shots.iterdir() if p.is_file()}
        self.assertEqual(now, self.before)

    def test_undo_moves_back_and_prunes_empty_date_folders(self):
        result = self.organize(self.dest)
        with capture_events() as records:
            back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(RESTORED), 4)
        self.assert_restored()
        self.assertEqual(list((self.dest / "_retail_").iterdir()), [])
        self.assertIsNotNone(read_journal(result.journal_path).undone)
        self.assertIsNone(latest_undoable(self.journals))
        self.assertIn("shots.undo_completed", [r["event"] for r in records])

    def test_undo_in_place_keeps_already_filed_folders(self):
        result = self.organize(None)
        undo(result.journal_path, wow_root=self.root)
        self.assert_restored()
        self.assertTrue((self.shots / "2025" / "01" / "02" / "WoWScrnShot_010225_090000.jpg").exists())
        self.assertFalse((self.shots / "2019").exists())

    def test_undo_cross_device(self):
        result = self.organize(self.dest, rename=exdev)
        back = undo(result.journal_path, wow_root=self.root, rename=exdev)
        self.assertEqual(back.count(RESTORED), 4)
        self.assert_restored()

    def test_undo_cross_device_keeps_restore_when_archive_copy_is_locked(self):
        result = self.organize(self.dest, rename=exdev)
        real_remove = os.remove

        def no_archive_remove(path, *a, **k):
            if self.dest in Path(path).parents:
                raise PermissionError(errno.EACCES, "locked")
            return real_remove(path, *a, **k)

        with unittest.mock.patch("wowtools.tools.screenshots.undo.os.remove", no_archive_remove):
            back = undo(result.journal_path, wow_root=self.root, rename=exdev)
        self.assertEqual(back.count(RESTORED), 4)
        self.assertTrue(all("could not be deleted" in o.reason for o in back.outcomes))
        self.assert_restored()

    def test_undo_copy_removes_copies(self):
        result = self.organize(self.dest, copy=True)
        back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(COPY_REMOVED), 4)
        self.assert_restored()
        self.assertFalse((self.dest / "_retail_" / "2019").exists())

    def test_undo_restores_removed_duplicate(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / A).write_bytes(b"shot-a")
        result = self.organize(self.dest)
        undo(result.journal_path, wow_root=self.root)
        self.assert_restored()
        self.assertEqual((day / A).read_bytes(), b"shot-a")  # the archive copy stays

    def test_undo_skips_when_things_changed(self):
        result = self.organize(self.dest)
        moved = self.dest / "_retail_" / "2019" / "07" / "31" / A
        moved.write_bytes(b"edited in an image editor")
        (self.shots / "WoWScrnShot_073119_232800.jpg").write_bytes(b"new file at source")
        back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(UNDO_SKIPPED), 2)
        self.assertEqual(back.count(RESTORED), 2)
        self.assertTrue(moved.exists())

    def test_undo_never_removes_foreign_or_nonempty_folders(self):
        result = self.organize(self.dest)
        (self.dest / "_retail_" / "2019" / "07" / "31" / "Thumbs.db").write_bytes(b"x")
        (self.dest / "_retail_" / "albums").mkdir()
        undo(result.journal_path, wow_root=self.root)
        self.assertTrue((self.dest / "_retail_" / "2019" / "07" / "31" / "Thumbs.db").exists())
        self.assertTrue((self.dest / "_retail_" / "albums").is_dir())
        self.assertFalse((self.dest / "_retail_" / "2019" / "08").exists())

    def test_undo_of_journal_without_finished_line(self):
        calls = []

        def boom(src, dst):
            calls.append(src)
            if len(calls) == 3:
                raise RuntimeError("boom")
            import os
            os.rename(src, dst)

        with self.assertRaises(OrganizeError) as ctx:
            self.organize(self.dest, rename=boom)
        path = ctx.exception.result.journal_path
        self.assertEqual(latest_undoable(self.journals), path)
        back = undo(path, wow_root=self.root)
        self.assertEqual(back.count(RESTORED), 2)
        self.assert_restored()

    def test_stopped_run_without_a_journal_does_not_offer_an_older_run(self):
        # Run A is journaled. Run B moves a file, then its journal cannot be written: B leaves no journal, and
        # Undo would offer run A, so the stop message must not point at Undo.
        from wowtools.tools.screenshots import journal as journal_mod
        first = self.organize(self.dest, copy=True)
        self.assertIsNotNone(first.journal_path)
        other = self.tmp / "arch2"

        def failing_add(writer, *a, **k):
            raise OSError(errno.ENOSPC, "No space left on device")

        with unittest.mock.patch.object(journal_mod.JournalWriter, "add", failing_add):
            with self.assertRaises(OrganizeError) as ctx:
                self.organize(other)
        result = ctx.exception.result
        self.assertIsNone(result.journal_path)
        self.assertEqual(latest_undoable(self.journals), first.journal_path)
        text = stopped_text(str(ctx.exception), result, latest_undoable(self.journals))
        self.assertNotIn("Undo last run (z) to put", text)
        self.assertIn("cannot put back", text)
        self.assertIn(result.outcomes[0].src.name, text)

    def test_stopped_run_with_its_journal_offers_undo(self):
        calls = []

        def boom(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise RuntimeError("boom")
            os.rename(src, dst)

        with self.assertRaises(OrganizeError) as ctx:
            self.organize(self.dest, rename=boom)
        result = ctx.exception.result
        text = stopped_text(str(ctx.exception), result, latest_undoable(self.journals))
        self.assertIn("Undo last run (z)", text)
        self.assertNotIn("cannot put back", text)

    def test_torn_multibyte_last_line_is_tolerated(self):
        # Non-ASCII paths are journaled as UTF-8; a crash can cut the last line inside a character.
        result = self.organize(self.dest)
        with result.journal_path.open("ab") as handle:
            handle.write(b'{"action": "moved", "src": "C:\\\\Jeux\\\\\xc3')
        self.assertEqual(latest_undoable(self.journals), result.journal_path)
        self.assertEqual(len(read_journal(result.journal_path).entries), 4)
        back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(RESTORED), 4)
        self.assert_restored()

    def test_undo_ignores_current_settings(self):
        result = self.organize(self.dest)
        # The user points dest_dir somewhere else afterwards: undo only reads the journal.
        back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(RESTORED), 4)

    def test_undo_refuses_paths_outside_the_install(self):
        result = self.organize(self.dest)
        back = undo(result.journal_path, wow_root=self.tmp / "Other WoW")
        self.assertEqual(back.count(UNDO_SKIPPED), 4)
        self.assertFalse((self.shots / A).exists())

    def test_only_the_newest_run_is_undoable(self):
        first = self.organize(self.dest)
        (self.shots / "WoWScrnShot_010101_000000.jpg").write_bytes(b"later")
        second = self.organize(self.dest)
        self.assertEqual(latest_undoable(self.journals), second.journal_path)
        undo(second.journal_path, wow_root=self.root)
        self.assertIsNone(latest_undoable(self.journals))
        self.assertIsNotNone(first.journal_path)

    def test_undo_of_journal_with_torn_last_line_is_not_offered_again(self):
        result = self.organize(self.dest)
        path = result.journal_path
        data = path.read_bytes()
        path.write_bytes(data[:-15])  # cut the "finished" line short, as a crash mid-write would
        undo(path, wow_root=self.root)
        self.assertIsNotNone(read_journal(path).undone)
        self.assertIsNone(latest_undoable(self.journals))
