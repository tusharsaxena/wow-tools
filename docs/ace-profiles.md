# Ace3 Profile Manager guide

[← Back to the main page](../README.md)

Many addons (ElvUI, Bartender4, HandyNotes and hundreds more) are built on a library called **Ace3**, and they keep
their settings in **profiles**. A profile is a named set of settings, such as "Default", "Healer" or
"Kaelys - Mug'thol". Each character uses one profile, and several characters can share one.

Over the years those profiles pile up: profiles nobody uses any more, characters you deleted long ago, every alt on
its own copy of the same setup. In game you can only tidy them one addon and one character at a time.

The Ace3 Profile Manager reads your `WTF` folder, shows each addon's profiles and which characters use them, and
lets you delete, rename and copy profiles, move characters to another profile and remove characters that no longer
exist. You line up every change first; nothing is written until you press **Apply**. It backs up every file it
edits, and **Undo last change** puts them back.

> **Close WoW first.** Addons keep their profiles in the game's memory while you play, and WoW writes them back to
> the `WTF` folder every time you log out or type `/reload`. Anything this tool changed while the game was open
> would be overwritten. That's why **Apply** and **Undo** refuse to run while WoW is running (a **Dry run** works
> any time).

<!-- screenshots: review screen, popup, result -->

## Step by step

