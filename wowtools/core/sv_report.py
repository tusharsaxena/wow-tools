"""Text for the screens of a tool on the SavedVariables write pipeline (core/sv_apply.py, sv_undo.py): progress
stage titles, the Undo confirm, the unfinished-run warning and the apply / undo result rows. UI-free."""
from __future__ import annotations

from pathlib import Path

from wowtools.core.install import flavor_name
from wowtools.core.journal import Journal, friendly_stamp
from wowtools.core.paths import to_stored
from wowtools.core.sv_apply import Marker, MultiApplyResult
from wowtools.core.sv_undo import UndoResult
from wowtools.core.text import plural

STAGE_TITLES = {
    "check": "Checking the files", "lock_check": "Checking for locked files",
    "snapshot_list": "Listing the WTF folder", "snapshot": "Backing up the WTF folder",
    "snapshot_verify": "Checking the WTF backup", "backup": "Saving the original files",
    "edit": "Writing the changes", "undo": "Putting files back",
}
DETAIL_COLUMNS = ("Flavor", "Account", "Addon", "Change", "Result")
UNDO_COLUMNS = ("Flavor", "File", "Result")
# Theme colour of a result's detail row (its last cell), by the status's first words (RESULT_TEXT and the undo
# statuses): ui.result_screen.ResultScreen.STATUS_COLOURS of every tool on this pipeline.
STATUS_COLOURS = (("would change", "accent"), ("changed", "success"), ("restored", "success"),
                  ("put back", "warning"), ("skipped", "warning"), ("failed", "error"))
# A run that finished but whose crash marker could not be removed (sv_apply marker_left), and recovery finding such a
# marker (sv_undo marker_stale): nothing is put back then.
MARKER_LEFT_TEXT = ("could not be removed (another program held it). The next scan offers this change as unfinished; "
                    "Put the originals back then only removes the marker.")
STALE_MARKER_TEXT = "only its leftover marker was removed. No file was changed, and Undo still offers it."
STALE_KEPT_TEXT = "No file was changed, and Undo still offers it."
# Recovery or Leave as is could not remove the marker either (sv_undo marker_left): the next scan offers it again.
MARKER_STILL_TEXT = ("Its crash marker could not be removed (another program held it), so the next scan offers this "
                     "change again.")
RESULT_TEXT = {"edited": "changed", "would_edit": "would change", "skipped": "skipped", "failed": "failed",
               "rolled_back": "put back"}


def undo_confirm(journal: Journal) -> tuple[str, str, list[str]]:
    files = len(journal.entries)
    folders = sorted({e["flavor"] for e in journal.entries})
    where = f" in {', '.join(flavor_name(f) for f in folders)}" if folders else ""
    body = (f"Put back {plural(files, 'file')} changed{where} {friendly_stamp(journal.started)}. A file saved "
            f"since (by WoW) is left as it is.")
    return "Undo the last change?", body, []


def recovery_text(marker: Marker) -> str:
    """The body of the unfinished-run warning (ui.dialogs.UnfinishedRunScreen): which run, its zip, both choices."""
    return "\n".join([
        (f"A change to {flavor_name(marker.flavor)} started {friendly_stamp(marker.started)} did not finish "
         f"({plural(len(marker.files), 'file')})."),
        "The original files are in:",
        str(marker.zip),
        ("Put the originals back: each file the change wrote is restored from that zip; a file saved since "
         "(by WoW) is left as it is."),
        "Leave as is: the files stay as they are now; the zip and the WTF backup are kept.",
    ])


