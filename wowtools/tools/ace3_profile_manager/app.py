"""The Ace3 Profile Manager inside the suite app: (first run: settings) → flavor (or All flavors) → account (one
flavor with several accounts only) → the USE AT YOUR OWN RISK warning (once per app session) → review → stage changes →
apply."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Button, Label, Static

from wowtools.core.blacklist import Pair, format_blacklist, unique_pairs
from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.install import Flavor, WowInstall, validate_backup_dir
from wowtools.core.text import plural
from wowtools.tools.ace3_profile_manager.blacklist_screen import BlacklistScreen
from wowtools.tools.ace3_profile_manager.report import DISCLAIMER
from wowtools.tools.ace3_profile_manager.review_screen import ProfileReviewScreen
from wowtools.tools.ace3_profile_manager.settings import (SECTION, ProfileSettings, load_settings,
                                                          resolve_root, save_settings)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen, folder_hint
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import action_button

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp

TITLE = "Ace3 Profile Manager"
RISK_WARNING_EVENT = "ace.risk_warning_changed"


class ProfileSettingsScreen(ToolSettingsScreen):
    FORM_TITLE = f"{TITLE} settings"
    FIRST_FIELD = "backup-dir"
    TICKS = True

    def __init__(self, tool_cfg: Config, wow_path: Path | None, *, source: str) -> None:
        super().__init__(tool_cfg, wow_path, source=source)
        self.blacklist = list(self.settings.blacklist)  # edited with "Edit blacklist…", written by Save

    def load(self, tool_cfg: Config) -> ProfileSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        yield Label("Backup folder: holds snapshots/ (whole WTF folder) and edited/ (each changed file as it "
                    "was). Leave empty to use <WoW folder>/wow-tools/ace3-profile-manager")
        yield self.folder_input(self.settings.backup_dir, id="backup-dir",
                                placeholder=folder_hint(resolve_root(ProfileSettings(), self.wow_path)))
        yield Label("Blacklist: addons whose profiles are shown but never changed, per flavor")
        yield Static(Text(blacklist_summary(self.blacklist)), id="blacklist-summary")
        yield action_button("Edit blacklist…", "navigate", id="edit-blacklist")
        yield self.risk_warning_box()

    def on_button_pressed(self, event: Button.Pressed) -> None:  # Save and Cancel: ToolSettingsScreen's handler
        if event.button.id == "edit-blacklist":
            self.edit_blacklist()

    def edit_blacklist(self) -> None:
        """The blacklist tree (BlacklistScreen) for every flavor of the WoW folder; its result waits for Save."""
        flavors = WowInstall(self.wow_path).flavors() if self.wow_path is not None else []
        if not flavors:
            self._error("Set the WoW folder first: the blacklist lists the addons it finds there.")
            return
        self.app.push_screen(BlacklistScreen(self.app.cfg, flavors, self.blacklist), self._blacklist_edited)

    def _blacklist_edited(self, pairs: list[Pair] | None) -> None:
        if pairs is None:
            return
        self.blacklist = pairs
        self.query_one("#blacklist-summary", Static).update(Text(blacklist_summary(pairs)))

    def save(self) -> bool:
        backup_dir = self.folder_value("backup-dir")
        if self.wow_path is not None:
            problem = validate_backup_dir(backup_dir, WowInstall(self.wow_path))
            if problem:
                self._error(problem)
                return False
        blacklist = unique_pairs(self.blacklist)
        stored = load_settings(self.tool_cfg)  # keeps the remembered flavor and account choices
        skip = self.risk_warning_skipped()
        save_settings(self.tool_cfg, replace(stored, backup_dir=backup_dir, blacklist=blacklist,
                                             skip_risk_warning=skip), source=self.source)
        self.log_risk_warning(RISK_WARNING_EVENT, stored.skip_risk_warning, skip)
        if blacklist != stored.blacklist:
            log_event("ace.blacklist_changed", pairs=format_blacklist(blacklist))
        return True


def blacklist_summary(pairs: list[Pair]) -> str:
    return f"{plural(len(pairs), 'addon')} blacklisted" if pairs else "None"


class AceProfilesFlow(ToolFlow):
    """The profile manager's workflow. Its settings live in config/ace3-profile-manager.cfg; the WoW folder is shared.
    `unlocked` holds the (casefolded) blacklisted (flavor folder, addon) pairs unlocked this session: it lives on
    the flow, so it survives going back to the flavor picker, and goes when the tool closes. The USE AT YOUR OWN RISK
    warning (L4) comes after the flavor and account picks until it is accepted once in the app session
    (ToolFlow.ask_disclaimer)."""

    SECTION = SECTION
    SETTINGS_SCREEN = ProfileSettingsScreen
    DISCLAIMER = DISCLAIMER
    DISCLAIMER_EVENTS = ("ace.disclaimer_accepted", "ace.disclaimer_declined")
    RISK_WARNING_EVENT = RISK_WARNING_EVENT
    SETTINGS_BLOCKERS = (BlacklistScreen,)

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check  # tests inject it; None: the review builds one for its flavors
        self.flavors: list[Flavor] = []
        self.unlocked: set[tuple[str, str]] = set()

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
        if choice == ALL_FLAVORS:  # every account of every flavor: no account picker
            self._review(list(self.flavors), "All flavors", None)
            return
        flavor = choice
        assert isinstance(flavor, Flavor)

        def review(account: str | None) -> None:
            label = f"{flavor.display_name} · {account}" if account else flavor.display_name
            self._review([flavor], label, account)

        self.pick_account(flavor, review)

    def _review(self, flavors: list[Flavor], label: str, account: str | None) -> None:
        self.ask_disclaimer(lambda: self._open_review(flavors, label, account), flavors=[f.folder for f in flavors],
                            account=account)

    def _open_review(self, flavors: list[Flavor], label: str, account: str | None) -> None:
        self.app.push_screen(ProfileReviewScreen(self.cfg, self.tool_cfg, flavors, label, account=account,
                                                 unlocked=self.unlocked, wow_check=self._wow_check),
                             self._after_review)


FLOW = AceProfilesFlow
