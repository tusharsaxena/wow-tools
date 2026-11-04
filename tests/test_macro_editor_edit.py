"""The Macro Editor's edit screen and its popups (config tools spec ME8-ME11): name (cut at 16), icon, scope label, the
`n / 255` meter that turns Save off above 255, the body with suggestions as you type (Tab / Enter accept) and the help
panel that follows the cursor; Ctrl+B the conditional builder (filled from the block under the cursor, OK rewrites it
or inserts a new one), Ctrl+O the optimizer (rewrites and their reasons, OK takes them), Ctrl+T a template (pick,
fill the placeholders, insert) and F1 the reference. The UI-free halves (builder.py, explain.describe_at,
syntax.completion_start) are tested here too. Every client file is synthesized by tests/fixtures.py
build_macro_tree, never a real install."""
from __future__ import annotations

import unittest

from textual.widgets import Checkbox, Input, OptionList, RadioButton, RadioSet, Static, TextArea, Tree

from tests.fixtures import BASE, TINY, assert_keys_on_buttons, settle
from tests.test_macro_editor_app import MacroEditorTestBase, character_node, goto, macro_node
from wowtools.core.kb import load_macro_reference
from wowtools.core.macrofile import BODY_LIMIT, ICON_DEFAULT, NAME_LIMIT
from wowtools.tools.macro_editor.builder import BlockChoice, block_at, read_block, write_block
from wowtools.tools.macro_editor.builder_screen import BuilderScreen
from wowtools.tools.macro_editor.edit_screen import MacroEditScreen
from wowtools.tools.macro_editor.explain import describe_at, reference_lines
from wowtools.tools.macro_editor.ops import effective_macros
from wowtools.tools.macro_editor.optimize_screen import OptimizeScreen
from wowtools.tools.macro_editor.reference_screen import ReferenceScreen
from wowtools.tools.macro_editor.syntax import completion_start
from wowtools.tools.macro_editor.template_screen import TemplateScreen
from wowtools.tools.macro_editor.templates import fill_template, load_templates

HEAL = "/cast [@mouseover,help,nodead] Flash Heal"


def plain(widget) -> str:
    rendered = widget.render()
    return getattr(rendered, "plain", str(rendered))


class BuilderLogicTest(unittest.TestCase):
    def setUp(self):
        self.builder = load_macro_reference("_retail_").builder

    def test_read_block(self):
        choice = read_block("[@mouseover,help,nodead]", self.builder)
        self.assertEqual((choice.target, choice.unit, choice.states), ("@mouseover", "help", ("nodead",)))
        self.assertEqual(read_block("[target=focus, harm]", self.builder).target, "@focus")
        self.assertEqual(read_block("[]", self.builder), BlockChoice(None, None, (), ()))
        other = read_block("[spec:2,@party1,MOD:SHIFT]", self.builder)
        self.assertEqual((other.target, other.unit, other.states), ("@party1", None, ("mod:shift",)))

    def test_write_unchanged_keeps_the_block_as_written(self):
        for block in ("[@mouseover, help, nodead]", "[target=focus,harm]", "[]", "[spec:2,@party1]"):
            choice = read_block(block, self.builder)
            self.assertEqual(write_block(choice, target=choice.target, unit=choice.unit, states=choice.states,
                                         builder=self.builder, block=block), block)

    def test_write_changes_in_place_and_keeps_what_the_builder_does_not_show(self):
        block = "[spec:2,@mouseover,help,nodead]"
        choice = read_block(block, self.builder)
        self.assertEqual(write_block(choice, target="@focus", unit="harm", states=("nodead", "combat"),
                                     builder=self.builder, block=block), "[spec:2,@focus,harm,nodead,combat]")
        self.assertEqual(write_block(choice, target=None, unit=None, states=(), builder=self.builder, block=block),
                         "[spec:2]")
        self.assertEqual(write_block(None, target="@cursor", unit=None, states=("mod:shift",), builder=self.builder),
                         "[@cursor,mod:shift]")
        self.assertEqual(write_block(None, target=None, unit=None, states=(), builder=self.builder), "[]")

    def test_block_at(self):
        self.assertEqual(block_at(HEAL, HEAL.index("help")).text, "[@mouseover,help,nodead]")
        self.assertEqual(block_at(HEAL, HEAL.index("[")).text, "[@mouseover,help,nodead]")
        self.assertIsNone(block_at(HEAL, HEAL.index("Flash")))
        self.assertIsNone(block_at("/say [help]", 7))  # chat text, not a condition


