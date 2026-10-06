# Open GitHub issues: status ledger

Plan: `2026-10-06-open-issues.md`. Branch: `fix/open-issues`. Resume at the first task not marked `done`.

| Task | Issue | Title | Status | Commit | Notes |
|---|---|---|---|---|---|
| I1 | #1 | macOS running-WoW detection | done | ac04a74 | `ps -axo comm=` branch, shared `wow_name()` rule; 4 new tests (test_process 17), suite 1308 OK, 2 skipped |
| I2 | #4 | keep_cleaned for cleaned zips | done | 685d44f | `[wtf_cleaner] keep_cleaned` (0 = all), `prune_cleaned_zips`, event `backup.cleaned_pruned`; 8 new tests, suite 1317 OK, 2 skipped |
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
- I2: `keep_cleaned` counts the zip the clean just wrote as one of the kept and never deletes it, even when an older
  zip carries a later stamp (a wrong clock). Pruning runs only after a real clean that deleted something and wrote a
  zip (mirrors the WTF backup pruning); per flavor, any account, like the dry-run zips. `prune_dry_run_zips` and
  `prune_cleaned_zips` share `_prune_run_zips`, now matching the flavor literally in the name and using one
  `os.scandir` without following links (was `iterdir` + `is_file()` per file). Settings form fit at 120x30: the new
  field uses a compact Input and both the new label and the backup-folder label are one line (the default folder is
  already the placeholder). Bad or negative values in the file read as 0 (keep all, the safe side).
- I2 review: 4 findings, 4 fixed, 0 rejected: wtf-cleaner.md's legacy `cleaned-…` dry-run sentence now says
  keep_cleaned counts and removes them; wtf-cleaner.md and architecture.md no longer claim Undo can lose its zip
  (the last clean's zip is always kept; a pruned older clean is restored by hand from its WTF backup); keep_cleaned
  is a full-height Input like max_age, the form still fitting at 120x30 because "Propose SavedVariables when:" is a
  plain Label instead of a margined .title; the stale dry-run test renamed and its comment corrected. Suite 1317 OK,
  2 skipped.
