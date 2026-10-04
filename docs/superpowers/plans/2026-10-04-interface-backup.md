# Interface Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Progress is checkpointed in `2026-10-04-interface-backup.status.md` (same folder): read it first, resume at the
> first task not marked done, and update it (and commit it) after every task.

**Goal:** A third suite tool, Interface Backup (`interface-backup`), that zips a flavor's `Interface` and `WTF`
folders into timestamped zips and restores them (exact replace, safety backup, warnings, Undo).

**Architecture:** UI-free logic modules in `wowtools/tools/interface_backup/` (settings, catalog, scanner, backup,
restore, undo, journal, report) over plain dataclasses, and three Textual modules (`app.py`, `summary_screen.py`,
`restore_screen.py`) that follow the Screenshot Organizer's screens. Small shared helpers move to `core/`
(`walk_files`, `is_link`, `remove_tree_no_follow`).

**Tech Stack:** Python 3.10+, stdlib (`zipfile`, `os.scandir`), vendored Textual, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-04-interface-backup-design.md`

## Global Constraints

- Python 3.10 floor; `from __future__ import annotations` first in every new module (`wowtools/`, `tests/`);
  stdlib + `vendor/` only. Import order as `tests/test_structure.py` enforces (stdlib, blank, third-party, blank,
  `wowtools`/`tests`).
- `wowtools/core/*` and the tool's logic modules never import `textual`. Only `app.py`, `summary_screen.py`,
  `restore_screen.py` do.
- The tool imports nothing from `wowtools.tools.wtf_cleaner` or `wowtools.tools.screenshot_organizer`.
- Tool name `interface-backup`; package `interface_backup`; config `config/interface-backup.cfg`, section
  `[interface_backup]`; event prefix `ibackup.`; zips in `<backup_dir or <WoW>/wow-tools>/interface-backup/`, named
  `backup-<flavor.short_name>-<YYYYMMDD-HHMMSS>.zip` and `pre-restore-<short>-<stamp>.zip` (`-2`, `-3` via
  `free_name`); journals in `<WoW>/wow-tools/interface-backup/journal/`.
- `keep_backups` default 10, 0 = never delete; `keep_journals` default 10, at least 1.
- Never call `resolve()` per file; never follow a symlink or junction; never delete through one.
- Never overwrite an existing backup (`rename_no_replace`); never leave a `.partial` behind.
- Every log event registered in `interface_backup/events.py`; `docs/events.md` regenerated
  (`python3 scripts/gen_event_docs.py`).
- No function or name called `_remove`, `_discard`, `_safe_progress` anywhere (test_structure); the literal
  `"wow-tools"` only via `core.journal.TOOLS_SUBDIR`.
- Tests: temp trees only, `tests.fixtures.TuiTestCase` for TUI tests, never a real install, never the network.
- Commit after every task (message ends with the two attribution lines from the session). Push the branch
  `feat/interface-backup` after each milestone. Never merge without the user's go-ahead.
- Test commands: `python3 scripts/run_tests.py -k interface_backup` for the tool, `python3 scripts/run_tests.py`
  for everything, `ruff check .` (the repo has `ruff.toml`; run if `ruff` is installed).

## Review Focus

1. **Zip entry names that are unsafe on Windows** (`..`, absolute, `C:x`, backslashes, `:` alternate data streams,
   trailing dot/space, two names that differ only in case): `open_backup` must refuse the whole zip before anything
   changes. Test in Task 5.
2. **Addon folders that are junctions/symlinks to a dev repo**: backup must not follow them; restore must keep
   them and must never delete the repo they point at, even when the old copy is deleted. Tests in Tasks 1, 3, 6.
3. **The folder swap failing half-way** (Windows lock because WoW is open): the part must be exactly as before,
   links included. Test in Task 6 with an injected `rename`.
4. **A file vanishing or changing while it is zipped** (WoW writing SavedVariables): a vanished file is skipped
   and listed, the zip still verifies; a size change must not fail verification (the manifest records the bytes
   stored). Test in Task 4.
5. **Undo when the safety zip is gone or the journal is from another WoW folder**: refused with a clear reason,
   nothing touched. Test in Task 7.

---

## Milestone 1: logic (Tasks 1–7), push after Task 7

### Task 1: shared core helpers (`walk_files`, `is_link`, `remove_tree_no_follow`)

**Files:**
- Modify: `wowtools/core/fsutil.py` (add `is_link`, `remove_tree_no_follow` and private helpers)
- Modify: `wowtools/core/backup.py` (add `walk_files`)
- Modify: `wowtools/tools/wtf_cleaner/safety.py` (`wtf_files` delegates to `walk_files`)
- Test: `tests/test_fsutil.py`, `tests/test_backup.py` (add test classes)

**Interfaces:**
- Produces: `fsutil.is_link(entry: os.DirEntry | Path) -> bool`; `fsutil.remove_tree_no_follow(path: Path) -> None`
  (raises `OSError`); `backup.walk_files(folder: Path, *, on_link=None, on_error=None, on_count=None, every=100)
  -> list[os.DirEntry]`.

- [ ] **Step 1: Write the failing tests** (append to the existing test modules; reuse their imports)

```python
# tests/test_fsutil.py
import os, sys, tempfile, unittest
from pathlib import Path
from wowtools.core.fsutil import is_link, remove_tree_no_follow

def can_symlink(tmp: Path) -> bool:
    try:
        (tmp / "probe-target").mkdir()
        os.symlink(tmp / "probe-target", tmp / "probe-link", target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False

class RemoveTreeNoFollowTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.tmp = Path(t.name)

    def test_removes_nested_tree_and_read_only_files(self):
        root = self.tmp / "tree"; (root / "a" / "b").mkdir(parents=True)
        f = root / "a" / "b" / "x.txt"; f.write_text("x"); os.chmod(f, 0o444)
        remove_tree_no_follow(root)
        self.assertFalse(root.exists())

    def test_link_inside_is_unlinked_never_followed(self):
        if not can_symlink(self.tmp):
            self.skipTest("symlinks not available")
        repo = self.tmp / "repo"; repo.mkdir(); (repo / "keep.lua").write_text("k")
        root = self.tmp / "Interface.replaced"; (root / "AddOns").mkdir(parents=True)
        os.symlink(repo, root / "AddOns" / "MyAddon", target_is_directory=True)
        self.assertTrue(is_link(root / "AddOns" / "MyAddon"))
        remove_tree_no_follow(root)
        self.assertFalse(root.exists())
        self.assertEqual((repo / "keep.lua").read_text(), "k")

    def test_is_link_false_for_plain_folder_and_missing_path(self):
        (self.tmp / "d").mkdir()
        self.assertFalse(is_link(self.tmp / "d"))
        self.assertFalse(is_link(self.tmp / "missing"))
```

```python
# tests/test_backup.py
from wowtools.core.backup import walk_files

class WalkFilesTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.tmp = Path(t.name)
        for rel in ("b/2.txt", "a/1.txt", "top.txt"):
            p = self.tmp / "root" / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(rel)

    def test_files_depth_first_sorted(self):
        names = [Path(e.path).relative_to(self.tmp / "root").as_posix() for e in walk_files(self.tmp / "root")]
        self.assertEqual(names, ["top.txt", "a/1.txt", "b/2.txt"])

    def test_links_reported_not_followed(self):
        target = self.tmp / "elsewhere"; target.mkdir(); (target / "x.txt").write_text("x")
        try:
            os.symlink(target, self.tmp / "root" / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        links = []
        files = walk_files(self.tmp / "root", on_link=links.append)
        self.assertEqual(links, [self.tmp / "root" / "link"])
        self.assertNotIn("x.txt", [e.name for e in files])

    def test_on_count_and_missing_root_raises(self):
        counts = []
        walk_files(self.tmp / "root", on_count=counts.append, every=2)
        self.assertEqual(counts, [2])
        with self.assertRaises(OSError):
            walk_files(self.tmp / "nope", on_error=lambda p, e: None)  # the root itself always raises
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 scripts/run_tests.py -k RemoveTreeNoFollow -k WalkFiles`
Expected: FAIL with `ImportError` (`is_link` / `walk_files` not defined).

- [ ] **Step 3: Implement** — in `wowtools/core/fsutil.py` (add `import stat`, `import sys` at the top):

```python
# Reparse tags (os.lstat(...).st_reparse_tag on Windows) of the two kinds of link: a symlink and a junction.
_LINK_TAGS = (0xA000000C, 0xA0000003)


def is_link(entry: os.DirEntry | Path) -> bool:
    """True for a symlink or, on Windows, a junction (Python 3.10 reports a junction as a plain folder, so its
    reparse tag is checked; other reparse points such as cloud placeholders are not links). Never raises."""
    try:
        if entry.is_symlink():
            return True
        if sys.platform != "win32":
            return False
        info = entry.stat(follow_symlinks=False) if isinstance(entry, os.DirEntry) else os.lstat(entry)
        return getattr(info, "st_reparse_tag", 0) in _LINK_TAGS
    except OSError:
        return False


def _unlink_link(path: Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        if sys.platform != "win32":
            raise
        os.rmdir(path)  # a junction or directory symlink is removed like a folder; its target is untouched


def _delete_entry(path: Path, *, folder: bool) -> None:
    remover = os.rmdir if folder else os.remove
    try:
        remover(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)  # a read-only file or folder on Windows
        remover(path)


def remove_tree_no_follow(path: Path) -> None:
    """Delete a folder tree. Links inside it (symlinks, junctions) are removed as links and never descended into,
    so whatever they point at is untouched; a link given as `path` is just unlinked. Raises OSError."""
    if is_link(path):
        _unlink_link(path)
        return
    with os.scandir(path) as entries:
        children = list(entries)
    for entry in children:
        child = Path(entry.path)
        if is_link(entry):
            _unlink_link(child)
        elif entry.is_dir(follow_symlinks=False):
            remove_tree_no_follow(child)
        else:
            _delete_entry(child, folder=False)
    _delete_entry(path, folder=True)
```

In `wowtools/core/backup.py` (add `import os`; import `is_link` from `wowtools.core.fsutil`):

```python
def walk_files(folder: Path, *, on_link: Callable[[Path], None] | None = None,
               on_error: Callable[[Path, OSError], None] | None = None,
               on_count: Callable[[int], None] | None = None, every: int = 100) -> list[os.DirEntry]:
    """Every regular file under folder, depth first with names sorted, as directory entries (entry.stat() is free
    on Windows; elsewhere it costs one disk round trip, so callers read it only when they need sizes). Links
    (symlinks, junctions) are never followed: each goes to on_link and is left out. An unreadable sub-folder goes
    to on_error and is skipped; without on_error, and always for `folder` itself, the OSError is raised.
    on_count(found) is called every `every` files."""
    found: list[os.DirEntry] = []
    pending = [folder]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                children = sorted(entries, key=lambda e: e.name)
        except OSError as exc:
            if on_error is None or current == folder:
                raise
            on_error(current, exc)
            continue
        subdirs = []
        for entry in children:
            if is_link(entry):
                if on_link is not None:
                    on_link(Path(entry.path))
            elif entry.is_dir(follow_symlinks=False):
                subdirs.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                found.append(entry)
                if on_count is not None and len(found) % every == 0:
                    on_count(len(found))
        pending.extend(reversed(subdirs))
    return found
```

In `wowtools/tools/wtf_cleaner/safety.py` replace the body of `wtf_files` (keep its signature and docstring, add
"Links are skipped." to the docstring):

```python
    def counted(found: int) -> None:
        progress(stage, found, 0, f"{found} files found")

    found = [Path(entry.path) for entry in walk_files(flavor.wtf_dir, on_count=None if progress is None else counted,
                                                      every=LIST_REPORT_EVERY)]
    if progress is not None:
        progress(stage, len(found), len(found), f"{len(found)} files found")
    return found
```
(import `walk_files` from `wowtools.core.backup`; drop the now-unused `os` import only if nothing else uses it.)

- [ ] **Step 4: Run the new tests and the cleaner suite**

Run: `python3 scripts/run_tests.py -k RemoveTreeNoFollow -k WalkFiles -k safety -k cleaner -k structure`
Expected: PASS (all).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(core): walk_files, is_link, remove_tree_no_follow"`

---

### Task 2: package skeleton — events, settings, catalog

**Files:**
- Create: `wowtools/tools/interface_backup/__init__.py`, `events.py`, `settings.py`, `catalog.py`
- Test: `tests/test_interface_backup_settings.py`, `tests/test_interface_backup_catalog.py`

**Interfaces:**
- Produces: `events.TOOL_NAME = "interface-backup"`; `settings.SECTION = "interface_backup"`,
  `BackupSettings(backup_dir: Path | None, keep_backups: int, keep_journals: int, last_flavor_choice: str)`,
  `load_settings(cfg)`, `save_settings(cfg, settings, *, source="settings")`,
  `resolve_backup_root(settings, wow_path) -> Path | None`, `resolve_journal_dir(wow_path) -> Path | None`,
  `validate_backup_dir(path, install) -> str | None`; `catalog.BackupInfo(path, kind, flavor_short, stamp, n, size)`
  with `.when` and `.is_safety`, `new_backup_path(root, flavor_short, now, kind="backup") -> Path`,
  `list_backups(root, flavor_shorts=None, *, kinds=KINDS) -> list[BackupInfo]` (newest first),
  `prune_backups(root, flavor_short, keep) -> list[Path]`, `prune_safety(root, referenced: set[str]) -> list[Path]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_interface_backup_settings.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.config import Config
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup.settings import (BackupSettings, load_settings, resolve_backup_root,
                                                      resolve_journal_dir, save_settings, validate_backup_dir)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.tmp = Path(t.name)
        self.cfg = Config(self.tmp / "interface-backup.cfg")

    def test_defaults(self):
        s = load_settings(self.cfg)
        self.assertEqual((s.backup_dir, s.keep_backups, s.keep_journals, s.last_flavor_choice), (None, 10, 10, ""))

    def test_round_trip_and_zero_means_keep_all(self):
        save_settings(self.cfg, BackupSettings(self.tmp / "bk", 0, 3, "_retail_"))
        s = load_settings(Config(self.tmp / "interface-backup.cfg").load())
        self.assertEqual((s.backup_dir, s.keep_backups, s.keep_journals, s.last_flavor_choice),
                         (self.tmp / "bk", 0, 3, "_retail_"))

    def test_bad_values_fall_back(self):
        self.cfg.set("interface_backup", "keep_backups", "-4", log=False)
        self.cfg.set("interface_backup", "keep_journals", "zero", log=False)
        s = load_settings(self.cfg)
        self.assertEqual((s.keep_backups, s.keep_journals), (10, 10))

    def test_roots(self):
        wow = self.tmp / "WoW"
        self.assertEqual(resolve_backup_root(BackupSettings(), wow), wow / "wow-tools" / "interface-backup")
        self.assertEqual(resolve_backup_root(BackupSettings(self.tmp / "x"), wow), self.tmp / "x" / "interface-backup")
        self.assertIsNone(resolve_backup_root(BackupSettings(), None))
        self.assertEqual(resolve_journal_dir(wow), wow / "wow-tools" / "interface-backup" / "journal")

    def test_validate(self):
        root = build_wow_tree(self.tmp / "WoW")
        install = WowInstall(root)
        self.assertIsNone(validate_backup_dir(None, install))
        self.assertIsNone(validate_backup_dir(self.tmp / "bk", install))
        self.assertIn("Interface", validate_backup_dir(root / "_retail_" / "Interface" / "x", install))
        self.assertIn("WoW folder", validate_backup_dir(root, install))
```

```python
# tests/test_interface_backup_catalog.py
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from wowtools.tools.interface_backup.catalog import list_backups, new_backup_path, prune_backups, prune_safety

NOW = datetime(2026, 10, 4, 15, 30, 12)


class CatalogTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.root = Path(t.name) / "interface-backup"
        self.root.mkdir()

    def touch(self, name: str) -> Path:
        p = self.root / name; p.write_bytes(b"z"); return p

    def test_new_path_and_collision(self):
        first = new_backup_path(self.root, "retail", NOW)
        self.assertEqual(first.name, "backup-retail-20261004-153012.zip")
        first.write_bytes(b"z")
        self.assertEqual(new_backup_path(self.root, "retail", NOW).name, "backup-retail-20261004-153012-2.zip")
        self.assertEqual(new_backup_path(self.root, "retail", NOW, kind="pre-restore").name,
                         "pre-restore-retail-20261004-153012.zip")

    def test_list_newest_first_filtered(self):
        self.touch("backup-retail-20261001-000000.zip"); self.touch("backup-retail-20261002-000000.zip")
        self.touch("backup-retail-20261002-000000-2.zip"); self.touch("backup-classic_era-20261003-000000.zip")
        self.touch("pre-restore-retail-20261003-000000.zip"); self.touch("notes.txt")
        names = [b.path.name for b in list_backups(self.root, {"retail"}, kinds=("backup",))]
        self.assertEqual(names, ["backup-retail-20261002-000000-2.zip", "backup-retail-20261002-000000.zip",
                                 "backup-retail-20261001-000000.zip"])
        everything = list_backups(self.root)
        self.assertEqual(len(everything), 5)
        self.assertTrue(everything[0].is_safety or everything[0].flavor_short == "classic_era")
        self.assertEqual(list_backups(self.root / "missing"), [])
        self.assertEqual(list_backups(None), [])

    def test_prune_per_flavor_never_safety_or_foreign(self):
        for day in range(1, 5):
            self.touch(f"backup-retail-2026100{day}-000000.zip")
        self.touch("backup-classic_era-20261001-000000.zip"); self.touch("pre-restore-retail-20261001-000000.zip")
        self.touch("notes.txt")
        removed = prune_backups(self.root, "retail", 2)
        self.assertEqual(sorted(p.name for p in removed),
                         ["backup-retail-20261001-000000.zip", "backup-retail-20261002-000000.zip"])
        self.assertTrue((self.root / "backup-classic_era-20261001-000000.zip").exists())
        self.assertTrue((self.root / "pre-restore-retail-20261001-000000.zip").exists())
        self.assertEqual(prune_backups(self.root, "retail", 0), [])  # 0 = never delete

    def test_prune_safety_keeps_referenced(self):
        keep = self.touch("pre-restore-retail-20261001-000000.zip")
        drop = self.touch("pre-restore-retail-20261002-000000.zip")
        backup = self.touch("backup-retail-20261002-000000.zip")
        self.assertEqual(prune_safety(self.root, {keep.name}), [drop])
        self.assertTrue(keep.exists() and backup.exists())
```

- [ ] **Step 2: Run to verify they fail** — `python3 scripts/run_tests.py -k interface_backup` → FAIL
  (`ModuleNotFoundError: wowtools.tools.interface_backup`).

- [ ] **Step 3: Implement**

`wowtools/tools/interface_backup/__init__.py`:
```python
"""Interface Backup: zip a flavor's Interface and WTF folders, and restore them."""
from __future__ import annotations

from wowtools.tools.interface_backup import events as _events  # noqa: F401  (registers the tool's events)
```

`events.py`:
```python
"""Events emitted by Interface Backup. Levels are fixed here; see docs/events.md.

Event names are global across tools, so every name here starts with `ibackup.`."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events

TOOL_NAME = "interface-backup"

EVENTS: dict[str, EventSpec] = {
    "ibackup.scan_started": EventSpec("info", "A scan of the chosen flavors' Interface and WTF folders started."),
    "ibackup.scan_completed": EventSpec("info", "A flavor was scanned: files, bytes (when known) and links per part."),
    "ibackup.scan_warning": EventSpec("warning", "A folder could not be read during a scan, or a part is itself a link."),
    "ibackup.leftover_found": EventSpec("warning", "A .restoring or .replaced folder from an interrupted restore was found."),
    "ibackup.backup_started": EventSpec("info", "A backup run started: flavors and destination."),
    "ibackup.backup_created": EventSpec("info", "A backup zip was written and verified: path, files, sizes."),
    "ibackup.backup_skipped": EventSpec("warning", "A flavor was skipped: it has neither an Interface nor a WTF folder."),
    "ibackup.backup_failed": EventSpec("error", "A flavor's backup failed; no zip was left behind."),
    "ibackup.links_skipped": EventSpec("info", "Links (symlinks, junctions) that were not followed: count and up to 20 paths."),
    "ibackup.pruned": EventSpec("info", "Older backups of a flavor were deleted to keep the newest N (keep_backups)."),
    "ibackup.restore_started": EventSpec("info", "A restore started: backup, flavor, parts and warning counts."),
    "ibackup.safety_created": EventSpec("info", "The pre-restore safety backup was written and verified."),
    "ibackup.part_restored": EventSpec("info", "A part (Interface or WTF) was replaced by the backup's copy."),
    "ibackup.part_rolled_back": EventSpec("warning", "A part could not be replaced and was left as it was."),
    "ibackup.replaced_left": EventSpec("warning", "A part was restored but its old copy could not be fully deleted."),
    "ibackup.restore_completed": EventSpec("info", "A restore finished, with totals (logged at warning if a part failed)."),
    "ibackup.restore_stopped": EventSpec("error", "A restore stopped unexpectedly; the journal holds what was done so far."),
    "ibackup.journal_pruned": EventSpec("info", "Older restore journals and the safety backups only they named were deleted."),
    "ibackup.undo_started": EventSpec("info", "Undo of a restore journal started."),
    "ibackup.undo_completed": EventSpec("info", "Undo of a restore finished, with totals."),
    "ibackup.undo_failed": EventSpec("error", "Undo was refused or failed on a part."),
}

register_events(TOOL_NAME, EVENTS)
```
(Check `wowtools/core/events.py` for how the level of `restore_completed` is raised to warning in the
organizer — `log_event(..., level="warning")` or similar — and do the same.)

`settings.py`:
```python
"""Interface Backup's own settings: the [interface_backup] section of config/interface-backup.cfg, plus where
backups and journals go."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.install import WowInstall, validate_output_dir
from wowtools.core.journal import TOOLS_SUBDIR, journal_dir
from wowtools.tools.interface_backup.events import TOOL_NAME

SECTION = "interface_backup"
DEFAULT_KEEP_BACKUPS = 10
DEFAULT_KEEP_JOURNALS = 10


@dataclass
class BackupSettings:
    backup_dir: Path | None = None  # None (stored as empty) means <WoW folder>/wow-tools
    keep_backups: int = DEFAULT_KEEP_BACKUPS  # per flavor; 0 = never delete
    keep_journals: int = DEFAULT_KEEP_JOURNALS  # restore journals (each names its safety backup)
    last_flavor_choice: str = ""  # "" means all flavors, else a flavor folder such as _retail_


def load_settings(cfg: Config) -> BackupSettings:
    keep = cfg.get_int(SECTION, "keep_backups", DEFAULT_KEEP_BACKUPS)
    journals = cfg.get_int(SECTION, "keep_journals", DEFAULT_KEEP_JOURNALS)
    return BackupSettings(cfg.get_path(SECTION, "backup_dir"), keep if keep >= 0 else DEFAULT_KEEP_BACKUPS,
                          journals if journals >= 1 else DEFAULT_KEEP_JOURNALS,
                          (cfg.get(SECTION, "last_flavor_choice") or "").strip())


def save_settings(cfg: Config, settings: BackupSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    cfg.set(SECTION, "keep_backups", settings.keep_backups, source=source)
    cfg.set(SECTION, "keep_journals", settings.keep_journals, source=source)
    cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_backup_root(settings: BackupSettings, wow_path: Path | None) -> Path | None:
    """Where the zips go: <backup folder>/interface-backup, the backup folder defaulting to <WoW folder>/wow-tools."""
    base = settings.backup_dir if settings.backup_dir is not None else (
        wow_path / TOOLS_SUBDIR if wow_path is not None else None)
    return base / TOOL_NAME if base is not None else None


def resolve_journal_dir(wow_path: Path | None) -> Path | None:
    """<WoW folder>/wow-tools/interface-backup/journal."""
    return journal_dir(wow_path, TOOL_NAME)


def validate_backup_dir(path: Path | None, install: WowInstall) -> str | None:
    """Why a backup folder is not allowed, or None if it is fine (None itself means the default)."""
    return validate_output_dir(path, install, what="backup folder", example="D:\\WoW backups")
```

`catalog.py`:
```python
"""Backup file names in the backup root: backup-<flavor>-<stamp>.zip and pre-restore-<flavor>-<stamp>.zip, listing
and pruning. UI-free."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wowtools.core.fsutil import free_name

KINDS = ("backup", "pre-restore")
NAME = re.compile(r"^(?P<kind>backup|pre-restore)-(?P<flavor>.+?)-(?P<stamp>\d{8}-\d{6})(?:-(?P<n>\d+))?\.zip$")


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    kind: str  # "backup" or "pre-restore"
    flavor_short: str
    stamp: str  # YYYYMMDD-HHMMSS
    n: int
    size: int

    @property
    def is_safety(self) -> bool:
        return self.kind == "pre-restore"

    @property
    def when(self) -> str:
        """The stamp as "YYYY-MM-DD HH:MM:SS"."""
        return datetime.strptime(self.stamp, "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")


def new_backup_path(root: Path, flavor_short: str, now: datetime, kind: str = "backup") -> Path:
    return free_name(root, f"{kind}-{flavor_short}-{now:%Y%m%d-%H%M%S}", ".zip")


def list_backups(root: Path | None, flavor_shorts: set[str] | None = None, *,
                 kinds: tuple[str, ...] = KINDS) -> list[BackupInfo]:
    """Backups in root (top level only), newest first. Never raises: an unreadable folder lists nothing."""
    if root is None:
        return []
    try:
        with os.scandir(root) as it:
            entries = list(it)
    except OSError:
        return []
    found = []
    for entry in entries:
        m = NAME.match(entry.name)
        if not m or m["kind"] not in kinds or (flavor_shorts is not None and m["flavor"] not in flavor_shorts):
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            size = entry.stat().st_size
        except OSError:
            continue
        found.append(BackupInfo(Path(entry.path), m["kind"], m["flavor"], m["stamp"], int(m["n"] or 1), size))
    return sorted(found, key=lambda b: (b.stamp, b.n), reverse=True)


def _delete(paths: list[Path]) -> list[Path]:
    removed = []
    for path in paths:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    return removed


def prune_backups(root: Path, flavor_short: str, keep: int) -> list[Path]:
    """Delete all but the newest `keep` backup-<flavor>-*.zip of this flavor. keep 0 means never delete. Safety
    backups, other flavors' backups and other files are never touched."""
    if keep <= 0:
        return []
    return _delete([b.path for b in list_backups(root, {flavor_short}, kinds=("backup",))[keep:]])


def prune_safety(root: Path, referenced: set[str]) -> list[Path]:
    """Delete pre-restore zips whose file name no remaining restore journal mentions."""
    return _delete([b.path for b in list_backups(root, kinds=("pre-restore",)) if b.path.name not in referenced])
```

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup -k events -k structure` → PASS.
- [ ] **Step 5: Commit** — `feat(interface-backup): events, settings, backup catalog`

---

### Task 3: scanner

**Files:**
- Create: `wowtools/tools/interface_backup/scanner.py`
- Modify: `tests/fixtures.py` (add `build_interface_tree`)
- Test: `tests/test_interface_backup_scanner.py`

**Interfaces:**
- Consumes: `walk_files`, `is_link` (Task 1).
- Produces: `PARTS = ("Interface", "WTF")`, `STAGING_SUFFIXES = (".restoring", ".replaced")`, `CHEAP_STATS: bool`,
  `FileInfo(rel: str, size: int | None, mtime: float | None)`, `PartScan(name, path, exists, linked, files, links,
  errors)` with `.size -> int | None`, `FlavorScan(flavor, parts: dict[str, PartScan], leftovers: list[Path])` with
  `.file_count`, `.size`, `.has_data`, `.link_count`; `leftover_folders(flavor) -> list[Path]`;
  `scan_part(path, name, *, with_stats, on_count=None) -> PartScan`;
  `scan_flavor(flavor, *, with_stats=CHEAP_STATS, parts=PARTS, progress=None) -> FlavorScan`;
  `scan_flavors(flavors, *, with_stats=CHEAP_STATS, progress=None) -> list[FlavorScan]` (logs events).
  `progress(stage, current, total, detail)` with stage `"scan"`, total 0.
- Fixture: `build_interface_tree(root) -> Path` — call after `build_wow_tree(root)`; adds
  `_retail_/Interface/AddOns/Auctionator/Auctionator.lua` (`b"auc"`), `_retail_/Interface/AddOns/Details/core.lua`
  (`b"det"`), `_retail_/WTF/Config.wtf` (`b"SET a 1\n"`); creates `_ptr_` (an empty flavor folder, neither part).
  (`_classic_era_` already has both parts; `_anniversary_` only `WTF`.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_interface_backup_scanner.py
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup.scanner import leftover_folders, scan_flavor, scan_flavors


class ScannerTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.tmp = Path(t.name)
        self.root = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavors = {f.folder: f for f in WowInstall(self.root).flavors()}

    def test_parts_files_and_sizes(self):
        scan = scan_flavor(self.flavors["_retail_"], with_stats=True)
        rels = [f.rel for f in scan.parts["Interface"].files]
        self.assertIn("AddOns/Auctionator/Auctionator.lua", rels)
        self.assertIn("Config.wtf", [f.rel for f in scan.parts["WTF"].files])
        self.assertTrue(scan.has_data)
        self.assertIsNotNone(scan.size)

    def test_without_stats_sizes_unknown(self):
        scan = scan_flavor(self.flavors["_retail_"], with_stats=False)
        self.assertIsNone(scan.size)
        self.assertGreater(scan.file_count, 0)

    def test_missing_parts(self):
        scan = scan_flavor(self.flavors["_anniversary_"], with_stats=True)
        self.assertFalse(scan.parts["Interface"].exists)
        self.assertTrue(scan.parts["WTF"].exists)
        self.assertFalse(scan_flavor(self.flavors["_ptr_"], with_stats=True).has_data)

    def test_links_not_followed(self):
        repo = self.tmp / "repo"; (repo / "deep").mkdir(parents=True); (repo / "deep" / "x.lua").write_text("x")
        try:
            os.symlink(repo, self.root / "_retail_" / "Interface" / "AddOns" / "Dev", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        part = scan_flavor(self.flavors["_retail_"], with_stats=True).parts["Interface"]
        self.assertEqual(part.links, ["AddOns/Dev"])
        self.assertFalse(any(f.rel.startswith("AddOns/Dev/") for f in part.files))

    def test_part_that_is_a_link_is_not_scanned(self):
        target = self.tmp / "ext-wtf"; target.mkdir(); (target / "a.txt").write_text("a")
        era = self.root / "_classic_era_"
        os.rename(era / "WTF", self.tmp / "old-wtf")
        try:
            os.symlink(target, era / "WTF", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        part = scan_flavor(self.flavors["_classic_era_"], with_stats=True).parts["WTF"]
        self.assertTrue(part.linked)
        self.assertFalse(part.exists)
        self.assertEqual(part.files, [])

    def test_leftovers_and_events(self):
        (self.root / "_retail_" / "Interface.replaced").mkdir()
        self.assertEqual(leftover_folders(self.flavors["_retail_"]), [self.root / "_retail_" / "Interface.replaced"])
        with capture_events() as events:
            scans = scan_flavors([self.flavors["_retail_"]], with_stats=True)
        self.assertEqual(scans[0].leftovers, [self.root / "_retail_" / "Interface.replaced"])
        names = [e["event"] for e in events]
        self.assertIn("ibackup.scan_started", names)
        self.assertIn("ibackup.scan_completed", names)
        self.assertIn("ibackup.leftover_found", names)

    def test_progress_called(self):
        calls = []
        scan_flavor(self.flavors["_retail_"], with_stats=False, progress=lambda *a: calls.append(a))
        self.assertTrue(calls)
        self.assertEqual(calls[0][0], "scan")
```
(Check `capture_events()` in `wowtools/core/events.py` for the exact record shape — the key may be `"event"` or
`"name"` — and adjust the assertions to it.)

- [ ] **Step 2: Run** — `python3 scripts/run_tests.py -k interface_backup_scanner` → FAIL (`ImportError`).

- [ ] **Step 3: Implement**

`tests/fixtures.py` (append; update the module docstring with one line about it):
```python
def build_interface_tree(root: Path) -> Path:
    """Interface Backup extras (call after build_wow_tree): known bytes in _retail_'s Interface and WTF, and an
    empty _ptr_ flavor (neither part). _anniversary_ already has WTF only."""
    retail = root / "_retail_"
    _write_bytes(retail / "Interface" / "AddOns" / "Auctionator" / "Auctionator.lua", b"auc")
    _write_bytes(retail / "Interface" / "AddOns" / "Details" / "core.lua", b"det")
    _write_bytes(retail / "WTF" / "Config.wtf", b"SET a 1\n")
    (root / "_ptr_").mkdir(parents=True, exist_ok=True)
    return root
```

`scanner.py`:
```python
"""What a flavor's Interface and WTF folders hold: files (with sizes when cheap or asked for), links that are not
followed, and folders left by an interrupted restore. UI-free."""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.backup import walk_files
from wowtools.core.events import log_event
from wowtools.core.fsutil import is_link, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.paths import to_stored

PARTS = ("Interface", "WTF")
STAGING_SUFFIXES = (".restoring", ".replaced")
# DirEntry.stat() comes free with the directory listing on Windows; over WSL drvfs it costs a disk round trip per
# file, so a summary scan there counts files only and leaves sizes unknown.
CHEAP_STATS = os.name == "nt"
SAMPLE = 20

Progress = Callable[[str, int, int, str], None]


@dataclass(frozen=True)
class FileInfo:
    rel: str  # path inside the part folder, with forward slashes
    size: int | None  # None when the scan did not read sizes
    mtime: float | None


@dataclass
class PartScan:
    name: str  # "Interface" or "WTF"
    path: Path
    exists: bool = False
    linked: bool = False  # the part folder itself is a link: never backed up or restored
    files: list[FileInfo] = field(default_factory=list)
    links: list[str] = field(default_factory=list)  # rel paths of links inside, not followed
    errors: list[str] = field(default_factory=list)

    @property
    def size(self) -> int | None:
        sizes = [f.size for f in self.files]
        return None if any(s is None for s in sizes) else sum(sizes)  # type: ignore[misc]


@dataclass
class FlavorScan:
    flavor: Flavor
    parts: dict[str, PartScan]
    leftovers: list[Path] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(len(p.files) for p in self.parts.values())

    @property
    def link_count(self) -> int:
        return sum(len(p.links) for p in self.parts.values())

    @property
    def size(self) -> int | None:
        sizes = [p.size for p in self.parts.values() if p.exists]
        return None if any(s is None for s in sizes) else sum(sizes)  # type: ignore[misc]

    @property
    def has_data(self) -> bool:
        return any(p.exists for p in self.parts.values())


def leftover_folders(flavor: Flavor) -> list[Path]:
    """<part>.restoring / <part>.replaced folders an interrupted restore left in the flavor folder."""
    return [flavor.path / f"{part}{suffix}" for part in PARTS for suffix in STAGING_SUFFIXES
            if os.path.lexists(flavor.path / f"{part}{suffix}")]


def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()  # lexical: both come from the same directory listing


def scan_part(path: Path, name: str, *, with_stats: bool, on_count: Callable[[int], None] | None = None) -> PartScan:
    part = PartScan(name, path)
    if is_link(path):
        part.linked = True
        part.errors.append(f"{name} is a link to another folder; it is not backed up or restored")
        return part
    if not path.is_dir():
        return part
    part.exists = True
    try:
        entries = walk_files(path, on_link=lambda p: part.links.append(_rel(p, path)),
                             on_error=lambda p, exc: part.errors.append(f"{to_stored(p)}: {exc.strerror or exc}"),
                             on_count=on_count)
    except OSError as exc:
        part.errors.append(f"{to_stored(path)}: {exc.strerror or exc}")
        return part
    for entry in entries:
        size = mtime = None
        if with_stats:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                part.errors.append(f"{to_stored(Path(entry.path))}: {exc.strerror or exc}")
                continue
            size, mtime = info.st_size, info.st_mtime
        part.files.append(FileInfo(_rel(Path(entry.path), path), size, mtime))
    return part


def scan_flavor(flavor: Flavor, *, with_stats: bool = CHEAP_STATS, parts: tuple[str, ...] = PARTS,
                progress: Progress | None = None) -> FlavorScan:
    report = safe_progress(progress)
    scans: dict[str, PartScan] = {}
    for name in PARTS:
        if name not in parts:
            scans[name] = PartScan(name, flavor.path / name)
            continue
        report("scan", 0, 0, f"{flavor.display_name}: {name}")
        scans[name] = scan_part(flavor.path / name, name, with_stats=with_stats,
                                on_count=lambda n, name=name: report("scan", n, 0,
                                                                     f"{flavor.display_name}: {name} ({n} files)"))
    return FlavorScan(flavor, scans, leftover_folders(flavor))


def scan_flavors(flavors: list[Flavor], *, with_stats: bool = CHEAP_STATS,
                 progress: Progress | None = None) -> list[FlavorScan]:
    """Scan each flavor and log what was found."""
    log_event("ibackup.scan_started", flavors=[f.folder for f in flavors], with_stats=with_stats)
    scans = []
    for flavor in flavors:
        scan = scan_flavor(flavor, with_stats=with_stats, progress=progress)
        for part in scan.parts.values():
            for error in part.errors[:SAMPLE]:
                log_event("ibackup.scan_warning", flavor=flavor.folder, part=part.name, error=error)
        for path in scan.leftovers:
            log_event("ibackup.leftover_found", flavor=flavor.folder, path=to_stored(path))
        log_event("ibackup.scan_completed", flavor=flavor.folder,
                  parts={p.name: {"exists": p.exists, "files": len(p.files), "bytes": p.size, "links": len(p.links)}
                         for p in scan.parts.values()})
        scans.append(scan)
    return scans
```
(If `log_event` does not accept dict/list fields, pass them as they are passed elsewhere in the organizer's
planner; read `wowtools/tools/screenshot_organizer/planner.py` for the pattern.)

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup` → PASS.
- [ ] **Step 5: Commit** — `feat(interface-backup): scanner`

---

### Task 4: backup (zip, verify, prune)

**Files:**
- Create: `wowtools/tools/interface_backup/backup.py`
- Test: `tests/test_interface_backup_backup.py`

**Interfaces:**
- Consumes: `FlavorScan`, `PARTS` (Task 3); `new_backup_path`, `prune_backups` (Task 2); `core.backup.MANIFEST_NAME`,
  `BackupError`, `verify_backup`; `fsutil.rename_no_replace`, `remove_quietly`, `safe_progress`.
- Produces: `ZipStats(path, files, bytes_in, bytes_zip, missing: list[str], links: list[str], parts_existing:
  list[str])`; `write_zip(scan, dest, *, kind, parts=PARTS, progress=None) -> ZipStats` (raises `BackupError`;
  stages `"backup"` and `"verify"`); `BackupOutcome(flavor, kind, path=None, files=0, bytes_in=0, bytes_zip=0,
  links=[], missing=[], reason="", pruned=[])` with `kind` in `created | skipped | failed`;
  `back_up(scan, root, *, keep, now=None, progress=None) -> BackupOutcome`;
  `back_up_all(scans, root, *, keep, progress=None, on_flavor=None) -> list[BackupOutcome]`.
- Manifest (`manifest.json`): `{"version": 1, "kind": "backup"|"pre-restore", "flavor": short, "flavor_folder":
  folder, "created": iso, "suite_version", "parts": [parts written], "parts_existing": [same], "files": [{"path":
  "<Part>/<rel>", "size": bytes stored, "mtime": float}], "links": ["<Part>/<rel>", ...]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_interface_backup_backup.py
from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.backup import BackupError
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup import backup as backup_module
from wowtools.tools.interface_backup.backup import back_up, back_up_all, write_zip
from wowtools.tools.interface_backup.scanner import scan_flavor

NOW = datetime(2026, 10, 4, 15, 30, 12)


class BackupTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.tmp = Path(t.name)
        self.wow = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavors = {f.folder: f for f in WowInstall(self.wow).flavors()}
        self.root = self.tmp / "bk" / "interface-backup"

    def scan(self, folder="_retail_"):
        return scan_flavor(self.flavors[folder], with_stats=False)

    def test_zip_layout_and_manifest(self):
        outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertEqual(outcome.path, self.root / "backup-retail-20261004-153012.zip")
        with zipfile.ZipFile(outcome.path) as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
            self.assertEqual(zf.read("Interface/AddOns/Auctionator/Auctionator.lua"), b"auc")
        self.assertIn("WTF/Config.wtf", names)
        self.assertEqual(manifest["kind"], "backup")
        self.assertEqual(manifest["flavor_folder"], "_retail_")
        self.assertEqual(manifest["parts"], ["Interface", "WTF"])
        self.assertEqual({f["path"] for f in manifest["files"]}, names - {"manifest.json"})
        self.assertFalse(list(self.root.glob("*.partial")))

    def test_only_wtf_flavor_and_empty_flavor(self):
        self.assertEqual(back_up(self.scan("_anniversary_"), self.root, keep=10, now=NOW).kind, "created")
        skipped = back_up(self.scan("_ptr_"), self.root, keep=10, now=NOW)
        self.assertEqual(skipped.kind, "skipped")

    def test_vanished_file_is_listed_and_zip_still_verifies(self):
        scan = self.scan()
        (self.wow / "_retail_" / "WTF" / "Config.wtf").unlink()
        outcome = back_up(scan, self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "created")
        self.assertEqual(outcome.missing, ["WTF/Config.wtf"])

    def test_grown_file_does_not_fail_verification(self):
        scan = self.scan()
        (self.wow / "_retail_" / "WTF" / "Config.wtf").write_bytes(b"much longer than before\n")
        self.assertEqual(back_up(scan, self.root, keep=10, now=NOW).kind, "created")

    def test_verify_failure_leaves_no_partial(self):
        with patch.object(backup_module, "verify_backup", side_effect=BackupError("corrupt")):
            outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.kind, "failed")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_backup_never_replaced(self):
        self.root.mkdir(parents=True)
        (self.root / "backup-retail-20261004-153012.zip").write_bytes(b"old")
        outcome = back_up(self.scan(), self.root, keep=10, now=NOW)
        self.assertEqual(outcome.path.name, "backup-retail-20261004-153012-2.zip")
        self.assertEqual((self.root / "backup-retail-20261004-153012.zip").read_bytes(), b"old")

    def test_prune_after_success_only(self):
        self.root.mkdir(parents=True)
        for day in (1, 2, 3):
            (self.root / f"backup-retail-2026100{day}-000000.zip").write_bytes(b"z")
        outcome = back_up(self.scan(), self.root, keep=2, now=NOW)
        self.assertEqual(len(outcome.pruned), 2)
        with patch.object(backup_module, "verify_backup", side_effect=BackupError("corrupt")):
            failed = back_up(self.scan(), self.root, keep=1, now=NOW)
        self.assertEqual(failed.pruned, [])
        self.assertEqual(len(list(self.root.glob("backup-retail-*.zip"))), 2)

    def test_all_flavors_continue_after_a_failure_and_log(self):
        scans = [self.scan("_retail_"), self.scan("_classic_era_")]
        real = backup_module.write_zip
        calls = []

        def flaky(scan, dest, **kw):
            calls.append(scan.flavor.folder)
            if scan.flavor.folder == "_retail_":
                raise BackupError("disk full")
            return real(scan, dest, **kw)

        with capture_events() as events, patch.object(backup_module, "write_zip", side_effect=flaky):
            outcomes = back_up_all(scans, self.root, keep=10)
        self.assertEqual([o.kind for o in outcomes], ["failed", "created"])
        names = [e["event"] for e in events]
        self.assertIn("ibackup.backup_failed", names)
        self.assertIn("ibackup.backup_created", names)

    def test_write_zip_selected_parts_for_safety(self):
        stats = write_zip(self.scan(), self.root / "pre-restore-retail-x.zip", kind="pre-restore", parts=("WTF",))
        with zipfile.ZipFile(stats.path) as zf:
            self.assertTrue(all(n.startswith("WTF/") or n == "manifest.json" for n in zf.namelist()))
            self.assertEqual(json.loads(zf.read("manifest.json"))["parts_existing"], ["WTF"])
```

- [ ] **Step 2: Run** — `python3 scripts/run_tests.py -k interface_backup_backup` → FAIL (`ImportError`).

- [ ] **Step 3: Implement** `backup.py`:

```python
"""Back up a flavor's Interface and WTF folders to one verified zip. UI-free."""
from __future__ import annotations

import json
import os
import shutil
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools import __version__
from wowtools.core.backup import MANIFEST_NAME, BackupError, verify_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import remove_quietly, rename_no_replace, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import now_iso
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.catalog import new_backup_path, prune_backups
from wowtools.tools.interface_backup.scanner import PARTS, SAMPLE, FlavorScan

Progress = Callable[[str, int, int, str], None]
MANIFEST_VERSION = 1
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


@dataclass
class ZipStats:
    path: Path
    files: int
    bytes_in: int
    bytes_zip: int
    missing: list[str]
    links: list[str]
    parts_existing: list[str]


@dataclass
class BackupOutcome:
    flavor: Flavor
    kind: str  # created | skipped | failed
    path: Path | None = None
    files: int = 0
    bytes_in: int = 0
    bytes_zip: int = 0
    links: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reason: str = ""
    pruned: list[Path] = field(default_factory=list)


def _zip_info(arcname: str, st: os.stat_result) -> zipfile.ZipInfo:
    stamp = time.localtime(st.st_mtime)[:6]
    info = zipfile.ZipInfo(arcname, stamp if stamp[0] >= 1980 else _ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (st.st_mode & 0xFFFF) << 16
    info.file_size = st.st_size  # lets zipfile pick ZIP64 for files over 2 GiB
    return info


def write_zip(scan: FlavorScan, dest: Path, *, kind: str, parts: tuple[str, ...] = PARTS,
              progress: Progress | None = None) -> ZipStats:
    """Zip the scanned parts of a flavor to dest as <Part>/<rel> plus manifest.json, through dest.partial, verify
    it, then move it into place without replacing anything. A file gone since the scan is left out and listed.
    Raises BackupError; never leaves the .partial behind."""
    report = safe_progress(progress)
    flavor = scan.flavor
    chosen = [scan.parts[p] for p in parts if scan.parts[p].exists]
    total = sum(len(p.files) for p in chosen)
    partial = dest.with_name(dest.name + ".partial")
    expected: dict[str, int] = {}
    files: list[dict] = []
    missing: list[str] = []
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(partial, "w", allowZip64=True) as zf:
            for part in chosen:
                for info in part.files:
                    arcname = f"{part.name}/{info.rel}"
                    source = part.path.joinpath(*info.rel.split("/"))
                    try:
                        st = os.stat(source)
                        with open(source, "rb") as src, zf.open(_zip_info(arcname, st), "w") as out:
                            shutil.copyfileobj(src, out, 1 << 20)
                    except FileNotFoundError:
                        missing.append(arcname)
                        continue
                    stored = zf.getinfo(arcname).file_size  # the bytes actually stored, even if the file grew
                    expected[arcname] = stored
                    files.append({"path": arcname, "size": stored, "mtime": st.st_mtime})
                    report("backup", len(files) + len(missing), total, arcname)
            links = [f"{p.name}/{rel}" for p in chosen for rel in p.links]
            manifest = {"version": MANIFEST_VERSION, "kind": kind, "flavor": flavor.short_name,
                        "flavor_folder": flavor.folder, "created": now_iso(), "suite_version": __version__,
                        "parts": [p.name for p in chosen], "parts_existing": [p.name for p in chosen],
                        "files": files, "links": links}
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
        verify_backup(partial, expected, progress=lambda i, n, name: report("verify", i, n, name))
        rename_no_replace(partial, dest)
    except BackupError:
        remove_quietly(partial)
        raise
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        remove_quietly(partial)
        raise BackupError(f"the backup failed: {exc}") from exc
    except BaseException:  # e.g. Ctrl+C while zipping: never leave a stray .partial behind
        remove_quietly(partial)
        raise
    return ZipStats(dest, len(files), sum(expected.values()), dest.stat().st_size, missing, links,
                    [p.name for p in chosen])


def back_up(scan: FlavorScan, root: Path, *, keep: int, now: datetime | None = None,
            progress: Progress | None = None) -> BackupOutcome:
    """One flavor: zip, verify, then prune its older backups (only after a success)."""
    flavor = scan.flavor
    if not scan.has_data:
        log_event("ibackup.backup_skipped", flavor=flavor.folder)
        return BackupOutcome(flavor, "skipped", reason="no Interface or WTF folder")
    dest = new_backup_path(root, flavor.short_name, now or datetime.now())
    try:
        stats = write_zip(scan, dest, kind="backup", progress=progress)
    except BackupError as exc:
        log_event("ibackup.backup_failed", flavor=flavor.folder, error=str(exc))
        return BackupOutcome(flavor, "failed", reason=str(exc))
    log_event("ibackup.backup_created", flavor=flavor.folder, path=to_stored(stats.path), files=stats.files,
              bytes_in=stats.bytes_in, bytes_zip=stats.bytes_zip, missing=len(stats.missing))
    if stats.links:
        log_event("ibackup.links_skipped", flavor=flavor.folder, count=len(stats.links), sample=stats.links[:SAMPLE])
    safe_progress(progress)("prune", 0, 0, flavor.display_name)
    pruned = prune_backups(root, flavor.short_name, keep)
    if pruned:
        log_event("ibackup.pruned", flavor=flavor.folder, removed=[p.name for p in pruned])
    return BackupOutcome(flavor, "created", stats.path, stats.files, stats.bytes_in, stats.bytes_zip, stats.links,
                         stats.missing, "", pruned)


def back_up_all(scans: list[FlavorScan], root: Path, *, keep: int, progress: Progress | None = None,
                on_flavor: Callable[[str], None] | None = None) -> list[BackupOutcome]:
    """Each flavor in turn; one failing never stops the next."""
    log_event("ibackup.backup_started", flavors=[s.flavor.folder for s in scans], dest=to_stored(root))
    outcomes = []
    for scan in scans:
        if on_flavor is not None:
            safe_progress(on_flavor)(scan.flavor.display_name)
        outcomes.append(back_up(scan, root, keep=keep, progress=progress))
    return outcomes
```

Note `back_up` looks up `write_zip` and `verify_backup` through the module globals so the tests can patch them.

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup` → PASS.
- [ ] **Step 5: Commit** — `feat(interface-backup): verified per-flavor zip backups with pruning`

---

### Task 5: open a backup and plan a restore (warnings)

**Files:**
- Create: `wowtools/tools/interface_backup/restore.py` (first half)
- Test: `tests/test_interface_backup_restore.py` (first classes)

**Interfaces:**
- Consumes: `FlavorScan`, `PARTS` (Task 3); `MANIFEST_NAME`; zips from `write_zip` (Task 4).
- Produces: `RestoreError(Exception)`; `split_entry(name) -> tuple[str, str]`;
  `BackupContents(path, kind, flavor_short, flavor_folder, created, parts: tuple[str, ...], files: dict[str,
  dict[str, tuple[int, float]]], links: list[str])` with `.sizes() -> dict[str, int]` (entry name → size, for
  `verify_backup`); `open_backup(path) -> BackupContents`; `RestorePlan(contents, flavor, parts, removed, newer,
  links_kept, links_removed, bytes_needed, free_bytes, leftovers)` (lists of `(part, rel)`) with `.low_space`;
  `plan_restore(contents, scan, parts, *, disk_usage=shutil.disk_usage) -> RestorePlan`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_interface_backup_restore.py
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup.backup import back_up
from wowtools.tools.interface_backup.restore import RestoreError, open_backup, plan_restore, split_entry
from wowtools.tools.interface_backup.scanner import scan_flavor

NOW = datetime(2026, 10, 4, 15, 30, 12)


def write_fake_zip(path: Path, names: list[str], flavor_folder="_retail_") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        files = []
        for name in names:
            zf.writestr(name, b"x")
            files.append({"path": name, "size": 1, "mtime": 0.0})
        zf.writestr("manifest.json", json.dumps({"version": 1, "kind": "backup", "flavor": "retail",
                                                 "flavor_folder": flavor_folder, "created": "",
                                                 "parts": ["Interface", "WTF"], "parts_existing": [],
                                                 "files": files, "links": []}))
    return path


class RestoreTestBase(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.tmp = Path(t.name)
        self.wow = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavor = next(f for f in WowInstall(self.wow).flavors() if f.folder == "_retail_")
        self.root = self.tmp / "bk" / "interface-backup"
        self.backup = back_up(scan_flavor(self.flavor, with_stats=False), self.root, keep=10, now=NOW).path

    def scan(self):
        return scan_flavor(self.flavor, with_stats=True)


class SplitEntryTest(unittest.TestCase):
    def test_safe(self):
        self.assertEqual(split_entry("Interface/AddOns/A/a.lua"), ("Interface", "AddOns/A/a.lua"))

    def test_unsafe(self):
        for name in ("../x", "/abs", "C:/x", "Interface\\x", "Interface/../x", "Interface/./x", "Other/x",
                     "Interface/a:stream", "Interface/dot.", "Interface/space ", "Interface", "Interface//x",
                     "Interface/x/"):
            with self.subTest(name=name), self.assertRaises(RestoreError):
                split_entry(name)


class OpenBackupTest(RestoreTestBase):
    def test_reads_our_zip(self):
        c = open_backup(self.backup)
        self.assertEqual((c.flavor_folder, c.kind, c.parts), ("_retail_", "backup", ("Interface", "WTF")))
        self.assertIn("AddOns/Auctionator/Auctionator.lua", c.files["Interface"])

    def test_refuses_foreign_or_unsafe(self):
        plain = self.tmp / "plain.zip"
        with zipfile.ZipFile(plain, "w") as zf:
            zf.writestr("Interface/a.lua", b"x")
        with self.assertRaises(RestoreError):
            open_backup(plain)  # no manifest
        with self.assertRaises(RestoreError):
            open_backup(write_fake_zip(self.tmp / "evil.zip", ["Interface/../../x.lua"]))
        with self.assertRaises(RestoreError):
            open_backup(write_fake_zip(self.tmp / "case.zip", ["WTF/a.txt", "WTF/A.TXT"]))
        with self.assertRaises(RestoreError):
            open_backup(write_fake_zip(self.tmp / "flav.zip", ["WTF/a.txt"], flavor_folder="../x"))
        (self.tmp / "junk.zip").write_bytes(b"not a zip")
        with self.assertRaises(RestoreError):
            open_backup(self.tmp / "junk.zip")


class PlanRestoreTest(RestoreTestBase):
    def test_removed_and_newer(self):
        new = self.wow / "_retail_" / "Interface" / "AddOns" / "WeakAuras" / "WeakAuras.lua"
        new.parent.mkdir(parents=True); new.write_text("wa")
        cfg = self.wow / "_retail_" / "WTF" / "Config.wtf"
        later = time.time() + 3600
        os.utime(cfg, (later, later))
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface", "WTF"))
        self.assertIn(("Interface", "AddOns/WeakAuras/WeakAuras.lua"), plan.removed)
        self.assertIn(("WTF", "Config.wtf"), plan.newer)
        self.assertGreater(plan.bytes_needed, 0)

    def test_only_chosen_parts(self):
        (self.wow / "_retail_" / "WTF" / "extra.txt").write_text("e")
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        self.assertFalse([p for p in plan.removed if p[0] == "WTF"])

    def test_links_kept_or_removed(self):
        repo = self.tmp / "repo"; repo.mkdir()
        addons = self.wow / "_retail_" / "Interface" / "AddOns"
        try:
            os.symlink(repo, addons / "Dev", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        self.assertEqual(plan.links_kept, [("Interface", "AddOns/Dev")])
        self.assertEqual(plan.links_removed, [])

    def test_link_where_backup_has_files_is_removed(self):
        addons = self.wow / "_retail_" / "Interface" / "AddOns"
        repo = self.tmp / "repo"; repo.mkdir()
        os.rename(addons / "Details", self.tmp / "details-moved")
        try:
            os.symlink(repo, addons / "Details", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        self.assertEqual(plan.links_removed, [("Interface", "AddOns/Details")])

    def test_part_missing_from_backup_refused(self):
        wtf_only = back_up(scan_flavor(next(f for f in WowInstall(self.wow).flavors() if f.folder == "_anniversary_"),
                                       with_stats=False), self.root, keep=10, now=NOW).path
        contents = open_backup(wtf_only)
        self.assertEqual(contents.parts, ("WTF",))

    def test_low_space(self):
        usage = namedtuple("Usage", "total used free")
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",),
                            disk_usage=lambda p: usage(0, 0, 1))
        self.assertTrue(plan.low_space)
        roomy = plan_restore(open_backup(self.backup), self.scan(), ("Interface",),
                             disk_usage=lambda p: usage(0, 0, 10 ** 12))
        self.assertFalse(roomy.low_space)
```
(Add `from collections import namedtuple` to the test module's imports.)

- [ ] **Step 2: Run** — `python3 scripts/run_tests.py -k interface_backup_restore` → FAIL (`ImportError`).

- [ ] **Step 3: Implement** — `restore.py` (first half):

```python
"""Restore a flavor's Interface and/or WTF folders from a backup: exact replace through a staging folder and a
folder swap, after a pre-restore safety backup, with a run journal for Undo. UI-free."""
from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.backup import MANIFEST_NAME
from wowtools.core.install import Flavor
from wowtools.tools.interface_backup.scanner import PARTS, FlavorScan

NEWER_SLACK = 2.0  # zip timestamps have 2-second steps
_DRIVE = re.compile(r"^[A-Za-z]:")
_FLAVOR_FOLDER = re.compile(r"^_[A-Za-z0-9_]+_$")
_BAD_CHARS = set('<>:"|?*\x00')


class RestoreError(Exception):
    """A backup cannot be restored (unreadable, not ours, unsafe names), or a restore cannot start. Nothing was
    changed."""


def split_entry(name: str) -> tuple[str, str]:
    """('Interface', 'AddOns/A/a.lua') for a safe zip entry name; RestoreError for anything that could land
    outside the part folder on Windows or POSIX."""
    if not name or "\\" in name or name.startswith("/") or _DRIVE.match(name):
        raise RestoreError(f"unsafe entry name in the backup: {name!r}")
    parts = name.split("/")
    if (len(parts) < 2 or parts[0] not in PARTS
            or any(p in ("", ".", "..") or p != p.rstrip(". ") or _BAD_CHARS & set(p) for p in parts[1:])):
        raise RestoreError(f"unsafe entry name in the backup: {name!r}")
    return parts[0], "/".join(parts[1:])


@dataclass
class BackupContents:
    path: Path
    kind: str
    flavor_short: str
    flavor_folder: str
    created: str
    parts: tuple[str, ...]
    files: dict[str, dict[str, tuple[int, float]]]  # part -> rel -> (size, mtime)
    links: list[str] = field(default_factory=list)

    def sizes(self, parts: tuple[str, ...] | None = None) -> dict[str, int]:
        """Entry name -> size, for verify_backup (all parts by default)."""
        return {f"{part}/{rel}": size for part in (parts or PARTS) for rel, (size, _) in self.files[part].items()}


def open_backup(path: Path) -> BackupContents:
    """Read a backup's manifest and check every entry name. Raises RestoreError."""
    try:
        with zipfile.ZipFile(path) as zf:
            sizes = {info.filename: info.file_size for info in zf.infolist()}
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME))
            except KeyError:
                raise RestoreError("not an Interface Backup zip (it has no manifest.json)") from None
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise RestoreError(f"the backup cannot be read: {exc}") from exc
    try:
        if manifest["version"] != 1 or manifest["kind"] not in ("backup", "pre-restore"):
            raise RestoreError("not an Interface Backup zip (unknown manifest)")
        folder = str(manifest["flavor_folder"])
        if not _FLAVOR_FOLDER.match(folder):
            raise RestoreError(f"the backup names an invalid flavor folder: {folder!r}")
        names = [n for n in sizes if n != MANIFEST_NAME]
        seen: set[str] = set()
        for name in names:
            split_entry(name)
            if name.casefold() in seen:
                raise RestoreError(f"the backup has two entries that differ only in case: {name}")
            seen.add(name.casefold())
        listed = {str(f["path"]): float(f["mtime"]) for f in manifest["files"]}
        if set(listed) != set(names):
            raise RestoreError("the backup's manifest does not match its contents")
        files: dict[str, dict[str, tuple[int, float]]] = {part: {} for part in PARTS}
        for name, mtime in listed.items():
            part, rel = split_entry(name)
            files[part][rel] = (sizes[name], mtime)
        parts = tuple(p for p in PARTS if p in manifest["parts"])
        return BackupContents(path, str(manifest["kind"]), str(manifest["flavor"]), folder,
                              str(manifest.get("created", "")), parts, files,
                              [str(link) for link in manifest.get("links", [])])
    except (KeyError, TypeError, ValueError) as exc:
        raise RestoreError(f"the backup's manifest is damaged: {exc}") from exc


@dataclass
class RestorePlan:
    contents: BackupContents
    flavor: Flavor
    parts: tuple[str, ...]
    removed: list[tuple[str, str]]  # on disk now, not in the backup: lost by the restore
    newer: list[tuple[str, str]]  # on disk now and newer than the backup's copy
    links_kept: list[tuple[str, str]]
    links_removed: list[tuple[str, str]]  # the backup has files there: the link (never its target) goes
    bytes_needed: int
    free_bytes: int | None
    leftovers: list[Path]

    @property
    def low_space(self) -> bool:
        return self.free_bytes is not None and self.bytes_needed > self.free_bytes


def _free_space(path: Path, disk_usage: Callable) -> int | None:
    try:
        return int(disk_usage(path).free)
    except OSError:
        return None


def plan_restore(contents: BackupContents, scan: FlavorScan, parts: tuple[str, ...], *,
                 disk_usage: Callable = shutil.disk_usage) -> RestorePlan:
    """Compare the backup's chosen parts with what is on disk now. Raises RestoreError for a part the backup does
    not hold or a part folder that is itself a link."""
    removed: list[tuple[str, str]] = []
    newer: list[tuple[str, str]] = []
    kept: list[tuple[str, str]] = []
    dropped: list[tuple[str, str]] = []
    needed = 0
    for part in parts:
        if part not in contents.parts:
            raise RestoreError(f"the backup has no {part} folder")
        live = scan.parts[part]
        if live.linked:
            raise RestoreError(f"{part} is a link to another folder; restore it by hand")
        backup_files = {rel.casefold(): (size, mtime) for rel, (size, mtime) in contents.files[part].items()}
        folders = {"/".join(rel.split("/")[:i]) for rel in backup_files for i in range(1, rel.count("/") + 1)}
        needed += sum(size for size, _ in backup_files.values())
        for info in live.files:
            match = backup_files.get(info.rel.casefold())
            if match is None:
                removed.append((part, info.rel))
            elif info.mtime is not None and info.mtime > match[1] + NEWER_SLACK:
                newer.append((part, info.rel))
        for link in live.links:
            key = link.casefold()
            (dropped if key in backup_files or key in folders else kept).append((part, link))
    return RestorePlan(contents, scan.flavor, tuple(parts), removed, newer, kept, dropped, needed,
                       _free_space(scan.flavor.path, disk_usage), list(scan.leftovers))
```

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup` → PASS.
- [ ] **Step 5: Commit** — `feat(interface-backup): open backups safely and plan a restore with warnings`

---

### Task 6: run a restore (safety backup, extract, swap, journal)

**Files:**
- Create: `wowtools/tools/interface_backup/journal.py`
- Modify: `wowtools/tools/interface_backup/restore.py` (second half)
- Test: `tests/test_interface_backup_restore.py` (add `RunRestoreTest`)

**Interfaces:**
- Consumes: Tasks 1–5; `core.journal` (`JournalWriter`, `new_journal_path`, `read_journal`, `latest_undoable`,
  `list_journals`, `prune_journals`); `catalog.new_backup_path`, `prune_safety`.
- Produces (journal.py): `PATH_FIELDS = ("flavor_path", "backup", "zip")`,
  `read_restore_journal(path) -> Journal`, `latest_undoable(folder) -> Path | None` (newest not-undone journal
  with at least one `replaced` entry), `referenced_safety_zips(folder) -> set[str] | None` (file names; None if a
  journal cannot be read).
- Produces (restore.py): `SwapError(OSError)` with `.rolled_back: bool`; `PartOutcome(part, kind, reason="")`
  with kind in `restored | rolled_back | failed | replaced_left`; `RestoreResult(flavor, backup, parts:
  list[PartOutcome], safety_zip=None, journal_path=None, undo=False)` with `.ok`;
  `RestoreStopped(Exception)` with `.result`; `replace_part(zf, files: dict[str, tuple[int, float]], flavor_path,
  part, keep_links: list[str], *, progress=None, rename=os.rename) -> str | None` (returns why the old copy was
  left, or None); `restore(plan, *, root, journal_dir, keep_journals, now=None, progress=None, rename=os.rename)
  -> RestoreResult`. Stages: `verify`, `safety`, `safety_verify`, `extract`, `swap`, `cleanup`.
- Journal: header `{"flavor": folder, "flavor_path": Path, "backup": Path, "parts": [...], "suite_version"}`;
  entries `{"action": "safety_backup", "zip": Path, "parts_existing": [...]}` and `{"action": "replaced", "part",
  "existed": bool}`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_interface_backup_restore.py`; add imports
  `from unittest.mock import patch`, `from wowtools.core.events import capture_events`,
  `from wowtools.tools.interface_backup.journal import latest_undoable, read_restore_journal`,
  `from wowtools.tools.interface_backup.restore import restore`)

```python
class RunRestoreTest(RestoreTestBase):
    def setUp(self):
        super().setUp()
        self.journal_dir = self.wow / "wow-tools" / "interface-backup" / "journal"
        self.retail = self.wow / "_retail_"

    def run_restore(self, parts=("Interface", "WTF"), **kw):
        plan = plan_restore(open_backup(self.backup), self.scan(), parts)
        return restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10, **kw)

    def test_exact_replace_both_parts(self):
        (self.retail / "Interface" / "AddOns" / "WeakAuras").mkdir()
        (self.retail / "Interface" / "AddOns" / "WeakAuras" / "wa.lua").write_text("wa")
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"changed")
        result = self.run_restore()
        self.assertEqual([p.kind for p in result.parts], ["restored", "restored"])
        self.assertFalse((self.retail / "Interface" / "AddOns" / "WeakAuras").exists())
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"SET a 1\n")
        self.assertFalse(list(self.retail.glob("*.restoring")) + list(self.retail.glob("*.replaced")))
        self.assertTrue(result.safety_zip.exists())
        self.assertEqual(result.safety_zip.name[:20], "pre-restore-retail-2")
        journal = read_restore_journal(result.journal_path)
        self.assertEqual([e["action"] for e in journal.entries], ["safety_backup", "replaced", "replaced"])
        self.assertEqual(latest_undoable(self.journal_dir), result.journal_path)

    def test_single_part_leaves_other_alone(self):
        (self.retail / "WTF" / "extra.txt").write_text("e")
        self.run_restore(("Interface",))
        self.assertTrue((self.retail / "WTF" / "extra.txt").exists())

    def test_mtimes_restored(self):
        cfg = self.retail / "WTF" / "Config.wtf"
        before = open_backup(self.backup).files["WTF"]["Config.wtf"][1]
        cfg.write_bytes(b"changed")
        self.run_restore(("WTF",))
        self.assertAlmostEqual(cfg.stat().st_mtime, before, delta=1)

    def test_part_missing_on_disk_is_created(self):
        import shutil
        shutil.rmtree(self.retail / "Interface")
        result = self.run_restore(("Interface",))
        self.assertEqual(result.parts[0].kind, "restored")
        self.assertTrue((self.retail / "Interface" / "AddOns" / "Details" / "core.lua").exists())
        self.assertEqual(read_restore_journal(result.journal_path).entries[1]["existed"], False)

    def test_swap_failure_rolls_back_exactly(self):
        (self.retail / "Interface" / "new.txt").write_text("n")
        real = os.rename

        def flaky(src, dst):
            if str(src).endswith("Interface.restoring"):
                raise PermissionError(13, "locked by WoW")
            real(src, dst)

        with capture_events() as events:
            result = self.run_restore(("Interface",), rename=flaky)
        self.assertEqual(result.parts[0].kind, "rolled_back")
        self.assertTrue((self.retail / "Interface" / "new.txt").exists())
        self.assertFalse((self.retail / "Interface.restoring").exists())
        self.assertFalse((self.retail / "Interface.replaced").exists())
        self.assertIn("ibackup.part_rolled_back", [e["event"] for e in events])
        self.assertIsNone(latest_undoable(self.journal_dir))  # nothing was replaced: nothing to undo

    def test_links_kept_and_target_untouched(self):
        repo = self.tmp / "repo"; repo.mkdir(); (repo / "dev.lua").write_text("dev")
        link = self.retail / "Interface" / "AddOns" / "Dev"
        try:
            os.symlink(repo, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        self.run_restore(("Interface",))
        self.assertTrue(os.path.islink(link))
        self.assertEqual((repo / "dev.lua").read_text(), "dev")

    def test_leftover_blocks(self):
        (self.retail / "WTF.replaced").mkdir()
        with self.assertRaises(RestoreError):
            self.run_restore(("Interface",))
        self.assertFalse(list(self.root.glob("pre-restore-*")))

    def test_corrupt_backup_changes_nothing(self):
        plan = plan_restore(open_backup(self.backup), self.scan(), ("Interface",))
        data = bytearray(self.backup.read_bytes()); data[40] ^= 0xFF; self.backup.write_bytes(bytes(data))
        (self.retail / "Interface" / "new.txt").write_text("n")
        with self.assertRaises(RestoreError):
            restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10)
        self.assertTrue((self.retail / "Interface" / "new.txt").exists())
        self.assertIsNone(latest_undoable(self.journal_dir))

    def test_journal_and_safety_pruning(self):
        first = self.run_restore(("WTF",))
        second = restore(plan_restore(open_backup(self.backup), self.scan(), ("WTF",)), root=self.root,
                         journal_dir=self.journal_dir, keep_journals=1)
        self.assertFalse(first.journal_path.exists())
        self.assertFalse(first.safety_zip.exists())
        self.assertTrue(second.safety_zip.exists())
```
(If two restores in the same second collide on `new_journal_path`/`new_backup_path`, they get `-2` names — that
is expected and fine.)

- [ ] **Step 2: Run** — `python3 scripts/run_tests.py -k RunRestore` → FAIL (`ImportError`).

- [ ] **Step 3: Implement**

`journal.py`:
```python
"""Restore journals: the tool's entry fields over core/journal.py. A restore writes one journal; Undo uses the
newest one that replaced a part and was not undone."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from wowtools.core import journal as core_journal
from wowtools.core.journal import Journal, list_journals, read_journal

PATH_FIELDS = ("flavor_path", "backup", "zip")


def read_restore_journal(path: Path) -> Journal:
    journal = read_journal(path, path_fields=PATH_FIELDS)
    for name in ("flavor_path", "backup"):  # header paths: read_journal converts entry fields only
        if isinstance(journal.header.get(name), str):
            journal.header[name] = core_journal.to_native(journal.header[name])
    return journal


def _replaced_only(path: Path) -> Journal:
    journal = read_restore_journal(path)
    return replace(journal, entries=[e for e in journal.entries if e.get("action") == "replaced"])


def latest_undoable(folder: Path | None) -> Path | None:
    """The newest restore journal that replaced at least one part and was not undone."""
    return core_journal.latest_undoable(folder, reader=_replaced_only)


def referenced_safety_zips(folder: Path | None) -> set[str] | None:
    """File names of the safety zips the remaining journals name; None if any journal cannot be read (then no
    safety zip is deleted)."""
    names: set[str] = set()
    for path in list_journals(folder):
        try:
            journal = read_restore_journal(path)
        except (OSError, ValueError):
            return None
        names.update(Path(e["zip"]).name for e in journal.entries
                     if e.get("action") == "safety_backup" and e.get("zip"))
    return names
```
(`core.journal` imports `to_native` from `core.paths`; import it from `wowtools.core.paths` directly instead of
through `core_journal` if Ruff complains.)

`restore.py` (second half; add imports `from datetime import datetime`, `from wowtools import __version__`,
`from wowtools.core.backup import BackupError, verify_backup`, `from wowtools.core.events import log_event`,
`from wowtools.core.fsutil import remove_tree_no_follow, safe_progress`,
`from wowtools.core.journal import JournalWriter, new_journal_path, prune_journals`,
`from wowtools.core.paths import to_stored`,
`from wowtools.tools.interface_backup.backup import write_zip`,
`from wowtools.tools.interface_backup.catalog import new_backup_path, prune_safety`,
`from wowtools.tools.interface_backup.journal import referenced_safety_zips`,
`from wowtools.tools.interface_backup.scanner import leftover_folders, scan_flavor`):

```python
Rename = Callable[[Path, Path], None]


class SwapError(OSError):
    """A part could not be replaced. rolled_back says whether it is exactly as it was."""

    def __init__(self, message: str, *, rolled_back: bool) -> None:
        super().__init__(message)
        self.rolled_back = rolled_back


@dataclass
class PartOutcome:
    part: str
    kind: str  # restored | rolled_back | failed | replaced_left
    reason: str = ""


@dataclass
class RestoreResult:
    flavor: Flavor
    backup: Path
    parts: list[PartOutcome] = field(default_factory=list)
    safety_zip: Path | None = None
    journal_path: Path | None = None
    undo: bool = False

    @property
    def ok(self) -> bool:
        return all(p.kind in ("restored", "replaced_left") for p in self.parts)


class RestoreStopped(Exception):
    """A restore or undo stopped unexpectedly. `result` holds what was done; the journal records it."""

    def __init__(self, message: str, result: RestoreResult) -> None:
        super().__init__(message)
        self.result = result


def _native(base: Path, rel: str) -> Path:
    return base.joinpath(*rel.split("/"))


def _extract(zf: zipfile.ZipFile, part: str, files: dict[str, tuple[int, float]], staging: Path,
             report: Callable[..., None]) -> None:
    staging.mkdir()  # FileExistsError if a staging folder is already there
    total = len(files)
    for index, (rel, (_, mtime)) in enumerate(sorted(files.items()), 1):
        target = _native(staging, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(f"{part}/{rel}") as src, open(target, "xb") as out:
            shutil.copyfileobj(src, out, 1 << 20)
        os.utime(target, (mtime, mtime))
        report("extract", index, total, f"{part}/{rel}")


def _roll_back(live: Path, staging: Path, moved: list[str], rename: Rename) -> str | None:
    problems = []
    for rel in reversed(moved):
        try:
            rename(_native(staging, rel), _native(live, rel))
        except OSError as exc:
            problems.append(f"the link {rel} is still in {to_stored(staging)} ({exc})")
    if not problems and os.path.lexists(staging):
        try:
            remove_tree_no_follow(staging)
        except OSError as exc:
            problems.append(f"{to_stored(staging)} could not be deleted ({exc})")
    return "; ".join(problems) or None


def replace_part(zf: zipfile.ZipFile, files: dict[str, tuple[int, float]], flavor_path: Path, part: str,
                 keep_links: list[str], *, progress: Callable[..., None] | None = None,
                 rename: Rename = os.rename) -> str | None:
    """Swap <flavor>/<part> for the zip's copy: extract to <part>.restoring, move the links to keep into it, rename
    <part> to <part>.replaced and <part>.restoring to <part>, then delete <part>.replaced (never through a link).
    Returns why the old copy could not be fully deleted, or None. Raises SwapError when the part could not be
    replaced (rolled_back=True: it is exactly as it was)."""
    report = safe_progress(progress)
    live, staging, old = (flavor_path / part, flavor_path / f"{part}.restoring", flavor_path / f"{part}.replaced")
    if os.path.lexists(staging) or os.path.lexists(old):
        raise SwapError(f"{staging.name} or {old.name} is left from an interrupted restore", rolled_back=True)
    moved: list[str] = []
    existed = os.path.lexists(live)
    try:
        _extract(zf, part, files, staging, report)
        report("swap", 0, 0, part)
        for rel in keep_links:
            _native(staging, rel).parent.mkdir(parents=True, exist_ok=True)
            rename(_native(live, rel), _native(staging, rel))
            moved.append(rel)
        if existed:
            rename(live, old)
        try:
            rename(staging, live)
        except OSError:
            if existed:
                rename(old, live)
            raise
    except (OSError, zipfile.BadZipFile) as exc:
        problem = _roll_back(live, staging, moved, rename)
        raise SwapError(f"{part} could not be replaced: {exc}" + (f"; {problem}" if problem else ""),
                        rolled_back=problem is None) from exc
    if not existed:
        return None
    report("cleanup", 0, 0, to_stored(old))
    try:
        remove_tree_no_follow(old)
    except OSError as exc:
        return f"the old copy could not be fully deleted: {to_stored(old)} ({exc.strerror or exc})"
    return None


def _log_part(flavor: Flavor, outcome: PartOutcome, *, undo: bool = False) -> None:
    event = {"restored": "ibackup.part_restored", "replaced_left": "ibackup.replaced_left"}.get(
        outcome.kind, "ibackup.undo_failed" if undo else "ibackup.part_rolled_back")
    log_event(event, flavor=flavor.folder, part=outcome.part, kind=outcome.kind, reason=outcome.reason, undo=undo)


def restore(plan: RestorePlan, *, root: Path, journal_dir: Path, keep_journals: int, now: datetime | None = None,
            progress: Callable[..., None] | None = None, rename: Rename = os.rename) -> RestoreResult:
    """Restore the plan's parts. Raises RestoreError (nothing changed) or RestoreStopped (stopped part-way; the
    journal holds what was done)."""
    report = safe_progress(progress)
    flavor, contents = plan.flavor, plan.contents
    if leftover_folders(flavor):
        raise RestoreError("a folder from an interrupted restore is still there: "
                           + ", ".join(to_stored(p) for p in leftover_folders(flavor)))
    result = RestoreResult(flavor, contents.path)
    writer = JournalWriter(new_journal_path(journal_dir, now),
                           {"flavor": flavor.folder, "flavor_path": flavor.path, "backup": contents.path,
                            "parts": list(plan.parts), "suite_version": __version__})
    try:
        writer.open()
    except OSError as exc:
        raise RestoreError(f"the restore journal cannot be written: {exc}") from exc
    result.journal_path = writer.path
    log_event("ibackup.restore_started", flavor=flavor.folder, backup=to_stored(contents.path), parts=list(plan.parts),
              removed=len(plan.removed), newer=len(plan.newer), links_kept=len(plan.links_kept),
              links_removed=len(plan.links_removed))
    try:
        try:
            verify_backup(contents.path, contents.sizes(),
                          progress=lambda i, n, name: report("verify", i, n, name))
        except (BackupError, OSError, zipfile.BadZipFile) as exc:
            raise RestoreError(f"the backup did not verify, nothing was changed: {exc}") from exc
        scan = scan_flavor(flavor, with_stats=False, parts=plan.parts)
        safety = new_backup_path(root, flavor.short_name, now or datetime.now(), kind="pre-restore")
        try:
            stats = write_zip(scan, safety, kind="pre-restore", parts=plan.parts,
                              progress=lambda s, i, n, d: report("safety" if s == "backup" else "safety_verify",
                                                                 i, n, d))
        except BackupError as exc:
            raise RestoreError(f"the safety backup failed, nothing was changed: {exc}") from exc
        writer.add_entry({"action": "safety_backup", "zip": safety, "parts_existing": stats.parts_existing})
        result.safety_zip = safety
        log_event("ibackup.safety_created", flavor=flavor.folder, path=to_stored(safety), files=stats.files)
        with zipfile.ZipFile(contents.path) as zf:
            for part in plan.parts:
                keep = [rel for p, rel in plan.links_kept if p == part]
                try:
                    left = replace_part(zf, contents.files[part], flavor.path, part, keep, progress=report,
                                        rename=rename)
                except SwapError as exc:
                    outcome = PartOutcome(part, "rolled_back" if exc.rolled_back else "failed", str(exc))
                else:
                    writer.add_entry({"action": "replaced", "part": part, "existed": part in stats.parts_existing})
                    outcome = PartOutcome(part, "replaced_left" if left else "restored", left or "")
                result.parts.append(outcome)
                _log_part(flavor, outcome)
        writer.finish()
    except RestoreError:
        raise
    except Exception as exc:
        log_event("ibackup.restore_stopped", flavor=flavor.folder, error=f"{type(exc).__name__}: {exc}")
        raise RestoreStopped(f"{type(exc).__name__}: {exc}", result) from exc
    finally:
        writer.discard_if_empty()
    log_event("ibackup.restore_completed", flavor=flavor.folder,
              parts={p.part: p.kind for p in result.parts}, ok=result.ok)
    report("cleanup", 0, 0, "journals")
    pruned = prune_journals(journal_dir, keep_journals)
    referenced = referenced_safety_zips(journal_dir)
    dropped = prune_safety(root, referenced) if referenced is not None else []
    if pruned or dropped:
        log_event("ibackup.journal_pruned", journals=[p.name for p in pruned], safety=[p.name for p in dropped])
    return result
```
Note: when the run raises `RestoreError` after the journal was opened but before any entry, `discard_if_empty()`
removes the header-only journal. If `restore_completed` must be logged at warning level when a part failed, use
the same mechanism the organizer uses for `shots.organize_completed` (see Task 2 note).

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup` → PASS.
- [ ] **Step 5: Commit** — `feat(interface-backup): exact-replace restore with safety backup and journal`

---

### Task 7: undo a restore

**Files:**
- Create: `wowtools/tools/interface_backup/undo.py`
- Test: `tests/test_interface_backup_undo.py`

**Interfaces:**
- Consumes: `read_restore_journal`, `latest_undoable` (Task 6), `open_backup`, `plan_restore`, `replace_part`,
  `RestoreError`, `RestoreResult`, `PartOutcome`, `RestoreStopped` (Tasks 5–6); `core.journal.mark_undone`.
- Produces: `undo_restore(journal_path, *, wow_root, root, progress=None, rename=os.rename) -> RestoreResult`
  (`undo=True`; raises `RestoreError` when refused, nothing changed). Stages: `verify`, `extract`, `swap`,
  `cleanup`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_interface_backup_undo.py
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup.backup import back_up
from wowtools.tools.interface_backup.journal import latest_undoable
from wowtools.tools.interface_backup.restore import RestoreError, open_backup, plan_restore, restore
from wowtools.tools.interface_backup.scanner import scan_flavor
from wowtools.tools.interface_backup.undo import undo_restore

NOW = datetime(2026, 10, 4, 15, 30, 12)


class UndoTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.tmp = Path(t.name)
        self.wow = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavor = next(f for f in WowInstall(self.wow).flavors() if f.folder == "_retail_")
        self.retail = self.wow / "_retail_"
        self.root = self.tmp / "bk" / "interface-backup"
        self.journal_dir = self.wow / "wow-tools" / "interface-backup" / "journal"
        self.backup = back_up(scan_flavor(self.flavor, with_stats=False), self.root, keep=10, now=NOW).path

    def do_restore(self, parts=("Interface", "WTF")):
        plan = plan_restore(open_backup(self.backup), scan_flavor(self.flavor, with_stats=True), parts)
        return restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10)

    def test_undo_puts_both_parts_back(self):
        (self.retail / "Interface" / "after.txt").write_text("after")
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"mine")
        result = self.do_restore()
        self.assertFalse((self.retail / "Interface" / "after.txt").exists())
        undone = undo_restore(result.journal_path, wow_root=self.wow, root=self.root)
        self.assertTrue(undone.undo and undone.ok)
        self.assertEqual((self.retail / "Interface" / "after.txt").read_text(), "after")
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"mine")
        self.assertIsNone(latest_undoable(self.journal_dir))  # never offered again

    def test_part_that_did_not_exist_is_removed(self):
        shutil.rmtree(self.retail / "Interface")
        result = self.do_restore(("Interface",))
        self.assertTrue((self.retail / "Interface").exists())
        undo_restore(result.journal_path, wow_root=self.wow, root=self.root)
        self.assertFalse((self.retail / "Interface").exists())

    def test_missing_safety_zip_refused(self):
        result = self.do_restore(("WTF",))
        result.safety_zip.unlink()
        with self.assertRaises(RestoreError):
            undo_restore(result.journal_path, wow_root=self.wow, root=self.root)
        self.assertEqual(latest_undoable(self.journal_dir), result.journal_path)

    def test_journal_from_another_wow_folder_refused(self):
        result = self.do_restore(("WTF",))
        lines = result.journal_path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0]); header["flavor_path"] = str(self.tmp / "Other" / "_retail_")
        result.journal_path.write_text("\n".join([json.dumps(header), *lines[1:]]) + "\n", encoding="utf-8")
        with self.assertRaises(RestoreError):
            undo_restore(result.journal_path, wow_root=self.wow, root=self.root)

    def test_safety_zip_outside_backup_root_refused(self):
        result = self.do_restore(("WTF",))
        moved = self.tmp / result.safety_zip.name
        shutil.copy2(result.safety_zip, moved)
        text = result.journal_path.read_text(encoding="utf-8").replace(
            json.dumps(str(result.safety_zip))[1:-1], json.dumps(str(moved))[1:-1])
        result.journal_path.write_text(text, encoding="utf-8")
        with self.assertRaises(RestoreError):
            undo_restore(result.journal_path, wow_root=self.wow, root=self.root)
```
(The journal stores paths with `to_stored()`; on Linux that is the POSIX path unchanged, so the string replace
works in the test environment.)

- [ ] **Step 2: Run** — `python3 scripts/run_tests.py -k interface_backup_undo` → FAIL (`ImportError`).

- [ ] **Step 3: Implement** `undo.py`:

```python
"""Undo a restore: put the replaced parts back from the restore's safety backup. UI-free."""
from __future__ import annotations

import os
import zipfile
from collections.abc import Callable
from pathlib import Path

from wowtools.core.backup import BackupError, verify_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import remove_tree_no_follow, safe_progress
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.journal import mark_undone
from wowtools.tools.interface_backup.journal import read_restore_journal
from wowtools.tools.interface_backup.restore import (PartOutcome, RestoreError, RestoreResult, RestoreStopped,
                                                     SwapError, _log_part, open_backup, plan_restore, replace_part)
from wowtools.tools.interface_backup.scanner import PARTS, scan_flavor


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def undo_restore(journal_path: Path, *, wow_root: Path, root: Path, progress: Callable[..., None] | None = None,
                 rename: Callable[[Path, Path], None] = os.rename) -> RestoreResult:
    report = safe_progress(progress)
    try:
        journal = read_restore_journal(journal_path)
    except (OSError, ValueError) as exc:
        raise RestoreError(f"the journal cannot be read: {exc}") from exc
    if journal.undone is not None:
        raise RestoreError("this restore was already undone")
    folder = str(journal.header.get("flavor", ""))
    flavor_path = journal.header.get("flavor_path")
    flavors = {f.folder: f for f in WowInstall(wow_root).flavors()}
    if folder not in flavors or not isinstance(flavor_path, Path) or not _same(flavor_path, flavors[folder].path):
        raise RestoreError("the journal is not for a flavor of the configured WoW folder")
    flavor: Flavor = flavors[folder]
    safety = next((e for e in journal.entries if e.get("action") == "safety_backup"), None)
    zip_path = safety.get("zip") if safety else None
    if not isinstance(zip_path, Path) or not _same(zip_path.parent, root):
        raise RestoreError("the journal's safety backup is not in the backup folder")
    if not zip_path.is_file():
        raise RestoreError(f"the safety backup is gone: {zip_path.name}")
    contents = open_backup(zip_path)
    try:
        verify_backup(zip_path, contents.sizes(), progress=lambda i, n, name: report("verify", i, n, name))
    except (BackupError, OSError, zipfile.BadZipFile) as exc:
        raise RestoreError(f"the safety backup did not verify, nothing was changed: {exc}") from exc
    replaced = [e for e in journal.entries if e.get("action") == "replaced" and e.get("part") in PARTS]
    result = RestoreResult(flavor, zip_path, journal_path=journal_path, undo=True)
    log_event("ibackup.undo_started", flavor=folder, journal=journal_path.name, parts=[e["part"] for e in replaced])
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for entry in reversed(replaced):
                part = entry["part"]
                try:
                    if entry.get("existed"):
                        if part not in contents.parts:
                            raise SwapError(f"the safety backup has no {part} folder", rolled_back=True)
                        plan = plan_restore(contents, scan_flavor(flavor, with_stats=False, parts=(part,)), (part,))
                        keep = [rel for p, rel in plan.links_kept if p == part]
                        left = replace_part(zf, contents.files[part], flavor.path, part, keep, progress=report,
                                            rename=rename)
                    else:  # the restore created this part: take it away again
                        old = flavor.path / f"{part}.replaced"
                        rename(flavor.path / part, old)
                        left = None
                        try:
                            remove_tree_no_follow(old)
                        except OSError as exc:
                            left = f"the restored copy could not be fully deleted: {old} ({exc})"
                except (SwapError, RestoreError, OSError) as exc:
                    outcome = PartOutcome(part, "failed", str(exc))
                else:
                    outcome = PartOutcome(part, "replaced_left" if left else "restored", left or "")
                result.parts.append(outcome)
                _log_part(flavor, outcome, undo=True)
    except Exception as exc:
        raise RestoreStopped(f"{type(exc).__name__}: {exc}", result) from exc
    done = sum(p.kind in ("restored", "replaced_left") for p in result.parts)
    mark_undone(journal_path, done, len(result.parts) - done)
    log_event("ibackup.undo_completed", flavor=folder, restored=done, failed=len(result.parts) - done)
    return result
```
(`_log_part` is shared from `restore.py`; rename it to `log_part` (public) in both files if Ruff flags the
private import.)

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup` → PASS; then the full suite
  `python3 scripts/run_tests.py` → PASS; `ruff check .` → clean.
- [ ] **Step 5: Commit** — `feat(interface-backup): undo a restore from its safety backup`
- [ ] **Milestone 1:** update the ledger, commit, `git push -u origin feat/interface-backup`.

---

## Milestone 2: TUI (Tasks 8–10), push after Task 10

### Task 8: report helpers (UI-free text)

**Files:**
- Create: `wowtools/tools/interface_backup/report.py`
- Test: `tests/test_interface_backup_report.py`

**Interfaces:**
- Consumes: `FlavorScan` (3), `BackupOutcome` (4), `RestorePlan`, `RestoreResult` (5–6), `BackupInfo` (2),
  `core.journal.Journal`, `friendly_stamp`.
- Produces: `human_size(n: int | None) -> str`; `plural(n, word) -> str`; `STAGE_TITLES: dict[str, str]`;
  `SUMMARY_COLUMNS`, `summary_rows(scans, backups: dict[str, list[BackupInfo]]) -> list[tuple[str, ...]]`;
  `notices(scans) -> list[str]`; `picker_note(backups: list[BackupInfo]) -> str`;
  `backup_confirm(scans, root, keep, running, free) -> tuple[str, str, tuple[str, ...]]`;
  `BACKUP_RESULT_COLUMNS`, `backup_result_rows(outcomes) -> list[tuple[str, ...]]`;
  `LIST_COLUMNS`, `list_rows(infos) -> list[tuple[str, ...]]`;
  `group_paths(items: list[tuple[str, str]], depth=3) -> list[tuple[str, int]]` (largest first, then name);
  `restore_warnings(plan, limit=15) -> list[str]`;
  `restore_confirm(plan, when: str, running) -> tuple[str, str, tuple[str, ...]]`;
  `RESTORE_RESULT_COLUMNS`, `restore_result_rows(result) -> list[tuple[str, ...]]`;
  `undo_confirm(journal) -> tuple[str, str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_interface_backup_report.py
from __future__ import annotations

import unittest
from pathlib import Path

from wowtools.core.install import Flavor
from wowtools.tools.interface_backup import report
from wowtools.tools.interface_backup.backup import BackupOutcome
from wowtools.tools.interface_backup.restore import BackupContents, PartOutcome, RestorePlan, RestoreResult
from wowtools.tools.interface_backup.scanner import FileInfo, FlavorScan, PartScan

RETAIL = Flavor("_retail_", Path("/wow/_retail_"))


def scan(sizes=True) -> FlavorScan:
    size = 100 if sizes else None
    parts = {"Interface": PartScan("Interface", RETAIL.path / "Interface", True, False,
                                   [FileInfo("AddOns/A/a.lua", size, 1.0)], ["AddOns/Dev"]),
             "WTF": PartScan("WTF", RETAIL.path / "WTF")}
    return FlavorScan(RETAIL, parts, [RETAIL.path / "WTF.replaced"])


def plan(removed=(), newer=(), kept=(), dropped=(), free=None) -> RestorePlan:
    contents = BackupContents(Path("/bk/backup-retail-20261004-153012.zip"), "backup", "retail", "_retail_", "",
                              ("Interface", "WTF"), {"Interface": {}, "WTF": {}})
    return RestorePlan(contents, RETAIL, ("Interface",), list(removed), list(newer), list(kept), list(dropped),
                       1000, free, [])


class ReportTest(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(report.human_size(None), "—")
        self.assertEqual(report.human_size(512), "512 B")
        self.assertEqual(report.human_size(1536), "1.5 KB")
        self.assertEqual(report.human_size(3 * 1024 ** 3), "3.0 GB")

    def test_summary_rows_and_notices(self):
        rows = report.summary_rows([scan()], {"retail": []})
        self.assertEqual(rows[0][0], "Retail")
        self.assertIn("1 file", rows[0][1])
        self.assertEqual(rows[0][2], "—")
        self.assertIn("100 B", rows[0][1])
        self.assertIn("1 file", report.summary_rows([scan(False)], {})[0][1])
        self.assertTrue(any("WTF.replaced" in n for n in report.notices([scan()])))

    def test_group_paths(self):
        items = [("Interface", "AddOns/WeakAuras/a.lua"), ("Interface", "AddOns/WeakAuras/b/c.lua"),
                 ("WTF", "Account/ME/x.lua"), ("WTF", "Config.wtf")]
        self.assertEqual(report.group_paths(items), [("Interface/AddOns/WeakAuras", 2), ("WTF/Account/ME", 1),
                                                     ("WTF/Config.wtf", 1)])

    def test_restore_warnings(self):
        many = [("Interface", f"AddOns/A{i}/x.lua") for i in range(20)]
        lines = report.restore_warnings(plan(removed=many, newer=[("Interface", "AddOns/B/y.lua")],
                                             dropped=[("Interface", "AddOns/Dev")], free=10), limit=15)
        text = "\n".join(lines)
        self.assertIn("Will be removed: 20 files", text)
        self.assertIn("and 5 more", text)
        self.assertIn("newer", text)
        self.assertIn("AddOns/Dev", text)
        self.assertIn("space", text.lower())
        self.assertEqual(report.restore_warnings(plan()), [])

    def test_confirms(self):
        title, body, alerts = report.restore_confirm(plan(removed=[("Interface", "AddOns/A/x.lua")]),
                                                     "2026-10-04 15:30:12", ["Wow.exe"])
        self.assertIn("Interface", title)
        self.assertTrue(any("Wow.exe" in a for a in alerts))
        title, body, alerts = report.backup_confirm([scan()], Path("/bk"), 0, None, None)
        self.assertIn("never", body)

    def test_result_rows(self):
        out = BackupOutcome(RETAIL, "created", Path("/bk/backup-retail-x.zip"), 3, 300, 100)
        self.assertEqual(report.backup_result_rows([out])[0][1], "Backed up")
        result = RestoreResult(RETAIL, Path("/bk/x.zip"), [PartOutcome("WTF", "rolled_back", "locked")])
        self.assertEqual(report.restore_result_rows(result)[0][:2], ("WTF", "Left as it was"))
```

- [ ] **Step 2: Run** — `python3 scripts/run_tests.py -k interface_backup_report` → FAIL.

- [ ] **Step 3: Implement** `report.py`:

```python
"""Labels, sizes, table rows and dialog texts for Interface Backup's screens (UI-free text helpers)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from wowtools.core.journal import Journal, friendly_stamp
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.backup import BackupOutcome
from wowtools.tools.interface_backup.catalog import BackupInfo
from wowtools.tools.interface_backup.restore import RestorePlan, RestoreResult
from wowtools.tools.interface_backup.scanner import FlavorScan, PartScan

STAGE_TITLES = {
    "scan": "Scanning", "backup": "Zipping", "verify": "Verifying the zip", "prune": "Removing old backups",
    "safety": "Safety backup of the current folders", "safety_verify": "Verifying the safety backup",
    "extract": "Unpacking the backup", "swap": "Swapping folders", "cleanup": "Deleting the replaced copy",
}
SUMMARY_COLUMNS = ("Flavor", "Interface", "WTF", "Links", "Backups", "Newest backup")
BACKUP_RESULT_COLUMNS = ("Flavor", "Outcome", "Zip", "Files", "Size", "Zip size", "Old backups removed")
LIST_COLUMNS = ("Date", "Flavor", "Kind", "Size")
RESTORE_RESULT_COLUMNS = ("Part", "Outcome", "Details")
_BACKUP_KINDS = {"created": "Backed up", "skipped": "Skipped", "failed": "Failed"}
_PART_KINDS = {"restored": "Restored", "replaced_left": "Restored (old copy left)", "rolled_back": "Left as it was",
               "failed": "Failed"}


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def human_size(n: int | None) -> str:
    if n is None:
        return "—"
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{n} B"


def _part_cell(part: PartScan) -> str:
    if not part.exists:
        return "link (skipped)" if part.linked else "—"
    size = part.size
    return plural(len(part.files), "file") + ("" if size is None else f", {human_size(size)}")


def summary_rows(scans: list[FlavorScan], backups: dict[str, list[BackupInfo]]) -> list[tuple[str, ...]]:
    rows = []
    for scan in scans:
        mine = [b for b in backups.get(scan.flavor.short_name, []) if not b.is_safety]
        rows.append((scan.flavor.display_name, _part_cell(scan.parts["Interface"]), _part_cell(scan.parts["WTF"]),
                     str(scan.link_count) if scan.link_count else "—", str(len(mine)),
                     mine[0].when if mine else "none yet"))
    return rows


def notices(scans: list[FlavorScan]) -> list[str]:
    lines = []
    for scan in scans:
        name = scan.flavor.display_name
        for path in scan.leftovers:
            lines.append(f"{name}: {to_stored(path)} is left from an interrupted restore. Restore is blocked for "
                         "this flavor until you move or delete it (see the guide).")
        for part in scan.parts.values():
            lines += [f"{name}: {error}" for error in part.errors[:3]]
        if scan.link_count:
            lines.append(f"{name}: {plural(scan.link_count, 'link')} (e.g. addon folders linked to a repo) are not "
                         "backed up; a restore keeps them.")
    return lines


def picker_note(backups: list[BackupInfo]) -> str:
    mine = [b for b in backups if not b.is_safety]
    return f"{plural(len(mine), 'backup')}, last {mine[0].when[:16]}" if mine else "no backups yet"


def backup_confirm(scans: list[FlavorScan], root: Path, keep: int, running: list[str] | None,
                   free: int | None) -> tuple[str, str, tuple[str, ...]]:
    files = sum(s.file_count for s in scans if s.has_data)
    sizes = [s.size for s in scans if s.has_data]
    total = None if any(x is None for x in sizes) else sum(sizes)  # type: ignore[misc]
    lines = [f"{plural(files, 'file')}" + ("" if total is None else f" ({human_size(total)})") + " from "
             + ", ".join(s.flavor.display_name for s in scans if s.has_data) + ".",
             f"Zips go to: {to_stored(root)}",
             "Older backups are never deleted." if keep == 0 else
             f"The newest {keep} backups of each flavor are kept; older ones are deleted."]
    alerts = []
    if running:
        alerts.append(f"WoW appears to be running ({', '.join(running)}). It rewrites WTF when you log out, so this "
                      "backup may miss your latest settings.")
    if total is not None and free is not None and total > free:
        alerts.append(f"The backup drive may be short of space: {human_size(free)} free, up to {human_size(total)} "
                      "needed.")
    title = f"Back up {plural(sum(s.has_data for s in scans), 'flavor')}?"
    return title, "\n".join(lines), tuple(alerts)


def backup_result_rows(outcomes: list[BackupOutcome]) -> list[tuple[str, ...]]:
    rows = []
    for o in outcomes:
        detail = o.path.name if o.path else o.reason
        rows.append((o.flavor.display_name, _BACKUP_KINDS.get(o.kind, o.kind), detail,
                     str(o.files) if o.kind == "created" else "", human_size(o.bytes_in) if o.kind == "created" else "",
                     human_size(o.bytes_zip) if o.kind == "created" else "", str(len(o.pruned)) if o.pruned else ""))
    return rows


def list_rows(infos: list[BackupInfo]) -> list[tuple[str, ...]]:
    return [(b.when, b.flavor_short, "safety (pre-restore)" if b.is_safety else "backup", human_size(b.size))
            for b in infos]


def group_paths(items: list[tuple[str, str]], depth: int = 3) -> list[tuple[str, int]]:
    """Group (part, rel) paths by their first `depth` path parts, e.g. Interface/AddOns/WeakAuras."""
    counts = Counter("/".join([part, *rel.split("/")][:depth]) for part, rel in items)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _grouped(title: str, items: list[tuple[str, str]], limit: int) -> list[str]:
    groups = group_paths(items)
    lines = [f"{title}: {plural(len(items), 'file')}"]
    lines += [f"  {name} ({plural(count, 'file')})" for name, count in groups[:limit]]
    if len(groups) > limit:
        lines.append(f"  … and {len(groups) - limit} more")
    return lines


def restore_warnings(plan: RestorePlan, limit: int = 15) -> list[str]:
    lines: list[str] = []
    if plan.removed:
        lines += _grouped("Will be removed", plan.removed, limit)
    if plan.newer:
        lines += _grouped("Newer now than in the backup (these changes are lost)", plan.newer, limit)
    if plan.links_removed:
        lines.append("Links replaced by the backup's files (only the link goes, never what it points at): "
                     + ", ".join(f"{p}/{r}" for p, r in plan.links_removed[:limit]))
    if plan.low_space:
        lines.append(f"Low disk space: {human_size(plan.free_bytes)} free on the WoW drive, about "
                     f"{human_size(plan.bytes_needed)} needed.")
    return lines


def restore_confirm(plan: RestorePlan, when: str, running: list[str] | None) -> tuple[str, str, tuple[str, ...]]:
    parts = " and ".join(plan.parts)
    title = f"Replace {parts} of {plan.flavor.display_name} with the backup from {when}?"
    body = ("The folders become exactly what the backup holds. A safety backup of the current folders is taken "
            "first, so Undo last restore (z) can put them back.")
    if plan.links_kept:
        body += f"\n{plural(len(plan.links_kept), 'link')} are kept as they are."
    alerts = list(restore_warnings(plan))
    if running:
        alerts.append(f"WoW appears to be running ({', '.join(running)}). Close it first: it rewrites WTF when you "
                      "log out, and an open game can lock Interface files.")
    return title, body, tuple(alerts)


def restore_result_rows(result: RestoreResult) -> list[tuple[str, ...]]:
    return [(p.part, _PART_KINDS.get(p.kind, p.kind), p.reason) for p in result.parts]


def undo_confirm(journal: Journal) -> tuple[str, str]:
    parts = [e["part"] for e in journal.entries if e.get("action") == "replaced"]
    flavor = str(journal.header.get("flavor", "?"))
    title = f"Undo the restore from {friendly_stamp(journal.started)}?"
    body = (f"Put {' and '.join(parts)} of {flavor} back as they were before that restore, from its safety backup. "
            "Anything changed since the restore is lost.")
    return title, body
```
(The display name for `_retail_` comes from `Flavor.display_name`; check it is "Retail" and adjust the test if
the suite names it differently.)

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup` → PASS.
- [ ] **Step 5: Commit** — `feat(interface-backup): report helpers`

---

### Task 9: tool flow, settings screen, summary/backup screens, registration

**Files:**
- Create: `wowtools/tools/interface_backup/app.py`, `wowtools/tools/interface_backup/summary_screen.py`
- Modify: `wowtools/tools/__init__.py` (third `Tool`), `README.md` (tools-table row + "Tool guides" link + config
  file line, so `tests/test_docs.py` passes), create a first `docs/interface-backup.md` (completed in Task 11)
- Test: `tests/test_interface_backup_app.py`

**Interfaces:**
- Consumes: everything above; `ToolFlow`, `FlavorScreen`/`ALL_FLAVORS`, `ConfirmScreen`, `ProgressScreen`,
  `NAV_BINDINGS`, `ButtonRow`, `action_button`, `NavHint`, `BrandBar`, `core.process.wow_check_for`,
  `core.activity.running`, `theme_colour`.
- Produces: `InterfaceBackupFlow` (`FLOW`), `BackupSettingsScreen(tool_cfg, install, *, source)`;
  `BackupSummaryScreen(cfg, tool_cfg, flavors, scope_label, *, wow_check=None, disk_usage=shutil.disk_usage)`
  dismissing with `"flavors" | "tools" | "quit"`; `BackupProgressScreen(ProgressScreen)` (`ID_PREFIX="ibackup"`,
  `STAGE_TITLES=report.STAGE_TITLES`); `BackupResultScreen(outcomes)` dismissing with `"review" | "restore" |
  "flavors" | "tools" | "quit"`. Task 10 adds the restore methods to `BackupSummaryScreen`.

Registration (`wowtools/tools/__init__.py`, third entry):
```python
    Tool("interface-backup", "Interface Backup",
         "Zip a flavor's Interface and WTF folders, and restore them.",
         "wowtools.tools.interface_backup.app", "interface_backup"),
```

- [ ] **Step 1: Write the failing TUI tests**

```python
# tests/test_interface_backup_app.py
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from textual.widgets import Button, DataTable, Input

from tests.fixtures import TuiTestCase, build_interface_tree, build_wow_tree, make_config, settle
from wowtools.core.config import Config
from wowtools.tools.interface_backup.app import BackupSettingsScreen
from wowtools.tools.interface_backup.settings import load_settings
from wowtools.tools.interface_backup.summary_screen import BackupResultScreen, BackupSummaryScreen
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp

SIZE = (140, 50)


class InterfaceBackupAppTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.tmp = Path(t.name)
        self.root = build_interface_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        self.bk = self.tmp / "bk"

    def save_tool_cfg(self, **values):
        tool_cfg = Config(self.config_dir / "interface-backup.cfg")
        for key, value in values.items():
            tool_cfg.set("interface_backup", key, value, log=False)
        tool_cfg.save()

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={"interface-backup": {"wow_check": lambda: []}})

    async def open_tool(self, app, pilot):
        await pilot.pause()
        self.assertIsInstance(app.screen, ToolMenuScreen)
        await pilot.press("down", "down", "enter")  # third tool in the menu
        await pilot.pause()

    async def open_summary(self, app, pilot):
        await self.open_tool(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")  # All flavors
        await settle(app, pilot)
        self.assertIsInstance(app.screen, BackupSummaryScreen)
        return app.screen

    async def test_first_open_asks_for_settings(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            self.assertIsInstance(app.screen, BackupSettingsScreen)
            app.screen.query_one("#backup_dir", Input).value = str(self.bk)
            app.screen.query_one("#keep_backups", Input).value = "0"
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            await settle(app, pilot)
        s = load_settings(Config(self.config_dir / "interface-backup.cfg").load())
        self.assertEqual((s.backup_dir, s.keep_backups), (self.bk, 0))

    async def test_settings_refuse_folder_inside_wtf(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            app.screen.query_one("#backup_dir", Input).value = str(self.root / "_retail_" / "WTF" / "bk")
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, BackupSettingsScreen)
            self.assertIn("WTF", app.screen.error_text)

    async def test_back_up_all_flavors(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            summary = await self.open_summary(app, pilot)
            table = summary.query_one("#flavors", DataTable)
            self.assertGreaterEqual(table.row_count, 3)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupResultScreen)
        zips = sorted(p.name for p in (self.bk / "interface-backup").glob("backup-*.zip"))
        self.assertTrue(any(n.startswith("backup-retail-") for n in zips))
        self.assertFalse(any(n.startswith("backup-ptr-") for n in zips))  # neither part: skipped
        with zipfile.ZipFile(self.bk / "interface-backup" / next(n for n in zips if "retail" in n)) as zf:
            self.assertIn("WTF/Config.wtf", zf.namelist())

    async def test_decline_confirm_writes_nothing(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)
        self.assertFalse((self.bk / "interface-backup").exists())

    async def test_tools_key_returns_to_menu(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)
```
(Check how `WowToolsApp` passes `tool_options` to a flow — read `wowtools/ui/suite_app.py` and how
`test_wtf_app.py` injects `wow_check` — and inject the WoW-running check the same way; the flow passes
`wow_check` on to `BackupSummaryScreen`. The tool's menu position is third: `down, down, enter`.)

- [ ] **Step 2: Run** — `python3 scripts/run_tests.py -k interface_backup_app` → FAIL.

- [ ] **Step 3: Implement** `app.py`, modelled line by line on `wowtools/tools/screenshot_organizer/app.py`:

```python
"""Interface Backup inside the suite app: (first run: settings) → flavor (or All flavors) → summary → back up or
restore."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.paths import to_native, to_stored
from wowtools.tools.interface_backup.catalog import list_backups
from wowtools.tools.interface_backup.report import picker_note
from wowtools.tools.interface_backup.settings import (SECTION, BackupSettings, load_settings, resolve_backup_root,
                                                      save_settings, validate_backup_dir)
from wowtools.tools.interface_backup.summary_screen import BackupSummaryScreen
from wowtools.ui.branding import BrandBar
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp

COUNTING = "checking…"


class BackupSettingsScreen(Screen[bool]):
    DEFAULT_CSS = """
    BackupSettingsScreen #settings { padding: 0 2; }
    BackupSettingsScreen .title { color: $accent; text-style: bold; margin: 1 0; }
    BackupSettingsScreen #settings-error { color: $error; height: auto; }
    BackupSettingsScreen .buttons { height: auto; margin-top: 1; }
    BackupSettingsScreen Button { margin-right: 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, tool_cfg: Config, install: WowInstall | None, *, source: str) -> None:
        super().__init__()
        self.tool_cfg = tool_cfg
        self.install = install
        self.source = source
        self.settings = load_settings(tool_cfg)
        self.error_text = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="settings", can_focus=False):
            yield Static("Interface Backup settings", classes="title")
            yield Label("Backup folder. Zips go to <backup folder>\\interface-backup\\backup-<flavor>-<date>.zip. "
                        "Leave it empty to use <WoW folder>\\wow-tools.")
            yield Input(to_stored(self.settings.backup_dir) if self.settings.backup_dir else "",
                        placeholder="Empty = <WoW folder>\\wow-tools", id="backup_dir")
            yield Label("Backups to keep per flavor (0 = never delete old backups)")
            yield Input(str(self.settings.keep_backups), type="integer", id="keep_backups")
            yield Label("Restore journals to keep (each names its safety backup; Undo uses the newest)")
            yield Input(str(self.settings.keep_journals), type="integer", id="keep_journals")
            yield Static("", id="settings-error")
            with ButtonRow(classes="buttons"):
                yield action_button("Save", "confirm", id="save")
                yield action_button("Cancel", "neutral", id="cancel")
            yield NavHint("↑↓/Tab move · ←→ buttons · Enter/Space press · Esc cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Interface Backup settings"
        self.query_one("#backup_dir", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _error(self, text: str) -> None:
        self.error_text = text
        self.query_one("#settings-error", Static).update(Text(text))

    def _int(self, widget_id: str) -> int | None:
        try:
            return int(self.query_one(f"#{widget_id}", Input).value)
        except ValueError:
            return None

    def _save(self) -> None:
        keep, journals = self._int("keep_backups"), self._int("keep_journals")
        if keep is None or keep < 0:
            self._error("Backups to keep must be 0 (never delete) or more.")
            return
        if journals is None or journals < 1:
            self._error("Keep at least 1 journal.")
            return
        raw = self.query_one("#backup_dir", Input).value.strip()
        folder = to_native(raw) if raw else None
        if self.install is not None:
            problem = validate_backup_dir(folder, self.install)
            if problem:
                self._error(problem)
                return
        save_settings(self.tool_cfg, BackupSettings(folder, keep, journals,
                                                    load_settings(self.tool_cfg).last_flavor_choice),
                      source=self.source)
        self.dismiss(True)


class InterfaceBackupFlow(ToolFlow):
    """Interface Backup's workflow. Its settings live in config/interface-backup.cfg; the WoW folder is shared."""

    def __init__(self, app: WowToolsApp, tool_cfg: Config, **options) -> None:
        super().__init__(app, tool_cfg)
        self.options = options  # tests inject wow_check / disk_usage
        self.flavors: list[Flavor] = []

    def start(self) -> None:
        self.require_install(self._ready)

    def _ready(self, install: WowInstall, first_run: bool) -> None:
        if not self.tool_cfg.exists:
            self.app.push_screen(BackupSettingsScreen(self.tool_cfg, install, source="wizard"),
                                 lambda _: self._pick_flavor())
        else:
            self._pick_flavor()

    def _pick_flavor(self) -> None:
        install = self.install()
        if install is None:
            self.start()
            return
        self.flavors = install.flavors()
        settings = load_settings(self.tool_cfg)
        picker = FlavorScreen(self.cfg, install, include_all=True, last=settings.last_flavor_choice,
                              flavors=self.flavors, note=lambda f: COUNTING, all_note=COUNTING)
        self.app.push_screen(picker, self._after_flavor)
        root = resolve_backup_root(settings, self.cfg.wow_path)
        picker.run_worker(lambda: self._notes_worker(picker, root), thread=True, group="notes")

    def _notes_worker(self, picker: FlavorScreen, root) -> None:
        backups = list_backups(root)  # never raises
        self.app.call_from_thread(self._notes_ready, picker, backups)

    def _notes_ready(self, picker: FlavorScreen, backups) -> None:
        if self.app.screen is not picker:
            return
        by_flavor = {f.short_name: [b for b in backups if b.flavor_short == f.short_name] for f in self.flavors}
        mine = [b for b in backups if not b.is_safety]
        picker.set_notes(lambda f: picker_note(by_flavor.get(f.short_name, [])),
                         picker_note(mine))

    def _after_flavor(self, choice: Flavor | str | None) -> None:
        if choice is None:
            self.close()
            return
        if choice == ALL_FLAVORS:
            chosen, label, stored = list(self.flavors), "All flavors", ""
        else:
            assert isinstance(choice, Flavor)
            chosen, label, stored = [choice], choice.display_name, choice.folder
        if self.tool_cfg.get(SECTION, "last_flavor_choice", "") != stored:
            self.tool_cfg.set(SECTION, "last_flavor_choice", stored)
            self.tool_cfg.save_if_exists()
        self.app.push_screen(BackupSummaryScreen(self.cfg, self.tool_cfg, chosen, label, **self.options),
                             self._after_summary)

    def _after_summary(self, choice: str | None) -> None:
        if choice == "flavors":
            self._pick_flavor()
        elif choice == "tools":
            self.close()
        else:
            self.app.exit()

    def open_settings(self) -> None:
        if isinstance(self.app.screen, BackupSettingsScreen):
            return
        self.app.open_general_settings(
            lambda _: self.app.push_screen(BackupSettingsScreen(self.tool_cfg, self.install(), source="settings"),
                                           self._settings_done))

    def _settings_done(self, saved: bool | None) -> None:
        if saved:
            self.app.notify("Settings saved. Press r on the summary to rescan with them.")


FLOW = InterfaceBackupFlow
```
(If `WowToolsApp` builds flows as `flow_cls(app, tool_cfg)` and hands `tool_options` some other way, follow that
mechanism instead of `**options`; keep the defaults working when no options are given.)

`summary_screen.py` — the summary, the backup run, its progress and result screens. Model the worker, busy flag,
progress and result handling on `ShotReviewScreen._run/_job_worker/_job_done` and the preflight on
`wtf_cleaner/review_screen.py` `_run_preflight/_preflight_worker/_preflight_done`:

```python
"""The summary of the chosen flavors (what Interface and WTF hold, existing backups) with Back up, Restore and
Undo, plus the progress and result screens of a backup."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, ProgressBar, Static

from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.process import wow_check_for
from wowtools.tools.interface_backup.backup import BackupOutcome, back_up_all
from wowtools.tools.interface_backup.catalog import list_backups
from wowtools.tools.interface_backup.journal import latest_undoable
from wowtools.tools.interface_backup.report import (BACKUP_RESULT_COLUMNS, STAGE_TITLES, SUMMARY_COLUMNS,
                                                    backup_confirm, backup_result_rows, notices, summary_rows)
from wowtools.tools.interface_backup.scanner import CHEAP_STATS, FlavorScan, scan_flavors
from wowtools.tools.interface_backup.settings import (load_settings, resolve_backup_root, resolve_journal_dir,
                                                      validate_backup_dir)
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import ConfirmScreen, ProgressScreen, theme_colour
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

NAV_HINT = ("↑↓/Tab move · ←→ buttons · Enter/Space press · b back up · e restore · z undo · r rescan · "
            "f flavors · t tools · q quit")


class BackupProgressScreen(ProgressScreen):
    ID_PREFIX = "ibackup"
    STAGE_TITLES = STAGE_TITLES

    def __init__(self, first_stage: str = "backup") -> None:
        super().__init__(first_stage=first_stage)


class BackupResultScreen(Screen[str]):
    DEFAULT_CSS = """
    BackupResultScreen #result { height: 1fr; padding: 1 2; }
    BackupResultScreen #result-table { height: 1fr; }
    BackupResultScreen .buttons { height: auto; padding: 0 2; }
    BackupResultScreen Button { margin-right: 2; }
    BackupResultScreen NavHint { padding: 0 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("r", "choose('review')", "Rescan"), Binding("e", "choose('restore')", "Restore"),
        Binding("f", "choose('flavors')", "Flavors"), Binding("t", "choose('tools')", "Tools"),
        Binding("q", "choose('quit')", "Quit"), Binding("escape", "choose('review')", "Back", show=False),
        *NAV_BINDINGS]

    def __init__(self, outcomes: list[BackupOutcome]) -> None:
        super().__init__()
        self.outcomes = outcomes

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="result"):
            yield Static(id="result-head")
            yield DataTable(id="result-table", cursor_type="row", zebra_stripes=True)
        with ButtonRow(classes="buttons"):
            yield action_button("Rescan (r)", "neutral", id="review")
            yield action_button("Restore (e)", "neutral", id="restore")
            yield action_button("Other flavor (f)", "neutral", id="flavors")
            yield action_button("Tools (t)", "neutral", id="tools")
            yield action_button("Quit (q)", "neutral", id="quit")
        yield NavHint("↑↓/Tab move · ←→ buttons · Enter/Space press · Esc back · r rescan · e restore · "
                      "f other flavor · t tools · q quit")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Interface Backup · result"
        made = sum(o.kind == "created" for o in self.outcomes)
        self.query_one("#result-head", Static).update(Text(f"{made} of {len(self.outcomes)} flavors backed up."))
        table = self.query_one("#result-table", DataTable)
        table.add_columns(*BACKUP_RESULT_COLUMNS)
        styles = {"created": "success", "failed": "error", "skipped": "warning"}
        for outcome, (flavor, kind, *rest) in zip(self.outcomes, backup_result_rows(self.outcomes)):
            style = f"bold {theme_colour(self.app, styles[outcome.kind])}" if outcome.kind in styles else ""
            table.add_row(Text(flavor), Text(kind, style=style), *(Text(c) for c in rest))
        self.query_one("#review", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "quit")

    def action_choose(self, choice: str) -> None:
        log_event("ui.selection", screen="ibackup_result", control="next", value=choice)
        self.dismiss(choice)


class BackupSummaryScreen(Screen[str]):
    DEFAULT_CSS = """
    BackupSummaryScreen #body { height: 1fr; padding: 1 2; }
    BackupSummaryScreen #scan-box { height: auto; }
    BackupSummaryScreen #scan-progress { width: 1fr; }
    BackupSummaryScreen #scan-label { color: $text-muted; }
    BackupSummaryScreen #flavors { height: auto; max-height: 14; margin: 1 0; }
    BackupSummaryScreen #details { height: auto; }
    BackupSummaryScreen #notices { height: auto; color: $warning; margin-top: 1; }
    BackupSummaryScreen #actions { height: auto; padding: 0 2; }
    BackupSummaryScreen #actions Button { min-width: 0; width: auto; margin-right: 1; }
    BackupSummaryScreen NavHint { padding: 0 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("b", "back_up", "Back up"), Binding("e", "restore", "Restore"),
        Binding("z", "undo", "Undo last restore"), Binding("r", "rescan", "Rescan"),
        Binding("f", "leave('flavors')", "Flavors"), Binding("t", "leave('tools')", "Tools"),
        Binding("q", "leave('quit')", "Quit"), Binding("escape", "leave('flavors')", "Flavors", show=False),
        *NAV_BINDINGS]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: list[Flavor], scope_label: str, *,
                 wow_check: Callable[[], list[str] | None] | None = None,
                 disk_usage: Callable = shutil.disk_usage) -> None:
        super().__init__()
        self.cfg = cfg
        self.tool_cfg = tool_cfg
        self.flavors = flavors
        self.scope_label = scope_label
        self.wow_check = wow_check
        self.disk_usage = disk_usage
        self.settings = load_settings(tool_cfg)
        self.scans: list[FlavorScan] | None = None
        self._scanning = False
        self._progress_screen: ProgressScreen | None = None

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield DataTable(id="flavors", cursor_type="row", zebra_stripes=True)
            yield Static("", id="details")
            yield Static("", id="notices")
        with ButtonRow(id="actions"):
            yield action_button("Back up (b)", "confirm", id="btn-backup")
            yield action_button("Restore (e)", "neutral", id="btn-restore")
            yield action_button("Undo last restore (z)", "revert", id="btn-undo")
            yield action_button("Rescan (r)", "neutral", id="btn-rescan")
            yield action_button("Flavors (f)", "neutral", id="btn-flavors")
            yield action_button("Tools (t)", "neutral", id="btn-tools")
        yield NavHint(NAV_HINT)
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"Interface Backup · {self.scope_label}"
        self.query_one("#flavors", DataTable).add_columns(*SUMMARY_COLUMNS)
        self.action_rescan()

    # --- paths ---------------------------------------------------------------------------------
    def _root(self) -> Path | None:
        return resolve_backup_root(self.settings, self.cfg.wow_path)

    def _journal_dir(self) -> Path | None:
        return resolve_journal_dir(self.cfg.wow_path)

    def _folder_problem(self) -> str | None:
        wow = self.cfg.wow_path
        if wow is None:
            return "No WoW folder is set."
        return validate_backup_dir(self.settings.backup_dir, WowInstall(wow))

    def _refresh_buttons(self) -> None:
        busy = self._scanning or self.app.busy
        has_data = bool(self.scans) and any(s.has_data for s in self.scans)
        self.query_one("#btn-backup", Button).disabled = busy or not has_data
        self.query_one("#btn-restore", Button).disabled = busy
        self.query_one("#btn-undo", Button).disabled = busy or latest_undoable(self._journal_dir()) is None
        self.query_one("#btn-rescan", Button).disabled = busy

    # --- scan ----------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if self._scanning or self.app.busy:
            return
        self.settings = load_settings(self.tool_cfg)
        self._scanning = True
        self.scans = None
        self.query_one("#scan-box").display = True
        self._refresh_buttons()
        self.run_worker(self._scan_worker, thread=True, exclusive=True, group="scan")

    def _scan_worker(self) -> None:
        def progress(stage: str, current: int, total: int, detail: str) -> None:
            self.app.call_from_thread(self._scan_progress, current, total, detail)

        try:
            scans = scan_flavors(self.flavors, with_stats=CHEAP_STATS, progress=progress)
            backups = list_backups(self._root())
        except Exception as exc:  # noqa: BLE001 - shown, never a crash
            log_exception("ibackup.ui", exc)
            self.app.call_from_thread(self._scan_failed, f"{type(exc).__name__}: {exc}")
            return
        self.app.call_from_thread(self._scanned, scans, backups)

    def _scan_progress(self, current: int, total: int, detail: str) -> None:
        if not self.is_attached:
            return
        self.query_one("#scan-progress", ProgressBar).update(total=total or None, progress=current)
        self.query_one("#scan-label", Static).update(Text(detail))

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        self.query_one("#scan-box").display = False
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, scans: list[FlavorScan], backups) -> None:
        self._scanning = False
        self.scans = scans
        self.query_one("#scan-box").display = False
        by_flavor: dict[str, list] = {}
        for info in backups:
            by_flavor.setdefault(info.flavor_short, []).append(info)
        table = self.query_one("#flavors", DataTable)
        table.clear()
        for row in summary_rows(scans, by_flavor):
            table.add_row(*(Text(c) for c in row))
        root = self._root()
        keep = self.settings.keep_backups
        self.query_one("#details", Static).update(Text(
            f"Backups go to: {root}\n"
            f"Keeping: {'all backups' if keep == 0 else f'the newest {keep} per flavor'}\n"
            f"Restore journals: {self._journal_dir()}"))
        self.query_one("#notices", Static).update(Text("\n".join(notices(scans))))
        self._refresh_buttons()

    # --- back up -------------------------------------------------------------------------------
    def action_back_up(self) -> None:
        if self.scans is None or self._scanning or self.app.busy:
            return
        log_event("ui.selection", screen="ibackup_summary", control="back_up", value=True)
        problem = self._folder_problem()
        if problem:
            self.notify(f"{problem} Fix the folder in settings (s).", title="Backup folder not allowed",
                        severity="error", timeout=15)
            return
        scans = [s for s in self.scans if s.has_data]
        if not scans:
            self.notify("Nothing to back up: no Interface or WTF folder.")
            return
        check = self.wow_check or wow_check_for([s.flavor for s in scans])
        self.run_preflight(check, lambda running: self._confirm_backup(scans, running))

    def run_preflight(self, check: Callable[[], list[str] | None],
                      then: Callable[[list[str] | None], None]) -> None:
        """The running-WoW check takes seconds on Windows: run it in a worker, then call then(running)."""
        self.app.busy = True
        self._refresh_buttons()
        self.query_one("#scan-label", Static).update(Text("Checking for running programs…"))

        def worker() -> None:
            running = None
            try:
                running = check()
            except Exception as exc:  # noqa: BLE001 - a failed check is "unknown"
                log_exception("preflight", exc)
            self.app.call_from_thread(self._preflight_done, running, then)

        self.run_worker(worker, thread=True, group="preflight")

    def _preflight_done(self, running: list[str] | None, then: Callable[[list[str] | None], None]) -> None:
        self.app.busy = False
        self._refresh_buttons()
        if not self.is_attached or self.app.screen is not self:
            return
        if running:
            log_event("wow.running_warning", executables=running)
        then(running)

    def _free(self, path: Path | None) -> int | None:
        while path is not None and not path.exists() and path.parent != path:
            path = path.parent
        try:
            return int(self.disk_usage(path).free) if path is not None else None
        except OSError:
            return None

    def _confirm_backup(self, scans: list[FlavorScan], running: list[str] | None) -> None:
        root = self._root()
        if root is None:
            return
        title, body, alerts = backup_confirm(scans, root, self.settings.keep_backups, running, self._free(root))
        self.app.push_screen(ConfirmScreen(title, body, alerts, default_yes=True),
                             lambda ok: self._backup_confirmed(ok, scans, root))

    def _backup_confirmed(self, ok: bool | None, scans: list[FlavorScan], root: Path) -> None:
        log_event("ui.selection", screen="confirm", control="back_up_confirm", value=bool(ok))
        if not ok:
            return
        keep = self.settings.keep_backups
        screen = BackupProgressScreen("backup")
        self.run_job(screen, lambda progress, on_flavor: back_up_all(scans, root, keep=keep, progress=progress,
                                                                     on_flavor=on_flavor),
                     self._backup_done)

    # --- running a job -------------------------------------------------------------------------
    def run_job(self, screen: ProgressScreen, job, done: Callable) -> None:
        """Run job(progress, on_flavor) in a worker behind the progress screen, then call done(result)."""
        self.app.busy = True
        self._refresh_buttons()
        self._progress_screen = screen
        self.app.push_screen(screen)

        def worker() -> None:
            def progress(*args) -> None:
                self.app.call_from_thread(screen.update_progress, *args)

            def on_flavor(label: str) -> None:
                self.app.call_from_thread(screen.set_flavor, label)

            try:
                with activity.running():
                    result = job(progress, on_flavor)
            except Exception as exc:  # noqa: BLE001 - shown by the UI
                self.app.call_from_thread(self._job_failed, exc)
                return
            self.app.call_from_thread(self._job_done, done, result)

        self.run_worker(worker, thread=True, exclusive=True, group="job")

    def _close_progress(self) -> None:
        screen, self._progress_screen = self._progress_screen, None
        if screen is not None and self.app.screen is screen:
            self.app.pop_screen()

    def _job_done(self, done: Callable, result) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_buttons()
        done(result)

    def _job_failed(self, exc: Exception) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_buttons()
        self.job_failed(exc)

    def job_failed(self, exc: Exception) -> None:
        """Overridden for restores in Task 10 (RestoreStopped shows its partial result)."""
        log_exception("ibackup.ui", exc)
        self.notify(f"{type(exc).__name__}: {exc}", title="Stopped", severity="error", timeout=20)

    def _backup_done(self, outcomes: list[BackupOutcome]) -> None:
        self.app.push_screen(BackupResultScreen(outcomes), self._after_result)

    def _after_result(self, choice: str | None) -> None:
        if choice in ("flavors", "tools", "quit"):
            self.dismiss(choice)
        elif choice == "restore":
            self.action_rescan()
            self.action_restore()
        else:
            self.action_rescan()

    # --- restore and undo (Task 10) ------------------------------------------------------------
    def action_restore(self) -> None:
        self.notify("Restore is not available yet.")

    def action_undo(self) -> None:
        self.notify("Nothing to undo.")

    # --- leaving -------------------------------------------------------------------------------
    def action_leave(self, choice: str) -> None:
        if not self.app.busy:
            self.dismiss(choice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {"btn-backup": self.action_back_up, "btn-restore": self.action_restore,
                   "btn-undo": self.action_undo, "btn-rescan": self.action_rescan,
                   "btn-flavors": lambda: self.action_leave("flavors"),
                   "btn-tools": lambda: self.action_leave("tools")}
        action = actions.get(event.button.id or "")
        if action is not None:
            event.stop()
            action()
```
(Check `action_button`'s valid styles in `wowtools/ui/widgets.py` — `"confirm"`, `"neutral"`, `"revert"` are
used elsewhere — and `theme_colour` names (`"success"`, `"error"`, `"warning"`). If `self.app.busy` is not a
plain attribute, use the same flag the organizer uses.)

README: add the tools-table row (copy the format of the two existing rows), a link `docs/interface-backup.md`
under "Tool guides", and `config/interface-backup.cfg` under "Your settings". Create `docs/interface-backup.md`
with a title, one-paragraph description and a "Settings" table (finished in Task 11).

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup -k docs -k structure -k suite_app` →
  PASS. Then the full suite `python3 scripts/run_tests.py` → PASS (other TUI tests that count menu entries may
  need their expected count raised by one).
- [ ] **Step 5: Commit** — `feat(interface-backup): tool flow, settings, summary and backup screens`

---

### Task 10: restore and undo screens

**Files:**
- Create: `wowtools/tools/interface_backup/restore_screen.py`
- Modify: `wowtools/tools/interface_backup/summary_screen.py` (replace the Task 9 restore/undo stubs)
- Test: `tests/test_interface_backup_app.py` (add restore/undo tests)

**Interfaces:**
- Consumes: Tasks 2–9.
- Produces: `BackupListScreen(root, flavors)` → dismisses with `BackupInfo | None`;
  `RestoreScreen(info: BackupInfo, flavor: Flavor, *, disk_usage=shutil.disk_usage)` → dismisses with
  `RestorePlan | None`; `RestoreResultScreen(result: RestoreResult)` → dismisses with `"undo" | "review" |
  "flavors" | "tools" | "quit"`.

- [ ] **Step 1: Write the failing tests** (append to `InterfaceBackupAppTest`; add imports
  `from textual.widgets import Checkbox, Static`, `from wowtools.tools.interface_backup.restore_screen import
  BackupListScreen, RestoreResultScreen, RestoreScreen`)

```python
    async def make_backup(self, app, pilot):
        await pilot.press("b")
        await settle(app, pilot)
        await pilot.press("y")
        await settle(app, pilot)
        self.assertIsInstance(app.screen, BackupResultScreen)

    async def test_restore_with_warnings_then_undo(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        retail = self.root / "_retail_"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            extra = retail / "Interface" / "AddOns" / "WeakAuras" / "wa.lua"
            extra.parent.mkdir(parents=True); extra.write_text("wa")
            await pilot.press("e")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupListScreen)
            table = app.screen.query_one("#backups", DataTable)
            retail_row = next(i for i in range(table.row_count)
                              if "retail" == str(table.get_row_at(i)[1]))
            table.move_cursor(row=retail_row)
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreScreen)
            self.assertIn("AddOns/WeakAuras", str(app.screen.query_one("#warnings", Static).render()))
            await pilot.press("o")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertFalse(app.screen.default_yes)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            self.assertFalse(extra.exists())
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            self.assertTrue(app.screen.result.undo)
        self.assertEqual(extra.read_text(), "wa")

    async def test_restore_wtf_only(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        retail = self.root / "_retail_"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            (retail / "Interface" / "keep.txt").write_text("k")
            (retail / "WTF" / "Config.wtf").write_bytes(b"mine")
            await pilot.press("e")
            await settle(app, pilot)
            table = app.screen.query_one("#backups", DataTable)
            table.move_cursor(row=next(i for i in range(table.row_count) if str(table.get_row_at(i)[1]) == "retail"))
            await pilot.press("enter")
            await settle(app, pilot)
            app.screen.query_one("#part-Interface", Checkbox).value = False
            await settle(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
        self.assertTrue((retail / "Interface" / "keep.txt").exists())
        self.assertEqual((retail / "WTF" / "Config.wtf").read_bytes(), b"SET a 1\n")

    async def test_restore_list_escape_returns_to_summary(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await pilot.press("e")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupListScreen)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)
```

- [ ] **Step 2: Run** — `python3 scripts/run_tests.py -k interface_backup_app` → FAIL.

- [ ] **Step 3: Implement** `restore_screen.py`:

```python
"""Pick a backup, choose what to restore and see what would be lost; the restore's result screen."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.catalog import BackupInfo, list_backups
from wowtools.tools.interface_backup.report import (LIST_COLUMNS, RESTORE_RESULT_COLUMNS, human_size, list_rows,
                                                    restore_result_rows, restore_warnings)
from wowtools.tools.interface_backup.restore import (BackupContents, RestoreError, RestorePlan, RestoreResult,
                                                     open_backup, plan_restore)
from wowtools.tools.interface_backup.scanner import PARTS, FlavorScan, scan_flavor
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import theme_colour
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button


class BackupListScreen(Screen[BackupInfo | None]):
    DEFAULT_CSS = """
    BackupListScreen #list { height: 1fr; padding: 1 2; }
    BackupListScreen #backups { height: 1fr; }
    BackupListScreen NavHint { padding: 0 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Back"), *NAV_BINDINGS]

    def __init__(self, root: Path | None, flavors: list[Flavor]) -> None:
        super().__init__()
        self.root = root
        self.flavors = flavors
        self.infos: list[BackupInfo] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="list"):
            yield Static(Text(f"Backups in {to_stored(self.root) if self.root else '?'}"), id="list-title")
            yield DataTable(id="backups", cursor_type="row", zebra_stripes=True)
        yield NavHint("↑↓ choose · Enter restore from this backup · Esc back")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Interface Backup · choose a backup"
        self.infos = list_backups(self.root, {f.short_name for f in self.flavors})
        table = self.query_one("#backups", DataTable)
        table.add_columns(*LIST_COLUMNS)
        for row in list_rows(self.infos):
            table.add_row(*(Text(c) for c in row))
        if not self.infos:
            self.query_one("#list-title", Static).update(Text("No backups yet for these flavors. Press Esc."))
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self.infos):
            info = self.infos[event.cursor_row]
            log_event("ui.selection", screen="ibackup_list", control="backup", value=info.path.name)
            self.dismiss(info)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RestoreScreen(Screen[RestorePlan | None]):
    DEFAULT_CSS = """
    RestoreScreen #restore { padding: 1 2; height: 1fr; }
    RestoreScreen .title { color: $accent; text-style: bold; }
    RestoreScreen #warnings { height: auto; margin-top: 1; }
    RestoreScreen .buttons { height: auto; padding: 0 2; }
    RestoreScreen Button { margin-right: 2; }
    RestoreScreen NavHint { padding: 0 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("o", "restore", "Restore"), Binding("escape", "cancel", "Back"),
                                         *NAV_BINDINGS]

    def __init__(self, info: BackupInfo, flavor: Flavor, *, disk_usage: Callable = shutil.disk_usage) -> None:
        super().__init__()
        self.info = info
        self.flavor = flavor
        self.disk_usage = disk_usage
        self.contents: BackupContents | None = None
        self.scan: FlavorScan | None = None
        self.plan: RestorePlan | None = None
        self.problem = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="restore"):
            yield Static(Text(f"{self.flavor.display_name}: backup from {self.info.when} "
                              f"({human_size(self.info.size)})"), classes="title")
            for part in PARTS:
                yield Ka0sCheckbox(f"Restore {part}", True, id=f"part-{part}", disabled=True)
            yield Static(Text("Comparing the backup with your folders…"), id="warnings")
        with ButtonRow(classes="buttons"):
            yield action_button("Restore (o)", "confirm", id="btn-restore", disabled=True)
            yield action_button("Back (Esc)", "neutral", id="btn-back")
        yield NavHint("↑↓/Tab move · Space tick · Enter/Space press · o restore · Esc back")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Interface Backup · restore"
        self.run_worker(self._load_worker, thread=True, group="restore-plan")

    def _load_worker(self) -> None:
        try:
            contents = open_backup(self.info.path)
            scan = scan_flavor(self.flavor, with_stats=True)
        except RestoreError as exc:
            self.app.call_from_thread(self._loaded, None, None, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - shown, never a crash
            log_exception("ibackup.ui", exc)
            self.app.call_from_thread(self._loaded, None, None, f"{type(exc).__name__}: {exc}")
            return
        self.app.call_from_thread(self._loaded, contents, scan, "")

    def _loaded(self, contents: BackupContents | None, scan: FlavorScan | None, problem: str) -> None:
        self.contents, self.scan, self.problem = contents, scan, problem
        if contents is not None and contents.flavor_folder != self.flavor.folder:
            self.problem = f"This backup belongs to {contents.flavor_folder}, not {self.flavor.folder}."
        if scan is not None and scan.leftovers:
            self.problem = ("A folder from an interrupted restore is still there: "
                            + ", ".join(to_stored(p) for p in scan.leftovers)
                            + ". Move or delete it first (see the guide).")
        for part in PARTS:
            box = self.query_one(f"#part-{part}", Ka0sCheckbox)
            available = (contents is not None and part in contents.parts and scan is not None
                         and not scan.parts[part].linked)
            box.disabled = not available or bool(self.problem)
            if not available:
                box.value = False
        self._replan()

    def on_checkbox_changed(self, event) -> None:
        self._replan()

    def _chosen(self) -> tuple[str, ...]:
        return tuple(p for p in PARTS if self.query_one(f"#part-{p}", Ka0sCheckbox).value
                     and not self.query_one(f"#part-{p}", Ka0sCheckbox).disabled)

    def _replan(self) -> None:
        warnings = self.query_one("#warnings", Static)
        button = self.query_one("#btn-restore", Button)
        self.plan = None
        if self.problem:
            warnings.update(Text(self.problem, style=f"bold {theme_colour(self.app, 'error')}"))
            button.disabled = True
            return
        if self.contents is None or self.scan is None:
            return
        parts = self._chosen()
        if not parts:
            warnings.update(Text("Tick Interface, WTF or both."))
            button.disabled = True
            return
        try:
            self.plan = plan_restore(self.contents, self.scan, parts, disk_usage=self.disk_usage)
        except RestoreError as exc:
            warnings.update(Text(str(exc), style=f"bold {theme_colour(self.app, 'error')}"))
            button.disabled = True
            return
        lines = restore_warnings(self.plan)
        text = "\n".join(lines) if lines else "Nothing on disk would be lost: your folders hold nothing the backup lacks."
        if self.plan.links_kept:
            text += f"\nLinks kept as they are: {len(self.plan.links_kept)}"
        warnings.update(Text(text, style=f"{theme_colour(self.app, 'warning')}" if lines else ""))
        button.disabled = False

    def action_restore(self) -> None:
        if self.plan is not None and not self.query_one("#btn-restore", Button).disabled:
            log_event("ui.selection", screen="ibackup_restore", control="restore", value=list(self.plan.parts))
            self.dismiss(self.plan)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-restore":
            self.action_restore()
        else:
            self.action_cancel()


class RestoreResultScreen(Screen[str]):
    DEFAULT_CSS = """
    RestoreResultScreen #result { height: 1fr; padding: 1 2; }
    RestoreResultScreen #result-table { height: auto; }
    RestoreResultScreen .buttons { height: auto; padding: 0 2; }
    RestoreResultScreen Button { margin-right: 2; }
    RestoreResultScreen NavHint { padding: 0 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("z", "choose('undo')", "Undo"), Binding("r", "choose('review')", "Rescan"),
        Binding("f", "choose('flavors')", "Flavors"), Binding("t", "choose('tools')", "Tools"),
        Binding("q", "choose('quit')", "Quit"), Binding("escape", "choose('review')", "Back", show=False),
        *NAV_BINDINGS]

    def __init__(self, result: RestoreResult) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="result"):
            yield Static(id="result-head")
            yield DataTable(id="result-table", cursor_type="row", zebra_stripes=True)
        with ButtonRow(classes="buttons"):
            if not self.result.undo:
                yield action_button("Undo (z)", "revert", id="undo")
            yield action_button("Rescan (r)", "neutral", id="review")
            yield action_button("Other flavor (f)", "neutral", id="flavors")
            yield action_button("Tools (t)", "neutral", id="tools")
            yield action_button("Quit (q)", "neutral", id="quit")
        yield NavHint("←→ buttons · Enter/Space press · z undo · r rescan · f other flavor · t tools · q quit")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        r = self.result
        self.sub_title = "Interface Backup · undo result" if r.undo else "Interface Backup · restore result"
        head = [f"{r.flavor.display_name}: " + ("undo finished." if r.undo else "restore finished.")]
        if r.safety_zip is not None:
            head.append(f"Safety backup of the folders as they were: {to_stored(r.safety_zip)}")
        if r.journal_path is not None:
            head.append(f"Journal: {to_stored(r.journal_path)}")
        self.query_one("#result-head", Static).update(Text("\n".join(head)))
        table = self.query_one("#result-table", DataTable)
        table.add_columns(*RESTORE_RESULT_COLUMNS)
        styles = {"restored": "success", "replaced_left": "warning", "rolled_back": "warning", "failed": "error"}
        for outcome, (part, kind, reason) in zip(r.parts, restore_result_rows(r)):
            table.add_row(Text(part), Text(kind, style=f"bold {theme_colour(self.app, styles.get(outcome.kind, 'warning'))}"),
                          Text(reason))
        self.query_one("#review", Button).focus()

    def action_choose(self, choice: str) -> None:
        if choice == "undo" and self.result.undo:
            return
        log_event("ui.selection", screen="ibackup_restore_result", control="next", value=choice)
        self.dismiss(choice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "quit")
```

In `summary_screen.py` replace the two stubs and override `job_failed` (add imports `from wowtools.core.install
import Flavor` (already), `from wowtools.tools.interface_backup.journal import read_restore_journal`,
`from wowtools.tools.interface_backup.report import restore_confirm, undo_confirm`,
`from wowtools.tools.interface_backup.restore import RestoreError, RestorePlan, RestoreResult, RestoreStopped,
restore`, `from wowtools.tools.interface_backup.undo import undo_restore`,
`from wowtools.tools.interface_backup.restore_screen import BackupListScreen, RestoreResultScreen, RestoreScreen`):

```python
    # --- restore -------------------------------------------------------------------------------
    def action_restore(self) -> None:
        if self._scanning or self.app.busy:
            return
        log_event("ui.selection", screen="ibackup_summary", control="restore", value=True)
        self.app.push_screen(BackupListScreen(self._root(), self.flavors), self._backup_chosen)

    def _backup_chosen(self, info) -> None:
        if info is None:
            return
        flavor = next((f for f in self.flavors if f.short_name == info.flavor_short), None)
        if flavor is None:
            self.notify(f"No flavor here matches {info.flavor_short}.", severity="error")
            return
        self.app.push_screen(RestoreScreen(info, flavor, disk_usage=self.disk_usage), self._restore_chosen)

    def _restore_chosen(self, plan: RestorePlan | None) -> None:
        if plan is None:
            return
        check = self.wow_check or wow_check_for([plan.flavor])
        self.run_preflight(check, lambda running: self._confirm_restore(plan, running))

    def _confirm_restore(self, plan: RestorePlan, running: list[str] | None) -> None:
        when = next((b.when for b in list_backups(self._root()) if b.path == plan.contents.path), "?")
        title, body, alerts = restore_confirm(plan, when, running)
        self.app.push_screen(ConfirmScreen(title, body, alerts, default_yes=False),
                             lambda ok: self._restore_confirmed(ok, plan))

    def _restore_confirmed(self, ok: bool | None, plan: RestorePlan) -> None:
        log_event("ui.selection", screen="confirm", control="restore_confirm", value=bool(ok))
        root, journal_dir = self._root(), self._journal_dir()
        if not ok or root is None or journal_dir is None:
            return
        keep = self.settings.keep_journals
        self.run_job(BackupProgressScreen("verify"),
                     lambda progress, _flavor: restore(plan, root=root, journal_dir=journal_dir,
                                                       keep_journals=keep, progress=progress),
                     self._restore_done)

    def _restore_done(self, result: RestoreResult) -> None:
        self.app.push_screen(RestoreResultScreen(result), self._after_restore_result)

    def _after_restore_result(self, choice: str | None) -> None:
        if choice == "undo":
            self.action_rescan()
            self.action_undo()
        else:
            self._after_result(choice)

    def job_failed(self, exc: Exception) -> None:
        if isinstance(exc, RestoreError):
            self.notify(str(exc), title="Not restored", severity="error", timeout=20)
        elif isinstance(exc, RestoreStopped):
            self.notify(f"{exc} Undo last restore (z) puts back what was replaced.", title="Restore stopped",
                        severity="error", timeout=20)
            self.app.push_screen(RestoreResultScreen(exc.result), self._after_restore_result)
        else:
            super().job_failed(exc)
        self.action_rescan()

    # --- undo ----------------------------------------------------------------------------------
    def action_undo(self) -> None:
        if self.app.busy:
            return
        log_event("ui.selection", screen="ibackup_summary", control="undo", value=True)
        path = latest_undoable(self._journal_dir())
        if path is None:
            self.notify("Nothing to undo.")
            return
        try:
            journal = read_restore_journal(path)
        except (OSError, ValueError) as exc:
            self.notify(f"The journal could not be read: {exc}", severity="error")
            return
        folder = str(journal.header.get("flavor", ""))
        check = self.wow_check or wow_check_for([folder])

        def confirm(running: list[str] | None) -> None:
            title, body = undo_confirm(journal)
            alerts = (f"WoW appears to be running ({', '.join(running)}). Close it first.",) if running else ()
            self.app.push_screen(ConfirmScreen(title, body, alerts, default_yes=False),
                                 lambda ok: self._undo_confirmed(ok, path))

        self.run_preflight(check, confirm)

    def _undo_confirmed(self, ok: bool | None, path: Path) -> None:
        log_event("ui.selection", screen="confirm", control="undo_confirm", value=bool(ok))
        wow, root = self.cfg.wow_path, self._root()
        if not ok or wow is None or root is None:
            return
        self.run_job(BackupProgressScreen("verify"),
                     lambda progress, _flavor: undo_restore(path, wow_root=wow, root=root, progress=progress),
                     self._restore_done)
```
(`action_rescan` is a no-op while `self.app.busy`; `_job_done` clears busy before calling `done`, so the rescan
after a result runs. `wow_check_for` accepts folder strings as well as `Flavor`s.)

- [ ] **Step 4: Run** — `python3 scripts/run_tests.py -k interface_backup` → PASS; full suite → PASS;
  `ruff check .` → clean.
- [ ] **Step 5: Commit** — `feat(interface-backup): restore and undo screens`
- [ ] **Milestone 2:** update the ledger, commit, `git push`.

---

## Milestone 3: docs and final verification (Task 11), push after Task 11

### Task 11: documentation, events, final checks

**Files:**
- Modify: `docs/interface-backup.md` (full guide), `README.md` (Version History line), `docs/architecture.md`,
  `docs/adding-a-tool.md` (mention the third tool only where a list of tools appears), `CLAUDE.md` (tool list),
  `docs/events.md` (regenerated)

- [ ] **Step 1: Regenerate events** — `python3 scripts/gen_event_docs.py`; check the `interface-backup` section
  lists all 21 events.
- [ ] **Step 2: Guide** — write `docs/interface-backup.md` in the style of `docs/screenshot-organizer.md` (read it
  first): what it does; where zips go (`<backup folder>\interface-backup\backup-<flavor>-<date>.zip`, default
  `<WoW folder>\wow-tools`); the screens (flavor picker notes, summary, back up, restore list, restore screen with
  warnings, result, Undo); settings table (`backup_dir`, `keep_backups` with 0 = never delete, `keep_journals`,
  `last_flavor_choice`); links (not backed up, kept on restore); safety backups (`pre-restore-*.zip`, kept with
  their journal); a FAQ and a Symptom/Fix table (WoW running, low space, "left from an interrupted restore" — how
  to fix by hand: if `<part>` exists, delete `<part>.restoring`/`<part>.replaced`; if `<part>` is missing, rename
  `<part>.replaced` back to `<part>`; "not an Interface Backup zip"; a part that is itself a link).
- [ ] **Step 3: README** — Version History line for the new tool (unreleased, no version bump); verify the
  tools-table row and the guide link from Task 9.
- [ ] **Step 4: architecture.md** — add `config/interface-backup.cfg` to the config schema; an "Interface Backup
  data flow" block (`scan_flavors → back_up_all → BackupOutcome`; `open_backup → plan_restore → restore →
  RestoreResult`; `undo_restore`), its screens, and the three new core helpers in the core-modules table
  (`fsutil.is_link`/`remove_tree_no_follow`, `backup.walk_files`).
- [ ] **Step 5: CLAUDE.md** — the first line's tool list gains `Interface Backup (interface-backup, package
  tools/interface_backup)`.
- [ ] **Step 6: Verify everything** — `python3 scripts/run_tests.py` (all pass), `ruff check .` (clean),
  `python3 -m unittest discover -s tests -t . -v 2>&1 | tail -3` (OK). Launch the app once to see it:
  `./wow-tools.sh` is interactive, so use the TUI tests as the end-to-end check and say so in the report.
- [ ] **Step 7: Commit** — `docs(interface-backup): guide, README, architecture, events`; update the ledger;
  `git push`. Report to the user and ask for the merge go-ahead (merge and release are separate approvals).
