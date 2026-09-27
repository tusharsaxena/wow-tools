# Ka0s WoW Tools — Framework + WTF Cleaner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared `wowtools` framework (config, paths, install model, backup, event log, updater, Ka0s-themed Textual UI) and its first tool, the WTF Cleaner, with both a TUI and a CLI.

**Architecture:** A UI-free `wowtools/core` package plus UI-free tool logic (`scanner`, `rules`, `cleaner`, `report`), with thin front ends on top: Textual screens in `wowtools/ui` and `wowtools/tools/wtf_cleaner/app.py`/`review_screen.py`, and argparse in `cli.py`. `python -m wowtools` puts the committed `vendor/` folder on `sys.path` and then dispatches through `wowtools/suite.py`. Every module records what it does through one registered-event log (`core/events.py`).

**Tech Stack:** Python ≥ 3.10 (stdlib), Textual 8.2.8 and Rich 15 (vendored, pure Python), stdlib `unittest`/`IsolatedAsyncioTestCase` with Textual's `App.run_test()` pilot.

**Spec:** `docs/superpowers/specs/2026-09-27-wtf-cleaner-design.md`

## Global Constraints

- Python floor 3.10: every module starts with `from __future__ import annotations`. Don't use `datetime.UTC`, `tomllib`, `typing.Self` or `ExceptionGroup`.
- No third-party imports outside `vendor/`. `wowtools/core/*` and the tool logic modules (`scanner.py`, `rules.py`, `settings.py`, `cleaner.py`, `report.py`, `events.py`) never import `textual`.
- Config: `wow-tools.cfg` (INI) in the repo root. Logs: `logs/` in the repo root. Both are git-ignored.
- Stored paths are in Windows form under WSL (`G:\X` ⇄ `/mnt/g/X`) and go through `core/paths.py` only.
- Criteria are `not_installed`, `not_enabled`, `older_than`, `stray_copies`. Default: all on, and an item is flagged if any criterion matches. `max_age_days` defaults to 90. "Enabled" is global within a flavor.
- Never propose `Blizzard_*` or anything outside a `SavedVariables/` folder.
- Nothing is deleted unless the backup zip has been verified, or backup is explicitly off.
- Every event name is registered with a fixed level. A caller may only raise the level, never lower it.
- GitHub repo: `tusharsaxena/wow-tools`. Releases are tagged `vX.Y.Z`. The suite version is `wowtools.__version__` = `"0.1.0"`.
- Test command (from repo root): `python3 -m unittest discover -s tests -t . -v`. Tests never touch a real WoW install; they use `tests/fixtures.py`.
- Branding: the theme is named `ka0s`, the title is "Ka0s · WoW Tools", and the brand bar reads "Ka0s WoW Tools v<version>".
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Jyp6HKcwib9Yj1ntXn7tPT
  ```
  The commit commands below omit the trailer for brevity. Add it to every one.

## Review Focus

1. **Hand-edited config with bad values** (`max_age_days = soon`, `check_for_updates = maybe`, `log_level = loud`) must fall back to defaults, not crash. Pinned in Task 4 and Task 9.
2. **Odd file and character names** (`Chârb`, `Details.lua - Copy.bak`, `[Weird] Addon.lua`) must scan, display (no Rich-markup mangling) and clean correctly. Pinned in Task 8, Task 9 and Task 15.
3. **A backup destination that can't be written** (a file in the way, permissions) must mean exit code 4 or a TUI error, with every SV file still present. Pinned in Task 6, Task 10 and Task 13.
4. **An empty selection or empty proposal** must write no zip and create no backup folder, and the CLI must say "Nothing to clean." Pinned in Task 10 and Task 13.
5. **Launching from another working directory or through the wrappers** must resolve config, logs and vendor from the repo root, not the cwd. Pinned in Task 1, Task 4 and Task 13.

---

## File Map

| File | Responsibility |
|---|---|
| `requirements.txt`, `scripts/update_vendor.py`, `vendor/` | pinned, committed third-party libs |
| `wowtools/__init__.py` | `__version__` |
| `wowtools/__main__.py` | Python check + vendor path, then `suite.run` |
| `wowtools/suite.py` | dispatcher: tools, `update`, tool picker, session events, auto-update |
| `wowtools/core/bootstrap.py` | `REPO_ROOT`, `VENDOR_DIR`, `check_python`, `add_vendor_path` |
| `wowtools/core/paths.py` | WSL detection and path translation |
| `wowtools/core/events.py` | event registry, `EventLog`, sinks, `log_event`, `capture_events` |
| `wowtools/core/config.py` | `Config` (INI) + typed `[general]` accessors |
| `wowtools/core/install.py` | `WowInstall` → `Flavor` → `Account` → `Character`, `detect_installs` |
| `wowtools/core/backup.py` | verified zip backups with manifest |
| `wowtools/core/process.py` | is WoW running? |
| `wowtools/core/updater.py` | release check, `UpdateCheck`, `apply_update`, `run_update_command` |
| `wowtools/tools/__init__.py` | tool registry `TOOLS` |
| `wowtools/tools/wtf_cleaner/events.py` | wtf-cleaner event registry |
| `wowtools/tools/wtf_cleaner/scanner.py` | installed/enabled addons, SV grouping |
| `wowtools/tools/wtf_cleaner/rules.py` | `Criteria`, `evaluate` → `Proposal` |
| `wowtools/tools/wtf_cleaner/settings.py` | `[wtf_cleaner]` section ⇄ `CleanerSettings` |
| `wowtools/tools/wtf_cleaner/cleaner.py` | recheck, guard, backup, delete / simulate |
| `wowtools/tools/wtf_cleaner/report.py` | sizes, labels, text/JSON rendering |
| `wowtools/tools/wtf_cleaner/cli.py` | argparse front end + TUI launch |
| `wowtools/ui/theme.py`, `branding.py`, `base.py` | Ka0s theme, banner, brand bar, `Ka0sApp`, `UpdateScreen` |
| `wowtools/ui/setup_screen.py`, `flavor_screen.py`, `tool_picker.py` | shared screens |
| `wowtools/tools/wtf_cleaner/app.py` | `WtfCleanerApp`, `CleanerSettingsScreen` |
| `wowtools/tools/wtf_cleaner/review_screen.py` | `ReviewScreen`, `ConfirmScreen`, `ResultScreen` |
| `wtf-cleaner.cmd/.sh`, `wow-tools.cmd/.sh` | launch wrappers (the `wow-tools` pair opens the tool picker / `update`) |
| `tests/fixtures.py` | synthetic WoW tree + configured `Config` |
| `README.md`, `CLAUDE.md`, `docs/*.md`, `scripts/gen_event_docs.py` | documentation |

---

### Task 1: Scaffold, vendored libraries, bootstrap

**Files:**
- Create: `requirements.txt`, `scripts/update_vendor.py`, `.gitattributes`, `wowtools/__init__.py`, `wowtools/core/__init__.py`, `wowtools/core/bootstrap.py`, `tests/__init__.py`, `tests/test_bootstrap.py`
- Generate + commit: `vendor/`

**Interfaces:**
- Produces: `wowtools.__version__: str`; `bootstrap.REPO_ROOT: Path`, `bootstrap.VENDOR_DIR: Path`, `bootstrap.MIN_PYTHON = (3, 10)`, `bootstrap.check_python(version_info: tuple[int, ...] | None = None) -> str | None`, `bootstrap.add_vendor_path(vendor_dir: Path = VENDOR_DIR) -> None`.

- [ ] **Step 1: Create the pinned requirements and the vendor script**

`requirements.txt`:
```
# Pinned, pure-Python only. Rebuild vendor/ with: python3 scripts/update_vendor.py
textual==8.2.8
rich==15.0.0
Pygments==2.21.0
markdown-it-py==4.2.0
mdit-py-plugins==0.6.1
linkify-it-py==2.2.0
mdurl==0.1.2
platformdirs==4.12.0
typing_extensions==4.16.0
```

`scripts/update_vendor.py`:
```python
#!/usr/bin/env python3
"""Rebuild vendor/ from requirements.txt. Run from anywhere: python3 scripts/update_vendor.py"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
NATIVE_SUFFIXES = {".so", ".pyd", ".dll", ".dylib"}


def main() -> int:
    if VENDOR.exists():
        shutil.rmtree(VENDOR)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--target", str(VENDOR), "--no-compile",
         "--no-deps", "--only-binary=:all:", "-r", str(ROOT / "requirements.txt")],
        check=True,
    )
    shutil.rmtree(VENDOR / "bin", ignore_errors=True)
    for cache in list(VENDOR.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
    native = [p for p in VENDOR.rglob("*") if p.suffix.lower() in NATIVE_SUFFIXES]
    if native:
        print("vendor/ must be pure Python, but native files were installed:", file=sys.stderr)
        for path in native:
            print(f"  {path}", file=sys.stderr)
        return 1
    print(f"vendor/ rebuilt from {ROOT / 'requirements.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`.gitattributes`:
```
* text=auto
*.sh text eol=lf
*.cmd text eol=crlf
vendor/** -diff linguist-vendored
```

- [ ] **Step 2: Populate vendor/**

Run: `python3 scripts/update_vendor.py`
Expected: pip installs the 9 packages and the script prints `vendor/ rebuilt from …`. `ls vendor` shows `textual`, `rich`, `pygments`, `markdown_it`, `mdit_py_plugins`, `linkify_it`, `mdurl`, `platformdirs`, `typing_extensions.py` and their `*.dist-info` folders. If pip reports a missing dependency on import later, add the pin to `requirements.txt` and rerun.

- [ ] **Step 3: Write the failing tests**

`tests/__init__.py`:
```python
"""Test package: make vendored libraries importable, exactly like the launcher does."""
from wowtools.core.bootstrap import add_vendor_path

add_vendor_path()
```

`tests/test_bootstrap.py`:
```python
import sys
import unittest

from wowtools.core import bootstrap


class CheckPythonTest(unittest.TestCase):
    def test_rejects_old_python(self):
        message = bootstrap.check_python((3, 9, 18))
        self.assertIn("3.10", message)
        self.assertIn("3.9", message)

    def test_accepts_supported_python(self):
        self.assertIsNone(bootstrap.check_python((3, 10, 0)))
        self.assertIsNone(bootstrap.check_python((3, 13, 1)))


class VendorPathTest(unittest.TestCase):
    def test_paths_are_anchored_to_the_repo_not_the_cwd(self):
        self.assertEqual(bootstrap.VENDOR_DIR, bootstrap.REPO_ROOT / "vendor")
        self.assertTrue((bootstrap.REPO_ROOT / "wowtools" / "__init__.py").is_file())

    def test_add_vendor_path_is_idempotent(self):
        bootstrap.add_vendor_path()
        bootstrap.add_vendor_path()
        self.assertEqual(sys.path.count(str(bootstrap.VENDOR_DIR)), 1)

    def test_textual_imports_from_vendor(self):
        import textual

        self.assertTrue(str(textual.__file__).startswith(str(bootstrap.VENDOR_DIR)))
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'wowtools'`.

- [ ] **Step 5: Implement**

`wowtools/__init__.py`:
```python
"""Ka0s WoW Tools: out-of-game companion tools for World of Warcraft."""
__version__ = "0.1.0"
```

`wowtools/core/__init__.py`:
```python
"""Shared, UI-free framework used by every tool."""
```

`wowtools/core/bootstrap.py`:
```python
"""Interpreter check and vendor/ path setup. Stdlib only: runs before any third-party import."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = REPO_ROOT / "vendor"
MIN_PYTHON = (3, 10)


def check_python(version_info: tuple[int, ...] | None = None) -> str | None:
    """Return a readable error if this Python is too old, else None."""
    major, minor = tuple(version_info or sys.version_info)[:2]
    if (major, minor) < MIN_PYTHON:
        return (f"Ka0s WoW Tools needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer "
                f"(found {major}.{minor}).")
    return None


def add_vendor_path(vendor_dir: Path = VENDOR_DIR) -> None:
    """Put vendor/ first on sys.path so bundled libraries win over anything installed."""
    path = str(vendor_dir)
    if path not in sys.path:
        sys.path.insert(0, path)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: 5 tests, OK.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt scripts/update_vendor.py .gitattributes wowtools tests vendor
git commit -m "feat: scaffold package, vendored Textual, bootstrap"
```

---

### Task 2: Windows ⇄ WSL paths

**Files:**
- Create: `wowtools/core/paths.py`, `tests/test_paths.py`

**Interfaces:**
- Produces: `is_wsl() -> bool` (cached), `win_to_wsl(value: str) -> str | None`, `wsl_to_win(value: str) -> str | None`, `to_native(value: str, *, wsl: bool | None = None) -> Path`, `to_stored(value: str | Path, *, wsl: bool | None = None) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_paths.py`:
```python
import unittest
from pathlib import Path

from wowtools.core.paths import to_native, to_stored, win_to_wsl, wsl_to_win


class TranslateTest(unittest.TestCase):
    def test_win_to_wsl(self):
        self.assertEqual(win_to_wsl(r"G:\Games\Blizzard\World of Warcraft"), "/mnt/g/Games/Blizzard/World of Warcraft")
        self.assertEqual(win_to_wsl("c:/Program Files (x86)/World of Warcraft/"), "/mnt/c/Program Files (x86)/World of Warcraft")
        self.assertEqual(win_to_wsl("D:\\"), "/mnt/d")
        self.assertIsNone(win_to_wsl("/home/user/wow"))
        self.assertIsNone(win_to_wsl(r"\\server\share"))

    def test_wsl_to_win(self):
        self.assertEqual(wsl_to_win("/mnt/g/Games/Blizzard/World of Warcraft"), r"G:\Games\Blizzard\World of Warcraft")
        self.assertEqual(wsl_to_win("/mnt/d/"), "D:\\")
        self.assertIsNone(wsl_to_win("/home/user/wow"))
        self.assertIsNone(wsl_to_win("/mnt/data/x"))

    def test_to_native_under_wsl(self):
        self.assertEqual(to_native(r"G:\WoW", wsl=True), Path("/mnt/g/WoW"))
        self.assertEqual(to_native("/home/me/wow", wsl=True), Path("/home/me/wow"))

    def test_to_stored_under_wsl(self):
        self.assertEqual(to_stored(Path("/mnt/g/WoW"), wsl=True), r"G:\WoW")
        self.assertEqual(to_stored("/home/me/wow", wsl=True), "/home/me/wow")

    def test_no_translation_off_wsl(self):
        self.assertEqual(to_stored("/mnt/g/WoW", wsl=False), "/mnt/g/WoW")
        self.assertEqual(str(to_native("/home/me/wow", wsl=False)), "/home/me/wow")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_paths -v`
Expected: ERROR, `No module named 'wowtools.core.paths'`.

- [ ] **Step 3: Implement**

`wowtools/core/paths.py`:
```python
"""Path handling that lets one config work from both Windows and WSL.

Paths are stored in Windows form (G:\\Games\\...) whenever they point at a Windows drive,
and converted to the native form (/mnt/g/Games/...) when running under WSL.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

_WIN_DRIVE = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")
_WSL_MOUNT = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")


@functools.lru_cache(maxsize=1)
def is_wsl() -> bool:
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return "microsoft" in text or "wsl" in text


def win_to_wsl(value: str) -> str | None:
    match = _WIN_DRIVE.match(value.strip())
    if not match:
        return None
    drive = match.group(1).lower()
    rest = (match.group(2) or "").replace("\\", "/").strip("/")
    return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"


def wsl_to_win(value: str) -> str | None:
    text = value.strip()
    if text != "/":
        text = text.rstrip("/")
    match = _WSL_MOUNT.match(text)
    if not match:
        return None
    drive = match.group(1).upper()
    rest = (match.group(2) or "").strip("/")
    return f"{drive}:\\" + rest.replace("/", "\\")


def to_native(value: str, *, wsl: bool | None = None) -> Path:
    """Turn a stored path into one this process can open."""
    if is_wsl() if wsl is None else wsl:
        converted = win_to_wsl(value)
        if converted:
            return Path(converted)
    return Path(value.strip())


def to_stored(value: str | Path, *, wsl: bool | None = None) -> str:
    """Turn a native path into the form written to wow-tools.cfg."""
    text = str(value)
    if is_wsl() if wsl is None else wsl:
        converted = wsl_to_win(text)
        if converted:
            return converted
    return text
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_paths -v`
Expected: 5 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add wowtools/core/paths.py tests/test_paths.py
git commit -m "feat(core): Windows/WSL path translation"
```

---

### Task 3: Suite event log

**Files:**
- Create: `wowtools/core/events.py`, `tests/test_events.py`

**Interfaces:**
- Produces:
  - `SCHEMA_VERSION = 1`, `LEVELS: dict[str, int]` (debug 10, info 20, warning 30, error 40).
  - `EventSpec(level: str, description: str)` (frozen dataclass).
  - `UnknownEventError(KeyError)`.
  - `CORE_EVENTS`, `REGISTRY`, `TOOL_REGISTRIES: dict[str, dict[str, EventSpec]]`, `register_events(owner: str, events: dict[str, EventSpec]) -> None`.
  - `EventLog(log_dir: Path | None = None, *, tool="suite", mode="cli", text_level="info", retention_days=90, strict=False, memory=False, clock=None, on_sink_error=None)` with:
    - `.emit(name, *, dry_run=None, level=None, **data) -> dict`
    - `.set_context(*, tool=None, mode=None)`
    - `.prune() -> list[Path]`
    - `.records: list[dict] | None`
    - `.session: str`
  - `format_text(record) -> str`.
  - `init_event_log(log_dir, **kwargs) -> EventLog`, `get_event_log() -> EventLog`.
  - `log_event(name, *, dry_run=None, level=None, **data) -> dict`, `log_exception(where: str, exc: BaseException) -> dict`.
  - `capture_events(**kwargs)`, a context manager that yields `list[dict]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_events.py`:
```python
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wowtools.core import events
from wowtools.core.events import (EventLog, EventSpec, UnknownEventError, capture_events,
                                  log_event, register_events)

FIXED = datetime(2026, 9, 27, 14, 3, 11, 482000, tzinfo=timezone(timedelta(hours=10)))


class EnvelopeTest(unittest.TestCase):
    def test_record_has_envelope_fields_and_registry_level(self):
        log = EventLog(memory=True, tool="wtf-cleaner", mode="tui", clock=lambda: FIXED)
        record = log.emit("wow.running_warning", executables=["Wow.exe"])
        self.assertEqual(record["v"], 1)
        self.assertEqual(record["ts"], "2026-09-27T14:03:11.482+10:00")
        self.assertEqual(len(record["session"]), 8)
        self.assertEqual(record["suite_version"], "0.1.0")
        self.assertEqual((record["tool"], record["mode"]), ("wtf-cleaner", "tui"))
        self.assertEqual(record["event"], "wow.running_warning")
        self.assertEqual(record["level"], "warning")
        self.assertIsNone(record["dry_run"])
        self.assertEqual(record["data"], {"executables": ["Wow.exe"]})
        self.assertEqual(log.records, [record])

    def test_unregistered_event_raises_when_strict(self):
        with self.assertRaises(UnknownEventError):
            EventLog(strict=True).emit("nope.nothing")

    def test_unregistered_event_becomes_error_when_not_strict(self):
        record = EventLog(memory=True).emit("nope.nothing", a=1)
        self.assertEqual(record["event"], "error")
        self.assertEqual(record["data"], {"unregistered_event": "nope.nothing", "a": 1})

    def test_level_can_only_be_raised(self):
        log = EventLog(memory=True)
        self.assertEqual(log.emit("session.end", level="warning", exit_code=3)["level"], "warning")
        self.assertEqual(log.emit("wow.running_warning", level="debug")["level"], "warning")

    def test_register_conflicting_spec_raises(self):
        register_events("test-a", {"test.same": EventSpec("info", "x")})
        register_events("test-b", {"test.same": EventSpec("info", "x")})
        with self.assertRaises(ValueError):
            register_events("test-c", {"test.same": EventSpec("error", "y")})

    def test_every_registered_level_is_valid(self):
        for name, spec in events.REGISTRY.items():
            self.assertIn(spec.level, events.LEVELS, name)


class SinkTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_jsonl_keeps_debug_text_respects_level(self):
        log = EventLog(self.dir, text_level="info", clock=lambda: FIXED)
        log.emit("update.checked", current="0.1.0", latest=None, throttled=False)
        log.emit("config.created", path="x.cfg")
        lines = (self.dir / "events-2026-09-27.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["event"] for line in lines], ["update.checked", "config.created"])
        text = (self.dir / "wow-tools-2026-09-27.log").read_text(encoding="utf-8")
        self.assertNotIn("update.checked", text)
        self.assertIn("2026-09-27 14:03:11 INFO    [suite] config.created  path=x.cfg", text)

    def test_text_line_marks_dry_run_and_joins_lists(self):
        record = EventLog(memory=True, clock=lambda: FIXED).emit(
            "wow.running_warning", dry_run=True, executables=["Wow.exe", "WowClassic.exe"])
        self.assertTrue(events.format_text(record).endswith(
            "wow.running_warning  DRY-RUN executables=Wow.exe,WowClassic.exe"))

    def test_paths_and_sets_serialise(self):
        log = EventLog(self.dir, clock=lambda: FIXED)
        log.emit("config.created", path=Path("/x/y.cfg"))
        line = (self.dir / "events-2026-09-27.jsonl").read_text(encoding="utf-8").strip()
        self.assertEqual(json.loads(line)["data"]["path"], str(Path("/x/y.cfg")))

    def test_prune_removes_only_old_log_files(self):
        old = self.dir / "events-2026-01-01.jsonl"
        old.write_text("{}\n")
        keep = self.dir / "wow-tools-2026-09-20.log"
        keep.write_text("x\n")
        other = self.dir / "notes-2020-01-01.txt"
        other.write_text("x")
        removed = EventLog(self.dir, retention_days=90, clock=lambda: FIXED).prune()
        self.assertEqual(removed, [old])
        self.assertTrue(keep.exists())
        self.assertTrue(other.exists())

    def test_io_failure_disables_sinks_without_raising(self):
        blocker = self.dir / "logs"
        blocker.write_text("a file where the log folder should be")
        warnings = []
        log = EventLog(blocker, on_sink_error=warnings.append)
        log.emit("config.created", path="a")
        self.assertEqual(len(warnings), 2)
        log.emit("config.created", path="b")
        self.assertEqual(len(warnings), 2)


class GlobalLogTest(unittest.TestCase):
    def test_capture_events_swaps_global_log(self):
        before = events.get_event_log()
        with capture_events() as records:
            log_event("config.created", path="p")
        self.assertEqual([r["event"] for r in records], ["config.created"])
        self.assertIs(events.get_event_log(), before)

    def test_log_exception_records_traceback(self):
        with capture_events() as records:
            try:
                raise RuntimeError("boom")
            except RuntimeError as exc:
                events.log_exception("test", exc)
        data = records[0]["data"]
        self.assertEqual((data["where"], data["type"], data["message"]), ("test", "RuntimeError", "boom"))
        self.assertIn("RuntimeError: boom", data["traceback"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_events -v`
Expected: ERROR, `No module named 'wowtools.core.events'`.

- [ ] **Step 3: Implement**

`wowtools/core/events.py`:
```python
"""Suite-wide structured event log. The reference is docs/events.md (generated).

Every event name is registered once with a fixed level. log_event() writes one JSON line to
logs/events-YYYY-MM-DD.jsonl (all levels) and one readable line to logs/wow-tools-YYYY-MM-DD.log
(filtered by [general] log_level). Logging never raises into the caller because of I/O.
"""
from __future__ import annotations

import contextlib
import json
import re
import secrets
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

from wowtools import __version__

SCHEMA_VERSION = 1
LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


@dataclass(frozen=True)
class EventSpec:
    level: str
    description: str


class UnknownEventError(KeyError):
    """An event name that no registry declares."""


CORE_EVENTS: dict[str, EventSpec] = {
    "session.start": EventSpec("info", "The launcher or a tool started."),
    "session.end": EventSpec("info", "The process is exiting."),
    "config.created": EventSpec("info", "wow-tools.cfg was written for the first time."),
    "config.changed": EventSpec("info", "A config value changed, or was overridden for one run."),
    "ui.selection": EventSpec("info", "The user made a choice in the TUI or CLI."),
    "ui.item_toggled": EventSpec("debug", "The user ticked or unticked a single item."),
    "update.checked": EventSpec("debug", "The GitHub release check ran or was throttled."),
    "update.check_failed": EventSpec("debug", "The release check failed (offline, rate limited, bad data)."),
    "update.available": EventSpec("info", "A newer suite release exists."),
    "update.applied": EventSpec("info", "The suite was updated."),
    "update.failed": EventSpec("error", "Applying an update failed."),
    "wow.running_warning": EventSpec("warning", "World of Warcraft appears to be running."),
    "error": EventSpec("error", "An unexpected or fatal error."),
}
REGISTRY: dict[str, EventSpec] = dict(CORE_EVENTS)
TOOL_REGISTRIES: dict[str, dict[str, EventSpec]] = {"core": dict(CORE_EVENTS)}

_LOG_NAME = re.compile(r"^(?:events|wow-tools)-(\d{4}-\d{2}-\d{2})\.(?:jsonl|log)$")


def register_events(owner: str, events: dict[str, EventSpec]) -> None:
    """Declare a tool's events. Re-registering the same spec is fine; a different spec is a bug."""
    for name, spec in events.items():
        if spec.level not in LEVELS:
            raise ValueError(f"event {name!r} has unknown level {spec.level!r}")
        existing = REGISTRY.get(name)
        if existing is not None and existing != spec:
            raise ValueError(f"event {name!r} is already registered with a different spec")
    REGISTRY.update(events)
    TOOL_REGISTRIES.setdefault(owner, {}).update(events)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _render_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set, frozenset)):
        return ",".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, default=_json_default, ensure_ascii=False)
    return str(value)


def format_text(record: dict) -> str:
    """One readable line for the .log file."""
    ts = datetime.fromisoformat(record["ts"]).strftime("%Y-%m-%d %H:%M:%S")
    parts = [f"{key}={_render_value(value)}" for key, value in record["data"].items()]
    if record.get("dry_run"):
        parts.insert(0, "DRY-RUN")
    return f"{ts} {record['level'].upper():<7} [{record['tool']}] {record['event']}  " + " ".join(parts)


class EventLog:
    def __init__(self, log_dir: Path | None = None, *, tool: str = "suite", mode: str = "cli",
                 text_level: str = "info", retention_days: int = 90, strict: bool = False,
                 memory: bool = False, clock: Callable[[], datetime] | None = None,
                 on_sink_error: Callable[[str], None] | None = None) -> None:
        self.log_dir = Path(log_dir) if log_dir is not None else None
        self.tool = tool
        self.mode = mode
        self.text_level = text_level if text_level in LEVELS else "info"
        self.retention_days = retention_days
        self.strict = strict
        self.records: list[dict] | None = [] if memory else None
        self.session = secrets.token_hex(4)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._on_sink_error = on_sink_error or (lambda message: print(message, file=sys.stderr))
        self._disabled: set[str] = set()

    def set_context(self, *, tool: str | None = None, mode: str | None = None) -> None:
        if tool is not None:
            self.tool = tool
        if mode is not None:
            self.mode = mode

    def emit(self, name: str, *, dry_run: bool | None = None, level: str | None = None, **data: Any) -> dict:
        spec = REGISTRY.get(name)
        if spec is None:
            if self.strict:
                raise UnknownEventError(name)
            data = {"unregistered_event": name, **data}
            name, spec = "error", REGISTRY["error"]
        final_level = spec.level
        if level in LEVELS and LEVELS[level] > LEVELS[final_level]:
            final_level = level
        now = self._clock()
        record = {
            "v": SCHEMA_VERSION,
            "ts": now.isoformat(timespec="milliseconds"),
            "session": self.session,
            "suite_version": __version__,
            "tool": self.tool,
            "mode": self.mode,
            "event": name,
            "level": final_level,
            "dry_run": dry_run,
            "data": data,
        }
        if self.records is not None:
            self.records.append(record)
        if self.log_dir is not None:
            day = now.strftime("%Y-%m-%d")
            self._append("jsonl", self.log_dir / f"events-{day}.jsonl",
                         json.dumps(record, default=_json_default, ensure_ascii=False))
            if LEVELS[final_level] >= LEVELS[self.text_level]:
                self._append("text", self.log_dir / f"wow-tools-{day}.log", format_text(record))
        return record

    def _append(self, sink: str, path: Path, line: str) -> None:
        if sink in self._disabled:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            self._disabled.add(sink)
            self._on_sink_error(f"Ka0s WoW Tools: {sink} log disabled for this session ({exc})")

    def prune(self) -> list[Path]:
        """Delete dated log files older than retention_days. Returns what was removed."""
        if self.log_dir is None or not self.log_dir.is_dir():
            return []
        cutoff = (self._clock() - timedelta(days=self.retention_days)).date()
        removed: list[Path] = []
        for path in sorted(self.log_dir.iterdir()):
            match = _LOG_NAME.match(path.name)
            if not match:
                continue
            try:
                day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                try:
                    path.unlink()
                    removed.append(path)
                except OSError:
                    pass
        return removed


_current = EventLog(strict=True)


def init_event_log(log_dir: Path | None, **kwargs: Any) -> EventLog:
    """Install the process-wide log (called once by the launcher) and prune old files."""
    global _current
    _current = EventLog(log_dir, **kwargs)
    _current.prune()
    return _current


def get_event_log() -> EventLog:
    return _current


def log_event(name: str, *, dry_run: bool | None = None, level: str | None = None, **data: Any) -> dict:
    return _current.emit(name, dry_run=dry_run, level=level, **data)


def log_exception(where: str, exc: BaseException) -> dict:
    return log_event("error", where=where, type=type(exc).__name__, message=str(exc),
                     traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


@contextlib.contextmanager
def capture_events(**kwargs: Any) -> Iterator[list[dict]]:
    """Tests: route log_event() into a strict in-memory log and yield its records."""
    global _current
    previous = _current
    _current = EventLog(strict=True, memory=True, **kwargs)
    try:
        yield _current.records  # type: ignore[misc]
    finally:
        _current = previous
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_events -v`
Expected: 13 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add wowtools/core/events.py tests/test_events.py
git commit -m "feat(core): structured suite event log with registry and levels"
```

---

### Task 4: Config

**Files:**
- Create: `wowtools/core/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `REPO_ROOT` (Task 1), `to_native`/`to_stored` (Task 2), `LEVELS`/`log_event` (Task 3).
- Produces:
  - Constants: `DEFAULT_CONFIG_PATH`, `DEFAULT_BACKUP_DIRNAME = "wow-tools-backups"`, `GENERAL = "general"`.
  - `ConfigError`.
  - `Config(path: Path | None = None)` with:
    - `.load() -> Config`, `.save()`, `.save_if_exists()`, `.exists: bool`, `.path`.
    - `.get(section, key, fallback=None) -> str | None`, `.get_int(section, key, fallback: int) -> int`, `.get_bool(section, key, fallback: bool) -> bool`.
    - `.set(section, key, value, *, source="app", log=True)`.
    - `.get_path(section, key) -> Path | None`, `.set_path(section, key, value: Path | str | None, *, source="app")`.
    - Properties: `wow_path`, `backup_dir`, `last_flavor`, `check_for_updates`, `auto_update`, `log_level`, `log_retention_days`, `last_update_check: datetime | None` (aware), `latest_seen_version`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import DEFAULT_CONFIG_PATH, Config, ConfigError
from wowtools.core.events import capture_events


class ConfigTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "wow-tools.cfg"

    def test_default_path_is_repo_root_not_cwd(self):
        self.assertEqual(DEFAULT_CONFIG_PATH, REPO_ROOT / "wow-tools.cfg")

    def test_missing_file_gives_defaults(self):
        cfg = Config(self.path).load()
        self.assertFalse(cfg.exists)
        self.assertIsNone(cfg.wow_path)
        self.assertIsNone(cfg.backup_dir)
        self.assertIsNone(cfg.last_flavor)
        self.assertTrue(cfg.check_for_updates)
        self.assertFalse(cfg.auto_update)
        self.assertEqual(cfg.log_level, "info")
        self.assertEqual(cfg.log_retention_days, 90)
        self.assertIsNone(cfg.last_update_check)

    def test_round_trip_preserves_unknown_keys_and_sections(self):
        self.path.write_text("[general]\nwow_path = /games/wow\nmystery = 42\n\n[other_tool]\nfoo = bar\n",
                             encoding="utf-8")
        cfg = Config(self.path).load()
        cfg.set("general", "last_flavor", "_retail_")
        cfg.save()
        again = Config(self.path).load()
        self.assertEqual(again.get("general", "mystery"), "42")
        self.assertEqual(again.get("other_tool", "foo"), "bar")
        self.assertEqual(again.last_flavor, "_retail_")
        self.assertEqual(again.wow_path, Path("/games/wow"))

    def test_bad_values_fall_back_to_defaults(self):
        self.path.write_text("[general]\ncheck_for_updates = maybe\nlog_level = loud\n"
                             "log_retention_days = soon\nlast_update_check = yesterday\n", encoding="utf-8")
        cfg = Config(self.path).load()
        self.assertTrue(cfg.check_for_updates)
        self.assertEqual(cfg.log_level, "info")
        self.assertEqual(cfg.log_retention_days, 90)
        self.assertIsNone(cfg.last_update_check)
        self.assertEqual(cfg.get_int("general", "log_retention_days", 7), 7)

    def test_backup_dir_defaults_under_wow_path(self):
        cfg = Config(self.path)
        cfg.set("general", "wow_path", "/games/wow")
        self.assertEqual(cfg.backup_dir, Path("/games/wow") / "wow-tools-backups")
        cfg.set_path("general", "backup_dir", Path("/elsewhere/bk"))
        self.assertEqual(cfg.backup_dir, Path("/elsewhere/bk"))
        cfg.set_path("general", "backup_dir", None)
        self.assertEqual(cfg.backup_dir, Path("/games/wow") / "wow-tools-backups")

    def test_set_logs_real_changes_only(self):
        cfg = Config(self.path)
        with capture_events() as records:
            cfg.set("wtf_cleaner", "max_age_days", 30, source="wizard")
            cfg.set("wtf_cleaner", "max_age_days", 30)
            cfg.set("general", "last_update_check", "x", log=False)
        changed = [r for r in records if r["event"] == "config.changed"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["data"], {"section": "wtf_cleaner", "key": "max_age_days",
                                              "old": None, "new": "30", "source": "wizard"})

    def test_bools_are_written_lowercase(self):
        cfg = Config(self.path)
        cfg.set("x", "flag", True)
        self.assertEqual(cfg.get("x", "flag"), "true")
        self.assertTrue(cfg.get_bool("x", "flag", False))

    def test_first_save_logs_created_once(self):
        with capture_events() as records:
            cfg = Config(self.path)
            cfg.save()
            cfg.save()
        self.assertEqual([r["event"] for r in records].count("config.created"), 1)
        self.assertTrue(self.path.exists())

    def test_save_if_exists_does_not_create(self):
        Config(self.path).save_if_exists()
        self.assertFalse(self.path.exists())

    def test_last_update_check_round_trip(self):
        cfg = Config(self.path)
        when = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
        cfg.set("general", "last_update_check", when.isoformat())
        self.assertEqual(cfg.last_update_check, when)
        cfg.set("general", "last_update_check", "2026-09-27T12:00:00")
        self.assertEqual(cfg.last_update_check, when)

    def test_unreadable_config_raises_config_error(self):
        self.path.write_text("this is not an ini file [[[", encoding="utf-8")
        with self.assertRaises(ConfigError):
            Config(self.path).load()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_config -v`
Expected: ERROR, `No module named 'wowtools.core.config'`.

- [ ] **Step 3: Implement**

`wowtools/core/config.py`:
```python
"""wow-tools.cfg: one INI file in the repo root shared by every tool.

[general] belongs to the suite; each tool owns one section named after it (e.g. [wtf_cleaner]).
Unknown keys are preserved. Bad values fall back to defaults instead of failing.
"""
from __future__ import annotations

import configparser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.events import LEVELS, log_event
from wowtools.core.paths import to_native, to_stored

DEFAULT_CONFIG_PATH = REPO_ROOT / "wow-tools.cfg"
DEFAULT_BACKUP_DIRNAME = "wow-tools-backups"
GENERAL = "general"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(Exception):
    """wow-tools.cfg exists but cannot be read."""


def _to_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class Config:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        self.exists = False
        self._parser = configparser.ConfigParser(interpolation=None)

    def load(self) -> Config:
        if self.path.is_file():
            try:
                with self.path.open(encoding="utf-8") as handle:
                    self._parser.read_file(handle)
            except (configparser.Error, UnicodeDecodeError, OSError) as exc:
                raise ConfigError(f"Cannot read {self.path}: {exc}") from exc
            self.exists = True
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            self._parser.write(handle)
        if not self.exists:
            self.exists = True
            log_event("config.created", path=str(self.path))

    def save_if_exists(self) -> None:
        if self.exists:
            self.save()

    # --- raw access -------------------------------------------------------------------------
    def get(self, section: str, key: str, fallback: str | None = None) -> str | None:
        return self._parser.get(section, key, fallback=fallback)

    def get_int(self, section: str, key: str, fallback: int) -> int:
        raw = self.get(section, key)
        try:
            return int(raw) if raw is not None else fallback
        except ValueError:
            return fallback

    def get_bool(self, section: str, key: str, fallback: bool) -> bool:
        raw = self.get(section, key)
        if raw is None:
            return fallback
        value = raw.strip().lower()
        if value in _TRUE:
            return True
        if value in _FALSE:
            return False
        return fallback

    def set(self, section: str, key: str, value: Any, *, source: str = "app", log: bool = True) -> None:
        new = _to_text(value)
        old = self.get(section, key)
        if old == new:
            return
        if not self._parser.has_section(section):
            self._parser.add_section(section)
        self._parser.set(section, key, new)
        if log:
            log_event("config.changed", section=section, key=key, old=old, new=new, source=source)

    def get_path(self, section: str, key: str) -> Path | None:
        raw = (self.get(section, key) or "").strip()
        return to_native(raw) if raw else None

    def set_path(self, section: str, key: str, value: Path | str | None, *, source: str = "app") -> None:
        self.set(section, key, to_stored(value) if value else "", source=source)

    # --- [general] --------------------------------------------------------------------------
    @property
    def wow_path(self) -> Path | None:
        return self.get_path(GENERAL, "wow_path")

    @property
    def backup_dir(self) -> Path | None:
        explicit = self.get_path(GENERAL, "backup_dir")
        if explicit is not None:
            return explicit
        wow = self.wow_path
        return wow / DEFAULT_BACKUP_DIRNAME if wow is not None else None

    @property
    def last_flavor(self) -> str | None:
        return self.get(GENERAL, "last_flavor") or None

    @property
    def check_for_updates(self) -> bool:
        return self.get_bool(GENERAL, "check_for_updates", True)

    @property
    def auto_update(self) -> bool:
        return self.get_bool(GENERAL, "auto_update", False)

    @property
    def log_level(self) -> str:
        value = (self.get(GENERAL, "log_level") or "info").strip().lower()
        return value if value in LEVELS else "info"

    @property
    def log_retention_days(self) -> int:
        return max(1, self.get_int(GENERAL, "log_retention_days", 90))

    @property
    def last_update_check(self) -> datetime | None:
        raw = self.get(GENERAL, "last_update_check")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @property
    def latest_seen_version(self) -> str | None:
        return self.get(GENERAL, "latest_seen_version") or None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_config -v`
Expected: 11 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add wowtools/core/config.py tests/test_config.py
git commit -m "feat(core): shared INI config with typed accessors and change events"
```

---

### Task 5: WoW install model + test fixture tree

**Files:**
- Create: `wowtools/core/install.py`, `tests/fixtures.py`, `tests/test_install.py`

**Interfaces:**
- Consumes: `is_wsl` (Task 2), `Config` (Task 4, used by the fixture).
- Produces:
  - `FLAVOR_NAMES`, `InstallError`, `ACCOUNT_WIDE = "account-wide"`.
  - `Character(account: str, realm: str, name: str, path: Path)` with `.saved_variables_dir`, `.addons_txt`, `.label` (`"Realm/Name"`).
  - `Account(name: str, path: Path)` with `.saved_variables_dir` and `.characters(on_error=None) -> list[Character]`.
  - `Flavor(folder: str, path: Path)` with `.display_name`, `.short_name`, `.addons_dir`, `.wtf_dir`, `.account_dir` and `.accounts(on_error=None) -> list[Account]`.
  - `WowInstall(root: Path)` with `.flavors() -> list[Flavor]`, `.is_valid() -> bool` and `.flavor(name: str) -> Flavor | None`.
  - `drive_roots() -> list[Path]`, `detect_installs(roots: list[Path] | None = None) -> list[Path]`.
  - `on_error` has the type `Callable[[Path, OSError], None]`.
  - Fixture: `tests.fixtures.NOW`, `DAY`, `FRESH`, `OLD`, `build_wow_tree(root: Path) -> Path`, `make_config(directory: Path, wow_root: Path, **general) -> Config`.

- [ ] **Step 1: Write the fixture builder**

`tests/fixtures.py`:
```python
"""A synthetic World of Warcraft install for tests. Never touches a real install.

Layout built by build_wow_tree(root):

_retail_/Interface/AddOns: Auctionator, Details (Details_Mainline.toc only), DisabledAddon,
                           OldAddon, NoTocFolder (no .toc -> not an addon)
_retail_/WTF/Account/ACCT1/SavedVariables:
    Auctionator.lua, Auctionator.lua.bak, Auctionator.lua.pre-schema8-20260926-103400 (stray)
    Details.lua, "Details.lua - Copy.bak" (stray)
    Uninstalled.lua, Uninstalled.lua.bak        (addon not installed)
    DisabledAddon.lua                           (installed, disabled everywhere)
    OldAddon.lua, OldAddon.lua.bak              (200 days old)
    Blizzard_Foo.lua (protected), notes.txt (not an SV file)
_retail_/WTF/Account/ACCT1/config-cache.wtf
_retail_/WTF/Account/ACCT1/Realm1/CharA: AddOns.txt (Auctionator, Details, OldAddon enabled;
                                         DisabledAddon disabled), SV: Auctionator.lua, Uninstalled.lua
_retail_/WTF/Account/ACCT2/SavedVariables/Details.lua
_retail_/WTF/Account/ACCT2/Realm2/Chârb: AddOns.txt (Details/DisabledAddon/OldAddon disabled,
                                         one garbage line), SV: Details.lua
_classic_era_: Questie installed; ACCT1 account SV Questie.lua; Realm1/NoTxt (no AddOns.txt)
_anniversary_: WTF only, no Interface/AddOns (scanning it must abort)
_notaflavor: not a flavor folder
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from wowtools.core.config import Config

NOW = time.time()
DAY = 86400.0
FRESH = NOW - 1 * DAY
OLD = NOW - 200 * DAY


def _write(path: Path, text: str = "-- saved variables\n", mtime: float = FRESH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _addon(flavor: Path, name: str, toc: str | None = None) -> None:
    _write(flavor / "Interface" / "AddOns" / name / (toc or f"{name}.toc"), "## Interface: 110200\n")


def build_wow_tree(root: Path) -> Path:
    retail = root / "_retail_"
    for name in ("Auctionator", "DisabledAddon", "OldAddon"):
        _addon(retail, name)
    _addon(retail, "Details", "Details_Mainline.toc")
    _write(retail / "Interface" / "AddOns" / "NoTocFolder" / "readme.txt")

    acct1 = retail / "WTF" / "Account" / "ACCT1"
    sv = acct1 / "SavedVariables"
    for name in ("Auctionator.lua", "Auctionator.lua.bak", "Auctionator.lua.pre-schema8-20260926-103400",
                 "Details.lua", "Details.lua - Copy.bak", "Uninstalled.lua", "Uninstalled.lua.bak",
                 "DisabledAddon.lua", "Blizzard_Foo.lua", "notes.txt"):
        _write(sv / name)
    _write(sv / "OldAddon.lua", mtime=OLD)
    _write(sv / "OldAddon.lua.bak", mtime=OLD)
    _write(acct1 / "config-cache.wtf", "SET x 1\n")

    char_a = acct1 / "Realm1" / "CharA"
    _write(char_a / "AddOns.txt",
           "Auctionator: enabled\nDetails: enabled\nDisabledAddon: disabled\nOldAddon: enabled\n")
    _write(char_a / "SavedVariables" / "Auctionator.lua")
    _write(char_a / "SavedVariables" / "Uninstalled.lua")

    acct2 = retail / "WTF" / "Account" / "ACCT2"
    _write(acct2 / "SavedVariables" / "Details.lua")
    char_b = acct2 / "Realm2" / "Chârb"
    _write(char_b / "AddOns.txt",
           "Auctionator: enabled\nDetails: disabled\nDisabledAddon: disabled\nOldAddon: disabled\ngarbage line\n")
    _write(char_b / "SavedVariables" / "Details.lua")

    era = root / "_classic_era_"
    _addon(era, "Questie")
    _write(era / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "Questie.lua")
    _write(era / "WTF" / "Account" / "ACCT1" / "Realm1" / "NoTxt" / "SavedVariables" / "Questie.lua")

    _write(root / "_anniversary_" / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "Foo.lua")
    (root / "_notaflavor").mkdir(parents=True, exist_ok=True)
    return root


def make_config(directory: Path, wow_root: Path, **general: str) -> Config:
    """A saved config pointing at a fixture tree, with update checks off (no network in tests)."""
    cfg = Config(directory / "wow-tools.cfg")
    cfg.set("general", "wow_path", str(wow_root), log=False)
    cfg.set("general", "check_for_updates", "false", log=False)
    cfg.set("general", "last_flavor", "_retail_", log=False)
    for key, value in general.items():
        cfg.set("general", key, value, log=False)
    cfg.save()
    return cfg
```

- [ ] **Step 2: Write the failing tests**

`tests/test_install.py`:
```python
import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.install import Account, Flavor, WowInstall, detect_installs


class InstallTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.install = WowInstall(self.root)

    def test_discovers_flavor_folders_only(self):
        self.assertEqual([f.folder for f in self.install.flavors()],
                         ["_anniversary_", "_classic_era_", "_retail_"])

    def test_display_and_short_names(self):
        self.assertEqual(Flavor("_classic_era_", self.root).display_name, "Classic Era")
        self.assertEqual(Flavor("_retail_", self.root).display_name, "Retail")
        self.assertEqual(Flavor("_weird_new_", self.root).display_name, "Weird New")
        self.assertEqual(Flavor("_classic_era_", self.root).short_name, "classic_era")

    def test_flavor_lookup_accepts_short_and_folder_names(self):
        self.assertEqual(self.install.flavor("retail").folder, "_retail_")
        self.assertEqual(self.install.flavor("_Classic_Era_").folder, "_classic_era_")
        self.assertIsNone(self.install.flavor("wotlk"))

    def test_accounts_and_characters(self):
        retail = self.install.flavor("retail")
        accounts = retail.accounts()
        self.assertEqual([a.name for a in accounts], ["ACCT1", "ACCT2"])
        characters = [c for a in accounts for c in a.characters()]
        self.assertEqual([c.label for c in characters], ["Realm1/CharA", "Realm2/Chârb"])
        self.assertTrue(characters[0].addons_txt.is_file())
        self.assertEqual(characters[0].saved_variables_dir, characters[0].path / "SavedVariables")
        self.assertEqual(accounts[0].saved_variables_dir, accounts[0].path / "SavedVariables")

    def test_is_valid(self):
        self.assertTrue(self.install.is_valid())
        self.assertFalse(WowInstall(self.root / "nope").is_valid())
        self.assertFalse(WowInstall(self.root / "_retail_").is_valid())

    def test_missing_folder_is_silent(self):
        errors = []
        self.assertEqual(Account("X", self.root / "missing").characters(on_error=lambda p, e: errors.append(p)), [])
        self.assertEqual(errors, [])

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs POSIX permissions")
    def test_unreadable_folder_is_reported(self):
        locked = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "Realm1"
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        errors = []
        account = self.install.flavor("retail").accounts()[0]
        self.assertEqual(account.characters(on_error=lambda p, e: errors.append(p)), [])
        self.assertEqual(errors, [locked])

    def test_detect_installs(self):
        self.assertEqual(detect_installs([self.tmp]), [self.root])
        self.assertEqual(detect_installs([self.tmp / "empty"]), [])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_install -v`
Expected: ERROR, `No module named 'wowtools.core.install'`.

- [ ] **Step 4: Implement**

`wowtools/core/install.py`:
```python
"""Model of a World of Warcraft install: flavors, accounts, realms and characters."""
from __future__ import annotations

import os
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from wowtools.core.paths import is_wsl

ErrorHandler = Callable[[Path, OSError], None]
ACCOUNT_WIDE = "account-wide"

FLAVOR_NAMES = {
    "_retail_": "Retail",
    "_classic_": "Classic",
    "_classic_era_": "Classic Era",
    "_anniversary_": "Anniversary",
    "_ptr_": "Retail PTR",
    "_xptr_": "Retail Experimental PTR",
    "_beta_": "Retail Beta",
    "_classic_ptr_": "Classic PTR",
    "_classic_beta_": "Classic Beta",
    "_classic_era_ptr_": "Classic Era PTR",
}
_FLAVOR_DIR = re.compile(r"^_[a-z0-9_]+_$")

COMMON_SUBPATHS = (
    "Program Files (x86)/World of Warcraft",
    "Program Files/World of Warcraft",
    "Program Files (x86)/Blizzard/World of Warcraft",
    "World of Warcraft",
    "Games/World of Warcraft",
    "Games/Blizzard/World of Warcraft",
    "Blizzard/World of Warcraft",
)


class InstallError(Exception):
    """The configured folder is not a usable WoW install."""


def _subdirs(path: Path, on_error: ErrorHandler | None = None) -> list[Path]:
    if not path.is_dir():
        return []
    try:
        children = [p for p in path.iterdir() if p.is_dir()]
    except OSError as exc:
        if on_error is not None:
            on_error(path, exc)
        return []
    return sorted(children, key=lambda p: p.name.casefold())


@dataclass(frozen=True)
class Character:
    account: str
    realm: str
    name: str
    path: Path

    @property
    def saved_variables_dir(self) -> Path:
        return self.path / "SavedVariables"

    @property
    def addons_txt(self) -> Path:
        return self.path / "AddOns.txt"

    @property
    def label(self) -> str:
        return f"{self.realm}/{self.name}"


@dataclass(frozen=True)
class Account:
    name: str
    path: Path

    @property
    def saved_variables_dir(self) -> Path:
        return self.path / "SavedVariables"

    def characters(self, on_error: ErrorHandler | None = None) -> list[Character]:
        result = []
        for realm in _subdirs(self.path, on_error):
            if realm.name == "SavedVariables":
                continue
            for char in _subdirs(realm, on_error):
                result.append(Character(self.name, realm.name, char.name, char))
        return result


@dataclass(frozen=True)
class Flavor:
    folder: str
    path: Path

    @property
    def display_name(self) -> str:
        return FLAVOR_NAMES.get(self.folder) or self.folder.strip("_").replace("_", " ").title()

    @property
    def short_name(self) -> str:
        return self.folder.strip("_")

    @property
    def addons_dir(self) -> Path:
        return self.path / "Interface" / "AddOns"

    @property
    def wtf_dir(self) -> Path:
        return self.path / "WTF"

    @property
    def account_dir(self) -> Path:
        return self.wtf_dir / "Account"

    def accounts(self, on_error: ErrorHandler | None = None) -> list[Account]:
        return [Account(p.name, p) for p in _subdirs(self.account_dir, on_error)]


class WowInstall:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def flavors(self) -> list[Flavor]:
        return [Flavor(p.name, p) for p in _subdirs(self.root)
                if _FLAVOR_DIR.match(p.name) and ((p / "WTF").is_dir() or (p / "Interface").is_dir())]

    def is_valid(self) -> bool:
        return self.root.is_dir() and bool(self.flavors())

    def flavor(self, name: str) -> Flavor | None:
        wanted = name.strip().strip("_").casefold()
        for flavor in self.flavors():
            if flavor.short_name.casefold() == wanted:
                return flavor
        return None


def drive_roots() -> list[Path]:
    if os.name == "nt":
        return [Path(f"{d}:/") for d in string.ascii_uppercase if Path(f"{d}:/").exists()]
    if is_wsl():
        return [Path(f"/mnt/{d}") for d in string.ascii_lowercase if Path(f"/mnt/{d}").is_dir()]
    home = Path.home()
    return [home / ".wine" / "drive_c", home / "Games", home]


def detect_installs(roots: list[Path] | None = None) -> list[Path]:
    """Look for WoW in the usual places on every drive. Returns native paths."""
    found: list[Path] = []
    for root in drive_roots() if roots is None else roots:
        for sub in COMMON_SUBPATHS:
            candidate = root / sub
            if candidate not in found and WowInstall(candidate).is_valid():
                found.append(candidate)
    return found
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_install -v`
Expected: 8 tests, OK.

- [ ] **Step 6: Commit**

```bash
git add wowtools/core/install.py tests/fixtures.py tests/test_install.py
git commit -m "feat(core): WoW install model and synthetic test tree"
```

---

### Task 6: Verified zip backups

**Files:**
- Create: `wowtools/core/backup.py`, `tests/test_backup.py`

**Interfaces:**
- Produces:
  - `BackupError`, `BackupEntry(path: Path, reasons: tuple[str, ...] = ())`, `MANIFEST_NAME = "manifest.json"`.
  - `backup_filename(tool: str, flavor_short: str, when: datetime) -> str`.
  - `create_backup(entries: list[BackupEntry], base_dir: Path, dest_zip: Path, meta: dict) -> Path`.
  - `verify_backup(zip_path: Path, expected: dict[str, int]) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_backup.py`:
```python
import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core import backup
from wowtools.core.backup import BackupEntry, BackupError, backup_filename, create_backup


class BackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        root = build_wow_tree(self.tmp / "World of Warcraft")
        self.flavor_dir = root / "_retail_"
        self.sv = self.flavor_dir / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.dest = self.tmp / "backups" / "b.zip"
        self.entries = [BackupEntry(self.sv / "Uninstalled.lua", ("not_installed",)),
                        BackupEntry(self.sv / "Uninstalled.lua.bak", ("not_installed",))]

    def test_zip_contains_files_relative_to_flavor_and_manifest(self):
        out = create_backup(self.entries, self.flavor_dir, self.dest, {"tool": "wtf-cleaner", "flavor": "_retail_"})
        self.assertEqual(out, self.dest)
        with zipfile.ZipFile(self.dest) as zf:
            self.assertEqual(sorted(zf.namelist()), [
                "WTF/Account/ACCT1/SavedVariables/Uninstalled.lua",
                "WTF/Account/ACCT1/SavedVariables/Uninstalled.lua.bak",
                "manifest.json",
            ])
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["tool"], "wtf-cleaner")
        self.assertEqual(manifest["files"][0]["reasons"], ["not_installed"])
        self.assertEqual(manifest["files"][0]["size"], (self.sv / "Uninstalled.lua").stat().st_size)
        self.assertFalse(self.dest.with_name("b.zip.partial").exists())

    def test_file_outside_base_is_rejected(self):
        outside = self.tmp / "elsewhere.lua"
        outside.write_text("x")
        with self.assertRaises(BackupError):
            create_backup([BackupEntry(outside)], self.flavor_dir, self.dest, {})
        self.assertFalse(self.dest.exists())

    def test_missing_file_raises_and_leaves_no_zip(self):
        with self.assertRaises(BackupError):
            create_backup([BackupEntry(self.sv / "Gone.lua")], self.flavor_dir, self.dest, {})
        self.assertFalse(self.dest.exists())

    def test_verification_failure_leaves_nothing(self):
        with patch.object(backup, "verify_backup", side_effect=BackupError("boom")):
            with self.assertRaises(BackupError):
                create_backup(self.entries, self.flavor_dir, self.dest, {})
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_name("b.zip.partial").exists())

    def test_unwritable_destination_raises_backup_error(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("a file, not a folder")
        with self.assertRaises(BackupError):
            create_backup(self.entries, self.flavor_dir, blocker / "b.zip", {})

    def test_empty_entries_rejected(self):
        with self.assertRaises(BackupError):
            create_backup([], self.flavor_dir, self.dest, {})

    def test_backup_filename(self):
        self.assertEqual(backup_filename("wtf-cleaner", "retail", datetime(2026, 9, 27, 14, 3, 11)),
                         "wtf-cleaner_retail_20260927-140311.zip")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_backup -v`
Expected: ERROR, `No module named 'wowtools.core.backup'`.

- [ ] **Step 3: Implement**

`wowtools/core/backup.py`:
```python
"""Timestamped zip backups with a manifest, verified before anyone deletes anything."""
from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MANIFEST_NAME = "manifest.json"


class BackupError(Exception):
    """The backup could not be written or verified. Nothing should be deleted."""


@dataclass(frozen=True)
class BackupEntry:
    path: Path
    reasons: tuple[str, ...] = ()


def backup_filename(tool: str, flavor_short: str, when: datetime) -> str:
    return f"{tool}_{flavor_short}_{when:%Y%m%d-%H%M%S}.zip"


def create_backup(entries: list[BackupEntry], base_dir: Path, dest_zip: Path, meta: dict) -> Path:
    """Zip entries (stored relative to base_dir) plus manifest.json, verify, then move into place."""
    if not entries:
        raise BackupError("nothing to back up")
    base = base_dir.resolve()
    expected: dict[str, int] = {}
    files: list[dict] = []
    for entry in entries:
        source = entry.path.resolve()
        try:
            arcname = source.relative_to(base).as_posix()
        except ValueError as exc:
            raise BackupError(f"{entry.path} is not inside {base_dir}") from exc
        try:
            stat = source.stat()
        except OSError as exc:
            raise BackupError(f"cannot read {entry.path}: {exc}") from exc
        expected[arcname] = stat.st_size
        files.append({"path": arcname, "size": stat.st_size, "mtime": stat.st_mtime,
                      "reasons": list(entry.reasons)})

    partial = dest_zip.with_name(dest_zip.name + ".partial")
    try:
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
            for entry, info in zip(entries, files):
                zf.write(entry.path, info["path"])
            zf.writestr(MANIFEST_NAME, json.dumps({**meta, "files": files}, indent=2, ensure_ascii=False))
        verify_backup(partial, expected)
        os.replace(partial, dest_zip)
    except BackupError:
        _discard(partial)
        raise
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        _discard(partial)
        raise BackupError(f"backup failed: {exc}") from exc
    return dest_zip


def verify_backup(zip_path: Path, expected: dict[str, int]) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise BackupError(f"corrupt entry in backup: {bad}")
        sizes = {info.filename: info.file_size for info in zf.infolist() if info.filename != MANIFEST_NAME}
    if sizes != expected:
        raise BackupError("backup contents do not match the selected files")


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_backup -v`
Expected: 7 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add wowtools/core/backup.py tests/test_backup.py
git commit -m "feat(core): verified zip backups with manifest"
```

---

### Task 7: "Is WoW running?" check

**Files:**
- Create: `wowtools/core/process.py`, `tests/test_process.py`

**Interfaces:**
- Consumes: `is_wsl` (Task 2).
- Produces: `WOW_EXECUTABLES`, `names_in_tasklist(output: str) -> list[str]`, `running_wow_executables(*, use_tasklist: bool | None = None, runner=subprocess.run, proc_root: Path = Path("/proc")) -> list[str] | None` (`None` means unknown).

- [ ] **Step 1: Write the failing tests**

`tests/test_process.py`:
```python
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from wowtools.core.process import names_in_tasklist, running_wow_executables

TASKLIST = ('"System Idle Process","0","Services","0","8 K"\n'
            '"Wow.exe","1234","Console","1","1,234,567 K"\n'
            '"WowClassicHelper.exe","99","Console","1","10 K"\n')


class ProcessTest(unittest.TestCase):
    def test_parses_tasklist_csv(self):
        self.assertEqual(names_in_tasklist(TASKLIST), ["Wow.exe"])
        self.assertEqual(names_in_tasklist('"explorer.exe","1","Console","1","5 K"\n'), [])

    def test_tasklist_runner(self):
        runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=TASKLIST)
        self.assertEqual(running_wow_executables(use_tasklist=True, runner=runner), ["Wow.exe"])

    def test_tasklist_failure_is_unknown(self):
        def broken(*a, **k):
            raise FileNotFoundError("tasklist.exe")
        self.assertIsNone(running_wow_executables(use_tasklist=True, runner=broken))

        def timeout(*a, **k):
            raise subprocess.TimeoutExpired("tasklist", 5)
        self.assertIsNone(running_wow_executables(use_tasklist=True, runner=timeout))

    def test_proc_scan_for_wine(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / "123").mkdir()
            (proc / "123" / "comm").write_text("WowClassic.exe\n")
            (proc / "456").mkdir()
            (proc / "456" / "comm").write_text("bash\n")
            self.assertEqual(running_wow_executables(use_tasklist=False, proc_root=proc), ["WowClassic.exe"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_process -v`
Expected: ERROR, `No module named 'wowtools.core.process'`.

- [ ] **Step 3: Implement**

`wowtools/core/process.py`:
```python
"""Best-effort detection of a running WoW client (WoW rewrites SavedVariables on logout)."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from wowtools.core.paths import is_wsl

WOW_EXECUTABLES = ("Wow.exe", "WowClassic.exe", "WowB.exe", "WowT.exe")


def names_in_tasklist(output: str) -> list[str]:
    """Parse `tasklist /FO CSV /NH` output."""
    lower = output.lower()
    return [exe for exe in WOW_EXECUTABLES
            if re.search(rf'^"?{re.escape(exe.lower())}"?[\s,]', lower, re.MULTILINE)]


def running_wow_executables(*, use_tasklist: bool | None = None, runner=subprocess.run,
                            proc_root: Path = Path("/proc")) -> list[str] | None:
    """Names of running WoW executables, [] if none, None if we cannot tell."""
    if use_tasklist is None:
        use_tasklist = os.name == "nt" or is_wsl()
    if use_tasklist:
        command = "tasklist" if os.name == "nt" else "tasklist.exe"
        try:
            proc = runner([command, "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        return names_in_tasklist(proc.stdout or "")
    try:
        comm_files = list(proc_root.glob("[0-9]*/comm"))
    except OSError:
        return None
    names = set()
    for comm in comm_files:
        try:
            names.add(comm.read_text(encoding="utf-8", errors="replace").strip().lower())
        except OSError:
            continue
    return [exe for exe in WOW_EXECUTABLES if exe.lower() in names]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_process -v`
Expected: 4 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add wowtools/core/process.py tests/test_process.py
git commit -m "feat(core): best-effort WoW running detection"
```

