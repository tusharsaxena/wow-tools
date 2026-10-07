"""The Screenshot Organizer's help screen text (spec D18), shown with h on any of its screens. Keep it to the core
functions; docs/screenshot-organizer.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/screenshot-organizer.md"

HELP = f"""\
Sorts the screenshots in each game version's `Screenshots` folder into **year / month / day** folders, either right
where they are or into an archive folder you choose (a photos drive, say). File names are never changed, and the
date comes from the name WoW gives each screenshot (`WoWScrnShot_MMDDYY_HHMMSS.jpg`).

## Step by step

1. **Pick a game version**, or **All flavors**. Each row counts the screenshots waiting to be sorted.
2. The **review** lists them: game version → year → month → day → screenshots. Everything starts ticked ("sort
   this"): untick a day, a month or a version to leave it alone.
3. **Dry run** (`y`) shows what would happen; nothing moves.
4. **Organize** (`o`), read the summary, press **Yes**.
5. The **results** list every screenshot and where it went.

## Buttons and keys

| Button | Key | Does |
|---|---|---|
| **Organize** | `o` | Moves (or copies) the ticked screenshots into dated folders (asks first) |
| **Dry run** | `y` | Every check, nothing moved: "Would move", "Would copy" |
| **Rescan** | `r` | Scans again (after changing settings, say) |
| **Undo last run** | `z` | Reverses the most recent run |

`Space` ticks or unticks a line, `a` / `n` tick / untick everything shown, `/` reaches the filter box: type a game
version, a date (`2024-01`) or a file name, then **Filter** or `Enter` filters the tree (a hidden screenshot keeps
its tick and is still sorted), `x` / `c` expand / collapse it all, `←` `→` switch panes. `f` or `Esc` picks another
game version, `t` goes back to the tool menu, `s` opens the settings, `q` quits. On the results: **Rescan** (`r`),
**Other flavor** (`f`), **Tools** (`t`), **Quit** (`q`).

## Settings (`s`)

- **Destination folder**: empty sorts each `Screenshots` folder in place; a folder you pick gets
  `<folder>\\<game version>\\<year>\\<month>\\<day>`.
- **Copy instead of move**: keep the originals in `Screenshots` too.

## Warnings

When a folder could not be read, the bottom line shows **⚠ N unreadable folders**: click it or press `!` (the
**Warnings** button) to list them by game version, each with the folder and the error. **Back** (`Esc`) returns to
the review.

## Safety

- **Nothing is ever overwritten.** The same file already sorted is a duplicate (removed from `Screenshots`); a
  different file with the same name is a **conflict**, left alone and listed.
- Only WoW screenshot names are sorted; anything else is skipped and listed.
- Moving to another drive copies and checks each file before the original goes.
- **Undo last run** goes back one run: moved shots go back, copies are removed, removed duplicates come back. It
  only touches screenshots unchanged since the run.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
