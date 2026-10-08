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
| LR2 | review of L4-L5, green gate, push, CI | done | (this commit) | Review of L4-L5 with the rest of the branch: the shared disclaimer gate, the three tools' texts and events, the `t` key on both pickers, help, guides, internals, README and CHANGELOG agree; no stale "each time you open the tool" text or old `sv_browser.popups` disclaimer left. Fix: `sv_browser/popups.py` module docstring re-wrapped (a short line left by the move) and its `ui.dialogs` import joined on one line. CI run 37672520492 failed on windows / 3.10 only: `test_preflight_runs_in_a_worker` took 1.8 s for a 1.0 s bound; the WTF preflight and Undo worker tests now bound at 4.0 s, under the held check's 5 s (which a check on the UI thread would wait out). CI run 37674160141 failed on windows / 3.10 only, all tests OK: shard 1/4 took 594 s and passed the 600 s per-shard timeout while exiting; CI now runs `run_tests.py --timeout 900` (testing.md CI steps say why), the local default is unchanged. Full suite 1816 tests OK (2 skipped), ruff clean, events check OK |
| L6 | nothing blocks before the scan box (Screenshot Organizer + audit) | done | (this commit) | Evidence: the user's log (Windows) has 4.4 s between the flavor pick (08:35:00.605) and `shots.scan_started` (08:35:05.028) on the first open only, then 0.13 s of scan: `ShotReviewScreen.on_mount` ran `_refresh_undo` (`latest_undoable`) and `action_rescan` -> `validate_dest` (`install.flavors()` and `resolve()` of the destination, the first touch of drive H:) on the UI thread before the scan box. Fix: the scan box (label "Checking the destination folder", Organize / Dry run / Undo off) is shown first; the scan worker runs `validate_dest`, `latest_undoable`, then the scan ("Reading Screenshots folders"); a refused destination comes back as `_dest_refused` with today's UI. The WTF Cleaner had the same: `latest_undoable` on mount and after every scan, and `read_marker` on the backup folder on mount, on the UI thread. 5 tests in `tests/test_scan_box_first.py` (written first, all 5 failed first; 5 more from the L6 review, L6-e): each check held on an `Event` gate while the scan box is asserted shown, then the normal tree; the refused destination still gives the error state and no scan. STD-7.20 sentence and Enforced by, both internals, CHANGELOG. Full suite 1821 tests OK (2 skipped), ruff clean, events check OK |
| LR3 | review of L6, green gate, push, CI | done | (this commit) | Review of L6 with the rest of the branch: the scan box first in both tools, the workers' Undo lookups, the recovery notice gate, STD-7.20, internals and CHANGELOG agree. Fix: `latest_undoable` (core `journal`) never raises: L6 moved it into the scan and run workers (the WTF Cleaner's scan worker and both tools' run workers call it outside a `try`), where an unlistable journal folder (`iterdir` raising `OSError`) would have ended the worker with an error; it now offers nothing. Test first (`test_latest_undoable_never_raises_on_a_folder_it_cannot_list`, failed first); architecture `journal` row. Full suite 1827 tests OK (2 skipped), ruff clean, events check OK |
| L7 | `q` quits from any screen | done | (this commit) | Why q did nothing on the flavor picker: `q` was bound per screen (the menu `app.quit`, each review `leave('quit')`, each result `choose('quit')`, the lock warning; the help and the changelog bound it to Back) and the pickers, settings, warnings, blacklist and popups had none. Now `Ka0sApp.key_q` -> `action_quit` (busy: refused with the `ui.quit_refused` notice; work staged on a review in the stack: its `discard_question()` asks first; else `exit()`, the path suite.run follows with session.end and the lock release). Reviews bind `q` to `app.quit` (footer kept); `ReviewBase.discard_question` / `action_leave` replace the Ace3 and SV Browser `action_leave` copies; help and changelog no longer close on q. 4 tests in `tests/test_quit_key.py` (written first, failed first: every screen of every tool, menu / changelog / help / settings at BASE and LARGE, filter and settings field type q, busy refused, staged asks once and No keeps it); help and changelog tests now close with Esc / h. STD-8.11, architecture, README and suite help keys, CHANGELOG, `ui.quit_refused` description and events.md. Review fixes L7-e (`DiscardScreen`, no flag, 5 more tests, `QuitBindingsTest`). Full suite 1837 tests OK (2 skipped), ruff clean, events check OK |
| L8 | "Don't show this again" on the risk popup | done | (this commit) | `DisclaimerScreen` gets a `DontShowCheckbox` "Don't show this warning again for this tool" (`ChoiceScreen.extras()`; Tab reaches it, Space ticks, Enter on it presses I understand; I understand with it ticked dismisses `ACCEPT_DONT_SHOW`). `ToolFlow.ask_disclaimer` skips when `[SECTION] skip_risk_warning` (`core.config.SKIP_RISK_WARNING`) is true and saves it on a ticked accept (atomic `Config.save`); Back/Esc never save. The three settings forms get "Show the USE AT YOUR OWN RISK warning" (`ToolSettingsScreen.risk_warning_box()`, last field; all fit at 120x30); each tool's `skip_risk_warning` setting field. Events `clean.` / `ace.` / `svb.risk_warning_changed` (shown, source) registered, events.md regenerated. 6 tests in `DontShowAgainTest` (`tests/test_risk_disclaimer.py`, written first, failed first; the failed-write one after); WTF keyboard settings test takes the new box. Help (3), guides (3), README settings, architecture, internals (3), CHANGELOG. Full suite 1843 tests OK (2 skipped), ruff clean, events check OK |
| L9 | one toast anchor and stack | done | (this commit) | Why they overlapped: the toasts were placed per screen (`ui/review.py` `lift_toasts`, called by the SV Browser's `place_toasts` and the Ace3 `_place_overlays`; every other screen kept Textual's rack one row up, over the bottom line), and the Ace3 `#tip-rack`'s `auto` height was a row short of a tip that wraps at its scrollbar-narrowed width, so the tip hung over the guide and under the toasts. Now `ui/toasts.py`: `install(app)` (from `Ka0sApp.on_mount`) subscribes to `screen_change_signal` and to each shown screen's `screen_layout_refresh_signal`; `place_toasts` puts the rack on `toast_floor` (top of `BottomBar`, `SummaryBar`, `Footer`, `ActionBar`, `.toast-floor`; a popup without bars uses the screen under it); `TipRack` / `StackTip` (Ace3 `ActionTip`) are the stack's lowest box, the rack sized to the tip. Removed: `lift_toasts`, `ActionBar.on_mount`, SV Browser `place_toasts`, Ace3 `_place_overlays`, `ActionTip.on_resize` and the screen's `layers` CSS. Tests first in `tests/test_toast_stack.py` (failed first: the WTF Cleaner review's toasts covered the bottom line): 3 toasts on every screen of every tool (+ the Ace3 tip) at BASE and LARGE, menu / changelog / help / setup, one right edge, lowest box on the bars, no overlap, no bar covered; `OneHelperTest` (only `ui/toasts.py` names the rack). STD-7.24 is now a MUST for this (folded, not a new ID); architecture `toasts` and `base` rows, Ace3 internals, tree-screen recipe, testing.md, CHANGELOG. No new event. Full suite 1848 tests OK (2 skipped), ruff clean, events check OK. Review fixes L9-e (toasts clear a popup's own controls, `PopupStackTest`, STD-7.24 citations): full suite 1849 tests OK (2 skipped), ruff clean, events check OK |
| L10 | long warning lists collapse | done | (this commit) | Why Yes/No went off the popup: the Ace3 `report.apply_confirm` returned one red alert line per addon warning, all printed in the ConfirmScreen body, so 28 warnings made the box taller than the window and it scrolled its buttons away. New shared `ui/dialogs.CountedTree` (entries `core.text.Listed(message, where, item)`; one collapsed counted row "⚠ N warnings (Space or click to expand)" → message (n) → where (n) → items, the label flips to "collapse" when open) taken by `ConfirmScreen` and `InfoScreen` as `listed=` (`noun=`); `TreeKeys` acts on the focused tree when a popup has two. Adopted: the Ace3 Apply and Dry run confirms (warnings) and the Ace3 Notes popup (`OpResult.notes` are now `Listed`, where = `ops.where_of`: "Retail · ACCT1"). Audit of every other popup in L10-b. Tests first (`tests/test_counted_list.py`: 300 warnings at 120x30 and 160x45 on a confirm and an info popup, Tab reaches the tree, Space/Enter/x/c, buttons on screen and the box unscrolled; the grouping; Ace3 `test_apply_warnings_collapse_behind_a_counted_row`, the Notes test rewritten; failed first on the missing `Listed`/`LISTED_ID`). STD-7.26 added; architecture (dialogs, look and feel), common-tasks, Ace3 guide and internals, CHANGELOG. Full suite 1857 tests OK (2 skipped), ruff clean, events check OK |
| LR4 | review of L7-L10, green gate, push, CI | done | (this commit) | Review of L7-L10 with the rest of the branch for consistency: `q` (one app handler, `DiscardScreen` read from the stack, no screen binding q to anything but quitting) reaches the risk popup, its box, the counted trees and the Not done / Notes popups; the toast floor counts the risk popup's box and the popups' buttons, not the counted trees; every settings save re-reads the config before writing, so `skip_risk_warning` saved by the popup is never overwritten by a stale dataclass; help, guides, README, standards (STD-7.24 to STD-7.26, STD-8.11), events.md and CHANGELOG agree, no stale "Esc/q back", `lift_toasts` or "every time you open" text left. Fix: the README FAQ's risk-warning sentence now says the **Don't show this warning again for this tool** box stops it. CI run 37733704942 failed on windows / 3.13 only: `test_undo_is_disabled_while_scanning_or_busy` (WTF Cleaner) hit `settle() timed out after 10.0s on ResultScreen; still busy: messages` after a clean, the same signature as run 37661658846 on f0fec81 (before L7), not reproducible here under load (settles in under 1 s); `settle`'s default bound is now 30 s (testing.md says why). Full suite 1863 tests OK (2 skipped), ruff clean, events check OK |
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

