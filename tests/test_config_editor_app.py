"""The Config Editor in the suite app (config tools spec CE2-CE8; X1-X5, X8): flavor (All flavors allowed) → the
browse screen (Config.wtf, account › Account config, realm › character config, each file opening to its CVar rows),
the filters (category, changed only, show all known, the search), the help panel, Space on a boolean, Set, Add,
Remove, Reset and Recommend… staged and marked, Apply / Dry run / Undo through the client-file pipeline, and a CVar
the knowledge base doesn't know shown and editable. Every client file is synthesized in a tests/fixtures.py temp
tree (build_config_tree) and the knowledge base is a temp folder too, never a real install."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from textual.widgets import Checkbox, Input, Select, Static, Tree

from tests.fixtures import (BASE, CONFIG_AELLA, CONFIG_MACHINE, LARGE, TINY, TuiTestCase, build_config_tree,
                            make_config, settle, submit_filter)
from wowtools.core.kb import clear_cache
from wowtools.tools import TOOLS
from wowtools.tools.config_editor.model import CONFIG_CACHE, CONFIG_WTF
from wowtools.tools.config_editor.popups import AddCvarScreen, RecommendScreen
from wowtools.tools.config_editor.report import CHANGED, UNKNOWN
from wowtools.tools.config_editor.review_screen import (CvarNode, ConfigResultScreen, ConfigReviewScreen, FileKey,
                                                        FileNode)
from wowtools.ui.character_tree import CharacterNode
from wowtools.ui.dialogs import ConfirmScreen, DiscardScreen, TextPromptScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp

TOOL = "config-editor"
KB_CVARS = {
    "nameplateShowFriends": {"default": "0", "help": "Show friendly nameplates", "category": "game",
                             "scope": "character", "synced": True},
    "nameplateShowAll": {"default": "0", "help": "", "category": "game", "scope": "account", "synced": True},
    "cameraDistanceMaxZoomFactor": {"default": "1.9", "help": "", "category": "game", "scope": "character",
                                    "synced": True,
                                    "wiki": {"text": "How far the camera can zoom out.",
                                             "source": "https://warcraft.wiki.gg/wiki/CVar_cameraDistanceMaxZoomFactor"}},
    "assistedCombatHighlight": {"default": "1", "help": "", "category": "game", "scope": "character", "synced": True},
    "autoLootDefault": {"default": "0", "help": "", "category": "game", "scope": "account", "synced": True},
    "floatingCombatTextCombatDamage": {"default": "1", "help": "", "category": "game", "scope": "character",
                                       "synced": True},
    "gxMaximize": {"default": "0", "help": "", "category": "graphics", "scope": "machine", "synced": False},
    "Sound_MasterVolume": {"default": "1.0", "help": "", "category": "sound", "scope": "machine", "synced": False},
}
KB_RECOMMENDATIONS = [
    {"cvar": "nameplateShowFriends", "value": "0", "flavors": ["_retail_"], "reason": "Less clutter.",
     "source": "https://example.org/a"},
    {"cvar": "cameraDistanceMaxZoomFactor", "value": "2.6", "flavors": ["_retail_"], "reason": "See more.",
     "source": "https://example.org/b"},
    {"cvar": "floatingCombatTextCombatDamage", "value": "0", "flavors": ["_retail_"], "reason": "Quieter.",
     "source": "https://example.org/c"},
    {"cvar": "autoLootDefault", "value": "1", "flavors": ["_retail_"], "reason": "Faster loot.",
     "source": "https://example.org/d"},
]


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(current.children)))


def character_node(tree: Tree, name: str):
    for node in walk(tree.root):
        data = node.data
        if isinstance(data, CharacterNode) and data.kind == "character" and data.character.name == name:
            return node
    raise AssertionError(f"no character {name}")


def file_node(tree: Tree, label: str):
    return next(n for n in walk(tree.root) if isinstance(n.data, FileNode) and n.data.target.label == label)


async def open_rows(pilot, owner) -> list:
    """Open a file's node (its rows load on expand) and return its CVar row nodes."""
    owner.expand()
    await pilot.pause()
    await pilot.pause()
    return [n for n in owner.children if isinstance(n.data, CvarNode)]


