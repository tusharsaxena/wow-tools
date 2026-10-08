"""The Saved Variables Browser's own settings: the [sv_browser] section of config/sv-browser.cfg (spec §4)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.config import SKIP_RISK_WARNING, Config
from wowtools.core.journal import tool_root
from wowtools.tools.sv_browser.events import TOOL_NAME

SECTION = "sv_browser"


@dataclass
class SvBrowserSettings:
    # None: <WoW folder>/wow-tools. The tool's files go to <backup_dir>/sv-browser.
    backup_dir: Path | None = None
    last_flavor_choice: str | None = None  # "" = All flavors, else a flavor folder; None = never chosen
    skip_risk_warning: bool = False  # never show the USE AT YOUR OWN RISK popup (L8)
    # Snapshots and journals to keep are global: Config.keep_backups / keep_journals ([general]).


def load_settings(cfg: Config) -> SvBrowserSettings:
    choice = cfg.get(SECTION, "last_flavor_choice")
    return SvBrowserSettings(cfg.get_path(SECTION, "backup_dir"), None if choice is None else choice.strip(),
                             cfg.get_bool(SECTION, SKIP_RISK_WARNING, False))


def save_settings(cfg: Config, settings: SvBrowserSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    cfg.set(SECTION, SKIP_RISK_WARNING, settings.skip_risk_warning, source=source)
    cfg.remove_retired(SECTION, source=source)
    if settings.last_flavor_choice is not None:
        cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_root(settings: SvBrowserSettings, wow_path: Path | None) -> Path | None:
    """Where snapshots/, edited/ and the crash marker live (spec D14)."""
    return tool_root(settings.backup_dir, wow_path, TOOL_NAME)
