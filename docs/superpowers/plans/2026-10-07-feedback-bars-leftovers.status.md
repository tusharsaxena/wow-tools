# Bottom bars during a scan, one-press Leftovers: status ledger

Plan: `2026-10-07-feedback-bars-leftovers.md`. Spec: `../specs/2026-10-07-feedback-bars-leftovers-design.md`.
Branch: `fix/feedback-2026-10-07-b`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| L0 | spec, plan, ledger | done | (this commit) | user feedback 2026-10-07 |
| L1 | one-press Leftovers | done | (this commit) | `o` / the Leftovers button tick every shown leftover (`_tick_leftovers`, now returning whether it ticked any) then confirm the ticked leftovers; No keeps the ticks; none shown: notice, nothing staged. 4 tests in `OnePressLeftoversTest` (written first, failed first), 3 more after review (L1-e). Tip, help, guide, internals, CHANGELOG updated. Full suite 1804 tests OK (2 skipped), ruff clean, events check OK |
| L2 | bars stay at the bottom during a scan + standard | done | (this commit) | `two_pane_css` gives `#scan-box` `height: 1fr` (was `auto`): the scan box takes the tree's space on every two-pane screen. Test first (`test_bars_keep_their_place_while_a_scan_runs`, failed first: SV Browser's action bar at y 6 during the scan, 42 after at 160x45; blacklist scan box 5 rows high): every review on a rescan and the Ace3 blacklist on its first scan, worker held on a gate, at BASE and LARGE. STD-7.25 added; architecture look and feel, two_pane_css docstring, tree-screen recipe, CHANGELOG. Review fixes L2-d (failed scan on one row, `SummaryLine`), L2-e rejected. Full suite 1806 tests OK (2 skipped), ruff clean, events check OK (`test_restore_from_backup_result_goes_to_the_backup_just_made` failed once in one run: a flake that also fails on 5d9408a, 1 in 6 alone) |
| LR | review, green gate, push | todo | | |

## Decisions taken during the build

- L1-a: the action tip of **Leftovers** no longer depends on the ticks or the highlight: it counts the leftover
  characters shown (`_shown_leftovers`, shared with `_tick_leftovers`) and says it ticks them, then asks; with none
  shown it gives the same "No leftover characters are shown." as the action.
- L1-b: the confirm takes every ticked leftover, so a leftover ticked earlier and then hidden by the filter or a Show
  box is still included, and the popup's hidden-ticks line says so (as before). To remove only some, the guide says
  to narrow the tree with the filter first.
- L1-c: the press is logged as the existing `ui.selection` `tick_leftovers` event (no new event), then the usual
  staging; the CHANGELOG line goes under a new `### Changed` heading of [Unreleased].
- L1-d (review of L1): kept as specified, not changed: with no leftover shown, **Leftovers** gives the notice even
  when leftovers ticked earlier are now all hidden (before L1 it removed them). L1 says "none shown: notice, nothing
  staged", the guide documents it, and the one-press action acts on what the tree shows; with at least one leftover
  shown, the hidden ticked ones are still included (L1-b). To remove hidden ticked ones, show them again (or clear
  the filter) and press it.
- L1-e (review of L1): three tests added to `OnePressLeftoversTest` with a second leftover in another addon
  ("Ghost - Realm1" in HandyNotes_MapNotesDB, written into the temp tree): every shown leftover across two addons,
  the filter ticking only the shown one, and a ticked leftover hidden by the filter still included with the popup's
  "they are included" line (L1-b). The "never greyed out" sentence of the guide and the action-bar comment now say a
  button with nothing to act on says why (Leftovers: none shown), and the staging_actions docstring is re-wrapped
  to 120 columns.
- L2-a: the fix is the shared CSS only: every screen with a `#scan-box` builds it from `two_pane_css`, so the WTF
  Cleaner, Screenshot Organizer, Interface Backup, Ace3 review and blacklist, and Saved Variables Browser all get it
  at once. No other stand-in moves the bars: a failed or empty scan (and the Screenshot Organizer's folder problem)
  shows the tree again, empty, with the message in the bottom line, and a rebuild's load is the tree's own
  `loading` overlay, which keeps its size.
- L2-b: the test checks, during and after the scan, the y of the left pane's `#actions` row and of `#guide` and
  `#tree-actions` where a screen has them, and that the scan box has the tree's y and height. The reviews are
  measured on a rescan (`action_rescan`), the blacklist on the scan it starts when it opens; the screen class's
  `_scan_worker` is patched to wait on a `threading.Event`, set once the scan is measured (and on cleanup).
- L2-c: STD-7.25 is a MUST in section 7 next to STD-7.23 / STD-7.24; the tree-screen recipe in common-tasks.md
  lists it and names the test, so a new screen with a scan box is added to it.
- L2-d (review of 5d9408a): a failed scan put "The scan failed: <exception>" into the `height: auto` bottom line,
  so an error with a long WoW path wrapped and pushed the guide and action bars up a row per line. `SummaryBar` now
  composes a `SummaryLine` (warnings_view): `show_one_line(message)` adds `-one-line` (`text-wrap: nowrap;
  text-overflow: ellipsis`) and its next `update` takes it off. Every review's `_scan_failed` and the Screenshot
  Organizer's refused-folder line use it; the notice and the log keep the full message. The test now also runs each
  review with a failed scan (the held worker calls `_scan_failed` with a message far wider than the screen; failed
  first on all 10 cases), compares the rows before the rescan too, and measures the bottom line's y; a unit test
  checks the one row and the wrap after it. The docstring says the box-equals-tree check is the general one (the
  rows cannot move on screens with nothing under the tree). STD-7.25 names the failed-scan test and why an empty
  scan and a load need none; the CHANGELOG line drops "in every tool".
- L2-e (rejected): making the whole bottom line one row high, so a rescan that clears ticks never shifts the bars by
  the row the "N selected items are hidden by the filter" note took. That note, and the WTF Cleaner's "not scanned"
  flavors, sit at the end of the line and are warnings the user must read in full: an ellipsis at 120 columns would
  hide exactly them. The shift is one row, after the scan, because the new selection line is shorter, not the
  stand-in jumping; STD-7.25 says so.
