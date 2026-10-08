# Faster tests: status ledger

Plan: `2026-10-09-faster-tests.md`. Spec: `../specs/2026-10-09-faster-tests-design.md`.
Branch: `build/faster-tests`. Resume at the first task not marked `done`. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| F0 | spec, plan, ledger | done | (this commit) | baseline: WSL ~100-120 s, native Windows 3.14 149 s (1925 tests, 79 skipped) |
| F1 | `--windows` and `--all` | todo | | |
| F2 | balanced shards | todo | | |
| F3 | shard count by measurement | todo | | |
| F4/F5 | two-job CI; when CI is checked | todo | | |
| FR | review, gate, push, CI once | todo | | |

## Decisions taken during the build
