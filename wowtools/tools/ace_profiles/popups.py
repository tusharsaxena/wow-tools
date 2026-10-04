"""The Ace3 Profile Manager's popups, styled like ConfirmScreen: the target of a delete or an assignment, a new
profile name (rename and copy), and the quick actions menu."""
from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from wowtools.core.events import log_event
from wowtools.tools.ace_profiles.model import DEFAULT
from wowtools.tools.ace_profiles.ops import valid_name
from wowtools.ui.dialogs import ALERT_STYLE
from wowtools.ui.widgets import ButtonRow, NavHint, action_button

ACTIONS = (
    ("keep_default", "Keep only Default (ticked or highlighted addons)"),
    ("everyone_default", "Everyone → Default (ticked or highlighted addons)"),
    ("tick_leftovers", "Tick all leftover characters"),
    ("discard", "Discard staged changes"),
)


def popup_css(screen: str) -> str:
    """ConfirmScreen's look: a centred box with an accent border, a bold title and right-aligned buttons."""
    return f"""
    {screen} {{ align: center middle; }}
    {screen} .popup-box {{ width: 80; height: auto; max-height: 90%; border: thick $accent; background: $panel;
                          padding: 1 2; }}
    {screen} .title {{ color: $accent; text-style: bold; margin-bottom: 1; }}
    {screen} .popup-body {{ height: auto; max-height: 16; overflow-y: auto; }}
    {screen} Select, {screen} Input {{ margin-top: 1; }}
    {screen} .popup-error {{ height: auto; }}
    {screen} .popup-buttons {{ height: auto; align-horizontal: right; margin-top: 1; }}
    {screen} Button {{ margin-left: 2; }}
    {screen} OptionList {{ height: auto; max-height: 12; }}
    """


class TargetScreen(ModalScreen[str | None]):
    """Choose the profile that characters move to (delete, assign): a list of the profiles there are, or a new
    name typed below it (which wins when not blank). Dismisses with the name, or None."""

    DEFAULT_CSS = popup_css("TargetScreen")
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, body: str, targets: list[str], default: str = DEFAULT) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.targets = list(targets) if default in targets else [default, *targets]
        self.default = default

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text(self.title_text), classes="title")
            yield Static(Text(self.body_text), classes="popup-body")
            yield Select([(Text(name), name) for name in self.targets], value=self.default, allow_blank=False,
                         id="target")
            yield Input(placeholder="or type a new profile name", id="new-name")
            yield Static("", id="target-error", classes="popup-error")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", id="ok")
                yield action_button("Cancel", "neutral", id="cancel")
            yield NavHint("Tab move · Enter choose · Esc cancel")

    def on_mount(self) -> None:
        self.query_one("#target", Select).focus()

    def chosen(self) -> str:
        typed = self.query_one("#new-name", Input).value
        if typed.strip():
            return typed
        value = self.query_one("#target", Select).value
        return value if isinstance(value, str) else self.default

    def _ok(self) -> None:
        name = self.chosen()
        problem = valid_name(name)
        if problem is not None:
            self.query_one("#target-error", Static).update(Text(problem, style=ALERT_STYLE))
            return
        log_event("ui.selection", screen="ace_target", control="target", value=name)
        self.dismiss(name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._ok()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self._ok()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class NameScreen(ModalScreen[str | None]):
    """Type a profile name (rename, copy). `check` returns a problem with the name, or None. Dismisses with the
    name, or None."""

    DEFAULT_CSS = popup_css("NameScreen")
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, body: str, initial: str = "",
                 check: Callable[[str], str | None] = valid_name) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.initial = initial
        self.check = check

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text(self.title_text), classes="title")
            yield Static(Text(self.body_text), classes="popup-body")
            yield Input(self.initial, placeholder="profile name", id="name")
            yield Static("", id="name-error", classes="popup-error")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", id="ok")
                yield action_button("Cancel", "neutral", id="cancel")
            yield NavHint("Enter OK · Tab move · Esc cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def _ok(self) -> None:
        name = self.query_one("#name", Input).value
        problem = self.check(name)
        if problem is not None:
            self.query_one("#name-error", Static).update(Text(problem, style=ALERT_STYLE))
            return
        self.dismiss(name)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one("#name-error", Static).update("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._ok()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self._ok()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ActionsScreen(ModalScreen[str | None]):
    """The quick actions menu (m). Dismisses with the chosen action's id, or None."""

    DEFAULT_CSS = popup_css("ActionsScreen")
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text("Quick actions"), classes="title")
            yield OptionList(*[Option(Text(label), id=action) for action, label in ACTIONS], id="actions-list")
            yield NavHint("↑↓ choose · Enter select · Esc cancel")

    def on_mount(self) -> None:
        self.query_one("#actions-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        log_event("ui.selection", screen="ace_actions", control="action", value=event.option.id)
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
