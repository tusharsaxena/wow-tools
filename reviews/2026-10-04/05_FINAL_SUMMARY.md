# Final summary: wow-tools review-and-fix cycle (2026-10-04)

> Written as if every check in `03_TEST_PLAN.md` has passed and the plan in `04_EXECUTION_PLAN.md` has been
> carried out. Fill in the commit range and PR link under "Verification evidence" when that is true.

## Headline
This cycle makes the two tools safer in the situations they did not yet cover. The WTF Cleaner no longer
pre-selects the settings of installed addons when an account has no character folders. The app no longer lets
you quit, and no longer releases its one-copy lock, while files are still being deleted or moved. Unexpected
errors are now shown and logged instead of silently closing the app. Config saves and the self-updater can no
longer corrupt or half-replace the installation: saves are atomic, updates verify a published checksum, git
updates time out instead of hanging, and only shipped files are replaced. The screens stay responsive while the
tool checks for running programs, detects WoW, counts screenshots or downloads an update. Log writes are about
10× cheaper on WSL drives. Shared dialogs now live in one place, and CI runs the suite on Python 3.10 and 3.13 on
Linux and Windows.

## Counts
`Critical fixed: 0, High fixed: 2, Medium fixed: 10, Low fixed: 15`

Deliberately deferred:
- **F-018 (part): retention for cleaned zips (`keep_cleaned`).** Today's "kept until you delete them" behavior is
  documented and users may rely on it. Pruning `.update-backup/` shipped.
- **F-027: copy mode in place.** This is a product decision: either require a destination for copy mode, or
  track filed copies. Neither is a bug fix.
- **F-001 follow-up: per-account "enabled" sets.** More precise, but it would make all-accounts scans propose
  more. The shipped fix is the conservative one.

(All 29 findings are accounted for: 27 fixed in full, F-018 fixed in part, F-027 deferred. The Low count of 15
excludes F-018 and F-027.)

## Changes by theme

### T1. Evidence-based cleaner proposals
- **What changed:** when the scanned accounts have no character folders, every installed addon counts as
  enabled, and the scan says so in a warning.
- **Why it mattered:** the pre-ticked "not enabled" rule proposed deleting the settings of every installed addon
  on such accounts.
- **Findings covered:** F-001. **Changes:** C-01.
- **Files:** `wowtools/tools/wtf_cleaner/scanner.py`, `tests/test_scanner.py`, `tests/test_rules.py`.

### T2. Safe lifecycle for long-running work
- **What changed:** Ctrl+Q is refused while a run is busy. The launcher waits for any running worker before it
  releases `wow-tools.lock`. UI crashes are written to the event log and give a non-zero exit code. The WTF
  Cleaner's clean worker reports unexpected errors instead of closing the app.
- **Why it mattered:** quitting mid-run let a second copy start on the same folders while the first was still
  writing, and crashes were logged as clean exits.
- **Findings covered:** F-002, F-003, F-004. **Changes:** C-02, C-03, C-04.
- **Files:** `wowtools/ui/base.py`, `wowtools/suite.py`, `wowtools/core/activity.py` (new),
  `wowtools/tools/wtf_cleaner/review_screen.py`, `wowtools/tools/screenshot_organizer/review_screen.py`, tests.

### T3. A responsive UI
- **What changed:** process checks (PowerShell/tasklist), install detection, flavor screenshot counts and update
  downloads now run in background workers behind a "Checking…" or progress state. The event log keeps its files
  open and flushes each line. Interactive criterion toggles no longer write one log line per proposal item.
- **Why it mattered:** the UI froze for up to about 20 s on confirm, and for an unbounded time during in-app
  updates. 500 log events cost 1.4 s on WSL drives.
- **Findings covered:** F-005, F-006. **Changes:** C-05, C-06.
- **Files:** `wowtools/core/events.py`, `wowtools/tools/wtf_cleaner/rules.py`,
  `wowtools/tools/wtf_cleaner/review_screen.py`, `wowtools/ui/setup_screen.py`, `wowtools/ui/flavor_screen.py`,
  `wowtools/tools/screenshot_organizer/app.py`, `wowtools/ui/base.py`, tests.

