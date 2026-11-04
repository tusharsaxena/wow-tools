"""Text for the Config Copier's review, popups and result screen (config tools spec CC4, CC7): each pair's status, the
Copy / Dry run confirm (counts, the per-target detail tree, the CC7 macro warnings as a counted list) and the result
rows, one per file. The progress stage titles, the Undo confirm, the unfinished-run text and the undo rows are the
shared pipeline's (core/sv_report.py), re-exported here. UI-free."""
from __future__ import annotations

import difflib
from collections.abc import Sequence

from wowtools.core import sv_report
from wowtools.core.cvarfile import parse_cvars
from wowtools.core.install import Character, flavor_name
from wowtools.core.kb import is_state_cvar
from wowtools.core.sv_apply import MultiApplyResult
from wowtools.core.sv_report import (RESULT_TEXT, STAGE_TITLES, STATUS_COLOURS, UNDO_COLUMNS,
                                     recovery_text, undo_confirm, undo_detail_rows, undo_summary_rows)
from wowtools.core.text import Listed, plural
from wowtools.tools.config_copier.model import CONFIG_FILE, PairPlan
from wowtools.tools.config_copier.runner import COPYABLE

__all__ = ["FILE_COLUMNS", "PAIR_CAPS", "PAIR_MINIMUMS", "RESULT_TEXT", "STAGE_TITLES", "STATUS_COLOURS",
           "UNDO_COLUMNS", "WARNING_MARK", "WARNING_SHORT", "character_text", "copy_confirm", "copy_groups",
           "copy_listed", "diff_rows", "file_rows", "pair_cells", "pair_text", "recovery_text", "summary_rows",
           "undo_confirm", "undo_detail_rows", "undo_summary_rows"]

FILE_COLUMNS = ("Account", "Character", "File", "Result")
# A pair's status as the review tree and the confirm say it (CC4).
PAIR_TEXT = {"new": "new", "replace": "replaced", "unchanged": "unchanged", "no-source": "source has no file",
             "unreadable": "can't be read"}
MERGED = " (merged)"  # after a config-cache.wtf pair that writes: its state CVars stay the target's (CC5)
WARNING_MARK = "⚠"
WARNING_SHORT = "action bars"  # a replaced macros-cache.txt that held macros (CC7)
# A pair line's columns (feedback round 2 R4, STD-7.28): file · status · warning. A status is never cut (its
# minimum is the longest, `source has no file`): only a long problem gives way, cut at its end; then the file name,
# cut in its middle (`macros…e.txt`: the five names stay apart); the warning is never cut, only dropped.
PAIR_CAPS = (None, 40, None)
PAIR_MINIMUMS = (10, max(map(len, PAIR_TEXT.values())), 0)


def character_text(character: Character) -> str:
    """`ACCOUNT › Realm/Name`, as the confirm and the results name a character."""
    return f"{character.account} › {character.label}"


def pair_text(plan: PairPlan) -> str:
    """The status of a pair: new, replaced (merged, for config-cache.wtf), unchanged, source has no file, or why it
    can't be read."""
    text = PAIR_TEXT.get(plan.status, plan.status)
    if plan.status == "unreadable" and plan.problem:
        return plan.problem
    if plan.name == CONFIG_FILE and plan.status in COPYABLE:
        text += MERGED
    return text


def pair_cells(plan: PairPlan) -> tuple[str, str, str]:
    """A pair line's cells: the file, its status (pair_text) and the CC7 mark (`⚠ action bars`, or "": the whole
    sentence is in the confirm; the tree is narrow)."""
    return plan.name, pair_text(plan), f"{WARNING_MARK} {WARNING_SHORT}" if plan.warnings else ""


def _copying(plans: Sequence[PairPlan]) -> list[PairPlan]:
    return [plan for plan in plans if plan.status in COPYABLE]