- L6-a: the Screenshot Organizer and the WTF Cleaner keep what Undo offers in `self.undoable`, as Interface Backup,
  Ace3 and the SV Browser already did: the scan worker finds it, and so do the run / clean / undo workers after a
  run (passed to `_job_done` / `_cleaned` / `_undone` and their failure handlers), so `_refresh_undo` reads no
  disk. `z` acts on `self.undoable` (no lookup on the UI thread), as in the other three tools; a run stopped
  partway gets its "Undo can put back" text from the worker's lookup.
- L6-b: the Screenshot Organizer's scan worker checks the destination before the Undo lookup and the scan, so the
  label reads "Checking the destination folder" first, then "Reading Screenshots folders" (`_scan_progress(0, 0,
  ...)`, the bar pulsing). An exception in the check or the lookup is a failed scan ("The scan failed: ..."),
  never a crash; before, it would have raised on the UI thread.
- L6-c: the WTF Cleaner's crash-marker read moves to its own worker (group `recovery`), not into the scan worker,
  so the "An earlier clean did not finish" notice still appears at once on open (while the scan runs) and only on
  open, never on a rescan; its answer is dropped once the review was left.
- L6-d (audit, no change needed): Interface Backup, Ace3 (review and blacklist) and the SV Browser already show
  the scan box first and look up the Undo journal and the marker in the scan worker; the Interface Backup restore
  screen loads in a worker; their `on_screen_resume` and `action_rescan` read only the config (`load_settings`,
  path joins such as `resolve_root` / `resolve_journal_dir`). The steps between the flavor pick and the review
  push touch no user folder except `ToolFlow.pick_account` (`flavor.accounts()`, one listing of the flavor's
  `WTF\Account`, on the WoW drive the flavor picker just listed): left as is. Checks on a user's action (the WTF
  Cleaner's and Interface Backup's backup-folder check before a clean, a backup or a restore) are outside L6.
