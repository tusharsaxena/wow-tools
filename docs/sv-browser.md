# Saved Variables Browser guide

[← Back to the main page](../README.md)

## USE AT YOUR OWN RISK

> **USE AT YOUR OWN RISK.** This tool edits addon SavedVariables directly. It knows nothing about what an addon
> expects; a wrong value can break an addon or lose its settings. Backups and Undo are made, but you are responsible
> for what you change.

Every other tool in the app knows what it is changing: a leftover file, a screenshot, an Ace3 profile. This one
doesn't. It shows you the raw data an addon saved and lets you change any value in it. If you set a value the addon
doesn't expect (text where it wants a number, a colour that is out of range, a key it never reads), the addon may
throw errors, reset itself to its defaults or quietly lose that setting. The tool can't warn you about that.

So the tool asks you to accept this each time you open it from the tool menu (**I understand**, or **Back** to the
game versions), shows `⚠ USE AT YOUR OWN RISK` in red at the top of its left panel the whole time, and repeats the
warning in red on every **Apply** and **Undo** confirm.

What it does guarantee: every byte you didn't change stays exactly as it was, your whole `WTF` folder and every file
it changes are backed up before anything is written, and **Undo last change** puts the files back.

> **Close WoW first.** WoW keeps every addon's settings in memory while you play and writes them all back to the
> `WTF` folder every time you log out or type `/reload`. Anything this tool changed while the game was open would be
> overwritten. That's why **Apply** and **Undo** refuse to run while WoW is running (browsing, searching and a
> **Dry run** work any time).

<!-- screenshots: disclaimer popup, review screen (Browse), search popup, review screen (Results), apply confirm, result -->

## What it shows

Every addon keeps its settings in **SavedVariables** files: one `.lua` file per addon, in the `WTF` folder of each
game version. There is one set per account (**account-wide**) and one per character:

```
<game version>\WTF\Account\<ACCOUNT>\SavedVariables\ElvUI.lua                      account-wide
<game version>\WTF\Account\<ACCOUNT>\<Realm>\<Character>\SavedVariables\ElvUI.lua  per character
```

Each file is a list of variables (`ElvDB = { ... }`), and each variable is a value or a table of keys and values,
tables inside tables. The tool shows every such file of every game version you picked, every account, account-wide
and per character, including Blizzard's own (`Blizzard_*.lua`). It leaves out backup copies (`.lua.bak`, `.old`),
other files such as `Config.wtf`, and anything reached through a link (a symlink or junction).

## Step by step

