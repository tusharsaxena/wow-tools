"""The Macro Editor in the suite app (config tools spec ME2-ME7, ME13, ME14; X1-X5): flavor (All flavors allowed) →
the browse screen (account › Account macros and realm › character, slot use, one line per macro), the search on
names and bodies, Copy then Paste… into ticked sets with the paste review (clashes, slots, another game version),
New, Edit, Delete and Replace text… staged and marked, Apply / Dry run / Undo through the client-file pipeline, and
a file in a layout the reader doesn't know shown read-only. Every client file is synthesized in a tests/fixtures.py
temp tree (build_macro_tree), never a real install."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from textual.widgets import Checkbox, Input, OptionList, TextArea, Tree

from tests.fixtures import (BASE, COUNT_AFTER, LARGE, MACRO_ACCOUNT, MACRO_AELLA, MACRO_BOB, MACRO_UNKNOWN, TINY,
                            TuiTestCase, assert_fits_or_keeps_minimum, assert_siblings_distinct, build_macro_tree,
                            make_config, settle, submit_filter)
from wowtools.core.events import capture_events
from wowtools.core.install import flavor_name
from wowtools.core.macrofile import parse_macros
from wowtools.core.text import plural
from wowtools.tools import TOOLS
from wowtools.tools.macro_editor.edit_screen import MacroEditScreen
from wowtools.tools.macro_editor.model import MACRO_FILE
from wowtools.tools.macro_editor.popups import PasteScreen, ReplaceTextScreen
from wowtools.tools.macro_editor.report import ACCOUNT_MACROS, DELETE_WARNING, MACRO_MINIMUMS
from wowtools.tools.macro_editor.review_screen import (MacroNode, MacroResultScreen, MacroReviewScreen, SetKey,
                                                       SetNode)
from wowtools.ui import dialogs
from wowtools.ui.character_tree import CharacterNode
from wowtools.ui.columns import GROUP_NAME_MINIMUM
from wowtools.ui.dialogs import CONFIRM_GUARD, ConfirmScreen, DiscardScreen
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

    @mock.patch("wowtools.tools.macro_editor.model.limits_known", lambda folder: folder != "_classic_era_")
    async def test_browse_lists_sets_with_slot_counts(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            with capture_events() as events:
                review = await self.open_review(app, pilot)
            self.assertIn("macro.started", [e["event"] for e in events])
            tree = review.query_one("#macros", Tree)
            flavors = [n.label.plain.strip() for n in tree.root.children]
            self.assertEqual(len(flavors), 2)
            self.assertIn("Retail  6 items", [f[2:] for f in flavors])  # the mark, then the name and its count
            names = [n.data.character.name for n in walk(tree.root)
                     if isinstance(n.data, CharacterNode) and n.data.kind == "character"]
            self.assertEqual(sorted(names), sorted(["Aellâ", "Bob", "Trâxex", "Dænerys", "Other"]))  # no copies
            self.assertIn("Aellâ  3/30", character_node(tree, "Aellâ").label.plain)
            self.assertIn("Trâxex  0/30", character_node(tree, "Trâxex").label.plain)
            self.assertIn("Account macros  1/120", account_set_node(tree, "MAIN").label.plain)
            # ME3: a flavor with no sourced limits (Classic Era here, patched) counts with Retail's, marked unconfirmed
            self.assertTrue(character_node(tree, "Other", "_classic_era_").label.plain.endswith("/30 unconfirmed  1 item"))
            self.assertNotIn("unconfirmed", character_node(tree, "Aellâ").label.plain)
            self.assertNotIn("unconfirmed", account_set_node(tree, "MAIN").label.plain)
            heal = macro_node(tree, character_node(tree, "Aellâ"), "Heal Dænerys")
            # columns fitted to the pane (R4): at 120x30 with All flavors the first line gives way, cut at its end
            self.assertEqual(heal.label.plain[2:], "Heal Dænerys /cast [@mouseover,help,… 41/255")
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

    async def test_paste_button_waits_for_the_enter_guard(self):
        # With no clash the popup opens on Paste: a held or double Enter must not stage at once (STD-7.15, T23w5).
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            await self.copy_aella(app, pilot, review, "Fly")
            await self.tick(app, pilot, review, character_node(tree, "Trâxex"))
            now = [1000.0]
            self.confirm_guard(CONFIRM_GUARD)
            with mock.patch.object(dialogs, "monotonic", lambda: now[0]):
                await pilot.press("p")
                await settle(app, pilot)
                paste = app.screen
                self.assertIsInstance(paste, PasteScreen)
                self.assertEqual(paste.focused.id, "ok")
                await pilot.press("enter")
                await settle(app, pilot)
                self.assertIs(app.screen, paste)
                now[0] += CONFIRM_GUARD
                await pilot.press("enter")
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.pending, 1)

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


def indent(node) -> int:
    """The cells in front of a node's label: the tree guides, and the ▶ / ▼ of a node that opens."""
    depth, parent = 0, node.parent
    while parent is not None:
        depth, parent = depth + 1, parent.parent
    return depth * node.tree.guide_depth + (2 if node.allow_expand else 0)