---

### Task 8: WTF Cleaner scanner (+ the tool's event registry)

**Files:**
- Create: `wowtools/tools/__init__.py` (docstring only; the registry is added in Task 13), `wowtools/tools/wtf_cleaner/__init__.py`, `wowtools/tools/wtf_cleaner/events.py`, `wowtools/tools/wtf_cleaner/scanner.py`, `tests/test_scanner.py`

**Interfaces:**
- Consumes: `Flavor`, `Account`, `Character`, `ACCOUNT_WIDE` (Task 5); `EventSpec`, `register_events`, `log_event` (Task 3).
- Produces:
  - `wtf_cleaner.events.TOOL_NAME = "wtf-cleaner"`, `EVENTS: dict[str, EventSpec]`.
  - `ScanError`, `ScanWarning(path: str, message: str)`.
  - `SVFile(path: Path, size: int, mtime: float, canonical: bool)` with `.name`.
  - `SVGroup(account: str, character: Character | None, addon: str, files: list[SVFile])` with `.scope` (`"account"`/`"character"`), `.owner_label` (`ACCOUNT_WIDE` or `"Realm/Name"`), `.key`, `.newest_mtime`, `.total_size`.
  - `ScanResult(flavor, installed: dict[str, str], enabled: set[str], groups: list[SVGroup], accounts: int, characters: int, warnings: list[ScanWarning])` with `.sv_files`.
  - Functions:
    - `addon_name_for(filename: str) -> str | None`
    - `is_canonical(filename: str, addon: str) -> bool`
    - `installed_addons(addons_dir: Path) -> dict[str, str]` (casefold → folder name)
    - `parse_addons_txt(path: Path, warnings: list[ScanWarning] | None = None) -> dict[str, bool]`
    - `enabled_addons(characters, installed, warnings) -> set[str]`
    - `scan(flavor: Flavor) -> ScanResult`

