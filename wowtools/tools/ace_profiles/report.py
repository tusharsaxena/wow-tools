"""Text for the Ace3 Profile Manager's screens: tree labels and tags, the bottom line, the guidance line, confirm
texts and result rows (UI-free)."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowtools.core.install import FLAVOR_NAMES
from wowtools.core.journal import Journal, friendly_stamp
from wowtools.tools.ace_profiles.model import DEFAULT
from wowtools.tools.ace_profiles.multi import MultiApplyResult
from wowtools.tools.ace_profiles.ops import CopyOf, DbState, Original, Summary
from wowtools.tools.ace_profiles.undo import UndoResult

STAGE_TITLES = {
    "check": "Checking the files", "lock_check": "Checking for locked files",
    "snapshot_list": "Listing the WTF folder", "snapshot": "Backing up the WTF folder",
    "snapshot_verify": "Checking the WTF backup", "backup": "Saving the original files",
    "edit": "Writing the changes", "undo": "Putting files back",
}
DETAIL_COLUMNS = ("Flavor", "Account", "Addon", "Change", "Result")
UNDO_COLUMNS = ("Flavor", "File", "Result")
DELETED = "✘ deleted"
REMOVED = "✘ removed"
NO_PENDING = "No pending changes"
STEPS = ("1 Tick profiles or characters (Space) → 2 pick an action below → 3 check the pending changes in the tree "
         "→ 4 Apply (w) writes them; Dry run (y) only checks them")
CHARACTER_KINDS = ("char", "pair", "character")  # tree nodes that are one character
RESULT_TEXT = {"edited": "changed", "would_edit": "would change", "skipped": "skipped", "failed": "failed",
               "rolled_back": "put back"}


def plural(n: int, word: str, words: str | None = None) -> str:
    return f"{n} {word if n == 1 else (words or word + 's')}"


def flavor_name(folder: str) -> str:
    return FLAVOR_NAMES.get(folder) or folder.strip("_").replace("_", " ").title()


@dataclass
class CharRow:
    char: str
    tags: list[str] = field(default_factory=list)
    removed: bool = False

    @property
    def label(self) -> str:
        return " · ".join([self.char, *self.tags])


@dataclass
class ProfileRow:
    name: str
    deleted: bool = False
    tags: list[str] = field(default_factory=list)
    chars: list[CharRow] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.deleted:
            return " · ".join([self.name, *self.tags])
        live = sum(1 for c in self.chars if not c.removed)
        return " · ".join([self.name, plural(live, "character"), *self.tags])


def char_tags(state: DbState, char: str) -> list[str]:
    tags = []
    if char in state.leftovers:
        tags.append("no character folder")
    if state.db.lds_enabled(char):
        tags.append("spec profiles")
    old, new = state.db.profile_keys.get(char), state.keys.get(char)
    if new is None and old is not None:
        tags.append(REMOVED)
    elif old is not None and new != old:
        tags.append(f"was {old}")
    return tags


def profile_rows(state: DbState) -> list[ProfileRow]:
    rows: dict[str, ProfileRow] = {}
    for name in state.names():
        tags = []
        if name == DEFAULT:
            tags.append("Default")
        source = state.profiles.get(name)
        if isinstance(source, Original) and source.name != name:
            tags.append(f"renamed from {source.name}")
        if isinstance(source, CopyOf):
            tags.append(f"copy of {source.name}")
        if state.missing(name):
            tags.append("missing")
        elif not state.users(name):
            tags.append("unused")
        if isinstance(source, Original) and state.db.profiles[source.name].empty:
            tags.append("empty")
        rows[name] = ProfileRow(name, False, tags, [CharRow(c, char_tags(state, c)) for c in state.users(name)])
    for name in state.changes().deleted:
        rows.setdefault(name, ProfileRow(name, True, [f"{DELETED}"]))
    renamed = {src.name: name for name, src in state.profiles.items()
               if isinstance(src, Original) and src.name != name}
    for char, old in state.db.profile_keys.items():
        if state.keys.get(char) is None:
            # under its profile where it is now (renamed, deleted or kept); a missing profile it alone used keeps
            # a row of its own
            row = rows.get(renamed.get(old, old)) or rows.setdefault(old, ProfileRow(old, False, ["missing"]))
            row.chars.append(CharRow(char, char_tags(state, char), removed=True))
    return list(rows.values())


def pending_text(summary: Summary) -> str:
    parts = [(summary.deleted, "delete"), (summary.renamed, "rename"), (summary.copied, "copy", "copies"),
             (summary.reassigned, "reassign"), (summary.removed, "removed character"),
             (summary.lds, "spec profile")]
    text = " · ".join(plural(*p) for p in parts if p[0])
    return text or NO_PENDING


def pending_count(total: int, files: int) -> str:
    """The count of pending changes, for example "3 pending changes in 2 files"."""
    return f"{plural(total, 'pending change')} in {plural(files, 'file')}"


def selection_text(profiles: int, chars: int, summary: Summary, warnings: int) -> str:
    pending = pending_count(summary.total, summary.files) if summary.total else NO_PENDING
    text = f"Selected: {plural(profiles, 'profile')} · {plural(chars, 'character')} · {pending}"
    if warnings:
        text += f" · ⚠ {plural(warnings, 'scan warning')}"
    return text


def node_hint(node_kind: str | None, node_name: str, ticked: int, locked: str = "") -> str:
    """What can be done with the ticks, else with the highlighted node ("" when nothing in particular). `locked` is
    the addon's name when the highlighted node belongs to a blacklisted (locked) addon: only the unlock is offered."""
    if ticked:
        return f"{ticked} ticked: pick an action below (Delete, Assign, …)"
    if locked and (node_kind in ("profile", "addon", "db") or node_kind in CHARACTER_KINDS):
        return f"{locked} is blacklisted: shown, never changed (u unlocks it for this session)"
    if node_kind == "profile":
        return f'Profile "{node_name}": Delete, Rename or Copy it, or tick it with Space'
    if node_kind in CHARACTER_KINDS:
        return f'"{node_name}": Assign it a profile, or remove it if it is a leftover'
    if node_kind in ("addon", "db"):
        return f"{node_name}: Keep only Default or Everyone → Default (More…), or Blacklist…"
    return ""


