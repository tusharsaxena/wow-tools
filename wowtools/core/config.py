"""Config files in config/: one for the suite and one per tool.

config/wow-tools.cfg holds [general] (WoW folder, updates, logging), shared by every tool. Each tool keeps its own
settings in config/<tool>.cfg, in one section named after it (e.g. [wtf_cleaner] in config/wtf-cleaner.cfg).
Unknown keys are preserved. Bad values fall back to defaults instead of failing.
"""
from __future__ import annotations

import configparser
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.events import LEVELS, log_event
from wowtools.core.fsutil import atomic_write_text
from wowtools.core.paths import to_native, to_stored

CONFIG_DIR = REPO_ROOT / "config"
SUITE_CONFIG_NAME = "wow-tools.cfg"
DEFAULT_CONFIG_PATH = CONFIG_DIR / SUITE_CONFIG_NAME
LEGACY_CONFIG_PATH = REPO_ROOT / "wow-tools.cfg"  # the single shared file used before config/
GENERAL = "general"
# [general] keys that nothing reads any more; dropped when a legacy config is migrated.
RETIRED_GENERAL_KEYS = ("backup_dir",)
# Retention, shared by every tool ([general]): backups (snapshots, dry-run zips, Interface Backup zips) kept per
# flavor, 0 = keep all; and run journals kept per tool, at least 1.
DEFAULT_KEEP_BACKUPS = 10
DEFAULT_KEEP_JOURNALS = 10
# The per-tool keys these replaced: ignored when read, removed when a tool saves its settings.
RETIRED_TOOL_KEYS = ("keep_backups", "keep_snapshots", "keep_journals")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(Exception):
    """A config file exists but cannot be read."""


def tool_config_path(tool: str, config_dir: Path = CONFIG_DIR) -> Path:
    """config/<tool>.cfg, e.g. config/wtf-cleaner.cfg."""
    return config_dir / f"{tool}.cfg"


def migrate_legacy_config(legacy: Path, config_dir: Path, tool_sections: dict[str, str]) -> list[Path]:
    """Split the old shared wow-tools.cfg into config/: [general] to wow-tools.cfg, and each tool's section
    (tool_sections maps section -> tool name) to config/<tool>.cfg. Other sections stay with [general].

    Runs only when the legacy file exists and config/wow-tools.cfg does not. The legacy file is removed once
    every new file is written. Returns the files written ([] if there was nothing to do). Raises ConfigError if
    the legacy file cannot be read, or OSError if a new file cannot be written (the legacy file is then kept)."""
    target = config_dir / SUITE_CONFIG_NAME
    if not legacy.is_file() or target.exists():
        return []
    old = Config(legacy).load()
    files: dict[Path, configparser.ConfigParser] = {}
    for section in old._parser.sections():
        tool = tool_sections.get(section)
        path = tool_config_path(tool, config_dir) if tool else target
        parser = files.setdefault(path, configparser.ConfigParser(interpolation=None))
        parser.add_section(section)
        for key, value in old._parser.items(section, raw=True):
            if section == GENERAL and key in RETIRED_GENERAL_KEYS:
                continue
            parser.set(section, key, value)
    files.setdefault(target, configparser.ConfigParser(interpolation=None))
    config_dir.mkdir(parents=True, exist_ok=True)
    for path, parser in files.items():
        atomic_write_text(path, _render(parser))
    legacy.unlink()
    return sorted(files)


def _render(parser: configparser.ConfigParser) -> str:
    buffer = io.StringIO()
    parser.write(buffer)
    return buffer.getvalue()


