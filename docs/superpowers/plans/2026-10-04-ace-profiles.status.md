# Ace3 Profile Manager — status ledger

Plan: `2026-10-04-ace-profiles.md`. Spec: `../specs/2026-10-04-ace-profiles-design.md`.
Branch: `feat/ace-profiles`. Resume at the first task not marked `done`. Update this file and commit it after
every task; push after each milestone. Never merge without the user's go-ahead. At the end of the run, after the
merge, delete every branch, stash and worktree this run created.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| 0 | spec and plan | done | b5d55ca | plan code for Tasks 2–10 pre-validated against its own tests in a scratch copy (102 tests); parser read all 750 real SV files (read-only) with no error, 53 AceDB DBs, 12 MB Questie in 0.9 s |
| 1 | core helpers: snapshot, svfiles, atomic_write_bytes | done | 15c1cf9 | core/snapshot.py + core/svfiles.py; WTF Cleaner wraps them (messages, names unchanged); 3 test patch targets moved to core, no assertion changed; full suite 811 OK, ruff clean |
| 2 | luasv parser, splice, codec | done | 5c8b888 | plan code verbatim apart from ruff fixes; 19 luasv tests OK (speed test ~0.1 s); full suite 830 OK, ruff clean |
| 3 | model: find AceDB databases | done | 20db114 | plan code verbatim; 9 ace_model tests OK; full suite 839 OK, ruff clean |
| 4 | events, settings | done | 7ca6a9a | plan code verbatim (core `get_int` already falls back on bad values); 6 ace_settings tests OK; docs/events.md gains the `ace-profiles` section; full suite 845 OK (2 skipped), ruff clean |
| 5 | fixture + scanner | done | 98474e8 | plan code verbatim (install `ErrorHandler` is `(Path, OSError)`, capture records use `event`); fixtures.py docstring gains a `build_ace_tree`/`ace_lua` paragraph; 9 ace_scanner tests OK; full suite 854 OK (2 skipped), ruff clean |
| 6 | ops: staging | done | b0a42fe | plan code verbatim; test drops the unused `DbKey` import (ruff F401); 16 ace_ops tests OK; full suite 870 OK (2 skipped), ruff clean |
| 7 | compile + verify | done | 98f572d | plan code verbatim (`FileEdit.file` typed `SvFile \| None` as the plan notes); test file drops the plan's `# tests/...` path comment; 11 ace_compile tests OK; full suite 881 OK (2 skipped), ruff clean; not pushed by the task agent (milestone push left to the orchestrator) |
| M1 | push milestone 1 | reviewed (not pushed yet) | 0e27823 | review fixes: module-only profiles kept, verify covers namespaces, partial write never follows a link; full suite 888 OK (2 skipped), ruff clean |
| 8 | journal + editor | todo | | |
| 9 | undo, recovery, multi | todo | | |
| 10 | report helpers | todo | | |
| M2 | push milestone 2 | todo | | |
| 11 | flow, settings screen, registration | todo | | |
| 12 | review screen: tree, ticks, filters, blacklist | todo | | |
| 13 | popups + staging from the tree | todo | | |
| 14 | apply, dry run, undo, recovery, result screens | todo | | |
| M3 | push milestone 3 | todo | | |
| 15 | docs + final battery | todo | | |
| M4 | push, ask for merge go-ahead | todo | | |

## Decisions taken during the build

- Task 1: `atomic_write_text` delegates as `atomic_write_bytes(path, text.replace("\n", os.linesep).encode("utf-8"))`,
  not plain `.encode("utf-8")`: the old text-mode write turned `\n` into CRLF on Windows, and config files keep that.
- Task 1: patch targets moved to core (no assertion changed): `test_cleaner.LockAndCheckTest._lock` and
  `test_no_replace_call_sites` patch `wowtools.core.svfiles.rename_no_replace`; the never-replaces snapshot test
  patches `wowtools.core.snapshot.snapshot_path`.
- Task 1: `safety.py` gains `SNAPSHOT_PREFIX = "backup"`; `LIST_REPORT_EVERY`/`SnapshotProgress`/`wtf_files` and
  `cleaner.LOCK_PROBE_SUFFIX` stay importable from their old modules as re-exports (`# noqa: F401`).
- Task 2: ruff fixes only, no behaviour change: `re.S`/`re.I` spelled `re.DOTALL`/`re.IGNORECASE`, `splice` uses
  `itertools.pairwise`, and the test drops the unused `Scalar` import.
- Task 6: ruff fix only: `tests/test_ace_ops.py` drops the unused `DbKey` import; no assertion changed.
- Task 7: `tests/test_ace_compile.py` drops the plan's leading `# tests/test_ace_compile.py` comment so the docstring
  comes first, as in the other test modules; the plan's `git push` in Step 5 is left to the milestone step.
- M1 review: fixed (two findings, one bug): compile deleted every `namespaces[*].profiles` entry with no main
  `profiles` entry on any edit to that database, unreported and passed by verify. `DbState.module_only` now tracks
  these module-only profiles (original -> staged name, None = deleted); they change only when a delete or rename
  names them (a referenced missing profile carries its module data along), the change shows in `changes()`, and
  rename/copy onto one is refused (`DbState.taken`). Keep only Default leaves unreferenced module-only profiles
  alone, as they are not shown as profiles. Spec §7/§8.1 intent kept; the collision refusal is new behaviour.
- M1 review: fixed: verify skipped the whole `namespaces` section. It now compares it byte for byte with only the
  inside of each module's `profiles` table and the LibDualSpec spec values cut out (spec §2 "only ... may
  change"); `model._namespaces`/`_lds` became public `namespace_profiles`/`lds_chars` for this.
- M1 review: fixed: `atomic_write_bytes` followed a symlink sitting at `<name>.partial`. It now removes whatever is
  there (a link is unlinked, never followed) and creates the partial with `O_CREAT|O_EXCL` (+`O_NOFOLLOW`).
- M1 review: no finding rejected.