def guidance(node_kind: str | None, node_name: str, ticked_profiles: int, ticked_chars: int, pending_total: int,
             pending_files: int, *, locked: str = "", hint: bool = True) -> str:
    """The review's guidance line (#guide): the pending changes first (when there are any), then what can be done
    with the ticks or the highlighted node; with neither, the four steps of the workflow. hint=False leaves the
    per-node hint out (the screen does when it would squeeze the tree)."""
    lines = []
    if pending_total:
        lines.append(f"{pending_count(pending_total, pending_files)}, not written yet: Apply (w) writes them, "
                     "Dry run (y) checks them, Discard (⌫) drops them")
    text = node_hint(node_kind, node_name, ticked_profiles + ticked_chars, locked) if hint else ""
    if text:
        lines.append(text)
    return "\n".join(lines) or STEPS


def apply_confirm(summary: Summary, states: list[DbState], *, dry_run: bool) -> tuple[str, str, list[str]]:
    title = "Dry run" if dry_run else "Apply the pending changes?"
    flavors = sorted({flavor_name(s.file.flavor.folder) for s in states})
    lines = [f"{pending_text(summary)} in {plural(summary.files, 'file')} ({', '.join(flavors)})."]
    if dry_run:
        lines.append("Every change is checked in memory; no file is written.")
    else:
        lines.append("A backup of the whole WTF folder and of every file changed is taken first. Undo (z) puts "
                     "the files back.")
    alerts = []
    for state in states:
        changes = state.changes()
        addon = state.file.addon
        if DEFAULT in changes.deleted:
            alerts.append(f'{addon}: the "Default" profile will be deleted.')
        targets = {new for _, _, new in changes.reassigned}
        for name in sorted(t for t in targets if not state.exists(t)):
            alerts.append(f'{addon}: "{name}" does not exist yet; the addon creates it at the next login with its '
                          f"defaults.")
        if any(state.db.lds_enabled(c) for c, _, _ in changes.reassigned):
            alerts.append(f"{addon}: LibDualSpec switches some of these characters' profile by spec; it will "
                          f"override the change at login.")
    return title, "\n".join(lines), alerts


def undo_confirm(journal: Journal) -> tuple[str, str, list[str]]:
    files = len(journal.entries)
    folders = sorted({e["flavor"] for e in journal.entries})
    where = f" in {', '.join(flavor_name(f) for f in folders)}" if folders else ""
    body = (f"Put back {plural(files, 'file')} changed{where} {friendly_stamp(journal.started)}. A file saved "
            f"since (by WoW) is left as it is.")
    return "Undo the last change?", body, []


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
    for run in result.runs:
        if run.result is not None and run.result.snapshot is not None:
            rows.append((f"WTF backup ({flavor_name(run.flavor.folder)})", str(run.result.snapshot)))
        if run.result is not None and run.result.backup_zip is not None:
            rows.append((f"Original files ({flavor_name(run.flavor.folder)})", str(run.result.backup_zip)))
    if result.journal_path is not None:
        rows.append(("Journal", str(result.journal_path)))
    return rows


def apply_detail_rows(result: MultiApplyResult) -> list[tuple[str, str, str, str, str]]:
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
    rows = [("Put back", plural(len(result.restored), "file"))]
    if result.skipped:
        rows.append(("Left as they are", plural(len(result.skipped), "file")))
    if result.failed:
        rows.append(("Failed", plural(len(result.failed), "file")))
    rows += [("WTF backup", str(p)) for p in result.snapshots]
    return rows


def undo_detail_rows(result: UndoResult) -> list[tuple[str, str, str]]:
    return [(flavor_name(o.flavor), o.rel, o.status + (f": {o.detail}" if o.detail else ""))
            for o in result.outcomes]
