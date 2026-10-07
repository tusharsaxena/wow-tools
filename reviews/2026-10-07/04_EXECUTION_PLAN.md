# Execution plan: wow-tools full review (2026-10-07)

This follows STD-12.1 and STD-12.2. Work happens on a feature branch, e.g. `fix/review-2026-10-07`. Task 0 creates
the dated spec, the plan and the `.status.md` ledger under `docs/superpowers/`. Each task is committed on its own
and its ledger row updated. Push at each milestone. Merging into master and releasing are two separate approvals
from the user (STD-12.3). Every commit passes the green gate (STD-10.1).

There is no upstream milestone: there are no `[upstream]` findings.

## Milestones

### M0: Setup
- **T0** (coordinator): branch, spec (decision IDs for C-03's "finished journal wins" rule and C-06's option),
  plan, ledger.
- **Done when:** the branch is pushed with the spec, plan and ledger, and the user has chosen C-06 Option A or B.

### M1: Recovery and Undo correctness (F-001, F-002, F-003)
| Task | Role | Change | Files |
|---|---|---|---|
| T1.1 | security-fixer | C-02 (F-003) | `core/sv_undo.py`, `tests/test_core_sv_pipeline.py` |
| T1.2 | refactorer | C-01 (F-001) | `core/sv_undo.py`, `core/sv_apply.py`, `tools/ace3_profile_manager/undo.py`, `tools/sv_browser/undo.py`, both `review_screen.py` recovery call sites, tests |
| T1.3 | refactorer | C-03 (F-002) | `core/marker.py`, `core/sv_apply.py`, `core/sv_undo.py`, `core/sv_events.py`, `core/sv_report.py`, `docs/events.md`, `CHANGELOG.md`, tests |
- **Order:** T1.1, then T1.2, then T1.3, run one after another. All three touch `core/sv_undo.py`, and T1.2 and
  T1.3 both touch `core/sv_apply.py`.
- **Done when:** C-01, C-02 and C-03 are signed off in `03_TEST_PLAN.md`, and the full suite is green.
- **Checkpoint (human):** review the new recovery refusal wording and the `marker_left` result row before M2.

### M2: Independent safety fixes (F-004, F-005, F-006, F-009)
| Task | Role | Change | Files |
|---|---|---|---|
| T2.1 | refactorer | C-04 (F-004) | `tools/wtf_cleaner/cleaner.py`, `tests/test_cleaner.py`, `CHANGELOG.md` |
| T2.2 | refactorer | C-05 (F-005) | `core/updater.py`, `suite.py`, `tests/test_updater_apply.py` |
| T2.3 | refactorer | C-06 (F-006) | `tools/interface_backup/restore.py`, `tools/interface_backup/undo.py`, `tests/test_no_replace_call_sites.py` (A) **or** `docs/standards.md` (B) |
| T2.4 | refactorer | C-09 (F-009) | `core/backup.py`, `tests/test_backup.py` |
- **Parallelism:** the file sets are disjoint, so these can run in parallel. `CHANGELOG.md` is the one shared file
  (T2.1, and T1.3 before it). Merge the changelog lines one task at a time.
- **Done when:** C-04, C-05, C-06 and C-09 are signed off, and CI is green on both OSes.

### M3: Hardening (F-008, F-010, F-011, F-012, F-013, F-014)
| Task | Role | Change | Files |
|---|---|---|---|
| T3.1 | refactorer | C-08 (F-008) | `suite.py`, `core/events.py`, `tests/test_suite.py` |
| T3.2 | refactorer | C-10 (F-010) | `core/process.py`, `tests/test_process.py` |
| T3.3 | refactorer | C-11 (F-011) | `tools/wtf_cleaner/safety.py`, `tools/ace3_profile_manager/report.py`, `tests/test_structure.py` |
| T3.4 | refactorer | C-12 (F-012) | `core/fsutil.py`, `tests/test_fsutil.py` |
| T3.5 | doc-writer | C-13 (F-013) | `README.md`, `core/updater.py` (message) |
| T3.6 | test-author | C-14 (F-014) | `scripts/run_tests.py`, `docs/testing.md`, `CLAUDE.md` |
- **Serialize:** T3.1 after T2.2 (both touch `suite.py`). T3.5 after T2.2 (both touch `core/updater.py`). T3.3
  before C-07 (both touch `tests/test_structure.py`).
- **Parallelizable:** T3.2, T3.4 and T3.6.
- **Done when:** all six are signed off. The C-12 performance delta is recorded with its measurement.

### M4: Review-screen split (F-007)
| Task | Role | Change | Files |
|---|---|---|---|
| T4.1 | test-author | characterization: record the `-k ace` and `-k sv_browser` counts, and add any missing recovery-flow UI test before the move | `tests/test_ace_app.py`, `tests/test_sv_browser_run_ui.py` |
| T4.2 | refactorer | C-07: `SvRecoveryActions` in `ui/review.py`, plus the per-tool action mixins | `ui/review.py`, both `review_screen.py`, new mixin modules, `tests/test_structure.py`, `docs/architecture.md`, both `docs/internals/*.md` |
- **Serialize:** after M1 (T1.2 touches the same recovery call sites) and after T3.3 (`tests/test_structure.py`).
- **Checkpoint (human):** before T4.2, confirm the module names pass the STD-1.7 front-end list in
  `tests/test_structure.py`.
- **Done when:** the counts are not lower than T4.1's, there are 0 failures, and the meta-tests pass.

### M5: Whole-branch review (STD-12.5)
- **T5.1** (reviewer): review the branch, then run the full suite, ruff and the events check, and fill the
  sign-off table in `03_TEST_PLAN.md`. Ask the user for the merge go-ahead.

## Critical path
T0, then T1.1, T1.2, T1.3, then M2 (in parallel), then T3.1 and T3.5, then T3.3, then T4.1, T4.2, then T5.1.

## Commit boundaries (one per task)
- `fix(core): Undo snapshots only flavors that pass safe_destination (F-003)`
- `fix(core): recovery resolves files under the configured WoW folder; markers store paths in Windows form (F-001)`
- `fix(core): report a marker that could not be cleared; recovery leaves a finished run alone (F-002)`
- `fix(wtf-cleaner): recheck each file right before deleting it (F-004)`
- `fix(updater): roll the zip update back on any interruption (F-005)`
- `fix(interface-backup): folder swaps use rename_no_replace (F-006)` *or* `docs(standards): record Interface Backup's folder-swap rename deviation (F-006)`
- `fix(core): create_backup removes its partial on an interrupt (F-009)`
- `fix(suite): release the lock when logging cannot start (F-008)`
- `fix(core): decode process listings as UTF-8 (F-010)`
- `refactor: drop dead re-exports (F-011)`
- `fix(core): fsync before the atomic replace (F-012)`
- `docs: config comments are not kept on save (F-013)`
- `test: per-shard timeout in run_tests.py (F-014)`
- `test: characterization of the Ace3 and SV Browser recovery flows (F-007)`
- `refactor(ui): SvRecoveryActions; split the Ace3 and SV Browser review screens (F-007)`

Each commit message ends with the attribution lines the session requires.
