"""The Macro Editor inside the suite app (config tools spec ME1, ME2, X1): (first run: settings) → flavor (or All
flavors) → the browse screen. No USE AT YOUR OWN RISK popup, as on the Config Copier: it writes only the client's own
macros-cache.txt, every change staged and reviewed, with backups and Undo; the browse screen carries the red banner
(STD-7.10), since Delete and Overwrite remove macros."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Label

from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.install import Flavor, WowInstall, validate_backup_dir
from wowtools.tools.macro_editor.review_screen import TITLE, MacroReviewScreen
from wowtools.tools.macro_editor.settings import (SECTION, MacroSettings, load_settings, resolve_root,
                                                  save_settings)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen, folder_hint
from wowtools.ui.tool_flow import ToolFlow

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class MacroSettingsScreen(ToolSettingsScreen):
    FORM_TITLE = f"{TITLE} settings"
    FIRST_FIELD = "backup-dir"

    def load(self, tool_cfg: Config) -> MacroSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        yield Label("Backup folder: holds snapshots/ (whole WTF folder) and edited/ (each changed file as it "
                    "was). Leave empty to use <WoW folder>/wow-tools/macro-editor")
        yield self.folder_input(self.settings.backup_dir, id="backup-dir",
                                placeholder=folder_hint(resolve_root(MacroSettings(), self.wow_path)))

    def save(self) -> bool:
        backup_dir = self.folder_value("backup-dir")
        if self.wow_path is not None:
            problem = validate_backup_dir(backup_dir, WowInstall(self.wow_path))
            if problem:
                self._error(problem)
                return False
        stored = load_settings(self.tool_cfg)  # keeps the remembered flavor choice
        save_settings(self.tool_cfg, replace(stored, backup_dir=backup_dir), source=self.source)
        return True


class MacroEditorFlow(ToolFlow):
    """The editor's workflow. Its settings live in config/macro-editor.cfg; the WoW folder is shared. No account
    picker: the browse screen shows every account of the flavors chosen."""

    SECTION = SECTION
    SETTINGS_SCREEN = MacroSettingsScreen

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check  # tests inject it; None: the review builds one for the flavors it writes
        self.flavors: list[Flavor] = []

    def _pick_flavor(self) -> None:
        install = self.install()
        if install is None:
            self.start()
            return
        self.flavors = install.flavors()
        self.app.push_screen(FlavorScreen(self.cfg, install, include_all=True, flavors=self.flavors,
                                          last=load_settings(self.tool_cfg).last_flavor_choice),
                             self._after_flavor)

    def _after_flavor(self, choice: Flavor | str | None) -> None:
        if choice is None:
            self.close()
            return
        self.remember_flavor(choice)
        if choice == ALL_FLAVORS:
            flavors, label = list(self.flavors), "All flavors"
        else:
            assert isinstance(choice, Flavor)
            flavors, label = [choice], choice.display_name
        log_event("macro.started", flavors=[f.folder for f in flavors], label=label)
        self.app.push_screen(MacroReviewScreen(self.cfg, self.tool_cfg, flavors, label, wow_check=self._wow_check),
                             self._after_review)


FLOW = MacroEditorFlow
