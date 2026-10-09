# Faster tests: local Windows runs, balanced shards, a smaller CI matrix: design

Date: 2026-10-09. Branch: `build/faster-tests`. Plan: `../plans/2026-10-09-faster-tests.md`, ledger
`../plans/2026-10-09-faster-tests.status.md`.

User feedback 2026-10-08/09: waiting on GitHub CI at every review step adds a lot of time. Agreed: (1) run the
Windows tests locally, (2) stop waiting on GitHub CI during a build, (3) trim the CI matrix, and look for more
parallelism in the test runs.

Measured 2026-10-09 on the user's machine (16 CPUs, WSL2, repo on `/mnt/d`): WSL `run_tests.py` about 100-120 s;
native Windows Python 3.14 (`py -3.14`, launched from WSL through `cmd.exe`) ran the same 1925 tests in 149 s, 0
failures, 79 skipped (POSIX/WSL-only tests). GitHub CI took 8-13 minutes per run.

## Decisions

| # | Topic | Decision |
|---|---|---|
| F1 | Local Windows run | `scripts/run_tests.py --windows`: from WSL it runs the suite under the native Windows Python (`py -3`, the newest installed; `WOWTOOLS_WINDOWS_PYTHON` overrides the command) in the same checkout through `cmd.exe`, passing `-k`, `-j` and `--timeout` through and returning its exit code; on native Windows it is the normal run; on Linux that is not WSL it fails with a clear message. `--all` runs the WSL and the Windows suites at the same time (CPUs split between them) and fails if either fails, each with its own summary. The green gate becomes `python3 scripts/run_tests.py --all` (WSL + Windows), `ruff check --no-cache .`, `gen_event_docs.py --check`; where no Windows Python is available, the plain run plus CI before the merge. |
| F2 | Balanced shards | Shards are balanced by recorded test time instead of round-robin by id: each run writes per-test durations to a cache file next to the runner's other state (gitignored, never committed, e.g. `.test-times.json` at the repo root or under the OS temp dir per checkout), and the next run assigns tests to shards greedily (longest first, to the least-loaded shard). Unknown tests get the median time; no cache means today's round-robin. Shard order stays deterministic for a given cache. |
| F3 | Shard count | The default shard count is chosen by measurement on this machine: compare the default against more shards than CPUs (for example 1.5x and 2x) for the WSL run, the Windows run and `--all`; change the default only if a run is clearly faster (median of 3 runs each), and record the numbers in the ledger and `docs/testing.md`. |
| F4 | CI matrix | `.github/workflows/tests.yml` runs two jobs: `windows-latest` / Python 3.13 and `ubuntu-latest` / Python 3.10 (the floor). |
| F5 | When CI is checked | During a build, CI runs on each push but nobody waits for it; it is checked once before asking the user to merge into master, and before a release. STD-10.1 and STD-10.2, `CLAUDE.md` (the green gate), `docs/testing.md`, `docs/common-tasks.md` and `docs/releasing.md` say so. |
