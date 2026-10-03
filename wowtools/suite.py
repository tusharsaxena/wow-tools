"""What wow-tools.sh / wow-tools.cmd run: the suite app (tool menu first), or `update`.

Tools are never started on their own: they open from the menu inside the one suite app. Only one copy runs at a
time (see core/lock.py).
"""
from __future__ import annotations

import platform
import sys
import time
from pathlib import Path
from typing import Callable

from wowtools import __version__
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import (CONFIG_DIR, LEGACY_CONFIG_PATH, SUITE_CONFIG_NAME, Config, ConfigError,
                                  migrate_legacy_config)
from wowtools.core.events import init_event_log, log_event, log_exception
from wowtools.core.lock import LOCK_PATH, InstanceLock, LockInfo
from wowtools.core.migrate import ConfigMigration, merge_folder, migrate_tool_config, tool_folder_pairs
from wowtools.core.paths import is_wsl
from wowtools.core.updater import UpdateError, apply_update, check_for_update, run_update_command
from wowtools.tools import RENAMED_TOOLS, TOOLS

LOG_DIR = REPO_ROOT / "logs"


def usage() -> str:
    lines = [f"Ka0s WoW Tools v{__version__}", "",
             "Usage: wow-tools.sh (Linux/WSL) or wow-tools.cmd (Windows)", "",
             "With no arguments the tool menu opens. Every tool is opened from there:"]
    lines += [f"  {tool.title:<16} {tool.description}" for tool in TOOLS.values()]
    lines += ["", "Other commands:",
              "  update         Check for and install a newer version (--check to only look)",
              "  --version      Print the version",
              "  --help         Show this help"]
    return "\n".join(lines)


def run(argv: list[str], *, cfg: Config | None = None, log_dir: Path | None = LOG_DIR,
        config_dir: Path = CONFIG_DIR, legacy_config: Path = LEGACY_CONFIG_PATH, lock_path: Path = LOCK_PATH,
        app_factory: Callable[..., object] | None = None, input_fn: Callable[[str], str] = input) -> int:
    if argv[:1] in (["-h"], ["--help"], ["help"]):
        print(usage())
        return 0
    if argv[:1] == ["--version"]:
        print(__version__)
        return 0
    if argv and argv[0] != "update":
        hint = " Tools open from the menu: run wow-tools with no arguments." if argv[0] in TOOLS else ""
        print(f"Unknown command: {argv[0]}.{hint}\n\n{usage()}", file=sys.stderr)
        return 1
    migrated: list[Path] = []
    renamed: list[ConfigMigration] = []
    try:
        if cfg is None:
            # A legacy file may still use a renamed tool's old section: split it under the old name first.
            sections = {r.old_section: r.old for r in RENAMED_TOOLS} | {t.section: t.name for t in TOOLS.values()}
            migrated = migrate_legacy_config(legacy_config, config_dir, sections)
            cfg = Config(config_dir / SUITE_CONFIG_NAME).load()
        renamed = [m for r in RENAMED_TOOLS if (m := migrate_tool_config(config_dir, r)) is not None]
    except (ConfigError, OSError) as exc:
        print(f"{exc}\nFix or delete the file, then run again.", file=sys.stderr)
        return 1
    init_event_log(log_dir, tool="suite", mode="tui" if not argv else "cli",
                   text_level=cfg.log_level, retention_days=cfg.log_retention_days)
    if migrated:
        log_event("config.migrated", legacy=str(legacy_config), files=[str(p) for p in migrated])
    for m in renamed:
        log_event("config.renamed", old=str(m.old), new=str(m.new), merged=m.merged, added=m.added,
                  kept_old=str(m.kept_old) if m.kept_old else None)
    _migrate_renamed_folders(log_dir, cfg.wow_path)
    log_event("session.start", argv=argv, platform=platform.platform(), is_wsl=is_wsl(),
              python=platform.python_version(), suite_version=__version__)
    started = time.monotonic()
    code = 1
    lock = InstanceLock(lock_path)
    try:
        conflict = lock.acquire()
        if conflict is not None:
            log_event("lock.conflict", holder=conflict.describe(), stale=conflict.stale)
        code = _dispatch(argv, cfg, config_dir, lock, conflict, app_factory, input_fn)
        return code
    except KeyboardInterrupt:
        code = 130
        return code
    except Exception as exc:
        log_exception("suite", exc)
        raise
    finally:
        lock.release()
        log_event("session.end", level="warning" if code not in (0, 10) else None,
                  exit_code=code, duration_s=round(time.monotonic() - started, 3))


def _migrate_renamed_folders(log_dir: Path | None, wow_path: Path | None) -> None:
    """Move renamed tools' folders (logs/<old>/, <WoW>/wow-tools/<old>/) to the new name. Never fatal."""
    for rename in RENAMED_TOOLS:
        for old, new in tool_folder_pairs(rename, log_dir, wow_path):
            try:
                result = merge_folder(old, new)
            except OSError as exc:
                log_event("folder.renamed", level="error", old=str(old), new=str(new), error=str(exc))
                continue
            if result is None:
                continue
            level = "warning" if result.clashes or result.errors else None
            log_event("folder.renamed", level=level, old=str(old), new=str(new), renamed=result.renamed,
                      moved=len(result.moved), clashes=result.clashes, errors=result.errors,
                      old_removed=result.old_removed)


def _auto_update(cfg: Config) -> bool:
    """Apply an update before the menu opens when auto_update = true. True means 'exit now'."""
    if not (cfg.exists and cfg.check_for_updates and cfg.auto_update):
        return False
    release = check_for_update(cfg)
    if release is None:
        return False
    try:
        print(apply_update(release))
    except UpdateError as exc:
        print(f"Automatic update failed: {exc}", file=sys.stderr)
        return False
    return True


def _confirm_override(lock: InstanceLock, conflict: LockInfo, input_fn: Callable[[str], str]) -> bool:
    """`update` has no TUI: ask on the terminal whether to take the lock over."""
    print(f"Ka0s WoW Tools may already be running: {conflict.describe()}.\nLock file: {lock.path}",
          file=sys.stderr)
    if conflict.stale:
        print("That process is no longer running, so the lock file is probably left over from a crash.",
              file=sys.stderr)
    try:
        answer = input_fn("Override the lock and continue anyway? [y/N] ")
    except EOFError:
        answer = ""
    override = answer.strip().lower() in ("y", "yes")
    log_event("ui.selection", screen="lock", control="lock", value="override" if override else "quit")
    if override:
        lock.take_over()
        log_event("lock.overridden", holder=conflict.describe())
    return override


def _dispatch(argv: list[str], cfg: Config, config_dir: Path, lock: InstanceLock, conflict: LockInfo | None,
              app_factory: Callable[..., object] | None, input_fn: Callable[[str], str]) -> int:
    if argv:  # update
        if conflict is not None and not _confirm_override(lock, conflict, input_fn):
            return 1
        return run_update_command(argv[1:], cfg)
    if conflict is None and _auto_update(cfg):  # never update under another running copy
        return 0
    if app_factory is None:
        from wowtools.ui.suite_app import WowToolsApp

        app_factory = WowToolsApp
    app = app_factory(cfg, config_dir=config_dir, lock=lock, conflict=conflict)
    app.run()
    return 0
