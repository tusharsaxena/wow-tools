"""The review screens' shared machinery (spec D9): the tree with its ← key, ticks over a tick model of either
polarity, Space (tick, press, toggle or type), select all / none over the keys the tree shows, leaving, the
running-WoW check in a worker, the debounced rebuild, the scan box and button-id dispatch. A review screen mixes
`ReviewBase` in before `Screen`; a screen with buttons only (no ticks) can take `ButtonActions` alone. A review that
runs the shared SavedVariables pipeline (Ace3, SV Browser) also mixes in `RunActions` (before `ReviewBase`): its
apply / undo / recover plumbing, and `SvRecoveryActions` (before `RunActions`): the recovery of an Apply that did not
finish."""
from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Iterator
from contextlib import nullcontext
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode

from wowtools.core import activity
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import WowInstall, flavor_name, validate_backup_dir
from wowtools.core.sv_apply import Marker
from wowtools.core.sv_events import SvTool
from wowtools.core.sv_report import leave_notice, recovered_notice
from wowtools.core.sv_undo import UndoError, UndoResult
from wowtools.ui.dialogs import BUSY_STYLE, DiscardScreen, ProgressScreen, TwoPaneFocus
from wowtools.ui.widgets import WrapButtonRow

__all__ = ["BLACKLIST_BINDING", "BLACKLIST_KEY", "BLACKLIST_NO_TARGET", "ActionBar", "BarTree", "BlacklistAction",
           "ButtonActions", "NotTicked", "Preflight", "ReviewBase", "ReviewTree", "RunActions",
           "ScheduledRebuild", "SvRecoveryActions", "TickActions", "TickModel", "blacklist_toast"]

WowCheck = Callable[[], "list[str] | None"]


class ReviewTree(Tree):
    """A review screen's tree. ← jumps to the left pane (`screen.focus_filters`) instead of scrolling sideways."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class BarTree(ReviewTree):
    """A review tree with an action bar under it (#tree-actions, an ActionBar: the Ace3 review, the SV Browser): ↓
    on the last line goes on to the bar's first button that can take focus."""

    BAR_SELECTOR: ClassVar[str] = "#tree-actions"
    BINDINGS: ClassVar[list[Binding]] = [Binding("down", "down_or_bar", "Down", show=False)]

    def action_down_or_bar(self) -> None:
        if self.cursor_line >= self.last_line:
            button = next((b for b in self.screen.query(f"{self.BAR_SELECTOR} Button").results(Button)
                           if b.focusable), None)
            if button is not None:
                button.focus()
        else:
            self.action_cursor_down()


class ActionBar(WrapButtonRow):
    """The action bar under a review's tree (BarTree). ↑ goes back to the tree, from any of its rows."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("up", "screen.focus_tree", "Tree", show=False)]

    def on_mount(self) -> None:
        """A screen that keeps its toasts above the bar (place_toasts) moves them after every layout: the bar moves
        and wraps onto more or fewer rows as the screen settles or is resized."""
        place = getattr(self.screen, "place_toasts", None)
        if place is not None:
            self.screen.screen_layout_refresh_signal.subscribe(self, lambda _screen: place())


def lift_toasts(screen: Screen, above: int) -> None:
    """Show the screen's notifications (Textual's toast rack, docked at the bottom) `above` rows up from the
    bottom, so a toast never covers an action bar or the lines under it."""
    margin = (0, 0, max(above, 1), 0)
    for toasts in screen.query("#textual-toastrack"):
        if tuple(toasts.styles.margin) != margin:  # setting it lays the screen out again
            toasts.styles.margin = margin


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

    def no_ticks_here(self) -> bool:
        """True when the tree shows nothing that can be ticked (a screen with views that have none says why: Space,
        a and n stay keys, as on every review)."""
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
        if not isinstance(focused, Tree) or self.ticks_frozen() or self.no_ticks_here():
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
        if self.ticks_frozen() or self.no_ticks_here():
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
            self.app.refresh_bindings()  # s and h are off while the check runs (WowToolsApp.help_allowed)

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
    _progress_screen: Screen | None = None  # the run's progress popup, while it is open (_close_progress)

    def _close_progress(self) -> None:
        """Close the run's progress popup (_progress_screen) if it is still the screen shown."""
        screen, self._progress_screen = self._progress_screen, None
        if screen is not None and self.app.screen is screen:
            self.app.pop_screen()

    def ticks_frozen(self) -> bool:
        """The selection is frozen while the running-programs check runs (a screen may freeze it longer)."""
        return self._checking

    def discard_question(self) -> tuple[str, str] | None:
        """(title, body) of the question leaving this review asks first, when that would drop work staged and not
        yet written; None leaves at once. Asked by action_leave and by the app's quit (q from any screen)."""
        return None

    def action_leave(self, choice: str) -> None:
        """Dismiss with `choice` ("flavors", "tools", "quit"), never while a run is going on; with work staged
        (discard_question) only once the user says so."""
        if self.app.busy:
            return
        question = self.discard_question()
        if question is None:
            self.dismiss(choice)
            return
        self.app.push_screen(DiscardScreen(*question), lambda ok: self.dismiss(choice) if ok else None)

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


