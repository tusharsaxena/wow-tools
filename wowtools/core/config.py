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
GENERAL = "general"
# Retention, shared by every tool ([general]): backups (snapshots, dry-run zips, Interface Backup zips) kept per
# flavor, 0 = keep all; and run journals kept per tool, at least 1.
DEFAULT_KEEP_BACKUPS = 10
DEFAULT_KEEP_JOURNALS = 10
# Game versions a tool works on at once ([general] parallelism, core/parallel.py), 1-8. 2 suits an SSD; a hard drive
# or a WSL /mnt (drvfs) folder is often faster with 1, since parallel zips there fight over the same disk.
DEFAULT_PARALLELISM = 2
MIN_PARALLELISM = 1
MAX_PARALLELISM = 8
# The per-tool keys these replaced: ignored when read, removed when a tool saves its settings.
RETIRED_TOOL_KEYS = ("keep_backups", "keep_snapshots", "keep_journals")
# A tool's own setting (WTF Cleaner, Ace3 Profile Manager, SV Browser): true = never show its USE AT YOUR OWN RISK
# popup (spec 2026-10-07-feedback-bars-leftovers L8). Its "Don't show this warning again" box sets it.
SKIP_RISK_WARNING = "skip_risk_warning"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(Exception):
    """A config file exists but cannot be read."""


def tool_config_path(tool: str, config_dir: Path = CONFIG_DIR) -> Path:
    """config/<tool>.cfg, e.g. config/wtf-cleaner.cfg."""
    return config_dir / f"{tool}.cfg"


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
    def parallelism(self) -> int:
        """Game versions worked on at once (core/parallel.py), clamped to 1-8; unreadable gives the default (2)."""
        value = self.get_int(GENERAL, "parallelism", DEFAULT_PARALLELISM)
        return max(MIN_PARALLELISM, min(MAX_PARALLELISM, value))

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
