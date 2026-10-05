# Shared code and duplication across the four tools

## 1. What is already shared

### `wowtools/core/` (no Textual, used by all tools)
- `activity.py`: `running()` and `wait_idle()`, which make the suite wait for file-changing workers before it exits.
- `backup.py`: `BackupEntry`, `create_backup`, `verify_backup`, `walk_files`.
- `config.py`: `Config`, `tool_config_path`, `DEFAULT_KEEP_*`, `RETIRED_TOOL_KEYS`.
- `events.py`: `EventSpec`, `register_events`, `log_event`, `log_exception`, `capture_events`.
- `fsutil.py`: `atomic_write_bytes/text`, `rename_no_replace`, `free_name`, `remove_quietly`, `safe_progress` (fsutil.py:105), `is_link`, `is_real_dir`, `read_link`, `make_link`, `remove_tree_no_follow`.
- `install.py`: `WowInstall`/`Flavor`/`Account`/`Character`, `detect_installs`, `validate_output_dir` (install.py:180), `FLAVOR_NAMES`. `InstallError` (install.py:41) is dead.
- `journal.py`: `journal_dir`, `JournalWriter`, `read_journal`, `list_journals`, `latest_undoable`, `mark_undone`, `prune_journals`, `friendly_stamp`.
- `snapshot.py`: `wtf_files`, `take_snapshot`, `snapshot_path`, `prune_snapshots`.
- `svfiles.py`: `SvGuard`, `probe_lock`, `recover_probe_leftovers`, `saved_variables_folders`.
- `process.py`: `running_wow_processes`, `wow_check_for`, `running_wtf_lockers`.
- Also `migrate.py`, `lock.py`, `paths.py` (`to_native`/`to_stored`), `updater.py`, `bootstrap.py`.

### `wowtools/ui/` (Textual)
- **`dialogs.py`**
  - Styles: `ALERT_STYLE`, `ACCENT`, `BUSY_STYLE`, `PARTLY_TICKED`.
  - Sizes: `FILTERS_WIDTH=50` (:28), `POPUP_WIDTH="width: 90; max-width: 90%;"` (:31), `FORM_WIDTH`.
  - Hints and keys: `review_hint`/`REVIEW_HINT`, `TREE_HINT`, `TREE_BINDINGS` (:44, x/c), `RESULT_HINT`.
  - CSS builders: `two_pane_css` (:51), `result_css` (:70), `settings_css` (:84).
  - Helpers: `theme_colour` (:100), `detail_tree`/`detail_hint`, `tick_mark` (:140), `relabel_branch` (:154).
  - Mixins and screens:
    - `TreeKeys` (:171)
    - `TwoPaneFocus` (:216)
    - `ConfirmScreen` (:247; `default_yes=False` by default, focus set in `on_mount` :286-287; 12 `default_yes` uses, only 1 is `True`)
    - `InfoScreen` (:296)
    - `ProgressScreen` (:338). Its `.progress-box` is `height: auto` and `.progress-file` is `height: 2`. The width comes from `POPUP_WIDTH`, which is 90 or 90%, so the size is not fixed.
- **`widgets.py`**
  - Pick-list styles: `LIST_NAME_STYLE`, `LIST_CURSOR_BACKGROUND`.
  - `ACTION_VARIANTS` (:21) has six kinds: delete=error, apply=success, simulate=primary, revert=warning, confirm=primary, neutral=default. `confirm` and `simulate` are both blue, and "Restore" is `neutral`.
  - `action_button` (:31), `CHECK_ON/OFF`, `NAV_BINDINGS`, `NavSelect`, `FormScroll`, `Ka0sCheckbox`, `ButtonRow` (:83), `WrapButtonRow` (:119), `wrap_items`, `NavHint`.
- **Other modules:** `tool_flow.py` (`ToolFlow`: `start`, `open_settings`, `close`, `install`, `require_install`), `flavor_screen.py` (`FlavorScreen`, `ALL_FLAVORS`, `set_notes`), `account_screen.py` (`AccountScreen`), `setup_screen.py`, `suite_app.py` (`ToolMenuScreen` :89, `WowToolsApp` :126), `base.py` (`Ka0sApp`, update screens), `branding.py` (`Banner`, `BrandBar`), `theme.py`.

