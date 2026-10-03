# Proposed changes: wow-tools full review (2026-10-04)

Derived from `01_FINDINGS.md`. Change IDs are `C-NN`; each lists the finding IDs it closes.

## HLD: themes

### T1. Make the cleaner never call an addon "not enabled" without evidence (F-001)
**Rationale:** the criterion is pre-ticked and deletes user data, so lack of evidence must count as "enabled".
This is the same rule the scanner already applies to a character without `AddOns.txt`.
**Alternative considered:** compute "enabled" per account and compare each group with its own account. This is
more precise, but in all-accounts scans it would propose *more* deletions than today's global union, so it is a
behavior change. Rejected for this cycle and listed as a follow-up.
**Trade-off:** an account with no character folders gets no `not_enabled` proposals. That is acceptable:
`not_installed`, `older_than` and `stray_copies` still apply.

### T2. A safe lifecycle for long-running work (F-002, F-003, F-004)
**Rationale:** file-changing work runs in threads, and the app has to (a) refuse to exit while that work runs,
(b) turn every unexpected worker error into a visible, logged outcome, and (c) report a crash as a crash.
**Alternatives considered:** making worker threads daemon threads (rejected: a daemon thread killed at exit
causes exactly the half-done state we want to avoid), and joining workers in `suite.run` before releasing the lock
(kept as a backstop: cheap, and it also covers SIGHUP-style exits).
**Trade-off:** Ctrl+Q no longer works during a run. The user waits, or kills the process, in which case the
cleaner's marker and recovery notice still apply.

### T3. Keep the UI thread free (F-005, F-006)
**Rationale:** Textual apps must not block the event loop. Process listing, drive detection, update download and
directory listings move into thread workers. Logging keeps file handles open, and interactive rebuilds stop
writing per-item events.
**Alternatives considered:** a background logging thread with a queue (rejected: more moving parts, and a crash
can lose queued lines; keeping append handles open and flushing each line keeps "never lose a line" at a fraction
of the cost). Caching process checks for N seconds (rejected: a stale "WoW not running" is worse than a short wait
behind a spinner).
**Trade-off:** confirm dialogs appear after a short "Checking for running programs…" state instead of instantly.

### T4. Durable, single-threaded config writes (F-007)
**Rationale:** the suite config is a single point of failure for startup. Writes become atomic (`.partial` +
`os.replace`, as used everywhere else), and only the UI thread mutates `Config`; the update-check worker hands
its values back with `call_from_thread`.
**Alternative considered:** a `threading.Lock` inside `Config` (kept as a cheap guard, but the primary fix is
"mutate on one thread").

### T5. Validate output folders where they are set and where they are used (F-008, F-029)
**Rationale:** both tools write large or important files to user-chosen folders. One core helper,
`validate_output_dir(path, install, forbid=...)`, checks for an absolute path that is not inside any flavor's
`WTF`, `Interface` or `Screenshots` folder or the WoW root. It runs on save and again at scan/clean time.

### T6. Shared UI building blocks and less duplication (F-009, F-023, F-024)
**Rationale:** move `ConfirmScreen` and one generic `ProgressScreen(stage_titles, dry_run)` into
`wowtools/ui/dialogs.py`. Move `safe_progress` and `remove_quietly` into `wowtools/core/fsutil.py` (which also
hosts `atomic_write_text` for T4 and `rename_no_replace` for T9). Remove dead code and centralize the `wow-tools`
folder name.
**Alternative considered:** a shared `TreeReviewScreen` base class for both review screens. Deferred: the two
trees differ enough (lazy day nodes, read-only nodes, criteria pane) that a base class now would be a premature
abstraction. The tick-mark helper is extracted as a function instead.

### T7. Updater hardening (F-010, F-011, F-018 part, F-019, F-020, F-026)
**Rationale:** the updater replaces the program in place, so it must be bounded in time, honest about local
changes, verify what it installs, and touch only files it owns.
**Alternative considered for F-010:** signed tags with `git verify-tag` (git installs only; zip installs have no
verifier in the stdlib). Chosen instead: a `wow-tools-vX.Y.Z.zip` release asset plus a `SHA256SUMS` asset,
verified with `hashlib`. If the assets are missing, fall back to today's zipball path only when
`[general] allow_unverified_updates = true`.
**Trade-off:** the release process gains one step (`docs/releasing.md`).

