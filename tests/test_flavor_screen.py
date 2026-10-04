from __future__ import annotations

import tempfile
from pathlib import Path

from textual.app import App
from textual.widgets import OptionList

from tests.fixtures import TuiTestCase, build_wow_tree, make_config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self.picker = screen
        self.result = "unset"

    def on_mount(self):
        self.push_screen(self.picker, self.done)

    def done(self, value):
        self.result = value


def _ids(options):
    return [options.get_option_at_index(i).id for i in range(options.option_count)]


class FlavorScreenTest(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.cfg = make_config(self.tmp / "config", self.root)
        self.install = WowInstall(self.root)

    async def test_default_has_no_all_entry(self):
        app = Host(FlavorScreen(self.cfg, self.install))
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#flavors", OptionList)
            self.assertNotIn(ALL_FLAVORS, _ids(options))
            self.assertEqual(_ids(options), [f.folder for f in self.install.flavors()])

    async def test_all_flavors_first_and_selected(self):
        app = Host(FlavorScreen(self.cfg, self.install, include_all=True, last=""))
        with capture_events() as records:
            async with app.run_test() as pilot:
                await pilot.pause()
                options = app.screen.query_one("#flavors", OptionList)
                self.assertEqual(options.get_option_at_index(0).id, ALL_FLAVORS)
                self.assertEqual(options.highlighted, 0)
                await pilot.press("enter")
                await pilot.pause()
        self.assertEqual(app.result, ALL_FLAVORS)
        self.assertEqual(self.cfg.last_flavor, "_retail_")  # unchanged
        selections = [r for r in records if r["event"] == "ui.selection"]
        self.assertEqual(selections[-1]["data"]["value"], "all")

    async def test_last_none_falls_back_to_general_last_flavor(self):
        app = Host(FlavorScreen(self.cfg, self.install, include_all=True))
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#flavors", OptionList)
            self.assertEqual(options.get_option_at_index(options.highlighted).id, "_retail_")

    async def test_last_flavor_highlighted_and_flavor_override(self):
        era = self.install.flavor("classic_era")
        app = Host(FlavorScreen(self.cfg, self.install, include_all=True, last="_classic_era_",
                                flavors=[self.install.flavor("retail"), era]))
        async with app.run_test() as pilot:
            await pilot.pause()
            options = app.screen.query_one("#flavors", OptionList)
            self.assertEqual(options.option_count, 3)
            self.assertEqual(options.get_option_at_index(options.highlighted).id, "_classic_era_")
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.result, era)
        self.assertEqual(self.cfg.last_flavor, "_classic_era_")

    async def test_escape_dismisses_none(self):
        app = Host(FlavorScreen(self.cfg, self.install, include_all=True))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        self.assertIsNone(app.result)

    async def test_set_notes_replaces_remarks_and_keeps_the_highlight(self):
        picker = FlavorScreen(self.cfg, self.install, include_all=True, last="_classic_era_",
                              note=lambda f: "counting…", all_note="counting…")
        app = Host(picker)
        async with app.run_test() as pilot:
            await pilot.pause()
            options = picker.query_one("#flavors", OptionList)
            highlighted = options.highlighted
            picker.set_notes(lambda f: f"{len(f.folder)} here", "all here")
            await pilot.pause()
            labels = [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]
            self.assertTrue(labels[0].endswith("all here"))
            self.assertTrue(all("counting" not in label for label in labels))
            self.assertIn(f"{len('_retail_')} here", labels[_ids(options).index("_retail_")])
            self.assertEqual(options.highlighted, highlighted)
