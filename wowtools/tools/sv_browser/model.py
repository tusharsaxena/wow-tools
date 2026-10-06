"""The lazy tree model of one SavedVariables file (spec D5, D17, D18), and the display text of its nodes. UI-free.

A file is read once, when its roots are first asked for (its SHA-256 is recorded then, for D17), and parsed one level
ahead of what is shown: the file's top-level assignments are built with their own tables' entries (so a table node
knows its size, `{N}`), and every table below stays an Opaque span until its parent is opened. Opening a table node
parses just that table's span (luasv.parse_at), again one level ahead. A table shows its first CHILD_CAP children and
a "… N more" leaf. A file that can't be read, or a table whose span is not readable Lua, becomes an error node: the
model never raises.

Each node carries its key (typed; typed_key = luasv.key_id, its identity), the key's span (a top-level
assignment's is its name; None for a positional array entry), its value (a luasv Scalar, Table or Opaque, with its
span), its path from the top-level name, its remove span, and what D5 allows on it: a value edit on any scalar (a
top-level one included), a rename on a written key below the top level, a delete on anything below the top level.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.luasv import LuaParseError, Opaque, RawNumber, Scalar, Table, key_id, parse, parse_at
from wowtools.core.svfiles import SvFile, sha256_of

CHILD_CAP = 500  # children a table shows before its "… N more" leaf (D18)
VALUE_WIDTH = 60  # characters a string value shows, quotes and ellipsis included
ELLIPSIS = "…"

VALUE, MORE, ERROR = "value", "more", "error"  # Node.kind


@dataclass(slots=True, eq=False)
class Node:
    """One row under a file: a top-level assignment or table entry (kind "value"), the "… N more" leaf of a capped
    table (kind "more", `more` = children not shown), or a part that can't be read (kind "error", `error`)."""
    kind: str
    key: object = None
    key_span: tuple[int, int] | None = None
    value: Scalar | Table | Opaque | None = None
    path: tuple = ()
    parent: Node | None = None
    top_level: bool = False
    positional: bool = False
    remove_span: tuple[int, int] | None = None
    children: list[Node] | None = None  # None until the node is opened (SvDocument.children)
    more: int = 0
    error: str | None = None

    @property
    def typed_key(self) -> tuple[str, object] | None:
        """luasv.key_id of the key: its identity in Lua (true and 1 differ, [1.0] is [1]); None for a more/error
        node."""
        return key_id(self.key) if self.kind == VALUE else None

    @property
    def is_table(self) -> bool:
        return self.kind == VALUE and isinstance(self.value, (Table, Opaque))

    @property
    def is_scalar(self) -> bool:
        return self.kind == VALUE and isinstance(self.value, Scalar)

    @property
    def count(self) -> int | None:
        """A table's number of entries, None for a scalar or a table not parsed yet."""
        return len(self.value.fields) if self.kind == VALUE and isinstance(self.value, Table) else None

    @property
    def can_edit_value(self) -> bool:
        return self.is_scalar

    @property
    def can_rename(self) -> bool:
        return self.kind == VALUE and not self.top_level and not self.positional

    @property
    def can_delete(self) -> bool:
        return self.kind == VALUE and not self.top_level


def _one_level_ahead(depth: int):
    """descend for a parse that builds the tables at path length depth and depth + 1 (their entries' tables stay
    Opaque)."""
    return lambda path: len(path) <= depth + 1


