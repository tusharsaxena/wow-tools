# Final summary: wow-tools review-and-fix cycle (2026-10-07)

> This is written as if every check in `03_TEST_PLAN.md` passed. Fill in the commit range and the measured numbers
> when the work lands.

## Headline
This cycle tightened the recovery and Undo paths shared by the Ace3 Profile Manager and the Saved Variables
Browser:
- Recovering an interrupted change now works from either Windows or WSL.
- Recovery can no longer revert a change that actually finished.
- A damaged journal can no longer make Undo read or write outside the WoW and tool folders.

The WTF Cleaner now checks each file again just before deleting it. An interrupted zip update rolls back. Smaller
fixes harden start-up, process detection, atomic writes and the test runner. The two largest review screens were
split along their natural seams, with no change in behaviour.

## Counts
`Critical fixed: 0, High fixed: 0, Medium fixed: 7, Low fixed: 7`.

Deferred: none planned. F-006 follows the user's choice: renames fixed (Option A), or the deviation documented
(Option B).

## Changes by theme

### Recovery trusts the configured install (T1)
- **What changed:** recovery finds files under the configured WoW folder. The marker's paths are stored in
  Windows form and read back for this OS. Undo snapshots only valid game-version folders.
- **Why it mattered:** a marker written on one OS made recovery on the other skip every file and delete the
  marker. A hand-edited journal could make Undo zip folders outside WoW.
- **Findings:** F-001, F-003. **Changes:** C-01, C-02.
- **Files:**
  - `wowtools/core/sv_undo.py`, `wowtools/core/sv_apply.py`
  - `wowtools/tools/ace3_profile_manager/undo.py`, `wowtools/tools/sv_browser/undo.py`
  - `wowtools/tools/ace3_profile_manager/review_screen.py`, `wowtools/tools/sv_browser/review_screen.py`
  - `tests/test_core_sv_pipeline.py`

### A finished run is never reported as interrupted (T2)
- **What changed:** removing the crash marker is retried. A failure is logged and shown on the result screen.
  Recovery leaves a run whose journal says it finished alone and only clears its marker.
- **Why it mattered:** a marker held open by an antivirus scanner could later turn one press of Enter into
  reverting a completed Apply.
- **Findings:** F-002. **Changes:** C-03.
- **Files:**
  - `wowtools/core/marker.py`, `wowtools/core/sv_apply.py`, `wowtools/core/sv_undo.py`
  - `wowtools/core/sv_events.py`, `wowtools/core/sv_report.py`
  - `docs/events.md`, `CHANGELOG.md`

### Re-check just before the change (T3)
- **What changed:** the WTF Cleaner checks each file's size and modified time again right before deleting it.
- **Why it mattered:** a file WoW saved during the WTF backup could be deleted without its newest copy anywhere.
- **Findings:** F-004. **Changes:** C-04.
- **Files:** `wowtools/tools/wtf_cleaner/cleaner.py`, `tests/test_cleaner.py`.

### All-or-nothing update (T4)
- **What changed:** a zip update rolls back on any interruption, Ctrl+C included. The CLI says where the previous
  version is saved.
- **Findings:** F-005. **Changes:** C-05.
- **Files:** `wowtools/core/updater.py`, `wowtools/suite.py`, `tests/test_updater_apply.py`.

### Standards conformance (T5)
- **What changed:** Interface Backup's folder swaps either go through `rename_no_replace` and are pinned by the
  call-site test, or are recorded as a documented deviation.
- **Findings:** F-006. **Changes:** C-06.
- **Files:** `wowtools/tools/interface_backup/restore.py`, `wowtools/tools/interface_backup/undo.py`,
  `tests/test_no_replace_call_sites.py`, or `docs/standards.md` under Option B.

### Smaller review screens (T6)
- **What changed:** the shared recovery and Undo wiring moved to `ui/review.py` (`SvRecoveryActions`), and each
  large screen's action handlers moved into mixins.
