# Build status: review fixes (2026-10-04)

Checkpoint ledger for fixing every finding in `reviews/2026-10-04/01_FINDINGS.md`. The plan is
`reviews/2026-10-04/04_EXECUTION_PLAN.md` (changes in `02_PROPOSED_CHANGES.md`, tests in `03_TEST_PLAN.md`).
Work happens on branch `fix/review-2026-10-04`.

**To resume:** check out the branch, find the first row that isn't `done`, make sure `python3 scripts/run_tests.py`
passes, then carry on from that milestone.

Decisions taken on the review's open questions (by the maintainer's delegate, 2026-10-04):
- F-010: releases publish a zip asset plus `SHA256SUMS`; zip updates verify it and refuse without it unless
  `[general] allow_unverified_updates = true` (default false). Git installs unchanged.
- F-018: update backups keep the newest 2; dry-run cleaned zips are pruned like WTF backups (keep_backups per
  flavor); real cleaned-files zips are still never deleted (a documented promise).
- F-027: in copy mode, screenshots whose identical copy is already filed are not counted as waiting, show as
  already filed and start unticked.
- F-020: verified by a structural test plus the Windows CI job; no native manual check available.

| Milestone | Findings | Status | Commits | Notes |
|---|---|---|---|---|
| M6 CI | F-012 | done | 17e2ad3, 11d9399 | `.github/workflows/tests.yml` (ubuntu/windows x 3.10/3.13: compileall, gen_event_docs --check, run_tests). Run 37149064710 green on all four jobs (2nd attempt; the 1st failed only on Windows). Fixes: two WSL-simulation tests now skip on Windows (POSIX-only paths; a UNC path is a full path there); new `tests.fixtures.settle()` replaces wait_for_complete+pause in the TUI tests (Windows raced the review scan rebuild); run_tests.py pins shard pipes to UTF-8. vermin scan: nothing newer than 3.10. Linux 3.10/3.13 passed first time. |
| M1 Safety and lifecycle | F-001..F-004 | done | 8dc6ee6, cdfd2b0, 0d76992, a837a00 | All four reproduced by a failing test first. F-001: `enabled_addons()` returns every installed addon when there are no characters and adds a `scan.warning` (scope: the scanned account, or `WTF/Account` dir); new `tests.fixtures.build_solo_tree`. Only the zero-characters-overall case changes; an all-accounts scan where one account lacks characters still uses the global union (as the review's T1 intends). F-002: `Ka0sApp.action_quit` refuses while busy (new event `ui.quit_refused`); new `core/activity.py` is a counter (not a bare Event) so nested/overlapping runs are safe; clean, WTF undo and the organizer's job worker (organize and undo) run inside `activity.running()`; `suite.run` waits up to 600 s (`WORKER_WAIT_S`) before `lock.release()`, logs new `session.waiting_for_worker`, and `session.end` gets `waited_for_worker`/`worker_finished` (warning if the wait timed out). F-003: `_handle_exception` override logs `error` where=ui (unwraps `WorkerFailed`), guarded so logging can't break Textual; a worker-failure test added. F-004: `_clean_crashed` message names the WTF backup path when a backup was made; a dry run says nothing was deleted. Docs: wtf-cleaner.md (no-characters rule, troubleshooting row), README (no quit during a run), architecture.md, events.md regenerated. 420 tests green. |
| M2 Durability and file ops | F-007, F-008, F-013..F-017, F-021, F-022, F-028, F-029 | todo | | |
| R1 Review M1-M2 + fixes, push | | todo | | |
| M3 UI responsiveness | F-005, F-006 | todo | | |
| M4 Updater hardening | F-010, F-011, F-018, F-019, F-020, F-026 | todo | | |
| R2 Review M3-M4 + fixes, push | | todo | | |
| M5 Structure and cleanup | F-009, F-023, F-024, F-025, F-027 | todo | | |
| R3 Whole-branch review + fixes, push; ask for merge | | todo | | |
