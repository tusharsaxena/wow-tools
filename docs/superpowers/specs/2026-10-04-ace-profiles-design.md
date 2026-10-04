# Ka0s WoW Tools: Ace3 Profile Manager design

Date: 2026-10-04. Fourth tool in the suite. It follows `docs/adding-a-tool.md`, the two-pane look and feel of the
other tools (Interface Backup spec, Addendum A) and the safety model of the WTF Cleaner.

## 1. Purpose

Find every Ace3 (AceDB-3.0) database in a WoW install's SavedVariables, across every flavor and account, and show its
profiles and which characters use which profile. Let the user change that offline: delete, rename and copy profiles,
reassign characters, and remove leftover characters, with an addon blacklist, backups, a run journal and Undo.

## 2. AceDB on disk (the facts the tool relies on)

Source: AceDB-3.0 minor 33 (`AceDB-3.0.lua`), LibDualSpec-1.0 minor 35, the Ka0s addons and LibKa0s, and a read-only
survey of a real install (755 SavedVariables files, 61 AceDB databases).

- An AceDB database is one top-level SavedVariable (`KickCDDB = {...}`). It holds `profileKeys`
  (`["Name - Realm"] = "Profile"`), `profiles` (`["Profile"] = {...}`), `namespaces` (`["Module"] = {profiles=...}`)
  and other sections (`global`, `char`, `realm`, `class`, `race`, `faction`, `factionrealm`, `factionrealmregion`,
  `locale`) that the tool never touches.
- The character key is `UnitName .. " - " .. GetRealmName()`; split on the first `" - "` (names have no spaces,
  realms may have spaces, apostrophes and hyphens). Raw UTF-8.
- Namespaces have no `profileKeys`; they follow the parent's mapping. Their `profiles[X]` belongs to profile `X`.
- AceDB writes `profileKeys[char]` for every character that has logged in with the addon. The code-side default
  profile (`true` = "Default", a string, or the character key) is never on disk. "Every character shares a profile" is
  only visible as every `profileKeys` value being equal.
- A profile in use can be `{}` (defaults are stripped at logout). A character can point at a profile that has no
  entry in `profiles` (AceDB creates it at login). `profileKeys` entries for characters that no longer exist are
  common and never cleaned up by AceDB.
- `DeleteProfile` removes `profiles[X]` and every `namespaces[*].profiles[X]`, and drops the `profileKeys` entries
  that pointed at `X`. LibDualSpec rewrites spec entries that pointed at a deleted profile.
- LibDualSpec stores `namespaces["LibDualSpec-1.0"].char["Name - Realm"] = {enabled=true, [1]="A", [2]="B"}`; when
  `enabled` it switches the profile per spec at login, overriding `profileKeys`.
- One file can hold several databases (`ElvDB` + `ElvPrivateDB`) and plain tables (every Ka0s `*PerfDB`). Files are
  CRLF, unindented, up to ~12 MB, with full-precision floats, `\ddd` escapes, numeric keys and `nil,` array slots.
- WoW rewrites every SavedVariables file on logout and `/reload`: edits made while the game runs are lost.
- Ka0s addons migrate data keyed on `global.schemaVersion`; the tool never touches `global` and never moves a
  profile between files.

## 3. Decisions