1. Close WoW. Start Ka0s WoW Tools and choose **Ace3 Profile Manager**.
2. **The first time only:** check the settings (see [Settings](#settings)) and press **Save**. The suggested
   values are fine for most people.
3. **Pick a game version**, or **All flavors** to see every version at once.
4. If you picked one version that has more than one WoW account, **pick an account**, or **All accounts**.
5. The tool reads every addon's settings file and shows the review screen. Nothing is ticked yet.
6. Tick the profiles or characters you want to change, and press the key for the change: `d` deletes profiles, `p`
   moves characters to another profile, `e` renames a profile, `k` copies one, `o` removes leftover characters,
   and `m` opens the quick actions. Each change is **staged**: the tree shows the result straight away, but no file
   is touched yet. Stage as many changes as you like.
7. Press **Dry run** (`y`) if you'd like every change checked without writing anything.
8. Press **Apply** (`w`), read the summary, and press **Yes**.
9. The results screen lists every change and what happened to it.

## The review screen

**On the right** is a tree of every addon that keeps Ace3 profiles. It has two views; press `v` (or tick the box
on the left) to switch between them.

**By addon** (the usual view):

game version → account → addon → profile → the characters that use it

- An addon whose settings are kept per character shows that character (realm/name) after its name, for example
  `KickCD (Mug'thol/Kaelys)`.
- When one file holds more than one Ace3 database (ElvUI keeps `ElvDB` and `ElvPrivateDB` in one file), each
  database gets its own line under the addon.
- A profile line shows its name and how many characters use it, for example `Default · 12 characters`.

**By character**:

game version → account → character → one line per addon, `Addon: Profile`

This is the view for "what does this character use everywhere?". Ticking a line here picks that character in
that addon.

**On the left** are the view boxes, the filters, a search box, a line that sums up what's staged, and the buttons.

**At the bottom** a bar counts what's ticked and what's staged, for example
`Selected: 3 profiles · 8 characters · Staged: 6 changes in 2 files`, plus scan warnings when there are any.

### Tags

Lines in the tree carry small tags that tell you what's going on:

| Tag | On | Means |
|---|---|---|
| **Default** | profile | The profile called "Default", the one most addons start every character on |
| **unused** | profile | No character uses it. A good candidate for deleting |
| **empty** | profile | It holds no settings of its own: the addon uses its built-in defaults for it |
| **missing** | profile | A character points at it, but the profile has no settings saved yet. The addon creates it, with its defaults, the next time that character logs in |
| **no character folder** | character | The character has no folder in the `WTF` folder of that account any more: you deleted or renamed it, or moved it to another realm. A leftover |
| **spec profiles** | character | The addon switches this character's profile by talent spec (LibDualSpec, see the [FAQ](#faq)) |
| **blacklisted** | addon | It's on your [blacklist](#the-blacklist): shown greyed out, can't be ticked or changed |
| **unlocked** | addon | A blacklisted addon you unlocked for this session (`u`) |

### Staged changes

A staged change shows in the tree as if it were already done, marked so you can tell:

| You see | Means |
|---|---|
| `✘ deleted` | The profile will be deleted (its characters are shown under the profile they move to) |
| `renamed from Old` | The profile will be renamed (it used to be called Old) |
| `copy of A` | A new profile, a copy of profile A |
| `was Old` | The character moves to this profile; it used Old before |
| `✘ removed` | The leftover character will be removed |

The **Staged** line on the left counts each kind ("2 deletes · 5 reassigns · 1 rename"). Press `x` to throw all
staged changes away. **Rescan** with changes staged asks first, and so does leaving the screen.

### The filters

| Filter | Shows |
|---|---|
| **Only addons with 2+ profiles** | Only the addons (databases) with at least two profiles: the ones worth tidying |
| **Only unused profiles** | Only profiles no character uses (By addon view) |
| **Leftover characters** (on) | Characters tagged "no character folder". Untick to hide them |
| **Blacklisted addons** (on) | Addons on your blacklist. Untick to hide them |

The search box (`/`) keeps only lines whose addon, profile or character name contains what you type (upper or
lower case doesn't matter). `Esc` takes you from the search box back to the tree.

## The changes you can make

Tick the profiles or characters a change should apply to (`Space`), or just highlight one. Ticking an addon, an
account or a game version ticks everything below it. Changes are made per addon database: a profile in ElvUI and a
profile with the same name in Bartender4 are two different profiles.

| Key | Change | What it does |
|---|---|---|
| `d` | **Delete profiles** | Deletes the ticked profiles. Their characters have to go somewhere, so a popup asks which profile they move to: "Default" to start with, or any other profile of that addon. If you're deleting every profile, "Default" included, you type a name instead |
| `p` | **Assign a profile** | Moves the ticked characters to a profile you pick from the list, or to a new name you type |
| `e` | **Rename a profile** | Renames the highlighted profile. Its characters follow it |
| `k` | **Copy a profile** | Copies the highlighted profile, settings and all, under a new name. Nobody uses the copy until you assign it |
| `o` | **Remove leftover characters** | Removes the ticked characters tagged "no character folder" from the addon's list |

A profile name can be up to 100 characters. Names are case-sensitive, as in the game ("healer" and "Healer" are two
profiles), and you can't rename or copy onto a name the addon already has.

If a change can't be made in some of the ticked addons (a blacklisted addon, say), it's made in the others and a
message lists the ones it skipped.

### Quick actions

`m` opens a menu with the quick actions. They work on the ticked addons, or on the highlighted one when nothing is
ticked:

- **Keep only Default**: deletes every profile except "Default" and moves everyone onto "Default".
- **Everyone → Default**: moves every character to "Default" and keeps the other profiles.
- **Tick all leftover characters**: ticks every character tagged "no character folder" that's shown, ready for
  `o`.
- **Discard staged changes**, and every key the bottom bar has no room for (`e`, `k`, `o`, `b`, `u`, `v`, `/`,
  `x`), so you can find them without this guide.

### The blacklist

Some addons you never want touched. Put them on the blacklist: they stay in the tree, greyed out, so you can still
see their profiles, but they can't be ticked or changed.

- `b` adds the highlighted addon to the blacklist, or takes it off. The blacklist is saved in the settings, where
  you can also edit it as a list of names.
- `u` **unlocks** a blacklisted addon for this session only: it can be changed until you close the tool, and it's
  tagged "unlocked". Press `u` again to lock it again.
- Blacklisting or locking an addon throws away any changes already staged for it, and says so.

An addon's name is its settings file's name without `.lua` (`ElvUI`, `Bartender4`), upper or lower case doesn't
matter.

## Keys on the review screen

| Key | Does |
|---|---|
| `Space` | Tick or untick the highlighted line |
| `a` / `n` | Tick everything shown / untick everything |
| `d` | Delete the ticked profiles |
| `p` | Assign a profile to the ticked characters |
| `e` | Rename the highlighted profile |
| `k` | Copy the highlighted profile |
| `o` | Remove the ticked leftover characters |
| `m` | Quick actions, and every key the bottom bar doesn't show |
| `x` | Discard all staged changes |
| `b` | Put the highlighted addon on the blacklist, or take it off |
| `u` | Unlock the highlighted blacklisted addon for this session, or lock it again |
| `v` | Switch view: By addon / By character |
| `/` | Search |
| `w` | **Apply** the staged changes (asks first; the answer starts on **No**) |
| `y` | **Dry run** (asks first; the answer starts on **Yes**) |
| `r` | Scan again |
| `z` | **Undo last change** (asks first; the answer starts on **No**) |
| `f` or `Esc` | Pick another game version (from the search box, `Esc` goes back to the tree) |
| `t` | Back to the tool menu |
| `s` | Settings |
| `q` | Quit |
| `←` `→` | Jump between the tree and the left panel |

Leaving with `f`, `Esc`, `t` or `q` while changes are staged asks first: they haven't been written, and leaving
throws them away.

## What the tool never touches

The tool changes only which profiles exist and which character uses which profile. It never touches:

- **The settings inside a profile.** A renamed profile keeps its settings exactly; a copy is a byte-for-byte copy.
- **The other parts of an addon's settings**: account-wide data, per-character data and the rest (Ace3's `global`,
  `char`, `realm` and so on sections). Addons often keep their own data there.
- **Settings files without Ace3 profiles**, Blizzard's own files (`Blizzard_*`) and backup copies (`.bak`,
  `.old`).
- **Any byte it doesn't need to change.** It doesn't rewrite the file the way the game does: it edits the exact
  lines that change and leaves every other character of the file as it was. Before writing, it reads the new
  file back and checks that only the planned changes are in it.

It never moves a profile from one addon, account or game version to another, and it doesn't import or export
profiles.

## Apply

When you press **Apply**, the bottom bar says "Checking whether WoW is running…" for a moment. If WoW is running
for a game version you're changing, it stops there and asks you to close it. Then a summary lists what's staged,
in which game versions, with alerts in red for anything worth a second look:

- a "Default" profile is being deleted;
- characters are moving to a profile that doesn't exist yet (the addon creates it with its defaults at the next
  login);
