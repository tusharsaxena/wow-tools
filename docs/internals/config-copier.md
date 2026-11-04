# Config Copier internals

How the Config Copier (`wowtools/tools/config_copier/`) plans a copy of a character's client files, merges
`config-cache.wtf`, writes through the shared client-file pipeline, and how its screens are built.

User guide: [config-copier.md](../config-copier.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools). Decisions: spec `CC1`-`CC8`, `X1`-`X5`, facts `V1`-`V5`
(`docs/superpowers/specs/2026-11-04-config-copier-macro-editor-config-editor-design.md`).

## Contents

- [Data flow](#data-flow)
- [Screens](#screens)

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