class NodeCountsAndColumnsTest(MacroEditorTestBase):
    """Feedback round 2 R2 / R4 (STD-7.27, STD-7.28) on the Macro Editor's browse tree: every node with children
    (the root, a flavor, an account, Account macros, a realm, a character) counts the macro lines below it that the
    tree shows (after the search and Only matching macros; a staged delete included); a
    macro line is the leaf and its name · first line · length are aligned columns cut to the pane, as are a
    character's name · slots (or read-only) · count among its realm's characters."""

    def shown_macros(self, node) -> int:
        return sum(1 for n in walk(node) if isinstance(n.data, MacroNode))

    def assert_counts(self, tree) -> None:
        for node in walk(tree.root):
            if not node.children or isinstance(node.data, MacroNode) or node.data is None and node is not tree.root:
                continue
            with self.subTest(node=str(node.label)):
                expected = plural(self.shown_macros(node), "item")
                self.assertTrue(str(node.label).endswith(f"  {expected}"), str(node.label))
                count = node.label.spans[-1]
                self.assertEqual((str(node.label)[count.start:].strip(), str(count.style)), (expected, "dim"))

    async def test_every_node_counts_the_macros_below_it(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#macros", Tree)
            # Retail: Account macros 1, Aellâ 3, Bob 2 (Dænerys' file is in a layout the reader doesn't know: no
            # macro lines); Classic Era: Other 1
            self.assertTrue(str(tree.root.label).endswith("  7 items"), str(tree.root.label))
            flavors = {n.data[1]: str(n.label) for n in tree.root.children if isinstance(n.data, list)}
            self.assertTrue(flavors["_retail_"].endswith("  6 items"), flavors)
            self.assertTrue(flavors["_classic_era_"].endswith("  1 item"), flavors)
            self.assertTrue(str(character_node(tree, "Aellâ").label).endswith("  3 items"))
            self.assertTrue(str(character_node(tree, "Dænerys").label).endswith("read-only"))  # no lines, no count
            self.assertTrue(str(account_set_node(tree, "MAIN").label).endswith("  1 item"))
            self.assertNotIn("item", str(character_node(tree, "Trâxex").label))  # no macros: a leaf, no count
            for node in walk(tree.root):  # a macro line is the leaf: no count of its own
                if isinstance(node.data, MacroNode):
                    self.assertNotIn("item", str(node.label))
            self.assert_counts(tree)
            # a staged delete stays a line (struck) until Apply, so it is still counted; the slots say what is left
            bob = character_node(tree, "Bob")
            await goto(pilot, tree, macro_node(tree, bob, "Bob"))
            await pilot.press("d")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            bob = character_node(tree, "Bob")
            self.assertIn("1/30", str(bob.label))
            self.assertTrue(str(bob.label).endswith("  2 items"), str(bob.label))
            self.assert_counts(tree)

    async def test_counts_follow_the_search(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            self.assertTrue(str(tree.root.label).endswith("  6 items"), str(tree.root.label))
            submit_filter(review, "flash")
            await settle(app, pilot)
            self.assertTrue(str(tree.root.label).endswith("  2 items"), str(tree.root.label))
            self.assertTrue(str(character_node(tree, "Aellâ").label).endswith("  1 item"))
            self.assert_counts(tree)
            submit_filter(review, "Bob")  # a character's name: all of its macros
            await settle(app, pilot)
            self.assertTrue(str(character_node(tree, "Bob").label).endswith("  2 items"))
            self.assert_counts(tree)
            review.query_one("#only-matching", Checkbox).value = False  # every macro shown, the matches marked
            await settle(app, pilot)
            self.assertTrue(str(tree.root.label).endswith("  6 items"), str(tree.root.label))
            self.assert_counts(tree)
            review.query_one("#only-matching", Checkbox).value = True
            review.query_one("#search-names", Checkbox).value = False
            review.query_one("#search-bodies", Checkbox).value = False
            submit_filter(review, "flash")
            await settle(app, pilot)
            self.assertTrue(str(tree.root.label).endswith("  0 items"), str(tree.root.label))

    async def test_rows_are_aligned_columns(self):
        app = self.make_app()
        async with app.run_test(size=LARGE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#macros", Tree)
            aella = character_node(tree, "Aellâ")
            rows = [macro_node(tree, aella, name) for name in ("Heal Dænerys", "D Up", "Fly")]
            await settle(app, pilot)
            labels = [str(n.label) for n in rows]
            for label in labels:
                self.assertNotIn(" · ", label)
                self.assertFalse(label.endswith(" "), label)
            self.assertEqual(len({label.index("/cast") for label in labels}), 1, labels)  # first lines line up
            self.assertEqual(len({label.rindex("/255") for label in labels}), 1, labels)  # lengths line up
            self.assertRegex(labels[0], r"^. Heal Dænerys  /cast \[@mouseover,help,nodead\] Flash Heal +41/255$")
            # a staged mark before one line: its siblings keep the mark's room, so the names still line up
            await goto(pilot, tree, rows[1])
            await pilot.press("d")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            aella = character_node(tree, "Aellâ")
            labels = [str(macro_node(tree, aella, name).label) for name in ("Heal Dænerys", "D Up", "Fly")]
            self.assertIn("✗ D Up", labels[1])
            self.assertEqual(len({label.index(name) for label, name in zip(labels, ("Heal Dænerys", "D Up", "Fly"))}),
                             1, labels)
            self.assertEqual(len({label.index("/cast") for label in labels}), 1, labels)
            # a realm's characters: name · slots · count, the slots and the counts lined up
            chars = [str(character_node(tree, name).label) for name in ("Aellâ", "Bob")]
            self.assertEqual(len({label.index("/30") for label in chars}), 1, chars)
            self.assertEqual(len({label.rindex("item") for label in chars}), 1, chars)
            self.assertRegex(chars[1], r"^. Bob +2/30 +2 items$")
            spans = {chars[1][s.start:s.end].strip(): str(s.style) for s in character_node(tree, "Bob").label.spans}
            self.assertEqual(spans.get("2 items"), "dim", spans)
            self.assertRegex(str(character_node(tree, "Dænerys").label), r"^ +Dænerys  read-only$")

    async def test_rows_fit_the_pane(self):
        """Every line fits the pane at 120x30; at 80x24 a macro line 16 to 20 cells deep keeps its name's 6 cells
        (a character or a realm its name's 4) and scrolls sideways instead of reading `He…s` (STD-7.28, user
        decision U1)."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#macros", Tree)
            for name in ("Aellâ", "Bob", "Dænerys"):
                character_node(tree, name).expand()
            account_set_node(tree, "MAIN").expand()
            await settle(app, pilot)
            for size in (BASE, TINY):
                await pilot.resize_terminal(*size)
                await settle(app, pilot)
                room = tree.size.width - tree.styles.scrollbar_size_vertical
                for node in walk(tree.root):
                    data = node.data
                    if data is None:
                        continue
                    if isinstance(data, MacroNode):
                        name, minimum = data.macro.name, MACRO_MINIMUMS[0]
                    else:
                        name = ACCOUNT_MACROS if isinstance(data, SetNode) else \
                            data.text if isinstance(data, CharacterNode) else flavor_name(data[1])
                        minimum = GROUP_NAME_MINIMUM
                    with self.subTest(size=size, row=str(node.label)):
                        if size == BASE:
                            self.assertLessEqual(indent(node) + node.label.cell_len, room)
                        assert_fits_or_keeps_minimum(self, node, indent(node), room, name, minimum,
                                                     after=COUNT_AFTER if node.allow_expand else "")
                assert_siblings_distinct(self, [n for n in walk(tree.root) if isinstance(n.data, MacroNode)])
                if size == BASE:  # at 120 columns the names and lengths read in full
                    aella = character_node(tree, "Aellâ")
                    for node in aella.children:
                        plain = str(node.label)
                        self.assertIn(node.data.macro.name, plain)
                        self.assertRegex(plain, r"\d+/255$")
                    self.assertTrue(str(aella.label).endswith("3/30  3 items"), str(aella.label))
