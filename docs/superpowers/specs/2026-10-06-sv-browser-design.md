# Ka0s WoW Tools: Saved Variables Browser design

Date: 2026-10-06. Fifth tool in the suite. Branch: `feat/sv-browser`. Plan: `../plans/2026-10-06-sv-browser.md`,
ledger `../plans/2026-10-06-sv-browser.status.md`. It follows `docs/adding-a-tool.md`, the two-pane look and feel of
the other tools, the suite rules (D7/D8 tree filter, D12 action kinds, D13 confirms, D17 keys on buttons, D18 help)
and the safety model of the Ace3 Profile Manager, whose SavedVariables reader and write pipeline move into the shared
library for it.

## 1. Purpose

Show every SavedVariables file of a WoW install (every flavor, account, account-wide and per character) as a tree the
user can browse down to single values, and let them change it offline: edit a value, rename a key, delete a key. The
key feature is **bulk replace**: find every value by key name, by value text, or both (for example every `font`
key whose value is `Friz Quadrata TT`), tick the hits, and replace them all in one run. This is a power tool with no
knowledge of what any addon expects, so it carries a strong **USE AT OWN RISK** disclaimer, and it has the same
safety net as every other tool that writes: a whole-WTF snapshot, a zip of every changed file's original, a run
journal, Undo and crash recovery.

## 2. SavedVariables on disk (facts the tool relies on)

- A SavedVariables file is `<Flavor>/WTF/Account/<ACCOUNT>/SavedVariables/<Addon>.lua` (account-wide) or
  `.../<ACCOUNT>/<Realm>/<Character>/SavedVariables/<Addon>.lua` (per character). It is a list of `Name = value`
  assignments: tables, strings, numbers, booleans, nil. CRLF, unindented, keys in `["x"]`/`[1]` form, array entries
  as `value, -- [n]`, full-precision floats, `\ddd` escapes, sometimes invalid UTF-8.
- Files go up to tens of MB (WeakAuras, Details, Plater). A full-depth parse of a 33 MB file takes ~15 s and ~1 GB
  (measured with the Ace3 parser); a depth-1 parse takes ~2 s.
- WoW rewrites every SavedVariables file on logout and `/reload`: edits made while the game runs are lost. Companion
  apps (RaiderIO, WeakAuras Companion) may hold files open.
- `.bak`/`.old` copies and `Blizzard_*.lua` files sit in the same folders.

## 3. Decisions

Settled with the user up front (2026-10-06): D2, D5–D9, D13–D15, D21. The rest are the implementer's calls, recorded
here.

