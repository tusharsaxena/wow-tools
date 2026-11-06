# Config Copier feedback round 1: status

Branch `feat/config-copier-feedback-1`. Plan `2026-11-06-config-copier-feedback-1.md`. Resume at the first row not
`done`.

## Resume here

- P1, P2 and P3 done (Change source on `p`; Diff a `confirm` button with its reason line; side-by-side diff rows
  and screen). Next: **P4** (inline on `v`, the 100-column width rule, the session view, CP4; then push).
- Spec, plan and ledger committed. Build runs as a workflow: per task implement (test first), review, fix; each
  task's row goes `done` with its commits. Push after P4; P5 is the whole-branch review, push and CI. Merge into
  master needs the user's approval.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| P1 | Change source on `p` (CP1) | done | bae360b, (this commit) | 6 new tests (`ChangeSourceTest`); gate green: 2432 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes: the fresh-review test now picks Dænerys (Bob stays the ticked target) and checks `files` too, so carried-over ticks fail it (checked against a shared-ticks mutant); `#source-row` margin dropped (the Files heading's own margin keeps one blank row, one row back at 80x24); gate green again, same counts |
| P2 | Diff stands out: confirm kind, reason line (CP3) | done | 2825a5e | 5 new tests (`DiffReasonTest`: confirm kind and colour, the line on a character row and gone on a replaced pair at 120x30 and 80x24, refit on resize, empty during a scan and a run, `fit_reason` cuts) and `"Diff": "confirm"` pinned in `test_same_label_same_colour`; gate green: 2437 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes: `assert_fits_beside_the_button` now pins the button's place and full width and the line right after its gap, at 120x30 and 80x24 (P2r) |
| P3 | Side-by-side diff rows and screen (CP4) | done | 01ddaf6, (this commit) | 12 new tests: 8 unit (`SideBySideRowsTest`: equal, delete, insert, replace of unequal lengths both ways, gaps and context as `diff_rows`, config file whole with KEPT notes, empty old or new file, bytes only) and 4 screen (`SideBySideDiffTest` at 120x30: both sides aligned with their numbers and colours, config kept notes, a long line cut with `…` on one row, bytes-only and same-files lines); gate green: 2449 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes (P3r): the note column is a short dim `kept` (head explains it once), so a changed config value shows on both sides at 100 columns; a removed / added line's number reads `-N` / `+N`; 3 new tests (100-column config values, marks without colour, CRLF-only config-cache.wtf side by side with its rows and BYTES_ONLY), the guide's pinned `kept` string moved in `test_docs.py`; gate green: 2452 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. One WSL-only failure under `--all` in the untouched `test_restore_from_backup_result_goes_to_the_backup_just_made` (`'anniversary' != 'classic_era'`) passed on the rerun (environmental) |
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
- P2r (review fix, my call): the one finding (nothing pinned the Diff button's own width and place) is fixed in
  the test only: `assert_fits_beside_the_button` asserts the button is as wide as its whole label + 2, sits at the
  row's content start, and the reason line starts at `button.region.right + ActionBar.GUTTER`. A bar cut to the
  bare label and a bar 6 cells too wide both fail it now.
- P3a (builder, my call): `report.SideRow` is a NamedTuple (left_no, left, left_mark, right_no, right, right_mark,
  note); marks `" "` kept, `"-"` removed, `"+"` added, `""` a blank side; a gap is `GAP_ROW` (GAP as both marks and
  texts, no numbers). `diff_rows` and `side_by_side_rows` share `_diff_groups` (the same lines, opcode groups and
  KEPT test), so the two views can never show different lines. A plain file with no line changed gives no row in
  either view (difflib's grouped opcodes are empty), as before: the screen says `The files are the same.`
- P3b (builder, my call): `DiffScreen.side_view` draws the rows as a Rich `Table.grid` (number, line, dim `│`,
  number, line; a dim italic note column only when a row has a note): the two line columns share the width (ratio
  1 each), `no_wrap` with `overflow="ellipsis"`, so a long line is cut with `…` and every row stays one screen row;
  Rich refits it on a resize by itself. A removed line and its number are bold red, an added one bold green, kept
  lines plain. `diff_text` (the unified view) is kept as it is for P4; the head counts still come from `diff_rows`.
  Until P4 lands the screen opens side by side at every width (at 80x24 each side has about 33 cells).
- P3c (builder, my call): P3 lists no docs, but the user guide's Diff sentence described `-` / `+` lines, so it and
  the internals doc are updated now; the keys table, `help.py` and the rest of the Diff section stay for P4.
- P3r (review fix, my call): finding 1 (important, the fixed 22-cell note column hid changed config values): the
  side view's note column holds `KEPT_MARK` = `kept` (4 cells) and the head says once `N state lines kept as they
  are, the target's own (marked kept).`; `report.KEPT` and the inline view's note are unchanged. At 100 columns each
  side now has about 42 cells; at 80x24 a long `SET` value can still be cut (P4 opens inline there).
- P3r (review fix, my call): finding 2 (minor, no mark without colour): the mark goes on the line number (`-5`,
  `+5`, kept lines unmarked), one cell at most, not a column of its own, so kept rows lose no width.
- P3r (review fix): finding 3 (minor, test gap) taken as written: a CRLF-only config-cache.wtf drawn side by side
  shows its rows and BYTES_ONLY, never `The files are the same.`
