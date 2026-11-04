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
from wowtools.tools.config_editor.report import CHANGED, DEFAULT_STATE, NOT_SET, UNKNOWN, row_cells
from wowtools.tools.config_editor.review_screen import (CvarNode, ConfigResultScreen, ConfigReviewScreen, FileKey,
                                                        FileNode)
from wowtools.ui.character_tree import CharacterNode
from wowtools.ui.dialogs import ConfirmScreen, DiscardScreen, TextPromptScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp
from wowtools.ui.theme import CVAR_CATEGORY_COLOURS, CVAR_STATE_COLOURS
from wowtools.ui.tree_filter import NO_MATCH_TEXT

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


def cells(label: str) -> list[str]:
    """A CVar row's columns, read back from its line (two or more spaces, or one, apart: the cells hold no runs of
    spaces in these tests)."""
    return label.split()


def indent(node) -> int:
    """The tree guides' width in front of a node's label."""
    depth, parent = 0, node.parent
    while parent is not None:
        depth, parent = depth + 1, parent.parent
    return depth * node.tree.guide_depth


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
            self.assertEqual(cells(rows["cameraDistanceMaxZoomFactor"])[1:], ["2.6", "1.9", CHANGED, "camera"])
            self.assertEqual(cells(rows["myAddonThing"]), ["myAddonThing", "Dænerys", UNKNOWN, "other"])
            for node in await open_rows(pilot, aella):  # CE4, CF1: each row ends with its category column
                self.assertTrue(node.label.plain.endswith(f" {node.data.row.category}"), node.label.plain)
            machine = file_node(tree, CONFIG_WTF)
            self.assertEqual(cells((await cvar_node(pilot, machine, "gxMaximize")).label.plain),
                             ["gxMaximize", "1", "0", CHANGED, "graphics"])
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

    async def test_rows_are_aligned_coloured_columns(self):
        """CF1-CF3: a file's rows are five aligned columns (name, value, default, state, category), a 300-character
        value is cut with … and the state and category still show, the state and category carry their colours, and
        a row fits the tree pane at 120x30; at 80x24 (the floor) the rows are fitted again and still fit the pane
        (columns dropped, the name cut: FB2r)."""
        blob = "v21##" + "7" * 295
        self.aella().write_bytes(CONFIG_AELLA + f'SET collapsedCurrencyCategoryDefaults "{blob}"\r\n'.encode())
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            await open_rows(pilot, character_node(tree, "Aellâ"))
            await settle(app, pilot)
            nodes = [n for n in character_node(tree, "Aellâ").children if isinstance(n.data, CvarNode)]
            room = tree.size.width - tree.styles.scrollbar_size_vertical
            starts = set()
            for node in nodes:
                label = node.label
                name, _, _, state, category = row_cells(node.data.row)
                with self.subTest(name=name):
                    self.assertTrue(label.plain.endswith(category), label.plain)
                    starts.add(len(label.plain) - len(category))  # every row's category starts in one column
                    self.assertIn(state, label.plain)
                    self.assertLessEqual(indent(node) + label.cell_len, room)
                    styles = {label.plain[span.start:span.end].strip(): str(span.style) for span in label.spans}
                    self.assertEqual(styles[state], CVAR_STATE_COLOURS[state])
                    self.assertEqual(styles[category], CVAR_CATEGORY_COLOURS[category])
            self.assertEqual(len(starts), 1, starts)
            blob_row = next(n for n in nodes if n.data.row.name == "collapsedCurrencyCategoryDefaults")
            long, blob_category = blob_row.label.plain, blob_row.data.row.category
            self.assertIn("…", long)
            self.assertNotIn(blob, long)
            self.assertEqual(cells(long)[-2:], [UNKNOWN, blob_category])  # the state and category still show
            await pilot.resize_terminal(*TINY)
            await settle(app, pilot)
            room = tree.size.width - tree.styles.scrollbar_size_vertical
            for node in nodes:  # fitted again to the narrower pane: every row still fits it (FB2r)
                with self.subTest(name=node.data.row.name, size=TINY):
                    self.assertLessEqual(indent(node) + node.label.cell_len, room)
            small = next(n for n in nodes if n.data.row.name == "collapsedCurrencyCategoryDefaults").label.plain
            self.assertLess(len(small), len(long))
            self.assertTrue(small.strip().startswith("col"), small)  # the name's start is what is left

    async def test_rows_fit_with_two_flavors_and_show_all_known(self):
        """FB2r: a character file one level deeper (All flavors, two flavors) with Show all known ticked: at 120x30
        every row fits its pane, the state and category whole (the default column gives way first), names sharing a
        long start are cut in their middle and stay apart; at 80x30 every row still fits (only the name is left)."""
        data = dict(KB_CVARS)
        for name in ("raidFramesDisplayAggroHighlight", "raidFramesDisplayClassColor"):
            data[name] = {"default": "1", "help": "", "category": "game", "scope": "character", "synced": True}
        (self.kb / "cvars" / "_retail_.json").write_text(json.dumps(
            {"source": "client dump _retail_ 1", "cvars": data}), encoding="utf-8")
        clear_cache()
        era = self.root / "_classic_era_" / "WTF"
        (era / "Account" / "ACCT" / "Realm1" / "Other").mkdir(parents=True)
        (era / CONFIG_WTF).write_bytes(b'SET gxMaximize "0"\r\n')
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, ALL_FLAVORS)
            review.query_one("#show-all", Checkbox).value = True
            await settle(app, pilot)
            tree = review.query_one("#cvars", Tree)
            nodes = await open_rows(pilot, character_node(tree, "Aellâ"))
            await settle(app, pilot)
            self.assertIn("raidFramesDisplayClassColor", {n.data.row.name for n in nodes})
            room = tree.size.width - tree.styles.scrollbar_size_vertical
            for node in nodes:
                name, _, _, state, category = row_cells(node.data.row)
                with self.subTest(name=name, size=BASE):
                    self.assertLessEqual(indent(node) + node.label.cell_len, room)
                    self.assertEqual(node.label.plain.split()[-len(category.split()) - 1:],
                                     [state, *category.split()])
            names = {n.data.row.name: cells(n.label.plain)[0] for n in nodes}
            self.assertNotEqual(names["raidFramesDisplayAggroHighlight"], names["raidFramesDisplayClassColor"])
            await pilot.resize_terminal(80, 30)
            await settle(app, pilot)
            room = tree.size.width - tree.styles.scrollbar_size_vertical
            for node in nodes:
                with self.subTest(name=node.data.row.name, size=(80, 30)):
                    self.assertLessEqual(indent(node) + node.label.cell_len, room)
                    self.assertTrue(node.label.plain.strip(), node.label.plain)

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
            self.assertEqual(cells(row.label.plain)[2], "0")  # ✎, the name (cut to fit), then the value
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
            self.assertEqual(cells(row.label.plain)[2:], [*NOT_SET.split(), "1.9", DEFAULT_STATE, "camera"])
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

    async def test_reset_checks_each_ticked_file_flavor(self):
        # Classic Era has no CVar data, so no default: Reset across both flavors stages only Retail's file,
        # whichever file's row is highlighted (T21 review fix)
        era = self.root / "_classic_era_" / "WTF"
        (era / "Account" / "ACCT" / "Realm1" / "Other").mkdir(parents=True)
        (era / CONFIG_WTF).write_bytes(b'SET cameraDistanceMaxZoomFactor "2.0"\r\n')
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, ALL_FLAVORS)
            tree = review.query_one("#cvars", Tree)
            era_file = next(n for n in walk(tree.root) if isinstance(n.data, FileNode)
                            and n.data.target.flavor.folder == "_classic_era_" and n.data.target.label == CONFIG_WTF)
            for node in (era_file, character_node(tree, "Aellâ")):
                await self.press_on(app, pilot, review, node, "space")
            self.assertEqual(len(review.ticked), 2)
            await self.press_on(app, pilot, review, await cvar_node(pilot, era_file, "cameraDistanceMaxZoomFactor"),
                                "R")
            self.assertEqual(review.staged.removes, {self.aella(): {"cameraDistanceMaxZoomFactor"}})
            self.assertTrue(any("no known default in 1 file" in n.message for n in app._notifications))
            # only the Era file ticked: refused, nothing more staged
            await self.press_on(app, pilot, review, character_node(tree, "Aellâ"), "space")
            self.assertEqual(len(review.ticked), 1)
            await self.press_on(app, pilot, review, await cvar_node(pilot, era_file, "cameraDistanceMaxZoomFactor"),
                                "R")
            self.assertEqual(review.staged.removes, {self.aella(): {"cameraDistanceMaxZoomFactor"}})
            self.assertTrue(any("Remove (d) takes its line out" in n.message for n in app._notifications))

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

    async def test_each_category_lists_its_cvars_at_every_level(self):
        """CF4a: with Show all known ticked, every category lists its CVars in Config.wtf, an account's config and a
        character's file. The client files them all under `game` (the curated groups, CF4b, place them)."""
        levels = {"machine": CONFIG_WTF, "account": "MAIN", "character": "Aellâ"}
        groups = {"sound": "Sound_Test", "camera": "cameraTest", "nameplates": "nameplateTest",
                  "combat text": "WorldTextTest", "network": "netTest", "graphics": "gxTest", "other": "debugTest"}
        cvars = dict(KB_CVARS)
        curated = {}
        for group, stem in groups.items():
            for level in levels:
                name = f"{stem}{level.capitalize()}"
                cvars[name] = {"default": "1", "help": "", "category": "game", "scope": level, "synced": True}
                curated[name] = group
        (self.kb / "cvars" / "_retail_.json").write_text(json.dumps(
            {"source": "client dump _retail_ 1", "cvars": cvars}), encoding="utf-8")
        (self.kb / "cvar_categories.json").write_text(json.dumps({"comment": "test", "categories": curated}),
                                                      encoding="utf-8")
        clear_cache()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            review.query_one("#show-all", Checkbox).value = True
            await settle(app, pilot)
            for group, stem in groups.items():
                review.query_one("#category", Select).value = group
                await settle(app, pilot)
                for level, label in levels.items():
                    with self.subTest(group=group, level=level):
                        owner = file_node(tree, label) if level != "character" else character_node(tree, label)
                        names = [n.data.row.name for n in await open_rows(pilot, owner)]
                        self.assertIn(f"{stem}{level.capitalize()}", names)
                        self.assertEqual({n.data.row.category for n in await open_rows(pilot, owner)}, {group})

    async def test_a_search_left_applied_is_named_when_a_category_shows_nothing(self):
        """The user's smoke test (CF4a, from its log): a search ("gra") applied earlier stays applied, so Sound,
        Camera ... showed only "Nothing matches the filter". That line stays (STD-7.8); the help panel names the
        search and the category that together match nothing, and how to clear each."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            review.query_one("#show-all", Checkbox).value = True
            submit_filter(review, "gra")
            await settle(app, pilot)
            review.query_one("#category", Select).value = "sound"
            await settle(app, pilot)
            self.assertEqual([str(n.label) for n in tree.root.children], [NO_MATCH_TEXT])
            help_text = str(review.query_one("#cvar-help-text", Static).render())
            self.assertIn('the search "gra"', help_text)
            self.assertIn("Sound", help_text)
            self.assertIn("Esc in the filter box", help_text)
            self.assertIn("All categories", help_text)
            review.query_one("#changed-only", Checkbox).value = True
            await settle(app, pilot)
            self.assertIn("Changed only", str(review.query_one("#cvar-help-text", Static).render()))
            review.query_one("#changed-only", Checkbox).value = False
            review.query_one("#category", Select).clear()
            submit_filter(review, "")
            await settle(app, pilot)
            review.query_one("#category", Select).value = "sound"  # the category alone: Config.wtf's sound CVars
            await settle(app, pilot)
            self.assertNotIn(NO_MATCH_TEXT, [str(n.label) for n in tree.root.children])
            self.assertIn("Sound_MasterVolume",
                          [n.data.row.name for n in await open_rows(pilot, file_node(tree, CONFIG_WTF))])
            self.assertNotIn('the search', str(review.query_one("#cvar-help-text", Static).render()))

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

    async def test_help_panel_layout(self):
        """CF5: the help panel's Text has the CVar's name as a bold title, bold labels, the state and the category in
        their row colours, a blank line between sections and a bullet per source; a file's panel a bold title too.
        Under the tree the panel is tall enough for the sections at 120x30 and the tree keeps the larger part."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#cvars", Tree)
            aella = character_node(tree, "Aellâ")
            await self.press_on(app, pilot, review, await cvar_node(pilot, aella, "cameraDistanceMaxZoomFactor"))
            text = review.help_text()
            plain = text.plain

            def styles_of(fragment: str, inner: str | None = None) -> list[str]:
                """The styles over `inner` (else the whole fragment) where `fragment` first appears."""
                start = plain.index(fragment) + (fragment.index(inner) if inner else 0)
                end = start + len(inner or fragment)
                return [str(span.style) for span in text.spans if span.start <= start and span.end >= end]

            self.assertTrue(plain.startswith("cameraDistanceMaxZoomFactor\n\n"), plain)
            self.assertIn("bold", styles_of("cameraDistanceMaxZoomFactor"))
            for label in ("Value:", "Default:", "State:", "Category:", "Note:", "Scope:", "Sources:"):
                self.assertIn("bold", styles_of(label), label)
            self.assertIn(CVAR_STATE_COLOURS[CHANGED].lower(), " ".join(styles_of("State: changed", "changed")).lower())
            self.assertIn(CVAR_CATEGORY_COLOURS["camera"].lower(),
                          " ".join(styles_of("Category: camera", "camera")).lower())
            self.assertIn("\n\nScope:", plain)
            self.assertIn("\n\nSources:\n  • Note: https://warcraft.wiki.gg", plain)
            self.assertNotIn("bold", " ".join(styles_of("Default: 1.9", "1.9")))  # values are in normal weight
            shown = review.query_one("#cvar-help-text", Static)
            self.assertIn("Sources:", str(shown.render()))
            under = review.query_one("#cvar-help")
            self.assertGreaterEqual(under.region.height, 8)
            self.assertGreater(tree.region.height, under.region.height)
            # FB3r1: the recommendation sits with the value and the default, so the panel (which scrolls with the
            # mouse only) shows it at 120x30 without scrolling, with the value section and the note
            wrapped = [line.plain for line in text.wrap(app.console, under.scrollable_content_region.width)]
            visible = wrapped[:under.scrollable_content_region.height]
            for start in ("Value:", "Default:", "Recommended: 2.6. See more.", "State:", "Category:", "Note:"):
                self.assertTrue(any(line.startswith(start) for line in visible), (start, visible))
            await self.press_on(app, pilot, review, aella)
            text = review.help_text()
            self.assertTrue(text.plain.startswith("Retail › MAIN/Realm1/Aellâ\n\nFile: config-cache.wtf"),
                            text.plain)
            self.assertIn("bold", [str(span.style) for span in text.spans if span.start == 0])

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
