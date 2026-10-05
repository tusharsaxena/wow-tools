"""Ka0sApp: theme, branding, background update check and the `u` update flow for every tool."""
from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Label, LoadingIndicator, Markdown

from wowtools import __version__
from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.updater import (ReleaseInfo, UpdateError, apply_update, check_for_update,
                                   persist_check_state)
from wowtools.ui.dialogs import GUARD_BINDING, EnterGuard
from wowtools.ui.theme import KA0S_THEME, action_variables
from wowtools.ui.widgets import ACTION_CSS, NAV_BINDINGS, ButtonRow, NavHint, action_button


class UpdateScreen(EnterGuard, ModalScreen[bool]):
    """Offers a new release. "Update now" is focused at the start, so Enter waits CONFIRM_GUARD (EnterGuard)."""

    DEFAULT_CSS = """
    UpdateScreen { align: center middle; }
    UpdateScreen #update-box { width: 76; height: auto; max-height: 85%; border: thick $accent;
                               background: $panel; padding: 1 2; }
    UpdateScreen #update-notes { height: auto; max-height: 20; margin: 1 0; }
    UpdateScreen #update-buttons { height: auto; align-horizontal: right; }
    UpdateScreen Button { margin-left: 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "later", "Later"), GUARD_BINDING,
                                         *NAV_BINDINGS]

    def __init__(self, release: ReleaseInfo) -> None:
        super().__init__()
        self.release = release

    def compose(self) -> ComposeResult:
        with Vertical(id="update-box"):
            yield Label(f"Ka0s WoW Tools v{self.release.version} is available (you have v{__version__}).")
            with VerticalScroll(id="update-notes"):
                yield Markdown(self.release.notes or "_No release notes._")
            with ButtonRow(id="update-buttons"):
                yield action_button("Update now", "overwrite", id="update-yes")
                yield action_button("Later", "cancel", id="update-no")
            yield NavHint("←→ buttons · ↑↓/Tab move · Enter/Space press · Esc later")

    def on_mount(self) -> None:
        self.start_guard()
        self.query_one("#update-yes", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "update-yes")

    def action_later(self) -> None:
        self.dismiss(False)


class UpdateProgressScreen(ModalScreen[None]):
    """Shown while an accepted update downloads and installs. It has no keys: it closes when the update ends."""
    DEFAULT_CSS = """
    UpdateProgressScreen { align: center middle; }
    UpdateProgressScreen #update-progress-box { width: 64; height: auto; border: thick $accent;
                                                background: $panel; padding: 1 2; }
    UpdateProgressScreen LoadingIndicator { height: 1; margin-top: 1; }
    """

    def __init__(self, version: str) -> None:
        super().__init__()
        self.version = version

    def compose(self) -> ComposeResult:
        with Vertical(id="update-progress-box"):
            yield Label(f"Updating Ka0s WoW Tools to v{self.version}… This can take a minute.")
            yield LoadingIndicator()


class Ka0sApp(App):
    """Base for every tool's TUI. Subclasses override after_mount(), not on_mount()."""

    TITLE = "Ka0s · WoW Tools"
    # The footer leaves out the command palette's key (Ctrl+P still opens it; nothing documents it): at 120x30 the
    # review screens need that room for their own keys. ACTION_CSS colours every button by its action kind.
    CSS = "Footer FooterKey.-command-palette { display: none; }" + ACTION_CSS
    BINDINGS: ClassVar[list[Binding]] = [Binding("u", "update", "Update", show=False)]
    release: reactive[ReleaseInfo | None] = reactive(None)

    def __init__(self, cfg: Config, *, check_updates: bool = True) -> None:
        super().__init__()
        self.cfg = cfg
        self.busy = False
        self._check_updates = check_updates

    def on_mount(self) -> None:
        self.register_theme(KA0S_THEME)
        self.theme = "ka0s"
        if self._check_updates and self.cfg.check_for_updates:
            self.run_worker(self._check_update, thread=True, group="update-check")
        self.after_mount()

    def after_mount(self) -> None:
        """Hook for subclasses."""

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """The `$act-<kind>` button colours exist under every theme (ACTION_CSS is parsed before on_mount switches
        to the Ka0s theme, and the command palette can switch to another)."""
        return {**super().get_theme_variable_defaults(), **action_variables()}

    def _handle_exception(self, error: Exception) -> None:
        """Textual's (private) hook for an unhandled exception in a handler or worker: it sets return_code = 1,
        prints the traceback and exits. Log it first, so a crash reaches logs/ (a test pins that the hook is
        still called). Worker errors arrive wrapped in WorkerFailed; the original is logged."""
        try:
            log_exception("ui", getattr(error, "error", None) or error)
        except Exception:  # noqa: BLE001, S110 - logging must never stop Textual's own handling
            pass
        super()._handle_exception(error)

    async def action_quit(self) -> None:
        """Ctrl+Q (Textual's priority binding). Refused while a clean, organize or undo is running: quitting
        would end the session and release the lock while the worker thread is still changing files."""
        if self.busy:
            log_event("ui.quit_refused")
            self.notify("A run is in progress. Wait for it to finish before quitting.", severity="warning")
            return
        await super().action_quit()

    def _check_update(self) -> None:
        """Worker thread. The config is changed and saved on the UI thread only (see _persist_update_state)."""
        release = check_for_update(self.cfg, persist=lambda values: self.call_from_thread(
            self._persist_update_state, values))
        if release is not None:
            self.call_from_thread(self._update_found, release)

    def _persist_update_state(self, values: dict[str, str]) -> None:
        persist_check_state(self.cfg, values)

    def _update_found(self, release: ReleaseInfo) -> None:
        self.release = release
        self.notify(f"v{release.version} is available. Press u to update.",
                    title="Ka0s WoW Tools update", timeout=10)

    def action_update(self) -> None:
        if self.release is None:
            self.notify("You are on the latest version.")
            return
        if self.busy:
            self.notify("Finish the current task before updating.", severity="warning")
            return
        self.push_screen(UpdateScreen(self.release), self._update_answered)

    def _update_answered(self, accepted: bool | None) -> None:
        log_event("ui.selection", screen="update", control="update",
                  value="accepted" if accepted else "declined")
        if not accepted or self.release is None:
            return
        # The download, git fetch and file copy can take a while: they run in a worker behind a popup, and
        # quitting is refused until they finish (F-005).
        release = self.release
        self.busy = True
        progress = UpdateProgressScreen(release.version)
        self.push_screen(progress)
        self.run_worker(lambda: self._apply_update_worker(release, progress), thread=True, group="update")

    def _apply_update_worker(self, release: ReleaseInfo, progress: UpdateProgressScreen) -> None:
        try:
            with activity.running():
                message = apply_update(release, allow_unverified=self.cfg.allow_unverified_updates)
        except UpdateError as exc:
            self.call_from_thread(self._update_failed, str(exc), progress)
            return
        except Exception as exc:  # noqa: BLE001 - shown and logged, never a crash mid-update
            log_exception("update", exc)
            self.call_from_thread(self._update_failed, f"{type(exc).__name__}: {exc}", progress)
            return
        self.call_from_thread(self._update_done, message)

    def _update_failed(self, message: str, progress: UpdateProgressScreen) -> None:
        self.busy = False
        if self.screen is progress:
            self.pop_screen()
        self.notify(message, title="Update failed", severity="error", timeout=15)

    def _update_done(self, message: str) -> None:
        self.busy = False
        self.exit(message=message)
