# Test plan: wow-tools full review (2026-10-07)

## Pre-flight

```sh
cd <repo>
python3 --version                          # 3.10 or newer
python3 scripts/run_tests.py               # baseline: 1710 run, 0 failures, 0 errors, 2 skipped (2026-10-07)
ruff check --no-cache .                    # All checks passed!
python3 scripts/gen_event_docs.py --check  # exit 0
```

No installation is needed: `vendor/` is committed. Tests use `tests/fixtures.py` trees and `make_config`, and
never touch a real WoW install or the network (STD-10.3, STD-10.4). Textual tests subclass `TuiTestCase`
(STD-10.5).

## Per-change tests

### C-01: recovery resolves under the configured WoW folder (F-001)
- **Setup:** `build_wow_tree` in a temp folder. Write an `edit-in-progress.json` whose `flavor_path` is
  `G:\World of Warcraft\_retail_` and whose `zip` is a Windows-form path. The file on disk is at `sha_after`.
  Put an originals zip with the `sha_before` bytes in `<root>/edited/`.
- **Steps:**
  1. Add `tests/test_core_sv_pipeline.py::test_recover_uses_the_configured_wow_folder_not_the_markers`.
  2. Call `sv_undo.recover(SV_TOOL, marker, wow_root=<tmp WoW>, root=<root>, journal_dir=...)`.
- **Expected:** the file is put back to `sha_before`, the outcome is `restored`, and the marker is removed.
- **Second case:** with a marker naming a flavor folder that does not exist under `wow_root`, the call raises
  `UndoError` ending "Nothing was changed." and the marker file still exists.
- **Pass/Fail:** pass only if both cases behave as described.

### C-02: Undo snapshots only validated flavors (F-003)
- **Setup:** a journal with one `edited` entry whose `flavor` is `../elsewhere`, and a sibling `elsewhere/WTF`
  folder holding a file.
- **Steps:** add `tests/test_core_sv_pipeline.py::test_undo_never_snapshots_a_flavor_outside_the_install` and
  call `undo_run`.
- **Expected:** `result.snapshots == []`. No file exists anywhere under `<root>` except what was there before. The
  outcome is `skipped` with "it is outside the WTF folder".
- **Pass/Fail:** pass only if no zip is created.

### C-03: a marker left after a finished run is reported, and recovery does not revert a finished run (F-002)
- **Steps:**
  1. Add `tests/test_core_sv_pipeline.py::test_a_marker_that_cannot_be_removed_is_reported`. Patch `os.remove`
     to raise `PermissionError` for the marker name only, then run `apply_flavor` (real run).
  2. **Expected:** `result.marker_left is True`, and `<prefix>.marker_left` is logged (`capture_events`).
  3. Add `tests/test_core_sv_pipeline.py::test_recovery_of_a_finished_run_changes_nothing`. After a successful
     apply, write the same marker back by hand and call `recover(...)`.
  4. **Expected:** the files stay at `sha_after`, the marker is removed, `<prefix>.marker_stale` is logged, and
     no `rolled_back` record is appended to the journal.
- **Pass/Fail:** pass only if all the expected results hold.
- **Regenerate:** `python3 scripts/gen_event_docs.py`, then `--check` exits 0.

### C-04: WTF Cleaner rechecks just before deleting (F-004)
- **Steps:** add `tests/test_cleaner.py::test_a_file_changed_after_the_snapshot_is_not_deleted`. Patch
  `cleaner._take_safety_snapshot` with a wrapper that calls the real one, then rewrites one selected file with
  longer content. Run `execute(..., dry_run=False, backup=False)`.
- **Expected:** that file still exists with its new content, its outcome is `skipped` / `changed`, and the other
  files are deleted.
- **Pass/Fail:** pass only if the rewritten file survives.

### C-05: updater rolls back on `KeyboardInterrupt` (F-005)
- **Steps:** add `tests/test_updater_apply.py::test_ctrl_c_during_the_swap_rolls_back`. Inject a `_copy` (patch)
  that raises `KeyboardInterrupt` on the first shipped name, and call `apply_update` on a fake zip install.
- **Expected:** `KeyboardInterrupt` propagates, and every managed name in `root` has its pre-update content
  (compare a hash of the tree before and after).
- **Pass/Fail:** pass only if the trees match.

### C-06: Interface Backup renames (F-006)
- **Option A:** `tests/test_no_replace_call_sites.py::test_default_renames_are_rename_no_replace` includes the
  three Interface Backup functions and passes. `python3 scripts/run_tests.py -k interface_backup` is green.
- **Option B:** the new deviation row exists in `docs/standards.md`, and a test asserts the `os.rename` default.
- **Pass/Fail:** pass only if the option the user chose is fully in place.

### C-07: review-screen split (F-007)
- **Steps:**
  1. Before the split, record `python3 scripts/run_tests.py -k ace` and `-k sv_browser` (counts, all green).
  2. Do the split.
  3. Run the same commands again, plus the meta-tests: `-k test_structure`, `-k test_look_and_feel`,
     `-k test_help`.
- **Expected:** the same or higher pass counts, 0 failures. The new structure pin for `SvRecoveryActions` passes.
- **Pass/Fail:** pass only if counts are not lower and there are no failures.

