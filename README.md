<img src="docs/assets/ka0s-logo.png" alt="Ka0s" width="220">

# Ka0s WoW Tools

Out-of-game companion tools for World of Warcraft, in one app. You start it with `wow-tools`, pick a tool from
the menu, and come back to the menu when you're done. Each tool has its own workflow and settings file; they
share the WoW folder, the bundled libraries and one look. It runs straight from this folder on Windows, Linux and
WSL. There's no `pip install` and no virtualenv.

| Tool | What it does |
|---|---|
| **WTF Cleaner** | Finds SavedVariables left behind by addons you no longer use, backs them up to a zip, and deletes them. |
| **Screenshot Organizer** | Files screenshots into year/month/day folders, per flavor, in place or into an archive folder, with dry run and undo. |

## Requirements

- **Python 3.10 or newer.** On Windows, install it from python.org (tick "Add python.exe to PATH") or the
  Microsoft Store. The `py` launcher is used when present.
- World of Warcraft, in any flavor: Retail, Classic, Classic Era, Anniversary, PTR or Beta.

## Getting it

- **With git (recommended, so updates are one command):**
  `git clone https://github.com/tusharsaxena/wow-tools.git`
- **As a zip:** download the latest release from
  [Releases](https://github.com/tusharsaxena/wow-tools/releases) and unzip it anywhere.

## Quick start

There is one way in:

| Platform | Start |
|---|---|
| Windows | double-click `wow-tools.cmd` |
| Linux / WSL | `./wow-tools.sh` |

The first screen lists the tools. Pick one with `↑`/`↓` and `Enter`. Inside a tool, `Esc` on the flavor screen or
`t` on the review and results screens takes you back to the menu; `q` quits. `s` opens the settings: on the menu
the shared WoW folder, inside a tool the WoW folder and then that tool's own settings. The tools can't be started
on their own.

**First time you open a tool.** It asks for:

1. **Your World of Warcraft folder** (once, shared by every tool). This is the folder that contains `_retail_`,
   `_classic_` and so on. Common locations on every drive are detected for you.
2. **That tool's settings.** For the WTF Cleaner: the age limit, which criteria to use, whether to back up before
   deleting, and the **backup folder**. Leave the backup folder empty to use `<WoW folder>\wow-tools\wtf-cleaner`.
   For the Screenshot Organizer: the destination folder (empty = organise in place), how many run journals to
   keep, and whether to copy instead of move.

Your answers are saved in the `config\` folder (see [Settings](#settings-config)). Then you pick a **flavor**, and
the last one you used is pre-selected next time. If the flavor has more than one WoW account, you then pick an **account**, or
"All accounts". The last choice is pre-selected next time.

> **Close WoW before cleaning.** WoW rewrites SavedVariables when you log out, and it can recreate files you
> just removed. The tool warns you if it sees WoW running for the flavor you chose (see
> [Is WoW running?](#is-wow-running)).

## WTF Cleaner

### What gets proposed

Each rule can be switched on or off. By default **all four are on**, and a file is proposed if **any**
rule matches.

| Criterion | Proposes… | Example |
|---|---|---|
| `not_installed` | SavedVariables for addons no longer in `Interface\AddOns` | `WTF\Account\ME\SavedVariables\OldBagAddon.lua` |
| `not_enabled` | SavedVariables for installed addons that **no character in scope** has enabled | Addon disabled on every character |
| `older_than` | Addons whose newest SavedVariables file is older than the age limit (default 90 days) | `Recount.lua` untouched since last expansion |
| `stray_copies` | Hand-made copies next to real files: anything but `<Addon>.lua` / `<Addon>.lua.bak` | `Details.lua - Copy.bak`, `Plater.lua.pre-update` |

It looks in every account in scope, both account-wide (`WTF\Account\<ACCOUNT>\SavedVariables`) and
per character (`WTF\Account\<ACCOUNT>\<Realm>\<Character>\SavedVariables`). An addon's `.lua` and `.lua.bak`
files are treated as one group.

### Account scope

- **All accounts** (the default): "enabled" is judged across the whole flavor. If an addon is enabled on any
  character of any account, its SavedVariables are kept everywhere.
- **One account** (picked on the account screen): only that account's
  SavedVariables are scanned and proposed, and only that account's characters decide what counts as enabled.
  An addon enabled only on another account's characters counts as not enabled here.

A character with no `AddOns.txt`, or an addon that isn't listed in it, counts as enabled, because that's what
WoW does.

### What is never touched

- `Blizzard_*` SavedVariables.
- Everything outside `SavedVariables` folders: `config-cache.wtf`, keybindings, macros, `AddOns.txt`,
  layouts, chat settings.
- Anything outside the chosen flavor's `WTF\Account` folder.

If a flavor has no addons installed at all, the scan stops rather than proposing everything.

### Using the TUI

The review screen shows a tree: account → account-wide / each character → addon → files.
Everything starts ticked. A progress bar shows while the scan runs.

The left panel holds the criteria, the max age box and three buttons: **Clean**, **Dry run** and **Rescan**.
Each criterion shows how many files it matches on its own, for example `1 Not installed (672 files)`. The counts
update after each scan and whenever the max age changes. A ticked criterion shows a bright `✔` and an unticked
one a dimmed `✘`. The tree uses the same marks.

Each criterion has its own colour. It's used on the criterion's checkbox and wherever that reason appears in
the tree:

| Colour | Criterion |
|---|---|
| Red (`#E5534B`) | `not_installed` |
| Orange (`#F08C3A`) | `not_enabled` |
| Yellow (`#E8C547`) | `older_than` |
| Purple (`#B07CFF`) | `stray_copies` |

| Key | Action |
|---|---|
| `space` | Tick or untick the highlighted account, character, addon or file (on a button, press it) |
| `a` / `n` | Tick all / none |
| `1` `2` `3` `4` | Toggle `not_installed`, `not_enabled`, `older_than`, `stray_copies` |
| Max age box + `Enter` | Change the age limit for this session |
| `c` | **Clean** the ticked files (asks for confirmation first; the dialog starts on **No**) |
| `y` | **Dry run** on the ticked files (asks first; the dialog starts on **Yes**) |
| `r` | Rescan |
| `f` | Choose another flavor |
| `s` | Settings |
| `u` | Install an available update |
| `q` | Quit |

While a clean runs, a progress window shows the current stage, a percentage bar and the current file:
checking the selected files, checking for locked files, listing the WTF folder, backing up and verifying the WTF
folder, zipping and verifying the files to clean, deleting, and checking the result. A dry run skips the lock
check, the WTF backup and the result check. When a criterion or the max age changes, the tree shows a loading spinner
and the summary bar says "Updating the list…" until the new list is ready. The results screen then shows a summary table and a table of every file
with its status, account, character, addon, size and reasons.

#### Keyboard use

Every screen works without a mouse, and each one shows a one-line hint with its keys.

| Key | Action |
|---|---|
| `↑` / `↓`, `Tab` / `Shift+Tab` | Move between fields and buttons |
| `←` / `→` | Move between the buttons in a row. On the review screen they also switch panes: `←` from the tree goes to the filters (to the control you used last), `→` from the filters or the last button goes to the tree |
| `Enter` or `Space` | Press the focused button, or tick the focused checkbox |
| `Esc` | Go back or cancel |

The tree, lists, tables and text boxes keep the arrow keys for themselves while they have focus. Use `Tab` to
leave them.

### Dry run

A dry run (the **Dry run** button or `y`) writes and verifies the cleaned-files zip, exactly as a real clean
would, and then deletes nothing. It reports what *would* be deleted, and it's recorded in the log. It takes no
WTF backup. If zipping the cleaned files is turned off, a dry run writes nothing at all.

### Where the zips go

Everything the cleaner writes goes in its backup folder, a WTF Cleaner setting (press `s`). By default that is
`<WoW folder>\wow-tools\wtf-cleaner`:

```
wow-tools\wtf-cleaner\
  backup\backup-<flavor>-<YYYYMMDD-HHMMSS>.zip                  the whole WTF folder, taken before each clean
  cleaned\cleaned-<flavor>-<account>-<YYYYMMDD-HHMMSS>.zip      only the files that clean removed
```

`<flavor>` is the flavor folder's short name (`retail`, `classic_era`, …), and `<account>` is the account you
picked, or `all` for "All accounts". For example `cleaned-retail-all-20261003-140311.zip`.

- **Cleaned files** (`cleaned\`). Before deleting, the cleaner zips the files it is about to remove, then
  re-opens the zip and checks every file. **If it can't be written or verified, nothing is deleted.** Each zip has
  a `manifest.json` listing every file, its size and why it was removed. These zips are never deleted by the tool.
  You can turn them off in settings, but it isn't recommended.
- **WTF backups** (`backup\`). See [Backup of the WTF folder](#backup-of-the-wtf-folder). The newest 5 **of each flavor**
  are kept (`keep_backups` in settings); older ones of that flavor are deleted after each clean. Only files named
  `backup-<flavor>-<stamp>.zip` are ever deleted.

Zips from older versions (`wtf-cleaner_<flavor>_*.zip`, `wtf-snapshot_*.zip` in the folder itself) are left alone.

### Locked files

Some companion apps hold SavedVariables files open, which stops Windows from deleting them. The Raider.IO
client is known to do this, and so is the WeakAuras Companion. Before a real clean:

- the confirm dialog warns you if either app is running;
- before the WTF backup, each selected file is renamed aside and straight back. This is a lock test that fails
  exactly when a delete would fail. If any file is locked, the clean stops with nothing deleted and names the
  locked files (`clean.locked`). Close the app and clean again.

Dry runs skip both checks.

### Backup of the WTF folder

A real clean (not a dry run) also protects you against a crash halfway through. Before deleting anything it:

1. zips the **whole** `<flavor>\WTF` folder to `<backup folder>\backup\backup-<flavor>-<YYYYMMDD-HHMMSS>.zip` and
   verifies it;
2. writes a marker file, `<backup folder>\clean-in-progress.json`, that names that backup and the files about
   to be deleted.

If the backup can't be written, the clean stops and nothing is deleted. The backup is **kept** after the clean
(the newest `keep_backups` of each flavor, default 5, are kept).

When the deleting is done (including when a few files could not be deleted), the cleaner checks the WTF folder
against the backup:

- every file it deleted is really gone;
- every other file in the backup is still on disk;
- with the cleaned-files zip on, it lists every deleted file at the right size.

The results screen shows the backup's path and the check's result. If the check finds anything, the first
problem is shown there and every problem is logged (`clean.check_failed`). The marker is cleared either way,
because the clean did finish.

If something unexpected stops the clean partway (an error), the cleaner puts back **only the files
this run had already deleted**, taking them from the backup. It never overwrites a file that exists on disk. It
then reports that the clean stopped and how many files were restored. If that restore fails, the marker is kept
and the error names the backup.

### After an interrupted clean

If the program itself was killed mid-clean (power cut, closed window), the marker is still there next time. The
cleaner **never restores on its own**. Instead:

- The app shows a warning with when the clean started, where its WTF backup is and how to restore it by hand.
  **Dismiss (keep the backup)** removes the marker and leaves the backup in place. **Remind me next time**
  keeps both.

While that marker exists, new real cleans are refused, because they would lose track of the earlier backup.
Dry runs still work. Use Dismiss, or delete `clean-in-progress.json`, to clean again.

**To restore by hand:** close WoW, then unzip that `backup\backup-<flavor>-<stamp>.zip` **into the flavor folder** (for
example `World of Warcraft\_retail_`), keeping the folder structure. The paths inside start with `WTF\`. This
puts back the whole WTF folder as it was before that clean, so only do it if files are really missing.

### Restoring a backup

- **Some cleaned files:** close WoW, then unzip the `cleaned\cleaned-…zip` **into the flavor folder** (for example `World of Warcraft\_retail_`),
  keeping the folder structure. The paths inside the zip start with `WTF\Account\…`, so the files land back where
  they were. You can ignore `manifest.json`.
- **The whole WTF folder:** the same, with a `backup\backup-…zip` (its paths start with `WTF\`).

### Is WoW running?

Before a clean, the cleaner looks for running WoW processes and warns only about the flavor you chose. A process
belongs to a flavor when its executable sits in that flavor's folder (`_retail_`, `_classic_era_`, …).

- On Windows and WSL it reads executable paths through PowerShell. If the paths can't be read it falls back to
  process names only, and those are listed as "flavor unknown".
- On Linux (Wine) it reads `/proc`.
- On macOS it can't tell, so there is no warning.

## Screenshot Organizer

WoW drops every screenshot into one flat `Screenshots` folder per flavor. The organizer files them into
`YYYY\MM\DD` folders, separately for each flavor. The date comes from the file name only.

### Where screenshots go

There are two layouts, picked by the **destination folder** setting (press `s`):

| Destination folder | Screenshots go to | Example |
|---|---|---|
| Set (an archive folder) | `<destination>\<flavor folder>\YYYY\MM\DD` | `H:\Media\Screenshots\World of Warcraft\_retail_\2019\07\31\WoWScrnShot_073119_232713.jpg` |
| Empty (the default) | in place: `<flavor>\Screenshots\YYYY\MM\DD` | `World of Warcraft\_retail_\Screenshots\2019\07\31\WoWScrnShot_073119_232713.jpg` |

File names are never changed. Only files lying directly in a flavor's `Screenshots` folder are looked at; date
folders made by earlier runs are not read again. The destination can't be the WoW folder itself or anything
inside a flavor's `Screenshots` folder (leave it empty for that). It doesn't have to exist yet: it's created on
the first real run.

**Recognised names.** `WoWScrnShot_MMDDYY_HHMMSS` with `.jpg`, `.jpeg`, `.png` or `.tga`, in any case, and a
real calendar date (the year is `20YY`). Anything else, such as `notes.txt` or `WoWScrnShot_023119_…` (there is
no 31 February), is **left where it is** and listed under "Skipped (n): name not recognised".

### Picking flavors

The flavor screen lists only the flavors that have a `Screenshots` folder, with **All flavors** first. Your
choice (All flavors or one flavor) is pre-selected next time. If no flavor has a `Screenshots` folder, the tool
says so and goes back to the menu.

### Using the TUI

The review screen shows a tree: All flavors (or the flavor) → flavor → year → month → day → files. Every node
shows how many shots are under it, and everything starts ticked. A day's files appear when you expand it. A
progress bar shows while the scan runs. The left panel shows the destination, the mode (Move or Copy) and four
buttons: **Organize**, **Dry run**, **Rescan** and **Undo last run**. The bar at the bottom totals the ticked
shots, possible duplicates, conflicts and skipped names.

| Key | Action |
|---|---|
| `space` | Tick or untick the highlighted flavor, year, month, day or file (on a button, press it) |
| `a` / `n` | Tick all / none |
| `o` | **Organize** the ticked shots (asks for confirmation first; the dialog starts on **No**) |
| `y` | **Dry run** on the ticked shots (asks first; the dialog starts on **Yes**) |
| `r` | Rescan |
| `z` | **Undo last run** (asks first; the dialog starts on **No**) |
| `f` | Choose another flavor |
| `t` | Back to the tool menu |
| `s` | Settings |
| `q` | Quit |

`←` and `→` switch between the tree and the left panel, as on the WTF Cleaner's review screen. If nothing is
left to file, the bar says "Nothing to file." and Organize and Dry run are disabled. Settings you change take
effect at the next rescan (`r`).

While a run goes, a progress window shows the stage and the current file. The results screen then shows a
summary table (the mode, a count per outcome, and the journal) and a table of every file with its outcome,
flavor, target folder and reason. From there `r` rescans, `f` picks another flavor, `t` goes back to the tool
menu and `q` quits.

### Duplicates and conflicts

When a file with the same name is already at the target:

- **Same size** shows as a "possible duplicate" in the tree. At run time both files are compared by content
  (SHA-256). If they're identical, the screenshot in `Screenshots` is removed, because it's already filed
  ("Duplicate removed"). In copy mode it's left alone ("Already filed"). If the content differs after all, it's a
  conflict.
- **Different size** is a **conflict**. Conflicts are listed under their own read-only "Conflicts (n)" node and
  can't be ticked. Both files are left alone and you sort them out by hand.

**Nothing is ever overwritten.** The target is checked again right before each move or copy, so a file that
appears there during the run is a conflict too.

### Copy mode

With "Copy instead of move" on (in settings), screenshots are copied into the date folders and stay in
`Screenshots` as well. Every copy goes through a temporary `<name>.partial` file and is checked (size and
SHA-256) before it's renamed into place. A move to another drive works the same way, and the original is deleted
only after the copy checks out. If that delete fails, the result says "Copied, source left".

### Dry run

A dry run (the **Dry run** button or `y`) walks exactly the same checks, comparing possible duplicates by content
too, and reports what *would* happen: "Would move", "Would copy", "Would remove duplicate" or a conflict. It
creates no folders, moves nothing and writes no journal. It's recorded in the log.

### Undo

Every real run writes a **journal**, one file per run, in `<WoW folder>\wow-tools\screenshots\journal\`
(`journal-<YYYYMMDD-HHMMSS>.jsonl`). It's kept beside the WTF Cleaner's folder and never in your screenshot
archive. Each move, copy or removed duplicate is written to it the moment it happens, so it's accurate even if the
run is cut short. If the journal can't be written, the run stops before it touches anything. A run that changed
nothing leaves no journal.

**Undo last run** (`z`) reverses the newest run, newest file first:

- moved screenshots go back to their `Screenshots` folder;
- copies are deleted (only while the original is still there, at the same size);
- removed duplicates are copied back from the archive.

Undo is careful:

- It only touches a file that still matches the journal (same size). Anything that changed since, or a file of
  the same name back in `Screenshots`, is **left alone** and listed as such. Nothing is ever overwritten.
- Afterwards, `YYYY`, `MM` and `DD` folders that the run filed into are removed if they're now empty. Other
  folders are never removed.
- It goes back **one run only**. Once a run is undone, the button stays disabled until the next real run that files something; older
  journals are kept for reference, not offered.
- A journal line that doesn't point from a `Screenshots` folder in your WoW folder to a `YYYY\MM\DD` folder is
  left alone.

The newest 10 journals are kept (`keep_journals` in settings); older ones are deleted after each run. Undone
journals count towards that.

If a run stops partway (an error), the results screen shows what was done, and Undo last run can put it back when
the run left a journal. If it stopped before anything could be journaled, the message says so and Undo is not
offered for it.

## Settings (`config\`)

Each tool keeps its own settings file, next to one shared file for the suite:

| File | Holds |
|---|---|
| `config\wow-tools.cfg` | `[general]`: the WoW folder, updates and logging, shared by every tool |
| `config\wtf-cleaner.cfg` | `[wtf_cleaner]`: the WTF Cleaner's own settings |
| `config\screenshots.cfg` | `[screenshots]`: the Screenshot Organizer's own settings |

The files are created the first time they're needed. Press `s` in the app to change them, or edit them while
the app is closed. A `wow-tools.cfg` from an older version (in the main folder) is split into `config\` on the
next start, and the old file is removed.

| File · section / key | Default | Meaning |
|---|---|---|
| `wow-tools.cfg` `[general] wow_path` | (asked) | WoW folder. Stored as a Windows path so it works from Windows **and** WSL. |
| `wow-tools.cfg` `[general] last_flavor` | | Pre-selected flavor |
| `wow-tools.cfg` `[general] check_for_updates` | `true` | Check GitHub for a new version (at most once a day) |
| `wow-tools.cfg` `[general] auto_update` | `false` | Install new versions automatically on launch |
| `wow-tools.cfg` `[general] log_level` | `info` | Detail level of the readable log (`debug`, `info`, `warning`, `error`) |
| `wow-tools.cfg` `[general] log_retention_days` | `90` | Delete log files older than this |
| `wtf-cleaner.cfg` `[wtf_cleaner] max_age_days` | `90` | Age limit for `older_than` |
| `wtf-cleaner.cfg` `[wtf_cleaner] criterion_*` | `true` | Default on/off for each criterion |
| `wtf-cleaner.cfg` `[wtf_cleaner] backup_before_delete` | `true` | Zip the files to clean (`cleaned\`) before deleting |
| `wtf-cleaner.cfg` `[wtf_cleaner] backup_dir` | `<wow_path>\wow-tools\wtf-cleaner` | Holds `backup\` and `cleaned\` |
| `wtf-cleaner.cfg` `[wtf_cleaner] keep_backups` | `5` | How many WTF backups (`backup\backup-<flavor>-*.zip`) to keep per flavor |
| `wtf-cleaner.cfg` `[wtf_cleaner] last_account` | (empty = all accounts) | Pre-selected account |
| `screenshots.cfg` `[screenshots] dest_dir` | (empty = in place) | Archive root: screenshots go to `<dest_dir>\<flavor folder>\YYYY\MM\DD`. Stored as a Windows path. |
| `screenshots.cfg` `[screenshots] copy_mode` | `false` | Copy instead of move |
| `screenshots.cfg` `[screenshots] last_flavor_choice` | (empty = all flavors) | Pre-selected flavor choice, e.g. `_retail_` |
| `screenshots.cfg` `[screenshots] keep_journals` | `10` | How many run journals to keep (at least 1) |

## Updates

On launch the suite checks GitHub Releases in the background, at most once a day. If a newer version exists,
the app shows it in the bottom bar (press `u`).

- `wow-tools update --check` (`./wow-tools.sh update --check` or `wow-tools.cmd update --check`) reports whether
  an update is available.
- `wow-tools update` installs it. A git clone is fast-forwarded to the release tag, and it refuses if
  you have local changes. A zip install downloads the release and replaces the program files, keeping a copy
  in `.update-backup\` and rolling back if anything fails. Your `config\`, `logs\` and backups are never
  touched.

Set `auto_update = true` to install updates on launch without asking.

## Logs

Everything the tools do is logged, including settings changes, your choices, scan results, backups, and every
file deleted, moved or skipped. Each tool has its own folder, `logs\wtf-cleaner\` and `logs\screenshots\`
(the launcher uses `logs\suite\`):

- `logfile-YYYY-MM-DD.log` is readable.
- `events-YYYY-MM-DD.log` is structured, one JSON object per line.

The format is described in [docs/events.md](docs/events.md).

## One copy at a time

Only one copy of Ka0s WoW Tools runs at a time. While it's open it holds a lock file, `wow-tools.lock`, in this
folder, and it removes the file when it closes. If you start a second copy (or the last one crashed and left the
file behind), you get a warning naming the process that holds the lock, with two choices:

- **Quit** (the default), if the other copy really is open.
- **Override and continue**, if it isn't, for example after a crash. When the process is known to be gone, the
  warning says so and this button is focused.

`wow-tools update` asks the same question on the terminal.

## Windows and WSL together

The same folder works from both. Paths are stored in Windows form (`G:\Games\…`) and translated to
`/mnt/g/Games/…` automatically under WSL.

## Troubleshooting

- **"No WoW flavor folders were found"**: choose the `World of Warcraft` folder itself, not `_retail_`.
- **"Refusing to scan"**: that flavor has no addons installed. Nothing is proposed, on purpose.
- **Files come back after cleaning**: WoW was running. Close it and clean again.
- **"files are locked by another program"**: close the Raider.IO client (or WeakAuras Companion), then clean
  again. Nothing was deleted.
- **"Ka0s WoW Tools may already be running"**: see [One copy at a time](#one-copy-at-a-time).
- **"An earlier clean did not finish"**: see [After an interrupted clean](#after-an-interrupted-clean).
- **"No Screenshots folders found"**: no flavor has a `Screenshots` folder yet. Take a screenshot in game first.
- **A screenshot stays in `Screenshots` after organizing**: its name isn't a WoW screenshot name, or a different
  file with the same name is already filed (a conflict). Both show in the tree and on the results screen.
- **Python not found on Windows**: install Python 3.10+ from python.org and tick "Add to PATH".

## For developers

See [docs/architecture.md](docs/architecture.md), [docs/adding-a-tool.md](docs/adding-a-tool.md),
[docs/vendoring.md](docs/vendoring.md), [docs/releasing.md](docs/releasing.md) and
[docs/events.md](docs/events.md). Run the tests with `python3 scripts/run_tests.py` (in parallel), or
`python3 -m unittest discover -s tests -t .` (one process).
