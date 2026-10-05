# Dead code, tests and docs: research report (wow-tools, read-only)

## 1. `InstallError` (`wowtools/core/install.py:41`)
- It is defined as `class InstallError(Exception): """The configured folder is not a usable WoW install."""`.
- A whole-repo grep (`--exclude-dir=.git --exclude-dir=vendor`) finds it only at its definition and in two historical plans: `docs/superpowers/plans/2026-09-27-wtf-cleaner.md:1095` and `:1328`. Nothing in `wowtools/`, `tests/`, `scripts/`, `README.md` or the current `docs/*.md` raises, catches or imports it.
- `install.py` has no `raise` statement at all. Its only `except` is `_subdirs()` at line 50, which catches `OSError` and hands it to the `on_error` callback. Invalid states are reported through return values instead:
  - `WowInstall.is_valid()` (line 133) returns a bool.
  - `WowInstall.flavor(name)` returns `None` (line 141).
  - `validate_output_dir(...)` (line 180) returns `str | None`, an error message. The settings screens of all 4 tools import it and show the message inline.
- Callers (`ToolFlow.require_install()`, the settings screens, `wtf_cleaner/app.py`) branch on those return values. No path would gain anything from an exception. Switching to one would mean adding `try` blocks to UI code that handles return values today.
- **Recommendation: delete it.** It is safe to remove: there are no imports, and it is not in `__all__`. Optionally add `self.assertFalse(hasattr(install, "InstallError"))` to `tests/test_structure.py::test_dead_code_is_gone` (line 86), which already guards three removed names.

## 2. `SNAPSHOT_NAME` (`wowtools/tools/wtf_cleaner/safety.py:29`)
- It is `SNAPSHOT_NAME = re.compile(r"^backup-(?P<flavor>.+?)-(?P<stamp>\d{8}-\d{6})(?:-(?P<n>\d+))?\.zip$")`.
- The only other mentions are historical: `docs/superpowers/plans/2026-10-04-ace-profiles.md:290` ("`SNAPSHOT_NAME` stays in `safety.py`"), `docs/superpowers/plans/2026-10-04-review-fixes.status.md:23` and `reviews/2026-10-04/02_PROPOSED_CHANGES.md:341`. No code or test references it.
- `prune_snapshots()` delegates to `core.snapshot`, which has its own pattern.
- **The catch:** line 29 is the only use of `re` in `safety.py`. The `import re` at line 13 must go too, or ruff flags F401.
- **Recommendation: delete both lines.** Optionally add it to `test_dead_code_is_gone`.

## 3. Other unused module-level names
I ran an AST scan over the top-level functions, classes and assignments in `wowtools/`, counting word-boundary references across `wowtools/`, `scripts/` and `tests/`:
- `InstallError` and `SNAPSHOT_NAME` are the only names with no reference beyond their definition.
- `wowtools/core/events.py:327` `capture_events` is used only by tests. That is deliberate: its docstring says "Tests: route log_event() into a strict in-memory log". Keep it.
- Re-exports such as `safety.py:24` (`LIST_REPORT_EVERY, SnapshotProgress, wtf_files  # noqa: F401 - re-exported`) and `review_screen.ConfirmScreen` are intentional; `test_structure.py:63` asserts the latter "kept as a re-export for one release".
- Nothing else stands out.

## 4. Test infrastructure
- **`scripts/run_tests.py`:**
  - Discovers the tests with `unittest` (after `add_vendor_path()`), sorts them by id and deals them round-robin into shards (`[index::count]`).
  - `-j` defaults to `min(cpu_count, 16)`. `-k TEXT` filters by a substring of the test id.
  - Each shard is a subprocess (`--shard i/n`, `PYTHONIOENCODING=utf-8`) that prints `@@shard-result {json}` with its run, failures, errors and skipped counts. Exit code 0 only if every shard passes.
- **This run (16 CPUs):** `Ran 1055 tests in 49.5s across 16 processes (0 failures, 0 errors, 2 skipped) OK`, wall time 52.4s. CLAUDE.md says "~10s", so the suite is now about 5x slower than documented on this WSL machine, which runs on `/mnt/d`.
- **`tests/fixtures.py`:**
  - `TuiTestCase` (line 127) subclasses `IsolatedAsyncioTestCase`, and `asyncSetUp` calls `set_debug(False)`.
  - `settle(app, pilot, timeout=10)` (line 136) loops until workers finish and `screen._rebuild_pending` is false.
  - Builders: `build_wow_tree`, `build_screenshot_tree`, `build_interface_tree`, `build_ace_tree`, plus `make_config`.
  - Sizes: `BASE` (120x30), `LARGE` (160x45), `TINY` (80x24).
