"""Text for the Config Editor's browse screen, popups and result screen (config tools spec CE3-CE8): a file's line
and a CVar row's columns in the tree (name, value, default, state, category: feedback spec CF1, CF2), the help
panel's details of a CVar (CE4, laid out by CF5), what a CVar does for Set and Add (CF6), the
Apply / Dry run confirm (counts, one group per file in its detail tree, the scope warnings of CE5 as listed entries)
and the result rows, one per file. The progress stage titles, the Undo confirm, the unfinished-run text and the undo
rows are the shared pipeline's (core/sv_report.py), re-exported here. UI-free."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from wowtools.core import sv_report
from wowtools.core.install import Flavor, flavor_name
from wowtools.core.kb import CvarInfo, Recommendation
from wowtools.core.sv_apply import MultiApplyResult
from wowtools.core.sv_report import (RESULT_TEXT, STAGE_TITLES, STATUS_COLOURS, UNDO_COLUMNS, recovery_text,
                                     undo_confirm, undo_detail_rows, undo_summary_rows)
from wowtools.core.text import Listed, plural
from wowtools.tools.config_editor.model import CONFIG_WTF, ConfigTarget, Row
from wowtools.tools.config_editor.ops import ConfigStaged, build_changes, is_boolean

__all__ = ["ACCOUNT_CONFIG", "CHANGED", "COLUMN_CAPS", "COLUMN_MINIMUMS", "DEFAULT_STATE", "DROP_ORDER",
           "FILE_COLUMNS", "NOT_SET", "NO_DESCRIPTION", "RESULT_TEXT", "STAGE_TITLES", "STATUS_COLOURS",
           "UNDO_COLUMNS", "UNKNOWN", "HelpLine", "HelpPanel", "apply_confirm", "apply_groups", "file_label",
           "file_rows", "help_panel", "path_label", "recovery_text", "row_cells", "row_state",
           "scope_listed", "scope_text", "summary_rows", "target_text", "undo_confirm", "undo_detail_rows",
           "undo_summary_rows", "what_it_does"]

ACCOUNT_CONFIG = "Account config"
NOT_SET = "not set"
# The state column (CF1, U1): the value differs from the known default, matches it (or is not set, so the game uses
# it), or there is no default to compare with (a CVar the knowledge base has no entry for, CE5, or no default for).
CHANGED = "changed"
DEFAULT_STATE = "default"
UNKNOWN = "unknown"
# The name, value and default columns (CF2): as wide as the file's widest cell up to the cap; when the tree pane is
# narrower the value and the default give way first, then the name, down to the minimum (the state and category
# columns are never cut, only dropped when nothing else fits: DROP_ORDER). "not set" fits the value's minimum. The
# screen fits them with the shared ui.columns (feedback round 2 R4).
COLUMN_CAPS = (40, 24, 24)
COLUMN_MINIMUMS = (12, 7, 6)
# The columns a too-narrow pane drops, one more each step: the default, the category, the value, then the state,
# leaving the name (FB2r: a row always fits, at 80 columns too).
DROP_ORDER = (2, 4, 1, 3)
FILE_COLUMNS = ("Flavor", "File", "Result")
LEVEL_FILES: dict[str, str] = {
    "machine": "this computer's Config.wtf",
    "account": "the account's config-cache.wtf",
    "character": "the character's config-cache.wtf",
}


NO_DESCRIPTION = "No description in the reference."


def what_it_does(info: CvarInfo | None) -> str:
    """What a CVar does, on one line (feedback spec CF6: Set and Add show it): our note when there is one, else
    Blizzard's help text, else NO_DESCRIPTION (also for a CVar the knowledge base doesn't know)."""
    text = (info.description or info.help) if info is not None else ""
    return " ".join(text.split()) or NO_DESCRIPTION


def _shown(value: str) -> str:
    return value if value else '""'


def row_state(row: Row) -> str:
    """The state column (CF1): `changed`, `default` (also for a CVar not set: the game uses its default) or
    `unknown` (the knowledge base has no entry or no default for it)."""
    if row.changed:
        return CHANGED
    if row.info is None or row.default is None:
        return UNKNOWN
    return DEFAULT_STATE


def row_cells(row: Row) -> tuple[str, str, str, str, str]:
    """A CVar row's five cells, uncut (CF1): name, value (`not set` when the file has no line for it), default
    (empty when not known), state and category."""
    value = NOT_SET if row.value is None else _shown(row.value)
    default = "" if row.default is None else _shown(row.default)
    return row.name, value, default, row_state(row), row.category


def file_label(target: ConfigTarget) -> str:
    """A file's own line in the tree: Config.wtf, Account config or the character's name."""
    if target.level == "machine":
        return CONFIG_WTF
    if target.level == "account":
        return ACCOUNT_CONFIG
    return target.character.name if target.character is not None else target.label


def target_text(target: ConfigTarget) -> str:
    """`Retail › Config.wtf`, `Retail › MAIN account config`, `Retail › MAIN/Realm1/Aellâ`: a file in a confirm or a
    popup."""
    label = f"{target.label} account config" if target.level == "account" else target.label
    return f"{target.flavor.display_name} › {label}"


def _index(cvars: Mapping[str, CvarInfo]) -> dict[str, CvarInfo]:
    return {name.casefold(): info for name, info in cvars.items()}


def scope_text(info: CvarInfo) -> str:
    """Where the game keeps a CVar and whether it syncs it (CE4, X8)."""
    if info.scope is None:
        return "Where the game keeps it is not known."
    where = {"machine": "on this computer (Config.wtf)", "account": "per account (the account's config-cache.wtf)",
             "character": "per character (the character's config-cache.wtf)"}[info.scope]
    synced = "the game syncs it with Blizzard's servers" if info.synced else "not synced"
    return f"Kept {where}; {synced}."


class HelpLine(NamedTuple):
    """One line of the help panel (CF5): a label (shown bold; "" none) and its text. `kind` names the colour the
    screen gives the text (`state`, `category`: the row colours of CF3; `warning`; "" none) and `tail` follows it in
    the plain style; a `bullet` line is one entry of a list (the sources)."""
    label: str
    text: str
    kind: str = ""
    tail: str = ""
    bullet: bool = False

    def plain(self) -> str:
        head = f"{self.label}:" if self.label else ""
        body = f"{self.text}{self.tail}"
        line = f"{head} {body}" if head and body else head or body
        return f"  • {line}" if self.bullet else line


class HelpPanel(NamedTuple):
    """The help panel's content (CF5): a title (shown bold) and its sections, a blank line between them."""
    title: str
    sections: tuple[tuple[HelpLine, ...], ...]

    def lines(self) -> list[str]:
        """The panel as plain lines: the title, then each section after a blank line."""
        out = [self.title]
        for section in self.sections:
            out.append("")
            out.extend(line.plain() for line in section)
        return out


