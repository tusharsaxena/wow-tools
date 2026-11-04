# Config Editor internals

How the Config Editor (`wowtools/tools/config_editor/`) reads every `Config.wtf` and `config-cache.wtf`, lists their
CVars with the knowledge base's help, stages edits, writes them through the shared client-file pipeline, and how its
screens are built.

User guide: [config-editor.md](../config-editor.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools). Decisions: spec `CE1`-`CE8`, `X1`-`X8`, facts `V1`, `V2`
(`docs/superpowers/specs/2026-11-04-config-copier-macro-editor-config-editor-design.md`).

## Contents

- [The files](#the-files)
- [Data flow](#data-flow)
- [Staging](#staging)
- [Safety](#safety)
- [Screens](#screens)
- [Events](#events)
- [Tests](#tests)

## The files

`core/cvarfile.py` reads and splices `SET <name> "<value>"` lines byte-exact: every other line and every line not
changed keeps its bytes and place, the file's own line ending is kept (CRLF or LF), added lines are appended. Three
levels (CE3): `WTF/Config.wtf` (machine), `WTF/Account/<A>/config-cache.wtf` (account) and the real characters'
(X3: `Bob - Copy` is never one). A missing file is an empty target that a set creates; a file that can't be read is
read-only (`ConfigTarget.problem`), listed in the warnings view and never written. The CVar data
(`core.kb.load_cvars`: default, Blizzard help, our wiki-based note, category, scope, synced; X6-X8) and the
recommendations (`core.kb.load_recommendations`, CE7) come from `wowtools/kb/`; a flavor without data shows every
CVar as `unknown`.

## Data flow

    ConfigEditorFlow: settings (first run) → FlavorScreen (All flavors allowed) → ConfigReviewScreen(flavors)
    scan worker: scanner.scan_targets(flavor) per flavor → [ConfigTarget(flavor, level, account, character, path, ...)]
        plus kb.load_cvars(flavor) and kb.load_recommendations(flavor) (kb_root: tests point it at a temp folder)
    tree: Config.wtf FileNode, then populate_characters(..., account_extra=Account config FileNode,
        character_extra=the character's file, rows loaded when the node opens)
        tick keys: FileKey(path); rows: ops.rows(target, cvars, filters, staged) → CvarNode leaves
    edits (edit_actions.py) → ops.stage_set / stage_remove / stage_reset / stage_toggle on ConfigStaged
    Apply / Dry run → runner.run_apply(staged, targets) = changes_by_flavor(build_changes(...))
        → core/client_apply.apply_client_flavors (one run over every flavor: one journal, one Undo)
    Undo → undo.undo_run(journal) (client_apply.undo_client_run, names = {Config.wtf, config-cache.wtf})

## Staging

`ops.ConfigStaged` holds per file the CVars to set and to remove, folded as the user works (T18e). Set, Remove and
Reset act on the highlighted CVar in every ticked file (else its own file), Add on the ticked files (else the
highlighted one), Space on a 0/1 row toggles it in place (`stage_toggle`), Recommend… lists
`ops.applicable_recommendations` (the CVar's KB scope is the file's level, or unknown) and stages the ticked ones.
Reset is remove (CE5) and is offered only for a CVar with a known default; Remove takes any CVar's lines out. A set in
a file whose level is not the KB scope is allowed; the confirm lists it (`report.scope_listed`).

## Safety

Every write goes through `core/client_apply.py` (X5): refused while that game version's WoW runs, Dry run that writes
nothing, SHA-256 recheck against the scan, whole-WTF snapshot per flavor, originals zip, crash marker and journal
before the first write, atomic write and read-back, Undo of the last Apply, recovery after a crash. `NAMES` is
`{"Config.wtf", "config-cache.wtf"}`, so the guard refuses `cache.md5`, `.old` files and anything outside
`WTF/Config.wtf` or an account or real character folder (V2). Leaving, quitting, a rescan and Undo ask before dropping
staged changes.

## Screens

- `review_screen.ConfigReviewScreen`: the shared two-pane review (`WarningsHost`, `ConfigEditActions`, `TreeFilter`,
  `SvRecoveryActions`, `RunActions`, `ReviewBase`). Left pane: the risk banner (STD-7.10), the filter box (a CVar's
  name, help and note, or its file's group), Show (category select, Changed only, Show all known), the staged line,
  Apply / Dry run / Rescan / Undo last change. The bar under the tree: Set `e`, Add `N`, Remove `d`, Reset `R`,
  Recommend… `m` (`edit_actions.TREE_ACTIONS`). The help panel (`report.help_lines`) sits under the tree, or beside
  it from 160 columns (`HORIZONTAL_BREAKPOINTS`, the `-wide` class).
- `popups.AddCvarScreen` (name, value, what the KB knows of the name), `RecommendScreen` (tick list, reason and
  source); Set is the shared `TextPromptScreen`.
- `ConfigResultScreen` (the shared result screen), `ConfigProgressScreen` (one row per flavor).

## Events

`cvar.started`, `cvar.scanned`, `cvar.file_unreadable` and the pipeline's `cvar.*` events
(`sv_events.client_events("cvar")`); see [events.md](../events.md).

## Tests

`tests/test_config_editor_ops.py` (files, rows and staging), `tests/test_config_editor_run.py` (runs across levels and
flavors, created files, dry run, WoW running, a file changed since, recovery, texts, Recommend…'s list) and
`tests/test_config_editor_app.py` (the browse screen end to end), on `tests/fixtures.py` `build_config_tree` and a temp
knowledge base.
