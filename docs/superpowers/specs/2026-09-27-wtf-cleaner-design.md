# Ka0s WoW Tools — Framework + WTF Cleaner Design

- **Date:** 2026-09-27
- **Status:** Draft for review
- **Scope:** The shared `wow-tools` framework and its first tool, the WTF Cleaner. The screenshot organizer is a later, separate spec.

## 1. Purpose

`wow-tools` is a repo of out-of-game companion tools for World of Warcraft, branded **Ka0s**. The tools share one framework: a single config, one set of vendored libraries, a common WoW-install model and common TUI screens. They run with no install step on Windows and on Linux/WSL.

The first tool is the **WTF Cleaner**. Over time the WTF folder collects SavedVariables (SV) files from addons that are no longer installed, no longer enabled, or long abandoned, plus hand-made backup copies. The cleaner finds these files, proposes them for deletion with the reason for each, backs them up to a timestamped zip, and deletes them only after you confirm. A dry-run mode simulates the whole process.

**Success criteria**
- On a fresh clone: run `wtf-cleaner.cmd` (Windows) or `./wtf-cleaner.sh` (Linux/WSL), answer the first-run questions, pick a flavor, review a proposal, and clean. No pip, no virtualenv.
- Nothing is deleted without a verified backup, unless the user explicitly opts out.
- Every proposed file shows the reason it was proposed.
- The same config file works from both Windows and WSL.

## 2. Constraints and decisions

| Topic | Decision |
|---|---|
| Language | Python ≥ 3.10, stdlib plus vendored pure-Python libs |
| TUI | Textual (with Rich), vendored |
| Vendoring | `vendor/` is committed to git and populated by `scripts/update_vendor.py` via `pip install --target vendor -r requirements.txt` (pinned) |
| Entry point | `python -m wowtools <tool> [args]`; `wowtools/__main__.py` adds `vendor/` to `sys.path` before any third-party import. Thin wrappers: `wtf-cleaner.cmd`, `wtf-cleaner.sh` |
| Config | `wow-tools.cfg` (INI, `configparser`) in the repo root, git-ignored |
| Paths | `wow_path` is stored in Windows form and translated automatically under WSL (`G:\X` ⇄ `/mnt/g/X`) |
| Front ends | TUI (default) **and** a non-interactive CLI, both thin layers over a UI-free core |
| Criteria | Four, each toggleable. Default: all on, and a group is flagged if **any** criterion matches |
| "Enabled" scope | **Global** within the flavor: enabled on any character in any account protects the addon's SV files everywhere |
| Tests | Stdlib `unittest`; Textual's `App.run_test()` for the TUI |

## 3. Repo layout

```
wow-tools/
├── README.md                     # user-facing
├── CLAUDE.md                     # dev notes
├── .gitignore                    # wow-tools.cfg, logs/, __pycache__/, backups/, .update-backup/
├── requirements.txt              # pinned textual + deps
├── wtf-cleaner.cmd               # @py -3 -m wowtools wtf-cleaner %*   (falls back to python)
├── wtf-cleaner.sh                # exec python3 -m wowtools wtf-cleaner "$@"
├── vendor/                       # committed third-party libs
├── scripts/update_vendor.py
├── wowtools/
│   ├── __init__.py               # __version__
│   ├── __main__.py               # bootstrap vendor/, dispatch subcommand; no args → tool picker
│   ├── core/                     # no UI imports
│   │   ├── bootstrap.py          # vendor path setup + Python version check
│   │   ├── config.py             # load/save wow-tools.cfg, typed accessors, defaults
│   │   ├── paths.py              # WSL detection, Windows⇄WSL translation
│   │   ├── install.py            # WowInstall → Flavor → Account → Realm → Character
│   │   ├── backup.py             # zip writer + manifest + verification
│   │   ├── process.py            # best-effort "is WoW running?"
│   │   ├── updater.py            # GitHub release check + self-update
│   │   └── events.py             # suite event log (JSONL + text), event registry
│   ├── ui/                       # shared Textual pieces
│   │   ├── theme.py              # Ka0s theme + branding widgets
│   │   ├── setup_screen.py       # first-run / settings wizard
│   │   └── flavor_screen.py      # flavor picker
│   └── tools/
│       ├── __init__.py           # tool registry: name → (cli main, tui app)
│       └── wtf_cleaner/
│           ├── scanner.py        # installed/enabled addons, SV discovery, grouping
│           ├── rules.py          # criteria → Proposal
│           ├── cleaner.py        # recheck, backup, delete / simulate
│           ├── events.py         # EVENTS registry for this tool
│           ├── cli.py
│           └── app.py            # Textual app + screens
├── tests/
│   ├── fixtures.py               # synthetic WoW tree builder
│   └── test_*.py
└── docs/
    ├── architecture.md
    ├── adding-a-tool.md
    ├── vendoring.md
    ├── releasing.md
    └── assets/ka0s-logo.png
```

