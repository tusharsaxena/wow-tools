"""Read WoW SavedVariables files (Lua) with byte spans, and splice edits into them (spec §5.1). UI-free.

WoW writes SavedVariables as `Name = value` assignments: tables, strings, numbers, booleans and nil, usually CRLF and
unindented. This reader works on the raw bytes and records where every key and value starts and ends, so a caller
can change a few exact spans and leave every other byte as it was. Nothing here ever re-serializes a file.

parse() only builds the tables its `descend(path)` accepts; any other table is skipped by a fast scan that finds
its closing brace (strings, comments and nested braces are honoured) and becomes an Opaque value.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field as dc_field
from itertools import pairwise

_WS = re.compile(rb"[ \t\r\n\f\v]*")
_LONG_COMMENT = re.compile(rb"--\[(=*)\[.*?\]\1\]", re.DOTALL)
_NAME = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")
_STRING = re.compile(rb'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', re.DOTALL)
_NUMBER = re.compile(rb"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?(?:#[A-Za-z]+\d*)?)"
                     rb"|-?(?:inf|nan)(?:\([a-z]*\))?", re.IGNORECASE)
_INT = re.compile(rb"-?\d+")
_SKIP = re.compile(rb'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|--\[(=*)\[.*?\]\1\]|--[^\n]*|[{}]', re.DOTALL)
_ESCAPE = re.compile(rb"\\(?:(\d{1,3})|x([0-9a-fA-F]{2})|(\r\n|\n\r|\n|\r)|z\s*|(.))", re.DOTALL)
_SIMPLE_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"a": b"\a", b"b": b"\b", b"f": b"\f", b"v": b"\v",
                   b"\\": b"\\", b'"': b'"', b"'": b"'"}
_LINE_REST = re.compile(rb"[ \t]*(?:\r\n|\n|\r)")
_KEYWORDS = {b"true": True, b"false": False, b"nil": None}


class LuaParseError(ValueError):
    def __init__(self, offset: int, message: str) -> None:
        super().__init__(f"{message} at byte {offset}")
        self.offset = offset


@dataclass(frozen=True)
class RawNumber:
    """A number Python can't read as int or float (1.#INF, -nan(ind)): kept as its text."""
    text: str


@dataclass
class Scalar:
    start: int
    end: int
    value: str | int | float | bool | RawNumber | None


@dataclass
class Opaque:
    """A table that was not descended into: only its extent is known."""
    start: int
    end: int


@dataclass
class Field:
    key: object
    key_span: tuple[int, int] | None
    value: Table | Opaque | Scalar
    entry_start: int
    entry_end: int
    remove_span: tuple[int, int]


@dataclass
class Table:
    start: int
    end: int
    fields: list[Field] = dc_field(default_factory=list)

    @property
    def close(self) -> int:
        return self.end - 1

    def get(self, key: object) -> Field | None:
        found = None
        for item in self.fields:
            if item.key == key and type(item.key) is type(key):
                found = item
        return found

    def keys(self) -> list:
        return [item.key for item in self.fields]


Value = Table | Opaque | Scalar


@dataclass
class Assignment:
    name: str
    start: int
    end: int
    value: Value


@dataclass
class Chunk:
    assignments: list[Assignment] = dc_field(default_factory=list)

    def get(self, name: str) -> Assignment | None:
        for item in self.assignments:
            if item.name == name:
                return item
        return None


def decode_string(raw: bytes) -> str:
    """The text of a Lua string literal (quotes included). Bytes that aren't UTF-8 survive as surrogates."""
    body = raw[1:-1]

    def one(match: re.Match) -> bytes:
        decimal, hexa, newline, other = match.groups()
        if decimal is not None:
            return bytes([int(decimal) & 0xFF])
        if hexa is not None:
            return bytes([int(hexa, 16)])
        if newline is not None:
            return b"\n"
        if other is None:  # \z: skips the following whitespace
            return b""
        return _SIMPLE_ESCAPES.get(other, other)

    return _ESCAPE.sub(one, body).decode("utf-8", "surrogateescape")


def encode_string(text: str) -> bytes:
    """A double-quoted Lua string literal for text: `\\`, `"`, CR, LF and other control bytes escaped."""
    out = bytearray(b'"')
    for byte in text.encode("utf-8", "surrogateescape"):
        if byte == 0x5C:
            out += b"\\\\"
        elif byte == 0x22:
            out += b'\\"'
        elif byte == 0x0A:
            out += b"\\n"
        elif byte == 0x0D:
            out += b"\\r"
        elif byte < 0x20 or byte == 0x7F:
            out += b"\\%03d" % byte
        else:
            out.append(byte)
    out += b'"'
    return bytes(out)


def newline_of(data: bytes) -> bytes:
    index = data.find(b"\n")
    return b"\r\n" if index > 0 and data[index - 1:index] == b"\r" else b"\n"


def line_start(data: bytes, offset: int) -> int:
    return data.rfind(b"\n", 0, offset) + 1


def is_blank_table(data: bytes, value: Table | Opaque) -> bool:
    inner = data[value.start + 1:value.end - 1]
    pos = 0
    while True:
        pos = _WS.match(inner, pos).end()
        if inner.startswith(b"--", pos):
            long = _LONG_COMMENT.match(inner, pos)
            if long:
                pos = long.end()
                continue
            newline = inner.find(b"\n", pos)
            pos = len(inner) if newline < 0 else newline + 1
            continue
        return pos == len(inner)


