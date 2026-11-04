"""The Config Copier in the suite app (config tools spec CC2-CC8, X1-X3): flavor (All flavors allowed) → source
picker (the shared character tree, one choice) → review (files ticked in the left pane; targets in the tree, each with
its file pairs and their status; other flavors' characters and the source greyed) → Copy / Dry run (confirm with the
CC7 warnings) → result, Diff on a replaced pair (config pairs mark the state lines kept), and Undo. Every client file
is synthesized in a tests/fixtures.py temp tree (build_copier_tree), never a real install."""
from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

from textual.widgets import Checkbox, Tree

from tests.fixtures import (BASE, COPIER_ADDONS, COPIER_CHAT, COPIER_MACROS, TINY, TuiTestCase, build_copier_tree,
                            make_config, settle)
from wowtools.core.events import capture_events
from wowtools.tools import TOOLS
from wowtools.tools.config_copier.diff_screen import DiffScreen
from wowtools.tools.config_copier.model import COPY_FILES, MACRO_WARNING
from wowtools.tools.config_copier.review_screen import CopierReviewScreen, CopierResultScreen, PairNode
from wowtools.tools.config_copier.source_screen import SourceScreen
from wowtools.ui.character_tree import CharacterNode
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp

TOOL = "config-copier"


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(current.children)))


def character_node(tree: Tree, name: str):
    return next(n for n in walk(tree.root) if isinstance(n.data, CharacterNode) and n.data.kind == "character"
                and n.data.character.name == name)


def pair_node(tree: Tree, character: str, file: str):
    owner = character_node(tree, character)
    owner.expand()
    return next(n for n in owner.children if isinstance(n.data, PairNode) and n.data.plan.name == file)


async def goto(pilot, tree: Tree, node) -> None:
    """Highlight `node` (once an expand above it has been laid out)."""
    await pilot.pause()
    tree.move_cursor(node)
    await pilot.pause()


class CopierAppTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_copier_tree(tmp / "World of Warcraft")
        self.accounts = self.root / "_retail_" / "WTF" / "Account"
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self, wow_check=list):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={TOOL: {"wow_check": wow_check}})

    def tree_bytes(self) -> dict[str, bytes]:
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob("*"))
                if p.is_file() and "wow-tools" not in p.parts}

    async def open_sources(self, app, pilot, flavor=ALL_FLAVORS) -> SourceScreen:
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
        self.assertIsInstance(app.screen, SourceScreen)
        return app.screen

    async def open_review(self, app, pilot, flavor=ALL_FLAVORS, source="Aellâ") -> CopierReviewScreen:
        sources = await self.open_sources(app, pilot, flavor)
        tree = sources.query_one("#sources", Tree)
        tree.focus()
        tree.move_cursor(character_node(tree, source))
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        review = app.screen
        self.assertIsInstance(review, CopierReviewScreen)
        return review

    async def tick(self, app, pilot, review, *names) -> None:
        tree = review.query_one("#targets", Tree)
        tree.focus()
        for name in names:
            tree.move_cursor(character_node(tree, name))
            await pilot.pause()
            await pilot.press("space")
            await settle(app, pilot)

    async def test_registered_in_the_menu(self):
        tool = TOOLS[TOOL]
        self.assertEqual((tool.title, tool.section), ("Config Copier", "config_copier"))
        # shorter than the plan's line: it fits one row of the tool menu at 120 columns (T11)
        self.assertEqual(tool.description, "Copy one character's macros, chat, layout, CVars and addons to others.")

    async def test_flow_source_targets_review_copy(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            sources = await self.open_sources(app, pilot)
            labels = [n.data.character.name for n in walk(sources.query_one("#sources", Tree).root)
                      if isinstance(n.data, CharacterNode) and n.data.kind == "character"]
            self.assertEqual(sorted(labels), sorted(["Aellâ", "Bob", "Trâxex", "Dænerys", "Other"]))  # no copies
            await pilot.press("escape")  # back to the flavor picker
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            app.screen.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            sources = app.screen
            tree = sources.query_one("#sources", Tree)
            tree.focus()
            tree.move_cursor(character_node(tree, "Aellâ"))
            await pilot.pause()
            with capture_events() as events:
                await pilot.press("enter")
                await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, CopierReviewScreen)
            self.assertIn("copier.started", [e["event"] for e in events])
            self.assertTrue(all(box.value for box in review.query(Checkbox)))  # every file ticked (CC3)
            self.assertEqual(review.selected_plans(), [])  # no target ticked yet (CC2)
            self.assertTrue(review.query_one("#btn-copy").disabled)
            await self.tick(app, pilot, review, "Bob", "Trâxex")
            selected = review.selected_plans()
            self.assertEqual({(p.target.name, p.status) for p in selected},
                             {("Bob", "replace"), ("Bob", "new"), ("Trâxex", "new")})
            self.assertEqual(len(selected), 10)
            self.assertFalse(review.query_one("#btn-copy").disabled)
            await pilot.press("w")
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.kind, "overwrite")
            confirm.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, CopierResultScreen)
            for target in ("MAIN/Realm1/Bob", "MAIN/Realm2/Trâxex"):
                for name, data in (("macros-cache.txt", COPIER_MACROS), ("AddOns.txt", COPIER_ADDONS),
                                   ("chat-cache.txt", COPIER_CHAT)):
                    self.assertEqual((self.accounts / target / name).read_bytes(), data, (target, name))
            self.assertEqual((self.accounts / "MAIN" / "Realm1" / "Bob - Copy" / "macros-cache.txt").read_bytes(),
                             COPIER_MACROS)
            self.assertFalse((self.accounts / "ALT" / "Realm1" / "Dænerys" / "macros-cache.txt").exists())
            app.screen.dismiss("rescan")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.selected_plans(), [])  # everything copied is now unchanged
            self.assertIsNotNone(review.undoable)

    async def test_unticked_pair_and_file_left_alone(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.tick(app, pilot, review, "Bob")
            tree = review.query_one("#targets", Tree)
            await goto(pilot, tree, pair_node(tree, "Bob", "macros-cache.txt"))
            await pilot.press("space")  # drop one pair (CC4)
            await settle(app, pilot)
            box = review.query_one("#file-AddOns-txt", Checkbox)
            box.value = False  # and one file for every target
            await settle(app, pilot)
            self.assertEqual([p.name for p in review.selected_plans()],
                             ["chat-cache.txt", "config-cache.wtf", "layout-local.txt"])
            review.action_copy()
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            bob = "_retail_/WTF/Account/MAIN/Realm1/Bob/"
            after = self.tree_bytes()
            self.assertEqual(after[bob + "macros-cache.txt"], before[bob + "macros-cache.txt"])
            self.assertEqual(after[bob + "AddOns.txt"], before[bob + "AddOns.txt"])
            self.assertEqual(after[bob + "chat-cache.txt"], COPIER_CHAT)

    async def test_dry_run_then_undo(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.tick(app, pilot, review, "Bob", "Trâxex")
            await pilot.press("y")
            await settle(app, pilot)
            self.assertEqual(app.screen.kind, "simulate")
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, CopierResultScreen)
            self.assertEqual(self.tree_bytes(), before)
            await pilot.press("escape")  # Back to review: the ticks are kept
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(len(review.selected_plans()), 10)
            review.action_copy()
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertNotEqual(self.tree_bytes(), before)
            app.screen.dismiss("rescan")
            await settle(app, pilot)
            await pilot.press("z")
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.kind, "destructive")
            confirm.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, CopierResultScreen)
            self.assertEqual(self.tree_bytes(), before)  # replaced files back, created ones gone
            self.assertFalse(any((self.accounts / "MAIN" / "Realm2" / "Trâxex").iterdir()))

    async def test_refused_while_wow_runs(self):
        before = self.tree_bytes()
        app = self.make_app(wow_check=lambda: ["Wow.exe"])
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.tick(app, pilot, review, "Bob")
            with capture_events() as events:
                review.action_copy()
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIn("copier.wow_running", [e["event"] for e in events])
            self.assertEqual(self.tree_bytes(), before)

    async def test_diff_screen_for_replaced_pair(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            tree.focus()
            await goto(pilot, tree, pair_node(tree, "Trâxex", "AddOns.txt"))  # new: nothing to compare
            await pilot.press("d")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            await goto(pilot, tree, pair_node(tree, "Bob", "macros-cache.txt"))
            await pilot.press("d")
            await settle(app, pilot)
            diff = app.screen
            self.assertIsInstance(diff, DiffScreen)
            text = diff.diff_text().plain
            self.assertIn("- /sit", text)
            self.assertIn("+ /cast [@mouseover] Flash Heal", text)
            self.assertIn("Heal Dænerys", text)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            await goto(pilot, tree, pair_node(tree, "Bob", "config-cache.wtf"))
            await pilot.press("d")
            await settle(app, pilot)
            text = app.screen.diff_text().plain
            kept = next(line for line in text.splitlines() if "hardTrackedQuests" in line)
            self.assertTrue(kept.startswith("  "), kept)
            self.assertIn("kept", kept)
            self.assertIn('- SET enableMultiActionBars "15"', text)
            self.assertIn('+ SET assistedCombatHighlight "1"', text)
            self.assertNotIn("savedClassConfigOne", text)  # the source's state is never copied

    async def test_diff_screen_names_a_line_ending_only_change(self):
        """T11 review: a replaced pair whose files differ only in line endings says so, not "the same"; a
        config-cache.wtf one keeps its rows and adds the line."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            plans = {(p.target.name, p.name): p for p in review.plans.values()}
            for name in ("macros-cache.txt", "config-cache.wtf"):
                with self.subTest(name=name):
                    plan = plans["Bob", name]
                    crlf = (plan.old or b"").replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                    pair = dataclasses.replace(plan, new=crlf.replace(b"\r\n", b"\n"), old=crlf)
                    app.push_screen(DiffScreen(pair, "MAIN › Realm1/Aellâ"))
                    await settle(app, pilot)
                    text = app.screen.diff_text().plain
                    self.assertIn("Only line endings or bytes that are not text differ.", text)
                    self.assertNotIn("The files are the same.", text)
                    self.assertIn("0 lines removed, 0 lines added", app.screen.head_text().plain)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertIs(app.screen, review)

    async def test_other_flavor_targets_greyed(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            other = character_node(tree, "Other")
            self.assertEqual(other.data.reason, "other flavor")
            self.assertEqual(other.data.keys, ())
            source = character_node(tree, "Aellâ")
            self.assertEqual(source.data.reason, "source")
            self.assertIn("other flavor", other.label.plain)
            tree.focus()
            tree.move_cursor(other)
            await pilot.pause()
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(review.selected_plans(), [])
            await pilot.press("a")  # select all: the source's flavor only
            await settle(app, pilot)
            self.assertEqual({p.target.name for p in review.selected_plans()}, {"Bob", "Trâxex", "Dænerys"})
            self.assertFalse(any(p.target.name == "Other" for p in review.selected_plans()))

    async def test_pair_statuses_in_the_tree(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            chat = pair_node(tree, "Dænerys", "chat-cache.txt")
            self.assertEqual(chat.data.key, None)  # unchanged: nothing to tick
            self.assertIn("unchanged", chat.label.plain)
            macros = pair_node(tree, "Bob", "macros-cache.txt")
            self.assertIn("replaced", macros.label.plain)
            self.assertIn("⚠", macros.label.plain)
            self.assertIn("new (merged)", pair_node(tree, "Trâxex", "config-cache.wtf").label.plain)
            self.assertEqual([n.data.plan.name for n in character_node(tree, "Bob").children], list(COPY_FILES))

    async def test_macro_warning_in_confirm(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.tick(app, pilot, review, "Bob", "Trâxex")
            review.action_copy()
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual([(e.message, e.where, e.item) for e in confirm.listed],
                             [(MACRO_WARNING, "MAIN › Realm1/Bob", "macros-cache.txt")])
            self.assertIn("MAIN › Realm1/Bob", confirm.groups)
            confirm.dismiss(False)
            await settle(app, pilot)
            self.assertIs(app.screen, review)

    async def test_one_flavor_and_tiny(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot, flavor="_retail_")
            tree = review.query_one("#targets", Tree)
            self.assertFalse(any(isinstance(n.data, CharacterNode) and n.data.character is not None
                                 and n.data.character.name == "Other" for n in walk(tree.root)))
            self.assertTrue(review.sub_title.startswith("Config Copier · Retail"), review.sub_title)
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsNone(app.flow)


if __name__ == "__main__":
    import unittest
    unittest.main()
