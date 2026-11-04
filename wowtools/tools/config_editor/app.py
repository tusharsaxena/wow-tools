"""The Config Editor inside the suite app (config tools spec CE1, CE2, X1): (first run: settings) → flavor (or All
flavors) → the browse screen. No USE AT YOUR OWN RISK popup, as on the Config Copier and the Macro Editor: it writes
only the client's own Config.wtf and config-cache.wtf, every change staged and reviewed, with backups and Undo; the
browse screen carries the red banner (STD-7.10), since Remove and Reset take CVar lines out."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Label

from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.install import Flavor, WowInstall, validate_backup_dir
from wowtools.tools.config_editor.review_screen import TITLE, ConfigReviewScreen
from wowtools.tools.config_editor.settings import (SECTION, ConfigEditorSettings, load_settings, resolve_root,
                                                   save_settings)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen, folder_hint
from wowtools.ui.tool_flow import ToolFlow

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class ConfigEditorSettingsScreen(ToolSettingsScreen):
    FORM_TITLE = f"{TITLE} settings"
    FIRST_FIELD = "backup-dir"

    def load(self, tool_cfg: Config) -> ConfigEditorSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        yield Label("Backup folder: holds snapshots/ (whole WTF folder) and edited/ (each changed file as it "
                    "was). Leave empty to use <WoW folder>/wow-tools/config-editor")
        yield self.folder_input(self.settings.backup_dir, id="backup-dir",
                                placeholder=folder_hint(resolve_root(ConfigEditorSettings(), self.wow_path)))

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


class ConfigEditorFlow(ToolFlow):
    """The editor's workflow. Its settings live in config/config-editor.cfg; the WoW folder is shared. No account
    picker: the browse screen shows every account of the flavors chosen."""

    SECTION = SECTION
    SETTINGS_SCREEN = ConfigEditorSettingsScreen

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None, kb_root: Path | None = None) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check  # tests inject it; None: the review builds one for the flavors it writes
        self._kb_root = kb_root  # tests point it at a temp knowledge base; None: wowtools/kb
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
        log_event("cvar.started", flavors=[f.folder for f in flavors], label=label)
        self.app.push_screen(ConfigReviewScreen(self.cfg, self.tool_cfg, flavors, label, wow_check=self._wow_check,
                                                kb_root=self._kb_root),
                             self._after_review)


FLOW = ConfigEditorFlow
