# Testing

How the test suite runs, how it is laid out, the fixtures and helpers every test builds on, and what the meta-tests
enforce across the suite. The testing rules every change follows are the `STD-10.x` rules in
[standards.md](standards.md#10-testing); this page is the how-to behind them. Back to the
[architecture hub](architecture.md).

## Contents

1. [The green gate](#the-green-gate)
2. [CI](#ci)
3. [Test layout](#test-layout)
4. [Fixtures: tests/fixtures.py](#fixtures-testsfixturespy)
5. [Textual tests](#textual-tests)
6. [The meta-tests](#the-meta-tests)
7. [Adding tests for a new tool](#adding-tests-for-a-new-tool)
8. [Timing races and skipped tests](#timing-races-and-skipped-tests)

## The green gate

Before every commit, the three commands marked **gate** must pass ([STD-10.1](standards.md#10-testing)); the other
rows are ways to run the suite while you work.

| Command | What it does |
|---|---|
| **gate** `python3 scripts/run_tests.py --all` | From WSL: the WSL suite and the native Windows suite at the same time, each with half the default shards (12 each on 16 CPUs; or `-j N` each), each printed under its own `===== WSL (-j N) =====` / `===== Windows (-j N) =====` heading, then `WSL: OK, Windows: OK, in T s` and `OK` or `FAILED`. Exit code 0 only if both passed. About 175 s on the 16-CPU WSL `/mnt/d` machine (200 s at 8 shards each, 265 to 280 s before balanced shards), about what the two runs take one after the other (about 90 s and 80 s): the machine is CPU-bound. With no Windows Python, the plain run below is the gate and CI covers Windows before the merge ([below](#windows-from-wsl)). |
| `python3 scripts/run_tests.py` | The whole suite in parallel: 1.5 shards per CPU (at most 24; [below](#shard-count)), one process per shard, the tests dealt by recorded time ([below](#balanced-shards)). Exit code 0 only if every shard passed. About 90 s on WSL `/mnt/d` (100 s at one shard per CPU, 145 s round-robin). |
| `python3 scripts/run_tests.py --windows` | From WSL: the whole suite under the native Windows Python, in the same checkout, its output streamed as it comes; exit code that run's. About 80 s (100 s at one shard per CPU, 140 s round-robin). On native Windows it is the plain run; on Linux that is not WSL both `--windows` and `--all` fail with a message. |
| `python3 scripts/run_tests.py -k TEXT` | Only the tests whose id (`tests.test_wtf_app.SomeTest.test_name`) contains `TEXT`, e.g. `-k sv_browser` or `-k test_look_and_feel`. |
| `python3 scripts/run_tests.py -j N` | `N` shards instead of the default 1.5 per CPU. |
| `python3 scripts/run_tests.py --verbose-shards` | Also a line per shard before the summary: `shard i/N: T s, K tests, planned P s` (the time the cache predicted for it). Passed on with `--windows`, and to both sides of `--all`. |
| `python3 scripts/run_tests.py --timeout S` | Kill and fail a shard still running after `S` seconds (`0`: no limit). The default is 600 s per shard at `-j 4` or more, and proportionally more below that (1200 s at `-j 2`, 2400 s at `-j 1`; a one-shard run takes about 15 minutes on WSL `/mnt/d`). |
| `python3 -m unittest discover -s tests -t . -v` | The same tests, serially and verbose, in one process. Use it to read a failure's full output in order. |
| **gate** `ruff check --no-cache .` | Lint (settings in `ruff.toml`: Python 3.10 target, 120 columns, `vendor/` excluded). Not run in CI, so it is on you. |
| **gate** `python3 scripts/gen_event_docs.py --check` | Fails if `docs/events.md` is out of date with the event registries. Run `python3 scripts/gen_event_docs.py` (no flag) to regenerate it after changing a registry. `tests/test_docs.py` checks the same thing. |

`run_tests.py` adds `vendor/` to the path itself and pins each shard's output encoding to UTF-8, so it works the
same on Windows. A failing shard prints its whole unittest output under `===== shard i/N failed =====`; the last line
is `OK` or `FAILED` after a `Ran N tests in T s across J processes (...)` summary. A shard that hangs (say, a pilot
waiting on a worker that never finishes) is killed at its timeout, with every process it started, and reported as
`===== shard i/N timed out after S s in <test id> =====`, naming the test it was running, so a hang fails the run
with a name well before CI's 20-minute job timeout. A shard that hangs after its last test (say, a non-daemon thread
that keeps the interpreter alive) is reported as `timed out after S s after its tests finished`, and its tests still
count in the summary. Shard output goes to temp files, not pipes, so a child process a hung test left behind cannot
hold the run open on Windows.

### Balanced shards

Shards are balanced by recorded test time (spec F2). Each shard child gets its explicit list of test ids in a temp
file, times every test (from the end of the one before, so a class's `setUpClass` counts towards its first test) and
reports the times with its summary, with how many ids it read and any it did not find (a shard that did not run its
whole list fails the run); the runner merges the times into `.test-times-<platform>.json` at the repo root (`wsl`,
`linux` or `windows`; one file per platform, so the WSL and the Windows side of `--all` never clobber each other).
The files are gitignored (`.test-times-*.json`), so they are never committed and, untracked, never in a release. The
next run deals the tests longest first (ties by id), each to the least-loaded shard (ties to the lowest index); a
test with no recorded time counts as the median; each shard runs its tests in id order. A `-k` run uses the cache
too and updates only its own tests' times; a full run also drops the times of tests that are gone. With no cache, or
one that is unreadable, corrupt or of another version, the tests are dealt round-robin by id, silently, as before.
The same tests and cache always give the same shards. Just before the `Ran N tests` line the runner prints `Shard
times: fastest A s, slowest B s (balanced by recorded test times)` (or `(round-robin: no recorded test times yet)`).

Measured 2026-10-09 on the 16-CPU WSL `/mnt/d` machine, 16 shards, median of 3 runs (1945 to 1959 tests):

| Run | Round-robin | Balanced |
|---|---|---|
| WSL `run_tests.py` | 143.5 s (shards 62 to 144 s) | 99.8 s (shards 87 to 97 s) |
| `--windows` (Python 3.14) | 138.6 s (shards 58 to 139 s) | 97.3 s (shards 91 to 97 s) |
| `--all` (-j 8 each) | 269 to 283 s | 201.6 s (one run; shards 181 to 198 s) |

### Shard count

The default shard count was chosen by measurement (spec F3): 1.5 shards per CPU, at most 24 (`MAX_DEFAULT_JOBS`),
and `--all` gives each side half of that. The tests spend much of their time waiting (pilots, workers, file I/O),
so more shards than CPUs pay, up to a point: 2 per CPU were no faster than 1.5, and the cap keeps a big machine from
starting dozens of Textual processes. Measured 2026-10-09 on the 16-CPU WSL `/mnt/d` machine with balanced shards,
median of 3 runs each (the runner's own `Ran N tests in T s`; 1962 to 1965 tests), shards of the median run:

| Run | One per CPU | 1.5 per CPU | 2 per CPU |
|---|---|---|---|
| WSL `run_tests.py` (-j 16 / 24 / 32) | 100.9 s (shards 96 to 98 s) | 87.5 s, 13 % faster (shards 80 to 85 s) | 87.3 s (shards 70 to 84 s) |
| `--windows` (Python 3.14; -j 16 / 24 / 32) | 99.6 s (shards 92 to 99 s) | 78.0 s, 22 % faster (shards 73 to 78 s) | 78.1 s (shards 70 to 78 s) |
| `--all` (-j 8 / 12 / 16 each) | 197.9 s (WSL shards 187 to 194 s, Windows 180 to 186 s) | 176.5 s, 11 % faster (WSL 160 to 173 s, Windows 149 to 154 s) | 177.9 s (WSL 150 to 174 s, Windows 143 to 152 s) |

### Windows from WSL

`--windows` and `--all` reach Windows through `cmd.exe` (spec F1): the runner turns the checkout into a Windows path
with `wslpath -w`, and `cmd.exe` runs `pushd <that path> && py -3 scripts\run_tests.py ...` with `-k`, `-j` and
`--timeout` passed through, so both suites test the same files. `py -3` is the newest Python the Windows `py`
launcher knows; set `WOWTOOLS_WINDOWS_PYTHON` to another command (say `py -3.13`, or a full path to `python.exe`)
to pick one. It goes into the `cmd.exe` line as written, so a path with spaces needs double quotes inside the value:
`WOWTOOLS_WINDOWS_PYTHON='"C:\Program Files\Python314\python.exe"'`. The `cmd.exe` line travels in the
`WOWTOOLS_WINDOWS_RUN` variable, shared through `WSLENV`, because WSL would escape the double quotes in an argument
in a way `cmd.exe` does not read; for the same reason a `-k` text cannot contain a double quote (a trailing
backslash is fine: it is doubled, as Windows argument parsing needs). `cmd.exe` starts from the checkout's own
drive (or `C:`), so it never warns about a UNC current directory, and `pushd` also reaches a checkout on
`\\wsl.localhost`. With no `cmd.exe` on `PATH` (WSL interop off) or a checkout `wslpath` cannot map, both flags
stop at once with a message and exit 2. A Windows run that fails without printing its summary, typically because
no Windows Python is installed, ends with a hint to set `WOWTOOLS_WINDOWS_PYTHON` or use the plain run. Ctrl+C
stops both suites: the Windows runner announces its pid and is killed with its shards by `taskkill.exe /T` (a
Ctrl+C before that line arrives waits up to 10 s for it), and the WSL runner gets SIGINT and kills its own shards.
The Windows suite skips about 79 POSIX- or WSL-only tests that the WSL suite runs.

## CI

`.github/workflows/tests.yml` runs on every push, every pull request and by hand (`workflow_dispatch`), with
read-only permissions and a 20-minute timeout per job ([STD-10.2](standards.md#10-testing)). The matrix is two
jobs, listed with `include` (spec F4):

| Job | `os` | `python` |
|---|---|---|
| Windows | `windows-latest` | `3.13` |
| Linux | `ubuntu-latest` | `3.10` (the floor) |

`fail-fast` is off, so both jobs finish. Nobody waits for CI during a build (spec F5): the local green gate already
runs the WSL and native Windows suites. It is checked once before asking to merge into master, and before a
release ([releasing.md](releasing.md#steps)). Each job runs, in bash:

1. `python -m compileall -q wowtools scripts tests` (byte-compile: catches syntax newer than the interpreter).
2. `python scripts/gen_event_docs.py --check`.
3. `python scripts/run_tests.py --timeout 900`: no `-j`, so the [default shard count](#shard-count) applies:
   6 shards on a 4-vCPU runner (4 before spec F3; 1.5 per CPU was measured only on the 16-CPU machine, so CI's
   timings are checked when CI is next checked, before the merge). CI's shards are dealt round-robin, not
   [balanced](#balanced-shards): each job starts from a fresh checkout, the `.test-times-*.json` files are
   gitignored and the workflow has no cache step, so there are no recorded times (locally round-robin's slowest
   shard took about 2.3 times its fastest). 900 s per shard, not the 600 s default, since a slow Windows runner has
   taken 594 s for one round-robin shard (of 4); a hang still fails with its test's name inside the 20 minutes. The
   Windows job's slowest shard at 6 shards is checked against 900 s and the job against 20 minutes before the merge.

Ruff is not part of CI (the suite stays stdlib-only); run it locally.

A second workflow, `.github/workflows/virustotal.yml`, runs no tests: it scans a release's zip on VirusTotal when
the release is published, or by hand (`workflow_dispatch`), and adds the report's line to the release notes
([releasing.md](releasing.md#steps), step 8). GitHub reads its file from the tagged commit on a release, and
from `master` for a run by hand, so a tag that predates it is scanned by hand only. It never runs on a push, so
the green gate and the two jobs above do not depend on it or on its `VT_API_KEY` secret.

## Test layout

Every test lives in `tests/test_*.py` and uses `unittest`. A tool's tests are named `test_<tool>_<module>.py`, with
`test_<tool>_app.py` for its screens ([STD-10.9](standards.md#10-testing)), so `-k <tool>` picks them out. The WTF
Cleaner's tests predate that rule: its logic tests are `test_cleaner.py`, `test_rules.py`, `test_safety.py` and
`test_scanner.py`, and its other tests use the `test_wtf_` prefix.

### Suite-wide rules (the meta-tests)

`test_structure.py`, `test_look_and_feel.py`, `test_help.py`, `test_docs.py`, `test_events.py`. See
[The meta-tests](#the-meta-tests).

### Shared core (`wowtools/core/`, no Textual)

| File | Covers |
|---|---|
| `test_backup.py` | `core/backup.py` |
| `test_core_shared.py` | `core/text`, `core/progress`, `core/marker`, `core/undo` and the shared journal and install helpers |
| `test_core_snapshot.py` | `core/snapshot.py` (the whole-WTF snapshot the WTF Cleaner and Ace3 Profile Manager take) |
| `test_core_svfiles.py` | `core/svfiles.py`: the guard, lock probe and probe-leftover recovery |
| `test_core_sv_pipeline.py` | The shared SavedVariables write pipeline: `sv_apply`, `sv_journal`, `sv_undo`, `sv_verify` |
| `test_luasv.py` | `core/luasv.py`, the SavedVariables reader with byte spans |
| `test_fsutil.py` | `core/fsutil.py`: atomic writes, no-replace renames, free names |
| `test_no_replace_call_sites.py` | Every rename into a final name refuses an existing target |
| `test_journal.py` | `core/journal.py` |
| `test_parallel.py`, `test_parallel_runs.py` | `core/parallel.py`, and every parallel run giving the same result at parallelism 1 and 4 |
| `test_config.py`, `test_paths.py`, `test_install.py`, `test_process.py`, `test_lock.py`, `test_bootstrap.py`, `test_migrate.py`, `test_changelog.py` | The module of the same name (`test_changelog.py` also drives the changelog screen) |

### Shared UI (`wowtools/ui/`)

| File | Covers |
|---|---|
| `test_ui_base.py` | The app shell (`ui/base.py`): setup, account and flavor screens, the background update check, quit while busy, crash logging, brand text, action colours |
| `test_ui_review.py` | `ui/review.py`: the tick model, `ReviewTree`, the shared review machinery |
| `test_ui_tree_filter.py` | `ui/tree_filter.py`: the `/` filter |
| `test_ui_shared_screens.py` | The shared result screen, choice popup, settings form and `ToolFlow`, driven through toy screens |
| `test_ui_warnings.py`, `test_warnings_view.py` | The shared warnings view, then the same rules on every tool's review |
| `test_ui_widgets.py` | `action_button` and keys on buttons |
| `test_dialogs.py`, `test_progress_popup.py` | `ui/dialogs.py`; the progress popup and its `ProgressBoard` |
| `test_flavor_screen.py` | `ui/flavor_screen.py` |
| `test_counted_list.py` | `CountedTree` (spec L10, STD-7.26): long lists in popups behind one counted row |
| `test_picker_keys.py` | The flavor and account pickers' keys in every tool |
| `test_risk_disclaimer.py` | The USE AT YOUR OWN RISK popup (`ui/disclaimer.py`) and its don't-show box in the three tools that show it |
| `test_scan_box_first.py` | A review shows its scan progress box at once, before any slow check (spec L6) |

### Suite, updater and release

| File | Covers |
|---|---|
| `test_suite.py`, `test_suite_app.py` | `wowtools/suite.py` (start-up, the instance lock, renamed-tool migration on start, the update at start) and `WowToolsApp` (menu, setup, opening tools) |
| `test_updater_check.py`, `test_updater_apply.py` | `core/updater.py`: the release check (fake openers, never the network) and applying an update |
| `test_release_scripts.py` | `scripts/build_release.py`, the hashed vendor lock, `scripts/run_tests.py`'s per-shard timeout, its `--windows` / `--all` runs (the `cmd.exe` call is faked), its shards balanced by recorded time (the cache in a temp folder) and its default shard count (and that this page's CI section names it for a 4-vCPU runner); and the CI workflow (`CiWorkflowTest`): exactly its two jobs, no doc still claiming the old CI matrix, CI's round-robin shards named in the workflow and this page, STD-10.2 naming both jobs and STD-10.1 pointing to it |
| `test_virustotal_scan.py` | `scripts/virustotal_scan.py` against a fake VirusTotal (fake opener and clock; no network, no real key): a finished report reused without an upload, upload then polls 15 s apart until completed, HTTP 429 backed off and retried, 401 / 403 / 413 / other errors, a missing key (no traceback, no request), a zip over 32 MB, the notes block appended then replaced (idempotent), `--block-file` then `--splice` (no key, no request), the detections line, the timeout (kept even when every request is slow; no request given longer than the time left), a dropped connection as a clean error; and `.github/workflows/virustotal.yml` (only on a published release or by hand, `contents: write` only, the key from `secrets.VT_API_KEY`, `SHA256SUMS` checked before the scan, the notes fetched only after it) |
| `test_release_contents.py` | The release manifest (STD-11.5): every tracked path is in a table of [releasing.md](releasing.md#what-a-release-contains), `.gitattributes` export-ignores the "stays out" table, `git archive` of `HEAD` holds exactly the "ships" table, no shipped Markdown file links to a file that does not ship (needs git; skips without it), the updater's `RELEASE_SHIPS` / `RELEASE_STAYS_OUT` are the two tables entry for entry, and its `MANAGED_DIRS` / `MANAGED_FILES` are the top-level "ships" names |
| `test_launcher.py` | `wow-tools.cmd` stays safe to replace while it runs (Windows-only parts skip elsewhere) |
| `test_quit_key.py`, `test_tool_menu_key.py`, `test_toast_stack.py` | The suite-wide walks: `q` and `t` from every screen and popup, toasts above the bars (see [below](#the-suite-wide-key-and-toast-walks)) |

### Per tool

| Tool | Files |
|---|---|
| WTF Cleaner | `test_wtf_app.py`, `test_wtf_journal.py`, `test_wtf_multi.py`, `test_wtf_undo.py`, `test_cleaner.py`, `test_rules.py`, `test_safety.py`, `test_scanner.py` |
| Screenshot Organizer | `test_screenshot_organizer_{app,naming,organizer,planner,report,settings,undo}.py` |
| Interface Backup | `test_interface_backup_{app,backup,catalog,folder,report,restore,scanner,settings,undo}.py` |
| Ace3 Profile Manager | `test_ace_{app,compile,editor,journal,model,multi,ops,report,scanner,settings,undo}.py` |
| Saved Variables Browser | `test_sv_browser_{app,apply,bulk,compile,edit,model,ops,run_ui,scanner,search,search_ui,skeleton}.py` |

## Fixtures: tests/fixtures.py

Every test builds its own synthetic WoW install in its own `tempfile.TemporaryDirectory()`; never a real install,
never a file shared with another test, since the parallel shards would collide
([STD-10.3](standards.md#10-testing)). The module docstring of `tests/fixtures.py` draws the full tree of each
builder.

### Builders

| Builder | Builds |
|---|---|
| `build_wow_tree(root)` | The base install: `_retail_` with installed, disabled, old and uninstalled addons, stray copies, two accounts and characters (one with a non-ASCII name); `_classic_era_` with Questie; `_anniversary_` with WTF only (a scan must abort); `_notaflavor` |
| `build_multi_account_tree(root)` | A retail install whose three accounts enable different addons (the per-account "not enabled" rule) |
| `build_solo_tree(root)` | One account with account-wide SavedVariables and no character folders |
| `build_screenshot_tree(root)` | Screenshots folders on top of `build_wow_tree`; `SHOT_BYTES` maps each valid shot name to its bytes |
| `build_interface_tree(root)` | Known bytes in `_retail_`'s Interface and WTF, and an empty `_ptr_` flavor |
| `build_ace_tree(root)` | A separate install with AceDB SavedVariables written byte-exact with CRLF (the `ACE_*` texts) |
| `build_sv_tree(root)` | A separate install for the Saved Variables Browser (the `SVB_*` texts): two flavors, two accounts, nested tables, numeric and boolean keys, escapes, a nil array slot, a `Blizzard_*` file, a `.bak` and a broken file |

`ace_lua(*lines)` makes SavedVariables text the way WoW writes it. `NOW`, `DAY`, `FRESH` and `OLD` are the ages the
builders stamp on files.

### Config

`make_config(directory, wow_root, **general)` saves a `wow-tools.cfg` that points at a fixture tree, picks `_retail_` as
the last flavor and turns update checks off, so no test reaches the network ([STD-10.4](standards.md#10-testing)). Extra
keyword arguments go into `[general]`. A tool's own settings go into `<config_dir>/<tool>.cfg` through
`Config(...).set(section, key, value, log=False)` and `save()`.

### Helpers

| Helper | Use |
|---|---|
| `await settle(app, pilot, timeout=30.0)` | Wait until workers are done, no rebuild or message is pending and every visible footer has recomposed. Call it after anything that starts work and before asserting. Past the timeout it fails, naming what was still busy (30 s: a loaded Windows CI runner needed more than 10 s after a clean) |
| `submit_filter(screen, text)` | Put text in a tree screen's filter box and submit it (typing alone never filters, spec D40); `settle` after it |
| `await accept_disclaimer(app, pilot)` | Accept the USE AT YOUR OWN RISK popup (`ui.disclaimer`, L4: WTF Cleaner, Ace3 Profile Manager, Saved Variables Browser) if it is showing |
| `stage_sv_edit(review)` | Stage one value edit on a Saved Variables Browser review, so Apply and Dry run have something to do |
| `await footer_keys(screen, pilot, wanted)` | The keys a screen's footer lists, once it lists every key in `wanted` (or the timeout passes) |
| `assert_keys_on_buttons(test, screen)` | Spec D17 on one screen: a button shows its action's key, a shown key works there, and the footer lists none of them |
| `with record_fsyncs(module=None) as calls:` | Record `("fsync", file size)` for every `os.fsync`, and with `module`, `("rename", source size)` for every call of that module's `rename_no_replace`: a test checks a file reached the disk before it was moved into place or counted (F-012) |
| `with cpu_seconds() as cpu:` | The process's CPU time inside the block (`time.process_time()`), in `cpu.seconds` once it ends: what a CPU-cost budget asserts on ([below](#timing-races-and-skipped-tests)) |

Logging is tested through `wowtools.core.events.capture_events()`, a context manager that swaps in a strict
in-memory event log and yields its records. An unregistered event then raises, and nothing is written to `logs/`
([STD-10.7](standards.md#10-testing)).

## Textual tests

### TuiTestCase

Every Textual test subclasses `tests.fixtures.TuiTestCase`, never `unittest.IsolatedAsyncioTestCase` directly
([STD-10.5](standards.md#10-testing)). Its `asyncSetUp` does two things:

- **Turns asyncio debug mode off.** `IsolatedAsyncioTestCase` runs its loop in debug mode, which times and logs every
  callback; Textual is many times slower under it (the class docstring measures about 15x, and the whole suite ran
  about 10x slower). No test needs it.
- **Patches `wowtools.ui.dialogs.CONFIRM_GUARD` to 0.** The real guard (0.25 s) ignores Enter or Space on a
  just-opened `ConfirmScreen`; with it off a test can answer a confirm at once. A test of the guard itself calls
  `self.confirm_guard(seconds)`; the patch puts the real value back afterwards.

### Driving the app

Tests drive the real app from the tool menu: build `WowToolsApp(cfg, config_dir=..., check_updates=False,
detect=list)` (the pattern in `test_screenshot_organizer_app.py`), open it with `async with app.run_test(size=...) as
pilot`, and press keys through `pilot`. Injected callables replace anything slow or system-dependent through
`tool_options`, e.g. `WowToolsApp(..., tool_options={"wtf-cleaner": {"wow_check": ..., "locker_check": list}})`.

Pass `notifications=True` to `run_test` when a test asserts on toasts: Textual's `run_test` defaults to
`notifications=False` and then shows none (see `test_toast_stack.py`, `test_ace_app.py` and
`test_sv_browser_app.py`).

### Sizes

`tests/fixtures.py` defines the terminal sizes. Use them rather than literals for anything about layout (see
[Look and feel and terminal size](architecture.md#look-and-feel-and-terminal-size)).

| Name | Size | Meaning |
|---|---|---|
| `BASE` | 120x30 | Windows Terminal's default window: the design target |
| `LARGE` | 160x45 | The window maximized: screens grow, popups and forms keep a readable width |
| `TINY` | 80x24 | Not a design target; it only has to keep working |

Some older tests use a roomier local size (`SIZE = (140, 50)` in `test_screenshot_organizer_app.py` and
`test_scan_box_first.py`) where the test is not about layout.

## The meta-tests

These five files check rules across the whole suite, mostly by reading the source or by opening every tool's screens;
the [suite-wide key and toast walks](#the-suite-wide-key-and-toast-walks) open every screen too. A rule they enforce is
listed in [standards.md](standards.md) with the test as its *Enforced by*.

### tests/test_structure.py

Reads the source of `wowtools`, `scripts` and `tests` with `ast`:

- **Layering:** `wowtools/core` never imports `textual`, `wowtools.ui` or `wowtools.tools`, and has no relative
  imports (`test_core_never_imports_textual`); importing every core module in a fresh process loads no Textual
  (`test_importing_core_loads_no_textual`); in a tool, only its front-end modules (`app.py`, `*_screen.py`,
  `*_actions.py`, `popups.py`, `tree_view.py`) import `textual`, `rich` or `wowtools.ui`
  (`test_only_front_end_modules_import_the_ui`, STD-1.7).
- **No cross-tool imports:** a tool never imports another tool, in any import form
  (`test_no_tool_imports_another_tool`, `test_the_import_check_sees_every_form`).
- **Single definitions:** shared helpers, classes and literals are defined once, in core or UI, and never copied
  into a tool: `test_shared_helpers_are_defined_once`, `test_literals_are_defined_once`,
  `test_tools_use_the_shared_helpers`, the SavedVariables reader, file model and write pipeline
  (`test_saved_variables_*`), the review machinery, tree filter, blacklist, dialogs, result screens, settings forms
  and flow steps, and the recovery of an unfinished SavedVariables Apply (`SvRecoveryActions`)
  (`test_review_machinery_lives_in_ui`, `test_sv_recovery_lives_in_ui`, `test_tree_filter_lives_in_ui`,
  `test_blacklist_helpers_and_key_are_shared`, `test_shared_dialogs_live_in_ui`,
  `test_result_choice_settings_and_flow_live_in_ui`, `test_lock_refusal_and_progress_close_are_shared`).
- **Action mixins:** the Ace3 and SV Browser review screens take their staging, blacklist and key-edit actions
  from per-tool `*_actions.py` mixins and never define them again (`test_review_screens_are_split_into_action_mixins`,
  STD-3.6).
- **Buttons:** only `action_button` builds a `Button` (`test_every_button_is_built_with_an_action_kind`); one label
  has one action kind everywhere (`test_same_label_same_colour`); a label never spells its key
  (`test_button_labels_never_spell_their_key`); every `ConfirmScreen` names its kind
  (`test_every_confirm_names_its_kind`).
- **Screens:** the `RiskBanner` is on exactly the destructive screens
  (`test_risk_banner_on_exactly_the_destructive_screens`); only `BottomBar` builds the footer and brand bar
  (`test_footer_and_brand_bar_only_in_the_bottom_bar`).
- **Modules:** every module has `from __future__ import annotations` (`test_every_module_has_the_future_import`);
  top-level `from wowtools... import` lines are sorted (`test_wowtools_imports_are_in_order`); removed names stay
  removed (`test_dead_code_is_gone`).

### tests/test_look_and_feel.py

Opens every tool's screens through the app (the tools in its `TOOLS` tuple) at `BASE`, `LARGE` and `TINY`:

- The review's left pane is the same in every tool, one focusable control per row, and its hint wraps only between
  items.
- The risk banner tops the left pane of the `DESTRUCTIVE_REVIEWS` and no other.
- Every tree screen has the `/` filter box; it waits for Enter or its button; a group's mark counts only what the
  filter shows; a filter matching nothing says so; `x` / `c` expand and collapse all.
- Result screens share one layout; settings forms and popups keep a readable width (`FORM_MAX_WIDTH`,
  `POPUP_MAX_WIDTH`, both 100) and fit at `BASE`.
- Keys are on the buttons and off the footer on every screen and popup (`assert_keys_on_buttons`), the footer lists
  no keys under a popup, and every footer key shows at `BASE`.
- The tool menu, changelog and brand bar (version, update notice) fit at `BASE` and keep working at `TINY` and below.
- The Ace3 Profile Manager's tree pane, guide and action bar keep their room at `BASE` and `LARGE`.
- `test_tiny_terminal_still_works`: at 80x24 every tool's settings, review and result screens open without raising
  and Tab reaches every control; nothing about the layout is asserted there.

`RUN_ACTION` names the action that reaches each tool's result screen without a running-WoW popup, and `PREPARE`
stages what a review needs first (the Ace3 Profile Manager and Saved Variables Browser run pending changes only).

### tests/test_help.py

Spec D18. Every registered tool (`wowtools.tools.TOOLS`) has help over 500 characters that links its guide
`docs/<tool>.md`; the suite help names every tool and links the README; every GitHub link in any help points at a
file in the repo. Through the app: `h` on the menu and the changelog opens the suite help, `h` on every screen of a
tool (flavor picker, account picker, review, settings, result, the Ace3 blacklist) opens that tool's help, and the
help names every button those screens show; `h` and `s` wait for the running-programs check; `h` types in a text
box; help and the footer still fit at `TINY`. It has its own `RUN_ACTION` and `PREPARE` tables.

### tests/test_docs.py

Keeps the docs in step with the code:

- `docs/events.md` equals what `scripts/gen_event_docs.py` renders now.
- The README names and links a guide `docs/<tool>.md` for every registered tool, carries the version badge, the
  terms of use word for word and a link to `CHANGELOG.md`; `CHANGELOG.md` has an entry for the current
  `__version__`.
- Each user guide carries the sections, keys and wording its spec requires (a needle list per tool, plus the
  `**Filter**` button, the `⚠ USE AT YOUR OWN RISK` banner and the `!` warnings view in every guide that has them).
- `docs/standards.md`, `docs/architecture.md` and the per-tool `docs/internals/*.md` name the shared pieces the
  tests list; `CLAUDE.md` names every tool and every link in it resolves.

When a doc moves or a section is renamed, update the matching needles here in the same commit.

### tests/test_events.py

The event log itself: the record envelope and the registry level (`test_record_has_envelope_fields_and_registry_level`);
an unregistered event raises in strict mode and becomes an error otherwise; a level can only be raised, never
lowered; a conflicting registration raises; every registered level is valid; the file sinks (one handle per file,
each line on disk at once, day rollover, per-tool folders, pruning, I/O failures disable the sink without raising);
and `capture_events()` swapping the global log ([STD-10.7](standards.md#10-testing)).

### The suite-wide key and toast walks

`tests/test_quit_key.py` (`q` quits from every screen and popup, STD-8.11), `tests/test_tool_menu_key.py` (`t` goes
back to the tool menu the same way, L11) and `tests/test_toast_stack.py` (toasts stack above the bars, STD-7.24) walk
every screen of every tool at `BASE` and `LARGE`. Each has its own `ACCOUNT_TOOLS`, `RUN_ACTION` and `PREPARE`
tables, which a new tool must join (STD-10.8).

## Adding tests for a new tool

The full checklist for a new tool is [adding-a-tool.md](adding-a-tool.md). For the tests
([STD-10.8](standards.md#10-testing)):

1. **A builder.** Add `build_<tool>_tree(root)` to `tests/fixtures.py` (or reuse `build_wow_tree` and add to it), and
   describe its tree in the module docstring.
2. **Logic tests.** `tests/test_<tool>_<module>.py` per logic module: scanner, planner or model, the writer, the
   journal, Undo, the report. Use temp folders, `make_config` and `capture_events()`. Write the failing test first
   and name the spec decision a test pins in its docstring ([STD-10.10](standards.md#10-testing)).
3. **Screen tests.** `tests/test_<tool>_app.py` with `TuiTestCase`, opening the tool from the menu through
   `WowToolsApp(..., tool_options={"<tool>": {...}})`, sizes from `tests/fixtures.py`, and `settle()` before each
   assert.
4. **The meta-test tables.** In `tests/test_look_and_feel.py`: add the tool to `TOOLS` and `RUN_ACTION`, to
   `DESTRUCTIVE_REVIEWS` if its review can destroy data, and to `PREPARE` if its run needs staged changes. In
   `tests/test_help.py`: `RUN_ACTION` and `PREPARE`. The suite-wide walks: `ACCOUNT_TOOLS` (if it has an account
   picker), `RUN_ACTION` and `PREPARE` in `tests/test_quit_key.py`, `tests/test_tool_menu_key.py` and
   `tests/test_toast_stack.py` (they index `RUN_ACTION[name]` for every tool: a tool left out fails with a `KeyError`);
   `ACCOUNT_TOOLS` in `tests/test_picker_keys.py`; and, for a tool with the USE AT YOUR OWN RISK popup, `TOOLS` and
   `RISK_EVENTS` in `tests/test_risk_disclaimer.py`. `test_help.py`'s text checks and `test_docs.py`'s README check pick
   a new tool up from the registry on their own.
5. **Docs needles.** If the tool's guide has required sections, add a test for them to `tests/test_docs.py`.
6. **Events.** Register the tool's events in `<tool>/events.py` and run `python3 scripts/gen_event_docs.py`.

## Timing races and skipped tests

No test is known to be flaky today. The races seen so far were all in Textual tests on slow machines (Windows CI,
16 shards on native Windows): a test read a footer before it recomposed, asserted before a worker or a tree rebuild
finished, or left `run_test` while a new screen was still mounting (`NoMatches` on `HeaderTitle`). Each was fixed in
the test with `settle()`, which now waits for workers, pending rebuilds, queued messages and stale footers, and
fails loudly at its timeout rather than passing on a half-drawn screen. If a TUI test fails only under the parallel
runner or only on Windows, look for a missing `await settle(app, pilot)` first.

A test that bounds how long work takes uses the right clock. A CPU-cost budget of in-process work (parsing,
compiling, searching a big file) measures the process's CPU time with `cpu_seconds()`, never wall time: the
`--all` gate runs the WSL and Windows suites at once on every CPU, and under that load wall time broke the 4 s budget
of `test_thousands_of_edits_in_one_file_compile_and_verify_quickly` while the work takes about 0.6 s of CPU. CPU
time is not load-proof under WSL either: a vCPU the Windows side holds back still counts as the process's CPU time
(that 0.6 s read 1.2 s with only the Windows suite running, and 11.5 s once under `--all`). So a budget keeps a wide
margin (11x to 35x for the four in `test_luasv.py`, `test_sv_browser_model.py` and `test_sv_browser_search.py`),
and a test that guards against quadratic work asserts on how the CPU cost grows instead: the compile test alternates
three 1000-edit and three 4000-edit runs, divides the fastest large run by the fastest small one and wants it under 8
(linear is 4, the quadratic code was 15). That ratio guards growth, not a constant-factor slowdown that stays linear;
that trade-off is accepted for its purpose (the M2 quadratic regression). Wall time (`time.monotonic()`) is only
for a bound on waiting (a worker, a subprocess, a timeout), which CPU time cannot see, and that bound is set against
the thing it guards: under the 5 s `slow_check` a UI-thread check would hold, under the 30 s sleep a killed process
would otherwise finish.

Some tests skip on purpose, with the reason in the decorator: POSIX-only behaviour (`chmod` read-only, hard links,
`EXDEV`), symlinks (they need privileges on Windows), Windows-only launcher tests, and a config-save stress test
Windows cannot run. On Linux the suite reports 2 skipped; on Windows more skip.
