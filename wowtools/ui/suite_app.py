"""The one Ka0s WoW Tools app: the lock check, the tool menu, then whichever tool is picked.

Every tool runs inside this app as a ToolFlow, so the tools share one window, theme, header and footer, and
leaving a tool comes back to the menu. Under the hood each tool keeps its own screens, workflow and config file.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Header, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.config import CONFIG_DIR, Config, ConfigError, tool_config_path
from wowtools.core.events import get_event_log, log_event
from wowtools.core.install import detect_installs
from wowtools.core.lock import InstanceLock, LockInfo
from wowtools.tools import TOOLS
from wowtools.ui.base import Ka0sApp
from wowtools.ui.branding import Banner, BottomBar, TermsText, VersionLine
from wowtools.ui.dialogs import ChoiceScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import LIST_CURSOR_BACKGROUND, LIST_NAME_STYLE, NAV_BINDINGS, NavHint, wrap_items


class LockScreen(ChoiceScreen):
    """Another copy may be running: quit, or take the lock over and carry on. Dismisses with "lock-override" or
    "lock-quit" (Esc and q quit); Quit is focused first unless the other copy is known to be gone (D13)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("o", "choose('lock-override')", "Override"),
                                         Binding("q,escape", "choose('lock-quit')", "Quit"), *NAV_BINDINGS]

    def __init__(self, holder: LockInfo, lock_path: Path) -> None:
        self.holder = holder
        self.lock_path = lock_path
        self.stale = holder.stale
        super().__init__("Ka0s WoW Tools may already be running", self.body(),
                         [("lock-override", "Override and continue (o)", "overwrite"),
                          ("lock-quit", "Quit (q)", "cancel")],
                         default="lock-override" if self.stale else "lock-quit",
                         hint="←→ choose · Enter/Space press · o override · q/Esc quit")

    def body(self) -> str:
        lines = [f"The lock file {self.lock_path} says Ka0s WoW Tools is already open:",
                 f"  {self.holder.describe()}", ""]
        if self.stale:
            lines.append("That process is no longer running, so the lock file is probably left over from a crash.")
        else:
            lines.append("Running two copies at once can make them overwrite each other's settings and backups. "
                         "If the other copy is not really open (for example it crashed), override the lock.")
        return "\n".join(lines)

    def action_choose(self, choice: str) -> None:
        self.choose(choice)


TOOL_NAME_STYLE = LIST_NAME_STYLE


def tool_label(title: str, description: str, width: int) -> Text:
    """A menu row: the tool name padded to `width`, then its description, so both line up as columns."""
    return Text.assemble((title.ljust(width), TOOL_NAME_STYLE), description)


MENU_HINT = "↑↓ choose · Enter open · s settings · q/Esc quit"


class ToolArea(Vertical):
    """The tool list and the hint under it, in the rows the banner and the terms leave. The list is as tall as its
    tools, up to what leaves the hint room, then it scrolls (a short window); the hint stays right under it."""

    def on_resize(self, event: Resize) -> None:
        hint = self.query_one(NavHint)
        hint_rows = len(wrap_items(hint.hint, event.size.width - 4).splitlines()) + 1  # its margin-top
        self.query_one("#tools", OptionList).styles.max_height = max(3, event.size.height - 1 - hint_rows)


