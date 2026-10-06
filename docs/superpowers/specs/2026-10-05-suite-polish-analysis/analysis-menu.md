# Tool menu, version, release and changelog: current state

## 1. Tool-menu screen (app selector)

**File:** `wowtools/ui/suite_app.py`

**`ToolMenuScreen(Screen[None])`, lines 89-123.** `compose()` at lines 101-110 yields these widgets, top to bottom:
1. `Header()`: title `Ka0s · WoW Tools`, from `Ka0sApp.TITLE` in `ui/base.py:80`. The subtitle is "Choose a tool".
2. `Banner()`, from `ui/branding.py:22-29`. The shield art plus the line `"K a 0 s   ·   W o W   T o o l s"` (the `BANNER` constant, lines 9-19). Its CSS is `width:100%; height:auto; content-align/text-align center; color:$accent; bold; padding:1 0`. It is 11 rows tall: 9 lines of art plus 2 of padding.
3. `Static("Choose a tool", id="pick-title")`.
4. `OptionList(id="tools")`. It has one `Option` per entry in `TOOLS`, built by `tool_label()` (lines 84-86) with `LIST_NAME_STYLE` as gold names in a column. Its CSS is `margin:1 2; height:auto; border:tall $primary`.
5. `NavHint("↑↓ choose · Enter open · s settings · q/Esc quit")`.
6. `BrandBar()`, from `ui/branding.py:32-49`. It is `dock: bottom; height:1`. It shows `Ka0s WoW Tools v{__version__}` and, when an update is available, adds `"⬆ vX available, press u to update"`.
7. `Footer()`.

**Bindings:**
- `ToolMenuScreen.BINDINGS` (line 99): `q,escape → app.quit` ("Quit"), plus `NAV_BINDINGS` (up/down move focus, hidden).
- `WowToolsApp.BINDINGS` (line 128): `s → settings`.
- `Ka0sApp.BINDINGS` (`ui/base.py:84`): `u → update`, with `show=False`.
- `Ka0sApp.CSS` hides the command-palette footer key.
- At 120x30 the footer currently reads ` q Quit  s Settings`.

**The menu has no toolbar or button row.** The only interactive widget is the OptionList. Under CLAUDE.md's look-and-feel rule, a menu "toolbar" would be either a `ButtonRow` using `action_button(...)` (`ui/widgets.py:30-32`) or footer bindings only.

**Key `c` on the menu is free.** No menu, app or `Ka0sApp` binding uses it. `c` is bound only in `TREE_BINDINGS` (`ui/dialogs.py:44-47`, `collapse_all`), which tree screens, `ConfirmScreen` and `InfoScreen` bind. Those screens are pushed above the menu, so their `c` takes precedence there. Two caveats:
- A changelog screen that uses a `Tree` and binds `TREE_BINDINGS` would give `c` a second meaning on that screen.
- If the new cross-tool filter shortcut (a separate item in this request) is meant to be global, it must not be `c`, `x`, `s`, `u` or `q`.

## 2. Measured layout (headless `run_test`, scratch script only, no repo changes)

**At 120x30:**

| Widget | Rows |
|---|---|
| Header | y0 |
| Banner | y1-11 (the "K a 0 s · W o W T o o l s" line is y10, y11 is padding) |
| pick-title | y12 |
| OptionList | y14-19 (4 tools plus border) |
| NavHint | y21 |
| Empty | y22-28 (**7 free rows**) |
| Footer | y29 |

`max_scroll_y` is 0.

**At 80x24:** the tool descriptions wrap to two lines, so the OptionList is 10 rows. `max_scroll_y` is 3, so the screen already scrolls and the NavHint sits below the fold. Any added line (version, disclaimer) makes this worse. The 80x24 rule is "must keep working", not "must fit", and `test_tiny_terminal_still_works` (`tests/test_look_and_feel.py:525`) doesn't open the menu layout at all. The menu has no look-and-feel test of its own.