| # | Topic | Decision |
|---|---|---|
| D1 | Name | Tool `sv-browser` (used for every name in code and on disk: registry, `config/sv-browser.cfg`, `logs/sv-browser/`, `<WoW>/wow-tools/sv-browser/`, `docs/sv-browser.md`). Display name **"Saved Variables Browser"** (menu, titles, help, README, guide). Package `wowtools/tools/sv_browser/` (a Python package can't contain `-`, the same as every tool). Config section `[sv_browser]`. Events `svb.*`. Menu text: "Browse and edit every SavedVariables file, with bulk find and replace." Appended last in `TOOLS`. |
| D2 | Disclaimer | **Every time the tool starts** (flow entry, not on rescan), a warning popup before the first scan: "USE AT YOUR OWN RISK. This tool edits addon SavedVariables directly. It knows nothing about what an addon expects; a wrong value can break an addon or lose its settings. Backups and Undo are made, but you are responsible for what you change." Buttons **I understand** (confirm, default) and **Back** (cancel, Esc, returns to the flavor picker). The review also shows a permanent red one-line banner at the top of the left pane, and every Apply/Undo confirm carries the disclaimer in its red alert lines. |
| D3 | Scope and flow | Flavor picker with **All flavors** first (remembered in `last_flavor_choice`), then the review. No account picker: the tree shows every account. |
| D4 | Which files | Every `*.lua` directly in a `SavedVariables` folder (account-wide and per character), **including `Blizzard_*`**; never `.bak`/`.old` or anything else; links are never followed (`SvGuard`). A file that fails to parse shows as a red "can't read" row and can't be edited or searched. |
| D5 | Tree edits | **Edit value** (any scalar; the type may change between string, number and boolean), **Rename key**, **Delete key** (scalar or whole subtable). No adding keys and no editing a table as a value. Top-level SavedVariables (`Name = …`): value edit only when it is a scalar; never renamed or deleted. Array entries (no written key): delete allowed with a warning that later entries shift down like `table.remove` and their `-- [n]` comments go stale; rename refused. A rename to a key that already exists in that table is refused. New keys are always written in bracket form (`["x"]`, `[5]`, `[true]`). |
| D6 | Key search | Search text matched against the key's text (`font`, `5`, `true`). Two switches per search: **Exact / Contains** (default Exact) and **Match case** (default off; off = `casefold()`). |
| D7 | Value search | Search text matched against **string values**, plus numbers and booleans by their written text in Exact mode only. Switches per search: **Whole value / Contains** (default Whole value) and **Match case** (default off). Contains matches only strings and replaces **every occurrence of the text inside the string** (case-insensitive replace via `re.escape`), keeping the rest of the string. |
| D8 | Key + value | Either field may be empty but not both. When both are given, a hit must satisfy both (e.g. key `font` exact, value `Friz` contains). Only scalar values are hits; a key whose value is a table is never a hit. |
| D9 | Search scope | Optional filters on the search popup: **Flavor** (only when All flavors), **Account**, **Character** (with an "Account-wide only" choice) and **Addon file** (text, contains, case-insensitive). Default: everything. |
| D10 | Replacement | Whole-value hits are replaced with a **typed value**: string (default), number, or boolean, entered in the search popup before searching, so the results show `old → new`. Contains hits get the replacement **text** spliced into the string. Number entry refuses `inf`/`nan` and anything Lua would not read back as the same number. |
| D11 | Results view | Find runs as a progress job over every file in scope (parallel per file, `run_units`, `[general] parallelism`), streaming with a byte pre-filter, so huge files are never fully built in memory. Hits fill a **Results** view of the tree: flavor › account › account-wide/character › file › key path, one leaf per hit showing `path = old → new`, **all ticked** (a/n/space and the `/` filter act as on every tree screen, D7/D8). `v` switches between the **Browse** and **Results** views. A new search replaces the results (confirm if any are ticked). Results are capped at 10,000 hits (the summary says how many were dropped and that the search should be narrowed). |
| D12 | Staging | Nothing is written until **Apply**. Browse-view edits (D5) are staged one by one and marked in the tree (`✎ new value`, `✗ deleted`, `→ new name`); Backspace on a staged node unstages it. Apply writes **all staged edits plus every ticked result** in one run. A ticked result on a value that also has a staged edit (or lies under a staged delete) is dropped with a note in the summary; the staged edit wins. The left-pane summary shows `Staged: N edits · Ticked: M results in F files`. |
| D13 | Before executing | Apply shows a destructive `ConfirmScreen` listing counts per flavor and file and the disclaimer as red alert lines. Dry run (`simulate`) does every check (WoW, locks, file changed since scan, compile, verify) and writes nothing. |
| D14 | Safety net (same as every writing tool) | Per flavor, before writing: a **whole-WTF snapshot zip** (`<root>/snapshots/`, kept to `[general] keep_backups`), a **zip of the original bytes of every file the run changes** (`<root>/edited/`, the Undo source, pruned with the journals), a crash **marker**, atomic writes, a read-back and re-parse **verify** of every written file, roll-back of the run's written files on any failure. One **run journal** per Apply (`<WoW>/wow-tools/sv-browser/journal/`, kept to `[general] keep_journals`). `<root>` is `<backup_dir>/sv-browser` when `backup_dir` is set, else `<WoW>/wow-tools/sv-browser`. |
| D15 | Undo and recovery | `z` undoes the latest Apply exactly like the Ace3 Profile Manager: a file goes back only if it is byte-for-byte what the run wrote (else "changed since"), refused while WoW runs, its own snapshot first, journaled. An unfinished run (marker present at start) offers **Put back** or **Leave**. |
| D16 | WoW running | Apply and Undo **refuse** while that flavor's WoW runs (the game would overwrite the edits); if the check can't run, warn in the confirm and allow. Locked files are refused by the lock probe. Find, Browse and Dry run are always allowed. |
| D17 | File changed since scan | Every file's SHA-256 is taken when it is first read (browse load or search). Apply re-reads it; a different hash skips that file with "changed since scan, rescan". |
| D18 | Lazy tree | The scan lists files and sizes only (no parse). Expanding a file parses its top level; expanding a table parses that table only (`parse_at` on the span). A table with more than 500 children shows the first 500 and a "… N more" leaf. `x` (expand all) expands down to file level only. The `/` filter matches loaded labels only (in Browse); in Results it matches every hit. |
| D19 | Writing method | Byte-span splices (no re-serialization, every untouched byte identical). Strings are written with double quotes and Lua escapes (an edited single-quoted string changes quote style). Numbers: `int` as `str()`, `float` as `repr()`, untouched raw numbers (`1.#INF`) kept. Verify: the new file parses; the assignment names and the bytes between them are unchanged; every touched table re-parses to exactly the expected ordered list of (key, value); bytes outside the edit spans are unchanged. |
| D20 | Shared library | Under the two-tool rule the Ace3 code SV Browser needs moves to `wowtools/core/` and `wowtools/ui/` first, with Ace3 refactored onto it and **no Ace3 test assertion changed**: `core/luasv.py` (parser, plus `parse_at`, `iter_scalars`, `encode_value`, `encode_key`, the `-- [n]` remove-span fix), `core/svfiles.py` (`SvFile`, `sha256_of`, the file walk), `core/sv_apply.py` (prepare/compile/verify/snapshot/originals zip/marker/write/roll-back, per flavor and multi-flavor), `core/sv_journal.py` (edit journal reader/writer), `core/sv_undo.py` (`undo_run`, `recover`), verify helpers, report rows, `tool_root`; UI: `popup_css`, `show_error`, a text prompt popup, the recovery popup, and the apply/undo/recover worker plumbing in `ui/review.py`. Events stay per tool: core takes the tool's event prefix (`ace.*` unchanged, `svb.*` new). Exact module split is the implementer's call, pinned by `tests/test_structure.py`. |
| D21 | Disclaimer before executing | See D2 and D13: the disclaimer is shown on start, on screen, and in every Apply/Undo confirm. |

## 4. Package layout (`wowtools/tools/sv_browser/`)

| Module | Job |
|---|---|
| `__init__.py`, `events.py` | Registers `svb.*` events. |
| `settings.py` | `[sv_browser]`: `backup_dir` (blank = WoW folder), `last_flavor_choice`. `save_settings` calls `Config.remove_retired("sv_browser")`. |
| `scanner.py` | Lists SavedVariables files per flavor/account/character (`SvFile`), no parse; recovers probe leftovers. |
| `model.py` | Lazy tree model: file → top-level → tables, typed keys `(type, value)`, child cap. |
| `search.py` | `SearchSpec` (key, value, modes, case, scope, replacement), per-file streaming search with pre-filter, `Hit`. |
| `ops.py` | `Staging`: staged edits (set, rename, delete) plus ticked hits → per-file plans; collapses overlaps (D12). |
| `compile.py` / `verify.py` | Per-file edit list → splice; verify per D19. |
| `journal.py`, `undo.py`, `report.py` | Thin wrappers over the shared core (tool name, events, result rows). |
| `app.py` | `SvBrowserFlow(ToolFlow)`, `FLOW`. |
| `review_screen.py`, `popups.py`, `result_screen.py` | UI (the only modules importing `textual`). |
| `help.py` | `HELP`, `GUIDE_URL` (D18 of suite polish). |

## 5. TUI

**Disclaimer popup** (D2): a warning `ChoiceScreen` pushed by the flow after the flavor pick, before the review
scans; Back returns to the flavor picker.

**Review** (`SvReviewScreen`, two panes, 120x30 base, works at 80x24):
- **Left pane** (`#filters`), one focusable control per row: the red `USE AT YOUR OWN RISK` banner (static),
  `FilterInput`, the `Static#pending` summary, `ButtonRow#actions` with **Search** (`s`, navigate), **Apply** (`w`,
  destructive), **Dry run** (`y`, simulate), **Rescan** (`r`, navigate), **Undo last change** (`z`, revert), and the
  `NavHint` (REVIEW_HINT, `v` view, FILTER_HINT, TREE_HINT, flavors/tools). The search form lives in a popup so the
  left pane stays short at 80x24.
- **Tree**, Browse view: flavor › account › `Account-wide` / `Realm › Character` › `Addon.lua (size)` › keys.
  Scalars show `key = value` (strings quoted, long strings cut with `…`); tables show `key {N}`. Staged edits are
  marked (D12). Results view: see D11. The sub-title names the view.
- **Under the tree**, a `WrapButtonRow` acting on the highlighted node: **Edit value** (`e`, overwrite), **Rename
  key** (`k`, overwrite), **Delete key** (`d`, destructive), **View** (`v`, navigate). Buttons that can't act on the
  highlighted node are disabled.
- Keys: `space`/`a`/`n` (Results), `/`, `x`/`c`, `backspace` unstage, `f` flavors, `t` tools, `q` quit, `h` help,
  `←`/`→` between panes. Leaving with staged edits or ticked results asks first (destructive confirm).

**Popups** (`popups.py`): **Search** (key, key Exact/Contains, value, value Whole/Contains, Match case, scope
Flavor/Account/Character/Addon, replacement type and value; Find runs the search), **Edit value** (type select +
input or checkbox, validated per D10), **Rename key** (shared text prompt; refuses duplicates and empty), **Delete
key** (destructive confirm; array-shift warning per D5), and the shared progress, confirm, recovery and help popups.

**Result screen**: the suite's result screen with summary rows (flavors, files edited/would edit/skipped/failed/rolled
back, edits written, snapshot and originals zip paths, journal) and one detail row per file. Buttons Rescan, Other
flavor, Tools, Quit.

