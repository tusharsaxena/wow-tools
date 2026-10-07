# Ace3 Profile Manager internals

How the Ace3 Profile Manager (`wowtools/tools/ace3_profile_manager/`) reads AceDB profiles, stages changes and writes them through the shared SavedVariables pipeline, and how its screens are built.

User guide: [ace3-profile-manager.md](../ace3-profile-manager.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools).

## Contents

- [Data flow](#data-flow)
  - [Never re-serialize](#never-re-serialize)
  - [Parse](#parse)
  - [Model](#model)
  - [Scan](#scan)
  - [Staging](#staging)
  - [Compile and verify](#compile-and-verify)
  - [Apply](#apply)
  - [Journal and Undo](#journal-and-undo)
- [Screens](#screens)

## Data flow

    scan_flavors(flavors, account=None, progress=None) → ScanResult(flavors[FlavorScan(flavor, accounts[AccountScan(files[AddonFile(SvFile, dbs[AceDb])], characters)], warnings, error)])
    Staging.from_scan(scan, locked=) → delete / assign / rename / copy / remove_leftovers / keep_only_default / everyone_to_default → OpResult(applied, refused, notes)
    compile_file(states_of_one_file, data) → FileEdit(file, data, changes, expected{sv_name: Expected})
    verify_edit(edit, old_bytes) → [problems]
    apply_flavors([(flavor, [DbState]), ...], root, journal_dir, keep_journals, keep_snapshots, dry_run, account, wow_check, progress)
      (the review passes [general] keep_backups as keep_snapshots and keep_journals; 0 snapshots = keep all)
                      → MultiApplyResult(dry_run, runs[FlavorRun(flavor, result: ApplyResult, error)], journal_path)
    undo_run(journal_path, wow_root, root, keep_snapshots, wow_check, progress, parallelism=1, on_flavor=None,
             on_flavor_done=None) → UndoResult(outcomes, snapshots)
    recover(marker, wow_root, root, journal_dir, keep_snapshots, wow_check, progress) → UndoResult

Modules in `tools/ace3_profile_manager/` (all UI-free except `app.py`, `review_screen.py`, `tree_view.py`, `popups.py`,
`blacklist_screen.py` and `result_screen.py`): `events`, `settings`, `help` (`HELP`, `GUIDE_URL`), `model`, `scanner`, `ops`, `verify`, `editor`, `multi`,
`journal`, `undo` and `report` (labels, tags, confirm texts). The write pipeline is core's (`core/sv_apply.py`,
`sv_journal.py`, `sv_undo.py`, `sv_verify.py`, `sv_report.py`): `editor`, `multi`, `journal` and `undo` are thin
wrappers passing `SV_TOOL` (`events.py`: name `ace3-profile-manager`, prefix `ace`) and, for `editor`, the per-file
compile (`ops.compile_file`) and verify (`verify.verify_edit`, on `core/sv_verify.py`); `report` re-exports the
shared stage titles and result rows.

### Never re-serialize

Every change is a byte-span splice; every byte outside the edited spans stays identical.
Only `profileKeys` entries, `profiles` entries, `namespaces[*].profiles` entries and the LibDualSpec
`namespaces["LibDualSpec-1.0"].char[*]` spec values may change.

### Parse

Code: `core/luasv.py`, shared with Saved Variables Browser. A stdlib tokenizer over the file's raw bytes (strings decode as UTF-8 with
`surrogateescape`). `parse(data, descend)` returns a `Chunk` of `Assignment`s; a table field is a `Field` with
`entry_start`/`entry_end` (the entry and its separator), `key_span`, and `remove_span` (what removing the entry
cuts: its whole line, with a trailing line comment such as WoW's `-- [n]`, when nothing else is on that line); a `Table` records its braces. Values whose path `descend`
rejects are skipped by a compiled-regex scanner that only finds their end (`Opaque`), so a 12 MB file parses in
about a second. Numbers WoW writes oddly (`1.#INF`) stay text (`RawNumber`). `splice(data, edits)` applies
non-overlapping `(start, end, bytes)` edits from the end; `encode_string`/`decode_string` round-trip Lua
strings; new text uses the file's own line ending (`newline_of`). A parse error is `LuaParseError(offset)`.

### Model

Code: `model.py`. `has_profile_keys(data)` pre-filters (no `profileKeys` bytes: never parsed).
`ace_descend` descends only into the database table, `profileKeys`, the keys of `profiles`, each namespace's
`profiles` keys and LibDualSpec's `char` tables. `find_dbs(chunk, data)` keeps a top-level table as an `AceDb` when
`profileKeys` maps `"Name - Realm"` strings to strings and `profiles` (if present) maps strings to tables; any
other look-alike is a note (`ace.lookalike`) and left alone. `AceDb` holds the mapping, `ProfileEntry` per
profile (field, empty, size), `NamespaceProfiles` per module and `LdsChar` per character.

### Scan

Code: `scanner.py`. Per flavor and account (`account=` narrows it): the account's and each character's
`SavedVariables/*.lua` (`core.svfiles.walk_sv_files` with `is_addon_sv_file`: regular files directly in the folder,
exactly `.lua`, not `Blizzard_*`, no link), skipping a SavedVariables folder under a link (a scan warning). Each file is read once; `SvFile` (`core/svfiles.py`) keeps
path, flavor, account, owner character, size, mtime and SHA-256 (not the bytes). Characters come from the
`<Realm>/<Name>` folders; `AccountScan.is_leftover` compares `"Name - Realm"` ignoring case. Unreadable and
unparsable files become `SvScanWarning`s (`core/svfiles.py`, shared with the Saved Variables Browser's scanner).

### Staging

Code: `ops.py`. `Staging` holds a `DbState` per database (`DbKey(path, sv_name)`): `keys` (character →
profile, or removed), `profiles` (name → `Original(name)` or `CopyOf(name)`), `module_only` (profiles that exist
only in a namespace: they change only when a delete or rename names them), the LibDualSpec specs and the
leftovers. Operations change only this model and return `OpResult` (`applied` keys, `refused` with a reason per
database, `notes`). A locked (blacklisted, not unlocked) addon is refused; `drop_locked()` resets one that became
locked, and `changed()`/`summary()` never include one. `DbState.changes()` lists deleted, renamed, copied,
reassigned and removed entries; `Summary` counts them for the left pane and the confirm.

### Compile and verify

Code: `ops.compile_file`, `verify.py`. Per file, the pending states become edits against the
parsed original: a changed `profileKeys` value is a value-span replace, a removed one an entry removal; in
`profiles` and every namespace holding the profile a delete removes the entry, a rename replaces the key span and a
copy inserts `[new] = <source value bytes verbatim>,` before the closing brace; LibDualSpec spec values follow
renames and deletes. `FileEdit` carries the new bytes, human-readable change lines and an `Expected` model per database.
`verify_edit` parses the new bytes again and compares: the mapping, profile names per table, LibDualSpec entries,
each kept or copied profile byte-identical to its source, every other top-level variable and the gaps between
them byte-identical, and the namespaces section with only the profile tables and spec values cut out. Any
mismatch fails the file (`ace.verify_failed`) and stops the run before anything is written.

### Apply

Code: `editor.apply_flavor`, `multi.apply_flavors`, on `core/sv_apply.py`. `apply_flavors` refuses while WoW runs (`WowRunning`,
skipped for a dry run; the review screen checks only the flavors with pending changes), opens one `ProfileJournal`
for the run, then per flavor: a real run is refused while an earlier run's crash marker is there
(`ace.earlier_unfinished`: it would overwrite, then clear, the only pointer to that run's originals; the review
screen offers that recovery again instead); `SvGuard`; recheck each file's
SHA-256 (a changed file is skipped, "changed since the scan; rescan", `ace.file_changed`); compile and verify. A
dry run stops here (`would_edit` outcomes, nothing written). A real run: journal open, probe leftovers recovered,
lock probe (`probe_lock`; any locked file refuses), whole-WTF snapshot (`core.snapshot`,
`<root>/snapshots/snapshot-<flavor>-<stamp>.zip`), the originals zip `<root>/edited/edited-<flavor>-<acct|all>-<stamp>.zip`
(`core.backup`, verified), the crash marker `<root>/edit-in-progress.json` (`Marker`: flavor, flavor path, zip,
`files` rel → original SHA-256, `after` rel → SHA-256 of what the run writes, started, pid, suite version), then
per file: recheck, `atomic_write_bytes`, read back, journal `edited` entry. Any failure there (Ctrl+C included)
puts back every file this run wrote, newest first, records `rolled_back` in the journal and raises `ApplyError`
(its `result` keeps what was done; a file that could not be put back is `failed`, its detail naming the zip, and
the marker then stays). Then the marker is cleared (`core/marker.clear_marker` tries again after 0.05, 0.1 and 0.2 s;
a marker still there is `ApplyResult.marker_left`, `ace.marker_left`, and a "Crash marker" result row) and snapshots
pruned to `keep_snapshots`. Any refusal before the
writes is an `ApplyError` ending "Nothing was changed."; a flavor that stops ends the run (`ace.flavors_stopped`).
`apply_flavors` is serial whatever `[general] parallelism` says: the flavors share the one crash marker (one pointer
for the recovery screen) and the run stops at the first flavor that fails.
Afterwards journals are pruned to `keep_journals` and `prune_edited_zips` deletes only `edited-*.zip` files no kept
journal names (nothing when a journal cannot be read). The review screen checks the backup folder with
`validate_backup_dir` before an Apply, an Undo or a recovery (it may have been edited by hand in the cfg).

### Journal and Undo

Code: `journal.py`, `undo.py`, on `core/sv_journal.py` and `core/sv_undo.py`. `<WoW>/wow-tools/ace3-profile-manager/journal/journal-<stamp>.jsonl`:

    {"version": 1, "started": iso, "tool": "ace3-profile-manager", "kind": "apply", "flavors": [...], "root": stored, "suite_version": "..."}
    {"action": "edited", "flavor": "_retail_", "path": stored, "rel": "WTF/Account/...", "zip": stored, "sha_before": hex, "sha_after": hex, "size_before": n, "size_after": n, "changes": [...]}
    {"action": "rolled_back", "flavor": "_retail_", "rels": [...]}
    {"action": "completed", "flavor": "_retail_", "zip": stored}
    {"finished": iso, "entries": n}
    {"undone": iso, "restored": n, "skipped": n}

`read_profile_journal` drops `edited` entries a `rolled_back` line names. `latest_undoable` is the newest journal of
the whole tool. `undo_run` refuses while WoW of a flavor the journal changed runs and when a file is locked
(`UndoError`), snapshots each of those flavors that has an entry passing `safe_destination` (`undo_flavors`, the
same list the popup's rows come from), up to `parallelism` at once (`core/parallel.py` with
`stop_on_error`: every snapshot is its own zip of its own WTF folder; the first failure, in flavor order, is raised
as "Nothing was changed" once the running ones ended, and a flavor not started by then never starts, so with 1 it
stops where the serial loop did; the snapshots made by then are deleted, `ace.snapshot_discarded`, as they protect
nothing; `on_flavor` / `on_flavor_done` run in the snapshot's thread, the popup's
`start_unit` / `finish_unit`, one row per flavor), prunes them to `keep_snapshots` afterwards, then in the
worker's own thread, newest entry first: a file whose SHA-256 is `sha_after` gets
its original bytes from the zip (checked against `sha_before`, written atomically: "restored"); any other file is
"skipped: changed since"; the journal is marked undone unless nothing was restored and something failed.
`recover(marker)` (the recovery popup's "Put the originals back") first looks for a journal that records the
marker's run as finished (spec R2): it holds a `completed` line for the marker's flavor and zip (Apply writes it once
that flavor's write loop got through every file, before it removes the marker; never after a failure or Ctrl+C, so
the run-level `finished` line, written either way, is not used) and an `edited` entry from the marker's zip for every
file of the marker, except a file the run skipped as changed in its write loop, which counts when it is not at the marker's
`after` hash. Such a run finished and only its marker was left (Apply logged `ace.marker_left`), so nothing is put
back: the marker is removed, `ace.marker_stale` is logged and the result has `UndoResult.stale_marker` set; neither
the flavor check nor the WoW-running and lock guards run, since no file is touched, and the run stays in its
journal for Undo. Otherwise `recover` is guarded as Undo and puts back only files
still at the marker's `after` hash, each resolved under the configured WoW folder (`wow_root`), never the marker's
own `flavor_path` (a marker written on the other OS names a folder this one cannot open); a marker whose flavor is
not a folder there is refused with "Nothing was changed." and kept; a file at its original is left alone, any other
is skipped. The files now at their original get a `rolled_back` line in the journal that holds their entries from
the marker's zip (`journal.record_recovered`), so Undo never offers them again; its snapshot is pruned to
`keep_snapshots`. When removing the marker fails again (another program still holds it), the result has
`marker_left` set and `ace.marker_stale` or `ace.recovery_done` is logged at warning with `marker_left`;
`recovered_notice` then says the marker is still there and the review keeps it, so the next scan offers it again.
"Leave as is" is `undo.leave(marker, root=)` (core `sv_undo.leave`): it removes the marker and logs
`ace.recovery_done` `choice="leave"`; when the marker could not be removed it returns False, and the review keeps
the marker and shows `leave_notice()`.

## Screens

`app.py` holds `AceProfilesFlow` (`FLOW`: `require_install` → `ProfileSettingsScreen` on the tool's first open →
`FlavorScreen(include_all=True, last=last_flavor_choice)` → `AccountScreen` for one flavor with several accounts
(`last_account`) → `ProfileReviewScreen`; `unlocked`, the addons unlocked this session, lives on the flow) and
`ProfileSettingsScreen` (backup folder, a `#blacklist-summary` line and **Edit blacklist…**, which opens the
`BlacklistScreen` and keeps its answer until Save; `validate_backup_dir` errors inline). `s` opens the shared WoW-folder settings, then this tool's (not while a `ProfileSettingsScreen` or a `BlacklistScreen` is on the stack: two Saves would overwrite each other).

- `ProfileReviewScreen` (`review_screen.py`): `TreeFilter` and `ReviewBase`, `two_pane_css`. Left pane `#filters`, one control
  per row: the shared `RiskBanner` (D37), the View pair under a "View" heading (By addon / By character), the Show boxes under a "Show" heading, the
  shared `FilterBar` (its box id `#search`, `FILTER_SELECTOR`), the `#pending` line (`report.pending_text`, "N pending changes" or `NO_PENDING`) and the
  action row **Apply** (destructive), **Dry run**, **Rescan**, **Undo last change** (revert). Right:
  `BarTree` (`#profiles`, the shared `ReviewTree` whose ↓ on the last line goes on to the action bar), built by `tree_view.TreeBuilder` from the scan, the staging, `Filters` (the
  Show boxes) and the screen's `TextFilter` (matched on the path: flavor with several, account, addon, database,
  profile, character; while it is set every group opens and the user's expansion is not remembered); each
  rebuild keeps expansion and the cursor by `ident`. The builder already narrows the tree, so the keys shown are
  the root's (`filter_keys`), `all_tick_keys` adds every tick, and `tree_narrowed()` is always true: a tick a Show
  box hides counts as hidden too. `a` / `n` act on what is shown; Delete, Assign, Leftovers, Only Default and
  Everyone → Default still take every tick (falling back to the highlighted node only with no tick at all), and
  their popup (a toast for the two that stage at once) says how many ticks are hidden. Labels and tags come from `report.profile_rows` and
  `char_tags`. Ticks are `("p", DbKey, profile)` and `("c", DbKey, char)`; groups tick their descendants; locked
  addons, deleted profiles, removed characters and notes are read-only. `#summary` is `report.selection_text` plus
  the hidden-ticks line.
  The scan, the running-WoW preflight, Apply/dry run, Undo and recovery each run in a worker; the jobs set
  `app.busy` and run inside `activity.running()`.
  The tree sits in `#tree-pane` above the guidance line `#guide` (`report.guidance`: the four `STEPS` on the root,
  a flavor or an account or with nothing highlighted, else `report.node_hint` for the highlighted node; with
  pending changes the pending count and the w/y/⌫ keys come first, and the node hint follows within
  `GUIDE_MAX_ROWS` (2) rows: a name too long for the hint's row at 120x30 is shortened with "…", and the hint is
  left out only if even that does not fit; on a locked addon the hint names it and the `u` unlock) and the action
  bar `#tree-actions`, a
  `ActionBar` (a `WrapButtonRow`; ↑ goes back to the tree, and ↓ on the tree's last line comes to it) of
  `TREE_ACTIONS`, staged changes first (amber; Copy green, it only adds a profile), then staged deletes (red), then the rest (Assign, Rename, Copy,
  Everyone → Default (E), Delete, Only Default (D), Leftovers, Blacklist…, More…, Discard: three rows at 120x30, two at 160x45), each button doing what
  its key does. The focused button's `ActionTip` (`action_tip()`: what it would do with the ticks or the
  highlighted node now) sits on its own `action-tip` layer just above the guidance line over the bar, and
  `_place_overlays()` keeps Textual's toast rack above the tip (or the guidance line). With nothing ticked, Delete and Assign act on the
  highlighted node, but never on the root, a flavor or an account (`GROUP_KINDS`). The guide follows the cursor, the ticks and the pending
  changes. Discard is Backspace (`x`/`c` are expand and collapse all); `b` toggles the highlighted addon's
  (flavor, addon) pair through the shared `BlacklistAction` (`ui/review.py`; `core/blacklist.toggle_pair`) and saves at once; **Blacklist…** (`action_edit_blacklist`) opens
  the `BlacklistScreen` for the review's flavors and saves its answer at once.
- `BlacklistScreen(cfg, flavors, pairs)` (`blacklist_screen.py`): `TreeFilter` and `ReviewBase`, `two_pane_css`. Left
  pane: an explanation, the `FilterBar` (filter box and **Filter** button) and **Save** / **Select none** / **Cancel** (keys `n` and Esc on the buttons); right: a flavor → addon tree, from its own
  scan worker (`scan_flavors`), of every addon with Ace3 data plus each blacklisted pair no longer found
  ("(not found)"; a legacy `"*"` pair is listed under every shown flavor, so a Save, or a failed scan, never drops
  it). A ticked pair is blacklisted; nothing else is ticked. `a`/`n`/`/`/`x`/`c` as on every tree (the filter
  matches flavor and addon names; a mark counts the keys shown). With ticks the filter hides, Save asks first
  (`ConfirmScreen`, kind `confirm`, saying how many). It
  dismisses with the new pair list (or `None`); pairs of flavors it does not show are kept, and a legacy `"*"`
  pair is saved as explicit pairs (for the hidden flavors too).
- `popups.py`: `TargetScreen` (delete and assign: a target `Select` plus a new-name `Input`), `NameScreen` (rename
  and copy, with live validation) and `ActionsScreen` (the `m` menu: every key the footer
  and the action bar hide, under the `ACTION_GROUPS` headings Selection and Modification), styled with the shared `popup_css`; `NameScreen` is the shared `TextPromptScreen` checked with `valid_name`. Apply and Undo use `ConfirmScreen` (`report.apply_confirm`/`undo_confirm`; alerts
  in red; Yes red for Apply and Undo, cyan for a dry run).
- `ProfileProgressScreen(title, dry_run=, first_stage=, flavors=)` (ids `ace-*`, `report.STAGE_TITLES`; Apply feeds `report_unit`, a row per flavor in turn) and `ProfileRecoveryScreen` (the shared `UnfinishedRunScreen`: Put the originals
  back / Leave as is; Esc leaves the marker for the next scan). The review's apply, undo and recovery runs go through
  the shared `RunActions` (`ui/review.py`).
- `ProfileResultScreen` (`result_screen.py`): the shared `ResultScreen` built from rows; `#result-summary` (`apply_summary_rows` or
  `undo_summary_rows`: zips and the journal are named inside the backup folder, `report.in_backup_folder`, which
  has a "Backup folder" row of its own) above `#result-detail` (`DETAIL_COLUMNS` or `UNDO_COLUMNS`); Rescan, Other flavor,
  Tools, Quit (keys `r` `f` `t` `q` on the buttons), plus a focused **Back to review** (Esc) after a dry run. After a real Apply or Undo the
  staging is dropped and the review rescans when shown again.
