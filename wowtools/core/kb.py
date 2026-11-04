"""The offline knowledge base (config tools spec X6, X8, CC5, ME3, ME5, ME8-ME11): versioned JSON under wowtools/kb/, which ships
with the app. wowtools/kb/README.md is the schema and the sources rule.

Every loader reads its file once per process (`clear_cache()` forgets them) and never raises: a missing file means
"no data" (everything unknown), and a file that cannot be read or parsed is logged once as `kb.unreadable` and read
as empty. Each loader takes `root=` (default `KB_ROOT`, read at call time) so tests use a temp folder.
"""
from __future__ import annotations

import fnmatch
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from wowtools.core.events import log_event

KB_ROOT = Path(__file__).resolve().parents[1] / "kb"

# The Config Editor's groups (X8), in the order its filter lists them.
CATEGORY_GROUPS = ("graphics", "sound", "interface", "camera", "nameplates", "combat text", "network", "other")
# The client's console category (the dump's lowercased Enum.ConsoleCategory name) -> group. Any other word (debug,
# console, combat, gm, reveal, none, a bare number) is "other". The name rules in category_group come first.
CONSOLE_CATEGORY_GROUPS = {"graphics": "graphics", "sound": "sound", "net": "network", "game": "interface"}
RETAIL_LIMITS = (120, 30)
SCOPES = ("machine", "account", "character")

_SAFE_FLAVOR = re.compile(r"^[A-Za-z0-9_]+$")
_cache: dict[Path, dict | None] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class CvarInfo:
    name: str
    default: str | None          # None: the data has no default
    help: str                    # Blizzard's help text ("" when the client has none)
    description: str             # our plain-English note (wiki-based), "" when there is none
    description_source: str      # its warcraft.wiki.gg URL ("" exactly when description is "")
    category: str                # one of CATEGORY_GROUPS
    scope: Literal["machine", "account", "character"] | None
    synced: bool
    source: str                  # where the entry comes from: "client dump <flavor> <build>"


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _read(path: Path) -> dict | None:
    """The file's JSON object, cached. None when the file is missing (silently) or unreadable (logged once)."""
    with _cache_lock:
        if path in _cache:
            return _cache[path]
    data: dict | None = None
    if path.is_file():
        try:
            loaded = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError) as exc:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
            log_event("kb.unreadable", path=str(path), reason=f"{type(exc).__name__}: {exc}")
        else:
            if isinstance(loaded, dict):
                data = loaded
            else:
                log_event("kb.unreadable", path=str(path), reason="not a JSON object")
    with _cache_lock:
        _cache.setdefault(path, data)
        return _cache[path]


def _root(root: Path | None) -> Path:
    return KB_ROOT if root is None else Path(root)


def _flavor_file(root: Path | None, folder: str, flavor: str) -> Path | None:
    if not isinstance(flavor, str) or not _SAFE_FLAVOR.match(flavor):
        return None
    return _root(root) / folder / f"{flavor}.json"


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def category_group(name: str, raw: str) -> str:
    """The X8 group of a CVar: by name first (nameplates, camera, combat text cut across the client's categories),
    then by the client's console category."""
    low = name.lower()
    if low.startswith("nameplate"):
        return "nameplates"
    if "camera" in low:
        return "camera"
    if "floatingcombattext" in low or low.startswith("combattext"):
        return "combat text"
    return CONSOLE_CATEGORY_GROUPS.get(str(raw).lower(), "other")


def _cvar_info(name: str, entry: dict, source: str) -> CvarInfo:
    wiki = entry.get("wiki") if isinstance(entry.get("wiki"), dict) else {}
    text, wiki_source = _str(wiki.get("text")).strip(), _str(wiki.get("source"))
    if not (text and wiki_source):
        text, wiki_source = "", ""
    scope = entry.get("scope") if entry.get("scope") in SCOPES else None
    default = entry.get("default")
    return CvarInfo(name=name, default=default if isinstance(default, str) else None, help=_str(entry.get("help")),
                    description=text, description_source=wiki_source,
                    category=category_group(name, _str(entry.get("category"))), scope=scope,
                    synced=entry.get("synced") is True, source=source)


def load_cvars(flavor_folder: str, *, root: Path | None = None) -> dict[str, CvarInfo]:
    """Every CVar the flavor's dump knows, by name; {} when there is no data for the flavor (all unknown)."""
    path = _flavor_file(root, "cvars", flavor_folder)
    data = _read(path) if path is not None else None
    if data is None:
        return {}
    cvars = data.get("cvars")
    if not isinstance(cvars, dict):
        log_event("kb.unreadable", path=str(path), reason='no "cvars" object')
        with _cache_lock:
            _cache[path] = None
        return {}
    source = _str(data.get("source"))
    return {name: _cvar_info(name, entry, source) for name, entry in cvars.items()
            if isinstance(name, str) and name and isinstance(entry, dict)}


