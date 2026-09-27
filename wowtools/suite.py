"""Dispatcher for `python -m wowtools`: tools, `update`, the tool picker, sessions and auto-update."""
from __future__ import annotations

import platform
import sys
import time
from pathlib import Path

from wowtools import __version__
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import Config, ConfigError
from wowtools.core.events import get_event_log, init_event_log, log_event, log_exception
from wowtools.core.paths import is_wsl
from wowtools.core.updater import UpdateError, apply_update, check_for_update, run_update_command
from wowtools.tools import TOOLS

LOG_DIR = REPO_ROOT / "logs"


def usage() -> str:
    lines = [f"Ka0s WoW Tools v{__version__}", "",
             "Usage: python -m wowtools [TOOL] [OPTIONS]", "",
             "With no TOOL, a menu of tools opens.", "", "Tools:"]
    lines += [f"  {tool.name:<14} {tool.description}" for tool in TOOLS.values()]
    lines += ["", "Other commands:",
              "  update         Check for and install a newer version (--check to only look)",
              "  --version      Print the version", "",
              "Run `python -m wowtools TOOL --help` for a tool's options."]
    return "\n".join(lines)


def run(argv: list[str], *, cfg: Config | None = None, log_dir: Path | None = LOG_DIR) -> int:
    if argv[:1] in (["-h"], ["--help"], ["help"]):
        print(usage())
        return 0
    if argv[:1] == ["--version"]:
        print(__version__)
        return 0
    try:
        cfg = cfg if cfg is not None else Config().load()
    except ConfigError as exc:
        print(f"{exc}\nFix or delete the file, then run again.", file=sys.stderr)
        return 1
    command = argv[0] if argv and not argv[0].startswith("-") else None
    init_event_log(log_dir, tool=command if command in TOOLS else "suite", mode="cli",
                   text_level=cfg.log_level, retention_days=cfg.log_retention_days)
    log_event("session.start", argv=argv, platform=platform.platform(), is_wsl=is_wsl(),
              python=platform.python_version(), suite_version=__version__)
    started = time.monotonic()
    code = 1
    try:
        code = _dispatch(argv, command, cfg)
        return code
    except KeyboardInterrupt:
        code = 130
        return code
    except Exception as exc:
        log_exception("suite", exc)
        raise
    finally:
        log_event("session.end", level="warning" if code not in (0, 10) else None,
                  exit_code=code, duration_s=round(time.monotonic() - started, 3))


def _auto_update(cfg: Config) -> bool:
    """Apply an update before any tool starts when auto_update = true. True means 'exit now'."""
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


def _dispatch(argv: list[str], command: str | None, cfg: Config) -> int:
    if command is None and argv:
        print(usage(), file=sys.stderr)
        return 1
    if command == "update":
        return run_update_command(argv[1:], cfg)
    if command is not None and command not in TOOLS:
        print(f"Unknown tool: {command}\n\n{usage()}", file=sys.stderr)
        return 1
    if _auto_update(cfg):
        return 0
    if command is None:
        from wowtools.ui.tool_picker import ToolPickerApp

        get_event_log().set_context(mode="tui")
        picked = ToolPickerApp(cfg).run()
        if not picked:
            return 0
        get_event_log().set_context(tool=picked)
        return TOOLS[picked].main()([], cfg=cfg)
    return TOOLS[command].main()(argv[1:], cfg=cfg)
