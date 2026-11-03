# Config Copier, Macro Editor, Config Editor and the launcher fix: status ledger

Plan: `2026-11-04-config-copier-macro-editor-config-editor.md`. Spec:
`../specs/2026-11-04-config-copier-macro-editor-config-editor-design.md`.
Branch: `feat/config-tools-and-launcher`. Resume at the first task not marked `done`. Push after each milestone;
never merge without the user's go-ahead.

Statuses: `todo`, `in-progress`, `done`, `waiting-user`, `blocked`.

| Task | Milestone | Title | Status | Commit | Notes |
|---|---|---|---|---|---|
| T0 | - | spec, plan, ledger | done | (this commit) | builder check folded into the spec |
| T1 | M1 | bootstrap log writer, launcher events, LN7 deviation | done | (this commit) | 15 new tests (8 test_bootstrap, 7 test_suite incl. MainTest); gate green: WSL 1987 OK (2 skipped), Windows 1987 OK (78 skipped), ruff clean, events.md current. Review fixes (T1r): bootstrap.py parses on 3.7 again (no walrus; ast test), and the 2000-line cap (MAX_KEEP_LINES) now applies after the date trim too; gate green: WSL/Windows 1989 OK |
| T2 | M1 | wow-tools.cmd check, log, pause | done | (this commit) | 8 new tests in test_launcher.py (2 structure tests on every platform, 6 cmd.exe tests Windows-only); gate green: WSL 1997 OK (8 skipped), Windows 1997 OK (78 skipped), ruff clean, events.md current. Manual run from a folder named `a!b & c` logged and paused correctly; review fix: test_old_python_message covers the LN2 too-old branch (fake python.bat on PATH reports 3.8, exits 3); gate after it green: WSL OK, Windows 1998 OK (78 skipped), ruff clean, events.md current (one earlier --all run had a single Windows error that did not recur on the rerun and was not captured) |
| T3 | M1 | wow-tools.sh parity, README FAQ, CHANGELOG; push | done | (this commit) | 9 new tests in test_launcher.py (3 structure tests on every platform, 6 `sh` tests POSIX-only); gate green: WSL 2007 OK (9 skipped), Windows 2007 OK (84 skipped), ruff clean, events.md current. Push left to the orchestrator. T3 review fix (minor, docs only): the FAQ row's log path now reads `logs/suite/launcher.log` with the Windows form beside it, and "a text editor (Notepad on Windows)"; no test needed; gate green again: WSL 2007 OK (9 skipped), Windows 2007 OK (84 skipped), ruff clean, events.md current |
| T4 | M2 | dump addon, refresh script; then user runs dumps | waiting-user | (this commit) | 11 new tests in test_refresh_kb.py (10 refresh_kb, 1 addon shape); the Lua (112 lines) also smoke-run under lua5.1 with stubbed APIs and fed through refresh_kb.py end to end (scratchpad only); gate green: WSL 2018 OK (9 skipped), Windows 2018 OK (84 skipped), ruff clean, events.md current. Waiting on the user: install the addon and `/kbdump` once per flavor (scripts/kb_dump/README.md); T5 onward does not wait, T20 needs the dumps. Review fix (fix: T4 review fixes): a dump string that is not valid UTF-8 now skips its flavor with a message instead of crashing the run (T4h); +1 test, gate green: WSL 2019 OK (9 skipped), Windows 2019 OK (84 skipped), ruff clean, events.md current |
| T5 | M2 | install helpers (Forever, real characters) | done | (this commit) | 5 new tests in test_install.py (RealCharactersTest: the plan's 4 plus on_error passed through); gate green: WSL 2024 OK (9 skipped), Windows 2024 OK (84 skipped), ruff clean, events.md current. Review fix (fix: T5 review fixes): test_real_characters_passes_on_error checked nothing (a missing account folder never reaches on_error); it now makes one realm's iterdir raise PermissionError and asserts on_error gets that realm and the other realm's character still lists (fails if real_characters drops on_error); gate green: WSL 2024 OK (9 skipped), Windows 2024 OK (84 skipped; one first-run WinError 10055 socket-buffer error, environmental, clean on rerun), ruff clean, events.md current |
| T6 | M2 | client-file write pipeline | done | (this commit) | 28 new tests: 24 in test_client_apply.py (the plan's 9 plus created-only run, stale-skip-rest, appears-before-write, link guard, guarded path stops the run, client_destination, roll-back removes a created file, undo of a gone created file, undo while WoW runs, journal entry outside the names, recovery leaves a rewritten created file, finished-run recovery, no cache.md5/.old, client_events), 3 in test_fsutil.py (atomic_create_bytes), 1 in test_backup.py (allow_empty); test_structure pins the new pieces in core. Existing Ace3 / SV Browser / pipeline tests unchanged and green. Gate green: WSL 2052 OK (9 skipped), Windows 2052 OK (85 skipped; the first --all run had one WinError 10055 socket-buffer error, environmental as in T5, clean on the --windows rerun), ruff clean, events.md current. Review fix (fix: T6 review fixes): a created file roll-back could not remove now gets its own detail and message (delete it / Undo / recovery), never the unzip advice; +1 test, crash-marker test asserts it; gate green again: WSL 2053 OK, Windows 2053 OK (one WinError 10055 on --all, clean on the --windows rerun), ruff clean, events.md current |
| T7 | M2 | macro and CVar file parsers | done | 2e9243e, review fixes (this commit) | 27 new tests: 14 in test_macrofile.py (the plan's 6 plus empty file, quoted name and lowercase id, limits, empty-body add, bad changes, invalid UTF-8, other-prefix ids, id overflow), 13 in test_cvarfile.py (the plan's 3 plus spans, other lines kept, duplicates, empty file, spelling and line ending kept, every duplicate set/removed, unterminated last line, removing a missing CVar, invalid UTF-8, bad changes); fixtures gain macro_file_bytes and cvar_file_bytes; architecture.md Core modules rows for both. Gate green: WSL 2080 OK (9 skipped), Windows 2080 OK (85 skipped; the first --all run had one Windows failure in the test runner's own shard-balancing test, not in this change, clean on the --windows rerun and a second --all), ruff clean, events.md current. No CHANGELOG line: nothing a user sees yet. Review fixes (T7r1): a replace whose name, icon and body equal the parsed macro keeps the block's bytes (the one-blank-line block), pinned by test_unchanged_replace_keeps_the_block_bytes |
| T8 | M2 | KB loader, state list, macro limits | done | (this commit) | 17 new tests in test_kb.py (the plan's 4 plus case-insensitive state match, exceptions, unreadable state list, the refresh_kb schema, odd entries, unsafe flavor names, caching, the X8 category groups, unknown-flavor limits, every shipped limit sourced, bad limits, the KB folder and README, kb.unreadable registered); architecture.md Core modules row for `kb`; events.md regenerated. Gate green: WSL 2098 OK (9 skipped), Windows 2098 OK (85 skipped; the first --all run's Windows half reported FAILED with 0 failures and 0 errors after one shard hung 600 s on the executor join in test_ui_base, environmental, clean on the --windows rerun in 81 s), ruff clean, events.md current. No CHANGELOG line: nothing a user sees yet Review fix (fix: T8 review fixes): `highestUnlocked*` added to the state patterns, `showTutorials` made an exception (T8g); T20's row now carries CC5's per-pattern dump check; +1 test, gate green: WSL 2099 OK (9 skipped), Windows 2099 OK (85 skipped), ruff clean, events.md current |
| T9 | M2 | shared character tree; push | todo | | |
| T10 | M3 | copier planning and config merge | todo | | |
| T11 | M3 | copier run, undo, flow | todo | | |
| T12 | M3 | copier docs; push | todo | | |
| T13 | M4 | macro model, ops, paste rules | todo | | |
| T14 | M4 | macro reference, explainer, optimizer, templates | todo | | |
| T15 | M4 | macro browse screen, apply, undo | todo | | |
| T16 | M4 | macro edit screen and popups | todo | | |
| T17 | M4 | macro docs; push | todo | | |
| T18 | M5 | config model and edits | todo | | |
| T19 | M5 | recommendations data | todo | | |
| T20 | M5 | CVar base from dumps + wiki notes | todo | | needs the user's dumps (T4). Also CC5's state-list check (T8d, T8g): list every `cvar_state.json` pattern's matches in each flavor's dump, move any preference into `exceptions`, record the result here |
| T21 | M5 | config editor screens, apply, undo | todo | | |
| T22 | M5 | config editor docs; push | todo | | |
| T23 | M6 | whole-branch review, gate, CI, ready to merge | todo | | |

## Decisions taken during the build

(append `T<n>a: …` lines here as calls are made)

- T1a: launcher.log trim rule (LN6). A record is a line with a leading date plus the indented lines under it (the
  traceback of a `bootstrap.failed`). Dates read: year first (`2026-11-04`, `2026/11/04`) and the `cmd.exe`
  `%date%` shapes with an optional weekday (`Wed 11/04/2026`, `04.11.2026`); a day/month that could be either order
  is dropped only when both readings are older than `log_retention_days`. Undated lines are kept. When no line has a
  readable date, the last 2000 lines are kept. Rewritten via `.partial` + replace, only when something is dropped.
- T1b: `log_bootstrap_failure(..., path: Path | None = None)` instead of `path: Path = LAUNCHER_LOG`: the default
  is read at call time, so tests can patch `bootstrap.LAUNCHER_LOG` and never write the repo's `logs/`. `suite.run`
  passes `<log_dir>/suite/launcher.log` explicitly (none when `log_dir` is None).
- T1c: a string problem (the Python check) has no `type=` field; an exception gets `type=` and its last 10
  traceback lines, indented 4 spaces. Multi-line messages are joined with ` | ` to keep one line per record.
- T1d: `where` values: `python_check`, `startup` (uncaught in `__main__` before the log opens), `lock`, `config`,
  `log_start`. The LN3 folder hint goes on the lock, `log_start` and the non-`ConfigError` `OSError` of the config
  step; a `ConfigError` keeps "Fix or delete the file". An exception after the log opened but before
  `session.start` is now also logged there as `error` (`where=suite.start`), so `__main__` never logs it twice.
- T1e: the CHANGELOG line for the launcher fix lands in T3 with the `.cmd`/`.sh` work (the user-visible part).
- T2a: the `.cmd` Python check runs before the last line and, on failure, writes `launcher.python_missing` or
  `launcher.python_too_old` and then `launcher.exited`, pauses when double-clicked and exits: 3 for too old, 9009
  (cmd.exe's "not found") for missing. Any probe result other than 0 or 3 counts as missing (the Store placeholder,
  `py` without a Python 3). The probe and the version read use `call`, so a `.bat` shim (pyenv-win) returns.
- T2b: double-click = `%cmdcmdline%` contains both the script's name and `/c` (case-insensitive), compared by
  delayed-expansion substitution rather than `echo | findstr`, so quotes or `&` in the command line can't break it.
  The pause shows the launcher's own English prompt ("Press any key to close this window.", `pause >nul`), since
  `pause`'s text is localised and the tests pin the prompt.
- T2c: log writes are `(>>"<log>" echo ...) 2>nul`: a `2>nul` on the same command doesn't hide cmd.exe's own
  "cannot find the path" message for a failed redirect, the group's does. On the last line the path is read as
  `!WOWTOOLS_LOG!` (a `!` in the app folder survives). `launcher.started` writes `args=%*` last (`python=`,
  `platform=windows` first) so arbitrary arguments can only trail the line; an argument with `)` would cut the
  logged args short, which the suite's own arguments (`update`, `--check`, `--version`, `--help`) never contain.
- T3a: `wow-tools.sh` puts its whole body in `main()` and ends on `main "$@"; exit $?`, so the shell has parsed
  everything (the exit included) before Python starts; no `exec`, so it can log the exit. The rewrite test replaces
  the file with `echo REREAD; exit 99` lines while the fake app runs and checks none of them ran (dash and bash).
- T3b: the `.sh` Python check mirrors the `.cmd` (T2a): `python3` not on PATH, or a probe result other than 0 or
  3, is missing and exits 127 (the shell's "not found"); 3 is too old, reads `found=x.y`, exits 3. Its messages go
  to stderr. Log lines use ISO local time (`date '+%Y-%m-%dT%H:%M:%S'`), `platform=` is `uname -s`, and `args=$*`
  comes last as in the `.cmd`. Log writes are `{ ... >>"$log"; } 2>/dev/null`, so an unwritable folder is silent.
- T3c: README gets two FAQ rows ("The window flashes and closes when I start it", "It says the folder isn't
  writable") and a Troubleshooting row pointing at the first; the CHANGELOG starts an `## [Unreleased]` section
  with one `### Fixed` line for the launcher fix (T1-T3).
- T4a: the dump's console `category` is stored as the `Enum.ConsoleCategory` name (a number on a client without
  the enum) and written lowercased (`graphics`, `game`, `net` ...); the X8 mapping to the issue's groups is left to
  the KB loader (T8), so the JSON keeps the client's own word.
- T4b: scope: `isStoredServerCharacter` wins over `isStoredServerAccount` when both are set (the more specific
  file); neither is `machine`. `synced` is true exactly when the scope isn't `machine`. The dump's current `value`
  and `secure` flag are recorded by the addon but never written to the KB JSON (the user's own settings stay out).
- T4c: one `.toc` for every flavor, `## Interface: 120105, 50503, 20505, 11508` (the comma list the current
  clients read); the README tells the user to tick "Load out of date AddOns" if a flavor says it is out of date.
- T4d: several accounts of one flavor with a dump: the newest `KaosKbDump.lua` by modification time wins, and the
  output line names the file. A flavor with no or an unreadable dump is skipped with a message and keeps its older
  JSON; the run fails (exit 1, nothing written) only when no flavor had a readable dump.
- T4e: slash keys are lowercased (`/CASTSEQUENCE` -> `/castsequence`; the client matches them case-insensitively);
  when two `SLASH_*` keys claim one slash the alphabetically first wins (in Lua and again in Python), so reruns
  agree. The addon leaves its own `/kbdump` out. `slash_commands/<flavor>.json` also carries a top-level `source`
  (`client dump <flavor> <build>`, X6), beyond the plan's schema.
- T4f: `--wiki` reads `{"cvars": {name: {"text", "source"}}}` from `scripts/kb_dump/wiki_notes.json` (or
  `--wiki-notes PATH`) and adds `"wiki": {"text", "source"}` to that CVar's entry, beside the Blizzard `help` whose
  source is the file's top-level `source`. A note without text or without a `https://warcraft.wiki.gg/` source stops
  the run before anything is written; a note for a CVar the dump lacks is ignored. `refresh_kb.py` never uses the
  network: the notes are researched and rewritten in our own words by hand in T20 (X7's "MediaWiki API" fetch is not
  needed for that and is not built).
- T4g: output JSON is UTF-8, `indent=1`, sorted keys, LF, written via `.partial` + replace, so reruns on the same
  dump are byte-identical and diffs stay readable.
- T4h (T4 review): both files of a flavor are rendered to bytes before either is written; a dump string that is
  not valid UTF-8 (luasv keeps such bytes as surrogates) raises DumpError there, so the flavor is skipped with
  "could not be read: a string in the dump is not valid UTF-8", its older files are kept and the other flavors carry
  on. Refused rather than replaced: a KB entry with mangled text is worse than the previous good one.
- T5a: `is_character_name` is exactly `bool(name) and all(ch.isalpha() for ch in name)`: accented letters
  (`Aellâ`, `Trâxex`, `Dænerys`) pass, while spaces, digits, `_`, `.` and `-` fail. `real_characters(on_error=...)`
  takes the same `on_error` as `characters()` and passes it on. No CHANGELOG line: `flavor_name("_forever_")` already
  showed "Forever" through the title-case fallback, so the new `FLAVOR_NAMES` row changes nothing a user sees; it
  only pins the name. `docs/architecture.md`'s `install` row names both helpers.
- T6a: X5 is done by generalising, not forking: `core/client_apply.py` is thin and runs every write through
  `sv_apply.apply_flavor` / `apply_flavors` and `sv_undo.undo_run` / `recover`, which gained `guard=` (default
  `SvGuard`), `create=` and `dest_for=` (default the SavedVariables `destination`). Nothing had to be separate, so
  the docstring records that instead. A created file is a unit whose `SvFile.sha256` is None (annotation widened to
  `str | None`; the SavedVariables tools never make one, so their runs, events and journals are unchanged).
- T6b: a created file: refused (skipped, `EXISTS` "it exists now; rescan") if it exists at the check or right
  before the write; written with the new `fsutil.atomic_create_bytes` (fsync'ed partial, then `rename_no_replace`,
  so one that appears in between is never replaced, STD-5.16/5.17); journaled `{"action": "created", ...,
  "sha_after", "zip"}` with the run's zip so it matches its run like an edited entry; in the marker's new
  `created` list (not in `files`: no original); deleted by roll-back (`sv_apply.remove_created`), Undo and recovery
  only while still at its `sha_after`; recovery counts an absent one as at its original. Its outcome is `edited`
  with detail `created`, so the result rows count it as changed.
- T6c: every real run with something to write still gets an originals zip, even one that only creates files: it
  holds just `manifest.json` (with a `created` list), via `create_backup(..., allow_empty=True)`, so the marker and
  journal always name a real zip. The default still refuses an empty backup (WTF Cleaner unchanged).
- T6d: a stale `expected_sha256` follows the pipeline's own rule: that file is skipped (`file_changed`) and the rest
  of the run is written; a single stale change therefore writes nothing (no journal, no zip). A path the guard
  refuses stops the whole run before anything is written (`result.stopped`), as `SvGuard` does.
- T6e: `ClientFileGuard` takes exact, case-sensitive names (the tool's list, X4) at exactly
  `WTF/Account/<A>/<name>` or `WTF/Account/<A>/<Realm>/<Char>/<name>` with `is_character_name(Char)` (X3 enforced
  at the write too, so `Name - Copy` is refused even if a tool forgot to filter), never with `SavedVariables` on
  the way, and `Config.wtf` only as `WTF/Config.wtf`. It refuses a file that is a link and a path whose parent
  resolves anywhere but the lexical place below the flavor folder (a link on the way). `check(path, info=None)`
  returns the resolved path; `client_rel_ok` is the one rule both the guard and `client_destination` (Undo,
  recovery) use. The tool passes `names`; `cache.md5` and `.old` are never in it (V2).
- T6f: events: `sv_events.client_events(prefix)` = the pipeline's events with client-file texts for
  `file_edited`, `write_failed` and `probe_recovered`, plus `file_created` (Apply) and `file_removed` (Undo,
  recovery). No registry of an existing tool changed, so `docs/events.md` is unchanged until a tool registers it.
  No CHANGELOG line: nothing a user can see yet (the tools that use it land in T11, T15, T21).
- T7a: a macros-cache.txt is a known layout only when every line ends in CRLF (the file ends in one too), every
  block is `VER 3 <16 hex> "<name>" "<icon>"`, its body lines and `END`, with nothing between blocks and no id twice
  (compared case-insensitively). Anything else (LF-only or mixed endings, a missing `END`, `MACRO`, `VER 2`, a blank
  or stray line, no final newline, a BOM, a duplicated id) is read-only: `known_layout` False with a `line N ...`
  problem, no macros listed, and `apply_macro_changes` raises even with no changes. An empty file is known, empty,
  CRLF. A body line that is itself a `VER 3` header ends the block early, so it reads as a missing `END`.
- T7b: the header's icon has no quote and the name is greedy, so a name holding quotes reads back whole. A body is
  its lines joined with "\n"; an empty body is written with no lines (a block with one blank line also reads as "").
  `apply_macro_changes` refuses (ValueError) a malformed id, a line break in name or icon, a CR in the body, a quote
  in the icon, a body line `END` or `VER 3 ...`, an add of an id in the file, a replace/delete of one it lacks, and
  two changes to one id. It does not enforce `NAME_LIMIT` (16) or `BODY_LIMIT` (255): those are the model's (T13).
  Changed blocks are rewritten in place, deletes removed, adds appended in the order given. `ICON_DEFAULT = "134400"`
  is added for ME8.
- T7r1: (review) a `replace` whose name, icon and body all equal the parsed macro's keeps the block's exact bytes
  (ME13), so a block with one blank body line survives a no-op replace even though it reads as "" like a block
  with no body lines. Done in `apply_macro_changes` rather than left to each caller (T13), so no caller can drop it.
- T7c: `next_macro_id` counts only ids with the scope's prefix (another prefix in the file is ignored), writes
  16 uppercase hex digits, starts at `<prefix>00000000000001` and raises ValueError when the prefix runs out
  (`00FFFFFFFFFFFFFF`) or the layout is unknown.
- T7d: CVar files: a `SET <name> "<value>"` line has a name without spaces or quotes and the value runs to the line's
  last quote (quotes inside kept). Names match case-insensitively (the client's rule); `get` returns the last line's
  value. A set rewrites the CVar's first line in place, keeping the file's spelling of the name and that line's own
  ending, leaves the bytes untouched when the value is the same, and removes any later duplicate; a remove drops
  every line of it. New lines are appended with the file's newline (the first line's; CRLF for an empty file or one
  without a line ending), adding a newline first when the last line has none. ValueError for an empty name or one
  with a space or quote, a value with a line break, or a CVar both set and removed (or set twice in other cases).
- T8a: `kb.py` loaders take a keyword-only `root=` (default `KB_ROOT` = `wowtools/kb`, read at call time) beyond the
  plan's signatures, so tests read temp folders. Cached per process by path (`clear_cache()`), thread-safe. A missing
  file is "no data" and logs nothing; a file that is not UTF-8, not JSON, not an object, or a `cvars/<flavor>.json`
  without a `cvars` object, logs `kb.unreadable` (warning, `path`, `reason`) once and reads as empty. A flavor folder
  name that isn't `[A-Za-z0-9_]+` reads nothing (no path escapes). `kb.unreadable` sits in `CORE_EVENTS`, beside
  `changelog.unreadable`.
- T8b: `CvarInfo` from the T4 schema: `default` is None only when the entry has no string default; `help` is
  Blizzard's text; `description` / `description_source` are the `wiki` note's text and URL, both "" unless both are
  present (no unsourced description); `scope` is None for anything but machine/account/character; `source` is the
  file's top-level `source` (`client dump <flavor> <build>`). The raw `locked` / `readonly` flags are not in
  `CvarInfo` (the plan's interface); a later task can add them if the Config Editor needs them.
- T8c: the X8 mapping (`category_group(name, raw)`), groups `CATEGORY_GROUPS` = graphics, sound, interface,
  camera, nameplates, combat text, network, other. Name rules first, case-insensitive: `nameplate*` -> nameplates,
  any name containing `camera` -> camera, containing `floatingcombattext` or starting `combattext` -> combat text.
  Then the client's console category: graphics -> graphics, sound -> sound, net -> network, game -> interface;
  everything else (debug, console, combat, default, gm, reveal, none, a bare number, empty) -> other. Revisit when
  T20 has the real dumps.
- T8d: `cvar_state.json` = `{source, names, patterns, exceptions}`: the appendix reading's names plus every pattern
  the spec names (`closed*`, `*Tutorial*`, `last*`, `latest*`, `lastRenownForCovenant*`, `new*Season`,
  `saved*Config*`, `savedClassConfig*`, `garrison*`, `cameraSaved*`, `*Collapsed`). Matched case-insensitively
  (fnmatch on lowercased names, the client's own rule); an `exceptions` name is never state, which is how a pattern
  that catches a real preference in a flavor's dump gets corrected. CC5's "each pattern checked against the
  flavor's CVar dump" can only run once the dumps are in: it is T20's job (list each pattern's matches per flavor,
  move any preference into `exceptions`). An unreadable state list means no CVar is state (logged).
- T8e: macro limits: Retail 120 / 30 confirmed from the client's generated UI docs
  (`Blizzard_APIDocumentationGenerated/MacroConstantsDocumentation.lua`, Gethe/wow-ui-source `live` at 12.1.5 70688:
  `MAX_ACCOUNT_MACROS` 120, `MAX_CHARACTER_MACROS` 30), the URL in `macro_limits.json`. The `classic`, `classic_era`
  and `classic_anniversary` branches (5.5.4, 1.15.9, 2.5.6) use the same globals in `Blizzard_MacroUI.lua` but define
  them nowhere in Lua (no `MacroConstants` doc either), so those flavors are not shipped: they get Retail's values with
  `limits_known` False, for ME3's flag. A sourced entry needs positive integers and a `source`, else it isn't known.
  A later task can add them from an in-game check (e.g. the dump addon recording `MAX_CHARACTER_MACROS`).
- T8f: `wowtools/kb/README.md` (ships) names files and scripts in backticks only, no links into `scripts/`, which
  doesn't ship. No CHANGELOG line: nothing a user sees yet.
- T8g (review fix): `highestUnlocked*` joins the patterns (CC5 names it; T8d's list had only the exact name), so a
  sibling progress CVar such as `highestUnlockedMythicPlusTier` stays the target's own. `showTutorials` (the Retail
  Tutorials toggle, a preference) goes into `exceptions`, since `*Tutorial*` caught it. The per-pattern dump check
  stays with T20, now written on T20's ledger row so it can't be missed.