### T8. Consistent journals and undo (F-015, F-016, F-017)
**Rationale:** the two tools share `core/journal.py` but diverge on robustness. The organizer adopts the cleaner's
rules: guarded parsing, a strict destination check, and "mark undone only if something was restored or nothing
failed".

### T9. File-operation atomicity (F-013, F-014, F-028)
**Rationale:** "never overwrite" should hold on every platform, and a crash should never leave a renamed SV file
behind unnoticed.

### T10. CI and a tested Python floor (F-012)
**Rationale:** a GitHub Actions matrix (3.10 and 3.13; ubuntu and windows) runs the suite, `gen_event_docs.py
--check` and `compileall`.

### T11. Small correctness cleanups (F-021, F-022, F-025, F-027)

---

## LLD: change sets

### C-01: Evidence-based "enabled" set (F-001)
- **Files:** `wowtools/tools/wtf_cleaner/scanner.py` (`enabled_addons`, `scan`).
- **Change:**
  ```python
  def enabled_addons(characters, installed, warnings, *, scope: str = "") -> set[str]:
      characters = list(characters)
      if not characters:
          # No character data: WoW's default is "on", and deleting on a guess is never acceptable.
          warnings.append(ScanWarning(scope or "WTF/Account",
                                      "no character folders: the 'not enabled' rule is not applied"))
          return set(installed)
      ...  # unchanged
  ```
  `scan()` passes `scope=str(flavor.account_dir)` (or the scoped account's path).
- **Risk:** a new `scan.warning` line appears for such accounts. Tests that count warnings on the fixture are
  unaffected, because the fixture has characters.

### C-02: Refuse to quit while busy, and join workers before releasing the lock (F-002)
- **Files:** `wowtools/ui/base.py`, `wowtools/suite.py`.
- **Change:**
  ```python
  # base.py, Ka0sApp
  async def action_quit(self) -> None:
      if self.busy:
          self.notify("A run is in progress. Wait for it to finish before quitting.", severity="warning")
          return
      await super().action_quit()
  ```
  Backstop for exits that bypass `action_quit` (signals, a crash in another handler): add a tiny
  `wowtools/core/activity.py` holding a `threading.Event`, `RUN_IDLE`, plus a `running()` context manager. The
  workers wrap `execute_flavors` / `execute` / `undo` / `undo_clean` in `with running():`. In `suite.run`'s
  `finally`, call `RUN_IDLE.wait(timeout=600)` *before* `lock.release()`, and log `session.end` with
  `waited_for_worker=True` when it had to wait. (Textual's `WorkerManager.wait_for_complete` is async and the event
  loop is gone by then, so a plain thread primitive is the reliable choice.)
- **Risk:** Textual's `action_quit` signature is async in 8.x; pin it with a TUI test (see test plan).

### C-03: Report and log UI crashes (F-003)
- **Files:** `wowtools/suite.py` (`_dispatch`), `wowtools/ui/base.py`.
- **Change:**
  ```python
  # base.py
  def _handle_exception(self, error: Exception) -> None:  # Textual hook (private; pinned by test)
      log_exception("ui", getattr(error, "error", error))  # WorkerFailed wraps the original
      super()._handle_exception(error)
  # suite.py
  app.run()
  return getattr(app, "return_code", 0) or 0
  ```
- **Risk:** this overrides a private Textual method. The vendored version is pinned, and a test asserts that the
  hook is still called after a vendor bump.

### C-04: Catch-all in the clean worker (F-004)
- **Files:** `wowtools/tools/wtf_cleaner/review_screen.py` (`_clean_worker`, new `_clean_crashed`).
- **Change:** wrap `execute_flavors(...)` in `try/except Exception as exc:` →
  `log_exception("clean", exc)` → `call_from_thread(self._clean_crashed, exc)`. `_clean_crashed` clears `busy`,
  closes the progress modal, refreshes Undo and shows "The clean stopped unexpectedly: … Check the result with
  Rescan; if files are missing, Undo last clean (z) or the WTF backup in <backup>/backup can put them back." Do
  **not** reuse `nothing_deleted()`, which reports "Nothing was deleted" for any exception without
  `files_missing`.

### C-05: Move blocking work off the UI thread (F-005)
- **Files:** `wowtools/tools/wtf_cleaner/review_screen.py` (`_start`, `action_undo`),
  `wowtools/ui/setup_screen.py`, `wowtools/tools/screenshot_organizer/app.py` (`_pick_flavor`),
  `wowtools/ui/base.py` (`_update_answered`).
- **Change:**
  - `_start` → set `self._checking = True`, show the summary "Checking for running programs…", then
    `run_worker(self._preflight_worker, thread=True, group="preflight")`, which computes `running` and `lockers`
    and calls back `_show_confirm(plan, running, lockers, dry_run)` on the UI thread. Do the same for
    `action_undo`. While `_checking` is set, ignore repeated `c`/`y`/`z` presses.
  - `SetupScreen` → `_detected = []` in `__init__`; `on_mount` starts a thread worker that fills `_detected` and
    updates the hint and the initial value if the input is still empty.
  - `ScreenshotsFlow._pick_flavor` → push `FlavorScreen` right away with the note "counting…", and fill counts
    from a worker through a `FlavorScreen.set_notes()` method.
  - `_update_answered` → `busy = True`, push a progress modal, run `apply_update` in a thread worker, then
    `exit(message)` or notify the failure.
- **Risk:** existing TUI tests that assert the confirm screen appears synchronously need
  `await pilot.pause()` / `wait_for_scheduled_animations`. Injected `wow_check` / `locker_check` fakes keep the
  tests deterministic.

### C-06: Cheaper logging (F-006)
- **Files:** `wowtools/core/events.py` (`EventLog`), `wowtools/tools/wtf_cleaner/rules.py`,
  `wowtools/tools/wtf_cleaner/review_screen.py`.
- **Change:**
  ```python
  class EventLog:
      def __init__(...): ...; self._handles: dict[Path, IO[str]] = {}
      def _append(self, sink, path, line):
          handle = self._handles.get(path)
          if handle is None:
              self._close_other_days(path)          # day rollover closes yesterday's handles
              path.parent.mkdir(parents=True, exist_ok=True)
              handle = self._handles[path] = path.open("a", encoding="utf-8")
          handle.write(line + "\n"); handle.flush()  # still durable per line
      def close(self): ...                           # called from init_event_log replacement and atexit
  ```
  `ReviewScreen._rebuild` calls `evaluate(..., log=False)`. A single `proposal.built` (with per-reason counts) is
  logged after a scan, and `proposal.item` events are emitted once, when the user confirms a clean (the
  selection that actually matters).
- **Risk:** Windows keeps the files open, so log pruning of *today's* files is unaffected (only older days are
  pruned, and those handles are closed on rollover). Register `atexit` to close handles.