- [ ] **Step 1: Write the failing tests**

`tests/test_scanner.py`:
```python
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.scanner import (ScanError, addon_name_for, installed_addons, is_canonical,
                                                parse_addons_txt, scan)


class NameTest(unittest.TestCase):
    def test_addon_name_for(self):
        cases = {"Auctionator.lua": "Auctionator", "Foo.LUA.bak": "Foo", "Foo.lua - Copy.bak": "Foo",
                 "!BugGrabber.lua": "!BugGrabber", "[Weird] Addon.lua": "[Weird] Addon",
                 "notes.txt": None, ".lua": None}
        for filename, expected in cases.items():
            with self.subTest(filename):
                self.assertEqual(addon_name_for(filename), expected)

    def test_is_canonical(self):
        self.assertTrue(is_canonical("Foo.lua", "Foo"))
        self.assertTrue(is_canonical("Foo.lua.bak", "Foo"))
        self.assertFalse(is_canonical("Foo.lua.pre-schema8-20260926-103400", "Foo"))
        self.assertFalse(is_canonical("Foo.lua - Copy.bak", "Foo"))


class ScannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.install = WowInstall(build_wow_tree(Path(tmp.name) / "World of Warcraft"))
        self.retail = self.install.flavor("retail")

    def test_installed_addons_needs_a_toc(self):
        self.assertEqual(installed_addons(self.retail.addons_dir), {
            "auctionator": "Auctionator", "details": "Details",
            "disabledaddon": "DisabledAddon", "oldaddon": "OldAddon"})

    def test_parse_addons_txt_warns_on_garbage(self):
        warnings = []
        path = self.retail.account_dir / "ACCT2" / "Realm2" / "Chârb" / "AddOns.txt"
        states = parse_addons_txt(path, warnings)
        self.assertFalse(states["details"])
        self.assertTrue(states["auctionator"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("garbage line", warnings[0].message)

    def test_enabled_is_global_union(self):
        self.assertEqual(scan(self.retail).enabled, {"auctionator", "details", "oldaddon"})

    def test_unlisted_installed_addon_counts_as_enabled(self):
        (self.retail.account_dir / "ACCT1" / "Realm1" / "CharA" / "AddOns.txt").write_text(
            "Auctionator: enabled\n", encoding="utf-8")
        self.assertIn("disabledaddon", scan(self.retail).enabled)

    def test_character_without_addons_txt_enables_everything(self):
        self.assertEqual(scan(self.install.flavor("classic_era")).enabled, {"questie"})

    def test_groups_counts_and_events(self):
        with capture_events() as records:
            result = scan(self.retail)
        self.assertCountEqual([(g.account, g.owner_label, g.addon) for g in result.groups], [
            ("ACCT1", "account-wide", "Auctionator"), ("ACCT1", "account-wide", "Details"),
            ("ACCT1", "account-wide", "DisabledAddon"), ("ACCT1", "account-wide", "OldAddon"),
            ("ACCT1", "account-wide", "Uninstalled"), ("ACCT1", "Realm1/CharA", "Auctionator"),
            ("ACCT1", "Realm1/CharA", "Uninstalled"), ("ACCT2", "account-wide", "Details"),
            ("ACCT2", "Realm2/Chârb", "Details")])
        self.assertEqual((result.sv_files, result.accounts, result.characters), (14, 2, 2))
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "scan.started")
        self.assertIn("scan.addons", names)
        self.assertIn("scan.warning", names)
        completed = [r for r in records if r["event"] == "scan.completed"][0]["data"]
        self.assertEqual((completed["groups"], completed["sv_files"], completed["installed"]), (9, 14, 4))

    def test_blizzard_and_non_sv_files_are_never_scanned(self):
        names = {f.name for g in scan(self.retail).groups for f in g.files}
        for never in ("Blizzard_Foo.lua", "notes.txt", "config-cache.wtf", "AddOns.txt"):
            self.assertNotIn(never, names)

    def test_stray_files_are_not_canonical(self):
        group = next(g for g in scan(self.retail).groups
                     if g.addon == "Auctionator" and g.character is None)
        self.assertEqual({f.name: f.canonical for f in group.files}, {
            "Auctionator.lua": True, "Auctionator.lua.bak": True,
            "Auctionator.lua.pre-schema8-20260926-103400": False})

    def test_empty_addons_folder_aborts(self):
        with self.assertRaises(ScanError):
            scan(self.install.flavor("anniversary"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_scanner -v`
Expected: ERROR, `No module named 'wowtools.tools'`.

- [ ] **Step 3: Implement**

`wowtools/tools/__init__.py`:
```python
"""Tools that ship with the suite."""
```

`wowtools/tools/wtf_cleaner/__init__.py`:
```python
"""WTF Cleaner: find and remove stale addon SavedVariables, with backups."""
from wowtools.tools.wtf_cleaner import events as _events  # noqa: F401  registers this tool's events
```

`wowtools/tools/wtf_cleaner/events.py`:
```python
"""Events emitted by the WTF Cleaner. Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events

TOOL_NAME = "wtf-cleaner"

EVENTS: dict[str, EventSpec] = {
    "scan.started": EventSpec("info", "A scan of one flavor started."),
    "scan.addons": EventSpec("debug", "Installed and enabled addon lists found by the scan."),
    "scan.completed": EventSpec("info", "A scan finished, with counts."),
    "scan.warning": EventSpec("warning", "Something was skipped during a scan (unreadable folder, bad AddOns.txt line)."),
    "proposal.built": EventSpec("info", "The cleanup proposal was built from scan results and criteria."),
    "proposal.item": EventSpec("debug", "One addon group in the proposal."),
    "clean.started": EventSpec("info", "A clean (or dry run) started."),
    "backup.created": EventSpec("info", "A backup zip was written and verified."),
    "backup.would_create": EventSpec("info", "Dry run: the backup zip that would have been written."),
    "backup.failed": EventSpec("error", "The backup failed; nothing was deleted."),
    "sv.deleted": EventSpec("info", "A SavedVariables file was deleted."),
    "sv.would_delete": EventSpec("info", "Dry run: a SavedVariables file that would have been deleted."),
    "sv.skipped": EventSpec("warning", "A selected file was skipped because it vanished or changed after the scan."),
    "sv.failed": EventSpec("error", "A SavedVariables file could not be deleted."),
    "clean.completed": EventSpec("info", "A clean finished (logged at warning if any file failed)."),
}

register_events(TOOL_NAME, EVENTS)
```

`wowtools/tools/wtf_cleaner/scanner.py`:
```python
"""Find installed and enabled addons and group every SavedVariables file by addon."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from wowtools.core.events import log_event
from wowtools.core.install import ACCOUNT_WIDE, Account, Character, Flavor

PROTECTED_PREFIXES = ("blizzard_",)
_LUA = re.compile(r"\.lua", re.IGNORECASE)


class ScanError(Exception):
    """The flavor cannot be scanned safely."""


@dataclass(frozen=True)
class ScanWarning:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class SVFile:
    path: Path
    size: int
    mtime: float
    canonical: bool

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class SVGroup:
    account: str
    character: Character | None
    addon: str
    files: list[SVFile] = field(default_factory=list)

    @property
    def scope(self) -> str:
        return "character" if self.character else "account"

    @property
    def owner_label(self) -> str:
        return self.character.label if self.character else ACCOUNT_WIDE

    @property
    def key(self) -> str:
        return f"{self.account}|{self.owner_label}|{self.addon.casefold()}"

    @property
    def newest_mtime(self) -> float:
        return max(f.mtime for f in self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


@dataclass
class ScanResult:
    flavor: Flavor
    installed: dict[str, str]
    enabled: set[str]
    groups: list[SVGroup]
    accounts: int
    characters: int
    warnings: list[ScanWarning]

    @property
    def sv_files(self) -> int:
        return sum(len(g.files) for g in self.groups)


def addon_name_for(filename: str) -> str | None:
    """Everything before the first '.lua' (any case); None if there is no addon name."""
    match = _LUA.search(filename)
    if not match or match.start() == 0:
        return None
    return filename[:match.start()]


def is_canonical(filename: str, addon: str) -> bool:
    """True for the only two names WoW itself writes: <Addon>.lua and <Addon>.lua.bak."""
    return filename.casefold() in {f"{addon}.lua".casefold(), f"{addon}.lua.bak".casefold()}


def installed_addons(addons_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        entries = list(addons_dir.iterdir())
    except OSError:
        return result
    for folder in entries:
        try:
            if folder.is_dir() and any(p.suffix.lower() == ".toc" for p in folder.iterdir()):
                result[folder.name.casefold()] = folder.name
        except OSError:
            continue
    return result


def parse_addons_txt(path: Path, warnings: list[ScanWarning] | None = None) -> dict[str, bool]:
    """Parse 'Name: enabled|disabled' lines. Keys are casefolded addon names."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    states: dict[str, bool] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        name, sep, state = line.rpartition(":")
        state = state.strip().lower()
        if not sep or not name.strip() or state not in ("enabled", "disabled"):
            if warnings is not None:
                warnings.append(ScanWarning(str(path), f"line {lineno} not understood: {raw!r}"))
            continue
        states[name.strip().casefold()] = state == "enabled"
    return states


def enabled_addons(characters: Iterable[Character], installed: dict[str, str],
                   warnings: list[ScanWarning]) -> set[str]:
    """Global union: enabled on any character. Unlisted or no AddOns.txt means WoW's default (on)."""
    enabled: set[str] = set()
    for character in characters:
        if not character.addons_txt.is_file():
            enabled.update(installed)
            continue
        try:
            states = parse_addons_txt(character.addons_txt, warnings)
        except OSError as exc:
            warnings.append(ScanWarning(str(character.addons_txt), f"cannot read: {exc}"))
            enabled.update(installed)
            continue
        enabled.update(name for name, on in states.items() if on)
        enabled.update(name for name in installed if name not in states)
    return enabled


def _scan_sv_dir(sv_dir: Path, account: Account, character: Character | None,
                 warnings: list[ScanWarning]) -> list[SVGroup]:
    if not sv_dir.is_dir():
        return []
    try:
        entries = sorted(sv_dir.iterdir(), key=lambda p: p.name.casefold())
    except OSError as exc:
        warnings.append(ScanWarning(str(sv_dir), f"cannot read folder: {exc}"))
        return []
    groups: dict[str, SVGroup] = {}
    for path in entries:
        addon = addon_name_for(path.name)
        if addon is None or addon.casefold().startswith(PROTECTED_PREFIXES):
            continue
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError as exc:
            warnings.append(ScanWarning(str(path), f"cannot read file: {exc}"))
            continue
        group = groups.setdefault(addon.casefold(), SVGroup(account.name, character, addon))
        group.files.append(SVFile(path, stat.st_size, stat.st_mtime, is_canonical(path.name, addon)))
    return list(groups.values())


def scan(flavor: Flavor) -> ScanResult:
    started = time.monotonic()
    log_event("scan.started", flavor=flavor.folder, wow_path=str(flavor.path.parent))
    installed = installed_addons(flavor.addons_dir)
    if not installed:
        raise ScanError(f"No addons found in {flavor.addons_dir}. Refusing to scan: every "
                        "SavedVariables file would look uninstalled.")
    warnings: list[ScanWarning] = []

    def on_error(path: Path, exc: OSError) -> None:
        warnings.append(ScanWarning(str(path), f"cannot read folder: {exc}"))

    accounts = flavor.accounts(on_error)
    characters = [c for account in accounts for c in account.characters(on_error)]
    enabled = enabled_addons(characters, installed, warnings)
    log_event("scan.addons", installed=sorted(installed.values(), key=str.casefold), enabled=sorted(enabled))

    groups: list[SVGroup] = []
    for account in accounts:
        groups += _scan_sv_dir(account.saved_variables_dir, account, None, warnings)
        for character in (c for c in characters if c.account == account.name):
            groups += _scan_sv_dir(character.saved_variables_dir, account, character, warnings)

    for warning in warnings:
        log_event("scan.warning", path=warning.path, message=warning.message)
    result = ScanResult(flavor, installed, enabled, groups, len(accounts), len(characters), warnings)
    log_event("scan.completed", flavor=flavor.folder, installed=len(installed), enabled=len(enabled),
              accounts=len(accounts), characters=len(characters), sv_files=result.sv_files,
              groups=len(groups), duration_s=round(time.monotonic() - started, 3))
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_scanner -v`
Expected: 11 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools tests/test_scanner.py
git commit -m "feat(wtf-cleaner): scanner for installed/enabled addons and SV groups"
```

---

### Task 9: Rules, settings and text/JSON report

**Files:**
- Create: `wowtools/tools/wtf_cleaner/rules.py`, `wowtools/tools/wtf_cleaner/settings.py`, `wowtools/tools/wtf_cleaner/report.py`, `tests/test_rules.py`

**Interfaces:**
- Consumes: `ScanResult`, `SVGroup`, `SVFile` (Task 8); `Config` (Task 4); `Flavor` (Task 5).
- Produces:
  - `rules`:
    - `CRITERIA`, `DAY`.
    - `Criteria(not_installed=True, not_enabled=True, older_than=True, stray_copies=True, max_age_days=90)` with `.enabled_names()`, `.describe()`, `.copy()`, and the classmethod `from_names(names, max_age_days=90)` (raises `ValueError`).
    - `ProposalItem(group, files, reasons)` with `.account`, `.character`, `.addon`, `.scope`, `.owner_label`, `.key`, `.total_size`, `.newest_mtime`, `.with_files(files)`.
    - `Proposal(items, criteria, warnings)` with `.total_files`, `.total_size`, `.by_reason()`.
    - `evaluate(scan: ScanResult, criteria: Criteria, *, now: float | None = None) -> Proposal`.
  - `settings`: `SECTION = "wtf_cleaner"`, `CleanerSettings(criteria: Criteria, backup_before_delete: bool = True)`, `load_settings(cfg) -> CleanerSettings`, `save_settings(cfg, settings, *, source="settings") -> None`.
  - `report`: `CRITERION_LABELS`, `CRITERION_SHORT`, `format_size(n: int) -> str`, `age_days(mtime: float, now: float) -> int`, `proposal_to_dict(proposal, flavor, now=None) -> dict`, `format_proposal_text(proposal, flavor, now=None) -> str`. The result helpers are added in Task 10.

- [ ] **Step 1: Write the failing tests**

`tests/test_rules.py`:
```python
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import NOW, build_wow_tree
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.report import format_proposal_text, format_size, proposal_to_dict
from wowtools.tools.wtf_cleaner.rules import Criteria, evaluate
from wowtools.tools.wtf_cleaner.scanner import scan
from wowtools.tools.wtf_cleaner.settings import SECTION, load_settings, save_settings


class RulesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.retail = WowInstall(build_wow_tree(self.tmp / "World of Warcraft")).flavor("retail")
        self.sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        self.scan = scan(self.retail)

    def summary(self, proposal):
        return [(i.account, i.owner_label, i.addon, tuple(i.reasons), tuple(sorted(f.name for f in i.files)))
                for i in proposal.items]

    def test_default_criteria_flag_any_match(self):
        proposal = evaluate(self.scan, Criteria(), now=NOW)
        self.assertCountEqual(self.summary(proposal), [
            ("ACCT1", "account-wide", "Auctionator", ("stray_copies",), ("Auctionator.lua.pre-schema8-20260926-103400",)),
            ("ACCT1", "account-wide", "Details", ("stray_copies",), ("Details.lua - Copy.bak",)),
            ("ACCT1", "account-wide", "DisabledAddon", ("not_enabled",), ("DisabledAddon.lua",)),
            ("ACCT1", "account-wide", "OldAddon", ("older_than",), ("OldAddon.lua", "OldAddon.lua.bak")),
            ("ACCT1", "account-wide", "Uninstalled", ("not_installed",), ("Uninstalled.lua", "Uninstalled.lua.bak")),
            ("ACCT1", "Realm1/CharA", "Uninstalled", ("not_installed",), ("Uninstalled.lua",)),
        ])
        self.assertEqual(proposal.total_files, 8)
        self.assertEqual(proposal.by_reason(), {"not_installed": 2, "not_enabled": 1, "older_than": 1, "stray_copies": 2})

    def test_each_criterion_alone(self):
        expected = {"not_installed": {"Uninstalled"}, "not_enabled": {"DisabledAddon"},
                    "older_than": {"OldAddon"}, "stray_copies": {"Auctionator", "Details"}}
        for name, addons in expected.items():
            with self.subTest(name):
                proposal = evaluate(self.scan, Criteria.from_names([name]), now=NOW)
                self.assertEqual({i.addon for i in proposal.items}, addons)

    def test_no_criteria_proposes_nothing(self):
        self.assertEqual(evaluate(self.scan, Criteria.from_names([]), now=NOW).items, [])

    def test_age_uses_newest_file_in_group(self):
        os.utime(self.sv / "OldAddon.lua", (NOW, NOW))
        proposal = evaluate(scan(self.retail), Criteria.from_names(["older_than"]), now=NOW)
        self.assertEqual(proposal.items, [])

    def test_max_age_threshold(self):
        proposal = evaluate(self.scan, Criteria.from_names(["older_than"], max_age_days=250), now=NOW)
        self.assertEqual(proposal.items, [])

    def test_flagged_group_with_strays_lists_both_reasons(self):
        (self.sv / "Uninstalled.lua.old").write_text("x")
        proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        item = next(i for i in proposal.items if i.addon == "Uninstalled" and i.character is None)
        self.assertEqual(item.reasons, ["not_installed", "stray_copies"])
        self.assertEqual(len(item.files), 3)

    def test_unknown_criterion_rejected(self):
        with self.assertRaises(ValueError):
            Criteria.from_names(["bogus"])

    def test_proposal_events(self):
        with capture_events() as records:
            evaluate(self.scan, Criteria(), now=NOW)
        built = [r for r in records if r["event"] == "proposal.built"]
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["data"]["items"], 6)
        self.assertEqual(len([r for r in records if r["event"] == "proposal.item"]), 6)

    def test_describe(self):
        self.assertEqual(Criteria().describe(), "not_installed, not_enabled, older_than(90d), stray_copies")
        self.assertEqual(Criteria.from_names([]).describe(), "none")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "c.cfg"

    def test_defaults_and_round_trip(self):
        cfg = Config(self.path)
        settings = load_settings(cfg)
        self.assertEqual(settings.criteria, Criteria())
        self.assertTrue(settings.backup_before_delete)
        settings.criteria.not_enabled = False
        settings.criteria.max_age_days = 30
        save_settings(cfg, settings)
        again = load_settings(Config(self.path).load())
        self.assertFalse(again.criteria.not_enabled)
        self.assertEqual(again.criteria.max_age_days, 30)

    def test_bad_values_fall_back(self):
        cfg = Config(self.path)
        cfg.set(SECTION, "max_age_days", "0")
        cfg.set(SECTION, "criterion_older_than", "perhaps")
        settings = load_settings(cfg)
        self.assertEqual(settings.criteria.max_age_days, 1)
        self.assertTrue(settings.criteria.older_than)
        cfg.set(SECTION, "max_age_days", "soon")
        self.assertEqual(load_settings(cfg).criteria.max_age_days, 90)


class ReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.retail = WowInstall(build_wow_tree(Path(tmp.name) / "World of Warcraft")).flavor("retail")

    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1023), "1023 B")
        self.assertEqual(format_size(1536), "1.5 KB")
        self.assertEqual(format_size(5 * 1024 * 1024), "5.0 MB")

    def test_proposal_text_and_json(self):
        proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        text = format_proposal_text(proposal, self.retail, now=NOW)
        self.assertIn("ACCT1 · account-wide", text)
        self.assertIn("ACCT1 · Realm1/CharA", text)
        self.assertIn("Total: 6 items, 8 files", text)
        data = proposal_to_dict(proposal, self.retail, now=NOW)
        json.dumps(data)
        self.assertEqual(data["flavor"], "_retail_")
        self.assertEqual(data["totals"]["files"], 8)
        self.assertEqual(len(data["items"]), 6)

    def test_names_with_brackets_survive(self):
        (self.retail.account_dir / "ACCT1" / "SavedVariables" / "[Weird] Addon.lua").write_text("x")
        proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        self.assertIn("[Weird] Addon", {i.addon for i in proposal.items})
        self.assertIn("[Weird] Addon", format_proposal_text(proposal, self.retail, now=NOW))

    def test_empty_proposal_text(self):
        proposal = evaluate(scan(self.retail), Criteria.from_names([]), now=NOW)
        self.assertIn("Nothing to clean.", format_proposal_text(proposal, self.retail, now=NOW))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_rules -v`
Expected: ERROR, `No module named 'wowtools.tools.wtf_cleaner.rules'`.

- [ ] **Step 3: Implement**

`wowtools/tools/wtf_cleaner/rules.py`:
```python
"""Turn scan results into a cleanup proposal using the four toggleable criteria."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Iterable

from wowtools.core.events import log_event
from wowtools.core.install import Character
from wowtools.tools.wtf_cleaner.scanner import ScanResult, ScanWarning, SVFile, SVGroup

CRITERIA = ("not_installed", "not_enabled", "older_than", "stray_copies")
DAY = 86400.0


@dataclass
class Criteria:
    not_installed: bool = True
    not_enabled: bool = True
    older_than: bool = True
    stray_copies: bool = True
    max_age_days: int = 90

    @classmethod
    def from_names(cls, names: Iterable[str], max_age_days: int = 90) -> Criteria:
        wanted = set(names)
        unknown = wanted - set(CRITERIA)
        if unknown:
            raise ValueError(f"unknown criteria: {', '.join(sorted(unknown))} "
                             f"(choose from {', '.join(CRITERIA)})")
        return cls(**{name: name in wanted for name in CRITERIA}, max_age_days=max_age_days)

    def enabled_names(self) -> list[str]:
        return [name for name in CRITERIA if getattr(self, name)]

    def describe(self) -> str:
        parts = [f"older_than({self.max_age_days}d)" if n == "older_than" else n for n in self.enabled_names()]
        return ", ".join(parts) or "none"

    def copy(self) -> Criteria:
        return replace(self)


@dataclass
class ProposalItem:
    group: SVGroup
    files: list[SVFile]
    reasons: list[str]

    @property
    def account(self) -> str:
        return self.group.account

    @property
    def character(self) -> Character | None:
        return self.group.character

    @property
    def addon(self) -> str:
        return self.group.addon

    @property
    def scope(self) -> str:
        return self.group.scope

    @property
    def owner_label(self) -> str:
        return self.group.owner_label

    @property
    def key(self) -> str:
        return self.group.key

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def newest_mtime(self) -> float:
        return max(f.mtime for f in self.files)

    def with_files(self, files: Iterable[SVFile]) -> ProposalItem:
        return ProposalItem(self.group, list(files), list(self.reasons))


@dataclass
class Proposal:
    items: list[ProposalItem]
    criteria: Criteria
    warnings: list[ScanWarning] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        return sum(len(i.files) for i in self.items)

    @property
    def total_size(self) -> int:
        return sum(i.total_size for i in self.items)

    def by_reason(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            for reason in item.reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return counts


def _group_reasons(group: SVGroup, scan: ScanResult, criteria: Criteria, now: float) -> list[str]:
    key = group.addon.casefold()
    reasons = []
    if criteria.not_installed and key not in scan.installed:
        reasons.append("not_installed")
    if criteria.not_enabled and key in scan.installed and key not in scan.enabled:
        reasons.append("not_enabled")
    if criteria.older_than and now - group.newest_mtime > criteria.max_age_days * DAY:
        reasons.append("older_than")
    return reasons


def evaluate(scan: ScanResult, criteria: Criteria, *, now: float | None = None) -> Proposal:
    now = time.time() if now is None else now
    items: list[ProposalItem] = []
    for group in scan.groups:
        reasons = _group_reasons(group, scan, criteria, now)
        strays = [f for f in group.files if not f.canonical]
        if reasons:
            if criteria.stray_copies and strays:
                reasons.append("stray_copies")
            items.append(ProposalItem(group, list(group.files), reasons))
        elif criteria.stray_copies and strays:
            items.append(ProposalItem(group, strays, ["stray_copies"]))
    proposal = Proposal(items, criteria.copy(), list(scan.warnings))
    log_event("proposal.built", flavor=scan.flavor.folder, criteria=criteria.enabled_names(),
              max_age_days=criteria.max_age_days, items=len(items), files=proposal.total_files,
              bytes=proposal.total_size, by_reason=proposal.by_reason())
    for item in items:
        log_event("proposal.item", account=item.account, character=item.owner_label, addon=item.addon,
                  reasons=item.reasons, files=[f.name for f in item.files])
    return proposal
```

`wowtools/tools/wtf_cleaner/settings.py`:
```python
"""The [wtf_cleaner] section of wow-tools.cfg."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowtools.core.config import Config
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria

SECTION = "wtf_cleaner"


@dataclass
class CleanerSettings:
    criteria: Criteria = field(default_factory=Criteria)
    backup_before_delete: bool = True


def load_settings(cfg: Config) -> CleanerSettings:
    criteria = Criteria(**{name: cfg.get_bool(SECTION, f"criterion_{name}", True) for name in CRITERIA},
                        max_age_days=max(1, cfg.get_int(SECTION, "max_age_days", 90)))
    return CleanerSettings(criteria, cfg.get_bool(SECTION, "backup_before_delete", True))


def save_settings(cfg: Config, settings: CleanerSettings, *, source: str = "settings") -> None:
    cfg.set(SECTION, "max_age_days", settings.criteria.max_age_days, source=source)
    for name in CRITERIA:
        cfg.set(SECTION, f"criterion_{name}", getattr(settings.criteria, name), source=source)
    cfg.set(SECTION, "backup_before_delete", settings.backup_before_delete, source=source)
    cfg.save()
```

`wowtools/tools/wtf_cleaner/report.py`:
```python
"""Human and machine renderings of proposals and clean results (shared by CLI and TUI)."""
from __future__ import annotations

import time

from wowtools.core.install import ACCOUNT_WIDE, Flavor
from wowtools.tools.wtf_cleaner.rules import Proposal

DAY = 86400.0

CRITERION_LABELS = {
    "not_installed": "Addon is not installed",
    "not_enabled": "Addon is installed but not enabled on any character",
    "older_than": "SavedVariables are older than the age limit",
    "stray_copies": "Hand-made copies (anything but <Addon>.lua / <Addon>.lua.bak)",
}
CRITERION_SHORT = {
    "not_installed": "Not installed",
    "not_enabled": "Not enabled",
    "older_than": "Older than max age",
    "stray_copies": "Stray copies",
}


def format_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def age_days(mtime: float, now: float) -> int:
    return max(0, int((now - mtime) // DAY))


def _sort_key(item) -> tuple:
    return (item.account.casefold(), item.owner_label != ACCOUNT_WIDE, item.owner_label.casefold(),
            item.addon.casefold())


def proposal_to_dict(proposal: Proposal, flavor: Flavor, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return {
        "flavor": flavor.folder,
        "criteria": proposal.criteria.enabled_names(),
        "max_age_days": proposal.criteria.max_age_days,
        "totals": {"items": len(proposal.items), "files": proposal.total_files, "bytes": proposal.total_size},
        "by_reason": proposal.by_reason(),
        "items": [{
            "account": item.account,
            "character": item.owner_label if item.character else None,
            "addon": item.addon,
            "scope": item.scope,
            "reasons": item.reasons,
            "bytes": item.total_size,
            "age_days": age_days(item.newest_mtime, now),
            "files": [{"path": str(f.path), "size": f.size, "mtime": f.mtime} for f in item.files],
        } for item in sorted(proposal.items, key=_sort_key)],
        "warnings": [str(w) for w in proposal.warnings],
    }


def format_proposal_text(proposal: Proposal, flavor: Flavor, now: float | None = None) -> str:
    now = time.time() if now is None else now
    lines = [f"WTF Cleaner · {flavor.display_name} ({flavor.folder})",
             f"Criteria: {proposal.criteria.describe()}", ""]
    if not proposal.items:
        lines.append("Nothing to clean.")
    heading = None
    for item in sorted(proposal.items, key=_sort_key):
        current = f"{item.account} · {item.owner_label}"
        if current != heading:
            lines.append(current)
            heading = current
        lines.append(f"  {item.addon:<32} {', '.join(item.reasons):<30} {len(item.files):>3} files "
                     f"{format_size(item.total_size):>9} {age_days(item.newest_mtime, now):>5}d")
    lines += ["", f"Total: {len(proposal.items)} items, {proposal.total_files} files, "
                  f"{format_size(proposal.total_size)}"]
    for warning in proposal.warnings:
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_rules -v`
Expected: 16 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools/wtf_cleaner/rules.py wowtools/tools/wtf_cleaner/settings.py wowtools/tools/wtf_cleaner/report.py tests/test_rules.py
git commit -m "feat(wtf-cleaner): criteria rules, settings section, proposal report"
```

---

### Task 10: Clean pipeline (recheck, guard, backup, delete / simulate)

**Files:**
- Create: `wowtools/tools/wtf_cleaner/cleaner.py`, `tests/test_cleaner.py`
- Modify: `wowtools/tools/wtf_cleaner/report.py` (append the result helpers)

**Interfaces:**
- Consumes: `ProposalItem` (Task 9); `create_backup`, `BackupEntry`, `BackupError`, `backup_filename` (Task 6); `Flavor` (Task 5); `log_event` (Task 3).
- Produces:
  - `CleanError`.
  - `FileOutcome(path: Path, size: int, status: str, detail: str = "", reasons: tuple[str, ...] = ())`, where `status` is one of `deleted`, `would_delete`, `skipped`, `failed`.
  - `CleanResult(dry_run: bool, backup_path: Path | None, outcomes: list[FileOutcome])` with `.deleted`, `.would_delete`, `.skipped`, `.failed` (lists) and `.bytes_freed`.
  - `execute(items, flavor, *, dry_run: bool, backup: bool, backup_dir: Path | None, now: datetime | None = None) -> CleanResult`. It raises `BackupError` (nothing deleted) or `CleanError` (the guard tripped, nothing touched).
  - In `report`: `result_to_dict(result) -> dict`, `format_result_text(result) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cleaner.py`:
```python
import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import NOW, build_wow_tree
from wowtools.core.backup import BackupError
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.cleaner import CleanError, execute
from wowtools.tools.wtf_cleaner.report import format_result_text, result_to_dict
from wowtools.tools.wtf_cleaner.rules import Criteria, ProposalItem, evaluate
from wowtools.tools.wtf_cleaner.scanner import SVFile, scan

WHEN = datetime(2026, 9, 27, 14, 3, 11)


def snapshot(root: Path) -> dict:
    result = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            stat = path.stat()
            result[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime)
    return result


class CleanerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.retail = WowInstall(self.root).flavor("retail")
        self.sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        self.proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        self.backup_dir = self.tmp / "backups"

    def paths(self):
        return [f.path for item in self.proposal.items for f in item.files]

    def item(self, addon, owner="account-wide"):
        return next(i for i in self.proposal.items if i.addon == addon and i.owner_label == owner)

    def test_clean_backs_up_then_deletes(self):
        with capture_events() as records:
            result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                             backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(len(result.deleted), 8)
        for path in self.paths():
            self.assertFalse(path.exists(), path)
        self.assertEqual(result.backup_path, self.backup_dir / "wtf-cleaner_retail_20260927-140311.zip")
        with zipfile.ZipFile(result.backup_path) as zf:
            self.assertEqual(len(zf.namelist()), 9)
        for kept in ("Auctionator.lua", "Auctionator.lua.bak", "Details.lua", "Blizzard_Foo.lua"):
            self.assertTrue((self.sv / kept).exists(), kept)
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "clean.started")
        self.assertEqual(names[-1], "clean.completed")
        self.assertEqual(names.count("sv.deleted"), 8)
        self.assertIn("backup.created", names)
        self.assertLess(names.index("backup.created"), names.index("sv.deleted"))

    def test_dry_run_touches_nothing(self):
        before = snapshot(self.root)
        with capture_events() as records:
            result = execute(self.proposal.items, self.retail, dry_run=True, backup=True,
                             backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.backup_dir.exists())
        self.assertTrue(result.dry_run)
        self.assertEqual(len(result.would_delete), 8)
        self.assertEqual(result.deleted, [])
        would = [r for r in records if r["event"] == "sv.would_delete"]
        self.assertEqual(len(would), 8)
        self.assertTrue(all(r["dry_run"] for r in would))
        self.assertIn("backup.would_create", [r["event"] for r in records])
        self.assertIn("DRY RUN", format_result_text(result))

    def test_changed_and_missing_files_are_skipped(self):
        (self.sv / "Uninstalled.lua").write_text("written by WoW after the scan, longer than before")
        (self.sv / "Uninstalled.lua.bak").unlink()
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                         backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(sorted(o.detail for o in result.skipped), ["changed", "missing"])
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertEqual(len(result.deleted), 6)
        with zipfile.ZipFile(result.backup_path) as zf:
            self.assertNotIn("WTF/Account/ACCT1/SavedVariables/Uninstalled.lua", zf.namelist())

    def test_backup_failure_deletes_nothing(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("a file where the backup folder should be")
        with capture_events() as records:
            with self.assertRaises(BackupError):
                execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                        backup_dir=blocker / "sub", now=WHEN)
        for path in self.paths():
            self.assertTrue(path.exists(), path)
        self.assertIn("backup.failed", [r["event"] for r in records])

    def test_without_backup(self):
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=False,
                         backup_dir=self.backup_dir, now=WHEN)
        self.assertIsNone(result.backup_path)
        self.assertEqual(len(result.deleted), 8)
        self.assertFalse(self.backup_dir.exists())

    def test_empty_selection_makes_no_backup(self):
        result = execute([], self.retail, dry_run=False, backup=True, backup_dir=self.backup_dir, now=WHEN)
        self.assertIsNone(result.backup_path)
        self.assertEqual(result.outcomes, [])
        self.assertFalse(self.backup_dir.exists())

    def test_path_guard_rejects_files_outside_savedvariables(self):
        outside = self.retail.account_dir / "ACCT1" / "config-cache.wtf"
        stat = outside.stat()
        rogue = ProposalItem(self.item("DisabledAddon").group,
                             [SVFile(outside, stat.st_size, stat.st_mtime, False)], ["not_enabled"])
        with self.assertRaises(CleanError):
            execute([rogue], self.retail, dry_run=False, backup=False, backup_dir=None, now=WHEN)
        self.assertTrue(outside.exists())

    @unittest.skipIf(os.name == "nt", "symlinks need admin rights on Windows")
    def test_symlink_escaping_wtf_is_rejected(self):
        target = self.tmp / "elsewhere.lua"
        target.write_text("precious")
        (self.sv / "Evil.lua").symlink_to(target)
        proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        with self.assertRaises(CleanError):
            execute(proposal.items, self.retail, dry_run=False, backup=False, backup_dir=None, now=WHEN)
        self.assertTrue(target.exists())
        self.assertTrue((self.sv / "DisabledAddon.lua").exists())

    def test_delete_failure_is_reported_and_others_continue(self):
        original = Path.unlink

        def flaky(path, *args, **kwargs):
            if path.name == "DisabledAddon.lua":
                raise PermissionError("locked by another program")
            return original(path, *args, **kwargs)

        with capture_events() as records:
            with patch.object(Path, "unlink", flaky):
                result = execute(self.proposal.items, self.retail, dry_run=False, backup=False,
                                 backup_dir=None, now=WHEN)
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(len(result.deleted), 7)
        completed = [r for r in records if r["event"] == "clean.completed"][0]
        self.assertEqual(completed["level"], "warning")
        self.assertIn("sv.failed", [r["event"] for r in records])

    def test_result_dict(self):
        result = execute(self.proposal.items, self.retail, dry_run=True, backup=True,
                         backup_dir=self.backup_dir, now=WHEN)
        data = result_to_dict(result)
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["counts"]["would_delete"], 8)
        self.assertEqual(len(data["outcomes"]), 8)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_cleaner -v`
Expected: ERROR, `No module named 'wowtools.tools.wtf_cleaner.cleaner'`.

- [ ] **Step 3: Implement**

`wowtools/tools/wtf_cleaner/cleaner.py`:
```python
"""Execute a selection: recheck, guard, back up (verified), then delete, or simulate all of it."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools import __version__
from wowtools.core.backup import BackupEntry, BackupError, backup_filename, create_backup
from wowtools.core.events import log_event
from wowtools.core.install import Flavor
from wowtools.tools.wtf_cleaner.events import TOOL_NAME
from wowtools.tools.wtf_cleaner.rules import ProposalItem
from wowtools.tools.wtf_cleaner.scanner import SVFile


class CleanError(Exception):
    """A selected path is not a SavedVariables file inside WTF/Account. Nothing was touched."""


@dataclass(frozen=True)
class FileOutcome:
    path: Path
    size: int
    status: str
    detail: str = ""
    reasons: tuple[str, ...] = ()


@dataclass
class CleanResult:
    dry_run: bool
    backup_path: Path | None
    outcomes: list[FileOutcome] = field(default_factory=list)

    def _with(self, status: str) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def deleted(self) -> list[FileOutcome]:
        return self._with("deleted")

    @property
    def would_delete(self) -> list[FileOutcome]:
        return self._with("would_delete")

    @property
    def skipped(self) -> list[FileOutcome]:
        return self._with("skipped")

    @property
    def failed(self) -> list[FileOutcome]:
        return self._with("failed")

    @property
    def bytes_freed(self) -> int:
        return sum(o.size for o in self.outcomes if o.status in ("deleted", "would_delete"))


def _guard(path: Path, flavor: Flavor) -> None:
    root = flavor.account_dir.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise CleanError(f"Refusing to touch {path}: it is outside {flavor.account_dir}") from None
    if resolved.parent.name != "SavedVariables":
        raise CleanError(f"Refusing to touch {path}: it is not inside a SavedVariables folder")


def _recheck(sv: SVFile) -> str | None:
    try:
        stat = sv.path.stat()
    except OSError:
        return "missing"
    if stat.st_size != sv.size or stat.st_mtime != sv.mtime:
        return "changed"
    return None


def _relative(path: Path, flavor: Flavor) -> str:
    try:
        return path.relative_to(flavor.path).as_posix()
    except ValueError:
        return str(path)


def execute(items: list[ProposalItem], flavor: Flavor, *, dry_run: bool, backup: bool,
            backup_dir: Path | None, now: datetime | None = None) -> CleanResult:
    now = now or datetime.now()
    selected = [(item, sv) for item in items for sv in item.files]
    log_event("clean.started", dry_run=dry_run, flavor=flavor.folder, items=len(items), files=len(selected),
              bytes=sum(sv.size for _, sv in selected), backup=backup)
    for _, sv in selected:
        _guard(sv.path, flavor)

    result = CleanResult(dry_run=dry_run, backup_path=None)
    ready: list[tuple[ProposalItem, SVFile]] = []
    for item, sv in selected:
        problem = _recheck(sv)
        if problem:
            result.outcomes.append(FileOutcome(sv.path, sv.size, "skipped", problem, tuple(item.reasons)))
            log_event("sv.skipped", dry_run=dry_run, path=_relative(sv.path, flavor), reason=problem)
        else:
            ready.append((item, sv))

    if backup and ready:
        if backup_dir is None:
            raise BackupError("no backup folder is configured")
        dest = backup_dir / backup_filename(TOOL_NAME, flavor.short_name, now)
        ready_bytes = sum(sv.size for _, sv in ready)
        if dry_run:
            log_event("backup.would_create", dry_run=True, zip=str(dest), files=len(ready), bytes=ready_bytes)
        else:
            meta = {"tool": TOOL_NAME, "suite_version": __version__, "flavor": flavor.folder,
                    "created": now.isoformat(timespec="seconds")}
            try:
                create_backup([BackupEntry(sv.path, tuple(item.reasons)) for item, sv in ready],
                              flavor.path, dest, meta)
            except BackupError as exc:
                log_event("backup.failed", zip=str(dest), error=str(exc))
                raise
            log_event("backup.created", zip=str(dest), files=len(ready), bytes=ready_bytes, verified=True)
        result.backup_path = dest

    for item, sv in ready:
        data = {"flavor": flavor.folder, "account": item.account,
                "character": item.owner_label if item.character else None,
                "path": _relative(sv.path, flavor), "size": sv.size, "reasons": item.reasons}
        if dry_run:
            result.outcomes.append(FileOutcome(sv.path, sv.size, "would_delete", "", tuple(item.reasons)))
            log_event("sv.would_delete", dry_run=True, **data)
            continue
        try:
            sv.path.unlink()
        except OSError as exc:
            result.outcomes.append(FileOutcome(sv.path, sv.size, "failed", str(exc), tuple(item.reasons)))
            log_event("sv.failed", path=data["path"], error=str(exc))
            continue
        result.outcomes.append(FileOutcome(sv.path, sv.size, "deleted", "", tuple(item.reasons)))
        log_event("sv.deleted", dry_run=False, **data)

    log_event("clean.completed", dry_run=dry_run, level="warning" if result.failed else None,
              deleted=len(result.deleted), would_delete=len(result.would_delete),
              skipped=len(result.skipped), failed=len(result.failed), bytes=result.bytes_freed,
              backup=str(result.backup_path) if result.backup_path else None)
    return result
```

Append to `wowtools/tools/wtf_cleaner/report.py`:
```python


def result_to_dict(result) -> dict:
    return {
        "dry_run": result.dry_run,
        "backup": str(result.backup_path) if result.backup_path else None,
        "counts": {"deleted": len(result.deleted), "would_delete": len(result.would_delete),
                   "skipped": len(result.skipped), "failed": len(result.failed)},
        "bytes": result.bytes_freed,
        "outcomes": [{"path": str(o.path), "size": o.size, "status": o.status, "detail": o.detail,
                      "reasons": list(o.reasons)} for o in result.outcomes],
    }


def format_result_text(result) -> str:
    lines = ["DRY RUN: nothing was backed up or deleted." if result.dry_run else "Clean finished."]
    if result.backup_path:
        lines.append(("Backup would be written to: " if result.dry_run else "Backup: ") + str(result.backup_path))
    else:
        lines.append("No backup was made.")
    done = result.would_delete if result.dry_run else result.deleted
    verb = "Would delete" if result.dry_run else "Deleted"
    lines.append(f"{verb}: {len(done)} files ({format_size(result.bytes_freed)})")
    if result.skipped:
        lines.append(f"Skipped (changed or missing since the scan): {len(result.skipped)} files")
        lines += [f"  {o.path}  ({o.detail})" for o in result.skipped]
    if result.failed:
        lines.append(f"Failed: {len(result.failed)} files")
        lines += [f"  {o.path}  ({o.detail})" for o in result.failed]
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_cleaner -v`
Expected: 10 tests, OK. On Windows, 9 tests plus 1 skipped.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all OK.

- [ ] **Step 6: Commit**

```bash
git add wowtools/tools/wtf_cleaner/cleaner.py wowtools/tools/wtf_cleaner/report.py tests/test_cleaner.py
git commit -m "feat(wtf-cleaner): verified-backup clean pipeline with dry run and path guard"
```

---

### Task 11: Updater, part 1: release check

**Files:**
- Create: `wowtools/core/updater.py`, `tests/test_updater_check.py`

**Interfaces:**
- Consumes: `Config` (Task 4), `log_event` (Task 3).
- Produces:
  - Constants: `REPO = "tusharsaxena/wow-tools"`, `LATEST_URL`, `CHECK_INTERVAL = timedelta(hours=24)`.
  - `UpdateError`.
  - `parse_version(text) -> tuple[int, int, int]`, `is_newer(candidate, current) -> bool`.
  - `ReleaseInfo(version, tag, notes="", zipball_url="", html_url="")` with the classmethod `from_version(version)`.
  - `fetch_latest(*, timeout=3.0, opener=urllib.request.urlopen) -> ReleaseInfo | None`.
  - `check_for_update(cfg, *, current=__version__, now=None, fetch=None, force=False, raise_errors=False) -> ReleaseInfo | None`.
  - `UpdateCheck(cfg, *, check=check_for_update)` with `.start() -> UpdateCheck` and `.notice(timeout=0.5) -> str | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_updater_check.py`:
```python
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.updater import (ReleaseInfo, UpdateCheck, UpdateError, check_for_update, fetch_latest,
                                   is_newer, parse_version)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def opener_for(payload):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return lambda request, timeout: Response(json.dumps(payload).encode("utf-8"))


class VersionTest(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        with self.assertRaises(ValueError):
            parse_version("1.2")
        self.assertTrue(is_newer("0.2.0", "0.1.9"))
        self.assertTrue(is_newer("0.10.0", "0.9.0"))
        self.assertFalse(is_newer("0.1.0", "0.1.0"))
        self.assertFalse(is_newer("garbage", "0.1.0"))


class FetchTest(unittest.TestCase):
    def test_parses_release(self):
        release = fetch_latest(opener=opener_for({
            "tag_name": "v0.2.0", "body": "Notes", "draft": False, "prerelease": False,
            "zipball_url": "https://api.github.com/zip", "html_url": "https://github.com/r"}))
        self.assertEqual((release.version, release.tag, release.notes), ("0.2.0", "v0.2.0", "Notes"))

    def test_404_means_no_release(self):
        def not_found(request, timeout):
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        self.assertIsNone(fetch_latest(opener=not_found))

    def test_prerelease_ignored(self):
        self.assertIsNone(fetch_latest(opener=opener_for({"tag_name": "v9.0.0", "prerelease": True})))


class CheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = Config(self.tmp / "c.cfg")
        self.cfg.save()

    def test_newer_release_is_returned_and_cached(self):
        with capture_events() as records:
            release = check_for_update(self.cfg, current="0.1.0", now=NOW,
                                       fetch=lambda: ReleaseInfo.from_version("0.2.0"))
        self.assertEqual(release.version, "0.2.0")
        saved = Config(self.cfg.path).load()
        self.assertEqual(saved.latest_seen_version, "0.2.0")
        self.assertEqual(saved.last_update_check, NOW)
        self.assertIn("update.available", [r["event"] for r in records])
        self.assertNotIn("config.changed", [r["event"] for r in records])

    def test_throttled_within_24h_uses_cache(self):
        check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=lambda: ReleaseInfo.from_version("0.2.0"))
        never = Mock(side_effect=AssertionError("must not fetch while throttled"))
        cached = check_for_update(self.cfg, current="0.1.0", now=NOW + timedelta(hours=12), fetch=never)
        self.assertEqual(cached.version, "0.2.0")
        later = Mock(return_value=ReleaseInfo.from_version("0.3.0"))
        self.assertEqual(check_for_update(self.cfg, current="0.1.0", now=NOW + timedelta(hours=25),
                                          fetch=later).version, "0.3.0")
        later.assert_called_once()

    def test_force_ignores_throttle(self):
        check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=lambda: None)
        fetch = Mock(return_value=ReleaseInfo.from_version("0.2.0"))
        self.assertIsNotNone(check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=fetch, force=True))

    def test_same_version_returns_none(self):
        self.assertIsNone(check_for_update(self.cfg, current="0.2.0", now=NOW,
                                           fetch=lambda: ReleaseInfo.from_version("0.2.0")))

    def test_failure_is_silent_unless_asked(self):
        def offline():
            raise urllib.error.URLError("offline")
        with capture_events() as records:
            self.assertIsNone(check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=offline))
        self.assertIn("update.check_failed", [r["event"] for r in records])
        with self.assertRaises(UpdateError):
            check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=offline, force=True, raise_errors=True)

    def test_does_not_create_config_before_setup(self):
        fresh = Config(self.tmp / "new.cfg")
        check_for_update(fresh, current="0.1.0", now=NOW, fetch=lambda: ReleaseInfo.from_version("0.2.0"))
        self.assertFalse(fresh.path.exists())

    def test_background_check_notice(self):
        found = UpdateCheck(self.cfg, check=lambda cfg: ReleaseInfo.from_version("9.9.9")).start()
        self.assertIn("v9.9.9", found.notice(timeout=2))
        self.assertIsNone(UpdateCheck(self.cfg, check=lambda cfg: None).start().notice(timeout=2))

        def boom(cfg):
            raise RuntimeError("x")
        self.assertIsNone(UpdateCheck(self.cfg, check=boom).start().notice(timeout=2))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_updater_check -v`
Expected: ERROR, `No module named 'wowtools.core.updater'`.

- [ ] **Step 3: Implement (check half of the module)**

`wowtools/core/updater.py`:
```python
"""Suite updater: check GitHub Releases on launch and update the whole suite in place."""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from wowtools import __version__
from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event

REPO = "tusharsaxena/wow-tools"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_INTERVAL = timedelta(hours=24)
USER_AGENT = f"ka0s-wow-tools/{__version__}"


class UpdateError(Exception):
    """Checking for or applying an update failed."""


def parse_version(text: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer(candidate: str, current: str) -> bool:
    try:
        return parse_version(candidate) > parse_version(current)
    except ValueError:
        return False


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    notes: str = ""
    zipball_url: str = ""
    html_url: str = ""

    @classmethod
    def from_version(cls, version: str) -> ReleaseInfo:
        tag = f"v{version}"
        return cls(version, tag, "", f"https://api.github.com/repos/{REPO}/zipball/{tag}",
                   f"https://github.com/{REPO}/releases/tag/{tag}")


def fetch_latest(*, timeout: float = 3.0, opener=urllib.request.urlopen) -> ReleaseInfo | None:
    """The latest published (non-draft, non-prerelease) release, or None if there is none."""
    request = urllib.request.Request(LATEST_URL, headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag = str(payload.get("tag_name", ""))
    version = tag[1:] if tag.startswith("v") else tag
    parse_version(version)
    return ReleaseInfo(version, tag, payload.get("body") or "", payload.get("zipball_url") or "",
                       payload.get("html_url") or "")


def check_for_update(cfg: Config, *, current: str = __version__, now: datetime | None = None,
                     fetch: Callable[[], ReleaseInfo | None] | None = None, force: bool = False,
                     raise_errors: bool = False) -> ReleaseInfo | None:
    """Return the newer release, if any. Throttled to once per CHECK_INTERVAL unless force=True."""
    now = now or datetime.now(timezone.utc)
    fetch = fetch or fetch_latest
    last = cfg.last_update_check
    if not force and last is not None and now - last < CHECK_INTERVAL:
        cached = cfg.latest_seen_version
        log_event("update.checked", current=current, latest=cached, throttled=True)
        if cached and is_newer(cached, current):
            log_event("update.available", current=current, latest=cached)
            return ReleaseInfo.from_version(cached)
        return None
    try:
        release = fetch()
    except Exception as exc:  # offline, rate limited, bad JSON: never bother the user
        log_event("update.check_failed", error=f"{type(exc).__name__}: {exc}")
        if raise_errors:
            raise UpdateError(f"could not reach GitHub: {exc}") from exc
        return None
    cfg.set(GENERAL, "last_update_check", now.isoformat(timespec="seconds"), log=False)
    if release is not None:
        cfg.set(GENERAL, "latest_seen_version", release.version, log=False)
    cfg.save_if_exists()
    log_event("update.checked", current=current, latest=release.version if release else None, throttled=False)
    if release is not None and is_newer(release.version, current):
        log_event("update.available", current=current, latest=release.version)
        return release
    return None


class UpdateCheck:
    """Run check_for_update in a daemon thread so launch never waits on the network."""

    def __init__(self, cfg: Config, *, check: Callable[[Config], ReleaseInfo | None] = check_for_update) -> None:
        self.cfg = cfg
        self.release: ReleaseInfo | None = None
        self._check = check
        self._thread = threading.Thread(target=self._run, name="wowtools-update-check", daemon=True)

    def start(self) -> UpdateCheck:
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            self.release = self._check(self.cfg)
        except Exception:
            self.release = None

    def notice(self, timeout: float = 0.5) -> str | None:
        self._thread.join(timeout)
        if self.release is None:
            return None
        return (f"Ka0s WoW Tools v{self.release.version} is available (you have v{__version__}). "
                "Update with: python -m wowtools update")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_updater_check -v`
Expected: 11 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add wowtools/core/updater.py tests/test_updater_check.py
git commit -m "feat(core): throttled GitHub release check"
```

---

### Task 12: Updater, part 2: apply (git / zip with rollback) + `update` command

**Files:**
- Modify: `wowtools/core/updater.py` (append the apply half)
- Create: `tests/test_updater_apply.py`

**Interfaces:**
- Consumes: `REPO_ROOT` (Task 1), the Task 11 names.
- Produces:
  - Constants: `MANAGED_DIRS`, `MANAGED_FILES`, `BACKUP_DIR_NAME = ".update-backup"`.
  - `install_kind(root: Path = REPO_ROOT) -> str` (`"git"` or `"zip"`).
  - `apply_update(release, *, root=REPO_ROOT, current=__version__, runner=subprocess.run, download=None) -> str`. It returns the restart message and raises `UpdateError`.
  - `run_update_command(argv, cfg, *, stdout=None, stderr=None, check=check_for_update, apply=apply_update) -> int`. Exit codes: 0 means up to date or updated, 10 means an update is available (`--check`), 1 means an error.

- [ ] **Step 1: Write the failing tests**

`tests/test_updater_apply.py`:
```python
import io
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from wowtools.core import updater
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.updater import ReleaseInfo, UpdateError, apply_update, install_kind, run_update_command

HAS_GIT = shutil.which("git") is not None
TOP = "tusharsaxena-wow-tools-abc123"


def make_install(root: Path, version: str) -> None:
    (root / "wowtools").mkdir(parents=True)
    (root / "wowtools" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (root / "vendor").mkdir()
    (root / "vendor" / "lib.py").write_text(f"# {version}\n")
    (root / "docs").mkdir()
    (root / "docs" / f"only-in-{version}.md").write_text("doc\n")
    (root / "README.md").write_text(f"readme {version}\n")
    (root / "requirements.txt").write_text("textual\n")


def make_zipball(path: Path, version: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{TOP}/wowtools/__init__.py", f'__version__ = "{version}"\n')
        zf.writestr(f"{TOP}/vendor/lib.py", f"# {version}\n")
        zf.writestr(f"{TOP}/docs/only-in-{version}.md", "doc\n")
        zf.writestr(f"{TOP}/scripts/x.py", "print('x')\n")
        zf.writestr(f"{TOP}/README.md", f"readme {version}\n")
        zf.writestr(f"{TOP}/requirements.txt", "textual\n")


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", *args],
                   cwd=cwd, check=True, capture_output=True)


class ZipUpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "suite"
        make_install(self.root, "0.1.0")
        (self.root / "wow-tools.cfg").write_text("[general]\n")
        (self.root / "logs").mkdir()
        (self.root / "logs" / "events-2026-09-27.jsonl").write_text("{}\n")
        (self.root / "my-notes.txt").write_text("mine")
        self.zipball = self.tmp / "release.zip"

    def download(self, url, dest):
        shutil.copy(self.zipball, dest)

    def version_on_disk(self):
        return (self.root / "wowtools" / "__init__.py").read_text()

    def test_install_kind(self):
        self.assertEqual(install_kind(self.root), "zip")
        (self.root / ".git").mkdir()
        self.assertEqual(install_kind(self.root), "git")

    def test_replaces_managed_paths_and_keeps_user_files(self):
        make_zipball(self.zipball, "0.2.0")
        with capture_events() as records:
            message = apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                                   download=self.download)
        self.assertIn("Restart", message)
        self.assertIn("0.2.0", self.version_on_disk())
        self.assertEqual((self.root / "README.md").read_text(), "readme 0.2.0\n")
        self.assertFalse((self.root / "docs" / "only-in-0.1.0.md").exists())
        self.assertTrue((self.root / "scripts" / "x.py").exists())
        self.assertEqual((self.root / "wow-tools.cfg").read_text(), "[general]\n")
        self.assertTrue((self.root / "logs" / "events-2026-09-27.jsonl").exists())
        self.assertEqual((self.root / "my-notes.txt").read_text(), "mine")
        self.assertIn("0.1.0", (self.root / ".update-backup" / "0.1.0" / "wowtools" / "__init__.py").read_text())
        applied = [r for r in records if r["event"] == "update.applied"][0]["data"]
        self.assertEqual((applied["from"], applied["to"], applied["method"]), ("0.1.0", "0.2.0", "zip"))

    def test_wrong_version_in_zip_is_rejected(self):
        make_zipball(self.zipball, "0.3.0")
        with capture_events() as records:
            with self.assertRaises(UpdateError):
                apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                             download=self.download)
        self.assertIn("0.1.0", self.version_on_disk())
        self.assertIn("update.failed", [r["event"] for r in records])

    def test_bad_zip_is_rejected(self):
        self.zipball.write_bytes(b"not a zip")
        with self.assertRaises(UpdateError):
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=self.download)
        self.assertIn("0.1.0", self.version_on_disk())

    def test_failure_mid_apply_rolls_back(self):
        make_zipball(self.zipball, "0.2.0")
        real_copy = updater._copy

        def failing_copy(src, dst):
            if TOP in str(src) and src.name == "vendor":
                raise OSError("disk full")
            real_copy(src, dst)

        with patch.object(updater, "_copy", failing_copy):
            with self.assertRaises(UpdateError) as ctx:
                apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                             download=self.download)
        self.assertIn("rolled back", str(ctx.exception))
        self.assertIn("0.1.0", self.version_on_disk())
        self.assertTrue((self.root / "docs" / "only-in-0.1.0.md").exists())
        self.assertEqual((self.root / "README.md").read_text(), "readme 0.1.0\n")
        self.assertTrue((self.root / "vendor" / "lib.py").exists())
        self.assertFalse((self.root / "scripts").exists())


