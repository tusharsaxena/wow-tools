# Suite polish: plan

Spec: `../specs/2026-10-05-suite-polish-design.md` (decisions D1-D15). Ledger: `2026-10-05-suite-polish.status.md`.
Branch: `feat/suite-polish`. Resume at the first ledger row not marked `done`. Every task: tests first where it
makes sense, `python3 scripts/run_tests.py` green, `python3 scripts/gen_event_docs.py` when a registry changed,
docs touched by the task updated in the same commit, ledger row updated, one commit (or a few) per task. Push after
each milestone. Never merge, tag or release without the user's go-ahead.

## M0: setup and quick fixes
- **T0.1** Branch, spec, plan, ledger, analysis copied into the spec folder.
- **T0.2** Dead code (D14); "core never imports textual" structure test.
- **T0.3** Version 0.1.0 (D1): `wowtools/__init__.py`, README badge; `CHANGELOG.md` with the 0.1.0 entry (merge the
  README 1.0.0 and Unreleased rows; this run's features are added to it as they land); README Version History
  section replaced by a link.

## M1: shared library (D9)
- **T1.1** UI-free helpers into `core/`: `plural`, `flavor_name`, size formatting, `ThrottledProgress` (made
  thread-safe), journal helpers (prune/latest with event name, `resolve_journal_dir`), `validate_backup_dir`,
  run-marker helpers, undo result base + safe `destination()`. Single-definition pins in `test_structure.py`.
- **T1.2** Textual review-screen base in `ui/`: `ReviewTree`, toggle (with Input passthrough), filter-ready
  select-all/none hooks over a tick-model adapter (ticked vs unchecked polarity), leave actions, preflight worker,
  debounced rebuild, `BUTTON_ACTIONS` dispatch, scan-worker skeleton where it pays.
- **T1.3** Generic result screen, recovery/choice dialog, settings-screen base, `ToolFlow` helpers.
- **T1.4** Policy docs: CLAUDE.md convention line, `docs/adding-a-tool.md` step 1, `docs/architecture.md` Layers +
  module tables.

## M2: buttons and confirms (D12, D13)
- **T2.1** Action kinds: theme variables, `action_button(kind=...)`, CSS; every button in every tool mapped.
- **T2.2** `ConfirmScreen` default Yes + destructive colour + Enter debounce; call sites and tests; docs.

## M3: tool menu (D2-D6, D15)
- **T3.1** BrandBar visibility fix (shared), Ace3 `u` decision.
- **T3.2** Version under the banner; Terms text; menu look-and-feel tests (BASE and TINY).
- **T3.3** `core/changelog.py` parser + tests; `ChangelogScreen` + `c`; `build_release.py` check;
  `docs/releasing.md` step; README.

## M4: tree filter (D7, D8)
- **T4.1** Shared `ui/tree_filter.py` (filter text, match on model data, `/` binding, Input passthrough, Esc rules,
  hidden-selected count).
- **T4.2** Wire into WTF, Shots, IB review, IB Restore, Ace3 review (replace its own search), Blacklist. Summary and
  confirm texts. Tests per tool. Docs (README keys, guides, architecture).

## M5: parallel runs and progress popup (D10, D11)
- **T5.1** `[general] parallelism` (Config, setup screen, docs) + `core/parallel.py` runner + thread-safety
  (journal writer, progress, logging) + events.
- **T5.2** Fixed-size multi-row `ProgressScreen` (shared) + tests (width and height, BASE and TINY).
- **T5.3** Apply: IB back up all, read-only per-flavor scans, picker counts, Ace3 undo snapshots.

## M6: finish
- **T6.1** Docs sync (README keys/terms/changelog, guides, architecture, CLAUDE.md incl. test-suite time), events
  docs, CHANGELOG 0.1.0 entry complete.
- **T6.2** Multi-lens review workflow, fixes, push; ask for merge go-ahead. After merge: delete the branch (local and
  origin), stashes and worktrees created in this run.
