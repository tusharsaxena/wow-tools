#!/usr/bin/env python3
"""Run the test suite in parallel: the tests are dealt into shards by recorded time, one process per shard.

    python3 scripts/run_tests.py            # 1.5 shards per CPU (at most 24; spec F3)
    python3 scripts/run_tests.py -j 4       # four shards
    python3 scripts/run_tests.py -k tree    # only tests whose id contains "tree"
    python3 scripts/run_tests.py --timeout 0  # no per-shard time limit
    python3 scripts/run_tests.py --verbose-shards  # also print each shard's time and test count
    python3 scripts/run_tests.py --windows  # from WSL: the suite under the native Windows Python (spec F1)
    python3 scripts/run_tests.py --all      # from WSL: the WSL and the Windows suites at the same time

Same tests as `python3 -m unittest discover -s tests -t .`, which still works. Every test uses its own temp
folder, so shards never share files. Exit code 0 only if every shard passed. A shard still running after its
timeout (a hung test) is killed with everything it started and reported as failed, naming the test it was running
(or saying its tests had all finished).

Shards are balanced by recorded test time (spec F2): each shard reports how long each of its tests took, the run
merges them into .test-times-<platform>.json at the repo root (gitignored; one file per platform, so a WSL and a
Windows run of one checkout never clobber each other), and the next run deals the tests longest first, each to the
least-loaded shard. A test with no recorded time counts as the median; with no usable cache the tests are dealt
round-robin by id. Each shard gets its explicit list of test ids in a temp file.

--windows runs the suite in this same checkout under the native Windows Python through cmd.exe (`py -3`, or the
command in WOWTOOLS_WINDOWS_PYTHON), passing -k, -j and --timeout through and returning its exit code; on native
Windows it is the normal run, on Linux that is not WSL an error. --all runs both suites at once, each with half the
default shards unless -j is given (then each gets -j), and passes only if both pass.
"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT_PREFIX = "@@shard-result "
RUNNING_PREFIX = "@@shard-running "
# Seconds a shard may run by default when the suite is split four or more ways (as in CI); narrower runs get
# proportionally more: -j 2 doubles it, -j 1 quadruples it. A 16-way shard takes under two minutes today, a
# one-shard (-j 1) run about 15 on WSL /mnt/d.
DEFAULT_TIMEOUT = 600
PID_PREFIX = "@@runner-pid "  # a --windows run's Windows-side runner announces its pid, so Ctrl+C can kill it
WINDOWS_PYTHON_ENV = "WOWTOOLS_WINDOWS_PYTHON"
DEFAULT_WINDOWS_PYTHON = "py -3"
# The cmd.exe command line travels in this variable (shared with Windows through WSLENV) and cmd.exe runs
# %WOWTOOLS_WINDOWS_RUN%: WSL would escape double quotes inside an argument as \", which cmd.exe does not understand.
WINDOWS_RUN_VAR = "WOWTOOLS_WINDOWS_RUN"
SUMMARY_RE = re.compile(r"^Ran \d+ tests in ", re.MULTILINE)  # the last-but-one line of every finished run
PID_WAIT = 10  # Ctrl+C before a Windows runner announced its pid: seconds to wait for the pid line
TIMES_DIR = ROOT  # where the per-platform test-time caches live (tests point it at a temp folder)
TIMES_VERSION = 1
# The default shard count, chosen by measurement (spec F3; docs/testing.md): 1.5 shards per CPU, at most 24. The
# tests spend much of their time waiting (pilots, workers, file I/O), so on 16 CPUs 24 shards beat 16 by 13 % (WSL)
# and 22 % (Windows), and --all at 12 a side beat 8 a side by 11 %; 2 shards per CPU were no faster than 1.5.
MAX_DEFAULT_JOBS = 24


def default_jobs(cpus: int | None = None) -> int:
    """Shards for a run without -j: 1.5 per CPU (os.cpu_count(), two if unknown), at least 1, at most 24."""
    cpus = (os.cpu_count() or 2) if cpus is None else cpus
    return max(1, min(cpus * 3 // 2, MAX_DEFAULT_JOBS))


def default_timeout(jobs: int) -> float:
    return DEFAULT_TIMEOUT * max(1.0, 4 / jobs)


class _ShardResult(unittest.TextTestResult):
    """Prints each test's id to stdout as it starts, so a shard killed on timeout names the test it hung in, and
    times each test: from the end of the one before (or the start of the run), so a class's setUpClass counts
    towards its first test and a shard's times add up to its run."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.times: dict[str, float] = {}
        self._mark = time.perf_counter()

    def startTest(self, test):
        print(RUNNING_PREFIX + test.id(), flush=True)
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        now = time.perf_counter()
        self.times[test.id()] = round(now - self._mark, 4)
        self._mark = now


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


