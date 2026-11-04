#!/usr/bin/env python3
"""Rebuild the knowledge base's per-flavor CVar and slash-command files from the KaosKbDump addon's SavedVariables
(spec X7, X8; plan T4). Developer-only: it never ships, and the app never runs it.

For each flavor folder of the WoW install given by `--wow`, it reads the newest
`WTF/Account/*/SavedVariables/KaosKbDump.lua` with `core/luasv` and writes `<out>/cvars/<flavor>.json` and
`<out>/slash_commands/<flavor>.json`. A flavor without a dump (or with one it can't read) is skipped with a message
and its older files are left as they are. Only the client's defaults, help and flags are kept, never the values the
dumping character had set. `--wiki` layers the reviewed plain-English notes from `scripts/kb_dump/wiki_notes.json`
(written in our own words, each with its warcraft.wiki.gg URL) onto the CVars the dump has.

A dump from the current addon (`dumpVersion` 2) also gives the slash list without any addon's commands, with the
emotes, and the client's macro limits, which go into `<out>/macro_limits.json`. A dump from the first addon version
writes only the CVars. `--provisional FLAVOR=FROM` writes a flavor that has no dump as a copy of another flavor's
files, marked `provisional`, until its own dump exists. Nothing here uses the network. Run it again after a client
patch; see scripts/kb_dump/README.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wowtools.core import luasv  # noqa: E402
from wowtools.core.install import WowInstall  # noqa: E402

DUMP_NAME = "KaosKbDump.lua"
DUMP_VARIABLE = "KaosKbDumpDB"
DEFAULT_OUT = ROOT / "wowtools" / "kb"
DEFAULT_WIKI_NOTES = ROOT / "scripts" / "kb_dump" / "wiki_notes.json"
DUMP_VERSION = 2          # the addon version that marks addon commands and records emotes and macro limits
MACRO_LIMITS = "macro_limits.json"
_FLAVOR = re.compile(r"^_[A-Za-z0-9_]+_$")


class DumpError(ValueError):
    pass


def lua_to_python(value: luasv.Value) -> object:
    """A parsed luasv value as plain Python: a Table becomes a dict keyed by its Lua keys."""
    if isinstance(value, luasv.Scalar):
        return value.value
    if isinstance(value, luasv.Table):
        return {item.key: lua_to_python(item.value) for item in value.fields}
    raise DumpError("a table in the dump could not be read")


def find_dump(flavor_dir: Path) -> Path | None:
    """The newest KaosKbDump.lua of any account of the flavor (newest by modification time)."""
    found = sorted((flavor_dir / "WTF" / "Account").glob(f"*/SavedVariables/{DUMP_NAME}"),
                   key=lambda path: (path.stat().st_mtime, str(path)))
    return found[-1] if found else None


def read_dump(path: Path) -> dict:
    try:
        chunk = luasv.parse(path.read_bytes())
    except (OSError, luasv.LuaParseError) as exc:
        raise DumpError(str(exc)) from exc
    assignment = chunk.get(DUMP_VARIABLE)
    if assignment is None or not isinstance(assignment.value, luasv.Table):
        raise DumpError(f"no {DUMP_VARIABLE} table (was /kbdump run and the game closed or reloaded after?)")
    data = lua_to_python(assignment.value)
    if not isinstance(data.get("build"), str) or not isinstance(data.get("cvars"), dict):
        raise DumpError("the dump has no build or no cvars")
    return data


def scope_of(info: dict) -> str:
    if info.get("character") is True:
        return "character"
    if info.get("account") is True:
        return "account"
    return "machine"


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def cvar_entry(info: dict) -> dict:
    if info.get("default") is None:
        # GetCVarInfo gave nothing for it (no default, no flags): where it is kept is unknown, not "machine".
        return {"default": None, "help": _text(info.get("help")), "category": _text(info.get("category")).lower(),
                "scope": None, "synced": False, "locked": info.get("locked") is True,
                "readonly": info.get("readonly") is True}
    scope = scope_of(info)
    return {
        "default": _text(info.get("default")),
        "help": _text(info.get("help")),
        "category": _text(info.get("category")).lower(),
        "scope": scope,
        "synced": scope != "machine",
        "locked": info.get("locked") is True,
        "readonly": info.get("readonly") is True,
    }


def build_cvars(flavor: str, dump: dict, notes: dict[str, dict] | None = None) -> dict:
    build = dump["build"]
    cvars = {}
    for name, info in dump["cvars"].items():
        if isinstance(name, str) and isinstance(info, dict):
            entry = cvar_entry(info)
            if notes and name in notes:
                entry["wiki"] = {"text": notes[name]["text"], "source": notes[name]["source"]}
            cvars[name] = entry
    return {"flavor": flavor, "build": build, "source": f"client dump {flavor} {build}", "cvars": cvars}


def is_current(dump: dict) -> bool:
    version = dump.get("dumpVersion")
    return isinstance(version, int) and not isinstance(version, bool) and version >= DUMP_VERSION


def build_slash(flavor: str, dump: dict) -> dict:
    """The client's slash commands and emotes; the commands an addon registered (`addonCommands`) are left out."""
    build = dump["build"]
    commands: dict[str, str] = {}
    raw = dump.get("commands") if isinstance(dump.get("commands"), dict) else {}
    addon = dump.get("addonCommands") if isinstance(dump.get("addonCommands"), dict) else {}
    for slash, key in sorted(raw.items(), key=lambda item: (str(item[0]).lower(), str(item[1]))):
        if isinstance(slash, str) and isinstance(key, str) and slash.startswith("/") and addon.get(key) is not True:
            commands.setdefault(slash.lower(), key)
    return {"flavor": flavor, "build": build, "source": f"client dump {flavor} {build}", "commands": commands}


