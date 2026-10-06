# Test plan: wow-tools review fixes (2026-10-04)

Derived from `02_PROPOSED_CHANGES.md`. Each change has at least one automated test. Manual steps cover only what
the suite cannot (Windows cmd.exe, a real PowerShell, a real network release).

## Pre-flight

Run everything from the repo root (`/mnt/d/Profile/Users/Tushar/Documents/GIT/wow-tools`):

```sh
python3 --version                          # >= 3.10
python3 scripts/run_tests.py               # baseline: "Ran 405 tests ... OK" before any change
python3 scripts/gen_event_docs.py --check  # exit 0
python3 -m compileall -q wowtools scripts  # exit 0, no output
```

- No extra installs are needed: stdlib plus `vendor/` only. Tests build temp trees through `tests/fixtures.py`.
  They never use a real WoW install or the network.
- Run a single module verbosely with `python3 -m unittest tests.test_scanner -v`, or filter with
  `python3 scripts/run_tests.py -k enabled`.
- Textual tests must subclass `tests.fixtures.TuiTestCase`.
- Delete or ignore `reviews/` before testing `wow-tools update` on a git checkout. It is untracked, and until C-11
  lands it makes `git status --porcelain` non-empty.

---

## Per-change tests

### C-01: evidence-based "enabled" set
- **Change covered:** C-01 (F-001). An account with no characters never gets `not_enabled`.
- **Setup:** temp tree with `_retail_/Interface/AddOns/{Details,WeakAuras}/<name>.toc` and
  `_retail_/WTF/Account/SOLO/SavedVariables/{Details.lua,WeakAuras.lua,Gone.lua}`, and no realm folders.
- **Steps:**
  1. Add `tests/test_scanner.py::ScannerTest::test_account_without_characters_enables_every_installed_addon`:
     `scan(flavor, account="SOLO")` inside `capture_events()`.
  2. Add `tests/test_rules.py::RulesTest::test_no_characters_proposes_only_not_installed`:
     `evaluate(scan_result, Criteria())`.
  3. `python3 -m unittest tests.test_scanner tests.test_rules -v`
- **Expected:**
  - Test 1: `result.enabled == {"details", "weakauras"}`, and `result.warnings` holds one warning whose message
    contains `no character folders`.
  - Test 2: the proposal has one item, `Gone`, with `reasons == ["not_installed"]`. No item carries
    `not_enabled`.
  - The existing `test_enabled_is_global_union` and `test_all_accounts_unchanged` still pass.
- **Pass / Fail:** Pass if all three hold and both modules are green.

### C-02: no quit while busy; wait for workers before releasing the lock
- **Change covered:** C-02 (F-002).
- **Setup:** a `TuiTestCase` with `build_wow_tree`, `WowToolsApp` opened on the WTF Cleaner, and a fake
  `execute_flavors` patched to block on a `threading.Event`.
- **Steps:**
  1. Add `tests/test_ui_base.py::test_ctrl_q_is_refused_while_busy`: set `app.busy = True`, `await
     pilot.press("ctrl+q")`, `await pilot.pause()`.
  2. In the same test, set `app.busy = False`, then `await pilot.press("ctrl+q")`.
  3. Add `tests/test_suite.py::test_lock_released_only_after_worker_finishes`: an `app_factory` whose `run()`
     enters `activity.running()` on a thread that sleeps 0.2 s, then returns. Record the time of the
     `lock.release` call through a patched `InstanceLock.release`.
- **Expected:**
  1. After step 1, `app.is_running` is still True and a notification with `"A run is in progress"` is in
     `app._notifications`.
  2. After step 2, the app exits.
  3. Release happens at least 0.2 s after the thread starts, and the `session.end` record has
     `waited_for_worker=True`.
- **Pass / Fail:** Pass if all three expectations hold.

### C-03: UI crashes are logged and change the exit code
- **Change covered:** C-03 (F-003).
- **Setup:** a `FakeApp` in `tests/test_suite.py` whose `run()` sets `self.return_code = 1`, plus a TUI test where
  a button handler raises `RuntimeError("boom")`.
- **Steps:**
  1. Add `test_suite.py::test_app_return_code_is_propagated`: call `run([], app_factory=FakeApp, ...)` inside
     `capture_events()`.
  2. Add `test_ui_base.py::test_unhandled_ui_exception_is_logged`: trigger the raising handler with `run_test()`
     and catch the re-raised exception that the pilot surfaces.
