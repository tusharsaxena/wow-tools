"""Ka0s branding widgets: the shield banner (with the version line and the terms of use on the tool menu), and the
bottom bar every screen ends with (the footer's keys on the left, the brand bar's version and update notice on the
right, in one row, or two when a narrow window can't fit the keys in one). The footer lists only the keys that
no shown button carries (spec D17)."""
from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Input, Static, TextArea
from textual.widgets._footer import FooterKey

from wowtools import __version__
from wowtools.ui.widgets import button_keys

BANNER_NAME = "K a 0 s   ·   W o W   T o o l s"
BANNER = "\n".join([  # noqa: FLY002 - one row of the art per line
    "  ▗▄▄▄▄▄▄▄▄▄▄▄▖  ",
    "  ▐ ██  ▄██▀  ▌  ",
    "  ▐ ██▄██▀    ▌  ",
    "  ▐ ██▀██▄    ▌  ",
    "  ▐ ██  ▀██▄  ▌  ",
    "   ▀▄       ▄▀   ",
    "     ▀▀▄▄▄▀▀     ",
    "",
    BANNER_NAME,
])

# Spec D6: shown at the bottom of the tool menu and, word for word, in the README (tests/test_docs.py pins both).
TERMS = ("Terms of use: Ka0s WoW Tools is provided as is, without warranty of any kind, and you use it at your own "
         "risk. Every tool backs up the files it changes before changing them, but keep your own backups of anything "
         "you can't afford to lose.")


class Banner(Static):
    DEFAULT_CSS = """
    Banner { width: 100%; height: auto; content-align: center middle; text-align: center;
             color: $accent; text-style: bold; padding: 1 0; }
    """

    def __init__(self) -> None:
        super().__init__(Text(BANNER))
        self.art = True

    def show_art(self, art: bool) -> None:
        """The whole shield, or only the name line (the tool menu in a short window keeps its rows for the list)."""
        if art != self.art:
            self.art = art
            self.update(Text(BANNER if art else BANNER_NAME))


def version_text(version: str, release_version: str | None) -> str:
    """The tool menu's line under the banner (spec D4): the version, and the new one once the updater finds it. The
    menu does not bind u itself, so the notice always says to press it."""
    if release_version is None:
        return f"v{version}"
    return f"v{version} · {update_notice(release_version, key_free=True)}"


class VersionLine(Static):
    """The version under the banner on the tool menu, muted and centred; it names the new version once found."""

    DEFAULT_CSS = """
    VersionLine { width: 100%; height: auto; text-align: center; color: $text-muted; }
    VersionLine.-update { color: $warning; text-style: bold; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(version_text(__version__, None), **kwargs)
        self.text = version_text(__version__, None)

    def on_mount(self) -> None:
        self.watch(self.app, "release", self._show, init=True)

    def _show(self, release) -> None:
        self.text = version_text(__version__, None if release is None else release.version)
        self.set_class(release is not None, "-update")
        self.update(self.text)


class TermsText(Static):
    """The terms of use (spec D6), muted and wrapped; no acceptance click."""

    DEFAULT_CSS = """
    TermsText { width: 100%; height: auto; color: $text-muted; padding: 0 2; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(TERMS, **kwargs)


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


def under_popup(screen: Screen) -> bool:
    """A popup (a ModalScreen: a confirm, a progress window) is open over `screen`: none of its keys work until the
    popup closes, and the popup says what to press itself."""
    top = screen.app.screen
    return top is not screen and isinstance(top, ModalScreen)


def footer_bindings(screen: Screen) -> list:
    """The (binding, enabled, tooltip) the footer lists for a screen: its shown bindings, one per action, less every
    action whose key a shown button carries (any of its keys: "n,escape" goes with a "(n)" button). The button
    says that key itself (action_button's `key`), so the footer keeps its room for the keys no button has. Under a
    popup the footer lists nothing: the screen's keys wait for the popup to close."""
    if under_popup(screen):
        return []
    active = screen.active_bindings
    on_buttons = button_keys(screen)
    covered = {active_binding.binding.action for key, active_binding in active.items() if key in on_buttons}
    listed: dict[str, tuple] = {}
    for _node, binding, enabled, tooltip in active.values():
        if binding.show and binding.action not in covered and binding.action not in listed:
            listed[binding.action] = (binding, enabled, tooltip)
    return list(listed.values())


class KeyFooter(Footer):
    """The compact Footer of every screen, listing footer_bindings: a key a shown button carries is on that button
    instead. (Textual's Footer lists every shown binding; this one has no key groups and no command palette key.)
    When the keys and the shortest version text don't fit one row (a review at 80 columns), the keys wrap into two
    rows, in columns, and the bottom bar grows to two rows: every key stays on screen."""

    rows = 1

    def wanted_rows(self, bindings: list, width: int) -> int:
        """1 if the keys (each "key description" and a space) and the shortest brand text fit `width`, else 2."""
        keys = sum(cell_len(self.app.get_key_display(binding)) + cell_len(binding.description) + 2
                   for binding, _enabled, _tooltip in bindings)
        return 1 if keys + cell_len(f"v{__version__}") + 1 <= width else 2

    def compose(self) -> ComposeResult:
        if not self._bindings_ready:
            return
        bindings = footer_bindings(self.screen)
        if not under_popup(self.screen):  # under a popup the bar keeps its height: the screen does not move
            self.rows = self.wanted_rows(bindings, self.app.size.width)
        self.styles.layout = "vertical" if self.rows > 1 else "horizontal"
        self.styles.height = self.rows
        if isinstance(self.parent, BottomBar):
            self.parent.styles.height = self.rows
        keys = [FooterKey(binding.key, self.app.get_key_display(binding), binding.description, binding.action,
                          disabled=not enabled, tooltip=tooltip).data_bind(compact=Footer.compact)
                for binding, enabled, tooltip in bindings]
        if self.rows == 1:
            yield from keys
            return
        half = -(-len(keys) // 2)  # the first row takes the odd one
        for row in (keys[:half], keys[half:]):
            yield HorizontalGroup(*row, classes="key-row")


class BottomBar(Horizontal):
    """The last row of every screen: the Footer's keys (compact) from the left, the BrandBar in what is left on
    the right. One docked container holding both, so neither hides the other and no screen loses a row to it."""

    DEFAULT_CSS = """
    BottomBar { dock: bottom; height: 1; width: 100%; background: $footer-background; }
    BottomBar > Footer { dock: none; width: auto; max-width: 100%; }
    BottomBar > Footer > .key-row { width: auto; height: 1; }
    """

    def compose(self) -> ComposeResult:
        yield KeyFooter(compact=True)
        yield BrandBar()

    def on_resize(self) -> None:
        """A narrower or wider window can change whether the keys need a second row (KeyFooter)."""
        footer = self.query_one(KeyFooter)
        if not footer._bindings_ready or under_popup(self.screen):
            return
        if footer.wanted_rows(footer_bindings(self.screen), self.app.size.width) != footer.rows:
            footer.refresh(recompose=True)
