"""The blacklist as a tree of flavor → addon (feedback round 1): every addon with Ace3 data, ticked when its
(flavor, addon) pair is blacklisted. Opened from the settings screen and from the review."""
from __future__ import annotations

import time
from collections.abc import Iterable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode

from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor, WowInstall
from wowtools.tools.ace_profiles.report import plural
from wowtools.tools.ace_profiles.scanner import ScanResult, scan_flavors
from wowtools.tools.ace_profiles.settings import WILDCARD, Pair, is_blacklisted, unique_pairs
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import (ACCENT, TREE_BINDINGS, TREE_HINT, TwoPaneFocus, relabel_branch, review_hint,
                                 theme_colour, tick_mark, two_pane_css)
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

EXPLANATION = "Ticked addons are blacklisted: their profiles are shown but never changed."
NAV_HINT = review_hint() + "a all · n none · " + TREE_HINT + "Esc cancel"
PROGRESS_EVERY = 0.05  # seconds between two scan progress reports sent to the UI thread
Key = tuple[str, str]  # (flavor folder, addon), casefolded


def _key(flavor: str, addon: str) -> Key:
    return flavor.casefold(), addon.casefold()


class BlacklistTree(Tree):
    """The flavor → addon tree. ← jumps to the left pane (instead of scrolling sideways)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Buttons", show=False)]


class BlacklistScreen(TwoPaneFocus, Screen["list[Pair] | None"]):
    """Tick the (flavor, addon) pairs to blacklist. Dismisses with the new pair list (Save), or None (Cancel, Esc).

    `cfg` is the suite config (its WoW folder names every flavor of the install); `flavors` are the flavors shown;
    `pairs` the blacklist now. A legacy wildcard pair ("*") shows ticked under every shown flavor that has the addon
    and is saved as explicit pairs; pairs of flavors not shown are kept as they are."""

    TREE_SELECTOR = "#blacklist-tree"
    DEFAULT_CSS = two_pane_css("BlacklistScreen", "#blacklist-tree") + """
    BlacklistScreen #explain { height: auto; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("escape", "cancel", "Cancel"),
        Binding("left", "focus_filters", "Buttons", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *TREE_BINDINGS,
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, flavors: list[Flavor], pairs: Iterable[Pair]) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavors = list(flavors)
        self.pairs = list(pairs)
        self.shown_folders = {f.folder.casefold() for f in self.flavors}
        self.ticked: set[Key] = set()
        self.names: dict[Key, Pair] = {}  # every addon in the tree, with its spelling
        self.scan: ScanResult | None = None
        self._scanning = False

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Static(Text(EXPLANATION), id="explain")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Save", "apply", id="save")
                    yield action_button("Select none", "neutral", id="select-none")
                    yield action_button("Cancel", "neutral", id="cancel")
                yield NavHint(NAV_HINT)
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield BlacklistTree(Text("Blacklist", style=ACCENT), id="blacklist-tree")
        yield Static(Text(""), id="summary")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Ace3 Profile Manager · blacklist"
        self._scan()

    def first_filter(self) -> Widget | None:
        return self.query_one("#save", Button)

    # --- scan ----------------------------------------------------------------------------------
    def _scan(self) -> None:
        self._scanning = True
        self.query_one("#scan-progress", ProgressBar).update(total=None, progress=0)
        self.query_one("#scan-label", Static).update(Text("Reading SavedVariables"))
        self.query_one("#scan-box").display = True
        self.query_one("#blacklist-tree", Tree).display = False
        flavors = list(self.flavors)
        self.run_worker(lambda: self._scan_worker(flavors), thread=True, exclusive=True, group="scan")

    def _scan_worker(self, flavors: list[Flavor]) -> None:
        last = [0.0]

        def progress(flavor: Flavor, current: int, total: int, name: str) -> None:
            now = time.monotonic()
            if current < total and now - last[0] < PROGRESS_EVERY:
                return
            last[0] = now
            self.app.call_from_thread(self._scan_progress, current, total, name)

        try:
            scan = scan_flavors(flavors, progress=progress)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("ace.scan", exc)
            scan = None
            self.app.call_from_thread(self.notify, f"The scan failed: {exc}", title="Scan failed",
                                      severity="error", timeout=15)
        self.app.call_from_thread(self._scanned, scan)

    def _scan_progress(self, current: int, total: int, name: str) -> None:
        if not self.is_attached:
            return
        self.query_one("#scan-progress", ProgressBar).update(total=total or None, progress=current)
        self.query_one("#scan-label", Static).update(Text(f"Reading SavedVariables: {name}" if name else
                                                          "Reading SavedVariables"))

    def _scanned(self, scan: ScanResult | None) -> None:
        self._scanning = False
        self.scan = scan
        if not self.is_attached:
            return
        self.query_one("#scan-box").display = False
        tree = self.query_one("#blacklist-tree", Tree)
        tree.display = True
        self._build(tree)
        tree.focus()

    # --- tree ------------------------------------------------------------------------------------
    def _found(self) -> dict[str, dict[str, str]]:
        """flavor folder (casefolded) → {addon casefolded: addon} with Ace3 data in any account."""
        found: dict[str, dict[str, str]] = {f.folder.casefold(): {} for f in self.flavors}
        for flavor_scan in (self.scan.flavors if self.scan is not None else []):
            addons = found.setdefault(flavor_scan.flavor.folder.casefold(), {})
            for account in flavor_scan.accounts:
                for addon_file in account.files:
                    addons.setdefault(addon_file.file.addon.casefold(), addon_file.file.addon)
        return found

    def _build(self, tree: Tree) -> None:
        tree.clear()
        root = tree.root
        root.data = ("root",)
        found = self._found()
        for flavor in self.flavors:
            folder = flavor.folder
            addons = dict(found.get(folder.casefold(), {}))
            missing = set()
            for where, addon in self.pairs:  # blacklisted here but not found: shown so it can be taken off
                if where.casefold() == folder.casefold() and addon.casefold() not in addons:
                    addons[addon.casefold()] = addon
                    missing.add(addon.casefold())
            node = root.add(Text(""), data=("flavor", folder, flavor.display_name), expand=True)
            if not addons:
                node.add_leaf(Text("no Ace3 data", style="dim"), data=("note",))
                node.allow_expand = False
            for name in sorted(addons):
                addon = addons[name]
                key = _key(folder, addon)
                self.names[key] = (folder, addon)
                if is_blacklisted(self.pairs, folder, addon):
                    self.ticked.add(key)
                node.add_leaf(Text(""), data=("addon", folder, addon, name in missing))
        root.expand()
        self._relabel()

    def _keys(self, data) -> list[Key]:
        if data is None:
            return []
        if data[0] == "addon":
            return [_key(data[1], data[2])]
        if data[0] == "flavor":
            folder = data[1].casefold()
            return [k for k in self.names if k[0] == folder]
        if data[0] == "root":
            return list(self.names)
        return []

    def _label(self, data) -> Text:
        if data is None:
            return Text("")
        keys = self._keys(data)
        mark = tick_mark(keys, set(keys) - self.ticked, success=theme_colour(self.app, "success")) if keys \
            else ("  ", "")
        if data[0] == "flavor":
            return Text.assemble(mark, (data[2], ACCENT))
        if data[0] == "addon":
            body = Text(data[2], style="bold")
            if data[3]:
                body.append(" (not found)", style="dim")
            return Text.assemble(mark, body)
        if data[0] == "root":
            return Text.assemble(mark, ("Blacklist", ACCENT))
        return Text("no Ace3 data", style="dim")

    def _relabel(self, node: TreeNode | None = None) -> None:
        relabel_branch(self.query_one("#blacklist-tree", Tree), node, self._label, skip=("note",))
        count = len(self.ticked)
        self.query_one("#summary", Static).update(
            Text(f"{plural(count, 'addon')} blacklisted" if count else "Nothing blacklisted"))

    # --- ticks -----------------------------------------------------------------------------------
    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Button):  # Space activates the focused button, never the tree
            focused.press()
            return
        if not isinstance(focused, Tree) or self._scanning:
            return
        node = focused.cursor_node
        keys = self._keys(node.data if node is not None else None)
        if node is None or not keys:
            return
        check = any(k not in self.ticked for k in keys)
        if check:
            self.ticked.update(keys)
        else:
            self.ticked.difference_update(keys)
        log_event("ui.item_toggled", screen="ace_blacklist", key=str(node.data[1:3]), checked=check)
        self._relabel(node)

    def action_select_all(self) -> None:
        if self._scanning:
            return
        self.ticked.update(self.names)
        log_event("ui.selection", screen="ace_blacklist", control="select_all", value=True)
        self._relabel()

    def action_select_none(self) -> None:
        if self._scanning:
            return
        self.ticked.clear()
        log_event("ui.selection", screen="ace_blacklist", control="select_none", value=True)
        self._relabel()

    # --- leaving ---------------------------------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        elif event.button.id == "select-none":
            self.action_select_none()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _all_folders(self) -> list[str]:
        """Every flavor folder of the install (a wildcard is kept for the ones not shown), or the shown ones."""
        try:
            folders = [f.folder for f in WowInstall(self.cfg.wow_path).flavors()] if self.cfg.wow_path else []
        except OSError:
            folders = []
        return folders or [f.folder for f in self.flavors]

    def result(self) -> list[Pair]:
        """The ticked pairs, plus the pairs of flavors not shown (a wildcard becomes one pair per such flavor)."""
        pairs = [self.names[key] for key in self.ticked if key in self.names]
        hidden = [f for f in self._all_folders() if f.casefold() not in self.shown_folders]
        for where, addon in self.pairs:
            if where == WILDCARD:
                pairs += [(folder, addon) for folder in hidden]
            elif where.casefold() not in self.shown_folders:
                pairs.append((where, addon))
        return unique_pairs(pairs)

    def action_save(self) -> None:
        if self._scanning:
            return
        self.dismiss(self.result())
