# Changelog

Every change to Ka0s WoW Tools that you'd notice, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version numbers follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-05

The first version: five tools in one app.

### Added

- **The app**
  - One app with a tool menu: pick a tool, use it, and come back to the menu when you're done.
  - Works with every installed game version (Retail, Classic, Classic Era, Anniversary, PTR and Beta) on Windows,
    Mac, Linux and WSL.
  - Notices a running WoW for the game versions you're working on, on every platform (Windows, WSL, Mac and
    Linux), and warns you or waits before touching files WoW rewrites.
  - Checks for updates and installs them for you. Older backups of replaced versions are deleted, but files you
    had added inside the app's own folders are moved to `update-leftovers` first.
  - How many backups and journals to keep is one setting for every tool (10 each; 0 backups keeps them all), on
    the first settings screen.
  - `x` expands and `c` collapses every line of a tree, on every tree screen.
  - `/` filters every tree: type part of a name (an addon, a file, a date, a profile…), press `Enter` or the
    **Filter** button beside the box, and the tree keeps the matching lines and the groups they're in (typing alone
    doesn't rebuild the tree, so big trees stay quick). `a` / `n` tick or untick only what the filter shows; ticks it hides
    stay, and the bottom line and the "are you sure?" window say how many. A group's tick mark counts what the
    filter shows, and a filter that matches nothing says so. `Esc` in the filter box clears it.
  - The title bar of every screen reads **Ka0s WoW Tools** in bold gold, then the tool, game version and view in bold
    white.
  - The screens that can destroy data (the WTF Cleaner, Ace3 Profile Manager and Saved Variables Browser reviews and
    Interface Backup's restore screen) show a red `⚠ USE AT YOUR OWN RISK` line at the top of their left panel.
  - Every checkbox and box in a left panel has a row of its own, so `↑` / `↓` reach each one.
  - Buttons are coloured by what they do, the same in every tool: red deletes, amber overwrites, green adds
    something new, violet undoes, cyan is a dry run, blue confirms, grey moves between screens, dim grey backs out.
  - `h` opens a help screen everywhere: on the tool menu it explains the app (what each tool does, the keys every
    tool shares, settings, button colours); in a tool it explains that tool, step by step, with every button and
    its key, the safety nets and a link to the tool's guide. `Esc`, `q` or `h` closes it.
  - Every button shows its key under its name (**Clean** over `(w)`), and the row of keys along the bottom lists
    only the keys no button has, so it stays short; while a popup is open it is empty, since the popup's buttons
    say what to press.
  - Every "are you sure?" window opens on **Yes**, coloured by what it does (red when it deletes, overwrites, undoes
    or drops pending changes, a backup that deletes older ones included); Enter and Space wait a quarter of a
    second after it opens and are ignored while a held key repeats, `y` / `n` / `Esc` answer at once. The update offer's "Update now" waits the same way.
  - The bottom row of every screen shows the version, and says when a new one is out and how to get it (on the
    Ace3 Profile Manager's review, where `u` unlocks an addon, it points you to the tool menu).
  - The tool menu shows the version under the banner (and the new one, once found), and the terms of use along
    its bottom; in a short window the tool list scrolls so the terms and the keys stay in view.
  - Game versions that don't depend on each other are worked on several at once: Interface Backup's backups and
    its scan, the WTF Cleaner's scan of All flavors, the Screenshot Organizer's counts in the flavor picker and the
    WTF backups Ace3 Undo takes first. How many at once is `parallelism` on the first settings screen (2, from 1 to
    8; use 1 on a hard drive or a WSL `/mnt` folder). A WTF clean and an Ace3 Apply still go one game version at a
    time.
  - The progress window keeps one size from start to finish in every tool: the job, an overall bar when several
    game versions are worked on ("1 of 3 game versions"), a row per game version being worked on (label, step and
    its own bar) and the current file; long text is cut short with "…" instead of wrapping.
  - Scan warnings have a screen of their own, so you never have to read the logs for them: when a scan couldn't
    read something, a **⚠ N scan warnings (!)** button sits at the right end of the bottom bar (the review screens
    of every tool and Interface Backup's restore screen). Click it or press `!` to open the warnings view: every
    warning grouped by game version, each with where it is and what went wrong, with the `/` filter, `x` / `c`, `h`
    and **Back** (`Esc`).
  - `b` on a tree line puts the highlighted addon (or the addon a file or profile belongs to) on the tool's
    blacklist, or takes it off, in the tools that keep one (the WTF Cleaner and the Ace3 Profile Manager), and says
    which ("ElkBuffBars (Retail) is now on the blacklist."). Each tool keeps its own list.
  - `c` on the tool menu opens the changelog: every version on the left (yours marked "current"), its notes on the
    right.
- **WTF Cleaner**
  - Finds settings left behind by addons you no longer use, shows them for review, backs them up and deletes them.
  - Works on one game version, one account or **All flavors**.
  - Five rules, each switched on or off with `1` to `5`: Not installed, Not enabled, Older than max age, Stray
    copies and **Orphan backups** (an `<Addon>.lua.bak` whose `<Addon>.lua` is gone). An addon a rule matches
    loses all its files, its `.lua.bak` included.
  - "Not enabled" is decided per account: settings for an addon that only another account uses are suggested (an
    account with no characters counts every addon as enabled).
  - **Clean** is on `w`.
  - A blacklist of addons it never cleans, one game version each: `b` on an addon's line (or one of its files) adds
    it or takes it off. Blacklisted addons stay in the review, greyed and tagged "blacklisted", but are never
    ticked, counted or cleaned. The list is `[wtf_cleaner] blacklist` in `config\wtf-cleaner.cfg`
    (`_retail_:ElkBuffBars, ...`; a name without a game version means every one).
  - **Dry run** and **Undo last clean**.
  - The zips of the files each clean removed are kept forever unless you set how many to keep per game version
    (**Cleaned-files zips to keep** in its settings; 0, the default, keeps them all).
- **Screenshot Organizer**
  - Sorts screenshots into year, month and day folders, in place or into an archive folder.
  - Duplicate checks, copy mode, **Dry run** and **Undo last run**.
- **Interface Backup**
  - Zips each game version's `Interface` and `WTF` folders (your addons and their settings) into one dated,
    checked zip, and keeps the newest backups per game version (see the retention setting under "The app").
  - Restores a backup exactly: the `Interface` folder, the `WTF` folder or both, after listing what would be
    removed or changed. It takes a safety backup first, and **Undo** puts the folders back.
  - Never follows linked addon folders (symlinks, junctions): they're left out of backups and kept by a restore.
  - Backing up several game versions: one that fails never stops the others, and the results list each one.
- **Ace3 Profile Manager**
  - Shows every Ace3 addon's profiles and which characters use them.
  - Deletes, renames and copies profiles, moves characters between them and removes characters that no longer
    exist.
  - A blacklist (per game version, picked from a tree, or `b` on an addon in the review) keeps addons out of its
    reach. When the filter hides ticked
    addons, **Save** says how many and asks first.
  - Changes wait as **pending changes** until you apply them; an action bar and a guidance line under the tree say
    what to do next.
  - Edits only the lines that change in each settings file, after backing up the whole `WTF` folder and every file
    it edits, and refuses while WoW is running.
  - **Dry run** and **Undo last change**.
- **Saved Variables Browser** (use at your own risk)
  - Shows every SavedVariables file of every game version, account and character as a tree you can open down to
    single values; a file is only read when you open it, and a big table shows its first 500 entries.
  - Edits a value (string, number or boolean), renames a key or deletes a key (a whole table with it); a top-level
    variable can only have its value edited, and an array entry can be deleted (the entries after it move down) but
    not renamed.
  - **Search** (`S`) finds values by key (Exact or Contains), by value (Whole value or Contains) or both, with
    **Match case**, in one game version, account, character or addon file. The hits show as `path = value`, all
    ticked, up to 10,000.
  - On the results, **Edit value** and **Rename key** work on every ticked hit at once ("Edit 37 values"); after a
    value Contains search, Edit value can replace only the matched text. Each hit gets its own staged edit, marked
    in the results and in the tree alike; a hit that can't take it is left out, and a notice says why.
  - Edits wait as staged changes until you apply them.
  - Changes only the bytes you edited, after backing up the whole `WTF` folder and every file it edits, checks each
    new file before writing it, and refuses while WoW is running. **Dry run** and **Undo last change**; a change
    cut short (a crash, a power cut) can be put back.
  - Asks you to accept a USE AT YOUR OWN RISK warning each time you open it, and repeats it on every Apply and Undo.
- **Shared SavedVariables library**
  - The SavedVariables reader and the safe write pipeline (backups, journal, Undo, recovery) the Ace3 Profile
    Manager used are now shared by both tools; the Ace3 Profile Manager works as before.
  - Strings with a backslash before a character Lua 5.1 doesn't treat as an escape (`\x41`, `\z`) are now read the
    way WoW reads them.
