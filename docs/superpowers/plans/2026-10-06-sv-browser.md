# Saved Variables Browser: plan

Spec: `../specs/2026-10-06-sv-browser-design.md` (decisions D1-D21). Ledger: `2026-10-06-sv-browser.status.md`.
Branch: `feat/sv-browser`. Resume at the first ledger row not marked `done`. Every task: tests first where it makes
sense, `python3 scripts/run_tests.py` green, `python3 scripts/gen_event_docs.py` when a registry changed, docs touched
by the task updated in the same commit, ledger row updated, one commit (or a few) per task. Push after each
milestone. Never merge, tag or release without the user's go-ahead. After the merge: delete every branch, stash and
worktree this run created.

## Global constraints

- Naming (D1): tool `sv-browser`, title "Saved Variables Browser", package `wowtools/tools/sv_browser`, section
  `[sv_browser]`, events `svb.*`, root `<backup_dir>/sv-browser` or `<WoW>/wow-tools/sv-browser` (`snapshots/`,
  `edited/`, marker), journals `<WoW>/wow-tools/sv-browser/journal/`.
- CLAUDE.md conventions apply (future import, import order, core never imports textual, no cross-tool imports, one
  definition of every shared helper, keys on buttons, help on `h`, `ConfirmScreen(kind=)`, retention global).
- Byte splices only; refuse writes while WoW runs; no per-file `resolve()`; never follow links.
- Ace3 Profile Manager behaviour and every Ace3 test assertion stay unchanged through M1 (patch targets and imports
  may move; record each in the ledger's Decisions).

## M0: setup
- **T0.1** Branch, spec, plan, ledger.

## M1: shared library (D19, D20)
- **T1.1** Move `luasv.py` to `wowtools/core/luasv.py` (git mv), switch Ace3 imports and tests
  (`tests/test_luasv.py`), pin single definitions. Add `parse_at`, `iter_scalars` (streaming, no Table objects),
  `encode_value`, `encode_key`, the `-- [n]` remove-span fix, `slots=True` dataclasses; unit tests for each.
- **T1.2** Move the SV file model and walk (`SvFile`, `sha256_of`, the SavedVariables file walk with a filter hook)
  into `core/svfiles.py`; `tool_root` helper into core (adopted by every tool that has its own `resolve_root`).
- **T1.3** Move the write pipeline into core: `core/sv_apply.py` (per-flavor apply with prepare/compile/verify hook,
  snapshot, originals zip, marker, atomic write + read-back, roll-back; multi-flavor driver; one `WowRunning`),
  `core/sv_journal.py` (edit journal), `core/sv_undo.py` (`undo_run`, `recover`), generic verify helpers and report
  rows; events parameterised by the tool's prefix. Ace3 becomes thin wrappers.
- **T1.4** UI: `popup_css`, `show_error`, a text prompt popup and the recovery popup into `wowtools/ui/dialogs.py`;
  apply/undo/recover worker plumbing into `wowtools/ui/review.py`; Ace3 review uses them. Structure tests updated.

## M2: SV Browser logic (D3-D12, D14-D19)
- **T2.1** Package skeleton: registry entry, `events.py`, `settings.py`, `help.py` stub, `app.py` flow stub,
  `build_sv_tree` fixture; menu tests green with five tools.
- **T2.2** `scanner.py` + `model.py`: file listing, lazy table loading via `parse_at`, typed keys, child cap.
- **T2.3** `search.py`: `SearchSpec`, matching rules D6-D9, streaming per-file search with pre-filter, replacement
  preview D10, result cap; streaming time/memory guard test.
- **T2.4** `ops.py` + compile/verify: staging (set/rename/delete + hits, overlap rules D5/D12), per-file splices,
  verify D19.
- **T2.5** Apply/undo/journal/report wiring on the core pipeline: dry run, apply, undo, recovery end-to-end on
  fixture trees (logic level, no UI).

## M3: screens (D2, D11-D13, D18)
- **T3.1** Flow + disclaimer popup + review screen Browse view (lazy tree, banner, pending summary, buttons, keys).
- **T3.2** Popups: Edit value, Rename key, Delete key; staging marks; unstage; leave-with-pending confirm.
- **T3.3** Search popup, search progress job, Results view, ticks, `v`.
- **T3.4** Apply / Dry run / Undo / recovery from the screen, result screen, help text; `test_look_and_feel.py` and
  `test_help.py` cover the tool (120x30 and 80x24).

## M4: finish
- **T4.1** Docs: `docs/sv-browser.md`, README, architecture, adding-a-tool, events.md, CHANGELOG, CLAUDE.md.
- **T4.2** Multi-lens review workflow (correctness, data safety, UX consistency, tests), fixes, push; ask for the
  merge go-ahead. After the merge: delete the branch (local and origin), stashes and worktrees created in this run.
