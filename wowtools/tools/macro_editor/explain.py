"""Plain-English reading of a macro's [...] blocks and the flavor check (config tools spec ME5, ME8). UI-free.

Every phrase comes from wowtools/kb/macro_reference.json; a conditional or unit the reference doesn't know is named
as such, never described from imagination (X6).
"""
from __future__ import annotations

import re

from wowtools.core.install import flavor_name
from wowtools.core.kb import CommandInfo, ConditionalInfo, MacroReference, UnitInfo
from wowtools.tools.macro_editor.syntax import Token, lines, no_help, option_commands

__all__ = ["SPELL_TEXT", "describe_at", "explain_block", "explain_unit", "read_conditional", "reference_lines",
           "unknown_terms"]

UNKNOWN = "(not in the reference)"
SPELL_TEXT = "A spell or item name: free text, not checked against any spell list."
CHAT_TEXT = "Text the command takes as it is (never read as conditions)."
COMMENT_TEXT = "A # line that is not #showtooltip or #show: the client skips it."
VERBS = {"/cast": "Cast", "/spell": "Cast", "/castsequence": "Cast", "/castrandom": "Cast", "/use": "Use",
         "/userandom": "Use"}
_NUMBERED = re.compile(r"^([a-z]+?)(\d+)$")
_MERGE = ("it's ", "your target is ", "you're ")


def read_conditional(word: str, ref: MacroReference) -> tuple[ConditionalInfo | None, bool, str]:
    """(entry, negated, argument) for `nodead`, `mod:shift`, `nochanneling:Drain Life`; entry None if unknown."""
    name, _, arg = word.partition(":")
    low = name.strip().lower()
    info = ref.conditionals.get(low)
    if info is None and low.startswith("no") and low[2:] in ref.conditionals:
        return ref.conditionals[low[2:]], True, arg.strip()
    return info, False, arg.strip()


def _unit_name(word: str) -> str:
    word = word.strip()
    return (word[1:] if word.startswith("@") else word.split("=", 1)[1] if "=" in word else word).strip().lower()


def explain_unit(name: str, ref: MacroReference) -> str:
    """"the unit under the mouse", "party member 2", "your focus's target"; the name itself marked unknown."""
    name = name.lower()
    info = ref.units.get(name)
    if info is not None and not info.numbered:
        return info.explain
    match = _NUMBERED.match(name)
    if match and match.group(1) in ref.units and ref.units[match.group(1)].numbered:
        return ref.units[match.group(1)].explain.replace("{n}", match.group(2))
    if name == "playertarget":
        return explain_unit("target", ref)
    if name.endswith("target") and len(name) > len("target"):
        base = explain_unit(name[:-len("target")], ref)
        if not base.endswith(UNKNOWN):
            return f"{base}'s target"
    return f"{name} {UNKNOWN}"


def _arg_words(info: ConditionalInfo, arg: str) -> str:
    return " or ".join(info.arg_names.get(part.strip().lower(), part.strip()) for part in arg.split("/"))


def _phrase(word: str, ref: MacroReference, subject: str) -> str:
    info, negated, arg = read_conditional(word, ref)
    if info is None:
        return f"{word} {UNKNOWN}"
    if arg and info.explain_arg:
        text = (info.explain_no_arg if negated else info.explain_arg).replace("{arg}", _arg_words(info, arg))
    else:
        text = info.explain_no if negated else info.explain
    subject_is = "it's" if subject == "it" else f"{subject} is"
    return text.replace("{unit} is ", f"{subject_is} ").replace("{unit}", subject)


def _join(phrases: list[str]) -> str:
    """"it's friendly", "it's not dead" -> "it's friendly and not dead"; other phrases joined with "and"."""
    groups: list[tuple[str, list[str]]] = []
    for phrase in phrases:
        prefix = next((p for p in _MERGE if phrase.startswith(p)), "")
        rest = phrase[len(prefix):]
        if prefix and groups and groups[-1][0] == prefix:
            groups[-1][1].append(rest)
        else:
            groups.append((prefix, [rest]))
    return " and ".join(prefix + " and ".join(rests) for prefix, rests in groups)


def explain_block(block: str, ref: MacroReference, *, verb: str = "Cast") -> str:
    """One [...] block in plain English: "[@mouseover,help,nodead]" -> "Cast on the unit under the mouse, if it's
    friendly and not dead." `[]` is "Always."."""
    inner = block.strip().removeprefix("[").removesuffix("]")
    items = [item.strip() for item in inner.split(",") if item.strip()]
    if not items:
        return "Always."
    units = [item for item in items if item.startswith("@") or item.lower().startswith("target=")]
    unit = _unit_name(units[-1]) if units else None
    subject = "it" if unit else "your target"
    phrases = [_phrase(item, ref, subject) for item in items if item not in units]
    head = f"{verb} on {explain_unit(unit, ref)}" if unit else verb
    return f"{head}, if {_join(phrases)}." if phrases else f"{head}."


