<p align="center"><img src="docs/assets/ka0s-logo.png" alt="Ka0s" width="220"></p>

# Ka0s WoW Tools

Out-of-game companion tools for World of Warcraft. The tools share one settings file, one set of
bundled libraries and one look, and they run straight from this folder on Windows, Linux and WSL.
There's no `pip install` and no virtualenv.

| Tool | What it does |
|---|---|
| **WTF Cleaner** (`wtf-cleaner`) | Finds SavedVariables left behind by addons you no longer use, backs them up to a zip, and deletes them. |
| Screenshot Organizer | Coming later. |

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

| Platform | WTF Cleaner | Tool menu |
|---|---|---|
| Windows | double-click `wtf-cleaner.cmd` | `wow-tools.cmd` |
| Linux / WSL | `./wtf-cleaner.sh` | `./wow-tools.sh` |
| Anywhere | `python -m wowtools wtf-cleaner` (from this folder) | `python -m wowtools` |

**First launch.** A short setup asks for:

1. **Your World of Warcraft folder.** This is the folder that contains `_retail_`, `_classic_` and so on.
   Common locations on every drive are detected for you.
2. **WTF Cleaner settings.** These are the age limit, which criteria to use, whether to back up before deleting,
   and the **backup folder**. Leave the backup folder empty to use `<WoW folder>\wow-tools\wtf-cleaner`.

Your answers are saved in `wow-tools.cfg` next to this README. Then you pick a **flavor**, and the last one you
used is pre-selected next time. If the flavor has more than one WoW account, you then pick an **account**, or
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
- **One account** (picked on the account screen, or `--account NAME` on the command line): only that account's
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

While a clean runs, a progress window shows the current stage (safety snapshot, backup, verify, delete), a
percentage bar and the current file. The results screen then shows a summary table and a table of every file
with its status, account, character, addon, size and reasons.

#### Keyboard use

Every screen works without a mouse, and each one shows a one-line hint with its keys.

| Key | Action |
|---|---|
| `↑` / `↓`, `Tab` / `Shift+Tab` | Move between fields and buttons |
| `←` / `→` | Move between the buttons in a row |
| `Enter` or `Space` | Press the focused button, or tick the focused checkbox |
| `Esc` | Go back or cancel |

The tree, lists, tables and text boxes keep the arrow keys for themselves while they have focus. Use `Tab` to
leave them.

### Dry run

A dry run (the **Dry run** button, `y`, or `--dry-run`) writes and verifies the backup zip, exactly as a real
clean would, and then deletes nothing. It reports what *would* be deleted, and it's recorded in the log. It
takes no safety snapshot. If backups are turned off, a dry run writes nothing at all.

### Backups

The backup folder is a WTF Cleaner setting (press `s`, then the WTF Cleaner settings screen). By default it is
`<WoW folder>\wow-tools\wtf-cleaner`. `--backup-dir PATH` overrides it for one command-line run.

Before deleting, the cleaner writes
`<backup folder>\wtf-cleaner_<flavor>_<YYYYMMDD-HHMMSS>.zip`, then re-opens it and checks every file.
**If the backup can't be written or verified, nothing is deleted.** Each zip contains a
`manifest.json` that lists every file, its size and why it was removed. You can turn backups off in settings,
or with `--no-backup --yes` on the command line, but it isn't recommended.

### Safety snapshot

A real clean (not a dry run) also protects you against a crash halfway through. Before deleting anything it:

1. zips the **whole** `<flavor>\WTF` folder to `<backup folder>\wtf-snapshot_<flavor>_<YYYYMMDD-HHMMSS>.zip`
   and verifies it;
2. writes a marker file, `<backup folder>\clean-in-progress.json`, that names the snapshot and the files about
   to be deleted.

If the snapshot can't be written, the clean stops and nothing is deleted. When the clean finishes, including
when a few files could not be deleted, the snapshot and the marker are removed again.

If something unexpected stops the clean partway (an error, or `Ctrl+C`), the cleaner puts back **only the files
this run had already deleted**, taking them from the snapshot. It never overwrites a file that exists on
disk. It then reports that the clean stopped and how many files were restored. If that restore fails, the marker and the snapshot are
kept and the error names the snapshot.

### After an interrupted clean

If the program itself was killed mid-clean (power cut, closed window), the marker is still there next time. The
cleaner **never restores on its own**. Instead:

- The TUI shows a warning with when the clean started, where the snapshot is and how to restore it by hand.
  **Dismiss (keep the snapshot)** removes the marker and leaves the snapshot in place. **Remind me next time**
  keeps both.
- The command line prints the same message to stderr.

While that marker exists, new real cleans are refused, because they would lose track of the earlier snapshot.
Dry runs still work. Use Dismiss, or delete `clean-in-progress.json`, to clean again.

