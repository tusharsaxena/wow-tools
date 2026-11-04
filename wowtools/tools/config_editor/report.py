"""Text for the Config Editor's browse screen, popups and result screen (config tools spec CE3-CE8): a file's and a
CVar row's line in the tree (`name = value (default …) ✱changed`), the help panel's details of a CVar (CE4), the
Apply / Dry run confirm (counts, one group per file in its detail tree, the scope warnings of CE5 as listed entries)
and the result rows, one per file. The progress stage titles, the Undo confirm, the unfinished-run text and the undo
rows are the shared pipeline's (core/sv_report.py), re-exported here. UI-free."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from wowtools.core import sv_report
from wowtools.core.install import Flavor, flavor_name
from wowtools.core.kb import CvarInfo, Recommendation
from wowtools.core.sv_apply import MultiApplyResult
from wowtools.core.sv_report import (RESULT_TEXT, STAGE_TITLES, STATUS_COLOURS, UNDO_COLUMNS, recovery_text,
                                     undo_confirm, undo_detail_rows, undo_summary_rows)
from wowtools.core.text import Listed, plural
from wowtools.tools.config_editor.model import CONFIG_WTF, ConfigTarget, Row
from wowtools.tools.config_editor.ops import ConfigStaged, build_changes, is_boolean

__all__ = ["ACCOUNT_CONFIG", "CHANGED", "FILE_COLUMNS", "NOT_SET", "RESULT_TEXT", "STAGE_TITLES", "STATUS_COLOURS",
           "UNDO_COLUMNS", "UNKNOWN", "apply_confirm", "apply_groups", "file_label", "file_rows", "help_lines",
           "path_label", "recovery_text", "row_text", "scope_listed", "scope_text", "summary_rows", "target_text", "undo_confirm",
           "undo_detail_rows", "undo_summary_rows"]

ACCOUNT_CONFIG = "Account config"
NOT_SET = "not set"
UNKNOWN = "unknown"  # CE5: a CVar the knowledge base has no entry for (still editable)
CHANGED = "✱changed"  # CE4: set to something other than the KB default
FILE_COLUMNS = ("Flavor", "File", "Result")
LEVEL_FILES: dict[str, str] = {
    "machine": "this computer's Config.wtf",
    "account": "the account's config-cache.wtf",
    "character": "the character's config-cache.wtf",
}


def _shown(value: str) -> str:
    return value if value else '""'


def row_text(row: Row) -> str:
    """A CVar's line in the tree: `name = value (default d) ✱changed`, `name  not set (default d)`, and `unknown`
    for a CVar the knowledge base has no entry for (CE4, CE5)."""
    text = row.name + (f" = {_shown(row.value)}" if row.value is not None else f"  {NOT_SET}")
    if row.info is None:
        text += f"  {UNKNOWN}"
    elif row.default is not None:
        text += f" (default {_shown(row.default)})"
    if row.changed:
        text += f"  {CHANGED}"
    return text


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


def help_lines(target: ConfigTarget, row: Row | None, *, recommendation: Recommendation | None = None,
               has_data: bool = True) -> list[str]:
    """The help panel under the tree (CE4): for a CVar row its value here and the default, whether it differs, the
    Blizzard text and our note (each with its source), the type where it is known, the scope and sync, the
    recommendation and a scope warning; for a file (`row` None) where it is and what it holds."""
    if row is None:
        count = len({line.name.casefold() for line in target.parsed.lines}) if target.parsed is not None else 0
        lines = [f"{target_text(target)}: {target.path.name}, {LEVEL_FILES[target.level]}."]
        if target.read_only:
            lines.append(f"Read-only: {target.problem}")
        elif not target.exists:
            lines.append("No file yet: a CVar set here creates it.")
        else:
            lines.append(f"It sets {plural(count, 'CVar')}.")
        if not has_data:
            lines.append(f"No CVar data for {target.flavor.display_name} yet: every CVar shows as {UNKNOWN}.")
        return lines
    info = row.info
    value = "not set here (the game uses its default)" if row.value is None else f"{_shown(row.value)} here"
    head = f"{row.name} ({row.category}): {value}"
    if info is not None:
        head += f"; default {_shown(row.default)}" if row.default is not None else "; default not known"
        if row.changed:
            head += f" ({CHANGED.removeprefix('✱')} from the default)"
    lines = [head]
    if info is None:
        lines.append(f"Unknown CVar: the knowledge base has no entry for it in {target.flavor.display_name}. You can "
                     "still set or remove it.")
        return lines
    if info.help:
        lines.append(f"Blizzard: {info.help}" + (f"  ({info.source})" if info.source else ""))
    if info.description:
        lines.append(f"Note: {info.description}  ({info.description_source})")
    if not info.help and not info.description:
        lines.append("No description yet.")
    if is_boolean(info.default):
        lines.append("Type: on or off (1 or 0); Space toggles it.")
    lines.append(scope_text(info))
    if row.scope_mismatch:
        lines.append(f"⚠ This file is the {target.level} level, but the game keeps this CVar at the {info.scope} "
                     "level: it may ignore it here.")
    if recommendation is not None:
        lines.append(f"Recommended: {_shown(recommendation.value)}. {recommendation.reason}  ({recommendation.source})")
    return lines


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
