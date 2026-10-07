# Findings: wow-tools full review (2026-10-07)

**Verdict:** minor issues. Nothing blocks a release. The green gate passes and the data-safety design holds up
well. Seven Medium findings are worth fixing before the first tagged release. Four of them are in the recovery
and Undo paths of the shared SavedVariables pipeline, where a small mistake costs the most.

**Resolved scope:** `all`, so this covers the **whole first-party repository** at `81bfc4d` on `master`, with a
clean working tree: `wowtools/` (core, ui, all five tools), `scripts/`, `tests/` (their structure and gaps, plus
sampled assertions), the launchers, and `docs/` where the code makes claims about them. `vendor/` was not reviewed,
and no `[upstream]` findings were raised. `docs/superpowers/` and `reviews/2026-10-04/` were read only for
context; they are frozen (STD-12.4).

**Profile:** `profile=generic` (dev-copilot-profile, reason=default). This matches the caller.

## Measurement run

All commands ran from the repo root on 2026-10-07 under WSL2 (Linux 6.6, Python 3), and their output went to a
scratch directory outside the repo.

| Suite | Command | Result |
|---|---|---|
| Tests (full, parallel, as CI runs them) | `timeout 600 python3 scripts/run_tests.py` | **pass**: `Ran 1710 tests in 103.8s across 16 processes (0 failures, 0 errors, 2 skipped)`, exit 0 |
| Lint | `timeout 300 ruff check --no-cache .` | **pass**: `All checks passed!`, exit 0 |
| Event docs | `timeout 120 python3 scripts/gen_event_docs.py --check` | **pass**, exit 0 |
| Type-check | none | **skipped**: the project configures no type-checker |
| Coverage / benchmarks | none | **skipped**: none are configured and no reports are committed |

Committed artifacts compared with this run:
- `CLAUDE.md` gives the suite's runtime as "70-100 s on WSL /mnt/d". Today's run took **103.8 s**, a little
  over that range. One run is not enough to call the claim stale, so it is noted in F-014 rather than raised alone.
- No committed test count, coverage figure or badge was found. The search was
  `git ls-files | grep -v '^vendor/\|^docs/superpowers/\|^reviews/' | xargs grep -nE "[0-9]{3,4} tests"`, which
  matched nothing.

Two scenarios were also reproduced with scratch scripts (both kept outside the repo):
- `marker_xplat.py` backs F-001.
- `journal_flavor.py` backs F-003.

Census (scope: authored source, from `git ls-files 'wowtools/*.py'`): 131 modules, 25,214 lines. The noqa count
comes from `git ls-files 'wowtools/*.py' 'scripts/*.py' | xargs grep -c noqa`: 46 markers (29 `BLE001`, 9 `F401`,
5 `E402`, 3 `S110`, 2 `SIM115`, 1 `FLY002`).

Status of the previous review (2026-10-04), from reading the current code: F-002 (Ctrl+Q while busy), F-003
(return code and crash logging), F-007 (atomic config), F-010 (SHA256SUMS), F-011 (git hang) and F-012 (CI) are
fixed. They are not raised again.

Counts: **Critical 0 · High 0 · Medium 7 · Low 7**

---

## Medium

### F-001: Recovery uses the marker's own `flavor_path`, which is not portable, so recovering from the other OS skips every file and clears the marker
- **Where:**
  - `wowtools/core/marker.py:280`: `stored = {key: str(value) if isinstance(value, Path) else value ...}`
  - `wowtools/core/sv_apply.py:168`: `Marker(str(data["flavor"]), Path(data["flavor_path"]), Path(data["zip"]), ...`
  - `wowtools/core/sv_undo.py:212`: `targets = {rel: destination(marker.flavor_path.parent, marker.flavor, rel) ...}`
  - `wowtools/core/sv_undo.py:245-246`: `if not result.failed: clear_marker(root)`
