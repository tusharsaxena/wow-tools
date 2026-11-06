# Config Copier feedback round 1: status

Branch `feat/config-copier-feedback-1`. Plan `2026-11-06-config-copier-feedback-1.md`. Resume at the first row not
`done`.

## Resume here

- P1 done (Change source on `p`). Next: **P2** (Diff stands out: confirm kind, reason line, CP3).
- Spec, plan and ledger committed. Build runs as a workflow: per task implement (test first), review, fix; each
  task's row goes `done` with its commits. Push after P4; P5 is the whole-branch review, push and CI. Merge into
  master needs the user's approval.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| P1 | Change source on `p` (CP1) | done | bae360b, (this commit) | 6 new tests (`ChangeSourceTest`); gate green: 2432 tests on WSL and Windows, 0 failures (WSL 10 skipped, Windows 86), ruff clean, events doc in step. Review fixes: the fresh-review test now picks Dænerys (Bob stays the ticked target) and checks `files` too, so carried-over ticks fail it (checked against a shared-ticks mutant); `#source-row` margin dropped (the Files heading's own margin keeps one blank row, one row back at 80x24); gate green again, same counts |
| P2 | Diff stands out: confirm kind, reason line (CP3) | todo | | |
| P3 | Side-by-side diff rows and screen (CP4) | todo | | |
| P4 | Inline on `v`, width rule, session view (CP4) | todo | | |
| P5 | CHANGELOG, whole-branch review, push, CI | todo | | |

## Decisions taken during the build

- P0a (builder check, my call): the review dismisses with `"source"` and `CopierFlow` reopens `SourceScreen` with
  the same flavors and label; the new review's file boxes start as any fresh review's.
- P0b (builder check, my call): an explicit `v` wins over the 100-column rule; the width is read on open only; the
  Diff reason line is cut to the room after the button and hidden under 10 cells (spec CP3, CP4).
- P1a (builder, my call): **Change source (p)** is a compact `navigate` button on its own row right under the Source
  line (`#source-row`, a `ButtonRow`), not beside it: the source text keeps the pane's whole width (a long
  `Flavor › ACCOUNT › Realm/Name` wraps at 80 columns), and the button never moves.
- P1b (builder, my call): the button is never disabled, as `f` and `t` are not: `action_change_source` goes through
  `action_leave("source")`, which refuses silently while a run writes (only `t` says why, L11). During a scan it
  leaves at once; the scan's late result lands on the old review object (gone from the stack), never the new one.
- P1c (builder, my call): `CopierFlow._review` wraps the shared `_after_review` in a closure that turns `"source"`
  into `_pick_source(flavors, label)`; `ToolFlow` is unchanged (no other tool has a source to change).
- P1r (review fix, my call): `#source-row` loses its `margin-bottom: 1`; the `.section` heading under it already has
  `margin-top: 1`, so the gap was two rows. One row comes back for the left pane at 80x24 (it still scrolls there,
  as before this task; STD-7.23 makes 80x24 a floor, not a fit).
