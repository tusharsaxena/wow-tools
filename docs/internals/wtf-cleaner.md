# WTF Cleaner internals

How the WTF Cleaner (`wowtools/tools/wtf_cleaner/`) scans, proposes, cleans and undoes, and how its screens are built.

User guide: [wtf-cleaner.md](../wtf-cleaner.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools).

## Contents

- [Data flow](#data-flow)
  - [Run journal and Undo last clean](#run-journal-and-undo-last-clean)
  - [Safety snapshot](#safety-snapshot)
  - [Progress callbacks](#progress-callbacks)
- [Screens](#screens)

## Data flow

    scan(flavor, account=None, progress=None) → ScanResult(installed, enabled, groups[SVGroup[SVFile]])
    evaluate(scan, Criteria, blacklist=()) → Proposal(items[ProposalItem(group, files, reasons)], blacklisted[ProposalItem(…, blacklisted=True)])
    TUI selection → execute(items, flavor, dry_run, backup, backup_dir, progress=None, journal=None)
                      → CleanResult(outcomes, backup_path, snapshot_path, restored, journal_path)
    undo_clean(journal_path, wow_root, progress=None) → UndoResult(outcomes[UndoOutcome])

`evaluate(blacklist=pairs)` (`[wtf_cleaner] blacklist`, `core/blacklist.py`) holds a blacklisted group (its flavor and
addon matched by `is_blacklisted`) aside in `Proposal.blacklisted`, as what the criteria would propose of it, each
`ProposalItem.blacklisted=True`; `Proposal.items` never holds one, so the totals, `by_reason`,
`criterion_counts(blacklist=)`, the `proposal.item` events, the selection, the confirm, a clean and a dry run leave
it out. `proposal.built` counts them (`blacklisted`). A blacklisted group no criterion matches is in neither list.

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
file right after it is deleted. `_delete_one` re-checks size and mtime once more right before each delete (STD-5.7),
so a file WoW rewrote while the backups were written is skipped (`sv.skipped`, `changed`) and kept. A dry run writes the backup (as `cleaned/dryrun-<flavor>-<account>-<stamp>.zip`) and deletes nothing; it takes
no snapshot, writes no journal, and then prunes the flavor's dry-run zips to the newest `keep_backups`
(`prune_dry_run_zips`). Real `cleaned-*.zip` files are pruned only when `[wtf_cleaner] keep_cleaned` is above 0: a
real clean that deleted something then keeps the flavor's newest `keep_cleaned` (`prune_cleaned_zips`, any account,
newest by the stamp in the name, one `os.scandir` and no stat per file; the zip this run wrote is always kept and
counts as one; `CleanResult.cleaned_pruned`, event `backup.cleaned_pruned`, shown on the result's "Cleaned files
zip" row). A dry run never prunes them. Undo (always the latest clean) is unaffected, since that clean's zip is
always kept; a pruned older clean can only be restored by hand from its WTF backup while one is kept.

### Run journal and Undo last clean

`tools/wtf_cleaner/journal.py` and `undo.py`, both UI-free, built on `core/journal.py`. A real clean (the review screen passes
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
is extracted, exclusive create and `fsync`ed (F-012), from the cleaned-files zip (by its name, which is `rel`) or, when there is no zip,
the zip is gone or lacks it, or its size differs, from the WTF backup by `rel`. The written size must match the
entry (else the partial file is removed and the entry fails) and the file's mtime is put back. Each zip is opened
once. Afterwards the journal is marked undone, unless nothing was restored and something failed (a source
that is missing for now, such as an unplugged backup drive), so Undo can be tried again (`clean.undo_started`, `clean.undo_restored`, `clean.undo_skipped`,
`clean.undo_failed`, `clean.undo_completed`).

### Safety snapshot

`tools/wtf_cleaner/safety.py`, UI-free: thin wrappers over `core/snapshot.py` and `core/svfiles.py` (names, messages and file names unchanged). `take_snapshot()` zips the whole `<flavor>/WTF` folder to `backup/backup-<flavor>-<stamp>.zip`
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
- `clear_marker()` retries (`core/marker.clear_marker`) and returns False when another program still holds the
  marker; `cleaner._clear_marker` then logs `clean.marker_left` (warning, with the `stage`), and a clean that
  finished sets `CleanResult.marker_left`, shown as a "Crash marker" summary row. **Dismiss** on `RecoveryScreen`
  does the same (stage `dismiss`) and the review shows a "Marker not removed" notice: while the marker exists every
  real clean is refused.
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

## Screens

The WTF Cleaner's own screens live in `tools/wtf_cleaner/`. `app.py` holds `WtfCleanerFlow` (`FLOW`) and
`CleanerSettingsScreen` (in screen order: max age, backup folder, the five criteria, zip the files before deleting
on/off, cleaned-files zips to keep, show the risk warning). The flow shows `FlavorScreen` with `include_all=True`
and `last=last_flavor_choice`; All flavors skips the account screen. Before the review it asks
`ToolFlow.ask_disclaimer` (the shared `ui.disclaimer.DisclaimerScreen` with `report.DISCLAIMER`, once per app
session, L4; `clean.disclaimer_accepted` / `_declined`; Back returns to the flavor
picker; never with `skip_risk_warning`, which its "Don't show this warning again" box and the settings form's box
set, `clean.risk_warning_changed`, L8). `review_screen.py` holds:

- `ReviewScreen(cfg, tool_cfg, flavors, *, account, wow_check, locker_check)`: a `TreeFilter` and `ReviewBase`; tree,
  the shared `RiskBanner` (D37) above the criteria, the `FilterBar` (filter box and **Filter** button) under the max age (it narrows the proposal on top of the criteria: the tree is built
  from `ModelNode`s matched on flavor, account, owner, addon and file names; an addon opens when a file in it
  matches; the summary and the confirm's alerts say how many ticked files it hides), the Clean /
  Dry run / Rescan buttons and **Undo last clean** (violet, key `z`, last in the same row; disabled when nothing is
  undoable, while scanning and while busy; its confirm (Yes red) names the clean's time, flavors and file
  count). What Undo offers (`self.undoable`) is looked up by the scan, clean and undo workers, never on the UI
  thread, and the crash marker in the backup folder is read in its own worker on mount, whose answer opens
  `RecoveryScreen` once the review is the screen shown and idle (L6: the scan box shows before any disk access).
  `flavors` is one `Flavor` (root = the flavor, accounts below) or a list (root = All
  flavors, a node per flavor, a "not scanned" leaf for a flavor whose scan failed). `wow_check` covers every
  flavor (`core.process.wow_check_for(list)` lists the processes once). Blacklisted items (`Proposal.blacklisted`)
  stay in the tree, greyed and tagged "blacklisted", with no tick keys (`_paths` gives none, so Space / `a` / `n`
  skip them) and the shared blacklist mark (`ui.review.blacklisted_mark()`, `⊘`, dim, L15) in place of a tick mark;
  group rows count and mark the cleanable items only. `b` is the shared
  `BlacklistAction` (`BLACKLIST_BINDING`, not in the footer: the left-pane hint names it): `blacklist_target` maps an
  item or file row to (its flavor folder, from `_item_flavor`, rebuilt per rebuild, so All flavors toggles per flavor;
  the addon), `toggle_blacklist` reloads the settings, applies `toggle_pair` over every flavor folder of the install,
  saves (`source="review"`) and logs `blacklist.changed`, and `blacklist_changed()` refreshes the criterion counts,
  then rebuilds. The bottom line is a `SummaryBar` (`WarningsHost`: the scans' `ScanWarning`s, under the flavor,
  paths inside the flavor folder);
- the shared `ConfirmScreen` (`wowtools.ui.dialogs`): Yes red for a real clean and cyan for a dry run; lists each flavor's counts;
- `CleanProgressScreen`, a `ProgressScreen` (ids `clean-*`): one row, taken by each flavor in turn (its label
  names the flavor; `execute_flavors`' `on_flavor` is `start_unit`); also shown for an undo;
- `RecoveryScreen` (a `ChoiceScreen`): Dismiss or Remind me next time.

`result_screen.py` holds `ResultScreen(result, flavor=None)`, a `ResultBase`: a summary table plus a per-file `DataTable`. With a
`MultiCleanResult` it shows Done / Stopped / Not started rows after a stop, one block of summary rows per finished
flavor, and a Flavor column (`report.MULTI_RESULT_COLUMNS`). Zips are named inside the backup folder (`cleaned/<name>`, `backup/<name>`), which has a "Backup folder" row of its own. A real clean adds a "Run journal" row: inside the backup folder when it is there (the default one holds
`journal/`), else its name after a "Journal folder" row, so both fit at 120x30 for the default install path; it
carries the Undo note (`UNDO_NOTE`). Several flavors share one journal: `multi_summary_rows` names it once, above
the flavor blocks, which leave it out (`summary_rows(result, journal=False)`, L14). That row comes before any file
is named, so its note says what Undo restores (`MULTI_UNDO_NOTE`). The per-file table puts Reasons before
Size and File, so why each file goes shows at 120x30. With an
`UndoResult` it is titled "undo result" and shows `report.undo_summary_rows` and `report.UNDO_COLUMNS`.
