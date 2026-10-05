# Tree views across wow-tools: inventory and constraints for filter, select all and select none

## 1. Shared tree infrastructure (`wowtools/ui/dialogs.py`)

| Symbol | Line | Notes |
|---|---|---|
| `review_hint(space="tick")` / `REVIEW_HINT` | 36-40 | `"↑↓/Tab move · ←→ panes and buttons · Space {space} · Enter/Space press · "` |
| `TREE_HINT` | 42 | `"x expand all · c collapse all · "`. The comment says it comes "before r rescan". |
| `TREE_BINDINGS` | 44-47 | `x`→`expand_all`, `c`→`collapse_all`, both `show=False` |
| `two_pane_css(screen, tree, width=FILTERS_WIDTH)` | 50-65 | `#body` Horizontal; `#filters` is `width: 50` (`FILTERS_WIDTH`, line 28) with `border-right`; `.section` headings; `#filters Ka0sCheckbox, #filters Input {margin:0}`; `#actions` button row; tree `width:1fr`; `#scan-box` holds `#scan-progress` and `#scan-label`; `#summary` |
| `detail_tree(groups)` | 113 | Read-only popup tree `#details.popup-tree`. One branch per group, items are leaves. It opens fully when everything fits in `DETAIL_ROWS=12` lines. |
| `detail_hint` | 131 | `"↑↓/Tab move · Space open · " + TREE_HINT` |
| `tick_mark(items, unchecked, key, success=)` | 140 | Returns ✘, ◩ (`PARTLY_TICKED`) or ✔. It works from an "unchecked" collection. |
| `relabel_branch(tree, node, label, skip=)` | 154 | Relabels a node's branch and its ancestors, or the whole tree when `node` is None. Kinds listed in `skip` (read-only) are left alone. |
| `TreeKeys` mixin | 171-213 | `TREE_SELECTOR`. `_tree_for_keys()` returns None while the tree is hidden during a scan. Also `action_expand_all`, `action_collapse_all` and `_keep_cursor`. |
| `TwoPaneFocus(TreeKeys)` | 216-244 | `first_filter()` (abstract). `on_descendant_focus` remembers `_last_filter` only for widgets inside an ancestor with `id == "filters"`. `action_focus_filters` (←) and `action_focus_tree` (→). |
| `ConfirmScreen(TreeKeys, ModalScreen[bool])` | 247 | Keys: `y` yes, `n`/`escape` no, plus NAV and TREE bindings. Has an optional `detail_tree` when `groups=` is passed. `default_yes` chooses the focused button. |
| `InfoScreen(TreeKeys, ModalScreen[None])` | 296 | Keys: `escape` close, plus NAV and TREE bindings. Has a `detail_tree`. |

Supporting pieces in `wowtools/ui/widgets.py`:
- `NAV_BINDINGS` (line 41): up/down move focus.
- `ButtonRow` (line 83): ←/→ move between buttons and Space presses. With `wrap=False`, a key at either end falls through to the screen.
- `WrapButtonRow` (line 119).
- `NavHint` (line 185): wraps only between `" · "` items.
- `Ka0sCheckbox` (line 69).

App-level bindings apply on every tree screen:
- `Ka0sApp` (`ui/base.py:84`): `u` update.
- `WowToolsApp` (`ui/suite_app.py:128`): `s` settings. On a tool screen this opens the current tool's settings (`action_settings`, line 182).
- `ctrl+p` opens the command palette, which is hidden from the footer.

## 2. Every tree screen

All review screens follow the same pattern. The tree subclass binds `left` → `screen.focus_filters`. The screen binds `space` → `toggle` with `priority=True`, and `action_toggle` checks what has focus: a Checkbox toggles, a Button is pressed, and only when the Tree has focus is a node ticked.

### 2.1 WTF Cleaner: `ReviewScreen` (`tools/wtf_cleaner/review_screen.py:103`), tree `ProposalTree` (line 97), `#proposal`
- **Nodes** (`_rebuild` 308, `_add_accounts` 344):
  - root: `("group", items, name)`
  - flavor (multi only): `("group", …)`
  - account: `("group", …)`
  - owner (account-wide or character): `("group", …)`
  - addon: `("item", ProposalItem)`
  - file leaf: `("file", item, sv)`
  - A flavor that failed to scan becomes a plain leaf with no data.
