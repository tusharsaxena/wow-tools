# Adding a tool

This walks through how the Screenshot Organizer (`screenshot-organizer`) was added, as an example.

1. **Package.** Create `wowtools/tools/screenshot_organizer/` with:
   - `__init__.py`, which imports `events` so the tool's events register:
     `from wowtools.tools.screenshot_organizer import events as _events  # noqa: F401`
   - `events.py`:
     ```python
     from wowtools.core.events import EventSpec, register_events
     TOOL_NAME = "screenshot-organizer"
     EVENTS = {"shots.moved": EventSpec("info", "A screenshot was moved into its date folder.")}
     register_events(TOOL_NAME, EVENTS)
     ```
     Event names share one registry across all tools (the same name with a different spec is an error), so give
     every name a tool prefix: `shots.*` here (`ibackup.*` for Interface Backup). The WTF Cleaner already owns bare names such as `scan.started`
     and `backup.created`, which predate this rule.
   - UI-free logic modules over plain dataclasses, which never import `textual`. The organizer has `naming.py`
     (parse the file name), `planner.py` (`scan(flavors, dest_dir, progress)` returns a `Plan` of `ShotItem`s),
     `organizer.py` (`execute(items, ...)` takes the ticked `ShotItem`s and returns an `OrganizeResult`),
     `journal.py`, `undo.py` and `report.py` (labels and table rows as plain strings).
   - **Run journal.** A tool that changes or deletes files writes a run journal with `wowtools/core/journal.py`, the
     suite standard: one JSON Lines file per real run in `journal_dir(wow_path, TOOL_NAME)`
     (`<WoW>/wow-tools/<tool>/journal/`). Open the `JournalWriter` (header) before the first change and stop if it
     cannot be written; `add_entry({"action": ..., ...})` after each change; `finish()` and `discard_if_empty()` at
     the end; `prune_journals(dir, cfg.keep_journals)` (the shared `[general] keep_journals`; a tool has no retention setting
of its own, and backups it prunes follow `cfg.keep_backups`, 0 = keep all). Keep the
     tool's own entry fields, `read_journal` wrapper and undo rules in its own `journal.py` / `undo.py` (see
     `screenshot_organizer/`, `wtf_cleaner/` and `interface_backup/`, whose journal records restores only), offer only `latest_undoable(dir)`, `mark_undone()` after an
     undo, and give the review screen an amber Undo button (`action_button(..., "revert")`, key `z`, confirm
     starting on No). A dry run writes no journal.
   - **Code another tool already has** moves to `wowtools/core/` first, never imported across tools. A tool that
     changes SavedVariables files takes the whole-`WTF` snapshot from `core/snapshot.py` (folder and name prefix are
     parameters), the path guard and lock probe from `core/svfiles.py`, and `core.fsutil.atomic_write_bytes` for its
     writes, as the WTF Cleaner and the Ace3 Profile Manager do.
   - `settings.py` for the tool's own settings: the `[screenshot_organizer]` section of `config/screenshot-organizer.cfg`.
     Follow `wtf_cleaner/settings.py`; it takes the tool's `Config`, never the suite one.
   - `app.py` with `class ScreenshotsFlow(ToolFlow)` and `FLOW = ScreenshotsFlow`. `start()` pushes the first
     screen; call `self.require_install(...)` first if the tool needs the WoW folder, and `self.close()` to go
     back to the menu. `self.cfg` is the shared suite config and `self.tool_cfg` the tool's own file. Reuse
     `FlavorScreen` for the flavor (`include_all=True` adds "All flavors"), and put `Header()`, `BrandBar()` and
     `Footer()` on every screen. The organizer's screens are in `app.py` (`ScreenshotSettingsScreen`) and
     `review_screen.py` (`ShotReviewScreen`, `ShotProgressScreen`, `ShotResultScreen`).
   - **Shared dialogs.** Take the confirm and progress dialogs from `wowtools/ui/dialogs.py`, never from another
     tool (a tool imports nothing from another tool; `tests/test_structure.py` checks it):
     `ConfirmScreen(title, body, alerts, default_yes=...)` (start on No for anything that changes files), and a
     subclass of `ProgressScreen` with your own `ID_PREFIX`, `STAGE_TITLES` and `SIMULATED_STAGE`, fed by the
     run's `progress(stage, current, total, detail)` through `app.call_from_thread`. Wrap that callback with
     `core.fsutil.safe_progress` inside the run. A review tree can use `tick_mark`, `relabel_branch` and the
     `TwoPaneFocus` mixin; `theme_colour(app, "success")` gives theme colours with the Ka0s fallback.
   - **One look.** Build the screens' CSS and hints from the same module, so a new tool looks like the others:
     `two_pane_css(screen, tree)` for the review (left pane `FILTERS_WIDTH` wide, four action buttons in one row),
     `result_css(screen)` for the result, `settings_css(screen)` for the settings form, and hints that start with
     `REVIEW_HINT` (or `review_hint("tick or open")` when Space does more in your tree) and `RESULT_HINT`.
     `tests/test_look_and_feel.py` checks every tool against them; add yours to its `TOOLS`.
2. **Register** it in `wowtools/tools/__init__.py`:
   `Tool("screenshot-organizer", "Screenshot Organizer", "File screenshots into year/month/day folders, per flavor.",
   "wowtools.tools.screenshot_organizer.app", "screenshot_organizer")`. It appears in the tool menu. There are no per-tool wrappers or command-line modes: every tool
   opens from the menu of `wow-tools.sh` / `wow-tools.cmd`.
3. **Events**: run `python3 scripts/gen_event_docs.py` and commit `docs/events.md`.
4. **Tests**: add `tests/test_screenshot_organizer_*.py` (`test_screenshot_organizer_planner.py`, `test_screenshot_organizer_organizer.py`, `test_screenshot_organizer_undo.py`, …, plus
   `test_screenshot_organizer_app.py` for the TUI; `tests/fixtures.py` has `build_screenshot_tree()`). Use temp folders, `tests.fixtures.TuiTestCase` as the base for TUI tests, `capture_events()` for logging
   assertions
   and `WowToolsApp(..., tool_options={"screenshot-organizer": {...}}).run_test()` for the TUI (open the tool from the menu
   with Enter). Never touch a real install.
5. **Docs**: write a user guide, `docs/<tool name>.md` (for example `docs/screenshot-organizer.md`), in the same
   plain style as the other guides, with screenshots from `docs/assets/`, its settings and its troubleshooting.
   Add a row to the README's tools table and a link under "Tool guides", plus the tool's config file in "Your
   settings", and a line in "Version history". Add the config section, data flow and screens to
   `docs/architecture.md`. `tests/test_docs.py` checks that the README names and links a guide for every tool.
6. **Renaming a tool later**: change the name in `TOOLS`, the tool's `TOOL_NAME` and `SECTION`, and add one line
   to `RENAMED_TOOLS` in `wowtools/tools/__init__.py`, e.g.
   `ToolRename("screenshots", "screenshot-organizer", "screenshots", "screenshot_organizer")`. On the next start
   the old config file, `logs/<old>/` and `<WoW folder>/wow-tools/<old>/` move to the new name (`core/migrate.py`).
   Nothing else moves: a tool whose output folder is named after `TOOL_NAME` inside a folder the user chose
   (Interface Backup's `<backup folder>/interface-backup`, when the backup folder is set) needs that subfolder
   moved too, which migrate does not do. Without it the tool lists no backups and Undo refuses the moved journals.