## 2. Duplication candidates (file:line pairs)

### A. UI-free logic, belongs in `core/`

| # | Duplicated thing | Locations | Notes |
|---|---|---|---|
| A1 | `plural(n, word)` | wtf_cleaner/report.py:32, interface_backup/report.py:29, screenshot_organizer/report.py:54, ace3_profile_manager/report.py:37 | Same body four times. Ace's version adds a `words=` argument; adopt that one. |
| A2 | `flavor_name(folder)` | wtf_cleaner/report.py:111, screenshot_organizer/report.py:71, ace3_profile_manager/report.py:41 | WTF and SO use `Flavor(...).display_name`. Ace uses its own `FLAVOR_NAMES.get(...)` logic, which can give different output. |
| A3 | Size formatting | wtf_cleaner/report.py:36 `format_size`, interface_backup/report.py:33 `human_size` | Slightly different (handling of None, the TB unit). |
| A4 | Throttled progress | interface_backup/review_screen.py:58 `ThrottledProgress` (class, interval 0.1) vs closure copies at ace3_profile_manager/review_screen.py:398-408 and ace3_profile_manager/blacklist_screen.py:115-123 (`PROGRESS_EVERY=0.05`, defined twice: review_screen.py:58, blacklist_screen.py:31) | `ThrottledProgress` imports no Textual, so it can move to `core` as is. It also fits progress reporting from parallel runs. |
| A5 | Undo result types | wtf_cleaner/undo.py:32 `UndoOutcome` + :43 `UndoResult` (`_with`/`restored`/`skipped`/`failed`) vs ace3_profile_manager/undo.py:41 + :50 | Same status-filter properties. WTF uses constants (`RESTORED`… :23-25), Ace uses string literals. |
| A6 | `destination(wow_root, flavor, rel)` | wtf_cleaner/undo.py:67 vs ace3_profile_manager/undo.py:71 | Same flavor and `..` guards. Ace adds the `WTF/Account/.../SavedVariables` shape check. Could become a core helper with an `allowed_prefix` parameter. |
| A7 | Incomplete-run marker (`Marker`, `write_marker`, `read_marker`, `clear_marker`) | wtf_cleaner/safety.py:33/64/75/94 vs ace3_profile_manager/editor.py:97/108/116/131 | Same lifecycle. The fields differ. |
| A8 | Per-tool journal wrappers `latest_undoable` / `prune_journals` (prune + log `<prefix>.journal_pruned`) | wtf_cleaner/journal.py:78/82, ace3_profile_manager/journal.py:85/89, screenshot_organizer/journal.py:45/50, interface_backup/journal.py:35 | Only the reader and event name change. A factory or a core `prune_journals(..., event=)` would remove them. |
| A9 | `resolve_journal_dir(wow_path)` = `journal_dir(wow_path, TOOL_NAME)` | screenshot_organizer/settings.py:47, interface_backup/settings.py:46, ace3_profile_manager/settings.py:125; wtf_cleaner/journal.py:28 `clean_journal_dir` | Trivial, four copies. |
| A10 | `validate_backup_dir` wrapping `validate_output_dir` | interface_backup/settings.py:51, ace3_profile_manager/settings.py:129, screenshot_organizer/settings.py:52 (`validate_dest`), inline at wtf_cleaner/app.py:98 | Ace's docstring already says "as Interface Backup does". |
| A11 | Multi-flavor run containers (`FlavorRun.status`, `Multi*Result._with`/`stopped`/outcome properties) | wtf_cleaner/multi.py:52-111 vs ace3_profile_manager/multi.py:30-78 | Same shape, run serially. This is where a parallel runner would plug in (§4). |
| A12 | Flavor loop in batch functions | wtf_cleaner/multi.py:32 `scan_flavors` and :113 `execute_flavors`, ace3_profile_manager/multi.py:104 `apply_flavors`, interface_backup/backup.py:238 `back_up_all` | All loop over flavors one after another. Candidates for a shared `core/parallel.py` runner. |

