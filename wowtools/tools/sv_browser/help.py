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
2. The **review** shows what you picked.

This build of the tool stops at the review: **Back** returns to the game versions. Browsing, search and editing
come in the next build.

## Keys

`f` or `Esc` picks another game version, `t` goes back to the tool menu, `s` opens the settings, `q` quits.

## Settings (`s`)

- **Backup folder**: where the zips go (`snapshots` for the whole `WTF` folder, `edited` for each changed file as it
  was). Empty means `<WoW folder>\\wow-tools\\sv-browser`. How many are kept is a shared setting.

**Full guide:** [{GUIDE_URL}]({GUIDE_URL})
"""
