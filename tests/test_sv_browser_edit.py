"""Saved Variables Browser edits in the Browse view (spec D5, D10, D12, §5): the Edit value, Rename key and Delete key
popups on the highlighted key, their checks, the marks staged nodes show, Backspace (Unstage) and the pending line,
and leaving with staged edits."""
from __future__ import annotations

from textual.widgets import Button, Input, Select, Static, Tree

from tests.fixtures import BASE, TINY, assert_keys_on_buttons, settle
from tests.test_sv_browser_app import SvBrowserTestBase, child, labels, select
from wowtools.core.events import capture_events
from wowtools.tools.sv_browser.ops import SHIFT_WARNING
from wowtools.tools.sv_browser.popups import EditValueScreen, RenameKeyScreen
from wowtools.tools.sv_browser.review_screen import SvReviewScreen
from wowtools.tools.sv_browser.search import REPLACE_BOOLEAN, REPLACE_NUMBER, REPLACE_STRING
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.suite_app import ToolMenuScreen
from wowtools.ui.widgets import Ka0sCheckbox, NavHint


def error_text(screen, selector: str) -> str:
    line = screen.query_one(selector, Static)
    return line.render().plain if line.display else ""


class SvEditTestBase(SvBrowserTestBase):
    async def elv_default(self, app, pilot):
        """The review (Retail) with ElvUI.lua › ElvDB › profiles › Default open; returns (review, ElvUI.lua node,
        Default node)."""
        review = await self.open_review(app, pilot, "_retail_")
        tree = review.query_one("#browse", Tree)
        wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
        elv = await self.open_node(review, pilot, child(wide, "ElvUI.lua"))
        db = await self.open_node(review, pilot, child(elv, "ElvDB"))
        profiles = await self.open_node(review, pilot, child(db, "profiles"))
        default = await self.open_node(review, pilot, child(profiles, "Default"))
        return review, elv, default

    async def general(self, app, pilot):
        review, _, default = await self.elv_default(app, pilot)
        return review, await self.open_node(review, pilot, child(default, "general"))

    async def press_on(self, review, pilot, node, key: str):
        tree = review.query_one("#browse", Tree)
        select(tree, node)
        tree.focus()
        await settle(review.app, pilot)
        await pilot.press(key)
        await settle(review.app, pilot)
        return review.app.screen

    def pending(self, review) -> str:
        return review.query_one("#pending").render().plain


