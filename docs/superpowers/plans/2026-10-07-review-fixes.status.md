# Full-review fixes: status ledger

Plan: `2026-10-07-review-fixes.md`. Spec: `../specs/2026-10-07-review-fixes-design.md`.
Branch: `fix/review-2026-10-07`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| T0 | spec, plan, ledger, review bundle | done | (this commit) | baseline full suite 1710 run, 0 failures (2 skipped) per the review |
| T1.1 | C-02 Undo snapshots validated flavors (F-003) | done | (this commit) | `undo_run` builds the flavors to snapshot (and prune) only from entries whose destination passed `safe_destination`; new `test_undo_never_snapshots_a_flavor_outside_the_install` (failed first: zip at `snapshots/snapshot-../elsewhere-*.zip`). Review fix: the rule is now `core/sv_undo.undo_flavors`, shared by `undo_run` and both Undo popups (Ace3 Profile Manager and Saved Variables Browser `review_screen.py`), so the popup no longer shows a row for a flavor that is never snapshotted (STD-2.2); new `test_undo_flavors_keeps_only_flavors_with_an_entry_inside_the_install` (failed first); internals and architecture docs updated. Full suite 1712 run, 0 failures (2 skipped) |
| T1.2 | C-01 recovery under the configured WoW folder (F-001) | todo | | |
| T1.3 | C-03 marker_left, finished journal wins (F-002) | todo | | |
| T2.1 | C-04 WTF recheck before each delete (F-004) | todo | | |
| T2.2 | C-05 updater rollback on any interruption (F-005) | todo | | |
| T2.3 | C-06 IB folder swaps use rename_no_replace (F-006) | todo | | |
| T2.4 | C-09 create_backup removes its partial (F-009) | todo | | |
| T3.1 | C-08 lock released when logging fails (F-008) | todo | | |
| T3.2 | C-10 process listings decoded as UTF-8 (F-010) | todo | | |
| T3.3 | C-11 drop dead re-exports (F-011) | todo | | |
| T3.4 | C-12 fsync before atomic replace (F-012) | todo | | |
| T3.5 | C-13 config comments documented (F-013) | todo | | |
| T3.6 | C-14 per-shard timeout (F-014) | todo | | |
| T4.1 | characterization of recovery flows (F-007) | todo | | |
| T4.2 | C-07 SvRecoveryActions, screen split (F-007) | todo | | |
| T5.1 | whole-branch review, fixes, push | todo | | |

## Decisions taken during the build

- T1.1: no `CHANGELOG.md` line. The fix only changes behavior for a hand-edited or corrupted journal, so it is not user-noticeable on any normal run (STD-11.1); the 04 plan's T1.1 file list also leaves it out.
- T1.1: the flavor list also feeds `_prune`, so a crafted flavor no longer reaches pruning either; the review's sketch was followed as written.
- T1.1: the review's UI finding was taken as real: the Undo popups' rows now come from the same `undo_flavors` helper as `undo_run` (re-exported by each tool's `undo.py`, as `destination` is), instead of only rewording the comment.