- **Tickable:** every node. State is `self.unchecked: set[Path]`. `_paths(data)` is at line 367 and the marks come from `tick_mark`.
- **Select all / none:**
  - `action_select_all` (469) clears `unchecked`.
  - `action_select_none` (476) unchecks every file in `self.proposal`.
  - Neither looks at what is shown.
- **Left pane** (compose 157-179): `Label "Criteria (keys 1-4)"`, 4 `Ka0sCheckbox` `#crit_*`, `Label "Max age in days (Enter)"`, `Input #max_age` (integer, compact), `ButtonRow #actions` (Clean, Dry run, Rescan, Undo last clean), `NavHint`. `first_filter` is `#crit_<first>`.
- **Keys** (106-126): `space a n w y r z f t q escape 1 2 3 4 left right x c up down`, plus `s u` from the app.
- **Hint** (line 45): `REVIEW_HINT + "a all · n none · w clean · y dry run · " + TREE_HINT + "r rescan · z undo · f flavors · t tools"` (plus the rest).
- **Search or filter:** none. The criteria checkboxes and max age only change the proposal (`_schedule_rebuild`).
- **Risk:** `action_toggle` (445) does not handle a focused `Input`. That is harmless today because `#max_age` is an integer field, but a text filter Input would need a Space passthrough, as in Ace3 (`review_screen.py:728`).

### 2.2 Screenshot Organizer: `ShotReviewScreen` (`tools/screenshot_organizer/review_screen.py:116`), tree `ShotTree` (line 110), `#shots`
- **Nodes** (`_rebuild` 316):
  - `("root",)`
  - `("flavor", fp)`
  - `("year", fp, y)` → `("month", fp, y, m)` → `("day", fp, day)`. Day nodes get their files when expanded (`on_tree_node_expanded` 362).
  - `("filed", fp)` (copy mode). Its files also load on expand.
  - `("conflicts", fp)` with `("conflict"…)` leaves.
  - `("skipped", fp)` with `("skip", s)` leaves.
  - `("file", ShotItem)`
- **Tickable:** everything except `READ_ONLY = ("conflicts","skipped","conflict","skip")` (line 37). State is `unchecked: set[Path]` (src). Already-filed items start unticked (271). Items are precomputed per key in `_items_by_key` (`_index` 294).
- **Select all / none:**
  - `select_all` (463): `unchecked &= filed`. Already-filed copies keep their state.
  - `select_none` (470): unchecks every `plan.selectable`.
- **Left pane** (153-170): `Label Destination`, `Static #dest-label`, `Label Mode`, `Static #mode-label`, `#actions` (Organize, Dry run, Rescan, Undo last run), `NavHint`. The buttons are the only focusable controls in this pane; `first_filter` returns the first enabled button.
- **Keys** (119-135): `space a n o y r z f t q escape left right x c up down`, plus `s u`.
- **Hint** (line 36): `REVIEW_HINT + "a all · n none · o organize · y dry run · " + TREE_HINT + "r rescan · …"`
- **Search or filter:** none.
- **Filter caveat:** file leaves are created only when their day is expanded. A filter on file names has to match against `_items_by_key` (the model), not against tree nodes, and then expand the matching days.

### 2.3 Interface Backup: `BackupReviewScreen` (`tools/interface_backup/review_screen.py:166`), tree `BackupTree` (line 160), `#flavors`
- **Nodes** (`_rebuild` 392):
  - `("root",)`
  - `("flavor", scan)`, with these children:
    - `("part", scan)` leaves
    - `("links", scan)`, loaded on expand
    - `("leftover", …)`
    - `("warnings", scan)`, loaded on expand
    - `("backups", scan)`, loaded on expand (`_add_backups` 443). Its `("backup", BackupInfo)` leaves get their parts from a worker.
