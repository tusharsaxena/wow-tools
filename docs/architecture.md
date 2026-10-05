# Architecture

## Layers

    wow-tools.sh / .cmd    the only entry point (runs python -m wowtools). The .cmd starts Python and exits on its
                           last line, so a zip update can replace it while it runs (tests/test_launcher.py)
    wowtools/__main__.py   Python check + vendor/ on sys.path, then suite.run()
    wowtools/suite.py      no args: config migration, instance lock, the suite app; or `update`, `--version`, `--help`
    wowtools/core/         UI-free framework shared by every tool (never imports textual)
    wowtools/ui/           shared Textual pieces: theme, branding, Ka0sApp, WowToolsApp, ToolFlow, shared screens
    wowtools/tools/<tool>/ one package per tool: logic modules (UI-free) + a ToolFlow (FLOW) and its screens

There is one Textual app, `WowToolsApp` (`ui/suite_app.py`). Its first screen is the tool menu
(`ToolMenuScreen`), which stays at the bottom of the screen stack. Picking a tool builds that tool's `ToolFlow`
(`TOOLS[name].flow()`), which pushes the tool's own screens; `flow.close()` (`app.close_tool()`) pops back to the
menu. So the tools look like one connected app, while each keeps its own workflow and its own config file
(`config/<tool>.cfg`). The event log's `tool` field (and so its log folder) follows the open tool. Tools can't be
started on their own; there is no command-line mode.

Tool logic is pure Python over plain dataclasses, so the TUI and the tests drive the same functions. Front ends
stay thin.

## Core modules

