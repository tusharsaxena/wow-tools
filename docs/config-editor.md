# Config Editor guide

[← Back to the main page](../README.md)

WoW keeps its settings, the CVars, in plain files: `Config.wtf` for this computer, one `config-cache.wtf` for each
account and one in each character's folder. The Config Editor shows all of them in one tree, for every game version
you have installed, explains each CVar, and lets you set, add, remove and reset them, including CVars the game's
menus don't show. Nothing is written until you press **Apply**, and **Undo last change** puts it all back.

**Close WoW first.** WoW rewrites these files when you log out or exit, so a change made while it runs would be
overwritten. **Apply** and **Undo last change** refuse while that game version runs.

The left pane starts with a red `⚠ USE AT YOUR OWN RISK` line: a wrong value can change how the game looks or
plays, and Remove and Reset take lines out of the files.

## Step by step

1. Start Ka0s WoW Tools and choose **Config Editor**.
2. **The first time only:** check the backup folder (empty is fine) and press **Save**.
3. **Pick a game version**, or **All flavors**. `t` or `Esc` goes back to the tool menu.
4. The tree lists **Config.wtf**, each account's **Account config** and every character. Open one to see its CVars.
5. Highlight a CVar to read about it in the help panel, and change what you like. Each change is marked in the tree;
   nothing is written yet.
6. Press **Dry run** (`y`) to check everything without writing, or **Apply** (`w`), read the summary and press
   **Yes**.
7. The results screen lists every file written.

## The browse screen

![The Config Editor](assets/screenshots/config-editor/browse.png)

The tree has three levels, as the game does:

| Line | File | Holds |
|---|---|---|
| **Config.wtf** | `WTF\Config.wtf` | This computer's settings (graphics, sound, the window) |
| **Account config** | `WTF\Account\<account>\config-cache.wtf` | Settings shared by every character of the account |
| a character | `WTF\Account\<account>\<realm>\<character>\config-cache.wtf` | That character's own settings |

