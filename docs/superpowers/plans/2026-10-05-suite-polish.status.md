# Suite polish: status ledger

Plan: `2026-10-05-suite-polish.md`. Spec: `../specs/2026-10-05-suite-polish-design.md`.
Branch: `feat/suite-polish`. Resume at the first task not marked `done`. Update this file and commit it after every
task; push after every milestone. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| T0.1 | branch, spec, plan, ledger | done | | |
| T0.2 | dead code, core-no-textual test | done | 7f7a279 | InstallError, SNAPSHOT_NAME + `import re`, ConfirmScreen re-export gone; pinned; core-no-textual AST test. 1056 tests OK (2 skipped) |
| T0.3 | version 0.1.0, CHANGELOG.md | done | 76cc51d | `__version__` 0.1.0, README badge, CHANGELOG.md with the 0.1.0 entry, README Version History is a pointer; test pins badge + changelog heading. 1058 tests OK (2 skipped) |
| T1.1 | core helpers | todo | | |
| T1.2 | review-screen base in ui | todo | | |
| T1.3 | result/choice/settings/flow helpers | todo | | |
| T1.4 | shared-library policy docs | todo | | |
| T2.1 | action-kind colours | todo | | |
| T2.2 | confirm default Yes + safeguards | todo | | |
| T3.1 | BrandBar fix, Ace3 u | todo | | |
| T3.2 | version under banner, terms, menu tests | todo | | |
| T3.3 | changelog parser + screen + release check | todo | | |
| T4.1 | shared tree filter | todo | | |
| T4.2 | filter in every tree screen | todo | | |
| T5.1 | parallelism setting + runner + thread safety | todo | | |
| T5.2 | fixed-size progress popup | todo | | |
| T5.3 | apply parallel runs | todo | | |
| T6.1 | docs sync | todo | | |
| T6.2 | review, fixes, push | todo | | |

## Decisions taken during the build

- **T0.2** The ConfirmScreen re-export is pinned as `"ConfirmScreen" not in review_screen.__all__`, not `not hasattr`: review_screen still imports ConfirmScreen from `ui.dialogs` for its own confirms, so the name stays a module attribute. Nothing outside frozen historical plans imported it from there. `ruff check` panics on a stale `.ruff_cache` in this checkout; `ruff check --no-cache .` is clean.
- **T0.2** review: 2 findings, 2 fixed, 0 rejected: core-no-textual test now also flags `wowtools.ui`/`wowtools.tools` and relative imports, plus a fresh-interpreter check that importing every core module loads no textual or wowtools.ui (1057 tests OK); stale "still importable from here for one release" ConfirmScreen line dropped from docs/architecture.md.
- **T0.3** The 0.1.0 entry has only an `### Added` section (grouped per tool, plus "The app"): nothing was released before it, so the old "Unreleased" row's changes (global retention, `x`/`c`, Clean on `w`, one row per checkbox) are written as features of 0.1.0, not "Changed". The `"1.0.0"` strings left in `tests/test_ace_*.py` are arbitrary `suite_version` journal fixture data, not version pins, so they stay. The new `test_version_badge_and_changelog_match_the_version` (test_docs.py) is a regex stand-in for the "`__version__` has an entry" pin; T3.3 can move it onto `core/changelog.py`. The stale README Tests badge (1053) is left for T6.1 docs sync.
