# Screenshot Organizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the suite's second tool, the Screenshot Organizer. It files `<WoW>/<flavor>/Screenshots/WoWScrnShot_MMDDYY_HHMMSS.*` into `YYYY/MM/DD` folders, either in place or under an archive root (`<dest>/<flavor folder>/YYYY/MM/DD`), with a review screen, dry run, copy mode, a run journal and undo.

**Architecture:** UI-free logic modules in `wowtools/tools/screenshot_organizer/` (`naming`, `settings`, `planner`, `organizer`, `journal`, `undo`, `report`, `events`) and a thin Textual front end (`app.py`, `review_screen.py`) that runs as a `ToolFlow` inside `WowToolsApp`. The shared `FlavorScreen` gains an opt-in "All flavors" entry.

**Tech Stack:** Python ≥ 3.10, stdlib plus vendored Textual/Rich, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-03-screenshot-organizer-design.md`

## Global Constraints

- `from __future__ import annotations` in every module. Stdlib plus `vendor/` only. Python 3.10 floor.
- Only `app.py` and `review_screen.py` in the tool import `textual`. Logic modules never do.
- Paths saved in config or a journal go through `core/paths.to_stored()`, and are read back with `to_native()`.
- Every event is registered with a fixed level in `wowtools/tools/screenshot_organizer/events.py`. **Event names are global across tools** (`core/events.REGISTRY`), so every screenshot event starts with `shots.`. Run `python3 scripts/gen_event_docs.py` after changing the registry.
- No per-file `Path.resolve()`. No per-file `stat()` beyond what one `os.scandir` per folder gives. The user runs on WSL over drvfs, where each call costs about 13ms.
- Nothing is ever overwritten. Only `YYYY`/`MM`/`DD` folders and screenshot files that the tool filed are created or removed in the destination.
- Tests use temp trees (`tests/fixtures.py`), never a real install or the network. Textual tests subclass `tests.fixtures.TuiTestCase`.
- Tests: `python3 scripts/run_tests.py` (full, about 10s); `python3 -m unittest tests.test_x -v` for one module.
- Commit after every task, on branch `feat/screenshot-organizer`, ending messages with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UcpDPMuktyHqM8xWGFXb22
  ```
- Update `docs/superpowers/plans/2026-10-03-screenshot-organizer.status.md` (the ledger) after each task.

## Review Focus

1. **Archive on another drive** (`G:` to `H:`, which gives `EXDEV`): the file is copied, verified, renamed from `.partial`, and only then is the source deleted. The mtime is preserved, because photo managers sort by it. Pinned in Task 3 (`test_cross_device_move_verifies_and_keeps_mtime`).
2. **Re-running after an interrupted run**: a stale `<name>.partial` sits in a day folder and the journal has no `finished` line. The next run replaces the partial file, and Undo still works on the cut-short journal. Pinned in Task 3 (`test_stale_partial_is_replaced`) and Task 4 (`test_undo_of_journal_without_finished_line`).
3. **Shot already in the archive from the old script**: an identical file means the source is removed (or left alone in copy mode). A different file is a conflict, and both are left alone. Pinned in Task 3.
4. **Foreign files in the destination** (digiKam `*.db`, non-date folders): neither a run nor undo pruning ever touches them. Pinned in Task 3 and Task 4 (`test_undo_never_removes_foreign_or_nonempty_folders`).
5. **Undo after the settings changed** (`dest_dir` edited after a run): undo works from the journal's own paths, not the current settings. Pinned in Task 4 (`test_undo_ignores_current_settings`).

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `wowtools/tools/screenshot_organizer/__init__.py` | new | imports `events` |
| `wowtools/tools/screenshot_organizer/events.py` | new | `shots.*` registry |
| `wowtools/tools/screenshot_organizer/naming.py` | new | parse `WoWScrnShot_MMDDYY_HHMMSS.ext` |
| `wowtools/tools/screenshot_organizer/settings.py` | new | `[screenshot_organizer]` settings, folder rules, `validate_dest` |
| `wowtools/tools/screenshot_organizer/planner.py` | new | `scan()` gives `Plan` |
| `wowtools/tools/screenshot_organizer/journal.py` | new | journal format, writer, reader, list, prune |
| `wowtools/tools/screenshot_organizer/organizer.py` | new | `execute()` gives `OrganizeResult`; outcome kinds; file helpers |
| `wowtools/tools/screenshot_organizer/undo.py` | new | `undo()` gives `OrganizeResult` |
| `wowtools/tools/screenshot_organizer/report.py` | new | UI-free labels, summary and result rows |
| `wowtools/tools/screenshot_organizer/app.py` | new | `ScreenshotsFlow` (`FLOW`), `ScreenshotSettingsScreen` |
| `wowtools/tools/screenshot_organizer/review_screen.py` | new | `ShotReviewScreen`, `ShotProgressScreen`, `ShotResultScreen` |
| `wowtools/ui/flavor_screen.py` | modify | `include_all`, `last`, `flavors` params; `ALL_FLAVORS` |
| `wowtools/tools/__init__.py` | modify | register the tool |
| `tests/fixtures.py` | modify | `build_screenshot_tree()` |
| `tests/test_screenshot_organizer_*.py` | new | per module |
| `README.md`, `docs/architecture.md`, `docs/adding-a-tool.md`, `docs/events.md`, `CLAUDE.md`, the spec (§3, §8) | modify | docs |

Tasks 1 to 4 are the logic, in dependency order. Task 5 (`FlavorScreen`) is independent. Task 6 (UI) needs 1 to 5. Task 7 is docs.

---

### Task 1: Package, events, naming, settings

**Files:**
- Create: `wowtools/tools/screenshot_organizer/__init__.py`, `events.py`, `naming.py`, `settings.py`
- Test: `tests/test_screenshot_organizer_naming.py`, `tests/test_screenshot_organizer_settings.py`

**Interfaces (produces):**
- `naming.parse_shot_name(name: str) -> datetime.date | None`
- `naming.day_parts(day: date) -> tuple[str, str, str]`, e.g. `("2019", "07", "31")`
- `settings.SECTION = "screenshot_organizer"`, `SCREENSHOTS_DIR = "Screenshots"`, `DEFAULT_KEEP_JOURNALS = 10`, `JOURNAL_SUBDIR = Path("wow-tools") / "screenshot-organizer" / "journal"`
- `settings.ShotSettings(dest_dir: Path | None = None, copy_mode: bool = False, last_flavor_choice: str = "", keep_journals: int = 10)`. In `last_flavor_choice`, `""` means all flavors; otherwise it holds a flavor folder.
- `settings.load_settings(cfg: Config) -> ShotSettings`, `save_settings(cfg, s, *, source="settings") -> None`
- `settings.source_dir(flavor: Flavor) -> Path` (`flavor.path / "Screenshots"`)
- `settings.target_root(flavor: Flavor, dest_dir: Path | None) -> Path` (`dest_dir / flavor.folder`, or `source_dir(flavor)` when `dest_dir` is None)
- `settings.resolve_journal_dir(wow_path: Path | None) -> Path | None`
- `settings.validate_dest(dest: Path | None, install: WowInstall) -> str | None` (an error message, or None if OK)

- [ ] **Step 1: Write the failing tests**

`tests/test_screenshot_organizer_naming.py`:
```python
import unittest
from datetime import date

from wowtools.tools.screenshot_organizer.naming import day_parts, parse_shot_name


class NamingTest(unittest.TestCase):
    def test_valid_names(self):
        self.assertEqual(parse_shot_name("WoWScrnShot_073119_232713.jpg"), date(2019, 7, 31))
        self.assertEqual(parse_shot_name("WoWScrnShot_010224_000001.tga"), date(2024, 1, 2))
        self.assertEqual(parse_shot_name("wowscrnshot_080119_101010.PNG"), date(2019, 8, 1))
        self.assertEqual(parse_shot_name("WoWScrnShot_123199_235959.jpeg"), date(2099, 12, 31))

    def test_invalid_names(self):
        for name in ("WoWScrnShot_023119_120000.jpg",   # 31 February
                     "WoWScrnShot_133119_120000.jpg",   # month 13
                     "WoWScrnShot_073119_232713.gif",
                     "WoWScrnShot_073119.jpg", "WoWScrnShot_07311_232713.jpg",
                     "copy of WoWScrnShot_073119_232713.jpg", "WoWScrnShot_073119_232713.jpg.bak",
                     "notes.txt", ""):
            self.assertIsNone(parse_shot_name(name), name)

    def test_day_parts(self):
        self.assertEqual(day_parts(date(2019, 7, 3)), ("2019", "07", "03"))
```

`tests/test_screenshot_organizer_settings.py`:
```python
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.config import Config
from wowtools.core.events import REGISTRY
from wowtools.core.install import WowInstall
from wowtools.tools.screenshot_organizer import events
from wowtools.tools.screenshot_organizer.settings import (DEFAULT_KEEP_JOURNALS, SECTION, ShotSettings, load_settings,
                                                 resolve_journal_dir, save_settings, source_dir, target_root,
                                                 validate_dest)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("retail")

    def test_defaults_and_round_trip(self):
        cfg = Config(self.tmp / "screenshot-organizer.cfg")
        self.assertEqual(load_settings(cfg), ShotSettings())
        save_settings(cfg, ShotSettings(self.tmp / "arch", True, "_retail_", 3))
        again = load_settings(Config(cfg.path).load())
        self.assertEqual(again, ShotSettings(self.tmp / "arch", True, "_retail_", 3))

    def test_bad_values_fall_back(self):
        cfg = Config(self.tmp / "screenshot-organizer.cfg")
        cfg.set(SECTION, "copy_mode", "maybe", log=False)
        cfg.set(SECTION, "keep_journals", "0", log=False)
        s = load_settings(cfg)
        self.assertFalse(s.copy_mode)
        self.assertEqual(s.keep_journals, 1)
        cfg.set(SECTION, "keep_journals", "x", log=False)
        self.assertEqual(load_settings(cfg).keep_journals, DEFAULT_KEEP_JOURNALS)

    def test_target_root(self):
        self.assertEqual(source_dir(self.retail), self.root / "_retail_" / "Screenshots")
        self.assertEqual(target_root(self.retail, None), self.root / "_retail_" / "Screenshots")
        self.assertEqual(target_root(self.retail, self.tmp / "arch"), self.tmp / "arch" / "_retail_")

    def test_journal_dir(self):
        self.assertIsNone(resolve_journal_dir(None))
        self.assertEqual(resolve_journal_dir(self.root), self.root / "wow-tools" / "screenshot-organizer" / "journal")

    def test_validate_dest(self):
        self.assertIsNone(validate_dest(None, self.install))
        self.assertIsNone(validate_dest(self.tmp / "arch", self.install))
        self.assertIsNotNone(validate_dest(self.root, self.install))
        self.assertIsNotNone(validate_dest(self.root / "_retail_" / "Screenshots", self.install))
        self.assertIsNotNone(validate_dest(self.root / "_retail_" / "Screenshots" / "x", self.install))

    def test_events_are_prefixed(self):
        self.assertTrue(events.EVENTS)
        for name in events.EVENTS:
            self.assertTrue(name.startswith("shots."), name)
            self.assertIs(REGISTRY[name], events.EVENTS[name])
```

- [ ] **Step 2: Run them; expect `ModuleNotFoundError`**

Run: `python3 -m unittest tests.test_screenshot_organizer_naming tests.test_screenshot_organizer_settings -v`

- [ ] **Step 3: Implement**

`wowtools/tools/screenshot_organizer/__init__.py`:
```python
"""Screenshot Organizer: file WoW screenshots into YYYY/MM/DD folders, per flavor."""
from wowtools.tools.screenshot_organizer import events as _events  # noqa: F401
```

