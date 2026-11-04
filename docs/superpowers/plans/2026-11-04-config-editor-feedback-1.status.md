# Config Editor feedback round 1: status

Branch `feat/config-editor-feedback-1`. Plan `2026-11-04-config-editor-feedback-1.md`. Resume at the first row not
`done`.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| FB0 | curate a group for every shipped CVar (workflow pass, data handed to FB1) | done | (FB1's commit) | 1896 names: interface 673, other 250, camera 352, network 18, graphics 358, sound 68, combat text 71, nameplates 106 |
| FB1 | category filter fix, cvar_categories.json, kb lookup | done | (this commit) | +7 tests (5 test_kb CuratedCategoriesTest, 2 test_config_editor_app), test_category_mapping and the kb README test extended; gate: run_tests --all WSL 2327 OK (10 skipped) + Windows 2327 OK (86 skipped), ruff clean, gen_event_docs --check OK |
| FB2 | columnar rows, truncation, colours | todo | | |
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
