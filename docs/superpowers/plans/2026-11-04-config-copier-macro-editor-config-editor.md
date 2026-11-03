# Config Copier, Macro Editor, Config Editor and the launcher fix: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Resume at the first task not `done` in the ledger, `2026-11-04-config-copier-macro-editor-config-editor.status.md`.

**Goal:** Ship the launcher fix (window stays open, every launch and pre-log failure logged) and three new suite
tools: Config Copier (#14), Macro Editor (#12) and Config Editor (#13), with the shared core, UI and an offline
knowledge base they need.

**Architecture:** Each tool is a package under `wowtools/tools/` built exactly like the existing five
([adding-a-tool.md](../../adding-a-tool.md) is the recipe; the Saved Variables Browser is the closest worked
example). Byte-exact parsers for `macros-cache.txt` and `config-cache.wtf`/`Config.wtf` live once in `core/`.
Every write goes through one client-file pipeline built by generalising the SavedVariables pipeline
(`core/sv_apply`, `core/sv_undo`). Static knowledge (CVars, macro reference, templates, recommendations) is JSON
under `wowtools/kb/`, read by `core/kb.py`, built by dev scripts under `scripts/`.

**Tech Stack:** Python 3.10+, stdlib + vendored Textual, `unittest` via `scripts/run_tests.py`, cmd.exe / POSIX sh.

**Spec:** [`../specs/2026-11-04-config-copier-macro-editor-config-editor-design.md`](../specs/2026-11-04-config-copier-macro-editor-config-editor-design.md)
(decision IDs `LN*`, `X*`, `CC*`, `ME*`, `CE*`, facts `V1`-`V5`). Read it before any task.

## Global Constraints

- All of [docs/standards.md](../../standards.md) and [CLAUDE.md](../../../CLAUDE.md). A change that would break a
  MUST stops the task and is reported; the only new accepted deviation is LN7 (launcher/bootstrap records written
  outside `log_event`).
- Python floor 3.10; every module starts with `from __future__ import annotations`; stdlib + `vendor/` only.
- `core/` never imports `textual`; no tool imports another tool; shared code in `core/` or `ui/`.
- Tests never touch a real WoW install or the network. Client files in tests are synthesized in
  `tests/fixtures.py` temp trees, never copied from the user's machine.
- Client files are bytes: CRLF kept, UTF-8 with `surrogateescape` for names; unchanged bytes stay identical.
- Never write `cache.md5` or `.old` files (V2).
- Every user-noticeable change gets a `CHANGELOG.md` line under `## [Unreleased]`, short, major features only.
- After any event registry change: `python3 scripts/gen_event_docs.py`, commit `docs/events.md`.
- Every task ends with the green gate (CLAUDE.md): `python3 scripts/run_tests.py --all` (or plain on WSL-only),
  `ruff check --no-cache .`, `python3 scripts/gen_event_docs.py --check`. Commit per task with the session's
  attribution lines; push after each milestone (M1-M5); never merge.
- Layout: design for 120x30, grow with the window, 80x24 must keep working; every tree screen has `x`/`c`, `/`
  filter, labelled `action_button`s, `Header()` + `BottomBar()`.

## Review Focus

1. A `macros-cache.txt` in a layout the reader doesn't know (LF-only, a missing final `END`, a `MACRO` layout from
   an older flavor, trailing garbage): shown read-only with a warning, never rewritten. Pinned in T11.
2. Non-ASCII names in paths and in file content (`Aellâ`, `Trâxex`, a body with `Dænerys`): round-trip
   byte-identical, tree labels show them correctly. Pinned in T5, T10, T11.
3. WoW for that flavor starts after the review opened: Apply refuses at run time, nothing written. Pinned in T6.
4. A target file changed on disk between review and Apply: that file is refused by the SHA-256 recheck, the rest of
   the run is still all-or-nothing per the pipeline's rules. Pinned in T6.
5. Config Copier edge files: target has no `config-cache.wtf` (merge = source preferences only, file created),
   source lacks a ticked file (pair shown "source has no file", not copied), empty source file. Pinned in T8, T9.

---

## M1: Launcher fix (LN1-LN8)

### Task 1: Bootstrap log writer and launcher events

**Files:**
- Modify: `wowtools/core/bootstrap.py`, `wowtools/__main__.py`, `wowtools/suite.py` (pre-log failure paths, LN3
  hints, trim at start), `wowtools/core/events.py` (register names)
- Modify: `docs/standards.md` (Documented deviations row, LN7), `docs/events.md` (generated)
- Test: `tests/test_bootstrap.py`, `tests/test_suite.py` (or the existing suite start test file)

**Interfaces:**
- Produces: `LAUNCHER_LOG: Path = REPO_ROOT / "logs" / "suite" / "launcher.log"`;
  `log_bootstrap_failure(where: str, problem: BaseException | str, *, path: Path = LAUNCHER_LOG, now: datetime | None = None) -> None`
  (appends one line `<ISO time> bootstrap.failed where=<where> type=<T> message=<m>` plus up to 10 indented
  traceback lines; creates `logs/suite/`; never raises); `trim_launcher_log(path: Path, retention_days: int, now: datetime) -> None`
  (drops lines whose leading ISO or `cmd.exe` date is older than `retention_days`; when no line's date parses, keeps
  the last 2000 lines; never raises). Registered events (all `info` except `bootstrap.failed`, `launcher.python_missing`,
  `launcher.python_too_old` = `error`): `launcher.started`, `launcher.exited`, `launcher.python_missing`,
  `launcher.python_too_old`, `bootstrap.failed`.

