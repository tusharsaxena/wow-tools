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
| 7 | undo | todo | | |
| M1 | push milestone 1 | todo | | |
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
