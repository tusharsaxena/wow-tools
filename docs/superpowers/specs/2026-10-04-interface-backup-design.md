# Ka0s WoW Tools: Interface Backup design

Date: 2026-10-04. Third tool in the suite. It follows `docs/adding-a-tool.md` and the conventions of the WTF
Cleaner and Screenshot Organizer specs.

## 1. Purpose

Take a full backup of a WoW flavor's `Interface` and `WTF` folders as one timestamped zip per flavor, and restore a
flavor from such a backup. Restoring is an exact replace, guarded by a pre-restore safety backup, warnings about
anything that would be lost, and Undo.

## 2. Decisions

| Topic | Decision |
|---|---|
| Flavor scope | Flavor picker with **All flavors** first, then each flavor. The choice is remembered. There is no account picker. |
| Backup location | `<backup folder>/interface-backup/backup-<flavor>-<YYYYMMDD-HHMMSS>.zip`, `<flavor>` being the flavor's short name (`retail`, `classic_era`), `-2`, `-3`, ... when the name is taken. The backup folder setting is empty by default, meaning `<WoW folder>/wow-tools`. |
| Zip contents | `Interface/...` and `WTF/...` (paths relative to the flavor folder) plus `manifest.json`. All flavors makes one zip per flavor. |
| Dry run | None. A backup only reads the game folders. |
| Retention | `keep_backups` (default 10; **0 = never delete**): after a successful backup, only the newest N `backup-<flavor>-*.zip` of that flavor are kept. Asked on the tool's first-run settings screen. |
| Restore | Pick a backup, choose Interface, WTF or both (both ticked), and the parts are replaced **exactly** (files not in the backup are removed), after warnings listing what would be lost. Only into the backup's own flavor. |
| Safety net | Before a restore, the current state of the parts being restored is zipped to `pre-restore-<flavor>-<stamp>.zip` beside the backups. A run journal records the restore. **Undo (z)** restores the safety zip the same way. |
| WoW running | Checked before a backup, a restore and an undo (as the WTF Cleaner does). Warn in the confirm dialog, allow going on. |
| Links | Symlinks and junctions under `Interface`/`WTF` (addon developers link addon folders to their repos) are never followed, never zipped and never deleted through. A backup lists them in the manifest and in the result. A restore keeps links that exist on disk, unless the backup holds real files at that path (then the link itself is removed, never its target, with a warning). |
| Free space | A backup or restore whose estimated need exceeds the free space on the target drive gets a warning in the confirm dialog (not a block). |
| Interrupted restore | Leftover `Interface.restoring` / `Interface.replaced` (or the WTF ones) produce a notice on the summary screen and block a new restore of that flavor until resolved by hand. Nothing is repaired automatically. |

## 3. Package layout

`wowtools/tools/interface_backup/`. Tool name `interface-backup`, config `config/interface-backup.cfg` with section
`[interface_backup]`, logs in `logs/interface-backup/`, journals in `<WoW>/wow-tools/interface-backup/journal/`.
Menu entry: "Interface Backup", "Zip a flavor's Interface and WTF folders, and restore them."