# The state line's note (CF5): what the state word means for this CVar.
STATE_NOTES: dict[str, str] = {
    CHANGED: " (differs from the default)",
    DEFAULT_STATE: " (matches the default)",
    UNKNOWN: " (no default to compare with)",
}
NOT_SET_NOTE = " (not set: the game uses the default)"


def _file_panel(target: ConfigTarget, has_data: bool) -> HelpPanel:
    lines = [HelpLine("File", f"{target.path.name}, {LEVEL_FILES[target.level]}.")]
    if target.read_only:
        lines.append(HelpLine("Read-only", target.problem or "", "warning"))
    elif not target.exists:
        lines.append(HelpLine("No file yet", "a CVar set here creates it."))
    else:
        count = len({line.name.casefold() for line in target.parsed.lines}) if target.parsed is not None else 0
        lines.append(HelpLine("CVars", f"{count} set in this file"))
    if not has_data:
        lines.append(HelpLine("", f"No CVar data for {target.flavor.display_name} yet: every CVar shows as {UNKNOWN}.",
                              "warning"))
    return HelpPanel(target_text(target), (tuple(lines),))


def help_panel(target: ConfigTarget, row: Row | None, *, recommendation: Recommendation | None = None,
               has_data: bool = True) -> HelpPanel:
    """The help panel under the tree (CE4, laid out by CF5). For a CVar row: its name as the title; its value here,
    the default, the recommendation, the state (with what it means), the category and the type where it is known;
    Blizzard's text and our note; the scope and sync and a scope warning; then the source of each as a bullet. For a
    file (`row` None): where it is and what it holds."""
    if row is None:
        return _file_panel(target, has_data)
    info = row.info
    state = row_state(row)
    value = "not set here (the game uses its default)" if row.value is None else f"{_shown(row.value)} here"
    values = [HelpLine("Value", value)]
    if info is not None:
        values.append(HelpLine("Default", _shown(row.default) if row.default is not None else "not known"))
        if recommendation is not None:  # beside the value and the default, so the panel under the tree shows it
            # without scrolling at 120x30 (FB3r1: it scrolls with the mouse only)
            values.append(HelpLine("Recommended", f"{_shown(recommendation.value)}. {recommendation.reason}"))
    note = NOT_SET_NOTE if state == DEFAULT_STATE and row.value is None else STATE_NOTES[state]
    values += [HelpLine("State", state, "state", note), HelpLine("Category", row.category, "category")]
    if info is None:
        unknown = HelpLine("Unknown CVar", f"the knowledge base has no entry for it in {target.flavor.display_name}. "
                                           "You can still set or remove it.")
        return HelpPanel(row.name, (tuple(values), (unknown,)))
    if is_boolean(info.default):
        values.append(HelpLine("Type", "on or off (1 or 0); Space toggles it."))
    sections: list[tuple[HelpLine, ...]] = [tuple(values)]
    described = []
    sources = []
    if info.help:
        described.append(HelpLine("Blizzard", info.help))
        if info.source:
            sources.append(HelpLine("Blizzard", info.source, bullet=True))
    if info.description:
        described.append(HelpLine("Note", info.description))
        if info.description_source:
            sources.append(HelpLine("Note", info.description_source, bullet=True))
    sections.append(tuple(described) or (HelpLine("Description", "No description yet."),))
    scope = [HelpLine("Scope", scope_text(info))]
    if row.scope_mismatch:
        scope.append(HelpLine("", f"⚠ This file is the {target.level} level, but the game keeps this CVar at the "
                                  f"{info.scope} level: it may ignore it here.", "warning"))
    sections.append(tuple(scope))
    if recommendation is not None and recommendation.source:
        sources.append(HelpLine("Recommended", recommendation.source, bullet=True))
    if sources:
        sections.append((HelpLine("Sources", ""), *sources))
    return HelpPanel(row.name, tuple(sections))