def _to_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class Config:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        self.exists = False
        self._parser = configparser.ConfigParser(interpolation=None)

    def load(self) -> Config:
        if self.path.is_file():
            try:
                with self.path.open(encoding="utf-8") as handle:
                    self._parser.read_file(handle)
            except (configparser.Error, UnicodeDecodeError, OSError) as exc:
                raise ConfigError(f"Cannot read {self.path}: {exc}") from exc
            self.exists = True
        return self

    def save(self) -> None:
        """Write the file atomically (a crash or a concurrent reader never sees a half-written config).
        Call it from one thread only: the UI thread in the app (see Ka0sApp._persist_update_state)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, _render(self._parser))
        if not self.exists:
            self.exists = True
            log_event("config.created", path=str(self.path))

    def save_if_exists(self) -> None:
        if self.exists:
            self.save()

    # --- raw access -------------------------------------------------------------------------
    def get(self, section: str, key: str, fallback: str | None = None) -> str | None:
        return self._parser.get(section, key, fallback=fallback)

    def get_int(self, section: str, key: str, fallback: int) -> int:
        raw = self.get(section, key)
        try:
            return int(raw) if raw is not None else fallback
        except ValueError:
            return fallback

    def get_bool(self, section: str, key: str, fallback: bool) -> bool:
        raw = self.get(section, key)
        if raw is None:
            return fallback
        value = raw.strip().lower()
        if value in _TRUE:
            return True
        if value in _FALSE:
            return False
        return fallback

    def set(self, section: str, key: str, value: Any, *, source: str = "app", log: bool = True) -> None:
        new = _to_text(value)
        old = self.get(section, key)
        if old == new:
            return
        if not self._parser.has_section(section):
            self._parser.add_section(section)
        self._parser.set(section, key, new)
        if log:
            log_event("config.changed", section=section, key=key, old=old, new=new, source=source)

    def remove(self, section: str, key: str, *, source: str = "app", log: bool = True) -> None:
        """Drop a key (nothing happens when it is not there). Logged as a change to None."""
        old = self.get(section, key)
        if old is None:
            return
        self._parser.remove_option(section, key)
        if log:
            log_event("config.changed", section=section, key=key, old=old, new=None, source=source)

    def remove_retired(self, section: str, *, source: str = "app") -> None:
        """Drop the per-tool retention keys that [general] keep_backups / keep_journals replaced."""
        for key in RETIRED_TOOL_KEYS:
            self.remove(section, key, source=source)

    def get_path(self, section: str, key: str) -> Path | None:
        raw = (self.get(section, key) or "").strip()
        return to_native(raw) if raw else None

    def set_path(self, section: str, key: str, value: Path | str | None, *, source: str = "app") -> None:
        self.set(section, key, to_stored(value) if value else "", source=source)

    # --- [general] --------------------------------------------------------------------------
    @property
    def wow_path(self) -> Path | None:
        return self.get_path(GENERAL, "wow_path")

    @property
    def last_flavor(self) -> str | None:
        return self.get(GENERAL, "last_flavor") or None

    @property
    def check_for_updates(self) -> bool:
        return self.get_bool(GENERAL, "check_for_updates", True)

    @property
    def auto_update(self) -> bool:
        return self.get_bool(GENERAL, "auto_update", False)

    @property
    def allow_unverified_updates(self) -> bool:
        """Let a zip install update from a release with no SHA256SUMS asset (off: such an update is refused)."""
        return self.get_bool(GENERAL, "allow_unverified_updates", False)

    @property
    def log_level(self) -> str:
        value = (self.get(GENERAL, "log_level") or "info").strip().lower()
        return value if value in LEVELS else "info"

    @property
    def log_retention_days(self) -> int:
        return max(1, self.get_int(GENERAL, "log_retention_days", 90))

    @property
    def keep_backups(self) -> int:
        """Backups kept per flavor by every tool; 0 = keep all. A negative or unreadable value gives the default."""
        value = self.get_int(GENERAL, "keep_backups", DEFAULT_KEEP_BACKUPS)
        return value if value >= 0 else DEFAULT_KEEP_BACKUPS

    @property
    def keep_journals(self) -> int:
        """Run journals kept per tool (at least 1: Undo uses the newest)."""
        return max(1, self.get_int(GENERAL, "keep_journals", DEFAULT_KEEP_JOURNALS))

    @property
    def last_update_check(self) -> datetime | None:
        raw = self.get(GENERAL, "last_update_check")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @property
    def latest_seen_version(self) -> str | None:
        return self.get(GENERAL, "latest_seen_version") or None
