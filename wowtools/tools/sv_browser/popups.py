"""The Saved Variables Browser's popups (spec §5). The USE AT YOUR OWN RISK warning (D2) is a warning ChoiceScreen the
flow shows before the review scans. The Edit value, Rename key, Delete key and Search popups come with plan T3.2 and
T3.3."""
from __future__ import annotations

from wowtools.tools.sv_browser.report import DISCLAIMER
from wowtools.ui.dialogs import ChoiceScreen

ACCEPT, BACK = "accept", "back"
DISCLAIMER_TITLE = "USE AT YOUR OWN RISK"
# The warning body: the spec's D2 text after its first words (the title says them), then where it is said again.
DISCLAIMER_TEXT = (DISCLAIMER.removeprefix(f"{DISCLAIMER_TITLE}. ")
                   + "\n\nClose WoW before you apply anything: it rewrites every SavedVariables file when you log out."
                   " Every Apply and Undo asks again.")


class DisclaimerScreen(ChoiceScreen):
    """D2: shown each time the tool is opened from the menu, after the flavor pick and before the first scan. "I
    understand" (focused) goes on to the review; Back (or Esc, which dismisses with None) goes back to the flavor
    picker."""

    def __init__(self) -> None:
        super().__init__(DISCLAIMER_TITLE, DISCLAIMER_TEXT,
                         [(BACK, "Back", "cancel", "escape"), (ACCEPT, "I understand", "confirm")],
                         default=ACCEPT, escape=True)
