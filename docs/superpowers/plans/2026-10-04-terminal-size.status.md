# Feedback round 2 (terminal size) — status ledger

Plan: `2026-10-04-terminal-size.md`. Spec: `../specs/2026-10-04-ace-profiles-design.md` (Addendum B).
Branch: `feat/ace-profiles`. Resume at the first task not marked `done`. Update this file and commit it after every
task; push after the round. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| S1 | shared sizes, tests, CSS; Ace3 headings back | done | 8c94fac | BASE/LARGE/TINY; look-and-feel at BASE + LARGE grow/popup checks + 80x24 smoke; POPUP_WIDTH; flow WrapButtonRow; View/Show headings. Suite 1024 tests, 0 failures; ruff clean. Renders in /tmp/wow-tools-shots/S1/ |
| S2 | WTF Cleaner, Screenshot Organizer, Interface Backup at 120x30 | todo | | |
| S3 | Ace3 screens at 120x30 | todo | | |
| S4 | docs | todo | | |
| R | review, fixes, push | todo | | |

## Decisions taken during the build

- Task S1: `FILTERS_WIDTH` stays 50. The left pane's four action buttons take 45 columns, so it can't shrink, and at
  120x30 the restored View and Show headings and the whole hint fit, so it doesn't need to grow. The tree takes the
  rest (`1fr`, 70 columns at 120x30).
- Task S1: popup width is the shared `POPUP_WIDTH` in `ui/dialogs.py` (`width: 90; max-width: 90%`). It is used by
  ConfirmScreen, ProgressScreen, Ace3 `popup_css`, `ProfileRecoveryScreen`, WTF Cleaner's `RecoveryScreen` and
  `LockScreen`. `UpdateScreen` (76) and `UpdateProgressScreen` (64) keep their narrower widths.
- Task S1 (moved forward from S3, needed for the Review Focus 5 tests): `WrapButtonRow` was a grid with one column
  width for every button (3 rows of 3 at 120x30). It now flows the buttons in order, each as wide as its label, as
  column spans on a grid of one-cell columns, so the action bar takes 2 rows at 120x30. At 160x45 it still takes 2
  rows (6 + 2); getting to 1 row there is left to S3.
- Task S1 (moved forward from S3): the guide's rule is now `GUIDE_MAX_ROWS = 2`, replacing `GUIDE_MIN_TREE = 5`.
  With pending changes, the node hint is dropped when the guide would take more than 2 rows. To fit, `STEPS` lost
  "; Dry run (y) only checks them" (3 rows at 68 columns before), and the pending line became "…, not written yet:
  Apply (w) writes, Dry run (y) checks, Discard (⌫) drops" (one row at 160x45, so pending + hint show together
  there). At 120x30 the pending line takes 2 rows on its own, so the hint is still dropped while changes are pending.
  S3's "drop the squeeze if it no longer triggers" doesn't apply yet; changing that needs shorter texts or a wider
  tree pane. `test_ace_report` and `test_ace_app` were updated for the new texts.
- Task S1: the docs this changes were updated in the same commit (`docs/ace-profiles.md` filter names,
  `docs/architecture.md` left pane headings and `GUIDE_MAX_ROWS`). S4 still owns the rest.
- Task S1: noticed for S2/S3 in the renders. At 120x30 the Footer key list is cut off at the right edge in the
  review screens (WTF Cleaner, Ace3). Interface Backup's result screen leaves an empty band under its detail table.
