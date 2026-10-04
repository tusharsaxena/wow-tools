from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.backup import BackupError
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup.backup import back_up
from wowtools.tools.interface_backup.journal import latest_undoable, read_restore_journal, referenced_safety_zips
from wowtools.tools.interface_backup.restore import (RestoreError, RestoreStopped, open_backup, plan_restore, restore,
                                                     split_entry)
from wowtools.tools.interface_backup.scanner import scan_flavor

NOW = datetime(2026, 10, 4, 15, 30, 12)
Usage = namedtuple("Usage", "total used free")


def write_fake_zip(path: Path, names: list[str], flavor_folder: str = "_retail_", *, listed: list[str] | None = None,
                   parts: object = None, mtime: object = 0.0) -> Path:
    """A zip shaped like ours: each name holds b"x"; the manifest lists `listed` (default: the names)."""
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, b"x")
        files = [{"path": name, "size": 1, "mtime": mtime} for name in (names if listed is None else listed)]
        zf.writestr("manifest.json", json.dumps({"version": 1, "kind": "backup", "flavor": "retail",
                                                 "flavor_folder": flavor_folder, "created": "",
                                                 "parts": ["Interface", "WTF"] if parts is None else parts,
                                                 "parts_existing": [],
                                                 "files": files, "links": []}))
    return path


def _symlink(test, target, link):
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        test.skipTest("symlinks not permitted here")


class RestoreTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavors = {f.folder: f for f in WowInstall(self.wow).flavors()}
        self.flavor = self.flavors["_retail_"]
        self.root = self.tmp / "bk" / "interface-backup"
        with capture_events():
            self.backup = back_up(scan_flavor(self.flavor, with_stats=False), self.root, keep=10, now=NOW).path

    def scan(self, folder="_retail_"):
        return scan_flavor(self.flavors[folder], with_stats=True)


class SplitEntryTest(unittest.TestCase):
    def test_safe(self):
        self.assertEqual(split_entry("Interface/AddOns/A/a.lua"), ("Interface", "AddOns/A/a.lua"))
        self.assertEqual(split_entry("WTF/Config.wtf"), ("WTF", "Config.wtf"))
        self.assertEqual(split_entry("WTF/Account/x.lua.bak"), ("WTF", "Account/x.lua.bak"))

    def test_unsafe(self):
        for name in ("", "../x", "/abs", "C:/x", "C:x", "Interface\\x", "Interface/../x", "Interface/./x",
                     "Other/x", "interface/x", "Interface/a:stream", "Interface/dot.", "Interface/space ",
                     "Interface", "Interface//x", "Interface/x/", "Interface/a<b", "Interface/a?b",
                     "Interface/a\x00b"):
            for windows in (False, True):
                with self.subTest(name=name, windows=windows), self.assertRaises(RestoreError):
                    split_entry(name, windows=windows)

    def test_windows_only_names(self):
        # Device names and control characters are ordinary names on POSIX (a character called Aux gets a folder).
        for name in ("Interface/CON", "Interface/AddOns/nul.lua", "WTF/com1.txt", "WTF/LPT9",
                     "WTF/Account/A/Realm/Aux/SavedVariables/x.lua", "Interface/AddOns/Foo/Aux.Tooltip.lua",
                     "Interface/AddOns/Con/x.lua", "Interface/a\x01b"):
            with self.subTest(name=name):
                self.assertEqual(split_entry(name, windows=False)[0], name.split("/")[0])
                with self.assertRaises(RestoreError):
                    split_entry(name, windows=True)


