# Feedback round 2: status

Branch `feat/config-editor-feedback-1`. Plan `2026-11-04-feedback-round-2.md`. Resume at the first row not `done`.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| G0 | re-sort the 250 "other" CVars (workflow pass, data handed to G2) | todo | | |
| G1 | shared column and count helpers, two standards | done | (this commit) | 16 new tests in tests/test_ui_columns.py + test_structure::test_tree_label_helpers_live_in_ui; CE ops column tests on the shared fit. Gate: run_tests --all 2365 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK |
| G2 | Config Editor R1, R2, R3, R5, R6 | todo | | |
| G3 | WTF Cleaner counts + columns | todo | | |
| G4 | Screenshot Organizer counts + columns | todo | | |
| G5 | Interface Backup counts + columns | todo | | |
| G6 | Ace3 Profile Manager counts + columns | todo | | |
| G7 | Saved Variables Browser counts + columns | todo | | |
| G8 | Config Copier counts + columns | todo | | |
| G9 | Macro Editor counts + columns | todo | | |
| G10 | CHANGELOG, whole-branch review, push, CI | todo | | |

## Decisions taken during the build

- G1a: the whole of R4's helper sits in `wowtools/ui/columns.py` as the plan names it (pure, Rich only, no Textual),
  so a tool's `report.py` (STD-1.7: no `wowtools.ui` import) keeps only its cells and plain constants and the
  screen fits and draws; the Config Editor's layout is `review_screen.CVAR_COLUMNS` built from report's
  `COLUMN_CAPS` / `COLUMN_MINIMUMS` / `DROP_ORDER` (now `(2, 4, 1, 3)`, the leading `None` step is the helper's own).
- G1b: the layout is a `ColumnLayout(caps, minimums, shrink, drop)` NamedTuple: shrink stages of free-text columns,
  a drop order, and past it the helper always falls back to the first column (the name) alone cut to the room, so
  a tool whose drop order leaves status columns still fits. The CE behaviour (CF2, FB2r) is unchanged, pinned by
  its existing tests.
- G1c: the shared middle cut is `cut_middle` (cell-aware), not `cut_name`: the Macro Editor's `ops.cut_name` (a
  macro name cut to the game's limit) is a different thing and keeps its name; the structure test pins both.
- G1d: the count helper is its own module, `wowtools/ui/counts.py` (`count_text`, `with_count`, `COUNT_STYLE` dim,
  `COUNT_GAP` two spaces: the WTF Cleaner's look). The WTF Cleaner's group label already moves onto `with_count`
  here, so there is never a second copy; G3 still owns its counts and columns.
- G1e: the two rules are STD-7.27 (leaf counts) and STD-7.28 (node columns), enforced now by the helper and
  structure tests and, as G2-G9 land, by each tool's app test (the rule text names them).
