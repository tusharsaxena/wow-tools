# Buttons, colours and confirm dialogs: inventory and proposals

Read-only analysis (Textual 8.2.8, vendored). Paths are relative to the repo root.

## 1. Existing colour scheme

**Theme.** `wowtools/ui/theme.py:6-18` defines `KA0S_THEME`, which is registered in `Ka0sApp.on_mount` (`ui/base.py:93-95`):

| Token | Hex |
|---|---|
| primary | #2F8CFF |
| secondary | #8A96A8 |
| accent | #5CC8FF |
| foreground | #D3DAE3 |
| background | #05080F |
| surface | #0B1526 |
| panel | #10213D |
| success | #4CC38A |
| warning | #E8B04B |
| error | #E5534B |

**Button colour scheme already in place.** `wowtools/ui/widgets.py:21-28` has `ACTION_VARIANTS`, and `action_button(label, action, **kw)` at `widgets.py:31-33` returns `Button(label, variant=ACTION_VARIANTS[action])`.

| Kind | Textual variant | Colour |
|---|---|---|
| delete | error | red |
| apply | success | green |
| simulate | primary | blue |
| revert | warning | amber |
| confirm | primary | blue |
| neutral | default | grey |

- Every button in the app is built through `action_button`. No direct `Button(...)` calls exist outside `widgets.py:33`.
- Textual only has 5 button variants (`default`, `primary`, `success`, `warning`, `error`). So `simulate` and `confirm` look the same today: both are blue `primary`.
- There is no global Button CSS. `Ka0sApp.CSS` (`base.py:83`) only hides the command palette's footer key. All `.tcss` files are under `vendor/`; the app has none of its own. Per-screen Button CSS only sets spacing:
  - `margin-left: 2`: `dialogs.py:258`, `popups.py:63`, `review_screen.py(ace):113`, `wtf review_screen.py:69`, `suite_app.py:41`, `base.py:30`
  - `margin-right`: `dialogs.py:61`, `79`, `96`; `setup_screen.py:34`; `widgets.py:127` (WrapButtonRow, compact)

**Other hard-coded colours** (Rich styles, not tokens):

| Constant | Location | Colour |
|---|---|---|
| `ALERT_STYLE` | `dialogs.py:22` | "bold #E5534B" |
| `ACCENT` | `dialogs.py:23` | "bold #5CC8FF" |
| `BUSY_STYLE` | `dialogs.py:24` | "bold #E8B04B" |
| `LIST_NAME_STYLE` | `widgets.py:17` | gold #F2C14E |
| `LIST_CURSOR_BACKGROUND` | `widgets.py:18` | #1C4E8F |

WTF Cleaner's `CRITERION_COLORS` (in its report module) uses red #E5534B, orange #F08C3A, yellow #E8C547 and purple #B07CFF for its criteria. Reusing those colours for buttons would clash with their meaning on that screen.

**Popup borders.**
- `$accent`: ConfirmScreen, InfoScreen, ProgressScreen, Ace3 popups, UpdateScreen
- `$warning`: LockScreen (`suite_app.py:38`), WTF RecoveryScreen (`wtf_cleaner/review_screen.py:66`), ProfileRecoveryScreen (`ace3_profile_manager/review_screen.py:110`)

**Docs that describe the scheme:**
- `docs/architecture.md:594` (widgets row)
- `docs/architecture.md:528` (Ace3 Apply uses the delete variant)
- `docs/adding-a-tool.md:44-51`

## 2. Inventory of every button

Columns: Location | Label | id | Current kind → variant | What it really does.

### Shared and suite

| Location | Label | id | Current | Does |
|---|---|---|---|---|
| ui/dialogs.py:282 ConfirmScreen | Yes (y) | yes | confirm → primary | accepts whatever is being confirmed (delete, restore, backup…) |
| ui/dialogs.py:283 | No (n) | no | neutral | cancel |
| ui/dialogs.py:324 InfoScreen | OK | ok | confirm | acknowledge |
| ui/suite_app.py:67 LockScreen | Override and continue (o) | lock-override | revert → warning | overrides a safeguard |
| ui/suite_app.py:68 | Quit (q) | lock-quit | neutral | quit app |
| ui/base.py:44 UpdateScreen | Update now | update-yes | confirm | downloads and overwrites the install |
| ui/base.py:45 | Later | update-no | neutral | cancel |
| ui/setup_screen.py:63-64 | Save / Cancel | save / cancel | confirm / neutral | write the config / back out |

