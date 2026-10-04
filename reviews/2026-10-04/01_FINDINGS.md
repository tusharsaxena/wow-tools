# Findings: wow-tools full review (2026-10-04)

**Verdict:** minor issues. The code is careful and well tested (405 tests, all passing). Two High findings should
still be fixed before the next release: a proposal bug that pre-ticks installed addons for deletion, and a quit
path that releases the instance lock while a file-changing run is still going.

**Resolved scope:** the working tree is clean and `master` (the default branch, at `6e9ac1f release: v1.0.0`) has
no feature branch to diff against, so this covers the **whole first-party repository**: `wowtools/` (core, ui, both
tools), `scripts/`, the launchers (`wow-tools.sh`, `wow-tools.cmd`), `requirements.txt`, the test suite (its
structure and gaps, not every assertion) and `docs/` (checked for drift against the code). `vendor/` (pinned
third-party code) was only checked where the project relies on its behavior: Textual worker threads, the
quit binding and exception handling.

**Stack:** Python >= 3.10, stdlib plus vendored Textual 8.2.8 / Rich 15. Tests use `unittest` through
`scripts/run_tests.py`. There is no CI, no linter or type-checker config, and no pre-commit. Conventions come from
`CLAUDE.md`: `core/*` and tool logic never import textual, config paths go through `core/paths.py`, every event is
registered, and there is one app with one `ToolFlow` per tool.

Counts: **Critical 0 · High 2 · Medium 10 · Low 17**

---

## High

### F-001: An account with no character folders gets every installed addon proposed as "not enabled"
- **Where:** `wowtools/tools/wtf_cleaner/scanner.py:137-153` (`enabled_addons`), used by
  `wowtools/tools/wtf_cleaner/rules.py:113` (`_group_reasons`).
- **Problem:** `enabled_addons()` builds "enabled" only from the characters it is given. With zero characters (a
  scoped scan of an account that has only account-wide `SavedVariables`, or a flavor where no account has
  realm/character folders), the result is the empty set. So every installed addon's account-wide SV file matches
  `not_enabled`, and that criterion is on and pre-ticked by default.
- **Impact:** one click on Clean deletes the settings of addons the user has installed and uses. Recovery depends
  on the user noticing and running Undo. Reproduced: an account `SOLO` with `Details.lua` and `WeakAuras.lua`, both
  addons installed and no character folder, produces `Details ['not_enabled']` and `WeakAuras ['not_enabled']`.
- **Tag:** `[correctness]`

### F-002: Ctrl+Q during a clean, organize or undo releases the instance lock while the worker thread keeps changing files
- **Where:** `wowtools/ui/base.py:54-106` (`Ka0sApp` never overrides `action_quit`; Textual's `ctrl+q` binding is
  `priority=True`, see `vendor/textual/app.py:455-461`), `wowtools/suite.py:99-102` (`finally: lock.release()`),
  `wowtools/tools/wtf_cleaner/review_screen.py:688-694`, `wowtools/tools/screenshot_organizer/review_screen.py:580-587`.
- **Problem:** `app.busy` protects `s`, `u`, `f`, `t`, `q` and the review actions, but not the app-level priority
  quit. Thread workers run on the default `ThreadPoolExecutor` (`vendor/textual/worker.py:326`), so quitting tears
  down the UI and returns from `app.run()`. `suite.run()` then releases `wow-tools.lock` and logs `session.end`,
  while the worker thread keeps deleting, moving or restoring files until the interpreter joins it.
- **Impact:** a second copy can acquire the lock and work on the same WTF or Screenshots folders while the first is
  still writing. The user never sees the result screen. A second Ctrl+C during the interpreter's join kills the
  worker mid-operation. The cleaner's marker and snapshot limit the damage; the organizer has no equivalent.
- **Tag:** `[concurrency]`

---

## Medium

### F-003: The suite ignores the app's return code, and UI crashes never reach the event log
- **Where:** `wowtools/suite.py:164-170` (`app.run(); return 0`), `wowtools/suite.py:96-98`.
- **Problem:** When a handler or worker raises, Textual handles it internally (`_handle_exception` sets
  `return_code = 1`, prints a traceback and exits) and `app.run()` returns normally. `_dispatch` always returns 0,
  so `log_exception("suite", ...)` never runs and `session.end` records `exit_code=0`.
- **Impact:** the structured logs, which are the project's main diagnostic tool, show crashes as clean exits. The
  process exit status is wrong, and bug reports carry no traceback in `logs/`.
