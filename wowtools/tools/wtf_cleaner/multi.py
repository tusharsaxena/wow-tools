"""Scan and clean several flavors one after another (All flavors). Each flavor goes through the unchanged
per-flavor scan() and execute(); this module only runs them in turn and collects what happened."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from wowtools.core.backup import BackupError
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor
from wowtools.tools.wtf_cleaner.cleaner import CleanError, CleanProgress, CleanResult, FileOutcome, execute
from wowtools.tools.wtf_cleaner.rules import ProposalItem
from wowtools.tools.wtf_cleaner.safety import DEFAULT_KEEP_SNAPSHOTS
from wowtools.tools.wtf_cleaner.scanner import ScanError, ScanProgress, ScanResult, scan


@dataclass
class FlavorScan:
    """One flavor's scan: its result, or why it could not be scanned (it is then not cleaned)."""
    flavor: Flavor
    result: ScanResult | None = None
    error: str | None = None


def scan_flavors(flavors: list[Flavor], *, account: str | None = None,
                 progress: ScanProgress | None = None) -> list[FlavorScan]:
    """Scan each flavor in turn. A ScanError is recorded for that flavor and the others carry on. With more than
    one flavor, the progress label starts with the flavor's name."""
    named = len(flavors) > 1
    scans: list[FlavorScan] = []
    for flavor in flavors:
        def report(current: int, total: int, label: str, flavor: Flavor = flavor) -> None:
            if progress is not None:
                progress(current, total, f"{flavor.display_name} · {label}" if named else label)

        try:
            scans.append(FlavorScan(flavor, scan(flavor, account=account, progress=report)))
        except ScanError as exc:
            log_exception("scan", exc)
            scans.append(FlavorScan(flavor, error=str(exc)))
    return scans


@dataclass
class FlavorRun:
    flavor: Flavor
    items: list[ProposalItem]
    result: CleanResult | None = None
    error: Exception | None = None  # the BackupError or CleanError that stopped this flavor

    @property
    def status(self) -> str:
        if self.result is not None:
            return "done"
        return "stopped" if self.error is not None else "not_started"


@dataclass
class MultiCleanResult:
    """A clean or dry run over several flavors. Counts add up the flavors that finished."""
    dry_run: bool
    runs: list[FlavorRun] = field(default_factory=list)

    @property
    def done(self) -> list[FlavorRun]:
        return [r for r in self.runs if r.status == "done"]

    @property
    def stopped(self) -> FlavorRun | None:
        return next((r for r in self.runs if r.status == "stopped"), None)

    @property
    def not_started(self) -> list[FlavorRun]:
        return [r for r in self.runs if r.status == "not_started"]

    @property
    def outcomes(self) -> list[tuple[Flavor, FileOutcome]]:
        return [(r.flavor, o) for r in self.done for o in r.result.outcomes]  # type: ignore[union-attr]

    def _with(self, status: str) -> list[FileOutcome]:
        return [o for _, o in self.outcomes if o.status == status]

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
        return sum(r.result.bytes_freed for r in self.done)  # type: ignore[union-attr]


def execute_flavors(plan: list[tuple[Flavor, list[ProposalItem]]], *, dry_run: bool, backup: bool,
                    backup_dir: Path | None, account: str | None = None,
                    keep_backups: int = DEFAULT_KEEP_SNAPSHOTS, progress: CleanProgress | None = None,
                    on_flavor: Callable[[Flavor, int, int], None] | None = None) -> MultiCleanResult:
    """Run execute() for each (flavor, selection) in turn. A BackupError or CleanError stops the run before the
    next flavor starts; flavors already done keep their results. Any other exception propagates (execute() has
    already restored what it deleted)."""
    result = MultiCleanResult(dry_run, [FlavorRun(flavor, items) for flavor, items in plan])
    for index, run in enumerate(result.runs):
        if on_flavor is not None:
            on_flavor(run.flavor, index, len(result.runs))
        try:
            run.result = execute(run.items, run.flavor, dry_run=dry_run, backup=backup, backup_dir=backup_dir,
                                 progress=progress, account=account, keep_backups=keep_backups)
        except (BackupError, CleanError) as exc:
            run.error = exc
            if len(result.runs) > 1:
                log_event("clean.flavors_stopped", dry_run=dry_run, flavor=run.flavor.folder, error=str(exc),
                          done=[r.flavor.folder for r in result.done],
                          not_started=[r.flavor.folder for r in result.not_started])
            break
    return result


def nothing_deleted(error: BaseException | None) -> bool:
    """True when a stopped flavor run left nothing deleted: a BackupError, or a CleanError that was a refusal or
    whose deleted files were all restored. False when files were deleted and restoring them failed."""
    return not getattr(error, "files_missing", False)
