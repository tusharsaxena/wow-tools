"""Labels, stage titles and table rows for the Screenshot Organizer screens. UI-free (plain strings only)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from wowtools.core.paths import to_stored
from wowtools.tools.screenshots.organizer import (ALREADY_FILED, CONFLICT_KEPT, COPIED, COPY_REMOVED,
                                                  DUPLICATE_REMOVED, FAILED, MOVED, REFUSED, RESTORED, SKIPPED,
                                                  SOURCE_LEFT, UNDO_SKIPPED, WOULD_COPY, WOULD_MOVE,
                                                  WOULD_REMOVE_DUPLICATE, OrganizeResult)
from wowtools.tools.screenshots.planner import MAYBE_DUPLICATE, Plan, ShotItem
from wowtools.tools.screenshots.settings import ShotSettings

# Every outcome kind, in the order the result summary lists them.
KIND_LABELS: dict[str, str] = {
    MOVED: "Moved",
    COPIED: "Copied",
    SOURCE_LEFT: "Copied, source left",
    DUPLICATE_REMOVED: "Duplicate removed",
    ALREADY_FILED: "Already filed",
    WOULD_MOVE: "Would move",
    WOULD_COPY: "Would copy",
    WOULD_REMOVE_DUPLICATE: "Would remove duplicate",
    RESTORED: "Put back",
    COPY_REMOVED: "Copy removed",
    CONFLICT_KEPT: "Conflict (kept both)",
    SKIPPED: "Skipped",
    UNDO_SKIPPED: "Left alone",
    REFUSED: "Refused",
    FAILED: "Failed",
}

# Colour class per kind for the result table: the screen maps these to theme colours.
SUCCESS_KINDS = frozenset({MOVED, COPIED, RESTORED, COPY_REMOVED, DUPLICATE_REMOVED})
ACCENT_KINDS = frozenset({WOULD_MOVE, WOULD_COPY, WOULD_REMOVE_DUPLICATE})
WARNING_KINDS = frozenset({CONFLICT_KEPT, SKIPPED, SOURCE_LEFT, ALREADY_FILED, UNDO_SKIPPED})
ERROR_KINDS = frozenset({FAILED, REFUSED})

STAGE_TITLES = {"organize": "Filing screenshots", "prune": "Tidying journals", "undo": "Undoing the last run"}
RESULT_COLUMNS = ("Outcome", "Flavor", "File", "Target", "Reason")


def kind_class(kind: str) -> str:
    """"success", "accent", "warning", "error" or "" for an outcome kind."""
    for name, kinds in (("success", SUCCESS_KINDS), ("accent", ACCENT_KINDS), ("warning", WARNING_KINDS),
                        ("error", ERROR_KINDS)):
        if kind in kinds:
            return name
    return ""


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def friendly_stamp(stamp: str) -> str:
    """A journal's ISO-8601 time as "YYYY-MM-DD HH:MM" (its own clock); anything unparsable is shown as is."""
    if not stamp:
        return "an unknown time"
    try:
        return datetime.fromisoformat(stamp).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp


def destination_label(dest_dir: Path | None) -> str:
    if dest_dir is None:
        return "in place (<flavor>\\Screenshots\\YYYY\\MM\\DD)"
    return to_stored(dest_dir) + "\\<flavor>\\YYYY\\MM\\DD"


def mode_label(result: OrganizeResult) -> str:
    if result.undo:
        return "Undo"
    verb = "copy" if result.copy else "move"
    return f"Dry run ({verb})" if result.dry_run else verb.capitalize()


def result_rows(result: OrganizeResult) -> list[tuple[str, str, str, str, str]]:
    return [(KIND_LABELS.get(o.kind, o.kind), o.flavor, o.src.name, str(o.dst.parent), o.reason)
            for o in result.outcomes]


def summary_rows(result: OrganizeResult) -> list[tuple[str, str]]:
    rows = [("Mode", mode_label(result))]
    counts = result.counts()
    rows.extend((label, str(counts[kind])) for kind, label in KIND_LABELS.items() if counts.get(kind))
    if result.dry_run:
        journal = "not written (dry run)"
    elif result.journal_path is None:
        journal = "none (nothing changed)"
    else:
        journal = str(result.journal_path)
    rows.append(("Journal", journal))
    if result.pruned:
        rows.append(("Older journals removed", str(len(result.pruned))))
    return rows


def confirm_text(selection: list[ShotItem], plan: Plan, settings: ShotSettings, dry_run: bool) -> tuple[str, str]:
    """(title, body) for the organize / dry run confirmation. The destination is the scanned plan's."""
    verb = "Copy" if settings.copy_mode else "Move"
    where = "into date folders in place" if plan.dest_dir is None else f"to {to_stored(plan.dest_dir)}"
    title = f"{verb} {plural(len(selection), 'screenshot')} {where}?"
    if dry_run:
        title = f"Dry run: {title}"
    per_flavor: dict[str, list[ShotItem]] = {}
    for item in selection:
        per_flavor.setdefault(item.flavor.folder, []).append(item)
    lines = []
    for folder, items in per_flavor.items():
        dupes = sum(1 for i in items if i.state == MAYBE_DUPLICATE)
        line = f"{folder}: {plural(len(items), 'screenshot')}"
        if dupes:
            line += f" ({plural(dupes, 'possible duplicate')})"
        lines.append(line)
    lines.append(f"Destination: {destination_label(plan.dest_dir)}")
    if any(i.state == MAYBE_DUPLICATE for i in selection):
        lines.append("Possible duplicates are compared by content: an identical source is "
                     + ("left alone." if settings.copy_mode else "removed.")
                     + " A different file is a conflict and both are kept.")
    lines.append("Nothing is ever overwritten.")
    if dry_run:
        lines.append("DRY RUN: nothing is moved, copied or written.")
    else:
        lines.append("A run journal is written, so Undo last run (z) can put this back.")
    return title, "\n".join(lines)
