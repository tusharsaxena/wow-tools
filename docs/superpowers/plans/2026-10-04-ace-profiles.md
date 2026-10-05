# Ace3 Profile Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Progress is checkpointed in `2026-10-04-ace-profiles.status.md` (same folder): read it first, resume at the
> first task not marked done, and update it (and commit it) after every task.

**Goal:** A fourth suite tool, Ace3 Profile Manager (`ace-profiles`). It finds every AceDB-3.0 database in a WoW
install's SavedVariables and shows its profiles and which characters use them. Users can delete, rename and copy
profiles, reassign characters and remove leftover characters, protected by a blacklist, backups, a journal and Undo.

**Architecture:** A stdlib Lua SavedVariables parser records byte spans (`luasv.py`). AceDB detection (`model.py`)
and a staged, byte-free operation model (`ops.py`) sit on top of it. Staged changes compile to span splices that
leave every other byte identical, are verified by re-parsing (`verify.py`) and are written atomically by
`editor.py`, behind a whole-WTF snapshot, a per-file original zip, a crash marker and a journal. Three Textual
modules plus a popups module follow the suite's two-pane look and feel. Shared helpers move into `core/`.

**Tech Stack:** Python 3.10+, stdlib (`re`, `hashlib`, `zipfile`, `json`), vendored Textual, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-04-ace-profiles-design.md` (read it first; section numbers below
refer to it).

## Global Constraints

- Python 3.10 floor; `from __future__ import annotations` first in every new module (`wowtools/`, `scripts/`,
  `tests/`); stdlib + `vendor/` only. Top-level `from wowtools... import` lines sorted by module name
  (`tests/test_structure.py`).
- `wowtools/core/*` and the tool's logic modules never import `textual`. Only `app.py`, `review_screen.py`,
  `popups.py`, `result_screen.py` in the tool do.
- The tool imports nothing from another tool (`wowtools.tools.wtf_cleaner`, `...interface_backup`,
  `...screenshot_organizer`). Code it needs from them moves to `core/` first (Task 1).
- Tool name `ace-profiles`; package `wowtools/tools/ace_profiles/`; title "Ace3 Profile Manager"; menu text
  "See and change which Ace3 profile each character uses."; config `config/ace-profiles.cfg`, section
  `[ace_profiles]`; event prefix `ace.`; tool root `<backup_dir or <WoW>/wow-tools>/ace-profiles/` holding
  `snapshots/snapshot-<short>-<YYYYMMDD-HHMMSS>.zip`, `edited/edited-<short>-<acct|all>-<stamp>.zip` and
  `edit-in-progress.json`; journals in `<WoW>/wow-tools/ace-profiles/journal/`.
- Settings defaults: `keep_snapshots` 2 (at least 1), `keep_journals` 10 (at least 1), `blacklist` empty.
- Never re-serialize a SavedVariables file: every change is a byte-span splice; every byte outside the edited spans
  stays identical. Only `profileKeys` entries, `profiles` entries, `namespaces[*].profiles` entries and LibDualSpec
  `namespaces["LibDualSpec-1.0"].char[*]` spec values may change.
- Apply and Undo refuse while WoW of the flavor runs (a check that cannot run: warn and allow). Dry run never writes
  anything.
- Never call `resolve()` per file; never follow a symlink or junction; skip SavedVariables folders under one.
- The literal `"wow-tools"` only via `core.journal.TOOLS_SUBDIR`; no function named `_remove`, `_discard`,
  `_safe_progress`, `safe_progress` or `remove_quietly` outside `core/fsutil.py`; `ConfirmScreen`/`ProgressScreen`
  defined only in `ui/dialogs.py`.
- Every log event registered in `ace_profiles/events.py` with a fixed level; `docs/events.md` regenerated
  (`python3 scripts/gen_event_docs.py`) whenever the registry changes.
- Tests: temp trees only (`tests/fixtures.py`), `tests.fixtures.TuiTestCase` + `settle` for TUI tests, never a real
  install, never the network.
- Commit after every task (message ends with the two attribution lines given in the session). Push the branch
  `feat/ace-profiles` after each milestone. Never merge without the user's go-ahead.
- Test commands: `python3 scripts/run_tests.py -k ace` for the tool, `python3 scripts/run_tests.py` for everything,
  `ruff check .` (if `ruff` is installed).

## Review Focus

1. **A file WoW rewrote between scan and Apply** (the user logged out of a character with the tool open): the
   SHA-256 recheck must skip that file, with "changed since the scan; rescan", and still apply the others. Test in
   Task 8.
2. **Byte-exact preservation of untouched content** (floats like `0.6000000000000001`, `\ddd` escapes, CRLF,
   UTF-8 names, a plain `*PerfDB` sharing the file): only the edited spans may differ. Test in Tasks 2 and 7 (a
   no-op compile is byte-identical; a one-key edit changes exactly one span).
3. **Composed staging** (copy A as B, then rename B to C, then delete A with target C): the compiled file must hold
   C as a byte copy of A's old value, no A, and every user of A on C. Test in Task 7.
4. **A failure in the middle of a multi-file Apply** (the third file's write raises): files already written are put
   back byte-identical from the originals, the journal records `rolled_back`, and Undo is then not offered for them.
   Test in Task 8.
5. **Undo after WoW saved the file again**: a file whose SHA-256 is no longer `sha_after` is skipped ("changed
   since") and never overwritten. Test in Task 9.

---

## Milestone 1: parsing, model, staging (Tasks 1–7), push after Task 7

### Task 1: shared core helpers (snapshot, lock probe, guard, atomic bytes write)

Move the WTF Cleaner's whole-WTF snapshot and SavedVariables safety helpers into `core/`, so the new tool can use
them without importing another tool. Behaviour, messages and file names of the WTF Cleaner stay exactly as they are.

**Files:**
- Create: `wowtools/core/snapshot.py`, `wowtools/core/svfiles.py`
- Modify: `wowtools/core/fsutil.py` (add `atomic_write_bytes`; `atomic_write_text` delegates)
- Modify: `wowtools/tools/wtf_cleaner/safety.py` (`wtf_files`, `take_snapshot`, `snapshot_path`, `prune_snapshots`
  become thin wrappers over `core/snapshot.py`)
- Modify: `wowtools/tools/wtf_cleaner/cleaner.py` (`_Guard`, `_probe_lock`, `recover_probe_leftovers`,
  `saved_variables_folders` delegate to `core/svfiles.py`, converting `SvFileError` to `CleanError` with the same
  message)
- Modify: `wowtools/tools/wtf_cleaner/scanner.py` (`LOCK_PROBE_SUFFIX` re-exported from `core/svfiles.py`)
- Test: `tests/test_core_snapshot.py`, `tests/test_core_svfiles.py`, `tests/test_fsutil.py` (add a class)

**Interfaces:**
- Produces:
  - `fsutil.atomic_write_bytes(path: Path, data: bytes) -> None` (same contract as `atomic_write_text`).
  - `snapshot.wtf_files(flavor, progress=None, stage="snapshot_list") -> list[Path]`
  - `snapshot.snapshot_path(folder: Path, prefix: str, flavor_short: str, now: datetime) -> Path`
    (= `free_name(folder, f"{prefix}-{short}-{now:%Y%m%d-%H%M%S}", ".zip")`)
  - `snapshot.take_snapshot(flavor, folder: Path, prefix: str, now: datetime, progress=None,
    must_hold: list[str] | None = None) -> Path` (raises `core.backup.BackupError`)
  - `snapshot.prune_snapshots(folder: Path, prefix: str, flavor_short: str, keep: int) -> list[Path]`
  - `svfiles.LOCK_PROBE_SUFFIX = ".wowtools-lockcheck"`, `class SvFileError(Exception)`,
    `class SvGuard(flavor)` with `.check(path, info: os.stat_result | None) -> None` (raises `SvFileError`),
    `svfiles.probe_lock(path) -> str | None` (raises `SvFileError` when the file can't be put back),
    `svfiles.recover_probe_leftovers(folders, on_recovered: Callable[[Path], None] | None = None) -> list[Path]`,
    `svfiles.saved_variables_folders(flavor, account: str | None = None) -> list[Path]`,
    `svfiles.lstat_or_none(path) -> os.stat_result | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_core_snapshot.py
"""core/snapshot.py: the whole-WTF snapshot shared by the WTF Cleaner and the Ace3 Profile Manager."""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core import snapshot
from wowtools.core.install import WowInstall

WHEN = datetime(2026, 10, 4, 12, 0, 0)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.flavor = WowInstall(build_wow_tree(self.tmp / "wow")).flavor("_retail_")

    def test_prefix_and_folder_are_parameters(self):
        out = snapshot.take_snapshot(self.flavor, self.tmp / "out" / "snapshots", "snapshot", WHEN)
        self.assertEqual(out, self.tmp / "out" / "snapshots" / "snapshot-retail-20261004-120000.zip")
        with zipfile.ZipFile(out) as zf:
            self.assertIn("WTF/Account/ACCT1/SavedVariables/Details.lua", zf.namelist())

    def test_second_snapshot_in_the_same_second_gets_a_suffix(self):
        folder = self.tmp / "s"
        first = snapshot.take_snapshot(self.flavor, folder, "snapshot", WHEN)
        second = snapshot.take_snapshot(self.flavor, folder, "snapshot", WHEN)
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.endswith("-2.zip"))

    def test_prune_keeps_newest_of_that_prefix_and_flavor_only(self):
        folder = self.tmp / "s"
        folder.mkdir()
        for name in ("snapshot-retail-20260101-000000.zip", "snapshot-retail-20260102-000000.zip",
                     "snapshot-retail-20260103-000000.zip", "snapshot-classic_era-20260101-000000.zip",
                     "backup-retail-20260101-000000.zip", "notes.txt"):
            (folder / name).write_bytes(b"x")
        removed = snapshot.prune_snapshots(folder, "snapshot", "retail", 2)
        self.assertEqual([p.name for p in removed], ["snapshot-retail-20260101-000000.zip"])
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["backup-retail-20260101-000000.zip", "notes.txt",
                          "snapshot-classic_era-20260101-000000.zip", "snapshot-retail-20260102-000000.zip",
                          "snapshot-retail-20260103-000000.zip"])

    def test_prune_keeps_at_least_one(self):
        folder = self.tmp / "s"
        folder.mkdir()
        (folder / "snapshot-retail-20260101-000000.zip").write_bytes(b"x")
        self.assertEqual(snapshot.prune_snapshots(folder, "snapshot", "retail", 0), [])
```

```python
# tests/test_core_svfiles.py
"""core/svfiles.py: the guard, lock probe and probe-leftover recovery shared by tools that change SavedVariables."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core import svfiles
from wowtools.core.install import WowInstall


class SvFilesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.flavor = WowInstall(build_wow_tree(self.tmp / "wow")).flavor("_retail_")
        self.sv = self.flavor.account_dir / "ACCT1" / "SavedVariables" / "Details.lua"

    def test_guard_accepts_a_saved_variables_file(self):
        svfiles.SvGuard(self.flavor).check(self.sv, svfiles.lstat_or_none(self.sv))

    def test_guard_refuses_outside_account_folder(self):
        outside = self.tmp / "elsewhere" / "SavedVariables" / "x.lua"
        outside.parent.mkdir(parents=True)
        outside.write_text("x", encoding="utf-8")
        with self.assertRaises(svfiles.SvFileError) as caught:
            svfiles.SvGuard(self.flavor).check(outside, None)
        self.assertIn("outside", str(caught.exception))

    def test_guard_refuses_a_file_not_directly_in_saved_variables(self):
        path = self.flavor.account_dir / "ACCT1" / "config-cache.wtf"
        with self.assertRaises(svfiles.SvFileError) as caught:
            svfiles.SvGuard(self.flavor).check(path, None)
        self.assertIn("SavedVariables", str(caught.exception))

    def test_probe_lock_puts_the_file_back(self):
        before = self.sv.read_bytes()
        self.assertIsNone(svfiles.probe_lock(self.sv))
        self.assertEqual(self.sv.read_bytes(), before)
        self.assertFalse(self.sv.with_name(self.sv.name + svfiles.LOCK_PROBE_SUFFIX).exists())

    def test_probe_lock_reports_a_locked_file(self):
        def refuse(src, dst):
            raise PermissionError(13, "in use")
        with patch("wowtools.core.svfiles.rename_no_replace", refuse):
            self.assertEqual(svfiles.probe_lock(self.sv), "in use")

    def test_recover_probe_leftovers_renames_back(self):
        aside = self.sv.with_name(self.sv.name + svfiles.LOCK_PROBE_SUFFIX)
        os.rename(self.sv, aside)
        seen = []
        recovered = svfiles.recover_probe_leftovers([self.sv.parent], on_recovered=seen.append)
        self.assertEqual(recovered, [self.sv])
        self.assertEqual(seen, [self.sv])
        self.assertTrue(self.sv.exists())

    def test_saved_variables_folders_one_account(self):
        folders = svfiles.saved_variables_folders(self.flavor, "acct2")
        self.assertEqual([f.relative_to(self.flavor.account_dir).as_posix() for f in folders],
                         ["ACCT2/SavedVariables", "ACCT2/Realm2/Chârb/SavedVariables"])
```

```python
# tests/test_fsutil.py — add this class (reuse the module's imports; add `from wowtools.core.fsutil import
# atomic_write_bytes` to them)
class AtomicWriteBytesTest(unittest.TestCase):
    def test_writes_exact_bytes_and_leaves_no_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.lua"
            path.write_bytes(b"old")
            atomic_write_bytes(path, b"\r\nX = {\r\n}\r\n\xc3\xa2")
            self.assertEqual(path.read_bytes(), b"\r\nX = {\r\n}\r\n\xc3\xa2")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.lua"])

    def test_failed_replace_keeps_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.lua"
            path.write_bytes(b"old")
            with patch("os.replace", side_effect=OSError("locked")), self.assertRaises(OSError):
                atomic_write_bytes(path, b"new")
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.lua"])
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 scripts/run_tests.py -k core_snapshot` then `-k core_svfiles` then `-k fsutil`
Expected: ImportError / AttributeError (modules and function missing).

- [ ] **Step 3: Implement**

`fsutil.atomic_write_bytes` is `atomic_write_text`'s body with `partial.open("wb")` and `handle.write(data)`.
`atomic_write_text(path, text)` becomes `atomic_write_bytes(path, text.encode("utf-8"))`.

`core/snapshot.py`: move the bodies of `wtf_files`, `take_snapshot`, `snapshot_path` and `prune_snapshots` from
`wtf_cleaner/safety.py`. The changes:
- `take_snapshot(flavor, folder, prefix, now, progress=None, must_hold=None)` writes to
  `snapshot_path(folder, prefix, flavor.short_name, now)`.
- `prune_snapshots(folder, prefix, flavor_short, keep)` matches
  `re.compile(rf"^{re.escape(prefix)}-(?P<flavor>.+?)-(?P<stamp>\d{{8}}-\d{{6}})(?:-(?P<n>\d+))?\.zip$")`.
- Keep `SnapshotProgress` and `LIST_REPORT_EVERY` here, and import them into `safety.py`.

The wrappers in `wtf_cleaner/safety.py` keep their old signatures:

```python
def take_snapshot(flavor, backup_dir, now, progress=None, must_hold=None):
    return core_snapshot.take_snapshot(flavor, backup_dir / SNAPSHOT_SUBDIR, "backup", now, progress, must_hold)

def snapshot_path(backup_dir, flavor_short, now):
    return core_snapshot.snapshot_path(backup_dir / SNAPSHOT_SUBDIR, "backup", flavor_short, now)

def prune_snapshots(backup_dir, flavor_short, keep):
    return core_snapshot.prune_snapshots(backup_dir / SNAPSHOT_SUBDIR, "backup", flavor_short, keep)
```

`wtf_files` is re-exported (`from wowtools.core.snapshot import wtf_files`). `SNAPSHOT_NAME` stays in `safety.py`,
because the cleaner's other code uses it.

`core/svfiles.py`: move `_Guard` (as `SvGuard`), `_lstat` (as `lstat_or_none`), `_probe_lock` (as `probe_lock`),
`recover_probe_leftovers` and `saved_variables_folders` from `wtf_cleaner/cleaner.py`.
- Raise `SvFileError` where they raised `CleanError`, with the same message text.
- The WTF-specific tail of the put-back message, " Nothing was deleted.", is added by the cleaner's wrapper.
- `recover_probe_leftovers` takes an `on_recovered` callback instead of logging `clean.probe_recovered` itself.

In `cleaner.py`, the wrappers are:

```python
class _Guard(SvGuard):
    def check(self, path, info):
        try:
            super().check(path, info)
        except SvFileError as exc:
            raise CleanError(str(exc)) from None

def _probe_lock(path):
    try:
        return probe_lock(path)
    except SvFileError as exc:
        raise CleanError(f"{exc} Nothing was deleted.") from exc.__cause__

def recover_probe_leftovers(folders, flavor):
    return core_recover(folders, on_recovered=lambda original: log_event(
        "clean.probe_recovered", flavor=flavor.folder, path=_relative(original, flavor)))
```

`_lstat = lstat_or_none` and `saved_variables_folders` are re-exported. If any existing test patches a moved name
at its old module path (for example `wowtools.tools.wtf_cleaner.safety.rename_no_replace` or
`...cleaner.rename_no_replace`), change only that patch target to the `core` module. Change no assertion.

- [ ] **Step 4: Run the new tests and the whole WTF Cleaner battery**

Run: `python3 scripts/run_tests.py -k core_` , `-k fsutil`, `-k safety`, `-k cleaner`, `-k wtf`, `-k no_replace`,
`-k structure`
Expected: all pass; no WTF Cleaner assertion changed.

- [ ] **Step 5: Commit**

```bash
git add wowtools/core/snapshot.py wowtools/core/svfiles.py wowtools/core/fsutil.py wowtools/tools/wtf_cleaner tests
git commit -m "refactor: move WTF snapshot, lock probe and SV guard into core"
```

---

### Task 2: `luasv.py`: SavedVariables parser with byte spans, splice, string codec

**Files:**
- Create: `wowtools/tools/ace_profiles/__init__.py` (empty for now except the future import and a docstring; Task 4
  adds `from wowtools.tools.ace_profiles import events  # noqa: F401`)
- Create: `wowtools/tools/ace_profiles/luasv.py`
- Test: `tests/test_ace_luasv.py`

**Interfaces:**
- Produces (all in `luasv`):
  - `class LuaParseError(ValueError)` with `.offset: int`.
  - `@dataclass Scalar(start: int, end: int, value: str | int | float | bool | None | RawNumber)`;
    `@dataclass(frozen=True) RawNumber(text: str)` for numbers Python can't read (`1.#INF`, `-nan(ind)`).
  - `@dataclass Opaque(start: int, end: int)`: a table that was not descended (`start` = `{`, `end` = after `}`).
  - `@dataclass Field(key, key_span: tuple[int, int] | None, value: Value, entry_start: int, entry_end: int,
    remove_span: tuple[int, int])`. `key` is a str, int, float or bool; positional fields get int keys 1, 2, …
    and `key_span=None`.
  - `@dataclass Table(start: int, end: int, fields: list[Field])` with `.close` (= `end - 1`, the `}` offset),
    `.get(key) -> Field | None` (last field with that key), `.keys() -> list`.
  - `Value = Table | Opaque | Scalar`.
  - `@dataclass Assignment(name: str, start: int, end: int, value: Value)` (`start` = the name, `end` = after the
    value).
  - `@dataclass Chunk(assignments: list[Assignment])` with `.get(name) -> Assignment | None`.
  - `parse(data: bytes, descend: Callable[[tuple], bool] = lambda path: True) -> Chunk`. `path` is
    `(sv_name, key1, key2, …)`; a table value whose path `descend` rejects becomes `Opaque`.
  - `decode_string(raw: bytes) -> str` (raw = the literal including quotes).
  - `encode_string(text: str) -> bytes`.
  - `is_blank_table(data: bytes, value: Opaque | Table) -> bool` (only whitespace or comments between the braces).
  - `newline_of(data: bytes) -> bytes` (`b"\r\n"` if the first line ending is CRLF, else `b"\n"`).
  - `line_start(data: bytes, offset: int) -> int` (start of the line holding `offset`).
  - `splice(data: bytes, edits: list[tuple[int, int, bytes]]) -> bytes`. Raises `ValueError` on overlapping edits.
    Zero-length inserts at the end of a removed span are allowed.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ace_luasv.py
"""luasv: the SavedVariables reader with byte spans (spec §5.1)."""
from __future__ import annotations

import time
import unittest

from wowtools.tools.ace_profiles import luasv
from wowtools.tools.ace_profiles.luasv import LuaParseError, Opaque, Scalar, Table

CRLF_FILE = (b'\r\nKickCDDB = {\r\n["profileKeys"] = {\r\n["Ka\xc3\xa2los - Mug\'thol"] = "Default",\r\n'
             b'["Alt - Khaz Modan"] = "Default",\r\n},\r\n["profiles"] = {\r\n["Default"] = {\r\n'
             b'["scale"] = 0.6000000000000001,\r\n["tiny"] = 8e-05,\r\n["text"] = "a\\"b\\\\c\\n\\000",\r\n'
             b'[114052] = true,\r\n["arr"] = {\r\n"TOP",\r\nnil,\r\n"TOP",\r\n},\r\n},\r\n["Empty"] = {\r\n},\r\n},\r\n'
             b'}\r\nKickCDPerfDB = {\r\n["runs"] = 3,\r\n}\r\n')


class ParseTest(unittest.TestCase):
    def test_top_level_assignments(self):
        chunk = luasv.parse(CRLF_FILE)
        self.assertEqual([a.name for a in chunk.assignments], ["KickCDDB", "KickCDPerfDB"])
        db = chunk.get("KickCDDB")
        self.assertEqual(CRLF_FILE[db.start:db.start + 8], b"KickCDDB")
        self.assertEqual(CRLF_FILE[db.end - 1:db.end], b"}")

    def test_keys_values_and_spans(self):
        db = luasv.parse(CRLF_FILE).get("KickCDDB").value
        keys = db.get("profileKeys").value
        self.assertIsInstance(keys, Table)
        self.assertEqual(keys.keys(), ["Kaâlos - Mug'thol", "Alt - Khaz Modan"])
        field = keys.get("Alt - Khaz Modan")
        self.assertEqual(CRLF_FILE[field.key_span[0]:field.key_span[1]], b'["Alt - Khaz Modan"]')
        self.assertEqual(CRLF_FILE[field.value.start:field.value.end], b'"Default"')
        self.assertEqual(field.value.value, "Default")
        start, end = field.remove_span
        self.assertEqual(CRLF_FILE[start:end], b'["Alt - Khaz Modan"] = "Default",\r\n')

    def test_scalars(self):
        default = luasv.parse(CRLF_FILE).get("KickCDDB").value.get("profiles").value.get("Default").value
        self.assertEqual(default.get("scale").value.value, 0.6000000000000001)
        self.assertEqual(default.get("tiny").value.value, 8e-05)
        self.assertEqual(default.get("text").value.value, 'a"b\\c\n\x00')
        self.assertIs(default.get(114052).value.value, True)
        arr = default.get("arr").value
        self.assertEqual([f.key for f in arr.fields], [1, 2, 3])
        self.assertEqual([f.value.value for f in arr.fields], ["TOP", None, "TOP"])
        self.assertIsNone(arr.fields[0].key_span)

    def test_selective_depth_makes_opaque_values(self):
        def descend(path):
            return len(path) <= 2
        profiles = luasv.parse(CRLF_FILE, descend).get("KickCDDB").value.get("profiles").value
        default = profiles.get("Default").value
        self.assertIsInstance(default, Opaque)
        self.assertEqual(CRLF_FILE[default.start:default.start + 1], b"{")
        self.assertEqual(CRLF_FILE[default.end - 1:default.end], b"}")
        self.assertTrue(luasv.is_blank_table(CRLF_FILE, profiles.get("Empty").value))
        self.assertFalse(luasv.is_blank_table(CRLF_FILE, default))

    def test_opaque_skip_ignores_braces_in_strings_and_comments(self):
        data = b'X = {\n["a"] = {\n["s"] = "}{\\"}",\n-- }\n--[[ } ]]\n["t"] = \'}\',\n},\n["b"] = 1,\n}\n'
        x = luasv.parse(data, lambda path: len(path) == 1).get("X").value
        self.assertEqual(x.keys(), ["a", "b"])
        self.assertEqual(x.get("b").value.value, 1)

    def test_name_keys_semicolons_comments_and_single_quotes(self):
        data = b"-- header\nX = { a = 1; ['b'] = 'q\\'s', [-2] = -3.5e2, c = 0x1F, d = 1.#INF } -- tail\n"
        x = luasv.parse(data).get("X").value
        self.assertEqual(x.keys(), ["a", "b", -2, "c", "d"])
        self.assertEqual(x.get("b").value.value, "q's")
        self.assertEqual(x.get(-2).value.value, -350.0)
        self.assertEqual(x.get("c").value.value, 31)
        self.assertEqual(x.get("d").value.value, luasv.RawNumber("1.#INF"))

    def test_decimal_and_hex_escapes_and_utf8(self):
        self.assertEqual(luasv.decode_string(b'"\\104\\x69 \\195\\162"'), "hi â")
        self.assertEqual(luasv.decode_string(b'"Tr\xc3\xa2xex"'), "Trâxex")

    def test_invalid_utf8_round_trips(self):
        text = luasv.decode_string(b'"\xff\xfe"')
        self.assertEqual(luasv.encode_string(text), b'"\xff\xfe"')

    def test_errors_have_offsets(self):
        for bad in (b"X = {", b"X = {[1 = 2}", b'X = "open', b"X = {} Y", b"= 1", b"X = {a 1}"):
            with self.subTest(bad=bad), self.assertRaises(LuaParseError) as caught:
                luasv.parse(bad)
            self.assertGreaterEqual(caught.exception.offset, 0)

    def test_remove_span_covers_indented_line(self):
        data = b"X = {\n    [\"a\"] = 1,\n    [\"b\"] = 2,\n}\n"
        field = luasv.parse(data).get("X").value.get("a")
        start, end = field.remove_span
        self.assertEqual(data[start:end], b'    ["a"] = 1,\n')

    def test_remove_span_of_entry_sharing_a_line(self):
        data = b'X = { ["a"] = 1, ["b"] = 2 }\n'
        field = luasv.parse(data).get("X").value.get("a")
        start, end = field.remove_span
        self.assertEqual(data[start:end], b'["a"] = 1,')


class CodecTest(unittest.TestCase):
    def test_encode_escapes(self):
        self.assertEqual(luasv.encode_string('a"b\\c\nd\re\x01'), b'"a\\"b\\\\c\\nd\\re\\001"')
        self.assertEqual(luasv.encode_string("Kaâlos - Mug'thol"), b'"Ka\xc3\xa2los - Mug\'thol"')

    def test_round_trip(self):
        for text in ("", "Default", 'x"y', "tab\tnew\nline", "\x00\x7f", "Ishtâr - Khaz Modan"):
            with self.subTest(text=text):
                self.assertEqual(luasv.decode_string(luasv.encode_string(text)), text)


class SpliceTest(unittest.TestCase):
    def test_no_edits_is_identity(self):
        self.assertEqual(luasv.splice(CRLF_FILE, []), CRLF_FILE)

    def test_replace_remove_insert(self):
        data = b"0123456789"
        self.assertEqual(luasv.splice(data, [(1, 3, b"AB"), (5, 7, b""), (9, 9, b"!")]), b"0AB3478!9")

    def test_insert_at_end_of_removed_span(self):
        self.assertEqual(luasv.splice(b"abcdef", [(1, 3, b""), (3, 3, b"X")]), b"aXdef")

    def test_overlap_is_refused(self):
        with self.assertRaises(ValueError):
            luasv.splice(b"abcdef", [(1, 4, b""), (3, 5, b"")])

    def test_newline_and_line_start(self):
        self.assertEqual(luasv.newline_of(CRLF_FILE), b"\r\n")
        self.assertEqual(luasv.newline_of(b"X = {\n}\n"), b"\n")
        data = b"ab\ncd"
        self.assertEqual(luasv.line_start(data, 4), 3)
        self.assertEqual(luasv.line_start(data, 1), 0)


class SpeedTest(unittest.TestCase):
    def test_large_file_with_selective_depth_is_fast(self):
        profile = b'["x"] = {\n' + b''.join(b'["k%d"] = {\n["v"] = "s}",\n[1] = 0.5,\n},\n' % i
                                         for i in range(400)) + b'},\n'
        body = b"".join(b'["P%d"] = {\n%s},\n' % (i, profile) for i in range(250))
        data = b"BigDB = {\n[\"profileKeys\"] = {\n[\"A - B\"] = \"P1\",\n},\n[\"profiles\"] = {\n" + body + b"},\n}\n"
        self.assertGreater(len(data), 3_000_000)

        def descend(path):
            return len(path) <= 2
        started = time.perf_counter()
        chunk = luasv.parse(data, descend)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(chunk.get("BigDB").value.get("profiles").value.fields), 250)
        self.assertLess(elapsed, 5.0)
```

- [ ] **Step 2: Run to see it fail**

Run: `python3 scripts/run_tests.py -k ace_luasv`
Expected: ImportError (`luasv` missing).

- [ ] **Step 3: Implement `luasv.py`**

```python
"""Read WoW SavedVariables files (Lua) with byte spans, and splice edits into them (spec §5.1). UI-free.

WoW writes SavedVariables as `Name = value` assignments: tables, strings, numbers, booleans and nil, usually CRLF and
unindented. This reader works on the raw bytes and records where every key and value starts and ends, so a caller
can change a few exact spans and leave every other byte as it was. Nothing here ever re-serializes a file.

parse() only builds the tables its `descend(path)` accepts; any other table is skipped by a fast scan that finds
its closing brace (strings, comments and nested braces are honoured) and becomes an Opaque value.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field as dc_field

_WS = re.compile(rb"[ \t\r\n\f\v]*")
_LONG_COMMENT = re.compile(rb"--\[(=*)\[.*?\]\1\]", re.S)
_NAME = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")
_STRING = re.compile(rb'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', re.S)
_NUMBER = re.compile(rb"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?(?:#[A-Za-z]+\d*)?)"
                     rb"|-?(?:inf|nan)(?:\([a-z]*\))?", re.I)
_INT = re.compile(rb"-?\d+")
_SKIP = re.compile(rb'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|--\[(=*)\[.*?\]\1\]|--[^\n]*|[{}]', re.S)
_ESCAPE = re.compile(rb"\\(?:(\d{1,3})|x([0-9a-fA-F]{2})|(\r\n|\n\r|\n|\r)|z\s*|(.))", re.S)
_SIMPLE_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"a": b"\a", b"b": b"\b", b"f": b"\f", b"v": b"\v",
                   b"\\": b"\\", b'"': b'"', b"'": b"'"}
_LINE_REST = re.compile(rb"[ \t]*(?:\r\n|\n|\r)")
_KEYWORDS = {b"true": True, b"false": False, b"nil": None}


class LuaParseError(ValueError):
    def __init__(self, offset: int, message: str) -> None:
        super().__init__(f"{message} at byte {offset}")
        self.offset = offset


@dataclass(frozen=True)
class RawNumber:
    """A number Python can't read as int or float (1.#INF, -nan(ind)): kept as its text."""
    text: str


@dataclass
class Scalar:
    start: int
    end: int
    value: str | int | float | bool | RawNumber | None


@dataclass
class Opaque:
    """A table that was not descended into: only its extent is known."""
    start: int
    end: int


@dataclass
class Field:
    key: object
    key_span: tuple[int, int] | None
    value: Table | Opaque | Scalar
    entry_start: int
    entry_end: int
    remove_span: tuple[int, int]


@dataclass
class Table:
    start: int
    end: int
    fields: list[Field] = dc_field(default_factory=list)

    @property
    def close(self) -> int:
        return self.end - 1

    def get(self, key: object) -> Field | None:
        found = None
        for item in self.fields:
            if item.key == key and type(item.key) is type(key):
                found = item
        return found

    def keys(self) -> list:
        return [item.key for item in self.fields]


Value = Table | Opaque | Scalar


@dataclass
class Assignment:
    name: str
    start: int
    end: int
    value: Value


@dataclass
class Chunk:
    assignments: list[Assignment] = dc_field(default_factory=list)

    def get(self, name: str) -> Assignment | None:
        for item in self.assignments:
            if item.name == name:
                return item
        return None


def decode_string(raw: bytes) -> str:
    """The text of a Lua string literal (quotes included). Bytes that aren't UTF-8 survive as surrogates."""
    body = raw[1:-1]

    def one(match: re.Match) -> bytes:
        decimal, hexa, newline, other = match.groups()
        if decimal is not None:
            return bytes([int(decimal) & 0xFF])
        if hexa is not None:
            return bytes([int(hexa, 16)])
        if newline is not None:
            return b"\n"
        if other is None:  # \z: skips the following whitespace
            return b""
        return _SIMPLE_ESCAPES.get(other, other)

    return _ESCAPE.sub(one, body).decode("utf-8", "surrogateescape")


def encode_string(text: str) -> bytes:
    """A double-quoted Lua string literal for text: `\\`, `"`, CR, LF and other control bytes escaped."""
    out = bytearray(b'"')
    for byte in text.encode("utf-8", "surrogateescape"):
        if byte == 0x5C:
            out += b"\\\\"
        elif byte == 0x22:
            out += b'\\"'
        elif byte == 0x0A:
            out += b"\\n"
        elif byte == 0x0D:
            out += b"\\r"
        elif byte < 0x20 or byte == 0x7F:
            out += b"\\%03d" % byte
        else:
            out.append(byte)
    out += b'"'
    return bytes(out)


def newline_of(data: bytes) -> bytes:
    index = data.find(b"\n")
    return b"\r\n" if index > 0 and data[index - 1:index] == b"\r" else b"\n"


def line_start(data: bytes, offset: int) -> int:
    return data.rfind(b"\n", 0, offset) + 1


def is_blank_table(data: bytes, value: Table | Opaque) -> bool:
    inner = data[value.start + 1:value.end - 1]
    pos = 0
    while True:
        pos = _WS.match(inner, pos).end()
        if inner.startswith(b"--", pos):
            long = _LONG_COMMENT.match(inner, pos)
            if long:
                pos = long.end()
                continue
            newline = inner.find(b"\n", pos)
            pos = len(inner) if newline < 0 else newline + 1
            continue
        return pos == len(inner)


def splice(data: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    """Apply (start, end, replacement) edits. They must not overlap; an insert (start == end) may sit at the end of
    another edit's span."""
    ordered = sorted(edits, key=lambda e: (e[0], e[1]))
    for (s1, e1, _), (s2, e2, _) in zip(ordered, ordered[1:]):
        if s2 < e1:
            raise ValueError(f"overlapping edits at {s1}-{e1} and {s2}-{e2}")
    out = []
    pos = 0
    for start, end, replacement in ordered:
        out.append(data[pos:start])
        out.append(replacement)
        pos = end
    out.append(data[pos:])
    return b"".join(out)


class _Parser:
    def __init__(self, data: bytes, descend: Callable[[tuple], bool]) -> None:
        self.data = data
        self.descend = descend
        self.size = len(data)

    def skip(self, pos: int) -> int:
        data = self.data
        while True:
            pos = _WS.match(data, pos).end()
            if data.startswith(b"--", pos):
                long = _LONG_COMMENT.match(data, pos)
                if long:
                    pos = long.end()
                    continue
                newline = data.find(b"\n", pos)
                pos = self.size if newline < 0 else newline + 1
                continue
            return pos

    def expect(self, pos: int, token: bytes) -> int:
        pos = self.skip(pos)
        if not self.data.startswith(token, pos):
            raise LuaParseError(pos, f"expected {token.decode()!r}")
        return pos + len(token)

    def chunk(self) -> Chunk:
        chunk = Chunk()
        pos = self.skip(0)
        while pos < self.size:
            if self.data[pos:pos + 1] == b";":
                pos = self.skip(pos + 1)
                continue
            name = _NAME.match(self.data, pos)
            if not name:
                raise LuaParseError(pos, "expected a variable name")
            text = name.group().decode("ascii")
            after = self.expect(name.end(), b"=")
            value, end = self.value(self.skip(after), (text,))
            chunk.assignments.append(Assignment(text, pos, end, value))
            pos = self.skip(end)
        return chunk

    def value(self, pos: int, path: tuple) -> tuple[Value, int]:
        data = self.data
        if pos >= self.size:
            raise LuaParseError(pos, "expected a value")
        head = data[pos:pos + 1]
        if head == b"{":
            if self.descend(path):
                return self.table(pos, path)
            end = self.skip_table(pos)
            return Opaque(pos, end), end
        if head in (b'"', b"'"):
            match = _STRING.match(data, pos)
            if not match:
                raise LuaParseError(pos, "unterminated string")
            return Scalar(pos, match.end(), decode_string(match.group())), match.end()
        number = _NUMBER.match(data, pos)
        if number and number.end() > pos:
            return Scalar(pos, number.end(), _number(number.group())), number.end()
        name = _NAME.match(data, pos)
        if name and name.group() in _KEYWORDS:
            return Scalar(pos, name.end(), _KEYWORDS[name.group()]), name.end()
        raise LuaParseError(pos, "expected a value")

    def skip_table(self, pos: int) -> int:
        depth = 0
        for match in _SKIP.finditer(self.data, pos):
            token = match.group()
            if token == b"{":
                depth += 1
            elif token == b"}":
                depth -= 1
                if depth == 0:
                    return match.end()
        raise LuaParseError(pos, "unclosed table")

    def table(self, pos: int, path: tuple) -> tuple[Table, int]:
        data = self.data
        table = Table(pos, -1)
        index = 1
        pos += 1
        while True:
            pos = self.skip(pos)
            if pos >= self.size:
                raise LuaParseError(table.start, "unclosed table")
            if data[pos:pos + 1] == b"}":
                table.end = pos + 1
                return table, pos + 1
            entry_start = pos
            if data[pos:pos + 1] == b"[" and data[pos + 1:pos + 2] not in (b"[", b"="):
                key_value, after = self.value(self.skip(pos + 1), path)
                if not isinstance(key_value, Scalar) or key_value.value is None:
                    raise LuaParseError(pos, "bad table key")
                after = self.expect(after, b"]")
                key, key_span = key_value.value, (entry_start, after)
                pos = self.skip(self.expect(after, b"="))
            else:
                name = _NAME.match(data, pos)
                after_name = self.skip(name.end()) if name else pos
                if name and name.group() not in _KEYWORDS and data[after_name:after_name + 1] == b"=" \
                        and data[after_name + 1:after_name + 2] != b"=":
                    key, key_span = name.group().decode("ascii"), (entry_start, name.end())
                    pos = self.skip(after_name + 1)
                else:
                    key, key_span = index, None
                    index += 1
            value, end = self.value(pos, path + (key,))
            pos = self.skip(end)
            separator = data[pos:pos + 1]
            if separator in (b",", b";"):
                pos += 1
            elif separator != b"}":
                raise LuaParseError(pos, "expected ',' or '}'")
            entry_end = pos
            remove_start, remove_end = entry_start, entry_end
            rest = _LINE_REST.match(data, entry_end)
            line = line_start(data, entry_start)
            if rest and not data[line:entry_start].strip(b" \t"):
                remove_start, remove_end = line, rest.end()
            table.fields.append(Field(key, key_span, value, entry_start, entry_end, (remove_start, remove_end)))


def _number(text: bytes) -> int | float | RawNumber:
    if _INT.fullmatch(text):
        return int(text)
    try:
        if text.lower().startswith((b"0x", b"-0x")):
            return int(text, 16)
        return float(text)
    except ValueError:
        return RawNumber(text.decode("ascii", "replace"))


def parse(data: bytes, descend: Callable[[tuple], bool] = lambda path: True) -> Chunk:
    """Parse a SavedVariables file. Raises LuaParseError (with the byte offset) on anything that isn't one."""
    return _Parser(data, descend).chunk()
```

Notes for the implementer:
- `Table.get` compares the key type as well, so `True` doesn't match `1`. That is why it checks `type(item.key)`.
- `remove_span` covers the whole line, including indentation and the line ending, only when the entry is alone on
  its line. Otherwise it is exactly `entry_start..entry_end`.
- If a test exposes a regex corner case (for example `-` before a name), fix it in the regex, not by special-casing
  the test.

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_luasv`
Expected: all pass, and SpeedTest well under 5 s.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools/ace_profiles tests/test_ace_luasv.py
git commit -m "feat(ace-profiles): SavedVariables parser with byte spans and splice"
```

---

### Task 3: `model.py`: find AceDB databases in a parsed file

**Files:**
- Create: `wowtools/tools/ace_profiles/model.py`
- Test: `tests/test_ace_model.py`

**Interfaces:**
- Consumes: `luasv.parse`, `Chunk`, `Table`, `Opaque`, `Scalar`, `Field`, `is_blank_table`.
- Produces (all in `model`):
  - `LDS = "LibDualSpec-1.0"`, `DEFAULT = "Default"`.
  - `ace_descend(path: tuple) -> bool` (the `descend` predicate for `luasv.parse`).
  - `has_profile_keys(data: bytes) -> bool` (the byte pre-filter: `b"profileKeys" in data`).
  - `split_char_key(key: str) -> tuple[str, str] | None` (`"Name - Realm"` → `("Name", "Realm")`, split on the
    first `" - "`).
  - `@dataclass ProfileEntry(name: str, field: Field, empty: bool, size: int)`.
  - `@dataclass NamespaceProfiles(name: str, table: Table, entries: dict[str, Field])`.
  - `@dataclass LdsChar(char: str, enabled: bool, specs: dict[int, Field])` (spec index → the field whose
    `value` is the profile-name `Scalar`).
  - `@dataclass AceDb(sv_name: str, keys_table: Table, profile_keys: dict[str, str], key_fields: dict[str, Field],
    profiles_table: Table | None, profiles: dict[str, ProfileEntry], namespaces: dict[str, NamespaceProfiles],
    lds: dict[str, LdsChar])` with:
    - `users(name) -> list[str]` (characters whose `profile_keys` value is `name`, in file order);
    - `profile_names() -> list[str]` (profiles in file order, then names that are only referenced, sorted);
    - `missing(name) -> bool` (referenced but no entry);
    - `lds_enabled(char) -> bool`.
  - `find_dbs(chunk: Chunk, data: bytes) -> tuple[list[AceDb], list[str]]` (databases, notes about look-alikes
    that were rejected).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ace_model.py
"""model: which top-level SavedVariables are AceDB databases, and what they hold (spec §2, §5.2)."""
from __future__ import annotations

import unittest

from wowtools.tools.ace_profiles import luasv, model

NL = b"\r\n"


def lua(*lines: str) -> bytes:
    return NL + NL.join(line.encode("utf-8") for line in lines) + NL


ELV = lua(
    'ElvDB = {',
    '["profileKeys"] = {', '["Kaelys - Mug\'thol"] = "Default",', '["Alt - Khaz Modan"] = "Default",', '},',
    '["profiles"] = {', '["Default"] = {', '["scale"] = 1,', '},', '["Old"] = {', '},', '},',
    '["namespaces"] = {',
    '["Bags"] = {', '["profiles"] = {', '["Default"] = {', '["x"] = 1,', '},', '["Old"] = {', '},', '},', '},',
    '["LibDualSpec-1.0"] = {', '["char"] = {',
    '["Kaelys - Mug\'thol"] = {', '["enabled"] = true,', '[1] = "Default",', '[2] = "Old",', '},',
    '},', '},',
    '},',
    '["global"] = {', '["schemaVersion"] = 3,', '},',
    '}',
    'ElvPrivateDB = {',
    '["profileKeys"] = {', '["Kaelys - Mug\'thol"] = "Kaelys - Mug\'thol",', '},',
    '["profiles"] = {', '["Kaelys - Mug\'thol"] = {', '["a"] = 1,', '},', '},',
    '}',
    'ElvPerfDB = {', '["runs"] = 1,', '}',
    'Memento = {', '["profileKeys"] = {', '["Player-3725-0A"] = {', '},', '},', '}',
    'HidingBar = {', '["profileKeys"] = {', '["A - B"] = "x",', '},', '["profiles"] = {', '"one",', '},', '}',
    'Stock = {', '["profileKeys"] = {', '["A - B"] = "Gone",', '},', '}',
)


def dbs(data: bytes):
    return model.find_dbs(luasv.parse(data, model.ace_descend), data)


class FindDbsTest(unittest.TestCase):
    def test_finds_only_acedb_databases(self):
        found, notes = dbs(ELV)
        self.assertEqual([db.sv_name for db in found], ["ElvDB", "ElvPrivateDB", "Stock"])
        self.assertEqual(len(notes), 2)
        self.assertTrue(any("Memento" in n for n in notes))
        self.assertTrue(any("HidingBar" in n for n in notes))

    def test_mapping_profiles_users(self):
        elv = dbs(ELV)[0][0]
        self.assertEqual(elv.profile_keys, {"Kaelys - Mug'thol": "Default", "Alt - Khaz Modan": "Default"})
        self.assertEqual(list(elv.profiles), ["Default", "Old"])
        self.assertEqual(elv.users("Default"), ["Kaelys - Mug'thol", "Alt - Khaz Modan"])
        self.assertEqual(elv.users("Old"), [])
        self.assertFalse(elv.profiles["Default"].empty)
        self.assertTrue(elv.profiles["Old"].empty)

    def test_namespaces_and_libdualspec(self):
        elv = dbs(ELV)[0][0]
        self.assertEqual(set(elv.namespaces), {"Bags"})  # LibDualSpec has no profiles table
        self.assertEqual(list(elv.namespaces["Bags"].entries), ["Default", "Old"])
        lds = elv.lds["Kaelys - Mug'thol"]
        self.assertTrue(lds.enabled)
        self.assertEqual({i: f.value.value for i, f in lds.specs.items()}, {1: "Default", 2: "Old"})
        self.assertTrue(elv.lds_enabled("Kaelys - Mug'thol"))
        self.assertFalse(elv.lds_enabled("Alt - Khaz Modan"))

    def test_missing_profile(self):
        stock = dbs(ELV)[0][2]
        self.assertIsNone(stock.profiles_table)
        self.assertTrue(stock.missing("Gone"))
        self.assertEqual(stock.profile_names(), ["Gone"])

    def test_profile_names_order(self):
        data = lua('X = {', '["profileKeys"] = {', '["A - R"] = "Zed",', '["B - R"] = "Beta",', '},',
                   '["profiles"] = {', '["Gamma"] = {', '},', '["Beta"] = {', '},', '},', '}')
        self.assertEqual(dbs(data)[0][0].profile_names(), ["Gamma", "Beta", "Zed"])

    def test_empty_profile_keys_is_still_acedb(self):
        data = lua('X = {', '["profileKeys"] = {', '},', '["profiles"] = {', '["Default"] = {', '},', '},', '}')
        found, _ = dbs(data)
        self.assertEqual([db.sv_name for db in found], ["X"])

    def test_global_is_never_descended(self):
        descended = []

        def spy(path):
            ok = model.ace_descend(path)
            if ok:
                descended.append(path)
            return ok
        luasv.parse(ELV, spy)
        self.assertFalse(any("global" in path[1:2] for path in descended))
        self.assertIn(("ElvDB", "namespaces", "LibDualSpec-1.0", "char", "Kaelys - Mug'thol"), descended)

    def test_split_char_key(self):
        self.assertEqual(model.split_char_key("Kaelys - Mug'thol"), ("Kaelys", "Mug'thol"))
        self.assertEqual(model.split_char_key("X - Azjol-Nerub"), ("X", "Azjol-Nerub"))
        self.assertEqual(model.split_char_key("A - Khaz - Modan"), ("A", "Khaz - Modan"))
        self.assertIsNone(model.split_char_key("NoRealm"))

    def test_prefilter(self):
        self.assertTrue(model.has_profile_keys(ELV))
        self.assertFalse(model.has_profile_keys(b"X = {\n}\n"))
```

- [ ] **Step 2: Run to see it fail**

Run: `python3 scripts/run_tests.py -k ace_model`
Expected: ImportError.

- [ ] **Step 3: Implement `model.py`**

```python
"""Which top-level SavedVariables are AceDB-3.0 databases, and their profiles, characters, module profiles and
LibDualSpec spec profiles (spec §2, §5.2). UI-free.

A database is recognised by its shape: `profileKeys` maps "Name - Realm" strings to profile-name strings, and
`profiles` (when present) maps names to tables. Look-alikes (GUID-keyed tables, arrays) are rejected with a note.
"""
from __future__ import annotations

from dataclasses import dataclass

from wowtools.tools.ace_profiles.luasv import Chunk, Field, Opaque, Scalar, Table, is_blank_table

LDS = "LibDualSpec-1.0"
DEFAULT = "Default"
CHAR_SEPARATOR = " - "


def ace_descend(path: tuple) -> bool:
    """Descend only where profile data lives: the database table, profileKeys, the keys of profiles, each
    namespace's profiles keys and LibDualSpec's per-character spec tables."""
    depth = len(path)
    if depth == 1:
        return True
    section = path[1]
    if depth == 2:
        return section in ("profileKeys", "profiles", "namespaces")
    if section != "namespaces":
        return False
    if depth == 3:
        return True
    if depth == 4:
        return path[3] == "profiles" or (path[2] == LDS and path[3] == "char")
    if depth == 5:
        return path[2] == LDS and path[3] == "char"
    return False


def has_profile_keys(data: bytes) -> bool:
    return b"profileKeys" in data


def split_char_key(key: str) -> tuple[str, str] | None:
    name, sep, realm = key.partition(CHAR_SEPARATOR)
    return (name, realm) if sep and name and realm else None


@dataclass
class ProfileEntry:
    name: str
    field: Field
    empty: bool
    size: int


@dataclass
class NamespaceProfiles:
    name: str
    table: Table
    entries: dict[str, Field]


@dataclass
class LdsChar:
    char: str
    enabled: bool
    specs: dict[int, Field]


@dataclass
class AceDb:
    sv_name: str
    keys_table: Table
    profile_keys: dict[str, str]
    key_fields: dict[str, Field]
    profiles_table: Table | None
    profiles: dict[str, ProfileEntry]
    namespaces: dict[str, NamespaceProfiles]
    lds: dict[str, LdsChar]

    def users(self, name: str) -> list[str]:
        return [char for char, profile in self.profile_keys.items() if profile == name]

    def profile_names(self) -> list[str]:
        referenced = sorted({p for p in self.profile_keys.values() if p not in self.profiles})
        return list(self.profiles) + referenced

    def missing(self, name: str) -> bool:
        return name not in self.profiles and name in self.profile_keys.values()

    def lds_enabled(self, char: str) -> bool:
        entry = self.lds.get(char)
        return entry is not None and entry.enabled


def _string_map(table: Table) -> dict[str, Field] | None:
    """{key: field} when every key is a string and every value a string scalar; else None."""
    out: dict[str, Field] = {}
    for item in table.fields:
        if not isinstance(item.key, str) or item.key in out:
            return None
        if not isinstance(item.value, Scalar) or not isinstance(item.value.value, str):
            return None
        out[item.key] = item
    return out


def _table_map(value) -> dict[str, Field] | None:
    """{key: field} when value is a table whose keys are strings and whose values are tables; else None."""
    if not isinstance(value, Table):
        return None
    out: dict[str, Field] = {}
    for item in value.fields:
        if not isinstance(item.key, str) or item.key in out or not isinstance(item.value, (Table, Opaque)):
            return None
        out[item.key] = item
    return out


def _namespaces(db_table: Table) -> dict[str, NamespaceProfiles]:
    found: dict[str, NamespaceProfiles] = {}
    holder = db_table.get("namespaces")
    if holder is None or not isinstance(holder.value, Table):
        return found
    for ns in holder.value.fields:
        if not isinstance(ns.key, str) or not isinstance(ns.value, Table):
            continue
        profiles = ns.value.get("profiles")
        entries = _table_map(profiles.value) if profiles is not None else None
        if entries is not None:
            found[ns.key] = NamespaceProfiles(ns.key, profiles.value, entries)
    return found


def _lds(db_table: Table) -> dict[str, LdsChar]:
    found: dict[str, LdsChar] = {}
    holder = db_table.get("namespaces")
    if holder is None or not isinstance(holder.value, Table):
        return found
    lds = holder.value.get(LDS)
    chars = lds.value.get("char") if lds is not None and isinstance(lds.value, Table) else None
    if chars is None or not isinstance(chars.value, Table):
        return found
    for entry in chars.value.fields:
        if not isinstance(entry.key, str) or not isinstance(entry.value, Table):
            continue
        enabled = entry.value.get("enabled")
        specs = {item.key: item for item in entry.value.fields
                 if isinstance(item.key, int) and not isinstance(item.key, bool)
                 and isinstance(item.value, Scalar) and isinstance(item.value.value, str)}
        found[entry.key] = LdsChar(entry.key, bool(enabled and isinstance(enabled.value, Scalar)
                                                    and enabled.value.value is True), specs)
    return found


def find_dbs(chunk: Chunk, data: bytes) -> tuple[list[AceDb], list[str]]:
    dbs: list[AceDb] = []
    notes: list[str] = []
    for assignment in chunk.assignments:
        table = assignment.value
        if not isinstance(table, Table):
            continue
        keys = table.get("profileKeys")
        if keys is None:
            continue
        name = assignment.name
        key_fields = _string_map(keys.value) if isinstance(keys.value, Table) else None
        if key_fields is None or any(split_char_key(k) is None for k in key_fields):
            notes.append(f"{name}: profileKeys is not an AceDB character map; left alone")
            continue
        profiles_field = table.get("profiles")
        profile_fields = _table_map(profiles_field.value) if profiles_field is not None else {}
        if profile_fields is None:
            notes.append(f"{name}: profiles is not an AceDB profile table; left alone")
            continue
        profiles = {n: ProfileEntry(n, f, is_blank_table(data, f.value), f.value.end - f.value.start)
                    for n, f in profile_fields.items()}
        dbs.append(AceDb(name, keys.value, {k: f.value.value for k, f in key_fields.items()}, key_fields,
                         profiles_field.value if profiles_field is not None else None, profiles,
                         _namespaces(table), _lds(table)))
    return dbs, notes
```

Note: `_namespaces` skips `LibDualSpec-1.0` naturally (it has no `profiles` table). If it ever had one, it would be
a namespace like any other, which is what AceDB does too.

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_model`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools/ace_profiles/model.py tests/test_ace_model.py
git commit -m "feat(ace-profiles): detect AceDB databases, profiles, namespaces and LibDualSpec"
```

---
### Task 4: package skeleton: events, settings

**Files:**
- Create: `wowtools/tools/ace_profiles/events.py`, `wowtools/tools/ace_profiles/settings.py`
- Modify: `wowtools/tools/ace_profiles/__init__.py` (import `events`)
- Modify: `docs/events.md` (regenerated)
- Test: `tests/test_ace_settings.py`

**Interfaces:**
- Produces:
  - `events.TOOL_NAME = "ace-profiles"`, `events.EVENTS`.
  - `settings.SECTION = "ace_profiles"`, `DEFAULT_KEEP_SNAPSHOTS = 2`, `DEFAULT_KEEP_JOURNALS = 10`,
    `ROOT_NAME = TOOL_NAME`.
  - `@dataclass ProfileSettings(backup_dir: Path | None = None, keep_snapshots: int = 2, keep_journals: int = 10,
    blacklist: list[str] = [], last_flavor_choice: str | None = None, last_account: str | None = None)`.
  - `load_settings(cfg) -> ProfileSettings`, `save_settings(cfg, settings, *, source="settings") -> None`.
  - `parse_blacklist(text: str) -> list[str]`, `format_blacklist(names: list[str]) -> str`,
    `is_blacklisted(names: list[str], addon: str) -> bool`.
  - `resolve_root(settings, wow_path) -> Path | None` (`<backup_dir or <WoW>/wow-tools>/ace-profiles`),
    `resolve_journal_dir(wow_path) -> Path | None`, `validate_backup_dir(path, install) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ace_settings.py
"""Ace3 Profile Manager settings: [ace_profiles] in config/ace-profiles.cfg (spec §11)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.events import TOOL_REGISTRIES
from wowtools.tools.ace_profiles import settings as s
from wowtools.tools.ace_profiles.events import TOOL_NAME


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = Config(self.tmp / "ace-profiles.cfg")

    def test_defaults(self):
        loaded = s.load_settings(self.cfg)
        self.assertEqual(loaded, s.ProfileSettings())
        self.assertEqual((loaded.keep_snapshots, loaded.keep_journals, loaded.blacklist), (2, 10, []))

    def test_round_trip(self):
        saved = s.ProfileSettings(backup_dir=self.tmp / "out", keep_snapshots=4, keep_journals=3,
                                  blacklist=["ElvUI", "Questie"], last_flavor_choice="", last_account="ACCT1")
        s.save_settings(self.cfg, saved)
        self.assertEqual(s.load_settings(Config(self.tmp / "ace-profiles.cfg").load()), saved)

    def test_bad_numbers_fall_back_and_floor_at_one(self):
        self.cfg.set(s.SECTION, "keep_snapshots", "0", log=False)
        self.cfg.set(s.SECTION, "keep_journals", "abc", log=False)
        loaded = s.load_settings(self.cfg)
        self.assertEqual((loaded.keep_snapshots, loaded.keep_journals), (1, 10))

    def test_blacklist_parsing(self):
        self.assertEqual(s.parse_blacklist(" ElvUI, questie\nQuestie ,, Bartender4 "), ["Bartender4", "ElvUI", "questie"])
        self.assertEqual(s.format_blacklist(["ElvUI", "Questie"]), "ElvUI, Questie")
        self.assertTrue(s.is_blacklisted(["ElvUI"], "elvui"))
        self.assertFalse(s.is_blacklisted(["ElvUI"], "ElvUI_Options"))

    def test_root_and_journal_dir(self):
        wow = self.tmp / "World of Warcraft"
        self.assertEqual(s.resolve_root(s.ProfileSettings(), wow), wow / "wow-tools" / "ace-profiles")
        self.assertEqual(s.resolve_root(s.ProfileSettings(backup_dir=self.tmp / "b"), wow),
                         self.tmp / "b" / "ace-profiles")
        self.assertIsNone(s.resolve_root(s.ProfileSettings(), None))
        self.assertEqual(s.resolve_journal_dir(wow), wow / "wow-tools" / "ace-profiles" / "journal")

    def test_events_registered_with_prefix(self):
        self.assertIn(TOOL_NAME, TOOL_REGISTRIES)
        self.assertTrue(all(name.startswith("ace.") for name in TOOL_REGISTRIES[TOOL_NAME]))
```

(If `TOOL_REGISTRIES` holds something other than a dict of names per tool, adapt only the last test to its real shape;
`scripts/gen_event_docs.py` shows how it is read.)

- [ ] **Step 2: Run to see it fail**

Run: `python3 scripts/run_tests.py -k ace_settings`. Expected: ImportError.

- [ ] **Step 3: Implement**

`events.py`, in the shape of `wtf_cleaner/events.py`:

```python
"""Events emitted by the Ace3 Profile Manager. Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events

TOOL_NAME = "ace-profiles"

EVENTS: dict[str, EventSpec] = {
    "ace.scan_started": EventSpec("info", "A scan of one flavor's SavedVariables for AceDB databases started."),
    "ace.scan_completed": EventSpec("info", "A scan finished, with counts (files, databases, profiles, characters, leftover characters, seconds)."),
    "ace.file_unreadable": EventSpec("warning", "A SavedVariables file or folder could not be read; it is left out."),
    "ace.parse_failed": EventSpec("warning", "A SavedVariables file is not readable Lua; it is shown as a warning and never changed."),
    "ace.lookalike": EventSpec("debug", "A table looks like an AceDB database but is not one; it is left alone."),
    "ace.staged": EventSpec("debug", "A change was staged on the review screen (operation and counts)."),
    "ace.blacklist_changed": EventSpec("info", "An addon was added to or removed from the blacklist."),
    "ace.unlocked": EventSpec("info", "A blacklisted addon was unlocked for this session."),
    "ace.apply_started": EventSpec("info", "Apply (or a dry run) of the staged changes started."),
    "ace.wow_running": EventSpec("warning", "Apply or Undo was refused because WoW of that flavor is running."),
    "ace.file_changed": EventSpec("warning", "A file changed since the scan; its changes were skipped."),
    "ace.file_locked": EventSpec("error", "Apply or Undo stopped before changing anything: files are locked by another program."),
    "ace.probe_recovered": EventSpec("warning", "A SavedVariables file left as <name>.wowtools-lockcheck by an interrupted lock check was renamed back."),
    "ace.snapshot_taken": EventSpec("info", "The whole-WTF snapshot was written and verified."),
    "ace.snapshot_failed": EventSpec("error", "The whole-WTF snapshot failed; nothing was changed."),
    "ace.files_backed_up": EventSpec("info", "The originals of the files to change were zipped and verified."),
    "ace.backup_failed": EventSpec("error", "The zip of the original files failed; nothing was changed."),
    "ace.file_edited": EventSpec("info", "A SavedVariables file was rewritten with the staged changes."),
    "ace.would_edit": EventSpec("info", "Dry run: a file that would be rewritten, with its changes (checked, not written)."),
    "ace.verify_failed": EventSpec("error", "An edited file did not re-read as expected; it was not written and the run stopped."),
    "ace.write_failed": EventSpec("error", "A SavedVariables file could not be written; the run stopped."),
    "ace.rolled_back": EventSpec("warning", "After a failure, the files this run had already written were put back."),
    "ace.rollback_failed": EventSpec("error", "A file could not be put back after a failure; restore it from the zip the message names."),
    "ace.apply_completed": EventSpec("info", "Apply finished (logged at warning if any file was skipped or failed)."),
    "ace.dry_run_completed": EventSpec("info", "A dry run finished."),
    "ace.flavors_stopped": EventSpec("warning", "An Apply over several flavors stopped at one flavor; the flavors after it were not started."),
    "ace.snapshots_pruned": EventSpec("info", "Older whole-WTF snapshots of the flavor were deleted to keep the newest N (keep_snapshots)."),
    "ace.journal_failed": EventSpec("error", "The run journal could not be written; nothing was changed."),
    "ace.journal_pruned": EventSpec("info", "Older journals (and the zips only they used) were deleted to keep the newest N (keep_journals)."),
    "ace.undo_started": EventSpec("info", "Undo last change started, from the newest journal."),
    "ace.file_restored": EventSpec("info", "Undo or recovery: a file was put back to its original bytes."),
    "ace.file_skipped": EventSpec("warning", "Undo or recovery: a file was left alone (it changed since the run, or is outside the WTF folder)."),
    "ace.undo_failed": EventSpec("error", "Undo or recovery: a file could not be put back (its zip is missing or does not match)."),
    "ace.undo_completed": EventSpec("info", "Undo last change finished (logged at warning if any file was skipped or failed)."),
    "ace.recovery_offered": EventSpec("warning", "A marker from an Apply that did not finish was found when the tool opened."),
    "ace.recovery_done": EventSpec("info", "The user chose what to do about an unfinished Apply (put back or leave)."),
}

register_events(TOOL_NAME, EVENTS)
```

`settings.py`:

```python
"""The Ace3 Profile Manager's own settings: the [ace_profiles] section of config/ace-profiles.cfg (spec §11)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core import journal as core_journal
from wowtools.core.config import Config
from wowtools.core.install import WowInstall, validate_output_dir
from wowtools.core.journal import TOOLS_SUBDIR
from wowtools.tools.ace_profiles.events import TOOL_NAME

SECTION = "ace_profiles"
ROOT_NAME = TOOL_NAME
DEFAULT_KEEP_SNAPSHOTS = 2
DEFAULT_KEEP_JOURNALS = 10
_SPLIT = re.compile(r"[,\r\n]+")


@dataclass
class ProfileSettings:
    backup_dir: Path | None = None  # None: <WoW folder>/wow-tools; the tool's files go to <backup_dir>/ace-profiles
    keep_snapshots: int = DEFAULT_KEEP_SNAPSHOTS  # whole-WTF snapshots kept per flavor (at least 1)
    keep_journals: int = DEFAULT_KEEP_JOURNALS  # run journals kept (at least 1); their per-file zips go with them
    blacklist: list[str] = field(default_factory=list)  # addon names (SavedVariables file name without .lua)
    last_flavor_choice: str | None = None  # "" = All flavors, else a flavor folder; None = never chosen
    last_account: str | None = None  # None (stored as empty) = all accounts


def parse_blacklist(text: str) -> list[str]:
    """Names separated by commas or new lines; blanks dropped; duplicates (ignoring case) keep the first spelling;
    sorted ignoring case."""
    seen: dict[str, str] = {}
    for part in _SPLIT.split(text or ""):
        name = part.strip()
        if name and name.casefold() not in seen:
            seen[name.casefold()] = name
    return sorted(seen.values(), key=str.casefold)


def format_blacklist(names: list[str]) -> str:
    return ", ".join(names)


def is_blacklisted(names: list[str], addon: str) -> bool:
    wanted = addon.casefold()
    return any(name.casefold() == wanted for name in names)


def _count(cfg: Config, key: str, default: int) -> int:
    value = cfg.get_int(SECTION, key, default)
    return max(1, value)


def load_settings(cfg: Config) -> ProfileSettings:
    choice = cfg.get(SECTION, "last_flavor_choice")
    return ProfileSettings(cfg.get_path(SECTION, "backup_dir"),
                           _count(cfg, "keep_snapshots", DEFAULT_KEEP_SNAPSHOTS),
                           _count(cfg, "keep_journals", DEFAULT_KEEP_JOURNALS),
                           parse_blacklist(cfg.get(SECTION, "blacklist") or ""),
                           None if choice is None else choice.strip(),
                           (cfg.get(SECTION, "last_account") or "").strip() or None)


def save_settings(cfg: Config, settings: ProfileSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    cfg.set(SECTION, "keep_snapshots", settings.keep_snapshots, source=source)
    cfg.set(SECTION, "keep_journals", settings.keep_journals, source=source)
    cfg.set(SECTION, "blacklist", format_blacklist(settings.blacklist), source=source)
    cfg.set(SECTION, "last_account", settings.last_account or "", source=source)
    if settings.last_flavor_choice is not None:
        cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_root(settings: ProfileSettings, wow_path: Path | None) -> Path | None:
    """Where snapshots/, edited/ and the crash marker live."""
    if settings.backup_dir is not None:
        return settings.backup_dir / ROOT_NAME
    return wow_path / TOOLS_SUBDIR / ROOT_NAME if wow_path is not None else None


def resolve_journal_dir(wow_path: Path | None) -> Path | None:
    return core_journal.journal_dir(wow_path, TOOL_NAME)


def validate_backup_dir(path: Path | None, install: WowInstall) -> str | None:
    """None when fine (empty means the default); else the reason, as Interface Backup does."""
    if path is None:
        return None
    return validate_output_dir(path, install, what="backup folder", example="D:\\WoW backups")
```

`get_int` with a bad value: check `core/config.py`. If it raises instead of returning the default, wrap it in
`try/except ValueError`, returning `default`. The test pins "abc" → 10.

`__init__.py`:

```python
"""Ace3 Profile Manager: see and change which AceDB-3.0 profile each character uses (spec 2026-10-04)."""
from __future__ import annotations

from wowtools.tools.ace_profiles import events  # noqa: F401  (registers the tool's events)
```

- [ ] **Step 4: Regenerate docs and run tests**

Run: `python3 scripts/gen_event_docs.py`, then `python3 scripts/run_tests.py -k ace_settings`, then `-k docs`, then
`-k events`.
Expected: all pass. `docs/events.md` gains an "ace-profiles" section. If `gen_event_docs.py` only renders tools
listed in `TOOLS`, `test_docs` stays green now, and Task 11 regenerates it after registration.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools/ace_profiles docs/events.md tests/test_ace_settings.py
git commit -m "feat(ace-profiles): events and settings"
```

---

### Task 5: test fixture `build_ace_tree` and the scanner

**Files:**
- Modify: `tests/fixtures.py` (add `ace_lua`, `build_ace_tree` and the module docstring lines)
- Create: `wowtools/tools/ace_profiles/scanner.py`
- Test: `tests/test_ace_scanner.py`

**Interfaces:**
- Consumes: `luasv.parse`, `LuaParseError`; `model.ace_descend`, `has_profile_keys`, `find_dbs`, `AceDb`;
  `core.install.Flavor/Account/Character`; `core.fsutil.is_link`; `core.events.log_event`.
- Produces (all in `scanner`):
  - `@dataclass(frozen=True) SvFile(path: Path, flavor: Flavor, account: str, character: Character | None,
    size: int, mtime: float, sha256: str)` with `.addon -> str` (file name without `.lua`), `.rel -> str` (path
    relative to `flavor.path`, POSIX, e.g. `WTF/Account/ACCT1/SavedVariables/KickCD.lua`), `.owner -> str`
    (`"Account-wide"` or `character.label`).
  - `@dataclass AddonFile(file: SvFile, dbs: list[AceDb])`.
  - `@dataclass AccountScan(flavor: Flavor, account: str, characters: dict[str, str], files: list[AddonFile])`
    (`characters`: casefolded `"Name - Realm"` → display `"Name - Realm"`, from the folders) with
    `.is_leftover(char_key) -> bool`.
  - `@dataclass(frozen=True) ScanWarning(path: Path | None, message: str)`.
  - `@dataclass FlavorScan(flavor: Flavor, accounts: list[AccountScan], warnings: list[ScanWarning],
    error: str | None = None)` with `.files() -> list[AddonFile]`.
  - `@dataclass ScanResult(flavors: list[FlavorScan])` with `.warnings -> list[ScanWarning]`.
  - `ScanProgress = Callable[[int, int, str], None]`.
  - `candidate_files(sv_dir: Path) -> list[Path]`.
  - `sha256_of(data: bytes) -> str`.
  - `scan_flavor(flavor, *, account: str | None = None, progress: ScanProgress | None = None) -> FlavorScan`.
  - `scan_flavors(flavors: list[Flavor], *, account: str | None = None,
    progress: Callable[[Flavor, int, int, str], None] | None = None) -> ScanResult`.
  - Fixture: `tests.fixtures.build_ace_tree(root: Path) -> Path` and `tests.fixtures.ace_lua(*lines: str) -> str`.

- [ ] **Step 1: Add the fixture**

Append to `tests/fixtures.py`. Write the files with `newline=""`, so the CRLF stays exactly as written. Add a
docstring paragraph describing `build_ace_tree`.

```python
def ace_lua(*lines: str) -> str:
    """SavedVariables text the way WoW writes it: a leading blank line, CRLF, no indentation."""
    return "\r\n" + "\r\n".join(lines) + "\r\n"


def _write_lua(path: Path, text: str, mtime: float = FRESH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.utime(path, (mtime, mtime))
    return path


ACE_KICKCD = ace_lua(
    'KickCDDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '["Mierin - Khaz Modan"] = "Default",',
    '["Gone - Realm1"] = "Default",', '},', '["profiles"] = {', '["Default"] = {', '["scale"] = 0.6000000000000001,',
    '["text"] = "a\\"b\\\\c\\n\\000",', '[114052] = true,', '},', '["Backup"] = {', '},', '},',
    '["global"] = {', '["schemaVersion"] = 3,', '},', '}',
    'KickCDPerfDB = {', '["runs"] = 3,', '}')
ACE_HANDYNOTES = ace_lua(
    'HandyNotesDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Kaelys - Realm1",',
    '["Mierin - Khaz Modan"] = "Mierin - Khaz Modan",', '},', '["profiles"] = {',
    '["Kaelys - Realm1"] = {', '["icon_scale"] = 1.5,', '},', '["Mierin - Khaz Modan"] = {', '},',
    '["Unused - Realm1"] = {', '["icon_scale"] = 2,', '},', '},', '}',
    'HandyNotes_MapNotesDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '},',
    '["profiles"] = {', '["Default"] = {', '["notes"] = {', '"TOP",', 'nil,', '"TOP",', '},', '},', '},', '}')
ACE_ELVUI = ace_lua(
    'ElvDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '["Mierin - Khaz Modan"] = "Healer",', '},',
    '["profiles"] = {', '["Default"] = {', '["x"] = 1,', '},', '["Healer"] = {', '["x"] = 2,', '},', '},',
    '["namespaces"] = {', '["Bags"] = {', '["profiles"] = {', '["Default"] = {', '["b"] = 1,', '},',
    '["Healer"] = {', '["b"] = 2,', '},', '},', '},', '["LibDualSpec-1.0"] = {', '["char"] = {',
    '["Kaelys - Realm1"] = {', '["enabled"] = true,', '[1] = "Default",', '[2] = "Healer",', '},', '},', '},', '},',
    '}',
    'ElvPrivateDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Kaelys - Realm1",', '},',
    '["profiles"] = {', '["Kaelys - Realm1"] = {', '["install"] = true,', '},', '},', '}')
ACE_STOCK = ace_lua('StockDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Gone",', '},', '["global"] = {',
                    '},', '}')
ACE_MEMENTO = ace_lua('Memento = {', '["profileKeys"] = {', '["Player-3725-0A"] = {', '},', '},', '}')
ACE_BROKEN = ace_lua('BrokenDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",')
ACE_PERCHAR = ace_lua('PerCharDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '},',
                      '["profiles"] = {', '["Default"] = {', '},', '},', '}')
ACE_ACCT2 = ace_lua('KickCDDB = {', '["profileKeys"] = {', '["Chârb - Realm2"] = "Default",', '},',
                    '["profiles"] = {', '["Default"] = {', '},', '},', '}')
ACE_QUESTIE = ace_lua('QuestieConfig = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '},',
                      '["profiles"] = {', '["Default"] = {', '},', '},', '}')


def build_ace_tree(root: Path) -> Path:
    """A WoW install with AceDB SavedVariables (see ACE_* above):

    _retail_/WTF/Account/ACCT1: characters Realm1/Kaelys and "Khaz Modan"/Mierin
      SavedVariables: KickCD.lua (KickCDDB, Default shared, leftover "Gone - Realm1", unused Backup; KickCDPerfDB
      plain), KickCD.lua.bak (ignored), HandyNotes.lua (char-keyed HandyNotesDB with an unused profile, plus
      HandyNotes_MapNotesDB), ElvUI.lua (ElvDB with namespace Bags and LibDualSpec; ElvPrivateDB), Stock.lua
      (StockDB: missing profile "Gone"), Memento.lua (look-alike), Broken.lua (unparsable), Plain.lua (no AceDB),
      Blizzard_AceThing.lua (skipped by name)
      Realm1/Kaelys/SavedVariables/PerChar.lua (per-character PerCharDB)
    _retail_/WTF/Account/ACCT2: Realm2/Chârb; SavedVariables/KickCD.lua
    _classic_era_/WTF/Account/ACCT1: Realm1/Kaelys; SavedVariables/Questie.lua (QuestieConfig)
    """
    retail = root / "_retail_"
    _addon(retail, "KickCD")
    acct1 = retail / "WTF" / "Account" / "ACCT1"
    sv = acct1 / "SavedVariables"
    _write_lua(sv / "KickCD.lua", ACE_KICKCD)
    _write_lua(sv / "KickCD.lua.bak", ACE_KICKCD)
    _write_lua(sv / "HandyNotes.lua", ACE_HANDYNOTES)
    _write_lua(sv / "ElvUI.lua", ACE_ELVUI)
    _write_lua(sv / "Stock.lua", ACE_STOCK)
    _write_lua(sv / "Memento.lua", ACE_MEMENTO)
    _write_lua(sv / "Broken.lua", ACE_BROKEN)
    _write_lua(sv / "Plain.lua", ace_lua('PlainDB = {', '["x"] = 1,', '}'))
    _write_lua(sv / "Blizzard_AceThing.lua", ACE_PERCHAR)
    _write_lua(acct1 / "Realm1" / "Kaelys" / "SavedVariables" / "PerChar.lua", ACE_PERCHAR)
    (acct1 / "Khaz Modan" / "Mierin").mkdir(parents=True, exist_ok=True)
    acct2 = retail / "WTF" / "Account" / "ACCT2"
    _write_lua(acct2 / "SavedVariables" / "KickCD.lua", ACE_ACCT2)
    (acct2 / "Realm2" / "Chârb").mkdir(parents=True, exist_ok=True)
    era = root / "_classic_era_"
    _addon(era, "Questie")
    _write_lua(era / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "Questie.lua", ACE_QUESTIE)
    (era / "WTF" / "Account" / "ACCT1" / "Realm1" / "Kaelys").mkdir(parents=True, exist_ok=True)
    return root
```

- [ ] **Step 2: Write the failing scanner test**

```python
# tests/test_ace_scanner.py
"""scanner: SavedVariables across accounts and characters, AceDB databases, leftovers and warnings (spec §6)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import scanner


class ScannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = build_ace_tree(Path(tmp.name) / "wow")
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("_retail_")

    def files(self, scan):
        return {(f.file.account, f.file.owner, f.file.addon): [db.sv_name for db in f.dbs] for f in scan.files()}

    def test_finds_databases_per_file(self):
        scan = scanner.scan_flavor(self.retail)
        self.assertIsNone(scan.error)
        self.assertEqual(self.files(scan), {
            ("ACCT1", "Account-wide", "ElvUI"): ["ElvDB", "ElvPrivateDB"],
            ("ACCT1", "Account-wide", "HandyNotes"): ["HandyNotesDB", "HandyNotes_MapNotesDB"],
            ("ACCT1", "Account-wide", "KickCD"): ["KickCDDB"],
            ("ACCT1", "Account-wide", "Stock"): ["StockDB"],
            ("ACCT1", "Realm1/Kaelys", "PerChar"): ["PerCharDB"],
            ("ACCT2", "Account-wide", "KickCD"): ["KickCDDB"],
        })

    def test_skips_bak_blizzard_and_non_lua(self):
        names = {f.file.path.name for f in scanner.scan_flavor(self.retail).files()}
        self.assertNotIn("KickCD.lua.bak", names)
        self.assertNotIn("Blizzard_AceThing.lua", names)

    def test_warnings_for_unparsable_and_lookalike(self):
        with capture_events() as events:
            scan = scanner.scan_flavor(self.retail)
        messages = [w.message for w in scan.warnings]
        self.assertTrue(any("Broken.lua" in str(w.path) for w in scan.warnings))
        self.assertTrue(any("not readable" in m for m in messages))
        self.assertIn("ace.parse_failed", [e["event"] for e in events])
        self.assertIn("ace.scan_completed", [e["event"] for e in events])

    def test_leftovers_and_characters(self):
        scan = scanner.scan_flavor(self.retail)
        acct1 = next(a for a in scan.accounts if a.account == "ACCT1")
        self.assertTrue(acct1.is_leftover("Gone - Realm1"))
        self.assertFalse(acct1.is_leftover("kaelys - realm1"))
        self.assertFalse(acct1.is_leftover("Mierin - Khaz Modan"))

    def test_file_identity(self):
        scan = scanner.scan_flavor(self.retail)
        kick = next(f.file for f in scan.files() if f.file.addon == "KickCD" and f.file.account == "ACCT1")
        data = kick.path.read_bytes()
        self.assertEqual(kick.sha256, scanner.sha256_of(data))
        self.assertEqual(kick.size, len(data))
        self.assertEqual(kick.rel, "WTF/Account/ACCT1/SavedVariables/KickCD.lua")

    def test_one_account_case_insensitive(self):
        scan = scanner.scan_flavor(self.retail, account="acct2")
        self.assertEqual([a.account for a in scan.accounts], ["ACCT2"])

    def test_progress_and_multi_flavor(self):
        seen = []
        result = scanner.scan_flavors([self.retail, self.install.flavor("_classic_era_")],
                                      progress=lambda flavor, i, n, label: seen.append((flavor.folder, i, n)))
        self.assertEqual([f.flavor.folder for f in result.flavors], ["_retail_", "_classic_era_"])
        self.assertEqual(seen[-1][0], "_classic_era_")
        self.assertEqual(seen[-1][1], seen[-1][2])

    def test_flavor_without_wtf_is_an_error_not_an_exception(self):
        empty = self.root / "_ptr_"
        empty.mkdir()
        scan = scanner.scan_flavor(self.install.flavor("_ptr_"))
        self.assertIsNotNone(scan.error)

    @unittest.skipIf(os.name == "nt", "symlink creation needs privileges on Windows")
    def test_saved_variables_under_a_link_is_skipped(self):
        target = self.root.parent / "elsewhere"
        target.mkdir()
        link = self.retail.account_dir / "ACCT2" / "Realm2" / "Linked"
        os.symlink(target, link)
        (target / "SavedVariables").mkdir()
        (target / "SavedVariables" / "X.lua").write_bytes(b'X = {\n["profileKeys"] = {\n},\n}\n')
        scan = scanner.scan_flavor(self.retail)
        self.assertNotIn("X", {f.file.addon for f in scan.files()})
        self.assertTrue(any("link" in w.message for w in scan.warnings))
```

- [ ] **Step 3: Run to see it fail**

Run: `python3 scripts/run_tests.py -k ace_scanner`. Expected: ImportError.

- [ ] **Step 4: Implement `scanner.py`**

```python
"""Scan a flavor's SavedVariables for AceDB databases (spec §6). UI-free.

Every account-wide and per-character SavedVariables/*.lua is read once. A file without the bytes "profileKeys" is
not parsed. Files are parsed with model.ace_descend, so only profile data is built. Blizzard_* files, *.lua.bak
(anything not ending in exactly ".lua") and SavedVariables folders under a symlink or junction are skipped.
"""
from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.fsutil import is_link
from wowtools.core.install import Account, Character, Flavor
from wowtools.tools.ace_profiles.luasv import LuaParseError, parse
from wowtools.tools.ace_profiles.model import AceDb, ace_descend, find_dbs, has_profile_keys

ScanProgress = Callable[[int, int, str], None]
PROTECTED_PREFIX = "blizzard_"
ACCOUNT_WIDE = "Account-wide"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SvFile:
    path: Path
    flavor: Flavor
    account: str
    character: Character | None
    size: int
    mtime: float
    sha256: str

    @property
    def addon(self) -> str:
        return self.path.name[:-4]

    @property
    def rel(self) -> str:
        return self.path.relative_to(self.flavor.path).as_posix()

    @property
    def owner(self) -> str:
        return ACCOUNT_WIDE if self.character is None else self.character.label


@dataclass
class AddonFile:
    file: SvFile
    dbs: list[AceDb]


@dataclass
class AccountScan:
    flavor: Flavor
    account: str
    characters: dict[str, str] = field(default_factory=dict)
    files: list[AddonFile] = field(default_factory=list)

    def is_leftover(self, char_key: str) -> bool:
        return char_key.casefold() not in self.characters


@dataclass(frozen=True)
class ScanWarning:
    path: Path | None
    message: str


@dataclass
class FlavorScan:
    flavor: Flavor
    accounts: list[AccountScan] = field(default_factory=list)
    warnings: list[ScanWarning] = field(default_factory=list)
    error: str | None = None

    def files(self) -> list[AddonFile]:
        return [f for account in self.accounts for f in account.files]


@dataclass
class ScanResult:
    flavors: list[FlavorScan]

    @property
    def warnings(self) -> list[ScanWarning]:
        return [w for f in self.flavors for w in f.warnings]


def candidate_files(sv_dir: Path) -> list[Path]:
    """Regular files directly in sv_dir whose name ends in exactly ".lua" and doesn't start with Blizzard_."""
    found = []
    with os.scandir(sv_dir) as entries:
        for entry in entries:
            name = entry.name
            if not name.endswith(".lua") or name.casefold().startswith(PROTECTED_PREFIX) or len(name) <= 4:
                continue
            if entry.is_file(follow_symlinks=False) and not is_link(entry):
                found.append(Path(entry.path))
    return sorted(found, key=lambda p: p.name.casefold())


def _under_link(sv_dir: Path, account_dir: Path) -> bool:
    current = sv_dir
    while True:
        if is_link(current):
            return True
        if current == account_dir or current.parent == current:
            return False
        current = current.parent


def scan_flavor(flavor: Flavor, *, account: str | None = None, progress: ScanProgress | None = None) -> FlavorScan:
    started = time.monotonic()
    result = FlavorScan(flavor)
    log_event("ace.scan_started", flavor=flavor.folder, account=account or "all")
    if not flavor.account_dir.is_dir():
        result.error = f"{flavor.display_name} has no WTF/Account folder"
        return result

    def on_error(path: Path, exc: OSError) -> None:
        result.warnings.append(ScanWarning(path, f"could not read {path.name}: {exc.strerror or exc}"))
        log_event("ace.file_unreadable", path=str(path), error=str(exc))

    accounts: list[Account] = flavor.accounts(on_error)
    if account is not None:
        accounts = [a for a in accounts if a.name.casefold() == account.casefold()]
    work: list[tuple[AccountScan, Character | None, Path]] = []
    for acct in accounts:
        scan = AccountScan(flavor, acct.name)
        result.accounts.append(scan)
        characters = acct.characters(on_error)
        for char in characters:
            key = f"{char.name} - {char.realm}"
            scan.characters[key.casefold()] = key
        for owner, sv_dir in [(None, acct.saved_variables_dir)] + [(c, c.saved_variables_dir) for c in characters]:
            if not sv_dir.is_dir():
                continue
            if _under_link(sv_dir, acct.path):
                result.warnings.append(ScanWarning(sv_dir, "skipped: this SavedVariables folder is under a link"))
                continue
            try:
                for path in candidate_files(sv_dir):
                    work.append((scan, owner, path))
            except OSError as exc:
                on_error(sv_dir, exc)
    for index, (scan, owner, path) in enumerate(work, 1):
        _read_one(result, scan, owner, path)
        if progress is not None:
            progress(index, len(work), path.name)
    if progress is not None and not work:
        progress(0, 0, "")
    dbs = [db for f in result.files() for db in f.dbs]
    log_event("ace.scan_completed", flavor=flavor.folder, files=len(result.files()), dbs=len(dbs),
              profiles=sum(len(db.profile_names()) for db in dbs),
              characters=sum(len(db.profile_keys) for db in dbs),
              leftovers=sum(1 for a in result.accounts for f in a.files for db in f.dbs
                            for c in db.profile_keys if a.is_leftover(c)),
              warnings=len(result.warnings), seconds=round(time.monotonic() - started, 2))
    return result


def _read_one(result: FlavorScan, scan: AccountScan, owner: Character | None, path: Path) -> None:
    try:
        data = path.read_bytes()
        info = path.stat()
    except OSError as exc:
        result.warnings.append(ScanWarning(path, f"could not read {path.name}: {exc.strerror or exc}"))
        log_event("ace.file_unreadable", path=str(path), error=str(exc))
        return
    if not has_profile_keys(data):
        return
    try:
        chunk = parse(data, ace_descend)
    except LuaParseError as exc:
        result.warnings.append(ScanWarning(path, f"{path.name} is not readable Lua ({exc}); it is left alone"))
        log_event("ace.parse_failed", path=str(path), offset=exc.offset, error=str(exc))
        return
    dbs, notes = find_dbs(chunk, data)
    for note in notes:
        log_event("ace.lookalike", path=str(path), note=note)
    if dbs:
        sv = SvFile(path, scan.flavor, scan.account, owner, len(data), info.st_mtime, sha256_of(data))
        scan.files.append(AddonFile(sv, dbs))


def scan_flavors(flavors: list[Flavor], *, account: str | None = None,
                 progress: Callable[[Flavor, int, int, str], None] | None = None) -> ScanResult:
    scans = []
    for flavor in flavors:
        report = None if progress is None else (lambda i, n, label, f=flavor: progress(f, i, n, label))
        scans.append(scan_flavor(flavor, account=account, progress=report))
    return ScanResult(scans)
```

Notes:
- Check the real field names on `capture_events()`'s records in `core/events.py`. The test reads `e["event"]`;
  use whatever key the existing tests use (for example `tests/test_events.py`).
- `Flavor.accounts(on_error)` and `Account.characters(on_error)` take the `ErrorHandler` signature from
  `core/install.py`. If it isn't `(Path, OSError)`, adapt `on_error`.
- A look-alike is logged at debug level only; it is not a user-facing warning.

- [ ] **Step 5: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_scanner`, then `-k fixtures`, `-k wtf`, `-k look_and_feel` (the fixture
must not disturb other tools' trees).
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures.py tests/test_ace_scanner.py wowtools/tools/ace_profiles/scanner.py
git commit -m "feat(ace-profiles): scanner and AceDB fixture tree"
```

---

### Task 6: `ops.py`: staging (the operations on a byte-free model)

**Files:**
- Create: `wowtools/tools/ace_profiles/ops.py`
- Test: `tests/test_ace_ops.py`

**Interfaces:**
- Consumes: `scanner.ScanResult`, `SvFile`, `AccountScan`; `model.AceDb`, `DEFAULT`.
- Produces (all in `ops`):
  - `@dataclass(frozen=True) DbKey(path: Path, sv_name: str)`.
  - `@dataclass(frozen=True) Original(name: str)`, `@dataclass(frozen=True) CopyOf(name: str)` (`name` is
    always an original profile name of that database).
  - `@dataclass DbState(key: DbKey, file: SvFile, db: AceDb, leftovers: frozenset[str], keys: dict[str, str | None],
    profiles: dict[str, Original | CopyOf], lds: dict[tuple[str, int], str])` with `fresh(file, db, leftovers)`
    (classmethod), `users(name) -> list[str]`, `names() -> list[str]`, `exists(name) -> bool`,
    `missing(name) -> bool`, `changes() -> Changes`, `changed -> bool` (property).
  - `@dataclass Changes(deleted: list[str], renamed: list[tuple[str, str]], copied: list[tuple[str, str]],
    reassigned: list[tuple[str, str, str]], removed: list[str], lds: list[tuple[str, int, str, str]])` with
    `.count -> int` and `.lines() -> list[str]`.
  - `@dataclass OpResult(applied: list[DbKey], refused: list[tuple[DbKey, str]], notes: list[str])` with
    `.ok -> bool` (`applied` non-empty).
  - `@dataclass Summary(deleted, renamed, copied, reassigned, removed, lds, files: int)` with `.total -> int`.
  - `valid_name(name: str) -> str | None` (the error, or None).
  - `class Staging(states: dict[DbKey, DbState], locked: Callable[[str], bool])` with
    `from_scan(scan: ScanResult, *, locked=lambda addon: False) -> Staging` (classmethod), `state(key)`,
    `delete(selection: dict[DbKey, list[str]], target: str) -> OpResult`,
    `assign(selection: dict[DbKey, list[str]], target: str) -> OpResult`,
    `rename(key, old, new) -> OpResult`, `copy(key, source, new) -> OpResult`,
    `remove_leftovers(selection: dict[DbKey, list[str]]) -> OpResult`,
    `keep_only_default(keys: list[DbKey]) -> OpResult`, `everyone_to_default(keys: list[DbKey]) -> OpResult`,
    `discard() -> None`, `changed() -> list[DbState]`, `summary() -> Summary`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ace_ops.py
"""ops: staging changes on the byte-free model (spec §7)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import ops, scanner
from wowtools.tools.ace_profiles.ops import CopyOf, DbKey, Original


class OpsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_ace_tree(Path(tmp.name) / "wow")
        self.scan = scanner.ScanResult([scanner.scan_flavor(WowInstall(root).flavor("_retail_"), account="ACCT1")])
        self.staging = ops.Staging.from_scan(self.scan)

    def key(self, sv_name):
        return next(k for k in self.staging.states if k.sv_name == sv_name)

    def st(self, sv_name):
        return self.staging.state(self.key(sv_name))

    def test_fresh_state_is_unchanged(self):
        state = self.st("KickCDDB")
        self.assertFalse(state.changed)
        self.assertEqual(state.names(), ["Default", "Backup"])
        self.assertEqual(state.leftovers, frozenset({"Gone - Realm1"}))
        self.assertEqual(self.staging.summary().total, 0)

    def test_delete_reassigns_users_to_target(self):
        k = self.key("ElvDB")
        result = self.staging.delete({k: ["Healer"]}, "Default")
        self.assertTrue(result.ok)
        state = self.st("ElvDB")
        self.assertEqual(state.names(), ["Default"])
        self.assertEqual(state.keys["Mierin - Khaz Modan"], "Default")
        self.assertEqual(state.lds[("Kaelys - Realm1", 2)], "Default")
        changes = state.changes()
        self.assertEqual(changes.deleted, ["Healer"])
        self.assertEqual(changes.reassigned, [("Mierin - Khaz Modan", "Healer", "Default")])
        self.assertEqual(changes.lds, [("Kaelys - Realm1", 2, "Healer", "Default")])

    def test_delete_refuses_target_in_selection(self):
        k = self.key("ElvDB")
        result = self.staging.delete({k: ["Default", "Healer"]}, "Default")
        self.assertFalse(result.ok)
        self.assertEqual(result.refused[0][0], k)
        self.assertFalse(self.st("ElvDB").changed)

    def test_delete_to_a_missing_target_notes_it(self):
        k = self.key("HandyNotesDB")
        result = self.staging.delete({k: ["Kaelys - Realm1"]}, "Default")
        self.assertTrue(result.ok)
        self.assertTrue(any("next login" in n for n in result.notes))
        self.assertTrue(self.st("HandyNotesDB").missing("Default"))

    def test_assign_and_noop(self):
        k = self.key("HandyNotesDB")
        self.staging.assign({k: ["Kaelys - Realm1"]}, "Unused - Realm1")
        state = self.st("HandyNotesDB")
        self.assertEqual(state.users("Unused - Realm1"), ["Kaelys - Realm1"])
        self.staging.assign({k: ["Kaelys - Realm1"]}, "Kaelys - Realm1")
        self.assertFalse(self.st("HandyNotesDB").changed)

    def test_rename_moves_users_and_keeps_order(self):
        k = self.key("ElvDB")
        self.assertTrue(self.staging.rename(k, "Healer", "Heals").ok)
        state = self.st("ElvDB")
        self.assertEqual(state.names(), ["Default", "Heals"])
        self.assertEqual(state.profiles["Heals"], Original("Healer"))
        self.assertEqual(state.keys["Mierin - Khaz Modan"], "Heals")
        self.assertEqual(state.lds[("Kaelys - Realm1", 2)], "Heals")
        self.assertEqual(state.changes().renamed, [("Healer", "Heals")])

    def test_rename_refusals(self):
        k = self.key("ElvDB")
        self.assertFalse(self.staging.rename(k, "Healer", "Default").ok)
        self.assertFalse(self.staging.rename(k, "Nope", "X").ok)
        self.assertFalse(self.staging.rename(k, "Healer", "").ok)
        self.assertFalse(self.staging.rename(k, "Healer", "bad\nname").ok)

    def test_rename_missing_profile_only_moves_users(self):
        k = self.key("StockDB")
        self.assertTrue(self.staging.rename(k, "Gone", "Default").ok)
        state = self.st("StockDB")
        self.assertEqual(state.keys["Kaelys - Realm1"], "Default")
        self.assertEqual(state.profiles, {})

    def test_copy_then_rename_then_delete_source(self):
        k = self.key("ElvDB")
        self.assertTrue(self.staging.copy(k, "Healer", "Healer copy").ok)
        self.assertTrue(self.staging.rename(k, "Healer copy", "Tank").ok)
        self.assertTrue(self.staging.delete({k: ["Healer"]}, "Tank").ok)
        state = self.st("ElvDB")
        self.assertEqual(state.profiles, {"Default": Original("Default"), "Tank": CopyOf("Healer")})
        self.assertEqual(state.keys["Mierin - Khaz Modan"], "Tank")
        changes = state.changes()
        self.assertEqual(changes.deleted, ["Healer"])
        self.assertEqual(changes.copied, [("Healer", "Tank")])

    def test_copy_refusals(self):
        k = self.key("StockDB")
        self.assertFalse(self.staging.copy(k, "Gone", "X").ok)  # missing: no data to copy
        k = self.key("ElvDB")
        self.assertFalse(self.staging.copy(k, "Healer", "Default").ok)

    def test_remove_leftovers_only_removes_leftovers(self):
        k = self.key("KickCDDB")
        result = self.staging.remove_leftovers({k: ["Gone - Realm1", "Kaelys - Realm1"]})
        state = self.st("KickCDDB")
        self.assertIsNone(state.keys["Gone - Realm1"])
        self.assertEqual(state.keys["Kaelys - Realm1"], "Default")
        self.assertEqual(state.changes().removed, ["Gone - Realm1"])
        self.assertTrue(result.notes)

    def test_quick_actions(self):
        keys = [self.key("HandyNotesDB"), self.key("ElvDB")]
        self.staging.everyone_to_default(keys)
        self.assertEqual(set(self.st("HandyNotesDB").keys.values()), {"Default"})
        self.staging.keep_only_default(keys)
        self.assertEqual(self.st("HandyNotesDB").names(), ["Default"])
        self.assertEqual(self.st("ElvDB").names(), ["Default"])

    def test_locked_addon_is_refused(self):
        staging = ops.Staging.from_scan(self.scan, locked=lambda addon: addon == "ElvUI")
        k = next(k for k in staging.states if k.sv_name == "ElvDB")
        result = staging.delete({k: ["Healer"]}, "Default")
        self.assertFalse(result.ok)
        self.assertIn("blacklisted", result.refused[0][1])

    def test_summary_and_discard(self):
        self.staging.delete({self.key("ElvDB"): ["Healer"]}, "Default")
        self.staging.remove_leftovers({self.key("KickCDDB"): ["Gone - Realm1"]})
        summary = self.staging.summary()
        self.assertEqual((summary.deleted, summary.reassigned, summary.removed, summary.lds, summary.files),
                         (1, 1, 1, 1, 2))
        self.assertEqual(summary.total, 4)
        self.staging.discard()
        self.assertEqual(self.staging.summary().total, 0)

    def test_change_lines(self):
        k = self.key("ElvDB")
        self.staging.rename(k, "Healer", "Heals")
        self.assertIn('rename profile "Healer" to "Heals"', self.st("ElvDB").changes().lines())

    def test_valid_name(self):
        self.assertIsNone(ops.valid_name("My \"Main\" - x"))
        for bad in ("", "   ", "a\tb", "x" * 101):
            with self.subTest(bad=bad):
                self.assertIsNotNone(ops.valid_name(bad))
```

- [ ] **Step 2: Run to see it fail**

Run: `python3 scripts/run_tests.py -k ace_ops`. Expected: ImportError.

- [ ] **Step 3: Implement `ops.py`**

```python
"""Staged changes to AceDB databases, on a byte-free model (spec §7). UI-free.

Each database gets a DbState: the staged profileKeys mapping (None = entry removed), the staged profile table
(name -> Original(name in the file) or CopyOf(original name)) and the staged LibDualSpec spec values. Operations
only change these; compile_file() (Task 7) turns them into byte edits. Changes() is always the difference from the
file, so operations compose and discard() is just a reset.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.tools.ace_profiles.model import DEFAULT, AceDb
from wowtools.tools.ace_profiles.scanner import ScanResult, SvFile

MAX_NAME = 100
CREATED_AT_LOGIN = "will be created by the addon at its next login, with its defaults"


@dataclass(frozen=True)
class DbKey:
    path: Path
    sv_name: str


@dataclass(frozen=True)
class Original:
    name: str


@dataclass(frozen=True)
class CopyOf:
    name: str


Source = Original | CopyOf


def valid_name(name: str) -> str | None:
    if not name or not name.strip():
        return "A profile name can't be empty."
    if len(name) > MAX_NAME:
        return f"A profile name can be at most {MAX_NAME} characters."
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        return "A profile name can't contain tabs, new lines or other control characters."
    return None


@dataclass
class Changes:
    deleted: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    copied: list[tuple[str, str]] = field(default_factory=list)
    reassigned: list[tuple[str, str, str]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    lds: list[tuple[str, int, str, str]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return (len(self.deleted) + len(self.renamed) + len(self.copied) + len(self.reassigned)
                + len(self.removed) + len(self.lds))

    def lines(self) -> list[str]:
        out = [f'delete profile "{n}"' for n in self.deleted]
        out += [f'rename profile "{a}" to "{b}"' for a, b in self.renamed]
        out += [f'copy profile "{a}" as "{b}"' for a, b in self.copied]
        out += [f'"{c}": "{a}" to "{b}"' for c, a, b in self.reassigned]
        out += [f'remove leftover character "{c}"' for c in self.removed]
        out += [f'"{c}" spec {i} (LibDualSpec): "{a}" to "{b}"' for c, i, a, b in self.lds]
        return out


@dataclass
class DbState:
    key: DbKey
    file: SvFile
    db: AceDb
    leftovers: frozenset[str]
    keys: dict[str, str | None]
    profiles: dict[str, Source]
    lds: dict[tuple[str, int], str]

    @classmethod
    def fresh(cls, file: SvFile, db: AceDb, leftovers: frozenset[str]) -> DbState:
        return cls(DbKey(file.path, db.sv_name), file, db, leftovers, dict(db.profile_keys),
                   {name: Original(name) for name in db.profiles},
                   {(c, i): f.value.value for c, entry in db.lds.items() for i, f in entry.specs.items()})

    def users(self, name: str) -> list[str]:
        return [c for c, p in self.keys.items() if p == name]

    def names(self) -> list[str]:
        referenced = sorted({p for p in self.keys.values() if p is not None and p not in self.profiles})
        return list(self.profiles) + referenced

    def exists(self, name: str) -> bool:
        return name in self.profiles

    def missing(self, name: str) -> bool:
        return name not in self.profiles and name in self.keys.values()

    def changes(self) -> Changes:
        out = Changes()
        placed = {src.name: name for name, src in self.profiles.items() if isinstance(src, Original)}
        for name in self.db.profiles:
            if name not in placed:
                out.deleted.append(name)
            elif placed[name] != name:
                out.renamed.append((name, placed[name]))
        out.copied = [(src.name, name) for name, src in self.profiles.items() if isinstance(src, CopyOf)]
        for char, old in self.db.profile_keys.items():
            new = self.keys.get(char)
            if new is None:
                out.removed.append(char)
            elif new != old:
                out.reassigned.append((char, old, new))
        for (char, spec), new in self.lds.items():
            old = self.db.lds[char].specs[spec].value.value
            if new != old:
                out.lds.append((char, spec, old, new))
        return out

    @property
    def changed(self) -> bool:
        return self.changes().count > 0

    def _move_users(self, old: str, new: str) -> None:
        for char, profile in self.keys.items():
            if profile == old:
                self.keys[char] = new
        for spot, profile in self.lds.items():
            if profile == old:
                self.lds[spot] = new


@dataclass
class OpResult:
    applied: list[DbKey] = field(default_factory=list)
    refused: list[tuple[DbKey, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.applied)


@dataclass
class Summary:
    deleted: int = 0
    renamed: int = 0
    copied: int = 0
    reassigned: int = 0
    removed: int = 0
    lds: int = 0
    files: int = 0

    @property
    def total(self) -> int:
        return self.deleted + self.renamed + self.copied + self.reassigned + self.removed + self.lds


class Staging:
    def __init__(self, states: dict[DbKey, DbState], locked: Callable[[str], bool] = lambda addon: False) -> None:
        self.states = states
        self.locked = locked

    @classmethod
    def from_scan(cls, scan: ScanResult, *, locked: Callable[[str], bool] = lambda addon: False) -> Staging:
        states: dict[DbKey, DbState] = {}
        for flavor in scan.flavors:
            for account in flavor.accounts:
                for addon_file in account.files:
                    for db in addon_file.dbs:
                        leftovers = frozenset(c for c in db.profile_keys if account.is_leftover(c))
                        state = DbState.fresh(addon_file.file, db, leftovers)
                        states[state.key] = state
        return cls(states, locked)

    def state(self, key: DbKey) -> DbState:
        return self.states[key]

    def _refuse_locked(self, key: DbKey, result: OpResult) -> bool:
        state = self.states[key]
        if self.locked(state.file.addon):
            result.refused.append((key, f"{state.file.addon} is blacklisted (press u to unlock it)"))
            return True
        return False

    def _each(self, keys: Iterable[DbKey], result: OpResult, apply: Callable[[DbState], str | None],
              operation: str) -> OpResult:
        for key in keys:
            if self._refuse_locked(key, result):
                continue
            problem = apply(self.states[key])
            if problem is None:
                result.applied.append(key)
            else:
                result.refused.append((key, problem))
        log_event("ace.staged", operation=operation, applied=len(result.applied), refused=len(result.refused))
        return result

    def delete(self, selection: dict[DbKey, list[str]], target: str) -> OpResult:
        result = OpResult()
        problem = valid_name(target)
        if problem is not None:
            result.refused = [(key, problem) for key in selection]
            return result

        def apply(state: DbState) -> str | None:
            names = [n for n in selection[state.key] if n in state.names()]
            if target in names:
                return f'"{target}" is being deleted itself; choose another profile for its characters'
            if not names:
                return "none of those profiles is in this database any more"
            for name in names:
                state.profiles.pop(name, None)
                state._move_users(name, target)
            if not state.exists(target) and state.users(target):
                result.notes.append(f'{state.file.addon}: "{target}" {CREATED_AT_LOGIN}.')
            return None
        return self._each(selection, result, apply, "delete")

    def assign(self, selection: dict[DbKey, list[str]], target: str) -> OpResult:
        result = OpResult()
        problem = valid_name(target)
        if problem is not None:
            result.refused = [(key, problem) for key in selection]
            return result

        def apply(state: DbState) -> str | None:
            chars = [c for c in selection[state.key] if state.keys.get(c) is not None]
            if not chars:
                return "none of those characters is in this database any more"
            for char in chars:
                state.keys[char] = target
            if not state.exists(target):
                result.notes.append(f'{state.file.addon}: "{target}" {CREATED_AT_LOGIN}.')
            if any(state.db.lds_enabled(c) for c in chars):
                result.notes.append(f"{state.file.addon}: LibDualSpec switches the profile by spec for some of "
                                    f"these characters; it will override this at login.")
            return None
        return self._each(selection, result, apply, "assign")

    def rename(self, key: DbKey, old: str, new: str) -> OpResult:
        result = OpResult()

        def apply(state: DbState) -> str | None:
            if old not in state.names():
                return f'"{old}" is not a profile of this database'
            problem = valid_name(new)
            if problem is not None:
                return problem
            if new in state.names():
                return f'"{new}" is already a profile of this database'
            if old in state.profiles:
                state.profiles = {(new if name == old else name): src for name, src in state.profiles.items()}
            state._move_users(old, new)
            return None
        return self._each([key], result, apply, "rename")

    def copy(self, key: DbKey, source: str, new: str) -> OpResult:
        result = OpResult()

        def apply(state: DbState) -> str | None:
            if source not in state.profiles:
                return f'"{source}" has no data in the file to copy'
            problem = valid_name(new)
            if problem is not None:
                return problem
            if new in state.names():
                return f'"{new}" is already a profile of this database'
            state.profiles[new] = CopyOf(state.profiles[source].name)
            return None
        return self._each([key], result, apply, "copy")

    def remove_leftovers(self, selection: dict[DbKey, list[str]]) -> OpResult:
        result = OpResult()

        def apply(state: DbState) -> str | None:
            chars = [c for c in selection[state.key] if c in state.leftovers and state.keys.get(c) is not None]
            skipped = [c for c in selection[state.key] if c not in state.leftovers]
            if skipped:
                result.notes.append(f"{state.file.addon}: {len(skipped)} character(s) have a folder in WTF and "
                                    f"were kept.")
            if not chars:
                return "no leftover characters selected here"
            for char in chars:
                state.keys[char] = None
            return None
        return self._each(selection, result, apply, "remove_leftovers")

    def keep_only_default(self, keys: list[DbKey]) -> OpResult:
        selection = {k: [n for n in self.states[k].names() if n != DEFAULT] for k in keys}
        selection = {k: names for k, names in selection.items() if names}
        return self.delete(selection, DEFAULT)

    def everyone_to_default(self, keys: list[DbKey]) -> OpResult:
        return self.assign({k: [c for c, p in self.states[k].keys.items() if p is not None] for k in keys},
                           DEFAULT)

    def discard(self) -> None:
        for key, state in self.states.items():
            self.states[key] = DbState.fresh(state.file, state.db, state.leftovers)

    def changed(self) -> list[DbState]:
        return [state for state in self.states.values() if state.changed]

    def summary(self) -> Summary:
        out = Summary()
        files = set()
        for state in self.states.values():
            changes = state.changes()
            if not changes.count:
                continue
            files.add(state.file.path)
            out.deleted += len(changes.deleted)
            out.renamed += len(changes.renamed)
            out.copied += len(changes.copied)
            out.reassigned += len(changes.reassigned)
            out.removed += len(changes.removed)
            out.lds += len(changes.lds)
        out.files = len(files)
        return out
```

Notes:
- `everyone_to_default` on a database where every character already uses "Default" stages nothing. It still counts
  as applied: assign is a no-op there. Leave it like that.
- In `delete`, a database where `names` would include the target is refused as a whole.
  `test_delete_refuses_target_in_selection` pins that.

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_ops`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools/ace_profiles/ops.py tests/test_ace_ops.py
git commit -m "feat(ace-profiles): staged operations"
```

---

### Task 7: compile staged changes to byte edits, and verify them

**Files:**
- Modify: `wowtools/tools/ace_profiles/ops.py` (add `Expected`, `FileEdit`, `compile_file`)
- Create: `wowtools/tools/ace_profiles/verify.py`
- Test: `tests/test_ace_compile.py`

**Interfaces:**
- Consumes: `luasv.splice`, `encode_string`, `newline_of`, `line_start`, `Table`, `Field`; `DbState`.
- Produces:
  - `ops.Expected(profile_keys: dict[str, str], profiles: dict[str, bytes], namespaces: dict[str, dict[str, bytes]],
    lds: dict[str, dict[int, str]])`.
  - `ops.FileEdit(file: SvFile, data: bytes, changes: list[str], expected: dict[str, Expected])`.
  - `ops.compile_file(states: list[DbState], data: bytes) -> FileEdit`. `states` are the changed states of one
    file. `data` must be the file's bytes as scanned; the caller checks the SHA-256.
  - `verify.verify_edit(edit: FileEdit, old: bytes) -> list[str]` (problems; empty means good).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ace_compile.py
"""compile_file + verify_edit: staged changes become exact byte edits (spec §8)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import luasv, model, ops, scanner, verify


class CompileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_ace_tree(Path(tmp.name) / "wow")
        self.scan = scanner.ScanResult([scanner.scan_flavor(WowInstall(root).flavor("_retail_"), account="ACCT1")])
        self.staging = ops.Staging.from_scan(self.scan)

    def key(self, sv_name):
        return next(k for k in self.staging.states if k.sv_name == sv_name)

    def compile(self, sv_name):
        key = self.key(sv_name)
        states = [s for s in self.staging.states.values() if s.file.path == key.path and s.changed]
        data = key.path.read_bytes()
        edit = ops.compile_file(states, data)
        self.assertEqual(verify.verify_edit(edit, data), [])
        return data, edit

    def reparse(self, data, sv_name):
        dbs, _ = model.find_dbs(luasv.parse(data, model.ace_descend), data)
        return next(db for db in dbs if db.sv_name == sv_name)

    def test_no_change_is_byte_identical(self):
        key = self.key("KickCDDB")
        data = key.path.read_bytes()
        edit = ops.compile_file([], data)
        self.assertEqual(edit.data, data)
        self.assertEqual(verify.verify_edit(edit, data), [])

    def test_one_reassign_changes_exactly_one_span(self):
        self.staging.assign({self.key("ElvDB"): ["Kaelys - Realm1"]}, "Healer")
        old, edit = self.compile("ElvDB")
        self.assertEqual(edit.data, old.replace(b'["Kaelys - Realm1"] = "Default",\r\n["Mierin',
                                                b'["Kaelys - Realm1"] = "Healer",\r\n["Mierin', 1))
        self.assertEqual(edit.changes, ['ElvDB: "Kaelys - Realm1": "Default" to "Healer"'])

    def test_delete_removes_main_and_namespace_entries_and_fixes_lds(self):
        self.staging.delete({self.key("ElvDB"): ["Healer"]}, "Default")
        old, edit = self.compile("ElvDB")
        db = self.reparse(edit.data, "ElvDB")
        self.assertEqual(list(db.profiles), ["Default"])
        self.assertEqual(list(db.namespaces["Bags"].entries), ["Default"])
        self.assertEqual(db.profile_keys["Mierin - Khaz Modan"], "Default")
        self.assertEqual(db.lds["Kaelys - Realm1"].specs[2].value.value, "Default")
        self.assertNotIn(b'["Healer"]', edit.data)
        private_old = old[old.index(b"ElvPrivateDB"):]
        self.assertTrue(edit.data.endswith(private_old))  # the other database is byte-identical

    def test_rename_rewrites_keys_everywhere(self):
        self.staging.rename(self.key("ElvDB"), "Healer", 'My "Heals"')
        _, edit = self.compile("ElvDB")
        self.assertIn(b'["My \\"Heals\\""] = {', edit.data)
        db = self.reparse(edit.data, "ElvDB")
        self.assertEqual(list(db.profiles), ["Default", 'My "Heals"'])
        self.assertEqual(list(db.namespaces["Bags"].entries), ["Default", 'My "Heals"'])

    def test_copy_inserts_verbatim_bytes_in_main_and_namespaces(self):
        self.staging.copy(self.key("ElvDB"), "Healer", "Tank")
        old, edit = self.compile("ElvDB")
        db = self.reparse(edit.data, "ElvDB")
        new_value = db.profiles["Tank"].field.value
        old_db = self.reparse(old, "ElvDB")
        source = old_db.profiles["Healer"].field.value
        self.assertEqual(edit.data[new_value.start:new_value.end], old[source.start:source.end])
        self.assertIn("Tank", db.namespaces["Bags"].entries)
        self.assertIn(b'["Tank"] = {\r\n["x"] = 2,\r\n},\r\n}', edit.data)

    def test_composed_copy_rename_delete(self):
        k = self.key("ElvDB")
        self.staging.copy(k, "Healer", "A")
        self.staging.rename(k, "A", "C")
        self.staging.delete({k: ["Healer"]}, "C")
        old, edit = self.compile("ElvDB")
        db = self.reparse(edit.data, "ElvDB")
        self.assertEqual(list(db.profiles), ["Default", "C"])
        self.assertEqual(db.profile_keys["Mierin - Khaz Modan"], "C")
        old_db = self.reparse(old, "ElvDB")
        src = old_db.profiles["Healer"].field.value
        new = db.profiles["C"].field.value
        self.assertEqual(edit.data[new.start:new.end], old[src.start:src.end])

    def test_remove_leftover_removes_the_line(self):
        self.staging.remove_leftovers({self.key("KickCDDB"): ["Gone - Realm1"]})
        old, edit = self.compile("KickCDDB")
        self.assertEqual(edit.data, old.replace(b'["Gone - Realm1"] = "Default",\r\n', b"", 1))

    def test_untouched_bytes_survive(self):
        self.staging.delete({self.key("KickCDDB"): ["Backup"]}, "Default")
        _, edit = self.compile("KickCDDB")
        self.assertIn(b'["scale"] = 0.6000000000000001,\r\n["text"] = "a\\"b\\\\c\\n\\000",\r\n[114052] = true,',
                      edit.data)
        self.assertIn(b'KickCDPerfDB = {\r\n["runs"] = 3,\r\n}', edit.data)
        self.assertIn(b'["schemaVersion"] = 3,', edit.data)

    def test_two_databases_in_one_file(self):
        self.staging.everyone_to_default([self.key("HandyNotesDB")])
        self.staging.copy(self.key("HandyNotes_MapNotesDB"), "Default", "Spare")
        _, edit = self.compile("HandyNotesDB")
        self.assertEqual(set(edit.expected), {"HandyNotesDB", "HandyNotes_MapNotesDB"})

    def test_copy_into_a_table_without_trailing_comma(self):
        data = b'X = {\n["profileKeys"] = {\n["A - R"] = "P"\n},\n["profiles"] = { ["P"] = { ["v"] = 1 } }\n}\n'
        path = Path(self.scan.flavors[0].flavor.account_dir / "ACCT1" / "SavedVariables" / "X.lua")
        path.write_bytes(data)
        dbs, _ = model.find_dbs(luasv.parse(data, model.ace_descend), data)
        file = scanner.SvFile(path, self.scan.flavors[0].flavor, "ACCT1", None, len(data), 0.0,
                              scanner.sha256_of(data))
        state = ops.DbState.fresh(file, dbs[0], frozenset())
        staging = ops.Staging({state.key: state})
        staging.copy(state.key, "P", "Q")
        edit = ops.compile_file([state], data)
        self.assertEqual(verify.verify_edit(edit, data), [])
        self.assertEqual(list(self.reparse(edit.data, "X").profiles), ["P", "Q"])


class VerifyTest(unittest.TestCase):
    def test_catches_a_wrong_mapping_and_a_changed_neighbour(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_ace_tree(Path(tmp.name) / "wow")
        scan = scanner.ScanResult([scanner.scan_flavor(WowInstall(root).flavor("_retail_"), account="ACCT1")])
        staging = ops.Staging.from_scan(scan)
        key = next(k for k in staging.states if k.sv_name == "KickCDDB")
        staging.assign({key: ["Kaelys - Realm1"]}, "Backup")
        data = key.path.read_bytes()
        edit = ops.compile_file([staging.state(key)], data)
        bad = ops.FileEdit(edit.file, edit.data.replace(b'"Backup",', b'"Other",', 1), edit.changes, edit.expected)
        self.assertTrue(verify.verify_edit(bad, data))
        bad = ops.FileEdit(edit.file, edit.data.replace(b'["runs"] = 3', b'["runs"] = 4'), edit.changes, edit.expected)
        self.assertTrue(any("KickCDPerfDB" in p for p in verify.verify_edit(bad, data)))
        bad = ops.FileEdit(edit.file, edit.data.replace(b'["schemaVersion"] = 3', b'["schemaVersion"] = 9'),
                           edit.changes, edit.expected)
        self.assertTrue(any("global" in p for p in verify.verify_edit(bad, data)))
        bad = ops.FileEdit(edit.file, edit.data[:-10], edit.changes, edit.expected)
        self.assertTrue(verify.verify_edit(bad, data))
```

- [ ] **Step 2: Run to see it fail**

Run: `python3 scripts/run_tests.py -k ace_compile`. Expected: AttributeError / ImportError.

- [ ] **Step 3: Implement**

Append to `ops.py`. Add `from wowtools.tools.ace_profiles.luasv import Field, Table, encode_string, line_start,
newline_of, splice` to the imports, keeping them sorted.

```python
@dataclass
class Expected:
    """What a database must read back as after the edit (verify.verify_edit)."""
    profile_keys: dict[str, str]
    profiles: dict[str, bytes]
    namespaces: dict[str, dict[str, bytes]]
    lds: dict[str, dict[int, str]]


@dataclass
class FileEdit:
    file: SvFile
    data: bytes
    changes: list[str]
    expected: dict[str, Expected]


def _table_edits(data: bytes, table: Table | None, entries: dict[str, Field], staged: dict[str, Source],
                 nl: bytes) -> tuple[list[tuple[int, int, bytes]], dict[str, bytes]]:
    """Edits that turn this profiles table into the staged one, and the expected {name: value bytes}."""
    if table is None:
        return [], {}
    edits: list[tuple[int, int, bytes]] = []
    placed = {src.name: name for name, src in staged.items() if isinstance(src, Original)}
    for original, item in entries.items():
        if original not in placed:
            edits.append((item.remove_span[0], item.remove_span[1], b""))
        elif placed[original] != original:
            edits.append((item.key_span[0], item.key_span[1], b"[" + encode_string(placed[original]) + b"]"))
    expected = {}
    for name, src in staged.items():
        item = entries.get(src.name)
        if item is not None:
            expected[name] = data[item.value.start:item.value.end]
    inserts = [b"[" + encode_string(name) + b"] = " + expected[name] + b"," + nl
               for name, src in staged.items() if isinstance(src, CopyOf) and name in expected]
    if inserts:
        kept = [item for name, item in entries.items() if name in placed]
        last = kept[-1] if kept else None
        if last is not None and data[last.entry_end - 1:last.entry_end] not in (b",", b";"):
            edits.append((last.value.end, last.value.end, b","))
        at = line_start(data, table.close)
        if data[at:table.close].strip(b" \t"):
            edits.append((table.close, table.close, nl + b"".join(inserts)))
        else:
            edits.append((at, at, b"".join(inserts)))
    return edits, expected


def compile_file(states: list[DbState], data: bytes) -> FileEdit:
    """Byte edits for every changed database of one file, applied in one splice."""
    nl = newline_of(data)
    edits: list[tuple[int, int, bytes]] = []
    changes: list[str] = []
    expected: dict[str, Expected] = {}
    file = states[0].file if states else None
    for state in states:
        db = state.db
        for char, item in db.key_fields.items():
            new = state.keys.get(char)
            if new is None:
                edits.append((item.remove_span[0], item.remove_span[1], b""))
            elif new != db.profile_keys[char]:
                edits.append((item.value.start, item.value.end, encode_string(new)))
        main_edits, main_expected = _table_edits(
            data, db.profiles_table, {n: e.field for n, e in db.profiles.items()}, state.profiles, nl)
        edits += main_edits
        namespaces = {}
        for ns in db.namespaces.values():
            ns_edits, namespaces[ns.name] = _table_edits(data, ns.table, ns.entries, state.profiles, nl)
            edits += ns_edits
        lds: dict[str, dict[int, str]] = {}
        for (char, spec), new in state.lds.items():
            item = db.lds[char].specs[spec]
            if new != item.value.value:
                edits.append((item.value.start, item.value.end, encode_string(new)))
            lds.setdefault(char, {})[spec] = new
        expected[db.sv_name] = Expected({c: p for c, p in state.keys.items() if p is not None}, main_expected,
                                        namespaces, lds)
        changes += [f"{db.sv_name}: {line}" for line in state.changes().lines()]
    return FileEdit(file, splice(data, edits), changes, expected)
```

`verify.py`:

```python
"""Re-read an edited SavedVariables file and check it says exactly what was staged (spec §8.2). UI-free."""
from __future__ import annotations

from wowtools.tools.ace_profiles.luasv import Chunk, LuaParseError, Table, parse
from wowtools.tools.ace_profiles.model import ace_descend, find_dbs
from wowtools.tools.ace_profiles.ops import FileEdit

PROFILE_SECTIONS = ("profileKeys", "profiles", "namespaces")


def _gaps(data: bytes, chunk: Chunk) -> list[bytes]:
    """The bytes between and around the top-level assignments (blank lines, comments)."""
    out, pos = [], 0
    for item in chunk.assignments:
        out.append(data[pos:item.start])
        pos = item.end
    out.append(data[pos:])
    return out


def _other_sections(data: bytes, table: Table) -> dict:
    return {f.key: data[f.value.start:f.value.end] for f in table.fields if f.key not in PROFILE_SECTIONS}


def verify_edit(edit: FileEdit, old: bytes) -> list[str]:
    try:
        new_chunk = parse(edit.data, ace_descend)
    except LuaParseError as exc:
        return [f"the edited file does not read back: {exc}"]
    old_chunk = parse(old, ace_descend)
    problems: list[str] = []
    if [a.name for a in new_chunk.assignments] != [a.name for a in old_chunk.assignments]:
        return ["the edited file does not hold the same SavedVariables"]
    if _gaps(edit.data, new_chunk) != _gaps(old, old_chunk):
        problems.append("text between the SavedVariables changed")
    for before, after in zip(old_chunk.assignments, new_chunk.assignments):
        if before.name in edit.expected:
            if isinstance(before.value, Table) and isinstance(after.value, Table):
                old_other, new_other = _other_sections(old, before.value), _other_sections(edit.data, after.value)
                for key in sorted(set(old_other) | set(new_other), key=str):
                    if old_other.get(key) != new_other.get(key):
                        problems.append(f"{before.name}: section {key} changed")
            continue
        if old[before.start:before.end] != edit.data[after.start:after.end]:
            problems.append(f"{before.name} changed but nothing was staged for it")
    dbs = {db.sv_name: db for db in find_dbs(new_chunk, edit.data)[0]}
    for name, expected in edit.expected.items():
        db = dbs.get(name)
        if db is None:
            problems.append(f"{name} no longer reads as an AceDB database")
            continue
        if db.profile_keys != expected.profile_keys:
            problems.append(f"{name}: the character to profile mapping is not what was staged")
        got = {n: edit.data[e.field.value.start:e.field.value.end] for n, e in db.profiles.items()}
        if got != expected.profiles:
            problems.append(f"{name}: the profiles are not what was staged")
        for ns_name, ns_expected in expected.namespaces.items():
            ns = db.namespaces.get(ns_name)
            ns_got = {} if ns is None else {n: edit.data[f.value.start:f.value.end] for n, f in ns.entries.items()}
            if ns_got != ns_expected:
                problems.append(f"{name}: module {ns_name}'s profiles are not what was staged")
        lds = {c: {i: f.value.value for i, f in entry.specs.items()} for c, entry in db.lds.items()}
        if {c: lds.get(c) for c in expected.lds} != expected.lds:
            problems.append(f"{name}: LibDualSpec spec profiles are not what was staged")
    return problems
```

Note: `ops.compile_file([], data)` returns `FileEdit(None, data, [], {})`. Type the `file` field as
`SvFile | None`.

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_compile`, then `-k ace`.
Expected: all pass.

- [ ] **Step 5: Commit and push milestone 1**

```bash
git add wowtools/tools/ace_profiles tests/test_ace_compile.py
git commit -m "feat(ace-profiles): compile staged changes to span edits and verify them"
git push -u origin feat/ace-profiles
```

---
## Milestone 2: writing safely (Tasks 8–10), push after Task 10

### Task 8: journal and `editor.py` (Apply, dry run, crash marker, roll-back)

**Files:**
- Create: `wowtools/tools/ace_profiles/journal.py`, `wowtools/tools/ace_profiles/editor.py`
- Test: `tests/test_ace_journal.py`, `tests/test_ace_editor.py`

**Interfaces:**
- Consumes: `core.journal` (`JournalWriter`, `read_journal`, `latest_undoable`, `prune_journals`, `journal_dir`,
  `now_iso`); `core.snapshot.take_snapshot`, `prune_snapshots`; `core.svfiles` (`SvGuard`, `SvFileError`,
  `probe_lock`, `recover_probe_leftovers`, `lstat_or_none`); `core.backup` (`BackupEntry`, `BackupError`,
  `create_backup`); `core.fsutil` (`atomic_write_bytes`, `free_name`, `remove_quietly`, `safe_progress`);
  `ops.compile_file`, `DbState`; `verify.verify_edit`; `scanner.sha256_of`, `SvFile`.
- Produces:
  - `journal.A_EDITED = "edited"`, `A_ROLLED_BACK = "rolled_back"`,
    `class ProfileJournal(JournalWriter)` with `add_edited(*, flavor: str, path: Path, rel: str, zip_path: Path,
    sha_before: str, sha_after: str, size_before: int, size_after: int, changes: list[str])` and
    `add_rolled_back(*, flavor: str, rels: list[str])`; `read_profile_journal(path) -> Journal`;
    `latest_undoable(folder) -> Path | None`; `prune_journals(folder, keep) -> list[Path]`;
    `referenced_zips(folder) -> set[str]` (file names of zips named by the journals left).
  - `editor.SNAPSHOT_SUBDIR = "snapshots"`, `SNAPSHOT_PREFIX = "snapshot"`, `EDITED_SUBDIR = "edited"`,
    `MARKER_NAME = "edit-in-progress.json"`, `ApplyProgress = Callable[[str, int, int, str], None]`.
  - `class ApplyError(Exception)` (`.rolled_back: list[str]`, `.files_left: list[str]`).
  - `@dataclass FileOutcome(file: SvFile, status: str, detail: str = "", changes: list[str] = [])`. Statuses:
    `edited`, `would_edit`, `skipped`, `failed`, `rolled_back`.
  - `@dataclass ApplyResult(flavor: Flavor, dry_run: bool, outcomes: list[FileOutcome], snapshot: Path | None,
    backup_zip: Path | None, pruned: list[Path])` with properties `edited`, `would_edit`, `skipped`, `failed`,
    `rolled_back`.
  - `@dataclass Marker(flavor: str, flavor_path: Path, zip: Path, files: dict[str, str], started: str, pid: int,
    suite_version: str)`, plus `write_marker(root, marker)`, `read_marker(root) -> Marker | None`,
    `clear_marker(root)`.
  - `edited_zip_path(root, flavor_short, account: str | None, now) -> Path`.
  - `group_by_file(states: list[DbState]) -> dict[Path, list[DbState]]`, `restore_original(path, data) -> None`.
  - `apply_flavor(flavor, states, *, root: Path, journal: ProfileJournal | None, dry_run: bool,
    keep_snapshots: int, account: str | None = None, now: datetime | None = None,
    progress: ApplyProgress | None = None, write: Callable[[Path, bytes], None] = atomic_write_bytes)
    -> ApplyResult`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ace_journal.py
"""journal: the Ace3 Profile Manager's run journals over core/journal.py."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wowtools.tools.ace_profiles import journal as j


class JournalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "journal"

    def write(self, rels, rolled=()):
        self.count = getattr(self, "count", 0) + 1
        writer = j.ProfileJournal(self.folder / f"journal-20261004-12000{self.count}.jsonl", {"kind": "apply"})
        for rel in rels:
            writer.add_edited(flavor="_retail_", path=Path("/w") / rel, rel=rel, zip_path=Path("/z/edited-a.zip"),
                              sha_before="a", sha_after="b", size_before=1, size_after=2, changes=["x"])
        if rolled:
            writer.add_rolled_back(flavor="_retail_", rels=list(rolled))
        writer.finish()
        writer.discard_if_empty()
        return writer.path

    def test_round_trip(self):
        path = self.write(["WTF/Account/A/SavedVariables/K.lua"])
        journal = j.read_profile_journal(path)
        self.assertEqual(len(journal.entries), 1)
        entry = journal.entries[0]
        self.assertEqual((entry["action"], entry["sha_before"], entry["sha_after"]), ("edited", "a", "b"))
        self.assertIsInstance(entry["zip"], Path)

    def test_rolled_back_entries_are_dropped_and_not_undoable(self):
        path = self.write(["WTF/Account/A/SavedVariables/K.lua"], rolled=["WTF/Account/A/SavedVariables/K.lua"])
        self.assertFalse(path.exists())  # every edit rolled back: nothing to keep
        self.assertIsNone(j.latest_undoable(self.folder))

    def test_referenced_zips(self):
        self.write(["WTF/Account/A/SavedVariables/K.lua"])
        self.assertEqual(j.referenced_zips(self.folder), {"edited-a.zip"})
```

```python
# tests/test_ace_editor.py
"""editor.apply_flavor: guard, recheck, lock probe, snapshot, originals zip, atomic writes, roll-back (spec §9)."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_ace_tree
from wowtools.core.events import capture_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import editor, luasv, model, ops, scanner
from wowtools.tools.ace_profiles.journal import ProfileJournal, read_profile_journal

WHEN = datetime(2026, 10, 4, 12, 0, 0)


class EditorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_ace_tree(self.tmp / "wow")
        self.flavor = WowInstall(self.wow).flavor("_retail_")
        self.root = self.tmp / "out" / "ace-profiles"
        self.scan = scanner.ScanResult([scanner.scan_flavor(self.flavor, account="ACCT1")])
        self.staging = ops.Staging.from_scan(self.scan)

    def key(self, sv_name):
        return next(k for k in self.staging.states if k.sv_name == sv_name)

    def stage_two_files(self):
        self.staging.delete({self.key("ElvDB"): ["Healer"]}, "Default")
        self.staging.remove_leftovers({self.key("KickCDDB"): ["Gone - Realm1"]})

    def journal(self):
        journal = ProfileJournal(self.tmp / "journal" / "journal-20261004-120000.jsonl", {"kind": "apply"})
        self.addCleanup(journal.close)
        return journal

    def apply(self, *, dry_run=False, journal=None, **kwargs):
        return editor.apply_flavor(self.flavor, self.staging.changed(), root=self.root,
                                   journal=None if dry_run else (journal or self.journal()), dry_run=dry_run,
                                   keep_snapshots=2, account="ACCT1", now=WHEN, **kwargs)

    def test_dry_run_writes_nothing(self):
        self.stage_two_files()
        before = {p: p.read_bytes() for p in self.flavor.wtf_dir.rglob("*.lua")}
        result = self.apply(dry_run=True)
        self.assertEqual(len(result.would_edit), 2)
        self.assertEqual({p: p.read_bytes() for p in self.flavor.wtf_dir.rglob("*.lua")}, before)
        self.assertFalse(self.root.exists())

    def test_apply_writes_snapshots_backs_up_and_journals(self):
        self.stage_two_files()
        journal = self.journal()
        elv = self.key("ElvDB").path
        original = elv.read_bytes()
        result = self.apply(journal=journal)
        journal.finish()
        journal.close()
        self.assertEqual(len(result.edited), 2)
        self.assertNotIn(b'["Healer"]', elv.read_bytes())
        self.assertEqual(result.snapshot.parent, self.root / "snapshots")
        self.assertTrue(result.snapshot.name.startswith("snapshot-retail-20261004-120000"))
        self.assertEqual(result.backup_zip.name, "edited-retail-ACCT1-20261004-120000.zip")
        with zipfile.ZipFile(result.backup_zip) as zf:
            self.assertEqual(zf.read("WTF/Account/ACCT1/SavedVariables/ElvUI.lua"), original)
        entries = read_profile_journal(journal.path).entries
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["sha_before"], scanner.sha256_of(original))
        self.assertEqual(entries[0]["sha_after"], scanner.sha256_of(elv.read_bytes()))
        self.assertIsNone(editor.read_marker(self.root))

    def test_file_changed_since_scan_is_skipped_others_applied(self):
        self.stage_two_files()
        kick = self.key("KickCDDB").path
        kick.write_bytes(kick.read_bytes() + b"\r\n")
        with capture_events() as events:
            result = self.apply()
        self.assertEqual([o.file.addon for o in result.skipped], ["KickCD"])
        self.assertIn("changed since the scan", result.skipped[0].detail)
        self.assertEqual([o.file.addon for o in result.edited], ["ElvUI"])
        self.assertIn("ace.file_changed", [e["event"] for e in events])

    def test_failure_mid_run_rolls_back_written_files(self):
        self.stage_two_files()
        self.staging.copy(self.key("HandyNotesDB"), "Unused - Realm1", "Spare")
        paths = sorted({s.file.path for s in self.staging.changed()}, key=lambda p: p.name.casefold())
        before = {p: p.read_bytes() for p in paths}
        calls = []

        def flaky(path, data):
            calls.append(path)
            if len(calls) == 3:
                raise OSError("disk full")
            atomic_write_bytes(path, data)
        journal = self.journal()
        with self.assertRaises(editor.ApplyError) as caught:
            self.apply(journal=journal, write=flaky)
        journal.close()
        self.assertEqual({p: p.read_bytes() for p in paths}, before)
        self.assertEqual(len(caught.exception.rolled_back), 2)
        self.assertEqual(caught.exception.files_left, [])
        self.assertIsNone(editor.read_marker(self.root))
        self.assertEqual(read_profile_journal(journal.path).entries if journal.path.exists() else [], [])

    def test_verify_failure_stops_before_anything_is_written(self):
        self.stage_two_files()
        before = {p: p.read_bytes() for p in self.flavor.wtf_dir.rglob("*.lua")}
        with patch("wowtools.tools.ace_profiles.editor.verify_edit", return_value=["broken"]), \
                self.assertRaises(editor.ApplyError):
            self.apply()
        self.assertEqual({p: p.read_bytes() for p in self.flavor.wtf_dir.rglob("*.lua")}, before)
        self.assertFalse((self.root / "snapshots").exists())

    def test_locked_file_refuses_before_snapshot(self):
        self.stage_two_files()
        with patch("wowtools.tools.ace_profiles.editor.probe_lock", return_value="in use"), \
                self.assertRaises(editor.ApplyError) as caught:
            self.apply()
        self.assertIn("locked", str(caught.exception))
        self.assertFalse((self.root / "snapshots").exists())

    def test_marker_is_left_when_put_back_fails(self):
        self.stage_two_files()
        calls = []

        def broken(path, data):
            calls.append(path)
            if len(calls) == 1:
                atomic_write_bytes(path, data)
                return
            raise OSError("gone wrong")
        with patch("wowtools.tools.ace_profiles.editor.restore_original", side_effect=OSError("no")), \
                self.assertRaises(editor.ApplyError) as caught:
            self.apply(write=broken)
        self.assertTrue(caught.exception.files_left)
        marker = editor.read_marker(self.root)
        self.assertIsNotNone(marker)
        self.assertEqual(marker.flavor, "_retail_")
        self.assertTrue(marker.zip.exists())

    def test_guard_refuses_a_path_outside_saved_variables(self):
        self.stage_two_files()
        state = self.staging.changed()[0]
        moved = scanner.SvFile(self.flavor.account_dir / "ACCT1" / "x.lua", state.file.flavor, "ACCT1", None,
                               0, 0.0, "")
        bad = ops.DbState(state.key, moved, state.db, state.leftovers, state.keys, state.profiles, state.lds)
        with self.assertRaises(editor.ApplyError):
            editor.apply_flavor(self.flavor, [bad], root=self.root, journal=self.journal(), dry_run=False,
                                keep_snapshots=2, now=WHEN)

    def test_prunes_old_snapshots(self):
        folder = self.root / "snapshots"
        folder.mkdir(parents=True)
        for day in ("01", "02", "03"):
            (folder / f"snapshot-retail-202610{day}-000000.zip").write_bytes(b"x")
        self.stage_two_files()
        result = self.apply()
        self.assertEqual(len(result.pruned), 2)
        self.assertEqual(len(list(folder.iterdir())), 2)

    def test_written_file_reads_back_as_acedb(self):
        self.stage_two_files()
        self.apply()
        data = self.key("ElvDB").path.read_bytes()
        dbs, _ = model.find_dbs(luasv.parse(data, model.ace_descend), data)
        self.assertEqual([db.sv_name for db in dbs], ["ElvDB", "ElvPrivateDB"])

    @unittest.skipIf(os.name == "nt", "chmod read-only does not stop a rename on Windows")
    def test_nothing_staged_does_nothing(self):
        result = editor.apply_flavor(self.flavor, [], root=self.root, journal=self.journal(), dry_run=False,
                                     keep_snapshots=2, now=WHEN)
        self.assertEqual(result.outcomes, [])
        self.assertFalse(self.root.exists())
```

- [ ] **Step 2: Run to see them fail**

Run: `python3 scripts/run_tests.py -k ace_journal`, `-k ace_editor`. Expected: ImportError.

- [ ] **Step 3: Implement `journal.py`**

```python
"""The Ace3 Profile Manager's run journals: the suite format (core/journal.py) with this tool's entries.

One journal per Apply, even across All flavors: <WoW>/wow-tools/ace-profiles/journal/journal-<stamp>.jsonl. Each
rewritten file adds {"action": "edited", "flavor", "path", "rel", "zip", "sha_before", "sha_after", "size_before",
"size_after", "changes"}: zip is the edited-*.zip holding the file's original bytes (as <rel>). When a run puts
written files back after a failure it appends {"action": "rolled_back", "flavor", "rels"}; those entries are
dropped on reading, so they are never offered for Undo.
"""
from __future__ import annotations

from pathlib import Path

from wowtools.core import journal as core
from wowtools.core.events import log_event
from wowtools.core.journal import Journal

A_EDITED = "edited"
A_ROLLED_BACK = "rolled_back"
PATH_FIELDS = ("path", "zip")


class ProfileJournal(core.JournalWriter):
    def __init__(self, path: Path, header: dict) -> None:
        super().__init__(path, header)
        self._edited: set[tuple[str, str]] = set()

    def add_edited(self, *, flavor: str, path: Path, rel: str, zip_path: Path, sha_before: str, sha_after: str,
                   size_before: int, size_after: int, changes: list[str]) -> None:
        self.add_entry({"action": A_EDITED, "flavor": flavor, "path": path, "rel": rel, "zip": zip_path,
                        "sha_before": sha_before, "sha_after": sha_after, "size_before": size_before,
                        "size_after": size_after, "changes": list(changes)})
        self._edited.add((flavor, rel))

    def add_rolled_back(self, *, flavor: str, rels: list[str]) -> None:
        undone = {(flavor, rel) for rel in rels} & self._edited
        if not undone:
            return
        self._write({"action": A_ROLLED_BACK, "flavor": flavor, "rels": sorted(rel for _, rel in undone)})
        self._edited -= undone
        self.count -= len(undone)


def read_profile_journal(path: Path) -> Journal:
    journal = core.read_journal(path, path_fields=PATH_FIELDS)
    rolled = {(e.get("flavor"), rel) for e in journal.entries
              if e.get("action") == A_ROLLED_BACK and isinstance(e.get("rels"), list)
              for rel in e["rels"] if isinstance(rel, str)}
    entries = []
    for entry in journal.entries:
        if entry.get("action") != A_EDITED or (entry.get("flavor"), entry.get("rel")) in rolled:
            continue
        if not all(isinstance(entry.get(k), str) for k in ("flavor", "rel", "sha_before", "sha_after")):
            continue
        if not isinstance(entry.get("zip"), Path):
            continue
        entries.append(entry)
    journal.entries = entries
    return journal


def latest_undoable(folder: Path | None) -> Path | None:
    return core.latest_undoable(folder, read_profile_journal)


def prune_journals(folder: Path | None, keep: int) -> list[Path]:
    removed = core.prune_journals(folder, keep)
    if removed:
        log_event("ace.journal_pruned", removed=[p.name for p in removed], keep=keep)
    return removed


def referenced_zips(folder: Path | None) -> set[str]:
    names: set[str] = set()
    for path in core.list_journals(folder):
        try:
            journal = read_profile_journal(path)
        except OSError:
            continue
        names.update(entry["zip"].name for entry in journal.entries)
    return names
```

Note: a writer whose every entry was rolled back has `count == 0`, so `discard_if_empty()` removes the file, which
is what `test_rolled_back_entries_are_dropped_and_not_undoable` expects. If `JournalWriter.finish()` has already
written a "finished" line, `discard_if_empty` still deletes it, because it looks only at `count`.

- [ ] **Step 4: Implement `editor.py`**

```python
"""Apply staged profile changes to one flavor's SavedVariables (spec §9). UI-free.

Order: guard every path, re-read each file and check it is still what the scan saw (SHA-256), compile and verify
every edit in memory, then (real runs only) open the journal, recover lock-probe leftovers, refuse locked files,
take the whole-WTF snapshot, zip the original bytes of every file to change, write the crash marker, and write
each file atomically (re-read and compared), journalling each one. Any failure while writing puts the files
already written back from their original bytes, then the run stops. A dry run stops after the verify step and
writes nothing at all.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools import __version__
from wowtools.core.backup import BackupEntry, BackupError, create_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import atomic_write_bytes, free_name, remove_quietly, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import now_iso
from wowtools.core.snapshot import prune_snapshots, take_snapshot
from wowtools.core.svfiles import SvFileError, SvGuard, lstat_or_none, probe_lock, recover_probe_leftovers
from wowtools.tools.ace_profiles.events import TOOL_NAME
from wowtools.tools.ace_profiles.journal import ProfileJournal
from wowtools.tools.ace_profiles.ops import DbState, FileEdit, compile_file
from wowtools.tools.ace_profiles.scanner import SvFile, sha256_of
from wowtools.tools.ace_profiles.verify import verify_edit

SNAPSHOT_SUBDIR = "snapshots"
SNAPSHOT_PREFIX = "snapshot"
EDITED_SUBDIR = "edited"
MARKER_NAME = "edit-in-progress.json"
ALL_ACCOUNTS = "all"
CHANGED = "changed since the scan; rescan"
ApplyProgress = Callable[[str, int, int, str], None]


class ApplyError(Exception):
    """Apply was refused or stopped. rolled_back: files put back after a failure; files_left: files that could
    not be put back (the marker is kept; the originals are in the edited-*.zip it names)."""

    def __init__(self, message: str, *, rolled_back: list[str] | None = None,
                 files_left: list[str] | None = None) -> None:
        super().__init__(message)
        self.rolled_back = list(rolled_back or [])
        self.files_left = list(files_left or [])


@dataclass
class FileOutcome:
    file: SvFile
    status: str
    detail: str = ""
    changes: list[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    flavor: Flavor
    dry_run: bool
    outcomes: list[FileOutcome] = field(default_factory=list)
    snapshot: Path | None = None
    backup_zip: Path | None = None
    pruned: list[Path] = field(default_factory=list)

    def _with(self, status: str) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def edited(self) -> list[FileOutcome]:
        return self._with("edited")

    @property
    def would_edit(self) -> list[FileOutcome]:
        return self._with("would_edit")

    @property
    def skipped(self) -> list[FileOutcome]:
        return self._with("skipped")

    @property
    def failed(self) -> list[FileOutcome]:
        return self._with("failed")

    @property
    def rolled_back(self) -> list[FileOutcome]:
        return self._with("rolled_back")


@dataclass
class Marker:
    flavor: str
    flavor_path: Path
    zip: Path
    files: dict[str, str]  # rel -> SHA-256 of the original
    started: str
    pid: int
    suite_version: str


def write_marker(root: Path, marker: Marker) -> None:
    data = asdict(marker)
    data["flavor_path"] = str(marker.flavor_path)
    data["zip"] = str(marker.zip)
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(root / MARKER_NAME, json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))


def read_marker(root: Path | None) -> Marker | None:
    if root is None:
        return None
    try:
        data = json.loads((root / MARKER_NAME).read_text(encoding="utf-8"))
        files = data["files"]
        if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                  for k, v in files.items()):
            return None
        return Marker(str(data["flavor"]), Path(data["flavor_path"]), Path(data["zip"]), dict(files),
                      str(data["started"]), int(data["pid"]), str(data["suite_version"]))
    except Exception:  # noqa: BLE001 - an unreadable marker is no usable marker
        return None


def clear_marker(root: Path) -> None:
    remove_quietly(root / MARKER_NAME)


def edited_zip_path(root: Path, flavor_short: str, account: str | None, now: datetime) -> Path:
    return free_name(root / EDITED_SUBDIR,
                     f"edited-{flavor_short}-{account or ALL_ACCOUNTS}-{now:%Y%m%d-%H%M%S}", ".zip")


def group_by_file(states: list[DbState]) -> dict[Path, list[DbState]]:
    grouped: dict[Path, list[DbState]] = {}
    for state in states:
        grouped.setdefault(state.file.path, []).append(state)
    return grouped


def _prepare(flavor: Flavor, states: list[DbState], result: ApplyResult,
             report: ApplyProgress) -> list[tuple[SvFile, FileEdit, bytes]]:
    """Guard, recheck, compile and verify every file. Raises ApplyError on a guard or verify failure."""
    guard = SvGuard(flavor)
    grouped = group_by_file(states)
    ready: list[tuple[SvFile, FileEdit, bytes]] = []
    for index, (path, file_states) in enumerate(grouped.items(), 1):
        file = file_states[0].file
        try:
            guard.check(path, lstat_or_none(path))
        except SvFileError as exc:
            raise ApplyError(str(exc)) from None
        try:
            data = path.read_bytes()
        except OSError as exc:
            result.outcomes.append(FileOutcome(file, "skipped", f"could not read it: {exc.strerror or exc}"))
            continue
        if sha256_of(data) != file.sha256:
            result.outcomes.append(FileOutcome(file, "skipped", CHANGED))
            log_event("ace.file_changed", flavor=flavor.folder, path=file.rel)
            continue
        edit = compile_file(file_states, data)
        problems = verify_edit(edit, data)
        if problems:
            log_event("ace.verify_failed", flavor=flavor.folder, path=file.rel, problems=problems[:10])
            raise ApplyError(f"{file.rel}: the change did not check out ({'; '.join(problems[:3])}). "
                             f"Nothing was changed.")
        ready.append((file, edit, data))
        report("check", index, len(grouped), file.rel)
    return ready


def _refuse_locked(ready: list[tuple[SvFile, FileEdit, bytes]], flavor: Flavor, report: ApplyProgress) -> None:
    locked = []
    for index, (file, _, _) in enumerate(ready, 1):
        try:
            error = probe_lock(file.path)
        except SvFileError as exc:
            raise ApplyError(f"{exc} Nothing was changed.") from exc
        if error is not None:
            locked.append((file.rel, error))
        report("lock_check", index, len(ready), file.rel)
    if locked:
        log_event("ace.file_locked", flavor=flavor.folder, files=len(locked), details=[r for r, _ in locked[:20]])
        names = "\n".join(f"  {rel} ({error})" for rel, error in locked[:10])
        raise ApplyError(f"{len(locked)} files are locked by another program (the Raider.IO client and WeakAuras "
                         f"Companion are known to do this). Close it and apply again.\n{names}")


def apply_flavor(flavor: Flavor, states: list[DbState], *, root: Path, journal: ProfileJournal | None,
                 dry_run: bool, keep_snapshots: int, account: str | None = None, now: datetime | None = None,
                 progress: ApplyProgress | None = None,
                 write: Callable[[Path, bytes], None] = atomic_write_bytes) -> ApplyResult:
    report = safe_progress(progress)
    now = now or datetime.now()
    result = ApplyResult(flavor, dry_run)
    log_event("ace.apply_started", flavor=flavor.folder, dry_run=dry_run, databases=len(states))
    ready = _prepare(flavor, states, result, report)
    if dry_run:
        for file, edit, _ in ready:
            result.outcomes.append(FileOutcome(file, "would_edit", changes=edit.changes))
            log_event("ace.would_edit", flavor=flavor.folder, path=file.rel, changes=edit.changes[:50])
        log_event("ace.dry_run_completed", flavor=flavor.folder, files=len(ready))
        return result
    if not ready:
        return result
    assert journal is not None, "a real run needs a journal"
    try:
        journal.open()
    except OSError as exc:
        log_event("ace.journal_failed", error=str(exc))
        raise ApplyError(f"The run journal could not be written ({exc}). Nothing was changed.") from exc
    recover_probe_leftovers(sorted({f.path.parent for f, _, _ in ready}), on_recovered=lambda p: log_event(
        "ace.probe_recovered", flavor=flavor.folder, path=p.relative_to(flavor.path).as_posix()))
    _refuse_locked(ready, flavor, report)
    rels = [file.rel for file, _, _ in ready]
    try:
        result.snapshot = take_snapshot(flavor, root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, now, progress=report,
                                        must_hold=rels)
    except BackupError as exc:
        log_event("ace.snapshot_failed", flavor=flavor.folder, error=str(exc))
        raise ApplyError(f"The WTF backup failed ({exc}). Nothing was changed.") from exc
    log_event("ace.snapshot_taken", flavor=flavor.folder, path=str(result.snapshot))
    try:
        result.backup_zip = create_backup(
            [BackupEntry(file.path, size=len(data)) for file, _, data in ready], flavor.path,
            edited_zip_path(root, flavor.short_name, account, now),
            {"tool": TOOL_NAME, "kind": "originals", "flavor": flavor.folder, "suite_version": __version__,
             "sha256": {file.rel: file.sha256 for file, _, _ in ready}},
            on_file=lambda i, n, name: report("backup", i, n, name))
    except BackupError as exc:
        log_event("ace.backup_failed", flavor=flavor.folder, error=str(exc))
        raise ApplyError(f"Saving the original files failed ({exc}). Nothing was changed.") from exc
    log_event("ace.files_backed_up", flavor=flavor.folder, path=str(result.backup_zip), files=len(ready))
    write_marker(root, Marker(flavor.folder, flavor.path, result.backup_zip,
                              {file.rel: file.sha256 for file, _, _ in ready}, now_iso(), os.getpid(), __version__))
    written: list[tuple[SvFile, bytes]] = []
    try:
        for index, (file, edit, data) in enumerate(ready, 1):
            current = file.path.read_bytes()
            if sha256_of(current) != file.sha256:
                result.outcomes.append(FileOutcome(file, "skipped", CHANGED))
                log_event("ace.file_changed", flavor=flavor.folder, path=file.rel)
                continue
            write(file.path, edit.data)
            written.append((file, data))
            if file.path.read_bytes() != edit.data:
                raise OSError(f"{file.rel} did not read back as written")
            journal.add_edited(flavor=flavor.folder, path=file.path, rel=file.rel, zip_path=result.backup_zip,
                               sha_before=file.sha256, sha_after=sha256_of(edit.data), size_before=len(data),
                               size_after=len(edit.data), changes=edit.changes)
            result.outcomes.append(FileOutcome(file, "edited", changes=edit.changes))
            log_event("ace.file_edited", flavor=flavor.folder, path=file.rel, changes=edit.changes[:50])
            report("edit", index, len(ready), file.rel)
    except BaseException as exc:
        _roll_back(exc, written, result, journal, root, flavor, write)
    clear_marker(root)
    result.pruned = prune_snapshots(root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, flavor.short_name, keep_snapshots)
    if result.pruned:
        log_event("ace.snapshots_pruned", flavor=flavor.folder, removed=[p.name for p in result.pruned])
    return result


def restore_original(path: Path, data: bytes) -> None:
    """Put a file's original bytes back (roll-back after a failure); its own name so tests can fail it."""
    atomic_write_bytes(path, data)


def _roll_back(exc: BaseException, written: list[tuple[SvFile, bytes]], result: ApplyResult,
               journal: ProfileJournal, root: Path, flavor: Flavor, write: Callable[[Path, bytes], None]) -> None:
    """Put back every file this run wrote, newest first, then raise ApplyError (or re-raise a non-Exception)."""
    put_back, left = [], []
    for file, original in reversed(written):
        try:
            restore_original(file.path, original)
            put_back.append(file.rel)
        except OSError as error:
            left.append(file.rel)
            log_event("ace.rollback_failed", flavor=flavor.folder, path=file.rel, error=str(error))
    if put_back:
        try:
            journal.add_rolled_back(flavor=flavor.folder, rels=put_back)
        except OSError:
            pass
    done = set(put_back)
    for outcome in result.outcomes:
        if outcome.status == "edited" and outcome.file.rel in done:
            outcome.status = "rolled_back"
    log_event("ace.rolled_back", flavor=flavor.folder, files=put_back, left=left, error=str(exc))
    if not left:
        clear_marker(root)
    if not isinstance(exc, Exception):
        raise exc
    log_event("ace.write_failed", flavor=flavor.folder, error=str(exc))
    message = f"Writing the changes failed ({exc})."
    if put_back:
        message += f" The {len(put_back)} file(s) already written were put back."
    if left:
        message += (f" {len(left)} file(s) could not be put back: their originals are in "
                    f"{result.backup_zip}. Close WoW and use Undo, or unzip them by hand.")
    raise ApplyError(message, rolled_back=put_back, files_left=left) from exc
```

Notes:
- Roll-back always uses `restore_original` (not the injectable `write`), so a test can fail the third write and
  still see the first two put back. `test_marker_is_left_when_put_back_fails` patches `restore_original` to fail.
- `create_backup` stats a file when `mtime` is None. That is fine: one stat per changed file only.

- [ ] **Step 5: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_journal`, `-k ace_editor`, `-k ace`. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add wowtools/tools/ace_profiles/journal.py wowtools/tools/ace_profiles/editor.py tests/test_ace_journal.py tests/test_ace_editor.py
git commit -m "feat(ace-profiles): apply staged changes with snapshot, originals zip, journal and roll-back"
```

---

### Task 9: undo, recovery and All flavors (`undo.py`, `multi.py`)

**Files:**
- Create: `wowtools/tools/ace_profiles/undo.py`, `wowtools/tools/ace_profiles/multi.py`
- Test: `tests/test_ace_undo.py`, `tests/test_ace_multi.py`

**Interfaces:**
- Consumes: everything from Task 8; `core.journal.mark_undone`, `new_journal_path`.
- Produces:
  - `undo.UndoError(Exception)`, `undo.WowRunning(UndoError)` with `.running: list[str]`.
  - `@dataclass undo.UndoOutcome(flavor: str, rel: str, path: Path | None, status: str, detail: str = "")`.
    Statuses: `restored`, `skipped`, `failed`.
  - `@dataclass undo.UndoResult(outcomes: list[UndoOutcome], journal_path: Path | None,
    snapshots: list[Path])` with properties `restored`, `skipped`, `failed`.
  - `undo.destination(wow_root: Path, flavor: str, rel: str) -> Path | None`.
  - `undo.undo_run(journal_path, *, wow_root: Path, root: Path, keep_snapshots: int,
    wow_check: Callable[[], list[str] | None] | None = None, now=None, progress=None) -> UndoResult`.
  - `undo.recover(marker: Marker, *, root: Path) -> UndoResult`. It puts back, from `marker.zip`, every file whose
    current SHA-256 is not the original's, then clears the marker.
  - `multi.WowRunning(ApplyError)` with `.running`.
  - `@dataclass multi.FlavorRun(flavor: Flavor, result: ApplyResult | None, error: str | None)` with
    `status -> "done" | "stopped" | "not_started"`.
  - `@dataclass multi.MultiApplyResult(dry_run: bool, runs: list[FlavorRun], journal_path: Path | None)` with
    `outcomes -> list[FileOutcome]`, `edited`, `would_edit`, `skipped`, `failed`, `rolled_back`, `stopped`.
  - `multi.apply_flavors(plan: list[tuple[Flavor, list[DbState]]], *, root: Path, journal_dir: Path,
    keep_journals: int, keep_snapshots: int, dry_run: bool, account: str | None = None,
    wow_check: Callable[[], list[str] | None] | None = None, now=None,
    progress: Callable[[Flavor, str, int, int, str], None] | None = None) -> MultiApplyResult`.
  - `multi.prune_edited_zips(root: Path, journal_dir: Path | None, keep_names: set[str] = frozenset())
    -> list[Path]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ace_undo.py
"""undo_run and recover: put files back only when they are still what the run wrote (spec §10)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.core.journal import read_journal
from wowtools.tools.ace_profiles import editor, multi, ops, scanner, undo
from wowtools.tools.ace_profiles.journal import latest_undoable

WHEN = datetime(2026, 10, 4, 12, 0, 0)


class UndoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_ace_tree(self.tmp / "wow")
        self.flavor = WowInstall(self.wow).flavor("_retail_")
        self.root = self.tmp / "out"
        self.journals = self.tmp / "journal"
        scan = scanner.ScanResult([scanner.scan_flavor(self.flavor, account="ACCT1")])
        self.staging = ops.Staging.from_scan(scan)
        elv = next(k for k in self.staging.states if k.sv_name == "ElvDB")
        kick = next(k for k in self.staging.states if k.sv_name == "KickCDDB")
        self.elv, self.kick = elv.path, kick.path
        self.before = {p: p.read_bytes() for p in (self.elv, self.kick)}
        self.staging.delete({elv: ["Healer"]}, "Default")
        self.staging.remove_leftovers({kick: ["Gone - Realm1"]})
        multi.apply_flavors([(self.flavor, self.staging.changed())], root=self.root, journal_dir=self.journals,
                            keep_journals=10, keep_snapshots=2, dry_run=False, account="ACCT1", now=WHEN)
        self.journal = latest_undoable(self.journals)

    def undo(self, **kwargs):
        return undo.undo_run(self.journal, wow_root=self.wow, root=self.root, keep_snapshots=2, now=WHEN, **kwargs)

    def test_undo_restores_both_files(self):
        result = self.undo()
        self.assertEqual(len(result.restored), 2)
        self.assertEqual({p: p.read_bytes() for p in (self.elv, self.kick)}, self.before)
        self.assertIsNotNone(read_journal(self.journal).undone)
        self.assertIsNone(latest_undoable(self.journals))
        self.assertTrue(result.snapshots)

    def test_file_changed_since_is_skipped_not_overwritten(self):
        self.kick.write_bytes(self.kick.read_bytes() + b"-- saved by WoW\r\n")
        changed = self.kick.read_bytes()
        result = self.undo()
        self.assertEqual([o.rel.rsplit("/", 1)[-1] for o in result.skipped], ["KickCD.lua"])
        self.assertIn("changed since", result.skipped[0].detail)
        self.assertEqual(self.kick.read_bytes(), changed)
        self.assertEqual(self.elv.read_bytes(), self.before[self.elv])

    def test_refused_while_wow_runs(self):
        with self.assertRaises(undo.WowRunning):
            self.undo(wow_check=lambda: ["Wow.exe"])
        self.assertNotEqual(self.elv.read_bytes(), self.before[self.elv])

    def test_missing_zip_fails_and_journal_stays_undoable(self):
        for zip_path in (self.root / "edited").iterdir():
            zip_path.unlink()
        result = self.undo()
        self.assertEqual(len(result.failed), 2)
        self.assertEqual(latest_undoable(self.journals), self.journal)

    def test_destination_refuses_escapes(self):
        self.assertIsNone(undo.destination(self.wow, "_retail_", "../x.lua"))
        self.assertIsNone(undo.destination(self.wow, "_retail_", "Interface/AddOns/x.lua"))
        self.assertIsNone(undo.destination(self.wow, "_retail_", "WTF/Account/A/x.lua"))
        self.assertEqual(undo.destination(self.wow, "_retail_", "WTF/Account/A/SavedVariables/x.lua"),
                         self.wow / "_retail_" / "WTF" / "Account" / "A" / "SavedVariables" / "x.lua")


class RecoverTest(unittest.TestCase):
    def test_recover_puts_back_only_changed_files_and_clears_marker(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        wow = build_ace_tree(base / "wow")
        flavor = WowInstall(wow).flavor("_retail_")
        root = base / "out"
        scan = scanner.ScanResult([scanner.scan_flavor(flavor, account="ACCT1")])
        staging = ops.Staging.from_scan(scan)
        elv = next(k for k in staging.states if k.sv_name == "ElvDB")
        original = elv.path.read_bytes()
        staging.delete({elv: ["Healer"]}, "Default")
        editor.apply_flavor(flavor, staging.changed(), root=root, journal=None, dry_run=True, keep_snapshots=2)
        from wowtools.core.backup import BackupEntry, create_backup
        zip_path = create_backup([BackupEntry(elv.path)], flavor.path, root / "edited" / "edited-x.zip", {})
        elv.path.write_bytes(b"half written")
        marker = editor.Marker("_retail_", flavor.path, zip_path,
                               {"WTF/Account/ACCT1/SavedVariables/ElvUI.lua": scanner.sha256_of(original)},
                               "now", 1, "1.0.0")
        editor.write_marker(root, marker)
        result = undo.recover(marker, root=root)
        self.assertEqual(len(result.restored), 1)
        self.assertEqual(elv.path.read_bytes(), original)
        self.assertIsNone(editor.read_marker(root))
```

```python
# tests/test_ace_multi.py
"""apply_flavors: one journal per run, WoW-running refusal, stop at the first failing flavor, pruning."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.core.journal import list_journals
from wowtools.tools.ace_profiles import editor, multi, ops, scanner

WHEN = datetime(2026, 10, 4, 12, 0, 0)


class MultiTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        install = WowInstall(build_ace_tree(self.tmp / "wow"))
        self.retail, self.era = install.flavor("_retail_"), install.flavor("_classic_era_")
        scan = scanner.scan_flavors([self.retail, self.era])
        self.staging = ops.Staging.from_scan(scan)
        self.staging.everyone_to_default(list(self.staging.states))
        for key in list(self.staging.states):
            if self.staging.state(key).file.addon == "Questie":
                self.staging.copy(key, "Default", "Copy")
        self.plan = [(f, [s for s in self.staging.changed() if s.file.flavor == f]) for f in (self.retail, self.era)]

    def run_plan(self, **kwargs):
        options = dict(root=self.tmp / "out", journal_dir=self.tmp / "journal", keep_journals=10, keep_snapshots=2,
                       dry_run=False, now=WHEN)
        options.update(kwargs)
        return multi.apply_flavors(self.plan, **options)

    def test_one_journal_for_both_flavors(self):
        result = self.run_plan()
        self.assertEqual([r.status for r in result.runs], ["done", "done"])
        self.assertEqual(len(list_journals(self.tmp / "journal")), 1)
        self.assertTrue(result.edited)

    def test_wow_running_refuses_everything(self):
        with self.assertRaises(multi.WowRunning) as caught:
            self.run_plan(wow_check=lambda: ["Wow.exe"])
        self.assertEqual(caught.exception.running, ["Wow.exe"])
        self.assertFalse((self.tmp / "journal").exists())

    def test_dry_run_ignores_wow_and_writes_no_journal(self):
        result = self.run_plan(dry_run=True, wow_check=lambda: ["Wow.exe"])
        self.assertTrue(result.would_edit)
        self.assertFalse((self.tmp / "journal").exists())

    def test_stops_at_failing_flavor(self):
        real = editor.apply_flavor

        def failing(flavor, *args, **kwargs):
            if flavor.folder == "_retail_":
                raise editor.ApplyError("boom")
            return real(flavor, *args, **kwargs)
        with patch("wowtools.tools.ace_profiles.multi.apply_flavor", failing):
            result = self.run_plan()
        self.assertEqual([r.status for r in result.runs], ["stopped", "not_started"])
        self.assertEqual(result.stopped.error, "boom")

    def test_prune_edited_zips_keeps_referenced(self):
        result = self.run_plan()
        edited = self.tmp / "out" / "edited"
        stray = edited / "edited-retail-all-20200101-000000.zip"
        stray.write_bytes(b"x")
        removed = multi.prune_edited_zips(self.tmp / "out", self.tmp / "journal")
        self.assertEqual(removed, [stray])
        self.assertTrue(all(o.file for o in result.edited))
        self.assertTrue(any(edited.iterdir()))
```

- [ ] **Step 2: Run to see them fail**

Run: `python3 scripts/run_tests.py -k ace_undo`, `-k ace_multi`. Expected: ImportError.

- [ ] **Step 3: Implement `undo.py`**

```python
"""Undo the latest Apply, and recover from one that did not finish (spec §10). UI-free.

A file is put back from the edited-*.zip only when it is still byte-for-byte what the run wrote (sha_after); a file
WoW (or anything else) saved since is skipped and never overwritten. Undo is refused while WoW runs, refuses locked
files, and takes a whole-WTF snapshot of each flavor first.
"""
from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from wowtools.core.backup import BackupError
from wowtools.core.events import log_event
from wowtools.core.fsutil import atomic_write_bytes, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import mark_undone
from wowtools.core.snapshot import take_snapshot
from wowtools.core.svfiles import SvFileError, probe_lock
from wowtools.tools.ace_profiles.editor import SNAPSHOT_PREFIX, SNAPSHOT_SUBDIR, Marker, clear_marker
from wowtools.tools.ace_profiles.journal import read_profile_journal

CHANGED_SINCE = "changed since the change was made (WoW may have saved it); left as it is"


class UndoError(Exception):
    pass


class WowRunning(UndoError):
    def __init__(self, running: list[str]) -> None:
        super().__init__("WoW is running: " + ", ".join(running) + ". Close it first; it would overwrite the files.")
        self.running = running


@dataclass
class UndoOutcome:
    flavor: str
    rel: str
    path: Path | None
    status: str
    detail: str = ""


@dataclass
class UndoResult:
    outcomes: list[UndoOutcome] = field(default_factory=list)
    journal_path: Path | None = None
    snapshots: list[Path] = field(default_factory=list)

    def _with(self, status: str) -> list[UndoOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def restored(self) -> list[UndoOutcome]:
        return self._with("restored")

    @property
    def skipped(self) -> list[UndoOutcome]:
        return self._with("skipped")

    @property
    def failed(self) -> list[UndoOutcome]:
        return self._with("failed")


def destination(wow_root: Path, flavor: str, rel: str) -> Path | None:
    """<WoW>/<flavor>/<rel> when rel is WTF/Account/.../SavedVariables/<file>; None for anything else."""
    pure = PurePosixPath(rel)
    parts = pure.parts
    if pure.is_absolute() or ".." in parts or len(parts) < 5 or parts[:2] != ("WTF", "Account") \
            or parts[-2] != "SavedVariables" or "/" in flavor or "\\" in flavor or flavor in ("", ".", ".."):
        return None
    return wow_root.joinpath(flavor, *parts)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _put_back(zip_path: Path, rel: str, dest: Path, sha_before: str) -> str | None:
    """Write the original bytes of rel from zip_path over dest. Returns a problem, or None when done."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            original = zf.read(rel)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return f"its original could not be read from {zip_path.name}: {exc}"
    if _sha(original) != sha_before:
        return f"the copy in {zip_path.name} is not the original"
    try:
        atomic_write_bytes(dest, original)
    except OSError as exc:
        return f"could not be written: {exc.strerror or exc}"
    return None


def undo_run(journal_path: Path, *, wow_root: Path, root: Path, keep_snapshots: int,
             wow_check: Callable[[], list[str] | None] | None = None, now: datetime | None = None,
             progress: Callable[[str, int, int, str], None] | None = None) -> UndoResult:
    report = safe_progress(progress)
    journal = read_profile_journal(journal_path)
    entries = list(reversed(journal.entries))
    log_event("ace.undo_started", journal=journal_path.name, files=len(entries))
    if wow_check is not None:
        running = wow_check()
        if running:
            log_event("ace.wow_running", action="undo", running=running)
            raise WowRunning(running)
    targets = [(e, destination(wow_root, e["flavor"], e["rel"])) for e in entries]
    locked = []
    for entry, dest in targets:
        if dest is not None and dest.exists():
            try:
                error = probe_lock(dest)
            except SvFileError as exc:
                raise UndoError(f"{exc} Nothing was changed.") from exc
            if error is not None:
                locked.append(f"{entry['rel']} ({error})")
    if locked:
        log_event("ace.file_locked", action="undo", files=len(locked))
        raise UndoError(f"{len(locked)} files are locked by another program. Close it and undo again.\n  "
                        + "\n  ".join(locked[:10]))
    result = UndoResult(journal_path=journal_path)
    for folder in sorted({e["flavor"] for e in entries}):
        try:
            result.snapshots.append(take_snapshot(Flavor(folder, wow_root / folder), root / SNAPSHOT_SUBDIR,
                                                  SNAPSHOT_PREFIX, now or datetime.now(), progress=report))
        except BackupError as exc:
            log_event("ace.snapshot_failed", flavor=folder, error=str(exc))
            raise UndoError(f"The WTF backup before undo failed ({exc}). Nothing was changed.") from exc
    for index, (entry, dest) in enumerate(targets, 1):
        rel, flavor = entry["rel"], entry["flavor"]
        report("undo", index, len(targets), rel)
        if dest is None:
            result.outcomes.append(UndoOutcome(flavor, rel, None, "skipped", "it is outside the WTF folder"))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="outside")
            continue
        try:
            current = dest.read_bytes()
        except OSError:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, "skipped", "the file is gone"))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="gone")
            continue
        if _sha(current) != entry["sha_after"]:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, "skipped", CHANGED_SINCE))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="changed")
            continue
        problem = _put_back(entry["zip"], rel, dest, entry["sha_before"])
        if problem is None:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, "restored"))
            log_event("ace.file_restored", flavor=flavor, path=rel)
        else:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, "failed", problem))
            log_event("ace.undo_failed", flavor=flavor, path=rel, error=problem)
    if result.restored or not result.failed:
        mark_undone(journal_path, len(result.restored), len(result.skipped))
    level_bad = result.skipped or result.failed
    log_event("ace.undo_completed", restored=len(result.restored), skipped=len(result.skipped),
              failed=len(result.failed), level="warning" if level_bad else None)
    return result


def recover(marker: Marker, *, root: Path) -> UndoResult:
    """After an Apply that did not finish: put back every file of the marker that is not its original."""
    result = UndoResult()
    for rel, sha_before in sorted(marker.files.items()):
        dest = destination(marker.flavor_path.parent, marker.flavor, rel)
        if dest is None:
            result.outcomes.append(UndoOutcome(marker.flavor, rel, None, "skipped", "it is outside the WTF folder"))
            continue
        try:
            current = dest.read_bytes()
        except OSError:
            current = b""
        if _sha(current) == sha_before:
            continue
        problem = _put_back(marker.zip, rel, dest, sha_before)
        status = "restored" if problem is None else "failed"
        result.outcomes.append(UndoOutcome(marker.flavor, rel, dest, status, problem or ""))
        log_event("ace.file_restored" if problem is None else "ace.undo_failed", flavor=marker.flavor, path=rel)
    if not result.failed:
        clear_marker(root)
    log_event("ace.recovery_done", choice="put_back", restored=len(result.restored), failed=len(result.failed))
    return result
```

Note: check `log_event` for whether it takes a level override. If it doesn't, drop the `level=` keyword and log
`ace.undo_completed` at its registered level. Never invent a new kwarg API in `core/events.py`.

- [ ] **Step 4: Implement `multi.py`**

```python
"""Apply over one or several flavors with one journal for the whole run (spec §9). UI-free."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools import __version__
from wowtools.core.events import log_event
from wowtools.core.install import Flavor
from wowtools.core.journal import new_journal_path
from wowtools.tools.ace_profiles.editor import (EDITED_SUBDIR, ApplyError, ApplyResult, FileOutcome, apply_flavor,
                                                read_marker)
from wowtools.tools.ace_profiles.journal import ProfileJournal, prune_journals, referenced_zips
from wowtools.tools.ace_profiles.ops import DbState

EDITED_NAME = re.compile(r"^edited-.+-\d{8}-\d{6}(?:-\d+)?\.zip$")


class WowRunning(ApplyError):
    def __init__(self, running: list[str]) -> None:
        super().__init__("WoW is running: " + ", ".join(running) + ". Close it first; it would overwrite the changes.")
        self.running = running


@dataclass
class FlavorRun:
    flavor: Flavor
    result: ApplyResult | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error is not None:
            return "stopped"
        return "done" if self.result is not None else "not_started"


@dataclass
class MultiApplyResult:
    dry_run: bool
    runs: list[FlavorRun] = field(default_factory=list)
    journal_path: Path | None = None

    @property
    def outcomes(self) -> list[FileOutcome]:
        return [o for r in self.runs if r.result is not None for o in r.result.outcomes]

    def _with(self, status: str) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def edited(self) -> list[FileOutcome]:
        return self._with("edited")

    @property
    def would_edit(self) -> list[FileOutcome]:
        return self._with("would_edit")

    @property
    def skipped(self) -> list[FileOutcome]:
        return self._with("skipped")

    @property
    def failed(self) -> list[FileOutcome]:
        return self._with("failed")

    @property
    def rolled_back(self) -> list[FileOutcome]:
        return self._with("rolled_back")

    @property
    def stopped(self) -> FlavorRun | None:
        return next((r for r in self.runs if r.status == "stopped"), None)


def prune_edited_zips(root: Path, journal_dir: Path | None, keep_names: set[str] = frozenset()) -> list[Path]:
    """Delete edited-*.zip files no journal names any more (and not the crash marker's)."""
    folder = root / EDITED_SUBDIR
    marker = read_marker(root)
    keep = set(keep_names) | referenced_zips(journal_dir) | ({marker.zip.name} if marker else set())
    removed = []
    try:
        candidates = sorted(p for p in folder.iterdir() if EDITED_NAME.match(p.name) and p.is_file())
    except OSError:
        return []
    for path in candidates:
        if path.name not in keep:
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed


def apply_flavors(plan: list[tuple[Flavor, list[DbState]]], *, root: Path, journal_dir: Path, keep_journals: int,
                  keep_snapshots: int, dry_run: bool, account: str | None = None,
                  wow_check: Callable[[], list[str] | None] | None = None, now: datetime | None = None,
                  progress: Callable[[Flavor, str, int, int, str], None] | None = None) -> MultiApplyResult:
    now = now or datetime.now()
    if not dry_run and wow_check is not None:
        running = wow_check()
        if running:
            log_event("ace.wow_running", action="apply", running=running)
            raise WowRunning(running)
    result = MultiApplyResult(dry_run, [FlavorRun(flavor) for flavor, _ in plan])
    journal = None
    if not dry_run:
        journal = ProfileJournal(new_journal_path(journal_dir, now),
                                 {"tool": "ace-profiles", "kind": "apply", "flavors": [f.folder for f, _ in plan],
                                  "root": root, "suite_version": __version__})
        result.journal_path = journal.path
    try:
        for run, (flavor, states) in zip(result.runs, plan):
            report = None if progress is None else (lambda *a, f=flavor: progress(f, *a))
            try:
                run.result = apply_flavor(flavor, states, root=root, journal=journal, dry_run=dry_run,
                                          keep_snapshots=keep_snapshots, account=account, now=now, progress=report)
            except ApplyError as exc:
                run.error = str(exc)
                later = [r.flavor.folder for r in result.runs if r.status == "not_started" and r is not run]
                if later:
                    log_event("ace.flavors_stopped", flavor=flavor.folder, not_started=later)
                break
    finally:
        if journal is not None:
            if journal.count:
                journal.finish()
            journal.discard_if_empty()
            if not journal.opened:
                result.journal_path = None
    if not dry_run:
        prune_journals(journal_dir, keep_journals)
        prune_edited_zips(root, journal_dir)
        edited = len(result.edited)
        log_event("ace.apply_completed", files=edited, skipped=len(result.skipped),
                  stopped=result.stopped.flavor.folder if result.stopped else None)
    return result
```

Note: `ApplyError` from `apply_flavor` is caught per flavor. A `WowRunning` raised before the loop propagates
(the UI shows it). `test_stops_at_failing_flavor` reads `result.stopped.error`.

- [ ] **Step 5: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_undo`, `-k ace_multi`, `-k ace`. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add wowtools/tools/ace_profiles/undo.py wowtools/tools/ace_profiles/multi.py tests/test_ace_undo.py tests/test_ace_multi.py
git commit -m "feat(ace-profiles): undo, crash recovery and All flavors"
```

---

### Task 10: report helpers (UI-free text for the tree, popups and results)

**Files:**
- Create: `wowtools/tools/ace_profiles/report.py`
- Test: `tests/test_ace_report.py`

**Interfaces:**
- Consumes: `ops.DbState`, `Summary`; `model.DEFAULT`; `multi.MultiApplyResult`; `undo.UndoResult`.
- Produces (all in `report`):
  - `STAGE_TITLES: dict[str, str]` for the stages `check`, `lock_check`, `snapshot_list`, `snapshot`,
    `snapshot_verify`, `backup`, `edit`, `undo`.
  - `plural(n: int, word: str, words: str | None = None) -> str` (`"1 profile"`, `"3 profiles"`).
  - `@dataclass CharRow(char: str, tags: list[str], removed: bool)`.
  - `@dataclass ProfileRow(name: str, deleted: bool, tags: list[str], chars: list[CharRow])` with
    `.label -> str`.
  - `profile_rows(state: DbState) -> list[ProfileRow]`. Order: staged names (`state.names()`), then deleted
    originals.
  - `char_tags(state: DbState, char: str) -> list[str]`.
  - `selection_text(profiles: int, chars: int, summary: Summary, warnings: int) -> str`.
  - `staged_text(summary: Summary) -> str`.
  - `apply_confirm(summary: Summary, states: list[DbState], *, dry_run: bool) -> tuple[str, str, list[str]]`
    (title, body, alerts).
  - `undo_confirm(journal) -> tuple[str, str, list[str]]`.
  - `apply_summary_rows(result: MultiApplyResult) -> list[tuple[str, str]]`.
  - `apply_detail_rows(result: MultiApplyResult) -> list[tuple[str, str, str, str, str]]`
    (flavor, account, addon, change, result).
  - `undo_summary_rows(result: UndoResult) -> list[tuple[str, str]]` and
    `undo_detail_rows(result: UndoResult) -> list[tuple[str, str, str]]` (flavor, file, result).
  - `DETAIL_COLUMNS = ("Flavor", "Account", "Addon", "Change", "Result")`,
    `UNDO_COLUMNS = ("Flavor", "File", "Result")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ace_report.py
"""report: labels, tags, summary lines and result rows."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import ops, report, scanner


class ReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_ace_tree(Path(tmp.name) / "wow")
        scan = scanner.ScanResult([scanner.scan_flavor(WowInstall(root).flavor("_retail_"), account="ACCT1")])
        self.staging = ops.Staging.from_scan(scan)

    def st(self, sv_name):
        return next(s for s in self.staging.states.values() if s.db.sv_name == sv_name)

    def rows(self, sv_name):
        return {r.name: r for r in report.profile_rows(self.st(sv_name))}

    def test_tags_on_a_fresh_database(self):
        rows = self.rows("KickCDDB")
        self.assertEqual(rows["Default"].tags, ["Default"])
        self.assertEqual(rows["Default"].label, "Default · 3 characters · Default")
        self.assertIn("unused", rows["Backup"].tags)
        self.assertIn("empty", rows["Backup"].tags)
        gone = next(c for c in rows["Default"].chars if c.char == "Gone - Realm1")
        self.assertIn("no character folder", gone.tags)

    def test_missing_and_lds_tags(self):
        self.assertIn("missing", self.rows("StockDB")["Gone"].tags)
        kaelys = next(c for c in self.rows("ElvDB")["Default"].chars if c.char == "Kaelys - Realm1")
        self.assertIn("spec profiles", kaelys.tags)

    def test_staged_marks(self):
        key = self.st("ElvDB").key
        self.staging.copy(key, "Default", "Spare")
        self.staging.delete({key: ["Healer"]}, "Default")
        rows = self.rows("ElvDB")
        self.assertTrue(rows["Healer"].deleted)
        self.assertIn("✘ deleted", rows["Healer"].label)
        self.assertIn("copy of Default", rows["Spare"].tags)
        mierin = next(c for c in rows["Default"].chars if c.char == "Mierin - Khaz Modan")
        self.assertIn("was Healer", mierin.tags)
        self.staging.rename(key, "Spare", "Tank")
        self.assertIn("copy of Default", self.rows("ElvDB")["Tank"].tags)

    def test_removed_character_stays_under_its_profile(self):
        key = self.st("KickCDDB").key
        self.staging.remove_leftovers({key: ["Gone - Realm1"]})
        gone = next(c for c in self.rows("KickCDDB")["Default"].chars if c.char == "Gone - Realm1")
        self.assertTrue(gone.removed)
        self.assertIn("✘ removed", gone.tags)

    def test_selection_and_staged_text(self):
        self.assertEqual(report.selection_text(0, 0, ops.Summary(), 0),
                         "Selected: 0 profiles · 0 characters · Nothing staged")
        summary = ops.Summary(deleted=2, reassigned=5, renamed=1, files=2)
        self.assertEqual(report.staged_text(summary), "2 deletes · 1 rename · 5 reassigns")
        self.assertEqual(report.selection_text(1, 3, summary, 2),
                         "Selected: 1 profile · 3 characters · Staged: 8 changes in 2 files · ⚠ 2 scan warnings")

    def test_apply_confirm_alerts(self):
        key = self.st("ElvDB").key
        self.staging.delete({key: ["Default"]}, "Healer")
        self.staging.assign({self.st("HandyNotesDB").key: ["Kaelys - Realm1"]}, "Default")
        title, body, alerts = report.apply_confirm(self.staging.summary(), self.staging.changed(), dry_run=False)
        self.assertIn("Apply", title)
        self.assertIn("2 files", body)
        self.assertTrue(any("Default" in a and "deleted" in a for a in alerts))
        self.assertTrue(any("next login" in a for a in alerts))
        self.assertTrue(any("LibDualSpec" in a for a in alerts))

    def test_plural(self):
        self.assertEqual(report.plural(1, "profile"), "1 profile")
        self.assertEqual(report.plural(2, "copy", "copies"), "2 copies")
```

- [ ] **Step 2: Run to see it fail**

Run: `python3 scripts/run_tests.py -k ace_report`. Expected: ImportError.

- [ ] **Step 3: Implement `report.py`**

```python
"""Text for the Ace3 Profile Manager's screens: tree labels and tags, the bottom line, confirm texts and result
rows (UI-free)."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowtools.core.install import FLAVOR_NAMES
from wowtools.core.journal import Journal, friendly_stamp
from wowtools.tools.ace_profiles.model import DEFAULT
from wowtools.tools.ace_profiles.multi import MultiApplyResult
from wowtools.tools.ace_profiles.ops import CopyOf, DbState, Original, Summary
from wowtools.tools.ace_profiles.undo import UndoResult

STAGE_TITLES = {
    "check": "Checking the files", "lock_check": "Checking for locked files",
    "snapshot_list": "Listing the WTF folder", "snapshot": "Backing up the WTF folder",
    "snapshot_verify": "Checking the WTF backup", "backup": "Saving the original files",
    "edit": "Writing the changes", "undo": "Putting files back",
}
DETAIL_COLUMNS = ("Flavor", "Account", "Addon", "Change", "Result")
UNDO_COLUMNS = ("Flavor", "File", "Result")
DELETED = "✘ deleted"
REMOVED = "✘ removed"
RESULT_TEXT = {"edited": "changed", "would_edit": "would change", "skipped": "skipped", "failed": "failed",
               "rolled_back": "put back"}


def plural(n: int, word: str, words: str | None = None) -> str:
    return f"{n} {word if n == 1 else (words or word + 's')}"


def flavor_name(folder: str) -> str:
    return FLAVOR_NAMES.get(folder) or folder.strip("_").replace("_", " ").title()


@dataclass
class CharRow:
    char: str
    tags: list[str] = field(default_factory=list)
    removed: bool = False

    @property
    def label(self) -> str:
        return " · ".join([self.char, *self.tags])


@dataclass
class ProfileRow:
    name: str
    deleted: bool = False
    tags: list[str] = field(default_factory=list)
    chars: list[CharRow] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.deleted:
            return " · ".join([self.name, *self.tags])
        live = sum(1 for c in self.chars if not c.removed)
        return " · ".join([self.name, plural(live, "character"), *self.tags])


def char_tags(state: DbState, char: str) -> list[str]:
    tags = []
    if char in state.leftovers:
        tags.append("no character folder")
    if state.db.lds_enabled(char):
        tags.append("spec profiles")
    old, new = state.db.profile_keys.get(char), state.keys.get(char)
    if new is None and old is not None:
        tags.append(REMOVED)
    elif old is not None and new != old:
        tags.append(f"was {old}")
    return tags


def profile_rows(state: DbState) -> list[ProfileRow]:
    rows: dict[str, ProfileRow] = {}
    for name in state.names():
        tags = []
        if name == DEFAULT:
            tags.append("Default")
        source = state.profiles.get(name)
        if isinstance(source, Original) and source.name != name:
            tags.append(f"renamed from {source.name}")
        if isinstance(source, CopyOf):
            tags.append(f"copy of {source.name}")
        if state.missing(name):
            tags.append("missing")
        elif not state.users(name):
            tags.append("unused")
        if isinstance(source, Original) and state.db.profiles[source.name].empty:
            tags.append("empty")
        rows[name] = ProfileRow(name, False, tags, [CharRow(c, char_tags(state, c)) for c in state.users(name)])
    for name in state.changes().deleted:
        rows.setdefault(name, ProfileRow(name, True, [f"{DELETED}"]))
    for char, old in state.db.profile_keys.items():
        if state.keys.get(char) is None:
            row = rows.get(old) or next((r for r in rows.values() if r.deleted), None)
            if row is None:
                row = rows.setdefault(old, ProfileRow(old, False, ["missing"]))
            row.chars.append(CharRow(char, char_tags(state, char), removed=True))
    return list(rows.values())


def staged_text(summary: Summary) -> str:
    parts = [(summary.deleted, "delete"), (summary.renamed, "rename"), (summary.copied, "copy", "copies"),
             (summary.reassigned, "reassign"), (summary.removed, "removed character"),
             (summary.lds, "spec profile")]
    text = " · ".join(plural(*p) for p in parts if p[0])
    return text or "Nothing staged"


def selection_text(profiles: int, chars: int, summary: Summary, warnings: int) -> str:
    staged = (f"Staged: {plural(summary.total, 'change')} in {plural(summary.files, 'file')}" if summary.total
              else "Nothing staged")
    text = f"Selected: {plural(profiles, 'profile')} · {plural(chars, 'character')} · {staged}"
    if warnings:
        text += f" · ⚠ {plural(warnings, 'scan warning')}"
    return text


def apply_confirm(summary: Summary, states: list[DbState], *, dry_run: bool) -> tuple[str, str, list[str]]:
    title = "Dry run" if dry_run else "Apply the staged changes?"
    lines = [f"{staged_text(summary)} in {plural(summary.files, 'file')}."]
    if dry_run:
        lines.append("Every change is checked in memory; no file is written.")
    else:
        lines.append("A backup of the whole WTF folder and of every file changed is taken first. Undo (z) puts "
                     "the files back.")
    alerts = []
    for state in states:
        changes = state.changes()
        addon = state.file.addon
        if DEFAULT in changes.deleted:
            alerts.append(f'{addon}: the "Default" profile will be deleted.')
        targets = {new for _, _, new in changes.reassigned}
        for name in sorted(t for t in targets if not state.exists(t)):
            alerts.append(f'{addon}: "{name}" does not exist yet; the addon creates it at the next login with its '
                          f"defaults.")
        if any(state.db.lds_enabled(c) for c, _, _ in changes.reassigned):
            alerts.append(f"{addon}: LibDualSpec switches some of these characters' profile by spec; it will "
                          f"override the change at login.")
    return title, "\n".join(lines), alerts


def undo_confirm(journal: Journal) -> tuple[str, str, list[str]]:
    files = len(journal.entries)
    body = (f"Put back {plural(files, 'file')} changed {friendly_stamp(journal.started)}. A file saved since "
            f"(by WoW) is left as it is.")
    return "Undo the last change?", body, []


def apply_summary_rows(result: MultiApplyResult) -> list[tuple[str, str]]:
    verb = "Would change" if result.dry_run else "Changed"
    rows = [(f"{verb}", plural(len(result.would_edit if result.dry_run else result.edited), "file"))]
    if result.skipped:
        rows.append(("Skipped", plural(len(result.skipped), "file")))
    if result.rolled_back:
        rows.append(("Put back after a failure", plural(len(result.rolled_back), "file")))
    if result.stopped:
        rows.append(("Stopped", f"{flavor_name(result.stopped.flavor.folder)}: {result.stopped.error}"))
    for run in result.runs:
        if run.result is not None and run.result.snapshot is not None:
            rows.append((f"WTF backup ({flavor_name(run.flavor.folder)})", str(run.result.snapshot)))
        if run.result is not None and run.result.backup_zip is not None:
            rows.append((f"Original files ({flavor_name(run.flavor.folder)})", str(run.result.backup_zip)))
    if result.journal_path is not None:
        rows.append(("Journal", str(result.journal_path)))
    return rows


def apply_detail_rows(result: MultiApplyResult) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for outcome in result.outcomes:
        file = outcome.file
        state = RESULT_TEXT.get(outcome.status, outcome.status)
        if outcome.detail:
            state += f": {outcome.detail}"
        for change in outcome.changes or [""]:
            rows.append((flavor_name(file.flavor.folder), file.account, file.addon, change, state))
    return rows


def undo_summary_rows(result: UndoResult) -> list[tuple[str, str]]:
    rows = [("Put back", plural(len(result.restored), "file"))]
    if result.skipped:
        rows.append(("Left as they are", plural(len(result.skipped), "file")))
    if result.failed:
        rows.append(("Failed", plural(len(result.failed), "file")))
    rows += [("WTF backup", str(p)) for p in result.snapshots]
    return rows


def undo_detail_rows(result: UndoResult) -> list[tuple[str, str, str]]:
    return [(flavor_name(o.flavor), o.rel, o.status + (f": {o.detail}" if o.detail else ""))
            for o in result.outcomes]
```

Check: `FLAVOR_NAMES` is the mapping `core/install.py` uses for `Flavor.display_name`. Import it from there. If it
is private, use `Flavor(folder, Path(folder)).display_name` instead.

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_report`, then `-k ace`. Expected: all pass.

- [ ] **Step 5: Commit and push milestone 2**

```bash
git add wowtools/tools/ace_profiles/report.py tests/test_ace_report.py
git commit -m "feat(ace-profiles): report helpers"
git push
```

---
## Milestone 3: screens (Tasks 11–14), push after Task 14

The UI tasks follow existing screens closely. Before writing any of them, read:
- `wowtools/tools/wtf_cleaner/app.py`: the flow and settings screen this tool mirrors.
- `wowtools/tools/interface_backup/review_screen.py`: the two-pane review screen, its `READ_ONLY` kinds, scan worker,
  `_refresh_buttons`, `idle` and `wow_folder_changed`.
- `wowtools/tools/wtf_cleaner/review_screen.py`: ticks with `tick_mark` / `relabel_branch`, the debounced rebuild,
  `RecoveryScreen`, and the preflight → confirm → progress → result run flow.
- `wowtools/ui/dialogs.py` and `wowtools/ui/widgets.py`: the shared pieces. Never redefine them.

Copy patterns, not code from another tool's module by import. TUI tests subclass `tests.fixtures.TuiTestCase` and
use `settle`. The selectors and helper calls in the tests below are the intended ones. If a Textual detail forces a
different mechanic (for example how a `Select` is driven in a test), adapt the mechanic but keep every assertion.

### Task 11: flow, settings screen, registration (the tool opens)

**Files:**
- Create: `wowtools/tools/ace_profiles/app.py` (`ProfileSettingsScreen`, `AceProfilesFlow`, `FLOW`)
- Create: `wowtools/tools/ace_profiles/review_screen.py`. In this task it is only a stub `ProfileReviewScreen` with
  the four buttons, hint, `#summary` and an empty tree, enough for the flow; Task 12 fills it.
- Create: `docs/ace-profiles.md` (stub: title, back link, one paragraph; Task 15 writes the guide)
- Modify: `wowtools/tools/__init__.py` (add the `Tool`)
- Modify: `README.md` (a row in "The tools" and a link under "Tool guides", in the shape of the other three)
- Modify: `tests/fixtures.py` (nothing new; `build_ace_tree` is used by the tests below)
- Test: `tests/test_ace_app.py`

**Interfaces:**
- Consumes: `settings.*`; `ui.tool_flow.ToolFlow`; `ui.flavor_screen.FlavorScreen`, `ALL_FLAVORS`;
  `ui.account_screen.AccountScreen`; `ui.dialogs.settings_css`; `ui.widgets` (`FormScroll`, `ButtonRow`,
  `action_button`).
- Produces:
  - `Tool("ace-profiles", "Ace3 Profile Manager", "See and change which Ace3 profile each character uses.",
    "wowtools.tools.ace_profiles.app", "ace_profiles")` in `TOOLS`, after Interface Backup.
  - `ProfileSettingsScreen(Screen[bool])`: `__init__(tool_cfg, wow_path, *, source)`, fields `#backup-dir`
    (Input), `#keep-snapshots` (Input), `#keep-journals` (Input), `#blacklist` (Input, comma-separated), a
    `#settings-error` Static, Save/Cancel; `_save()` validates and calls `save_settings`; `.title` heading
    "Ace3 Profile Manager settings". Built like `CleanerSettingsScreen` in `wtf_cleaner/app.py:35-130`.
  - `AceProfilesFlow(ToolFlow)`: `__init__(app, tool_cfg, *, wow_check=None)`, `start()`, `open_settings()`,
    attribute `unlocked: set[str]` (casefolded addon names unlocked this session; kept on the flow, so it survives
    going back to the flavor picker and returning, and is gone once the tool closes).
  - `ProfileReviewScreen(Screen[str])`: `__init__(cfg, tool_cfg, flavors: list[Flavor], scope_label: str, *,
    account: str | None, unlocked: set[str], wow_check=None)`. It dismisses with `"flavors"`, `"tools"` or
    `"quit"`. It has `summary_text: str` and `sub_title = f"Ace3 Profile Manager · {scope_label}"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ace_app.py
"""Ace3 Profile Manager screens (flow, settings, review, popups, apply, undo, recovery)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Input

from tests.fixtures import TuiTestCase, build_ace_tree, make_config, settle
from wowtools.core.config import Config
from wowtools.tools.ace_profiles.app import ProfileSettingsScreen
from wowtools.tools.ace_profiles.review_screen import ProfileReviewScreen
from wowtools.tools.ace_profiles.settings import load_settings
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp

TOOL = "ace-profiles"


class AceAppBase(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.root = build_ace_tree(self.tmp / "World of Warcraft")
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        self.running: list[str] = []

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={TOOL: {"wow_check": lambda: list(self.running)}})

    async def open_review(self, app, pilot, choice=ALL_FLAVORS):
        await pilot.pause()
        app.open_tool(TOOL)
        await settle(app, pilot)
        if isinstance(app.screen, ProfileSettingsScreen):
            app.screen._save()
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        app.screen.dismiss(choice)
        await settle(app, pilot)
        if not isinstance(app.screen, ProfileReviewScreen):  # one flavor with several accounts: the picker
            app.screen.dismiss("")
            await settle(app, pilot)
        self.assertIsInstance(app.screen, ProfileReviewScreen)
        return app.screen


class FlowTest(AceAppBase):
    async def test_first_open_shows_settings_then_flavors(self):
        app = self.make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.open_tool(TOOL)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileSettingsScreen)
            app.screen.query_one("#blacklist", Input).value = "ElvUI, Questie"
            app.screen._save()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
        saved = load_settings(Config(self.config_dir / "ace-profiles.cfg").load())
        self.assertEqual(saved.blacklist, ["ElvUI", "Questie"])

    async def test_settings_refuse_a_folder_inside_wtf(self):
        app = self.make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.open_tool(TOOL)
            await settle(app, pilot)
            screen = app.screen
            screen.query_one("#backup-dir", Input).value = str(self.root / "_retail_" / "WTF" / "x")
            screen._save()
            await settle(app, pilot)
            self.assertIs(app.screen, screen)
            self.assertTrue(str(screen.query_one("#settings-error").render()))

    async def test_all_flavors_review_and_escape_back(self):
        app = self.make_app()
        async with app.run_test() as pilot:
            review = await self.open_review(app, pilot)
            self.assertTrue(review.sub_title.startswith("Ace3 Profile Manager · All flavors"))
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
```

- [ ] **Step 2: Run to see it fail**

Run: `python3 scripts/run_tests.py -k ace_app`. Expected: ImportError.

- [ ] **Step 3: Implement**

- `app.py`: mirror `wtf_cleaner/app.py` (settings screen, `_default_backup_hint`, flow), with these differences:
  - **Settings fields:** backup folder (empty means `<WoW folder>/wow-tools`, hint shows the resolved
    `.../ace-profiles`), "WTF backups to keep per flavor" (`keep_snapshots`), "Journals to keep" (`keep_journals`),
    "Blacklist (addon names, comma-separated)" (`blacklist`).
  - **Validation:** numbers must be integers ≥ 1; the backup folder goes through `validate_backup_dir`.
  - **Flow:** the same steps and remembered choices as `WtfCleanerFlow`: `last_flavor_choice` and `last_account`
    via `save_settings(..., source="picker")`, and an account picker only for one flavor with several accounts.
  - The flow keeps `self.unlocked = set()` and passes it, by reference, to every `ProfileReviewScreen` it pushes.
  - `wow_check`: when none is given, the review builds `wow_check_for(flavors)` from `core.process`.
  - Last line: `FLOW = AceProfilesFlow`.
- `review_screen.py` stub: compose the two-pane layout exactly as Task 12 describes (filters pane with sections,
  `ButtonRow(id="actions", wrap=False)` holding Apply (`delete` variant), Dry run (`simulate`), Rescan (`neutral`),
  Undo last change (`revert`), the `NavHint`, `#scan-box`, the `ProfileTree` `#profiles`, `#summary`, `BrandBar`,
  `Footer`). Bind `f`/Esc → `dismiss("flavors")`, `t` → `"tools"`, `q` → `"quit"`. Set
  `summary_text = "Selected: 0 profiles · 0 characters · Nothing staged"`.
- `wowtools/tools/__init__.py`: add the `Tool` line.
- `README.md`: add a row to "The tools" and a bullet to "Tool guides" linking `docs/ace-profiles.md`, worded like
  the others. `docs/ace-profiles.md` stub: `# Ace3 Profile Manager`, the back link
  `[← Back to the main page](../README.md)`, one paragraph saying what it does.
- Run `python3 scripts/gen_event_docs.py` (registration can change the rendered tool list).

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_app`, `-k docs`, `-k suite`, `-k structure`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools/ace_profiles wowtools/tools/__init__.py README.md docs tests/test_ace_app.py
git commit -m "feat(ace-profiles): register the tool, flow and settings screen"
```

---

### Task 12: the review screen: scan, tree (both views), ticks, filters, search, blacklist

**Files:**
- Modify: `wowtools/tools/ace_profiles/review_screen.py`
- Test: `tests/test_ace_app.py` (add `ReviewTest`)

**Interfaces:**
- Consumes: `scanner.scan_flavors`, `ScanResult`; `ops.Staging`, `DbKey`; `report.profile_rows`, `char_tags`,
  `selection_text`, `staged_text`, `plural`; `settings.load_settings`, `save_settings`, `is_blacklisted`;
  `ui.dialogs` (`two_pane_css`, `REVIEW_HINT`, `tick_mark`, `relabel_branch`, `TwoPaneFocus`, `theme_colour`,
  `BUSY_STYLE`); `ui.widgets` (`Ka0sCheckbox`, `ButtonRow`, `NavHint`, `action_button`, `NAV_BINDINGS`).
- Produces, on `ProfileReviewScreen`:
  - `scan: ScanResult | None` and `staging: Staging | None`.
  - `ticked: set[tuple]`: `("p", DbKey, profile)` and `("c", DbKey, char)` tuples. Nothing is ticked after a scan.
  - `view: str` (`"addon"` or `"character"`).
  - `undoable: Path | None` (the newest undoable journal, looked up in the scan worker).
  - `selected_profiles() -> dict[DbKey, list[str]]` and `selected_chars() -> dict[DbKey, list[str]]`: the ticks,
    or the highlighted node when nothing is ticked.
  - `locked(addon: str) -> bool` (blacklisted and not unlocked).
  - `refresh_view() -> None` (rebuild the tree and bottom line, keeping ticks and expansion).
  - `NAV_HINT = REVIEW_HINT + "a all · n none · d delete · p assign · m more · w apply · y dry run · r rescan · z undo · f flavors · t tools"`.

Behaviour (spec §13):
- **Scan.** On mount and on `r`, run a thread worker (`group="scan"`, `exclusive=True`) that calls
  `scanner.scan_flavors(flavors, account=account, progress=...)`. Progress goes through `call_from_thread` to
  `#scan-box` (`ProgressBar` and label "Reading SavedVariables: <file>"). The worker also looks up
  `journal.latest_undoable(resolve_journal_dir(wow))` and `editor.read_marker(root)`. When it finishes:
  - `self.staging = Staging.from_scan(scan, locked=self.locked)`;
  - clear `ticked`;
  - rebuild the tree;
  - if a marker was found, push the recovery popup (Task 14).

  Rescan while something is staged first asks `ConfirmScreen("Discard staged changes?", ...)`.
- **Tree, By addon view.** The root label is the scope. Below it:
  - flavor (only when several), then account;
  - addon: the file name, plus " (Realm/Name)" for a per-character file; tags "blacklisted", "unlocked";
  - database: only when the file has more than one;
  - profile: label from `ProfileRow.label`;
  - character leaves: `CharRow.label`.

  Every node is built when the tree is built (no lazy loading: a whole install has well under a thousand
  nodes), so tests and `a` see every key. Account nodes start expanded, addon nodes collapsed. Scan warnings go under a final "⚠ Scan warnings" node
  (read-only). A flavor with `error` is a leaf showing the error in the warning colour. An account with no AceDB
  data shows "no Ace3 data".
- **Tree, By character view.** flavor → account → character (every char key in any database of that account,
  sorted ignoring case, tagged "no character folder" for a leftover) → `"<Addon> (<db if several>): <profile>"`
  leaves, carrying the `("c", DbKey, char)` tick key and the same "was X" / "✘ removed" tags as `char_tags`.
- **Node data** is a tuple whose first item is the kind: `("flavor", ...)`, `("account", ...)`,
  `("addon", AddonFile)`, `("db", DbKey)`, `("profile", DbKey, name)`, `("char", DbKey, char)`,
  `("character", account_label, char)`, `("pair", DbKey, char)`, `("deleted", DbKey, name)`,
  `("removed", DbKey, char)`, `("note", text)`, `("warnings", list)`.
  - `READ_ONLY = ("deleted", "removed", "note", "warnings")`.
  - A node whose addon is locked is read-only too: `_tick_keys(node)` returns nothing for it, and its label has
    no mark, only `"  "`.
- **Ticks.**
  - `_tick_keys(node)` returns the tick tuples under a node: a profile gives its `"p"` key; a character or pair
    gives its `"c"` key; a group gives every key below it that is not locked or read-only.
  - The mark comes from `tick_mark(keys, NotTicked(self.ticked))`, where `NotTicked` is a tiny `Collection`
    whose `__contains__(k)` is `k not in ticked`.
  - Space toggles the highlighted node's keys: all on if any is off, else all off.
  - `a` ticks every visible key and `n` clears all.
  - Relabel with `relabel_branch(tree, node, self._label, skip=READ_ONLY)`.
- **Filters** (left pane, `Label(..., classes="section")` headings):
  - "View": `Ka0sCheckbox("By addon", id="view-addon", value=True)` and `Ka0sCheckbox("By character",
    id="view-character")`, which behave as a pair (ticking one unticks the other); `v` switches.
  - "Show": `#only-multi` "Only addons with 2+ profiles", `#only-unused` "Only unused profiles",
    `#show-leftovers` "Leftover characters" (on), `#show-blacklisted` "Blacklisted addons" (on).
  - "Search": `Input(id="search", placeholder="addon, profile or character")`, matched case-insensitively against
    addon, database, profile and character names. A branch is kept when anything inside it matches. `/` focuses
    the search box.
  - "Staged": `Static(id="staged")` showing `report.staged_text(staging.summary())`.
  - Every filter change schedules the debounced rebuild (`_schedule_rebuild`, as in the WTF Cleaner).
  - Hidden items keep their ticks, but `a` only ticks visible ones.
- **Blacklist.**
  - `b` on a node inside an addon adds that addon to `settings.blacklist`, or removes it (`parse_blacklist`
    order). It saves immediately with `save_settings(tool_cfg, settings, source="review")`, logs
    `ace.blacklist_changed` (addon, blacklisted), unticks that addon's keys and rebuilds.
  - `u` adds the addon's casefolded name to the flow's `unlocked` set (logs `ace.unlocked`) or removes it again.
  - `locked(addon)` is `is_blacklisted(settings.blacklist, addon) and addon.casefold() not in unlocked`.
    `Staging.from_scan(..., locked=self.locked)` uses it, so operations refuse locked addons too.
- **Bottom line.** `#summary` shows
  `summary_text = report.selection_text(profiles, chars, staging.summary(), len(scan.warnings))`, where profiles
  and chars count the ticked keys of each kind. `#staged` is updated at the same time.
- **Buttons.** `_refresh_buttons()`:
  - Apply and Dry run are enabled when idle and something is staged;
  - Rescan when idle;
  - Undo when idle and `undoable` is set.

  `idle` follows Interface Backup (`not scanning and not app.busy`).
- **Keys** (BINDINGS): space, a, n, d, p, e, k, o, m, x, b, u, v, slash, w, y, r, z, f, escape, t, q, left, right,
  plus `NAV_BINDINGS`. In this task, d/p/e/k/o/m/x/w/y/z call methods that just `notify("…")`; Tasks 13 and 14 fill
  them in.

- [ ] **Step 1: Add the failing tests**

```python
# tests/test_ace_app.py — add
from textual.widgets import Tree  # noqa: E402  (keep the import block sorted when merging)

from wowtools.core.install import WowInstall  # noqa: E402


def labels(tree):
    out, stack = [], [tree.root]
    while stack:
        node = stack.pop()
        out.append(str(node.label))
        stack.extend(reversed(node.children))
    return out


def find(tree, kind, *rest):
    stack = [tree.root]
    while stack:
        node = stack.pop()
        if node.data and node.data[0] == kind and all(r in node.data for r in rest):
            return node
        stack.extend(node.children)
    raise AssertionError(f"no {kind} node {rest}")


def find_addon(tree, name, account="ACCT1"):
    stack = [tree.root]
    while stack:
        node = stack.pop()
        if node.data and node.data[0] == "addon" and node.data[1].file.addon == name \
                and node.data[1].file.account == account:
            return node
        stack.extend(node.children)
    raise AssertionError(f"no addon node {name}")


class ReviewTest(AceAppBase):
    async def test_tree_shows_databases_profiles_and_characters(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            for node in list(tree.root.children):
                node.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            for expected in ("Retail", "Classic Era", "ACCT1", "KickCD", "ElvUI", "ElvDB", "ElvPrivateDB",
                             "Default · 3 characters · Default", "unused", "missing",
                             "Gone - Realm1 · no character folder", "spec profiles", "Scan warnings"):
                self.assertIn(expected, text)
            self.assertNotIn("KickCDPerfDB", text)
            self.assertNotIn("Memento", text.replace("Memento.lua", ""))
            self.assertEqual(review.ticked, set())
            self.assertTrue(review.summary_text.startswith("Selected: 0 profiles · 0 characters"))

    async def test_tick_a_profile_and_summary_counts(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            node = find(tree, "profile", "Healer")
            node.parent.expand()
            tree.move_cursor(node)
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(len([k for k in review.ticked if k[0] == "p"]), 1)
            self.assertTrue(review.summary_text.startswith("Selected: 1 profile · 0 characters"))
            await pilot.press("n")
            await settle(app, pilot)
            self.assertEqual(review.ticked, set())

    async def test_blacklist_greys_out_and_unlock(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            tree.move_cursor(find_addon(tree, "ElvUI"))
            await pilot.press("b")
            await settle(app, pilot)
            self.assertTrue(review.locked("ElvUI"))
            self.assertIn("blacklisted", "\n".join(labels(tree)))
            self.assertEqual(load_settings(Config(self.config_dir / "ace-profiles.cfg").load()).blacklist, ["ElvUI"])
            tree.move_cursor(find_addon(tree, "ElvUI"))
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(review.ticked, set())  # locked: nothing to tick
            await pilot.press("u")
            await settle(app, pilot)
            self.assertFalse(review.locked("ElvUI"))
            self.assertIn("unlocked", "\n".join(labels(tree)))

    async def test_character_view_and_search(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("v")
            await settle(app, pilot)
            self.assertEqual(review.view, "character")
            tree = review.query_one("#profiles", Tree)
            tree.root.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            self.assertIn("Kaelys - Realm1", text)
            self.assertIn("KickCD: Default", text)
            review.query_one("#search", Input).value = "mierin"
            await settle(app, pilot)
            tree.root.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            self.assertIn("Mierin - Khaz Modan", text)
            self.assertNotIn("Kaelys - Realm1", text)

    async def test_only_unused_filter(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot, choice=WowInstall(self.root).flavor("_retail_"))
            review.query_one("#only-unused").value = True
            await settle(app, pilot)
            tree = review.query_one("#profiles", Tree)
            tree.root.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            self.assertIn("Backup", text)
            self.assertNotIn("Healer", text)
```

`test_only_unused_filter` picks Retail, so the account picker shows; `open_review` dismisses it with `""` (all
accounts).

- [ ] **Step 2: Run to see them fail**

Run: `python3 scripts/run_tests.py -k ace_app`. Expected: the new tests fail.

- [ ] **Step 3: Implement the review screen as described above**

Keep the screen under about 700 lines. If it grows past that, move the tree building
(`build_addon_view(tree, scan, staging, filters)` and `build_character_view(...)`) into a UI module
`wowtools/tools/ace_profiles/tree_view.py`. Count it as a fifth UI module in the Global Constraints. Its node
labels come from `report`.

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_app`, then `-k ace`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools/ace_profiles tests/test_ace_app.py
git commit -m "feat(ace-profiles): review screen with tree views, ticks, filters, search and blacklist"
```

---

### Task 13: popups and staging from the tree

**Files:**
- Create: `wowtools/tools/ace_profiles/popups.py`
- Modify: `wowtools/tools/ace_profiles/review_screen.py` (d, p, e, k, o, m, x)
- Test: `tests/test_ace_app.py` (add `StagingTest`)

**Interfaces:**
- Produces in `popups.py` (all `ModalScreen`s styled like `ConfirmScreen`: a centred box with a `$accent` border,
  `.title`, body, buttons right-aligned, Esc cancels):
  - `TargetScreen(ModalScreen[str | None])`: `__init__(title: str, body: str, targets: list[str],
    default: str = "Default")`. A `Select(id="target")` of `targets`, preselected `default` (added at the top
    when missing). An `Input(id="new-name", placeholder="or type a new profile name")` overrides the select when
    not blank. `#target-error` shows `ops.valid_name` problems. OK (`#ok`) dismisses the name and Cancel
    (`#cancel`) dismisses None. Used for delete (title "Delete profiles") and assign (title "Assign a profile").
  - `NameScreen(ModalScreen[str | None])`: `__init__(title: str, body: str, initial: str = "",
    check: Callable[[str], str | None] = valid_name)`. `Input(id="name")` with `#name-error`. Used for rename and
    copy.
  - `ActionsScreen(ModalScreen[str | None])`: an `OptionList(id="actions-list")` with the options `keep_default`
    "Keep only Default (ticked or highlighted addons)", `everyone_default` "Everyone → Default (ticked or
    highlighted addons)", `tick_leftovers` "Tick all leftover characters", `discard` "Discard staged changes". It
    dismisses the option id.
- Review screen actions:
  - `action_delete()`:
    1. `selected_profiles()`; if empty, notify "Tick or highlight a profile first".
    2. Targets = `"Default"` first, then the union of the selected databases' names minus the selected ones.
    3. The body lists, per addon, the profiles and how many characters move.
    4. On a name: `staging.delete(selection, name)`.
  - `action_assign()`: `selected_chars()` → `TargetScreen("Assign a profile", ...)` (targets = the union of those
    databases' names, Default first) → `staging.assign(...)`.
  - `action_rename()` / `action_copy()`: the highlighted profile node only (`("profile", key, name)`), else notify
    "Highlight a profile". Then `NameScreen` → `staging.rename(key, name, new)` / `staging.copy(key, name, new)`.
    The copy popup's initial text is `f"{name} copy"`.
  - `action_remove_leftovers()`: the ticked `"c"` keys whose char is in that database's leftovers (or the
    highlighted leftover) → `ConfirmScreen("Remove leftover characters?", ...)` → `staging.remove_leftovers`.
  - `action_more()`: `ActionsScreen`, then:
    - `keep_default` → `staging.keep_only_default(keys)`, where `keys` are the databases of the ticked keys or of
      the highlighted node's addon/database;
    - `everyone_default` → `staging.everyone_to_default(keys)`;
    - `tick_leftovers` → tick every visible leftover `"c"` key;
    - `discard` → `action_discard()`.
  - `action_discard()`: `ConfirmScreen("Discard staged changes?")` → `staging.discard()`.
  - After every operation:
    1. Show each `OpResult.refused` reason and note with `self.notify` (refusals at `severity="warning"`).
    2. Clear the ticks of the affected databases.
    3. `refresh_view()`.

    Staged marks come from `report.profile_rows` / `char_tags`. Deleted profiles are `("deleted", ...)` nodes
    labelled with the "✘ deleted" tag; removed characters are `("removed", ...)` nodes.

- [ ] **Step 1: Add the failing tests**

```python
# tests/test_ace_app.py — add
from wowtools.tools.ace_profiles.popups import ActionsScreen, NameScreen, TargetScreen  # noqa: E402


class StagingTest(AceAppBase):
    async def highlight(self, app, pilot, review, kind, *rest):
        tree = review.query_one("#profiles", Tree)
        tree.root.expand_all()
        await settle(app, pilot)
        node = find(tree, kind, *rest)
        tree.move_cursor(node)
        await settle(app, pilot)
        return node

    async def test_delete_to_default(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("d")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)
            app.screen.dismiss("Default")
            await settle(app, pilot)
            summary = review.staging.summary()
            self.assertEqual((summary.deleted, summary.reassigned), (1, 1))
            self.assertIn("✘ deleted", "\n".join(labels(review.query_one("#profiles", Tree))))
            self.assertIn("Staged: ", review.summary_text)

    async def test_rename_refuses_existing_name_then_accepts(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("e")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, NameScreen)
            app.screen.dismiss("Default")
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().total, 0)  # refused, notified
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("e")
            await settle(app, pilot)
            app.screen.dismiss("Heals")
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().renamed, 1)

    async def test_assign_from_character_view(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("v")
            await settle(app, pilot)
            node = await self.highlight(app, pilot, review, "character", "Kaelys - Realm1")
            node.expand()
            await pilot.press("space")
            await settle(app, pilot)
            await pilot.press("p")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)
            app.screen.dismiss("Default")
            await settle(app, pilot)
            self.assertGreater(review.staging.summary().reassigned, 0)
            self.assertEqual(review.ticked, set())

    async def test_quick_action_keep_only_default_and_discard(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("m")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ActionsScreen)
            app.screen.dismiss("keep_default")
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().deleted, 1)
            review.action_discard()
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().total, 0)

    async def test_locked_addon_refuses_quick_action(self):
        self.cfg_tool = Config(self.config_dir / "ace-profiles.cfg")
        self.cfg_tool.set("ace_profiles", "blacklist", "ElvUI", log=False)
        self.cfg_tool.save()
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            review.staging.keep_only_default([k for k in review.staging.states if k.sv_name == "ElvDB"])
            self.assertEqual(review.staging.summary().total, 0)
```

The last test writes the config before the first open, so the settings screen opens first with the blacklist
preloaded; `open_review` saves it as it is. That is intended.

- [ ] **Step 2: Run to see them fail**

Run: `python3 scripts/run_tests.py -k ace_app`. Expected: the new tests fail.

- [ ] **Step 3: Implement `popups.py` and the actions**

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace_app`, `-k ace`, `-k structure`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add wowtools/tools/ace_profiles tests/test_ace_app.py
git commit -m "feat(ace-profiles): popups and staging operations from the tree"
```

---

### Task 14: apply, dry run, undo, recovery, progress and result screens

**Files:**
- Create: `wowtools/tools/ace_profiles/result_screen.py` (`ProfileResultScreen`)
- Modify: `wowtools/tools/ace_profiles/review_screen.py` (w, y, z, recovery, progress screen subclass)
- Modify: `wowtools/tools/ace_profiles/report.py` (`apply_confirm` body names the flavors; see Step 3)
- Modify: `tests/test_look_and_feel.py` (add the tool)
- Test: `tests/test_ace_app.py` (add `RunTest`), `tests/test_ace_report.py` (one assertion)

**Interfaces:**
- Consumes: `multi.apply_flavors`, `WowRunning`, `MultiApplyResult`; `undo.undo_run`, `recover`, `UndoError`,
  `WowRunning as UndoWowRunning`, `UndoResult`; `editor.read_marker`, `clear_marker`; `journal.latest_undoable`,
  `read_profile_journal`; `report.*`; `core.activity.running`; `ui.dialogs.ConfirmScreen`, `ProgressScreen`,
  `result_css`, `RESULT_HINT`.
- Produces:
  - `ProfileProgressScreen(ProgressScreen)` with `ID_PREFIX = "ace"`, `STAGE_TITLES = report.STAGE_TITLES`,
    `SIMULATED_STAGE = "check"`.
  - `ProfileResultScreen(Screen[str])`: `__init__(title: str, summary_rows: list[tuple[str, str]],
    columns: tuple[str, ...], detail_rows: list[tuple], scope_label: str)`. `sub_title` is
    `f"Ace3 Profile Manager · {scope_label} · {title} result"`, with title being "Apply", "Dry run" or "Undo".
    It has `#result-summary` (Item/Value `DataTable`), one `.result-detail` `DataTable`, the buttons "Rescan (r)",
    "Other flavor (f)", "Tools (t)", "Quit (q)" in one `ButtonRow`, and a `NavHint` of `RESULT_HINT +
    "r rescan · f other flavor · t tools · q quit"`. It dismisses with `"rescan"`, `"flavors"`, `"tools"` or
    `"quit"`.
  - `ProfileRecoveryScreen(ModalScreen[str])` (in `review_screen.py`), modelled on the WTF Cleaner's
    `RecoveryScreen`: it shows the marker (flavor, started, files, the zip path) and the buttons
    "Put the originals back" (`put_back`) and "Leave as is" (`leave`).

Behaviour:
- **`y` (dry run) / `w` (Apply).**
  1. Notify "Nothing staged" when nothing is staged.
  2. Otherwise run a preflight worker that calls `wow_check()`.
  3. For Apply, when the check returns names: notify the error "WoW is running (<names>). Close it first: it would
     overwrite the changes." and stop. When it returns None, add the alert "Could not check whether WoW is
     running; close it before you go on."
  4. Push `ConfirmScreen(*report.apply_confirm(summary, staging.changed(), dry_run=...),
     default_yes=dry_run)`.
  5. On yes: `app.busy = True`, push `ProfileProgressScreen(dry_run=...)`, then a thread worker inside
     `activity.running()` calls `multi.apply_flavors(plan, root=..., journal_dir=..., keep_journals=...,
     keep_snapshots=..., dry_run=..., account=self.account, wow_check=None if dry_run else self.wow_check,
     progress=...)`. The plan is `[(flavor, [s for s in staging.changed() if s.file.flavor == flavor]) for flavor
     in flavors if any]`, and progress calls `set_flavor(flavor.display_name)` then `update_progress`.
  6. On success: pop the progress screen and push `ProfileResultScreen("Dry run" | "Apply",
     report.apply_summary_rows(r), report.DETAIL_COLUMNS, report.apply_detail_rows(r), scope_label)`.
  7. On `ApplyError` / `WowRunning`: pop it and `notify(str(exc), severity="error", timeout=15)`.

  After a real Apply, the staging is dropped (its changes are on disk now) and the review rescans when it is shown
  again, without asking, because its scan is stale.
- **`z` (Undo).**
  1. Notify "Nothing to undo" when `undoable` is None.
  2. Preflight as above (WoW running: refuse).
  3. `ConfirmScreen(*report.undo_confirm(read_profile_journal(undoable)))`.
  4. Run `undo.undo_run(undoable, wow_root=cfg.wow_path, root=..., keep_snapshots=..., wow_check=...)` under
     progress.
  5. Push `ProfileResultScreen("Undo", report.undo_summary_rows(r), report.UNDO_COLUMNS,
     report.undo_detail_rows(r), scope_label)`.
- **Result screen choices.** `rescan` → `action_rescan()`; `flavors` / `tools` / `quit` → dismiss the review with
  that value.
- **Recovery.** When the scan worker found a marker, push `ProfileRecoveryScreen` (log `ace.recovery_offered`).
  - `put_back` → worker `undo.recover(marker, root=root)`, then notify the counts and rescan.
  - `leave` → `editor.clear_marker(root)`, log `ace.recovery_done` with `choice="leave"`.

- [ ] **Step 1: Add the failing tests**

```python
# tests/test_ace_app.py — add
from textual.widgets import DataTable  # noqa: E402

from wowtools.tools.ace_profiles import editor  # noqa: E402
from wowtools.tools.ace_profiles.result_screen import ProfileResultScreen  # noqa: E402
from wowtools.ui.dialogs import ConfirmScreen  # noqa: E402


class RunTest(AceAppBase):
    async def stage(self, app, pilot):
        review = await self.open_review(app, pilot)
        key = next(k for k in review.staging.states if k.sv_name == "ElvDB")
        review.staging.delete({key: ["Healer"]}, "Default")
        review.refresh_view()
        await settle(app, pilot)
        return review, key.path

    async def test_dry_run_changes_nothing_and_shows_result(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review, path = await self.stage(app, pilot)
            before = path.read_bytes()
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileResultScreen)
            self.assertTrue(app.screen.sub_title.endswith("Dry run result"))
            self.assertEqual(path.read_bytes(), before)

    async def test_apply_then_undo(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review, path = await self.stage(app, pilot)
            before = path.read_bytes()
            await pilot.press("w")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileResultScreen)
            self.assertNotEqual(path.read_bytes(), before)
            rows = app.screen.query_one("#result-summary", DataTable).row_count
            self.assertGreater(rows, 1)
            await pilot.press("r")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIsNotNone(review.undoable)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileResultScreen)
            self.assertEqual(path.read_bytes(), before)

    async def test_apply_refused_while_wow_runs(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review, path = await self.stage(app, pilot)
            before = path.read_bytes()
            self.running.append("Wow.exe")
            await pilot.press("w")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(path.read_bytes(), before)

    async def test_recovery_offered_and_put_back(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            path = next(k for k in review.staging.states if k.sv_name == "ElvDB").path
            original = path.read_bytes()
            from wowtools.core.backup import BackupEntry, create_backup
            root = self.root / "wow-tools" / "ace-profiles"
            flavor = next(s for s in review.staging.states.values() if s.file.path == path).file.flavor
            zip_path = create_backup([BackupEntry(path)], flavor.path, root / "edited" / "edited-retail-all-20261004-120000.zip", {})
            path.write_bytes(b"torn")
            from wowtools.tools.ace_profiles.scanner import sha256_of
            editor.write_marker(root, editor.Marker("_retail_", flavor.path, zip_path,
                                                    {path.relative_to(flavor.path).as_posix(): sha256_of(original)},
                                                    "2026-10-04T12:00:00+00:00", 1, "1.0.0"))
            await pilot.press("r")
            await settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "ProfileRecoveryScreen")
            app.screen.dismiss("put_back")
            await settle(app, pilot)
            self.assertEqual(path.read_bytes(), original)
            self.assertIsNone(editor.read_marker(root))
```

Note: `test_recovery_offered_and_put_back` writes `b"torn"` into a file the scan then fails to parse. That is fine:
the file shows as a scan warning until recovery puts it back and the rescan reads it again.

In `tests/test_look_and_feel.py`:
- Add `"ace-profiles"` to `TOOLS` and `RUN_ACTION["ace-profiles"] = "dry_run"`.
- Build the tree with `build_ace_tree(...)` added to the existing chain in `setUp`.
- Add `"ace-profiles": {"wow_check": list}` to `make_app`'s options.
- Add `PREPARE = {"ace-profiles": lambda review: (review.staging.everyone_to_default(list(review.staging.states)),
  review.refresh_view())}`, and call `PREPARE.get(tool, lambda r: None)(review)` before the run action in
  `test_result_screens_share_one_layout`.

In `tests/test_ace_report.py`, add to `test_apply_confirm_alerts`: `self.assertIn("Retail", body)`.

- [ ] **Step 2: Run to see them fail**

Run: `python3 scripts/run_tests.py -k ace_app`, `-k look_and_feel`, `-k ace_report`. Expected: the new tests fail.

- [ ] **Step 3: Implement**

`report.apply_confirm`: make the first body line name the flavors, so confirms never show a bare folder (the
look-and-feel test checks this):

```python
    flavors = sorted({flavor_name(s.file.flavor.folder) for s in states})
    lines = [f"{staged_text(summary)} in {plural(summary.files, 'file')} ({', '.join(flavors)})."]
```

Then build `result_screen.py` (mirror `wtf_cleaner/result_screen.py`'s layout with `result_css`), the progress
subclass, the recovery screen and the run flows described above.

- [ ] **Step 4: Run the tests**

Run: `python3 scripts/run_tests.py -k ace`, `-k look_and_feel`, then the whole suite `python3 scripts/run_tests.py`.
Expected: all pass.

- [ ] **Step 5: Commit and push milestone 3**

```bash
git add wowtools/tools/ace_profiles tests
git commit -m "feat(ace-profiles): apply, dry run, undo, recovery and result screens"
git push
```

---

## Milestone 4: documentation and final checks (Task 15), push and ask for the merge go-ahead

### Task 15: guide, README, architecture, events, CLAUDE.md, final battery

**Files:**
- Modify: `docs/ace-profiles.md` (the full guide)
- Modify: `README.md`, `docs/architecture.md`, `docs/adding-a-tool.md` (only if a step changed), `CLAUDE.md`,
  `docs/events.md` (regenerated)

- [ ] **Step 1: Write the guide** in the shape of `docs/wtf-cleaner.md` and `docs/interface-backup.md`:
  - back link and intro: what Ace3 profiles are, in plain words;
  - a "Close WoW first" callout explaining why: WoW rewrites SavedVariables on logout and /reload;
  - step by step;
  - the review screen: both views, tags (Default, unused, empty, missing, no character folder, spec profiles,
    blacklisted, unlocked) and the staged marks;
  - every key, the quick actions and the blacklist (with the unlock);
  - what the tool never touches: settings inside a profile, `global`, `char` and the other sections, files without
    Ace3 data, `Blizzard_*`, `.bak`;
  - Apply and Dry run;
  - results;
  - Undo (including "changed since" skips);
  - where the backups go (`snapshots/`, `edited/`, journals);
  - an interrupted Apply (the recovery popup);
  - settings;
  - FAQ, including: why a "missing" profile, why a character comes back after removing it (logging in recreates
    it), LibDualSpec, deleting Default;
  - troubleshooting as a Symptom / Fix table.

  Add `<!-- screenshots: review screen, popup, result -->` where the screenshots will go.
- [ ] **Step 2: README** — "The tools" row (done in Task 11), "Your settings" table rows for `[ace_profiles]`, and
  "Undo and run journals" mentioning this tool.
- [ ] **Step 3: `docs/architecture.md`** — the package, data flow (scan → stage → compile → verify → apply),
  config schema, screens, and the moved `core/snapshot.py` and `core/svfiles.py`.
- [ ] **Step 4: `CLAUDE.md`** — add "Ace3 Profile Manager (`ace-profiles`, package `tools/ace_profiles`)" to the
  tool list in the first paragraph.
- [ ] **Step 5: Regenerate events and run the full battery**

Run: `python3 scripts/gen_event_docs.py`, `python3 scripts/run_tests.py`, `ruff check .` (if installed), and the
serial run `python3 -m unittest discover -s tests -t .`.
Expected: everything passes; record the test count in the ledger.

- [ ] **Step 6: Commit, push, report**

```bash
git add -A docs README.md CLAUDE.md
git commit -m "docs: Ace3 Profile Manager guide, README, architecture"
git push
```

Then report to the user, and ask for the merge go-ahead. Merging and any release are separate approvals.
