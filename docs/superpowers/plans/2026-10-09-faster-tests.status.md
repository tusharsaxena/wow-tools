# Faster tests: status ledger

Plan: `2026-10-09-faster-tests.md`. Spec: `../specs/2026-10-09-faster-tests-design.md`.
Branch: `build/faster-tests`. Resume at the first task not marked `done`. Never merge without the user's go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| F0 | spec, plan, ledger | done | (this commit) | baseline: WSL ~100-120 s, native Windows 3.14 149 s (1925 tests, 79 skipped) |
| F1 | `--windows` and `--all` | done | (this commit) | 20 new tests in `test_release_scripts.py` (`RunTestsWindowsTest`, cmd.exe faked). After the review fixes (F1g) `--all` ran 1945 tests: WSL 0 failures, 2 skipped; Windows 0 failures, 79 skipped; 283 s. Before them: full suite 1940 tests: WSL 0 failures, 2 skipped; Windows 3.14 0 failures, 79 skipped. Wall times: plain WSL 148 s; `--windows` 141 s (and 147 s); `--all` (-j 8 each) 269 s, 279 s; `--all -j 16` 264 s. Back to back the two runs take about 289 s, so `--all` saves only about 10-25 s: the machine is CPU-bound, and halving the shards makes the round-robin's slowest shard the limit (F2/F3 to tune). Ctrl+C checked by hand on `--windows` and `--all`: no python.exe/py.exe or WSL runner left |
| F2 | balanced shards | todo | | |
| F3 | shard count by measurement | todo | | |
| F4/F5 | two-job CI; when CI is checked | todo | | |
| FR | review, gate, push, CI once | todo | | |

## Decisions taken during the build

- F1a: the cmd.exe line travels in `WOWTOOLS_WINDOWS_RUN` (shared through `WSLENV`) and cmd.exe runs
  `%WOWTOOLS_WINDOWS_RUN%`: WSL escapes double quotes inside an argument as `\"`, which cmd.exe keeps literally, so
  a quoted path or `-k` text could not be passed as an argument. A `-k` text with a double quote is refused (exit 2).
- F1b: `pushd` (not `cd /d`) so a checkout on `\\wsl.localhost` also works; cmd.exe starts in the checkout when it
  is on a Windows drive (`/mnt/<x>/`), else `/mnt/c`, so it never prints the UNC-cwd warning.
- F1c: Ctrl+C: the Windows runner prints its pid (hidden `--announce-pid`) and is killed with `taskkill.exe /T /F`;
  the WSL runner of `--all` gets SIGINT so it kills its own shards. Both runs are in sessions of their own.
- F1d: cmd.exe returns 1 (not 9009) when `py` is missing, so a Windows run that fails without a `Ran N tests`
  summary prints a hint naming `WOWTOOLS_WINDOWS_PYTHON` instead of keying on an exit code.
- F1e: `--all -j N` gives each suite N shards (not N split in two); without -j each gets half the CPUs.
  `--all` on native Windows is the plain run, like `--windows`. `--windows` streams its output; `--all` buffers each
  side and prints it under `===== WSL (-j N) =====` / `===== Windows (-j N) =====`, then one combined line.
- F1f: no CHANGELOG line: the runner is developer tooling, not a user-noticeable change (STD-11.1).
- F1g: review fixes, all seven taken. Windows unreachable (no `cmd.exe` on `PATH`, `wslpath` failing, `cmd.exe`
  failing to start) is `WindowsUnreachable`/`OSError`, caught in `main`: a message naming WSL interop and exit 2,
  checked before anything starts; under `--all` the side that raises stops the other at once (`wait` with
  `FIRST_EXCEPTION`, then `_kill_relays`). `_cmd_quote` doubles trailing backslashes (Windows argv rules), so a
  `-k` text ending in `\` reaches Windows unchanged. `--windows` now reads its run on a worker thread like `--all`,
  so a Ctrl+C that comes before the `@@runner-pid` line waits for it (up to `PID_WAIT`, 10 s, or until the run
  ends) and still kills the Windows tree with `taskkill.exe`; the relay's own KeyboardInterrupt handler (and its
  test with the unreaped child) went. A `WOWTOOLS_WINDOWS_PYTHON` path with spaces is documented to need double
  quotes inside the value rather than quoted by guesswork (a value can be a command with arguments). Ctrl+C at
  0.3 s and 1.5 s into `--windows` checked by hand: nothing left running on Windows.