**Rule:** `core/` and the non-UI modules of each tool (`scanner`, `rules`, `cleaner`) never import Textual. They can be tested and used from the CLI without it.

## 4. Shared framework

### 4.1 Bootstrap (`__main__.py`, `core/bootstrap.py`)
- Checks that Python is ≥ 3.10, with a readable message otherwise.
- Inserts `<repo>/vendor` at the front of `sys.path`.
- Starts the background update check (§4.9) for every tool.
- Dispatches: `python -m wowtools wtf-cleaner …` goes to the registered tool. `python -m wowtools update [--check]` goes to the updater. No argument opens a small Textual tool picker. `--help` lists the tools.
- A tool runs its TUI unless CLI-mode flags are given (see §6.6).

### 4.2 Config (`core/config.py`)
INI file `wow-tools.cfg` in the repo root:

```ini
[general]
wow_path = G:\Games\Blizzard\World of Warcraft
backup_dir = G:\Games\Blizzard\World of Warcraft\wow-tools-backups
last_flavor = _retail_
check_for_updates = true
auto_update = false
last_update_check = 2026-09-27T12:00:00
latest_seen_version = 0.1.0
log_level = info
log_retention_days = 90

[wtf_cleaner]
max_age_days = 90
criterion_not_installed = true
criterion_not_enabled = true
criterion_older_than = true
criterion_stray_copies = true
backup_before_delete = true
```

- Path values are stored in Windows form when they came from a Windows or WSL-translatable path. Other Linux paths (e.g. native Linux WoW under Wine/Lutris) are stored as-is.
- Missing keys fall back to defaults. Unknown keys are preserved on save.
- Each tool owns one section. `[general]` is shared.
- Default `backup_dir` is `<wow_path>/wow-tools-backups`.

### 4.3 Paths (`core/paths.py`)
- `is_wsl()`: checks `/proc/version` for `microsoft`/`WSL`.
- `to_native(p)`: under WSL, `X:\a\b` becomes `/mnt/x/a/b`. On Windows or native Linux, the path is unchanged.
- `to_stored(p)`: under WSL, `/mnt/x/a/b` becomes `X:\a\b`. Otherwise the path is unchanged.
- All code works on native `pathlib.Path` objects from `to_native()`.

### 4.4 Install model (`core/install.py`)
- `WowInstall(root)` validates that `root` contains at least one flavor folder.
- **Flavor discovery** means any direct child folder matching `_*_`, e.g. `_retail_`, `_classic_`, `_classic_era_`, `_anniversary_`, `_classic_beta_`, `_ptr_`, `_beta_`. Display names come from a known-name map, and unknown flavors fall back to title-casing (`_classic_beta_` → "Classic Beta").
- `Flavor` exposes `addons_dir`, `wtf_dir`, and `accounts()`.
- `Account(name, path)` exposes `saved_variables_dir` and `characters()`.
- `Character(account, realm, name, path)` exposes `saved_variables_dir` and `addons_txt`.
- Realm and character discovery covers the subdirectories of `Account/<acct>/` other than `SavedVariables`, and their subdirectories.
- Directory names are read as `str` from the filesystem, so the UTF-8 names WoW writes (e.g. `Aellâ`) are handled as-is.
- **Auto-detect** candidates for setup: common Windows install paths (`C:\Program Files (x86)\World of Warcraft`, `C:\Program Files\…`, `<drive>:\Games\…`, and `<drive>:\…\Blizzard\World of Warcraft` on every existing drive letter up to a shallow depth). Under WSL these are checked via `/mnt/<drive>/`.

