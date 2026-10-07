# Saved Variables Browser feedback round 1 — status ledger

Plan: `2026-10-07-sv-browser-feedback-1.md`. Spec: `../specs/2026-10-06-sv-browser-design.md` Addendum B.
Branch: `feat/sv-browser`. Resume at the first task not marked `done`. Update and commit after every task; push
after the round. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| F0 | spec addendum B, plan, ledger | done | (this commit) | user feedback 2026-10-07 |
| F1 | header + risk banner | done | (this commit) | `Ka0sApp.format_title` paints `Ka0s WoW Tools` gold (`TITLE_GOLD` #E6B422) and ` — <sub-title>` near-white (`TITLE_TEXT` #F0F0F0), all bold; shared `RiskBanner`/`RISK_TEXT` in `ui/widgets.py` tops the left pane of the SV Browser, WTF Cleaner and Ace3 reviews and IB's restore screen; full suite 1651 OK (2 skipped), +4 tests |
| F2 | filter on submit (all tools) | done | (this commit) | shared `FilterBar` (box + non-focusable compact **Filter** `(⏎)` button, navigate) replaces the bare `FilterInput` on all 7 tree screens; typing only edits the box, Enter or the button applies (`FilterBox.submit_filter`, one rebuild, tree focused after it), Esc clears box and filter; `FILTER_HINT` "/ filter, then Filter", tool and suite help updated; full suite 1655 OK (2 skipped), +4 tests |
| F3 | find-only search, bulk edit/rename into staging | todo | | |
| F4 | docs, review, push | todo | | |
| FB1 | push round | todo | | |

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
