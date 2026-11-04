"""The Macro Editor's edit screen (config tools spec ME8-ME11), for New and Edit: the macro's name (cut at 16 as typed,
V4), its icon (a file id or a texture name; empty is the "?" icon), which set it is in (account or character), the
body with a live `n / 255` meter (Save is off above 255) and, beside it, a help panel that explains the token under
the cursor from the flavor's macro reference and reads a whole [...] block out in plain English (explain.describe_at).

Typing a `/command`, a `#directive`, a conditional after `[` or `,`, a unit after `@` or an argument after `:` lists
suggestions under the body (syntax.suggestions): ↑/↓ choose, Tab or Enter take one, Esc hides the list. When the
word typed is already complete (`/targetenemy`, which `/targetenemyplayer` also starts with), Enter is a new line
unless ↑/↓ chose a suggestion; Tab still takes one. A suggestion taken closes the list until the next keystroke. Ctrl+B opens
the conditional builder on the block under the cursor (OK rewrites it, or inserts a new block at the cursor), Ctrl+O
the optimizer (its rewrites and their reasons; OK takes them), Ctrl+T a template (filled in, inserted as whole
lines), F1 the full reference. `check` returns why the macro can't be staged, or None. Dismisses with (name, icon,
body), or None (Cancel, Esc). Nothing is written here: the review stages what it returns."""
from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Header, Input, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from wowtools.core.kb import load_macro_reference
from wowtools.core.macrofile import BODY_LIMIT, ICON_DEFAULT, NAME_LIMIT
from wowtools.tools.macro_editor.builder import block_at, read_block, write_block
from wowtools.tools.macro_editor.builder_screen import BuilderScreen
from wowtools.tools.macro_editor.explain import describe_at, unknown_terms
from wowtools.tools.macro_editor.ops import body_length
from wowtools.tools.macro_editor.optimize_screen import OptimizeScreen
from wowtools.tools.macro_editor.optimizer import optimize
from wowtools.tools.macro_editor.reference_screen import ReferenceScreen
from wowtools.tools.macro_editor.syntax import completion_start, suggestions
from wowtools.tools.macro_editor.template_screen import TemplateScreen
from wowtools.tools.macro_editor.templates import load_templates
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import ALERT_STYLE, show_error
from wowtools.ui.widgets import NavHint, WrapButtonRow, action_button

__all__ = ["HELP_WIDTH", "MAX_SUGGESTIONS", "MacroEditScreen", "MacroTextArea"]

HELP_WIDTH = 40          # the help panel beside the body; the body takes the rest
MAX_SUGGESTIONS = 6      # rows the suggestion list shows before it scrolls
EDIT_HINT = "Tab move · ↑↓ then Tab/Enter take a suggestion"
NOTHING_HERE = "Move the cursor onto a command, a [...] block, a conditional or a @unit to read about it."


class MacroTextArea(TextArea):
    """The body. While the screen lists suggestions, Tab and Enter take the highlighted one and ↑/↓ choose it;
    otherwise the keys do what they always do (Enter a new line, Tab the next control). Enter after a word that is
    already complete is a new line, unless ↑/↓ chose a suggestion."""

    async def _on_key(self, event: events.Key) -> None:
        screen = self.screen
        if isinstance(screen, MacroEditScreen) and screen.suggesting and event.key in ("tab", "enter"):
            if event.key == "enter" and not screen.enter_takes_suggestion():
                screen.hide_suggestions()  # the word is complete: Enter is the new line the user meant
            else:
                event.stop()
                event.prevent_default()
                screen.take_suggestion()
                return
        await super()._on_key(event)

    def action_cursor_up(self, select: bool = False) -> None:
        screen = self.screen
        if not select and isinstance(screen, MacroEditScreen) and screen.suggesting:
            screen.move_suggestion(-1)
            return
        super().action_cursor_up(select)

    def action_cursor_down(self, select: bool = False) -> None:
        screen = self.screen
        if not select and isinstance(screen, MacroEditScreen) and screen.suggesting:
            screen.move_suggestion(1)
            return
        super().action_cursor_down(select)