- **Tickable:** only root and flavor nodes. `READ_ONLY` (line 50) covers part, links, link, leftover, warnings, warning, backups and backup. State is `unchecked: set[str]` of flavor folders. Enter or Select on a backup leaf starts a restore (`on_tree_node_selected` 757).
- **Select all / none:** `select_all` (576) clears; `select_none` (581) unticks every flavor.
- **Left pane** (222-243): `Label "Backup folder"`, `Static #folder-label`, `Label Keep`, `Static #keep-label`, `#actions` (Back up, Restore, Rescan, Undo last restore), `NavHint`. Only the buttons can take focus.
- **Keys** (173-189): `space a n b e r z f t q escape left right x c up down`, plus `s u`.
- **Hint** (line 48): `REVIEW_HINT + "a all · n none · b back up · e restore · " + TREE_HINT + "r rescan · z undo · f flavors · t tools"`
- **Search or filter:** none.
- **Filter caveat:** the selection unit is a flavor, and there are at most about 5 flavors. A filter here could only narrow flavors, or narrow backups or links, which are read-only.

### 2.4 Interface Backup: `RestoreScreen` (`tools/interface_backup/restore_screen.py:63`), tree `RestoreTree` (line 57), `#effects`
- **Width:** a narrower left pane, `two_pane_css(..., width=46)` (line 71).
- **Nodes** (`_show_plan` 265):
  - `("effect", kind)`, one for each of removed, newer, links_kept, links_removed and unreadable (`EFFECTS` line 34)
  - `("group", kind, name)` folder groups, which load their files on expand (295)
  - `("file",)` leaves
  - `("note",)`
  - Warning and success leaves without data.
- **Tickable:** no. What gets restored is chosen with the `Ka0sCheckbox #part-<part>` boxes in the left pane. There is no `space` binding; Space opens a node, and the hint says "Space tick or open".
- **Left pane:** `Label Backup`, `Static #backup-info`, `Label Restore`, one checkbox per part, `#actions` (Restore, Back). `first_filter` is at line 140.
- **Keys** (72-80): `o b escape left right x c up down`, plus `s u`. The letters `a` and `n` are free here.
- **Hint** (line 32): `review_hint("tick or open") + TREE_HINT + "o restore · b/Esc back"`
- **Search or filter:** none.
- **Filter caveat:** only a read-only filter fits this screen. There is nothing to select.

### 2.5 Ace3 Profile Manager: `ProfileReviewScreen` (`tools/ace3_profile_manager/review_screen.py:182`), tree `ProfileTree` (line 149), `#profiles`
- **Tree bindings:** `left` → filters, and `down` on the last line moves to the action bar (`action_down_or_bar`).
- **Layout:** the tree sits in `Vertical #tree-pane` together with `Static #guide` and `ActionBar #tree-actions` (a `WrapButtonRow` of 10 buttons, `TREE_ACTIONS` line 63). `ActionTip` is an overlay. The tree is built by `TreeBuilder` (`tree_view.py:57`).
- **Nodes:**
  - `root`, `flavor`, `account`
  - By addon: `addon`, `db`, `profile`, `deleted`, `char`, `removed`
  - By character: `character`, `pair`
  - `warnings` and `note`
  - `READ_ONLY = ("deleted","removed","note","warnings")` (`tree_view.py:18`)
- **Tickable:** profile and char/pair nodes. State is `self.ticked: set[tuple]` holding `("p", DbKey, profile)` and `("c", DbKey, char)`. This is an inverted model: the screen stores ticked keys, where the other tools store unchecked ones (`NotTicked` adapter, line 79). Groups cover the keys of their children through `_gather`. Locked (blacklisted) nodes have no keys.
- **Filtering already exists:**
  - `Filters` dataclass (`tree_view.py:24`): `view`, `only_multi`, `only_unused`, `leftovers`, `blacklisted`, `search`.
  - `matches()` (line 38) is a casefold substring test on addon, sv_name, profile and char.
  - `narrowing` drops empty groups.
  - `searching` expands every group while a search is active and does not save that expansion state (line 78).
  - Search box: `Input #search` with placeholder "Search addon, profile or character" (compose line 282).
  - `slash` → `focus_search` (221, 791).
  - `on_input_changed` (782) rebuilds the tree.
  - `on_input_submitted` (787) and `Esc` (`action_back` 1472) move focus back to the tree.
  - Space typed in the Input is inserted as text (728).
