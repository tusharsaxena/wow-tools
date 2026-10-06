# Saved Variables Browser — status ledger

Plan: `2026-10-06-sv-browser.md`. Spec: `../specs/2026-10-06-sv-browser-design.md`.
Branch: `feat/sv-browser`. Resume at the first task not marked `done`. Update this file and commit it after every
task; push after each milestone. Never merge without the user's go-ahead. At the end of the run, after the merge,
delete every branch, stash and worktree this run created.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| T0.1 | branch, spec, plan, ledger | done | (this commit) | user answers 2026-10-06: per-search key toggles, whole/contains value match, values+rename+delete, scope filters + ticked results; same backup/journal/undo set as every tool; name `sv-browser`, display "Saved Variables Browser" |
| T1.1 | luasv to core + parser surface | done | (this commit) | `luasv.py` git-mv'd to `wowtools/core/` (Ace3 modules + tests switched, `tests/test_ace_luasv.py` -> `tests/test_luasv.py`), added `parse_at`, streaming `iter_scalars`, `encode_value`/`encode_key`/`key_id`, the `-- [n]` remove-span fix and slotted dataclasses; no Ace3 assertion changed; full suite 1357 OK (2 skipped), +23 tests |
| T1.2 | SvFile/walk/tool_root to core | done | (this commit) | `SvFile`, `sha256_of`, `OWNER_ACCOUNT_WIDE`, `candidate_files`, `under_link` and a generic `walk_sv_files` (filter hook `is_sv_file`/`is_addon_sv_file`) now in `core/svfiles.py`, Ace3 scanner/editor/ops/review/tree_view import them from core, `core.journal.tool_root` adopted by Ace3 `resolve_root` and Interface Backup `resolve_backup_root` (WTF Cleaner kept), structure pin added; no Ace3 assertion changed; full suite 1365 OK (2 skipped), +8 tests |
| T1.3 | write pipeline, journal, undo to core | todo | | |
| T1.4 | shared UI helpers | todo | | |
| M1 | push milestone 1 | todo | | |
| T2.1 | package skeleton, registry, fixture | todo | | |
| T2.2 | scanner + lazy model | todo | | |
| T2.3 | search | todo | | |
| T2.4 | staging, compile, verify | todo | | |
| T2.5 | apply/undo/recovery wiring | todo | | |
| M2 | push milestone 2 | todo | | |
| T3.1 | flow, disclaimer, Browse view | todo | | |
| T3.2 | edit/rename/delete popups, staging UI | todo | | |
| T3.3 | search popup, Results view | todo | | |
| T3.4 | apply/dry run/undo/recovery UI, result, help, look-and-feel | todo | | |
| M3 | push milestone 3 | todo | | |
| T4.1 | docs | todo | | |
| T4.2 | review, fixes, push, ask for merge | todo | | |

## Decisions taken during the build
- **T1.1** `iter_scalars(data, descend)` yields `(path, key, key_span, Scalar)` where `path` is the *containing*
  table's path (the same tuple `descend` gets, raw Python-typed keys); a top-level `Name = scalar` yields `path=()`,
  key = the name, key span = the name's bytes; positional entries have key = index and `key_span=None`. It walks with
  an explicit stack (no recursion, no Table/Field objects): ~2x faster than `parse` (16.7 MB, 900k scalars: 4.4 s vs
  9.5 s on WSL).
- **T1.1** `_Parser` refactored so `table()` and the stream share `scalar()`, `key()` and `separator()`; a table used
  as a key (`[{}] = 1`) still raises "bad table key" at the `[`.
- **T1.1** `parse_at(data, start, path=(), descend=all)` skips blanks/comments before `start`; `descend` is asked
  about `path` first (pass `lambda p: len(p) <= len(path)` for one level).
- **T1.1** `key_id(k)` = `(type name, value)`, except an integral float folds to `("int", n)` (Lua 5.1 folds `[1.0]`
  into `[1]`); `Table.get` is unchanged (Ace3 behaviour).
- **T1.1** `encode_value` refuses nil (`ValueError`: a nil set is a delete) and non-scalars (`TypeError`);
  `encode_key` = `[` + `encode_value` + `]`, so it refuses nil/inf/nan the same way.
- **T1.1** Remove-span fix: `_LINE_REST` takes an optional trailing line comment, never one starting a long comment
  (`--[[`/`--[=[`), which could run past the line.
- **T1.1** `slots=True` on `Scalar`, `Opaque`, `Field`, `Table`, `Assignment`, `Chunk` (Ace3 sets no extra
  attributes on them); `RawNumber` stays frozen without slots (frozen+slots pickling bug on early 3.10).
- **T1.1** `tests/test_structure.py::test_saved_variables_reader_lives_in_core` pins the one `luasv.py` and every
  parser function/class to core; `docs/architecture.md` paths updated now (the rest of the docs is T4.1).
- **T1.2** `walk_sv_files(flavor, *, account, accept, on_error, on_account, on_link)` is a generator of
  `(Account, Character | None, path)` (the `Account` object, not just its name, so a caller has `.name` and `.path`);
  `on_account(acct, characters)` fires before an account's files, so Ace3 still gets an `AccountScan` (with its
  character keys) for an account with no files; the "no WTF/Account folder" error stays in Ace3's `scan_flavor`.
- **T1.2** Filters: `is_sv_file` (exactly `.lua` with a name before it; never `.lua.bak`/`.old`; the default, for SV
  Browser) and `is_addon_sv_file` (also not `Blizzard_*`; Ace3). `candidate_files(sv_dir, accept)` never takes a link
  or a folder.
- **T1.2** The owner constant is `svfiles.OWNER_ACCOUNT_WIDE = "Account-wide"`, not `ACCOUNT_WIDE`, because
  `core/install.ACCOUNT_WIDE = "account-wide"` (WTF Cleaner) already exists with another value. Ace3's
  `scanner.SvFile`/`scanner.sha256_of` stay importable (the scanner imports them), so the Ace3 tests that use
  `scanner.SvFile` / `scanner.sha256_of` are untouched; Ace3 production modules import them from core.
- **T1.2** `tool_root(backup_dir, wow_path, tool)` lives in `core/journal.py` next to `TOOLS_SUBDIR` and
  `journal_dir` (`core/paths.py` would import journal, which imports paths: a cycle). Ace3 `resolve_root` and
  Interface Backup `resolve_backup_root` are now one-line wrappers (callers and tests unchanged). The WTF Cleaner's
  `resolve_backup_dir` is left alone: a set `backup_dir` is used as-is, with no `wtf-cleaner` subfolder, so it is not
  the same behaviour. `test_saved_variables_files_and_tool_root_live_in_core` pins the definitions and that only
  `wtf_cleaner/settings.py` among tools still uses `TOOLS_SUBDIR`.
- **T1.2** `ruff check .` panicked on a stale cache (`wrong package cache for file`); `ruff check --no-cache .` passes.
