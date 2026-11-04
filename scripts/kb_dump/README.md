# KaosKbDump: the knowledge-base dump addon

A developer-only WoW addon. It records what each game client knows about its CVars and slash commands, so
`scripts/refresh_kb.py` can rebuild the knowledge base the Config Editor, Config Copier and Macro Editor read
(`wowtools/kb/cvars/<flavor>.json`, `wowtools/kb/slash_commands/<flavor>.json`). Like everything under `scripts/`,
it never ships with the app, and the app never runs it.

## What it records

`/kbdump` writes one table, `KaosKbDumpDB`, to the addon's SavedVariables:

- `build`: the client version and build (`GetBuildInfo()`), for example `12.0.5 61234`.
- `cvars`: every console command of type CVar (`C_Console.GetAllCommands()`), each with its help text and console
  category, and from `C_CVar.GetCVarInfo()` its default, current value, whether the server stores it per account
  or per character, and its locked, secure and read-only flags.
- `commands`: every slash command (`/cast` = `CAST`), from the `SLASH_*` globals and `hash_SlashCmdList`, and every
  emote (`/dance` = `EMOTE35`, from the `EMOTE<n>_CMD<m>` globals).
- `addonCommands`: the keys of the commands an addon registered (`issecurevariable` says the entry is tainted).
- `macroLimits`: how many account macros and macros per character the client allows (`MacroConstants`).
- `dumpVersion`: 2. A dump without it comes from the first version of the addon, which recorded no emotes, did not
  tell addon commands apart and had no macro limits: `refresh_kb.py` then writes only the CVars.

`refresh_kb.py` keeps the defaults, help and flags, leaves the addon commands out and writes the macro limits into
`macro_limits.json`. It drops the current values: those are your own settings, not the client's.

## Run it (once per flavor, again after a patch)

1. Copy the `KaosKbDump` folder into each installed flavor's AddOns folder, for example
   `World of Warcraft/_retail_/Interface/AddOns/KaosKbDump/`, and the same under `_classic_`, `_classic_era_`,
   `_anniversary_` and `_forever_`.
2. Start that flavor and log in to any character. If the addon shows as out of date, tick "Load out of date
   AddOns" on the character screen's AddOns list.
3. Type `/kbdump`. It prints how many CVars and slash commands it recorded.
4. Log out (or `/reload`). The game writes
   `World of Warcraft/<flavor>/WTF/Account/<ACCOUNT>/SavedVariables/KaosKbDump.lua`.
5. Repeat for every flavor, then remove the addon again if you like (its SavedVariables file can stay).

## Rebuild the knowledge base

```sh
python3 scripts/refresh_kb.py --wow "/path/to/World of Warcraft"          # every flavor with a dump
python3 scripts/refresh_kb.py --wow "/path/to/World of Warcraft" --wiki   # plus the reviewed wiki notes
```

For each flavor it uses the newest `KaosKbDump.lua` of any account. A flavor with no dump is skipped with a message
and keeps its older files, so the tools show its CVars as unknown until a dump arrives. `--out DIR` writes somewhere
other than `wowtools/kb/`. The script never uses the network.

A flavor you can't dump yet can stand in with another flavor's data:

```sh
python3 scripts/refresh_kb.py --wow "/path/to/World of Warcraft" --wiki --provisional _forever_=_retail_
```

writes `_forever_`'s files as a copy of `_retail_`'s from this run, marked `"provisional": "copied from _retail_ until a
_forever_ dump exists"`. Once `_forever_` has its own dump, the same command writes the real files instead; it takes a `dumpVersion` 2
dump to replace the slash commands and macro limits (a first-version dump replaces only the CVars).

`--wiki` adds plain-English notes from `scripts/kb_dump/wiki_notes.json` for CVars whose Blizzard help is empty or
cryptic:

```json
{"cvars": {"<CVar name>": {"text": "<our own words>", "source": "https://warcraft.wiki.gg/wiki/<page>"}}}
```

Every note is written in our own words, never copied from the wiki, and names the warcraft.wiki.gg page it rests
on. A note without text or without a warcraft.wiki.gg source stops the run. A note for a CVar the dump doesn't have
is ignored. Review the JSON diff before committing it.
