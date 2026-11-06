# Config Copier feedback round 1: implementation plan

> **For agentic workers:** run task by task (implement test first, review, fix). Resume at the first ledger row not
> `done` (`2026-11-06-config-copier-feedback-1.status.md`). Each task is one checkpoint: its feature commit, its
> review, its fix commit, then the ledger row is `done`.

**Goal:** spec CP1-CP4: change the source from the review, a Diff button that stands out, a side-by-side diff with
an inline view on `v`.

**Spec:** `docs/superpowers/specs/2026-11-06-config-copier-feedback-1-design.md`

## Global Constraints

- Branch `feat/config-copier-feedback-1` (from master `6fe9da6`). Green gate before each commit
  (`python3 scripts/run_tests.py --all`, `ruff check --no-cache .`, `python3 scripts/gen_event_docs.py --check`);
  check the gate's exit status itself, never through a pipe.
- `core/` never imports textual; a tool never imports another tool; shared code lives once in `ui/` or `core/`.
- Button colours come only from `ui/theme.ACTION_COLOURS` (STD-8.2). Log only registered events (STD-6.1).
- 120x30 and 80x24 still fit (STD-7.23, STD-7.28).
- Tests never touch a real WoW install: `tests/fixtures.py` trees, `TuiTestCase`.

## Review Focus

1. Change source leaving stale state behind: old ticks, an old plan, the old source's scan still running, or a
   worker result landing on the new review.
2. Change source while a scan or a run is going on (refused while a run writes, as `action_leave`).
3. Side-by-side rows that drift apart: a `replace` run of unequal lengths, a gap, the `config-cache.wtf` whole file
   with its kept notes, empty files, a bytes-only difference, line numbers off by one.
4. The view preference and the width rule (spec CP4): an explicit `v` wins, the note shows only when the width
   rule chose inline, width read on open only.
5. The Diff reason line at 80x24 and 120x30, and while busy; the button's kind (`confirm`) and that no other
   `Diff` button in the suite has a different kind (`test_same_label_same_colour`).

---

### P1: Change source (CP1)

- [ ] `p` and a compact **Change source** `navigate` button by the Source line on the review. The review dismisses
  with a new choice (`"source"`) through `action_leave`; `CopierFlow` reopens `SourceScreen` with the same flavors
  and label. The new review is a fresh one (file boxes as any fresh review: all ticked; nothing in the tree ticked).
- [ ] Tests: `p` returns to the source picker of the same flavor choice (one flavor and All flavors), picking
  another source opens its review with nothing ticked; `p` refused while a run writes; Rescan still keeps the
  source; the key in the footer/hint and the help.
- [ ] Docs: user guide (keys table, left pane), internals, `help.py`.

### P2: Diff stands out (CP3)

- [ ] Diff button kind `navigate` → `confirm`. A dim reason line beside it while disabled
  (`highlight a replaced file to see its diff`), cut at its end with `…` to the room after the button, hidden under
  10 cells, empty while busy; refit on resize.
- [ ] Tests: the button's colour is the confirm colour; the line shows on a character row, is gone on a replaced
  pair, fits at 120x30 and 80x24 (cut or hidden), empty during a scan.
- [ ] Docs: user guide Diff section.

### P3: Side-by-side diff (CP4, rows and screen)

- [ ] `report.side_by_side_rows(plan)`: pure, from the same opcodes as `diff_rows` (same context and gaps, the
  config file whole with KEPT notes): rows of (left number, left text, left mark, right number, right text, right
  mark, note); a `replace` run paired line by line, the longer side's extra lines beside a blank.
- [ ] `DiffScreen` draws it by default: two aligned columns with line numbers, removed red left, added green right,
  long lines cut with `…` to the column; the head counts unchanged.
- [ ] Tests: unit tests of the rows (equal, delete, insert, replace of unequal lengths, gaps, config file kept
  notes, empty old or new file, bytes only); the screen at 120x30 shows both sides aligned.

### P4: Inline on `v`, the width rule, the session view (CP4)

- [ ] `v` (diff screen only, a `navigate` button and the hint line) switches side-by-side ↔ inline (today's
  unified view, unchanged). The session (the tool's flow, not a setting) holds the user's chosen view or none;
  with none, below 100 columns the diff opens inline with the head note `opened inline: the window is narrow`.
  Width read on open only.
- [ ] Tests: 120x30 opens side-by-side; 80x24 opens inline with the note; `v` switches both ways; the choice
  carries to the next diff at both sizes and the note is gone once `v` was pressed; a resize while open changes
  nothing.
- [ ] Docs: user guide Diff section and keys table, internals, `help.py`. Push the branch (milestone).

### P5: CHANGELOG, whole-branch review, push, CI

- [ ] One short CHANGELOG `[Unreleased]` change (the Config Copier is unreleased: fold into its Added line if it
  reads better; changelog style: major features only). A fresh whole-branch review (separate workflow), fixes,
  gate, push, CI once (STD-10.2). Merging into master needs the user's approval.
