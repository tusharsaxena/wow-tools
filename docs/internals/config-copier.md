# Config Copier internals

How the Config Copier (`wowtools/tools/config_copier/`) plans a copy of a character's client files, merges
`config-cache.wtf`, writes through the shared client-file pipeline, and how its screens are built.

User guide: [config-copier.md](../config-copier.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools). Decisions: spec `CC1`-`CC8`, `X1`-`X5`, facts `V1`-`V5`
(`docs/superpowers/specs/2026-11-04-config-copier-macro-editor-config-editor-design.md`).

## Contents

- [Why a plain copy works (V1, V2)](#why-a-plain-copy-works-v1-v2)
- [Data flow](#data-flow)
- [The config merge (CC5)](#the-config-merge-cc5)
- [Safety](#safety)
- [Screens](#screens)
- [Events](#events)
- [Tests](#tests)

## Why a plain copy works (V1, V2)

Checked in the client on 2026-11-04 (spec V1-V3). Each account and character folder holds a binary `cache.md5`: one
24-byte record per synced file (16-byte MD5, 4-byte little-endian timestamp, 4 zero bytes) at a fixed slot per file
type. `config-cache`, `macros-cache`, `layout-local` and `chat-cache` have slots; `AddOns.txt` is not tracked. Five
files copied with WoW closed left `cache.md5` stale, yet at login the client used the copied files, and at logout it
rewrote `cache.md5` with the new fingerprints and made its own `.old` files; nothing was reverted from the server.
So the copier writes only the plain files and never `cache.md5` or `.old` files: they are not in `NAMES`, so the
pipeline's guard refuses them. The client also prunes some state at logout (tracked quests the character lacks, the
reputation list, V3); the guide says so, so a user doesn't take it for a failed copy.

A target with macros loses its action bar links (V5: buttons point at macro IDs, and a copy gives the target the
source's IDs), hence the CC7 warning; the account folder's `macros-cache.txt` (account macros) is never a copy file.

## Data flow

    SourceScreen(flavors, label) → (Flavor, Character)                       (the shared character tree, one choice)
    plan_copy(source, targets, COPY_FILES) → [PairPlan(target, name, status, new, old, old_sha256, warnings, problem)]
        status: new | replace | unchanged | no-source | unreadable;  config-cache.wtf: new = merge_config(source, old)
    review ticks → selected_plans() = ticked PairKey(target, name) of a ticked file whose status is new or replace
    runner.copy_changes(source, plans) → [ClientChange(target/name, new, old_sha256 or None, (journal line,))]
    runner.run_copy(flavor, source, plans, root, journal_dir, keep_journals, keep_snapshots, dry_run, wow_check, progress)
        → core.client_apply.apply_client_changes(SV_TOOL, flavor, changes, names=NAMES) → MultiApplyResult
    undo.undo_run(journal_path, ...) / undo.recover(marker, ...) / undo.leave(marker, root=) → UndoResult

Modules (all UI-free except `app.py` and the `*_screen.py` files):

- `events`: `copier.started`, `copier.planned`, `copier.file_unreadable`, plus `client_events("copier")` (the
  pipeline's events with `file_created` and `file_removed`); `SV_TOOL = SvTool("config-copier", "copier")`.
- `model`: `COPY_FILES` (CC3, in order), `PairPlan`, `MACRO_WARNING` (CC7).
- `planner`: `plan_copy` reads each source file once and each target file, never writes; unreadable files are
  pairs of their own, never copied (logged once per path).
- `merge`: `merge_config(source, target)` (CC5): the target's file with its preferences made exactly the source's;
  state CVars (`core.kb.is_state_cvar`) stay the target's, byte for byte. Built on `core/cvarfile.py`.
- `runner`: `NAMES = frozenset(COPY_FILES)` (the guard refuses any other name, X4; never `cache.md5` or `.old`,
  V2), `COPYABLE`, `copy_changes`, `run_copy`. A pair with no target file is created (`expected_sha256` None:
  refused if it appears meanwhile, journaled `created`).
- `journal`, `undo`: the shared edit journal and `core/client_apply.undo_client_run` / `recover_client_run` with
  `NAMES`; Undo puts back replaced files and deletes created ones, each only while it is what the run wrote (CC8).
- `report`: pair statuses, the confirm (`copy_confirm`, `copy_groups`, `copy_listed` for the CC7 warnings as a
  counted list), result rows, and `diff_rows(plan)` (difflib: three lines of context per change for a plain file,
  the whole file with state lines noted kept for `config-cache.wtf`); `bytes_only(plan)` is true for a replace whose
  lines are the same (only line endings or bytes that are not UTF-8 differ): the diff screen says so.
- `settings`: `[config_copier]` `backup_dir`, `last_flavor_choice`; `resolve_root` = `core.journal.tool_root`.

## The config merge (CC5)

`merge.merge_config(source, target)` works on `core/cvarfile.py`'s byte spans, never re-serialising:

- a CVar is **state** when `core.kb.is_state_cvar(name)` says so (the shipped list in `wowtools/kb/`: names, a few
  patterns such as `closed*`, `*Tutorial*`, `last*`, `saved*Config*`, and exceptions such as `showTutorials`); every
  other CVar is a **preference**;
- every target preference the source lacks is removed (each of its lines); every source preference whose value the
  client would read from the target (`CvarFile.get`, last line wins) differs is set in place (keeping that line's
  ending), and one the target lacks is appended in the source's order; names match case-insensitively;
- with a target file: target state lines stay byte for byte; source state lines and the source's other non-`SET`
  lines are never copied;
- no target file: the source's bytes minus its state lines (its non-`SET` lines, if any, are kept with its
  preferences).

A target whose preferences already match comes back byte-identical, so the planner calls it `unchanged` and it is
never written (the anti-goal "a file changed where the user changed nothing"). Each pattern of the state
list was checked against the 12.1.5 / 5.5.4 / 2.5.6 / 1.15.9 CVar dumps (T20): the tutorial toggles
(`showNPETutorials`, `housingTutorialsEnabled`) are exceptions, kept with the preferences.

## Safety

The copy runs on the shared client-file pipeline (`core/client_apply.py`, X5), not a pipeline of its own: the
SavedVariables one (`core/sv_apply`, `core/sv_undo`, `core/sv_journal`) with `ClientFileGuard` in place of `SvGuard`.
The guard takes only `NAMES` directly in a real character's folder (`core.install.is_character_name`, X3) of the
flavor's `WTF/Account`, nothing under a link. From the pipeline: refused while that flavor's WoW runs
(`copier.wow_running`), dry run in memory, refused while an earlier run's crash marker is there, the SHA-256 recheck of
every target file against what the review read (a changed file is skipped, the rest written), the lock probe, the
whole-WTF snapshot, the originals zip (`edited-<flavor>-all-<stamp>.zip`), the crash marker, the journal, atomic write
and read-back, roll-back on a failed write, and one Undo of the last run. A pair with no target file is a
`ClientChange` with `expected_sha256` None: created with `atomic_create_bytes` (refused if the file appeared since),
journaled `created`; Undo and recovery delete it only while it is still what the run wrote (CC8). The copier's
backups go under `settings.resolve_root()` (`<backup_dir or <wow_path>/wow-tools>/config-copier`), its journals under
`<wow_path>/wow-tools/config-copier/journal`.

## Screens

- `app.CopierFlow`: settings (first run) → `FlavorScreen` (All flavors allowed, X1) → `SourceScreen` → review.
  No USE AT YOUR OWN RISK popup (only the client's own five files, within one game version, with backups and Undo),
  but the review carries the shared `RiskBanner` (STD-7.10): Write overwrites the targets' files.
- `source_screen.SourceScreen`: `populate_characters` without marks under each flavor (All flavors), the shared
  filter (`FilterBox`), **Choose** (Enter) and **Back** (Esc); `t` to the tool menu.
- `review_screen.CopierReviewScreen` (`WarningsHost`, `TreeFilter`, `SvRecoveryActions`, `RunActions`,
  `ReviewBase`): the scan worker plans every real character of the source's flavor; the tree is
  `populate_characters` with `disabled` (source, other flavor) and `character_extra` adding one `PairNode` per file
  (tick key `PairKey(target, name)` when it writes something). A character's own tick key is never ticked: its
  `node_tick_keys` and mark use only its pairs. Left pane: the source, a box per file, the filter, **Write**, **Dry
  run**, **Rescan**, **Undo last change**; **Diff** in the bar under the tree. Ticks are a selection, not staged
  work, so leaving asks nothing.
- `diff_screen.DiffScreen`: the unified diff of one replaced pair, read-only.
- `CopierResultScreen` (`ResultScreen`): the copy, dry run and Undo results.

## Events

`copier.started`, `copier.planned` (counts by status) and `copier.file_unreadable` (warning, once per path) are the
copier's own; every other `copier.*` event is the pipeline's, from `core.sv_events.client_events("copier")`
(`copier.apply_started` … `copier.file_created`, `copier.file_removed`, `copier.wow_running`). The full list with
levels is in [events.md](../events.md).

## Tests

- `tests/test_config_copier_planner.py`: `plan_copy` statuses, byte-for-byte plain files, the CC7 warning, unreadable
  files, nothing written.
- `tests/test_config_copier_merge.py`: `merge_config` (preferences exactly the source's, state kept, no target file,
  identity on equal preferences, line order and endings, odd names).
- `tests/test_config_copier_run.py`: the run on the pipeline (two targets byte-identical, unticked pairs left alone,
  dry run, Undo removing created files, non-ASCII paths and bodies, an unknown macro layout, WoW running, a file
  changed since the review, recovery), the report and diff rows.
- `tests/test_config_copier_app.py`: the TUI flow (source → targets → review → copy), the diff screen, greyed
  targets, the macro warning in the confirm, 80x24. The suite-wide meta-tests (look and feel, help, quit, tool menu,
  toasts, warnings, structure) cover the copier too; `tests/fixtures.py` `reach_review` and `pick_source` reach it.
- `tests/test_docs.py` `test_config_copier_guide_readme_and_notes`: this doc, the guide, the README rows.
