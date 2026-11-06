"""The Config Copier's help screen text, shown with h on any of its screens. Keep it to the core functions;
docs/config-copier.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/config-copier.md"

HELP = f"""\
The **Config Copier** copies one character's client files to other characters of the same game version: its macros
(`macros-cache.txt`), enabled addons (`AddOns.txt`), chat windows (`chat-cache.txt`), CVars (`config-cache.wtf`)
and layout (`layout-local.txt`). **Close WoW first**: it rewrites these files when a character logs out, and Write
and Undo refuse while it runs.

## Step by step

1. **Pick a game version**, or **All flavors**.
2. **Pick the source**: the character to copy from (Enter, or **Choose**). **Back** returns to the game versions.
3. On the **review**, tick the **targets** in the tree. Each target opens to its five files: **new** (it has none),
   **replaced**, **unchanged** or **source has no file**. Untick a single file of a target to leave it alone, or
   untick a file in the left pane to leave it alone for every target. The source and other game versions'
   characters are greyed.
4. **Diff** shows what a replaced file loses and gets. **Dry run** checks everything without writing. **Write**
   asks first, then copies; the **results** list every file.

`config-cache.wtf` is **merged**, not copied: the target gets the source's settings exactly, but keeps its own
progress and bookkeeping CVars (tracked quests, talent loadouts, tutorials seen...). The diff marks those lines kept.
Copying macros onto a character that has macros may leave its action bar buttons pointing at the wrong macro: the
review marks those files ⚠ and the confirm lists them. WoW's own `cache.md5` and `.old` files are never touched.

## Left pane

| Button | Key | Does |
|---|---|---|
| **Write** | `w` | Copies the ticked files, after backing everything up (asks first) |
| **Dry run** | `y` | Checks it all, writes nothing; **Back to review** (`Esc`) keeps the ticks |
| **Rescan** | `r` | Reads the files again |
| **Undo last change** | `z` | Puts back every file the last copy replaced and removes the ones it created |

Under the source, **Change source** (`p`) goes back to the source picker for the same game versions; the new
source's review starts with nothing ticked. Under the tree, **Diff** (`d`) opens the diff of the highlighted replaced
file; until one is highlighted the line beside it says so.

## Keys

`Space` ticks or unticks the highlighted target or file, `a` ticks everything shown, `n` nothing. `/` goes to the
filter box: type, then Enter or **Filter** shows only the targets and files that match. `x` / `c` expand or
collapse the whole tree. `f` or `Esc` goes back to the game versions, `t` to the tool menu, `s` opens the settings,
`q` quits. The results screen has **Rescan** (`r`), **Other flavor** (`f`), **Tools** (`t`) and **Quit** (`q`); after
a dry run, **Back to review** (`Esc`). The diff screen opens side by side (inline in a window under 100 columns);
**View** (`v`) switches between side by side and inline, and the next diff opens in the view you picked. Its
**Back** (`Esc`) returns to the review.

## Settings (`s`)

- **Backup folder**: the zips go in its `config-copier` folder (`snapshots` for the whole `WTF` folder, `edited` for
  each replaced file as it was). Empty means `<WoW folder>\\wow-tools`. How many are kept is a shared setting.
  **Save** keeps it, **Cancel** (`Esc`) drops it.

## Warnings

A file or folder that could not be read is never copied: the **Warnings** button (`!`) on the bottom line lists
them. **Back** (`Esc`) returns to the review.

## Safety

Before anything is written, the whole WTF folder of that game version is backed up, then every file to be replaced
is zipped. **Undo last change** (`z`) puts the replaced files back and removes the files the copy created, each
only if WoW has not changed it since. If the app stops half way, the next scan offers to put the originals back.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
