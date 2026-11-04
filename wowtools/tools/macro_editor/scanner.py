"""Read every macro set of a flavor (config tools spec ME2, ME14; X3, X4). UI-free; never writes."""
from __future__ import annotations

import hashlib

from wowtools.core.events import log_event
from wowtools.core.install import Account, Character, ErrorHandler, Flavor
from wowtools.core.macrofile import NEWLINE, MacroFile, parse_macros
from wowtools.tools.macro_editor.model import MACRO_FILE, MacroSet

__all__ = ["read_set", "scan_sets"]


def read_set(flavor: Flavor, account: Account, character: Character | None) -> MacroSet:
    """The set of the account (character None) or of the character. No file is an empty set (the run creates it);
    a file that can't be read is a read-only set with the reason, logged."""
    path = (account.path if character is None else character.path) / MACRO_FILE
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return MacroSet(flavor, account, character, path, parse_macros(b""), b"", None)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        log_event("macro.file_unreadable", path=str(path), reason=reason)
        parsed = MacroFile((), NEWLINE, False, f"{MACRO_FILE} could not be read: {reason}")
        return MacroSet(flavor, account, character, path, parsed, b"", None)
    return MacroSet(flavor, account, character, path, parse_macros(data), data, hashlib.sha256(data).hexdigest())


def scan_sets(flavor: Flavor, on_error: ErrorHandler | None = None) -> list[MacroSet]:
    """Per account: its account set, then each real character's set (X3: `Bob - Copy` is never one), in the order
    install lists them. A missing file is an empty set."""
    sets: list[MacroSet] = []
    for account in flavor.accounts(on_error):
        sets.append(read_set(flavor, account, None))
        sets.extend(read_set(flavor, account, character) for character in account.real_characters(on_error))
    log_event("macro.scanned", flavor=flavor.folder, sets=len(sets), macros=sum(len(s.parsed.macros) for s in sets),
              read_only=sum(s.read_only for s in sets))
    return sets
