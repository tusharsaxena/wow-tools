# Open GitHub issues: plan

Branch: `fix/open-issues`. Ledger: `2026-10-06-open-issues.status.md`. Resume at the first ledger row not `done`.
Every task: tests green (`python3 scripts/run_tests.py`), ruff clean (`ruff check --no-cache .`), event docs
regenerated if a registry changed, docs touched by the task updated, ledger row updated, commit. Push after each
milestone. Never merge, tag or release without the user's go-ahead.

## Decisions (user, 2026-10-06)
- #2 screenshots: the user captures them; post the exact capture list on the issue, leave it open.
- #3 first release: not ready; do nothing, mark `state:triaged`.
- #4 cleaned-file zips: a WTF Cleaner-specific setting `keep_cleaned` (in `wtf-cleaner.cfg`), default 0 = never
  pruned; when N > 0 keep the newest N cleaned zips per game version. An explicit exception to "retention is global"
  (CLAUDE.md notes it).
- #6 signed tags: will not do (zip installs already check SHA256SUMS); close as not planned.

## M1: code fixes
- **I1 (#1)** Detect a running WoW on macOS: `core/process.py` gains a macOS branch (`ps -axo comm=` style listing,
  no new dependency), mapped to the same WoW process names; tests with a fake runner; README FAQ, guides and
  architecture stop saying macOS has no warning.
- **I2 (#4)** `keep_cleaned` for WTF Cleaner cleaned zips (setting on the WTF Cleaner settings screen, validation,
  pruning after a clean per flavor, event, tests, docs, CHANGELOG).
- **I3 (#5)** Per-account enabled-addon sets in the WTF Cleaner scanner: an addon counts as enabled for an
  account's files only if it's enabled for a character of that account (account-wide files judged per account);
  multi-account fixture tests; docs.
- **I4 (#7)** Before `prune_update_backups` deletes an old `.update-backup` folder, carry user-added files (files in
  managed folders that the release did not ship) out of it so they survive; tests; docs.

## M2: verification and housekeeping
- **I5 (#8)** Run the suite natively on Windows (Windows Python via WSL interop, repo copy on an NTFS path) and a
  scripted WTF Cleaner happy path (scan, clean, backup zip, undo) on a fixture WTF copy on NTFS; record the result
  in the review-fixes ledger M2 row and in this ledger.
- **I6 (#9, #10)** Fill the 2026-10-04 review bundle's sign-off table and placeholders (SHAs, merge commit, CI);
  mark the merged plans' ledgers as merged.
- **I7** Whole-branch review, fixes, push; ask for the merge. After the merge: close #1 #4 #5 #7 #8 #9 #10 as
  `state:done`, #6 as `state:will-not-do`, #3 `state:triaged`, comment the capture list on #2; delete the branch.
