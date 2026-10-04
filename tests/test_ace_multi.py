"""apply_flavors: one journal per run, WoW-running refusal, stop at the first failing flavor, pruning."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.core.journal import list_journals
from wowtools.tools.ace_profiles import editor, multi, ops, scanner

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
        with patch("wowtools.tools.ace_profiles.multi.apply_flavor", failing):
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
