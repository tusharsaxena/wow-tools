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
   **Rename key** (`[5]` or `[true]` makes a number or boolean key), **Delete key** (a whole table goes with its
   key; deleting an array entry moves the entries after it down), **Unstage** drops what is staged on the key, and
   **View** switches between browsing and the search results. Nothing is written yet: a staged key shows its new
   value (✎), its new name (→) or ✗ deleted, and the left pane counts what is staged.
5. In the left pane: **Search** (find and replace in bulk), **Apply** writes what is staged, **Dry run** checks it
   without writing, **Rescan** reads the files again and **Undo last change** puts back the last Apply. Leaving or
   rescanning with something staged asks first.

## Search and replace (`S`)

**Search** finds values in every file in scope, by **key** (Exact or Contains), by **value** (Whole value, or
Contains for text inside strings), or both (a hit then matches both), with **Match case** off by default. Narrow it
to one game version, account, character (or **Account-wide only**) or addon file. **Replace with** a string, a
number or a boolean (Contains puts the new text in place of the found text), or **Find only**. **Find** checks what
you typed and searches; each hit shows as `path = old → new` in the **Results** view (flavor, account, owner, file),
all ticked: `Space` ticks one or a group, `a` and `n` tick or untick what the filter shows. **View** switches back
to browsing. The results stop at 10,000 hits (narrow the search for more). A ticked result on a key with a staged
edit is left out when you apply: the staged edit wins. A new search replaces the results (it asks first when some
are ticked).

Apply, Dry run and Undo come in the next build of the tool.

## Keys

`/` filters what has been opened, `x` opens everything down to the files and `c` closes it all, `f` or `Esc` picks
another game version, `t` goes back to the tool menu, `s` opens the settings, `q` quits.

## Settings (`s`)

- **Backup folder**: where the zips go (`snapshots` for the whole `WTF` folder, `edited` for each changed file as it
  was). Empty means `<WoW folder>\\wow-tools\\sv-browser`. How many are kept is a shared setting.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
