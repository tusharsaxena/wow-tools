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
| `cvar_categories.json` | The Config Editor's group of every CVar in any `cvars/<flavor>.json` | by hand, from each CVar's name and help |
| `macro_limits.json` | Macro slots per flavor | by hand from the client's UI source, or `scripts/refresh_kb.py` from the dump addon |
| `macro_reference.json` | Macro commands, conditionals and `@unit` targets, with help and plain-English phrases | by hand, from the wiki |
| `macro_templates.json` | The Macro Editor's templates | by hand |
| `optimizer_rules.json` | The Macro Editor's optimizer rules and why each is the same in game | by hand |
| `recommendations.json` | The Config Editor's recommended CVar values, with the reason and the source of each | by hand, from the wiki |

A flavor without a `cvars/<flavor>.json` has no CVar data yet: the tools treat each of its CVars as unknown. A file
with a top-level `provisional` note (`"copied from _retail_ until a _forever_ dump exists"`) is another flavor's data
standing in until that flavor's own dump exists; its `source` still names the dump it was copied from.

### `cvars/<flavor>.json`

```json
{"flavor": "_retail_", "build": "12.1.5 70688", "source": "client dump _retail_ 12.1.5 70688",
 "cvars": {"<name>": {"default": "1", "help": "<Blizzard's help text>", "category": "game",
                      "scope": "account", "synced": true, "locked": false, "readonly": false,
                      "wiki": {"text": "<our own words>", "source": "https://warcraft.wiki.gg/wiki/<page>"}}}}
```

`scope` is where the client keeps the CVar (`machine` = `WTF/Config.wtf`, `account`, `character`); `synced` is true
when the server stores it. A CVar the client listed but gave no details for has `default` and `scope` `null`
(unknown), and `synced` false. `category` is the client's console category, lowercased; for a CVar
`cvar_categories.json` doesn't list, `core/kb.py` maps it (with name rules) to the Config Editor's groups (graphics,
sound, interface, camera, nameplates, combat text, network, game state, debug, system, other). `wiki` is optional and is only used with its
source. The dumping character's own values are never stored.

### `slash_commands/<flavor>.json`

`{"flavor", "build", "source", "commands": {"/cast": "CAST", "/dance": "EMOTE35", ...}}`, the slash in lower case:
the client's own commands and emotes, never an addon's.

### `cvar_state.json`

`{"source", "names": [...], "patterns": [...], "exceptions": [...]}`. A CVar is state when its name is in `names` or
matches one of the `patterns` (fnmatch: `*` is any run of characters), unless it is in `exceptions`; all matched
without regard to case, as the client matches CVar names. Every other CVar is a preference. The Config Copier keeps
the target character's state CVars and copies the source's preferences. When a pattern catches a real preference in a
flavor's CVar list, add that name to `exceptions`.

### `cvar_categories.json`

`{"comment", "categories": {"<CVar name>": "<group>"}}`, sorted by name: the Config Editor's group (one of graphics,
sound, interface, camera, nameplates, combat text, network, game state, debug, system, other) of every CVar any
`cvars/<flavor>.json` holds,
decided by hand from the CVar's name and Blizzard's help text, since the client files most CVars under `game`,
`default` or `none`. Names match without regard to case. `core/kb.py` uses this group first; a CVar not listed (one a
newer dump adds) gets the group of the name and console-category rules. After `scripts/refresh_kb.py` brings new
CVars, add them here: `tests/test_kb.py` checks that every shipped CVar is listed and every group is one of the eleven.
**game state** is what the client remembers rather than a setting (`seen*`, `last*`, `read*`, `new*Season`, renown
and transmog trackers, counters, unlocked lists), **debug** the developer, logging, error, event-log, frame stack,
taint and profiling CVars, **system** threads, async, caches, install and hardware detection, kiosk, the OS and the
title bar; **other** keeps only what fits none of them (feedback round 2 R6).

### `macro_limits.json`

`{"flavors": {"<flavor>": {"account": 120, "character": 30, "build": "...", "source": "<URL>"}}}`; the source is a
URL or `client dump <flavor> <build>`, and an entry may carry a `provisional` note as above. A flavor with no
entry here (or one without a source) uses Retail's values (`core.kb.limits_known` is then False); the Macro Editor
counts with them and marks that flavor's slots `unconfirmed` in its tree.

### `macro_reference.json`

`{"commands": {"/cast": {...}}, "conditionals": {"help": {...}}, "units": {"mouseover": {...}}, "builder": {...}}`.
Every entry has `help`, `source` and `flavors`: the flavor folders (`_retail_` ...) its source says it applies to, or
`null` when the source does not say, in which case the Macro Editor never flags it as missing from a flavor.
A command has `options` (true: its argument reads `[conditions]` and `;` clauses, as a secure command does; false:
its argument is plain text, such as chat or Lua) and may have `aliases`. A conditional has `subject` (`unit`,
`player`, `ui`), `explain` / `explain_no` (its plain-English phrase and that of its `no` form; `{unit}` stands for
the macro's unit), and when it takes an argument `args`, `explain_arg` / `explain_no_arg` (`{arg}`) and optional
`arg_names` (`shift` -> `Shift`). A unit has `explain`, and `numbered` for `party1`-style units (`{n}`). `builder`
lists what the conditional builder offers: `targets`, `unit`, `states`. Whether a flavor has a command at all comes
from its `slash_commands/<flavor>.json`, never from this file.

### `macro_templates.json`

`{"templates": [{"id", "title", "body", "placeholders", "source"}]}`. A placeholder is written `{name}` in the body.

### `optimizer_rules.json`

`{"rules": {"<id>": {"title", "reason", "source", "automatic"}}}`. Only rules with `automatic` true are applied, and
only rewrites that are the same in game: `reason` says why. A rule listed with `automatic` false is kept for the
record of why the optimizer does not make that rewrite.

### `recommendations.json`

`{"recommendations": [{"cvar", "value", "flavors", "reason", "source"}]}`. One recommended value of one CVar: `value`
is the string to set, `flavors` the flavor folders whose CVar list has the CVar (as the source shows it; a flavor
not listed gets no recommendation for it), `reason` why, in our own words, and `source` an https URL. An entry
without any of them is not loaded, and of two entries for one CVar and flavor the first wins. When a flavor's
`cvars/<flavor>.json` exists, every recommended CVar must be in it (`tests/test_kb.py` checks).