- some of the characters switch profile by spec, which overrides the change at login.

The answer starts on **No**. Once you press **Yes**, a progress window shows each step. For each game version the
tool:

1. **Checks every file again.** If a file changed since the scan (you logged a character out with the tool open,
   say), that file is **skipped** with "changed since the scan; rescan", and the others go ahead. Press `r`
   afterwards and stage that addon's changes again.
2. **Checks that no other program has the files open.** The Raider.IO client and the WeakAuras Companion are
   known to lock these files. If any is locked, nothing is changed; close that program and apply again.
3. **Backs up your whole `WTF` folder** into a zip and checks the zip.
4. **Saves the files it's about to change**, as they are now, into another zip. This is what Undo uses.
5. **Writes each file**, after checking the new version, and reads it back to make sure it landed.

If anything goes wrong while writing, every file already written in that game version is put back as it was, and
the run stops. With **All flavors**, the game versions are changed one after another; if one runs into a problem,
the versions after it aren't touched, and the versions before it keep their changes (Undo puts them back).

## Dry run

A **Dry run** (`y`) does everything Apply does except writing: it rechecks every file and builds and checks each
new version in memory. It writes nothing at all: no zip, no journal. It works while WoW is running. Its results
screen has a **Back to review** button (`Esc`) that takes you back with your staged changes still there.

## The results screen

The top table sums up the run: how many files were changed, skipped or put back, where the `WTF` backup and the
zip of the original files are, and the journal. The table below lists each change, by game version, account and
addon, and what happened to it ("changed", "would change" after a dry run, "skipped", "put back", "failed"),
with the reason when there is one.