| Module | Job |
|---|---|
| `bootstrap` | `REPO_ROOT`, `VENDOR_DIR`, Python ≥ 3.10 check, `add_vendor_path()` |
| `paths` | WSL detection; `to_native()` / `to_stored()` translate `G:\X` ⇄ `/mnt/g/X` |
| `config` | `config/wow-tools.cfg` (`[general]`) plus `config/<tool>.cfg` per tool (`tool_config_path()`); typed accessors; `config.changed` events; `migrate_legacy_config()` splits the old root `wow-tools.cfg`. `save()` is atomic and runs on the UI thread only (the background update check hands its values back through `check_for_update(persist=...)`) |
| `migrate` | Start-up moves for renamed tools (`wowtools.tools.RENAMED_TOOLS`, one `ToolRename` line each): `migrate_tool_config()` turns `config/<old>.cfg` into `config/<new>.cfg` with the section renamed; `merge_folder()` (or `merge_folder_logged()`, which logs `folder.renamed` and never raises) moves `logs/<old>/` and `<WoW>/wow-tools/<old>/` to the new name. Never overwrites (details below) |
| `lock` | `InstanceLock` on `wow-tools.lock` (O_EXCL create; holder pid, host, start time, platform (WSL via `paths.is_wsl`, the suite's one check), token). `acquire()` returns the holder on conflict; `take_over()`; `release()` removes the file only if it is still ours. `LockInfo.stale` is known only on POSIX for a lock from this host |
| `fsutil` | `atomic_write_bytes()` (remove whatever sits at `<name>.partial` without following it, create it with `O_CREAT\|O_EXCL` (+`O_NOFOLLOW`), write, then `os.replace`; the Ace3 Profile Manager's SavedVariables writes) and its wrapper `atomic_write_text()` (`\n` written as `os.linesep`), used for every config write; `rename_no_replace()` (refuses an existing target with no check-then-act window: a hard link then unlink on POSIX, `os.rename` on Windows; falls back to check + rename where hard links are unsupported); `free_name(folder, stem, suffix)` (`-2`, `-3`, ... for same-second names: journals, WTF backups, cleaned zips, Interface Backup zips); `remove_quietly()` (delete one of our own temporary or partial files, ignoring errors); `safe_progress(cb)` (wraps a run's progress callback so an error in it never disturbs the run; every clean, organize, backup, restore and undo uses it); `is_link(entry_or_path)` (a symlink, or on Windows a junction or directory symlink by its reparse tag; never raises); `is_real_dir(path)` (a folder that is not itself a link, from one lstat); `read_link(path)` → `(target, junction)` or None, and `make_link(target, path, junction=)` (a junction on Windows when it was one, else a symlink), which Interface Backup's Undo uses to make again a link a restore removed; `remove_tree_no_follow(path)` (delete a folder tree, removing links inside it as links and never descending into them; a link given as `path` is just unlinked) |
| `activity` | `running()` context manager that file-changing workers (clean, organize, backup, restore, undo) enter; `wait_idle(timeout)`. `suite.run()` waits on it before releasing the lock, so a worker still writing never shares its folders with a second copy |
| `events` | Registry of event names with fixed levels; JSONL + text sinks (files kept open, flushed per line, closed on a new day and at exit); `log_event()`; `capture_events()` for tests |
| `install` | `WowInstall` → `Flavor` → `Account` → `Character`; install auto-detection. A flavor is any `_name_` folder in the WoW folder, whatever it holds. `flavor_name(folder)` is `Flavor.display_name` for a flavor known only by its folder (journals, markers). `validate_output_dir()` refuses a tool output folder that is relative, the WoW folder, or inside a flavor's `WTF`/`Interface`/`Screenshots` (every tool with an output folder uses it on save and before use); `validate_backup_dir()` is that check for a tool's backup folder setting (WTF Cleaner, Interface Backup, Ace3 Profile Manager) |
| `journal` | Run journals, the suite standard for any tool that changes files: JSON Lines (header, one line per completed change flushed at once, `{"finished"}`, `{"undone"}`). `journal_dir(wow_path, tool)` = `<WoW>/wow-tools/<tool>/journal/`; `new_journal_path`, `JournalWriter` (`open()` exclusive-creates and writes the header, `add_entry()`, `finish()`, `discard_if_empty()`), `read_journal(path, path_fields=)`, `list_journals` (newest first), `latest_undoable` (newest journal with entries, never past an undone one), `mark_undone`, `prune_journals(dir, keep, event=)` (logs `event` with the removed names and `keep` when it removed any), `friendly_stamp`. Path values go through `to_stored()` / `to_native()`. Tools add their own entry fields and undo rules. `ToolJournals(tool, reader, pruned_event)` binds one tool's journals: each tool's `journal.py` makes one (`JOURNALS`) and exports its `dir` / `latest_undoable` / `prune` as `resolve_journal_dir` / `latest_undoable` / `prune_journals` (Interface Backup logs its own prune event, with the safety zips it drops) |
| `text` | `plural(n, word, words=None)` ("1 file", "2 copies") and `human_size(n)` (B, KB, MB, GB, TB; `MISSING` "—" for None): every tool's counts and sizes |
| `progress` | `ThrottledProgress(forward, interval=PROGRESS_INTERVAL)`: a worker's `progress(stage, current, total, detail)` forwarded to the UI only on a stage change, a stage's end, a report with no count, after `reset()`, or once per `PROGRESS_INTERVAL` (0.1 s; each `call_from_thread` blocks the worker). Several workers may share one: each thread is throttled on its own (its stage and last forward kept per thread; workers should report distinct stages), and the decision and the forward run under one lock, so reports reach the UI in the order they were decided. Interface Backup's jobs and the Ace3 scans use it |
| `marker` | Run-in-progress markers: `write_marker(folder, name, data)` (atomic JSON, Path values as `str()`), `read_marker(folder, name)` (a dict, or None when missing or unreadable; never raises), `clear_marker`. Each tool keeps its own `Marker` fields and checks (the WTF Cleaner's `clean-in-progress.json`, the Ace3 Profile Manager's `edit-in-progress.json`) |
| `undo` | What the WTF Cleaner's and the Ace3 Profile Manager's Undo share: `RESTORED` / `SKIPPED` / `FAILED`, `UndoResultBase` (a result dataclass's `restored` / `skipped` / `failed` lists) and `safe_destination(wow_root, flavor, rel, prefix=, min_parts=, parent=)`, `<WoW>/<flavor>/<rel>` or None unless flavor is one plain folder name and rel a relative path without `..`, `\` or `:` under `prefix` (the Ace3 tool asks for `WTF/Account/.../SavedVariables/<file>`) |
| `backup` | Zip + `manifest.json`, verified before it is moved into place; optional `on_file(current, total, name)` hook for progress. `verify_backup(zip, expected, progress)` reads every entry back (CRC) and compares sizes. `walk_files(folder, on_link=, on_error=, on_count=)`: every regular file under a folder as `DirEntry`s (depth first, names sorted), never following a link (each goes to `on_link`), an unreadable sub-folder to `on_error`; the WTF Cleaner's `wtf_files` and Interface Backup's scanner use it |
| `snapshot` | The whole-`WTF` safety zip shared by the tools that change SavedVariables: `wtf_files(flavor, progress)` (every regular file under `<flavor>/WTF`, links skipped), `take_snapshot(flavor, folder, prefix, now, progress=, must_hold=)` (zip to `folder/<prefix>-<flavor>-<stamp>.zip`, verify, `rename_no_replace` into place), `snapshot_path`, `prune_snapshots(folder, prefix, flavor_short, keep)`. The WTF Cleaner uses `backup/backup-…`, the Ace3 Profile Manager `snapshots/snapshot-…` |
| `svfiles` | SavedVariables safety checks shared by those tools: `SvGuard(flavor)` (refuses a path that resolves outside `<flavor>/WTF/Account` or not directly in a `SavedVariables` folder, `SvFileError`; each parent folder is resolved once, a file that is a link in full), `lstat_or_none`, `probe_lock(path)` (rename to `<name>.wowtools-lockcheck` and straight back; the error when another program holds it), `recover_probe_leftovers(folders)` (renames a probe leftover back after a crash) and `saved_variables_folders(flavor, account)` |
| `process` | Best-effort "is WoW running?" per flavor: `running_wow_processes()` returns `WowProcess(name, path)` (PowerShell `Get-CimInstance Win32_Process` on Windows/WSL, `/proc/<pid>/cmdline` on Linux, name-only `tasklist` fallback, `None` on macOS); `processes_for_flavor()` matches the executable's parent folder to the flavor folder, ignoring case and `\`/`/`; `wow_check_for(flavor)` is the check the review screen and CLI call |
| `updater` | GitHub Releases check (24 h throttle; a future stamp never throttles; records the release's assets), git fast-forward (120 s timeout per step that kills git's whole process tree, output via temp files, no prompts: `GIT_TERMINAL_PROMPT=0`, and `ssh -oBatchMode=yes` only when no `GIT_SSH_COMMAND`/`GIT_SSH`/`core.sshCommand` is set; untracked files ignored) or zip replace with rollback (downloads the `wow-tools-vX.Y.Z.zip` asset and checks its SHA-256 against the `SHA256SUMS` asset before touching anything; without `SHA256SUMS` it refuses unless `allow_unverified_updates`, then falls back to the zip asset or the source zipball; replaces the managed names plus only the root `*.md` files the release ships; keeps 2 `.update-backup/<version>` folders: the one this update made plus the highest other version); a zip update also removes `RETIRED_FILES` (the old `wtf-cleaner.cmd/.sh`) |

## Config schema

`config/wow-tools.cfg` `[general]`: `wow_path`, `last_flavor`, `check_for_updates`, `auto_update`, `allow_unverified_updates`,
`last_update_check`, `latest_seen_version`, `log_level`, `log_retention_days`, and the retention every tool shares:
`keep_backups` (`Config.keep_backups`: backups kept per flavor, WTF Cleaner snapshots and dry-run zips, Interface
Backup zips and Ace3 snapshots; default 10, 0 = keep all, negative or bad = 10) and `keep_journals`
(`Config.keep_journals`: run journals kept per tool, default 10, at least 1). Both are edited on the setup screen
(`#keep-backups`, `#keep-journals`). The per-tool `keep_backups` / `keep_snapshots` / `keep_journals` they replaced
are ignored, and each tool's `save_settings` drops them (`Config.remove_retired`).
Each tool owns one file with one section. `config/wtf-cleaner.cfg` `[wtf_cleaner]`: `max_age_days`, `criterion_*`, `backup_before_delete`,
`backup_dir` (empty = `<wow_path>/wow-tools/wtf-cleaner`, resolved by `settings.resolve_backup_dir()`) and
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

`scan(account=NAME)` is fully scoped: only that account's SavedVariables are read, and only its characters
decide the enabled set. `account=None` is the whole flavor.

All flavors (`tools/wtf_cleaner/multi.py`, UI-free) runs the same per-flavor functions in turn and changes none
of them:

    scan_flavors(flavors, account=None, progress=None) → [FlavorScan(flavor, result | None, error | None)]
    execute_flavors([(flavor, items), ...], dry_run, backup, backup_dir, account, keep_backups,
                    progress=None, on_flavor=None, journal_dir=None, keep_journals=10)
                      → MultiCleanResult(dry_run, runs[FlavorRun], journal_path, journals_pruned)

`scan_flavors` records a `ScanError` on that flavor and carries on (with several flavors the progress label
starts with the flavor's name). `execute_flavors` calls `execute()` per flavor, so each flavor gets its own WTF
backup, marker, cleaned-files zip, post-clean check and pruning; a `BackupError` or `CleanError` stops the run
before the next flavor (`clean.flavors_stopped`), and each `FlavorRun.status` is `done`, `stopped` or
`not_started`. The review screen uses both for one flavor too, so the single-flavor path is the same code.

`execute` guards every path (it must resolve inside `<flavor>/WTF/Account/**/SavedVariables`) and re-checks
size and mtime. For a real clean it then opens the run journal (when given one), takes the safety snapshot and
writes the marker (`safety.py`), writes and verifies the selective backup, and only then deletes, journaling each
file right after it is deleted. A dry run writes the backup (as `cleaned/dryrun-<flavor>-<account>-<stamp>.zip`) and deletes nothing; it takes
no snapshot, writes no journal, and then prunes the flavor's dry-run zips to the newest `keep_backups`
(`prune_dry_run_zips`). Real `cleaned-*.zip` files are never pruned.

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
- Both run in the caller's thread. The TUI runs scans and cleans in thread workers, so its callbacks forward
  to the UI with `app.call_from_thread` (the scan progress bar and `CleanProgressScreen`).

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
each target day folder and leaves out names already there. Unparsable names become `Skipped`. Progress is
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

    scan_flavors(flavors, with_stats=CHEAP_STATS, progress=None) → [FlavorScan(flavor, parts{Interface, WTF: PartScan}, leftovers)]
    back_up_all(scans, root, keep, progress=None, on_flavor=None) → [BackupOutcome(flavor, kind, path, files, bytes_in, bytes_zip, links, missing, reason, pruned)]
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
`newer`).

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
zips, other flavors or foreign files). `back_up_all` runs flavors in turn; one failing never stops the next.
Stages `backup`, `verify`, `prune`.

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

- `BackupReviewScreen(cfg, tool_cfg, flavors, scope_label, *, wow_check, disk_usage, wow_root)`: `ReviewBase`
  (`ui/review.py`), `two_pane_css`. Left pane `#filters`: "Backup folder", "Keep" ("newest N per flavor" / "all backups"), the
  action row **Back up** (apply), **Restore** (neutral: it opens the restore screen), **Rescan**, **Undo last
  restore** (revert; disabled when nothing is undoable), and the NavHint. Right: a `ReviewTree` (`#flavors`), filled
  after a worker scans (`scan_flavors`, `list_backups`, `latest_undoable`): the root (scope label, files and size
  ticked) → a node per flavor (tick, `report.flavor_text`) → read-only children: `Interface` and `WTF`
  (`part_text`), `Links (n)`, a leftover notice, `Scan warnings (n)` and `Backups (n)` (`backups_title`; safety
  zips counted apart). Links, warnings and Backups load their children on expand; a Backups node lists the
  flavor's zips newest first (`backup_text`: kind, date and time, parts, size), their parts read per
  zip by a worker (`read_parts`; `PARTS_PENDING` until read). Ticks are on flavors with something to back up only
  (and the root): `READ_ONLY` nodes keep their label on `relabel_branch`; ticks survive a rescan. `#summary` is
  `selection_text` plus the highlighted backup in full (`backup_detail`) or how to pick one, then "Restore blocked
  for …" and scan-warning counts. Keys Space, `a`, `n`, `b`, `e` (or Enter on a backup node: restores the
  highlighted backup; with none highlighted a notice says how), `r`, `z`; `f`/Esc, `t`, `q` leave. Back up,
  restore and undo each run the running-WoW check (and the backup drive's free space, for a backup and for a
  restore's safety backup; the undo also reads its journal there) in a worker, with "Checking for running
  programs…" on `#summary`, then a `ConfirmScreen` (Back up starts on Yes, Restore and Undo on No); the job runs
  in a worker with `app.busy` set, inside `activity.running()`, its per-file progress reaching the progress
  screen through `core.progress.ThrottledProgress` (on a stage change, at a stage's end, or every `PROGRESS_INTERVAL` = 0.1 s:
  each `call_from_thread` blocks the worker, and an `Interface` folder can hold tens of thousands of files). A
  `RestoreError` is a "Nothing was changed" notice, a `RestoreStopped` a notice plus its result screen; then a
  rescan;
- `BackupProgressScreen`, a `ProgressScreen` (ids `ibackup-*`) for a backup, restore or undo;
- `BackupResultScreen`: `result_css`; `#result-summary` (Item/Value, `report.backup_summary_rows`) above
  `#result-table` (a row per flavor, `report.BACKUP_RESULT_COLUMNS`); `r`, `e` (rescan, then open every flavor's
  Backups and put the cursor on the newest non-safety zip, the one just made), `f`, `t`, `q`.

`restore_screen.py` holds:

- `RestoreScreen(info, flavor, *, disk_usage)`: `TwoPaneFocus` and `ButtonActions`, `two_pane_css(width=46)` (two buttons only, and
  the tree's root and effect titles fit at 120 columns). Left: "Backup" (flavor, kind and date; size, parts
  and files once read; "made …" when the manifest's date differs), "Restore" with an `Interface` and a `WTF`
  `Ka0sCheckbox` (`#part-Interface`, `#part-WTF`; disabled for a part the backup lacks or that is a link; both off
  when a leftover, another flavor's backup or an unreadable zip blocks it), **Restore** (apply, `o`) and **Back**
  (`b`/Esc). Right: a `ReviewTree` (`#effects`) rooted at "<flavor> · <date>": "Will be removed (N files)" and
  "Newer now than in the backup (N files)" (open, one node per folder group from `report.group_items`, files on
  expand), "Links kept", "Links replaced", "Could not be read" (lines on expand), a low-space leaf, or "Nothing on
  disk would be lost"; while loading, with no box ticked or when blocked, one line saying so. `open_backup` +
  `scan_flavor` run in one worker, `plan_restore` in another on every box change (a generation counter drops
  stale plans); **Restore** is enabled only once the current plan is in. `#summary` is `report.restore_summary`.
  The confirm shows `report.restore_confirm_alerts` (one counted line per kind);
- `RestoreResultScreen(result)`: `result_css`; `#result-summary` (`report.restore_summary_rows`: flavor, finished
  or not, zip, safety zip and journal names, the zips' folder) above `#result-table` (a row per part,
  `report.RESTORE_RESULT_COLUMNS`); **Undo (z)** only for a restore whose journal recorded a swapped part
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
    undo_run(journal_path, wow_root, root, keep_snapshots, wow_check, progress) → UndoResult(outcomes, snapshots)
    recover(marker, root, journal_dir, keep_snapshots, wow_check, progress) → UndoResult

Modules in `tools/ace3_profile_manager/` (all UI-free except `app.py`, `review_screen.py`, `tree_view.py`, `popups.py`,
`blacklist_screen.py` and `result_screen.py`): `events`, `settings`, `luasv`, `model`, `scanner`, `ops`, `verify`, `editor`, `multi`,
`journal`, `undo` and `report` (labels, tags, stage titles, confirm texts, result rows).

**Never re-serialize.** Every change is a byte-span splice; every byte outside the edited spans stays identical.
Only `profileKeys` entries, `profiles` entries, `namespaces[*].profiles` entries and the LibDualSpec
`namespaces["LibDualSpec-1.0"].char[*]` spec values may change.

**Parse** (`luasv.py`). A stdlib tokenizer over the file's raw bytes (strings decode as UTF-8 with
`surrogateescape`). `parse(data, descend)` returns a `Chunk` of `Assignment`s; a table field is a `Field` with
`entry_start`/`entry_end` (the entry and its separator), `key_span`, and `remove_span` (what removing the entry
cuts: its whole line when nothing else is on that line); a `Table` records its braces. Values whose path `descend`
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
`SavedVariables/*.lua` (`candidate_files`: regular files directly in the folder, exactly `.lua`, not `Blizzard_*`,
no link), skipping a SavedVariables folder under a link (a scan warning). Each file is read once; `SvFile` keeps
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

**Apply** (`editor.apply_flavor`, `multi.apply_flavors`). `apply_flavors` refuses while WoW runs (`WowRunning`,
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
Afterwards journals are pruned to `keep_journals` and `prune_edited_zips` deletes only `edited-*.zip` files no kept
journal names (nothing when a journal cannot be read). The review screen checks the backup folder with
`validate_backup_dir` before an Apply, an Undo or a recovery (it may have been edited by hand in the cfg).

**Journal and Undo** (`journal.py`, `undo.py`). `<WoW>/wow-tools/ace3-profile-manager/journal/journal-<stamp>.jsonl`:

    {"version": 1, "started": iso, "tool": "ace3-profile-manager", "kind": "apply", "flavors": [...], "root": stored, "suite_version": "..."}
    {"action": "edited", "flavor": "_retail_", "path": stored, "rel": "WTF/Account/...", "zip": stored, "sha_before": hex, "sha_after": hex, "size_before": n, "size_after": n, "changes": [...]}
    {"action": "rolled_back", "flavor": "_retail_", "rels": [...]}
    {"finished": iso, "entries": n}
    {"undone": iso, "restored": n, "skipped": n}

`read_profile_journal` drops `edited` entries a `rolled_back` line names. `latest_undoable` is the newest journal of
the whole tool. `undo_run` refuses while WoW of a flavor the journal changed runs and when a file is locked
(`UndoError`), snapshots each of those flavors (pruned to `keep_snapshots` afterwards), then newest entry first: a file whose SHA-256 is `sha_after` gets
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

- `ProfileReviewScreen` (`review_screen.py`): `ReviewBase`, `two_pane_css`. Left pane `#filters`, one control per row: the
  View pair under a "View" heading (By addon / By character), the Show boxes under a "Show" heading, the search `Input`, the `#pending` line (`report.pending_text`, "N pending changes" or `NO_PENDING`) and the
  action row **Apply** (delete variant), **Dry run**, **Rescan**, **Undo last change** (revert). Right:
  `ProfileTree` (`#profiles`, a `ReviewTree` whose ↓ on the last line goes on to the action bar), built by `tree_view.TreeBuilder` from the scan, the staging and `Filters`; each
  rebuild keeps expansion and the cursor by `ident`. Labels and tags come from `report.profile_rows` and
  `char_tags`. Ticks are `("p", DbKey, profile)` and `("c", DbKey, char)`; groups tick their descendants; locked
  addons, deleted profiles, removed characters and notes are read-only. `#summary` is `report.selection_text`.
  The scan, the running-WoW preflight, Apply/dry run, Undo and recovery each run in a worker; the jobs set
  `app.busy` and run inside `activity.running()`.
  The tree sits in `#tree-pane` above the guidance line `#guide` (`report.guidance`: the four `STEPS` on the root,
  a flavor or an account or with nothing highlighted, else `report.node_hint` for the highlighted node; with
  pending changes the pending count and the w/y/⌫ keys come first, and the node hint follows within
  `GUIDE_MAX_ROWS` (2) rows: a name too long for the hint's row at 120x30 is shortened with "…", and the hint is
  left out only if even that does not fit; on a locked addon the hint names it and the `u` unlock) and the action
  bar `#tree-actions`, a
  `ActionBar` (a `WrapButtonRow`; ↑ goes back to the tree, and ↓ on the tree's last line comes to it) of
  `TREE_ACTIONS`, green first, then red, then the rest (Assign, Rename, Copy, Everyone → Default (E), Delete, Only
  Default (D), Leftovers, Blacklist…, More…, Discard: three rows at 120x30, two at 160x45), each button doing what
  its key does. The focused button's `ActionTip` (`action_tip()`: what it would do with the ticks or the
  highlighted node now) sits on its own `action-tip` layer just above the guidance line over the bar, and
  `_place_overlays()` keeps Textual's toast rack above the tip (or the guidance line). With nothing ticked, Delete and Assign act on the
  highlighted node, but never on the root, a flavor or an account (`GROUP_KINDS`). The guide follows the cursor, the ticks and the pending
  changes. Discard is Backspace (`x`/`c` are expand and collapse all); `b` toggles the highlighted addon's
  (flavor, addon) pair (`settings.toggle_pair`) and saves at once; **Blacklist…** (`action_edit_blacklist`) opens
  the `BlacklistScreen` for the review's flavors and saves its answer at once.
- `BlacklistScreen(cfg, flavors, pairs)` (`blacklist_screen.py`): `ReviewBase`, `two_pane_css`. Left pane: an
  explanation and **Save** / **Select none** / **Cancel** (Esc); right: a flavor → addon tree, from its own
  scan worker (`scan_flavors`), of every addon with Ace3 data plus each blacklisted pair no longer found
  ("(not found)"; a legacy `"*"` pair is listed under every shown flavor, so a Save, or a failed scan, never drops
  it). A ticked pair is blacklisted; nothing else is ticked. `a`/`n`/`x`/`c` as on every tree. It
  dismisses with the new pair list (or `None`); pairs of flavors it does not show are kept, and a legacy `"*"`
  pair is saved as explicit pairs (for the hidden flavors too).
- `popups.py`: `TargetScreen` (delete and assign: a target `Select` plus a new-name `Input`), `NameScreen` (rename
  and copy, with live validation) and `ActionsScreen` (the `m` menu: every key the footer
  and the action bar hide, under the `ACTION_GROUPS` headings Selection and Modification), sharing `popup_css`. Apply and Undo use `ConfirmScreen` (`report.apply_confirm`/`undo_confirm`; alerts
  in red; Apply and Undo start on No, a dry run on Yes).
- `ProfileProgressScreen` (ids `ace-*`, `report.STAGE_TITLES`) and `ProfileRecoveryScreen` (Put the originals
  back / Leave as is; Esc leaves the marker for the next scan).
- `ProfileResultScreen` (`result_screen.py`): `result_css`; `#result-summary` (`apply_summary_rows` or
  `undo_summary_rows`: zips and the journal are named inside the backup folder, `report.in_backup_folder`, which
  has a "Backup folder" row of its own) above `#result-detail` (`DETAIL_COLUMNS` or `UNDO_COLUMNS`); Rescan (r), Other flavor (f),
  Tools (t), Quit (q), plus a focused **Back to review (Esc)** after a dry run. After a real Apply or Undo the
  staging is dropped and the review rescans when shown again.

## UI

`Ka0sApp` registers the `ka0s` theme, starts the background update check, handles `u`, and exposes
the `after_mount()` hook. Every screen shows a `Header`, the `BrandBar` and a `Footer`. Long-running or blocking work
runs in thread workers and reports back with `call_from_thread`: scan, clean, organize, backup, restore, profile apply, undo, and also the
running-programs check before a clean, backup, restore or undo confirm (PowerShell/`tasklist`; the
review screen shows "Checking for running programs…" and ignores its action keys meanwhile), install detection on the setup screen, the organizer's
per-flavor waiting counts (`FlavorScreen.set_notes()`), and an accepted in-app update (`UpdateProgressScreen`,
with `app.busy` set). While a clean, organize, backup, restore, profile apply, recovery or undo runs, `app.busy` is set: every key that would leave the screen is refused, and so is Ctrl+Q
(`Ka0sApp.action_quit`, logged as `ui.quit_refused`).
An unhandled exception in a handler or worker is logged as `error` with `where=ui` by `Ka0sApp._handle_exception`
(a private Textual hook, pinned by a test) before Textual exits; `suite.run()` returns the app's `return_code`, so
`session.end` and the process exit status show the crash.

Shared screens and widgets in `wowtools/ui/`:

| Module | Job |
|---|---|
| `suite_app` | `WowToolsApp`, `ToolMenuScreen` (the first screen), `LockScreen` (another copy may be running: Quit, or Override and continue) |
| `tool_flow` | `ToolFlow` base: `start()`, `open_settings()`, `close()`, `require_install()` (shared WoW-folder setup) |
| `setup_screen` | General setup (a `FormScroll`, so ↑/↓ move between fields at any size): the WoW folder, and the retention every tool shares (`#keep-backups`, `#keep-journals`: `[general] keep_backups` / `keep_journals`) |
| `flavor_screen` | `FlavorScreen(cfg, install, *, include_all=False, last=None, flavors=None)`: the flavor picker. `include_all` adds "All flavors" first (dismisses with `ALL_FLAVORS`); `last` is the folder to pre-select (`""` = All flavors, `None` = `[general] last_flavor`); `flavors` replaces `install.flavors()`; `note`/`all_note` fill the remarks column and `set_notes()` replaces them later. Picking one flavor saves `[general] last_flavor`. |
| `account_screen` | `AccountScreen(cfg, flavor, last)`: "All accounts" plus each account. Dismisses with the name, `""` for all, or `None` for back. The WTF Cleaner and the Ace3 Profile Manager show it only when a flavor has more than one account and save the choice as their own `last_account`. |
| `dialogs` | What every tool's screens share, so no tool imports another tool's screens: `ConfirmScreen(title, body, alerts=(), *, default_yes=False, groups=None)` (yes/no; `alerts` in red; risky actions start on No; `groups` ({label: items}) listed in a `detail_tree`), `InfoScreen(title, groups, body="")` (something to read and acknowledge with OK, its details in a `detail_tree`), `detail_tree(groups)` / `detail_hint(groups)` (a popup's read-only tree, every branch open when it all fits in `DETAIL_ROWS` = 12 lines; `POPUP_TREE_CSS`), `ProgressScreen` (stage, bar and current file of a run; a tool subclasses it with `ID_PREFIX`, `STAGE_TITLES` and `SIMULATED_STAGE`, and calls `update_progress(stage, current, total, detail)`, plus `set_flavor(label)` across several flavors), `tick_mark(items, unchecked, key, success=)` (✔ / ◩ / ✘ for a review-tree line), `relabel_branch(tree, node, label, skip=)` (after a tick), the `TwoPaneFocus` mixin (←/→ between the left `#filters` panel and the tree; it is a `TreeKeys`, whose `x`/`c` expand and collapse every node below the root, bound with `TREE_BINDINGS` and named in the hint by `TREE_HINT`), `theme_colour(app, name)` (the theme's colour, or the Ka0s one before a theme is set), and the one look every tool's screens are built from: `two_pane_css(screen, tree, width=FILTERS_WIDTH)` (review: left pane `#filters`, `FILTERS_WIDTH` = 50, one-row actions, scan box, summary), `ACCENT` (names in a tree) and `BUSY_STYLE` (a summary line while work runs), `result_css(screen)` (the summary takes at most 60% of the height), `settings_css(screen)` (the form at `FORM_WIDTH`: up to 100 columns, centred; compact checkboxes), and the hint starts `REVIEW_HINT` / `review_hint(space)` and `RESULT_HINT` |
| `review` | The review screens' shared machinery (spec D9), so no tool copies it: `ReviewTree` (← to the left pane; the Ace3 `ProfileTree` adds ↓ to its action bar), `TickModel` (ticks kept as the ticked keys or as the unticked ones, changed in place; `unticked` feeds `tick_mark`) and `NotTicked`, and the mixins `ReviewBase` puts together over `TwoPaneFocus`: `TickActions` (Space ticks the highlighted node, presses a button, toggles a checkbox or types into an input; `a` / `n` act on `shown_tick_keys()` only: the screen's `all_tick_keys()` narrowed by `filter_keys()`, the one hook a filter takes, so hidden ticks stay; a screen supplies `tick_model()`, `node_tick_keys(node)`, `tick_log_key()`, `LOG_SCREEN` and, if it needs them, `all_tick_keys()`, `select_all_keys()`, `select_none_keys()` and `ticks_frozen()`, which `ReviewBase` sets while the running-programs check runs), `Preflight` (`run_preflight(check, then, extra)`: the running-programs check and `extra()` in a worker, `then(running, extra_result)` on the UI thread while the screen is shown; `_checking` and `_checking_changed()`, `PREFLIGHT_TEXT` on the summary), `ScheduledRebuild` (`_schedule_rebuild()`: the tree's loading indicator and "Updating the list…", then one `_rebuild()`), `ButtonActions` (`BUTTON_ACTIONS`: button id → action name), plus `action_leave(choice)` (never while `app.busy`), `show_scan_box(scanning, label)` and `_scan_progress(current, total, label)` |
| `widgets` | `action_button(label, action)` and `ACTION_VARIANTS` (one colour per kind of action in every tool: delete red, apply green, simulate blue, revert amber, confirm blue, neutral grey), `LIST_NAME_STYLE` / `LIST_CURSOR_BACKGROUND` (pick lists), `Ka0sCheckbox` (✔/✘ marks), `ButtonRow` (←/→ move focus between its buttons, Space presses the focused one), `WrapButtonRow` (a `ButtonRow` of compact one-row buttons in a grid whose column count follows its width; the Ace3 review's action bar), `NAV_BINDINGS` (↑/↓ move focus; not priority bindings, so a focused tree, list, table or input keeps its arrow keys), `NavSelect` (a `Select` that leaves ↑/↓ to `NAV_BINDINGS`; Enter or Space opens its list), and `NavHint` (the key hint every screen shows; when it takes more than one row it breaks only between its
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
- footers show every key whole at 120 columns: the command palette's key is hidden suite-wide (Ctrl+P still opens
  it), and keys that are on a button (the Ace3 review's `d`, `p`, `m`) are left off the footer;
- paths on result screens are named inside a "Backup folder" row (`cleaned/<name>`, `snapshots/<name>`, …) rather
  than whole, so they fit (a file outside that folder keeps its whole path); the Screenshot Organizer names its
  targets inside a "Target folder" row (`report.target_folder`), each keeping its YYYY/MM/DD; a tree line longer
  than its pane scrolls sideways.

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
`CleanerSettingsScreen` (criteria, max age, backup on/off, backup folder). The flow shows `FlavorScreen` with
`include_all=True` and `last=last_flavor_choice`; All flavors skips the account screen. `review_screen.py` holds:

- `ReviewScreen(cfg, tool_cfg, flavors, *, account, wow_check, locker_check)`: a `ReviewBase`; tree, criteria, the Clean /
  Dry run / Rescan buttons and **Undo last clean** (amber, key `z`, last in the same row; disabled when nothing is
  undoable, while scanning and while busy; its confirm starts on No and names the clean's time, flavors and file
  count). `flavors` is one `Flavor` (root = the flavor, accounts below) or a list (root = All
  flavors, a node per flavor, a "not scanned" leaf for a flavor whose scan failed). `wow_check` covers every
  flavor (`core.process.wow_check_for(list)` lists the processes once);
- the shared `ConfirmScreen` (`wowtools.ui.dialogs`): starts on No
  for a real clean and on Yes for a dry run; lists each flavor's counts;
- `CleanProgressScreen`, a `ProgressScreen` (ids `clean-*`): with several flavors the stage title names the
  flavor; also shown for an undo;
- `RecoveryScreen`: Dismiss or Remind me next time.

`result_screen.py` holds `ResultScreen(result, flavor=None)`: a summary table plus a per-file `DataTable`. With a
`MultiCleanResult` it shows Done / Stopped / Not started rows after a stop, one block of summary rows per finished
flavor, and a Flavor column (`report.MULTI_RESULT_COLUMNS`). Zips are named inside the backup folder (`cleaned/<name>`, `backup/<name>`), which has a "Backup folder" row of its own. A real clean adds a "Run journal" row: inside the backup folder when it is there (the default one holds
`journal/`), else its whole path with the Undo note on a row of its own. The per-file table puts Reasons before
Size and File, so why each file goes shows at 120x30. With an
`UndoResult` it is titled "undo result" and shows `report.undo_summary_rows` and `report.UNDO_COLUMNS`.

The Screenshot Organizer's screens live in `tools/screenshot_organizer/`. `app.py` holds `ScreenshotsFlow` (`FLOW`:
`require_install` → `ScreenshotSettingsScreen` on the tool's first open → `FlavorScreen(include_all=True,
note=<"no Screenshots folder" where missing>)` → review; every flavor is listed) and `ScreenshotSettingsScreen` (destination,
copy mode; `validate_dest` errors show inline). `review_screen.py` holds:

- `ShotReviewScreen`: a `ReviewBase`; the flavor → year → month → day → file tree (day files load on expand; read-only
  Conflicts and Skipped nodes; in copy mode an Already filed node, unticked, that `a` leaves alone) and the Organize / Dry run / Rescan / Undo last run buttons. It uses the
  shared `ConfirmScreen`;
- `ShotProgressScreen`, a `ProgressScreen` (ids `shots-*`): stage, bar and current file for a run, dry run or undo;
- `ShotResultScreen`: a summary table (with a "Target folder" row) plus a per-file `DataTable` whose Target column
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
