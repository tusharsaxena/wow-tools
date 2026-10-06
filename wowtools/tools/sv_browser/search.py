"""Find (and preview replacing) values across SavedVariables files (spec D6-D11). UI-free.

A SearchSpec holds the key text and the value text (either may be empty, not both), their modes, Match case, the
scope (flavor, account, character or account-wide only, addon) and the replacement. run_search() streams every file
in scope with luasv.iter_scalars (no Table or Field objects, so a 50 MB file is never built in memory), one file per
unit through core.parallel.run_units ([general] parallelism), and returns the hits in file-list and file order,
capped at HIT_CAP (the rest are counted in `dropped`).

Matching (D6-D8). Only scalar values are hits; with both a key and a value given, a hit must match both.
- Key: the key's text (a string key as it is, a number key as written: `[2.50]` is "2.50", `[0x10]` "0x10"; a
  positional entry by its index; true/false; a top-level `Name = scalar` by its name), Exact or Contains.
- Value, Whole value: a string's decoded text equals the needle, or a number's or boolean's written text does.
  nil is never a value hit (a key search does find it).
- Value, Contains: strings only; the replacement text takes the place of every occurrence (re.escape, so the needle
  is never a pattern, and the replacement is never a template).
- Match case off: Exact and Whole compare casefold(); Contains is re.IGNORECASE.

Replacement (D10): a typed value (string, number, boolean) for whole values; text for Contains; None for a find only
(hits then have no new value). A number must read back in Lua as exactly that number: finite, an int within 2^53.
parse_replacement() turns what the user typed into that value.

Byte pre-filter: a file is only parsed when its bytes can hold every needle. That is checked with bytes.find (on
lowered bytes when match case is off), and only when it is safe: the needle has no quote, backslash or control
character (escapes write those differently), is not a run of digits for a key (an array index is never written), and
is ASCII when match case is off; and the file has no escape that could hide a plain character (`\\070`, `\\x`, `\\F`:
Lua 5.1 reads an unknown escape letter as the letter; an escaped backslash `\\\\` is one escape, so WoW's
`Interface\\\\Icons` paths never count) nor, when match case is off, a character that folds into ASCII
(FOLDS_TO_ASCII: `K` (Kelvin) matches "k").
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation

from wowtools.core.events import log_event
from wowtools.core.luasv import LuaParseError, RawNumber, Scalar, encode_value, iter_scalars, key_id
from wowtools.core.parallel import run_units
from wowtools.core.svfiles import SvFile, sha256_of

KEY_EXACT, KEY_CONTAINS = "exact", "contains"
VALUE_WHOLE, VALUE_CONTAINS = "whole", "contains"
REPLACE_STRING, REPLACE_NUMBER, REPLACE_BOOLEAN = "string", "number", "boolean"

HIT_CAP = 10_000  # hits a search keeps (D11); the rest are counted as dropped
MAX_EXACT_INT = 2 ** 53  # Lua 5.1 numbers are doubles: a larger int would not read back as itself

NEED_TEXT = "Enter a key, a value or both."

# Characters outside ASCII whose case folding (casefold, or re.IGNORECASE) gives ASCII: with match case off a
# file holding one may match an ASCII needle its lowered bytes do not contain. Pinned by a test that recomputes it.
FOLDS_TO_ASCII = ("ßİıŉſǰẖẗẘẙẚẞK"
                  "ﬀﬁﬂﬃﬄﬅﬆ")
_FOLDS = re.compile(b"|".join(re.escape(c.encode("utf-8")) for c in FOLDS_TO_ASCII))
# An escape that could write a plain character another way (`\070`, `\x`, `\z`, `\F`): only `\\`, `\"`, `\'`,
# a newline and the letter escapes of control characters are not. Searched with every `\\` pair taken out first
# (escape pairs read left to right), so the `\\I` of WoW's "Interface\\Icons" paths is not one.
_HIDING_ESCAPE = re.compile(rb"\\[^\\\"'abfnrtv\r\n]")
_UNSAFE_NEEDLE = re.compile(r"[\"'\\\x00-\x1f\x7f]")
_LUA_NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_LUA_INT = re.compile(r"-?\d+")

Replacement = str | int | float | bool
Progress = Callable[[int, int, SvFile], None]


@dataclass(frozen=True)
class SearchScope:
    """Which files a search reads (D9). None / "" = every one. character: an owner label (`Realm/Name`), or
    svfiles.OWNER_ACCOUNT_WIDE for account-wide files only. addon: text the addon name contains, any case."""
    flavor: str | None = None  # flavor folder
    account: str | None = None
    character: str | None = None
    addon: str = ""

    def accepts(self, file: SvFile) -> bool:
        return ((self.flavor is None or file.flavor.folder == self.flavor)
                and (self.account is None or file.account == self.account)
                and (self.character is None or file.owner == self.character)
                and self.addon.casefold() in file.addon.casefold())

    def files(self, files: Sequence[SvFile]) -> list[SvFile]:
        return [f for f in files if self.accepts(f)]

    def as_log(self) -> dict:
        return {"flavor": self.flavor, "account": self.account, "character": self.character, "addon": self.addon}


def number_problem(value: object) -> str | None:
    """Why value can't be written as a Lua number that reads back as itself, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "not a number"
    if isinstance(value, float) and not math.isfinite(value):
        return "infinity and nan can't be written as a Lua number"
    if isinstance(value, int) and abs(value) > MAX_EXACT_INT:
        return f"a whole number can be at most {MAX_EXACT_INT:,} either way (Lua keeps numbers as doubles)"
    return None