- L6-e (review of L6, all six findings accepted, 1 and 3 are one bug): (1/3) the Screenshot Organizer's
  `_scan_failed` takes the worker's `undoable` and sets it, as the WTF Cleaner's does; the worker starts it at
  `None`, so a check or lookup that raised offers nothing, and a scan that raised after the lookup keeps what it
  found. (2) `ShotReviewScreen.action_rescan` is refused while `_scanning`, as in the WTF Cleaner and Interface
  Backup: one scan worker at a time, so no superseded worker can deliver `_scanned` / `_dest_refused` (a stale
  plan, a second toast). The Rescan button stays enabled, as in those tools (the action is the guard); saving a
  new destination during the check still needs `r` after it, as before L6. (5) The WTF Cleaner's `_scan_failed`
  assigns `undoable` as found, `None` included. (4) The WTF Cleaner's recovery notice is kept
  (`_pending_recovery`) until the review is the screen shown, not busy and not in its running-programs check
  (`_offer_recovery`, from `_marker_read`, `on_screen_resume` and the end of the check), never over a confirm, the
  progress popup, the help or the settings. (6) 5 tests, written first (the 4 behaviour ones failed first): an
  undoable journal enables Undo once the held worker ends and `z` opens its confirm (both tools); a failed scan
  keeps the Undo; `r r` during a held destination check runs one check and gives one toast; a failed WTF scan
  with nothing undoable drops a stale Undo; a marker read while the help is shown opens the notice on return.
  Full suite 1826 tests OK (2 skipped), ruff clean, events check OK.