BLACKLIST_KEY = "b"
# Shown on no footer: a screen that wants `b` listed binds its own Binding(BLACKLIST_KEY, "blacklist", ..., show=True).
BLACKLIST_BINDING = Binding(BLACKLIST_KEY, "blacklist", "Blacklist", show=False)
BLACKLIST_NO_TARGET = "Highlight an addon (or something inside one) first."


def blacklist_toast(flavor: str, addon: str, listed: bool) -> str:
    """What `b` says once it has toggled (flavor folder, addon)."""
    return f"{addon} ({flavor_name(flavor)}) is {'now' if listed else 'no longer'} on the blacklist."


class BlacklistAction:
    """The tree's `b` (spec B1), mixed into a review whose tool keeps a blacklist of (flavor folder, addon) pairs
    (core/blacklist.py). Bind BLACKLIST_BINDING. The screen supplies `blacklist_target(node)` (the highlighted
    node's (flavor folder, addon), or None for a node with no single addon) and `toggle_blacklist(flavor, addon)`
    (its own list, saved and logged its own way; True when the pair is now listed). `b` then says so in the shared
    toast and calls `blacklist_changed()` (by default a rebuild). What being listed means stays the tool's."""

    TREE_SELECTOR: ClassVar[str]

    def blacklist_ready(self) -> bool:
        """`b` may act now (not while scanning or running): the screen narrows it."""
        return True

    def blacklist_target(self, node: TreeNode | None) -> tuple[str, str] | None:
        raise NotImplementedError

    def toggle_blacklist(self, flavor: str, addon: str) -> bool:
        raise NotImplementedError

    def blacklist_changed(self) -> None:
        """After a toggle: show the change (the tree's labels, ticks and counts)."""
        self._schedule_rebuild()

    def action_blacklist(self) -> None:
        """b: blacklist the highlighted addon in its flavor, or take it off."""
        if not self.blacklist_ready():
            return
        target = self.blacklist_target(self.query_one(self.TREE_SELECTOR, Tree).cursor_node)
        if target is None:
            self.notify(BLACKLIST_NO_TARGET)
            return
        flavor, addon = target
        listed = self.toggle_blacklist(flavor, addon)
        self.notify(blacklist_toast(flavor, addon, listed))
        self.blacklist_changed()


