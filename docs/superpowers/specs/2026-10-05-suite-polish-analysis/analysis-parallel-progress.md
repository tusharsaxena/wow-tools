## Long-running tasks, parallelism and the progress popup: current state

### 1. How background work runs today

- **Threads only.** Every long job is a Textual thread worker: `self.run_worker(fn, thread=True, exclusive=True, group=...)`. Nothing uses `concurrent.futures` or `ThreadPoolExecutor`. The only `threading` users in the repo are `core/activity.py:14` (a `Condition` counter) and `core/events.py:188` (a log lock).
- **Worker sites (file-changing):**
  - WTF Cleaner: `wtf_cleaner/review_screen.py:666` `_clean_worker` (group `clean`) and `:797` `_undo_worker`.
  - Screenshot Organizer: `screenshot_organizer/review_screen.py:533` `_job_worker` (group `organize`), used for runs and undo (`:614`).
  - Interface Backup: `interface_backup/review_screen.py:676` `run_job`/`_job_worker` (group `job`), used for backup (`:659`), restore (`:804`) and undo (`:859`).
  - Ace3 Profile Manager: `ace3_profile_manager/review_screen.py:1261` `_apply_worker` (group `run`), `:1374` `_undo_worker`, `:1434` `_recover_worker`.
- **Worker sites (read-only):**
  - Scans: `wtf_cleaner/review_screen.py:212`, `screenshot_organizer/review_screen.py:221`, `interface_backup/review_screen.py:318`, `ace3_profile_manager/review_screen.py:386`, `ace3_profile_manager/blacklist_screen.py:113`.
  - Preflight WoW-running checks (group `preflight`): `wtf_cleaner/review_screen.py:581`, `interface_backup/review_screen.py:594`, `ace3_profile_manager/review_screen.py:1156`.
  - Picker counts: `screenshot_organizer/app.py:140` `_count_worker` and `interface_backup/app.py:147` `_notes_worker`.
  - Interface Backup: `restore_screen.py:124` and `:232`, and `review_screen.py:450` `_parts_worker`.
  - Setup: `ui/setup_screen.py:74` `_detect_worker`.
- **Common job pattern** (for example `wtf_cleaner/review_screen.py:655-696`):
  1. Set `app.busy = True`.
  2. Push the tool's `ProgressScreen` subclass.
  3. In the worker, run `with activity.running(): result = job(progress)`.
  4. `progress` is a closure that calls `self.app.call_from_thread(screen.update_progress, *args)`.
  5. On finish, `call_from_thread(self._done / _failed / _crashed)`. These pop the progress screen (`_close_progress`), clear `busy` and push a result screen or `notify(severity="error")`.
- **`call_from_thread` blocks.** In `vendor/textual/app.py:1833-1837` it is `run_coroutine_threadsafe(...).result()`, so the worker waits for the UI thread on every report. Several parallel workers reporting per file would all queue on the UI loop.
- **Throttling is uneven:**

  | Where | Throttle |
  |---|---|
  | Interface Backup jobs | `ThrottledProgress` (`interface_backup/review_screen.py:55-90`, `PROGRESS_INTERVAL = 0.1`). It forwards on a stage change, total 0, `current >= total`, or once per interval; `reset()` runs per flavor. |
  | Ace3 scan | Inline throttle, `PROGRESS_EVERY = 0.05` (`ace3_profile_manager/review_screen.py:58`, `blacklist_screen.py:31`) |
  | WTF Cleaner clean/undo, Screenshot Organizer run/undo, Ace3 apply/undo (`_progress_cb`, `:1139`) | None: one `call_from_thread` per file |

  `ThrottledProgress` is private to Interface Backup and keeps unsynchronised state (`_stage`, `_last`, `_fresh`), so it is not safe to share between threads.