### C-07: Atomic, single-thread config writes (F-007)
- **Files:** new `wowtools/core/fsutil.py`, `wowtools/core/config.py`, `wowtools/core/updater.py`,
  `wowtools/ui/base.py`.
- **Change:**
  ```python
  # fsutil.py
  def atomic_write_text(path: Path, text: str) -> None:
      partial = path.with_name(path.name + ".partial")
      partial.write_text(text, encoding="utf-8"); os.replace(partial, path)
  # config.py save()
  buf = io.StringIO(); self._parser.write(buf); atomic_write_text(self.path, buf.getvalue())
  ```
  `check_for_update` gains `persist: Callable[[dict[str, str]], None] | None`. The background check in
  `Ka0sApp._check_update` passes `persist=lambda v: self.call_from_thread(self._persist_update_state, v)`. The CLI
  and `_auto_update` keep persisting inline, since they are single-threaded. `migrate_legacy_config` and
  `migrate._write` reuse `atomic_write_text`.
- **Risk:** low. Tests already cover `save()` content.

### C-08: Output-folder validation (F-008, F-029)
- **Files:** `wowtools/core/install.py` (new `validate_output_dir`), `wowtools/tools/wtf_cleaner/app.py`,
  `wowtools/tools/wtf_cleaner/review_screen.py` (`_start`), `wowtools/tools/screenshot_organizer/settings.py`,
  `wowtools/tools/screenshot_organizer/review_screen.py` (`action_rescan`).
- **Change:** `validate_output_dir(dest, install) -> str | None` refuses relative paths, the WoW root, and anything
  inside any flavor's `WTF`, `Interface` or `Screenshots`, using the existing casefolded `_key()` logic.
  `validate_dest` becomes a thin wrapper. `CleanerSettingsScreen._save` shows errors inline. `_start` and
  `action_rescan` re-validate and refuse with a notify ("Fix the folder in settings (s)").
- **Risk:** users who already set a backup folder inside WTF get a refusal and must change it, which is
  intended. Mention it in the release notes.