- **Expected:**
  1. The return value is `1`, and the `session.end` record has `level == "warning"` and `exit_code == 1`.
  2. The captured events contain `event == "error"` with `data.where == "ui"` and `data.message == "boom"`.
- **Pass / Fail:** Pass if both hold.

### C-04: catch-all in the clean worker
- **Change covered:** C-04 (F-004).
- **Setup:** `test_wtf_app.py` fixture; patch `wowtools.tools.wtf_cleaner.review_screen.execute_flavors` to raise
  `RuntimeError("disk vanished")`.
- **Steps:** add `test_wtf_app.py::test_unexpected_clean_error_is_shown_not_fatal`: open the review screen, press
  `c`, confirm with `y`, then `await pilot.pause()`.
- **Expected:**
  - `app.is_running` is True and `app.busy` is False.
  - The progress screen is gone (`app.screen` is the `ReviewScreen`).
  - A notification contains `stopped unexpectedly` and does **not** contain `Nothing was deleted`.
  - Captured events contain `error` with `where == "clean"`.
- **Pass / Fail:** Pass if all hold.

### C-05: no blocking work on the UI thread
- **Change covered:** C-05 (F-005).
- **Setup:** inject `wow_check=lambda: (time.sleep(0.5), [])[1]` and `locker_check=lambda: []` through
  `tool_options`.
- **Steps:**
  1. Add `test_wtf_app.py::test_preflight_runs_in_a_worker`: press `c`. Within 0.1 s, assert that
     `app.screen` is still `ReviewScreen` and that `#summary` contains `Checking for running programs`. Press `c`
     again (ignored). After `await pilot.pause(0.7)`, assert `ConfirmScreen` is on top, exactly once.
  2. Add `test_flavor_screen.py::test_setup_screen_detects_in_background`: `detect` sleeps 0.3 s. Assert the
     screen mounts immediately with an empty hint, and after a pause the hint starts with `Found:`.
  3. Add `test_ui_base.py::test_update_applies_in_worker`: patch `apply_update` to sleep 0.3 s and return
     `"ok"`. Press `u`, choose Update now, and assert `app.busy` is True during the sleep and the app exits with
     message `"ok"`.
  4. Add `test_screenshot_organizer_app.py::test_flavor_counts_fill_in_after_mount`.
- **Expected:** as stated in each step. No `ConfirmScreen` appears twice.
- **Pass / Fail:** Pass if all four tests are green.

### C-06: cheaper logging
- **Change covered:** C-06 (F-006).
- **Setup:** an `EventLog(tmp)`, a TUI review screen on `build_wow_tree`.
- **Steps:**
  1. Add `test_events.py::test_append_reuses_one_handle_per_file`: emit 100 events and patch `Path.open` to
     count calls.
  2. Add `test_events.py::test_day_rollover_closes_old_handles`: use a `clock` that crosses midnight.
  3. Add `test_wtf_app.py::test_criterion_toggle_logs_no_proposal_items`: after the scan, clear the captured
     records, press `1`, pause, and count `proposal.item` records.
  4. Add `test_wtf_app.py::test_confirmed_clean_logs_selected_items`.
- **Expected:**
  1. `Path.open` is called at most twice (events + text).
  2. Yesterday's handle is closed, the new file is created, and both files have the right lines.
  3. 0 `proposal.item` records after the toggle.
  4. One `proposal.item` per selected group at confirm.
- **Pass / Fail:** Pass if all hold.

### C-07: atomic, single-thread config writes
- **Change covered:** C-07 (F-007).
- **Steps:**
  1. Add `test_config.py::test_save_is_atomic`: patch `os.replace` to raise `OSError` and call `cfg.save()`.
  2. Add `test_config.py::test_save_leaves_no_partial_on_success`.
  3. Add `test_ui_base.py::test_background_check_persists_on_ui_thread`: patch `check_for_update` to record
     `threading.current_thread()` inside `persist`.
  4. Run `python3 -m unittest tests.test_config tests.test_ui_base tests.test_updater_check -v`.
- **Expected:**
  1. `OSError` propagates and the original file content is byte-for-byte unchanged.
  2. No `wow-tools.cfg.partial` remains.
  3. `persist` runs on the main thread.
  4. All green.
- **Pass / Fail:** Pass if all hold.

