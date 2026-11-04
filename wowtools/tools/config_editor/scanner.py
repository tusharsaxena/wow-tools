"""Read every CVar file of a flavor (config tools spec CE3; X3, X4). UI-free; never writes."""
from __future__ import annotations

import hashlib
from pathlib import Path

from wowtools.core.cvarfile import parse_cvars
from wowtools.core.events import log_event
from wowtools.core.install import Account, Character, ErrorHandler, Flavor
from wowtools.tools.config_editor.model import CONFIG_CACHE, CONFIG_WTF, ConfigTarget, Level

__all__ = ["read_target", "scan_targets"]


def _path(flavor: Flavor, account: Account | None, character: Character | None) -> Path:
    if account is None:
        return flavor.wtf_dir / CONFIG_WTF
    return (account.path if character is None else character.path) / CONFIG_CACHE


def read_target(flavor: Flavor, account: Account | None = None, character: Character | None = None) -> ConfigTarget:
    """Config.wtf (no account), the account's config-cache.wtf (no character) or the character's. No file is an
    empty target; a file that can't be read is a read-only one with the reason, logged."""
    level: Level = "machine" if account is None else ("account" if character is None else "character")
    path = _path(flavor, account, character)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return ConfigTarget(flavor, level, account, character, path, None, None, None)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        log_event("cvar.file_unreadable", path=str(path), reason=reason)
        return ConfigTarget(flavor, level, account, character, path, None, None, None,
                            f"{path.name} could not be read: {reason}")
    return ConfigTarget(flavor, level, account, character, path, data, parse_cvars(data),
                        hashlib.sha256(data).hexdigest())


def scan_targets(flavor: Flavor, on_error: ErrorHandler | None = None) -> list[ConfigTarget]:
    """WTF/Config.wtf, then per account its config-cache.wtf and each real character's (X3: `Bob - Copy` is never
    one), in the order install lists them. A missing file is an empty target."""
    targets = [read_target(flavor)]
    for account in flavor.accounts(on_error):
        targets.append(read_target(flavor, account))
        targets.extend(read_target(flavor, account, character) for character in account.real_characters(on_error))
    log_event("cvar.scanned", flavor=flavor.folder, files=len(targets), existing=sum(t.exists for t in targets),
              read_only=sum(t.read_only for t in targets))
    return targets