### C-09: Shared dialogs and utilities; dead code (F-009, F-023, F-024)
- **Files:** new `wowtools/ui/dialogs.py` (`ConfirmScreen`, `ProgressScreen`, `tick_mark(items, unchecked,
  key)`), `wowtools/core/fsutil.py` (`safe_progress`, `remove_quietly`); update both tools' review screens, result
  screens, `cleaner.py`, `undo.py` ×2, `organizer.py`, `safety.py`, `backup.py`; `core/journal.py` (drop
  `is_open`), `core/migrate.py` (drop `FolderMerge.changed`; `WOW_TOOLS_DIR` imports `TOOLS_SUBDIR`),
  `tools/wtf_cleaner/rules.py` (drop `ProposalItem.scope`), `tools/wtf_cleaner/settings.py`
  (`Path(TOOLS_SUBDIR) / TOOL_NAME`), `docs/architecture.md`, `docs/adding-a-tool.md`, `CLAUDE.md` (narrow the
  future-import rule to `wowtools/` and `scripts/`, or add it to the tests).
- **Change:** `wtf_cleaner.review_screen` re-exports `ConfirmScreen` for one release (`__all__`), so external
  imports and old tests keep working. `CleanProgressScreen` and `ShotProgressScreen` become thin subclasses of
  `ProgressScreen` that keep their CSS IDs, so TUI tests keep passing.
- **Risk:** moderate churn in the UI. Do it after M1-M3 to avoid conflicts (see execution plan).

### C-10: Verified updates (F-010)
- **Files:** `wowtools/core/updater.py`, `docs/releasing.md`, `scripts/update_vendor.py`, new
  `requirements.lock` (hashes).
- **Change:** `fetch_latest` records `assets` (name → `browser_download_url`). `_apply_zip` downloads
  `wow-tools-v{ver}.zip` and `SHA256SUMS`, checks `hashlib.sha256` of the zip against the line for that file, and
  raises `UpdateError("the download does not match its published checksum")` on a mismatch. Without the assets,
  it refuses unless `allow_unverified_updates = true`. `update_vendor.py` uses
  `pip install --require-hashes -r requirements.lock`.
- **Risk:** the first release after this change must publish the assets, or zip users get a clear refusal with a
  link to the release page. Git installs are unaffected (git verifies object hashes; tag signing is a follow-up).

### C-11: Bounded, non-interactive git updates (F-011)
- **Files:** `wowtools/core/updater.py` (`_git`, `_apply_git`).
- **Change:**
  ```python
  env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")}
  proc = runner(["git", *args], cwd=root, capture_output=True, text=True, check=False, timeout=120, env=env)
  ...
  except subprocess.TimeoutExpired as exc: raise UpdateError(f"git {args[0]} timed out") from exc
  # status
  _git(root, runner, "status", "--porcelain", "--untracked-files=no")
  ```
- **Risk:** tests inject `runner` and must accept the new kwargs (`**kwargs` in the fakes).

### C-12: CI (F-012)
- **Files:** new `.github/workflows/tests.yml`.
- **Change:** matrix `os: [ubuntu-latest, windows-latest]`, `python: ["3.10", "3.13"]`; steps:
  `python scripts/run_tests.py`, `python scripts/gen_event_docs.py --check`, `python -m compileall -q wowtools scripts`.
  No network in the tests (already true).
- **Risk:** Windows may surface path or permission differences in tests. Fix those or mark them
  `skipUnless(os.name == "posix")` with a reason.

### C-13: Recover lock-probe leftovers (F-013)
- **Files:** `wowtools/tools/wtf_cleaner/cleaner.py`, `wowtools/tools/wtf_cleaner/scanner.py`.
- **Change:** the scanner skips names ending in `LOCK_PROBE_SUFFIX` (move the constant to `scanner.py`) and adds a
  `ScanWarning`. At the start of `execute()` (real cleans), any `<x>.wowtools-lockcheck` whose `<x>` is absent in a
  selected SavedVariables folder is renamed back with no overwrite, and logged (`clean.probe_recovered`, a new
  event; regenerate `docs/events.md`).
- **Risk:** low. It only touches files carrying our own suffix.

### C-14: No-replace rename (F-014)
- **Files:** `wowtools/core/fsutil.py` (`rename_no_replace`), `organizer.py` (`move_file`, `copy_verified`),
  `cleaner.py` (`_probe_lock`).