- **Select all / none:**
  - `action_select_all` (745) ticks only visible keys (`_tick_keys(tree.root)`), so it already respects the filter.
  - `action_select_none` (751) does `ticked.clear()`, which clears hidden ticks too. This is inconsistent with select all.
  - Both are also in the More menu (`popups.py ACTION_GROUPS`): "Tick everything shown (a)" and "Untick everything (n)".
- **Left pane** (270-292):
  - `Label View`, then `Ka0sCheckbox #view-addon`, `#view-character`
  - `Label Show`, then `#only-multi`, `#only-unused`, `#show-leftovers`, `#show-blacklisted`
  - `Input #search`
  - `Static #pending`
  - `#actions` (Apply, Dry run, Rescan, Undo last change)
  - `NavHint`
  - `first_filter` is the first checkbox.
- **Keys** (203-234): `space a n d p e k o D E m backspace b u v slash w y r z f t q escape left right x c up down`, plus `s`. The screen's own `u` (unlock) shadows the app's `u` (update).
- **Hint** (line 53): `REVIEW_HINT + "a all · n none · d delete · p assign · m more · w apply · y dry run · " + TREE_HINT + "r rescan · z undo · f flavors · t tools"`. The `/ search` key is not in the hint.

### 2.6 Ace3 Profile Manager: `BlacklistScreen` (`tools/ace3_profile_manager/blacklist_screen.py:45`), tree `BlacklistTree` (line 39), `#blacklist-tree`
- **Nodes** (`_build` ~163): `("root",)`, `("flavor", folder, display)`, `("addon", folder, addon, missing)` leaves, and `("note",)` for "no Ace3 data".
- **Tickable:** addon leaves, and flavor and root as groups. State is `ticked: set[Key]` of casefolded (flavor, addon) pairs.
- **Select all / none:** `select_all` (245) ticks every name, ignoring what is visible. `select_none` (252) clears. There is a `#select-none` button but no Select all button.
- **Left pane:** `Static #explain` and `#actions` (Save, Select none, Cancel), then `NavHint`. `first_filter` is `#save`.
- **Keys** (57-66): `space a n escape left right x c up down`, plus `s u`.
- **Hint** (line 30): `review_hint() + "a all · n none · " + TREE_HINT + "Esc cancel"`
- **Search or filter:** none.
- This screen is not in the look-and-feel `TOOLS` loop.

### 2.7 Popup detail trees
`ConfirmScreen` and `InfoScreen` use `detail_tree`. They are read-only and have no ticks. Current callers that use groups:
- Ace3 "Remove leftover characters?" (`review_screen.py:1060`)
- Ace3 "Notes" InfoScreen (941)

The popup keys are `y n escape x c up down` (Confirm) and `escape x c up down` (Info). Here `n` already means No.

## 3. Key availability for filter, select all and select none

All letters in use on tree screens:

| Screen | Letters used |
|---|---|
| WTF | a c f n q r t w x y z, plus 1-4 |
| Shots | a c f n o q r t x y z |
| IB review | a b c e f n q r t x y z |
| Restore | b c o x |
| Ace review | a b c d e f k m n o p q r t u v w x y z D E, plus `/` and Backspace |
| Blacklist | a c n x |
| App (global) | s u |

- **Free on every tree screen:** g h i j l, any other uppercase letter except D and E, `/` (used only by Ace3, and there it already means focus search), and `ctrl+f`.
- **Natural choice:** keep `a` for select all and `n` for select none. They are already bound with the same meaning on all 5 tickable screens. Add `/` as the filter key on every tree screen, which extends the Ace3 convention.
- **Popup conflict:** `n` means No in `ConfirmScreen`. If filter or select keys are added to popups, `n` cannot be reused there.
- **Collapse key:** `c` stays collapse all on tree screens, so the new changelog key `c` on the tool menu does not clash, because the menu has no tree.
- **Typing letters in an Input:** the screen's `a` and `n` are non-priority bindings, so a focused Input takes the letter first. The Ace3 search box already works this way.
- **Space:** Space is priority-bound on every review screen. Each `action_toggle` needs an `isinstance(focused, Input)` passthrough. Ace3 has one; WTF, Shots, IB and Blacklist do not.
- **Esc:** today Esc on a review returns to the flavor picker. Ace3 overrides this so that Esc in the Input returns to the tree, and that override is needed on every screen that gets a filter.