| Topic | Decision |
|---|---|
| Name | Tool `ace-profiles`, title "Ace3 Profile Manager", package `wowtools/tools/ace_profiles/`, events `ace.*`, config `config/ace-profiles.cfg` section `[ace_profiles]`. Menu text: "See and change which Ace3 profile each character uses." |
| Scope | Flavor picker with **All flavors** first (remembered), then an account picker for one flavor with several accounts (like the WTF Cleaner). Account-wide and per-character SavedVariables are both scanned. |
| Editing method | **Span-preserving splices.** A stdlib parser records the byte span of every key and value it reads; an edit replaces, removes or inserts exact spans. Every other byte of the file stays identical. No file is ever re-serialized. |
| What can change | Only `profileKeys` entries, `profiles` entries, `namespaces[*].profiles` entries and LibDualSpec `char` spec entries. Nothing else. |
| Operations | Delete profiles; assign characters to a profile; rename a profile; copy a profile (same database only); remove leftover characters. Quick actions: **Keep only Default**, **Everyone → Default**. |
| Delete with users | Characters using a deleted profile are reassigned. The delete popup offers a target, preselected "Default", changeable to any other profile of that database. |
| Staging | Operations are staged, not run one by one. The tree shows the staged result; **Apply** writes everything in one run; **Dry run** checks it all without writing. |
| Blacklist | A list of addon names (SavedVariables file name without `.lua`, case-insensitive), empty by default, edited in settings or toggled on the tree (`b`). Blacklisted addons show greyed out with a "blacklisted" tag and can't be ticked or changed. `u` unlocks the highlighted one for this session only. |
| WoW running | Apply and Undo **refuse** while that flavor's WoW runs (the WTF Cleaner only warns; here WoW would overwrite the edits). If the check can't run, warn and allow. Dry run is always allowed. Files held by RaiderIO / WeakAuras Companion are refused by a lock probe, as in the WTF Cleaner. |
| Safety net | Per run: a whole-`WTF` snapshot zip (temporary safety net, pruned to `keep_snapshots`), a per-file zip of the original bytes of every edited file (the Undo source), a crash marker, atomic writes, a re-parse check of every written file, and roll-back of the run's already-written files on any failure. |
| Undo | `z` undoes the latest run: a file is put back only if it is byte-for-byte what the run wrote (SHA-256); otherwise it is skipped with "changed since" (WoW saved it). Undo is refused while WoW runs and takes its own snapshot first. |
| Leftover characters | A `profileKeys` character with no `<Realm>/<Name>` folder in that account (case-insensitive) is tagged "no character folder". It is never removed unless ticked and staged. |
| Default ticks | Nothing is ticked after a scan (this tool changes things; the user picks). |

## 4. Package layout

| Module | Job |
|---|---|
| `__init__.py` | imports `events` |
| `events.py` | the registry (§12), prefix `ace.` |
| `settings.py` | `ProfileSettings`, `load_settings`, `save_settings`, `resolve_root(settings, wow_path)` (= `<backup_dir or WoW/wow-tools>/ace-profiles`), `resolve_journal_dir`, blacklist parse/format |
| `luasv.py` | SavedVariables tokenizer and span parser (§5.1), Lua string encode/decode, `splice(data, edits)` |
| `model.py` | `AceDb`, `Profile`, `CharEntry`, `NamespaceInfo`, `LdsEntry` and `find_dbs(parsed_file)` (§5.2) |
| `scanner.py` | walk flavors/accounts/characters, read files, build `ScanResult` (§6) |
| `ops.py` | staged operations and the staged model (§7), compile to per-file edits (§8.1) |
| `verify.py` | re-parse a spliced file and compare with the expected model (§8.2) |
| `editor.py` | `apply(plan, ...)` and `dry_run(plan, ...)` (§9) |
| `multi.py` | All flavors: scan and apply per flavor, one journal per run |
| `journal.py` | entry fields over `core/journal.py`, `read_profile_journal` |
| `undo.py` | `undo_run(journal_path, ...)` (§10) |
| `report.py` | labels, tags, stage titles, summary and result rows (UI-free) |
| `app.py` | (UI) `AceProfilesFlow` (`FLOW`), `ProfileSettingsScreen` |
| `review_screen.py` | (UI) `ProfileReviewScreen`, `ProfileTree`, progress screen subclass, `RecoveryScreen` |
| `popups.py` | (UI) delete-target, assign, rename, copy and quick-action popups |
| `result_screen.py` | (UI) `ProfileResultScreen` (apply, dry run and undo results) |

Everything except the four UI modules is UI-free and never imports `textual`.

Shared code: the whole-`WTF` snapshot (`wtf_files`, `take_snapshot`, `snapshot_path`, `prune_snapshots`) moves from
`wtf_cleaner/safety.py` to a new `core/snapshot.py`, with the snapshot file prefix and folder as parameters. The WTF
Cleaner keeps thin wrappers with unchanged behaviour and file names; its tests stay green unchanged. `core/fsutil`
gains `atomic_write_bytes(path, data)` (`atomic_write_text` becomes a wrapper).