class RunActions:
    """The apply / undo / recover plumbing of a review on the shared SavedVariables pipeline (Ace3, SV Browser),
    mixed in before ReviewBase (it uses Preflight and _close_progress):

    - _check_wow(check, then): the running-WoW check in a worker, then `then(running)` on the UI thread;
    - _refused_while_running(running, alerts): refuse (and say so, logging <prefix>.wow_running) while WoW runs,
      or add an alert to the confirm when the check could not run;
    - _backup_dir_refused(): refuse when the backup folder in the settings is not allowed;
    - start_run(progress, work, done, ...): the app is busy, the progress popup opens and `work()` runs in a worker
      inside activity.running(); then the popup closes and `done(result)` runs on the UI thread, or the failure is
      logged (<prefix>.<name>) and shown (_run_failed).

    The screen supplies SV_TOOL (its event prefix), `cfg` (the suite config: wow_path), run_backup_dir() (the
    backup folder in its settings now), _refresh_buttons() and _mark_stale() (the files changed under the scan)."""

    SV_TOOL: ClassVar[SvTool]

    def run_backup_dir(self) -> Path | None:
        """The tool's backup folder setting as saved now (None: the default)."""
        raise NotImplementedError

    def _refresh_buttons(self) -> None:
        """Enable or disable the buttons for the current state (busy, pending changes)."""

    def _mark_stale(self) -> None:
        """The files changed under this scan (a run that failed half way)."""
        raise NotImplementedError

    # --- before a run --------------------------------------------------------------------------
    def _check_wow(self, check: WowCheck, then: Callable[[list[str] | None], None]) -> None:
        """The running-WoW check (ReviewBase.run_preflight, in a worker: it can take seconds), then `then` with its
        answer on the UI thread: process names, [] when none run, None when it could not run."""
        self.run_preflight(check, lambda running, _extra: then(running))

    def _refused_while_running(self, running: list[str] | None, alerts: list[str]) -> bool:
        """True (and say so) when WoW runs; adds an alert when the check could not run."""
        if running:
            log_event(self.SV_TOOL.event("wow_running"), action="preflight", running=running)
            self.notify(f"WoW is running ({', '.join(running)}). Close it first: it would overwrite the changes.",
                        title="WoW is running", severity="error", timeout=15)
            return True
        if running is None:
            alerts.append("Could not check whether WoW is running; close it before you go on.")
        return False

    def _backup_dir_refused(self) -> bool:
        """True (and say so) when the backup folder in the settings is not allowed (it may have been edited by
        hand in the cfg): checked before anything is written to it, as on save."""
        wow_path = self.cfg.wow_path
        if wow_path is None:
            return False
        problem = validate_backup_dir(self.run_backup_dir(), WowInstall(wow_path))
        if problem:
            self.notify(f"{problem} Fix the folder in settings (s).", title="Backup folder not allowed",
                        severity="error", timeout=15)
        return bool(problem)

    # --- the run -------------------------------------------------------------------------------
    def start_run(self, progress: ProgressScreen, work: Callable[[], Any], done: Callable[[Any], None], *,
                  name: str, failure: str, stale_on_crash: bool,
                  expected: tuple[type[BaseException], ...] = (), writes: bool = True) -> None:
        """Run `work()` (apply, undo, recover; a search with `writes=False`) in a worker with `progress` open over
        the review. An `expected` error (refused before anything was written) is shown as its message; any other is
        shown as "<failure>: <type>: <message>" and, with `stale_on_crash`, marks the scan stale. Both are logged as
        errors at <prefix>.<name>. Work that `writes` runs inside activity.running() (file-changing work)."""
        self.app.busy = True
        self._refresh_buttons()
        self._progress_screen = progress
        self.app.push_screen(progress)
        self.run_worker(lambda: self._run_worker(progress, work, done, name, failure, stale_on_crash, expected,
                                                 writes), thread=True, exclusive=True, group="run")

    def _run_worker(self, progress: ProgressScreen, work: Callable[[], Any], done: Callable[[Any], None],
                    name: str, failure: str, stale_on_crash: bool,
                    expected: tuple[type[BaseException], ...], writes: bool = True) -> None:
        where = self.SV_TOOL.event(name)
        try:
            with activity.running() if writes else nullcontext():
                result = work()
        except expected as exc:  # WowRunning included: refused before anything was written
            log_exception(where, exc)
            self.app.call_from_thread(self._run_failed, str(exc), False)
            return
        except Exception as exc:  # noqa: BLE001 - shown and logged, never a crash
            log_exception(where, exc)
            self.app.call_from_thread(self._run_failed, f"{failure}: {type(exc).__name__}: {exc}", stale_on_crash)
            return
        progress.finish_all()  # the run ended: the board ends at m of m
        self.app.call_from_thread(self._run_done, done, result)

    def _end_run(self) -> None:
        """The run is over: not busy, the progress popup closed."""
        self.app.busy = False
        self._close_progress()

    def _run_done(self, done: Callable[[Any], None], result: Any) -> None:
        self._end_run()
        done(result)

    def _run_failed(self, message: str, stale: bool) -> None:
        self._end_run()
        if stale:  # files may have changed: the scan no longer matches them
            self._mark_stale()
        self._refresh_buttons()
        self.notify(message, severity="error", timeout=15)


