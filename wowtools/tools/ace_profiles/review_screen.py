"""Review the AceDB profiles of the chosen flavors as a tree (by addon or by character), tick profiles and
characters, stage deletes, renames, copies and reassignments, then apply them, try them in a dry run, or undo the
last change."""
from __future__ import annotations

import time
from collections.abc import Callable, Hashable, Iterator
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode

from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor
from wowtools.core.process import wow_check_for
from wowtools.tools.ace_profiles.editor import Marker, read_marker
from wowtools.tools.ace_profiles.journal import latest_undoable
from wowtools.tools.ace_profiles.ops import DbKey, Staging
from wowtools.tools.ace_profiles.report import selection_text, staged_text
from wowtools.tools.ace_profiles.scanner import ScanResult, scan_flavors
from wowtools.tools.ace_profiles.settings import (is_blacklisted, load_settings, parse_blacklist, resolve_journal_dir,
                                                  resolve_root, save_settings)
from wowtools.tools.ace_profiles.tree_view import READ_ONLY, Filters, TreeBuilder, counts, ident
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import (BUSY_STYLE, REVIEW_HINT, ConfirmScreen, TwoPaneFocus, relabel_branch, theme_colour,
                                tick_mark, two_pane_css)
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button

NAV_HINT = (REVIEW_HINT + "a all · n none · d delete · p assign · m more · w apply · y dry run · r rescan · "
            "z undo · f flavors · t tools")
WowCheck = Callable[[], "list[str] | None"]
SHOW_FILTERS = {"only-multi": "only_multi", "only-unused": "only_unused", "show-leftovers": "leftovers",
                "show-blacklisted": "blacklisted"}
PROGRESS_EVERY = 0.05  # seconds between two scan progress reports sent to the UI thread


