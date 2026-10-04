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
| M1 | push milestone 1 | reviewed, fixes in 2b66d80 | 2b66d80 | Milestone 1 review: 15 findings fixed (see decisions, "M1 review") |
| 8 | report helpers | todo | | |
| 9 | flow, settings, summary, backup screens, registration | todo | | |
| 10 | restore and undo screens | todo | | |
| M2 | push milestone 2 | todo | | |
| 11 | docs, events, final checks | todo | | |
| M3 | push milestone 3, ask for merge go-ahead | todo | | |

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