## 3. Bug: the BrandBar is never visible

`BrandBar` and `Footer` are both `dock: bottom`, and in Textual 8.2.8 docked siblings overlap rather than stack. Measured at 120x30, both have region `(0,29,120,1)`, and the rendered last line is only the footer. On `SetupScreen` the last row shows `esc Cancel` and no version. With `app.release` set, the "available, press u" text doesn't show either.

All 19 `BrandBar()` uses in `wowtools/` sit next to a `Footer()`, so the version label and the update notice are hidden on every checked screen. This contradicts the README at line 158 ("the bottom bar says so"). Tests at `tests/test_ui_base.py:66` and `:80` assert only `BrandBar.text`, not its visibility, so they pass.

This matters for this request in two ways:
- The version is effectively not shown anywhere in the UI today.
- Any new bottom "terms" strip must not be one more `dock: bottom` widget. It would need a single combined bottom container, or an in-flow widget.

## 4. Version: where it is defined and used

| Location | Use |
|---|---|
| `wowtools/__init__.py:4` | `__version__ = "1.0.0"`, the single source |
| `wowtools/suite.py:14,31,48-49` | `usage()` header, `--version` |
| `ui/branding.py:7,45` | BrandBar text (hidden, see §3) |
| `ui/base.py:13,40` | UpdateScreen label "you have v…" |
| `core/updater.py:21,29,116,165` | User-Agent, `check_for_update(current=__version__)`, `_VERSION_RE` for staged installs |
| `core/events.py:29,212` | `suite_version` on every log event |
| `scripts/build_release.py:19,36-41,56-60` | `_VERSION_RE` reads `__init__.py`; refuses if the tag holds a different version |
| `README.md:3` | Static badge `Version-1.0.0` (bumped by hand) |

## 5. Releases, tags and the update mechanism

**Tags and history:**
- `git tag` returns nothing: **no tags exist**, which matches the memory note "no release exists".
- 275 commits, from 2026-09-27 to today.
- Remote: `github.com/tusharsaxena/wow-tools`. CI: `.github/workflows/tests.yml`.

**Release process (`docs/releasing.md`):**
1. Green CI and `gen_event_docs.py --check`.
2. Bump `__version__`.
3. `git commit -am "release: vX.Y.Z"`.
4. `git tag vX.Y.Z` and push the tags.
5. `scripts/build_release.py` builds `dist/wow-tools-vX.Y.Z.zip` (a `git archive` of the tag) and `dist/SHA256SUMS`.
6. `gh release create … --notes "..."`. "The notes appear in the in-app update prompt."
7. Verify.

There is no changelog step. A "update CHANGELOG" step belongs between steps 2 and 3, so the file is inside the tagged archive.

**How the updater finds versions (`core/updater.py`):**
- `fetch_latest()` (lines 86-105) reads GitHub's latest published, non-prerelease release.
- `tag.removeprefix("v")` must pass `parse_version()` (lines 53-57, strict `X.Y.Z`).
- `is_newer()` is at lines 60-62. Release notes come from `payload["body"]`.
- `check_for_update()` (lines 116-153) is throttled through `[general] last_update_check` / `latest_seen_version`. On a throttled hit, `ReleaseInfo.from_version()` has **empty notes**.
- `UpdateScreen` (`ui/base.py:23-55`) renders the notes with Textual's `Markdown` widget inside a `VerticalScroll`. That is a ready pattern for drawing changelog text.

**Shipping a changelog file:**
- `git archive` ships every tracked file.
- On update, `MANAGED_DIRS = ("wowtools","vendor","scripts","docs")` (line 158) plus root `*.md` files that the release ships (`_shipped_names` / `_replaced_names`, lines 350-362) are replaced.
- So a `CHANGELOG.md` at the repo root or under `docs/` is delivered and refreshed by both git and zip updates. For a Python-parsed form, `wowtools/` works too.

