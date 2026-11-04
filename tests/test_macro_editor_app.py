"""The Macro Editor in the suite app (config tools spec ME2-ME7, ME13, ME14; X1-X5): flavor (All flavors allowed) →
the browse screen (account › Account macros and realm › character, slot use, one line per macro), the search on
names and bodies, Copy then Paste… into ticked sets with the paste review (clashes, slots, another game version),
New, Edit, Delete and Replace text… staged and marked, Apply / Dry run / Undo through the client-file pipeline, and
a file in a layout the reader doesn't know shown read-only. Every client file is synthesized in a tests/fixtures.py
temp tree (build_macro_tree), never a real install."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Checkbox, Input, OptionList, TextArea, Tree

from tests.fixtures import (BASE, MACRO_ACCOUNT, MACRO_AELLA, MACRO_BOB, MACRO_UNKNOWN, TINY, TuiTestCase,
                            build_macro_tree, make_config, settle, submit_filter)
from wowtools.core.events import capture_events
from wowtools.core.macrofile import parse_macros
from wowtools.tools import TOOLS
from wowtools.tools.macro_editor.edit_screen import MacroEditScreen
from wowtools.tools.macro_editor.model import MACRO_FILE
from wowtools.tools.macro_editor.popups import PasteScreen, ReplaceTextScreen
from wowtools.tools.macro_editor.report import DELETE_WARNING
from wowtools.tools.macro_editor.review_screen import (MacroNode, MacroResultScreen, MacroReviewScreen, SetKey,
                                                       SetNode)
from wowtools.ui.character_tree import CharacterNode
from wowtools.ui.dialogs import ConfirmScreen, DiscardScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp
from wowtools.ui.warnings_view import WarningsScreen

TOOL = "macro-editor"


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(current.children)))


def character_node(tree: Tree, name: str, flavor: str | None = None):
    for node in walk(tree.root):
        data = node.data
        if (isinstance(data, CharacterNode) and data.kind == "character" and data.character.name == name
                and (flavor is None or data.character.path.parts[-6] == flavor)):
            return node
    raise AssertionError(f"no character {name}")


def account_set_node(tree: Tree, account: str):
    return next(n for n in walk(tree.root) if isinstance(n.data, SetNode) and n.data.mset.account.name == account)


def macro_node(tree: Tree, owner, name: str):
    owner.expand()
    return next(n for n in owner.children if isinstance(n.data, MacroNode) and n.data.macro.name == name)


async def goto(pilot, tree: Tree, node) -> None:
    await pilot.pause()
    tree.move_cursor(node)
    await pilot.pause()


class MacroEditorTestBase(TuiTestCase):
    """The temp WoW folder (build_macro_tree), the app and the steps to the browse screen; shared with
    tests/test_macro_editor_edit.py."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_macro_tree(tmp / "World of Warcraft")
        self.accounts = self.root / "_retail_" / "WTF" / "Account"
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self, wow_check=list):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={TOOL: {"wow_check": wow_check}})

    def tree_bytes(self) -> dict[str, bytes]:
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob("*"))
                if p.is_file() and "wow-tools" not in p.parts}

    def file(self, rel: str) -> Path:
        return self.accounts / rel / MACRO_FILE

    async def open_review(self, app, pilot, flavor: str = ALL_FLAVORS) -> MacroReviewScreen:
        await pilot.pause()
        app.open_tool(TOOL)
        await settle(app, pilot)
        if not isinstance(app.screen, FlavorScreen):
            app.screen._save()  # first open: the tool's settings, saved as they are
            await settle(app, pilot)
        picker = app.screen
        self.assertIsInstance(picker, FlavorScreen)
        picker.dismiss(flavor if flavor == ALL_FLAVORS else next(f for f in picker.flavors if f.folder == flavor))
        await settle(app, pilot)
        review = app.screen
        self.assertIsInstance(review, MacroReviewScreen)
        review.query_one("#macros", Tree).focus()
        return review

    async def tick(self, app, pilot, review, *nodes) -> None:
        tree = review.query_one("#macros", Tree)
        tree.focus()
        for node in nodes:
            await goto(pilot, tree, node)
            await pilot.press("space")
            await settle(app, pilot)

    async def copy_aella(self, app, pilot, review, *names) -> None:
        tree = review.query_one("#macros", Tree)
        aella = character_node(tree, "Aellâ", "_retail_")
        await self.tick(app, pilot, review, *(macro_node(tree, aella, name) for name in names))
        await pilot.press("k")
        await settle(app, pilot)
        self.assertEqual([m.name for _, m in review.clipboard], list(names))
        self.assertEqual(review.ticked, set())  # the next ticks pick the targets

    async def apply(self, app, pilot, review) -> None:
        await pilot.press("w")
        await settle(app, pilot)
        confirm = app.screen
        self.assertIsInstance(confirm, ConfirmScreen)
        self.assertEqual(confirm.kind, "destructive")
        confirm.dismiss(True)
        await settle(app, pilot)
        self.assertIsInstance(app.screen, MacroResultScreen)


