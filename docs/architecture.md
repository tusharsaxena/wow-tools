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
| `backup` | Zip + `manifest.json`, verified before it is moved into place |
| `process` | Best-effort "is WoW running?" (tasklist / tasklist.exe / /proc) |
| `updater` | GitHub Releases check (24 h throttle), `UpdateCheck` thread, git fast-forward or zip replace with rollback |

## Config schema

`[general]`: `wow_path`, `backup_dir`, `last_flavor`, `check_for_updates`, `auto_update`,
`last_update_check`, `latest_seen_version`, `log_level`, `log_retention_days`.
Each tool owns one section (`[wtf_cleaner]`). Paths are stored in Windows form when they point at a
Windows drive. Unknown keys are preserved, and bad values fall back to defaults.

## WTF Cleaner data flow

    scan(flavor) → ScanResult(installed, enabled, groups[SVGroup[SVFile]])
    evaluate(scan, Criteria) → Proposal(items[ProposalItem(group, files, reasons)])
    TUI/CLI selection → execute(items, flavor, dry_run, backup, backup_dir) → CleanResult(outcomes)

`execute` guards every path (it must resolve inside `<flavor>/WTF/Account/**/SavedVariables`), re-checks
size and mtime, writes and verifies the backup, and only then deletes.

## UI

`Ka0sApp` registers the `ka0s` theme, starts the background update check, handles `u`, and exposes
the `after_mount()` hook. Every screen shows a `Header`, the `BrandBar` and a `Footer`. Long-running work
(scan, clean) runs in thread workers and reports back with `call_from_thread`.

## Testing

`python3 -m unittest discover -s tests -t .`. `tests/fixtures.py` builds a synthetic install in a temp
folder, and TUI tests use Textual's `App.run_test()` pilot. No test touches a real WoW folder or the network.