- [ ] **Step 1: Failing tests** in `tests/test_bootstrap.py`: `test_bootstrap_failure_appends_a_line` (temp path;
  line starts with an ISO time and contains `bootstrap.failed where=python_check message=`),
  `test_bootstrap_failure_never_raises` (path inside a file, not a folder → returns None),
  `test_trim_drops_old_lines_keeps_recent`, `test_trim_without_dates_keeps_last_2000`; in the suite tests:
  `test_lock_failure_is_logged_and_hints_the_folder` (lock path in an unwritable/nonexistent location → stderr
  contains "isn't writable" and "Program Files"; `launcher.log` gets `bootstrap.failed where=lock`),
  `test_old_python_logged` (`main()` with patched `check_python` → `bootstrap.failed where=python_check`).
- [ ] **Step 2:** run `python3 scripts/run_tests.py -k bootstrap` → FAIL.
- [ ] **Step 3:** implement; `__main__.main` wraps everything before `init_event_log` and logs uncaught exceptions
  there (`where="startup"`) before re-raising; `suite.run` calls `trim_launcher_log` after the config loads.
- [ ] **Step 4:** add the LN7 row to Documented deviations (Rule `STD-6.1, STD-6.6`; what differs; why: nothing
  else can log before Python or before the log opens; Decided: LN7 in the spec). Regenerate `docs/events.md`.
- [ ] **Step 5:** gate, commit `feat(launcher): log pre-log failures to logs/suite/launcher.log (LN3, LN5, LN7)`.

### Task 2: `wow-tools.cmd`: Python check, launch log, pause on failure

**Files:** Modify `wow-tools.cmd`; Test `tests/test_launcher.py` (extend; Windows-only tests skip elsewhere as today).

**Interfaces:** Consumes the line shape and event names of Task 1. Log lines: `%date% %time% launcher.started
args=<%*> python=<cmd>`, `… launcher.exited code=<n>`, `… launcher.python_missing`, `… launcher.python_too_old found=<x.y>`.

- [ ] **Step 1: Failing tests:** `test_double_click_pauses_on_failure` (run through `cmd /c` with the script name
  in the command line and a fake package exiting 3; stdin supplies a key; output contains the pause prompt),
  `test_terminal_run_does_not_pause` (run as `cmd /c call wow-tools.cmd` from a shell whose `cmdcmdline` lacks the
  name → no pause), `test_launch_and_exit_logged` (`logs/suite/launcher.log` in the temp copy gets a started and an
  exited line with `code=3`), `test_missing_python_message` (PATH without python/py → message names README
  "Installing Python", `launcher.python_missing` logged, exit not 0), and the existing F-020 structure test must
  still pass (Python started on the last non-comment line, nothing after it reads the file).
- [ ] **Step 2:** run `python3 scripts/run_tests.py --windows -k launcher` → FAIL.
- [ ] **Step 3:** implement. Detection: `echo "%cmdcmdline%" | findstr /i /c:"%~nx0" >nul` together with `/c` →
  `WOWTOOLS_DBLCLICK=1`. Version probe: `%WOWTOOLS_PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 3)"`
  (9009 or not found = missing, 3 = too old; print `found=` via a second `-c` only when it ran). Log writes are
  `>>"%WOWTOOLS_LOG%" 2>nul` so an unwritable folder is silent. The last line gains, after the saved exit code,
  the exited log write and `if !WOWTOOLS_RC! neq 0 if defined WOWTOOLS_DBLCLICK pause`, then `exit /b`.
- [ ] **Step 4:** gate (`--all`), commit `fix(launcher): wow-tools.cmd checks Python, logs launches, pauses on failure (LN1, LN2, LN4)`.

### Task 3: `wow-tools.sh` parity, README FAQ, CHANGELOG

**Files:** Modify `wow-tools.sh`, `README.md` (FAQ rows), `CHANGELOG.md`, `docs/architecture.md` (Layers note);
Test `tests/test_launcher.py` (POSIX part).

- [ ] **Step 1: Failing tests:** `test_sh_logs_start_and_exit` (temp copy, fake package exit 3 → two lines, exit 3
  propagated), `test_sh_missing_python3` (PATH without python3 → message + `launcher.python_missing`, exit 127),
  `test_sh_body_parsed_before_running` (the script's commands are inside one `main` function or `{ }` block called
  on its last line: rewrite-while-running test like F-020).
- [ ] **Step 2:** run → FAIL. **Step 3:** implement (no `exec`; `trap` not needed: exit code captured with `$?`).
- [ ] **Step 4:** README FAQ: "The window flashes and closes" row (run it from a terminal to read the message;
  look in `logs/suite/launcher.log`) and the folder-not-writable row; CHANGELOG `### Fixed` line.