### 4.5 Backup (`core/backup.py`)
- `create_backup(files, base_dir, dest_zip, manifest_extra)` writes a ZIP_DEFLATED archive. Entries are stored relative to `base_dir` (the flavor folder), so they start with `WTF/Account/...`.
- Adds `manifest.json`, which contains the tool, version, flavor, timestamp, and a list of files, each with its relative path, size, modified time and reasons.
- **Verification:** re-open the zip, run `testzip()`, and check that the entry set and sizes match the input. Anything else raises `BackupError`.
- Restoring means unzipping into the flavor folder. This is documented in the README. No restore command is included in this version.

### 4.6 WoW running check (`core/process.py`)
- Windows: `tasklist` filtered for `Wow.exe`, `WowClassic.exe`, `WowB.exe`, `WowT.exe`.
- WSL: the same, via `tasklist.exe`.
- Linux: `/proc/*/comm` matching those names (for Wine).
- Returns a bool or `None` (unknown). The check is only a warning and never blocks.

### 4.7 Event log (`core/events.py`)
The suite has one structured, extendable event log that every tool shares.

**Sinks**
- `logs/events-YYYY-MM-DD.jsonl` is the source of truth. It records **every** event at every level, including debug, with one JSON object per line.
- `logs/wow-tools-YYYY-MM-DD.log` holds the same events rendered as readable lines. It is filtered by `[general] log_level` (default `info`). Example line:
  `2026-09-27 14:03:11 INFO  [wtf-cleaner] sv.deleted  _retail_ ADD1KTED2KA0S Frostmourne/Aellâ Auctionator.lua (12.4 KB) reasons=not_enabled`
- Files older than `log_retention_days` (default 90) are pruned at session start.
- `logs/` lives in the repo root and is git-ignored.

**Envelope (schema `v` = 1)**
```json
{"v": 1, "ts": "2026-09-27T14:03:11.482+10:00", "session": "3f9a1c2e",
 "suite_version": "0.1.0", "tool": "wtf-cleaner", "mode": "tui",
 "event": "sv.deleted", "level": "info", "dry_run": false,
 "data": {"flavor": "_retail_", "path": "WTF/Account/…/Auctionator.lua", "size": 12698, "reasons": ["not_enabled"]}}
```
- `ts` is local time in ISO-8601 with a UTC offset.
- `session` is 8 random hex characters per launch.
- `tool` is `suite` for events from the dispatcher or picker.
- `mode` is `tui` or `cli`.
- `dry_run` is set when relevant, otherwise `null`.
- `data` is event-specific. New fields may be added to `data` at any time. The envelope only changes with a `v` bump.

**Registry and levels**
- Every event name is declared once, with a fixed level and a description. `core/events.py` holds `CORE_EVENTS`, and each tool has an `EVENTS` dict in `<tool>/events.py` that it registers at startup.
- `log_event(name, **data)` looks up the level. Logging an unregistered name is a programming error: it raises in tests and logs `error` in production.
- `docs/events.md` lists every event and is generated by `scripts/gen_event_docs.py` from the registries.