### T4. Durable config
- **What changed:** `Config.save()` writes through `.partial` + `os.replace`. The background update check hands its
  values to the UI thread to save.
- **Why it mattered:** a truncated `config/wow-tools.cfg` stops the app from starting and loses the user's
  settings.
- **Findings covered:** F-007. **Changes:** C-07.
- **Files:** `wowtools/core/fsutil.py` (new), `wowtools/core/config.py`, `wowtools/core/migrate.py`,
  `wowtools/core/updater.py`, `wowtools/ui/base.py`, tests.

### T5. Validated output folders
- **What changed:** the cleaner's backup folder and the organizer's destination must be full paths outside the WoW
  root and outside any flavor's `WTF`, `Interface` or `Screenshots` folder. They are checked on save and again
  before scanning or cleaning.
- **Why it mattered:** relative paths landed wherever the program was started from, and a backup folder inside
  `WTF` made every backup contain all the earlier ones.
- **Findings covered:** F-008, F-029. **Changes:** C-08.
- **Files:** `wowtools/core/install.py`, `wowtools/tools/wtf_cleaner/app.py`,
  `wowtools/tools/wtf_cleaner/review_screen.py`, `wowtools/tools/screenshot_organizer/settings.py`,
  `wowtools/tools/screenshot_organizer/review_screen.py`, tests.

### T6. Shared UI building blocks
- **What changed:** `ConfirmScreen` and a generic `ProgressScreen` moved to `wowtools/ui/dialogs.py`. Progress and
  file helpers moved to `wowtools/core/fsutil.py`. Unused methods were removed, the `wow-tools` folder name is
  defined once, and the future-import convention was aligned.
- **Why it mattered:** the Screenshot Organizer imported the WTF Cleaner's screen module, and fixes had to be
  copied N times.
- **Findings covered:** F-009, F-023, F-024. **Changes:** C-09.
- **Files:** `wowtools/ui/dialogs.py` (new), `wowtools/core/fsutil.py`, both tools' review, result and logic
  modules, `wowtools/core/{backup,journal,migrate}.py`, `docs/architecture.md`, `docs/adding-a-tool.md`,
  `CLAUDE.md`.

### T7. Updater hardening
- **What changed:** zip updates download the release's `wow-tools-vX.Y.Z.zip` and check it against the published
  `SHA256SUMS` before touching anything. Git commands time out after 120 s, never prompt, and ignore untracked
  files. Only files the release ships are replaced, so user `*.md` notes survive. `.update-backup/` keeps the
  newest two versions. A future `last_update_check` no longer suppresses checks. `wow-tools.cmd` exits from
  inside its parsed block, so an update can safely replace it.
- **Why it mattered:** the updater replaces the program in place, often automatically. It could install
  unverified code, hang behind the TUI, refuse because of a stray file, or delete user files.
- **Findings covered:** F-010, F-011, F-018 (part), F-019, F-020, F-026. **Changes:** C-10, C-11, C-18, C-19,
  C-20, C-24.
- **Files:** `wowtools/core/updater.py`, `wow-tools.cmd`, `scripts/update_vendor.py`, `requirements.lock` (new),
  `docs/releasing.md`, `docs/vendoring.md`, tests.

### T8. Consistent journals and undo
- **What changed:** the organizer's journal reader skips malformed sizes instead of crashing. Undo only touches
  files at the exact target the run would have used. A journal stays undoable when every entry failed (matching
  the cleaner).
- **Why it mattered:** one corrupt line crashed the review screen. A tampered journal could move or delete files
  elsewhere. A transient failure removed Undo for good.
- **Findings covered:** F-015, F-016, F-017. **Changes:** C-15, C-16, C-17.
- **Files:** `wowtools/tools/screenshot_organizer/{journal,undo,organizer,report}.py`, `wowtools/core/journal.py`,
  tests.

