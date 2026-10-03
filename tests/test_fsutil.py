from __future__ import annotations

import errno
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from wowtools.core import fsutil
from wowtools.core.fsutil import atomic_write_text, free_name, remove_quietly, rename_no_replace, safe_progress


class RenameNoReplaceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = self.tmp / "src.txt"
        self.dst = self.tmp / "dst.txt"
        self.src.write_bytes(b"source")

    def test_rename_no_replace_moves(self):
        rename_no_replace(self.src, self.dst)
        self.assertFalse(self.src.exists())
        self.assertEqual(self.dst.read_bytes(), b"source")

    def test_rename_no_replace_refuses_existing_target(self):
        self.dst.write_bytes(b"target")
        with self.assertRaises(FileExistsError):
            rename_no_replace(self.src, self.dst)
        self.assertEqual(self.src.read_bytes(), b"source")
        self.assertEqual(self.dst.read_bytes(), b"target")

    @unittest.skipIf(os.name == "nt", "Windows renames never replace; hard links are not used there")
    def test_rename_no_replace_falls_back_without_hardlinks(self):
        with patch.object(fsutil.os, "link", side_effect=OSError(errno.EPERM, "not supported")):
            rename_no_replace(self.src, self.dst)
            self.assertEqual(self.dst.read_bytes(), b"source")
            self.assertFalse(self.src.exists())
            self.src.write_bytes(b"again")
            with self.assertRaises(FileExistsError):
                rename_no_replace(self.src, self.dst)
        self.assertEqual(self.dst.read_bytes(), b"source")

    @unittest.skipIf(os.name == "nt", "EXDEV comes from os.link on POSIX only")
    def test_cross_device_error_is_raised_unchanged(self):
        with patch.object(fsutil.os, "link", side_effect=OSError(errno.EXDEV, "cross-device")):
            with self.assertRaises(OSError) as ctx:
                rename_no_replace(self.src, self.dst)
        self.assertEqual(ctx.exception.errno, errno.EXDEV)
        self.assertTrue(self.src.exists())

    def test_missing_source_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            rename_no_replace(self.tmp / "nope", self.dst)


class FreeNameTest(unittest.TestCase):
    def test_suffixes_when_taken(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(free_name(folder, "backup-x", ".zip"), folder / "backup-x.zip")
            (folder / "backup-x.zip").write_bytes(b"")
            self.assertEqual(free_name(folder, "backup-x", ".zip"), folder / "backup-x-2.zip")
            (folder / "backup-x-2.zip").write_bytes(b"")
            self.assertEqual(free_name(folder, "backup-x", ".zip"), folder / "backup-x-3.zip")

    def test_missing_folder_is_free(self):
        self.assertEqual(free_name(Path("/no/such/folder"), "a", ".b"), Path("/no/such/folder/a.b"))


class AtomicWriteTest(unittest.TestCase):
    def test_writes_and_leaves_no_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.cfg"
            atomic_write_text(path, "one")
            atomic_write_text(path, "two")
            self.assertEqual(path.read_text(encoding="utf-8"), "two")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["x.cfg"])


class SmallHelpersTest(unittest.TestCase):
    def test_remove_quietly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.partial"
            path.write_text("x", encoding="utf-8")
            remove_quietly(path)
            self.assertFalse(path.exists())
            remove_quietly(path)  # already gone: no error
            remove_quietly(Path(tmp))  # a folder cannot be removed this way: still no error
            self.assertTrue(Path(tmp).is_dir())

    def test_safe_progress_passes_calls_and_swallows_errors(self):
        calls = []
        safe_progress(lambda *a: calls.append(a))("stage", 1, 2, "file")
        self.assertEqual(calls, [("stage", 1, 2, "file")])
        safe_progress(None)("stage", 1, 2)

        def broken(*_):
            raise RuntimeError("display gone")
        safe_progress(broken)("stage", 1, 2)  # never raises
