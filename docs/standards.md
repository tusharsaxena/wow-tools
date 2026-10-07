# Standards

The rules every tool in Ka0s WoW Tools follows, whichever tool you are changing. The keywords **MUST**, **MUST NOT**
and **SHOULD** are used as in RFC 2119. If a change would break a MUST, stop and flag it to the user; never deviate
or "fix" silently. An accepted deviation is recorded in [Documented deviations](#documented-deviations) at the end.

Each rule has a stable ID (`STD-<section>.<n>`) to cite in reviews, commits and tests, a short *Why*, and what enforces
it: a test (`tests/<file>.py::<test>`) or *review*. Decision IDs (D9, D17, W1, B1 ...) point at the frozen specs in
[`docs/superpowers/specs/`](superpowers/specs/); those specs are records and are never edited.

## Contents

1. [Code and layering](#1-code-and-layering)
2. [Shared library](#2-shared-library)
3. [Tool package and registry](#3-tool-package-and-registry)
4. [Configuration and paths](#4-configuration-and-paths)
5. [Data safety](#5-data-safety)
6. [Events and logging](#6-events-and-logging)
7. [UI look and feel](#7-ui-look-and-feel)
8. [Keys and buttons](#8-keys-and-buttons)
9. [Help and docs](#9-help-and-docs)
10. [Testing](#10-testing)
11. [Release and vendoring](#11-release-and-vendoring)
12. [Process](#12-process)
13. [Documented deviations](#documented-deviations)

---

## 1. Code and layering

- **STD-1.1 MUST** Target Python 3.10 as the floor: no syntax or stdlib API newer than 3.10; the interpreter check in
  `core/bootstrap.py` stays the first thing the entry point runs.
  *Why:* users run whatever Python they have; an old one gets a readable refusal, not a crash.
  *Enforced by:* `tests/test_bootstrap.py::test_rejects_old_python`, CI matrix (3.10 and 3.13).
- **STD-1.2 MUST** Start every module in `wowtools/`, `scripts/` and `tests/` with `from __future__ import annotations`
  (after the docstring, before any other import).
  *Why:* modern annotations (`X | None`, built-in generics) on 3.10.
  *Enforced by:* `tests/test_structure.py::test_every_module_has_the_future_import`.
- **STD-1.3 MUST** Keep top-level `from wowtools... import` lines sorted by module name.
  *Why:* one import order; Ruff's sorter cannot produce the hanging-indent style, so a test checks it.
  *Enforced by:* `tests/test_structure.py::test_wowtools_imports_are_in_order`.
- **STD-1.4 MUST** Use only the standard library plus the pinned, pure-Python packages in `vendor/`; add no other
  third-party dependency.
  *Why:* the suite runs from a clone or release zip with no `pip install`.
  *Enforced by:* `tests/test_bootstrap.py::test_textual_imports_from_vendor`, review.
- **STD-1.5 MUST** In the entry point, import nothing beyond `core/bootstrap` (stdlib-only) until `add_vendor_path()`
  has run; import everything else after it.
  *Why:* a third-party import before `vendor/` is on `sys.path` loads a system copy or fails.
  *Enforced by:* review (`wowtools/__main__.py`).
- **STD-1.6 MUST NOT** `wowtools/core/` imports `textual`, `wowtools.ui` or `wowtools.tools`, directly or
  transitively ([D9][polish]).
  *Why:* core is the UI-free half of the shared library, testable without a terminal.
  *Enforced by:* `tests/test_structure.py::test_core_never_imports_textual`,
  `tests/test_structure.py::test_importing_core_loads_no_textual`.
- **STD-1.7 MUST** Keep a tool's logic modules (scanner, planner, model, ops, journal, undo, report, settings, ...)
  UI-free over plain dataclasses; only front-end modules (`app.py`, `*_screen.py`, `popups.py`, `tree_view.py`) import
  `textual` or `wowtools.ui`.
  *Why:* logic is unit-tested without Textual.
  *Enforced by:* review.
- **STD-1.8 SHOULD** Keep front ends thin: `report.py` turns results into plain-string labels and table rows; screens
  lay out and dispatch to logic functions.
  *Why:* display text is testable without a TUI and screens stay small.
  *Enforced by:* review.
- **STD-1.9 SHOULD** Read and write text, and decode subprocess output, with an explicit `encoding="utf-8"` (and
  `PYTHONIOENCODING=utf-8` for child processes).
  *Why:* the Windows locale code page (cp1252) cannot decode every byte.
  *Enforced by:* `tests/test_release_scripts.py::test_the_tags_changelog_is_read_as_utf8_whatever_the_locale`, review.
- **STD-1.10 MUST** Keep `ruff check --no-cache .` clean against `ruff.toml` (py310, 120 columns), marking
  deliberate broad excepts and late imports with their `noqa` code (`BLE001`, `E402`). It is part of the green gate
  (STD-10.1).
  *Why:* Ruff is not run in CI; the `noqa` codes document intent.
  *Enforced by:* the green gate, review.

## 2. Shared library

- **STD-2.1 MUST NOT** A tool imports another tool, in any form (absolute, `from wowtools.tools import x`, relative)
  ([D9][polish]).
  *Why:* tools stay independent; the shared library replaces cross-tool coupling.
  *Enforced by:* `tests/test_structure.py::test_no_tool_imports_another_tool`,
  `tests/test_structure.py::test_the_import_check_sees_every_form`.
- **STD-2.2 MUST** Put anything two or more tools need in `wowtools/core` (UI-free) or `wowtools/ui` (Textual),
  defined once. When a second tool needs code one tool has, move it there first and make both use it; never copy it
  ([D9][polish], [D20][svb]).
  *Why:* one definition means one fix and one behaviour.
  *Enforced by:* `tests/test_structure.py::test_shared_helpers_are_defined_once`.
- **STD-2.3 MUST** When a helper moves into the shared library, pin its single definition in
  `tests/test_structure.py` and list the retired tool copies as gone.
  *Why:* the pin stops a copy from coming back.
  *Enforced by:* `tests/test_structure.py::test_shared_helpers_are_defined_once`.
- **STD-2.4 MUST** Take generic helpers from core: `safe_progress`, `remove_quietly`, `atomic_write_*`,
  `rename_no_replace`, `free_name` (`fsutil`); `plural`, `human_size` (`text`); `flavor_name`, `validate_backup_dir`
  (`install`); journals through `ToolJournals` (`journal`); `safe_destination`, `UndoResultBase` (`undo`); markers
  (`marker`); `ThrottledProgress` (`progress`); `run_units` (`parallel`).
  *Why:* these were once copied per tool.
  *Enforced by:* `tests/test_structure.py::test_tools_use_the_shared_helpers`.
- **STD-2.5 MUST** A tool that reads or edits SavedVariables builds on core's stack (`luasv`, `svfiles`, `sv_events`,
  `sv_apply`, `sv_journal`, `sv_undo`, `sv_verify`, `sv_report`) and supplies only its `SvTool` and compile/verify
  callbacks; it defines no parser, file walk, write pipeline or `tool_root` ([D20][svb], [D34][svb]).
  *Why:* byte-exact parsing and the safe write pipeline are one audited implementation.
  *Enforced by:* `tests/test_structure.py::test_saved_variables_reader_lives_in_core`,
  `tests/test_structure.py::test_saved_variables_files_and_tool_root_live_in_core`,
  `tests/test_structure.py::test_saved_variables_write_pipeline_lives_in_core`.
- **STD-2.6 MUST** Take UI machinery from `wowtools/ui` and subclass it, never re-define it in a tool: review ticks,
  Space, a/n, leaving, preflight, debounced rebuild, scan box (`ui/review.py`); the tree filter (`ui/tree_filter.py`);
  the `b` blacklist action; lock refusal; dialogs; `ResultBase`; `ToolSettingsScreen`; `ToolFlow` steps. No tool
  subclasses Textual's `Tree` directly; review trees are `ReviewTree`/`BarTree`.
  *Why:* one look and one behaviour, fixed in one place ([D7][polish], [D9][polish], [B1][wb]).
  *Enforced by:* `tests/test_structure.py::test_review_machinery_lives_in_ui`,
  `tests/test_structure.py::test_tree_filter_lives_in_ui`,
  `tests/test_structure.py::test_blacklist_helpers_and_key_are_shared`,
  `tests/test_structure.py::test_lock_refusal_and_progress_close_are_shared`,
  `tests/test_structure.py::test_saved_variables_ui_helpers_live_in_ui`,
  `tests/test_structure.py::test_shared_dialogs_live_in_ui`,
  `tests/test_structure.py::test_result_choice_settings_and_flow_live_in_ui`.
- **STD-2.7 MUST** Define suite-wide literals once: the data folder name `"wow-tools"` only in `core/journal.py`
  (`TOOLS_SUBDIR`), the 86400.0 day constant once, and the theme's success colour `#4CC38A` taken from
  `KA0S_THEME`, never re-typed. Button colours live only in `ui/theme.py` `ACTION_COLOURS` (STD-8.2). Other theme
  hex values are still copied in a few modules (`ui/dialogs.py` `ALERT_STYLE`/`ACCENT`, WTF Cleaner's
  `WARNING_STYLE`, result screen and report criteria, Screenshot Organizer's review); new code takes them from the
  theme.
  *Why:* a copied literal drifts.
  *Enforced by:* `tests/test_structure.py::test_literals_are_defined_once`.
- **STD-2.8 MUST** Delete dead code and re-exports outright (for example, no tool re-exports `ConfirmScreen`)
  ([D14][polish]).
  *Why:* stale attributes invite callers to depend on the wrong place.
  *Enforced by:* `tests/test_structure.py::test_dead_code_is_gone`.

## 3. Tool package and registry

- **STD-3.1 MUST** Name a tool three ways consistently: the id is lowercase-hyphenated (`Tool.name` = `TOOL_NAME` =
  `config/<id>.cfg` = `logs/<id>/` = `docs/<id>.md`); the package and config section are the id with underscores
  (`Tool.section` = `settings.SECTION`); the title is title case (`Tool.title`).
  *Why:* config files, log, journal and tool folders, guide links and migrations are derived from these names.
  *Enforced by:* `tests/test_structure.py::test_result_choice_settings_and_flow_live_in_ui`,
  `tests/test_help.py::test_every_tool_has_help_with_its_guide`, review.
- **STD-3.2 MUST** Register each tool once in `TOOLS` (`wowtools/tools/__init__.py`) as
  `Tool(name, title, description, module, section)`. Tools open only from the menu: no per-tool entry point, wrapper
  or CLI mode.
  *Why:* the menu, help and the meta-tests iterate `TOOLS`; flows load lazily.
  *Enforced by:* `tests/test_suite.py::test_registry`, `tests/test_suite.py::test_tools_cannot_be_started_directly`.
- **STD-3.3 MUST** A tool's package `__init__.py` imports its `events` module, so its events register on import.
  *Why:* events must exist with fixed levels before anything logs them.
  *Enforced by:* review (every `wowtools/tools/*/__init__.py` imports its `events`).
- **STD-3.4 MUST** `app.py` defines a `ToolFlow` subclass with `SECTION` (= the registry's section) and
  `SETTINGS_SCREEN` (a `ToolSettingsScreen` subclass), implements `_pick_flavor()`, exports it as module-level `FLOW`,
  and redefines no shared flow step (`start`, `open_settings`, `_after_review`, `remember_flavor`, `pick_account`,
  `fill_notes`, `_settings_done`, `_save`, `_error`, `action_cancel`, ...) ([D9][polish]).
  *Why:* every tool opens, asks for settings, remembers choices and leaves the same way.
  *Enforced by:* `tests/test_structure.py::test_result_choice_settings_and_flow_live_in_ui`.
- **STD-3.5 MUST** `settings.py` defines `SECTION`, a settings dataclass, `load_settings(cfg)` and
  `save_settings(cfg, settings, *, source="settings")`, taking the tool's own `Config`.
  *Why:* the form, flow and tests treat every tool alike.
  *Enforced by:* the per-tool `tests/test_*_settings.py` round trips, review.
- **STD-3.6 SHOULD** Lay out a new tool's package like the others: `__init__.py`, `events.py`, `settings.py`,
  `help.py`, `app.py`, `review_screen.py` (plus `result_screen.py` if large), and UI-free logic (`scanner.py`/
  `planner.py`, `journal.py`, `undo.py`, `report.py`). Follow [adding-a-tool.md](adding-a-tool.md).
  *Why:* one shape makes every tool navigable; some structure tests address files by name.
  *Enforced by:* review.
- **STD-3.7 MUST** Rename a tool only by changing `TOOLS`, `TOOL_NAME` and `SECTION` and adding one
  `ToolRename(old, new, old_section, new_section)` line to `RENAMED_TOOLS`. Anything named after the tool inside a
  user-chosen folder (Interface Backup's `<backup_dir>/interface-backup`) the tool moves itself.
  *Why:* `core/migrate.py` moves config, logs and `<WoW>/wow-tools/<tool>/` at start-up, never user-chosen folders.
  *Enforced by:* `tests/test_migrate.py::test_every_rename_points_at_a_registered_tool`,
  `tests/test_suite.py::test_renamed_tool_config_and_folders_move_on_start`.

## 4. Configuration and paths

- **STD-4.1 MUST** Keep suite-wide settings in `[general]` of `config/wow-tools.cfg` and each tool's in
  `config/<tool id>.cfg`, one section named `<package>`; never in the working directory.
  *Why:* each tool owns one file and one section; renames migrate file by file.
  *Enforced by:* `tests/test_config.py::test_default_paths_are_in_the_config_folder_not_cwd`.
- **STD-4.2 MUST** Read config only through the typed getters (`get`, `get_int`, `get_bool`, `get_path`) with a
  default, so a missing or bad value falls back instead of raising.
  *Why:* config files are hand-editable.
  *Enforced by:* `tests/test_config.py::test_bad_values_fall_back_to_defaults`.
- **STD-4.3 MUST** Change values only through `Config.set`/`remove`/`set_path` and write only through `Config.save()`
  (atomic, from the UI thread). Unknown keys and sections survive a load and save; a real change logs
  `config.changed` with its `source`, a no-op logs nothing.
  *Why:* no half-written config, no lost keys, and an audit trail of who changed what.
  *Enforced by:* `tests/test_config.py::test_save_is_atomic`,
  `tests/test_config.py::test_round_trip_preserves_unknown_keys_and_sections`,
  `tests/test_config.py::test_set_logs_real_changes_only`.
- **STD-4.4 MUST** Store folder paths through `set_path`/`get_path` (`core/paths.to_stored`/`to_native`): Windows form
  on disk (`G:\...`), converted to `/mnt/g/...` only when read under WSL. Journals store paths the same way.
  *Why:* one config and one journal work from Windows and WSL.
  *Enforced by:* `tests/test_paths.py::test_to_stored_under_wsl`,
  `tests/test_journal.py::test_paths_are_stored_in_windows_form_under_wsl`.
- **STD-4.5 MUST** Retention is global: backups and snapshots prune per flavor to `[general] keep_backups`
  (`Config.keep_backups`, 0 = all), journals per tool to `keep_journals`. A tool has no retention setting, and its
  `save_settings` calls `cfg.remove_retired(SECTION, source=source)` then `cfg.save()`.
  *Why:* one setting the user understands, edited on the setup screen; retired per-tool keys go on the next save.
  *Enforced by:* `tests/test_config.py::test_retention_defaults_are_ten_and_ten`,
  `tests/test_ace_app.py::test_settings_have_no_retention_inputs`, the per-tool
  `test_retention_is_global_and_stale_keys_go_on_save`. *Deviation:* WTF Cleaner `keep_cleaned`.
- **STD-4.6 SHOULD** Add a new suite-wide setting as a typed, clamped `Config` property on `[general]` (with a
  `DEFAULT_` constant), edited on the setup screen.
  *Why:* bad input gives a sane default ([D10][polish]).
  *Enforced by:* `tests/test_config.py::test_parallelism_defaults_to_two_and_is_clamped`, review.
- **STD-4.7 MUST** Resolve a tool's output folder with `core.journal.tool_root(backup_dir, wow_path, TOOL_NAME)`:
  `<backup_dir>/<tool>` when a backup folder is set, else `<WoW>/wow-tools/<tool>` ([D20][svb]).
  *Why:* every tool's files live in the same place.
  *Enforced by:* `tests/test_structure.py::test_saved_variables_files_and_tool_root_live_in_core`.
  *Deviation:* WTF Cleaner's backup folder.
- **STD-4.8 MUST** Journals live at `<WoW>/wow-tools/<tool>/journal/journal-<stamp>.jsonl` (`ToolJournals.dir`),
  whatever `backup_dir` says.
  *Why:* Undo finds the latest run in a fixed place even after the backup folder changes.
  *Enforced by:* `tests/test_journal.py::test_journal_dir`,
  `tests/test_sv_browser_apply.py::test_a_backup_folder_puts_the_zips_there_and_the_journal_under_wow`.
- **STD-4.9 MUST** Validate a folder a tool writes into with `core.install.validate_output_dir`
  (`validate_backup_dir` for a backup folder setting; Screenshot Organizer's `validate_dest` for its destination): a
  full path, not the WoW folder, not inside any flavor's WTF, Interface or Screenshots. Validate when the form saves
  (show `_error`, return `False`) and again before every run writes to it.
  *Why:* backups inside what they protect get swept up or deleted with it; the cfg can be hand-edited.
  *Enforced by:* `tests/test_core_shared.py::test_backup_folder_rules`, `tests/test_ui_review.py::test_backup_dir_refused`,
  `tests/test_interface_backup_app.py::test_settings_refuse_folder_inside_wtf`.
- **STD-4.10 SHOULD** Remember the flavor picker's last choice as `last_flavor_choice` in the tool's section (`""` =
  All flavors, absent = never chosen) and `last_account` where the tool picks accounts; the settings form's `save()`
  reloads the stored settings and replaces only its own fields so these survive a Save.
  *Why:* the same picker memory in every tool.
  *Enforced by:* `tests/test_ui_shared_screens.py::test_remember_flavor`, review.

## 5. Data safety

The order of a real run that changes files: guard, recheck, verify in memory, lock probe, snapshot, originals zip,
marker, journal, atomic writes with read-back, roll-back on failure, clear marker.

### 5a. Before anything is written

- **STD-5.1 MUST** Run the flavor-aware running-WoW check (`core.process.wow_check_for`) in a worker before the
  confirm of every real run that changes files under a flavor; an unknown result (`None`) is never "not running" and
  adds an alert to the confirm ([D16][svb]).
  *Why:* WoW rewrites SavedVariables at logout and can lock Interface files.
  *Deviation:* Screenshot Organizer.
  *Enforced by:* `tests/test_ui_review.py::test_refused_while_running`,
  `tests/test_sv_browser_run_ui.py::test_apply_says_when_the_wow_check_could_not_run`.
- **STD-5.2 MUST** Tools that edit SavedVariables in place (the `core/sv_apply` pipeline) refuse Apply, Undo and
  recovery while that flavor's WoW runs (`WowRunning`); Dry run, Find and Browse stay allowed ([D16][svb]).
  *Why:* an in-place edit is lost when the game saves at logout.
  *Enforced by:* `tests/test_core_sv_pipeline.py::test_one_wow_running_for_apply_and_undo`,
  `tests/test_sv_browser_run_ui.py::test_apply_and_undo_are_refused_while_wow_runs`.
- **STD-5.3 SHOULD** A tool that deletes or replaces whole files or folders picks refuse or warn on purpose and records
  it in its spec; warning means a red alert in the confirm plus `wow.running_warning` in the log.
  *Why:* their safety nets still cover the run. *Deviation:* WTF Cleaner and Interface Backup warn.
  *Enforced by:* `tests/test_wtf_app.py::test_wow_running_warning_is_shown_and_logged`,
  `tests/test_interface_backup_app.py::test_wow_running_is_an_alert`.
- **STD-5.4 MUST** Pass every SavedVariables path through `core.svfiles.SvGuard`; anything that resolves outside
  `<flavor>/WTF/Account` or not directly in a `SavedVariables` folder stops the run.
  *Why:* a link or a bad plan must never change a file elsewhere.
  *Enforced by:* `tests/test_core_svfiles.py::test_guard_refuses_outside_account_folder`,
  `tests/test_cleaner.py::test_symlink_escaping_wtf_is_rejected`.
- **STD-5.5 MUST NOT** Follow a symlink or Windows junction when scanning, backing up, deleting or restoring: use
  `fsutil.is_link`, `is_real_dir`, `remove_tree_no_follow` and `backup.walk_files`, report links through `on_link`.
  *Why:* a link can point at another flavor or system folders; Python 3.10 reports a junction as a plain folder.
  *Enforced by:* `tests/test_backup.py::test_links_reported_not_followed`,
  `tests/test_fsutil.py::test_link_inside_is_unlinked_never_followed`,
  `tests/test_sv_browser_scanner.py::test_links_are_never_followed`.
- **STD-5.6 MUST NOT** Tools that act on addon data list or touch `Blizzard_*.lua`, `*.lua.bak` or `*.lua.old`
  (`svfiles.is_addon_sv_file`).
  *Why:* the game owns its own SavedVariables (keybindings, layout). *Deviation:* SV Browser lists `Blizzard_*`.
  *Enforced by:* `tests/test_scanner.py::test_blizzard_and_non_sv_files_are_never_scanned`,
  `tests/test_ace_scanner.py::test_skips_bak_blizzard_and_non_lua`.
- **STD-5.7 MUST** Re-read every file just before changing it and compare with what the scan saw (SHA-256 for
  SavedVariables edits, size and mtime for WTF deletes, existence and size for moves); skip a changed or missing file
  as "changed since the scan" ([D17][svb]).
  *Why:* a stale plan must not overwrite newer data.
  *Enforced by:* `tests/test_ace_editor.py::test_file_changed_since_scan_is_skipped_others_applied`,
  `tests/test_cleaner.py::test_changed_and_missing_files_are_skipped`,
  `tests/test_screenshot_organizer_organizer.py::test_target_appearing_after_scan_is_never_overwritten`.
- **STD-5.8 MUST** Compile and verify every edit in memory before writing (one problem stops the run, nothing
  written), read each written file back, and check copies by hash before they replace or remove anything
  ([D14][svb], [D19][svb]).
  *Why:* catch a bad edit while the original can still be put back.
  *Enforced by:* `tests/test_core_sv_pipeline.py::test_a_verify_problem_stops_before_anything_is_written`,
  `tests/test_ace_editor.py::test_verify_failure_stops_before_anything_is_written`.
- **STD-5.9 MUST** Before a real run changes or deletes SavedVariables, rename back lock-probe leftovers
  (`recover_probe_leftovers`), lock-probe every target (`svfiles.find_locked`) and refuse the whole run with
  `locked_message` if any file is held. A dry run skips the probe.
  *Why:* companion apps hold files open; on Windows a replace then fails part-way.
  *Enforced by:* `tests/test_ace_editor.py::test_locked_file_refuses_before_snapshot`,
  `tests/test_cleaner.py::test_locked_file_stops_a_real_clean_before_anything`,
  `tests/test_cleaner.py::test_dry_run_skips_the_lock_check`.

### 5b. Safety nets

STD-5.10 to STD-5.15 apply to runs that change or delete SavedVariables or WTF files (WTF Cleaner, Ace3 Profile
Manager, SV Browser). Interface Backup and Screenshot Organizer meet the same goals differently; see the
[Documented deviations](#documented-deviations).

- **STD-5.10 MUST** Before a real run changes or deletes any SavedVariables file, take a verified whole-WTF snapshot of
  that flavor (`core.snapshot.take_snapshot`, `must_hold` = the files to change); if it fails, nothing changes
  ([D14][svb]).
  *Why:* the last-resort copy of everything in WTF.
  *Enforced by:* `tests/test_safety.py::test_snapshot_refuses_when_a_file_to_delete_is_not_in_it`,
  `tests/test_cleaner.py::test_snapshot_failure_deletes_nothing`.
- **STD-5.11 MUST** Before the first destructive write, zip the original bytes of exactly the files the run changes,
  deletes or replaces (`core.backup.create_backup`, or Interface Backup's safety zip); if that fails, nothing changes.
  *Why:* this zip is Undo's precise source.
  *Enforced by:* `tests/test_cleaner.py::test_selective_backup_failure_after_snapshot_deletes_nothing`,
  `tests/test_sv_browser_apply.py::test_the_snapshot_and_the_originals_zip_hold_the_right_members`.
- **STD-5.12 MUST** Write every backup or snapshot zip to `<name>.partial`, read every entry back (`verify_backup`),
  then move it into place with `rename_no_replace`; on any failure, Ctrl+C included, remove the partial.
  *Why:* an unverified or half-written zip is no backup.
  *Enforced by:* `tests/test_backup.py::test_verification_failure_leaves_nothing`,
  `tests/test_no_replace_call_sites.py::test_create_backup_never_replaces`.
- **STD-5.13 MUST** Before the first destructive write, atomically write a crash marker (`core.marker`) naming the
  flavor, the backup and each file with its SHA-256; clear it only when the run finished or fully rolled back. If it
  cannot be written, nothing changes.
  *Why:* the next start learns a run was cut short and where its originals are.
  *Enforced by:* `tests/test_ace_editor.py::test_marker_write_failure_changes_nothing`,
  `tests/test_ace_editor.py::test_marker_is_left_when_put_back_fails`.
- **STD-5.14 MUST** While a marker exists, refuse a new real run (a dry run is allowed) and offer the shared recovery
  choice (put the originals back, or leave as is), settled in the folder the marker was read from ([D15][svb],
  [D33][svb]).
  *Why:* a new run would overwrite the only pointer to the earlier run's originals.
  *Enforced by:* `tests/test_safety.py::test_real_clean_is_refused_and_marker_kept`,
  `tests/test_sv_browser_apply.py::test_a_new_apply_is_refused_while_a_marker_waits`,
  `tests/test_sv_browser_run_ui.py::test_the_marker_is_settled_in_the_folder_it_was_found_in`.
- **STD-5.15 MUST** Recovery puts back only files still byte-for-byte what the interrupted run wrote; anything else is
  left alone. Reading a marker never raises (a damaged one reads as `None`).
  *Why:* the game may have saved newer data after the crash; a bad marker must not block the tool.
  *Enforced by:* `tests/test_ace_undo.py::test_recover_leaves_a_file_wow_saved_after_the_run_wrote_it`,
  `tests/test_core_shared.py::test_unreadable_marker_is_none`.

### 5c. Writing

- **STD-5.16 MUST** Write a file in place only with `fsutil.atomic_write_bytes`/`atomic_write_text` (exclusive-create
  `<name>.partial`, never following a link, then `os.replace`).
  *Why:* a crash leaves the old file or the new one, never a mix.
  *Enforced by:* `tests/test_fsutil.py::test_failed_replace_keeps_the_original`,
  `tests/test_fsutil.py::test_a_link_at_the_partial_name_is_never_followed`.
- **STD-5.17 MUST** Every rename or move into a final name goes through `fsutil.rename_no_replace` (never
  `os.rename`/`os.replace`); timestamped names come from `free_name`.
  *Why:* POSIX `os.rename` silently replaces; two runs in one second must not share a name.
  *Deviation:* `core/migrate.py`.
  *Enforced by:* `tests/test_no_replace_call_sites.py::test_default_renames_are_rename_no_replace`,
  `tests/test_safety.py::test_same_second_snapshot_gets_suffix`.
- **STD-5.18 MUST** If writing fails part-way (any exception, Ctrl+C included), put back everything this run changed,
  newest first, journal the roll-back, re-raise, and name in the message what was put back and where the remaining
  originals are ([D14][svb]).
  *Why:* a run is all or nothing per flavor.
  *Enforced by:* `tests/test_ace_editor.py::test_failure_mid_run_rolls_back_written_files`,
  `tests/test_interface_backup_restore.py::test_swap_failure_rolls_back_exactly`.
- **STD-5.19 MUST** Run all file-changing work in a worker thread inside exactly one `with activity.running():`
  (`RunActions.start_run(..., writes=True)`); read-only work stays outside it.
  *Why:* the suite waits on `wait_idle()` before releasing the lock, so no exit or update cuts a write short.
  *Enforced by:* `tests/test_wtf_app.py::test_clean_and_undo_run_inside_activity_running`,
  `tests/test_screenshot_organizer_app.py::test_runs_happen_inside_activity_running`,
  `tests/test_suite.py::test_lock_released_only_after_worker_finishes`.
- **STD-5.20 MUST** Runs that write SavedVariables across several flavors go one flavor at a time whatever
  `parallelism` says, share one journal and stop at the first failing flavor ([D10][polish]).
  *Why:* they share one crash marker; damage and recovery stay to one flavor.
  *Enforced by:* `tests/test_ace_multi.py::test_stops_at_failing_flavor`, review.
- **STD-5.21 MUST** Only one copy of the suite runs at a time (`core.lock.InstanceLock`, `wow-tools.lock`).
  *Why:* two copies changing the same WTF, markers or journals corrupt each other.
  *Enforced by:* `tests/test_suite_app.py::test_first_acquires_second_sees_holder`,
  `tests/test_suite_app.py::test_lock_conflict_quit`.
- **STD-5.22 SHOULD** Wrap every progress callback a run reports to in `fsutil.safe_progress`.
  *Why:* a broken progress display must never abort a write.
  *Enforced by:* `tests/test_fsutil.py::test_safe_progress_passes_calls_and_swallows_errors`.

### 5d. Journals, Undo, dry run, retention

- **STD-5.23 MUST** Every real run that changes files writes one journal (`ToolJournals`/`JournalWriter`): opened
  before anything is touched (refuse the run if it cannot be), one flushed entry after each change, a finished line,
  and no journal left when nothing changed.
  *Why:* Undo can reverse only what the journal recorded.
  *Enforced by:* `tests/test_journal.py::test_open_is_exclusive_and_header_only_journal_is_discarded`,
  `tests/test_screenshot_organizer_organizer.py::test_unwritable_journal_stops_before_anything_moves`.
- **STD-5.24 MUST** Undo offers only the latest run (`latest_undoable`), never overwrites a file that changed after the
  run (skip it with a reason), and stays undoable when nothing was restored and something failed ([D15][svb]).
  *Why:* newer data wins; an unplugged drive must stay retryable.
  *Enforced by:* `tests/test_journal.py::test_latest_undoable_skips_empty_and_never_reaches_past_an_undone_run`,
  `tests/test_ace_undo.py::test_file_changed_since_is_skipped_not_overwritten`,
  `tests/test_ace_undo.py::test_missing_zip_fails_and_journal_stays_undoable`.
- **STD-5.25 MUST** Treat every journal or marker path as untrusted: map it back only through
  `core.undo.safe_destination` or the tool's equivalent, and refuse anything outside the flavor or the tool's root.
  *Why:* a hand-edited journal must never make Undo write elsewhere.
  *Enforced by:* `tests/test_core_shared.py::test_safe_destination`,
  `tests/test_wtf_undo.py::test_undo_refuses_entries_outside_the_wtf_folder`.
- **STD-5.26 SHOULD** An Undo or recovery that overwrites files in place takes its own snapshot first and refuses
  locked files, exactly as Apply does ([D15][svb]).
  *Why:* Undo is itself a write.
  *Enforced by:* `tests/test_ace_undo.py::test_recover_backs_up_the_wtf_folder_first`.
- **STD-5.27 MUST** A dry run walks the same checks as a real run but changes nothing: no snapshot, marker, journal,
  lock probe or write ([D13][svb]).
  *Why:* it is safe at any time and shows exactly what a real run would do. *Deviation:* WTF Cleaner's dry-run zip.
  *Enforced by:* `tests/test_core_sv_pipeline.py::test_dry_run_writes_nothing`,
  `tests/test_screenshot_organizer_organizer.py::test_dry_run_changes_nothing`,
  `tests/test_cleaner.py::test_dry_run_takes_no_snapshot`.
- **STD-5.28 MUST** Pruning deletes only the tool's own timestamped files of that prefix and flavor, never one a kept
  journal or the marker names, and nothing when a journal cannot be read.
  *Why:* pruning must never remove an Undo or recovery source.
  *Enforced by:* `tests/test_core_snapshot.py::test_prune_keeps_newest_of_that_prefix_and_flavor_only`,
  `tests/test_interface_backup_restore.py::test_unreadable_pruned_journal_keeps_its_safety_zip`.
- **STD-5.29 SHOULD** A run refused or stopped before its first write raises the tool's error type with a message
  ending "Nothing was changed.", logs a registered event, and shows as an expected refusal, not a crash.
  *Why:* the user must know for certain their files were not touched.
  *Enforced by:* review.

## 6. Events and logging

- **STD-6.1 MUST** Log only registered events, each declared once with a fixed level (`debug`, `info`, `warning`,
  `error`) in `core/events.py` or the tool's `events.py`; a caller may raise a level for one record, never lower it.
  *Why:* a machine-readable log and a complete [events.md](events.md).
  *Enforced by:* `tests/test_events.py::test_unregistered_event_raises_when_strict`,
  `tests/test_events.py::test_level_can_only_be_raised`.
- **STD-6.2 MUST** A tool's `events.py` defines `TOOL_NAME` and `EVENTS: dict[str, EventSpec]` and calls
  `register_events(TOOL_NAME, EVENTS)`; a SavedVariables tool also defines `SV_TOOL = SvTool(TOOL_NAME, "<prefix>")`
  and registers `**sv_events(SV_TOOL.prefix)` ([D20][svb]).
  *Why:* `TOOL_NAME` keys the tool's log and journal folders; pipeline events stay per tool.
  *Enforced by:* `tests/test_sv_browser_skeleton.py::test_tool_events_and_the_shared_pipeline_under_svb`.
- **STD-6.3 MUST** Prefix every new tool's event names with its own namespace (`shots.`, `ibackup.`, `ace.`, `svb.`).
  *Why:* one global registry; a name registered twice with a different spec raises.
  *Enforced by:* `tests/test_events.py::test_register_conflicting_spec_raises`,
  `tests/test_screenshot_organizer_settings.py::test_events_are_prefixed`. *Deviation:* WTF Cleaner's bare names.
- **STD-6.4 MUST** After any registry change, regenerate [events.md](events.md) with `python3 scripts/gen_event_docs.py`
  and commit it; never edit it by hand.
  *Why:* it is generated; the test and CI fail when stale.
  *Enforced by:* `tests/test_docs.py::test_event_reference_is_up_to_date`, CI (`gen_event_docs.py --check`).
- **STD-6.5 SHOULD** Write each `EventSpec` description as one plain sentence (what happened, which fields) and name
  events with the shared lifecycle vocabulary (`scan_started`/`scan_completed`, `*_started`/`*_completed`/`*_failed`,
  `journal_pruned`, `undo_*`).
  *Why:* one reader can query any tool's log the same way.
  *Enforced by:* review.
- **STD-6.6 MUST** Tool and UI code logs through `log_event(name, **data)` and `log_exception(where, exc)` only;
  never the `logging` module, a hand-opened log file or `print`. Pass `dry_run=` where dry runs matter. (The terminal
  entry points `__main__.py`, `suite.py` and `core/updater.py`'s CLI print user messages to stdout/stderr, and the
  sink-failure warning of STD-6.8 goes to stderr.)
  *Why:* one sink writes both log files with the shared envelope.
  *Enforced by:* `tests/test_events.py::test_record_has_envelope_fields_and_registry_level`, review.
- **STD-6.7 SHOULD** Call `log_exception` with `where` = `<prefix>.<stage>` (`ace.scan`, `shots.ui`, `svb.load`).
  *Why:* locates the failure without a per-tool error event.
  *Enforced by:* review.
- **STD-6.8 MUST** Each tool logs to `logs/<tool>/` (the suite switches the log context on open and close), and
  logging never raises into the caller because of I/O (a failed sink is disabled with one stderr warning).
  *Why:* readable per-tool logs; a full disk never breaks a run.
  *Enforced by:* `tests/test_events.py::test_each_tool_logs_to_its_own_folder`,
  `tests/test_events.py::test_io_failure_disables_sinks_without_raising`.
- **STD-6.9 SHOULD** Log each user choice as `ui.selection(screen, control, value)` (ticks as `ui.item_toggled`;
  confirms as `screen="confirm"`, `control="<action>_confirm"`); the shared bases already do.
  *Why:* every tool's log records choices in one shape.
  *Enforced by:* review.

## 7. UI look and feel

- **STD-7.1 MUST** Every tool runs inside the one app, `WowToolsApp` (`ui/suite_app.py`): tool menu first; the tool's
  `ToolFlow` pushes its screens and `close()`s back to the menu ([D9][polish]).
  *Why:* one app owns the lock, theme, busy state, help and settings keys.
  *Enforced by:* `tests/test_ui_base.py::test_theme_branding_and_menu_first`.
- **STD-7.2 MUST** First open of a tool (no `config/<tool>.cfg`): the shared WoW-folder setup if needed, then the
  tool's settings once, as a wizard; cancelling closes the tool. `s` opens settings only through
  `ToolFlow.open_settings`.
  *Why:* every tool needs its settings before its first scan.
  *Enforced by:* `tests/test_ui_shared_screens.py::test_first_open_asks_for_settings_once`,
  `tests/test_ui_shared_screens.py::test_open_settings_once_and_notify_on_save`.
- **STD-7.3 MUST** Start at the shared `FlavorScreen` with an "All flavors" entry and the remembered choice; call
  `remember_flavor` after a pick. Notes that need the disk come through `fill_notes` in a worker; per-account tools use
  `pick_account`.
  *Why:* the same picker in every tool; it opens at once.
  *Enforced by:* `tests/test_flavor_screen.py::test_all_flavors_first_and_selected`,
  `tests/test_ui_shared_screens.py::test_fill_notes_reach_an_open_picker`,
  `tests/test_ui_shared_screens.py::test_pick_account`. *Deviation:* SV Browser has no account picker.
- **STD-7.4 MUST** Build every review as a two-pane screen (`two_pane_css`): the fixed-width left pane `#filters`
  (`FILTERS_WIDTH`) holds the controls, one focusable control per row (only a `ButtonRow` shares a row and uses ←/→),
  the tree takes the rest, `#summary` is the bottom line.
  *Why:* one layout, learnt once; arrow keys reach every control.
  *Enforced by:* `tests/test_look_and_feel.py::test_review_left_pane_is_the_same_in_every_tool`,
  `tests/test_look_and_feel.py::test_review_left_pane_has_one_control_per_row`.
- **STD-7.5 MUST** A review's left-pane action row has four keyed buttons in one row: the run action, Dry run (`y`),
  Rescan (`r`), "Undo last ..." (`z`); Esc goes back to the flavor picker.
  *Why:* the same action in the same place in every tool.
  *Enforced by:* `tests/test_look_and_feel.py::test_review_left_pane_is_the_same_in_every_tool`.
  *Deviation:* Interface Backup's second button.
- **STD-7.6 MUST** Build reviews from the shared mixins (`WarningsHost`, `TreeFilter`, `RunActions`, `ReviewBase`,
  optionally `BlacklistAction`) with a `ReviewTree`/`BarTree` and a `TickModel`: `of_unchecked` when the scan's
  proposals are the work, `of_ticked` when ticks select for staging ([D8][polish]).
  *Why:* one tick machinery of either polarity.
  *Enforced by:* `tests/test_structure.py::test_review_machinery_lives_in_ui`.
- **STD-7.7 MUST** Every tree screen binds `TREE_BINDINGS` (`x` expand all, `c` collapse all), has the shared `/`
  filter (`TreeFilter`/`FilterBox`, `FilterBar` with its **Filter** button) and puts `FILTER_HINT` right before
  `TREE_HINT` in its hint ([D7][polish]).
  *Why:* one filter and one expand/collapse everywhere.
  *Enforced by:* `tests/test_look_and_feel.py::test_every_tree_screen_has_the_filter_box`,
  `tests/test_look_and_feel.py::test_review_tree_expands_and_collapses_all`.
- **STD-7.8 MUST** The filter applies only on submit (Enter or the Filter button), never per keystroke; an empty
  submit shows everything; no match leaves the single `NO_MATCH_TEXT` line ([D40][svb]).
  *Why:* a big tree is never rebuilt per keystroke.
  *Enforced by:* `tests/test_look_and_feel.py::test_the_filter_waits_for_enter_or_its_button`,
  `tests/test_look_and_feel.py::test_a_filter_that_matches_nothing_says_so`.
- **STD-7.9 MUST** a, n and Space on a group act only on what the filter shows; hidden ticks stay and are reported
  (`hidden_by_filter`) on the summary and the confirm ([D8][polish]).
  *Why:* the user never ticks what they cannot see.
  *Enforced by:* `tests/test_look_and_feel.py::test_a_group_mark_counts_what_the_filter_shows`,
  `tests/test_ui_tree_filter.py::test_select_all_and_none_act_on_what_the_filter_shows`.
- **STD-7.10 MUST** Show the shared `RiskBanner` (`⚠  USE AT YOUR OWN RISK`) as the first child of the left pane on
  exactly the screens that can destroy data (WTF Cleaner, Ace3 and SV Browser reviews, Interface Backup restore)
  ([D37][svb]).
  *Why:* warn exactly where data can be lost.
  *Enforced by:* `tests/test_structure.py::test_risk_banner_on_exactly_the_destructive_screens`,
  `tests/test_look_and_feel.py::test_destructive_reviews_open_with_the_risk_banner`.
- **STD-7.11 MUST** Every review shows scan warnings through `WarningsHost`: the `SummaryBar`'s **Warnings** button
  (key `!`) appears only while there are warnings and opens the shared `WarningsScreen`; no summary says "see the
  log" ([W1][wb]).
  *Why:* warnings get a screen of their own.
  *Enforced by:* `tests/test_warnings_view.py::test_every_review_opens_its_warnings`,
  `tests/test_warnings_view.py::test_no_warnings_no_button`.
- **STD-7.12 SHOULD** A tool whose review targets addons offers `b` through the shared `BlacklistAction`, its list in
  `[<section>] blacklist` in the `core/blacklist.py` pair format ([B1][wb], [B3][wb]).
  *Why:* one key and one message. Out of scope by B3: Screenshot Organizer, Interface Backup, SV Browser.
  *Enforced by:* `tests/test_structure.py::test_blacklist_helpers_and_key_are_shared`.
- **STD-7.13 MUST** A tool that stages changes before writing shows a `#pending` line, enables Apply/Dry run only
  while something is pending, and asks a destructive confirm before Rescan or any way out drops pending work
  ([D12][svb]).
  *Why:* staged work is never lost silently.
  *Enforced by:* `tests/test_ace_app.py::test_leaving_with_staged_changes_asks_first`,
  `tests/test_sv_browser_edit.py::test_leaving_with_staged_edits_asks_a_destructive_question_for_every_way_out`.
- **STD-7.14 MUST** Use the shared dialogs (`ConfirmScreen`, `ChoiceScreen`, `InfoScreen`, `TextPromptScreen`,
  `UnfinishedRunScreen`, `ProgressScreen`); every `ConfirmScreen` passes `kind=`, focuses Yes (Yes, No order) and is
  coloured by it ([D13][polish]).
  *Why:* Enter answers Yes, so Yes's colour is the safeguard.
  *Enforced by:* `tests/test_structure.py::test_every_confirm_names_its_kind`,
  `tests/test_ui_shared_screens.py::test_opens_on_yes_coloured_by_kind`.
- **STD-7.15 MUST** Popups whose focused button Enter would press mix in `EnterGuard` (`start_guard()` on mount).
  *Why:* a held or double Enter never confirms a destructive action.
  *Enforced by:* `tests/test_ui_shared_screens.py::test_a_held_enter_never_answers`.
- **STD-7.16 MUST** Show every run, dry run and undo in a `ProgressScreen` subclass (own `ID_PREFIX`,
  `STAGE_TITLES`), fed from the worker, one fixed size with `min(parallelism, units)` rows ([D11][polish]).
  *Why:* one progress popup; workers never block on the UI.
  *Enforced by:* `tests/test_progress_popup.py::test_every_tools_popup_is_the_shared_box`,
  `tests/test_progress_popup.py::test_the_box_never_changes_size`.
- **STD-7.17 MUST** End every run, dry run and undo on a `ResultBase` subclass: Item/Value summary over one detail
  table, sub-title ending "result", one button row from Rescan (`r`) to Other flavor (`f`), Tools (`t`), Quit (`q`).
  *Why:* every run ends on the same screen.
  *Enforced by:* `tests/test_look_and_feel.py::test_result_screens_share_one_layout`.
- **STD-7.18 SHOULD** When a dry run leaves staged work pending, open its result with `back=True` so Esc returns to
  the review with staging kept ([D32][svb]).
  *Why:* nothing was written, so the user goes back to the same work.
  *Enforced by:* `tests/test_ui_shared_screens.py::test_back_opens_on_back_to_review`.
- **STD-7.19 MUST** Set `app.busy` for the whole of a file-changing run; leaving, quitting, settings, update,
  warnings and `b` are refused while busy.
  *Why:* leaving mid-run would release the lock while a worker writes.
  *Enforced by:* `tests/test_ui_base.py::test_ctrl_q_is_refused_while_busy`,
  `tests/test_ui_review.py::test_leave_waits_for_a_run`.
- **STD-7.20 MUST** Run scans, preflight checks and runs in thread workers and apply their answers on the UI thread,
  dropping answers that arrive after the screen was left; show the shared scan box while scanning.
  *Why:* the UI never freezes on disk work.
  *Enforced by:* `tests/test_ui_review.py::test_preflight_answer_is_dropped_once_the_screen_is_left`,
  `tests/test_ui_review.py::test_scan_box_stands_in_for_the_tree`.
- **STD-7.21 MUST** Run independent per-flavor or per-file work through `core.parallel.run_units` with
  `Config.parallelism`, never a private pool; results equal at parallelism 1 and N; one failing unit never stops the
  others ([D10][polish]).
  *Why:* one runner and one setting.
  *Enforced by:* `tests/test_parallel_runs.py::test_scan_is_the_same_with_parallelism_1_and_4`,
  `tests/test_parallel_runs.py::test_a_failing_flavor_never_stops_the_others`.
- **STD-7.22 MUST** Title bars come from `Ka0sApp.format_title`; a screen's `sub_title` reads
  `<Tool title> · <flavor> · <view>` ([D41][svb]).
  *Why:* one header on every screen.
  *Enforced by:* `tests/test_ui_base.py::test_title_bar_is_gold_then_near_white_all_bold`.
- **STD-7.23 MUST** Design for 120x30 and grow at 160x45 (trees grow; the left pane, popups and forms keep at most
  100 columns, centred); at 80x24 every screen opens, raises nothing and Tab reaches every control. Settings forms
  fit with Save visible at 120x30.
  *Why:* 120x30 is the Windows Terminal default; 80x24 is a floor, not a target.
  *Enforced by:* `tests/test_look_and_feel.py::test_tiny_terminal_still_works`,
  `tests/test_look_and_feel.py::test_popups_keep_a_readable_width_at_large`,
  `tests/test_look_and_feel.py::test_settings_forms_fit_at_base_and_keep_a_readable_width`.
- **STD-7.24 SHOULD** A screen with an `ActionBar` under its tree lifts toasts above it (`place_toasts` with
  `lift_toasts`).
  *Why:* a toast must not cover the controls being pressed.
  *Enforced by:* `tests/test_sv_browser_app.py::test_toasts_sit_above_the_action_bar`.

## 8. Keys and buttons

- **STD-8.1 MUST** Build every button with `action_button(label, kind, key)` (never `Button(...)`), the kind one of
  `destructive`, `overwrite`, `create`, `revert`, `simulate`, `confirm`, `refresh`, `navigate`, `cancel`
  ([D12][polish]).
  *Why:* one colour per kind of action; an unknown kind raises.
  *Enforced by:* `tests/test_structure.py::test_every_button_is_built_with_an_action_kind`,
  `tests/test_ui_base.py::test_action_button_kinds`.
- **STD-8.2 MUST** Button colours live only in `ui/theme.py` `ACTION_COLOURS` (one readable, distinct colour per kind, in
  step with `ACTION_VARIANTS`).
  *Why:* readable, distinguishable, clear of the WTF criterion hues.
  *Enforced by:* `tests/test_ui_base.py::test_every_kind_has_a_readable_colour_and_a_variant`,
  `tests/test_ui_base.py::test_button_colours_keep_clear_of_the_wtf_criterion_colours`.
- **STD-8.3 MUST** The same label has the same kind everywhere (Clean/Apply/Delete destructive, Organize/Assign/Update
  now overwrite, Back up create, Undo... revert, Dry run simulate, Save/OK confirm, Rescan refresh, Other flavor/Tools
  navigate, Cancel/No/Quit/Back cancel).
  *Why:* a label means one thing and one colour. *Deviation:* Interface Backup's Restore.
  *Enforced by:* `tests/test_structure.py::test_same_label_same_colour`.
- **STD-8.4 MUST** A button's key goes in `key=` (shown under the label, or `Label (k)` on a compact button), never in
  the label, and is one the screen binds to that button's action ([D17][polish]).
  *Why:* the key is found where the action is.
  *Enforced by:* `tests/test_structure.py::test_button_labels_never_spell_their_key`,
  `tests/test_look_and_feel.py::test_keys_are_on_the_buttons_and_off_the_footer`,
  `tests/test_look_and_feel.py::test_keys_are_on_the_popup_buttons`.
- **STD-8.5 MUST** End every full screen with `BottomBar`; the footer (`KeyFooter`) lists only keys no shown button
  carries, nothing under a popup, and wraps so every key stays visible at 80 columns ([D5][polish], [D17][polish]).
  *Why:* the footer has room only for keys no button shows.
  *Enforced by:* `tests/test_structure.py::test_footer_and_brand_bar_only_in_the_bottom_bar`,
  `tests/test_look_and_feel.py::test_no_keys_in_the_footer_under_a_popup`.
- **STD-8.6 MUST NOT** Repeat a shown button's key in a hint, label or guide line ([D17][polish]).
  *Why:* each key is said once, where it acts.
  *Enforced by:* `tests/test_look_and_feel.py::test_keys_are_on_the_buttons_and_off_the_footer`.
- **STD-8.7 MUST** A review's hint is `REVIEW_HINT + "a all · n none · " + FILTER_HINT + TREE_HINT +
  "f flavors · t tools"`, followed by any tool-only keys (WTF Cleaner: `1-5 criteria · b blacklist`); hints are
  `·`-separated "key action" items in a `NavHint`, built from the shared constants.
  *Why:* hints read alike and never split a key from its action.
  *Enforced by:* review, `tests/test_look_and_feel.py::test_review_hint_wraps_between_items_at_base`.
- **STD-8.8 MUST** Every review binds: Space (toggle), `a`, `n`, `x`/`c`, `/`, `r`, `z`, `f`, `t`, `q`, Esc (as `f`),
  ←/→ (pane focus) and `!`. Letter keys that may be typed (`h`, `s`, `u`, `!`) are non-priority; `/` and Space are
  priority (`ToggleTicks` passes Space through to a focused Input).
  *Why:* the same keys on every review; typing in a box never triggers an action.
  *Enforced by:* `tests/test_help.py::test_h_types_in_a_text_box`,
  `tests/test_ui_tree_filter.py::test_slash_leaves_a_number_box_and_types_into_a_text_box`; the key list itself by
  review.
- **STD-8.9 SHOULD** Put a tool's writing run on `w` and its Dry run on `y`; never use a suite or shared review key
  (`s`, `h`, `u`, `c`, `q`, `f`, `t`, `r`, `z`, `a`, `n`, `x`, `/`, `!`) for a tool action ([D15][polish],
  [D22][svb]).
  *Why:* suite keys must mean the same on every screen.
  *Enforced by:* review. *Deviations:* Organize `o`, Back up `b`, Restore `e`, restore-screen Restore `o` and Back
  `b`, Ace3 `u`.
- **STD-8.10 SHOULD** Wire presses through `ButtonActions.BUTTON_ACTIONS` (button id to action name), so a button and
  its key run the same `action_<name>`.
  *Why:* a button and its key never drift.
  *Enforced by:* `tests/test_ui_review.py::test_buttons_dispatch_by_id`.

## 9. Help and docs

- **STD-9.1 MUST** Each tool has `help.py` (sibling of `app.py`) with `HELP` (Markdown, over 500 characters, naming
  every button its screens show as `**Label**`, ending with a **Full guide:** link) and `GUIDE_URL` =
  `https://github.com/tusharsaxena/wow-tools/blob/master/docs/<tool id>.md`; `h` opens it on every full screen of the
  tool, the suite help on the menu ([D18][polish]).
  *Why:* help everywhere, complete by test.
  *Enforced by:* `tests/test_help.py::test_every_tool_has_help_with_its_guide`,
  `tests/test_help.py::test_h_on_every_screen_of_a_tool_opens_its_help`,
  `tests/test_help.py::test_every_help_link_points_at_a_file_in_the_repo`.
- **STD-9.2 MUST** Each tool has a user guide `docs/<tool id>.md`, linked from the README, documenting the warnings
  view (a `` `!` `` key row), the **Filter** button and, on destructive tools, the `⚠ USE AT YOUR OWN RISK` banner.
  *Why:* guides cannot drift from the shared UI.
  *Enforced by:* `tests/test_docs.py::test_readme_links_a_guide_for_every_tool`,
  `tests/test_docs.py::test_warnings_view_and_blacklist_key_are_documented`,
  `tests/test_docs.py::test_guides_filter_on_submit_and_risk_banner`.
- **STD-9.3 SHOULD** Follow the shared skeletons. Help: intro, how to use it (step by step), the buttons and keys,
  Warnings, Safety, then **Full guide:** last; Settings where the tool has settings beyond the backup folder. The
  section names vary (Interface Backup splits the steps into Making / Restoring a backup; Ace3 and SV Browser name
  their keys by pane), and Screenshot Organizer puts Settings before Warnings. Guide: Step by step, The review screen (keys table), the run, Dry run, results, Undo last
  ..., where backups go, interrupted runs, Settings, FAQ, Troubleshooting.
  *Why:* every tool's help and guide read alike.
  *Enforced by:* `tests/test_docs.py::test_ace3_profile_manager_guide_and_readme`,
  `tests/test_docs.py::test_sv_browser_guide_readme_and_notes`, review.
- **STD-9.4 MUST** Keep the README user-facing: the menu's terms of use word for word under `## Terms of use`, a
  version badge matching `__version__`, a `## Version history` link to `CHANGELOG.md`, no `## For developers`
  ([D6][polish]).
  *Why:* developer material lives in `CLAUDE.md` and `docs/`.
  *Enforced by:* `tests/test_docs.py::test_readme_has_the_menus_terms_of_use`,
  `tests/test_docs.py::test_version_badge_and_changelog_match_the_version`.
- **STD-9.5 SHOULD** A change that adds a user-visible behaviour or a shared module updates the guides, README,
  CHANGELOG, [architecture.md](architecture.md) and the tool's [internals](internals/) doc in the same branch (a new
  tool also gets its line and index rows in `CLAUDE.md`), and pins key phrases in `tests/test_docs.py`.
  *Why:* docs tests stop drift.
  *Enforced by:* `tests/test_docs.py`, review.
- **STD-9.6 MUST** Moving or rewording text in `CLAUDE.md`, `README.md`, `docs/architecture.md`, `docs/internals/` or
  a guide keeps the strings `tests/test_docs.py` pins, or updates the test in the same commit.
  *Why:* the docs tests read these files directly.
  *Enforced by:* `tests/test_docs.py`.

## 10. Testing

- **STD-10.1 MUST** Pass the green gate before every commit: `python3 scripts/run_tests.py`,
  `ruff check --no-cache .` and `python3 scripts/gen_event_docs.py --check` ([testing.md](testing.md#the-green-gate)).
  *Why:* CI runs the same runner and events check; ruff runs only here.
  *Enforced by:* CI (tests, events check), review.
- **STD-10.2 MUST** Stay green on the CI matrix: Linux and Windows, Python 3.10 and 3.13 (byte-compile,
  `gen_event_docs.py --check`, `run_tests.py`).
  *Why:* users run Windows and WSL; 3.10 is the floor.
  *Enforced by:* `.github/workflows/tests.yml`.
- **STD-10.3 MUST** Build every test's WoW install with a `tests/fixtures.py` builder in its own temp folder; never a
  real install, never shared files between tests.
  *Why:* hermetic tests; the parallel runner's shards must not collide.
  *Enforced by:* review.
- **STD-10.4 MUST NOT** A test touches the network: build configs with `make_config` (update checks off) and inject
  fake openers into network code.
  *Why:* deterministic, offline runs.
  *Enforced by:* review.
- **STD-10.5 MUST** Textual tests subclass `tests.fixtures.TuiTestCase` (never `IsolatedAsyncioTestCase` directly),
  run at the shared sizes `BASE` (120x30), `LARGE` (160x45), `TINY` (80x24), and `await settle(app, pilot)` before
  asserting.
  *Why:* asyncio debug off (about 10x faster), the confirm guard off, and no race with workers on slow CI.
  *Enforced by:* review.
- **STD-10.6 SHOULD** Use the shared helpers (`submit_filter`, `accept_disclaimer`, `stage_sv_edit`, `footer_keys`,
  `assert_keys_on_buttons`, `self.confirm_guard(seconds)`), pass `notifications=True` to `run_test` when asserting on
  toasts, and drive tools through `WowToolsApp(..., tool_options=...)` from the menu.
  *Why:* each helper encodes a spec rule once.
  *Enforced by:* review.
- **STD-10.7 MUST** Test logging with `core.events.capture_events()` (strict, in memory), never by reading log files.
  *Why:* an unregistered event fails the test; tests stay off `logs/`.
  *Enforced by:* `tests/test_events.py::test_capture_events_swaps_global_log`.
- **STD-10.8 MUST** Add a new tool to every per-tool meta-test table: `TOOLS` and `RUN_ACTION` (and
  `DESTRUCTIVE_REVIEWS`, `PREPARE` as needed) in `tests/test_look_and_feel.py`, `RUN_ACTION`/`PREPARE` in `tests/test_help.py`, a builder in
  `tests/fixtures.py`.
  *Why:* the meta-tests only check tools they list.
  *Enforced by:* review.
- **STD-10.9 SHOULD** Name tests `tests/test_<tool>_<module>.py` (`test_<tool>_app.py` for the TUI); put suite-wide
  rules in the meta-tests (`test_structure`, `test_look_and_feel`, `test_help`, `test_docs`, `test_events`).
  *Why:* `-k <tool>` works and every rule has an obvious home.
  *Enforced by:* review.
- **STD-10.10 SHOULD** Write the failing test first, and name the spec decision a test pins in its docstring.
  *Why:* tests trace back to the frozen spec.
  *Enforced by:* review.

## 11. Release and vendoring

- **STD-11.1 MUST** Record every user-noticeable change in `CHANGELOG.md` (Keep a Changelog: `## [X.Y.Z] - YYYY-MM-DD`
  newest first, optional `## [Unreleased]`); never delete an entry (mark a pulled one `[YANKED]`) ([D2][polish]).
  *Why:* `core/changelog.py` shows it in-app on `c`; a test fails while `__version__` has no entry.
  *Enforced by:* `tests/test_changelog.py::test_the_real_changelog_parses_and_has_this_version`,
  `tests/test_changelog.py::test_a_yanked_release_parses_and_is_marked`.
- **STD-11.2 MUST** Cut a release only through [releasing.md](releasing.md) (bump `__version__`, changelog entry, tag
  `vX.Y.Z`, `scripts/build_release.py`, publish the zip and `SHA256SUMS`); never re-use or move a tag or replace a
  published asset.
  *Why:* zip installs verify against `SHA256SUMS`; git installs must fast-forward.
  *Enforced by:* `tests/test_release_scripts.py::test_refuses_a_tag_without_a_changelog_entry_for_its_version`,
  `tests/test_release_scripts.py::test_refuses_a_tag_whose_version_differs`, review.
- **STD-11.3 MUST NOT** Edit `vendor/` by hand: change `requirements.txt`, run `python3 scripts/update_vendor.py --lock`,
  then `python3 scripts/update_vendor.py`, and commit all three together ([vendoring.md](vendoring.md)).
  *Why:* `vendor/` is installed with `--require-hashes` from the lock.
  *Enforced by:* `tests/test_release_scripts.py::test_committed_lock_matches_requirements`.
- **STD-11.4 MUST** Vendor only pure-Python packages, each pinned with `==` (transitive ones too) and 3.10-compatible.
  *Why:* one `vendor/` runs unchanged on Windows, Linux and WSL.
  *Enforced by:* `tests/test_release_scripts.py::test_unpinned_requirement_is_refused`,
  `tests/test_release_scripts.py::test_package_without_a_pure_wheel_is_refused`.

## 12. Process

- **STD-12.1 MUST** Do multi-task work on a feature branch with a dated spec
  (`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, decision IDs), a plan and a resumable status ledger
  (`<plan>.status.md`), set up as task 0.
  *Why:* any session resumes at the first task not done; decision IDs are stable citations.
  *Enforced by:* review.
- **STD-12.2 MUST** Within an approved plan, commit once per task, updating its ledger row (status, commit,
  full-suite count), and push at each milestone; outside one, commit or push only when the user asks.
  *Why:* the ledger is the single resumable record.
  *Enforced by:* review.
- **STD-12.3 MUST NOT** Merge into master, tag or publish a release without the user's explicit go-ahead; merge and
  release are separate approvals; never file a GitHub issue to track a release.
  *Why:* the user approves each gate and tags when ready.
  *Enforced by:* review.
- **STD-12.4 MUST NOT** Edit a dated spec or plan in `docs/superpowers/` once its branch is merged, or any bundle in
  `reviews/`; cite their decision IDs instead, and record build-time choices under "Decisions taken during the build" in the ledger.
  *Why:* later sessions can trace why the code looks the way it does.
  *Enforced by:* review.
- **STD-12.5 SHOULD** End a build with a whole-branch review task (review, fix, full suite, ruff, events check), and
  after the merge delete the branches, stashes and worktrees the run created.
  *Why:* the review rows found real bugs before every merge.
  *Enforced by:* review.

---

## Documented deviations

The accepted exceptions to the rules above. A deviation not listed here is not accepted: flag it.

| Rule | What differs | Why | Decided |
|---|---|---|---|
| STD-4.5 | WTF Cleaner keeps its own `keep_cleaned` (its `cleaned-*.zip` files, 0 = keep all, the default). | Once the snapshots holding them are pruned, a cleaned zip may be the only copy of deleted data. | Ace3 spec feedback round 1 ([ace]) |
| STD-4.7 | WTF Cleaner resolves its own folder (`resolve_backup_dir`): a set `backup_dir` is used as is, with no `wtf-cleaner` subfolder; its `settings.py` builds the default from `TOOLS_SUBDIR`. | The first tool's folder layout predates `tool_root`; moving it would orphan users' backups. | [D20][svb] (tool_root moved to core for SV tools) |
| STD-5.3 | WTF Cleaner (clean, undo) and Interface Backup (back up, restore, undo) warn about a running WoW instead of refusing. | Their safety nets (snapshot, safety zip, journal) still cover the run; only in-place edits are refused. | [IB spec][ib], [D16][svb] |
| STD-5.1 | Screenshot Organizer runs no running-WoW check. | Filing screenshots does not depend on the game. | [SO spec][so] (Extras row) |
| STD-5.11, STD-5.13, STD-5.14 | Screenshot Organizer writes no originals zip and no crash marker. | It only moves or copies files with `rename_no_replace`, never overwriting; its journal is the Undo source. | [SO spec][so] |
| STD-5.13, STD-5.14 | Interface Backup restore writes no crash marker. | It detects an interrupted swap from leftover `.restoring` and `.replaced` folders (`scanner.leftover_folders`) and refuses a new restore of that flavor until they are gone. | [IB spec][ib] |
| STD-5.17 | `core/migrate.py` (`merge_folder`, `_merge_into`, the `.migrated` config copy) renames with `os.rename` after an `lexists` check or onto a `_free_name`. | Start-up migration of the suite's own folders, while the instance lock is held and before any tool runs. | review |
| STD-5.6 | SV Browser lists `Blizzard_*.lua` files. | It is a raw editor behind an at-your-own-risk disclaimer; it changes only what the user edits. | D2, D4 in the [SV Browser spec][svb] |
| STD-5.27 | A WTF Cleaner dry run writes `dryrun-*.zip` of the selected files when its backup setting is on. | Lets the user inspect exactly what a clean would remove; it deletes nothing. | `wowtools/tools/wtf_cleaner/cleaner.py`, `tests/test_cleaner.py::test_dry_run_writes_backup_but_deletes_nothing` |
| STD-6.3 | WTF Cleaner's events have bare names (`scan.started`, `clean.*`, `sv.*`, `backup.created`). | The first tool, registered before prefixes; renaming would break log readers. | Grandfathered ([adding-a-tool.md](adding-a-tool.md)) |
| STD-3.4, STD-2.6 | Interface Backup wraps two shared steps: `ToolFlow._settings_done` (a changed WoW folder says nothing) and `ReviewBase.run_preflight` (logs a running WoW first). Both call the shared one. | Tool-specific behaviour around a shared step; the structure tests allow exactly these. | `tests/test_structure.py` |
| STD-7.3 | SV Browser has no account picker; Screenshot Organizer and Interface Backup have no account level. | SV Browser shows every account by design; the others act per flavor. | [D3][svb] |
| STD-7.5, STD-8.9 | Interface Backup's second review button is Restore (`e`), not Dry run (`y`); its run is Back up (`b`). Screenshot Organizer runs Organize on `o`. | Back up only adds files, so there is nothing to simulate; `w` reads as "write". On the restore screen, Restore (the run) is `o` and Back is `b`. | `tests/test_look_and_feel.py` |
| STD-8.3 | Interface Backup's **Restore** is `navigate` on the review (it opens the restore screen) and `overwrite` on the restore screen. | The left pane has no room for a longer label. | `tests/test_structure.py::test_same_label_same_colour` |
| STD-8.9 | Ace3 Profile Manager binds `u` (unlock) on its review, shadowing the suite's update key there. | Users already know the unlock key; on any screen that binds `u` the update notice says "press u on the tool menu" instead. | [D15][polish] |
| STD-8.9 | SV Browser adds Search (`S`) in its own button row above the four action buttons. | `s` is the suite's settings key. | [D22][svb] |

[polish]: superpowers/specs/2026-10-05-suite-polish-design.md
[svb]: superpowers/specs/2026-10-06-sv-browser-design.md
[wb]: superpowers/specs/2026-10-07-warnings-and-blacklist-design.md
[ace]: superpowers/specs/2026-10-04-ace-profiles-design.md
[ib]: superpowers/specs/2026-10-04-interface-backup-design.md
[so]: superpowers/specs/2026-10-03-screenshot-organizer-design.md
