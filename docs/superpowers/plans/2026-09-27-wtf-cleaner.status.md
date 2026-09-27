# Build status: framework + WTF Cleaner

Checkpoint ledger for `2026-09-27-wtf-cleaner.md`. Work happens on branch `feat/wtf-cleaner`.
Each task commits its code **and** its row update here in the same commit, so the ledger always
matches git history.

**To resume:**
1. `git checkout feat/wtf-cleaner`
2. Find the first row that isn't `done`.
3. Run `python3 -m unittest discover -s tests -t .`. It must be green before you continue.
4. Carry on from that task in the plan.

Status values: `pending` · `in-progress` · `done` · `blocked (reason)`

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| 1 | Scaffold, vendored libraries, bootstrap | done | 4faabcf | No deviations (pip deps complete; tests pass from repo root and another cwd) |
| 2 | Windows ⇄ WSL paths | done | 07ac44a | No deviations |
| 3 | Suite event log | done | 4a2cebf | No code deviations (plan says 12 tests; its test file has 13, all pass) |
| 4 | Config | done | 1a4e4a0 | No deviations |
| 5 | WoW install model + test fixture tree | done |  | No deviations |
| 6 | Verified zip backups | done | 5461825 | No deviations |
| 7 | "Is WoW running?" check | done | 9751713 | No deviations |
| 8 | WTF Cleaner scanner + event registry | done | b983c70 | No deviations |
| 9 | Rules, settings, report | done | 4294b06 | No code deviations (plan says 16 tests; its test file has 15, all pass) |
| 10 | Clean pipeline | done | 5897e4a | No deviations |
| 11 | Updater part 1: release check | done | | No deviations |
| 12 | Updater part 2: apply + update command | done | | No deviations |
| 13 | Dispatcher, registry, CLI, wrappers | pending | | |
| 14 | Shared UI | pending | | |
| 15 | WTF Cleaner TUI | pending | | |
| 16 | Documentation | pending | | |
| 17 | Verify end to end + publish v0.1.0 | pending | | Needs the user's approval for the release |

## Milestones (the branch is pushed to origin after each; merging into master waits for the user's go-ahead)

| Milestone | Tasks | Pushed |
|---|---|---|
| M1 Core foundation | 1–4 | yes |
| M2 Core services | 5–7 | yes |
| M3 Cleaner logic | 8–10 | yes |
| M4 Updater + CLI | 11–13 | |
| M5 TUI | 14–15 | |
| M6 Docs + verification | 16–17 | |