| Event | Level | Data |
|---|---|---|
| `session.start` | info | argv, platform, is_wsl, python, suite_version |
| `session.end` | info | exit_code, duration_s |
| `config.created` | info | path |
| `config.changed` | info | section, key, old, new, source (`wizard`, `settings`, `cli`, `app`) |
| `ui.selection` | info | screen, control, value (flavor, criteria toggle, max age, dry-run toggle, confirm yes/no, tool picked, update accepted/declined) |
| `ui.item_toggled` | debug | screen, key, checked (per group/file tick) |
| `update.checked` | debug | current, latest, throttled |
| `update.check_failed` | debug | error |
| `update.available` | info | current, latest |
| `update.applied` | info | from, to, method |
| `update.failed` | error | method, error |
| `wow.running_warning` | warning | executables |
| `error` | error | where, type, message, traceback |
| **wtf-cleaner** | | |
| `scan.started` | info | flavor, wow_path |
| `scan.addons` | debug | installed (list), enabled (list) |
| `scan.completed` | info | flavor, installed, enabled, accounts, characters, sv_files, groups, duration_s |
| `scan.warning` | warning | path, message |
| `proposal.built` | info | criteria, max_age_days, items, files, bytes, by_reason |
| `proposal.item` | debug | account, character, addon, reasons, files |
| `clean.started` | info | items, files, bytes, dry_run, backup |
| `backup.created` | info | zip, files, bytes, verified |
| `backup.would_create` | info | zip, files, bytes |
| `backup.failed` | error | zip, error |
| `sv.deleted` | info | flavor, account, character, path, size, reasons |
| `sv.would_delete` | info | same as above |
| `sv.skipped` | warning | path, reason (`missing`/`changed`) |
| `sv.failed` | error | path, error |
| `clean.completed` | info (warning if any failed) | deleted, would_delete, skipped, failed, bytes |

**Safety**
- Logging never breaks a tool. If an I/O error occurs, that sink is disabled for the session and a single warning goes to stderr (CLI) or a toast (TUI).
- The log contains only metadata and paths, never file contents.

### 4.8 Theme and branding (`ui/theme.py`)
The Textual theme is registered as `ka0s` and taken from the Ka0s shield logo: a near-black navy background, deep-blue panels, glowing electric-blue accents, and steel-silver text.

| Token | Value | Use |
|---|---|---|
| background | `#05080F` | app background |
| surface | `#0B1526` | panels, tree |
| panel | `#10213D` | header/footer, dialogs |
| primary | `#2F8CFF` | focus, selection, buttons |
| accent | `#5CC8FF` | glow highlights, active borders |
| foreground | `#D3DAE3` | body text (steel silver) |
| secondary | `#8A96A8` | muted text, metadata |
| success | `#4CC38A` | |
| warning | `#E8B04B` | dry-run banner, WoW-running warning |
| error | `#E5534B` | |

Branding:
- The header title is **"Ka0s · WoW Tools"**, with the tool name as sub-title.
- A small Unicode shield/"K" banner with the tagline **"Ka0s WoW Tools"** in accent blue appears on the tool picker and the setup wizard.
- The footer shows `Ka0s` and the version.
- The README shows `docs/assets/ka0s-logo.png` at the top.

### 4.9 Suite updater (`core/updater.py`)
The updater applies to the **whole suite**, not to individual tools.

**Versioning**
- The whole suite has one version, `wowtools.__version__` (semver, starting at `0.1.0`).
- Releases are GitHub Releases tagged `vX.Y.Z` on `tusharsaxena/wow-tools`.
- The release steps are in `docs/releasing.md`.

**Check on load**
- `__main__.py` starts the check before the tool picker or any tool.
- It calls `GET https://api.github.com/repos/tusharsaxena/wow-tools/releases/latest` using stdlib `urllib`. No auth is needed, the timeout is 3 seconds, and it runs in a daemon thread so startup never waits on the network.
- It checks at most once every 24 hours via `last_update_check`, and caches `latest_seen_version`.
- It is disabled with `check_for_updates = false`. Drafts and pre-releases are ignored.
- Versions are compared as semver tuples.
- Every failure (offline, rate limit, bad JSON) is logged and otherwise silent.

**Notify**
- **TUI:** a toast and a header badge: "Ka0s WoW Tools vX available (you have vY)". A release-notes view offers `u` to update now.
- **CLI:** one line on stderr. There is no notice in `--json` mode.
- **`python -m wowtools update`** applies the update. With `--check`, it only reports and exits 0 if the suite is up to date or 10 if an update is available.

