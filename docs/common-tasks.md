# Common tasks

Recipes for the changes this repo actually gets. Each lists the files to touch in order, the rules it must satisfy
(IDs from [standards.md](standards.md)), and ends with [the green gate](#the-green-gate). Write the failing test
first ([STD-10.10](standards.md#10-testing)). If a step would break a MUST, stop and flag it; never work around it.

## Contents

- [The green gate](#the-green-gate)
1. [Add a tool](#1-add-a-tool)
2. [Add a setting to a tool](#2-add-a-setting-to-a-tool)
3. [Add a `[general]` setting](#3-add-a-general-setting)
4. [Add a log event](#4-add-a-log-event)
5. [Add a button and its key to a screen](#5-add-a-button-and-its-key-to-a-screen)
6. [Add a tree screen](#6-add-a-tree-screen)
7. [Add a shared helper (the two-tool rule)](#7-add-a-shared-helper-the-two-tool-rule)
8. [Add a WTF Cleaner criterion](#8-add-a-wtf-cleaner-criterion)
9. [Change a button's colour or kind](#9-change-a-buttons-colour-or-kind)
10. [Rename a tool](#10-rename-a-tool)
11. [Update the vendored libraries](#11-update-the-vendored-libraries)
12. [Cut a release](#12-cut-a-release)

## The green gate

Before every commit, all three pass ([testing.md](testing.md#the-green-gate) has the details):

```sh
python3 scripts/run_tests.py --all        # the full suite on WSL and native Windows; -k TEXT to filter while you work
ruff check --no-cache .                   # not run in CI, so it is on you
python3 scripts/gen_event_docs.py --check # docs/events.md matches the registries
```

On a machine with no Windows Python, run the plain `python3 scripts/run_tests.py` instead and let CI cover Windows
before the merge ([testing.md](testing.md#windows-from-wsl)).

## 1. Add a tool

The full walk-through is [adding-a-tool.md](adding-a-tool.md); the test side is
[testing.md](testing.md#adding-tests-for-a-new-tool). In short:

1. `wowtools/tools/<package>/`: `__init__.py` (imports `events`), `events.py`, UI-free logic modules,
   `settings.py`, `help.py`, `app.py` (`FLOW`), `review_screen.py`. Copy the shape of the closest tool; take every
   shared piece from `wowtools/core` and `wowtools/ui`.
2. `wowtools/tools/__init__.py`: one `Tool(name, title, description, module, section)` line in `TOOLS`.
3. `python3 scripts/gen_event_docs.py`, commit `docs/events.md`.
4. `tests/fixtures.py` (a builder), `tests/test_<package>_*.py`, and the meta-test tables: `TOOLS`, `RUN_ACTION`,
   `DESTRUCTIVE_REVIEWS`, `PREPARE` in `tests/test_look_and_feel.py`; `RUN_ACTION`, `PREPARE` in `tests/test_help.py`;
   `ACCOUNT_TOOLS`, `RUN_ACTION`, `PREPARE` in `tests/test_quit_key.py`, `tests/test_tool_menu_key.py` and
   `tests/test_toast_stack.py`; `ACCOUNT_TOOLS` in `tests/test_picker_keys.py`; `TOOLS`, `RISK_EVENTS` in
   `tests/test_risk_disclaimer.py` for a tool with the USE AT YOUR OWN RISK popup (STD-10.8).
5. Docs: `docs/<tool id>.md` (the guide), a README row and guide link and its config file under "Your settings",
   a `CHANGELOG.md` bullet, a row in the [architecture.md](architecture.md) Documentation map and Config schema,
   `docs/internals/<tool id>.md`, and in `CLAUDE.md` the tool line plus its links in the Documentation index's
   `docs/internals/` and User guide rows, and the guide in the "Ships" table of
   [releasing.md](releasing.md#what-a-release-contains) and in `RELEASE_SHIPS` (`wowtools/core/updater.py`).

**Rules:** all of sections 1 to 10 apply; start with STD-3.1 to STD-3.6 (package and registry), STD-2.1/2.2 (shared
library), STD-6.2/6.3 (events), STD-7.1 to STD-7.11 (the review), STD-9.1/9.2 (help and guide), STD-10.8 (meta-test
tables), STD-11.5 (the release manifest). Then [the green gate](#the-green-gate).

## 2. Add a setting to a tool

Example: the Screenshot Organizer's `copy_mode`.

1. `wowtools/tools/<package>/settings.py`: a field with its default on the settings dataclass; read it in
   `load_settings` with a typed getter and a default (`cfg.get_bool(SECTION, "copy_mode", False)`); write it in
   `save_settings` with `cfg.set` (`cfg.set_path` for a folder), before the existing `cfg.remove_retired(SECTION,
   source=source)` and `cfg.save()`.
2. `wowtools/tools/<package>/app.py`: the row in the `ToolSettingsScreen` subclass, `fields()` (a `Label` then an
   `Input`, or one `Ka0sCheckbox`; `folder_input()` for a folder), and its value in `save()`. Validate there: on a
   bad value call `self._error(...)` and return `False`; a folder goes through `core.install.validate_backup_dir`
   (or `validate_output_dir`). `save()` reloads the stored settings and replaces only the form's own fields, so
   `last_flavor_choice` and `last_account` survive.
3. Read the setting where it acts (the planner, the run), never from the screen.
4. Tests: a round trip in `tests/test_<package>_settings.py` (WTF Cleaner: `tests/test_rules.py`), and a form test in
   `tests/test_<package>_app.py` for validation. A new row must still fit at 120x30 with Save visible
   (`tests/test_look_and_feel.py::test_settings_forms_fit_at_base_and_keep_a_readable_width`).
5. Docs: the guide's `## Settings`, the `## Settings` part of `help.py` when the tool's help has one, the README's
   "Your settings" row if it names keys, the tool's section in the [architecture.md](architecture.md#config-schema)
   Config schema, and `CHANGELOG.md`.

A retention count is not a tool setting: retention is global (recipe 3, STD-4.5).

**Rules:** STD-3.5, STD-4.1 to STD-4.5, STD-4.9, STD-4.10, STD-7.4 (one control per row), STD-7.23, STD-9.5. Then
[the green gate](#the-green-gate).

## 3. Add a `[general]` setting

Example: `parallelism`.

1. `wowtools/core/config.py`: a `DEFAULT_<NAME>` constant and a typed, clamped `Config` property on `GENERAL` that
   falls back to the default on a bad value (see `Config.parallelism`, `Config.keep_journals`).
2. `wowtools/ui/setup_screen.py`: a `Label` and an `Input` (id `#kebab-case`) in `SetupScreen.compose()`, and in
   `_save()` a check with `_count(id, least, most)` that calls `_error(...)` and returns on a bad value, then
   `self.cfg.set(GENERAL, "<key>", value, source=source)` before the one `self.cfg.save()`.
3. Use it through the property (`cfg.<name>`), never `cfg.get(GENERAL, ...)` in a tool.
4. Tests: `tests/test_config.py` (default, clamping, bad values; `test_parallelism_defaults_to_two_and_is_clamped`
   is the model), the setup screen in `tests/test_ui_base.py` (`test_saves_retention_to_general`), and the form
   still fits (`tests/test_look_and_feel.py::test_general_settings_form_fits_at_base_and_keeps_a_readable_width`).
5. Docs: the README's `config\wow-tools.cfg` row under "Your settings", `[general]` in the
   [architecture.md](architecture.md#config-schema) Config schema, the suite help (`suite_help()` in
   `wowtools/ui/help_screen.py`) if users need to know it, and `CHANGELOG.md`.

**Rules:** STD-4.1 to STD-4.3, STD-4.6. Then [the green gate](#the-green-gate).

## 4. Add a log event

1. Register it, once, with a fixed level and a one-sentence description:
   - a tool's event: `EVENTS` in `wowtools/tools/<package>/events.py`, named with the tool's prefix (`shots.`,
     `ibackup.`, `ace.`, `svb.`);
   - a suite or shared-library event: `CORE_EVENTS` in `wowtools/core/events.py`;
   - a SavedVariables pipeline event: `sv_events()` in `wowtools/core/sv_events.py` (every tool on the pipeline gets
     it under its own prefix).
2. Log it with `log_event(name, **data)` (pass `dry_run=` where it matters), or `log_exception(where, exc)` for a
   failure, with `where` = `<prefix>.<stage>`.
3. Assert it in a test with `capture_events()` (strict: an unregistered name fails the test).
4. `python3 scripts/gen_event_docs.py`, and commit `docs/events.md` with the change.

**Rules:** STD-6.1 to STD-6.7, STD-10.7. Then [the green gate](#the-green-gate).

## 5. Add a button and its key to a screen

Example: the Screenshot Organizer review's Undo (`btn-undo`, `z`).

1. Pick the kind by what the button does: `destructive`, `overwrite`, `create`, `revert`, `simulate`, `confirm`,
   `refresh`, `navigate` or `cancel` (the comments on `ACTION_VARIANTS` in `wowtools/ui/widgets.py`). A label already
   used elsewhere keeps its kind.
2. The screen's `compose()`: `action_button("Label", "<kind>", "<key>", id="btn-<name>")`, inside a `ButtonRow`
   when it shares a row. Never `Button(...)`; never the key in the label. A result screen adds it as a
   `(label, kind, id, key)` tuple in `lead_buttons()` / `extra_buttons()`.
3. The screen's `BINDINGS`: `Binding("<key>", "<action>", "Label")`, and `"btn-<name>": "<action>"` in
   `BUTTON_ACTIONS`, so the button and the key both run `action_<action>`. A letter users may type in a text box is
   non-priority. Do not take a suite or shared review key (STD-8.9).
4. Leave the key out of the screen's hint (`NavHint`) and every guide or status line; the button shows it and the
   footer drops it.
5. A confirm it opens names its `kind` (`ConfirmScreen(..., kind="destructive")`); a list in it that can grow
   (warnings, notes, refusals, skipped items) goes in `listed=` as `core.text.Listed` entries, never in `alerts`
   (STD-7.26).
6. `wowtools/tools/<package>/help.py`: name the button as `**Label**` (`tests/test_help.py` checks every button the
   tool's screens show), and the guide's keys table in `docs/<tool id>.md`.
7. Tests: the action in `tests/test_<package>_app.py`; a new label/kind pair the spec fixes goes into the `expected`
   map of `tests/test_structure.py::test_same_label_same_colour`.

**Rules:** STD-8.1, STD-8.3 to STD-8.6, STD-8.8 to STD-8.10, STD-7.4 (one control per row), STD-9.1. Then
[the green gate](#the-green-gate).

## 6. Add a tree screen

Model: a review (`ShotReviewScreen` in `wowtools/tools/screenshot_organizer/review_screen.py`); a read-only tree
uses `FilterBox` instead of `TreeFilter` (Interface Backup's restore screen).

1. The class: `TreeFilter` (ticks; before `ReviewBase`) or `FilterBox` (read-only) from `wowtools/ui/tree_filter.py`,
   with `WarningsHost` first, then `ReviewBase` on a review, or `ButtonActions, TwoPaneFocus` on a read-only screen
   (`RestoreScreen`). Supply what the mixins ask for: `TREE_SELECTOR`, and on a tick screen `all_tick_keys()`,
   `filter_texts(key)` and `HIDDEN_NOUN`.
2. Layout: `DEFAULT_CSS = two_pane_css("<Screen>", "#<tree id>")`; the left pane `#filters` with one focusable
   control per row and the `FilterBar`; `Header()` first and `BottomBar()` last.
3. Keys: `*FILTER_BINDINGS` and `*TREE_BINDINGS` in `BINDINGS` (plus `WARNINGS_BINDING` and the review keys on a
   review).
4. The hint: a `NavHint` that puts `FILTER_HINT + TREE_HINT` together; a review's starts with `REVIEW_HINT` and ends
   with `f flavors · t tools`.
5. Tests: `tests/test_look_and_feel.py::test_every_tree_screen_has_the_filter_box` and
   `test_review_tree_expands_and_collapses_all` reach every tool's review through `TOOLS`; a tree screen they do not
   open (like the restore screen) needs the same checks in the tool's own tests. Check it at `BASE` and `TINY`.
   A screen with a scan box goes in `test_bars_keep_their_place_while_a_scan_runs` (STD-7.25). A new screen goes
   in the walk of `tests/test_toast_stack.py`: toasts are placed for it (`ui/toasts.py`); a row toasts must stay
   above that is not a bar gets the `TOAST_FLOOR` class (STD-7.24).
6. Help and guide: the screen's buttons in `help.py`, the `**Filter**` button and the keys in the guide.

**Rules:** STD-7.4, STD-7.6 to STD-7.9, STD-7.11, STD-7.23 to STD-7.25, STD-8.5, STD-8.7. Then [the green
gate](#the-green-gate).

## 7. Add a shared helper (the two-tool rule)

When a second tool needs code one tool already has, move it; never copy it and never import it across tools.

1. Move it to `wowtools/core/<module>.py` if it is UI-free (core never imports `textual`, `wowtools.ui` or
   `wowtools.tools`), else `wowtools/ui/<module>.py`. Keep it generic: no tool names, the tool-specific part a
   parameter.
2. Point both tools at it, and delete the tool's copy outright (no re-export).
3. `tests/test_structure.py`: pin the single definition (the `once` / `classes` maps in
   `test_shared_helpers_are_defined_once`, or a test like `test_tree_filter_lives_in_ui`) and list the old tool copy
   in `gone`.
4. Move its tests to `tests/test_core_shared.py` or a `tests/test_<module>.py` of its own.
5. Docs: a row in the [architecture.md](architecture.md) Core modules or UI table.

**Rules:** STD-1.6, STD-1.7, STD-2.1 to STD-2.3, STD-2.8, STD-9.5. Then [the green gate](#the-green-gate).

## 8. Add a WTF Cleaner criterion

Worked example: commit `8d6a1a8` (`orphan_backups`, rule 5).

1. `wowtools/tools/wtf_cleaner/rules.py`: the name at the end of `CRITERIA`, a `bool` field on `Criteria` (default
   on or off), and the match in `evaluate()` (`_group_reasons` for a whole-addon rule, or the `extra` list for one
   that proposes only some of a group's files). `criterion_counts()` and `Criteria.describe()` follow `CRITERIA`.
2. `wowtools/tools/wtf_cleaner/report.py`: `CRITERION_LABELS`, `CRITERION_SHORT` and `CRITERION_COLORS` (a colour
   clear of the button colours: `tests/test_ui_base.py::test_button_colours_keep_clear_of_the_wtf_criterion_colours`).
3. `wowtools/tools/wtf_cleaner/review_screen.py`: a digit `Binding("<n>", "criterion(<n-1>)", ...)`, and the `1-N` in
   `NAV_HINT` and the "Criteria (keys 1-N)" label. The checkboxes come from `CRITERIA`.
4. Settings: nothing to add. `settings.py` stores `criterion_<name>` for every name in `CRITERIA`, and the form in
   `app.py` makes an `sw_<name>` switch for each; check it still fits at 120x30 (`8d6a1a8` put max age on one
   compact row for this).
5. `wowtools/tools/wtf_cleaner/help.py`: a row in the rules table.
6. Tests: `tests/test_rules.py` (the rule alone, with other reasons, `criterion_counts`, `describe`) and
   `tests/test_wtf_app.py` (the counts on the review, the settings form's focus order).
7. Docs: [wtf-cleaner.md](wtf-cleaner.md) (the rules and settings), [internals/wtf-cleaner.md](internals/wtf-cleaner.md)
   if the data flow changes, and `CHANGELOG.md`.

**Rules:** STD-1.7, STD-5.6 (never `Blizzard_*` files), STD-7.4, STD-7.23, STD-8.2, STD-9.1, STD-9.5. Then
[the green gate](#the-green-gate).

## 9. Change a button's colour or kind

1. A colour: `ACTION_COLOURS` in `wowtools/ui/theme.py` (the one place colours live), and the nearest Textual variant
   in `ACTION_VARIANTS` in `wowtools/ui/widgets.py`. A new kind needs both, plus its comment in each.
2. A button's kind: the `action_button(...)` call (or the result-screen tuple), and the same label's kind on every
   other screen; the `expected` map in `tests/test_structure.py::test_same_label_same_colour`.
3. Tests: `tests/test_ui_base.py` checks contrast and a variant per kind
   (`test_every_kind_has_a_readable_colour_and_a_variant`) and the distance from the WTF criterion colours.
4. Docs: the colour sentence in the README, the suite help's colour line (`suite_help()` in
   `wowtools/ui/help_screen.py`), and `CHANGELOG.md`.

**Rules:** STD-8.1 to STD-8.3. A label that must keep two kinds is a deviation: record it in
[standards.md](standards.md#documented-deviations) and the test's allowance. Then [the green gate](#the-green-gate).

## 10. Rename a tool

1. `wowtools/tools/__init__.py`: the new name (and section) in `TOOLS`, and one `ToolRename(old, new, old_section,
   new_section)` line in `RENAMED_TOOLS`.
2. The package's `TOOL_NAME` (`events.py`) and `SECTION` (`settings.py`); rename the package folder and fix its
   imports and the `Tool.module` path if the package name changes.
3. A folder named after the tool inside a folder the user chose is not moved by `core/migrate.py`: the tool moves
   it itself when it opens (the Ace3 Profile Manager's `settings.migrate_backup_root()` with
   `merge_folder_logged()`).
4. Tests: the per-tool tables (`TOOLS`, `RUN_ACTION`, `PREPARE`, `DESTRUCTIVE_REVIEWS`, `ACCOUNT_TOOLS`, `RISK_EVENTS`;
   every file STD-10.8 lists), `tool_options` keys, test file names;
   `tests/test_migrate.py::test_every_rename_points_at_a_registered_tool` checks the new line.
5. Docs: rename `docs/<old>.md` and `docs/internals/<old>.md`, then fix every link (README, `GUIDE_URL` in `help.py`,
   architecture, `CLAUDE.md`) and the strings `tests/test_docs.py` pins; rename the guide in the "Ships" table of
   [releasing.md](releasing.md#what-a-release-contains) and in `RELEASE_SHIPS` (`wowtools/core/updater.py`); a
   `CHANGELOG.md` bullet.

**Rules:** STD-3.1, STD-3.7, STD-9.6, STD-11.5. Then [the green gate](#the-green-gate).

## 11. Update the vendored libraries

Follow [vendoring.md](vendoring.md): edit `requirements.txt` (every transitive dependency pinned with `==`), run
`python3 scripts/update_vendor.py --lock`, then `python3 scripts/update_vendor.py`, and commit `requirements.txt`,
`requirements.lock` and `vendor/` together. Never edit `vendor/` by hand.

**Rules:** STD-1.4, STD-11.3, STD-11.4. Then [the green gate](#the-green-gate).

## 12. Cut a release

Only with the user's go-ahead (merge and release are separate approvals). Follow [releasing.md](releasing.md):
bump `__version__` in `wowtools/__init__.py`, add the `## [X.Y.Z] - YYYY-MM-DD` entry to `CHANGELOG.md`, commit, tag
`vX.Y.Z`, push, run `python3 scripts/build_release.py`, and publish the zip and `SHA256SUMS` with `gh release create`.
The README version badge must match `__version__` (`tests/test_docs.py`).

**Rules:** STD-9.4, STD-11.1, STD-11.2, STD-11.5, STD-12.3. Then [the green gate](#the-green-gate).