### C-08: output-folder validation
- **Change covered:** C-08 (F-008, F-029).
- **Steps:**
  1. Add `test_install.py::ValidateOutputDirTest`, parametrized over `None`, `Path("backups")`, `<root>`,
     `<root>/_retail_/WTF/x`, `<root>/_retail_/Interface/AddOns/x`, `<root>/_retail_/Screenshots/x`,
     `<root>/wow-tools/wtf-cleaner` and `<tmp>/elsewhere`.
  2. Add `test_wtf_app.py::test_settings_reject_backup_dir_inside_wtf`: type the path and press Save.
  3. Add `test_wtf_app.py::test_clean_refuses_invalid_stored_backup_dir`: write it straight to the cfg and press
     `c`.
  4. Add `test_screenshot_organizer_app.py::test_rescan_refuses_invalid_stored_dest`.
- **Expected:**
  1. `None` → None. Relative → error containing `full path`. Root/WTF/Interface/Screenshots → error. The last
     two → None.
  2. `#settings-error` shows the message and the cfg is unchanged.
  3. A notification contains `Fix the folder in settings` and no `ConfirmScreen` appears.
  4. Same as 3, with no scan worker started.
- **Pass / Fail:** Pass if all hold.

### C-09: shared dialogs, dedupe, dead code
- **Change covered:** C-09 (F-009, F-023, F-024).
- **Steps:**
  1. `grep -rn "wtf_cleaner" wowtools/tools/screenshot_organizer/` → expect no output.
  2. `grep -rn "def _safe_progress\|def safe_progress\|def _remove\b\|def _discard" wowtools/` → expect only
     `wowtools/core/fsutil.py`.
  3. `grep -rn "is_open\|def changed\|def scope" wowtools/core/journal.py wowtools/core/migrate.py wowtools/tools/wtf_cleaner/rules.py`
     → expect no output.
  4. `grep -rn '"wow-tools"' wowtools/` → expect one definition (`core/journal.py` `TOOLS_SUBDIR`), plus the
     `TOOL_NAME`-style names that are not folder roots.
  5. `python3 scripts/run_tests.py` → all green. The existing TUI tests that query `#clean-stage` and
     `#shots-stage` must pass unchanged.
- **Pass / Fail:** Pass if greps 1-4 match and the suite is green.

### C-10: verified updates
- **Change covered:** C-10 (F-010).
- **Steps:**
  1. Add `test_updater_apply.py::test_zip_with_matching_checksum_applies`: a fake `download` that writes
     zip bytes and `SHA256SUMS` with the correct hash.
  2. Add `test_updater_apply.py::test_zip_with_wrong_checksum_is_refused_and_tree_untouched`.
  3. Add `test_updater_apply.py::test_missing_assets_refused_unless_allowed`.
  4. Add `test_updater_check.py::test_fetch_latest_records_assets`.
- **Expected:**
  - Test 2: `UpdateError` containing `does not match its published checksum`, and the `root` tree has the same
    file list and bytes as before (compare `sha256` over every file). There is no `.update-backup/` folder.
  - Test 3: refused by default, applied with `allow_unverified_updates = true`.
- **Pass / Fail:** Pass if all four are green.
- **Manual (once, at release):** publish `v1.0.1` with the assets, run `./wow-tools.sh update` on a zip install,
  and expect "Updated Ka0s WoW Tools to v1.0.1". Corrupt one byte of a locally served asset (point `LATEST_URL` at
  a local `python3 -m http.server` fixture) and expect a refusal.

### C-11: bounded, non-interactive git updates
- **Change covered:** C-11 (F-011).
- **Steps:**
  1. Add `test_updater_apply.py::test_git_runner_gets_timeout_and_no_prompt_env`: assert `kwargs["timeout"] ==
     120` and `kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"` on every call.
  2. Add `test_updater_apply.py::test_git_timeout_becomes_update_error`: the runner raises
     `subprocess.TimeoutExpired`.
  3. Add `test_updater_apply.py::test_untracked_files_do_not_block_update`: assert the status call includes
     `--untracked-files=no`.
- **Expected:** step 2 raises `UpdateError` containing `timed out`.
- **Pass / Fail:** Pass if all three are green.

