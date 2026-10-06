# Saved Variables Browser — status ledger

Plan: `2026-10-06-sv-browser.md`. Spec: `../specs/2026-10-06-sv-browser-design.md`.
Branch: `feat/sv-browser`. Resume at the first task not marked `done`. Update this file and commit it after every
task; push after each milestone. Never merge without the user's go-ahead. At the end of the run, after the merge,
delete every branch, stash and worktree this run created.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| T0.1 | branch, spec, plan, ledger | done | (this commit) | user answers 2026-10-06: per-search key toggles, whole/contains value match, values+rename+delete, scope filters + ticked results; same backup/journal/undo set as every tool; name `sv-browser`, display "Saved Variables Browser" |
| T1.1 | luasv to core + parser surface | done | (this commit) | `luasv.py` git-mv'd to `wowtools/core/` (Ace3 modules + tests switched, `tests/test_ace_luasv.py` -> `tests/test_luasv.py`), added `parse_at`, streaming `iter_scalars`, `encode_value`/`encode_key`/`key_id`, the `-- [n]` remove-span fix and slotted dataclasses; no Ace3 assertion changed; full suite 1357 OK (2 skipped), +23 tests |
| T1.2 | SvFile/walk/tool_root to core | done | (this commit) | `SvFile`, `sha256_of`, `OWNER_ACCOUNT_WIDE`, `candidate_files`, `under_link` and a generic `walk_sv_files` (filter hook `is_sv_file`/`is_addon_sv_file`) now in `core/svfiles.py`, Ace3 scanner/editor/ops/review/tree_view import them from core, `core.journal.tool_root` adopted by Ace3 `resolve_root` and Interface Backup `resolve_backup_root` (WTF Cleaner kept), structure pin added; no Ace3 assertion changed; full suite 1365 OK (2 skipped), +8 tests |
| T1.3 | write pipeline, journal, undo to core | done | (this commit) | Ace3's generic apply/multi/journal/undo/verify/report moved to `core/sv_apply.py`, `sv_journal.py`, `sv_undo.py`, `sv_verify.py`, `sv_report.py` and `sv_events.py` (`SvTool(name, prefix)`, `sv_events(prefix)`), Ace3 `editor`/`multi`/`journal`/`undo`/`report` are thin wrappers and `verify` uses the core helpers, one `WowRunning`, `docs/events.md` byte-identical (`gen_event_docs.py --check`), structure pin added, 4 patch targets moved, no Ace3 assertion changed; full suite 1376 OK (2 skipped), +11 tests |
| T1.4 | shared UI helpers | done | (this commit) | `popup_css`/`show_error`, a generic `TextPromptScreen` (Ace3 `NameScreen` built on it) and `UnfinishedRunScreen` (Ace3 `ProfileRecoveryScreen` built on it, its text now `core.sv_report.recovery_text`) in `ui/dialogs.py`, and a `RunActions` mixin in `ui/review.py` (WoW check, running/backup-dir refusals, `start_run` = busy + progress popup + worker in `activity.running()` + done/failure) that Ace3's review now uses (its `_close_progress(screen)` shadow gone), structure pin added and the progress-close pin narrowed to `ui/review.py`; no Ace3 assertion changed; full suite 1390 OK (2 skipped), +14 tests |
| M1 | push milestone 1 | done (pushed) | 0ac3786 | review fixes: Ace3 `TargetScreen` gets `popup_css(..., list_rows=ACTIONS_ROWS)` back (its Select dropdown is an OptionList, max-height 16 again), pinned in `test_look_and_feel`; full suite 1391 OK (2 skipped) |
| T2.1 | package skeleton, registry, fixture | done | (this commit) | `wowtools/tools/sv_browser/` (events with 9 own `svb.*` + `sv_events("svb")`/`SV_TOOL`, `[sv_browser]` settings + `resolve_root`, help stub, settings form, `SvBrowserFlow` flavor picker with All flavors and no account picker -> placeholder `SvReviewScreen`), registered last in `TOOLS`, `build_sv_tree` + `SVB_*` texts in fixtures, README rows + placeholder `docs/sv-browser.md`, `docs/events.md` regenerated; full suite 1402 OK (2 skipped), +11 tests |
| T2.2 | scanner + lazy model | done | (this commit) | `scanner.py` lists every flavor's SavedVariables files (`walk_sv_files` + `is_sv_file`: Blizzard_* in, .bak/.old/links out) as flavors > accounts > owners > `SvFile` (size, mtime, no read, `sha256=""`), recovers probe leftovers first and logs one `svb.scan_completed`; `model.py` `SvDocument` reads a file once (sha256 then), parses one level ahead (`parse` / `parse_at` on the table's span), `Node` with typed key, spans, path, remove span and D5 flags, 500-child cap with a `… N more` leaf, error nodes instead of raising, plus `key_text`/`scalar_text`/`table_text`/`node_text`; full suite 1430 OK (2 skipped), +28 tests |
| T2.3 | search | done | (this commit) | `search.py`: `SearchSpec` (+`problems()`/`check()`, `SearchScope` flavor/account/character-or-`Account-wide`/addon-contains, replacement typed or None = find only), `parse_replacement` (strict Lua decimal that reads back exactly, int within 2^53, true/false), `_Matcher` per D6-D8, byte pre-filter `may_hold`, `search_file` (streams `iter_scalars`, never raises: unreadable/not-Lua logged `svb.file_unreadable`), `run_search` over `run_units` with `progress(done, total, file)`, `HIT_CAP` 10,000 + `dropped`, `svb.search_started`/`_completed`; full suite 1490 OK (2 skipped), +60 tests |
| T2.4 | staging, compile, verify | done | (this commit) | `ops.py` `Staging` (set/rename/delete/unstage on model nodes with every D5 refusal, duplicates by `key_id` counting staged renames/deletes and array-index shifts, delete drops the edits inside it) and `plans(hits)` -> `Plan` of one `FilePlan` per `SvFile` (sha of load/search) with D12 overlap rules (`DroppedHit` reasons), `compile.py` `compile_file` (re-locates every target by typed path in the bytes Apply read, parse limited to touched tables, value/key/remove-span splices, problems instead of raising) and `verify.py` `verify_edit` per D19 on the core helpers (touched tables found by their new keys); full suite 1540 OK (2 skipped), +50 tests |
| T2.5 | apply/undo/recovery wiring | done | (this commit) | `editor.py` (`flavor_plan` groups a `Plan` by flavor in plan order, `apply_flavor` = core `apply_flavor` with `compile_file`/`verify_edit` and `started` files+edits, `apply_plan` = core `apply_flavors` under one journal), `journal.py` (`SV_TOOL.journals` wrappers, `read_journal`), `undo.py` (`undo_run`, `recover`, `pending_recovery`, `leave`; core `UndoResult`), `report.py` (`DISCLAIMER`, `apply_confirm`/`undo_confirm` with it as alert lines, `summary_rows`, per-file `file_rows`/`FILE_COLUMNS`) with end-to-end tests on `build_sv_tree` (exact bytes over two flavors, staged+hits in one run, snapshot/originals zip members, journal, keep_journals/keep_backups pruning, dry run, WoW running, D17 skip, verify stop, roll-back, undo byte-identical and changed-since, crash -> marker -> put back / leave, new Apply refused while a marker waits), structure pins extended; no event registry changed; full suite 1566 OK (2 skipped), +26 tests |
| M2 | push milestone 2 | done (pushed) | 8f642d0 | review fixes: a value of blanks is a needle (`has_value` = non-empty), `luasv.decode_string` reads Lua 5.1 escapes (`\x41` = "x41", `\z` = "z"), the pre-filter takes `\\` pairs out before looking for a hiding escape, `compile.FieldIndex` (dict per table) + verify edits grouped per table (4000 edits: 12 s -> 0.5 s), search keeps about `HIT_CAP` hits at a time (`_Room`: per-file room + trim of searched files), opening a table builds only its shown child tables; full suite 1574 OK (2 skipped) |
| T3.1 | flow, disclaimer, Browse view | done | (this commit) | `popups.DisclaimerScreen` (warning `ChoiceScreen`, I understand/Back, Esc = Back) once per opening of the tool, `svb.disclaimer_*`/`svb.started` logged, real two-pane `SvReviewScreen` (banner, filter, pending line, Search row + Apply/Dry run/Rescan/Undo row, NavHint; lazy Browse tree loaded in workers with the child cap, red unreadable rows, x to file level, `/` on loaded labels, bar Edit value/Rename key/Delete key/View enabled per D5 flags, leave/rescan with staged edits confirm), `BarTree`/`ActionBar` moved from Ace3 to `ui/review.py`, sv-browser in `test_look_and_feel.TOOLS` with `NO_RUN` (and `test_help.NO_RUN`), `fixtures.accept_disclaimer`; full suite 1586 OK (2 skipped), +12 tests |
| T3.2 | edit/rename/delete popups, staging UI | done | (this commit) | `popups.py` `EditValueScreen` (type NavSelect string/number/boolean, Input or `Ka0sCheckbox`, `parse_replacement` + staging check inline), `RenameKeyScreen` (shared `TextPromptScreen`, keys typed as the tree shows them via `ops.parse_key`/`key_input`) and `delete_confirm` (destructive, entry count, dropped inner edits, `SHIFT_WARNING` alert) wired to e/k/d; marks `→ name`, `✎ value`, `✗ deleted` (dim strike below a delete), an **Unstage** (Backspace) button on the bar, `ops.Staging.set_problem`/`rename_problem`/`delete_problem`/`staged_inside` and equal-value no-ops; full suite 1607 OK (2 skipped), +21 tests |
| T3.3 | search popup, Results view | done | (this commit) | `popups.SearchScreen` (one labelled control per row: key + Exact/Contains, value + Whole value/Contains, Match case, Flavor (only with several flavors scanned)/Account/Character incl. Account-wide only/Addon file, Replace with String/Number/Boolean/Find only + text or checkbox; Find = `parse_replacement` + `SearchSpec.problems()` inline, prefilled with the last search, box scrolls at 80x24), `S` runs `run_search` through `RunActions.start_run(writes=False)` with `SearchProgressScreen` (`[general] parallelism`), Results view flavor › account › owner › file › `path = old → new` leaves all ticked (space/a/n, `/` on every hit, hidden-ticked note), `v` rebuilds the view (sub-title), new search over ticks asks (destructive), pending line adds Results/cap/unreadable/left-out lines and leaves show `⚠ left out: <reason>` from `Staging.plans(ticked)`, help text; full suite 1624 OK (2 skipped), +17 tests |
| T3.4 | apply/dry run/undo/recovery UI, result, help, look-and-feel | done | (this commit) | w/y/z wired on `RunActions` (`_start` → `staging.plans(ticked)`, WoW check per plan flavor via `check_for`, destructive/simulate confirm from `report.apply_confirm` + new `apply_groups` detail tree per flavor/file, disclaimer and the WoW-unknown alert as red lines; Undo confirm with the disclaimer and the dropped staged work), `RunProgressScreen`, `result_screen.SvResultScreen` (Back to review after a dry run), rescan after Apply/Undo (`_stale`), the shared `UnfinishedRunScreen` offered by every scan that finds a marker and by Apply (put back / leave), full `help.py`, `STATUS_COLOURS` moved to `core/sv_report.py`, sv-browser in `test_help`/`test_look_and_feel` RUN_ACTION/PREPARE (`fixtures.stage_sv_edit`) and `NO_RUN` gone, new `tests/test_sv_browser_run_ui.py` (search → apply → files, snapshots, originals zips, journal → undo byte-identical); full suite 1632 OK (2 skipped), +8 tests |
| M3 | push milestone 3 | done (pushed) | a9ea0da | review fixes: Enter on a popup checkbox presses OK / Find (Space ticks), → on Search goes to the tree, Edit value starts from a staged value, Space/a/n say why in Browse or after a find only, Delete off on a key staged for delete, an Undo or Apply refused before writing keeps the staged work (refused Apply result goes Back to review), recovery warns about the staged work it drops, is offered only on the review (deferred past Help/Settings) and settled in the folder its marker was found in, a stale load keeps the new load's guard, tests (Undo refused while WoW runs, ElvUI doc in the equal-value test, a replacement in no fixture); full suite 1642 OK (2 skipped) |
| T4.1 | docs | done | (this commit) | full guide `docs/sv-browser.md` (risk section first, browse/edit rules table, search fields/replacement/Find only/results/left-out, Apply/Dry run/Undo/safety net/backup paths/recovery, WoW running, settings, keys, FAQ, troubleshooting, screenshots placeholder), README prose to five tools + tests badge, architecture (`luasv` core row, review row with `BarTree`/`ActionBar`/`RunActions(writes=)`/`no_ticks_here`, `[sv_browser]` config, new SV Browser data flow + screens sections), adding-a-tool shared SavedVariables stack bullet, CHANGELOG 0.1.0 Added groups, CLAUDE.md tool/core/UI lists, spec Addendum A D22-D36, events.md unchanged; full suite 1643 OK (2 skipped), +1 tests |
| T4.2 | review, fixes, push, ask for merge | done (pushed; awaiting merge go-ahead) | e6f03f0 | whole-branch review over 4 lenses: 10 claims, 7 confirmed and fixed, 3 rejected on verify; full suite 1647 OK (2 skipped), ruff clean, events.md up to date |
| M4 | push milestone 4 | todo | | review fixes: a file must parse whole before compile splices it (a deep parse fault stops Apply, D4), ticked hits whose replacement is the value already there left out as `UNCHANGED` (D29), Addon file scope matches the file name (`ElvUI.lua`), `SvScanWarning` shared in `core/svfiles.py`, docs (`core/sv_undo._moved_zip()`, architecture shared-module users, parallelism per search file in README/help); full suite 1647 OK (2 skipped) |

