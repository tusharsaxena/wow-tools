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
| T3 | M1 | wow-tools.sh parity, README FAQ, CHANGELOG; push | done | (this commit) | 9 new tests in test_launcher.py (3 structure tests on every platform, 6 `sh` tests POSIX-only); gate green: WSL 2007 OK (9 skipped), Windows 2007 OK (84 skipped), ruff clean, events.md current. Push left to the orchestrator |
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
