"""Labels, colours and table rows for the WTF Cleaner screens."""
from __future__ import annotations


from wowtools.core.install import ACCOUNT_WIDE, Flavor, flavor_name
from wowtools.core.journal import friendly_stamp
from wowtools.core.text import human_size
from wowtools.tools.wtf_cleaner.rules import DAY
from wowtools.tools.wtf_cleaner.scanner import addon_name_for

# The USE AT YOUR OWN RISK popup's text (ui.disclaimer, L4), shown before the first scan of a session.
DISCLAIMER = ("This tool deletes addon settings files (SavedVariables) from your WTF folder. It goes by the rules you "
              "tick and can't know what an addon still needs; a deleted file takes that addon's settings with it. A "
              "backup zip of the WTF folder is made first and Undo puts the files back, but you are responsible for "
              "what you clean."
              "\n\nClose WoW before you clean: it rewrites the WTF folder when you log out and can bring back what "
              "you removed. Every Clean and Undo asks again.")

CRITERION_LABELS = {
    "not_installed": "Addon is not installed",
    "not_enabled": "Addon is installed but not enabled on any character of its account",
    "older_than": "SavedVariables are older than the age limit",
    "stray_copies": "Hand-made copies (anything but <Addon>.lua / <Addon>.lua.bak)",
    "orphan_backups": "<Addon>.lua.bak with no <Addon>.lua next to it",
}
CRITERION_SHORT = {
    "not_installed": "Not installed",
    "not_enabled": "Not enabled",
    "older_than": "Older than max age",
    "stray_copies": "Stray copies",
    "orphan_backups": "Orphan backups",
}

CRITERION_COLORS = {
    "not_installed": "#E5534B",
    "not_enabled": "#F08C3A",
    "older_than": "#E8C547",
    "stray_copies": "#B07CFF",
    "orphan_backups": "#5CC46A",
}


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
    "undo": "Undoing the last clean",
}

# Reasons (why each file goes) before Size and File: at 120x30 a long file name ends at the window's edge, not them.
RESULT_COLUMNS = ("Status", "Account", "Character", "Addon", "Reasons", "Size", "File")
MULTI_RESULT_COLUMNS = ("Status", "Flavor", *RESULT_COLUMNS[1:])  # a clean across several flavors
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


def outcome_row(outcome, flavor: Flavor) -> tuple[str, ...]:
    """One outcome in RESULT_COLUMNS order. Skipped and failed rows carry their reason in Status."""
    status = STATUS_LABELS.get(outcome.status, outcome.status)
    if outcome.detail:
        status = f"{status}: {outcome.detail}"
    account, character = _owner(outcome.path, flavor)
    return (status, account, character, addon_name_for(outcome.path.name) or "", ", ".join(outcome.reasons),
            human_size(outcome.size), outcome.path.name)


def result_rows(result, flavor: Flavor) -> list[tuple[str, ...]]:
    """One row per outcome of a one-flavor result, in RESULT_COLUMNS order."""
    return [outcome_row(outcome, flavor) for outcome in result.outcomes]


def multi_result_rows(result) -> list[tuple[str, ...]]:
    """One row per outcome of a MultiCleanResult, in MULTI_RESULT_COLUMNS order (the flavor after the status)."""
    rows = []
    for flavor, outcome in result.outcomes:
        status, *rest = outcome_row(outcome, flavor)
        rows.append((status, flavor.display_name, *rest))
    return rows


UNDO_COLUMNS = ("Status", "Flavor", "Account", "Character", "Addon", "File", "Size", "Restored from")
UNDO_STATUS_LABELS = {"restored": "Restored", "skipped": "Skipped", "failed": "Failed"}
UNDO_SOURCES = {"zip": "cleaned-files zip", "backup": "WTF backup", "": ""}


def undo_row(outcome) -> tuple[str, ...]:
    """One UndoOutcome in UNDO_COLUMNS order. Skipped and failed rows carry their reason in Status."""
    status = UNDO_STATUS_LABELS.get(outcome.status, outcome.status)
    if outcome.detail:
        status = f"{status}: {outcome.detail}"
    parts = outcome.rel.split("/")  # WTF/Account/<account>/[<realm>/<character>/]SavedVariables/<file>
    account = parts[2] if len(parts) > 3 and parts[1] == "Account" else ""
    character = f"{parts[3]}/{parts[4]}" if account and len(parts) >= 7 else (ACCOUNT_WIDE if account else "")
    name = parts[-1]
    return (status, flavor_name(outcome.flavor), account, character, addon_name_for(name) or "", name,
            human_size(max(0, outcome.size)), UNDO_SOURCES.get(outcome.source, outcome.source))


def undo_summary_rows(result) -> list[tuple[str, str]]:
    flavors = ", ".join(flavor_name(f) for f in result.flavors) or "unknown"
    return [
        ("Mode", "Undo last clean"),
        ("Clean undone", f"{friendly_stamp(result.started)} ({flavors})"),
        ("Journal", str(result.journal_path)),
        ("Restored", f"{len(result.restored)} files"),
        ("Skipped", f"{len(result.skipped)} files (back at their path, or outside the WTF folder)"),
        ("Failed", f"{len(result.failed)} files"),
    ]