- [ ] **Step 5:** gate, commit; **push branch (milestone M1).**

---

## M2: Shared core, UI and the dump addon

### Task 4: Dump addon and refresh scripts (user step follows)

**Files:**
- Create: `scripts/kb_dump/KaosKbDump/KaosKbDump.toc`, `scripts/kb_dump/KaosKbDump/KaosKbDump.lua`,
  `scripts/kb_dump/README.md` (how to install, `/kbdump`, where the SavedVariables lands, one run per flavor)
- Create: `scripts/refresh_kb.py` (reads dumps, writes `wowtools/kb/cvars/<flavor>.json` and
  `wowtools/kb/slash_commands/<flavor>.json`; `--wiki` layers rewritten wiki text from a reviewed
  `scripts/kb_dump/wiki_notes.json`, see Task 20)
- Test: `tests/test_refresh_kb.py` (synthesized dump `.lua` in a temp tree)
- Modify: `docs/releasing.md` / `RELEASE_STAYS_OUT` only if `scripts/` handling needs it (it is already "stays out").

**Interfaces:**
- Dump SavedVariables `KaosKbDumpDB = { build = "<version> <build>", flavor = "<project id>", cvars = { [name] = {
  help=, category=, default=, value=, account=bool, character=bool, locked=bool, secure=bool, readonly=bool } },
  commands = { [slash] = "<SlashCmdList key>" } }` from `C_Console.GetAllCommands()` (commandType == CVar),
  `C_CVar.GetCVarInfo`, `SLASH_*` globals.
