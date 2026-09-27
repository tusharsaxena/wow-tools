"""The [wtf_cleaner] section of wow-tools.cfg."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.config import Config
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria

SECTION = "wtf_cleaner"
DEFAULT_BACKUP_SUBDIR = Path("wow-tools") / "wtf-cleaner"


@dataclass
class CleanerSettings:
    criteria: Criteria = field(default_factory=Criteria)
    backup_before_delete: bool = True
    backup_dir: Path | None = None
    last_account: str | None = None  # None (stored as empty) means all accounts


def load_settings(cfg: Config) -> CleanerSettings:
    criteria = Criteria(**{name: cfg.get_bool(SECTION, f"criterion_{name}", True) for name in CRITERIA},
                        max_age_days=max(1, cfg.get_int(SECTION, "max_age_days", 90)))
    return CleanerSettings(criteria, cfg.get_bool(SECTION, "backup_before_delete", True),
                           cfg.get_path(SECTION, "backup_dir"),
                           (cfg.get(SECTION, "last_account") or "").strip() or None)


def save_settings(cfg: Config, settings: CleanerSettings, *, source: str = "settings") -> None:
    cfg.set(SECTION, "max_age_days", settings.criteria.max_age_days, source=source)
    for name in CRITERIA:
        cfg.set(SECTION, f"criterion_{name}", getattr(settings.criteria, name), source=source)
    cfg.set(SECTION, "backup_before_delete", settings.backup_before_delete, source=source)
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    cfg.set(SECTION, "last_account", settings.last_account or "", source=source)
    cfg.save()


def resolve_backup_dir(cfg: Config, settings: CleanerSettings, override: Path | None = None) -> Path | None:
    """Where backup zips go: the override, else the saved setting, else <WoW folder>/wow-tools/wtf-cleaner."""
    if override is not None:
        return override
    if settings.backup_dir is not None:
        return settings.backup_dir
    wow = cfg.wow_path
    return wow / DEFAULT_BACKUP_SUBDIR if wow is not None else None
