# Config Copier, Macro Editor, Config Editor and the launcher fix: status ledger

Plan: `2026-11-04-config-copier-macro-editor-config-editor.md`. Spec:
`../specs/2026-11-04-config-copier-macro-editor-config-editor-design.md`.
Branch: `feat/config-tools-and-launcher`. Resume at the first task not marked `done`. Push after each milestone;
never merge without the user's go-ahead.

Statuses: `todo`, `in-progress`, `done`, `waiting-user`, `blocked`.

| Task | Milestone | Title | Status | Commit | Notes |
|---|---|---|---|---|---|
| T0 | - | spec, plan, ledger | done | (this commit) | builder check folded into the spec |
| T1 | M1 | bootstrap log writer, launcher events, LN7 deviation | done | (this commit) | 15 new tests (8 test_bootstrap, 7 test_suite incl. MainTest); gate green: WSL 1987 OK (2 skipped), Windows 1987 OK (78 skipped), ruff clean, events.md current. Review fixes (T1r): bootstrap.py parses on 3.7 again (no walrus; ast test), and the 2000-line cap (MAX_KEEP_LINES) now applies after the date trim too; gate green: WSL/Windows 1989 OK |
| T2 | M1 | wow-tools.cmd check, log, pause | done | (this commit) | 8 new tests in test_launcher.py (2 structure tests on every platform, 6 cmd.exe tests Windows-only); gate green: WSL 1997 OK (8 skipped), Windows 1997 OK (78 skipped), ruff clean, events.md current. Manual run from a folder named `a!b & c` logged and paused correctly; review fix: test_old_python_message covers the LN2 too-old branch (fake python.bat on PATH reports 3.8, exits 3); gate after it green: WSL OK, Windows 1998 OK (78 skipped), ruff clean, events.md current (one earlier --all run had a single Windows error that did not recur on the rerun and was not captured) |
| T3 | M1 | wow-tools.sh parity, README FAQ, CHANGELOG; push | done | (this commit) | 9 new tests in test_launcher.py (3 structure tests on every platform, 6 `sh` tests POSIX-only); gate green: WSL 2007 OK (9 skipped), Windows 2007 OK (84 skipped), ruff clean, events.md current. Push left to the orchestrator. T3 review fix (minor, docs only): the FAQ row's log path now reads `logs/suite/launcher.log` with the Windows form beside it, and "a text editor (Notepad on Windows)"; no test needed; gate green again: WSL 2007 OK (9 skipped), Windows 2007 OK (84 skipped), ruff clean, events.md current |
| T4 | M2 | dump addon, refresh script; then user runs dumps | done | (this commit) | 11 new tests in test_refresh_kb.py (10 refresh_kb, 1 addon shape); the Lua (112 lines) also smoke-run under lua5.1 with stubbed APIs and fed through refresh_kb.py end to end (scratchpad only); gate green: WSL 2018 OK (9 skipped), Windows 2018 OK (84 skipped), ruff clean, events.md current. Waiting on the user: install the addon and `/kbdump` once per flavor (scripts/kb_dump/README.md); T5 onward does not wait, T20 needs the dumps. Review fix (fix: T4 review fixes): a dump string that is not valid UTF-8 now skips its flavor with a message instead of crashing the run (T4h); +1 test, gate green: WSL 2019 OK (9 skipped), Windows 2019 OK (84 skipped), ruff clean, events.md current |
| T5 | M2 | install helpers (Forever, real characters) | done | (this commit) | 5 new tests in test_install.py (RealCharactersTest: the plan's 4 plus on_error passed through); gate green: WSL 2024 OK (9 skipped), Windows 2024 OK (84 skipped), ruff clean, events.md current. Review fix (fix: T5 review fixes): test_real_characters_passes_on_error checked nothing (a missing account folder never reaches on_error); it now makes one realm's iterdir raise PermissionError and asserts on_error gets that realm and the other realm's character still lists (fails if real_characters drops on_error); gate green: WSL 2024 OK (9 skipped), Windows 2024 OK (84 skipped; one first-run WinError 10055 socket-buffer error, environmental, clean on rerun), ruff clean, events.md current |
| T6 | M2 | client-file write pipeline | done | (this commit) | 28 new tests: 24 in test_client_apply.py (the plan's 9 plus created-only run, stale-skip-rest, appears-before-write, link guard, guarded path stops the run, client_destination, roll-back removes a created file, undo of a gone created file, undo while WoW runs, journal entry outside the names, recovery leaves a rewritten created file, finished-run recovery, no cache.md5/.old, client_events), 3 in test_fsutil.py (atomic_create_bytes), 1 in test_backup.py (allow_empty); test_structure pins the new pieces in core. Existing Ace3 / SV Browser / pipeline tests unchanged and green. Gate green: WSL 2052 OK (9 skipped), Windows 2052 OK (85 skipped; the first --all run had one WinError 10055 socket-buffer error, environmental as in T5, clean on the --windows rerun), ruff clean, events.md current. Review fix (fix: T6 review fixes): a created file roll-back could not remove now gets its own detail and message (delete it / Undo / recovery), never the unzip advice; +1 test, crash-marker test asserts it; gate green again: WSL 2053 OK, Windows 2053 OK (one WinError 10055 on --all, clean on the --windows rerun), ruff clean, events.md current |
| T7 | M2 | macro and CVar file parsers | done | 2e9243e, review fixes (this commit) | 27 new tests: 14 in test_macrofile.py (the plan's 6 plus empty file, quoted name and lowercase id, limits, empty-body add, bad changes, invalid UTF-8, other-prefix ids, id overflow), 13 in test_cvarfile.py (the plan's 3 plus spans, other lines kept, duplicates, empty file, spelling and line ending kept, every duplicate set/removed, unterminated last line, removing a missing CVar, invalid UTF-8, bad changes); fixtures gain macro_file_bytes and cvar_file_bytes; architecture.md Core modules rows for both. Gate green: WSL 2080 OK (9 skipped), Windows 2080 OK (85 skipped; the first --all run had one Windows failure in the test runner's own shard-balancing test, not in this change, clean on the --windows rerun and a second --all), ruff clean, events.md current. No CHANGELOG line: nothing a user sees yet. Review fixes (T7r1): a replace whose name, icon and body equal the parsed macro keeps the block's bytes (the one-blank-line block), pinned by test_unchanged_replace_keeps_the_block_bytes |
| T8 | M2 | KB loader, state list, macro limits | done | (this commit) | 17 new tests in test_kb.py (the plan's 4 plus case-insensitive state match, exceptions, unreadable state list, the refresh_kb schema, odd entries, unsafe flavor names, caching, the X8 category groups, unknown-flavor limits, every shipped limit sourced, bad limits, the KB folder and README, kb.unreadable registered); architecture.md Core modules row for `kb`; events.md regenerated. Gate green: WSL 2098 OK (9 skipped), Windows 2098 OK (85 skipped; the first --all run's Windows half reported FAILED with 0 failures and 0 errors after one shard hung 600 s on the executor join in test_ui_base, environmental, clean on the --windows rerun in 81 s), ruff clean, events.md current. No CHANGELOG line: nothing a user sees yet Review fix (fix: T8 review fixes): `highestUnlocked*` added to the state patterns, `showTutorials` made an exception (T8g); T20's row now carries CC5's per-pattern dump check; +1 test, gate green: WSL 2099 OK (9 skipped), Windows 2099 OK (85 skipped), ruff clean, events.md current |
| T9 | M2 | shared character tree; push | done | (this commit) | 7 new tests in test_character_tree.py (the plan's 4 plus account_extra, shown=, populating under a flavor node without marks), on a toy ReviewBase screen over the new `build_character_tree` fixture; architecture.md UI row for `character_tree`. Gate green: WSL 2106 OK (9 skipped), Windows 2106 OK (85 skipped), ruff clean, events.md current. No CHANGELOG line: nothing a user sees yet. Push (M2) left to the orchestrator. Review fixes (T9c, T9d): `character_extra` hook, hooks' keys fold into parents, 5 more tests (12 in all) incl. a TreeFilter screen; gate green: WSL 2111 OK (9 skipped), Windows 2111 OK (85 skipped), ruff clean, events.md current |
| T10 | M3 | copier planning and config merge | done | (this commit) | 24 new tests: 13 in test_config_copier_planner.py (the plan's 5 plus COPY_FILES order, unknown-layout macro warning, no warning when unchanged, config pair is the merge, config unchanged when only state differs, unreadable files and their events, bad arguments, nothing written), 11 in test_config_copier_merge.py (the plan's 4 plus line order and bytes, empty target, empty source, a duplicated line, LF and other lines kept, case-insensitive names, source duplicate); `copier.*` events registered, events.md regenerated. Gate green: WSL 2135 OK (9 skipped), Windows 2135 OK (85 skipped), ruff clean, events.md current. No CHANGELOG line: nothing a user sees yet (the tool is registered in T11). Review fix (f64164e review): core.cvarfile `_NAME` compiled with re.ASCII so `apply_cvar_changes` accepts every name `parse_cvars` reads (a source name holding U+00A0 made `merge_config`, and so `plan_copy`, raise); 2 new tests (cvarfile, merge) and an ASCII tab case in the bad-changes test. Gate green: WSL 2137 OK (9 skipped), Windows 2137 OK (85 skipped), ruff clean, events.md current |
| T11 | M3 | copier run, undo, flow | done | (this commit) | 26 new tests: 16 in test_config_copier_run.py (the plan's 4 plus names, non-ASCII round trip, unknown macro layout (Review Focus 1), unchanged/no-source never written, change lines, WoW running, changed since review, recovery, leave, 3 report tests), 10 TUI in test_config_copier_app.py (the plan's 4 plus registry, unticked file, dry run then undo, WoW running, pair statuses, one flavor at 80x24); the copier added to every meta-test table (look and feel, help, quit, tool menu, toasts, warnings) and to test_structure; first guide, internals doc, README/CLAUDE.md/architecture/releasing rows, RELEASE_SHIPS and CHANGELOG line (T11j); events.md regenerated. Gate: ruff clean, events.md current, Windows 2163 OK (85 skipped); WSL 2163 OK except the two test_release_contents git-archive checks, which read HEAD and so fail until the new guide is committed; re-run green after the commit. Review fix (3d33355 review): the review carries the shared RiskBanner (T11r1: STD-7.10's list, test_structure, DESTRUCTIVE_REVIEWS, test_docs, guide and internals updated); the diff names a line-ending or non-text-only change instead of "The files are the same." (T11r2, `report.bytes_only`); 2 new tests (run: bytes_only cases, app: the diff screen line). Gate green: WSL 2165 OK (9 skipped), Windows 2165 OK (85 skipped), ruff clean, events.md current |
| T12 | M3 | copier docs; push | done | (this commit) | 1 new test in test_docs.py (`test_config_copier_guide_readme_and_notes`: guide V1/V2 section, the five files, merge, macro warning, safety net, keys; README rows and FAQ; CLAUDE.md, CHANGELOG, architecture, internals sections, releasing); guide gains Why a copy sticks, What the tool never touches, The safety net (backups, interrupted copy), WoW running, more FAQ and troubleshooting rows; internals doc gains V1/V2, the merge, Safety, Events, Tests; README names the copier in its Dry run, Undo, journals and FAQ lines and shows its review; `review.png` re-rendered with the banner (T12b). Gate green: WSL 2166 OK (9 skipped), Windows 2166 OK (85 skipped), ruff clean, events.md current. Push (M3) left to the orchestrator. Review fix (fix: T12 review fixes): the internals doc's CC5 bullets and the guide's no-target sentence now say a target with no config-cache.wtf gets the source's file minus its state lines (non-SET lines kept), as merge.py does; 1 new test (`test_merge_without_target_file_keeps_the_sources_other_lines`). Gate green: WSL 2167 OK (9 skipped), Windows 2167 OK (85 skipped), ruff clean, events.md current |
| T13 | M4 | macro model, ops, paste rules | done | d0c5c50, review fixes (this commit) | 19 new tests in test_macro_editor_ops.py (the plan's nine plus scan, read-only and unreadable sets, empty-set create, skip, edit back to the original, staged add edit/delete, delete, non-UTF-8 bytes, count/clear); `macro.*` events registered; gate green: WSL 2186 OK (9 skipped), Windows 2186 OK (85 skipped), ruff clean, events.md current. Review fixes: stage_edit keeps a macro's own name when it is unchanged and cuts only a new one, so Replace text on a file name over 16 characters changes only the body (ME13); a paste clash compares cut names on both sides, and rename_for_clash gets the cut names; 2 new tests; gate green: WSL 2188 OK (9 skipped), Windows 2188 OK (85 skipped), ruff clean, events.md current |
| T14 | M4 | macro reference, explainer, optimizer, templates | done | (this commit) | 28 new tests: 18 in test_macro_editor_syntax.py (the plan's seven syntax ones plus spaces and target=, chat text and comments, token_at, more explain blocks, a conditional the flavor lacks, command and conditional suggestions, reference aliases and builder lists, unsourced entries dropped, a bad reference file, fill_template's checks, unsourced templates dropped), 10 in test_macro_editor_optimizer.py (one per rule incl. cast_to_use never applied, the rules data, only KB rules applied, kept #showtooltip cases, rules together, spell text untouched); test_kb's README needles gain the three files; architecture.md `kb` row and wowtools/kb/README.md describe the new files and loaders. Gate green: WSL 2216 OK (9 skipped), Windows 2216 OK (85 skipped), ruff clean, events.md current. No CHANGELOG line: nothing a user sees yet (the tool is registered in T15). Review fixes (T14r): duplicate_conditions keeps unit segments, `no` suggestions read their explain_no; test_duplicate_units_are_kept and a nodead help assertion added; gate green: 2217 OK on WSL and Windows, ruff clean, events.md current |
| T15 | M4 | macro browse screen, apply, undo | done | (this commit) | 24 new tests: 11 in test_macro_editor_run.py (the run across files then Undo, across flavors, dry run, WoW running, changed since the scan, unknown layout never written, paste preview clashes/choices/refusals, cross-flavor warnings, texts, confirm and result rows), 11 TUI in test_macro_editor_app.py (the plan's seven plus registry, leaving asks, WoW running, 80x24), 2 in test_client_apply.py (several flavors in one run and one Undo, a flavor's guard refuses another's file); the editor added to every meta-test table (look and feel incl. DESTRUCTIVE_REVIEWS, help, quit incl. STAGING_TOOLS, tool menu, toasts, warnings) and to test_structure (journals/undo, recovery, action mixins, banner, 9 tree screens); first guide, internals doc, README/CLAUDE.md/architecture/releasing rows, RELEASE_SHIPS, STD-7.10 list, CHANGELOG line (T15j); events.md regenerated. Gate: ruff clean, events.md current, Windows 2241 OK (85 skipped); WSL 2241 OK except the two test_release_contents git-archive checks, which read HEAD and so fail until the new guide is committed (as T11); re-run green after the commit. Review fix (T15r): architecture.md's `client_apply` row names `apply_client_flavors` (one journal and one Undo over several flavors, a guard per flavor, the WoW check once, stops at the first failing flavor); docs only, no new tests; gate green: 2241 OK on WSL (9 skipped) and Windows (85 skipped), ruff clean, events.md current |
| T16 | M4 | macro edit screen and popups | done | (this commit) | 14 new tests in test_macro_editor_edit.py (the plan's seven TUI ones plus 4 builder read/write/block_at, describe_at, reference_lines, completion_start); test_macro_editor_app's setUp and helpers moved to `MacroEditorTestBase` (shared), its New/Edit steps now on MacroEditScreen (T15f's MacroFormScreen removed); guide New and Edit section, internals Screens/Tests, architecture row and the CHANGELOG Macro Editor line name the editor. Gate green: WSL 2255 OK (9 skipped), Windows 2255 OK (85 skipped), ruff clean, events.md current; review fixes (T16r): Enter after a complete word is a new line unless ↑/↓ chose, a taken suggestion keeps the list closed, HELP names the edit screen's buttons, the builder preview keeps the block's spaces; 2 new tests (test_enter_after_a_complete_word_is_a_new_line, test_builder_preview_keeps_the_block_as_written), test_help walks the edit and reference screens; guide and internals name the Enter rule; gate green: WSL 2257 OK (9 skipped), Windows 2257 OK (85 skipped), ruff clean, events.md current |
| T17 | M4 | macro docs; push | done | (this commit) | 1 new test in test_docs.py (`test_macro_editor_guide_readme_and_notes`: guide V4/V5 sections before the steps, slots, action bars and the delete warning, cross-flavor warning (report.CROSS_FLAVOR), every KB template title and automatic optimizer rule title, spell names not checked, builder, safety net, backups layout, interrupted Apply, WoW running, every browse and edit-screen key; README Dry run / Undo / journals / Screenshots / FAQ rows; CLAUDE.md, CHANGELOG, architecture, internals (new Knowledge base section), releasing); test_config_copier_guide_readme_and_notes' README needle follows the moved Dry run sentence (STD-9.6). Guide gains How WoW keeps your macros, Macros and action bars, Slots, Keys on the edit screen, The conditional builder, Templates, The optimizer, Spell names are not checked, Across game versions, What the tool never touches, The safety net (Where your backups go, If an Apply was interrupted), WoW running, more FAQ and troubleshooting rows, and `edit.png` (T17c). Gate green: WSL 2258 OK (9 skipped), Windows 2258 OK (85 skipped), ruff clean, events.md current. Push (M4) left to the orchestrator. Review fix (fix: T17 review fixes): slots of a flavor without sourced limits are marked `unconfirmed` (ME3, T17r); Classic limits carried to T20; assertions added to 3 existing tests (app tree labels, slots_text, MacroSet.limit_known) and the guide needle; gate green: WSL 2258 OK (9 skipped), Windows 2258 OK (85 skipped), ruff clean, events.md current |
| T18 | M5 | config model and edits | done | (this commit) | 10 new tests in test_config_editor_ops.py (the plan's nine plus test_scan_unreadable_file_is_read_only_and_logged); tests/fixtures.py gains build_config_tree; events cvar.scanned, cvar.file_unreadable and client_events("cvar") registered, docs/events.md regenerated; gate green: WSL 2268 OK (9 skipped), Windows 2268 OK (85 skipped), ruff clean, events.md current |
| T19 | M5 | recommendations data | done | (this commit) | 5 new tests in test_kb.py (the plan's test_recommendations_all_sourced_and_known_cvars plus one per CVar and flavor, the schema, unsourced or odd entries dropped, missing or bad file) and recommendations.json in KbShipsTest's README check; 37 recommendations over 36 CVars; gate green: 2273 tests WSL and Windows (0 failures), ruff clean, events.md matches |
| T20 | M5 | CVar base from dumps + wiki notes | done | (this commit) | CVars shipped for _retail_ 12.1.5, _classic_ 5.5.4, _anniversary_ 2.5.6, _classic_era_ 1.15.9 (1834/1595/1584/1578 CVars, 26-28 wiki notes each) and _forever_ as a marked copy of Retail (U1); 28 sourced wiki notes; CC5 state check done (T20e); category rules for uncategorised CVars (T20f). 10 new tests (5 test_refresh_kb: old dump, CVar without client info, macro limits from the dump, provisional copy, bad --provisional; 5 test_kb: test_retail_base_covers_the_client_list, every dumped flavor ships, Forever copy, wiki notes sourced, patterns checked against the dumps) plus new category cases. Gate green: WSL 2310 OK (9 skipped), Windows 2310 OK (85 skipped), ruff clean, events.md current. Waiting on the user: the addon now marks addon commands, records emotes and macro limits (dumpVersion 2); the four dumps predate it, so no slash_commands/*.json and no dump-sourced macro limits ship yet (T20b, T20c): /kbdump again per flavor, then rerun refresh_kb.py (user_action). Review fixes (fix: T20 review fixes, T20r1-T20r4): a client slash key now beats an addon key on the same slash in the dump addon, +1 test (runs the addon's Lua under `lua`, skipped without one); internals, macro guide and dump README brought up to date; gate green: WSL 2311 OK (9 skipped), Windows 2311 OK (86 skipped), ruff clean, events.md current |
| T21 | M5 | config editor screens, apply, undo | done | (this commit) | 26 new tests: 13 in test_config_editor_run.py (runs across levels and flavors then Undo, created file, dry run, WoW running, changed since the scan, LF file, recovery, row text, help lines, confirm groups and scope entries, result rows, applicable recommendations), 13 TUI in test_config_editor_app.py (the plan's six plus registry, Set on ticked files, filters, leaving asks, WoW running, the help panel beside the tree at 160 columns, 80x24); the editor added to every meta-test table (look and feel incl. DESTRUCTIVE_REVIEWS, help, quit incl. STAGING_TOOLS, tool menu, toasts, warnings) and to test_structure (journals/undo, recovery, action mixins, banner, 10 tree screens); shared `TickActions.space_on_node` hook (T21a) and the compact tool menu (T21k); first guide, internals doc, README/CLAUDE.md/architecture/releasing rows, RELEASE_SHIPS, STD-7.10 list, CHANGELOG line, browse.png (T21j); events.md regenerated. Gate: ruff clean, events.md current, Windows 2299 OK (85 skipped); WSL 2299 OK except the two test_release_contents git-archive checks, which read HEAD and so fail until the new guide is committed (as T11, T15); re-run green after the commit; review fixes (T21r1, T21r2): Reset checks each ticked file's own flavor for a default, +1 TUI test; gate green (WSL and Windows 2300 OK) |
| T22 | M5 | config editor docs; push | done | (this commit) | 1 new test in test_docs.py (`test_config_editor_guide_readme_and_notes`: guide's The three levels and Synced CVars and why an edit sticks (V2 evidence, `cache.md5`, `.old`) before the steps, If a change comes back (report a revert, Q5), Unknown CVars, Where the help comes from, Recommend…, the categories, never touches, safety net, backups layout, interrupted Apply, WoW running, every browse key; README practice-run, undo, journals, Screenshots and the three FAQ rows; CLAUDE.md, CHANGELOG, architecture, internals (new Why an edit sticks (V1, V2) and Knowledge base sections), releasing); the T12 and T17 README needles follow the practice-run sentence (STD-9.6); `recommend.png` added (T22c). Gate: ruff clean, events.md current, Windows 2312 OK (86 skipped); WSL 2312 OK except test_release_contents' shipped-link check, which reads HEAD and so fails until recommend.png is committed (as T11, T15, T21); re-run green after the commit. Push (M5) left to the orchestrator. Review fixes (T22 review, all three accepted, docs only): the guide's Unknown CVars says Reset refuses an unknown CVar and points at Remove (it stays enabled, as ticked files may know the default; pinned in test_docs), Where the help comes from says the build is named beside Blizzard's text, the internals Staging wording matches, and T22c's count now reads Retail's 32 (Classic flavors have 3 character CVars) |
| T23 | M6 | whole-branch review, gate, CI, ready to merge | done | (this commit) | No new tests (a review task with no code change). The whole-branch review found nothing to fix (T23a). CHANGELOG `[Unreleased]` was already complete (T23b). Gate green: WSL 2312 OK (9 skipped), Windows 2312 OK (86 skipped), ruff clean, events.md current. CI run 41787680465 on 789d7b3 succeeded (ubuntu / 3.10, windows / 3.13). Push and merge left to the orchestrator and the user (T23c). Review fixes (T23r): no code change, no new tests; a separate reviewer agent checked T23 and its two findings are recorded, not fixed here (T23r1, T23r2). Before the user is told the branch is ready to merge, the orchestrator still owes the milestone push (CI need not be re-checked for this docs-only ledger change) and a fresh-reviewer pass over the whole `git diff master...HEAD` |

## Decisions taken during the build

(append `T<n>a: …` lines here as calls are made)

- T1a: launcher.log trim rule (LN6). A record is a line with a leading date plus the indented lines under it (the
  traceback of a `bootstrap.failed`). Dates read: year first (`2026-11-04`, `2026/11/04`) and the `cmd.exe`
  `%date%` shapes with an optional weekday (`Wed 11/04/2026`, `04.11.2026`); a day/month that could be either order
  is dropped only when both readings are older than `log_retention_days`. Undated lines are kept. When no line has a
  readable date, the last 2000 lines are kept. Rewritten via `.partial` + replace, only when something is dropped.
- T1b: `log_bootstrap_failure(..., path: Path | None = None)` instead of `path: Path = LAUNCHER_LOG`: the default
  is read at call time, so tests can patch `bootstrap.LAUNCHER_LOG` and never write the repo's `logs/`. `suite.run`
  passes `<log_dir>/suite/launcher.log` explicitly (none when `log_dir` is None).
- T1c: a string problem (the Python check) has no `type=` field; an exception gets `type=` and its last 10
  traceback lines, indented 4 spaces. Multi-line messages are joined with ` | ` to keep one line per record.
- T1d: `where` values: `python_check`, `startup` (uncaught in `__main__` before the log opens), `lock`, `config`,
  `log_start`. The LN3 folder hint goes on the lock, `log_start` and the non-`ConfigError` `OSError` of the config
  step; a `ConfigError` keeps "Fix or delete the file". An exception after the log opened but before
  `session.start` is now also logged there as `error` (`where=suite.start`), so `__main__` never logs it twice.
- T1e: the CHANGELOG line for the launcher fix lands in T3 with the `.cmd`/`.sh` work (the user-visible part).
- T2a: the `.cmd` Python check runs before the last line and, on failure, writes `launcher.python_missing` or
  `launcher.python_too_old` and then `launcher.exited`, pauses when double-clicked and exits: 3 for too old, 9009
  (cmd.exe's "not found") for missing. Any probe result other than 0 or 3 counts as missing (the Store placeholder,
  `py` without a Python 3). The probe and the version read use `call`, so a `.bat` shim (pyenv-win) returns.
- T2b: double-click = `%cmdcmdline%` contains both the script's name and `/c` (case-insensitive), compared by
  delayed-expansion substitution rather than `echo | findstr`, so quotes or `&` in the command line can't break it.
  The pause shows the launcher's own English prompt ("Press any key to close this window.", `pause >nul`), since
  `pause`'s text is localised and the tests pin the prompt.
- T2c: log writes are `(>>"<log>" echo ...) 2>nul`: a `2>nul` on the same command doesn't hide cmd.exe's own
  "cannot find the path" message for a failed redirect, the group's does. On the last line the path is read as
  `!WOWTOOLS_LOG!` (a `!` in the app folder survives). `launcher.started` writes `args=%*` last (`python=`,
  `platform=windows` first) so arbitrary arguments can only trail the line; an argument with `)` would cut the
  logged args short, which the suite's own arguments (`update`, `--check`, `--version`, `--help`) never contain.
- T3a: `wow-tools.sh` puts its whole body in `main()` and ends on `main "$@"; exit $?`, so the shell has parsed
  everything (the exit included) before Python starts; no `exec`, so it can log the exit. The rewrite test replaces
  the file with `echo REREAD; exit 99` lines while the fake app runs and checks none of them ran (dash and bash).
- T3b: the `.sh` Python check mirrors the `.cmd` (T2a): `python3` not on PATH, or a probe result other than 0 or
  3, is missing and exits 127 (the shell's "not found"); 3 is too old, reads `found=x.y`, exits 3. Its messages go
  to stderr. Log lines use ISO local time (`date '+%Y-%m-%dT%H:%M:%S'`), `platform=` is `uname -s`, and `args=$*`
  comes last as in the `.cmd`. Log writes are `{ ... >>"$log"; } 2>/dev/null`, so an unwritable folder is silent.
- T3c: README gets two FAQ rows ("The window flashes and closes when I start it", "It says the folder isn't
  writable") and a Troubleshooting row pointing at the first; the CHANGELOG starts an `## [Unreleased]` section
  with one `### Fixed` line for the launcher fix (T1-T3).
- T4a: the dump's console `category` is stored as the `Enum.ConsoleCategory` name (a number on a client without
  the enum) and written lowercased (`graphics`, `game`, `net` ...); the X8 mapping to the issue's groups is left to
  the KB loader (T8), so the JSON keeps the client's own word.
- T4b: scope: `isStoredServerCharacter` wins over `isStoredServerAccount` when both are set (the more specific
  file); neither is `machine`. `synced` is true exactly when the scope isn't `machine`. The dump's current `value`
  and `secure` flag are recorded by the addon but never written to the KB JSON (the user's own settings stay out).
- T4c: one `.toc` for every flavor, `## Interface: 120105, 50503, 20505, 11508` (the comma list the current
  clients read); the README tells the user to tick "Load out of date AddOns" if a flavor says it is out of date.
- T4d: several accounts of one flavor with a dump: the newest `KaosKbDump.lua` by modification time wins, and the
  output line names the file. A flavor with no or an unreadable dump is skipped with a message and keeps its older
  JSON; the run fails (exit 1, nothing written) only when no flavor had a readable dump.
- T4e: slash keys are lowercased (`/CASTSEQUENCE` -> `/castsequence`; the client matches them case-insensitively);
  when two `SLASH_*` keys claim one slash the alphabetically first wins (in Lua and again in Python), so reruns
  agree. The addon leaves its own `/kbdump` out. `slash_commands/<flavor>.json` also carries a top-level `source`
  (`client dump <flavor> <build>`, X6), beyond the plan's schema.
- T4f: `--wiki` reads `{"cvars": {name: {"text", "source"}}}` from `scripts/kb_dump/wiki_notes.json` (or
  `--wiki-notes PATH`) and adds `"wiki": {"text", "source"}` to that CVar's entry, beside the Blizzard `help` whose
  source is the file's top-level `source`. A note without text or without a `https://warcraft.wiki.gg/` source stops
  the run before anything is written; a note for a CVar the dump lacks is ignored. `refresh_kb.py` never uses the
  network: the notes are researched and rewritten in our own words by hand in T20 (X7's "MediaWiki API" fetch is not
  needed for that and is not built).
- T4g: output JSON is UTF-8, `indent=1`, sorted keys, LF, written via `.partial` + replace, so reruns on the same
  dump are byte-identical and diffs stay readable.
- T4h (T4 review): both files of a flavor are rendered to bytes before either is written; a dump string that is
  not valid UTF-8 (luasv keeps such bytes as surrogates) raises DumpError there, so the flavor is skipped with
  "could not be read: a string in the dump is not valid UTF-8", its older files are kept and the other flavors carry
  on. Refused rather than replaced: a KB entry with mangled text is worse than the previous good one.
- T5a: `is_character_name` is exactly `bool(name) and all(ch.isalpha() for ch in name)`: accented letters
  (`Aellâ`, `Trâxex`, `Dænerys`) pass, while spaces, digits, `_`, `.` and `-` fail. `real_characters(on_error=...)`
  takes the same `on_error` as `characters()` and passes it on. No CHANGELOG line: `flavor_name("_forever_")` already
  showed "Forever" through the title-case fallback, so the new `FLAVOR_NAMES` row changes nothing a user sees; it
  only pins the name. `docs/architecture.md`'s `install` row names both helpers.
- T6a: X5 is done by generalising, not forking: `core/client_apply.py` is thin and runs every write through
  `sv_apply.apply_flavor` / `apply_flavors` and `sv_undo.undo_run` / `recover`, which gained `guard=` (default
  `SvGuard`), `create=` and `dest_for=` (default the SavedVariables `destination`). Nothing had to be separate, so
  the docstring records that instead. A created file is a unit whose `SvFile.sha256` is None (annotation widened to
  `str | None`; the SavedVariables tools never make one, so their runs, events and journals are unchanged).
- T6b: a created file: refused (skipped, `EXISTS` "it exists now; rescan") if it exists at the check or right
  before the write; written with the new `fsutil.atomic_create_bytes` (fsync'ed partial, then `rename_no_replace`,
  so one that appears in between is never replaced, STD-5.16/5.17); journaled `{"action": "created", ...,
  "sha_after", "zip"}` with the run's zip so it matches its run like an edited entry; in the marker's new
  `created` list (not in `files`: no original); deleted by roll-back (`sv_apply.remove_created`), Undo and recovery
  only while still at its `sha_after`; recovery counts an absent one as at its original. Its outcome is `edited`
  with detail `created`, so the result rows count it as changed.
- T6c: every real run with something to write still gets an originals zip, even one that only creates files: it
  holds just `manifest.json` (with a `created` list), via `create_backup(..., allow_empty=True)`, so the marker and
  journal always name a real zip. The default still refuses an empty backup (WTF Cleaner unchanged).
- T6d: a stale `expected_sha256` follows the pipeline's own rule: that file is skipped (`file_changed`) and the rest
  of the run is written; a single stale change therefore writes nothing (no journal, no zip). A path the guard
  refuses stops the whole run before anything is written (`result.stopped`), as `SvGuard` does.
- T6e: `ClientFileGuard` takes exact, case-sensitive names (the tool's list, X4) at exactly
  `WTF/Account/<A>/<name>` or `WTF/Account/<A>/<Realm>/<Char>/<name>` with `is_character_name(Char)` (X3 enforced
  at the write too, so `Name - Copy` is refused even if a tool forgot to filter), never with `SavedVariables` on
  the way, and `Config.wtf` only as `WTF/Config.wtf`. It refuses a file that is a link and a path whose parent
  resolves anywhere but the lexical place below the flavor folder (a link on the way). `check(path, info=None)`
  returns the resolved path; `client_rel_ok` is the one rule both the guard and `client_destination` (Undo,
  recovery) use. The tool passes `names`; `cache.md5` and `.old` are never in it (V2).
- T6f: events: `sv_events.client_events(prefix)` = the pipeline's events with client-file texts for
  `file_edited`, `write_failed` and `probe_recovered`, plus `file_created` (Apply) and `file_removed` (Undo,
  recovery). No registry of an existing tool changed, so `docs/events.md` is unchanged until a tool registers it.
  No CHANGELOG line: nothing a user can see yet (the tools that use it land in T11, T15, T21).
- T7a: a macros-cache.txt is a known layout only when every line ends in CRLF (the file ends in one too), every
  block is `VER 3 <16 hex> "<name>" "<icon>"`, its body lines and `END`, with nothing between blocks and no id twice
  (compared case-insensitively). Anything else (LF-only or mixed endings, a missing `END`, `MACRO`, `VER 2`, a blank
  or stray line, no final newline, a BOM, a duplicated id) is read-only: `known_layout` False with a `line N ...`
  problem, no macros listed, and `apply_macro_changes` raises even with no changes. An empty file is known, empty,
  CRLF. A body line that is itself a `VER 3` header ends the block early, so it reads as a missing `END`.
- T7b: the header's icon has no quote and the name is greedy, so a name holding quotes reads back whole. A body is
  its lines joined with "\n"; an empty body is written with no lines (a block with one blank line also reads as "").
  `apply_macro_changes` refuses (ValueError) a malformed id, a line break in name or icon, a CR in the body, a quote
  in the icon, a body line `END` or `VER 3 ...`, an add of an id in the file, a replace/delete of one it lacks, and
  two changes to one id. It does not enforce `NAME_LIMIT` (16) or `BODY_LIMIT` (255): those are the model's (T13).
  Changed blocks are rewritten in place, deletes removed, adds appended in the order given. `ICON_DEFAULT = "134400"`
  is added for ME8.
- T7r1: (review) a `replace` whose name, icon and body all equal the parsed macro's keeps the block's exact bytes
  (ME13), so a block with one blank body line survives a no-op replace even though it reads as "" like a block
  with no body lines. Done in `apply_macro_changes` rather than left to each caller (T13), so no caller can drop it.
- T7c: `next_macro_id` counts only ids with the scope's prefix (another prefix in the file is ignored), writes
  16 uppercase hex digits, starts at `<prefix>00000000000001` and raises ValueError when the prefix runs out
  (`00FFFFFFFFFFFFFF`) or the layout is unknown.
- T7d: CVar files: a `SET <name> "<value>"` line has a name without spaces or quotes and the value runs to the line's
  last quote (quotes inside kept). Names match case-insensitively (the client's rule); `get` returns the last line's
  value. A set rewrites the CVar's first line in place, keeping the file's spelling of the name and that line's own
  ending, leaves the bytes untouched when the value is the same, and removes any later duplicate; a remove drops
  every line of it. New lines are appended with the file's newline (the first line's; CRLF for an empty file or one
  without a line ending), adding a newline first when the last line has none. ValueError for an empty name or one
  with a space or quote, a value with a line break, or a CVar both set and removed (or set twice in other cases).
- T8a: `kb.py` loaders take a keyword-only `root=` (default `KB_ROOT` = `wowtools/kb`, read at call time) beyond the
  plan's signatures, so tests read temp folders. Cached per process by path (`clear_cache()`), thread-safe. A missing
  file is "no data" and logs nothing; a file that is not UTF-8, not JSON, not an object, or a `cvars/<flavor>.json`
  without a `cvars` object, logs `kb.unreadable` (warning, `path`, `reason`) once and reads as empty. A flavor folder
  name that isn't `[A-Za-z0-9_]+` reads nothing (no path escapes). `kb.unreadable` sits in `CORE_EVENTS`, beside
  `changelog.unreadable`.
- T8b: `CvarInfo` from the T4 schema: `default` is None only when the entry has no string default; `help` is
  Blizzard's text; `description` / `description_source` are the `wiki` note's text and URL, both "" unless both are
  present (no unsourced description); `scope` is None for anything but machine/account/character; `source` is the
  file's top-level `source` (`client dump <flavor> <build>`). The raw `locked` / `readonly` flags are not in
  `CvarInfo` (the plan's interface); a later task can add them if the Config Editor needs them.
- T8c: the X8 mapping (`category_group(name, raw)`), groups `CATEGORY_GROUPS` = graphics, sound, interface,
  camera, nameplates, combat text, network, other. Name rules first, case-insensitive: `nameplate*` -> nameplates,
  any name containing `camera` -> camera, containing `floatingcombattext` or starting `combattext` -> combat text.
  Then the client's console category: graphics -> graphics, sound -> sound, net -> network, game -> interface;
  everything else (debug, console, combat, default, gm, reveal, none, a bare number, empty) -> other. Revisit when
  T20 has the real dumps.
- T8d: `cvar_state.json` = `{source, names, patterns, exceptions}`: the appendix reading's names plus every pattern
  the spec names (`closed*`, `*Tutorial*`, `last*`, `latest*`, `lastRenownForCovenant*`, `new*Season`,
  `saved*Config*`, `savedClassConfig*`, `garrison*`, `cameraSaved*`, `*Collapsed`). Matched case-insensitively
  (fnmatch on lowercased names, the client's own rule); an `exceptions` name is never state, which is how a pattern
  that catches a real preference in a flavor's dump gets corrected. CC5's "each pattern checked against the
  flavor's CVar dump" can only run once the dumps are in: it is T20's job (list each pattern's matches per flavor,
  move any preference into `exceptions`). An unreadable state list means no CVar is state (logged).
- T8e: macro limits: Retail 120 / 30 confirmed from the client's generated UI docs
  (`Blizzard_APIDocumentationGenerated/MacroConstantsDocumentation.lua`, Gethe/wow-ui-source `live` at 12.1.5 70688:
  `MAX_ACCOUNT_MACROS` 120, `MAX_CHARACTER_MACROS` 30), the URL in `macro_limits.json`. The `classic`, `classic_era`
  and `classic_anniversary` branches (5.5.4, 1.15.9, 2.5.6) use the same globals in `Blizzard_MacroUI.lua` but define
  them nowhere in Lua (no `MacroConstants` doc either), so those flavors are not shipped: they get Retail's values with
  `limits_known` False, for ME3's flag. A sourced entry needs positive integers and a `source`, else it isn't known.
  A later task can add them from an in-game check (e.g. the dump addon recording `MAX_CHARACTER_MACROS`).
- T8f: `wowtools/kb/README.md` (ships) names files and scripts in backticks only, no links into `scripts/`, which
  doesn't ship. No CHANGELOG line: nothing a user sees yet.
- T8g (review fix): `highestUnlocked*` joins the patterns (CC5 names it; T8d's list had only the exact name), so a
  sibling progress CVar such as `highestUnlockedMythicPlusTier` stays the target's own. `showTutorials` (the Retail
  Tutorials toggle, a preference) goes into `exceptions`, since `*Tutorial*` caught it. The per-pattern dump check
  stays with T20, now written on T20's ledger row so it can't be missed.
- T9a: `populate_characters` takes three keywords beyond the plan's interface: `shown=` (a filtered rebuild leaves
  the other characters out, and a realm or account left empty with them), `mark=` (the tick mark of each label at
  build time, e.g. the screen's `TreeFilter.shown_tick_mark`; none when omitted) and `on_error=` (passed to the
  folder listing). Node data is a `CharacterNode` NamedTuple (`kind` is data[0], as `relabel_branch` reads it) that
  carries its tick keys, so `node_keys(node)` is a screen's whole `node_tick_keys` for these nodes; an account's keys
  are its characters' only, so a tool that adds its own tickable nodes with `account_extra` adds their keys itself.
- T9b: an account with no real characters still shows (a dim "no characters" line under it) so the user sees every
  account of the flavor; with `shown=` it is dropped instead, unless `account_extra` put something under it. An
  account or realm with nothing tickable under it (every character disabled) shows a blank mark, never ✔. A disabled
  character is dim, its reason after it in dim italic. Realms keep `real_characters()`'s order (case-insensitive).
  `tests/fixtures.py` gains `build_character_tree` (folders only) for T10 onward.
- T9c (review fix): `populate_characters` takes `character_extra(character, node)` for T15 (macros under a character)
  and T21 (a character's config): with it a character is built with `allow_expand=True`, collapsed, and goes back to
  a leaf when the hook added nothing. Both hooks now return the tick keys of what they added (None for none), folded
  into the `CharacterNode.keys` of every node above in tree order (account: its extras' then its realms'; character:
  its own key, none when disabled, then its extras'), and into the returned list, so a parent's mark and Space cover
  them. This replaces T9a's "a tool adds their keys itself".
- T9d (review fix): the tests gain a `TreeFilter` toy screen (filtered rebuild through `shown=` on
  `character_filter_texts`, marks from `shown_tick_mark`): Space on an account and `n` act on the shown keys only,
  a hidden tick is kept and counted by `hidden_ticked_keys`, the realm matches case-insensitively, no match shows
  `NO_MATCH_TEXT`.
- T10a: `PairPlan` gains a fifth status `unreadable` and a `problem: str | None` field (default None) beyond the
  plan's interface: a source or target file that exists but can't be read (a folder by that name, no permission, an
  I/O error) is never copied, its reason is shown instead of a crash, and it is logged once per path as
  `copier.file_unreadable` (warning). `warnings` defaults to `()`. `no-source` and `unreadable` pairs carry no bytes
  (`new`, `old`, `old_sha256` None), so the target's file is left alone.
- T10b: `plan_copy` returns targets in the order given and files in `COPY_FILES` order whatever order `names` has;
  it raises ValueError for a name outside `COPY_FILES` (X4) or the source among the targets (CC2), reads each source
  file once, never writes, and logs `copier.planned` (source, target count, files, counts by status). A target file
  already equal to what it would get (after the merge, for config) is `unchanged`, so it is never rewritten.
- T10c: the CC7 macro warning is on a `replace` of `macros-cache.txt` whose target file holds at least one macro, or
  is in a layout the reader doesn't know and isn't blank (it may hold macros); not on `new`, `unchanged` or a target
  file with no macros.
- T10d: `merge_config` sets a source preference only when the value the client reads from the target differs
  (`CvarFile.get`, last line wins), so a target with the same preferences comes back byte-identical even with odd
  spelling or a duplicated line; a duplicated line is collapsed only when the CVar's value changes. A source
  duplicate gives the last value. A target-only preference loses every line of it. With no target the result is the
  source's bytes minus its state lines (its own order, newline and other lines); an empty target file is merged like
  any target (CRLF for appended lines). The source's comment and other non-`SET` lines are not copied into a target.
  State is `core.kb.is_state_cvar` on the shipped list; the per-pattern dump check is still T20's.
- T11a: the left pane keeps the shared four buttons (Write, Dry run, Rescan, Undo last change; the look-and-feel
  meta-test pins Rescan third and Undo last), so **Diff** (navigate, `d`) sits in the action bar under the tree
  (`BarTree` / `ActionBar`, as the SV Browser's), enabled on a highlighted `replace` pair. Diff on anything else says
  why.
- T11b: the copy button is **Write** (overwrite, `w`), not "Copy": "Copy" is the Ace3 action bar's create-kind label
  (one label, one kind: test_structure), and "Copy files" made the row wider than the 50-column left pane. The confirm
  is `kind="overwrite"` (dry run `simulate`) and lists the CC7 warnings in `listed=`; its title is "Copy the ticked
  files?".
- T11c: tick keys are `PairKey(target, name)`; nothing is ticked at first (CC2), the left pane's five file boxes are
  all ticked (CC3). Only pairs that write something (new, replace) of a ticked file get a key; unchanged, no-source
  and unreadable pairs show dim with no tick. `populate_characters`' own character key is never ticked:
  `node_tick_keys` and the mark use only a character's pairs. What Write copies = ticked pair, ticked file, status
  new/replace, filter-hidden ticks included (the confirm says how many are hidden). After a real run the ticks of
  pairs that are now unchanged drop out; a dry run keeps them (Back to review).
- T11d: no USE AT YOUR OWN RISK popup (only the client's own five files, one game version, backups and Undo; like
  Interface Backup, whose tool has no popup). Superseded for the banner by T11r1. Ticks are a selection, not staged work: leaving asks nothing. The quit and
  tool-menu meta-tests now take "staged" from `review.discard_question()` instead of "in PREPARE", and the leave
  question test iterates `STAGING_TOOLS` (Ace3, SV Browser).
- T11e: the source picker is its own screen (`SourceScreen`: the shared tree without marks under each flavor for All
  flavors, the shared filter box, **Choose** (Enter) and **Back** (Esc), `t` to the tool menu); it dismisses with
  `(flavor, character)`. The meta-tests reach a review through `tests/fixtures.py` `reach_review` (the disclaimer,
  then `pick_source`: the first character with a file to copy) and walk the picker as a screen of its own (q, t,
  h, toasts); `tick_copier_targets` is the copier's PREPARE.
- T11f: the diff is unified (one column fits 80x24): plain files show each change with three lines around it and `…`
  between parts; `config-cache.wtf` shows the whole file with its state lines noted "kept: the target's own".
  Computed in `report.diff_rows` (UI-free); bytes decoded UTF-8 with replacement for display only.
- T11g: the registry description is "Copy one character's macros, chat, layout, CVars and addons to others." instead
  of the plan's longer line, which wrapped in the tool menu at 120 columns and made the list scroll, dropping the
  shield art at 120x30.
- T11h: the scan worker plans every real character of the source's flavor at once (`plan_copy` over all five files);
  other flavors' characters are listed at rebuild without reading any file. Folder listing errors and unreadable
  pairs feed the warnings view (`!`).
- T11i: the tree marks a CC7 pair "⚠ action bars" (the tree is narrow); the full sentence is in the confirm.
- T11j: registering the tool makes test_docs, test_help and test_release_contents require its guide, internals doc,
  README / CLAUDE.md / architecture / releasing rows, `RELEASE_SHIPS` entry and screenshots, so a first version of
  each lands here (screenshots `source.png` and `review.png` rendered from the app's own SVG screenshot of a fixture
  tree with headless Chrome), with the CHANGELOG `### Added` line. T12 reviews and completes the docs.
- T11k: test_structure pins the copier's journal and undo on the shared helpers and its review on
  `SvRecoveryActions`; the tree-filter screen count is 8; test_sv_browser_skeleton finds the SV Browser by name, no
  longer as the last registry entry.
- T11r1 (T11 review): the copier review does carry the shared `RiskBanner` as the first child of its left pane:
  STD-7.10 puts it on every screen that can destroy data, and Write overwrites the targets' files (Interface Backup's
  restore, Ace3 and SV Browser have backups and Undo too and still carry it). STD-7.10's list, test_structure's
  banner table, `DESTRUCTIVE_REVIEWS` (test_look_and_feel) and test_docs' banner guides now name the copier; the
  guide and the internals doc say so. The guide's `review.png` predates the banner: T12 re-renders it.
- T11r2 (T11 review): a replace whose files differ only in line endings or bytes that are not UTF-8 gave no diff
  row, so the diff said "The files are the same."; `report.bytes_only(plan)` now detects it and the diff screen
  shows "Only line endings or bytes that are not text differ." (after the rows of a `config-cache.wtf`).
- T12a: the guide's V1/V2 section is "Why a copy sticks" (plain words: WoW's fingerprint file `cache.md5`, the
  2026-11-04 test, never touching `cache.md5` or `.old`), placed right after "Close WoW first" so a user reads why
  the copy is safe before the steps; V3 (WoW tidies quests and reputations at logout) is one line there and an FAQ
  row. The safety part follows the SV Browser guide's layout (The safety net, Where your backups go, If a copy was
  interrupted, WoW running) so the tools read alike; "Dry run" became its own `##` section, as in the other guides.
- T12b: `review.png` is re-rendered at 120x30 (BASE) from the app's own SVG (`save_screenshot` on the
  `build_copier_tree` fixture, Retail, source Aellâ, Bob ticked, his macros pair highlighted) through headless Chrome
  at 1920 px wide (1920x1013, the SVG's own aspect; the T11 picture was 1920x1032). `source.png` is unchanged (the
  source picker has no banner). No script is committed: a one-off render, like T11's.
- T12c: the README's Screenshots section gains the copier's review; its "Terms of use" popup paragraph stays as is,
  since the copier has the banner but no USE AT YOUR OWN RISK popup (T11d, T11r1). The README test badge count is
  left for the release (releasing.md), as in T1-T11.
- T13a: `MacroSet.sha256` is `str | None` (None: no file, the run creates it) and the set gains `read_only` and
  `label` (`MAIN/Account macros`, `MAIN/Realm1/Aellâ`; no flavor in it). A missing file is an empty, writable set
  (`data` b""); a file that can't be read is a read-only set whose `parsed.problem` says why, logged once as
  `macro.file_unreadable` (warning); `scan_sets` logs `macro.scanned`. Event prefix `macro` (`SvTool("macro-editor",
  "macro")`, `client_events`). `scanner.read_set` reads one set (for a rescan after Apply).
- T13b: `Staged` keeps at most one `MacroChange` per id and file, folded as the user works: editing a staged add
  keeps it an add with the new text, deleting it drops it, an edit back to the file's own text drops the change.
  `stage_edit(staged, mset, macro_id, *, name, icon, body)`, `stage_new(staged, mset, *, name, body, icon=ICON_DEFAULT)
  -> id`, `stage_delete(staged, mset, macro_id)` raise ValueError (read-only or full set, unknown or deleted id, a
  macro the file can't hold); `effective_macros` and `free_slots` give the set as staged, which every operation
  works on (a second Replace text sees the first's text; pastes count earlier pastes' slots). `Staged.count()` and
  `clear()`.
- T13c: a new or pasted id is the highest of its prefix plus one over every id the file holds as read and every
  staged add, so a macro deleted in the same run never gives its id to a new one (an action bar button of the
  deleted macro must not start firing the new one); an add dropped before Apply never reached the file, so its id
  is free again.
- T13d: a clash is the same (cut) name, case-sensitive, among the target's macros as staged; `on_clash(pasted,
  existing)`. Overwrite needs no slot; rename and a plain paste do. Refusals are one line per macro not pasted:
  `<label>: <why>; <name> was not pasted.` (read-only, `no free macro slot (n/limit)`, a body over 255 or one the
  layout can't hold). Names are cut at 16 everywhere (`cut_name`), as the client does; an empty name is refused.
- T13e: the 255 limit counts characters with a line break as one (`body_length`: the client's MacroFrame counts
  letters, `GetNumLetters`, not bytes). `check_macro(name, icon, body)` is the one check (limits, then the file
  layout's own rules from `core.macrofile` by a probe add).
- T13f: Replace text acts on bodies only (ME7: reworking spell names); `preview_replace(staged, picks, find, new, *,
  case) -> list[ReplaceRow]` gives one row per macro with a match (before, after, count, refusal) in pick order and
  stages nothing; `stage_replace_text` stages the rows without a refusal and returns how many. An empty find matches
  nothing.
- T13g: `build_changes` raises ValueError for staged changes of a set not passed, skips a set whose bytes would not
  change, and gives each ClientChange one line per change (`macros-cache.txt: added "X"`, `changed "X"`, `deleted
  "X"`).
- T14a: `MacroReference`, `CommandInfo`, `ConditionalInfo`, `UnitInfo`, `MacroTemplate` and `RuleInfo` live in
  `core/kb.py` beside their loaders (core can't import a tool); `templates.py` re-exports `MacroTemplate` and
  `load_templates`. `load_macro_reference(flavor)` keys commands and conditionals by name and every alias, lower
  case, units by name; `slash_commands` is the flavor's `slash_commands/<flavor>.json` set, None with no dump (no
  dump is in the repo yet: until T4's dumps arrive no command is flagged in any flavor). `applies(entry)` is
  True/False only when the entry's `flavors` is a list. An entry without `source` or `help` is not loaded. Beyond
  the plan: `ConditionalInfo` carries `subject`, `explain`/`explain_no`, `explain_arg`/`explain_no_arg`, `args`,
  `arg_names`; the reference has a `builder` section (targets, unit, states) for T16's builder (ME9).
- T14b: sources. Conditionals, `@cursor`/`@none` and their patch notes from warcraft.wiki.gg/wiki/Macro_conditionals,
  commands from Macro_commands, units from UnitId, the Making_a_macro page for `/castsequence`, `/startattack` and
  `targettarget`; all help rewritten in our own words (X7, Q2). The `options` flag of each command (does its
  argument read conditions) follows Blizzard's SlashCommands.lua (Gethe/wow-ui-source `live`): the commands whose
  handler calls `SecureCmdOptionParse`; a command not in the reference is read as plain text. Every entry's
  `flavors` is null (the pages don't say which flavors have what) except `advflyable` (Skyriding, patch 10.0.7) and
  `house` (player housing, patch 11.2.7), marked `["_retail_"]` from the source's patch history: the only two the
  data flags outside Retail (ME5). Reversible; T20 can widen it from the dumps.
- T14c: tokens. A line is a command, a `#showtooltip`/`#show` directive (its argument read like `/cast`), a comment
  (any other `#` line) or chat text. Only a command with `options` gets clauses, blocks, conditions and units; any
  other command's argument is one `text` token, so `/say [help]` or `/run` code is never read or rewritten as a
  condition. A condition block token comes before its conditionals; `token_at` gives the innermost token containing
  the cursor or ending at it (a cursor right after `help` is on `help`).
- T14d: `explain_block(block, ref, *, verb="Cast")`: "Cast on <unit>" (or "Cast"), then ", if " and the phrases
  joined with "and", runs of "it's"/"your target is"/"you're" merged ("it's friendly and not dead"); `[]` is
  "Always."; an unknown term reads "<term> (not in the reference)". Units: numbered (`party2`), and `<unit>target`
  as "<unit>'s target" (`playertarget` = your target).
- T14e: `suggestions` returns (completion, help) where the completion replaces the word after its last separator
  (`/command` or `#directive` whole; after `@` the unit; after `[` or `,` the conditional, `no` forms offered once
  `no` is typed; after `:` the argument from `arg_names`); nothing outside a `[` of a command with options.
- T14f: optimizer rules (ME10): `target_to_at`, `duplicate_conditions` (an exact repeat in one block; conditionals are
  case-sensitive), `strip_spaces` (inside `[]`, between blocks and after `;`, on command lines with options only;
  the space between a block and the spell name is kept), `showtooltip_same` (only when the first command line is
  `/cast` or `/use`, every clause names that spell, and the last clause can't fail: no block or an empty `[]`).
  `/use`<->`/cast` is **not applied**: Blizzard's handlers differ (`/cast` prefers the spell, `/use` the item, when
  a name is both; even a slot number goes through `C_Spell.DoesSpellExist` under `/cast`), so it is in the KB as
  `cast_to_use` with `automatic` false and its reason, and `optimize` never makes it. `optimize(body, *, rules=None)`
  takes the rules for tests; a Rewrite's before/after are whole lines.
- T14g: twelve templates (the plan's ten plus harm-or-help and cast-sequence), each with at least one `{placeholder}`
  and a source; `fill_template` fills in one pass and raises ValueError for a missing, empty or multi-line value.
- T14r: review fixes. `duplicate_conditions` never drops a unit segment (`@...` or `target=...`): of several units
  in one block one wins, and dropping a repeat could change which, so `[@focus,@target,@focus]` stays as it is
  (conditionals are still deduplicated). A `no` completion in `suggestions` takes its help from the conditional's
  `explain_no` (`{unit}` read as "the unit", capitalised, a full stop), not the positive form's help.
- T15a: one Apply over several flavors (ME13 with All flavors) is one run: `core/client_apply.apply_client_flavors(tool,
  [(flavor, changes)], ...)` (`apply_client_changes` now wraps it) runs `sv_apply.apply_flavors` with a guard per
  flavor, the WoW check once for all, one journal and so one Undo. `runner.changes_by_flavor` groups
  `ops.build_changes` by flavor in scan order; `runner.NAMES` is `{"macros-cache.txt"}`.
- T15b: the left pane keeps the shared four buttons (Apply `w` destructive, Dry run, Rescan, Undo last change: the
  look-and-feel meta-test), so New `N`, Edit `e`, Delete `d`, Copy `k`, Paste… `p` and Replace text… `R` sit in the
  action bar under the tree (`edit_actions.TREE_ACTIONS`, as the SV Browser's), keys clear of a/n/x/c/s/t/f/q/h.
  Copy keeps Ace3's `create` kind and Rename (paste review) Ace3's `overwrite` (one label, one kind).
- T15c: tick keys are `SetKey(path)` (a Paste… target) and `MacroKey(path, id)`; Space on a character or on Account
  macros ticks the set and its macros (X2). Copy, Delete and Replace text… act on the ticked macros, else the
  highlighted one; Copy clears the ticks so the next ticks pick the targets; Paste… takes the ticked sets. A
  read-only set (ME14) has no keys and refuses New; it is listed in the warnings view ("read-only: <problem>").
- T15d: the search is the shared filter box: **Names** / **Bodies** boxes choose a macro's own texts, and the group
  texts (flavor, account, realm, character or Account macros) match as on every tree (a matching group keeps all its
  macros). "Show all / matching" is the **Only matching macros** box (ticked at first); unticked, every macro stays,
  the matches are underlined and a / n / Space act on everything (`narrowing`, `filter_keys`, `tree_narrowed`).
- T15e: the paste review (`popups.PasteScreen`) lists the clashes with their choice, **Skip** by default (nothing is
  overwritten unless asked), Skip / Rename / Overwrite buttons, **Apply to all**, Enter on a clash cycles its choice;
  it re-runs `ops.preview_paste` (new: `PasteClash`, `PastePreview`, `copy_staged`, `clash_key`) on a copy of the
  staging and shows the refusals and `report.paste_warnings` (one ME5 line per (from, into) pair of flavors, then
  each macro's `unknown_terms` in the target flavor's reference). Paste keeps the copy as the staging.
- T15f: until T16's edit screen, New and Edit open `popups.MacroFormScreen`: name (max 16), icon (empty = `134400`),
  body `TextArea`, `n / 255` meter, Save (`Ctrl+S`) off over 255, the staging's `check_macro` refusal under the fields.
- T15g: staged marks are short symbols before the macro's line (`✎` changed, `+` new, `✗` deleted and struck), not
  after it as on the SV Browser: a macro line (`name · first line · n/255`) is usually wider than the tree.
- T15h: like the copier (T11d, T11r1): no USE AT YOUR OWN RISK popup (only `macros-cache.txt`, every change staged and
  reviewed, backups and Undo), but the `RiskBanner` tops the left pane (Delete and Overwrite remove macros):
  STD-7.10's list, test_structure's banner table, `DESTRUCTIVE_REVIEWS` and test_docs' banner guides name it.
- T15i: staged edits ask before leaving, quitting, a rescan or Undo drops them (the SV Browser's "staged edits"
  wording); the macro editor is in `STAGING_TOOLS` and `PREPARE` (`tests/fixtures.stage_macro_edit`: a new macro in
  Retail's first writable set). The Delete confirm (destructive) only stages, with the ME6 action bar sentence
  (`report.DELETE_WARNING`), which the Apply confirm repeats while a delete is staged.
- T15j: registering the tool makes the docs tests require its guide, internals doc, README / CLAUDE.md /
  architecture / releasing rows, `RELEASE_SHIPS` entry, CHANGELOG `### Added` line and a screenshot, so first
  versions land here (`browse.png`: the app's own SVG at 120x30 of `build_macro_tree`, Retail, an edit and a new
  macro staged, through headless Chrome at 1920x1013; no script committed, as T11/T12). T17 completes the docs.
- T16a: the edit screen's keys are Ctrl+B (builder), Ctrl+O (optimize), Ctrl+T (template), F1 (reference) and
  Ctrl+S (Save), not the plan's bare `b`, `o`, `t`: the focus sits in the name, icon or body boxes, where a letter
  types (STD-8.8), and `t` is the suite's tool-menu key that a screen may bind to nothing else (STD-8.11). The
  letters stay as the Ctrl mnemonics; every popup's OK / Insert is Ctrl+S too.
- T16b: the builder, optimizer and template popups are `builder_screen.py`, `optimize_screen.py` and
  `template_screen.py`, not the plan's `*_popup.py`: STD-1.7's front-end module names (`*_screen.py`, `popups.py`,
  ...) are the only ones that may import textual (test_only_front_end_modules_import_the_ui). Their UI-free halves:
  `builder.py` (`BlockChoice`, `read_block`, `write_block`, `block_at`), `explain.describe_at` /
  `reference_lines`, `syntax.completion_start`, `report.scope_text`.
- T16c: the edit screen is a full screen (Header, the body and the help panel side by side, a WrapButtonRow of six
  compact buttons, BottomBar), so the help panel has room; Esc closes the suggestion list first, then cancels. The
  optimizer's and builder's confirm button is **OK** (confirm), not "Apply": Apply is the destructive run label
  everywhere (STD-8.3) and these popups only change the editor's text. With no rewrite to make, Ctrl+O shows a
  notice instead of an empty popup.
- T16d: suggestions open on typing only (a cursor move closes them, so ↑/↓ keep moving the cursor), list what
  `syntax.suggestions` gives minus the word already typed in full, and replace from `completion_start` to the
  cursor; while they show, ↑/↓ choose and Tab/Enter take one, else Enter is a new line and Tab the next control.
- T16e: builder (ME9): the target radio list is none + the reference's builder targets, plus the block's own unit
  when the list lacks it (`@party1`); `target=x` reads as `@x`; help/harm/either; a checkbox per builder state,
  ticking one unticks its `no` opposite. An unchanged choice writes the block back exactly as written (spacing
  kept); a change keeps every item's place and spelling, drops unticked ones, puts a new target or reaction first
  and new states last, and keeps items the builder doesn't show (`spec:2`). Outside a block OK inserts a new one
  at the cursor, with a space before the spell name or after the command if none is there.
- T16f: a template replaces an empty body, else goes in as whole lines after the cursor's line. The help panel
  reads directives as "a metacommand (not in the reference)" (the KB has no directive entries) and adds the
  flavor's `unknown_terms` line (ME5) under the cursor's help. The name box keeps a file name longer than 16 as it
  is (its max length is the longer of 16 and the name), so an edit that leaves the name alone never cuts it (T13r).
- T16r: review fixes, all three taken. Enter after a word that is itself a reference entry (`/targetenemy`, `/cast`,
  `/use`) is a new line unless ↑/↓ moved the highlight; Tab still takes the highlighted suggestion; the Changed a
  taken suggestion causes lists nothing, so `/cas` Tab Enter is `/cast` and a new line. HELP gains "The edit screen
  (New, Edit)" naming Save, Builder…, Optimize…, Template…, Reference (and OK, Insert, Back) and drops the removed
  macro form; test_help's walk opens MacroEditScreen and ReferenceScreen and checks their labels. BuilderScreen takes
  the block as written (`block=`), so its preview keeps the block's spaces as OK writes them.
- T17a: the guide puts V4 ("How WoW keeps your macros": one file per account and character, numbers, names cut at 16,
  icons, WoW re-sorts by name, and V2's why an edited file sticks with `cache.md5` and `.old` never touched) and V5
  ("Macros and action bars": edit and Overwrite keep the number, new and pasted get the next free one, delete takes
  the buttons, a deleted number is never reused in the same Apply) right after "Close WoW first", then "Slots",
  before the steps, as T12a did for the copier. The edit screen's keys table, builder, templates, optimizer and "Spell
  names are not checked" are `###` sections under "New and Edit"; "Across game versions" sits under "Copy and paste".
  The safety part follows the copier guide's layout (The safety net, Where your backups go, If an Apply was
  interrupted, WoW running) so the tools read alike.
- T17b: `macro_limits.json` is sourced for Retail only, and the tool does not mark another flavor's limits as
  unconfirmed, although `wowtools/kb/README.md` and the file's comment said it does. T17 is docs only, so the docs now
  match the code: the guide's Slots section says other game versions are counted with Retail's numbers, which may not
  be what the game allows there; the KB README, the JSON comment and the internals doc say so too. Showing an
  "unconfirmed" mark, or sourcing the Classic limits, is left for review (T23).
- T17c: `docs/assets/screenshots/macro-editor/edit.png` added to the guide's New and Edit section: MacroEditScreen on
  `build_macro_tree` (Retail, Bob's macro, a mouseover-heal body with the cursor in `help`, so the help panel reads
  the block out) at 120x30 (BASE), the app's own SVG through headless Chrome at 1920x1013, no script committed (as
  T12b). The README's Screenshots section gains `browse.png`; its "Terms of use" popup paragraph stays as is (the
  editor has the banner but no popup, T15h, as T12c).
- T17d: the guide lists every template title and every automatic optimizer rule title, and test_docs checks them
  against `load_templates()` / `load_optimizer_rules()`, so a new template or rule must reach the guide. The in-app
  help (`help.py`) is unchanged: it already covers the core functions and links the guide.
- T17r: review fix for ME3. The tree now marks the slots of a flavor with no sourced `macro_limits.json` entry
  `unconfirmed` (`3/30 unconfirmed`, `30/30 FULL unconfirmed`): `MacroSet.limit_known` reads `kb.limits_known`, and
  `report.slots_text(count, limit, known)` appends `report.UNCONFIRMED`. The counting and the New / paste refusal still
  use Retail's 120 / 30 there. The guide's Slots section, the in-app help, the KB README, the JSON comment and the
  internals doc describe the mark, and the guide no longer guesses what the game does with a file over its limit.
  Sourced limits for the other flavors are not added here: the repo has no Classic client data, and a value without
  a source is not shipped (X6). They are now on T20's row, to be taken from each flavor's `MacroConstants` with the
  dumps; until then ME3 holds for Retail, and other flavors carry the mark.
- T18a: the Config Editor's event prefix is `cvar` (`cvar.scanned`, `cvar.file_unreadable`, the client pipeline's
  `cvar.*`), since `config.` is core's. T18 registers only the events it logs plus client_events; T21 adds
  `cvar.started` with the app.
- T18b: ConfigTarget gains `problem` (default None): a file that can't be read is read-only, with data, parsed and
  sha256 None, as a missing file has (exists False, read_only False; a set there creates the file). scan_targets
  lists every account and real character (X3) even with no file, so a CVar can be added to one, and Config.wtf
  first, then accounts in install's (sorted) order, each followed by its characters.
- T18c: rows() takes `staged=` (keyword, default None) so the list shows values as staged; Row gains `staged` (a
  pending change touches it) and the properties `category` and `known`. Rows are sorted by name, case ignored.
  "Show all known" adds the KB CVars whose scope is the file's level; one whose scope the data lacks (None) is not
  added (it can't be said to belong there) but still shows when the file sets it, never with a scope warning.
- T18d: `changed` compares as text and then as numbers (`same_value`: "1.0" equals "1"); a CVar not set is never
  changed (the client uses its default); set with no KB default is None, and "changed only" leaves those out.
- T18e: staging folds: a set back to the file's own value, or a remove of a CVar the file doesn't set, stages
  nothing; set and remove of one CVar replace each other; names match in any case and keep the file's spelling.
  stage_toggle(staged, target, name, info) flips "0"/"1" from the staged value, else the KB default, and refuses
  (ValueError) anything else; a toggle back to the default of a CVar the file doesn't set drops the change instead
  of writing the default. Name and value rules are core.cvarfile's (stage_set probes apply_cvar_changes), so the
  stager and the writer can't disagree.
- T18f: category_of uses the KB's group (core.kb.category_group already maps the client category and the name
  rules, T8) and falls back to the name rules for an unknown CVar; model.CATEGORIES is kb.CATEGORY_GROUPS, kept once.
  build_changes' lines read `config-cache.wtf: name "old" -> "new"`, `added name "value"`, `removed name` (sets in
  staging order, then removals by name).
- T19a: `recommendations.json` is a JSON object, `{"comment", "recommendations": [...]}`, like every other KB file
  (`_read` takes only an object), each entry exactly `cvar`, `value`, `flavors`, `reason`, `source`.
  `load_recommendations(flavor)` returns `Recommendation(cvar, value, flavors, reason, source)` for the flavor in file
  order; an entry without a cvar, a string value, a reason, an `https://` source or a `flavors` list is dropped, and of
  two for one CVar and flavor (any case) the first wins. Unlike the macro reference there is no `flavors: null`: a
  value is recommended only where the source shows the CVar.
- T19b: sources. Each CVar's flavors come from warcraft.wiki.gg's Console variables/Classic comparison table (its
  per-row client bits: 12.1.5 Retail, 1.60.1 Forever, 5.5.4 `_classic_`, 2.5.6 `_anniversary_`, 1.15.9
  `_classic_era_`), every Retail one also checked against Console variables/Complete list (12.1.5). PTR, beta and
  other test folders get none (no source names them). The source URL is the CVar's own wiki page where one exists,
  else the Console variables page (Retail only) or Console variables/Classic; cameraIndirectVisibility and
  cameraIndirectOffset cite the seekingaura config notes, advancedCombatLogging Raider.IO's support article. Reasons
  are our own words. Retail 12 renamed the combat text CVars to `*_v2`, and they are listed so; `nameplateMotion` is
  in neither 12.1.5 list and is not recommended. Recommendations that depend on the player (SpellQueueWindow by
  latency, scriptErrors) are left out.
- T19c: two entries for one CVar are allowed when their flavors don't overlap and the source gives each its own value
  (cameraDistanceMaxZoomFactor: 2.6 on Retail, 4 on Classic). The two nameplate values taken from Retail's own
  defaults (nameplateOccludedAlphaMult 0.4, nameplateSelectedScale 1.2) are for the Classic flavors only.
- T19d: no CHANGELOG line: the data has no user yet (the Config Editor lands in T21, whose CHANGELOG line covers it).
- T21a: ticks pick files (`FileKey(path)`: Config.wtf, an Account config, a character; an account, realm or flavor
  ticks its files). Set, Remove and Reset act on the highlighted CVar in every ticked file, else in the row's own
  file; Add puts a CVar into every ticked file, else the highlighted one; Recommend… acts on the highlighted file
  only (recommendations differ per flavor). Space on a CVar row switches it when its value as staged (else its
  default) is 0 or 1 and says "use Set (e)" otherwise; on any other node it ticks (STD-8.8 keeps Space, a and n).
  The shared `TickActions.action_toggle` gained one hook, `space_on_node(node)` (False by default), since no tool may
  define its own `action_toggle` (test_review_machinery_lives_in_ui). The hint keeps REVIEW_HINT and adds "Space on
  a 0/1 CVar toggle".
- T21b: the plan's left-pane buttons Set, Add, Remove, Reset and Recommend… sit in the action bar under the tree
  (`edit_actions.TREE_ACTIONS`, keys `e`, `N`, `d`, `R`, `m`; kinds overwrite, create, destructive, revert,
  overwrite), as T15b did: the left pane keeps exactly Apply / Dry run / Rescan / Undo last change (the
  look-and-feel meta-test). The left pane has the filter box, a **Show** heading, the category select (All
  categories + the eight X8 groups), **Changed only** and **Show all known**.
- T21c: Reset is offered only for a CVar whose KB default is known (it stages the removal, so the game uses that
  default, CE5); Remove takes any CVar's lines out, an unknown one included. Neither asks first: both only stage,
  and the Apply confirm lists every change.
- T21d: the tree is (flavor ›) Config.wtf, then populate_characters: Account config (account_extra) and each
  character, whose own node is its config-cache.wtf (no extra file node under it). A file's CVar rows load when it
  opens (`on_tree_node_expanded`; a real file sets hundreds and Show all known adds the KB's), at once when the
  search opens it or a rebuild keeps it open (the cursor goes back to the row). The search is the shared filter box:
  a CVar matches on its name, Blizzard's help or our note, a file on its group texts (flavor, Config.wtf / account,
  Account config / realm, character); a matching group shows all its rows, a file with no match is hidden.
- T21e: the help panel (`report.help_lines`) is a 5-row scrolling panel under the tree; from 160 columns
  (`Screen.HORIZONTAL_BREAKPOINTS`, class `-wide`) a right column a third of the tree pane wide instead (the tree keeps two thirds, so it still grows at 160x45). For a file it says where it
  is, its level, how many CVars it sets (or "No file yet", or read-only) and, for a flavor without CVar data, that
  every CVar shows as unknown. "Type" is said only for a CVar whose default is 0 or 1 (the KB has no type field).
- T21f: Recommend… (`popups.RecommendScreen`) lists `ops.applicable_recommendations`: the flavor's recommendations
  whose CVar the KB keeps at the file's level, or whose scope it doesn't know (until T20 that is every one); one
  already at its value is listed dim and can't be ticked. Space or Enter ticks, OK stages the ticked ones.
- T21g: Add (`popups.AddCvarScreen`) shows, as the name is typed, what the KB knows (default, scope, sync), or
  `unknown`, and a scope warning; it never refuses for scope. The Apply confirm lists every CVar set at another level
  than its KB scope (`report.scope_listed`, ConfirmScreen `listed=`). Set is the shared TextPromptScreen, opened on
  the value as staged (else the default) and checked with ops.stage_set's own rules.
- T21h: like the copier and the macro editor (T11r1, T15h): no USE AT YOUR OWN RISK popup, but the RiskBanner tops
  the left pane (Remove and Reset take lines out): STD-7.10's list, test_structure's banner table,
  DESTRUCTIVE_REVIEWS and test_docs' banner guides name it. The editor is in STAGING_TOOLS and every PREPARE table
  (`tests/fixtures.stage_config_edit`).
- T21i: the flow takes `kb_root` (tool_options; tests point it at a temp knowledge base). Until T20 ships the CVar
  data, a real install shows every CVar as `unknown` (still editable) and Recommend… lists every recommendation of
  the flavor. `cvar.started` registered, docs/events.md regenerated.
- T21j: registering the tool makes the docs tests require its guide, internals doc, README / CLAUDE.md /
  architecture / releasing rows, `RELEASE_SHIPS` entry, CHANGELOG `### Added` line and a screenshot, so first
  versions land here, as T15j: `browse.png` is the app's own SVG at 120x30 of `build_config_tree` with the test
  knowledge base (Retail, Aellâ open, one staged CVar, cameraDistanceMaxZoomFactor highlighted), through headless
  Chrome at 1920x1013, no script committed. The README's practice-run, undo and journal sentences (pinned by
  test_docs) and its Screenshots section are left for T22.
- T21k: the tool menu's description is "See and change CVars in Config.wtf and each account and character, with
  help." (77 characters), not the plan's 95-character text, which wrapped at 120 columns
  (test_menu_shows_everything_at_base). An eighth tool no longer fit the menu either: at 120x30 the shield art made
  the list scroll, at 80x30 the list scrolled even without it. So the blank row between "Choose a tool" and the list
  is gone at every size (ToolArea counts no list margin), and once the art gives way to the name line the blank rows
  above the banner and under the version go too (`ToolMenuScreen` class `-compact`). The hint now fits down to 80x14;
  test_menu_hides_the_hint_below_tiny_rather_than_overlap checks (80, 13) and (80, 11), the same distance below the
  new floor as (80, 16) and (80, 14) were below the old one.
- T21r1: Reset across ticked files checks the default in each file's own flavor (`cvars_for(t.flavor.folder)`), not
  the highlighted row's: it stages only where a default is known, names the skipped files in a warning toast, and is
  refused only when no ticked file's flavor knows one (keeps T21c true in All flavors).
- T21r2: the guide's Troubleshooting row no longer says Space "does nothing" on a non-boolean CVar (it shows a
  toast pointing to Set); the Reset FAQ notes the per-version skip.
- U1 (user, 2026-11-04): the user ran /kbdump in _retail_ (12.1.5), _classic_ (5.5.4), _anniversary_ (2.5.6) and
  _classic_era_ (1.15.9); the dumps are under each flavor's WTF/Account/ADD1KTED2KA0S/SavedVariables/KaosKbDump.lua.
  _forever_ has not launched yet: the user said to treat it as the same client as Retail. So T20 ships
  cvars/_forever_.json and slash_commands/_forever_.json as a copy of Retail's, each with a top-level
  "provisional": "copied from _retail_ until a _forever_ dump exists" marker (and macro_limits likewise), and the
  user will supply the real _forever_ dump later; rerunning scripts/refresh_kb.py then replaces the copy.
- T20a: a CVar the client lists but whose `GetCVarInfo` gave nothing (161 on Retail: `enableCombatText`,
  `readEULA`, `removeChatDelay` ...) is written with `default` and `scope` null and `synced` false, not `""` and
  `machine` (the addon's `flag(nil)` made them look machine-scoped); `core/kb.py` already reads null as unknown. So
  test_retail_base_covers_the_client_list checks that every CVar has a `default` and a `scope` key, that both are known
  or both unknown, and that over 85% are known (91% on Retail).
- T20b: the four dumps carry the dumping client's addon commands (ACECONSOLE_*, DBM, ElvUI, TomTom ...) and no emotes
  (`/dance` comes from `EMOTE<n>_CMD<m>`, not `SLASH_*`), so the Macro Editor would have flagged every emote as missing
  and shipped one player's addon list. The addon (dumpVersion 2) now records emotes and puts every key whose
  SlashCmdList entry or SLASH_ global is tainted (`issecurevariable`) in `addonCommands`; refresh_kb.py drops those and
  writes `slash_commands/<flavor>.json` only from a dumpVersion 2 dump (an older list is kept, the run says why). No
  slash list ships until the user dumps again; until then the Macro Editor flags no command as missing (as before).
  The Lua was smoke-run under lua5.1 with stubbed APIs (scratchpad only).
- T20c: macro limits (T17r) come from the client too: the addon records `Constants.MacroConstants` (or the
  `MAX_ACCOUNT_MACROS` / `MAX_CHARACTER_MACROS` globals the Classic clients define in C) as `macroLimits`, and
  refresh_kb.py writes the flavor's `macro_limits.json` entry with source `client dump <flavor> <build>`, keeping the
  other entries and the comment. The Classic flavors stay `unconfirmed` until the new dumps arrive.
- T20d: U1's Forever copy is `refresh_kb.py --provisional _forever_=_retail_`: for a flavor without a dump in the run it
  writes the origin's files with `flavor` set, the source unchanged (it still names the Retail dump) and
  `"provisional": "copied from _retail_ until a _forever_ dump exists"`, and copies the origin's `macro_limits.json`
  entry with the same note (so Forever's slots read as known, 120/30). A flavor with its own dump is never replaced by
  a copy. The tools don't read `provisional` (no UI change); the KB README and the dump README describe it.
- T20e: CC5's per-pattern check against the four dumps: `*Tutorial*` caught two more preferences, `showNPETutorials`
  ("display NPE tutorials") and `housingTutorialsEnabled`, now in `exceptions` beside `showTutorials`. Every other
  match is state: `*Collapsed` (7, UI panels), `cameraSaved*` (4), `closed*` (4), `garrison*` (2), `highestUnlocked*`
  (2), `last*` (41: renown, transmog set IDs, EULA/TOS, GM chat, character select), `latest*` (2), `new*Season` (3);
  `saved*Config*` and `savedClassConfig*` match nothing in these clients and stay (the spec appendix names them).
- T20f: the dumps file 453 Retail CVars under the console category `Default` (and a few under `None`), among them the
  whole graphics menu (`graphicsQuality`, `RAIDfarclip`, `shadowMode`, `gxMaximize`) and the `Sound_*` volumes, which
  T8c's table put in `other`. For an uncategorised CVar only, `category_group` now places `sound_*` in sound and a
  list of graphics name prefixes (after dropping a leading `raid`) in graphics; a CVar with a real category keeps it.
- T20g: wiki notes: 28 CVars with no (or a one-word) Blizzard help that have their own warcraft.wiki.gg page (found via
  the MediaWiki API; `curl` on the page URLs gets 403) and are not marked removed there: camera (the zoom factor,
  follow style and its speed, terrain tilt, water collision ...), graphics (render scale, sharpening, SSAO, view and
  shadow settings ...), `nameplateMotion`, `Sound_AmbienceVolume`, `synchronizeConfig` / `synchronizeBindings` (V2),
  `maxFPS`, two interface toggles. The recommendations' `cameraIndirect*` and `ResampleAlwaysSharpen` have no wiki page,
  so they get no note (no unsourced text). Notes avoid the wiki's stated defaults (the client's own default is shown
  beside them).
- T20h: the dumps were read from the user's install read-only, only the four `KaosKbDump.lua` files, copied to a
  scratch tree that refresh_kb.py was pointed at; no test reads them. No CHANGELOG line: the Config Editor's unreleased
  `### Added` line covers the data.
- T20r1: in the dump addon a slash claimed by two keys goes to the client's (secure) key over an addon's, and only
  between two of a kind to the alphabetically first, so an addon key that sorts first no longer hides a client command
  from slash_commands/<flavor>.json. Fixed in the Lua (the dump keeps one key per slash, so the refresh cannot repair
  it); `test_client_command_beats_an_addon_key_on_the_same_slash` runs the addon under a plain `lua` with stubbed
  client APIs and skips where none is installed (the Windows suite, CI). Not changed: a key is still flagged as an
  addon's when any one of its SLASH_ globals is tainted, as before.
- T20r2: docs/internals/config-copier.md now records the CC5 check's result (each pattern checked against the four
  dumps; the tutorial toggles are exceptions) instead of saying it is T20's to do.
- T20r3: docs/macro-editor.md's Slots section says Forever uses Retail's numbers for now and only the Classic flavors
  are marked `unconfirmed`.
- T20r4: scripts/kb_dump/README.md says a `dumpVersion` 2 dump is what replaces a provisional flavor's slash commands
  and macro limits (a first-version dump replaces only the CVars); no new message in refresh_kb.py, since the addon
  always writes version 2 now and the refresh already prints that a first-version dump wrote no slash commands.
- T22a: the guide's spec facts come before the steps, as T12a / T17a: "The three levels" (the table moved up from the
  browse screen, with the help panel's own scope words and what `not set` means) and "Synced CVars and why an edit
  sticks" (account and character CVars are the synced ones, every `machine` CVar in the four dumps has `synced` false;
  V2's copied `config-cache.wtf` used at the next login, `cache.md5` and `.old` left to WoW).
- T22b: the revert report (builder check Q5) is a "If a change comes back" subsection: the account level was not
  tested on its own, so the guide says why it is treated like a character's and asks for game version, file, CVar, old
  and new value through README's Reporting a bug, with the `logs\config-editor` folder; a FAQ and a Troubleshooting row
  link it. No in-app text changes.
- T22c: `docs/assets/screenshots/config-editor/recommend.png` added to the guide's Recommend… section: RecommendScreen
  on `build_config_tree`'s ALT Account config (Retail) with the shipped knowledge base (17 recommendations at the
  account level; none of Retail's 32 is a character CVar, so a Retail character's popup would be empty; Classic, Classic
  Era and Anniversary each have 3), two ticked, the
  highlighted one's reason and source shown, at 120x30 (BASE), the app's own SVG through headless Chrome at
  1920x1013, no script committed (as T12b, T17c). The README's Screenshots section gains the existing `browse.png`.
- T22d: the guide does not list the recommendations one by one (unlike T17d's templates): they are data the help
  panel and Recommend… already show with their reason and source, and a list would drift from `recommendations.json`;
  the guide says how many, which areas and where they come from, and test_docs pins the categories and the sources
  rule instead.
- T23a: the whole-branch review ran in this task's agent (it has no subagent tool, so there was no separate fresh
  reviewer). It read `git diff master...HEAD` for the shared pipeline (`core/client_apply`, the `sv_apply`,
  `sv_undo`, `sv_journal` and `fsutil` changes), the byte-exact parsers (`core/macrofile`, `core/cvarfile`), the
  Config Copier's planner and merge, the three runners and undo modules, and the WoW-check, dry-run and read-only
  wiring of the three review screens, against the spec and the five Review Focus items. It also checked that `core/`
  never imports textual, that no tool imports another, that no tool names `cache.md5` or `.old`, and that CLAUDE.md,
  README, architecture and the internals and guide docs name all eight tools. Nothing needed a fix. Every earlier
  task already had its own review-fix commit.
- T23b: `CHANGELOG.md` `[Unreleased]` already held what T23 asks for (one line per new tool under Added, the
  launcher fix under Fixed, short), so it is left as it is.
- T23c: the push and the merge are left to the orchestrator and the user (this run's agents never push or merge).
  CI was checked once on the last pushed commit, which is HEAD before this ledger commit (STD-10.2). T20 stays
  `waiting-user`: the dumpVersion 2 re-dump does not hold up the merge, because the shipped KB works without it.
- T23r1: the whole-branch review (T23a) was not by a fresh reviewer, as T23 step 1 asks. The separate reviewer
  agent that checked T23 read only the T23 ledger commit, not the 154-file `git diff master...HEAD`, so it is not
  counted as the fresh whole-branch pass. This agent has no subagent tool either, so the dedicated fresh-reviewer
  pass over `git diff master...HEAD` (most capable model) is left to the orchestrator before the user is asked to
  merge; T23 step 1 is open until then.
- T23r2: the branch is one commit ahead of origin (the T23 ledger commit), so T23 step 3's push is still owed.
  Rejected for this agent, not for the run: this run's agents never push (T23c), so the push is the orchestrator's
  milestone push. The commits since the last CI run (789d7b3) change only the ledger, so CI need not be checked again.
- T23w1: the double-click check in `wow-tools.cmd` (LN1) now needs Explorer's and a shortcut's own command line,
  `cmd.exe /c ""<script>" "` (a space and a quote after the script's name, from `cmdfile`'s `"%1" %*`). Before, any
  `/c` line that named the script counted, so PowerShell (`/c ""<script>""`), a script or a scheduled task
  (`cmd /c wow-tools.cmd update --check`, which returns 10 when an update waits) stopped at "Press any key" on a
  non-zero exit. test_launcher runs the Explorer, PowerShell and script lines on Windows and pins the check.
- T23w2: Space on the source flavor's node (All flavors) ticks only its pairs: `node_tick_keys` drops the
  characters' own keys there as the character branch and `mark()` already did. With a filter applied it raised
  KeyError in `_pair_texts` and closed the app; without one it put the character keys in `ticked`.
- T23w3: the review's filter matches the source flavor's name too (`_target_texts`: the flavor, then account, realm
  and name), as it does for the greyed flavors and the source picker, in the tree, the marks and the hidden-tick
  count alike.
- T23w4: a source `config-cache.wtf` value that `apply_cvar_changes` can't write (a lone CR in it) makes only that
  pair `unreadable` (logged as `copier.file_unreadable`, its description now names the merge) instead of failing the
  whole scan. A target with no such file still plans as `new` (its source values are not merged).
- T23w5: PasteScreen mixes in EnterGuard (GUARD_BINDING, `start_guard()` on mount): with no clash it opens on Paste,
  so STD-7.15 applies.
- T23w6: the guide's id sentence is narrowed to one Apply, and says to log in once after an Apply that deletes a
  file's highest-numbered macro before adding to that file in another (its number is given out again). No code
  change: keeping a per-file high-water id across Applies is not in the spec.
- T23w7: MacroEditScreen.values() gives back the body and icon as they were when the user left them: the TextArea
  splits lines on U+0085, U+2028 and the like, and the icon box is trimmed, so a name-only edit rewrote untouched
  body lines (ME13).
- T23w8: Recommend… counts a recommendation as done when the file doesn't set the CVar and the KB default already
  is the value (`already the default`, never ticked); the guide says so. `cameraIndirectVisibility` (default 1 in
  every dump) stays in `recommendations.json`: it now shows as already the default, and `cameraIndirectOffset`'s
  reason refers to it.
- T23w9: each CVar row ends with its category, dim (`· camera`), as CE4 asks; the guide names it. The help panel
  still opens with it.
- T23w10: architecture.md's Config Editor line says which actions use the ticked files (Set, Add, Remove, Reset,
  else the highlighted one), which the highlighted file (Recommend…) and which act in place (Space on a 0/1 CVar).
- T23w11: no CHANGELOG line: every fix is inside a tool or launcher change this branch already lists under
  `[Unreleased]`. The Config Editor screenshots (`browse.png`, `recommend.png`, T22c) were taken before T23w8 and
  T23w9 and are not retaken here: they lack the category suffix and may show a default-valued recommendation as
  tickable. A retake is left for the next screenshot pass.
- U2 (user, 2026-11-04): the user re-ran /kbdump (dumpVersion 2) in _retail_, _classic_, _anniversary_ and
  _classic_era_ with every other addon disabled, so no addon commands are in the dumps (checked: addonCommands empty,
  no ElvUI/DBM/TomTom). refresh_kb.py --wiki --provisional _forever_=_retail_ on scratch copies of those dumps wrote
  slash_commands/<flavor>.json (674 Retail, 635-636 Classic, emotes included) and dump-sourced macro_limits.json
  entries (120/30 each). Every shipped flavor's slots now count as known, so the two tests that pinned Classic Era as
  `unconfirmed` patch macro_editor.model.limits_known instead; the guide, help and internals now describe
  `unconfirmed` as the case for a flavor with no recorded numbers. T20 is done; _forever_ stays a provisional copy
  of _retail_ until its own dump (rerun the same command without --provisional).
