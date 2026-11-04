"""The Config Editor's popups, styled like ConfirmScreen (ui.dialogs.popup_css): Add (CE5: a CVar's name and value,
with what the knowledge base says about the name as it is typed: its default, scope and what it does, `unknown`, or
the scope warning; CF6: the name field narrows a list of the known CVars the files don't set, and picking one fills
the name and its default) and Recommend… (CE7: the recommendations for a file, each with its value, reason and source, ticked and
staged as a batch). Set is the shared TextPromptScreen. Each dismisses with what the user chose; the review stages
it (edit_actions.py). Nothing is written here."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.kb import CvarInfo
from wowtools.tools.config_editor.ops import RecommendRow, match_candidates
from wowtools.ui.dialogs import GUARD_BINDING, EnterGuard, popup_css, show_error
from wowtools.ui.widgets import CHECK_OFF, CHECK_ON, NAV_BINDINGS, ButtonRow, NavHint, action_button

__all__ = ["AddCvarScreen", "RecommendScreen"]


class EdgeOptionList(OptionList):
    """An OptionList whose ↑ on its first enabled row and ↓ on its last move the focus (to the field above or
    below) instead of wrapping round, so the popup's ↑↓ walk passes through the list both ways."""

    def _enabled(self) -> list[int]:
        return [index for index, option in enumerate(self.options) if not option.disabled]

    def action_cursor_up(self) -> None:
        enabled = self._enabled()
        if not enabled or self.highlighted is None or self.highlighted <= enabled[0]:
            self.screen.focus_previous()
            return
        super().action_cursor_up()

    def action_cursor_down(self) -> None:
        enabled = self._enabled()
        if not enabled or self.highlighted is not None and self.highlighted >= enabled[-1]:
            self.screen.focus_next()
            return
        super().action_cursor_down()