## 4. Current select all / none behaviour versus "only nodes matching the filter"

| Screen | Select all | Select none | Already respects the filter? |
|---|---|---|---|
| WTF | clear `unchecked` | all files | no filter exists |
| Shots | `unchecked &= filed` | all selectable | no filter exists |
| IB review | clear | all flavors | no filter exists |
| Ace review | visible keys only | `clear()` (all) | half: only select all |
| Blacklist | all names | clear | no filter exists |
| Restore | — | — | not tickable |

The shared helper would need two things:
1. A way to collect the tick keys under the visible or matching nodes. Ace3's `_tick_keys(root)` is the model to follow.
2. Applying ticks or unticks to that set only.

Tick polarity differs between tools: WTF, Shots and IB store `unchecked`, while Ace review and Blacklist store `ticked`. Lazily loaded children (Shots day and filed files, IB links, warnings and backups, Restore groups) mean matching has to run on the model data, not on rendered nodes.

## 5. Where a filter input could go

**Option A: an Input row in the left pane `#filters`.** This is the Ace3 pattern.
- It satisfies "one focusable control per row" by itself.
- `TwoPaneFocus` already treats it as a left-pane control, so ←/→ and `_last_filter` work.
- `two_pane_css` already styles `#filters Input`.
- Cost: 1 row, or 2 with a section `Label`. The WTF, Shots and IB left panes are short (only Statics and buttons) and have room.
- The Ace3 left pane is already tight. It must fit the pending line (up to 3 rows), the summary (2 rows) and the whole hint at 120x30.
- The Restore pane is 46 wide and must still work at 80x24.

**Option B: above the tree in the right pane.**
- Only Ace3 has a container (`#tree-pane`) for this. WTF, Shots, IB, Restore and Blacklist yield the tree straight into `#body`, so each would need a wrapping `Vertical`, and `two_pane_css`'s `{tree} width:1fr` would need to change.
- `on_descendant_focus` keys on the `filters` ancestor, so an Input here would not be remembered by ← and needs its own focus rules.
- The Ace3 test requires the tree to keep at least 12 rows at BASE together with the guide and action bar; a filter row here would eat into that.

## 6. Look-and-feel and structure rules that constrain this

From `tests/test_look_and_feel.py` (TOOLS = the 4 review screens; the Blacklist and Restore screens are not covered):

**Left pane:**
- `#filters.outer_size.width == FILTERS_WIDTH` (50), and the width stays the same at LARGE.
- `#actions` holds exactly 4 Buttons in one row. The last starts with "Undo last " and has variant `warning`; the third is "Rescan".
- The buttons and NavHint sit inside the left pane at BASE, not clipped.
- `test_review_left_pane_has_one_control_per_row`: every focusable widget in `#filters`, apart from the `#actions` buttons, must be on its own row (unique `region.y`).

**Hints:**
- Hint text starts with `REVIEW_HINT` and contains `"r rescan · z undo · f flavors · t tools"`.
- It must contain `TREE_HINT + "r rescan"`, so nothing can go between `TREE_HINT` and `r rescan`. A new `/ filter` item has to sit before `x expand all` or after `t tools`.
- `TREE_HINT` must start with `"x expand all · c collapse all"`.
- For Ace3, the hint must end with `"f flavors · t tools"` (`test_ace_left_pane_hint_fits_…`).
- The hint wraps only between items, and its height equals its line count.

**Other review checks:**
- The summary text starts with `"Selected: "` or `"Nothing to"`.
- Esc on a review goes back to `FlavorScreen`. A filter Input must not break this when focus is on the tree.
- `x` and `c` expand and collapse the whole tree, and `c` must never start a run.

