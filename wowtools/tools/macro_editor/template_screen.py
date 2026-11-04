"""The template picker (config tools spec ME11), opened from the edit screen with Ctrl+T: the curated templates
(templates.load_templates) in a list, the highlighted one's body and source, and a box per placeholder (a spell
name, one line each). Insert dismisses with the filled body (templates.fill_template), or says what is missing;
Cancel and Esc dismiss with None."""
from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.tools.macro_editor.templates import MacroTemplate, fill_template
from wowtools.ui.dialogs import popup_css, show_error
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

__all__ = ["TemplateScreen"]

LIST_ROWS = 6


class TemplateScreen(ModalScreen[str | None]):
    DEFAULT_CSS = popup_css("TemplateScreen", list_rows=LIST_ROWS) + """
    TemplateScreen #template-preview { height: auto; margin: 1 0; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"),
                                         Binding("ctrl+s", "insert", "Insert", show=False), *NAV_BINDINGS]

    def __init__(self, templates: Sequence[MacroTemplate]) -> None:
        super().__init__()
        self.templates = list(templates)
        self.boxes = max((len(t.placeholders) for t in self.templates), default=0)

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text("Insert a template"), classes="title")
            yield OptionList(*[Option(t.title) for t in self.templates], id="templates", compact=True)
            yield Static("", id="template-preview")
            for number in range(1, self.boxes + 1):
                yield Input("", id=f"value-{number}", compact=True)
            yield Static("", id="template-error", classes="popup-error")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("Insert", "create", "ctrl+s", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("↑↓ template · Tab move · Enter in a box inserts")

    def on_mount(self) -> None:
        listed = self.query_one("#templates", OptionList)
        if self.templates:
            listed.highlighted = 0
        self._show()
        listed.focus()

    @property
    def template(self) -> MacroTemplate | None:
        index = self.query_one("#templates", OptionList).highlighted
        return self.templates[index] if index is not None and self.templates else None

    def _show(self) -> None:
        template = self.template
        preview = self.query_one("#template-preview", Static)
        if template is None:
            preview.update(Text("No templates to show.", style="dim"))
        else:
            preview.update(Text.assemble((template.body, "bold"), "\n", (f"Source: {template.source}", "dim")))
        holders = template.placeholders if template is not None else ()
        for number in range(1, self.boxes + 1):
            box = self.query_one(f"#value-{number}", Input)
            box.display = number <= len(holders)
            box.placeholder = holders[number - 1] if number <= len(holders) else ""
        show_error(self.query_one("#template-error", Static), None)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self._show()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.focus_next()  # Enter on a template: on to its first box

    def on_input_changed(self, event: Input.Changed) -> None:
        show_error(self.query_one("#template-error", Static), None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_insert()

    def action_insert(self) -> None:
        template = self.template
        if template is None:
            return
        values = {name: self.query_one(f"#value-{number}", Input).value
                  for number, name in enumerate(template.placeholders, 1)}
        try:
            text = fill_template(template, values)
        except ValueError as exc:
            show_error(self.query_one("#template-error", Static), str(exc)[:1].upper() + str(exc)[1:] + ".")
            return
        self.dismiss(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self.action_insert()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