### WTF Cleaner

| Location | Label | id | Current | Does |
|---|---|---|---|---|
| wtf_cleaner/app.py:65-66 (settings) | Save / Cancel | save / cancel | confirm / neutral | config |
| wtf_cleaner/review_screen.py:168 | Clean | btn-clean | delete → error | backs up, then deletes files |
| :169 | Dry run | btn-dry | simulate → primary | simulate |
| :170 | Rescan | btn-rescan | neutral | refresh |
| :171 | Undo last clean | btn-undo | revert → warning | restore from journal |
| :83 RecoveryScreen | Dismiss (keep the backup) | recovery-dismiss | neutral | clears the marker |
| :84 | Remind me next time | recovery-remind | confirm | no-op; this button has focus first (:87) |
| wtf_cleaner/result_screen.py:154-157 | Rescan (r) / Other flavor (f) / Tools (t) / Quit (q) | review / flavors / tools / quit | neutral | navigation |

### Screenshot Organizer

| Location | Label | id | Current | Does |
|---|---|---|---|---|
| screenshot_organizer/app.py:55-56 | Save / Cancel | save / cancel | confirm / neutral | config |
| screenshot_organizer/review_screen.py:162 | Organize | btn-organize | apply → success | moves or copies files |
| :163 | Dry run | btn-dry | simulate | simulate |
| :164 | Rescan | btn-rescan | neutral | refresh |
| :165 | Undo last run | btn-undo | revert | put back |
| :73-76 (result) | Rescan (r) / Other flavor (f) / Tools (t) / Quit (q) | review / flavors / tools / quit | neutral | navigation |

### Interface Backup

| Location | Label | id | Current | Does |
|---|---|---|---|---|
| interface_backup/app.py:61-62 | Save / Cancel | save / cancel | confirm / neutral | config |
| interface_backup/review_screen.py:231 | Back up | btn-backup | apply → success | creates a zip; changes no files |
| :232 | Restore | btn-restore | neutral | opens the restore screen |
| :233 | Rescan | btn-rescan | neutral | refresh |
| :234 | Undo last restore | btn-undo | revert | put back |
| :130-134 (backup result) | Rescan (r) / Restore (e) / Other flavor (f) / Tools (t) / Quit (q) | review / restore / flavors / tools / quit | neutral | navigation |
| interface_backup/restore_screen.py:110 | Restore | btn-restore | apply → success | overwrites Interface/WTF (after a safety backup) |
| :111 | Back | btn-back | neutral | navigation |
| :362 (restore result, shown only if `can_undo`) | Undo (z) | undo | revert | put back |
| :363-366 | Rescan (r) / Other flavor (f) / Tools (t) / Quit (q) | review / flavors / tools / quit | neutral | navigation |

### Ace3 Profile Manager

| Location | Label | id | Current | Does |
|---|---|---|---|---|
| ace3_profile_manager/app.py:63 (settings) | Edit blacklist… | edit-blacklist | neutral | opens a screen |
| :66-67 | Save / Cancel | save / cancel | confirm / neutral | config |
| blacklist_screen.py:86 | Save | save | apply → success | writes the blacklist config (other Save buttons are `confirm`) |
| :87 | Select none | select-none | neutral | clears ticks |
| :88 | Cancel | cancel | neutral | cancel |
| review_screen.py:285 (left pane) | Apply | btn-apply | delete → error | writes all staged changes, which may include deletes |
| :286 | Dry run | btn-dry-run | simulate | simulate |
| :287 | Rescan | btn-rescan | neutral | refresh |
| :288 | Undo last change | btn-undo | revert | put back |
| :65-76 `TREE_ACTIONS`, rendered :296-298 as compact buttons in `WrapButtonRow#tree-actions` | Assign (p) | act-assign | apply | stages (writes nothing until Apply) |
| | Rename (e) | act-rename | apply | stages |
| | Copy (k) | act-copy | apply | stages |
| | Everyone → Default (E) | act-everyone-default | apply | stages |
| | Delete (d) | act-delete | delete | stages a delete |
| | Only Default (D) | act-keep-default | delete | stages a delete |
| | Leftovers (o) | act-leftovers | delete | stages a delete |
| | Blacklist… | act-blacklist | neutral | opens a screen |
| | More… (m) | act-more | neutral | opens a menu |
| | Discard (⌫) | act-discard | neutral | drops staged changes; behind a confirm |
| review_screen.py:138 ProfileRecoveryScreen | Leave as is | leave | neutral | dismiss |
| :139 | Put the originals back | put_back | revert | restores from zip; focused first (:140-141) |
| popups.py:100-101 TargetScreen, :160-161 NameScreen | OK / Cancel | ok / cancel | confirm / neutral | confirm a choice |
| result_screen.py:55-60 | Rescan (r) / Back to review (Esc) / Other flavor (f) / Tools (t) / Quit (q) | rescan / back / flavors / tools / quit | Back is confirm (shown only if `self.back`); the rest neutral | navigation |

