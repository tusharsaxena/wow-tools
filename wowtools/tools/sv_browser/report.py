"""Text for the Saved Variables Browser's run popups and result screen (spec D13, D15, D21): the Apply / Dry run
and Undo confirms (with the USE AT YOUR OWN RISK disclaimer as their alert lines) and the result rows, one summary
and one detail row per file. The progress stage titles, the unfinished-run text and the undo rows are the shared
pipeline's (core/sv_report.py), re-exported here. UI-free."""
from __future__ import annotations

from wowtools.core import sv_report
from wowtools.core.install import flavor_name
from wowtools.core.journal import Journal
from wowtools.core.sv_apply import MultiApplyResult
from wowtools.core.sv_report import (RESULT_TEXT, STAGE_TITLES, UNDO_COLUMNS,  # noqa: F401 - re-exported
                                     recovery_text, undo_detail_rows, undo_summary_rows)
from wowtools.core.text import plural
from wowtools.tools.sv_browser.ops import Plan

DISCLAIMER = ("USE AT YOUR OWN RISK. This tool edits addon SavedVariables directly. It knows nothing about what an "
              "addon expects; a wrong value can break an addon or lose its settings. Backups and Undo are made, but "
              "you are responsible for what you change.")
# The USE AT YOUR OWN RISK popup's text (ui.disclaimer; D2, L4): DISCLAIMER after its first words (the popup's title
# says them), then where it is said again.
DISCLAIMER_POPUP = (DISCLAIMER.removeprefix("USE AT YOUR OWN RISK. ")
                    + "\n\nClose WoW before you apply anything: it rewrites every SavedVariables file when you log "
                      "out. Every Apply and Undo asks again.")
FILE_COLUMNS = ("Flavor", "Account", "Owner", "File", "Edits", "Result")
BROWSE, RESULTS = "Browse", "Results"  # the review tree's two views (v): the files, and the hits of the last search


def _edits(plan: Plan) -> int:
    return sum(len(p.edits) for p in plan.files.values())


def _per_flavor(plan: Plan) -> str:
    counts: dict[str, int] = {}
    for file in plan.files:
        counts[file.flavor.folder] = counts.get(file.flavor.folder, 0) + 1
    return ", ".join(f"{flavor_name(folder)}: {plural(n, 'file')}" for folder, n in counts.items())


def apply_confirm(plan: Plan, *, dry_run: bool) -> tuple[str, str, list[str]]:
    """(title, body, alerts) of the Apply / Dry run confirm: the counts per flavor, what the run does, and as red
    alert lines the array entries that move down and (Apply) the disclaimer."""
    title = "Dry run" if dry_run else "Apply the pending changes?"
    lines = [f"{plural(_edits(plan), 'edit')} in {plural(len(plan.files), 'file')} ({_per_flavor(plan)})."]
    if dry_run:
        lines.append("Every change is checked in memory; no file is written.")
    else:
        lines.append("A backup of the whole WTF folder and of every file changed is taken first. Undo (z) puts "
                     "the files back.")
    alerts = []
    shifts = sum(1 for p in plan.files.values() for e in p.edits if e.delete and e.positional)
    if shifts:
        alerts.append(f"{plural(shifts, 'array entry', 'array entries')} deleted: the entries after each move down "
                      f"one place.")
    if not dry_run:
        alerts.append(DISCLAIMER)
    return title, "\n".join(lines), alerts


def apply_groups(plan: Plan) -> dict[str, list[str]]:
    """The confirm's detail tree: per flavor, one line per file with its edits (`ACCT1 › Account-wide › ElvUI.lua:
    2 edits`), in plan order."""
    groups: dict[str, list[str]] = {}
    for file, file_plan in plan.files.items():
        line = f"{file.account} › {file.owner} › {file.path.name}: {plural(len(file_plan.edits), 'edit')}"
        groups.setdefault(flavor_name(file.flavor.folder), []).append(line)
    return groups


def undo_confirm(journal: Journal) -> tuple[str, str, list[str]]:
    """The shared Undo confirm with the disclaimer as its alert line (D21)."""
    title, body, alerts = sv_report.undo_confirm(journal)
    return title, body, [*alerts, DISCLAIMER]


def summary_rows(result: MultiApplyResult) -> list[tuple[str, str]]:
    """The result screen's summary: the flavors, the files changed (or that would be), the edits written (or
    checked), then the shared rows (skipped, put back, failed, stopped, the zips, the journal)."""
    shared = sv_report.apply_summary_rows(result)
    outcomes = result.would_edit if result.dry_run else result.edited
    edits = sum(len(o.changes) for o in outcomes)
    rows = [("Flavors", ", ".join(flavor_name(run.flavor.folder) for run in result.runs)), shared[0],
            ("Edits checked" if result.dry_run else "Edits written", plural(edits, "edit"))]
    return rows + shared[1:]


def file_rows(result: MultiApplyResult) -> list[tuple[str, str, str, str, str, str]]:
    """One row per file (FILE_COLUMNS): flavor, account, owner (Account-wide or Realm/Name), file, its edits and
    what became of it."""
    rows = []
    for outcome in result.outcomes:
        file = outcome.file
        state = RESULT_TEXT.get(outcome.status, outcome.status)
        if outcome.detail:
            state += f": {outcome.detail}"
        edits = plural(len(outcome.changes), "edit") if outcome.changes else ""
        rows.append((flavor_name(file.flavor.folder), file.account, file.owner, file.path.name, edits, state))
    return rows
