"""Scan and clean several flavors (All flavors). Each flavor goes through the unchanged per-flavor scan() and
execute(); this module only runs them and collects what happened. Scans run up to [general] parallelism at once
(core/parallel.py); a clean runs the flavors one after another, never in parallel: every flavor shares the one crash
marker in the backup folder (clean-in-progress.json, which the recovery screen reads as one pointer) and the run
stops at the first flavor whose backup or clean fails (the others are "not started")."""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools import __version__
from wowtools.core.backup import BackupError
from wowtools.core.config import DEFAULT_KEEP_BACKUPS, DEFAULT_KEEP_JOURNALS
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor
from wowtools.core.journal import new_journal_path
from wowtools.core.parallel import run_units, workers_for
from wowtools.core.paths import to_stored
from wowtools.tools.wtf_cleaner.cleaner import CleanError, CleanProgress, CleanResult, FileOutcome, execute
from wowtools.tools.wtf_cleaner.events import TOOL_NAME
from wowtools.tools.wtf_cleaner.journal import CleanJournal, prune_journals
from wowtools.tools.wtf_cleaner.rules import ProposalItem
from wowtools.tools.wtf_cleaner.scanner import ScanError, ScanProgress, ScanResult, scan


@dataclass
class FlavorScan:
    """One flavor's scan: its result, or why it could not be scanned (it is then not cleaned)."""
    flavor: Flavor
    result: ScanResult | None = None
    error: str | None = None
    note: str | None = None  # the error in a few words, for the review tree (ScanError.short)


def scan_flavors(flavors: list[Flavor], *, account: str | None = None,
                 progress: ScanProgress | None = None, parallelism: int = 1) -> list[FlavorScan]:
    """Scan each flavor, up to `parallelism` at once ([general] parallelism: a scan only reads, and each flavor's
    is its own). A ScanError is recorded for that flavor and the others carry on; any other error stops the
    flavors not started yet and is raised once the running ones ended. The scans come back in the order of
    `flavors`. With more than one flavor, the progress label starts with the flavor's name; with more than one
    running at once, the counts are every running flavor's added up (one bar), reported under a lock."""
    named = len(flavors) > 1
    combined = workers_for(parallelism, len(flavors)) > 1
    lock = threading.Lock()
    counts: dict[str, tuple[int, int]] = {}  # flavor folder -> (current, total), when combined

    def one(flavor: Flavor, _report: Callable[..., None]) -> FlavorScan:
        def report(current: int, total: int, label: str) -> None:
            if progress is None:
                return
            text = f"{flavor.display_name} · {label}" if named else label
            if not combined:
                progress(current, total, text)
                return
            with lock:
                counts[flavor.folder] = (current, total)
                progress(sum(c for c, _ in counts.values()), sum(t for _, t in counts.values()), text)

        try:
            return FlavorScan(flavor, scan(flavor, account=account, progress=report))
        except ScanError as exc:
            log_exception("scan", exc)
            return FlavorScan(flavor, error=str(exc), note=exc.short)

    results = run_units(flavors, one, parallelism=parallelism, what="scan", label=lambda flavor: flavor.folder,
                        stop_on_error=True)
    for result in results:
        if result.error is not None:
            raise result.error
    return [result.value for result in results if result.value is not None]


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
    journal_path: Path | None = None  # the run journal (a real clean that deleted something)
    journals_pruned: list[Path] = field(default_factory=list)  # older journals removed to keep the newest N

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
                    keep_backups: int = DEFAULT_KEEP_BACKUPS, progress: CleanProgress | None = None,
                    on_flavor: Callable[[Flavor, int, int], None] | None = None, journal_dir: Path | None = None,
                    keep_journals: int = DEFAULT_KEEP_JOURNALS, keep_cleaned: int = 0) -> MultiCleanResult:
    """Run execute() for each (flavor, selection) in turn (never in parallel: see the module docstring). A BackupError or CleanError stops the run before the
    next flavor starts; flavors already done keep their results. Any other exception propagates (execute() has
    already restored what it deleted).

    A real clean with a journal_dir writes one run journal for all the flavors (removed again if nothing was
    deleted), then keeps the newest keep_journals journals. keep_cleaned goes to execute() (cleaned-files zips kept
    per flavor, 0 = all)."""
    result = MultiCleanResult(dry_run, [FlavorRun(flavor, items) for flavor, items in plan])
    journal = None
    if not dry_run and journal_dir is not None:
        journal = CleanJournal(new_journal_path(journal_dir), {
            "tool": TOOL_NAME, "suite_version": __version__, "flavors": [flavor.folder for flavor, _ in plan],
            "account": account, "backup_dir": to_stored(backup_dir) if backup_dir else None})
    completed = False
    try:
        for index, run in enumerate(result.runs):
            if on_flavor is not None:
                on_flavor(run.flavor, index, len(result.runs))
            try:
                run.result = execute(run.items, run.flavor, dry_run=dry_run, backup=backup, backup_dir=backup_dir,
                                     progress=progress, account=account, keep_backups=keep_backups,
                                     journal=journal, keep_cleaned=keep_cleaned)
            except (BackupError, CleanError) as exc:
                run.error = exc
                if len(result.runs) > 1:
                    log_event("clean.flavors_stopped", dry_run=dry_run, flavor=run.flavor.folder, error=str(exc),
                              done=[r.flavor.folder for r in result.done],
                              not_started=[r.flavor.folder for r in result.not_started])
                break
        completed = True
    finally:
        if journal is not None:
            if completed:
                try:
                    journal.finish()
                except OSError:
                    pass  # the entries are already on disk; only the closing line is missing
            journal.discard_if_empty()
    if journal is not None and journal.opened:
        result.journal_path = journal.path
        for run in result.done:
            run.result.journal_path = journal.path  # type: ignore[union-attr]
        result.journals_pruned = prune_journals(journal_dir, keep_journals)
    return result


def nothing_deleted(error: BaseException | None) -> bool:
    """True when a stopped flavor run left nothing deleted: a BackupError, or a CleanError that was a refusal or
    whose deleted files were all restored. False when files were deleted and restoring them failed."""
    return not getattr(error, "files_missing", False)
