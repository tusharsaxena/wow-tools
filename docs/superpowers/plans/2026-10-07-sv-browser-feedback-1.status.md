# Saved Variables Browser feedback round 1 — status ledger

Plan: `2026-10-07-sv-browser-feedback-1.md`. Spec: `../specs/2026-10-06-sv-browser-design.md` Addendum B.
Branch: `feat/sv-browser`. Resume at the first task not marked `done`. Update and commit after every task; push
after the round. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| F0 | spec addendum B, plan, ledger | done | (this commit) | user feedback 2026-10-07 |
| F1 | header + risk banner | done | (this commit) | `Ka0sApp.format_title` paints `Ka0s WoW Tools` gold (`TITLE_GOLD` #E6B422) and ` — <sub-title>` near-white (`TITLE_TEXT` #F0F0F0), all bold; shared `RiskBanner`/`RISK_TEXT` in `ui/widgets.py` tops the left pane of the SV Browser, WTF Cleaner and Ace3 reviews and IB's restore screen; full suite 1651 OK (2 skipped), +4 tests |
| F2 | filter on submit (all tools) | done | (this commit) | shared `FilterBar` (box + non-focusable compact **Filter** `(⏎)` button, navigate) replaces the bare `FilterInput` on all 7 tree screens; typing only edits the box, Enter or the button applies (`FilterBox.submit_filter`, one rebuild, tree focused after it), Esc clears box and filter; `FILTER_HINT` "/ filter, then Filter", tool and suite help updated; full suite 1655 OK (2 skipped), +4 tests |
| F3 | find-only search, bulk edit/rename into staging | done | (this commit) | Search popup finds only (no Replace with / New value / Find only; a blank row between the key and value pairs), `SearchSpec.replacement` and `Hit.new`/`new_bytes` removed (`search.replace_matched` added); new UI-free `bulk.py` stages one edit per ticked (else highlighted) hit via new `Staging.stage_hit_value` / `stage_hit_rename` / `unstage_hit`, leaving out already-staged, under-delete, changed-bytes and D5-refused hits with a notice by reason (`svb.bulk_staged`); Results-view Edit value / Rename key open the normal popups titled with the count (matched-text vs whole value after a Contains search), marks show on hits and in Browse; `Staging.plans()` is staged edits only, the pending line reads `Staged: N edits in F files` + `Ticked: M results`; help, architecture, Addendum A updated; full suite 1667 OK (2 skipped), +12 tests (net) |
| F4 | docs, review, push | done | (this commit) | `docs/sv-browser.md` rewritten for D37-D39 (find-only `## Search`, new `## Editing the results in bulk` with the matched-text/whole-value choice and left-out reasons, ticks only select, Apply/Rescan/leave/Undo/Dry run no longer mention ticks, filter on Enter/**Filter**, keys, FAQ, troubleshooting), the other four guides and README describe the filter on submit and the `⚠ USE AT YOUR OWN RISK` line, architecture gains a title bar/banner/filter paragraph and per-screen `RiskBanner` mentions, CLAUDE.md look-and-feel line names `FilterBar`/`RiskBanner`, CHANGELOG 0.1.0 updated (no new version), help texts verified; full suite 1668 OK (2 skipped), +1 test |
| FB1 | push round | done (pushed; awaiting merge go-ahead) | 497d366 | review fixes: Results Unstage of a rename reads its table in a worker and shows the real reason; `BYTES_DIFFER` (search again, then rescan) for hits differing from the loaded document or staged edits; banner two spaces after ⚠; regression tests for the D29 escapes case and the loaded-document hashes; full suite 1672 OK (2 skipped) |

## Decisions taken during the build
- **F1** Header: Textual's `Header` renders title and sub-title in one `HeaderTitle` via `App.format_title`, so
  `Ka0sApp` overrides that (no CSS per part needed); the ` — ` separator between title and sub-title stays, now
  near-white instead of dim. `Ka0sApp.TITLE` is `Ka0s WoW Tools` (was `Ka0s · WoW Tools`); the one assertion on the
  old string (`tests/test_ui_base.py`) was updated. The menu's shield-art name line (`BANNER_NAME`, `K a 0 s · W o W
  T o o l s`) is not the title bar and was left as is.
- **F1** `RiskBanner` lives in `ui/widgets.py` (a non-focusable `Static`, `color: $error`, bold, `margin-top: 1`),
  first child of `#filters`; the SV Browser's `RISK_BANNER` constant and `#risk` CSS are gone (its test now queries
  `RiskBanner`). `tests/test_structure.py` pins the banner to exactly the four screen classes. At 80x24 the WTF
  Cleaner and Ace3 left panes lose their NavHint rows below the buttons (clipped, not focusable); allowed by the
  80x24 rule (Tab still reaches every control).
- **F1** Docs touched now (rest in F4): `docs/architecture.md` (`base`, `widgets` rows, SV left pane), spec Addendum A
  D25 banner text marked replaced by D37.
- **F2** Filter row: the input and the **Filter** button share one row (`FilterBar`, a `Horizontal` in `ui/tree_filter.py`);
  the button is built by `action_button("Filter", "navigate", "enter", compact=True)` and then made non-focusable
  (`can_focus = False`), so the one-focusable-control-per-row rule holds without a new row (the left panes have no
  spare rows at 80x24) and Tab/↑↓ never stop on it; the mouse clicks it, the keyboard uses Enter in the box. Its key
  shows as `(⏎)` (`key_text("enter")`, as the footer writes it), so it does not clash with the hints' `Enter/Space
  press`. `tests/fixtures.assert_keys_on_buttons` accepts its key as the filter box's own Enter binding (not a screen
  binding).
- **F2** No timer to remove: the "debounced" rebuild was `ScheduledRebuild` (one `call_after_refresh`); it stays, so a
  submit still shows "Updating the list…" and folds into one rebuild. Because a loading tree cannot take focus,
  `_apply_filter` focuses the tree again after the rebuild. Submitting the applied text again rebuilds nothing.
  `clear_filter` (Esc) now drops the applied filter even when the box held unsubmitted text.
- **F2** Tests: `tests.fixtures.submit_filter(screen, text)` replaces the `filter_input().value = ...` pattern in the
  tool tests; typing tests press Enter where they expect a filter. New: typing alone does not filter, the button
  applies, the button sits beside the box without focus (toy screen), and one look-and-feel test across all tree
  screens (Enter and button, empty submit shows all). Docs touched now: `docs/architecture.md` (`tree_filter` row,
  `FilterBar` in the left panes), `docs/adding-a-tool.md`, spec Addendum A left pane; the user guides are F4.
- **F3** `SearchSpec.replacement`, `SearchSpec.replaces`, `Hit.new` / `Hit.new_bytes`, `FieldEdit.hit`, `Plan.dropped` /
  `Plan.hits`, `DroppedHit`, `ops.HAS_STAGED_EDIT` / `DUPLICATE_HIT` / `UNCHANGED`, `report.dropped_text`, the review's
  `_left_out` / `_recount` / `LEFT_OUT_MARK` / `NO_TICKS_FIND_ONLY` / `replaces`, and the popup's `FIND_ONLY` /
  `NEW_TYPES` are removed (dead under D38/D39). `Staging.plans()` takes no hits; `report.summary_rows(result)` lost
  its `plan` argument. The left-out reasons are full sentences (`ops.ALREADY_STAGED`, `UNDER_DELETE`,
  `FILE_CHANGED`, plus D5's `TOP_LEVEL`, `ARRAY_RENAME`, the duplicate-key message) shown as `N · reason` lines.
- **F3** Bulk logic lives in a new UI-free `tools/sv_browser/bulk.py` (not `ops.py`: the rename's duplicate check needs
  each key's table, and the table lookup reuses `compile.FieldIndex` / `locate`, while `compile` imports `ops`).
  `read_tables` runs in a `start_run(writes=False)` worker with the search progress popup (a "Reading" stage), since
  a rename may parse big files; value edits read no file and stage at once. Unstage of a renamed hit reads its one
  table on the UI thread (the duplicate check). A hit is left out with `FILE_CHANGED` when a file it belongs to was
  opened in Browse from other bytes (`shas` of the loaded documents) or has staged edits from other bytes.
- **F3** New event `svb.bulk_staged` (info; staged, unchanged, left_out, reasons); `docs/events.md` regenerated. A hit
  whose value already is the new value (or rename to its own key) stages nothing and is counted as "already had
  it", as D29 does for a single edit. Delete key is disabled in Results.
- **F3** Ticks only select: `pending` is the staged count, so leaving or a new search with only ticks never asks (the
  new-search confirm is gone), and Apply / Dry run are disabled until something is staged. The bulk Edit value popup
  starts from the hits' value when they all share one (else empty, String); the bulk Rename popup starts from the
  key when all hits share it. With nothing ticked, the highlighted hit is the target and the popups keep their
  single titles ("Edit value", with its Now line).
- **F3** Tests: new `tests/test_sv_browser_bulk.py`; `test_sv_browser_ops` `PlanTest` replaced by `HitStagingTest` and a
  staged-only `PlanTest`; `test_sv_browser_search_ui` `StagedEditWinsTest` / find-only tests replaced by
  `BulkEditTest` (whole, matched text, highlighted hit, Browse marks, left out, rename, delete stays single-key) and a
  `SearchTestBase.bulk_value` helper; `test_sv_browser_run_ui.search_friz` now stages through a bulk edit, plus two
  end-to-end Apply tests (matched text on one ticked hit; bulk rename) checking the exact bytes, snapshot, originals
  zip and journal. The look-and-feel `PREPARE` helper (`stage_sv_edit`) already stages, so it needed no change.
  Docs touched now: `docs/architecture.md` (SV Browser data flow, modules, screens), spec Addendum A D24/D29/D31/D32/
  D36 marked replaced by D38/D39; the user guide is F4.
- **F4** Docs only; no event registry changed (events.md untouched). `tests/test_docs.py`: the SV guide test now
  requires `## Search`, `## Editing the results in bulk`, "Replace only the matched text" and the banner text, and
  forbids `## Search and replace`, Replace with, Find only, New value; new `test_guides_filter_on_submit_and_risk_banner`
  (every guide names **Filter** and drops "keeps the filter", the four destructive guides name the banner, README,
  CHANGELOG and CLAUDE.md checks). The push itself is FB1 (not done here).
- **F4** Kept the spec D1 menu text "Browse and edit every SavedVariables file, with bulk find and replace." (tool
  registry and `test_sv_browser_skeleton`): it still describes find-then-bulk-edit, and D1 is not named by Addendum B;
  the README row was reworded to "find values and edit the results in bulk". The shared `ScheduledRebuild` keeps its
  "debounced rebuild" wording in code and `docs/adding-a-tool.md` (it is one rebuild per submit now, per F2).
- **F4** `ruff check .` panicked on a stale cache ("wrong package cache for file", ruff 0.16.10); `ruff check
  --no-cache .` passes.
- **FB1 review**: 6 findings, 6 fixed, 0 rejected (findings 1 and 3 were the same defect, fixed once): (1/3) Results
  Unstage on a renamed hit no longer calls `read_tables` on the event loop: `_read_tables_then(hits, then, name=,
  title=)` is shared with the bulk rename and runs it through `start_run(writes=False)` under the progress popup
  ("Reading the table of the key to unstage"); `Staging.unstage_hit` now takes `Table | str | None` and a str is the
  refusal (e.g. `FILE_CHANGED`), never `NOT_LOADED`. (2) `_hit_refused` returns the new `BYTES_DIFFER` ("...search
  again, and rescan if that does not clear it") when the hit's bytes differ from the loaded document or the staged
  edits; `FILE_CHANGED` ("...since the search; search again") is now only `read_tables`' reason, where a new search
  does clear it. (4) `RISK_TEXT` has two spaces after U+26A0 (a terminal drawing it as a two-cell emoji covers the
  first); spec D37 and the look-and-feel test say so; the guides' inline mentions keep one space (prose). (5) New
  `test_a_hit_written_with_other_escapes_but_the_same_value_stages_nothing` (Details, matched b -> b) fails with the
  bytes-only check. (6) New UI test opens ElvUI in Browse, changes it on disk, searches and bulk-edits: its hits are
  left out with `BYTES_DIFFER`; fails when `_loaded_shas` returns {}. Each new test was checked against the mutant or
  pre-fix code.
