"""The base of every tool's settings screen: one form (a title, the tool's own fields, an error line, Save and
Cancel, the hint), Esc to cancel, and the shared folder-field handling. Spec D9.

A tool screen sets FORM_TITLE, FIRST_FIELD (the id focused at the start) and TICKS (the form has checkboxes, so the
hint names Space/Enter tick), and implements load(), fields() and save()."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Header, Input, Static

from wowtools.core.config import Config
from wowtools.core.install import WowInstall
from wowtools.core.paths import to_native, to_stored
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import settings_css
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, FormScroll, NavHint, action_button


def settings_hint(ticks: bool) -> str:
    """A settings form's hint; `ticks` when it has checkboxes."""
    return "↑↓/Tab move · ←→ buttons · " + ("Space/Enter tick · " if ticks else "") + "Enter/Space press · Esc cancel"


def folder_hint(path: Path | None) -> str:
    """A folder field's placeholder: the folder used when it is left empty, as stored ("" when there is none)."""
    return to_stored(path) if path is not None else ""


class ToolSettingsScreen(Screen[bool]):
    """A tool's settings form. Dismisses with True once saved, False on Cancel or Esc.

    `wow_path` is the shared WoW folder (None before one is set), `source` the config.changed source ("wizard" the
    first time the tool opens, "settings" from the s key). self.wow_install is that folder as an install when it
    is a valid one, else None. self.settings is what load() read when the screen opened."""

    DEFAULT_CSS = settings_css("ToolSettingsScreen")
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]
    FORM_TITLE = ""
    FIRST_FIELD = ""
    TICKS = False

    def __init__(self, tool_cfg: Config, wow_path: Path | None, *, source: str) -> None:
        super().__init__()
        self.tool_cfg = tool_cfg
        self.wow_path = wow_path
        self.wow_install = WowInstall.at(wow_path)  # read once: the form never touches the disk while typing
        self.source = source
        self.settings: Any = self.load(tool_cfg)
        self.error_text = ""

    # --- what a tool supplies --------------------------------------------------------------------
    def load(self, tool_cfg: Config) -> Any:
        """The tool's settings as stored."""
        raise NotImplementedError

    def fields(self) -> Iterable[Widget]:
        """The form's own labels, inputs and checkboxes, between the title and the error line."""
        raise NotImplementedError

    def save(self) -> bool:
        """Check and write the form; False (after _error) keeps the screen open."""
        raise NotImplementedError

    # --- shared --------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with FormScroll(id="settings", can_focus=False):
            yield Static(self.FORM_TITLE, classes="title")
            yield from self.fields()
            yield Static("", id="settings-error")
            with ButtonRow(classes="buttons"):
                yield action_button("Save", "confirm", id="save")
                yield action_button("Cancel", "cancel", id="cancel")
            yield NavHint(settings_hint(self.TICKS))
        yield BottomBar()

    def on_mount(self) -> None:  # Textual also runs a subclass's own on_mount: no super() call there
        self.sub_title = self.FORM_TITLE
        self.query_one(f"#{self.FIRST_FIELD}", Input).focus()
        self.query_one("#settings", FormScroll).open_at_top()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Textual calls this handler as well as a subclass's own: a form's other buttons are the subclass's.
        if event.button.id == "save":
            self._save()
        elif event.button.id == "cancel":
            self.action_cancel()

    def _save(self) -> None:
        if self.save():
            self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _error(self, text: str) -> None:
        self.error_text = text
        self.query_one("#settings-error", Static).update(Text(text))

    @staticmethod
    def folder_input(value: Path | None, *, placeholder: str, id: str) -> Input:
        """A folder field: the stored form of `value`, empty for "the default"."""
        return Input(to_stored(value) if value else "", placeholder=placeholder, id=id)

    def folder_value(self, field_id: str) -> Path | None:
        """A folder field's value as a native path, None when it is left empty."""
        raw = self.query_one(f"#{field_id}", Input).value.strip()
        return to_native(raw) if raw else None
