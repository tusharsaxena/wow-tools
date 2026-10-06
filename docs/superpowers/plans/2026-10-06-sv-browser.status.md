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
| T2.2 | scanner + lazy model | todo | | |
| T2.3 | search | todo | | |
| T2.4 | staging, compile, verify | todo | | |
| T2.5 | apply/undo/recovery wiring | todo | | |
| M2 | push milestone 2 | todo | | |
| T3.1 | flow, disclaimer, Browse view | todo | | |
| T3.2 | edit/rename/delete popups, staging UI | todo | | |
| T3.3 | search popup, Results view | todo | | |
| T3.4 | apply/dry run/undo/recovery UI, result, help, look-and-feel | todo | | |
| M3 | push milestone 3 | todo | | |
| T4.1 | docs | todo | | |
| T4.2 | review, fixes, push, ask for merge | todo | | |

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