**Ace3-specific checks:**
- At BASE the action bar takes at most 3 rows, the guide at most 2, and the tree at least 12 (`assert_ace_tree_pane_rows`).
- At LARGE the action bar takes at most 2 rows.
- The headings are exactly `["View","Show"]` first, and the checkbox labels are exactly the 6 listed (`test_ace_left_pane_has_view_and_show_headings`). An Input does not change this, but a new checkbox would.
- `#pending` and the NavHint stay inside the left pane with every kind of pending change and with scan warnings.

**Footer:**
- `test_footer_shows_every_key_at_base`: every footer key with `show=True` must render whole at 120 columns. New bindings should be `show=False` and documented in the hint instead.

**Sizes:**
- At LARGE the tree grows while the left pane keeps its width.
- `test_tiny_terminal_still_works`: at 80x24, Tab must reach every focusable control on the settings, review, confirm and result screens.

From `tests/test_structure.py` and `CLAUDE.md`: a tool never imports another tool, so a shared filter widget or mixin must live in `wowtools/ui/`. `core/*` and tool logic modules never import textual. Every module needs `from __future__ import annotations`, and import order is enforced. Every new log event (for example `ui.selection` with `control="filter"`) must be registered in `core/events.py` or the tool's `events.py`, and `docs/events.md` regenerated afterwards.

Existing events: `ui.selection` (`control=select_all/select_none/...`) and `ui.item_toggled` are already used for ticks.

## Open questions / decisions

1. **Key choices.** Use `/` for "focus filter" everywhere, as Ace3 already does, and keep `a`/`n` for select all/none? Or should "select all/none within filter" get new keys? `a`/`n` are already consistent on every tickable screen.
2. **Select none semantics.** Should Ace3's `n` change to untick only the matching or visible nodes? Today it clears everything. The same question applies to WTF, Shots, IB and Blacklist once they have a filter: should select all and none touch hidden ticks at all, and what happens to hidden ticks when the filter is cleared? They would be kept but not visible.
3. **What the filter matches.** Leaf text only (file, addon, profile, character), or any node label (account, flavor, owner, date)? Does a match on a group show the whole group with all its children? Plain case-insensitive substring like Ace3 `Filters.matches`, or glob/regex?
4. **Lazily loaded nodes.** Should the filter search inside Shots day and filed files and IB links, warnings and backups, which do not exist until expanded, and expand the matching branches automatically as the Ace3 search does?
5. **Interface Backup review.** Only flavors can be ticked there, and there are at most about 5. Is a filter wanted on this screen (it would narrow only flavors, or the read-only backups and links)? Should select all/none here simply keep working as they do?
6. **Restore screen.** The tree cannot be ticked. Should it get a read-only filter, or be left out?
7. **Popup detail trees** (`ConfirmScreen`/`InfoScreen`). In scope or not? `n` means No there.
8. **Placement.** Use a left-pane Input row (the Ace3 pattern, which fits `TwoPaneFocus` and the one-control-per-row test) or a box above the tree? Should the Ace3 left pane, which is already tight at 120x30, keep its current `#search` as the shared filter rather than add another row?
9. **Ace3 search versus the new filter.** Should Ace3's existing `Filters.search` and `#search` become the shared component, with its placeholder and its "expand all while searching, restore after" behaviour as the standard for every tool?
10. **Esc behaviour.** Esc in the filter Input returns to the tree (as in Ace3). Should Esc also clear a non-empty filter before leaving the screen, or should it go straight back to the flavor picker as today?
11. **Footer and hint.** Should the filter key show in the footer (it may not fit at 120 columns on Ace3, see `test_footer_shows_every_key_at_base`) or only in the NavHint? Where should `/ filter` go in the hint? It cannot sit between `TREE_HINT` and `r rescan`.
12. **WTF criteria.** The criteria checkboxes and max age already narrow the WTF tree by rebuilding the proposal. Is the new text filter on top of them, and does select all apply to the criteria result and the text filter together?
13. **Blacklist screen.** It has a "Select none" button but no "Select all" button. Should every tree screen get Select all / Select none buttons for consistency? The review screens' `#actions` must keep exactly 4 buttons (look-and-feel test), so such buttons would need a separate row or the test would have to change.