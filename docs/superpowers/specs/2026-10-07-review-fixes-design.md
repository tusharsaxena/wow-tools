# Full-review fixes: design

Date: 2026-10-07. Branch: `fix/review-2026-10-07`. Plan: `../plans/2026-10-07-review-fixes.md`, ledger
`../plans/2026-10-07-review-fixes.status.md`.

Source: the full-repo review bundle `reviews/2026-10-07/` (frozen). Its `01_FINDINGS.md` holds F-001 to F-014,
`02_PROPOSED_CHANGES.md` the changes C-01 to C-14, `03_TEST_PLAN.md` the tests and sign-off table, and
`04_EXECUTION_PLAN.md` the milestones this build follows. The user asked for every finding, Low included, to be fixed.

## Decisions

| # | Topic | Decision |
|---|---|---|
| R1 | F-006 (STD-5.17) | Option A, chosen by the user on 2026-10-07: Interface Backup's `restore.replace_part`, `restore.restore` and `undo.undo` default to `rename_no_replace`; the three are added to `tests/test_no_replace_call_sites.py`. No deviation row. |
| R2 | F-002 guard | A finished journal wins: if the run's journal ends with `finished` and every marker file has an `edited` entry, recovery only clears the stale marker (event `<prefix>.marker_stale`) and changes no files. The `UnfinishedRunScreen` default (D33) is unchanged. |
| R3 | F-001 roots | Recovery and Undo take the WoW folder from the configured `wow_path` (`wow_root`), never from the marker; the marker's `flavor_path` and `zip` are written with `to_stored()` and read with `to_native()`, kept for display and old markers. |
| R4 | Checkpoints | The user asked to be consulted only when absolutely necessary: the review plan's two human checkpoints (M1 refusal wording, M4 module names) are taken by the coordinator and recorded under "Decisions taken during the build" in the ledger. |
| R5 | F-007 split | Shared `SvRecoveryActions` in `ui/review.py`; per-tool mixins named after what they do (no `part2`), names checked against the STD-1.7 front-end list in `tests/test_structure.py`; no behaviour change in that commit. |
| R6 | Others | C-04, C-05, C-08 to C-14 as `02_PROPOSED_CHANGES.md` describes them; a build-time departure is recorded in the ledger. |