- **Cancellation: none.** `ProgressScreen` (`ui/dialogs.py:338`) has no bindings and no buttons, and the jobs have no stop token. Quitting is refused while busy: `Ka0sApp.action_quit` (`ui/base.py:113-121`) logs `ui.quit_refused`. On exit, `suite.py:103-106` calls `activity.wait_idle(WORKER_WAIT_S=600)` (`suite.py:27`) before releasing the lock. Ctrl+C mid-zip is handled by `except BaseException: remove_quietly(partial)` in `core/snapshot.py:74` and `interface_backup/backup.py:194`.
- **Error handling:**
  - Logic layers raise domain errors: `BackupError` (`core/backup.py:17`), `CleanError`, `OrganizeError`, `ApplyError`/`WowRunning`, `RestoreError`, `UndoError`.
  - Workers catch the expected error and route it to a UI handler. They then catch bare `Exception`, call `log_exception`, and show a "stopped unexpectedly" toast (for example `wtf_cleaner/review_screen.py:686-729`, `ace3_profile_manager/review_screen.py:1274-1283`).
  - `fsutil.safe_progress` (`core/fsutil.py:105`) swallows exceptions raised inside progress callbacks.
  - Anything that escapes reaches `Ka0sApp._handle_exception` (`ui/base.py:103`), which logs it.

### 2. Loops over independent units, per tool

#### WTF Cleaner (`tools/wtf_cleaner/`)

- **Scan:** `multi.scan_flavors` (`multi.py:32-48`) loops flavors serially. Each call to `scanner.scan(flavor)` (`scanner.py:237`) is read-only and per flavor, and a `ScanError` is caught per flavor. This is safe to parallelise. The progress label is prefixed with `"{flavor} · "`.
- **Clean / dry run:** `multi.execute_flavors` (`multi.py:113-160`) loops `for index, run in enumerate(result.runs)` and calls `cleaner.execute(...)` (`cleaner.py:216`) per flavor. It is not trivially independent:
  - **One shared run journal.** A single `CleanJournal` (`new_journal_path(journal_dir)`, `multi.py:127`) is passed to every flavor's `execute()`. `core/journal.JournalWriter` (`core/journal.py:58-115`) has no lock: `_write` does `handle.write` and `flush`, and `count += 1` is unsynchronised. Undo reads the entries reversed (`wtf_cleaner/undo.py:182-200`). Order across flavors does not matter for correctness because entries are per file, but the writes must be serialised.
  - **One shared safety marker per backup folder.** `_take_safety_snapshot` (`cleaner.py:162-194`) refuses when `read_marker(backup_dir)` finds a marker, then writes `backup_dir/clean-in-progress.json` (`safety.py:26`, `write_marker` `:58`). The marker holds a single flavor and snapshot. Two flavors cleaning at once would refuse each other or overwrite the only recovery pointer. `RecoveryScreen` (`wtf_cleaner/review_screen.py:60`) shows only one marker.
  - **Shared destination folders, but per-flavor file names.** Snapshots go to `<backup_dir>/backup/backup-<flavor>-<stamp>.zip`, and cleaned/dry-run zips go to `<backup_dir>/cleaned/...` (`cleaned_zip_path`, `cleaner.py:329`). Names are unique per flavor (and account), and `free_name` (`core/fsutil.py:85`) does a lexists check. `rename_no_replace` makes a collision fail instead of overwrite. Pruning is per flavor (`prune_snapshots`, `prune_dry_run_zips` `:338`), so it is safe.
  - **Stop-on-first-failure semantics.** A `BackupError` or `CleanError` breaks the loop (`multi.py:139-145`). The `not_started` list and the `clean.flavors_stopped` event (fields `done`, `not_started`) assume serial order. `MultiCleanResult.stopped` returns only one stopped flavor. `ResultScreen` and the `_clean_failed` text ("Not started: …", `review_screen.py:708-711`) rely on this.
  - **Rollback is per flavor.** `_restore_after` puts back from that flavor's snapshot, then clears the shared marker (`cleaner.py:197-211`).
- **Undo:** `undo_clean` (`undo.py:182-200`) loops journal entries in reverse, uses one shared `_Zips` cache (not thread-safe) and calls `mark_undone` once at the end. It could be split per flavor, but it is cheap (extracting single files).

#### Screenshot Organizer (`tools/screenshot_organizer/`)

