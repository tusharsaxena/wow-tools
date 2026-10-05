"""The review screens' shared machinery (spec D9): the tree with its ← key, ticks over a tick model of either
polarity, Space (tick, press, toggle or type), select all / none over the keys the tree shows, leaving, the
running-WoW check in a worker, the debounced rebuild, the scan box and button-id dispatch. A review screen mixes
`ReviewBase` in before `Screen`; a screen with buttons only (no ticks) can take `ButtonActions` alone."""
from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Iterator
from typing import Any, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Button, Checkbox, Input, ProgressBar, Static, Tree

from wowtools.core.events import log_event, log_exception
from wowtools.ui.dialogs import BUSY_STYLE, TwoPaneFocus

__all__ = ["ButtonActions", "NotTicked", "Preflight", "ReviewBase", "ReviewTree", "ScheduledRebuild", "TickActions",
           "TickModel"]

WowCheck = Callable[[], "list[str] | None"]


class ReviewTree(Tree):
    """A review screen's tree. ← jumps to the left pane (`screen.focus_filters`) instead of scrolling sideways."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class NotTicked:
    """The keys not in `ticked`, as tick_mark's `unchecked` collection (without listing every key)."""

    def __init__(self, ticked: Collection[Hashable]) -> None:
        self.ticked = ticked

    def __contains__(self, key: object) -> bool:
        return key not in self.ticked

    def __iter__(self) -> Iterator:
        return iter(())

    def __len__(self) -> int:
        return 0


class TickModel:
    """Ticks kept in one set of keys, of either polarity: the ticked keys (nothing ticked by default: the Ace3
    review, the blacklist) or the unticked ones (everything ticked by default: the WTF Cleaner, the Screenshot
    Organizer, Interface Backup). The set is changed in place, never replaced, so the screen's own attribute stays
    the model's."""

    def __init__(self, keys: set, *, ticked: bool) -> None:
        self.keys = keys
        self.stores_ticked = ticked

    @classmethod
    def of_ticked(cls, keys: set) -> TickModel:
        return cls(keys, ticked=True)

    @classmethod
    def of_unchecked(cls, keys: set) -> TickModel:
        return cls(keys, ticked=False)

    def is_ticked(self, key: Hashable) -> bool:
        return (key in self.keys) == self.stores_ticked

    def tick(self, keys: Iterable[Hashable]) -> None:
        if self.stores_ticked:
            self.keys.update(keys)
        else:
            self.keys.difference_update(keys)

    def untick(self, keys: Iterable[Hashable]) -> None:
        if self.stores_ticked:
            self.keys.difference_update(keys)
        else:
            self.keys.update(keys)

    def toggle(self, keys: Iterable[Hashable]) -> bool:
        """Tick them all when any is unticked, else untick them all. True when they were ticked."""
        keys = list(keys)
        check = any(not self.is_ticked(k) for k in keys)
        (self.tick if check else self.untick)(keys)
        return check

    def ticked_among(self, keys: Iterable[Hashable]) -> list[Hashable]:
        """The ticked ones of these keys (e.g. how many ticked items a filter hides)."""
        return [k for k in keys if self.is_ticked(k)]

    @property
    def unticked(self) -> Collection[Hashable]:
        """The unticked keys, as tick_mark's `unchecked` argument."""
        return NotTicked(self.keys) if self.stores_ticked else self.keys


class ButtonActions:
    """on_button_pressed for a screen whose buttons each do what an action does: BUTTON_ACTIONS maps a button id to
    the action's name (`"btn-clean": "clean"` calls action_clean). Other buttons are left to bubble."""

    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {}

    def on_button_pressed(self, event: Button.Pressed) -> None:
        name = self.BUTTON_ACTIONS.get(event.button.id or "")
        if name is not None:
            event.stop()
            getattr(self, f"action_{name}")()


