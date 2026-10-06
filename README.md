# Ka0s WoW Tools

![Version](https://img.shields.io/badge/Version-0.1.0-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)
![Platforms](https://img.shields.io/badge/Platforms-Windows_%7C_macOS_%7C_Linux-purple)
![Tests](https://img.shields.io/badge/Tests-1284%2F1284_passing-green)
![License](https://img.shields.io/badge/License-MIT-orange)

Ka0s WoW Tools is a small set of World of Warcraft helpers that run ***outside*** the game and tidy up the files WoW
leaves lying around on your computer. It's a single app - you open it, pick a tool from the menu, and when you're done
you land back on the menu.

**_The tool menu_**

![The tool menu](docs/assets/screenshot-01.png)

## The tools

| Tool | What it does | Guide |
|---|---|---|
| **WTF Cleaner** | Finds settings files left behind by addons you no longer use, backs them up, and deletes them. | [WTF Cleaner guide](docs/wtf-cleaner.md) |
| **Screenshot Organizer** | Sorts your WoW screenshots into folders by year, month and day, one set per game version. | [Screenshot Organizer guide](docs/screenshot-organizer.md) |
| **Interface Backup** | Zips a game version's `Interface` and `WTF` folders (your addons and their settings), and puts them back from a zip. | [Interface Backup guide](docs/interface-backup.md) |
| **Ace3 Profile Manager** | Shows the profiles of every addon built on Ace3 and which characters use them, and lets you delete, rename and copy profiles or move characters between them. | [Ace3 Profile Manager guide](docs/ace3-profile-manager.md) |

Every tool works with every version of the game you have installed: Retail, Classic, Classic Era, Anniversary,
and the PTR and Beta clients. You can work on one version at a time or all of them at once.

No tool changes anything until you say so. Each one shows you what it will do first and asks before it
touches a file. The WTF Cleaner, the Screenshot Organizer and the Ace3 Profile Manager can also do a practice run
(a **Dry run**) that shows what would happen without changing anything. And if you change your mind afterwards, you
can undo the last clean, the last sort, the last restore or the last profile change.

## Terms of use

Terms of use: Ka0s WoW Tools is provided as is, without warranty of any kind, and you use it at your own risk. Every
tool backs up the files it changes before changing them, but keep your own backups of anything you can't afford to
lose.

The tool menu shows these terms along its bottom. They say in plain words what the [MIT License](LICENSE) says: the
software comes with no warranty.

## Screenshots

**_WTF Cleaner: the list of leftover addon settings, ready to clean_**

![WTF Cleaner review screen](docs/assets/screenshot-02-wtfcleaner-main.png)

**_Screenshot Organizer: screenshots grouped by day, ready to sort_**

![Screenshot Organizer review screen](docs/assets/screenshot-05-screenshot-organizer-main.png)

Every tool looks and works the same way: a panel on the left with its settings and buttons, a tree on the right
with what it found (tick what you want), and a bar at the bottom that totals your choice. Before it changes
anything, a window asks you to confirm. More pictures of every screen are in each tool's guide.

## What you need

You need the following:

1. **World of Warcraft**, duh!
2. **Python 3.10 or newer.** Python is a free program language and interpreter which runs these tools. You install it once.

### Installing Python

**Windows**

1. Go to [python.org/downloads](https://www.python.org/downloads/) and click the big **Download Python** button.
2. Open the file you downloaded.
3. On the first screen, tick **Add python.exe to PATH** (don't skip this one), then click **Install Now**.

You can also get Python from the Microsoft Store: search for "Python 3.12" (or newer) and click **Get**.

**Mac**

1. Go to [python.org/downloads](https://www.python.org/downloads/) and click **Download Python**.
2. Open the downloaded `.pkg` file and follow the steps.

**Linux**

Most Linux systems already have Python. To check, open a terminal and type `python3 --version`. If it shows
3.10 or higher, you're set. If not, install it with your system's package manager, for example:

- Ubuntu or Debian: `sudo apt install python3`
- Fedora: `sudo dnf install python3`
- Arch: `sudo pacman -S python`

**Check that it worked.** Open a terminal (on Windows: press the Windows key, type `cmd`, press Enter) and
type `python --version` on Windows or `python3 --version` on Mac and Linux. You should see something like
`Python 3.12.4`.

That's the only thing you install. Everything else the tools need comes in the download.

## Getting Ka0s WoW Tools

1. Go to the [Releases page](https://github.com/tusharsaxena/wow-tools/releases).
2. Under the newest version, download the **wow-tools-vX.Y.Z.zip** file (X.Y.Z is the version number).
3. Unzip it anywhere you like, for example `Documents\wow-tools`.

If you use git, you can clone it instead, which makes updates a single command:
`git clone https://github.com/tusharsaxena/wow-tools.git`

## Getting started

### Running the app

| On | Do this |
|---|---|
| Windows | Double-click `wow-tools.cmd` in the folder you unzipped |
| Mac and Linux | Open a terminal in that folder and type `./wow-tools.sh` |

> **Tip for Windows:** make a shortcut so you don't have to open the folder every time. Right-click
> `wow-tools.cmd`, choose **Show more options**, then **Send to → Desktop (create shortcut)**. Double-click the
> shortcut to start the app. You can also right-click the shortcut and pick **Pin to Start**.

### Navigating the app

The app opens in a terminal window. You drive it with the keyboard:

| Key | Does |
|---|---|
| `↑` `↓` | Move up and down |
| `Enter` | Choose |
| `x` `c` | Expand or collapse every line of a tree |
| `/` | Filter a tree: type part of a name, `Enter` keeps the filter, `Esc` clears it |
| `a` `n` | Tick or untick everything the tree shows |
| `c` (tool menu) | What's new: the changelog |
| `Esc` | Go back |
| `s` | Settings |
| `q` | Quit |

Each screen lists its keys along the bottom, so you don't have to remember them. A mouse works too. While a tool is
changing or writing files (a clean, a sort, a backup, a restore, a profile change or an undo), the app won't quit until it has
finished.

Buttons are coloured by what they do, the same in every tool: **red** deletes, **amber** overwrites or changes
files, **green** adds something new (a backup, an Ace3 profile copy), **violet** undoes, **cyan** is a dry run
that changes nothing, **blue** confirms (Save, OK), **grey** moves between screens or rescans, and **dim grey** backs
out (Cancel, Back, Quit).

Every "are you sure?" window opens with **Yes** selected, coloured the same way: red when it deletes, overwrites,
undoes or throws away pending changes, cyan for a dry run. A backup's is red when older backups are deleted to
keep the number you set, green only when every backup is kept. So read it before you press Enter.
For a quarter of a second after it opens, Enter and Space do nothing there, and a key you are still holding is
ignored until you let it go, so it can't answer for you (the update offer's **Update now** waits the same way). `y` answers Yes, `n` or `Esc` No.

### Terminal size

The app is laid out for the window Windows Terminal (the default on Windows 11) opens: 120 columns by 30 lines.
Maximize the window and the lists and tables grow to fill it. A smaller window still works, but it's cramped and
you'll scroll more (on the tool menu the banner shrinks to one line when the tools need its room, and the tool list
scrolls, so the terms of use and the keys at the bottom stay in view).

### The first time

The first time you open a tool, it asks for two things:

1. **Your World of Warcraft folder.** This is the folder that holds `_retail_`, `_classic_` and so on, for
   example `C:\Program Files (x86)\World of Warcraft`. The app looks in the usual places and suggests what it
   finds (this can take a few seconds; you can type the folder meanwhile). You only answer this once; every tool shares it.
   The same screen asks how many backups to keep per game version (10; 0 keeps them all), how many journals
   each tool keeps (10) and how many game versions to work on at once (2; use 1 on a hard drive or a WSL `/mnt`
   folder). All three apply to every tool.
2. **That tool's settings.** Each guide explains them. If you're not sure, keep the suggested values.

Then you pick which version of the game to work on, or **All flavors** for every version at once. ("Flavor" is
WoW's word for a game version such as Retail or Classic.)

## Tool guides

Each tool has its own guide, with pictures, that walks through every screen:

- [WTF Cleaner guide](docs/wtf-cleaner.md): clean out old addon settings safely, and undo a clean.
- [Screenshot Organizer guide](docs/screenshot-organizer.md): sort screenshots into dated folders, and undo a
  run.
- [Interface Backup guide](docs/interface-backup.md): back up your addons and their settings, restore them, and
  undo a restore.
- [Ace3 Profile Manager guide](docs/ace3-profile-manager.md): tidy up Ace3 addon profiles, move characters between them,
  and undo a change.

## Updates

The app checks for a new version once a day while it's open. If there is one, the bottom bar says so (at its right
end, next to the version you have), and so does the line under the banner on the tool menu; press `u` to install it. On the Ace3 Profile Manager's review `u` unlocks an
addon, so there (and while a text box has focus, where `u` types the letter) the bar tells you to press `u` on the
tool menu instead. Before it tells you about a version, and again when you press `u`, the app asks GitHub; if that version has been
withdrawn, the app says there is no update and the notice goes away. A small window stays up while it downloads and installs, then the app closes so you can start the
new version. You can also update from a terminal in the app's folder:

- `wow-tools update --check` (on Windows `wow-tools.cmd update --check`, on Mac and Linux
  `./wow-tools.sh update --check`) tells you whether an update is available.
- `wow-tools update` installs it.

Before installing, the app checks that the download is exactly the file that was published with that version
(its checksum, listed in the release's `SHA256SUMS` file). If it doesn't match, nothing is changed. If a release
has no `SHA256SUMS` file, the update is refused and you're pointed to the Releases page to download it yourself.
If you'd rather update anyway in that case, add `allow_unverified_updates = true` under `[general]` in
`config\wow-tools.cfg` (it starts as `false`; leaving it that way is safer).

Updating never touches your settings, logs or backups, or files you put directly in the app's folder (notes, say).
The app's own folders (`wowtools`, `vendor`, `scripts` and `docs`) are replaced as a whole, so don't keep your own
files in them. If an update fails partway, the app puts the old version back. A copy of the version you replaced is
kept in the `.update-backup` folder; only two are kept (the one this update made and the newest other one).

If you cloned with git, the update is a fast-forward to the new version. It stops if you've edited the app's own
files, but files you added yourself (notes, say) don't get in its way. It never waits for a password: if git
would ask for one, or takes more than two minutes, the update stops and tells you why.

## Your settings

Your answers are saved in the `config` folder inside the app's folder, one file per tool:

| File | Holds |
|---|---|
| `config\wow-tools.cfg` | Shared by every tool (`[general]`): your WoW folder, how many backups to keep per game version (`keep_backups`, 10; 0 keeps all) and journals per tool (`keep_journals`, 10), how many game versions to work on at once (`parallelism`, 2, from 1 to 8; use 1 on a hard drive or a WSL `/mnt` folder, where working on several at once is slower), plus update and log options |
| `config\wtf-cleaner.cfg` | The WTF Cleaner's settings |
| `config\screenshot-organizer.cfg` | The Screenshot Organizer's settings |
| `config\interface-backup.cfg` | Interface Backup's settings |
| `config\ace3-profile-manager.cfg` | The Ace3 Profile Manager's settings (`[ace3_profile_manager]`): backup folder and the blacklist of addons (each in one game version) it never changes |

The easiest way to change them is to press `s` in the app: the first screen is the shared one (WoW folder,
backups and journals to keep, game versions to work on at once), then the tool's own. You can also open the files in Notepad while the app
is closed. The guides list every setting.

## Undo and run journals

Every tool that changes files keeps a short record of what it did, called a **journal**, so it can undo its last
run: the WTF Cleaner's last clean, the Screenshot Organizer's last sort, Interface Backup's last restore and the Ace3
Profile Manager's last change. Journals are kept in your WoW folder, under `wow-tools\<tool name>\journal` (for
example `wow-tools\ace3-profile-manager\journal`). Each tool's guide explains its undo.

## Logs

The app writes down everything it does, down to every file it deletes or moves. The logs are in the `logs`
folder, one folder per tool, and the `logfile-<date>.log` files are plain text you can open in Notepad. They're
kept for 90 days. If you ever need to report a problem, send these along.

## Windows and WSL

If you use WSL (Linux inside Windows), the same folder works from both sides. Run `./wow-tools.sh` from WSL or
`wow-tools.cmd` from Windows; your settings carry over.

## FAQ

| Question | Answer |
|----------|--------|
| Is it safe? Can I lose anything? | Every tool shows you what it will do and asks before it changes anything. The WTF Cleaner backs up your whole `WTF` folder and zips every file before deleting it, the Screenshot Organizer never overwrites a file, Interface Backup takes a safety backup of your folders before every restore, and the Ace3 Profile Manager backs up your whole `WTF` folder and every file it edits before changing a profile. Each can undo its last run (Interface Backup: its last restore). If you're unsure, press **Dry run** in the WTF Cleaner, the Screenshot Organizer or the Ace3 Profile Manager first: it shows what would happen without changing anything. |
| Does it change the game itself? | No. It never touches the game program. The WTF Cleaner and the Screenshot Organizer only work on files the game leaves in your WoW folder: addon settings in `WTF` and pictures in `Screenshots`. Interface Backup only reads your `Interface` and `WTF` folders to back them up; they change only when you restore a backup (or undo a restore) and confirm it. The Ace3 Profile Manager only changes the profile lists in addon settings files in `WTF`, and only when you apply and confirm. |
| Do I need to close WoW? | Close it before you clean with the WTF Cleaner: WoW rewrites those files when you log out and can bring deleted ones back. Close it before an Interface Backup restore or undo too; a backup works with the game open but may miss your latest settings. The WTF Cleaner and Interface Backup warn you if WoW is running. The Ace3 Profile Manager refuses to apply or undo a change while WoW is running, since the game would overwrite it. The Screenshot Organizer doesn't mind if the game is open. |
| Do I need to install anything besides Python? | No. Everything else the app needs comes in the download. |
| Does it work on a Mac? | Yes, with `./wow-tools.sh`. The only thing missing on a Mac is the "WoW is running" warning, so close WoW yourself before cleaning or restoring. |
| Why does it say another copy may already be running? | Only one copy of the app can run at once. While it's open it keeps a small file called `wow-tools.lock` in its folder. If you start it a second time, or it crashed last time, you get a warning with two buttons: **Quit** if the app really is open somewhere else, or **Override and continue** if it isn't (for example after a crash). When the app can tell the other copy is gone, it says so and puts you on **Override and continue**. |
| Can I work on all my game versions at once? | Yes. Pick **All flavors** at the top of the list, in any tool. |
| Where are my settings, backups and logs? | Settings are in the app's `config` folder and logs in its `logs` folder. Backups and undo journals are in your WoW folder, under `wow-tools`. See [Your settings](#your-settings) and the guides. |
| How do I update? | The app tells you on its bottom bar when a new version is out; press `u`. See [Updates](#updates). |
| How do I uninstall it? | Delete the app's folder. If you also want the backups and undo journals gone, delete the `wow-tools` folder inside your WoW folder. Nothing else is installed anywhere. |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Python was not found", or nothing happens when I double-click `wow-tools.cmd` | Python isn't installed, or **Add python.exe to PATH** wasn't ticked. Run the Python installer again, choose **Modify**, and tick it. |
| "No WoW flavor folders were found" | Pick the `World of Warcraft` folder itself, not `_retail_` inside it. |
| "Ka0s WoW Tools may already be running" | See *Why does it say another copy may already be running?* in the [FAQ](#faq). |
| The window looks garbled or too small | Make the terminal window bigger (at least 120 columns by 30 lines; see [Terminal size](#terminal-size)), or use Windows Terminal (the default on Windows 11). |
| It's very slow on WSL | WSL (Linux inside Windows) is slow at reading files on Windows drives such as `C:` or `G:`: every file takes a moment to check, and a WoW folder has thousands of them. Start the app from Windows instead, by double-clicking `wow-tools.cmd`. It uses the same settings, so nothing needs setting up again. If you stay on WSL, give the first scan time; the progress bar shows it's still working, and set "Game versions to work on at once" to 1 in the general settings (`s` on the tool menu). |
| The app offers an update to a version that doesn't exist | The release was withdrawn after the app saw it. Restart the app or press `u`: either checks GitHub again, finds no update and drops the notice. |
| A tool does something unexpected | See the troubleshooting table at the end of that tool's guide. |
| Something looks wrong and I want to report it | Follow [Reporting a bug](#reporting-a-bug) below. |

## Reporting a bug

- Note what you did and what you expected to happen.
- Open the `logs` folder inside the app's folder, then the folder of the tool you were using (for example
  `logs\wtf-cleaner`).
- Attach that day's `logfile-<date>.log` and `events-<date>.log` to your report.

The logs list every step the app took, so they usually show what went wrong.

## Issues and feature requests

Bugs, ideas and planned work all go in the GitHub issue tracker:
[https://github.com/tusharsaxena/wow-tools/issues](https://github.com/tusharsaxena/wow-tools/issues).
Please file reports there, so nothing gets lost.

## Version History

What changed in each version is in [CHANGELOG.md](CHANGELOG.md), newest first. The app shows it too: press `c` on
the tool menu for every version on the left (yours marked "current") and its notes on the right; `Esc` goes back.

## Credits

The app's screens are built with [Textual](https://github.com/Textualize/textual) and
[Rich](https://github.com/Textualize/rich) by Textualize (MIT license). They ship inside the app, together with
the small libraries they use: Pygments (BSD 2-Clause), markdown-it-py, mdit-py-plugins, mdurl, linkify-it-py and
platformdirs (all MIT), and typing_extensions (PSF license).

## License

Ka0s WoW Tools is released under the [MIT License](LICENSE). You're free to use, copy, change and share it.