- **Problem:** The crash marker stores paths as `str()`, not through `to_stored()` the way journals do. `recover()`
  then takes the WoW root from the marker's `flavor_path`, not from the configured `wow_path`. A marker written on
  Windows (`G:\World of Warcraft\_retail_`) and read under WSL, or the other way round, points at a folder that
  does not exist. Every file is reported as "the file is gone or could not be read". No file counts as `failed`,
  so the marker is cleared.
- **Impact:** After an interrupted Apply, a user who recovers from the other OS restores nothing, and the only
  pointer to the interrupted run is deleted. The flavor is left half-edited. Undo from the journal still works,
  because journal paths are portable, but the dedicated recovery flow says it handled the run.
  - Reproduced with `marker_xplat.py`: `outcomes: [('WTF/Account/ACC/SavedVariables/Addon.lua', 'skipped', 'the
    file is gone or could not be read')]`, `marker still there: False`, `file content: b'after'`.
- **Reachability:** Any user who runs the suite from both Windows and WSL against one WoW folder. This is a
  supported setup: STD-4.4 promises that "one config and one journal work from Windows and WSL". It happens when
  an Ace3 or SV Browser Apply was interrupted on one OS and the user recovers on the other.
- **Standards:** STD-4.4 (paths are stored in Windows form) and STD-5.25 (marker paths are untrusted and map only
  through `safe_destination` under the flavor) are both only partly met here.
- **Tests:** No test writes a marker in one path form and reads it in the other.
- **Tag:** `[correctness]`

### F-002: A marker that fails to delete after a successful Apply later offers "Put the originals back" as the focused default, which reverts the completed run
- **Where:**
  - `wowtools/core/marker.py:297-298`: `def clear_marker(...): remove_quietly(folder / name)`
  - `wowtools/core/sv_apply.py:332`: `clear_marker(root)` (after the write loop)
  - `wowtools/core/sv_undo.py:231`: `if current is None or current != marker.after.get(rel):` (any other file is
    put back)
  - `wowtools/ui/dialogs.py:415-416`: `("put_back", "Put the originals back", "revert")], default="put_back"`
- **Problem:** `clear_marker` swallows every error. If the delete fails, for example because an antivirus scanner
  or a sync client holds the new marker for a moment on Windows, the Apply still reports success. On the next
  scan the review offers the unfinished-run choice with **Put the originals back** focused. Every file is still at
  the marker's `sha_after`, so recovery puts back all of them. `record_recovered` then journals them as rolled
  back, so Undo cannot reapply them.
- **Impact:** One Enter silently reverts an Apply that actually finished. No log event records the failed delete,
  so the user and the log both believe the run "did not finish".
- **Reachability:** A Windows user whose tool folder is scanned or synced (Defender, OneDrive) at the moment
  the marker is removed. This is rare, but nothing in the code path rules it out. This finding comes from
  reading the code; it was not reproduced.
- **Tests:** `tests/test_core_shared.py:155-157` and `tests/test_safety.py:110-112` test only that clearing twice
  is harmless. No test makes the delete fail.
- **Tag:** `[error-handling]`

### F-003: Undo builds `Flavor` objects from the journal's unchecked `flavor` field, so a crafted journal makes Undo zip a folder outside WoW and write the zip outside `snapshots/`
- **Where:** `wowtools/core/sv_undo.py:165`:
  `flavors = [Flavor(folder, wow_root / folder) for folder in sorted({e["flavor"] for e in entries})]`, passed to
  `_snapshots` at `:166`.
