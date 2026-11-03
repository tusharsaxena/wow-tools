"""The offline knowledge base (config tools spec X6, X8, CC5, ME3): versioned JSON under wowtools/kb/, which ships
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
