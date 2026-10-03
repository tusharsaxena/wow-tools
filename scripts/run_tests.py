#!/usr/bin/env python3
"""Run the test suite in parallel: the tests are dealt round-robin into shards, one process per shard.

    python3 scripts/run_tests.py            # one shard per CPU (at most 16)
    python3 scripts/run_tests.py -j 4       # four shards
    python3 scripts/run_tests.py -k tree    # only tests whose id contains "tree"

Same tests as `python3 -m unittest discover -s tests -t .`, which still works. Every test uses its own temp
folder, so shards never share files. Exit code 0 only if every shard passed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_PREFIX = "@@shard-result "


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
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=0).run(unittest.TestSuite(tests))
    summary = {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "skipped": len(result.skipped)}
    print(RESULT_PREFIX + json.dumps(summary), flush=True)
    return 0 if result.wasSuccessful() else 1


def _launch(index: int, count: int, pattern: str | None) -> tuple[int, dict | None, str]:
    command = [sys.executable, str(Path(__file__).resolve()), "--shard", f"{index}/{count}"]
    if pattern:
        command += ["-k", pattern]
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    summary = None
    for line in proc.stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            summary = json.loads(line[len(RESULT_PREFIX):])
    return proc.returncode, summary, proc.stderr


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the wow-tools tests in parallel.")
    parser.add_argument("-j", "--jobs", type=int, default=min(os.cpu_count() or 2, 16), help="number of shards")
    parser.add_argument("-k", dest="pattern", help="only run tests whose id contains this text")
    parser.add_argument("--shard", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.shard:
        index, count = (int(n) for n in args.shard.split("/"))
        return _run_shard(index, count, args.pattern)

    jobs = max(1, args.jobs)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        outcomes = list(pool.map(lambda i: _launch(i, jobs, args.pattern), range(jobs)))
    totals = {"run": 0, "failures": 0, "errors": 0, "skipped": 0}
    ok = True
    for index, (code, summary, stderr) in enumerate(outcomes):
        if summary is not None:
            for key in totals:
                totals[key] += summary[key]
        if code != 0 or summary is None:
            ok = False
            print(f"===== shard {index + 1}/{jobs} failed =====", file=sys.stderr)
            print(stderr, file=sys.stderr)
    elapsed = time.monotonic() - started
    print(f"Ran {totals['run']} tests in {elapsed:.1f}s across {jobs} processes "
          f"({totals['failures']} failures, {totals['errors']} errors, {totals['skipped']} skipped)")
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
