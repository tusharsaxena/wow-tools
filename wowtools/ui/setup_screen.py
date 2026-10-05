"""First-run and general settings: the WoW folder and retention, shared by every tool ([general] in wow-tools.cfg)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import WowInstall, detect_installs
from wowtools.core.paths import to_native, to_stored
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import FORM_WIDTH
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, FormScroll, NavHint, action_button


class SetupScreen(Screen[bool]):
    """The [general] settings form, laid out as every tool's settings form (ui/dialogs.settings_css): a readable
    width (FORM_WIDTH), centred, and no banner, so the whole form, Save included, shows at 120x30."""
    DEFAULT_CSS = f"""
    SetupScreen {{ align-horizontal: center; }}
    SetupScreen #setup {{ {FORM_WIDTH} padding: 0 2; }}
    SetupScreen .title {{ color: $accent; text-style: bold; margin: 1 0; }}
    SetupScreen Label {{ width: 1fr; height: auto; }}
    SetupScreen .hint {{ color: $text-muted; margin-bottom: 1; }}
    SetupScreen #setup-error {{ color: $error; height: auto; }}
    SetupScreen .buttons {{ height: auto; margin-top: 1; }}
    SetupScreen Button {{ margin-right: 2; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, cfg: Config, *, first_run: bool,
                 detect: Callable[[], list[Path]] = detect_installs) -> None:
        super().__init__()
        self.cfg = cfg
        self.first_run = first_run
        self.error_text = ""
        self._detect = detect
        self._detected: list[Path] = []
        # Looking for installs checks every drive letter: it runs in a worker once the screen is up (F-005).
        self._detecting = not cfg.wow_path

    def compose(self) -> ComposeResult:
        yield Header()
        with FormScroll(id="setup", can_focus=False):
            yield Static("First-time setup" if self.first_run else "General settings", classes="title")
            yield Label("World of Warcraft folder (the one that contains _retail_, _classic_ and so on)")
            yield Input(value=self._initial_wow_path(), placeholder=r"C:\Program Files (x86)\World of Warcraft",
                        id="wow_path")
            yield Static(Text(self._detected_hint()), classes="hint", id="setup-hint")
            yield Label("Backups to keep per flavor (0 = keep all; applies to every tool)")
            yield Input(str(self.cfg.keep_backups), type="integer", id="keep-backups")
            yield Label("Journals to keep per tool (Undo uses the newest)")
            yield Input(str(self.cfg.keep_journals), type="integer", id="keep-journals")
            yield Static("", id="setup-error")
            with ButtonRow(classes="buttons"):
                yield action_button("Save", "confirm", id="save")
                yield action_button("Cancel", "neutral", id="cancel")
            yield NavHint("↑↓/Tab move · ←→ buttons · Enter save/press · Esc cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Setup"
        self.query_one("#wow_path", Input).focus()
        self.query_one("#setup", FormScroll).open_at_top()
        if self._detecting:
            self.run_worker(self._detect_worker, thread=True, group="detect")

    def _detect_worker(self) -> None:
        try:
            found = list(self._detect())
        except Exception as exc:  # noqa: BLE001 - detection is a convenience: the folder can still be typed
            log_exception("setup.detect", exc)
            found = []
        self.app.call_from_thread(self._detected_ready, found)

    def _detected_ready(self, found: list[Path]) -> None:
        self._detecting = False
        self._detected = found
        if not self.is_attached:
            return
        self.query_one("#setup-hint", Static).update(Text(self._detected_hint()))
        path_input = self.query_one("#wow_path", Input)
        if found and not path_input.value.strip():  # never replace what the user has started typing
            path_input.value = to_stored(found[0])

    def _initial_wow_path(self) -> str:
        stored = self.cfg.get(GENERAL, "wow_path")
        if stored:
            return stored
        return to_stored(self._detected[0]) if self._detected else ""

    def _detected_hint(self) -> str:
        if self._detecting:
            return "Looking for World of Warcraft installations…"
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

    def _error(self, text: str) -> None:
        self.error_text = text
        self.query_one("#setup-error", Static).update(Text(text))

    def _count(self, widget_id: str, least: int) -> int | None:
        try:
            value = int(self.query_one(f"#{widget_id}", Input).value.strip())
        except ValueError:
            return None
        return value if value >= least else None

    def _save(self) -> None:
        raw = self.query_one("#wow_path", Input).value.strip()
        wow = to_native(raw) if raw else None
        if wow is None or not WowInstall(wow).is_valid():
            self._error("No WoW flavor folders (_retail_, _classic_ ...) were found there. "
                        "Choose the World of Warcraft folder itself.")
            return
        keep_backups = self._count("keep-backups", 0)
        if keep_backups is None:
            self._error("Backups to keep must be a whole number: 0 (keep all) or more.")
            return
        keep_journals = self._count("keep-journals", 1)
        if keep_journals is None:
            self._error("Journals to keep must be a whole number, at least 1.")
            return
        source = "wizard" if self.first_run else "settings"
        self.cfg.set_path(GENERAL, "wow_path", wow, source=source)
        self.cfg.set(GENERAL, "keep_backups", keep_backups, source=source)
        self.cfg.set(GENERAL, "keep_journals", keep_journals, source=source)
        self.cfg.save()
        self.dismiss(True)