def parse_replacement(kind: str, text: str) -> Replacement:
    """The typed replacement for what the user typed (D10). A string is the text as typed; a number must be a plain
    Lua decimal (no hex, inf, nan or digit separators) that reads back as exactly that number; a boolean is true or
    false. Raises ValueError with a message for the user."""
    if kind == REPLACE_STRING:
        return text
    if kind == REPLACE_BOOLEAN:
        word = text.strip().lower()
        if word not in ("true", "false"):
            raise ValueError("Enter true or false.")
        return word == "true"
    if kind != REPLACE_NUMBER:
        raise ValueError(f"Unknown replacement type {kind!r}.")
    word = text.strip()
    if not _LUA_NUMBER.fullmatch(word):
        raise ValueError("Enter a number such as 12, -3 or 2.5.")
    value: int | float = int(word) if _LUA_INT.fullmatch(word) else float(word)
    problem = number_problem(value)
    if problem is None and isinstance(value, float):
        try:
            same = Decimal(word) == Decimal(repr(value))
        except InvalidOperation:  # pragma: no cover - the pattern only lets decimals through
            same = False
        if not same:
            problem = f"{word} would be saved as {value!r}"
    if problem:
        raise ValueError(f"Can't use {word}: {problem}.")
    return value


@dataclass(frozen=True)
class SearchSpec:
    key: str = ""
    key_mode: str = KEY_EXACT
    value: str = ""
    value_mode: str = VALUE_WHOLE
    match_case: bool = False
    scope: SearchScope = field(default_factory=SearchScope)
    replacement: Replacement | None = None  # None: find only

    @property
    def has_key(self) -> bool:
        return bool(self.key.strip())

    @property
    def has_value(self) -> bool:
        """Any value text is a needle, blanks too (a value of spaces is never "no value": that would make a key-only
        search, whose replacement overwrites every value under the key)."""
        return self.value != ""

    @property
    def contains_value(self) -> bool:
        return self.has_value and self.value_mode == VALUE_CONTAINS

    @property
    def replaces(self) -> bool:
        return self.replacement is not None

    def problems(self) -> list[str]:
        found = []
        if not self.has_key and not self.has_value:
            found.append(NEED_TEXT)
        if self.key_mode not in (KEY_EXACT, KEY_CONTAINS):
            found.append(f"Unknown key match {self.key_mode!r}.")
        if self.value_mode not in (VALUE_WHOLE, VALUE_CONTAINS):
            found.append(f"Unknown value match {self.value_mode!r}.")
        new = self.replacement
        if new is None:
            return found
        if self.contains_value:
            if not isinstance(new, str):
                found.append("A Contains value search puts text inside strings: the replacement must be text.")
        elif isinstance(new, (int, float)) and not isinstance(new, bool):
            problem = number_problem(new)
            if problem:
                found.append(f"Can't use {new!r} as the replacement: {problem}.")
        elif not isinstance(new, (str, bool)):
            found.append("The replacement must be a string, a number or a boolean.")
        return found

    def check(self) -> None:
        problems = self.problems()
        if problems:
            raise ValueError(" ".join(problems))

    def as_log(self) -> dict:
        return {"key": self.key, "key_mode": self.key_mode, "value": self.value, "value_mode": self.value_mode,
                "match_case": self.match_case, "scope": self.scope.as_log(),
                "replacement": None if self.replacement is None else repr(self.replacement)}