def _state_list(root: Path | None) -> tuple[frozenset[str], tuple[str, ...], frozenset[str]]:
    data = _read(_root(root) / "cvar_state.json") or {}

    def strings(key: str) -> list[str]:
        value = data.get(key)
        return [item.lower() for item in value if isinstance(item, str) and item] if isinstance(value, list) else []

    return frozenset(strings("names")), tuple(strings("patterns")), frozenset(strings("exceptions"))


def is_state_cvar(name: str, *, root: Path | None = None) -> bool:
    """True for a CVar that records a character's state (progress, history, IDs, UI bookkeeping), which the Config
    Copier keeps on the target (CC5): a listed name or a match of a listed fnmatch pattern, unless it is a listed
    exception. Matched case-insensitively, as the client matches CVar names."""
    if not isinstance(name, str) or not name:
        return False
    names, patterns, exceptions = _state_list(root)
    low = name.lower()
    if low in exceptions:
        return False
    return low in names or any(fnmatch.fnmatchcase(low, pattern) for pattern in patterns)


def _limits(flavor_folder: str, root: Path | None) -> tuple[int, int] | None:
    data = _read(_root(root) / "macro_limits.json") or {}
    flavors = data.get("flavors") if isinstance(data.get("flavors"), dict) else {}
    entry = flavors.get(flavor_folder) if isinstance(flavor_folder, str) else None
    if not isinstance(entry, dict) or not _str(entry.get("source")):
        return None
    account, character = entry.get("account"), entry.get("character")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (account, character)):
        return None
    return account, character


def macro_limits(flavor_folder: str, *, root: Path | None = None) -> tuple[int, int]:
    """(account macros, macros per character) for the flavor; Retail's values when the KB has no sourced entry for
    it (`limits_known` then says False, so the tool can flag them)."""
    return _limits(flavor_folder, root) or RETAIL_LIMITS


def limits_known(flavor_folder: str, *, root: Path | None = None) -> bool:
    return _limits(flavor_folder, root) is not None


# --- The Macro Editor's reference, templates and optimizer rules (ME5, ME8-ME11) --------------------------------------

def _flavors(value: object) -> tuple[str, ...] | None:
    """An entry's `flavors`: the flavor folders its source says it applies to, None when the source does not say."""
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item)
    return None


@dataclass(frozen=True)
class CommandInfo:
    name: str                          # "/cast"
    aliases: tuple[str, ...]           # other spellings the reference lists ("/spell")
    help: str
    options: bool                      # True: the argument takes [conditions] and ;-clauses (a secure command)
    source: str
    flavors: tuple[str, ...] | None    # None: the source does not say (never flagged)


@dataclass(frozen=True)
class ConditionalInfo:
    name: str                          # "mod"
    aliases: tuple[str, ...]           # "modifier"
    help: str
    subject: Literal["unit", "player", "ui"]   # what it tests: the macro's unit, you, or the interface
    explain: str                       # "{unit} is friendly", "you're in combat", "a modifier key is held"
    explain_no: str                    # the `no` form: "{unit} is not friendly", "you're not in combat"
    explain_arg: str                   # with an argument: "{arg} is held" ("" when it takes none)
    explain_no_arg: str                # the `no` form with an argument: "{arg} isn't held"
    args: str                          # what goes after ":" ("" when it takes none)
    arg_names: Mapping[str, str]       # plain words for argument values ("shift" -> "Shift")
    source: str
    flavors: tuple[str, ...] | None


@dataclass(frozen=True)
class UnitInfo:
    name: str                          # "mouseover"; a numbered unit is its stem ("party" for party1-party4)
    help: str
    explain: str                       # "the unit under the mouse"; "party member {n}" for a numbered unit
    numbered: bool
    source: str
    flavors: tuple[str, ...] | None


@dataclass(frozen=True)
class MacroReference:
    """What the Macro Editor knows about macro syntax for one flavor. The commands, conditionals and units come
    from the curated `macro_reference.json` (keyed by name and by every alias, lower case); `slash_commands` is the
    flavor's own slash-command list from the dump addon, None when the flavor has no dump yet (then no command is
    flagged as unknown)."""
    flavor: str
    commands: Mapping[str, CommandInfo]
    conditionals: Mapping[str, ConditionalInfo]
    units: Mapping[str, UnitInfo]
    builder: Mapping[str, tuple[str, ...]]
    slash_commands: frozenset[str] | None

    def applies(self, entry: CommandInfo | ConditionalInfo | UnitInfo) -> bool | None:
        """True or False when the entry's source names its flavors, None when it does not say."""
        return None if entry.flavors is None else self.flavor in entry.flavors


def _sourced(entries: object) -> list[tuple[str, dict]]:
    if not isinstance(entries, dict):
        return []
    return [(name.lower(), entry) for name, entry in entries.items()
            if isinstance(name, str) and name and isinstance(entry, dict) and _str(entry.get("source"))
            and _str(entry.get("help"))]


