# Warnings view and the blacklist key — status ledger

Plan: `2026-10-07-warnings-and-blacklist.md`. Spec: `../specs/2026-10-07-warnings-and-blacklist-design.md`.
Branch: `feat/warnings-blacklist`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| K0 | spec, plan, ledger | done | (this commit) | user feedback 2026-10-07 |
| K1 | warnings view, all tools | done | (this commit) | Shared `ui/warnings_view.py` (`SummaryBar` bottom line + compact Warnings button "⚠ N … (!)", `WarningsHost`, `WarningsScreen` grouped by flavor with filter/x/c/Back(Esc)/detail line) adopted by the WTF Cleaner, Screenshot Organizer, Interface Backup review + restore, Ace3 and SV Browser reviews, every "(see the log)/(see the tree)" count gone; full suite 1689 OK (2 skipped), +13 tests |
| K2 | blacklist helpers to core + shared b | todo | | |
| K3 | WTF Cleaner blacklist | todo | | |
| K4 | docs | todo | | |
| KR | review, fixes, push | todo | | |

## Decisions taken during the build
- **K1** Key `!` (`exclamation_mark`): free on every review and the IB restore screen (b, h, s, digits, letters all taken
  somewhere). It sits on a compact `action_button("Warnings", "navigate", "!")` at the right end of the bottom line
  (`SummaryBar`, which now wraps `#summary`), not focusable, shown only while there are warnings; the binding is
  `show=False`, so D17 holds (the button carries the key, the footer never lists it). Its `label_text` stays
  "Warnings" (help names **Warnings**); the visible label is "⚠ N scan warnings (!)".
- **K1** The warning count left the summary text in every tool (WTF, SO, IB, Ace3 `selection_text` lost its
  `warnings` argument, SVB): the button is the count. Tests that pinned the old text (test_ace_report,
  test_interface_backup_app scan-warnings node, the Ace3 look-and-feel hint test) now check the button.
- **K1** Screenshot Organizer `Plan.warnings` holds `PlanWarning(flavor, path, message)` instead of "path: error"
  strings (a Windows path has a colon: where and what could not be split back). Its tree's flavor row says
  "could not be read (see Warnings)".
- **K1** Paths in the view are relative to the flavor folder (`where_text`; the group names the flavor); Interface
  Backup's where is the part (`Interface`/`WTF`), its message already names the path. A detail line in the left pane
  shows the highlighted warning whole (the tree cuts long paths at 80 columns); the view opens on the first warning.
- **K1** What counts: WTF `ScanWarning`s; SO unreadable folders; IB part scan errors (review: every flavor; restore
  screen: its own scan of the flavor); Ace3 flavor scan warnings (also still the tree's group); SVB flavor scan
  warnings plus files found unreadable (opened docs and the last search), deduplicated. "Not scanned" flavors stay
  on the summary line (they are not scan warnings). IB's tree node text "(the log lists up to 20 per folder)" kept.
- **K1** The view does not open while the screen scans, runs or does its running-programs check, nor from under a
  popup; opening logs `ui.selection` (control `warnings`): no new event, docs/events.md unchanged.