### B. Textual code, belongs in `ui/`

| # | Duplicated thing | Locations | Notes |
|---|---|---|---|
| B1 | Settings screens: same `__init__` / `on_button_pressed` / `action_cancel` / `_error` / `on_mount` / Save+Cancel `ButtonRow` / NavHint text / `BINDINGS` | screenshot_organizer/app.py:30-91, wtf_cleaner/app.py:35-110, interface_backup/app.py:36-109, ace3_profile_manager/app.py:39-121 | `_error` is copied at SO:75, IB:94, Ace:102 and inlined twice in WTF :92-93/:104-105. All four parse the folder field with `to_native(raw) if raw else None`, then validate. A `ToolSettingsScreen` base could hold these. |
| B2 | `_default_backup_hint(wow_path)` | wtf_cleaner/app.py:112, ace3_profile_manager/app.py:127 | Same pattern. |
| B3 | ToolFlow boilerplate: `start` → `require_install(self._ready)`; `_ready` (open the settings wizard first if `not tool_cfg.exists`); `_after_review` (flavors/tools/exit); `open_settings` (guard + `open_general_settings` + push); `_settings_done` (same notify text) | wtf_cleaner/app.py:129-203, screenshot_organizer/app.py:113-198, interface_backup/app.py:123-203, ace3_profile_manager/app.py:144-222 | `_after_review` is identical four times. The `last_flavor_choice` save in `_after_flavor` is repeated at WTF:154-157, SO:174-176, IB:176-178, Ace:169-171 (Ace passes `source="picker"`). The account-picker branch (`_after_account`) is in WTF:169 and Ace:184. Candidate: helpers in `ToolFlow` (`remember_flavor`, `pick_account`, default `_after_review` and `open_settings(screen_factory)`). |
| B4 | Background-filled flavor-picker notes (push the picker, run a worker, `_ready` checks `picker in screen_stack`, then `set_notes`) | screenshot_organizer/app.py:123-159, interface_backup/app.py:133-160 | Shared pattern; could be `FlavorScreen.fill_notes_async(worker)`. |
| B5 | Review-tree subclasses with one ← binding | wtf_cleaner/review_screen.py:97 `ProposalTree`, screenshot_organizer/review_screen.py:110 `ShotTree`, interface_backup/review_screen.py:160 `BackupTree`, interface_backup/restore_screen.py:57 `RestoreTree`, ace3_profile_manager/review_screen.py:149 `ProfileTree` (adds down→bar) | One `ReviewTree(Tree)` class in `ui` would cover them. |
| B6 | `action_toggle` (Space: press a focused Button or Checkbox, else tick or untick the tree node, log `ui.item_toggled`, `_refresh_labels`) | wtf_cleaner/review_screen.py:445, screenshot_organizer/review_screen.py:438, interface_backup/review_screen.py:554, ace3_profile_manager/review_screen.py:720 | Same skeleton. The key extraction differs. |
| B7 | `action_select_all` / `action_select_none` (`a` / `n`, already the same keys in all four) | WTF :469/:476, SO :463/:470, IB :576/:581, Ace :745/:751 | Two tick models: WTF, SO and IB keep an `unchecked` set (everything ticked by default), Ace keeps a `ticked` set. Only Ace's select-all is filter-aware (`_tick_keys(tree.root)`, "visible keys only", :747). Ace's select-none clears everything, hidden items included. A shared filter-aware select needs one tick model, or an adapter. |
| B8 | Leave actions: `action_flavors` / `action_tools` / `action_quit_tool` guarded by `app.busy` | wtf_cleaner/review_screen.py:513-523, screenshot_organizer/review_screen.py:476-486 vs one `action_leave(choice)` at interface_backup/review_screen.py:864, ace3_profile_manager/review_screen.py:1478 | Two styles for the same thing. Standardise on `action_leave`. |
| B9 | Running-WoW preflight worker (`_run_preflight` → `_preflight_worker` → `_preflight_done`, `BUSY_STYLE` "Checking…") | wtf_cleaner/review_screen.py:576-606, interface_backup/review_screen.py:587-622 (public `run_preflight`, with `extra`), ace3_profile_manager/review_screen.py:1148-1173 | Three copies. IB's is the most general (check + extra), so promote that one. |
| B10 | Debounced rebuild (`_schedule_rebuild` / `_run_scheduled_rebuild`, `tree.loading`, "Updating the list…") | wtf_cleaner/review_screen.py:290-306, ace3_profile_manager/review_screen.py:451-466 | Copied word for word. Filtering in every tool will need it everywhere. |
| B11 | Scan worker plumbing (`_scan_worker` / `_scan_progress` / `_scan_failed` / `_scanned`, scan-box ProgressBar + `#scan-label`) | WTF :237-259, SO :244-269, IB :330-361, Ace :398-436 | Same flow of states. |
| B12 | `on_button_pressed` mapping button ids to actions | WTF :525-531, SO :488-494, IB :868-874, Ace (similar) | Could be a class-level `BUTTON_ACTIONS` dict in a base class. |
| B13 | Result screens: same compose (summary DataTable + detail DataTable + Rescan / Other flavor / Tools / Quit buttons + `RESULT_HINT` + BrandBar/Footer), same `on_button_pressed` / `action_choose` (log `ui.selection` + dismiss) | screenshot_organizer/review_screen.py:52-107, interface_backup/review_screen.py:108-157, interface_backup/restore_screen.py:327-390, ace3_profile_manager/result_screen.py:24-89, wtf_cleaner/result_screen.py:128-212 | Ace's `ProfileResultScreen` is already generic (title, summary_rows, columns, detail_rows, back). It is a ready base for a `ui/result_screen.py`. The status-colour maps also repeat: wtf_cleaner/result_screen.py:31, ace3_profile_manager/result_screen.py:20, inline at interface_backup/review_screen.py:144. |
| B14 | Recovery popups (same CSS block, `$warning` border, title, message, two buttons) | wtf_cleaner/review_screen.py:60 `RecoveryScreen`, ace3_profile_manager/review_screen.py:103 `ProfileRecoveryScreen` | The CSS strings are near copies. A `ui.dialogs.ChoiceScreen` / `WarningScreen` would cover both. |
| B15 | Progress subclasses | wtf_cleaner/review_screen.py:49, screenshot_organizer/review_screen.py:40, interface_backup/review_screen.py:98, ace3_profile_manager/review_screen.py:95 | Already shared through `ProgressScreen`. For the fixed-size request, the change goes only in `ProgressScreen.DEFAULT_CSS` (dialogs.py:349-355). |
| B16 | Search filter | Only Ace has one: `Filters.search` + `matches()` (ace3_profile_manager/tree_view.py:24-44), `#search` Input (review_screen.py:291), `/` → `action_focus_search` (:221, :791), `on_input_changed` → `_schedule_rebuild` (:782) | The generic part (search text, `matches`, `narrowing`, `/` binding, Input widget, rebuild hook) can be lifted into `ui/` as a tree-filter mixin. |