def _aliases(entry: dict) -> tuple[str, ...]:
    value = entry.get("aliases")
    return tuple(a.lower() for a in value if isinstance(a, str) and a) if isinstance(value, list) else ()


def _keyed(infos: list) -> dict:
    out: dict = {}
    for info in infos:
        for key in (info.name, *info.aliases):
            out.setdefault(key, info)
    return out


def _reference_data(root: Path | None) -> dict:
    return _read(_root(root) / "macro_reference.json") or {}


def _slash_dump(flavor_folder: str, root: Path | None) -> frozenset[str] | None:
    path = _flavor_file(root, "slash_commands", flavor_folder)
    data = _read(path) if path is not None else None
    commands = data.get("commands") if data is not None else None
    if not isinstance(commands, dict):
        return None
    return frozenset(name.lower() for name in commands if isinstance(name, str) and name.startswith("/"))


def load_macro_reference(flavor_folder: str, *, root: Path | None = None) -> MacroReference:
    """The macro reference for a flavor (ME5, ME8). Entries without a source or help text are not loaded (X6)."""
    data = _reference_data(root)
    commands = [CommandInfo(name=name, aliases=_aliases(e), help=_str(e["help"]), options=e.get("options") is True,
                            source=e["source"], flavors=_flavors(e.get("flavors")))
                for name, e in _sourced(data.get("commands")) if name.startswith("/")]
    conditionals = []
    for name, e in _sourced(data.get("conditionals")):
        subject = e.get("subject") if e.get("subject") in ("unit", "player", "ui") else "player"
        names = e.get("arg_names") if isinstance(e.get("arg_names"), dict) else {}
        conditionals.append(ConditionalInfo(
            name=name, aliases=_aliases(e), help=_str(e["help"]), subject=subject,
            explain=_str(e.get("explain")) or name, explain_no=_str(e.get("explain_no")) or f"not {name}",
            explain_arg=_str(e.get("explain_arg")), explain_no_arg=_str(e.get("explain_no_arg")),
            args=_str(e.get("args")), arg_names={k.lower(): v for k, v in names.items() if isinstance(v, str)},
            source=e["source"], flavors=_flavors(e.get("flavors"))))
    units = [UnitInfo(name=name, help=_str(e["help"]), explain=_str(e.get("explain")) or name,
                      numbered=e.get("numbered") is True, source=e["source"], flavors=_flavors(e.get("flavors")))
             for name, e in _sourced(data.get("units"))]
    raw_builder = data.get("builder") if isinstance(data.get("builder"), dict) else {}
    builder = {key: tuple(v for v in value if isinstance(v, str))
               for key, value in raw_builder.items() if isinstance(key, str) and isinstance(value, list)}
    return MacroReference(flavor=flavor_folder, commands=_keyed(commands), conditionals=_keyed(conditionals),
                          units={u.name: u for u in units}, builder=builder, slash_commands=_slash_dump(flavor_folder, root))


@dataclass(frozen=True)
class MacroTemplate:
    id: str
    title: str
    body: str                          # placeholders written {name}
    placeholders: tuple[str, ...]
    source: str


def load_templates(*, root: Path | None = None) -> list[MacroTemplate]:
    """The curated macro templates (ME11), in file order; one without an id, title, body or source is dropped."""
    data = _read(_root(root) / "macro_templates.json") or {}
    raw = data.get("templates") if isinstance(data.get("templates"), list) else []
    out: list[MacroTemplate] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        fields = [_str(entry.get(key)) for key in ("id", "title", "body", "source")]
        holders = entry.get("placeholders")
        if not all(fields) or not isinstance(holders, list):
            continue
        out.append(MacroTemplate(*fields[:3], tuple(h for h in holders if isinstance(h, str) and h), fields[3]))
    return out


@dataclass(frozen=True)
class RuleInfo:
    id: str
    title: str
    reason: str                        # why the rewrite is the same in game (or, automatic False, why it is not)
    source: str
    automatic: bool                    # False: listed for the record, never applied


def load_optimizer_rules(*, root: Path | None = None) -> dict[str, RuleInfo]:
    """The optimizer's rules (ME10) by id; one without a title, reason or source is dropped."""
    data = _read(_root(root) / "optimizer_rules.json") or {}
    raw = data.get("rules") if isinstance(data.get("rules"), dict) else {}
    out: dict[str, RuleInfo] = {}
    for rule_id, entry in raw.items():
        if not isinstance(rule_id, str) or not isinstance(entry, dict):
            continue
        title, reason, source = (_str(entry.get(key)) for key in ("title", "reason", "source"))
        if title and reason and source:
            out[rule_id] = RuleInfo(rule_id, title, reason, source, entry.get("automatic") is True)
    return out
