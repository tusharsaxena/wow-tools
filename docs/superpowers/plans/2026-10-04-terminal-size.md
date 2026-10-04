# Feedback round 2: design for 120x30 (Windows Terminal default), grow with the window

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.
> Progress is checkpointed in `2026-10-04-terminal-size.status.md` (same folder). Read it first, resume at the first
> task not marked done, and update and commit it after every task.

**Goal:** Every TUI screen of every tool looks complete at 120x30 and uses the extra space at larger sizes. 80x24 only
has to keep working.

**Spec:** `docs/superpowers/specs/2026-10-04-ace-profiles-design.md`, **Addendum B**. Addendum A and the one look
and feel rules (shared CSS in `wowtools/ui/dialogs.py`, `tests/test_look_and_feel.py`) still apply.

**Branch:** `feat/ace-profiles` (nothing has been merged yet).

## Global Constraints

- All the main plan's Global Constraints still apply.
- Every commit ends with the two attribution lines given in the workflow prompt. Never push or merge from a task.
- After every task: `python3 scripts/run_tests.py` (whole suite) and `ruff check .` pass.
- **Look at the screens.** For every screen a task touches, render it with Textual's `app.save_screenshot()` (SVG)
  at 120x30 and 160x45 into `/tmp/wow-tools-shots/<task>/`, never into the repo. Read the SVG text to check for
  truncation, wrapped hints, empty bands and squeezed trees. A layout claim with no render behind it is not done.

## Review Focus

1. **Truncation at 120x30:** a button label, hint line, tree label or popup text cut off or wrapped awkwardly.
2. **Wasted space at 160x45:** a pane or table that stays its 120x30 size and leaves a large empty band.
3. **Popups:** they fit at 120x30, stay centred and readable at 160x45, and their buttons are reachable by keyboard.
4. **80x24 smoke:** every tool's screens open and every control can be focused; nothing raises.
5. **Ace3 tree pane at 120x30:** the action bar takes at most 2 rows, the guidance line takes at most 2 rows, and the
   tree keeps at least 12 rows.

### Task S1: shared sizes, tests and CSS

- **`tests/fixtures.py`.** Add `BASE = (120, 30)`, `LARGE = (160, 45)` and `TINY = (80, 24)`.
- **`tests/test_look_and_feel.py`.**
  - Every existing check runs at `BASE` instead of 80x24. Change the module docstring to match.
  - At `LARGE`, add a check for every tool that the review tree's region is wider and taller than at `BASE` (it
    grows), while `#filters` keeps its width.
  - Add a check that every popup and confirm stays at most 100 columns wide at `LARGE`.
  - Add `test_tiny_terminal_still_works`. At 80x24 it opens, for every tool, the settings, the review and a result
    screen (through the existing `RUN_ACTION`/`PREPARE`). It checks that nothing raises and that every focusable
    widget on each screen can be focused, by tabbing through them. It asserts nothing about layout.
- **Ace3 tree-pane tests.** Rework the existing 80x24 ones (the guide-line, action-bar and left-pane fit tests) at
  `BASE`, using the Review Focus 5 numbers.
- **Shared CSS** in `ui/dialogs.py`:
  - Revisit `FILTERS_WIDTH` (50) and `two_pane_css` / `result_css` / `settings_css` / popup CSS for 120x30. Keep
    the left pane fixed and let the tree take `1fr`.
  - Give popups a width like `min(90, 80%)`, or the Textual equivalent: `width: 90; max-width: 90%`.
- **Ace3 left pane.** Restore the "View" and "Show" section headings. The checkboxes go back to "By addon", "By
  character", "Only addons with 2+ profiles", "Only unused profiles", "Leftover characters" and "Blacklisted
  addons", keeping one per row.

### Task S2: WTF Cleaner, Screenshot Organizer and Interface Backup screens at 120x30

For each of these tools, go through every screen and fix what the renders show:
- settings;
- review;
- confirm popups;
- progress;
- result;
- recovery and restore screens;
- Interface Backup's restore tree.

Their tests named or commented "80x24" move to `BASE`. A test that only guarded an 80-column squeeze, such as
"each group's row shows the name that tells it apart at 80x24", is kept at `BASE` if it still means something there,
and otherwise removed, with the reason in the ledger. Tree labels and result columns may use the extra width
(for example full timestamps or names that were shortened for 80 columns), as long as they stay consistent with the
guides.

### Task S3: Ace3 screens at 120x30

Do the same for every Ace3 screen:
- settings;
- the blacklist screen;
- the review screen, in both views, with pending changes and with a scan warning;
- every popup: target, name, actions, confirm, recovery;
- progress;
- every result screen.

The specific targets:
- At 120x30, the action bar fits in at most 2 rows, the guidance line takes at most 2 rows, and the tree keeps at
  least 12 rows.
- At 160x45, the action bar is one row.
- The guidance line can show the pending line and the node hint together at 120x30, so drop the "hint only when the
  tree keeps 5 rows" squeeze if it no longer triggers.

Update the Ace3 tests.

### Task S4: docs

- **README:** a short "Terminal size" note saying the tool is designed for Windows Terminal's default 120x30 window
  and grows when the window is maximized. A smaller window works but is cramped.
- **The four guides:** wherever they mention 80x24 or describe layout compromises.
- **`docs/architecture.md`:** the look-and-feel section, covering the sizes and the tests.
- **`CLAUDE.md`:** one line under Conventions: "Screens are designed for 120x30 (Windows Terminal default) and grow;
  80x24 must only keep working (tests/test_look_and_feel.py)".
- Run the full suite and ruff, and record the counts in the ledger.