### C. Dead code (also flagged in the user request)
- `InstallError` at core/install.py:41: no references in wowtools or tests.
- `SNAPSHOT_NAME` at wtf_cleaner/safety.py:29: no references.
- `test_structure.test_dead_code_is_gone` (tests/test_structure.py:84) is where to pin their removal: `assertFalse(hasattr(install, "InstallError"))`.
- wtf_cleaner/review_screen.py:43-44 keeps a `ConfirmScreen` re-export "for one release", and test_structure.py:63 asserts it. Retiring it also needs that assertion dropped.

## 3. Rules in `tests/test_structure.py`
- `test_no_tool_imports_another_tool` (:41): AST-scans every module under `wowtools/tools/<name>/` and fails on any import starting `wowtools.tools.<other>`.
- `test_shared_helpers_are_defined_once` (:54): `safe_progress` and `remove_quietly` may be defined only in core/fsutil.py; `_safe_progress`, `_remove` and `_discard` are banned. The same pattern can pin new library helpers (`plural`, `flavor_name`, `human_size`, `ThrottledProgress`) to one definition.
- `test_shared_dialogs_live_in_ui` (:59): `ConfirmScreen` and `ProgressScreen` may be defined only in `wowtools/ui/dialogs.py`; tool progress screens must subclass `ProgressScreen`.
- `test_literals_are_defined_once` (:72): `"wow-tools"` appears only in core/journal.py; `#4CC38A` is never assigned (it comes from the theme); `86400.0` appears once.
- `test_dead_code_is_gone` (:84).
- `test_every_module_has_the_future_import` (:93): covers `wowtools`, `scripts` and `tests`.
- `test_wowtools_imports_are_in_order` (:102): top-level `from wowtools… import` lines are sorted by module name. New `wowtools.common.*` or `wowtools.ui.*` imports must slot in alphabetically.
- No test enforces that `core` never imports Textual. CLAUDE.md states the rule, but test_structure has no check for it. A shared library split by Textual dependency would benefit from one.

