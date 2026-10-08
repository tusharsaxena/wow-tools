"""The USE AT YOUR OWN RISK popup (spec 2026-10-07-feedback-bars-leftovers L4, L8): a warning ChoiceScreen that the
WTF Cleaner, the Ace3 Profile Manager and the Saved Variables Browser show after the flavor pick (and the account
pick) and before the first scan, each with its own text. ToolFlow.ask_disclaimer() shows it at most once per tool per
app session, and never once the tool's skip_risk_warning setting is on (its "Don't show this warning again" box)."""
from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from textual.binding import Binding
from textual.widget import Widget

from wowtools.ui.dialogs import ChoiceScreen
from wowtools.ui.widgets import Ka0sCheckbox

ACCEPT, BACK = "accept", "back"
ACCEPT_DONT_SHOW = "accept-dont-show"  # I understand with the box ticked: the tool saves skip_risk_warning = true
DONT_SHOW = "dont-show"
DONT_SHOW_LABEL = "Don't show this warning again for this tool"
DISCLAIMER_TITLE = "USE AT YOUR OWN RISK"


class DontShowCheckbox(Ka0sCheckbox):
    """The popup's "Don't show this warning again" box: Space ticks it, Enter presses I understand (as it does
    everywhere else on the popup, behind the same Enter guard), so ticking it never needs a second key to go on."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("enter", "accept", "I understand", show=False)]

    def action_accept(self) -> None:
        screen = self.screen
        if isinstance(screen, DisclaimerScreen) and not screen.too_soon():
            screen.choose(ACCEPT)


class DisclaimerScreen(ChoiceScreen):
    """`text` under the title (`title`, USE AT YOUR OWN RISK by default), then the "Don't show this warning again
    for this tool" box (Tab reaches it, Space ticks it). "I understand" (focused) dismisses with ACCEPT, or with
    ACCEPT_DONT_SHOW when the box is ticked; Back (or Esc, which dismisses with None) is the way out, back to the
    flavor picker, whatever the box says."""

    DEFAULT_CSS = """
    DisclaimerScreen #dont-show { margin-top: 1; }
    """

    def __init__(self, text: str, title: str = DISCLAIMER_TITLE) -> None:
        super().__init__(title, text, [(BACK, "Back", "cancel", "escape"), (ACCEPT, "I understand", "confirm")],
                         default=ACCEPT, escape=True)

    def extras(self) -> Iterable[Widget]:
        yield DontShowCheckbox(DONT_SHOW_LABEL, False, id=DONT_SHOW, compact=True)

    def choose(self, choice: str) -> None:
        if choice == ACCEPT and self.query_one(f"#{DONT_SHOW}", DontShowCheckbox).value:
            choice = ACCEPT_DONT_SHOW
        self.dismiss(choice)
