"""The Ace3 Profile Manager's popups, styled like ConfirmScreen (ui.dialogs.popup_css): the target of a delete or an
assignment, a new profile name (rename and copy, on the shared text prompt), and the quick actions menu."""
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
from wowtools.tools.ace3_profile_manager.model import DEFAULT
from wowtools.tools.ace3_profile_manager.ops import valid_name
from wowtools.ui.dialogs import ACCENT, TextPromptScreen, popup_css, show_error
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, NavSelect, action_button

# The quick actions, and every review key the footer and the action bar have no room for (each label names its key),
# under two headings: what changes the selection (or what there is to select from), and what changes the selected
# items. The most used actions (Delete, Assign, Only Default, Everyone → Default, Leftovers) are on the action bar.
ACTION_GROUPS = (
    ("Selection", (
        ("tick_leftovers", "Tick all leftover characters"),
        ("select_all", "Tick everything shown (a)"),
        ("select_none", "Untick everything shown (n)"),
        ("filter", "Filter the tree (/)"),
        ("switch_view", "Switch view: by addon / by character (v)"),
    )),
    ("Modification", (
        ("rename", "Rename the highlighted profile (e)"),
        ("copy", "Copy the highlighted profile (k)"),
        ("blacklist", "Blacklist or un-blacklist the highlighted addon in its flavor (b)"),
        ("edit_blacklist", "Edit the blacklist: every flavor and addon, ticked = blacklisted"),
        ("unlock", "Unlock a blacklisted addon for this session, or lock it again (u)"),
        ("discard", "Discard the pending changes (Backspace)"),
    )),
)
ACTIONS = tuple(action for _, actions in ACTION_GROUPS for action in actions)
ACTIONS_ROWS = len(ACTIONS) + 2 * len(ACTION_GROUPS) - 1  # every action, a heading per group, a gap between groups

HEADING_STYLE = ACCENT  # a group heading in the quick actions menu, like a section heading in the left pane


class TargetScreen(ModalScreen[str | None]):
    """Choose the profile that characters move to (delete, assign): a list of the profiles there are (preselected:
    `default` when it is one of them, else the first), or a new name typed below it (which wins when not blank).
    With no profile to offer only the new name is asked for. ↑/↓ move between the list, the name and the buttons
    (Enter or Space opens the list). Dismisses with the name, or None."""

    DEFAULT_CSS = popup_css("TargetScreen")
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, title: str, body: str, targets: list[str], default: str = DEFAULT) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.targets = list(dict.fromkeys(targets))
        self.default = default if default in self.targets else (self.targets[0] if self.targets else "")

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text(self.title_text), classes="title")
            yield Static(Text(self.body_text), classes="popup-body")
            if self.targets:
                yield NavSelect([(Text(name), name) for name in self.targets], value=self.default, allow_blank=False,
                             id="target", compact=True)
            yield Input(placeholder="or type a new profile name" if self.targets else "new profile name",
                        id="new-name", compact=True)
            yield Static("", id="target-error", classes="popup-error")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("↑↓/Tab move · Enter/Space open the list · ←→ buttons")

    def on_mount(self) -> None:
        self.query_one("#target" if self.targets else "#new-name").focus()

    def chosen(self) -> str:
        typed = self.query_one("#new-name", Input).value
        if typed.strip() or not self.targets:
            return typed
        value = self.query_one("#target", Select).value
        return value if isinstance(value, str) else self.default

    def _ok(self) -> None:
        name = self.chosen()
        problem = valid_name(name)
        if problem is not None:
            show_error(self.query_one("#target-error", Static), problem)
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


class NameScreen(TextPromptScreen):
    """Type a profile name (rename, copy): the shared text prompt, checked with valid_name unless `check` (a
    problem with the name, or None) is given. Dismisses with the name, or None."""

    def __init__(self, title: str, body: str, initial: str = "",
                 check: Callable[[str], str | None] = valid_name) -> None:
        super().__init__(title, body, initial, check, placeholder="profile name")


class ActionsScreen(ModalScreen[str | None]):
    """The quick actions menu (m), its actions under their group's heading (ACTION_GROUPS). Dismisses with the
    chosen action's id, or None."""

    DEFAULT_CSS = popup_css("ActionsScreen", list_rows=ACTIONS_ROWS)
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        options: list[Option | None] = []
        for heading, actions in ACTION_GROUPS:
            if options:
                options.append(None)  # a gap between groups
            options.append(Option(Text(heading, style=HEADING_STYLE), disabled=True))  # never highlighted
            options += [Option(Text(f"  {label}"), id=action) for action, label in actions]
        with Vertical(classes="popup-box"):
            yield Static(Text("Quick actions"), classes="title")
            yield OptionList(*options, id="actions-list")
            yield NavHint("↑↓ choose · Enter select · Esc cancel")

    def on_mount(self) -> None:
        actions = self.query_one("#actions-list", OptionList)
        actions.highlighted = 1  # the first action, under the first heading
        actions.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        log_event("ui.selection", screen="ace_actions", control="action", value=event.option.id)
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
