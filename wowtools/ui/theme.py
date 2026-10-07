"""The Ka0s theme, taken from the Ka0s shield logo: navy-black, deep blue, electric-blue glow, steel silver.

It also holds the action-kind button colours (spec D12): one colour per kind of action, the same in every tool, as
theme variables `$act-<kind>` (plus `-lighten`, `-darken` and `-text` shades) that `ui/widgets.py` turns into
button CSS."""
from __future__ import annotations

from textual.color import Color
from textual.theme import Theme

KA0S_THEME = Theme(
    name="ka0s",
    primary="#2F8CFF",
    secondary="#8A96A8",
    accent="#5CC8FF",
    foreground="#D3DAE3",
    background="#05080F",
    surface="#0B1526",
    panel="#10213D",
    success="#4CC38A",
    warning="#E8B04B",
    error="#E5534B",
    dark=True,
)
FOREGROUND: str = KA0S_THEME.foreground or ""
BACKGROUND: str = KA0S_THEME.background or ""
# The title bar (spec D41): "Ka0s WoW Tools" in gold, then the tool, flavor and view in near-white, all bold.
TITLE_GOLD = "#E6B422"
TITLE_TEXT = "#F0F0F0"
TITLE_TOOL = KA0S_THEME.accent or "#5CC8FF"  # the tool's name in the title bar: cyan

# Button colour per action kind: (background, text). A text of None takes whichever of the theme's foreground and
# background reads better on it. The violet leans to red (an orchid), a clear hue away from the lavender the WTF
# Cleaner uses for its "stray copies" criterion next to its Undo button; the cyan is a green-blue, apart from the
# confirm blue. Only the red is shared with a criterion (not installed: those files are what Clean deletes).
ACTION_COLOURS: dict[str, tuple[str, str | None]] = {
    "destructive": (KA0S_THEME.error or "", None),  # deletes for good (Clean, Ace3 Apply): red
    "overwrite": (KA0S_THEME.warning or "", None),  # overwrites files (Restore, Organize, Update now): amber
    "create": (KA0S_THEME.success or "", None),     # only adds files (Back up): green
    "revert": ("#C060C8", None),                    # puts a change back (Undo, Put the originals back): violet
    "simulate": ("#22B8C4", None),                  # shows what would happen, changes nothing (Dry run): cyan
    "confirm": (KA0S_THEME.primary, None),          # the expected next step (Save, OK, Yes): blue
    "refresh": ("#A8D94A", None),                   # reads the files again (Rescan): lime
    "navigate": ("#33425A", FOREGROUND),            # moves between screens (Tools, Other flavor, Search): grey
    "cancel": ("#1A2536", KA0S_THEME.secondary),    # backs out or declines (Cancel, No, Quit, Back): dim grey
}
SHADE = 0.15  # how much lighter / darker the top and bottom edges (and the hover background) are


def _luminance(colour: Color) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(colour.r) + 0.7152 * channel(colour.g) + 0.0722 * channel(colour.b)


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio of two colours (1 to 21)."""
    high, low = sorted((_luminance(Color.parse(a)), _luminance(Color.parse(b))), reverse=True)
    return (high + 0.05) / (low + 0.05)


def action_text(kind: str) -> str:
    background, text = ACTION_COLOURS[kind]
    return text or max((FOREGROUND, BACKGROUND), key=lambda candidate: contrast(candidate, background))


def action_variables() -> dict[str, str]:
    """The `act-<kind>` CSS variables: background, lighter and darker edge, and text colour per kind."""
    variables: dict[str, str] = {}
    for kind, (background, _) in ACTION_COLOURS.items():
        colour = Color.parse(background)
        variables[f"act-{kind}"] = colour.hex
        variables[f"act-{kind}-lighten"] = colour.lighten(SHADE).hex
        variables[f"act-{kind}-darken"] = colour.darken(SHADE).hex
        variables[f"act-{kind}-text"] = action_text(kind)
    return variables


KA0S_THEME.variables.update(action_variables())