class EditValueTest(SvEditTestBase):
    async def test_edit_shows_the_current_value_checks_it_and_stages_it(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "fontSize"), "e")
            self.assertIsInstance(popup, EditValueScreen)
            self.assertIn("ElvUI.lua › ElvDB › profiles › Default › general › fontSize", popup.where)
            self.assertEqual(popup.current, "12")
            self.assertEqual(popup.query_one("#value-type", Select).value, REPLACE_NUMBER)
            field = popup.query_one("#value-text", Input)
            self.assertEqual(field.value, "12")
            self.assertIs(popup.focused, field)
            self.assertFalse(popup.query_one("#value-bool", Ka0sCheckbox).display)
            assert_keys_on_buttons(self, popup)
            for typed, problem in (("abc", "Enter a number"), ("inf", "Enter a number"),
                                   ("0.1000000000000000055511151231257827", "would be saved as")):
                field.value = typed
                field.focus()
                await settle(app, pilot)  # the field's Changed clears the problem line: let it pass first
                await pilot.press("enter")
                await settle(app, pilot)
                self.assertIs(app.screen, popup)
                self.assertIn(problem, error_text(popup, "#value-error"), typed)
            field.value = "14"
            await settle(app, pilot)
            self.assertEqual(error_text(popup, "#value-error"), "")  # typing clears the problem
            with capture_events() as events:
                await pilot.click("#ok")
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIn("svb.staged", [e["event"] for e in events])
            node = child(general, "fontSize")
            self.assertEqual(node.label.plain, "fontSize = 12  ✎ 14")
            self.assertEqual(self.pending(review), "Staged: 1 edit in 1 file")
            self.assertFalse(review.query_one("#btn-apply", Button).disabled)

    async def test_the_type_may_change_to_a_boolean_or_a_string(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "font ="), "e")
            self.assertEqual(popup.query_one("#value-type", Select).value, REPLACE_STRING)
            self.assertEqual(popup.query_one("#value-text", Input).value, "Friz Quadrata TT")
            popup.query_one("#value-type", Select).value = REPLACE_BOOLEAN
            await settle(app, pilot)
            box = popup.query_one("#value-bool", Ka0sCheckbox)
            self.assertTrue(box.display)
            self.assertFalse(popup.query_one("#value-text", Input).display)
            box.value = True
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(child(general, "font =").label.plain, 'font = "Friz Quadrata TT"  ✎ true')
            popup = await self.press_on(review, pilot, child(general, "autoRepair"), "e")
            self.assertEqual(popup.query_one("#value-type", Select).value, REPLACE_BOOLEAN)
            self.assertTrue(popup.query_one("#value-bool", Ka0sCheckbox).value)
            self.assertIs(popup.focused, popup.query_one("#value-bool"))
            popup.query_one("#value-type", Select).value = REPLACE_STRING
            await settle(app, pilot)
            popup.query_one("#value-text", Input).value = "12"
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(child(general, "autoRepair").label.plain, 'autoRepair = true  ✎ "12"')
            self.assertEqual(self.pending(review), "Staged: 2 edits in 1 file")

    async def test_cancel_and_the_same_value_stage_nothing(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            await self.press_on(review, pilot, child(general, "fontSize"), "e")
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            await self.press_on(review, pilot, child(general, "fontSize"), "e")
            await pilot.click("#ok")  # 12 as it is
            await settle(app, pilot)
            self.assertEqual(review.staging.count, 0)
            self.assertEqual(child(general, "fontSize").label.plain, "fontSize = 12")

    async def test_a_nil_top_level_value_and_a_string_with_line_breaks(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, elv, _ = await self.elv_default(app, pilot)
            popup = await self.press_on(review, pilot, child(elv, "ElvVersion"), "e")
            self.assertEqual((popup.current, popup.query_one("#value-text", Input).value), ("nil", ""))
            popup.query_one("#value-text", Input).value = "13.0"
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(child(elv, "ElvVersion").label.plain, 'ElvVersion = nil  ✎ "13.0"')
            tree = review.query_one("#browse", Tree)
            wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
            details = await self.open_node(review, pilot, child(wide, "Details.lua"))
            glob = await self.open_node(review, pilot, child(details, "_detalhes_global"))
            tip = await self.open_node(review, pilot, child(glob, "tooltip"))
            popup = await self.press_on(review, pilot, child(tip, "text"), "e")
            self.assertEqual(popup.query_one("#value-text", Input).value, "")
            self.assertIn("can't be typed here", popup.note)
            await pilot.press("escape")
            await settle(app, pilot)

    async def test_e_does_nothing_on_a_table_a_file_or_a_group(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, elv, default = await self.elv_default(app, pilot)
            for node in (child(default, "general"), elv, elv.parent):
                await self.press_on(review, pilot, node, "e")
                self.assertIs(app.screen, review, node.label.plain)


    async def test_enter_on_the_boolean_checkbox_presses_ok_and_space_ticks(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "autoRepair"), "e")
            box = popup.query_one("#value-bool", Ka0sCheckbox)
            self.assertIs(popup.focused, box)
            self.assertIn("Space tick", popup.query_one(NavHint).hint)
            await pilot.press("space")  # Space ticks or unticks
            await settle(app, pilot)
            self.assertFalse(box.value)
            await pilot.press("enter")  # Enter is OK, as the hint says: never a flip of the value
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(child(general, "autoRepair").label.plain, "autoRepair = true  ✎ false")

    async def test_a_staged_value_is_where_the_popup_starts(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "fontSize"), "e")
            popup.query_one("#value-text", Input).value = "14.5"
            await pilot.press("enter")
            await settle(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "fontSize"), "e")
            self.assertEqual(popup.current, "12")  # Now: the file's value
            self.assertEqual(popup.query_one("#value-type", Select).value, REPLACE_NUMBER)
            self.assertEqual(popup.query_one("#value-text", Input).value, "14.5")  # the staged one to change
            await pilot.press("escape")
            await settle(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "font ="), "e")
            popup.query_one("#value-type", Select).value = REPLACE_BOOLEAN
            await settle(app, pilot)
            popup.query_one("#value-bool", Ka0sCheckbox).value = True
            await pilot.click("#ok")
            await settle(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "font ="), "e")
            self.assertEqual(popup.query_one("#value-type", Select).value, REPLACE_BOOLEAN)
            self.assertTrue(popup.query_one("#value-bool", Ka0sCheckbox).value)
            self.assertIs(popup.focused, popup.query_one("#value-bool"))
            await pilot.press("escape")
            await settle(app, pilot)