Non-button pickers:
- `ToolMenuScreen` (`suite_app.py:89-123`) uses an `OptionList#tools` and has no buttons. Its bindings are `q,escape` quit and the app-level `s` settings (`suite_app.py:128`). Its hint is at `suite_app.py:108`.
- `ActionsScreen` (`popups.py:193`) is also an OptionList.
- `flavor_screen.py` and `account_screen.py` have no buttons.

### Inconsistencies today

- Ace3 left-pane **Apply** is red (`delete`), while Organize, Back up and Restore are green (`apply`). WTF **Clean** is red.
- The Ace3 tree-action bar colours *staging* actions green or red even though they write nothing.
- Blacklist **Save** is `apply` (green); every other Save is `confirm` (blue).
- **Back up** (only creates files) and **Restore** (overwrites files) share green.
- `confirm` and `simulate` are both blue.
- ConfirmScreen **Yes** is always blue, whatever is being confirmed.

## 3. Proposed set of action kinds

Textual has only 5 variants, so per-kind colours need custom classes. The suggested way:
- Make `action_button` add a class (for example `-act-<kind>`) next to the closest variant, so the existing `.variant` assertions keep working.
- Define the colours once, as app-level CSS in `Ka0sApp.CSS` or `DEFAULT_CSS` on a `Button` subclass in `widgets.py`, using theme tokens or new tokens through `Theme(variables={...})`.

