# Ace3 Profile Manager — status ledger

Plan: `2026-10-04-ace-profiles.md`. Spec: `../specs/2026-10-04-ace-profiles-design.md`.
Branch: `feat/ace-profiles`. Resume at the first task not marked `done`. Update this file and commit it after
every task; push after each milestone. Never merge without the user's go-ahead. At the end of the run, after the
merge, delete every branch, stash and worktree this run created.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| 0 | spec and plan | done | b5d55ca | plan code for Tasks 2–10 pre-validated against its own tests in a scratch copy (102 tests); parser read all 750 real SV files (read-only) with no error, 53 AceDB DBs, 12 MB Questie in 0.9 s |
| 1 | core helpers: snapshot, svfiles, atomic_write_bytes | done | 15c1cf9 | core/snapshot.py + core/svfiles.py; WTF Cleaner wraps them (messages, names unchanged); 3 test patch targets moved to core, no assertion changed; full suite 811 OK, ruff clean |
| 2 | luasv parser, splice, codec | done | 5c8b888 | plan code verbatim apart from ruff fixes; 19 luasv tests OK (speed test ~0.1 s); full suite 830 OK, ruff clean |
| 3 | model: find AceDB databases | done | 20db114 | plan code verbatim; 9 ace_model tests OK; full suite 839 OK, ruff clean |
| 4 | events, settings | done | 7ca6a9a | plan code verbatim (core `get_int` already falls back on bad values); 6 ace_settings tests OK; docs/events.md gains the `ace-profiles` section; full suite 845 OK (2 skipped), ruff clean |
| 5 | fixture + scanner | done | 98474e8 | plan code verbatim (install `ErrorHandler` is `(Path, OSError)`, capture records use `event`); fixtures.py docstring gains a `build_ace_tree`/`ace_lua` paragraph; 9 ace_scanner tests OK; full suite 854 OK (2 skipped), ruff clean |
| 6 | ops: staging | done | b0a42fe | plan code verbatim; test drops the unused `DbKey` import (ruff F401); 16 ace_ops tests OK; full suite 870 OK (2 skipped), ruff clean |
| 7 | compile + verify | done | 98f572d | plan code verbatim (`FileEdit.file` typed `SvFile \| None` as the plan notes); test file drops the plan's `# tests/...` path comment; 11 ace_compile tests OK; full suite 881 OK (2 skipped), ruff clean; not pushed by the task agent (milestone push left to the orchestrator) |
| M1 | push milestone 1 | done (pushed) | 0e27823 | review fixes: module-only profiles kept, verify covers namespaces, partial write never follows a link; full suite 888 OK (2 skipped), ruff clean |
| 8 | journal + editor | done | fe6fc85 | plan code verbatim apart from one ruff `noqa: BLE001` on the deliberate `except BaseException` (roll back, then re-raise); 3 ace_journal + 11 ace_editor tests OK; ace 340 OK; full suite 902 OK (2 skipped), ruff clean |
| 9 | undo, recovery, multi | done | f62f843 | plan code verbatim apart from a ruff fix in the test and the `ace.apply_completed` warning level; 6 ace_undo + 5 ace_multi tests OK; ace 351 OK; full suite 913 OK (2 skipped), ruff clean |
| 10 | report helpers | done | a7d0f81 | plan code verbatim (`FLAVOR_NAMES` is public in `core/install.py`); test file drops the plan's `# tests/...` path comment; 7 ace_report tests OK; ace 358 OK; full suite 920 OK (2 skipped), ruff clean; milestone push left to the orchestrator |
| M2 | push milestone 2 | done (pushed) | 8c6f4fd | review fixes: zips kept when a journal is unreadable, recovery only reverts what the run wrote, a stopped flavor's result reaches the report, marker write failure is an ApplyError, removed characters under the right profile row; full suite 928 OK (2 skipped), ruff clean |
| 11 | flow, settings screen, registration | done | 60460ad | tool registered after Interface Backup; settings screen + flow mirror the WTF Cleaner's; review screen is the Task 12 layout stub (filters pane, four buttons, `ProfileTree #profiles`, f/Esc/t/q); README row + guide link, `docs/ace-profiles.md` stub; events.md unchanged by regeneration; 3 ace_app tests OK; ace 369 OK; full suite 931 OK (2 skipped), ruff clean |
| 12 | review screen: tree, ticks, filters, blacklist | done | 33bbe9a | tree building split into `tree_view.py` (`TreeBuilder`, `Filters`, `ident`) as the plan allows; screen 570 lines; d/p/e/k/o/m/x/w/y/z are notify stubs for Tasks 13–14; recovery marker is read and kept on `self.marker` (`offer_recovery` notifies until Task 14); 9 ace_app tests OK (+1 added); ace 375 OK; full suite 937 OK (2 skipped), ruff clean; events.md unchanged |
| 13 | popups + staging from the tree | done | 9a888c0 | `popups.py` (`TargetScreen`, `NameScreen`, `ActionsScreen`, shared `popup_css`); d/p/e/k/o/m/x staged from the tree, refusals notified as warnings, ticks of changed databases cleared; w/y/z stay stubs for Task 14; 5 StagingTest tests OK; ace 380 OK; structure OK; full suite 942 OK (2 skipped), ruff clean |
| 14 | apply, dry run, undo, recovery, result screens | done | 3fbdd3d | `result_screen.py` (`ProfileResultScreen`); `ProfileProgressScreen`, `ProfileRecoveryScreen` and the w/y/z, recovery and stale-rescan flows in `review_screen.py`; `apply_confirm` names the flavors; left pane made to fit 80x24 (look-and-feel test); 4 RunTest tests OK; ace 384 OK; look_and_feel 3 OK; full suite 946 OK (2 skipped), ruff clean; events.md unchanged; milestone push left to the orchestrator |
| M3 | push milestone 3 | done (pushed) | 131119c | review fixes: blacklisting drops staged changes, Undo/recovery check the WoW of the flavor they touch, recovery guarded like Undo, leaving asks, popups fit 80x24, delete target, menu lists hidden keys, dry-run Back, search expands; full suite 965 OK (2 skipped), ruff clean |
| 15 | docs + final battery | done | 4b7c156 | full guide `docs/ace-profiles.md` (every key, tags, staged marks, blacklist, never touched, Apply/Dry run/results/Undo, backups, recovery, settings, FAQ, troubleshooting, screenshots placeholder); README settings row, undo, FAQ, version history; architecture: core `snapshot`/`svfiles`/`atomic_write_bytes`, `[ace_profiles]` schema, data flow and screens; adding-a-tool notes the core helpers; CLAUDE.md tool list; events.md unchanged by regeneration; +1 docs test; ace 404 OK; full suite 966 OK (2 skipped), serial run 966 OK; ruff clean; not pushed (milestone push left to the orchestrator) |
| M4 | push, ask for merge go-ahead | done (pushed; awaiting merge go-ahead) | 0360805 | review fixes: Apply refuses (and the screen re-offers recovery) while an earlier marker is there, recovery marks the journal, Undo/recovery prune snapshots, backup folder validated before use, Apply checks only the changed flavors' WoW, docs/spec/events corrected; full suite 975 OK (2 skipped), ruff clean |