- **Change:**
  ```python
  def rename_no_replace(src: Path, dst: Path) -> None:
      if os.name == "nt":
          os.rename(src, dst); return                 # already fails if dst exists
      try:
          os.link(src, dst)                           # atomic EEXIST if dst exists
      except OSError as exc:
          if exc.errno in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV):
              if os.path.lexists(dst): raise FileExistsError(errno.EEXIST, "target exists", str(dst))
              os.rename(src, dst); return             # best effort where hard links are unsupported
          raise
      os.unlink(src)
  ```
  `move_file` keeps its EXDEV → `copy_verified` branch, keyed on the `EXDEV` from `os.link`.
- **Risk:** a hard link briefly shows two names for one file. A crash in that window leaves both names; undo
  and rescan treat the `src` as still present (safe).

### C-15: Guarded organizer journal parsing (F-015)
- **Files:** `wowtools/tools/screenshot_organizer/journal.py`, `wowtools/core/journal.py`.
- **Change:** mirror the cleaner: `try: size = int(...) except (TypeError, ValueError): continue`.
  `core.latest_undoable` catches `(OSError, ValueError, TypeError)`.

### C-16: Confine organizer undo destinations (F-016)
- **Files:** `wowtools/tools/screenshot_organizer/undo.py`.
- **Change:** `_guard(src, dst, wow_root, dest_dir)`, where `dest_dir = to_native(header["dest_dir"])` if it is
  set. The expected `dst` is `target_root(flavor_folder, dest_dir) / YYYY / MM / DD / src.name`, with the date
  parts taken from `parse_shot_name(src.name)`. Refuse unless `dst == expected`.

### C-17: Retryable organizer undo (F-017)
- **Files:** `wowtools/tools/screenshot_organizer/undo.py`.
- **Change:** `marked = restored > 0 or result.count(FAILED) == 0`, then call `mark_undone` only if `marked`. Add
  `OrganizeResult.marked_undone` and show "Undo can be tried again" on the result screen.

### C-18: Prune update backups; optional retention for cleaned zips (F-018)
- **Files:** `wowtools/core/updater.py`, `wowtools/tools/wtf_cleaner/settings.py`, `cleaner.py`.
- **Change:** keep the newest 2 folders in `.update-backup/`. Add `keep_cleaned` (default `0` = keep all, so
  today's documented behavior stays the default). When it is above 0, prune `cleaned-<flavor>-*.zip` after a real
  clean, never deleting a zip that a kept journal still references.
- **Status:** the `.update-backup` part is in scope. `keep_cleaned` is **deferred** as a product decision (see
  the final summary).

### C-19: Only replace files the release ships (F-019)
- **Files:** `wowtools/core/updater.py` (`_managed_names`, `_apply_zip`, `_rollback`).
- **Change:** `old_names = [n for n in set(_managed_names_fixed(root)) | set(_shipped(staging)) if (root/n).exists()]`,
  where `_shipped(staging)` lists the staging root's top-level entries that are `MANAGED_*` or `*.md`. Root `*.md`
  files that the release does not ship stay untouched.

### C-20: Make `wow-tools.cmd` safe to replace while it runs (F-020)
- **Files:** `wow-tools.cmd`.
- **Change:** put `exit /b` inside the parsed block, so nothing is read from the file after Python returns:
  ```bat
  @echo off
  setlocal
  set "PYTHONPATH=%~dp0;%PYTHONPATH%"
  where py >nul 2>nul && (py -3 -m wowtools %* & exit /b) || (python -m wowtools %* & exit /b)
  ```
  (`exit /b` without a code keeps the current ERRORLEVEL.) Check exit-code propagation by hand on Windows (test
  plan).

### C-21..C-27: Small fixes
- **C-21 (F-021):** `lock._platform()` → `"wsl" if is_wsl() else platform.system().lower()`.
- **C-22 (F-022):** `CleanError.__init__(self, message, *, restored=None, files_missing=False)` sets instance
  attributes; update the two raise sites in `_restore_after`.
- **C-23 (F-025):** `unknown = [p for p in processes if p.path is None]` once, outside the loop; `matching` comes
  from `processes_for_flavor` per folder.
- **C-24 (F-026):** `if not force and last is not None and timedelta(0) <= now - last < CHECK_INTERVAL:`.
- **C-25 (F-027):** **deferred** (product decision: should copy mode in place be supported at all, or should it
  require a destination?).
- **C-26 (F-028):** `snapshot_path` and `cleaned_zip_path` get a `-2`, `-3` suffix when the name exists (reuse
  the `new_journal_path` logic; generalize it to `free_name(folder, stem, suffix)` in `fsutil`).
  `SNAPSHOT_NAME` accepts the optional suffix, and prune sorting uses `(stamp, n)`.