def macro_limits_entry(dump: dict) -> dict | None:
    """`{account, character, build, source}` from the dump's `macroLimits`, None without two positive integers."""
    raw = dump.get("macroLimits") if isinstance(dump.get("macroLimits"), dict) else {}
    account, character = raw.get("account"), raw.get("character")
    if isinstance(account, float) and account.is_integer():
        account = int(account)
    if isinstance(character, float) and character.is_integer():
        character = int(character)
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (account, character)):
        return None
    return {"account": account, "character": character, "build": dump["build"],
            "source": f"client dump {dump['flavor_folder']} {dump['build']}"}


def provisional_copy(data: dict, flavor: str, origin: str) -> dict:
    """A flavor's file as a copy of another flavor's, marked: its source still names the dump it comes from."""
    return {**data, "flavor": flavor, "provisional": provisional_note(flavor, origin)}


def provisional_note(flavor: str, origin: str) -> str:
    return f"copied from {origin} until a {flavor} dump exists"


def parse_provisional(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values:
        flavor, sep, origin = value.partition("=")
        if not sep or not _FLAVOR.match(flavor) or not _FLAVOR.match(origin) or flavor == origin:
            raise DumpError(f"--provisional {value!r}: use FLAVOR=FROM, two flavor folders such as _forever_=_retail_")
        out[flavor] = origin
    return out


def read_limits(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"flavors": {}}
    except (OSError, ValueError) as exc:
        raise DumpError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("flavors"), dict):
        raise DumpError(f"{path}: no \"flavors\" object")
    return data


