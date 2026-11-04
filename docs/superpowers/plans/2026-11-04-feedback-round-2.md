# Feedback round 2: implementation plan

> **For agentic workers:** run task by task (implement test first, review, fix). Steps use checkboxes.

**Goal:** spec R1-R6: leaf counts and columns as suite standards adopted by all eight tools, plus Config Editor
polish.

**Spec:** `docs/superpowers/specs/2026-11-04-feedback-round-2-design.md`

## Global Constraints

- Branch `feat/config-editor-feedback-1` (round 1 is on it, unmerged; this round continues it). Green gate before
  each commit. Check the gate's exit status itself, not a piped `tail`.
- `core/` never imports textual; a tool never imports another tool; shared code lives once in `ui/` or `core/`.
- 120x30 and 80x30 still fit.

## Review Focus

1. Counts that disagree with what the tree shows after a search or a Show filter.
2. Lazily loaded nodes showing `0 items` before they are opened.
3. Columns that misalign between sibling rows, or a long cell pushing a status off screen.
4. A tool's existing tests or screenshots pinned to the old labels, silently loosened instead of updated.
5. Performance: counting or fitting on every keypress over thousands of nodes (SV Browser, Screenshot Organizer).

---

### G1: shared helpers and the two standards (R2, R4)

- [ ] `wowtools/ui/columns.py`: move `fit_columns` (and the cut-with-`…` helper) out of `config_editor/report.py`;
  config_editor imports it. A generic `column_text(cells, widths, styles)` that builds the Rich `Text`.
- [ ] `wowtools/ui/` count helper: `count_text(n) -> str` (`1 item` / `n items`) and the dim style; a function that
  appends it to a node label.
- [ ] `docs/standards.md` section 7: two new MUST rules (leaf counts, node columns) with reasons and the tests that
  enforce them (each tool's app test); `docs/architecture.md` and `docs/common-tasks.md` (tree screen recipe)
  mention both. WTF Cleaner may already have a count helper: reuse or move it rather than duplicate.
- [ ] Tests for the helpers.

### G2: Config Editor (R1, R2, R3, R5, R6)

- [ ] R6 data: the re-sorted groups for the 250 "other" CVars are supplied in the task prompt; add `game state`,
  `debug`, `system` to `CATEGORY_GROUPS` (order: graphics, sound, interface, camera, nameplates, combat text,
  network, game state, debug, system, other), their colours, update `cvar_categories.json`, the KB README, tests.
- [ ] R2 counts on every node (flavor, Config.wtf, account, account config, realm, character), counted from the
  model under the current filters, including unopened files.
- [ ] R1 help panel colours, R3 darker not-set rows, R5 dropdown counts updated on every filter change.
- [ ] Guide and internals.

### G3-G9: adopt R2 and R4 in each other tool

One task per tool, each: decide the leaf and the columns, adopt the shared helpers, update the tool's app tests
(assert the count on each node level and the column alignment), internals doc and guide, and list stale screenshots
in the ledger.

- G3 WTF Cleaner (counts exist: move to the helper; columns for `name · reason · files · size · age`)
- G4 Screenshot Organizer
- G5 Interface Backup
- G6 Ace3 Profile Manager
- G7 Saved Variables Browser
- G8 Config Copier
- G9 Macro Editor

### G10: CHANGELOG, whole-branch review, push, CI

- [ ] One CHANGELOG `[Unreleased]` line for the counts and columns; a fresh whole-branch review (separate
  workflow), push, CI once.
