# Changelog

Every change to Ka0s WoW Tools that you'd notice, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version numbers follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-09

The first release: five tools for the files World of Warcraft keeps on your disk, in one app.

### Added

- **WTF Cleaner** finds the settings that addons you no longer use left behind in your WTF folder. You review
  them, it zips them up, then deletes them. A blacklist keeps the addons you care about out of it.
- **Screenshot Organizer** files your screenshots into year, month and day folders, in place or into an archive
  folder, and checks for duplicates on the way.
- **Interface Backup** zips a game version's `Interface` and `WTF` folders and restores either one exactly as it
  was.
- **Ace3 Profile Manager** shows which characters use which Ace3 profile. You can delete, rename, copy and
  reassign profiles, and clear out characters that no longer exist.
- **Saved Variables Browser** opens any SavedVariables file as a tree you can edit. Search finds a key or a value
  across every file, and you can change all the hits in one go.
- All five run from one tool menu and work with every installed game version (Retail, Classic, Classic Era,
  Anniversary, PTR and Beta) on Windows, macOS, Linux and WSL. The app checks for updates and can install them.
- Every tool backs up the files it changes before it changes them. You can see what a run will do before you
  start it, and undo the last one afterwards. If WoW is running, the app tells you. The three tools that delete
  or rewrite addon settings make you accept the risk first.
