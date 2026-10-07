# Saved Variables Browser internals

How the Saved Variables Browser (`wowtools/tools/sv_browser/`) reads, searches and edits SavedVariables files through the shared pipeline, and how its screens are built.

User guide: [sv-browser.md](../sv-browser.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools).

## Contents

- [Data flow](#data-flow)
- [Screens](#screens)

## Data flow

    scan_flavors(flavors, progress=(flavor, i, n, label)) → ScanResult(flavors[FlavorFiles(flavor, accounts[AccountFiles(name, owners[OwnerFiles(character, files[SvFile])])], warnings, error)])
    SvDocument(file).roots() / .children(node) → [Node]            (lazy: a file is read once, a table parsed when opened)
    Staging.set_value / rename / delete / unstage(doc, node, ...) → OpResult(ok, message, warning, dropped)
    run_search(files, SearchSpec, parallelism=, progress=(done, total, file)) → SearchResult(hits[Hit], dropped, unreadable, seconds)
    bulk.stage_values(staging, ticked hits, value_for) / bulk.stage_renames(staging, hits, key, bulk.read_tables(hits)) → BulkResult(staged, unchanged, left_out)
    Staging.plans() → Plan(files{SvFile(sha256 of what was read): FilePlan(edits[FieldEdit])}, staged)
    compile_file(file, FilePlan, bytes) → SvEdit(file, data, changes, plan, spans, problems);  verify_edit(edit, old_bytes) → [problems]
    editor.apply_plan(plan, root, journal_dir, keep_journals, keep_snapshots, dry_run, wow_check, progress) → MultiApplyResult
    undo.undo_run(journal_path, ...) / undo.recover(marker, ...) / undo.leave(marker, root=) → UndoResult

Modules in `tools/sv_browser/` (all UI-free except `app.py`, `review_screen.py`, `popups.py` and `result_screen.py`):

- `events` registers its 10 own `svb.*` events plus `sv_events("svb")` (the shared pipeline's) and exports
  `SV_TOOL = SvTool("sv-browser", "svb")`. `settings`: `[sv_browser]` `backup_dir`, `last_flavor_choice`;
  `resolve_root` = `core.journal.tool_root(backup_dir, wow_path, "sv-browser")`.
- `scanner` lists every flavor's SavedVariables files with `core.svfiles.walk_sv_files` and `is_sv_file` (exactly
  `.lua`, `Blizzard_*` included, no `.bak`/`.old`, nothing under a link), as flavor → account → owner (`Account-wide`
  or `Realm/Name`) → `SvFile` (size, mtime; `sha256` stays `""`: the scan reads no file). Probe leftovers are
  renamed back first (`svb.probe_recovered`); one `svb.scan_completed`; an unreadable folder is `svb.file_unreadable`.
- `model`: `SvDocument` reads a file once (its SHA-256 then, the D17 baseline) and parses **one level ahead**, so each
  shown table knows its size: the file with `parse(data, len(path) <= 1)`, a table on opening with `parse_at` on its
  span only (its first `CHILD_CAP` = 500 child tables one level deeper). `Node` (slots): kind `value` / `more` (the
  `… N more` leaf past the cap) / `error` (a fault in that table; a fault at the top level makes the whole file one
  error root), `typed_key` (`luasv.key_id`), `key_span`, `value`, `path` (top-level name first), `remove_span` and the
  D5 flags `can_edit_value` (any scalar), `can_rename` (below the top level, a written key), `can_delete` (below the
  top level). `key_text` / `scalar_text` / `table_text` / `node_text` are plain text (never markup: `[5]` is a key).
- `search`: `SearchSpec(key, key_mode, value, value_mode, match_case, scope)` (it only finds, D38), `problems()` /
  `check()`, `pattern()`, `SearchScope(flavor, account, character, addon)`, `parse_replacement(kind, text)` (what a
  value edit sets: a number must read back in Lua 5.1 as itself: no inf/nan, ints within 2^53) and
  `replace_matched(spec, text, new)` (a bulk edit's matched-text replace: every occurrence, literal). `search_file` streams
  `luasv.iter_scalars` behind a byte pre-filter (`may_hold`: skipped for needles or files where an escape or a
  case fold could hide a match) and never raises: a file that is not Lua is reported in `unreadable` with its hits
  dropped. `run_search` runs files through `core.parallel.run_units` (`[general] parallelism`), keeps about
  `HIT_CAP` = 10,000 hits (`_Room`: the first 10,000 in file order whatever the parallelism) and counts the rest in
  `dropped`; `svb.search_started` / `svb.search_completed`. A `Hit` carries the file (with the SHA-256 of the bytes
  searched), the typed path, the spans and the value with its bytes.
- `ops`: `Staging` holds one `FieldEdit(path, set_value, value, rename, new_key, delete, positional)` per key, by
  typed path in the coordinates of the bytes the document read, with every D5 refusal (`set_problem`,
  `rename_problem`, `delete_problem` are the checks the popups show inline): no nil and no table as a value, no
  rename or delete at the top level, no array-entry rename, no rename to a key the table would then hold twice
  (`new_duplicates` over the staged renames, deletes and array shifts), nothing inside a staged delete (staging a
  delete drops the edits inside it). Search hits are staged by `stage_hit_value` / `stage_hit_rename` /
  `unstage_hit` (`hit_edit`, `hit_deleted_above` for the marks), keyed the same way with the SHA-256 the search read
  (D39): refused when the key already has an edit (`ALREADY_STAGED`), is on or under a staged delete, or the bytes
  differ from the staging's or the loaded document's (`BYTES_DIFFER`: search again, and rescan if that does not clear
  it, since both are kept until a rescan), plus D5 (a rename is given its table for the duplicate check;
  `unstage_hit` of a rename too, and a str table is the reason it could not be read). `plans()` is the staged edits only. `parse_key` / `key_input` read and write keys as the tree
  shows them (`[5]`, `[true]`, `["[5]"]`).
- `bulk` (D39): `stage_values(staging, hits, value_for, shas)` and `stage_renames(staging, hits, new_key, tables,
  shas)` stage one edit per hit and return a `BulkResult` (staged, unchanged, `left_out` by reason; `text()` is the
  notice; logs `svb.bulk_staged`); `new_value(spec, mode, value, hit)` (`MATCHED` after a value Contains search:
  `replace_matched`; `WHOLE`); `read_tables(hits, progress)` reads each file once, checks its SHA-256 against the
  search's (`FILE_CHANGED`), and parses only the tables holding a hit (`compile.FieldIndex` / `locate`), a str reason
  where it can't.
- `compile`: `compile_file` re-locates every target by typed path in the bytes Apply read (`FieldIndex`: one dict
  per touched table), parses only the touched tables, and splices the value, key and remove spans
  (`luasv.encode_value` / `encode_key`, keys always bracketed). A plan that doesn't fit the bytes (key missing or
  there twice, an overlap, …) is not spliced: its problems become `verify_edit`'s, so the pipeline stops with "the
  change did not check out". `verify.verify_edit` (D19, on `core/sv_verify.py`): the new file parses, the
  assignments and the text between them are unchanged, each touched table (found by its **new** path) holds exactly
  the expected ordered (key, value) list, and every byte outside the spans is unchanged (`same_outside`).
- `editor` (`flavor_plan(plan)` groups `Plan.units()` by flavor in plan order; `apply_flavor` = core
  `sv_apply.apply_flavor(SV_TOOL, ..., compile_file, verify_edit, started={files, edits})`; `apply_plan` = core
  `apply_flavors` under one journal), `journal` (`SV_TOOL.journals`), `undo` (`undo_run`, `recover`,
  `pending_recovery(root)` = the crash marker, `leave(marker, root=)` = core `sv_undo.leave`: clears it and logs
  `svb.recovery_done` `choice="leave"`, False (and `marker_left`, at warning) when the marker could not be removed:
  the review keeps it and shows `leave_notice()`) and `report` (`DISCLAIMER`, `apply_confirm(plan, dry_run=)` with the array-shift and (Apply)
  disclaimer alert lines, `apply_groups` (per flavor, one line per file), `undo_confirm` (the shared one plus
  the disclaimer), `summary_rows`, `file_rows` / `FILE_COLUMNS`) are thin wrappers over the shared pipeline
  (`core/sv_apply.py`, `sv_journal.py`, `sv_undo.py`, `sv_report.py`).

On disk: `<root>` = `<backup_dir>/sv-browser`, else `<WoW>/wow-tools/sv-browser`, holds `snapshots/snapshot-<flavor>-<stamp>.zip`
(kept to `[general] keep_backups` per flavor), `edited/edited-<flavor>-all-<stamp>.zip` (the originals, pruned with
the journals) and `edit-in-progress.json` (the crash marker); journals are `<WoW>/wow-tools/sv-browser/journal/`
(`[general] keep_journals`). Apply is serial per flavor (one marker), stops at the first failing flavor and rolls
back that flavor's written files; Undo snapshots up to `parallelism` flavors at once.

## Screens

`app.py` holds `SvBrowserFlow` (`FLOW`: `require_install` → `SvBrowserSettingsScreen` (backup folder only) on the
tool's first open → `FlavorScreen(include_all=True, last=last_flavor_choice)` → `popups.DisclaimerScreen` (a warning `ChoiceScreen`: **I
understand** focused, **Back**/Esc back to the picker, `svb.disclaimer_accepted` / `_declined`) → `SvReviewScreen`
(`svb.started`)). No account picker. `accepted` lives on the flow, so the warning is asked once per opening of the
tool from the menu, not on a new flavor pick or a rescan.

- `SvReviewScreen` (`review_screen.py`): `RunActions`, `TreeFilter` and `ReviewBase`, `two_pane_css`. Left pane
  `#filters`, one control per row: the shared `RiskBanner` (D37), the `FilterBar` (filter box and **Filter** button), the multi-line `#pending` line
  (`Staged: N edits in F files`, then after a search the Results count, `Ticked: M results`, the cap line and the
  unreadable files), `ButtonRow#search-row` (**Search**, `S`, navigate; its own row so
  `#actions` stays the four-button row of every tool), `#actions` (**Apply** destructive `w`, **Dry run** simulate
  `y`, **Rescan** `r`, **Undo last change** revert `z`) and the `NavHint`. Right: a `BarTree` (`#browse`) over an
  `ActionBar` of `TREE_ACTIONS`: **Edit value** (`e`, overwrite), **Rename key** (`k`, overwrite), **Delete key**
  (`d`, destructive), **Unstage** (`backspace`, cancel), **View** (`v`, navigate), enabled in Browse from the
  highlighted node's D5 flags and the staging's checks; in Results Edit value and Rename key act on `bulk_targets()`
  (the ticked hits, else the highlighted one), Delete key is off and Unstage acts on the highlighted hit. The scan (`scan_flavors`, `latest_undoable`, `pending_recovery`) runs in a
  worker behind the shared scan box. **Browse** data: `("flavor", FlavorFiles)`, `("problem", ff, text)`,
  `("account", ...)`, `("realm", ...)`, `("owner", ...)`, `("file", SvFile)`, `("node", SvFile, Node)`; opening a
  file or table runs `doc.roots()` / `doc.children(node)` in a `load` worker (a dim "Reading…" leaf meanwhile) and
  adds the children in place; a rescan bumps `_generation` so a late load is dropped. `x` opens group kinds only
  (down to the files). The `/` filter is a `ModelFilter` over the scan plus what has been read. Marks: `→ new key`,
  `✎ new value`, `✗ deleted` (keys below it dim and struck through); every staging change relabels the tree.
  **Results** data: `("r-flavor", ...)`, `("r-account", ...)`, `("r-owner", ...)`, `("r-file", SvFile, idx)`,
  `("hit", i)` (an index into `hits`; `ticked` holds indexes); every hit ticked, groups open; Space/`a`/`n` tick
  only there (`no_ticks_here()` notifies why in Browse); a hit shows Browse's marks for its staged edit. `S` opens
  `popups.SearchScreen` (prefilled with `last_spec`) and runs `run_search` through `start_run(writes=False)` with
  `SearchProgressScreen`; a new search replaces the results without asking (ticks only select). `e`/`k`/`d` open
  `EditValueScreen`, `RenameKeyScreen` (the shared `TextPromptScreen`) and `delete_confirm` (destructive, with the
  array-shift alert); in Results `e`/`k` open them titled with the count (`Edit 37 values`), `EditValueScreen(...,
  matched=True)` after a value Contains search, then `bulk.stage_values` at once or, for a rename, `bulk.read_tables`
  in a `start_run(writes=False)` worker ("Reading" row, `_read_tables_then`) then `bulk.stage_renames`; Backspace on
  a renamed hit reads its table the same way before `unstage_hit` (never on the event loop); the `BulkResult` text is the
  notice and the Results view stays, ticks kept. Apply / Dry run build the plan once (`staging.plans()`), then: a waiting marker → recovery first, the
  backup-folder check, the WoW check over the plan's flavors (`run_preflight`), `ConfirmScreen(..., groups=
  report.apply_groups(plan))`, and `start_run` with `editor.apply_plan` and `RunProgressScreen` (ids `svb-*`). Undo
  checks the journal's flavors and confirms (destructive, with the disclaimer and the staged work it drops). A
  real Apply or Undo drops the staging (`_set_stale`) and rescans when the result screen is left; a crash or a
  recovery rescans at once (`_mark_stale`). A scan that finds a marker offers the shared `UnfinishedRunScreen`
  (only while the review is the shown screen, else on resume), settled in the folder the marker was read from.
- `popups.py`: `DisclaimerScreen`, `EditValueScreen` (`title`; with `matched` a first `#edit-mode` select, Replace
  only the matched text / Whole value; a type `NavSelect`, then an `Input` or a `PopupCheckbox`), `RenameKeyScreen`
  (`title`), `delete_confirm`, `SearchScreen` (find only, D38: one labelled control per row, a blank row between
  the key pair and the value pair; the box scrolls at 80x24) and
  `PopupCheckbox` (Space ticks, Enter presses the popup's OK / Find). All styled with the shared `popup_css`.
- `SvResultScreen` (`result_screen.py`): the shared `ResultScreen` with `report.summary_rows` and `file_rows` (or the
  shared undo rows); Rescan, Other flavor, Tools, Quit, plus a focused **Back to review** (Esc) after a dry run or an
  Apply refused before it wrote anything, which keeps the staged edits and ticks.
