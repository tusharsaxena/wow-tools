"""Labels, sizes, table rows and dialog texts for Interface Backup's screens (UI-free text helpers)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from wowtools.core.install import Flavor
from wowtools.core.journal import Journal, friendly_stamp
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.backup import BackupOutcome, skip_reason
from wowtools.tools.interface_backup.catalog import BackupInfo
from wowtools.tools.interface_backup.restore import PartOutcome, RestorePlan, RestoreResult
from wowtools.tools.interface_backup.scanner import PARTS, SAMPLE, FlavorScan, PartScan

# Titles for the stages the logic modules pass to progress(stage, done, total, detail).
STAGE_TITLES = {
    "scan": "Scanning", "backup": "Zipping", "verify": "Verifying the zip", "prune": "Removing old backups",
    "safety": "Safety backup of the current folders", "safety_verify": "Verifying the safety backup",
    "extract": "Unpacking the backup", "swap": "Swapping folders", "cleanup": "Deleting the replaced copy",
}
BACKUP_RESULT_COLUMNS = ("Flavor", "Outcome", "Zip", "Files", "Size", "Zip size", "Old backups removed")
RESTORE_RESULT_COLUMNS = ("Part", "Outcome", "Details")
_BACKUP_KINDS = {"created": "Backed up", "skipped": "Skipped", "failed": "Failed"}
_PART_KINDS = {"restored": "Restored", "replaced_left": "Restored (old copy left)", "rolled_back": "Left as it was",
               "failed": "Failed"}


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def human_size(n: int | None) -> str:
    if n is None:
        return "—"
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            break
    return f"{value:.1f} {unit}"


def _files_and_size(files: int, size: int | None) -> str:
    return plural(files, "file") + ("" if size is None else f" · {human_size(size)}")


def part_text(part: PartScan) -> str:
    """A part's line in the review tree: its files and size, "missing" or "link, skipped"."""
    if not part.exists:
        return "link, skipped" if part.linked else "missing"
    return _files_and_size(len(part.files), part.size)


def flavor_text(scan: FlavorScan, backups: list[BackupInfo]) -> str:
    """A flavor's line in the review tree: what a backup would hold (or why there is nothing) and its backups."""
    held = _files_and_size(scan.file_count, scan.size) if scan.has_data else f"nothing to back up: {skip_reason(scan)}"
    return f"{held} · {picker_note(backups)}"


def leftover_text(scan: FlavorScan) -> str:
    """The notice for folders an interrupted restore left (they block a restore of the flavor)."""
    return (f"Left from an interrupted restore: {', '.join(p.name for p in scan.leftovers)}. Restore is blocked for "
            "this flavor until you move or delete it (see the guide).")


def warnings_text(scan: FlavorScan) -> str:
    """The scan-warnings node of a flavor: how many places were skipped."""
    count = sum(len(p.errors) for p in scan.parts.values())
    return f"Scan warnings ({count}): skipped, not backed up (the log lists up to {SAMPLE} per folder)"


def held_text(scans: list[FlavorScan]) -> str:
    """Files and size (when known) a backup of these flavors would hold."""
    chosen = [s for s in scans if s.has_data]
    return _files_and_size(sum(s.file_count for s in chosen), _known_total([s.size for s in chosen]))


def selection_text(scans: list[FlavorScan]) -> str:
    """The review screen's bottom line for the ticked flavors."""
    text = f"Selected: {plural(len(scans), 'flavor')} · {held_text(scans)}"
    links = sum(s.link_count for s in scans if s.has_data)
    if links:
        text += f" · {plural(links, 'link')} not backed up"
    return text


def picker_note(backups: list[BackupInfo]) -> str:
    """The flavor picker's note: backups (not safety zips) of one flavor, newest first."""
    mine = [b for b in backups if not b.is_safety]
    return f"{plural(len(mine), 'backup')}, last {mine[0].when[:16]}" if mine else "no backups yet"


def _known_total(sizes: list[int | None]) -> int | None:
    total = 0
    for size in sizes:
        if size is None:
            return None
        total += size
    return total