- **Tag:** `[error-handling]`

### F-004: The WTF Cleaner's clean worker has no catch-all, unlike every other worker
- **Where:** `wowtools/tools/wtf_cleaner/review_screen.py:696-717` (`_clean_worker`). Compare `_undo_worker`
  (lines 806-812) and the organizer's `_job_worker`.
- **Problem:** `execute_flavors()` catches only `BackupError` and `CleanError`. An `OSError` or `RuntimeError` from
  `Path.resolve()` in `_Guard`, from `snapshot.stat()`, or from `aside.exists()` in the lock probe escapes the
  worker, and `exit_on_error=True` then kills the whole app.
- **Impact:** an unexpected error before or after the delete loop (the loop itself rolls back) closes the app
  mid-flow. The user does not learn whether anything was deleted, and per F-003 nothing is logged.
- **Tag:** `[error-handling]`

### F-005: Blocking subprocesses and I/O run on the UI thread
- **Where:**
  - `wowtools/tools/wtf_cleaner/review_screen.py:640-641, 670` and `779-780`: `wow_check_for(...)()` runs
    PowerShell (10 s timeout), falls back to `tasklist` (5 s), then `running_wtf_lockers()` runs `tasklist`
    again (5 s), all synchronously in `_start` and `action_undo`.
  - `wowtools/ui/setup_screen.py:39`: `detect()` checks 26 drives × 7 sub-paths inside `__init__`.
  - `wowtools/tools/screenshot_organizer/app.py:141`: `waiting_count()` lists every flavor's Screenshots folder
    before the picker appears.
  - `wowtools/ui/base.py:96-106`: `_update_answered` calls `apply_update()` synchronously (60 s download timeout,
    git fetch with no timeout, extract and copy).
- **Problem:** each of these blocks the Textual event loop. On WSL, PowerShell alone takes about 1-3 s to start.
- **Impact:** the UI freezes with no feedback, for up to about 20 s on the clean or undo confirm path and
  open-ended during an in-app update. Users press keys again or kill the process.
- **Tag:** `[perf]`

### F-006: The event log opens and closes the file for every event, and criterion toggles emit one event per proposal item on the UI thread
- **Where:** `wowtools/core/events.py:211-220` (`_append`), `wowtools/tools/wtf_cleaner/rules.py:135-140`
  (`proposal.item` per item), `wowtools/tools/wtf_cleaner/review_screen.py:396` (`evaluate(..., log=True)` on every
  rebuild).
- **Problem:** each `log_event` does `mkdir` + `open("a")` + write + close. Every criterion toggle or max-age change
  rebuilds the proposal with logging on, so it writes `proposal.built` plus one `proposal.item` per item to the
  JSONL sink. The JSONL sink takes every level, debug included.
- **Impact:** measured on this checkout, which lives on a Windows drive under WSL: 500 events take 1378 ms on
  drvfs against 22 ms on tmpfs, about 2.75 ms per event. A 500-item proposal freezes the review screen for about
  1.4 s per toggle and fills the logs with repeated snapshots.
- **Tag:** `[perf]`

### F-007: Config saves are not atomic and can run on two threads at once
- **Where:** `wowtools/core/config.py:92-98` (`save()` truncates and rewrites in place), `wowtools/ui/base.py:70-80`
  (the update check runs `check_for_update` in a thread), `wowtools/core/updater.py:104-107` (`cfg.set` +
  `save_if_exists` from that thread), alongside UI-thread saves in `setup_screen.py:95-96` and
  `flavor_screen.py:91-92`.
- **Problem:** every other writer in the codebase uses `.partial` + `os.replace`; `Config.save()` does not. The
  `ConfigParser` is also mutated and serialized from the update-check thread while the UI thread may be doing the
  same.
- **Impact:** a crash, power loss or two concurrent writers can leave a truncated or interleaved
  `config/wow-tools.cfg`. On the next start `suite.run` refuses to launch ("Fix or delete the file") and the WoW
  path and settings are lost. Iterating while the other thread mutates can also raise `RuntimeError: dictionary
  changed size during iteration`.
- **Tag:** `[concurrency]` `[error-handling]`

### F-008: The WTF Cleaner's backup folder setting is not validated
- **Where:** `wowtools/tools/wtf_cleaner/app.py:120-126` (`CleanerSettingsScreen._save`),
  `wowtools/tools/wtf_cleaner/settings.py:55-60`.