async def cvar_node(pilot, owner, name: str):
    return next(n for n in await open_rows(pilot, owner) if n.data.row.name == name)


async def goto(pilot, tree: Tree, node) -> None:
    await pilot.pause()
    tree.move_cursor(node)
    await pilot.pause()


class ConfigEditorAppTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_config_tree(tmp / "World of Warcraft")
        self.wtf = self.root / "_retail_" / "WTF"
        self.accounts = self.wtf / "Account"
        self.kb = tmp / "kb"
        (self.kb / "cvars").mkdir(parents=True)
        (self.kb / "cvars" / "_retail_.json").write_text(json.dumps(
            {"source": "client dump _retail_ 1", "cvars": KB_CVARS}), encoding="utf-8")
        (self.kb / "recommendations.json").write_text(json.dumps(
            {"comment": "test", "recommendations": KB_RECOMMENDATIONS}), encoding="utf-8")
        clear_cache()
        self.addCleanup(clear_cache)
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self, wow_check=list):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={TOOL: {"wow_check": wow_check, "kb_root": self.kb}})

    def tree_bytes(self) -> dict[str, bytes]:
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob("*"))
                if p.is_file() and "wow-tools" not in p.parts}

    def aella(self) -> Path:
        return self.accounts / "MAIN" / "Realm1" / "Aellâ" / CONFIG_CACHE

    async def open_review(self, app, pilot, flavor: str = "_retail_") -> ConfigReviewScreen:
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
        self.assertIsInstance(review, ConfigReviewScreen)
        review.query_one("#cvars", Tree).focus()
        return review

    async def press_on(self, app, pilot, review, node, *keys) -> None:
        tree = review.query_one("#cvars", Tree)
        tree.focus()
        await goto(pilot, tree, node)
        await pilot.press(*keys)
        await settle(app, pilot)

    async def apply(self, app, pilot) -> None:
        await pilot.press("w")
        await settle(app, pilot)
        confirm = app.screen
        self.assertIsInstance(confirm, ConfirmScreen)
        self.assertEqual(confirm.kind, "destructive")
        confirm.dismiss(True)
        await settle(app, pilot)
        self.assertIsInstance(app.screen, ConfigResultScreen)

    async def test_registered_in_the_menu(self):
        tool = TOOLS[TOOL]
        self.assertEqual((tool.title, tool.section), ("Config Editor", "config_editor"))
        self.assertEqual(tool.description, "See and change CVars in Config.wtf and each account and character, with help.")

    async def test_tree_three_levels(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            top = [n.label.plain.lstrip("✔✘◐ ").strip() for n in tree.root.children]
            self.assertEqual(top, [CONFIG_WTF, "ALT", "BARE", "MAIN"])  # the machine file first, then the accounts
            main = tree.root.children[3]
            self.assertTrue(main.children[0].label.plain.strip().endswith("Account config"))
            self.assertEqual(main.children[0].data.target.level, "account")
            labels = [n.label.plain for n in walk(tree.root)]
            self.assertFalse([label for label in labels if "Bob - Copy" in label or "Bob2" in label])
            aella = character_node(tree, "Aellâ")
            self.assertEqual(aella.data.keys, (FileKey(self.aella()),))
            rows = {n.data.row.name: n.label.plain for n in await open_rows(pilot, aella)}
            self.assertIn(f"cameraDistanceMaxZoomFactor = 2.6 (default 1.9)  {CHANGED}",
                          rows["cameraDistanceMaxZoomFactor"])
            self.assertIn(f"myAddonThing = Dænerys  {UNKNOWN}", rows["myAddonThing"])
            machine = file_node(tree, CONFIG_WTF)
            self.assertIn("gxMaximize = 1 (default 0)", (await cvar_node(pilot, machine, "gxMaximize")).label.plain)
            await self.press_on(app, pilot, review, await cvar_node(pilot, aella, "cameraDistanceMaxZoomFactor"))
            help_text = str(review.query_one("#cvar-help-text", Static).render())
            self.assertIn("How far the camera can zoom out.", help_text)
            self.assertIn("warcraft.wiki.gg", help_text)
            # All flavors: the flavor is the top level
            era = self.root / "_classic_era_" / "WTF"
            (era / "Account" / "ACCT" / "Realm1" / "Other").mkdir(parents=True)
            (era / CONFIG_WTF).write_bytes(b'SET gxMaximize "0"\r\n')
            await pilot.press("f")
            await settle(app, pilot)
            review = await self.open_review(app, pilot, ALL_FLAVORS)
            tree = review.query_one("#cvars", Tree)
            self.assertEqual(tree.root.children[0].data[0], "flavor")
            self.assertIn(CONFIG_WTF, tree.root.children[0].children[0].label.plain)

    async def test_toggle_and_apply(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            aella = character_node(tree, "Aellâ")
            await self.press_on(app, pilot, review, await cvar_node(pilot, aella, "assistedCombatHighlight"), "space")
            self.assertEqual(review.staged.sets, {self.aella(): {"assistedCombatHighlight": "0"}})
            row = await cvar_node(pilot, character_node(tree, "Aellâ"), "assistedCombatHighlight")
            self.assertIn("✎", row.label.plain)
            self.assertIn("assistedCombatHighlight = 0", row.label.plain)
            # Space on a CVar that is not 0/1 stages nothing
            await self.press_on(app, pilot, review, await cvar_node(pilot, character_node(tree, "Aellâ"),
                                                             "cameraDistanceMaxZoomFactor"), "space")
            self.assertEqual(review.staged.count(), 1)
            await self.apply(app, pilot)
            self.assertEqual(self.aella().read_bytes(),
                             CONFIG_AELLA.replace(b'assistedCombatHighlight "1"', b'assistedCombatHighlight "0"'))
            app.screen.dismiss("rescan")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.staged.count(), 0)

    async def test_reset_to_default_and_undo(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            row = await cvar_node(pilot, character_node(tree, "Aellâ"), "cameraDistanceMaxZoomFactor")
            await self.press_on(app, pilot, review, row, "R")
            self.assertEqual(review.staged.removes, {self.aella(): {"cameraDistanceMaxZoomFactor"}})
            row = await cvar_node(pilot, character_node(tree, "Aellâ"), "cameraDistanceMaxZoomFactor")
            self.assertIn("not set (default 1.9)", row.label.plain)
            await self.apply(app, pilot)
            self.assertNotIn(b"cameraDistanceMaxZoomFactor", self.aella().read_bytes())
            app.screen.dismiss("rescan")
            await settle(app, pilot)
            self.assertIsNotNone(review.undoable)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfigResultScreen)
            self.assertEqual(self.aella().read_bytes(), CONFIG_AELLA)

    async def test_recommend_batch_staged(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            await self.press_on(app, pilot, review, character_node(tree, "Aellâ"), "m")
            popup = app.screen
            self.assertIsInstance(popup, RecommendScreen)
            # autoLootDefault is an account CVar: not offered for a character's file
            self.assertEqual([r.recommendation.cvar for r in popup.rows],
                             ["nameplateShowFriends", "cameraDistanceMaxZoomFactor", "floatingCombatTextCombatDamage"])
            self.assertTrue(popup.rows[1].done)  # Aellâ already has 2.6
            text = str(popup.query_one("#rec-detail", Static).render())
            self.assertIn("Less clutter.", text)
            self.assertIn("https://example.org/a", text)
            await pilot.press("space")  # tick the first
            await pilot.press("down", "space")  # the done one can't be ticked
            await pilot.press("down", "space")
            await settle(app, pilot)
            self.assertEqual(popup.ticked, {0, 2})
            popup.query_one("#ok").press()
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.staged.sets, {self.aella(): {"nameplateShowFriends": "0",
                                                                 "floatingCombatTextCombatDamage": "0"}})

    async def test_unknown_cvar_editable_labelled(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            row = await cvar_node(pilot, character_node(tree, "Aellâ"), "myAddonThing")
            await self.press_on(app, pilot, review, row)
            self.assertIn("Unknown CVar", str(review.query_one("#cvar-help-text", Static).render()))
            await pilot.press("e")  # Set
            await settle(app, pilot)
            prompt = app.screen
            self.assertIsInstance(prompt, TextPromptScreen)
            self.assertEqual(prompt.query_one("#prompt", Input).value, "Dænerys")
            prompt.query_one("#prompt", Input).value = "Trâxex"
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertEqual(review.staged.sets, {self.aella(): {"myAddonThing": "Trâxex"}})
            # Add: an unknown CVar on Bob (no file yet), and an account CVar there (a scope warning, not a refusal)
            bob = character_node(tree, "Bob")
            for name in ("brandNewThing", "nameplateShowAll"):
                await self.press_on(app, pilot, review, character_node(tree, "Bob"), "N")
                add = app.screen
                self.assertIsInstance(add, AddCvarScreen)
                add.query_one("#cvar-name", Input).value = name
                add.query_one("#cvar-value", Input).value = "1"
                await settle(app, pilot)
                if name == "nameplateShowAll":
                    self.assertIn("account level", str(add.query_one("#cvar-note", Static).render()))
                else:
                    self.assertIn(UNKNOWN, str(add.query_one("#cvar-note", Static).render()))
                add.query_one("#ok").press()
                await settle(app, pilot)
            self.assertEqual(review.staged.sets[bob.data.character.path / CONFIG_CACHE],
                             {"brandNewThing": "1", "nameplateShowAll": "1"})
            await pilot.press("w")
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual([(e.where, e.item) for e in confirm.listed],
                             [("Retail › MAIN/Realm1/Bob", "nameplateShowAll")])
            confirm.dismiss(True)
            await settle(app, pilot)
            self.assertEqual((bob.data.character.path / CONFIG_CACHE).read_bytes(),
                             b'SET brandNewThing "1"\r\nSET nameplateShowAll "1"\r\n')
            self.assertIn(b'SET myAddonThing "Tr\xc3\xa2xex"\r\n', self.aella().read_bytes())

    async def test_dry_run_changes_nothing(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            before = self.tree_bytes()
            tree = review.query_one("#cvars", Tree)
            await self.press_on(app, pilot, review, await cvar_node(pilot, file_node(tree, CONFIG_WTF), "gxMaximize"),
                                "space")
            await self.press_on(app, pilot, review, await cvar_node(pilot, character_node(tree, "Aellâ"), "myAddonThing"),
                                "d")
            self.assertEqual(review.staged.count(), 2)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertEqual(app.screen.kind, "simulate")
            app.screen.dismiss(True)
            await settle(app, pilot)
            result = app.screen
            self.assertIsInstance(result, ConfigResultScreen)
            self.assertEqual(self.tree_bytes(), before)
            await pilot.press("escape")  # back to review: the staged changes stay
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.staged.count(), 2)
            self.assertFalse((self.root / "_retail_" / "wow-tools").exists())

    async def test_set_on_the_ticked_files(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            for name in ("Aellâ", "Trâxex"):
                await self.press_on(app, pilot, review, character_node(tree, name), "space")
            self.assertEqual(len(review.ticked), 2)
            await self.press_on(app, pilot, review, await cvar_node(pilot, character_node(tree, "Aellâ"),
                                                             "nameplateShowFriends"), "e")
            prompt = app.screen
            self.assertIsInstance(prompt, TextPromptScreen)
            self.assertIn("2 files", prompt.body_text)
            prompt.query_one("#prompt", Input).value = "0"
            await pilot.press("enter")
            await settle(app, pilot)
            traxex = self.accounts / "MAIN" / "Realm2" / "Trâxex" / CONFIG_CACHE
            # Trâxex already has 0: nothing to stage there
            self.assertEqual(review.staged.sets, {self.aella(): {"nameplateShowFriends": "0"}})
            self.assertNotIn(traxex, review.staged.sets)

    async def test_filters(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)

            async def names(owner_label: str) -> list[str]:
                return [n.data.row.name for n in await open_rows(pilot, character_node(tree, owner_label))]
            self.assertEqual(await names("Aellâ"), ["assistedCombatHighlight", "cameraDistanceMaxZoomFactor",
                                              "myAddonThing", "nameplateShowFriends"])
            review.query_one("#category", Select).value = "camera"
            await settle(app, pilot)
            self.assertEqual(await names("Aellâ"), ["cameraDistanceMaxZoomFactor"])
            review.query_one("#category", Select).clear()
            review.query_one("#changed-only", Checkbox).value = True
            await settle(app, pilot)
            self.assertEqual(await names("Aellâ"), ["cameraDistanceMaxZoomFactor", "nameplateShowFriends"])
            review.query_one("#changed-only", Checkbox).value = False
            review.query_one("#show-all", Checkbox).value = True
            await settle(app, pilot)
            self.assertEqual(await names("Aellâ"), ["assistedCombatHighlight", "cameraDistanceMaxZoomFactor",
                                              "floatingCombatTextCombatDamage", "myAddonThing",
                                              "nameplateShowFriends"])
            review.query_one("#show-all", Checkbox).value = False
            submit_filter(review, "zoom out")  # the search reads descriptions too
            await settle(app, pilot)
            self.assertEqual(await names("Aellâ"), ["cameraDistanceMaxZoomFactor"])
            self.assertTrue(character_node(tree, "Aellâ").is_expanded)
            self.assertFalse([n for n in walk(tree.root) if isinstance(n.data, FileNode)
                              and n.data.target.level == "machine"])

    async def test_leaving_with_staged_edits_asks_first(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            await self.press_on(app, pilot, review, await cvar_node(pilot, character_node(tree, "Aellâ"),
                                                             "assistedCombatHighlight"), "space")
            await pilot.press("f")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, DiscardScreen)
            app.screen.dismiss(False)
            await settle(app, pilot)
            self.assertIs(app.screen, review)

    async def test_refused_while_wow_runs(self):
        app = self.make_app(wow_check=lambda: ["Wow.exe"])
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            before = self.tree_bytes()
            tree = review.query_one("#cvars", Tree)
            await self.press_on(app, pilot, review, await cvar_node(pilot, file_node(tree, CONFIG_WTF), "gxMaximize"),
                                "space")
            await pilot.press("w")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(self.tree_bytes(), before)
            self.assertEqual((self.wtf / CONFIG_WTF).read_bytes(), CONFIG_MACHINE)

    async def test_help_panel_moves_beside_the_tree_when_wide(self):
        """Under the tree up to 159 columns, the right column from 160 on (the plan's ≥ 160 cols)."""
        for size, side in ((BASE, False), (LARGE, True)):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    review = await self.open_review(app, pilot)
                    await settle(app, pilot)
                    under, beside = review.query_one("#cvar-help"), review.query_one("#side-help")
                    self.assertEqual((under.display, beside.display), (not side, side))
                    shown = review.query_one("#side-help-text" if side else "#cvar-help-text", Static)
                    tree = review.query_one("#cvars", Tree)
                    await self.press_on(app, pilot, review, character_node(tree, "Aellâ"))
                    self.assertIn("config-cache.wtf", str(shown.render()))
                    if side:
                        self.assertGreater(beside.region.x, tree.region.right - 1)

    async def test_tiny_still_works(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            self.assertGreater(tree.region.height, 3)
            await self.press_on(app, pilot, review, await cvar_node(pilot, character_node(tree, "Aellâ"),
                                                             "assistedCombatHighlight"), "space")
            self.assertEqual(review.staged.count(), 1)
