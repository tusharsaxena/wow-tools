#!/usr/bin/env python3
"""Run the test suite in parallel: the tests are dealt round-robin into shards, one process per shard.

    python3 scripts/run_tests.py            # one shard per CPU (at most 16)
    python3 scripts/run_tests.py -j 4       # four shards
    python3 scripts/run_tests.py -k tree    # only tests whose id contains "tree"
    python3 scripts/run_tests.py --timeout 0  # no per-shard time limit

Same tests as `python3 -m unittest discover -s tests -t .`, which still works. Every test uses its own temp
folder, so shards never share files. Exit code 0 only if every shard passed. A shard still running after its
timeout (a hung test) is killed with everything it started and reported as failed, naming the test it was running
(or saying its tests had all finished).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_PREFIX = "@@shard-result "
RUNNING_PREFIX = "@@shard-running "
# Seconds a shard may run by default when the suite is split four or more ways (as in CI); narrower runs get
# proportionally more: -j 2 doubles it, -j 1 quadruples it. A 16-way shard takes under two minutes today, a
# one-shard (-j 1) run about 15 on WSL /mnt/d.
DEFAULT_TIMEOUT = 600


def default_timeout(jobs: int) -> float:
    return DEFAULT_TIMEOUT * max(1.0, 4 / jobs)


class _ShardResult(unittest.TextTestResult):
    """Prints each test's id to stdout as it starts, so a shard killed on timeout names the test it hung in."""

    def startTest(self, test):
        print(RUNNING_PREFIX + test.id(), flush=True)
        super().startTest(test)


def _flatten(suite: unittest.TestSuite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _flatten(test)
        else:
            yield test


def _discover(pattern: str | None) -> list[unittest.TestCase]:
    sys.path.insert(0, str(ROOT))
    from wowtools.core.bootstrap import add_vendor_path

    add_vendor_path()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    tests = sorted(_flatten(suite), key=lambda t: t.id())
    return [t for t in tests if pattern is None or pattern in t.id()]


def _run_shard(index: int, count: int, pattern: str | None) -> int:
    """Child process: run every count-th test starting at index, then print a one-line JSON summary."""
    tests = _discover(pattern)[index::count]
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=0, resultclass=_ShardResult)
    result = runner.run(unittest.TestSuite(tests))
    summary = {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "skipped": len(result.skipped)}
    print(RESULT_PREFIX + json.dumps(summary), flush=True)
    return 0 if result.wasSuccessful() else 1


def _shard_command(index: int, count: int, pattern: str | None) -> list[str]:
    command = [sys.executable, str(Path(__file__).resolve()), "--shard", f"{index}/{count}"]
    if pattern:
        command += ["-k", pattern]
    return command


_LIVE: set[subprocess.Popen] = set()  # the shards still running, killed on Ctrl+C
_LIVE_LOCK = threading.Lock()


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill a timed-out shard and everything it started (a git, launcher or updater test's own child)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)  # start_new_session: the group is the shard and its children
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
        proc.wait(timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def _read(handle) -> str:
    handle.seek(0)
    return handle.read().decode("utf-8", errors="replace")


def _timed_out_why(timeout: float, stdout: str) -> str:
    """Name the test a timed-out shard hung in, or say it hung after printing its summary (say, a non-daemon
    thread that kept the interpreter alive once every test had finished)."""
    why = f"timed out after {timeout:g} s"
    if any(line.startswith(RESULT_PREFIX) for line in stdout.splitlines()):
        return why + " after its tests finished"
    running = [line[len(RUNNING_PREFIX):] for line in stdout.splitlines() if line.startswith(RUNNING_PREFIX)]
    return why + (f" in {running[-1]}" if running else " before its first test started")


def _launch(index: int, count: int, pattern: str | None,
            timeout: float | None) -> tuple[int, dict | None, str, str | None]:
    """Run one shard; returns (exit code, its summary or None, its stderr, and on a timeout, why).

    Output goes to temp files, not pipes: after a timeout on Windows, subprocess.run waits with no limit for the
    pipes to close, which a child the hung test started could hold open forever. On a timeout the shard's whole
    process tree is killed (as core.updater does for git)."""
    # Pin the output encoding so a Windows code page can't break decoding of a shard's output.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # POSIX: a session of its own, so killpg reaches the shard's children (and Ctrl+C does not; main kills the
    # live shards then). Windows: taskkill /T follows the process tree itself.
    group = {} if os.name == "nt" else {"start_new_session": True}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(_shard_command(index, count, pattern), cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=err, **group)
        with _LIVE_LOCK:
            _LIVE.add(proc)
        why = None
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            why = _timed_out_why(timeout, _read(out))
        finally:
            with _LIVE_LOCK:
                _LIVE.discard(proc)
        stdout, stderr = _read(out), _read(err)
    summary = None
    for line in stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            summary = json.loads(line[len(RESULT_PREFIX):])
    return (1 if why else proc.returncode), summary, stderr, why


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the wow-tools tests in parallel.")
    parser.add_argument("-j", "--jobs", type=int, default=min(os.cpu_count() or 2, 16), help="number of shards")
    parser.add_argument("-k", dest="pattern", help="only run tests whose id contains this text")
    parser.add_argument("--timeout", type=float,
                        help=f"seconds each shard may run before it is killed and failed (default {DEFAULT_TIMEOUT}, "
                             "more below -j 4; 0 for no limit)")
    parser.add_argument("--shard", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.shard:
        index, count = (int(n) for n in args.shard.split("/"))
        return _run_shard(index, count, args.pattern)

    jobs = max(1, args.jobs)
    timeout = default_timeout(jobs) if args.timeout is None else (args.timeout if args.timeout > 0 else None)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        try:
            outcomes = list(pool.map(lambda i: _launch(i, jobs, args.pattern, timeout), range(jobs)))
        except KeyboardInterrupt:
            with _LIVE_LOCK:
                live = list(_LIVE)
            for proc in live:
                _kill_tree(proc)
            raise
    totals = {"run": 0, "failures": 0, "errors": 0, "skipped": 0}
    ok = True
    for index, (code, summary, stderr, timed_out_why) in enumerate(outcomes):
        if summary is not None:
            for key in totals:
                totals[key] += summary[key]
        if code != 0 or summary is None:
            ok = False
            print(f"===== shard {index + 1}/{jobs} {timed_out_why or 'failed'} =====", file=sys.stderr)
            print(stderr, file=sys.stderr)
    elapsed = time.monotonic() - started
    print(f"Ran {totals['run']} tests in {elapsed:.1f}s across {jobs} processes "
          f"({totals['failures']} failures, {totals['errors']} errors, {totals['skipped']} skipped)")
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
