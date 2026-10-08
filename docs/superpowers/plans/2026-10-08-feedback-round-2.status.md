# Feedback round 2: status ledger

Plan: `2026-10-08-feedback-round-2.md`. Spec: `../specs/2026-10-08-feedback-round-2-design.md`.
Branch: `fix/feedback-2026-10-07-b`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| R0 | spec, plan, ledger | done | (this commit) | written 2026-10-08 09:58 while round 1's workflow ran |
| L11 | `t` from any screen | done | (this commit) | `WowToolsApp.key_t` -> `action_tool_menu`; q's busy and staged-work logic shared (`refused_while_busy`, `ask_before_leaving`); new event `ui.tool_menu_refused`; STD-8.11 extended; tests/test_tool_menu_key.py (9 tests, every screen of every tool at BASE and LARGE); full suite 1872 tests OK (2 skipped) |
| L14 | one "Run journal" row | done | (this commit) | cause: a clean across flavors (`multi_summary_rows`) named the shared journal on top and again in every flavor block (`summary_rows`); now once on top with the Undo note, blocks pass `journal=False`; the top note is `MULTI_UNDO_NOTE` (L14-c); the other four tools already have one journal row (Ace3/SV Browser guard test added); tests in test_wtf_app.py and test_ace_report.py; full suite 1875 tests OK (2 skipped) |
| L15 | blacklist mark | done | (this commit) | `BLACKLISTED_MARK` (`⊘`), `BLACKLISTED_STYLE` (dim) and `blacklisted_mark()` in `ui/review.py`; WTF Cleaner addon and file rows, Ace3 every row of a locked addon in both views (`TreeBuilder.held`); help, guides, internals, architecture, STD-7.12, CHANGELOG; tests in test_wtf_app.py, test_ace_app.py, test_docs.py, test_structure.py; full suite 1879 tests OK (2 skipped) |
| L16 | Interface Backup `backup/` folder | done | (this commit) | zips in `<root>/backup` (`catalog.ZIPS_SUBDIR`, `zips_dir`); `move_old_zips` in the review scan worker, `rename_no_replace`, new event `ibackup.zips_moved` (warning when a taken or failed name is left); listing and pruning span both places; Undo finds an older run's safety zip by name (`zip_now_at`); `core.fsutil.free_name(also=)`; guide, help, internals, architecture, CHANGELOG; tests/test_interface_backup_folder.py (17) plus an app test; full suite 1897 tests OK (2 skipped); review fixes L16-f to L16-i (folder tests 22, two app tests) |
| LR5 | review L11-L16, push, CI | todo | | |
| S1 | merge docs/screenshots | todo | | branch pushed at 3b6da86 |
| L12 | docs and help in sync | todo | | |
| L13 | humanize | todo | | |
| LRF | whole-branch review, CI | todo | | |
| M | merge (user go-ahead), cleanup | todo | | |

## How to resume (any session)

1. `git -C <repo> status` on `fix/feedback-2026-10-07-b`. Round 1 first: open
   `2026-10-07-feedback-bars-leftovers.status.md`; resume at its first row not `done` (L8, L9, L10, LR4 were in
   flight at 09:58 on 2026-10-08).
   - Uncommitted changes in the tree belong to the round-1 task that was running (its row says `todo`): finish that
     task (test first, green gate, commit, ledger row), or `git stash` them and redo the task.
   - The round-1 workflow, if the same Claude session is still alive: `Workflow({scriptPath:
     "~/.claude/projects/-mnt-d-Profile-Users-Tushar-Documents-GIT-wow-tools/<session>/workflows/scripts/feedback-l7-l10-wf_d3a782a9-242.js",
     resumeFromRunId: "wf_d3a782a9-242"})` replays finished agents from cache. In a new session, run the remaining
     tasks from the spec instead.
2. Then this ledger, first row not `done`. Each task: tests first, green gate (`python3 scripts/run_tests.py`,
   `ruff check --no-cache .`, `python3 scripts/gen_event_docs.py --check`), one commit, ledger row, then review.
   Push at LR5 and LRF and wait for CI (`gh run watch <id> --exit-status`).
