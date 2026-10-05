"""D10 applied (T5.3): every run that goes through core/parallel.py gives the same result with parallelism 1 and 4,
and a failing unit never stops the others where failures are isolated (Interface Backup's back up all)."""
from __future__ import annotations

import tempfile
import threading
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_ace_tree, build_interface_tree, build_screenshot_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.progress import ProgressBoard
from wowtools.tools.ace3_profile_manager import multi as ace_multi
from wowtools.tools.ace3_profile_manager import ops, scanner, undo
from wowtools.tools.ace3_profile_manager.journal import latest_undoable, read_profile_journal
from wowtools.tools.interface_backup import backup as backup_module
from wowtools.tools.interface_backup import scanner as ib_scanner
from wowtools.tools.screenshot_organizer.planner import count_waiting
from wowtools.tools.wtf_cleaner import multi as wtf_multi
from wowtools.tools.wtf_cleaner import scanner as wtf_scanner

NOW = datetime(2026, 10, 4, 15, 30, 12)
WAIT = 10


class TempTree(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)


class InterfaceBackupParallelTest(TempTree):
    def setUp(self):
        super().setUp()
        self.wow = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavors = WowInstall(self.wow).flavors()

    def scans(self, parallelism: int = 1):
        with capture_events():
            return ib_scanner.scan_flavors(self.flavors, with_stats=True, parallelism=parallelism)

    @staticmethod
    def shape(scans):
        return [(s.flavor.folder, {name: (p.exists, p.linked, sorted((f.rel, f.size) for f in p.files))
                                   for name, p in s.parts.items()}, s.leftovers) for s in scans]

    def test_scan_is_the_same_with_parallelism_1_and_4(self):
        self.assertEqual(self.shape(self.scans(1)), self.shape(self.scans(4)))

    def test_scan_logs_every_flavor_with_parallelism_4(self):
        with capture_events() as records:
            ib_scanner.scan_flavors(self.flavors, parallelism=4)
        done = sorted(r["data"]["flavor"] for r in records if r["event"] == "ibackup.scan_completed")
        self.assertEqual(done, sorted(f.folder for f in self.flavors))

    def test_scan_raises_an_unexpected_error_after_the_others(self):
        real = ib_scanner.scan_flavor

        def broken(flavor, **kwargs):
            if flavor.folder == "_retail_":
                raise RuntimeError("boom")
            return real(flavor, **kwargs)

        for parallelism in (1, 4):
            with self.subTest(parallelism=parallelism), capture_events(), \
                    patch.object(ib_scanner, "scan_flavor", broken), self.assertRaises(RuntimeError):
                ib_scanner.scan_flavors(self.flavors, parallelism=parallelism)

    def back_up(self, root: Path, parallelism: int, **kwargs):
        scans = [s for s in self.scans() if s.has_data]
        with capture_events():
            return backup_module.back_up_all(scans, root, keep=10, parallelism=parallelism, **kwargs)

    @staticmethod
    def zip_content(path: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(path) as zf:
            return {n: zf.read(n) for n in zf.namelist() if n != "manifest.json"}

    def test_back_up_all_is_the_same_with_parallelism_1_and_4(self):
        one = self.back_up(self.tmp / "one", 1)
        four = self.back_up(self.tmp / "four", 4)
        self.assertEqual([(o.flavor.folder, o.kind, o.files, o.bytes_in) for o in one],
                         [(o.flavor.folder, o.kind, o.files, o.bytes_in) for o in four])
        self.assertTrue(all(o.kind == "created" for o in one))
        for a, b in zip(one, four):
            self.assertEqual(a.path.name.split("-")[1], b.path.name.split("-")[1])
            self.assertEqual(self.zip_content(a.path), self.zip_content(b.path))
        self.assertEqual(len(list((self.tmp / "four").glob("*.partial"))), 0)

    def test_back_up_all_runs_flavors_at_the_same_time(self):
        """Each flavor's zip waits at a barrier for the others: only flavors backed up at once get past it."""
        scans = [s for s in self.scans() if s.has_data]
        barrier = threading.Barrier(len(scans), timeout=WAIT)
        real = backup_module.write_zip

        def meet(scan, dest, **kwargs):
            barrier.wait()
            return real(scan, dest, **kwargs)

        with patch.object(backup_module, "write_zip", meet):
            outcomes = self.back_up(self.tmp / "bk", len(scans))
        self.assertEqual([o.kind for o in outcomes], ["created"] * len(scans))

    def test_a_failing_flavor_never_stops_the_others(self):
        real = backup_module.write_zip

        def broken(scan, dest, **kwargs):
            if scan.flavor.folder == "_classic_era_":
                raise RuntimeError("cable pulled")  # not a BackupError: an unexpected failure
            return real(scan, dest, **kwargs)

        for parallelism in (1, 4):
            with self.subTest(parallelism=parallelism), patch.object(backup_module, "write_zip", broken):
                root = self.tmp / f"bk{parallelism}"
                outcomes = self.back_up(root, parallelism)
                kinds = {o.flavor.folder: o.kind for o in outcomes}
                self.assertEqual(kinds["_classic_era_"], "failed")
                self.assertEqual({k for f, k in kinds.items() if f != "_classic_era_"}, {"created"})
                failed = next(o for o in outcomes if o.kind == "failed")
                self.assertIn("RuntimeError: cable pulled", failed.reason)
                self.assertEqual(len(list(root.glob("backup-*.zip"))), len(outcomes) - 1)

    def test_on_flavor_and_on_flavor_done_name_every_flavor(self):
        started, ended = [], []
        outcomes = self.back_up(self.tmp / "bk", 4, on_flavor=started.append, on_flavor_done=ended.append)
        names = [o.flavor.display_name for o in outcomes]
        self.assertEqual(sorted(started), sorted(names))
        self.assertEqual(sorted(ended), sorted(names))

    def test_progress_lands_in_each_flavors_own_row(self):
        """The popup's board binds each pool thread to the flavor it backs up: untagged reports go to its row (a
        flavor's "prune" report names it, so it must land in that flavor's row)."""
        scans = [s for s in self.scans() if s.has_data]
        board = ProgressBoard(rows=len(scans), units=len(scans))
        units, prunes = set(), []
        lock = threading.Lock()

        def report(stage, current=0, total=0, detail=None):
            board.report(stage, current, total, detail)
            _version, view = board.snapshot()
            with lock:
                if stage == "prune":
                    row = next(r for r in view.rows if r.stage == "prune" and r.label == detail)
                    prunes.append(row.label)
                units.update(r.label for r in view.rows if r.used)

        with capture_events():
            backup_module.back_up_all(scans, self.tmp / "bk", keep=10, parallelism=4, progress=report,
                                      on_flavor=board.start, on_flavor_done=board.finish)
        board.finish_all()
        names = {s.flavor.display_name for s in scans}
        self.assertEqual(units, names)  # never the unnamed placeholder row
        self.assertEqual(sorted(prunes), sorted(names))
        _version, view = board.snapshot()
        self.assertEqual((view.done, view.units), (len(scans), len(scans)))


class WtfScanParallelTest(TempTree):
    def setUp(self):
        super().setUp()
        self.install = WowInstall(build_wow_tree(self.tmp / "World of Warcraft"))

    @staticmethod
    def shape(scans):
        return [(s.flavor.folder, s.error, s.note,
                 None if s.result is None else (s.result.account_names, s.result.sv_files, s.result.accounts,
                                                 s.result.characters, sorted(s.result.installed)))
                for s in scans]

    def test_scan_is_the_same_with_parallelism_1_and_4(self):
        with capture_events():
            one = wtf_multi.scan_flavors(self.install.flavors(), parallelism=1)
            four = wtf_multi.scan_flavors(self.install.flavors(), parallelism=4)
        self.assertEqual(self.shape(one), self.shape(four))
        self.assertIn("No addons found", four[0].error)  # a ScanError stays that flavor's own

    def test_parallel_progress_adds_every_flavors_counts_up(self):
        reports = []
        with capture_events():
            wtf_multi.scan_flavors(self.install.flavors(), parallelism=4,
                                   progress=lambda c, t, label: reports.append((c, t, label)))
        last_current, last_total, _label = reports[-1]
        self.assertEqual(last_current, last_total)  # every flavor's counts, all done
        single = []
        with capture_events():
            for flavor in self.install.flavors():
                try:
                    wtf_scanner.scan(flavor, progress=lambda c, t, label, f=flavor: single.append((f.folder, t)))
                except wtf_scanner.ScanError:
                    pass
        self.assertEqual(last_total, sum({folder: t for folder, t in single}.values()))
        self.assertTrue(all(" · " in label for _c, _t, label in reports))

    def test_an_unexpected_error_is_raised(self):
        def broken(flavor, **kwargs):
            raise RuntimeError("boom")

        for parallelism in (1, 4):
            with self.subTest(parallelism=parallelism), capture_events(), \
                    patch.object(wtf_multi, "scan", broken), self.assertRaises(RuntimeError):
                wtf_multi.scan_flavors(self.install.flavors(), parallelism=parallelism)


class ScreenshotCountParallelTest(TempTree):
    def test_counts_are_the_same_with_parallelism_1_and_4(self):
        root = build_screenshot_tree(build_wow_tree(self.tmp / "WoW"))
        flavors = WowInstall(root).flavors()
        with capture_events():
            one = count_waiting(flavors, None, parallelism=1)
            four = count_waiting(flavors, None, parallelism=4)
            copy_one = count_waiting(flavors, self.tmp / "dest", copy=True, parallelism=1)
            copy_four = count_waiting(flavors, self.tmp / "dest", copy=True, parallelism=4)
        self.assertEqual(one, four)
        self.assertEqual(copy_one, copy_four)
        self.assertEqual((one["_retail_"], one["_classic_era_"], one["_anniversary_"]), (4, 2, None))
        self.assertEqual(list(four), [f.folder for f in flavors])


class AceUndoParallelTest(TempTree):
    """Undo of a run over Retail and Classic Era: both flavors' WTF snapshots come first, up to parallelism at
    once; the files are put back after both succeeded."""

    def setUp(self):
        super().setUp()
        self.build("wow")

    def build(self, name: str) -> None:
        """An Apply over both flavors in its own tree under tmp/name: self.wow, root, journals, journal, files."""
        self.wow = build_ace_tree(self.tmp / name)
        install = WowInstall(self.wow)
        retail, era = install.flavor("_retail_"), install.flavor("_classic_era_")
        self.root = self.tmp / f"{name}-out"
        self.journals = self.tmp / f"{name}-journal"
        staging = ops.Staging.from_scan(scanner.scan_flavors([retail, era]))
        staging.everyone_to_default(list(staging.states))
        for key in list(staging.states):
            if staging.state(key).file.addon == "Questie":
                staging.copy(key, "Default", "Copy")  # Classic Era's change
        self.files = {s.file.path: s.file.path.read_bytes() for s in staging.changed()}
        plan = [(f, [s for s in staging.changed() if s.file.flavor == f]) for f in (retail, era)]
        with capture_events():
            ace_multi.apply_flavors(plan, root=self.root, journal_dir=self.journals, keep_journals=10,
                                    keep_snapshots=5, dry_run=False, now=NOW)
        self.journal = latest_undoable(self.journals)
        self.assertEqual({e["flavor"] for e in read_profile_journal(self.journal).entries},
                         {"_retail_", "_classic_era_"})

    def undo(self, parallelism: int, **kwargs):
        with capture_events():
            return undo.undo_run(self.journal, wow_root=self.wow, root=self.root, keep_snapshots=5, now=NOW,
                                 parallelism=parallelism, **kwargs)

    def test_undo_is_the_same_with_parallelism_1_and_4(self):
        results = {}
        for parallelism in (1, 4):
            self.build(f"wow{parallelism}")
            result = self.undo(parallelism)
            self.assertEqual({p: p.read_bytes() for p in self.files}, self.files)  # the originals are back
            results[parallelism] = ([(o.flavor, o.rel.split("/", 2)[-1], o.status) for o in result.outcomes],
                                    [p.name for p in result.snapshots])
        self.assertEqual(results[1], results[4])
        self.assertTrue(results[4][0])
        # flavor order, whichever finished first
        self.assertEqual([n.split("-")[1] for n in results[4][1]], ["classic_era", "retail"])

    def test_snapshots_run_at_the_same_time(self):
        barrier = threading.Barrier(2, timeout=WAIT)
        real = undo.take_snapshot

        def meet(*args, **kwargs):
            barrier.wait()
            return real(*args, **kwargs)

        started, ended = [], []
        with patch.object(undo, "take_snapshot", meet):
            result = self.undo(2, on_flavor=started.append, on_flavor_done=ended.append)
        self.assertEqual(len(result.restored), len(self.files))
        self.assertEqual(sorted(f.folder for f in started), ["_classic_era_", "_retail_"])
        self.assertEqual(sorted(f.folder for f in ended), ["_classic_era_", "_retail_"])

    def test_a_failed_snapshot_changes_nothing(self):
        real = undo.take_snapshot

        def broken(flavor, *args, **kwargs):
            if flavor.folder == "_classic_era_":
                raise undo.BackupError("disk full")
            return real(flavor, *args, **kwargs)

        edited = {p: p.read_bytes() for p in self.files}
        for parallelism in (1, 4):
            with self.subTest(parallelism=parallelism), patch.object(undo, "take_snapshot", broken):
                with self.assertRaises(undo.UndoError) as caught:
                    self.undo(parallelism)
                self.assertIn("Nothing was changed", str(caught.exception))
                self.assertEqual({p: p.read_bytes() for p in self.files}, edited)
                self.assertEqual(latest_undoable(self.journals), self.journal)

    def test_serial_stops_at_the_first_failed_snapshot(self):
        calls = []

        def broken(flavor, *args, **kwargs):
            calls.append(flavor.folder)
            raise undo.BackupError("disk full")

        with patch.object(undo, "take_snapshot", broken), self.assertRaises(undo.UndoError):
            self.undo(1)
        self.assertEqual(calls, ["_classic_era_"])  # as before: the next flavor never started

    def test_the_put_back_stage_is_not_counted_as_a_game_version(self):
        """The popup: one row per flavor's snapshot, then the files are put back in a row of their own; the
        overall count stays at 2 of 2 game versions."""
        board = ProgressBoard(rows=2, units=2, label=lambda flavor: flavor.display_name, first_stage="undo")
        self.undo(2, progress=board.report, on_flavor=board.start, on_flavor_done=board.finish)
        _version, view = board.snapshot()
        self.assertEqual((view.done, view.units), (2, 2))
        self.assertIn("undo", [r.stage for r in view.rows])
        board.finish_all()
        _version, view = board.snapshot()
        self.assertEqual((view.done, view.units), (2, 2))


if __name__ == "__main__":
    unittest.main()
