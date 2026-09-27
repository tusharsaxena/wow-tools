"""Human and machine renderings of proposals and clean results (shared by CLI and TUI)."""
from __future__ import annotations

import time

from wowtools.core.install import ACCOUNT_WIDE, Flavor
from wowtools.tools.wtf_cleaner.rules import Proposal

DAY = 86400.0

CRITERION_LABELS = {
    "not_installed": "Addon is not installed",
    "not_enabled": "Addon is installed but not enabled on any character",
    "older_than": "SavedVariables are older than the age limit",
    "stray_copies": "Hand-made copies (anything but <Addon>.lua / <Addon>.lua.bak)",
}
CRITERION_SHORT = {
    "not_installed": "Not installed",
    "not_enabled": "Not enabled",
    "older_than": "Older than max age",
    "stray_copies": "Stray copies",
}


def format_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def age_days(mtime: float, now: float) -> int:
    return max(0, int((now - mtime) // DAY))


def _sort_key(item) -> tuple:
    return (item.account.casefold(), item.owner_label != ACCOUNT_WIDE, item.owner_label.casefold(),
            item.addon.casefold())


def proposal_to_dict(proposal: Proposal, flavor: Flavor, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return {
        "flavor": flavor.folder,
        "criteria": proposal.criteria.enabled_names(),
        "max_age_days": proposal.criteria.max_age_days,
        "totals": {"items": len(proposal.items), "files": proposal.total_files, "bytes": proposal.total_size},
        "by_reason": proposal.by_reason(),
        "items": [{
            "account": item.account,
            "character": item.owner_label if item.character else None,
            "addon": item.addon,
            "scope": item.scope,
            "reasons": item.reasons,
            "bytes": item.total_size,
            "age_days": age_days(item.newest_mtime, now),
            "files": [{"path": str(f.path), "size": f.size, "mtime": f.mtime} for f in item.files],
        } for item in sorted(proposal.items, key=_sort_key)],
        "warnings": [str(w) for w in proposal.warnings],
    }


def format_proposal_text(proposal: Proposal, flavor: Flavor, now: float | None = None) -> str:
    now = time.time() if now is None else now
    lines = [f"WTF Cleaner · {flavor.display_name} ({flavor.folder})",
             f"Criteria: {proposal.criteria.describe()}", ""]
    if not proposal.items:
        lines.append("Nothing to clean.")
    heading = None
    for item in sorted(proposal.items, key=_sort_key):
        current = f"{item.account} · {item.owner_label}"
        if current != heading:
            lines.append(current)
            heading = current
        lines.append(f"  {item.addon:<32} {', '.join(item.reasons):<30} {len(item.files):>3} files "
                     f"{format_size(item.total_size):>9} {age_days(item.newest_mtime, now):>5}d")
    lines += ["", f"Total: {len(proposal.items)} items, {proposal.total_files} files, "
                  f"{format_size(proposal.total_size)}"]
    for warning in proposal.warnings:
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)