3. Never stage `docs/assets/new/` (the user's screenshot originals); stage files explicitly.
4. Never merge without the user's go-ahead (M).

## Decisions taken during the build

- **L11-a** The app's `t` closes the tool through `ToolFlow.close()` (`close_tool`), which removes every screen
  above the menu without running their dismiss callbacks, as the review's own `t` already ended. So `t` on the
  USE AT YOUR OWN RISK popup logs no accepted or declined event (it is neither answer: the popup is asked again the
  next time); the `ui.selection` event (`screen=app`, `control=tool_menu`, `value=<screen class>`) records where it
  was pressed. A popup's callback (an update offer, a confirm) is dropped, never answered.
- **L11-b** The busy notice is not word for word q's: one template, `BUSY_NOTICE` in `ui/base.py`, "A run is in
  progress. Wait for it to finish before {quitting | going back to the tool menu}." (q's text is unchanged), logged
  as a new event `ui.tool_menu_refused`. The review's own `t` binding (kept for the footer) says it too when busy;
  its `f` and `Esc` stay silent, as before.
- **L11-c** The per-screen `t` bindings stay on the flavor and account pickers, reviews and results (they put
  Tools in the footer, D17); every other screen gets `t` from the app. `ToolMenuBindingsTest` allows a `t` binding
  only to `leave('tools')`, `tool_menu` or `choose('tools')`.
- **L11-d** `t` does nothing under the lock warning (the menu is not open until it is answered), as on the menu.
- **L11-e** `Ka0sApp.action_quit` now calls `ask_before_leaving(self.exit)` instead of `super().action_quit()`;
  Textual's `App.action_quit` is only `self.exit()`, so q's behaviour is unchanged (tests/test_quit_key.py green).
- **L14-a** The journal row kept is the one on top of a multi-flavor summary, now carrying the Undo note
  (`UNDO_NOTE`): the journal is one file for every flavor of the run, so a row per flavor block would still repeat
  it with two flavors. The flavor blocks leave out "Journal folder" and "Run journal" (`summary_rows(result,
  journal=False)`); a single-flavor result (`CleanResult`) keeps its row in place, with the note, as before.
- **L14-b** The other tools: Ace3 Profile Manager and Saved Variables Browser share `sv_report.apply_summary_rows`
  (one "Journal" row after the per-flavor zips; a two-flavor test pins it), Interface Backup's restore summary is
  one flavor with one "Journal" row, the Screenshot Organizer's summary one "Journal" row. No change there.
- **L14-c** Review: the top row's note said "puts them back" before any file is named (a stop with "Done: none"
  leaves nothing for "them"). A multi-flavor result now uses `MULTI_UNDO_NOTE`, "(Undo last clean on the review
  restores deleted files)"; the single-flavor row keeps `UNDO_NOTE` after its files. The wording is kept to 54
  characters so `journal/<name>` plus the note fits at 120x30 with the default backup folder (a longer "puts the
  deleted files back" scrolled sideways; a test pins the fit). The internals paragraph that grew past 120 columns
  is rewrapped.
- **L15-a** The mark is one constant pair in `ui/review.py`, next to `BlacklistAction`: `BLACKLISTED_MARK` (`⊘`)
  and `BLACKLISTED_STYLE` (`dim`, the muted style both trees already give a blacklisted row), returned as
  `blacklisted_mark()` in the `(mark, style)` shape of `ui.dialogs.tick_mark`. `test_structure` pins its one home
  and that both review screens use it.
- **L15-b** The Ace3 blacklist screen keeps its ticks: there a tick is the blacklisted state and Space toggles it,
  so a `⊘` in its tick column would hide what Space changes. Its explanation line names the mark instead ("the
  review shows them marked ⊘, never ticked or changed").
  This departs from the spec's L15 row, which lists the blacklist screen among the places that show the mark;
  the review flagged it and it stays open for the user to confirm (keep the ticks, or show the mark there too).
- **L15-c** Which rows: in the WTF Cleaner the blacklisted addon's item row and its file rows (group rows still
  count and mark the cleanable items only); in the Ace3 Profile Manager every row of a locked addon (addon,
  database, profile, character; By character its pair rows), recorded in `TreeBuilder.held`. A group that is not
  itself blacklisted (an account, a By character character whose every row is locked) keeps a blank tick column.
  An addon unlocked with `u` is not locked, so its rows take tick marks again.
- **L15-d** STD-7.12 (SHOULD) now also names the shared mark; no MUST changed.
- **L15-e** Review fixes: both new Textual tests run at `BASE` (120x30, STD-10.5), not the files' local
  `(140, 50)`. A new Ace3 test covers the read-only rows of a locked addon: a deleted profile and a removed
  leftover character (By addon) and the removed pair (By character) show the mark when locked and no mark when
  not. In the app `b` and the blacklist screen drop a locked addon's staged changes first, so the test locks it
  through the settings with the changes still staged, to pin the tree builder's own marking.
- **L16-a** `root` stays the tool's folder (`resolve_backup_root`) in every API (`back_up`, `restore`,
  `undo_restore`, the catalog); only the catalog knows the zips live in `zips_dir(root)` = `<root>/backup`. The
  "Zips go to:" lines (settings, the Back up confirm) and the review's **Backup folder** label show `<root>/backup`.