- L7-a: `q` is a key method on the app (`Ka0sApp.key_q`), not an app `Binding`: Textual leaves the app's
  non-priority bindings out of the chain under a modal screen (`Screen._modal_binding_chain`), so a binding would
  not reach the popups; a priority binding would take the letter from text boxes and from the screens that bind `q`
  themselves. A key no binding took still bubbles to the app's `key_q`, popup or not, and an `Input` stops it first.
  It is shown on no footer: the menu and the reviews keep their own visible `q` (`app.quit`), the results their
  Quit button, so no footer gains a key (D17).
- L7-b: kept per-screen `q`s, all of which quit: the menu and the reviews (`app.quit`, for the footer), the result
  screens (`choose('quit')`: the Quit button's key, logged, and a review whose dry run kept staged work asks first
  through `_after_result`), the lock warning (`lock-quit`: logs the lock choice). Removed: the reviews'
  `leave('quit')` (busy was silent there; now the notice), the help's and the changelog's q-as-Back (spec D3 / D18,
  superseded by L7; Esc and h still close them; hints "Esc/h back", "Esc back").
- L7-c: staged work is the only safety kept: `ReviewBase.discard_question()` (None by default; Ace3 pending changes,
  SV Browser staged edits) is asked by `action_leave` and by `action_quit` for any screen in the stack, so `q` on
  the help, a confirm or a popup over such a review asks the same question; a second `q` while it is open does
  nothing (`_quit_asking`). Ctrl+Q (Textual's priority binding to the same `action_quit`) now asks too. Settings
  forms and the Ace3 blacklist screen have no `discard_question` and quit at once (L7 lists them as screens q quits).
- L7-d: no new event: the refusal keeps `ui.quit_refused` (its description now names q), and the quit itself is
  `session.end`, as before.
- L7-e (review of L7, six findings; 1 and 4 are one bug): (1/4) `q` over the review's own "Leave and discard ...?"
  question (`action_leave`: f, t, Esc, or a result's Quit after a dry run) pushed a second, identical question.
  Both questions are now a `DiscardScreen` (ui/dialogs, a destructive `ConfirmScreen`), and `action_quit` asks
  nothing while one is in the stack: the open question is answered first (Yes leaves as asked, then `q` quits); it
  is not turned into the quit question, so the answer always does what its title says. (2) `_quit_asking` is gone:
  the stack check above replaces it, so a question closed without `dismiss()` (pop_screen) cannot silence `q` and
  Ctrl+Q for the session; L7-c's flag is superseded. (3) tests added, written first (the 8 leave-question cases
  failed first): q over the leave question on both tools for f / t / Esc / the result's Quit (one question, no
  exit, No keeps the work, q asks again after), q after a quit question removed by pop_screen, q on a confirm over
  the warnings and over the help, on the update offer and on the Ace3 `TargetScreen` and SV Browser
  `EditValueScreen` with focus on a closed `NavSelect` (BASE and LARGE), and q on the lock warning; the walk of
  every tool's screens now runs at BASE and LARGE (two test methods). (5) the architecture paragraph is re-wrapped
  to 120 columns and names `DiscardScreen`; the `dialogs` row lists it. (6) `QuitBindingsTest` imports every
  `wowtools` module and checks the own `BINDINGS` of every screen and widget class: a `q` may only be `app.quit`,
  `choose('quit')` or `choose('lock-quit')` (it failed when the help's q-as-Back was put back); STD-8.11's Enforced
  by names it. Rejected in part: the WTF Cleaner's blacklist is the review's `b` toggle, not a screen, so there is
  nothing more to walk; the lock warning was covered by `test_suite_app` and is now in `test_quit_key` too.

- L8-a: the box reads "Don't show this warning again for this tool" and sits between the text and the buttons;
  **I understand** keeps the focus, so Enter answers as before; Enter on the box itself also presses **I
  understand** (`DontShowCheckbox`; Space ticks), so a ticked box never needs a second key. The popup dismisses
  with `ACCEPT_DONT_SHOW` and the flow saves: the screen writes nothing.
- L8-b: the popup's save is `tool_cfg.set(SECTION, skip_risk_warning, True)` then `Config.save()`, the same atomic
  write the tools' `save_settings` end with (configparser: unknown keys kept, comments dropped, as today); not
  `save_if_exists`: an explicit choice is kept even when the first-run settings were cancelled (the file is then
  created and that form is not asked again). The key is read generically by `ToolFlow` (`get_bool`, default
  false); each tool's settings dataclass also carries it, so a settings Save (or the WTF Cleaner's `b`) keeps it.
