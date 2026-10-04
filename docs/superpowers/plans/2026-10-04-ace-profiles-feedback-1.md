# Feedback round 1: global retention, blacklist tree, one control per row, expand/collapse, Ace3 guidance

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.
> Progress is checkpointed in `2026-10-04-ace-profiles-feedback-1.status.md` (same folder). Read it first, resume at
> the first task not marked done, and update and commit it after every task.

**Goal:** Carry out the user's first round of feedback on the Ace3 Profile Manager. Three of the five items apply to
every tool in the suite.

**Spec:** `docs/superpowers/specs/2026-10-04-ace-profiles-design.md`, **Addendum A** (items 1–5). The base design is
in the same file.

**Branch:** `feat/ace-profiles` (continue on it; nothing has been merged yet).

## Global Constraints

- All the rules of the main plan's Global Constraints still apply (`2026-10-04-ace-profiles.md`): the future import,
  sorted wowtools imports, no textual in logic modules, no cross-tool imports, events registered and
  `docs/events.md` regenerated, temp-tree tests only, `TuiTestCase` + `settle`.
- One look and feel: shared pieces go in `wowtools/ui/dialogs.py` or `wowtools/ui/widgets.py`, never copied into a
  tool. `tests/test_look_and_feel.py` is where suite-wide UI rules are enforced. Extend it; never weaken it.
- Every commit ends with the two attribution lines given in the workflow prompt. Never push or merge from a task.
- Test commands: `python3 scripts/run_tests.py` (whole suite) and `ruff check .`. Both must pass after every task.

## Review Focus

1. **Settings files that still hold the old per-tool keys** (the user's real `config/*.cfg` holds
   `keep_backups = 10`, `keep_journals = 10` and `keep_snapshots = 2`): load must ignore them and use `[general]`;
   saving a tool's settings removes them. Test in F1.
2. **Interface Backup's "0 = keep all" for backups** must keep working through the global setting. A 0 must never
   make WTF Cleaner or Ace3 delete every snapshot. Test in F1.
3. **Key moves:** WTF Cleaner Clean on `w`, Ace3 discard on Backspace. Nothing may still answer to the old keys in a
   surprising way: `c` on a WTF review collapses, it doesn't clean. Test in F2.
4. **Blacklist pairs:** a pair for `_retail_` must not lock the same addon in `_classic_era_`. A bare legacy name locks
   it everywhere. Test in F3.
5. **80x24:** every tool's left pane, and the Ace3 tree pane with its guidance line and action bar, fit at 80x24 with
   nothing cut off. Test in F2 and F4.

---

### Task F1: global retention settings

**Files:** `wowtools/core/config.py`, `wowtools/ui/setup_screen.py` (the general settings screen),
`wowtools/tools/{wtf_cleaner,screenshot_organizer,interface_backup,ace_profiles}/settings.py` and each tool's
settings screen (`app.py`) plus every place that reads the old fields; tests in `tests/test_config.py`,
`tests/test_suite_app.py` or `tests/test_ui_base.py` (wherever the setup screen is tested), and each tool's settings
tests; `README.md` ("Your settings" table); `docs/*.md` guides where they describe the old fields.

**Behaviour:**
- `Config.keep_backups -> int`: `[general] keep_backups`, default 10. A negative or unreadable value gives 10.
  0 means keep all.
- `Config.keep_journals -> int`: `[general] keep_journals`, default 10, at least 1.
- The general settings screen (`SetupScreen`, opened by `s` and on first run) gets two Inputs under the WoW folder:
  - "Backups to keep per flavor (0 = keep all; applies to every tool)" (`#keep-backups`);
  - "Journals to keep per tool (Undo uses the newest)" (`#keep-journals`).

  Both are validated as integers. On save they are written to `[general]`.
- Each tool reads retention from the suite `cfg`, not from its own settings:
  - **WTF Cleaner:** snapshot prune and dry-run zip prune use `keep_backups`; 0 means no pruning.
  - **Interface Backup:** the backups-to-keep value comes from `keep_backups`, with its existing 0 = never delete.
  - **Ace3:** snapshot prune uses `keep_backups`; 0 means no pruning.
  - **Every tool:** journals use `keep_journals`.

  The dataclass fields `keep_backups` / `keep_snapshots` / `keep_journals` are removed from the tool settings. Tool
  code gets the values from `cfg.keep_backups` / `cfg.keep_journals`.
- Each tool's `save_settings` removes its stale keys (`keep_backups`, `keep_snapshots`, `keep_journals`) from its
  section. If `Config` has no remove method, add `Config.remove(section, key)`.
- The tool settings screens drop their retention fields.
- `core/snapshot.prune_snapshots(..., keep)` and every other pruner treat `keep <= 0` as "keep all". The WTF
  Cleaner's and Ace3's `max(1, …)` floors are gone.

**Tests (write first):**
- Config defaults are 10/10. Bad values fall back to 10. `keep_journals` 0 becomes 1. `keep_backups` 0 stays 0.
- A tool cfg holding `keep_backups = 3`, `keep_journals = 2` and `keep_snapshots = 2` gives the tool the global
  values. After `save_settings`, those keys are gone from the file.
