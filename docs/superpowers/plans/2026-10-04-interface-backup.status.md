# Interface Backup — status ledger

Plan: `2026-10-04-interface-backup.md`. Spec: `../specs/2026-10-04-interface-backup-design.md`.
Branch: `feat/interface-backup`. Resume at the first task not marked `done`. Update this file and commit it after
every task; push after each milestone. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| 1 | core helpers: walk_files, is_link, remove_tree_no_follow | done | 440fce5 | wtf_files delegates to walk_files; symlink tests run on WSL; extra tests for on_error and link-as-root |
| 2 | events, settings, catalog | done | e7f75e5 | docs/events.md regenerated now (test_docs needs it); extra tests for event registry, info fields, folder named like a zip |
| 3 | scanner | done | dbd0932 | API as planned; sizes summed without type-ignores; extra tests for chosen parts, unreadable sub-folder, part-as-link warning, broken progress |
| 4 | backup | done | 9609ac3, 59349ac | API as planned; lstat before open (a file turned link is not followed); DOS date clamped both ends; extra tests for links, interrupt, locked file, progress stages, old mtime. Review fix 59349ac: ancestor folders lstat-checked (no reading through an addon folder turned link), O_NOFOLLOW open, vanished/linked parts not claimed in the manifest, linked parts reported, prune never deletes the new zip |
| 5 | open backup + plan restore | done | 7127e9d, 7a2a5b5 | API as planned; stricter entry checks (duplicates over infolist, file/folder clash, files in an unclaimed part); plan_restore raises for a part not in the backup. Review fix: device names and control chars refused only on Windows (backups made on POSIX with an `Aux` character folder restore there), manifest mtimes must be finite and >= 0, `parts` must be a list, `sizes(())` is empty, plan_restore refuses a backup of another flavor. Review fix 2: negative (pre-1970) manifest mtimes accepted (only NaN/inf refused), names compare with per-character `lower()` not `casefold()` (NTFS: `ß` is not `ss`), flavor folder `fullmatch`, plan_restore refuses an unknown or empty part list, `RestorePlan.unreadable` carries the chosen parts' scan errors; 29 tests |
| 6 | run restore + journal | done | cc1c768 | API as planned plus `on_swapped` (journal `replaced` entry written before the old copy is deleted, as the spec orders); Ctrl+C before the swap rolls the part back; part turned link since the plan refused; new `ibackup.restore_failed` event; `log_part` public; 21 new tests |
| 7 | undo | done | c753f94 | API as planned; all guards run before anything changes (also: zip kind pre-restore, leftovers, unknown/duplicate parts, existed part absent from the zip); per-part outcomes rolled_back/failed like restore; journal left undoable when nothing changed; `ZIP_ERRORS` public; 19 tests |
| M1 | push milestone 1 | done (pushed) | 2b66d80 | Milestone 1 review: 15 findings fixed (see decisions, "M1 review") |
| 8 | report helpers | done | 4cbafec | API as planned plus `RestorePlan.unreadable` warnings, missing files in the backup result, notices capped per part; 12 tests |
| 9 | flow, settings, summary, backup screens, registration | done | e6e3ab6 | API as planned with explicit `wow_check`/`disk_usage` flow kwargs; journal lookup and free space moved off the UI thread; own `_checking` flag for the WoW check; 19 TUI tests |
| 10 | restore and undo screens | done | ae15647, ed8ee75 | API as planned; backup list, backup load/scan and every plan built in workers; Undo on the result screen only for a restore that changed a part; 12 new TUI tests. Follow-up ed8ee75: Parts column in the backup list (spec §10), manifests read in a worker |
| M2 | push milestone 2 | done (pushed) | 763a34b | Milestone 2 review: 20 findings fixed (see decisions, "M2 review") |
| 11 | docs, events, final checks | done | 4e3aa0d | Full guide (no images yet: an HTML comment marks where the screenshots go); README, architecture, adding-a-tool, CLAUDE.md; events.md regenerated (22 events, unchanged); 766 tests OK (2 skipped) parallel and serial; ruff clean; reviewed, fixes in 42958c4 |
| M3 | push milestone 3, ask for merge go-ahead | done (pushed; awaiting merge go-ahead) | 42958c4 | final review: 13 findings fixed |
| R1 | redesign: two-pane review screen with flavor ticks and Backups nodes (spec Addendum A) | done | d9d2d31 | `BackupReviewScreen` in `review_screen.py` (renamed from `summary_screen.py`); BackupListScreen removed; tests rewritten for the tree |
| R2 | redesign: two-pane restore screen with warnings tree; result screens in the organizer's shape | todo | | |
| R3 | look-and-feel parity pass across all three tools | todo | | |
| R4 | redesign review, docs (guide, architecture), push | todo | | |