class NotTicked:
    """The keys not ticked, as tick_mark's `unchecked` collection (without listing every key)."""

    def __init__(self, ticked: set[tuple]) -> None:
        self.ticked = ticked

    def __contains__(self, key: object) -> bool:
        return key not in self.ticked

    def __iter__(self) -> Iterator:
        return iter(())

    def __len__(self) -> int:
        return 0


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
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("d", "delete", "Delete"),
        Binding("p", "assign", "Assign"),
        Binding("e", "rename", "Rename", show=False),
        Binding("k", "copy", "Copy", show=False),
        Binding("o", "remove_leftovers", "Remove leftovers", show=False),
        Binding("m", "more", "More"),
        Binding("x", "discard", "Discard", show=False),
        Binding("b", "blacklist", "Blacklist", show=False),
        Binding("u", "unlock", "Unlock", show=False),
        Binding("v", "switch_view", "View", show=False),
        Binding("slash", "focus_search", "Search", show=False),
        Binding("w", "apply", "Apply"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
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
        # The WoW folder these flavors were read from (see wow_folder_changed).
        self.wow_root = cfg.wow_path
        self._leaving_for_new_folder = False
        self.settings = load_settings(tool_cfg)
        self.scan: ScanResult | None = None
        self.staging: Staging | None = None
        self.ticked: set[tuple] = set()  # ("p", DbKey, profile) and ("c", DbKey, char)
        self.view = "addon"
        self.filters = Filters()
        self.undoable: Path | None = None  # the newest undoable journal, found by the scan worker
        self.marker: Marker | None = None  # an Apply that did not finish, found by the scan worker
        self.summary_text = "Selected: 0 profiles · 0 characters · Nothing staged"
        self._builder: TreeBuilder | None = None
        self._expanded: dict[Hashable, bool] = {}
        self._scanning = False
        self._checking = False  # a running-WoW check is in its worker
        self._rebuild_pending = False
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
        self._refresh_buttons()
        self._scan()

    # --- panes (←/→): TwoPaneFocus ------------------------------------------------------------------
    def first_filter(self) -> Widget | None:
        return next((w for w in self.query("#filters Ka0sCheckbox").results(Ka0sCheckbox) if w.focusable), None)

    # --- the WoW folder ------------------------------------------------------------------------
    def wow_folder_changed(self) -> bool:
        """True when the shared WoW folder is no longer the one these flavors came from (changed with `s`). The
        review then goes back to the flavor picker as soon as it is the screen shown."""
        if self.cfg.wow_path == self.wow_root:
            return False
        if not self._leaving_for_new_folder and self.app.screen is self and not self.app.busy:
            self._leaving_for_new_folder = True
            self.notify("The WoW folder changed: pick the flavor again.", severity="warning")
            self.dismiss("flavors")
        return True

    def on_screen_resume(self) -> None:
        self.wow_folder_changed()

    # --- state ---------------------------------------------------------------------------------
    @property
    def idle(self) -> bool:
        """Nothing is scanning, checking or running: the actions are open."""
        return not (self._scanning or self._checking or self.app.busy)

    def _refresh_buttons(self) -> None:
        if not self.is_attached:
            return
        idle = self.idle
        staged = self.staging is not None and self.staging.summary().total > 0
        self.query_one("#btn-apply", Button).disabled = not idle or not staged
        self.query_one("#btn-dry-run", Button).disabled = not idle or not staged
        self.query_one("#btn-rescan", Button).disabled = not idle
        self.query_one("#btn-undo", Button).disabled = not idle or self.undoable is None

    def locked(self, addon: str) -> bool:
        """Blacklisted and not unlocked this session: shown, never changed."""
        return is_blacklisted(self.settings.blacklist, addon) and addon.casefold() not in self.unlocked

    def _blacklisted(self, addon: str) -> bool:
        return is_blacklisted(self.settings.blacklist, addon)

    # --- scan ----------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if not self.idle or self.wow_folder_changed():
            return
        if self.staging is not None and self.staging.summary().total:
            self.app.push_screen(ConfirmScreen("Discard staged changes?",
                                               "A rescan reads the files again and drops every staged change."),
                                 lambda ok: self._scan() if ok else None)
            return
        self._scan()

    def _scan(self) -> None:
        if not self.idle:
            return
        self.settings = load_settings(self.tool_cfg)
        self._show_scan_progress(True)
        self._refresh_buttons()
        flavors, account = list(self.flavors), self.account
        root, journal_dir = resolve_root(self.settings, self.cfg.wow_path), resolve_journal_dir(self.cfg.wow_path)
        self.run_worker(lambda: self._scan_worker(flavors, account, root, journal_dir), thread=True,
                        exclusive=True, group="scan")

    def _show_scan_progress(self, scanning: bool) -> None:
        """While scanning, the tree is replaced by a progress bar and the file being read."""
        self._scanning = scanning
        if scanning:
            self.query_one("#scan-progress", ProgressBar).update(total=None, progress=0)
            self.query_one("#scan-label", Static).update(Text("Reading SavedVariables"))
        self.query_one("#scan-box").display = scanning
        self.query_one("#profiles", Tree).display = not scanning

    def _scan_worker(self, flavors: list[Flavor], account: str | None, root: Path | None,
                     journal_dir: Path | None) -> None:
        last = [0.0]

        def progress(flavor: Flavor, current: int, total: int, name: str) -> None:
            now = time.monotonic()
            if current < total and now - last[0] < PROGRESS_EVERY:
                return
            last[0] = now
            self.app.call_from_thread(self._scan_progress, current, total, name)

        try:
            scan = scan_flavors(flavors, account=account, progress=progress)
            undoable = latest_undoable(journal_dir)
            marker = read_marker(root)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("ace.scan", exc)
            self.app.call_from_thread(self._scan_failed, f"The scan failed: {exc}")
            return
        self.app.call_from_thread(self._scanned, scan, undoable, marker)

    def _scan_progress(self, current: int, total: int, name: str) -> None:
        if not self.is_attached:
            return
        self.query_one("#scan-progress", ProgressBar).update(total=total or None, progress=current)
        self.query_one("#scan-label", Static).update(Text(f"Reading SavedVariables: {name}" if name else
                                                          "Reading SavedVariables"))

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        if not self.is_attached:
            return
        self._show_scan_progress(False)
        self.summary_text = message
        self.query_one("#summary", Static).update(Text(message))
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, scan: ScanResult, undoable: Path | None, marker: Marker | None) -> None:
        self._scanning = False
        self.scan, self.undoable, self.marker = scan, undoable, marker
        self.staging = Staging.from_scan(scan, locked=self.locked)
        self.ticked.clear()
        if not self.is_attached:
            return
        self._show_scan_progress(False)
        self.refresh_view()
        self._refresh_buttons()
        self.query_one("#profiles", Tree).focus()
        if marker is not None:
            self.offer_recovery(marker)

    def offer_recovery(self, marker: Marker) -> None:
        """An Apply did not finish. Task 14 shows the recovery popup here."""
        self.notify(f"An earlier change to {marker.flavor} did not finish. Its WTF backup and original files are "
                    "kept.", title="Unfinished change", severity="warning", timeout=15)

    # --- tree ------------------------------------------------------------------------------------
    def _schedule_rebuild(self) -> None:
        """Show that the list is being rebuilt, then rebuild once that has been drawn. Changes made before the
        rebuild runs are folded into it."""
        if self.scan is None:
            return
        self.query_one("#profiles", Tree).loading = True
        self.query_one("#summary", Static).update(Text("Updating the list…", style=BUSY_STYLE))
        if not self._rebuild_pending:
            self._rebuild_pending = True
            self.call_after_refresh(self._run_scheduled_rebuild)

    def _run_scheduled_rebuild(self) -> None:
        self._rebuild_pending = False
        try:
            self.refresh_view()
        finally:
            self.query_one("#profiles", Tree).loading = False

    def _walk_tree(self) -> Iterator[TreeNode]:
        stack = [self.query_one("#profiles", Tree).root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children)

    def refresh_view(self) -> None:
        """Rebuild the tree and the bottom line from the scan, the staged changes and the filters, keeping ticks,
        expansion and the highlighted node."""
        if self.scan is None or self.staging is None or not self.is_attached:
            return
        tree = self.query_one("#profiles", Tree)
        if self._builder is not None:  # remember what the user opened and closed
            for node in self._walk_tree():
                if node.data is not None and node.allow_expand:
                    self._expanded[ident(node.data)] = node.is_expanded
        cursor = tree.cursor_node
        cursor_id = ident(cursor.data) if cursor is not None and cursor.data is not None else None
        self.filters.view = self.view
        self._builder = TreeBuilder(self.scan, self.staging, self.filters, scope_label=self.scope_label,
                                    locked=self.locked, blacklisted=self._blacklisted, expanded=self._expanded,
                                    warning_style=theme_colour(self.app, "warning"))
        self._builder.build(tree)
        for node in self._walk_tree():
            node.set_label(self._label(node.data))
        tree.get_node_at_line(0)  # lay the lines out now, so the cursor (and move_cursor) find the new nodes
        if cursor_id is not None:
            target = next((n for n in self._walk_tree() if n.data is not None and ident(n.data) == cursor_id), None)
            if target is not None and target.line >= 0:
                tree.move_cursor(target)
        self._update_summary()

    def _tick_keys(self, node: TreeNode | None) -> tuple:
        if node is None or node.data is None or self._builder is None:
            return ()
        return self._builder.keys.get(id(node.data), ())

    def _label(self, data) -> Text:
        builder = self._builder
        if builder is None or data is None:
            return Text("")
        body = builder.bodies.get(id(data), Text(""))
        keys = builder.keys.get(id(data), ())
        if not keys:
            return Text.assemble("  ", body)
        mark = tick_mark(keys, NotTicked(self.ticked), success=theme_colour(self.app, "success"))
        return Text.assemble(mark, body)

    def _refresh_labels(self, node: TreeNode | None = None) -> None:
        relabel_branch(self.query_one("#profiles", Tree), node, self._label, skip=READ_ONLY)
        self._update_summary()

    def _update_summary(self) -> None:
        if self.scan is None or self.staging is None or not self.is_attached:
            return
        summary = self.staging.summary()
        profiles, chars = counts(self.ticked)
        self.summary_text = selection_text(profiles, chars, summary, len(self.scan.warnings))
        self.query_one("#summary", Static).update(Text(self.summary_text))
        self.query_one("#staged", Static).update(Text(staged_text(summary)))
        self._refresh_buttons()

    # --- selection -----------------------------------------------------------------------------------
    def _selected(self, kind: str) -> dict[DbKey, list[str]]:
        keys = self.ticked or set(self._tick_keys(self.query_one("#profiles", Tree).cursor_node))
        out: dict[DbKey, list[str]] = {}
        for key in sorted((k for k in keys if k[0] == kind), key=lambda k: (str(k[1].path), k[1].sv_name, k[2])):
            out.setdefault(key[1], []).append(key[2])
        return out

    def selected_profiles(self) -> dict[DbKey, list[str]]:
        """The ticked profiles, or the highlighted node's when nothing is ticked."""
        return self._selected("p")

    def selected_chars(self) -> dict[DbKey, list[str]]:
        """The ticked characters, or the highlighted node's when nothing is ticked."""
        return self._selected("c")

    # --- ticks -----------------------------------------------------------------------------------
    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Checkbox):
            focused.toggle()
            return
        if isinstance(focused, Button):  # Space activates the focused button, never the tree
            focused.press()
            return
        if isinstance(focused, Input):  # Space is priority-bound: type it into the search box
            focused.insert_text_at_cursor(" ")
            return
        if not isinstance(focused, Tree) or not self.idle:
            return
        node = self.query_one("#profiles", Tree).cursor_node
        keys = self._tick_keys(node)
        if node is None or not keys:
            return
        check = any(k not in self.ticked for k in keys)
        if check:
            self.ticked.update(keys)
        else:
            self.ticked.difference_update(keys)
        log_event("ui.item_toggled", screen="ace_review", key=str(ident(node.data)), checked=check)
        self._refresh_labels(node)

    def action_select_all(self) -> None:
        tree = self.query_one("#profiles", Tree)
        self.ticked.update(self._tick_keys(tree.root))  # visible keys only: hidden ones stay as they are
        log_event("ui.selection", screen="ace_review", control="select_all", value=True)
        self._refresh_labels()

    def action_select_none(self) -> None:
        self.ticked.clear()
        log_event("ui.selection", screen="ace_review", control="select_none", value=True)
        self._refresh_labels()

    # --- filters ---------------------------------------------------------------------------------
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        widget_id = event.checkbox.id or ""
        if widget_id in ("view-addon", "view-character"):
            self._set_view("addon" if (widget_id == "view-addon") == event.value else "character")
            return
        name = SHOW_FILTERS.get(widget_id)
        if name is None:
            return
        setattr(self.filters, name, event.value)
        log_event("ui.selection", screen="ace_review", control=name, value=event.value)
        self._schedule_rebuild()

    def _set_view(self, view: str) -> None:
        """The two View boxes act as a pair: exactly one is ticked."""
        self.query_one("#view-addon", Ka0sCheckbox).value = view == "addon"
        self.query_one("#view-character", Ka0sCheckbox).value = view == "character"
        if view == self.view:
            return
        self.view = view
        log_event("ui.selection", screen="ace_review", control="view", value=view)
        self._schedule_rebuild()

    def action_switch_view(self) -> None:
        self._set_view("character" if self.view == "addon" else "addon")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.filters.search = event.value
            self._schedule_rebuild()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#profiles", Tree).focus()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    # --- blacklist -------------------------------------------------------------------------------
    def _addon_at_cursor(self) -> str | None:
        node = self.query_one("#profiles", Tree).cursor_node
        while node is not None and node.data is not None:
            data = node.data
            if data[0] == "addon":
                return data[1].file.addon
            if len(data) > 1 and isinstance(data[1], DbKey) and self.staging is not None:
                return self.staging.state(data[1]).file.addon
            node = node.parent
        self.notify("Highlight an addon (or something inside one) first.")
        return None

    def action_blacklist(self) -> None:
        if not self.idle or self.scan is None:
            return
        addon = self._addon_at_cursor()
        if addon is None:
            return
        self.settings = load_settings(self.tool_cfg)
        listed = is_blacklisted(self.settings.blacklist, addon)
        if listed:
            self.settings.blacklist = [n for n in self.settings.blacklist if n.casefold() != addon.casefold()]
        else:
            self.settings.blacklist = parse_blacklist(", ".join([*self.settings.blacklist, addon]))
            self.ticked = {k for k in self.ticked if self.staging is None
                           or self.staging.state(k[1]).file.addon.casefold() != addon.casefold()}
        save_settings(self.tool_cfg, self.settings, source="review")
        log_event("ace.blacklist_changed", addon=addon, blacklisted=not listed)
        self.notify(f"{addon} is {'no longer' if listed else 'now'} on the blacklist.")
        self._schedule_rebuild()

    def action_unlock(self) -> None:
        if not self.idle or self.scan is None:
            return
        addon = self._addon_at_cursor()
        if addon is None:
            return
        if not self._blacklisted(addon):
            self.notify(f"{addon} is not blacklisted.")
            return
        name = addon.casefold()
        unlocked = name not in self.unlocked
        if unlocked:
            self.unlocked.add(name)
        else:
            self.unlocked.discard(name)
            self.ticked = {k for k in self.ticked if self.staging is None
                           or self.staging.state(k[1]).file.addon.casefold() != name}
        log_event("ace.unlocked", addon=addon, unlocked=unlocked)
        self.notify(f"{addon} is {'unlocked for this session' if unlocked else 'locked again'}.")
        self._schedule_rebuild()

    # --- staging and runs (Tasks 13 and 14) -------------------------------------------------------
    def _not_yet(self, what: str) -> None:
        self.notify(f"{what} is not available yet.")

    def action_delete(self) -> None:
        self._not_yet("Delete")

    def action_assign(self) -> None:
        self._not_yet("Assign")

    def action_rename(self) -> None:
        self._not_yet("Rename")

    def action_copy(self) -> None:
        self._not_yet("Copy")

    def action_remove_leftovers(self) -> None:
        self._not_yet("Remove leftover characters")

    def action_more(self) -> None:
        self._not_yet("Quick actions")

    def action_discard(self) -> None:
        self._not_yet("Discard")

    def action_apply(self) -> None:
        self._not_yet("Apply")

    def action_dry_run(self) -> None:
        self._not_yet("Dry run")

    def action_undo(self) -> None:
        self._not_yet("Undo")

    # --- leaving -------------------------------------------------------------------------------
    def action_leave(self, choice: str) -> None:
        if not self.app.busy:
            self.dismiss(choice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {"btn-apply": self.action_apply, "btn-dry-run": self.action_dry_run,
                   "btn-rescan": self.action_rescan, "btn-undo": self.action_undo}
        action = actions.get(event.button.id or "")
        if action is not None:
            event.stop()
            action()
