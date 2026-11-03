"""macros-cache.txt, byte-exact (config tools spec V4, V5, ME6, ME13, ME14). UI-free.

The Retail client writes one block per macro, every line ending in CRLF, UTF-8:

    VER 3 0100000000000005 "D Up" "132360"
    <body lines>
    END

The id is 16 hex digits (`00...` an account macro, `01...` a character macro, numbered per file); the icon is a file
id (`134400`, the "?" icon) or a texture name. parse_macros reads that layout and nothing else: a file in any other
shape (LF-only or mixed line endings, a block without its END, the older `MACRO <n> ...` layout, another `VER`, a
blank or stray line, no final newline, a byte-order mark, a duplicated id) comes back with known_layout False and a
problem, and apply_macro_changes refuses to rewrite it (Review Focus 1). Text is decoded as UTF-8 with
surrogateescape, so any byte survives a round trip.

apply_macro_changes splices: a block nobody changed keeps its exact bytes and its place; a replaced block is rewritten
where it stands (keeping its id: action bar buttons point at macro ids, V5); a deleted block goes; an added one is
appended (the client re-sorts by name when it saves). The 16-character name and 255-character body limits are the
caller's to enforce (NAME_LIMIT, BODY_LIMIT): this module only refuses what would break the layout.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

__all__ = ["ACCOUNT_PREFIX", "BODY_LIMIT", "CHARACTER_PREFIX", "ICON_DEFAULT", "NAME_LIMIT", "Macro", "MacroChange",
           "MacroFile", "apply_macro_changes", "next_macro_id", "parse_macros"]

ACCOUNT_PREFIX = "00"
CHARACTER_PREFIX = "01"
NAME_LIMIT = 16  # the client cuts a name at 16 characters (V4)
BODY_LIMIT = 255
ICON_DEFAULT = "134400"  # the "?" icon: the client picks the icon from the first spell (ME8)

NEWLINE = b"\r\n"
_ENCODING = "utf-8"
_ERRORS = "surrogateescape"
# The icon has no quote, so the name (greedy) may hold one: `"say "hi"" "134400"` is the name `say "hi"`.
_HEADER = re.compile(rb'VER 3 ([0-9A-Fa-f]{16}) "(.*)" "([^"]*)"')
_ID = re.compile(r"[0-9A-Fa-f]{16}")
_PREFIXES = {"account": ACCOUNT_PREFIX, "character": CHARACTER_PREFIX}


@dataclass(frozen=True)
class Macro:
    id: str  # 16 hex digits as written
    name: str
    icon: str  # file id or texture name, as written
    body: str  # lines joined with "\n"
    span: tuple[int, int]  # byte span of the whole VER..END block incl. its final newline


@dataclass(frozen=True)
class MacroFile:
    macros: tuple[Macro, ...]
    newline: bytes
    known_layout: bool  # False: read-only (Review Focus 1)
    problem: str | None


@dataclass(frozen=True)
class MacroChange:
    kind: Literal["add", "replace", "delete"]
    id: str
    name: str = ""
    icon: str = ""
    body: str = ""


def _decode(raw: bytes) -> str:
    return raw.decode(_ENCODING, _ERRORS)


def _unknown(problem: str) -> MacroFile:
    return MacroFile((), NEWLINE, False, problem)


def _lines(data: bytes) -> list[tuple[int, int]] | str:
    """The (start, end-without-CRLF) of every line, or the problem when a line does not end in CRLF."""
    lines: list[tuple[int, int]] = []
    start = 0
    while start < len(data):
        end = data.find(b"\n", start)
        if end < 0:
            return f"line {len(lines) + 1} has no line ending"
        if end == start or data[end - 1:end] != b"\r":
            return f"line {len(lines) + 1} does not end in CRLF"
        lines.append((start, end - 1))
        start = end + 1
    return lines


def parse_macros(data: bytes) -> MacroFile:
    """Read a macros-cache.txt. A layout this reader does not know comes back read-only (known_layout False)."""
    lines = _lines(data)
    if isinstance(lines, str):
        return _unknown(lines)
    macros: list[Macro] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        start, end = lines[index]
        header = _HEADER.fullmatch(data, start, end)
        if header is None:
            return _unknown(f"line {index + 1} is not a `VER 3 <id> \"<name>\" \"<icon>\"` line")
        macro_id = header.group(1).decode("ascii")
        if macro_id.upper() in seen:
            return _unknown(f"line {index + 1}: macro id {macro_id} appears twice")
        seen.add(macro_id.upper())
        body_at = index + 1
        close = body_at
        while close < len(lines) and data[lines[close][0]:lines[close][1]] != b"END":
            if _HEADER.fullmatch(data, *lines[close]):
                close = len(lines)  # a new block before this one's END
                break
            close += 1
        if close >= len(lines):
            return _unknown(f"the macro on line {index + 1} has no END line")
        body = "\n".join(_decode(data[s:e]) for s, e in lines[body_at:close])
        macros.append(Macro(macro_id, _decode(header.group(2)), _decode(header.group(3)), body,
                            (start, lines[close][1] + len(NEWLINE))))
        index = close + 1
    return MacroFile(tuple(macros), NEWLINE, True, None)


def _block(change: MacroChange, newline: bytes) -> bytes:
    """One macro's bytes. Raises ValueError for anything that would not read back as this macro."""
    if not _ID.fullmatch(change.id):
        raise ValueError(f"a macro id is 16 hex digits, not {change.id!r}")
    for label, text in (("name", change.name), ("icon", change.icon), ("body", change.body)):
        if "\r" in text or (label != "body" and "\n" in text):
            raise ValueError(f"the macro {label} has a line break")
    if '"' in change.icon:
        raise ValueError("the macro icon has a quote")
    lines = change.body.split("\n") if change.body else []
    if "END" in lines or any(_HEADER.fullmatch(line.encode(_ENCODING, _ERRORS)) for line in lines):
        raise ValueError("a macro body line cannot be END or a VER line")
    header = f'VER 3 {change.id} "{change.name}" "{change.icon}"'
    return b"".join(line.encode(_ENCODING, _ERRORS) + newline for line in (header, *lines, "END"))


