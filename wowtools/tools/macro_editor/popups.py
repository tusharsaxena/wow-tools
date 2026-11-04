"""The Macro Editor's popups, styled like ConfirmScreen (ui.dialogs.popup_css): the paste review (ME4, ME5: every name
clash with Skip, Rename or Overwrite, "Apply to all", the macros a full or read-only set refuses and the cross-flavor
warnings) and Replace text… (ME7: find, replace, Match case and a before/after preview). The edit screen of New and
Edit and its builder, optimizer, template and reference screens are in their own *_screen.py modules.
Each dismisses with what the user chose; the review stages it (edit_actions.py). Nothing is written here."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.text import plural
from wowtools.tools.macro_editor.ops import ClashChoice, PastePreview, ReplaceRow, clash_key
from wowtools.ui.dialogs import ALERT_STYLE, GUARD_BINDING, EnterGuard, popup_css
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button

__all__ = ["CHOICE_TEXT", "PasteScreen", "ReplaceTextScreen"]

CHOICE_TEXT = {"skip": "skip", "rename": "rename", "overwrite": "overwrite"}
CHOICES: tuple[ClashChoice, ...] = ("skip", "rename", "overwrite")
PREVIEW_ROWS = 6  # Replace text… shows this many macros, then "and n more"


class PasteScreen(EnterGuard, ModalScreen[dict[tuple[Path, str], ClashChoice] | None]):
    """The paste review (ME4, ME5): `preview(choices)` is ops.preview_paste on the review's staging. The list shows
    every name clash with its choice (skip at first); Skip, Rename and Overwrite set the highlighted one's, or every
    one's with Apply to all ticked; Enter on a clash moves it to the next choice. Under it, the macros that can't be
    pasted (a full or read-only set) and `warnings` (another game version, ME5). Paste dismisses with the choices,
    Cancel with None. It opens on Paste when nothing clashes, so Enter waits for the EnterGuard (STD-7.15)."""

    DEFAULT_CSS = popup_css("PasteScreen", list_rows=8) + """
    PasteScreen #paste-notes { height: auto; max-height: 8; overflow-y: auto; margin-top: 1; }
    PasteScreen #clash-buttons { height: auto; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), GUARD_BINDING, *NAV_BINDINGS]

    def __init__(self, title: str, body: str, preview: Callable[[dict], PastePreview],
                 warnings: Sequence[str] = ()) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.preview = preview
        self.warnings = list(warnings)
        self.choices: dict[tuple[Path, str], ClashChoice] = {}
        self.result: PastePreview = preview(self.choices)

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text(self.title_text), classes="title")
            yield Static(Text(self.body_text), classes="popup-body")
            yield OptionList(id="clashes", compact=True)
            with ButtonRow(id="clash-buttons"):
                yield action_button("Skip", "cancel", id="choose-skip", compact=True)
                yield action_button("Rename", "overwrite", id="choose-rename", compact=True)
                yield action_button("Overwrite", "overwrite", id="choose-overwrite", compact=True)
            yield Ka0sCheckbox("Apply to all", False, id="apply-all", compact=True)
            yield Static("", id="paste-notes")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("Paste", "create", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("↑↓/Tab move · Enter on a clash: next choice · ←→ buttons")

    def on_mount(self) -> None:
        self.start_guard()
        self._show()
        clashes = self.query_one("#clashes", OptionList)
        (clashes if self.result.clashes else self.query_one("#ok", Button)).focus()

    def _show(self) -> None:
        clashes = self.query_one("#clashes", OptionList)
        highlighted = clashes.highlighted
        clashes.clear_options()
        clashes.add_options([Option(f"[{CHOICE_TEXT[c.choice]}] {c.target.label}: {c.pasted.name} "
                                    f"(it has a macro of that name)") for c in self.result.clashes])
        clashes.display = bool(self.result.clashes)
        for widget in ("#clash-buttons", "#apply-all"):
            self.query_one(widget).display = bool(self.result.clashes)
        if self.result.clashes:
            clashes.highlighted = min(highlighted or 0, len(self.result.clashes) - 1)
        notes = [*self.warnings, *self.result.refusals]
        self.query_one("#paste-notes", Static).update(Text("\n".join(notes), style=ALERT_STYLE) if notes else "")
        self.query_one("#paste-notes", Static).display = bool(notes)
        self.query_one("#ok", Button).disabled = not self.result.staged.count() and not self.result.clashes

    def choose(self, choice: ClashChoice, index: int | None = None) -> None:
        """Give the clash at `index` (the highlighted one by default) this choice, or every clash with Apply to
        all ticked."""
        clashes = self.result.clashes
        if not clashes:
            return
        if self.query_one("#apply-all", Checkbox).value:
            picked = clashes
        else:
            at = self.query_one("#clashes", OptionList).highlighted if index is None else index
            picked = [clashes[at or 0]]
        for clash in picked:
            self.choices[clash_key(clash.target, clash.pasted)] = choice
        self.result = self.preview(self.choices)
        self._show()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        clash = self.result.clashes[event.option_index]
        self.choose(CHOICES[(CHOICES.index(clash.choice) + 1) % len(CHOICES)], event.option_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button = event.button.id or ""
        if button.startswith("choose-"):
            self.choose(button.removeprefix("choose-"))  # type: ignore[arg-type]
        elif button == "ok":
            self.dismiss(dict(self.choices))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ReplaceTextScreen(ModalScreen[tuple[str, str, bool] | None]):
    """Replace text… (ME7): find, replace with, Match case; the preview (`preview(find, new, case)`, ops.
    preview_replace) shows each macro that changes, before → after, and why one can't. Replace dismisses with
    (find, new, case), Cancel with None."""

    DEFAULT_CSS = popup_css("ReplaceTextScreen") + """
    ReplaceTextScreen #replace-preview { height: auto; max-height: 12; overflow-y: auto; margin-top: 1; }
    ReplaceTextScreen Ka0sCheckbox { margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, title: str, body: str, preview: Callable[[str, str, bool], list[ReplaceRow]]) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body
        self.preview = preview
        self.rows: list[ReplaceRow] = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text(self.title_text), classes="title")
            yield Static(Text(self.body_text), classes="popup-body")
            yield Input("", placeholder="find", id="find", compact=True)
            yield Input("", placeholder="replace with", id="replace", compact=True)
            yield Ka0sCheckbox("Match case", False, id="case", compact=True)
            yield Static("", id="replace-preview")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("Replace", "overwrite", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("Enter Replace · ↑↓/Tab move · Space tick · ←→ buttons")

    def on_mount(self) -> None:
        self._show()
        self.query_one("#find", Input).focus()

    def values(self) -> tuple[str, str, bool]:
        return (self.query_one("#find", Input).value, self.query_one("#replace", Input).value,
                self.query_one("#case", Checkbox).value)

    def _show(self) -> None:
        self.rows = self.preview(*self.values())
        ok = [row for row in self.rows if row.refusal is None]
        lines: list[Text] = [Text(f"{plural(len(ok), 'macro')} change.", style="bold")]
        for row in self.rows[:PREVIEW_ROWS]:
            where = f"{row.mset.label} › {row.macro.name}"
            if row.refusal is not None:
                lines.append(Text(f"{where}: {row.refusal}", style=ALERT_STYLE))
            else:
                before, after = row.before.replace("\n", " ⏎ "), row.after.replace("\n", " ⏎ ")
                lines.append(Text(f"{where}: {before}  →  {after}"))
        if len(self.rows) > PREVIEW_ROWS:
            lines.append(Text(f"… and {plural(len(self.rows) - PREVIEW_ROWS, 'more macro')}", style="dim"))
        self.query_one("#replace-preview", Static).update(Text("\n").join(lines))
        self.query_one("#ok", Button).disabled = not ok

    def on_input_changed(self, event: Input.Changed) -> None:
        self._show()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        self._show()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._ok()

    def _ok(self) -> None:
        if not self.query_one("#ok", Button).disabled:
            self.dismiss(self.values())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self._ok()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
