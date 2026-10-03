# Adding a tool

This walks through adding the Screenshot Organizer (`screenshots`) as an example.

1. **Package.** Create `wowtools/tools/screenshots/` with:
   - `__init__.py`, which imports `events` so the tool's events register:
     `from wowtools.tools.screenshots import events as _events  # noqa: F401`
   - `events.py`:
     ```python
     from wowtools.core.events import EventSpec, register_events
     TOOL_NAME = "screenshots"
     EVENTS = {"shots.moved": EventSpec("info", "A screenshot was filed into a folder.")}
     register_events(TOOL_NAME, EVENTS)
     ```
   - UI-free logic modules (e.g. `organizer.py`) that take a `Flavor` and plain values.
   - `settings.py` for the tool's own settings: the `[screenshots]` section of `config/screenshots.cfg`.
     Follow `wtf_cleaner/settings.py`; it takes the tool's `Config`, never the suite one.
   - `app.py` with `class ScreenshotsFlow(ToolFlow)` and `FLOW = ScreenshotsFlow`. `start()` pushes the first
     screen; call `self.require_install(...)` first if the tool needs the WoW folder, and `self.close()` to go
     back to the menu. `self.cfg` is the shared suite config and `self.tool_cfg` the tool's own file. Reuse
     `FlavorScreen` for the flavor, and put `Header()`, `BrandBar()` and `Footer()` on every screen.
2. **Register** it in `wowtools/tools/__init__.py`:
   `Tool("screenshots", "Screenshot Organizer", "Sort screenshots into folders.", "wowtools.tools.screenshots.app",
   "screenshots")`. It appears in the tool menu. There are no per-tool wrappers or command-line modes: every tool
   opens from the menu of `wow-tools.sh` / `wow-tools.cmd`.
3. **Events**: run `python3 scripts/gen_event_docs.py` and commit `docs/events.md`.
4. **Tests**: add `tests/test_screenshots_*.py`. Use temp folders, `tests.fixtures.TuiTestCase` as the base for TUI tests, `capture_events()` for logging
   assertions
   and `WowToolsApp(..., tool_options={"screenshots": {...}}).run_test()` for the TUI (open the tool from the menu
   with Enter). Never touch a real install.
5. **Docs**: add a section to `README.md` and a row to its tools table.
