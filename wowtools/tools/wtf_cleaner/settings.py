"""The [wtf_cleaner] section of wow-tools.cfg."""
from __future__ import annotations

from dataclasses import dataclass, field

from wowtools.core.config import Config
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria

SECTION = "wtf_cleaner"


@dataclass
class CleanerSettings:
    criteria: Criteria = field(default_factory=Criteria)
    backup_before_delete: bool = True


def load_settings(cfg: Config) -> CleanerSettings:
    criteria = Criteria(**{name: cfg.get_bool(SECTION, f"criterion_{name}", True) for name in CRITERIA},
                        max_age_days=max(1, cfg.get_int(SECTION, "max_age_days", 90)))
    return CleanerSettings(criteria, cfg.get_bool(SECTION, "backup_before_delete", True))


def save_settings(cfg: Config, settings: CleanerSettings, *, source: str = "settings") -> None:
    cfg.set(SECTION, "max_age_days", settings.criteria.max_age_days, source=source)
    for name in CRITERIA:
        cfg.set(SECTION, f"criterion_{name}", getattr(settings.criteria, name), source=source)
    cfg.set(SECTION, "backup_before_delete", settings.backup_before_delete, source=source)
    cfg.save()
