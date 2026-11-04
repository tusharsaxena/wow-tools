# Config Editor feedback round 1: design

The user's first smoke test of the Config Editor (merged in 03d9bf6, spec
`2026-11-04-config-copier-macro-editor-config-editor-design.md`, decisions CE1-CE8, X8) asked for six changes. This
spec records them as decisions CF1-CF6. Everything not named here stays as CE1-CE8 decided.

## Decisions

| ID | Decision |
|---|---|
| CF1 | **Columnar CVar rows.** Each CVar row in the browse tree reads as five aligned columns: **CVar name**, **current value**, **default value**, **state**, **category**. The state column says `changed` (the value differs from the known default), `default` (it matches) or `unknown` (the reference has no default). The user chose "the column is called state" (no per-character-state marker). The staged mark (✎ / + / ✗) stays in front of the name. Columns align within one file: each column is as wide as its widest cell in that file, up to a cap. |
| CF2 | **Truncation.** The current and default value columns are capped (my call: 24 characters each) and a longer value is cut with `…`, so a long blob (`collapsedCurrencyCategoryDefaults = v21##…`) can't push the other columns off screen. The full value stays visible in the help panel and the Set popup. The name column is capped too (my call: 40) for the same reason. |
| CF3 | **Colour.** State: `changed` in amber, `default` in dim green, `unknown` in dim grey. Category: one fixed colour per category group (graphics, sound, interface, camera, nameplates, combat text, network, other), defined once in `ui/theme.py` next to the other shared colours. The colours must read on the suite's dark background and match the existing palette's tone. |
| CF4 | **Category filter and mapping.** (a) Bug: picking any category in the left pane except the busiest ones (seen for Sound, Camera, Nameplates, Combat text, Network, with Show all known ticked) shows "Nothing matches the filter" although the data has CVars in those groups. Find and fix the cause, with a test that reproduces the user's case. (b) The groups themselves stay (the user said they make sense), but the mapping of every CVar is redone: the client's console category files most CVars under `game` (now all "interface") or `default` / `none`, which puts cursor, tooltip, chat, map and similar settings in the wrong group or in "other". A curated file `wowtools/kb/cvar_categories.json` assigns a group to every CVar name in any shipped `cvars/<flavor>.json`, decided from the name and the help text; `core.kb` uses it first, then the existing name and console-category rules for a CVar it doesn't list (a CVar a future dump adds). `scripts/refresh_kb.py` keeps working unchanged; a test checks that every shipped CVar has a curated group. |
| CF5 | **Help panel layout.** The help panel under the tree is laid out for reading: the CVar name as a bold title, then labelled lines in bold (Value, Default, State, Category, Scope, Blizzard, Note, Recommended, Sources) with values in normal weight, the state and category in their CF3 colours, a blank line between the sections, and bullets where a section lists several things (sources). Same content as today, only clearer. |
| CF6 | **Popups.** (a) **Set** shows what the setting does under the Default line: our note when there is one, else Blizzard's help text, else "No description in the reference." (b) **Add**'s CVar name becomes a searchable dropdown: the list holds every CVar the reference knows for that file's game version (and level, as Show all known does) that the file (or, for several ticked files, any of them) doesn't set yet; typing narrows it. Picking one shows a one-line description under it and fills the value with its default (editable). A name the reference doesn't know can still be typed and added, as CE5 allows. |

## Not changing

The tree structure, the left pane (apart from the fix in CF4a), the keys, the write pipeline and every safety net.

## Builder notes

- Rich `Text` for the columns and colours; no new widget library. The tree stays a Textual `Tree`.
- Every visible change gets a line in the Config Editor guide (`docs/config-editor.md`) and, where it shows, the
  internals doc. The CHANGELOG `[Unreleased]` already has a Config Editor line; no new line unless something new
  for users appears outside this tool.
- At 120x30 and 80x30 the rows still fit in the tree pane (truncate further when the pane is narrow).
