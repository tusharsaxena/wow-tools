# Config Copier feedback round 1: status

Branch `feat/config-copier-feedback-1`. Plan `2026-11-06-config-copier-feedback-1.md`. Resume at the first row not
`done`.

## Resume here

- P1 and P2 done (Change source on `p`; Diff a `confirm` button with its reason line). Next: **P3** (side-by-side
  diff rows and screen, CP4).
- Spec, plan and ledger committed. Build runs as a workflow: per task implement (test first), review, fix; each
  task's row goes `done` with its commits. Push after P4; P5 is the whole-branch review, push and CI. Merge into
  master needs the user's approval.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| P1 | Change source on `p` (CP1) | done | bae360b, (this commit) | 6 new tests (`ChangeSourceTest`); gate green: 2432 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes: the fresh-review test now picks Dænerys (Bob stays the ticked target) and checks `files` too, so carried-over ticks fail it (checked against a shared-ticks mutant); `#source-row` margin dropped (the Files heading's own margin keeps one blank row, one row back at 80x24); gate green again, same counts |
| P2 | Diff stands out: confirm kind, reason line (CP3) | done | (this commit) | 5 new tests (`DiffReasonTest`: confirm kind and colour, the line on a character row and gone on a replaced pair at 120x30 and 80x24, refit on resize, empty during a scan and a run, `fit_reason` cuts) and `"Diff": "confirm"` pinned in `test_same_label_same_colour`; gate green: 2437 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step |
| P3 | Side-by-side diff rows and screen (CP4) | todo | | |
| P4 | Inline on `v`, width rule, session view (CP4) | todo | | |
| P5 | CHANGELOG, whole-branch review, push, CI | todo | | |

## Decisions taken during the build

- P0a (builder check, my call): the review dismisses with `"source"` and `CopierFlow` reopens `SourceScreen` with
  the same flavors and label; the new review's file boxes start as any fresh review's.
- P0b (builder check, my call): an explicit `v` wins over the 100-column rule; the width is read on open only; the
  Diff reason line is cut to the room after the button and hidden under 10 cells (spec CP3, CP4).
- P1a (builder, my call): **Change source (p)** is a compact `navigate` button on its own row right under the Source
  line (`#source-row`, a `ButtonRow`), not beside it: the source text keeps the pane's whole width (a long
  `Flavor › ACCOUNT › Realm/Name` wraps at 80 columns), and the button never moves.
- P1b (builder, my call): the button is never disabled, as `f` and `t` are not: `action_change_source` goes through
  `action_leave("source")`, which refuses silently while a run writes (only `t` says why, L11). During a scan it
  leaves at once; the scan's late result lands on the old review object (gone from the stack), never the new one.
- P1c (builder, my call): `CopierFlow._review` wraps the shared `_after_review` in a closure that turns `"source"`
  into `_pick_source(flavors, label)`; `ToolFlow` is unchanged (no other tool has a source to change).
- P2a (builder, my call): the Diff bar (`#tree-actions`, still an `ActionBar` so ↑ goes back to the tree) sits in a
  `#diff-row` Horizontal with the reason line; the bar is set as wide as its one button plus its gap
  (label + 2 + `GUTTER`) and the row takes the old `padding: 0 1` (a padded bar would give the button the padding's
  cells, as `WrapButtonRow._fit` spans `size.width`). The button keeps its place and width; at 80x24 the line has
  17 cells (`highlight a repl…`), at 120x30 the whole text.
- P2b (builder, my call): `ReasonLine` (a dim italic one-row `Static`) and `fit_reason` (Rich `truncate` with
  ellipsis, `""` under `MIN_ROOM` = 10) live in `review_screen.py`, not `ui/`: only the Config Copier uses them; move
  them to `ui/widgets.py` when a second tool needs one. The line is set in `_refresh_buttons` (which runs on every
  highlight, scan start and end, and busy change) and refits itself on its own resize.
- P2c (builder, my call): the user guide names the reason text in bold; the `d` key's notify (`NO_DIFF`) is kept as
  it is (a key press with no button in view still says why).
- P1r (review fix, my call): `#source-row` loses its `margin-bottom: 1`; the `.section` heading under it already has
  `margin-top: 1`, so the gap was two rows. One row comes back for the left pane at 80x24 (it still scrolls there,
  as before this task; STD-7.23 makes 80x24 a floor, not a fit).
