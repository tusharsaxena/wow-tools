# Changelog

Every change to Ka0s WoW Tools that you'd notice, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version numbers follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-05

The first version: four tools in one app.

### Added

- **The app**
  - One app with a tool menu: pick a tool, use it, and come back to the menu when you're done.
  - Works with every installed game version (Retail, Classic, Classic Era, Anniversary, PTR and Beta) on Windows,
    Mac, Linux and WSL.
  - Checks for updates and installs them for you.
  - How many backups and journals to keep is one setting for every tool (10 each; 0 backups keeps them all), on
    the first settings screen.
  - `x` expands and `c` collapses every line of a tree, on every tree screen.
  - `/` filters every tree: type part of a name (an addon, a file, a date, a profile…) and the tree keeps the
    matching lines and the groups they're in. `a` / `n` tick or untick only what the filter shows; ticks it hides
    stay, and the bottom line and the "are you sure?" window say how many. `Esc` in the filter box clears it.
  - Every checkbox and box in a left panel has a row of its own, so `↑` / `↓` reach each one.
  - Buttons are coloured by what they do, the same in every tool: red deletes, amber overwrites, green only adds
    files, violet undoes, cyan is a dry run, blue confirms, grey moves between screens, dim grey backs out.
  - Every "are you sure?" window opens on **Yes**, coloured by what it does (red when it deletes, overwrites, undoes
    or drops pending changes); Enter and Space wait a quarter of a second after it opens and are ignored while
    a held key repeats, `y` / `n` / `Esc` answer at once. The update offer's "Update now" waits the same way.
  - The bottom row of every screen shows the version, and says when a new one is out and how to get it (on the
    Ace3 Profile Manager's review, where `u` unlocks an addon, it points you to the tool menu).
  - The tool menu shows the version under the banner (and the new one, once found), and the terms of use along
    its bottom; in a short window the tool list scrolls so the terms and the keys stay in view.
  - Game versions that don't depend on each other are worked on several at once: Interface Backup's backups and
    its scan, the WTF Cleaner's scan of All flavors, the Screenshot Organizer's counts in the flavor picker and the
    WTF backups Ace3 Undo takes first. How many at once is `parallelism` on the first settings screen (2, from 1 to
    8; use 1 on a hard drive or a WSL `/mnt` folder). A WTF clean and an Ace3 Apply still go one game version at a
    time.
  - The progress window keeps one size from start to finish in every tool: the job, an overall bar ("1 of 3 game
    versions"), a row per game version being worked on (label, step and its own bar) and the current file; long
    text is cut short with "…" instead of wrapping.
  - `c` on the tool menu opens the changelog: every version on the left (yours marked "current"), its notes on the
    right.
- **WTF Cleaner**
  - Finds settings left behind by addons you no longer use, shows them for review, backs them up and deletes them.
  - Works on one game version, one account or **All flavors**.
  - **Clean** is on `w`.
  - **Dry run** and **Undo last clean**.
- **Screenshot Organizer**
  - Sorts screenshots into year, month and day folders, in place or into an archive folder.
  - Duplicate checks, copy mode, **Dry run** and **Undo last run**.
- **Interface Backup**
  - Zips each game version's `Interface` and `WTF` folders (your addons and their settings) into one dated,
    checked zip, and keeps the newest backups per game version (see the retention setting under "The app").
  - Restores a backup exactly: the `Interface` folder, the `WTF` folder or both, after listing what would be
    removed or changed. It takes a safety backup first, and **Undo** puts the folders back.
  - Never follows linked addon folders (symlinks, junctions): they're left out of backups and kept by a restore.
- **Ace3 Profile Manager**
  - Shows every Ace3 addon's profiles and which characters use them.
  - Deletes, renames and copies profiles, moves characters between them and removes characters that no longer
    exist.
  - A blacklist (per game version, picked from a tree) keeps addons out of its reach.
  - Changes wait as **pending changes** until you apply them; an action bar and a guidance line under the tree say
    what to do next.
  - Edits only the lines that change in each settings file, after backing up the whole `WTF` folder and every file
    it edits, and refuses while WoW is running.
  - **Dry run** and **Undo last change**.
