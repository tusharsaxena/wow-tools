"""Ace3 Profile Manager screens (flow, settings, review, popups, apply, undo, recovery)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Input, Tree

from tests.fixtures import TuiTestCase, build_ace_tree, make_config, settle
from wowtools.core.config import Config
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles.app import ProfileSettingsScreen
from wowtools.tools.ace_profiles.popups import ActionsScreen, NameScreen, TargetScreen
from wowtools.tools.ace_profiles.review_screen import ProfileReviewScreen
from wowtools.tools.ace_profiles.settings import load_settings
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp

TOOL = "ace-profiles"


class AceAppBase(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.root = build_ace_tree(self.tmp / "World of Warcraft")
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        self.running: list[str] = []

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={TOOL: {"wow_check": lambda: list(self.running)}})

    async def open_review(self, app, pilot, choice=ALL_FLAVORS):
        await pilot.pause()
        app.open_tool(TOOL)
        await settle(app, pilot)
        if isinstance(app.screen, ProfileSettingsScreen):
            app.screen._save()
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        app.screen.dismiss(choice)
        await settle(app, pilot)
        if not isinstance(app.screen, ProfileReviewScreen):  # one flavor with several accounts: the picker
            app.screen.dismiss("")
            await settle(app, pilot)
        self.assertIsInstance(app.screen, ProfileReviewScreen)
        return app.screen


class FlowTest(AceAppBase):
    async def test_first_open_shows_settings_then_flavors(self):
        app = self.make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.open_tool(TOOL)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileSettingsScreen)
            app.screen.query_one("#blacklist", Input).value = "ElvUI, Questie"
            app.screen._save()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
        saved = load_settings(Config(self.config_dir / "ace-profiles.cfg").load())
        self.assertEqual(saved.blacklist, ["ElvUI", "Questie"])

    async def test_settings_refuse_a_folder_inside_wtf(self):
        app = self.make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.open_tool(TOOL)
            await settle(app, pilot)
            screen = app.screen
            screen.query_one("#backup-dir", Input).value = str(self.root / "_retail_" / "WTF" / "x")
            screen._save()
            await settle(app, pilot)
            self.assertIs(app.screen, screen)
            self.assertTrue(str(screen.query_one("#settings-error").render()))

    async def test_all_flavors_review_and_escape_back(self):
        app = self.make_app()
        async with app.run_test() as pilot:
            review = await self.open_review(app, pilot)
            self.assertTrue(review.sub_title.startswith("Ace3 Profile Manager · All flavors"))
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)


def labels(tree):
    out, stack = [], [tree.root]
    while stack:
        node = stack.pop()
        out.append(str(node.label))
        stack.extend(reversed(node.children))
    return out


def find(tree, kind, *rest):
    stack = [tree.root]
    while stack:
        node = stack.pop()
        if node.data and node.data[0] == kind and all(r in node.data for r in rest):
            return node
        stack.extend(node.children)
    raise AssertionError(f"no {kind} node {rest}")


def find_addon(tree, name, account="ACCT1"):
    stack = [tree.root]
    while stack:
        node = stack.pop()
        if node.data and node.data[0] == "addon" and node.data[1].file.addon == name \
                and node.data[1].file.account == account:
            return node
        stack.extend(node.children)
    raise AssertionError(f"no addon node {name}")


class ReviewTest(AceAppBase):
    async def test_tree_shows_databases_profiles_and_characters(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            for node in list(tree.root.children):
                node.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            for expected in ("Retail", "Classic Era", "ACCT1", "KickCD", "ElvUI", "ElvDB", "ElvPrivateDB",
                             "Default · 3 characters · Default", "unused", "missing",
                             "Gone - Realm1 · no character folder", "spec profiles", "Scan warnings"):
                self.assertIn(expected, text)
            self.assertNotIn("KickCDPerfDB", text)
            self.assertNotIn("Memento", text.replace("Memento.lua", ""))
            self.assertEqual(review.ticked, set())
            self.assertTrue(review.summary_text.startswith("Selected: 0 profiles · 0 characters"))

    async def test_tick_a_profile_and_summary_counts(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            node = find(tree, "profile", "Healer")
            parent = node.parent
            while parent is not None:  # the addon node starts collapsed: open the way down to the profile
                parent.expand()
                parent = parent.parent
            await settle(app, pilot)  # the tree lays out its lines before the cursor can go to the node
            tree.move_cursor(node)
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(len([k for k in review.ticked if k[0] == "p"]), 1)
            self.assertTrue(review.summary_text.startswith("Selected: 1 profile · 0 characters"))
            await pilot.press("n")
            await settle(app, pilot)
            self.assertEqual(review.ticked, set())

    async def test_blacklist_greys_out_and_unlock(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            tree.move_cursor(find_addon(tree, "ElvUI"))
            await pilot.press("b")
            await settle(app, pilot)
            self.assertTrue(review.locked("ElvUI"))
            self.assertIn("blacklisted", "\n".join(labels(tree)))
            self.assertEqual(load_settings(Config(self.config_dir / "ace-profiles.cfg").load()).blacklist, ["ElvUI"])
            tree.move_cursor(find_addon(tree, "ElvUI"))
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(review.ticked, set())  # locked: nothing to tick
            await pilot.press("u")
            await settle(app, pilot)
            self.assertFalse(review.locked("ElvUI"))
            self.assertIn("unlocked", "\n".join(labels(tree)))

    async def test_character_view_and_search(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("v")
            await settle(app, pilot)
            self.assertEqual(review.view, "character")
            tree = review.query_one("#profiles", Tree)
            tree.root.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            self.assertIn("Kaelys - Realm1", text)
            self.assertIn("KickCD: Default", text)
            review.query_one("#search", Input).value = "mierin"
            await settle(app, pilot)
            tree.root.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            self.assertIn("Mierin - Khaz Modan", text)
            self.assertNotIn("Kaelys - Realm1", text)

    async def test_only_unused_filter(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot, choice=WowInstall(self.root).flavor("_retail_"))
            review.query_one("#only-unused").value = True
            await settle(app, pilot)
            tree = review.query_one("#profiles", Tree)
            tree.root.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            self.assertIn("Backup", text)
            self.assertNotIn("Healer", text)

    async def test_all_ticks_visible_profiles_and_characters(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("a")
            await settle(app, pilot)
            kinds = {k[0] for k in review.ticked}
            self.assertEqual(kinds, {"p", "c"})
            await pilot.press("n")
            review.query_one("#search", Input).value = "mierin"
            await settle(app, pilot)
            await pilot.press("a")
            await settle(app, pilot)
            self.assertTrue(review.ticked)
            self.assertTrue(all(k[2].startswith("Mierin") for k in review.ticked if k[0] == "c"))
            review.query_one("#search", Input).value = ""
            await settle(app, pilot)
            self.assertTrue(review.ticked)  # hidden items keep their ticks


class StagingTest(AceAppBase):
    async def highlight(self, app, pilot, review, kind, *rest):
        tree = review.query_one("#profiles", Tree)
        tree.root.expand_all()
        await settle(app, pilot)
        node = find(tree, kind, *rest)
        tree.move_cursor(node)
        await settle(app, pilot)
        return node

    async def test_delete_to_default(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("d")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)
            app.screen.dismiss("Default")
            await settle(app, pilot)
            summary = review.staging.summary()
            self.assertEqual((summary.deleted, summary.reassigned), (1, 1))
            self.assertIn("✘ deleted", "\n".join(labels(review.query_one("#profiles", Tree))))
            self.assertIn("Staged: ", review.summary_text)

    async def test_rename_refuses_existing_name_then_accepts(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("e")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, NameScreen)
            app.screen.dismiss("Default")
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().total, 0)  # refused, notified
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("e")
            await settle(app, pilot)
            app.screen.dismiss("Heals")
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().renamed, 1)

    async def test_assign_from_character_view(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("v")
            await settle(app, pilot)
            node = await self.highlight(app, pilot, review, "character", "Kaelys - Realm1")
            node.expand()
            await pilot.press("space")
            await settle(app, pilot)
            await pilot.press("p")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)
            app.screen.dismiss("Default")
            await settle(app, pilot)
            self.assertGreater(review.staging.summary().reassigned, 0)
            self.assertEqual(review.ticked, set())

    async def test_quick_action_keep_only_default_and_discard(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("m")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ActionsScreen)
            app.screen.dismiss("keep_default")
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().deleted, 1)
            review.action_discard()
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().total, 0)

    async def test_locked_addon_refuses_quick_action(self):
        self.cfg_tool = Config(self.config_dir / "ace-profiles.cfg")
        self.cfg_tool.set("ace_profiles", "blacklist", "ElvUI", log=False)
        self.cfg_tool.save()
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            review.staging.keep_only_default([k for k in review.staging.states if k.sv_name == "ElvDB"])
            self.assertEqual(review.staging.summary().total, 0)
