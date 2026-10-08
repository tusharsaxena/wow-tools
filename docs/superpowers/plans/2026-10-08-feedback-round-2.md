# Feedback round 2: plan

Spec: `../specs/2026-10-08-feedback-round-2-design.md`. Ledger: `2026-10-08-feedback-round-2.status.md`.
Runs after round 1's L8-L10 and LR4 (ledger `2026-10-07-feedback-bars-leftovers.status.md`) are done.

| Task | What |
|---|---|
| R0 | this spec, plan and ledger (committed once round 1's LR4 is pushed) |
| L11 | `t` from any screen |
| L14 | WTF Cleaner result: one "Run journal" row |
| L15 | blacklist mark `⊘` |
| L16 | Interface Backup `backup/` folder + one-time move |
| LR5 | review of L11-L16, green gate, push, CI |
| S1 | merge `docs/screenshots` (pushed, worktree `<scratchpad>/wt-shots`) into the branch; resolve doc conflicts |
| L12 | docs and help in sync with the code |
| L13 | humanize user-facing text and help |
| LRF | whole-branch review, green gate, push, CI green on all 4 jobs |
| M | ask the user for the merge go-ahead; after it: merge to master, push, CI on master, delete `fix/feedback-2026-10-07-b` and `docs/screenshots` (local + origin), remove the `wt-shots` worktree, delete `docs/assets/new/` (the user's originals, all copied into docs/assets/screenshots) only with the user's OK |