- Produces JSON schema `cvars/<flavor>.json`: `{"flavor": "_retail_", "build": "...", "source": "client dump _retail_ <build>",
  "cvars": {"<name>": {"default": str, "help": str, "category": str, "scope": "machine"|"account"|"character", "synced": bool,
  "locked": bool, "readonly": bool}}}`; `slash_commands/<flavor>.json`: `{"flavor":..., "build":..., "commands": {"/cast": "CAST", ...}}`.
  `refresh_kb.py main(argv) -> int`, `--wow PATH` (finds each flavor's dump under its `WTF/Account/*/SavedVariables/KaosKbDump.lua`), `--out DIR`.

- [ ] **Step 1:** failing tests `test_dump_to_cvar_json` (scope: account flag → "account", character flag →
  "character", neither → "machine"; default and help copied; source names flavor and build),
  `test_dump_to_slash_json`, `test_missing_dump_flavor_skipped_with_message`. Parse dumps with `core/luasv`.
- [ ] **Step 2-4:** run → FAIL, implement, PASS. Lua is not unit-tested; keep it under 150 lines, no libraries.
- [ ] **Step 5:** gate, commit. **Then stop and tell the user** (ledger status `waiting-user`): install
  `scripts/kb_dump/KaosKbDump` into each flavor's `Interface/AddOns`, log in once per flavor, `/kbdump`, log out.
  Work continues with T5 onward; T20 needs the dumps.

### Task 5: Install helpers: Forever name, real characters

**Files:** Modify `wowtools/core/install.py`; Test `tests/test_install.py`.

**Interfaces:** Produces `FLAVOR_NAMES["_forever_"] = "Forever"`; `is_character_name(name: str) -> bool` (non-empty,
every char `str.isalpha()`); `Account.real_characters() -> list[Character]` (filters `characters()` by
`is_character_name`, same order). `characters()` unchanged (X3).

- [ ] Tests: `test_forever_display_name`, `test_character_name_rules` (`Aellâ`, `Trâxex` true; `Testwarrka - Copy`,
  `Bob2`, `` false), `test_real_characters_skips_copies`, `test_characters_unchanged_includes_copies`. Run → FAIL →
  implement → PASS → gate → commit.

### Task 6: Client-file write pipeline (X5)

**Files:**
- Create: `wowtools/core/client_apply.py`
- Modify: `wowtools/core/sv_apply.py`, `wowtools/core/sv_undo.py`, `wowtools/core/svfiles.py` (guard made
  pluggable; SavedVariables behaviour unchanged), `wowtools/core/sv_journal.py` (a `created` entry)
- Test: `tests/test_client_apply.py`; the existing Ace3/SV Browser pipeline tests must pass unchanged.
- Modify: `docs/architecture.md` Core modules row.

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class ClientChange:
      path: Path                     # an account or character folder file of the flavor
      new: bytes
      expected_sha256: str | None    # None: the file must not exist yet (created by the run)

  class ClientFileGuard:             # accepts only `names`, directly in <flavor>/WTF/Account/<A>/ or …/<A>/<Realm>/<Char>/ (or WTF/Config.wtf when "Config.wtf" in names)
      def __init__(self, flavor: Flavor, names: frozenset[str]) -> None: ...
      def check(self, path: Path) -> Path: ...   # raises svfiles.SvFileError

  def apply_client_changes(tool: SvTool, flavor: Flavor, changes: Sequence[ClientChange], *,
                           names: frozenset[str], root: Path, journal_dir: Path, keep_journals: int,
                           keep_snapshots: int, dry_run: bool, wow_check: Callable[[], list[str] | None] | None,
                           now: datetime | None = None, progress: ApplyProgress | None = None) -> MultiApplyResult
  def undo_client_run(tool: SvTool, journal_path: Path, *, wow_root: Path, root: Path, keep_snapshots: int,
                      names: frozenset[str], wow_check=None, now=None, progress=None, parallelism: int = 1) -> UndoResult
  def recover_client_run(tool: SvTool, marker: Marker, *, wow_root: Path, root: Path, names: frozenset[str], **kw) -> UndoResult
  ```
  Same snapshot, originals zip, marker, journal, atomic write, read-back and roll-back as `apply_flavor`. A created
  file is journaled `created`; Undo deletes it only if still at its `sha_after`, and restores replaced files from
  the originals zip.
- Consumes: `apply_flavor`, `apply_flavors`, `undo_run`, `recover`, `SvTool`.

- [ ] Tests (temp WoW tree from `tests/fixtures.py`): `test_replace_and_create_then_undo` (one replaced, one created;
  undo restores bytes and deletes the created one), `test_dry_run_writes_nothing` (no journal, no zip, files
  unchanged), `test_refuses_when_wow_running` (wow_check returns a process → `WowRunning`, nothing written),
  `test_changed_on_disk_is_refused` (expected_sha256 stale → refused, nothing written),
  `test_created_file_already_exists_is_refused`, `test_guard_refuses_unlisted_and_outside` (`macros-cache - Copy.txt`,
  a `SavedVariables` file, `cache.md5`, a path outside `WTF/Account` all refused), `test_undo_skips_file_changed_since`,
  `test_recover_after_crash_marker`, `test_non_ascii_character_path_round_trip` (`Aellâ`).
- [ ] Run → FAIL → implement (generalise, don't fork; record the reason in the module docstring if any part had
  to be separate) → PASS; the full suite (Ace3, SV Browser) stays green → gate → commit.

### Task 7: Client file parsers: macros and CVars

**Files:** Create `wowtools/core/macrofile.py`, `wowtools/core/cvarfile.py`; Test `tests/test_macrofile.py`,
`tests/test_cvarfile.py`; `tests/fixtures.py` gains `macro_file_bytes(macros, newline=b"\r\n")` and
`cvar_file_bytes(pairs)`.

**Interfaces:**
```python
# macrofile.py
@dataclass(frozen=True)
class Macro:
    id: str          # 16 hex digits as written
    name: str
    icon: str        # file id or texture name, as written
    body: str        # lines joined with "\n"
    span: tuple[int, int]   # byte span of the whole VER..END block incl. its final newline
@dataclass(frozen=True)
class MacroFile:
    macros: tuple[Macro, ...]
    newline: bytes
    known_layout: bool      # False: read-only (Review Focus 1)
    problem: str | None
@dataclass(frozen=True)
class MacroChange:
    kind: Literal["add", "replace", "delete"]
    id: str
    name: str = ""
    icon: str = ""
    body: str = ""
def parse_macros(data: bytes) -> MacroFile
def apply_macro_changes(data: bytes, parsed: MacroFile, changes: Sequence[MacroChange]) -> bytes   # raises ValueError on unknown layout or id
def next_macro_id(parsed: MacroFile, scope: Literal["account", "character"]) -> str   # highest+1, prefix 00/01 (V5)
ACCOUNT_PREFIX = "00"; CHARACTER_PREFIX = "01"; NAME_LIMIT = 16; BODY_LIMIT = 255

# cvarfile.py
@dataclass(frozen=True)
class CvarLine:
    name: str
    value: str
    span: tuple[int, int]
@dataclass(frozen=True)
class CvarFile:
    lines: tuple[CvarLine, ...]
    newline: bytes
    def get(self, name: str) -> str | None: ...
def parse_cvars(data: bytes) -> CvarFile        # lines that aren't SET lines are kept verbatim, not listed
def apply_cvar_changes(data: bytes, parsed: CvarFile, sets: Mapping[str, str], removes: Collection[str]) -> bytes
    # replace in place, remove lines, append new `SET name "value"` with the file's newline, keep all else
```
- [ ] Tests: `test_round_trip_unchanged_is_identical` (both), `test_parse_retail_layout` (V4 sample: id, name,
  icon number and texture name, multi-line body), `test_unknown_layout_read_only` (LF-only, missing END, `MACRO`
  layout, trailing junk → `known_layout False`, apply raises), `test_add_replace_delete_touch_only_their_blocks`,
  `test_next_id_account_and_character` (`…ED`→`00…EE`; empty character file → `0100000000000001`),
  `test_non_ascii_body_round_trip` (`Dænerys`), `test_cvar_set_replace_remove_append`, `test_cvar_value_with_quotes_kept`.
  Run → FAIL → implement → PASS → gate → commit.

### Task 8: Knowledge base loader and seed data

**Files:** Create `wowtools/core/kb.py`, `wowtools/kb/cvar_state.json`, `wowtools/kb/macro_limits.json`,
`wowtools/kb/README.md` (schema + sources rule); Test `tests/test_kb.py`.

**Interfaces:**
```python
@dataclass(frozen=True)
class CvarInfo:
    name: str; default: str | None; help: str; description: str; description_source: str
    category: str; scope: Literal["machine", "account", "character"] | None; synced: bool; source: str
def load_cvars(flavor_folder: str) -> dict[str, CvarInfo]        # {} when no data: everything "unknown"
def is_state_cvar(name: str) -> bool                              # cvar_state.json: names + fnmatch patterns
def macro_limits(flavor_folder: str) -> tuple[int, int]           # (account, character); Retail (120, 30); unknown flavor: Retail values, flagged by `limits_known(flavor)`
def limits_known(flavor_folder: str) -> bool
```
Later tasks add `load_macro_reference`, `load_templates`, `load_optimizer_rules`, `load_recommendations` to this
module. Every loader caches per process, never raises (bad JSON → empty, logs `kb.unreadable` (warning)).
- [ ] `cvar_state.json` holds the spec appendix's state reading (names and patterns). Tests:
  `test_state_list_matches_spec_appendix` (each state name/pattern from the appendix true; `assistedCombatHighlight`,
  `nameplateMaxScaleDistance`, `enableMultiActionBars`, `EJLootClass` false), `test_missing_flavor_data_is_empty`,
  `test_bad_json_is_logged_not_raised`, `test_macro_limits_retail`. Register `kb.unreadable`, regenerate events.
  Gate, commit.

### Task 9: Shared character tree for tick screens (X2)

**Files:** Create `wowtools/ui/character_tree.py`; Test `tests/test_character_tree.py`; Modify `docs/architecture.md` UI table.

**Interfaces:** `populate_characters(parent: TreeNode, flavor: Flavor, *, key: Callable[[Character], str],
label: Callable[[Character], str], disabled: Callable[[Character], str | None] = lambda c: None,
account_extra: Callable[[Account, TreeNode], None] | None = None) -> list[str]` (adds account › realm › character
nodes from `real_characters()`, returns the tick keys it added; a disabled character shows greyed with the reason and
has no tick key). Works with `ReviewTree` / `TickModel` / `TreeFilter` (ticking a parent ticks its children, as
the existing trees do).
- [ ] `TuiTestCase` tests: `test_tree_lists_accounts_realms_characters_without_copies`, `test_ticking_realm_ticks_its_characters`,
  `test_disabled_character_has_no_tick_and_shows_reason`, `test_non_ascii_labels`. Gate, commit; **push (M2).**

---

## M3: Config Copier (CC1-CC8)

### Task 10: Copy planning and the config merge

**Files:** Create `wowtools/tools/config_copier/{__init__,events,model,planner,merge}.py`; Test
`tests/test_config_copier_planner.py`, `tests/test_config_copier_merge.py`.

**Interfaces:**
```python
COPY_FILES = ("macros-cache.txt", "AddOns.txt", "chat-cache.txt", "config-cache.wtf", "layout-local.txt")  # CC3, in this order
@dataclass(frozen=True)
class PairPlan:
    target: Character; name: str
    status: Literal["new", "replace", "unchanged", "no-source"]
    new: bytes | None; old: bytes | None; old_sha256: str | None
    warnings: tuple[str, ...]        # CC7 macro warning
def plan_copy(source: Character, targets: Sequence[Character], names: Sequence[str]) -> list[PairPlan]
def merge_config(source: bytes, target: bytes | None) -> bytes   # CC5 using core.kb.is_state_cvar and core.cvarfile
MACRO_WARNING = "Action bar buttons that use macros may need placing again."
```
- [ ] Tests: `test_plain_files_copied_byte_for_byte`, `test_unchanged_when_identical`, `test_no_source_file_pair`,
  `test_empty_source_file_is_copied_as_empty`, `test_macro_warning_only_when_target_has_macros`,
  `test_merge_takes_source_preferences_exactly` (target-only `enableMultiActionBars` removed; source
  `assistedCombatHighlight` added), `test_merge_keeps_target_state` (target `savedClassConfigOne`, `hardTrackedQuests`,
  `closedInfoFrames` kept with target values; source's not copied), `test_merge_without_target_file`
  (= source preferences only), `test_merge_is_identity_when_same_preferences` (target bytes unchanged). Register
  `copier.*` events as needed (prefix `copier.`). Gate, commit.

### Task 11: Copier run, undo and the flow

**Files:** Create `wowtools/tools/config_copier/{runner,journal,undo,report,help,settings,app,review_screen,source_screen,diff_screen}.py`;
Modify `wowtools/tools/__init__.py` (register `Tool("config-copier", "Config Copier", "Copy a character's macros, chat, layout, CVars and enabled addons to other characters.", …)`);
Test `tests/test_config_copier_run.py`, `tests/test_config_copier_app.py`.

**Interfaces:** Consumes T6 `apply_client_changes` / `undo_client_run` / `recover_client_run` with
`names=frozenset(COPY_FILES)`, T9 tree, T10 planner. Flow: FlavorScreen (All flavors allowed) → source picker
(the T9 tree, single choice) → review: left pane (files as ticks, ticked by default; buttons Copy, Dry run, Undo,
Diff), tree = targets (T9; other flavors' characters greyed "other flavor", source greyed "source") with each
target expanding to its file pairs and their status; dropping a pair = unticking it; Diff opens a side-by-side or
unified diff screen for a replaced pair (config pairs mark state lines "kept"). Confirm popup (`kind="overwrite"`)
lists the CC7 warnings in `listed=`; result screen on `ResultBase`.
- [ ] Tests: `test_copy_to_two_targets_byte_identical`, `test_unticked_pair_left_alone`, `test_dry_run_changes_nothing`,
  `test_undo_restores_and_removes_created`, TUI: `test_flow_source_targets_review_copy`, `test_diff_screen_for_replaced_pair`,
  `test_other_flavor_targets_greyed`, `test_macro_warning_in_confirm`. Add the tool to every meta-test table
  (adding-a-tool step 4). Gate, commit.

### Task 12: Copier docs

**Files:** Create `docs/config-copier.md` (guide: V1/V2 facts in plain words, the five files, merge rule, the
macro warning, safety), `docs/internals/config-copier.md`; Modify README (tools table, guide link, config file),
`CLAUDE.md` (tool line and doc links), `docs/architecture.md` (Tools, config schema, documentation map),
`docs/releasing.md` + `RELEASE_SHIPS` (guide), `CHANGELOG.md`. Test: `tests/test_docs.py`, `tests/test_release_contents.py` pass.
- [ ] Write, gate, commit; **push (M3).**

---

## M4: Macro Editor (ME1-ME14)

### Task 13: Macro model, operations and paste rules

**Files:** Create `wowtools/tools/macro_editor/{__init__,events,model,scanner,ops}.py`; Test
`tests/test_macro_editor_ops.py`.

**Interfaces:**
```python
@dataclass(frozen=True)
class MacroSet:                       # one file
    flavor: Flavor; account: Account; character: Character | None   # None = account macros
    path: Path; parsed: MacroFile; data: bytes; sha256: str
    @property
    def scope(self) -> Literal["account", "character"]: ...
    @property
    def limit(self) -> int: ...       # core.kb.macro_limits
def scan_sets(flavor: Flavor) -> list[MacroSet]      # account file + each real character's file (missing file = empty set)
@dataclass
class Staged:                         # pending changes per set path
    changes: dict[Path, list[MacroChange]]
ClashChoice = Literal["skip", "rename", "overwrite"]
def stage_paste(staged: Staged, macros: Sequence[Macro], target: MacroSet, on_clash: Callable[[Macro, Macro], ClashChoice]) -> list[str]  # returns refusals (slots full)
def stage_replace_text(staged: Staged, picks: Sequence[tuple[MacroSet, Macro]], find: str, replace: str, *, case: bool) -> int
def stage_edit(...), stage_new(...), stage_delete(...)
def rename_for_clash(name: str, taken: Collection[str]) -> str   # "Name 2", cut to 16 chars
def build_changes(staged: Staged, sets: Sequence[MacroSet]) -> list[ClientChange]   # via apply_macro_changes
```
- [ ] Tests: `test_paste_new_gets_next_id_and_prefix`, `test_paste_overwrite_keeps_target_id` (ME6),
  `test_paste_rename_cuts_to_16`, `test_paste_refused_when_slots_full`, `test_edit_keeps_id`,
  `test_replace_text_counts_and_previews`, `test_replace_over_255_is_refused_for_that_macro`,
  `test_build_changes_byte_exact_elsewhere`, `test_cross_flavor_paste_allowed`. Gate, commit.

### Task 14: Macro reference, explainer, optimizer, templates data

**Files:** Create `wowtools/kb/macro_reference.json` (conditionals, `@unit` targets, command help; each entry
`source` URL + `flavors` list or `null` = not stated), `wowtools/kb/macro_templates.json`,
`wowtools/kb/optimizer_rules.json`; Create `wowtools/tools/macro_editor/{syntax,explain,optimizer,templates}.py`;
Modify `wowtools/core/kb.py` (`load_macro_reference(flavor) -> MacroReference`, `load_templates() -> list[MacroTemplate]`,
`load_optimizer_rules() -> dict[str, RuleInfo]`); Test `tests/test_macro_editor_syntax.py`, `tests/test_macro_editor_optimizer.py`.

**Interfaces:**
```python
@dataclass(frozen=True)
class Token: kind: Literal["command", "condition_block", "condition", "unit", "text", "comment", "directive"]; text: str; start: int; end: int
def tokenize(body: str) -> list[Token]
def token_at(body: str, offset: int) -> Token | None
def explain_block(block: str, ref: MacroReference) -> str           # "[@mouseover,help,nodead]" → "Cast on the unit under the mouse, if it's friendly and not dead."
def unknown_terms(body: str, ref: MacroReference) -> list[str]      # ME5: commands absent from the flavor's slash dump; conditionals whose flavors exclude it
def suggestions(body: str, offset: int, ref: MacroReference) -> list[tuple[str, str]]   # (completion, short help)
@dataclass(frozen=True)
class Rewrite: rule: str; before: str; after: str; reason: str; source: str
def optimize(body: str) -> tuple[str, list[Rewrite]]                # only rules in optimizer_rules.json
@dataclass(frozen=True)
class MacroTemplate: id: str; title: str; body: str; placeholders: tuple[str, ...]; source: str
def fill_template(t: MacroTemplate, values: Mapping[str, str]) -> str
```
Data rules: wiki text rewritten in our own words with the URL (X7, builder check Q2); templates ≥ 10 covering
mouseover heal, cursor ground-target, focus interrupt, self-cast fallback, stop-casting interrupt, modifier
alternate, trinket+spell, pet attack, target-of-target help, mount (each `source`). Optimizer rules at least:
`target=`→`@`, drop spaces after `,`/`;`/inside `[]`, `/use`↔`/cast` shortening, duplicate condition removal,
`#showtooltip <same spell>` → `#showtooltip`; each with a test proving the input and output are equivalent per
the rule's stated reason.
- [ ] Tests: `test_tokenize_click_cast_macro`, `test_explain_mouseover_help_nodead`, `test_unknown_terms_flags_missing_command`,
  `test_unknown_terms_silent_when_flavor_not_stated`, `test_suggestions_after_at`, one test per optimizer rule,
  `test_optimize_never_changes_spell_text`, `test_templates_have_sources_and_placeholders`, `test_reference_entries_have_sources`.
  Gate, commit.

### Task 15: Browse screen, apply and undo

**Files:** Create `wowtools/tools/macro_editor/{runner,journal,undo,report,help,settings,app,review_screen,edit_actions,popups}.py`;
Modify `wowtools/tools/__init__.py` (register `Tool("macro-editor", "Macro Editor", "Browse, edit, copy and paste macros across characters, accounts and flavors.", …)`);
Test `tests/test_macro_editor_app.py`, `tests/test_macro_editor_run.py`.

**Interfaces:** Consumes T6 (`names=frozenset({"macros-cache.txt"})`), T9, T13. Screen per ME2 and the agreed
mockup (spec, "Browse screen"): left pane search box with names/bodies ticks and "show all / matching", buttons
New, Edit, Delete, Copy, Paste…, Replace text…, Apply, Dry run, Undo; tree (flavor ›) account › Account macros
`n/limit` and realm › character `n/limit` › macros `name · first line · n/255`; pending changes marked as in the
SV Browser. Paste… opens a review popup with clashes (skip/rename/overwrite + apply to all), slot refusals and,
for a cross-flavor paste, the warning plus `unknown_terms`. Delete's confirm carries the ME6 action-bar warning.
Unknown-layout files show read-only with a warning (`WarningsHost`).
- [ ] Tests: `test_browse_lists_sets_with_slot_counts`, `test_search_bodies`, `test_copy_paste_to_two_characters`,
  `test_clash_overwrite_keeps_id_end_to_end`, `test_cross_flavor_paste_warns`, `test_apply_dry_run_undo`,
  `test_unknown_layout_read_only`. Meta-test tables. Gate, commit.

### Task 16: Edit screen, builder, optimizer and template popups

**Files:** Create `wowtools/tools/macro_editor/{edit_screen,builder_popup,optimize_popup,template_popup,reference_screen}.py`;
Test `tests/test_macro_editor_edit.py`.

**Interfaces:** Consumes T14. Edit screen per ME8 and the agreed mockup: name (max 16), icon (free text, default
`134400`), scope label, `n / 255` meter (Save disabled above 255), `TextArea` with a suggestion list (Tab/Enter
accepts) and a help panel that follows the cursor (`token_at`, `explain_block`). Keys: `b` builder (ME9:
radio/checkbox popup filled from the block under the cursor; OK rewrites that block or inserts a new one), `o`
optimize (diff + reasons, Apply/Cancel), `t` template (pick, fill placeholders, insert), `F1` reference screen.
Builder fields: target (none, @mouseover, @cursor, @focus, @target, @player, @targettarget), unit (help, harm,
either), states (dead/nodead, combat/nocombat, exists, mod:shift/ctrl/alt, channeling, stealth, mounted, flying,
indoors/outdoors), all from `macro_reference.json`.
- [ ] Tests: `test_meter_blocks_save_over_255`, `test_name_cut_at_16`, `test_help_panel_follows_cursor`,
  `test_builder_round_trip_block`, `test_optimize_apply_updates_text`, `test_template_fill_inserts`,
  `test_80x24_still_usable`. Gate, commit.

### Task 17: Macro Editor docs

As Task 12 for `macro-editor` (guide covers V4/V5 in plain words: IDs, action bars, why overwrite keeps the ID;
cross-flavor warning; templates and optimizer; spell names are not checked). Gate, commit; **push (M4).**

---

## M5: Config Editor (CE1-CE8)

### Task 18: Config model and edits

**Files:** Create `wowtools/tools/config_editor/{__init__,events,model,scanner,ops}.py`; Test `tests/test_config_editor_ops.py`.

**Interfaces:**
```python
@dataclass(frozen=True)
class ConfigTarget:
    flavor: Flavor; level: Literal["machine", "account", "character"]
    account: Account | None; character: Character | None
    path: Path; data: bytes | None; parsed: CvarFile | None; sha256: str | None
def scan_targets(flavor: Flavor) -> list[ConfigTarget]   # WTF/Config.wtf, each account and real character config-cache.wtf
@dataclass(frozen=True)
class Row:
    name: str; value: str | None; default: str | None; changed: bool | None   # None: unknown default
    info: CvarInfo | None; scope_mismatch: bool
def rows(target: ConfigTarget, cvars: Mapping[str, CvarInfo], *, show_all_known: bool, category: str | None,
         changed_only: bool, search: str) -> list[Row]
@dataclass
class ConfigStaged:
    sets: dict[Path, dict[str, str]]; removes: dict[Path, set[str]]
def stage_set / stage_remove / stage_reset (= remove, CE5) / stage_toggle (booleans "0"/"1")
def build_changes(staged: ConfigStaged, targets: Sequence[ConfigTarget]) -> list[ClientChange]
CATEGORIES = ("graphics", "sound", "interface", "camera", "nameplates", "combat text", "network", "other")
def category_of(info: CvarInfo | None, name: str) -> str   # X8 mapping: client category + name prefixes (nameplate*, camera*, floatingCombatText*/*CombatText*)
```
- [ ] Tests: `test_scan_three_levels`, `test_rows_set_and_known`, `test_changed_from_default`, `test_unknown_cvar_row`,
  `test_toggle_boolean`, `test_reset_removes_line`, `test_scope_mismatch_flag`, `test_category_mapping`,
  `test_build_changes_byte_exact_elsewhere`. Gate, commit.

### Task 19: Recommendations data

**Files:** Create `wowtools/kb/recommendations.json` (`[{"cvar", "value", "flavors", "reason", "source"}]`, a few
dozen across nameplates, camera, combat text, graphics, interface; every entry with a real source URL, researched
with web search; none unsourced); Modify `core/kb.py` (`load_recommendations(flavor) -> list[Recommendation]`);
Test in `tests/test_kb.py`: `test_recommendations_all_sourced_and_known_cvars` (each `cvar` exists in that
flavor's CVar data when the data exists). Gate, commit.

### Task 20: CVar base from the dumps plus wiki notes

Needs the user's dumps (Task 4). If any flavor is missing when this task starts, ask the user once; build with the
dumps present and leave the rest "unknown".
**Files:** run `scripts/refresh_kb.py`; Create `scripts/kb_dump/wiki_notes.json` (plain-English descriptions in our
own words for CVars whose Blizzard help is empty or cryptic, each with its warcraft.wiki.gg URL; prioritise the
CVars the issue's categories and the recommendations touch); commit `wowtools/kb/cvars/*.json`,
`wowtools/kb/slash_commands/*.json`. Test: `tests/test_kb.py::test_retail_base_covers_the_client_list`
(every CVar in the committed Retail dump-derived file has default, scope and source; descriptions carry a source).
Gate, commit.

### Task 21: Config Editor screens, apply and undo

**Files:** Create `wowtools/tools/config_editor/{runner,journal,undo,report,help,settings,app,review_screen,edit_actions,popups}.py`;
Modify `wowtools/tools/__init__.py` (register `Tool("config-editor", "Config Editor", "See and change CVars in Config.wtf and every account and character config, with help for each.", …)`);
Test `tests/test_config_editor_app.py`, `tests/test_config_editor_run.py`.

**Interfaces:** Consumes T6 (`names=frozenset({"Config.wtf", "config-cache.wtf"})`), T9, T18, T19. Screen: left
pane filters (category select, changed-only tick, show-all-known tick, search) and buttons Set, Add, Remove,
Reset, Recommend…, Apply, Dry run, Undo; tree (flavor ›) Config.wtf / account › account config / realm ›
character config, a file node expanding to its CVar rows (`name = value (default …) ✱changed`); `Space` on a
boolean row toggles it (staged); a help panel under the tree (or the right column at ≥ 160 cols) shows CE4's
details. Recommend… lists applicable recommendations for the selected file with reason and source, tick and
stage as a batch. Scope mismatch warns in the confirm (`listed=`).
- [ ] Tests: `test_tree_three_levels`, `test_toggle_and_apply`, `test_reset_to_default_and_undo`,
  `test_recommend_batch_staged`, `test_unknown_cvar_editable_labelled`, `test_dry_run_changes_nothing`. Meta-test
  tables. Gate, commit.

### Task 22: Config Editor docs

As Task 12 for `config-editor` (guide covers the three levels, synced CVars and V2 evidence, unknown CVars, where
descriptions and recommendations come from, how to report a revert). Gate, commit; **push (M5).**

---

## M6: Finish

### Task 23: Whole-branch review and release readiness

- [ ] Review `git diff master...HEAD` against the spec (fresh reviewer, most capable model); fix findings.
- [ ] `CHANGELOG.md` `[Unreleased]` holds: the launcher fix, three new tools (one line each), short.
- [ ] Green gate `--all`; push; check CI once (STD-10.2); ledger `done`; tell the user the branch is ready to merge.
  Never merge without the go-ahead. After the merge (user's go-ahead), delete this run's branches, stashes and
  worktrees.