class RenameKeyTest(SvEditTestBase):
    async def test_rename_checks_empty_and_duplicate_keys_then_stages(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "font ="), "k")
            self.assertIsInstance(popup, RenameKeyScreen)
            field = popup.query_one("#prompt", Input)
            self.assertEqual(field.value, "font")
            assert_keys_on_buttons(self, popup)
            for typed, problem in (("", "can't be empty"), ("fontSize", "already has the key fontSize"),
                                   ("[1e999]", "Can't use")):
                field.value = typed
                field.focus()
                await settle(app, pilot)  # the field's Changed clears the problem line: let it pass first
                await pilot.press("enter")
                await settle(app, pilot)
                self.assertIs(app.screen, popup, typed)
                self.assertIn(problem, error_text(popup, "#prompt-error"), typed)
            field.value = "Font"  # another case is another key
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(child(general, "font =").label.plain, 'font = "Friz Quadrata TT"  → Font')
            # renaming another key to the new name is now a duplicate; [5] is a number key
            popup = await self.press_on(review, pilot, child(general, "scale"), "k")
            popup.query_one("#prompt", Input).value = "Font"
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertIn("already has the key Font", error_text(popup, "#prompt-error"))
            popup.query_one("#prompt", Input).value = "[5]"
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(child(general, "scale").label.plain, "scale = 0.6000000000000001  → [5]")
            edit = review.staging.edit_for(review.docs[child(general, "scale").data[1].path],
                                           child(general, "scale").data[2])
            self.assertEqual((edit.new_key, type(edit.new_key)), (5, int))

    async def test_a_rename_and_an_edit_on_one_key_show_both_marks(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "fontSize"), "k")
            popup.query_one("#prompt", Input).value = "size"
            await pilot.press("enter")
            await settle(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "fontSize"), "e")
            popup.query_one("#value-text", Input).value = "13"
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertEqual(child(general, "fontSize").label.plain, "fontSize = 12  → size  ✎ 13")
            self.assertEqual(self.pending(review), "Staged: 1 edit in 1 file")

    async def test_k_is_refused_on_top_level_and_array_entries(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, elv, _ = await self.elv_default(app, pilot)
            tree = review.query_one("#browse", Tree)
            wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
            details = await self.open_node(review, pilot, child(wide, "Details.lua"))
            glob = await self.open_node(review, pilot, child(details, "_detalhes_global"))
            bars = await self.open_node(review, pilot, child(glob, "bars"))
            for node in (child(elv, "ElvDB"), bars.children[0]):
                await self.press_on(review, pilot, node, "k")
                self.assertIs(app.screen, review, node.label.plain)
                self.assertTrue(review.query_one("#act-rename", Button).disabled)


class DeleteKeyTest(SvEditTestBase):
    async def test_deleting_a_table_says_how_many_entries_go_and_marks_it(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, _, default = await self.elv_default(app, pilot)
            unit = await self.open_node(review, pilot, child(default, "unitframe"))
            popup = await self.press_on(review, pilot, child(unit, "barFont"), "e")
            popup.query_one("#value-text", Input).value = "Arial"
            await pilot.press("enter")
            await settle(app, pilot)
            confirm = await self.press_on(review, pilot, unit, "d")
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.kind, "destructive")
            self.assertIn("ElvUI.lua › ElvDB › profiles › Default › unitframe", confirm.body_text)
            self.assertIn("its 6 entries go with it", confirm.body_text)
            self.assertIn("The 1 edit staged inside it is dropped", confirm.body_text)
            self.assertEqual(confirm.alerts, ())
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(unit.label.plain, "unitframe {6}  ✗ deleted")
            self.assertEqual(child(unit, "barFont").label.plain, 'barFont = "Expressway"')  # its edit went
            self.assertEqual(self.pending(review), "Staged: 1 edit in 1 file")
            # nothing can be staged inside it now: the bar is off there, and e says why
            await self.press_on(review, pilot, child(unit, "barFont"), "e")
            self.assertIs(app.screen, review)
            self.assertTrue(review.query_one("#act-edit", Button).disabled)
            self.assertTrue(review.query_one("#act-delete", Button).disabled)
            # the deleted key itself: nothing left to delete, so the bar is off and d asks nothing again
            confirm = await self.press_on(review, pilot, unit, "d")
            self.assertIs(confirm, review)
            self.assertTrue(review.query_one("#act-delete", Button).disabled)

    async def test_an_array_entry_carries_the_shift_warning_and_no_stages_nothing(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#browse", Tree)
            wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
            details = await self.open_node(review, pilot, child(wide, "Details.lua"))
            glob = await self.open_node(review, pilot, child(details, "_detalhes_global"))
            bars = await self.open_node(review, pilot, child(glob, "bars"))
            confirm = await self.press_on(review, pilot, bars.children[0], "d")
            self.assertEqual(confirm.alerts, (SHIFT_WARNING,))
            await pilot.press("n")
            await settle(app, pilot)
            self.assertEqual(review.staging.count, 0)
            confirm = await self.press_on(review, pilot, bars.children[0], "d")
            await pilot.press("y")
            await settle(app, pilot)
            self.assertEqual(labels(bars)[0], '[1] = "one"  ✗ deleted')

    async def test_d_is_refused_on_a_top_level_variable(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, elv, _ = await self.elv_default(app, pilot)
            await self.press_on(review, pilot, child(elv, "ElvVersion"), "d")
            self.assertIs(app.screen, review)


class UnstageTest(SvEditTestBase):
    async def test_backspace_unstages_the_highlighted_node(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            self.assertTrue(review.query_one("#act-unstage", Button).disabled)
            await self.press_on(review, pilot, child(general, "scale"), "d")
            await pilot.press("y")
            await settle(app, pilot)
            self.assertFalse(review.query_one("#act-unstage", Button).disabled)
            self.assertEqual(self.pending(review), "Staged: 1 edit in 1 file")
            with capture_events() as events:
                await self.press_on(review, pilot, child(general, "scale"), "backspace")
            self.assertIn("svb.unstaged", [e["event"] for e in events])
            self.assertEqual(child(general, "scale").label.plain, "scale = 0.6000000000000001")
            self.assertEqual(self.pending(review), "Staged: 0 edits in 0 files")
            self.assertTrue(review.query_one("#act-unstage", Button).disabled)
            self.assertTrue(review.query_one("#btn-apply", Button).disabled)
            await self.press_on(review, pilot, child(general, "scale"), "backspace")  # nothing staged: nothing
            self.assertEqual(review.staging.count, 0)

    async def test_the_bar_has_unstage_on_backspace(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, _ = await self.general(app, pilot)
            button = review.query_one("#act-unstage", Button)
            self.assertEqual((button.label_text, button.shortcut), ("Unstage", "backspace"))
            assert_keys_on_buttons(self, review)


class LeaveTest(SvEditTestBase):
    async def test_leaving_with_staged_edits_asks_a_destructive_question_for_every_way_out(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            await self.press_on(review, pilot, child(general, "scale"), "d")
            await pilot.press("y")
            await settle(app, pilot)
            for key in ("f", "t", "q", "escape"):
                await pilot.press(key)
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen, key)
                self.assertEqual(app.screen.kind, "destructive")
                self.assertIn("1 staged edit", app.screen.body_text)
                await pilot.press("n")
                await settle(app, pilot)
                self.assertIs(app.screen, review)
            await pilot.press("t")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)

    async def test_leaving_after_unstaging_everything_does_not_ask(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            await self.press_on(review, pilot, child(general, "scale"), "d")
            await pilot.press("y")
            await settle(app, pilot)
            await self.press_on(review, pilot, child(general, "scale"), "backspace")
            await pilot.press("f")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)


class PopupsAtTinyTest(SvEditTestBase):
    async def test_the_popups_work_at_80x24(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review, general = await self.general(app, pilot)
            self.assertIsInstance(review, SvReviewScreen)
            popup = await self.press_on(review, pilot, child(general, "fontSize"), "e")
            for selector in ("#value-type", "#value-text", "#ok", "#cancel"):
                widget = popup.query_one(selector)
                self.assertGreater(widget.region.height, 0, selector)
                self.assertLessEqual(widget.region.right, TINY[0], selector)
            await pilot.press("escape")
            await settle(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "fontSize"), "k")
            self.assertGreater(popup.query_one("#prompt").region.height, 0)
            await pilot.press("escape")
            await settle(app, pilot)
