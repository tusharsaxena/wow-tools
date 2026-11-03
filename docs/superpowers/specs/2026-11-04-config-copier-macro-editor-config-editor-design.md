# Config Copier, Macro Editor, Config Editor and the launcher fix: design

Date: 2026-11-04. Issues: #14 (Config Copier), #12 (Macro Editor), #13 (Config Editor), plus the Windows
"window flashes and nothing happens" report from Reddit (no issue). Follow-up filed: #15 (account-level copy).
Plan: `../plans/2026-11-04-config-copier-macro-editor-config-editor.md`, ledger `….status.md` beside it.

Decision IDs: `LN` launcher, `X` shared, `CC` Config Copier, `ME` Macro Editor, `CE` Config Editor. "User" means
the decision came from the user in the 2026-11-04 session; "builder's call" marks a choice made for them, which the
user may still reverse at review.

## Why

- **Config Copier (#14).** The user sets up alts by hand-copying a main's client files (macros, chat, layout,
  CVars, enabled addons), mostly onto existing characters. They want it done in one reviewed, undoable step.
- **Macro Editor (#12).** The user has many click-cast macros on one character, wants to move them to another and
  rework spell names, and doesn't know macro commands and conditionals by heart. They want an editor that teaches
  and checks as they write, shrinks macros under 255 characters, and starts from templates.
- **Config Editor (#13).** One place to see and change every CVar at all three file levels, with plain-English
  help and defaults for every known CVar, and a small set of sourced recommendations.
- **Launcher fix.** A user double-clicked `wow-tools.cmd`, saw a window flash and close, and found no `logs/`
  folder. Any failure before the event log opens is invisible today.

## Verified in the client (2026-11-04, on the user's Retail install, test character Testwarrka)

These facts are what the design rests on. Record them in the guides and the internals docs.

**V1 `cache.md5`.** A binary index in each account and character folder: one 24-byte record per synced file
(16-byte MD5, 4-byte little-endian timestamp, 4 zero bytes), at fixed slots per file type. Character slots seen:
config-cache, bindings-cache (all zeros when the file is empty), macros-cache, layout-local, chat-cache,
tts-cache, flagged-cache, click-bindings-cache, edit-mode-cache-character, cooldownmanager. `AddOns.txt` is not
tracked.

**V2 A copied file wins over a stale index.** Five files were copied from Aellâ to Testwarrka with WoW closed,
leaving `cache.md5` stale. At login the client used the copied macros, chat and config (Assisted Highlight came
across). At logout it rewrote `cache.md5` with the new fingerprints and made its own `.old` files. Nothing was
reverted from the server. So: **copy or edit the plain file; never touch `cache.md5` or `.old` files.**

**V3 The client tidies some state by itself at logout.** It dropped tracked quests the character doesn't have and
pruned the reputation list. Talent loadout IDs, renown and tutorial flags stayed.

**V4 Macro file format (Retail).** Not the `MACRO <id> …` the issue guessed:

```
VER 3 0100000000000005 "D Up" "132360"
<body lines>
END
```

CRLF line endings, UTF-8 bytes. The ID is 16 hex digits: `00…` prefix for account macros, `01…` for character
macros, numbered per file (two characters can both have `…1B`). The icon is a file ID (`134400`, the "?" auto icon)
or a texture name (`INV_Misc_QuestionMark`, either case). Names are cut at 16 characters ("Celestial Condui"). The
client re-sorts macros by name when it saves.

**V5 Macro IDs.**

| Test | Client did |
|---|---|
| New macro, next free ID | kept it |
| New macro, ID with a gap (`…80`) | kept it |
| New macro with an ID already in use | **renumbered the new one** to highest + 1; the existing macro kept its ID |
| New account macro, next free ID | kept it |
| Existing macro's ID changed | **its action bar button disappeared**: buttons point at macro IDs |

## Scope

In:

- Launcher fix (LN1-LN8).
- Three new tools in the suite: Config Copier (`config-copier`), Macro Editor (`macro-editor`), Config Editor
  (`config-editor`), each a full tool per [adding-a-tool.md](../../adding-a-tool.md): registry row, flow, screens,
  settings, events, help, guide, internals doc, README row, CHANGELOG line, release manifest entry for its guide.
- The shared pieces they need, in `core/` and `ui/` (X1-X8).
- An offline knowledge base shipped in the app (X6), a dev-only dump addon and refresh scripts that build it.

Out (non-goals):

- Account-level file copy (#15).
- Copying bindings, click-bindings, Cooldown Manager or Edit Mode files (user: server-side, class-specific).
- Copying between flavors in Config Copier (user: one flavor per run).
- Spell-name checking or suggestions in the Macro Editor (user: spell names are free text).
- SavedVariables copy ("Character Cloner", I17 in #11).
- Any network use by the app. Refresh scripts may use the network; the app never does.

Anti-goals (a failure even if it "works"):

- A copy or edit the client silently reverts or that breaks a target's action bars without warning.
- A file changed byte-for-byte where the user changed nothing.
- A knowledge-base entry that guesses: an unknown CVar or command is shown as unknown, never described from
  imagination. Every description and recommendation carries its source.
- A tool that looks or behaves differently from the other five without a recorded reason.

## Launcher fix (LN)

| # | Decision |
|---|---|
| LN1 | User: `wow-tools.cmd` keeps the window open when it was **double-clicked** and the exit code is not 0 (detect `%cmdcmdline%` containing `/c` and the script's own name; Explorer and a desktop shortcut both qualify). Started from an open terminal, it behaves as today. The `pause` lives on the same last line as the Python call (F-020 rule, `tests/test_launcher.py`). |
| LN2 | User: before running Python, the `.cmd` checks that a usable interpreter exists: `py -3` if `py` is on PATH, else `python`. A run of `-c` that checks `sys.version_info >= (3, 10)` tells apart "none" (the Microsoft Store placeholder exits 9009), "too old" and "fine". None or too old: a plain message naming what was found and pointing at README → Installing Python, then the pause. `wow-tools.sh` does the same check for `python3`. |
| LN3 | User: "Could not create the lock file …" gains a hint: the folder isn't writable, so move wow-tools out of `Program Files` (or another protected folder) into a folder you own. The same hint goes on the other pre-log `OSError` messages in `suite.run()` that are about writing in the app folder. |
| LN4 | User: every launch is logged. Each launcher appends a `launcher.started` line before Python (time, arguments, interpreter command it chose, platform) and a `launcher.exited` line after (exit code), plus `launcher.python_missing` / `launcher.python_too_old` when LN2 stops it. |
| LN5 | User: Python failures before `init_event_log` (the Python check in `__main__.py`, lock, config load, any uncaught exception before the log opens) are appended as `bootstrap.failed` (where, type, message, the traceback's last lines) by a small stdlib-only writer in `core/bootstrap.py`. |
| LN6 | User (recommended by builder): these records go to `logs/suite/`, beside the suite's own log. Builder's call: one file, `logs/suite/launcher.log`, not one per date, because `cmd.exe` has no locale-independent date without starting PowerShell. Each line is `<local time as the shell gives it> <event> key=value …`; Python's writer uses the same shape with ISO time. The suite trims `launcher.log` at start (lines older than `log_retention_days`, or by size if dates can't be parsed: builder decides the exact rule). If `logs/suite/` can't be created or written, the launcher skips logging silently (the pause still shows the error). |
| LN7 | User approved the deviation: the launcher and bootstrap records are written outside `log_event` (STD-6.1, STD-6.6). Their names are still registered in `core/events.py` so `docs/events.md` lists them. Add a row to [Documented deviations](../../standards.md#documented-deviations). |
| LN8 | `wow-tools.sh` can no longer `exec` Python (it must write the exit line), so its body must be parsed whole before it runs (one `{ …; exit; }` block or a function called on the last line), keeping the update-safety property the `.cmd` has. README FAQ gets a row for "the window flashes and closes" and the folder hint. CHANGELOG line. |

## Shared pieces (X)

| # | Decision |
|---|---|
| X1 | **Flavor picker.** All three tools start at the shared `FlavorScreen` with its "All flavors" entry (STD-7.3). The tree's top level is the flavor when "All flavors" is chosen. Config Copier limits targets to the source's flavor (other flavors are shown greyed with a one-line reason), so it needs no deviation. |
| X2 | **Character tree.** One shared widget/helper for "account › realm › character" trees with ticks at every level (ticking a node ticks everything under it), `x` expand all, `c` collapse all, per [one look and feel]. Built on `core/install.py`'s `Account` / `Character`. |
| X3 | User (confirmed guess): **folders that aren't real characters are ignored** by the three new tools. WoW character names have no spaces, digits or punctuation, so a folder under a realm whose name has anything but letters (e.g. `Testwarrka - Copy`) is not a character. Builder's call (builder check Q1): an opt-in helper in `core/install.py` that only the new tools call; `Account.characters()` and the five existing tools are unchanged, because filtering there would change what the WTF Cleaner proposes for deletion. Filing an issue for the existing tools is a follow-up, not part of this build. |
| X4 | User (confirmed guess): **only client-named files are touched.** `macros-cache - Copy.txt` and the like are never read as client files. Each tool works from an explicit list of file names. |
| X5 | **Writing client files safely.** All three tools change files in account and character folders outside `SavedVariables`. They go through the suite's safety nets (STD-5.10 to 5.18, 5.27): refuse while that flavor's WoW runs, Dry run that changes nothing, originals zip of every file replaced or deleted, crash marker and journal before the first write, atomic write and read-back, Undo of the last run, recovery after a crash. Builder's call on how: prefer making the shared SavedVariables pipeline (`core/sv_apply`, `core/sv_undo`, `SvGuard`) take a pluggable guard and file list over writing a second pipeline; the guard for these tools accepts only listed file names directly in an account or character folder of the flavor's `WTF/Account`. Write a parallel pipeline only if the generalisation would bend the SavedVariables one, and record why. |
| X6 | **Knowledge base (KB).** Versioned JSON data under `wowtools/kb/` (ships with the app, since `wowtools/` is in `RELEASE_SHIPS`), loaded by a UI-free `core/kb.py`. Contents: CVars per flavor (X7), the CVar state list (CC5), macro slash commands and conditionals per flavor, macro templates, optimizer rules, CVar recommendations. Every entry that carries text has a `source` (URL or "client dump <flavor> <build>"). A missing entry means "unknown". |
| X7 | User: **the CVar base comes from an in-game dump plus wiki text.** A dev-only addon (lives under `scripts/`, which never ships) calls `C_Console.GetAllCommands()` and `C_CVar.GetCVarInfo()` (value, default, `isStoredServerAccount`, `isStoredServerCharacter`, locked/secure/read-only flags) and writes them to its SavedVariables. A refresh script reads each flavor's dump with `core/luasv`, layers plain-English descriptions from warcraft.wiki.gg where Blizzard's help text is missing or cryptic (each with its URL; cached so reruns are repeatable), and writes the per-flavor JSON with the client build number. User: **every installed flavor** (`_retail_`, `_classic_`, `_classic_era_`, `_anniversary_`, `_forever_`). Builder's call (builder check Q2): wiki text is **rewritten in our own words** with the page URL as its source, never copied word for word, so no CC BY-SA text ships in the MIT app; the refresh script uses the MediaWiki API and its fetch cache stays out of the repo (`scripts/` or a git-ignored folder). Builder's call (Q3): the dump addon also records the client's slash commands (`SLASH_*` globals and `hash_SlashCmdList`) per flavor, which feeds ME5/ME8; macro conditionals and `@unit` targets are curated from the wiki's macro-conditional pages (rewritten, sourced), each marked with the flavors the source says it applies to, and "flavor not stated" where it doesn't say, in which case ME5 does not warn. The user installs the addon and runs it once per flavor; the plan must make that a clear, early user step, and the tools must work (as "unknown") for a flavor with no dump yet. |
| X8 | The CVar data's own `isStoredServer*` flags give each CVar's scope (machine `Config.wtf`, account, character) and whether the client syncs it; the category comes from the client's console category, mapped to the issue's groups (graphics, sound, interface, camera, nameplates, combat text, network, other). Builder decides the mapping table. |

## Config Copier (CC), issue #14

| # | Decision |
|---|---|
| CC1 | User: name **Config Copier**, id `config-copier`, package `tools/config_copier`. |
| CC2 | User: flow = pick a **source** character → tick **targets** in the X2 tree (account › realm › character, every account of the source's flavor; the source can't be ticked) → tick **files** → **review** → copy. Usually pushing to many existing characters, sometimes one new alt. |
| CC3 | User: a **fixed file list**, all ticked by default: `macros-cache.txt`, `AddOns.txt`, `chat-cache.txt`, `config-cache.wtf`, `layout-local.txt`. Nothing else is offered. Adding a file later is a code change after a client check. |
| CC4 | User: **review** shows, per target and file: new, replaced or unchanged. Every replaced pair opens a **diff**. The user can drop any single (target, file) pair and copy the rest. |
| CC5 | User: `config-cache.wtf` is **merged, not copied**. The source's *preference* CVars replace the target's preference CVars exactly: a preference CVar the target has and the source doesn't is removed. The target keeps its own *state* CVars. "State" is a curated list in the KB (seed it from the 2026-11-04 diff: `savedClassConfig*`, `hardTrackedQuests`, `trackedAchievements`, `lastSelectedClubId`, `lastRenownForCovenant*`, `garrison*`, tutorial flags such as `closed*`/`*Tutorial*`, season markers `new*Season`, `latest*`, `eventSchedulerLastUpdate`, `highestUnlocked*`, `maxLevelSpecsUsed`, collapsed-list markers `reputationsCollapsed`/`currencyCategoriesCollapsed`, `unlockedMajorFactions`). Builder check Q4: the full 2026-11-04 diff, as seen on Aellâ (source) and the original Testwarrka (target), is in the appendix below; every CVar there that records progress, history, IDs or UI bookkeeping goes on the state list. The list is names plus a few name patterns (`closed*`, `*Tutorial*`, `last*`, `new*Season`, `saved*Config*`, `garrison*`, `*Collapsed`), each pattern checked against the flavor's CVar dump so it can't catch a real preference by accident. Builder's call: a CVar not on the state list counts as a preference, and the review's config diff marks which lines are state (kept) and which are preferences (copied/removed). Line order: keep the target's order for kept lines and append new ones; the client rewrites the file anyway. |
| CC6 | All other files are a plain byte copy. `cache.md5` and `.old` files are never touched (V2). |
| CC7 | Builder's call from V5: copying `macros-cache.txt` onto a character that already has macros replaces their IDs, so its action bar buttons may point at a different macro or at nothing. The review shows a warning on every such pair ("action bar buttons that use macros may need placing again"). No warning for a target with no macros. |
| CC8 | Safety per X5. Undo puts back every replaced file and removes every file the run created. |

## Macro Editor (ME), issue #12

| # | Decision |
|---|---|
| ME1 | Name **Macro Editor**, id `macro-editor`, package `tools/macro_editor` (issue title; builder's call to keep it). |
| ME2 | **Browse screen** (mockup agreed 2026-11-04): left pane with search (names and/or bodies, "show all / matching"), action buttons New, Edit, Delete, Copy, Paste…, Replace text…, key hints. Main tree: (flavor ›) account › "Account macros" and realm › character › macros, with ticks. Each set shows slot use (`12/30`, `30/30 FULL`), each macro its name, first body line and `n/255`. |
| ME3 | **Slot limits per flavor** from the KB (Retail 120 account / 30 per character; builder confirms each flavor from the client's FrameXML constants and records the source). A paste or New that would overflow a set is refused for that set in the review. |
| ME4 | User: **copy/paste** = tick macros, Copy, tick one or more target sets (characters and/or account macros) in the same tree, Paste… → review. Name clash at a target: skip, rename or overwrite, chosen per clash with an "apply to all" option. |
| ME5 | User: **across flavors** is allowed between any two flavors. The review carries a clear warning that the macro may not work there. Builder's call: it also flags commands and conditionals the target flavor's KB doesn't know. |
| ME6 | From V5: editing never changes a macro's ID. A new or pasted macro gets the target file's highest ID + 1 with the right prefix (`00…` account, `01…` character). **Overwrite keeps the target macro's ID** and replaces its name, icon and body, so the target's action bar keeps working. Delete warns that action bar buttons using the macro will be removed. |
| ME7 | User: **Replace text…** = find and replace across the ticked macros, with a before/after preview, staged like any other edit. Editing one by hand stays available. |
| ME8 | **Edit screen**: name (16-character limit from V4), icon (free text: a file ID or texture name; default the "?" icon `134400`), scope label, a live `n / 255` meter that refuses Save over the limit. A text editor with **suggestions as you type** (slash commands, conditionals, `@unit` targets) and a **help panel** that explains whatever is under the cursor and reads a whole `[...]` block out in plain English. `F1` opens the full command and conditional reference. |
| ME9 | User: **conditional builder** (`b`): a popup with radio buttons and checkboxes (target, help/harm, states and modifiers). Builder's call: it is two-way: opened on an existing `[...]` it is filled from that block, and OK rewrites that block. |
| ME10 | User: **optimizer** (`o`): shows a before/after diff with the reason for each cut and changes nothing until Apply. Builder's call: it only applies rewrites that are provably the same in game (e.g. `target=` → `@`, dropping spaces the parser ignores, `/use` for `/cast` where WoW treats them alike, removing a duplicated condition); each rule lives in the KB with its source. |
| ME11 | User: **templates** (`t`): a curated set of common macros (mouseover heal, cursor ground-target, focus interrupt, …) with placeholders the user fills in. Each template is KB data with a source. |
| ME12 | User: spell names are free text. No spell database. |
| ME13 | Writing: byte-exact for every macro not changed; CRLF; the client's `VER 3 <id> "<name>" "<icon>"` / body / `END` layout. Unchanged order is kept; new macros are appended (the client re-sorts). Safety per X5; one Apply writes every staged change across files and is one Undo. |
| ME14 | Formats in other flavors: the reader recognises the Retail `VER 3` layout. The builder checks the other installed flavors' files (from fixtures the user can supply on request, never by reading a real install in tests) and supports what they use; a file in a layout it doesn't know is shown read-only with a warning. |

## Config Editor (CE), issue #13

| # | Decision |
|---|---|
| CE1 | Name **Config Editor**, id `config-editor`, package `tools/config_editor` (issue title; builder's call to keep it). |
| CE2 | User: used for everything about equally: browsing, setting hidden CVars, resetting odd ones, tuning graphics. No single mode leads. |
| CE3 | **Files**: `WTF/Config.wtf` (machine), `WTF/Account/<A>/config-cache.wtf`, `WTF/Account/<A>/<Realm>/<Char>/config-cache.wtf`, in every installed flavor. Tree: (flavor ›) Config.wtf, account › account config, realm › character config. |
| CE4 | **CVar list** for the chosen file: every CVar the file sets plus, with a "show all known" switch, every CVar the KB knows for that flavor and scope. Each row: name, value in this file (or "not set"), default, changed-from-default mark, category. The help panel shows the description (Blizzard text and/or wiki text, each with source), type and allowed values where known, default, scope and whether the client syncs it, and the recommendation if any. |
| CE5 | **Edits**: set a value, add a CVar, remove one, toggle a boolean in place, reset to default. Builder's call: reset removes the `SET` line, since a missing line means the client default. Adding a CVar to a file whose level doesn't match the KB scope gets a warning, not a refusal. Unknown CVars can be edited, labelled unknown. |
| CE6 | **Filters**: category (X8) and "changed from default"; search by name and description. |
| CE7 | User: **a small curated set of recommendations** in v1 (a few dozen across nameplates, camera, combat text, graphics and similar), each with a source link, applied one at a time or as a reviewed batch. The builder researches and sources them; an unsourced recommendation is not shipped. |
| CE8 | Writing: byte-exact where nothing changed; `SET <name> "<value>"` lines with the file's own line endings; changed lines keep their place, added lines are appended. Safety per X5; every staged change in one Apply, one Undo. |

## Builder check answers (2026-11-04)

- Q5 (account-level `config-cache.wtf` survives login?): not tested on its own. Evidence: V5's T4 shows an
  account-level synced file (`macros-cache.txt`) edited by hand survives login and logout, and V1 shows the account
  folder uses the same `cache.md5` scheme. Builder's call: treat account-level config the same as character-level,
  and have the Config Editor guide ask users to report a revert. No in-client test blocks the build.
- Q6 (ship the launcher fix separately?): user: one spec and plan for all four. Builder's call: the launcher fix
  is the plan's first milestone, pushed when done, so the user can choose to merge or release it early on its own.
- `_forever_` has no entry in `FLAVOR_NAMES`; builder's call: add it as "Forever" unless the user names it
  otherwise.

## Appendix: the 2026-11-04 config-cache diff (CC5 seed)

Aellâ only (source): `EJDungeonDifficulty`, `EJRaidDifficulty`, `TTSUseCharacterSettings`, `assistAttack`,
`assistedCombatHighlight`, `autoQuestPopUps`, `calendarShowResets`, `cameraSavedVehicleDistance`,
`closedExtraAbiltyTutorials`, `clubFinderPlayerSettings`, `covenantMissionTutorial`, `dragonRidingRacesFilter`,
`eventSchedulerLastUpdate`, `garrisonCompleteTalent`, `garrisonCompleteTalentType`,
`highestUnlockedTieredEntranceTier`, `lastRenownForCovenant1`, `lastSelectedClubId`, `latestSplashScreen`,
`latestTransmogSetSource`, `lfgSelectedRoles`, `maxLevelSpecsUsed`, `nameplateMaxScaleDistance`,
`nameplateMinScaleDistance`, `nameplatePlayerMaxDistance`, `nameplateSelectedAlpha`, `newDelvesSeason`,
`newMythicPlusSeason`, `newPvpSeason`, `pvpSelectedRoles`, `savedClassConfigOne`, `savedClassConfigTwo`,
`savedClassConfigThree`, `seenPurchasableClassCapstone`, `showArenaEnemyFrames`, `soulbindsActivatedTutorial`,
`soulbindsLandingPageTutorial`, `soulbindsViewedTutorial`, `transmogCurrentSpecOnly`.

Testwarrka only (target): `EJSelectedTier`, `enableMultiActionBars`.

Both, different values: `EJLootClass`, `cameraSavedDistance`, `cameraSavedPitch`, `closedInfoFrames`,
`currencyCategoriesCollapsed`, `hardTrackedQuests`, `reputationsCollapsed`, `trackedAchievements`,
`unlockedMajorFactions`.

Builder's reading (state, kept on the target): `EJSelectedTier`, `closed*`, `*Tutorial*`, `clubFinderPlayerSettings`,
`eventSchedulerLastUpdate`, `garrison*`, `highestUnlockedTieredEntranceTier`, `lastRenownForCovenant*`,
`lastSelectedClubId`, `latest*`, `maxLevelSpecsUsed`, `new*Season`, `savedClassConfig*`,
`seenPurchasableClassCapstone`, `hardTrackedQuests`, `trackedAchievements`, `reputationsCollapsed`,
`currencyCategoriesCollapsed`, `unlockedMajorFactions`, `cameraSaved*` (camera position, not a setting),
`lfgSelectedRoles`, `pvpSelectedRoles` (role choice depends on class). Everything else above is a preference.

## Constraints

- [docs/standards.md](../../standards.md) in full. Known touch points: STD-5 (data safety) for every write; STD-6
  (events, with the LN7 deviation); STD-7 and STD-8 (look and feel, keys: two-pane review, ticks, `x`/`c`,
  labelled buttons, 120x30 design size that grows, 80x24 still works); STD-10 (tests never touch a real install or
  the network: synthesize client files in `tests/fixtures.py` temp trees, never copy the user's files into the
  repo); STD-1.4 (stdlib + vendored packages only); STD-2.1/2.2 (no tool imports another; shared code in `core/`
  or `ui/`).
- Each tool's guide is shipped (`RELEASE_SHIPS` gets its `docs/<tool>.md`); the KB ships inside `wowtools/`;
  the dump addon and refresh scripts stay out.
- Release notes follow the short changelog style (major features only).

## Left to the builder

Module boundaries inside each package, screen and widget code, how the X5 generalisation is done (within X5's
preference), the category mapping (X8), the exact optimizer rule set and templates (within ME10/ME11), the exact
recommendation set (within CE7), the trim rule for `launcher.log` (within LN6), test layout, and the order of work
(the plan). Builder's calls listed above are reversible at review.

[one look and feel]: ../../architecture.md#look-and-feel-and-terminal-size
