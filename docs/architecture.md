# Architecture

## Layers

    wow-tools.sh / .cmd    the only entry point (runs python -m wowtools)
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
| `config` | `config/wow-tools.cfg` (`[general]`) plus `config/<tool>.cfg` per tool (`tool_config_path()`); typed accessors; `config.changed` events; `migrate_legacy_config()` splits the old root `wow-tools.cfg` |
| `lock` | `InstanceLock` on `wow-tools.lock` (O_EXCL create; holder pid, host, start time, platform, token). `acquire()` returns the holder on conflict; `take_over()`; `release()` removes the file only if it is still ours. `LockInfo.stale` is known only on POSIX for a lock from this host |
| `events` | Registry of event names with fixed levels; JSONL + text sinks; `log_event()`; `capture_events()` for tests |
| `install` | `WowInstall` → `Flavor` → `Account` → `Character`; install auto-detection |
| `backup` | Zip + `manifest.json`, verified before it is moved into place; optional `on_file(current, total, name)` hook for progress |
| `process` | Best-effort "is WoW running?" per flavor: `running_wow_processes()` returns `WowProcess(name, path)` (PowerShell `Get-CimInstance Win32_Process` on Windows/WSL, `/proc/<pid>/cmdline` on Linux, name-only `tasklist` fallback, `None` on macOS); `processes_for_flavor()` matches the executable's parent folder to the flavor folder, ignoring case and `\`/`/`; `wow_check_for(flavor)` is the check the review screen and CLI call |
| `updater` | GitHub Releases check (24 h throttle), git fast-forward or zip replace with rollback; a zip update also removes `RETIRED_FILES` (the old `wtf-cleaner.cmd/.sh`) |

## Config schema

`config/wow-tools.cfg` `[general]`: `wow_path`, `last_flavor`, `check_for_updates`, `auto_update`,
`last_update_check`, `latest_seen_version`, `log_level`, `log_retention_days`.
Each tool owns one file with one section. `config/wtf-cleaner.cfg` `[wtf_cleaner]`: `max_age_days`, `criterion_*`, `backup_before_delete`,
`backup_dir` (empty = `<wow_path>/wow-tools/wtf-cleaner`, resolved by `settings.resolve_backup_dir()`) and
`last_account` (empty = all accounts). `config/screenshots.cfg` `[screenshots]`: `dest_dir` (empty = in place),
`copy_mode`, `last_flavor_choice` (empty = all flavors, else a flavor folder) and `keep_journals` (default 10, at
least 1). The retired `[general] backup_dir` is dropped by the migration. Paths are stored in Windows form when they point at a
Windows drive. Unknown keys are preserved, and bad values fall back to defaults.

## WTF Cleaner data flow

    scan(flavor, account=None, progress=None) → ScanResult(installed, enabled, groups[SVGroup[SVFile]])
    evaluate(scan, Criteria) → Proposal(items[ProposalItem(group, files, reasons)])
    TUI selection → execute(items, flavor, dry_run, backup, backup_dir, progress=None)
                      → CleanResult(outcomes, backup_path, snapshot_path, restored)

`scan(account=NAME)` is fully scoped: only that account's SavedVariables are read, and only its characters
decide the enabled set. `account=None` is the whole flavor.

`execute` guards every path (it must resolve inside `<flavor>/WTF/Account/**/SavedVariables`) and re-checks
size and mtime. For a real clean it then takes the safety snapshot and writes the marker (`safety.py`),
writes and verifies the selective backup, and only then deletes. A dry run writes the backup and deletes
nothing; it takes no snapshot.

### Safety snapshot (`tools/wtf_cleaner/safety.py`)

UI-free. `take_snapshot()` zips the whole `<flavor>/WTF` folder to `backup/backup-<flavor>-<stamp>.zip`
in the backup folder and verifies it; the user-facing name is "WTF backup". It is kept after the clean, and
`prune_snapshots(backup_dir, flavor_short, keep)` deletes all but that flavor's newest `keep_backups`
(`backup-<flavor>-<stamp>.zip` names only).
The zip of the files a clean removes is `cleaned/cleaned-<flavor>-<account or all>-<stamp>.zip` (`cleaner.cleaned_zip_path`). `write_marker()` / `read_marker()` / `clear_marker()` manage
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

Modules in `tools/screenshots/` (all UI-free except `app.py` and `review_screen.py`): `naming` (`parse_shot_name`,
`day_parts`), `settings` (`ShotSettings`, `source_dir`, `target_root`, `resolve_journal_dir`, `validate_dest`),
`planner`, `organizer`, `journal`, `undo` and `report` (labels, stage titles, rows and the confirm text).

**Targets.** `target_root(flavor, dest_dir)` is `<dest_dir>/<flavor folder>`, or the flavor's `Screenshots`
folder when `dest_dir` is `None` (in place). A shot goes to `target_root/YYYY/MM/DD/<name>`; the day comes from
`WoWScrnShot_MMDDYY_HHMMSS.<jpg|jpeg|png|tga>` only. `validate_dest` (settings screen only) refuses the WoW folder
itself and anything inside a flavor's `Screenshots` folder.