## 5. Reading SavedVariables

### 5.1 `luasv.py`

- Input is the file's raw bytes. Positions are byte offsets. Strings decode as UTF-8 with `surrogateescape`, so any
  byte sequence round-trips.
- Grammar: a sequence of `Name = value` assignments. Values: table constructors, strings (`"..."` and `'...'` with
  `\\ \" \' \n \r \t \a \b \f \v \ddd \xXX` and backslash-newline), numbers (int, float, exponent, hex, `inf`/`nan`
  spellings WoW writes such as `1.#INF` are read as text), `true`, `false`, `nil`. Table fields: `[key] = value`,
  `name = value` and positional values, separated by `,` or `;`. Comments `--...` and `--[[...]]` are skipped.
- Node spans: each table field records `entry_start` (first byte of the key or value), `entry_end` (after the
  separator, plus the rest of its line when only whitespace follows, so removing an entry removes its line),
  `key_span`, `value_span`. Each table records its `open` and `close` brace offsets.
- **Selective depth.** `parse(data, descend)` builds nodes only along key paths that `descend(path)` accepts; any
  other value is skipped by a fast scanner (a compiled regex over strings, comments and braces) that only finds its
  end. The scanner descends into `profileKeys`, the keys (not values) of `profiles`, `namespaces[*]` and their
  `profiles` keys, and `namespaces["LibDualSpec-1.0"].char[*]`. A 12 MB file parses in well under 2 s.
