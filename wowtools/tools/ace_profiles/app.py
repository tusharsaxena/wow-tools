"""The Ace3 Profile Manager inside the suite app: (first run: settings) → flavor (or All flavors) → account (one
flavor with several accounts only) → review → stage changes → apply."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.paths import to_native, to_stored
from wowtools.tools.ace_profiles.blacklist_screen import BlacklistScreen
from wowtools.tools.ace_profiles.report import plural
from wowtools.tools.ace_profiles.review_screen import ProfileReviewScreen
from wowtools.tools.ace_profiles.settings import (SECTION, Pair, ProfileSettings, format_blacklist, load_settings,
                                                  resolve_root, save_settings, unique_pairs, validate_backup_dir)
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import settings_css
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, FormScroll, NavHint, action_button

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp

TITLE = "Ace3 Profile Manager"


class ProfileSettingsScreen(Screen[bool]):
    DEFAULT_CSS = settings_css("ProfileSettingsScreen")
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, tool_cfg: Config, wow_path: Path | None, *, source: str) -> None:
        super().__init__()
        self.tool_cfg = tool_cfg
        self.wow_path = wow_path
        self.source = source
        self.settings = load_settings(tool_cfg)
        self.blacklist = list(self.settings.blacklist)  # edited with "Edit blacklist…", written by Save
        self.error_text = ""

    def compose(self) -> ComposeResult:
        settings = self.settings
        yield Header()
        with FormScroll(id="settings", can_focus=False):
            yield Static(f"{TITLE} settings", classes="title")
            yield Label("Backup folder: holds snapshots/ (whole WTF folder) and edited/ (each changed file as it "
                        "was). Leave empty to use <WoW folder>/wow-tools/ace-profiles")
            yield Input(to_stored(settings.backup_dir) if settings.backup_dir else "",
                        placeholder=_default_backup_hint(self.wow_path), id="backup-dir")
            yield Label("Blacklist: addons whose profiles are shown but never changed, per flavor")
            yield Static(Text(blacklist_summary(self.blacklist)), id="blacklist-summary")
            yield action_button("Edit blacklist…", "neutral", id="edit-blacklist")
            yield Static("", id="settings-error")
            with ButtonRow(classes="buttons"):
                yield action_button("Save", "confirm", id="save")
                yield action_button("Cancel", "neutral", id="cancel")
            yield NavHint("↑↓/Tab move · ←→ buttons · Enter/Space press · Esc cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"{TITLE} settings"
        self.query_one("#backup-dir", Input).focus()
        self.query_one("#settings", FormScroll).open_at_top()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        elif event.button.id == "edit-blacklist":
            self.edit_blacklist()
        else:
            self.action_cancel()

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

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _error(self, text: str) -> None:
        self.error_text = text
        self.query_one("#settings-error", Static).update(Text(text))

    def _save(self) -> None:
        raw = self.query_one("#backup-dir", Input).value.strip()
        backup_dir = to_native(raw) if raw else None
        if self.wow_path is not None:
            problem = validate_backup_dir(backup_dir, WowInstall(self.wow_path))
            if problem:
                self._error(problem)
                return
        blacklist = unique_pairs(self.blacklist)
        stored = load_settings(self.tool_cfg)  # keeps the remembered flavor and account choices
        save_settings(self.tool_cfg, replace(stored, backup_dir=backup_dir, blacklist=blacklist),
                      source=self.source)
        if blacklist != stored.blacklist:
            log_event("ace.blacklist_changed", pairs=format_blacklist(blacklist))
        self.dismiss(True)


def blacklist_summary(pairs: list[Pair]) -> str:
    return f"{plural(len(pairs), 'addon')} blacklisted" if pairs else "None"


def _default_backup_hint(wow_path: Path | None) -> str:
    default = resolve_root(ProfileSettings(), wow_path)
    return to_stored(default) if default is not None else ""


class AceProfilesFlow(ToolFlow):
    """The profile manager's workflow. Its settings live in config/ace-profiles.cfg; the WoW folder is shared.
    `unlocked` holds the (casefolded) blacklisted (flavor folder, addon) pairs unlocked this session: it lives on
    the flow, so it survives going back to the flavor picker, and goes when the tool closes."""

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check  # tests inject it; None: the review builds one for its flavors
        self.flavors: list[Flavor] = []
        self.unlocked: set[tuple[str, str]] = set()

    def start(self) -> None:
        self.require_install(self._ready)

    def _ready(self, install: WowInstall, first_run: bool) -> None:
        if not self.tool_cfg.exists:  # first time this tool is opened: ask for its settings once
            self.app.push_screen(ProfileSettingsScreen(self.tool_cfg, self.cfg.wow_path, source="wizard"),
                                 lambda _: self._pick_flavor())
        else:
            self._pick_flavor()

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
        stored = "" if choice == ALL_FLAVORS else choice.folder  # type: ignore[union-attr]
        if self.tool_cfg.get(SECTION, "last_flavor_choice") != stored:
            self.tool_cfg.set(SECTION, "last_flavor_choice", stored, source="picker")
            self.tool_cfg.save_if_exists()
        if choice == ALL_FLAVORS:  # every account of every flavor: no account picker
            self._review(list(self.flavors), "All flavors", None)
            return
        flavor = choice
        assert isinstance(flavor, Flavor)
        if len(flavor.accounts()) > 1:
            self.app.push_screen(AccountScreen(self.cfg, flavor, load_settings(self.tool_cfg).last_account),
                                 lambda choice: self._after_account(flavor, choice))
        else:
            self._review([flavor], flavor.display_name, None)

    def _after_account(self, flavor: Flavor, choice: str | None) -> None:
        if choice is None:
            self._pick_flavor()
            return
        account = choice or None
        if self.tool_cfg.get(SECTION, "last_account", "") != (account or ""):
            self.tool_cfg.set(SECTION, "last_account", account or "", source="picker")
            self.tool_cfg.save_if_exists()
        label = f"{flavor.display_name} · {account}" if account else flavor.display_name
        self._review([flavor], label, account)

    def _review(self, flavors: list[Flavor], label: str, account: str | None) -> None:
        self.app.push_screen(ProfileReviewScreen(self.cfg, self.tool_cfg, flavors, label, account=account,
                                                 unlocked=self.unlocked, wow_check=self._wow_check),
                             self._after_review)

    def _after_review(self, choice: str | None) -> None:
        if choice == "flavors":
            self._pick_flavor()
        elif choice == "tools":
            self.close()
        else:
            self.app.exit()

    def open_settings(self) -> None:
        """`s`: the shared WoW folder first, then this tool's own settings."""
        if isinstance(self.app.screen, ProfileSettingsScreen):
            return
        self.app.open_general_settings(
            lambda _: self.app.push_screen(ProfileSettingsScreen(self.tool_cfg, self.cfg.wow_path,
                                                                 source="settings"),
                                           self._settings_done))

    def _settings_done(self, saved: bool | None) -> None:
        if saved:
            self.app.notify("Settings saved. Press r on the review screen to rescan with them.")


FLOW = AceProfilesFlow
