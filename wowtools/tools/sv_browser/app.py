"""The Saved Variables Browser inside the suite app: (first run: settings) → flavor (or All flavors) → the USE AT YOUR
OWN RISK warning (once per opening of the tool) → review."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Label

from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.install import Flavor, WowInstall, validate_backup_dir
from wowtools.tools.sv_browser.popups import ACCEPT, DisclaimerScreen
from wowtools.tools.sv_browser.review_screen import TITLE, SvReviewScreen
from wowtools.tools.sv_browser.settings import (SECTION, SvBrowserSettings, load_settings, resolve_root,
                                                save_settings)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen, folder_hint
from wowtools.ui.tool_flow import ToolFlow

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class SvBrowserSettingsScreen(ToolSettingsScreen):
    FORM_TITLE = f"{TITLE} settings"
    FIRST_FIELD = "backup-dir"

    def load(self, tool_cfg: Config) -> SvBrowserSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        yield Label("Backup folder: holds snapshots/ (whole WTF folder) and edited/ (each changed file as it "
                    "was). Leave empty to use <WoW folder>/wow-tools/sv-browser")
        yield self.folder_input(self.settings.backup_dir, id="backup-dir",
                                placeholder=folder_hint(resolve_root(SvBrowserSettings(), self.wow_path)))

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


class SvBrowserFlow(ToolFlow):
    """The browser's workflow. Its settings live in config/sv-browser.cfg; the WoW folder is shared. No account
    picker (spec D3): the review shows every account. The USE AT YOUR OWN RISK warning (D2) comes after the flavor
    pick until it is accepted; `accepted` lives on the flow, so it is asked again each time the tool is opened from
    the menu, but not when the user goes back to the flavor picker and picks again (nor on a rescan)."""

    SECTION = SECTION
    SETTINGS_SCREEN = SvBrowserSettingsScreen

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check  # tests inject it; None: the review builds one for its flavors
        self.flavors: list[Flavor] = []
        self.accepted = False

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
        if self.accepted:
            self._review(flavors, label)
            return
        self.app.push_screen(DisclaimerScreen(), lambda answer: self._after_disclaimer(answer, flavors, label))

    def _after_disclaimer(self, answer: str | None, flavors: list[Flavor], label: str) -> None:
        folders = [f.folder for f in flavors]
        if answer != ACCEPT:  # Back or Esc: nothing is read
            log_event("svb.disclaimer_declined", flavors=folders)
            self._pick_flavor()
            return
        self.accepted = True
        log_event("svb.disclaimer_accepted", flavors=folders)
        self._review(flavors, label)

    def _review(self, flavors: list[Flavor], label: str) -> None:
        log_event("svb.started", flavors=[f.folder for f in flavors], label=label)
        self.app.push_screen(SvReviewScreen(self.cfg, self.tool_cfg, flavors, label, wow_check=self._wow_check),
                             self._after_review)


FLOW = SvBrowserFlow