## Decisions taken during the build

- Task 1: `scripts/run_tests.py` takes a single `-k`; the plan's multi-`-k` commands were run one filter at a time.
- Task 1: tests written in the repo style (one import per line, no semicolons, explicit `encoding=`) rather than the
  plan's compressed snippets; `walk_files` and `remove_tree_no_follow` coerce their argument with `Path(...)`.
- Task 2: `docs/events.md` regenerated in Task 2, not Task 11: `gen_event_docs.py` imports every tool package, so
  `tests/test_docs.py` fails as soon as the package exists. Task 11 just regenerates it again.
- Task 2: catalog keeps the plan's API (`NAME`, `new_backup_path(..., kind=)`) rather than the spec's
  `BACKUP_NAME`/`SAFETY_NAME`/`backup_path`/`safety_path`; adds `BACKUP`/`SAFETY` constants, `new_backup_path` rejects
  an unknown kind, `list_backups` stats without following links, `BackupInfo.when` formats the stamp by slicing.
- Task 3: `PartScan.links` holds rel strings (plan) rather than the spec's `list[Path]`; the spec's `PartScan.size: int`
  is `int | None` (unknown when sizes were not read, the WSL default). `scan_flavors` logs at most 20 warnings per
  part plus one "N more not logged" line, and `scan_completed` also records `linked` per part. A file whose
  `stat()` fails during a stats scan is left out of `files` and listed in `errors`.
- Task 4: `write_zip` lstats each file and treats one that is no longer a regular file (now a link or folder) like a
  vanished one: left out and listed in `missing`, never followed. `NotADirectoryError` counts as vanished too.
- Task 4: zip entry dates are clamped to the DOS range at both ends (1980 and 2107), not only the low end, instead
  of the spec's `strict_timestamps=False` (entries are written through `ZipInfo`, which that flag does not cover).
- Task 4: a `RuntimeError` from zipfile (a file that grew past the ZIP64 limit mid-write) becomes a `BackupError`, so
  All flavors still continues. Manifest `links` stay a list of `"<Part>/<rel>"` strings (plan, matches Task 5's
  reader) rather than the spec's `[{"path"}]`.
- Task 4 review: `prune_backups` gained `protect=` (the new zip, which takes one keep slot whatever its stamp);
  `core.fsutil.is_real_dir` added (one lstat, junction-aware). A part that vanished, turned link or lost all its
  files shows in `missing` as a bare `"<Part>"` and is not in the manifest's parts; a part that is a link shows in
  `links` as `"<Part>"`; `backup_skipped` carries `reason` and `links`. Nothing readable at all is a `BackupError`.
- Task 4: events carry a little more than the plan: `backup_failed` has the intended `path`, `backup_created` a
  `missing_sample` (up to 20), `pruned` the `keep` value.
