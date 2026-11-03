#!/usr/bin/env python3
"""Rebuild the knowledge base's per-flavor CVar and slash-command files from the KaosKbDump addon's SavedVariables
(spec X7, X8; plan T4). Developer-only: it never ships, and the app never runs it.

For each flavor folder of the WoW install given by `--wow`, it reads the newest
`WTF/Account/*/SavedVariables/KaosKbDump.lua` with `core/luasv` and writes `<out>/cvars/<flavor>.json` and
`<out>/slash_commands/<flavor>.json`. A flavor without a dump (or with one it can't read) is skipped with a message
and its older files are left as they are. Only the client's defaults, help and flags are kept, never the values the
dumping character had set. `--wiki` layers the reviewed plain-English notes from `scripts/kb_dump/wiki_notes.json`
(written in our own words, each with its warcraft.wiki.gg URL) onto the CVars the dump has. Nothing here uses the
network. Run it again after a client patch; see scripts/kb_dump/README.md.
"""
from __future__ import annotations

import argparse
import json
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


def build_slash(flavor: str, dump: dict) -> dict:
    build = dump["build"]
    commands: dict[str, str] = {}
    raw = dump.get("commands") if isinstance(dump.get("commands"), dict) else {}
    for slash, key in sorted(raw.items(), key=lambda item: (str(item[0]).lower(), str(item[1]))):
        if isinstance(slash, str) and isinstance(key, str) and slash.startswith("/"):
            commands.setdefault(slash.lower(), key)
    return {"flavor": flavor, "build": build, "source": f"client dump {flavor} {build}", "commands": commands}


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
    args = parser.parse_args(argv)
    try:
        notes = load_wiki_notes(args.wiki_notes) if args.wiki else None
    except DumpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    flavors = WowInstall(args.wow).flavors()
    if not flavors:
        print(f"error: no flavor folders (_retail_ ...) in {args.wow}", file=sys.stderr)
        return 1
    written = 0
    for flavor in flavors:
        path = find_dump(flavor.path)
        if path is None:
            print(f"{flavor.folder}: skipped, no {DUMP_NAME} under WTF/Account/*/SavedVariables "
                  f"(install the addon, /kbdump in game, log out)")
            continue
        try:
            dump = read_dump(path)
            cvars = build_cvars(flavor.folder, dump, notes)
            slash = build_slash(flavor.folder, dump)
            cvars_bytes, slash_bytes = render_json(cvars), render_json(slash)
        except DumpError as exc:
            print(f"{flavor.folder}: skipped, {path} could not be read: {exc}")
            continue
        write_bytes(args.out / "cvars" / f"{flavor.folder}.json", cvars_bytes)
        write_bytes(args.out / "slash_commands" / f"{flavor.folder}.json", slash_bytes)
        noted = sum("wiki" in entry for entry in cvars["cvars"].values())
        print(f"{flavor.folder}: build {dump['build']} from {path}: {len(cvars['cvars'])} CVars "
              f"({noted} with wiki notes), {len(slash['commands'])} slash commands")
        written += 1
    if not written:
        print(f"error: no flavor had a readable {DUMP_NAME}; nothing written", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