**Auto update**
- `auto_update = false` is the default: the updater notifies and waits for the user to press `u` or run the command.
- When `auto_update = true`, the update is applied at launch before any tool starts, and the app asks the user to restart.

**Apply.** The method depends on how the suite was obtained:
- **Git checkout** (`.git` present): `git fetch --tags`, then `git merge --ff-only v<X.Y.Z>`.
  - It refuses with a clear message if there are uncommitted changes, the branch has diverged, or git is not available.
- **Zip download** (no `.git`):
  1. Download the release zipball to a temp dir and extract it to staging.
  2. Validate that `wowtools/__init__.py` exists and has the expected version.
  3. Copy the current **managed paths** (`wowtools/`, `vendor/`, `scripts/`, `docs/`, root `*.md`, `wtf-cleaner.cmd`, `wtf-cleaner.sh`, `requirements.txt`) to `.update-backup/<old-version>/`.
  4. Replace the managed paths from staging.
  5. On any failure, roll back automatically from `.update-backup/`.
- **Never touched:** `wow-tools.cfg`, `wow-tools.log*`, backup zips, and anything not on the managed list.
- **After applying:** "Updated to vX. Restart to use the new version", then a clean exit. There is no hot reload.
- **Safety:** an update is never applied while a clean is running. The TUI only offers `u` from the tool picker, flavor and review screens.

## 5. WTF Cleaner — scanning

### 5.1 Installed addons
- Every folder under `<flavor>/Interface/AddOns/` that contains at least one `*.toc` counts. This includes flavor-suffixed TOCs (`Foo_Mainline.toc`, `Foo-Classic.toc`, `Foo_Vanilla.toc`, etc.). The addon name is the folder name.
- Names are compared case-insensitively (casefold).

### 5.2 Enabled addons (global)
- For each character in each account of the flavor, parse `AddOns.txt`. Lines have the form `Name: enabled|disabled`. Surrounding whitespace is stripped, and malformed lines are ignored.
- `enabled_set` is the union of addons listed `enabled`.
- Plus: for each character, installed addons **not listed** in its `AddOns.txt` count as enabled, because WoW's default is on.
- Plus: a character with **no** `AddOns.txt` contributes all installed addons.

### 5.3 SV discovery and grouping
- Scanned locations:
  - `WTF/Account/<acct>/SavedVariables/`
  - `WTF/Account/<acct>/<realm>/<char>/SavedVariables/`
- Only regular files directly in these folders are scanned (no recursion).
- **Addon name** is the part of the filename before the first occurrence of `.lua` (case-insensitive). Files with no `.lua` are ignored.
- A **group** is (scope = account or character, the owner, addon name) together with all its files.
- **Canonical files** are exactly `<Addon>.lua` and `<Addon>.lua.bak`. Every other file in the group is a **stray copy** (e.g. `Foo.lua.pre-schema8-20260926-103400`, `Foo.lua - Copy.bak`, `Foo.lua.before-x`).

### 5.4 Protection (never proposed)
- Groups whose addon name starts with `Blizzard_` (case-insensitive).
- Anything outside a `SavedVariables/` folder: `config-cache.wtf`, bindings, macros, `AddOns.txt`, layout files, etc.
- **Safety abort:** if `Interface/AddOns` is missing or has no addons, the scan raises `ScanError`. Otherwise every SV file would look not-installed.

## 6. WTF Cleaner — rules, flow, cleaning

### 6.1 Criteria (`rules.py`)
Each criterion is toggleable in config, the TUI and the CLI. Default: all on, and an item is flagged if any criterion matches.

| Criterion | Unit | Flags when |
|---|---|---|
| `not_installed` | group | addon not in the installed set |
| `not_enabled` | group | addon installed but not in `enabled_set` |
| `older_than` | group | the **newest** modified time among the group's files is older than `max_age_days` (default 90) |
| `stray_copies` | file | the file is a stray copy (§5.3). Applies even when the group is otherwise kept |