- Task 5: `split_entry` refuses the plan's set (`<>:"|?*`, NUL, trailing dot/space, ...) everywhere and, on
  Windows only (`windows=` parameter, default `os.name == "nt"`), control characters and device names (`CON`,
  `nul.lua`, `COM1`..`LPT9`): on POSIX those are ordinary names that back_up writes (a character called Aux); `open_backup` checks duplicates over `infolist()` (the plan's dict hid exact duplicates), refuses
  a file whose path another entry needs as a folder, a manifest that lists a file twice, and files in a part the
  manifest does not claim. A damaged/encrypted/unsupported zip (`zlib.error`, `NotImplementedError`,
  `RuntimeError`) is a `RestoreError`. `plan_restore` keeps the chosen parts in `PARTS` order. The plan's
  `test_part_missing_from_backup_refused` only checked `parts`; it now asserts `plan_restore` raises. The spec's
  `missing_parts` field is not added: a part the backup lacks is refused instead (plan behaviour).
- Task 5 review: `open_backup` refuses a manifest mtime that is NaN or infinite and a `parts` that is not a list; `BackupContents.sizes(())` is empty (None means all);
  `plan_restore` itself refuses a backup whose flavor folder differs (case ignored) from the scan's.
- Task 5 review 2: negative mtimes are accepted (write_zip stores raw `st_mtime`; a pre-1970 file must not make
  our own backup unopenable). Task 6 must treat an `os.utime` failure (`OSError`, `OverflowError`, `ValueError`) as
  "leave the extraction time", not fail the restore. Case comparisons use `str.lower()` (closer to NTFS's simple
  upcase table than `casefold()`). `RestorePlan.unreadable` (new, not in the plan or spec): the chosen parts'
  `PartScan.errors`, for the restore screen (Tasks 9/10) to warn that unlisted files there are lost too.
- Task 6: `replace_part` takes `on_swapped=` (called after the swap, before `<part>.replaced` is deleted) so the
  journal's `replaced` entry is written first, as spec §7 orders (the plan wrote it after the delete). A failure to
  write it leaves the old copy as a `.replaced` leftover and stops the run (`RestoreStopped`).
- Task 6: the swap rolls back on any `BaseException` (Ctrl+C included) and re-raises it; zip read errors
  (`zlib.error`, `EOFError`, ...) during extraction roll the part back like an `OSError`. Rollback puts the old copy
  back before the links (the plan's version did not handle a failure of `rename(old, live)` itself). A kept link gone
  since the plan is skipped; one whose destination already exists is never replaced (POSIX `rename` would).
- Task 6: `restore()` re-checks after the verify that no chosen part became a link (RestoreError) and
  `replace_part` refuses a part that is not a plain folder. An `os.utime` failure leaves the extraction time.
- Task 6: a journal that cannot record the safety zip deletes that zip and raises RestoreError (nothing changed).
  A `RestoreError` after the journal opened logs the new `ibackup.restore_failed` (error); `docs/events.md`
  regenerated. `restore_completed` is logged at warning when a part failed; a `failed` part (not rolled back
  exactly) logs `part_rolled_back` at error. `_log_part` is public `log_part` (Task 7 imports it).
- Task 6: pruning is skipped when this run's journal would not be among the kept ones (a clock set back), so its
  safety zip is never deleted. Known edge, not addressed: a custom `backup_dir` shared by two WoW folders lets one
  install's prune delete the other's safety zips (the spec's "no remaining journal names it" rule).
- Task 6: `scripts/run_tests.py -k X` reports "Ran 0 tests ... OK" when a test module fails to import; the
  red step was checked with `python3 -m unittest tests.test_interface_backup_restore`.
- Task 7: `undo_restore` refuses (RestoreError, logged as `ibackup.undo_failed` with `refused=True`) before anything
  changes, also when the safety zip is not of kind `pre-restore` or not of the journal's flavor, a `.restoring` /
  `.replaced` leftover is there, a `replaced` entry names an unknown or repeated part or has no boolean `existed`, or
  a part that existed is missing from the safety zip (the plan only checked this per part, mid-run). The verify
  failure is a refusal too.
- Task 7: a failed part is `rolled_back` (left as it was) or `failed`, as in restore (the plan used `failed` for
  every error). The journal is marked undone only when at least one part changed: an undo whose parts were all
  left as they were (WoW locking the folder) stays on offer to retry. Partial success is marked undone (spec).
- Task 7: a part the restore created is skipped when already gone, left alone when it is now a link, and its
  `.replaced` copy is deleted with `remove_tree_no_follow`. A stop part-way logs `ibackup.undo_failed`
  (`stopped=True`), since there is no `undo_stopped` event; `undo_completed` is logged at warning when a part
  failed. `restore._ZIP_ERRORS` became public `ZIP_ERRORS` (undo catches the same zip errors); `log_part` imported
  as Task 6 made it public. No new events, so `docs/events.md` is unchanged.
- Task 7: tests rewrite the journal by parsing its JSON lines and storing paths with `to_stored()` (the plan did a
  raw string replace of the path), and damage the safety zip at the entry's first data byte.
- M1 review: `_prune` never deletes the zip being restored from (`prune_safety(..., protect=)`), and a restore whose
  parts were all rolled back prunes nothing, so a no-op retry cannot push out an older undoable journal.
- M1 review: a link whose path has an ancestor the backup holds as a file goes in `links_removed` (it had no folder
  to stay in, so the part rolled back on every attempt).
- M1 review: `replace_part` calls `on_swapped(existed)` with its own `lexists` result; the journal's `existed` no
  longer comes from the safety zip's parts. A part that is there but that the safety zip does not hold (its files
  vanished while it was written) is left alone (`rolled_back`), since Undo could not put it back.
- M1 review: WTF Cleaner skips (with a scan warning) SavedVariables folders under a linked account, realm,
  character or SavedVariables folder, and `take_snapshot(must_hold=)` refuses the clean (BackupError, nothing
  deleted) when a file to delete is not among the files backed up. Both layers, so a symlinked SV file that the
  scanner still lists is refused too. `test_symlink_escaping_wtf_is_rejected` is unchanged (the guard runs first).
- M1 review: after writing the safety zip, `restore()` opens it with `open_backup` plus the target name rules (what
  Undo will run) and refuses the restore, deleting the zip, if it fails (case twins on a case-sensitive disk). The
  alternative (case rule only on case-insensitive targets) was not taken.
- M1 review: `_extract` remembers the folders it made (one `mkdir` per staging folder, not per file).
- M1 review: a failing `on_swapped` raises `SwapNotRecorded`; `restore()` records the part as `failed` with a reason
  naming the part, the `.replaced` folder and the safety zip, logs it, and stops (`RestoreStopped` carries that text
  as is). No "swapping" intent entry was added to the journal format.
- M1 review: `fsutil._delete_entry` retries with `chmod(S_IWRITE)` only on Windows; on POSIX it re-raises.
- M1 review: safety-zip pruning deletes only the zips that the journals being pruned named and no remaining journal
  names (`journal.safety_zips_named`, read before the prune); `prune_safety(root, names, protect=)` now takes the
  names to delete, not the names to keep. A zip no journal of this folder ever named (another install sharing the
  backup folder) is never touched; a pruned journal that cannot be read keeps its zip.
- M1 review: `split_entry` strips spaces before the extension (`nul .lua`) and refuses `COM¹²³`/`LPT¹²³`;
  `windows_target(path)` is true on Windows and for a WSL `/mnt/<letter>/` path, and `plan_restore`
  (`check_target_names`) then applies the Windows rules to the chosen parts' names.
- M1 review: `write_zip` opens files with `O_NOFOLLOW | O_NONBLOCK` and `fstat`s the descriptor on POSIX (no lstat
  per file; a FIFO is left out without blocking); Windows keeps lstat-then-open. Three backup tests that hooked
  `builtins.open` now hook `os.open` (and `os.fstat` for the grown-file case).
- M1 review: tests added for the `_prune` guards (clock set back, unreadable pruned journal, `journal_pruned`
  payload) and for Undo's stopped path and a created part's `replaced_left`; these covered existing code, so they
  passed before the fix.
- M1 review: the leftover refusal and a journal that cannot be opened log `ibackup.restore_failed` (`restore._refuse`).
- M1 review: `restore` imports `KINDS` from catalog; `undo` imports `Rename` and `case_key` (`_case_key` renamed
  public) from restore. No events changed, so `docs/events.md` is unchanged.
- M1 review: the run was done in one session without sub-workflows (no workflow tool in this agent's tool set).
- Task 8: `report.py` keeps the plan's API. Additions: `restore_warnings` lists `RestorePlan.unreadable` (first
  `limit`, "and N more") and caps `links_removed` the same way; `notices` shows 3 scan warnings per part plus a
  "N more ... warnings in the log" line; `backup_result_rows` appends "N files gone while zipping, left out" to the
  Zip cell when `BackupOutcome.missing` is non-empty; `undo_confirm` shows the flavor's display name (from the
  journal's `flavor` folder) and copes with a journal without parts. `backup_confirm` sums sizes without a
  type-ignore (unknown sizes: no space alert). The plan test's `assertIn("newer", text)` could not pass against the
  plan's own "Newer now ..." text; it asserts "Newer now than in the backup" (spec wording). `LIST_COLUMNS` has no
  Parts column (spec §10 lists one): `BackupInfo` does not know a zip's parts without opening it.
- Task 9: `InterfaceBackupFlow` takes explicit `wow_check=None, disk_usage=shutil.disk_usage` keyword arguments
  (as `WtfCleanerFlow` does) instead of the plan's `**options`; `WowToolsApp.tool_options` passes them unchanged.
- Task 9: nothing slow runs on the UI thread. The scan worker also runs `list_backups` and `latest_undoable`
  (the result is kept in `BackupSummaryScreen.undoable`; the plan called `latest_undoable` in `_refresh_buttons`),
  and the preflight worker also works out the free space (`free_bytes(root, disk_usage)`, module-level; the plan's
  `_free` ran on the UI thread). `run_preflight(check, then, extra=None)` calls `then(running, extra_result)`.
- Task 9: the WoW check uses a screen-local `_checking` flag (as WTF Cleaner does), not `app.busy`: `busy` stays
  reserved for work that changes files (it blocks quit). Buttons and actions are off while scanning, checking or
  busy (`BackupSummaryScreen.idle`); leaving (f/t/q/Esc) is refused only while busy.
- Task 9: Restore (e) on the result screen rescans first and opens Restore when that scan is done
  (`_then_restore`), instead of the plan's `action_rescan(); action_restore()` back to back (the second would be
  ignored while the scan runs). `action_restore`/`action_undo` are placeholders until Task 10 (they log the
  `ui.selection` and notify). A job that raises unexpectedly is notified and the summary rescans.
- Task 9: `action_back_up` reloads the settings before checking the folder (a hand-edited file), and the picker's
  "All flavors" note counts only the install's flavors' backups. The summary focuses its table on mount and the
  Back up button after a scan. The result head says "N of M flavors backed up".
- Task 9: tests go beyond the plan's five: registration, bad counts, cancelled first settings, `s` (WoW folder then
  tool settings), picker notes from a worker, single flavor remembered, summary rows/details/button colours, scan
  and WoW check off the UI thread, WoW-running alert, hand-edited folder refused, busy guard during a backup
  (inside `activity.running`), result → flavors with the new counts, a failing job clearing busy. No menu-count
  test needed a change. `docs/events.md` unchanged (no new events).