## Decisions taken during the build

- Task 1: `atomic_write_text` delegates as `atomic_write_bytes(path, text.replace("\n", os.linesep).encode("utf-8"))`,
  not plain `.encode("utf-8")`: the old text-mode write turned `\n` into CRLF on Windows, and config files keep that.
- Task 1: patch targets moved to core (no assertion changed): `test_cleaner.LockAndCheckTest._lock` and
  `test_no_replace_call_sites` patch `wowtools.core.svfiles.rename_no_replace`; the never-replaces snapshot test
  patches `wowtools.core.snapshot.snapshot_path`.
- Task 1: `safety.py` gains `SNAPSHOT_PREFIX = "backup"`; `LIST_REPORT_EVERY`/`SnapshotProgress`/`wtf_files` and
  `cleaner.LOCK_PROBE_SUFFIX` stay importable from their old modules as re-exports (`# noqa: F401`).
- Task 2: ruff fixes only, no behaviour change: `re.S`/`re.I` spelled `re.DOTALL`/`re.IGNORECASE`, `splice` uses
  `itertools.pairwise`, and the test drops the unused `Scalar` import.
- Task 6: ruff fix only: `tests/test_ace_ops.py` drops the unused `DbKey` import; no assertion changed.
- Task 7: `tests/test_ace_compile.py` drops the plan's leading `# tests/test_ace_compile.py` comment so the docstring
  comes first, as in the other test modules; the plan's `git push` in Step 5 is left to the milestone step.
