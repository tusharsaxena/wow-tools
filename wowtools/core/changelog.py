"""CHANGELOG.md, parsed for the changelog screen and the release check (spec D2). No UI here.

The file follows Keep a Changelog: a `## [X.Y.Z] - YYYY-MM-DD` heading per release (a trailing ` [YANKED]` marks a
pulled release), plus an optional `## [Unreleased]` one; everything under a heading, up to the next, is that
version's notes (Markdown). Text above the first heading is the file's introduction and is not an entry. A `## `
line inside a code fence is notes; a fence closes only on the same character repeated at least as often as the one
that opened it (CommonMark). CHANGELOG.md sits at the install root, a root *.md file the updater ships and replaces
(core/updater.py `_shipped_names`), so the notes always match the program."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.events import log_event

CHANGELOG_NAME = "CHANGELOG.md"
CHANGELOG_PATH = REPO_ROOT / CHANGELOG_NAME
UNRELEASED = "Unreleased"

_HEADING_RE = re.compile(r"^## \[(?P<version>[^\]]*)\](?:\s+-\s+(?P<date>\S+))?(?P<yanked>\s+\[YANKED\])?\s*$",
                         re.IGNORECASE)
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<rest>.*)$")


class ChangelogError(ValueError):
    """CHANGELOG.md does not follow the format: a bad version heading, a duplicate version, an unclosed code fence,
    or no entry at all."""


@dataclass(frozen=True)
class ChangelogEntry:
    version: str  # "X.Y.Z", or UNRELEASED
    date: str | None  # "YYYY-MM-DD"; None for UNRELEASED
    body: str  # the version's notes, Markdown, without the heading
    yanked: bool = False  # "## [X.Y.Z] - YYYY-MM-DD [YANKED]": the release was pulled

    @property
    def unreleased(self) -> bool:
        return self.version == UNRELEASED

    def sort_key(self) -> tuple[int, ...]:
        return (1_000_000,) if self.unreleased else tuple(int(part) for part in self.version.split("."))


@dataclass(frozen=True)
class Changelog:
    """What the changelog screen shows: the entries newest first, or why there are none (`problem`)."""
    entries: list[ChangelogEntry]
    problem: str | None = None


def _heading(line: str, number: int) -> tuple[str, str | None, bool]:
    match = _HEADING_RE.match(line)
    if match is None:
        raise ChangelogError(f"line {number}: expected '## [X.Y.Z] - YYYY-MM-DD' or '## [{UNRELEASED}]', "
                             f"found {line.strip()!r}")
    version, when, yanked = match.group("version").strip(), match.group("date"), match.group("yanked") is not None
    if version.lower() == UNRELEASED.lower():
        if when is not None or yanked:
            raise ChangelogError(f"line {number}: [{UNRELEASED}] takes no date and no [YANKED]")
        return UNRELEASED, None, False
    if not _VERSION_RE.match(version):
        raise ChangelogError(f"line {number}: {version!r} is not a version (X.Y.Z)")
    if when is None:
        raise ChangelogError(f"line {number}: version {version} has no date (## [{version}] - YYYY-MM-DD)")
    try:
        valid = bool(_DATE_RE.match(when)) and date.fromisoformat(when) is not None
    except ValueError:
        valid = False
    if not valid:
        raise ChangelogError(f"line {number}: {when!r} is not a date (YYYY-MM-DD)")
    return version, when, yanked


def _fence_closes(line: str, opener: str) -> bool:
    """True if `line` closes the fence `opener` opened: the same character, at least as many, nothing after it."""
    match = _FENCE_RE.match(line)
    return (match is not None and match.group("fence")[0] == opener[0]
            and len(match.group("fence")) >= len(opener) and not match.group("rest").strip())


def parse_changelog(text: str) -> list[ChangelogEntry]:
    """The entries of a CHANGELOG.md text, newest first ([Unreleased] on top). Every `## ` heading outside a code
    fence must be a version heading; raises ChangelogError for a bad one, a duplicate version, an unclosed fence or
    no entry."""
    entries: list[ChangelogEntry] = []
    seen: set[str] = set()
    current: tuple[str, str | None, bool] | None = None
    body: list[str] = []
    fence: tuple[str, int] | None = None  # the open fence's marker and line

    def close() -> None:
        if current is not None:
            entries.append(ChangelogEntry(current[0], current[1], "\n".join(body).strip("\n"), current[2]))

    for number, line in enumerate(text.splitlines(), 1):
        if fence is not None:
            if _fence_closes(line, fence[0]):
                fence = None
        elif (opened := _FENCE_RE.match(line)) is not None:
            fence = (opened.group("fence"), number)
        elif line.startswith("## "):
            close()
            current = _heading(line, number)
            if current[0] in seen:
                raise ChangelogError(f"line {number}: version {current[0]} appears twice")
            seen.add(current[0])
            body = []
            continue
        if current is not None:
            body.append(line)
    if fence is not None:
        raise ChangelogError(f"line {fence[1]}: code fence {fence[0]} is never closed")
    close()
    if not entries:
        raise ChangelogError("no version entries (## [X.Y.Z] - YYYY-MM-DD)")
    return sorted(entries, key=ChangelogEntry.sort_key, reverse=True)


def entry_for(entries: list[ChangelogEntry], version: str) -> ChangelogEntry | None:
    return next((entry for entry in entries if entry.version == version), None)


def load_changelog(path: Path = CHANGELOG_PATH) -> Changelog:
    """Read and parse CHANGELOG.md. Never raises: a missing, unreadable or malformed file gives no entries and a
    `problem` to show instead, and logs changelog.unreadable."""
    try:
        return Changelog(parse_changelog(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        problem = f"{path.name} is missing from {path.parent}."
    except (OSError, UnicodeDecodeError) as exc:
        problem = f"{path.name} could not be read: {exc}"
    except ChangelogError as exc:
        problem = f"{path.name} is not in the expected format ({exc})."
    log_event("changelog.unreadable", path=str(path), reason=problem)
    return Changelog([], problem)
