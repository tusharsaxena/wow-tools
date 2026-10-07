# Proposed changes: wow-tools full review (2026-10-07)

This document is derived from `01_FINDINGS.md`. Every change keeps to `docs/standards.md`. Where a rule shaped a
change, it is cited.

## HLD: themes

### T1. Recovery trusts the configured install, not the marker (F-001, F-003)
Recovery and Undo already use `safe_destination` for every file they write. The gap is the *roots*: the WoW folder
comes from the marker's `flavor_path` in `recover`, and the flavors to snapshot come from raw journal values in
`undo_run`. The fix makes both come from the configured `wow_path` and the validated flavor names.
- **Rationale:** STD-5.25 ("refuse anything outside the flavor or the tool's root") and STD-4.4 (paths stored in
  Windows form, so they work from both OSes).
- **Alternatives rejected:**
  - Converting the marker's `flavor_path` with `to_native()` alone. That fixes F-001, but recovery would still
    trust a path from an untrusted file.
  - Dropping `flavor_path` from the marker entirely. Older markers on disk would then not parse, and STD-5.15
    says reading a marker never raises and a damaged one reads as `None`. Instead, the field is kept and ignored
    for resolution, and it is written with `to_stored()` for display.
- **Trade-off:** `recover()` gains a `wow_root` parameter. Both tools' `undo.recover` wrappers and both review
  screens pass `self.cfg.wow_path`.

### T2. Leaving the marker behind is never silent (F-002)
A marker is the "this run did not finish" signal. Removing it after a successful run must either succeed or be
reported.
- **Change:** `core.marker.clear_marker` returns `bool` (True when the marker is gone). A new
  `core.marker.clear_marker_or_retry` tries a few times with short waits (the same pattern as
  `fsutil.REPLACE_RETRY_WAITS`). On final failure, `sv_apply._apply` logs a new registered event
  `<prefix>.marker_left` and sets `ApplyResult.marker_left`, and the result screen shows a red row.
- **Extra guard:** `recover()` checks the run's journal before putting files back. If every marker file has an
  `edited` entry and the journal ends with `finished`, the run actually completed. Recovery then only clears the
  marker, logging `<prefix>.marker_stale`, and changes no files.
- **Rationale:** STD-5.13 ("clear it only when the run finished or fully rolled back") together with STD-5.15
  ("Recovery puts back only files still byte-for-byte what the interrupted run wrote"). A run that finished is not
  an interrupted run.
- **Alternative rejected:** making **Leave as is** the default choice. The D33 / `UnfinishedRunScreen` default is
  a frozen spec decision, and in the true crash case **Put the originals back** is still the right default.
- **Standards:** new events are registered in `core/sv_events.py` and `docs/events.md` is regenerated (STD-6.1,
  STD-6.4). Each gets a `CHANGELOG.md` line (STD-11.1).

### T3. The WTF Cleaner rechecks each file just before deleting it (F-004)
- **Change:** in `_delete_one`, `lstat` the file again right before `unlink`. If size or mtime differ from the
  scan, skip it as "changed" and log `sv.skipped`, as the early recheck does.
- **Rationale:** STD-5.7 ("Re-read every file just before changing it").
- **Alternative rejected:** comparing against the snapshot's copy. That costs a hash per file, and the size+mtime
  rule is what STD-5.7 names for WTF deletes.
- **Trade-off:** one more `lstat` per deleted file (cheap), and a file skipped this late is in the snapshot and
  possibly in the cleaned zip without being deleted. That is harmless: it adds bytes to an archive.

### T4. Updater swap is all-or-nothing (F-005)
- **Change:** in `_apply_zip`, change the swap guard from `except OSError` to `except BaseException`. Roll back,
  then re-raise a `KeyboardInterrupt` / non-`Exception` as is, or wrap an `Exception` in `UpdateError`.
  `_auto_update` and `run_update_command` also catch `OSError` around `apply` and print the backup location.
- **Rationale:** the same "Ctrl+C included" rule the suite applies to user data (STD-5.18 by analogy). The
  install folder is the user's program.

