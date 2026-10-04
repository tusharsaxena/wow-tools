"""Review the AceDB profiles of the chosen flavors as a tree (by addon or by character), tick profiles and
characters, stage deletes, renames, copies and reassignments, then apply them, try them in a dry run, or undo the
last change."""
from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, Label, ProgressBar, Static, Tree

from wowtools.core.config import Config
from wowtools.core.install import Flavor
from wowtools.core.process import wow_check_for
from wowtools.tools.ace_profiles.settings import load_settings
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import REVIEW_HINT, TwoPaneFocus, two_pane_css
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button

NAV_HINT = (REVIEW_HINT + "a all · n none · d delete · p assign · m more · w apply · y dry run · r rescan · "
            "z undo · f flavors · t tools")
WowCheck = Callable[[], "list[str] | None"]


class ProfileTree(Tree):
    """The profiles tree. ← jumps to the left panel (instead of scrolling sideways)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class ProfileReviewScreen(TwoPaneFocus, Screen[str]):
    """The AceDB databases of the chosen flavors (and account) as a tree. Dismisses with "flavors", "tools" or
    "quit". `unlocked` is the flow's set of casefolded blacklisted addons unlocked this session (shared, not
    copied)."""

    TREE_SELECTOR = "#profiles"
    DEFAULT_CSS = two_pane_css("ProfileReviewScreen", "#profiles")
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("f", "leave('flavors')", "Flavors"),
        Binding("t", "leave('tools')", "Tools"),
        Binding("q", "leave('quit')", "Quit"),
        Binding("escape", "leave('flavors')", "Flavors", show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: list[Flavor], scope_label: str, *,
                 account: str | None, unlocked: set[str], wow_check: WowCheck | None = None) -> None:
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/ace-profiles.cfg
        self.flavors = list(flavors)
        self.scope_label = scope_label
        self.account = account
        self.unlocked = unlocked
        self.wow_check = wow_check if wow_check is not None else wow_check_for(self.flavors)
        self.settings = load_settings(tool_cfg)
        self.summary_text = "Selected: 0 profiles · 0 characters · Nothing staged"
        self._last_filter: Widget | None = None

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("View", classes="section")
                yield Ka0sCheckbox("By addon", True, id="view-addon")
                yield Ka0sCheckbox("By character", False, id="view-character")
                yield Label("Show", classes="section")
                yield Ka0sCheckbox("Only addons with 2+ profiles", False, id="only-multi")
                yield Ka0sCheckbox("Only unused profiles", False, id="only-unused")
                yield Ka0sCheckbox("Leftover characters", True, id="show-leftovers")
                yield Ka0sCheckbox("Blacklisted addons", True, id="show-blacklisted")
                yield Label("Search", classes="section")
                yield Input(placeholder="addon, profile or character", id="search")
                yield Label("Staged", classes="section")
                yield Static("Nothing staged", id="staged")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Apply", "delete", id="btn-apply")
                    yield action_button("Dry run", "simulate", id="btn-dry-run")
                    yield action_button("Rescan", "neutral", id="btn-rescan")
                    yield action_button("Undo last change", "revert", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield ProfileTree(Text(self.scope_label), id="profiles")
        yield Static(Text(self.summary_text), id="summary")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"Ace3 Profile Manager · {self.scope_label}"
        self.query_one("#scan-box").display = False
        self.query_one("#profiles", Tree).focus()

    # --- panes (←/→): TwoPaneFocus ------------------------------------------------------------------
    def first_filter(self) -> Widget | None:
        return next((w for w in self.query("#filters Ka0sCheckbox").results(Ka0sCheckbox) if w.focusable), None)

    # --- leaving -------------------------------------------------------------------------------
    def action_leave(self, choice: str) -> None:
        self.dismiss(choice)
