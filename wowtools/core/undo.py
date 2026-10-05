"""What the tools that put files back after a run share (the WTF Cleaner's and the Ace3 Profile Manager's Undo):
the outcome statuses, the restored / skipped / failed lists of a result, and the guard that keeps a journal or
marker entry from pointing outside a flavor's WTF folder. UI-free."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

RESTORED = "restored"
SKIPPED = "skipped"
FAILED = "failed"


class UndoResultBase:
    """Mixin for an undo result dataclass with `outcomes` (each with a `status`): the outcomes by status."""

    outcomes: list[Any]

    def _with(self, status: str) -> list[Any]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def restored(self) -> list[Any]:
        return self._with(RESTORED)

    @property
    def skipped(self) -> list[Any]:
        return self._with(SKIPPED)

    @property
    def failed(self) -> list[Any]:
        return self._with(FAILED)


def safe_destination(wow_root: Path, flavor: str, rel: str, *, prefix: tuple[str, ...] = ("WTF",),
                     min_parts: int = 2, parent: str | None = None) -> Path | None:
    """<WoW>/<flavor>/<rel>, or None when the entry could point anywhere else: flavor must be one plain folder
    name, and rel a relative POSIX path with no "..", backslash or colon that starts with `prefix`, has at least
    `min_parts` parts and, with `parent`, sits directly in a folder of that name."""
    if not flavor or flavor in (".", "..") or any(c in flavor for c in "/\\:"):
        return None
    posix = PurePosixPath(rel)
    parts = posix.parts
    if posix.is_absolute() or ".." in parts or "\\" in rel or ":" in rel:
        return None
    if len(parts) < max(min_parts, len(prefix) + 1) or parts[:len(prefix)] != prefix:
        return None
    if parent is not None and parts[-2] != parent:
        return None
    return wow_root.joinpath(flavor, *parts)