- Pre-filter: a file without the bytes `profileKeys` can't hold a main AceDB database and is not parsed.
- `splice(data, edits)`: edits are `(start, end, replacement_bytes)`, non-overlapping, applied from the end.
- `encode_string(text)`: `"` + escapes for `\`, `"`, CR, LF and control bytes (`\ddd`) + `"`, UTF-8.
- New text inserted into a file uses the file's own line ending (CRLF if the file's first line ending is CRLF).
- A parse error raises `LuaParseError(offset, message)`; the file is reported unreadable and never edited.

### 5.2 `model.py`: finding AceDB databases

A top-level SavedVariable is an AceDB database when `profileKeys` is a table whose keys are all strings containing
`" - "` and whose values are all strings, and `profiles` (if present) is a table with string keys whose values are
tables. Anything else (Memento's GUID-keyed tables, HidingBar's array, `profiles` with no `profileKeys`) is not.

`AceDb(file, sv_name, profile_keys: dict[char_key, profile], profiles: dict[name, ProfileSpan],
namespaces: dict[name, set[profile names]], lds: dict[char_key, LdsEntry])`. Per profile the tool knows: users
(characters mapped to it), whether it has an entry (`missing` when not), whether it is empty `{}`, and its
size in bytes. Per character: profile, leftover flag, LibDualSpec enabled flag.

## 6. Scan (`scanner.py`)

- For each flavor in scope and each account in scope: the account's `SavedVariables/*.lua` and each character's
  `SavedVariables/*.lua` (regular files only, directly in the folder). `.lua.bak`, `.lua.old`, `Blizzard_*` and
  anything under a symlink or junction are skipped (the WTF Cleaner's rules).
- Each candidate file is read once (bytes), pre-filtered, parsed and searched for databases. The scan keeps per file:
  path, size, mtime, SHA-256 and the parsed spans needed later (memory: spans, not the bytes; bytes are re-read at
  apply time and checked against the hash).
- Characters per account come from the `<Realm>/<Name>` folders (`Account.characters()`); leftover detection compares
  `"Name - Realm"` case-insensitively.
- Unreadable or unparsable files become scan warnings, shown in the tree as non-tickable notes.
- Runs in a worker with a progress bar (file count). `ScanResult(flavors -> accounts -> AddonEntry(addon name,
  file, scope account|character, dbs))`.

## 7. Staging (`ops.py`)

The staged model is a copy of every database's mapping state: `profile_keys` (char → profile or removed), and a
profile table `name → Source` where `Source` is `Original(name)` or `CopyOf(original name)`. Operations change the
staged model; they never touch bytes.

| Operation | Effect on the staged model | Refused when |
|---|---|---|
| Delete profiles `P` (target `T`) | remove `P` from the profile table; characters on `P` → `T` | `T` is in `P`; addon blacklisted and locked |
| Assign characters `C` to `T` | `profile_keys[c] = T` | `T` empty or invalid name |
| Rename `A` to `B` | key `A` becomes `B`; characters on `A` → `B` | `B` exists in that database; `B` invalid |
| Copy `A` as `B` | add `B = CopyOf(A's source)` | `A` missing (no data); `B` exists; `B` invalid |
| Remove leftover characters `C` | drop `profile_keys[c]` | `c` is not a leftover |
| Keep only Default | delete every profile except "Default" in the ticked addons, target "Default" | — |
| Everyone → Default | assign every character of the ticked addons to "Default" | — |

- Assigning to, or reassigning onto, a profile with no entry is allowed: the confirm popup notes "will be created by
  the addon at next login with its defaults". The tool never writes an empty profile for it.
- A profile name is valid when non-empty, at most 100 characters and without control characters. Names compare
  exactly (AceDB is case-sensitive).
- Operations across several databases (ticks spanning addons) apply per database; a database where the operation is
  refused is skipped and listed in the popup.
- LibDualSpec: spec entries follow renames and deletes (pointed to the new name, or to the delete target), as the
  library does in game. Assigning a character whose LibDualSpec switching is enabled shows an alert: the spec setting
  will override it at login.
- `x` discards all staged changes; Rescan with staged changes asks first.

## 8. Writing

### 8.1 Compile (`ops.compile_plan`)

Per file, the staged model is turned into span edits against the parsed original:

- `profileKeys`: changed value → replace the value span with `encode_string(new)`; removed → remove the entry span.
- `profiles` and every `namespaces[*].profiles` that has the profile: deleted → remove the entry span; renamed →
  replace the key span with `[encode_string(new)]`; copied → insert `[new] = <source value bytes verbatim>,` plus a
  line ending just before the table's closing brace (for each namespace holding the source too).
- LibDualSpec `char[c][i]` values → replace value spans.
- The result is the edit list, the expected model (§8.2) and a list of human-readable change lines per file.

### 8.2 Verify (`verify.py`)

Before writing, the new bytes are parsed again and must give exactly the expected model: the same `profileKeys`
mapping, the same profile names in `profiles` and each namespace, the same LibDualSpec entries, and for each kept or
copied profile a value byte-identical to its source. Every top-level SavedVariable not being changed must be
byte-identical. A mismatch fails the file (`ace.verify_failed`), nothing of that file is written, and the run stops.

## 9. Apply (`editor.py`)

Order per flavor (multi-flavor runs go flavor by flavor, one journal for the run; a failure stops before the next
flavor):

1. Guard: every path lies inside `<flavor>/WTF/Account` and directly in a `SavedVariables` folder.
2. WoW of that flavor running → refuse (`ace.wow_running`).
3. Recheck each file: size, mtime and SHA-256 must match the scan; a changed file is skipped ("changed since the
   scan; rescan") with its edits.
4. Open the journal; lock probe (rename to `.wowtools-lockcheck` and back) on every file to change.
5. Write the crash marker (`edit-in-progress.json` in the tool root: flavor, files with the SHA-256 of the
   original and of what the run writes, per-file zip, pid, started).
6. Whole-`WTF` snapshot to `<root>/snapshots/snapshot-<flavor>-<stamp>.zip` (`core/snapshot.py`, verified).
7. Per-file backup zip `<root>/edited/edited-<flavor>-<acct|all>-<stamp>.zip` of every file to change (original
   bytes, manifest with rel path, size, SHA-256), verified.
8. For each file: compile → verify → `atomic_write_bytes` → re-read and compare the SHA-256 → journal `edited` entry.
9. On any failure in step 8: put back every file already written in this run from the per-file zip (journal
   `rolled_back`), stop, report.
10. Clear the marker; prune snapshots to `keep_snapshots` and journals (with their per-file zips) to `keep_journals`.

Dry run: steps 1–3 and compile + verify for every file, in memory. Nothing is written (no zip, no journal).

Crash marker on next open: a recovery popup lists the files and offers **Put the originals back** (from the per-file
zip, only files whose hash is still what the run wrote; a file at neither hash, skipped by the run or saved since by
WoW, is left as it is) or **Leave as is**. Same flow as the WTF Cleaner's.

## 10. Undo (`undo.py`)

Latest undoable journal (`core/journal.latest_undoable`). Refused while that flavor's WoW runs; lock probe; snapshot
first. For each `edited` entry, newest first: current SHA-256 equals `sha_after` → write the original bytes from the
per-file zip atomically and check `sha_before` → "restored"; otherwise "skipped: changed since". The journal is
marked undone unless nothing was restored and something failed (WTF Cleaner rule).

## 11. Settings (`[ace_profiles]`)

| Key | Default | Meaning |
|---|---|---|
| `backup_dir` | empty | Folder for snapshots, per-file zips. Empty = `<WoW folder>/wow-tools`; files go to `<backup_dir>/ace-profiles/`. Validated with `validate_output_dir`. |
| `keep_snapshots` | 2 | Whole-WTF snapshots kept per flavor (at least 1). |
| `keep_journals` | 10 | Run journals kept (at least 1); a per-file zip is deleted with its journal. |
| `blacklist` | empty | Comma-separated addon names. |
| `last_flavor_choice` | empty | Empty = All flavors. |
| `last_account` | empty | Empty = all accounts. |

First open shows the settings screen (backup folder, snapshots to keep, blacklist), as the other tools do.

## 12. Events (`events.py`, prefix `ace.`)

`ace.scan_started`, `ace.scan_completed` (flavors, files, dbs, profiles, characters, leftovers, seconds),
`ace.file_unreadable` (warning), `ace.parse_failed` (warning), `ace.staged` (debug: operation summary),
`ace.apply_started`, `ace.wow_running` (warning), `ace.file_changed` (warning), `ace.file_locked` (warning),
`ace.snapshot_taken`, `ace.files_backed_up`, `ace.file_edited`, `ace.verify_failed` (error),
`ace.rolled_back` (warning), `ace.apply_completed`, `ace.dry_run_completed`, `ace.undo_started`,
`ace.file_restored`, `ace.file_skipped` (warning), `ace.undo_completed`, `ace.recovery_offered`,
`ace.recovery_done`, `ace.blacklist_changed`, `ace.unlocked`, `ace.settings_saved`. Levels and fields are fixed in
the plan; `docs/events.md` is regenerated.

## 13. TUI

Two panes like the other tools (`two_pane_css`, `FILTERS_WIDTH`, `review_hint`).

**Left pane** (`#filters`):
- *View*: two radio-style checkboxes, **By addon** (default) and **By character**.
- *Show*: Only addons with 2+ profiles; Only unused profiles; Leftover characters (on); Blacklisted addons (on).
- *Search*: an `Input` filtering addon, profile and character names (case-insensitive substring).
- *Staged*: one line per kind of staged change ("2 deletes · 5 assigns · 1 rename"), or "Nothing staged".
- `#actions`, exactly four buttons: **Apply** (delete variant), **Dry run** (simulate), **Rescan** (neutral),
  **Undo last change** (revert).
- `NavHint`: `review_hint()` + keys.

**Tree, By addon**: root → flavor (when several) → account → addon (`KickCD`, tags: blacklisted / unlocked /
per character) → database (only when the file has more than one) → profile (`Default · 12 characters`, tags
Default, unused, empty, missing, staged marks) → character leaves (`Kaelys - Mug'thol`, tags no character folder,
spec profiles). Staged marks: deleted profile `✘ deleted → Default`, renamed `Old → New`, copied `+ copy of A`,
reassigned character `Old → New`, removed character `✘ removed`. Unreadable files are warning notes.

**Tree, By character**: root → flavor → account → character (`Kaelys - Mug'thol`, leftover tag) → `Addon: Profile`
leaves. Ticking here selects (database, character) pairs.

**Ticks** select targets. Profile nodes and character leaves are tickable; addon, database, account, flavor and
character-group nodes tick their descendants (`tick_mark`, `relabel_branch`); blacklisted (locked) addons and notes
are read-only kinds. Bottom `#summary`: `Selected: 3 profiles · 8 characters · Staged: 6 changes in 2 files`
(plus `⚠ scan warnings` when any).

**Keys**: Space tick, `a` all, `n` none, `d` delete ticked profiles, `p` assign ticked characters, `e` rename
highlighted profile, `k` copy highlighted profile, `o` remove ticked leftover characters, `m` quick actions menu
(Keep only Default, Everyone → Default, Tick all leftover characters, Discard staged changes), `x` discard staged,
`b` blacklist/unblacklist highlighted addon, `u` unlock highlighted blacklisted addon for this session, `v` switch
view, `/` search, `w` Apply, `y` Dry run, `r` Rescan, `z` Undo, `f`/Esc flavors, `t` tools, `q` quit, ←/→ panes.

**Popups** (`ModalScreen`s in `popups.py`, styled like `ConfirmScreen`): delete (lists profiles and affected
characters, target selector preselected "Default"), assign (target selector listing the union of profile names of the
ticked databases plus a "New name" input, missing-target note), rename and copy (name input, validation message),
quick actions (a list). Apply and Undo use `ConfirmScreen` (alerts in red: WoW running, LibDualSpec overrides,
targets that will be created at login, Default being deleted) and a `ProgressScreen` subclass (stages: check,
snapshot, back up, edit, verify).

**Result screen** (`result_css`): Item/Value summary (files changed, skipped, failed, profiles deleted/renamed/
copied, characters reassigned/removed, snapshot, per-file backup, journal) above one `.result-detail` table (flavor,
account, addon, change, result). Buttons Rescan (r) … Other flavor (f), Tools (t), Quit (q). The same screen shows
dry-run and undo results.

## 14. Testing

- `tests/fixtures.py`: `build_ace_tree()` writes WoW-format SavedVariables (CRLF, no indentation) for: a Ka0s-style
  DB (Default shared, plus a `*PerfDB` in the same file), a char-keyed DB with unused profiles, a file with two DBs,
  a DB with namespaces and LibDualSpec data, a DB with a missing profile and leftover characters, a non-AceDB
  look-alike, an unparsable file, a per-character AceDB, and odd strings (escapes, UTF-8, quotes in keys, floats,
  numeric keys, `nil,` slots).
- `test_ace_luasv`: tokens, escapes, comments, selective depth, spans, splice, no-op round trip byte-identical, parse
  errors with offsets, a generated multi-MB file within a time budget.
- `test_ace_model`, `test_ace_scanner`, `test_ace_ops` (each operation, composition: copy then rename, delete onto
  target, LibDualSpec follow-up, refusals), `test_ace_verify` (mismatches caught), `test_ace_editor` (snapshot,
  per-file zip, atomic writes, recheck skip, WoW-running refusal, lock refusal, roll-back on a failure mid-run,
  marker and recovery), `test_ace_multi`, `test_ace_journal`, `test_ace_undo` (restore, skip changed, refusal),
  `test_ace_report`, `test_ace_settings`, `test_ace_app` (TUI: tree, ticks, views, filters, search, blacklist and
  unlock, each popup, staged marks, apply, dry run, result, undo, recovery).
- `test_core_snapshot` for the moved helpers; the WTF Cleaner's tests unchanged.
- `tests/test_look_and_feel.py`: add the tool to `TOOLS` and `RUN_ACTION`.
- Tests never touch a real WoW install or the network.

## 15. Documentation

`docs/ace-profiles.md` (the guide shape of the other tools: close WoW, step by step, the review screen, keys,
staging, what is never touched, backups and Undo, settings, FAQ, troubleshooting), README (tools table, guides, your
settings, undo and journals), `docs/architecture.md`, `docs/events.md` (regenerated), `CLAUDE.md` tool list.

## 16. Out of scope

Editing settings inside a profile; moving or copying profiles between files, accounts or flavors; import/export;
`global`/`char`/other AceDB sections; creating LibDualSpec mappings; profile systems that aren't AceDB (WeakAuras,
Details' own, Plater's own).
