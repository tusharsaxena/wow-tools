"""The Config Copier inside the suite app (config tools spec CC2, X1): (first run: settings) → flavor (or All
flavors) → source picker (one character, the shared character tree) → review. The review's targets are the source's
flavor only; other flavors' characters show greyed. No USE AT YOUR OWN RISK popup: the copier writes only the
client's own five files, between characters of one game version, with backups and Undo (as Interface Backup's
restore, which has none either)."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Label

from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.install import Character, Flavor, WowInstall, validate_backup_dir
from wowtools.tools.config_copier.review_screen import TITLE, CopierReviewScreen
from wowtools.tools.config_copier.settings import (SECTION, CopierSettings, load_settings, resolve_root,
                                                   save_settings)
from wowtools.tools.config_copier.source_screen import BACK, TOOLS, SourceScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen, folder_hint
from wowtools.ui.tool_flow import ToolFlow

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class CopierSettingsScreen(ToolSettingsScreen):
    FORM_TITLE = f"{TITLE} settings"
    FIRST_FIELD = "backup-dir"

    def load(self, tool_cfg: Config) -> CopierSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        yield Label("Backup folder: holds snapshots/ (whole WTF folder) and edited/ (each replaced file as it "
                    "was). Leave empty to use <WoW folder>/wow-tools/config-copier")
        yield self.folder_input(self.settings.backup_dir, id="backup-dir",
                                placeholder=folder_hint(resolve_root(CopierSettings(), self.wow_path)))

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


class CopierFlow(ToolFlow):
    """The copier's workflow. Its settings live in config/config-copier.cfg; the WoW folder is shared. No account
    picker: the source picker and the review show every account of the flavors chosen."""

    SECTION = SECTION
    SETTINGS_SCREEN = CopierSettingsScreen

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check  # tests inject it; None: the review builds one for the source's flavor
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
        self._pick_source(flavors, label)

    def _pick_source(self, flavors: list[Flavor], label: str) -> None:
        def chosen(choice: tuple[Flavor, Character] | str | None) -> None:
            if choice == TOOLS:
                self.close()
            elif choice is None or choice == BACK:
                self._pick_flavor()
            else:
                assert isinstance(choice, tuple)
                self._review(flavors, label, *choice)
        self.app.push_screen(SourceScreen(flavors, label), chosen)

    def _review(self, flavors: list[Flavor], label: str, flavor: Flavor, source: Character) -> None:
        log_event("copier.started", flavors=[f.folder for f in flavors],
                  source=f"{flavor.folder}/{source.account}/{source.label}")
        self.app.push_screen(CopierReviewScreen(self.cfg, self.tool_cfg, flavors, label, flavor, source,
                                                wow_check=self._wow_check), self._after_review)


FLOW = CopierFlow
