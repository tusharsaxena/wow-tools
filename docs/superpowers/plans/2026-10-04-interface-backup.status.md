# Interface Backup — status ledger

Plan: `2026-10-04-interface-backup.md`. Spec: `../specs/2026-10-04-interface-backup-design.md`.
Branch: `feat/interface-backup`. Resume at the first task not marked `done`. Update this file and commit it after
every task; push after each milestone. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| 1 | core helpers: walk_files, is_link, remove_tree_no_follow | done | 440fce5 | wtf_files delegates to walk_files; symlink tests run on WSL; extra tests for on_error and link-as-root |
| 2 | events, settings, catalog | done | e7f75e5 | docs/events.md regenerated now (test_docs needs it); extra tests for event registry, info fields, folder named like a zip |
| 3 | scanner | done | dbd0932 | API as planned; sizes summed without type-ignores; extra tests for chosen parts, unreadable sub-folder, part-as-link warning, broken progress |
| 4 | backup | done | 9609ac3 | API as planned; lstat before open (a file turned link is not followed); DOS date clamped both ends; extra tests for links, interrupt, locked file, progress stages, old mtime |
| 5 | open backup + plan restore | todo | | |
| 6 | run restore + journal | todo | | |
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
- Task 4: events carry a little more than the plan: `backup_failed` has the intended `path`, `backup_created` a
  `missing_sample` (up to 20), `pruned` the `keep` value.