class OpenBackupTest(RestoreTestBase):
    def test_reads_our_zip(self):
        contents = open_backup(self.backup)
        self.assertEqual((contents.flavor_folder, contents.flavor_short, contents.kind, contents.parts),
                         ("_retail_", "retail", "backup", ("Interface", "WTF")))
        self.assertEqual(contents.path, self.backup)
        self.assertEqual(contents.files["Interface"]["AddOns/Auctionator/Auctionator.lua"][0], 3)
        self.assertIn("Config.wtf", contents.files["WTF"])
        self.assertTrue(contents.created)

    def test_sizes_match_the_zip(self):
        contents = open_backup(self.backup)
        with zipfile.ZipFile(self.backup) as zf:
            expected = {i.filename: i.file_size for i in zf.infolist() if i.filename != "manifest.json"}
        self.assertEqual(contents.sizes(), expected)
        self.assertEqual(set(contents.sizes(("WTF",))), {n for n in expected if n.startswith("WTF/")})

    def test_wtf_only_backup(self):
        with capture_events():
            path = back_up(scan_flavor(self.flavors["_anniversary_"], with_stats=False), self.root, keep=10,
                           now=NOW).path
        contents = open_backup(path)
        self.assertEqual(contents.parts, ("WTF",))
        self.assertEqual(contents.files["Interface"], {})

    def test_refuses_foreign_or_unsafe(self):
        plain = self.tmp / "plain.zip"
        with zipfile.ZipFile(plain, "w") as zf:
            zf.writestr("Interface/a.lua", b"x")
        cases = {
            "no manifest": plain,
            "dot-dot": write_fake_zip(self.tmp / "evil.zip", ["Interface/../../x.lua"]),
            "case twins": write_fake_zip(self.tmp / "case.zip", ["WTF/a.txt", "WTF/A.TXT"]),
            "bad flavor": write_fake_zip(self.tmp / "flav.zip", ["WTF/a.txt"], flavor_folder="../x"),
            "unlisted entry": write_fake_zip(self.tmp / "extra.zip", ["WTF/a.txt", "WTF/b.txt"],
                                             listed=["WTF/a.txt"]),
            "listed, not stored": write_fake_zip(self.tmp / "short.zip", ["WTF/a.txt"],
                                                 listed=["WTF/a.txt", "WTF/b.txt"]),
            "file and folder": write_fake_zip(self.tmp / "clash.zip", ["WTF/a", "WTF/A/b.txt"]),
            "part not claimed": write_fake_zip(self.tmp / "part.zip", ["Interface/a.lua"], parts=["WTF"]),
            "parts a string": write_fake_zip(self.tmp / "pstr.zip", ["WTF/a.txt"], parts="InterfaceWTF"),
            "mtime NaN": write_fake_zip(self.tmp / "nan.zip", ["WTF/a.txt"], mtime=float("nan")),
            "mtime infinite": write_fake_zip(self.tmp / "inf.zip", ["WTF/a.txt"], mtime=float("inf")),
            "flavor with newline": write_fake_zip(self.tmp / "nl.zip", ["WTF/a.txt"], flavor_folder="_retail_\n"),
        }
        junk = self.tmp / "junk.zip"
        junk.write_bytes(b"not a zip")
        cases["not a zip"] = junk
        cases["missing file"] = self.tmp / "absent.zip"
        bad_json = self.tmp / "badjson.zip"
        with zipfile.ZipFile(bad_json, "w") as zf:
            zf.writestr("manifest.json", "{not json")
        cases["damaged manifest"] = bad_json
        for label, path in cases.items():
            with self.subTest(label), self.assertRaises(RestoreError):
                open_backup(path)

    def test_refuses_duplicate_entries(self):
        path = self.tmp / "dup.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("WTF/a.txt", b"x")
            with self.assertWarns(UserWarning):  # zipfile warns about the duplicate name
                zf.writestr("WTF/a.txt", b"y")
            zf.writestr("manifest.json", json.dumps({"version": 1, "kind": "backup", "flavor": "retail",
                                                     "flavor_folder": "_retail_", "parts": ["WTF"],
                                                     "files": [{"path": "WTF/a.txt", "size": 1, "mtime": 0}]}))
        with self.assertRaises(RestoreError):
            open_backup(path)

    @unittest.skipIf(os.name == "nt", "device names are refused on Windows")
    def test_device_named_folders_open_on_posix(self):
        names = ["WTF/Account/A/Realm/Aux/x.lua", "Interface/AddOns/Con/x.lua"]
        contents = open_backup(write_fake_zip(self.tmp / "aux.zip", names))
        self.assertIn("Account/A/Realm/Aux/x.lua", contents.files["WTF"])

    def test_pre_1970_file_round_trips(self):
        # A zeroed Windows FILETIME (1601) or a wrong clock gives a negative st_mtime; our own backup must open.
        cfg = self.wow / "_retail_" / "WTF" / "Config.wtf"
        try:
            os.utime(cfg, (-11644473600, -11644473600))
        except (OSError, OverflowError, ValueError):
            self.skipTest("this filesystem cannot hold a pre-1970 time")
        with capture_events():
            path = back_up(scan_flavor(self.flavor, with_stats=False), self.root, keep=10,
                           now=datetime(2026, 10, 4, 16, 0, 0)).path
        contents = open_backup(path)
        self.assertLess(contents.files["WTF"]["Config.wtf"][1], 0)
        self.assertEqual(open_backup(write_fake_zip(self.tmp / "neg.zip", ["WTF/a.txt"], mtime=-1.0))
                         .files["WTF"]["a.txt"][1], -1.0)

    def test_sharp_s_is_not_ss(self):
        # NTFS compares with a simple upcase table: "Straße.lua" and "STRASSE.lua" are two files.
        contents = open_backup(write_fake_zip(self.tmp / "ss.zip", ["WTF/Straße.lua", "WTF/STRASSE.lua"]))
        self.assertEqual(set(contents.files["WTF"]), {"Straße.lua", "STRASSE.lua"})

    def test_sizes_of_no_parts_is_empty(self):
        self.assertEqual(open_backup(self.backup).sizes(()), {})

    def test_refuses_unknown_manifest(self):
        path = self.tmp / "v2.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"version": 2, "kind": "backup"}))
        with self.assertRaisesRegex(RestoreError, "not an Interface Backup zip"):
            open_backup(path)


