"""The Saved Variables Browser's help screen text (spec D18), shown with h on any of its screens. Keep it to the core
functions; docs/sv-browser.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/sv-browser.md"

HELP = f"""\
**USE AT YOUR OWN RISK.** This tool edits addon SavedVariables directly. It knows nothing about what an addon
expects; a wrong value can break an addon or lose its settings. Backups and Undo are made, but you are responsible
for what you change. **Close WoW first**: WoW rewrites every SavedVariables file when you log out, and Apply and
Undo refuse while it runs.

The **Saved Variables Browser** shows every SavedVariables file of your WoW folder (every game version, account,
account-wide and per character) as a tree you can browse down to single values, and lets you change them offline:
edit a value, rename a key, delete a key, or find values and edit them in bulk.

## Step by step

1. **Pick a game version**, or **All flavors**.
2. Read the warning: **I understand** goes on, **Back** returns to the game versions. It is asked each time you open
   the tool from the menu.
3. The **review** lists every SavedVariables file: game version, account, **Account-wide** or realm and character,
   then the file and its size. Nothing is read until you open a file; opening a file shows its SavedVariables, and
   opening a table shows its keys (a table with more than 500 shows the first 500 and how many more). A file that is
   not readable Lua shows in red and is never changed.
4. **Stage** changes with the buttons under the tree, or **Search** and edit the results in bulk. Nothing is
   written yet: a staged key shows its new value (✎), its new name (→) or ✗ deleted, and the left pane counts what
   is staged.
5. **Dry run** (`y`) checks everything without writing. **Apply** (`w`), read the summary and the warning, press
   **Yes**. The **results** list every file.

## Under the tree (the highlighted key; in the results, the ticked results)

| Button | Key | Does |
|---|---|---|
| **Edit value** | `e` | Sets a string, number or boolean (the type may change) |
| **Rename key** | `k` | Renames the key; `[5]` or `[true]` makes a number or boolean key |
| **Delete key** | `d` | Deletes the key, a whole table with it; an array entry moves the entries after it down (browsing only) |
| **Unstage** | `Backspace` | Drops what is staged on the key |
| **View** | `v` | Switches between browsing and the search results |

A top-level variable can only have its value edited, and an array entry can't be renamed. A rename to a key the
table already has is refused.

## Left pane

| Button | Key | Does |
|---|---|---|
| **Search** | `S` | Finds values, to edit in bulk (below) |
| **Apply** | `w` | Writes what is staged, after backing everything up (asks first) |
| **Dry run** | `y` | Checks it all, writes nothing; **Back to review** (`Esc`) keeps it staged |
| **Rescan** | `r` | Reads the files again (drops what is staged; asks first) |
| **Undo last change** | `z` | Puts back every file the last Apply changed |

## Search and bulk edits

**Search** finds values in every file in scope, by **key** (Exact or Contains), by **value** (Whole value, or
Contains for text inside strings), or both (a hit then matches both), with **Match case** off by default. Numbers and
booleans match by their written text, as a whole value only; a key whose value is a table is never a hit. Narrow it
to one game version, account, character (or **Account-wide only**) or addon file. **Find** searches; each hit shows
as `path = value` in the **Results** view (game version, account, owner, file), all ticked: `Space` ticks one or a
group, `a` and `n` tick or untick what the filter shows. The results stop at 10,000 hits (narrow the search for
more).

In the results, **Edit value** and **Rename key** act on every ticked result (or the highlighted one when none is
ticked): one popup ("Edit 37 values"), then one staged edit per result, marked as in browsing. After a value
**Contains** search, Edit value can **Replace only the matched text** (every match in each string) or set the
**Whole value**. A result that can't take the edit is left out, and a notice says how many and why: it already has
a staged edit, it is inside a key staged for delete, or (rename) it is a top-level variable, an array entry or a
key its table already has. Ticks only choose what to edit: **Apply** writes what is staged. A new search replaces
the results; what is staged stays.

## Safety

- Before writing, Apply checks that no file changed since it was read and no program has one open, zips your
  **whole `WTF` folder** and every file it changes, writes only the bytes that change, then reads each file back and
  checks it. If anything fails, the files it wrote are put back.
- Every Apply has a **journal**. **Undo last change** puts the files back, and leaves alone a file saved again
  since (by WoW).
- If an Apply was cut short (a crash, a power cut), the next scan offers **Put the originals back** or **Leave as
  is**.
- The result shows the backup folder, the `WTF` backup, the zip of the original files and the journal.

## Keys

`/` reaches the filter box: type, then **Filter** or `Enter` filters what has been opened (in the results: every
hit), `x` opens everything down to the files and `c` closes it all, `←` `→` switch panes, `Tab` or `↓` on the last
line reach the buttons under the tree. `f` or `Esc` picks another game version, `t` goes back to the tool menu, `s`
opens the settings, `q` quits (leaving with something staged asks first). On the results: **Rescan**
(`r`), **Other flavor** (`f`), **Tools** (`t`), **Quit** (`q`).

## Settings (`s`)

- **Backup folder**: where the zips go (`snapshots` for the whole `WTF` folder, `edited` for each changed file as it
  was). Empty means `<WoW folder>\\wow-tools\\sv-browser`. How many are kept is a shared setting.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