def scope_listed(staged: ConfigStaged, targets: Sequence[ConfigTarget],
                 cvars: Mapping[str, Mapping[str, CvarInfo]]) -> list[Listed]:
    """CE5's warning, one entry per CVar set in a file whose level is not where the knowledge base says the game
    keeps it (the confirm lists them; never a refusal). `cvars` is by flavor folder."""
    out: list[Listed] = []
    indexes: dict[str, dict[str, CvarInfo]] = {}
    for target in targets:
        sets = staged.sets.get(target.path, {})
        if not sets:
            continue
        index = indexes.setdefault(target.flavor.folder, _index(cvars.get(target.flavor.folder, {})))
        for name in sets:
            info = index.get(name.casefold())
            if info is not None and info.scope is not None and info.scope != target.level:
                out.append(Listed(f"Set at the {target.level} level, but the game keeps it at the {info.scope} "
                                  "level: it may ignore it there.", target_text(target), name))
    return out


def apply_confirm(staged: ConfigStaged, targets: Sequence[ConfigTarget], *,
                  dry_run: bool) -> tuple[str, str, list[str]]:
    """(title, body, alerts) of the Apply / Dry run confirm: how many changes in how many files, then what the run
    does; a real run's alert says to close WoW."""
    changes = build_changes(staged, targets)
    count = sum(len(change.changes) for change in changes)
    by_path = {target.path: target for target in targets}
    flavors = ", ".join(dict.fromkeys(flavor_name(by_path[change.path].flavor.folder) for change in changes))
    title = "Dry run" if dry_run else "Apply the staged changes?"
    lines = [f"{plural(count, 'change')} in {plural(len(changes), 'file')} ({flavors})."]
    if dry_run:
        lines.append("Every file is checked in memory; no file is written.")
    else:
        lines.append("A backup of the whole WTF folder and of every file changed is taken first. Undo (z) puts the "
                     "files back and removes the new ones.")
    alerts = [] if dry_run else ["Close WoW first: it rewrites these files when you log out or exit."]
    return title, "\n".join(lines), alerts


def apply_groups(staged: ConfigStaged, targets: Sequence[ConfigTarget]) -> dict[str, list[str]]:
    """The confirm's detail tree: one group per file (target_text), one line per change."""
    by_path = {target.path: target for target in targets}
    return {target_text(by_path[change.path]): list(change.changes) for change in build_changes(staged, targets)}


def summary_rows(result: MultiApplyResult) -> list[tuple[str, str]]:
    """The result screen's summary: the shared rows (files changed or that would be, skipped, put back, failed,
    stopped, the zips, the journal)."""
    return sv_report.apply_summary_rows(result)


def path_label(flavor: Flavor, path: Path) -> str:
    """A written file's place: Config.wtf, `MAIN account config`, `MAIN/Realm1/Aellâ`."""
    try:
        parts = path.parent.relative_to(flavor.account_dir).parts
    except ValueError:
        return path.name
    if len(parts) == 1:
        return f"{parts[0]} account config"
    return "/".join(parts) if parts else path.name


def file_rows(result: MultiApplyResult) -> list[tuple[str, str, str]]:
    """One row per file (FILE_COLUMNS): game version, which file and what became of it."""
    rows = []
    for outcome in result.outcomes:
        file = outcome.file
        state = RESULT_TEXT.get(outcome.status, outcome.status)
        if outcome.detail:
            state += f": {outcome.detail}"
        rows.append((flavor_name(file.flavor.folder), path_label(file.flavor, file.path), state))
    return rows