### C-12: CI
- **Change covered:** C-12 (F-012).
- **Steps:** push the branch and open the PR.
- **Expected:** the `tests` workflow runs four jobs (ubuntu/windows × 3.10/3.13). Each job's log shows
  `Ran N tests ... OK`, `gen_event_docs --check` exits 0, and `compileall` exits 0.
- **Pass / Fail:** Pass if all four jobs are green.

### C-13: lock-probe leftovers
- **Change covered:** C-13 (F-013).
- **Steps:**
  1. Add `test_scanner.py::test_lock_probe_leftover_is_not_a_stray_copy`: create
     `SavedVariables/Details.lua.wowtools-lockcheck` with no `Details.lua`.
  2. Add `test_cleaner.py::test_execute_recovers_probe_leftover_before_snapshot`.
- **Expected:**
  1. No `SVFile` for the leftover, and one `ScanWarning` mentioning `lock check`.
  2. `Details.lua` exists again with the original bytes, and a `clean.probe_recovered` event is captured.
  3. `python3 scripts/gen_event_docs.py --check` exits 0 after regenerating.
- **Pass / Fail:** Pass if all hold.

### C-14: no-replace rename
- **Change covered:** C-14 (F-014).
- **Steps:**
  1. Add `tests/test_fsutil.py::test_rename_no_replace_refuses_existing_target`: both files exist; expect
     `FileExistsError` and both contents unchanged.
  2. Add `test_rename_no_replace_moves`: src is gone and dst has the content.
  3. Add `test_rename_no_replace_falls_back_without_hardlinks`: patch `os.link` to raise `OSError(EPERM)`.
  4. Add `test_screenshot_organizer_organizer.py::test_target_created_between_check_and_rename_is_not_overwritten`:
     inject a `rename` that creates `dst` first.
- **Expected:** as stated. In step 4, the outcome kind is `conflict` and the pre-existing `dst` bytes are intact.
- **Pass / Fail:** Pass if all are green.

### C-15: guarded organizer journal parsing
- **Change covered:** C-15 (F-015).
- **Steps:** add `test_screenshot_organizer_undo.py::test_null_size_entry_is_skipped`: write a journal whose second
  entry has `"size": null`, then call `latest_undoable(dir)` and `read_journal(path)`.
- **Expected:** no exception. The entry is dropped, and the other entries remain.
- **Pass / Fail:** Pass if both hold.

### C-16: confined organizer undo destinations
- **Change covered:** C-16 (F-016).
- **Steps:** add `test_screenshot_organizer_undo.py::test_dst_outside_target_root_is_refused`: a journal entry with
  `dst = <tmp>/elsewhere/2020/01/01/WoWScrnShot_010120_101010.jpg` and a matching file there.
- **Expected:** the outcome is `undo_skipped`, with reason `outside the WoW folder or not a date folder`, and the
  file at `elsewhere` still exists.
- **Pass / Fail:** Pass if both hold.

### C-17: retryable organizer undo
- **Change covered:** C-17 (F-017).
- **Steps:** add `test_screenshot_organizer_undo.py::test_all_failed_keeps_journal_undoable`: every filed copy
  removed from disk, then run `undo`.
- **Expected:** `result.marked_undone is False`, the journal has no `undone` line, and
  `latest_undoable(dir) == journal_path`.
- **Pass / Fail:** Pass if all hold.

### C-18: update-backup pruning (in-scope part)
- **Change covered:** C-18 (F-018, partial).
- **Steps:** add `test_updater_apply.py::test_update_backup_keeps_newest_two`: pre-create
  `.update-backup/{0.9.0,0.9.1,0.9.2}`, then apply a zip update from 1.0.0.
- **Expected:** `.update-backup` contains `0.9.2` and `1.0.0` only.
- **Pass / Fail:** Pass if exact.

### C-19: only replace shipped files
- **Change covered:** C-19 (F-019).
- **Steps:** add `test_updater_apply.py::test_user_markdown_in_root_survives_zip_update`: create `root/my-notes.md`;
  the staging zip ships `README.md` only.
- **Expected:** `my-notes.md` is still in `root` with the same bytes, and `README.md` holds the new content.
- **Pass / Fail:** Pass if both hold.