@dataclass(frozen=True, slots=True)
class Hit:
    """One matching scalar. file: the SvFile with the SHA-256 of the bytes searched (D17); path: the top-level name,
    then each key, each of its own type, ending in this value's key; key_span: the key's bytes (a top-level name's;
    None for a positional entry); value_span: the value's bytes. new / new_bytes: the replacement and its Lua (None
    for a find only)."""
    file: SvFile
    path: tuple
    key_span: tuple[int, int] | None
    value_span: tuple[int, int]
    old: str | int | float | bool | RawNumber | None
    old_bytes: bytes
    new: Replacement | None = None
    new_bytes: bytes | None = None

    @property
    def sha256(self) -> str:
        return self.file.sha256

    @property
    def key(self) -> object:
        return self.path[-1]

    @property
    def typed_path(self) -> tuple:
        """The path as luasv.key_id identities (true and 1 differ, [1.0] is [1])."""
        return tuple(key_id(k) for k in self.path)


@dataclass
class FileSearch:
    """What searching one file found: its hits (at most HIT_CAP), how many more it had, or why it can't be read."""
    file: SvFile
    hits: list[Hit] = field(default_factory=list)
    extra: int = 0
    error: str | None = None


@dataclass
class SearchResult:
    spec: SearchSpec
    hits: list[Hit]
    dropped: int  # hits over HIT_CAP
    files: int  # files in scope (searched, or skipped by the pre-filter)
    unreadable: list[tuple[SvFile, str]]
    seconds: float

    @property
    def capped(self) -> bool:
        return self.dropped > 0

    @property
    def files_with_hits(self) -> int:
        return len({id(h.file) for h in self.hits})


class _Matcher:
    """The spec's matching rules, ready to run on every scalar of a file."""

    def __init__(self, spec: SearchSpec) -> None:
        self.spec = spec
        fold = (lambda s: s) if spec.match_case else str.casefold
        self.fold = fold
        self.key = fold(spec.key) if spec.has_key else None
        self.key_contains = spec.key_mode == KEY_CONTAINS
        self.value = spec.value if spec.has_value else None
        self.contains = spec.contains_value
        self.pattern = re.compile(re.escape(spec.value), 0 if spec.match_case else re.IGNORECASE)
        self.whole = fold(spec.value)
        self.new_bytes = None if spec.replacement is None or self.contains else encode_value(spec.replacement)

    def key_ok(self, data: bytes, key: object, key_span: tuple[int, int] | None) -> bool:
        if self.key is None:
            return True
        text = self.fold(key_text(data, key, key_span))
        return self.key in text if self.key_contains else text == self.key

    def value_hit(self, data: bytes, scalar: Scalar) -> tuple[bool, Replacement | None, bytes | None]:
        """(matches, new value, new bytes)."""
        value = scalar.value
        new = self.spec.replacement
        if self.value is None:
            return True, new, self.new_bytes
        if self.contains:
            if not isinstance(value, str) or not self.pattern.search(value):
                return False, None, None
            if new is None:
                return True, None, None
            text = self.pattern.sub(lambda _m: new, value)
            return True, text, encode_value(text)
        if value is None:
            return False, None, None
        text = value if isinstance(value, str) else data[scalar.start:scalar.end].decode("ascii", "replace")
        if self.fold(text) != self.whole:
            return False, None, None
        return True, new, self.new_bytes


def key_text(data: bytes, key: object, key_span: tuple[int, int] | None) -> str:
    """The text a key search matches (D6): a string key as it is, a number key as written (`[2.50]`: "2.50"), a
    positional entry's index, "true"/"false"."""
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if key_span is None:
        return str(key)
    return data[key_span[0] + 1:key_span[1] - 1].strip().decode("ascii", "replace")


def _needles(spec: SearchSpec) -> list[str]:
    """The needles the pre-filter may look for in a file's bytes (the unsafe ones left out)."""
    needles = []
    if spec.has_key and not (spec.key.isascii() and spec.key.isdigit()):
        needles.append(spec.key)
    if spec.has_value:
        needles.append(spec.value)
    return [n for n in needles if not _UNSAFE_NEEDLE.search(n) and (spec.match_case or n.isascii())]


def may_hold(data: bytes, spec: SearchSpec) -> bool:
    """False only when the file's bytes can't hold a hit (the byte pre-filter)."""
    needles = _needles(spec)
    if not needles or (b"\\" in data and _HIDING_ESCAPE.search(data.replace(b"\\\\", b""))):
        return True
    if spec.match_case:
        return all(n.encode("utf-8") in data for n in needles)
    if _FOLDS.search(data):
        return True
    lowered = data.lower()
    return all(n.lower().encode("ascii") in lowered for n in needles)


