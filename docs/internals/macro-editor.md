# Macro Editor internals

How the Macro Editor (`wowtools/tools/macro_editor/`) reads every `macros-cache.txt`, stages edits, pastes and
deletes, writes them through the shared client-file pipeline, and how its screens are built.

User guide: [macro-editor.md](../macro-editor.md). Rules every tool follows: [standards.md](../standards.md).
Back to [architecture](../architecture.md#tools). Decisions: spec `ME1`-`ME14`, `X1`-`X5`, facts `V4`, `V5`
(`docs/superpowers/specs/2026-11-04-config-copier-macro-editor-config-editor-design.md`).

## Contents

- [The file and its IDs (V4, V5)](#the-file-and-its-ids-v4-v5)
- [Data flow](#data-flow)
- [Staging](#staging)
- [Knowledge base](#knowledge-base)
- [Safety](#safety)
- [Screens](#screens)
- [Events](#events)
- [Tests](#tests)

## The file and its IDs (V4, V5)

`core/macrofile.py` reads and splices the Retail layout byte-exact: `VER 3 <16 hex id> "<name>" "<icon>"`, the body
lines, `END`, every line CRLF, UTF-8 with `surrogateescape`. Any other shape (LF-only, a block without `END`, an older
layout, a duplicated id) comes back `known_layout` False: the set is read-only (ME14), listed in the warnings view and
never written. Action bar buttons point at macro IDs (V5), so an edit or an overwrite keeps the macro's id, and a new
or pasted macro gets the highest id of its prefix (`00` account, `01` character) plus one; a macro deleted in the same
Apply never gives its id away (`ops._next_id`, T13c).

## Data flow

    MacroEditorFlow: settings (first run) → FlavorScreen (All flavors allowed) → MacroReviewScreen(flavors)
    scan worker: scanner.scan_sets(flavor) per flavor → [MacroSet(flavor, account, character, path, parsed, data, sha256)]
        account set, then each real character's (X3); no file = an empty, writable set (sha256 None: the run creates it)
    tree: populate_characters(..., account_extra=Account macros node, character_extra=macro leaves)
        tick keys: SetKey(path) (a Paste… target), MacroKey(path, id) (Copy / Delete / Replace text)
    edits (edit_actions.py) → ops.stage_new / stage_edit / stage_delete / preview_paste / stage_replace_text on Staged
    Apply / Dry run → runner.run_apply(staged, sets) = changes_by_flavor(build_changes(...))
        → core/client_apply.apply_client_flavors (one run over every flavor: one journal, one Undo)
    Undo → undo.undo_run(journal) (client_apply.undo_client_run, names = {macros-cache.txt})

## Staging

`ops.Staged` holds at most one `MacroChange` per id and file, folded as the user works (T13b). Every operation reads
the set as staged (`effective_macros`), so slot counts and a second Replace text see earlier changes. The tree shows
`review_screen.macro_rows`: the file's macros in order (changed ones with their new text, deleted ones struck), then
the new ones. Paste… runs `ops.preview_paste` on a copy of the staging with the clash choices the popup holds (skip by
default; `clash_key` = target path and cut name); Paste keeps that copy. `report.paste_warnings` adds the ME5 lines
for another game version: one per (from, into) pair, then each macro's `explain.unknown_terms` against the target
version's `core.kb.load_macro_reference`.

## Knowledge base

The editor's help, suggestions, warnings, builder, optimizer and templates are data under `wowtools/kb/`, read by
`core/kb.py` (X6; schema and the sources rule in `wowtools/kb/README.md`). Every entry carries a `source`; one without
it is not loaded, so nothing is described from a guess.

- `macro_reference.json` → `load_macro_reference(flavor)`: commands, conditionals and `@unit` targets with their help
  and plain-English phrases (`explain_block`, the help panel, `F1`), and the `builder` lists (ME9). An entry's
  `flavors` names the flavors its source says it applies to; `null` (not stated) is never flagged by
  `explain.unknown_terms` (ME5). Whether a flavor has a command at all comes only from its
  `slash_commands/<flavor>.json` dump (X7); with no dump yet, no command is flagged as missing.
- `macro_templates.json` → `load_templates()`: the templates (ME11), each with `{placeholder}`s and a source.
- `optimizer_rules.json` → `load_optimizer_rules()`: the optimizer's rules (ME10) with the reason each rewrite is the
  same in game; `optimizer.optimize` applies only the `automatic` ones (`cast_to_use` is listed, never applied).
- `macro_limits.json` → `macro_limits(flavor)`: the slots (ME3), sourced per flavor (Retail from the client's
  `MacroConstants`; `_classic_`, `_classic_era_` and `_anniversary_` from their client dumps, source
  `client dump <flavor> <build>`). `_forever_` has a `provisional` copy of Retail's entry (T20d) with
  Retail's source, which the tools don't read: Forever counts as known (`limits_known` True) and is never marked. Any
  other flavor counts with Retail's values (`limits_known` False); `MacroSet.limit_known` carries that, and
  `report.slots_text` marks the set's slots `unconfirmed` (T17r).

Spell names are free text (ME12): there is no spell data, nothing checks or suggests them, and the optimizer never
changes them (`showtooltip_same` only compares the directive's spell with the first one cast;
`test_optimize_never_changes_spell_text`).

## Safety

Every write goes through `core/client_apply.py` (X5): refused while that game version's WoW runs, Dry run that writes
nothing, SHA-256 recheck against the scan, whole-WTF snapshot per flavor, originals zip, crash marker and journal
before the first write, atomic write and read-back, Undo of the last Apply, recovery after a crash. `NAMES` is
`{"macros-cache.txt"}`, so each flavor's `ClientFileGuard` refuses `cache.md5`, `.old` files and anything outside an account or real
character folder. Leaving, quitting, a rescan and Undo ask before dropping staged changes.

## Screens

- `review_screen.MacroReviewScreen`: the shared two-pane review (`WarningsHost`, `MacroEditActions`, `TreeFilter`,
  `SvRecoveryActions`, `RunActions`, `ReviewBase`). Left pane: the risk banner (STD-7.10), the filter box with
  Names / Bodies / Only matching macros, the staged line, Apply / Dry run / Rescan / Undo last change. The bar under
  the tree: New `N`, Edit `e`, Delete `d`, Copy `k`, Paste… `p`, Replace text… `R` (`edit_actions.TREE_ACTIONS`).
  The leaf (STD-7.27) is a macro line as `macro_rows` lists it and the search leaves it (a staged delete included:
  it stays a struck line until Apply, while the slots leave it out); a read-only set lists none. The root, a
  flavor, an account, a realm, a character and Account macros end with the lines the tree shows under them,
  counted in `_add_macros` as the tree is built (`_set_idents`; nothing loads on expand), so a realm or an account
  with no macro lines says `0 items`, and a set with none (a leaf) has no count. A macro line is columns
  (STD-7.28, `report.macro_cells`, `MACRO_COLUMNS`): name · first line · `n/255`, as wide as the set's widest
  cells; the first line gives way first, cut at its end, then the name, cut in its middle; the length is never cut,
  only dropped (after the first line). The staged mark's room is kept blank on the other lines of a set that has
  one, so the names line up. A character's or Account macros' line is name · slots (or `read-only`) · count
  (`SET_COLUMNS`), aligned across a realm's characters (`_character_widths`); the slots are never cut, only
  dropped. An account's, realm's or flavor's name is cut in its middle so its count fits the pane
  (`_group_text`); every line is fitted again on a resize (`_fit_rows`).
- `edit_screen.MacroEditScreen` (New, Edit; ME8): name (cut at 16), icon, scope line, the `n / 255` meter (Save off
  over 255), `MacroTextArea` with the suggestion list (`syntax.suggestions`, replacing from `syntax.completion_start`;
  ↑/↓, Tab/Enter, Esc while it shows; Enter after a word that is itself an entry is a new line unless ↑/↓ moved the
  highlight, and a taken suggestion's own Changed lists nothing) and the help panel (`explain.describe_at`, plus `unknown_terms` for the flavor).
  Ctrl+B `builder_screen.BuilderScreen` (ME9: `builder.read_block` / `write_block`, an unchanged block stays as
  written, unshown items kept), Ctrl+O `optimize_screen.OptimizeScreen` (ME10: each `Rewrite` with its reason and
  source; OK takes the body), Ctrl+T `template_screen.TemplateScreen` (ME11: fill the placeholders, inserted as whole
  lines after the cursor's line), F1 `reference_screen.ReferenceScreen` (`explain.reference_lines`).
- `popups.PasteScreen` (clashes, Skip / Rename / Overwrite, Apply to all, refusals and warnings), `ReplaceTextScreen`.
- `MacroResultScreen` (the shared result screen), `MacroProgressScreen` (one row per flavor).

## Events

`macro.started`, `macro.scanned`, `macro.file_unreadable` and the pipeline's `macro.*` events
(`sv_events.client_events("macro")`); see [events.md](../events.md).

## Tests

`tests/test_macro_editor_ops.py` (staging and the bytes), `tests/test_macro_editor_syntax.py` and
`tests/test_macro_editor_optimizer.py` (the reference, explainer, optimizer and templates), `tests/test_macro_editor_edit.py`
(the edit screen, builder, optimizer, template and reference screens, and their UI-free halves), `tests/test_macro_editor_run.py`
(runs across files and flavors, dry run, WoW running, a file changed since, the paste preview and warnings, texts) and
`tests/test_macro_editor_app.py` (the browse screen end to end; `NodeCountsAndColumnsTest`: every node's count, also
under a search, Only matching macros off and a staged delete, the macro and character columns aligned, every line
fitting the pane at 120x30 and 80x24), on `tests/fixtures.py` `build_macro_tree`.
