"""The Screenshot Organizer's own settings: the [screenshot_organizer] section of config/screenshot-organizer.cfg,
plus where things go (source folder, target root, journal folder)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall, validate_output_dir
from wowtools.core.journal import journal_dir
from wowtools.tools.screenshot_organizer.events import TOOL_NAME

SECTION = "screenshot_organizer"
SCREENSHOTS_DIR = "Screenshots"
DEFAULT_KEEP_JOURNALS = 10


@dataclass
class ShotSettings:
    dest_dir: Path | None = None  # None (stored as empty) means organise in place
    copy_mode: bool = False
    last_flavor_choice: str = ""  # "" means all flavors, else a flavor folder such as _retail_
    keep_journals: int = DEFAULT_KEEP_JOURNALS


def load_settings(cfg: Config) -> ShotSettings:
    return ShotSettings(cfg.get_path(SECTION, "dest_dir"), cfg.get_bool(SECTION, "copy_mode", False),
                        (cfg.get(SECTION, "last_flavor_choice") or "").strip(),
                        max(1, cfg.get_int(SECTION, "keep_journals", DEFAULT_KEEP_JOURNALS)))


def save_settings(cfg: Config, settings: ShotSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "dest_dir", settings.dest_dir, source=source)
    cfg.set(SECTION, "copy_mode", settings.copy_mode, source=source)
    cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.set(SECTION, "keep_journals", settings.keep_journals, source=source)
    cfg.save()


def source_dir(flavor: Flavor) -> Path:
    return flavor.path / SCREENSHOTS_DIR


def target_root(flavor: Flavor, dest_dir: Path | None) -> Path:
    """Where a flavor's YYYY/MM/DD folders go: <dest>/<flavor folder>, or in place in its Screenshots folder."""
    return dest_dir / flavor.folder if dest_dir is not None else source_dir(flavor)


def resolve_journal_dir(wow_path: Path | None) -> Path | None:
    """<WoW folder>/wow-tools/screenshot-organizer/journal: never inside the screenshot archive."""
    return journal_dir(wow_path, TOOL_NAME)


def validate_dest(dest: Path | None, install: WowInstall) -> str | None:
    """Why a destination folder is not allowed, or None if it is fine (None itself means in place)."""
    problem = validate_output_dir(dest, install, what="destination", example="D:\\Screenshots")
    if problem and problem.endswith("\\Screenshots."):
        problem += " Leave it empty to organise in place."
    return problem