## 4. Docs: structure and where a "common library" policy belongs
- `docs/`:
  - `adding-a-tool.md` (85 lines)
  - `architecture.md` (672 lines; sections: Layers :3, Core modules :23, per-tool data flows, UI :570, Look and feel :597, Testing :662)
  - per-tool guides
  - `events.md` (generated)
  - `releasing.md` (40 lines, numbered steps; no changelog step)
  - `vendoring.md`
  - `assets/`
  - `superpowers/{specs,plans}`
- **The policy partly exists already.** adding-a-tool.md step 1 says: "**Code another tool already has** moves to `wowtools/core/` first, never imported across tools." It is limited to `core/` and does not mention `ui/`. A separate bullet covers "Shared dialogs" and "One look". Places to put the new rule ("needed by 2+ tools → shared library"):
  1. **CLAUDE.md**, Conventions: one bullet next to the "Shared dialogs … a tool never imports another tool" line. This file is the main instruction surface.
  2. **docs/adding-a-tool.md**, step 1: generalise the "Code another tool already has" bullet to name both `core/` (no Textual) and `ui/` (Textual), with the 2-tool threshold.
  3. **docs/architecture.md**, "Layers" (:3-11): name `core/` + `ui/` as "the shared library (in-repo, not a separate package)". Extend the tables at :23 and :570 for the new modules.
  4. Optionally `tests/test_structure.py`: add the new helper names to `test_shared_helpers_are_defined_once`, plus a "core never imports textual" test.
- The changelog request also touches `releasing.md` (add a step: "add a CHANGELOG entry for vX.Y.Z") and README "Version History" (:257). That section is already a per-version table that a changelog screen could read or replace.

## 5. Suggested library layout
This extends the existing split instead of adding a new `wowtools/common/`. Reasons:
- CLAUDE.md, test_structure, the docs and every import already treat `core` as UI-free shared code and `ui` as shared Textual code.
- A third package would blur the "core never imports textual" rule.
- The import-order test and the existing paths would change everywhere.

```
wowtools/core/                 UI-free shared library (no textual)
  text.py        plural, flavor_name, human_size          (A1-A3)
  progress.py    ThrottledProgress (+ move safe_progress here, or keep in fsutil and re-export)  (A4)
  parallel.py    run_per_flavor(items, fn, workers=cfg.parallelism, progress=...)  (A11/A12, new [general] key)
  undo.py        UndoOutcome/UndoResult base, safe destination()  (A5/A6)
  marker.py      run-in-progress marker read/write/clear          (A7)
  journal.py     + tool-journal helpers (prune with event name, reader-bound latest_undoable)  (A8/A9)
  install.py     + validate_backup_dir-style wrapper              (A10)
wowtools/ui/                   Textual shared library
  dialogs.py     (existing) + ChoiceScreen/WarningScreen (B14); fixed-size ProgressScreen
  widgets.py     (existing) + ACTION_VARIANTS expansion for per-action colours
  review.py      ReviewTree (B5), ReviewScreenBase: leave/back (B8), preflight (B9), schedule_rebuild (B10),
                 scan-worker skeleton (B11), BUTTON_ACTIONS dispatch (B12), toggle/select_all/none (B6/B7)
  tree_filter.py TreeFilter (search text, matches, narrowing) + "/" binding + filter-aware select all/none (B16)
  result_screen.py  generic ResultScreen (from ProfileResultScreen) + status-colour helper (B13)
  settings_form.py  ToolSettingsScreen base (B1/B2)
  tool_flow.py   (existing) + remember_flavor, pick_account, default _after_review/open_settings (B3), async picker notes (B4)
  changelog_screen.py  (new feature: version list left, notes right)
```
`dialogs.py` is already about 390 lines. Putting the review base, filters and results in new modules keeps it from growing into one large file. Keep re-exports where tests pin `dialogs.*` names.