def _discover_ids(pattern: str | None) -> list[str]:
    """The parent's list of test ids to deal into shards, sorted."""
    return [test.id() for test in _discover(pattern)]


def _run_shard(ids_file: str) -> int:
    """Child process: run the tests whose ids are listed in ids_file (in id order), then print a one-line JSON
    summary with each test's time, how many ids it read and the listed ids it did not discover (which fail it)."""
    wanted = set(Path(ids_file).read_text(encoding="utf-8").split())
    tests = [test for test in _discover(None) if test.id() in wanted]
    missing = sorted(wanted - {test.id() for test in tests})
    for test_id in missing:
        print(f"Listed but not found: {test_id}", file=sys.stderr, flush=True)
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=0, resultclass=_ShardResult)
    result = runner.run(unittest.TestSuite(tests))
    summary = {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "skipped": len(result.skipped), "times": result.times, "listed": len(wanted), "missing": missing}
    print(RESULT_PREFIX + json.dumps(summary), flush=True)
    return 0 if result.wasSuccessful() and not missing else 1


def _list_gap(ids: list[str], summary: dict) -> str | None:
    """Why a shard did not run its whole list (it read fewer ids than it was dealt, or did not find some), or None.

    Checked on the list, not on summary["run"]: a class whose setUpClass skips or fails runs fewer tests, rightly."""
    listed, missing = summary.get("listed", len(ids)), summary.get("missing") or []
    if listed != len(ids):
        return f"it read {listed} of the {len(ids)} ids it was dealt"
    if missing:
        return f"{len(missing)} listed tests not found: {', '.join(missing)}"
    return None


def _shard_command(ids_file: Path) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--shard-file", str(ids_file)]


def times_path(host: str | None = None) -> Path:
    """This platform's test-time cache: one file per platform, so concurrent WSL and Windows runs never clash."""
    return TIMES_DIR / f".test-times-{host or host_kind()}.json"


