"""The blacklist as a tree of flavor → addon (feedback round 1): every addon with Ace3 data, ticked when its
(flavor, addon) pair is blacklisted. Opened from the settings screen and from the review."""
from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Header, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode

from wowtools.core.blacklist import WILDCARD, Pair, is_blacklisted, unique_pairs
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.progress import ThrottledProgress
from wowtools.core.text import plural
from wowtools.tools.ace3_profile_manager.report import scan_label
from wowtools.tools.ace3_profile_manager.scanner import ScanResult, scan_flavors
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import (ACCENT, TREE_BINDINGS, TREE_HINT, ConfirmScreen, relabel_branch, review_hint,
                                two_pane_css)
from wowtools.ui.review import ReviewBase, ReviewTree, TickModel
from wowtools.ui.tree_filter import FILTER_BINDINGS, FILTER_HINT, FilterBar, TreeFilter
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

EXPLANATION = "Ticked addons are blacklisted: the review shows them marked ⊘, never ticked or changed."
NAV_HINT = review_hint() + "a all · " + FILTER_HINT + TREE_HINT.removesuffix(" · ")
Key = tuple[str, str]  # (flavor folder, addon), casefolded


def _key(flavor: str, addon: str) -> Key:
    return flavor.casefold(), addon.casefold()


