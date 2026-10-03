"""The WTF Cleaner's own settings: the [wtf_cleaner] section of config/wtf-cleaner.cfg."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.config import Config
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria
from wowtools.tools.wtf_cleaner.safety import DEFAULT_KEEP_SNAPSHOTS

SECTION = "wtf_cleaner"
DEFAULT_BACKUP_SUBDIR = Path("wow-tools") / "wtf-cleaner"
DEFAULT_KEEP_JOURNALS = 10


@dataclass
class CleanerSettings:
    criteria: Criteria = field(default_factory=Criteria)
    backup_before_delete: bool = True
    backup_dir: Path | None = None
    last_account: str | None = None  # None (stored as empty) means all accounts
    keep_backups: int = DEFAULT_KEEP_SNAPSHOTS  # WTF backups to keep per flavor (backup/backup-<flavor>-<stamp>.zip)
    # The flavor picker's last choice: "" means All flavors, else a flavor folder such as _retail_. None means
    # never chosen (not stored); the picker then highlights [general] last_flavor.
    last_flavor_choice: str | None = None
    keep_journals: int = DEFAULT_KEEP_JOURNALS  # run journals to keep (<WoW>/wow-tools/wtf-cleaner/journal)


def load_settings(cfg: Config) -> CleanerSettings:
    choice = cfg.get(SECTION, "last_flavor_choice")
    criteria = Criteria(**{name: cfg.get_bool(SECTION, f"criterion_{name}", True) for name in CRITERIA},
                        max_age_days=max(1, cfg.get_int(SECTION, "max_age_days", 90)))
    return CleanerSettings(criteria, cfg.get_bool(SECTION, "backup_before_delete", True),
                           cfg.get_path(SECTION, "backup_dir"),
                           (cfg.get(SECTION, "last_account") or "").strip() or None,
                           max(1, cfg.get_int(SECTION, "keep_backups", DEFAULT_KEEP_SNAPSHOTS)),
                           None if choice is None else choice.strip(),
                           max(1, cfg.get_int(SECTION, "keep_journals", DEFAULT_KEEP_JOURNALS)))


def save_settings(cfg: Config, settings: CleanerSettings, *, source: str = "settings") -> None:
    cfg.set(SECTION, "max_age_days", settings.criteria.max_age_days, source=source)
    for name in CRITERIA:
        cfg.set(SECTION, f"criterion_{name}", getattr(settings.criteria, name), source=source)
    cfg.set(SECTION, "backup_before_delete", settings.backup_before_delete, source=source)
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    cfg.set(SECTION, "last_account", settings.last_account or "", source=source)
    cfg.set(SECTION, "keep_backups", settings.keep_backups, source=source)
    cfg.set(SECTION, "keep_journals", settings.keep_journals, source=source)
    if settings.last_flavor_choice is not None:
        cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_backup_dir(settings: CleanerSettings, wow_path: Path | None) -> Path | None:
    """The cleaner's output folder (backup/ and cleaned/ live in it): the saved setting, else
    <WoW folder>/wow-tools/wtf-cleaner."""
    if settings.backup_dir is not None:
        return settings.backup_dir
    return wow_path / DEFAULT_BACKUP_SUBDIR if wow_path is not None else None