def load_wiki_notes(path: Path) -> dict[str, dict]:
    """The reviewed wiki notes, `{"cvars": {name: {"text": ..., "source": "https://warcraft.wiki.gg/..."}}}`. A note
    without text or without a warcraft.wiki.gg source is refused (spec X6: every description carries its source)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DumpError(f"{path}: {exc}") from exc
    notes = data.get("cvars") if isinstance(data, dict) else None
    if not isinstance(notes, dict):
        raise DumpError(f"{path}: no \"cvars\" object")
    bad = sorted(name for name, note in notes.items()
                 if not isinstance(note, dict) or not str(note.get("text") or "").strip()
                 or not str(note.get("source") or "").startswith("https://warcraft.wiki.gg/"))
    if bad:
        raise DumpError(f"{path}: notes without text or a warcraft.wiki.gg source: {', '.join(bad)}")
    return notes


def render_json(data: dict) -> bytes:
    """The file's bytes. A dump string that was not valid UTF-8 (luasv keeps such bytes as surrogates) cannot be
    encoded and raises DumpError, so the flavor is skipped like any other unreadable dump."""
    text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DumpError("a string in the dump is not valid UTF-8") from exc


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(payload)
    partial.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild wowtools/kb/{cvars,slash_commands}/<flavor>.json from "
                                                 "each flavor's KaosKbDump SavedVariables.")
    parser.add_argument("--wow", type=Path, required=True, help="the World of Warcraft folder (holds _retail_ ...)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the knowledge-base folder (wowtools/kb)")
    parser.add_argument("--wiki", action="store_true", help="layer the reviewed wiki notes onto the CVars")
    parser.add_argument("--wiki-notes", type=Path, default=DEFAULT_WIKI_NOTES, help="the wiki notes file")
    parser.add_argument("--provisional", action="append", default=[], metavar="FLAVOR=FROM",
                        help="write a flavor without a dump as a marked copy of another flavor's files")
    args = parser.parse_args(argv)
    try:
        notes = load_wiki_notes(args.wiki_notes) if args.wiki else None
        provisional = parse_provisional(args.provisional)
        limits = read_limits(args.out / MACRO_LIMITS)
    except DumpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    flavors = WowInstall(args.wow).flavors()
    if not flavors:
        print(f"error: no flavor folders (_retail_ ...) in {args.wow}", file=sys.stderr)
        return 1
    written = 0
    built: dict[str, tuple[dict, dict | None]] = {}
    limits_changed = False
    for flavor in flavors:
        path = find_dump(flavor.path)
        if path is None:
            print(f"{flavor.folder}: skipped, no {DUMP_NAME} under WTF/Account/*/SavedVariables "
                  f"(install the addon, /kbdump in game, log out)")
            continue
        try:
            dump = read_dump(path)
            dump["flavor_folder"] = flavor.folder
            current = is_current(dump)
            cvars = build_cvars(flavor.folder, dump, notes)
            slash = build_slash(flavor.folder, dump) if current else None
            cvars_bytes = render_json(cvars)
            slash_bytes = render_json(slash) if slash is not None else None
        except DumpError as exc:
            print(f"{flavor.folder}: skipped, {path} could not be read: {exc}")
            continue
        write_bytes(args.out / "cvars" / f"{flavor.folder}.json", cvars_bytes)
        if slash_bytes is not None:
            write_bytes(args.out / "slash_commands" / f"{flavor.folder}.json", slash_bytes)
        entry = macro_limits_entry(dump) if current else None
        if entry is not None:
            limits["flavors"][flavor.folder] = entry
            limits_changed = True
        built[flavor.folder] = (cvars, slash)
        noted = sum("wiki" in item for item in cvars["cvars"].values())
        print(f"{flavor.folder}: build {dump['build']} from {path}: {len(cvars['cvars'])} CVars "
              f"({noted} with wiki notes), "
              + (f"{len(slash['commands'])} slash commands" if slash is not None else
                 "slash commands not written (a dump from the first addon version: /kbdump again with the "
                 "current addon)")
              + (f", macro limits {entry['account']}/{entry['character']}" if entry is not None else ""))
        written += 1
    if not written:
        print(f"error: no flavor had a readable {DUMP_NAME}; nothing written", file=sys.stderr)
        return 1
    for flavor_folder, origin in sorted(provisional.items()):
        if flavor_folder in built:
            print(f"{flavor_folder}: has its own dump, no provisional copy")
            continue
        if origin not in built:
            print(f"{flavor_folder}: no provisional copy, {origin} had no readable dump in this run")
            continue
        cvars, slash = built[origin]
        write_bytes(args.out / "cvars" / f"{flavor_folder}.json",
                    render_json(provisional_copy(cvars, flavor_folder, origin)))
        if slash is not None:
            write_bytes(args.out / "slash_commands" / f"{flavor_folder}.json",
                        render_json(provisional_copy(slash, flavor_folder, origin)))
        origin_limits = limits["flavors"].get(origin)
        if isinstance(origin_limits, dict):
            limits["flavors"][flavor_folder] = {**origin_limits, "provisional": provisional_note(flavor_folder, origin)}
            limits_changed = True
        print(f"{flavor_folder}: provisional copy of {origin}")
    if limits_changed:
        write_bytes(args.out / MACRO_LIMITS, render_json(limits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
