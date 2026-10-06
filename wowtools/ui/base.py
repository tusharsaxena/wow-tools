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
from wowtools.ui.branding import update_key_free, update_notice
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
                yield action_button("Later", "cancel", "escape", id="update-no")
            yield NavHint("←→ buttons · ↑↓/Tab move · Enter/Space press")

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
        self._busy = False
        self._check_updates = check_updates
        self._rechecking = False  # `u` is re-checking GitHub before it offers the update

    @property
    def busy(self) -> bool:
        """A long job runs (a clean, an undo, an update): quitting and settings wait for it."""
        return self._busy

    @busy.setter
    def busy(self, value: bool) -> None:
        # The footer lists `s` only when settings are allowed (WowToolsApp.check_action): refresh it on a change,
        # not only at the next screen change.
        changed = value != self._busy
        self._busy = value
        if changed and self.is_running:
            self.refresh_bindings()

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
        # verify_cached: a cached version is confirmed with GitHub before it is announced (one request, only
        # while an update is pending), so a deleted release stops showing at once (D16).
        release = check_for_update(self.cfg, verify_cached=True, persist=lambda values: self.call_from_thread(
            self._persist_update_state, values))
        if release is not None:
            self.call_from_thread(self._update_found, release)

    def _persist_update_state(self, values: dict[str, str]) -> None:
        # A config file briefly locked (antivirus, an editor) or read-only must not end the app from a check.
        try:
            persist_check_state(self.cfg, values)
        except OSError as exc:
            log_exception("update", exc)

    def _update_found(self, release: ReleaseInfo) -> None:
        self.release = release
        self.notify(f"Ka0s WoW Tools {update_notice(release.version, update_key_free(self.screen))}.",
                    title="Ka0s WoW Tools update", timeout=10)

    def action_update(self) -> None:
        if self.release is None:
            self.notify("You are on the latest version.")
            return
        if self.busy:
            self.notify("Finish the current task before updating.", severity="warning")
            return
        if self._rechecking:
            return
        # The notice may come from the throttled check's cache, and a release can be deleted after it was seen:
        # ask GitHub again before offering it, so `u` never tries to install a release that is gone (D16).
        self._rechecking = True
        self.run_worker(self._recheck_update, thread=True, group="update-recheck")

    def _recheck_update(self) -> None:
        """Worker thread: a forced update check. The config is changed and saved on the UI thread only."""
        try:
            release = check_for_update(self.cfg, force=True, raise_errors=True, persist=lambda values:
                                       self.call_from_thread(self._persist_update_state, values))
        except UpdateError as exc:
            self.call_from_thread(self._recheck_failed, str(exc))
            return
        self.call_from_thread(self._recheck_done, release)

    def _recheck_failed(self, message: str) -> None:
        self._rechecking = False
        self.notify(f"Could not check for updates: {message}", title="Update", severity="error", timeout=10)

    def _recheck_done(self, release: ReleaseInfo | None) -> None:
        self._rechecking = False
        if release is None:
            # The release that was offered no longer exists (or is not newer): drop the notice everywhere.
            self.release = None
            self.notify("No update available. You are on the latest version.", title="Update")
            return
        self.release = release
        if self.busy:
            self.notify("Finish the current task before updating.", severity="warning")
            return
        self.push_screen(UpdateScreen(release), self._update_answered)

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
