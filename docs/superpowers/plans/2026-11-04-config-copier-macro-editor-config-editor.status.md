# Config Copier, Macro Editor, Config Editor and the launcher fix: status ledger

Plan: `2026-11-04-config-copier-macro-editor-config-editor.md`. Spec:
`../specs/2026-11-04-config-copier-macro-editor-config-editor-design.md`.
Branch: `feat/config-tools-and-launcher`. Resume at the first task not marked `done`. Push after each milestone;
never merge without the user's go-ahead.

Statuses: `todo`, `in-progress`, `done`, `waiting-user`, `blocked`.

| Task | Milestone | Title | Status | Commit | Notes |
|---|---|---|---|---|---|
| T0 | - | spec, plan, ledger | done | (this commit) | builder check folded into the spec |
| T1 | M1 | bootstrap log writer, launcher events, LN7 deviation | todo | | |
| T2 | M1 | wow-tools.cmd check, log, pause | todo | | |
| T3 | M1 | wow-tools.sh parity, README FAQ, CHANGELOG; push | todo | | |
| T4 | M2 | dump addon, refresh script; then user runs dumps | todo | | |
| T5 | M2 | install helpers (Forever, real characters) | todo | | |
| T6 | M2 | client-file write pipeline | todo | | |
| T7 | M2 | macro and CVar file parsers | todo | | |
| T8 | M2 | KB loader, state list, macro limits | todo | | |
| T9 | M2 | shared character tree; push | todo | | |
| T10 | M3 | copier planning and config merge | todo | | |
| T11 | M3 | copier run, undo, flow | todo | | |
| T12 | M3 | copier docs; push | todo | | |
| T13 | M4 | macro model, ops, paste rules | todo | | |
| T14 | M4 | macro reference, explainer, optimizer, templates | todo | | |
| T15 | M4 | macro browse screen, apply, undo | todo | | |
| T16 | M4 | macro edit screen and popups | todo | | |
| T17 | M4 | macro docs; push | todo | | |
| T18 | M5 | config model and edits | todo | | |
| T19 | M5 | recommendations data | todo | | |
| T20 | M5 | CVar base from dumps + wiki notes | todo | | needs the user's dumps (T4) |
| T21 | M5 | config editor screens, apply, undo | todo | | |
| T22 | M5 | config editor docs; push | todo | | |
| T23 | M6 | whole-branch review, gate, CI, ready to merge | todo | | |

## Decisions taken during the build

(append `T<n>a: …` lines here as calls are made)