- L8-c: one registered event per tool, `<ns>.risk_warning_changed` (`shown`, `source`: `disclaimer`, `settings` or
  `wizard`), logged only when the value changes (STD-6.3; `config.changed` is logged as well). A toast after the
  tick says how to turn it back on; a failed write logs `error` (`<ns>.risk_warning`) and a warning toast, and the
  review still opens (it is accepted for the session).
- L8-d: the "Show the USE AT YOUR OWN RISK warning" box fits on all three settings forms at 120x30
  (`test_settings_forms_fit_at_base_and_keep_a_readable_width` and `test_settings_screens_open_at_the_title_and_fit`
  pass with it), so no hand edit is needed; it is the last field (ticked = shown), and the SV Browser and Ace3
  forms now set `TICKS`. `save_settings` always writes `skip_risk_warning` (false included). The guides still name
  the key for a hand edit. Turning the popup off leaves the red `⚠ USE AT YOUR OWN RISK` line and the SV Browser's
  Apply / Undo confirm warning as they are.
- L8-e (review of L8, four findings; 1 and 3 are one bug): (1/3) a failed save of the popup's box left
  `skip_risk_warning = true` in the in-memory `Config`, so a later write of the same config (a flavor pick's
  `save_if_exists`, a blacklist edit, a settings Save) saved it after the user was told it was not saved, and
  `config.changed` was logged for a change that did not happen. `_skip_risk_warning` now sets the key without
  logging, puts the previous value back (or removes the key) when `save()` raises, and logs `config.changed` only
  after the write. (2) Enter on the box skipped the popup's Enter guard: `EnterGuard.too_soon()` now holds the
  guard's check (the buttons' `action_guard_press` uses it), and `DontShowCheckbox.action_accept` calls it too, so
  Enter on the box is ignored for `CONFIRM_GUARD` after the popup opens, as on the buttons; Space still ticks it at
  once (a tick answers nothing). (4) the two internals lines over 120 columns are re-wrapped. Tests written first
  and failing first: the failed-save test asserts the key is still false in memory and on disk after a later save
  of the same config, and that no `config.changed` is logged; a new test presses Enter on the box at once (ignored)
  and after the guard (accepted). Rejected: none.