| Kind | Meaning | Colour | Buttons |
|---|---|---|---|
| destructive | permanently deletes or overwrites user data | red $error | Clean; Ace3 Apply (if staged deletes count as destructive); Yes on the Clean, Apply and Restore confirms |
| write | changes files, can be undone | amber/orange (new token, e.g. #F08C3A) | Organize; Restore (restore screen); Ace3 Apply (alternative to red); Update now |
| stage | queues an edit, writes nothing yet | light/outline version of write or destructive | Assign, Rename, Copy, Everyone→Default (write-tint); Delete, Only Default, Leftovers (destructive-tint) |
| create-safe | only adds files (backups, snapshots) | green $success | Back up |
| revert | puts a change back from journal or zip | purple (e.g. #B07CFF; clashes with WTF "stray copies") or keep amber | Undo last clean/run/restore/change, Undo (z), Put the originals back |
| override | bypasses a safeguard | amber $warning | Override and continue |
| simulate | shows what would happen, changes nothing | cyan $accent | Dry run (×3) |
| confirm/primary | expected next step, nothing risky | blue $primary | Save (all, including blacklist Save), OK (Info, Target, Name), Remind me next time, Back to review |
| navigate | moves between screens or refreshes | default grey | Rescan, Rescan (r), Restore (e) / Restore (opens screen), Other flavor, Tools, Back, Blacklist…, Edit blacklist…, More…, Select none |
| cancel | backs out or declines | muted/dim grey (`$text-muted` on `$panel`) | Cancel, No, Later, Quit, Dismiss, Leave as is, Discard (⌫) |

Proposed `ConfirmScreen` change: an `action=` (kind) argument so **Yes** takes the colour of the action it confirms. For example, Clean's confirm gets a red Yes and Back up gets a green one.

Tests that pin current variants and would need updating:
- `test_look_and_feel.py:89` (last left-pane button is "warning")
- `test_ace_app.py:999` (`["success"]*4 + ["error"]*3 + ["default"]*3`)
- `test_wtf_app.py:430-432` (error, primary, default)
- `test_wtf_app.py:1609` (Undo warning)
- `test_interface_backup_app.py:282-287`, `:773`, `:1427-1428` (through `ACTION_VARIANTS`)
- `test_screenshot_organizer_app.py:499-507`

## 4. ConfirmScreen and every yes/no dialog

**`ConfirmScreen`** is at `ui/dialogs.py:247-293`.
- Signature: `(title, body, alerts=(), *, default_yes=False, groups=None)`.
- Bindings (`:260-261`):
  - `y` answers True
  - `n` and `escape` answer False
  - `NAV_BINDINGS`: ↑/↓ move focus
  - `TREE_BINDINGS`: x and c
- Buttons are in a `ButtonRow#confirm-buttons`, right-aligned, in the order **Yes (y), No (n)** (`:281-283`).
- Focus on mount (`:286-287`): `#yes` if `default_yes`, else `#no`. The default is `default_yes=False`.
- Hint (`:284`): "←→ choose · Enter/Space press · y yes · n/Esc no".
- Enter or Space presses the focused button. `ButtonRow.action_press_focused` at `widgets.py:86` handles Space.

### ConfirmScreen call sites and their current defaults

| Call site | Confirms | Default focus |
|---|---|---|
| wtf_cleaner/review_screen.py:646 | Clean "Back up and delete these files?" / "Simulate this clean?" | `default_yes=dry_run`: No for a real clean, Yes for a dry run |
| wtf_cleaner/review_screen.py:784 | Undo clean | No (explicit) |
| screenshot_organizer/review_screen.py:512 | Organize / dry run | `default_yes=dry_run` |
| screenshot_organizer/review_screen.py:604 | Undo run | No |
| interface_backup/review_screen.py:652 | Back up | **Yes** (explicit) |
| interface_backup/review_screen.py:785 | Restore | No |
| interface_backup/review_screen.py:850 | Undo restore | No |
| ace3_profile_manager/review_screen.py:371 | Rescan, discarding pending changes | No (implicit) |
| ace3_profile_manager/review_screen.py:1060 | Remove leftover characters (with groups) | No |
| ace3_profile_manager/review_screen.py:1134 | Discard pending changes | No |
| ace3_profile_manager/review_screen.py:1240 | Apply / dry run | `default_yes=dry_run` |
| ace3_profile_manager/review_screen.py:1357 | Undo last change | No |
| ace3_profile_manager/review_screen.py:1485 | Leave the review (f/t/q) and discard pending changes | No |

### Other two-choice dialogs

| Dialog | Location | Order | First focus | Keys |
|---|---|---|---|---|
| LockScreen | suite_app.py:33-78 | Override, Quit | Override if the lock is stale, else Quit (`:71-72`) | `o` override; `q`/Esc quit (`:43`) |
| UpdateScreen | base.py:23-55 | Update now, Later | Update now (`:48-49`) | only Esc = later (`:32`); no y/n |
| WTF RecoveryScreen | wtf_cleaner/review_screen.py:60-93 | Dismiss, Remind | Remind (`:87`) | no bindings at all, not even Esc |
| ProfileRecoveryScreen | ace3_profile_manager/review_screen.py:103-145 | Leave as is, Put the originals back | Put back (`:140-141`) | Esc dismisses with None |
| TargetScreen / NameScreen | popups.py | OK, Cancel | the input field, not a button | Esc cancel |

Button order is not consistent across dialogs:
- Confirm, Update, Lock and the Ace3 popups put the positive button first (left).
- The two recovery screens put the passive button first.

### Tests and docs that pin "starts on No" (and would break under default Yes)

Tests:
- `test_wtf_app.py:669`, `:677` (`KeyboardNavigationTest`: the clean confirm starts on "no"; right/left moves)
- `test_wtf_app.py:692` (Space on the focused No cancels)
- `test_wtf_app.py:1628` (Undo starts on No)
- `test_wtf_app.py:714` (probe with `default_yes=True`; not affected)
- `test_ace_app.py:1278` (Leftovers confirm focus is `#no`; then `up up` goes No → Yes → tree, which depends on order and focus)
- `test_interface_backup_app.py:764-765`, `:780`, `:977` (`assertFalse(default_yes)`)
- `test_interface_backup_app.py:1085`, `:1176`, `:1484` (focus is `#no`)
- `test_interface_backup_app.py:451` (Back up starts on Yes)
- `test_suite_app.py:96` (lock starts on Quit), `:124` (Override when stale)
- `test_ui_base.py:362-366` (update starts on update-yes)

Docs:
- `docs/adding-a-tool.md:31`, `:46` ("start on No for anything that changes files")
- `docs/architecture.md:388`, `:561`, `:593`, `:633`, `:637-638`
- the per-tool docs

### Look-and-feel tests on buttons (`tests/test_look_and_feel.py`)

- `:77-100`: left-pane `#actions` has 4 buttons in one row, the last is "Undo last …" with the warning variant, the third is "Rescan", and all fit inside `FILTERS_WIDTH`.
- `:165-191`, `:274-285`: the Ace3 `#tree-actions` bar has 10 buttons, at most 3 rows at 120x30 and 2 at LARGE, and every label is drawn whole (`width >= len(label)+2`).
- `:316-342`: result screens: the first label is "Rescan (r)", the last three are Other flavor (f), Tools (t), Quit (q), and all sit in one row.
- `:463-492`: popup width at BASE and LARGE for ConfirmScreen, InfoScreen, ProgressScreen, TargetScreen, NameScreen and ActionsScreen.
- `:545-562`: on an 80x24 terminal, Tab reaches every focusable control, the ConfirmScreen included.

Adding new labels or widening the Ace3 bar has to keep these passing.

### Key notes for the other features in this run

- `c` is `collapse_all` in `TREE_BINDINGS` (`dialogs.py:44-47`) on every tree screen and in ConfirmScreen and InfoScreen. A main-menu `c` for the changelog does not clash, because ToolMenuScreen has no tree.
- On review screens, `a`, `n` and `y` already mean select all, select none and dry run:
  - wtf `review_screen.py:108-111`
  - screenshot_organizer `review_screen.py:121-124`
  - interface_backup `review_screen.py:175-176`
  - ace3 `review_screen.py:205-206`
  - ace3 `blacklist_screen.py:59-60`

  `y`/`n` are only bound inside the ConfirmScreen modal, so there is no conflict there.
- Ace3 binds `slash` to `focus_search` (`ace3_profile_manager/review_screen.py:221`) and already has a search `Input#search` (`:281`). That is the only existing tree filter.

## 5. Open questions / decisions

1. **Default Yes everywhere?** Default Yes on Clean, Ace3 Apply, Restore and the Undo confirms means one Enter deletes or overwrites. Choose between:
   - (a) Yes everywhere, accepting the risk because backups exist;
   - (b) Yes everywhere, but Yes is coloured red on destructive confirms;
   - (c) keep No for destructive confirms only.

   The current docs and about 12 tests encode "risky starts on No".
2. **Button order.** "no/yes scenario" could mean the order should become No, Yes (Yes on the right, as on Windows and macOS), or just that focus should start on Yes. The current order is Yes, No.
3. **Does default Yes reach the non-ConfirmScreen two-choice dialogs?**
   - LockScreen currently focuses Quit unless the lock is stale.
   - WTF RecoveryScreen: which is "yes", Remind or Dismiss?
   - ProfileRecoveryScreen already focuses Put back.
   - UpdateScreen already focuses Update now.
4. **Ace3 Apply.** Red (it can delete profiles), amber/write, or coloured by what is staged (red only when deletes are pending)?
5. **Staging actions** (Assign, Delete, …): full colours, or a lighter "staged" version, since they write nothing until Apply?
6. **Back up versus Restore.** Should Back up (only creates files) be green and Restore (overwrites files) amber or red? Today both are green.
7. **Revert colour.** Keep amber (the tests pin "warning") or move to a new colour such as purple? If amber goes to "write" and purple to "revert", the WTF criterion colours (orange and purple) carry other meanings on the same screen.
8. **Custom colours.** Is a custom CSS class per kind acceptable, keeping the 5 Textual variants for compatibility? Or should kinds be squeezed into the 5 variants, so "simulate" and "confirm" stay alike?
9. **Navigation buttons.** Should Rescan, Other flavor, Tools and Quit stay plain grey, or should Quit and Cancel get a separate muted "cancel" style?
10. **Discard (⌫).** Is it cancel-grey or destructive-tint? It drops staged edits behind a confirm.
11. **ConfirmScreen kind argument.** Should it take an `action=` kind so Yes matches the action's colour, with every call site updated?
12. **UpdateScreen keys.** Should it get `y`/`n` bindings for consistency? Today it only has Esc. Should RecoveryScreen get an Esc binding?