"""The WTF Cleaner TUI: setup → settings → flavor → review → confirm → result."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall, detect_installs
from wowtools.core.paths import to_native, to_stored
from wowtools.tools.wtf_cleaner.report import CRITERION_LABELS
from wowtools.tools.wtf_cleaner.review_screen import ReviewScreen
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Criteria
from wowtools.tools.wtf_cleaner.settings import (SECTION, CleanerSettings, load_settings, resolve_backup_dir,
                                                 save_settings)
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.base import Ka0sApp
from wowtools.ui.branding import BrandBar
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint


class CleanerSettingsScreen(Screen[bool]):
    DEFAULT_CSS = """
    CleanerSettingsScreen #settings { padding: 0 2; }
    CleanerSettingsScreen .title { color: $accent; text-style: bold; margin: 1 0; }
    CleanerSettingsScreen Ka0sCheckbox { margin-bottom: 1; }
    CleanerSettingsScreen #settings-error { color: $error; height: auto; }
    CleanerSettingsScreen .buttons { height: auto; margin-top: 1; }
    CleanerSettingsScreen Button { margin-right: 2; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, cfg: Config, *, source: str) -> None:
        super().__init__()
        self.cfg = cfg
        self.source = source
        self.settings = load_settings(cfg)
        self.error_text = ""

    def compose(self) -> ComposeResult:
        criteria = self.settings.criteria
        yield Header()
        with VerticalScroll(id="settings", can_focus=False):
            yield Static("WTF Cleaner settings", classes="title")
            yield Label("Propose SavedVariables older than this many days")
            yield Input(str(criteria.max_age_days), type="integer", id="max_age")
            yield Label("Backup folder (leave empty to use <WoW folder>/wow-tools/wtf-cleaner)")
            yield Input(to_stored(self.settings.backup_dir) if self.settings.backup_dir else "",
                        placeholder=_default_backup_hint(self.cfg), id="backup_dir")
            yield Static("Propose SavedVariables when:", classes="title")
            for name in CRITERIA:
                yield Ka0sCheckbox(CRITERION_LABELS[name], getattr(criteria, name), id=f"sw_{name}")
            yield Ka0sCheckbox("Back up files to a timestamped zip before deleting (recommended)",
                               self.settings.backup_before_delete, id="sw_backup")
            yield Static("", id="settings-error")
            with ButtonRow(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")
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
        criteria = Criteria(**{name: self.query_one(f"#sw_{name}", Ka0sCheckbox).value for name in CRITERIA},
                            max_age_days=days)
        backup_raw = self.query_one("#backup_dir", Input).value.strip()
        save_settings(self.cfg, CleanerSettings(criteria, self.query_one("#sw_backup", Ka0sCheckbox).value,
                                                to_native(backup_raw) if backup_raw else None,
                                                load_settings(self.cfg).last_account),
                      source=self.source)
        self.dismiss(True)


def _default_backup_hint(cfg: Config) -> str:
    default = resolve_backup_dir(cfg, CleanerSettings())
    return to_stored(default) if default is not None else ""


class WtfCleanerApp(Ka0sApp):
    SUB_TITLE = "WTF Cleaner"
    BINDINGS = [Binding("s", "settings", "Settings")]

    def __init__(self, cfg: Config, *, check_updates: bool = True,
                 wow_check: Callable[[], list[str] | None] | None = None,
                 locker_check: Callable[[], list[str] | None] | None = None,
                 detect: Callable[[], list[Path]] = detect_installs) -> None:
        super().__init__(cfg, check_updates=check_updates)
        self._wow_check = wow_check
        self._locker_check = locker_check
        self._detect = detect

    def after_mount(self) -> None:
        if self._install() is None:
            self.push_screen(SetupScreen(self.cfg, first_run=True, detect=self._detect), self._after_setup)
        else:
            self._pick_flavor()

    def _install(self) -> WowInstall | None:
        path = self.cfg.wow_path
        if path is None:
            return None
        install = WowInstall(path)
        return install if install.is_valid() else None

    def _after_setup(self, ok: bool | None) -> None:
        if not ok:
            self.exit()
            return
        self.push_screen(CleanerSettingsScreen(self.cfg, source="wizard"), lambda _: self._pick_flavor())

    def _pick_flavor(self) -> None:
        install = self._install()
        if install is None:
            self.push_screen(SetupScreen(self.cfg, first_run=True, detect=self._detect), self._after_setup)
            return
        self.push_screen(FlavorScreen(self.cfg, install), self._after_flavor)

    def _after_flavor(self, flavor: Flavor | None) -> None:
        if flavor is None:
            self.exit()
            return
        if len(flavor.accounts()) > 1:
            self.push_screen(AccountScreen(self.cfg, flavor, load_settings(self.cfg).last_account),
                             lambda choice: self._after_account(flavor, choice))
        else:
            self._review(flavor, None)

    def _after_account(self, flavor: Flavor, choice: str | None) -> None:
        if choice is None:
            self._pick_flavor()
            return
        account = choice or None
        if self.cfg.get(SECTION, "last_account", "") != (account or ""):
            self.cfg.set(SECTION, "last_account", account or "")
            self.cfg.save_if_exists()
        self._review(flavor, account)

    def _review(self, flavor: Flavor, account: str | None) -> None:
        self.push_screen(ReviewScreen(self.cfg, flavor, account=account, wow_check=self._wow_check,
                                     locker_check=self._locker_check),
                         self._after_review)

    def _after_review(self, choice: str | None) -> None:
        if choice == "flavors":
            self._pick_flavor()
        else:
            self.exit()

    def action_settings(self) -> None:
        if self.busy or isinstance(self.screen, (SetupScreen, CleanerSettingsScreen)):
            return
        self.push_screen(SetupScreen(self.cfg, first_run=False, detect=self._detect),
                         lambda _: self.push_screen(CleanerSettingsScreen(self.cfg, source="settings"),
                                                    self._settings_done))

    def _settings_done(self, saved: bool | None) -> None:
        if saved:
            self.notify("Settings saved. Press r on the review screen to rescan with them.")
