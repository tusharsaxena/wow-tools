"""The shared result screen, choice popup, settings form and ToolFlow helpers (spec D9), driven through toy
subclasses. The tools' own TUI tests drive the same code on their real screens."""
from __future__ import annotations

import tempfile
import threading
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar
from unittest import mock

from rich.text import Text
from textual.app import App
from textual.binding import Binding
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Static

from tests.fixtures import BASE, TINY, TuiTestCase, build_wow_tree, make_config, settle
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import Flavor, WowInstall
from wowtools.ui import dialogs
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.dialogs import (CONFIRM_GUARD, RESULT_HINT, ChoiceScreen, ConfirmScreen, TextPromptScreen,
                                UnfinishedRunScreen, popup_css, show_error)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.result_screen import (ResultBase, ResultScreen, result_bindings, status_colour,
                                       status_style)
from wowtools.ui.settings_form import ToolSettingsScreen, folder_hint, settings_hint
from wowtools.ui.tool_flow import SETTINGS_SAVED, ToolFlow
from wowtools.ui.widgets import Ka0sCheckbox, NavHint, action_kind


class Host(App):
    """A bare app to push one screen on; records what it was dismissed with."""

    def __init__(self, screen: Screen) -> None:
        super().__init__()
        self.first = screen
        self.results: list = []

    def on_mount(self) -> None:
        self.push_screen(self.first, self.results.append)


class StatusTest(unittest.TestCase):
    def test_status_colour_whole_or_by_prefix(self):
        self.assertEqual(status_colour("failed", {"failed": "error"}), "error")
        self.assertIsNone(status_colour("failed: no space", {"failed": "error"}))
        self.assertEqual(status_colour("failed: no space", (("failed", "error"),), prefix=True), "error")
        self.assertEqual(status_colour("changed", {"would change": "accent", "changed": "success"}, prefix=True),
                         "success")
        self.assertIsNone(status_colour("other", (("failed", "error"),), prefix=True))

    def test_status_style(self):
        self.assertTrue(status_style(None, "error").startswith("bold #"))
        self.assertEqual(status_style(None, None), "bold")
        self.assertEqual(status_style(None, None, plain=""), "")

    def test_result_bindings_order(self):
        keys = [b.key for b in result_bindings("review", before=[Binding("z", "choose('undo')", "Undo")],
                                               after=[Binding("e", "choose('restore')", "Restore")])]
        self.assertEqual(keys[:7], ["z", "r", "e", "f", "t", "q", "escape"])
        self.assertEqual(result_bindings("review")[0].action, "choose('review')")


class ResultScreenTest(TuiTestCase):
    def make(self, **kwargs) -> ResultScreen:
        class Toy(ResultScreen):
            LOG_SCREEN = "toy_result"
            STATUS_COLOURS: ClassVar = (("done", "success"), ("failed", "error"))

        return Toy("Toy · result", [("Mode", "Run")], ("Name", "Status"),
                   [("a", "done"), ("b", "failed: locked"), ("c", "other")], **kwargs)

    async def test_layout_hint_colours_and_choice(self):
        screen = self.make()
        app = Host(screen)
        with capture_events() as events:
            async with app.run_test(size=BASE) as pilot:
                await pilot.pause()
                self.assertEqual(screen.sub_title, "Toy · result")
                self.assertEqual([b.id for b in screen.query(Button)], ["rescan", "flavors", "tools", "quit"])
                self.assertIs(screen.focused, screen.query_one("#rescan"))
                hint = str(screen.query_one(NavHint).render())
                self.assertEqual(hint, RESULT_HINT)  # the keys are on the buttons (D17)
                self.assertEqual([b.shortcut for b in screen.query(Button)], ["r", "f", "t", "q"])
                detail = screen.query_one("#result-detail", DataTable)
                styles = [detail.get_row_at(i)[1].style for i in range(3)]
                self.assertTrue(styles[0].startswith("bold #") and styles[1].startswith("bold #"))
                self.assertNotEqual(styles[0], styles[1])
                self.assertEqual(styles[2], "bold")
                summary = screen.query_one("#result-summary", DataTable)
                self.assertFalse(summary.can_focus)
                self.assertEqual(str(summary.get_row_at(0)[1]), "Run")
                await pilot.press("escape")
                await pilot.pause()
        self.assertEqual(app.results, ["rescan"])
        self.assertIn({"screen": "toy_result", "control": "next", "value": "rescan"},
                      [r["data"] for r in events if r["event"] == "ui.selection"])

    async def test_back_opens_on_back_to_review(self):
        for key, expected in (("escape", "back"), ("t", "tools")):
            with self.subTest(key=key):
                screen = self.make(back=True)
                app = Host(screen)
                async with app.run_test(size=TINY) as pilot:
                    await pilot.pause()
                    self.assertEqual([b.id for b in screen.query(Button)],
                                     ["rescan", "back", "flavors", "tools", "quit"])
                    self.assertIs(screen.focused, screen.query_one("#back"))
                    await pilot.press(key)
                    await pilot.pause()
                self.assertEqual(app.results, [expected])

    async def test_a_screen_of_its_own_fills_the_tables(self):
        class Own(ResultBase):
            RESCAN = "review"
            DETAIL_ID = "result-files"
            BINDINGS: ClassVar[list[Binding]] = result_bindings(RESCAN, before=[Binding("z", "choose('undo')", "Undo")])

            def result_title(self) -> str:
                return "Own"

            def lead_buttons(self):
                return [("Undo", "revert", "undo", "z")]

            def fill_detail(self, detail: DataTable) -> None:
                detail.add_columns("File")
                detail.add_row(Text("x"))

        screen = Own()
        app = Host(screen)
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            self.assertEqual([b.id for b in screen.query(Button)], ["undo", "review", "flavors", "tools", "quit"])
            self.assertEqual([b.label.plain for b in screen.query(Button)][:2], ["Undo\n(z)", "Rescan\n(r)"])
            self.assertEqual(screen.query_one("#result-files", DataTable).row_count, 1)
            await pilot.click("#undo")
            await pilot.pause()
        self.assertEqual(app.results, ["undo"])


