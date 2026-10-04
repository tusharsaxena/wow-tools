# Execution plan: wow-tools review fixes (2026-10-04)

Branch: `fix/review-2026-10-04` off `master`. The user's preferences apply: work on a branch with a ledger, push
per milestone, and treat merge and release as separate approvals. Commit messages follow the repo's
conventional-commit style (`fix(wtf-cleaner): …`, `refactor(core): …`) and end with the session's attribution
lines.

## Milestones

### M1: Safety-critical correctness and lifecycle
**Done when:** C-01..C-04 are merged into the branch, their tests are green, and `run_tests.py` is green.

| Task | Owner role | Implements | Files touched |
|---|---|---|---|
| M1-T1 | correctness-fixer | C-01 (F-001) | `wowtools/tools/wtf_cleaner/scanner.py`, `tests/test_scanner.py`, `tests/test_rules.py` |
| M1-T2 | lifecycle-fixer | C-02 (F-002) | `wowtools/ui/base.py`, `wowtools/suite.py`, new `wowtools/core/activity.py`, `wowtools/tools/wtf_cleaner/review_screen.py`, `wowtools/tools/screenshot_organizer/review_screen.py`, `tests/test_ui_base.py`, `tests/test_suite.py` |
| M1-T3 | lifecycle-fixer | C-03 (F-003) | `wowtools/suite.py`, `wowtools/ui/base.py`, `tests/test_suite.py`, `tests/test_ui_base.py` |
| M1-T4 | error-handling-fixer | C-04 (F-004) | `wowtools/tools/wtf_cleaner/review_screen.py`, `tests/test_wtf_app.py` |

### M2: Data durability and file-op safety
**Done when:** C-07, C-08, C-13..C-17, C-21, C-22, C-26 are green, `gen_event_docs.py --check` passes (C-13 adds
an event), and the concurrency stress test for F-007 passes.

| Task | Owner role | Implements | Files touched |
|---|---|---|---|
| M2-T1 | durability-fixer | C-07 (F-007) | new `wowtools/core/fsutil.py`, `wowtools/core/config.py`, `wowtools/core/migrate.py`, `wowtools/core/updater.py` (`check_for_update` persist hook only), `wowtools/ui/base.py`, `tests/test_config.py`, `tests/test_ui_base.py`, `tests/test_updater_check.py` |
| M2-T2 | validation-fixer | C-08 (F-008, F-029) | `wowtools/core/install.py`, `wowtools/tools/wtf_cleaner/app.py`, `wowtools/tools/wtf_cleaner/review_screen.py`, `wowtools/tools/screenshot_organizer/settings.py`, `wowtools/tools/screenshot_organizer/review_screen.py`, `tests/test_install.py`, `tests/test_wtf_app.py`, `tests/test_screenshot_organizer_app.py` |
| M2-T3 | file-ops-fixer | C-14 (F-014), C-26 (F-028) | `wowtools/core/fsutil.py`, `wowtools/tools/screenshot_organizer/organizer.py`, `wowtools/tools/wtf_cleaner/cleaner.py`, `wowtools/tools/wtf_cleaner/safety.py`, `wowtools/core/journal.py` (`new_journal_path` → `free_name`), new `tests/test_fsutil.py`, `tests/test_safety.py`, `tests/test_screenshot_organizer_organizer.py` |
| M2-T4 | file-ops-fixer | C-13 (F-013), C-22 (F-022) | `wowtools/tools/wtf_cleaner/cleaner.py`, `wowtools/tools/wtf_cleaner/scanner.py`, `wowtools/tools/wtf_cleaner/events.py`, `docs/events.md`, `tests/test_cleaner.py`, `tests/test_scanner.py` |
| M2-T5 | journal-fixer | C-15, C-16, C-17 (F-015..F-017) | `wowtools/tools/screenshot_organizer/journal.py`, `wowtools/tools/screenshot_organizer/undo.py`, `wowtools/tools/screenshot_organizer/organizer.py` (`OrganizeResult.marked_undone`), `wowtools/tools/screenshot_organizer/report.py`, `wowtools/core/journal.py`, `tests/test_screenshot_organizer_undo.py` |
| M2-T6 | correctness-fixer | C-21 (F-021) | `wowtools/core/lock.py`, new `tests/test_lock.py` |

### M3: UI responsiveness
**Done when:** C-05 and C-06 are green, and the F-005/F-006 perf spot-checks meet their targets (≤ 150 ms per 500
events on drvfs; confirm latency < 100 ms).

