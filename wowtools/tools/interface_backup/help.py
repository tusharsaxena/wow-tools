"""Interface Backup's help screen text (spec D18), shown with h on any of its screens. Keep it to the core
functions; docs/interface-backup.md has the rest."""
from __future__ import annotations

GUIDE_URL = "https://github.com/tusharsaxena/wow-tools/blob/master/docs/interface-backup.md"

HELP = f"""\
Zips a game version's `Interface` folder (your addons) and `WTF` folder (their settings, your keybindings and
macros) into one dated zip, and puts them back from a zip when something goes wrong. **Close WoW before you
restore.**

## Making a backup

1. **Pick a game version**, or **All flavors**.
2. The **review** counts what each `Interface` and `WTF` folder holds. Untick a game version to leave it out.
3. **Back up** (`b`), read the summary, press **Yes**.
4. The **results** show each zip and its size.

## Restoring a backup

1. On the review, open a game version's **Backups** line (`Enter`) and highlight a backup.
2. **Restore** (`e`, or `Enter` on the backup) opens the **restore screen**.
3. Tick **Interface**, **WTF** or both. The tree shows what you would lose: files that will be removed, and files
   newer now than in the backup.
4. **Restore** (`o`), read the summary, press **Yes**. **Back** (`b` or `Esc`) leaves without restoring.
5. The **results** say what happened to each folder; **Undo** (`z`) there takes it back.

## Buttons and keys

| Button | Key | Does |
|---|---|---|
| **Back up** | `b` | Backs up the ticked game versions (asks first) |
| **Restore** | `e` | Opens the restore screen for the highlighted backup |
| **Rescan** | `r` | Scans again (after changing settings, say) |
| **Undo last restore** | `z` | Puts back the folders the last restore replaced |

`Space` ticks or unticks a game version (`Enter` opens a line), `a` / `n` tick / untick every game version shown, `/`
reaches the filter box (type, then **Filter** or `Enter` filters the tree; a hidden ticked version is still backed
up), `x` / `c` expand / collapse it all, `←` `→` switch panes. `f` or `Esc` picks another game version, `t` goes
back to the tool menu and `q` quits (from any screen or popup, not while a backup or restore runs), `s` opens the
settings. On the backup results: **Rescan** (`r`), **Restore** (`e`), **Other flavor** (`f`), **Tools** (`t`),
**Quit** (`q`); on the restore results, **Undo** (`z`) comes first and there is no **Restore**. On both, `Esc` goes
back to the review and scans again.

## Warnings

When the scan skipped something it could not read, the bottom line of the review and of the restore screen shows
**⚠ N scan warnings (!)**: click it or press `!` to list them by game version, each with its folder (`Interface` or
`WTF`) and what went wrong. **Back** (`Esc`) returns.

## Safety

- The app checks every zip after writing it. It keeps the newest backups of each game version (as many as the
  shared settings say, 10 by default; `0` keeps them all) and deletes old ones only after the new zip checks out.
- Before every restore, the app takes a **safety backup** of the folders as they are now, so you can undo the
  restore. Safety backups are listed under **Backups** and can be restored too.
- A folder is swapped in one rename, and only once the new copy is complete, so it is never left half-copied.
  Links are kept.
- **Undo last restore** goes back one restore, from its safety backup.
- Backups go to `<WoW folder>\\wow-tools\\interface-backup\\backup` unless you pick another **Backup folder** (`s`).

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
