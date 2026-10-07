# Bottom bars during a scan, one-press Leftovers: status ledger

Plan: `2026-10-07-feedback-bars-leftovers.md`. Spec: `../specs/2026-10-07-feedback-bars-leftovers-design.md`.
Branch: `fix/feedback-2026-10-07-b`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| L0 | spec, plan, ledger | done | (this commit) | user feedback 2026-10-07 |
| L1 | one-press Leftovers | done | (this commit) | `o` / the Leftovers button tick every shown leftover (`_tick_leftovers`, now returning whether it ticked any) then confirm the ticked leftovers; No keeps the ticks; none shown: notice, nothing staged. 4 tests in `OnePressLeftoversTest` (written first, failed first), 3 more after review (L1-e). Tip, help, guide, internals, CHANGELOG updated. Full suite 1804 tests OK (2 skipped), ruff clean, events check OK |
| L2 | bars stay at the bottom during a scan + standard | todo | | |
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
