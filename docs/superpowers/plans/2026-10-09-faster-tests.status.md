# Faster tests: status ledger

Plan: `2026-10-09-faster-tests.md`. Spec: `../specs/2026-10-09-faster-tests-design.md`.
Branch: `build/faster-tests`. Resume at the first task not marked `done`. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| F0 | spec, plan, ledger | done | (this commit) | baseline: WSL ~100-120 s, native Windows 3.14 149 s (1925 tests, 79 skipped) |
| F1 | `--windows` and `--all` | done | (this commit) | 20 new tests in `test_release_scripts.py` (`RunTestsWindowsTest`, cmd.exe faked). After the review fixes (F1g) `--all` ran 1945 tests: WSL 0 failures, 2 skipped; Windows 0 failures, 79 skipped; 283 s. Before them: full suite 1940 tests: WSL 0 failures, 2 skipped; Windows 3.14 0 failures, 79 skipped. Wall times: plain WSL 148 s; `--windows` 141 s (and 147 s); `--all` (-j 8 each) 269 s, 279 s; `--all -j 16` 264 s. Back to back the two runs take about 289 s, so `--all` saves only about 10-25 s: the machine is CPU-bound, and halving the shards makes the round-robin's slowest shard the limit (F2/F3 to tune). Ctrl+C checked by hand on `--windows` and `--all`: no python.exe/py.exe or WSL runner left |
| F2 | balanced shards | done | (this commit) | 14 new tests in `test_release_scripts.py` (`RunTestsBalanceTest`; the cache in a temp folder, discovery and shards faked) plus the shard child's id-list test. Full suite 1959 tests: WSL 0 failures, 2 skipped; Windows 3.14 0 failures, 79 skipped; `--all` both OK. 16 shards, median of 3, round-robin before / balanced after: WSL 143.5 s (142.7, 143.5, 147.9; shards 62-144 s) / 99.8 s (99.7, 99.8, 102.1; shards 87-97 s, about 10 s apart); `--windows` 138.6 s (138.0, 138.6, 138.9; shards 58-139 s) / 97.3 s (96.6, 97.3, 104.7; shards 91-97 s in the median run, as everywhere here; the 104 s shard was the 104.7 s run's). Re-measured with the F2f fixes: `--windows` 99.7 s (99.4, 99.7, 99.8; median run's shards 91-99 s), 1962 tests, 0 failures, 79 skipped. `--all` (-j 8 each): 269-283 s (F1) / 201.6 s (one run; shards 181-198 s). The parent's discovery adds about 3 s; the cache files are about 185 KB each |
| F3 | shard count by measurement | todo | | |
| F4/F5 | two-job CI; when CI is checked | todo | | |
| FR | review, gate, push, CI once | todo | | |

## Decisions taken during the build

- F1a: the cmd.exe line travels in `WOWTOOLS_WINDOWS_RUN` (shared through `WSLENV`) and cmd.exe runs
  `%WOWTOOLS_WINDOWS_RUN%`: WSL escapes double quotes inside an argument as `\"`, which cmd.exe keeps literally, so
  a quoted path or `-k` text could not be passed as an argument. A `-k` text with a double quote is refused (exit 2).
- F1b: `pushd` (not `cd /d`) so a checkout on `\\wsl.localhost` also works; cmd.exe starts in the checkout when it
  is on a Windows drive (`/mnt/<x>/`), else `/mnt/c`, so it never prints the UNC-cwd warning.
- F1c: Ctrl+C: the Windows runner prints its pid (hidden `--announce-pid`) and is killed with `taskkill.exe /T /F`;
  the WSL runner of `--all` gets SIGINT so it kills its own shards. Both runs are in sessions of their own.
- F1d: cmd.exe returns 1 (not 9009) when `py` is missing, so a Windows run that fails without a `Ran N tests`
  summary prints a hint naming `WOWTOOLS_WINDOWS_PYTHON` instead of keying on an exit code.
- F1e: `--all -j N` gives each suite N shards (not N split in two); without -j each gets half the CPUs.
  `--all` on native Windows is the plain run, like `--windows`. `--windows` streams its output; `--all` buffers each
  side and prints it under `===== WSL (-j N) =====` / `===== Windows (-j N) =====`, then one combined line.
- F1f: no CHANGELOG line: the runner is developer tooling, not a user-noticeable change (STD-11.1).
- F1g: review fixes, all seven taken. Windows unreachable (no `cmd.exe` on `PATH`, `wslpath` failing, `cmd.exe`
  failing to start) is `WindowsUnreachable`/`OSError`, caught in `main`: a message naming WSL interop and exit 2,
  checked before anything starts; under `--all` the side that raises stops the other at once (`wait` with
  `FIRST_EXCEPTION`, then `_kill_relays`). `_cmd_quote` doubles trailing backslashes (Windows argv rules), so a
  `-k` text ending in `\` reaches Windows unchanged. `--windows` now reads its run on a worker thread like `--all`,
  so a Ctrl+C that comes before the `@@runner-pid` line waits for it (up to `PID_WAIT`, 10 s, or until the run
  ends) and still kills the Windows tree with `taskkill.exe`; the relay's own KeyboardInterrupt handler (and its
  test with the unreaped child) went. A `WOWTOOLS_WINDOWS_PYTHON` path with spaces is documented to need double
  quotes inside the value rather than quoted by guesswork (a value can be a command with arguments). Ctrl+C at
  0.3 s and 1.5 s into `--windows` checked by hand: nothing left running on Windows.
- F2a: one cache file per platform, `.test-times-<host_kind>.json` at the repo root (`wsl`, `linux`, `windows`),
  gitignored as `.test-times-*.json`: the two sides of `--all` write different files, so they never clobber each
  other, and a merge re-reads the file just before an atomic `os.replace`. Untracked, the files are neither committed
  nor archived, so the release manifest test (`git ls-files` / `git archive`) never sees them. Format
  `{"version": 1, "times": {id: seconds}}`; unusable entries are skipped, an unusable file reads as no cache.
- F2b: the parent discovers the tests (about 3 s on WSL) and writes each shard's ids to a closed temp file
  (`--shard-file`, replacing `--shard i/N`; closed so Windows can open it); the child discovers as before and runs the
  listed ids in id order, so a class's tests stay together. Shards are capped at the number of tests (none empty).
- F2c: a test's time runs from the end of the one before (the start of the run for the first), so `setUpClass` counts
  towards a class's first test and a shard's times add up to its run. Times from a timed-out shard are lost (it
  prints no summary); failing tests' times are kept. A `-k` run updates only its tests; a full run drops the gone.
- F2d: ties: longest first, then by id; least-loaded shard, then the lowest index (a heap of (load, index)); all-equal
  times give the round-robin deal. The median is over every recorded time, not just this run's tests.
- F2e: the summary always has `Shard times: fastest A s, slowest B s (balanced by recorded test times | round-robin:
  no recorded test times yet)` before `Ran N tests`; `--verbose-shards` adds a line per shard with its planned time.
  No CHANGELOG line (developer tooling, as F1f).
- F2f: review fixes, all six taken (two pairs were the same finding). `--verbose-shards` is passed on to `--windows`
  and to both sides of `--all` (`_passthrough`). The shard child reports `listed` (ids it read) and `missing`
  (listed ids it did not discover; named on stderr, and they fail it); the parent fails a shard whose `listed` is not
  the number of ids it dealt or whose `missing` is not empty (`_list_gap`). The check is on the list, not on
  `run` == the ids: a class whose `setUpClass` skips or fails rightly runs fewer tests. The `--windows` shard spread
  now reads the median run's in both documents (91-97 s; the ledger had mixed runs). CLAUDE.md's gate timings follow
  testing.md (`--all` about 3.5 min, the plain run about 100 s).