## 6. Events (`events.py`, prefix `svb.`)

`svb.started`, `svb.disclaimer_accepted`, `svb.disclaimer_declined`, `svb.scan_completed`, `svb.file_unreadable`
(warning), `svb.search_started`, `svb.search_completed`, `svb.staged`, `svb.unstaged`, plus the shared apply/undo/
recovery events under the `svb.` prefix (`apply_started`, `file_edited`, `file_changed` (warning), `file_failed`
(error), `rolled_back` (warning), `apply_completed`, `undo_*`, `recovery_*`, `journal_pruned`). Levels and fields are
fixed in the plan; `docs/events.md` is regenerated.

## 7. Testing

- `tests/fixtures.py` gains `build_sv_tree(root)`: two flavors, two accounts, account-wide and per-character files,
  nested tables, numeric and boolean keys, `Font`/`font`/`barFont` keys, `"Friz Quadrata TT"` in several files and
  flavors, escapes, floats, `nil` array slots with `-- [n]` comments, a `Blizzard_*` file, a `.bak`, a broken file.
- Unit tests per module (`test_sv_browser_*`), plus `tests/test_luasv.py` for the new parser surface (`parse_at`,
  `iter_scalars`, encoders, the remove-span fix) and the moved core modules (existing Ace3 tests keep every
  assertion).
