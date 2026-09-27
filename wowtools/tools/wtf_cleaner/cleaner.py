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