## Decisions taken during the build
- **T1.1** `iter_scalars(data, descend)` yields `(path, key, key_span, Scalar)` where `path` is the *containing*
  table's path (the same tuple `descend` gets, raw Python-typed keys); a top-level `Name = scalar` yields `path=()`,
  key = the name, key span = the name's bytes; positional entries have key = index and `key_span=None`. It walks with
  an explicit stack (no recursion, no Table/Field objects): ~2x faster than `parse` (16.7 MB, 900k scalars: 4.4 s vs
  9.5 s on WSL).
- **T1.1** `_Parser` refactored so `table()` and the stream share `scalar()`, `key()` and `separator()`; a table used
  as a key (`[{}] = 1`) still raises "bad table key" at the `[`.
- **T1.1** `parse_at(data, start, path=(), descend=all)` skips blanks/comments before `start`; `descend` is asked
  about `path` first (pass `lambda p: len(p) <= len(path)` for one level).
- **T1.1** `key_id(k)` = `(type name, value)`, except an integral float folds to `("int", n)` (Lua 5.1 folds `[1.0]`
  into `[1]`); `Table.get` is unchanged (Ace3 behaviour).
- **T1.1** `encode_value` refuses nil (`ValueError`: a nil set is a delete) and non-scalars (`TypeError`);
  `encode_key` = `[` + `encode_value` + `]`, so it refuses nil/inf/nan the same way.
