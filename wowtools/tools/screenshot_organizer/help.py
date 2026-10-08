"""The Screenshot Organizer's help screen text (spec D18), shown with h on any of its screens. Keep it to the core
functions; docs/screenshot-organizer.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/screenshot-organizer.md"

HELP = f"""\
Sorts the screenshots in each game version's `Screenshots` folder into **year / month / day** folders, either right
where they are or into an archive folder you choose (a photos drive, say). File names are never changed, and the
date comes from the name WoW gives each screenshot (`WoWScrnShot_MMDDYY_HHMMSS.jpg`, or .png / .tga).

## Step by step

1. **Pick a game version**, or **All flavors**. Each row counts the screenshots waiting to be sorted.
2. The **review** lists them: game version → year → month → day → screenshots. Everything starts ticked ("sort
   this"): untick a day, a month or a version to leave it alone.
3. **Dry run** (`y`) shows what would happen without moving anything.
4. Press **Organize** (`o`), read the summary, and press **Yes**.
5. The **results** list every screenshot and where it went.

## Buttons and keys

| Button | Key | Does |
|---|---|---|
| **Organize** | `o` | Moves (or copies) the ticked screenshots into dated folders (asks first) |
| **Dry run** | `y` | Every check, nothing moved: "Would move", "Would copy" |
| **Rescan** | `r` | Scans again (after changing settings, say) |
| **Undo last run** | `z` | Reverses the most recent run |

`Space` ticks or unticks a line, and `a` / `n` tick / untick everything shown. `/` takes you to the filter box: type
a game version, a date (`2024-01`) or a file name, then press **Filter** or `Enter`. A screenshot the filter hides
keeps its tick and is still sorted. `x` / `c` expand / collapse the whole tree, and `←` `→` switch panes.

`f` or `Esc` picks another game version. `t` goes back to the tool menu from any screen or popup, except while a run
is writing. `s` opens the settings and `q` quits. The results screen has **Rescan** (`r`; `Esc` also goes back to the
review and scans again), **Other flavor** (`f`), **Tools** (`t`) and **Quit** (`q`).

## Settings (`s`)

- **Destination folder**: empty sorts each `Screenshots` folder in place; a folder you pick gets
  `<folder>\\<game version folder, e.g. _retail_>\\<year>\\<month>\\<day>`.
- **Copy instead of move**: keep the originals in `Screenshots` too.

## Warnings

When a folder could not be read, the bottom line shows **⚠ N unreadable folders (!)** at its right end. Click it or
press `!` to list them by game version, each with the folder and the error. `/` filters the list, `x` / `c` expand /
collapse it, `h` opens the help, and **Back** (`Esc`) returns to the review.

## Safety

- **Nothing is ever overwritten.** If the same file is already sorted, it's a duplicate and is removed from
  `Screenshots` (in copy mode it's left alone and marked **Already filed**). A different file with the same name is a
  **conflict**: both are left alone and listed.
- In copy mode a screenshot whose name and size are already in its dated folder is listed unticked under
  **Already filed (N)**; tick it by hand to have the run compare the two files.
- Only WoW screenshot names are sorted; anything else is skipped and listed.
- Moving to another drive copies and checks each file before the original is deleted.
- **Undo last run** goes back one run. Moved shots return, copies are removed and removed duplicates come back. It
  only touches screenshots that haven't changed since the run.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