def copy_confirm(source: Character, flavor: str, plans: Sequence[PairPlan], *,
                 dry_run: bool) -> tuple[str, str, list[str]]:
    """(title, body, alerts) of the Copy / Dry run confirm: what is copied where, then what the run does."""
    copying = _copying(plans)
    targets = len({plan.target.path for plan in copying})
    new = sum(plan.status == "new" for plan in copying)
    title = "Dry run" if dry_run else "Copy the ticked files?"
    lines = [(f"From {character_text(source)} ({flavor_name(flavor)}) to {plural(targets, 'character')}: "
              f"{plural(len(copying) - new, 'file')} replaced, {new} new.")]
    if dry_run:
        lines.append("Every file is checked in memory; no file is written.")
    else:
        lines.append("A backup of the whole WTF folder and of every file replaced is taken first. Undo (z) puts "
                     "the files back and removes the new ones.")
    alerts = [] if dry_run else ["Close WoW first: it rewrites these files when a character logs out."]
    return title, "\n".join(lines), alerts


def copy_groups(plans: Sequence[PairPlan]) -> dict[str, list[str]]:
    """The confirm's detail tree: one group per target character, one line per file it gets (`macros-cache.txt:
    replaced`), in plan order."""
    groups: dict[str, list[str]] = {}
    for plan in _copying(plans):
        groups.setdefault(character_text(plan.target), []).append(f"{plan.name}: {pair_text(plan)}")
    return groups


def copy_listed(plans: Sequence[PairPlan]) -> list[Listed]:
    """The CC7 warnings of the pairs copied, one entry each (the message, the character, the file)."""
    return [Listed(warning, character_text(plan.target), plan.name)
            for plan in _copying(plans) for warning in plan.warnings]


def summary_rows(result: MultiApplyResult, source: Character) -> list[tuple[str, str]]:
    """The result screen's summary: the source, then the shared rows (files changed or that would be, skipped, put
    back, failed, stopped, the zips, the journal)."""
    flavors = ", ".join(flavor_name(run.flavor.folder) for run in result.runs)
    return [("Source", f"{character_text(source)} ({flavors})"), *sv_report.apply_summary_rows(result)]


def file_rows(result: MultiApplyResult) -> list[tuple[str, str, str, str]]:
    """One row per file (FILE_COLUMNS): account, character, file and what became of it (created files say so)."""
    rows = []
    for outcome in result.outcomes:
        file = outcome.file
        state = RESULT_TEXT.get(outcome.status, outcome.status)
        if outcome.detail:
            state += f": {outcome.detail}"
        rows.append((file.account, file.owner, file.path.name, state))
    return rows


KEPT = "kept: the target's own"  # a config-cache.wtf state line the copy leaves as it is (CC5)
GAP = "…"  # between two parts of a long diff
BYTES_ONLY = "Only line endings or bytes that are not text differ."  # a replace no line of the diff shows


def _lines(data: bytes | None) -> list[str]:
    return (data or b"").decode("utf-8", "replace").splitlines()


def bytes_only(plan: PairPlan) -> bool:
    """True when the pair's files differ but not in any line the diff shows: only line endings (CRLF against LF, a
    last newline) or bytes that are not UTF-8 text, which the display decodes the same."""
    old, new = plan.old or b"", plan.new or b""
    return old != new and _lines(old) == _lines(new)


def _state_line(line: str) -> bool:
    parsed = parse_cvars(line.encode("utf-8", "replace") + b"\n")
    return bool(parsed.lines) and is_state_cvar(parsed.lines[0].name)


def diff_rows(plan: PairPlan) -> list[tuple[str, str, str]]:
    """The diff of a replaced pair, the target's file as it is against what it gets: (mark, line, note) rows, mark
    " " for a line kept, "-" removed, "+" added, GAP between two parts. A plain file shows its changes with three
    lines around each; a config-cache.wtf shows the whole file, its state lines noted KEPT (CC5)."""
    old, new = _lines(plan.old), _lines(plan.new)
    config = plan.name == CONFIG_FILE
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    groups = [matcher.get_opcodes()] if config else list(matcher.get_grouped_opcodes(3))
    rows: list[tuple[str, str, str]] = []
    for index, group in enumerate(groups):
        if index:
            rows.append((GAP, "", ""))
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                rows += [(" ", line, KEPT if config and _state_line(line) else "") for line in old[i1:i2]]
                continue
            rows += [("-", line, "") for line in old[i1:i2]]
            rows += [("+", line, "") for line in new[j1:j2]]
    return rows
