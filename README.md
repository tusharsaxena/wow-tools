# Ka0s WoW Tools

Ka0s WoW Tools is a small set of World of Warcraft helpers that run outside the game and tidy up the files WoW
leaves lying around on your computer. It's one app. You open it, pick a tool from the menu, and when you're done
you land back on the menu.

![The tool menu](docs/assets/screenshot-01.png)

## The tools

| Tool | What it does | Guide |
|---|---|---|
| **WTF Cleaner** | Finds settings files left behind by addons you no longer use, backs them up, and deletes them. | [WTF Cleaner guide](docs/wtf-cleaner.md) |
| **Screenshot Organizer** | Sorts your WoW screenshots into folders by year, month and day, one set per game version. | [Screenshot Organizer guide](docs/screenshot-organizer.md) |

Both tools work with every version of the game you have installed: Retail, Classic, Classic Era, Anniversary,
and the PTR and Beta clients. You can work on one version at a time or all of them at once.

Neither tool changes anything until you say so. Each one shows you the full list first and asks before it
touches a file. If you'd rather see what would happen first, do a practice run (a **Dry run**). And if you
change your mind afterwards, you can undo the last run.

## What you need

You need two things:

1. **World of Warcraft**, installed in the usual way.
2. **Python 3.10 or newer.** Python is a free program that runs these tools. You install it once.

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
2. Under the newest version, download the **Source code (zip)** file.
3. Unzip it anywhere you like, for example `Documents\wow-tools`.

If you use git, you can clone it instead, which makes updates a single command:
`git clone https://github.com/tusharsaxena/wow-tools.git`

## Starting it

| On | Do this |
|---|---|
| Windows | Double-click `wow-tools.cmd` in the folder you unzipped |
| Mac and Linux | Open a terminal in that folder and type `./wow-tools.sh` |

> **Tip for Windows:** make a shortcut so you don't have to open the folder every time. Right-click
> `wow-tools.cmd`, choose **Show more options**, then **Send to → Desktop (create shortcut)**. Double-click the
> shortcut to start the app. You can also right-click the shortcut and pick **Pin to Start**.

The app opens in a terminal window. You drive it with the keyboard:

| Key | Does |
|---|---|
| `↑` `↓` | Move up and down |
| `Enter` | Choose |
| `Esc` | Go back |
| `s` | Settings |
| `q` | Quit |

Each screen lists its keys along the bottom, so you don't have to remember them. A mouse works too.

### The first time

The first time you open a tool, it asks for two things:

1. **Your World of Warcraft folder.** This is the folder that holds `_retail_`, `_classic_` and so on, for
   example `C:\Program Files (x86)\World of Warcraft`. The app looks in the usual places and suggests what it
   finds. You only answer this once; every tool shares it.
2. **That tool's settings.** Each guide explains them. If you're not sure, keep the suggested values.

Then you pick which version of the game to work on, or **All flavors** for every version at once. ("Flavor" is
WoW's word for a game version such as Retail or Classic.)

## Tool guides

Each tool has its own guide, with pictures, that walks through every screen:

- [WTF Cleaner guide](docs/wtf-cleaner.md): clean out old addon settings safely, and undo a clean.
- [Screenshot Organizer guide](docs/screenshot-organizer.md): sort screenshots into dated folders, and undo a
  run.

## Updates

The app checks for a new version once a day while it's open. If there is one, the bottom bar says so; press `u`
to install it. You can also update from a terminal in the app's folder:

- `wow-tools update --check` (on Windows `wow-tools.cmd update --check`, on Mac and Linux
  `./wow-tools.sh update --check`) tells you whether an update is available.
- `wow-tools update` installs it.

Updating never touches your settings, logs or backups. If an update fails partway, the app puts the old version
back.

## Your settings

Your answers are saved in the `config` folder inside the app's folder, one file per tool:

| File | Holds |
|---|---|
| `config\wow-tools.cfg` | Your WoW folder, plus update and log options, shared by every tool |
| `config\wtf-cleaner.cfg` | The WTF Cleaner's settings |
| `config\screenshot-organizer.cfg` | The Screenshot Organizer's settings |

The easiest way to change them is to press `s` in the app. You can also open the files in Notepad while the app
is closed. The guides list every setting.

## Undo and run journals

Every tool that changes files keeps a short record of what it did, called a **journal**, so it can undo its last
run. Journals are kept in your WoW folder, under `wow-tools\<tool name>\journal`. Each tool's guide explains its
undo.

## Logs

The app writes down everything it does, down to every file it deletes or moves. The logs are in the `logs`
folder, one folder per tool, and the `logfile-<date>.log` files are plain text you can open in Notepad. They're
kept for 90 days. If you ever need to report a problem, send these along.

## One copy at a time

Only one copy of the app can run at once. While it's open, it keeps a small file called `wow-tools.lock` in its
folder. If you start it a second time, or it crashed last time, you'll see a warning with two buttons:

- **Quit** if the app really is open somewhere else.
- **Override and continue** if it isn't, for example after a crash.

## Windows and WSL

If you use WSL (Linux inside Windows), the same folder works from both sides. Run `./wow-tools.sh` from WSL or
`wow-tools.cmd` from Windows; your settings carry over.

## Troubleshooting

- **"Python was not found" or nothing happens on Windows.** Python isn't installed, or **Add python.exe to PATH**
  wasn't ticked. Run the Python installer again, choose **Modify**, and tick it.
- **"No WoW flavor folders were found."** Pick the `World of Warcraft` folder itself, not `_retail_` inside it.
- **"Ka0s WoW Tools may already be running."** See [One copy at a time](#one-copy-at-a-time).
- **The window looks garbled or too small.** Make the terminal window bigger, or use Windows Terminal, which
  is the default on Windows 11.
- For tool-specific problems, see the troubleshooting section at the end of each guide.

## Version history

| Version | Date | What changed |
|---|---|---|
| 1.0.0 | 2026-10-03 | First release. The **WTF Cleaner** finds and removes old addon settings, with backups, a dry run, All flavors and **Undo last clean**. The new **Screenshot Organizer** sorts screenshots into year, month and day folders, with a dry run, copy mode, duplicate checks and **Undo last run**. Both tools work with every installed game version, and the app checks for updates and installs them. |
