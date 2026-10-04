"""ToolFlow: how a tool runs inside the suite app. Each tool has its own screens, workflow and config file."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from wowtools.core.config import Config
from wowtools.core.install import WowInstall
from wowtools.ui.setup_screen import SetupScreen

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class ToolFlow:
    """One open tool. The suite app makes one when the tool is picked from the menu and drops it on close().

    Subclasses implement start() (push the tool's first screen) and may implement open_settings() (the `s` key).
    self.cfg is the shared suite config (WoW folder, updates, logging); self.tool_cfg is the tool's own file.
    """

    def __init__(self, app: WowToolsApp, tool_cfg: Config) -> None:
        self.app = app
        self.cfg = app.cfg
        self.tool_cfg = tool_cfg

    def start(self) -> None:
        raise NotImplementedError

    def open_settings(self) -> None:
        self.app.open_general_settings()

    def close(self) -> None:
        """Leave the tool and go back to the tool menu."""
        self.app.close_tool()

    def install(self) -> WowInstall | None:
        path = self.cfg.wow_path
        if path is None:
            return None
        install = WowInstall(path)
        return install if install.is_valid() else None

    def require_install(self, then: Callable[[WowInstall, bool], None]) -> None:
        """Call then(install, first_run) once a valid WoW folder is configured. If none is, the shared setup screen
        asks for it first (first_run=True); cancelling it closes the tool."""
        install = self.install()
        if install is not None:
            then(install, False)
            return

        def after_setup(ok: bool | None) -> None:
            install = self.install() if ok else None
            if install is None:
                self.close()
            else:
                then(install, True)

        self.app.push_screen(SetupScreen(self.cfg, first_run=True, detect=self.app.detect), after_setup)
