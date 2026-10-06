"""The Saved Variables Browser's help screen text (spec D18), shown with h on any of its screens. Keep it to the core
functions; docs/sv-browser.md has the rest. The full text comes with the M3 screens (plan T3.4)."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/sv-browser.md"

HELP = f"""\
**USE AT YOUR OWN RISK.** This tool edits addon SavedVariables directly. It knows nothing about what an addon
expects; a wrong value can break an addon or lose its settings. Backups and Undo are made, but you are responsible
for what you change. **Close WoW first**: WoW rewrites every SavedVariables file when you log out.

The **Saved Variables Browser** shows every SavedVariables file of your WoW folder (every game version, account,
account-wide and per character) as a tree you can browse down to single values, and lets you change them offline:
edit a value, rename a key, delete a key, or find and replace values in bulk.

## Step by step

1. **Pick a game version**, or **All flavors**.
2. Read the warning: **I understand** goes on, **Back** returns to the game versions. It is asked each time you open
   the tool from the menu.
3. The **review** lists every SavedVariables file: game version, account, **Account-wide** or realm and character,
   then the file and its size. Nothing is read until you open a file; opening a file shows its SavedVariables, and
   opening a table shows its keys (a table with more than 500 shows the first 500 and how many more). A file that is
   not readable Lua shows in red and is never changed.
4. The buttons under the tree act on the highlighted key: **Edit value** (a string, number or boolean),
   **Rename key**, **Delete key**, and **View** switches between browsing and the search results. In the left pane:
   **Search** (find and replace in bulk), **Apply** writes what is staged, **Dry run** checks it without writing,
   **Rescan** reads the files again and **Undo last change** puts back the last Apply.

This build of the tool browses only: editing, search and the runs come in the next build.

## Keys

`/` filters what has been opened, `x` opens everything down to the files and `c` closes it all, `f` or `Esc` picks
another game version, `t` goes back to the tool menu, `s` opens the settings, `q` quits.

## Settings (`s`)

- **Backup folder**: where the zips go (`snapshots` for the whole `WTF` folder, `edited` for each changed file as it
  was). Empty means `<WoW folder>\\wow-tools\\sv-browser`. How many are kept is a shared setting.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