def search_file(file: SvFile, spec: SearchSpec, matcher: _Matcher | None = None,
                room: int = HIT_CAP) -> FileSearch:
    """Search one file; never raises for a file that can't be read or parsed (FileSearch.error, logged). It keeps at
    most `room` hits (HIT_CAP at most) and counts the rest in `extra`."""
    matcher = matcher or _Matcher(spec)
    room = max(0, min(room, HIT_CAP))
    found = FileSearch(file)
    try:
        data = file.path.read_bytes()
    except OSError as exc:
        return _unreadable(found, f"could not read {file.path.name}: {exc.strerror or exc}", exc)
    if not may_hold(data, spec):
        return found
    hits: list[tuple] = []
    try:
        for path, key, key_span, scalar in iter_scalars(data):
            if not matcher.key_ok(data, key, key_span):
                continue
            ok, new, new_bytes = matcher.value_hit(data, scalar)
            if not ok:
                continue
            if len(hits) >= room:
                found.extra += 1
                continue
            hits.append((path + (key,), key_span, scalar, new, new_bytes))
    except LuaParseError as exc:
        return _unreadable(found, f"{file.path.name} is not readable Lua ({exc})", exc)
    if hits:
        searched = replace(file, sha256=sha256_of(data))
        found.hits = [Hit(searched, path, key_span, (s.start, s.end), s.value, data[s.start:s.end], new, new_bytes)
                      for path, key_span, s, new, new_bytes in hits]
    return found


def _unreadable(found: FileSearch, message: str, error: object) -> FileSearch:
    found.error = message
    log_event("svb.file_unreadable", flavor=found.file.flavor.folder, path=found.file.rel, error=str(error))
    return found


class _Room:
    """The hits a search may still keep, per file, so a search holds about HIT_CAP hits at a time (not HIT_CAP per
    file). run_search keeps the first HIT_CAP in file-list order, so file i can use at most HIT_CAP less the matches
    of the files before it that have been searched: room(i) before its search; done(i, found) trims every searched
    file to that bound (their kept hits then add up to HIT_CAP at most), the rest moving to `extra`."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.found: dict[int, FileSearch] = {}

    def room(self, index: int) -> int:
        with self.lock:
            before = sum(len(f.hits) + f.extra for i, f in self.found.items() if i < index)
        return max(0, HIT_CAP - before)

    def done(self, index: int, found: FileSearch) -> FileSearch:
        with self.lock:
            self.found[index] = found
            matches = 0
            for i in sorted(self.found):
                one = self.found[i]
                room = max(0, HIT_CAP - matches)
                if len(one.hits) > room:
                    one.extra += len(one.hits) - room
                    del one.hits[room:]
                matches += len(one.hits) + one.extra
        return found


def run_search(files: Sequence[SvFile], spec: SearchSpec, *, parallelism: int = 1,
               progress: Progress | None = None) -> SearchResult:
    """Search every file in the spec's scope, `parallelism` files at once. progress(done, total, file) follows each
    file (from the unit's thread). Raises ValueError for a spec with problems."""
    spec.check()
    started = time.monotonic()
    in_scope = spec.scope.files(files)
    log_event("svb.search_started", **spec.as_log(), files=len(in_scope))
    matcher = _Matcher(spec)
    lock = threading.Lock()
    done = [0]

    room = _Room()

    def finished(_result) -> None:
        if progress is None:
            return
        with lock:
            done[0] += 1
            count = done[0]
        progress(count, len(in_scope), _result.unit[1])

    def one_file(unit: tuple[int, SvFile], _report) -> FileSearch:
        index, file = unit
        return room.done(index, search_file(file, spec, matcher, room.room(index)))

    results = run_units(list(enumerate(in_scope)), one_file, parallelism=parallelism, what="sv-browser search",
                        label=lambda u: u[1].rel, on_done=finished)
    hits: list[Hit] = []
    dropped = 0
    unreadable: list[tuple[SvFile, str]] = []
    for unit in results:
        if unit.error is not None:  # not expected: search_file reports what it can't read
            unreadable.append((unit.unit[1], f"{type(unit.error).__name__}: {unit.error}"))
            continue
        one = unit.value
        if one.error is not None:
            unreadable.append((one.file, one.error))
        left = HIT_CAP - len(hits)
        hits += one.hits[:left]
        dropped += max(0, len(one.hits) - left) + one.extra
    seconds = round(time.monotonic() - started, 2)
    log_event("svb.search_completed", files=len(in_scope), hits=len(hits), dropped=dropped,
              unreadable=len(unreadable), seconds=seconds)
    return SearchResult(spec, hits, dropped, len(in_scope), unreadable, seconds)
