"""Read WoW SavedVariables files (Lua) with byte spans, and splice edits into them. UI-free; shared by Ace3 Profile
Manager (its spec §5.1) and Saved Variables Browser (its D18, D20).

WoW writes SavedVariables as `Name = value` assignments: tables, strings, numbers, booleans and nil, usually CRLF and
unindented. This reader works on the raw bytes and records where every key and value starts and ends, so a caller
can change a few exact spans and leave every other byte as it was. Nothing here ever re-serializes a file.

parse() only builds the tables its `descend(path)` accepts; any other table is skipped by a fast scan that finds
its closing brace (strings, comments and nested braces are honoured) and becomes an Opaque value. parse_at() parses
one value at an offset (an Opaque expanded later), and iter_scalars() streams every scalar of a file without building
Table or Field objects (a search over a 50 MB file). encode_value() / encode_key() write the Lua for an edit, and
key_id() keys dicts by Lua key identity.
"""
from __future__ import annotations

import re
import math
from collections.abc import Callable, Iterator
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
# Lua 5.1 (WoW's) escapes: \ddd, a backslash-newline, the letter escapes; any other escaped byte stands for itself
# (5.2's `\x41` and `\z` are not escapes there: they read "x41" and "z").
_ESCAPE = re.compile(rb"\\(?:(\d{1,3})|(\r\n|\n\r|\n|\r)|(.))", re.DOTALL)
_SIMPLE_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"a": b"\a", b"b": b"\b", b"f": b"\f", b"v": b"\v",
                   b"\\": b"\\", b'"': b'"', b"'": b"'"}
# The rest of an entry's line: blanks, then maybe a line comment (WoW's `-- [n]` after an array entry, never the
# start of a long comment, which may run on), then the line ending.
_LINE_REST = re.compile(rb"[ \t]*(?:--(?!\[=*\[)[^\r\n]*)?(?:\r\n|\n|\r)")
_KEYWORDS = {b"true": True, b"false": False, b"nil": None}


class LuaParseError(ValueError):
    def __init__(self, offset: int, message: str) -> None:
        super().__init__(f"{message} at byte {offset}")
        self.offset = offset


@dataclass(frozen=True)
class RawNumber:
    """A number Python can't read as int or float (1.#INF, -nan(ind)): kept as its text."""
    text: str


@dataclass(slots=True)
class Scalar:
    start: int
    end: int
    value: str | int | float | bool | RawNumber | None


@dataclass(slots=True)
class Opaque:
    """A table that was not descended into: only its extent is known."""
    start: int
    end: int


@dataclass(slots=True)
class Field:
    key: object
    key_span: tuple[int, int] | None
    value: Table | Opaque | Scalar
    entry_start: int
    entry_end: int
    remove_span: tuple[int, int]


@dataclass(slots=True)
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


@dataclass(slots=True)
class Assignment:
    name: str
    start: int
    end: int
    value: Value


@dataclass(slots=True)
class Chunk:
    assignments: list[Assignment] = dc_field(default_factory=list)

    def get(self, name: str) -> Assignment | None:
        for item in self.assignments:
            if item.name == name:
                return item
        return None


def decode_string(raw: bytes) -> str:
    """The text of a Lua string literal (quotes included), read as Lua 5.1 reads it. Bytes that aren't UTF-8 survive
    as surrogates."""
    body = raw[1:-1]

    def one(match: re.Match) -> bytes:
        decimal, newline, other = match.groups()
        if decimal is not None:
            return bytes([int(decimal) & 0xFF])
        if newline is not None:
            return b"\n"
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


def encode_value(value: str | float | bool | RawNumber) -> bytes:
    """The Lua for a scalar value. A float must read back as the same number, so inf and nan are refused (Python
    writes `inf`, which Lua reads as a variable: nil). nil is never written: setting nil is a delete."""
    if isinstance(value, str):
        return encode_string(value)
    if isinstance(value, bool):
        return b"true" if value else b"false"
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{value!r} cannot be written as a Lua number")
        return repr(value).encode("ascii")
    if isinstance(value, RawNumber):
        return value.text.encode("ascii")
    if value is None:
        raise ValueError("nil is not a value to write (delete the key instead)")
    raise TypeError(f"not a Lua scalar: {value!r}")


def encode_key(key: str | float | bool | RawNumber) -> bytes:
    """A table key, always in bracket form (`["s"]`, `[5]`, `[1.5]`, `[true]`): never a bare name, so a reserved
    word such as `end` is safe."""
    return b"[" + encode_value(key) + b"]"