- M1 review: fixed (two findings, one bug): compile deleted every `namespaces[*].profiles` entry with no main
  `profiles` entry on any edit to that database, unreported and passed by verify. `DbState.module_only` now tracks
  these module-only profiles (original -> staged name, None = deleted); they change only when a delete or rename
  names them (a referenced missing profile carries its module data along), the change shows in `changes()`, and
  rename/copy onto one is refused (`DbState.taken`). Keep only Default leaves unreferenced module-only profiles
  alone, as they are not shown as profiles. Spec §7/§8.1 intent kept; the collision refusal is new behaviour.
- M1 review: fixed: verify skipped the whole `namespaces` section. It now compares it byte for byte with only the
  inside of each module's `profiles` table and the LibDualSpec spec values cut out (spec §2 "only ... may
  change"); `model._namespaces`/`_lds` became public `namespace_profiles`/`lds_chars` for this.
- M1 review: fixed: `atomic_write_bytes` followed a symlink sitting at `<name>.partial`. It now removes whatever is
  there (a link is unlinked, never followed) and creates the partial with `O_CREAT|O_EXCL` (+`O_NOFOLLOW`).
- M1 review: no finding rejected.
- Task 8: `editor.apply_flavor`'s `except BaseException` (roll back on anything, even Ctrl+C, then re-raise)
  carries `# noqa: BLE001` with that reason; ruff flagged it, behaviour unchanged.
- Task 9: `multi.apply_flavors` logs `ace.apply_completed` with `level="warning"` when any file was skipped or
  failed or a flavor stopped, as the event's registered description says (the plan logged it at info always).
- Task 9: ruff C408 only: `tests/test_ace_multi.py` builds the `run_plan` options as a dict literal, not `dict()`;
  no assertion changed.
- Task 10: `tests/test_ace_report.py` drops the plan's leading `# tests/test_ace_report.py` comment (as in Task 7);
  the plan's `git push` in Step 5 is left to the milestone step.
- M2 review: fixed: `referenced_zips` skipped a journal it could not read, so `prune_edited_zips` deleted the
  originals zip of a journal still offered for Undo. It now returns None on any read failure and the prune deletes
  nothing that time (a journal that stays unreadable blocks zip pruning until it is gone; the safe side).
- M2 review: fixed (two findings, one bug): `recover()` reverted every marker file whose hash differed from the
  original, including files the run skipped as changed since the scan and files WoW saved after the crash. The
  marker gains `after` (rel -> SHA-256 of what the run writes); recovery puts back only files still at that hash
  and skips the rest (`ace.file_skipped`). Spec §9 step 5 and the recovery paragraph updated: this changes the
  spec's "only files whose hash differs from the original" rule. `RecoverTest`'s existing test now writes "what
  the run wrote" with a matching `after` hash instead of "half written" (atomic writes never leave a half file);
  its assertions are unchanged. Not done: a WTF snapshot before recovery; with the hash rule recovery only
  overwrites bytes the run itself wrote, and the failed run's own snapshot already exists.