class SvRecoveryActions:
    """The recovery of a SavedVariables Apply that did not finish (its crash marker was found by the scan), mixed
    in before RunActions by a review on the shared pipeline (Ace3, SV Browser; F-007):

    - offer_recovery(marker): log <prefix>.recovery_offered and open the tool's unfinished-run popup;
    - Leave as is: drop the marker (core sv_undo.leave), or say it is still there;
    - Put the originals back: the backup-folder and running-WoW checks of the marker's flavor, then the tool's
      recover in start_run (RUN_PROGRESS popup), then the notice (sv_report.recovered_notice) and recovery_done().

    Closed without a choice, refused, or stopped, the marker stays: it is offered again at the next scan or Apply.
    The screen supplies `marker`, RUN_PROGRESS (its run progress popup), recovery_screen(marker) (the popup),
    recovery_root() (the tool folder the marker is settled in), run_leave(marker, root=) and run_recover(marker,
    **kwargs) (the tool's undo.leave and undo.recover), and recovery_done() (read the files again)."""

    RUN_PROGRESS: ClassVar[type[ProgressScreen]]
    marker: Marker | None

    def recovery_screen(self, marker: Marker) -> Screen:
        """The popup that offers the choice (a ui.dialogs.UnfinishedRunScreen)."""
        raise NotImplementedError

    def recovery_root(self) -> Path | None:
        """The tool folder the marker is settled in (None: none, nothing is done)."""
        raise NotImplementedError

    def run_leave(self, marker: Marker, *, root: Path) -> bool:
        """The tool's undo.leave: True when the marker is gone."""
        raise NotImplementedError

    def run_recover(self, marker: Marker, **kwargs: Any) -> UndoResult:
        """The tool's undo.recover (run in the worker)."""
        raise NotImplementedError

    def recovery_done(self) -> None:
        """After the notice: the files were put back (or the marker dropped), read them again."""
        raise NotImplementedError

    def offer_recovery(self, marker: Marker) -> None:
        """An Apply did not finish: offer to put the originals back, or to leave the files as they are."""
        log_event(self.SV_TOOL.event("recovery_offered"), flavor=marker.flavor, files=len(marker.files),
                  started=marker.started)
        self.app.push_screen(self.recovery_screen(marker), lambda choice: self._recovery_chosen(marker, choice))

    def _recovery_chosen(self, marker: Marker, choice: str | None) -> None:
        root = self.recovery_root()
        if root is None or choice not in ("put_back", "leave"):
            return  # closed without a choice: offered again at the next scan or Apply
        if choice == "leave":
            if self.run_leave(marker, root=root):
                self.marker = None
            else:  # the marker stays (another program holds it): offered again, and the user is told why
                message, severity = leave_notice()
                self.notify(message, title="Unfinished change", severity=severity, timeout=15)
            return
        if self._backup_dir_refused():
            return  # the marker stays: offered again
        check = self.check_for([marker.flavor])  # the marker's flavor, which may not be one reviewed
        self._check_wow(check, lambda running: self._after_recover_preflight(marker, root, check, running))

    def _after_recover_preflight(self, marker: Marker, root: Path, check: WowCheck,
                                 running: list[str] | None) -> None:
        if self._refused_while_running(running, []):
            return  # the marker stays: offered again
        if self.cfg.wow_path is None:
            return  # the marker stays: offered again (recovery resolves files under the WoW folder)
        screen = self.RUN_PROGRESS("Putting the originals back", first_stage="undo")
        keep_snapshots = self.cfg.keep_backups
        wow_root, journal_dir = self.cfg.wow_path, self.SV_TOOL.journals.dir(self.cfg.wow_path)
        self.start_run(screen, lambda: self.run_recover(marker, wow_root=wow_root, root=root,
                                                        journal_dir=journal_dir, keep_snapshots=keep_snapshots,
                                                        wow_check=check, progress=screen.report),
                       self._recovered, name="recover", failure="Putting the originals back stopped",
                       stale_on_crash=True, expected=(UndoError,))

    def _recovered(self, result: UndoResult) -> None:
        if not result.marker_left:
            self.marker = None
        message, severity = recovered_notice(result)
        self.notify(message, title="Unfinished change", severity=severity, timeout=15)
        self.recovery_done()
