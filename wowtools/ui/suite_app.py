"""The one Ka0s WoW Tools app: the lock check, the tool menu, then whichever tool is picked.

Every tool runs inside this app as a ToolFlow, so the tools share one window, theme, header and footer, and
leaving a tool comes back to the menu. Under the hood each tool keeps its own screens, workflow and config file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.config import CONFIG_DIR, Config, ConfigError, tool_config_path
from wowtools.core.events import get_event_log, log_event
from wowtools.core.install import detect_installs
from wowtools.core.lock import InstanceLock, LockInfo
from wowtools.tools import TOOLS
from wowtools.ui.base import Ka0sApp
from wowtools.ui.branding import Banner, BrandBar
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint


class LockScreen(ModalScreen[bool]):
    """Another copy may be running: quit, or take the lock over and carry on."""

    DEFAULT_CSS = """
    LockScreen { align: center middle; }
    LockScreen #lock-box { width: 90; height: auto; border: thick $warning; background: $panel; padding: 1 2; }
    LockScreen #lock-title { color: $warning; text-style: bold; margin-bottom: 1; }
    LockScreen #lock-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    LockScreen Button { margin-left: 2; }
    """
    BINDINGS = [Binding("o", "answer(True)", "Override"), Binding("q,escape", "answer(False)", "Quit"),
                *NAV_BINDINGS]

    def __init__(self, holder: LockInfo, lock_path: Path) -> None:
        super().__init__()
        self.holder = holder
        self.lock_path = lock_path
        self.stale = holder.stale

    def body(self) -> str:
        lines = [f"The lock file {self.lock_path} says Ka0s WoW Tools is already open:",
                 f"  {self.holder.describe()}", ""]
        if self.stale:
            lines.append("That process is no longer running, so the lock file is probably left over from a crash.")
        else:
            lines.append("Running two copies at once can make them overwrite each other's settings and backups. "
                         "If the other copy is not really open (for example it crashed), override the lock.")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        with Vertical(id="lock-box"):
            yield Static(Text("Ka0s WoW Tools may already be running"), id="lock-title")
            yield Static(Text(self.body()), id="lock-body")
            with ButtonRow(id="lock-buttons"):
                yield Button("Override and continue (o)", variant="warning", id="lock-override")
                yield Button("Quit (q)", variant="primary", id="lock-quit")
            yield NavHint("←→ choose · Enter/Space press · o override · q/Esc quit")

    def on_mount(self) -> None:
        self.query_one("#lock-override" if self.stale else "#lock-quit", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "lock-override")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class ToolMenuScreen(Screen[None]):
    """The first screen: every tool in the suite. It stays at the bottom of the stack while a tool runs."""

    DEFAULT_CSS = """
    ToolMenuScreen #pick-title { color: $accent; text-style: bold; padding: 0 2; }
    ToolMenuScreen #tools { margin: 1 2; height: auto; border: tall $primary; }
    ToolMenuScreen NavHint { padding: 0 2; }
    """
    BINDINGS = [Binding("q,escape", "app.quit", "Quit"), *NAV_BINDINGS]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Banner()
        yield Static("Choose a tool", id="pick-title")
        yield OptionList(*[Option(Text.assemble((t.title, "bold"), "  ·  ", t.description), id=t.name)
                           for t in TOOLS.values()], id="tools")
        yield NavHint("↑↓ choose · Enter open · s settings · q/Esc quit")
        yield BrandBar()
        yield Footer()

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
    BINDINGS = [Binding("s", "settings", "Settings")]

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

    def _lock_answered(self, override: bool | None) -> None:
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