- L9-a: STD-7.24 is rewritten as the MUST (it was the SHOULD "lift toasts above an `ActionBar`" with the per-screen
  `place_toasts`), not a new STD-7.26: same subject, same ID, the SV Browser test it named still enforces part of
  it. The new test file is named in its Enforced by.
- L9-b: the anchor is the top of the screen's lowest bars, found by type (`BottomBar`, `SummaryBar`, `Footer`,
  `ActionBar`) plus the `TOAST_FLOOR` class for a row that is not a bar (the Ace3 guidance line over its action
  bar). The left pane's `#actions` button row is not a floor: it sits left of the toasts (toasts are at most half
  the width, at the right). A popup without bars (confirm, risk popup, update offer) takes the anchor of the screen
  under it, so toasts do not jump when it opens; a popup's own buttons may still sit under a tall stack at 120x30,
  as with Textual's default.
- L9-c: the tip joins the stack as its lowest box: it sits on the floor and the toasts start one row above it
  (`GAP`, the row Textual leaves between toasts). It keeps its own `toast-tip` layer (`TIP_LAYER_CSS`, on every
  screen through `Ka0sApp.CSS`), so it never takes room from the layout; the shared `TipRack` gets an explicit height
  equal to its tip's, because its `auto` height was measured a row short at 120x30.
- L9-d: placement runs from the app, not the screens: `screen_change_signal` (every push, pop and switch) and each
  shown screen's layout refresh (a bar that wraps, a tip shown or hidden, a resize, a toast mounted), subscribed
  once per screen with the app as subscriber (running even before the screen has started). A margin is set only
  when it changes, so a placement never loops. When three toasts and the tip are taller than the space above the
  bars (120x30 on the Ace3 review), Textual's rack scrolls the oldest toast's top out of sight, as before.
- L9-e (review of the L9 commit, folded into it): (1) accepted, and L9-b's "a popup's own buttons may still sit
  under a tall stack" is withdrawn: toasts covered Yes/No, OK/Cancel and the prompt field on the popups. A popup's
  floor is now the higher of the bars under it and the top of its own highest control (`CONTROL_SELECTOR`:
  `Button`, `Input`, `TextArea`, `Checkbox`, `Switch`, `Select`, `RadioSet`, `OptionList`) that reaches into the
  toasts' column (the right 60 columns, at most half the width, left of the rack's 2-column gutter); only the shown
  popup counts (one under it cannot be pressed). Detail trees are not controls: they are read, and a popup tree as
  a floor would leave the stack no room. On the tallest popups at 120x30 (Quick actions, Search) that leaves 7-8
  rows, so the rack scrolls the older toasts out of sight and the newest stays whole (L9-d). (2) accepted:
  `PopupStackTest` pushes every other popup over the menu at 120x30 and 160x45 (the generic and each tool's
  progress screen, the text prompt, Ace3 Name / Target / Quick actions, SV Rename key / Edit value / Search /
  search progress, Notes, the confirm, the unfinished-run and both recovery warnings, the lock, the update offer
  and its progress) and the discard question over a prompt; `assert_stack` now also checks, on any popup, that no
  toast covers one of its controls (found by type in the test) and that the stack starts above the highest one in
  the toasts' column. Written first and failing first (the risk popup's box, the prompt's field). (3) and (5), one
  finding: the three `STD-7.26` citations read `STD-7.24`. (4) kept, explained: the anchor is per screen by the
  spec's own words ("just above the screen's bottom bars and action bars"), the same on every screen with the same
  bars; a popup's anchor differs because what it must not cover differs (now its controls too). The test pins
  one right edge on every screen of a size and the bottom of each stack against that screen's bars and controls.
  To confirm with the user: whether "the same anchor" meant one fixed height instead.

