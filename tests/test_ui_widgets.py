"""Keys on buttons (spec D17): action_button shows its key, the footer leaves out the keys shown buttons carry."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button
from textual.widgets._footer import FooterKey

from tests.fixtures import TuiTestCase, settle
from wowtools.core.config import Config
from wowtools.ui.base import Ka0sApp
from wowtools.ui.branding import BottomBar, footer_bindings
from wowtools.ui.widgets import ActionButton, ButtonRow, action_button, button_keys, key_text


class KeyTextTest(unittest.TestCase):
    def test_keys_are_written_as_the_footer_writes_them_with_named_keys_capitalised(self):
        self.assertEqual([key_text(k) for k in ("w", "D", "E", "escape", "space", "backspace", "slash", "delete")],
                         ["w", "D", "E", "Esc", "Space", "⌫", "/", "Del"])
        self.assertEqual(key_text("ctrl+s"), "Ctrl+s")


class ActionButtonTest(unittest.TestCase):
    def test_a_full_size_button_shows_its_key_on_a_second_line(self):
        button = action_button("Clean", "destructive", "w", id="clean")
        self.assertIsInstance(button, ActionButton)
        self.assertEqual(button.label.plain, "Clean\n(w)")
        self.assertEqual((button.label_text, button.shortcut), ("Clean", "w"))
        self.assertTrue(button.has_class("-keyed"))
        self.assertEqual(action_button("Cancel", "cancel", "escape").label.plain, "Cancel\n(Esc)")

    def test_a_compact_button_keeps_its_key_on_its_one_row(self):
        button = action_button("Discard", "cancel", "backspace", compact=True)
        self.assertEqual(button.label.plain, "Discard (⌫)")
        self.assertFalse(button.has_class("-keyed"))

    def test_a_button_without_a_key_shows_its_label_only(self):
        button = action_button("Save", "confirm")
        self.assertEqual(button.label.plain, "Save")
        self.assertIsNone(button.shortcut)


class Keyed(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("a", "noop('a')", "All"),
        Binding("w", "noop('w')", "Clean"),
        Binding("n,escape", "noop('n')", "No"),
        Binding("h", "noop('h')", "Hidden"),
    ]

    def compose(self) -> ComposeResult:
        with ButtonRow(id="row"):
            yield action_button("Clean", "destructive", "w", id="clean")
            yield action_button("No", "cancel", "n", id="no")
            yield action_button("Save", "confirm", id="save")
        hidden = action_button("Hidden", "navigate", "h", id="hidden")
        hidden.display = False
        yield hidden
        yield BottomBar()

    def action_noop(self, key: str) -> None:
        pass


class Host(Ka0sApp):
    def after_mount(self) -> None:
        self.push_screen(Keyed())


class FooterTest(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = Config(Path(tmp.name) / "wow-tools.cfg")

    async def test_the_footer_lists_only_keys_no_shown_button_carries(self):
        app = Host(self.cfg, check_updates=False)
        async with app.run_test(size=(120, 30)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            self.assertEqual(button_keys(screen), {"w", "n"})  # the hidden button's h is not shown
            listed = [key.key for key in screen.query(FooterKey)]
            self.assertEqual(listed, ["a", "h"])  # w and n are on buttons, and Esc goes with n (one action)
            self.assertEqual([b.description for b, _, _ in footer_bindings(screen)], ["All", "Hidden"])

    async def test_every_button_of_a_row_with_a_keyed_one_is_as_tall(self):
        app = Host(self.cfg, check_updates=False)
        async with app.run_test(size=(120, 30)) as pilot:
            await settle(app, pilot)
            row = app.screen.query_one("#row", ButtonRow)
            self.assertTrue(row.has_class("-keyed"))
            self.assertEqual({b.region.height for b in row.query(Button)}, {4})
            save = app.screen.query_one("#save", Button)
            self.assertEqual(save.label.plain, "Save")


if __name__ == "__main__":
    unittest.main()
