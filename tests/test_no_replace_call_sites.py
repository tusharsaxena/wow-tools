"""Every place that renames a file into its final name must refuse an existing target (F-014, F-028): a file that
appears between the existence check and the rename is never replaced. fsutil.rename_no_replace is tested on its
own in test_fsutil; these tests pin each call site to it, so a later change back to os.rename / os.replace fails."""
from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core.backup import BackupEntry, BackupError, create_backup
from wowtools.core.fsutil import rename_no_replace
from wowtools.core.install import WowInstall
from wowtools.tools.screenshot_organizer import organizer, undo
from wowtools.tools.wtf_cleaner import cleaner, safety
from wowtools.tools.wtf_cleaner.cleaner import CleanError

WHEN = datetime(2026, 9, 27, 14, 3, 11)


def never_exists(path) -> bool:
    """The existence checks see nothing, as if the target appeared right after them."""
    return False


class NoReplaceCallSiteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = self.tmp / "src.jpg"
        self.src.write_bytes(b"source")
        self.dst = self.tmp / "dst.jpg"
        self.dst.write_bytes(b"existing")

    def assert_dst_kept(self):
        self.assertEqual(self.dst.read_bytes(), b"existing")

    def test_default_renames_are_rename_no_replace(self):
        for func in (organizer.move_file, organizer.execute, undo.undo):
            with self.subTest(func=func.__qualname__):
                self.assertIs(inspect.signature(func).parameters["rename"].default, rename_no_replace)

    def test_move_file_never_replaces(self):
        with patch("os.path.lexists", never_exists), self.assertRaises(FileExistsError):
            organizer.move_file(self.src, self.dst)
        self.assert_dst_kept()
        self.assertEqual(self.src.read_bytes(), b"source")

    def test_copy_verified_never_replaces(self):
        with patch("os.path.lexists", never_exists), self.assertRaises(FileExistsError):
            organizer.copy_verified(self.src, self.dst)
        self.assert_dst_kept()
        self.assertFalse(self.dst.with_name(self.dst.name + organizer.PARTIAL).exists())

    def test_create_backup_never_replaces(self):
        dest = self.tmp / "backup.zip"
        dest.write_bytes(b"older backup")
        with self.assertRaises(BackupError):
            create_backup([BackupEntry(self.src)], self.tmp, dest, {})
        self.assertEqual(dest.read_bytes(), b"older backup")

    def test_take_snapshot_never_replaces(self):
        flavor = WowInstall(build_wow_tree(self.tmp / "World of Warcraft")).flavor("retail")
        taken = self.tmp / "backups" / "backup" / "backup-retail-20260927-140311.zip"
        taken.parent.mkdir(parents=True)
        taken.write_bytes(b"older backup")
        with patch.object(safety, "snapshot_path", lambda *args: taken), self.assertRaises(BackupError):
            safety.take_snapshot(flavor, self.tmp / "backups", WHEN)
        self.assertEqual(taken.read_bytes(), b"older backup")

    def test_lock_probe_put_back_never_replaces(self):
        """A new file at the original name during the probe stays; the probed file is left at the aside name."""
        real = cleaner.rename_no_replace
        calls = []

        def rename_then_new_file(src, dst):
            real(src, dst)
            calls.append((src, dst))
            if len(calls) == 1:
                self.src.write_bytes(b"new file")  # appears at the original name right after the probe's rename

        with patch.object(cleaner, "rename_no_replace", rename_then_new_file), self.assertRaises(CleanError):
            cleaner._probe_lock(self.src)
        self.assertEqual(self.src.read_bytes(), b"new file")
        self.assertEqual(self.src.with_name("src.jpg" + cleaner.LOCK_PROBE_SUFFIX).read_bytes(), b"source")


if __name__ == "__main__":
    unittest.main()
