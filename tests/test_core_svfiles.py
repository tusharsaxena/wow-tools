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


class SvFileWalkTest(unittest.TestCase):
    """The SavedVariables file model and walk (SV Browser spec D20) shared by Ace3 and SV Browser."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.flavor = WowInstall(build_wow_tree(self.tmp / "wow")).flavor("_retail_")
        self.sv_dir = self.flavor.account_dir / "ACCT1" / "SavedVariables"

    def rows(self, walked):
        return [(acct.name, None if char is None else char.label, path.name) for acct, char, path in walked]

    def test_sv_file_identity(self):
        path = self.sv_dir / "Details.lua"
        data = path.read_bytes()
        char = self.flavor.accounts()[0].characters()[0]
        sv = svfiles.SvFile(path, self.flavor, "ACCT1", None, len(data), 0.0, svfiles.sha256_of(data))
        self.assertEqual(sv.addon, "Details")
        self.assertEqual(sv.rel, "WTF/Account/ACCT1/SavedVariables/Details.lua")
        self.assertEqual(sv.owner, svfiles.OWNER_ACCOUNT_WIDE)
        self.assertEqual(svfiles.OWNER_ACCOUNT_WIDE, "Account-wide")
        self.assertEqual(svfiles.SvFile(path, self.flavor, "ACCT1", char, 0, 0.0, "").owner, "Realm1/CharA")
        self.assertEqual(svfiles.sha256_of(b"abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_walk_takes_every_lua_file_directly_in_saved_variables(self):
        (self.sv_dir / "Old.lua.old").write_text("x", encoding="utf-8")
        (self.sv_dir / ".lua").write_text("x", encoding="utf-8")
        (self.sv_dir / "Folder.lua").mkdir()
        (self.sv_dir / "Folder.lua" / "Inner.lua").write_text("x", encoding="utf-8")
        self.assertEqual(self.rows(svfiles.walk_sv_files(self.flavor)), [
            ("ACCT1", None, "Auctionator.lua"), ("ACCT1", None, "Blizzard_Foo.lua"), ("ACCT1", None, "Details.lua"),
            ("ACCT1", None, "DisabledAddon.lua"), ("ACCT1", None, "OldAddon.lua"), ("ACCT1", None, "Uninstalled.lua"),
            ("ACCT1", "Realm1/CharA", "Auctionator.lua"), ("ACCT1", "Realm1/CharA", "Uninstalled.lua"),
            ("ACCT2", None, "Details.lua"), ("ACCT2", "Realm2/Chârb", "Details.lua")])

    def test_walk_filter_hook_and_one_account(self):
        walked = svfiles.walk_sv_files(self.flavor, account="acct1", accept=svfiles.is_addon_sv_file)
        names = [name for acct, owner, name in self.rows(walked)]
        self.assertNotIn("Blizzard_Foo.lua", names)
        self.assertIn("Details.lua", names)
        self.assertEqual({acct for acct, owner, name in self.rows(
            svfiles.walk_sv_files(self.flavor, account="acct1"))}, {"ACCT1"})
        self.assertFalse(svfiles.is_sv_file("KickCD.lua.bak"))
        self.assertFalse(svfiles.is_addon_sv_file("blizzard_x.lua"))

    def test_walk_reports_every_account_with_its_characters(self):
        seen = []
        list(svfiles.walk_sv_files(self.flavor, on_account=lambda acct, chars: seen.append(
            (acct.name, [c.label for c in chars]))))
        self.assertEqual(seen, [("ACCT1", ["Realm1/CharA"]), ("ACCT2", ["Realm2/Chârb"])])

    def test_walk_reports_a_folder_it_cannot_list(self):
        errors = []
        real = os.scandir

        def scandir(path):
            if Path(path) == self.sv_dir:
                raise PermissionError(13, "denied")
            return real(path)

        with patch("wowtools.core.svfiles.os.scandir", scandir):
            rows = self.rows(svfiles.walk_sv_files(self.flavor, on_error=lambda p, e: errors.append(p)))
        self.assertEqual(errors, [self.sv_dir])
        self.assertIn(("ACCT1", "Realm1/CharA", "Auctionator.lua"), rows)

    @unittest.skipIf(os.name == "nt", "symlink creation needs privileges on Windows")
    def test_walk_skips_a_folder_under_a_link_and_a_linked_file(self):
        target = self.tmp / "elsewhere"
        (target / "SavedVariables").mkdir(parents=True)
        (target / "SavedVariables" / "X.lua").write_text("x", encoding="utf-8")
        os.symlink(target, self.flavor.account_dir / "ACCT2" / "Realm2" / "Linked")
        os.symlink(target / "SavedVariables" / "X.lua", self.sv_dir / "Linked.lua")
        linked = []
        names = [name for acct, owner, name in self.rows(svfiles.walk_sv_files(self.flavor, on_link=linked.append))]
        self.assertNotIn("X.lua", names)
        self.assertNotIn("Linked.lua", names)
        self.assertEqual(linked, [target.parent / "wow" / "_retail_" / "WTF" / "Account" / "ACCT2" / "Realm2"
                                  / "Linked" / "SavedVariables"])
        self.assertTrue(svfiles.under_link(linked[0], self.flavor.account_dir / "ACCT2"))
        self.assertFalse(svfiles.under_link(self.sv_dir, self.flavor.account_dir / "ACCT1"))