## Open questions / decisions
1. **Package location:** extend `core/` + `ui/` and call them "the shared library" in the docs (recommended), or create a new `wowtools/common/` package? `common` would need test_structure and doc changes, and still a UI-free/Textual split.
2. **Threshold wording:** the request says "2 more apps". Should it read "2 or more tools" (move on the second use, as adding-a-tool.md already implies) or "more than 2"?
3. **Tick model:** WTF, SO and IB use "unchecked" sets (default all ticked); Ace uses "ticked" (default none). Filter-aware select all/none needs one model, or select actions that work on visible keys only. Should all tools converge on one model, and which default (all ticked or none ticked)?
4. **Select within a filter:** should "select none" clear only the visible items (Ace clears everything today, ace review_screen.py:751)? Should hidden ticked items still count toward Apply/Clean, and should the summary say how many hidden items are ticked?
5. **Filter key:** Ace uses `/` for search. Should every tool use `/`? Should `a`/`n` remain select all/none? Note that `n` is also "No" in `ConfirmScreen` and `c` is "collapse all" (`TREE_BINDINGS`), which matters for the menu's changelog `c`; that one is on a different screen, so it is fine.
6. **What filters mean per tool:** a text search only, or search plus tool-specific checkbox filters? What gets searched (file, addon, flavor, date)? SO and IB have no filter controls today; each new left-pane control needs its own row (look-and-feel rule).
7. **Tool menu changes and versions:** does the version line on the tool menu (`ToolMenuScreen`, suite_app.py:89) go in `Banner`? `git tag` lists no tags, yet `__version__="1.0.0"` and the README lists 1.0.0 (2026-10-04). Should 1.0.0 be treated as the first changelog entry, and should it be tagged?
8. **Changelog source:** a new `CHANGELOG.md` parsed at runtime, a Python data module, or the README "Version History" table? It must survive zip updates (the updater replaces only the root `*.md` files a release ships, so a root `CHANGELOG.md` works).
9. **Per-action button colours:** Textual has only five button variants (default, primary, success, warning, error). "Unique colour per action" needs custom CSS classes beyond `ACTION_VARIANTS`. Which actions get which colours: back up, restore, organize, apply, clean, dry run, rescan, undo, navigation?
10. **Default-Yes confirms:** 11 of the 12 `ConfirmScreen` calls start on No on purpose, for risky actions (documented in adding-a-tool.md and architecture.md). The request says Yes should be the default. Should that hold for destructive confirms too (Clean, Restore, Apply), or only non-destructive ones? The docs say the opposite today and would need rewording.
11. **Parallelism:** what default for the factor and what range? Should it apply to scans, writes, or both? Should two flavors share one destination (backup root, snapshot folder)? Event-log ordering and `app.busy` / `activity.running()` semantics with N workers? How should a fixed-size `ProgressScreen` show N concurrent flavors: one row per worker, or an overall bar? Today it is one stage, one bar and one file line, with `height: auto`.
12. **`ConfirmScreen` re-export:** remove the re-export in wtf_cleaner/review_screen.py now, along with the dead code? It was kept "for one release", and test_structure.py:63 asserts it.