- **`tests/test_look_and_feel.py`** (`LookAndFeelTest`):
  - Constants: `TOOLS` (4 tools), `RUN_ACTION`, `PREPARE`, `POPUP_MAX_WIDTH` and `FORM_MAX_WIDTH` (both 100).
  - It imports `FILTERS_WIDTH, RESULT_HINT, REVIEW_HINT, TREE_HINT, ConfirmScreen, InfoScreen, ProgressScreen` from `ui/dialogs`.
  - Key tests:
    - Review left pane identical across tools (line 77).
    - Hint wraps between items (107).
    - One control per row (126).
    - x/c expand and collapse (140).
    - Result screens share one layout (312).
    - Settings fit at base (345, 365, 384).
    - **`test_footer_shows_every_key_at_base` (404):** every visible `FooterKey` must render whole as "key description" on the last line at 120 columns. Any new footer binding (filter, changelog) has to fit, or be hidden with `show=False`.
    - Popups keep a readable width at LARGE (461).
    - `test_tiny_terminal_still_works` (525).
  - A new tool-menu version line, terms text and a `c` changelog key would be checked by these at BASE and TINY. There is no test of the tool menu yet; one should be added.
- **`tests/test_structure.py`** (AST-based):
  - `test_no_tool_imports_another_tool`.
  - `test_shared_helpers_are_defined_once`: `safe_progress` and `remove_quietly` only in `core/fsutil.py`.
  - `test_shared_dialogs_live_in_ui`: `ConfirmScreen` and `ProgressScreen` are defined only in `wowtools/ui/dialogs.py`.
  - `test_literals_are_defined_once`: `"wow-tools"` only in `core/journal.py`; `#4CC38A` must not be a literal (it comes from `KA0S_THEME`); `86400.0` once.
  - `test_dead_code_is_gone`.
  - `test_every_module_has_the_future_import`.
  - `test_wowtools_imports_are_in_order`.
  - A new shared-components library should extend these: helpers defined once, and classes such as `FilterBox` or `ChangelogScreen` defined only in `ui/`.
- **`tests/test_docs.py`:**
  - `test_event_reference_is_up_to_date`: rendered output must equal `docs/events.md`.
  - `test_every_event_is_documented`.
  - `test_readme_links_a_guide_for_every_tool`.
  - `test_user_docs_cover_...`: a list of literal needles.
  - `test_ace3_profile_manager_guide_and_readme`: needs headings such as "## Keys on the review screen".
- **CI:** `.github/workflows/tests.yml`, Ubuntu and Windows × Python 3.10 and 3.13. It byte-compiles, runs `gen_event_docs.py --check`, then `run_tests.py`.

## 5. Docs (one line each, plus the update impact)

| File | Purpose | Needs an update for the new features? |
|---|---|---|
| `README.md` (273 lines) | User front page: install, run, "Navigating the app" key table (lines 107-122: ↑↓ Enter x c Esc s q), terminal size, settings, undo/journals, logs, FAQ, **Version History** table (line 257: "Unreleased" plus 1.0.0 2026-10-04), credits | **Yes**: key table (filter key, `c` changelog on the menu), a terms/disclaimer note, Version History versus the new changelog (one source?), `[general]` parallelism in "Your settings" |
| `docs/wtf-cleaner.md` | Tool guide; "Keys on the review screen" lines 86-103 (`a`/`n`, `w`, `y` "starts on Yes", `z`/`w` "starts on No") | **Yes**: filter key, `a`/`n` within a filter, button colors, confirm default text |
| `docs/screenshot-organizer.md` | Tool guide; keys lines 66-81 (`o`, `y`, `z`) | **Yes**: same as above |
| `docs/interface-backup.md` | Tool guide; keys lines 117-134 (`b` starts Yes; `z` starts No) | **Yes**: same, plus the parallel backup and its progress popup |
| `docs/ace3-profile-manager.md` | Tool guide; "### The filters" line 140, keys lines 214-242 (`/` search already exists, `a` "tick everything shown", `w` starts No) | **Yes**: unify `/` as the shared filter key |
| `docs/architecture.md` (672 lines) | Layers, core modules, config schema, per-tool data flows, `## UI` (line 570) module table (`dialogs`, `widgets` incl. `ACTION_VARIANTS` "delete red, apply green, simulate blue, revert amber, confirm blue, neutral grey"; `ConfirmScreen ... default_yes=False ... risky actions start on No`), look and feel, `## Testing` (line 662) | **Yes**: new library module(s), changelog screen, parallelism, the confirm-default change, colors |
| `docs/adding-a-tool.md` | How a tool is added (`two_pane_css`, `FILTERS_WIDTH`, four action buttons) | **Yes**: the "reuse rule" note (functionality used by 2+ tools goes into the shared library), plus the filter wiring |
| `docs/releasing.md` | Release steps (bump `__version__`, tag `vX.Y.Z`, `build_release.py`, `gh release create`) | **Yes**: add a "update the changelog" step |
| `docs/events.md` | Generated event reference, never edited by hand | Regenerate if new events are added (changelog opened, parallel backup) |
| `docs/vendoring.md` | `vendor/` rebuild from `requirements.lock` | No |
| `docs/superpowers/{plans,specs}/` | Historical plans, status ledgers and design specs | No (history; the new plan goes here) |
| `CLAUDE.md` | Agent notes and conventions | **Yes**: shared library rule, changelog-on-release rule, parallelism config key, test-time claim (~10s is stale) |

