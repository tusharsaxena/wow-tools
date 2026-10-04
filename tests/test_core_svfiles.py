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