- **Findings:** F-007. **Changes:** C-07.
- **Files:**
  - `wowtools/ui/review.py`
  - the two `review_screen.py` files and their new mixin modules
  - `tests/test_structure.py`, `docs/architecture.md`, `docs/internals/*.md`

### Hardening (T7)
- **Findings:** F-008 to F-014. **Changes:** C-08 to C-14.
- **What changed:**
  - The lock is released if logging cannot start.
  - Backup partials are removed on interrupt.
  - Process listings are decoded as UTF-8.
  - Dead re-exports are gone.
  - Writes are fsynced before the atomic replace.
  - The README notes that config comments are not kept.
  - Test shards have a timeout.
- **Files:**
  - `wowtools/suite.py`, `wowtools/core/events.py`, `wowtools/core/backup.py`, `wowtools/core/process.py`
  - `wowtools/tools/wtf_cleaner/safety.py`, `wowtools/tools/ace3_profile_manager/report.py`
  - `wowtools/core/fsutil.py`
  - `README.md`, `scripts/run_tests.py`, `docs/testing.md`, `CLAUDE.md`

## API and behaviour changes
- New log events: `ace.marker_left` / `svb.marker_left` and `ace.marker_stale` / `svb.marker_stale` (registered
  through `sv_events`; `docs/events.md` regenerated).
- Recovery now **refuses** with "Nothing was changed." when the marker's game version is not in the configured WoW
  folder. Before, it skipped every file and cleared the marker.
- The WTF Cleaner can report a file as "changed" that the clean selected but WoW rewrote during the clean.
- `scripts/run_tests.py` gains `--timeout`.
- No config keys or commands change.

## Migration notes
Crash markers are now written with Windows-form paths (`to_stored`). Markers already on disk still read: a POSIX
path is left as it is, and the paths are no longer used to resolve files. No manual step is needed.

## Dependency changes
None. STD-1.4 is unchanged and `vendor/` is untouched.

## Performance impact
Only C-12 (`fsync`) can change timings. Record the median of three timed runs of
`python3 scripts/run_tests.py -k sv_pipeline -j 1`, before and after, from one session. *Fill in once measured;
do not estimate.*

## Test movement
- **Before:** 1710 run, 0 failures, 0 errors, 2 skipped (2026-10-07, `python3 scripts/run_tests.py`).
- **After:** 1710 plus the new tests in `03_TEST_PLAN.md` (about 14), all passing.
- No committed count, coverage figure or badge exists, so none moved.

## Known follow-ups
- Consider whether the SHA256SUMS check should also verify a signature. The current check proves integrity
  against GitHub, not authenticity. It was out of scope here, and the 2026-10-04 review accepted F-010's fix.
- Reconsider the WTF Cleaner's warn-only stance on a running WoW (documented deviation STD-5.3) if F-004's late
  skips show up in logs.

## Verification evidence
- `reviews/2026-10-07/03_TEST_PLAN.md` with the sign-off table filled.
- Commit range: `<base>..<head>` on `fix/review-2026-10-07`. PR: `<link>`.

## Suggested PR description

```
Review fixes 2026-10-07: recovery and Undo hardening, WTF Cleaner late recheck, update rollback

- Recovery resolves files under the configured WoW folder; markers store Windows-form paths (F-001)
- A marker that could not be cleared is reported; recovery never reverts a finished run (F-002)
- Undo snapshots only valid game-version folders (F-003, STD-5.25)
- WTF Cleaner rechecks each file right before deleting it (F-004, STD-5.7)
- Zip update rolls back on any interruption (F-005)
- Interface Backup folder swaps: rename_no_replace / documented deviation (F-006, STD-5.17)
- Ace3 and SV Browser review screens split; shared SvRecoveryActions (F-007)
- Hardening: lock release, backup partials, UTF-8 process listings, dead re-exports, fsync,
  config-comment note, shard timeout (F-008..F-014)

Green gate: run_tests.py, ruff check --no-cache ., gen_event_docs.py --check.
```
