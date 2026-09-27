# Architecture

## Layers

    wowtools/__main__.py   Python check + vendor/ on sys.path, then suite.run()
    wowtools/suite.py      dispatcher: tools, `update`, tool picker, session events, auto-update
    wowtools/core/         UI-free framework shared by every tool (never imports textual)
    wowtools/ui/           shared Textual pieces: theme, branding, Ka0sApp, setup/flavor/picker screens
    wowtools/tools/<tool>/ one package per tool: logic modules (UI-free) + cli.py + Textual screens

Tool logic is pure Python over plain dataclasses, so the CLI, the TUI and the tests all drive the
same functions. Front ends stay thin.

## Core modules

| Module | Job |
|---|---|
| `bootstrap` | `REPO_ROOT`, `VENDOR_DIR`, Python ≥ 3.10 check, `add_vendor_path()` |
| `paths` | WSL detection; `to_native()` / `to_stored()` translate `G:\X` ⇄ `/mnt/g/X` |
| `config` | `wow-tools.cfg` INI: `[general]` + one section per tool; typed accessors; `config.changed` events |
| `events` | Registry of event names with fixed levels; JSONL + text sinks; `log_event()`; `capture_events()` for tests |
| `install` | `WowInstall` → `Flavor` → `Account` → `Character`; install auto-detection |
| `backup` | Zip + `manifest.json`, verified before it is moved into place; optional `on_file(current, total, name)` hook for progress |
| `process` | Best-effort "is WoW running?" per flavor: `running_wow_processes()` returns `WowProcess(name, path)` (PowerShell `Get-CimInstance Win32_Process` on Windows/WSL, `/proc/<pid>/cmdline` on Linux, name-only `tasklist` fallback, `None` on macOS); `processes_for_flavor()` matches the executable's parent folder to the flavor folder, ignoring case and `\`/`/`; `wow_check_for(flavor)` is the check the review screen and CLI call |
| `updater` | GitHub Releases check (24 h throttle), `UpdateCheck` thread, git fast-forward or zip replace with rollback |

## Config schema

`[general]`: `wow_path`, `last_flavor`, `check_for_updates`, `auto_update`,
`last_update_check`, `latest_seen_version`, `log_level`, `log_retention_days`.
Each tool owns one section. `[wtf_cleaner]`: `max_age_days`, `criterion_*`, `backup_before_delete`,
`backup_dir` (empty = `<wow_path>/wow-tools/wtf-cleaner`, resolved by `settings.resolve_backup_dir()`) and
`last_account` (empty = all accounts). `[general] backup_dir` is no longer read. Paths are stored in Windows form when they point at a
Windows drive. Unknown keys are preserved, and bad values fall back to defaults.

## WTF Cleaner data flow

    scan(flavor, account=None, progress=None) → ScanResult(installed, enabled, groups[SVGroup[SVFile]])
    evaluate(scan, Criteria) → Proposal(items[ProposalItem(group, files, reasons)])
    TUI/CLI selection → execute(items, flavor, dry_run, backup, backup_dir, progress=None)
                      → CleanResult(outcomes, backup_path, snapshot_path, restored)

`scan(account=NAME)` is fully scoped: only that account's SavedVariables are read, and only its characters
decide the enabled set. `account=None` is the whole flavor.

`execute` guards every path (it must resolve inside `<flavor>/WTF/Account/**/SavedVariables`) and re-checks
size and mtime. For a real clean it then takes the safety snapshot and writes the marker (`safety.py`),
writes and verifies the selective backup, and only then deletes. A dry run writes the backup and deletes
nothing; it takes no snapshot.

### Safety snapshot (`tools/wtf_cleaner/safety.py`)

UI-free. `take_snapshot()` zips the whole `<flavor>/WTF` folder to `wtf-snapshot_<flavor>_<stamp>.zip`
in the backup folder and verifies it. `write_marker()` / `read_marker()` / `clear_marker()` manage
`clean-in-progress.json` (`Marker`: snapshot, flavor, flavor_path, started, pid, suite_version, files).
`restore_deleted()` extracts exactly the given relative paths and never overwrites an existing file.
`recovery_message()` is the text the TUI's `RecoveryScreen` and the CLI show for a leftover marker.

In `cleaner.execute`:

- If the snapshot or marker fails, a `BackupError` is raised and nothing is deleted.
- A leftover marker from an earlier clean also refuses a real clean.
- An unexpected exception while deleting (anything but a per-file `OSError`, including `KeyboardInterrupt`)
  restores only this run's deletions and raises `CleanError` (with `.restored`).
- If that restore fails, the marker and snapshot are kept.
- On success (including per-file failures) the snapshot and marker are removed.
- Nothing ever restores automatically at start-up.

### Progress callbacks

- `scan(progress=cb)` calls `cb(current, total, label)` once per SavedVariables folder. The total counts every
  account and character folder in scope.
- `execute(progress=cb)` calls `cb(stage, current, total, detail)` with stage `snapshot`, `backup`, `verify`
  or `delete`. The callback is wrapped so an exception inside it is swallowed and never disturbs a clean.
- Both run in the caller's thread. The TUI runs scans and cleans in thread workers, so its callbacks forward
  to the UI with `app.call_from_thread` (the scan progress bar and `CleanProgressScreen`). The CLI prints one
  line per stage change, and nothing in `--json` mode.

## UI

`Ka0sApp` registers the `ka0s` theme, starts the background update check, handles `u`, and exposes
the `after_mount()` hook. Every screen shows a `Header`, the `BrandBar` and a `Footer`. Long-running work
(scan, clean) runs in thread workers and reports back with `call_from_thread`.

Shared screens and widgets in `wowtools/ui/`:

| Module | Job |
|---|---|
| `setup_screen` | General setup: the WoW folder only |
| `flavor_screen` | Flavor picker (last flavor pre-selected) |
| `account_screen` | `AccountScreen(cfg, flavor, last)`: "All accounts" plus each account. Dismisses with the name, `""` for all, or `None` for back. The WTF Cleaner shows it only when a flavor has more than one account and saves the choice as `[wtf_cleaner] last_account`. |
| `widgets` | `Ka0sCheckbox` (✔/✘ marks), `ButtonRow` (←/→ move focus between its buttons, Space presses the focused one), `NAV_BINDINGS` (↑/↓ move focus; not priority bindings, so a focused tree, list, table or input keeps its arrow keys), and `NavHint` (the one-line key hint every screen shows) |

The WTF Cleaner's own screens live in `tools/wtf_cleaner/`. `app.py` holds `WtfCleanerApp` and
`CleanerSettingsScreen` (criteria, max age, backup on/off, backup folder). `review_screen.py` holds:

- `ReviewScreen`: tree, criteria, and the Clean / Dry run / Rescan buttons;
- `ConfirmScreen`: starts on No for a real clean and on Yes for a dry run;
- `CleanProgressScreen`;
- `RecoveryScreen`: Dismiss or Remind me next time;
- `ResultScreen`: a summary table plus a per-file `DataTable`.

## Testing

`python3 -m unittest discover -s tests -t .`. `tests/fixtures.py` builds a synthetic install in a temp
folder, and TUI tests use Textual's `App.run_test()` pilot. No test touches a real WoW folder or the network.