### T9. File-operation atomicity
- **What changed:** renames use a no-replace primitive (a hard link plus unlink on POSIX, `os.rename` on Windows).
  Leftover lock-probe files are recognized and renamed back before a clean. Backup zips get `-2`, `-3` suffixes
  instead of overwriting a same-second name.
- **Why it mattered:** "never overwrites" did not hold on Linux or WSL, and a crash during the lock probe could
  leave a SavedVariables file renamed and then offered for deletion as a stray copy.
- **Findings covered:** F-013, F-014, F-028. **Changes:** C-13, C-14, C-26.
- **Files:** `wowtools/core/fsutil.py`, `wowtools/tools/wtf_cleaner/{cleaner,scanner,safety,events}.py`,
  `wowtools/tools/screenshot_organizer/organizer.py`, `wowtools/core/journal.py`, `docs/events.md`, tests.

### T10. CI and a tested Python floor
- **What changed:** a GitHub Actions matrix (ubuntu and windows × Python 3.10 and 3.13) runs the suite,
  `gen_event_docs.py --check` and `compileall`.
- **Why it mattered:** the declared 3.10 floor and the Windows paths were never tested automatically.
- **Findings covered:** F-012. **Changes:** C-12.
- **Files:** `.github/workflows/tests.yml` (new).

### T11. Small correctness cleanups
- **What changed:** one WSL detection is used everywhere. `CleanError` has per-instance fields. `wow_check_for`
  computes pathless processes once.
- **Findings covered:** F-021, F-022, F-025. **Changes:** C-21, C-22, C-23.
- **Files:** `wowtools/core/lock.py`, `wowtools/tools/wtf_cleaner/cleaner.py`, `wowtools/core/process.py`, tests.

## API and behavior changes
- **Quit:** Ctrl+Q shows "A run is in progress…" instead of quitting while a clean, organize or undo runs.
- **Exit code:** the process exits with 1 (not 0) after an unhandled UI error, and `session.end` records it.
- **New config key:** `[general] allow_unverified_updates` (default `false`). When false, zip updates refuse a
  release without the `wow-tools-vX.Y.Z.zip` and `SHA256SUMS` assets.
- **Release process:** every release must attach those two assets (`docs/releasing.md`).
- **Validation:** WTF Cleaner settings refuse a relative backup folder or one inside the WoW folder's `WTF`,
  `Interface` or `Screenshots`. The same rule applies to the organizer destination, which now also refuses
  `WTF` and `Interface`. An existing invalid value is refused at clean/scan time with "Fix the folder in settings
  (s)".
- **Scanner:** a new `scan.warning` message ("no character folders: the 'not enabled' rule is not applied").
  Such accounts no longer get `not_enabled` proposals.
- **Events:** new `clean.probe_recovered` (warning). `proposal.item` is now logged once per confirmed clean
  instead of on every rebuild. `docs/events.md` was regenerated.
- **Backup names:** a same-second backup is written as `backup-<flavor>-<stamp>-2.zip` (and likewise for
  `cleaned-…`).
- **Organizer undo:** a journal stays undoable when every entry failed, and the result screen says so.
- **Update backups:** `.update-backup/` keeps only the newest two version folders.
- **Launcher:** `wow-tools.cmd` was restructured. Arguments and exit codes are unchanged.

## Migration notes
- **No data-format changes.** Journal, marker and config formats are unchanged; `allow_unverified_updates` is a new
  optional key that defaults when absent. Nothing needs migrating.
- **Manual step for some users:** if the WTF Cleaner's backup folder is set inside `WTF` or is a relative path,
  the next clean refuses until it is changed in settings (`s`). Existing backups in the old location are not moved.
  Cleaned zips referenced by existing journals keep working, because journals store absolute paths.
- **Maintainers:** the first release after this cycle must publish the checksum assets. Otherwise zip installs
  show "the release has no published checksum" and link to the release page. Git installs are unaffected.

## Dependency changes
| Dependency | Old | New | Why |
|---|---|---|---|
| textual, rich, pygments, markdown-it-py, mdit-py-plugins, linkify-it-py, mdurl, platformdirs, typing_extensions | pinned versions | same versions | unchanged; now installed with `--require-hashes` from the new `requirements.lock` |

