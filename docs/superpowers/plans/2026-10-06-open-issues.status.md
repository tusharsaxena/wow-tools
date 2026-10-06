# Open GitHub issues: status ledger

Plan: `2026-10-06-open-issues.md`. Branch: `fix/open-issues`. Resume at the first task not marked `done`.

| Task | Issue | Title | Status | Commit | Notes |
|---|---|---|---|---|---|
| I1 | #1 | macOS running-WoW detection | done | ac04a74 | `ps -axo comm=` branch, shared `wow_name()` rule; 4 new tests (test_process 17), suite 1308 OK, 2 skipped |
| I2 | #4 | keep_cleaned for cleaned zips | done | 685d44f | `[wtf_cleaner] keep_cleaned` (0 = all), `prune_cleaned_zips`, event `backup.cleaned_pruned`; 8 new tests, suite 1317 OK, 2 skipped |
| I3 | #5 | per-account enabled addons | done | ff55b8d | `ScanResult.enabled_by_account` + `enabled_for()`, rules judge each group by its account; `build_multi_account_tree` fixture, 5 new tests (PerAccountEnabledTest); suite 1322 OK, 2 skipped |
| I4 | #7 | keep user files when pruning update backups | done | db8c687 | `_carry_user_files` before each prune moves user files to `<root>/update-leftovers/<version>/`; failed move keeps the folder; events `update.leftovers_kept`, `update.backup_kept`; 5 new tests (test_updater_apply 37), suite 1327 OK, 2 skipped |
| I5 | #8 | native Windows checkpoint run | done | 037ef36 | Windows 11 / Python 3.14.3 on NTFS: suite 1330 OK, 64 skipped (6 parallel runs + 1 serial green after 4 test-only fixes); scripted WTF Cleaner happy path on NTFS all passed; WSL suite 1330 OK, 2 skipped |
| I6 | #9 #10 | review bundle sign-off, merged ledgers | done | (this commit) | reviews/2026-10-04 sign-off table (25 rows) and evidence filled from the review-fixes ledger, "Closed 2026-10-06" lines; 7 ledgers' final rows marked merged (96c3527, 51a3155, 397e0d8, dd8d635 x3, 4c3676e), each hash checked with git log; docs only; suite 1333 OK, 2 skipped; ruff clean |
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
- I3: character-level files are judged by their *account's* set too (any character of the account enabling the
  addon keeps every file of that account), not by the character's own AddOns.txt: that keeps a single-account
  install's verdict identical (the brief's hard requirement) and never suggests an alt's file because the alt alone
  switched the addon off. An account with no characters, in an install where other accounts have some, now counts
  every installed addon as enabled (with its own "no character folders" warning) instead of borrowing the other
  accounts' union: the safe side. A flavor with no characters at all keeps its one flavor-wide warning.
  `ScanResult.enabled` stays the union over accounts with characters (logs, `scan.completed`); `scan.addons` also
  logs `enabled_by_account`. The shared `build_wow_tree` fixture's Chârb now enables Details, so ACCT2 keeps its
  Details files under per-account judging and every existing count stays the same; the new behaviour is tested on
  the separate `build_multi_account_tree`. No extra file I/O: each AddOns.txt is still read once.
  I3 review: 3 findings, 2 fixed, 1 kept as a decision: CHANGELOG/docs no longer describe the per-account rule as a
  change from an unreleased behaviour; the design spec's "Enabled scope: Global" row is marked superseded (#5). Kept:
  a characterless account in an All-accounts scan counts every addon as enabled (with its own warning) rather than
  borrowing the union of the other accounts. This is deliberate, and the user should confirm it at the merge ask.