- **Problem:** any string is accepted. A relative path (`backups`) resolves against the process's current
  directory. A folder inside `<flavor>\WTF` makes every WTF snapshot include the earlier snapshots and cleaned
  zips, so each backup is bigger than the last. The Screenshot Organizer validates its destination
  (`validate_dest`); the cleaner does not.
- **Impact:** backups end up somewhere unexpected (and Undo then cannot find them if the current directory
  changes), or backup size grows without bound and fills the disk.
- **Tag:** `[correctness]`

### F-009: The Screenshot Organizer depends on the WTF Cleaner's UI module, and review-screen scaffolding is duplicated
- **Where:** `wowtools/tools/screenshot_organizer/review_screen.py:29` imports `ConfirmScreen` from
  `wowtools.tools.wtf_cleaner.review_screen`. Duplicated pieces:
  - progress modals: `CleanProgressScreen` / `ShotProgressScreen`;
  - result screens;
  - tree helpers: `_mark` / `_refresh_labels` / `action_focus_filters` / `on_descendant_focus`;
  - `_safe_progress` (cleaner.py:184, undo.py:66, organizer.py:160 `safe_progress`);
  - `_remove`/`_discard` (backup.py, safety.py, undo.py);
  - `SUCCESS_FALLBACK` (3 copies);
  - `DAY` (rules.py, report.py).
- **Problem:** one tool depends on another tool's screen module (so opening the organizer imports the whole
  cleaner UI), and shared dialog code lives inside a tool instead of `wowtools/ui/`.
- **Impact:** a change to the cleaner's confirm dialog silently changes the organizer. A third tool will copy the
  pattern again (`docs/adding-a-tool.md` gives no shared dialog to reuse), and fixes such as F-002/F-004 have to be
  made N times.
- **Tag:** `[design]`

### F-010: Self-update runs downloaded code with no integrity check beyond TLS
- **Where:** `wowtools/core/updater.py:160-243` (`_download`, `_apply_zip`), `scripts/update_vendor.py:18-22`
  (`pip install` without `--require-hashes`).
- **Problem:** a zip install replaces its own program files with whatever `zipball_url` serves, checking only that
  `wowtools/__init__.py` carries the expected version string. There is no checksum, signature or pinned asset
  hash. Vendor rebuilds pin versions but not hashes.
- **Impact:** a compromised GitHub account or token, or a poisoned PyPI mirror during a vendor rebuild, becomes
  code execution on every user's machine at the next update. Severity is moderate because the channel is HTTPS to
  github.com and the project is small, but `auto_update = true` makes this silent.
- **Tag:** `[security]`

### F-011: The git update path can hang and is blocked by any untracked file
- **Where:** `wowtools/core/updater.py:143-157` (`_git`, `_apply_git`).
- **Problem:** `subprocess.run(["git", ...])` has no `timeout` and no `GIT_TERMINAL_PROMPT=0`, so a credential or
  SSH-passphrase prompt waits forever, invisibly behind the TUI when started from `u` (see F-005).
  `git status --porcelain` also counts untracked files, so any stray file in the install refuses the update with
  "You have local changes". That includes this `reviews/` folder, a `*.partial` leftover or a user's notes, even
  though `merge --ff-only` would only fail if a tracked path conflicted.
- **Impact:** the update hangs, or is refused for reasons the user cannot see.
- **Tag:** `[error-handling]`

### F-012: No CI, and the declared Python floor is never tested
- **Where:** no `.github/workflows/` and no lint or type-check config at the repo root; `README.md:4` and
  `wowtools/core/bootstrap.py:9` declare Python 3.10.
- **Problem:** the suite runs only when a developer runs it locally, here on 3.12. Nothing exercises 3.10/3.11 or
  native Windows, the main user platform: `os.name == "nt"` branches in `process.py`, `install.py`, `lock.py` and
  `wow-tools.cmd`. The many `# type: ignore` comments suggest a type checker was meant to run, but none is
  configured.
