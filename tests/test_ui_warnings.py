"""The shared warnings view (spec W1): the bottom line's Warnings button (shown only while there are warnings, its
key `!` on it), the WarningsScreen it opens (a tree grouped by flavor, each warning's where and what, the `/` filter,
x / c, Back with Esc) and the host mixin a review mixes in. The tools' own tests drive it on their real screens."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Tree

from tests.fixtures import BASE, TINY, TuiTestCase, assert_keys_on_buttons, settle, submit_filter
from wowtools.core.events import capture_events
from wowtools.core.svfiles import SvScanWarning
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import TREE_HINT
from wowtools.ui.tree_filter import FILTER_HINT, NO_MATCH_TEXT
from wowtools.ui.warnings_view import (WARNINGS_BINDING, WARNINGS_BUTTON_ID, SummaryBar, WarningItem, WarningsHost,
                                       WarningsScreen, scan_warning_items, warnings_label, where_text)
from wowtools.ui.widgets import NavHint, action_kind

ITEMS = [WarningItem("WTF/Account/A/SavedVariables", "cannot read folder: denied", "Retail"),
         WarningItem("WTF/Account/A/Realm/Char/AddOns.txt", "line 3 not understood: 'x'", "Retail"),
         WarningItem("WTF/Account/B", "no character folders", "Classic Era")]


class HostScreen(WarningsHost, Screen[None]):
    LOG_SCREEN = "toy"
    BINDINGS: ClassVar[list[Binding]] = [WARNINGS_BINDING]

    def __init__(self) -> None:
        super().__init__()
        self.items: list[WarningItem] = []

    def compose(self) -> ComposeResult:
        yield SummaryBar("Selected: nothing")
        yield BottomBar()

    def warning_items(self) -> list[WarningItem]:
        return self.items

    def set_items(self, items) -> None:
        self.items = list(items)
        self.refresh_warnings()


class HostApp(App):
    def on_mount(self) -> None:
        self.push_screen(HostScreen())


class HelpersTest(TuiTestCase):
    def test_label_counts_with_the_noun(self):
        self.assertEqual(warnings_label(1, "scan warning"), "⚠ 1 scan warning")
        self.assertEqual(warnings_label(4, "scan warning"), "⚠ 4 scan warnings")

    def test_where_is_inside_the_flavor_folder(self):
        base = Path("/wow/_retail_")
        self.assertEqual(where_text(base / "WTF" / "Account" / "A", base), "WTF/Account/A")
        self.assertEqual(where_text(str(base / "WTF"), base), "WTF")
        self.assertIn("elsewhere", where_text(Path("/elsewhere/x"), base))  # outside: the whole path
        self.assertEqual(where_text(None, base), "")
        self.assertEqual(scan_warning_items([SvScanWarning(base / "WTF" / "B.lua", "bad")], "Retail", base),
                         [WarningItem("WTF/B.lua", "bad", "Retail")])

    def test_scan_warning_items_keep_path_and_message(self):
        items = scan_warning_items([SvScanWarning(Path("/x/Broken.lua"), "not readable Lua"),
                                    SvScanWarning(None, "no folder")], "Retail")
        self.assertEqual([(i.what, i.group) for i in items], [("not readable Lua", "Retail"), ("no folder", "Retail")])
        self.assertIn("Broken.lua", items[0].where)
        self.assertEqual(items[1].where, "")


class WarningsViewTest(TuiTestCase):
    async def test_button_shows_only_with_warnings_and_carries_the_key(self):
        app = HostApp()
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            screen = app.screen
            button = screen.query_one(f"#{WARNINGS_BUTTON_ID}")
            self.assertFalse(button.display)
            screen.set_items(ITEMS)
            await settle(app, pilot)
            self.assertTrue(button.display)
            self.assertEqual(button.label.plain, "⚠ 3 scan warnings (!)")
            self.assertEqual((button.label_text, action_kind(button)), ("Warnings", "navigate"))
            self.assertFalse(button.focusable)
            self.assertGreater(button.region.width, 0)
            self.assertEqual(button.region.y, screen.query_one("#summary").region.y)  # the summary's row
            assert_keys_on_buttons(self, screen)
            screen.set_items([])
            await settle(app, pilot)
            self.assertFalse(button.display)

    async def test_key_and_click_open_the_view_and_esc_returns(self):
        for how in ("key", "click"):
            with self.subTest(how=how):
                app = HostApp()
                async with app.run_test(size=BASE) as pilot:
                    await settle(app, pilot)
                    host = app.screen
                    await pilot.press("exclamation_mark")  # no warnings: nothing opens
                    await settle(app, pilot)
                    self.assertIs(app.screen, host)
                    host.set_items(ITEMS)
                    await settle(app, pilot)
                    with capture_events() as events:
                        if how == "key":
                            await pilot.press("exclamation_mark")
                        else:
                            await pilot.click(f"#{WARNINGS_BUTTON_ID}")
                        await settle(app, pilot)
                    self.assertIsInstance(app.screen, WarningsScreen)
                    self.assertTrue(any(e["event"] == "ui.selection" and e["data"].get("control") == "warnings"
                                        for e in events), events)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertIs(app.screen, host)

    async def test_view_groups_by_flavor_and_shows_where_and_what(self):
        for size in (BASE, TINY):
            with self.subTest(size=size):
                app = HostApp()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    app.push_screen(WarningsScreen("Scan warnings", ITEMS, scope="Toy"))
                    await settle(app, pilot)
                    screen = app.screen
                    tree = screen.query_one("#warnings", Tree)
                    self.assertIs(screen.focused, tree)
                    self.assertIs(tree.cursor_node, tree.root.children[0].children[0])  # the first warning
                    self.assertIn(ITEMS[0].what, str(screen.query_one("#warning-detail").render()))
                    groups = [n for n in tree.root.children]
                    self.assertEqual([str(g.label).split("  ")[0] for g in groups], ["Retail", "Classic Era"])
                    self.assertTrue(all(g.is_expanded for g in groups))
                    leaves = [str(leaf.label) for g in groups for leaf in g.children]
                    self.assertEqual(len(leaves), 3)
                    for item, leaf in zip(ITEMS, leaves):
                        self.assertIn(item.where, leaf)
                        self.assertIn(item.what, leaf)
                    hint = screen.query_one(NavHint).hint
                    self.assertIn(FILTER_HINT + TREE_HINT.removesuffix(" · "), hint)
                    back = screen.query_one("#btn-back")
                    self.assertEqual((back.label_text, back.shortcut, action_kind(back)), ("Back", "escape", "cancel"))
                    assert_keys_on_buttons(self, screen)
                    self.assertIn("3 scan warnings", str(screen.query_one("#warnings-count").render()))
                    self.assertGreater(back.region.width, 0)
                    self.assertLessEqual(back.region.bottom, size[1])

    async def test_the_highlighted_warning_shows_in_full_in_the_left_pane(self):
        app = HostApp()
        async with app.run_test(size=TINY) as pilot:
            await settle(app, pilot)
            app.push_screen(WarningsScreen("Scan warnings", ITEMS))
            await settle(app, pilot)
            screen = app.screen
            tree = screen.query_one("#warnings", Tree)
            tree.move_cursor(tree.root.children[0].children[1])
            await settle(app, pilot)
            detail = str(screen.query_one("#warning-detail").render())
            self.assertEqual(detail.splitlines(), ["Retail", ITEMS[1].where, ITEMS[1].what])
            tree.move_cursor(tree.root.children[0])
            await settle(app, pilot)
            self.assertEqual(str(screen.query_one("#warning-detail").render()), "")

    async def test_ungrouped_warnings_sit_under_the_root(self):
        app = HostApp()
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            app.push_screen(WarningsScreen("Scan warnings", [WarningItem("Interface", "denied")]))
            await settle(app, pilot)
            tree = app.screen.query_one("#warnings", Tree)
            self.assertEqual(len(tree.root.children), 1)
            self.assertIn("denied", str(tree.root.children[0].label))
            self.assertFalse(tree.root.children[0].allow_expand)

    async def test_filter_narrows_and_x_c_expand_collapse(self):
        app = HostApp()
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            app.push_screen(WarningsScreen("Scan warnings", ITEMS))
            await settle(app, pilot)
            screen = app.screen
            tree = screen.query_one("#warnings", Tree)
            submit_filter(screen, "addons.txt")
            await settle(app, pilot)
            self.assertEqual(len(tree.root.children), 1)
            self.assertEqual(len(tree.root.children[0].children), 1)
            submit_filter(screen, "classic")  # a group's name keeps everything in it
            await settle(app, pilot)
            self.assertEqual([len(g.children) for g in tree.root.children], [1])
            submit_filter(screen, "nothing like it")
            await settle(app, pilot)
            self.assertIn(NO_MATCH_TEXT, str(tree.root.children[0].label))
            submit_filter(screen, "")
            await settle(app, pilot)
            tree.focus()
            await pilot.press("c")
            await settle(app, pilot)
            self.assertFalse(any(g.is_expanded for g in tree.root.children))
            await pilot.press("x")
            await settle(app, pilot)
            self.assertTrue(all(g.is_expanded for g in tree.root.children))
            await pilot.press("slash")
            await pilot.pause()
            self.assertIs(screen.focused, screen.filter_input())
            await pilot.press("escape")  # in the box: clears it, stays
            await settle(app, pilot)
            self.assertIs(app.screen, screen)
            await pilot.press("escape")  # in the tree: back
            await settle(app, pilot)
            self.assertIsInstance(app.screen, HostScreen)


if __name__ == "__main__":
    import unittest
    unittest.main()