- Pruning with keep 0 removes nothing (`core/snapshot`, the WTF dry-run zips, Interface Backup).
- The general settings screen saves both values. A non-number shows an error and doesn't save.
- The WTF Cleaner, Interface Backup and Ace3 settings screens no longer contain retention inputs.

### Task F2: one control per row, and expand/collapse all on every tree

**Files:** `wowtools/ui/dialogs.py` (or `widgets.py`): a shared `TreeKeys` mixin, or `TREE_BINDINGS` plus actions,
and the hint helper. Every tree screen:
- `wtf_cleaner/review_screen.py`, `screenshot_organizer/review_screen.py`;
- `interface_backup/review_screen.py`, `interface_backup/restore_screen.py`;
- `ace_profiles/review_screen.py`.

Also `tests/test_look_and_feel.py`, each tool's app tests, and the guides' key tables.

**Behaviour:**
- **Expand and collapse all.**
  - `x` expands every node under the root, and `c` collapses every node under the root (the root stays expanded).
  - Each tree screen has these bindings, with `show=False` like the others, and its hint gains
    `x expand all · c collapse all` before `r rescan`. The required tail `r rescan · z undo · f flavors · t tools`
    is unchanged.
  - Interface Backup's lazily loaded children are loaded by expand-all.
  - The Ace3 tree must keep its expansion memory consistent: a rebuild after `x` keeps everything open.
- **Key moves.**
  - WTF Cleaner: Clean moves from `c` to `w`, everywhere it is named (binding, hint, button label if it shows a key,
    guide, README).
  - Ace3: discard moves from `x` to `backspace`.
- **One control per row.**
  - The Ace3 View boxes go on two rows.
  - Check every tool's left pane for other side-by-side focusable controls and fix them.
  - Any tool that then no longer fits at 80x24 gets the fix that keeps the look: compact widgets, shorter labels,
    folding a heading into a placeholder. Don't drop a control.
- **New look-and-feel tests**, for every tool in `TOOLS`:
  - **One control per row:** in `#filters`, no two focusable widgets outside `#actions` have the same `region.y`.
  - **Expand and collapse:** on the review tree, pressing `x` leaves every node with children expanded, and `c` leaves
    none expanded except the root.
  - **Hint:** contains `x expand all · c collapse all`.

**Tests (write first):**
- The look-and-feel tests above.
- WTF Cleaner: `w` opens the Clean confirm, and `c` does not.
- Ace3: Backspace asks to discard pending changes.
- Interface Backup restore screen: `x` and `c` work.

### Task F3: Ace3 blacklist as (flavor, addon) pairs with a tree screen

**Files:** `ace_profiles/settings.py`, a new UI module `ace_profiles/blacklist_screen.py`, `ace_profiles/app.py`
(the settings screen), `ace_profiles/review_screen.py`, `ace_profiles/ops.py` if `locked` needs the flavor, and
`ace_profiles/events.py`. Tests in `tests/test_ace_settings.py`, `tests/test_ace_app.py` and
`tests/test_ace_ops.py`.

**Behaviour:**
- **Settings.**
  - `blacklist: list[tuple[str, str]]` holds (flavor folder, addon).
  - `parse_blacklist` reads `"_retail_:ElvUI, Questie"` as `[("_retail_", "ElvUI"), ("*", "Questie")]`. `"*"`
    (legacy bare names) matches every flavor.
  - `format_blacklist` writes `flavor:addon` and sorts.
  - `is_blacklisted(pairs, flavor_folder, addon)` compares flavor and addon case-insensitively, with `"*"` as a
    wildcard.
- **Locking.** `Staging.locked` and the review's `locked` take the file's flavor (`SvFile.flavor.folder`) as well as
  the addon. The session unlock set becomes `(flavor, addon)` casefolded pairs.
