"""Ka0sApp: theme, branding, background update check and the `u` update flow for every tool."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Markdown

from wowtools import __version__
from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.updater import ReleaseInfo, UpdateError, apply_update, check_for_update
from wowtools.ui.theme import KA0S_THEME


class UpdateScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    UpdateScreen { align: center middle; }
    UpdateScreen #update-box { width: 76; height: auto; max-height: 85%; border: thick $accent;
                               background: $panel; padding: 1 2; }
    UpdateScreen #update-notes { height: auto; max-height: 20; margin: 1 0; }
    UpdateScreen #update-buttons { height: auto; align-horizontal: right; }
    UpdateScreen Button { margin-left: 2; }
    """
    BINDINGS = [Binding("escape", "later", "Later")]

    def __init__(self, release: ReleaseInfo) -> None:
        super().__init__()
        self.release = release

    def compose(self) -> ComposeResult:
        with Vertical(id="update-box"):
            yield Label(f"Ka0s WoW Tools v{self.release.version} is available (you have v{__version__}).")
            with VerticalScroll(id="update-notes"):
                yield Markdown(self.release.notes or "_No release notes._")
            with Horizontal(id="update-buttons"):
                yield Button("Update now", variant="primary", id="update-yes")
                yield Button("Later", id="update-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "update-yes")

    def action_later(self) -> None:
        self.dismiss(False)


class Ka0sApp(App):
    """Base for every tool's TUI. Subclasses override after_mount(), not on_mount()."""

    TITLE = "Ka0s · WoW Tools"
    BINDINGS = [Binding("u", "update", "Update", show=False)]
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

    def _check_update(self) -> None:
        release = check_for_update(self.cfg)
        if release is not None:
            self.call_from_thread(self._update_found, release)

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
        try:
            message = apply_update(self.release)
        except UpdateError as exc:
            self.notify(str(exc), title="Update failed", severity="error", timeout=15)
            return
        self.exit(message=message)