def apply_macro_changes(data: bytes, parsed: MacroFile, changes: Sequence[MacroChange]) -> bytes:
    """`data` (as `parsed` read it) with `changes` applied; every other byte stays. Raises ValueError on a file of an
    unknown layout (even with no changes), an id the file lacks (replace, delete) or has (add), two changes to one id,
    or a name, icon or body the layout cannot hold."""
    if not parsed.known_layout:
        raise ValueError(f"the macro file is in a layout this tool does not know: {parsed.problem}")
    by_id = {m.id.upper(): m for m in parsed.macros}
    touched: set[str] = set()
    edits: dict[int, tuple[int, bytes]] = {}  # block start -> (block end, new bytes)
    added = bytearray()
    for change in changes:
        key = change.id.upper()
        if key in touched:
            raise ValueError(f"two changes to macro {change.id}")
        touched.add(key)
        macro = by_id.get(key)
        if change.kind == "add":
            if macro is not None:
                raise ValueError(f"macro id {change.id} is already in the file")
            added += _block(change, parsed.newline)
        elif macro is None:
            raise ValueError(f"no macro {change.id} in the file")
        elif change.kind == "replace":
            edits[macro.span[0]] = (macro.span[1], _block(change, parsed.newline))
        elif change.kind == "delete":
            edits[macro.span[0]] = (macro.span[1], b"")
        else:
            raise ValueError(f"unknown macro change {change.kind!r}")
    out = bytearray()
    at = 0
    for start in sorted(edits):
        end, new = edits[start]
        out += data[at:start] + new
        at = end
    out += data[at:] + added
    return bytes(out)


def next_macro_id(parsed: MacroFile, scope: Literal["account", "character"]) -> str:
    """The id for a new macro in this file: the highest id with the scope's prefix plus one, or `<prefix>...01` (V5:
    the client keeps it). Ids with the other prefix are not counted. Raises ValueError on an unknown layout or when
    the prefix's numbers run out."""
    if not parsed.known_layout:
        raise ValueError(f"the macro file is in a layout this tool does not know: {parsed.problem}")
    prefix = _PREFIXES[scope]
    numbers = [int(m.id, 16) for m in parsed.macros if m.id[:2] == prefix]
    new = f"{max(numbers) + 1 if numbers else int(prefix, 16) << 56 | 1:016X}"
    if new[:2] != prefix:
        raise ValueError(f"no {scope} macro id is left after {max(numbers):016X}")
    return new
