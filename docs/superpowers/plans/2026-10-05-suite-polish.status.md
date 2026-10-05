# Suite polish: status ledger

Plan: `2026-10-05-suite-polish.md`. Spec: `../specs/2026-10-05-suite-polish-design.md`.
Branch: `feat/suite-polish`. Resume at the first task not marked `done`. Update this file and commit it after every
task; push after every milestone. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| T0.1 | branch, spec, plan, ledger | done | | |
| T0.2 | dead code, core-no-textual test | done | 7f7a279 | InstallError, SNAPSHOT_NAME + `import re`, ConfirmScreen re-export gone; pinned; core-no-textual AST test. 1056 tests OK (2 skipped) |
| T0.3 | version 0.1.0, CHANGELOG.md | done | 76cc51d | `__version__` 0.1.0, README badge, CHANGELOG.md with the 0.1.0 entry, README Version History is a pointer; test pins badge + changelog heading. 1058 tests OK (2 skipped) |
| T1.1 | core helpers | done | 7b7ff92 | New `core/text.py` (plural, human_size), `core/progress.py` (ThrottledProgress + lock, PROGRESS_INTERVAL), `core/marker.py`, `core/undo.py` (UndoResultBase, statuses, safe_destination); `install.flavor_name` / `validate_backup_dir`; `journal.ToolJournals` + `prune_journals(event=)`. Tool copies deleted, pinned in test_structure. 1069 tests OK (2 skipped) |
| T1.2 | review-screen base in ui | todo | | |
| T1.3 | result/choice/settings/flow helpers | todo | | |
| T1.4 | shared-library policy docs | todo | | |
| T2.1 | action-kind colours | todo | | |
| T2.2 | confirm default Yes + safeguards | todo | | |
| T3.1 | BrandBar fix, Ace3 u | todo | | |
| T3.2 | version under banner, terms, menu tests | todo | | |
| T3.3 | changelog parser + screen + release check | todo | | |
| T4.1 | shared tree filter | todo | | |
| T4.2 | filter in every tree screen | todo | | |
| T5.1 | parallelism setting + runner + thread safety | todo | | |
| T5.2 | fixed-size progress popup | todo | | |
| T5.3 | apply parallel runs | todo | | |
| T6.1 | docs sync | todo | | |
| T6.2 | review, fixes, push | todo | | |

## Decisions taken during the build

- **T0.2** The ConfirmScreen re-export is pinned as `"ConfirmScreen" not in review_screen.__all__`, not `not hasattr`: review_screen still imports ConfirmScreen from `ui.dialogs` for its own confirms, so the name stays a module attribute. Nothing outside frozen historical plans imported it from there. `ruff check` panics on a stale `.ruff_cache` in this checkout; `ruff check --no-cache .` is clean.
- **T0.2** review: 2 findings, 2 fixed, 0 rejected: core-no-textual test now also flags `wowtools.ui`/`wowtools.tools` and relative imports, plus a fresh-interpreter check that importing every core module loads no textual or wowtools.ui (1057 tests OK); stale "still importable from here for one release" ConfirmScreen line dropped from docs/architecture.md.
- **T0.3** The 0.1.0 entry has only an `### Added` section (grouped per tool, plus "The app"): nothing was released before it, so the old "Unreleased" row's changes (global retention, `x`/`c`, Clean on `w`, one row per checkbox) are written as features of 0.1.0, not "Changed". The `"1.0.0"` strings left in `tests/test_ace_*.py` are arbitrary `suite_version` journal fixture data, not version pins, so they stay. The new `test_version_badge_and_changelog_match_the_version` (test_docs.py) is a regex stand-in for the "`__version__` has an entry" pin; T3.3 can move it onto `core/changelog.py`. The stale README Tests badge (1053) is left for T6.1 docs sync.
- **T0.3** review: 2 findings, 2 fixed, 0 rejected: docs/adding-a-tool.md step 5 now says to add a CHANGELOG.md bullet instead of a README "Version history" line; the CHANGELOG Interface Backup bullet no longer hard-codes 10 backups and points at the global retention setting.
- **T1.1** `flavor_name` lives in `core/install.py` (next to `FLAVOR_NAMES`; `Flavor.display_name` calls it), not `core/text.py`: text importing install and install using text would be a cycle. Ace's `FLAVOR_NAMES.get(...)` version had the same body as `Flavor.display_name`, so the names the user sees do not change.
- **T1.1** One size formatter, `core.text.human_size` (Interface Backup's: None → "—", up to TB). The WTF Cleaner's `format_size` gave the same text below 1024 GB, so its screens do not change.
- **T1.1** Journal helpers are a `ToolJournals(tool, reader, pruned_event)` per tool (`JOURNALS` in its `journal.py`), and the module names `resolve_journal_dir` / `latest_undoable` / `prune_journals` stay as its bound methods, so callers and ~60 test call sites keep their imports. `resolve_journal_dir` moved from the tools' `settings.py` to their `journal.py`; the WTF Cleaner's `clean_journal_dir` is now `resolve_journal_dir`. Interface Backup passes no pruned event: its `ibackup.journal_pruned` carries the safety zips too and stays in `restore.py`. Event names and fields are unchanged (docs/events.md regenerated, no diff).
- **T1.1** `ThrottledProgress` decides under a lock and forwards outside it (a blocking `call_from_thread` never holds up another worker's decision; reports from one thread stay in order). The Ace3 scan closures use it too, so their interval is now the shared `PROGRESS_INTERVAL` 0.1 s instead of Ace's own `PROGRESS_EVERY` 0.05 s (defined twice); the Ace scans also forward each flavor's first report now.
- **T1.1** Markers: only the file handling is shared (`core/marker.py`: atomic JSON write via `atomic_write_bytes`, `str()` for Paths as before, read as a dict, clear). Each tool keeps its `Marker` dataclass, its field checks and its `write_marker`/`read_marker`/`clear_marker` names (tests patch `editor.write_marker`); file names and JSON fields on disk are unchanged.
- **T1.1** `safe_destination` takes the stricter of the two guards for both tools (no `\` or `:` in rel or flavor); Ace keeps a one-line `destination` asking for `WTF/Account/.../SavedVariables/<file>`. `UndoResultBase` is a plain mixin (not a dataclass) so each tool's `UndoResult` keeps its own fields and field order.
- **T1.1** Deliberately left: A11/A12 (multi-flavor run containers and flavor loops) wait for T5.1's `core/parallel.py`; Ace's `ApplyResult._with` and Interface Backup's / Screenshot Organizer's undo results have other shapes; the Screenshot Organizer's `validate_dest` keeps its own wording ("destination", in-place hint). Tests for `plural`, `human_size` and `ThrottledProgress` moved from the tool test files to `tests/test_core_shared.py`.