class TickActions:
    """Space and a / n on a review tree (bind them with `space` priority, `a` and `n`). Space ticks or unticks the
    highlighted node, presses a focused button, toggles a focused checkbox, or types a space into a focused input
    (Space is priority-bound, so an input would never get it). Select all / none act on `shown_tick_keys()` only:
    the screen's keys (`all_tick_keys()`) narrowed by `filter_keys()`, the one place a filter hooks in; Space narrows
    a node's keys by it too (a group ticks only what the filter shows). Ticks hidden by it stay as they are.

    A screen supplies TREE_SELECTOR, LOG_SCREEN (the `screen` of its ui events), tick_model(), node_tick_keys(node),
    tick_log_key(node, keys) and _refresh_labels(node=None); and, if it needs them, all_tick_keys(),
    select_all_keys(), select_none_keys() and ticks_frozen()."""

    TREE_SELECTOR: ClassVar[str] = "Tree"
    LOG_SCREEN: ClassVar[str] = "review"

    def tick_model(self) -> TickModel:
        raise NotImplementedError

    def node_tick_keys(self, node) -> Collection[Hashable]:
        """The keys a tick on this node covers (none for a read-only or empty node)."""
        raise NotImplementedError

    def tick_log_key(self, node, keys: Collection[Hashable]) -> str:
        """The `key` of the ui.item_toggled event for a tick on this node."""
        raise NotImplementedError

    def _refresh_labels(self, node=None) -> None:
        raise NotImplementedError

    def all_tick_keys(self) -> Collection[Hashable]:
        """Every key the screen can tick (the root's, by default). A screen whose tree loads children on expand
        works them out from its model."""
        return self.node_tick_keys(self.query_one(self.TREE_SELECTOR, Tree).root)

    def filter_keys(self, keys: Collection[Hashable]) -> Collection[Hashable]:
        """The keys a filter lets through (all of them until a filter is set)."""
        return keys

    def shown_tick_keys(self) -> Collection[Hashable]:
        """The keys select all / none act on: every key, narrowed by the filter."""
        return self.filter_keys(self.all_tick_keys())

    def select_all_keys(self) -> Collection[Hashable]:
        """The keys select all ticks: the shown ones, unless some keep their own state."""
        return self.shown_tick_keys()

    def select_none_keys(self) -> Collection[Hashable]:
        """The keys select none unticks: the shown ones."""
        return self.shown_tick_keys()

    def ticks_frozen(self) -> bool:
        """True while ticks must not change (a scan or a running-programs check)."""
        return False

    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Checkbox):
            focused.toggle()
            return
        if isinstance(focused, Button):  # Space activates the focused button, never the tree
            focused.press()
            return
        if isinstance(focused, Input):  # Space is priority-bound: type it into the input
            focused.insert_text_at_cursor(" ")
            return
        if not isinstance(focused, Tree) or self.ticks_frozen():
            return
        node = self.query_one(self.TREE_SELECTOR, Tree).cursor_node
        if node is None or node.data is None:
            return
        keys = list(self.filter_keys(self.node_tick_keys(node)))  # a group: only what the filter shows
        if not keys:
            return
        checked = self.tick_model().toggle(keys)
        log_event("ui.item_toggled", screen=self.LOG_SCREEN, key=self.tick_log_key(node, keys), checked=checked)
        self._refresh_labels(node)

    def action_select_all(self) -> None:
        self._select(True)

    def action_select_none(self) -> None:
        self._select(False)

    def _select(self, tick: bool) -> None:
        if self.ticks_frozen():
            return
        model = self.tick_model()
        if tick:
            model.tick(list(self.select_all_keys()))
        else:
            model.untick(list(self.select_none_keys()))
        log_event("ui.selection", screen=self.LOG_SCREEN, control="select_all" if tick else "select_none",
                  value=True)
        self._refresh_labels()