- A streaming guard: searching a generated multi-MB file stays within a time and memory bound.
- Add the tool to `tests/test_look_and_feel.py` (`TOOLS`, `RUN_ACTION`, `PREPARE`, the disclaimer step) and
  `tests/test_help.py`. Tests never touch a real WoW install or the network.

## 8. Documentation

`docs/sv-browser.md` (guide in the house style, a USE AT YOUR OWN RISK section first, a screenshots placeholder),
README (tools row, guide link, settings row), `docs/architecture.md`, `docs/adding-a-tool.md` (shared luasv/write
pipeline), `docs/events.md` (regenerated), `CHANGELOG.md` (Added), CLAUDE.md (tool list, core list).

## 9. Out of scope

Adding keys or tables, editing a table as a value, regex search, `.bak` files, `WTF/Config.wtf` and other non-Lua
files, editing while WoW runs, and any knowledge of particular addons.

## Addendum A: as built (2026-10-07)

Where the build differs from or adds to the decisions above, from the ledger's "Decisions taken during the build"
(`../plans/2026-10-06-sv-browser.status.md`). The user guide (`docs/sv-browser.md`) and `docs/architecture.md`
describe the tool as built.

| # | Topic | As built |
|---|---|---|
| D22 | Search key and row | **Search** is on `S` (Shift+S), not `s`: `s` is the suite's settings key on every screen. It sits on its own `ButtonRow#search-row` above `#actions` (§5 put it in `#actions`): five keyed buttons do not fit the 50-column left pane, and `#actions` stays the four-button row every tool has (Apply, Dry run, Rescan, Undo last change). |
| D23 | Unstage button | The action bar under the tree has a fifth button, **Unstage** (`cancel`, key Backspace, like Ace3's Discard), enabled only on a key with a staged edit (D17: the key shows on a button rather than in a hint). |
| D24 | Find only | The search popup's **Replace with** has a fourth choice, **Find only** (`replacement=None`): its hits show `path = old` with no tick and count nothing for Apply; Space/`a`/`n` there (and in Browse) say why nothing can be ticked. A Contains value search with a Number or Boolean replacement is refused inline by `SearchSpec.problems()` instead of the select being locked to String. The popup opens with the previous search. |
| D25 | Disclaimer | Asked once per opening of the tool from the menu (the flag lives on the flow), after the flavor pick: not again when the user goes back to the picker and picks again, nor on a rescan. **Back** carries Esc; **I understand** is focused. The red banner reads "⚠ USE AT YOUR OWN RISK: you change addon data". In the confirms the disclaimer is an alert line of every **Apply** and **Undo** (not of a Dry run, which writes nothing). |
| D26 | Events | The spec's `svb.file_failed` is the shared `svb.write_failed` / `svb.verify_failed`; `svb.file_unreadable` (warning) also covers an unreadable folder and a file that is not readable Lua. Recovery "Leave" logs the shared `svb.recovery_done` with `choice="leave"`. |
| D27 | Lazy tree | The model parses **one level ahead**, so every shown table knows its size (`key {N}`): a file loads with its top-level tables built, a table opens with `parse_at` on its span and its first 500 child tables parsed one level deeper. A fault deeper than that shows as one red error child when its table is opened; the rest of the file stays browsable. The scan runs behind the shared scan box (not a popup) and reads no file; the SHA-256 (D17) is taken when the model or the search first reads the bytes. |
| D28 | Search matching | A number key matches its written text (`[2.50]` is "2.50"), an array entry its position; `nil` is found by key, never by value; Match case off is `casefold()` for Exact/Whole and case-insensitive regex for Contains; a value of only blanks is still a needle. The byte pre-filter is off for needles or files where an escape or a non-ASCII case fold could hide a match. A file with a parse fault is listed as unreadable and its hits dropped (D4). The 10,000 cap keeps the first hits in file order whatever the parallelism, and also bounds one file's hits in memory. |
| D29 | Staging rules | Edits under a key are dropped **when** its delete is staged (and new ones there refused), so a plan never holds both; setting the value already there (by Lua identity: `12.0` for `12`) or renaming to the same key stages nothing; an empty key is refused; unstaging a rename is refused when it would leave a duplicate key; a number key must read back as itself. Dropped-hit reasons (D12): a staged edit on the value, on or under a staged delete, the same value ticked twice, or the file read with other bytes than the staging's. A hit on a key that is only renamed **combines** with the rename. |
| D30 | Typing keys and values | Rename reads keys as the tree writes them: `[5]`, `[2.5]`, `[true]` / `[false]` are number or boolean keys, `["…"]` the literal text inside, anything else a string key. Edit value starts from the staged value if any (else the file's), on its type; a string with control characters or invalid UTF-8 starts empty with a note. In the popups Enter on a checkbox presses OK / Find and Space ticks it. |
| D31 | Results view | Groups are flavor › account › owner (`Account-wide` or `Realm/Name`, one level) › file; every group opens. The `/` filter matches the names and the hit text (not the marks). A ticked hit Apply would leave out shows `⚠ left out: <reason>`, and the pending line counts them. A rescan drops the results and returns to Browse. |
| D32 | Runs and staged work | A Dry run, and an Apply refused before writing anything, open the result with **Back to review** (Esc) and keep the staged edits and ticks. A real Apply or Undo drops them and rescans when the result screen is left. An Undo refused before it starts keeps them; its confirm says what it will drop. Rescan with something staged or ticked asks first (destructive). |
| D33 | Recovery | Every scan that finds a crash marker offers the shared `UnfinishedRunScreen` (Put the originals back / Leave as is), only while the review is the shown screen (else when it is shown again), and Apply offers it before a new run. Its message says that putting back drops the staged work, and the choice is settled in the folder the marker was read from. |
| D34 | Shared library as built | D20's split: `core/luasv.py` (moved from Ace3, plus `parse_at`, `iter_scalars`, `encode_value` / `encode_key` / `key_id`, the `-- [n]` remove-span fix), `core/svfiles.py` (`SvFile`, `sha256_of`, `walk_sv_files` with `is_sv_file` / `is_addon_sv_file`, `OWNER_ACCOUNT_WIDE`), `core/journal.tool_root`, `core/sv_events.py` (`SvTool(name, prefix)`, `sv_events(prefix)`), `core/sv_apply.py` (one `WowRunning` for Apply and Undo), `core/sv_journal.py`, `core/sv_undo.py`, `core/sv_verify.py`, `core/sv_report.py` (also `recovery_text`, `STATUS_COLOURS`); UI: `TextPromptScreen`, `UnfinishedRunScreen`, `popup_css`, `show_error` in `ui/dialogs.py`; `RunActions` (with `start_run(..., writes=)`), `BarTree` and `ActionBar` (moved from Ace3) and the `TickActions.no_ticks_here()` hook in `ui/review.py`. The tool's apply wrapper is `editor.py` (per flavor and `apply_plan`; no separate `multi.py`); the result screen is `result_screen.py`. |
| D35 | Lua 5.1 escapes | `luasv.decode_string` follows Lua 5.1, WoW's: `\x41` and `\z` are not escapes (an unknown escaped byte stands for itself), so such strings read as WoW reads them, in both tools. |
| D36 | Confirm detail | The Apply / Dry run confirm lists, per flavor, one line per file (`ACCT1 › Account-wide › ElvUI.lua: 2 edits`) in its detail tree, and its alerts name the ticked results left out and the array entries that move down. |

## Addendum B: feedback round 1 (2026-10-07)

The user's feedback after trying the first build. These replace the earlier decisions they name.

| # | Topic | Decision |
|---|---|---|
| D37 | Risk banner | The on-screen banner reads exactly `⚠ USE AT YOUR OWN RISK` (a space after the icon, nothing after it), defined once in `wowtools/ui/` and shown at the top of the left pane of every screen that can destroy data: the Saved Variables Browser review, the WTF Cleaner review, the Ace3 Profile Manager review and Interface Backup's restore screen. The start-up popup and the confirm alerts (D2, D13) stay. |
| D38 | Search is find only | The Search popup loses **Replace with** / **New value** (and the Find only choice, D24): it only finds. A blank row separates Key + Key match from Value + Value match. Replaces D10's "entered in the search popup". |
| D39 | Bulk edit on ticked results | In the Results view, **Edit value** and **Rename key** act on every ticked hit when any are ticked (else on the highlighted hit). They open the normal popups (titled with the count, e.g. "Edit 37 values"); OK stages one edit per ticked hit (a set or a rename) into the same staging as Browse edits, so the marks show in Browse and the pending line counts them. A hit whose key can't be renamed (top-level, array entry, duplicate in its table) or that already has a staged edit is left out and the popup's result says how many. If the search used value **Contains**, Edit value also offers **Replace only the matched text** (default) vs **Whole value**; the matched-text mode replaces every occurrence in each string (D7 rules). Ticks select only; Apply writes staged edits (replaces D11/D12's "Apply writes every ticked result"). Delete key stays single-key. |
| D40 | Filter on submit | In every tool, the `/` tree filter no longer filters on each keystroke. It filters when submitted: Enter in the box or a **Filter** button beside it (shared `TreeFilter`/`FilterBox`); clearing the box and submitting shows everything. The hint says so. Replaces the debounced live filter (suite D7). |
| D41 | Header | The title bar reads `Ka0s WoW Tools` (no separator between Ka0s and WoW) in a gold colour, then the tool name, flavor and view in near-white, all bold, on every screen (shared header/branding). |