class DescribeTest(unittest.TestCase):
    def setUp(self):
        self.ref = load_macro_reference("_retail_")

    def test_describe_at(self):
        command = "\n".join(describe_at(HEAL, 2, self.ref))
        self.assertIn("/cast", command)
        self.assertIn(self.ref.commands["/cast"].help, command)
        self.assertIn(self.ref.commands["/cast"].source, command)
        condition = "\n".join(describe_at(HEAL, HEAL.index("help") + 2, self.ref))
        self.assertIn(self.ref.conditionals["help"].help, condition)
        self.assertIn("Cast on the unit under the mouse, if it's friendly and not dead.", condition)
        unit = "\n".join(describe_at(HEAL, HEAL.index("mouseover"), self.ref))
        self.assertIn("the unit under the mouse", unit)
        spell = "\n".join(describe_at(HEAL, HEAL.index("Heal"), self.ref))
        self.assertIn("not checked", spell)
        self.assertIn("(not in the reference)", "\n".join(describe_at("/frobnicate", 3, self.ref)))
        self.assertEqual(describe_at("", 0, self.ref)[:1], [])  # nothing under the cursor: no lines
        used = "\n".join(describe_at("/use [@focus] 13", 7, self.ref))
        self.assertIn("Use on your focus", used)

    def test_reference_lines_carry_their_sources(self):
        rows = reference_lines(self.ref)
        self.assertEqual({section for section, *_ in rows}, {"Commands", "Conditionals", "Units"})
        self.assertTrue(all(source.startswith("https://") for *_, source, _ in rows))
        self.assertIn("/cast", [name for _, name, *_ in rows])
        self.assertIn("@mouseover", [name for _, name, *_ in rows])
        era = reference_lines(load_macro_reference("_classic_era_"))
        notes = {name: note for _, name, _, _, note in era}
        self.assertTrue(notes["advflyable"])  # the source leaves Classic Era out
        self.assertEqual(notes["help"], "")

    def test_completion_start(self):
        self.assertEqual(completion_start("/ca", 3), 0)
        self.assertEqual(completion_start("x\n  /ca", 7), 4)
        body = "/cast [@mo"
        self.assertEqual(completion_start(body, len(body)), body.index("mo"))
        body = "/cast [help, no"
        self.assertEqual(completion_start(body, len(body)), body.index("no"))
        body = "/cast [mod:sh"
        self.assertEqual(completion_start(body, len(body)), body.index("sh"))


