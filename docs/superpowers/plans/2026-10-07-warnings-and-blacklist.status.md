# Warnings view and the blacklist key — status ledger

Plan: `2026-10-07-warnings-and-blacklist.md`. Spec: `../specs/2026-10-07-warnings-and-blacklist-design.md`.
Branch: `feat/warnings-blacklist`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| K0 | spec, plan, ledger | done | (this commit) | user feedback 2026-10-07 |
| K1 | warnings view, all tools | done | (this commit) | Shared `ui/warnings_view.py` (`SummaryBar` bottom line + compact Warnings button "⚠ N … (!)", `WarningsHost`, `WarningsScreen` grouped by flavor with filter/x/c/Back(Esc)/detail line) adopted by the WTF Cleaner, Screenshot Organizer, Interface Backup review + restore, Ace3 and SV Browser reviews, every "(see the log)/(see the tree)" count gone; full suite 1689 OK (2 skipped), +13 tests |
| K2 | blacklist helpers to core + shared b | done | (this commit) | Pair helpers moved to UI-free `core/blacklist.py` (Ace3 settings/app/blacklist screen/review import them), shared `BlacklistAction` + `BLACKLIST_BINDING` + `blacklist_toast` in `ui/review.py` adopted by the Ace3 review (its `b`, events, `u`, blacklist screen unchanged), single definitions pinned in test_structure; full suite 1693 OK (2 skipped), +4 tests |
| K3 | WTF Cleaner blacklist | done | (this commit) | `[wtf_cleaner] blacklist` (core pair format, load/save, kept by the settings form, no new form row), `evaluate(blacklist=)` holds blacklisted groups in `Proposal.blacklisted` (out of items/totals/by_reason/criterion counts/summary/confirm/clean/dry run), review shows them greyed + tagged and untickable, shared `b` (`BlacklistAction`) on addon/file rows per flavor, `blacklist.changed` event, help section, hint names `b`; full suite 1705 OK (2 skipped), +12 tests |
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
- **K2** `core/blacklist.py` holds `WILDCARD`, `Pair`, `unique_pairs`, `parse_blacklist`, `format_blacklist`,
  `is_blacklisted`, `toggle_pair` (and `_pair_order`); Ace3's `settings.py` imports only what it uses (no re-export).
  No `patch()` target named the moved helpers; the only test change is `tests/test_ace_settings.py` calling them as
  `bl.<name>` (`from wowtools.core import blacklist as bl`) instead of `s.<name>`, assertions identical.
- **K2** `BlacklistAction` (ui/review.py) is a plain mixin (Textual collects `BINDINGS` only from DOMNode classes), so
  a screen binds `BLACKLIST_BINDING` (`b`, `show=False`, as Ace3 had it; a screen that wants `b` in the footer binds
  its own shown Binding with `BLACKLIST_KEY`). Hooks: `blacklist_ready()` (Ace3: idle and scanned),
  `blacklist_target(node)`, `toggle_blacklist(flavor, addon) -> listed` (save + the tool's own event),
  `blacklist_changed()` (default a scheduled rebuild; Ace3 drops locked changes first). The toast
  "<Addon> (<Flavor name>) is now / no longer on the blacklist." and the no-target notice `BLACKLIST_NO_TARGET`
  ("Highlight an addon (or something inside one) first.", Ace3's existing text, also used by its `u`) are shared.
- **K3** `evaluate()` keeps the blacklisted groups (what the criteria would propose of them) in a new
  `Proposal.blacklisted` list, each `ProposalItem.blacklisted=True`; `Proposal.items` (and so totals, `by_reason`,
  `criterion_counts(blacklist=)`, `proposal.item` events, the selection, confirm, clean and dry run) never hold them.
  `proposal.built` gained a `blacklisted` count. A blacklisted addon that no criterion matches is not shown (nothing
  to clean there); taking it off then is a hand edit of `[wtf_cleaner] blacklist`.
- **K3** Tree: a blacklisted item/file row has no tick keys (`_paths` returns none: Space/a/n skip it) and no tick
  mark; greyed with a "blacklisted" tag; group rows count and mark only the cleanable items. An unticked file keeps
  its `unchecked` entry across a blacklist round trip. The flavor of a row comes from `_item_flavor` (id(item) ->
  folder, built per rebuild), so All flavors toggles per flavor.
- **K3** `b` is `BLACKLIST_BINDING` (`show=False`, as on the Ace3 review): a shown footer key wrapped the WTF footer
  to two rows at 120x30 (test_look_and_feel footer/brand-bar tests). The left-pane hint names "b blacklist" instead
  (it still fits at 120x30 and 80x24), and the help has a "## Blacklist" section. `toggle_blacklist` reloads the
  settings, uses the shared `toggle_pair` with every flavor folder of the install (a wildcard taken off in one
  flavor becomes explicit pairs for the others), saves (`source="review"`) and logs the new WTF event
  `blacklist.changed` (the cleaner's unprefixed naming); `blacklist_changed()` refreshes the criterion counts, then
  rebuilds. docs/events.md regenerated.