`wowtools/tools/screenshot_organizer/events.py`:
```python
"""Events emitted by the Screenshot Organizer. Levels are fixed here; see docs/events.md.

Event names are global across tools, so every name here starts with `shots.`."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events

TOOL_NAME = "screenshot-organizer"

EVENTS: dict[str, EventSpec] = {
    "shots.scan_started": EventSpec("info", "A scan of the chosen flavors' Screenshots folders started."),
    "shots.scan_completed": EventSpec("info", "A scan finished: per flavor, files to file, possible duplicates, conflicts and unrecognised names."),
    "shots.scan_warning": EventSpec("warning", "A Screenshots or target folder could not be read during a scan."),
    "shots.organize_started": EventSpec("info", "A run (or dry run) started: mode, destination and file count."),
    "shots.moved": EventSpec("info", "A screenshot was moved into its date folder."),
    "shots.copied": EventSpec("info", "A screenshot was copied into its date folder (copy mode)."),
    "shots.would_file": EventSpec("info", "Dry run: a screenshot that would have been filed."),
    "shots.duplicate_removed": EventSpec("info", "The source was identical to the file already at the target and was removed."),
    "shots.already_filed": EventSpec("info", "Copy mode: an identical file was already at the target."),
    "shots.conflict": EventSpec("warning", "A different file with the same name is already at the target; both were left alone."),
    "shots.skipped": EventSpec("warning", "A screenshot was skipped because it vanished or changed after the scan."),
    "shots.source_left": EventSpec("warning", "A screenshot was copied across drives but the source could not be deleted."),
    "shots.refused": EventSpec("error", "The path guard refused a screenshot (its source or target is not where it should be)."),
    "shots.failed": EventSpec("error", "A screenshot could not be filed."),
    "shots.organize_completed": EventSpec("info", "A run finished, with totals (logged at warning if any file failed)."),
    "shots.organize_stopped": EventSpec("error", "A run stopped unexpectedly; the journal holds what was done so far."),
    "shots.journal_pruned": EventSpec("info", "Older run journals were deleted to keep the newest N (keep_journals)."),
    "shots.undo_started": EventSpec("info", "Undo of a run journal started."),
    "shots.undo_restored": EventSpec("info", "Undo put one screenshot back (or removed one copy)."),
    "shots.undo_skipped": EventSpec("warning", "Undo left an entry alone because it could not be reversed safely."),
    "shots.undo_failed": EventSpec("error", "Undo hit an error on one entry."),
    "shots.undo_completed": EventSpec("info", "Undo finished, with totals."),
}

register_events(TOOL_NAME, EVENTS)
```

`wowtools/tools/screenshot_organizer/naming.py`:
```python
"""WoW's screenshot file names: WoWScrnShot_MMDDYY_HHMMSS.<jpg|jpeg|png|tga>. The date comes from the name only."""
from __future__ import annotations

import re
from datetime import date

SHOT_RE = re.compile(r"^WoWScrnShot_(\d{2})(\d{2})(\d{2})_(\d{6})\.(?:jpe?g|png|tga)$", re.IGNORECASE)


def parse_shot_name(name: str) -> date | None:
    """The day a screenshot was taken, or None if the name is not a WoW screenshot name (or not a real date)."""
    match = SHOT_RE.match(name)
    if match is None:
        return None
    month, day, year = (int(match.group(i)) for i in (1, 2, 3))
    try:
        return date(2000 + year, month, day)
    except ValueError:
        return None


def day_parts(day: date) -> tuple[str, str, str]:
    """The YYYY, MM and DD folder names for a day."""
    return f"{day.year:04d}", f"{day.month:02d}", f"{day.day:02d}"
```

`wowtools/tools/screenshot_organizer/settings.py`:
```python
"""The Screenshot Organizer's own settings: the [screenshot_organizer] section of config/screenshot-organizer.cfg, plus where
things go (source folder, target root, journal folder)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall

SECTION = "screenshot_organizer"
SCREENSHOTS_DIR = "Screenshots"
DEFAULT_KEEP_JOURNALS = 10
JOURNAL_SUBDIR = Path("wow-tools") / "screenshot-organizer" / "journal"


@dataclass
class ShotSettings:
    dest_dir: Path | None = None  # None (stored as empty) means organise in place
    copy_mode: bool = False
    last_flavor_choice: str = ""  # "" means all flavors, else a flavor folder such as _retail_
    keep_journals: int = DEFAULT_KEEP_JOURNALS


def load_settings(cfg: Config) -> ShotSettings:
    return ShotSettings(cfg.get_path(SECTION, "dest_dir"), cfg.get_bool(SECTION, "copy_mode", False),
                        (cfg.get(SECTION, "last_flavor_choice") or "").strip(),
                        max(1, cfg.get_int(SECTION, "keep_journals", DEFAULT_KEEP_JOURNALS)))


def save_settings(cfg: Config, settings: ShotSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "dest_dir", settings.dest_dir, source=source)
    cfg.set(SECTION, "copy_mode", settings.copy_mode, source=source)
    cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.set(SECTION, "keep_journals", settings.keep_journals, source=source)
    cfg.save()


def source_dir(flavor: Flavor) -> Path:
    return flavor.path / SCREENSHOTS_DIR


def target_root(flavor: Flavor, dest_dir: Path | None) -> Path:
    """Where a flavor's YYYY/MM/DD folders go: <dest>/<flavor folder>, or in place in its Screenshots folder."""
    return dest_dir / flavor.folder if dest_dir is not None else source_dir(flavor)


def resolve_journal_dir(wow_path: Path | None) -> Path | None:
    """<WoW folder>/wow-tools/screenshot-organizer/journal: never inside the screenshot archive."""
    return wow_path / JOURNAL_SUBDIR if wow_path is not None else None


def _key(path: Path) -> str:
    return str(path.resolve()).casefold()  # a handful of paths, once, on the settings screen


def validate_dest(dest: Path | None, install: WowInstall) -> str | None:
    """Why a destination folder is not allowed, or None if it is fine (None itself means in place)."""
    if dest is None:
        return None
    key = _key(dest)
    if key == _key(install.root):
        return "The destination cannot be the WoW folder itself."
    for flavor in install.flavors():
        shots = _key(source_dir(flavor))
        if key == shots or key.startswith(shots.rstrip("/\\") + ("\\" if "\\" in shots else "/")):
            return (f"The destination cannot be inside {flavor.folder}\\Screenshots. "
                    "Leave it empty to organise in place.")
    return None
```

- [ ] **Step 4: Run the tests; expect PASS**

Run: `python3 -m unittest tests.test_screenshot_organizer_naming tests.test_screenshot_organizer_settings -v`

- [ ] **Step 5: Commit** with message `feat(screenshots): package, events, file-name parsing, settings`

---

### Task 2: Fixture and planner

**Files:**
- Modify: `tests/fixtures.py` (add `build_screenshot_tree`, `SHOT_BYTES`)
- Create: `wowtools/tools/screenshot_organizer/planner.py`
- Test: `tests/test_screenshot_organizer_planner.py`

**Interfaces:**
- Consumes: Task 1 (`parse_shot_name`, `day_parts`, `source_dir`, `target_root`).
- Produces:
  - `planner.NEW = "new"`, `MAYBE_DUPLICATE = "maybe_duplicate"`, `CONFLICT = "conflict"`
  - `ShotItem(flavor: Flavor, src: Path, dst: Path, day: date, size: int, mtime: float, state: str)` (frozen)
  - `Skipped(flavor: Flavor, path: Path, reason: str)` (frozen)
  - `FlavorPlan(flavor, source_dir: Path, target_root: Path, items: list[ShotItem], skipped: list[Skipped])` with properties `new`, `maybe_duplicates`, `conflicts` (lists of `ShotItem` by state) and `selectable` (items not in `CONFLICT`)
  - `Plan(flavors: list[FlavorPlan], dest_dir: Path | None, warnings: list[str])` with `items` (all `ShotItem`s), `selectable` and `skipped`
  - `scan(flavors: list[Flavor], dest_dir: Path | None, progress: Callable[[int, int, str], None] | None = None) -> Plan`
  - `tests.fixtures.build_screenshot_tree(root: Path) -> Path` and `SHOT_BYTES: dict[str, bytes]`

- [ ] **Step 1: Add the fixture** (append to `tests/fixtures.py`; extend the module docstring with the layout)

```python
SHOT_BYTES = {
    "WoWScrnShot_073119_232713.jpg": b"shot-a",
    "WoWScrnShot_073119_232800.jpg": b"shot-b",
    "WoWScrnShot_080119_101010.PNG": b"shot-c",
    "WoWScrnShot_010224_000001.tga": b"shot-d",
    "WoWScrnShot_120520_111111.jpg": b"era-1",
    "WoWScrnShot_120520_111112.jpg": b"era-2",
}
OLD_SHOT = NOW - 30 * DAY


def _write_bytes(path: Path, data: bytes, mtime: float = OLD_SHOT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


def build_screenshot_tree(root: Path) -> Path:
    """Screenshots for the synthetic install (call after build_wow_tree):

    _retail_/Screenshots: 4 shots (2 on 2019-07-31, 1 on 2019-08-01 with .PNG, 1 on 2024-01-02 with .tga),
        WoWScrnShot_023119_120000.jpg (bad date), notes.txt, and 2025/01/02/WoWScrnShot_010225_090000.jpg
        (already filed in place; never rescanned)
    _classic_era_/Screenshots: 2 shots on 2020-12-05
    _anniversary_: no Screenshots folder
    """
    retail = root / "_retail_" / "Screenshots"
    era = root / "_classic_era_" / "Screenshots"
    for name, data in SHOT_BYTES.items():
        _write_bytes((era if data.startswith(b"era") else retail) / name, data)
    _write_bytes(retail / "WoWScrnShot_023119_120000.jpg", b"bad-date")
    _write_bytes(retail / "notes.txt", b"notes")
    _write_bytes(retail / "2025" / "01" / "02" / "WoWScrnShot_010225_090000.jpg", b"filed")
    return root
```

- [ ] **Step 2: Write the failing tests** (`tests/test_screenshot_organizer_planner.py`)

```python
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests.fixtures import SHOT_BYTES, build_screenshot_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.screenshot_organizer.planner import CONFLICT, MAYBE_DUPLICATE, NEW, scan


class PlannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("retail")
        self.era = self.install.flavor("classic_era")
        self.shots = self.root / "_retail_" / "Screenshots"

    def test_in_place_plan(self):
        plan = scan([self.retail], None)
        [fp] = plan.flavors
        self.assertEqual(fp.target_root, self.shots)
        self.assertEqual(sorted(i.src.name for i in fp.items), sorted(n for n, d in SHOT_BYTES.items()
                                                                     if not d.startswith(b"era")))
        item = next(i for i in fp.items if i.src.name == "WoWScrnShot_073119_232713.jpg")
        self.assertEqual(item.dst, self.shots / "2019" / "07" / "31" / "WoWScrnShot_073119_232713.jpg")
        self.assertEqual((item.day, item.size, item.state), (date(2019, 7, 31), 6, NEW))
        self.assertEqual(sorted(s.path.name for s in fp.skipped), ["WoWScrnShot_023119_120000.jpg", "notes.txt"])
        self.assertTrue(all(s.reason == "name not recognised" for s in fp.skipped))

    def test_already_filed_folders_are_not_rescanned(self):
        plan = scan([self.retail], None)
        self.assertNotIn("WoWScrnShot_010225_090000.jpg", [i.src.name for i in plan.items])

    def test_external_plan_and_flavor_folder_names(self):
        dest = self.tmp / "arch"
        plan = scan([self.retail, self.era], dest)
        self.assertEqual([fp.target_root for fp in plan.flavors], [dest / "_retail_", dest / "_classic_era_"])
        era_item = plan.flavors[1].items[0]
        self.assertEqual(era_item.dst.parent, dest / "_classic_era_" / "2020" / "12" / "05")

    def test_existing_targets_are_duplicates_or_conflicts(self):
        dest = self.tmp / "arch"
        day = dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / "WoWScrnShot_073119_232713.jpg").write_bytes(b"shot-a")       # same size
        (day / "WoWScrnShot_073119_232800.jpg").write_bytes(b"different!")   # other size
        plan = scan([self.retail], dest)
        states = {i.src.name: i.state for i in plan.items}
        self.assertEqual(states["WoWScrnShot_073119_232713.jpg"], MAYBE_DUPLICATE)
        self.assertEqual(states["WoWScrnShot_073119_232800.jpg"], CONFLICT)
        self.assertEqual(len(plan.selectable), len(plan.items) - 1)

    def test_flavor_without_screenshots_contributes_nothing(self):
        anniversary = self.install.flavor("anniversary")
        self.assertEqual(scan([anniversary], None).flavors, [])

    def test_progress_and_events(self):
        calls = []
        with capture_events() as records:
            scan([self.retail, self.era], None, progress=lambda *a: calls.append(a))
        self.assertEqual(calls[0][:2], (0, 2))
        self.assertEqual(calls[-1][:2], (2, 2))
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "shots.scan_started")
        done = next(r for r in records if r["event"] == "shots.scan_completed")
        self.assertEqual(done["data"]["flavors"]["_retail_"]["to_file"], 4)
        self.assertEqual(done["data"]["flavors"]["_retail_"]["unrecognised"], 2)

    def test_unreadable_folder_is_a_warning(self):
        plan = scan([self.retail], None)
        self.assertEqual(plan.warnings, [])
```

