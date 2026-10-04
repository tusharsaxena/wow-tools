from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.backup import BackupError
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup import backup as backup_module
from wowtools.tools.interface_backup.backup import back_up, back_up_all, write_zip
from wowtools.tools.interface_backup.scanner import scan_flavor

NOW = datetime(2026, 10, 4, 15, 30, 12)


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
        real_open = open

        def locked(path, *args, **kwargs):
            if str(path).endswith("Config.wtf"):
                raise PermissionError(13, "locked", str(path))
            return real_open(path, *args, **kwargs)

        with capture_events(), patch("builtins.open", side_effect=locked):
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
