"""The Config Editor's help screen text, shown with h on any of its screens. Keep it to the core functions;
docs/config-editor.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/config-editor.md"

HELP = f"""\
The **Config Editor** shows the CVars (the game's settings) in `Config.wtf` and in every account's and character's
`config-cache.wtf`, with help for each, and lets you set, add, remove and reset them. **Close WoW first**: it
rewrites these files when you log out or exit, and Apply and Undo refuse while it runs.

## Step by step

1. **Pick a game version**, or **All flavors**.
2. The tree shows **Config.wtf** (this computer), each account's **Account config** and each character. Open one to
   see its CVars in columns: name, value, default, state and category. The state is `changed` when the value
   differs from the default, `default` when it matches (or isn't set), `unknown` when there is no default to compare
   with (you can still change it). A long value is cut with `…`: the help panel shows it whole.
3. Highlight a CVar: the **help panel** (under the tree, or beside it in a wide window) says what it does, its
   default, where the game keeps it, whether it syncs it and any recommendation.
4. Change what you like: nothing is written yet. Changed CVars are marked ✎.
5. **Dry run** checks everything without writing. **Apply** asks first, then writes every change in one go; the
   **results** list every file.

## The bar under the tree

| Button | Key | Does |
|---|---|---|
| **Set** | `e` | A new value for the highlighted CVar |
| **Add** | `N` | A CVar the file does not set yet (any name, known or not) |
| **Remove** | `d` | Takes the highlighted CVar's line out of the file |
| **Reset** | `R` | Back to the default: the line goes, so the game uses its default |
| **Recommend…** | `m` | Recommendations for the highlighted file, each with its reason and source: tick and stage them |

Set, Remove and Reset act on the highlighted CVar in every **ticked** file (Space on a file, a character, an account
or a realm ticks it), else in the highlighted CVar's own file; Add puts the CVar into every ticked file, else the
highlighted one. `Space` on a CVar that is `0` or `1` switches it. A CVar set in a file of another level than the
one the game keeps it in (an account CVar in a character's file) is allowed, with a warning.

## Left pane

The **filter box** searches the CVars' names and descriptions, and the files' names (type, then Enter or
**Filter**). **Show** narrows the list: a category, **Changed only** (set to something other than the default) and
**Show all known** (adds every CVar the knowledge base knows for that file's level, set or not).

| Button | Key | Does |
|---|---|---|
| **Apply** | `w` | Writes every staged change, after backing everything up (asks first) |
| **Dry run** | `y` | Checks it all, writes nothing; **Back to review** (`Esc`) keeps the changes |
| **Rescan** | `r` | Reads the files again (asks first when it would drop staged changes) |
| **Undo last change** | `z` | Puts back every file the last Apply changed and removes the ones it created |

## Keys

`Space` ticks or unticks the highlighted file or group (on a 0/1 CVar it switches it), `a` ticks every file shown,
`n` none. `/` goes to the filter box. `x` / `c` expand or collapse the whole tree. `f` or `Esc` goes back to the game
versions, `t` to the tool menu, `s` opens the settings, `q` quits; with staged changes each asks first. The results
screen has **Rescan** (`r`), **Other flavor** (`f`), **Tools** (`t`) and **Quit** (`q`); after a dry run, **Back
to review** (`Esc`). In Add and Set, **OK** stages and **Cancel** (`Esc`) drops it; in Recommend…, `Space` or
`Enter` ticks and **OK** stages the ticked ones.

## Settings (`s`)

- **Backup folder**: the zips go in its `config-editor` folder (`snapshots` for the whole `WTF` folder, `edited`
  for each changed file as it was). Empty means `<WoW folder>\\wow-tools`. How many are kept is a shared setting.
  **Save** keeps it, **Cancel** (`Esc`) drops it.

## Warnings

A file that can't be read is shown **read-only** and never written; the **Warnings** button (`!`) on the bottom
line lists those files and any folder that could not be read. **Back** (`Esc`) returns.

## Safety

Before anything is written, the whole WTF folder of each game version changed is backed up, then every file to be
changed is zipped. Lines you did not change keep their exact bytes. **Undo last change** (`z`) puts the files back
and removes the files the Apply created, each only if WoW has not changed it since. If the app stops half way, the
next scan offers to put the originals back.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