- [ ] **Step 3: Run; expect `ModuleNotFoundError`**

Run: `python3 -m unittest tests.test_screenshot_organizer_planner -v`

- [ ] **Step 4: Implement `planner.py`**

```python
"""Scan Screenshots folders and plan where each screenshot goes. Reads only: one listing per source folder and
one per target day folder, no per-file stat or resolve (slow on WSL drvfs)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from wowtools.core.events import log_event
from wowtools.core.install import Flavor
from wowtools.tools.screenshot_organizer.naming import day_parts, parse_shot_name
from wowtools.tools.screenshot_organizer.settings import source_dir, target_root

ScanProgress = Callable[[int, int, str], None]
NEW = "new"
MAYBE_DUPLICATE = "maybe_duplicate"  # a file of the same size is at the target; execute compares hashes
CONFLICT = "conflict"  # a file of another size is at the target: never touched
UNRECOGNISED = "name not recognised"
TICK = 500  # progress tick every N files inside one folder
SAMPLE = 20


@dataclass(frozen=True)
class ShotItem:
    flavor: Flavor
    src: Path
    dst: Path
    day: date
    size: int
    mtime: float
    state: str


@dataclass(frozen=True)
class Skipped:
    flavor: Flavor
    path: Path
    reason: str


@dataclass
class FlavorPlan:
    flavor: Flavor
    source_dir: Path
    target_root: Path
    items: list[ShotItem] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    def _state(self, state: str) -> list[ShotItem]:
        return [i for i in self.items if i.state == state]

    @property
    def new(self) -> list[ShotItem]:
        return self._state(NEW)

    @property
    def maybe_duplicates(self) -> list[ShotItem]:
        return self._state(MAYBE_DUPLICATE)

    @property
    def conflicts(self) -> list[ShotItem]:
        return self._state(CONFLICT)

    @property
    def selectable(self) -> list[ShotItem]:
        return [i for i in self.items if i.state != CONFLICT]


@dataclass
class Plan:
    flavors: list[FlavorPlan]
    dest_dir: Path | None
    warnings: list[str] = field(default_factory=list)

    @property
    def items(self) -> list[ShotItem]:
        return [i for fp in self.flavors for i in fp.items]

    @property
    def selectable(self) -> list[ShotItem]:
        return [i for fp in self.flavors for i in fp.selectable]

    @property
    def skipped(self) -> list[Skipped]:
        return [s for fp in self.flavors for s in fp.skipped]


def list_files(folder: Path) -> dict[str, os.stat_result]:
    """name -> stat for the regular files directly in folder ({} if it does not exist)."""
    files: dict[str, os.stat_result] = {}
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    files[entry.name] = entry.stat(follow_symlinks=False)
    except FileNotFoundError:
        return {}
    return files


def scan(flavors: list[Flavor], dest_dir: Path | None, progress: ScanProgress | None = None) -> Plan:
    log_event("shots.scan_started", flavors=[f.folder for f in flavors],
              dest_dir=str(dest_dir) if dest_dir else None)
    plan = Plan([], dest_dir)
    targets: dict[Path, dict[str, os.stat_result]] = {}
    total = len(flavors)
    summary: dict[str, dict] = {}
    for index, flavor in enumerate(flavors):
        label = f"Reading {flavor.display_name} screenshots"
        if progress:
            progress(index, total, label)
        src_dir = source_dir(flavor)
        if not src_dir.is_dir():
            continue
        try:
            files = list_files(src_dir)
        except OSError as exc:
            plan.warnings.append(f"{src_dir}: {exc}")
            log_event("shots.scan_warning", path=str(src_dir), error=str(exc))
            continue
        root = target_root(flavor, dest_dir)
        fp = FlavorPlan(flavor, src_dir, root)
        for count, name in enumerate(sorted(files, key=str.casefold), start=1):
            if progress and count % TICK == 0:
                progress(index, total, f"{label}: {count} files")
            st = files[name]
            day = parse_shot_name(name)
            if day is None:
                fp.skipped.append(Skipped(flavor, src_dir / name, UNRECOGNISED))
                continue
            day_dir = root.joinpath(*day_parts(day))
            if day_dir not in targets:
                try:
                    targets[day_dir] = list_files(day_dir)
                except OSError as exc:
                    plan.warnings.append(f"{day_dir}: {exc}")
                    log_event("shots.scan_warning", path=str(day_dir), error=str(exc))
                    targets[day_dir] = {}
            existing = targets[day_dir].get(name)
            state = NEW if existing is None else (MAYBE_DUPLICATE if existing.st_size == st.st_size else CONFLICT)
            fp.items.append(ShotItem(flavor, src_dir / name, day_dir / name, day, st.st_size, st.st_mtime, state))
        plan.flavors.append(fp)
        summary[flavor.folder] = {"to_file": len(fp.new), "maybe_duplicates": len(fp.maybe_duplicates),
                                  "conflicts": len(fp.conflicts), "unrecognised": len(fp.skipped),
                                  "unrecognised_sample": [s.path.name for s in fp.skipped[:SAMPLE]]}
    if progress:
        progress(total, total, "Done")
    log_event("shots.scan_completed", flavors=summary, warnings=len(plan.warnings))
    return plan
```

Note: a flavor in place whose `Screenshots/2019/07/31/` already holds a same-name file (copied by hand) lands in `MAYBE_DUPLICATE`/`CONFLICT` like any other target.

- [ ] **Step 5: Run; expect PASS.** Then the full suite: `python3 scripts/run_tests.py`.
- [ ] **Step 6: Commit** with message `feat(screenshots): planner (scan Screenshots folders into a per-flavor plan)`

---

### Task 3: Journal writer and organizer

**Files:**
- Create: `wowtools/tools/screenshot_organizer/journal.py`, `wowtools/tools/screenshot_organizer/organizer.py`
- Test: `tests/test_screenshot_organizer_organizer.py`

**Interfaces:**
- Consumes: Task 2 (`ShotItem`, `list_files`, `CONFLICT`, `MAYBE_DUPLICATE`), Task 1 (`source_dir`, `target_root`, `day_parts`, `parse_shot_name`).
- Produces (journal.py):
  - `JOURNAL_VERSION = 1`
  - Action names: `A_MOVED = "moved"`, `A_COPIED = "copied"`, `A_SOURCE_LEFT = "copied_source_left"`, `A_DUPLICATE = "duplicate_removed"`
  - `new_journal_path(journal_dir: Path, now: datetime | None = None) -> Path`, giving `journal-YYYYMMDD-HHMMSS.jsonl` (with `-2`, `-3`, ... if it is taken)
  - `class JournalWriter(path: Path, header: dict)`: lazy open on the first `add(action, src, dst, size)`; `finish()`; `path`; `count`
  - `@dataclass Journal(path, header: dict, entries: list[dict], finished: str | None, undone: str | None)`; `read_journal(path) -> Journal` (bad lines are ignored); `list_journals(journal_dir) -> list[Path]` (newest first); `latest_undoable(journal_dir) -> Path | None` (newest with entries and not undone); `mark_undone(path, restored: int, skipped: int) -> None`; `prune_journals(journal_dir, keep: int) -> list[Path]`
  - Journal paths are written with `to_stored()` and read with `to_native()`.
- Produces (organizer.py):
  - Outcome kinds: `MOVED, COPIED, SOURCE_LEFT, DUPLICATE_REMOVED, ALREADY_FILED, CONFLICT_KEPT, SKIPPED, REFUSED, FAILED, WOULD_MOVE, WOULD_COPY, WOULD_REMOVE_DUPLICATE, RESTORED, COPY_REMOVED, UNDO_SKIPPED` (string constants equal to their lower-case names: `"moved"`, `"copied"`, `"source_left"`, `"duplicate_removed"`, `"already_filed"`, `"conflict"`, `"skipped"`, `"refused"`, `"failed"`, `"would_move"`, `"would_copy"`, `"would_remove_duplicate"`, `"restored"`, `"copy_removed"`, `"undo_skipped"`)
  - `@dataclass(frozen=True) Outcome(flavor: str, src: Path, dst: Path, kind: str, reason: str = "")`
  - `@dataclass OrganizeResult(dry_run: bool, copy: bool, outcomes: list[Outcome], journal_path: Path | None = None, pruned: list[Path] = [], undo: bool = False)` with `count(kind) -> int`, `counts() -> dict[str, int]`, `of(kind) -> list[Outcome]`
  - `class OrganizeError(Exception)` with `.result: OrganizeResult` (partial)
  - `sha256_file(path) -> str`; `copy_verified(src, dst) -> None` (via `<dst>.partial`, copystat, size and hash verify, refuses an existing `dst`; raises `OSError`); `move_file(src, dst, rename=os.rename) -> bool` (True if it fell back to copy across devices; the source is still there in that case and the caller deletes it)
  - `execute(items: list[ShotItem], *, dest_dir: Path | None, copy: bool, dry_run: bool, journal_dir: Path | None, keep_journals: int, progress: Callable[[str, int, int, str], None] | None = None, rename: Callable[[Path, Path], None] = os.rename) -> OrganizeResult`

- [ ] **Step 1: Write the failing tests** (`tests/test_screenshot_organizer_organizer.py`)