- M2 review: fixed (two findings, one bug): a flavor that stopped with ApplyError lost its ApplyResult.
  `ApplyError.result` now carries it (set by `apply_flavor` for every refusal) and `apply_flavors` keeps it on the
  `FlavorRun`, so the report shows put-back files, the stopped flavor's WTF snapshot and originals zip. New
  outcomes: a file that could not be put back becomes "failed" (detail names the zip), and the file whose write
  failed gets a "rolled_back" or "failed" outcome; `apply_summary_rows` gains a "Failed" row.
- M2 review: fixed: an OSError writing the crash marker escaped as a raw OSError past `apply_flavors`. It is now
  `ApplyError("The crash marker could not be written (...). Nothing was changed.")` with a new
  `ace.marker_failed` event (error); docs/events.md regenerated.
- M2 review: fixed (two findings, one bug): `profile_rows` put a removed character under the first deleted row or
  a phantom "missing" row when its profile was renamed or gone. It now goes under the row of its profile's
  current name (renamed, deleted or kept), else a "missing" row named after its old profile.
- M2 review: no finding rejected.
- Task 11: scope label for one flavor with a chosen account is `"<flavor> · <account>"` (plan named only
  "All flavors"); picker choices (`last_flavor_choice`, `last_account`) are saved with `source="picker"`, as the
  plan says. No `ace.settings_saved` log: that event is not in the registry (config changes already log
  `config.changed`). `docs/ace-profiles.md` stub and README rows are worded for users; Task 15 writes the guide.
- Task 12: `test_tick_a_profile_and_summary_counts` mechanic adapted, assertions unchanged: the plan expanded only
  the profile's parent and moved the cursor at once, but the ElvUI addon node above it starts collapsed and a
  newly shown node has no line until the tree lays out, so `move_cursor` landed on the root (verified: it ticked
  every profile). The test now expands every ancestor and settles before `move_cursor`.
- Task 12: the tree is built by `wowtools/tools/ace_profiles/tree_view.py` (fifth UI module, as the plan allows).
  A profile node ticks only its own `"p"` key, but a group above it covers the profile and its characters. Each
  rebuild keeps expansion and the highlighted node, and lays the lines out at once so `move_cursor` finds new
  nodes. Group nodes left empty by a filter or search are dropped; with no filter, an account without AceDB data
  shows "no Ace3 data". "Only unused profiles" applies to the By addon view only; "Only addons with 2+ profiles"
  filters per database. Space typed in the search box goes into it (Space is priority-bound for ticking).
- Task 12: added `test_all_ticks_visible_profiles_and_characters` (`a` ticks profiles and characters, only
  visible ones under a search; hidden ticks survive clearing the search).
- Task 13: the popups import goes in the sorted import block of `tests/test_ace_app.py`, not appended with
  `# noqa: E402`. Quick actions (Keep only Default, Everyone → Default) with nothing ticked act on the highlighted
  node's database (a profile, character or database node) or every database of a highlighted addon; on any other
  node they notify "Tick or highlight an addon first". The rename/copy `NameScreen` also refuses a name already
  taken in that database (staging refuses it too). Ticks are cleared only for databases the operation changed;
  refused ones keep theirs.
- Task 14: the left pane did not fit 80x24 once the tool joined `test_look_and_feel` (buttons at row 32). The
  checkboxes and the search box are `compact=True` (as in the WTF Cleaner), the two View boxes share one row, the
  "Search" and "Staged" section headings are gone: the search box's placeholder reads "Search addon, profile or
  character" and the staged line reads "Staged: <kinds>" (spec §13 sections kept, only their headings merged).
