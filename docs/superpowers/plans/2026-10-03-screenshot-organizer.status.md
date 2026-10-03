# Build status: Screenshot Organizer

Checkpoint ledger for `2026-10-03-screenshot-organizer.md`. Work happens on branch `feat/screenshot-organizer`.

**To resume:** check out the branch, find the first row that isn't `done`, make sure
`python3 scripts/run_tests.py` passes, then carry on from that task.

| # | Task | Status | Commit | Notes |
|---|---|---|---|---|
| 0 | Spec + plan | done | 5e51887 | Spec approved in chat; event names get a `shots.` prefix (registry is global) |
| 1 | Package, events, naming, settings | done | 0335683 | Deviation: `scripts/gen_event_docs.py` now imports every `wowtools/tools/*` package and orders owners core, then `TOOLS`, then the rest sorted; the test suite imports `screenshots.events` before the tool is in `TOOLS`, so `test_docs` depended on import order. `docs/events.md` regenerated (screenshots section) |
| 2 | Fixture + planner | todo | | |
| 3 | Journal writer + organizer | todo | | |
| 4 | Undo | todo | | |
| M1 | Push (logic) | todo | | |
| 5 | FlavorScreen "All flavors" | todo | | |
| 6 | TUI + registration | todo | | |
| M2 | Push (UI) | todo | | |
| 7 | Docs | todo | | |
| R | Whole-branch review + fixes | todo | | |
| M3 | Push; ask for merge go-ahead | todo | | |