```python
import errno
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import OLD_SHOT, build_screenshot_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.screenshot_organizer.journal import latest_undoable, prune_journals, read_journal
from wowtools.tools.screenshot_organizer.organizer import (ALREADY_FILED, CONFLICT_KEPT, COPIED, DUPLICATE_REMOVED, FAILED,
                                                  MOVED, REFUSED, SKIPPED, SOURCE_LEFT, WOULD_COPY, WOULD_MOVE,
                                                  WOULD_REMOVE_DUPLICATE, OrganizeError, execute)
from wowtools.tools.screenshot_organizer.planner import scan

A = "WoWScrnShot_073119_232713.jpg"
B = "WoWScrnShot_073119_232800.jpg"


def exdev(src, dst):
    raise OSError(errno.EXDEV, "Invalid cross-device link")


class OrganizerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("retail")
        self.era = self.install.flavor("classic_era")
        self.shots = self.root / "_retail_" / "Screenshots"
        self.dest = self.tmp / "arch"
        self.journals = self.tmp / "journal"

    def run_plan(self, dest=None, flavors=None, **kw):
        plan = scan(flavors or [self.retail], dest)
        kw.setdefault("copy", False)
        kw.setdefault("dry_run", False)
        return plan, execute(plan.selectable, dest_dir=dest, journal_dir=self.journals, keep_journals=10, **kw)

    def test_move_in_place(self):
        _, result = self.run_plan()
        self.assertEqual(result.count(MOVED), 4)
        self.assertTrue((self.shots / "2019" / "07" / "31" / A).is_file())
        self.assertFalse((self.shots / A).exists())
        self.assertTrue((self.shots / "notes.txt").exists())  # unrecognised: untouched
        journal = read_journal(result.journal_path)
        self.assertEqual(len(journal.entries), 4)
        self.assertIsNotNone(journal.finished)
        self.assertEqual(result.journal_path, latest_undoable(self.journals))

    def test_move_to_archive_keeps_foreign_files(self):
        self.dest.mkdir()
        (self.dest / "digikam4.db").write_bytes(b"db")
        _, result = self.run_plan(self.dest, [self.retail, self.era])
        self.assertEqual(result.count(MOVED), 6)
        self.assertTrue((self.dest / "_classic_era_" / "2020" / "12" / "05" / "WoWScrnShot_120520_111111.jpg").exists())
        self.assertEqual((self.dest / "digikam4.db").read_bytes(), b"db")

    def test_cross_device_move_verifies_and_keeps_mtime(self):
        _, result = self.run_plan(self.dest, rename=exdev)
        self.assertEqual(result.count(MOVED), 4)
        target = self.dest / "_retail_" / "2019" / "07" / "31" / A
        self.assertEqual(target.read_bytes(), b"shot-a")
        self.assertAlmostEqual(target.stat().st_mtime, OLD_SHOT, delta=2)
        self.assertFalse((self.shots / A).exists())
        self.assertEqual(list(self.dest.rglob("*.partial")), [])

    def test_cross_device_source_left_when_delete_fails(self):
        real_remove = os.remove

        def no_remove(path, *a, **k):
            if Path(path).parent == self.shots:
                raise PermissionError(errno.EACCES, "locked")
            return real_remove(path, *a, **k)

        with unittest.mock.patch("wowtools.tools.screenshot_organizer.organizer.os.remove", no_remove):
            _, result = self.run_plan(self.dest, rename=exdev)
        self.assertEqual(result.count(SOURCE_LEFT), 4)
        self.assertTrue((self.shots / A).exists())
        self.assertTrue((self.dest / "_retail_" / "2019" / "07" / "31" / A).exists())
        self.assertEqual(read_journal(result.journal_path).entries[0]["action"], "copied_source_left")

    def test_copy_mode(self):
        _, result = self.run_plan(self.dest, copy=True)
        self.assertEqual(result.count(COPIED), 4)
        self.assertTrue((self.shots / A).exists())
        self.assertTrue((self.dest / "_retail_" / "2019" / "07" / "31" / A).exists())

    def test_dry_run_changes_nothing(self):
        before = sorted(p for p in self.root.rglob("*"))
        with capture_events() as records:
            _, result = self.run_plan(self.dest, dry_run=True)
        self.assertEqual(result.count(WOULD_MOVE), 4)
        self.assertEqual(sorted(p for p in self.root.rglob("*")), before)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.journals.exists())
        self.assertIsNone(result.journal_path)
        self.assertIn("shots.would_file", [r["event"] for r in records])
        _, copy_result = self.run_plan(self.dest, dry_run=True, copy=True)
        self.assertEqual(copy_result.count(WOULD_COPY), 4)

    def test_duplicate_removed_and_conflict_kept(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / A).write_bytes(b"shot-a")   # identical
        (day / B).write_bytes(b"shot-X")   # same size, different content -> conflict at execute
        plan, result = self.run_plan(self.dest)
        self.assertEqual(result.count(DUPLICATE_REMOVED), 1)
        self.assertEqual(result.count(CONFLICT_KEPT), 1)
        self.assertFalse((self.shots / A).exists())
        self.assertEqual((self.shots / B).read_bytes(), b"shot-b")
        self.assertEqual((day / B).read_bytes(), b"shot-X")

    def test_duplicate_in_copy_mode_and_dry_run(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / A).write_bytes(b"shot-a")
        _, dry = self.run_plan(self.dest, dry_run=True)
        self.assertEqual(dry.count(WOULD_REMOVE_DUPLICATE), 1)
        _, copied = self.run_plan(self.dest, copy=True)
        self.assertEqual(copied.count(ALREADY_FILED), 1)
        self.assertTrue((self.shots / A).exists())

    def test_changed_or_missing_since_scan_is_skipped(self):
        plan = scan([self.retail], self.dest)
        (self.shots / A).write_bytes(b"longer-now")
        (self.shots / B).unlink()
        result = execute(plan.selectable, dest_dir=self.dest, copy=False, dry_run=False,
                         journal_dir=self.journals, keep_journals=10)
        self.assertEqual(result.count(SKIPPED), 2)
        self.assertEqual(result.count(MOVED), 2)

    def test_target_appearing_after_scan_is_never_overwritten(self):
        plan = scan([self.retail], self.dest)
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / A).write_bytes(b"other!")  # same size as shot-a, different bytes
        result = execute(plan.selectable, dest_dir=self.dest, copy=False, dry_run=False,
                         journal_dir=self.journals, keep_journals=10)
        self.assertEqual(result.count(CONFLICT_KEPT), 1)
        self.assertEqual((day / A).read_bytes(), b"other!")

    def test_path_guard_refuses(self):
        plan = scan([self.retail], self.dest)
        item = plan.selectable[0]
        bad = [item.__class__(item.flavor, item.src, self.tmp / "elsewhere" / item.src.name, item.day,
                              item.size, item.mtime, item.state),
               item.__class__(item.flavor, self.tmp / item.src.name, item.dst, item.day, item.size, item.mtime,
                              item.state)]
        result = execute(bad, dest_dir=self.dest, copy=False, dry_run=False, journal_dir=self.journals,
                         keep_journals=10)
        self.assertEqual(result.count(REFUSED), 2)
        self.assertTrue(item.src.exists())

    def test_per_file_error_continues(self):
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 1:
                raise PermissionError(errno.EACCES, "denied")
            os.rename(src, dst)

        _, result = self.run_plan(self.dest, rename=flaky)
        self.assertEqual(result.count(FAILED), 1)
        self.assertEqual(result.count(MOVED), 3)

    def test_unexpected_error_stops_with_partial_journal(self):
        calls = []

        def boom(src, dst):
            calls.append(src)
            if len(calls) == 3:
                raise RuntimeError("boom")
            os.rename(src, dst)

        with capture_events() as records:
            with self.assertRaises(OrganizeError) as ctx:
                self.run_plan(self.dest, rename=boom)
        self.assertEqual(ctx.exception.result.count(MOVED), 2)
        journal = read_journal(ctx.exception.result.journal_path)
        self.assertEqual(len(journal.entries), 2)
        self.assertIsNone(journal.finished)
        self.assertIn("shots.organize_stopped", [r["event"] for r in records])

    def test_stale_partial_is_replaced(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / (A + ".partial")).write_bytes(b"half")
        _, result = self.run_plan(self.dest, rename=exdev)
        self.assertEqual(result.count(MOVED), 4)
        self.assertEqual((day / A).read_bytes(), b"shot-a")
        self.assertFalse((day / (A + ".partial")).exists())

    def test_journal_pruning(self):
        self.journals.mkdir()
        for i in range(5):
            (self.journals / f"journal-2020010{i}-000000.jsonl").write_text('{"version": 1}\n')
        (self.journals / "keep-me.txt").write_text("x")
        removed = prune_journals(self.journals, 2)
        self.assertEqual(len(removed), 3)
        self.assertTrue((self.journals / "keep-me.txt").exists())
        self.assertTrue((self.journals / "journal-20200104-000000.jsonl").exists())

    def test_progress_callback_errors_are_swallowed(self):
        def bad(*a):
            raise ValueError("ui gone")

        _, result = self.run_plan(self.dest, progress=bad)
        self.assertEqual(result.count(MOVED), 4)
```
Add `import unittest.mock` at the top.

- [ ] **Step 2: Run; expect `ModuleNotFoundError`**

Run: `python3 -m unittest tests.test_screenshot_organizer_organizer -v`

- [ ] **Step 3: Implement `journal.py`**

```python
"""Run journals: one JSON Lines file per real run, in <WoW>/wow-tools/screenshot-organizer/journal/.

Line 1 is a header. Each completed action appends one line, flushed at once, so the journal is accurate even if
the run is cut short. A {"finished": ...} line closes a run and an {"undone": ...} line records an undo."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from wowtools.core.events import log_event
from wowtools.core.paths import to_native, to_stored

JOURNAL_VERSION = 1
A_MOVED = "moved"
A_COPIED = "copied"
A_SOURCE_LEFT = "copied_source_left"
A_DUPLICATE = "duplicate_removed"
_NAME = re.compile(r"^journal-(\d{8}-\d{6})(?:-(\d+))?\.jsonl$")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_journal_path(journal_dir: Path, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = journal_dir / f"journal-{stamp}.jsonl"
    n = 2
    while path.exists():
        path = journal_dir / f"journal-{stamp}-{n}.jsonl"
        n += 1
    return path


class JournalWriter:
    """Opens the file on the first entry, so a run that changes nothing leaves no journal."""

    def __init__(self, path: Path, header: dict[str, Any]) -> None:
        self.path = path
        self.header = {"version": JOURNAL_VERSION, **header}
        self.count = 0
        self._handle: IO[str] | None = None

    def _write(self, record: dict[str, Any]) -> None:
        assert self._handle is not None
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._handle.flush()

    def add(self, action: str, src: Path, dst: Path, size: int) -> None:
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("x", encoding="utf-8")
            self._write(self.header)
        self._write({"action": action, "src": to_stored(src), "dst": to_stored(dst), "size": size})
        self.count += 1

    def finish(self) -> None:
        if self._handle is not None:
            self._write({"finished": _now(), "entries": self.count})

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    @property
    def opened(self) -> bool:
        return self.count > 0


@dataclass
class Journal:
    path: Path
    header: dict[str, Any]
    entries: list[dict[str, Any]] = field(default_factory=list)
    finished: str | None = None
    undone: str | None = None

    @property
    def started(self) -> str:
        return str(self.header.get("started", ""))


def read_journal(path: Path) -> Journal:
    journal = Journal(path, {})
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle):
            try:
                record = json.loads(line)
            except ValueError:
                continue  # a torn last line from a crash
            if not isinstance(record, dict):
                continue
            if number == 0 and "version" in record:
                journal.header = record
            elif "action" in record and "src" in record and "dst" in record:
                journal.entries.append({**record, "src": to_native(str(record["src"])),
                                        "dst": to_native(str(record["dst"])), "size": int(record.get("size", -1))})
            elif "finished" in record:
                journal.finished = str(record["finished"])
            elif "undone" in record:
                journal.undone = str(record["undone"])
    return journal


def list_journals(journal_dir: Path | None) -> list[Path]:
    """Journal files, newest first (only journal-<stamp>.jsonl names)."""
    if journal_dir is None or not journal_dir.is_dir():
        return []
    found = [p for p in journal_dir.iterdir() if p.is_file() and _NAME.match(p.name)]

    def key(p: Path) -> tuple[str, int]:
        m = _NAME.match(p.name)
        assert m is not None
        return m.group(1), int(m.group(2) or 1)

    return sorted(found, key=key, reverse=True)


def latest_undoable(journal_dir: Path | None) -> Path | None:
    """The newest journal that has entries and was not undone. Only that journal is ever offered."""
    for path in list_journals(journal_dir):
        try:
            journal = read_journal(path)
        except OSError:
            continue
        if journal.undone is None and journal.entries:
            return path
        if journal.undone is not None:
            return None  # never reach back past an undone run
    return None


def mark_undone(path: Path, restored: int, skipped: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"undone": _now(), "restored": restored, "skipped": skipped}) + "\n")


def prune_journals(journal_dir: Path | None, keep: int) -> list[Path]:
    removed = []
    for path in list_journals(journal_dir)[max(1, keep):]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    if removed:
        log_event("shots.journal_pruned", removed=[p.name for p in removed], keep=keep)
    return removed
```

`latest_undoable` returns None once it meets an undone journal. That gives one level of undo, as spec §12 requires: undoing the last run never exposes the run before it.

- [ ] **Step 4: Implement `organizer.py`**