def backup_confirm(scans: list[FlavorScan], root: Path, keep: int, running: list[str] | None,
                   free: int | None) -> tuple[str, str, tuple[str, ...]]:
    """(title, body, alerts) for the Back up ConfirmScreen. `free` is the backup drive's free bytes (None: unknown);
    a space alert needs the scan's sizes, which a summary scan under WSL does not read. A flavor with nothing to
    back up is named on a "Skipped" line (its row in the result says Skipped too)."""
    chosen = [s for s in scans if s.has_data]
    skipped = [f"{s.flavor.display_name} ({skip_reason(s)})" for s in scans if not s.has_data]
    files = sum(s.file_count for s in chosen)
    total = _known_total([s.size for s in chosen])
    lines = [plural(files, "file") + ("" if total is None else f" ({human_size(total)})") + " from "
             + ", ".join(s.flavor.display_name for s in chosen) + ".",
             *([f"Skipped: {', '.join(skipped)}."] if skipped else []),
             f"Zips go to: {to_stored(root)}",
             "Older backups are never deleted." if keep == 0 else
             f"The newest {keep} backups of each flavor are kept; older ones are deleted."]
    alerts = []
    if running:
        alerts.append(f"WoW appears to be running ({', '.join(running)}). It rewrites WTF when you log out, so this "
                      "backup may miss your latest settings.")
    if total is not None and free is not None and total > free:
        alerts.append(f"The backup drive may be short of space: {human_size(free)} free, up to {human_size(total)} "
                      "needed.")
    title = f"Back up {plural(len(chosen), 'flavor')}?"
    return title, "\n".join(lines), tuple(alerts)


def backup_result_rows(outcomes: list[BackupOutcome]) -> list[tuple[str, ...]]:
    rows = []
    for o in outcomes:
        created = o.kind == "created"
        detail = o.path.name if o.path else o.reason
        if created and o.missing:
            detail += f" ({plural(len(o.missing), 'file')} gone while zipping, left out)"
        rows.append((o.flavor.display_name, _BACKUP_KINDS.get(o.kind, o.kind), detail,
                     str(o.files) if created else "", human_size(o.bytes_in) if created else "",
                     human_size(o.bytes_zip) if created else "", str(len(o.pruned)) if o.pruned else ""))
    return rows


def parts_cell(parts: tuple[str, ...] | None) -> str:
    """A backup's parts for the list ("Interface, WTF"); "?" when its manifest could not be read."""
    if parts is None:
        return "?"
    return ", ".join(parts) or "none"


PARTS_PENDING = "…"  # a backup's parts until a worker has read its manifest


def backup_text(info: BackupInfo, parts: tuple[str, ...] | None | str = PARTS_PENDING) -> str:
    """A backup's line in the review tree: date, kind, parts (PARTS_PENDING until read) and size."""
    kind = "safety (pre-restore)" if info.is_safety else "backup"
    cell = parts if isinstance(parts, str) else parts_cell(parts)
    return f"{info.when} · {kind} · {cell} · {human_size(info.size)}"


def friendly_created(created: str) -> str:
    """A manifest's ISO-8601 `created` as "YYYY-MM-DD HH:MM:SS" (its own clock), like every other date shown;
    anything unparsable is shown as is."""
    try:
        return datetime.fromisoformat(created).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return created


def group_paths(items: list[tuple[str, str]], depth: int = 3) -> list[tuple[str, int]]:
    """Group (part, rel) paths by their first `depth` path parts (e.g. Interface/AddOns/WeakAuras), largest group
    first, then by name."""
    counts = Counter("/".join([part, *rel.split("/")][:depth]) for part, rel in items)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _more(shown: int, total: int) -> list[str]:
    return [f"  … and {total - shown} more"] if total > shown else []


def _grouped(title: str, items: list[tuple[str, str]], limit: int) -> list[str]:
    groups = group_paths(items)
    lines = [f"{title}: {plural(len(items), 'file')}"]
    lines += [f"  {name} ({plural(count, 'file')})" for name, count in groups[:limit]]
    return lines + _more(min(limit, len(groups)), len(groups))


def restore_warnings(plan: RestorePlan, limit: int = 15) -> list[str]:
    """What the restore loses or changes beyond the backup's own files; empty when nothing needs saying."""
    lines: list[str] = []
    if plan.removed:
        lines += _grouped("Will be removed", plan.removed, limit)
    if plan.newer:
        lines += _grouped("Newer now than in the backup (these changes are lost)", plan.newer, limit)
    if plan.unreadable:
        lines.append("Some folders could not be read; whatever they hold is replaced without being listed here:")
        lines += [f"  {error}" for error in plan.unreadable[:limit]]
        lines += _more(min(limit, len(plan.unreadable)), len(plan.unreadable))
    if plan.links_removed:
        lines.append("Links replaced by the backup's files (only the link goes, never what it points at; Undo makes "
                     "it again): "
                     + ", ".join(f"{p}/{r}" for p, r in plan.links_removed[:limit])
                     + (f" and {len(plan.links_removed) - limit} more" if len(plan.links_removed) > limit else ""))
    if plan.low_space:
        lines.append(f"Low disk space: {human_size(plan.free_bytes)} free on the WoW drive, about "
                     f"{human_size(plan.bytes_needed)} needed.")
    return lines