- Task 14: `test_recovery_offered_and_put_back` writes the marker with `after = {rel: sha256(b"torn")}`: since the
  M2 review, recovery puts back only a file still at what the run wrote, and a marker without `after` would leave
  the torn file alone. Assertions unchanged. `test_dry_run_...` unpacks `_review` (ruff RUF059); the new imports go
  in the sorted import block (as in Task 13), not appended with `# noqa: E402`.
- Task 14: the dry run skips the running-WoW check (it writes nothing; the plan's step 3 acts on the check only
  for Apply), so no process listing delays it. Apply and Undo run the check in a worker and refuse while WoW runs;
  a check that cannot run adds the plan's alert to the confirm.
- Task 14: after a real Apply, an Undo, or an unexpected crash in either, the staging is discarded and the review
  is marked stale: it rescans without asking when shown again (result "Rescan", or on resume). After a dry run,
  Rescan goes through the usual "Discard staged changes?" confirm, so the staging can be kept. Esc on the result
  screen is Rescan, as in the WTF Cleaner. A stopped flavor still shows the result screen, with an error notify.
- Task 14: the recovery popup closed with Esc (no choice) leaves the marker, so it is offered again at the next
  scan; "Put the originals back" runs `recover` under the progress screen, notifies the counts and rescans.
- M3 review: fixed (three findings, one bug): blacklisting an addon (`b`), locking it again (`u`) or blacklisting it
  in settings left its staged changes in place and Apply wrote them. `Staging.drop_locked()` resets a locked
  addon's databases (called by `b`/`u`, before Apply/dry run and when the review is shown again, with a warning
  naming the addons), and `Staging.changed()`/`summary()` never include a locked addon (the last guard). Spec §3
  intent kept ("can't be ticked or changed").
- M3 review: fixed (two findings, one bug): Undo ran the running-WoW check for the reviewed flavors only, while the
  journal is the newest of the whole tool. The check is now built from the flavors the journal changed
  (`ProfileReviewScreen.check_for`, as the WTF Cleaner does) for the preflight and inside `undo_run`;
  `undo_confirm` names those flavors. An injected test check still stands for every flavor.
- M3 review: fixed (two findings, one bug): "Put the originals back" had no running-WoW check. It now runs the
  preflight for the marker's flavor and `recover()` takes `wow_check` and `progress`, probes locks and takes a WTF
  snapshot first (only when a file is to be put back), like `undo_run` (shared `_refuse_running`,
  `_refuse_locked`, `_snapshot`). Refused: the marker stays and is offered at the next scan. This reverses the M2
  note "Not done: a WTF snapshot before recovery"; spec recovery paragraph updated.
- M3 review: fixed: Esc/`f`/`t`/`q` dropped staged changes silently (Esc even from the search box). Leaving with
  changes staged now asks "Leave and discard the staged changes?" (also from a dry-run result); Esc in the search
  box returns to the tree; the Undo confirm adds a line when staged changes will be dropped. Spec keys paragraph
  updated.
- M3 review: fixed: the Delete/Assign/Name popups clipped their controls at 80x24. The box is `max-height: 100%`
  (scrolls if ever needed), the Select and Inputs are compact, the error line takes no room until there is an
  error and the body gets at most 35vh. The recovery box is 80 wide (was 90) with `max-width: 100%`.
- M3 review: fixed: the delete target always offered and preselected "Default", even when it was being deleted.
  `_targets` leaves out every profile being deleted (Default included); `TargetScreen` preselects `default` only
  when offered, else the first; with nothing left only a new name is asked for. Refusals are one notification
  (at most 8 lines), and `_addon_name` adds the flavor/account when the same addon is in another one. Spec popups
  paragraph updated.
- M3 review: fixed: `e`, `k`, `o`, `b`, `u`, `v`, `/`, `x` were shown nowhere. The `m` menu now lists each (label
  names the key) and runs it. The footer and left-pane hint are unchanged (the hint must fit 80x24); the guide
  (Task 15) lists every key.
