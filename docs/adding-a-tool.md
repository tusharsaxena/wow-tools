# Adding a tool

This walks through how the Screenshot Organizer (`screenshots`) was added, as an example.

1. **Package.** Create `wowtools/tools/screenshots/` with:
   - `__init__.py`, which imports `events` so the tool's events register:
     `from wowtools.tools.screenshots import events as _events  # noqa: F401`
   - `events.py`:
     ```python
     from wowtools.core.events import EventSpec, register_events
     TOOL_NAME = "screenshots"
     EVENTS = {"shots.moved": EventSpec("info", "A screenshot was moved into its date folder.")}
     register_events(TOOL_NAME, EVENTS)
     ```
     Event names share one registry across all tools (the same name with a different spec is an error), so give
     every name a tool prefix: `shots.*` here. The WTF Cleaner already owns bare names such as `scan.started`
     and `backup.created`, which predate this rule.
   - UI-free logic modules over plain dataclasses, which never import `textual`. The organizer has `naming.py`
     (parse the file name), `planner.py` (`scan(flavors, dest_dir, progress)` returns a `Plan` of `ShotItem`s),
     `organizer.py` (`execute(items, ...)` takes the ticked `ShotItem`s and returns an `OrganizeResult`),
     `journal.py`, `undo.py` and `report.py` (labels and table rows as plain strings).
   - `settings.py` for the tool's own settings: the `[screenshots]` section of `config/screenshots.cfg`.
     Follow `wtf_cleaner/settings.py`; it takes the tool's `Config`, never the suite one.
   - `app.py` with `class ScreenshotsFlow(ToolFlow)` and `FLOW = ScreenshotsFlow`. `start()` pushes the first
     screen; call `self.require_install(...)` first if the tool needs the WoW folder, and `self.close()` to go
     back to the menu. `self.cfg` is the shared suite config and `self.tool_cfg` the tool's own file. Reuse
     `FlavorScreen` for the flavor (`include_all=True` adds "All flavors"), and put `Header()`, `BrandBar()` and
     `Footer()` on every screen. The organizer's screens are in `app.py` (`ScreenshotSettingsScreen`) and
     `review_screen.py` (`ShotReviewScreen`, `ShotProgressScreen`, `ShotResultScreen`).
2. **Register** it in `wowtools/tools/__init__.py`:
   `Tool("screenshots", "Screenshot Organizer", "File screenshots into year/month/day folders, per flavor.",
   "wowtools.tools.screenshots.app", "screenshots")`. It appears in the tool menu. There are no per-tool wrappers or command-line modes: every tool
   opens from the menu of `wow-tools.sh` / `wow-tools.cmd`.
3. **Events**: run `python3 scripts/gen_event_docs.py` and commit `docs/events.md`.
4. **Tests**: add `tests/test_screenshots_*.py` (`test_screenshots_planner.py`, `test_screenshots_organizer.py`, `test_screenshots_undo.py`, …, plus
   `test_screenshots_app.py` for the TUI; `tests/fixtures.py` has `build_screenshot_tree()`). Use temp folders, `tests.fixtures.TuiTestCase` as the base for TUI tests, `capture_events()` for logging
   assertions
   and `WowToolsApp(..., tool_options={"screenshots": {...}}).run_test()` for the TUI (open the tool from the menu
   with Enter). Never touch a real install.
5. **Docs**: add a section to `README.md`, a row to its tools table and the tool's config file and keys to its
   Settings tables; add the config section, data flow and screens to `docs/architecture.md`. `tests/test_docs.py`
   checks the README names every tool.
