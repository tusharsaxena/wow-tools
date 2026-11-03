# The knowledge base

Static data the Config Copier, Macro Editor and Config Editor read, shipped with the app and read only by
`wowtools/core/kb.py`. The app never fetches any of it: every file here is committed, and the app never uses the
network.

## The sources rule

Every entry that carries text names its `source`: a URL, or `client dump <flavor> <build>` for data the game client
reported itself. Text from the wiki is rewritten in our own words, never copied, and keeps the page's URL as its
source. Nothing is guessed: a CVar, command or flavor the data does not cover shows as unknown in the tools. An entry
without a source is not shipped.

## Files

| File | What it holds | Built by |
|---|---|---|
| `cvars/<flavor>.json` | Every CVar of one flavor (`_retail_`, `_classic_` ...) | `scripts/refresh_kb.py` from the dump addon |
| `slash_commands/<flavor>.json` | The flavor's slash commands (`/cast` -> `CAST`) | `scripts/refresh_kb.py` from the dump addon |
| `cvar_state.json` | The CVars that are a character's state, not a preference | by hand |
| `macro_limits.json` | Macro slots per flavor | by hand, from the client's UI source |

A flavor without a `cvars/<flavor>.json` has no CVar data yet: the tools treat each of its CVars as unknown.

### `cvars/<flavor>.json`

```json
{"flavor": "_retail_", "build": "12.1.5 70688", "source": "client dump _retail_ 12.1.5 70688",
 "cvars": {"<name>": {"default": "1", "help": "<Blizzard's help text>", "category": "game",
                      "scope": "account", "synced": true, "locked": false, "readonly": false,
                      "wiki": {"text": "<our own words>", "source": "https://warcraft.wiki.gg/wiki/<page>"}}}}
```

`scope` is where the client keeps the CVar (`machine` = `WTF/Config.wtf`, `account`, `character`); `synced` is true
when the server stores it. `category` is the client's console category, lowercased; `core/kb.py` maps it to the
Config Editor's groups (graphics, sound, interface, camera, nameplates, combat text, network, other). `wiki` is
optional and is only used with its source. The dumping character's own values are never stored.

### `slash_commands/<flavor>.json`

`{"flavor", "build", "source", "commands": {"/cast": "CAST", ...}}`, the slash in lower case.

### `cvar_state.json`

`{"source", "names": [...], "patterns": [...], "exceptions": [...]}`. A CVar is state when its name is in `names` or
matches one of the `patterns` (fnmatch: `*` is any run of characters), unless it is in `exceptions`; all matched
without regard to case, as the client matches CVar names. Every other CVar is a preference. The Config Copier keeps
the target character's state CVars and copies the source's preferences. When a pattern catches a real preference in a
flavor's CVar list, add that name to `exceptions`.

### `macro_limits.json`

`{"flavors": {"<flavor>": {"account": 120, "character": 30, "build": "...", "source": "<URL>"}}}`. A flavor with no
entry here (or one without a source) uses Retail's values, and the Macro Editor says they are unconfirmed.
