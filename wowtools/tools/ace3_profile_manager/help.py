"""The Ace3 Profile Manager's help screen text (spec D18), shown with h on any of its screens. Keep it to the core
functions; docs/ace3-profile-manager.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/ace3-profile-manager.md"

HELP = f"""\
Addons built on **Ace3** (ElvUI, Bartender4, ...) keep their settings in **profiles**, and each character uses one.
This tool shows every addon's profiles and who uses them, and lets you delete, rename and copy profiles, move
characters to another profile and remove characters that no longer exist. **Close WoW first**: Apply and Undo
refuse while it runs.

## Step by step

1. **Pick a game version**, or **All flavors**; then an account, or **All accounts**.
2. The **review** shows a tree: game version → account → addon → profile → its characters. `v` switches to **By
   character**. Nothing is ticked yet.
3. **Tick** profiles or characters (`Space`), or just highlight one, and press an action below the tree. Each
   change is **pending**: the tree shows it at once (`✘ deleted`, `was Healer`), but no file is touched.
4. **Dry run** (`y`) checks every pending change without writing anything.
5. **Apply** (`w`), read the summary, press **Yes**. The **results** list every change.

## The action bar (under the tree)

| Button | Key | Does |
|---|---|---|
| **Assign** | `p` | Moves the ticked (or highlighted) characters to another profile |
| **Rename** | `e` | Renames the highlighted profile; its characters follow it |
| **Copy** | `k` | Copies the highlighted profile under a new name |
| **Everyone → Default** | `E` | Moves every character of the ticked addons to "Default" |
| **Delete** | `d` | Deletes the ticked profiles; you pick where their characters go |
| **Only Default** | `D` | Deletes every profile but "Default" and moves everyone onto it |
| **Leftovers** | `o` | Removes ticked characters whose folder no longer exists |
| **Blacklist…** | | Edits the blacklist: addons shown but never changed (`b` toggles the highlighted one) |
| **More…** | `m` | Quick actions, and every key the bottom row doesn't show |
| **Discard** | `Backspace` | Drops every pending change |

## Left pane

| Button | Key | Does |
|---|---|---|
| **Apply** | `w` | Writes the pending changes, after backing everything up (asks first) |
| **Dry run** | `y` | Checks them, writes nothing; **Back to review** (`Esc`) keeps them pending |
| **Rescan** | `r` | Reads the files again |
| **Undo last change** | `z` | Puts back every file the last Apply changed |

The **Show** boxes narrow the tree (only addons with 2+ profiles, only unused profiles, leftover characters,
blacklisted addons). `a` / `n` tick / untick everything shown, `/` reaches the filter box (type, then **Filter** or
`Enter` filters the tree; `Esc` clears it), `x` / `c` expand / collapse it all, `u` unlocks a blacklisted addon for
this session, `←` `→` switch panes, `Tab` or `↓` on the last line reach the action bar. `f` or `Esc` picks another
game version, `t` goes back to the tool menu, `s` opens the settings, `q` quits (leaving with pending changes asks
first). On the results: **Rescan** (`r`), **Other flavor** (`f`), **Tools** (`t`), **Quit** (`q`).

## Warnings

When the scan could not read a file (or skipped a folder), the bottom line shows **⚠ N scan warnings**, and the
tree lists them too: click it or press `!` (the **Warnings** button) to see them by game version, each with the
file and what went wrong. **Back** (`Esc`) returns to the review.

## Safety

- Before writing, Apply checks no file changed since the scan and no program has one open, zips your **whole `WTF`
  folder** and the files it edits, then writes only the lines that change and reads each file back.
- It never touches the settings inside a profile, other addon data, or Blizzard's files.
- **Undo last change** goes back one Apply, and leaves alone a file saved again since.

## Settings (`s`)

- **Backup folder**: where the zips go (`snapshots` for the whole `WTF` folder, `edited` for each changed file as it
  was). Empty means `<WoW folder>\\wow-tools\\ace3-profile-manager`. How many are kept is a shared setting.
- **Edit blacklist…** (or **Blacklist…** on the review) opens the blacklist: tick the addons to leave alone, in
  every game version. **Select none** (`n`) unticks them all, **Save** keeps the list, **Cancel** (`Esc`) drops
  the edits.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
