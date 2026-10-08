# Faster tests: status ledger

Plan: `2026-10-09-faster-tests.md`. Spec: `../specs/2026-10-09-faster-tests-design.md`.
Branch: `build/faster-tests`. Resume at the first task not marked `done`. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| F0 | spec, plan, ledger | done | (this commit) | baseline: WSL ~100-120 s, native Windows 3.14 149 s (1925 tests, 79 skipped) |
| F1 | `--windows` and `--all` | done | (this commit) | 20 new tests in `test_release_scripts.py` (`RunTestsWindowsTest`, cmd.exe faked). After the review fixes (F1g) `--all` ran 1945 tests: WSL 0 failures, 2 skipped; Windows 0 failures, 79 skipped; 283 s. Before them: full suite 1940 tests: WSL 0 failures, 2 skipped; Windows 3.14 0 failures, 79 skipped. Wall times: plain WSL 148 s; `--windows` 141 s (and 147 s); `--all` (-j 8 each) 269 s, 279 s; `--all -j 16` 264 s. Back to back the two runs take about 289 s, so `--all` saves only about 10-25 s: the machine is CPU-bound, and halving the shards makes the round-robin's slowest shard the limit (F2/F3 to tune). Ctrl+C checked by hand on `--windows` and `--all`: no python.exe/py.exe or WSL runner left |
| F2 | balanced shards | done | (this commit) | 14 new tests in `test_release_scripts.py` (`RunTestsBalanceTest`; the cache in a temp folder, discovery and shards faked) plus the shard child's id-list test. Full suite 1959 tests: WSL 0 failures, 2 skipped; Windows 3.14 0 failures, 79 skipped; `--all` both OK. 16 shards, median of 3, round-robin before / balanced after: WSL 143.5 s (142.7, 143.5, 147.9; shards 62-144 s) / 99.8 s (99.7, 99.8, 102.1; shards 87-97 s, about 10 s apart); `--windows` 138.6 s (138.0, 138.6, 138.9; shards 58-139 s) / 97.3 s (96.6, 97.3, 104.7; shards 91-97 s in the median run, as everywhere here; the 104 s shard was the 104.7 s run's). Re-measured with the F2f fixes: `--windows` 99.7 s (99.4, 99.7, 99.8; median run's shards 91-99 s), 1962 tests, 0 failures, 79 skipped. `--all` (-j 8 each): 269-283 s (F1) / 201.6 s (one run; shards 181-198 s). The parent's discovery adds about 3 s; the cache files are about 185 KB each |
| F3 | shard count by measurement | done | (this commit) | Default now 1.5 shards per CPU, at most 24 (`default_jobs`, `MAX_DEFAULT_JOBS`); `--all` gives each side half (12 on 16 CPUs). 3 new tests (`RunTestsShardCountTest`) and the `--all` default test updated. Median of 3 runs (runner's `Ran N tests in T s`), balanced shards, 16 CPUs, 1x / 1.5x / 2x CPUs: WSL -j 16/24/32 100.9 s (100.6, 100.9, 102.7) / 87.5 s (86.7, 87.5, 89.2; 13 % faster) / 87.3 s (86.4, 87.3, 88.6); `--windows` -j 16/24/32 99.6 s (98.4, 99.6, 100.2) / 78.0 s (77.1, 78.0, 89.0; 22 % faster) / 78.1 s (76.8, 78.1, 78.2); `--all` -j 8/12/16 each 197.9 s (196.0, 197.9, 199.7) / 176.5 s (176.0, 176.5, 178.1; 11 % faster) / 177.9 s (175.6, 177.9, 179.1). Gate with the new defaults: `--all` (12 each) 1965 tests: WSL 0 failures, 2 skipped; Windows 3.14 0 failures, 79 skipped; 175.1 s. Plain WSL run 1965 tests, 24 shards, 90.3 s, 0 failures, 2 skipped |
| F4/F5 | two-job CI; when CI is checked | done | (this commit) | `tests.yml` matrix is now `include`: `windows-latest` / 3.13 and `ubuntu-latest` / 3.10; fail-fast off, the 20-minute timeout, the steps and `--timeout 900` kept. 3 new tests (`CiWorkflowTest` in `test_release_scripts.py`: the two jobs, no doc says "four jobs", STD-10.2 names both). STD-1.1, STD-10.2, `CLAUDE.md`, `testing.md` (CI table and when CI is checked), `common-tasks.md` (gate and release recipe) and `releasing.md` step 1 updated. Gate: plain WSL run 1969 tests, 24 shards, 87.2 s, 0 failures, 2 skipped; `--all` (12 each) 172.7 s: WSL 1969 tests, 0 failures, 2 skipped (shards 161-169 s); Windows 3.14 1969 tests, 0 failures, 79 skipped (shards 146-153 s). CI not run or measured here (F5: checked once at FR) |
| FR | review, gate, push, CI once | todo | | at the CI check: the Windows job's slowest round-robin shard (6 shards) against `--timeout 900`, and the job against its 20 minutes (F4/F5d) |

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
- F3a: the default is 1.5 shards per CPU (`cpus * 3 // 2`, two CPUs if `os.cpu_count()` is unknown), at least 1,
  capped at 24 (`MAX_DEFAULT_JOBS`): 1.5x was 13 % (WSL), 22 % (Windows) and 11 % (`--all`) faster than one shard
  per CPU, and 2x was no faster than 1.5x anywhere, so the cap sits at 1.5x this 16-CPU machine rather than letting
  a bigger one start dozens of Textual processes. `--all` without -j gives each side `default_jobs() // 2` (12 here),
  not half the CPUs; the per-shard timeout rule (600 s at -j 4 or more) is unchanged. No CHANGELOG line (developer
  tooling, as F1f). Measured with `-j` given explicitly, so every run used the same code; the three new tests landed
  mid-way through the `--all -j 12` runs (1962 then 1965 tests).
- F3b: review fixes. CI passes no -j, so a 4-vCPU GitHub runner now runs 6 shards (`default_jobs(4)`), not 4:
  testing.md's CI step and the `tests.yml` comment no longer say "four shards" and name the new count, and a test
  (`RunTestsShardCountTest`) pins testing.md's number to `default_jobs(4)`. 1.5 per CPU is unmeasured on a 4-vCPU
  runner (the one that needed settle timeouts above 10 s); its timings are checked at F4/FR, and the 900 s timeout
  only gains headroom from smaller shards. Not changed: the measurement caveat (three tests landing mid-way through
  the `--all -j 12` runs, and `Ran N tests in T s` including the parent's ~3 s discovery) is already in F3a and
  F2b; both affect every column alike and the 11-22 % gains are far past the 10 % bar.
- F4/F5a: the two jobs are listed with `include` (flow-style `- {os: ..., python: "..."}` entries, which
  `CiWorkflowTest` reads with a regex: the suite stays stdlib-only, no YAML parser) rather than a cross-product with
  `exclude`, so the file says exactly which jobs run. Windows gets 3.13 (the newest the users are likely to have;
  3.14 runs locally through `--windows`) and Linux the 3.10 floor, so the floor is still checked on every push.
- F4/F5b: the `tests.yml` shard comment keeps the 900 s timeout and now says the 594 s shard was "one shard of 4"
  (before F3's 6 shards on a 4-vCPU runner); testing.md's "checked again at F4" became "when CI is next checked,
  before the merge", since F5 forbids waiting on CI during the build. The 4-vCPU timings are read at FR.
- F4/F5c: STD-10.2 carries the F5 rule (CI runs on every push, nobody waits for it during a build; checked once
  before asking to merge into master and before a release); STD-10.1 already had the `--all` gate from F1.
  STD-1.1's enforcer reads "CI (Linux / Python 3.10, Windows / Python 3.13)". No CHANGELOG line: CI is developer
  tooling, not a user-noticeable change (STD-11.1, as F1f).
- F4/F5d: review fixes, all five taken (two were the same STD-10.1 finding). CI deals its shards round-robin (a fresh
  checkout has no gitignored `.test-times-*.json` and the workflow has no cache step): the `tests.yml` comment and
  testing.md's CI step 3 now say so, and that the 594 s shard was round-robin; the Windows job's slowest shard at
  6 round-robin shards is checked against 900 s and the job against 20 minutes at FR, when CI is checked (no CI run
  here, F5). No cache step added: balancing CI is out of the spec's scope. STD-10.1 now points to STD-10.2 for when
  CI is checked, as F5 lists both. `test_no_doc_still_claims_four_ci_jobs` matches only "four/4 (CI) jobs" and
  "all four/4 (CI) jobs", with self-checks that "all four flavors" and similar pass. testing.md's
  `test_release_scripts.py` row names `CiWorkflowTest` and gets its missing comma. Gate: `--all` (12 each) 171.5 s, 1971 tests: WSL 0 failures, 2 skipped; Windows 3.14 0 failures, 79 skipped. 2 new tests in `CiWorkflowTest`
  (CI's round-robin named in the workflow and the CI section, no `actions/cache`; STD-10.1 names STD-10.2).