| Task | Owner role | Implements | Files touched |
|---|---|---|---|
| M3-T1 | ui-perf | C-06 (F-006) | `wowtools/core/events.py`, `wowtools/tools/wtf_cleaner/rules.py`, `wowtools/tools/wtf_cleaner/review_screen.py`, `tests/test_events.py`, `tests/test_wtf_app.py` |
| M3-T2 | ui-perf | C-05 (F-005) | `wowtools/tools/wtf_cleaner/review_screen.py`, `wowtools/ui/setup_screen.py`, `wowtools/ui/flavor_screen.py` (`set_notes`), `wowtools/tools/screenshot_organizer/app.py`, `wowtools/ui/base.py`, `tests/test_wtf_app.py`, `tests/test_flavor_screen.py`, `tests/test_ui_base.py`, `tests/test_screenshot_organizer_app.py` |

### M4: Updater hardening
**Done when:** C-10, C-11, C-18 (update-backup part), C-19, C-20 and C-24 are green, `docs/releasing.md` describes
the new assets, and the Windows manual check for C-20 is signed off.

| Task | Owner role | Implements | Files touched |
|---|---|---|---|
| M4-T1 | security-fixer | C-10 (F-010) | `wowtools/core/updater.py`, `scripts/update_vendor.py`, new `requirements.lock`, `docs/releasing.md`, `docs/vendoring.md`, `tests/test_updater_apply.py`, `tests/test_updater_check.py` |
| M4-T2 | updater-fixer | C-11 (F-011), C-24 (F-026) | `wowtools/core/updater.py`, `tests/test_updater_apply.py`, `tests/test_updater_check.py` |
| M4-T3 | updater-fixer | C-18 partial (F-018), C-19 (F-019) | `wowtools/core/updater.py`, `tests/test_updater_apply.py` |
| M4-T4 | windows-fixer | C-20 (F-020) | `wow-tools.cmd` |

### M5: Structure and cleanup
**Done when:** C-09 and C-23 are green, the C-09 greps match, and `docs/architecture.md`, `docs/adding-a-tool.md`
and `CLAUDE.md` describe the shared dialogs.

| Task | Owner role | Implements | Files touched |
|---|---|---|---|
| M5-T1 | refactorer | C-09 (F-009, F-023, F-024) | new `wowtools/ui/dialogs.py`, `wowtools/core/fsutil.py`, both `review_screen.py`, `wowtools/tools/wtf_cleaner/result_screen.py`, `wowtools/tools/wtf_cleaner/cleaner.py`, `wowtools/tools/wtf_cleaner/undo.py`, `wowtools/tools/screenshot_organizer/organizer.py`, `wowtools/tools/screenshot_organizer/undo.py`, `wowtools/tools/wtf_cleaner/safety.py`, `wowtools/core/backup.py`, `wowtools/core/journal.py`, `wowtools/core/migrate.py`, `wowtools/tools/wtf_cleaner/rules.py`, `wowtools/tools/wtf_cleaner/settings.py`, `wowtools/tools/wtf_cleaner/multi.py`, docs, `CLAUDE.md`, tests (imports only) |
| M5-T2 | correctness-fixer | C-23 (F-025) | `wowtools/core/process.py`, `tests/test_process.py` |

### M6: CI
**Done when:** the workflow runs green on all four matrix jobs for the branch's PR.

| Task | Owner role | Implements | Files touched |
|---|---|---|---|
| M6-T1 | test-author | C-12 (F-012) | new `.github/workflows/tests.yml`; any Windows-specific test fixes it surfaces |

M6 is listed last for the narrative, but its workflow file touches nothing else. **Start it in parallel with M1**
so every later milestone benefits from CI.

## Critical path and concurrency map

**Critical path:** M1 → M2 → M3 → M5. M4 and M6 run beside it.

These files are hot spots. Tasks that touch the same file must run one after another, in the order shown:

| File | Tasks touching it | Order |
|---|---|---|
| `wowtools/tools/wtf_cleaner/review_screen.py` | M1-T2, M1-T4, M2-T2, M3-T1, M3-T2, M5-T1 | M1-T2 → M1-T4 → M2-T2 → M3-T1 → M3-T2 → M5-T1 |
| `wowtools/ui/base.py` | M1-T2, M1-T3, M2-T1, M3-T2 | M1-T2 → M1-T3 → M2-T1 → M3-T2 |
| `wowtools/suite.py` | M1-T2, M1-T3 | M1-T2 → M1-T3 |
| `wowtools/core/updater.py` | M2-T1 (persist hook), M4-T1, M4-T2, M4-T3 | M2-T1 → M4-T2 → M4-T3 → M4-T1 (biggest last) |
| `wowtools/core/fsutil.py` (new) | M2-T1 (creates), M2-T3, M5-T1 | M2-T1 → M2-T3 → M5-T1 |
| `wowtools/tools/wtf_cleaner/cleaner.py` | M2-T3, M2-T4, M5-T1 | M2-T3 → M2-T4 → M5-T1 |
| `wowtools/tools/screenshot_organizer/organizer.py` | M2-T3, M2-T5, M5-T1 | M2-T3 → M2-T5 → M5-T1 |
| `wowtools/core/journal.py` | M2-T3, M2-T5, M5-T1 | M2-T3 → M2-T5 → M5-T1 |
| `wowtools/tools/screenshot_organizer/review_screen.py` | M1-T2, M2-T2, M5-T1 | M1-T2 → M2-T2 → M5-T1 |
| `tests/test_wtf_app.py` | M1-T4, M2-T2, M3-T1, M3-T2 | same order as the source tasks |