**No `CHANGELOG*` file exists.**

**Unrelated finding:** `CLAUDE.md` says the tools have "no CLI mode". That holds for the tools themselves; the suite has only `update`, `--version` and `--help`.

## 6. What a changelog screen needs, and what it can reuse

**Data source options:**
- (a) A `CHANGELOG.md` parsed at runtime, for example Keep-a-Changelog `## [X.Y.Z] - date` sections. A parser would live in `wowtools/core/` (no textual import there, per the conventions).
- (b) A Python data module, for example `wowtools/changelog.py`, with `CHANGES: list[(version, date, markdown)]`.

**Testability:** the parser should be pure and unit-tested. A test can pin "`__version__` has an entry", so a release can't ship without one. `build_release.py` could also refuse a tag whose version has no entry; it already validates the tag's `__init__.py`.

**Layout options:**
- **Mirror the two-pane screens.** `two_pane_css(screen, tree, width=FILTERS_WIDTH)` (`ui/dialogs.py:51-67`) defines `#body`, a left `#filters` pane (default width 50) with `border-right: solid $primary`, and a right pane at `1fr`. The `TwoPaneFocus` mixin (`ui/dialogs.py:216-244`) provides ←/→ between `#filters` and `TREE_SELECTOR`. Existing users:
  - `BackupReviewScreen` (`interface_backup/review_screen.py:166`)
  - `RestoreScreen` (`interface_backup/restore_screen.py:63`, `width=46`)
  - `ShotReviewScreen`
  - `ReviewScreen` (wtf_cleaner)
  - `ProfileReviewScreen`
  - `BlacklistScreen`
- **Fit with the conventions.** `TwoPaneFocus.action_focus_tree` expects a `Tree`. A changelog with an `OptionList` of versions on the left (styled like `#tools`, with `LIST_NAME_STYLE` and `LIST_CURSOR_BACKGROUND`) and a `Markdown` or `VerticalScroll` on the right fits "one focusable control per row in the left pane" without forcing a Tree. In that case it doesn't need `TREE_BINDINGS`, and `c` stays unambiguous.
- **List-to-detail without trees.** `ui/flavor_screen.py` and `ui/account_screen.py` (OptionList-based) are simpler models.
- **Width:** `FILTERS_WIDTH` of 50 is too wide for a version list. Something like 20-24 would do, via `two_pane_css(..., width=N)` or custom CSS.
- **Screen type and chrome:** it should be a full `Screen` with `Header()`, `Footer()`, `BrandBar()` and a `NavHint`, and bind `escape` (and maybe `c` again) to close.
- **Logging:** it should call `log_event("ui.selection", screen="tool_menu", control="changelog", …)`. `ui.selection` is already registered (`core/events.py:60`), so no event-doc regeneration is needed unless a new event is added.
- **Menu wiring:** `ToolMenuScreen.BINDINGS` gets `Binding("c", "changelog", "Changelog")`, and the menu NavHint text needs updating.
- **Refusal pattern:** follow `WowToolsApp.action_settings`. Refuse while `self.flow is not None` or `busy`, or bind only on `ToolMenuScreen` so it can't fire inside a tool.

**Tests touching this area:**
- `tests/test_suite_app.py` (menu)
- `tests/test_ui_base.py:66,80` (BrandBar text)
- `tests/test_look_and_feel.py`: `assert_footer_whole` at line 420 needs every footer key whole at 120x30. Menu footer keys are currently few, so adding "c Changelog" is fine.
- `tests/test_structure.py`: future import, import order, literals.

## 7. Version below the logo, and a disclaimer footer

**Version under the logo:**
- The simplest change is to make `Banner` render `BANNER + "\n" + f"v{__version__}"`. That adds one row (Banner becomes 12 rows).
- The alternative is to fix the hidden `BrandBar` (§3), for example by stacking BrandBar and Footer in one docked `Vertical`, or by giving BrandBar `dock: bottom` with Footer laid out above it.
- `Banner` is used only by `ToolMenuScreen` (grep: the menu is its only compose use), so it's a safe place to change.