class MacroEditorAppTest(MacroEditorTestBase):
    async def test_registered_in_the_menu(self):
        tool = TOOLS[TOOL]
        self.assertEqual((tool.title, tool.section), ("Macro Editor", "macro_editor"))
        self.assertEqual(tool.description,
                         "Browse, edit, copy and paste macros across characters, accounts and flavors.")

    async def test_browse_lists_sets_with_slot_counts(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            with capture_events() as events:
                review = await self.open_review(app, pilot)
            self.assertIn("macro.started", [e["event"] for e in events])
            tree = review.query_one("#macros", Tree)
            flavors = [n.label.plain.strip() for n in tree.root.children]
            self.assertEqual(len(flavors), 2)
            self.assertTrue(any(f.endswith("Retail") for f in flavors), flavors)
            names = [n.data.character.name for n in walk(tree.root)
                     if isinstance(n.data, CharacterNode) and n.data.kind == "character"]
            self.assertEqual(sorted(names), sorted(["Aellâ", "Bob", "Trâxex", "Dænerys", "Other"]))  # no copies
            self.assertIn("Aellâ  3/30", character_node(tree, "Aellâ").label.plain)
            self.assertIn("Trâxex  0/30", character_node(tree, "Trâxex").label.plain)
            self.assertIn("Account macros  1/120", account_set_node(tree, "MAIN").label.plain)
            heal = macro_node(tree, character_node(tree, "Aellâ"), "Heal Dænerys")
            self.assertIn("Heal Dænerys · /cast [@mouseover,help,nodead] Flash Heal · 41/255", heal.label.plain)
            self.assertTrue(review.query_one("#btn-apply").disabled)  # nothing staged
            self.assertTrue(review.sub_title.startswith("Macro Editor · All flavors"))

    async def test_search_bodies(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            submit_filter(review, "flash")
            await settle(app, pilot)

            def shown() -> list[str]:
                return sorted(n.data.macro.name for n in walk(tree.root) if isinstance(n.data, MacroNode))
            self.assertEqual(shown(), ["D Up", "Heal Dænerys"])  # Bob's D Up and Aellâ's heal: bodies
            review.query_one("#search-bodies", Checkbox).value = False
            await settle(app, pilot)
            self.assertEqual(shown(), [])
            submit_filter(review, "d up")
            await settle(app, pilot)
            self.assertEqual(shown(), ["D Up", "D Up"])  # names
            review.query_one("#only-matching", Checkbox).value = False  # show all, the matches marked
            await settle(app, pilot)
            self.assertGreater(len(shown()), 2)
            up = macro_node(tree, character_node(tree, "Bob"), "D Up")
            self.assertTrue(any("underline" in str(span.style) for span in up.label.spans), up.label.spans)

    async def test_copy_paste_to_two_characters(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            await self.copy_aella(app, pilot, review, "Heal Dænerys", "Fly")
            await self.tick(app, pilot, review, character_node(tree, "Trâxex"), account_set_node(tree, "MAIN"))
            self.assertEqual({k.path.parent.name for k in review.ticked if isinstance(k, SetKey)}, {"Trâxex", "MAIN"})
            await pilot.press("p")
            await settle(app, pilot)
            paste = app.screen
            self.assertIsInstance(paste, PasteScreen)
            self.assertEqual(paste.result.clashes, [])
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.pending, 4)
            traxex = character_node(tree, "Trâxex")
            traxex.expand()
            await settle(app, pilot)
            labels = [n.label.plain for n in traxex.children]
            self.assertIn("+ Heal Dænerys", labels[0])
            self.assertIn("+ Fly", labels[1])
            self.assertIn("2/30", traxex.label.plain)
            await self.apply(app, pilot, review)
            written = parse_macros(self.file("MAIN/Realm2/Trâxex").read_bytes())
            self.assertEqual([(m.id, m.name) for m in written.macros],
                             [("0100000000000001", "Heal Dænerys"), ("0100000000000002", "Fly")])
            account = parse_macros(self.file("MAIN").read_bytes())
            self.assertEqual([m.id for m in account.macros], ["0000000000000001", "0000000000000002",
                                                               "0000000000000003"])  # account prefix (ME6)
            self.assertTrue(self.file("MAIN").read_bytes().startswith(MACRO_ACCOUNT))  # unchanged bytes kept
            self.assertEqual(self.file("MAIN/Realm1/Aellâ").read_bytes(), MACRO_AELLA)
            app.screen.dismiss("rescan")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.pending, 0)
            self.assertIsNotNone(review.undoable)

    async def test_clash_overwrite_keeps_id_end_to_end(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            await self.copy_aella(app, pilot, review, "D Up")
            await self.tick(app, pilot, review, character_node(tree, "Bob"))
            await pilot.press("p")
            await settle(app, pilot)
            paste = app.screen
            self.assertIsInstance(paste, PasteScreen)
            self.assertEqual([(c.pasted.name, c.choice) for c in paste.result.clashes], [("D Up", "skip")])
            self.assertIn("[skip] MAIN/Realm1/Bob: D Up", str(paste.query_one(OptionList).get_option_at_index(0).prompt))
            await pilot.click("#choose-overwrite")
            await settle(app, pilot)
            self.assertEqual([c.choice for c in paste.result.clashes], ["overwrite"])
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertIn("✎ D Up", macro_node(tree, character_node(tree, "Bob"), "D Up").label.plain)
            await self.apply(app, pilot, review)
            bob = parse_macros(self.file("MAIN/Realm1/Bob").read_bytes())
            self.assertEqual([(m.id, m.name, m.icon, m.body) for m in bob.macros],
                             [("0100000000000001", "Bob", "134400", "/sit"),
                              ("0100000000000007", "D Up", "132360", "/cast Divine Protection")])  # Bob's id kept

    async def test_cross_flavor_paste_warns(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#macros", Tree)
            await self.copy_aella(app, pilot, review, "Fly")
            await self.tick(app, pilot, review, character_node(tree, "Other", "_classic_era_"))
            await pilot.press("p")
            await settle(app, pilot)
            paste = app.screen
            self.assertIsInstance(paste, PasteScreen)
            notes = str(paste.query_one("#paste-notes").render())
            self.assertIn("From Retail into Classic Era", notes)
            self.assertIn("advflyable", notes)
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(review.pending, 1)  # allowed between any two flavors (ME5)

    async def test_apply_dry_run_undo(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            bob = character_node(tree, "Bob")
            # Edit: Bob's "Bob" macro gets a new body; its id stays
            await goto(pilot, tree, macro_node(tree, bob, "Bob"))
            await pilot.press("e")
            await settle(app, pilot)
            form = app.screen
            self.assertIsInstance(form, MacroEditScreen)
            form.query_one("#macro-body", TextArea).text = "/sit\n/wave"
            await settle(app, pilot)
            self.assertIn("10 / 255", str(form.query_one("#macro-meter").render()))
            form.query_one("#macro-body", TextArea).text = "x" * 256  # over the limit: Save is off (ME8)
            await settle(app, pilot)
            self.assertTrue(form.query_one("#ok").disabled)
            form.query_one("#macro-body", TextArea).text = "/sit\n/wave"
            await settle(app, pilot)
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            # New on Trâxex
            await goto(pilot, tree, character_node(tree, "Trâxex"))
            await pilot.press("N")
            await settle(app, pilot)
            form = app.screen
            self.assertIsInstance(form, MacroEditScreen)
            form.query_one("#macro-name", Input).value = "Hello"
            form.query_one("#macro-body", TextArea).text = "/wave"
            await settle(app, pilot)
            await pilot.click("#ok")
            await settle(app, pilot)
            # Delete Bob's D Up (the ME6 warning)
            await goto(pilot, tree, macro_node(tree, character_node(tree, "Bob"), "D Up"))
            await pilot.press("d")
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertIn(DELETE_WARNING, confirm.alerts)
            confirm.dismiss(True)
            await settle(app, pilot)
            self.assertIn("✗ D Up", macro_node(tree, character_node(tree, "Bob"), "D Up").label.plain)
            # Replace text on Aellâ's heal
            await goto(pilot, tree, macro_node(tree, character_node(tree, "Aellâ"), "Heal Dænerys"))
            await pilot.press("R")
            await settle(app, pilot)
            replace = app.screen
            self.assertIsInstance(replace, ReplaceTextScreen)
            replace.query_one("#find", Input).value = "Flash Heal"
            replace.query_one("#replace", Input).value = "Holy Light"
            await settle(app, pilot)
            self.assertIn("1 macro change", str(replace.query_one("#replace-preview").render()))
            await pilot.click("#ok")
            await settle(app, pilot)
            self.assertEqual(review.pending, 4)
            self.assertFalse(review.query_one("#btn-apply").disabled)
            # Dry run: nothing written, the staged edits kept
            await pilot.press("y")
            await settle(app, pilot)
            self.assertEqual(app.screen.kind, "simulate")
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, MacroResultScreen)
            self.assertEqual(self.tree_bytes(), before)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.pending, 4)
            await self.apply(app, pilot, review)
            bob_now = parse_macros(self.file("MAIN/Realm1/Bob").read_bytes())
            self.assertEqual([(m.id, m.body) for m in bob_now.macros], [("0100000000000001", "/sit\n/wave")])
            self.assertIn(b"Holy Light", self.file("MAIN/Realm1/Aellâ").read_bytes())
            self.assertTrue(self.file("MAIN/Realm2/Trâxex").is_file())
            app.screen.dismiss("rescan")
            await settle(app, pilot)
            await pilot.press("z")
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            confirm.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, MacroResultScreen)
            self.assertEqual(self.tree_bytes(), before)  # changed files back, the created one gone
            self.assertEqual(self.file("MAIN/Realm1/Bob").read_bytes(), MACRO_BOB)

    async def test_unknown_layout_read_only(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            daenerys = character_node(tree, "Dænerys")
            self.assertIn("read-only", daenerys.label.plain)
            self.assertEqual(review.node_tick_keys(daenerys), ())
            await goto(pilot, tree, daenerys)
            await pilot.press("N")
            await settle(app, pilot)
            self.assertIs(app.screen, review)  # refused: nothing to stage
            self.assertEqual(review.pending, 0)
            items = review.warning_items()
            self.assertEqual(len(items), 1)
            self.assertIn("read-only", items[0].what)
            await pilot.press("exclamation_mark")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, WarningsScreen)
            app.screen.dismiss(None)
            await settle(app, pilot)
            # a paste into it is refused for that set, never written
            await self.copy_aella(app, pilot, review, "D Up")
            review.ticked.add(SetKey(self.file("ALT/Realm1/Dænerys")))  # not tickable in the tree: forced here
            self.assertEqual(review.ticked_sets(), [])
            self.assertEqual(self.file("ALT/Realm1/Dænerys").read_bytes(), MACRO_UNKNOWN)

    async def test_leaving_with_staged_edits_asks_first(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            await goto(pilot, tree, macro_node(tree, character_node(tree, "Bob"), "Bob"))
            await pilot.press("d")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            await pilot.press("f")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, DiscardScreen)
            app.screen.dismiss(False)
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.pending, 1)

    async def test_refused_while_wow_runs(self):
        before = self.tree_bytes()
        app = self.make_app(wow_check=lambda: ["Wow.exe"])
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            await goto(pilot, tree, macro_node(tree, character_node(tree, "Bob"), "Bob"))
            await pilot.press("d")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            with capture_events() as events:
                review.action_apply()
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIn("macro.wow_running", [e["event"] for e in events])
            self.assertEqual(self.tree_bytes(), before)

    async def test_one_flavor_at_80x24(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            self.assertGreater(tree.region.width, 20)
            for button in ("#btn-apply", "#act-new", "#act-paste"):
                self.assertTrue(review.query_one(button).display)
