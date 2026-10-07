# Full-review fixes: plan

Spec: `../specs/2026-10-07-review-fixes-design.md`. Ledger: `2026-10-07-review-fixes.status.md`. Branch:
`fix/review-2026-10-07`.

The tasks, files, order and commit messages are those of `reviews/2026-10-07/04_EXECUTION_PLAN.md` (frozen); the
change for each is in `02_PROPOSED_CHANGES.md` and its tests in `03_TEST_PLAN.md`. Every task: write the failing test
first, make the change, run the green gate (`python3 scripts/run_tests.py`, `ruff check --no-cache .`,
`python3 scripts/gen_event_docs.py --check`), add a `CHANGELOG.md` line when the change is user-noticeable, commit
once, and update its ledger row (status, commit, full-suite count). Push after each milestone. Never merge.

| Milestone | Tasks |
|---|---|
| M0 Setup | T0 branch, spec, plan, ledger, review bundle |
| M1 Recovery and Undo | T1.1 C-02 (F-003), T1.2 C-01 (F-001), T1.3 C-03 (F-002), in that order |
| M2 Safety | T2.1 C-04 (F-004), T2.2 C-05 (F-005), T2.3 C-06 option A (F-006), T2.4 C-09 (F-009) |
| M3 Hardening | T3.1 C-08 (F-008), T3.2 C-10 (F-010), T3.3 C-11 (F-011), T3.4 C-12 (F-012), T3.5 C-13 (F-013), T3.6 C-14 (F-014) |
| M4 Split | T4.1 characterization tests, T4.2 C-07 (F-007) |
| M5 Review | T5.1 whole-branch review, fixes, sign-off table in the ledger, push; then ask for the merge go-ahead |