**Disclaimer or terms at the bottom:**
- At 120x30 there are 7 free rows (y22-28). A 2-3 line muted `Static` (for example `color:$text-muted`, wrapped, `padding:0 2`) fits as an in-flow widget after the NavHint, or docked inside a single bottom container together with Footer and BrandBar.
- An extra separately docked widget would overlap like BrandBar does.
- At 80x24 the screen already scrolls by 3 rows. A disclaimer adds 3-4 more (wrapped at 78 columns), so it sits below the fold unless it is docked. If docked, it takes rows from the OptionList area, which is fine because the screen scrolls.
- No existing test constrains the menu at 80x24.
- Suggested wording: "Provided as is, without warranty of any kind. You use these tools at your own risk. Every tool backs up the files it changes before changing them, but keep your own backups of your WoW folders as well."

## Open questions / decisions

1. **Changelog source format:** a root `CHANGELOG.md` (human-readable on GitHub, parsed at runtime) or a Python data module (no parser)? And should GitHub release notes (`--notes`) be generated from that entry?
2. **Backfilling entries:** no tags exist, yet the request says "every tagged release has an entry". Should the first entry be `1.0.0` (unreleased or to-be-tagged), with an `Unreleased` section in the meantime? Should the changelog screen show `Unreleased`?
3. **Release for these changes:** does this work ship as `1.0.0`, the first tag, or bump to `1.1.0`? This decides the first changelog entry and the README badge.
4. **Enforcement:** should `build_release.py` and/or a unit test refuse a release whose `__version__` has no changelog entry?
5. **Version placement:** a version line under the logo in `Banner`, and also fix the hidden BrandBar (§3), which today also hides the "update available, press u" notice on every screen? Fixing it costs one row on every screen, and review screens at 120x30 are tight (see `test_ace_tree_keeps_12_rows_*`).
6. **Changelog "toolbar":** the menu has no button row today. Is "toolbar" the footer key (`c Changelog`) only, or should the menu gain a `ButtonRow` (Changelog / Settings / Quit)? A ButtonRow changes focus behaviour (one focusable control per row, ←/→ only in ButtonRow).
7. **Changelog right pane:** rendered Markdown (bullets, headings) or a plain tree of change items? A Tree brings `TREE_BINDINGS`, where `c` means collapse all.
8. **Changelog grouping:** group entries by tool (Added/Changed/Fixed per tool) or keep them flat?
9. **Disclaimer behaviour:** always-visible static text, or also a one-time acknowledgement on first run (for example in `SetupScreen(first_run=True)`) stored in `[general]`? "The user acknowledges" suggests an explicit acceptance may be wanted.
10. **Disclaimer at 80x24:** docked (always visible, shrinks the tool list) or in-flow (may scroll off at 80x24)?
11. **Filter shortcut key:** for the separate filtering item, which key? It must avoid `c`, `x`, `s`, `u` and `q`, plus each tool's existing action keys.

Files read: `wowtools/ui/suite_app.py`, `wowtools/ui/branding.py`, `wowtools/ui/base.py`, `wowtools/ui/widgets.py`, `wowtools/ui/dialogs.py`, `wowtools/__init__.py`, `wowtools/suite.py`, `wowtools/core/updater.py`, `scripts/build_release.py`, `docs/releasing.md`, `tests/test_look_and_feel.py`, `tests/test_structure.py`, `tests/test_ui_base.py`. The layout measurement scripts are in `/tmp/claude-1000/-mnt-d-Profile-Users-Tushar-Documents-GIT-wow-tools/266b10e4-b7bc-420c-a62b-9d17b5f84f9b/scratchpad/` (`measure.py` and `m2.py`).