def read_times(path: Path) -> dict[str, float] | None:
    """The recorded seconds per test id, or None if there is no usable cache (missing, unreadable, corrupt or of
    another version). Entries that are not a finite number of seconds are skipped."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != TIMES_VERSION or not isinstance(data.get("times"), dict):
        return None
    return {test_id: float(seconds) for test_id, seconds in data["times"].items()
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and 0 <= seconds < float("inf")}


def write_times(path: Path, measured: dict[str, float], keep: set[str] | None) -> None:
    """Merge this run's times into the cache on disk (atomically: a temp file, then os.replace). keep, for a full
    run, is every test id that exists: entries for tests that are gone are dropped. A cache that cannot be written
    is left as it is: it only speeds up the next run."""
    merged = {**(read_times(path) or {}), **measured}
    if keep is not None:
        merged = {test_id: seconds for test_id, seconds in merged.items() if test_id in keep}
    text = json.dumps({"version": TIMES_VERSION, "times": dict(sorted(merged.items()))}, indent=0)
    try:
        handle, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    except OSError:
        return
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text + "\n")
        os.replace(temp, path)
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass


def median(values) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def balance(ids: list[str], times: dict[str, float] | None, count: int) -> list[list[str]]:
    """Deal ids into at most count shards (never an empty one, unless there are no tests at all). With recorded
    times: longest first (ties by id), each to the least-loaded shard (ties to the lowest index), a test with no
    time counting as the median. Without: round-robin by id. Each shard lists its tests in id order. The same ids
    and times always give the same shards."""
    ids = sorted(ids)
    count = max(1, min(count, len(ids)))
    if not times:
        return [ids[index::count] for index in range(count)]
    default = median(times.values())
    loads = [(0.0, index) for index in range(count)]  # a heap of (load, shard index)
    shards: list[list[str]] = [[] for _ in range(count)]
    for test_id in sorted(ids, key=lambda test_id: (-times.get(test_id, default), test_id)):
        load, index = heapq.heappop(loads)
        shards[index].append(test_id)
        heapq.heappush(loads, (load + times.get(test_id, default), index))
    return [sorted(shard) for shard in shards]


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


def _launch(ids: list[str], timeout: float | None) -> tuple[int, dict | None, str, str | None, float]:
    """Run one shard on its ids; returns (exit code, its summary or None, its stderr, on a timeout why, and the
    seconds it took).

    Output goes to temp files, not pipes: after a timeout on Windows, subprocess.run waits with no limit for the
    pipes to close, which a child the hung test started could hold open forever. On a timeout the shard's whole
    process tree is killed (as core.updater does for git)."""
    # Pin the output encoding so a Windows code page can't break decoding of a shard's output.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # POSIX: a session of its own, so killpg reaches the shard's children (and Ctrl+C does not; main kills the
    # live shards then). Windows: taskkill /T follows the process tree itself.
    group = {} if os.name == "nt" else {"start_new_session": True}
    started = time.monotonic()
    # The id list goes in a closed temp file (Windows cannot open a file another process holds open for writing).
    handle, ids_file = tempfile.mkstemp(prefix="wowtools-shard-", suffix=".txt")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as listing:
            listing.write("".join(test_id + "\n" for test_id in ids))
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(_shard_command(Path(ids_file)), cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
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
    finally:
        try:
            os.unlink(ids_file)
        except OSError:
            pass
    summary = None
    for line in stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            summary = json.loads(line[len(RESULT_PREFIX):])
    return (1 if why else proc.returncode), summary, stderr, why, time.monotonic() - started


def host_kind(os_name: str | None = None, osrelease: str | None = None) -> str:
    """'windows' (native), 'wsl' (Linux under WSL, where cmd.exe reaches the Windows side) or 'linux'."""
    if (os_name or os.name) == "nt":
        return "windows"
    if osrelease is None:
        try:
            osrelease = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8", errors="replace")
        except OSError:
            osrelease = ""
    return "wsl" if "microsoft" in osrelease.lower() else "linux"


class WindowsUnreachable(Exception):
    """WSL cannot start the Windows run: no cmd.exe on PATH (interop off), or wslpath failed."""


def _windows_path(path: Path) -> str:
    try:
        done = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise WindowsUnreachable(f"wslpath could not map {path} to a Windows path ({error})") from error
    return done.stdout.strip()


def _require_cmd_exe() -> None:
    if shutil.which("cmd.exe") is None:
        raise WindowsUnreachable("cmd.exe is not on PATH")


def _cmd_quote(arg: str) -> str:
    """One argument for the Windows command line. Backslashes before the closing quote are doubled: Windows reads
    a lone \\" as an escaped quote, so a -k text ending in a backslash would otherwise swallow it."""
    if '"' in arg:
        raise ValueError(f"cannot pass a double quote (\") to the Windows run: {arg}")
    return '"' + re.sub(r"(\\+)$", r"\1\1", arg) + '"'


