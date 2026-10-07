# Saved Variables Browser feedback round 1 — status ledger

Plan: `2026-10-07-sv-browser-feedback-1.md`. Spec: `../specs/2026-10-06-sv-browser-design.md` Addendum B.
Branch: `feat/sv-browser`. Resume at the first task not marked `done`. Update and commit after every task; push
after the round. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| F0 | spec addendum B, plan, ledger | done | (this commit) | user feedback 2026-10-07 |
| F1 | header + risk banner | done | (this commit) | `Ka0sApp.format_title` paints `Ka0s WoW Tools` gold (`TITLE_GOLD` #E6B422) and ` — <sub-title>` near-white (`TITLE_TEXT` #F0F0F0), all bold; shared `RiskBanner`/`RISK_TEXT` in `ui/widgets.py` tops the left pane of the SV Browser, WTF Cleaner and Ace3 reviews and IB's restore screen; full suite 1651 OK (2 skipped), +4 tests |
| F2 | filter on submit (all tools) | todo | | |
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
