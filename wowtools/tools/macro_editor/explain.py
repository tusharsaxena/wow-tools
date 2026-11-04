"""Plain-English reading of a macro's [...] blocks and the flavor check (config tools spec ME5, ME8). UI-free.

Every phrase comes from wowtools/kb/macro_reference.json; a conditional or unit the reference doesn't know is named
as such, never described from imagination (X6).
"""
from __future__ import annotations

import re

from wowtools.core.kb import ConditionalInfo, MacroReference
from wowtools.tools.macro_editor.syntax import lines, option_commands

__all__ = ["explain_block", "explain_unit", "read_conditional", "unknown_terms"]

UNKNOWN = "(not in the reference)"
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