class SvDocument:
    """One SavedVariables file, read on first use. roots() are its top-level assignments; children(node) opens a
    table node."""

    def __init__(self, file: SvFile) -> None:
        self.file = file
        self.data: bytes | None = None
        self.sha256: str | None = None
        self.error: str | None = None
        self._roots: list[Node] | None = None

    @property
    def loaded(self) -> bool:
        return self._roots is not None

    def _unreadable(self, message: str, error: object) -> Node:
        log_event("svb.file_unreadable", flavor=self.file.flavor.folder, path=self.file.rel, error=str(error))
        return Node(ERROR, error=message)

    def roots(self) -> list[Node]:
        if self._roots is not None:
            return self._roots
        path: Path = self.file.path
        try:
            self.data = path.read_bytes()
        except OSError as exc:
            self.error = f"could not read {path.name}: {exc.strerror or exc}"
            self._roots = [self._unreadable(self.error, exc)]
            return self._roots
        self.sha256 = sha256_of(self.data)
        try:
            chunk = parse(self.data, _one_level_ahead(0))
        except LuaParseError as exc:
            self.error = f"{path.name} is not readable Lua ({exc})"
            self._roots = [self._unreadable(self.error, exc)]
            return self._roots
        nodes = [Node(VALUE, a.name, (a.start, a.start + len(a.name)), a.value, (a.name,), top_level=True)
                 for a in chunk.assignments]
        self._roots = _capped(nodes)
        return self._roots

    def children(self, node: Node) -> list[Node]:
        """The node's children, parsed from its span the first time (one level ahead); [] for anything but a
        table."""
        if node.children is not None:
            return node.children
        if not node.is_table or self.data is None:
            return []
        try:
            table, _ = parse_at(self.data, node.value.start, node.path, _one_level_ahead(len(node.path)))
        except LuaParseError as exc:
            node.children = [self._unreadable(f"this table is not readable Lua ({exc})", exc)]
            return node.children
        assert isinstance(table, Table)
        node.value = table
        node.children = _capped([Node(VALUE, f.key, f.key_span, f.value, node.path + (f.key,), node,
                                      positional=f.key_span is None, remove_span=f.remove_span)
                                 for f in table.fields], node)
        return node.children


def _capped(nodes: list[Node], parent: Node | None = None) -> list[Node]:
    if len(nodes) <= CHILD_CAP:
        return nodes
    return nodes[:CHILD_CAP] + [Node(MORE, parent=parent, more=len(nodes) - CHILD_CAP)]


# Display text (the review's tree labels). Plain text: the UI must not read it as markup ([5] is a key).

_SHOWN_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escaped(text: str) -> str:
    """Text as a Lua string body: backslash, quote, newlines and tabs escaped, other control characters and bytes
    that aren't UTF-8 (surrogates) as \\ddd."""
    out = []
    for char in text:
        if char in _SHOWN_ESCAPES:
            out.append(_SHOWN_ESCAPES[char])
        elif "\udc80" <= char <= "\udcff":
            out.append(f"\\{ord(char) - 0xDC00}")
        elif char < " " or char == "\x7f":
            out.append(f"\\{ord(char):03d}")
        else:
            out.append(char)
    return "".join(out)


def _number_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, RawNumber):
        return value.text
    return str(value)


def key_text(key: object) -> str:
    """A key as the tree shows it: a string key bare (`font`), any other in brackets (`[5]`, `[true]`, `[2.5]`)."""
    if isinstance(key, str):
        return _escaped(key) if key else '[""]'
    return f"[{_number_text(key)}]"


def scalar_text(value: object, raw: bytes | None = None, width: int = VALUE_WIDTH) -> str:
    """A scalar as the tree shows it: a string in double quotes, cut to `width` characters with an ellipsis; a
    number as written in the file (raw, its bytes) or else as Python writes it; true, false, nil."""
    if value is None:
        return "nil"
    if isinstance(value, str):
        body = _escaped(value)
        if len(body) + 2 > width:
            body = body[:max(width - 3, 0)] + ELLIPSIS
        return f'"{body}"'
    if raw is not None and not isinstance(value, bool):
        return raw.decode("ascii", "replace")
    return _number_text(value)


def table_text(count: int | None) -> str:
    """A table's size: {N}, or {…} when its entries are not parsed yet."""
    return "{…}" if count is None else f"{{{count:,}}}"


def node_text(node: Node, data: bytes | None) -> str:
    """The tree label of a node: `key = value`, `key {N}`, `… N more` or `can't read: …`."""
    if node.kind == MORE:
        return f"{ELLIPSIS} {node.more:,} more"
    if node.kind == ERROR:
        return f"can't read: {node.error}"
    if node.is_table:
        return f"{key_text(node.key)} {table_text(node.count)}"
    scalar = node.value
    raw = data[scalar.start:scalar.end] if data is not None else None
    return f"{key_text(node.key)} = {scalar_text(scalar.value, raw)}"
