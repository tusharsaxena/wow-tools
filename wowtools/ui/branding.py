"""Ka0s branding widgets: the shield banner, and the bottom bar every screen ends with (the footer's keys on the
left, the brand bar's version and update notice on the right, in one row)."""
from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Input, Static, TextArea

from wowtools import __version__

BANNER = "\n".join([  # noqa: FLY002 - one row of the art per line
    "  ▗▄▄▄▄▄▄▄▄▄▄▄▖  ",
    "  ▐ ██  ▄██▀  ▌  ",
    "  ▐ ██▄██▀    ▌  ",
    "  ▐ ██▀██▄    ▌  ",
    "  ▐ ██  ▀██▄  ▌  ",
    "   ▀▄       ▄▀   ",
    "     ▀▀▄▄▄▀▀     ",
    "",
    "K a 0 s   ·   W o W   T o o l s",
])


class Banner(Static):
    DEFAULT_CSS = """
    Banner { width: 100%; height: auto; content-align: center middle; text-align: center;
             color: $accent; text-style: bold; padding: 1 0; }
    """

    def __init__(self) -> None:
        super().__init__(Text(BANNER))


def update_key_free(screen: Screen) -> bool:
    """True when `u` on this screen reaches the app's update action (spec D15). It does not when the screen binds
    `u` itself (the Ace3 review's Unlock) or when a text box has focus (it types the letter); then the update
    notice must not tell the user to press it there. A popup (ModalScreen) is judged by the screen under it,
    where the key lands once the popup closes."""
    if isinstance(screen, ModalScreen):
        try:
            stack = screen.app.screen_stack
        except Exception:  # noqa: BLE001 - not mounted: judge the popup itself
            stack = []
        below = [s for s in stack[:stack.index(screen)] if not isinstance(s, ModalScreen)] if screen in stack else []
        if below:
            screen = below[-1]
    if isinstance(screen.focused, (Input, TextArea)):
        return False
    return all(binding.action in ("update", "app.update")
               for binding in screen._bindings.key_to_bindings.get("u", []))


def update_notice(version: str, key_free: bool) -> str:
    """The "new version" text for the bottom bar and the toast: press u, or, where the screen uses u for its own
    action (update_key_free), update from the tool menu."""
    if key_free:
        return f"v{version} available, press u to update"
    return f"v{version} available, press u on the tool menu to update"


def brand_texts(version: str, release_version: str | None, key_free: bool) -> list[str]:
    """What the brand bar can say, longest first: it shows the first that fits the room the footer's keys leave
    (a review's footer leaves 15 to 20 columns at 120; the tool menu's leaves room for the whole text). The
    shortest keeps the new version's number; ellipsis is the last resort."""
    name = f"Ka0s WoW Tools v{version}"
    if release_version is None:
        return [name, f"v{version}"]
    notice = f"⬆ {update_notice(release_version, key_free)}"
    new = f"⬆ v{release_version}"
    short = [f"{new}: press u", f"{new} (u)"] if key_free else [f"{new}: menu, u", f"{new} (menu)"]
    return [f"{notice} · {name}", f"{notice} · v{version}", notice, *short, new]


class BrandBar(Static):
    """The version, and the update notice once the background check finds a release, in the longest wording that
    fits (brand_texts). Only shown inside a BottomBar: docked at the bottom on its own it would sit under the
    Footer (docked siblings overlap, so for a long time it was never seen)."""

    DEFAULT_CSS = """
    BrandBar { width: 1fr; height: 1; background: $footer-background; color: $text-muted; padding: 0 1 0 0;
               text-align: right; text-wrap: nowrap; text-overflow: ellipsis; }
    BrandBar.-update { color: $warning; text-style: bold; }
    """

    def __init__(self) -> None:
        super().__init__("")
        self.text = ""  # the longest wording; what shows is shown_text
        self.texts: list[str] = []

    def on_mount(self) -> None:
        self.watch(self.app, "release", self._show, init=True)
        # a text box taking focus takes `u` too (update_key_free), so the wording follows the focus
        self.watch(self.screen, "focused", lambda _focused: self._show(getattr(self.app, "release", None)), init=False)

    def _show(self, release) -> None:
        self.texts = brand_texts(__version__, None if release is None else release.version,
                                 update_key_free(self.screen))
        self.text = self.texts[0]
        self.set_class(release is not None, "-update")
        self.refresh()

    @property
    def shown_text(self) -> str:
        room = self.content_size.width
        return next((text for text in self.texts if cell_len(text) <= room), self.texts[-1] if self.texts else "")

    def render(self) -> Text:
        return Text(self.shown_text)


class BottomBar(Horizontal):
    """The last row of every screen: the Footer's keys (compact) from the left, the BrandBar in what is left on
    the right. One docked container holding both, so neither hides the other and no screen loses a row to it."""

    DEFAULT_CSS = """
    BottomBar { dock: bottom; height: 1; width: 100%; background: $footer-background; }
    BottomBar > Footer { dock: none; width: auto; max-width: 100%; }
    """

    def compose(self) -> ComposeResult:
        yield Footer(compact=True)
        yield BrandBar()
