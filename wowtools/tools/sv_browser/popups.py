"""The Saved Variables Browser's popups (spec §5), styled like ConfirmScreen (ui.dialogs.popup_css): the USE AT YOUR
OWN RISK warning (D2), a warning ChoiceScreen the flow shows before the review scans; Edit value (D5, D10: a type
select, then a text field or a checkbox), Rename key (the shared text prompt) and Delete key (a destructive
confirm, with D5's array-shift warning). The Search popup comes with plan T3.3. The popups check what is typed with
the checks they are given (the review passes the staging's own, ops.Staging.*_problem) and dismiss with the value,
the key text or the answer; the review stages it."""
from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from wowtools.core.text import plural
from wowtools.tools.sv_browser.ops import SHIFT_WARNING, parse_key
from wowtools.tools.sv_browser.report import DISCLAIMER
from wowtools.tools.sv_browser.search import (REPLACE_BOOLEAN, REPLACE_NUMBER, REPLACE_STRING, Replacement,
                                              parse_replacement)
from wowtools.ui.dialogs import ChoiceScreen, ConfirmScreen, TextPromptScreen, popup_css, show_error
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, NavSelect, action_button

ACCEPT, BACK = "accept", "back"
DISCLAIMER_TITLE = "USE AT YOUR OWN RISK"
# The warning body: the spec's D2 text after its first words (the title says them), then where it is said again.
DISCLAIMER_TEXT = (DISCLAIMER.removeprefix(f"{DISCLAIMER_TITLE}. ")
                   + "\n\nClose WoW before you apply anything: it rewrites every SavedVariables file when you log out."
                   " Every Apply and Undo asks again.")

VALUE_TYPES = ((REPLACE_STRING, "String"), (REPLACE_NUMBER, "Number"), (REPLACE_BOOLEAN, "Boolean"))
NOT_TYPABLE = "It has line breaks or other characters that can't be typed here: type the whole new value."
KEY_HELP = ("Type the new key. [5], [2.5], [true] or [false] make a number or boolean key; anything else is a "
            'string key (["[5]"] for the text [5]).')


class DisclaimerScreen(ChoiceScreen):
    """D2: shown each time the tool is opened from the menu, after the flavor pick and before the first scan. "I
    understand" (focused) goes on to the review; Back (or Esc, which dismisses with None) goes back to the flavor
    picker."""

    def __init__(self) -> None:
        super().__init__(DISCLAIMER_TITLE, DISCLAIMER_TEXT,
                         [(BACK, "Back", "cancel", "escape"), (ACCEPT, "I understand", "confirm")],
                         default=ACCEPT, escape=True)


class EditValueScreen(ModalScreen[Replacement | None]):
    """Edit value (D5, D10): `where` names the key, `current` its value as the tree shows it. The type select
    (string, number, boolean; it starts on `kind`) shows a text field (#value-text, starting with `text`) for a
    string or a number, or a checkbox (#value-bool, ticked = true, starting as `flag`) for a boolean. OK reads the
    value (a number must read back in Lua as itself: search.parse_replacement) and asks `check` (the staging's
    refusal, or None); a problem shows under the fields until they change. Dismisses with the value, or None."""

    DEFAULT_CSS = popup_css("EditValueScreen", list_rows=len(VALUE_TYPES)) + """
    EditValueScreen Ka0sCheckbox { margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, where: str, current: str, kind: str = REPLACE_STRING, text: str = "", flag: bool = False,
                 check: Callable[[Replacement], str | None] | None = None, note: str = "") -> None:
        super().__init__()
        self.where = where
        self.current = current
        self.kind = kind
        self.text = text
        self.flag = flag
        self.check = check or (lambda value: None)
        self.note = note

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text("Edit value"), classes="title")
            body = f"{self.where}\nNow: {self.current}"
            yield Static(Text(f"{body}\n{self.note}" if self.note else body), classes="popup-body")
            yield NavSelect([(label, kind) for kind, label in VALUE_TYPES], value=self.kind, allow_blank=False,
                            id="value-type", compact=True)
            yield Input(self.text, placeholder="new value", id="value-text", compact=True)
            yield Ka0sCheckbox("true", self.flag, id="value-bool", compact=True)
            yield Static("", id="value-error", classes="popup-error")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("Enter OK · ↑↓/Tab move · Enter/Space open the list · ←→ buttons")

    def on_mount(self) -> None:
        self._show_fields()
        self.query_one("#value-bool" if self.kind == REPLACE_BOOLEAN else "#value-text").focus()

    def chosen_kind(self) -> str:
        value = self.query_one("#value-type", Select).value
        return value if isinstance(value, str) else REPLACE_STRING

    def _show_fields(self) -> None:
        boolean = self.chosen_kind() == REPLACE_BOOLEAN
        self.query_one("#value-text", Input).display = not boolean
        self.query_one("#value-bool", Ka0sCheckbox).display = boolean

    def _error(self, problem: str | None) -> None:
        show_error(self.query_one("#value-error", Static), problem)

    def value(self) -> Replacement:
        """The value entered; ValueError (its message for the user) when it is not one."""
        kind = self.chosen_kind()
        if kind == REPLACE_BOOLEAN:
            return self.query_one("#value-bool", Ka0sCheckbox).value
        return parse_replacement(kind, self.query_one("#value-text", Input).value)

    def _ok(self) -> None:
        try:
            value = self.value()
        except ValueError as exc:
            self._error(str(exc))
            return
        problem = self.check(value)
        if problem is not None:
            self._error(problem)
            return
        self.dismiss(value)

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        self._show_fields()
        self._error(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._error(None)

    def on_checkbox_changed(self, event: Ka0sCheckbox.Changed) -> None:
        event.stop()
        self._error(None)

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


def key_check(check: Callable[[object], str | None]) -> Callable[[str], str | None]:
    """The rename prompt's check: the typed text read as a key (ops.parse_key), then `check` (the staging's
    refusal: an empty key, one the table already holds, ...)."""
    def problem(text: str) -> str | None:
        try:
            key = parse_key(text)
        except ValueError as exc:
            return str(exc)
        return check(key)
    return problem


class RenameKeyScreen(TextPromptScreen):
    """Rename key (D5): the shared text prompt, starting with the key as ops.key_input writes it and checked with
    key_check(check). Dismisses with the text (ops.parse_key reads the key), or None."""

    def __init__(self, where: str, initial: str, check: Callable[[object], str | None]) -> None:
        super().__init__("Rename key", f"{where}\n{KEY_HELP}", initial, key_check(check), placeholder="new key")


def delete_confirm(where: str, *, count: int | None = None, table: bool = False, positional: bool = False,
                   staged_inside: int = 0) -> ConfirmScreen:
    """Delete key (D5): a destructive confirm naming the key. A table says how many entries go with it (`count`,
    None when not read yet); an array entry carries the shift warning; edits staged inside it are dropped."""
    lines = [f"{where} is deleted when you apply."]
    if table:
        lines.append("It is a table: " + ("everything in it goes with it." if count is None else
                                          f"its {plural(count, 'entry', 'entries')} {'goes' if count == 1 else 'go'} with it."))
    if staged_inside:
        lines.append(f"The {plural(staged_inside, 'edit')} staged inside it {'is' if staged_inside == 1 else 'are'} "
                     "dropped.")
    alerts = (SHIFT_WARNING,) if positional else ()
    return ConfirmScreen("Delete key?", "\n".join(lines), alerts, kind="destructive")