Other facts relevant to the new features:
- **No `CHANGELOG*` file exists, and `git tag` returns nothing: there are no tagged releases.** `__version__ = "1.0.0"` is at `wowtools/__init__.py:4`. The README Version History is the only change history (1.0.0 plus Unreleased).
- **Select all / select none already exist** as `a` / `n` in all four review screens. The Ace3 Profile Manager already has `/` search and a filters section.
- **`c` is already bound to "collapse all" (`TREE_BINDINGS`)** on every tree screen. The tool menu (`ToolMenuScreen` in `ui/suite_app.py`) is not a tree screen, so `c` for the changelog there does not clash, but the same key means two things in two places.
- **Colored buttons already exist:** `ACTION_VARIANTS` in `wowtools/ui/widgets.py`, one colour per kind of action.
- **Confirm defaults today:** `ConfirmScreen(..., default_yes=False)` (`ui/dialogs.py:263`, focus at line 287) is passed `default_yes=dry_run` or `True` for safe actions and `False` for risky ones:

  | Tool | Passes `default_yes=dry_run` | Passes a literal |
  |---|---|---|
  | WTF Cleaner | `review_screen.py:646` | `False` at `:784` |
  | Screenshot Organizer | `review_screen.py:512` | `False` at `:604` |
  | Interface Backup | — | `True` at `review_screen.py:652`; `False` at `:785` and `:850` |
  | Ace3 Profile Manager | `review_screen.py:1240` | — |

  Docs and `test_docs` needles state "the answer starts on No/Yes".

## 6. Events registry rules
- `wowtools/core/events.py`:
  - `EventSpec(level, description)` (line 36).
  - `register_events(owner, events)` (line 132) raises `ValueError` on an unknown level or when a name is re-registered with a different spec. It fills `REGISTRY` and `TOOL_REGISTRIES[owner]`.
  - `EventLog.emit` (line 197): an unregistered name raises `UnknownEventError` in strict mode. Otherwise it is logged as `error` with `data.unregistered_event`.
  - The default `_current = EventLog(strict=True)` (line 299). Tests use `capture_events()`, also strict.
  - A level is fixed per event; a caller may only raise it (`level=` that is higher in `LEVELS`).
- Each tool declares its events in `wowtools/tools/<tool>/events.py` (all 4 exist) as `EVENTS = {...}`, calls `register_events(TOOL_NAME, EVENTS)`, and imports the module from the package `__init__.py`.
- `scripts/gen_event_docs.py` imports every tool package and renders `docs/events.md` (header, envelope schema, and one table per registry). `--check` fails if the file is stale. The check is enforced by `tests/test_docs.py::test_event_reference_is_up_to_date` and the CI step.

## Open questions / decisions
1. **Confirm default to Yes:** today risky actions (Clean `w`, Organize `o`, Apply `w`, Undo `z`, Restore) deliberately start on **No**. The architecture doc and the four guides say so. Should every yes/no start on Yes, risky ones included, or only the ones that start on No today minus the destructive ones?
2. **Changelog source:** should `CHANGELOG.md` replace the README "Version History" table, or should one be generated from the other? There are no git tags yet. Should "every tagged release" be read as 1.0.0 plus Unreleased?
3. **The `c` key:** `c` already means "collapse all" on every tree screen. Is `c` for the changelog acceptable on the tool menu only, or should another key be used?
4. **Shared filter key:** the Ace3 Profile Manager already uses `/` for search. Should `/` become the shared filter key? Is filtering by name only, or also by the existing view or rule filters? Should `a`/`n` (already select all/none in every tool) apply only to the visible lines?
5. **Colored buttons:** `ACTION_VARIANTS` already gives one colour per kind of action (delete red, apply green, simulate blue, revert amber, confirm blue, neutral grey). Is the request to extend this (for example, a distinct colour per action, or to settings and navigation buttons), or only to check it is applied consistently?
6. **Parallelism:** what should the config key and default be (for example `[general] parallel_jobs`, default `min(4, cpu)`)? It belongs on the setup screen next to `keep_backups`. Which operations count as conflict-free (Interface Backup across flavors, WTF Cleaner snapshots across flavors, Ace3 Profile Manager across accounts)?
7. **Library location:** `ui/` and `core/` already act as the shared library, with `tests/test_structure.py` enforcing it. Is the request a new package (for example `wowtools/common/`), or formalizing the existing `ui/` and `core/` plus a documentation rule?
8. **Disclaimer:** should it be static text at the bottom of the tool menu only, or also need a one-time acknowledgement stored in config?
9. **Dead code:** the recommendation is to delete `InstallError` and to delete `SNAPSHOT_NAME` together with `import re` in `safety.py`. Should guards be added to `test_dead_code_is_gone`?
10. **Stale timing:** CLAUDE.md says the suite takes "~10s"; this run took 52s on 16 shards under WSL. Should the claim be updated?