```python
"""File planned screenshots into their date folders: guard, re-check, move or copy, journal.

Never overwrites. One listing per source folder and per target day folder; per-file stat only where a hash
or copy needs it. A dry run walks the same checks (hashing included) and changes nothing."""
from __future__ import annotations

import errno
import hashlib
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from wowtools import __version__
from wowtools.core.events import log_event
from wowtools.core.paths import to_stored
from wowtools.tools.screenshot_organizer.journal import (A_COPIED, A_DUPLICATE, A_MOVED, A_SOURCE_LEFT, JournalWriter,
                                                new_journal_path, prune_journals)
from wowtools.tools.screenshot_organizer.naming import day_parts, parse_shot_name
from wowtools.tools.screenshot_organizer.planner import CONFLICT, ShotItem, list_files
from wowtools.tools.screenshot_organizer.settings import source_dir, target_root

Progress = Callable[[str, int, int, str], None]
Rename = Callable[[Path, Path], None]
PARTIAL = ".partial"
CHUNK = 1024 * 1024

MOVED, COPIED, SOURCE_LEFT = "moved", "copied", "source_left"
DUPLICATE_REMOVED, ALREADY_FILED, CONFLICT_KEPT = "duplicate_removed", "already_filed", "conflict"
SKIPPED, REFUSED, FAILED = "skipped", "refused", "failed"
WOULD_MOVE, WOULD_COPY, WOULD_REMOVE_DUPLICATE = "would_move", "would_copy", "would_remove_duplicate"
RESTORED, COPY_REMOVED, UNDO_SKIPPED = "restored", "copy_removed", "undo_skipped"

_EVENTS = {MOVED: "shots.moved", COPIED: "shots.copied", SOURCE_LEFT: "shots.source_left",
           DUPLICATE_REMOVED: "shots.duplicate_removed", ALREADY_FILED: "shots.already_filed",
           CONFLICT_KEPT: "shots.conflict", SKIPPED: "shots.skipped", REFUSED: "shots.refused",
           FAILED: "shots.failed", WOULD_MOVE: "shots.would_file", WOULD_COPY: "shots.would_file",
           WOULD_REMOVE_DUPLICATE: "shots.would_file"}


@dataclass(frozen=True)
class Outcome:
    flavor: str
    src: Path
    dst: Path
    kind: str
    reason: str = ""


@dataclass
class OrganizeResult:
    dry_run: bool
    copy: bool
    outcomes: list[Outcome] = field(default_factory=list)
    journal_path: Path | None = None
    pruned: list[Path] = field(default_factory=list)
    undo: bool = False

    def of(self, kind: str) -> list[Outcome]:
        return [o for o in self.outcomes if o.kind == kind]

    def count(self, kind: str) -> int:
        return sum(1 for o in self.outcomes if o.kind == kind)

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for o in self.outcomes:
            result[o.kind] = result.get(o.kind, 0) + 1
        return result


class OrganizeError(Exception):
    """A run stopped unexpectedly. `result` holds what was done; the journal records it for Undo."""

    def __init__(self, message: str, result: OrganizeResult) -> None:
        super().__init__(message)
        self.result = result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same_file_content(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and sha256_file(a) == sha256_file(b)


def copy_verified(src: Path, dst: Path) -> None:
    """Copy src to dst through <dst>.partial: copy bytes and times, check size and SHA-256, then rename into
    place. Refuses an existing dst. Raises OSError on any failure (the partial file is removed)."""
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "target exists", str(dst))
    partial = dst.with_name(dst.name + PARTIAL)
    if os.path.lexists(partial):
        os.remove(partial)  # left over from an interrupted run; our own temporary name
    source_hash = hashlib.sha256()
    try:
        with src.open("rb") as reader, partial.open("xb") as writer:
            for chunk in iter(lambda: reader.read(CHUNK), b""):
                source_hash.update(chunk)
                writer.write(chunk)
        shutil.copystat(src, partial)
        if partial.stat().st_size != src.stat().st_size or sha256_file(partial) != source_hash.hexdigest():
            raise OSError(errno.EIO, "copy verification failed", str(dst))
        if os.path.lexists(dst):
            raise FileExistsError(errno.EEXIST, "target appeared during copy", str(dst))
        os.rename(partial, dst)
    except BaseException:
        try:
            os.remove(partial)
        except OSError:
            pass
        raise


def move_file(src: Path, dst: Path, rename: Rename = os.rename) -> bool:
    """Rename src to dst. Across devices (EXDEV), copy it verified instead and return True: the source is then
    still there and the caller deletes it."""
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "target exists", str(dst))
    try:
        rename(src, dst)
        return False
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    copy_verified(src, dst)
    return True


def _guard(item: ShotItem, dest_dir: Path | None) -> str | None:
    if item.src.parent != source_dir(item.flavor):
        return "source is not directly in the flavor's Screenshots folder"
    day = parse_shot_name(item.src.name)
    if day is None or day != item.day:
        return "source name does not match the planned day"
    expected = target_root(item.flavor, dest_dir).joinpath(*day_parts(day), item.src.name)
    if item.dst != expected or ".." in item.dst.parts:
        return f"target is not {expected}"
    return None


def _safe(progress: Progress | None) -> Progress:
    def call(stage: str, current: int, total: int, detail: str = "") -> None:
        if progress is None:
            return
        try:
            progress(stage, current, total, detail)
        except Exception:  # noqa: BLE001 - a broken progress callback must never disturb a run
            pass
    return call


class _Run:
    def __init__(self, dest_dir: Path | None, copy: bool, dry_run: bool, journal: JournalWriter | None,
                 rename: Rename) -> None:
        self.dest_dir = dest_dir
        self.copy = copy
        self.dry_run = dry_run
        self.journal = journal
        self.rename = rename
        self.sources: dict[Path, dict[str, os.stat_result]] = {}
        self.targets: dict[Path, set[str]] = {}

    def _source_size(self, item: ShotItem) -> int | None:
        folder = item.src.parent
        if folder not in self.sources:
            self.sources[folder] = list_files(folder)
        st = self.sources[folder].get(item.src.name)
        return None if st is None else st.st_size

    def _target_exists(self, item: ShotItem) -> bool:
        folder = item.dst.parent
        if folder not in self.targets:
            self.targets[folder] = set(list_files(folder))
        return item.dst.name in self.targets[folder] or os.path.lexists(item.dst)

    def _record(self, action: str, item: ShotItem) -> None:
        if self.journal is not None:
            self.journal.add(action, item.src, item.dst, item.size)

    def file_one(self, item: ShotItem) -> Outcome:
        def out(kind: str, reason: str = "") -> Outcome:
            return Outcome(item.flavor.folder, item.src, item.dst, kind, reason)

        refusal = _guard(item, self.dest_dir)
        if refusal:
            return out(REFUSED, refusal)
        if item.state == CONFLICT:
            return out(CONFLICT_KEPT, "a different file with this name is already at the target")
        size = self._source_size(item)
        if size is None:
            return out(SKIPPED, "missing since the scan")
        if size != item.size:
            return out(SKIPPED, "changed since the scan")
        if self._target_exists(item):
            if not same_file_content(item.src, item.dst):
                return out(CONFLICT_KEPT, "a different file with this name is already at the target")
            if self.copy:
                return out(ALREADY_FILED, "an identical file is already at the target")
            if self.dry_run:
                return out(WOULD_REMOVE_DUPLICATE, "identical file already at the target")
            os.remove(item.src)
            self._record(A_DUPLICATE, item)
            return out(DUPLICATE_REMOVED, "identical file already at the target")
        if self.dry_run:
            return out(WOULD_COPY if self.copy else WOULD_MOVE)
        os.makedirs(item.dst.parent, exist_ok=True)
        if self.copy:
            copy_verified(item.src, item.dst)
            self.targets.setdefault(item.dst.parent, set()).add(item.dst.name)
            self._record(A_COPIED, item)
            return out(COPIED)
        copied = move_file(item.src, item.dst, self.rename)
        self.targets.setdefault(item.dst.parent, set()).add(item.dst.name)
        if copied:
            try:
                os.remove(item.src)
            except OSError as exc:
                self._record(A_SOURCE_LEFT, item)
                return out(SOURCE_LEFT, f"copied, but the source could not be deleted: {exc}")
        self._record(A_MOVED, item)
        return out(MOVED)


def execute(items: list[ShotItem], *, dest_dir: Path | None, copy: bool, dry_run: bool,
            journal_dir: Path | None, keep_journals: int, progress: Progress | None = None,
            rename: Rename = os.rename) -> OrganizeResult:
    report = _safe(progress)
    result = OrganizeResult(dry_run=dry_run, copy=copy)
    journal = None
    if not dry_run and journal_dir is not None:
        journal = JournalWriter(new_journal_path(journal_dir), {
            "started": datetime.now().astimezone().isoformat(timespec="seconds"), "copy": copy,
            "dest_dir": to_stored(dest_dir) if dest_dir else None, "suite_version": __version__,
            "flavors": sorted({i.flavor.folder for i in items})})
    log_event("shots.organize_started", dry_run=dry_run, copy=copy, files=len(items),
              dest_dir=str(dest_dir) if dest_dir else None)
    run = _Run(dest_dir, copy, dry_run, journal, rename)
    total = len(items)
    try:
        for index, item in enumerate(items):
            report("organize", index, total, item.src.name)
            try:
                outcome = run.file_one(item)
            except OSError as exc:
                outcome = Outcome(item.flavor.folder, item.src, item.dst, FAILED, str(exc))
            result.outcomes.append(outcome)
            log_event(_EVENTS[outcome.kind], dry_run=dry_run, flavor=outcome.flavor, src=str(outcome.src),
                      dst=str(outcome.dst), reason=outcome.reason or None)
        report("organize", total, total, "")
        if journal is not None:
            journal.finish()
    except (Exception, KeyboardInterrupt) as exc:
        if journal is not None:
            journal.close()
            result.journal_path = journal.path if journal.opened else None
        log_event("shots.organize_stopped", error=f"{type(exc).__name__}: {exc}", done=len(result.outcomes),
                  journal=str(result.journal_path) if result.journal_path else None)
        raise OrganizeError(f"The run stopped: {exc}", result) from exc
    finally:
        if journal is not None:
            journal.close()
    if journal is not None and journal.opened:
        result.journal_path = journal.path
        report("prune", 0, 0, "")
        result.pruned = prune_journals(journal_dir, keep_journals)
    counts = result.counts()
    log_event("shots.organize_completed", level="warning" if counts.get(FAILED) else None, dry_run=dry_run,
              copy=copy, counts=counts, journal=str(result.journal_path) if result.journal_path else None)
    return result
```

- [ ] **Step 5: Run; expect PASS.** Then `python3 scripts/run_tests.py`.
- [ ] **Step 6: Commit** with message `feat(screenshots): organizer (move/copy/dry run, duplicate and conflict handling, run journal)`

---

### Task 4: Undo

**Files:**
- Create: `wowtools/tools/screenshot_organizer/undo.py`
- Test: `tests/test_screenshot_organizer_undo.py`

**Interfaces:**
- Consumes: Task 3 (`read_journal`, `mark_undone`, `A_*`, `Outcome`, `OrganizeResult`, `RESTORED`, `COPY_REMOVED`, `UNDO_SKIPPED`, `FAILED`, `move_file`, `copy_verified`).
- Produces: `undo(journal_path: Path, *, wow_root: Path, progress: Progress | None = None, rename: Rename = os.rename) -> OrganizeResult` (with `undo=True` and `journal_path` set)

