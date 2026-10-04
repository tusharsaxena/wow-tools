# Interface Backup guide

[← Back to the main page](../README.md)

Your addons live in a game version's `Interface` folder and their settings in its `WTF` folder. Interface Backup
zips those two folders into one dated zip per game version, so a bad addon update or a lost setting is one restore
away. Zips go to `<backup folder>\interface-backup\backup-<flavor>-<YYYYMMDD-HHMMSS>.zip`.

This guide is finished in a later step; for now it lists the settings.

## Settings

Press `s` to change them, or edit `config\interface-backup.cfg` while the app is closed (section
`[interface_backup]`).

| Setting | Default | Meaning |
|---|---|---|
| `backup_dir` | empty | The backup folder. Empty means `<WoW folder>\wow-tools`. Zips go to its `interface-backup` folder. It can't be the WoW folder itself, or inside a game version's `WTF`, `Interface` or `Screenshots` folder. |
| `keep_backups` | 10 | Backups to keep for each game version; older ones are deleted after a new backup. `0` keeps every backup. |
| `keep_journals` | 10 | Restore journals to keep (at least 1). Each names the safety backup taken before that restore; Undo uses the newest. |
| `last_flavor_choice` | empty | The game version picked last time (empty means **All flavors**). |