### T5. Bring Interface Backup's folder renames in line with STD-5.17, or record the deviation (F-006)
This is a **decision for the user**. CLAUDE.md says to flag a MUST deviation, not to fix it silently.
- **Option A (preferred):** make `rename_no_replace` the default `rename` in `restore.replace_part`,
  `restore.restore` and `undo.undo` (Interface Backup). `rename_no_replace` already handles directories: `os.link`
  on a directory raises `EPERM`, which falls back to the check+rename branch. Add the three functions to
  `tests/test_no_replace_call_sites.py::test_default_renames_are_rename_no_replace`.
- **Option B:** add a row to the Documented deviations table (STD-5.17, Interface Backup's folder swap) and pin
  the `os.rename` default in a test, so the exception is visible.
- **Note:** `core/lock.py` `take_over` and `core/events.py` log migration write the suite's own files, so they are
  out of STD-5.17's intent. No change is proposed there.

### T6. Split the two largest review screens along their seams (F-007)
- **Change:** move recovery and Undo wiring, which is near-identical in Ace3 and SV Browser, into a shared
  `ui/review.py` mixin, `SvRecoveryActions`. Then split each screen's popup and staging handlers into
  `*_actions.py` mixins inside the tool package. The class keeps layout and dispatch.
- **Rationale:** STD-1.8 (thin front ends) and STD-2.2/2.3: what two tools need lives once in `ui/`, pinned in
  `tests/test_structure.py`. The extraction is justified because both tools call the same `sv_undo`/`sv_apply`
  functions with the same semantics and differ only in `SV_TOOL` and labels, with no per-tool behaviour flags.
- **Alternative rejected:** splitting by line count alone. Mixins named after what they do (recovery, staging) are
  allowed. A `part2` mixin is not.
- **Risk:** a large mechanical diff. It must land as its own milestone, after the behaviour fixes, with the full
  suite green before and after and no behaviour change in the same commit.

### T7. Small hardening (F-008 to F-014)
These are independent, one-file changes. See the LLD below.

## Upstream change-set
None. No defect was found in `vendor/`, and `vendor/` was not reviewed beyond how the project uses it.

## LLD: changes per finding

### C-01: F-001. `recover` resolves under the configured WoW folder
- **Files:**
  - `wowtools/core/sv_undo.py` (`recover`)
  - `wowtools/core/sv_apply.py` (`Marker` write and read)
  - `wowtools/tools/ace3_profile_manager/undo.py`, `wowtools/tools/sv_browser/undo.py` (wrappers)
  - `wowtools/tools/ace3_profile_manager/review_screen.py:1285`, `wowtools/tools/sv_browser/review_screen.py:1339`
- **Sketch:**
  ```python
  # sv_undo.recover(tool, marker, *, wow_root: Path, root: Path, ...)
  targets = {rel: destination(wow_root, marker.flavor, rel) for rel in marker.files}
  flavor = Flavor(marker.flavor, wow_root / marker.flavor)
  if destination(wow_root, marker.flavor, "WTF/Account/x/SavedVariables/x.lua") is None:
      raise UndoError("The unfinished change names a game version folder that is not valid. Nothing was changed.")
  if not flavor.path.is_dir():
      raise UndoError(f"{marker.flavor} is not in {wow_root}. Nothing was changed.")  # the marker stays
  ```
  The marker's `zip` and `flavor_path` are written with `to_stored()` and read with `to_native()`
  (`core/paths.py`, STD-4.4). `_moved_zip` keeps its fallback by name.
- **Risk:** existing markers written with `str()` still read: `to_native()` leaves a POSIX path as it is.
  Because the folder is missing, recovery now **refuses** instead of clearing the marker. That is the safe
  direction.

### C-02: F-003. Undo snapshots only validated flavors
- **File:** `wowtools/core/sv_undo.py` (`undo_run`)
- **Sketch:**
  ```python
  targets = [(e, destination(wow_root, e["flavor"], e["rel"])) for e in entries]
  flavors = [Flavor(f, wow_root / f) for f in sorted({e["flavor"] for e, dest in targets if dest is not None})]
  ```
- **Risk:** none. Entries with a `None` destination were already skipped.

### C-03: F-002. Report a marker that failed to clear, and treat a finished journal as authoritative
- **Files:**
  - `wowtools/core/marker.py` (`clear_marker` returns `bool`)
  - `wowtools/core/sv_apply.py:332` (retry, event, `ApplyResult.marker_left`)
  - `wowtools/core/sv_undo.py` (`recover` checks the journal)
  - `wowtools/core/sv_events.py` (`marker_left`, `marker_stale`)
  - `wowtools/core/sv_report.py` (result row)
  - `docs/events.md` (regenerated), `CHANGELOG.md`
- **Sketch:**
  ```python
  def clear_marker(folder: Path, name: str, waits=(0.05, 0.1, 0.2)) -> bool:
      path = folder / name
      for wait in (*waits, None):
          try:
              os.remove(path); return True
          except FileNotFoundError:
              return True
          except OSError:
              if wait is None: return False
              time.sleep(wait)
  ```
  `recover()` gets `journal_dir` (it already does). If the journal whose `edited` entries name `marker.zip`
  ends with `finished`, it clears the marker, logs `<prefix>.marker_stale` and returns an empty `UndoResult`.
- **Risk:** WTF Cleaner's `safety.clear_marker` gets the same return value. Its callers may ignore it, since its
  marker only produces a notice.

### C-04: F-004. Recheck right before unlink
- **File:** `wowtools/tools/wtf_cleaner/cleaner.py` (`_delete_one`)
- **Sketch:**
  ```python
  problem = _recheck(sv, _lstat(sv.path))
  if problem:
      result.outcomes.append(FileOutcome(sv.path, sv.size, "skipped", problem, tuple(item.reasons)))
      log_event("sv.skipped", dry_run=False, path=rel, reason=problem)
      return
  deleted.append(rel)
  ```
- **Risk:** `check_clean` must not report a late-skipped file as a problem. It only checks `deleted`, so it does
  not.

### C-05: F-005. Updater rolls back on anything
- **Files:** `wowtools/core/updater.py` (`_apply_zip` swap block, `run_update_command`), `wowtools/suite.py`
  (`_auto_update`)
- **Sketch:**
  ```python
  except BaseException as exc:
      try:
          _rollback(root, backup, shipped)
      except OSError as rollback_exc:
          raise UpdateError(f"... Your previous version is saved in {backup}") from exc
      if not isinstance(exc, Exception):
          raise
      raise UpdateError(f"update failed and was rolled back: {exc}") from exc
  ```
  `run_update_command` and `_auto_update` also catch `OSError` around `apply(...)` and print it as
  "Update failed: ...".

### C-06: F-006. Interface Backup renames
- **Option A (if the user agrees):**
  - `wowtools/tools/interface_backup/restore.py:391,495` and `undo.py:185`: change the default to
    `rename_no_replace` (imported from `core/fsutil`, STD-2.4).
  - `tests/test_no_replace_call_sites.py:44-47`: add `restore.replace_part`, `restore.restore` and
    `interface_backup.undo.undo` to the tuple.
- **Option B:** add a row to `docs/standards.md` *Documented deviations*. The rule text itself is unchanged.
- **Risk (A):** on drvfs (`/mnt/*`), `os.link` on a directory raises `EPERM`, so the fallback runs. The swap's
  rollback paths already use the injected `rename`, so they follow the change.

### C-07: F-007. Extract `SvRecoveryActions` and per-tool action mixins
- **Files:**
  - `wowtools/ui/review.py` (new mixin)
  - `wowtools/tools/ace3_profile_manager/review_screen.py`, `wowtools/tools/sv_browser/review_screen.py`
  - new `wowtools/tools/<tool>/review_actions.py` (STD-1.7 allows front-end modules to import `textual`; the
    module name must end in `_screen.py` or be added to the front-end list. Check `tests/test_structure.py`
    before naming it)
  - `tests/test_structure.py` (pin the single definition, STD-2.3)
  - `docs/architecture.md` (the `review` row, STD-9.5)
- **Before:** each screen defines `_after_recover_preflight` / `_recovered` / `_offer_recovery`.
- **After:** `SvRecoveryActions` defines them once, with screen hooks `recovery_screen()` and `recover_fn`.
- **Risk:** must be a pure move. Start with characterization tests: the existing `test_ace_undo.py` and
  `test_sv_browser_run_ui.py` recovery tests pass unchanged before and after.

### C-08: F-008. Release the lock on early start-up failure
- **Files:**
  - `wowtools/suite.py`: move `init_event_log` and `_migrate_renamed_folders` inside a `try` that releases the
    lock on an exception, or widen the existing `try/finally` to start right after `lock.acquire()`.
  - `wowtools/core/events.py`: wrap the `iterdir()` calls in `migrate_flat_logs` and `prune` in
    `try/except OSError: return []`, which makes the "Never raises" docstring true.

### C-09: F-009. `create_backup` cleans its partial on `BaseException`
- **File:** `wowtools/core/backup.py:81-86`. Add `except BaseException: remove_quietly(partial); raise`, as
  `core/snapshot.py:74-76` does.

### C-10: F-010. Decode process listings explicitly
- **File:** `wowtools/core/process.py:40,117`
- **Change:** pass `encoding="utf-8", errors="replace"` (STD-1.9). For PowerShell, also prefix the query with
  `[Console]::OutputEncoding=[Text.Encoding]::UTF8;` so paths come out as UTF-8. Add `ValueError` to the caught
  exceptions as a last resort (a failed listing is `None`, unknown).

### C-11: F-011. Remove the dead re-exports
- **Files:** `wowtools/tools/wtf_cleaner/safety.py:23` (drop `LIST_REPORT_EVERY`) and
  `wowtools/tools/ace3_profile_manager/report.py:10` (drop `RESULT_TEXT`).
- **Test:** add both to `tests/test_structure.py::test_dead_code_is_gone` (STD-2.8).

### C-12: F-012. `fsync` the partial before the replace
- **File:** `wowtools/core/fsutil.py:51-53`. Call `handle.flush(); os.fsync(handle.fileno())` before closing.
  `fsync` of the parent directory is optional on POSIX and is not done on Windows.
- **Perf note:** one `fsync` per SavedVariables write, marker or config save. The cost should be measured with
  the existing pipeline tests' timings before and after (see `03_TEST_PLAN.md`), not assumed.

### C-13: F-013. Tell users their config comments do not survive a save
- **Files:** `README.md` (the settings section) and the `allow_unverified_updates` message in
  `wowtools/core/updater.py`. Say that comments in `config/*.cfg` are not kept.
- **Rejected alternative:** a comment-preserving writer. That would mean a custom INI writer or a new dependency,
  and STD-1.4 forbids new third-party packages.
- **Standards:** README changes keep the strings `tests/test_docs.py` pins (STD-9.6).

### C-14: F-014. Bound each shard
- **File:** `scripts/run_tests.py:61`. Add `timeout=` (default 600 s, `--timeout` flag). On
  `TimeoutExpired`, report the shard as failed with "timed out".
- **Optional:** update the runtime range in `CLAUDE.md` and `docs/testing.md` from fresh measurements. Keep the
  strings `tests/test_docs.py` pins (STD-9.6).

## Standards conformance

| Change | Rules it follows | New deviation? |
|---|---|---|
| C-01, C-02 | STD-4.4, STD-5.15, STD-5.25 | No |
| C-03 | STD-5.13, STD-6.1, STD-6.4, STD-11.1 | No |
| C-04 | STD-5.7 | No |
| C-05 | STD-6.6 (CLI prints allowed in `suite.py` and the updater CLI) | No |
| C-06 | STD-5.17. Option B adds a documented deviation, by the user's decision | Only under B |
| C-07 | STD-1.7, STD-1.8, STD-2.2, STD-2.3, STD-9.5 | No |
| C-08 to C-14 | STD-1.4, STD-1.9, STD-2.8, STD-5.12, STD-5.16, STD-9.6 | No |

No change edits `vendor/`, `docs/superpowers/` or an earlier `reviews/` bundle (STD-11.3, STD-12.4). No committed
test count or badge exists, so none moves.