def apply_summary_rows(result: MultiApplyResult) -> list[tuple[str, str]]:
    verb = "Would change" if result.dry_run else "Changed"
    rows = [(f"{verb}", plural(len(result.would_edit if result.dry_run else result.edited), "file"))]
    if result.skipped:
        rows.append(("Skipped", plural(len(result.skipped), "file")))
    if result.rolled_back:
        rows.append(("Put back after a failure", plural(len(result.rolled_back), "file")))
    if result.failed:
        rows.append(("Failed", plural(len(result.failed), "file")))
    if result.stopped:
        rows.append(("Stopped", f"{flavor_name(result.stopped.flavor.folder)}: {result.stopped.error}"))
    if result.marker_left:
        rows.append(("Crash marker", MARKER_LEFT_TEXT))
    zips = [(f"{label} ({flavor_name(run.flavor.folder)})", path) for run in result.runs if run.result is not None
            for label, path in (("WTF backup", run.result.snapshot), ("Original files", run.result.backup_zip))
            if path is not None]
    files = zips + ([("Journal", result.journal_path)] if result.journal_path is not None else [])
    return rows + in_backup_folder(files, [path for _, path in zips])


def in_backup_folder(files: list[tuple[str, Path]], zips: list[Path]) -> list[tuple[str, str]]:
    """Result rows naming `files` inside the backup folder (the folder above the first zip's snapshots/ or edited/),
    which gets a row of its own in front of them: a whole path does not fit at 120x30. A file elsewhere keeps its
    whole path."""
    if not zips:
        return [(item, to_stored(path)) for item, path in files]
    folder = zips[0].parent.parent
    rows = [("Backup folder", to_stored(folder))]
    for item, path in files:
        rows.append((item, str(path.relative_to(folder)) if path.is_relative_to(folder) else to_stored(path)))
    return rows


def apply_detail_rows(result: MultiApplyResult) -> list[tuple[str, str, str, str, str]]:
    """One row per change (DETAIL_COLUMNS): flavor, account, addon, the change and what became of its file."""
    rows = []
    for outcome in result.outcomes:
        file = outcome.file
        state = RESULT_TEXT.get(outcome.status, outcome.status)
        if outcome.detail:
            state += f": {outcome.detail}"
        for change in outcome.changes or [""]:
            rows.append((flavor_name(file.flavor.folder), file.account, file.addon, change, state))
    return rows


def undo_summary_rows(result: UndoResult) -> list[tuple[str, str]]:
    if result.stale_marker:
        if result.marker_left:
            return [("Already finished", STALE_KEPT_TEXT), ("Crash marker", MARKER_STILL_TEXT)]
        return [("Already finished", STALE_MARKER_TEXT)]
    rows = [("Put back", plural(len(result.restored), "file"))]
    if result.skipped:
        rows.append(("Left as they are", plural(len(result.skipped), "file")))
    if result.failed:
        rows.append(("Failed", plural(len(result.failed), "file")))
    return rows + in_backup_folder([("WTF backup", p) for p in result.snapshots], result.snapshots)


def recovered_notice(result: UndoResult) -> tuple[str, str]:
    """The notice after putting the originals back: (message, severity)."""
    if result.stale_marker:
        if result.marker_left:
            return f"That change had finished. {STALE_KEPT_TEXT} {MARKER_STILL_TEXT}", "warning"
        return f"That change had finished: {STALE_MARKER_TEXT}", "information"
    message = (f"Put back {plural(len(result.restored), 'file')}; left {plural(len(result.skipped), 'file')} "
               f"as they are")
    if result.failed:
        message += f"; {plural(len(result.failed), 'file')} could not be put back (see the log)"
    if result.marker_left:
        return f"{message}. {MARKER_STILL_TEXT}", "error" if result.failed else "warning"
    return message + ".", "error" if result.failed else "information"


def leave_notice() -> tuple[str, str]:
    """The notice when Leave as is (sv_undo.leave) could not remove the marker: (message, severity)."""
    return f"The files were left as they are. {MARKER_STILL_TEXT}", "warning"


def undo_detail_rows(result: UndoResult) -> list[tuple[str, str, str]]:
    return [(flavor_name(o.flavor), o.rel, o.status + (f": {o.detail}" if o.detail else ""))
            for o in result.outcomes]