def _passthrough(jobs: int | None, pattern: str | None, timeout: float | None, verbose_shards: bool) -> list[str]:
    flags = [] if jobs is None else ["-j", str(jobs)]
    if pattern:
        flags += ["-k", pattern]
    if timeout is not None:
        flags += ["--timeout", f"{timeout:g}"]
    if verbose_shards:
        flags.append("--verbose-shards")
    return flags


def _windows_invocation(flags: list[str]) -> tuple[list[str], Path, dict]:
    """The cmd.exe call that runs this runner under the Windows Python: (argv, cwd, env).

    pushd (not cd /d) also reaches a checkout on a \\wsl.localhost path, by mapping a drive letter. The cwd is a
    Windows drive so cmd.exe does not warn that it cannot start in a UNC directory."""
    _require_cmd_exe()
    python = os.environ.get(WINDOWS_PYTHON_ENV, "").strip() or DEFAULT_WINDOWS_PYTHON
    line = " ".join([f"pushd {_cmd_quote(_windows_path(ROOT))} && {python} scripts\\run_tests.py --announce-pid",
                     *map(_cmd_quote, flags)])
    shared = [part for part in os.environ.get("WSLENV", "").split(":") if part]
    env = {**os.environ, WINDOWS_RUN_VAR: line, "PYTHONIOENCODING": "utf-8",
           "WSLENV": ":".join([*shared, WINDOWS_RUN_VAR, "PYTHONIOENCODING"])}
    return ["cmd.exe", "/d", "/c", f"%{WINDOWS_RUN_VAR}%"], _windows_cwd(ROOT), env


def _windows_cwd(root: Path) -> Path:
    """Where cmd.exe starts: the checkout when it is on a Windows drive (/mnt/d/...), else C:."""
    return root if re.match(r"^/mnt/[a-z](/|$)", root.as_posix()) else Path("/mnt/c")


_RELAYS: dict[subprocess.Popen, dict] = {}  # the --windows / --all runs still going, killed on Ctrl+C


def _relay(command: list[str], cwd: Path, env: dict | None, sink, windows: bool) -> int:
    """Run a whole suite (a child runner) and pass each line of its output to sink; returns its exit code.

    Called on a worker thread, so the main thread stays free for Ctrl+C (_kill_relays) while this one keeps
    reading. A Windows run's pid line is kept, not passed on: Ctrl+C kills that runner's tree with taskkill.exe."""
    group = {} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, **group)
    info = {"windows": windows, "pid": None, "announced": threading.Event()}
    with _LIVE_LOCK:
        _RELAYS[proc] = info
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
            if line.startswith(PID_PREFIX):
                info["pid"] = line[len(PID_PREFIX):].strip()
                info["announced"].set()
            else:
                sink(line)
        return proc.wait()
    finally:
        info["announced"].set()  # no pid will come: do not keep a Ctrl+C waiting for one
        proc.stdout.close()
        with _LIVE_LOCK:
            _RELAYS.pop(proc, None)


def _await_pid(proc: subprocess.Popen, info: dict) -> str | None:
    """A Windows runner's pid, waiting up to PID_WAIT s for it (while its relay thread reads) if Ctrl+C came
    before it was announced: killing only the WSL-side cmd.exe would leave the Windows Python running."""
    deadline = time.monotonic() + PID_WAIT
    while not info["announced"].wait(0.05):
        if proc.poll() is not None or time.monotonic() >= deadline:
            break
    return info["pid"]


def _kill_relays() -> None:
    """Ctrl+C: stop every suite still running. A Windows runner's tree goes with taskkill.exe; a WSL runner gets
    SIGINT, so it kills its own shards (each in a session of its own) as a plain run does on Ctrl+C."""
    with _LIVE_LOCK:
        relays = list(_RELAYS.items())
    for proc, info in relays:
        try:
            if info["windows"]:
                if _await_pid(proc, info):
                    subprocess.run(["taskkill.exe", "/T", "/F", "/PID", info["pid"]], cwd="/mnt/c",
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=30, check=False)
            else:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
        _kill_tree(proc)