No runtime dependencies were added or removed.

## Performance impact
Numbers from the `03_TEST_PLAN.md` spot-checks on the maintainer's WSL checkout, which is on a Windows drive
(drvfs):

| Measure | Before | After (target) |
|---|---|---|
| 500 `log_event` calls on drvfs | 1378 ms | ≤ 150 ms |
| Criterion toggle with 500 proposal items: `proposal.item` writes | 500 | 0 |
| Clean/undo confirm: UI blocked while checking processes | up to ~20 s (PowerShell 10 s + tasklist 5 s + 5 s timeouts) | < 100 ms (check runs in a worker) |
| In-app update: UI blocked | whole download, extract and copy | 0 (worker + progress modal) |

Record the measured "after" values in the sign-off table.

## Known follow-ups
- **F-018 (rest):** a `keep_cleaned` setting for the cleaned-files zips, if users ask for it. Keep the documented
  default.
- **F-027:** decide whether copy mode needs a destination, or whether filed copies should be tracked so they stop
  counting as "waiting".
- **Per-account "enabled" sets** for the cleaner: more precise proposals in multi-account installs.
- **Signed tags** (`git verify-tag`) for git installs, on top of the zip checksum.
- **A shared `TreeReviewScreen` base**: revisit when a third tool needs a tick-tree review screen.
- **Repo housekeeping:** `master` holds `release: v1.0.0`, but no `v1.0.0` tag exists locally, and the updater
  needs a published tagged release. Add `reviews/` to `.gitignore` or commit it. Until C-11 shipped, an untracked
  `reviews/` blocked `wow-tools update` on git checkouts.

## Verification evidence
- Test plan with the sign-off table filled: `reviews/2026-10-04/03_TEST_PLAN.md`.
- Branch: `fix/review-2026-10-04`. Commit range: `master..fix/review-2026-10-04` (fill in the SHAs). PR: (link).
- CI: `tests` workflow, all four jobs green on the PR head (link).

## Suggested commit message / PR description

```
fix: review fixes for cleaner proposals, run lifecycle, config durability and updater safety

High
- fix(wtf-cleaner): an account with no character folders no longer gets every installed
  addon proposed as "not enabled" (F-001)
- fix(ui): Ctrl+Q is refused while a run is busy; the instance lock is held until workers
  finish (F-002)

Medium
- fix(suite): propagate the app's return code; log UI crashes (F-003)
- fix(wtf-cleaner): unexpected clean errors are shown and logged, not fatal (F-004)
- perf(ui): process checks, install detection, flavor counts and updates run in workers (F-005)
- perf(core): log files stay open; no per-item proposal events on rebuilds (F-006)
- fix(core): atomic config saves, persisted from the UI thread only (F-007)
- fix: validate backup and destination folders on save and before use (F-008, F-029)
- refactor(ui): shared ConfirmScreen/ProgressScreen; fsutil helpers; dead code removed (F-009, F-023, F-024)
- feat(updater): verify zip updates against published SHA-256 sums; hashed vendor installs (F-010)
- fix(updater): bounded, non-interactive git updates that ignore untracked files (F-011)
- ci: Python 3.10/3.13 on Linux and Windows (F-012)

Low
- F-013 lock-probe leftovers recovered; F-014 no-replace renames; F-015..F-017 organizer
  journal/undo robustness; F-019 user *.md files survive zip updates; F-020 cmd launcher
  safe to replace; F-021 one WSL check; F-022 CleanError fields; F-025 process check
  clarity; F-026 future update stamps; F-028 unique backup names; F-018 update-backup pruning

Deferred: F-018 keep_cleaned (documented behavior), F-027 copy mode in place (product decision).
See reviews/2026-10-04/ for findings, design, test plan and sign-off.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UcpDPMuktyHqM8xWGFXb22
```

For the PR body, use the same text, ending with:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01UcpDPMuktyHqM8xWGFXb22
```