### C-20: cmd launcher safe to replace while running
- **Change covered:** C-20 (F-020). Manual, Windows only.
- **Setup:** a Windows 10/11 machine with `py` installed and a copy of the repo.
- **Steps:**
  1. `wow-tools.cmd --version`, then `echo %ERRORLEVEL%` → expect `1.0.x` and then `0`.
  2. `wow-tools.cmd bogus`, then `echo %ERRORLEVEL%` → expect `Unknown command: bogus.` and then `1`.
  3. Simulate the replacement: run `wow-tools.cmd update --check` while a second shell overwrites
     `wow-tools.cmd` with a version that has an extra 200-character `rem` line at the top. Do this while Python is
     running, for example by adding `input()` temporarily, or by using a debugger breakpoint.
- **Expected:** steps 1-2 as stated. In step 3, no `'…' is not recognized` error appears after Python exits, and
  the exit code is unchanged.
- **Pass / Fail:** Pass if all three hold.

### C-21 .. C-26: small fixes
| ID | Test to add | Expected |
|---|---|---|
| C-21 | `test_lock.py::test_platform_uses_is_wsl` (patch `is_wsl` → True, `platform.release` → `"6.6-generic"`) | `_platform() == "wsl"` |
| C-22 | `test_cleaner.py::test_clean_error_instances_do_not_share_lists` | `CleanError("a").restored is not CleanError("b").restored` |
| C-23 | `test_process.py::test_unknown_processes_listed_once_for_many_flavors` | labels for two flavors + one pathless process = `["Wow.exe (flavor unknown)"]` exactly once |
| C-24 | `test_updater_check.py::test_future_last_check_is_ignored` (last = now + 2 days) | the fetch runs once and `last_update_check` is reset to now |
| C-26 | `test_safety.py::test_same_second_snapshot_gets_suffix` (two `take_snapshot` with the same `now`) | two files, `backup-retail-<stamp>.zip` and `backup-retail-<stamp>-2.zip`; `prune_snapshots(keep=1)` keeps `-2` |

---

## Regression suite
1. `python3 scripts/run_tests.py` → `Ran N tests ... (0 failures, 0 errors, 0 skipped)`, where N ≥ 405 + the new
   tests.
2. `python3 -m unittest discover -s tests -t . -v 2>&1 | tail -3` → `OK` (serial run, which catches shard-order
   dependence).
3. `python3 scripts/gen_event_docs.py --check` → exit 0.
4. `python3 -m compileall -q wowtools scripts` → exit 0.
5. `./wow-tools.sh --version` prints the version; `./wow-tools.sh --help` lists both tools; `./wow-tools.sh bogus`
   exits 1.
6. Manual happy path on a **copy** of a WTF folder (never the live install). Point `[general] wow_path` at the
   copy.
   - Open the WTF Cleaner and choose Retail, then All accounts. Dry run (`y`) and confirm: the result says
     "Would delete N files" and nothing is deleted.
   - Clean (`c`) and confirm: the result shows "Post-clean check: passed".
   - Undo (`z`) and confirm: the result shows "Restored N files".
   - Open the Screenshot Organizer and choose All flavors. Organize (`o`): files move to `YYYY/MM/DD`. Undo
     (`z`): the files are back.
7. Lock check: start `./wow-tools.sh` in two terminals. The second shows the lock screen; `q` quits it. Close the
   first with `q` and check that `wow-tools.lock` is gone.

## Security spot-checks
- **F-010:** with a local release fixture, serve a zip whose `SHA256SUMS` line differs by one hex digit, and run
  `apply_update` against it. **Before:** the update applies. **After:** `UpdateError` and an untouched tree.
- **F-016:** a crafted organizer journal pointing `dst` at `<tmp>/victim/2020/01/01/WoWScrnShot_010120_000000.jpg`
  (copy action, sizes matching). **Before:** Undo deletes the victim file. **After:** `undo_skipped` and the file
  survives.
- **F-011:** a runner fake that blocks forever on `fetch`. **Before:** the test hangs (use
  `timeout 30 python3 -m unittest ...` to see it). **After:** `UpdateError("... timed out")`. The 120 s timeout is
  patched to 0.1 s in the test.

## Performance spot-checks
- **F-006, logging cost:**
  ```sh
  PYTHONPATH=.:vendor python3 -c "
  import time; from pathlib import Path; from wowtools.core.events import EventLog
  log=EventLog(Path('./.bench-logs')); t=time.perf_counter()
  [log.emit('ui.item_toggled', key='x'*40, checked=True) for _ in range(500)]
  print(round((time.perf_counter()-t)*1000),'ms'); import shutil; shutil.rmtree('./.bench-logs')"
  ```
  Baseline on this WSL/drvfs checkout: **1378 ms**. Target after C-06: **≤ 150 ms** on the same drive.
