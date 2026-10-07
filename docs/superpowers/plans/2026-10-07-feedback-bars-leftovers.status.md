# Bottom bars during a scan, one-press Leftovers: status ledger

Plan: `2026-10-07-feedback-bars-leftovers.md`. Spec: `../specs/2026-10-07-feedback-bars-leftovers-design.md`.
Branch: `fix/feedback-2026-10-07-b`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| L0 | spec, plan, ledger | done | (this commit) | user feedback 2026-10-07 |
| L1 | one-press Leftovers | done | (this commit) | `o` / the Leftovers button tick every shown leftover (`_tick_leftovers`, now returning whether it ticked any) then confirm the ticked leftovers; No keeps the ticks; none shown: notice, nothing staged. 4 tests in `OnePressLeftoversTest` (written first, failed first), 3 more after review (L1-e). Tip, help, guide, internals, CHANGELOG updated. Full suite 1804 tests OK (2 skipped), ruff clean, events check OK |
| L2 | bars stay at the bottom during a scan + standard | done | (this commit) | `two_pane_css` gives `#scan-box` `height: 1fr` (was `auto`): the scan box takes the tree's space on every two-pane screen. Test first (`test_bars_keep_their_place_while_a_scan_runs`, failed first: SV Browser's action bar at y 6 during the scan, 42 after at 160x45; blacklist scan box 5 rows high): every review on a rescan and the Ace3 blacklist on its first scan, worker held on a gate, at BASE and LARGE. STD-7.25 added; architecture look and feel, two_pane_css docstring, tree-screen recipe, CHANGELOG. Review fixes L2-d (failed scan on one row, `SummaryLine`), L2-e rejected. Full suite 1806 tests OK (2 skipped), ruff clean, events check OK (`test_restore_from_backup_result_goes_to_the_backup_just_made` failed once in one run: a flake that also fails on 5d9408a, 1 in 6 alone) |
| L4 | shared risk disclaimer, once per session (WTF, Ace3, SVB) | done | (this commit) | `ui/disclaimer.py` `DisclaimerScreen(text, title)` (moved out of `sv_browser/popups.py`), `ToolFlow.ask_disclaimer(then, **data)` with the flow's `DISCLAIMER` / `DISCLAIMER_EVENTS`, `WowToolsApp.disclaimers_accepted` (by `SECTION`). WTF and Ace3 ask after the flavor and account picks; events `clean.disclaimer_*`, `ace.disclaimer_*` registered, events.md regenerated. 5 tests in `tests/test_risk_disclaimer.py` (written first; first open of each tool, not again in the session, Back/Esc does not count, per tool, WTF after the account pick); SV Browser's "each time the tool is opened" test now checks it is not asked again; WTF/Ace3/suite open helpers accept it (`accept_disclaimer`). Help, guides, internals, testing.md, architecture, README FAQ, CHANGELOG updated. Full suite 1811 tests OK (2 skipped), ruff clean, events check OK |
| L5 | `t` back to tools on the pickers | done | (this commit) | `FlavorScreen` and `AccountScreen` bind `t` ("Tools", action `tool_menu`) next to Esc (now labelled "Back"): the flavor picker dismisses with `None` as Esc does, the account picker with `account_screen.TOOLS`, which `ToolFlow.pick_account` turns into `close()`; Esc on it still goes back to the flavor picker. Hints name `t tools`. 5 tests in `tests/test_picker_keys.py` (written first, failed first: t on every tool's flavor picker and on both account pickers goes to the tool menu, Esc unchanged, footer lists `t` and Esc, hint names t). Suite help keys table (`t` row), the five guides' pick steps, architecture rows, CHANGELOG updated. Full suite 1816 tests OK (2 skipped), ruff clean, events check OK |
| LR2 | review of L4-L5, green gate, push, CI | done | (this commit) | Review of L4-L5 with the rest of the branch: the shared disclaimer gate, the three tools' texts and events, the `t` key on both pickers, help, guides, internals, README and CHANGELOG agree; no stale "each time you open the tool" text or old `sv_browser.popups` disclaimer left. Fix: `sv_browser/popups.py` module docstring re-wrapped (a short line left by the move) and its `ui.dialogs` import joined on one line. CI run 37672520492 failed on windows / 3.10 only: `test_preflight_runs_in_a_worker` took 1.8 s for a 1.0 s bound; the WTF preflight and Undo worker tests now bound at 4.0 s, under the held check's 5 s (which a check on the UI thread would wait out). Full suite 1816 tests OK (2 skipped), ruff clean, events check OK |
| LR | review, green gate, push | done | (this commit) | Whole-branch review: code, docs, help and CHANGELOG agree with L1-L3 and STD-7.25; fixes: the new import and docstring lines in the four reviews and `warnings_view` re-wrapped to 120 columns (STD-1.10), the internals line for Leftovers re-wrapped. Full suite 1806 tests OK (2 skipped), ruff clean, events check OK |

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
- L4-a: the gate lives on `WowToolsApp` (`disclaimers_accepted`, the tool's `SECTION`), not on `Ka0sApp`: only the
  suite app opens tools, and it already holds the open flow. The popup and the gate are shared (`ui/disclaimer.py`,
  `ToolFlow.ask_disclaimer`); each tool only sets `DISCLAIMER` (its text, in its UI-free `report.py`) and
  `DISCLAIMER_EVENTS` (its own registered accepted/declined names), so the events stay per tool (STD-6.3).
- L4-b: the WTF Cleaner's events take the `clean.` namespace (`clean.disclaimer_accepted` / `_declined`), next to
  its other bare-named events (documented deviation of STD-6.3); both tools log `flavors` and `account`, the SV
  Browser `flavors`, as before.
- L4-c: the WTF Cleaner's text says it deletes SavedVariables files (it never deletes folders), that the WTF folder
  is zipped first and Undo puts the files back; the Ace3 text names what it rewrites (rename, copy, delete
  profiles; move or remove characters) and the backups and Undo. Both end with the close-WoW paragraph and that
  every Clean / Apply and Undo asks again, as the SV Browser's text does.
- L4-d: the SV Browser keeps its D2 text word for word (now `report.DISCLAIMER_POPUP`); its FAQ "Why does it ask me
  every time?" is reworded for the once-per-session rule and no longer says no other tool can do damage.
- L4-e (review of 9615f05): the hub's `dialogs` row still named "the Saved Variables Browser's `DisclaimerScreen`"
  among the Esc-closable `ChoiceScreen`s; it now names the shared `ui.disclaimer.DisclaimerScreen` of the WTF
  Cleaner, Ace3 and the SV Browser, as the `disclaimer` row does. The two review findings were the same line.
- L5-a: the pickers bind `t` to their own action `tool_menu` (not `tools`: `action_tools` is the shared review
  machinery's name, which `test_review_machinery_lives_in_ui` keeps in `ui/review.py`), and the footer lists one key
  per action, so Esc keeps its own action and its label becomes "Back" (it was "Tools" on the flavor picker): the
  footer reads "t Tools  Esc Back" on both pickers. No button carries either key (D17).
- L5-b: the account picker dismisses with a `TOOLS` sentinel (`"__tools__"`, like `ALL_ID`), handled once in
  `ToolFlow.pick_account`, so the WTF Cleaner and Ace3 need no change. `t` is not logged, as Esc and the review's
  `t` are not (closing a tool is not a choice event).
- L5-c: no other pre-review picker exists: the SV Browser and the other tools have no account picker, and the
  setup and settings forms are forms with their own Save / Cancel, not pickers. The per-tool help pages do not list
  the picker keys; the suite help's keys table gets a `t` row and the guides' pick steps name `t` and Esc.
- L5-d (review of a23eaeb): README's "Navigating the app" keys table gets the same `t` row as the suite help
  (STD-9.5; two findings, one line). The flavor picker's hint named two keys for one action ("t tools · Esc back to
  tools"); it now reads "t/Esc tools", as the help's "Esc/q/h back" does. The account picker keeps "t tools · Esc
  back to flavors": there the two keys differ. The footer keeps one key per action ("t Tools  Esc Back", L5-a).
  The picker-keys test's 122-column setup line is wrapped (STD-1.10).
