"""The WTF Cleaner inside the suite app: (first run: settings) → flavor (or All flavors) → account (one flavor
only) → the USE AT YOUR OWN RISK warning (once per app session) → review → confirm → result."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Input, Label

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall, validate_backup_dir
from wowtools.tools.wtf_cleaner.report import CRITERION_LABELS, DISCLAIMER
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
    DEFAULT_CSS = ToolSettingsScreen.DEFAULT_CSS + """
    CleanerSettingsScreen #max-age-row { height: 1; }
    CleanerSettingsScreen #max-age-row Label { width: auto; }
    CleanerSettingsScreen #max_age { width: 10; }
    """
    FIRST_FIELD = "max_age"
    TICKS = True

    def load(self, tool_cfg: Config) -> CleanerSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        criteria = self.settings.criteria
        # Label and box on one row (a compact box): with five rules the form still shows whole at 120x30.
        with Horizontal(id="max-age-row"):
            yield Label("Propose SavedVariables older than this many days: ")
            yield Input(str(criteria.max_age_days), type="integer", id="max_age", compact=True)
        # One line each: the form shows whole, Save included, at 120x30 (the default is the folder's placeholder).
        yield Label("Backup folder for backup/ (whole WTF folder) and cleaned/ (files removed); empty = default")
        yield self.folder_input(self.settings.backup_dir, id="backup_dir",
                                placeholder=folder_hint(resolve_backup_dir(CleanerSettings(), self.wow_path)))
        yield Label("Propose SavedVariables when:")  # a plain label, not a spaced .title: the form fits at 120x30
        for name in CRITERIA:
            yield Ka0sCheckbox(CRITERION_LABELS[name], getattr(criteria, name), id=f"sw_{name}", compact=True)
        yield Ka0sCheckbox("Zip the files to clean before deleting them (recommended)",
                           self.settings.backup_before_delete, id="sw_backup", compact=True)
        yield Label("Cleaned-files zips to keep per game version (0 keeps all; they hold what Clean deleted)")
        yield Input(str(self.settings.keep_cleaned), type="integer", id="keep_cleaned")

    def save(self) -> bool:
        try:
            days = int(self.query_one("#max_age", Input).value)
        except ValueError:
            days = 0
        if days < 1:
            self._error("Max age must be a whole number of days, at least 1.")
            return False
        try:
            keep_cleaned = int(self.query_one("#keep_cleaned", Input).value)
        except ValueError:
            keep_cleaned = -1
        if keep_cleaned < 0:
            self._error("Cleaned-files zips to keep must be a whole number, 0 or more (0 keeps all).")
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
                                             backup_dir=backup_dir, keep_cleaned=keep_cleaned),
                      source=self.source)
        return True


class WtfCleanerFlow(ToolFlow):
    """The cleaner's own workflow. Its settings live in config/wtf-cleaner.cfg; the WoW folder and the last
    flavor are shared suite settings. The USE AT YOUR OWN RISK warning (L4) comes after the flavor and account picks
    until it is accepted once in the app session (ToolFlow.ask_disclaimer)."""

    SECTION = SECTION
    SETTINGS_SCREEN = CleanerSettingsScreen
    DISCLAIMER = DISCLAIMER
    DISCLAIMER_EVENTS = ("clean.disclaimer_accepted", "clean.disclaimer_declined")

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
        folders = [f.folder for f in (flavors if isinstance(flavors, list) else [flavors])]
        self.ask_disclaimer(lambda: self._open_review(flavors, account), flavors=folders, account=account)

    def _open_review(self, flavors: Flavor | list[Flavor], account: str | None) -> None:
        self.app.push_screen(ReviewScreen(self.cfg, self.tool_cfg, flavors, account=account,
                                          wow_check=self._wow_check, locker_check=self._locker_check),
                             self._after_review)


FLOW = WtfCleanerFlow