- **`BlacklistScreen(Screen[list | None])`.** `__init__(cfg, tool_cfg, flavors, pairs)`. It follows the two-pane look:
  - **Left pane:** a one-line explanation ("Ticked addons are blacklisted: their profiles are shown but never
    changed."), then a `ButtonRow` with Save (`apply`), Select none (`neutral`) and Cancel (`neutral`), then a
    `NavHint` that includes `x expand all · c collapse all`.
  - **Right pane:** a `Tree` built by a scan worker (`scanner.scan_flavors(flavors)`) with a progress box, laid out as
    flavor → addon. The addons are those with Ace3 data in any account, plus the blacklisted pairs not found
    (labelled "(not found)").
  - **Ticks:** nothing is ticked except the pairs already blacklisted. Space ticks, `a`/`n` tick all or none, `x`/`c`
    expand or collapse all.
  - **Leaving:** Save dismisses with the new pair list, and Cancel or Esc dismisses `None`.
  - A legacy `"*"` pair is shown ticked under every flavor where that addon is found. Saving writes explicit pairs
    for the ticked ones, so the wildcard goes away.
- **Settings screen.** The blacklist Input becomes a `Static` summary ("2 addons blacklisted" or "None") plus a
  button "Edit blacklist…" that pushes `BlacklistScreen` and stores the result in the form. Save then writes it.
  It works on the first-run settings too: the WoW folder is known by then.
- **Review screen.**
  - `b` toggles the highlighted addon's (flavor, addon) pair and drops that addon's pending changes, as the M3 fix
    does today, with a notify.
  - The action-bar button "Blacklist…" (Task F4) opens `BlacklistScreen` for the review's flavors. Its result is saved
    at once, followed by a refresh.
- **Event.** `ace.blacklist_changed` carries `flavor`, `addon` and `blacklisted`, or `pairs` when the whole list was
  saved.

**Tests (write first):**
- **Parse and format:** round trip, the wildcard, case-insensitive comparison. A `_retail_` pair doesn't lock the
  same addon in `_classic_era_`.
- **Blacklist screen:** it opens with nothing ticked, ticking ElvUI under Retail and saving returns
  `[("_retail_", "ElvUI")]`, and Cancel returns None.
- **Settings screen:** "Edit blacklist…" opens the screen, and the saved file holds `_retail_:ElvUI`.
- **Review:** `b` on Retail ElvUI locks it in Retail only, while Classic Era Questie stays tickable.

### Task F4: Ace3 review explains itself: pending changes, action bar, guidance line

**Files:** `ace_profiles/review_screen.py`, `ace_profiles/tree_view.py`, `ace_profiles/report.py` (texts),
`ace_profiles/events.py` (descriptions only), `docs/ace-profiles.md`. Tests in `tests/test_ace_app.py`,
`tests/test_ace_report.py` and `tests/test_look_and_feel.py`.

**Behaviour:**
- **"Pending changes" everywhere.**
  - Rename every user-visible "staged" to "pending changes": the left-pane line, `report.selection_text`
    ("Selected: … · 3 pending changes in 2 files", or "· No pending changes"), confirm texts, notifies, docs and event
    descriptions.
  - Code identifiers (`Staging`, `staged_text`) may stay, but rename `staged_text` to `pending_text` if it is cheap.
- **Tree pane layout.** The tree pane becomes a `Vertical` holding:
  - the tree (`1fr`);
  - `Static(id="guide")`, one or two lines in the muted style;
  - `ButtonRow(id="tree-actions", wrap=True)` with these buttons, using `action_button` variants:
    - Delete profile (d) and Remove leftovers (o): `delete`;
    - Assign profile (p), Rename (e) and Copy (k): `apply`;
    - Blacklist…, More… (m) and Discard (⌫): `neutral`.

  Each button calls the same action as its key. A button whose action has nothing to act on stays enabled, and
  pressing it explains what to tick or highlight; this is easier to learn than a greyed-out button.
- **Guidance line**, recomputed on every cursor move, tick change and pending change. A pure function
  `report.guidance(node_kind, node_name, ticked_profiles, ticked_chars, pending_total, pending_files)` returns the
  text:
  - nothing pending and nothing ticked: "1 Tick profiles or characters (Space) → 2 pick an action below → 3 check
    the pending changes in the tree → 4 Apply (w) writes them; Dry run (y) only checks them";
  - something ticked: "N ticked: pick an action below (Delete, Assign, …)";
  - a profile highlighted, nothing ticked: `Profile "Healer": Delete, Rename or Copy it, or tick it with Space`;
  - a character highlighted: `"Kaelys - Realm1": Assign it a profile, or remove it if it is a leftover`;
  - an addon highlighted: `ElvUI: Keep only Default or Everyone → Default (More…), or Blacklist…`;
  - something pending: "N pending changes in F files, not written yet: Apply (w) writes them, Dry run (y) checks
    them, Discard (⌫) drops them". This line comes first, with the per-node hint after it when there is room.
- **Left pane.** View (two rows, from F2), Show, Search, a "Pending changes" line, then the four run buttons and the
  hint. It must fit at 80x24 with nothing cut off; the look-and-feel tests cover it.
- **Guide.** `docs/ace-profiles.md` gets a "How it works" section near the top (the four steps), uses "pending
  changes" throughout, and documents the action bar, the guidance line and the blacklist screen. The README
  mentions are updated too.

**Tests (write first):**
- `report.guidance` for each state above.
- **Review screen:**
  - `#guide` shows the 4-step text after a scan, changes when a profile is highlighted, and shows the pending line
    after a delete;
  - every `#tree-actions` button triggers its action (Delete opens `TargetScreen`, and so on);
  - at 80x24, `#tree-actions` buttons and `#guide` lie inside the screen and the tree still has at least 5 rows.
- `selection_text` says "pending changes".

### Task F5: docs and a final check

Make the README, the guides of all four tools, `docs/architecture.md` and `CLAUDE.md` match what was built:
- the global retention settings;
- the key moves;
- expand and collapse all;
- the blacklist screen;
- "pending changes".

Then regenerate `docs/events.md` and run the full suite (parallel and serial) and ruff. Record the counts in the
ledger.