- A flagged group proposes **all** its files.
- An unflagged group with stray copies proposes **only those stray files**.
- Each `ProposalItem` records the account, the character (if character-scoped), the addon, the scope, the files (path, size, modified time), the reasons (a list), the total size and the newest modified time.
- A `Proposal` holds the items plus totals and scan warnings (e.g. unreadable directories).

### 6.2 TUI flow (`app.py`)
1. **Setup wizard** runs when there is no config or `wow_path` is invalid. It can be reopened with `s`. The fields are: WoW folder (auto-detected choices plus a text input, validated), backup folder, max age, the four criterion toggles, and backup-before-delete. The answers are saved to the config.
2. **Flavor picker** lists the flavors found on disk with the last one used pre-selected, and saves `last_flavor`.
3. **Scan and review:**
   - Scanning runs in a worker with a loading indicator.
   - The results are shown as a tree: Account → "Account-wide" and one node per `Realm / Character` → addon group, showing reasons, file count, size and age. Group nodes expand to individual files.
   - Everything starts checked. `space` toggles the current item, and `a`/`n` select all or none.
   - Criterion filter toggles (keys `1`–`4`) re-evaluate the proposal live, and the max age can be edited inline.
   - A summary bar shows the selected groups, files and bytes.
   - `d` toggles **dry run**. When dry run is on, a warning-colored **DRY RUN** banner appears in the header.
   - `c` starts cleaning, `r` rescans, `q` quits.
4. **Confirm dialog** shows the counts and size, the backup path (or "no backup" in red), the dry-run state, and the WoW-running warning if it applies.
5. **Result screen** shows the backup zip path, the deleted (or would-delete) count and size, and a list of skipped and failed files with their reasons. From there you can go back to the flavor picker or quit.

### 6.3 Clean pipeline (`cleaner.py`)
`execute(selection, *, dry_run, backup, flavor, backup_dir) -> CleanResult`

1. **Re-check** each selected file. Skip it (reason `missing` or `changed`) if it no longer exists or its modified time or size differs from the scan.
2. **Path guard.** Resolve each path and require it to be inside `<flavor>/WTF/Account/` and inside a `SavedVariables` folder. Anything else aborts with an error. This is a programming-error guard.
3. **Backup** (if enabled and not a dry run): write `<backup_dir>/wtf-cleaner_<flavor>_<YYYYMMDD-HHMMSS>.zip` and verify it. On any failure, abort and delete nothing.
4. **Delete** each file with `Path.unlink()`. Per-file errors are collected, and processing continues.
5. **Dry run:** steps 1–2 run for real. Steps 3–4 are only reported ("would write …", "would delete …"). No files are created or removed.
6. Every step emits the corresponding events (§4.7).

### 6.4 WoW running
The check runs before the confirm step, as a warning (§4.6).

### 6.5 Error handling summary
| Situation | Behavior |
|---|---|
| Config missing/unreadable | TUI → setup wizard; CLI → error with hint (`run the TUI once or pass --wow-path`) |
| `wow_path` invalid | re-validated every launch; same as above |
| Unreadable directory during scan | skipped, added to the proposal's warnings, `scan.warning` |
| Malformed `AddOns.txt` line | ignored |
| Empty/missing `Interface/AddOns` | `ScanError`, nothing proposed |
| Backup failure | whole clean aborted, nothing deleted |
| Per-file delete failure | recorded, rest continue, shown in results |
| Path outside `WTF/Account/**/SavedVariables` | abort (guard) |

