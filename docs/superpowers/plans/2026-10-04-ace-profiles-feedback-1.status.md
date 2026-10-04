# Feedback round 1 — status ledger

Plan: `2026-10-04-ace-profiles-feedback-1.md`. Spec: `../specs/2026-10-04-ace-profiles-design.md` (Addendum A).
Branch: `feat/ace-profiles`. Resume at the first task not marked `done`. Update this file and commit it after every
task; push after the round. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| F1 | global retention settings | done | 05aa3cd | `Config.keep_backups`/`keep_journals` + `remove`/`remove_retired`; setup screen inputs; tool settings/screens lose retention (Screenshot Organizer too); pruners keep all at 0; docs + events regenerated |
| F2 | one control per row; expand/collapse all on every tree | done | 7376239 | `TreeKeys` mixin (base of `TwoPaneFocus`) + `TREE_BINDINGS`/`TREE_HINT` in `ui/dialogs.py`; x/c on every review tree and the restore screen; WTF Clean on `w`; Ace3 discard on Backspace; Ace3 View boxes one per row; look-and-feel tests for one-control-per-row and expand/collapse; guides' key tables |
| F3 | Ace3 blacklist pairs + tree screen | done | 35ec7d6 | `parse/format_blacklist`, `is_blacklisted(pairs, flavor, addon)`, `toggle_pair`, `unique_pairs` (`"*"` = legacy bare name); `Staging.locked(flavor, addon)`; `BlacklistScreen` (two panes, scan worker, flavor → addon, "(not found)", a/n/x/c); settings "Edit blacklist…" + summary; review `b` per flavor, `action_edit_blacklist` saves at once; events regenerated |
| F4 | Ace3 guidance: pending changes, action bar, guidance line | done | 4a1959c | `report.guidance`/`node_hint`/`pending_text` (was `staged_text`), `NO_PENDING`, `STEPS`; `#pending` line; tree pane `#tree-pane` = tree + `#guide` + `#tree-actions` (`WrapButtonRow` in `ui/widgets.py`, 8 compact buttons, `TREE_ACTIONS`); guide updates on cursor/tick/pending; 80x24 tree-pane test in look-and-feel; guide "How it works", action bar, guidance line, blacklist screen; events regenerated |
| F5 | docs + final check | todo | | |
| R | review, fixes, push | todo | | |

## Decisions taken during the build

- Task F1: the Screenshot Organizer's settings screen also lost its `keep_journals` input (the spec says tool
  settings screens no longer show retention; the plan's test list named only the other three).
- Task F1: Ace3's logic functions keep their `keep_snapshots` parameter name (`apply_flavors`, `undo_run`,
  `recover`, `apply_flavor`); the review screen passes `cfg.keep_backups` into it. Renaming would churn many tests
  for no behaviour change.
- Task F1: `Config.remove_retired(section)` (drops `keep_backups`/`keep_snapshots`/`keep_journals`) is the shared
  helper each tool's `save_settings` calls; `Config.remove` logs `config.changed` with `new=None` (event description
  updated to say "or was removed").
- Task F1: `wtf_cleaner/safety.DEFAULT_KEEP_SNAPSHOTS` (5) and the per-tool `DEFAULT_KEEP_*` constants are gone;
  `core/config.DEFAULT_KEEP_BACKUPS`/`DEFAULT_KEEP_JOURNALS` (10/10) replace them. The WTF confirm says "all of
  this flavor are kept" when keep_backups is 0.
- Task F1: `tests/test_docs.py` now requires `keep_backups` (not `keep_snapshots`) in the Ace3 guide.
- Task F2: to fit 80x24 with the View boxes on two rows, the Ace3 "View" heading is folded into the box labels
  ("View by addon" / "View by character").
- Task F2: expand/collapse all live in a `TreeKeys` mixin that `TwoPaneFocus` now subclasses, so every two-pane
  screen has the actions; each screen still lists `*TREE_BINDINGS` in its `BINDINGS`. Collapse-all moves the cursor
  to the top-level node it was under; expand-all keeps it on the same node.
- Task F2: the restore screen's hint puts `TREE_HINT` before `o restore` (it has no `r rescan`). The Ace3 More…
  popup names the discard key as "(Backspace)". `tests/test_docs.py` now also requires `Backspace` and `c` in the
  Ace3 guide.
- Task F3: `BlacklistScreen.__init__(cfg, flavors, pairs)`, without `tool_cfg`: the screen never reads or writes
  the tool's file (the caller saves). `cfg` (suite config) gives every flavor of the install.
- Task F3: pairs of flavors the screen does not show are kept on Save, and a legacy `"*"` pair becomes explicit
  pairs for those hidden flavors (so opening it from a one-flavor review never unblacklists another flavor).
  Likewise `b` on an addon blacklisted by `"*"` takes it off in that flavor only (`toggle_pair` expands the wildcard
  into the install's other flavor folders).
- Task F3: lists are sorted by addon, then flavor (ignoring case), so `"_retail_:ElvUI, Questie"` parses to
  `[("_retail_", "ElvUI"), ("*", "Questie")]`; `format_blacklist` writes a `"*"` pair as the bare name.
- Task F3: until F4 adds the action-bar "Blacklist…" button, the review reaches `action_edit_blacklist` through the
  More… menu (new entry `edit_blacklist`). Guide updates are left to F5.
- Task F4: the "wrapping ButtonRow" is a new shared `WrapButtonRow(ButtonRow)` in `ui/widgets.py`: Textual has no
  flowing layout, so it is a grid whose column count is set on resize from the widest label; its buttons are compact
  (one row each). At 80x24 the tree pane is 30 columns wide, so the bar is one column of 8 rows and the tree keeps 6.
- Task F4: the left pane's `#pending` line (was `#staged`) lost its top margin: with pending changes and a scan
  warning the bottom line takes two rows, which cut the hint off at 80x24. The new look-and-feel test checks the
  hint and `#pending` with and without pending changes.
- Task F4: the per-node hint replaces the four steps (the steps show on the root, a flavor or an account, or with
  nothing highlighted); with pending changes, the pending line comes first and the hint follows on a second line.
  Deleted and removed lines, warnings and notes have no hint of their own.
- Task F4: the review's "Not staged (N)" notification is now "Not done (N)"; `verify.py`'s problem texts say
  "planned" instead of "staged" (they reach the result screen). Code identifiers (`Staging`, `_staged`, the
  `ace.staged` event name) stay. The More… menu keeps its "Edit the blacklist" entry next to the new button.
- Task F4: `tests/test_docs.py` now requires "## How it works", "pending change", "guidance line", "action bar",
  "Blacklist…" and "blacklist screen" in the Ace3 guide, and no "staged" in it. The guide and README updates were
  done here (the plan's F4 file list), leaving F5 the final check.