**Scan.** One listing per `Screenshots` folder (top-level files only) and one names-only listing
(`planner.list_names`) per target day folder. Only a name already at the target is stat'ed, to set the state:
`new`, `maybe_duplicate` (same size) or `conflict` (other size). Unparsable names become `Skipped`. Progress is
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
`os.rename`; on `EXDEV` (and always in copy mode) `copy_verified` copies to `<name>.partial`, checks size and
SHA-256, then renames into place. After a cross-device move a failed source delete is `source_left`, a warning. A
`FileExistsError` from the last check is `conflict`. Nothing is ever overwritten. A dry run walks the same checks,
hashing included, and reports `would_move` / `would_copy` / `would_remove_duplicate`; it creates no folders and
writes no journal. A per-file `OSError` is `failed` and the run continues; anything else (including
`KeyboardInterrupt`) raises `OrganizeError` with `.result`. Progress is `cb(stage, current, total, detail)` with
the stages in `report.STAGE_TITLES` (`organize`, `prune`, `undo`), wrapped by `organizer.safe_progress`.

**Journal** (`journal.py`). A real run writes `<WoW>/wow-tools/screenshots/journal/journal-<YYYYMMDD-HHMMSS>.jsonl`
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
entry passes a lexical guard (`src` directly in a `Screenshots` folder of a flavor under `wow_root`; `dst` ending
in `YYYY/MM/DD/<src name>`), then:

- `moved`: if `dst` has the recorded size and `src` is free, move it back (`move_file`, copy-verify-delete across
  devices; a failed delete of the archive copy is still `restored`, with a reason);
- `copied` / `copied_source_left`: delete `dst` if both `src` and `dst` have the recorded size (`copy_removed`);
- `duplicate_removed`: if `src` is free and `dst` has the recorded size, `copy_verified(dst, src)`;
- anything else, or a failed check, is `undo_skipped`; an `OSError` is `failed`.

Then the `DD`, `MM` and `YYYY` folders it touched are removed bottom-up while empty and digit-named, and an
`undone` line is appended (even when every entry was skipped).

## UI

`Ka0sApp` registers the `ka0s` theme, starts the background update check, handles `u`, and exposes
the `after_mount()` hook. Every screen shows a `Header`, the `BrandBar` and a `Footer`. Long-running work
(scan, clean, organize, undo) runs in thread workers and reports back with `call_from_thread`.

Shared screens and widgets in `wowtools/ui/`:

| Module | Job |
|---|---|
| `suite_app` | `WowToolsApp`, `ToolMenuScreen` (the first screen), `LockScreen` (another copy may be running: Quit, or Override and continue) |
| `tool_flow` | `ToolFlow` base: `start()`, `open_settings()`, `close()`, `require_install()` (shared WoW-folder setup) |
| `setup_screen` | General setup: the WoW folder only |
| `flavor_screen` | `FlavorScreen(cfg, install, *, include_all=False, last=None, flavors=None)`: the flavor picker. `include_all` adds "All flavors" first (dismisses with `ALL_FLAVORS`); `last` is the folder to pre-select (`""` = All flavors, `None` = `[general] last_flavor`); `flavors` replaces `install.flavors()`. Picking one flavor saves `[general] last_flavor`. |
| `account_screen` | `AccountScreen(cfg, flavor, last)`: "All accounts" plus each account. Dismisses with the name, `""` for all, or `None` for back. The WTF Cleaner shows it only when a flavor has more than one account and saves the choice as `[wtf_cleaner] last_account`. |
| `widgets` | `Ka0sCheckbox` (✔/✘ marks), `ButtonRow` (←/→ move focus between its buttons, Space presses the focused one), `NAV_BINDINGS` (↑/↓ move focus; not priority bindings, so a focused tree, list, table or input keeps its arrow keys), and `NavHint` (the one-line key hint every screen shows) |

The WTF Cleaner's own screens live in `tools/wtf_cleaner/`. `app.py` holds `WtfCleanerFlow` (`FLOW`) and
`CleanerSettingsScreen` (criteria, max age, backup on/off, backup folder). `review_screen.py` holds:

- `ReviewScreen`: tree, criteria, and the Clean / Dry run / Rescan buttons;
- `ConfirmScreen`: starts on No for a real clean and on Yes for a dry run;
- `CleanProgressScreen`;
- `RecoveryScreen`: Dismiss or Remind me next time;
- `ResultScreen`: a summary table plus a per-file `DataTable`.

The Screenshot Organizer's screens live in `tools/screenshots/`. `app.py` holds `ScreenshotsFlow` (`FLOW`:
`require_install` → `ScreenshotSettingsScreen` on the tool's first open → `FlavorScreen(include_all=True,
flavors=<flavors with a Screenshots folder>)` → review) and `ScreenshotSettingsScreen` (destination, journals to
keep, copy mode; `validate_dest` errors show inline). `review_screen.py` holds:

- `ShotReviewScreen`: the flavor → year → month → day → file tree (day files load on expand; read-only
  Conflicts and Skipped nodes) and the Organize / Dry run / Rescan / Undo last run buttons. It reuses the
  cleaner's `ConfirmScreen`;
- `ShotProgressScreen`: stage, bar and current file for a run, dry run or undo;
- `ShotResultScreen`: a summary table plus a per-file `DataTable`.

## Testing

`python3 scripts/run_tests.py` deals the tests round-robin into one process per CPU (at most 16); `python3 -m
unittest discover -s tests -t .` runs them in one process. Textual tests subclass `tests.fixtures.TuiTestCase`,
which turns off asyncio debug mode. `tests/fixtures.py` builds a synthetic install in a temp
folder, and TUI tests use Textual's `App.run_test()` pilot. No test touches a real WoW folder or the network.