- M3 review: fixed: Esc and the focused button on a dry-run result led to "Discard staged changes?". A dry-run
  result adds a focused "Back to review (Esc)" button (after Rescan, which stays first as on every result screen)
  and Esc goes back with the staging kept. Apply/Undo results keep Esc = Rescan.
- M3 review: fixed: a search left addon nodes collapsed in By addon view. While searching every group shown is
  open (scan warnings excepted) and the expansion state is not recorded, so clearing the search restores it.
- M3 review: no finding rejected. Regression tests: `ReviewFixesTest` (15, `tests/test_ace_app.py`), three
  `RecoverTest` cases (`tests/test_ace_undo.py`), one ops test; each failed on the code before the fix.
- Task 15: `tests/test_docs.py` gains `test_ace_profiles_guide_and_readme` (the guide covers the plan's topics and every
  review key, the README names `config\ace-profiles.cfg`, CLAUDE.md lists the tool), written before the docs as the
  task's failing test. `docs/adding-a-tool.md` gains one bullet (shared code moves to core: `core/snapshot.py`,
  `core/svfiles.py`, `atomic_write_bytes`), as Task 1 changed that step. The plan's `git add -A docs ...` and
  `git push` are replaced by adding only the changed files; the push is left to the milestone step.
- M4 (final, whole branch) review:
  - fixed (two findings, one cause): a new Apply silently overwrote, then cleared, an earlier unfinished Apply's
    crash marker, losing its recovery (and its edited zip to pruning). `editor._apply` now refuses a real run while
    a marker is there (`ApplyError`, "Nothing was changed", new event `ace.earlier_unfinished`, error level), as
    the WTF Cleaner does; a dry run is still allowed. The review screen re-offers `ProfileRecoveryScreen` when Apply
    is pressed with `self.marker` set. Spec §9 step 2 updated.
  - fixed: after recovery put files back, the crashed run's journal still offered them for Undo ("changed since").
    `recover(..., journal_dir=)` appends a `rolled_back` line (`journal.record_recovered`, via the new
    `core.journal.append_record`, which `mark_undone` now uses) to the journal whose entries came from the
    marker's zip, for every file now at its original. Spec recovery paragraph updated.
  - fixed: Undo and recovery never pruned their WTF snapshots. `undo_run` uses its `keep_snapshots`; `recover`
    gains `keep_snapshots=` (the screen passes the setting). Spec §10 updated.
  - fixed: the backup folder was validated only on save. The review screen runs `validate_backup_dir` before an
    Apply, an Undo and a recovery ("Backup folder not allowed", as the WTF Cleaner and Interface Backup do); a dry
    run writes nothing and is not checked.
  - fixed (code, not docs): Apply's running-WoW check covered every reviewed flavor; it now covers only the
    flavors with staged changes (`apply_check`), as the guide and spec §3 say.
  - fixed (docs): per-character addon label is `Addon (Realm/Name)`; Scan warnings sit at the bottom of the tree;
    roll-back is per game version (earlier flavors keep their changes); the typed-name delete case needs "Default"
    deleted too; Details dropped as an Ace3 example (its own profiles aren't covered); `#result-detail` in the
    architecture; `ace.unlocked` and `ace.recovery_offered` descriptions (docs/events.md regenerated).
  - fixed (spec): §13 staged marks and result summary rewritten to what was built (the guide already matched).
  - no finding rejected. Regression tests: `FinalReviewFixesTest` (3, `tests/test_ace_app.py`),
    `RecoverJournalTest` (3) and an Undo prune test (`tests/test_ace_undo.py`), an editor marker test, a
    `record_recovered` journal test; each failed on the code before the fix.
- Final check (orchestrator): read-only scan of the real install (all flavors) in 6.2 s, 53 AceDB databases, 0 warnings, 233 leftover character entries; an in-memory edit + verify of every database gave 0 problems (nothing written).
