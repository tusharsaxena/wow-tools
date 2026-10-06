# Architecture

## Layers

    wow-tools.sh / .cmd    the only entry point (runs python -m wowtools). The .cmd starts Python and exits on its
                           last line, so a zip update can replace it while it runs (tests/test_launcher.py)
    wowtools/__main__.py   Python check + vendor/ on sys.path, then suite.run()
    wowtools/suite.py      no args: config migration, instance lock, the suite app; or `update`, `--version`, `--help`
    wowtools/core/         UI-free framework shared by every tool (never imports textual)
    wowtools/ui/           shared Textual pieces: theme, branding, Ka0sApp, WowToolsApp, ToolFlow, shared screens
    wowtools/tools/<tool>/ one package per tool: logic modules (UI-free) + a ToolFlow (FLOW) and its screens

`wowtools/core/` and `wowtools/ui/` together are the suite's **shared library**: in-repo reusable code, not a
separate package. Functionality two or more tools need lives there (UI-free code in `core/`, Textual code in `ui/`),
never copied into a tool and never imported from one tool into another. `tests/test_structure.py` pins the single
definitions (journal, marker, undo, progress and text helpers; the review, result, choice and settings screen bases)
and the no-cross-tool-import rule, and checks that `core/` never imports `textual` or `wowtools.ui`. The shared
modules are listed under [Core modules](#core-modules) and [UI](#ui).

There is one Textual app, `WowToolsApp` (`ui/suite_app.py`). Its first screen is the tool menu
(`ToolMenuScreen`), which stays at the bottom of the screen stack. Picking a tool builds that tool's `ToolFlow`
(`TOOLS[name].flow()`), which pushes the tool's own screens; `flow.close()` (`app.close_tool()`) pops back to the
menu. So the tools look like one connected app, while each keeps its own workflow and its own config file
(`config/<tool>.cfg`). The event log's `tool` field (and so its log folder) follows the open tool. Tools can't be
started on their own; there is no command-line mode.

Tool logic is pure Python over plain dataclasses, so the TUI and the tests drive the same functions. Front ends
stay thin.

## Core modules

The UI-free half of the shared library (`wowtools/core/`):

| Module | Job |
|---|---|
| `bootstrap` | `REPO_ROOT`, `VENDOR_DIR`, Python ≥ 3.10 check, `add_vendor_path()` |
| `paths` | WSL detection; `to_native()` / `to_stored()` translate `G:\X` ⇄ `/mnt/g/X` |
| `config` | `config/wow-tools.cfg` (`[general]`) plus `config/<tool>.cfg` per tool (`tool_config_path()`); typed accessors; `config.changed` events; `migrate_legacy_config()` splits the old root `wow-tools.cfg`. `save()` is atomic and runs on the UI thread only (the background update check hands its values back through `check_for_update(persist=...)`) |
| `migrate` | Start-up moves for renamed tools (`wowtools.tools.RENAMED_TOOLS`, one `ToolRename` line each): `migrate_tool_config()` turns `config/<old>.cfg` into `config/<new>.cfg` with the section renamed; `merge_folder()` (or `merge_folder_logged()`, which logs `folder.renamed` and never raises) moves `logs/<old>/` and `<WoW>/wow-tools/<old>/` to the new name. Never overwrites (details below) |
| `lock` | `InstanceLock` on `wow-tools.lock` (O_EXCL create; holder pid, host, start time, platform (WSL via `paths.is_wsl`, the suite's one check), token). `acquire()` returns the holder on conflict; `take_over()`; `release()` removes the file only if it is still ours. `LockInfo.stale` is known only on POSIX for a lock from this host |
| `fsutil` | `atomic_write_bytes()` (remove whatever sits at `<name>.partial` without following it, create it with `O_CREAT\|O_EXCL` (+`O_NOFOLLOW`), write, then `os.replace`, which on Windows is tried again for about a second (`REPLACE_RETRY_WAITS`) while another program holds the target open; the Ace3 Profile Manager's SavedVariables writes) and its wrapper `atomic_write_text()` (`\n` written as `os.linesep`), used for every config write; `rename_no_replace()` (refuses an existing target with no check-then-act window: a hard link then unlink on POSIX, `os.rename` on Windows; falls back to check + rename where hard links are unsupported); `free_name(folder, stem, suffix)` (`-2`, `-3`, ... for same-second names: journals, WTF backups, cleaned zips, Interface Backup zips); `remove_quietly()` (delete one of our own temporary or partial files, ignoring errors); `safe_progress(cb)` (wraps a run's progress callback so an error in it never disturbs the run; every clean, organize, backup, restore and undo uses it); `is_link(entry_or_path)` (a symlink, or on Windows a junction or directory symlink by its reparse tag; never raises); `is_real_dir(path)` (a folder that is not itself a link, from one lstat); `read_link(path)` → `(target, junction)` or None, and `make_link(target, path, junction=)` (a junction on Windows when it was one, else a symlink), which Interface Backup's Undo uses to make again a link a restore removed; `remove_tree_no_follow(path)` (delete a folder tree, removing links inside it as links and never descending into them; a link given as `path` is just unlinked) |
| `activity` | `running()` context manager that file-changing workers (clean, organize, backup, restore, undo) enter; `wait_idle(timeout)`. `suite.run()` waits on it before releasing the lock, so a worker still writing never shares its folders with a second copy |
| `events` | Registry of event names with fixed levels; JSONL + text sinks (files kept open, flushed per line, closed on a new day and at exit); `log_event()`; `capture_events()` for tests. Thread-safe: one re-entrant lock covers a record's time stamp and both sinks, so lines from parallel workers stay whole and each file is in time order |
| `parallel` | `run_units(units, fn, parallelism=, what=, label=, progress=, on_start=, on_done=, stop_on_error=False)`: `fn(unit, report)` over independent units (game versions), at most `parallelism` at once in a `ThreadPoolExecutor` (1, or one unit: a plain loop in the calling thread, in order). Returns one `UnitResult(unit, value, error)` per unit in input order; a unit's `Exception` is kept in its result (logged `parallel.unit_failed`) and the others carry on (with `stop_on_error` the units not started yet never start: `UnitResult.started` False); a `BaseException` propagates once the running units finish, and a unit not started by then never starts. `report(*args)` calls `progress(unit, *args)` (pass a `ProgressScreen`'s `report_unit`); errors in progress / `on_start` / `on_done` are swallowed. It runs inside the tool's one Textual thread worker and returns only when every thread is done, so that worker's one `activity.running()` covers them all. Logs `parallel.started` / `parallel.finished` (debug). `workers_for(parallelism, units)`, `clamp_parallelism`. Runs through it: Interface Backup's scan and back up all, the WTF Cleaner's scan of several flavors, the Screenshot Organizer's picker counts and Ace3 Undo's WTF snapshots; WTF Clean and Ace3 Apply stay serial (one crash marker per run, stop at the first failure) |
| `install` | `WowInstall` → `Flavor` → `Account` → `Character`; install auto-detection. A flavor is any `_name_` folder in the WoW folder, whatever it holds. `flavor_name(folder)` is `Flavor.display_name` for a flavor known only by its folder (journals, markers). `validate_output_dir()` refuses a tool output folder that is relative, the WoW folder, or inside a flavor's `WTF`/`Interface`/`Screenshots` (every tool with an output folder uses it on save and before use); `validate_backup_dir()` is that check for a tool's backup folder setting (WTF Cleaner, Interface Backup, Ace3 Profile Manager) |
| `journal` | Run journals, the suite standard for any tool that changes files: JSON Lines (header, one line per completed change flushed at once, `{"finished"}`, `{"undone"}`). `journal_dir(wow_path, tool)` = `<WoW>/wow-tools/<tool>/journal/`; `tool_root(backup_dir, wow_path, tool)` = `<backup_dir>/<tool>`, else `<WoW>/wow-tools/<tool>` (Ace3's `resolve_root`, Interface Backup's `resolve_backup_root`; the WTF Cleaner's backup folder holds no tool subfolder, so it keeps its own); `new_journal_path`, `JournalWriter` (`open()` exclusive-creates and writes the header, `add_entry()`, `finish()`, `discard_if_empty()`; thread-safe: every method holds its re-entrant `lock`, which a subclass also takes around a write plus its own state), `read_journal(path, path_fields=)`, `list_journals` (newest first), `latest_undoable` (newest journal with entries, never past an undone one), `mark_undone`, `prune_journals(dir, keep, event=)` (logs `event` with the removed names and `keep` when it removed any), `friendly_stamp`. Path values go through `to_stored()` / `to_native()`. Tools add their own entry fields and undo rules. `ToolJournals(tool, reader, pruned_event)` binds one tool's journals: each tool's `journal.py` makes one (`JOURNALS`) and exports its `dir` / `latest_undoable` / `prune` as `resolve_journal_dir` / `latest_undoable` / `prune_journals` (Interface Backup logs its own prune event, with the safety zips it drops) |
| `text` | `plural(n, word, words=None)` ("1 file", "2 copies") and `human_size(n)` (B, KB, MB, GB, TB; `MISSING` "—" for None): every tool's counts and sizes |
| `progress` | `ThrottledProgress(forward, interval=PROGRESS_INTERVAL)`: a worker's `progress(stage, current, total, detail)` forwarded to the UI only on a stage change, a stage's end, a report with no count, or once per `PROGRESS_INTERVAL` (0.1 s; each `call_from_thread` blocks the worker). Several workers may share one: each thread is throttled on its own (its stage and last forward kept per thread; workers should report distinct stages), and the decision and the forward run under one lock, so reports reach the UI in the order they were decided. The Ace3 scans use it. `ProgressBoard(rows, units, label=, first_stage=)`: the state a progress popup draws, written by any thread under one lock and read with `snapshot()` (a version and a `BoardView`: `RowView` rows, `done` of `units`, the newest detail). A unit takes a row when it starts (`start`, or its first `report_unit`): a row never used first, then the row of the unit that finished first; a thread starting a unit finishes the one it ran before (serial runs that only announce the next unit); untagged `report`s go to the calling thread's unit, or to an unnamed placeholder row that the first named unit replaces; a late report of a finished unit is dropped; `finish_all()` ends every unit still running when the run returns, so the board ends at `units` of `units` |
| `marker` | Run-in-progress markers: `write_marker(folder, name, data)` (atomic JSON, Path values as `str()`), `read_marker(folder, name)` (a dict, or None when missing or unreadable; never raises), `clear_marker`. Each tool keeps its own `Marker` fields and checks (the WTF Cleaner's `clean-in-progress.json`, the Ace3 Profile Manager's `edit-in-progress.json`) |
| `undo` | What the WTF Cleaner's and the Ace3 Profile Manager's Undo share: `RESTORED` / `SKIPPED` / `FAILED`, `UndoResultBase` (a result dataclass's `restored` / `skipped` / `failed` lists) and `safe_destination(wow_root, flavor, rel, prefix=, min_parts=, parent=)`, `<WoW>/<flavor>/<rel>` or None unless flavor is one plain folder name and rel a relative path without `..`, `\` or `:` under `prefix` (the Ace3 tool asks for `WTF/Account/.../SavedVariables/<file>`) |
| `backup` | Zip + `manifest.json`, verified before it is moved into place; optional `on_file(current, total, name)` hook for progress. `verify_backup(zip, expected, progress)` reads every entry back (CRC) and compares sizes. `walk_files(folder, on_link=, on_error=, on_count=)`: every regular file under a folder as `DirEntry`s (depth first, names sorted), never following a link (each goes to `on_link`), an unreadable sub-folder to `on_error`; the WTF Cleaner's `wtf_files` and Interface Backup's scanner use it |
| `snapshot` | The whole-`WTF` safety zip shared by the tools that change SavedVariables: `wtf_files(flavor, progress)` (every regular file under `<flavor>/WTF`, links skipped), `take_snapshot(flavor, folder, prefix, now, progress=, must_hold=)` (zip to `folder/<prefix>-<flavor>-<stamp>.zip`, verify, `rename_no_replace` into place), `snapshot_path`, `prune_snapshots(folder, prefix, flavor_short, keep)`. The WTF Cleaner uses `backup/backup-…`, the Ace3 Profile Manager `snapshots/snapshot-…` |
| `svfiles` | SavedVariables files shared by the tools that read or change them: the file model `SvFile` (path, flavor, account, owner character, size, mtime, SHA-256; `.addon`, `.rel`, `.owner` = `OWNER_ACCOUNT_WIDE` or `Realm/Name`) and `sha256_of`; `walk_sv_files(flavor, account=, accept=, on_error=, on_account=, on_link=)` yields `(Account, Character or None, path)` over each account's and character's SavedVariables folder, skipping a folder under a link (`under_link`, reported to `on_link`), with a file-name filter (`is_sv_file`: exactly `.lua`, the default; `is_addon_sv_file`: also not `Blizzard_*`; `candidate_files` never takes a link). Then the safety checks: `SvGuard(flavor)` (refuses a path that resolves outside `<flavor>/WTF/Account` or not directly in a `SavedVariables` folder, `SvFileError`; each parent folder is resolved once, a file that is a link in full), `lstat_or_none`, `probe_lock(path)` (rename to `<name>.wowtools-lockcheck` and straight back; the error when another program holds it), `find_locked(files, fail, report)` (`probe_lock` over `(rel, path)` pairs with a `lock_check` report each; a file it cannot put back raises the tool's `fail(error)`) and `locked_message(locked, verb)` (the one refusal text: the count, `KNOWN_LOCKERS`, "Close it and <verb> again", the first `LOCKED_LISTED` files and "…and N more"; WTF Clean, Ace3 Apply, Undo and recovery), `recover_probe_leftovers(folders)` (renames a probe leftover back after a crash) and `saved_variables_folders(flavor, account)` |
| `sv_events` | Who runs the SavedVariables write pipeline: `SvTool(name, prefix)` (the tool's name for its folders, journal and zip headers; its event prefix; `.event(short)`; `.journals`, its `ToolJournals` over `read_edit_journal` with `<prefix>.journal_pruned`) and `sv_events(prefix)`, the pipeline's event specs under that prefix, which the tool registers with its own (Ace3: `ace.*`, unchanged; SV Browser: `svb.*`) |
| `sv_apply` | The SavedVariables write pipeline (the Ace3 Profile Manager's, shared with the SV Browser): `apply_flavor(tool, flavor, units, compile, verify, root=, journal=, dry_run=, keep_snapshots=, account=, now=, progress=, write=, started=)` over `(SvFile, payload)` units: earlier-marker refusal, `SvGuard`, SHA-256 recheck, the tool's `compile(file, payload, bytes)` and `verify(edit, bytes)`, dry run, journal open, probe leftovers, lock probe, whole-WTF snapshot, originals zip `edited/`, crash marker (`Marker`, `write_marker` / `read_marker` / `clear_marker`), atomic write + read-back, roll-back (`restore_original`); `apply_flavors(tool, plan, apply_one, ...)` (one `EditJournal` per run, serial, stops at the first failing flavor, prunes journals and `prune_edited_zips`); `ApplyResult`, `MultiApplyResult`, `FlavorRun`, `FileOutcome`, `ApplyError`, `UndoError` and the one `WowRunning` (both an `ApplyError` and an `UndoError`; `refuse_running`) |
| `sv_journal` | The edit journal: `EditJournal` (`add_edited`, `add_rolled_back`), `read_edit_journal` (drops rolled-back entries), `record_recovered`, `referenced_zips` |
| `sv_undo` | `undo_run(tool, journal_path, ...)` and `recover(tool, marker, ...)`: put back from the originals zip only files still at the run's `sha_after`; refused while WoW runs or a file is locked; snapshots first (Undo: up to `parallelism` flavors at once); `destination`, `UndoResult`, `UndoOutcome` |
| `sv_verify` | Verify helpers on the re-parsed edited file: `gaps`, `check_assignments(old, old_chunk, new, new_chunk, planned, on_planned=)` (same names and order, text between unchanged, an unplanned assignment byte-identical), `rest_outside(data, start, end, cuts)` and `same_outside(old, old_spans, new, new_spans)` (bytes outside the edited spans unchanged) |
| `sv_report` | The pipeline's screen text: `STAGE_TITLES`, `DETAIL_COLUMNS`, `UNDO_COLUMNS`, `RESULT_TEXT`, `undo_confirm`, `apply_summary_rows`, `apply_detail_rows`, `undo_summary_rows`, `undo_detail_rows`, `in_backup_folder` |
| `process` | Best-effort "is WoW running?" per flavor: `running_wow_processes()` returns `WowProcess(name, path)` (PowerShell `Get-CimInstance Win32_Process` on Windows/WSL, `/proc/<pid>/cmdline` on Linux, `ps -axww -o comm=` on macOS (`-ww`: no cut to the terminal width) with the `.app` bundle as the path for a bundle's own `Contents/MacOS` executable, name-only `tasklist` fallback, `None` when the listing fails); `wow_name()` is the one name rule (the Windows `.exe` names and the macOS `World of Warcraft[ <variant>]` bundle executables, any variant except the Launcher, helper and crash-reporter processes); `processes_for_flavor()` matches the executable's parent folder to the flavor folder, ignoring case and `\`/`/`; `wow_check_for(flavor)` is the check the review screen and CLI call |
| `changelog` | `CHANGELOG.md` at the install root (a root `*.md` file, so updates ship it): `parse_changelog(text)` (Keep a Changelog `## [X.Y.Z] - YYYY-MM-DD`, optionally ending ` [YANKED]`, plus an optional `## [Unreleased]`; `## ` lines inside code fences are notes, and a fence closes only on its own character, at least as long) gives `ChangelogEntry(version, date, body, yanked)` newest first and raises `ChangelogError` on a bad heading, a duplicate version, an unclosed fence or no entry; `entry_for(entries, version)`; `load_changelog()` never raises (a missing, unreadable or malformed file gives no entries and a `problem`, logged as `changelog.unreadable`). `scripts/build_release.py` refuses a tag whose `CHANGELOG.md` has no entry for its version |
| `updater` | GitHub Releases check (24 h throttle; a future stamp never throttles; the throttled check offers the cached `latest_seen_version` only when it is a valid version newer than this one; a fresh check that finds no release clears it, so a deleted release stops being offered; `verify_cached=True`, used by the startup check and `auto_update`, re-fetches whenever the cache would be offered, so a pending update is confirmed with GitHub before it is announced or installed and the throttle only saves the request when nothing is pending; records the release's assets), git fast-forward (120 s timeout per step that kills git's whole process tree, output via temp files, no prompts: `GIT_TERMINAL_PROMPT=0`, and `ssh -oBatchMode=yes` only when no `GIT_SSH_COMMAND`/`GIT_SSH`/`core.sshCommand` is set; untracked files ignored) or zip replace with rollback (downloads the `wow-tools-vX.Y.Z.zip` asset and checks its SHA-256 against the `SHA256SUMS` asset before touching anything; without `SHA256SUMS` it refuses unless `allow_unverified_updates`, then falls back to the zip asset or the source zipball; replaces the managed names plus only the root `*.md` files the release ships; keeps 2 `.update-backup/<version>` folders: the one this update made plus the highest other version; before an older one is deleted, files in its managed folders with no file at the same path in the live install (no `__pycache__`/`*.pyc`; not a `vendor/*.dist-info` file or a path its `RECORD` lists; one `os.walk` per folder) are moved to `update-leftovers/<version>/<path>`, a taken name getting ` (2)`, and a folder whose move failed is kept for the next update, `update.backup_kept`; an existing backup of the version being replaced, left from reinstalling an older version, is carried the same way before it is overwritten, and a failed move there stops the update before anything changes); a zip update also removes `RETIRED_FILES` (the old `wtf-cleaner.cmd/.sh`) |

## Config schema

`config/wow-tools.cfg` `[general]`: `wow_path`, `last_flavor`, `check_for_updates`, `auto_update`, `allow_unverified_updates`,
`last_update_check`, `latest_seen_version`, `log_level`, `log_retention_days`, and the retention every tool shares:
`keep_backups` (`Config.keep_backups`: backups kept per flavor, WTF Cleaner snapshots and dry-run zips, Interface
Backup zips and Ace3 snapshots; default 10, 0 = keep all, negative or bad = 10) and `keep_journals`
(`Config.keep_journals`: run journals kept per tool, default 10, at least 1). Also shared: `parallelism`
(`Config.parallelism`: game versions a tool works on at once through `core/parallel.py`, default 2, clamped to 1-8,
unreadable = 2; a hard drive or a WSL `/mnt` folder should use 1). All three are edited on the setup screen
(`#keep-backups`, `#keep-journals`, `#parallelism`; Save refuses a value outside 1-8). The per-tool `keep_backups` / `keep_snapshots` / `keep_journals` they replaced
are ignored, and each tool's `save_settings` drops them (`Config.remove_retired`).
Each tool owns one file with one section. `config/wtf-cleaner.cfg` `[wtf_cleaner]`: `max_age_days`, `criterion_*`, `backup_before_delete`,
`keep_cleaned` (cleaned-files zips kept per flavor, default 0 = keep all, negative or bad = 0; the one tool-level
retention setting, which `remove_retired` leaves alone), `backup_dir` (empty = `<wow_path>/wow-tools/wtf-cleaner`, resolved by `settings.resolve_backup_dir()`) and
`last_account` (empty = all accounts) and `last_flavor_choice` (empty = all flavors, else a flavor
folder; absent until first chosen, and then the picker pre-selects `[general] last_flavor`). `config/screenshot-organizer.cfg` `[screenshot_organizer]`: `dest_dir` (empty = in place),
`copy_mode` and `last_flavor_choice` (empty = all flavors, else a flavor folder). `config/interface-backup.cfg` `[interface_backup]`: `backup_dir` (empty = `<wow_path>/wow-tools`;
zips go to its `interface-backup` folder, `settings.resolve_backup_root()`) and
`last_flavor_choice` (empty = all flavors, else a flavor folder). `config/ace3-profile-manager.cfg` `[ace3_profile_manager]`:
`backup_dir` (empty = `<wow_path>/wow-tools`; files go to its `ace3-profile-manager` folder, `settings.resolve_root()`),
`blacklist` (comma-separated `flavor:addon` pairs such as `_retail_:ElvUI`, matched ignoring case;
a bare name, from the first build, means every flavor (`"*"`) until the blacklist is next saved), `last_flavor_choice` and `last_account` (empty = all accounts). The retired `[general] backup_dir` is dropped by the migration. Paths are stored in Windows form when they point at a
Windows drive. Unknown keys are preserved, and bad values fall back to defaults.

**Renamed tools.** `suite.run()` applies every `RENAMED_TOOLS` line on each start, after the instance lock is
taken and the suite config is loaded, before the app (the Screenshot Organizer was `screenshots` before it became
`screenshot-organizer`, the Ace3 Profile Manager `ace-profiles` before it became `ace3-profile-manager`). When another copy holds the lock (not known to be stale) they are skipped until a later
start, so nothing is moved under a running copy:

- `config/<old>.cfg`: if `config/<new>.cfg` does not exist, it is written with everything from the old file (the
  tool's section renamed, other sections as they were) and the old file is removed. If it exists, only the keys it
  lacks are added; its own values win. The old file is then removed if every one of its values is in the new
  file, and otherwise kept as `<old>.cfg.migrated` (`-2`, `-3`, … if that name is taken). An unreadable old file
  stops the start with the same "Fix or delete the file" message as a bad suite config. Logged as `config.renamed`.
  A legacy root `wow-tools.cfg` with the old section is split to `config/<old>.cfg` first, then renamed.
- `logs/<old>/` and `<WoW folder>/wow-tools/<old>/` (only when `wow_path` is set): if the new folder does not
  exist, the old one is renamed. If both exist, entries that are not in the new folder are moved into it,
  sub-folders (such as `journal/`) are merged the same way, entries already there are left in the old folder,
  and the old folder is removed only if it ends up empty. Logged as `folder.renamed` (a warning when something
  clashed or failed to move). A folder failure never stops the start (`merge_folder_logged()`).
- Not moved by the suite: a tool folder inside a folder the user chose. The Ace3 Profile Manager moves its own
  `<backup_dir>/ace-profiles` when it opens (`settings.migrate_backup_root()`), and Undo and recovery look for an
  `edited-*.zip` by name in the current `edited/` folder when the path a journal or marker recorded is gone
  (`undo._moved_zip()`).

## WTF Cleaner data flow

    scan(flavor, account=None, progress=None) → ScanResult(installed, enabled, groups[SVGroup[SVFile]])
    evaluate(scan, Criteria) → Proposal(items[ProposalItem(group, files, reasons)])
    TUI selection → execute(items, flavor, dry_run, backup, backup_dir, progress=None, journal=None)
                      → CleanResult(outcomes, backup_path, snapshot_path, restored, journal_path)
    undo_clean(journal_path, wow_root, progress=None) → UndoResult(outcomes[UndoOutcome])

`scan(account=NAME)` is fully scoped: only that account's SavedVariables are read. `account=None` is the whole
flavor. Either way the enabled set is per account (`ScanResult.enabled_by_account`, `enabled_for(account)`): the
"not enabled" rule judges a group, account-wide or character, by the addons enabled on any character of its own
account (every installed addon for an account with no characters); `ScanResult.enabled` is the union over the
accounts with characters, for logs. A single-account flavor gets exactly the old flavor-wide union.

All flavors (`tools/wtf_cleaner/multi.py`, UI-free) runs the same per-flavor functions and changes none of them:

    scan_flavors(flavors, account=None, progress=None, parallelism=1) → [FlavorScan(flavor, result | None, error | None)]
    execute_flavors([(flavor, items), ...], dry_run, backup, backup_dir, account, keep_backups,
                    progress=None, on_flavor=None, journal_dir=None, keep_journals=10, keep_cleaned=0)
                      → MultiCleanResult(dry_run, runs[FlavorRun], journal_path, journals_pruned)

`scan_flavors` reads up to `parallelism` flavors at once (`core/parallel.py`, `[general] parallelism` read by the
review on the UI thread; results in flavor order). It records a `ScanError` on that flavor and carries on; any
other error keeps the flavors not started yet from starting and is raised once the running ones ended. With
several flavors the progress label starts with the flavor's name, and with several at once the counts passed on
are every running flavor's added up (under a lock), so the one scan bar never jumps between flavors.
`execute_flavors` stays serial whatever the setting: every flavor shares the one crash marker in the backup folder
(`clean-in-progress.json`, one pointer for the recovery screen) and a failure stops the run before the next
flavor ("not started"). It calls `execute()` per flavor, so each flavor gets its own WTF
backup, marker, cleaned-files zip, post-clean check and pruning; a `BackupError` or `CleanError` stops the run
before the next flavor (`clean.flavors_stopped`), and each `FlavorRun.status` is `done`, `stopped` or
`not_started`. The review screen uses both for one flavor too, so the single-flavor path is the same code.

`execute` guards every path (it must resolve inside `<flavor>/WTF/Account/**/SavedVariables`) and re-checks
size and mtime. For a real clean it then opens the run journal (when given one), takes the safety snapshot and
writes the marker (`safety.py`), writes and verifies the selective backup, and only then deletes, journaling each
file right after it is deleted. A dry run writes the backup (as `cleaned/dryrun-<flavor>-<account>-<stamp>.zip`) and deletes nothing; it takes
no snapshot, writes no journal, and then prunes the flavor's dry-run zips to the newest `keep_backups`
(`prune_dry_run_zips`). Real `cleaned-*.zip` files are pruned only when `[wtf_cleaner] keep_cleaned` is above 0: a
real clean that deleted something then keeps the flavor's newest `keep_cleaned` (`prune_cleaned_zips`, any account,
newest by the stamp in the name, one `os.scandir` and no stat per file; the zip this run wrote is always kept and
counts as one; `CleanResult.cleaned_pruned`, event `backup.cleaned_pruned`, shown on the result's "Cleaned files
zip" row). A dry run never prunes them. Undo (always the latest clean) is unaffected, since that clean's zip is
always kept; a pruned older clean can only be restored by hand from its WTF backup while one is kept.

### Run journal and Undo last clean (`tools/wtf_cleaner/journal.py`, `undo.py`)

Both UI-free, built on `core/journal.py`. A real clean (the review screen passes
`journal_dir = journal.resolve_journal_dir(wow_path)`, i.e. `<WoW>/wow-tools/wtf-cleaner/journal/`) writes one journal for
the whole run, across All flavors:

    {"version": 1, "started": iso, "tool": "wtf-cleaner", "suite_version": "...", "flavors": [...], "account": ..., "backup_dir": stored}
    {"action": "deleted", "flavor": "_retail_", "path": stored, "rel": "WTF/Account/...", "size": n, "mtime": t, "zip": stored | null, "snapshot": stored}
    {"finished": iso, "entries": n}
    {"undone": iso, "restored": n, "skipped": n}

`execute_flavors` creates the `CleanJournal` and passes it to each `execute()`. `execute` opens it (header
written, once per run) before the lock check and the WTF backup (the lock check is preceded by
`recover_probe_leftovers`, which renames back any `<name>.wowtools-lockcheck` an interrupted probe left in any
SavedVariables folder in the clean's scope (`saved_variables_folders(flavor, account)`), never overwriting, `clean.probe_recovered`; the scanner never proposes such a file
and adds a `ScanWarning` for it); if that fails it raises `CleanError` and nothing
is deleted (`clean.journal_failed`). An entry is appended after each delete; if that append fails the delete loop
stops like any unexpected error, so that flavor's deletions are restored from its WTF backup. A journal with no
entries is removed, and after a clean that wrote one `prune_journals` keeps the newest `keep_journals`
(`clean.journal_pruned`). When a flavor's deletions are put back after an error, `execute` appends
`{"action": "rolled_back", "flavor", "rels"}`; `read_journal` drops those entries, and a journal left with none is
removed, so a rolled-back clean never hides the clean before it. A flavor that deleted nothing does not prune WTF
backups (an earlier clean's Undo may need them).

`latest_undoable(journal_dir)` is the only journal offered (never past an undone one). `undo_clean()` walks its
entries newest first: the destination is `<wow_root>/<flavor>/<rel>`, refused (skipped) unless `flavor` is a plain
folder name and `rel` starts with `WTF/` and has no `..`; a file that exists again is skipped; otherwise the entry
is extracted, exclusive create, from the cleaned-files zip (by its name, which is `rel`) or, when there is no zip,
the zip is gone or lacks it, or its size differs, from the WTF backup by `rel`. The written size must match the
entry (else the partial file is removed and the entry fails) and the file's mtime is put back. Each zip is opened
once. Afterwards the journal is marked undone, unless nothing was restored and something failed (a source
that is missing for now, such as an unplugged backup drive), so Undo can be tried again (`clean.undo_started`, `clean.undo_restored`, `clean.undo_skipped`,
`clean.undo_failed`, `clean.undo_completed`).

### Safety snapshot (`tools/wtf_cleaner/safety.py`)

UI-free; thin wrappers over `core/snapshot.py` and `core/svfiles.py` (names, messages and file names unchanged). `take_snapshot()` zips the whole `<flavor>/WTF` folder to `backup/backup-<flavor>-<stamp>.zip`
in the backup folder and verifies it; the user-facing name is "WTF backup". It is kept after the clean, and
`prune_snapshots(backup_dir, flavor_short, keep)` deletes all but that flavor's newest `keep_backups`
(`backup-<flavor>-<stamp>[-N].zip` names only, newest by stamp then N; 0 keeps all, as does `core/snapshot`).
The zip of the files a clean removes is `cleaned/cleaned-<flavor>-<account or all>-<stamp>.zip` (`cleaner.cleaned_zip_path`). Both names get `-2`, `-3`, ... (`fsutil.free_name`) when a run in the same second already used them, and finished zips are moved into place with `fsutil.rename_no_replace`, so a backup is never replaced. `write_marker()` / `read_marker()` / `clear_marker()` (over `core/marker.py`) manage
`clean-in-progress.json` (`Marker`: snapshot, flavor, flavor_path, started, pid, suite_version, files).
`restore_deleted()` extracts exactly the given relative paths and never overwrites an existing file.
`recovery_message()` is the text the TUI's `RecoveryScreen` shows for a leftover marker.

In `cleaner.execute`:

- If the snapshot or marker fails, a `BackupError` is raised and nothing is deleted.
- A leftover marker from an earlier clean also refuses a real clean.
- An unexpected exception while deleting (anything but a per-file `OSError`, including `KeyboardInterrupt`)
  restores only this run's deletions and raises `CleanError` (with `.restored`).
- If that restore fails, the marker is kept.
- On success (including per-file failures) `check_clean()` compares the WTF folder with the snapshot
  (`clean.validated`, or `clean.check_failed` with the problems in `CleanResult.check_problems`), the marker is
  cleared, the snapshot is kept, and older snapshots are pruned (`snapshot.pruned`).
- Nothing ever restores automatically at start-up.

### Progress callbacks

- `scan(progress=cb)` calls `cb(current, total, label)` once per SavedVariables folder. The total counts every
  account and character folder in scope.
- `execute(progress=cb)` calls `cb(stage, current, total, detail)` with the stages listed in
  `report.STAGE_TITLES` (total 0 = unknown). The callback is wrapped so an exception inside it is swallowed and never disturbs a clean.
- Both run in the caller's thread (a scan of several flavors: each flavor's in its own pool thread). The TUI runs
  scans and cleans in thread workers: the scan's callback forwards to the UI with `app.call_from_thread` (the scan
  progress bar); a clean's goes straight to
  `CleanProgressScreen.report` (its board, drawn by the UI thread), with `start_unit` as `on_flavor`.

## Screenshot Organizer data flow

    scan(flavors, dest_dir, progress=None) → Plan(flavors[FlavorPlan(items[ShotItem], skipped[Skipped])], dest_dir)
    TUI selection → execute(items, dest_dir, copy, dry_run, journal_dir, keep_journals, progress=None)
                      → OrganizeResult(outcomes[Outcome], journal_path, pruned)
    undo(journal_path, wow_root, progress=None) → OrganizeResult(undo=True)

Modules in `tools/screenshot_organizer/` (all UI-free except `app.py` and `review_screen.py`): `naming` (`parse_shot_name`,
`day_parts`), `settings` (`ShotSettings`, `source_dir`, `target_root`, `validate_dest`),
`planner`, `organizer`, `journal` (`resolve_journal_dir`), `undo` and `report` (labels, stage titles, rows and the confirm text).

**Targets.** `target_root(flavor, dest_dir)` is `<dest_dir>/<flavor folder>`, or the flavor's `Screenshots`
folder when `dest_dir` is `None` (in place). A shot goes to `target_root/YYYY/MM/DD/<name>`; the day comes from
`WoWScrnShot_MMDDYY_HHMMSS.<jpg|jpeg|png|tga>` only. `validate_dest` wraps `install.validate_output_dir` (a full path, not
the WoW folder, not inside any flavor's `WTF`, `Interface` or `Screenshots`); it runs on the settings screen and
again in `action_rescan`, which refuses to scan a hand-edited bad `dest_dir`.

**Scan.** One listing per `Screenshots` folder (top-level files only) and one names-only listing
(`planner.list_names`) per target day folder. Only a name already at the target is stat'ed, to set the state:
`new`, `maybe_duplicate` (same size) or `conflict` (other size). In copy mode (`scan(..., copy=True)`) a same-size
target is `filed` instead (the modified time is not compared: not every copy keeps it): the original stays in `Screenshots` after a copy, so it is not "to file" (`FlavorPlan.to_file` leaves it out), the review
screen lists it in an unticked Already filed group, and `execute` still compares hashes if it is ticked.
`waiting_count(flavor, dest_dir, copy=)` (the flavor picker's counts) lists names only; in copy mode it also lists
each target day folder and leaves out names already there. `count_waiting(flavors, dest_dir, copy=, parallelism=)`
runs it for every flavor, up to `parallelism` at once (`core/parallel.py`), into `{folder: count | None}` for the
picker's worker. `scan` itself stays one loop (cheap listings sharing one target-folder cache), and so does
`execute` (one journal, one shared cache, and a journal write error must stop the whole run). Unparsable names become `Skipped`. Progress is
`cb(current, total, label)` once per flavor, plus a tick every 500 files.

**No per-file resolve or stat.** `resolve()` and per-entry `stat` are slow over WSL drvfs, so neither the scan
nor `execute` calls them per file. `execute` reuses one listing per source folder (re-check: missing or changed
size gives `skipped`) and one names-only listing per target day folder. Beyond that it stats only where a hash, a
copy, or the no-overwrite `lexists` check right before a rename or copy needs it (POSIX `rename` overwrites).
`os.makedirs` runs once per day folder.

**Guard.** Every item is checked lexically, with no resolve: `src.parent` must equal `source_dir(flavor)`, the
name must parse to the planned day, and `dst` must equal exactly
`target_root(flavor, dest_dir)/YYYY/MM/DD/<src.name>` with no `..` part. A failure is `refused` and the file is
not touched. The TUI passes the scanned plan's `dest_dir`, so a settings change after a scan can't make the guard
refuse every file.

**Filing.** A same-name file at the target is hashed (SHA-256): identical means `duplicate_removed` (move: the
source is deleted) or `already_filed` (copy); different means `conflict`, and neither file is touched. A move is
`fsutil.rename_no_replace` (POSIX: hard link then unlink, so a file that appears at the target is never
replaced; Windows: `os.rename`); on `EXDEV` (and always in copy mode) `copy_verified` copies to `<name>.partial`, checks size and
SHA-256, then renames into place. After a cross-device move a failed source delete is `source_left`, a warning. A
`FileExistsError` from the last check is `conflict`. Nothing is ever overwritten. A dry run walks the same checks,
hashing included, and reports `would_move` / `would_copy` / `would_remove_duplicate`; it creates no folders and
writes no journal. A per-file `OSError` is `failed` and the run continues; anything else (including
`KeyboardInterrupt`) raises `OrganizeError` with `.result`. Progress is `cb(stage, current, total, detail)` with
the stages in `report.STAGE_TITLES` (`organize`, `prune`, `undo`), wrapped by `fsutil.safe_progress`.

**Journal** (`journal.py`, the organizer's entries on top of `core/journal.py`). A real run writes `<WoW>/wow-tools/screenshot-organizer/journal/journal-<YYYYMMDD-HHMMSS>.jsonl`
(`-2`, `-3`… on a clash), JSON Lines:

    {"version": 1, "started": iso, "copy": bool, "dest_dir": stored path | null, "suite_version": "...", "flavors": [...]}
    {"action": "moved" | "copied" | "copied_source_left" | "duplicate_removed", "src": stored, "dst": stored, "size": n}
    {"finished": iso, "entries": n}
    {"undone": iso, "restored": n, "skipped": n}

`JournalWriter.open()` writes the header before anything is touched; if that fails the run raises
`OrganizeError` and nothing moves. Each action is appended and flushed after it happens. If an append fails, the
change is reported done with a "not journaled" reason and the run stops (`JournalWriteError`). A header-only
journal is deleted, so a run that changes nothing leaves none. After a run that wrote one, `prune_journals` keeps
the newest `keep_journals` (undone ones count). `read_journal` skips torn lines (it reads with
`errors="replace"`), and `mark_undone` starts its record on a new line after a torn last line.

**Undo** (`undo.py`). `latest_undoable(journal_dir)` returns the newest journal with entries that is not undone,
and never reaches back past an undone one: one level of undo only. `undo()` walks the entries newest first. Each
entry passes a guard: `src` directly in a `Screenshots` folder of a flavor under `wow_root`, with a WoW screenshot
name; `dst` exactly `target_root(flavor, header dest_dir)/YYYY/MM/DD/<src name>`, the date from the name (so a
tampered journal cannot point Undo at a file anywhere else). `read_journal` drops entries without paths or with a
size that is not a number, and `latest_undoable` treats an unreadable journal as not offered. Then:

- `moved`: if `dst` has the recorded size and `src` is free, move it back (`move_file`, copy-verify-delete across
  devices; a failed delete of the archive copy is still `restored`, with a reason); a missing `dst` with `src` back
  at the recorded size (an interrupted Undo, or put back by hand) is `undo_skipped` ("the screenshot is already
  back in the Screenshots folder"), so the journal is closed;
- `copied` / `copied_source_left`: delete `dst` if both `src` and `dst` have the recorded size (`copy_removed`);
  a missing `dst` next to an intact `src` is already undone (`copy_removed`, "the copy was already gone");
- `duplicate_removed`: if `src` is free and `dst` has the recorded size, `copy_verified(dst, src)`;
- for `moved` and `duplicate_removed`, a `dst` that is missing altogether is `failed` (it may be on an unplugged
  archive drive; its reason says to connect it and try Undo again, shortened to "the filed copy is missing" when
  the journal is marked undone anyway); anything else, or a
  failed check, is `undo_skipped`; an `OSError` is `failed`.

Then the `DD`, `MM` and `YYYY` folders it touched are removed bottom-up while empty and digit-named, and an
`undone` line is appended (even when every entry was skipped), unless nothing was put back and something failed:
then `OrganizeResult.marked_undone` is False, the journal stays undoable and the result says Undo can be tried
again (the WTF Cleaner's rule).

## Interface Backup data flow

    scan_flavors(flavors, with_stats=CHEAP_STATS, progress=None, parallelism=1) → [FlavorScan(flavor, parts{Interface, WTF: PartScan}, leftovers)]
    back_up_all(scans, root, keep, progress=None, on_flavor=None, on_flavor_done=None, parallelism=1) → [BackupOutcome(flavor, kind, path, files, bytes_in, bytes_zip, links, missing, reason, pruned)]
    open_backup(zip) → BackupContents(kind, flavor_short, flavor_folder, created, parts, files, links)
    plan_restore(contents, scan_flavor(flavor, with_stats=True), parts, disk_usage) → RestorePlan(removed, newer, links_kept, links_removed, unreadable, bytes_needed, free_bytes, leftovers, current_bytes)
    restore(plan, root, journal_dir, keep_journals, progress=None) → RestoreResult(flavor, backup, parts[PartOutcome], safety_zip, journal_path)
    undo_restore(journal_path, wow_root, root, progress=None) → RestoreResult(undo=True)

Modules in `tools/interface_backup/` (all UI-free except `app.py`, `review_screen.py` and `restore_screen.py`):
`settings` (`BackupSettings`, `resolve_backup_root` = `<backup_dir or WoW/wow-tools>/interface-backup`,
`core.install.validate_backup_dir` checks the folder), `journal` (`resolve_journal_dir` = `<WoW>/wow-tools/interface-backup/journal`), `catalog` (names
`backup-<flavor>-<stamp>[-N].zip` and `pre-restore-<flavor>-<stamp>[-N].zip`, `list_backups` newest first,
`read_parts` (the manifest's parts only, never raises), `prune_backups`, `prune_safety`), `scanner`, `backup`,
`restore`, `undo`, `journal` and `report` (labels, stage titles, rows and dialog texts). `<flavor>` is the flavor's
short name.

**Scan.** `scan_part` walks `<flavor>/<part>` with `core.backup.walk_files`: directory listings only, never
`resolve()`, never following a link. A link inside a part goes to `PartScan.links` (a `<Part>/<rel>` string,
never zipped); a part that is itself a link is `linked` and is neither backed up nor restored. An unreadable
sub-folder is a `PartScan.errors` line (at most 20 logged per part as `ibackup.scan_warning`). `leftovers` are
`<part>.restoring` / `<part>.replaced` beside the parts. `CHEAP_STATS` is `os.name == "nt"`: `DirEntry.stat()` is
free on Windows but a round trip per file over WSL drvfs, so elsewhere the review's scan leaves sizes `None` (counts
only, no space alert on the backup confirm). The restore screen always scans with stats (it needs mtimes for
`newer`). `scan_flavors` reads up to `parallelism` flavors at once (read-only, independent; scans in flavor order,
each flavor's events logged by its own thread); an unexpected error keeps the flavors not started yet from
starting and is raised once the running ones ended. The scan bar has no total, and each report names its flavor.

**Backup** (`backup.py`). No journal: nothing in the game folders changes. `write_zip` writes `<Part>/<rel>`
entries plus `manifest.json` (`version`, `kind` backup | pre-restore, `flavor`, `flavor_folder`, `created`,
`suite_version`, `parts`, `parts_existing`, `files[{path, size, mtime}]`, `links`) to `<name>.partial`, runs
`verify_backup`, then `rename_no_replace`; any failure (Ctrl+C included) removes the `.partial` and is a
`BackupError`. Each file is opened without following links (POSIX `O_NOFOLLOW | O_NONBLOCK` plus `fstat`; Windows
lstat first), and each ancestor folder is lstat-checked once: a file gone, turned into a link or no longer regular
since the scan is left out and listed in `missing`; a part that vanished or lost every file is not claimed in the
manifest. Entry dates are clamped to the DOS range. `back_up` skips a flavor with no real part (`skip_reason`:
no folder, or links; the review has no tick for such a flavor and passes only ticked flavors with data, so from the UI no Skipped row comes back), then prunes the
flavor's `backup-*` zips to `keep_backups` after a success only (`protect=` the new zip; 0 keeps all; never safety
zips, other flavors or foreign files). `back_up_all` runs up to `parallelism` flavors at once
(`core/parallel.py`; each flavor writes its own zip and prunes only its own, so they are independent; outcomes in
flavor order); one failing never stops the others, and an unexpected error is that flavor's `failed` outcome
(`parallel.unit_failed` with the traceback, then `ibackup.backup_failed`). `on_flavor(name)` runs in the flavor's
pool thread before it starts and `on_flavor_done(name)` after: the review passes the popup's `start_unit` /
`finish_unit`, so each flavor's untagged reports land in its own row. Stages `backup`, `verify`, `prune`.

**Open and plan** (`restore.py`). `open_backup` reads only the manifest and the entry list: every entry name must
be safe (`split_entry`: relative, first part `Interface`/`WTF`, no `..`, backslash, drive, `<>:"|?*`, NUL or
trailing dot/space; on Windows also control characters and device names), no two entries the same ignoring case
(`case_key` = per-character `lower()`, as NTFS compares), no file where another entry needs a folder, and the
manifest's files exactly the zip's entries in parts it claims. Otherwise `RestoreError` ("not an Interface Backup
zip", "manifest is damaged", ...). `plan_restore` refuses another flavor's backup, a part the backup lacks and a
part that is a link; under WSL a target on `/mnt/<letter>/` gets the Windows name rules too
(`check_target_names`). It compares case-insensitively: `removed` (on disk, not in the backup), `newer` (on disk
more than 2 s newer), `links_kept`, `links_removed` (the backup holds a file or folder at the link's path, or a
file above it), `unreadable` (the chosen parts' scan errors), `bytes_needed` and the flavor drive's free bytes
(`low_space`), and `current_bytes` (what the chosen parts hold now, the most the safety zip can take; None without
sizes), which the restore confirm compares with the backup drive's free space.

**Restore.** `restore()` refuses (RestoreError, nothing changed, `ibackup.restore_failed`) on a leftover, a journal
that cannot be opened, a backup that does not verify, a part that turned into a link, or a safety backup that
fails or would not open for Undo (`_check_safety`, which then deletes it). In order: journal header (`flavor`,
`flavor_path`, `backup`, `parts`), verify, safety zip `pre-restore-<flavor>-<stamp>.zip` of the chosen parts as
they are (`write_zip(kind="pre-restore")`), journal `{"action": "safety_backup", "zip", "parts_existing"}`, then
per part `replace_part`: extract to `<part>.restoring` (exclusive create, manifest mtimes; an `os.utime` failure
keeps the extraction time), move the kept links into it, rename `<part>` → `<part>.replaced` and `<part>.restoring`
→ `<part>`, `on_swapped(existed)` writes a `{"action": "link_removed", "part", "rel", "target", "junction"}`
per link the swap removed (read with `read_link` just before; a zip never holds links) and then
`{"action": "replaced", "part", "existed"}`, then
`remove_tree_no_follow(<part>.replaced)` (a failure is `replaced_left`). An error before or during the swap
(including Ctrl+C) rolls the part back exactly (`rolled_back`; `failed` when the rollback itself fails) and the
next part goes on. A part present on disk that the safety zip does not hold is left alone. A journal entry that
cannot be written stops the run (`RestoreStopped`, the reason naming the `.replaced` folder and the safety zip).
After a restore that changed a part, `_prune` keeps `keep_journals` journals and deletes only the safety zips
that the pruned journals named and no kept journal names (never the zip restored from, never one no journal of
this WoW folder named). Stages `verify`, `safety`, `safety_verify`, `extract`, `swap`, `cleanup`.

**Journal and Undo** (`journal.py`, `undo.py`). `<WoW>/wow-tools/interface-backup/journal/journal-<stamp>.jsonl`:

    {"version": 1, "started": iso, "flavor": "_retail_", "flavor_path": stored, "backup": stored, "parts": [...], "suite_version": "..."}
    {"action": "safety_backup", "zip": stored, "parts_existing": [...]}
    {"action": "link_removed", "part": "Interface", "rel": "AddOns/Dev", "target": "D:\\dev\\Dev", "junction": true}
    {"action": "replaced", "part": "Interface", "existed": true}
    {"finished": iso, "entries": n}
    {"undone": iso, "restored": n, "skipped": n}

`latest_undoable` offers the newest journal with a `replaced` entry that is not undone (never past an undone
one). `undo_restore` checks everything before changing anything (RestoreError, `ibackup.undo_failed` with
`refused`): not undone, the journal's flavor a flavor folder of `wow_root` at the same path, `replaced` entries
naming Interface/WTF once each, `link_removed` entries with a known part, a safe `rel` (`split_entry`) and a
target, the safety zip in `root`, a regular file, of kind pre-restore and the same flavor,
holding every part that existed, no leftovers, and it verifies. Then, newest entry first, a part that existed is
replaced from the safety zip with `replace_part` (its links kept; no further safety backup), then each link the
restore removed from it is made again where nothing is now (`make_link`; one that cannot be made turns the part
`failed`, its reason naming the link and target), and a part the restore created is renamed to `<part>.replaced`
and deleted without following links. The journal is marked undone
unless every part was left as it was (then Undo can be tried again).

### Interface Backup screens

`app.py` holds `InterfaceBackupFlow` (`FLOW`: `require_install` → `BackupSettingsScreen` on the tool's first open
→ `FlavorScreen(include_all=True, last=last_flavor_choice)`, whose notes (`report.picker_note`: "N backups, last
…" / "no backups yet") a worker fills from `list_backups` → `BackupReviewScreen`) and `BackupSettingsScreen`
(backup folder with a live "Zips go to:" line; `validate_backup_dir` errors inline; retention is the shared
`[general]` setting). `s` opens the shared WoW-folder settings, then this tool's. If the WoW folder changes, the review (or the
picker's choice) goes back to the flavor picker. The screens follow the Screenshot Organizer's shape (left pane,
tree, bottom `#summary` line, popups for confirm and progress) and its shared CSS. `review_screen.py` holds:

- `BackupReviewScreen(cfg, tool_cfg, flavors, scope_label, *, wow_check, disk_usage, wow_root)`: `TreeFilter`
  (`ui/tree_filter.py`) and `ReviewBase` (`ui/review.py`), `two_pane_css`. Left pane `#filters`: "Backup folder", "Keep"
  ("newest N per flavor" / "all backups"), the `FilterInput` (`/`; the pane's first control), the action row **Back up** (create), **Restore** (navigate: it opens the restore screen), **Rescan**, **Undo last
  restore** (revert; disabled when nothing is undoable), and the NavHint. Right: a `ReviewTree` (`#flavors`), filled
  after a worker scans (`scan_flavors`, `list_backups`, `latest_undoable`): the root (scope label, files and size
  ticked) → a node per flavor (tick, `report.flavor_text`) → read-only children: `Interface` and `WTF`
  (`part_text`), `Links (n)`, a leftover notice, `Scan warnings (n)` and `Backups (n)` (`backups_title`; safety
  zips counted apart). Links, warnings and Backups load their children on expand; a Backups node lists the
  flavor's zips newest first (`backup_text`: kind, date and time, parts, size), their parts read per
  zip by a worker (`read_parts`; `PARTS_PENDING` until read). Ticks are on flavors with something to back up only
  (and the root): `READ_ONLY` nodes keep their label on `relabel_branch`; ticks survive a rescan. The filter
  matches the flavors as `ModelNode`s (`_model`: names, part names, link paths, warning lines, "backup <when>";
  lazy groups included, and a group it opens gets its children at once); a flavor key shows (`filter_keys`) while
  anything in the flavor matches, and `all_tick_keys` is the flavors with data. `#summary` is
  `selection_text` plus the highlighted backup in full (`backup_detail`) or how to pick one, then "Restore blocked
  for …", scan-warning counts and the filter's hidden-ticks line. Keys Space, `a`, `n`, `/`, `b`, `e` (or Enter on a backup node: restores the
  highlighted backup; with none highlighted a notice says how), `r`, `z`; `f`/Esc, `t`, `q` leave. Back up,
  restore and undo each run the running-WoW check (and the backup drive's free space, for a backup and for a
  restore's safety backup; the undo also reads its journal there) in a worker, with "Checking for running
  programs…" on `#summary`, then a `ConfirmScreen` (Yes green for Back up, red for Restore and Undo); the job runs
  in a worker with `app.busy` set, inside `activity.running()`, its per-file progress landing on the progress
  screen's board (`report`, `start_unit` as `on_flavor`), which the UI thread draws every `PROGRESS_INTERVAL` = 0.1 s:
  no report waits for the UI thread, and an `Interface` folder can hold tens of thousands of files. A
  `RestoreError` is a "Nothing was changed" notice, a `RestoreStopped` a notice plus its result screen; then a
  rescan;
- `BackupProgressScreen(title, first_stage, flavors)`, a `ProgressScreen` (ids `ibackup-*`) for a backup (a row per flavor in turn), restore or undo;
- `BackupResultScreen`: a `ResultBase`; `#result-summary` (Item/Value, `report.backup_summary_rows`) above
  `#result-table` (a row per flavor, `report.BACKUP_RESULT_COLUMNS`); `r`, `e` (rescan, then open every flavor's
  Backups and put the cursor on the newest non-safety zip, the one just made), `f`, `t`, `q`.

`restore_screen.py` holds:

- `RestoreScreen(info, flavor, *, disk_usage)`: `FilterBox` (the filter alone: nothing to tick; `LOG_SCREEN`
  `ibackup_restore`, `filter_changed` redraws the plan through it; the notes are never filtered), `TwoPaneFocus`
  and `ButtonActions`, `two_pane_css(width=46)` (two buttons only, and
  the tree's root and effect titles fit at 120 columns). Left: "Backup" (flavor, kind and date; size, parts
  and files once read; "made …" when the manifest's date differs), "Restore" with an `Interface` and a `WTF`
  `Ka0sCheckbox` (`#part-Interface`, `#part-WTF`; disabled for a part the backup lacks or that is a link; both off
  when a leftover, another flavor's backup or an unreadable zip blocks it), the `FilterInput`, **Restore** (overwrite, `o`) and **Back**
  (`b`/Esc). Right: a `ReviewTree` (`#effects`) rooted at "<flavor> · <date>": "Will be removed (N files)" and
  "Newer now than in the backup (N files)" (open, one node per folder group from `report.group_items`, files on
  expand), "Links kept", "Links replaced", "Could not be read" (lines on expand), a low-space leaf, or "Nothing on
  disk would be lost"; while loading, with no box ticked or when blocked, one line saying so. `open_backup` +
  `scan_flavor` run in one worker, `plan_restore` in another on every box change (a generation counter drops
  stale plans); **Restore** is enabled only once the current plan is in. `#summary` is `report.restore_summary`.
  The confirm shows `report.restore_confirm_alerts` (one counted line per kind);
- `RestoreResultScreen(result)`: a `ResultBase`; `#result-summary` (`report.restore_summary_rows`: flavor, finished
  or not, zip, safety zip and journal names, the zips' folder) above `#result-table` (a row per part,
  `report.RESTORE_RESULT_COLUMNS`); **Undo** (key `z`, shown on the button) only for a restore whose journal recorded a swapped part
  (`RestoreResult.swapped`: a part `restored` or `replaced_left`; a swap the journal could not record does not
  count; it rescans, then undoes if that journal is still the undoable one); `r`, `f`, `t`, `q`.

## Ace3 Profile Manager data flow

    scan_flavors(flavors, account=None, progress=None) → ScanResult(flavors[FlavorScan(flavor, accounts[AccountScan(files[AddonFile(SvFile, dbs[AceDb])], characters)], warnings, error)])
    Staging.from_scan(scan, locked=) → delete / assign / rename / copy / remove_leftovers / keep_only_default / everyone_to_default → OpResult(applied, refused, notes)
    compile_file(states_of_one_file, data) → FileEdit(file, data, changes, expected{sv_name: Expected})
    verify_edit(edit, old_bytes) → [problems]
    apply_flavors([(flavor, [DbState]), ...], root, journal_dir, keep_journals, keep_snapshots, dry_run, account, wow_check, progress)
      (the review passes [general] keep_backups as keep_snapshots and keep_journals; 0 snapshots = keep all)
                      → MultiApplyResult(dry_run, runs[FlavorRun(flavor, result: ApplyResult, error)], journal_path)
    undo_run(journal_path, wow_root, root, keep_snapshots, wow_check, progress, parallelism=1, on_flavor=None,
             on_flavor_done=None) → UndoResult(outcomes, snapshots)
    recover(marker, root, journal_dir, keep_snapshots, wow_check, progress) → UndoResult

Modules in `tools/ace3_profile_manager/` (all UI-free except `app.py`, `review_screen.py`, `tree_view.py`, `popups.py`,
`blacklist_screen.py` and `result_screen.py`): `events`, `settings`, `model`, `scanner`, `ops`, `verify`, `editor`, `multi`,
`journal`, `undo` and `report` (labels, tags, confirm texts). The write pipeline is core's (`core/sv_apply.py`,
`sv_journal.py`, `sv_undo.py`, `sv_verify.py`, `sv_report.py`): `editor`, `multi`, `journal` and `undo` are thin
wrappers passing `SV_TOOL` (`events.py`: name `ace3-profile-manager`, prefix `ace`) and, for `editor`, the per-file
compile (`ops.compile_file`) and verify (`verify.verify_edit`, on `core/sv_verify.py`); `report` re-exports the
shared stage titles and result rows.

**Never re-serialize.** Every change is a byte-span splice; every byte outside the edited spans stays identical.
Only `profileKeys` entries, `profiles` entries, `namespaces[*].profiles` entries and the LibDualSpec
`namespaces["LibDualSpec-1.0"].char[*]` spec values may change.

**Parse** (`core/luasv.py`, shared with Saved Variables Browser). A stdlib tokenizer over the file's raw bytes (strings decode as UTF-8 with
`surrogateescape`). `parse(data, descend)` returns a `Chunk` of `Assignment`s; a table field is a `Field` with
`entry_start`/`entry_end` (the entry and its separator), `key_span`, and `remove_span` (what removing the entry
cuts: its whole line, with a trailing line comment such as WoW's `-- [n]`, when nothing else is on that line); a `Table` records its braces. Values whose path `descend`
rejects are skipped by a compiled-regex scanner that only finds their end (`Opaque`), so a 12 MB file parses in
about a second. Numbers WoW writes oddly (`1.#INF`) stay text (`RawNumber`). `splice(data, edits)` applies
non-overlapping `(start, end, bytes)` edits from the end; `encode_string`/`decode_string` round-trip Lua
strings; new text uses the file's own line ending (`newline_of`). A parse error is `LuaParseError(offset)`.

**Model** (`model.py`). `has_profile_keys(data)` pre-filters (no `profileKeys` bytes: never parsed).
`ace_descend` descends only into the database table, `profileKeys`, the keys of `profiles`, each namespace's
`profiles` keys and LibDualSpec's `char` tables. `find_dbs(chunk, data)` keeps a top-level table as an `AceDb` when
`profileKeys` maps `"Name - Realm"` strings to strings and `profiles` (if present) maps strings to tables; any
other look-alike is a note (`ace.lookalike`) and left alone. `AceDb` holds the mapping, `ProfileEntry` per
profile (field, empty, size), `NamespaceProfiles` per module and `LdsChar` per character.

**Scan** (`scanner.py`). Per flavor and account (`account=` narrows it): the account's and each character's
`SavedVariables/*.lua` (`core.svfiles.walk_sv_files` with `is_addon_sv_file`: regular files directly in the folder,
exactly `.lua`, not `Blizzard_*`, no link), skipping a SavedVariables folder under a link (a scan warning). Each file is read once; `SvFile` (`core/svfiles.py`) keeps
path, flavor, account, owner character, size, mtime and SHA-256 (not the bytes). Characters come from the
`<Realm>/<Name>` folders; `AccountScan.is_leftover` compares `"Name - Realm"` ignoring case. Unreadable and
unparsable files become `ScanWarning`s.

**Staging** (`ops.py`). `Staging` holds a `DbState` per database (`DbKey(path, sv_name)`): `keys` (character →
profile, or removed), `profiles` (name → `Original(name)` or `CopyOf(name)`), `module_only` (profiles that exist
only in a namespace: they change only when a delete or rename names them), the LibDualSpec specs and the
leftovers. Operations change only this model and return `OpResult` (`applied` keys, `refused` with a reason per
database, `notes`). A locked (blacklisted, not unlocked) addon is refused; `drop_locked()` resets one that became
locked, and `changed()`/`summary()` never include one. `DbState.changes()` lists deleted, renamed, copied,
reassigned and removed entries; `Summary` counts them for the left pane and the confirm.

**Compile and verify** (`ops.compile_file`, `verify.py`). Per file, the pending states become edits against the
parsed original: a changed `profileKeys` value is a value-span replace, a removed one an entry removal; in
`profiles` and every namespace holding the profile a delete removes the entry, a rename replaces the key span and a
copy inserts `[new] = <source value bytes verbatim>,` before the closing brace; LibDualSpec spec values follow
renames and deletes. `FileEdit` carries the new bytes, human-readable change lines and an `Expected` model per database.
`verify_edit` parses the new bytes again and compares: the mapping, profile names per table, LibDualSpec entries,
each kept or copied profile byte-identical to its source, every other top-level variable and the gaps between
them byte-identical, and the namespaces section with only the profile tables and spec values cut out. Any
mismatch fails the file (`ace.verify_failed`) and stops the run before anything is written.

**Apply** (`editor.apply_flavor`, `multi.apply_flavors`, on `core/sv_apply.py`). `apply_flavors` refuses while WoW runs (`WowRunning`,
skipped for a dry run; the review screen checks only the flavors with pending changes), opens one `ProfileJournal`
for the run, then per flavor: a real run is refused while an earlier run's crash marker is there
(`ace.earlier_unfinished`: it would overwrite, then clear, the only pointer to that run's originals; the review
screen offers that recovery again instead); `SvGuard`; recheck each file's
SHA-256 (a changed file is skipped, "changed since the scan; rescan", `ace.file_changed`); compile and verify. A
dry run stops here (`would_edit` outcomes, nothing written). A real run: journal open, probe leftovers recovered,
lock probe (`probe_lock`; any locked file refuses), whole-WTF snapshot (`core.snapshot`,
`<root>/snapshots/snapshot-<flavor>-<stamp>.zip`), the originals zip `<root>/edited/edited-<flavor>-<acct|all>-<stamp>.zip`
(`core.backup`, verified), the crash marker `<root>/edit-in-progress.json` (`Marker`: flavor, flavor path, zip,
`files` rel → original SHA-256, `after` rel → SHA-256 of what the run writes, started, pid, suite version), then
per file: recheck, `atomic_write_bytes`, read back, journal `edited` entry. Any failure there (Ctrl+C included)
puts back every file this run wrote, newest first, records `rolled_back` in the journal and raises `ApplyError`
(its `result` keeps what was done; a file that could not be put back is `failed`, its detail naming the zip, and
the marker then stays). Then the marker is cleared and snapshots pruned to `keep_snapshots`. Any refusal before the
writes is an `ApplyError` ending "Nothing was changed."; a flavor that stops ends the run (`ace.flavors_stopped`).
`apply_flavors` is serial whatever `[general] parallelism` says: the flavors share the one crash marker (one pointer
for the recovery screen) and the run stops at the first flavor that fails.
Afterwards journals are pruned to `keep_journals` and `prune_edited_zips` deletes only `edited-*.zip` files no kept
journal names (nothing when a journal cannot be read). The review screen checks the backup folder with
`validate_backup_dir` before an Apply, an Undo or a recovery (it may have been edited by hand in the cfg).

**Journal and Undo** (`journal.py`, `undo.py`, on `core/sv_journal.py` and `core/sv_undo.py`). `<WoW>/wow-tools/ace3-profile-manager/journal/journal-<stamp>.jsonl`:

    {"version": 1, "started": iso, "tool": "ace3-profile-manager", "kind": "apply", "flavors": [...], "root": stored, "suite_version": "..."}
    {"action": "edited", "flavor": "_retail_", "path": stored, "rel": "WTF/Account/...", "zip": stored, "sha_before": hex, "sha_after": hex, "size_before": n, "size_after": n, "changes": [...]}
    {"action": "rolled_back", "flavor": "_retail_", "rels": [...]}
    {"finished": iso, "entries": n}
    {"undone": iso, "restored": n, "skipped": n}

`read_profile_journal` drops `edited` entries a `rolled_back` line names. `latest_undoable` is the newest journal of
the whole tool. `undo_run` refuses while WoW of a flavor the journal changed runs and when a file is locked
(`UndoError`), snapshots each of those flavors, up to `parallelism` at once (`core/parallel.py` with
`stop_on_error`: every snapshot is its own zip of its own WTF folder; the first failure, in flavor order, is raised
as "Nothing was changed" once the running ones ended, and a flavor not started by then never starts, so with 1 it
stops where the serial loop did; the snapshots made by then are deleted, `ace.snapshot_discarded`, as they protect
nothing; `on_flavor` / `on_flavor_done` run in the snapshot's thread, the popup's
`start_unit` / `finish_unit`, one row per flavor), prunes them to `keep_snapshots` afterwards, then in the
worker's own thread, newest entry first: a file whose SHA-256 is `sha_after` gets
its original bytes from the zip (checked against `sha_before`, written atomically: "restored"); any other file is
"skipped: changed since"; the journal is marked undone unless nothing was restored and something failed.
`recover(marker)` (the recovery popup's "Put the originals back") is guarded the same way and puts back only files
still at the marker's `after` hash; a file at its original is left alone, any other is skipped. The files now at
their original get a `rolled_back` line in the journal that holds their entries from the marker's zip
(`journal.record_recovered`), so Undo never offers them again; its snapshot is pruned to `keep_snapshots`.

### Ace3 Profile Manager screens

`app.py` holds `AceProfilesFlow` (`FLOW`: `require_install` → `ProfileSettingsScreen` on the tool's first open →
`FlavorScreen(include_all=True, last=last_flavor_choice)` → `AccountScreen` for one flavor with several accounts
(`last_account`) → `ProfileReviewScreen`; `unlocked`, the addons unlocked this session, lives on the flow) and
`ProfileSettingsScreen` (backup folder, a `#blacklist-summary` line and **Edit blacklist…**, which opens the
`BlacklistScreen` and keeps its answer until Save; `validate_backup_dir` errors inline). `s` opens the shared WoW-folder settings, then this tool's (not while a `ProfileSettingsScreen` or a `BlacklistScreen` is on the stack: two Saves would overwrite each other).

- `ProfileReviewScreen` (`review_screen.py`): `TreeFilter` and `ReviewBase`, `two_pane_css`. Left pane `#filters`, one control
  per row: the View pair under a "View" heading (By addon / By character), the Show boxes under a "Show" heading, the
  shared `FilterInput` (id `#search`, `FILTER_SELECTOR`), the `#pending` line (`report.pending_text`, "N pending changes" or `NO_PENDING`) and the
  action row **Apply** (destructive), **Dry run**, **Rescan**, **Undo last change** (revert). Right:
  `ProfileTree` (`#profiles`, a `ReviewTree` whose ↓ on the last line goes on to the action bar), built by `tree_view.TreeBuilder` from the scan, the staging, `Filters` (the
  Show boxes) and the screen's `TextFilter` (matched on the path: flavor with several, account, addon, database,
  profile, character; while it is set every group opens and the user's expansion is not remembered); each
  rebuild keeps expansion and the cursor by `ident`. The builder already narrows the tree, so the keys shown are
  the root's (`filter_keys`), `all_tick_keys` adds every tick, and `tree_narrowed()` is always true: a tick a Show
  box hides counts as hidden too. `a` / `n` act on what is shown; Delete, Assign, Leftovers, Only Default and
  Everyone → Default still take every tick (falling back to the highlighted node only with no tick at all), and
  their popup (a toast for the two that stage at once) says how many ticks are hidden. Labels and tags come from `report.profile_rows` and
  `char_tags`. Ticks are `("p", DbKey, profile)` and `("c", DbKey, char)`; groups tick their descendants; locked
  addons, deleted profiles, removed characters and notes are read-only. `#summary` is `report.selection_text` plus
  the hidden-ticks line.
  The scan, the running-WoW preflight, Apply/dry run, Undo and recovery each run in a worker; the jobs set
  `app.busy` and run inside `activity.running()`.
  The tree sits in `#tree-pane` above the guidance line `#guide` (`report.guidance`: the four `STEPS` on the root,
  a flavor or an account or with nothing highlighted, else `report.node_hint` for the highlighted node; with
  pending changes the pending count and the w/y/⌫ keys come first, and the node hint follows within
  `GUIDE_MAX_ROWS` (2) rows: a name too long for the hint's row at 120x30 is shortened with "…", and the hint is
  left out only if even that does not fit; on a locked addon the hint names it and the `u` unlock) and the action
  bar `#tree-actions`, a
  `ActionBar` (a `WrapButtonRow`; ↑ goes back to the tree, and ↓ on the tree's last line comes to it) of
  `TREE_ACTIONS`, staged changes first (amber; Copy green, it only adds a profile), then staged deletes (red), then the rest (Assign, Rename, Copy,
  Everyone → Default (E), Delete, Only Default (D), Leftovers, Blacklist…, More…, Discard: three rows at 120x30, two at 160x45), each button doing what
  its key does. The focused button's `ActionTip` (`action_tip()`: what it would do with the ticks or the
  highlighted node now) sits on its own `action-tip` layer just above the guidance line over the bar, and
  `_place_overlays()` keeps Textual's toast rack above the tip (or the guidance line). With nothing ticked, Delete and Assign act on the
  highlighted node, but never on the root, a flavor or an account (`GROUP_KINDS`). The guide follows the cursor, the ticks and the pending
  changes. Discard is Backspace (`x`/`c` are expand and collapse all); `b` toggles the highlighted addon's
  (flavor, addon) pair (`settings.toggle_pair`) and saves at once; **Blacklist…** (`action_edit_blacklist`) opens
  the `BlacklistScreen` for the review's flavors and saves its answer at once.
- `BlacklistScreen(cfg, flavors, pairs)` (`blacklist_screen.py`): `TreeFilter` and `ReviewBase`, `two_pane_css`. Left
  pane: an explanation, the `FilterInput` and **Save** / **Select none** / **Cancel** (keys `n` and Esc on the buttons); right: a flavor → addon tree, from its own
  scan worker (`scan_flavors`), of every addon with Ace3 data plus each blacklisted pair no longer found
  ("(not found)"; a legacy `"*"` pair is listed under every shown flavor, so a Save, or a failed scan, never drops
  it). A ticked pair is blacklisted; nothing else is ticked. `a`/`n`/`/`/`x`/`c` as on every tree (the filter
  matches flavor and addon names; a mark counts the keys shown). With ticks the filter hides, Save asks first
  (`ConfirmScreen`, kind `confirm`, saying how many). It
  dismisses with the new pair list (or `None`); pairs of flavors it does not show are kept, and a legacy `"*"`
  pair is saved as explicit pairs (for the hidden flavors too).
- `popups.py`: `TargetScreen` (delete and assign: a target `Select` plus a new-name `Input`), `NameScreen` (rename
  and copy, with live validation) and `ActionsScreen` (the `m` menu: every key the footer
  and the action bar hide, under the `ACTION_GROUPS` headings Selection and Modification), sharing `popup_css`. Apply and Undo use `ConfirmScreen` (`report.apply_confirm`/`undo_confirm`; alerts
  in red; Yes red for Apply and Undo, cyan for a dry run).
- `ProfileProgressScreen(title, dry_run=, first_stage=, flavors=)` (ids `ace-*`, `report.STAGE_TITLES`; Apply feeds `report_unit`, a row per flavor in turn) and `ProfileRecoveryScreen` (a `ChoiceScreen`: Put the originals
  back / Leave as is; Esc leaves the marker for the next scan).
- `ProfileResultScreen` (`result_screen.py`): the shared `ResultScreen` built from rows; `#result-summary` (`apply_summary_rows` or
  `undo_summary_rows`: zips and the journal are named inside the backup folder, `report.in_backup_folder`, which
  has a "Backup folder" row of its own) above `#result-detail` (`DETAIL_COLUMNS` or `UNDO_COLUMNS`); Rescan, Other flavor,
  Tools, Quit (keys `r` `f` `t` `q` on the buttons), plus a focused **Back to review** (Esc) after a dry run. After a real Apply or Undo the
  staging is dropped and the review rescans when shown again.

## UI

`Ka0sApp` registers the `ka0s` theme, starts the background update check, handles `u` (a forced check in a worker
first: the notice may come from the cache; if the release is gone it says "No update available" and clears
`app.release`, which drops the notice, and never installs; otherwise it offers what the fresh check found), and exposes
the `after_mount()` hook. Every screen shows a `Header` and ends with a `BottomBar`: one docked row holding a compact `KeyFooter` (its keys
from the left, less every key a shown button carries: spec D17) and the `BrandBar` (the version and the update notice, right-aligned, in the longest wording that
fits what the keys leave; docked on their own the two overlapped and the brand bar was never seen). Where a screen
binds `u` itself (the Ace3 review's Unlock) or a text box has focus, the notice and the toast say to press `u` on
the tool menu (`update_key_free`; the bar follows focus changes, and a popup is judged by the screen under it).
The tool menu (`ToolMenuScreen`) puts a `VersionLine` right under the `Banner`'s name line (`v<version>`, plus
"· vX.Y.Z available, press u to update" once the check finds one; `version_text`) and a `TermsText` (spec D6,
`branding.TERMS`, pinned word for word in the README by `tests/test_docs.py`) right above the `BottomBar`. Its
`ToolArea` (the list and the hint, `height: 1fr`) caps the list's height so the hint stays under it and the list
scrolls in a short window; under 30 rows, or when the art would make the list scroll (a narrow window wraps each
description onto two rows; `ToolMenuScreen.fit_art`), the banner shows only its name line (`Banner.show_art`). At
120x30 everything shows without scrolling, and at 80x24 the terms, the footer and every tool stay reachable
(`tests/test_look_and_feel.py`). The terms take two rows at 120 columns and three below about 115. TINY is the floor:
below it the list keeps one tool row and the hint is hidden rather than overlap the terms. Long-running or blocking work
runs in thread workers and reports back with `call_from_thread` (a run's progress instead lands on its `ProgressScreen`'s board, which the UI thread draws on a timer): scan, clean, organize, backup, restore, profile apply, undo, and also the
running-programs check before a clean, backup, restore or undo confirm (PowerShell/`tasklist`; the
review screen shows "Checking for running programs…" and ignores its action keys meanwhile), install detection on the setup screen, the organizer's
per-flavor waiting counts (`FlavorScreen.set_notes()`), and an accepted in-app update (`UpdateProgressScreen`,
with `app.busy` set). While a clean, organize, backup, restore, profile apply, recovery or undo runs, `app.busy` is set: every key that would leave the screen is refused, and so is Ctrl+Q
(`Ka0sApp.action_quit`, logged as `ui.quit_refused`).
An unhandled exception in a handler or worker is logged as `error` with `where=ui` by `Ka0sApp._handle_exception`
(a private Textual hook, pinned by a test) before Textual exits; `suite.run()` returns the app's `return_code`, so
`session.end` and the process exit status show the crash.

Shared screens and widgets in `wowtools/ui/` (the Textual half of the shared library):

| Module | Job |
|---|---|
| `base` | `Ka0sApp`: registers the theme, the background update check, `u` (`UpdateScreen`, focused on "Update now" behind the dialogs `EnterGuard`; `UpdateProgressScreen`), `after_mount()` |
| `theme` | `KA0S_THEME`, the Ka0s colours; `ACTION_COLOURS` (one button colour per action kind) and `action_variables()`, the `$act-<kind>` theme variables (`-lighten`, `-darken`, `-text`: whichever of the theme's foreground and background contrasts more, `contrast()`) |
| `branding` | `Banner` (the shield art on the tool menu and the flavor and account pickers), `VersionLine` and `TermsText` (`TERMS`) on the tool menu, `BrandBar` and `BottomBar` (the footer and the brand bar in one row, on every screen; two rows when the keys and the shortest version text don't fit one, as on a review at 80 columns: `KeyFooter.wanted_rows`, re-checked on resize), `KeyFooter` / `footer_bindings(screen)` (the footer lists a screen's shown bindings less every action whose key a shown button carries, any of its keys: `n,escape` goes with a `(n)` button; nothing while `under_popup(screen)`), `update_key_free` / `update_notice` / `brand_texts` |
| `suite_app` | `WowToolsApp`, `ToolMenuScreen` (the first screen; `ToolArea` holds its list and hint; `c` opens the changelog; with no tool open, `s` works on the menu only: `settings_allowed`, also hidden from the footer elsewhere through `check_action`; `h` (`action_help`, spec D18) opens a `HelpScreen`: the open tool's (`flow_name`, `Tool.help()`) or, with none open, `suite_help()`; `help_allowed` refuses it over a popup (any `ModalScreen`) and over the help itself, and hides it from the footer there; not a priority binding, so a focused text box types the letter), `LockScreen` (a `ChoiceScreen`: another copy may be running: Quit, or Override and continue) |
| `changelog_screen` | `ChangelogScreen` (spec D3; `c` on the tool menu): the two-pane look (`two_pane_css`, `TwoPaneFocus`) with an `OptionList` of versions on the left (`VERSIONS_WIDTH` 36; newest first, one row each with its date, the running version marked "current" and highlighted first) and the highlighted version's notes as `Markdown` in a `NotesScroll` on the right (→/Tab/Enter go there, ↑/↓/PgUp/PgDn scroll it, ← back); Esc/q back to the menu. No changelog: the right pane says why |
| `help_screen` | `HelpScreen(title, text)` (spec D18): the title over one scrollable `Markdown` pane (`#help-body`, focused, so ↑/↓/PgUp/PgDn scroll it), `HELP_HINT`, `BottomBar`; Esc, q or h dismisses it, back to the screen it covered as it was. `suite_help()` is the tool menu's text: every tool in `TOOLS` (title and description), the common flow, the keys, settings and parallelism, the button colours, the words and the terms, and `README_URL`. A tool's text is `HELP` in its own `help.py` (with `GUIDE_URL`, its guide on GitHub), read by `Tool.help()`; `tests/test_help.py` checks that each names every button of its screens and that every link points at a file in the repo |
| `tool_flow` | `ToolFlow` base (spec D9): `start()` (`require_install()`, the shared WoW-folder setup, then `SETTINGS_SCREEN` with source `wizard` the first time the tool opens, then the tool's `_pick_flavor()`), `open_settings()` (`s`: the WoW-folder settings, then `SETTINGS_SCREEN`; never while it or a `SETTINGS_BLOCKERS` screen is on the stack), `_settings_done()` ("Settings saved…"), `_after_review(choice)` (`flavors` / `tools` / quit), `remember_flavor(choice)` and `pick_account(flavor, then)` (the last choices in `[SECTION]` `last_flavor_choice` / `last_account`, logged with source `picker`; the account picker only for several accounts, Esc back to the flavor picker), `fill_notes(picker, work, ready)` (a flavor picker's notes worked out in a thread, set only while that picker is still on the stack), `close()` |
| `settings_form` | `ToolSettingsScreen(tool_cfg, wow_path, *, source)`: every tool's settings form (title `FORM_TITLE`, the tool's `fields()`, `#settings-error`, Save and Cancel, the hint from `settings_hint(TICKS)`, focus on `FIRST_FIELD`, Esc cancels). A tool supplies `load()`, `fields()` and `save()` (False after `_error(text)` keeps the form open); `folder_input()` / `folder_value()` handle a folder field (empty = the default, whose stored form `folder_hint(path)` shows), `wow_install` is the WoW folder when valid. Dismisses with True once saved |
| `result_screen` | `ResultBase`: every result screen's layout (`#result-summary` Item/Value above the detail table `DETAIL_ID`, the buttons: `lead_buttons()`, Rescan (`RESCAN`, the dismiss value), `extra_buttons()`, Other flavor, Tools, Quit, each `(label, kind, id, key)` with its key on the button; the hint is `RESULT_HINT`), keys (`result_bindings(rescan, before=, after=)`) and `ui.selection` logging (`LOG_SCREEN`); a tool screen fills `summary_rows()` / `fill_summary()` and `fill_detail()`. `ResultScreen(sub_title, summary_rows, columns, detail_rows, *, back=False)`: the generic one built from rows, its last cell a status coloured by `STATUS_COLOURS` (first words); `back` adds "Back to review" (`Esc` on the button). `status_colour(status, colours, prefix=)` / `status_style(app, colour)` colour a status cell on every result screen |
| `setup_screen` | General setup (a `FormScroll`, so ↑/↓ move between fields at any size): the WoW folder, and the retention every tool shares (`#keep-backups`, `#keep-journals`: `[general] keep_backups` / `keep_journals`) and `#parallelism` (`[general] parallelism`, 1-8) |
| `flavor_screen` | `FlavorScreen(cfg, install, *, include_all=False, last=None, flavors=None)`: the flavor picker. `include_all` adds "All flavors" first (dismisses with `ALL_FLAVORS`); `last` is the folder to pre-select (`""` = All flavors, `None` = `[general] last_flavor`); `flavors` replaces `install.flavors()`; `note`/`all_note` fill the remarks column and `set_notes()` replaces them later. Picking one flavor saves `[general] last_flavor`. |
| `account_screen` | `AccountScreen(cfg, flavor, last)`: "All accounts" plus each account. Dismisses with the name, `""` for all, or `None` for back. The WTF Cleaner and the Ace3 Profile Manager show it only when a flavor has more than one account and save the choice as their own `last_account`. |
| `dialogs` | What every tool's screens share, so no tool imports another tool's screens: `ConfirmScreen(title, body, alerts=(), *, kind="confirm", groups=None)` (yes/no, spec D13: Yes, No in that order, Yes focused at the start and built with action kind `kind`, which every caller names: `destructive` for a delete, overwrite, undo or discard, `simulate` for a dry run, `create` for a backup; Enter/Space on a button do nothing for `CONFIRM_GUARD` = 0.25 s after it opens, and each one ignored restarts that wait so a held key's auto-repeat never answers (the `EnterGuard` mixin, a priority `GUARD_BINDING` that lets the key through once the time is up; `UpdateScreen` uses it too), `y`/`n`/Esc are never delayed; `alerts` in red; `groups` ({label: items}) listed in a `detail_tree`), `InfoScreen(title, groups, body="")` (something to read and acknowledge with OK, its details in a `detail_tree`), `ChoiceScreen(title, message, choices, *, default, escape=False, hint="")` (a warning with one button per `(id, label, kind)`; `default` is focused at the start, the safe choice the user most likely wants: Remind me next time, Put the originals back, the lock's Quit unless the lock is stale; Enter/Space wait `CONFIRM_GUARD` like ConfirmScreen; dismisses with the id, through `choose(id)`, which a subclass may extend; Esc closes with None only with `escape`: the WTF Cleaner's `RecoveryScreen` and the Ace3 `ProfileRecoveryScreen`), `detail_tree(groups)` / `detail_hint(groups)` (a popup's read-only tree, every branch open when it all fits in `DETAIL_ROWS` = 12 lines; `POPUP_TREE_CSS`), `ProgressScreen(title, *, dry_run, first_stage, stage_titles, units, parallelism, what, label)` (spec D11: one box whose size never changes during a run: the title, an overall bar "n of m game versions" (only when opened with more than one unit; the box is 2 lines shorter without it), `min(parallelism, units)` unit rows chosen at open (label, stage, bar; a finished unit's row goes to the next one) and the newest detail, every line one line high and ellipsised, bars filling their column (`PROGRESS_BAR_WIDTH`, Textual's `Bar` widened from 32); fits 80x24 with 8 rows. Workers call `report(stage, current, total, detail)`, `report_unit(unit, ...)` (`run_units`' tagged progress), `start_unit(unit, index, total)` and `finish_unit(unit)` from any thread, and `finish_all()` once the job returned: they write a `core.progress.ProgressBoard` under its lock, and the screen draws it every `PROGRESS_INTERVAL`, so no worker waits for the UI loop. A tool subclasses it with `ID_PREFIX`, `STAGE_TITLES` and `SIMULATED_STAGE`), `tick_mark(items, unchecked, key, success=)` (✔ / ◩ / ✘ for a review-tree line), `relabel_branch(tree, node, label, skip=)` (after a tick), the `TwoPaneFocus` mixin (←/→ between the left `#filters` panel and the tree; it is a `TreeKeys`, whose `x`/`c` expand and collapse every node below the root, bound with `TREE_BINDINGS` and named in the hint by `TREE_HINT`), `theme_colour(app, name)` (the theme's colour, or the Ka0s one before a theme is set), and the one look every tool's screens are built from: `two_pane_css(screen, tree, width=FILTERS_WIDTH)` (review: left pane `#filters`, `FILTERS_WIDTH` = 50, the tree filter box a row apart, one-row actions, scan box, summary), `ACCENT` (names in a tree) and `BUSY_STYLE` (a summary line while work runs), `result_css(screen)` (the summary takes at most 60% of the height), `settings_css(screen)` (the form at `FORM_WIDTH`: up to 100 columns, centred; compact checkboxes), and the hint starts `REVIEW_HINT` / `review_hint(space)` and `RESULT_HINT` |
| `review` | The review screens' shared machinery (spec D9), so no tool copies it: `ReviewTree` (← to the left pane; the Ace3 `ProfileTree` adds ↓ to its action bar), `TickModel` (ticks kept as the ticked keys or as the unticked ones, changed in place; `unticked` feeds `tick_mark`) and `NotTicked`, and the mixins `ReviewBase` puts together over `TwoPaneFocus`: `TickActions` (Space ticks the highlighted node, presses a button, toggles a checkbox or types into an input; `a` / `n` act on `shown_tick_keys()` only: the screen's `all_tick_keys()` narrowed by `filter_keys()`, the one hook a filter takes, which Space applies to a node's keys too, so hidden ticks stay; a screen supplies `tick_model()`, `node_tick_keys(node)`, `tick_log_key()`, `LOG_SCREEN` and, if it needs them, `all_tick_keys()`, `select_all_keys()`, `select_none_keys()` and `ticks_frozen()`, which `ReviewBase` sets while the running-programs check runs), `Preflight` (`run_preflight(check, then, extra)`: the running-programs check and `extra()` in a worker, `then(running, extra_result)` on the UI thread while the screen is shown; `_checking` and `_checking_changed()`, `PREFLIGHT_TEXT` on the summary), `ScheduledRebuild` (`_schedule_rebuild()`: the tree's loading indicator and "Updating the list…", then one `_rebuild()`), `ButtonActions` (`BUTTON_ACTIONS`: button id → action name), plus `action_leave(choice)` (never while `app.busy`), `show_scan_box(scanning, label)`, `_scan_progress(current, total, label)` and `_close_progress()` (pops the run's `_progress_screen` if it is still shown) |
| `tree_filter` | The tree filter every tree screen shares (spec D7, D8): `FilterInput` (a compact one-row "Filter (/)" box, id `tree-filter`, in the left pane: Esc clears it and goes back to the tree, → at the end of the text goes to the tree), `FilterBox` (the box alone, for a read-only tree such as IB's Restore: the screen supplies `LOG_SCREEN`, `action_focus_tree()` and `filter_changed()`; `/` (a priority binding in `FILTER_BINDINGS`, named by `FILTER_HINT` before `TREE_HINT`) focuses the box from anywhere but a text box, where it is typed (an integer box gives it up); the box is found by `FILTER_SELECTOR`, so another id works; Enter keeps the filter and goes to the tree; Enter and the Esc that clears it log `ui.selection` with `control=filter`), `TreeFilter` (`FilterBox` for a tick screen, placed before `ReviewBase`: typing reschedules the debounced rebuild; its `filter_keys()` is `TickActions`' hook, so `a` / `n` and Space on a group or the root act on the keys it shows, from the screen's `filter_texts(key)` (the item's groups' labels and its own); the screen must supply `all_tick_keys()` with every key of its model, never the filtered tree's (abstract here; `tests/test_structure.py` checks it); `shown_tick_mark(items, key)` is the mark of a group or the root in every tool: over the items the filter shows only (what Space on it would tick or untick; no mark when it shows none); `hidden_ticked_keys()` / `hidden_ticked_note()` give "N selected items are hidden by the filter" (`hidden_by_filter(n, noun, by)`, the noun a screen's `HIDDEN_NOUN`: file, shot, flavor, addon, item) for the summary and confirms: hidden ticks stay and the run takes them; `tree_narrowed()` says when to count them (while the filter is set; Ace3 always, its Show boxes and view narrow too) and `hidden_cause(keys)` what hides them (the filter; Ace3 names the Show boxes and the By character view too)), `TextFilter` (case-insensitive substring, blanks ignored, empty matches all), `ModelNode` (data and children: a tree before it is built, for a screen whose model is not one) and `ModelFilter` (`model_filter(roots, children, texts, key=)`: what a filter keeps and opens of the screen's model, children that load on expand included; a match keeps its groups and opens them, a matched group keeps everything in it) |
| `widgets` | `action_button(label, kind, key=None)` (the only place a `Button` is built, an `ActionButton`: the kind's nearest Textual variant plus a `-act-<kind>` class; `key` is the binding key of what it does, shown centred on a second line, or after the label on a compact one, and kept as `shortcut`; spec D17), `key_text(key)` (a key as a button writes it: `Esc`, `Space`, `⌫`, `D`), `button_keys(screen)` (the keys its shown buttons carry), `ACTION_VARIANTS` (the eight kinds), `action_kind(button)` and `ACTION_CSS` (the kind colours, in `Ka0sApp.CSS`; see [Look and feel](#look-and-feel-and-terminal-size)), `LIST_NAME_STYLE` / `LIST_CURSOR_BACKGROUND` (pick lists), `Ka0sCheckbox` (✔/✘ marks), `ButtonRow` (←/→ move focus between its buttons, Space presses the focused one), `WrapButtonRow` (a `ButtonRow` of compact one-row buttons in a grid whose column count follows its width; the Ace3 review's action bar), `NAV_BINDINGS` (↑/↓ move focus; not priority bindings, so a focused tree, list, table or input keeps its arrow keys), `NavSelect` (a `Select` that leaves ↑/↓ to `NAV_BINDINGS`; Enter or Space opens its list), and `NavHint` (the key hint every screen shows; when it takes more than one row it breaks only between its
" · " items, `wrap_items`, so a key stays with its action), `FormScroll` (a scrolling form where ↑/↓ still move focus; `open_at_top()` after the first focus) |

### Look and feel and terminal size

Every screen is designed for **120x30**, the window Windows Terminal (Windows 11's default terminal) opens, and
grows when the window is larger; 80x24 only has to keep working (Addendum B of
`docs/superpowers/specs/2026-10-04-ace-profiles-design.md`). The sizes live in `wowtools/ui/dialogs.py`:

- the review's left pane is `FILTERS_WIDTH` (50) columns at every size (its four action buttons need 45); the tree
  takes the rest (`1fr`, 70 columns at 120x30) and all the height;
- popups (`ConfirmScreen`, `ProgressScreen`, the Ace3 popups, the recovery and lock screens) are `POPUP_WIDTH`
  (`width: 90; max-width: 90%`), centred; `UpdateScreen` (76) and `UpdateProgressScreen` (64) stay narrower;
- settings forms are `FORM_WIDTH` (`width: 100%; max-width: 100`), centred, with compact checkboxes, so the whole
  form and its Save button show at 120x30;
- a result screen's summary takes at most 60% of the height (`result_css`); the table below takes the rest;
- footers show every key whole at 120 columns: the footer is compact (one space between keys), the command
  palette's key is hidden suite-wide (Ctrl+P still opens it), and a key a shown button carries is on that button,
  not in the footer (spec D17, below); the brand bar takes what is left of the row (the whole name on a review);
- paths on result screens are named inside a "Backup folder" row (`cleaned/<name>`, `snapshots/<name>`, …) rather
  than whole, so they fit (a file outside that folder keeps its whole path); the Screenshot Organizer names its
  targets inside a "Target folder" row (`report.target_folder`), each keeping its YYYY/MM/DD; a tree line longer
  than its pane scrolls sideways.

**Keys on buttons** (spec D17). A button that does what a key does shows that key: `action_button(label, kind, key)`
puts it centred on a second line under the label (`Clean` over `(w)`; a full-size button is then four rows high,
and so is every button of a `ButtonRow` holding one, so a row lines up), or after the label on a compact one-row
button (the Ace3 action bar keeps `Delete (d)` on one row: two rows a button would take the tree two or three rows
at 120x30). A label never spells its key itself (`tests/test_structure.py`). The footer (`KeyFooter`) then leaves
out every key a shown button carries, and the other keys of the same action (`Esc` for No), so it lists only the
keys no button has: on a review `Space`, `a`, `n`, `/`, `x`, `c`, `f`, `t`, `q`, `s` and `h`; on a result screen
`s` and `h`. Under a popup (any `ModalScreen`) the footer of the screen beneath lists nothing, since none of its
keys work until the popup closes, and keeps its height so that screen does not move (`under_popup`). The hints
name navigation and the keys with no button, never a button's key; neither do the guide and status lines (the
Ace3 pending line says "Apply, Dry run or Discard them", the Interface Backup one "then Restore"), and a result
screen whose "Back to review" button carries `Esc` drops "Esc back" from `RESULT_HINT`.
`tests/test_look_and_feel.py` (`assert_keys_on_buttons` in `tests/fixtures.py`) checks every review, confirm,
result, blacklist, restore and settings screen: each button whose action has a key shows it, no footer lists
a key a shown button carries, and no hint names one.

**Button colours** (spec D12). Every button is built by `action_button(label, kind, key)` (`key` left out for a
button with no binding, such as Save) and coloured by what it does, the same in every tool. The colours are theme variables (`ACTION_COLOURS` in `ui/theme.py` becomes
`$act-<kind>`, `-lighten`, `-darken` and `-text` in `KA0S_THEME.variables`, and `Ka0sApp.get_theme_variable_defaults`
supplies them under any theme); `ACTION_CSS` in `ui/widgets.py` paints a `Button.-act-<kind>` with them, its hover
and its pressed state, and leaves Textual's dimmed disabled buttons, bold-reverse focused label and edge-less compact
buttons alone. Each kind also keeps its nearest Textual variant, which is what a plain `App` shows.

| Kind | Colour | Variant | Buttons |
|---|---|---|---|
| `destructive` | red | error | Clean, Ace3 Apply, Delete, Only Default, Leftovers |
| `overwrite` | amber | warning | Organize, Restore (restore screen), Update now, Override and continue, Assign, Rename, Everyone → Default |
| `create` | green | success | Back up, Copy (stages a new profile) |
| `revert` | violet | warning | Undo last clean / run / restore / change, Undo, Put the originals back |
| `simulate` | cyan | primary | Dry run |
| `confirm` | blue | primary | Save (every form and the blacklist), OK, Remind me next time, a ConfirmScreen Yes that names no other kind (each Yes takes its caller's `kind`: red, cyan or green) |
| `navigate` | grey | default | Rescan, Other flavor, Tools, Restore (open the restore screen), Edit blacklist…, Blacklist…, More…, Select none |
| `cancel` | dim grey | default | Cancel, No, Later, Quit, Back, Back to review, Dismiss, Leave as is, Discard |

Staging buttons (the Ace3 action bar) take the colour of the action they stage. Text on a coloured button is the
theme's foreground or background, whichever has the higher contrast (at least 4.5:1, pinned). The WTF review shows
its criteria in colour next to its buttons: only red is shared there (Not installed, the files Clean deletes); the
violet leans to red and the cyan to green, a clear hue away from the criterion purple and the confirm blue. Interface
Backup's review **Restore** opens the restore screen, so it is grey there and amber on the restore screen: the one
label with two kinds. `tests/test_structure.py` pins that only `action_button` builds a `Button` and the key
mappings; the look-and-feel screens check every button shows its kind's colour.

`tests/fixtures.py` names the sizes: `BASE = (120, 30)`, `LARGE = (160, 45)`, `TINY = (80, 24)`.
`tests/test_look_and_feel.py` runs each check for every tool: at BASE the left pane, its one-row buttons, the hint
shape, the result layout, the settings forms (whole, Save included), the footer keys and the popups (fit with room
around them; the Ace3 quick actions list every action without scrolling); the Ace3 tree pane keeps the plan's
Review Focus 5 (action bar at most 3 rows, guide at most `GUIDE_MAX_ROWS` = 2, tree at least 12 rows). At LARGE the
tree grows while the left pane keeps its width, the Ace3 action bar takes at most two rows, and popups and forms stay at a
readable width (at most 100 columns), centred. One TINY smoke test opens every tool's review, settings and result
screens at 80x24 and focuses every focusable control; nothing there is hidden or shortened for that size. Tool tests
that check a layout run at BASE (`…_at_base`).

The WTF Cleaner's own screens live in `tools/wtf_cleaner/`. `app.py` holds `WtfCleanerFlow` (`FLOW`) and
`CleanerSettingsScreen` (criteria, max age, backup on/off, cleaned-files zips to keep, backup folder). The flow shows `FlavorScreen` with
`include_all=True` and `last=last_flavor_choice`; All flavors skips the account screen. `review_screen.py` holds:

- `ReviewScreen(cfg, tool_cfg, flavors, *, account, wow_check, locker_check)`: a `TreeFilter` and `ReviewBase`; tree,
  criteria, the `FilterInput` under the max age (it narrows the proposal on top of the criteria: the tree is built
  from `ModelNode`s matched on flavor, account, owner, addon and file names; an addon opens when a file in it
  matches; the summary and the confirm's alerts say how many ticked files it hides), the Clean /
  Dry run / Rescan buttons and **Undo last clean** (violet, key `z`, last in the same row; disabled when nothing is
  undoable, while scanning and while busy; its confirm (Yes red) names the clean's time, flavors and file
  count). `flavors` is one `Flavor` (root = the flavor, accounts below) or a list (root = All
  flavors, a node per flavor, a "not scanned" leaf for a flavor whose scan failed). `wow_check` covers every
  flavor (`core.process.wow_check_for(list)` lists the processes once);
- the shared `ConfirmScreen` (`wowtools.ui.dialogs`): Yes red for a real clean and cyan for a dry run; lists each flavor's counts;
- `CleanProgressScreen`, a `ProgressScreen` (ids `clean-*`): one row, taken by each flavor in turn (its label
  names the flavor; `execute_flavors`' `on_flavor` is `start_unit`); also shown for an undo;
- `RecoveryScreen` (a `ChoiceScreen`): Dismiss or Remind me next time.

`result_screen.py` holds `ResultScreen(result, flavor=None)`, a `ResultBase`: a summary table plus a per-file `DataTable`. With a
`MultiCleanResult` it shows Done / Stopped / Not started rows after a stop, one block of summary rows per finished
flavor, and a Flavor column (`report.MULTI_RESULT_COLUMNS`). Zips are named inside the backup folder (`cleaned/<name>`, `backup/<name>`), which has a "Backup folder" row of its own. A real clean adds a "Run journal" row: inside the backup folder when it is there (the default one holds
`journal/`), else its name after a "Journal folder" row, so both fit at 120x30 for the default install path. The per-file table puts Reasons before
Size and File, so why each file goes shows at 120x30. With an
`UndoResult` it is titled "undo result" and shows `report.undo_summary_rows` and `report.UNDO_COLUMNS`.

The Screenshot Organizer's screens live in `tools/screenshot_organizer/`. `app.py` holds `ScreenshotsFlow` (`FLOW`:
`require_install` → `ScreenshotSettingsScreen` on the tool's first open → `FlavorScreen(include_all=True,
note=<"no Screenshots folder" where missing>)` → review; every flavor is listed) and `ScreenshotSettingsScreen` (destination,
copy mode; `validate_dest` errors show inline). `review_screen.py` holds:

- `ShotReviewScreen`: a `TreeFilter` and `ReviewBase`; the `FilterInput` (`/`, the left pane's first control: it
  matches flavor, year, month, day (`2024-01-02`) and file names on the plan, day and Already filed files included,
  and opens a day whose files match) and the flavor → year → month → day → file tree (day files load on expand; read-only
  Conflicts and Skipped nodes; in copy mode an Already filed node, unticked, that `a` leaves alone) and the Organize / Dry run / Rescan / Undo last run buttons. It uses the
  shared `ConfirmScreen`;
- `ShotProgressScreen`, a `ProgressScreen` (ids `shots-*`): one unnamed row (stage and bar) and the current file for a run, dry run or undo;
- `ShotResultScreen`, a `ResultBase`: a summary table (with a "Target folder" row) plus a per-file `DataTable` whose Target column
  names each folder inside it.

## Testing

`python3 scripts/run_tests.py` deals the tests round-robin into one process per CPU (at most 16); `python3 -m
unittest discover -s tests -t .` runs them in one process. Textual tests subclass `tests.fixtures.TuiTestCase`,
which turns off asyncio debug mode. `tests/fixtures.py` builds a synthetic install in a temp
folder, and TUI tests use Textual's `App.run_test()` pilot, at `BASE` (120x30) for anything about layout (see
[Look and feel and terminal size](#look-and-feel-and-terminal-size)). No test touches a real WoW folder or the network.

CI (`.github/workflows/tests.yml`) runs on every push and pull request: Ubuntu and Windows, Python 3.10 (the floor)
and 3.13. Each job byte-compiles `wowtools`, `scripts` and `tests`, runs `gen_event_docs.py --check`, then
`run_tests.py`.
