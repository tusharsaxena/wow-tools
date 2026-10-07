from __future__ import annotations

import errno
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wowtools.core import fsutil
from wowtools.core.fsutil import (
    atomic_write_bytes,
    atomic_write_text,
    free_name,
    is_link,
    is_real_dir,
    remove_quietly,
    remove_tree_no_follow,
    rename_no_replace,
    safe_progress,
)


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

    @unittest.skipIf(os.name == "nt", "Windows renames never replace; hard links are not used there")
    def test_rename_no_replace_falls_back_when_link_says_is_a_directory(self):
        # On WSL's drvfs (/mnt/<drive>) os.link gives EISDIR for a junction or a relative symlink to a folder.
        with patch.object(fsutil.os, "link", side_effect=OSError(errno.EISDIR, "Is a directory")):
            rename_no_replace(self.src, self.dst)
            self.assertEqual(self.dst.read_bytes(), b"source")
            self.assertFalse(self.src.exists())
            self.src.write_bytes(b"again")
            with self.assertRaises(FileExistsError):
                rename_no_replace(self.src, self.dst)
        self.assertEqual(self.dst.read_bytes(), b"source")

    @unittest.skipIf(os.name == "nt", "EXDEV comes from os.link on POSIX only")
    def test_cross_device_error_is_raised_unchanged(self):
        with (
            patch.object(fsutil.os, "link", side_effect=OSError(errno.EXDEV, "cross-device")),
            self.assertRaises(OSError) as ctx,
        ):
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


def can_symlink(tmp: Path) -> bool:
    """True when this platform (and user) may create a directory symlink."""
    try:
        (tmp / "probe-target").mkdir()
        os.symlink(tmp / "probe-target", tmp / "probe-link", target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


class RemoveTreeNoFollowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_removes_nested_tree_and_read_only_files(self):
        root = self.tmp / "tree"
        (root / "a" / "b").mkdir(parents=True)
        path = root / "a" / "b" / "x.txt"
        path.write_text("x", encoding="utf-8")
        os.chmod(path, stat.S_IREAD)
        remove_tree_no_follow(root)
        self.assertFalse(root.exists())

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0, "POSIX permissions, not as root")
    def test_posix_permission_error_leaves_modes_alone(self):
        root = self.tmp / "WTF.replaced"
        (root / "locked").mkdir(parents=True)
        path = root / "locked" / "x.lua"
        path.write_text("x", encoding="utf-8")
        before = stat.S_IMODE(path.stat().st_mode)
        os.chmod(root / "locked", 0o555)
        self.addCleanup(os.chmod, root / "locked", 0o755)
        with self.assertRaises(PermissionError):
            remove_tree_no_follow(root)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), before)
        self.assertEqual(path.read_text(encoding="utf-8"), "x")

    def test_read_only_retry_is_windows_only(self):
        path = self.tmp / "x.lua"
        path.write_text("x", encoding="utf-8")
        real = os.remove
        calls = []

        def read_only_once(target):
            calls.append(target)
            if len(calls) == 1:
                raise PermissionError(13, "read-only")
            real(target)

        with patch("os.remove", read_only_once), patch("os.chmod") as chmod, patch.object(fsutil.sys, "platform",
                                                                                          "linux"):
            with self.assertRaises(PermissionError):
                fsutil._delete_entry(path, folder=False)
            chmod.assert_not_called()
        calls.clear()
        with patch("os.remove", read_only_once), patch("os.chmod") as chmod, patch.object(fsutil.sys, "platform",
                                                                                          "win32"):
            fsutil._delete_entry(path, folder=False)
            chmod.assert_called_once_with(path, stat.S_IWRITE)
        self.assertFalse(path.exists())

    def test_link_inside_is_unlinked_never_followed(self):
        if not can_symlink(self.tmp):
            self.skipTest("symlinks not available")
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "keep.lua").write_text("k", encoding="utf-8")
        root = self.tmp / "Interface.replaced"
        (root / "AddOns").mkdir(parents=True)
        os.symlink(repo, root / "AddOns" / "MyAddon", target_is_directory=True)
        self.assertTrue(is_link(root / "AddOns" / "MyAddon"))
        remove_tree_no_follow(root)
        self.assertFalse(root.exists())
        self.assertEqual((repo / "keep.lua").read_text(encoding="utf-8"), "k")

    def test_link_given_as_path_is_just_unlinked(self):
        if not can_symlink(self.tmp):
            self.skipTest("symlinks not available")
        (self.tmp / "probe-target" / "keep.lua").write_text("k", encoding="utf-8")
        remove_tree_no_follow(self.tmp / "probe-link")
        self.assertFalse(os.path.lexists(self.tmp / "probe-link"))
        self.assertEqual((self.tmp / "probe-target" / "keep.lua").read_text(encoding="utf-8"), "k")

    def test_is_link_false_for_plain_folder_and_missing_path(self):
        (self.tmp / "d").mkdir()
        self.assertFalse(is_link(self.tmp / "d"))
        self.assertFalse(is_link(self.tmp / "missing"))
        with os.scandir(self.tmp) as entries:
            self.assertEqual([is_link(entry) for entry in entries], [False])

    def test_is_real_dir(self):
        (self.tmp / "d").mkdir()
        (self.tmp / "f").write_text("x", encoding="utf-8")
        self.assertTrue(is_real_dir(self.tmp / "d"))
        self.assertFalse(is_real_dir(self.tmp / "f"))
        self.assertFalse(is_real_dir(self.tmp / "missing"))
        if can_symlink(self.tmp):
            os.symlink(self.tmp / "d", self.tmp / "link", target_is_directory=True)
            self.assertFalse(is_real_dir(self.tmp / "link"))

    def test_missing_tree_raises(self):
        with self.assertRaises(OSError):
            remove_tree_no_follow(self.tmp / "missing")


class ReadMakeLinkTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_link_read_and_made_again(self):
        target = self.tmp / "repo"
        target.mkdir()
        link = self.tmp / "link"
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted here")
        self.assertEqual(fsutil.read_link(link), (os.fspath(target), False))
        os.unlink(link)
        fsutil.make_link(os.fspath(target), link, junction=False)
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), os.fspath(target))

    def test_not_a_link_is_none(self):
        (self.tmp / "file").write_text("x", encoding="utf-8")
        self.assertIsNone(fsutil.read_link(self.tmp / "file"))
        self.assertIsNone(fsutil.read_link(self.tmp))
        self.assertIsNone(fsutil.read_link(self.tmp / "missing"))


class AtomicWriteBytesTest(unittest.TestCase):
    def test_writes_exact_bytes_and_leaves_no_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.lua"
            path.write_bytes(b"old")
            atomic_write_bytes(path, b"\r\nX = {\r\n}\r\n\xc3\xa2")
            self.assertEqual(path.read_bytes(), b"\r\nX = {\r\n}\r\n\xc3\xa2")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.lua"])

    def test_atomic_write_fsyncs_before_replace(self):
        """F-012: the partial's bytes reach the disk before the replace, so a power cut leaves the old file or the
        new one, never an empty or stale file under the target's name."""
        calls = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd):
            calls.append(("fsync", os.fstat(fd).st_size))
            real_fsync(fd)

        def replace(src, dst):
            calls.append(("replace", Path(src).name))
            real_replace(src, dst)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.lua"
            path.write_bytes(b"old")
            with patch("os.fsync", side_effect=fsync), patch("os.replace", side_effect=replace):
                atomic_write_bytes(path, b"new data")
            self.assertEqual(path.read_bytes(), b"new data")
        self.assertEqual(calls[:2], [("fsync", len(b"new data")), ("replace", "a.lua.partial")])

    def test_failed_fsync_keeps_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.lua"
            path.write_bytes(b"old")
            with (patch("os.fsync", side_effect=OSError("disk gone")), patch("os.replace") as replace,
                  self.assertRaises(OSError)):
                atomic_write_bytes(path, b"new")
            replace.assert_not_called()
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.lua"])

    def test_failed_replace_keeps_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.lua"
            path.write_bytes(b"old")
            with patch("os.replace", side_effect=OSError("locked")), self.assertRaises(OSError):
                atomic_write_bytes(path, b"new")
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.lua"])

    def test_a_replace_refused_while_the_target_is_held_open_is_tried_again(self):
        """Windows: another program holding the target open makes os.replace raise PermissionError for a moment."""
        real_replace = os.replace
        refusals = iter([PermissionError("in use"), PermissionError("in use")])

        def replace(src, dst):
            refusal = next(refusals, None)
            if refusal is not None:
                raise refusal
            real_replace(src, dst)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.cfg"
            path.write_bytes(b"old")
            with (patch.object(fsutil, "REPLACE_RETRY_WAITS", (0.01, 0.01, 0.01)),
                  patch("os.replace", side_effect=replace), patch("time.sleep") as sleep):
                atomic_write_bytes(path, b"new")
            self.assertEqual(path.read_bytes(), b"new")
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.cfg"])

    def test_a_replace_refused_on_every_try_raises_and_keeps_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.cfg"
            path.write_bytes(b"old")
            with (patch.object(fsutil, "REPLACE_RETRY_WAITS", (0.01, 0.01)),
                  patch("os.replace", side_effect=PermissionError("in use")) as replace, patch("time.sleep"),
                  self.assertRaises(PermissionError)):
                atomic_write_bytes(path, b"new")
            self.assertEqual(replace.call_count, 3)
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.cfg"])

    def test_a_replace_is_tried_once_off_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.cfg"
            with (patch.object(fsutil, "REPLACE_RETRY_WAITS", ()),
                  patch("os.replace", side_effect=PermissionError("denied")) as replace, patch("time.sleep") as sleep,
                  self.assertRaises(PermissionError)):
                atomic_write_bytes(path, b"new")
            self.assertEqual((replace.call_count, sleep.call_count), (1, 0))

    def test_a_link_at_the_partial_name_is_never_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            victim = folder / "victim"
            victim.write_bytes(b"precious")
            path = folder / "a.lua"
            path.write_bytes(b"old")
            try:
                os.symlink(victim, folder / "a.lua.partial")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available here")
            atomic_write_bytes(path, b"new")
            self.assertEqual(victim.read_bytes(), b"precious")
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.read_bytes(), b"new")
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["a.lua", "victim"])

    def test_a_stale_partial_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.lua"
            (Path(tmp) / "a.lua.partial").write_bytes(b"stale leftover from a crash")
            atomic_write_bytes(path, b"new")
            self.assertEqual(path.read_bytes(), b"new")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.lua"])