- **F-006, toggle latency:** in `test_wtf_app.py`, build a fixture with 500 stray files, then time `press("1")` +
  `pause()` before and after. Target: no `proposal.item` writes, and at least 5× faster on drvfs.
- **F-005, confirm latency:** with `wow_check` sleeping 2 s, the time from the `c` keypress to the next screen
  refresh (`pilot.pause(0)`) should be < 100 ms after C-05 (currently ≥ 2 s).

## Concurrency spot-checks
- **F-002:** run the C-02 tests 50 times: `for i in $(seq 50); do python3 -m unittest tests.test_suite -k
  worker_finishes || break; done` → no failures.
- **F-007:** stress test `test_config.py::test_concurrent_set_and_save_never_corrupts`. Two threads, 1 000
  iterations each: one calls `cfg.set(...); cfg.save()` on the UI path through the injected persist callback, the
  other loads the file. Every load must parse (no `ConfigError`).
- **Full suite under parallel shards:** `python3 scripts/run_tests.py -j 16`, three runs in a row → all green.

---

## Sign-off

Closed 2026-10-06: filled from the fix ledger (`docs/superpowers/plans/2026-10-04-review-fixes.status.md`). Branch `fix/review-2026-10-04` (`6e9ac1f..fcdb5ac`, f56d881 to fcdb5ac, 37 commits) was merged to master in 96c3527. Full suite at merge: 548 tests green (2 skipped, the Windows-only launcher tests).

| ID | Tested? | Pass/Fail | Notes |
|---|---|---|---|
| C-01 | yes | Pass | 8dc6ee6 (F-001); `build_solo_tree` tests |
| C-02 | yes | Pass | cdfd2b0 (F-002); `ui.quit_refused`, worker wait before `lock.release()` |
| C-03 | yes | Pass | 0d76992 (F-003); return code propagated, UI crashes logged |
| C-04 | yes | Pass | a837a00 (F-004) |
| C-05 | yes | Pass | 74ef45f (F-005), ddfd611 (R2: selection frozen during the check); confirm latency 2110 ms before, 86 ms after |
| C-06 | yes | Pass | 7573f8f (F-006); 500 events on drvfs 1385 ms before, 85-88 ms after; toggle writes no `proposal.item` |
| C-07 | yes | Pass | fe6182f (F-007); 1000-save stress test (skips on Windows) |
| C-08 | yes | Pass | 637d7cd (F-008, F-029) |
| C-09 | yes | Pass | 0ff9693 (F-009, F-023, F-024); `tests/test_structure.py`, greps 1-4 match |
| C-10 | yes | Pass | f387a49 (F-010); a real release publish is left to the first release |
| C-11 | yes | Pass | 8ccd54f (F-011), ddfd611 (R2: process-tree kill on timeout, ssh settings respected) |
| C-12 | yes | Pass | 17e2ad3, 11d9399 (F-012); final CI run 37157279879 green on all four jobs |
| C-13 | yes | Pass | 537a704 (F-013), 91b8cd5 (R1: every SavedVariables folder in scope) |
| C-14 | yes | Pass | 4531d88 (F-014); call sites pinned by `tests/test_no_replace_call_sites.py` (91b8cd5) |
| C-15 | yes | Pass | fd6588c (F-015) |
| C-16 | yes | Pass | fd6588c (F-016) |
| C-17 | yes | Pass | fd6588c (F-017), 91b8cd5 (R1), 6e33781 (R3) |
| C-18 | yes | Pass | update-backup pruning only; `keep_cleaned` deferred. 2254dac (F-018), ddfd611 (R2: downgrade keeps the current folder) |
| C-19 | yes | Pass | 2254dac (F-019) |
| C-20 | yes | Pass | manual, Windows. e105a6e (F-020); `tests/test_launcher.py` run natively through `py -3` (exit codes 0/1/10, launcher rewritten mid-run) |
| C-21 | yes | Pass | f991fb8 (F-021) |
| C-22 | yes | Pass | 537a704 (F-022) |
| C-23 | yes | Pass | b45d431 (F-025) |
| C-24 | yes | Pass | 8ccd54f (F-026) |
| C-26 | yes | Pass | 4531d88 (F-028) |