- **L16-b** The one-time move runs in the review's scan worker, just before `list_backups` (STD-7.20: never on the
  UI thread; the flavor picker's notes worker only lists, and listing sees both places, so its counts are the
  same). Nothing to move logs nothing and makes no empty `backup/`; a `backup` that is not a folder leaves every
  zip in place, reported as failed.
- **L16-c** `core.fsutil.free_name` gained `also=` (folders whose names count as taken too): `new_backup_path`
  passes `<root>`, so a new zip never takes the name of a zip not moved yet and the later move never clashes
  with it. A clash can still come from a zip copied in by hand; it is left in place and reported.
- **L16-d** `prune_backups` matches `protect` by exact path first, then by name, so with a same-name zip left in
  `<root>` the one just made is the one spared. Pre-restore zips are still never pruned by `prune_backups`;
  `prune_safety` deletes by name in both places.
- **L16-e** Undo accepts a safety zip the journal names in `<root>/backup` or `<root>` (an older run's), and
  `zip_now_at` looks for it in `backup/` by file name only when the named path is gone. The move uses
  `rename_no_replace` (STD-5.17). As first committed it ran outside `activity.running()`, which broke STD-5.19
  (MUST); the review caught it and L16-g fixes it, so no deviation row is needed.
- **L16-f** Review fixes: the settings label and the guide's settings row name `interface-backup\backup`;
  `ibackup.backup_started` logs `dest` as `zips_dir(root)` (where the zips go, as the "Zips go to:" lines); the
  `undo_restore` docstring line over 120 columns is rewrapped.
- **L16-g** STD-5.19: `move_old_zips` renames the user's zips inside `activity.running()` when there is something
  to move (nothing to move enters nothing), so `suite.run()`'s `wait_idle()` waits for it before releasing the
  lock. Tests: the catalog's own and the review's scan (`*_inside_activity_running`).
- **L16-h** "Once" (spec L16) is read as "a zip is moved the first time it can be": the move stays in every scan,
  so a zip left in place (a taken name, or a move that keeps failing) is tried again each time and moves as soon
  as it can. Its warning is logged the first time only: a per-session set of (folder, name) left in place; a
  later scan logs `ibackup.zips_moved` only when something moved or a new name was left (that event lists every
  name still left). A new session logs it once again. The guide says what to do with a taken name (two rows of
  that name under Backups: check both, then move or delete the old one by hand); a test pins the two rows.
- **L16-i** A `backup` folder that is a link: both paths now follow it. `new_backup_path` and the zip writers'
  `mkdir(parents=True, exist_ok=True)` already wrote through it, and the user picks where backups go (the backup
  folder setting itself may be a link), so `move_old_zips` no longer refuses it. STD-5.5 is about the folders
  being scanned, backed up or restored (Interface, WTF), not the destination the user chose. A link to something
  that is not a folder still leaves every zip in place, reported as failed.