- I4: a "user file" in an old `.update-backup/<version>` is a file under its managed folders (wowtools, vendor,
  scripts, docs; `__pycache__` and `*.pyc` left out) with no file at the same relative path in the live install.
  A release has no manifest of what it shipped, so the live install is the only reference: a program file that
  old version had and a later release dropped is carried too (documented in the README; one file too many beats a
  lost one). A file the user edited, or one whose path the live install also has, is not carried. Files go to
  `<root>/update-leftovers/<version>/<same path>`, never back into the managed folders (the next update replaces
  them, and a stray module could be imported); a taken name gets ` (2)`, ` (3)`. Any failed move keeps the whole
  backup folder (files already moved stay in update-leftovers, so each file is in exactly one place) and the next
  update's prune tries again. The live tree is walked once per prune, only when something is to be pruned
  (`os.walk`, no per-file stat). `update-leftovers/` added to .gitignore.
  I4 review: 2 findings, 2 fixed, 0 rejected: (1) a bumped vendored library no longer lands its old
  `vendor/*.dist-info` folder and dropped modules in update-leftovers: the backup's own dist-info files and the
  paths each RECORD lists are program files (`_vendored_files`; a release manifest was not added, since the
  dist-info RECORDs cover the frequent case and wowtools/scripts/docs drops stay rare); (2) `_apply_zip` now
  carries user files out of an existing `.update-backup/<current>` (left by reinstalling an older version) before
  deleting it, and stops with UpdateError before touching anything if a move fails. 3 new tests.
- I5: Windows Python 3.14.3 (`cmd.exe /c py -3`) ran the suite on a `git archive HEAD` copy under
  `%TEMP%\wow-tools-check-<stamp>` (no config/ or logs). First run: 6 failures, all test faults, none in the
  product: (1) `settle()` returned before the KeyFooter recomposed (`call_after_refresh`), so tests read an empty
  footer or laid out the menu before the footer's row count changed: `settle` now also waits while a visible
  KeyFooter (top screen, and the screen under popups) has not composed, lists other keys than `footer_bindings`,
  or has keys not mounted and laid out; (2) it now also waits while the app or a widget of the top screen has
  queued messages (a rebuild's NodeExpanded was handled after the check under 16-shard load); (3) the pre-1970
  backup test used FILETIME 0, which SetFileTime takes as "leave unchanged": it now uses one day later and skips
  if the stat does not show a negative time; (4) the 120x30 result-summary check now lets only the journal's path
  overflow, by no more than its excess over the other values (a long Windows temp path). Linux suite time
  unchanged (~55 s on drvfs). The happy-path script stayed a scratch file (CI's windows jobs already run the same
  core paths through test_wtf_undo/test_cleaner); it ran against a `build_wow_tree` fixture, not a real WTF copy.
  Observed on drvfs (WSL Python, /mnt/c): `atomic_write_text` never exposed partial content to a concurrent reader,
  but a reader saw ENOENT 71 times in ~1000 reads during `os.replace` (drvfs replace is not atomic to readers;
  NTFS-native and ext4 showed none). Not fixed: the app never reads its config while saving it; recorded here.
  On native Windows a replace while a reader holds the file open raises PermissionError (253/500 in the stress),
  as the M2 skip note already says. Temp copy removed afterwards.
  I5 review: 5 findings, 5 fixed, 0 rejected: (1+4, one defect) the journal row overflowed at 120x30 for a real
  install too (the default `C:\Program Files (x86)\World of Warcraft\...\journal-<stamp>.jsonl` is 100 chars):
  a journal outside the backup folder now gets a "Journal folder" row plus a "Run journal" row with its name and
  the Undo note (one-flavor and multi-flavor summaries); the test is strict (0, 0) again and also requires spare
  width for a root as long as the default install's, allowing overflow only by a longer temp root's excess over it;
  (2+5) `settle()` now fails at its deadline naming what was still busy, and the stale footer it found was a real
  glitch: `Ka0sApp.busy` is now a property whose change refreshes the bindings (the footer showed `s` while busy
  until the next screen change); (3) `atomic_write_bytes` retries `os.replace` on PermissionError on Windows for
  about a second (`REPLACE_RETRY_WAITS`), 3 tests. drvfs readers seeing ENOENT mid-replace stays reader-side and
  unfixed (recorded above).
- I6: the review bundle stays frozen apart from the filled placeholders, a "Measured after" column in the
  final summary's performance table (values from the review-fixes ledger: 85-88 ms log writes, 86 ms confirm), a
  "Closed 2026-10-06" line in both files, and a note that F-027 was fixed on the same branch after all (7ddca2d)
  and F-018 `keep_cleaned` / per-account enabled sets follow here (#4, #5). Commit range given as `6e9ac1f..fcdb5ac`
  (first parent of 96c3527 to the branch head); CI cites run 37157279879 (the R3 push) with the Actions URL. No
  other status ledger said "awaiting merge"; plans with no ledger were left alone.