| Module | Job |
|---|---|
| `__init__.py` | imports `events` |
| `events.py` | the tool's event registry (§9), prefix `ibackup.` |
| `settings.py` | `BackupSettings`, `load_settings`, `save_settings`, `resolve_backup_root(settings, wow_path)` (= `<backup_dir or WoW/wow-tools>/interface-backup`), `resolve_journal_dir(wow_path)`, `validate_backup_dir(dir, install)` |
| `catalog.py` | backup file names: `BACKUP_NAME` / `SAFETY_NAME` regexes, `backup_path(root, flavor_short, now)`, `safety_path(...)`, `list_backups(root, flavors=None) -> list[BackupInfo]` (newest first; reads each zip's manifest lazily), `prune_backups(root, flavor_short, keep)`, `prune_safety(root, referenced)` |
| `scanner.py` | `scan_flavor(flavor, progress) -> FlavorScan` (files, links, total size per part; leftover staging folders) |
| `backup.py` | `back_up(flavor, scan, root, now, progress) -> BackupOutcome` (zip, verify, rename into place) |
| `restore.py` | `open_backup(path) -> BackupContents` (verify + entry safety check), `plan_restore(contents, flavor, parts) -> RestorePlan` (warnings), `restore(plan, *, root, journal_dir, keep_journals, progress) -> RestoreResult` |
| `undo.py` | `undo_restore(journal_path, *, wow_root, root, progress) -> RestoreResult` |
| `journal.py` | the tool's entry fields over `core/journal.py`, `read_restore_journal` |
| `report.py` | labels, stage titles, size formatting, summary and result rows (UI-free text helpers) |
| `app.py` | (UI) `InterfaceBackupFlow` (`FLOW`), `BackupSettingsScreen` |
| `summary_screen.py` | (UI) `BackupSummaryScreen`, `BackupProgressScreen`, `BackupResultScreen` |
| `restore_screen.py` | (UI) `BackupListScreen`, `RestoreScreen`, `RestoreResultScreen` |

Everything except the three UI modules is UI-free and never imports `textual`.

Shared code: the scandir walker that `wtf_cleaner/safety.wtf_files` uses moves to `core/backup.walk_files(folder,
progress, on_link)` (the cleaner's function becomes a thin wrapper, same behaviour), and `core/fsutil` gains
`is_link(entry_or_path)` (symlink, or a Windows junction / reparse point) and `remove_tree_no_follow(path)` (deletes
a folder tree, unlinking links without descending into them).

## 4. Settings (`[interface_backup]` in `config/interface-backup.cfg`)

| Key | Default | Meaning |
|---|---|---|
| `backup_dir` | empty | Backup folder. Empty means `<WoW folder>/wow-tools`. Zips go to `<backup_dir>/interface-backup/`. Stored in Windows form. |
| `keep_backups` | 10 | Backups to keep per flavor; 0 = never delete. Negative or bad values fall back to 10. |
| `keep_journals` | 10 | Restore journals to keep (at least 1). |
| `last_flavor_choice` | empty | Empty means All flavors, otherwise a flavor folder such as `_retail_`. |

`validate_backup_dir` is `validate_output_dir(...)`: absolute, not the WoW folder, not inside any flavor's
`WTF`/`Interface`/`Screenshots`. Checked on save and again before each run. The first time the tool is opened the
settings screen asks for the backup folder and backups to keep (like the organizer's first-run settings).

## 5. Scan (`scanner.py`)

`scan_flavor(flavor, progress)` walks `<flavor>/Interface` and `<flavor>/WTF` with `walk_files` (directory entries
only: one `stat` per file through the cached `DirEntry.stat()`, never `resolve()`, because WSL drvfs is slow):

    FlavorScan(flavor, parts: dict[str, PartScan], leftovers: list[Path])
    PartScan(name: "Interface" | "WTF", exists: bool, files: list[FileInfo], links: list[Path], size: int)
    FileInfo(path: Path, rel: str, size: int, mtime: float)

A missing part has `exists=False`. Unreadable folders are reported with `ibackup.scan_warning` and skipped.
`leftovers` are `<flavor>/<part>.restoring` and `<part>.replaced` folders. Progress `progress(stage, current, total,
detail)` every 100 files. The summary screen runs one scan per chosen flavor in a worker. The backup and the
restore plan reuse that scan; the backup does no extra `stat` per file (a file that vanished shows up as `zf.write`
failing with `FileNotFoundError`).

## 6. Backup (`backup.py`)

`back_up(flavor, scan, root, now, progress)`:

1. A flavor whose parts are both missing gives `skipped` ("no Interface or WTF folder").
2. Write `backup-<short>-<stamp>.zip.partial` in `root` (created if needed), `ZIP_DEFLATED`,
   `strict_timestamps=False`, every file as `<part>/<rel>`. A file that vanished since the scan is left out and
   listed in the outcome (`missing_since_scan`); any other `OSError` fails the backup.
3. Append `manifest.json`: `{"version": 1, "kind": "backup" | "pre-restore", "flavor", "flavor_folder",
   "created", "suite_version", "parts": [...], "files": [{"path", "size", "mtime"}], "links": [{"path"}]}`.
4. `core.backup.verify_backup` (CRC of every entry, sizes against the manifest), then `rename_no_replace` into place.
   Any failure (including `KeyboardInterrupt`) removes the `.partial`.
5. Prune (`keep_backups > 0`): keep the newest N `backup-<short>-*.zip` of that flavor; never other flavors', never
   `pre-restore-*`, never foreign files.

`BackupOutcome(flavor, kind: created | skipped | failed, path, files, bytes_in, bytes_zip, links, missing, reason,
pruned)`. All flavors runs flavors one after the other; one failing does not stop the next. Stages: `backup`,
`verify`, `prune`. No journal: nothing in the game folders changes.

## 7. Restore (`restore.py`)

**Open.** `open_backup(path)` reads the manifest and checks every entry name: no absolute path, no drive, no `..`,
no backslash, first part `Interface` or `WTF`, no duplicates. An unsafe or missing manifest refuses the backup
("not an Interface Backup zip"). Verification (CRC read of every entry) runs as the first restore stage, after the
confirm, because it reads the whole zip.

**Plan.** `plan_restore(contents, scan, parts)` compares the backup's entries for the chosen parts with the current
scan and returns:

    RestorePlan(backup, flavor, parts, removed: list[FileInfo], newer: list[FileInfo], links_kept, links_removed,
                missing_parts, bytes_needed)

- `removed`: files on disk that are not in the backup (they would be lost), grouped for display by their first
  three path parts (`Interface/AddOns/WeakAuras (312 files)`, `WTF/Account/NAME (40 files)`).
- `newer`: files on disk whose mtime is more than 2 s later than the backup's copy.
- `links_kept` / `links_removed` as in §2.
- A part the backup does not contain cannot be ticked.

**Run.** `restore(plan, ...)`, for a real restore only:

1. Open the journal (`JournalWriter`, header `{"version": 1, "flavor", "flavor_folder", "backup", "parts",
   "suite_version"}`); stop if it cannot be written.
2. Verify the backup (stage `verify`).
3. **Safety backup** of the chosen parts as they are now: `pre-restore-<short>-<stamp>.zip`, manifest `kind:
   "pre-restore"`, recording for each part whether it existed. Journal `{"action": "safety_backup", "zip",
   "parts_existing"}`. A failure here stops the restore with nothing changed.
4. For each chosen part:
   - Extract its entries into `<flavor>/<part>.restoring` (refusing to start if it already exists), setting each
     file's mtime from the manifest.
   - Move the links to keep from `<part>` into the staging folder at the same relative path.
   - Swap: rename `<part>` to `<part>.replaced` (skipped when the part does not exist), rename `<part>.restoring` to
     `<part>`. If the second rename fails, `<part>.replaced` is renamed back and the moved links are put back:
     the part is exactly as before (`rolled_back`).
   - Journal `{"action": "replaced", "part", "existed"}`, then `remove_tree_no_follow(<part>.replaced)`. A failure
     to delete the old copy is a warning (`replaced_left`, the folder path in the result); the restore stands.
5. `finish()`, then prune journals (`keep_journals`) and delete `pre-restore-*` zips no remaining journal names.

Errors: a per-part `OSError` rolls that part back and continues with the next. Any other exception stops; the
journal holds what was done, the exception goes to the UI, which points at Undo. Stages: `verify`, `safety`,
`extract`, `swap`, `cleanup`.

`RestoreResult(flavor, parts: list[PartOutcome(part, kind: restored | rolled_back | failed | replaced_left,
reason)], safety_zip, journal_path)`.

## 8. Undo (`undo.py`)

`latest_undoable(journal_dir)` (core) gives the newest restore not yet undone. `undo_restore(path, ...)`:

- Requires the journal's `safety_backup` zip to exist and verify; otherwise Undo is refused with the reason.
- For each `replaced` entry, newest first: if the part `existed` before, it is restored from the safety zip with
  the same extract-and-swap (no further safety backup, no warnings); if it did not exist, the restored part is
  moved to `<part>.replaced` and deleted.
- The path guard: the flavor folder in the journal must be a flavor of the configured WoW folder, the part must be
  `Interface` or `WTF`, and the safety zip must be in the backup root.
- Afterwards `mark_undone`. An undone journal is never offered again.

## 9. Events (`events.py`, tool `interface-backup`)

| Event | Level | When |
|---|---|---|
| `ibackup.scan_started` / `ibackup.scan_completed` | info | a scan of the chosen flavors; per flavor and part: files, bytes, links |
| `ibackup.scan_warning` | warning | a folder could not be read |
| `ibackup.leftover_found` | warning | a `.restoring` / `.replaced` folder from an interrupted restore |
| `ibackup.backup_started` | info | a backup run: flavors, destination |
| `ibackup.backup_created` | info | one zip written and verified: path, files, sizes |
| `ibackup.backup_skipped` | warning | a flavor had neither folder |
| `ibackup.backup_failed` | error | a flavor's backup failed (no zip left behind) |
| `ibackup.links_skipped` | info | links not followed (count + up to 20 paths) |
| `ibackup.pruned` | info | old backups deleted |
| `ibackup.restore_started` | info | backup, flavor, parts, warnings counts |
| `ibackup.safety_created` | info | the pre-restore zip |
| `ibackup.part_restored` | info | a part swapped in |
| `ibackup.part_rolled_back` | warning | a part left as it was after a failure |
| `ibackup.replaced_left` | warning | the old copy could not be deleted |
| `ibackup.restore_completed` | info | totals (warning if a part failed) |
| `ibackup.restore_stopped` | error | stopped unexpectedly; journal holds what was done |
| `ibackup.journal_pruned` | info | old journals (and their safety zips) deleted |
| `ibackup.undo_started` / `ibackup.undo_completed` | info | undo of a restore journal |
| `ibackup.undo_failed` | error | undo refused or failed on a part |

`docs/events.md` is regenerated.

## 10. TUI

Every screen has `Header`, `BrandBar`, `Footer` and `NavHint`, the shared `NAV_BINDINGS`, `ButtonRow`,
`action_button`, `Ka0sCheckbox`, `ConfirmScreen` and a `ProgressScreen` subclass. `s` opens the shared WoW-folder
settings, then this tool's settings; `t` goes back to the tool menu; `q` quits; `u` stays the app-wide update key.

Flow (`InterfaceBackupFlow`): `require_install` → first open: `BackupSettingsScreen` → `FlavorScreen(include_all=True,
last=...)` (notes filled by a worker: "last backup <date>" or "no backups yet") → `BackupSummaryScreen`.

- **`BackupSettingsScreen`**: backup folder (placeholder "Empty = <WoW folder>\wow-tools"; a line shows where zips
  go), backups to keep per flavor ("0 = never delete"), restore journals to keep. Error line on invalid input.
- **`BackupSummaryScreen`**: a scan worker with a progress line, then a `DataTable` with one row per flavor: flavor,
  Interface (files, size), WTF (files, size), links, backups (count, newest). Right/below: destination folder,
  journal folder, notices (leftovers, links). Buttons: **Back up (b)**, **Restore (e)**, **Undo last restore
  (z)** (amber, disabled when nothing is undoable), **Rescan (r)**, **Flavors (f)**, **Tools (t)**.
- **Back up** → running-WoW check (worker) → `ConfirmScreen` "Back up N flavors (X files, Y) to <folder>?" with
  alerts (WoW running, low space), `default_yes=True` (nothing is changed) → `BackupProgressScreen` (flavor label,
  stage title, bar, current file) → `BackupResultScreen`: a table per flavor (outcome, zip, files, size in → zip
  size, pruned) and buttons **Rescan (r)**, **Restore (e)**, **Flavors (f)**, **Tools (t)**, **Quit (q)**.
- **Restore** → `BackupListScreen`: backups (and, marked, safety zips) of the chosen flavors, newest first: date,
  flavor, kind, parts, size. Enter picks one; Esc goes back.
- **`RestoreScreen`**: the backup's details, checkboxes **Interface** and **WTF** (both ticked, disabled for a part
  the backup lacks), and a warnings pane recomputed (worker) when a box changes: "Will be removed (N files)" with
  the groups (first 15, "and N more"), "Newer now than in the backup (N files)", links kept/removed, low space.
  Buttons: **Restore (o)**, **Back (b)**, Esc. Blocked with a message when a leftover exists for the flavor.
- **Confirm**: "Replace <parts> of <flavor> with the backup from <date>?" with the warnings as alerts, starting on
  **No**. Then the running-WoW check alert, `BackupProgressScreen`, and **`RestoreResultScreen`**: per part outcome,
  the safety zip, the journal, and buttons **Undo (z)**, **Rescan (r)**, **Flavors (f)**, **Tools (t)**,
  **Quit (q)**.
- **Undo**: confirm "Undo the restore from <stamp>: put <flavor> <parts> back as they were?", starting on No.

## 11. Testing

`tests/fixtures.py` gains `build_interface_tree(root)`: the synthetic install with `_retail_/Interface/AddOns/<a,b>`,
`_retail_/WTF/Account/...`, `_classic_era_` with only `WTF`, and a flavor with neither. Link tests create a
symlink when the platform allows it (skipped otherwise).

- `test_interface_backup_settings.py`: round trip, defaults, `keep_backups=0`, validation.
- `test_interface_backup_catalog.py`: names, `-2` collisions, listing, prune (per flavor, 0 = keep all, never
  safety or foreign files), safety prune by journal reference.
- `test_interface_backup_scanner.py`: parts, missing parts, links not followed, leftovers, progress.
- `test_interface_backup_backup.py`: zip layout and manifest, verify failure removes `.partial`, vanished file,
  All flavors continues after a failure, prune after success only.
- `test_interface_backup_restore.py`: unsafe entries refused, plan warnings (removed, newer, links), exact replace,
  links kept, single part, part missing on disk, swap failure rolls back (injected rename), leftover blocks,
  journal written as it goes, mtimes restored.
- `test_interface_backup_undo.py`: undo restores both parts, a part that did not exist is removed, missing safety
  zip refused, undone journal not offered again.
- `test_interface_backup_app.py` (`TuiTestCase`): menu → tool → first-run settings → All flavors → summary → back
  up → result; restore with warnings → confirm → result → undo; Esc paths.
- `test_wtf_*` keep passing after the walker moves to core; `test_docs.py` / `test_events.py` / `test_structure.py`
  keep passing.

No test touches a real install or the network.

## 12. Documentation

README tools-table row, "Tool guides" link, config file under "Your settings", Version History line;
`docs/interface-backup.md` user guide (screens, settings, restore warnings, Undo, troubleshooting) in the style of
the other guides; `docs/architecture.md` config schema, data flow and screens; `docs/events.md` regenerated;
`CLAUDE.md` tool list.

## 13. Out of scope

Restoring into a different flavor, restoring single files or addons, scheduled or automatic backups, encryption,
incremental backups, a cancel button during a run (consistent with the other tools).

## Addendum A: two-pane layout like the other tools (2026-10-04)

The user asked for Interface Backup to follow the Screenshot Organizer's UX pattern (left pane, main tree, bottom
selection line, popups), and for all tools to keep one look and feel. This replaces the summary table and the
separate backup-list screen of §10; logic modules are unchanged.

- **Review screen** (replaces `BackupSummaryScreen`; `TwoPaneFocus` like `ShotReviewScreen`): left pane (`#filters`,
  same width and CSS as the organizer) with sections "Backup folder" (the zip folder) and "Keep" ("newest N per
  flavor" / "all backups"), the action row **Back up** (apply style), **Restore**, **Rescan**, **Undo last restore**
  (revert style), and the NavHint. Right: a tree rooted at the scope label (✓ All flavors, totals) → one node per
  flavor (tick mark; files · size · backups count/last) → read-only children: `Interface` and `WTF` (files · size, or
  "missing" / "link, skipped"), `Links (n)` (expandable, paths), a leftover notice node, scan-warning node, and
  `Backups (n)` (expandable; one node per zip, newest first: date, kind, parts, size; parts read in a worker).
  Ticks are on flavors only (and the root); a backup always holds the flavor's whole Interface + WTF. Keys: Space
  tick, a all, n none, b back up, e restore, r rescan, z undo, f flavors, t tools, q quit, ←/→ panes. Bottom
  `#summary` line: "Selected: N flavors · files · size · L links not backed up" plus a hint "highlight a backup and
  press e to restore". Restore (e or Enter on a backup node) opens the restore screen for the highlighted backup;
  with no backup highlighted it says how to pick one.
- **Restore screen**: the same two-pane shape. Left: "Backup" (date, flavor, kind, size, parts), "Restore" with the
  Interface / WTF checkboxes (`Ka0sCheckbox`, like the cleaner's criteria), buttons **Restore** (apply) and **Back**,
  NavHint. Right: a tree of what the restore changes: "Will be removed (N files)" → grouped folders → files (lazy),
  "Newer now than in the backup (N)" → groups → files, "Links kept (n)", "Links replaced (n)", "Could not be read
  (n)", or "Nothing on disk would be lost". Bottom line: "Restore <parts> of <flavor> from <date> · N removed · M
  newer · needs X, Y free". Confirm and progress stay popups.
- **Result screens**: the organizer's shape: a summary DataTable (Item / Value) above a detail DataTable, buttons in
  a ButtonRow below, NavHint.
- **All tools**: a parity pass renders every screen of the three tools at 80x24 and 140x50 and removes drift (left
  pane width and sections, action-row style and labels, bottom summary line, result-screen shape, footer keys);
  a difference stays only for a stated reason.
