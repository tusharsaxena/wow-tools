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
| K4 | docs | done | (this commit) | WTF guide gains The blacklist (`b`, greyed/untickable rows, hand-editing `[wtf_cleaner] blacklist`, `*`/bare-name wildcard, FAQ) and Scan warnings sections plus `b`/`!` key rows, the four other guides replace "plus scan warnings"/"the log lists" with the `⚠ N … (!)` button and warnings view and a `!` key row, README keys/settings/FAQ, CHANGELOG 0.1.0 (app + WTF + Ace3 bullets), architecture (core `blacklist` row, `warnings_view` row, `BlacklistAction` in the review row, WTF config/data flow/review), CLAUDE.md look-and-feel rule, adding-a-tool, events.md regenerated (unchanged), pinned by test_docs; full suite 1706 OK (2 skipped), +1 test |
| KR | review, fixes, push | todo | | review fixes: WTF review keeps the opened rows and the highlighted row across the rebuild after b (b again on a file row takes the addon back off), the settings-form blacklist test drives `CleanerSettingsScreen`, the warnings view's busy guard tested on every review plus the real running-programs check; full suite 1709 OK (2 skipped), +3 tests |

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
- **K4** New `tests/test_docs.py::test_warnings_view_and_blacklist_key_are_documented` pins the docs (no guide says
  "see the log)", every guide has a `!` key row and names the warnings view, the WTF guide's blacklist section, ini
  example and wildcard, the changelog/README/architecture/CLAUDE.md needles). CLAUDE.md already named the modules
  (K1, K2); K4 added a look-and-feel sentence (warnings via `SummaryBar`/`WarningsHost`, never "(see the log)"; the
  shared `b` for a tool with a blacklist). Also fixed the WTF guide's stale rule key row (`1` `2` `3` `4` → `1` to
  `5`). `docs/events.md` regenerated: no change (K3 already did it). The Ace3 guide's `b` text stays (behaviour
  unchanged); the README's `b` row names only the two tools that keep a blacklist (spec B3).
- **K4** Interface Backup's guide no longer says the log lists the scan warnings (the tree lists all of them; only
  the log samples 20 per folder); its new "### Scan warnings" sits after the review's key table and covers the
  restore screen's button too.
- **KR review**: 3 findings, 3 fixed, 0 rejected. (1) The WTF review's rebuild after `b` collapsed the addon and
  left the cursor on a line number: `blacklist_changed()` now records which rows are open and the highlighted row by
  identity (`_row_ident`: a file's path, an addon's flavor + group key, a group's names), and that rebuild puts them
  back (`_restore_view`); other rebuilds (criteria, max age, the `/` filter) still lay the tree out fresh, so a
  filter's opened addons are not overridden. (2) `test_settings_form_keeps_the_blacklist` now saves through
  `CleanerSettingsScreen` (checked to fail if `save()` drops the blacklist). (3) New tests in
  `tests/test_warnings_view.py`: `!` and the button do nothing on every review while `_scanning`, `_checking` or
  `app.busy`, and during the WTF Cleaner's real running-programs check (checked to fail without `warnings_blocked()`).
