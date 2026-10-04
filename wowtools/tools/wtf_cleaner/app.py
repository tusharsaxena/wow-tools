"""The WTF Cleaner inside the suite app: (first run: settings) → flavor (or All flavors) → account (one flavor
only) → review → confirm → result."""
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
from wowtools.core.install import Flavor, WowInstall, validate_output_dir
from wowtools.core.paths import to_native, to_stored
from wowtools.tools.wtf_cleaner.report import CRITERION_LABELS
from wowtools.tools.wtf_cleaner.review_screen import ReviewScreen
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria
from wowtools.tools.wtf_cleaner.settings import (SECTION, CleanerSettings, load_settings, resolve_backup_dir,
                                                 save_settings)
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.branding import BrandBar
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, FormScroll, Ka0sCheckbox, NavHint, action_button

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class CleanerSettingsScreen(Screen[bool]):
    DEFAULT_CSS = """
    CleanerSettingsScreen #settings { padding: 0 2; }
    CleanerSettingsScreen .title { color: $accent; text-style: bold; margin: 1 0; }
    CleanerSettingsScreen Label { width: 1fr; height: auto; }
    CleanerSettingsScreen Ka0sCheckbox { margin-bottom: 1; }
    CleanerSettingsScreen #settings-error { color: $error; height: auto; }
    CleanerSettingsScreen .buttons { height: auto; margin-top: 1; }
    CleanerSettingsScreen Button { margin-right: 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, tool_cfg: Config, wow_path: Path | None, *, source: str) -> None:
        super().__init__()
        self.tool_cfg = tool_cfg
        self.wow_path = wow_path
        self.source = source
        self.settings = load_settings(tool_cfg)
        self.error_text = ""

    def compose(self) -> ComposeResult:
        criteria = self.settings.criteria
        yield Header()
        with FormScroll(id="settings", can_focus=False):
            yield Static("WTF Cleaner settings", classes="title")
            yield Label("Propose SavedVariables older than this many days")
            yield Input(str(criteria.max_age_days), type="integer", id="max_age")
            yield Label("Backup folder: holds backup/ (whole WTF folder) and cleaned/ (the files removed). "
                        "Leave empty to use <WoW folder>/wow-tools/wtf-cleaner")
            yield Input(to_stored(self.settings.backup_dir) if self.settings.backup_dir else "",
                        placeholder=_default_backup_hint(self.wow_path), id="backup_dir")
            yield Label("Keep this many WTF backups (and dry-run zips) per flavor; older ones are deleted")
            yield Input(str(self.settings.keep_backups), type="integer", id="keep_backups")
            yield Label("Journals to keep (each real clean writes one; Undo last clean uses the newest)")
            yield Input(str(self.settings.keep_journals), type="integer", id="keep_journals")
            yield Static("Propose SavedVariables when:", classes="title")
            for name in CRITERIA:
                yield Ka0sCheckbox(CRITERION_LABELS[name], getattr(criteria, name), id=f"sw_{name}")
            yield Ka0sCheckbox("Zip the files to clean before deleting them (recommended)",
                               self.settings.backup_before_delete, id="sw_backup")
            yield Static("", id="settings-error")
            with ButtonRow(classes="buttons"):
                yield action_button("Save", "confirm", id="save")
                yield action_button("Cancel", "neutral", id="cancel")
            yield NavHint("↑↓/Tab move · ←→ buttons · Space/Enter tick · Enter/Space press · Esc cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "WTF Cleaner settings"
        self.query_one("#max_age", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _save(self) -> None:
        try:
            days = int(self.query_one("#max_age", Input).value)
        except ValueError:
            days = 0
        if days < 1:
            self.error_text = "Max age must be a whole number of days, at least 1."
            self.query_one("#settings-error", Static).update(Text(self.error_text))
            return
        try:
            keep = int(self.query_one("#keep_backups", Input).value)
        except ValueError:
            keep = 0
        if keep < 1:
            self.error_text = "Keep at least 1 WTF backup."
            self.query_one("#settings-error", Static).update(Text(self.error_text))
            return
        try:
            keep_journals = int(self.query_one("#keep_journals", Input).value)
        except ValueError:
            keep_journals = 0
        if keep_journals < 1:
            self.error_text = "Keep at least 1 journal."
            self.query_one("#settings-error", Static).update(Text(self.error_text))
            return
        criteria = Criteria(**{name: self.query_one(f"#sw_{name}", Ka0sCheckbox).value for name in CRITERIA},
                            max_age_days=days)
        backup_raw = self.query_one("#backup_dir", Input).value.strip()
        backup_dir = to_native(backup_raw) if backup_raw else None
        if self.wow_path is not None:
            problem = validate_output_dir(backup_dir, WowInstall(self.wow_path), what="backup folder")
            if problem:
                self.error_text = problem
                self.query_one("#settings-error", Static).update(Text(self.error_text))
                return
        stored = load_settings(self.tool_cfg)  # keeps the remembered flavor and account choices
        save_settings(self.tool_cfg, replace(stored, criteria=criteria,
                                             backup_before_delete=self.query_one("#sw_backup", Ka0sCheckbox).value,
                                             backup_dir=backup_dir,
                                             keep_backups=keep, keep_journals=keep_journals),
                      source=self.source)
        self.dismiss(True)


def _default_backup_hint(wow_path: Path | None) -> str:
    default = resolve_backup_dir(CleanerSettings(), wow_path)
    return to_stored(default) if default is not None else ""


class WtfCleanerFlow(ToolFlow):
    """The cleaner's own workflow. Its settings live in config/wtf-cleaner.cfg; the WoW folder and the last
    flavor are shared suite settings."""

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None,
                 locker_check: Callable[[], list[str] | None] | None = None) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check
        self._locker_check = locker_check
        self.flavors: list[Flavor] = []

    def start(self) -> None:
        self.require_install(self._ready)

    def _ready(self, install: WowInstall, first_run: bool) -> None:
        if not self.tool_cfg.exists:  # first time this tool is opened: ask for its settings once
            self.app.push_screen(CleanerSettingsScreen(self.tool_cfg, self.cfg.wow_path, source="wizard"),
                                 lambda _: self._pick_flavor())
        else:
            self._pick_flavor()

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
        stored = "" if choice == ALL_FLAVORS else choice.folder  # type: ignore[union-attr]
        if self.tool_cfg.get(SECTION, "last_flavor_choice") != stored:
            self.tool_cfg.set(SECTION, "last_flavor_choice", stored)
            self.tool_cfg.save_if_exists()
        if choice == ALL_FLAVORS:  # every account of every flavor: no account picker
            self._review(list(self.flavors), None)
            return
        flavor = choice
        assert isinstance(flavor, Flavor)
        if len(flavor.accounts()) > 1:
            self.app.push_screen(AccountScreen(self.cfg, flavor, load_settings(self.tool_cfg).last_account),
                                 lambda choice: self._after_account(flavor, choice))
        else:
            self._review(flavor, None)

    def _after_account(self, flavor: Flavor, choice: str | None) -> None:
        if choice is None:
            self._pick_flavor()
            return
        account = choice or None
        if self.tool_cfg.get(SECTION, "last_account", "") != (account or ""):
            self.tool_cfg.set(SECTION, "last_account", account or "")
            self.tool_cfg.save_if_exists()
        self._review(flavor, account)

    def _review(self, flavors: Flavor | list[Flavor], account: str | None) -> None:
        self.app.push_screen(ReviewScreen(self.cfg, self.tool_cfg, flavors, account=account,
                                          wow_check=self._wow_check, locker_check=self._locker_check),
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
        if isinstance(self.app.screen, CleanerSettingsScreen):
            return
        self.app.open_general_settings(
            lambda _: self.app.push_screen(CleanerSettingsScreen(self.tool_cfg, self.cfg.wow_path, source="settings"),
                                           self._settings_done))

    def _settings_done(self, saved: bool | None) -> None:
        if saved:
            self.app.notify("Settings saved. Press r on the review screen to rescan with them.")


FLOW = WtfCleanerFlow
