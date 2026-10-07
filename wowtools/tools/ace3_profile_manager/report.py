"""Text for the Ace3 Profile Manager's screens: tree labels and tags, the bottom line, the guidance line and confirm
texts (UI-free). The progress stage titles, the Undo confirm, the unfinished-run text and the result rows are the
shared pipeline's
(core/sv_report.py), re-exported here."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowtools.core.install import flavor_name
from wowtools.core.sv_report import (DETAIL_COLUMNS, STAGE_TITLES, UNDO_COLUMNS,  # noqa: F401 - re-exported
                                     apply_detail_rows, apply_summary_rows, recovery_text, undo_confirm,
                                     undo_detail_rows, undo_summary_rows)
from wowtools.core.text import plural
from wowtools.tools.ace3_profile_manager.model import DEFAULT
from wowtools.tools.ace3_profile_manager.ops import CopyOf, DbState, Original, Summary

# The USE AT YOUR OWN RISK popup's text (ui.disclaimer, L4), shown before the first scan of a session.
DISCLAIMER = ("This tool edits the AceDB profile data inside addon SavedVariables: it renames, copies and deletes "
              "profiles and moves or removes characters. It can't know how each addon uses its profiles; a wrong "
              "change can reset an addon's settings. Every file it changes is backed up first and Undo puts them "
              "back, but you are responsible for what you change."
              "\n\nClose WoW before you apply anything: it rewrites every SavedVariables file when you log out. "
              "Every Apply and Undo asks again.")
DELETED = "✘ deleted"
REMOVED = "✘ removed"
NO_PENDING = "No pending changes"
# The guide's texts at 120x30 (68 columns, tests/test_ace_report.py and tests/test_look_and_feel.py): the steps take
# two rows; the pending line (up to 99999 changes) and each hint (with a name of up to 16 characters) one row each,
# so both show together. A longer name is shortened with "…" by the screen to keep the hint on its row.
STEPS = ("1 Tick profiles or characters (Space) → 2 pick an action below → 3 check the pending changes in the tree "
         "→ 4 Apply writes them")
CHARACTER_KINDS = ("char", "pair", "character")  # tree nodes that are one character


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


def scan_label(name: str) -> str:
    """The scan box's line while SavedVariables are read: the file being read, once there is one."""
    return f"Reading SavedVariables: {name}" if name else "Reading SavedVariables"


def pending_text(summary: Summary) -> str:
    parts = [(summary.deleted, "delete"), (summary.renamed, "rename"), (summary.copied, "copy", "copies"),
             (summary.reassigned, "reassign"), (summary.removed, "removed character"),
             (summary.lds, "spec profile")]
    text = " · ".join(plural(*p) for p in parts if p[0])
    return text or NO_PENDING


def pending_count(total: int, files: int) -> str:
    """The count of pending changes, for example "3 pending changes in 2 files"."""
    return f"{plural(total, 'pending change')} in {plural(files, 'file')}"


def selection_text(profiles: int, chars: int, summary: Summary) -> str:
    """The review's bottom line (its scan warnings are on the Warnings button beside it)."""
    pending = pending_count(summary.total, summary.files) if summary.total else NO_PENDING
    return f"Selected: {plural(profiles, 'profile')} · {plural(chars, 'character')} · {pending}"


def node_hint(node_kind: str | None, node_name: str, ticked: int, locked: str = "") -> str:
    """What can be done with the ticks, else with the highlighted node ("" when nothing in particular). `locked` is
    the addon's name when the highlighted node belongs to a blacklisted (locked) addon: only the unlock is offered."""
    if ticked:
        return f"{ticked} ticked: pick an action below (Delete, Assign, …)"
    if locked and (node_kind in ("profile", "addon", "db") or node_kind in CHARACTER_KINDS):
        return f"{locked} is blacklisted: u unlocks it for this session"
    if node_kind == "profile":
        return f'Profile "{node_name}": Delete, Rename or Copy it'
    if node_kind in CHARACTER_KINDS:
        return f'"{node_name}": Assign a profile, or remove it if a leftover'
    if node_kind in ("addon", "db"):
        return f"{node_name}: Only Default, Everyone → Default (below)"
    return ""


def shorten(name: str, keep: int) -> str:
    """name cut to its first `keep` characters plus "…" when it is longer."""
    return name if len(name) <= keep else name[:keep] + "…"


def guidance(node_kind: str | None, node_name: str, ticked_profiles: int, ticked_chars: int, pending_total: int, *,
             locked: str = "", hint: bool = True) -> str:
    """The review's guidance line (#guide): the pending changes first (when there are any; the bottom line says in
    how many files), then what can be done with the ticks or the highlighted node; with neither, the four steps of
    the workflow. hint=False leaves the per-node hint out (the screen does when the guide would take more than two
    rows even with the name shortened)."""
    lines = []
    if pending_total:
        lines.append(f"{plural(pending_total, 'pending change')}, not written: Apply, Dry run or Discard them")
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
