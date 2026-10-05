"""apply_flavors: one journal per run, WoW-running refusal, stop at the first failing flavor, pruning."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_ace_tree
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.core.journal import list_journals
from wowtools.tools.ace3_profile_manager import editor, multi, ops, report, scanner

WHEN = datetime(2026, 10, 4, 12, 0, 0)


class MultiTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        install = WowInstall(build_ace_tree(self.tmp / "wow"))
        self.retail, self.era = install.flavor("_retail_"), install.flavor("_classic_era_")
        scan = scanner.scan_flavors([self.retail, self.era])
        self.staging = ops.Staging.from_scan(scan)
        self.staging.everyone_to_default(list(self.staging.states))
        for key in list(self.staging.states):
            if self.staging.state(key).file.addon == "Questie":
                self.staging.copy(key, "Default", "Copy")
        self.plan = [(f, [s for s in self.staging.changed() if s.file.flavor == f]) for f in (self.retail, self.era)]

    def run_plan(self, **kwargs):
        options = {"root": self.tmp / "out", "journal_dir": self.tmp / "journal", "keep_journals": 10,
                   "keep_snapshots": 2, "dry_run": False, "now": WHEN}
        options.update(kwargs)
        return multi.apply_flavors(self.plan, **options)

    def test_one_journal_for_both_flavors(self):
        result = self.run_plan()
        self.assertEqual([r.status for r in result.runs], ["done", "done"])
        self.assertEqual(len(list_journals(self.tmp / "journal")), 1)
        self.assertTrue(result.edited)

    def test_wow_running_refuses_everything(self):
        with self.assertRaises(multi.WowRunning) as caught:
            self.run_plan(wow_check=lambda: ["Wow.exe"])
        self.assertEqual(caught.exception.running, ["Wow.exe"])
        self.assertFalse((self.tmp / "journal").exists())

    def test_dry_run_ignores_wow_and_writes_no_journal(self):
        result = self.run_plan(dry_run=True, wow_check=lambda: ["Wow.exe"])
        self.assertTrue(result.would_edit)
        self.assertFalse((self.tmp / "journal").exists())

    def test_stops_at_failing_flavor(self):
        real = editor.apply_flavor

        def failing(flavor, *args, **kwargs):
            if flavor.folder == "_retail_":
                raise editor.ApplyError("boom")
            return real(flavor, *args, **kwargs)
        with patch("wowtools.tools.ace3_profile_manager.multi.apply_flavor", failing):
            result = self.run_plan()
        self.assertEqual([r.status for r in result.runs], ["stopped", "not_started"])
        self.assertEqual(result.stopped.error, "boom")

    def test_prune_edited_zips_keeps_referenced(self):
        result = self.run_plan()
        edited = self.tmp / "out" / "edited"
        stray = edited / "edited-retail-all-20200101-000000.zip"
        stray.write_bytes(b"x")
        removed = multi.prune_edited_zips(self.tmp / "out", self.tmp / "journal")
        self.assertEqual(removed, [stray])
        self.assertTrue(all(o.file for o in result.edited))
        self.assertTrue(any(edited.iterdir()))

    def test_prune_keeps_every_zip_when_a_journal_cannot_be_read(self):
        self.run_plan()
        edited = self.tmp / "out" / "edited"
        zips = sorted(edited.iterdir())
        self.assertTrue(zips)
        with patch("wowtools.tools.ace3_profile_manager.journal.read_profile_journal",
                   side_effect=PermissionError("held")):
            removed = multi.prune_edited_zips(self.tmp / "out", self.tmp / "journal")
        self.assertEqual(removed, [])
        self.assertEqual(sorted(edited.iterdir()), zips)

    def test_failing_flavor_keeps_its_result_for_the_report(self):
        real = editor.apply_flavor
        calls = []

        def flaky(path, data):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("disk full")
            atomic_write_bytes(path, data)

        def with_flaky_write(*args, **kwargs):
            return real(*args, write=flaky, **kwargs)
        with patch("wowtools.tools.ace3_profile_manager.multi.apply_flavor", with_flaky_write):
            result = self.run_plan()
        self.assertEqual([r.status for r in result.runs], ["stopped", "not_started"])
        stopped = result.stopped.result
        self.assertIsNotNone(stopped)
        self.assertIsNotNone(stopped.snapshot)
        self.assertIsNotNone(stopped.backup_zip)
        self.assertEqual(len(result.rolled_back), 1)  # the file written before the failure
        self.assertEqual(len(result.failed), 1)  # the file whose write failed
        self.assertIn("disk full", result.failed[0].detail)
        self.assertEqual(result.edited, [])
        summary = dict(report.apply_summary_rows(result))
        self.assertEqual(summary["Put back after a failure"], "1 file")
        self.assertEqual(summary["Failed"], "1 file")
        self.assertIn("WTF backup (Retail)", summary)
        self.assertIn("Original files (Retail)", summary)
        details = report.apply_detail_rows(result)
        self.assertTrue(any(row[4].startswith("put back") for row in details))
