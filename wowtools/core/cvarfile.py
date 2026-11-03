"""config-cache.wtf and Config.wtf, byte-exact (config tools spec CC5, CE5, CE8). UI-free.

Both files are `SET <name> "<value>"` lines. parse_cvars lists those lines (name, value, byte span with the line's
own ending); every other line (a comment, a blank, anything malformed) is kept verbatim and not listed. The value is
everything between the first quote after the name and the line's last quote, so a value holding quotes reads back
whole. Text is UTF-8 with surrogateescape, so any byte survives.

The client reads CVar names in any case, so get() and apply_cvar_changes match names case-insensitively; a file
that sets one CVar twice is read like the client reads it (the last line wins). apply_cvar_changes:

- set: the first line of that CVar is rewritten in place (its spelling and line ending kept; untouched when the
  value is already that), later lines of it are removed; a CVar the file lacks is appended with the file's newline
  (a missing final newline is added first);
- remove: every line of that CVar goes (removing one the file lacks changes nothing);
- every other byte stays.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

__all__ = ["CvarFile", "CvarLine", "apply_cvar_changes", "parse_cvars"]

DEFAULT_NEWLINE = b"\r\n"  # an empty file, or one without a line ending, gets the client files' CRLF
_ENCODING = "utf-8"
_ERRORS = "surrogateescape"
_SET = re.compile(rb'SET ([^\s"]+) "(.*)"')
_NAME = re.compile(r'[^\s"]+', re.ASCII)  # the same whitespace as _SET's bytes \s, so the writer takes every name read


@dataclass(frozen=True)
class CvarLine:
    name: str
    value: str
    span: tuple[int, int]  # the whole line with its own ending


@dataclass(frozen=True)
class CvarFile:
    lines: tuple[CvarLine, ...]
    newline: bytes

    def get(self, name: str) -> str | None:
        """The value the client would read (the last line of that name, in any case), None when not set."""
        key = name.casefold()
        for line in reversed(self.lines):
            if line.name.casefold() == key:
                return line.value
        return None


def _decode(raw: bytes) -> str:
    return raw.decode(_ENCODING, _ERRORS)


def parse_cvars(data: bytes) -> CvarFile:
    """The SET lines of a config-cache.wtf or Config.wtf. The newline is the first line's (CRLF when it has none)."""
    first = data.find(b"\n")
    newline = DEFAULT_NEWLINE if first < 0 else (b"\r\n" if data[first - 1:first] == b"\r" else b"\n")
    lines: list[CvarLine] = []
    start = 0
    while start < len(data):
        stop = data.find(b"\n", start)
        end = len(data) if stop < 0 else stop + 1
        text_end = stop if stop >= 0 else len(data)
        if text_end > start and data[text_end - 1:text_end] == b"\r":
            text_end -= 1
        match = _SET.fullmatch(data, start, text_end)
        if match:
            lines.append(CvarLine(_decode(match.group(1)), _decode(match.group(2)), (start, end)))
        start = end
    return CvarFile(tuple(lines), newline)


def _set_line(name: str, value: str) -> bytes:
    return f'SET {name} "{value}"'.encode(_ENCODING, _ERRORS)


def apply_cvar_changes(data: bytes, parsed: CvarFile, sets: Mapping[str, str], removes: Collection[str]) -> bytes:
    """`data` (as `parsed` read it) with `sets` and `removes` applied (see the module docstring). Raises ValueError for
    a name that is empty or holds ASCII whitespace or a quote, a value with a line break, or a CVar both set and
    removed."""
    wanted = {name.casefold(): (name, value) for name, value in sets.items()}
    dropped = {name.casefold() for name in removes}
    for name, value in sets.items():
        if not _NAME.fullmatch(name):
            raise ValueError(f"not a CVar name: {name!r}")
        if "\r" in value or "\n" in value:
            raise ValueError(f"the value of {name} has a line break")
    if len(wanted) != len(sets) or wanted.keys() & dropped:
        raise ValueError("a CVar is both set and removed, or set twice")
    edits: dict[int, tuple[int, bytes]] = {}  # line start -> (line end, new bytes)
    done: set[str] = set()
    for line in parsed.lines:
        key = line.name.casefold()
        start, end = line.span
        if key in dropped or key in done:
            edits[start] = (end, b"")
        elif key in wanted:
            done.add(key)
            value = wanted[key][1]
            if value != line.value:
                ending = data[start:end][len(data[start:end].rstrip(b"\r\n")):]
                edits[start] = (end, _set_line(line.name, value) + ending)
    out = bytearray()
    at = 0
    for start in sorted(edits):
        end, new = edits[start]
        out += data[at:start] + new
        at = end
    out += data[at:]
    added = [_set_line(name, value) + parsed.newline for key, (name, value) in wanted.items() if key not in done]
    if added and out and not out.endswith(b"\n"):
        out += parsed.newline
    return bytes(out) + b"".join(added)