@unittest.skipUnless(HAS_GIT, "git not installed")
class GitUpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin = self.tmp / "origin"
        make_install(self.origin, "0.1.0")
        git(self.origin, "init", "-q")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "v0.1.0")
        self.clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.clone))

    def test_refuses_dirty_tree(self):
        (self.clone / "README.md").write_text("my edit\n")
        with self.assertRaises(UpdateError) as ctx:
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.clone, current="0.1.0")
        self.assertIn("local changes", str(ctx.exception))

    def test_fast_forwards_to_tag(self):
        (self.origin / "wowtools" / "__init__.py").write_text('__version__ = "0.2.0"\n')
        git(self.origin, "commit", "-q", "-am", "v0.2.0")
        git(self.origin, "tag", "v0.2.0")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.clone, current="0.1.0")
        self.assertIn("0.2.0", (self.clone / "wowtools" / "__init__.py").read_text())


class UpdateCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = Config(Path(tmp.name) / "c.cfg")

    def run_cmd(self, argv, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        code = run_update_command(argv, self.cfg, stdout=out, stderr=err, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def test_check_only(self):
        code, out, _ = self.run_cmd(["--check"], check=lambda cfg, **kw: ReleaseInfo.from_version("9.9.9"))
        self.assertEqual(code, 10)
        self.assertIn("9.9.9", out)

    def test_up_to_date(self):
        code, out, _ = self.run_cmd([], check=lambda cfg, **kw: None)
        self.assertEqual(code, 0)
        self.assertIn("up to date", out)

    def test_apply(self):
        code, out, _ = self.run_cmd([], check=lambda cfg, **kw: ReleaseInfo.from_version("9.9.9"),
                                    apply=lambda release: "Updated. Restart.")
        self.assertEqual(code, 0)
        self.assertIn("Updated", out)

    def test_apply_failure(self):
        def broken(release):
            raise UpdateError("nope")
        code, _, err = self.run_cmd([], check=lambda cfg, **kw: ReleaseInfo.from_version("9.9.9"), apply=broken)
        self.assertEqual(code, 1)
        self.assertIn("nope", err)

    def test_check_failure(self):
        def offline(cfg, **kw):
            raise UpdateError("could not reach GitHub")
        code, _, err = self.run_cmd(["--check"], check=offline)
        self.assertEqual(code, 1)
        self.assertIn("Could not check", err)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_updater_apply -v`
Expected: ERROR, `cannot import name 'apply_update'`.

- [ ] **Step 3: Implement**

At the top of `wowtools/core/updater.py`, extend the imports to:
```python
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from wowtools import __version__
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event
```

Append to `wowtools/core/updater.py`:
```python


# --- applying an update ---------------------------------------------------------------------
MANAGED_DIRS = ("wowtools", "vendor", "scripts", "docs")
MANAGED_FILES = ("wtf-cleaner.cmd", "wtf-cleaner.sh", "wow-tools.cmd", "wow-tools.sh",
                 "requirements.txt", ".gitattributes")
BACKUP_DIR_NAME = ".update-backup"
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def install_kind(root: Path = REPO_ROOT) -> str:
    return "git" if (root / ".git").exists() else "zip"


def apply_update(release: ReleaseInfo, *, root: Path = REPO_ROOT, current: str = __version__,
                 runner=subprocess.run, download: Callable[[str, Path], None] | None = None) -> str:
    kind = install_kind(root)
    try:
        if kind == "git":
            _apply_git(root, release.tag, runner)
        else:
            _apply_zip(root, release, current, download or _download)
    except UpdateError as exc:
        log_event("update.failed", method=kind, error=str(exc))
        raise
    log_event("update.applied", method=kind, **{"from": current, "to": release.version})
    return f"Updated Ka0s WoW Tools to v{release.version}. Restart to use the new version."


def _git(root: Path, runner, *args: str) -> str:
    try:
        proc = runner(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise UpdateError("git is not available. Install git, or download the release zip instead.") from exc
    if proc.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def _apply_git(root: Path, tag: str, runner) -> None:
    if _git(root, runner, "status", "--porcelain").strip():
        raise UpdateError("You have local changes in the wow-tools folder. Commit or stash them, then update again.")
    _git(root, runner, "fetch", "--tags", "--force", "origin")
    _git(root, runner, "merge", "--ff-only", tag)


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError(f"download failed: {exc}") from exc


def _managed_names(folder: Path) -> list[str]:
    names = [name for name in (*MANAGED_DIRS, *MANAGED_FILES) if (folder / name).exists()]
    names += sorted(p.name for p in folder.glob("*.md") if p.is_file())
    return names


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _rollback(root: Path, backup: Path) -> None:
    saved = {p.name for p in backup.iterdir()}
    for name in set(_managed_names(root)) | saved:
        try:
            _remove(root / name)
        except OSError:
            pass
    for name in saved:
        _copy(backup / name, root / name)


def _apply_zip(root: Path, release: ReleaseInfo, current: str, download: Callable[[str, Path], None]) -> None:
    if not release.zipball_url:
        raise UpdateError("the release has no download URL")
    with tempfile.TemporaryDirectory(prefix="wowtools-update-") as tmp:
        work = Path(tmp)
        archive = work / "release.zip"
        download(release.zipball_url, archive)
        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(work / "extract")
        except (zipfile.BadZipFile, OSError) as exc:
            raise UpdateError(f"the downloaded file is not a valid zip: {exc}") from exc
        tops = [p for p in (work / "extract").iterdir() if p.is_dir()]
        if len(tops) != 1:
            raise UpdateError("unexpected release layout")
        staging = tops[0]
        init = staging / "wowtools" / "__init__.py"
        match = _VERSION_RE.search(init.read_text(encoding="utf-8")) if init.is_file() else None
        if not match or match.group(1) != release.version:
            raise UpdateError(f"the download does not contain version {release.version}")

        backup = root / BACKUP_DIR_NAME / current
        if backup.exists():
            shutil.rmtree(backup)
        backup.mkdir(parents=True)
        old_names = _managed_names(root)
        try:
            for name in old_names:
                _copy(root / name, backup / name)
        except OSError as exc:
            raise UpdateError(f"could not back up the current version: {exc}") from exc
        try:
            for name in old_names:
                _remove(root / name)
            for name in _managed_names(staging):
                _copy(staging / name, root / name)
        except OSError as exc:
            _rollback(root, backup)
            raise UpdateError(f"update failed and was rolled back: {exc}") from exc


def run_update_command(argv: list[str], cfg: Config, *, stdout=None, stderr=None,
                       check=check_for_update, apply=apply_update) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = argparse.ArgumentParser(prog="python -m wowtools update",
                                     description="Check for and apply Ka0s WoW Tools updates.")
    parser.add_argument("--check", action="store_true", help="only report whether an update is available")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code in (0, None) else 1
    try:
        release = check(cfg, force=True, raise_errors=True)
    except UpdateError as exc:
        print(f"Could not check for updates: {exc}", file=stderr)
        return 1
    if release is None:
        print(f"Ka0s WoW Tools v{__version__} is up to date.", file=stdout)
        return 0
    if args.check:
        print(f"Update available: v{release.version} (you have v{__version__}). "
              "Run: python -m wowtools update", file=stdout)
        return 10
    log_event("ui.selection", screen="cli", control="update", value="accepted")
    try:
        print(apply(release), file=stdout)
    except UpdateError as exc:
        print(f"Update failed: {exc}", file=stderr)
        return 1
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_updater_check tests.test_updater_apply -v`
Expected: all OK (the git tests are skipped if git is missing).

- [ ] **Step 5: Commit**

```bash
git add wowtools/core/updater.py tests/test_updater_apply.py
git commit -m "feat(core): self-update via git fast-forward or zip with rollback"
```

---

### Task 13: Suite dispatcher, tool registry, WTF Cleaner CLI, launch wrappers

**Files:**
- Create: `wowtools/__main__.py`, `wowtools/suite.py`, `wowtools/tools/wtf_cleaner/cli.py`, `wtf-cleaner.cmd`, `wtf-cleaner.sh`, `wow-tools.cmd`, `wow-tools.sh`, `tests/test_suite.py`, `tests/test_wtf_cli.py`
- Modify: `wowtools/tools/__init__.py` (the registry)

**Interfaces:**
- Consumes: everything from Tasks 1–12.
- Produces:
  - `wowtools.tools.Tool(name, title, description, module)` with `.main() -> Callable[..., int]`, and `TOOLS: dict[str, Tool]`.
  - `wowtools.suite.LOG_DIR`, `usage() -> str`, `run(argv: list[str], *, cfg: Config | None = None, log_dir: Path | None = LOG_DIR) -> int`.
  - `wtf_cleaner.cli`:
    - `build_parser()`.
    - `main(argv, *, cfg=None, stdout=None, stderr=None, input_fn=input, wow_check=running_wow_executables) -> int`.
    - Exit constants `EXIT_OK=0`, `EXIT_USAGE=1`, `EXIT_SCAN=2`, `EXIT_PARTIAL=3`, `EXIT_BACKUP=4`.
  - Every tool module's `main(argv, *, cfg=None, ...) -> int` must accept `cfg=` as a keyword argument.
  - Task 15 creates `wowtools.tools.wtf_cleaner.app.WtfCleanerApp(cfg)`, which `cli.main` imports lazily.

- [ ] **Step 1: Write the failing tests**

`tests/test_suite.py`:
```python
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.fixtures import build_wow_tree, make_config
from wowtools import __version__
from wowtools.core import events
from wowtools.suite import run
from wowtools.tools import TOOLS


class SuiteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = make_config(self.tmp, build_wow_tree(self.tmp / "World of Warcraft"))
        self.log_dir = self.tmp / "logs"
        # run() installs a process-wide log pointing at this temp dir; put the old one back afterwards.
        self.addCleanup(setattr, events, "_current", events.get_event_log())

    def run_suite(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run(argv, cfg=self.cfg, log_dir=self.log_dir)
        return code, out.getvalue(), err.getvalue()

    def test_registry(self):
        self.assertIn("wtf-cleaner", TOOLS)
        self.assertTrue(callable(TOOLS["wtf-cleaner"].main()))

    def test_version_and_help_do_not_log(self):
        code, out, _ = self.run_suite(["--version"])
        self.assertEqual((code, out.strip()), (0, __version__))
        code, out, _ = self.run_suite(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("wtf-cleaner", out)
        self.assertFalse(self.log_dir.exists())

    def test_unknown_tool(self):
        code, _, err = self.run_suite(["bogus"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown tool", err)

    def test_dispatches_to_tool_and_logs_session(self):
        code, out, _ = self.run_suite(["wtf-cleaner", "--flavor", "retail", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["totals"]["items"], 6)
        records = [json.loads(line) for path in self.log_dir.glob("events-*.jsonl")
                   for line in path.read_text(encoding="utf-8").splitlines()]
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "session.start")
        self.assertEqual(names[-1], "session.end")
        self.assertEqual(records[-1]["data"]["exit_code"], 0)
        self.assertTrue(all(r["tool"] == "wtf-cleaner" for r in records))
        self.assertIn("scan.completed", names)
        self.assertTrue(list(self.log_dir.glob("wow-tools-*.log")))
```

`tests/test_wtf_cli.py`:
```python
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree, make_config
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import Config
from wowtools.tools.wtf_cleaner.cli import main


class CliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.cfg = make_config(self.tmp, self.root)
        self.sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.backup_dir = self.tmp / "bk"

    def cli(self, *argv, answer="n", cfg=None, wow_running=()):
        out, err = io.StringIO(), io.StringIO()

        def ask(prompt):
            if answer is None:
                raise AssertionError("must not prompt")
            return answer

        code = main(list(argv), cfg=cfg or self.cfg, stdout=out, stderr=err, input_fn=ask,
                    wow_check=lambda: list(wow_running))
        return code, out.getvalue(), err.getvalue()

    def test_proposal_text_is_read_only(self):
        code, out, _ = self.cli("--flavor", "retail", answer=None)
        self.assertEqual(code, 0)
        self.assertIn("Total: 6 items, 8 files", out)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    def test_last_flavor_is_used_with_json(self):
        code, out, _ = self.cli("--json", answer=None)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["flavor"], "_retail_")

    def test_clean_prompt_declined(self):
        code, out, _ = self.cli("--flavor", "retail", "--clean", answer="n")
        self.assertEqual(code, 0)
        self.assertIn("Aborted", out)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    def test_clean_with_yes(self):
        code, out, _ = self.cli("--flavor", "retail", "--clean", "--yes", "--backup-dir", str(self.backup_dir),
                                answer=None)
        self.assertEqual(code, 0)
        self.assertFalse((self.sv / "Uninstalled.lua").exists())
        self.assertTrue((self.sv / "Auctionator.lua").exists())
        self.assertEqual(len(list(self.backup_dir.glob("wtf-cleaner_retail_*.zip"))), 1)
        self.assertIn("Deleted: 8 files", out)

    def test_dry_run_clean_needs_no_prompt(self):
        code, out, _ = self.cli("--flavor", "retail", "--clean", "--dry-run", answer=None)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    def test_no_backup_requires_yes(self):
        code, _, err = self.cli("--flavor", "retail", "--clean", "--no-backup")
        self.assertEqual(code, 1)
        self.assertIn("--no-backup", err)

    def test_json_clean_requires_yes_or_dry_run(self):
        code, _, _ = self.cli("--flavor", "retail", "--clean", "--json", answer=None)
        self.assertEqual(code, 1)

    def test_criteria_override(self):
        code, out, _ = self.cli("--flavor", "retail", "--json", "--criteria", "not_installed", answer=None)
        self.assertEqual(code, 0)
        self.assertEqual({i["addon"] for i in json.loads(out)["items"]}, {"Uninstalled"})

    def test_bad_criteria_and_max_age(self):
        code, _, err = self.cli("--flavor", "retail", "--criteria", "bogus")
        self.assertEqual(code, 1)
        self.assertIn("unknown criteria", err)
        code, _, err = self.cli("--flavor", "retail", "--max-age", "0")
        self.assertEqual(code, 1)

    def test_unknown_flavor(self):
        code, _, err = self.cli("--flavor", "wotlk")
        self.assertEqual(code, 1)
        self.assertIn("anniversary, classic_era, retail", err)

    def test_missing_config(self):
        code, _, err = self.cli("--flavor", "retail", cfg=Config(self.tmp / "none.cfg"))
        self.assertEqual(code, 1)
        self.assertIn("Run the TUI once", err)

    def test_wow_path_override_without_config(self):
        code, out, _ = self.cli("--flavor", "retail", "--json", "--wow-path", str(self.root),
                                cfg=Config(self.tmp / "none.cfg"), answer=None)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["totals"]["items"], 6)

    def test_scan_error_exit_code(self):
        code, _, err = self.cli("--flavor", "anniversary")
        self.assertEqual(code, 2)
        self.assertIn("No addons found", err)

    def test_backup_failure_exit_code_keeps_files(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("x")
        code, _, err = self.cli("--flavor", "retail", "--clean", "--yes", "--backup-dir", str(blocker / "sub"))
        self.assertEqual(code, 4)
        self.assertIn("nothing was deleted", err)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    def test_nothing_to_clean(self):
        code, out, _ = self.cli("--flavor", "classic_era", "--clean", "--yes", "--backup-dir", str(self.backup_dir))
        self.assertEqual(code, 0)
        self.assertIn("Nothing to clean.", out)
        self.assertFalse(self.backup_dir.exists())

    def test_wow_running_warning(self):
        code, _, err = self.cli("--flavor", "retail", "--clean", "--dry-run", answer=None, wow_running=["Wow.exe"])
        self.assertEqual(code, 0)
        self.assertIn("WoW appears to be running", err)

    def test_partial_failure_exit_code(self):
        original = Path.unlink

        def flaky(path, *a, **k):
            if path.name == "DisabledAddon.lua":
                raise PermissionError("locked")
            return original(path, *a, **k)

        with patch.object(Path, "unlink", flaky):
            code, out, _ = self.cli("--flavor", "retail", "--clean", "--yes", "--no-backup")
        self.assertEqual(code, 3)
        self.assertIn("Failed: 1 files", out)


@unittest.skipIf(os.name == "nt", "shell wrapper test runs on POSIX")
class WrapperTest(unittest.TestCase):
    def test_sh_wrapper_runs_from_another_cwd(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            proc = subprocess.run(["sh", str(REPO_ROOT / "wow-tools.sh"), "--version"], cwd=elsewhere,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "0.1.0")

    def test_module_help(self):
        proc = subprocess.run([sys.executable, "-m", "wowtools", "wtf-cleaner", "--help"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--dry-run", proc.stdout)
```

Note: `test_module_help` runs `wtf-cleaner --help` through the real `run()`, so it writes a session to the repo's git-ignored `logs/`. That's acceptable. It reads a real `wow-tools.cfg` only if one exists, and `--help` never uses it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_suite tests.test_wtf_cli -v`
Expected: ERROR, `No module named 'wowtools.suite'`.

- [ ] **Step 3: Implement the registry and dispatcher**

`wowtools/tools/__init__.py`:
```python
"""Tools that ship with the suite. Add new tools to TOOLS (see docs/adding-a-tool.md)."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    module: str

    def main(self) -> Callable[..., int]:
        """The tool's `main(argv, *, cfg=None, ...) -> int`, imported on demand."""
        return importlib.import_module(self.module).main


TOOLS: dict[str, Tool] = {tool.name: tool for tool in (
    Tool("wtf-cleaner", "WTF Cleaner",
         "Find and remove stale addon SavedVariables, with zip backups.",
         "wowtools.tools.wtf_cleaner.cli"),
)}
```

`wowtools/__main__.py`:
```python
"""Suite entry point: python -m wowtools [tool] [args]."""
from __future__ import annotations

import sys

from wowtools.core.bootstrap import add_vendor_path, check_python


def main(argv: list[str] | None = None) -> int:
    problem = check_python()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    add_vendor_path()
    from wowtools.suite import run  # everything else is imported after vendor/ is on sys.path

    return run(sys.argv[1:] if argv is None else list(argv))


if __name__ == "__main__":
    sys.exit(main())
```

`wowtools/suite.py`:
```python
"""Dispatcher for `python -m wowtools`: tools, `update`, the tool picker, sessions and auto-update."""
from __future__ import annotations

import platform
import sys
import time
from pathlib import Path

from wowtools import __version__
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import Config, ConfigError
from wowtools.core.events import get_event_log, init_event_log, log_event, log_exception
from wowtools.core.paths import is_wsl
from wowtools.core.updater import UpdateError, apply_update, check_for_update, run_update_command
from wowtools.tools import TOOLS

LOG_DIR = REPO_ROOT / "logs"


def usage() -> str:
    lines = [f"Ka0s WoW Tools v{__version__}", "",
             "Usage: python -m wowtools [TOOL] [OPTIONS]", "",
             "With no TOOL, a menu of tools opens.", "", "Tools:"]
    lines += [f"  {tool.name:<14} {tool.description}" for tool in TOOLS.values()]
    lines += ["", "Other commands:",
              "  update         Check for and install a newer version (--check to only look)",
              "  --version      Print the version", "",
              "Run `python -m wowtools TOOL --help` for a tool's options."]
    return "\n".join(lines)


def run(argv: list[str], *, cfg: Config | None = None, log_dir: Path | None = LOG_DIR) -> int:
    if argv[:1] in (["-h"], ["--help"], ["help"]):
        print(usage())
        return 0
    if argv[:1] == ["--version"]:
        print(__version__)
        return 0
    try:
        cfg = cfg if cfg is not None else Config().load()
    except ConfigError as exc:
        print(f"{exc}\nFix or delete the file, then run again.", file=sys.stderr)
        return 1
    command = argv[0] if argv and not argv[0].startswith("-") else None
    init_event_log(log_dir, tool=command if command in TOOLS else "suite", mode="cli",
                   text_level=cfg.log_level, retention_days=cfg.log_retention_days)
    log_event("session.start", argv=argv, platform=platform.platform(), is_wsl=is_wsl(),
              python=platform.python_version(), suite_version=__version__)
    started = time.monotonic()
    code = 1
    try:
        code = _dispatch(argv, command, cfg)
        return code
    except KeyboardInterrupt:
        code = 130
        return code
    except Exception as exc:
        log_exception("suite", exc)
        raise
    finally:
        log_event("session.end", level="warning" if code not in (0, 10) else None,
                  exit_code=code, duration_s=round(time.monotonic() - started, 3))


def _auto_update(cfg: Config) -> bool:
    """Apply an update before any tool starts when auto_update = true. True means 'exit now'."""
    if not (cfg.exists and cfg.check_for_updates and cfg.auto_update):
        return False
    release = check_for_update(cfg)
    if release is None:
        return False
    try:
        print(apply_update(release))
    except UpdateError as exc:
        print(f"Automatic update failed: {exc}", file=sys.stderr)
        return False
    return True


def _dispatch(argv: list[str], command: str | None, cfg: Config) -> int:
    if command is None and argv:
        print(usage(), file=sys.stderr)
        return 1
    if command == "update":
        return run_update_command(argv[1:], cfg)
    if command is not None and command not in TOOLS:
        print(f"Unknown tool: {command}\n\n{usage()}", file=sys.stderr)
        return 1
    if _auto_update(cfg):
        return 0
    if command is None:
        from wowtools.ui.tool_picker import ToolPickerApp

        get_event_log().set_context(mode="tui")
        picked = ToolPickerApp(cfg).run()
        if not picked:
            return 0
        get_event_log().set_context(tool=picked)
        return TOOLS[picked].main()([], cfg=cfg)
    return TOOLS[command].main()(argv[1:], cfg=cfg)
```

- [ ] **Step 4: Implement the WTF Cleaner CLI**

`wowtools/tools/wtf_cleaner/cli.py`:
```python
"""Command-line front end. With no CLI-mode flags it opens the TUI instead."""
from __future__ import annotations

import argparse
import json
import sys

from wowtools.core.backup import BackupError
from wowtools.core.config import Config
from wowtools.core.events import get_event_log, log_event, log_exception
from wowtools.core.install import WowInstall
from wowtools.core.paths import to_native
from wowtools.core.process import running_wow_executables
from wowtools.core.updater import UpdateCheck
from wowtools.tools.wtf_cleaner.cleaner import CleanError, execute
from wowtools.tools.wtf_cleaner.report import (format_proposal_text, format_result_text, format_size,
                                               proposal_to_dict, result_to_dict)
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria, evaluate
from wowtools.tools.wtf_cleaner.scanner import ScanError, scan
from wowtools.tools.wtf_cleaner.settings import SECTION, load_settings

EXIT_OK, EXIT_USAGE, EXIT_SCAN, EXIT_PARTIAL, EXIT_BACKUP = 0, 1, 2, 3, 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m wowtools wtf-cleaner",
        description="Find and remove stale addon SavedVariables, backing them up to a zip first. "
                    "Without --flavor, --clean, --json or --dry-run the interactive TUI opens.")
    parser.add_argument("--flavor", help="retail, classic, classic_era, anniversary, ... (default: last used)")
    parser.add_argument("--clean", action="store_true", help="back up and delete the proposal (asks first)")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--dry-run", action="store_true", help="simulate: nothing is backed up or deleted")
    parser.add_argument("--no-backup", action="store_true", help="skip the zip backup (requires --yes)")
    parser.add_argument("--max-age", type=int, metavar="DAYS", help="override max_age_days")
    parser.add_argument("--criteria", metavar="LIST", help=f"comma list from: {', '.join(CRITERIA)}")
    parser.add_argument("--wow-path", metavar="PATH", help="override the configured WoW folder")
    parser.add_argument("--backup-dir", metavar="PATH", help="override the configured backup folder")
    parser.add_argument("--json", action="store_true", help="machine-readable output on stdout")
    parser.add_argument("--tui", action="store_true", help="open the TUI even if other flags are given")
    return parser


def main(argv: list[str], *, cfg: Config | None = None, stdout=None, stderr=None, input_fn=input,
         wow_check=running_wow_executables) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code in (0, None) else EXIT_USAGE
    cfg = cfg if cfg is not None else Config().load()

    if args.tui or not any([args.flavor, args.clean, args.json, args.dry_run]):
        get_event_log().set_context(mode="tui")
        from wowtools.tools.wtf_cleaner.app import WtfCleanerApp

        WtfCleanerApp(cfg).run()
        return EXIT_OK

    get_event_log().set_context(mode="cli")
    checker = UpdateCheck(cfg).start() if cfg.check_for_updates and not args.json else None
    try:
        return _run(args, cfg, stdout, stderr, input_fn, wow_check)
    finally:
        notice = checker.notice() if checker else None
        if notice:
            print(notice, file=stderr)


def _override(section: str, key: str, old, new) -> None:
    log_event("config.changed", section=section, key=key, old=old, new=str(new), source="cli", persisted=False)


def _run(args, cfg: Config, stdout, stderr, input_fn, wow_check) -> int:
    def out(text: str) -> None:
        print(text, file=stdout)

    def err(text: str) -> None:
        print(text, file=stderr)

    if args.wow_path:
        wow_path = to_native(args.wow_path)
        _override("general", "wow_path", cfg.get("general", "wow_path"), args.wow_path)
    else:
        wow_path = cfg.wow_path
    if wow_path is None:
        err("No WoW folder is configured. Run the TUI once (python -m wowtools wtf-cleaner) or pass --wow-path.")
        return EXIT_USAGE
    install = WowInstall(wow_path)
    if not install.is_valid():
        err(f"No WoW flavor folders (_retail_, _classic_ ...) were found in {wow_path}.")
        return EXIT_USAGE
    flavor_name = args.flavor or cfg.last_flavor
    if not flavor_name:
        err("No flavor given. Pass --flavor (for example: --flavor retail).")
        return EXIT_USAGE
    flavor = install.flavor(flavor_name)
    if flavor is None:
        available = ", ".join(f.short_name for f in install.flavors())
        err(f"Unknown flavor {flavor_name!r}. Available: {available}")
        return EXIT_USAGE
    log_event("ui.selection", screen="cli", control="flavor", value=flavor.folder)

    settings = load_settings(cfg)
    criteria = settings.criteria
    if args.criteria is not None or args.max_age is not None:
        names = ([n.strip() for n in args.criteria.split(",") if n.strip()]
                 if args.criteria is not None else criteria.enabled_names())
        max_age = args.max_age if args.max_age is not None else criteria.max_age_days
        if max_age < 1:
            err("--max-age must be at least 1 day.")
            return EXIT_USAGE
        try:
            criteria = Criteria.from_names(names, max_age)
        except ValueError as exc:
            err(str(exc))
            return EXIT_USAGE
        if args.criteria is not None:
            _override(SECTION, "criteria", settings.criteria.enabled_names(), ",".join(names))
        if args.max_age is not None:
            _override(SECTION, "max_age_days", settings.criteria.max_age_days, max_age)

    backup = settings.backup_before_delete and not args.no_backup
    if args.backup_dir:
        backup_dir = to_native(args.backup_dir)
        _override("general", "backup_dir", cfg.get("general", "backup_dir"), args.backup_dir)
    else:
        backup_dir = cfg.get_path("general", "backup_dir") or wow_path / "wow-tools-backups"

    try:
        result_scan = scan(flavor)
    except ScanError as exc:
        log_exception("scan", exc)
        err(str(exc))
        return EXIT_SCAN
    proposal = evaluate(result_scan, criteria)

    if not args.clean:
        out(json.dumps(proposal_to_dict(proposal, flavor), indent=2, ensure_ascii=False) if args.json
            else format_proposal_text(proposal, flavor))
        return EXIT_OK
    if args.no_backup and not args.yes:
        err("--no-backup is only allowed together with --yes.")
        return EXIT_USAGE
    if args.json and not (args.yes or args.dry_run):
        err("--json with --clean needs --yes or --dry-run (there is no prompt in JSON mode).")
        return EXIT_USAGE
    if not proposal.items:
        out(json.dumps({"proposal": proposal_to_dict(proposal, flavor), "result": None}, indent=2)
            if args.json else "Nothing to clean.")
        return EXIT_OK
    if not args.json:
        out(format_proposal_text(proposal, flavor))

    running = wow_check()
    if running:
        log_event("wow.running_warning", executables=running)
        err(f"Warning: WoW appears to be running ({', '.join(running)}). Close it first: "
            "WoW rewrites SavedVariables when you log out.")

    if not args.yes and not args.dry_run:
        answer = input_fn(f"Back up and delete {proposal.total_files} files "
                          f"({format_size(proposal.total_size)})? [y/N] ")
        confirmed = answer.strip().lower() in ("y", "yes")
        log_event("ui.selection", screen="cli", control="confirm", value=confirmed)
        if not confirmed:
            out("Aborted. Nothing was changed.")
            return EXIT_OK

    try:
        result = execute(proposal.items, flavor, dry_run=args.dry_run, backup=backup, backup_dir=backup_dir)
    except BackupError as exc:
        err(f"Backup failed, nothing was deleted: {exc}")
        return EXIT_BACKUP
    except CleanError as exc:
        log_exception("clean", exc)
        err(str(exc))
        return EXIT_USAGE
    if args.json:
        out(json.dumps({"proposal": proposal_to_dict(proposal, flavor), "result": result_to_dict(result)},
                       indent=2, ensure_ascii=False))
    else:
        out("")
        out(format_result_text(result))
    return EXIT_PARTIAL if result.failed else EXIT_OK
```

- [ ] **Step 5: Create the launch wrappers**

`wtf-cleaner.sh`:
```sh
#!/usr/bin/env sh
# Ka0s WoW Tools: WTF Cleaner. Runs from any folder; needs Python 3.10+.
here="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m wowtools wtf-cleaner "$@"
```

`wow-tools.sh`:
```sh
#!/usr/bin/env sh
# Ka0s WoW Tools: tool menu, `update`, or any tool by name. Needs Python 3.10+.
here="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m wowtools "$@"
```

`wtf-cleaner.cmd`:
```bat
@echo off
rem Ka0s WoW Tools: WTF Cleaner. Needs Python 3.10+ (uses the py launcher when present).
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m wowtools wtf-cleaner %*
) else (
  python -m wowtools wtf-cleaner %*
)
exit /b %ERRORLEVEL%
```

`wow-tools.cmd`:
```bat
@echo off
rem Ka0s WoW Tools: tool menu, `update`, or any tool by name. Needs Python 3.10+.
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m wowtools %*
) else (
  python -m wowtools %*
)
exit /b %ERRORLEVEL%
```

Run: `git add wtf-cleaner.sh wow-tools.sh && git update-index --chmod=+x wtf-cleaner.sh wow-tools.sh && chmod +x wtf-cleaner.sh wow-tools.sh`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_suite tests.test_wtf_cli -v`
Expected: all OK. The TUI path isn't exercised here, because every test passes CLI-mode flags.

- [ ] **Step 7: Commit**

```bash
git add wowtools/__main__.py wowtools/suite.py wowtools/tools/__init__.py wowtools/tools/wtf_cleaner/cli.py \
        wtf-cleaner.cmd wtf-cleaner.sh wow-tools.cmd wow-tools.sh tests/test_suite.py tests/test_wtf_cli.py
git commit -m "feat: suite dispatcher, tool registry, WTF Cleaner CLI and launch wrappers"
```

---

### Task 14: Shared UI: Ka0s theme, branding, base app, update prompt, setup/flavor screens, tool picker

**Files:**
- Create: `wowtools/ui/__init__.py`, `wowtools/ui/theme.py`, `wowtools/ui/branding.py`, `wowtools/ui/base.py`, `wowtools/ui/setup_screen.py`, `wowtools/ui/flavor_screen.py`, `wowtools/ui/tool_picker.py`, `tests/test_ui_base.py`

**Interfaces:**
- Consumes: `Config`, `GENERAL` (Task 4); `WowInstall`, `Flavor`, `detect_installs` (Task 5); `to_native`/`to_stored` (Task 2); `check_for_update`, `apply_update`, `ReleaseInfo`, `UpdateError` (Tasks 11–12); `TOOLS` (Task 13); `log_event`.
- Produces:
  - `KA0S_THEME` (Textual `Theme` named `ka0s`).
  - `BANNER`, `Banner(Static)`, `BrandBar(Static)`; `BrandBar.text` holds its current string.
  - `Ka0sApp(App)`:
    - `__init__(cfg, *, check_updates=True)`.
    - Attributes: `.cfg`, `.busy: bool`, `release` (reactive `ReleaseInfo | None`).
    - Hook: `after_mount()`, which subclasses override instead of `on_mount`.
    - `_update_found(release)`, `action_update()`.
  - `UpdateScreen(ModalScreen[bool])`.
  - `SetupScreen(Screen[bool])`: `__init__(cfg, *, first_run: bool, detect=detect_installs)`, `.error_text`.
  - `FlavorScreen(Screen)`: `__init__(cfg, install: WowInstall)`. It dismisses with a `Flavor` or `None`.
  - `ToolPickerApp(Ka0sApp)`: `run()` returns the chosen tool name or `None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ui_base.py`:
```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input

from tests.fixtures import build_wow_tree
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.updater import ReleaseInfo
from wowtools.ui.base import Ka0sApp, UpdateScreen
from wowtools.ui.branding import BrandBar
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.tool_picker import ToolPickerApp


class Host(Ka0sApp):
    """Pushes one screen and records what it dismisses with."""

    def __init__(self, cfg, screen):
        super().__init__(cfg, check_updates=False)
        self._screen = screen
        self.results = []

    def after_mount(self):
        self.push_screen(self._screen, self.results.append)


class UiTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.cfg = Config(self.tmp / "wow-tools.cfg")


class ToolPickerTest(UiTestCase):
    async def test_theme_branding_and_choice(self):
        app = ToolPickerApp(self.cfg, check_updates=False)
        async with app.run_test(size=(120, 40)) as pilot:
            self.assertEqual(app.theme, "ka0s")
            self.assertEqual(app.title, "Ka0s · WoW Tools")
            self.assertIn("Ka0s WoW Tools v0.1.0", app.query_one(BrandBar).text)
            await pilot.press("enter")
        self.assertEqual(app.return_value, "wtf-cleaner")

    async def test_update_badge_and_prompt(self):
        app = ToolPickerApp(self.cfg, check_updates=False)
        applied = []
        with patch("wowtools.ui.base.apply_update", side_effect=lambda rel: applied.append(rel) or "Updated"):
            async with app.run_test(size=(120, 40)) as pilot:
                app._update_found(ReleaseInfo.from_version("9.9.9"))
                await pilot.pause()
                self.assertIn("v9.9.9 available", app.query_one(BrandBar).text)
                await pilot.press("u")
                await pilot.pause()
                self.assertIsInstance(app.screen, UpdateScreen)
                await pilot.click("#update-yes")
                await pilot.pause()
        self.assertEqual([r.version for r in applied], ["9.9.9"])

    async def test_update_blocked_while_busy(self):
        app = ToolPickerApp(self.cfg, check_updates=False)
        async with app.run_test(size=(120, 40)) as pilot:
            app._update_found(ReleaseInfo.from_version("9.9.9"))
            app.busy = True
            await pilot.press("u")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, UpdateScreen)


class SetupScreenTest(UiTestCase):
    async def test_rejects_invalid_folder_then_saves(self):
        screen = SetupScreen(self.cfg, first_run=True, detect=lambda: [])
        app = Host(self.cfg, screen)
        with capture_events() as records:
            async with app.run_test(size=(120, 50)) as pilot:
                screen.query_one("#wow_path", Input).value = str(self.tmp / "nothing-here")
                await pilot.click("#save")
                await pilot.pause()
                self.assertIn("No WoW flavor folders", screen.error_text)
                self.assertEqual(app.results, [])
                screen.query_one("#wow_path", Input).value = str(self.root)
                await pilot.click("#save")
                await pilot.pause()
        self.assertEqual(app.results, [True])
        saved = Config(self.cfg.path).load()
        self.assertEqual(saved.wow_path, self.root)
        changed = [r for r in records if r["event"] == "config.changed"]
        self.assertEqual(changed[0]["data"]["source"], "wizard")

    async def test_prefills_detected_install(self):
        screen = SetupScreen(self.cfg, first_run=True, detect=lambda: [self.root])
        app = Host(self.cfg, screen)
        async with app.run_test(size=(120, 50)):
            self.assertEqual(screen.query_one("#wow_path", Input).value, str(self.root))


class FlavorScreenTest(UiTestCase):
    async def test_last_flavor_preselected_and_logged(self):
        self.cfg.set("general", "last_flavor", "_classic_era_")
        app = Host(self.cfg, FlavorScreen(self.cfg, WowInstall(self.root)))
        with capture_events() as records:
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
        self.assertEqual(app.results[0].folder, "_classic_era_")
        selections = [r["data"] for r in records if r["event"] == "ui.selection"]
        self.assertIn({"screen": "flavor", "control": "flavor", "value": "_classic_era_"}, selections)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ui_base -v`
Expected: ERROR, `No module named 'wowtools.ui'`.

- [ ] **Step 3: Implement theme and branding**

`wowtools/ui/__init__.py`:
```python
"""Shared Textual UI: Ka0s theme, branding, base app and common screens."""
```

`wowtools/ui/theme.py`:
```python
"""The Ka0s theme, taken from the Ka0s shield logo: navy-black, deep blue, electric-blue glow, steel silver."""
from __future__ import annotations

from textual.theme import Theme

KA0S_THEME = Theme(
    name="ka0s",
    primary="#2F8CFF",
    secondary="#8A96A8",
    accent="#5CC8FF",
    foreground="#D3DAE3",
    background="#05080F",
    surface="#0B1526",
    panel="#10213D",
    success="#4CC38A",
    warning="#E8B04B",
    error="#E5534B",
    dark=True,
)
```

`wowtools/ui/branding.py`:
```python
"""Ka0s branding widgets: the shield banner and the brand bar shown on every screen."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from wowtools import __version__

BANNER = "\n".join([
    "  ▗▄▄▄▄▄▄▄▄▄▄▄▖  ",
    "  ▐ ██  ▄██▀  ▌  ",
    "  ▐ ██▄██▀    ▌  ",
    "  ▐ ██▀██▄    ▌  ",
    "  ▐ ██  ▀██▄  ▌  ",
    "   ▀▄       ▄▀   ",
    "     ▀▀▄▄▄▀▀     ",
    "",
    "K a 0 s   ·   W o W   T o o l s",
])


class Banner(Static):
    DEFAULT_CSS = """
    Banner { width: 100%; height: auto; content-align: center middle; text-align: center;
             color: $accent; text-style: bold; padding: 1 0; }
    """

    def __init__(self) -> None:
        super().__init__(Text(BANNER))


class BrandBar(Static):
    DEFAULT_CSS = """
    BrandBar { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    """

    def __init__(self) -> None:
        super().__init__("")
        self.text = ""

    def on_mount(self) -> None:
        self.watch(self.app, "release", self._show, init=True)

    def _show(self, release) -> None:
        text = f"Ka0s WoW Tools v{__version__}"
        if release is not None:
            text += f"    ⬆ v{release.version} available, press u to update"
        self.text = text
        self.update(Text(text))
```

- [ ] **Step 4: Implement the base app and update screen**

`wowtools/ui/base.py`:
```python
"""Ka0sApp: theme, branding, background update check and the `u` update flow for every tool."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Markdown

from wowtools import __version__
from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.updater import ReleaseInfo, UpdateError, apply_update, check_for_update
from wowtools.ui.theme import KA0S_THEME


class UpdateScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    UpdateScreen { align: center middle; }
    UpdateScreen #update-box { width: 76; height: auto; max-height: 85%; border: thick $accent;
                               background: $panel; padding: 1 2; }
    UpdateScreen #update-notes { height: auto; max-height: 20; margin: 1 0; }
    UpdateScreen #update-buttons { height: auto; align-horizontal: right; }
    UpdateScreen Button { margin-left: 2; }
    """
    BINDINGS = [Binding("escape", "later", "Later")]

    def __init__(self, release: ReleaseInfo) -> None:
        super().__init__()
        self.release = release

    def compose(self) -> ComposeResult:
        with Vertical(id="update-box"):
            yield Label(f"Ka0s WoW Tools v{self.release.version} is available (you have v{__version__}).")
            with VerticalScroll(id="update-notes"):
                yield Markdown(self.release.notes or "_No release notes._")
            with Horizontal(id="update-buttons"):
                yield Button("Update now", variant="primary", id="update-yes")
                yield Button("Later", id="update-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "update-yes")

    def action_later(self) -> None:
        self.dismiss(False)


class Ka0sApp(App):
    """Base for every tool's TUI. Subclasses override after_mount(), not on_mount()."""

    TITLE = "Ka0s · WoW Tools"
    BINDINGS = [Binding("u", "update", "Update", show=False)]
    release: reactive[ReleaseInfo | None] = reactive(None)

    def __init__(self, cfg: Config, *, check_updates: bool = True) -> None:
        super().__init__()
        self.cfg = cfg
        self.busy = False
        self._check_updates = check_updates

    def on_mount(self) -> None:
        self.register_theme(KA0S_THEME)
        self.theme = "ka0s"
        if self._check_updates and self.cfg.check_for_updates:
            self.run_worker(self._check_update, thread=True, group="update-check")
        self.after_mount()

    def after_mount(self) -> None:
        """Hook for subclasses."""

    def _check_update(self) -> None:
        release = check_for_update(self.cfg)
        if release is not None:
            self.call_from_thread(self._update_found, release)

    def _update_found(self, release: ReleaseInfo) -> None:
        self.release = release
        self.notify(f"v{release.version} is available. Press u to update.",
                    title="Ka0s WoW Tools update", timeout=10)

    def action_update(self) -> None:
        if self.release is None:
            self.notify("You are on the latest version.")
            return
        if self.busy:
            self.notify("Finish the current task before updating.", severity="warning")
            return
        self.push_screen(UpdateScreen(self.release), self._update_answered)

    def _update_answered(self, accepted: bool | None) -> None:
        log_event("ui.selection", screen="update", control="update",
                  value="accepted" if accepted else "declined")
        if not accepted or self.release is None:
            return
        try:
            message = apply_update(self.release)
        except UpdateError as exc:
            self.notify(str(exc), title="Update failed", severity="error", timeout=15)
            return
        self.exit(message=message)
```

- [ ] **Step 5: Implement the setup, flavor and tool picker screens**

`wowtools/ui/setup_screen.py`:
```python
"""First-run and general settings: WoW folder and backup folder ([general] in wow-tools.cfg)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event
from wowtools.core.install import WowInstall, detect_installs
from wowtools.core.paths import to_native, to_stored
from wowtools.ui.branding import Banner, BrandBar


class SetupScreen(Screen[bool]):
    DEFAULT_CSS = """
    SetupScreen #setup { padding: 0 2; }
    SetupScreen .title { color: $accent; text-style: bold; margin: 1 0; }
    SetupScreen .hint { color: $text-muted; margin-bottom: 1; }
    SetupScreen #setup-error { color: $error; height: auto; }
    SetupScreen .buttons { height: auto; margin-top: 1; }
    SetupScreen Button { margin-right: 2; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, cfg: Config, *, first_run: bool,
                 detect: Callable[[], list[Path]] = detect_installs) -> None:
        super().__init__()
        self.cfg = cfg
        self.first_run = first_run
        self.error_text = ""
        self._detected = [] if cfg.wow_path else detect()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="setup"):
            yield Banner()
            yield Static("First-time setup" if self.first_run else "General settings", classes="title")
            yield Label("World of Warcraft folder (the one that contains _retail_, _classic_ and so on)")
            yield Input(value=self._initial_wow_path(), placeholder=r"C:\Program Files (x86)\World of Warcraft",
                        id="wow_path")
            yield Static(Text(self._detected_hint()), classes="hint")
            yield Label("Backup folder (leave empty to use <WoW folder>/wow-tools-backups)")
            yield Input(value=self.cfg.get(GENERAL, "backup_dir") or "", id="backup_dir")
            yield Static("", id="setup-error")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Setup"
        self.query_one("#wow_path", Input).focus()

    def _initial_wow_path(self) -> str:
        stored = self.cfg.get(GENERAL, "wow_path")
        if stored:
            return stored
        return to_stored(self._detected[0]) if self._detected else ""

    def _detected_hint(self) -> str:
        if self._detected:
            return "Found: " + "; ".join(to_stored(p) for p in self._detected)
        return "" if self.cfg.wow_path else "No installation was found automatically. Type or paste the folder."

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._save()

    def action_cancel(self) -> None:
        log_event("ui.selection", screen="setup", control="cancel", value=True)
        self.dismiss(False)

    def _save(self) -> None:
        raw = self.query_one("#wow_path", Input).value.strip()
        wow = to_native(raw) if raw else None
        if wow is None or not WowInstall(wow).is_valid():
            self.error_text = ("No WoW flavor folders (_retail_, _classic_ ...) were found there. "
                               "Choose the World of Warcraft folder itself.")
            self.query_one("#setup-error", Static).update(Text(self.error_text))
            return
        backup_raw = self.query_one("#backup_dir", Input).value.strip()
        source = "wizard" if self.first_run else "settings"
        self.cfg.set_path(GENERAL, "wow_path", wow, source=source)
        self.cfg.set_path(GENERAL, "backup_dir", to_native(backup_raw) if backup_raw else None, source=source)
        self.cfg.save()
        self.dismiss(True)
```

`wowtools/ui/flavor_screen.py`:
```python
"""Choose which WoW flavor (_retail_, _classic_era_, ...) to work on."""
from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event
from wowtools.core.install import Flavor, WowInstall
from wowtools.ui.branding import Banner, BrandBar


class FlavorScreen(Screen[Optional[Flavor]]):
    DEFAULT_CSS = """
    FlavorScreen .title { color: $accent; text-style: bold; padding: 0 2; }
    FlavorScreen OptionList { margin: 1 2; height: auto; max-height: 20; border: tall $primary; }
    """
    BINDINGS = [Binding("escape", "cancel", "Quit")]

    def __init__(self, cfg: Config, install: WowInstall) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavors = install.flavors()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Banner()
        yield Static("Choose a WoW flavor", classes="title")
        yield OptionList(*[Option(Text(f"{f.display_name}  ({f.folder})"), id=f.folder) for f in self.flavors],
                         id="flavors")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Choose flavor"
        options = self.query_one("#flavors", OptionList)
        folders = [f.folder for f in self.flavors]
        options.highlighted = folders.index(self.cfg.last_flavor) if self.cfg.last_flavor in folders else 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        flavor = next(f for f in self.flavors if f.folder == event.option.id)
        self.cfg.set(GENERAL, "last_flavor", flavor.folder)
        self.cfg.save_if_exists()
        log_event("ui.selection", screen="flavor", control="flavor", value=flavor.folder)
        self.dismiss(flavor)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

`wowtools/ui/tool_picker.py`:
```python
"""`python -m wowtools` with no tool: pick one from the registry."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.events import log_event
from wowtools.tools import TOOLS
from wowtools.ui.base import Ka0sApp
from wowtools.ui.branding import Banner, BrandBar


class ToolPickerApp(Ka0sApp):
    SUB_TITLE = "Choose a tool"
    CSS = """
    #pick-title { color: $accent; text-style: bold; padding: 0 2; }
    #tools { margin: 1 2; height: auto; border: tall $primary; }
    """
    BINDINGS = [Binding("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Banner()
        yield Static("Choose a tool", id="pick-title")
        yield OptionList(*[Option(Text(f"{t.title}  ·  {t.description}"), id=t.name) for t in TOOLS.values()],
                         id="tools")
        yield BrandBar()
        yield Footer()

    def after_mount(self) -> None:
        self.query_one("#tools", OptionList).highlighted = 0
        self.query_one("#tools", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        log_event("ui.selection", screen="tool_picker", control="tool", value=event.option.id)
        self.exit(event.option.id)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ui_base -v`
Expected: 6 tests, OK. If a Textual API behaves differently in 8.2.8 (for example the reactive watch on the app or `OptionList.highlighted`), fix the implementation, not the test's intent, and note it in the commit message.

- [ ] **Step 7: Commit**

```bash
git add wowtools/ui tests/test_ui_base.py
git commit -m "feat(ui): Ka0s theme, branding, base app with update prompt, setup/flavor/tool picker"
```

---

### Task 15: WTF Cleaner TUI (settings, review tree, confirm, result)

**Files:**
- Create: `wowtools/tools/wtf_cleaner/app.py`, `wowtools/tools/wtf_cleaner/review_screen.py`, `tests/test_wtf_app.py`

**Interfaces:**
- Consumes: `Ka0sApp`, `SetupScreen`, `FlavorScreen`, `Banner`, `BrandBar` (Task 14); `scan`, `evaluate`, `execute`, `load_settings`/`save_settings`, the report helpers (Tasks 8–10); `running_wow_executables` (Task 7).
- Produces:
  - `WtfCleanerApp(cfg, *, check_updates=True, wow_check=running_wow_executables, detect=detect_installs)`.
  - `CleanerSettingsScreen(Screen[bool])`: `__init__(cfg, *, source: str)`.
  - `ReviewScreen(Screen[str])`: `__init__(cfg, flavor, *, wow_check)`. Attributes: `.proposal`, `.unchecked: set[Path]`, `.dry_run`, `.criteria`, `.summary_text`. Methods: `._selection() -> list[ProposalItem]`, `.action_rescan()`. It dismisses with `"flavors"` or `"quit"`.
  - `ConfirmScreen(ModalScreen[bool])`, and `ResultScreen(Screen[str])` with `.result`.

- [ ] **Step 1: Write the failing tests**

`tests/test_wtf_app.py`:
```python
import tempfile
import unittest
from pathlib import Path

from textual.widgets import Input, Tree

from tests.fixtures import build_wow_tree, make_config
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools.wtf_cleaner.app import CleanerSettingsScreen, WtfCleanerApp
from wowtools.tools.wtf_cleaner.review_screen import ConfirmScreen, ResultScreen, ReviewScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen

SIZE = (140, 50)


class AppTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.backup_dir = self.tmp / "bk"
        self.cfg = make_config(self.tmp, self.root, backup_dir=str(self.backup_dir))

    def make_app(self, cfg=None, running=()):
        return WtfCleanerApp(cfg or self.cfg, check_updates=False, wow_check=lambda: list(running),
                             detect=lambda: [])

    async def open_review(self, app, pilot):
        await pilot.pause()
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        review = app.screen
        self.assertIsInstance(review, ReviewScreen)
        self.assertIsNotNone(review.proposal)
        return review


class ReviewFlowTest(AppTestCase):
    async def test_dry_run_flow_changes_nothing(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                self.assertEqual(len(review.proposal.items), 6)
                await pilot.press("d")
                self.assertTrue(review.dry_run)
                await pilot.press("c")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.press("y")
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertIsInstance(app.screen, ResultScreen)
                self.assertTrue(app.screen.result.dry_run)
                self.assertEqual(len(app.screen.result.would_delete), 8)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertFalse(self.backup_dir.exists())
        names = [r["event"] for r in records]
        self.assertIn("sv.would_delete", names)
        self.assertIn({"screen": "review", "control": "dry_run", "value": True},
                      [r["data"] for r in records if r["event"] == "ui.selection"])

    async def test_real_clean_backs_up_and_deletes(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIsInstance(app.screen, ResultScreen)
            self.assertEqual(len(app.screen.result.deleted), 8)
        self.assertFalse((self.sv / "Uninstalled.lua").exists())
        self.assertTrue((self.sv / "Auctionator.lua").exists())
        self.assertEqual(len(list(self.backup_dir.glob("*.zip"))), 1)

    async def test_declining_confirm_changes_nothing(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            self.assertIs(app.screen, review)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    async def test_toggle_excludes_item_and_criterion_keys_rebuild(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one(Tree)
            node = next(n for n in _walk(tree.root)
                        if n.data and n.data[0] == "item" and n.data[1].addon == "DisabledAddon")
            tree.focus()
            tree.move_cursor(node)
            await pilot.press("space")
            self.assertNotIn("DisabledAddon", {i.addon for i in review._selection()})
            self.assertIn("5 items", review.summary_text)
            await pilot.press("1")
            await pilot.pause()
            self.assertNotIn("Uninstalled", {i.addon for i in review.proposal.items})
            self.assertFalse(review.criteria.not_installed)

    async def test_wow_running_warning_is_shown_and_logged(self):
        app = self.make_app(running=["Wow.exe"])
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await pilot.press("c")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIn("Wow.exe", app.screen.body_text)
                await pilot.press("n")
        self.assertIn("wow.running_warning", [r["event"] for r in records])

    async def test_odd_names_render_without_markup(self):
        (self.sv / "[Weird] Addon.lua").write_text("x")
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            labels = [str(n.label) for n in _walk(review.query_one(Tree).root)]
            self.assertTrue(any("[Weird] Addon" in label for label in labels))


class FirstRunTest(AppTestCase):
    async def test_setup_then_settings_then_flavor(self):
        cfg = Config(self.tmp / "fresh.cfg")
        app = self.make_app(cfg=cfg)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, SetupScreen)
            app.screen.query_one("#wow_path", Input).value = str(self.root)
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsInstance(app.screen, CleanerSettingsScreen)
            app.screen.query_one("#max_age", Input).value = "30"
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
        saved = Config(cfg.path).load()
        self.assertEqual(saved.wow_path, self.root)
        self.assertEqual(saved.get("wtf_cleaner", "max_age_days"), "30")

    async def test_settings_rejects_bad_max_age(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            screen = CleanerSettingsScreen(self.cfg, source="settings")
            app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#max_age", Input).value = "0"
            await pilot.click("#save")
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertIn("whole number", screen.error_text)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_wtf_app -v`
Expected: ERROR, `No module named 'wowtools.tools.wtf_cleaner.app'`.

- [ ] **Step 3: Implement the review, confirm and result screens**

`wowtools/tools/wtf_cleaner/review_screen.py`:
```python
"""Review the proposal as a tree, tick/untick, toggle criteria and dry run, then clean."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Static, Tree

from wowtools.core.backup import BackupError
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import ACCOUNT_WIDE, Flavor
from wowtools.tools.wtf_cleaner.cleaner import CleanError, CleanResult, execute
from wowtools.tools.wtf_cleaner.report import CRITERION_SHORT, age_days, format_result_text, format_size
from wowtools.tools.wtf_cleaner.rules import CRITERIA, ProposalItem, evaluate
from wowtools.tools.wtf_cleaner.scanner import ScanError, ScanResult, scan
from wowtools.tools.wtf_cleaner.settings import load_settings
from wowtools.ui.branding import BrandBar

ACCENT = "bold #5CC8FF"
REASON = "#E8B04B"


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen #confirm-box { width: 80; height: auto; border: thick $accent; background: $panel; padding: 1 2; }
    ConfirmScreen #confirm-title { color: $accent; text-style: bold; margin-bottom: 1; }
    ConfirmScreen #confirm-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    ConfirmScreen Button { margin-left: 2; }
    """
    BINDINGS = [Binding("y", "answer(True)", "Yes"), Binding("n,escape", "answer(False)", "No")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(Text(self.title_text), id="confirm-title")
            yield Static(Text(self.body_text))
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes (y)", variant="primary", id="yes")
                yield Button("No (n)", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class ResultScreen(Screen[str]):
    DEFAULT_CSS = """
    ResultScreen #result { padding: 1 2; }
    ResultScreen .buttons { height: auto; padding: 0 2; }
    ResultScreen Button { margin-right: 2; }
    """
    BINDINGS = [Binding("r", "choose('review')", "Rescan"), Binding("f", "choose('flavors')", "Flavors"),
                Binding("q", "choose('quit')", "Quit")]

    def __init__(self, result: CleanResult) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="result"):
            yield Static(Text(format_result_text(self.result)))
        with Horizontal(classes="buttons"):
            yield Button("Rescan (r)", variant="primary", id="review")
            yield Button("Other flavor (f)", id="flavors")
            yield Button("Quit (q)", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "WTF Cleaner · dry run result" if self.result.dry_run else "WTF Cleaner · result"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "quit")

    def action_choose(self, choice: str) -> None:
        log_event("ui.selection", screen="result", control="next", value=choice)
        self.dismiss(choice)


class ReviewScreen(Screen[str]):
    DEFAULT_CSS = """
    ReviewScreen #status { height: auto; padding: 0 1; color: $text-muted; }
    ReviewScreen #status.dry { background: $warning; color: $background; text-style: bold; }
    ReviewScreen #body { height: 1fr; }
    ReviewScreen #filters { width: 36; padding: 1; border-right: solid $primary; }
    ReviewScreen .section { color: $accent; text-style: bold; margin: 1 0 0 0; }
    ReviewScreen #proposal { width: 1fr; padding: 0 1; }
    ReviewScreen #summary { height: auto; padding: 0 1; background: $surface; }
    """
    BINDINGS = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("d", "toggle_dry_run", "Dry run"),
        Binding("c", "clean", "Clean"),
        Binding("r", "rescan", "Rescan"),
        Binding("f", "flavors", "Flavors"),
        Binding("q", "quit_tool", "Quit"),
        Binding("1", "criterion(0)", CRITERION_SHORT["not_installed"], show=False),
        Binding("2", "criterion(1)", CRITERION_SHORT["not_enabled"], show=False),
        Binding("3", "criterion(2)", CRITERION_SHORT["older_than"], show=False),
        Binding("4", "criterion(3)", CRITERION_SHORT["stray_copies"], show=False),
    ]

    def __init__(self, cfg: Config, flavor: Flavor, *, wow_check: Callable[[], list[str] | None]) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavor = flavor
        self.wow_check = wow_check
        self.settings = load_settings(cfg)
        self.criteria = self.settings.criteria.copy()
        self.dry_run = False
        self.scan_result: ScanResult | None = None
        self.proposal = None
        self.unchecked: set[Path] = set()
        self.summary_text = ""

    # --- layout -------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="status")
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("Criteria (keys 1-4)", classes="section")
                for index, name in enumerate(CRITERIA, start=1):
                    yield Checkbox(f"{index} {CRITERION_SHORT[name]}", getattr(self.criteria, name),
                                   id=f"crit_{name}")
                yield Label("Max age in days (Enter)", classes="section")
                yield Input(str(self.criteria.max_age_days), type="integer", id="max_age")
            yield Tree(Text(self.flavor.display_name), id="proposal")
        yield Static("", id="summary")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self._update_status()
        self.query_one("#proposal", Tree).focus()
        self.action_rescan()

    # --- scanning ------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        self.settings = load_settings(self.cfg)
        self.scan_result = None
        tree = self.query_one("#proposal", Tree)
        tree.loading = True
        self.run_worker(self._scan_worker, thread=True, exclusive=True, group="scan")

    def _scan_worker(self) -> None:
        try:
            result = scan(self.flavor)
        except ScanError as exc:
            log_exception("scan", exc)
            self.app.call_from_thread(self._scan_failed, str(exc))
            return
        self.app.call_from_thread(self._scanned, result)

    def _scan_failed(self, message: str) -> None:
        self.query_one("#proposal", Tree).loading = False
        self.summary_text = message
        self.query_one("#summary", Static).update(Text(message))
        self.notify(message, title="Scan failed", severity="error", timeout=15)

    def _scanned(self, result: ScanResult) -> None:
        self.scan_result = result
        self.query_one("#proposal", Tree).loading = False
        self._rebuild()

    # --- tree ------------------------------------------------------------------------------------
    def _rebuild(self) -> None:
        if self.scan_result is None:
            return
        self.proposal = evaluate(self.scan_result, self.criteria)
        tree = self.query_one("#proposal", Tree)
        tree.clear()
        tree.root.data = ("group", self.proposal.items, self.flavor.display_name)
        owners: dict[str, dict[str, list[ProposalItem]]] = {}
        for item in self.proposal.items:
            owners.setdefault(item.account, {}).setdefault(item.owner_label, []).append(item)
        for account in sorted(owners, key=str.casefold):
            account_items = [i for items in owners[account].values() for i in items]
            account_node = tree.root.add("", data=("group", account_items, account), expand=True)
            for owner in sorted(owners[account], key=lambda o: (o != ACCOUNT_WIDE, o.casefold())):
                items = sorted(owners[account][owner], key=lambda i: i.addon.casefold())
                owner_node = account_node.add("", data=("group", items, owner), expand=True)
                for item in items:
                    item_node = owner_node.add("", data=("item", item))
                    for sv in item.files:
                        item_node.add_leaf("", data=("file", item, sv))
        tree.root.expand()
        self._refresh_labels()

    @staticmethod
    def _paths(data) -> list[Path]:
        kind = data[0]
        if kind == "file":
            return [data[2].path]
        if kind == "item":
            return [f.path for f in data[1].files]
        return [f.path for item in data[1] for f in item.files]

    def _label(self, data) -> Text:
        now = time.time()
        paths = self._paths(data)
        unchecked = sum(1 for p in paths if p in self.unchecked)
        mark = "☐ " if paths and unchecked == len(paths) else ("◩ " if unchecked else "☑ ")
        kind = data[0]
        if kind == "file":
            sv = data[2]
            return Text.assemble((mark, "bold"), sv.name,
                                 (f"  {format_size(sv.size)} · {age_days(sv.mtime, now)}d", "dim"))
        if kind == "item":
            item = data[1]
            return Text.assemble((mark, "bold"), (item.addon, "bold"), "  ", (", ".join(item.reasons), REASON),
                                 (f"  {len(item.files)} files · {format_size(item.total_size)} · "
                                  f"{age_days(item.newest_mtime, now)}d", "dim"))
        items, name = data[1], data[2]
        return Text.assemble((mark, "bold"), (name, ACCENT), (f"  {len(items)} items", "dim"))

    def _refresh_labels(self) -> None:
        tree = self.query_one("#proposal", Tree)
        stack = [tree.root]
        while stack:
            node = stack.pop()
            if node.data is not None:
                node.set_label(self._label(node.data))
            stack.extend(node.children)
        self._update_summary()

    def _selection(self) -> list[ProposalItem]:
        if self.proposal is None:
            return []
        selected = []
        for item in self.proposal.items:
            files = [f for f in item.files if f.path not in self.unchecked]
            if files:
                selected.append(item.with_files(files))
        return selected

    def _update_summary(self) -> None:
        selection = self._selection()
        files = sum(len(i.files) for i in selection)
        size = sum(i.total_size for i in selection)
        text = (f"Selected: {len(selection)} items · {files} files · {format_size(size)}    "
                f"Criteria: {self.criteria.describe()}")
        if self.proposal is not None and not self.proposal.items:
            text = "Nothing to clean with the current criteria.    " + text
        if self.proposal is not None and self.proposal.warnings:
            text += f"    ⚠ {len(self.proposal.warnings)} scan warnings (see the log)"
        self.summary_text = text
        self.query_one("#summary", Static).update(Text(text))

    def _update_status(self) -> None:
        status = self.query_one("#status", Static)
        if self.dry_run:
            status.update(Text("DRY RUN: nothing will be backed up or deleted (press d to turn off)"))
            status.add_class("dry")
            self.sub_title = f"WTF Cleaner · {self.flavor.display_name} · DRY RUN"
        else:
            status.update(Text("space tick/untick · a all · n none · 1-4 criteria · d dry run · c clean"))
            status.remove_class("dry")
            self.sub_title = f"WTF Cleaner · {self.flavor.display_name}"

    # --- actions ---------------------------------------------------------------------------------
    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Checkbox):
            focused.toggle()
            return
        node = self.query_one("#proposal", Tree).cursor_node
        if node is None or node.data is None:
            return
        paths = self._paths(node.data)
        check = any(p in self.unchecked for p in paths)
        if check:
            self.unchecked.difference_update(paths)
        else:
            self.unchecked.update(paths)
        key = str(paths[0]) if node.data[0] == "file" else (
            node.data[1].key if node.data[0] == "item" else node.data[2])
        log_event("ui.item_toggled", screen="review", key=key, checked=check)
        self._refresh_labels()

    def action_select_all(self) -> None:
        self.unchecked.clear()
        log_event("ui.selection", screen="review", control="select_all", value=True)
        self._refresh_labels()

    def action_select_none(self) -> None:
        if self.proposal is not None:
            self.unchecked = {f.path for item in self.proposal.items for f in item.files}
        log_event("ui.selection", screen="review", control="select_none", value=True)
        self._refresh_labels()

    def action_toggle_dry_run(self) -> None:
        self.dry_run = not self.dry_run
        log_event("ui.selection", screen="review", control="dry_run", value=self.dry_run)
        self._update_status()

    def action_criterion(self, index: int) -> None:
        self.query_one(f"#crit_{CRITERIA[index]}", Checkbox).toggle()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        name = (event.checkbox.id or "").removeprefix("crit_")
        if name not in CRITERIA:
            return
        setattr(self.criteria, name, event.value)
        log_event("ui.selection", screen="review", control=f"criterion.{name}", value=event.value)
        self._rebuild()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "max_age":
            return
        try:
            days = int(event.value)
        except ValueError:
            days = 0
        if days < 1:
            self.notify("Max age must be a whole number of days, at least 1.", severity="warning")
            return
        self.criteria.max_age_days = days
        log_event("ui.selection", screen="review", control="max_age_days", value=days)
        self._rebuild()
        self.query_one("#proposal", Tree).focus()

    def action_flavors(self) -> None:
        if not self.app.busy:
            self.dismiss("flavors")

    def action_quit_tool(self) -> None:
        if not self.app.busy:
            self.dismiss("quit")

    # --- cleaning --------------------------------------------------------------------------------
    def action_clean(self) -> None:
        if self.proposal is None or self.app.busy:
            return
        selection = self._selection()
        if not selection:
            self.notify("Nothing is selected.")
            return
        running = self.wow_check()
        if running:
            log_event("wow.running_warning", executables=running)
        backup = self.settings.backup_before_delete
        backup_dir = self.cfg.backup_dir
        files = sum(len(i.files) for i in selection)
        size = format_size(sum(i.total_size for i in selection))
        lines = [f"{len(selection)} addon groups, {files} files, {size}."]
        lines.append(f"Backup zip goes to: {backup_dir}" if backup else "No backup will be made (backup is off in settings).")
        if self.dry_run:
            lines.append("DRY RUN: nothing will be written or deleted.")
        if running:
            lines.append(f"WoW appears to be running ({', '.join(running)}). Close it first: WoW rewrites "
                         "SavedVariables when you log out.")
        title = "Simulate this clean?" if self.dry_run else "Back up and delete these files?"
        self.app.push_screen(ConfirmScreen(title, "\n".join(lines)),
                             lambda ok: self._confirmed(ok, selection, backup, backup_dir))

    def _confirmed(self, ok: bool | None, selection: list[ProposalItem], backup: bool,
                   backup_dir: Path | None) -> None:
        log_event("ui.selection", screen="confirm", control="confirm", value=bool(ok), dry_run=self.dry_run)
        if not ok:
            return
        self.app.busy = True
        self.run_worker(lambda: self._clean_worker(selection, backup, backup_dir), thread=True,
                        exclusive=True, group="clean")

    def _clean_worker(self, selection: list[ProposalItem], backup: bool, backup_dir: Path | None) -> None:
        try:
            result = execute(selection, self.flavor, dry_run=self.dry_run, backup=backup, backup_dir=backup_dir)
        except (BackupError, CleanError) as exc:
            if isinstance(exc, CleanError):
                log_exception("clean", exc)
            self.app.call_from_thread(self._clean_failed, exc)
            return
        self.app.call_from_thread(self._cleaned, result)

    def _clean_failed(self, exc: Exception) -> None:
        self.app.busy = False
        self.notify(f"Nothing was deleted: {exc}", title="Clean stopped", severity="error", timeout=20)

    def _cleaned(self, result: CleanResult) -> None:
        self.app.busy = False
        self.unchecked.clear()
        self.app.push_screen(ResultScreen(result), self._after_result)

    def _after_result(self, choice: str | None) -> None:
        if choice == "flavors":
            self.dismiss("flavors")
        elif choice == "quit":
            self.dismiss("quit")
        else:
            self.action_rescan()
```

- [ ] **Step 4: Implement the app and settings screen**

`wowtools/tools/wtf_cleaner/app.py`:
```python
"""The WTF Cleaner TUI: setup → settings → flavor → review → confirm → result."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, Switch

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall, detect_installs
from wowtools.core.process import running_wow_executables
from wowtools.tools.wtf_cleaner.report import CRITERION_LABELS
from wowtools.tools.wtf_cleaner.review_screen import ReviewScreen
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria
from wowtools.tools.wtf_cleaner.settings import CleanerSettings, load_settings, save_settings
from wowtools.ui.base import Ka0sApp
from wowtools.ui.branding import BrandBar
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen


class CleanerSettingsScreen(Screen[bool]):
    DEFAULT_CSS = """
    CleanerSettingsScreen #settings { padding: 0 2; }
    CleanerSettingsScreen .title { color: $accent; text-style: bold; margin: 1 0; }
    CleanerSettingsScreen .row { height: auto; margin-bottom: 1; }
    CleanerSettingsScreen .row Label { padding: 1 0 0 1; }
    CleanerSettingsScreen #settings-error { color: $error; height: auto; }
    CleanerSettingsScreen .buttons { height: auto; margin-top: 1; }
    CleanerSettingsScreen Button { margin-right: 2; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, cfg: Config, *, source: str) -> None:
        super().__init__()
        self.cfg = cfg
        self.source = source
        self.settings = load_settings(cfg)
        self.error_text = ""

    def compose(self) -> ComposeResult:
        criteria = self.settings.criteria
        yield Header()
        with VerticalScroll(id="settings"):
            yield Static("WTF Cleaner settings", classes="title")
            yield Label("Propose SavedVariables older than this many days")
            yield Input(str(criteria.max_age_days), type="integer", id="max_age")
            yield Static("Propose SavedVariables when:", classes="title")
            for name in CRITERIA:
                with Horizontal(classes="row"):
                    yield Switch(getattr(criteria, name), id=f"sw_{name}")
                    yield Label(CRITERION_LABELS[name])
            with Horizontal(classes="row"):
                yield Switch(self.settings.backup_before_delete, id="sw_backup")
                yield Label("Back up files to a timestamped zip before deleting (recommended)")
            yield Static("", id="settings-error")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "WTF Cleaner settings"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _save(self) -> None:
        try:
            days = int(self.query_one("#max_age", Input).value)
        except ValueError:
            days = 0
        if days < 1:
            self.error_text = "Max age must be a whole number of days, at least 1."
            self.query_one("#settings-error", Static).update(Text(self.error_text))
            return
        criteria = Criteria(**{name: self.query_one(f"#sw_{name}", Switch).value for name in CRITERIA},
                            max_age_days=days)
        save_settings(self.cfg, CleanerSettings(criteria, self.query_one("#sw_backup", Switch).value),
                      source=self.source)
        self.dismiss(True)


class WtfCleanerApp(Ka0sApp):
    SUB_TITLE = "WTF Cleaner"
    BINDINGS = [Binding("s", "settings", "Settings")]

    def __init__(self, cfg: Config, *, check_updates: bool = True,
                 wow_check: Callable[[], list[str] | None] = running_wow_executables,
                 detect: Callable[[], list[Path]] = detect_installs) -> None:
        super().__init__(cfg, check_updates=check_updates)
        self._wow_check = wow_check
        self._detect = detect

    def after_mount(self) -> None:
        if self._install() is None:
            self.push_screen(SetupScreen(self.cfg, first_run=True, detect=self._detect), self._after_setup)
        else:
            self._pick_flavor()

    def _install(self) -> WowInstall | None:
        path = self.cfg.wow_path
        if path is None:
            return None
        install = WowInstall(path)
        return install if install.is_valid() else None

    def _after_setup(self, ok: bool | None) -> None:
        if not ok:
            self.exit()
            return
        self.push_screen(CleanerSettingsScreen(self.cfg, source="wizard"), lambda _: self._pick_flavor())

    def _pick_flavor(self) -> None:
        install = self._install()
        if install is None:
            self.push_screen(SetupScreen(self.cfg, first_run=True, detect=self._detect), self._after_setup)
            return
        self.push_screen(FlavorScreen(self.cfg, install), self._after_flavor)

    def _after_flavor(self, flavor: Flavor | None) -> None:
        if flavor is None:
            self.exit()
            return
        self.push_screen(ReviewScreen(self.cfg, flavor, wow_check=self._wow_check), self._after_review)

    def _after_review(self, choice: str | None) -> None:
        if choice == "flavors":
            self._pick_flavor()
        else:
            self.exit()

    def action_settings(self) -> None:
        if self.busy or isinstance(self.screen, (SetupScreen, CleanerSettingsScreen)):
            return
        self.push_screen(SetupScreen(self.cfg, first_run=False, detect=self._detect),
                         lambda _: self.push_screen(CleanerSettingsScreen(self.cfg, source="settings"),
                                                    self._settings_done))

    def _settings_done(self, saved: bool | None) -> None:
        if saved:
            self.notify("Settings saved. Press r on the review screen to rescan with them.")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_wtf_app -v`
Expected: 8 tests, OK. If Textual 8.2.8 differs on a detail (for example `Tree.move_cursor`, the `Checkbox.toggle()` name, or whether the priority `space` binding reaches the screen), adapt the implementation to keep the tested behaviour, and record it in the commit message.

- [ ] **Step 6: Smoke-test by hand against a copy (not the real install)**

Run: `python3 -c "from tests.fixtures import build_wow_tree; from pathlib import Path; import tempfile; d=Path(tempfile.mkdtemp()); print(build_wow_tree(d/'World of Warcraft'))"`. Then run `python3 -m wowtools wtf-cleaner --tui`, point setup at the printed folder, and walk through flavor → review → `d` → `c` → `y`. Check that the colours match the Ka0s theme (navy background, blue accents) and that the brand bar shows. Then restore or delete `wow-tools.cfg` if you created it in the repo.

- [ ] **Step 7: Run the whole suite and commit**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all OK.

```bash
git add wowtools/tools/wtf_cleaner/app.py wowtools/tools/wtf_cleaner/review_screen.py tests/test_wtf_app.py
git commit -m "feat(wtf-cleaner): Textual TUI with review tree, dry run, confirm and results"
```

---

### Task 16: Documentation (README, developer docs, generated event reference, CLAUDE.md)

**Files:**
- Create: `scripts/gen_event_docs.py`, `docs/events.md` (generated), `tests/test_docs.py`, `README.md`, `docs/architecture.md`, `docs/adding-a-tool.md`, `docs/vendoring.md`, `docs/releasing.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `TOOL_REGISTRIES` (Task 3), `TOOLS` (Task 13).
- Produces: `scripts/gen_event_docs.py` with `render() -> str` and `main() -> int` (`--check` exits 1 when `docs/events.md` is stale).

- [ ] **Step 1: Write the failing test**

`tests/test_docs.py`:
```python
import importlib.util
import unittest

from wowtools.core.bootstrap import REPO_ROOT


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_event_docs", REPO_ROOT / "scripts" / "gen_event_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocsTest(unittest.TestCase):
    def test_event_reference_is_up_to_date(self):
        generated = load_generator().render()
        on_disk = (REPO_ROOT / "docs" / "events.md").read_text(encoding="utf-8")
        self.assertEqual(on_disk, generated, "Run: python3 scripts/gen_event_docs.py")

    def test_every_event_is_documented(self):
        text = (REPO_ROOT / "docs" / "events.md").read_text(encoding="utf-8")
        for name in ("session.start", "config.changed", "sv.deleted", "backup.created", "update.available"):
            self.assertIn(f"`{name}`", text)

    def test_readme_mentions_every_tool_and_cli_flag(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for needle in ("wtf-cleaner", "--dry-run", "--clean", "--no-backup", "--criteria", "--max-age",
                       "--json", "python -m wowtools update", "stray_copies", "Restoring a backup"):
            self.assertIn(needle, readme)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_docs -v`
Expected: ERROR, `No such file ... gen_event_docs.py`.

- [ ] **Step 3: Write the generator and generate `docs/events.md`**

`scripts/gen_event_docs.py`:
```python
#!/usr/bin/env python3
"""Regenerate docs/events.md from the event registries. `--check` fails if the file is stale."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wowtools.core.bootstrap import add_vendor_path  # noqa: E402

add_vendor_path()

from wowtools.core.events import LEVELS, SCHEMA_VERSION, TOOL_REGISTRIES  # noqa: E402
from wowtools.tools import TOOLS  # noqa: E402

TARGET = ROOT / "docs" / "events.md"

HEADER = f"""# Event log reference

> Generated by `python3 scripts/gen_event_docs.py`. Do not edit by hand.

Every tool writes to the same log in `logs/`:

- `events-YYYY-MM-DD.jsonl`: one JSON object per line, **all** levels (source of truth).
- `wow-tools-YYYY-MM-DD.log`: the same events as readable lines, filtered by `[general] log_level`.

Files older than `[general] log_retention_days` (default 90) are deleted at start-up.

## Envelope (schema v{SCHEMA_VERSION})

| Field | Meaning |
|---|---|
| `v` | Schema version. Only changes when envelope fields change meaning. |
| `ts` | Local time, ISO-8601 with UTC offset and milliseconds. |
| `session` | 8 hex characters, one per launch. Group a run's events by this. |
| `suite_version` | `wowtools.__version__`. |
| `tool` | `suite` (launcher / picker) or the tool name, e.g. `wtf-cleaner`. |
| `mode` | `tui` or `cli`. |
| `event` | Dotted name from the tables below. |
| `level` | {", ".join(f"`{name}`" for name in LEVELS)}. Fixed per event; a caller may only raise it. |
| `dry_run` | `true`/`false` where it matters, otherwise `null`. |
| `data` | Event-specific fields. New fields may be added at any time. |

## Adding events to a tool

Declare them in `wowtools/tools/<tool>/events.py` as `EVENTS = {{"name": EventSpec(level, description)}}`
and call `register_events(TOOL_NAME, EVENTS)` there; import that module from the tool package's
`__init__.py`. Then call `log_event("name", **data)`. Regenerate this file and commit it.
"""


def render() -> str:
    for tool in TOOLS.values():
        importlib.import_module(tool.module.rsplit(".", 1)[0])
    parts = [HEADER]
    for owner, events in TOOL_REGISTRIES.items():
        if owner.startswith("test-"):
            continue
        parts.append(f"\n## `{owner}` events\n\n| Event | Level | Description |\n|---|---|---|\n")
        for name in sorted(events):
            spec = events[name]
            parts.append(f"| `{name}` | {spec.level} | {spec.description} |\n")
    return "".join(parts)


def main() -> int:
    text = render()
    if "--check" in sys.argv[1:]:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print("docs/events.md is out of date. Run: python3 scripts/gen_event_docs.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run: `python3 scripts/gen_event_docs.py`
Expected: `wrote …/docs/events.md`, with sections for `core` and `wtf-cleaner`.

Note: `test_events.py` registers `test-a`, `test-b` and `test-c` owners into the global registry. The generator skips owners starting with `test-`, so the file matches whether or not those tests ran first in the same process.

- [ ] **Step 4: Write `README.md`**

````markdown
<p align="center"><img src="docs/assets/ka0s-logo.png" alt="Ka0s" width="220"></p>

# Ka0s WoW Tools

Out-of-game companion tools for World of Warcraft. The tools share one settings file, one set of
bundled libraries and one look, and they run straight from this folder on Windows, Linux and WSL.
There's no `pip install` and no virtualenv.

| Tool | What it does |
|---|---|
| **WTF Cleaner** (`wtf-cleaner`) | Finds SavedVariables left behind by addons you no longer use, backs them up to a zip, and deletes them. |
| Screenshot Organizer | Coming later. |

## Requirements

- **Python 3.10 or newer.** On Windows, install it from python.org (tick "Add python.exe to PATH") or the
  Microsoft Store. The `py` launcher is used when present.
- World of Warcraft, in any flavor: Retail, Classic, Classic Era, Anniversary, PTR or Beta.

## Getting it

- **With git (recommended, so updates are one command):**
  `git clone https://github.com/tusharsaxena/wow-tools.git`
- **As a zip:** download the latest release from
  [Releases](https://github.com/tusharsaxena/wow-tools/releases) and unzip it anywhere.

## Quick start

| Platform | WTF Cleaner | Tool menu |
|---|---|---|
| Windows | double-click `wtf-cleaner.cmd` | `wow-tools.cmd` |
| Linux / WSL | `./wtf-cleaner.sh` | `./wow-tools.sh` |
| Anywhere | `python -m wowtools wtf-cleaner` (from this folder) | `python -m wowtools` |

**First launch.** A short setup asks for:

1. **Your World of Warcraft folder.** This is the folder that contains `_retail_`, `_classic_` and so on.
   Common locations on every drive are detected for you.
2. **A backup folder.** Leave it empty to use `<WoW folder>\wow-tools-backups`.
3. **WTF Cleaner settings.** These are the age limit, which criteria to use, and whether to back up before deleting.

Your answers are saved in `wow-tools.cfg` next to this README. Then you pick a **flavor**, and the last one you
used is pre-selected next time.

> **Close WoW before cleaning.** WoW rewrites SavedVariables when you log out, and it can recreate files you
> just removed. The tool warns you if it sees WoW running.

## WTF Cleaner

### What gets proposed

Each rule can be switched on or off. By default **all four are on**, and a file is proposed if **any**
rule matches.

| Criterion | Proposes… | Example |
|---|---|---|
| `not_installed` | SavedVariables for addons no longer in `Interface\AddOns` | `WTF\Account\ME\SavedVariables\OldBagAddon.lua` |
| `not_enabled` | SavedVariables for installed addons that **no character in any account** has enabled | Addon disabled on every character |
| `older_than` | Addons whose newest SavedVariables file is older than the age limit (default 90 days) | `Recount.lua` untouched since last expansion |
| `stray_copies` | Hand-made copies next to real files: anything but `<Addon>.lua` / `<Addon>.lua.bak` | `Details.lua - Copy.bak`, `Plater.lua.pre-update` |

It looks in every account, both account-wide (`WTF\Account\<ACCOUNT>\SavedVariables`) and
per character (`WTF\Account\<ACCOUNT>\<Realm>\<Character>\SavedVariables`). An addon's `.lua` and `.lua.bak`
files are treated as one group.

"Enabled" is judged across the whole flavor. If an addon is enabled on any character, its SavedVariables are
kept everywhere. A character with no `AddOns.txt`, or an addon that isn't listed in it, counts as enabled,
because that's what WoW does.

### What is never touched

- `Blizzard_*` SavedVariables.
- Everything outside `SavedVariables` folders: `config-cache.wtf`, keybindings, macros, `AddOns.txt`,
  layouts, chat settings.
- Anything outside the chosen flavor's `WTF\Account` folder.

If a flavor has no addons installed at all, the scan stops rather than proposing everything.

### Using the TUI

The review screen shows a tree: account → account-wide / each character → addon → files.
Everything starts ticked.

| Key | Action |
|---|---|
| `space` | Tick or untick the highlighted account, character, addon or file |
| `a` / `n` | Tick all / none |
| `1` `2` `3` `4` | Toggle `not_installed`, `not_enabled`, `older_than`, `stray_copies` |
| Max age box + `Enter` | Change the age limit for this session |
| `d` | Toggle **dry run** (a yellow DRY RUN bar shows while it is on) |
| `c` | Clean the ticked files (asks for confirmation first) |
| `r` | Rescan |
| `f` | Choose another flavor |
| `s` | Settings |
| `u` | Install an available update |
| `q` | Quit |

### Dry run

A dry run does everything except write the zip and delete files. It shows exactly what would be backed up
and deleted, and it's recorded in the log.

### Backups

Before deleting, the cleaner writes
`<backup folder>\wtf-cleaner_<flavor>_<YYYYMMDD-HHMMSS>.zip`, then re-opens it and checks every file.
**If the backup can't be written or verified, nothing is deleted.** Each zip contains a
`manifest.json` that lists every file, its size and why it was removed. You can turn backups off in settings,
or with `--no-backup --yes` on the command line, but it isn't recommended.

### Restoring a backup

Close WoW, then unzip the backup **into the flavor folder** (for example `World of Warcraft\_retail_`), keeping
the folder structure. The paths inside the zip start with `WTF\Account\…`, so the files land back where they
were. You can ignore `manifest.json`.

### Command line

Every flag also works through `wtf-cleaner.cmd` / `wtf-cleaner.sh`.

```
python -m wowtools wtf-cleaner --flavor retail                     # show the proposal (read-only)
python -m wowtools wtf-cleaner --flavor retail --clean             # back up + delete, asks y/N
python -m wowtools wtf-cleaner --flavor retail --clean --dry-run   # simulate
python -m wowtools wtf-cleaner --flavor classic_era --clean --yes  # no prompt (for scripts)
python -m wowtools wtf-cleaner --flavor retail --json --criteria not_installed,stray_copies
```

| Flag | Meaning |
|---|---|
| `--flavor NAME` | `retail`, `classic`, `classic_era`, `anniversary`, … (default: last used) |
| `--clean` | Back up and delete the proposal (asks first) |
| `--yes` | Don't ask |
| `--dry-run` | Simulate. Nothing is written or deleted. |
| `--no-backup` | Skip the zip (only with `--yes`) |
| `--max-age DAYS` | Override the age limit |
| `--criteria LIST` | Comma list of `not_installed,not_enabled,older_than,stray_copies` |
| `--wow-path PATH` / `--backup-dir PATH` | Override the configured folders for this run |
| `--json` | Machine-readable output (`--clean --json` also needs `--yes` or `--dry-run`) |
| `--tui` | Open the TUI even when other flags are given |

Exit codes: `0` ok · `1` usage or config problem · `2` scan refused (e.g. no addons installed) ·
`3` finished but some files could not be deleted · `4` backup failed (nothing deleted).

## Settings (`wow-tools.cfg`)

The file is created on first launch. Press `s` in the TUI to change the common settings, or edit the file
directly while no tool is running.

| Section / key | Default | Meaning |
|---|---|---|
| `[general] wow_path` | (asked) | WoW folder. Stored as a Windows path so it works from Windows **and** WSL. |
| `[general] backup_dir` | `<wow_path>\wow-tools-backups` | Where backup zips go |
| `[general] last_flavor` | | Pre-selected flavor |
| `[general] check_for_updates` | `true` | Check GitHub for a new version (at most once a day) |
| `[general] auto_update` | `false` | Install new versions automatically on launch |
| `[general] log_level` | `info` | Detail level of the readable log (`debug`, `info`, `warning`, `error`) |
| `[general] log_retention_days` | `90` | Delete log files older than this |
| `[wtf_cleaner] max_age_days` | `90` | Age limit for `older_than` |
| `[wtf_cleaner] criterion_*` | `true` | Default on/off for each criterion |
| `[wtf_cleaner] backup_before_delete` | `true` | Zip before deleting |

## Updates

On launch the suite checks GitHub Releases in the background, at most once a day. If a newer version exists,
the TUI shows it in the bottom bar (press `u`) and the command line prints a one-line notice.

- `python -m wowtools update --check` reports whether an update is available.
- `python -m wowtools update` installs it. A git clone is fast-forwarded to the release tag, and it refuses if
  you have local changes. A zip install downloads the release and replaces the program files, keeping a copy
  in `.update-backup\` and rolling back if anything fails. Your `wow-tools.cfg`, `logs\` and backups are never
  touched.

Set `auto_update = true` to install updates on launch without asking.

## Logs

Everything the tools do is logged in `logs\`, including settings changes, your choices, scan results, backups,
and every file deleted or skipped:

- `wow-tools-YYYY-MM-DD.log` is readable.
- `events-YYYY-MM-DD.jsonl` is structured, one JSON object per line.

The format is described in [docs/events.md](docs/events.md).

## Windows and WSL together

The same folder works from both. Paths are stored in Windows form (`G:\Games\…`) and translated to
`/mnt/g/Games/…` automatically under WSL.

## Troubleshooting

- **"No WoW flavor folders were found"**: choose the `World of Warcraft` folder itself, not `_retail_`.
- **"Refusing to scan"**: that flavor has no addons installed. Nothing is proposed, on purpose.
- **Files come back after cleaning**: WoW was running. Close it and clean again.
- **Python not found on Windows**: install Python 3.10+ from python.org and tick "Add to PATH".

## For developers

See [docs/architecture.md](docs/architecture.md), [docs/adding-a-tool.md](docs/adding-a-tool.md),
[docs/vendoring.md](docs/vendoring.md), [docs/releasing.md](docs/releasing.md) and
[docs/events.md](docs/events.md). Run the tests with `python3 -m unittest discover -s tests -t .`.
````

- [ ] **Step 5: Write the developer docs and CLAUDE.md**

`docs/architecture.md`:
```markdown
# Architecture

## Layers

    wowtools/__main__.py   Python check + vendor/ on sys.path, then suite.run()
    wowtools/suite.py      dispatcher: tools, `update`, tool picker, session events, auto-update
    wowtools/core/         UI-free framework shared by every tool (never imports textual)
    wowtools/ui/           shared Textual pieces: theme, branding, Ka0sApp, setup/flavor/picker screens
    wowtools/tools/<tool>/ one package per tool: logic modules (UI-free) + cli.py + Textual screens

Tool logic is pure Python over plain dataclasses, so the CLI, the TUI and the tests all drive the
same functions. Front ends stay thin.

## Core modules

| Module | Job |
|---|---|
| `bootstrap` | `REPO_ROOT`, `VENDOR_DIR`, Python ≥ 3.10 check, `add_vendor_path()` |
| `paths` | WSL detection; `to_native()` / `to_stored()` translate `G:\X` ⇄ `/mnt/g/X` |
| `config` | `wow-tools.cfg` INI: `[general]` + one section per tool; typed accessors; `config.changed` events |
| `events` | Registry of event names with fixed levels; JSONL + text sinks; `log_event()`; `capture_events()` for tests |
| `install` | `WowInstall` → `Flavor` → `Account` → `Character`; install auto-detection |
| `backup` | Zip + `manifest.json`, verified before it is moved into place |
| `process` | Best-effort "is WoW running?" (tasklist / tasklist.exe / /proc) |
| `updater` | GitHub Releases check (24 h throttle), `UpdateCheck` thread, git fast-forward or zip replace with rollback |

## Config schema

`[general]`: `wow_path`, `backup_dir`, `last_flavor`, `check_for_updates`, `auto_update`,
`last_update_check`, `latest_seen_version`, `log_level`, `log_retention_days`.
Each tool owns one section (`[wtf_cleaner]`). Paths are stored in Windows form when they point at a
Windows drive. Unknown keys are preserved, and bad values fall back to defaults.

## WTF Cleaner data flow

    scan(flavor) → ScanResult(installed, enabled, groups[SVGroup[SVFile]])
    evaluate(scan, Criteria) → Proposal(items[ProposalItem(group, files, reasons)])
    TUI/CLI selection → execute(items, flavor, dry_run, backup, backup_dir) → CleanResult(outcomes)

`execute` guards every path (it must resolve inside `<flavor>/WTF/Account/**/SavedVariables`), re-checks
size and mtime, writes and verifies the backup, and only then deletes.

## UI

`Ka0sApp` registers the `ka0s` theme, starts the background update check, handles `u`, and exposes
the `after_mount()` hook. Every screen shows a `Header`, the `BrandBar` and a `Footer`. Long-running work
(scan, clean) runs in thread workers and reports back with `call_from_thread`.

## Testing

`python3 -m unittest discover -s tests -t .`. `tests/fixtures.py` builds a synthetic install in a temp
folder, and TUI tests use Textual's `App.run_test()` pilot. No test touches a real WoW folder or the network.
```

`docs/adding-a-tool.md`:
````markdown
# Adding a tool

This walks through adding the Screenshot Organizer (`screenshots`) as an example.

1. **Package.** Create `wowtools/tools/screenshots/` with:
   - `__init__.py`, which imports `events` so the tool's events register:
     `from wowtools.tools.screenshots import events as _events  # noqa: F401`
   - `events.py`:
     ```python
     from wowtools.core.events import EventSpec, register_events
     TOOL_NAME = "screenshots"
     EVENTS = {"shots.moved": EventSpec("info", "A screenshot was filed into a folder.")}
     register_events(TOOL_NAME, EVENTS)
     ```
   - UI-free logic modules (e.g. `organizer.py`) that take a `Flavor` and plain values.
   - `settings.py` for a `[screenshots]` config section. Follow `wtf_cleaner/settings.py`.
   - `cli.py` with `main(argv, *, cfg=None, stdout=None, stderr=None) -> int`. It opens the TUI when no
     CLI-mode flags are given.
   - `app.py` with `class ScreenshotsApp(Ka0sApp)`, which overrides `after_mount()` (not `on_mount`).
     Reuse `SetupScreen` for the WoW folder and `FlavorScreen` for the flavor, and put `Header()`,
     `BrandBar()` and `Footer()` on every screen.
2. **Register** it in `wowtools/tools/__init__.py`:
   `Tool("screenshots", "Screenshot Organizer", "Sort screenshots into folders.", "wowtools.tools.screenshots.cli")`.
3. **Wrappers**: copy `wtf-cleaner.cmd/.sh` to `screenshots.cmd/.sh` and change the tool name. Add both
   names to `MANAGED_FILES` in `core/updater.py` so zip updates replace them.
4. **Events**: run `python3 scripts/gen_event_docs.py` and commit `docs/events.md`.
5. **Tests**: add `tests/test_screenshots_*.py`. Use temp folders, `capture_events()` for logging assertions
   and `App.run_test()` for the TUI. Never touch a real install.
6. **Docs**: add a section to `README.md` and a row to its tools table.
````

`docs/vendoring.md`:
```markdown
# Vendored libraries

Third-party code lives in `vendor/` and is committed, so the tools run without pip or a virtualenv.
`wowtools/__main__.py` (and `tests/__init__.py`) put `vendor/` first on `sys.path`.

Rules:
- **Pure Python only.** The same folder must work on Windows, Linux and WSL. `scripts/update_vendor.py`
  fails if a `.so`, `.pyd`, `.dll` or `.dylib` is installed.
- **Pin everything**, including transitive dependencies, in `requirements.txt`. The script installs with
  `--no-deps`, so the list must be complete.
- Python floor is 3.10. Check each package's `Requires-Python`.

Updating or adding a library:
1. Edit `requirements.txt` (bump pins, or add the package *and* its dependencies. Find them with
   `pip install --dry-run --report - <pkg>` or by installing it into a scratch folder with `--target`).
2. Run `python3 scripts/update_vendor.py`.
3. Run the full test suite, then commit `requirements.txt` and `vendor/` together.
```

`docs/releasing.md`:
```markdown
# Releasing

The updater reads the latest **published, non-prerelease** GitHub Release of `tusharsaxena/wow-tools`,
and its tag must be `vX.Y.Z` matching `wowtools/__init__.py`. Zip installs download that tag's zipball,
and git installs fast-forward to the tag.

1. Make sure `main`/`master` is green: `python3 -m unittest discover -s tests -t .`
   and `python3 scripts/gen_event_docs.py --check`.
2. Bump `__version__` in `wowtools/__init__.py`, following semver.
3. Commit: `git commit -am "release: vX.Y.Z"`.
4. Tag and push: `git tag vX.Y.Z && git push origin HEAD --tags`.
5. Publish: `gh release create vX.Y.Z --title "Ka0s WoW Tools vX.Y.Z" --notes "..."`.
   The notes appear in the in-app update prompt.

Never re-use or move a tag. Git installs would fail to fast-forward.
```

`CLAUDE.md`:
```markdown
# wow-tools: notes for Claude

Out-of-game WoW companion tools (Ka0s branded). First tool: WTF Cleaner. Spec and plan: `docs/superpowers/`.

- Tests: `python3 -m unittest discover -s tests -t . -v`
- Run: `python3 -m wowtools [wtf-cleaner|update] [args]` (no args opens the tool menu)
- Rebuild vendored libs: `python3 scripts/update_vendor.py`. Event docs: `python3 scripts/gen_event_docs.py`

Conventions:
- Python 3.10 floor; `from __future__ import annotations` in every module; stdlib + `vendor/` only.
- `wowtools/core/*` and tool logic modules never import `textual`. Front ends are thin.
- Config paths go through `core/paths.py` (stored in Windows form); config lives in the repo root.
- Every log event is registered with a fixed level (`core/events.py` or `<tool>/events.py`); regenerate
  `docs/events.md` after changing any registry.
- Textual apps subclass `Ka0sApp` and override `after_mount()`, not `on_mount()`.
- Tests use `tests/fixtures.py` temp trees; never a real WoW install, never the network.
- Adding a tool: `docs/adding-a-tool.md`.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all OK, including `tests.test_docs`.

- [ ] **Step 7: Commit**

```bash
git add README.md CLAUDE.md docs/events.md docs/architecture.md docs/adding-a-tool.md docs/vendoring.md \
        docs/releasing.md scripts/gen_event_docs.py tests/test_docs.py
git commit -m "docs: user README, developer docs, generated event reference"
```

---

### Task 17: Verify end to end and publish v0.1.0

**Files:** none (verification and release)

- [ ] **Step 1: Run the full suite on Linux/WSL**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all OK.

- [ ] **Step 2: Run the suite with Windows Python (from WSL, if available)**

Run: `cmd.exe /c "cd /d D:\Profile\Users\Tushar\Documents\GIT\wow-tools && py -3 -m unittest discover -s tests -t ."`
Expected: all OK. POSIX-only tests are skipped. If `py` isn't installed on Windows, note that and skip this step.

- [ ] **Step 3: Read-only check against the real install**

Run: `python3 -m wowtools wtf-cleaner --flavor retail --wow-path "/mnt/g/Games/Blizzard/World of Warcraft"`
Expected: a proposal is printed and **nothing is changed**, because there's no `--clean`. Show the output to
the user. Do **not** run `--clean` against the real install. That's the user's call.

- [ ] **Step 4: Push and ask before releasing**

Run: `git push origin HEAD`
Then **ask the user** before creating the release (it's public and every install will see it):
`gh release create v0.1.0 --title "Ka0s WoW Tools v0.1.0" --notes "First release: shared framework and the WTF Cleaner."`