def _windows_hint(code: int, output: str) -> None:
    """A Windows run that failed without a summary most likely never started: say how to point it at a Python."""
    if code != 0 and not SUMMARY_RE.search(output):
        python = os.environ.get(WINDOWS_PYTHON_ENV, "").strip() or DEFAULT_WINDOWS_PYTHON
        print(f"The Windows run did not finish. Is Python for Windows installed ({python})? Set "
              f"{WINDOWS_PYTHON_ENV} to the command that starts it, or use the plain run where there is none.",
              file=sys.stderr)


def _run_windows(flags: list[str]) -> int:
    command, cwd, env = _windows_invocation(flags)
    output: list[str] = []

    def stream(line: str) -> None:
        output.append(line)
        print(line, end="", flush=True)

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            code = pool.submit(_relay, command, cwd, env, stream, True).result()
        except KeyboardInterrupt:
            _kill_relays()
            raise
    _windows_hint(code, "".join(output))
    return code


def _run_all(jobs: int, pattern: str | None, timeout: float | None, verbose_shards: bool) -> int:
    flags = _passthrough(jobs, pattern, timeout, verbose_shards)
    command, cwd, env = _windows_invocation(flags)
    sides = {"WSL": ([sys.executable, str(Path(__file__).resolve()), *flags], ROOT,
                     {**os.environ, "PYTHONIOENCODING": "utf-8"}, False),
             "Windows": (command, cwd, env, True)}
    output: dict[str, list[str]] = {label: [] for label in sides}
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(sides)) as pool:
        try:
            futures = {label: pool.submit(_relay, *side[:3], output[label].append, side[3])
                       for label, side in sides.items()}
            # One side failing to start (say, cmd.exe gone) stops the other at once, not after its whole run.
            done, _ = wait(futures.values(), return_when=FIRST_EXCEPTION)
            raised = [future.exception() for future in done if future.exception() is not None]
            if raised:
                _kill_relays()
                raise raised[0]
            codes = {label: future.result() for label, future in futures.items()}
        except KeyboardInterrupt:
            _kill_relays()
            raise
    elapsed = time.monotonic() - started
    for label in sides:
        print(f"===== {label} (-j {jobs}) =====")
        print("".join(output[label]), end="", flush=True)
    _windows_hint(codes["Windows"], "".join(output["Windows"]))
    print(", ".join(f"{label}: {'OK' if code == 0 else f'FAILED (exit {code})'}" for label, code in codes.items())
          + f", in {elapsed:.1f}s")
    ok = all(code == 0 for code in codes.values())
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


