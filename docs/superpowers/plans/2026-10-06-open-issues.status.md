# Open GitHub issues: status ledger

Plan: `2026-10-06-open-issues.md`. Branch: `fix/open-issues`. Resume at the first task not marked `done`.

| Task | Issue | Title | Status | Commit | Notes |
|---|---|---|---|---|---|
| I1 | #1 | macOS running-WoW detection | done | ac04a74 | `ps -axo comm=` branch, shared `wow_name()` rule; 4 new tests (test_process 17), suite 1308 OK, 2 skipped |
| I2 | #4 | keep_cleaned for cleaned zips | todo | | |
| I3 | #5 | per-account enabled addons | todo | | |
| I4 | #7 | keep user files when pruning update backups | todo | | |
| I5 | #8 | native Windows checkpoint run | todo | | |
| I6 | #9 #10 | review bundle sign-off, merged ledgers | todo | | |
| I7 | all | review, push, merge, close issues | todo | | |

## Decisions taken during the build

- I1: on macOS the `WowProcess.path` is the `.app` bundle path (not the inner `Contents/MacOS/...` executable), so
  `processes_for_flavor()` keeps matching the parent folder to the flavor folder unchanged. A bare name from `ps`
  (no path) counts as "flavor unknown". The macOS name rule (first version) was `World of Warcraft[ Classic][ Beta|Test|PTR|Public
  Test]`, which leaves out the Launcher and helper processes; `wow_name()` is now the one rule for PowerShell, /proc
  and ps. `running_wtf_lockers` (Windows-only lockers) is unchanged.
- I1 review: 3 findings, 3 fixed, 0 rejected: the macOS name rule now accepts any `World of Warcraft[ <variant>]`
  except Launcher/helper/crash/error/reporter/updater/agent (fail toward warning on an unknown variant); the path is
  cut back to the `.app` only for a bundle's own `<X>.app/Contents/MacOS/<name>` executable, so a Wine `Wow.exe`
  inside a wrapper `.app` keeps its flavor folder; architecture.md describes the new rule. Suite 1309 OK, 2 skipped.
