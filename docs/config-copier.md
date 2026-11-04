# Config Copier guide

[← Back to the main page](../README.md)

Setting up an alt means making the same macros, picking the same addons, dragging the chat windows into place and
ticking the same options all over again. WoW keeps all of that in a handful of plain files in each character's
folder, so the Config Copier copies them for you: from one character (the **source**) to as many others of the same
game version as you like (the **targets**), in one step you can review and undo.

It copies five files, and nothing else:

| File | Holds |
|---|---|
| `macros-cache.txt` | The character's own macros |
| `AddOns.txt` | Which addons are enabled |
| `chat-cache.txt` | The chat windows and their channels |
| `config-cache.wtf` | The character's CVars (game options); **merged**, see below |
| `layout-local.txt` | The layout of the windows |

Key bindings, click bindings, the Cooldown Manager and Edit Mode are not copied: WoW keeps them on its servers too, and
they depend on the class.

**Close WoW first.** WoW rewrites these files when a character logs out, so a copy made while it runs would be
overwritten. **Write** and **Undo last change** refuse while that game version runs.

## Step by step

1. Start Ka0s WoW Tools and choose **Config Copier**.
2. **The first time only:** check the backup folder (empty is fine) and press **Save**.
3. **Pick a game version**, or **All flavors**. `t` or `Esc` goes back to the tool menu.
4. **Pick the source**, the character to copy from: highlight it and press Enter or **Choose**. **Back** returns to
   the game versions.
5. The review lists every character. Tick the **targets** (`Space`). Each target opens to its five files and what
   happens to each.
6. Press **Dry run** (`y`) to check everything without writing, or **Write** (`w`), read the summary and press
   **Yes**.
7. The results screen lists every file.

![Choosing the source](assets/screenshots/config-copier/source.png)

## The review screen

![The Config Copier review](assets/screenshots/config-copier/review.png)

The left pane shows the source, the five files (all ticked: untick one to leave it alone for every target), the
filter and the buttons. The tree on the right lists every account, realm and character. The source shows greyed
(**source**), and so do the characters of other game versions (**other flavor**): a copy stays within one game
version. Folders that aren't characters, such as `Bob - Copy`, are not listed.

Nothing is ticked at first. Ticking a character ticks every file it can get; open it to untick a single file. Each
file says what a copy does:

| Status | Means |
|---|---|
| **new** | The target has no such file: it is created |
| **replaced** | The target's file is replaced (**replaced (merged)** for `config-cache.wtf`) |
| **unchanged** | The target already has exactly this: nothing to do |
| **source has no file** | The source has none: the target's file is left alone |
| **can't be read** | The file could not be read: it is never copied, and the **warnings view** lists it |

A replaced `macros-cache.txt` on a character that already has macros shows **⚠ action bars**: see
[Macros and action bars](#macros-and-action-bars).

**Diff** (`d`, under the tree) shows what a replaced file loses (`-` lines) and gets (`+` lines). For
`config-cache.wtf` it shows the whole file and marks the lines the target keeps.

`/` goes to the filter box: type part of a name and press Enter or **Filter** to see only the characters (and files)
that match. Ticks the filter hides still count, and the bottom line says how many.

### Keys on the review screen

| Key | Does |
|---|---|
| `Space` | Tick or untick the highlighted character or file |
| `a` / `n` | Tick everything shown / nothing |
| `/` | Go to the filter box |
| `x` / `c` | Expand / collapse the whole tree |
| `w` | **Write**: copy the ticked files (asks first) |
| `y` | **Dry run** |
| `r` | **Rescan**: read the files again |
| `z` | **Undo last change** |
| `d` | **Diff** of the highlighted replaced file |
| `!` | Open the files and folders that could not be read (only while there are any; the **⚠ … (!)** button at the bottom does the same) |
| `f` | Back to the game versions |
| `t` | Back to the tool menu |
| `s` | Settings |
| `h` | Help |
| `q` | Quit |

## How config-cache.wtf is merged

`config-cache.wtf` holds two kinds of CVars. **Settings** are what you chose: nameplate distances, Assisted Highlight,
camera options and the like. **Progress and bookkeeping** belong to the character: tracked quests, talent loadouts,
tutorials seen, the last season it saw, which lists are collapsed.

The copy gives the target the source's settings **exactly**: a setting the source has is set to the source's value, and
a setting only the target has is removed. The target keeps its own progress and bookkeeping CVars, and the source's are
never copied. The list of which CVars are progress ships with the app; anything not on it counts as a setting.

## Macros and action bars

Action bar buttons point at a macro's number, not its name. Copying `macros-cache.txt` onto a character that already
has macros replaces those numbers, so its buttons may now point at a different macro, or at nothing. Such a file shows
**⚠ action bars** on the review, and the confirm lists every one. Place the macros on the bars again after the copy.
A target with no macros has nothing to lose.

## Write

**Write** asks first, with the targets and files in a list and the macro warnings counted below it. Then the copy:

1. backs up the whole `WTF` folder of that game version (`snapshots\snapshot-<flavor>-<YYYYMMDD-HHMMSS>.zip`),
2. zips every file it replaces as it was (`edited\...`),
3. writes each file, checking it reads back as written.

A target file that changed since the review (WoW saved it) is skipped, and the results say so. WoW's own `cache.md5`
and `.old` files are never touched: WoW notices the new files and updates them itself at the next logout.

### Dry run

**Dry run** checks every file without writing anything. **Back to review** (`Esc`) keeps your ticks.

## Undo last change

**Undo last change** (`z`) puts back every file the last copy replaced and removes every file it created, each only if
WoW hasn't changed it since. The journal of each copy is kept under `<WoW folder>\wow-tools\config-copier\journal\`.

If the app stops in the middle of a copy (a crash, a power cut), the next scan says so and offers **Put the originals
back** or **Leave as is**.

## Settings

Press `s` in the copier (you get the shared settings first, then the copier's). The copier's settings are saved in
`config\config-copier.cfg`.

| Setting | Starts as | What it means |
|---|---|---|
| Backup folder | empty | Where the snapshots and the zips of replaced files go. Empty means `<WoW folder>\wow-tools\config-copier` |

The file itself uses these names, if you edit it by hand: `backup_dir` and `last_flavor_choice`. Close the app
before editing the file, or your change may be overwritten. Comments you add to the file aren't kept (the app
rewrites it when it saves a setting or the game version you pick).

How many snapshots and journals to keep (`keep_backups`, `keep_journals`) are shared by every tool, on the first
screen `s` opens.

## FAQ

| Question | Answer |
|----------|--------|
| Will WoW put my old settings back from its servers? | No. WoW checked the copied files at the next login, used them, and updated its own records at logout. |
| Can I copy to a character I haven't made yet? | Log in with it once first, so WoW makes its folder. |
| Can I copy between Retail and Classic? | No: a copy stays within one game version. |
| Can I copy account-wide macros and settings? | Not yet: only character files. |
| Why did some tracked quests or reputations change after login? | WoW tidies those itself when the character logs out. |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **Write** is greyed out | Tick at least one target with a file that would change. |
| A target is greyed out | It is the source, or a character of another game version. |
| A character is missing | Its folder name isn't a character name (`Bob - Copy`, `Bob2`): rename or remove the folder. |
| Action bar buttons are empty after copying macros | Place the macros on the bars again (see [Macros and action bars](#macros-and-action-bars)). |
| Something else looks wrong | Follow [Reporting a bug](../README.md#reporting-a-bug) in the main README. |