**To restore by hand:** close WoW, then unzip `wtf-snapshot_<flavor>_*.zip` **into the flavor folder** (for
example `World of Warcraft\_retail_`), keeping the folder structure. The paths inside start with `WTF\`. This
puts back the whole WTF folder as it was before that clean, so only do it if files are really missing. Delete the
snapshot once you no longer need it.

### Restoring a backup

Close WoW, then unzip the backup **into the flavor folder** (for example `World of Warcraft\_retail_`), keeping
the folder structure. The paths inside the zip start with `WTF\Account\…`, so the files land back where they
were. You can ignore `manifest.json`.

### Command line

Every flag also works through `wtf-cleaner.cmd` / `wtf-cleaner.sh`.

```
python -m wowtools wtf-cleaner --flavor retail                     # show the proposal (read-only)
python -m wowtools wtf-cleaner --flavor retail --clean             # back up + delete, asks y/N
python -m wowtools wtf-cleaner --flavor retail --clean --dry-run   # write the backup, delete nothing
python -m wowtools wtf-cleaner --flavor retail --account ME        # one account only
python -m wowtools wtf-cleaner --flavor classic_era --clean --yes  # no prompt (for scripts)
python -m wowtools wtf-cleaner --flavor retail --json --criteria not_installed,stray_copies
```

| Flag | Meaning |
|---|---|
| `--flavor NAME` | `retail`, `classic`, `classic_era`, `anniversary`, … (default: last used) |
| `--account NAME` | Scan and clean only this account (any case). Default: all accounts. |
| `--clean` | Back up and delete the proposal (asks first) |
| `--yes` | Don't ask |
| `--dry-run` | Write and verify the backup zip, but delete nothing |
| `--no-backup` | Skip the zip (only with `--yes`) |
| `--max-age DAYS` | Override the age limit |
| `--criteria LIST` | Comma list of `not_installed,not_enabled,older_than,stray_copies` |
| `--wow-path PATH` / `--backup-dir PATH` | Override the configured folders for this run |
| `--json` | Machine-readable output (`--clean --json` also needs `--yes` or `--dry-run`) |
| `--tui` | Open the TUI even when other flags are given |

The text proposal starts with a `Scope: <flavor> · <account|all accounts>` line.

Exit codes: `0` ok · `1` usage or config problem (including an unknown `--account`), or a clean stopped by an unexpected error · `2` scan refused
(e.g. no addons installed) · `3` finished but some files could not be deleted · `4` backup or safety snapshot
failed, or an earlier clean is unresolved (nothing deleted).

### Is WoW running?

Before a clean, the cleaner looks for running WoW processes and warns only about the flavor you chose. A process
belongs to a flavor when its executable sits in that flavor's folder (`_retail_`, `_classic_era_`, …).

- On Windows and WSL it reads executable paths through PowerShell. If the paths can't be read it falls back to
  process names only, and those are listed as "flavor unknown".
- On Linux (Wine) it reads `/proc`.
- On macOS it can't tell, so there is no warning.

## Settings (`wow-tools.cfg`)

The file is created on first launch. Press `s` in the TUI to change the common settings, or edit the file
directly while no tool is running.

| Section / key | Default | Meaning |
|---|---|---|
| `[general] wow_path` | (asked) | WoW folder. Stored as a Windows path so it works from Windows **and** WSL. |
| `[general] last_flavor` | | Pre-selected flavor |
| `[general] check_for_updates` | `true` | Check GitHub for a new version (at most once a day) |
| `[general] auto_update` | `false` | Install new versions automatically on launch |
| `[general] log_level` | `info` | Detail level of the readable log (`debug`, `info`, `warning`, `error`) |
| `[general] log_retention_days` | `90` | Delete log files older than this |
| `[wtf_cleaner] max_age_days` | `90` | Age limit for `older_than` |
| `[wtf_cleaner] criterion_*` | `true` | Default on/off for each criterion |
| `[wtf_cleaner] backup_before_delete` | `true` | Zip before deleting |
| `[wtf_cleaner] backup_dir` | `<wow_path>\wow-tools\wtf-cleaner` | Where backup zips and safety snapshots go |
| `[wtf_cleaner] last_account` | (empty = all accounts) | Pre-selected account |

## Updates

On launch the suite checks GitHub Releases in the background, at most once a day. If a newer version exists,
the TUI shows it in the bottom bar (press `u`) and the command line prints a one-line notice.

- `python -m wowtools update --check` reports whether an update is available.
- `python -m wowtools update` installs it. A git clone is fast-forwarded to the release tag, and it refuses if
  you have local changes. A zip install downloads the release and replaces the program files, keeping a copy
  in `.update-backup\` and rolling back if anything fails. Your `wow-tools.cfg`, `logs\` and backups are never
  touched.

Set `auto_update = true` to install updates on launch without asking.

## Logs

Everything the tools do is logged in `logs\`, including settings changes, your choices, scan results, backups,
and every file deleted or skipped:

- `wow-tools-YYYY-MM-DD.log` is readable.
- `events-YYYY-MM-DD.jsonl` is structured, one JSON object per line.

The format is described in [docs/events.md](docs/events.md).

## Windows and WSL together

The same folder works from both. Paths are stored in Windows form (`G:\Games\…`) and translated to
`/mnt/g/Games/…` automatically under WSL.

## Troubleshooting

- **"No WoW flavor folders were found"**: choose the `World of Warcraft` folder itself, not `_retail_`.
- **"Refusing to scan"**: that flavor has no addons installed. Nothing is proposed, on purpose.
- **Files come back after cleaning**: WoW was running. Close it and clean again.
- **"An earlier clean did not finish"**: see [After an interrupted clean](#after-an-interrupted-clean).
- **Python not found on Windows**: install Python 3.10+ from python.org and tick "Add to PATH".

## For developers

See [docs/architecture.md](docs/architecture.md), [docs/adding-a-tool.md](docs/adding-a-tool.md),
[docs/vendoring.md](docs/vendoring.md), [docs/releasing.md](docs/releasing.md) and
[docs/events.md](docs/events.md). Run the tests with `python3 -m unittest discover -s tests -t .`.