- **T1.1** Remove-span fix: `_LINE_REST` takes an optional trailing line comment, never one starting a long comment
  (`--[[`/`--[=[`), which could run past the line.
- **T1.1** `slots=True` on `Scalar`, `Opaque`, `Field`, `Table`, `Assignment`, `Chunk` (Ace3 sets no extra
  attributes on them); `RawNumber` stays frozen without slots (frozen+slots pickling bug on early 3.10).
- **T1.1** `tests/test_structure.py::test_saved_variables_reader_lives_in_core` pins the one `luasv.py` and every
  parser function/class to core; `docs/architecture.md` paths updated now (the rest of the docs is T4.1).
- **T1.2** `walk_sv_files(flavor, *, account, accept, on_error, on_account, on_link)` is a generator of
  `(Account, Character | None, path)` (the `Account` object, not just its name, so a caller has `.name` and `.path`);
  `on_account(acct, characters)` fires before an account's files, so Ace3 still gets an `AccountScan` (with its
  character keys) for an account with no files; the "no WTF/Account folder" error stays in Ace3's `scan_flavor`.
- **T1.2** Filters: `is_sv_file` (exactly `.lua` with a name before it; never `.lua.bak`/`.old`; the default, for SV
  Browser) and `is_addon_sv_file` (also not `Blizzard_*`; Ace3). `candidate_files(sv_dir, accept)` never takes a link
  or a folder.
- **T1.2** The owner constant is `svfiles.OWNER_ACCOUNT_WIDE = "Account-wide"`, not `ACCOUNT_WIDE`, because
  `core/install.ACCOUNT_WIDE = "account-wide"` (WTF Cleaner) already exists with another value. Ace3's
  `scanner.SvFile`/`scanner.sha256_of` stay importable (the scanner imports them), so the Ace3 tests that use
  `scanner.SvFile` / `scanner.sha256_of` are untouched; Ace3 production modules import them from core.
- **T1.2** `tool_root(backup_dir, wow_path, tool)` lives in `core/journal.py` next to `TOOLS_SUBDIR` and
  `journal_dir` (`core/paths.py` would import journal, which imports paths: a cycle). Ace3 `resolve_root` and
  Interface Backup `resolve_backup_root` are now one-line wrappers (callers and tests unchanged). The WTF Cleaner's
  `resolve_backup_dir` is left alone: a set `backup_dir` is used as-is, with no `wtf-cleaner` subfolder, so it is not
  the same behaviour. `test_saved_variables_files_and_tool_root_live_in_core` pins the definitions and that only
  `wtf_cleaner/settings.py` among tools still uses `TOOLS_SUBDIR`.
- **T1.2** `ruff check .` panicked on a stale cache (`wrong package cache for file`); `ruff check --no-cache .` passes.
- **T1.3** Module split: `core/sv_events.py` (`SvTool(name, prefix)` with `.event(short)` and `.journals` = its
  `ToolJournals` over `read_edit_journal` and `<prefix>.journal_pruned`; `sv_events(prefix)` = the 31 shared event
  specs, texts and levels exactly Ace3's), `core/sv_journal.py` (`EditJournal`, `read_edit_journal`,
  `record_recovered`, `referenced_zips`), `core/sv_apply.py` (per-flavor `apply_flavor` + multi-flavor
  `apply_flavors` + `prune_edited_zips`, marker, results, errors), `core/sv_undo.py` (`undo_run`, `recover`,
  `destination`), `core/sv_verify.py` (`gaps`, `check_assignments`, `rest_outside`, `same_outside`), `core/sv_report.py`
  (stage titles, `undo_confirm`, apply/undo summary and detail rows, `in_backup_folder`). Ace3's events.py registers
  its 8 own events plus `sv_events("ace")` and exports `SV_TOOL`.
- **T1.3** Core API: `apply_flavor(tool, flavor, units, compile, verify, *, ..., started=)` takes `(SvFile, payload)`
  units, one per file; `compile(file, payload, bytes)` returns an edit with `.data` and `.changes`; `verify(edit,
  bytes)` returns problems. `started` holds the `apply_started` fields (Ace3 passes `databases=len(states)` so its
  log is unchanged; the default is `files=`). `apply_flavors(tool, plan, apply_one, ...)`: the tool passes its own
  per-flavor function (Ace3 a lambda that looks `multi.apply_flavor` up per call, so tests can still patch it there).
  `undo_run(tool, journal_path, ...)` / `recover(tool, marker, ...)`; Ace3's are `**options` wrappers.
- **T1.3** One `WowRunning(ApplyError, UndoError)` in `core/sv_apply.py` (`UndoError` lives there too to avoid a
  cycle; `sv_undo` re-exports both). Its text keeps each side's wording through `what` ("changes" for Apply, "files"
  for Undo/recovery); `refuse_running(tool, wow_check, action, what)` logs `<prefix>.wow_running`.
- **T1.3** Moved patch targets (patch strings only, no assertion changed): `ace3_profile_manager.editor.restore_original`
  and `.editor.write_marker` -> `wowtools.core.sv_apply.*` (test_ace_editor, test_ace_undo);
  `ace3_profile_manager.journal.read_profile_journal` -> `wowtools.core.sv_journal.read_edit_journal`
  (test_ace_multi); `patch.object(undo, "take_snapshot")` and `undo.BackupError` / `undo.SNAPSHOT_SUBDIR` ->
  `sv_undo.*` (test_parallel_runs). `editor.verify_edit` and `multi.apply_flavor` stay patchable where they were.