class MacroEditScreenTest(MacroEditorTestBase):
    async def edit_bob(self, app, pilot, size=BASE):
        """The review (Retail) and the edit screen of Bob's "Bob" macro."""
        review = await self.open_review(app, pilot, "_retail_")
        tree = review.query_one("#macros", Tree)
        await goto(pilot, tree, macro_node(tree, character_node(tree, "Bob"), "Bob"))
        await pilot.press("e")
        await settle(app, pilot)
        screen = app.screen
        self.assertIsInstance(screen, MacroEditScreen)
        return review, screen

    async def set_body(self, app, pilot, screen, text: str, cursor: int | None = None) -> TextArea:
        area = screen.query_one("#macro-body", TextArea)
        area.text = text
        area.focus()
        offset = len(text) if cursor is None else cursor
        row = text.count("\n", 0, offset)
        col = offset - (text.rfind("\n", 0, offset) + 1)
        area.cursor_location = (row, col)
        await settle(app, pilot)
        return area

    async def test_meter_blocks_save_over_255(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, screen = await self.edit_bob(app, pilot)
            self.assertIn("Character macro", plain(screen.query_one("#macro-scope", Static)))
            assert_keys_on_buttons(self, screen)
            await self.set_body(app, pilot, screen, "x" * (BODY_LIMIT + 1))
            self.assertIn(f"{BODY_LIMIT + 1} / {BODY_LIMIT}", plain(screen.query_one("#macro-meter", Static)))
            self.assertTrue(screen.query_one("#ok").disabled)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            self.assertIs(app.screen, screen)  # Save is off over the limit
            await self.set_body(app, pilot, screen, "x" * BODY_LIMIT)
            self.assertFalse(screen.query_one("#ok").disabled)
            await pilot.press("ctrl+s")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.pending, 1)
            bob = next(s for s in review.all_sets() if s.label == "MAIN/Realm1/Bob")
            self.assertEqual([m.body for m in effective_macros(review.staged, bob) if m.name == "Bob"],
                             ["x" * BODY_LIMIT])

    async def test_name_cut_at_16(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            await goto(pilot, tree, character_node(tree, "Trâxex"))
            await pilot.press("N")
            await settle(app, pilot)
            screen = app.screen
            self.assertIsInstance(screen, MacroEditScreen)
            name = screen.query_one("#macro-name", Input)
            self.assertIs(screen.focused, name)
            self.assertEqual(screen.query_one("#macro-icon", Input).value, ICON_DEFAULT)
            await pilot.press(*"Celestial Conduit")  # 17 characters: the client keeps 16 (V4)
            await settle(app, pilot)
            self.assertEqual(name.value, "Celestial Condui")
            self.assertEqual(len(name.value), NAME_LIMIT)
            await self.set_body(app, pilot, screen, "/cast Celestial Conduit")
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            traxex = next(s for s in review.all_sets() if s.label == "MAIN/Realm2/Trâxex")
            self.assertEqual([m.name for m in effective_macros(review.staged, traxex)], ["Celestial Condui"])

    async def test_help_panel_follows_cursor(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            _, screen = await self.edit_bob(app, pilot)
            ref = load_macro_reference("_retail_")
            area = await self.set_body(app, pilot, screen, HEAL, 2)
            help_panel = screen.query_one("#help-text", Static)
            self.assertIn(ref.commands["/cast"].help, plain(help_panel))
            area.cursor_location = (0, HEAL.index("help") + 2)
            await settle(app, pilot)
            self.assertIn("Cast on the unit under the mouse, if it's friendly and not dead.", plain(help_panel))
            area.cursor_location = (0, HEAL.index("Heal") + 1)
            await settle(app, pilot)
            self.assertIn("not checked", plain(help_panel))
            # suggestions as you type: after "[@mo" the list offers mouseover; Tab takes it
            area = await self.set_body(app, pilot, screen, "/cast [@mo")
            await pilot.press("u")
            await settle(app, pilot)
            suggestions = screen.query_one("#suggestions", OptionList)
            self.assertTrue(suggestions.display)
            self.assertIn("mouseover", [str(suggestions.get_option_at_index(i).prompt).split()[0]
                                        for i in range(suggestions.option_count)])
            await pilot.press("tab")
            await settle(app, pilot)
            self.assertEqual(area.text, "/cast [@mouseover")
            self.assertIs(screen.focused, area)
            self.assertFalse(suggestions.display)
            await pilot.press("comma", "h", "e")
            await settle(app, pilot)
            self.assertTrue(suggestions.display)
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertEqual(area.text, "/cast [@mouseover,help")
            await pilot.press("right_square_bracket", "space", "H", "enter")  # no suggestion: Enter is a new line
            await settle(app, pilot)
            self.assertEqual(area.text, "/cast [@mouseover,help] H\n")

    async def test_builder_round_trip_block(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            _, screen = await self.edit_bob(app, pilot)
            area = await self.set_body(app, pilot, screen, HEAL, HEAL.index("help"))
            await pilot.press("ctrl+b")
            await settle(app, pilot)
            builder = app.screen
            self.assertIsInstance(builder, BuilderScreen)
            assert_keys_on_buttons(self, builder)
            self.assertEqual(builder.query_one("#target", RadioSet).pressed_button.label.plain, "@mouseover")
            self.assertEqual(builder.query_one("#unit", RadioSet).pressed_button.label.plain, "help")
            self.assertTrue(builder.query_one("#state-nodead", Checkbox).value)
            self.assertFalse(builder.query_one("#state-combat", Checkbox).value)
            await pilot.click("#ok")  # unchanged: the block stays as written
            await settle(app, pilot)
            self.assertIs(app.screen, screen)
            self.assertEqual(area.text, HEAL)
            area.cursor_location = (0, HEAL.index("nodead"))
            await pilot.press("ctrl+b")
            await settle(app, pilot)
            builder = app.screen
            focus = next(b for b in builder.query_one("#target", RadioSet).query(RadioButton)
                         if b.label.plain == "@focus")
            focus.value = True
            builder.query_one("#state-nodead", Checkbox).value = False
            builder.query_one("#state-combat", Checkbox).value = True
            await settle(app, pilot)
            self.assertIn("[@focus,help,combat]", plain(builder.query_one("#block-preview", Static)))
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(area.text, "/cast [@focus,help,combat] Flash Heal")
            # outside a block: OK inserts a new one at the cursor
            await self.set_body(app, pilot, screen, "/cast Flash Heal", len("/cast "))
            await pilot.press("ctrl+b")
            await settle(app, pilot)
            builder = app.screen
            cursor = next(b for b in builder.query_one("#target", RadioSet).query(RadioButton)
                          if b.label.plain == "@cursor")
            cursor.value = True
            await settle(app, pilot)
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(area.text, "/cast [@cursor] Flash Heal")

    async def test_optimize_apply_updates_text(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            _, screen = await self.edit_bob(app, pilot)
            area = await self.set_body(app, pilot, screen, "/cast [target=focus, harm] Kick")
            await pilot.press("ctrl+o")
            await settle(app, pilot)
            popup = app.screen
            self.assertIsInstance(popup, OptimizeScreen)
            assert_keys_on_buttons(self, popup)
            shown = plain(popup.query_one("#rewrites", Static))
            self.assertIn("target= is the older spelling of @", shown)
            self.assertIn("https://warcraft.wiki.gg/wiki/Macro_conditionals", shown)
            await pilot.click("#cancel")
            await settle(app, pilot)
            self.assertEqual(area.text, "/cast [target=focus, harm] Kick")  # Cancel changes nothing
            await pilot.press("ctrl+o")
            await settle(app, pilot)
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertIs(app.screen, screen)
            self.assertEqual(area.text, "/cast [@focus,harm] Kick")
            self.assertIn(f"{len('/cast [@focus,harm] Kick')} / {BODY_LIMIT}",
                          plain(screen.query_one("#macro-meter", Static)))
            await pilot.press("ctrl+o")  # nothing more to shorten: a notice, no popup
            await settle(app, pilot)
            self.assertIs(app.screen, screen)

    async def test_template_fill_inserts(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            _, screen = await self.edit_bob(app, pilot)
            area = await self.set_body(app, pilot, screen, "")
            await pilot.press("ctrl+t")
            await settle(app, pilot)
            popup = app.screen
            self.assertIsInstance(popup, TemplateScreen)
            assert_keys_on_buttons(self, popup)
            templates = load_templates()
            focus = next(i for i, t in enumerate(templates) if t.id == "focus-interrupt")
            popup.query_one("#templates", OptionList).highlighted = focus
            await settle(app, pilot)
            self.assertIn(templates[focus].source, plain(popup.query_one("#template-preview", Static)))
            first = popup.query_one("#value-1", Input)
            self.assertEqual(first.placeholder, "Interrupt")
            self.assertFalse(popup.query_one("#value-2", Input).display)
            await pilot.click("#ok")  # no value yet: refused, said why
            await settle(app, pilot)
            self.assertIs(app.screen, popup)
            self.assertIn("Interrupt needs a value", plain(popup.query_one("#template-error", Static)))
            first.value = "Kick"
            await settle(app, pilot)
            await pilot.press("ctrl+s")  # Insert's key
            await settle(app, pilot)
            self.assertIs(app.screen, screen)
            self.assertEqual(area.text, fill_template(templates[focus], {"Interrupt": "Kick"}))
            # into a body that has text: the template goes in as whole lines after the cursor's line
            await self.set_body(app, pilot, screen, "/sit\n/wave", 2)
            await pilot.press("ctrl+t")
            await settle(app, pilot)
            popup = app.screen
            popup.query_one("#templates", OptionList).highlighted = focus
            popup.query_one("#value-1", Input).value = "Kick"
            await settle(app, pilot)
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(area.text, "/sit\n" + fill_template(templates[focus], {"Interrupt": "Kick"}) + "\n/wave")

    async def test_80x24_still_usable(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review, screen = await self.edit_bob(app, pilot, TINY)
            controls = ["#macro-name", "#macro-icon", "#macro-body", "#ok", "#builder", "#optimize", "#template",
                        "#reference", "#cancel"]
            seen = set()
            screen.query_one("#macro-name").focus()
            await settle(app, pilot)
            for _ in range(len(controls) + 2):
                seen.add(f"#{screen.focused.id}")
                screen.focus_next()
                await pilot.pause()
            self.assertTrue(set(controls) <= seen, set(controls) - seen)
            for selector in controls:
                widget = screen.query_one(selector)
                self.assertTrue(widget.display and widget.region.width > 0 and widget.region.height > 0, selector)
            await pilot.press("f1")
            await settle(app, pilot)
            reference = app.screen
            self.assertIsInstance(reference, ReferenceScreen)
            text = plain(reference.query_one("#reference", Static))
            self.assertIn("/cast", text)
            self.assertIn("@mouseover", text)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIs(app.screen, screen)
            for key, kind in (("ctrl+b", BuilderScreen), ("ctrl+t", TemplateScreen)):
                await pilot.press(key)
                await settle(app, pilot)
                self.assertIsInstance(app.screen, kind)
                await pilot.press("escape")
                await settle(app, pilot)
                self.assertIs(app.screen, screen)
            await pilot.press("escape")  # Cancel: nothing staged
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.pending, 0)


if __name__ == "__main__":
    unittest.main()
