"""Text for the Macro Editor's review, popups and result screen (config tools spec ME2-ME6): slot use, a macro's line,
the cross-flavor paste warnings (ME5), the Apply / Dry run confirm (counts, one group per file in its detail tree,
the ME6 action bar warning when a macro is deleted) and the result rows, one per file. The progress stage titles,
the Undo confirm, the unfinished-run text and the undo rows are the shared pipeline's (core/sv_report.py),
re-exported here. UI-free."""
from __future__ import annotations

from collections.abc import Sequence

from wowtools.core import sv_report
from wowtools.core.install import flavor_name
from wowtools.core.kb import load_macro_reference
from wowtools.core.macrofile import BODY_LIMIT, Macro
from wowtools.core.sv_apply import MultiApplyResult
from wowtools.core.sv_report import (RESULT_TEXT, STAGE_TITLES, STATUS_COLOURS, UNDO_COLUMNS, recovery_text,
                                     undo_confirm, undo_detail_rows, undo_summary_rows)
from wowtools.core.svfiles import OWNER_ACCOUNT_WIDE
from wowtools.core.text import plural
from wowtools.tools.macro_editor.explain import unknown_terms
from wowtools.tools.macro_editor.model import MacroSet
from wowtools.tools.macro_editor.ops import Staged, body_length, build_changes

__all__ = ["ACCOUNT_MACROS", "DELETE_WARNING", "FILE_COLUMNS", "RESULT_TEXT", "STAGE_TITLES", "STATUS_COLOURS",
           "UNDO_COLUMNS", "apply_confirm", "apply_groups", "file_rows", "macro_text", "paste_warnings",
           "recovery_text", "scope_text", "set_text", "slots_text", "summary_rows", "undo_confirm", "undo_detail_rows",
           "undo_summary_rows"]

ACCOUNT_MACROS = "Account macros"
FILE_COLUMNS = ("Flavor", "Account", "Macros", "Result")
FULL = "FULL"
# ME3: a flavor with no sourced limits in the KB is counted with Retail's, and its slots say so.
UNCONFIRMED = "unconfirmed"
# ME6 (V5): an action bar button points at a macro id; a deleted macro's buttons go with it.
DELETE_WARNING = "Action bar buttons that use the deleted macros will be removed."
CROSS_FLAVOR = "a macro written for one game version may not work in another."


def slots_text(count: int, limit: int, known: bool = True) -> str:
    """A set's slot use, as the tree shows it: `12/30`, `30/30 FULL` (ME2); `12/30 unconfirmed` when the limit is
    not sourced for the set's flavor (`known` False, ME3)."""
    text = f"{count}/{limit}"
    if count >= limit:
        text = f"{text} {FULL}"
    return f"{text} {UNCONFIRMED}" if not known else text


def macro_text(macro: Macro) -> str:
    """A macro's line in the tree: `name · first body line · n/255` (ME2)."""
    first = macro.body.split("\n", 1)[0]
    return f"{macro.name} · {first} · {body_length(macro.body)}/{BODY_LIMIT}"


def set_text(mset: MacroSet) -> str:
    """`Retail › MAIN/Account macros`, `Retail › MAIN/Realm1/Aellâ`: a set in a confirm or a warning."""
    return f"{mset.flavor.display_name} › {mset.label}"


def scope_text(mset: MacroSet) -> str:
    """The edit screen's scope line (ME8): whose macro this is."""
    if mset.character is None:
        return f"Account macro: every character of {mset.account.name} has it."
    return f"Character macro: only {mset.character.name} ({mset.character.realm}) has it."


def paste_warnings(picked: Sequence[tuple[MacroSet, Macro]], targets: Sequence[MacroSet]) -> list[str]:
    """The paste review's cross-flavor warnings (ME5): one line per (from, into) pair of game versions that differ,
    then one per pasted macro with commands or conditionals the target version's reference flags
    (explain.unknown_terms). Nothing when every target is in the macros' own game version."""
    lines: list[str] = []
    flagged: list[str] = []
    for target in targets:
        into = target.flavor.folder
        ref = None
        for source, macro in picked:
            if source.flavor.folder == into:
                continue
            line = f"From {flavor_name(source.flavor.folder)} into {flavor_name(into)}: {CROSS_FLAVOR}"
            if line not in lines:
                lines.append(line)
            ref = ref or load_macro_reference(into)
            terms = unknown_terms(macro.body, ref)
            note = f"{macro.name}: {', '.join(terms)} may not work in {flavor_name(into)}."
            if terms and note not in flagged:
                flagged.append(note)
    return lines + flagged


def apply_confirm(staged: Staged, sets: Sequence[MacroSet], *, dry_run: bool) -> tuple[str, str, list[str]]:
    """(title, body, alerts) of the Apply / Dry run confirm: how many changes in how many files, then what the run
    does; a real run's alerts say to close WoW and, when a macro is deleted, the ME6 warning."""
    changes = build_changes(staged, sets)
    count = sum(len(change.changes) for change in changes)
    title = "Dry run" if dry_run else "Apply the staged changes?"
    by_path = {mset.path: mset for mset in sets}
    flavors = ", ".join(dict.fromkeys(flavor_name(by_path[change.path].flavor.folder) for change in changes))
    lines = [f"{plural(count, 'change')} in {plural(len(changes), 'file')} ({flavors})."]
    if dry_run:
        lines.append("Every file is checked in memory; no file is written.")
    else:
        lines.append("A backup of the whole WTF folder and of every file changed is taken first. Undo (z) puts the "
                     "files back and removes the new ones.")
    alerts: list[str] = []
    if not dry_run:
        alerts.append("Close WoW first: it rewrites macros-cache.txt when a character logs out.")
        if any(c.kind == "delete" for path in staged.changes for c in staged.changes[path]):
            alerts.append(DELETE_WARNING)
    return title, "\n".join(lines), alerts


def apply_groups(staged: Staged, sets: Sequence[MacroSet]) -> dict[str, list[str]]:
    """The confirm's detail tree: one group per file (set_text), one line per change."""
    by_path = {mset.path: mset for mset in sets}
    return {set_text(by_path[change.path]): list(change.changes) for change in build_changes(staged, sets)}


def summary_rows(result: MultiApplyResult) -> list[tuple[str, str]]:
    """The result screen's summary: the shared rows (files changed or that would be, skipped, put back, failed,
    stopped, the zips, the journal)."""
    return sv_report.apply_summary_rows(result)


def file_rows(result: MultiApplyResult) -> list[tuple[str, str, str, str]]:
    """One row per file (FILE_COLUMNS): game version, account, whose macros and what became of it."""
    rows = []
    for outcome in result.outcomes:
        file = outcome.file
        state = RESULT_TEXT.get(outcome.status, outcome.status)
        if outcome.detail:
            state += f": {outcome.detail}"
        owner = ACCOUNT_MACROS if file.owner == OWNER_ACCOUNT_WIDE else file.owner
        rows.append((flavor_name(file.flavor.folder), file.account, owner, state))
    return rows