- **Problem:** Each entry's *destination* goes through `destination()`/`safe_destination`, which rejects a
  `flavor` containing `/`, `\` or `:`. The list of flavors to snapshot is built from the same raw values with no
  check, before the destinations are filtered. A `flavor` of `../elsewhere` therefore snapshots
  `<wow>/../elsewhere/WTF`, and because `Flavor.short_name` is `folder.strip("_")` the zip name carries `../`.
  - Reproduced with `journal_flavor.py`: `snapshots: [.../toolroot/snapshots/snapshot-../elsewhere-20261007-170421.zip]`,
    which resolves outside `snapshots/`. The entry itself was then correctly skipped: `('skipped', 'it is outside
    the WTF folder')`.
- **Impact:** Undo reads files outside the WoW install and writes a zip of them at a path the journal chooses. It
  never overwrites, because `rename_no_replace` is used, and it never touches SavedVariables. The risk is limited
  by needing write access to the journal folder, but the standard calls this out explicitly.
- **Reachability:** Nobody on a normal run. It needs a hand-edited or corrupted journal in
  `<WoW>/wow-tools/<tool>/journal/`. That caps the severity at Medium.
- **Standards:** STD-5.25 MUST ("refuse anything outside the flavor or the tool's root").
- **Tests:** `tests/test_ace_undo.py:94` (`undo.destination(self.wow, "_retail_", "../x.lua")`) covers `rel` only.
  Nothing covers a bad `flavor` reaching the snapshot step.
- **Tag:** `[security]`

### F-004: The WTF Cleaner rechecks files before the WTF snapshot, not just before each delete
- **Where:** `wowtools/tools/wtf_cleaner/cleaner.py:234-240` (the `_recheck` loop runs before
  `_take_safety_snapshot` at `:249`) and `cleaner.py:416-437` (`_delete_one` calls `sv.path.unlink()` with no
  recheck).
- **Problem:** STD-5.7 says to re-read a file "just before changing it". The size and mtime check happens before
  the whole-WTF snapshot and the optional cleaned-files zip. Zipping a large WTF folder can take tens of seconds.
  A file rewritten after the recheck is still deleted. With `backup_before_delete = false`, the only copy is then
  the snapshot, which may hold the older bytes if the file was zipped before the rewrite.
- **Impact:** Newer SavedVariables data can be deleted with no copy of it. The cleaned-files zip partly covers
  this: its size check against the scan fails on a grown file and stops the run. That protection does not exist
  when the zip is off.
- **Reachability:** A user who cleans while WoW or a companion app writes one of the selected files. WTF Cleaner
  only warns about a running WoW, by documented deviation STD-5.3, so this is reachable with the default
  settings. In practice it needs a logout or `/reload` during the clean.
- **Tests:** `tests/test_cleaner.py::test_changed_and_missing_files_are_skipped` changes the file *before*
  `execute()`, so it pins the early recheck only. No test changes a file between the snapshot and the delete.
- **Tag:** `[correctness]`

### F-005: A zip update rolls back on `OSError` only, so Ctrl+C during the swap leaves a half-replaced install
- **Where:** `wowtools/core/updater.py:560-571`. The swap loop
  (`for name in old_names: _remove_tree(root / name)` / `for name in shipped: _copy(staging / name, root / name)`)
  is guarded by `except OSError as exc:` only.
- **Problem:** A `KeyboardInterrupt` between removing `wowtools/` and copying the new one skips `_rollback`. The
  same applies to any non-`OSError` exception, such as a `shutil.Error` subclass or a `UnicodeError` in a file
  name. In the CLI paths (`wow-tools update` and auto-update before the menu), `run_update_command` and
  `_auto_update` catch `UpdateError` only, so the interrupt surfaces as a traceback.
- **Impact:** The program folders are partly deleted and the launcher no longer starts. The old version is in
  `.update-backup/<version>`, but the message does not say so. The user has to restore it by hand.
- **Reachability:** A zip-install user who presses Ctrl+C during the few seconds of the swap in
  `wow-tools update` or during an auto-update at start. The TUI's `u` path runs in a worker thread, which never
  receives `KeyboardInterrupt`, and catches `Exception` (`ui/base.py:249`).
- **Tag:** `[error-handling]`

### F-006: Interface Backup restore and Undo rename folders with `os.rename`, an undocumented STD-5.17 deviation the call-site test does not pin
- **Where:**
  - `wowtools/tools/interface_backup/restore.py:391`: `rename: Rename = os.rename` (`replace_part`)
  - `restore.py:495`: `rename: Rename = os.rename` (`restore`)
  - `wowtools/tools/interface_backup/undo.py:185`: `rename: Rename = os.rename`
  - `tests/test_no_replace_call_sites.py:44-47` pins only `organizer.move_file`, `organizer.execute` and
    `undo.undo` (Screenshot Organizer).
- **Problem:** STD-5.17 MUST: "Every rename or move into a final name goes through `fsutil.rename_no_replace`
  (never `os.rename`/`os.replace`)". The deviation table lists only `core/migrate.py`. The folder swap
  (`rename(live, old)`, `rename(staging, live)`) and `_move_links` use `os.rename` behind a separate `lexists`
  check. `core/lock.py:82` and `core/events.py:134` also use `Path.replace`, but those are the suite's own files.
- **Impact:** The data risk is small. On POSIX, `os.rename` replaces only an *empty* target directory, and the
  swap checks for leftovers first. The real problem is process: CLAUDE.md requires a MUST deviation to be flagged
  or recorded, and this one is neither recorded nor caught by the test meant to catch it.
- **Reachability:** Every Interface Backup restore and Undo on Linux, macOS or WSL. On Windows, `os.rename`
  already refuses an existing target.
- **Tag:** `[design]` (standards conformance)

### F-007: The Ace3 and SV Browser review screens are god-classes
- **Where:**
  - `wowtools/tools/ace3_profile_manager/review_screen.py:118`: `class ProfileReviewScreen(...)` has 111 methods
    in a 1,313-line file.
  - `wowtools/tools/sv_browser/review_screen.py:142`: `class SvReviewScreen(...)` has 104 methods in a 1,371-line
    file.
  - The next largest are Interface Backup's `BackupReviewScreen` (72 methods) and WTF Cleaner's `ReviewScreen`
    (69). These counts come from an `ast` pass over `git ls-files 'wowtools/*.py'`.
- **Problem:** Each screen holds layout, staging dispatch, popup wiring, recovery, Undo, search, tips and
  leave-guards. STD-1.8 (SHOULD) asks for thin front ends. The shared mixins took out the common machinery, but
  the per-tool screens have kept growing.
- **Impact:** Changes ripple. A fix to one flow (recovery, Undo) means reading a 1,300-line class. Both screens
  repeat similar recovery and Undo wiring (`_after_recover_preflight`, `_recovered`) that differs only in names.
  That duplication is a candidate for `ui/review.py`, but only if the semantics stay identical (STD-2.2).
- **Reachability:** Developers only, with no runtime effect.
- **Tag:** `[design]`

---

## Low

### F-008: `suite.run` takes the instance lock before steps that sit outside the `try/finally` that releases it
- **Where:**
  - `wowtools/suite.py:77`: `init_event_log(log_dir, ...)`. Lines `:79-87` (`_migrate_renamed_folders`,
    `session.start`) run before the `try:` at `:90`.
  - `wowtools/core/events.py:108`: `for path in sorted(log_dir.iterdir()):` (`migrate_flat_logs`, documented as
    "Never raises")
  - `events.py:284`: `files = sorted(p for folder in self.log_dir.iterdir() ...)` (`prune`)
- **Problem:** An `OSError` from listing an unreadable `logs/` sub-folder escapes, and `wow-tools.lock` is left
  behind.
- **Impact:** The next start shows "another copy may be running". On Windows, a stale lock cannot be detected.
- **Reachability:** Only a user whose `logs/` holds an unreadable folder or file. This is rare.
- **Tag:** `[error-handling]`

### F-009: `create_backup` leaves its `.partial` behind on a `BaseException`
- **Where:** `wowtools/core/backup.py:81-86`. Only `BackupError` and `(OSError, zipfile.BadZipFile, ValueError)`
  remove the partial. `core/snapshot.py:74-76` also has `except BaseException: remove_quietly(partial)`.
- **Problem:** STD-5.12 MUST says "on any failure, Ctrl+C included, remove the partial".
- **Impact:** A stray `*.zip.partial` in `cleaned/` or `edited/`.
- **Reachability:** Nobody in the app: runs execute in worker threads, which never receive `KeyboardInterrupt`.
  This is a letter-of-the-standard gap in a shared helper.
- **Tag:** `[error-handling]`

### F-010: Process-listing subprocesses decode with the locale and never catch `UnicodeDecodeError`
- **Where:**
  - `wowtools/core/process.py:40`: `runner([command, "/FO", "CSV", "/NH"], capture_output=True, text=True, ...)`
  - `process.py:117-118`: PowerShell call with `text=True`
  - Both catch only `(OSError, subprocess.SubprocessError)` (`:41`, `:121`).
- **Problem:** STD-1.9 SHOULD asks for explicit UTF-8. `tasklist.exe` and `powershell.exe` write in the OEM code
  page. If WoW's path contains, say, `é` or `ü`, decoding raises `UnicodeDecodeError`, which is a `ValueError`. It
  escapes the check without falling back to `tasklist`.
- **Impact:** The preflight turns it into an "unknown" alert. Inside an Apply or Undo worker,
  `refuse_running(...)` crashes instead, and the user sees "The run stopped unexpectedly: UnicodeDecodeError ..."
  rather than the WoW-running refusal. Nothing is written either way.
- **Reachability:** WSL or Windows users whose WoW install path has non-ASCII characters, while WoW is running.
- **Tag:** `[error-handling]`

### F-011: `# noqa: F401 - re-exported` hides imports nobody uses
- **Where:**
  - `wowtools/tools/wtf_cleaner/safety.py:23`: `from wowtools.core.snapshot import LIST_REPORT_EVERY, ...  # noqa: F401 - re-exported`.
    `LIST_REPORT_EVERY` has no reader outside `core/snapshot.py`.
  - `wowtools/tools/ace3_profile_manager/report.py:10`: `RESULT_TEXT` is imported, but neither that module nor
    any importer of it uses it.
  - Search used: `git ls-files 'wowtools/*.py' 'tests/*.py' | xargs grep -n "RESULT_TEXT\|LIST_REPORT_EVERY"`.
- **Problem:** STD-2.8 MUST ("Delete dead code and re-exports outright"). The noqa turns off the one check that
  would catch this.
- **Reachability:** No runtime effect.
- **Tag:** `[dead-code]` `[lint]`

### F-012: `atomic_write_bytes` never calls `fsync`, so "old file or new file, never a mix" holds for a process crash but not a power loss
- **Where:** `wowtools/core/fsutil.py:51-53`: `handle.write(data)` then `_replace_retrying(partial, path)`.
- **Problem:** Without `os.fsync` before the rename, a power cut or OS crash shortly after Apply can leave a
  zero-length or stale SavedVariables file on some file systems. Markers and journals are written the same way.
- **Impact:** The STD-5.16 guarantee is weaker than its *Why* says. The snapshot and originals zip still allow
  recovery.
- **Reachability:** Only a power or OS failure within seconds of an Apply, Undo or config save.
- **Tag:** `[correctness]`

### F-013: Saving the config drops hand-written comments, though the app tells users to hand-edit it
- **Where:** `wowtools/core/config.py:108-112` (`save` renders through `configparser`, which drops comments) and
  `wowtools/core/updater.py:318-319` ("set allow_unverified_updates = true in config/wow-tools.cfg").
- **Impact:** A note a user wrote beside a hand-edited value disappears on the next save. That save can come
  from any settings change or an update check.
- **Reachability:** Users who hand-edit `config/*.cfg` and add comments.
- **Tag:** `[ux]`

### F-014: Test shards have no timeout, and the documented runtime is at its edge
- **Where:** `scripts/run_tests.py:61-62`: `proc = subprocess.run(command, cwd=ROOT, capture_output=True, ...
  check=False)` has no `timeout=`.
- **Problem:** One hung Textual test (a pilot waiting on a worker) blocks the run until CI's
  `timeout-minutes: 20` and leaves no shard output. Separately, today's run took 103.8 s, against CLAUDE.md's
  "70-100 s".
- **Reachability:** Developers and CI only.
- **Tag:** `[tests]`
