"""Macro syntax for the Macro Editor's help panel, suggestions and optimizer (config tools spec ME8, ME10). UI-free.

A macro body is lines joined with "\\n". A line is a command (`/cast ...`), a metacommand (`#showtooltip`, `#show`),
a comment (any other `#` line, which the client skips) or plain text (said in chat). Only a command that reads
conditions (a secure command: `options` true in wowtools/kb/macro_reference.json) has its argument split into
`;` clauses, `[...]` condition blocks and their conditionals; any other command's argument (`/say`, `/run`) is one
text token, so nothing in it is ever read or rewritten as a condition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from wowtools.core.kb import MacroReference, load_macro_reference

__all__ = ["DIRECTIVES", "Clause", "Line", "Token", "lines", "option_commands", "parse_line", "suggestions", "token_at",
           "tokenize"]

DIRECTIVES = ("#showtooltip", "#show")  # written in lower case, or the client skips the line
TokenKind = Literal["command", "condition_block", "condition", "unit", "text", "comment", "directive"]
_COMMAND = re.compile(r"/\S*")


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    start: int  # offsets in the body
    end: int


@dataclass(frozen=True)
class Clause:
    """One `;` clause of a command that reads conditions: its [...] blocks (each with its conditionals and units)
    and its value (the spell or item name), None when the clause has none."""
    blocks: tuple[tuple[Token, tuple[Token, ...]], ...]
    value: Token | None


@dataclass(frozen=True)
class Line:
    start: int
    text: str
    head: Token | None                   # the command, directive or comment token
    clauses: tuple[Clause, ...] = ()     # a command or directive that reads conditions
    rest: Token | None = None            # the argument of one that doesn't (one text token)
    options: bool = False
    tokens: tuple[Token, ...] = field(default=())


def _reference() -> MacroReference:
    return load_macro_reference("")  # the shipped reference; commands are not per flavor


def option_commands(ref: MacroReference | None = None) -> frozenset[str]:
    """Every command name and alias (lower case) whose argument reads conditions."""
    ref = ref or _reference()
    return frozenset(name for name, info in ref.commands.items() if info.options)


def _trimmed(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _token(kind: TokenKind, line: str, base: int, start: int, end: int) -> Token | None:
    start, end = _trimmed(line, start, end)
    return Token(kind, line[start:end], base + start, base + end) if end > start else None


def _clauses(line: str, base: int, start: int) -> list[Clause]:
    out: list[Clause] = []
    pos = start
    while pos <= len(line):
        stop = line.find(";", pos)
        stop = len(line) if stop < 0 else stop
        blocks: list[tuple[Token, tuple[Token, ...]]] = []
        cur = pos
        while True:
            while cur < stop and line[cur].isspace():
                cur += 1
            if cur >= stop or line[cur] != "[":
                break
            close = line.find("]", cur, stop)
            close = stop - 1 if close < 0 else close
            block = Token("condition_block", line[cur:close + 1], base + cur, base + close + 1)
            items: list[Token] = []
            item_start = cur + 1
            inner_end = close if line[close] == "]" else close + 1
            for i in range(cur + 1, inner_end + 1):
                if i == inner_end or line[i] == ",":
                    a, b = _trimmed(line, item_start, i)
                    if b > a:
                        word = line[a:b]
                        kind: TokenKind = "unit" if word.startswith("@") or word.lower().startswith("target=") \
                            else "condition"
                        items.append(Token(kind, word, base + a, base + b))
                    item_start = i + 1
            blocks.append((block, tuple(items)))
            cur = close + 1
        out.append(Clause(tuple(blocks), _token("text", line, base, cur, stop)))
        pos = stop + 1
    return out


def parse_line(line: str, start: int, options: frozenset[str] | None = None) -> Line:
    """One body line, `start` its offset in the body."""
    options = option_commands() if options is None else options
    stripped = line.lstrip()
    lead = len(line) - len(stripped)
    if not stripped:
        return Line(start, line, None)
    if stripped.startswith("#"):
        word = stripped.split(None, 1)[0]
        if word in DIRECTIVES:
            head = Token("directive", word, start + lead, start + lead + len(word))
            clauses = tuple(_clauses(line, start, lead + len(word)))
            return Line(start, line, head, clauses, options=True, tokens=_flatten(head, clauses))
        head = _token("comment", line, start, 0, len(line))
        return Line(start, line, head, tokens=(head,))
    if stripped.startswith("/"):
        match = _COMMAND.match(stripped)
        end = lead + match.end()
        head = Token("command", line[lead:end], start + lead, start + end)
        if head.text.lower() in options:
            clauses = tuple(_clauses(line, start, end))
            return Line(start, line, head, clauses, options=True, tokens=_flatten(head, clauses))
        rest = _token("text", line, start, end, len(line))
        return Line(start, line, head, rest=rest, tokens=tuple(t for t in (head, rest) if t))
    rest = _token("text", line, start, 0, len(line))
    return Line(start, line, None, rest=rest, tokens=(rest,) if rest else ())


def _flatten(head: Token, clauses: tuple[Clause, ...]) -> tuple[Token, ...]:
    out = [head]
    for clause in clauses:
        for block, items in clause.blocks:
            out.append(block)
            out.extend(items)
        if clause.value is not None:
            out.append(clause.value)
    return tuple(out)


def lines(body: str, options: frozenset[str] | None = None) -> list[Line]:
    options = option_commands() if options is None else options
    out, pos = [], 0
    for text in body.split("\n"):
        out.append(parse_line(text, pos, options))
        pos += len(text) + 1
    return out


def tokenize(body: str) -> list[Token]:
    """Every token of the body in order; a condition block comes before the conditionals inside it."""
    return [token for line in lines(body) for token in line.tokens]


def token_at(body: str, offset: int) -> Token | None:
    """The innermost token under the cursor or just before it (a cursor right after `help` is on `help`); None
    between tokens."""
    tokens = tokenize(body)
    inside = [t for t in tokens if t.start <= offset <= t.end]
    return min(inside, key=lambda t: t.end - t.start) if inside else None


def _numbered(ref: MacroReference) -> list[str]:
    return [f"{name}1" for name, info in ref.units.items() if info.numbered]


def suggestions(body: str, offset: int, ref: MacroReference) -> list[tuple[str, str]]:
    """(completion, short help) for the word before the cursor. A completion replaces the part of the word after
    its last separator: the whole `/command` or `#directive`, the unit after `@`, the conditional after `[` or
    `,`, the argument after `:`. Nothing for chat text, spell names or code."""
    start = body.rfind("\n", 0, offset) + 1
    before = body[start:offset]
    word = before.lstrip()
    if re.fullmatch(r"/\S*", word):
        low = word.lower()
        return sorted({(name, info.help) for name, info in ref.commands.items() if name.startswith(low)})
    if re.fullmatch(r"#\S*", word):
        return [(d, "") for d in DIRECTIVES if d.startswith(word)]
    stop = body.find("\n", offset)
    line = parse_line(body[start:len(body) if stop < 0 else stop], start, option_commands(ref) or option_commands())
    if not line.options:
        return []
    open_at, close_at = before.rfind("["), before.rfind("]")
    if open_at < 0 or close_at > open_at:
        return []
    part = re.split(r"[,\[]", before[open_at:])[-1].lstrip()
    if part.startswith("@"):
        low = part[1:].lower()
        names = [n for n, info in ref.units.items() if not info.numbered] + _numbered(ref)
        return sorted((n, ref.units[n.rstrip("0123456789")].help) for n in names if n.startswith(low))
    if ":" in part:
        name, arg = part.split(":", 1)
        info = ref.conditionals.get(name.lower()) or ref.conditionals.get(name.lower()[2:])
        if info is None:
            return []
        return sorted((key, value) for key, value in info.arg_names.items() if key.startswith(arg.lower()))
    low = part.lower()
    out: set[tuple[str, str]] = set()
    for name, info in ref.conditionals.items():
        if name.startswith(low):
            out.add((name, info.help))
        if low.startswith("no") and f"no{name}".startswith(low):
            out.add((f"no{name}", info.help))
    return sorted(out)