class PlanRestoreTest(RestoreTestBase):
    def test_removed_and_newer(self):
        new = self.wow / "_retail_" / "Interface" / "AddOns" / "WeakAuras" / "WeakAuras.lua"
        new.parent.mkdir(parents=True)
        new.write_text("wa", encoding="utf-8")
        cfg = self.wow / "_retail_" / "WTF" / "Config.wtf"
        later = time.time() + 3600
        os.utime(cfg, (later, later))
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface", "WTF"))
        self.assertEqual(plan.removed, [("Interface", "AddOns/WeakAuras/WeakAuras.lua")])
        self.assertEqual(plan.newer, [("WTF", "Config.wtf")])
        self.assertEqual(plan.parts, ("Interface", "WTF"))
        self.assertEqual(plan.flavor, self.flavor)
        self.assertEqual(plan.bytes_needed, sum(open_backup(self.backup).sizes().values()))
        self.assertEqual(plan.leftovers, [])

    def test_unchanged_has_no_warnings(self):
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface", "WTF"))
        self.assertEqual((plan.removed, plan.newer, plan.links_kept, plan.links_removed), ([], [], [], []))

    def test_only_chosen_parts(self):
        (self.wow / "_retail_" / "WTF" / "extra.txt").write_text("e", encoding="utf-8")
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        self.assertEqual(plan.removed, [])
        contents = open_backup(self.backup)
        self.assertEqual(plan.bytes_needed, sum(contents.sizes(("Interface",)).values()))

    def test_case_difference_is_the_same_file(self):
        cfg = self.wow / "_retail_" / "WTF" / "Config.wtf"
        cfg.rename(cfg.with_name("CONFIG.WTF"))
        plan = plan_restore(open_backup(self.backup), self.scan(), ("WTF",))
        self.assertEqual(plan.removed, [])

    def test_links_kept(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        _symlink(self, repo, self.wow / "_retail_" / "Interface" / "AddOns" / "Dev")
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        self.assertEqual(plan.links_kept, [("Interface", "AddOns/Dev")])
        self.assertEqual(plan.links_removed, [])

    def test_link_where_backup_has_files_is_removed(self):
        addons = self.wow / "_retail_" / "Interface" / "AddOns"
        repo = self.tmp / "repo"
        repo.mkdir()
        os.rename(addons / "Details", self.tmp / "details-moved")
        _symlink(self, repo, addons / "details")  # case differs from the backup's folder: same folder on Windows
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        self.assertEqual(plan.links_removed, [("Interface", "AddOns/details")])
        self.assertEqual(plan.links_kept, [])

    def test_part_missing_from_backup_refused(self):
        with capture_events():
            wtf_only = back_up(scan_flavor(self.flavors["_anniversary_"], with_stats=False), self.root, keep=10,
                               now=NOW).path
        contents = open_backup(wtf_only)
        with self.assertRaisesRegex(RestoreError, "Interface"):
            plan_restore(contents, self.scan("_anniversary_"), ("Interface",))
        self.assertEqual(plan_restore(contents, self.scan("_anniversary_"), ("WTF",)).parts, ("WTF",))

    def test_unknown_or_no_part_refused(self):
        for parts in (("interface",), ("Interface", "Wtf"), ()):
            with self.subTest(parts=parts), self.assertRaises(RestoreError):
                plan_restore(open_backup(self.backup), self.scan(), parts)

    def test_sharp_s_live_file_is_removed(self):
        # The backup has no "Strasse.lua"; a live one is lost by the restore even though casefold() would match a
        # backed-up "Straße.lua".
        (self.wow / "_retail_" / "WTF" / "Straße.lua").write_text("a", encoding="utf-8")
        with capture_events():
            path = back_up(scan_flavor(self.flavor, with_stats=False), self.root, keep=10,
                           now=datetime(2026, 10, 4, 16, 0, 0)).path
        (self.wow / "_retail_" / "WTF" / "Straße.lua").rename(self.wow / "_retail_" / "WTF" / "Strasse.lua")
        plan = plan_restore(open_backup(path), self.scan(), ("WTF",))
        self.assertEqual(plan.removed, [("WTF", "Strasse.lua")])

    def test_unreadable_folders_reported(self):
        scan = self.scan()
        scan.parts["WTF"].errors.append("WTF/Account: access denied")
        scan.parts["Interface"].errors.append("Interface/AddOns/X: access denied")
        plan = plan_restore(open_backup(self.backup), scan, ("WTF",))
        self.assertEqual(plan.unreadable, ["WTF/Account: access denied"])
        self.assertEqual(plan_restore(open_backup(self.backup), self.scan(), ("WTF",)).unreadable, [])

    def test_other_flavor_refused(self):
        with self.assertRaisesRegex(RestoreError, "own flavor"):
            plan_restore(open_backup(self.backup), self.scan("_anniversary_"), ("WTF",))

    def test_linked_part_refused(self):
        wtf = self.wow / "_retail_" / "WTF"
        os.rename(wtf, self.tmp / "wtf-moved")
        _symlink(self, self.tmp / "wtf-moved", wtf)
        with self.assertRaisesRegex(RestoreError, "link"):
            plan_restore(open_backup(self.backup), self.scan(), ("WTF",))

    def test_missing_part_on_disk_restores_everything(self):
        os.rename(self.wow / "_retail_" / "WTF", self.tmp / "wtf-moved")
        plan = plan_restore(open_backup(self.backup), self.scan(), ("WTF",))
        self.assertEqual((plan.removed, plan.newer), ([], []))

    def test_leftovers_listed(self):
        (self.wow / "_retail_" / "Interface.restoring").mkdir()
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        self.assertEqual(plan.leftovers, [self.wow / "_retail_" / "Interface.restoring"])

    def test_low_space(self):
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",),
                            disk_usage=lambda p: Usage(0, 0, 1))
        self.assertTrue(plan.low_space)
        roomy = plan_restore(open_backup(self.backup), self.scan(), ("Interface",),
                             disk_usage=lambda p: Usage(0, 0, 10 ** 12))
        self.assertFalse(roomy.low_space)

    def test_free_space_unknown(self):
        def fail(path):
            raise OSError("no drive")

        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",), disk_usage=fail)
        self.assertIsNone(plan.free_bytes)
        self.assertFalse(plan.low_space)