- Task 10: nothing slow on the UI thread: `BackupListScreen` lists the folder in a worker (title "Listing the
  backups…" until then), `RestoreScreen` opens the zip and scans in one worker and runs `plan_restore` in another
  each time a box changes (spec §10; the plan ran it on the UI thread). A generation counter drops a plan worked
  out for boxes that changed since; Restore (o) stays off until the current plan is in.
- Task 10: `RestoreScreen` buttons are **Restore (o)** and **Back (b)** with `b` and Esc bound (spec §10; the plan
  had "Back (Esc)" only). The boxes are labelled `Interface` / `WTF`; a part the backup lacks reads "(not in this
  backup)", a linked part "(a link to another folder: restore it by hand)", both unticked and disabled. The flavor
  check compares with `case_key`. The screen shows the zip's path, parts, file count and `created`.
- Task 10: the confirm's date comes from the `BackupInfo` the list returned (kept in a closure), not from a
  `list_backups` call on the UI thread as in the plan. `_restore_confirmed` reloads the settings and re-checks the
  backup folder (`_folder_problem`) before running, as Back up does.
- Task 10: Undo reads the journal inside the preflight worker (the WoW check needs its flavor folder); the plan
  read it and called `latest_undoable` on the UI thread. The summary uses `self.undoable` from its scan.
