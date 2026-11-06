# Config Copier feedback round 1: status

Branch `feat/config-copier-feedback-1`. Plan `2026-11-06-config-copier-feedback-1.md`. Resume at the first row not
`done`.

## Resume here

- **Round complete:** P1-P6 done (P6: the user's smoke-test follow-up). CI green on `356274e` (run 42271416975). Merging into master waits for the user's approval;
  no release (the user smoke tests the Config Copier again first).

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| P1 | Change source on `p` (CP1) | done | bae360b, (this commit) | 6 new tests (`ChangeSourceTest`); gate green: 2432 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes: the fresh-review test now picks Dænerys (Bob stays the ticked target) and checks `files` too, so carried-over ticks fail it (checked against a shared-ticks mutant); `#source-row` margin dropped (the Files heading's own margin keeps one blank row, one row back at 80x24); gate green again, same counts |
| P2 | Diff stands out: confirm kind, reason line (CP3) | done | 2825a5e | 5 new tests (`DiffReasonTest`: confirm kind and colour, the line on a character row and gone on a replaced pair at 120x30 and 80x24, refit on resize, empty during a scan and a run, `fit_reason` cuts) and `"Diff": "confirm"` pinned in `test_same_label_same_colour`; gate green: 2437 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes: `assert_fits_beside_the_button` now pins the button's place and full width and the line right after its gap, at 120x30 and 80x24 (P2r) |
| P3 | Side-by-side diff rows and screen (CP4) | done | 01ddaf6, (this commit) | 12 new tests: 8 unit (`SideBySideRowsTest`: equal, delete, insert, replace of unequal lengths both ways, gaps and context as `diff_rows`, config file whole with KEPT notes, empty old or new file, bytes only) and 4 screen (`SideBySideDiffTest` at 120x30: both sides aligned with their numbers and colours, config kept notes, a long line cut with `…` on one row, bytes-only and same-files lines); gate green: 2449 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes (P3r): the note column is a short dim `kept` (head explains it once), so a changed config value shows on both sides at 100 columns; a removed / added line's number reads `-N` / `+N`; 3 new tests (100-column config values, marks without colour, CRLF-only config-cache.wtf side by side with its rows and BYTES_ONLY), the guide's pinned `kept` string moved in `test_docs.py`; gate green: 2452 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. One WSL-only failure under `--all` in the untouched `test_restore_from_backup_result_goes_to_the_backup_just_made` (`'anniversary' != 'classic_era'`) passed on the rerun (environmental) |
| P4 | Inline on `v`, width rule, session view (CP4) | done | 1c87e35, (this commit) | 10 new tests (`DiffViewTest`: 120x30 opens side by side with no note and a `navigate` View (v) button and `v` on the hint; 80x24 opens inline with the note; the rule at 99 / 100 columns; `v` and the button switch both ways, logged, focus back on the scroll; `v` at 80x24 drops the note and the choice carries both ways; the choice carries at 120x30; it outlives Change source and is gone after the tool is closed; a resize while open changes nothing either way; the inline view is `diff_text`; help and guide name `v` and the note); gate green: 2462 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes (P4r): `v` dropped from the diff hint (STD-8.6), the base test now asserts it is absent and runs `assert_keys_on_buttons` on the DiffScreen; a view switch starts the new view at its top; 1 new test (`test_a_switch_goes_back_to_the_top`, an 80-line replaced file at 120x30, both ways); gate green: 2463 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step |
| P5 | CHANGELOG, whole-branch review, push, CI | done | e8b6747 (CHANGELOG), 4388176 (review fixes) | CHANGELOG line done (e8b6747). Whole-branch review: 8 confirmed findings (2 important, 6 minor; two of the minor ones are the same `p` / `v` guide-key gap), all fixed (P5r). Fixes: after a rebuild the review refreshes its summary, Diff button and reason line once the tree has its new lines (`call_after_refresh`), so a copied pair or an unticked file box no longer leaves Diff enabled with no reason; `WrapButtonRow.button_need(button)` holds the per-button width rule once, used by `_fit` and the Diff bar; 4 new tests (`test_the_button_and_the_line_follow_a_rebuild`, `test_p_during_a_scan_leaves_and_the_late_result_stays_on_the_old_review`, `test_a_gap_between_two_parts_shows_on_both_sides`, the long-line test now also uses a line with spaces); the guide's `p` / `v` keys and rows pinned in `test_docs.py`; review.png noted stale. The no_wrap and GAP mutants now fail. Gate green: 2466 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Push and CI still to come Pushed; CI run 42258087083 on 4388176 green (Windows / 3.13 slowest shard 534 s, Linux / 3.10 794 s, of 1500 s). |
| P6 | Diff colours as backgrounds, GitHub's look (user smoke test) | done | 356274e | 2 new tests (test_ui_base::test_diff_backgrounds: white at 7:1 or better on both, red and green hues; SideBySideDiffTest::test_the_inline_view_has_the_same_backgrounds) and the side view's colour assertions now check white text on the filled backgrounds; no assertion loosened (the kept line checks it is not a diff colour). Gate green: 2468 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Pushed; CI run 42271416975 on 356274e green |

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
- P4a (builder, my call): the session view is a `DiffSession` dataclass (`view`: `SIDE`, `INLINE` or None) in
  `diff_screen.py`; `CopierFlow` makes one and hands it to every `CopierReviewScreen` it opens (`diff_session=`),
  which passes it to each `DiffScreen`. So the choice carries to the next diff and across Change source, and dies
  with the flow when the tool closes. A screen built without one (tests) makes its own.
- P4b (builder, my call): the button is **View** (`v`), a `navigate` button beside Back on the diff screen's button
  row, the label the SV Browser's `v` button already uses (one label, one kind); the hint line reads
  `v side by side / inline`. After a switch the focus goes back to the diff's scroll, so a click on View leaves the
  arrow keys scrolling.
- P4c (builder, my call): the note is the spec's text as written, `opened inline: the window is narrow`, dim italic on
  a second head line; `v` drops it for good (the width rule no longer applies once a view was chosen). The width
  read is `app.size.width < NARROW_WIDTH` (100) in `on_mount`.
- P4d (builder, my call): `v` logs `ui.selection` (`screen="copier_diff"`, `control="view"`, value the new view), as
  the Ace3 Profile Manager's view switch does; no new event.
- P4e (builder): the plan's milestone push after P4 is left to the workflow (this task's brief forbids the builder
  to push).
- P4r (review fix, my call): finding 2 (important, STD-8.6): the diff screen's hint no longer names `v`; the key is
  shown on the View (v) button only, as on the SV Browser. STD-8.6 is a MUST and the fix conforms to it, so no
  deviation row: the spec's (CP4) and plan's (P4) "on its hint line" wording is overridden by STD-8.6. The STD-8.6
  check now covers the DiffScreen: `test_base_opens_side_by_side_with_no_note` asserts `v` is not in the hint and runs
  the shared `assert_keys_on_buttons` (which checks hints) on the screen.
- P4r (review fix, my call): finding 1 (minor, scroll after `v`): `_show` resets `#diff-scroll` to the top
  (`scroll_home(animate=False)`) on every draw, rather than mapping the first visible row across views: cheap,
  never lands on unrelated lines, and the views share no row index. Mapping rows through `_diff_groups` is deferred
  (not asked for by the spec; revisit if users want to keep their place).
- P5r (review fix): finding 1 (important, a stale Diff state after a rebuild): `_rebuild` runs `_update_summary`
  through `call_after_refresh`, after the cursor is put back, so `cursor_node` is a node of the new tree. The stale
  read was older than this branch (the summary's `Selected:` was stale too); the fix covers both.
  `test_the_button_and_the_line_follow_a_rebuild` covers a Write of the highlighted pair and an unticked file box.
- P5r (review fix): finding 2 (minor, the Diff bar's width rule copied from `WrapButtonRow._fit`):
  `WrapButtonRow.button_need(button)` (label + 2 + `GUTTER`) is the one place; `_fit` and the review's `on_mount`
  call it. No behaviour change.
- P5r (review fix): findings 3 and 7 (minor, the guide's `p` and `v` not pinned): `test_docs.py` adds `` `p` `` and
  `` `v` `` to the key tuple and pins `**Change source** (`p`)` and both keys-table rows.
- P5r (review fix): finding 4 (important, no_wrap unpinned for lines with spaces): the long-line test also draws a
  macro line with spaces; dropping `no_wrap` now fails it. Finding 5 (minor, the gap row not drawn in any screen
  test): `test_a_gap_between_two_parts_shows_on_both_sides`; blanking the GAP cells now fails it.
- P5r (review fix, my call): finding 6 (minor, `p` during a scan not covered): the test holds the old review's
  rescan, presses `p`, picks Dænerys, then lets the scan finish. It checks that the new review has only its own
  plans and no ticks, and that the late result went to the old review. Removing the `is_attached` guard in
  `_scanned` still does not fail it. Without the guard, the late result rebuilds the detached screen's own tree,
  which nobody sees. The guard is defensive; the behaviour P1b promises is what the test pins.
- P5r (review fix): finding 8 (minor, a stale screenshot not noted):
  `docs/assets/screenshots/config-copier/review.png` (used in the guide and the README) is stale. It predates the
  Change source button, the blue Diff button and its reason line. It is left for the user to retake (spec builder
  notes); the diff screen has no screenshot.
- P6a (user, 2026-11-06 smoke test): a removed or added line is white text on a darker red or green background, as
  on GitHub, instead of red or green text. My calls: `ui/theme.py` `DIFF_REMOVED_BACKGROUND` `#8E3B3B` and
  `DIFF_ADDED_BACKGROUND` `#2A6340` (white reads at 7.4:1 and 7.1:1, WCAG AAA), `DIFF_TEXT` white; the background
  runs from the line number to the column's edge (no grid padding: the spaces live inside the cells, so no navy gap
  between number and line) and to the pane's edge in the inline view; the `│` separator, kept lines and the `kept`
  note keep the screen's background. Bold is dropped (white on a fill reads without it).