def unknown_terms(body: str, ref: MacroReference) -> list[str]:
    """What may not work in the reference's flavor (ME5): commands missing from the flavor's slash-command dump
    (none flagged when the flavor has no dump yet) and commands, conditionals or units whose source names flavors
    that leave this one out (none flagged when the source doesn't say). In first-seen order, each once."""
    out: list[str] = []

    def flag(term: str) -> None:
        if term not in out:
            out.append(term)

    for line in lines(body, option_commands(ref) or option_commands()):
        for token in line.tokens:
            if token.kind == "command":
                low = token.text.lower()
                info = ref.commands.get(low)
                missing = ref.slash_commands is not None and low not in ref.slash_commands and not low[1:].isdigit()
                if missing or (info is not None and ref.applies(info) is False):
                    flag(low)
            elif token.kind == "condition":
                info, _, _ = read_conditional(token.text, ref)
                if info is not None and ref.applies(info) is False:
                    flag(info.name)
            elif token.kind == "unit":
                name = _unit_name(token.text)
                info = ref.units.get(name) or ref.units.get(_NUMBERED.sub(r"\1", name))
                if info is not None and ref.applies(info) is False:
                    flag(f"@{info.name}")
    return out


def _verb(command: str) -> str:
    return VERBS.get(command.lower(), f"Run {command.lower()}")


def _source(entry: CommandInfo | ConditionalInfo | UnitInfo) -> str:
    return f"Source: {entry.source}"


def _flavor_note(entry: CommandInfo | ConditionalInfo | UnitInfo, ref: MacroReference) -> str:
    """"Not in <flavor> (by its source)." when the entry's source leaves the reference's flavor out, else ""."""
    if ref.applies(entry) is False:
        return f"Not in {flavor_name(ref.flavor)}, by its source."
    return ""


def describe_at(body: str, offset: int, ref: MacroReference) -> list[str]:
    """The help panel's lines for the cursor (ME8): what the token under it is, from the reference with its source;
    inside a [...] block also the whole block read out in plain English. No lines between tokens."""
    for line in lines(body, option_commands(ref) or option_commands()):
        if not line.start <= offset <= line.start + len(line.text):
            continue
        inside = [t for t in line.tokens if t.start <= offset <= t.end]
        if not inside:
            return []
        token = min(inside, key=lambda t: t.end - t.start)
        verb = _verb(line.head.text) if line.head is not None and line.head.kind == "command" else "Show"
        block = next((t for t in inside if t.kind == "condition_block"), None)
        out = _describe(token, line.head, ref)
        if block is not None:
            out.append(explain_block(block.text, ref, verb=verb))
        return [text for text in out if text]
    return []


def _describe(token: Token, head: Token | None, ref: MacroReference) -> list[str]:
    if token.kind == "command":
        info = ref.commands.get(token.text.lower())
        if info is None:
            return [f"{token.text} {UNKNOWN}"]
        return [f"{token.text}: {info.help}", _flavor_note(info, ref), _source(info)]
    if token.kind == "directive":
        return [f"{token.text}: a metacommand {UNKNOWN}"]
    if token.kind == "comment":
        return [COMMENT_TEXT]
    if token.kind == "condition":
        info, negated, _ = read_conditional(token.text, ref)
        if info is None:
            return [f"{token.text} {UNKNOWN}"]
        return [f"{token.text}: {no_help(info) if negated else info.help}", _flavor_note(info, ref), _source(info)]
    if token.kind == "unit":
        name = _unit_name(token.text)
        info = ref.units.get(name) or ref.units.get(_NUMBERED.sub(r"\1", name))
        text = f"@{name}: {explain_unit(name, ref)}"
        if info is None:
            return [text]
        return [text, info.help, _flavor_note(info, ref), _source(info)]
    if token.kind == "condition_block":
        return []
    # text: a clause's spell or item name on a command that reads conditions, else the argument as it is
    options = head is not None and head.kind in ("command", "directive") and (
        head.kind == "directive" or head.text.lower() in (option_commands(ref) or option_commands()))
    return [SPELL_TEXT if options else CHAT_TEXT]


def reference_lines(ref: MacroReference) -> list[tuple[str, str, str, str, str]]:
    """The full reference (F1): (section, name, help, source, flavor note) for every command, conditional and unit,
    each once (aliases named in the help), sorted by name within its section."""
    rows: list[tuple[str, str, str, str, str]] = []
    for section, entries, label in (("Commands", ref.commands, lambda e: e.name),
                                    ("Conditionals", ref.conditionals, lambda e: e.name),
                                    ("Units", ref.units, lambda e: f"@{e.name}1" if e.numbered else f"@{e.name}")):
        unique = {id(entry): entry for entry in entries.values()}.values()
        for entry in sorted(unique, key=lambda e: e.name):
            aliases = getattr(entry, "aliases", ())
            text = entry.help + (f" (also {', '.join(aliases)})" if aliases else "")
            rows.append((section, label(entry), text, entry.source, _flavor_note(entry, ref)))
    return rows