class BlacklistScreen(TreeFilter, ReviewBase, Screen["list[Pair] | None"]):
    """Tick the (flavor, addon) pairs to blacklist. Dismisses with the new pair list (Save), or None (Cancel, Esc).

    `cfg` is the suite config (its WoW folder names every flavor of the install); `flavors` are the flavors shown;
    `pairs` the blacklist now. A wildcard pair ("*") shows ticked under every shown flavor (marked
    "(not found)" where that flavor has no data for it) and is saved as explicit pairs; pairs of flavors not shown
    are kept as they are."""

    TREE_SELECTOR = "#blacklist-tree"
    LOG_SCREEN = "ace_blacklist"
    HIDDEN_NOUN = "addon"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {"save": "save", "select-none": "select_none", "cancel": "cancel"}
    DEFAULT_CSS = two_pane_css("BlacklistScreen", "#blacklist-tree") + """
    BlacklistScreen #explain { height: auto; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        Binding("escape", "cancel", "Cancel"),
        Binding("left", "focus_filters", "Buttons", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
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
        self.flavor_names: dict[Key, str] = {}  # the flavor's display name of each, for the filter
        self.scan: ScanResult | None = None
        self._scanning = False

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Static(Text(EXPLANATION), id="explain")
                yield FilterBar()
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Save", "confirm", id="save")
                    yield action_button("Select none", "navigate", "n", id="select-none")
                    yield action_button("Cancel", "cancel", "escape", id="cancel")
                yield NavHint(NAV_HINT)
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield ReviewTree(Text("Blacklist", style=ACCENT), id="blacklist-tree")
        yield Static(Text(""), id="summary")
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = "Ace3 Profile Manager · blacklist"
        self._scan()

    def first_filter(self) -> Widget | None:
        return self.query_one("#save", Button)

    # --- scan ----------------------------------------------------------------------------------
    def _scan(self) -> None:
        self.show_scan_box(True, "Reading SavedVariables")
        flavors = list(self.flavors)
        self.run_worker(lambda: self._scan_worker(flavors), thread=True, exclusive=True, group="scan")

    def _scan_worker(self, flavors: list[Flavor]) -> None:
        # The UI gets a report per PROGRESS_INTERVAL, plus each flavor's first and last (ThrottledProgress).
        progress = ThrottledProgress(
            lambda flavor, current, total, name: self.app.call_from_thread(self._scan_progress, current, total,
                                                                           scan_label(name)))

        try:
            scan = scan_flavors(flavors, progress=progress)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("ace.scan", exc)
            scan = None
            self.app.call_from_thread(self.notify, f"The scan failed: {exc}", title="Scan failed",
                                      severity="error", timeout=15)
        self.app.call_from_thread(self._scanned, scan)

    def _scanned(self, scan: ScanResult | None) -> None:
        self._scanning = False
        self.scan = scan
        if not self.is_attached:
            return
        self.show_scan_box(False)
        tree = self.query_one("#blacklist-tree", Tree)
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

    def _can_rebuild(self) -> bool:
        return not self._scanning

    def _rebuild(self) -> None:
        """The filter changed (TreeFilter, through the debounced rebuild): build the tree again."""
        self._build(self.query_one("#blacklist-tree", Tree))

    def _build(self, tree: Tree) -> None:
        """Every flavor and its addons; what the filter shows (a flavor's name, or an addon's) and a ticked pair
        stays ticked whatever the filter hides."""
        tree.clear()
        root = tree.root
        root.data = ("root",)
        found = self._found()
        text_filter = self.text_filter
        for flavor in self.flavors:
            folder = flavor.folder
            addons = dict(found.get(folder.casefold(), {}))
            missing = set()
            for where, addon in self.pairs:  # blacklisted here (or everywhere) but not found: shown, so a Save
                # keeps it and it can be taken off; this also keeps every pair when the scan failed
                if where.casefold() in (folder.casefold(), WILDCARD) and addon.casefold() not in addons:
                    addons[addon.casefold()] = addon
                    missing.add(addon.casefold())
            for name in sorted(addons):
                key = _key(folder, addons[name])
                if key not in self.names:  # the first build: the blacklist's ticks (later ones keep the user's)
                    self.names[key] = (folder, addons[name])
                    self.flavor_names[key] = flavor.display_name
                    if is_blacklisted(self.pairs, folder, addons[name]):
                        self.ticked.add(key)
            shown = [name for name in sorted(addons)
                     if text_filter.path_matches((flavor.display_name, addons[name]))]
            if not shown and not text_filter.matches(flavor.display_name):
                continue  # nothing of it matches
            node = root.add(Text(""), data=("flavor", folder, flavor.display_name), expand=True)
            if not addons:
                node.add_leaf(Text("no Ace3 data", style="dim"), data=("note",))
                node.allow_expand = False
            for name in shown:
                node.add_leaf(Text(""), data=("addon", folder, addons[name], name in missing))
        self.note_no_match(root)
        root.expand()
        self._refresh_labels()

    def _keys(self, data) -> list[Key]:
        """The keys a tick on this node covers (TickActions narrows a flavor's or the root's to what the filter
        shows)."""
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
        mark = self.shown_tick_mark(keys) if keys else ("  ", "")
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

    def _refresh_labels(self, node: TreeNode | None = None) -> None:
        relabel_branch(self.query_one("#blacklist-tree", Tree), node, self._label, skip=("note",))
        count = len(self.ticked)
        text = f"{plural(count, 'addon')} blacklisted" if count else "Nothing blacklisted"
        hidden = self.hidden_ticked_note()
        self.query_one("#summary", Static).update(Text(f"{text}    {hidden}" if hidden else text))

    # --- ticks (Space, a, n: ReviewBase) ------------------------------------------------------------
    def tick_model(self) -> TickModel:
        return TickModel.of_ticked(self.ticked)  # ticked: blacklisted

    def node_tick_keys(self, node) -> list[Key]:
        return self._keys(node.data if node is not None else None)

    def all_tick_keys(self) -> list[Key]:
        return list(self.names)

    def filter_texts(self, key: Key) -> tuple[str, ...]:
        return self.flavor_names.get(key, ""), self.names.get(key, ("", ""))[1]

    def tick_log_key(self, node, keys) -> str:
        return str(node.data[1:3])

    def ticks_frozen(self) -> bool:
        return self._scanning

    # --- leaving (Save, Select none and Cancel are BUTTON_ACTIONS) -------------------------------------------
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
        hidden = self.hidden_ticked_note()
        if not hidden:
            self.dismiss(self.result())
            return
        # A save with ticks the filter hides: say so first (they are saved like the others).
        body = f"{plural(len(self.ticked), 'addon')} will be blacklisted."
        self.app.push_screen(ConfirmScreen("Save the blacklist?", body, (f"{hidden}: they are saved too.",),
                                           kind="confirm"), self._save_confirmed)

    def _save_confirmed(self, ok: bool | None) -> None:
        log_event("ui.selection", screen="confirm", control="blacklist_save_confirm", value=bool(ok))
        if ok:
            self.dismiss(self.result())