### C-08: lock released on early start-up failure (F-008)
- **Steps:** add `tests/test_suite.py::test_lock_is_released_when_the_log_cannot_start`. Patch
  `wowtools.suite.init_event_log` to raise `OSError`, then call `suite.run([], lock_path=tmp_lock, ...)`.
- **Expected:** the exception propagates or the call returns 1, and `tmp_lock` does not exist afterwards.
- **Pass/Fail:** pass only if the lock file is gone.

### C-09: `create_backup` partial cleaned on `BaseException` (F-009)
- **Steps:** add `tests/test_backup.py::test_interrupt_leaves_no_partial`. Make `on_file` raise
  `KeyboardInterrupt`.
- **Expected:** no `*.partial` exists in the destination folder.

### C-10: process listing decode (F-010)
- **Steps:** add `tests/test_process.py::test_non_utf8_powershell_output_is_unknown_not_a_crash`. Use a fake
  runner that returns `stdout` bytes `b"Wow.exe|C:\\Jos\x82\\World of Warcraft\\_retail_\\Wow.exe"` through a
  `CompletedProcess`, or raises `UnicodeDecodeError` to simulate locale decoding.
- **Expected:** the check returns a list or `None` and never raises.

### C-11: dead re-exports (F-011)
- **Steps:** `python3 scripts/run_tests.py -k test_dead_code_is_gone` and `ruff check --no-cache .`.
- **Expected:** both pass, and `grep -n LIST_REPORT_EVERY wowtools/tools` finds nothing.

### C-12: `fsync` (F-012)
- **Steps:** add `tests/test_fsutil.py::test_atomic_write_fsyncs_before_replace`. Patch `os.fsync` and
  `os.replace` with recorders, then call `atomic_write_bytes`.
- **Expected:** `fsync` is recorded before `replace`.
- **Performance spot-check:** see below.

### C-13: config comments (F-013)
- **Steps:** `python3 scripts/run_tests.py -k test_docs`.
- **Expected:** green, and the README states that comments are not kept.

### C-14: shard timeout (F-014)
- **Steps:** `python3 scripts/run_tests.py --timeout 5 -k test_tiny_terminal_still_works`, using a deliberately
  short timeout on a slow test.
- **Expected:** the shard reports "timed out", and the exit code is 1.
- **Then:** run with the default timeout and confirm it is green.

## Manual / live-environment checks
These need a real install and cannot run here:
1. **F-001, cross-OS recovery:** on one PC with WoW at `G:\World of Warcraft`, start an SV Browser Apply from
   Windows and kill the process (Task Manager) after the "edit" stage begins. Open the suite from WSL
   (`./wow-tools.sh`), go to SV Browser, Retail, and choose **Put the originals back**. **Expected:** the edited
   files are back at their original bytes, or the run is refused with "Nothing was changed". The marker is never
   cleared with every file "gone".
2. **F-002, antivirus or OneDrive holding the marker:** this cannot be reliably reproduced. The automated test in
   C-03 stands in for it.
3. **F-005:** on a zip install, run `wow-tools update` against a test release and press Ctrl+C during "Updating".
   **Expected:** the message names the backup folder, and `./wow-tools.sh --version` still works.
4. **F-010:** on Windows with WoW in a folder whose path has `é` or `ü`, start WoW. Open an SV Browser review and
   press **Apply** with something staged. **Expected:** the WoW-running refusal, not "stopped unexpectedly".

## Regression suite
- `python3 scripts/run_tests.py`: 0 failures and 0 errors. The count is at least 1710 plus the tests added.
- `ruff check --no-cache .`: clean.
- `python3 scripts/gen_event_docs.py --check`: exit 0.
- CI matrix (Linux and Windows, Python 3.10 and 3.13): green on the branch.
- Smoke test: `./wow-tools.sh --version` prints `0.1.0`, and `./wow-tools.sh` opens the tool menu. Opening each
  of the five tools reaches its flavor picker.

## Security spot-checks
- **F-003:** before the fix, `journal_flavor.py` (in this review's scratch directory) shows a zip at
  `toolroot/snapshots/snapshot-../elsewhere-<stamp>.zip`. After the fix, the same script prints `snapshots: []`.
- **F-001:** a marker whose `flavor_path` points outside the configured WoW folder (e.g. `/tmp/x/_retail_`) must
  not cause any write under `/tmp/x`. Check `find /tmp/x -newer <marker>` is empty after `recover`.

## Performance spot-checks
- **C-12 (`fsync`):** time `python3 scripts/run_tests.py -k sv_pipeline -j 1` and `-k test_ace_editor -j 1`
  before and after, in one session on the same machine, three runs each, comparing the medians. Report the
  difference. A WSL `/mnt` drive is the worst case.

## Concurrency spot-checks
None of the changes touch threading. Run `python3 scripts/run_tests.py -k parallel` three times in a row; all
three must be green.

## Sign-off

| ID | Tested? | Pass/Fail | Notes |
|---|---|---|---|
| C-01 | | | |
| C-02 | | | |
| C-03 | | | |
| C-04 | | | |
| C-05 | | | |
| C-06 | | | Option A or B: |
| C-07 | | | |
| C-08 | | | |
| C-09 | | | |
| C-10 | | | |
| C-11 | | | |
| C-12 | | | perf delta: |
| C-13 | | | |
| C-14 | | | |
