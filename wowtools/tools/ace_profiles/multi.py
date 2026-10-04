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
                  stopped=result.stopped.flavor.folder if result.stopped else None,
                  level="warning" if result.skipped or result.failed or result.stopped else None)
    return result
