"""Labels, colours and table rows for the WTF Cleaner screens."""
from __future__ import annotations

from wowtools.core.install import ACCOUNT_WIDE, Flavor
from wowtools.tools.wtf_cleaner.scanner import addon_name_for

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

CRITERION_COLORS = {
    "not_installed": "#E5534B",
    "not_enabled": "#F08C3A",
    "older_than": "#E8C547",
    "stray_copies": "#B07CFF",
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


def locker_warning(running: list[str]) -> str:
    """The confirm-time warning when a program known to lock WTF files is running (real cleans only)."""
    return (f"{', '.join(running)} appears to be running. It can lock SavedVariables files, and then the clean "
            "stops before deleting anything. Close it first.")


# What each execute() progress stage is called in the progress popup, in order.
STAGE_TITLES = {
    "check": "Checking selected files",
    "lock_check": "Checking for locked files",
    "snapshot_list": "Listing the WTF folder",
    "snapshot": "Backing up the WTF folder",
    "snapshot_verify": "Verifying the WTF backup",
    "backup": "Zipping the files to clean",
    "verify": "Verifying the cleaned-files zip",
    "delete": "Deleting",
    "validate": "Checking the result against the WTF backup",
}

RESULT_COLUMNS = ("Status", "Account", "Character", "Addon", "File", "Size", "Reasons")
STATUS_LABELS = {"deleted": "Deleted", "would_delete": "Would delete", "skipped": "Skipped", "failed": "Failed"}


def _owner(path, flavor: Flavor) -> tuple[str, str]:
    """(account, character label) for a SavedVariables file under the flavor's WTF/Account folder."""
    try:
        parts = path.relative_to(flavor.account_dir).parts
    except ValueError:
        return "", ""
    account = parts[0] if parts else ""
    if len(parts) >= 5:  # <account>/<realm>/<character>/SavedVariables/<file>
        return account, f"{parts[1]}/{parts[2]}"
    return account, ACCOUNT_WIDE


def result_rows(result, flavor: Flavor) -> list[tuple[str, ...]]:
    """One row per outcome, in RESULT_COLUMNS order. Skipped and failed rows carry their reason in Status."""
    rows = []
    for outcome in result.outcomes:
        status = STATUS_LABELS.get(outcome.status, outcome.status)
        if outcome.detail:
            status = f"{status}: {outcome.detail}"
        account, character = _owner(outcome.path, flavor)
        rows.append((status, account, character, addon_name_for(outcome.path.name) or "", outcome.path.name,
                     format_size(outcome.size), ", ".join(outcome.reasons)))
    return rows