class MacroEditScreen(Screen[tuple[str, str, str] | None]):
    DEFAULT_CSS = f"""
    MacroEditScreen #edit-body {{ height: 1fr; }}
    MacroEditScreen #editor {{ width: 1fr; padding: 0 1; }}
    MacroEditScreen #macro-where {{ color: $accent; text-style: bold; height: auto; }}
    MacroEditScreen #macro-scope {{ color: $text-muted; height: auto; }}
    MacroEditScreen Input {{ margin: 0; }}
    MacroEditScreen #macro-body {{ height: 1fr; min-height: 3; margin-top: 1; }}
    MacroEditScreen #macro-meter {{ height: 1; }}
    MacroEditScreen #macro-error {{ height: auto; }}
    MacroEditScreen #suggestions {{ height: auto; max-height: {MAX_SUGGESTIONS}; }}
    MacroEditScreen #help {{ width: {HELP_WIDTH}; max-width: 45%; padding: 0 1; border-left: solid $primary; }}
    MacroEditScreen #help-title {{ color: $accent; text-style: bold; }}
    MacroEditScreen #edit-buttons {{ margin: 1 1 0 1; }}
    MacroEditScreen NavHint {{ padding: 0 1; margin-top: 0; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "save", "Save", show=False),
        Binding("ctrl+b", "builder", "Builder", show=False),
        Binding("ctrl+o", "optimize", "Optimize", show=False),
        Binding("ctrl+t", "template", "Template", show=False),
        Binding("f1", "reference", "Reference", show=False),
    ]
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {"ok": "save", "builder": "builder", "optimize": "optimize",
                                                "template": "template", "reference": "reference",
                                                "cancel": "cancel"}

    def __init__(self, title: str, where: str, scope: str, *, flavor: str, name: str = "",
                 icon: str = ICON_DEFAULT, body: str = "",
                 check: Callable[[str, str, str], str | None] | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.where = where
        self.scope = scope
        self.flavor = flavor
        self.macro_name, self.macro_icon, self.macro_body = name, icon, body
        self.check = check or (lambda name, icon, body: None)
        self.ref = load_macro_reference(flavor)
        self.options: list[tuple[str, str]] = []  # the suggestions listed
        self._seen_text = body                    # the text the suggestions were made for
        self._complete = False                    # the word typed is itself a reference entry
        self._moved = False                       # ↑/↓ moved the highlight since the list was made
        self._taken: str | None = None            # the body a taken suggestion makes: its Changed lists nothing
        self._shown_body = body                   # the body as the text box holds it (set on mount)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="edit-body"):
            with Vertical(id="editor"):
                yield Static(Text(f"{self.title_text} · {self.where}"), id="macro-where")
                yield Static(Text(self.scope), id="macro-scope")
                yield Input(self.macro_name, placeholder=f"name (up to {NAME_LIMIT} characters)",
                            max_length=max(NAME_LIMIT, len(self.macro_name)), id="macro-name", compact=True)
                yield Input(self.macro_icon, placeholder=f"icon: a file id or a texture name ({ICON_DEFAULT} is ?)",
                            id="macro-icon", compact=True)
                yield MacroTextArea(self.macro_body, id="macro-body", soft_wrap=True, compact=True)
                yield Static("", id="macro-meter")
                yield OptionList(id="suggestions", compact=True)
                yield Static("", id="macro-error")
            with VerticalScroll(id="help"):
                yield Static("Help", id="help-title")
                yield Static("", id="help-text")
        with WrapButtonRow(id="edit-buttons"):
            yield action_button("Save", "confirm", "ctrl+s", id="ok", compact=True)
            yield action_button("Builder…", "overwrite", "ctrl+b", id="builder", compact=True)
            yield action_button("Optimize…", "overwrite", "ctrl+o", id="optimize", compact=True)
            yield action_button("Template…", "create", "ctrl+t", id="template", compact=True)
            yield action_button("Reference", "navigate", "f1", id="reference", compact=True)
            yield action_button("Cancel", "cancel", "escape", id="cancel", compact=True)
        yield NavHint(EDIT_HINT)
        yield BottomBar()

    def on_mount(self) -> None:
        self._shown_body = self.area.text  # the body as the text box holds it, before any edit
        self.sub_title = f"Macro Editor · {self.title_text.lower()}"
        self.query_one("#suggestions", OptionList).display = False
        show_error(self.query_one("#macro-error", Static), None)
        self._meter()
        self._help()
        self.query_one("#macro-name", Input).focus()

    # --- the body, its meter and help --------------------------------------------------------------------
    @property
    def area(self) -> MacroTextArea:
        return self.query_one("#macro-body", MacroTextArea)

    def offset(self) -> int:
        """The cursor's offset in the body."""
        return self.area.document.get_index_from_location(self.area.cursor_location)

    def set_body(self, text: str, cursor: int) -> None:
        """Replace the whole body as one edit (Ctrl+Z takes it back) and put the cursor at `cursor`."""
        area = self.area
        area.replace(text, (0, 0), area.document.end)
        area.cursor_location = area.document.get_location_from_index(min(cursor, len(text)))
        area.focus()

    def values(self) -> tuple[str, str, str]:
        """Name, icon and body. The text box splits lines on more than \n (U+0085, U+2028, \x0c ...) and the icon
        is trimmed, so a body or icon the user left as it was comes back as it was given, byte for byte (ME13)."""
        icon = self.query_one("#macro-icon", Input).value.strip()
        icon = self.macro_icon if icon == self.macro_icon.strip() else icon or ICON_DEFAULT
        body = self.area.text
        if body == self._shown_body:
            body = self.macro_body
        return self.query_one("#macro-name", Input).value, icon, body

    def _meter(self) -> None:
        length = body_length(self.area.text)
        over = length > BODY_LIMIT
        self.query_one("#macro-meter", Static).update(
            Text(f"{length} / {BODY_LIMIT}", style=ALERT_STYLE if over else "dim"))
        self.query_one("#ok", Button).disabled = over

    def _help(self) -> None:
        body = self.area.text
        found = describe_at(body, self.offset(), self.ref)
        text = Text("\n\n".join(found) if found else NOTHING_HERE, style="" if found else "dim")
        unknown = unknown_terms(body, self.ref)
        if unknown:
            text.append(f"\n\nMay not work in this game version: {', '.join(unknown)}", style=ALERT_STYLE)
        self.query_one("#help-text", Static).update(text)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        event.stop()
        self._meter()
        self._help()
        show_error(self.query_one("#macro-error", Static), None)
        self._seen_text = self.area.text
        taken, self._taken = self._taken, None
        if taken is None or taken != self._seen_text:  # a suggestion just taken keeps the list closed
            self._suggest()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        event.stop()
        self._help()
        if self.area.text == self._seen_text:  # the cursor moved, nothing typed: the list goes
            self._show_suggestions([])

    # --- suggestions ---------------------------------------------------------------------------------
    @property
    def suggesting(self) -> bool:
        return bool(self.options) and self.query_one("#suggestions", OptionList).display

    def _suggest(self) -> None:
        body, offset = self.area.text, self.offset()
        typed = body[completion_start(body, offset):offset].lower()
        found = suggestions(body, offset, self.ref)
        complete = any(word.lower() == typed for word, _ in found)
        self._show_suggestions([(word, help_text) for word, help_text in found if word.lower() != typed])
        self._complete = complete

    def _show_suggestions(self, options: list[tuple[str, str]]) -> None:
        self.options = options
        self._complete = self._moved = False
        listed = self.query_one("#suggestions", OptionList)
        listed.clear_options()
        if options:
            listed.add_options([Option(Text.assemble((word, "bold"), "  ", (help_text, "dim")))
                                for word, help_text in options])
            listed.highlighted = 0
        listed.display = bool(options)

    def move_suggestion(self, step: int) -> None:
        listed = self.query_one("#suggestions", OptionList)
        listed.highlighted = ((listed.highlighted or 0) + step) % len(self.options)
        self._moved = True

    def enter_takes_suggestion(self) -> bool:
        """Enter takes the highlighted suggestion unless the word typed is already complete and ↑/↓ did not choose
        one: `/targetenemy` + Enter is a new line, not `/targetenemyplayer`."""
        return self._moved or not self._complete

    def hide_suggestions(self) -> None:
        self._show_suggestions([])

    def take_suggestion(self, index: int | None = None) -> None:
        listed = self.query_one("#suggestions", OptionList)
        word = self.options[(listed.highlighted or 0) if index is None else index][0]
        area, body, offset = self.area, self.area.text, self.offset()
        start = area.document.get_location_from_index(completion_start(body, offset))
        self._show_suggestions([])
        self._taken = body[:completion_start(body, offset)] + word + body[offset:]
        area.replace(word, start, area.cursor_location)
        area.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.take_suggestion(event.option_index)

    # --- the inputs ----------------------------------------------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        show_error(self.query_one("#macro-error", Static), None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        action = self.BUTTON_ACTIONS.get(event.button.id or "")
        if action is not None:
            getattr(self, f"action_{action}")()

    # --- the keys ------------------------------------------------------------------------------------
    def action_save(self) -> None:
        if self.query_one("#ok", Button).disabled:
            return
        name, icon, body = self.values()
        problem = self.check(name, icon, body)
        if problem is not None:
            show_error(self.query_one("#macro-error", Static), problem)
            return
        self.dismiss((name, icon, body))

    def action_cancel(self) -> None:
        if self.suggesting:
            self.hide_suggestions()
            return
        self.dismiss(None)

    def action_builder(self) -> None:
        body, offset = self.area.text, self.offset()
        token = block_at(body, offset)
        builder = self.ref.builder
        original = read_block(token.text, builder) if token is not None else None

        def done(choice: tuple | None) -> None:
            if choice is None:
                return
            target, unit, states = choice
            block = write_block(original, target=target, unit=unit, states=states, builder=builder,
                                block=token.text if token is not None else None)
            start, end = (token.start, token.end) if token is not None else (offset, offset)
            if token is None:  # a new block keeps a space from the command and from the spell name
                if start and not body[start - 1].isspace() and body[start - 1] not in "];":
                    block = " " + block
                if end < len(body) and not body[end].isspace() and body[end] not in "[;":
                    block += " "
            self.set_body(body[:start] + block + body[end:], start + len(block.rstrip()))
        self.app.push_screen(BuilderScreen(original, self.ref, block=None if token is None else token.text), done)

    def action_optimize(self) -> None:
        body = self.area.text
        after, rewrites = optimize(body)
        if not rewrites:
            self.notify("Nothing to shorten: no optimizer rule applies to this macro.")
            return

        def done(ok: bool | None) -> None:
            if ok:
                self.set_body(after, len(after))
        self.app.push_screen(OptimizeScreen(body, after, rewrites), done)

    def action_template(self) -> None:
        body, offset = self.area.text, self.offset()

        def done(text: str | None) -> None:
            if text is None:
                return
            if not body.strip():
                self.set_body(text, len(text))
                return
            stop = body.find("\n", offset)
            stop = len(body) if stop < 0 else stop
            self.set_body(body[:stop] + "\n" + text + body[stop:], stop + 1 + len(text))
        self.app.push_screen(TemplateScreen(load_templates()), done)

    def action_reference(self) -> None:
        self.app.push_screen(ReferenceScreen(self.ref))