### 6.6 CLI (`cli.py`)
```
python -m wowtools wtf-cleaner [--flavor NAME] [options]

  (no --clean)          print the proposal and exit (read-only)
  --clean               back up and delete the proposal after a y/N prompt
  --yes                 skip the prompt
  --dry-run             simulate even with --clean
  --no-backup           skip the zip; refused unless --yes is also given
  --max-age N           override max_age_days
  --criteria LIST       comma list of not_installed,not_enabled,older_than,stray_copies
  --wow-path PATH       override config wow_path
  --backup-dir PATH     override config backup_dir
  --json                machine-readable proposal/result on stdout
  --tui                 force the TUI
```
- CLI mode is active whenever any of `--flavor`, `--clean`, `--json` or `--dry-run` is given. Otherwise the TUI launches.
- `--flavor` accepts the folder name or a short form (`retail`, `classic`, `classic_era`, `anniversary`, …). If it's omitted in CLI mode, `last_flavor` is used, and if that's unset the CLI exits with an error.
- Exit codes: 0 ok, 1 usage/config error, 2 scan error, 3 clean completed with per-file failures, 4 backup failure.

## 7. Testing
- The `tests/fixtures.py` builder creates a temp WoW tree with:
  - `_retail_` and `_classic_era_`, 2 accounts, and several realms and characters.
  - One character without `AddOns.txt`.
  - Installed addons, including one with a flavor-suffixed TOC only.
  - Uninstalled-addon SVs, installed-but-disabled addons, and enabled addons.
  - `Blizzard_*` SVs, stray copies, non-SV files, and controlled modified times.
- **Unit tests:** path translation; config round-trip and defaults; flavor, account and character discovery; TOC detection; `AddOns.txt` parsing and the enabled union; grouping and stray detection; each criterion alone and in combination; protections; the safety abort; backup zip contents, manifest and verification failure; the dry run leaving the tree byte-identical; the re-check skipping changed files; the path guard; CLI argument handling, JSON output and exit codes.
- **Event log tests:** envelope fields; level taken from the registry; unregistered name raises; text sink respects `log_level` while JSONL keeps debug; retention pruning; I/O failure disables the sink without raising; the cleaner and config emit the expected events (captured with an in-memory sink).
- **Updater tests:** version comparison; 24h throttle; disabled flag; network failure is silent (mocked `urlopen`); git path refuses on a dirty tree (temp git repo); zip path replaces managed paths, preserves `wow-tools.cfg` and logs, and rolls back on a mid-apply failure (local fake zipball).
- **TUI tests:** `App.run_test()` pilot through setup → flavor → review → dry-run clean → result, against the fixture tree.
- Run with `python -m unittest` from the repo root. The test package bootstraps `vendor/` itself.
- Tests never touch a real WoW install.

## 8. Documentation
- **README.md** (user-facing):
  - Ka0s logo, what the repo is, and the list of tools.
  - Requirements (Python 3.10+).
  - Quick start for Windows and for Linux/WSL.
  - First-run setup and how to change settings.
  - WTF Cleaner: what it does, the four criteria with examples, the TUI key reference, CLI usage with examples, dry run, backups and **how to restore**.
  - Safety notes (close WoW first; `Blizzard_*` and game settings are never touched).
  - Where the config and log live, and an FAQ/troubleshooting section.
- **docs/architecture.md:** layering (core / ui / tools), bootstrap, config schema, install model, Windows⇄WSL paths, theme.
- **docs/adding-a-tool.md:** a step-by-step guide to adding a tool (registry entry, config section, reusing the flavor and setup screens and theme, tests), using the future screenshot organizer as the running example.
- **docs/events.md:** generated event reference plus envelope description and how a tool adds events.
- **docs/releasing.md:** bump `__version__`, commit, tag `vX.Y.Z`, push, `gh release create`; how the updater consumes releases.
- **docs/vendoring.md:** updating and adding libraries with `scripts/update_vendor.py`, pinning, and keeping libraries pure-Python.
- **CLAUDE.md:** commands, layout, conventions (no Textual in core, stdlib tests, Windows-form stored paths).

## 9. Out of scope (this spec)
- Restore command (restoring is a manual unzip, documented in the README).
- Updater rollback to an arbitrary older version; signed releases.
- Cleaning non-SV WTF files (config-cache, bindings, macros).
- Per-character/per-account "enabled" scoping (global was chosen).
- Screenshot organizer (separate spec; §3 and §4 are designed for reuse by it).
- Packaging (pyz/exe).
