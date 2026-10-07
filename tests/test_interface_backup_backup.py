from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import record_fsyncs, build_interface_tree, build_wow_tree
from wowtools.core.backup import BackupError
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup import backup as backup_module
from wowtools.tools.interface_backup.backup import back_up, back_up_all, write_zip
from wowtools.tools.interface_backup.scanner import scan_flavor

NOW = datetime(2026, 10, 4, 15, 30, 12)


def _symlink(test, target, link, *, folder=False):
    try:
        os.symlink(target, link, target_is_directory=folder)
    except (OSError, NotImplementedError):
        test.skipTest("symlinks not permitted here")


class BackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavors = {f.folder: f for f in WowInstall(self.wow).flavors()}
        self.root = self.tmp / "bk" / "interface-backup"

    def scan(self, folder="_retail_"):
        return scan_flavor(self.flavors[folder], with_stats=False)

    def test_zip_is_fsynced_before_it_is_moved_into_place(self):
        """F-012: a backup (and a pre-restore safety zip) is on the disk before a restore swaps any folder."""
        with record_fsyncs(backup_module) as calls:
            stats = write_zip(self.scan(), self.root / "pre-restore-retail-x.zip", kind="pre-restore",
                              parts=("WTF",))
        size = stats.path.stat().st_size
        self.assertEqual(calls, [("fsync", size), ("rename", size)])

    def test_zip_layout_and_manifest(self):
        with capture_events():
            outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertEqual(outcome.path, self.root / "backup-retail-20261004-153012.zip")
        with zipfile.ZipFile(outcome.path) as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
            self.assertEqual(zf.read("Interface/AddOns/Auctionator/Auctionator.lua"), b"auc")
        self.assertIn("WTF/Config.wtf", names)
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["kind"], "backup")
        self.assertEqual(manifest["flavor"], "retail")
        self.assertEqual(manifest["flavor_folder"], "_retail_")
        self.assertEqual(manifest["parts"], ["Interface", "WTF"])
        self.assertEqual(manifest["parts_existing"], ["Interface", "WTF"])
        self.assertEqual({f["path"] for f in manifest["files"]}, names - {"manifest.json"})
        self.assertEqual(outcome.files, len(names) - 1)
        self.assertEqual(outcome.bytes_in, sum(f["size"] for f in manifest["files"]))
        self.assertEqual(outcome.bytes_zip, outcome.path.stat().st_size)
        self.assertFalse(list(self.root.glob("*.partial")))

    def test_only_wtf_flavor_and_empty_flavor(self):
        with capture_events() as events:
            self.assertEqual(back_up(self.scan("_anniversary_"), self.root, keep=10, now=NOW).kind, "created")
            skipped = back_up(self.scan("_ptr_"), self.root, keep=10, now=NOW)
        self.assertEqual(skipped.kind, "skipped")
        self.assertEqual(skipped.reason, "no Interface or WTF folder")
        self.assertIn("ibackup.backup_skipped", [e["event"] for e in events])
        self.assertFalse(list(self.root.glob("backup-ptr-*")))

    def test_vanished_file_is_listed_and_zip_still_verifies(self):
        scan = self.scan()
        (self.wow / "_retail_" / "WTF" / "Config.wtf").unlink()
        with capture_events():
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertEqual(outcome.missing, ["WTF/Config.wtf"])
        with zipfile.ZipFile(outcome.path) as zf:
            self.assertNotIn("WTF/Config.wtf", zf.namelist())

    def test_grown_file_does_not_fail_verification(self):
        scan = scan_flavor(self.flavors["_retail_"], with_stats=True)
        (self.wow / "_retail_" / "WTF" / "Config.wtf").write_bytes(b"much longer than before\n")
        with capture_events():
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        with zipfile.ZipFile(outcome.path) as zf:
            sizes = {f["path"]: f["size"] for f in json.loads(zf.read("manifest.json"))["files"]}
        self.assertEqual(sizes["WTF/Config.wtf"], len(b"much longer than before\n"))

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_file_turned_into_link_after_scan_is_not_followed(self):
        scan = self.scan()
        secret = self.tmp / "secret.txt"
        secret.write_bytes(b"outside")
        config = self.wow / "_retail_" / "WTF" / "Config.wtf"
        config.unlink()
        try:
            os.symlink(secret, config)
        except OSError:
            self.skipTest("symlinks not permitted here")
        with capture_events():
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertEqual(outcome.missing, ["WTF/Config.wtf"])
        with zipfile.ZipFile(outcome.path) as zf:
            self.assertNotIn("WTF/Config.wtf", zf.namelist())

    def test_grown_while_zipping_stores_what_was_read(self):
        config = self.wow / "_retail_" / "WTF" / "Config.wtf"
        grown = b"SET a 1\n" + b"x" * 5000
        real_open, real_fstat = os.open, os.fstat
        opened = []

        def open_(path, *args, **kwargs):
            fd = real_open(path, *args, **kwargs)
            if str(path).endswith("Config.wtf"):
                opened.append(fd)
                if os.name == "nt":  # stat taken before the open there
                    config.write_bytes(grown)
            return fd

        def fstat(fd):
            st = real_fstat(fd)
            if fd in opened:
                config.write_bytes(grown)  # after write_zip's stat, before the read
            return st

        scan = self.scan()
        with capture_events(), patch("os.open", side_effect=open_), patch("os.fstat", side_effect=fstat):
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        with zipfile.ZipFile(outcome.path) as zf:
            self.assertEqual(zf.read("WTF/Config.wtf"), grown)
            sizes = {f["path"]: f["size"] for f in json.loads(zf.read("manifest.json"))["files"]}
            self.assertEqual(zf.getinfo("WTF/Config.wtf").file_size, len(grown))
        self.assertEqual(sizes["WTF/Config.wtf"], len(grown))

    def test_addon_folder_turned_link_after_scan_is_not_followed(self):
        if not hasattr(os, "symlink"):
            self.skipTest("needs symlinks")
        scan = self.scan()
        repo = self.tmp / "devrepo"
        repo.mkdir()
        (repo / "Auctionator.lua").write_bytes(b"REPO")
        addon = self.wow / "_retail_" / "Interface" / "AddOns" / "Auctionator"
        shutil.rmtree(addon)
        _symlink(self, repo, addon, folder=True)
        with capture_events():
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        scanned = {f"Interface/{f.rel}" for f in scan.parts["Interface"].files if f.rel.startswith("AddOns/Auctionator/")}
        self.assertIn("Interface/AddOns/Auctionator/Auctionator.lua", scanned)
        self.assertEqual(set(outcome.missing), scanned)
        with zipfile.ZipFile(outcome.path) as zf:
            names = zf.namelist()
            self.assertFalse([n for n in names if n.startswith("Interface/AddOns/Auctionator/")])
            self.assertIn("Interface/AddOns/Details/core.lua", names)
            self.assertFalse([n for n in names if zf.read(n) == b"REPO"])

    def test_part_folder_turned_link_after_scan_is_not_followed_or_claimed(self):
        if not hasattr(os, "symlink"):
            self.skipTest("needs symlinks")
        scan = self.scan()
        outside = self.tmp / "outside-wtf"
        outside.mkdir()
        (outside / "Config.wtf").write_bytes(b"OUTSIDE")
        wtf = self.wow / "_retail_" / "WTF"
        shutil.rmtree(wtf)
        _symlink(self, outside, wtf, folder=True)
        with capture_events():
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertEqual(outcome.missing, ["WTF"])
        with zipfile.ZipFile(outcome.path) as zf:
            self.assertFalse([n for n in zf.namelist() if n.startswith("WTF/")])
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["parts"], ["Interface"])
        self.assertEqual(manifest["parts_existing"], ["Interface"])

    def test_file_swapped_for_link_between_lstat_and_open_is_not_followed(self):
        if not getattr(os, "O_NOFOLLOW", 0) or not hasattr(os, "symlink"):
            self.skipTest("needs O_NOFOLLOW and symlinks")
        config = self.wow / "_retail_" / "WTF" / "Config.wtf"
        secret = self.tmp / "secret.txt"
        secret.write_bytes(b"outside")
        real_open = os.open

        def swap(path, *args, **kwargs):
            if str(path).endswith("Config.wtf"):
                config.unlink()
                _symlink(self, secret, config)
            return real_open(path, *args, **kwargs)

        scan = self.scan()
        with capture_events(), patch("os.open", side_effect=swap):
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertIn("WTF/Config.wtf", outcome.missing)
        with zipfile.ZipFile(outcome.path) as zf:
            self.assertNotIn("WTF/Config.wtf", zf.namelist())

    @unittest.skipIf(os.name == "nt", "Windows has no O_NOFOLLOW: it lstats before the open")
    def test_no_lstat_per_file_on_posix(self):
        scan = self.scan()
        files = {str(part.path.joinpath(*info.rel.split("/"))) for part in scan.parts.values() for info in part.files}
        real = os.lstat
        seen = []

        def lstat(path, *args, **kwargs):
            seen.append(str(path))
            return real(path, *args, **kwargs)

        with capture_events(), patch("os.lstat", lstat):
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertTrue(files)
        self.assertEqual(sorted(files & set(seen)), [])

    @unittest.skipIf(not hasattr(os, "mkfifo"), "needs FIFOs")
    def test_file_turned_fifo_is_left_out_without_waiting(self):
        scan = self.scan()
        config = self.wow / "_retail_" / "WTF" / "Config.wtf"
        config.unlink()
        os.mkfifo(config)
        with capture_events():
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertIn("WTF/Config.wtf", outcome.missing)

    def test_part_folder_gone_after_scan_is_not_claimed(self):
        scan = self.scan()
        shutil.rmtree(self.wow / "_retail_" / "WTF")
        with capture_events():
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertEqual(outcome.missing, ["WTF"])
        with zipfile.ZipFile(outcome.path) as zf:
            self.assertEqual(json.loads(zf.read("manifest.json"))["parts_existing"], ["Interface"])

    def test_part_whose_files_all_vanished_is_not_claimed(self):
        scan = self.scan()
        for info in scan.parts["WTF"].files:
            (self.wow / "_retail_" / "WTF").joinpath(*info.rel.split("/")).unlink()
        stats = write_zip(scan, self.root / "backup-retail-x.zip", kind="backup", parts=("Interface", "WTF"))
        self.assertEqual(stats.parts_existing, ["Interface"])
        self.assertEqual(stats.missing, [f"WTF/{f.rel}" for f in scan.parts["WTF"].files] + ["WTF"])
        with zipfile.ZipFile(stats.path) as zf:
            self.assertEqual(json.loads(zf.read("manifest.json"))["parts"], ["Interface"])

    def test_empty_part_folder_is_still_claimed(self):
        empty = self.flavors["_classic_era_"]
        scan = scan_flavor(empty, with_stats=False)
        for part in scan.parts.values():
            if part.exists:
                shutil.rmtree(part.path)
                part.path.mkdir()
                part.files.clear()
                part.links.clear()
        stats = write_zip(scan, self.root / "backup-classic_era-x.zip", kind="backup")
        self.assertEqual(stats.missing, [])
        self.assertEqual(stats.parts_existing, [p for p in ("Interface", "WTF") if scan.parts[p].exists])

    def test_nothing_readable_fails_the_backup(self):
        scan = self.scan()
        shutil.rmtree(self.wow / "_retail_" / "Interface")
        shutil.rmtree(self.wow / "_retail_" / "WTF")
        with capture_events():
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "failed")
        self.assertIn("nothing could be read", outcome.reason)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_linked_part_is_reported(self):
        if not hasattr(os, "symlink"):
            self.skipTest("needs symlinks")
        outside = self.tmp / "outside-wtf"
        outside.mkdir()
        wtf = self.wow / "_retail_" / "WTF"
        shutil.rmtree(wtf)
        _symlink(self, outside, wtf, folder=True)
        with capture_events() as events:
            outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertEqual(outcome.links, ["WTF"])
        with zipfile.ZipFile(outcome.path) as zf:
            self.assertEqual(json.loads(zf.read("manifest.json"))["links"], ["WTF"])
        self.assertIn("ibackup.links_skipped", [e["event"] for e in events])

    def test_flavor_with_only_linked_parts_says_so(self):
        if not hasattr(os, "symlink"):
            self.skipTest("needs symlinks")
        for name in ("Interface", "WTF"):
            outside = self.tmp / f"outside-{name}"
            outside.mkdir()
            part = self.wow / "_retail_" / name
            shutil.rmtree(part)
            _symlink(self, outside, part, folder=True)
        with capture_events() as events:
            outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "skipped")
        self.assertEqual(outcome.reason, "Interface and WTF are links (not followed)")
        self.assertEqual(outcome.links, ["Interface", "WTF"])
        skipped = [e for e in events if e["event"] == "ibackup.backup_skipped"]
        self.assertEqual(skipped[0]["data"]["links"], ["Interface", "WTF"])

    def test_prune_never_deletes_the_new_backup_even_if_others_are_stamped_later(self):
        self.root.mkdir(parents=True)
        for day in (5, 6, 7):
            (self.root / f"backup-retail-202611{day:02d}-000000.zip").write_bytes(b"z")
        for keep, left in ((2, 2), (1, 1)):
            with self.subTest(keep=keep), capture_events():
                outcome = back_up(self.scan(), self.root, keep=keep, now=NOW)
                self.assertEqual(outcome.kind, "created")
                self.assertTrue(outcome.path.exists())
                self.assertNotIn(outcome.path, outcome.pruned)
                self.assertEqual(len(list(self.root.glob("backup-retail-*.zip"))), left)

    def test_links_are_reported(self):
        scan = self.scan()
        scan.parts["Interface"].links.append("AddOns/DevAddon")
        with capture_events() as events:
            outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.links, ["Interface/AddOns/DevAddon"])
        with zipfile.ZipFile(outcome.path) as zf:
            self.assertEqual(json.loads(zf.read("manifest.json"))["links"], ["Interface/AddOns/DevAddon"])
        self.assertIn("ibackup.links_skipped", [e["event"] for e in events])

    def test_verify_failure_leaves_no_partial(self):
        with capture_events() as events, \
                patch.object(backup_module, "verify_backup", side_effect=BackupError("corrupt")):
            outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "failed")
        self.assertEqual(outcome.reason, "corrupt")
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertIn("ibackup.backup_failed", [e["event"] for e in events])

    def test_interrupt_leaves_no_partial(self):
        with patch.object(backup_module, "verify_backup", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            write_zip(self.scan(), self.root / "backup-retail-x.zip", kind="backup")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unreadable_file_fails_the_backup(self):
        real_open = os.open

        def locked(path, *args, **kwargs):
            if str(path).endswith("Config.wtf"):
                raise PermissionError(13, "locked", str(path))
            return real_open(path, *args, **kwargs)

        with capture_events(), patch("os.open", side_effect=locked):
            outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "failed")
        self.assertIn("locked", outcome.reason)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_backup_never_replaced(self):
        self.root.mkdir(parents=True)
        (self.root / "backup-retail-20261004-153012.zip").write_bytes(b"old")
        with capture_events():
            outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.path.name, "backup-retail-20261004-153012-2.zip")
        self.assertEqual((self.root / "backup-retail-20261004-153012.zip").read_bytes(), b"old")

    def test_prune_after_success_only(self):
        self.root.mkdir(parents=True)
        for day in (1, 2, 3):
            (self.root / f"backup-retail-2026100{day}-000000.zip").write_bytes(b"z")
        with capture_events() as events:
            outcome = back_up(self.scan(), self.root, keep=2, now=NOW)
        self.assertEqual(len(outcome.pruned), 2)
        self.assertIn("ibackup.pruned", [e["event"] for e in events])
        with capture_events(), patch.object(backup_module, "verify_backup", side_effect=BackupError("corrupt")):
            failed = back_up(self.scan(), self.root, keep=1, now=NOW)
        self.assertEqual(failed.pruned, [])
        self.assertEqual(len(list(self.root.glob("backup-retail-*.zip"))), 2)

    def test_progress_stages(self):
        seen = []
        with capture_events():
            back_up(self.scan(), self.root, keep=10, now=NOW, progress=lambda stage, *rest: seen.append(stage))
        self.assertEqual(list(dict.fromkeys(seen)), ["backup", "verify", "prune"])

    def test_broken_progress_never_stops_the_backup(self):
        def broken(*args):
            raise RuntimeError("display gone")

        with capture_events():
            self.assertEqual(back_up(self.scan(), self.root, keep=10, now=NOW, progress=broken).kind, "created")

    def test_all_flavors_continue_after_a_failure_and_log(self):
        scans = [self.scan("_retail_"), self.scan("_classic_era_")]
        real = backup_module.write_zip
        started = []

        def flaky(scan, dest, **kw):
            if scan.flavor.folder == "_retail_":
                raise BackupError("disk full")
            return real(scan, dest, **kw)

        with capture_events() as events, patch.object(backup_module, "write_zip", side_effect=flaky):
            outcomes = back_up_all(scans, self.root, keep=10, on_flavor=started.append)
        self.assertEqual([o.kind for o in outcomes], ["failed", "created"])
        self.assertEqual(outcomes[0].reason, "disk full")
        self.assertEqual(len(started), 2)
        names = [e["event"] for e in events]
        self.assertEqual(names[0], "ibackup.backup_started")
        self.assertIn("ibackup.backup_failed", names)
        self.assertIn("ibackup.backup_created", names)

    def test_write_zip_selected_parts_for_safety(self):
        stats = write_zip(self.scan(), self.root / "pre-restore-retail-x.zip", kind="pre-restore", parts=("WTF",))
        with zipfile.ZipFile(stats.path) as zf:
            self.assertTrue(all(n.startswith("WTF/") or n == "manifest.json" for n in zf.namelist()))
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["kind"], "pre-restore")
        self.assertEqual(manifest["parts_existing"], ["WTF"])
        self.assertEqual(stats.parts_existing, ["WTF"])

    def test_old_mtime_is_stored_with_the_zip_epoch(self):
        config = self.wow / "_retail_" / "WTF" / "Config.wtf"
        os.utime(config, (0, 0))
        stats = write_zip(self.scan(), self.root / "backup-retail-x.zip", kind="backup")
        with zipfile.ZipFile(stats.path) as zf:
            self.assertEqual(zf.getinfo("WTF/Config.wtf").date_time, (1980, 1, 1, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