Open a file to see its CVars, one per line: `name = value (default …)`. `✱changed` means the value differs from the
game's default; `not set` means the file has no line for it, so the game uses its default; `unknown` means the
knowledge base has no entry for that CVar (an addon's, or one too new or too old): you can still set, remove or add
it. A changed CVar is marked `✎` until **Apply**, and a file with changes shows `✎` and how many. A character with no
file yet says `no file`: setting a CVar there creates it. Folders that aren't characters, such as `Bob - Copy`, are
not listed. A file that can't be read shows **read-only**: it is never ticked or written, and the **warnings view**
lists it.

### The help panel

The panel under the tree (beside it in a window 160 columns wide or more) shows the highlighted CVar: its value here
and its default, whether it differs, Blizzard's own help text and our plain-English note, each with where it comes
from, whether it is an on/off switch, where the game keeps it (this computer, the account or the character) and
whether the game syncs it with Blizzard's servers, and the recommendation for it if there is one. A CVar set in a
file of the wrong level (an account CVar in a character's file) gets a warning there.

### Show and search

`/` goes to the filter box: type part of a CVar's name or of its description (or a file's name) and press Enter or
**Filter**; the files with a match open. Under **Show**, pick a category (graphics, sound, interface, camera,
nameplates, combat text, network, other), tick **Changed only** for the CVars set to something other than their
default, or tick **Show all known** to list every CVar the knowledge base knows for that file's level, set or not.

### Keys on the browse screen

| Key | Does |
|---|---|
| `Space` | On a CVar that is `0` or `1`: switch it. Elsewhere: tick or untick the highlighted file, character, account or realm |
| `a` / `n` | Tick every file shown / none |
| `/` | Go to the filter box |
| `x` / `c` | Expand / collapse the whole tree |
| `e` | **Set**: a new value for the highlighted CVar |
| `N` | **Add**: a CVar the file doesn't set yet |
| `d` | **Remove**: take the highlighted CVar's line out |
| `R` | **Reset**: back to the default (the line goes) |
| `m` | **Recommend…**: the recommendations for the highlighted file |
| `w` | **Apply**: write every change (asks first) |
| `y` | **Dry run** |
| `r` | **Rescan**: read the files again (asks first when it would drop your changes) |
| `z` | **Undo last change** |
| `!` | Open the files and folders that could not be read (only while there are any; the **⚠ … (!)** button at the bottom does the same) |
| `f` | Back to the game versions |
| `t` | Back to the tool menu |
| `s` | Settings |
| `h` | Help |
| `q` | Quit |

Leaving with changes not applied yet asks first.

## Set, Add, Remove and Reset

**Set**, **Remove** and **Reset** act on the highlighted CVar in every ticked file, or only in its own file when
nothing is ticked: tick your characters, highlight a CVar in one of them and **Set** it, and it is set in all of
them. **Add** asks for a name and a value and puts the CVar into every ticked file, or the highlighted one; as you
type the name it says whether the knowledge base knows it, its default and where the game keeps it. **Reset** takes
the line out, since a CVar a file doesn't set takes the game's default; **Remove** does the same for any CVar,
including one with no known default.

## Recommend…

**Recommend…** lists the recommendations for the highlighted file: each with the value, the reason and the page it
comes from. Tick the ones you want (`Space` or `Enter`) and press **OK**; they are staged like any other change.
A recommendation already at its value is listed but can't be ticked.

## Apply

**Apply** asks first, with every file and change in a list, and any CVar set in a file of another level than the
one the game keeps it in. Then it:

1. backs up the whole `WTF` folder of each game version it changes (`snapshots\snapshot-<flavor>-<YYYYMMDD-HHMMSS>.zip`),
2. zips every file it changes as it was (`edited\...`),
3. writes each file, checking it reads back as written. Lines you didn't change keep their exact bytes and place;
   new lines go at the end.

A file that changed since it was read (WoW saved it) is skipped, and the results say so. WoW's own `cache.md5` and
`.old` files are never touched.

## Dry run

**Dry run** checks every change without writing anything. **Back to review** (`Esc`) keeps your changes.

## Undo last change

**Undo last change** (`z`) puts back every file the last Apply changed and removes every file it created, each only
if WoW hasn't changed it since. The journal of each Apply is kept under
`<WoW folder>\wow-tools\config-editor\journal\`.

If the app stops in the middle of an Apply (a crash, a power cut), the next scan says so and offers **Put the
originals back** or **Leave as is**.

## Settings

Press `s` in the editor (you get the shared settings first, then the editor's). The editor's settings are saved in
`config\config-editor.cfg`.

| Setting | Starts as | What it means |
|---|---|---|
| Backup folder | empty | Where the snapshots and the zips of changed files go. Empty means `<WoW folder>\wow-tools\config-editor` |

The file itself uses these names, if you edit it by hand: `backup_dir` and `last_flavor_choice`. Close the app
before editing the file, or your change may be overwritten. Comments you add to the file aren't kept (the app
rewrites it when it saves a setting or the game version you pick).

How many snapshots and journals to keep (`keep_backups`, `keep_journals`) are shared by every tool, on the first
screen `s` opens.

## FAQ

| Question | Answer |
|----------|--------|
| Will the game undo my change from its servers? | No: a file changed with WoW closed is what the game uses at the next login. |
| What does `unknown` mean? | The knowledge base has no entry for that CVar in this game version. You can still change it. |
| Is Reset the same as Remove? | Both take the line out, so the game uses its default. Reset is only offered when the default is known. |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **Apply** is greyed out | Nothing is changed yet. |
| Space does nothing on a CVar | It isn't `0` or `1`: use **Set** (`e`). |
| A character is missing | Its folder name isn't a character name (`Bob - Copy`, `Bob2`): rename or remove the folder. |
| Something else looks wrong | Follow [Reporting a bug](../README.md#reporting-a-bug) in the main README. |