class RunRestoreTest(RestoreTestBase):
    def setUp(self):
        super().setUp()
        self.journal_dir = self.wow / "wow-tools" / "interface-backup" / "journal"
        self.retail = self.wow / "_retail_"

    def run_restore(self, parts=("Interface", "WTF"), **kw):
        plan = plan_restore(open_backup(self.backup), self.scan(), parts)
        with capture_events():
            return restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10, **kw)

    def assert_no_staging(self):
        self.assertFalse(list(self.retail.glob("*.restoring")) + list(self.retail.glob("*.replaced")))

    def test_exact_replace_both_parts(self):
        (self.retail / "Interface" / "AddOns" / "WeakAuras").mkdir()
        (self.retail / "Interface" / "AddOns" / "WeakAuras" / "wa.lua").write_text("wa", encoding="utf-8")
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"changed")
        result = self.run_restore()
        self.assertEqual([p.kind for p in result.parts], ["restored", "restored"])
        self.assertTrue(result.ok)
        self.assertFalse((self.retail / "Interface" / "AddOns" / "WeakAuras").exists())
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"SET a 1\n")
        self.assertEqual((self.retail / "Interface" / "AddOns" / "Details" / "core.lua").read_bytes(), b"det")
        self.assert_no_staging()
        self.assertTrue(result.safety_zip.exists())
        self.assertTrue(result.safety_zip.name.startswith("pre-restore-retail-"))
        safety = open_backup(result.safety_zip)
        self.assertEqual(safety.kind, "pre-restore")
        self.assertIn("AddOns/WeakAuras/wa.lua", safety.files["Interface"])
        journal = read_restore_journal(result.journal_path)
        self.assertEqual([e["action"] for e in journal.entries], ["safety_backup", "replaced", "replaced"])
        self.assertEqual(journal.entries[0]["zip"], result.safety_zip)
        self.assertEqual(journal.entries[0]["parts_existing"], ["Interface", "WTF"])
        self.assertEqual(journal.header["flavor"], "_retail_")
        self.assertEqual(journal.header["flavor_path"], self.retail)
        self.assertEqual(journal.header["backup"], self.backup)
        self.assertIsNotNone(journal.finished)
        self.assertEqual(latest_undoable(self.journal_dir), result.journal_path)

    def test_events_and_stages(self):
        stages = []
        plan = plan_restore(open_backup(self.backup), self.scan(), ("WTF",))
        with capture_events() as events:
            restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10,
                    progress=lambda stage, *rest: stages.append(stage))
        names = [e["event"] for e in events]
        self.assertEqual(names[0], "ibackup.restore_started")
        self.assertIn("ibackup.safety_created", names)
        self.assertIn("ibackup.part_restored", names)
        completed = next(e for e in events if e["event"] == "ibackup.restore_completed")
        self.assertEqual(completed["level"], "info")
        self.assertEqual(completed["data"]["parts"], {"WTF": "restored"})
        for stage in ("verify", "safety", "safety_verify", "extract", "swap", "cleanup"):
            self.assertIn(stage, stages)

    def test_single_part_leaves_other_alone(self):
        (self.retail / "WTF" / "extra.txt").write_text("e", encoding="utf-8")
        result = self.run_restore(("Interface",))
        self.assertTrue((self.retail / "WTF" / "extra.txt").exists())
        self.assertEqual(open_backup(result.safety_zip).parts, ("Interface",))

    def test_mtimes_restored(self):
        cfg = self.retail / "WTF" / "Config.wtf"
        before = open_backup(self.backup).files["WTF"]["Config.wtf"][1]
        cfg.write_bytes(b"changed")
        os.utime(cfg, (before + 1000, before + 1000))
        self.run_restore(("WTF",))
        self.assertAlmostEqual(cfg.stat().st_mtime, before, delta=1)

    def test_time_that_cannot_be_set_is_left(self):
        real = os.utime

        def refuse(path, *args, **kwargs):
            if ".restoring" in str(path):
                raise OverflowError("timestamp out of range for platform time_t")
            return real(path, *args, **kwargs)

        with patch("os.utime", refuse):
            result = self.run_restore(("WTF",))
        self.assertEqual(result.parts[0].kind, "restored")
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"SET a 1\n")

    def test_part_missing_on_disk_is_created(self):
        shutil.rmtree(self.retail / "Interface")
        result = self.run_restore(("Interface",))
        self.assertEqual(result.parts[0].kind, "restored")
        self.assertTrue((self.retail / "Interface" / "AddOns" / "Details" / "core.lua").exists())
        journal = read_restore_journal(result.journal_path)
        self.assertEqual(journal.entries[0]["parts_existing"], [])
        self.assertIs(journal.entries[1]["existed"], False)

    def test_swap_failure_rolls_back_exactly(self):
        (self.retail / "Interface" / "new.txt").write_text("n", encoding="utf-8")
        real = os.rename

        def flaky(src, dst):
            if str(src).endswith("Interface.restoring"):
                raise PermissionError(13, "locked by WoW")
            real(src, dst)

        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        with capture_events() as events:
            result = restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10, rename=flaky)
        self.assertEqual(result.parts[0].kind, "rolled_back")
        self.assertFalse(result.ok)
        self.assertIn("locked by WoW", result.parts[0].reason)
        self.assertTrue((self.retail / "Interface" / "new.txt").exists())
        self.assert_no_staging()
        self.assertIn("ibackup.part_rolled_back", [e["event"] for e in events])
        completed = next(e for e in events if e["event"] == "ibackup.restore_completed")
        self.assertEqual(completed["level"], "warning")
        self.assertIsNone(latest_undoable(self.journal_dir))  # nothing was replaced: nothing to undo

    def test_first_rename_failure_rolls_back(self):
        (self.retail / "Interface" / "new.txt").write_text("n", encoding="utf-8")
        real = os.rename

        def flaky(src, dst):
            if str(dst).endswith("Interface.replaced"):
                raise PermissionError(13, "locked by WoW")
            real(src, dst)

        result = self.run_restore(("Interface", "WTF"), rename=flaky)
        self.assertEqual([p.kind for p in result.parts], ["rolled_back", "restored"])
        self.assertTrue((self.retail / "Interface" / "new.txt").exists())
        self.assert_no_staging()
        journal = read_restore_journal(result.journal_path)
        self.assertEqual([e.get("part") for e in journal.entries], [None, "WTF"])

    def test_swap_failure_puts_kept_links_back(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "dev.lua").write_text("dev", encoding="utf-8")
        link = self.retail / "Interface" / "AddOns" / "Dev"
        _symlink(self, repo, link)
        real = os.rename

        def flaky(src, dst):
            if str(src).endswith("Interface.restoring"):
                raise PermissionError(13, "locked by WoW")
            real(src, dst)

        result = self.run_restore(("Interface",), rename=flaky)
        self.assertEqual(result.parts[0].kind, "rolled_back")
        self.assertTrue(os.path.islink(link))
        self.assertEqual((repo / "dev.lua").read_text(encoding="utf-8"), "dev")
        self.assert_no_staging()

    def test_links_kept_and_target_untouched(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "dev.lua").write_text("dev", encoding="utf-8")
        link = self.retail / "Interface" / "AddOns" / "Dev"
        _symlink(self, repo, link)
        result = self.run_restore(("Interface",))
        self.assertEqual(result.parts[0].kind, "restored")
        self.assertTrue(os.path.islink(link))
        self.assertEqual((repo / "dev.lua").read_text(encoding="utf-8"), "dev")

    def test_link_where_backup_has_files_goes_but_target_stays(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "dev.lua").write_text("dev", encoding="utf-8")
        shutil.rmtree(self.retail / "Interface" / "AddOns" / "Details")
        link = self.retail / "Interface" / "AddOns" / "Details"
        _symlink(self, repo, link)
        self.run_restore(("Interface",))
        self.assertFalse(os.path.islink(link))
        self.assertEqual((link / "core.lua").read_bytes(), b"det")
        self.assertEqual(sorted(p.name for p in repo.iterdir()), ["dev.lua"])

    def test_old_copy_left_is_a_warning(self):
        import wowtools.tools.interface_backup.restore as restore_module
        real = restore_module.remove_tree_no_follow

        def refuse(path):
            if str(path).endswith("WTF.replaced"):
                raise PermissionError(13, "in use")
            real(path)

        with patch.object(restore_module, "remove_tree_no_follow", refuse):
            result = self.run_restore(("WTF",))
        self.assertEqual(result.parts[0].kind, "replaced_left")
        self.assertIn("WTF.replaced", result.parts[0].reason)
        self.assertTrue(result.ok)
        self.assertEqual([e["action"] for e in read_restore_journal(result.journal_path).entries],
                         ["safety_backup", "replaced"])

    def test_leftover_blocks(self):
        (self.retail / "WTF.replaced").mkdir()
        with self.assertRaises(RestoreError):
            self.run_restore(("Interface",))
        self.assertFalse(list(self.root.glob("pre-restore-*")))
        self.assertEqual(list_or_empty(self.journal_dir), [])

    def test_corrupt_backup_changes_nothing(self):
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        data = bytearray(self.backup.read_bytes())
        data[40] ^= 0xFF
        self.backup.write_bytes(bytes(data))
        (self.retail / "Interface" / "new.txt").write_text("n", encoding="utf-8")
        with capture_events() as events, self.assertRaises(RestoreError):
            restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10)
        self.assertTrue((self.retail / "Interface" / "new.txt").exists())
        self.assertIsNone(latest_undoable(self.journal_dir))
        self.assertEqual(list_or_empty(self.journal_dir), [])
        self.assertFalse(list(self.root.glob("pre-restore-*")))
        self.assertIn("ibackup.restore_failed", [e["event"] for e in events])

    def test_safety_backup_failure_changes_nothing(self):
        (self.retail / "Interface" / "new.txt").write_text("n", encoding="utf-8")
        with patch("wowtools.tools.interface_backup.restore.write_zip", side_effect=BackupError("disk full")), \
                self.assertRaises(RestoreError):
            self.run_restore(("Interface",))
        self.assertTrue((self.retail / "Interface" / "new.txt").exists())
        self.assertEqual(list_or_empty(self.journal_dir), [])

    def test_journal_that_cannot_be_written_changes_nothing(self):
        self.journal_dir.parent.mkdir(parents=True, exist_ok=True)
        self.journal_dir.write_text("not a folder", encoding="utf-8")
        (self.retail / "Interface" / "new.txt").write_text("n", encoding="utf-8")
        with self.assertRaises(RestoreError):
            self.run_restore(("Interface",))
        self.assertTrue((self.retail / "Interface" / "new.txt").exists())
        self.assertFalse(list(self.root.glob("pre-restore-*")))

    def test_part_turned_link_since_plan_refused(self):
        plan = plan_restore(open_backup(self.backup), self.scan(), ("WTF",))
        repo = self.tmp / "repo"
        (self.retail / "WTF").rename(repo)
        _symlink(self, repo, self.retail / "WTF")
        with capture_events(), self.assertRaises(RestoreError):
            restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10)
        self.assertTrue(os.path.islink(self.retail / "WTF"))
        self.assertEqual((repo / "Config.wtf").read_bytes(), b"SET a 1\n")

    def test_interrupt_while_extracting_leaves_part_as_it_was(self):
        (self.retail / "Interface" / "new.txt").write_text("n", encoding="utf-8")

        def interrupt(stage, *rest):
            if stage == "extract":
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.run_restore(("Interface",), progress=interrupt)
        self.assertTrue((self.retail / "Interface" / "new.txt").exists())
        self.assert_no_staging()

    def test_unexpected_error_stops_with_result(self):
        import wowtools.tools.interface_backup.restore as restore_module
        real = restore_module.replace_part
        calls = []

        def second_fails(*args, **kwargs):
            calls.append(args[3])
            if len(calls) == 2:
                raise TypeError("boom")
            return real(*args, **kwargs)

        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface", "WTF"))
        with patch.object(restore_module, "replace_part", second_fails), capture_events() as events, \
                self.assertRaises(RestoreStopped) as caught:
            restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10)
        self.assertEqual([p.kind for p in caught.exception.result.parts], ["restored"])
        self.assertIn("ibackup.restore_stopped", [e["event"] for e in events])
        journal = read_restore_journal(caught.exception.result.journal_path)
        self.assertEqual([e["action"] for e in journal.entries], ["safety_backup", "replaced"])
        self.assertIsNone(journal.finished)

    def test_journal_and_safety_pruning(self):
        first = self.run_restore(("WTF",))
        plan = plan_restore(open_backup(self.backup), self.scan(), ("WTF",))
        with capture_events():
            second = restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=1)
        self.assertFalse(first.journal_path.exists())
        self.assertFalse(first.safety_zip.exists())
        self.assertTrue(second.journal_path.exists())
        self.assertTrue(second.safety_zip.exists())
        self.assertTrue(self.backup.exists())

    def test_unreadable_journal_keeps_every_safety_zip(self):
        first = self.run_restore(("WTF",))
        with patch("wowtools.tools.interface_backup.journal.read_restore_journal", side_effect=OSError("locked")):
            self.assertIsNone(referenced_safety_zips(self.journal_dir))
        self.assertEqual(referenced_safety_zips(self.journal_dir), {first.safety_zip.name})


def list_or_empty(folder: Path) -> list[Path]:
    return sorted(folder.iterdir()) if folder.is_dir() else []


if __name__ == "__main__":
    unittest.main()