- **Impact:** a 3.11+-only API or a Windows-only regression ships unnoticed. `docs/releasing.md` step 1 ("make
  sure master is green") is a manual promise.
- **Tag:** `[tests]`

---

## Low

### F-013: The lock probe renames SavedVariables files before the snapshot exists
- **Where:** `wowtools/tools/wtf_cleaner/cleaner.py:132-157` (`_probe_lock`), called at `:286`, before
  `_take_safety_snapshot` at `:287`.
- **Problem:** each selected file is renamed to `<name>.wowtools-lockcheck` and back. If the process dies between
  the two renames (kill, power loss, terminal closed), the file stays renamed, and no marker or journal records it.
- **Impact:** WoW stops loading that addon's settings. On the next scan, `addon_name_for` treats the leftover as a
  stray copy of the addon (the canonical file is gone), so the tool offers to delete the only copy. The window
  per file is tiny.
- **Tag:** `[correctness]`

### F-014: "Never overwrites" has check-then-act windows on POSIX and drvfs
- **Where:** `wowtools/tools/screenshot_organizer/organizer.py:105-145` (`copy_verified`, `move_file`:
  `lexists(dst)` then `os.rename`), `wowtools/tools/wtf_cleaner/cleaner.py:149-151` (probe rename back).
- **Problem:** on POSIX, including WSL drvfs, `os.rename` replaces an existing target. A file created between the
  `lexists` check and the rename is overwritten. Windows `os.rename` fails instead, which is the behavior the code
  assumes.
- **Impact:** a rare overwrite (for example WoW writing a new screenshot or SV file in that window) on Linux and WSL.
- **Tag:** `[correctness]`

### F-015: The organizer's journal reader can raise TypeError, which escapes `latest_undoable`
- **Where:** `wowtools/tools/screenshot_organizer/journal.py:31` (`int(e.get("size", -1))` is unguarded);
  `wowtools/core/journal.py:186-189` catches only `(OSError, ValueError)`.
- **Problem:** an entry with `"size": null` (hand edit or corruption) raises `TypeError` in `_refresh_undo` on the
  UI thread. The cleaner's reader guards the same conversion.
- **Impact:** the review screen crashes on mount until the journal is deleted.
- **Tag:** `[error-handling]`

### F-016: The Screenshot Organizer's undo guard does not confine `dst`
- **Where:** `wowtools/tools/screenshot_organizer/undo.py:26-33`.
- **Problem:** `_guard` checks only that `dst` ends in `YYYY/MM/DD/<src name>`. It never checks that `dst` sits
  under the run's recorded `dest_dir/<flavor>` or the flavor's Screenshots folder.
- **Impact:** defense in depth only. A tampered or corrupted journal could make Undo move, or (in copy actions)
  delete, a same-named, same-sized file anywhere that matches the date pattern. The cleaner's `destination()` is
  strict by comparison.
- **Tag:** `[security]`

### F-017: The organizer's undo marks the journal undone even when every entry failed
- **Where:** `wowtools/tools/screenshot_organizer/undo.py:105-108`. Compare
  `wowtools/tools/wtf_cleaner/undo.py:224-226`.
- **Problem:** the cleaner keeps a journal undoable when nothing was restored and something failed (for example an
  unplugged archive drive). The organizer always calls `mark_undone`.
- **Impact:** after a transient failure, Undo is gone for good, and the two tools behave differently.
- **Tag:** `[correctness]`

### F-018: Cleaned zips, dry-run zips and update backups are never pruned
- **Where:** `wowtools/tools/wtf_cleaner/cleaner.py:362-387` (cleaned zips; a dry run with backups on writes one
  too), `wowtools/core/updater.py:221-224` (`.update-backup/<version>` per update).
- **Problem:** this is documented in `docs/wtf-cleaner.md:165`, but dry runs, which users run repeatedly, add a
  zip every time.
- **Impact:** slow, unbounded disk growth next to the WoW install and the program folder.
- **Tag:** `[design]`

### F-019: A zip update deletes every `*.md` file in the install root
- **Where:** `wowtools/core/updater.py:169-172` (`_managed_names` globs `*.md`).
- **Problem:** user-created markdown files in the install root (notes, a copied guide) count as program files.
  They are removed (backed up to `.update-backup/`) and not restored.
- **Impact:** user files silently disappear from the folder after an update.
- **Tag:** `[correctness]`

### F-020: On Windows, a zip update rewrites `wow-tools.cmd` while cmd.exe is still running it
- **Where:** `wowtools/core/updater.py:117` (`MANAGED_FILES` includes `wow-tools.cmd`), `wow-tools.cmd:6-11`.
- **Problem:** cmd.exe reads batch files incrementally by byte offset. After `py -3 -m wowtools` returns,
  `exit /b %ERRORLEVEL%` on line 11 is read from the new file at the old offset.
- **Impact:** if a release changes `wow-tools.cmd`, the first exit after updating can run a fragment of a line or
  print a confusing error.
- **Tag:** `[correctness]`

### F-021: WSL is detected two different ways
- **Where:** `wowtools/core/lock.py:52-53` (`platform.release()`) and `wowtools/core/paths.py:16-22`
  (`/proc/version`).
- **Problem:** the two checks can disagree (custom WSL kernels), which changes `LockInfo.stale` and lock-platform
  matching.
- **Impact:** an inconsistent stale-lock diagnosis.
- **Tag:** `[correctness]`

### F-022: `CleanError` has class-level mutable defaults
- **Where:** `wowtools/tools/wtf_cleaner/cleaner.py:35-40` (`restored: list[str] = []`).
- **Problem:** every `CleanError` without an explicit `restored` shares one list object.
- **Impact:** latent. Any future `error.restored.append(...)` would leak into every other instance.
- **Tag:** `[correctness]`

### F-023: Dead code and duplicated literals
- **Where:** `JournalWriter.is_open` (`core/journal.py:79-81`), `FolderMerge.changed` (`core/migrate.py:43-45`) and
  `ProposalItem.scope` (`tools/wtf_cleaner/rules.py:62-64`) have zero callers in `wowtools/`, `scripts/` or
  `tests/`. `"wow-tools"` is defined three times: `core/journal.py:23 TOOLS_SUBDIR`,
  `core/migrate.py:21 WOW_TOOLS_DIR`, and `tools/wtf_cleaner/settings.py:12` (which also hardcodes `"wtf-cleaner"`
  instead of `TOOL_NAME`).
- **Impact:** small maintenance drag. If one of the folder names changes, the others drift.
- **Tag:** `[dead-code]`

### F-024: Convention drift on `from __future__ import annotations`, and import order
- **Where:** all 32 `tests/*.py` files and the package `__init__.py` files lack the future import that `CLAUDE.md`
  says belongs in "every module". `wowtools/tools/wtf_cleaner/multi.py:12` puts `from wowtools import __version__`
  inside the `wowtools.core` import block.
- **Impact:** the rule as written does not match practice. Either fix the files or narrow the rule.
- **Tag:** `[naming]`

### F-025: `wow_check_for` reassigns `unknown` on every loop iteration
- **Where:** `wowtools/core/process.py:166-171`.
- **Problem:** `found, unknown = processes_for_flavor(...)` overwrites `unknown` for each folder. This works only
  because `unknown` does not depend on the folder, and the code reads like a bug.
- **Impact:** a maintenance trap.
- **Tag:** `[naming]`

### F-026: A future `last_update_check` suppresses update checks indefinitely
- **Where:** `wowtools/core/updater.py:89-90`.
- **Problem:** `now - last < CHECK_INTERVAL` holds for any `last` in the future (clock skew, a manual edit, a
  config copied from another machine).
- **Impact:** no update notice until the clock passes that stamp.
- **Tag:** `[correctness]`

### F-027: In copy mode with in-place filing, already-filed screenshots stay "waiting" forever
- **Where:** `wowtools/tools/screenshot_organizer/planner.py:116-125` (`waiting_count`), `scan` (`:154-178`).
- **Problem:** in copy mode the original stays at the top level. Every later scan counts it as "to file" and
  reports `ALREADY_FILED` after hashing it again.
- **Impact:** a misleading flavor-picker count and repeated hashing of the whole backlog on every run.
- **Tag:** `[perf]`

### F-028: Backup names have one-second resolution, and `os.replace` overwrites a same-second file
- **Where:** `wowtools/tools/wtf_cleaner/safety.py:102-104` (`snapshot_path`), `cleaner.py:362-365`
  (`cleaned_zip_path`), `safety.py:89` and `core/backup.py:78` (`os.replace`).
- **Problem:** two cleans of the same flavor within one second (scripted tests, a fast double confirm) write the
  same name, and the second silently replaces the first. Journals avoid this with `-2` suffixes.
- **Impact:** an earlier backup that an older journal refers to can be lost. Unlikely in interactive use.
- **Tag:** `[correctness]`

### F-029: The organizer's destination check misses other WoW folders and is not re-checked at scan time
- **Where:** `wowtools/tools/screenshot_organizer/settings.py:58-72` (`validate_dest`); `ShotReviewScreen` uses
  `settings.dest_dir` without re-validating it.
- **Problem:** only the WoW root and the Screenshots folders are refused. `<flavor>\WTF` and
  `<flavor>\Interface\AddOns` are accepted, which puts date folders inside the WTF tree that the cleaner snapshots.
  A hand-edited `dest_dir` (relative, or inside Screenshots) is never checked.
- **Impact:** odd folder layouts, and a manual misconfiguration skips the safety check entirely.
- **Tag:** `[correctness]`
