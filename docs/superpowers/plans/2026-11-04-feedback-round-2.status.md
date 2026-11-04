# Feedback round 2: status

Branch `feat/config-editor-feedback-1`. Plan `2026-11-04-feedback-round-2.md`. Resume at the first row not `done`.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| G0 | re-sort the 250 "other" CVars (workflow pass, data handed to G2) | done | (this commit) | the 250: debug 92, game state 82, system 43, graphics 20, interface 9, network 3, other 1 (`repositionfrequency`); written into cvar_categories.json by G2 |
| G1 | shared column and count helpers, two standards | done | (this commit) | 16 new tests in tests/test_ui_columns.py + test_structure::test_tree_label_helpers_live_in_ui; CE ops column tests on the shared fit. Gate: run_tests --all 2365 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK |
| G2 | Config Editor R1, R2, R3, R5, R6 | done | (this commit) | 6 new tests (5 in test_config_editor_app: node counts, flavor counts, dropdown counts, not-set colour, help colours; test_kb::test_other_is_kept_to_a_handful), group lists / help styles / tree labels updated in test_config_editor_app, test_config_editor_ops, test_kb. Stale screenshots: config-editor/browse.png, recommend.png. Gate: run_tests --all 2371 tests, WSL OK (10 skipped) every run; Windows OK (86 skipped) on the --windows rerun, its --all runs each had one environmental error in an untouched test (WinError 10055 socket-buffer twice, as in T5/T6; one test_suite lock-timing KeyError under the doubled load); ruff clean; gen_event_docs --check OK. Review fixes (fix: G2 review fixes): kb/README.md cvars section lists the eleven groups; config-editor.md tree-count wording matches G2e (0 items included); docs only, gate run_tests --all 2371 WSL OK / Windows OK, ruff clean, gen_event_docs OK |
| G3 | WTF Cleaner counts + columns | done | (this commit) | 7 new tests (test_ui_columns::test_a_rich_cell_keeps_its_own_colours; 6 in test_wtf_app NodeCountsAndColumnsTest: group counts, counts follow the search, blacklisted not counted, aligned addon and file columns, long name cut to the pane at 120x30 and 80x24, flavor counts); no existing test changed. Stale screenshots: wtf-cleaner/review.png (also in README.md). Review fixes (fix: G3 review fixes, G3h/G3i): +1 test (test_a_group_of_blacklisted_rows_only_counts_zero), test_a_long_name_is_cut_to_fit_the_pane checks group rows too, test_flavor_with_nothing_to_clean_says_so changed (flavor `0 items`). Gate after the fixes: run_tests --all 2379 tests, WSL OK, Windows OK (86 skipped); ruff clean; gen_event_docs --check OK. Gate before the fixes: run_tests --all 2378 tests, WSL OK (10 skipped), Windows OK (86 skipped); ruff clean; gen_event_docs --check OK |
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
- G2a: the console category `debug` now maps to the debug group in `core.kb.category_group` (only a CVar a newer
  dump adds and `cvar_categories.json` doesn't list reaches the rules); `gm`, `console` and the rest stay "other".
- G2b: the three new groups' colours take hues the first eight left free: game state teal `#4FD6BE`, debug orange
  `#FF9E64`, system periwinkle `#9D9DFF` (each over 8:1 on the background).
- G2c: R3 is `ui/theme.NOT_SET_COLOUR` `#5F6B7B` (3.7:1, against about 6.4:1 for Textual's dim of the foreground)
  on the name, value and default of a row the file doesn't set; its state and category keep their CF3 colours, and
  a set row of a read-only file stays dim.
- G2d: R1's gold title (`HELP_TITLE`, bold `TITLE_GOLD`) is on a file's panel too; `HELP_LABEL` is the review
  trees' `ACCENT` (bold cyan) on every label, the bullets' source names and the file panel's included.
- G2e: R2's leaf is a CVar row as `rows_for` shows it. The root (the scope label) counts too; the count comes after
  the whole label (after a file's `✎ N` / `no file` note); a file or a character shows one only when it has rows,
  an account, realm, flavor and the root always (an account with no files and no characters says `0 items`).
- G2f: R5's counts are worked out in the same pass as R2 (`_count_rows`, once per rebuild: one extra `ops.rows`
  per file, every category at once) across the review's flavors, and put in the select with `set_options` under
  `prevent(Select.Changed)` so the pick stays and no second rebuild runs; the prompt reads `All categories (N items)`.
- G2g: no CHANGELOG line: the Config Editor is unreleased and its `[Unreleased]` Added line covers it; G10 adds the
  suite-wide counts and columns line.
- G3a: the WTF Cleaner's leaf is a cleanable addon entry (a `ProposalItem`); a blacklisted row is shown but not
  counted (it is never cleaned, as the group's tick mark already left it out). An addon row is the leaf itself: its
  files are its `files` column, not an R2 count.
- G3b: under a search a group counts the entries with a file `filter_keys` shows, the same test `ModelFilter` uses
  to keep an addon row (its addon, a file or a group above it matches), so the count is what the tree shows.
- G3c: a group with no cleanable entries at all keeps "nothing to clean" in the count's place (the guide and two
  tests name it); a group with entries none of which the search shows says `0 items`.
- G3d: columns: an addon row is name · reasons · files · size · age, a file row name · size · age (the ` · `
  separators are gone). Caps 40 / 48 for the name and reasons (56 for a file name), minimums 12 / 13; the reasons
  give way first, then the name (cut in its middle); files, size and age are never cut, dropped age, files, size
  (a file row: age). A blacklisted row now shows the age column too, so it aligns with its cleanable siblings.
- G3e: `ui/columns` takes a Rich `Text` cell as well as a string (`natural_widths` measures it, `column_text` keeps
  its spans over the column's style and cuts it at its end), so the reasons keep a colour per criterion.
- G3f: the natural widths are worked out over the sibling rows the search keeps, once per rebuild (`_add_node`),
  with the ages as of that rebuild; `_fit_rows` refits on a resize and after a rebuild made before the tree was
  laid out (the tree is hidden during the scan).
- G3g: no CHANGELOG line here (G10 adds the suite-wide one).
- G3h (review fix, replaces G3c): a group with rows below it but no cleanable entry (only blacklisted rows, or a
  flavor whose accounts have nothing to clean) counts `0 items` (STD-7.27); only a group with no rows at all keeps
  "nothing to clean". `test_flavor_with_nothing_to_clean_says_so` now checks `0 items` on the flavor and "nothing
  to clean" on its accounts.
- G3i (review fix): a group's name is cut in its middle so its count fits the pane (at 80 columns the 28-cell pane
  cut `account-wide  7 items` to `account-wide  7 `); `_fit_rows` refits group rows on a resize too, and the
  long-name test checks every row's width at 120 and 80 columns.
