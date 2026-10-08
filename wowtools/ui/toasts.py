"""One anchor and one stack for every toast, on every screen (spec L9, STD-7.24).

Textual docks each screen's toast rack (`#textual-toastrack`) at the bottom with one row of margin, so a toast
covered the bottom line, an action bar under a tree, and the Ace3 review's action tip, which was placed on its own.
Here the rack's bottom margin is set to the screen's *floor*: the top of its lowest bars (`FLOOR_SELECTOR`: the
bottom bar, the bottom line, an `ActionBar`, and any widget with the `TOAST_FLOOR` class, such as the Ace3
guidance line over its bar). A popup takes the floor of the screen under it, raised above its own controls
(`CONTROL_SELECTOR`: buttons, fields, boxes, lists) that reach into the toasts' column, so a toast never covers
what is pressed or typed into on it. Toasts stack upward inside the rack, one row apart, as Textual draws them.

A `TipRack` holds a `StackTip` (the Ace3 review's `ActionTip`): a toast-like box that is the stack's lowest member
while shown. It sits on the floor, and the toasts go one row above it, so a tip and a toast never overlap.

`install(app)` (called by `Ka0sApp.on_mount`) places them on every screen the app shows, again after each of the
screen's layouts (a bar that wraps onto another row, a tip shown or hidden, a resize); no screen places its own.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from weakref import WeakSet

from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import App

__all__ = ["CONTROL_SELECTOR", "FLOOR_SELECTOR", "TIP_LAYER_CSS", "TOAST_FLOOR", "StackTip", "TipRack", "install",
           "place_toasts", "toast_floor"]

TOAST_FLOOR = "toast-floor"  # the class of a widget toasts stay above, besides the bars below
FLOOR_SELECTOR = f"BottomBar, SummaryBar, Footer, ActionBar, .{TOAST_FLOOR}"
# What is pressed, typed into or chosen from on a popup: toasts stay above those in their column.
CONTROL_SELECTOR = "Button, Input, TextArea, Checkbox, Switch, Select, RadioSet, OptionList"
# Textual's Toast is 60 columns, at most half the rack's width, at the right of the rack's scrollbar gutter.
TOAST_WIDTH, TOAST_MAX_WIDTH, RACK_GUTTER = 60, 0.5, 2
# The tip's own layer, under Textual's toast layer: it never takes room from the screen's layout (docks are laid
# out per layer). Ka0sApp's CSS adds it to every screen.
TIP_LAYER_CSS = "\nScreen { layers: default toast-tip; }\n"
GAP = 1  # rows between two boxes of the stack (Textual's Toast has margin-top: 1)


class StackTip(Static):
    """A toast-like box at the bottom of the toast stack (in a `TipRack`): the same width and right edge as a
    toast. Its height is known once it is laid out; the screen's layout refresh then places the stack again."""

    DEFAULT_CSS = """
    StackTip { visibility: visible; width: 60; max-width: 50%; height: auto; padding: 1 1;
               background: $panel-lighten-1; border-left: outer $accent; }
    """


class TipRack(Vertical):
    """Holds a screen's `StackTip`, docked at the bottom on the toast-tip layer and aligned right as Textual's toast
    rack is; `place_toasts` sets its bottom margin to the floor. Show or hide it with `display`."""

    DEFAULT_CSS = """
    TipRack { layer: toast-tip; dock: bottom; width: 1fr; height: auto; align: right bottom; visibility: hidden;
              display: none; overflow-y: scroll; }
    """


def _bars_floor(screen: Screen) -> int:
    """Rows between the bottom of `screen` and the top of its lowest bars (at least 1). A popup without bars uses
    the screen under it (popups cover the whole screen, so the rows are the same)."""
    stack = list(screen.app.screen_stack)
    index = stack.index(screen) if screen in stack else len(stack) - 1
    for shown in reversed(stack[:index + 1] or [screen]):
        tops = [w.region.y for w in shown.query(FLOOR_SELECTOR) if w.display and w.region.height]
        if tops:
            return max(screen.size.height - min(tops), 1)
        if not isinstance(shown, ModalScreen):
            break
    return 1


def _controls_floor(screen: Screen) -> int:
    """On a popup: rows between the bottom of `screen` and the top of its highest control that reaches into the
    toasts' column (the right `TOAST_WIDTH` columns, at most half the width); 0 on a screen or without one. Only
    the shown popup counts: the ones under it cannot be pressed."""
    if not isinstance(screen, ModalScreen):
        return 0
    width, height = screen.size
    inner = width - RACK_GUTTER
    left = inner - min(TOAST_WIDTH, int(inner * TOAST_MAX_WIDTH))
    tops = [w.region.y for w in screen.query(CONTROL_SELECTOR)
            if w.display and w.region.height and w.region.right > left]
    return height - min(tops) if tops else 0


def toast_floor(screen: Screen) -> int:
    """Rows the toasts stand above on `screen`: its lowest bars (`_bars_floor`), and on a popup its controls in the
    toasts' column (`_controls_floor`), whichever is higher."""
    return max(_bars_floor(screen), _controls_floor(screen))


def _set_bottom_margin(widget, rows: int) -> None:
    margin = (0, 0, rows, 0)
    if tuple(widget.styles.margin) != margin:  # setting it lays the screen out again
        widget.styles.margin = margin


def place_toasts(screen: Screen) -> None:
    """Put `screen`'s tip (when shown) on the floor and its toast rack above it (or on the floor)."""
    if not screen.is_attached or not screen.is_running:
        return
    above = toast_floor(screen)
    for rack in screen.query(TipRack):
        _set_bottom_margin(rack, above)
        if rack.display:
            # the rack is invisible and has no region: its tips' laid-out heights. The rack takes exactly that
            # height: its own `auto` height can be a row short of a tip that wraps at the width it gets (its
            # scrollbar gutter), and the tip would then hang over the floor.
            height = sum(tip.outer_size.height for tip in rack.query(StackTip) if tip.display)
            current = rack.styles.height.cells if rack.styles.height is not None else None  # None: auto
            if current != (height or None):  # set only on a change: setting it lays the screen out again
                rack.styles.height = height or "auto"
            if height:
                above += height + GAP
    for toasts in screen.query("#textual-toastrack"):
        _set_bottom_margin(toasts, above)


_placed: WeakSet[Screen] = WeakSet()


def _watch(screen: Screen) -> None:
    """Place the toasts of a screen the app now shows, and again after each of its layouts (subscribed once per
    screen, by the app, which is running whether the screen has started yet or not)."""
    if screen not in _placed:
        _placed.add(screen)
        screen.screen_layout_refresh_signal.subscribe(screen.app, place_toasts)
    place_toasts(screen)


def install(app: App) -> None:
    """Place the toasts of every screen `app` shows (Ka0sApp.on_mount)."""
    app.screen_change_signal.subscribe(app, _watch)
    if app.screen_stack:
        _watch(app.screen)
