# Interface Backup internals

How Interface Backup (`wowtools/tools/interface_backup/`) scans, backs up, restores and undoes, and how its screens are built.

User guide: [interface-backup.md](../interface-backup.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools).

## Contents

- [Data flow](#data-flow)
  - [Scan](#scan)
  - [Backup](#backup)
  - [Open and plan](#open-and-plan)
  - [Restore](#restore)
  - [Journal and Undo](#journal-and-undo)
- [Screens](#screens)

## Data flow

    scan_flavors(flavors, with_stats=CHEAP_STATS, progress=None, parallelism=1) → [FlavorScan(flavor, parts{Interface, WTF: PartScan}, leftovers)]
    back_up_all(scans, root, keep, progress=None, on_flavor=None, on_flavor_done=None, parallelism=1) → [BackupOutcome(flavor, kind, path, files, bytes_in, bytes_zip, links, missing, reason, pruned)]
    open_backup(zip) → BackupContents(kind, flavor_short, flavor_folder, created, parts, files, links)
    plan_restore(contents, scan_flavor(flavor, with_stats=True), parts, disk_usage) → RestorePlan(removed, newer, links_kept, links_removed, unreadable, bytes_needed, free_bytes, leftovers, current_bytes)
    restore(plan, root, journal_dir, keep_journals, progress=None) → RestoreResult(flavor, backup, parts[PartOutcome], safety_zip, journal_path)
    undo_restore(journal_path, wow_root, root, progress=None) → RestoreResult(undo=True)

Modules in `tools/interface_backup/` (all UI-free except `app.py`, `review_screen.py` and `restore_screen.py`):
`settings` (`BackupSettings`, `resolve_backup_root` = `<backup_dir or WoW/wow-tools>/interface-backup`,
`core.install.validate_backup_dir` checks the folder), `journal` (`resolve_journal_dir` = `<WoW>/wow-tools/interface-backup/journal`), `catalog` (names
`backup-<flavor>-<stamp>[-N].zip` and `pre-restore-<flavor>-<stamp>[-N].zip` in `zips_dir(root)` =
`<root>/backup` (L16), `list_backups` newest first, `read_parts` (the manifest's parts only, never raises),
`prune_backups`, `prune_safety`, `move_old_zips`, `zip_now_at`), `scanner`, `backup`,
`restore`, `undo`, `journal` and `report` (labels, stage titles, rows and dialog texts). `<flavor>` is the flavor's
short name.

### The backup folder

`<root>` (`resolve_backup_root`) holds `backup/` (every zip: backups and pre-restore safety zips) next to
`journal/` when the backup folder is the default. Before L16 the zips sat in `<root>` itself. The review's scan
worker (never the UI thread, STD-7.20) calls `move_old_zips(root)` before `list_backups`: each
`backup-*.zip` / `pre-restore-*.zip` in `<root>` is moved into `backup/` with `rename_no_replace` (STD-5.17),
inside `activity.running()` (STD-5.19: `suite.run()`'s `wait_idle()` waits for it; nothing to move enters
nothing). A name `backup/` already has is left in place (`taken`), and so is a move that fails (`failed`); both
are tried again on every scan and logged in one `ibackup.zips_moved` (at warning when anything was left). A name
left in place is logged the first time only (a per-session set of folder and name), so a later scan logs nothing
until a zip moves or another is left; nothing is logged when there was nothing to move. A `backup` that is a
link to a folder is used, as `new_backup_path` and the zip writers use it; one that is not a folder leaves every
zip in place (`failed`).
Until a zip is moved, `list_backups`, `prune_backups` and `prune_safety` see it in `<root>` too, and a
pre-restore zip there is never pruned by `prune_backups`. `new_backup_path` picks a name free in both places
(`free_name(..., also=(root,))`), so a later move never clashes with a new zip. A journal written before the move
names `<root>/pre-restore-….zip`; `undo_restore` accepts a safety zip in either place and `zip_now_at` finds it in
`backup/` by file name once it was moved.

### Scan

`scan_part` walks `<flavor>/<part>` with `core.backup.walk_files`: directory listings only, never
`resolve()`, never following a link. A link inside a part goes to `PartScan.links` (a `<Part>/<rel>` string,
never zipped); a part that is itself a link is `linked` and is neither backed up nor restored. An unreadable
sub-folder is a `PartScan.errors` line (at most 20 logged per part as `ibackup.scan_warning`). `leftovers` are
`<part>.restoring` / `<part>.replaced` beside the parts. `CHEAP_STATS` is `os.name == "nt"`: `DirEntry.stat()` is
free on Windows but a round trip per file over WSL drvfs, so elsewhere the review's scan leaves sizes `None` (counts
only, no space alert on the backup confirm). The restore screen always scans with stats (it needs mtimes for
`newer`). `scan_flavors` reads up to `parallelism` flavors at once (read-only, independent; scans in flavor order,
each flavor's events logged by its own thread); an unexpected error keeps the flavors not started yet from
starting and is raised once the running ones ended. The scan bar has no total, and each report names its flavor.

### Backup

Code: `backup.py`. No journal: nothing in the game folders changes. `write_zip` writes `<Part>/<rel>`
entries plus `manifest.json` (`version`, `kind` backup | pre-restore, `flavor`, `flavor_folder`, `created`,
`suite_version`, `parts`, `parts_existing`, `files[{path, size, mtime}]`, `links`) to `<name>.partial`, runs
`verify_backup`, `fsync_file` (F-012), then `rename_no_replace`; any failure (Ctrl+C included) removes the `.partial` and is a
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

### Open and plan

Code: `restore.py`. `open_backup` reads only the manifest and the entry list: every entry name must
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

### Restore

`restore()` refuses (RestoreError, nothing changed, `ibackup.restore_failed`) on a leftover, a journal
that cannot be opened, a backup that does not verify, a part that turned into a link, or a safety backup that
fails or would not open for Undo (`_check_safety`, which then deletes it). In order: journal header (`flavor`,
`flavor_path`, `backup`, `parts`), verify, safety zip `pre-restore-<flavor>-<stamp>.zip` of the chosen parts as
they are (`write_zip(kind="pre-restore")`), journal `{"action": "safety_backup", "zip", "parts_existing"}`, then
per part `replace_part`: extract to `<part>.restoring` (exclusive create, manifest mtimes; an `os.utime` failure
keeps the extraction time), move the kept links into it, rename `<part>` → `<part>.replaced` and `<part>.restoring`
→ `<part>`, `on_swapped(existed)` writes a `{"action": "link_removed", "part", "rel", "target", "junction"}`
per link the swap removed (read with `read_link` just before; a zip never holds links) and then
`{"action": "replaced", "part", "existed"}`, then
`remove_tree_no_follow(<part>.replaced)` (a failure is `replaced_left`). Every rename of the swap, its link moves
and its rollback goes through `rename_no_replace` (STD-5.17; `restore`, `replace_part` and Undo's `undo_restore`
default `rename=` to it), which refuses a target that already exists. The refusal is atomic only where the item
can be hard-linked (a kept link on most POSIX file systems); a folder, and on WSL's drvfs a junction or a
relative symlink, takes its best-effort fallback (a last `lexists` check, then `os.rename`), so something that
appears in that last gap can still be replaced. An error before or during the swap
(including Ctrl+C) rolls the part back exactly (`rolled_back`; `failed` when the rollback itself fails) and the
next part goes on. A part present on disk that the safety zip does not hold is left alone. A journal entry that
cannot be written stops the run (`RestoreStopped`, the reason naming the `.replaced` folder and the safety zip).
After a restore that changed a part, `_prune` keeps `keep_journals` journals and deletes only the safety zips
that the pruned journals named and no kept journal names (never the zip restored from, never one no journal of
this WoW folder named). Stages `verify`, `safety`, `safety_verify`, `extract`, `swap`, `cleanup`.

### Journal and Undo

Code: `journal.py`, `undo.py`. `<WoW>/wow-tools/interface-backup/journal/journal-<stamp>.jsonl`:

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
target, the safety zip in `<root>/backup` or `<root>` (an older run's; `zip_now_at` finds it in `backup/` by name
once moved), a regular file, of kind pre-restore and the same flavor,
holding every part that existed, no leftovers, and it verifies. Then, newest entry first, a part that existed is
replaced from the safety zip with `replace_part` (its links kept; no further safety backup), then each link the
restore removed from it is made again where nothing is now (`make_link`; one that cannot be made turns the part
`failed`, its reason naming the link and target), and a part the restore created is renamed to `<part>.replaced`
and deleted without following links. The journal is marked undone
unless every part was left as it was (then Undo can be tried again).

## Screens

`app.py` holds `InterfaceBackupFlow` (`FLOW`: `require_install` → `BackupSettingsScreen` on the tool's first open
→ `FlavorScreen(include_all=True, last=last_flavor_choice)`, whose notes (`report.picker_note`: "N backups, last
…" / "no backups yet") a worker fills from `list_backups` → `BackupReviewScreen`) and `BackupSettingsScreen`
(backup folder with a live "Zips go to:" line; `validate_backup_dir` errors inline; retention is the shared
`[general]` setting). `s` opens the shared WoW-folder settings, then this tool's. If the WoW folder changes, the review (or the
picker's choice) goes back to the flavor picker. The screens follow the Screenshot Organizer's shape (left pane,
tree, bottom `#summary` line, popups for confirm and progress) and its shared CSS. `review_screen.py` holds:

- `BackupReviewScreen(cfg, tool_cfg, flavors, scope_label, *, wow_check, disk_usage, wow_root)`: `TreeFilter`
  (`ui/tree_filter.py`) and `ReviewBase` (`ui/review.py`), `two_pane_css`. Left pane `#filters`: "Backup folder", "Keep"
  ("newest N per flavor" / "all backups"), the `FilterBar` (filter box and **Filter** button) (`/`; the pane's first control), the action row **Back up** (create), **Restore** (navigate: it opens the restore screen), **Rescan**, **Undo last
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
  anything in the flavor matches, and `all_tick_keys` is the flavors with data. `#summary` (a `SummaryBar`) is
  `selection_text` plus the highlighted backup in full (`backup_detail`) or how to pick one, then the filter's
  hidden-ticks line and "Restore blocked for …"; scan warnings are counted on its **Warnings** button (`!`,
  `refresh_warnings`). Keys Space, `a`, `n`, `/`, `x`, `c`, `b`, `e` (or Enter on a backup node: restores the
  highlighted backup; with none highlighted a notice says how), `r`, `z`, `!` (the warnings view); `f`/Esc, `t`, `q` leave. Back up,
  restore and undo each run the running-WoW check (and the backup drive's free space, for a backup and for a
  restore's safety backup; the undo also reads its journal there) in a worker, with "Checking for running
  programs…" on `#summary`, then a `ConfirmScreen` (Yes red for Back up when `keep_backups` is above 0, since the run prunes older backups,
  green when it keeps all; red for Restore and Undo); the job runs
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
  when a leftover, another flavor's backup or an unreadable zip blocks it), the `FilterBar` (filter box and **Filter** button), **Restore** (overwrite, `o`) and **Back**
  (the shared `RiskBanner` tops this pane, D37)
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