- **Scan:** `planner.scan` (`planner.py:162-226`) loops flavors and shares a `targets` dict cache. It is read-only and cheap (listings only).
- **Run:** `organizer.execute` (`organizer.py:256-300`) is a single loop over all items across flavors. `_Run` holds shared caches (`sources`, `targets`, `made`, `organizer.py:164-174`) and one `JournalWriter`. Per-flavor targets are disjoint (`settings.target_root` returns `<dest>/<flavor folder>` or the flavor's own Screenshots folder, `settings.py:42`), so the work is independent by flavor. Splitting would still need per-flavor `_Run` instances and a locked journal.
  - Move mode on the same volume is just `rename`, so parallelism gains little. Copy mode (`copy_verified`, SHA-256) is I/O-bound and would benefit.
  - A `JournalWriteError` must stop the whole run (`organizer.py:283-285`); under parallelism that means stopping sibling workers.
- **Picker count:** `_count_worker` (`app.py:143-147`) runs a per-flavor `waiting_count` serially. These are independent reads.

#### Interface Backup (`tools/interface_backup/`)

This is the best candidate.

- **Scan:** `scanner.scan_flavors` (`scanner.py:144-164`) runs `scan_flavor` serially: two parts (Interface, WTF) per flavor, `walk_files`. It is read-only and each flavor is independent. Logging happens per flavor.
- **Backup:** `backup.back_up_all` (`backup.py:238-247`), `for scan in scans: back_up(scan, root, ...)`.
  - Each flavor gets its own zip at `root/backup-<flavor>-<stamp>.zip` (`catalog.new_backup_path`, `catalog.py:44`). It is written through `.partial` and moved with `rename_no_replace`.
  - Pruning is per flavor and protects the new zip (`prune_backups`, `catalog.py:105`).
  - There is no journal ("Nothing in the game folders changes, so there is no journal", `backup.py:1-2`).
  - One flavor failing never stops the next: `back_up` returns `BackupOutcome(kind="failed")` (`backup.py:220-224`).
  - These units are truly independent.
  - The only shared item is the `on_flavor` announcement plus `ThrottledProgress.reset()`, which drive one progress screen.
  - Disk-space preflight is aggregated (`free_bytes(root, ...)`, `review_screen.py:645`).
- **Restore / undo:** single flavor (`restore.restore(plan, ...)`). Parts are swapped in order with journal entries (`replace_part`, `restore.py:390`; `_prune` `:446`). Not a candidate: ordering and atomic swap semantics matter.

#### Ace3 Profile Manager (`tools/ace3_profile_manager/`)

- **Scan:** `scanner.scan_flavors` (`scanner.py:194`) runs `scan_flavor` (`:120-168`) over accounts, owners and files, calling `_read_one` (`:170`). `_read_one` uses `read_bytes` then `luasv.parse`, which is pure-Python Lua parsing and CPU-bound. Under the GIL, threads give little gain here; only processes would.
- **Apply:** `multi.apply_flavors` (`multi.py:104-148`) loops `for run, (flavor, states) in zip(...)` and calls `editor.apply_flavor` (`editor.py:209`). It has the same blockers as WTF Cleaner:
  - One `ProfileJournal` for the run (`multi.py:117`).
  - One crash marker `root/edit-in-progress.json` (`editor.py:36`, `write_marker` `:108`, `_refuse_unfinished` `:196`).
  - A single-marker recovery screen (`ProfileRecoveryScreen`, `review_screen.py:101`).
  - `break` on the first `ApplyError` (`multi.py:127-133`).
  - Global `prune_edited_zips`/`prune_journals` after the loop.
  - Per-flavor parts: snapshot at `root/snapshots/snapshot-<flavor>-<stamp>.zip` (`editor.py:250`), edited zip `edited_zip_path` (`:135`), and per-flavor `prune_snapshots` (`:298`).
- **Undo:** `undo.undo_run` (`undo.py:162-205`) runs `for flavor in flavors: result.snapshots.append(_snapshot(...))` (`:174-175`). The per-flavor WTF snapshots are independent zips and could run in parallel. The file restore loop that follows is cheap and must come after all snapshots succeed (any failure means "Nothing was changed"). `_prune` (`:152`) is per flavor.

#### Core zipping cost (shared)

`core/snapshot.take_snapshot` (`core/snapshot.py:37-77`) and `core/backup.create_backup` (`core/backup.py:156`) do DEFLATE writes plus `verify_backup` (a full re-read, `core/backup.py:200`). zlib and file I/O release the GIL, so whole-WTF snapshots and Interface zips gain real throughput from threads. The typical setup is a Windows drive under WSL (drvfs, noted slow in `events.py:8-10`) or a single HDD, where parallel I/O can be slower. The default factor should therefore be conservative.

### 3. ProgressScreen (`ui/dialogs.py:338-392`)

- **Layout:** `Vertical.progress-box` contains:
  - `Static.progress-stage` (stage title),
  - `ProgressBar.progress-bar` (`show_eta=False`),
  - `Static.progress-file` (detail).
- **CSS (`:347-354`):**
  - `ProgressScreen { align: center middle; }`
  - `.progress-box { POPUP_WIDTH; height: auto; border: thick $accent; background: $panel; padding: 1 2; }`, where `POPUP_WIDTH = "width: 90; max-width: 90%;"` (`dialogs.py:31`).
  - `.progress-stage { color: $accent; text-style: bold; margin-bottom: 1; }`, with no fixed height.
  - `.progress-bar { width: 1fr; }`. Textual's inner `Bar` is fixed at `width: 32` and `PercentageStatus` at `width: 5` (`vendor/textual/widgets/_progress_bar.py:41-56, 152-156`), so the bar never fills the box.
  - `.progress-file { color: $text-muted; margin-top: 1; height: 2; overflow: hidden hidden; }`
- **API:**
  - `update_progress(stage, current, total, detail)` rewrites the stage text, calls `bar.update(total=total or None, progress=current)` (total 0 means an indeterminate animation) and sets the detail.
  - `set_flavor(label)` prefixes `"<label>: "`.
  - `stage_title` maps through `STAGE_TITLES`; a dry run's `SIMULATED_STAGE` shows "Simulating".
- **Subclasses:**

  | Subclass | Location | `ID_PREFIX` | `SIMULATED_STAGE` |
  |---|---|---|---|
  | `CleanProgressScreen` | `wtf_cleaner/review_screen.py:49` | `clean` | `delete` |
  | `ShotProgressScreen` | `screenshot_organizer/review_screen.py:40` | `shots` | `organize` |
  | `BackupProgressScreen` | `interface_backup/review_screen.py:98` | `ibackup` | none |
  | `ProfileProgressScreen` | `ace3_profile_manager/review_screen.py:95` | `ace` | `check` |

- **Stage titles:** `wtf_cleaner/report.py:56-67` (10 stages: check, lock_check, snapshot_list, snapshot, snapshot_verify, backup, verify, delete, validate, undo), `interface_backup/report.py:17-21`, `ace3_profile_manager/report.py:16-21`, `screenshot_organizer/report.py:41`.
- **Flavor labels:**
  - WTF Cleaner shows `"Retail (1/3)"` only when `self.multi` (`review_screen.py:675-678`).
  - Ace3 calls `set_flavor(flavor.display_name)` on every report (`review_screen.py:1140-1145`).
  - Interface Backup labels via `on_flavor`.
- **Tests that pin it:** `tests/test_look_and_feel.py:461-482` (`test_popups_keep_a_readable_width_at_large`: popup at most `POPUP_MAX_WIDTH`, centred at BASE and LARGE), `tests/test_dialogs.py:29-41` (stage titles and the `set_flavor` prefix), `tests/test_structure.py:61-71` (subclassing, one definition), `tests/test_interface_backup_app.py:541-636`.

**Why it "jumps":**

1. **Height:** the box is `height: auto` and the stage `Static` has no fixed height. A long `"<flavor> (i/n): <title>"` wraps to two lines at 80 columns or narrow windows. Content width at 80x24 is about 72 − 2 (border) − 4 (padding) = 66 columns, which titles like "Classic Era (2/3): Checking the result against the WTF backup" approach. The popup then grows and shrinks.
2. **Width:** `max-width: 90%` makes width follow the terminal below 100 columns. That is stable at a fixed size, but it is not a fixed box.
3. **The bar resets on every stage.** Each stage has its own total: snapshot_list is indeterminate, then snapshot 0→N, verify 0→N, backup, verify, delete. The bar swings between indeterminate, 100% and 0% several times per flavor, and again for each flavor. There is no overall progress.
4. **Text flicker:** the stage and flavor text change on every flavor, and the detail line updates on every file (no throttle in three tools).
5. **Pop/push between popups:** confirm → progress → result. The popup is popped on finish (`_close_progress`) and the result appears as a full screen.

In a parallel run, interleaved per-flavor reports to one stage line would flip the title and bar between flavors. That is the worst case of jumpiness. The screen needs either one row per running unit or an aggregate overall bar.

### 4. Config: where a parallelism setting goes

- **`core/config.py`:**
  - `GENERAL = "general"` (`:24`).
  - Retention defaults: `DEFAULT_KEEP_BACKUPS = 10`, `DEFAULT_KEEP_JOURNALS = 10` (`:29-30`).
  - `RETIRED_TOOL_KEYS` (`:32`).
  - `Config` API: `load/save/save_if_exists`, `get/get_int/get_bool/set/remove/remove_retired/get_path/set_path`.
  - `[general]` properties: `wow_path`, `last_flavor`, `check_for_updates`, `auto_update`, `allow_unverified_updates`, `log_level`, `log_retention_days` (`max(1, …)`), `keep_backups` (`:201-205`, negative → default) and `keep_journals` (`:207-210`, `max(1, …)`).
  - `save()` is UI-thread only (docstring `:104-105`). `set()` logs `config.changed`.
- **New setting:** add a `DEFAULT_PARALLELISM` constant and a `Config.parallelism` property beside `keep_journals`, with a clamp such as `max(1, min(N, value))`.
- **Setup screen (`ui/setup_screen.py`):**
  - Fields: `#wow_path`, `#keep-backups` (`:57-58`), `#keep-journals` (`:59-60`), `#setup-error`, Save/Cancel `ButtonRow`.
  - Validation is in `_count(widget_id, least)` (`:124-129`) and `_save` (`:131-151`), which sets `source="wizard"|"settings"`.
  - Add a `Label` plus `Input(type="integer", id="parallelism")` after `keep-journals`, validated with `_count("parallelism", 1)` and an upper bound.
  - The form must keep Save visible at 120x30 (class docstring `:24-25`; checked by `tests/test_look_and_feel.py` and `tests/test_suite_app.py`/`test_ui_base.py`, which reference `SetupScreen`).
- **Docs to update:** `docs/architecture.md:47-50` (the `[general]` retention paragraph), `docs/adding-a-tool.md:26-27`, and each tool doc's settings section.
- **Passing it in:** the logic functions take explicit params (for example `keep_backups=`, `keep_journals=`), so a `workers: int = 1` param on `back_up_all`, `execute_flavors`, `apply_flavors` and `scan_flavors` matches the pattern. The UI would read `self.cfg.parallelism` on the UI thread before starting the worker, as it already does for `keep`.

### 5. Thread-safety of logging and shared state

- **`core/events.EventLog`:**
  - `_append` holds `self._lock` (`events.py:188`, `:229-247`) for opening, writing, flushing and disabling sinks, and `close()` takes it. Concurrent `log_event` from several workers is therefore safe at line level.
  - `emit` builds the record outside the lock: `REGISTRY.get` is read-only, `self.records.append` is atomic in CPython, and the `_clock()` timestamps may be slightly out of order across threads.
  - `set_context(tool=...)` mutates `self.tool` globally (not per thread). That is fine because only one tool runs at a time.
  - `_current` is swapped by `init_event_log` and `capture_events` (tests) without a lock.
  - Each line is flushed (about 2.75 ms per open noted for drvfs), so the lock can become a contention point under per-file logging from N threads. WTF Cleaner and Screenshot Organizer log one event per file (`_log_outcome`, `clean.undo_*`).
- **`core/activity`:** a `Condition`-guarded counter, safe for N nested `running()` calls.
- **Journals:**
  - `core/journal.JournalWriter` is not thread-safe: there is no lock around `_write`, `count`, or the lazy `open()` in `add_entry`.
  - Tool wrappers (`CleanJournal`, `ProfileJournal`, the Screenshot Organizer journal) inherit this.
  - `append_record`/`mark_undone` open and close per call.
  - Parallel writers would need a lock in `JournalWriter` or per-flavor journals. Per-flavor journals would break "Undo uses the newest journal" and `latest_undoable` (`core/journal.py:174`), which offers only the single newest one.
- **Markers:** WTF Cleaner `clean-in-progress.json` per backup folder and Ace3 `edit-in-progress.json` per root are singletons, so they are a hard blocker for running flavors in parallel in those two tools.
- **`free_name`/`new_journal_path`:** check-then-create (TOCTOU). It is safe in practice because names include the flavor, and `rename_no_replace` or `open("x")` fail instead of overwriting.
- **Config:** `Config.save` is UI-thread only. Workers must not write config.
- **UI:** the progress widgets must only be touched through `call_from_thread`. Because it blocks, per-file reports from N workers serialise on the UI loop; parallel runs need throttling or aggregation before the UI hop.

### 6. Related observations (outside this area)

- **`ConfirmScreen(default_yes=...)`** is the relevant setting for the "default to yes" request:

  | Call site | Default |
  |---|---|
  | WTF Cleaner clean (`wtf_cleaner/review_screen.py:646`) | `default_yes=dry_run`, so No for a real clean |
  | WTF Cleaner undo (`:784`) | No |
  | Screenshot Organizer undo (`screenshot_organizer/review_screen.py:607`) | No |
  | Interface Backup backup (`interface_backup/review_screen.py:651`) | Yes |
  | Interface Backup restore and undo (`:785`, `:838`) | No |

- **`SNAPSHOT_NAME`** (`wtf_cleaner/safety.py:29`) is still defined and unused, which confirms the earlier note. Removing it lets `import re` go too, if nothing else in `safety.py` uses `re`.

### Open questions / decisions

1. **Scope of "parallel":** I suggest the first pass covers only units that are truly independent and safe: Interface Backup (scan and `back_up_all`), plus the read-only scans in all four tools (WTF Cleaner, Interface Backup, Ace3 and the Screenshot Organizer picker counts). Should WTF Cleaner clean and Ace3 apply also run per flavor in parallel? That needs per-flavor crash markers (a new file naming, plus recovery screens that handle several markers), a locked shared journal, and new stop semantics.
2. **Failure semantics under parallelism:** today WTF Cleaner and Ace3 stop the remaining flavors on the first `BackupError`/`ApplyError` ("Not started: …"). In parallel, should in-flight siblings finish, or be stopped cooperatively (needs a cancel token)? Should flavors still queued be skipped?
3. **Unit of parallelism:** flavors only, or also accounts, characters, files? Accounts share one WTF snapshot per flavor, and the snapshot covers the whole WTF folder, so parallelism below flavor level gives little benefit at a high complexity cost. Recommend flavor level only.
4. **Setting:** name and key (`[general] parallelism` / `max_parallel`), default (1 = today's behaviour, or 2?), max (2/4/CPU count?), and whether 0 means "auto". Is it a setup-screen field on the shared `[general]` form (one more row; Save must still fit at 120x30)?
5. **Disk reality:** on a single HDD or a WSL drvfs mount, parallel zipping can be slower. Should we document "raise only on SSD", or detect and clamp?
6. **Progress popup design:** for a fixed width and height, choose between one row per running unit (flavor label, stage, bar) with a fixed number of rows equal to the parallelism, and one overall bar ("3 of 5 flavors · 42%") with a fixed-height detail area. Should the stage line be truncated with an ellipsis instead of wrapping? Should the bar span the full width (override `Bar { width: 32 }`)? Should the popup be fixed for serial runs too, so every tool looks the same?
7. **Overall progress:** add a whole-run bar (units done / total) on top of the per-stage bar, so the bar stops resetting at each stage?
8. **Cancellation:** add a Cancel/Esc on the progress popup, so a run stops at the next safe point and rollback rules stay as they are? Today there is none.
9. **Journals:** keep one journal per run with a lock (Undo stays "the newest run"), or move to per-flavor journals (which changes Undo's meaning and `keep_journals` counting)? Recommend one journal with a lock.
10. **Shared throttling:** promote `ThrottledProgress` (Interface Backup) into the planned shared component library (`ui/` or `core/`), make it thread-safe, and use it in every tool?
11. **Ace3 scan:** its Lua parsing is CPU-bound. Accept no real gain from threads, or use processes (more complexity, Windows spawn cost)? Recommend leaving it serial.
12. **Log volume:** per-file events from N threads all contend on one flushed lock. Is it acceptable to keep per-file events at debug, or batch them?