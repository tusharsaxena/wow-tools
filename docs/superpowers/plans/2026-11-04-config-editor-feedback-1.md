# Config Editor feedback round 1: implementation plan

> **For agentic workers:** run task by task (implement test first, review, fix). Steps use checkboxes.

**Goal:** the six Config Editor changes of spec CF1-CF6.

**Architecture:** rows, colours and help stay in `wowtools/tools/config_editor/` (review_screen, help, popups); the
category data lives in `wowtools/kb/cvar_categories.json`, read by `core/kb.py`; the colours in `ui/theme.py`.

**Tech stack:** Python 3.10+, Textual, Rich `Text`.

**Spec:** `docs/superpowers/specs/2026-11-04-config-editor-feedback-1-design.md`

## Global Constraints

- Branch `feat/config-editor-feedback-1`. The green gate before each commit (CLAUDE.md).
- `core/` never imports textual. Tests never touch a real WoW install.
- The rows must still fit at 120x30 and 80x30.

## Review Focus

1. A file with very long values (blob CVars) keeps every column visible: covered by FB2's test.
2. A category with CVars only in files not yet opened still shows them: covered by FB1's test.
3. The Add dropdown with thousands of CVars stays responsive (filter on input, cap the list shown): FB4.
4. A CVar not in `cvar_categories.json` (a new dump) still gets a group from the old rules: FB1.
5. Several ticked files in Add: the list excludes a CVar set in any of them: FB4.

---

### FB1: category filter fix and curated categories (CF4)

**Files:** `wowtools/core/kb.py`, `wowtools/kb/cvar_categories.json` (new), `wowtools/kb/README.md`,
`wowtools/tools/config_editor/review_screen.py` (or wherever the filter bug is), tests in `tests/test_kb.py` and
`tests/test_config_editor_app.py`.

- [ ] Reproduce the bug in a `TuiTestCase` with a temp KB holding sound, camera, nameplate, combat text and network
  CVars at machine, account and character level: pick each category with Show all known ticked, assert its CVars
  show. See it fail; fix the cause.
- [ ] `cvar_categories.json`: `{"comment": ..., "categories": {"<CVar name>": "<group>"}}` covering every name in
  every shipped `cvars/<flavor>.json`, groups from `CATEGORY_GROUPS` only. The data is supplied in the task prompt
  (curated by a separate pass from each CVar's name and help); write it as given, sorted, UTF-8, indent 1.
- [ ] `core.kb`: the curated group wins (case-insensitive name match); else today's `category_group` rules.
  Tests: a curated name gets its group; an unlisted name falls back; every shipped CVar name is listed; every value
  is a known group.

### FB2: columnar rows, truncation and colours (CF1-CF3)

**Files:** `wowtools/tools/config_editor/review_screen.py`, `wowtools/ui/theme.py`, tests, `docs/config-editor.md`.

- [ ] Tests: a file's rows render as aligned columns (name, value, default, state, category) with the widths of
  that file; a 300-character value shows cut to 24 with `…` and the state and category columns still appear; the
  state is `changed` / `default` / `unknown`; state and category carry their theme colours; at 80x30 the row
  still fits the pane.
- [ ] `ui/theme.py`: `CVAR_STATE_COLOURS` and `CVAR_CATEGORY_COLOURS` (one per `CATEGORY_GROUPS` entry).
- [ ] Guide: the browse screen section shows the new row layout.

### FB3: help panel layout (CF5)

**Files:** `wowtools/tools/config_editor/help.py` (or the panel's builder), tests, guide.

- [ ] Test: the panel's `Text` has the bold title, bold labels, coloured state and category, blank lines between
  sections and a bullet per source; the content matches today's (nothing lost).

### FB4: Set description and Add dropdown (CF6)

**Files:** `wowtools/tools/config_editor/popups.py`, `edit_actions.py`, tests, guide.

- [ ] Set: a description line under Default (note, else Blizzard help, else the fallback text). Test each case.
- [ ] Add: a filter input over an option list of the unset known CVars (level-matched, excluding names set in any
  ticked file), showing at most a capped number of matches (my call: 200) with a "… n more, keep typing" line;
  picking one shows its one-line description and fills the value with the default; typing an unknown name is still
  allowed. Tests: the list excludes set names (one file and several), narrowing works, picking prefills, an
  unknown name adds, Enter/Esc behave as in the other popups (EnterGuard).
- [ ] Guide: the Set and Add sections.
