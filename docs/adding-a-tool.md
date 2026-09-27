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
   - `settings.py` for a `[screenshots]` config section. Follow `wtf_cleaner/settings.py`.
   - `cli.py` with `main(argv, *, cfg=None, stdout=None, stderr=None) -> int`. It opens the TUI when no
     CLI-mode flags are given.
   - `app.py` with `class ScreenshotsApp(Ka0sApp)`, which overrides `after_mount()` (not `on_mount`).
     Reuse `SetupScreen` for the WoW folder and `FlavorScreen` for the flavor, and put `Header()`,
     `BrandBar()` and `Footer()` on every screen.
2. **Register** it in `wowtools/tools/__init__.py`:
   `Tool("screenshots", "Screenshot Organizer", "Sort screenshots into folders.", "wowtools.tools.screenshots.cli")`.
3. **Wrappers**: copy `wtf-cleaner.cmd/.sh` to `screenshots.cmd/.sh` and change the tool name. Add both
   names to `MANAGED_FILES` in `core/updater.py` so zip updates replace them.
4. **Events**: run `python3 scripts/gen_event_docs.py` and commit `docs/events.md`.
5. **Tests**: add `tests/test_screenshots_*.py`. Use temp folders, `capture_events()` for logging assertions
   and `App.run_test()` for the TUI. Never touch a real install.
6. **Docs**: add a section to `README.md` and a row to its tools table.