From here, `r` scans again, `f` picks another game version, `t` goes back to the tool menu, and `q` quits.

## Undo last change

Changed your mind? **Undo last change** (`z`, the amber button) puts back every file the most recent Apply
changed, from the zip of the original files. It asks first, naming when that change ran and in which game versions.
Close WoW first: Undo refuses while it's running, just like Apply.

- A file is put back only if it's still exactly what the tool wrote. If WoW (or anything else) saved it since,
  it's **left as it is** and marked "changed since the change was made". Undo never overwrites settings you
  saved after the change.
- Before it puts anything back, Undo backs up your whole `WTF` folder again, so the undo itself can be undone by
  hand.
- Undo works on the most recent change, whichever game version you picked. It only goes back **one** change;
  after you undo, the button stays greyed out until your next Apply.
- Any changes you've staged and not applied yet are dropped (the confirm says so).

## Where your backups go

Unless you change it in settings, the backup folder is `<your WoW folder>\wow-tools`. The tool's files go into its
`ace-profiles` folder:

```
<backup folder>\ace-profiles\
  snapshots\snapshot-<flavor>-<YYYYMMDD-HHMMSS>.zip           your whole WTF folder, taken before each change and undo
  edited\edited-<flavor>-<account>-<YYYYMMDD-HHMMSS>.zip       the files a change edited, as they were before it
  edit-in-progress.json                                        only while a change is being written
<your WoW folder>\wow-tools\ace-profiles\
  journal\journal-<YYYYMMDD-HHMMSS>.jsonl                      the record Undo last change uses
```

`<flavor>` is the game version (`retail`, `classic_era` and so on) and `<account>` is the account you picked, or
`all`. If two runs start in the same second, the second gets `-2` added before `.zip`, so no backup ever replaces
another. The journals always stay in your WoW folder, even if you pick another backup folder.

- Only the newest 10 **WTF backups** (`snapshots`) of each game version are kept (you can change this in the shared
  settings, the first screen `s` opens; `0` keeps them all).
  One is taken before each change, each Undo and each recovery. They're a safety net in case something goes badly
  wrong.
- Only the newest 10 **journals** are kept (also a shared setting). An `edited` zip is deleted along with the last journal that needs it.
- To put files back by hand (an older change, say): close WoW, open the `edited\edited-…zip`, and extract it **into
  the game version's folder** (for example `World of Warcraft\_retail_`), keeping the folders. You can ignore
  `manifest.json`.

## If a change was interrupted

If the app is closed in the middle of an Apply (a power cut, or you closed the window), it notices the next time
the review screen opens and shows **An earlier change did not finish**, with the number of files and where their
originals are. It **never repairs anything on its own**. You choose:

- **Put the originals back**: each file the change had already written is put back from the zip of the original
  files. A file that's neither the original nor what the change wrote (WoW saved it since, say) is left as it is.
  This is guarded like Undo: refused while WoW is running, and your `WTF` folder is backed up first.
- **Leave as is**: the files stay as they are now; the zips are kept.

If you close the message with `Esc`, it's shown again next time, and when you press **Apply**: a new change
can't start until you've chosen, since it would lose the way back for the earlier one.

## Settings

Press `s` in the tool (you get the shared settings first: WoW folder, backups and journals to keep; then this
tool's settings). The tool's settings are saved in
`config\ace-profiles.cfg`.

| Setting | Starts as | What it means |
|---|---|---|
| Backup folder | empty | Where the `WTF` backups and the zips of edited files go: they're put in its `ace-profiles` folder. Empty means `<WoW folder>\wow-tools`. It must be a full path (such as `D:\WoW backups`), and it can't be your WoW folder itself or inside a game version's `WTF`, `Interface` or `Screenshots` folder |
| Blacklist | empty | Addon names, separated by commas, that are shown but never changed |

The file itself uses these names, if you edit it by hand: `backup_dir`, `blacklist`, `last_flavor_choice` (the
game version you picked last time; empty means **All flavors**) and `last_account` (empty means all accounts).

Backups and journals to keep are shared by every tool: they're on the first screen `s` opens (the one with
your WoW folder), and saved as `keep_backups` (10; `0` keeps all) and `keep_journals` (10) under `[general]`
in `config\wow-tools.cfg`. The WTF backups (`snapshots`) follow `keep_backups`.