def _counted(title: str, items: list[tuple[str, str]]) -> str:
    groups = group_paths(items)
    where = groups[0][0] + (f" and {len(groups) - 1} more" if len(groups) > 1 else "")
    return f"{title}: {plural(len(items), 'file')} ({where})"


def restore_confirm_alerts(plan: RestorePlan) -> list[str]:
    """restore_warnings in one line per kind, so the confirm fits a small terminal: the restore screen just before
    it lists them by folder."""
    lines: list[str] = []
    if plan.removed:
        lines.append(_counted("Will be removed", plan.removed))
    if plan.newer:
        lines.append(_counted("Newer now than in the backup (these changes are lost)", plan.newer))
    if plan.unreadable:
        lines.append(f"{plural(len(plan.unreadable), 'place')} could not be read; whatever is there is replaced "
                     "too.")
    if plan.links_removed:
        lines.append(f"Links replaced by the backup's files: {len(plan.links_removed)} (only the link goes).")
    if plan.low_space:
        lines.append(f"Low disk space: {human_size(plan.free_bytes)} free on the WoW drive, about "
                     f"{human_size(plan.bytes_needed)} needed.")
    return lines


def restore_confirm(plan: RestorePlan, when: str, running: list[str] | None, *,
                    backup_free: int | None = None) -> tuple[str, str, tuple[str, ...]]:
    """(title, body, alerts) for the Restore ConfirmScreen (which starts on No). The alerts are counts, one line
    per kind (restore_confirm_alerts), never the full lists. `backup_free`: free bytes on the backup drive, where
    the safety backup goes (None: unknown); the zip is taken to be at most the folders' size, as for a backup."""
    parts = " and ".join(plan.parts)
    title = f"Replace {parts} of {plan.flavor.display_name} with the backup from {when}?"
    body = ("The folders become exactly what the backup holds. A safety backup of the current folders is taken "
            "first, so Undo (z) can put them back.")
    if plan.links_kept:
        body += f"\n{plural(len(plan.links_kept), 'link')} kept as they are."
    alerts = restore_confirm_alerts(plan)
    current = plan.current_bytes
    if current is not None and backup_free is not None and current > backup_free:
        alerts.append(f"The backup drive may be short of space for the safety backup: {human_size(backup_free)} "
                      f"free, up to {human_size(current)} needed.")
    if running:
        alerts.append(f"WoW appears to be running ({', '.join(running)}). Close it first: it rewrites WTF when you "
                      "log out, and an open game can lock Interface files.")
    return title, body, tuple(alerts)


def ordered_parts(result: RestoreResult) -> list[PartOutcome]:
    """The result's parts in PARTS order (an undo works through them in reverse; the tables do not)."""
    order = {part: n for n, part in enumerate(PARTS)}
    return sorted(result.parts, key=lambda p: order.get(p.part, len(order)))


def restore_result_rows(result: RestoreResult) -> list[tuple[str, ...]]:
    """RESTORE_RESULT_COLUMNS rows, in PARTS order (ordered_parts)."""
    return [(p.part, _PART_KINDS.get(p.kind, p.kind), p.reason) for p in ordered_parts(result)]


def undo_confirm(journal: Journal) -> tuple[str, str]:
    """(title, body) for the Undo ConfirmScreen (which starts on No)."""
    parts = [str(e.get("part", "?")) for e in journal.entries if e.get("action") == "replaced"]
    folder = journal.header.get("flavor")
    flavor = Flavor(folder, Path(folder)).display_name if isinstance(folder, str) and folder else "?"
    title = f"Undo the restore from {friendly_stamp(journal.started)}?"
    body = (f"Put {' and '.join(parts) or 'the restored folders'} of {flavor} back as they were before that restore, "
            "from its safety backup. Anything changed since the restore is lost.")
    return title, body