- **T1.3** Ace3 wrappers re-export the moved names (`__all__` in editor/journal/multi/undo, a `noqa: F401` import in
  report) so review_screen and the tests import them unchanged. Ace3 `verify.verify_edit` keeps its AceDB checks and
  uses `check_assignments(..., on_planned=)` + `rest_outside`, problem order unchanged. `apply_detail_rows` /
  `DETAIL_COLUMNS` (Flavor, Account, Addon, Change, Result) moved to core as generic (SvFile fields only).
  `test_saved_variables_write_pipeline_lives_in_core` pins the definitions; the marker-importer pin now names
  `core/sv_apply.py` instead of Ace3's editor. A made-up tool (`tests/test_core_sv_pipeline.py`, prefix `tsv`, owner
  `test-sv-pipeline`, skipped by gen_event_docs) drives apply, dry run, verify stop, undo, recovery and WowRunning.
- **T1.4** `RunActions` (ui/review.py) is a separate mixin, not part of `ReviewBase`: only the SavedVariables reviews
  use it (mixed in before `ReviewBase`). The screen supplies `SV_TOOL` (the event prefix: `<prefix>.wow_running`, and
  `<prefix>.apply`/`.undo`/`.recover` as the `log_exception` context, so Ace3's log is unchanged), `cfg`,
  `run_backup_dir()`, `_refresh_buttons()` and `_mark_stale()`. `start_run(progress, work, done, *, name, failure,
  stale_on_crash, expected)`: `work` is a closure (the tool's own core call with its progress callbacks), `expected`
  errors (ApplyError/UndoError) show their message and never mark stale; others show `<failure>: <type>: <msg>`.
  `done(result)` runs after the popup is closed and `app.busy` is off (as Ace3 did).
- **T1.4** Ace3's `_close_progress(screen)` shadow is gone: the run's popup is `ReviewBase._progress_screen`, set by
  `start_run`; `RunActions._end_run()` = busy off + `_close_progress()`. `_applied`/`_undone`/`_recovered` now take
  only the result; Ace3's `_apply_worker`/`_undo_worker`/`_recover_worker`, `_check_wow`, `_refused_while_running`,
  `_backup_dir_refused` and `_run_failed` are gone (no test called them).
- **T1.4** `popup_css(screen, *, list_rows=None)`: the OptionList max-height rule is only emitted with `list_rows`
  (Ace3's `ActionsScreen` passes `ACTIONS_ROWS`); Target/Name popups had that rule with no OptionList. `NameScreen`
  inherits `TextPromptScreen`'s CSS (Textual type selectors match subclasses); its field and error ids changed from
  `#name`/`#name-error` to `#prompt`/`#prompt-error` (no test queried them).
- **T1.4** The unfinished-run body moved to `core/sv_report.recovery_text(marker)` (UI-free, re-exported by Ace3's
  `report`); `UnfinishedRunScreen(message, marker=None)` keeps `.marker` and the title `TITLE`. Tests: toy
  `ToyRunReview` (prefix `tur`, owner `test-ui-run`, skipped by gen_event_docs) in `tests/test_ui_review.py`, the
  popups in `tests/test_ui_shared_screens.py`, `recovery_text` in `tests/test_core_sv_pipeline.py`, pin
  `test_saved_variables_ui_helpers_live_in_ui`.
- **M1 review**: 1 finding, 1 fixed, 0 rejected: T1.4 dropped the OptionList max-height rule from Ace3
  `TargetScreen` (its NavSelect overlay is an OptionList, so the T1.4 note "Target/Name popups had that rule with no
  OptionList" was wrong for TargetScreen); restored with `list_rows=ACTIONS_ROWS`, test
  `test_ace_target_dropdown_shows_as_many_rows_as_the_actions_menu`.
- **T2.1** Own events (spec §6, levels fixed): `svb.started`, `svb.disclaimer_accepted`, `svb.disclaimer_declined`,
  `svb.scan_completed`, `svb.search_started`, `svb.search_completed` (info), `svb.file_unreadable` (warning; also
  covers a file that is not readable Lua), `svb.staged`/`svb.unstaged` (debug, as `ace.staged`); the shared
  pipeline's 31 under `svb.` via `sv_events(SV_TOOL.prefix)`. The spec's `svb.file_failed` is the shared
  `svb.write_failed`/`svb.verify_failed` (no separate event).
- **T2.1** `SvBrowserSettings(backup_dir, last_flavor_choice)`; `last_flavor_choice` None = never chosen (as Ace3),
  written only when set; `resolve_root` = `tool_root(backup_dir, wow_path, "sv-browser")`. The settings form
  (`SvBrowserSettingsScreen`, backup folder only, `validate_backup_dir`) lives in `app.py` like Ace3's.
- **T2.1** M3 placeholders: `review_screen.SvReviewScreen(flavors, label)` names the pick and has one **Back**
  (`cancel`, Esc) button; `f`/Esc flavors, `t` tools, `q` quit; no disclaimer yet (T3.1). `help.py` describes only
  what this build does (T3.4 writes the full text); `docs/sv-browser.md` is a placeholder with the risk warning
  (T4.1). README got the tools row, guide link and `config\sv-browser.cfg` row now (test_docs needs them).
- **T2.1** Meta-tests: `test_help.PLACEHOLDER_REVIEW = {"sv-browser"}` skips the run/confirm/result leg of
  `test_h_on_every_screen_of_a_tool_opens_its_help` and expects a one-row footer at TINY in
  `test_every_footer_key_shows_at_tiny` (T3.4: add `RUN_ACTION["sv-browser"]` and empty the set);
  `test_look_and_feel.TOOLS` stays at four with a comment (T3.4 adds sv-browser plus RUN_ACTION/PREPARE); its menu
  checks already iterate the registry and pass with five tools at 120x30 and 80x24. `test_structure`'s screen-module
  count 6 -> 7 (the new `review_screen.py`).
- **T2.1** `build_sv_tree(root)` is a separate install (like `build_ace_tree`); `SVB_FONT = "Friz Quadrata TT"` is a
  value in 5 files over both flavors; Bartender4.lua has it in lower case only (a case-insensitive hit);
  `ElvVersion = nil` / `DetailsVersion = 4` are top-level scalars; Questie per-character has a table array entry.
- **T2.2** Scanner shape: `ScanResult.flavors` -> `FlavorFiles(flavor, accounts, warnings, error)` ->
  `AccountFiles(name, owners)` -> `OwnerFiles(character, files)` (`label` = `Account-wide` or `Realm/Name`; only owners
  with files; every account `walk_sv_files` reports is listed, even one with none). `scan_flavors(flavors, *,
  progress=(flavor, i, n, label))` reports per flavor; the scan never reads a file, so `SvFile.sha256` is `""` until
  the model or the search reads it (D17's hash is `SvDocument.sha256`). Probe leftovers are recovered before the walk in
  every SavedVariables folder not under a link, logged as the shared `svb.probe_recovered`. `svb.scan_completed`
  fields: flavors, accounts, files, bytes, warnings, seconds; `svb.file_unreadable` for an unreadable folder/file
  (flavor, path, error).
- **T2.2** Lazy model parses **one level ahead** so every shown table knows its size (`key {N}`): file load =
  `parse(data, len(path) <= 1)` (top-level tables built, their entries' tables Opaque); opening a node at path length L
  = `parse_at(data, start, path, len(p) <= L + 1)` on its span only (the node's `value` becomes that Table). A
  20,000-entry 5 MB file loads its top level well under the 3 s test bound (~0.1 s). Faults deeper than the parsed
  level are found only when that table is opened (`skip_table` only matches braces): it gets one error child, the rest
  of the file stays browsable; a file whose top level fails is one error root (`doc.error`).
- **T2.2** `Node` (slots, identity equality): kind `value`/`more`/`error`; `typed_key` (= `luasv.key_id`; a property
  named `key_id` broke the single-definition pin in `test_structure`), `key_span` (top-level: the name; positional:
  None), `value` (Scalar/Table/Opaque), `path` (top-level name first), `parent`, `remove_span` (Field's), `count`.
  D5 flags: `can_edit_value` = any scalar (top-level and nil included), `can_rename` = below top level and a written
  key (`[1] = x` may be renamed, `x, -- [1]` not), `can_delete` = below top level; more/error nodes allow nothing.
  The cap applies to top-level assignments too.
- **T2.2** Display text is plain text (the UI must not render it as markup: `[5]` is a key): `key_text` = string
  keys bare (escaped; `[""]` for empty), others `[5]`/`[true]`/`[2.5]`; `scalar_text` = strings double-quoted with
  Lua-style escapes (`\"`, `\\`, `\n`, control/invalid-UTF-8 bytes as `\ddd`) cut to `VALUE_WIDTH` (60) characters
  with `…`, numbers as written (raw bytes), `true`/`false`/`nil`; `table_text` = `{1,234}` or `{…}` unparsed;
  `node_text` = `key = value`, `key {N}`, `… 1,500 more`, `can't read: …`.
- **T2.3** `Hit(file, path, key_span, value_span, old, old_bytes, new, new_bytes)`: `file` is the scanned `SvFile`
  `dataclasses.replace`d with the SHA-256 of the bytes searched (one object per file, shared by its hits; hashed only
  when the file has hits), `path` = top-level name then raw typed keys ending in the hit's key (same tuple as
  `model.Node.path`), `typed_path` = `key_id` per key; `key_span` None for a positional entry. Hits come in
  file-list order, then file order, whatever the parallelism.
- **T2.3** `replacement=None` is a **find only** search (`spec.replaces` False; hits have `new`/`new_bytes` None),
  so the UI may search without a replacement; T2.4 staging must ignore such hits. A Contains hit whose replacement
  equals the needle is still a hit (no-op splice).
- **T2.3** Matching details: key text of a number key = its written text inside the brackets (`[2.50]` "2.50",
  `[0x10]` "0x10"), positional entries by `str(index)`; value Whole for numbers/booleans = written bytes; nil is a key
  hit (top-level `ElvVersion = nil`, array nil slots) but never a value hit; case off = `casefold()` for Exact/Whole
  (so "STRASSE" whole-matches "Straße") and `re.IGNORECASE` for Contains; the Contains replacement goes through a
  function (never a `re` template). Key/value "given" = not blank after strip; the text itself is matched unstripped.
- **T2.3** Pre-filter (`may_hold`) is stricter than the brief: besides unsafe needles (quote, apostrophe, backslash,
  control char; a digits-only **key** needle, since array indexes are never written; non-ASCII with case off), it is
  skipped for any file holding an escape that could write a plain char another way (`\ddd`, `\x`, `\z`, `\F`;
  regex `\\[^\\"'abfnrtv\r\n]`), and with case off for any file holding a non-ASCII char that folds into ASCII
  (`FOLDS_TO_ASCII`, 20 chars such as U+212A Kelvin and U+017F long s, pinned by a test that recomputes it). So the
  fixture's Details.lua (`\226\128\148`) is always parsed.
- **T2.3** A file with a parse fault is reported in `SearchResult.unreadable` and its earlier hits are dropped (D4:
  a broken file is never edited); a file skipped by the pre-filter is not parsed, so a broken one is only reported
  when its bytes could hold the needle. Per-file hits are capped at `HIT_CAP` too (extra counted), so one huge file
  never holds more than the cap in memory. The streaming guard is a 6 MB, 20,000-entry generated file (time bound
  15 s; ~0.5 s here); no memory measurement (tracemalloc slows the parse several-fold).
- **T2.4** Staging API takes the model's `(SvDocument, Node)`: `set_value`, `rename`, `delete`, `unstage` return an
  `OpResult(ok, message, warning, dropped)` (`warning` = `SHIFT_WARNING` for an array entry, `dropped` = staged edits
  inside a deleted table); `edit_for`/`deleted_above` for the T3.2 marks; `count`, `files()`, `clear()`. One
  `FieldEdit(path, set_value, value, rename, new_key, delete, positional, hit)` per key (flags, since `False` is a
  valid key/value), keyed by typed path in the old file's coordinates; `svb.staged` (operation, flavor, path, key) /
  `svb.unstaged` logged.
- **T2.4** Edits under a staged delete are dropped **when the delete is staged** (not at plan time) and new ones
  there are refused, so a plan never holds both; a delete replaces a set/rename on the same key. Setting the bytes
  already written (`encode_value(v) == old bytes`) or renaming to the same key drops that part (no no-op edits). A
  rename is refused when the table would then hold a key twice that it does not now (`ops.new_duplicates` over
  `new_keys`: staged renames, deletes and array-index shifts counted); `unstage` is refused for the same reason
  (unstaging a rename's victim). Empty string keys are refused (spec §5 rename popup); a number key must pass
  `search.number_problem`.
- **T2.4** `plans(hits)`: find-only hits are ignored; a hit on a key with a staged set (or another hit) is dropped
  (`HAS_STAGED_EDIT` / `DUPLICATE_HIT`), on or under a staged delete `UNDER_DELETE`; a hit on a key that is only
  renamed **combines** (rename + the hit's value, `hit=True`), the staging itself unchanged; a hit whose sha differs
  from the file's staged sha is dropped `FILE_CHANGED` (the staged edits win). `Plan.files` is keyed by
  `replace(file, sha256=<sha of load/search>)`; `Plan.units()` feeds `sv_apply.apply_flavor` (checked by a dry-run
  test).
- **T2.4** `compile_file` returns `SvEdit(file, data, changes, plan, spans, problems)`: a plan that does not fit the
  bytes (key missing or there twice, top-level rename/delete, array rename, set on a table, edit inside a deleted key,
  a rename leaving a duplicate, overlapping splices) is not spliced and its problems are what `verify_edit` returns,
  so the shared `_prepare` stops with "the change did not check out" instead of a crash. `spans` pairs each old span
  with its new span for `same_outside`. Change lines: `ElvDB › profiles › font: "a" → "b"`, `…: renamed to Font`,
  `…: renamed to Font, "a" → "b"`, `…: deleted (later entries move down)` (key path via `ops.path_text` with
  `model.key_text`, values via `model.scalar_text`).
- **T2.4** Verify finds each touched table in the new file by its **new** typed path (renamed ancestor, array entry
  moved down), parses old and new only down those tables, compares a set value as `(type name, value)` and every
  other entry by its old value bytes, a touched child table as "a table" (checked as its own entry). A 400-trial
  random staging run over the fixture files (scratch, not committed) compiled and verified every plan.
- **T2.5** Module names: the apply wrapper is `editor.py` (as Ace3's) holding both the per-flavor `apply_flavor` and
  the multi-flavor `apply_plan(plan, **options)` (no separate `multi.py`); `flavor_plan(plan)` groups `Plan.units()`
  by flavor in plan order (staging first, then hits), so the journal header's `flavors` follow that order. Its verify
  callback is a module-level `_verify` that looks `verify_edit` up per call, so tests patch
  `wowtools.tools.sv_browser.editor.verify_edit`. `apply_started` carries `files` and `edits`.
- **T2.5** Report names avoid the core-pinned `apply_summary_rows`/`apply_detail_rows` (test_structure's
  single-definition pin): `summary_rows(result, plan=None)` = Flavors, the shared first row (Changed / Would change),
  `Edits written`/`Edits checked`, `Ticked results left out` (from `plan.dropped`), then the shared rows (skipped, put
  back, failed, stopped, backup folder, zips, journal); `file_rows` = one row per file per spec §5 (`FILE_COLUMNS`
  Flavor, Account, Owner, File, Edits, Result). `apply_confirm(plan, dry_run)` names edits/files per flavor; alerts =
  dropped-hit note, array-entry shift note, and `DISCLAIMER` (real Apply only; a dry run writes nothing);
  `undo_confirm` = the shared one plus `DISCLAIMER`. `DISCLAIMER` is the spec D2 text, for T3.1's popup/banner too.
- **T2.5** Recovery "Leave" is logic, not UI: `undo.leave(marker, root=)` clears the marker and logs
  `svb.recovery_done` with `choice="leave"` (Ace3 does this in its review screen); `undo.pending_recovery(root)` =
  `read_marker`. No new event. `test_structure.test_tools_use_the_shared_helpers` and the write-pipeline pin now
  cover sv_browser's journal/undo/editor. A write failure in tests is injected through `editor.apply_flavor(...,
  write=)` (core `apply_flavors` passes no `write`); the crash case also patches `wowtools.core.sv_apply.restore_original`.
- **M2 review**: 6 findings, 6 fixed, 0 rejected: (1) `SearchSpec.has_value` is `value != ""` (blanks are a needle,
  never a key-only overwrite); (2) `luasv.decode_string` follows Lua 5.1: `\x`/`\z` are no escapes, an unknown escaped
  byte stands for itself (`tests/test_luasv.py`'s `\x69` case changed to `\105`; the search escape test now finds
  "x46oo"); (3) `may_hold` searches `_HIDING_ESCAPE` in the bytes with every `\\` pair removed (left-to-right pairing,
  as Lua lexes), so "Interface\\Icons" paths keep the pre-filter on; (4) `compile.FieldIndex` (assignments by name,
  each table's fields by typed key, built once per table; `locate` takes a chunk or an index) and `verify_edit` groups
  edits per parent table once; (5) `run_search` units are `(index, file)`; `_Room.room(i)` = HIT_CAP less the matches
  of searched files before i (passed to `search_file(..., room=)`, which counts the rest in `extra`), and `_Room.done`
  trims every searched file to that bound, so kept hits add up to about HIT_CAP (plus in-flight files) and the result
  is the same first HIT_CAP in file order; (6) `SvDocument.children` parses the table with its children Opaque, then
  `parse_at` on each shown (first CHILD_CAP) child table; a fault in a shown child still makes the one error child.
- **T3.1** Disclaimer: shown after the flavor pick until accepted; `SvBrowserFlow.accepted` lives on the flow, so it
  is asked again each time the tool is opened from the menu but not when the user goes back to the flavor picker and
  picks again, nor on a rescan. Back, and Esc (`ChoiceScreen(escape=True)` dismisses None), both go back to the
  picker and log `svb.disclaimer_declined`; accept logs `svb.disclaimer_accepted` then `svb.started` (flavors,
  label) as the review is pushed. Back carries `escape` as its key (D17); I understand has no key (Enter on it, the
  default). `DisclaimerScreen` lives in a new `popups.py` (spec §4).
- **T3.1** Search key is **`S`** (Shift+S), not `s`: `s` is the suite's settings key on every screen (app binding,
  `test_help` needs `s` in every review's footer). Search sits on its own `ButtonRow#search-row` above
  `#actions` (deviation from spec §5): five keyed buttons do not fit the 50-column left pane in one row, and this
  keeps `#actions` the same four-button row as every other tool (`test_review_left_pane_is_the_same_in_every_tool`).
  The hint leaves out `v view` (the View button carries `v`, D17).
- **T3.1** Scan: the shared scan box (`ReviewBase.show_scan_box`, as every review) stands in for the tree while
  `scan_flavors` + `latest_undoable` + `pending_recovery` run in a worker, not a popup (the scan reads no file and
  is quick). `marker`/`undoable` are kept for T3.4 (no recovery offer yet). `RunActions` is not mixed in yet (T3.4).
- **T3.1** Tree: data tuples `("flavor", FlavorFiles)`, `("problem", FlavorFiles, text)` (flavor error and scan
  warnings, red, under the flavor), `("account", ff, AccountFiles)`, `("realm", ff, acct, realm)`, `("owner", ff,
  acct, OwnerFiles)` (Account-wide directly under the account, characters under their realm), `("file", SvFile)`,
  `("node", SvFile, model.Node)`; `review_screen.ident(data)` keys expansion/cursor (typed path for keys). Open at
  first: root, flavors, accounts, owners (realms and files closed). Opening a file or table runs `doc.roots()` /
  `doc.children(node)` in a thread worker (group `load`) with a dim "Reading…" leaf; when done the node's children
  are added in place (no rebuild), or the tree is rebuilt while the filter is set (new labels may match). A rescan
  bumps `_generation` so a late load is dropped. The `/` filter is a `ModelFilter` over the scan plus what has been
  read (`_model()`), matched on the label text. `x` overrides `action_expand_all` to open group kinds only.
- **T3.1** Bottom line: `Selected: <place>    N files in M flavors[ · K scan warnings]`, the place being names
  down to the highlighted node (`Retail › ACCT1 › Account-wide › ElvUI.lua › ElvDB › font = "…"`). Pending line:
  `Staged: N edits · Ticked: M results in F files`. Apply/Dry run disabled until something is staged or ticked,
  Undo until a journal is undoable, View until a search ran (T3.3); Search, Apply, Dry run, Undo and the bar's
  actions notify "… comes in the next build" until T3.2-T3.4. The Browse view has no ticks (`all_tick_keys` empty).
- **T3.1** Shared UI: Ace3's `ProfileTree` (↓ on the last line to the bar) and `ActionBar` moved to `ui/review.py`
  as `BarTree` (`BAR_SELECTOR`, focuses the bar's first *focusable* button: SV Browser's may be disabled) and
  `ActionBar`; Ace3 uses them (no Ace3 test changed). A screen attribute named `_nodes` or `_name` breaks Textual
  (Widget internals): the review uses `_tree_nodes` and `_place_name`.
- **T3.1** Tests: `tests.fixtures.accept_disclaimer(app, pilot)` clicks through the warning when it is shown; used
  after every `dismiss(ALL_FLAVORS)` in `test_help` and `test_look_and_feel`. `test_look_and_feel.TOOLS` now has
  sv-browser, with `NO_RUN = {"sv-browser"}` skipping the run/confirm/result legs; `test_help.PLACEHOLDER_REVIEW`
  became `NO_RUN` and the TINY footer is two rows for every tool. T3.4: add `RUN_ACTION`/`PREPARE` and empty both
  `NO_RUN` sets. `help.py` names every review button now (test_help); T3.4 writes the full text.
- **T3.2** `ops.Staging` gained non-mutating checks `set_problem`, `rename_problem`, `delete_problem` (what
  `set_value`/`rename`/`delete` would refuse; those now call them) and `staged_inside(doc, node)`. The popups take
  them as their `check`, so a duplicate key (by `key_id`), an empty key or an inside-a-delete refusal shows inline
  under the field; the bar's Edit/Rename/Delete enable state uses them too (a key under a staged delete has them off,
  and e/k/d there notify why). `set_value` also treats a value equal by Lua identity to the one there (`12.0` for
  `12`, the same string written with other escapes) as "unchanged" (`_same_value`), so OK on an unchanged popup
  never stages a rewrite.
- **T3.2** Rename text is read like the tree writes keys (`ops.parse_key`): `[5]`, `[2.5]`, `[true]`/`[false]` are a
  number or boolean key, `["…"]` the literal string inside (no escapes, so `["[5]"]` is the text `[5]`), anything
  else a string key as typed; a number key must pass `parse_replacement` (reads back as itself). `ops.key_input`
  is the inverse (the prompt's starting text; a staged rename starts from the new key).
- **T3.2** Edit value starts on the current type (nil starts as an empty string): a number shows its written text,
  a string its text, a boolean the checkbox; a string with control characters or bytes that aren't UTF-8 starts
  empty with a note (`NOT_TYPABLE`), since an Input can't hold them.
- **T3.2** Deviation (spec §5 bar): the bar has a fifth button, **Unstage** (`cancel`, key `backspace`, as Ace3's
  Discard), enabled only on a key with a staged edit (D17: Backspace on a button rather than in the footer/hint).
  Marks follow the label: `  → new key`, `  ✎ new value` (warning colour, both when renamed and set), `  ✗ deleted`
  (error colour); keys below a staged delete are dim and struck through. Every staging change relabels the whole
  tree (`_refresh_labels`) and updates the pending line and buttons.
- **T3.2** Tests: `tests/test_sv_browser_edit.py` (pilot): two clicks on one button in a row within a test are read
  as a double click and the second press is lost, so the error-loop cases submit with Enter in the field.
- **T3.3** Search popup: one row per control, a dim label column (13) then the control (compact Input/NavSelect/
  Ka0sCheckbox), the scope and replacement groups a blank line apart; the `.popup-box` scrolls (popup_css) and ↑/↓
  move focus, each field scrolled into view, so it works at 80x24 without a FormScroll. The replacement select has a
  fourth choice, **Find only** (`popups.FIND_ONLY`, spec `replacement=None`, T2.3's find-only search): its hits show
  `path = old` with no tick and count nothing for Apply. A Contains value search with a Number/Boolean replacement is
  refused by `SearchSpec.problems()` (shown in the popup) rather than the select being locked to String. The popup
  starts with the previous search (`SvReviewScreen.last_spec`, kept across rescans); with no previous search, the
  replacement type starts as String (D10). Scope selects use `""` for "every" (`popups.EVERY`).
- **T3.3** The search runs through `RunActions` (now mixed in: `SV_TOOL`, `run_backup_dir`, a `_mark_stale` that
  drops what is pending and rescans; T3.4 may refine it). `RunActions.start_run` gained `writes=True`; a search
  passes `writes=False` so it does not run inside `activity.running()` (it changes no file). Failures log at
  `svb.search` (log_exception, no new event; `svb.search_started`/`_completed` come from `run_search`). Progress is
  one row (`SearchProgressScreen`, stage "Searching", detail `<flavor>: <rel path>`) fed by `run_search`'s
  `progress(done, total, file)`; parallelism is `cfg.parallelism`. Patch targets: `review_screen.run_search`,
  `review_screen.SearchProgressScreen`.
- **T3.3** Results tree data: `("r-flavor", Flavor, idx)`, `("r-account", Flavor, account, idx)`, `("r-owner",
  Flavor, account, owner_label, idx)`, `("r-file", SvFile, idx)`, `("hit", i)`; `idx` = the hit indexes under the
  group (its tick keys), `i` indexes `SvReviewScreen.hits`, `ticked` holds indexes. Owners show as
  `Account-wide` or `Realm/Name` (the owner label, one level, not Browse's realm › character). Groups show
  `N results`; the filter matches names and the hit text only (no marks or counts), and `filter_texts(i)` = flavor,
  account, owner, file, hit text. `x` opens every Results group; all start open. Nothing found = a dim
  `Nothing found.` line. Ticks (space/a/n) act only in the Results view and only when the search replaces; `v`
  keeps them. A rescan drops the results and goes back to Browse.
- **T3.3** D12 report: `_recount()` runs `Staging.plans(ticked_hits())` after every tick/staging change and rebuild
  and keeps `{index: reason}` for the dropped ones; their leaves show `⚠ left out: <reason>` and the pending line adds
  `N ticked results left out: a staged edit wins` (or `see the marked results` when a reason is not a staged edit /
  delete). The pending Static is multi-line after a search: `Results: N hits in F files[ (find only)]`, the cap
  (`N more hits left out (the results stop at 10,000): narrow the search.`) and `N files can't be read.`. `Ticked:
  M results in F files` counts files across staged edits and ticked hits.
- **T3.4** Runs follow Ace3's review: Apply = marker waiting → recovery popup first; `_backup_dir_refused`; the WoW
  check (`ReviewBase.run_preflight`) over the plan's flavor folders (`check_for`: the injected `wow_check` in tests,
  else `wow_check_for(folders)`; Undo checks the journal's flavors, recovery the marker's); confirm; `start_run` with
  `editor.apply_plan(..., progress=screen.report_unit)` / `undo.undo_run` / `undo.recover`. A dry run skips the WoW
  check, backup folder and marker (it writes nothing). The plan is built once at `_start` (`staging.plans(
  ticked_hits())`) and handed through the confirm (nothing can change while the check or a popup is up).
- **T3.4** Confirm: `ConfirmScreen(title, body, (*extra, *alerts), kind=simulate|destructive, groups=apply_groups(plan))`
  where `report.apply_groups` (new) lists per flavor display name one line per file `ACCT › owner › File.lua: N edits`
  (the spec's "counts per flavor and file"); `extra` holds the "Could not check whether WoW is running" alert, the
  plan's alerts end with `DISCLAIMER` (Apply only). Undo's confirm is destructive (as every tool's), with
  `The N staged edits and M ticked results not applied yet will be dropped.` when something is pending; the staging
  is dropped when the Undo starts.
- **T3.4** Stale handling split: `_set_stale()` (drop staging, ticks and left-out, `_stale = True`) after a real
  Apply / an Undo, so the rescan happens when the result screen is left (`_after_result`: Rescan/Esc → `_scan()`;
  f/t/q → `action_leave`, nothing pending any more; `on_screen_resume` rescans a stale review too), never under the
  result screen; `_mark_stale()` (RunActions' failure hook, and after a recovery) = `_set_stale()` + scan now when the
  review is shown. A dry run keeps everything (Back to review).
- **T3.4** Recovery: `_scanned` offers `ui.dialogs.UnfinishedRunScreen(report.recovery_text(marker), marker)` (no
  tool subclass) on every scan that finds a marker, logging the shared `svb.recovery_offered`; Leave = `undo.leave`
  (logs `svb.recovery_done` leave), Put back runs `undo.recover` with the progress popup and rescans; Esc keeps the
  marker (offered again by the next scan or Apply). No event registry changed.
- **T3.4** `RunProgressScreen` (ID prefix `svb`, core `STAGE_TITLES`, simulated stage `check`, one row per flavor) lives
  in `review_screen.py` next to `SearchProgressScreen`; `SvResultScreen` in the new `result_screen.py` (spec §4; not
  counted by test_structure's review-screen pin), sub-title `Saved Variables Browser · <scope> · <Apply|Dry run|Undo>
  result`, `LOG_SCREEN = "svb_result"`. `TITLE` now lives in `result_screen.py` (review_screen imports it). Ace3's
  `STATUS_COLOURS` moved to `core/sv_report.py` (both result screens use it; no Ace3 assertion changed).
- **T3.4** Meta-tests: `NO_RUN` removed from `test_help` and `test_look_and_feel` (not just emptied), `RUN_ACTION
  ["sv-browser"] = "dry_run"`, `PREPARE["sv-browser"] = tests.fixtures.stage_sv_edit` (stages " (edited)" on the
  first string value, Retail first, read synchronously in the test thread; look-and-feel wants "Retail" in the
  confirm). The help names every review, settings and result button (incl. **Back to review**).
- **M3 review**: 16 findings, 16 fixed, 0 rejected (6/11 and 7/13 were the same defects, each fixed once). (1) Edit
  value's and Search's checkboxes are `popups.PopupCheckbox` (Space ticks; Enter raises SkipAction, so the popup's
  own `enter` binding, action `submit`, presses OK / Find; not named `ok`/`find` so D17 does not ask the buttons to
  show Enter, which the hint names), hints add "Space tick". (2) `ButtonRow(id="search-row", wrap=False)`. (3) Edit
  value starts from the staged value (type, text via `encode_value`, checkbox); "Now:" stays the file's value. (4)
  Space/a/n stay keys (look-and-feel pins Space, a, n in every review footer, so not hidden with check_action): a
  new `TickActions.no_ticks_here()` hook (default False) lets the review notify `NO_TICKS_BROWSE` /
  `NO_TICKS_FIND_ONLY` instead of doing nothing. (5) `Staging.delete_problem` checks `deleted_above(doc, node)` (the
  node itself). (6/11) `_undo_confirmed` no longer drops the pending work: `_undone` (`_set_stale`) or a crash
  (`_mark_stale`) does; an expected `UndoError` keeps it and the tree/pending line stay true. (7/13) The recovery
  popup's message adds "Putting the originals back reads the files again: the N staged edits and M ticked results
  not applied yet will be dropped." when anything is pending (keeping edits across the rescan was judged riskier).
  (8) `_scanned` offers recovery only when the review is the shown screen, else sets `_offer_on_resume` and
  `on_screen_resume` offers it. (9) `_loaded` returns on a generation mismatch before touching `_loading`. (10)
  `_applied` keeps the staged work and ticks and opens the result with **Back to review** when nothing was written
  (`not (edited or rolled_back or failed)`). (12) `marker_root` (the root the scan worker read the marker from) is
  passed to `_scanned` and used by `_recovery_chosen` for leave/recover. (14) The WoW-running test applies one
  edit first, so `z` reaches the refusal (asserts `svb.wow_running`, review shown, journal kept). (15) The
  equal-value test uses the ElvUI document with its node. (16) `NEW_FONT = "Skurri Bold"`, asserted absent before
  Apply. +10 tests.
- **T4.1** Docs: `docs/sv-browser.md` uses "staged" (the tool's own word; the Ace3 guide's no-"staged" rule is
  Ace3-only) and adds a per-key table of what Edit/Rename/Delete allow (top-level, plain value, table, array entry).
  The CHANGELOG entries went under the existing unreleased `## [0.1.0] - 2026-10-05` Added (its intro now "five
  tools"), as **Saved Variables Browser** and **Shared SavedVariables library** groups (the latter holds the Lua 5.1
  escape fix); no new version entry. README tests badge set to the passing count (1641 of 1643, 2 skipped), it read
  1305. The architecture's Ace3 screens line now names the shared `BarTree` instead of the gone `ProfileTree`.
  `tests/test_docs.py::test_sv_browser_guide_readme_and_notes` pins the guide's sections, keys and paths
  (`edited\edited-<flavor>-all-`: SV Browser has no account pick, so the zip's account part is always `all`), the
  README cfg row and the "five tools" prose, the CLAUDE.md tool line and core modules, the CHANGELOG group and the
  architecture section. Spec Addendum A is D22-D36. CLAUDE.md suite time stays ~70s (1643 tests in 70 s here).
- **M4 review**: 7 findings, 7 fixed, 0 rejected. (1) `compile_file` first streams the whole file through `iter_scalars` (a full pass that builds nothing), so a parse fault in a table no edit touches gives the problem "not readable Lua", verify reports it and Apply stops before writing (D4); staging still accepts the edit (the lazy tree can't see the fault without a full parse on the UI thread, D27 keeps the rest browsable), the guide says Apply refuses such a file. (2) `Staging.plans` leaves out a ticked hit whose replacement is the value already there (`_same_value` or the same encoded bytes, as D29 for a manual edit) with the new reason `ops.UNCHANGED`; the pending line says "nothing to change" when that is the only reason; guide lists it. (3) Addon file scope now matches `file.path.name` (what the tree shows, `.lua` included), as the guide and D9's "Addon file" say; the search test that pinned the addon name flipped, placeholder "any (the file name contains)". (4) adding-a-tool and architecture name `core/sv_undo._moved_zip()`. (5) architecture: `validate_backup_dir`, `tool_root`, `run_units`, `HIDDEN_NOUN` (result) and `ChoiceScreen(escape=)` user lists include the Saved Variables Browser. (6) README (first-run, cfg row, `s`) and the suite help say the search reads `parallelism` files at once; the setup label is unchanged (README's WSL FAQ quotes it). (7) `SvScanWarning(path, message)` in `core/svfiles.py`, used by both SV scanners (each one's `ScanWarning` gone), pinned in `test_structure` (only the WTF Cleaner keeps its own `ScanWarning`, another shape).
