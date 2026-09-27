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


def evaluate(scan: ScanResult, criteria: Criteria, *, now: float | None = None, log: bool = True) -> Proposal:
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
    if not log:
        return proposal
    log_event("proposal.built", flavor=scan.flavor.folder, criteria=criteria.enabled_names(),
              max_age_days=criteria.max_age_days, items=len(items), files=proposal.total_files,
              bytes=proposal.total_size, by_reason=proposal.by_reason())
    for item in items:
        log_event("proposal.item", account=item.account, character=item.owner_label, addon=item.addon,
                  reasons=item.reasons, files=[f.name for f in item.files])
    return proposal


def criterion_counts(scan: ScanResult, *, max_age_days: int, now: float | None = None) -> dict[str, int]:
    """The number of files each criterion would propose on its own (no proposal.* events)."""
    now = time.time() if now is None else now
    return {name: evaluate(scan, Criteria.from_names([name], max_age_days=max_age_days), now=now,
                           log=False).total_files
            for name in CRITERIA}
