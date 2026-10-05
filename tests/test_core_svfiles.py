"""core/svfiles.py: the guard, lock probe and probe-leftover recovery shared by tools that change SavedVariables."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core import svfiles
from wowtools.core.install import WowInstall


class SvFilesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.flavor = WowInstall(build_wow_tree(self.tmp / "wow")).flavor("_retail_")
        self.sv = self.flavor.account_dir / "ACCT1" / "SavedVariables" / "Details.lua"

    def test_guard_accepts_a_saved_variables_file(self):
        svfiles.SvGuard(self.flavor).check(self.sv, svfiles.lstat_or_none(self.sv))

    def test_guard_refuses_outside_account_folder(self):
        outside = self.tmp / "elsewhere" / "SavedVariables" / "x.lua"
        outside.parent.mkdir(parents=True)
        outside.write_text("x", encoding="utf-8")
        with self.assertRaises(svfiles.SvFileError) as caught:
            svfiles.SvGuard(self.flavor).check(outside, None)
        self.assertIn("outside", str(caught.exception))

    def test_guard_refuses_a_file_not_directly_in_saved_variables(self):
        path = self.flavor.account_dir / "ACCT1" / "config-cache.wtf"
        with self.assertRaises(svfiles.SvFileError) as caught:
            svfiles.SvGuard(self.flavor).check(path, None)
        self.assertIn("SavedVariables", str(caught.exception))

    def test_probe_lock_puts_the_file_back(self):
        before = self.sv.read_bytes()
        self.assertIsNone(svfiles.probe_lock(self.sv))
        self.assertEqual(self.sv.read_bytes(), before)
        self.assertFalse(self.sv.with_name(self.sv.name + svfiles.LOCK_PROBE_SUFFIX).exists())

    def test_probe_lock_reports_a_locked_file(self):
        def refuse(src, dst):
            raise PermissionError(13, "in use")
        with patch("wowtools.core.svfiles.rename_no_replace", refuse):
            self.assertEqual(svfiles.probe_lock(self.sv), "in use")

    def test_find_locked_lists_the_locked_files_and_reports_each(self):
        free = self.sv.with_name("Auctionator.lua")
        reports = []

        def probe(path):
            return "in use" if path == self.sv else None

        with patch.object(svfiles, "probe_lock", probe):
            locked = svfiles.find_locked([("a/Details.lua", self.sv), ("a/Auctionator.lua", free)], RuntimeError,
                                         lambda *a: reports.append(a))
        self.assertEqual(locked, [("a/Details.lua", "in use")])
        self.assertEqual(reports, [("lock_check", 1, 2, "a/Details.lua"), ("lock_check", 2, 2, "a/Auctionator.lua")])

    def test_find_locked_raises_the_tools_error_when_a_file_cannot_be_put_back(self):
        def stuck(path):
            raise svfiles.SvFileError("Could not put it back.")

        with patch.object(svfiles, "probe_lock", stuck), self.assertRaises(ValueError) as caught:
            svfiles.find_locked([("a/Details.lua", self.sv)], lambda exc: ValueError(f"{exc} Nothing was changed."))
        self.assertEqual(str(caught.exception), "Could not put it back. Nothing was changed.")

    def test_locked_message_names_the_lockers_and_counts_the_rest(self):
        locked = [(f"f{i}.lua", "in use") for i in range(12)]
        message = svfiles.locked_message(locked, "clean")
        self.assertTrue(message.startswith("12 files are locked by another program (the Raider.IO client"))
        self.assertIn("Close it and clean again.", message)
        self.assertIn("  f9.lua (in use)", message)
        self.assertNotIn("f10.lua", message)
        self.assertTrue(message.endswith("…and 2 more"))
        self.assertNotIn("more", svfiles.locked_message(locked[:2], "apply"))

    def test_recover_probe_leftovers_renames_back(self):
        aside = self.sv.with_name(self.sv.name + svfiles.LOCK_PROBE_SUFFIX)
        os.rename(self.sv, aside)
        seen = []
        recovered = svfiles.recover_probe_leftovers([self.sv.parent], on_recovered=seen.append)
        self.assertEqual(recovered, [self.sv])
        self.assertEqual(seen, [self.sv])
        self.assertTrue(self.sv.exists())

    def test_saved_variables_folders_one_account(self):
        folders = svfiles.saved_variables_folders(self.flavor, "acct2")
        self.assertEqual([f.relative_to(self.flavor.account_dir).as_posix() for f in folders],
                         ["ACCT2/SavedVariables", "ACCT2/Realm2/Chârb/SavedVariables"])