These tasks can run in parallel because their file sets do not overlap:
- **M1-T1** (scanner, test_scanner, test_rules) ∥ M1-T2/T3/T4. Note that M2-T4 touches `scanner.py` later, so
  M1-T1 must land first.
- **M2-T6** (lock.py) ∥ every other M2 task.
- **M4-T4** (`wow-tools.cmd`) ∥ everything.
- **M5-T2** (process.py) ∥ everything.
- **M6-T1** (`.github/`) ∥ everything.
- **M2-T2** and **M2-T5** both touch `screenshot_organizer/*`, but the files differ (settings + review_screen vs
  journal + undo + report + organizer). They can run in parallel, **except** that M2-T5's `organizer.py` edit must
  come after M2-T3's.

## Checkpoints
1. **After M1:** a human reviews the F-001 behavior change (the new `scan.warning`, no `not_enabled` proposals
   for character-less accounts) and the quit-refusal UX. Confirm the C-03 private-hook override is acceptable.
   **Push the branch.**
2. **After M2:** a human runs the manual happy path (regression item 6) on a copy of a real WTF folder, on WSL
   and, if possible, natively on Windows, with focus on C-14's no-replace rename on drvfs and NTFS. Check
   `docs/events.md` was regenerated. **Push.**
3. **Before M4-T1 is merged:** agree the release-process change (zip + `SHA256SUMS` assets) and the
   `allow_unverified_updates` default. This changes what `docs/releasing.md` asks of the maintainer. **Push.**
4. **After M3:** check the perf spot-check numbers on the maintainer's real WSL setup and record them in the
   sign-off table.
5. **Before M5 (refactor):** confirm M1-M4 are green on CI (M6). M5 is pure restructuring, and CI is the safety
   net.
6. **Before merge:** full sign-off table filled, CI green on all jobs, and a separate approval for the merge. The
   release (tag `v1.0.1` plus the assets) is a further separate approval.

## Incremental commit strategy
One commit per task, in the serialization order above. Suggested messages:

| Task | Commit message |
|---|---|
| M1-T1 | `fix(wtf-cleaner): never propose "not enabled" for an account with no character folders (F-001)` |
| M1-T2 | `fix(ui): refuse Ctrl+Q while a run is busy and keep the lock until workers finish (F-002)` |
| M1-T3 | `fix(suite): propagate the app's return code and log UI crashes to the event log (F-003)` |
| M1-T4 | `fix(wtf-cleaner): unexpected clean errors are shown and logged instead of closing the app (F-004)` |
| M2-T1 | `fix(core): atomic config saves, persisted only from the UI thread (F-007)` |
| M2-T2 | `fix: validate backup and destination folders on save and before use (F-008, F-029)` |
| M2-T3 | `fix(core): no-replace renames and unique backup names (F-014, F-028)` |
| M2-T4 | `fix(wtf-cleaner): recover lock-probe leftovers; CleanError instance fields (F-013, F-022)` |
| M2-T5 | `fix(screenshot-organizer): robust journal parsing, confined and retryable undo (F-015, F-016, F-017)` |
| M2-T6 | `fix(core): one WSL detection for the instance lock (F-021)` |
| M3-T1 | `perf(core): keep log files open; no per-item proposal events on interactive rebuilds (F-006)` |
| M3-T2 | `perf(ui): run process checks, install detection, flavor counts and updates in workers (F-005)` |
| M4-T1 | `feat(updater): verify zip updates against published SHA-256 sums; hashed vendor installs (F-010)` |
| M4-T2 | `fix(updater): bounded, non-interactive git updates; ignore untracked files; future check stamps (F-011, F-026)` |
| M4-T3 | `fix(updater): replace only shipped files; keep the newest two update backups (F-018, F-019)` |
| M4-T4 | `fix(launcher): wow-tools.cmd exits inside its parsed block so updates can replace it (F-020)` |
| M5-T1 | `refactor(ui): shared ConfirmScreen/ProgressScreen and fsutil helpers; remove dead code (F-009, F-023, F-024)` |
| M5-T2 | `refactor(core): compute unknown WoW processes once in wow_check_for (F-025)` |
| M6-T1 | `ci: test matrix for Python 3.10/3.13 on Linux and Windows (F-012)` |
