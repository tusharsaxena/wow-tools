"""The WTF Cleaner inside the suite app: (first run: settings) → flavor (or All flavors) → account (one flavor
only) → review → confirm → result."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Input, Label, Static

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall, validate_backup_dir
from wowtools.tools.wtf_cleaner.report import CRITERION_LABELS
from wowtools.tools.wtf_cleaner.review_screen import ReviewScreen
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria
from wowtools.tools.wtf_cleaner.settings import (SECTION, CleanerSettings, load_settings, resolve_backup_dir,
                                                 save_settings)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen, folder_hint
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import Ka0sCheckbox

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class CleanerSettingsScreen(ToolSettingsScreen):
    FORM_TITLE = "WTF Cleaner settings"
    FIRST_FIELD = "max_age"
    TICKS = True

    def load(self, tool_cfg: Config) -> CleanerSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        criteria = self.settings.criteria
        yield Label("Propose SavedVariables older than this many days")
        yield Input(str(criteria.max_age_days), type="integer", id="max_age")
        yield Label("Backup folder: holds backup/ (whole WTF folder) and cleaned/ (the files removed). "
                    "Leave empty to use <WoW folder>/wow-tools/wtf-cleaner")
        yield self.folder_input(self.settings.backup_dir, id="backup_dir",
                                placeholder=folder_hint(resolve_backup_dir(CleanerSettings(), self.wow_path)))
        yield Static("Propose SavedVariables when:", classes="title")
        for name in CRITERIA:
            yield Ka0sCheckbox(CRITERION_LABELS[name], getattr(criteria, name), id=f"sw_{name}", compact=True)
        yield Ka0sCheckbox("Zip the files to clean before deleting them (recommended)",
                           self.settings.backup_before_delete, id="sw_backup", compact=True)

    def save(self) -> bool:
        try:
            days = int(self.query_one("#max_age", Input).value)
        except ValueError:
            days = 0
        if days < 1:
            self._error("Max age must be a whole number of days, at least 1.")
            return False
        criteria = Criteria(**{name: self.query_one(f"#sw_{name}", Ka0sCheckbox).value for name in CRITERIA},
                            max_age_days=days)
        backup_dir = self.folder_value("backup_dir")
        if self.wow_path is not None:
            problem = validate_backup_dir(backup_dir, WowInstall(self.wow_path))
            if problem:
                self._error(problem)
                return False
        stored = load_settings(self.tool_cfg)  # keeps the remembered flavor and account choices
        save_settings(self.tool_cfg, replace(stored, criteria=criteria,
                                             backup_before_delete=self.query_one("#sw_backup", Ka0sCheckbox).value,
                                             backup_dir=backup_dir),
                      source=self.source)
        return True


class WtfCleanerFlow(ToolFlow):
    """The cleaner's own workflow. Its settings live in config/wtf-cleaner.cfg; the WoW folder and the last
    flavor are shared suite settings."""

    SECTION = SECTION
    SETTINGS_SCREEN = CleanerSettingsScreen

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None,
                 locker_check: Callable[[], list[str] | None] | None = None) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check
        self._locker_check = locker_check
        self.flavors: list[Flavor] = []

    def _pick_flavor(self) -> None:
        install = self.install()
        if install is None:
            self.start()
            return
        self.flavors = install.flavors()
        # Never chosen yet (None): FlavorScreen highlights [general] last_flavor, the habit so far.
        self.app.push_screen(FlavorScreen(self.cfg, install, include_all=True, flavors=self.flavors,
                                          last=load_settings(self.tool_cfg).last_flavor_choice),
                             self._after_flavor)

    def _after_flavor(self, choice: Flavor | str | None) -> None:
        if choice is None:
            self.close()
            return
        self.remember_flavor(choice)
        if choice == ALL_FLAVORS:  # every account of every flavor: no account picker
            self._review(list(self.flavors), None)
            return
        flavor = choice
        assert isinstance(flavor, Flavor)
        self.pick_account(flavor, lambda account: self._review(flavor, account))

    def _review(self, flavors: Flavor | list[Flavor], account: str | None) -> None:
        self.app.push_screen(ReviewScreen(self.cfg, self.tool_cfg, flavors, account=account,
                                          wow_check=self._wow_check, locker_check=self._locker_check),
                             self._after_review)


FLOW = WtfCleanerFlow
