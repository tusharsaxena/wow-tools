"""ToolFlow: how a tool runs inside the suite app. Each tool has its own screens, workflow and config file; the
steps every tool takes the same way (first-run settings, the `s` key, remembering the flavor and account picked,
picker notes worked out in the background, leaving the review) live here. Spec D9."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar, TypeVar

from textual.screen import Screen

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen
from wowtools.ui.setup_screen import SetupScreen

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp

T = TypeVar("T")
SETTINGS_SAVED = "Settings saved. Press r on the review screen to rescan with them."


class ToolFlow:
    """One open tool. The suite app makes one when the tool is picked from the menu and drops it on close().

    start() checks the WoW folder (require_install), opens the tool's settings the first time the tool is opened
    (SETTINGS_SCREEN, while config/<tool>.cfg does not exist yet), then calls _pick_flavor(), which a subclass
    implements. open_settings() (the `s` key) opens the shared WoW-folder settings, then SETTINGS_SCREEN.
    _after_review() handles the review's "flavors" / "tools" / "quit". SECTION is the tool's config section, where
    remember_flavor() and pick_account() keep the last choices.
    self.cfg is the shared suite config (WoW folder, updates, logging); self.tool_cfg is the tool's own file.
    """

    SECTION = ""
    SETTINGS_SCREEN: ClassVar[type[ToolSettingsScreen] | None] = None
    # Screens besides SETTINGS_SCREEN that `s` never opens a second settings stack over (their Saves would
    # overwrite each other).
    SETTINGS_BLOCKERS: ClassVar[tuple[type[Screen], ...]] = ()

    def __init__(self, app: WowToolsApp, tool_cfg: Config) -> None:
        self.app = app
        self.cfg = app.cfg
        self.tool_cfg = tool_cfg

    # --- opening -------------------------------------------------------------------------------
    def start(self) -> None:
        self.require_install(self._ready)

    def _ready(self, install: WowInstall, first_run: bool) -> None:
        if self.SETTINGS_SCREEN is not None and not self.tool_cfg.exists:
            # first time this tool is opened: ask for its settings once
            self.app.push_screen(self.settings_screen("wizard"), lambda _: self._pick_flavor())
        else:
            self._pick_flavor()

    def _pick_flavor(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """Leave the tool and go back to the tool menu."""
        self.app.close_tool()

    def install(self) -> WowInstall | None:
        return WowInstall.at(self.cfg.wow_path)

    def require_install(self, then: Callable[[WowInstall, bool], None]) -> None:
        """Call then(install, first_run) once a valid WoW folder is configured. If none is, the shared setup screen
        asks for it first (first_run=True); cancelling it closes the tool."""
        install = self.install()
        if install is not None:
            then(install, False)
            return

        def after_setup(ok: bool | None) -> None:
            install = self.install() if ok else None
            if install is None:
                self.close()
            else:
                then(install, True)

        self.app.push_screen(SetupScreen(self.cfg, first_run=True, detect=self.app.detect), after_setup)

    # --- settings --------------------------------------------------------------------------------
    def settings_screen(self, source: str) -> ToolSettingsScreen:
        assert self.SETTINGS_SCREEN is not None
        return self.SETTINGS_SCREEN(self.tool_cfg, self.cfg.wow_path, source=source)

    def open_settings(self) -> None:
        """`s`: the shared WoW folder first, then this tool's own settings (none open already)."""
        if self.SETTINGS_SCREEN is None:
            self.app.open_general_settings()
            return
        blockers = (self.SETTINGS_SCREEN, *self.SETTINGS_BLOCKERS)
        if any(isinstance(screen, blockers) for screen in self.app.screen_stack):
            return
        self.app.open_general_settings(
            lambda _: self.app.push_screen(self.settings_screen("settings"), self._settings_done))

    def _settings_done(self, saved: bool | None) -> None:
        if saved:
            self.app.notify(SETTINGS_SAVED)

    # --- choices -------------------------------------------------------------------------------
    def remember_flavor(self, choice: Flavor | str) -> str:
        """Keep the flavor picked ("" for All flavors) in [SECTION] last_flavor_choice; returns what is stored."""
        stored = "" if choice == ALL_FLAVORS else choice.folder  # type: ignore[union-attr]
        if self.tool_cfg.get(self.SECTION, "last_flavor_choice") != stored:
            self.tool_cfg.set(self.SECTION, "last_flavor_choice", stored, source="picker")
            self.tool_cfg.save_if_exists()
        return stored

    def pick_account(self, flavor: Flavor, then: Callable[[str | None], None]) -> None:
        """A flavor with several accounts: the account picker, highlighting [SECTION] last_account. A choice is
        remembered there and passed to then() (None for all accounts); Esc goes back to the flavor picker. With
        one account (or none) then(None) runs at once."""
        if len(flavor.accounts()) <= 1:
            then(None)
            return
        last = (self.tool_cfg.get(self.SECTION, "last_account") or "").strip() or None

        def chosen(choice: str | None) -> None:
            if choice is None:
                self._pick_flavor()
                return
            account = choice or None
            if self.tool_cfg.get(self.SECTION, "last_account", "") != (account or ""):
                self.tool_cfg.set(self.SECTION, "last_account", account or "", source="picker")
                self.tool_cfg.save_if_exists()
            then(account)

        self.app.push_screen(AccountScreen(self.cfg, flavor, last), chosen)

    def fill_notes(self, picker: FlavorScreen, work: Callable[[], T], ready: Callable[[T], None], *,
                   group: str = "notes") -> None:
        """Work out the picker's notes (counts, backups) in a thread worker of the picker: work() runs there and
        never raises, ready(result) runs on the UI thread, and only while the picker is still on the stack (not
        once a flavor was chosen or Esc pressed). A picker only covered (settings opened with s) still gets them:
        it shows them when it is back."""
        def done(result: T) -> None:
            if picker in self.app.screen_stack:
                ready(result)

        picker.run_worker(lambda: self.app.call_from_thread(done, work()), thread=True, group=group)

    def _after_review(self, choice: str | None) -> None:
        """The review closed: "flavors" opens the flavor picker again, "tools" the tool menu; anything else quits."""
        if choice == "flavors":
            self._pick_flavor()
        elif choice == "tools":
            self.close()
        else:
            self.app.exit()
