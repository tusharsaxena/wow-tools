# Config Editor feedback round 1: status

Branch `feat/config-editor-feedback-1`. Plan `2026-11-04-config-editor-feedback-1.md`. Resume at the first row not
`done`.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| FB0 | curate a group for every shipped CVar (workflow pass, data handed to FB1) | done | (FB1's commit) | 1896 names: interface 673, other 250, camera 352, network 18, graphics 358, sound 68, combat text 71, nameplates 106 |
| FB1 | category filter fix, cvar_categories.json, kb lookup | done | (this commit) | +7 tests (5 test_kb CuratedCategoriesTest, 2 test_config_editor_app), test_category_mapping and the kb README test extended; gate: run_tests --all WSL 2327 OK (10 skipped) + Windows 2327 OK (86 skipped), ruff clean, gen_event_docs --check OK |
| FB2 | columnar rows, truncation, colours | done | (this commit) | +6 tests (4 test_config_editor_ops row columns, 1 test_ui_base colours, 1 test_config_editor_app aligned coloured columns), test_row_text became test_row_cells, row assertions in test_config_editor_app updated; gate: run_tests --all WSL 2333 OK (10 skipped) + Windows 2333 OK (86 skipped; first run hit a Windows asyncio socketpair error in an unrelated Config Copier test, --windows rerun clean), ruff clean, gen_event_docs --check OK |
| FB3 | help panel layout | todo | | |
| FB4 | Set description, Add dropdown | todo | | |
| FB5 | push, CI once, ready to merge | todo | | |

## Decisions taken during the build

- U1 (user): the state column is the column's name only: `changed` / `default` / `unknown`.
- FB1a: the cause of CF4a, from the user's own log (`logs/config-editor/events-2026-11-04.log`): at 16:36:57 the
  search "gra" was applied, and every category picked from 16:37 to 16:38:55 was combined with it. Graphics,
  Interface and Other hold CVars whose name or help contains "gra"; Sound, Camera, Nameplates, Combat text and
  Network hold none, so the tree showed only NO_MATCH_TEXT. The category filter itself, with the shipped data and
  Show all known, lists every group at every level (reproduced; now a test). STD-7.8 keeps the single NO_MATCH_TEXT
  line, so the fix is in the help panel: when the search empties the tree it names the search, the category and
  Changed only, says they narrow together, and how to clear each (Esc in the filter box, All categories), plus a
  Show all known hint when that is off.
- FB1b: `core.kb.curated_categories()` (lowercased name -> group, cached beside the file cache, cleared by
  `clear_cache`) and `cvar_category(name, raw)`; an entry whose group is not one of `CATEGORY_GROUPS` is ignored (the
  rules decide), a file without a `categories` object is `kb.unreadable`. `category_group` is kept unchanged as the
  rules fallback.
- FB1c: `model.category_of` gives a CVar the flavor's data doesn't know (a Classic file with a Retail-only name) the
  shipped curated group too, before the name rules.
- FB1d: "sorted by name" is Python's plain string order (upper case first, as `sort_keys` gives), checked by the test.
- FB1e: no shipped CVar name was missing from the curated list (1900 names in the five files are 1896 without
  regard to case: four differ only in case between flavors), so nothing was added from the old rules.
- FB1f: the search does not match the category name; not asked, and it would change the shared rule of what a
  search reads.
- FB2a: the state rule (`report.row_state`): `changed` when the value differs from the known default; `default` when
  it matches it or the CVar is not set (the game then uses the default); `unknown` when the knowledge base has no
  entry or no default for it. The value cell of a CVar not set reads `not set`; the default cell is blank when
  there is no default.
- FB2b: the columns fit the tree pane (`report.fit_columns`): the name, value and default capped at 40 / 24 / 24
  (CF2); two spaces between columns when that fits, else one; when the pane is too narrow the value and the default
  shrink first (the wider of the two each time), then the name, never under 12 / 7 / 6 (7 so `not set` stays
  whole); the state and category are never cut. The room is the tree's width less a scrollbar's, the guides in
  front of the file's rows and the 4-cell mark; the rows are fitted again when the screen is resized.
- FB2c: at 80 columns the tree pane is 28 cells wide and a character's rows have 8 cells after the guides and mark,
  so no five-column row can fit there: the plan's "at 80x30 the row still fits" is met at 120x30 (tested: every
  character row fits its pane), and at 80x24 (STD-7.23's floor) the columns go to their minimums and the tree
  scrolls sideways (tested: the row is cut further and the state and category still show).
- FB2d: colours (`ui/theme.py`): state changed = the theme's amber (warning), default `#5E9E7C`, unknown `#76869A`;
  categories graphics blue `#6E9BFF`, sound violet `#C792EA`, interface the theme's cyan accent, camera pink
  `#E58FD0`, nameplates lime `#A6D96A`, combat text coral `#F07178`, network sand `#D7BA7D`, other stone grey
  `#A39E93` (warm, apart from the unknown state's cool grey). Each at least 4.5:1 on the background (tested). The
  name and value keep the old dim (not set, read-only) and italic (unknown) styles; the default column is dim.
- FB2e: `report.row_text` (the one-line `name = value (default …) ✱changed`) is gone, replaced by `row_cells`;
  `CHANGED` is now the state word `changed` (the help panel's "(changed from the default)" unchanged). The in-app
  help (help.py) and the guide describe the columns; the guide's browse.png screenshot is not regenerated here
  (screenshots are taken by hand).
