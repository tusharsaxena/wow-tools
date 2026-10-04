# Interface Backup — status ledger

Plan: `2026-10-04-interface-backup.md`. Spec: `../specs/2026-10-04-interface-backup-design.md`.
Branch: `feat/interface-backup`. Resume at the first task not marked `done`. Update this file and commit it after
every task; push after each milestone. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| 1 | core helpers: walk_files, is_link, remove_tree_no_follow | done | 440fce5 | wtf_files delegates to walk_files; symlink tests run on WSL; extra tests for on_error and link-as-root |
| 2 | events, settings, catalog | done | e7f75e5 | docs/events.md regenerated now (test_docs needs it); extra tests for event registry, info fields, folder named like a zip |
| 3 | scanner | todo | | |
| 4 | backup | todo | | |
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