class FakeClock:
    """dialogs.monotonic for the Enter guard tests: time stands still until a test moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ConfirmScreenTest(TuiTestCase):
    """Spec D13: every confirm opens on Yes (Yes, No in that order), Yes coloured by its kind; Enter and Space are
    ignored for CONFIRM_GUARD seconds after it opens and while a held key repeats, `y`, `n` and Esc never are."""

    def guarded(self) -> FakeClock:
        self.assertGreaterEqual(CONFIRM_GUARD, 0.2)  # the real guard: longer than a double press, not a wait
        self.confirm_guard(CONFIRM_GUARD)
        clock = FakeClock()
        patcher = mock.patch.object(dialogs, "monotonic", clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return clock

    async def test_opens_on_yes_coloured_by_kind(self):
        for kind in ("confirm", "destructive", "simulate", "create"):
            screen = ConfirmScreen("Title", "Body", kind=kind)
            app = Host(screen)
            async with app.run_test(size=TINY) as pilot:
                await pilot.pause()
                yes, no = screen.query(Button)
                self.assertEqual((yes.id, no.id), ("yes", "no"))  # Yes first
                self.assertIs(screen.focused, yes)
                self.assertEqual((action_kind(yes), action_kind(no)), (kind, "cancel"))
                await pilot.press("enter")
                await pilot.pause()
            self.assertEqual(app.results, [True])
        with self.assertRaises(ValueError):
            ConfirmScreen("Title", "Body", kind="delete")

    async def test_enter_and_space_wait_for_the_guard(self):
        clock = self.guarded()
        for key in ("enter", "space"):
            screen = ConfirmScreen("Title", "Body", kind="destructive")
            app = Host(screen)
            async with app.run_test(size=TINY) as pilot:
                await pilot.pause()
                clock.now += CONFIRM_GUARD - 0.01
                await pilot.press(key)  # a key from the screen below: ignored, and the wait starts again
                await pilot.pause()
                self.assertIs(app.screen, screen)
                self.assertEqual(app.results, [])
                clock.now += 0.02
                await pilot.press(key)
                await pilot.pause()
                self.assertEqual(app.results, [])
                clock.now += CONFIRM_GUARD
                await pilot.press(key)
                await pilot.pause()
            self.assertEqual(app.results, [True], key)

    async def test_a_held_enter_never_answers(self):
        clock = self.guarded()
        screen = ConfirmScreen("Title", "Body", kind="destructive")
        app = Host(screen)
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            await pilot.press("enter")  # pressed at once
            for _ in range(10):  # then auto-repeat, every 0.1 s, well past CONFIRM_GUARD from the mount
                clock.now += 0.1
                await pilot.press("enter")
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertEqual(app.results, [])
            clock.now += CONFIRM_GUARD + 0.05  # the key is let go, then pressed again
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.results, [True])

    async def test_y_n_and_escape_are_never_delayed(self):
        self.guarded()
        for key, answer in (("y", True), ("n", False), ("escape", False)):
            screen = ConfirmScreen("Title", "Body", kind="destructive")
            app = Host(screen)
            async with app.run_test(size=TINY) as pilot:
                await pilot.pause()
                await pilot.press(key)
                await pilot.pause()
            self.assertEqual(app.results, [answer], key)

    async def test_the_guard_leaves_the_detail_tree_alone(self):
        clock = self.guarded()
        screen = ConfirmScreen("Title", "Body", groups={"Group": ["one", "two"]})
        app = Host(screen)
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            tree = screen.query_one("#details")
            tree.focus()
            await pilot.pause()
            branch = tree.root.children[0]
            self.assertTrue(branch.is_expanded)
            tree.move_cursor(branch)
            await pilot.press("space")  # within the guard: the tree still folds the branch
            await pilot.pause()
            self.assertFalse(branch.is_expanded)
            clock.now += 1
        self.assertEqual(app.results, [])


class ChoiceScreenTest(TuiTestCase):
    def make(self, **kwargs) -> ChoiceScreen:
        return ChoiceScreen("Something did not finish", "Line one\nLine two",
                            [("leave", "Leave", "cancel"), ("fix", "Fix it", "revert")], default="fix", **kwargs)

    async def test_default_focus_and_choice(self):
        screen = self.make()
        app = Host(screen)
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            self.assertIs(screen.focused, screen.query_one("#fix"))
            box = screen.query_one("#choice-box")
            for button in screen.query(Button):
                self.assertTrue(box.region.contains_region(button.region), button.id)
            await pilot.press("escape")  # Esc does nothing without escape=True
            await pilot.pause()
            self.assertIs(app.screen, screen)
            await pilot.click("#leave")
            await pilot.pause()
        self.assertEqual(app.results, ["leave"])

    async def test_enter_waits_for_the_guard(self):
        self.confirm_guard(CONFIRM_GUARD)
        clock = FakeClock()
        with mock.patch.object(dialogs, "monotonic", clock):
            screen = self.make()
            app = Host(screen)
            async with app.run_test(size=TINY) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertIs(app.screen, screen)
                clock.now += CONFIRM_GUARD
                await pilot.press("enter")
                await pilot.pause()
        self.assertEqual(app.results, ["fix"])

    async def test_escape_closes_when_allowed(self):
        screen = self.make(escape=True)
        app = Host(screen)
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        self.assertEqual(app.results, [None])


class PopupHelpersTest(TuiTestCase):
    def test_popup_css_names_the_screen_and_the_list_rows(self):
        css = popup_css("MyPopup")
        self.assertIn("MyPopup .popup-box", css)
        self.assertNotIn("OptionList", css)
        self.assertIn("max-height: 9;", popup_css("MyPopup", list_rows=7))

    async def test_show_error_shows_and_hides_the_line(self):
        line = Static("")
        app = Host(Screen())
        async with app.run_test(size=TINY) as pilot:
            await app.screen.mount(line)
            show_error(line, "Bad name")
            await pilot.pause()
            self.assertTrue(line.display)
            self.assertEqual(str(line.render()), "Bad name")
            show_error(line, None)
            self.assertFalse(line.display)


class TextPromptScreenTest(TuiTestCase):
    def make(self) -> TextPromptScreen:
        return TextPromptScreen("Rename a key", "Type the new name.", "old",
                                check=lambda text: "Empty" if not text.strip() else None, placeholder="key name")

    async def test_check_blocks_then_enter_answers(self):
        screen = self.make()
        app = Host(screen)
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            field = screen.query_one("#prompt", Input)
            self.assertIs(screen.focused, field)
            self.assertEqual((field.value, field.placeholder), ("old", "key name"))
            field.value = ""
            await pilot.press("enter")
            await pilot.pause()
            error = screen.query_one("#prompt-error", Static)
            self.assertIs(app.screen, screen)
            self.assertTrue(error.display)
            self.assertEqual(str(error.render()), "Empty")
            await pilot.press("x")  # typing clears the error
            await pilot.pause()
            self.assertFalse(error.display)
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.results, ["x"])

    async def test_cancel_and_escape_answer_none(self):
        for how in ("escape", "#cancel"):
            with self.subTest(how=how):
                screen = self.make()
                app = Host(screen)
                async with app.run_test(size=TINY) as pilot:
                    await pilot.pause()
                    await (pilot.press(how) if how == "escape" else pilot.click(how))
                    await pilot.pause()
                self.assertEqual(app.results, [None])

    async def test_ok_button_answers_with_no_check(self):
        screen = TextPromptScreen("Title", "Body")
        app = Host(screen)
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            await pilot.click("#ok")
            await pilot.pause()
        self.assertEqual(app.results, [""])


class UnfinishedRunScreenTest(TuiTestCase):
    async def test_put_back_is_the_default_and_esc_asks_later(self):
        for key, answer in (("escape", None), ("enter", "put_back")):
            with self.subTest(key=key):
                self.confirm_guard(0)
                screen = UnfinishedRunScreen("What happened", marker="M")
                app = Host(screen)
                async with app.run_test(size=TINY) as pilot:
                    await pilot.pause()
                    self.assertEqual(screen.marker, "M")
                    self.assertEqual(str(screen.query_one("#choice-title", Static).render()),
                                     "An earlier change did not finish")
                    self.assertIs(screen.focused, screen.query_one("#put_back"))
                    self.assertEqual({b.id for b in screen.query(Button)}, {"leave", "put_back"})
                    await pilot.press(key)
                    await pilot.pause()
                self.assertEqual(app.results, [answer])


class ToySettings(ToolSettingsScreen):
    FORM_TITLE = "Toy settings"
    FIRST_FIELD = "folder"
    TICKS = True

    def load(self, tool_cfg: Config) -> dict:
        return {"folder": tool_cfg.get_path("toy", "folder"), "flag": tool_cfg.get("toy", "flag") == "true"}

    def fields(self) -> Iterable[Widget]:
        yield self.folder_input(self.settings["folder"], placeholder=folder_hint(self.wow_path), id="folder")
        yield Ka0sCheckbox("A flag", self.settings["flag"], id="flag", compact=True)

    def save(self) -> bool:
        folder = self.folder_value("folder")
        if folder is not None and folder.name == "bad":
            self._error("Not that folder.")
            return False
        self.tool_cfg.set("toy", "folder", str(folder) if folder else "", source=self.source)
        self.tool_cfg.save()
        return True


class SettingsFormTest(TuiTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tool_cfg = Config(self.tmp / "toy.cfg")

    def test_hints(self):
        self.assertIn("Space/Enter tick", settings_hint(True))
        self.assertNotIn("tick", settings_hint(False))
        self.assertEqual(folder_hint(None), "")

    async def test_form_error_save_and_cancel(self):
        screen = ToySettings(self.tool_cfg, self.tmp, source="settings")
        app = Host(screen)
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            self.assertEqual(screen.sub_title, "Toy settings")
            self.assertIsNone(screen.wow_install)  # the temp folder holds no flavor folders
            self.assertIs(screen.focused, screen.query_one("#folder", Input))
            self.assertIn("Space/Enter tick", str(screen.query_one(NavHint).render()))
            self.assertEqual(screen.query_one("#folder", Input).placeholder, folder_hint(self.tmp))
            screen.query_one("#folder", Input).value = "C:\\bad"
            await pilot.click("#save")
            await pilot.pause()
            self.assertEqual(screen.error_text, "Not that folder.")
            self.assertIn("Not that folder.", str(screen.query_one("#settings-error", Static).render()))
            screen.query_one("#folder", Input).value = "  "
            screen.query_one("#save", Button).press()
            await pilot.pause()
        self.assertEqual(app.results, [True])
        self.assertEqual(self.tool_cfg.get("toy", "folder"), "")

        screen = ToySettings(self.tool_cfg, None, source="settings")
        app = Host(screen)
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        self.assertEqual(app.results, [False])


class FakeSuite(App):
    """What a ToolFlow needs from WowToolsApp: cfg, close_tool, open_general_settings (here: straight through)."""

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.closed = 0
        self.notes: list[str] = []
        self.detect = list

    def close_tool(self) -> None:
        self.closed += 1

    def open_general_settings(self, then=None) -> None:
        if then is not None:
            then(True)

    def notify(self, message, **kwargs) -> None:
        self.notes.append(str(message))


class ToyFlow(ToolFlow):
    SECTION = "toy"
    SETTINGS_SCREEN = ToySettings

    def __init__(self, app, tool_cfg) -> None:
        super().__init__(app, tool_cfg)
        self.picked = 0
        self.reviewed: list = []

    def _pick_flavor(self) -> None:
        self.picked += 1


class ToolFlowTest(TuiTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = build_wow_tree(self.tmp / "wow")
        self.cfg = make_config(self.tmp / "config", self.root)
        self.tool_cfg = Config(self.tmp / "config" / "toy.cfg")

    def flavor(self, folder: str) -> Flavor:
        return next(f for f in WowInstall(self.root).flavors() if f.folder == folder)

    async def test_first_open_asks_for_settings_once(self):
        app = FakeSuite(self.cfg)
        async with app.run_test(size=BASE) as pilot:
            flow = ToyFlow(app, self.tool_cfg)
            flow.start()
            await pilot.pause()
            self.assertIsInstance(app.screen, ToySettings)
            self.assertEqual(app.screen.source, "wizard")
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(flow.picked, 1)
            self.assertFalse(self.tool_cfg.exists)  # cancelled: asked again next time
            self.tool_cfg.save()
            flow.start()
            await pilot.pause()
            self.assertEqual(flow.picked, 2)

    async def test_open_settings_once_and_notify_on_save(self):
        app = FakeSuite(self.cfg)
        async with app.run_test(size=BASE) as pilot:
            flow = ToyFlow(app, self.tool_cfg)
            flow.open_settings()
            await pilot.pause()
            settings = app.screen
            self.assertIsInstance(settings, ToySettings)
            flow.open_settings()  # never a second settings screen over the first
            await pilot.pause()
            self.assertEqual(sum(isinstance(s, ToySettings) for s in app.screen_stack), 1)
            await pilot.click("#save")
            await pilot.pause()
            self.assertEqual(app.notes, [SETTINGS_SAVED])

    async def test_after_review(self):
        app = FakeSuite(self.cfg)
        exits: list = []
        app.exit = lambda *a, **k: exits.append(True)  # type: ignore[method-assign]
        async with app.run_test(size=BASE):
            flow = ToyFlow(app, self.tool_cfg)
            flow._after_review("flavors")
            flow._after_review("tools")
            flow._after_review("quit")
            self.assertEqual((flow.picked, app.closed, exits), (1, 1, [True]))

    async def test_remember_flavor(self):
        app = FakeSuite(self.cfg)
        self.tool_cfg.save()
        async with app.run_test(size=BASE):
            flow = ToyFlow(app, self.tool_cfg)
            with capture_events() as events:
                self.assertEqual(flow.remember_flavor(ALL_FLAVORS), "")
                self.assertEqual(flow.remember_flavor(ALL_FLAVORS), "")  # unchanged: not written again
                self.assertEqual(flow.remember_flavor(self.flavor("_retail_")), "_retail_")
            changes = [r["data"] for r in events if r["event"] == "config.changed"]
            self.assertEqual([(e["new"], e["source"]) for e in changes], [("", "picker"), ("_retail_", "picker")])
            self.assertEqual(Config(self.tool_cfg.path).load().get("toy", "last_flavor_choice"), "_retail_")

    async def test_pick_account(self):
        app = FakeSuite(self.cfg)
        self.tool_cfg.save()
        async with app.run_test(size=BASE) as pilot:
            flow = ToyFlow(app, self.tool_cfg)
            got: list = []
            flow.pick_account(self.flavor("_classic_era_"), got.append)  # one account: no picker
            self.assertEqual(got, [None])
            flow.pick_account(self.flavor("_retail_"), got.append)
            await pilot.pause()
            self.assertIsInstance(app.screen, AccountScreen)
            app.screen.dismiss("ACCT2")
            await pilot.pause()
            self.assertEqual(got, [None, "ACCT2"])
            self.assertEqual(self.tool_cfg.get("toy", "last_account"), "ACCT2")
            flow.pick_account(self.flavor("_retail_"), got.append)
            await pilot.pause()
            self.assertEqual(app.screen.last, "ACCT2")
            app.screen.dismiss(None)  # Esc: back to the flavor picker
            await pilot.pause()
            self.assertEqual((got, flow.picked), ([None, "ACCT2"], 1))

    async def test_fill_notes_reach_an_open_picker(self):
        app = FakeSuite(self.cfg)
        async with app.run_test(size=BASE) as pilot:
            flow = ToyFlow(app, self.tool_cfg)
            picker = FlavorScreen(self.cfg, WowInstall(self.root), include_all=True)
            app.push_screen(picker)
            await pilot.pause()
            got: list = []
            flow.fill_notes(picker, lambda: 7, got.append)
            await settle(app, pilot)
            self.assertEqual(got, [7])

    async def test_fill_notes_dropped_after_the_picker_closed(self):
        app = FakeSuite(self.cfg)
        async with app.run_test(size=BASE) as pilot:
            flow = ToyFlow(app, self.tool_cfg)
            picker = FlavorScreen(self.cfg, WowInstall(self.root), include_all=True)
            app.push_screen(picker)
            await pilot.pause()
            got: list = []
            release = threading.Event()

            def work() -> int:
                release.wait(5)
                return 3

            flow.fill_notes(picker, work, got.append)
            picker.dismiss(None)
            await pilot.pause()
            release.set()
            await settle(app, pilot)
            self.assertEqual(got, [])
