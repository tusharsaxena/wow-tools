# Feedback round 2: status ledger

Plan: `2026-10-08-feedback-round-2.md`. Spec: `../specs/2026-10-08-feedback-round-2-design.md`.
Branch: `fix/feedback-2026-10-07-b`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| R0 | spec, plan, ledger | done | (this commit) | written 2026-10-08 09:58 while round 1's workflow ran |
| L11 | `t` from any screen | todo | | |
| L14 | one "Run journal" row | todo | | |
| L15 | blacklist mark | todo | | |
| L16 | Interface Backup `backup/` folder | todo | | |
| LR5 | review L11-L16, push, CI | todo | | |
| S1 | merge docs/screenshots | todo | | branch pushed at 3b6da86 |
| L12 | docs and help in sync | todo | | |
| L13 | humanize | todo | | |
| LRF | whole-branch review, CI | todo | | |
| M | merge (user go-ahead), cleanup | todo | | |

## How to resume (any session)

1. `git -C <repo> status` on `fix/feedback-2026-10-07-b`. Round 1 first: open
   `2026-10-07-feedback-bars-leftovers.status.md`; resume at its first row not `done` (L8, L9, L10, LR4 were in
   flight at 09:58 on 2026-10-08).
   - Uncommitted changes in the tree belong to the round-1 task that was running (its row says `todo`): finish that
     task (test first, green gate, commit, ledger row), or `git stash` them and redo the task.
   - The round-1 workflow, if the same Claude session is still alive: `Workflow({scriptPath:
     "~/.claude/projects/-mnt-d-Profile-Users-Tushar-Documents-GIT-wow-tools/<session>/workflows/scripts/feedback-l7-l10-wf_d3a782a9-242.js",
     resumeFromRunId: "wf_d3a782a9-242"})` replays finished agents from cache. In a new session, run the remaining
     tasks from the spec instead.
2. Then this ledger, first row not `done`. Each task: tests first, green gate (`python3 scripts/run_tests.py`,
   `ruff check --no-cache .`, `python3 scripts/gen_event_docs.py --check`), one commit, ledger row, then review.
   Push at LR5 and LRF and wait for CI (`gh run watch <id> --exit-status`).
3. Never stage `docs/assets/new/` (the user's screenshot originals); stage files explicitly.
4. Never merge without the user's go-ahead (M).

## Decisions taken during the build