1. Close WoW. Start Ka0s WoW Tools and choose **Saved Variables Browser**.
2. **The first time only:** check the settings (see [Settings](#settings)) and press **Save**. The suggested value
   is fine for most people.
3. **Pick a game version**, or **All flavors** to see every version at once. There is no account picker: the tree
   shows every account.
4. Read the warning and press **I understand** (or **Back** to pick again).
5. The review screen lists every SavedVariables file. Open a file to see its variables, and open a table to see its
   keys.
6. Change what you want: highlight a key and press **Edit value**, **Rename key** or **Delete key** under the tree,
   or press **Search** to find values in many files at once and edit the results in bulk. Each change is
   **staged**: the tree marks it straight away, but no file is touched yet.
7. Press **Dry run** (`y`) if you'd like every change checked without writing anything.
8. Press **Apply** (`w`), read the summary and the warning, and press **Yes**.
9. The results screen lists every file and what happened to it. If you don't like the result, close WoW and press
   **Undo last change** (`z`) on the review screen.

## The review screen

**On the right** is the tree. It has two views; **View** (`v`) switches between them, and the screen's sub-title
names the one you're on.

**Browse** (the usual view):

game version → account → **Account-wide**, or realm → character → the file and its size (`ElvUI.lua  12.4 KB`) → variables → keys

- Nothing is read until you open a file, so the scan is quick even with thousands of files. Opening a file reads it
  and shows its variables; opening a table shows its keys. A big file takes a moment: a dim "Reading…" line shows
  while it loads.
- A value shows as `key = value`: text in double quotes (a long text is cut short with `…`), numbers as the file
  writes them, `true`, `false` or `nil`. A table shows as `key {12}`, with how many entries it holds.
- Keys show the way the tree writes them: a text key bare (`font`), a number or boolean key in brackets (`[5]`,
  `[true]`). Array entries (lists with no written key) show by their position, `[1]`, `[2]`, …
- A table with more than 500 entries shows the first 500 and a `… N more` line.
- A file that isn't readable Lua (damaged, cut short) shows in red with "can't read" and the reason. It is never
  changed and never searched. If only one table deep inside a file is damaged, that table shows the red line and the
  rest of the file is still there to read, but an edit staged anywhere in that file stops **Apply** before anything
  is written ("not readable Lua").

**Results**: the hits of your last search; see [Search](#search) and [Editing the results in bulk](#editing-the-results-in-bulk).

**Under the tree** is the action bar. It works on the highlighted key (in **Results**, **Edit value** and **Rename
key** work on every ticked result; see [Editing the results in bulk](#editing-the-results-in-bulk)); a button that
can't act on it is greyed out.

| Button | Key | Does |
|---|---|---|
| **Edit value** | `e` | Sets the key's value: a string, a number or a boolean |
| **Rename key** | `k` | Renames the key |
| **Delete key** | `d` | Deletes the key, and everything inside it when it is a table |
| **Unstage** | `Backspace` | Drops what is staged on the highlighted key |
| **View** | `v` | Switches between Browse and Results |

`Tab` from the tree reaches the bar, and so does `↓` on the tree's last line; `←` `→` move along it and `↑` goes
back to the tree.

**On the left** are the red `⚠ USE AT YOUR OWN RISK` line, the filter box with its **Filter** button, the lines that
count what is waiting (`Staged: 3 edits in 2 files`, and after a search `Results: 120 hits in 14 files` and
`Ticked: 120 results`), **Search** on a row of its own, then **Apply**, **Dry run**, **Rescan** and **Undo last
change**.

**At the bottom** a bar names the highlighted line in full
(`Selected: Retail › ACCT1 › Account-wide › ElvUI.lua › ElvDB › font = "Expressway"`) and counts the files found
(`312 files in 2 flavors`).

**Warnings**: when the scan skipped a folder, or a file couldn't be read (when you opened it in the tree, or a
search went through it), a **⚠ N warnings (!)** button sits at the right end of the bottom bar:
click it or press `!` to open the **warnings view**. It lists every warning, grouped by game version, each with the file or
folder (inside that game version's folder) and what went wrong; the line on the left shows the highlighted one in
full. `/` filters the list, `x` / `c` expand and collapse it, `h` opens the help, and **Back** (`Esc`) returns to
the review. With no warnings there's no button. The log still has them too.

### The filter

`/` takes you to the filter box. Type some text, then press `Enter` (or click **Filter** beside the box): the tree
keeps only lines whose text contains it (upper or lower case doesn't matter), and the groups they're in. Typing alone
changes nothing, so a big tree isn't rebuilt on every key you press. In **Browse** the filter looks only at what has
been read so far: the files and accounts, and the keys of the files and tables you've opened; open a file first to
filter inside it. In **Results** it looks at every hit. Empty the box and press `Enter` to show everything again;
`Esc` in the box clears it at once and goes back to the tree.

`x` opens every game version, account and character down to the files (it doesn't read any file), and `c` closes
everything.

## Editing

Highlight a key, then press a button under the tree. Every edit is **staged**: the tree shows it at once, and
nothing is written until **Apply**.

| You see | Means |
|---|---|
| `font = "Expressway"  ✎ "Friz Quadrata TT"` | The value will change |
| `fontSize = 12  → size` | The key will be renamed |
| `font = "Expressway"  → Font  ✎ "Arial"` | Both |
| `profiles {4}  ✗ deleted` | The key will be deleted; everything inside it shows dim and struck through |

What you can do depends on the key:

| Key | Edit value | Rename key | Delete key |
|---|---|---|---|
| Top-level variable (`ElvDB`, `DetailsVersion`) | Only when it isn't a table | No | No |
| A key with a plain value (`font = "Expressway"`) | Yes | Yes | Yes |
| A key holding a table (`profiles {4}`) | No: open it and edit its keys | Yes | Yes, with everything inside it |
| An array entry (`[3]` with no written key) | Yes | No | Yes, with a warning |

**Unstage** (`Backspace`) drops what is staged on the highlighted key. **Rescan** with staged edits asks first, and so
does leaving the screen: they haven't been written, and leaving throws them away.

### Edit value

The popup names the key and its value now (**Now:**), and has a type list (String, Number or Boolean) and the new value: a text
box for a string or a number, a checkbox for a boolean. The type may change (a number can become a string). **OK**
(or `Enter`) checks what you typed and stages it; a problem shows under the box until you change it.

- A **number** must be one Lua reads back as exactly that number: `12`, `-0.5`, `1e3`. `inf`, `nan` and integers
  past 2^53 are refused.
- A **string** is written in double quotes, with Lua escapes where needed. A string that holds line breaks or bytes
  that can't be typed starts empty, with a note: type the whole new value.
- Setting the value already there stages nothing.
- A value can't be set to `nil` (delete the key instead), and a table can't be edited as a value: open it and edit
  its keys.

### Rename key

Type the new key as the tree writes keys: `[5]` or `[2.5]` is a number key, `[true]` or `[false]` a boolean key, and
anything else a text key as you typed it (`["[5]"]` is the text `[5]`). New keys are always written in brackets, as
WoW writes them. Refused:

- an empty key;
- a key the table **already has** (by Lua's rules, so `[1]` and `[1.0]` are the same key, and `["1"]` is another), counting
  the edits already staged in that table;
- a **top-level** variable (`ElvDB`): the addon looks it up by that name, so it can't be renamed;
- an **array entry**: it has no written key to rename.

### Delete key

A confirm names the key (and for a table, how many entries go with it). **Yes** is selected, in red. Then:

- A **top-level** variable can't be deleted (only its value edited, when it isn't a table).
- An **array entry** can be deleted, with a warning: the entries after it move down one place, as Lua's
  `table.remove` does, and the `-- [n]` comments WoW writes after them no longer match their positions (WoW fixes them
  the next time it saves the file).
- Edits staged inside a deleted table are dropped (the confirm says how many), and nothing more can be staged inside
  it until you unstage the delete.

## Search

**Search** (`S`, that's Shift+S; `s` is settings) opens the search popup. It only finds: what to change is chosen
afterwards, on the results. Fill in what you need and press **Find** (or `Enter`):

| Field | What it means |
|---|---|
| **Key** | The key name to look for (`font`). A number key matches its written text (`5`), an array entry its position |
| **Key match** | **Exact** (the whole key, the default) or **Contains** (the text anywhere in the key) |
| **Value** | The value to look for (`Friz Quadrata TT`) |
| **Value match** | **Whole value** (the default) or **Contains** (the text anywhere inside a string value) |
| **Match case** | Off by default: `FONT`, `Font` and `font` are the same. Tick it to match upper and lower case exactly |
| **Flavor** | Every flavor, or one (only with **All flavors**) |
| **Account** | Every account, or one |
| **Character** | Every character and account-wide, **Account-wide only**, or one character |
| **Addon file** | Only files whose name contains this text (`elv` finds `ElvUI.lua`), any case |

Fill in the key, the value, or both: with both, a hit must match both (key `font` exact **and** value `Friz`
contains). Only plain values are hits: a key whose value is a table never is. Numbers and booleans match by how the
file writes them, and only as a **Whole value**; **Contains** looks inside strings only. A `nil` value can be found by
its key but never by its value.

The popup opens with your last search filled in, so narrowing it is quick.

### Results

The search reads every file in scope (several at once, with a progress window), and switches the tree to the
**Results** view: game version → account → **Account-wide** or `Realm/Name` → file → one line per hit,
`ElvDB › profiles › Default › general › font = "Expressway"`. A message says how many hits it found, in how many
files, and how long it took.

- **Every hit starts ticked.** `Space` ticks or unticks the highlighted hit or group, `a` and `n` tick and untick
  everything the filter shows (a tick the filter hides stays, and the bottom bar says how many). Ticks only choose
  which results a bulk edit works on: a ticked result is never written by itself.
- A hit with a staged edit shows the same marks as in Browse (`✎ "Arial"`, `→ size`), and a hit inside a key staged
  for delete shows dim and struck through. The edits staged from the results show in Browse too.
- `v` goes back to Browse and back again; the ticks stay. A **Rescan** drops the results.
- The results stop at **10,000** hits; the left panel says how many more were left out. Narrow the search (a game
  version, an account, an addon file) to get the rest.
- Files that can't be read are counted on the left ("3 files can't be read."); they are skipped.
- A **new search** replaces the results and their ticks; what is staged stays.

## Editing the results in bulk

In the **Results** view, **Edit value** (`e`) and **Rename key** (`k`) work on **every ticked result**, or on the
highlighted one when none is ticked. They open the same popups as in Browse, titled with the count ("Edit 37
values", "Rename 12 keys"), and **OK** stages one edit per result, exactly as if you had made each one in Browse. The
results stay on screen with their ticks, so you can check the marks, unstage a hit with `Backspace`, or run another
edit. **Delete key** works one key at a time, in Browse only.

- **Edit value** starts from the results' value when they all hold the same one. After a search with value
  **Contains**, the popup has one more choice first: **Replace only the matched text** (the default) puts your text
  in place of every match inside each string and keeps the rest (`Interface\Fonts\FRIZQT__.TTF`, found with
  value `FRIZQT__` contains and edited to `ARIALN`, becomes `Interface\Fonts\ARIALN.TTF`); **Whole value** sets
  the whole value, of the type you pick, as a normal edit does.
- **Rename key** first reads the tables the keys are in (a progress window shows "Reading"), so a rename to a key a
  table already has can be refused.

A notice then says how many edits were staged, how many results already had the new value (nothing to change), and
how many were **left out**, with the reason for each. A result is left out when:

- its key already has a staged edit (unstage it first if you want the bulk edit instead);
- it is staged for delete, or inside a key staged for delete;
- its file changed since the search (search again), or the search read other bytes than the copy you opened in
  Browse or your staged edits on that file (search again; if it is still left out, the file changed on disk after
  you opened it: rescan);
- (rename) it is a top-level variable, an array entry, or its table already has the new key.

**Apply** then writes what is staged, from Browse and from the results alike.

## Apply

When you press **Apply** (`w`), the bottom bar says "Checking whether WoW is running…" for a moment. If WoW is
running for a game version you're changing, it stops there and asks you to close it. If the check can't run, the
confirm warns you in red and lets you go on.

Then the confirm counts the edits and files per game version, lists each file under its game version
(`ACCT1 › Account-wide › ElvUI.lua: 2 edits`), and shows in red: array entries that will move down, and the USE AT
YOUR OWN RISK warning. **Yes** is selected, in red.

A progress window then shows each step. For each game version the tool:

1. **Checks every file again.** If a file changed since the tool read it (you logged a character out with the tool
   open, say), that file is **skipped** with "changed since the scan; rescan", and the others go ahead.
2. **Builds each new file in memory and checks it**: the new file must read as Lua, every variable must still be
   there in the same order, every table it touched must hold exactly what you asked for, and every byte outside your
   edits must be unchanged. The tool never rewrites a file the way the game does: it changes only the bytes of the
   values and keys you edited.
3. **Checks that no other program has the files open.** The Raider.IO client and the WeakAuras Companion are known
   to lock these files. If any is locked, nothing is changed; close that program and apply again.
4. **Backs up your whole `WTF` folder** into a zip and checks the zip.
5. **Saves the files it's about to change**, as they are now, into another zip. This is what Undo uses.
6. **Writes each file**, and reads it back to make sure it landed.

If anything goes wrong while writing, every file already written in that game version is put back as it was, and the
run stops. With **All flavors** the game versions are changed one after another; if one runs into a problem, the
versions after it aren't touched, and the versions before it keep their changes (Undo puts them back).

After a real Apply the staged edits are gone, and the review reads the files again when you leave the
results screen.

## Dry run

A **Dry run** (`y`) does everything Apply does except writing: it rechecks every file and builds and checks each new
version in memory. It writes nothing at all: no zip, no journal. It works while WoW is running. Its results screen
has a **Back to review** button (`Esc`) that takes you back with your staged edits still there.

## The results screen

The top table sums up the run: game versions, files changed (or that would change), edits written (or checked),
files skipped, put back or failed, the backup folder, the `WTF` backup, the zip of the
original files and the journal. The table below has one line per file: game version, account, account-wide or
character, file, how many edits, and what happened ("changed", "would change", "skipped", "put back", "failed"),
with the reason when there is one.

From here, `r` scans again, `f` picks another game version, `t` goes back to the tool menu, and `q` quits. If an
Apply was refused before it wrote anything, **Back to review** keeps your staged edits too.

## Undo last change

Changed your mind? **Undo last change** (`z`, the violet button) puts back every file the most recent Apply changed,
from the zip of the original files. It asks first, naming when that change ran and in which game versions, with the
USE AT YOUR OWN RISK warning. Close WoW first: Undo refuses while it's running, just like Apply.

- A file is put back only if it's still exactly what the tool wrote. If WoW (or anything else) saved it since, it's
  **left as it is** and marked "changed since the change was made". Undo never overwrites settings saved after the
  change.
- Before it puts anything back, Undo backs up your whole `WTF` folder again, so the undo itself can be undone by hand.
- Undo only goes back **one** change: after you undo, the button stays greyed out until your next Apply.
- Anything staged that you haven't applied is dropped when the Undo runs (the confirm says how much). If
  the Undo is refused before it starts (WoW running, say), it stays.

## The safety net

Every real Apply, Undo and recovery gets the same protection as the other tools that change your settings files:

- a **backup of your whole `WTF` folder** (per game version) before anything is written;
- a **zip of every file it changes**, as it was, which Undo puts back;
- a **journal**, the record of what was changed, which **Undo last change** reads;
- **a crash marker** while files are being written, so an interrupted run is noticed (see below);
- the **check of every new file** before it is written, and a read-back after;
- **roll-back**: if a write fails, the files already written in that game version are put back.

### Where your backups go

Unless you change it in settings, the backup folder is `<your WoW folder>\wow-tools`. The tool's files go into its
`sv-browser` folder:

```
<backup folder>\sv-browser\
  snapshots\snapshot-<flavor>-<YYYYMMDD-HHMMSS>.zip       your whole WTF folder, taken before each change, undo and recovery
  edited\edited-<flavor>-all-<YYYYMMDD-HHMMSS>.zip         the files a change edited, as they were before it
  edit-in-progress.json                                    only while a change is being written
<your WoW folder>\wow-tools\sv-browser\
  journal\journal-<YYYYMMDD-HHMMSS>.jsonl                  the record Undo last change uses
```

`<flavor>` is the game version (`retail`, `classic_era` and so on). If two runs start in the same second, the second
gets `-2` added before `.zip`, so no backup ever replaces another. The journals always stay in your WoW folder, even
if you pick another backup folder.

- Only the newest 10 **WTF backups** (`snapshots`) of each game version are kept: `keep_backups`, a shared setting
  on the first screen `s` opens (`0` keeps them all).
- Only the newest 10 **journals** are kept: `keep_journals`, also shared. An `edited` zip is deleted along with the
  last journal that needs it.
- To put files back by hand (an older change, say): close WoW, open the `edited\edited-…zip`, and extract it **into
  the game version's folder** (for example `World of Warcraft\_retail_`), keeping the folders. You can ignore
  `manifest.json`.

### If a change was interrupted

If the app is closed in the middle of an Apply (a power cut, or you closed the window), it notices the next time the
review screen reads the files and shows **An earlier change did not finish**, with the number of files and where
their originals are. It **never repairs anything on its own**. You choose:

- **Put the originals back**: each file the change had already written is put back from the zip of the original
  files. A file that's neither the original nor what the change wrote (WoW saved it since, say) is left as it is.
  This is guarded like Undo: refused while WoW is running, and your `WTF` folder is backed up first. It reads the
  files again afterwards, so anything staged is dropped (the message says so).
- **Leave as is**: the files stay as they are now; the zips are kept.

If you close the message with `Esc`, it's shown again at the next scan, and when you press **Apply**: a new change
can't start until you've chosen, since it would lose the way back for the earlier one.

The message can also appear after a change that did finish, when another program (a virus scanner or OneDrive)
held the app's reminder file so it could not be removed; the change's result says so. **Put the originals back**
then sees the change finished and only removes the reminder: no file is changed, and Undo still offers the change.
If the reminder still can't be removed (after **Put the originals back** or **Leave as is**), a notice says so and
the message comes back at the next scan; close the other program and choose again.

## WoW running

| Action | While WoW runs |
|---|---|
| Browse, Search, edit and stage | Fine: nothing is written |
| **Dry run** | Fine: nothing is written |
| **Apply**, **Undo last change**, **Put the originals back** | Refused for the game versions that are running. Close WoW and try again |

WoW is checked per game version: Classic running doesn't stop you changing Retail files.

## Settings

Press `s` in the tool (you get the shared settings first: WoW folder, backups and journals to keep, game versions to
work on at once; then this tool's). The tool's settings are saved in `config\sv-browser.cfg`.

| Setting | Starts as | What it means |
|---|---|---|
| Backup folder | empty | Where the `WTF` backups and the zips of edited files go: they're put in its `sv-browser` folder. Empty means `<WoW folder>\wow-tools`. It must be a full path (such as `D:\WoW backups`), and it can't be your WoW folder itself or inside a game version's `WTF`, `Interface` or `Screenshots` folder |

The file itself uses these names under `[sv_browser]`, if you edit it by hand: `backup_dir` and
`last_flavor_choice` (the game version you picked last time; empty means **All flavors**).

How many backups and journals to keep is shared by every tool: `keep_backups` (10; `0` keeps all) and
`keep_journals` (10) under `[general]` in `config\wow-tools.cfg`, on the first screen `s` opens. So is
`parallelism` (2, from 1 to 8; use 1 on a hard drive or a WSL `/mnt` folder): how many files a search reads at
once, and how many game versions Undo backs up at once. Apply still does one game version after another.

## Keys on the review screen

| Key | Does |
|---|---|
| `Enter` | Open or close the highlighted line (a file or table is read when first opened) |
| `S` (Shift+S) | **Search** |
| `e` | **Edit value** of the highlighted key (Results: of every ticked result) |
| `k` | **Rename key** (Results: of every ticked result) |
| `d` | **Delete key** (asks first) |
| `Backspace` | **Unstage** the highlighted key |
| `v` | Switch view: Browse / Results |
| `Space` | Tick or untick the highlighted result or group (Results view) |
| `a` / `n` | Tick / untick every result shown (Results view; ticks hidden by the filter stay) |
| `/` | Go to the filter box; `Enter` or **Filter** applies it |
| `x` / `c` | Open everything down to the files / close everything |
| `!` | Open the warnings (only while there are any; the **⚠ … (!)** button at the bottom does the same) |
| `w` | **Apply** what is staged (asks first; **Yes** is selected, in red) |
| `y` | **Dry run** (asks first; **Yes** is selected) |
| `r` | **Rescan**: read the files again (asks first when something is staged) |
| `z` | **Undo last change** (asks first; **Yes** is selected, in red) |
| `f` or `Esc` | Pick another game version (in the filter box, `Esc` clears the filter and goes back to the tree) |
| `t` | Back to the tool menu |
| `s` | Settings |
| `h` | Help: this tool's keys and steps, with a link to this guide |
| `q` | Quit |
| `←` `→` | Jump between the tree and the left panel |
| `Tab` | Move to the next control |

Leaving with `f`, `Esc`, `t` or `q` while something is staged asks first (ticks alone don't). In the popups,
`Enter` presses **OK** or **Find**, `Space` ticks a checkbox and `Esc` cancels.

## FAQ

| Question | Answer |
|----------|--------|
| Which files does it show? | Every `.lua` file directly in a `SavedVariables` folder, account-wide and per character, in every game version you picked, Blizzard's `Blizzard_*.lua` included. Not `.bak` / `.old` copies, `Config.wtf` or other files, and nothing reached through a link. |
| Will it break my addons? | It can, if you set a value an addon doesn't expect. The tool knows nothing about any addon. Change only what you understand, try one character first, and keep **Undo last change** in mind. Your whole `WTF` folder is backed up before every change. |
| Does it reformat my files? | No. It changes only the bytes of the values and keys you edited; every other character of the file stays exactly as it was, and it checks that before writing. WoW reformats the file itself the next time it saves it. |
| Can I add a key or a table? | No. You can edit values, rename keys and delete keys. Adding keys or tables, and editing a whole table as one value, are out of scope. |
| Why can't I rename or delete `ElvDB`? | It's a top-level variable: the addon looks it up by that exact name. You can edit its value only when it is a plain value, not a table. |
| Why did my array entries renumber? | Deleting an array entry moves the entries after it down one place, as Lua's `table.remove` does. The confirm warns you. The `-- [n]` comments WoW writes are left stale until WoW saves the file again. |
| Can I search with wildcards or regular expressions? | No: **Exact** / **Contains** for keys, **Whole value** / **Contains** for values, with or without **Match case**. Combine a key and a value to narrow it. |
| Why are there only 10,000 results? | The results stop there so a broad search can't fill memory. The left panel says how many more there were; narrow the search by game version, account, character or addon file. |
| Can I replace a number with text? | Yes: **Edit value** and pick **String** as the type. In a bulk edit after a value **Contains** search, pick **Whole value** first: **Replace only the matched text** works inside strings only. |
| What's the difference between Dry run and Apply? | A **Dry run** checks every staged edit and shows the results without writing anything. **Apply** writes them, after backing everything up. |
| Can I undo a change from last week? | **Undo last change** only goes back to the most recent change. For an older one, unzip its `edited` zip by hand; see [Where your backups go](#where-your-backups-go). |
| Why does it ask me to accept the warning every time? | Because this tool can do damage no other tool in the app can. It asks once each time you open it from the tool menu (not when you pick another game version or rescan). |
| Does it work on a Mac? | Yes. The "WoW is running" check works there too, so Apply and Undo wait until you close WoW. |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "WoW is running … Close it first" | Close that game version's WoW and try again. WoW would overwrite the changes when you log out. |
| A file was "skipped: changed since the scan; rescan" | WoW (or another program) saved that file after the tool read it. Press `r`, make that file's changes again and apply. The other files were changed as planned. |
| My changes were undone after I played | WoW was running while you applied, or an addon reset its settings because it didn't accept a value. Close WoW completely and apply again; if the addon resets it, the value isn't one it accepts. Undo puts the old file back. |
| An addon shows errors or lost its settings after a change | A value you set isn't what the addon expects. Close WoW and press **Undo last change** (`z`), or put the file back by hand from the `edited` zip. |
| "files are locked by another program" | Close the Raider.IO client or the WeakAuras Companion, then apply again. Nothing was changed. |
| A file shows in red with "can't read" | It isn't readable Lua (damaged, or cut short when WoW crashed). The tool never changes or searches it. WoW rewrites it the next time that addon saves. |
| `/` doesn't find a key I know is there | In Browse the filter only sees what has been read: open the file (and the table) first, or use **Search** (`S`). |
| **Edit value**, **Rename key** or **Delete key** is greyed out | It can't act on the highlighted line: a top-level variable can only have its value edited, an array entry can't be renamed, a table can't be edited as a value, and a key inside a deleted table can't be changed. |
| `Space` says there is nothing to tick | Ticks are for search results: run a search (`S`), then look at the Results view (`v`). |
| A bulk edit says some results were "left out" | The notice gives the reason for each; see [Editing the results in bulk](#editing-the-results-in-bulk). Unstage the earlier edit (`Backspace`) if you want the bulk edit instead, or rescan and search again if the file changed. |
| I ticked results but **Apply** is greyed out | Ticks only choose what a bulk edit works on. Press **Edit value** (`e`) or **Rename key** (`k`) to stage the edits, then **Apply**. |
| "An earlier change did not finish" | See [If a change was interrupted](#if-a-change-was-interrupted). |
| "Backup folder not allowed" | The backup folder in settings is a relative path, your WoW folder, or inside a game version's `WTF`, `Interface` or `Screenshots` folder. Press `s` and pick another folder, or leave it empty for the default. |
| **Undo last change** is greyed out | There's nothing to undo: you haven't applied a change yet, or you already undid the last one. |
| A file is "left as it is" after Undo | WoW saved it after the change, so putting the old version back would lose those settings. To go back anyway, close WoW and unzip it from the `edited` zip by hand. |
| Something else looks wrong | Follow [Reporting a bug](../README.md#reporting-a-bug) in the main README. |