def _print_shard_times(shards: list[list[str]], outcomes: list, recorded: dict[str, float] | None,
                       verbose: bool) -> None:
    """One line with the fastest and the slowest shard (their spread is what balancing shrinks); with
    --verbose-shards, a line per shard too, with the time the cache planned for it."""
    seconds = [outcome[4] for outcome in outcomes]
    if verbose:
        default = median(recorded.values()) if recorded else 0.0
        for index, (shard, took) in enumerate(zip(shards, seconds)):
            planned = (f", planned {sum(recorded.get(test_id, default) for test_id in shard):.1f} s"
                       if recorded else "")
            print(f"shard {index + 1}/{len(shards)}: {took:.1f} s, {len(shard)} tests{planned}")
    how = "balanced by recorded test times" if recorded else "round-robin: no recorded test times yet"
    print(f"Shard times: fastest {min(seconds):.1f} s, slowest {max(seconds):.1f} s ({how})")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the wow-tools tests in parallel.")
    parser.add_argument("-j", "--jobs", type=int,
                        help=f"number of shards (default 1.5 per CPU, at most {MAX_DEFAULT_JOBS})")
    parser.add_argument("-k", dest="pattern", help="only run tests whose id contains this text")
    parser.add_argument("--timeout", type=float,
                        help=f"seconds each shard may run before it is killed and failed (default {DEFAULT_TIMEOUT}, "
                             "more below -j 4; 0 for no limit)")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--windows", action="store_true",
                       help=f"from WSL: run the suite under the native Windows Python ({DEFAULT_WINDOWS_PYTHON}, or "
                            f"${WINDOWS_PYTHON_ENV}) through cmd.exe")
    where.add_argument("--all", action="store_true",
                       help="from WSL: run the WSL and the Windows suites at the same time, half the default shards "
                            "each unless -j is given; passes only if both pass")
    parser.add_argument("--verbose-shards", action="store_true",
                        help="also print each shard's time, test count and planned time")
    parser.add_argument("--shard-file", help=argparse.SUPPRESS)
    parser.add_argument("--announce-pid", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.shard_file:
        return _run_shard(args.shard_file)
    if args.announce_pid:
        print(PID_PREFIX + str(os.getpid()), flush=True)

    if args.windows or args.all:
        host = host_kind()
        if host == "linux":
            print("--windows and --all need WSL: they run the suite under the Windows Python through cmd.exe. "
                  "Here, run python3 scripts/run_tests.py.", file=sys.stderr)
            return 2
        if host == "wsl":
            jobs = None if args.jobs is None else max(1, args.jobs)
            try:
                if args.windows:
                    return _run_windows(_passthrough(jobs, args.pattern, args.timeout, args.verbose_shards))
                return _run_all(jobs or max(1, default_jobs() // 2), args.pattern, args.timeout,
                                args.verbose_shards)
            except ValueError as error:
                print(error, file=sys.stderr)
                return 2
            except (OSError, WindowsUnreachable) as error:
                print(f"Could not start the Windows run: {error}. --windows and --all need WSL interop (cmd.exe and "
                      "wslpath on PATH; see [interop] in /etc/wsl.conf). Use the plain run where there is none.",
                      file=sys.stderr)
                return 2
        # Native Windows: --windows (and --all) is the normal run.

    jobs = max(1, args.jobs) if args.jobs is not None else default_jobs()
    timeout = default_timeout(jobs) if args.timeout is None else (args.timeout if args.timeout > 0 else None)
    started = time.monotonic()
    ids = _discover_ids(args.pattern)
    cache = times_path()
    recorded = read_times(cache)
    shards = balance(ids, recorded, jobs)
    jobs = len(shards)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        try:
            outcomes = list(pool.map(lambda shard: _launch(shard, timeout), shards))
        except KeyboardInterrupt:
            with _LIVE_LOCK:
                live = list(_LIVE)
            for proc in live:
                _kill_tree(proc)
            raise
    totals = {"run": 0, "failures": 0, "errors": 0, "skipped": 0}
    measured: dict[str, float] = {}
    ok = True
    for index, (code, summary, stderr, timed_out_why, _seconds) in enumerate(outcomes):
        if summary is not None:
            for key in totals:
                totals[key] += summary[key]
            measured.update(summary.get("times") or {})
        gap = None if summary is None else _list_gap(shards[index], summary)
        if code != 0 or summary is None or gap:
            ok = False
            why = timed_out_why or (f"did not run its whole list: {gap}" if gap else "failed")
            print(f"===== shard {index + 1}/{jobs} {why} =====", file=sys.stderr)
            print(stderr, file=sys.stderr)
    if measured:
        write_times(cache, measured, keep=None if args.pattern else set(ids))
    elapsed = time.monotonic() - started
    _print_shard_times(shards, outcomes, recorded, args.verbose_shards)
    print(f"Ran {totals['run']} tests in {elapsed:.1f}s across {jobs} processes "
          f"({totals['failures']} failures, {totals['errors']} errors, {totals['skipped']} skipped)")
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