def key_id(key: object) -> tuple[str, object]:
    """A key's identity in Lua, for dict keys: in Python 1, True and 1.0 are equal and hash alike; in Lua true and 1
    are different keys, while [1.0] is the same key as [1]."""
    if isinstance(key, float) and key.is_integer():
        return ("int", int(key))
    return (type(key).__name__, key)


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
        if self.data[pos:pos + 1] == b"{":
            if self.descend(path):
                return self.table(pos, path)
            end = self.skip_table(pos)
            return Opaque(pos, end), end
        scalar = self.scalar(pos)
        return scalar, scalar.end

    def scalar(self, pos: int) -> Scalar:
        data = self.data
        if pos >= self.size:
            raise LuaParseError(pos, "expected a value")
        head = data[pos:pos + 1]
        if head in (b'"', b"'"):
            match = _STRING.match(data, pos)
            if not match:
                raise LuaParseError(pos, "unterminated string")
            return Scalar(pos, match.end(), decode_string(match.group()))
        number = _NUMBER.match(data, pos)
        if number and number.end() > pos:
            return Scalar(pos, number.end(), _number(number.group()))
        name = _NAME.match(data, pos)
        if name and name.group() in _KEYWORDS:
            return Scalar(pos, name.end(), _KEYWORDS[name.group()])
        raise LuaParseError(pos, "expected a value")

    def key(self, pos: int, index: int) -> tuple[object, tuple[int, int] | None, int, int]:
        """The key of the table entry at pos (its first byte): (key, key span, value position, next index). A
        positional entry gets the next index and no span."""
        data = self.data
        if data[pos:pos + 1] == b"[" and data[pos + 1:pos + 2] not in (b"[", b"="):
            at = self.skip(pos + 1)
            if data[at:at + 1] == b"{":
                raise LuaParseError(pos, "bad table key")
            key_value = self.scalar(at)
            if key_value.value is None:
                raise LuaParseError(pos, "bad table key")
            after = self.expect(key_value.end, b"]")
            return key_value.value, (pos, after), self.skip(self.expect(after, b"=")), index
        name = _NAME.match(data, pos)
        after_name = self.skip(name.end()) if name else pos
        if name and name.group() not in _KEYWORDS and data[after_name:after_name + 1] == b"=" \
                and data[after_name + 1:after_name + 2] != b"=":
            return name.group().decode("ascii"), (pos, name.end()), self.skip(after_name + 1), index
        return index, None, pos, index + 1

    def separator(self, end: int) -> int:
        """Past the `,` or `;` after an entry's value ending at end; at the `}` when there is none."""
        pos = self.skip(end)
        separator = self.data[pos:pos + 1]
        if separator in (b",", b";"):
            return pos + 1
        if separator != b"}":
            raise LuaParseError(pos, "expected ',' or '}'")
        return pos

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
            key, key_span, pos, index = self.key(pos, index)
            value, end = self.value(pos, path + (key,))
            pos = entry_end = self.separator(end)
            remove_start, remove_end = entry_start, entry_end
            rest = _LINE_REST.match(data, entry_end)
            line = line_start(data, entry_start)
            if rest and not data[line:entry_start].strip(b" \t"):
                remove_start, remove_end = line, rest.end()
            table.fields.append(Field(key, key_span, value, entry_start, entry_end, (remove_start, remove_end)))


    def scalars(self) -> Iterator[tuple[tuple, object, tuple[int, int] | None, Scalar]]:
        """iter_scalars(): the chunk() and table() walk with an explicit stack and no Table or Field objects."""
        data = self.data
        pos = self.skip(0)
        while pos < self.size:
            if data[pos:pos + 1] == b";":
                pos = self.skip(pos + 1)
                continue
            name = _NAME.match(data, pos)
            if not name:
                raise LuaParseError(pos, "expected a variable name")
            text = name.group().decode("ascii")
            at = self.skip(self.expect(name.end(), b"="))
            if data[at:at + 1] == b"{":
                if self.descend((text,)):
                    pos = yield from self.table_scalars(at, (text,))
                else:
                    pos = self.skip_table(at)
            else:
                scalar = self.scalar(at)
                yield (), text, (pos, name.end()), scalar
                pos = scalar.end
            pos = self.skip(pos)

    def table_scalars(self, pos: int, path: tuple) -> Iterator[tuple[tuple, object, tuple[int, int] | None, Scalar]]:
        data = self.data
        stack = [(path, pos, 1)]  # (table path, table start, next positional index)
        pos += 1
        while True:
            pos = self.skip(pos)
            if pos >= self.size:
                raise LuaParseError(stack[-1][1], "unclosed table")
            if data[pos:pos + 1] == b"}":
                stack.pop()
                if not stack:
                    return pos + 1
                pos = self.separator(pos + 1)
                continue
            table_path, start, index = stack[-1]
            key, key_span, pos, index = self.key(pos, index)
            stack[-1] = (table_path, start, index)
            if data[pos:pos + 1] == b"{":
                inner = table_path + (key,)
                if self.descend(inner):
                    stack.append((inner, pos, 1))
                    pos += 1
                    continue
                end = self.skip_table(pos)
            else:
                scalar = self.scalar(pos)
                yield table_path, key, key_span, scalar
                end = scalar.end
            pos = self.separator(end)


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


def parse_at(data: bytes, start: int, path: tuple = (), descend: Callable[[tuple], bool] = lambda path: True,
             ) -> tuple[Value, int]:
    """Parse the one value at start (blanks and comments before it are skipped): (value, its end offset). For a
    lazy tree, start is an Opaque's start and path its path, which descend() is first asked about."""
    parser = _Parser(data, descend)
    return parser.value(parser.skip(start), path)


def iter_scalars(data: bytes, descend: Callable[[tuple], bool] = lambda path: True,
                 ) -> Iterator[tuple[tuple, object, tuple[int, int] | None, Scalar]]:
    """Every scalar of a SavedVariables file in file order, as (path, key, key span, Scalar), building no Table or
    Field objects. path is the containing table's path (the tuple descend() gets: the variable name, then the keys,
    each of its own type); it is () for a top-level `Name = value`, whose key is the name and key span the name's.
    A positional entry's key is its index and its key span None. A table descend() refuses is skipped. Raises
    LuaParseError like parse(), once the stream reaches the fault."""
    return _Parser(data, descend).scalars()
