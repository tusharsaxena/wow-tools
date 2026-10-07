"""core/parallel.py (D10) and the thread safety of what parallel units share: journals and the event log."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from wowtools.core.events import EventLog, capture_events
from wowtools.core.journal import JournalWriter, read_journal
from wowtools.core.parallel import UnitResult, clamp_parallelism, run_units, workers_for
from wowtools.tools.wtf_cleaner.journal import CleanJournal

WAIT = 10  # seconds a synchronisation primitive waits before the test fails (never reached when it passes)


class WorkersTest(unittest.TestCase):
    def test_clamp_and_workers(self):
        self.assertEqual([clamp_parallelism(v) for v in (-1, 0, 1, 2, 8, 9)], [1, 1, 1, 2, 8, 8])
        self.assertEqual(workers_for(8, 3), 3)  # never more threads than units
        self.assertEqual(workers_for(2, 5), 2)
        self.assertEqual(workers_for(0, 5), 1)
        self.assertEqual(workers_for(20, 10), 8)
        self.assertEqual(workers_for(4, 0), 1)


class RunUnitsTest(unittest.TestCase):
    def test_no_units(self):
        with capture_events():
            self.assertEqual(run_units([], lambda u, r: u, parallelism=4), [])

    def test_parallelism_one_is_a_serial_loop_in_the_calling_thread(self):
        calls = []

        def fn(unit, report):
            calls.append((unit, threading.get_ident()))
            return unit * 10

        with capture_events() as records:
            results = run_units([3, 1, 2], fn, parallelism=1, what="test")
        self.assertEqual(calls, [(3, threading.get_ident()), (1, threading.get_ident()), (2, threading.get_ident())])
        self.assertEqual([(r.unit, r.value, r.ok) for r in results], [(3, 30, True), (1, 10, True), (2, 20, True)])
        started = next(r for r in records if r["event"] == "parallel.started")
        self.assertEqual(started["data"], {"what": "test", "units": ["3", "1", "2"], "workers": 1})
        finished = next(r for r in records if r["event"] == "parallel.finished")
        self.assertEqual((finished["data"]["units"], finished["data"]["failed"]), (3, 0))

    def test_a_single_unit_runs_in_the_calling_thread(self):
        with capture_events():
            [result] = run_units(["a"], lambda u, r: threading.get_ident(), parallelism=8)
        self.assertEqual(result.value, threading.get_ident())

    def test_units_really_run_at_the_same_time(self):
        """Each unit waits at a barrier for all three: only three units running at once get past it (run one after
        another, the first would time out and fail)."""
        barrier = threading.Barrier(3, timeout=WAIT)

        def fn(unit, report):
            barrier.wait()
            return threading.current_thread().name

        with capture_events():
            results = run_units(["a", "b", "c"], fn, parallelism=3)
        self.assertTrue(all(r.ok for r in results), [r.error for r in results])
        names = [r.value for r in results]
        self.assertEqual(len(set(names)), 3)
        self.assertTrue(all(n.startswith("wowtools-unit") for n in names), names)

    def test_never_more_than_parallelism_at_once(self):
        lock = threading.Lock()
        running = peak = 0
        both = threading.Barrier(2, timeout=WAIT)

        def fn(unit, report):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            if unit < 2:
                both.wait()  # the first two overlap for sure
            with lock:
                running -= 1
            return unit

        with capture_events():
            results = run_units(list(range(8)), fn, parallelism=2)
        self.assertEqual([r.value for r in results], list(range(8)))
        self.assertEqual(peak, 2)

    def test_results_come_back_in_input_order(self):
        """Unit 0 finishes last (it waits until every later unit is done); the results are still in input order."""
        later_done = threading.Semaphore(0)
        finished = []

        def fn(unit, report):
            if unit == 0:
                for _ in range(3):
                    self.assertTrue(later_done.acquire(timeout=WAIT))
            finished.append(unit)
            if unit:
                later_done.release()
            return f"v{unit}"

        with capture_events():
            results = run_units([0, 1, 2, 3], fn, parallelism=4)
        self.assertEqual(finished[-1], 0)
        self.assertEqual([r.unit for r in results], [0, 1, 2, 3])
        self.assertEqual([r.value for r in results], ["v0", "v1", "v2", "v3"])

    def test_one_unit_failing_never_stops_the_others(self):
        for parallelism in (1, 3):
            with self.subTest(parallelism=parallelism):
                def fn(unit, report):
                    if unit == "bad":
                        raise ValueError("disk on fire")
                    return unit.upper()

                with capture_events() as records:
                    results = run_units(["a", "bad", "c"], fn, parallelism=parallelism, what="backup")
                self.assertEqual([r.value for r in results], ["A", None, "C"])
                self.assertEqual([r.ok for r in results], [True, False, True])
                self.assertIsInstance(results[1].error, ValueError)
                [failed] = [r for r in records if r["event"] == "parallel.unit_failed"]
                self.assertEqual(failed["level"], "error")
                self.assertEqual((failed["data"]["what"], failed["data"]["unit"], failed["data"]["type"],
                                  failed["data"]["message"]), ("backup", "bad", "ValueError", "disk on fire"))
                self.assertIn("disk on fire", failed["data"]["traceback"])
                finished = next(r for r in records if r["event"] == "parallel.finished")
                self.assertEqual(finished["data"]["failed"], 1)

    def test_a_base_exception_propagates_after_running_units_finish(self):
        """KeyboardInterrupt in a unit is not a unit failure: it propagates. In parallel, only once the unit still
        running has finished (the caller's activity.running() must cover every thread)."""
        slow_started, other_done = threading.Event(), threading.Event()

        def fn(unit, report):
            if unit == "stop":
                if parallelism == 2:
                    self.assertTrue(slow_started.wait(WAIT))  # "slow" is running when the interrupt comes
                raise KeyboardInterrupt
            slow_started.set()
            other_done.set()
            return unit

        for parallelism, units in ((1, ["stop", "slow"]), (2, ["slow", "stop"])):
            with self.subTest(parallelism=parallelism):
                slow_started.clear()
                other_done.clear()
                with capture_events(), self.assertRaises(KeyboardInterrupt):
                    run_units(units, fn, parallelism=parallelism)
                # Serial: the loop stops at once. Parallel: run_units returned only after "slow" finished.
                self.assertEqual(other_done.is_set(), parallelism == 2)

    def test_units_not_yet_started_never_start_after_a_base_exception(self):
        """A unit's KeyboardInterrupt stops queued units from starting even while an earlier unit still runs."""
        called = []
        lock = threading.Lock()

        def fn(unit, report):
            with lock:
                called.append(unit)
            if unit == 0:
                self.assertTrue(stop_raised.wait(WAIT))
                time.sleep(0.05)  # the freed thread takes the next unit meanwhile
            if unit == 1:
                stop_raised.set()
                raise KeyboardInterrupt
            return unit

        stop_raised = threading.Event()
        with capture_events(), self.assertRaises(KeyboardInterrupt):
            run_units(range(6), fn, parallelism=2)
        self.assertEqual(sorted(called), [0, 1])

    def test_progress_is_tagged_with_the_unit_and_never_breaks_a_run(self):
        seen = []
        lock = threading.Lock()

        def progress(unit, *args):
            with lock:
                seen.append((unit, *args))
            raise RuntimeError("broken display")

        def fn(unit, report):
            report("zip", 1, 2, f"{unit}/file")
            report("zip", 2, 2, f"{unit}/other")
            return unit

        starts, dones = [], []
        with capture_events():
            results = run_units(["x", "y"], fn, parallelism=2, progress=progress,
                                on_start=lambda u, i, n: starts.append((u, i, n)),
                                on_done=lambda r: dones.append(r))
        self.assertTrue(all(r.ok for r in results))
        self.assertEqual(sorted(seen), [("x", "zip", 1, 2, "x/file"), ("x", "zip", 2, 2, "x/other"),
                                        ("y", "zip", 1, 2, "y/file"), ("y", "zip", 2, 2, "y/other")])
        self.assertEqual(sorted(starts), [("x", 0, 2), ("y", 1, 2)])
        self.assertEqual(sorted(d.unit for d in dones), ["x", "y"])
        self.assertTrue(all(isinstance(d, UnitResult) for d in dones))

    def test_label_names_units_in_the_log(self):
        with capture_events() as records:
            run_units([{"n": 1}], lambda u, r: None, parallelism=2, label=lambda u: f"unit-{u['n']}")
        started = next(r for r in records if r["event"] == "parallel.started")
        self.assertEqual(started["data"]["units"], ["unit-1"])

    def test_stop_on_error_serial_stops_at_the_first_failure(self):
        calls, done = [], []

        def fn(unit, report):
            calls.append(unit)
            if unit == "bad":
                raise ValueError("no")
            return unit

        with capture_events() as records:
            results = run_units(["a", "bad", "c", "d"], fn, parallelism=1, stop_on_error=True,
                                on_done=lambda r: done.append(r.unit))
        self.assertEqual(calls, ["a", "bad"])
        self.assertEqual(done, ["a", "bad"])  # on_done never runs for a unit that never started
        self.assertEqual([(r.started, r.ok) for r in results], [(True, True), (True, False), (False, True),
                                                                (False, True)])
        finished = next(r for r in records if r["event"] == "parallel.finished")
        self.assertEqual((finished["data"]["failed"], finished["data"]["not_started"]), (1, 2))

    def test_stop_on_error_lets_running_units_finish_and_never_starts_queued_ones(self):
        """Two threads: "bad" fails while "slow" runs; "slow" still finishes, "late" (queued) never starts."""
        failed = threading.Event()
        calls = []

        def fn(unit, report):
            calls.append(unit)
            if unit == "bad":
                raise ValueError("no")
            if unit == "slow":
                self.assertTrue(failed.wait(WAIT))
            return unit

        def on_done(result):
            if result.unit == "bad":
                failed.set()

        with capture_events():
            results = run_units(["slow", "bad", "late"], fn, parallelism=2, stop_on_error=True, on_done=on_done)
        self.assertEqual(sorted(calls), ["bad", "slow"])
        self.assertEqual([(r.unit, r.started, r.value) for r in results],
                         [("slow", True, "slow"), ("bad", True, None), ("late", False, None)])

    def test_without_stop_on_error_every_unit_starts(self):
        with capture_events():
            results = run_units(["bad", "b"], lambda u, r: 1 / 0 if u == "bad" else u, parallelism=1)
        self.assertEqual([r.started for r in results], [True, True])


class JournalThreadSafetyTest(unittest.TestCase):
    """What is under test is the lock: lines stay whole and counts right. os.fsync is replaced by a counter, so
    the hammer does not wait on the disk: the writer fsyncs every line under its lock (F-012), and a real
    FlushFileBuffers on a Windows CI runner is slow enough that 1,200 of them in a row outlast WAIT (C1). That every
    line is fsynced as it is written is test_journal's to pin; here the count of fsyncs must still equal the count
    of lines."""
    THREADS = 8
    EACH = 150

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.fsyncs: list[int] = []  # list.append is atomic, so writers on several threads may share it
        patcher = mock.patch("os.fsync", side_effect=self.fsyncs.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def hammer(self, work):
        start = threading.Barrier(self.THREADS, timeout=WAIT)

        def run(index):
            start.wait()
            for n in range(self.EACH):
                work(index, n)

        threads = [threading.Thread(target=run, args=(i,)) for i in range(self.THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(WAIT)
            self.assertFalse(t.is_alive())

    def test_shared_writer_keeps_every_line_whole_and_counts_right(self):
        writer = JournalWriter(self.dir / "journal-1.jsonl", {"tool": "test"})
        self.hammer(lambda i, n: writer.add_entry({"action": "x", "thread": i, "n": n, "pad": "é" * 50}))
        writer.finish()
        writer.close()
        total = self.THREADS * self.EACH
        self.assertEqual(writer.count, total)
        lines = (self.dir / "journal-1.jsonl").read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]  # every line is whole JSON
        self.assertEqual(len(records), total + 2)
        self.assertEqual(len(self.fsyncs), len(records))  # one fsync per line, the header and footer included
        self.assertEqual(records[0]["tool"], "test")
        self.assertEqual(records[-1]["entries"], total)
        journal = read_journal(self.dir / "journal-1.jsonl")
        self.assertEqual(len(journal.entries), total)
        self.assertEqual({(e["thread"], e["n"]) for e in journal.entries},
                         {(i, n) for i in range(self.THREADS) for n in range(self.EACH)})

    def test_clean_journal_add_and_roll_back_from_several_threads(self):
        writer = CleanJournal(self.dir / "journal-2.jsonl", {"tool": "test"})

        def work(i, n):
            writer.add_deleted(flavor=f"f{i}", path=self.dir / f"{n}.lua", rel=f"{n}.lua", size=1, mtime=0.0,
                               zip_path=None, snapshot=None)
            if n % 2:
                writer.add_rolled_back(flavor=f"f{i}", rels=[f"{n}.lua"])

        self.hammer(work)
        writer.close()
        self.assertEqual(writer.count, self.THREADS * self.EACH // 2)
        lines = (self.dir / "journal-2.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len([json.loads(line) for line in lines]), 1 + self.THREADS * self.EACH * 3 // 2)
        self.assertEqual(len(self.fsyncs), len(lines))


class EventLogThreadSafetyTest(unittest.TestCase):
    def test_lines_from_several_threads_stay_whole_and_in_time_order(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ticks = iter(range(10**6))
        base = datetime(2026, 10, 5, 12, 0, 0).astimezone()
        log = EventLog(Path(tmp.name), tool="suite", clock=lambda: base + timedelta(milliseconds=next(ticks)))
        self.addCleanup(log.close)
        start = threading.Barrier(6, timeout=WAIT)

        def run(i):
            start.wait()
            for n in range(100):
                log.emit("ui.selection", screen="t", control=f"{i}", value=n)

        threads = [threading.Thread(target=run, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(WAIT)
        log.close()
        [events_file] = (Path(tmp.name) / "suite").glob("events-*.log")
        records = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 600)
        stamps = [r["ts"] for r in records]
        self.assertEqual(stamps, sorted(stamps))  # the file is in time order
        [text_file] = (Path(tmp.name) / "suite").glob("logfile-*.log")
        text = text_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual([line.split("control=")[1] for line in text],
                         [f"{r['data']['control']} value={r['data']['value']}" for r in records])  # same order


if __name__ == "__main__":
    unittest.main()