- L10-a: the counted row always starts closed, however short the list (the spec's "one collapsed, counted tree
  row"); once it is opened, its groups are open too when the whole list fits in `DETAIL_ROWS` lines (the
  `detail_tree` rule), else closed (`x` opens them). Alerts of a fixed number (WoW running, a locker, hidden ticked
  items, the zip turned off, the SV Browser's disclaimer and array shift) stay red lines of the body: they do not
  grow, and hiding "WoW is running" behind a row would weaken it.
- L10-b: the audit of every `ConfirmScreen`, `InfoScreen`, `ChoiceScreen` and tool popup: only the Ace3 Apply / Dry
  run warnings and the Ace3 Notes are lists that grow with the selection. The rest are bounded or already scroll:
  the WTF Cleaner confirm (one line per flavor, and fixed alerts), the Screenshot Organizer and Interface Backup
  confirms (fixed alerts; the restore alerts are counts, one per kind), the SV Browser Apply confirm (its files are
  already a `detail_tree`, which scrolls; its alerts are fixed), the Ace3 Leftovers confirm (a `detail_tree`), the
  Ace3 Delete / Assign target popup (its body is `.popup-body`, `max-height: 40vh`, scrolling), the recovery,
  lock and update popups (fixed text). Result screens are full screens whose detail table scrolls under a fixed
  button row. The Ace3 "Not done (n)" refusals are a toast, not a popup, already cut at 8 lines plus "… and N
  more"; left as is.
- L10-c: `Listed` lives in `core/text.py` (UI-free) so a tool's report and ops modules can build the entries
  without importing `ui/`; the tree is in `ui/dialogs.py` next to `detail_tree`. The Ace3 "kept" note no longer
  puts a count in its sentence ("Characters that have a folder in WTF were kept."; the item says "ElvUI: 2
  characters"), so it groups across addons.
- L10-d: the warning sentences no longer start with the addon (it is the item): 'The "Default" profile will be
  deleted.', '"Healer" does not exist yet; ...', "LibDualSpec switches ...".
- L10-e: review of L10 (six findings, all minor). (1) fixed, superseding L10-b's last sentence: the Ace3 "Not
  done" refusals are now an `InfoScreen("Not done")` with a `CountedTree` ("⚠ N databases not changed", grouped
  by reason, then where, then the database), shown before the Notes (which follow when it closes), no longer a
  toast cut at 8 lines; `_lines` is gone. To confirm with the user: a refusal now needs OK (a popup, not a
  toast). (2) and (6), one finding, fixed, amending L10-a: `CountedTree(open_short=)` opens the row when the whole
  list fits in `DETAIL_ROWS`; `InfoScreen` passes it when the list is its only content (no body, no groups), so
  one or two notes show at once; a confirm's warnings still start closed. `alert=False` drops the ⚠ and the red for
  a neutral list: the Notes. (3) rejected: 100x20 is below the 80x24 floor of STD-7.23 (designed for 120x30,
  grows at 160x45); at 80x24 Yes stays visible, and the box scrolling below that is the documented behaviour
  (`POPUP_TREE_CSS` comment). (4) fixed: `ops.item_of(state, states)` names the database when another one of
  `states` is in the same file ("ElvUI (ElvPrivateDB)") and the character for a character's file ("PerChar
  [Realm1/Kaelys]"); `ops.listed` takes `states` (the staging's, or the confirm's changed ones); `CountedTree`
  drops exact repeats (`dict.fromkeys`), as the old Notes did. (5) fixed: architecture's dialogs row names
  `detail_hint(groups, listed=())` and the new `InfoScreen` / `CountedTree` parameters. Tests first (failed first):
  `test_an_entry_repeated_exactly_is_listed_once`, `test_a_neutral_list_has_no_warning_mark`,
  `test_open_short_opens_the_row_only_when_the_whole_list_fits`,
  `test_a_short_list_that_is_the_whole_popup_shows_at_once`,
  `test_listed_items_name_the_database_and_the_character`, `test_refusals_open_a_popup_listing_every_one`.