## FAQ

| Question | Answer |
|----------|--------|
| Which addons does it show? | Every addon that keeps its profiles with Ace3's database library (AceDB). Profile systems that aren't Ace3 (WeakAuras, or the profiles Plater and Details manage themselves) aren't covered. |
| Why is a profile "missing"? | A character points at a profile that has no settings saved. That's normal: the addon creates it, with its defaults, when that character next logs in. Moving characters to a new name you typed does the same. |
| I removed a leftover character and it came back. | Logging in on that character (or a new character with the same name and realm) makes the addon add it again. "No character folder" means WoW has no folder for it in that account right now; if you still play it, leave it alone. |
| What is LibDualSpec, and why "spec profiles"? | Some addons can switch your profile automatically when you change talent spec, using a library called LibDualSpec. For a character with that switched on, the spec setting wins at login, so assigning it another profile here may not stick. Renaming or deleting a profile updates its spec settings too, as the game would. Turn spec switching off in the addon's own options if you want a fixed profile. |
| Can I delete "Default"? | Yes, but most addons put every new character on "Default", and recreate it with its defaults when one logs in. The confirm warns you. "Keep only Default" is usually what you want instead. |
| Are my settings inside a profile safe? | Yes. The tool never changes what's in a profile: a renamed profile keeps its settings exactly, and a copy is an exact copy. |
| Can I copy a profile to another addon, account or game version? | No. Profiles belong to one addon on one account; copying works within the same addon only. |
| What's the difference between Dry run and Apply? | A **Dry run** checks every staged change and shows the results without writing anything. **Apply** writes them, after backing everything up. |
| Can I undo a change from last week? | **Undo last change** only goes back to the most recent change. For an older one, unzip its `edited` zip by hand; see [Where your backups go](#where-your-backups-go). |
| Does it work on a Mac? | Yes, but the "WoW is running" check can't tell on a Mac, so close WoW yourself first. |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "WoW is running … Close it first" | Close that game version's WoW and try again. WoW would overwrite the changes when you log out. |
| A file was "skipped: changed since the scan; rescan" | WoW (or another program) saved that file after the scan. Press `r` to scan again, stage that addon's changes again and apply. The other files were changed as planned. |
| My changes were undone after I played | WoW was running while you applied, or an addon synced its profiles back. Close WoW completely, apply again, then start the game. |
| "files are locked by another program" | Close the Raider.IO client or the WeakAuras Companion, then apply again. Nothing was changed. |
| An addon is missing from the tree | It doesn't use Ace3 profiles, its file is blacklisted and hidden (tick **Blacklisted addons**), or a filter or search hides it. If its file couldn't be read, it's listed under **Scan warnings** at the bottom of the tree. |
| "Not staged" with a list of addons | The change couldn't be made in those addons (blacklisted, a name already taken, …); the message says why for each. It was made in the others. |
| A character keeps a profile I changed | It has **spec profiles**: LibDualSpec switches its profile by spec at login. See the [FAQ](#faq). |
| "An earlier change did not finish" | See [If a change was interrupted](#if-a-change-was-interrupted). |
| "Backup folder not allowed" | The backup folder in settings is a relative path, your WoW folder, or inside a game version's `WTF`, `Interface` or `Screenshots` folder. Press `s` and pick another folder, or leave it empty for the default. |
| **Undo last change** is greyed out | There's nothing to undo: you haven't applied a change yet, or you already undid the last one. |
| A file is "left as it is" after Undo | WoW saved it after the change, so putting the old version back would lose those settings. To go back anyway, close WoW and unzip it from the `edited` zip by hand. |
| Something else looks wrong | Follow [Reporting a bug](../README.md#reporting-a-bug) in the main README. |