def splice(data: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    """Apply (start, end, replacement) edits. They must not overlap; an insert (start == end) may sit at the end of
    another edit's span."""
    ordered = sorted(edits, key=lambda e: (e[0], e[1]))
    for (s1, e1, _), (s2, e2, _) in pairwise(ordered):
        if s2 < e1:
            raise ValueError(f"overlapping edits at {s1}-{e1} and {s2}-{e2}")
    out = []
    pos = 0
    for start, end, replacement in ordered:
        out.append(data[pos:start])
        out.append(replacement)
        pos = end
    out.append(data[pos:])
    return b"".join(out)


class _Parser:
    def __init__(self, data: bytes, descend: Callable[[tuple], bool]) -> None:
        self.data = data
        self.descend = descend
        self.size = len(data)

    def skip(self, pos: int) -> int:
        data = self.data
        while True:
            pos = _WS.match(data, pos).end()
            if data.startswith(b"--", pos):
                long = _LONG_COMMENT.match(data, pos)
                if long:
                    pos = long.end()
                    continue
                newline = data.find(b"\n", pos)
                pos = self.size if newline < 0 else newline + 1
                continue
            return pos

    def expect(self, pos: int, token: bytes) -> int:
        pos = self.skip(pos)
        if not self.data.startswith(token, pos):
            raise LuaParseError(pos, f"expected {token.decode()!r}")
        return pos + len(token)

    def chunk(self) -> Chunk:
        chunk = Chunk()
        pos = self.skip(0)
        while pos < self.size:
            if self.data[pos:pos + 1] == b";":
                pos = self.skip(pos + 1)
                continue
            name = _NAME.match(self.data, pos)
            if not name:
                raise LuaParseError(pos, "expected a variable name")
            text = name.group().decode("ascii")
            after = self.expect(name.end(), b"=")
            value, end = self.value(self.skip(after), (text,))
            chunk.assignments.append(Assignment(text, pos, end, value))
            pos = self.skip(end)
        return chunk

    def value(self, pos: int, path: tuple) -> tuple[Value, int]:
        data = self.data
        if pos >= self.size:
            raise LuaParseError(pos, "expected a value")
        head = data[pos:pos + 1]
        if head == b"{":
            if self.descend(path):
                return self.table(pos, path)
            end = self.skip_table(pos)
            return Opaque(pos, end), end
        if head in (b'"', b"'"):
            match = _STRING.match(data, pos)
            if not match:
                raise LuaParseError(pos, "unterminated string")
            return Scalar(pos, match.end(), decode_string(match.group())), match.end()
        number = _NUMBER.match(data, pos)
        if number and number.end() > pos:
            return Scalar(pos, number.end(), _number(number.group())), number.end()
        name = _NAME.match(data, pos)
        if name and name.group() in _KEYWORDS:
            return Scalar(pos, name.end(), _KEYWORDS[name.group()]), name.end()
        raise LuaParseError(pos, "expected a value")

    def skip_table(self, pos: int) -> int:
        depth = 0
        for match in _SKIP.finditer(self.data, pos):
            token = match.group()
            if token == b"{":
                depth += 1
            elif token == b"}":
                depth -= 1
                if depth == 0:
                    return match.end()
        raise LuaParseError(pos, "unclosed table")

    def table(self, pos: int, path: tuple) -> tuple[Table, int]:
        data = self.data
        table = Table(pos, -1)
        index = 1
        pos += 1
        while True:
            pos = self.skip(pos)
            if pos >= self.size:
                raise LuaParseError(table.start, "unclosed table")
            if data[pos:pos + 1] == b"}":
                table.end = pos + 1
                return table, pos + 1
            entry_start = pos
            if data[pos:pos + 1] == b"[" and data[pos + 1:pos + 2] not in (b"[", b"="):
                key_value, after = self.value(self.skip(pos + 1), path)
                if not isinstance(key_value, Scalar) or key_value.value is None:
                    raise LuaParseError(pos, "bad table key")
                after = self.expect(after, b"]")
                key, key_span = key_value.value, (entry_start, after)
                pos = self.skip(self.expect(after, b"="))
            else:
                name = _NAME.match(data, pos)
                after_name = self.skip(name.end()) if name else pos
                if name and name.group() not in _KEYWORDS and data[after_name:after_name + 1] == b"=" \
                        and data[after_name + 1:after_name + 2] != b"=":
                    key, key_span = name.group().decode("ascii"), (entry_start, name.end())
                    pos = self.skip(after_name + 1)
                else:
                    key, key_span = index, None
                    index += 1
            value, end = self.value(pos, path + (key,))
            pos = self.skip(end)
            separator = data[pos:pos + 1]
            if separator in (b",", b";"):
                pos += 1
            elif separator != b"}":
                raise LuaParseError(pos, "expected ',' or '}'")
            entry_end = pos
            remove_start, remove_end = entry_start, entry_end
            rest = _LINE_REST.match(data, entry_end)
            line = line_start(data, entry_start)
            if rest and not data[line:entry_start].strip(b" \t"):
                remove_start, remove_end = line, rest.end()
            table.fields.append(Field(key, key_span, value, entry_start, entry_end, (remove_start, remove_end)))


def _number(text: bytes) -> int | float | RawNumber:
    if _INT.fullmatch(text):
        return int(text)
    try:
        if text.lower().startswith((b"0x", b"-0x")):
            return int(text, 16)
        return float(text)
    except ValueError:
        return RawNumber(text.decode("ascii", "replace"))


def parse(data: bytes, descend: Callable[[tuple], bool] = lambda path: True) -> Chunk:
    """Parse a SavedVariables file. Raises LuaParseError (with the byte offset) on anything that isn't one."""
    return _Parser(data, descend).chunk()
