"""Ka0s branding widgets: the shield banner and the brand bar shown on every screen."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

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


class BrandBar(Static):
    DEFAULT_CSS = """
    BrandBar { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    """

    def __init__(self) -> None:
        super().__init__("")
        self.text = ""

    def on_mount(self) -> None:
        self.watch(self.app, "release", self._show, init=True)

    def _show(self, release) -> None:
        text = f"Ka0s WoW Tools v{__version__}"
        if release is not None:
            text += f"    ⬆ v{release.version} available, press u to update"
        self.text = text
        self.update(Text(text))
