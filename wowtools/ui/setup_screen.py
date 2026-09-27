"""First-run and general settings: the WoW folder ([general] in wow-tools.cfg)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event
from wowtools.core.install import WowInstall, detect_installs
from wowtools.core.paths import to_native, to_stored
from wowtools.ui.branding import Banner, BrandBar
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint


class SetupScreen(Screen[bool]):
    DEFAULT_CSS = """
    SetupScreen #setup { padding: 0 2; }
    SetupScreen .title { color: $accent; text-style: bold; margin: 1 0; }
    SetupScreen .hint { color: $text-muted; margin-bottom: 1; }
    SetupScreen #setup-error { color: $error; height: auto; }
    SetupScreen .buttons { height: auto; margin-top: 1; }
    SetupScreen Button { margin-right: 2; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, cfg: Config, *, first_run: bool,
                 detect: Callable[[], list[Path]] = detect_installs) -> None:
        super().__init__()
        self.cfg = cfg
        self.first_run = first_run
        self.error_text = ""
        self._detected = [] if cfg.wow_path else detect()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="setup", can_focus=False):
            yield Banner()
            yield Static("First-time setup" if self.first_run else "General settings", classes="title")
            yield Label("World of Warcraft folder (the one that contains _retail_, _classic_ and so on)")
            yield Input(value=self._initial_wow_path(), placeholder=r"C:\Program Files (x86)\World of Warcraft",
                        id="wow_path")
            yield Static(Text(self._detected_hint()), classes="hint")
            yield Static("", id="setup-error")
            with ButtonRow(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")
            yield NavHint("↑↓/Tab move · ←→ buttons · Enter save/press · Esc cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Setup"
        self.query_one("#wow_path", Input).focus()

    def _initial_wow_path(self) -> str:
        stored = self.cfg.get(GENERAL, "wow_path")
        if stored:
            return stored
        return to_stored(self._detected[0]) if self._detected else ""

    def _detected_hint(self) -> str:
        if self._detected:
            return "Found: " + "; ".join(to_stored(p) for p in self._detected)
        return "" if self.cfg.wow_path else "No installation was found automatically. Type or paste the folder."

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._save()

    def action_cancel(self) -> None:
        log_event("ui.selection", screen="setup", control="cancel", value=True)
        self.dismiss(False)

    def _save(self) -> None:
        raw = self.query_one("#wow_path", Input).value.strip()
        wow = to_native(raw) if raw else None
        if wow is None or not WowInstall(wow).is_valid():
            self.error_text = ("No WoW flavor folders (_retail_, _classic_ ...) were found there. "
                               "Choose the World of Warcraft folder itself.")
            self.query_one("#setup-error", Static).update(Text(self.error_text))
            return
        source = "wizard" if self.first_run else "settings"
        self.cfg.set_path(GENERAL, "wow_path", wow, source=source)
        self.cfg.save()
        self.dismiss(True)