- Task 10: `RestoreResultScreen` offers Undo (button, `z`, hint) only for a restore with a journal that changed a
  part (`can_undo`); after a restore whose parts were all rolled back, `latest_undoable` would pick an older,
  unrelated restore. Undo from the result screen rescans and then undoes only if the scan still finds that
  result's journal the undoable one (else "That restore can no longer be undone."). Task 9's `_then_restore` flag
  became `_after_scan` (`("restore", None)` or `("undo", journal)`), since the plan's `action_rescan();
  action_undo()` would have been refused while the scan ran.
- Task 10: the result head also names the zip restored from (or put back from, for an undo) and says when a part
  did not finish. The progress screen gets the flavor label (`on_flavor`).
- Task 10: `job_failed`: RestoreError → "Nothing was changed" notice; RestoreStopped → notice (pointing at Undo
  only when a part changed and it was not an undo) plus its `RestoreResultScreen`; anything else as in Task 9.
  Each then rescans.
- Task 10: tests beyond the plan's three: no part ticked, a part missing from the backup, leftover blocks, Back
  and declined confirm change nothing, list/open/scan/plan off the UI thread, WoW-running alert on the restore
  confirm, refused and stopped restores, Undo from the summary starting on No. No menu-count test changed; no new
  events, so `docs/events.md` is unchanged.
- M2 review: the summary's action row is Back up / Restore / Undo (z) / Rescan (the spec's "Undo last restore (z)"
  label and the Flavors/Tools buttons are gone; f/t/Esc, the hint and the footer leave). The texts that named
  "Undo last restore (z)" say "Undo (z)". Task 11's guide must use the new labels.
- M2 review: the summary's `#body` is a `VerticalScroll(can_focus=False)` with PgUp/PgDn bound to scroll it; the
  notices sit under the table, the details under them.
