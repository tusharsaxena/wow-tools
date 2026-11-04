"""The conditional builder (config tools spec ME9), opened from the edit screen with Ctrl+B: radio buttons for the
target (none, or a unit from the reference's builder list; the block's own unit added when the list lacks it) and
for help / harm / either, and a checkbox per state (the reference's builder list: dead, nodead, combat, mod:shift,
…). Opened on a block it is filled from that block (builder.read_block); the preview shows the block it will write
and reads it out in plain English. OK dismisses with (target, unit, states); Cancel and Esc with None. Ticking a
state unticks its `no` opposite (dead and nodead can't both hold)."""
from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, RadioButton, RadioSet, Static

from wowtools.core.kb import MacroReference
from wowtools.tools.macro_editor.builder import REACTIONS, BlockChoice, write_block
from wowtools.tools.macro_editor.explain import explain_block
from wowtools.ui.dialogs import popup_css
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button

__all__ = ["EITHER", "NO_TARGET", "BuilderScreen", "state_id"]

NO_TARGET = "none"
EITHER = "either"
STATE_COLUMNS = 4


def state_id(state: str) -> str:
    """A state's checkbox id: `mod:shift` -> "state-mod-shift"."""
    return "state-" + "".join(c if c.isalnum() else "-" for c in state.lower())


class BuilderScreen(ModalScreen["tuple[str | None, str | None, tuple[str, ...]] | None"]):
    DEFAULT_CSS = popup_css("BuilderScreen") + f"""
    BuilderScreen #builder-radios {{ height: auto; }}
    BuilderScreen RadioSet {{ width: 1fr; height: auto; margin-right: 1; }}
    BuilderScreen #states {{ grid-size: {STATE_COLUMNS}; grid-rows: 1; height: auto; margin-top: 1; }}
    BuilderScreen #states Ka0sCheckbox {{ margin: 0; }}
    BuilderScreen #block-preview {{ height: auto; margin-top: 1; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"),
                                         Binding("ctrl+s", "ok", "OK", show=False), *NAV_BINDINGS]

    def __init__(self, original: BlockChoice | None, ref: MacroReference, *, block: str | None = None) -> None:
        """`block` is the block's text as written: the preview rewrites it as OK will (its spaces kept)."""
        super().__init__()
        self.original = original
        self.block_text = block
        self.ref = ref
        builder = ref.builder
        self.targets = [NO_TARGET, *builder.get("targets", ())]
        if original is not None and original.target is not None and original.target not in self.targets:
            self.targets.append(original.target)
        self.units = [EITHER, *(u for u in builder.get("unit", REACTIONS) if u in REACTIONS)]
        self.states = list(builder.get("states", ()))

    def compose(self) -> ComposeResult:
        chosen = self.original or BlockChoice(None, None, (), ())
        with Vertical(classes="popup-box"):
            yield Static(Text("Edit this [...] block" if self.original else "New [...] block"), classes="title")
            with Horizontal(id="builder-radios"):
                with RadioSet(id="target"):
                    for target in self.targets:
                        yield RadioButton(target, value=target == (chosen.target or NO_TARGET), compact=True)
                with RadioSet(id="unit"):
                    for unit in self.units:
                        yield RadioButton(unit, value=unit == (chosen.unit or EITHER), compact=True)
            with Grid(id="states"):
                for state in self.states:
                    yield Ka0sCheckbox(state, state in chosen.states, id=state_id(state), compact=True)
            yield Static("", id="block-preview")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", "ctrl+s", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("Tab move · ↑↓ in a list · Enter/Space choose")

    def on_mount(self) -> None:
        self._preview()
        self.query_one("#target", RadioSet).focus()

    def choice(self) -> tuple[str | None, str | None, tuple[str, ...]]:
        target = self._pressed("#target")
        unit = self._pressed("#unit")
        states = tuple(s for s in self.states if self.query_one(f"#{state_id(s)}", Checkbox).value)
        return (None if target == NO_TARGET else target, None if unit == EITHER else unit, states)

    def _pressed(self, selector: str) -> str:
        button = self.query_one(selector, RadioSet).pressed_button
        return button.label.plain if button is not None else ""

    def block(self) -> str:
        target, unit, states = self.choice()
        original = self.original
        text = None if original is None else self.block_text or "[" + ",".join(original.items) + "]"
        return write_block(original, target=target, unit=unit, states=states, builder=self.ref.builder, block=text)

    def _preview(self) -> None:
        block = self.block()
        self.query_one("#block-preview", Static).update(
            Text.assemble((block, "bold"), "\n", (explain_block(block, self.ref), "dim")))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._preview()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        state = str(event.checkbox.label)
        if event.value:  # dead and nodead can't both hold
            opposite = state[2:] if state.startswith("no") else f"no{state}"
            if opposite in self.states:
                self.query_one(f"#{state_id(opposite)}", Checkbox).value = False
        self._preview()

    def action_ok(self) -> None:
        self.dismiss(self.choice())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self.action_ok()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