class ToolMenuScreen(Screen[None]):
    """The first screen: every tool in the suite. It stays at the bottom of the stack while a tool runs.

    Top to bottom: the banner with the version under it (spec D4), the tool list, the hint, then the terms of use
    (spec D6) right above the bottom bar. The list's area takes what is left, so in a short window the terms and the
    footer stay put and the list scrolls; under MENU_ART_ROWS rows the shield art gives way to its name line."""

    MENU_ART_ROWS = 30  # BASE: at least this many rows show the whole shield
    DEFAULT_CSS = f"""
    ToolMenuScreen Banner {{ padding: 1 0 0 0; }}
    ToolMenuScreen VersionLine {{ padding: 0 0 1 0; }}
    ToolMenuScreen #pick-title {{ color: $accent; text-style: bold; padding: 0 2; }}
    ToolMenuScreen #tool-area {{ height: 1fr; }}
    ToolMenuScreen #tools {{ margin: 1 2 0 2; height: auto; border: tall $primary; }}
    ToolMenuScreen #tools > .option-list--option-highlighted {{ background: {LIST_CURSOR_BACKGROUND}; }}
    ToolMenuScreen #tools:focus > .option-list--option-highlighted {{ background: {LIST_CURSOR_BACKGROUND}; }}
    ToolMenuScreen NavHint {{ padding: 0 2; }}
    ToolMenuScreen TermsText {{ margin-top: 1; padding: 0; text-align: center; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("q,escape", "app.quit", "Quit"), *NAV_BINDINGS]

    def compose(self) -> ComposeResult:
        width = max(len(t.title) for t in TOOLS.values()) + 3  # names in one column, descriptions in the next
        yield Header()
        yield Banner()
        yield VersionLine()
        yield Static("Choose a tool", id="pick-title")
        with ToolArea(id="tool-area"):
            yield OptionList(*[Option(tool_label(t.title, t.description, width), id=t.name)
                               for t in TOOLS.values()], id="tools")
            yield NavHint(MENU_HINT)
        yield TermsText()
        yield BottomBar()

    def on_resize(self, event: Resize) -> None:
        self.query_one(Banner).show_art(event.size.height >= self.MENU_ART_ROWS)

    def on_mount(self) -> None:
        self.sub_title = "Choose a tool"
        options = self.query_one("#tools", OptionList)
        options.highlighted = 0
        options.focus()

    def on_screen_resume(self) -> None:
        self.sub_title = "Choose a tool"
        self.query_one("#tools", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.app.open_tool(event.option.id or "")


class WowToolsApp(Ka0sApp):
    SUB_TITLE = "Choose a tool"
    BINDINGS: ClassVar[list[Binding]] = [Binding("s", "settings", "Settings")]

    def __init__(self, cfg: Config, *, config_dir: Path = CONFIG_DIR, check_updates: bool = True,
                 detect: Callable[[], list[Path]] = detect_installs, lock: InstanceLock | None = None,
                 conflict: LockInfo | None = None, tool_options: dict[str, dict[str, Any]] | None = None) -> None:
        super().__init__(cfg, check_updates=check_updates)
        self.config_dir = config_dir
        self.detect = detect
        self.lock = lock
        self.conflict = conflict
        self.tool_options = tool_options or {}
        self.flow: ToolFlow | None = None
        self.menu = ToolMenuScreen()

    def after_mount(self) -> None:
        self.push_screen(self.menu)
        if self.conflict is not None and self.lock is not None:
            self.push_screen(LockScreen(self.conflict, self.lock.path), self._lock_answered)

    def _lock_answered(self, choice: str | None) -> None:
        override = choice == "lock-override"
        log_event("ui.selection", screen="lock", control="lock", value="override" if override else "quit")
        if not override or self.lock is None:
            self.exit()
            return
        self.lock.take_over()
        log_event("lock.overridden", holder=self.conflict.describe() if self.conflict else None)

    # --- tools ------------------------------------------------------------------------------------
    def open_tool(self, name: str) -> None:
        tool = TOOLS.get(name)
        if tool is None or self.flow is not None:
            return
        log_event("ui.selection", screen="tool_menu", control="tool", value=name)
        try:
            tool_cfg = Config(tool_config_path(name, self.config_dir)).load()
        except ConfigError as exc:
            self.notify(f"{exc}. Fix or delete the file, then try again.", title="Settings unreadable",
                        severity="error", timeout=15)
            return
        get_event_log().set_context(tool=name)
        self.flow = tool.flow()(self, tool_cfg, **self.tool_options.get(name, {}))
        self.sub_title = tool.title
        self.flow.start()

    def close_tool(self) -> None:
        """Back to the tool menu: drop the open tool and any of its screens still on the stack."""
        self.flow = None
        self.busy = False
        get_event_log().set_context(tool="suite")
        while len(self.screen_stack) > 1 and self.screen is not self.menu:
            self.pop_screen()
        self.sub_title = self.SUB_TITLE

    # --- settings ---------------------------------------------------------------------------------
    def action_settings(self) -> None:
        if self.busy or isinstance(self.screen, (SetupScreen, LockScreen)):
            return
        if self.flow is not None:
            self.flow.open_settings()
        else:
            self.open_general_settings()

    def open_general_settings(self, then: Callable[[bool | None], None] | None = None) -> None:
        self.push_screen(SetupScreen(self.cfg, first_run=False, detect=self.detect), then)
