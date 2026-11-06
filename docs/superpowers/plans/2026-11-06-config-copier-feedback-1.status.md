# Config Copier feedback round 1: status

Branch `feat/config-copier-feedback-1`. Plan `2026-11-06-config-copier-feedback-1.md`. Resume at the first row not
`done`.

## Resume here

- Spec, plan and ledger committed. Build runs as a workflow: per task implement (test first), review, fix; each
  task's row goes `done` with its commits. Push after P4; P5 is the whole-branch review, push and CI. Merge into
  master needs the user's approval.

| Task | What | Status | Commit | Notes |
|---|---|---|---|---|
| P1 | Change source on `p` (CP1) | todo | | |
| P2 | Diff stands out: confirm kind, reason line (CP3) | todo | | |
| P3 | Side-by-side diff rows and screen (CP4) | todo | | |
| P4 | Inline on `v`, width rule, session view (CP4) | todo | | |
| P5 | CHANGELOG, whole-branch review, push, CI | todo | | |

## Decisions taken during the build

- P0a (builder check, my call): the review dismisses with `"source"` and `CopierFlow` reopens `SourceScreen` with
  the same flavors and label; the new review's file boxes start as any fresh review's.
- P0b (builder check, my call): an explicit `v` wins over the 100-column rule; the width is read on open only; the
  Diff reason line is cut to the room after the button and hidden under 10 cells (spec CP3, CP4).