class AddCvarScreen(EnterGuard, ModalScreen[tuple[str, str] | None]):
    """Add a CVar (CE5, CF6): name and value. Under the name, a list of `known` (the CVars the knowledge base knows
    for the files that none of them sets, ops.add_candidates) narrowed by the name as it is typed, at most
    ops.ADD_LIST_CAP of them and then how many more; picking one (Enter in the list or a click, or Enter in the name
    field while a match is highlighted and the name typed is not itself a known one) puts its name in the field and
    its default in the value (editable), and moves to the value. ↑ on the list's top row goes back to the name, ↓ on
    its last to the value (EdgeOptionList). Any name can still be typed, known or not.
    `describe(name)` is the note under the fields (what the knowledge base knows of the name, what it does, or that
    it is unknown, and a scope warning; never a refusal); `check(name, value)` a problem that keeps the popup open
    (an empty name, a space or a quote in it, a line break in the value) or None. OK, Enter in the value, or Enter in
    the name with no match to pick, dismisses with (name, value), Cancel or Esc with None; Enter on a button waits for the EnterGuard, as in the other
    popups."""

    DEFAULT_CSS = popup_css("AddCvarScreen", list_rows=6) + """
    AddCvarScreen #cvar-note { height: auto; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), GUARD_BINDING, *NAV_BINDINGS]

    def __init__(self, title: str, body: str, describe: Callable[[str], str],
                 check: Callable[[str, str], str | None], known: Sequence[CvarInfo] = ()) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.describe = describe
        self.check = check
        self.known = list(known)
        self._by_name = {info.name: info for info in self.known}

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text(self.title_text), classes="title")
            yield Static(Text(self.body_text), classes="popup-body")
            yield Input("", placeholder="CVar name: type to narrow the list, or any name", id="cvar-name",
                        compact=True)
            yield EdgeOptionList(id="cvar-options", compact=True)
            yield Input("", placeholder="value", id="cvar-value", compact=True)
            yield Static("", id="cvar-note")
            yield Static("", id="cvar-error", classes="popup-error")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("Enter picks the highlighted CVar, then OK · ↑↓/Tab move · ←→ buttons")

    def on_mount(self) -> None:
        self.start_guard()
        self._options()
        self._note()
        self.query_one("#cvar-name", Input).focus()

    def values(self) -> tuple[str, str]:
        return self.query_one("#cvar-name", Input).value.strip(), self.query_one("#cvar-value", Input).value

    def _options(self) -> None:
        """The list narrowed to the name as typed: the capped matches, then a line counting the rest."""
        shown, more = match_candidates(self.known, self.values()[0])
        options = self.query_one("#cvar-options", OptionList)
        options.clear_options()
        options.add_options([Option(info.name, id=info.name) for info in shown])
        if more:
            options.add_option(Option(Text(f"… {more} more, keep typing", style="dim italic"), disabled=True))
        options.display = bool(shown)
        if shown:
            options.highlighted = 0

    def _note(self) -> None:
        name = self.values()[0]
        self.query_one("#cvar-note", Static).update(Text(self.describe(name) if name else ""))

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        show_error(self.query_one("#cvar-error", Static), None)
        if event.input.id == "cvar-name":
            self._options()
        self._note()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the value field is OK. Enter in the name field picks the highlighted CVar of the list when the
        name typed is not itself a known one (as a dropdown would), and is OK when it is, or when nothing matches
        (a name the reference doesn't know)."""
        event.stop()
        if event.input.id == "cvar-name" and self._pick_highlighted():
            return
        self._ok()

    def _pick_highlighted(self) -> bool:
        name = self.values()[0].casefold()
        if any(known.casefold() == name for known in self._by_name):
            return False
        options = self.query_one("#cvar-options", OptionList)
        if not options.display or options.highlighted is None:
            return False
        option = options.get_option_at_index(options.highlighted)
        if option.disabled or option.id not in self._by_name:
            return False
        self._pick(self._by_name[option.id])
        return True

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """A CVar picked from the list (Enter or a click)."""
        event.stop()
        info = self._by_name.get(event.option.id or "")
        if info is not None:
            self._pick(info)

    def _pick(self, info: CvarInfo) -> None:
        """Its name, its default as the value (empty when none is known), then the value field, ready to edit."""
        self.query_one("#cvar-name", Input).value = info.name
        value = self.query_one("#cvar-value", Input)
        value.value = info.default or ""
        value.focus()

    def _ok(self) -> None:
        name, value = self.values()
        problem = self.check(name, value)
        if problem is not None:
            show_error(self.query_one("#cvar-error", Static), problem)
            return
        self.dismiss((name, value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self._ok()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RecommendScreen(ModalScreen[list[RecommendRow] | None]):
    """Recommend… (CE7): one line per recommendation for the file (`cvar → value`, its value there now), the
    highlighted one's reason and source under the list. Space or Enter ticks a line; one already at the value is
    shown, never ticked. OK dismisses with the ticked rows (staged as a batch), Cancel with None."""

    DEFAULT_CSS = popup_css("RecommendScreen", list_rows=10) + """
    RecommendScreen #rec-detail { height: auto; min-height: 3; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"),
                                         Binding("space", "tick", "Tick", show=False), *NAV_BINDINGS]

    def __init__(self, title: str, body: str, rows: Sequence[RecommendRow]) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.rows = list(rows)
        self.ticked: set[int] = set()

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text(self.title_text), classes="title")
            yield Static(Text(self.body_text), classes="popup-body")
            yield OptionList(id="recs", compact=True)
            yield Static("", id="rec-detail")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("↑↓ move · Space/Enter tick · Tab buttons")

    def on_mount(self) -> None:
        self._show()
        recs = self.query_one("#recs", OptionList)
        if self.rows:
            recs.highlighted = 0
            recs.focus()
        else:
            self.query_one("#cancel", Button).focus()
        self._detail()

    def _line(self, index: int, row: RecommendRow) -> Text:
        rec = row.recommendation
        now = "not set" if row.current is None else row.current
        if row.done:
            done = "  already the default" if row.current is None else "  already set"
            return Text.assemble(("  ", ""), (f"{rec.cvar} = {rec.value}", "dim"), (done, "dim italic"))
        mark = CHECK_ON if index in self.ticked else CHECK_OFF
        return Text.assemble((f"{mark} ", "bold"), f"{rec.cvar} → {rec.value}", (f"  (now {now})", "dim"))

    def _show(self) -> None:
        recs = self.query_one("#recs", OptionList)
        highlighted = recs.highlighted
        recs.clear_options()
        recs.add_options([Option(self._line(i, row)) for i, row in enumerate(self.rows)])
        if self.rows:
            recs.highlighted = min(highlighted or 0, len(self.rows) - 1)
        if not self.rows:
            self.query_one("#rec-detail", Static).update(Text("No recommendation for this file.", style="dim"))
        self.query_one("#ok", Button).disabled = not self.ticked

    def _detail(self) -> None:
        index = self.query_one("#recs", OptionList).highlighted
        if index is None or not self.rows:
            return
        rec = self.rows[index].recommendation
        self.query_one("#rec-detail", Static).update(Text(f"{rec.reason}\nSource: {rec.source}"))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self._detail()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self._toggle(event.option_index)

    def action_tick(self) -> None:
        focused = self.focused
        if isinstance(focused, Button):
            focused.press()
            return
        index = self.query_one("#recs", OptionList).highlighted
        if index is not None:
            self._toggle(index)

    def _toggle(self, index: int) -> None:
        if self.rows[index].done:
            return
        self.ticked.symmetric_difference_update({index})
        self._show()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            if self.ticked:
                self.dismiss([self.rows[i] for i in sorted(self.ticked)])
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)