class Preflight:
    """The running-programs check before a confirm (PowerShell or tasklist can take seconds: never on the UI
    thread). run_preflight(check, then, extra) runs check() and extra() in a worker, then calls
    then(running, extra_result) on the UI thread if the screen is still the one shown. A failed check or extra is
    "unknown" (None). `_checking` is up meanwhile; _checking_changed() lets the screen lock its controls, and the
    summary says PREFLIGHT_TEXT until _update_summary() puts the selection back."""

    PREFLIGHT_TEXT: ClassVar[str] = "Checking for running programs…"
    _checking = False

    def _update_summary(self) -> None:
        raise NotImplementedError

    def _checking_changed(self) -> None:
        """Called when the check starts and ends (while attached): disable or enable what it locks."""

    def _set_checking(self, checking: bool) -> None:
        self._checking = checking
        if self.is_attached:
            self._checking_changed()

    def run_preflight(self, check: WowCheck, then: Callable[[list[str] | None, Any], None],
                      extra: Callable[[], Any] | None = None) -> None:
        self._set_checking(True)
        self.query_one("#summary", Static).update(Text(self.PREFLIGHT_TEXT, style=BUSY_STYLE))
        self.run_worker(lambda: self._preflight_worker(check, extra, then), thread=True,
                        group="preflight")

    def _preflight_worker(self, check: WowCheck, extra: Callable[[], Any] | None,
                          then: Callable[[list[str] | None, Any], None]) -> None:
        running = result = None
        try:
            running = check()
        except Exception as exc:  # noqa: BLE001 - a failed check is "unknown", as when PowerShell is missing
            log_exception("preflight", exc)
        if extra is not None:
            try:
                result = extra()
            except Exception as exc:  # noqa: BLE001 - unknown as well
                log_exception("preflight", exc)
        self.app.call_from_thread(self._preflight_done, running, result, then)

    def _preflight_done(self, running: list[str] | None, result: Any,
                        then: Callable[[list[str] | None, Any], None]) -> None:
        self._set_checking(False)
        if not self.is_attached:
            return
        self._update_summary()
        if self.app.screen is not self:
            return  # the user left the screen while the check ran
        then(running, result)


class ScheduledRebuild:
    """A rebuild of the tree that first shows that it runs: the tree's loading indicator and "Updating the list…"
    in the summary, then _rebuild() once that has been drawn. Changes made before it runs are folded into it. The
    screen supplies TREE_SELECTOR, _rebuild() and, if a rebuild needs data first, _can_rebuild()."""

    TREE_SELECTOR: ClassVar[str] = "Tree"
    _rebuild_pending = False  # tests.fixtures.settle waits for it

    def _rebuild(self) -> None:
        raise NotImplementedError

    def _can_rebuild(self) -> bool:
        return True

    def _schedule_rebuild(self) -> None:
        if not self._can_rebuild():
            return
        self.query_one(self.TREE_SELECTOR, Tree).loading = True
        self.query_one("#summary", Static).update(Text("Updating the list…", style=BUSY_STYLE))
        if not self._rebuild_pending:
            self._rebuild_pending = True
            self.call_after_refresh(self._run_scheduled_rebuild)

    def _run_scheduled_rebuild(self) -> None:
        self._rebuild_pending = False
        try:
            self._rebuild()
        finally:
            self.query_one(self.TREE_SELECTOR, Tree).loading = False


class ReviewBase(TickActions, Preflight, ScheduledRebuild, ButtonActions, TwoPaneFocus):
    """A two-pane review screen (TwoPaneFocus: ← / → between the left pane and the tree, x / c): ticks and Space
    (TickActions), the running-programs check (Preflight), the debounced rebuild (ScheduledRebuild), buttons by id
    (ButtonActions), leaving (action_leave, bound as `leave('flavors')` and so on) and the scan box that stands in
    for the tree while a scan runs (#scan-box with #scan-progress and #scan-label: show_scan_box, _scan_progress)."""

    _scanning = False

    def ticks_frozen(self) -> bool:
        """The selection is frozen while the running-programs check runs (a screen may freeze it longer)."""
        return self._checking

    def action_leave(self, choice: str) -> None:
        """Dismiss with `choice` ("flavors", "tools", "quit"), never while a run is going on."""
        if not self.app.busy:
            self.dismiss(choice)

    def show_scan_box(self, scanning: bool, label: str = "") -> None:
        """While scanning, the tree is replaced by an empty progress bar and `label`; after it, the tree is back."""
        self._scanning = scanning
        if scanning:
            self.query_one("#scan-progress", ProgressBar).update(total=None, progress=0)
            self.query_one("#scan-label", Static).update(Text(label))
        for selector in ("#scan-box", "#scan-progress", "#scan-label"):
            self.query_one(selector).display = scanning
        self.query_one(self.TREE_SELECTOR, Tree).display = not scanning

    def _scan_progress(self, current: int, total: int, label: str) -> None:
        """A scan's progress (on the UI thread): the bar (no total yet: it pulses) and what is being read."""
        if not self.is_attached:
            return
        self.query_one("#scan-progress", ProgressBar).update(total=total or None, progress=current)
        self.query_one("#scan-label", Static).update(Text(label))