- M2 review: `BackupResultScreen` and `RestoreResultScreen` buttons are `min-width: 0; width: auto; margin-right: 1`
  (all five fit 80 columns; "Other flavor (f)" kept, as in the other tools).
- M2 review: `report.restore_confirm` alerts come from the new `restore_confirm_alerts` (one counted line per kind:
  removed, newer, unreadable, links replaced, low space, naming the largest group); `restore_warnings` stays the
  full grouped list on the RestoreScreen.
- M2 review: `RestoreResultScreen.check_action` hides `z` when `can_undo` is false; `report.ordered_parts` puts
  result rows in PARTS order (an undo processes them in reverse).
- M2 review: `list_rows(infos, names)` maps short names to display names; `friendly_created` formats the
  manifest's `created`, dropped on the RestoreScreen when it equals the zip's stamp. A blocked RestoreScreen
  unticks both boxes; focus goes to Back whenever no box can be ticked.
- M2 review: `_scanned` runs a queued Restore/Undo only when the summary is the screen shown (else a "Press e/z
  on the summary" notice); `action_restore`/`action_undo` return unless the summary is shown.
- M2 review: `BackupSummaryScreen(wow_root=)` (the flow passes the install its flavors came from).
  `wow_folder_changed()` runs on resume and before every scan, backup, restore and undo step: a different
  `cfg.wow_path` notifies "The WoW folder changed: pick the flavor again." and dismisses to the picker (once, when
  shown and not busy). The flow's `_after_flavor` re-opens the picker for a choice made on the old install's
  list, and `_settings_done` drops the "Press r" notice when the WoW folder changed. WTF Cleaner and Screenshot
  Organizer have the same gap (not changed here).
- M2 review: the picker-notes guard is `picker not in app.screen_stack` (a covered picker still gets its notes);
  the same fix in Screenshot Organizer, whose "no Screenshots folder anywhere" dismiss still needs the picker
  shown.
- M2 review: settings `Label`s are `width: 1fr; height: auto` in all three tools (they wrap at 80 columns);
  Interface Backup's settings show "Zips go to: <resolved folder>" under the folder input, updated as you type.
- M2 review: README intro and FAQ reworded for three tools (Dry run named as a WTF Cleaner / Screenshot Organizer
  feature), done now rather than in Task 11 Step 3.
- M2 review: tests at 80x24 (summary and result buttons, notices, restore confirm, settings labels in all three
  tools) and for the paths the review named: notifications of refused/failed jobs, Restore (e) from the backup
  result, an Undo no longer possible, an unreadable journal, Esc on the summary, restore screen and both result
  screens, a stopped restore with a journal (with and without a replaced part). The tests-docs findings covered
  existing code, so those tests passed before the fix.
- Parts column (ed8ee75): `LIST_COLUMNS` is Date / Flavor / Kind / Parts / Size, as spec §10 lists (Task 8 had left
  Parts out). `catalog.read_parts(path)` reads only the manifest entry (no entry checks, no verify; never raises)
  and returns the claimed parts in PARTS order, None when unreadable. `BackupListScreen` lists the rows first
  (Parts "…"), then a second worker reads each zip and fills the cell (`report.parts_cell`: "Interface, WTF",
  "WTF", "?" for an unreadable zip, which stays listed); it checks `is_cancelled` and the update is skipped once
  the screen has left. Columns are keyed by label. Flavor stays the display name (M2 fix).
- Task 11: the guide has no image links (no Interface Backup screenshots yet); `<!-- screenshots: summary, restore
  screen, result -->` marks the place. It uses the M2 labels (Undo (z), no Flavors/Tools buttons on the summary).
- Task 11: `docs/events.md` lists 22 `ibackup.*` events (the plan said 21; Task 6 added `restore_failed`); the
  regeneration changed nothing.
- Task 11: README Version History gets an "Unreleased" row (no `__version__` bump); the 1.0.0 row's "two tools"
  is left as it describes that version. README FAQ/navigation wording now covers three tools. The Tests badge
  (405) is not updated here (left to the release bump).
- Task 11: no `git push` in this run (the orchestrator forbids it); milestone 3 push and the merge go-ahead stay
  with the user. `./wow-tools.sh` is interactive, so the TUI tests are the end-to-end check.
- Final review (42958c4): a restore journals each link it removes (`{"action": "link_removed", "part", "rel",
  "target", "junction"}`, read with the new `fsutil.read_link` just before the swap, written in `on_swapped`
  before the `replaced` entry) and Undo makes it again after swapping the part back (`fsutil.make_link`: a
  junction on Windows when it was one, else a symlink), where nothing is now; one it cannot make turns the part
  `failed`, the reason naming the link and its target. A damaged `link_removed` entry (unknown part, unsafe rel,
  no target) refuses the Undo. The safety zip still holds no links.
- Final review: `action_back_up` passes every flavor shown to `back_up_all`, so a flavor with no folders or only
  links comes back **Skipped** with its reason (spec §6.1); the check for "Nothing to back up" and the button's
  state still use `has_data`. `backup.skip_reason` is shared by `back_up` and `report.backup_confirm`, whose body
  gains a "Skipped: <flavor> (<reason>)." line. `test_back_up_all_flavors` now expects 4 result rows (Retail PTR
  Skipped).
- Final review: `RestorePlan.current_bytes` (what the chosen parts hold now; None without sizes) and
  `restore_confirm(..., backup_free=)`: the restore preflight also works out `free_bytes(root)`, and the confirm
  alerts when the safety zip (taken as at most the folders' size) may not fit on the backup drive. Same drive as
  WoW is not summed with `bytes_needed` (each drive is checked on its own).
- Final review: `summary_screen.ThrottledProgress` forwards a job's progress to the UI thread only on a stage
  change, a report with no count or at a stage's end, or once per `PROGRESS_INTERVAL` (0.1 s); `on_flavor` resets
  it. Logic modules unchanged.
- Final review: `RestoreResult.swapped` (a part `restored` or `replaced_left`, i.e. recorded by the journal);
  `RestoreResultScreen.can_undo` and `job_failed`'s "Undo (z) puts back what was replaced" hint use it, so a swap
  the journal could not record (SwapNotRecorded, `failed`) offers no Undo.
- Final review: TUI tests for the WoW-running alert on the Undo confirm (warn and allow) and for the Undo check
  using the journal's flavor; they cover existing code, so they passed before.
- Final review: `ibackup.part_rolled_back` description covers kind `failed` (at error); `docs/events.md`
  regenerated. Scan notices say "N more <part> warnings (the log lists the first 20)".
- Final review: guide fixes: Undo works on the most recent restore that changed a folder (an all-rolled-back one
  is passed over), the greyed-out Undo row, links made again by Undo, Skipped flavors on the confirm and results,
  Parts values ("Interface" and "none" added), "up to 20" in the log, the safety-backup space alert on the
  restore confirm. architecture.md updated to match.
- Final review: `docs/adding-a-tool.md` step 6, CLAUDE.md and the `RENAMED_TOOLS` comment say a rename does not
  move a `<TOOL_NAME>` folder inside a user-chosen folder (Interface Backup's `<backup_dir>/interface-backup`);
  the code was not changed.
- R1: `summary_screen.py` is now `review_screen.py` (`BackupReviewScreen`, `BackupTree`), named like the other
  tools' review screens. Every flavor can be ticked, including one with nothing to back up: ticked, it comes back
  Skipped with its reason on the confirm and the result (as before); with only such flavors ticked, Back up says
  "Nothing to back up". Nothing ticked: "Nothing is selected.". Ticks are kept across rescans (flavor folders are
  stable), unlike the organizer, which clears them because its items change.
- R1: flavor nodes start expanded (as in the organizer); `Links (n)`, `Scan warnings (n)` and `Backups (n)` load
  their children on expand. A Backups node lists the flavor's backups and safety zips, newest first; their parts
  are read by a worker (`read_parts`) started on expand, "…" until read, "?" when unreadable. A flavor without
  backups shows a leaf "Backups (0) none yet". The scan lists only the chosen flavors' zips.
- R1: Restore (e, the button, or Enter on a backup node) restores the highlighted backup; with none highlighted
  it notifies "Open a flavor's Backups in the tree, highlight a backup and press e (or Enter) ...". Restore (e)
  on the backup result rescans, then expands the Backups nodes and puts the cursor on the newest backup (the old
  flow opened the list), with a "Highlight a backup ..." notice. `ui.selection` for restore carries the zip name.
- R1: the old `#notices` lines live in the tree (leftover node, links node, warnings node) and in short form on
  the `#summary` line ("⚠ Restore blocked for X", "⚠ N scan warnings"); "Checking for running programs…" shows
  on the `#summary` line while the preflight runs. The old `#details` (backup folder, keep, journals folder) is
  the left pane's "Backup folder" and "Keep" sections; the journals folder is no longer shown.
- R1: report.py: `summary_rows`, `SUMMARY_COLUMNS`, `list_rows`, `LIST_COLUMNS`, `notices`, `NOTICE_ERRORS`
  removed (no caller left); added `part_text`, `flavor_text`, `leftover_text`, `warnings_text`, `held_text`,
  `selection_text`, `backup_text` (tested). No other logic module changed. Esc on the review still goes to the
  flavor picker (f), as before. docs/architecture.md and the guide still describe the summary: R4.
