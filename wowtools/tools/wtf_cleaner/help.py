"""The WTF Cleaner's help screen text (spec D18), shown with h on any of its screens. Keep it to the core
functions; docs/wtf-cleaner.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/wtf-cleaner.md"

HELP = f"""\
Finds the settings files (**SavedVariables**) that addons you no longer use left in WoW's `WTF` folder, backs them
up, and deletes the ones you leave ticked. **Close WoW first**: it rewrites these files when you log out.

## Step by step

1. **Pick a game version**, or **All flavors**; if that version has more than one account, then an account or
   **All accounts**.
2. Read the **USE AT YOUR OWN RISK** warning (before the first scan): **I understand** goes on, **Back** or `Esc`
   returns to the game versions. Once you press **I understand**, it isn't asked again until you restart the app.
   Tick **Don't show this warning again for this tool** (`Tab`, `Space`) to stop it for good; the tool's settings
   (`s`) turn it back on.
3. The **review** lists the files suggested for removal: game version → account → character → addon → files.
   Everything starts ticked ("remove this"): untick what you want to keep.
4. **Dry run** (`y`) to see what would happen; nothing is deleted.
5. **Clean** (`w`), read the summary, press **Yes**.
6. The **results** list every file and what happened to it.

## The rules (left pane, **Criteria (keys 1-5)**)

A file is suggested when any ticked rule matches it. `1`-`5` switch a rule on or off; the **Max age in days** box sets
the age limit for rule 3 (type the days, then `Enter`).

| Key | Rule | Suggests |
|---|---|---|
| `1` | Not installed | Settings of addons no longer installed |
| `2` | Not enabled | Addons installed but switched off on every character of that account |
| `3` | Older than max age | Settings unchanged for longer than the age limit (90 days to start with) |
| `4` | Stray copies | Copies made by hand next to the real file (`Details.lua - Copy.bak`) |
| `5` | Orphan backups | A `<Addon>.lua.bak` with no `<Addon>.lua` next to it |

When an addon matches rule 1, 2 or 3, all its files go (`.lua`, `.lua.bak`, stray copies); rules 4 and 5 suggest
only the extra files.

Never touched: Blizzard's own files, keybindings, macros, chat and UI layout, and anything outside `WTF`.

## Buttons and keys

| Button | Key | Does |
|---|---|---|
| **Clean** | `w` | Deletes the ticked files, after backing them up (asks first) |
| **Dry run** | `y` | Checks the files and zips what it would remove; no WTF backup, no journal, nothing deleted |
| **Rescan** | `r` | Scans again (after changing settings, say) |
| **Undo last clean** | `z` | Puts back every file the last clean deleted |

`Space` ticks or unticks a line, `a` / `n` tick / untick everything shown, `/` reaches the filter box (type, then
**Filter** or `Enter` filters the tree; a hidden file keeps its tick and is still cleaned), `x` / `c` expand /
collapse it all, `←` `→` switch panes. `f` or `Esc` picks another game version, `t` goes back to the tool menu (from any
screen or popup, not while a clean runs), `s` opens the settings, `q` quits. On the results: **Rescan** (`r`, or
`Esc`: back to the review, scanned again), **Other flavor** (`f`), **Tools** (`t`), **Quit** (`q`).

## Blacklist

An addon you never want cleaned goes on the **blacklist**: highlight its line (or one of its files) and press `b`.
Its lines stay in the tree, greyed, with `⊘` where the tick goes and marked *blacklisted*. They're never ticked,
counted or cleaned. The blacklist applies to that game version only, and `b` on the addon again takes it off.
The list is `blacklist` in `config\\wtf-cleaner.cfg` (`_retail_:ElkBuffBars, ...`; a name without a game version
means every one).

## Warnings

When the scan can't read something (a folder, a file, a line of an `AddOns.txt`), the bottom line shows
**⚠ N scan warnings (!)**: click it or press `!` to list them by game version, each with where it is and what
went wrong. **Back** (`Esc`) returns to the review.

## Safety

- Before deleting, the cleaner writes a **journal**, checks that no program has the files open (the Raider.IO
  client and the WeakAuras Companion lock them), zips your **whole `WTF` folder**, then zips the files it removes. If
  any step fails, nothing is deleted.
- **Undo last clean** goes back one clean, and never overwrites a file that has appeared since.
- Backups go to `<WoW folder>\\wow-tools\\wtf-cleaner` unless you pick another folder in settings (`s`).

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
