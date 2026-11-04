"""The Macro Editor's help screen text, shown with h on any of its screens. Keep it to the core functions;
docs/macro-editor.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/macro-editor.md"

HELP = f"""\
The **Macro Editor** shows every macro of your accounts and characters (`macros-cache.txt`) and lets you edit,
create, delete, copy and paste them, between characters, accounts and game versions. **Close WoW first**: it
rewrites these files when a character logs out, and Apply and Undo refuse while it runs.

## Step by step

1. **Pick a game version**, or **All flavors**.
2. The tree shows each account's **Account macros** and each character, with the slots used (`12/30`,
   `30/30 FULL`); open one to see its macros: name, first line and length (`n/255`).
3. Change what you like: nothing is written yet. Changed macros are marked ✎, new ones +, deleted ones ✗.
4. **Dry run** checks everything without writing. **Apply** asks first, then writes every change in one go; the
   **results** list every file.

## The bar under the tree

| Button | Key | Does |
|---|---|---|
| **New** | `N` | A new macro in the highlighted character or Account macros |
| **Edit** | `e` | Edit the highlighted macro (it keeps its place on your action bars) |
| **Delete** | `d` | Delete the ticked macros, or the highlighted one: their action bar buttons go too |
| **Copy** | `k` | Take the ticked macros (or the highlighted one) to paste somewhere else |
| **Paste…** | `p` | Paste them into the ticked characters and Account macros, after a review |
| **Replace text…** | `R` | Find and replace in the bodies of the ticked macros, with a preview |

**Paste…** lists every macro whose name the target already has: **Skip** it, **Rename** it (`Name 2`) or
**Overwrite** the target's (which keeps the target's place on its action bars), one by one or with **Apply to all**.
A full set refuses what does not fit. Pasting into another game version warns that the macro may not work there and
names the commands and conditions that version may not know.

## Left pane

The **filter box** searches the macros' **Names** and/or **Bodies** (type, then Enter or **Filter**). With **Only
matching macros** unticked every macro stays in the tree and the matches are underlined.

| Button | Key | Does |
|---|---|---|
| **Apply** | `w` | Writes every staged change, after backing everything up (asks first) |
| **Dry run** | `y` | Checks it all, writes nothing; **Back to review** (`Esc`) keeps the changes |
| **Rescan** | `r` | Reads the files again (asks first when it would drop staged changes) |
| **Undo last change** | `z` | Puts back every file the last Apply changed and removes the ones it created |

## Keys

`Space` ticks or unticks the highlighted macro or set (a character ticks its macros too), `a` ticks everything
shown, `n` nothing. `/` goes to the filter box. `x` / `c` expand or collapse the whole tree. `f` or `Esc` goes back
to the game versions, `t` to the tool menu, `s` opens the settings, `q` quits; with staged changes each asks first.
The results screen has **Rescan** (`r`), **Other flavor** (`f`), **Tools** (`t`) and **Quit** (`q`); after a dry
run, **Back to review** (`Esc`). In the paste review, **Paste** pastes and **Cancel** (`Esc`) drops it; Replace
text…'s **Replace** stages the replacements.

## The edit screen (New, Edit)

The name (up to 16 characters), the icon, the body with its `n / 255` meter and, beside it, help on what is under the
cursor. Typing a command, a condition or a `@unit` lists suggestions: `↑`/`↓` choose, `Tab` or `Enter` take one,
`Esc` hides them (after a word that is already complete, `Enter` is a new line).

| Button | Key | Does |
|---|---|---|
| **Save** | `Ctrl+S` | Stages the macro (off above 255 characters); **Cancel** (`Esc`) drops it |
| **Builder…** | `Ctrl+B` | Builds the `[...]` block under the cursor, or a new one, from lists and ticks; **OK** writes it |
| **Optimize…** | `Ctrl+O` | Shortens the macro and says why; **OK** takes the rewrites |
| **Template…** | `Ctrl+T` | A ready-made macro: pick one, fill its blanks, **Insert** puts it in |
| **Reference** | `F1` | Every command, condition and unit this game version knows; **Back** (`Esc`) returns |

## Settings (`s`)

- **Backup folder**: the zips go in its `macro-editor` folder (`snapshots` for the whole `WTF` folder, `edited` for
  each changed file as it was). Empty means `<WoW folder>\\wow-tools`. How many are kept is a shared setting.
  **Save** keeps it, **Cancel** (`Esc`) drops it.

## Warnings

A macro file in a layout the editor does not know is shown **read-only** and never written; the **Warnings** button
(`!`) on the bottom line lists those files and any folder that could not be read. **Back** (`Esc`) returns.

## Safety

Before anything is written, the whole WTF folder of each game version changed is backed up, then every file to be
changed is zipped. Macros you did not change keep their exact bytes. **Undo last change** (`z`) puts the files back
and removes the files the Apply created, each only if WoW has not changed it since. If the app stops half way, the
next scan offers to put the originals back.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