Rules:
- Path guard per entry: `src.parent.name == "Screenshots"` and `src.parent.parent.parent == wow_root` (compared lexically). `dst` must end in `YYYY/MM/DD/<src.name>`, with digit names of lengths 4, 2 and 2. A failed guard gives `UNDO_SKIPPED` with the reason "outside the WoW folder or not a date folder".
- Entries are processed in reverse order.
- `moved`: `dst` must be a file of the recorded size and `src` must not exist. Then `move_file(dst, src, rename)`; if that copied across devices, `os.remove(dst)`. The outcome is `RESTORED`.
- `copied` and `copied_source_left`: `src` must exist with the recorded size, and `dst` must exist with the recorded size. Then `os.remove(dst)`, giving `COPY_REMOVED`.
- `duplicate_removed`: `src` must be free and `dst` must exist with the recorded size. Then `copy_verified(dst, src)`, giving `RESTORED`.
- A failed check gives `UNDO_SKIPPED` (with the reason). An `OSError` gives `FAILED`.
- Prune empty folders: for each distinct `dst.parent` (DD), try `rmdir` on DD, then MM, then YYYY, each only if its name is digits of the right length and the folder is empty (`os.rmdir` raises if it isn't; catch `OSError` and stop for that chain).
- `mark_undone(journal_path, restored, skipped)`, where restored counts `RESTORED` and `COPY_REMOVED`, and skipped counts `UNDO_SKIPPED` and `FAILED`.
- Events: `shots.undo_started` (journal, entries), `shots.undo_restored`, `shots.undo_skipped` and `shots.undo_failed` per entry, then `shots.undo_completed` (counts).

- [ ] **Step 1: Write the failing tests** (`tests/test_screenshot_organizer_undo.py`)

```python
import errno
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_screenshot_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.screenshot_organizer.journal import latest_undoable, read_journal
from wowtools.tools.screenshot_organizer.organizer import (COPY_REMOVED, RESTORED, UNDO_SKIPPED, OrganizeError, execute)
from wowtools.tools.screenshot_organizer.planner import scan
from wowtools.tools.screenshot_organizer.undo import undo

A = "WoWScrnShot_073119_232713.jpg"


def exdev(src, dst):
    raise OSError(errno.EXDEV, "Invalid cross-device link")


class UndoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.retail = WowInstall(self.root).flavor("retail")
        self.shots = self.root / "_retail_" / "Screenshots"
        self.dest = self.tmp / "arch"
        self.journals = self.tmp / "journal"
        self.before = {p.name: p.read_bytes() for p in self.shots.iterdir() if p.is_file()}

    def organize(self, dest=None, **kw):
        plan = scan([self.retail], dest)
        kw.setdefault("copy", False)
        return execute(plan.selectable, dest_dir=dest, dry_run=False, journal_dir=self.journals,
                       keep_journals=10, **kw)

    def assert_restored(self):
        now = {p.name: p.read_bytes() for p in self.shots.iterdir() if p.is_file()}
        self.assertEqual(now, self.before)

    def test_undo_moves_back_and_prunes_empty_date_folders(self):
        result = self.organize(self.dest)
        with capture_events() as records:
            back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(RESTORED), 4)
        self.assert_restored()
        self.assertEqual(list((self.dest / "_retail_").iterdir()), [])
        self.assertIsNotNone(read_journal(result.journal_path).undone)
        self.assertIsNone(latest_undoable(self.journals))
        self.assertIn("shots.undo_completed", [r["event"] for r in records])

    def test_undo_in_place_keeps_already_filed_folders(self):
        result = self.organize(None)
        undo(result.journal_path, wow_root=self.root)
        self.assert_restored()
        self.assertTrue((self.shots / "2025" / "01" / "02" / "WoWScrnShot_010225_090000.jpg").exists())
        self.assertFalse((self.shots / "2019").exists())

    def test_undo_cross_device(self):
        result = self.organize(self.dest, rename=exdev)
        back = undo(result.journal_path, wow_root=self.root, rename=exdev)
        self.assertEqual(back.count(RESTORED), 4)
        self.assert_restored()

    def test_undo_copy_removes_copies(self):
        result = self.organize(self.dest, copy=True)
        back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(COPY_REMOVED), 4)
        self.assert_restored()
        self.assertFalse((self.dest / "_retail_" / "2019").exists())

    def test_undo_restores_removed_duplicate(self):
        day = self.dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / A).write_bytes(b"shot-a")
        result = self.organize(self.dest)
        undo(result.journal_path, wow_root=self.root)
        self.assert_restored()
        self.assertEqual((day / A).read_bytes(), b"shot-a")  # the archive copy stays

    def test_undo_skips_when_things_changed(self):
        result = self.organize(self.dest)
        moved = self.dest / "_retail_" / "2019" / "07" / "31" / A
        moved.write_bytes(b"edited in an image editor")
        (self.shots / "WoWScrnShot_073119_232800.jpg").write_bytes(b"new file at source")
        back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(UNDO_SKIPPED), 2)
        self.assertEqual(back.count(RESTORED), 2)
        self.assertTrue(moved.exists())

    def test_undo_never_removes_foreign_or_nonempty_folders(self):
        result = self.organize(self.dest)
        (self.dest / "_retail_" / "2019" / "07" / "31" / "Thumbs.db").write_bytes(b"x")
        (self.dest / "_retail_" / "albums").mkdir()
        undo(result.journal_path, wow_root=self.root)
        self.assertTrue((self.dest / "_retail_" / "2019" / "07" / "31" / "Thumbs.db").exists())
        self.assertTrue((self.dest / "_retail_" / "albums").is_dir())
        self.assertFalse((self.dest / "_retail_" / "2019" / "08").exists())

    def test_undo_of_journal_without_finished_line(self):
        calls = []

        def boom(src, dst):
            calls.append(src)
            if len(calls) == 3:
                raise RuntimeError("boom")
            import os
            os.rename(src, dst)

        with self.assertRaises(OrganizeError) as ctx:
            self.organize(self.dest, rename=boom)
        path = ctx.exception.result.journal_path
        self.assertEqual(latest_undoable(self.journals), path)
        back = undo(path, wow_root=self.root)
        self.assertEqual(back.count(RESTORED), 2)
        self.assert_restored()

    def test_undo_ignores_current_settings(self):
        result = self.organize(self.dest)
        # The user points dest_dir somewhere else afterwards: undo only reads the journal.
        back = undo(result.journal_path, wow_root=self.root)
        self.assertEqual(back.count(RESTORED), 4)

    def test_undo_refuses_paths_outside_the_install(self):
        result = self.organize(self.dest)
        back = undo(result.journal_path, wow_root=self.tmp / "Other WoW")
        self.assertEqual(back.count(UNDO_SKIPPED), 4)
        self.assertFalse((self.shots / A).exists())

    def test_only_the_newest_run_is_undoable(self):
        first = self.organize(self.dest)
        (self.shots / "WoWScrnShot_010101_000000.jpg").write_bytes(b"later")
        second = self.organize(self.dest)
        self.assertEqual(latest_undoable(self.journals), second.journal_path)
        undo(second.journal_path, wow_root=self.root)
        self.assertIsNone(latest_undoable(self.journals))
        self.assertIsNotNone(first.journal_path)
```

- [ ] **Step 2: Run; expect `ModuleNotFoundError`**

Run: `python3 -m unittest tests.test_screenshot_organizer_undo -v`

- [ ] **Step 3: Implement `undo.py`**

```python
"""Undo one run from its journal: newest entry first, and only when everything still matches what the journal
recorded. Never overwrites. Afterwards, empty YYYY/MM/DD folders the run filed into are removed."""
from __future__ import annotations

import os
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.tools.screenshot_organizer.journal import (A_COPIED, A_DUPLICATE, A_MOVED, A_SOURCE_LEFT, mark_undone,
                                                read_journal)
from wowtools.tools.screenshot_organizer.organizer import (COPY_REMOVED, FAILED, RESTORED, UNDO_SKIPPED, OrganizeResult,
                                                  Outcome, Progress, Rename, _safe, copy_verified, move_file)
from wowtools.tools.screenshot_organizer.settings import SCREENSHOTS_DIR

_DATE_PARTS = (4, 2, 2)  # YYYY, MM, DD


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size if path.is_file() else None
    except OSError:
        return None


def _guard(src: Path, dst: Path, wow_root: Path) -> str | None:
    if src.parent.name != SCREENSHOTS_DIR or src.parent.parent.parent != wow_root:
        return "outside the WoW folder or not a date folder"
    parts = dst.parts
    if (len(parts) < 4 or parts[-1] != src.name or ".." in parts
            or not all(p.isdigit() and len(p) == n for p, n in zip(parts[-4:-1], _DATE_PARTS))):
        return "outside the WoW folder or not a date folder"
    return None


def _undo_one(entry: dict, wow_root: Path, rename: Rename) -> tuple[str, str]:
    src, dst, size, action = entry["src"], entry["dst"], entry["size"], entry["action"]
    refusal = _guard(src, dst, wow_root)
    if refusal:
        return UNDO_SKIPPED, refusal
    if action == A_MOVED:
        if _size(dst) != size:
            return UNDO_SKIPPED, "the filed copy is missing or was changed"
        if os.path.lexists(src):
            return UNDO_SKIPPED, "a file with this name is back in the Screenshots folder"
        if move_file(dst, src, rename):
            os.remove(dst)
        return RESTORED, ""
    if action in (A_COPIED, A_SOURCE_LEFT):
        if _size(src) != size:
            return UNDO_SKIPPED, "the original is missing or was changed, so the copy is kept"
        if _size(dst) != size:
            return UNDO_SKIPPED, "the copy is missing or was changed"
        os.remove(dst)
        return COPY_REMOVED, ""
    if action == A_DUPLICATE:
        if os.path.lexists(src):
            return UNDO_SKIPPED, "a file with this name is back in the Screenshots folder"
        if _size(dst) != size:
            return UNDO_SKIPPED, "the filed copy is missing or was changed"
        copy_verified(dst, src)
        return RESTORED, ""
    return UNDO_SKIPPED, f"unknown action {action!r}"


def _prune_date_folders(day_dirs: set[Path]) -> None:
    for day_dir in sorted(day_dirs, key=lambda p: len(p.parts), reverse=True):
        folder = day_dir
        for length in reversed(_DATE_PARTS):  # DD, MM, YYYY
            if not (folder.name.isdigit() and len(folder.name) == length):
                break
            try:
                os.rmdir(folder)
            except OSError:
                break  # not empty (or gone): stop climbing
            folder = folder.parent


def undo(journal_path: Path, *, wow_root: Path, progress: Progress | None = None,
         rename: Rename = os.rename) -> OrganizeResult:
    report = _safe(progress)
    journal = read_journal(journal_path)
    result = OrganizeResult(dry_run=False, copy=bool(journal.header.get("copy")), journal_path=journal_path,
                            undo=True)
    entries = list(reversed(journal.entries))
    log_event("shots.undo_started", journal=str(journal_path), entries=len(entries))
    day_dirs: set[Path] = set()
    for index, entry in enumerate(entries):
        report("undo", index, len(entries), entry["dst"].name)
        flavor = entry["src"].parent.parent.name
        try:
            kind, reason = _undo_one(entry, wow_root, rename)
        except OSError as exc:
            kind, reason = FAILED, str(exc)
        if kind in (RESTORED, COPY_REMOVED):
            day_dirs.add(entry["dst"].parent)
        result.outcomes.append(Outcome(flavor, entry["src"], entry["dst"], kind, reason))
        event = {RESTORED: "shots.undo_restored", COPY_REMOVED: "shots.undo_restored",
                 UNDO_SKIPPED: "shots.undo_skipped"}.get(kind, "shots.undo_failed")
        log_event(event, action=entry["action"], src=str(entry["src"]), dst=str(entry["dst"]), reason=reason or None)
    report("undo", len(entries), len(entries), "")
    _prune_date_folders(day_dirs)
    restored = result.count(RESTORED) + result.count(COPY_REMOVED)
    skipped = result.count(UNDO_SKIPPED) + result.count(FAILED)
    mark_undone(journal_path, restored, skipped)
    log_event("shots.undo_completed", level="warning" if skipped else None, journal=str(journal_path),
              restored=restored, skipped=skipped)
    return result
```

Rename `organizer._safe` to the public `safe_progress` in Task 3 if the reviewer objects to the private import. Either name works as long as both modules use the same one.

- [ ] **Step 4: Run; expect PASS.** Then `python3 scripts/run_tests.py`.
- [ ] **Step 5: Commit** with message `feat(screenshots): undo the last run from its journal`

---

### Task 5: FlavorScreen "All flavors"

**Files:**
- Modify: `wowtools/ui/flavor_screen.py`
- Test: `tests/test_suite_app.py` or a new `tests/test_flavor_screen.py` (new file preferred)

**Interfaces (produces):**
- `flavor_screen.ALL_FLAVORS = "__all__"`
- `FlavorScreen(cfg, install, *, include_all: bool = False, last: str | None = None, flavors: list[Flavor] | None = None)`. It dismisses with a `Flavor`, with `ALL_FLAVORS` (only when `include_all`), or with `None` (Esc).
  - `flavors` overrides `install.flavors()`, for example to list only flavors that have a Screenshots folder.
  - `last` is the folder to highlight. `""` means "All flavors". `None` falls back to `cfg.last_flavor`.
  - Choosing a flavor still saves `[general] last_flavor`. Choosing All leaves it alone and logs `ui.selection` with value `all`.

- [ ] **Step 1: Write the failing tests** (`tests/test_flavor_screen.py`)

```python
import tempfile
from pathlib import Path

from textual.app import App
from textual.widgets import OptionList

from tests.fixtures import TuiTestCase, build_wow_tree, make_config
from wowtools.core.install import WowInstall
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self.picker = screen
        self.result = "unset"

    def on_mount(self):
        self.push_screen(self.picker, self.done)

    def done(self, value):
        self.result = value


class FlavorScreenTest(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.cfg = make_config(self.tmp / "config", self.root)
        self.install = WowInstall(self.root)

    async def test_default_has_no_all_entry(self):
        app = Host(FlavorScreen(self.cfg, self.install))
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#flavors", OptionList)
            self.assertNotIn(ALL_FLAVORS, [options.get_option_at_index(i).id for i in range(options.option_count)])

    async def test_all_flavors_first_and_selected(self):
        app = Host(FlavorScreen(self.cfg, self.install, include_all=True, last=""))
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#flavors", OptionList)
            self.assertEqual(options.get_option_at_index(0).id, ALL_FLAVORS)
            self.assertEqual(options.highlighted, 0)
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.result, ALL_FLAVORS)
        self.assertEqual(self.cfg.last_flavor, "_retail_")  # unchanged

    async def test_last_flavor_highlighted_and_flavor_override(self):
        era = self.install.flavor("classic_era")
        app = Host(FlavorScreen(self.cfg, self.install, include_all=True, last="_classic_era_",
                                flavors=[self.install.flavor("retail"), era]))
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#flavors", OptionList)
            self.assertEqual(options.option_count, 3)
            self.assertEqual(options.get_option_at_index(options.highlighted).id, "_classic_era_")
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.result, era)
        self.assertEqual(self.cfg.last_flavor, "_classic_era_")
```

- [ ] **Step 2: Run; expect FAIL** (`ImportError: ALL_FLAVORS`). Run: `python3 -m unittest tests.test_flavor_screen -v`

- [ ] **Step 3: Implement.** Change `wowtools/ui/flavor_screen.py`:

```python
ALL_FLAVORS = "__all__"  # dismiss value for the "All flavors" entry (include_all=True only)


class FlavorScreen(Screen[Union[Flavor, str, None]]):
    ...
    def __init__(self, cfg: Config, install: WowInstall, *, include_all: bool = False, last: str | None = None,
                 flavors: list[Flavor] | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavors = install.flavors() if flavors is None else flavors
        self.include_all = include_all
        self.last = cfg.last_flavor if last is None else last

    def compose(self) -> ComposeResult:
        options = [Option(Text(f"{f.display_name}  ({f.folder})"), id=f.folder) for f in self.flavors]
        if self.include_all:
            options.insert(0, Option(Text.assemble(("All flavors", "bold"), f"  ({len(self.flavors)})"),
                                     id=ALL_FLAVORS))
        yield Header()
        yield Banner()
        yield Static("Choose a WoW flavor", classes="title")
        yield OptionList(*options, id="flavors")
        yield NavHint("↑↓ choose · Enter select · Esc back to tools")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Choose flavor"
        options = self.query_one("#flavors", OptionList)
        ids = ([ALL_FLAVORS] if self.include_all else []) + [f.folder for f in self.flavors]
        wanted = ALL_FLAVORS if self.include_all and self.last == "" else self.last
        options.highlighted = ids.index(wanted) if wanted in ids else 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == ALL_FLAVORS:
            log_event("ui.selection", screen="flavor", control="flavor", value="all")
            self.dismiss(ALL_FLAVORS)
            return
        ...  # unchanged: save last_flavor, log, dismiss(flavor)
```
(`from typing import Union` replaces `Optional`; the module keeps `from __future__ import annotations`.)

- [ ] **Step 4: Run** the new tests and `python3 -m unittest tests.test_wtf_app -v`; expect PASS (the cleaner is unchanged).
- [ ] **Step 5: Commit** with message `feat(ui): FlavorScreen can offer "All flavors" and a custom flavor list`

---

### Task 6: TUI (flow, settings, review, progress, result) and registration

**Files:**
- Create: `wowtools/tools/screenshot_organizer/report.py`, `app.py`, `review_screen.py`
- Modify: `wowtools/tools/__init__.py`, `README.md` (tools-table row and a short section, so `tests/test_docs.py` passes)
- Test: `tests/test_screenshot_organizer_app.py`, `tests/test_screenshot_organizer_report.py`

**Interfaces:**
- Consumes: everything above. Patterns to copy from `wowtools/tools/wtf_cleaner/app.py` and `review_screen.py` (read both first): the settings screen layout and validation, `ConfirmScreen` (import it from `wowtools.tools.wtf_cleaner.review_screen`; it is generic), the progress modal, the result screen, thread workers with `call_from_thread`, `app.busy`, and the `_after_review` dispatch.
- Produces:
  - `report.KIND_LABELS: dict[str, str]`, which maps every outcome kind to text such as `"moved": "Moved"`, `"would_move": "Would move"`, `"conflict": "Conflict (kept both)"`, `"source_left": "Copied, source left"`, `"restored": "Put back"`, `"copy_removed": "Copy removed"`, `"undo_skipped": "Left alone"`
  - `report.STAGE_TITLES = {"organize": "Filing screenshots", "prune": "Tidying journals", "undo": "Undoing the last run"}`
  - `report.RESULT_COLUMNS = ("Outcome", "Flavor", "File", "Target", "Reason")`
  - `report.result_rows(result) -> list[tuple[str, str, str, str, str]]`: file is `src.name`, target is `str(dst.parent)`
  - `report.summary_rows(result) -> list[tuple[str, str]]`: a Mode row ("Move", "Copy", "Dry run (move)", "Dry run (copy)" or "Undo"), one row per non-zero kind in `KIND_LABELS` order, and a Journal row (path, "not written (dry run)", or "none (nothing changed)"), plus "Older journals removed" when pruned
  - `report.confirm_text(selection, plan, settings, dry_run) -> tuple[str, str]` (title, body)
  - `report.destination_label(dest_dir) -> str`: `"in place (<flavor>\\Screenshots\\YYYY\\MM\\DD)"` or `to_stored(dest) + "\\<flavor>\\YYYY\\MM\\DD"`
  - `app.ScreenshotsFlow(ToolFlow)` and `FLOW`, plus `app.ScreenshotSettingsScreen(Screen[bool])`
  - `review_screen.ShotReviewScreen(Screen[str])`, `ShotProgressScreen(ModalScreen[None])`, `ShotResultScreen(Screen[str])`
  - Registration: `Tool("screenshot-organizer", "Screenshot Organizer", "File screenshots into year/month/day folders, per flavor.", "wowtools.tools.screenshot_organizer.app", "screenshot_organizer")`, second in `TOOLS`

Behaviour:

**`ScreenshotsFlow`**
- `start()` calls `self.require_install(self._ready)`.
- `_ready`: if `not self.tool_cfg.exists`, push `ScreenshotSettingsScreen(self.tool_cfg, install, source="wizard")`, then `_pick_flavor`.
- `_pick_flavor`: `flavors = [f for f in install.flavors() if source_dir(f).is_dir()]`. If none have a Screenshots folder, `self.app.notify("No Screenshots folders found in <WoW folder>.", severity="warning")` and `self.close()`. Otherwise push `FlavorScreen(self.cfg, install, include_all=True, last=settings.last_flavor_choice, flavors=flavors)`.
- `_after_flavor(choice)`: `None` closes the tool. `ALL_FLAVORS` gives `chosen = flavors` and `label = "All flavors"`; otherwise `[choice]` and `choice.display_name`. Save `last_flavor_choice` (`""` for All, else the folder) with `tool_cfg.set` plus `save_if_exists()`, as the cleaner saves `last_account`. Then push `ShotReviewScreen(self.cfg, self.tool_cfg, chosen, label)`.
- `_after_review(choice)`: `"flavors"` goes back to `_pick_flavor`, `"tools"` closes the tool, anything else calls `self.app.exit()`.
- `open_settings()` (the `s` key): `self.app.open_general_settings(lambda _: push ScreenshotSettingsScreen(..., source="settings"))`, then notify "Settings saved. Press r on the review screen to rescan with them." Guard against `isinstance(self.app.screen, ScreenshotSettingsScreen)`.

**`ScreenshotSettingsScreen(tool_cfg, install: WowInstall | None, *, source)`**
- Fields:
  - `#dest_dir`: an Input holding the stored form, with placeholder `"Empty = in place: <flavor>\\Screenshots\\YYYY\\MM\\DD"`.
  - `#keep_journals`: an integer Input.
  - `#sw_copy`: a `Ka0sCheckbox`, "Copy instead of move (the screenshots stay in the Screenshots folder too)".
- Above the fields, a label that explains the external layout: `"<destination>\\<flavor folder>\\YYYY\\MM\\DD, e.g. ...\\_retail_\\2019\\07\\31"`.
- Save validates `keep_journals >= 1` ("Keep at least 1 journal.") and `validate_dest(...)` when an install is known. Errors go to `#settings-error`.
- Save keeps `last_flavor_choice` from the stored settings, calls `save_settings(...)`, and dismisses True. Esc or Cancel dismisses False.
- `Header`, `BrandBar`, `Footer` and `NavHint`, with the cleaner's CSS classes and `ButtonRow` buttons `#save` and `#cancel`.

**`ShotReviewScreen(cfg, tool_cfg, flavors: list[Flavor], scope_label: str)`**
- Layout, as in the cleaner's `ReviewScreen`:
  - Left panel `#filters`: a "Destination" section showing `destination_label`, a "Mode" section showing Move or Copy, a `ButtonRow(id="actions", wrap=False)` with `#btn-organize` ("Organize", variant success), `#btn-dry` ("Dry run", primary), `#btn-rescan` ("Rescan", warning) and `#btn-undo` ("Undo last run", default), and a `NavHint`.
  - Right: `#scan-box` with a progress bar and label while scanning, then the `#shots` Tree (a `ShotTree(Tree)` subclass whose ← binds to `screen.focus_filters`).
  - `#summary` Static at the bottom.
- `BINDINGS`: space toggle (priority), `a` all, `n` none, `o` organize, `y` dry run, `r` rescan, `z` undo, `f` flavors, `t` tools, `q` quit, ← filters, → tree, `*NAV_BINDINGS`.
- Scanning: `action_rescan` reloads the settings, then runs a thread worker that calls `scan(self.flavors, settings.dest_dir, progress)` through `call_from_thread`, then calls `_scanned(plan)`. `self.unchecked` is reset, because a new scan means new items.
- Tree (built in `_rebuild`):
  - The root label is `scope_label`.
  - One node per `FlavorPlan` (data `("flavor", fp)`), with year nodes `("year", fp, "2019")`, month nodes `("month", fp, "2019", "07")` and day nodes `("day", fp, date)`. A day node is added with `allow_expand=True`, and on `Tree.NodeExpanded`, if it has no children yet, its file leaves `("file", item)` are added.
  - Each label is `mark + name + "  N shots"`. For a file it is `mark + name`, plus `"  possible duplicate"` (dim) when its state is `MAYBE_DUPLICATE`.
  - Each flavor also gets a read-only `("conflicts", fp)` node (label `"Conflicts (n): a different file with the same name is already filed"`, children are file leaves without marks) and a read-only `("skipped", fp)` node (`"Skipped (n): name not recognised"`). Both are present only when n > 0.
  - Precompute `self._items_by_key: dict[tuple, list[ShotItem]]` for the flavor, year, month and day keys, so marks stay O(items) for each relabel.
- Ticks:
  - `self.unchecked: set[Path]` holds `item.src` values. `_mark()` works as in the cleaner (`CHECK_ON`, `CHECK_OFF`, `"◩ "`).
  - Toggling a conflicts or skipped node, or one of their leaves, does nothing.
  - Every toggle logs `ui.item_toggled` (screen `"shots_review"`).
  - `a` and `n` clear or fill `unchecked` from `plan.selectable`.
- Selection: `[i for i in plan.selectable if i.src not in self.unchecked]`.
- Summary text: `"Selected: N shots · D possible duplicates · C conflicts · S skipped (name not recognised)"`. When `plan.selectable` is empty, it is prefixed with `"Nothing to file."` and `#btn-organize` and `#btn-dry` are disabled. Plan warnings are appended as `"⚠ n folders could not be read (see the log)"`.
- Undo button: `disabled = latest_undoable(resolve_journal_dir(cfg.wow_path)) is None`. Refresh it on mount, after each scan, and after each run or undo.
- Organize and dry run:
  - If nothing is selected, `notify("Nothing is selected.")`.
  - Otherwise `title, body = confirm_text(...)`, then `ConfirmScreen(title, body, default_yes=dry_run)`. On yes: `app.busy = True`, push `ShotProgressScreen(title_for_stage)`, and run a thread worker that calls `execute(selection, dest_dir=..., copy=settings.copy_mode, dry_run=..., journal_dir=resolve_journal_dir(cfg.wow_path), keep_journals=..., progress=...)`.
  - On `OrganizeError`: `notify(f"{exc} What was done is in the journal; use Undo last run (z) to put it back.", severity="error", timeout=20)`, then show `ShotResultScreen(exc.result)`.
  - On success: pop the progress screen and push `ShotResultScreen(result)`.
  - Log `ui.selection` (screen `"shots_review"`, control `"organize"` or `"dry_run"`) and the confirm answer, as the cleaner does.
- Undo:
  - `path = latest_undoable(...)`. If None, `notify("Nothing to undo.")`.
  - Otherwise `journal = read_journal(path)` and `ConfirmScreen("Undo the last run?", f"Run from {journal.started}: {len(journal.entries)} files. Moved files go back to their Screenshots folders, copies are removed, removed duplicates are restored. Anything that changed since is left alone.", default_yes=False)`.
  - On yes, run a worker that calls `undo(path, wow_root=cfg.wow_path, progress=...)`, then show `ShotResultScreen`.
- After the result: `"flavors"`, `"tools"` and `"quit"` dismiss the review screen with that value. `"review"` (or Esc) rescans.

**`ShotProgressScreen(stage_titles=STAGE_TITLES, dry_run=False)`**
- Same layout as the cleaner's `CleanProgressScreen`: `#shots-stage`, `#shots-progress`, `#shots-file`.
- `update_progress(stage, current, total, detail)`. The title becomes "Simulating" for organize when `dry_run`.

**`ShotResultScreen(result: OrganizeResult)`**
- Same layout as the cleaner's `ResultScreen`: `#result-summary` (`summary_rows`) and `#result-files` (`RESULT_COLUMNS`, `result_rows`), with the outcome cell coloured: success for moved, copied, restored and copy removed; accent for the would-* kinds; warning for conflict, skipped, source left, already filed and undo skipped; error for failed and refused.
- Buttons: `#review` "Rescan (r)", `#flavors` "Other flavor (f)", `#tools` "Tools (t)", `#quit` "Quit (q)", with the matching bindings, and Esc for review.
- `sub_title`: `"Screenshot Organizer · result"`, `"· dry run result"` or `"· undo result"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_screenshot_organizer_report.py`: build an `OrganizeResult` by hand and check `summary_rows` (Mode row, one row per non-zero kind, the Journal row for a dry run says "not written (dry run)"), `result_rows`, `destination_label(None)` and `destination_label(Path("/x"))`, and that `KIND_LABELS` covers every kind constant in `organizer`:
```python
import unittest
from pathlib import Path

from wowtools.tools.screenshot_organizer import organizer
from wowtools.tools.screenshot_organizer.organizer import MOVED, CONFLICT_KEPT, WOULD_MOVE, OrganizeResult, Outcome
from wowtools.tools.screenshot_organizer.report import KIND_LABELS, destination_label, result_rows, summary_rows

KINDS = [v for k, v in vars(organizer).items() if k.isupper() and isinstance(v, str)
         and k not in ("PARTIAL",)]


class ReportTest(unittest.TestCase):
    def test_every_kind_has_a_label(self):
        for kind in KINDS:
            self.assertIn(kind, KIND_LABELS)

    def test_summary_and_rows(self):
        src = Path("/w/_retail_/Screenshots/WoWScrnShot_073119_232713.jpg")
        dst = Path("/a/_retail_/2019/07/31/WoWScrnShot_073119_232713.jpg")
        result = OrganizeResult(False, False, [Outcome("_retail_", src, dst, MOVED),
                                               Outcome("_retail_", src, dst, CONFLICT_KEPT, "different")],
                                journal_path=Path("/j/journal-x.jsonl"))
        rows = dict(summary_rows(result))
        self.assertEqual(rows["Mode"], "Move")
        self.assertEqual(rows[KIND_LABELS[MOVED]], "1")
        self.assertEqual(rows["Journal"], str(Path("/j/journal-x.jsonl")))
        self.assertEqual(result_rows(result)[1], (KIND_LABELS[CONFLICT_KEPT], "_retail_", src.name,
                                                  str(dst.parent), "different"))
        dry = OrganizeResult(True, False, [Outcome("_retail_", src, dst, WOULD_MOVE)])
        self.assertEqual(dict(summary_rows(dry))["Journal"], "not written (dry run)")

    def test_destination_label(self):
        self.assertIn("in place", destination_label(None))
        self.assertIn("YYYY", destination_label(Path("/arch")))
```
(Remove non-kind upper-case strings such as `CHUNK` from `KINDS` by checking `isinstance(v, str)`. `PARTIAL` is the only other string constant.)

`tests/test_screenshot_organizer_app.py` (based on `tests/test_wtf_app.py`'s `AppTestCase`):
```python
import tempfile
from pathlib import Path

from textual.widgets import Button, DataTable, Input, Tree

from tests.fixtures import TuiTestCase, build_screenshot_tree, build_wow_tree, make_config
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools.screenshot_organizer.app import ScreenshotSettingsScreen
from wowtools.tools.screenshot_organizer.journal import latest_undoable
from wowtools.tools.screenshot_organizer.review_screen import ShotResultScreen, ShotReviewScreen
from wowtools.tools.screenshot_organizer.settings import load_settings
from wowtools.tools.wtf_cleaner.review_screen import ConfirmScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp

SIZE = (140, 50)
A = "WoWScrnShot_073119_232713.jpg"


class ShotsAppTest(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.shots = self.root / "_retail_" / "Screenshots"
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        self.dest = self.tmp / "arch"

    def save_tool_cfg(self, **values):
        tool_cfg = Config(self.config_dir / "screenshot-organizer.cfg")
        for key, value in values.items():
            tool_cfg.set("screenshot_organizer", key, value, log=False)
        tool_cfg.save()

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=lambda: [])

    async def open_tool(self, app, pilot):
        await pilot.pause()
        self.assertIsInstance(app.screen, ToolMenuScreen)
        await pilot.press("down", "enter")  # second tool in the menu
        await pilot.pause()

    async def open_review(self, app, pilot):
        await self.open_tool(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")  # "All flavors" is highlighted by default
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        self.assertIsInstance(app.screen, ShotReviewScreen)
        return app.screen

    async def run_action(self, app, pilot, key, answer="y"):
        await pilot.press(key)
        await pilot.pause()
        self.assertIsInstance(app.screen, ConfirmScreen)
        await pilot.press(answer)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_first_open_asks_for_settings(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            self.assertIsInstance(app.screen, ScreenshotSettingsScreen)
            app.screen.query_one("#dest_dir", Input).value = str(self.dest)
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
        self.assertEqual(load_settings(Config(self.config_dir / "screenshot-organizer.cfg").load()).dest_dir, self.dest)

    async def test_settings_refuse_destination_inside_screenshots(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            app.screen.query_one("#dest_dir", Input).value = str(self.shots / "sorted")
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, ScreenshotSettingsScreen)
            self.assertIn("Screenshots", app.screen.error_text)

    async def test_all_flavors_organize_then_undo(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                self.assertEqual(len(review.plan.selectable), 6)
                self.assertTrue(review.query_one("#btn-undo", Button).disabled)
                await self.run_action(app, pilot, "o")
                self.assertIsInstance(app.screen, ShotResultScreen)
                self.assertEqual(app.screen.result.count("moved"), 6)
                await pilot.press("r")  # back to the review: rescans
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertIsInstance(app.screen, ShotReviewScreen)
                self.assertFalse(app.screen.query_one("#btn-undo", Button).disabled)
                await self.run_action(app, pilot, "z")
                self.assertIsInstance(app.screen, ShotResultScreen)
                self.assertTrue(app.screen.result.undo)
        self.assertTrue((self.shots / A).exists())
        self.assertIsNone(latest_undoable(self.root / "wow-tools" / "screenshot-organizer" / "journal"))
        names = [r["event"] for r in records]
        self.assertIn("shots.moved", names)
        self.assertIn("shots.undo_completed", names)

    async def test_dry_run_changes_nothing(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_action(app, pilot, "y")
            self.assertTrue(app.screen.result.dry_run)
            self.assertEqual(app.screen.result.count("would_move"), 6)
        self.assertFalse(self.dest.exists())
        self.assertTrue((self.shots / A).exists())

    async def test_unticking_a_day_excludes_it(self):
        self.save_tool_cfg()  # in place
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#shots", Tree)
            day = next(n for n in _walk(tree.root) if n.data and n.data[0] == "day"
                       and n.data[2].isoformat() == "2019-07-31")
            tree.focus()
            tree.move_cursor(day)
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(len(review.selection()), 4)
            await self.run_action(app, pilot, "o")
        self.assertTrue((self.shots / A).exists())
        self.assertTrue((self.shots / "2019" / "08" / "01" / "WoWScrnShot_080119_101010.PNG").exists())

    async def test_single_flavor_and_choice_remembered(self):
        self.save_tool_cfg()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            await pilot.press("down", "enter")  # first real flavor after "All flavors"
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            review = app.screen
            self.assertIsInstance(review, ShotReviewScreen)
            self.assertEqual(len(review.flavors), 1)
        saved = load_settings(Config(self.config_dir / "screenshot-organizer.cfg").load())
        self.assertEqual(saved.last_flavor_choice, review.flavors[0].folder)

    async def test_tools_key_returns_to_menu(self):
        self.save_tool_cfg()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("t")
            await pilot.pause()
            self.assertIsInstance(app.screen, ToolMenuScreen)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)
```
Expose `ShotReviewScreen.plan` (the last `Plan`, or None), `.flavors` and `.selection()`. Day node data is `("day", fp, date)`, so `n.data[2]` is the `date`.

- [ ] **Step 2: Run; expect `ModuleNotFoundError`**

Run: `python3 -m unittest tests.test_screenshot_organizer_report tests.test_screenshot_organizer_app -v`

- [ ] **Step 3: Implement** `report.py`, then `review_screen.py`, then `app.py`, following the behaviour above and the cleaner's code for layout and CSS. Register the tool in `wowtools/tools/__init__.py`. Add to `README.md` a tools-table row replacing "Coming later." with the description, and a `## Screenshot Organizer` section (expanded in Task 7).

- [ ] **Step 4: Run** the new tests, then `python3 scripts/run_tests.py`; expect all PASS. `tests/test_wtf_app.py` still opens the cleaner with Enter on the first menu row. If any existing test counts the menu's tools, update it to iterate over `TOOLS`.
- [ ] **Step 5: Smoke check** (manual, optional): `./wow-tools.sh` against a temp copy is not possible headless; rely on the pilot tests.
- [ ] **Step 6: Commit** with message `feat(screenshots): TUI (settings, all-flavor review tree, organize/dry run/undo, results) and menu entry`

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`, `docs/architecture.md`, `docs/adding-a-tool.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-10-03-screenshot-organizer-design.md`
- Regenerate: `docs/events.md`

- [ ] **Step 1: Regenerate events:** `python3 scripts/gen_event_docs.py`
- [ ] **Step 2: README**:
  - The tools-table row.
  - A `## Screenshot Organizer` section covering: what it does; both layouts (with `H:\Media\Screenshots\World of Warcraft\_retail_\2019\07\31\WoWScrnShot_073119_232713.jpg` as an example); the "All flavors" picker; the review tree and keys (`o`, `y`, `r`, `z`, `a`, `n`, Space, `f`, `t`, `q`); duplicates versus conflicts; copy mode; dry run; the journal folder `<WoW>\wow-tools\screenshots\journal`, undo and its rules; unrecognised names left alone; `config\screenshots.cfg` keys (`dest_dir`, `copy_mode`, `last_flavor_choice`, `keep_journals`); logs in `logs\screenshots\`.
  - Add `"config\\screenshot-organizer.cfg"`, `"Undo last run"` and `"journal"` to the needles in `tests/test_docs.py::test_readme_covers_the_entry_point_tools_and_safety`.
- [ ] **Step 3: `docs/architecture.md`**:
  - Config schema: add `config/screenshot-organizer.cfg` `[screenshot_organizer]` with its four keys.
  - A "Screenshot Organizer data flow" section: `scan → Plan → TUI selection → execute → OrganizeResult`, then `undo(journal) → OrganizeResult`. Cover the journal format, the guard rules, the no-per-file-stat rule, and undo's one-level rule.
  - The UI table: the `FlavorScreen` `include_all`, `last` and `flavors` params, and the screenshot screens.
- [ ] **Step 4: `docs/adding-a-tool.md`**: keep the walk-through, but make it match reality: events named `shots.*`, with a note that event names are global across tools so they need a tool prefix; `organizer.py` takes `ShotItem`s; module names as shipped.
- [ ] **Step 5: Spec**: fix §3 (add `undo.py`; `journal.py` no longer holds undo), §6.1 (the guard is an exact expected-path match with no resolve), and §8 (the `shots.` prefixed names, matching `events.py`).
- [ ] **Step 6: `CLAUDE.md`**: change the first lines to "Tools: WTF Cleaner, Screenshot Organizer". Spec and plan stay under `docs/superpowers/`.
- [ ] **Step 7: Run** `python3 scripts/run_tests.py`; expect PASS.
- [ ] **Step 8: Commit** with message `docs: Screenshot Organizer (README, architecture, adding-a-tool, events)`

---

## Milestones and pushes

- **M1** (Tasks 1–4, the logic): push `feat/screenshot-organizer`.
- **M2** (Tasks 5–6, the UI): push.
- **M3** (Task 7 plus the final whole-branch review fixes): push, then ask for the merge go-ahead. No merge or release without explicit approval.
