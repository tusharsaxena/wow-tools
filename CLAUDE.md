# wow-tools: notes for Claude

Out-of-game WoW companion tools (Ka0s branded). Tools: WTF Cleaner (`wtf-cleaner`), Screenshot Organizer
(`screenshot-organizer`, package `tools/screenshot_organizer`), Interface Backup (`interface-backup`, package
`tools/interface_backup`), Ace3 Profile Manager (`ace3-profile-manager`, package `tools/ace3_profile_manager`).
Specs and plans: `docs/superpowers/`.

- Tests: `python3 scripts/run_tests.py` (parallel, ~70s here on WSL `/mnt/d`; `-k TEXT` to filter, `-j N` processes).
  Serial, verbose: `python3 -m unittest discover -s tests -t . -v`
- Run: `./wow-tools.sh` (Windows: `wow-tools.cmd`); the tool menu opens. `./wow-tools.sh update [--check]`.
  Tools never start on their own and have no CLI mode.
- Rebuild vendored libs: `python3 scripts/update_vendor.py` (hashed, from `requirements.lock`; `--lock` after editing
  `requirements.txt`). Event docs: `python3 scripts/gen_event_docs.py`. Release assets (zip + `SHA256SUMS`):
  `python3 scripts/build_release.py` (`docs/releasing.md`). Every tagged release needs a `CHANGELOG.md` entry
  (`## [X.Y.Z] - YYYY-MM-DD`, parsed by `core/changelog.py`, shown in-app on `c`); `build_release.py` refuses a tag
  without one.

Conventions:
- Python 3.10 floor; `from __future__ import annotations` in every module (`wowtools/`, `scripts/`, `tests/`);
  stdlib + `vendor/` only.
- `wowtools/core/*` and tool logic modules never import `textual`. Front ends are thin.
- Config paths go through `core/paths.py` (stored in Windows form). Config lives in `config/`: `wow-tools.cfg`
  (`[general]`, shared) plus `<tool>.cfg` per tool. One instance at a time (`wow-tools.lock`, `core/lock.py`).
- Retention is global: `[general] keep_backups` / `keep_journals` (`Config.keep_backups`, `Config.keep_journals`,
  edited on the setup screen). A tool has no retention setting; its `save_settings` calls
  `Config.remove_retired(section)`.
- Every log event is registered with a fixed level (`core/events.py` or `<tool>/events.py`); regenerate
  `docs/events.md` after changing any registry.
- One Textual app, `WowToolsApp` (`ui/suite_app.py`): tool menu first; each tool is a `ToolFlow` (`FLOW` in its
  `app.py`) that pushes its own screens and `close()`s back to the menu.
- One look and feel (`tests/test_look_and_feel.py`): one focusable control per row in a left pane (only a
  `ButtonRow` uses ←/→); every tree screen binds `TREE_BINDINGS` (`x` expand all, `c` collapse all) and puts
  `TREE_HINT` in its hint, plus the `/` filter (`TreeFilter`/`FilterBox`, `FILTER_HINT` right before `TREE_HINT`;
  `a`/`n` act on what it shows). Every button is `action_button(label, kind)` (kind = what it does, colours in
  `ui/theme.py`); every `ConfirmScreen` names its `kind` (Yes is focused and coloured by it).
- Shared library: `wowtools/core/` (UI-free) + `wowtools/ui/` (Textual), in-repo, not a separate package. What two
  or more tools need lives there, never copied and never imported across tools (a tool never imports another tool).
  Core: `install`, `config`, `journal` (`ToolJournals`), `snapshot`, `svfiles`, `undo`, `marker`, `progress`
  (`ProgressBoard`), `parallel` (`run_units`, `[general] parallelism`), `text`, `fsutil`, `backup`, `changelog`.
  UI: `dialogs` (confirm/info/choice/progress popups, CSS, tick helpers), `review` (`ReviewBase`, `ReviewTree`,
  `TickModel`), `tree_filter` (`TreeFilter`, `/` filter box), `result_screen` (`ResultBase`), `settings_form`
  (`ToolSettingsScreen`), `tool_flow` (`ToolFlow`), `widgets` (`action_button`), `branding` (`BottomBar`, version,
  terms). `tests/test_structure.py` pins single definitions, the cross-tool rule, the future import and import order.
- Tests use `tests/fixtures.py` temp trees; never a real WoW install, never the network.
- Screens are designed for 120x30 (Windows Terminal default) and grow; 80x24 must only keep working
  (tests/test_look_and_feel.py).
- Textual tests subclass `tests.fixtures.TuiTestCase` (asyncio debug mode off; it made the suite ~10x slower).
- Adding a tool: `docs/adding-a-tool.md`. Renaming one: a `ToolRename` line in `RENAMED_TOOLS`
  (`wowtools/tools/__init__.py`); `core/migrate.py` moves its config, logs and `<WoW>/wow-tools/<tool>/` at start-up,
  but not a `<TOOL_NAME>` folder inside a user-chosen folder (Interface Backup's `<backup_dir>/interface-backup`).
