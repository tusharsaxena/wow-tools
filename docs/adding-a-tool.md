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
     the end; `prune_journals(dir, cfg.keep_journals)` from the tool's `JOURNALS = ToolJournals(TOOL_NAME, read_journal, "<prefix>.journal_pruned")` (the shared `[general] keep_journals`; a tool has no retention setting
of its own, and backups it prunes follow `cfg.keep_backups`, 0 = keep all). Keep the
     tool's own entry fields, `read_journal` wrapper and undo rules in its own `journal.py` / `undo.py` (see
     `screenshot_organizer/`, `wtf_cleaner/` and `interface_backup/`, whose journal records restores only), offer only `latest_undoable(dir)`, `mark_undone()` after an
     undo, and give the review screen a violet Undo button (`action_button(..., "revert")`, key `z`, its confirm
     `kind="destructive"`). A dry run writes no journal.
   - **The shared library.** `wowtools/core/` (UI-free, never imports `textual`) and `wowtools/ui/` (Textual) are the
     suite's shared library: in-repo reusable code, not a separate package. Anything two or more tools need lives
     there: use what is already there, and when your tool needs code another tool already has, move it into
     `core/` or `ui/` first and make both tools use it. Never copy it and never import it from the other tool
     (`tests/test_structure.py` pins the single definitions and the no-cross-tool-import rule). The main pieces:
     `ui/review.py` (the review screen base: `ReviewBase`, `ReviewTree`, `TickModel`), `ui/tree_filter.py` (the tree filter: `TreeFilter`, `FilterInput`, `/`), `ui/result_screen.py`
     (`ResultBase` / `ResultScreen`), `ui/settings_form.py` (`ToolSettingsScreen`), `ui/tool_flow.py` (the
     `ToolFlow` helpers: `start`, `open_settings`, `remember_flavor`, `pick_account`, `fill_notes`),
     `ui/dialogs.py` (popups and CSS), `ui/widgets.py` (`action_button`), and in `core/` `journal.ToolJournals`,
     `marker`, `undo`, `progress` (`ThrottledProgress`), `parallel` (`run_units`: independent game versions,
     `cfg.parallelism` at once; keep a run serial when its units share a journal or marker), `text` (`plural`,
     `human_size`) and `install` (`flavor_name`, `validate_backup_dir`).
     See [architecture.md](architecture.md) for each module. A tool that changes SavedVariables files takes the
     whole-`WTF` snapshot from `core/snapshot.py` (folder and name prefix are parameters), the path guard and lock
     probe from `core/svfiles.py`, and `core.fsutil.atomic_write_bytes` for its writes, as the WTF Cleaner and the
     Ace3 Profile Manager do.
   - `help.py` with `HELP`, the tool's help screen text (Markdown; `h` on any of its screens shows it, spec D18) and
     `GUIDE_URL` (`https://github.com/tusharsaxena/wow-tools/blob/master/docs/<tool name>.md`): what the tool does,
     the flow step by step, every button with its key, the filter and tick keys, the safety notes (backups, Dry
     run, Undo) and the link to the guide. Keep it to about two screens. `tests/test_help.py` checks that it names
     every button of the tool's screens (add the tool to its `RUN_ACTION`) and that its links exist in the repo.
   - `settings.py` for the tool's own settings: the `[screenshot_organizer]` section of `config/screenshot-organizer.cfg`.
     Follow `wtf_cleaner/settings.py`; it takes the tool's `Config`, never the suite one.
   - `app.py` with `class ScreenshotsFlow(ToolFlow)` and `FLOW = ScreenshotsFlow`. Set `SECTION` (the tool's
     config section) and `SETTINGS_SCREEN`, and implement `_pick_flavor()`: `ToolFlow.start()` checks the WoW
     folder (`require_install`), opens the settings the first time the tool is opened, then calls it, and `s`
     (`open_settings()`) and the review's `flavors` / `tools` / quit (`_after_review`) need nothing more.
     `self.close()` goes back to the menu. `self.cfg` is the shared suite config and `self.tool_cfg` the tool's
     own file. Reuse `FlavorScreen` for the flavor (`include_all=True` adds "All flavors"), keep the pick with
     `remember_flavor(choice)`, ask for the account with `pick_account(flavor, then)`, and fill slow picker notes
     with `fill_notes(picker, work, ready)`. The settings form subclasses `ToolSettingsScreen`
     (`wowtools/ui/settings_form.py`: `FORM_TITLE`, `FIRST_FIELD`, `TICKS`, `load()`, `fields()`, `save()`;
     `folder_input()` / `folder_value()` for a folder field). Put `Header()` and `BottomBar()` (`wowtools/ui/branding.py`:
     the footer and the version in one row) on every screen, never a `Footer()` of its own. The organizer's screens are in `app.py` (`ScreenshotSettingsScreen`) and `review_screen.py`
     (`ShotReviewScreen`, `ShotProgressScreen`, `ShotResultScreen`).
   - **Shared dialogs.** Take the confirm and progress dialogs from `wowtools/ui/dialogs.py`, never from another
     tool (a tool imports nothing from another tool; `tests/test_structure.py` checks it):
     `ConfirmScreen(title, body, alerts, kind=..., groups=...)` (it opens on Yes, so `kind` colours Yes by what it
     does: `"destructive"` for anything that deletes, overwrites, undoes or drops pending work, `"simulate"` for a
     dry run, `"create"` when it only adds files; every call names its kind, `tests/test_structure.py` checks it;
     Enter/Space wait `CONFIRM_GUARD` after it opens; `groups` lists long details in a tree), `InfoScreen(title, groups)` for notes too long for a notification,
     `ChoiceScreen(title, message, choices, default=...)` for a warning with a choice of buttons (an unfinished
     run; `default` is the safe choice the user most likely wants), and a
     subclass of `ProgressScreen` with your own `ID_PREFIX`, `STAGE_TITLES` and `SIMULATED_STAGE`, opened with a
     title and the run's units (`units=`, `parallelism=`, `label=`), and fed straight from the worker (no
     `call_from_thread`): pass `screen.report` as the run's `progress(stage, current, total, detail)`,
     `screen.start_unit` as its per-flavor callback, or `screen.report_unit` as `run_units`' tagged progress. Wrap
     that callback with `core.fsutil.safe_progress` inside the run. A review tree can use `tick_mark`, `relabel_branch` and, from
     `wowtools/ui/review.py`, `ReviewTree` and the `ReviewBase` mixin (Space, `a` / `n` over a `TickModel`, leaving,
     the running-programs check in a worker, the debounced rebuild, the scan box, `BUTTON_ACTIONS`);
     `theme_colour(app, "success")` gives theme colours with the Ka0s fallback.
   - **One look.** Build the screens' CSS and hints from the same module, so a new tool looks like the others:
     `two_pane_css(screen, tree)` for the review (left pane `FILTERS_WIDTH` wide, four action buttons in one row),
     a result screen on `ResultBase` (or the row-built `ResultScreen`) from `wowtools/ui/result_screen.py`, which
     brings the result layout, buttons and keys (`result_bindings`) and colours status cells (`status_style`), a
     settings form on `ToolSettingsScreen` (`settings_css`), and hints that start with
     `REVIEW_HINT` (or `review_hint("tick or open")` when Space does more in your tree) and `RESULT_HINT`.
     Every tree screen binds `TREE_BINDINGS` (`x` expand all, `c` collapse all) and puts `TREE_HINT` in its hint
     (before `f flavors`); each focusable control of the left pane gets a row of its own. Every tree screen also gets
     the `/` filter from `wowtools/ui/tree_filter.py`: a `FilterInput` in the left pane and `FILTER_HINT` right
     before `TREE_HINT`, through `TreeFilter` on a tick screen (placed before `ReviewBase`; supply `all_tick_keys()`
     and `filter_texts(key)`, and a `HIDDEN_NOUN` for the "N selected … are hidden by the filter" line) or
     `FilterBox` on a read-only tree.
     Build every button with `action_button(label, kind, key)` (`wowtools/ui/widgets.py`), never `Button(...)`.
     `key` is the binding key of what the button does (`"w"`, `"escape"`): the button shows it on a second line and
     the footer leaves it out (spec D17), so never write the key into the label ("Clean (w)") and leave button keys
     out of the left-pane hint (it names navigation and the keys with no button: `a all · n none · / filter · ...`).
     A result screen's `lead_buttons()` / `extra_buttons()` give `(label, kind, id, key)`. Pick
     its kind by what it does, as the other tools do: `destructive` (deletes), `overwrite` (overwrites or changes
     files), `create` (only adds files), `revert` (undo), `simulate` (dry run), `confirm` (Save, OK), `navigate`
     (Rescan, Other flavor, a button that opens a screen) or `cancel` (Cancel, Back, Quit). A button that stages a
     change takes the kind of the change. `tests/test_structure.py` checks that one label has one kind everywhere.
     Lay the screens out for 120x30 (Windows Terminal's default window) and let trees and tables take any extra
     room; 80x24 only has to keep working. `tests/test_look_and_feel.py` checks every tool against them at those
     sizes; add yours to its `TOOLS`.
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
   settings", and a bullet under the tool in the next `CHANGELOG.md` entry (Keep a Changelog format). Add the
   config section, data flow and screens to `docs/architecture.md`. `tests/test_docs.py` checks that the README names and links a guide for every tool.
6. **Renaming a tool later**: change the name in `TOOLS`, the tool's `TOOL_NAME` and `SECTION`, and add one line
   to `RENAMED_TOOLS` in `wowtools/tools/__init__.py`, e.g.
   `ToolRename("screenshots", "screenshot-organizer", "screenshots", "screenshot_organizer")`. On the next start
   the old config file, `logs/<old>/` and `<WoW folder>/wow-tools/<old>/` move to the new name (`core/migrate.py`).
   Nothing else moves: a tool whose output folder is named after `TOOL_NAME` inside a folder the user chose
   (Interface Backup's `<backup folder>/interface-backup`, when the backup folder is set) needs that subfolder
   moved too, which migrate does not do. Without it the tool lists no backups and Undo refuses the moved journals.
   The Ace3 Profile Manager's rename from `ace-profiles` is the worked example: `settings.migrate_backup_root()`
   moves `<backup_dir>/ace-profiles` with `merge_folder_logged()` when the tool opens, and `undo._moved_zip()`
   finds a journal's `edited-*.zip` by name in the new folder.
