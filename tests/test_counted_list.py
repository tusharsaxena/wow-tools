"""Long lists in popups collapse behind a counted tree row (spec L10, STD-7.26): one collapsed row ("⚠ 300 warnings
(Space or click to expand)") whose children group by message, then where (flavor · account), then the items; the
summary lines stay above it, the buttons always stay on screen and the tree scrolls inside the popup."""
from __future__ import annotations

import unittest

from textual.app import App
from textual.screen import Screen
from textual.widgets import Button, Tree

from tests.fixtures import BASE, LARGE, TuiTestCase
from wowtools.core.text import Listed
from wowtools.ui.dialogs import ALERT_STYLE, LISTED_ID, WARNING_MARK, ConfirmScreen, CountedTree, InfoScreen

CREATED = '"Default" does not exist yet; the addon creates it at the next login with its defaults.'
DUAL = "LibDualSpec switches some of these characters' profile by spec; it will override the change at login."
WHERES = ("Retail · ACCOUNT1", "Classic · ACCOUNT2")


def warnings(n: int = 300) -> list[Listed]:
    """n warnings: two messages taking turns, each in two places taking turns, one addon each."""
    return [Listed((CREATED, DUAL)[i % 2], WHERES[(i // 2) % 2], f"Addon{i:03}") for i in range(n)]


class Host(App):
    """A bare app to push one popup on; records what it was dismissed with."""

    def __init__(self, screen: Screen) -> None:
        super().__init__()
        self.first = screen
        self.results: list = []

    def on_mount(self) -> None:
        self.push_screen(self.first, self.results.append)


def labels(nodes) -> list[str]:
    return [str(node.label) for node in nodes]


class CountedTreeTest(unittest.TestCase):
    def test_one_collapsed_counted_row_grouped_by_message_then_where_then_items(self):
        tree = CountedTree(warnings(300))
        self.assertEqual(tree.id, LISTED_ID)
        (top,) = tree.root.children
        self.assertEqual(str(top.label), "⚠ 300 warnings (Space or click to expand)")
        self.assertFalse(top.is_expanded)
        self.assertEqual(labels(top.children), [f"{CREATED} (150)", f"{DUAL} (150)"])
        created = top.children[0]
        self.assertEqual(labels(created.children), [f"{WHERES[0]} (75)", f"{WHERES[1]} (75)"])
        self.assertEqual(labels(created.children[0].children)[:3], ["Addon000", "Addon004", "Addon008"])
        self.assertEqual(labels(created.children[1].children)[:2], ["Addon002", "Addon006"])

    def test_a_missing_where_or_item_drops_that_level(self):
        tree = CountedTree([Listed("Plain"), Listed("Two", item="b"), Listed("Two", item="a"),
                            Listed("Placed", "Retail · A"), Listed("Plain", "Classic · B")], noun="note")
        (top,) = tree.root.children
        self.assertEqual(str(top.label), "⚠ 5 notes (Space or click to expand)")
        plain, two, placed = top.children
        self.assertEqual(str(plain.label), "Plain (2)")
        self.assertEqual(labels(plain.children), ["Classic · B"])  # the entry with no where adds no row
        self.assertEqual(str(two.label), "Two (2)")
        self.assertEqual(labels(two.children), ["b", "a"])  # first seen first, never sorted
        self.assertEqual(labels(placed.children), ["Retail · A"])
        self.assertFalse(placed.children[0].allow_expand)

    def test_a_short_list_opens_whole_once_its_row_is_expanded(self):
        (top,) = CountedTree(warnings(2)).root.children
        self.assertFalse(top.is_expanded)
        self.assertTrue(all(node.is_expanded for node in top.children))
        (top,) = CountedTree(warnings(300)).root.children
        self.assertFalse(any(node.is_expanded for node in top.children))


    def test_an_entry_repeated_exactly_is_listed_once(self):
        """L10 review: the Notes popup used to drop exact repeats; the counted row does too."""
        tree = CountedTree([Listed("A", "Retail · X", "ElvUI"), Listed("A", "Retail · X", "ElvUI"),
                            Listed("A", "Retail · X", "Bags")], noun="note")
        (top,) = tree.root.children
        self.assertEqual(str(top.label), "⚠ 2 notes (Space or click to expand)")
        self.assertEqual(labels(top.children[0].children[0].children), ["ElvUI", "Bags"])

    def test_a_neutral_list_has_no_warning_mark(self):
        (top,) = CountedTree(warnings(2), noun="note", alert=False).root.children
        self.assertEqual(str(top.label), "2 notes (Space or click to expand)")
        self.assertNotIn(WARNING_MARK, top.label.plain)
        self.assertFalse(any(span.style == ALERT_STYLE for span in top.label.spans))

    def test_open_short_opens_the_row_only_when_the_whole_list_fits(self):
        (top,) = CountedTree(warnings(2), open_short=True).root.children
        self.assertTrue(top.is_expanded)
        self.assertEqual(str(top.label), "⚠ 2 warnings (Space or click to collapse)")
        (top,) = CountedTree(warnings(300), open_short=True).root.children
        self.assertFalse(top.is_expanded)


class CountedTreePopupTest(TuiTestCase):
    """At 120x30 (and 160x45) with 300 warnings: the buttons are on screen, the collapsed row shows the count, Tab
    reaches the tree, Space and Enter open the row, x opens every branch (the tree scrolls, the popup does not) and c
    closes them."""

    def assert_buttons_shown(self, screen: Screen, box_id: str, buttons: tuple[str, ...]) -> None:
        box = screen.query_one(f"#{box_id}")
        self.assertEqual(box.max_scroll_y, 0, "the popup itself scrolls: its buttons may be out of sight")
        for button_id in buttons:
            button = screen.query_one(f"#{button_id}", Button)
            self.assertTrue(screen.region.contains_region(button.region), button_id)
            self.assertTrue(box.region.contains_region(button.region), button_id)

    async def check(self, screen: Screen, box_id: str, buttons: tuple[str, ...], size: tuple[int, int]) -> None:
        app = Host(screen)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            tree = screen.query_one(f"#{LISTED_ID}", Tree)
            (top,) = tree.root.children
            self.assertEqual(str(top.label), "⚠ 300 warnings (Space or click to expand)")
            self.assertEqual(tree.region.height, 1)  # one row while collapsed
            self.assert_buttons_shown(screen, box_id, buttons)
            self.assertIsInstance(screen.focused, Button)
            for _ in range(len(buttons) + 1):  # Tab reaches the tree
                if screen.focused is tree:
                    break
                await pilot.press("tab")
            self.assertIs(screen.focused, tree)
            await pilot.press("space")
            await pilot.pause()
            self.assertTrue(top.is_expanded)
            self.assertEqual(str(top.label), "⚠ 300 warnings (Space or click to collapse)")
            self.assertEqual(labels(top.children), [f"{CREATED} (150)", f"{DUAL} (150)"])
            self.assert_buttons_shown(screen, box_id, buttons)
            await pilot.press("x")
            await pilot.pause()
            self.assertTrue(all(node.is_expanded for node in top.children))
            self.assertGreater(tree.max_scroll_y, 0)  # the tree scrolls inside the popup
            self.assert_buttons_shown(screen, box_id, buttons)
            await pilot.press("c")
            await pilot.pause()
            self.assertFalse(top.is_expanded)
            self.assertEqual(str(top.label), "⚠ 300 warnings (Space or click to expand)")
            tree.move_cursor(top)
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(top.is_expanded)
            self.assertEqual(app.results, [])  # nothing answered the popup

    async def test_confirm_keeps_yes_and_no_on_screen(self):
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                screen = ConfirmScreen("Dry run", "3 pending changes in 300 files (Retail).\nNo file is written.",
                                       ("WoW appears to be running.",), kind="simulate", listed=warnings(300))
                await self.check(screen, "confirm-box", ("yes", "no"), size)

    async def test_info_keeps_ok_on_screen(self):
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                await self.check(InfoScreen("Notes", listed=warnings(300)), "info-box", ("ok",), size)

    async def test_a_short_list_that_is_the_whole_popup_shows_at_once(self):
        """L10 review: a Notes popup with one or two notes shows them open, not behind a closed row; with a body
        or a long list the row starts closed."""
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                screen = InfoScreen("Notes", listed=warnings(2), noun="note", alert=False)
                app = Host(screen)
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    (top,) = screen.query_one(f"#{LISTED_ID}", Tree).root.children
                    self.assertTrue(top.is_expanded)
                    self.assertEqual(str(top.label), "2 notes (Space or click to collapse)")
                    self.assertTrue(all(node.is_expanded for node in top.children))
                    self.assert_buttons_shown(screen, "info-box", ("ok",))
        for screen in (InfoScreen("Notes", body="Some body", listed=warnings(2)),
                       InfoScreen("Notes", listed=warnings(300))):
            app = Host(screen)
            async with app.run_test(size=BASE) as pilot:
                await pilot.pause()
                (top,) = screen.query_one(f"#{LISTED_ID}", Tree).root.children
                self.assertFalse(top.is_expanded)

    async def test_summary_lines_stay_plain_above_the_tree(self):
        screen = ConfirmScreen("Dry run", "Body line", ("An alert",), kind="simulate", listed=warnings(3))
        app = Host(screen)
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            body = screen.query_one("#confirm-body")
            tree = screen.query_one(f"#{LISTED_ID}", Tree)
            self.assertIn("An alert", str(body.render()))
            self.assertNotIn("Addon000", str(body.render()))
            self.assertLess(body.region.y, tree.region.y)
            await pilot.press("y")
            await pilot.pause()
        self.assertEqual(app.results, [True])

    async def test_without_a_list_there_is_no_tree(self):
        screen = ConfirmScreen("Title", "Body", kind="confirm")
        app = Host(screen)
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            self.assertFalse(screen.query(f"#{LISTED_ID}"))
