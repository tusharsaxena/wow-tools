"""The USE AT YOUR OWN RISK popup (spec 2026-10-07-feedback-bars-leftovers L4): a warning ChoiceScreen that the WTF
Cleaner, the Ace3 Profile Manager and the Saved Variables Browser show after the flavor pick (and the account pick)
and before the first scan, each with its own text. ToolFlow.ask_disclaimer() shows it at most once per tool per app
session."""
from __future__ import annotations

from wowtools.ui.dialogs import ChoiceScreen

ACCEPT, BACK = "accept", "back"
DISCLAIMER_TITLE = "USE AT YOUR OWN RISK"


class DisclaimerScreen(ChoiceScreen):
    """`text` under the title (`title`, USE AT YOUR OWN RISK by default). "I understand" (focused) dismisses with
    ACCEPT; Back (or Esc, which dismisses with None) is the way out, back to the flavor picker."""

    def __init__(self, text: str, title: str = DISCLAIMER_TITLE) -> None:
        super().__init__(title, text, [(BACK, "Back", "cancel", "escape"), (ACCEPT, "I understand", "confirm")],
                         default=ACCEPT, escape=True)
