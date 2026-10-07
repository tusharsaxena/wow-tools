"""Turn scan results into a cleanup proposal using the five toggleable criteria."""
from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from wowtools.core.events import log_event
from wowtools.core.install import Character
from wowtools.tools.wtf_cleaner.scanner import ScanResult, ScanWarning, SVFile, SVGroup

CRITERIA = ("not_installed", "not_enabled", "older_than", "stray_copies", "orphan_backups")
DAY = 86400.0


@dataclass
class Criteria:
    not_installed: bool = True
    not_enabled: bool = True
    older_than: bool = True
    stray_copies: bool = True
    orphan_backups: bool = True
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
    if criteria.not_enabled and key in scan.installed and key not in scan.enabled_for(group.account):
        reasons.append("not_enabled")
    if criteria.older_than and now - group.newest_mtime > criteria.max_age_days * DAY:
        reasons.append("older_than")
    return reasons


def orphan_backups(group: SVGroup) -> list[SVFile]:
    """The group's <Addon>.lua.bak when there is no <Addon>.lua next to it (names in any case). A .lua the scan saw
    but could not list (renamed by an interrupted lock check, or unreadable) still counts as there."""
    main = f"{group.addon}.lua".casefold()
    if group.main_hidden or any(f.name.casefold() == main for f in group.files):
        return []
    return [f for f in group.files if f.canonical]


def evaluate(scan: ScanResult, criteria: Criteria, *, now: float | None = None, log: bool = True) -> Proposal:
    """Each group whose addon matches a criterion is proposed whole (its .lua.bak and stray copies with it); a
    group that matches none still proposes its stray copies and its orphan backup when those criteria are on."""
    now = time.time() if now is None else now
    items: list[ProposalItem] = []
    for group in scan.groups:
        reasons = _group_reasons(group, scan, criteria, now)
        extra = [("stray_copies", [f for f in group.files if not f.canonical]),
                 ("orphan_backups", orphan_backups(group))]
        extra = [(name, files) for name, files in extra if getattr(criteria, name) and files]
        if reasons:
            reasons += [name for name, _ in extra]
            items.append(ProposalItem(group, list(group.files), reasons))
        elif extra:
            files = {f.path: f for _, found in extra for f in found}
            items.append(ProposalItem(group, [f for f in group.files if f.path in files], [n for n, _ in extra]))
    proposal = Proposal(items, criteria.copy(), list(scan.warnings))
    if log:
        log_proposal_built(proposal, scan.flavor.folder)
        log_proposal_items(items)
    return proposal


def log_proposal_built(proposal: Proposal, flavor_folder: str) -> None:
    """One proposal.built summary (counts, per-reason totals) for a flavor's proposal."""
    criteria = proposal.criteria
    log_event("proposal.built", flavor=flavor_folder, criteria=criteria.enabled_names(),
              max_age_days=criteria.max_age_days, items=len(proposal.items), files=proposal.total_files,
              bytes=proposal.total_size, by_reason=proposal.by_reason())


def log_proposal_items(items: list[ProposalItem], *, dry_run: bool | None = None) -> None:
    """One proposal.item per addon group. The review screen logs these only for a run the user confirmed."""
    for item in items:
        log_event("proposal.item", dry_run=dry_run, account=item.account, character=item.owner_label,
                  addon=item.addon, reasons=item.reasons, files=[f.name for f in item.files])


def criterion_counts(scan: ScanResult, *, max_age_days: int, now: float | None = None) -> dict[str, int]:
    """The number of files each criterion would propose on its own (no proposal.* events)."""
    now = time.time() if now is None else now
    return {name: evaluate(scan, Criteria.from_names([name], max_age_days=max_age_days), now=now,
                           log=False).total_files
            for name in CRITERIA}
