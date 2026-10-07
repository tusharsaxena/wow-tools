# Full-review fixes: status ledger

Plan: `2026-10-07-review-fixes.md`. Spec: `../specs/2026-10-07-review-fixes-design.md`.
Branch: `fix/review-2026-10-07`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| T0 | spec, plan, ledger, review bundle | done | (this commit) | baseline full suite 1710 run, 0 failures (2 skipped) per the review |
| T1.1 | C-02 Undo snapshots validated flavors (F-003) | done | (this commit) | `undo_run` builds the flavors to snapshot (and prune) only from entries whose destination passed `safe_destination`; new `test_undo_never_snapshots_a_flavor_outside_the_install` (failed first: zip at `snapshots/snapshot-../elsewhere-*.zip`). Review fix: the rule is now `core/sv_undo.undo_flavors`, shared by `undo_run` and both Undo popups (Ace3 Profile Manager and Saved Variables Browser `review_screen.py`), so the popup no longer shows a row for a flavor that is never snapshotted (STD-2.2); new `test_undo_flavors_keeps_only_flavors_with_an_entry_inside_the_install` (failed first); internals and architecture docs updated. Full suite 1712 run, 0 failures (2 skipped) |
| T1.2 | C-01 recovery under the configured WoW folder (F-001) | done | (this commit) | `sv_undo.recover` takes a required `wow_root` (the configured `wow_path`) and resolves every file and the snapshot flavor under it, never the marker's `flavor_path`; a marker whose flavor is not a plain folder name or not a folder in `wow_root` is refused with `UndoError` ("... Nothing was changed.") before anything runs, and the marker stays. `core/marker.write_marker` stores Path values with `to_stored()`; `sv_apply.read_marker` and the WTF Cleaner's `safety.read_marker` read them with `to_native()`. `_moved_zip` takes the zip's name with `PureWindowsPath` so a Windows-form path still falls back by name. Both review screens pass `wow_root=self.cfg.wow_path` (and keep the marker when no WoW folder is set); the two `undo.py` wrappers' docstrings name it. New `test_recover_uses_the_configured_wow_folder_not_the_markers`, `test_recover_never_touches_the_folder_the_marker_names`, `test_recover_refuses_a_flavor_not_in_the_wow_folder_and_keeps_the_marker` and `test_marker_paths_are_stored_in_windows_form_and_read_natively` (all failed first), plus the same marker test for the WTF Cleaner's `clean-in-progress.json` in `test_safety.py` (fails if `read_marker` goes back to `Path(...)`); both marker tests skip on Windows (`os.name == "nt"`) like `test_journal.py`'s WSL test, since a `/mnt/g` path is a `WindowsPath` there (STD-10.x CI matrix); existing recover calls in `test_ace_undo.py`, `test_sv_browser_apply.py` and `test_core_sv_pipeline.py` pass `wow_root`. Architecture and Ace3 internals docs updated; CHANGELOG `[Unreleased]` / Fixed line. Full suite 1717 run, 0 failures (2 skipped) |
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
- T1.2: `wow_root` is a required keyword of `recover` (no fallback to the marker's `flavor_path`), per R3; every existing caller and test passes it.
- T1.2: the `to_stored()` write lives in the shared `core/marker.write_marker`, so the WTF Cleaner's `clean-in-progress.json` is stored in Windows form too; its `read_marker` reads with `to_native()` (a marker only produces a notice there, so no behavior change beyond portability). Older `str()` markers still read.
- T1.2: the flavor check runs first, before the WoW-running check, so a marker for a game version that is not in the configured WoW folder is refused with "<flavor> is not in the WoW folder <path>. Nothing was changed." (path shown with `to_stored()`), and an invalid flavor name with "The unfinished change names a game version folder that is not valid. Nothing was changed." This is the M1 refusal-wording checkpoint, taken per R4.
- T1.2: no new event for the refusal: it is an `UndoError` the review's `start_run` already handles as an expected refusal, like the locked-file and WoW-running refusals.
- T1.2: departure from the sketch: `_moved_zip` now takes the name with `PureWindowsPath(zip_path).name`, because on a non-WSL POSIX host `to_native()` leaves a Windows-form path as one path component and `.name` would be the whole string.
- T1.2: CHANGELOG gains an `## [Unreleased]` section with a `### Fixed` group (the first post-0.1.0 entry), following the 0.1.0 entry's tool-grouped bullet style.
