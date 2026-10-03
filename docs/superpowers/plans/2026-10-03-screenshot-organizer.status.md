# Build status: Screenshot Organizer

Checkpoint ledger for `2026-10-03-screenshot-organizer.md`. Work happens on branch `feat/screenshot-organizer`.

**To resume:** check out the branch, find the first row that isn't `done`, make sure
`python3 scripts/run_tests.py` passes, then carry on from that task.

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| 0 | Spec + plan | done | 5e51887 | Spec approved in chat; event names get a `shots.` prefix (registry is global) |
| 1 | Package, events, naming, settings | done | 0335683 | Deviation: `scripts/gen_event_docs.py` now imports every `wowtools/tools/*` package and orders owners core, then `TOOLS`, then the rest sorted; the test suite imports `screenshots.events` before the tool is in `TOOLS`, so `test_docs` depended on import order. `docs/events.md` regenerated (screenshots section) |
| 2 | Fixture + planner | done | dc3bd5b | Plan code as written; `test_unreadable_folder_is_a_warning` now patches `list_files` to raise so it really covers `shots.scan_warning` (the plan's version only checked the no-warning case) |
| 3 | Journal writer + organizer | done | 7863126 | Deviations (per-file syscalls): `_target_exists` trusts the execute-time day-folder listing (no extra `lexists`); `makedirs` once per day folder; the single `lexists` right before rename/copy stays (POSIX rename overwrites), and a `FileExistsError` from it is now `conflict` instead of `failed`. Added `test_target_appearing_during_the_run_is_a_conflict` |
| 4 | Undo | done | 3d5f956 | `organizer._safe` renamed to public `safe_progress` (the plan allowed this). After a cross-drive restore, a failed delete of the archive copy is `restored` with a reason, not `failed` (added `test_undo_cross_device_keeps_restore_when_archive_copy_is_locked`). Note: undo marks the journal undone even when every entry was skipped (spec §7 as written) |
| 4r | Review fixes (Tasks 1-4) | done | 138791d | Journal is opened (header written) before the first file is touched; an unwritable journal stops the run with `OrganizeError` and nothing moves; a header-only journal is deleted, so a run that changes nothing still leaves none. A journal append failure after a change raises `JournalWriteError`: the change is reported as done with a "not journaled" reason (never `failed`) and the run stops. `mark_undone` starts on a new line after a torn last line. Planner and execute list target day folders names-only (`list_names`) and stat only names already at the target. Not changed: case-insensitive target matching (nothing is overwritten; a case-only clash shows as conflict) - candidate for review R |
| M1 | Push (logic) | done | 138791d | Pushed after review fixes |
| 5 | FlavorScreen "All flavors" | done | e78b910 | Plan code as written. Tests also cover `last=None` falling back to `[general] last_flavor`, Esc, and the `ui.selection` value `all` (event fields sit under `data`) |
| 6 | TUI + registration | done | 13e4449 | Deviations: organize runs with the scanned plan's `dest_dir` (not the reloaded settings), so a settings change after a scan cannot make the guard refuse every file; `confirm_text` uses `plan.dest_dir` too. `test_screenshots_report.KINDS` also skips the `A_*` journal action names organizer imports (`copied_source_left` is not an outcome kind). Read-only tree leaves use data `("conflict", item)` / `("skip", skipped)`; the root node carries `("root",)` with its own mark; flavor/year/month nodes start expanded so day nodes are reachable (files still load on expand). Organize/Dry run are also disabled while scanning. `#filters` is 50 wide (46 clipped "Undo last run"). Result screen also has a BrandBar. An unexpected undo error (e.g. unreadable journal) is logged and notified instead of crashing. Extra tests: undo confirm No, lazy day files + read-only Skipped node + a/n, settings `keep_journals` error, no Screenshots folders returns to the menu |
| M2 | Push (UI) | todo | | |
| 7 | Docs | todo | | |
| R | Whole-branch review + fixes | todo | | |
| M3 | Push; ask for merge go-ahead | todo | | |
