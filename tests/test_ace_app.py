"""Ace3 Profile Manager screens (flow, settings, review, popups, apply, undo, recovery)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, DataTable, Input, Static, Tree

from tests.fixtures import BASE, TuiTestCase, build_ace_tree, make_config, settle, submit_filter
from wowtools.core.backup import BackupEntry, create_backup
from wowtools.core.config import Config
from wowtools.core.install import WowInstall
from wowtools.core.text import plural
from wowtools.tools.ace3_profile_manager import editor
from wowtools.tools.ace3_profile_manager import review_screen as review_module
from wowtools.tools.ace3_profile_manager.app import ProfileSettingsScreen
from wowtools.tools.ace3_profile_manager.blacklist_screen import BlacklistScreen
from wowtools.tools.ace3_profile_manager.popups import ActionsScreen, NameScreen, TargetScreen
from wowtools.tools.ace3_profile_manager.result_screen import ProfileResultScreen
from wowtools.tools.ace3_profile_manager.review_screen import ProfileReviewScreen
from wowtools.tools.ace3_profile_manager.scanner import sha256_of
from wowtools.tools.ace3_profile_manager.settings import load_settings
from wowtools.ui.dialogs import ConfirmScreen, InfoScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp
from wowtools.ui.tree_filter import FILTER_HINT
from wowtools.ui.widgets import action_kind

TOOL = "ace3-profile-manager"


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

    async def highlight(self, app, pilot, review, kind, *rest):
        tree = review.query_one("#profiles", Tree)
        tree.root.expand_all()
        await settle(app, pilot)
        node = find(tree, kind, *rest)
        tree.move_cursor(node)
        await settle(app, pilot)
        return node

    async def tick_pair(self, app, pilot, tree, flavor, addon):
        """Highlight (flavor, addon) on a blacklist tree and press Space."""
        tree.root.expand_all()
        await settle(app, pilot)
        node = find(tree, "addon", flavor, addon)
        tree.focus()
        tree.move_cursor(node)
        await settle(app, pilot)
        await pilot.press("space")
        await settle(app, pilot)

    async def highlight_addon(self, app, pilot, review, name, account="ACCT1"):
        tree = review.query_one("#profiles", Tree)
        tree.root.expand_all()
        await settle(app, pilot)
        tree.move_cursor(find_addon(tree, name, account))
        await settle(app, pilot)


class FlowTest(AceAppBase):
    async def test_first_open_shows_settings_then_flavors(self):
        app = self.make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.open_tool(TOOL)
            await settle(app, pilot)
            settings = app.screen
            self.assertIsInstance(settings, ProfileSettingsScreen)
            self.assertIn("None", str(settings.query_one("#blacklist-summary").render()))
            settings.query_one("#edit-blacklist", Button).press()  # "Edit blacklist…": the tree screen
            await settle(app, pilot)
            screen = app.screen
            self.assertIsInstance(screen, BlacklistScreen)
            tree = screen.query_one("#blacklist-tree", Tree)
            await self.tick_pair(app, pilot, tree, "_retail_", "ElvUI")
            screen.query_one("#save", Button).press()
            await settle(app, pilot)
            self.assertIs(app.screen, settings)
            self.assertIn("1 addon blacklisted", str(settings.query_one("#blacklist-summary").render()))
            settings._save()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
        tool = Config(self.config_dir / "ace3-profile-manager.cfg").load()
        self.assertEqual(tool.get("ace3_profile_manager", "blacklist"), "_retail_:ElvUI")
        self.assertEqual(load_settings(tool).blacklist, [("_retail_", "ElvUI")])

    async def test_settings_have_no_retention_inputs(self):
        """Feedback round 1: backups and journals to keep are global ([general], the `s` screen)."""
        app = self.make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.open_tool(TOOL)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileSettingsScreen)
            for box in ("#keep-snapshots", "#keep-journals", "#keep-backups", "#keep_backups", "#keep_journals"):
                self.assertFalse(app.screen.query(box), box)

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


def walk(node):
    """node and every node below it."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children)


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
            self.assertTrue(review.locked("_retail_", "ElvUI"))
            self.assertIn("blacklisted", "\n".join(labels(tree)))
            saved = load_settings(Config(self.config_dir / "ace3-profile-manager.cfg").load())
            self.assertEqual(saved.blacklist, [("_retail_", "ElvUI")])
            tree.move_cursor(find_addon(tree, "ElvUI"))
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(review.ticked, set())  # locked: nothing to tick
            await pilot.press("u")
            await settle(app, pilot)
            self.assertFalse(review.locked("_retail_", "ElvUI"))
            self.assertIn("unlocked", "\n".join(labels(tree)))

    async def test_b_locks_the_pair_in_its_flavor_only(self):
        """Feedback round 1: b blacklists (Retail, ElvUI); Classic Era's Questie stays tickable."""
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight_addon(app, pilot, review, "ElvUI")
            await pilot.press("b")
            await settle(app, pilot)
            self.assertTrue(review.locked("_retail_", "ElvUI"))
            self.assertFalse(review.locked("_classic_era_", "ElvUI"))
            self.assertFalse(review.locked("_classic_era_", "Questie"))
            await self.highlight_addon(app, pilot, review, "Questie")
            await pilot.press("space")
            await settle(app, pilot)
            self.assertTrue(review.ticked)
            self.assertTrue(all(review.staging.state(k[1]).file.addon == "Questie" for k in review.ticked))

    async def test_blacklist_dialog_from_the_review_saves_at_once(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            review.action_edit_blacklist()
            await settle(app, pilot)
            screen = app.screen
            self.assertIsInstance(screen, BlacklistScreen)
            await self.tick_pair(app, pilot, screen.query_one("#blacklist-tree", Tree), "_classic_era_", "Questie")
            screen.query_one("#save", Button).press()
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertTrue(review.locked("_classic_era_", "Questie"))
            tool = Config(self.config_dir / "ace3-profile-manager.cfg").load()
            self.assertEqual(load_settings(tool).blacklist, [("_classic_era_", "Questie")])

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
            submit_filter(review, "mierin")
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
            submit_filter(review, "mierin")
            await settle(app, pilot)
            await pilot.press("a")
            await settle(app, pilot)
            self.assertTrue(review.ticked)
            self.assertTrue(all(k[2].startswith("Mierin") for k in review.ticked if k[0] == "c"))
            submit_filter(review, "")
            await settle(app, pilot)
            self.assertTrue(review.ticked)  # hidden items keep their ticks

    async def test_none_unticks_only_what_the_filter_shows(self):
        """Spec D8: `n` unticks what the filter shows; ticks it hides stay, count, and the bottom line says so."""
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("a")
            await settle(app, pilot)
            everything = set(review.ticked)
            submit_filter(review, "mierin")
            await settle(app, pilot)
            shown = review._shown_keys()
            self.assertTrue(shown and shown < everything)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertEqual(review.ticked, everything - shown)
            hidden = len(everything - shown)
            self.assertEqual(len(review.hidden_ticked_keys()), hidden)
            self.assertIn(f"{hidden} selected items are hidden by the filter", review.summary_text)
            submit_filter(review, "")
            await settle(app, pilot)
            self.assertEqual(len(review.hidden_ticked_keys()), 0)
            self.assertNotIn("hidden by the filter", review.summary_text)

    async def test_hidden_ticks_are_said_in_the_popups_that_take_them(self):
        """A popup counts only the hidden ticks its action takes: Delete the profiles, Assign the characters."""
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("a")
            submit_filter(review, "mierin")
            await settle(app, pilot)
            hidden = review.hidden_ticked_keys()
            profiles = sum(1 for k in hidden if k[0] == "p")
            chars = len(hidden) - profiles
            self.assertTrue(profiles and chars)
            await pilot.press("d")  # every ticked profile, hidden ones too
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)
            self.assertIn(f"{plural(profiles, 'selected profile')} {'is' if profiles == 1 else 'are'} hidden by the "
                          "filter: they are included.", app.screen.body_text)
            app.screen.dismiss(None)
            await settle(app, pilot)
            await pilot.press("p")  # every ticked character
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)
            self.assertIn(f"{plural(chars, 'selected character')} {'is' if chars == 1 else 'are'} hidden by the "
                          "filter: they are included.", app.screen.body_text)

    async def test_ticks_hidden_by_a_show_box_are_not_blamed_on_the_filter(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("a")
            review.query_one("#only-multi").value = True
            await settle(app, pilot)
            self.assertFalse(review.filtering)
            hidden = len(review.hidden_ticked_keys())
            self.assertGreater(hidden, 0)
            self.assertIn(f"{hidden} selected items are hidden by the Show boxes", review.summary_text)
            self.assertNotIn("filter", review.summary_text)
            submit_filter(review, "mierin")
            await settle(app, pilot)
            self.assertIn("hidden by the filter or the Show boxes", review.summary_text)

    async def test_profile_ticks_hidden_by_the_character_view_are_named_and_unticked_by_none(self):
        """By character has no profile rows: their ticks are hidden by the view (not the empty filter), and `n`
        unticks them too, since the view has nowhere to untick them."""
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("a")
            await settle(app, pilot)
            profiles = sum(1 for k in review.ticked if k[0] == "p")
            self.assertGreater(profiles, 0)
            await pilot.press("v")
            await settle(app, pilot)
            self.assertEqual(review.view, "character")
            self.assertFalse(review.filtering)
            self.assertIn(f"{profiles} selected items are hidden by the view", review.summary_text)
            self.assertNotIn("filter", review.summary_text)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertEqual(review.ticked, set())
            self.assertNotIn("hidden by", review.summary_text)

    async def test_escape_in_the_filter_clears_it_and_slash_reaches_it(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("slash", "m", "i", "e", "r")
            await settle(app, pilot)
            field = review.query_one("#search", Input)
            self.assertIs(review.focused, field)
            self.assertEqual(field.value, "mier")
            self.assertFalse(review.filtering)  # typed, not submitted (spec D40)
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertTrue(review.filtering)
            await pilot.press("slash", "escape")
            await settle(app, pilot)
            self.assertEqual(field.value, "")
            self.assertIs(review.focused, review.query_one("#profiles", Tree))
            self.assertIs(app.screen, review)


class StagingTest(AceAppBase):

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
            self.assertIn(f"{summary.total} pending changes in 1 file", review.summary_text)
            self.assertIn("Pending changes: 1 delete · ", str(review.query_one("#pending").render()))

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

    async def test_only_default_button_and_discard(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            review.query_one("#act-keep-default", Button).press()
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().deleted, 1)
            review.action_discard()
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().total, 0)

    async def test_backspace_discards_and_x_expands_for_good(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            tree.focus()
            await pilot.press("x")
            await settle(app, pilot)
            review.refresh_view()  # a rebuild keeps what x opened
            await settle(app, pilot)
            parents = [n for n in review._walk_tree() if n.children]
            self.assertGreater(len(parents), 1)
            self.assertEqual([n for n in parents if not n.is_expanded], [])
            review.staging.everyone_to_default(list(review.staging.states))
            review.refresh_view()
            await pilot.press("x")  # no longer discard
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            await pilot.press("backspace")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("Discard", app.screen.title_text)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().total, 0)

    async def test_locked_addon_refuses_quick_action(self):
        self.cfg_tool = Config(self.config_dir / "ace3-profile-manager.cfg")
        self.cfg_tool.set("ace3_profile_manager", "blacklist", "ElvUI", log=False)
        self.cfg_tool.save()
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            review.staging.keep_only_default([k for k in review.staging.states if k.sv_name == "ElvDB"])
            self.assertEqual(review.staging.summary().total, 0)


class RunTest(AceAppBase):
    async def stage(self, app, pilot):
        review = await self.open_review(app, pilot)
        key = next(k for k in review.staging.states if k.sv_name == "ElvDB")
        review.staging.delete({key: ["Healer"]}, "Default")
        review.refresh_view()
        await settle(app, pilot)
        return review, key.path

    async def test_dry_run_changes_nothing_and_shows_result(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            _review, path = await self.stage(app, pilot)
            before = path.read_bytes()
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileResultScreen)
            self.assertTrue(app.screen.sub_title.endswith("Dry run result"))
            self.assertEqual(path.read_bytes(), before)

    async def test_runs_use_the_global_retention(self):
        """Feedback round 1: Apply prunes to [general] keep_backups / keep_journals; stale tool keys are ignored."""
        tool = Config(self.config_dir / "ace3-profile-manager.cfg")
        for key in ("keep_snapshots", "keep_backups", "keep_journals"):
            tool.set("ace3_profile_manager", key, "2", log=False)
        tool.save()
        self.cfg.set("general", "keep_backups", "0", log=False)
        self.cfg.set("general", "keep_journals", "4", log=False)
        calls = []
        real = review_module.apply_flavors

        def spy(*args, **kwargs):
            calls.append((kwargs["keep_snapshots"], kwargs["keep_journals"]))
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(review_module, "apply_flavors", spy):
            async with app.run_test(size=(140, 50)) as pilot:
                await self.stage(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                app.screen.dismiss(True)
                await settle(app, pilot)
        self.assertEqual(calls, [(0, 4)])

    async def test_apply_then_undo(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review, path = await self.stage(app, pilot)
            before = path.read_bytes()
            await pilot.press("w")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileResultScreen)
            self.assertNotEqual(path.read_bytes(), before)
            rows = app.screen.query_one("#result-summary", DataTable).row_count
            self.assertGreater(rows, 1)
            await pilot.press("r")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIsNotNone(review.undoable)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.cfg.set("general", "parallelism", "3", log=False)
            seen = []
            real = review_module.undo_run

            def undo_run(*args, **kwargs):
                screen = kwargs["on_flavor"].__self__
                seen.append((kwargs["parallelism"], screen.rows, screen.title_text))
                return real(*args, **kwargs)

            with patch.object(review_module, "undo_run", undo_run):
                app.screen.dismiss(True)
                await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileResultScreen)
            self.assertEqual(path.read_bytes(), before)
            # the WTF snapshots run up to [general] parallelism at once, one popup row per flavor of the journal
            self.assertEqual(seen, [(3, 1, "Undoing the last change")])

    async def test_apply_refused_while_wow_runs(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review, path = await self.stage(app, pilot)
            before = path.read_bytes()
            self.running.append("Wow.exe")
            await pilot.press("w")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(path.read_bytes(), before)

    async def test_recovery_offered_and_put_back(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            path = next(k for k in review.staging.states if k.sv_name == "ElvDB").path
            original = path.read_bytes()
            root = self.root / "wow-tools" / "ace3-profile-manager"
            flavor = next(s for s in review.staging.states.values() if s.file.path == path).file.flavor
            zip_path = create_backup([BackupEntry(path)], flavor.path,
                                     root / "edited" / "edited-retail-all-20261004-120000.zip", {})
            path.write_bytes(b"torn")
            rel = path.relative_to(flavor.path).as_posix()
            # recovery puts back only a file still at what the run wrote (the marker's `after`)
            editor.write_marker(root, editor.Marker("_retail_", flavor.path, zip_path, {rel: sha256_of(original)},
                                                    "2026-10-04T12:00:00+00:00", 1, "1.0.0",
                                                    {rel: sha256_of(b"torn")}))
            await pilot.press("r")
            await settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "ProfileRecoveryScreen")
            self.assertEqual(app.screen.focused.id, "put_back")  # the expected choice is focused (spec D13)
            app.screen.dismiss("put_back")
            await settle(app, pilot)
            self.assertEqual(path.read_bytes(), original)
            self.assertIsNone(editor.read_marker(root))

    async def test_recovery_leave_that_cannot_remove_the_marker_says_so(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            path = next(k for k in review.staging.states if k.sv_name == "ElvDB").path
            flavor = WowInstall(self.root).flavor("_retail_")
            rel = path.relative_to(flavor.path).as_posix()
            root = self.root / "wow-tools" / "ace3-profile-manager"
            marker = editor.Marker("_retail_", flavor.path, root / "edited" / "edited-retail-all-x.zip",
                                   {rel: "a"}, "2026-10-04T12:00:00+00:00", 1, "1.0.0", {rel: "b"})
            editor.write_marker(root, marker)
            await pilot.press("r")
            await settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "ProfileRecoveryScreen")
            with patch("wowtools.core.sv_undo.clear_marker", return_value=False):
                app.screen.dismiss("leave")
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIsNotNone(review.marker)
            self.assertEqual(editor.read_marker(root), marker)
            notes = [n for n in app._notifications if n.title == "Unfinished change"]
            self.assertTrue(notes and "could not be removed" in notes[-1].message)


def inside(widget, box) -> bool:
    """The widget is drawn whole inside box (and on screen)."""
    w, b = widget.region, box.region
    screen = widget.screen.size
    return (w.width > 0 and w.height > 0 and w.x >= b.x and w.y >= b.y and w.right <= b.right
            and w.bottom <= b.bottom and b.right <= screen.width and b.bottom <= screen.height)


class ReviewFixesTest(AceAppBase):
    """M3 review: blacklisting after staging, the Undo and recovery WoW checks, leaving with staged changes, the
    popups at 120x30, the delete target, the extra keys in the menu, the dry-run result and search expansion."""

    async def stage_elv(self, app, pilot, review):
        key = next(k for k in review.staging.states if k.sv_name == "ElvDB")
        review.staging.delete({key: ["Healer"]}, "Default")
        review.refresh_view()
        await settle(app, pilot)
        self.assertEqual(review.staging.summary().total, 3)
        return key.path

    def blacklist(self, names):
        tool = Config(self.config_dir / "ace3-profile-manager.cfg").load()
        tool.set("ace3_profile_manager", "blacklist", names, log=False)
        tool.save()

    async def assert_apply_writes_nothing(self, app, pilot, review, path):
        before = path.read_bytes()
        await pilot.press("w")
        await settle(app, pilot)
        if isinstance(app.screen, ConfirmScreen):
            app.screen.dismiss(True)
            await settle(app, pilot)
        self.assertIs(app.screen, review)
        self.assertEqual(path.read_bytes(), before)

    async def test_blacklisting_an_addon_drops_its_staged_changes(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            path = await self.stage_elv(app, pilot, review)
            await self.highlight_addon(app, pilot, review, "ElvUI")
            await pilot.press("b")
            await settle(app, pilot)
            self.assertTrue(review.locked("_retail_", "ElvUI"))
            self.assertEqual(review.staging.summary().total, 0)
            self.assertTrue(review.query_one("#btn-apply").disabled)
            await self.assert_apply_writes_nothing(app, pilot, review, path)

    async def test_locking_again_drops_its_staged_changes(self):
        self.blacklist("ElvUI")
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight_addon(app, pilot, review, "ElvUI")
            await pilot.press("u")
            await settle(app, pilot)
            path = await self.stage_elv(app, pilot, review)
            await self.highlight_addon(app, pilot, review, "ElvUI")
            await pilot.press("u")
            await settle(app, pilot)
            self.assertTrue(review.locked("_retail_", "ElvUI"))
            self.assertEqual(review.staging.summary().total, 0)
            await self.assert_apply_writes_nothing(app, pilot, review, path)

    async def test_blacklisted_in_settings_after_staging_is_not_written(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            path = await self.stage_elv(app, pilot, review)
            review.tool_cfg.set("ace3_profile_manager", "blacklist", "ElvUI", log=False)  # what `s` saves, no rescan
            await self.assert_apply_writes_nothing(app, pilot, review, path)
            self.assertEqual(review.staging.summary().total, 0)

    async def test_undo_checks_the_flavor_of_the_journal(self):
        from unittest.mock import patch

        from wowtools.core import process
        from wowtools.core.process import WowProcess
        procs: list[WowProcess] = []
        asked: list[list[str]] = []

        def check_for(folders, **_):
            asked.append(list(folders))
            return process.wow_check_for(folders, lister=lambda: list(procs))
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)
        with patch("wowtools.tools.ace3_profile_manager.review_screen.wow_check_for", side_effect=check_for):
            async with app.run_test(size=(140, 50)) as pilot:
                review = await self.open_review(app, pilot)
                path = await self.stage_elv(app, pilot, review)  # a Retail file
                await pilot.press("w")
                await settle(app, pilot)
                app.screen.dismiss(True)
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ProfileResultScreen)
                edited = path.read_bytes()
                await pilot.press("f")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, FlavorScreen)
                era = WowInstall(self.root).flavor("_classic_era_")
                app.screen.dismiss(era)
                await settle(app, pilot)
                review = app.screen
                self.assertIsInstance(review, ProfileReviewScreen)
                self.assertIsNotNone(review.undoable)  # the Retail journal
                procs.append(WowProcess("Wow.exe", str(self.root / "_retail_" / "Wow.exe")))
                await pilot.press("z")
                await settle(app, pilot)
                self.assertIs(app.screen, review)  # refused: Retail runs
                self.assertIn(["_retail_"], asked)
                self.assertEqual(path.read_bytes(), edited)
                procs.clear()
                await pilot.press("z")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIn("Retail", app.screen.body_text)

    async def write_torn_marker(self, review):
        path = next(k for k in review.staging.states if k.sv_name == "ElvDB").path
        original = path.read_bytes()
        root = self.root / "wow-tools" / "ace3-profile-manager"
        flavor = next(s for s in review.staging.states.values() if s.file.path == path).file.flavor
        zip_path = create_backup([BackupEntry(path)], flavor.path,
                                 root / "edited" / "edited-retail-all-20261004-120000.zip", {})
        path.write_bytes(b"torn")
        rel = path.relative_to(flavor.path).as_posix()
        editor.write_marker(root, editor.Marker("_retail_", flavor.path, zip_path, {rel: sha256_of(original)},
                                                "2026-10-04T12:00:00+00:00", 1, "1.0.0", {rel: sha256_of(b"torn")}))
        return root, path

    async def test_recovery_refused_while_wow_runs(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            root, path = await self.write_torn_marker(review)
            await pilot.press("r")
            await settle(app, pilot)
            self.running.append("Wow.exe")
            app.screen.dismiss("put_back")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(path.read_bytes(), b"torn")
            self.assertIsNotNone(editor.read_marker(root))  # offered again at the next scan

    async def test_recovery_popup_fits_at_base(self):
        """At 120x30 the recovery popup is drawn whole, and the zip's path has a line of its own (a path with a
        space, "World of Warcraft", is never split between two lines of text)."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.write_torn_marker(review)
            await pilot.press("r")
            await settle(app, pilot)
            box = app.screen.query_one("#choice-box")
            for button in app.screen.query("Button"):
                self.assertTrue(inside(button, box), button.id)
            self.assertIn(str(app.screen.marker.zip), app.screen.message_text.splitlines())

    async def test_leaving_with_staged_changes_asks_first(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.stage_elv(app, pilot, review)
            await pilot.press("slash")
            await pilot.press("h", "e", "a", "d")
            await settle(app, pilot)
            await pilot.press("escape")  # out of the filter box (cleared), not out of the review
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIs(review.focused, review.query_one("#profiles", Tree))
            for key in ("escape", "f", "t", "q"):
                await pilot.press(key)
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen, key)
                app.screen.dismiss(False)
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                self.assertEqual(review.staging.summary().total, 3)
            await pilot.press("f")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)

    async def test_undo_confirm_says_staged_changes_are_dropped(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.stage_elv(app, pilot, review)
            await pilot.press("w")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            await self.stage_elv_kick(app, pilot, review)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("pending change", app.screen.body_text)

    async def stage_elv_kick(self, app, pilot, review):
        key = next(k for k in review.staging.states if k.sv_name == "KickCDDB" and "ACCT1" in k.path.parts)
        review.staging.delete({key: ["Backup"]}, "Default")
        review.refresh_view()
        await settle(app, pilot)

    async def test_dry_run_result_escape_goes_back_with_the_staging(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.stage_elv(app, pilot, review)
            await pilot.press("y")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileResultScreen)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.staging.summary().total, 3)
            await pilot.press("y")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            await pilot.press("enter")  # the focused button: Back to review
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.staging.summary().total, 3)

    async def test_delete_target_never_offers_a_profile_being_deleted(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            key = next(k for k in review.staging.states if k.sv_name == "KickCDDB" and "ACCT1" in k.path.parts)
            await self.highlight(app, pilot, review, "profile", key, "Default")
            await pilot.press("d")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)
            self.assertNotIn("Default", app.screen.targets)
            self.assertEqual(app.screen.default, app.screen.targets[0])

    async def test_delete_everything_asks_for_a_new_name(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("a")
            await settle(app, pilot)
            await pilot.press("d")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)
            self.assertNotIn("Default", app.screen.targets)

    async def test_addon_name_tells_accounts_apart(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            kicks = [k for k in review.staging.states if k.sv_name == "KickCDDB"]
            names = {review._addon_name(k) for k in kicks}
            self.assertEqual(len(names), len(kicks))
            self.assertTrue(any("ACCT2" in n for n in names))

    async def test_popups_fit_at_base(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            # p ticks all first: on the root with nothing ticked, Delete and Assign ask for a tick (feedback round 1
            # review)
            for keys, kind in ((("a", "d"), TargetScreen), (("a", "p"), TargetScreen), (("m",), ActionsScreen)):
                for key in keys:
                    await pilot.press(key)
                    await settle(app, pilot)
                screen = app.screen
                self.assertIsInstance(screen, kind)
                box = screen.query_one(".popup-box")
                for widget in screen.query("Button, Input, Select, NavHint, OptionList"):
                    if not widget.display:  # the Select's closed overlay
                        continue
                    self.assertTrue(inside(widget, box), f"{kind.__name__} {keys}: {widget}")
                screen.dismiss(None)
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                review.ticked.clear()
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("e")
            await settle(app, pilot)
            box = app.screen.query_one(".popup-box")
            for widget in app.screen.query("Button, Input, NavHint"):
                self.assertTrue(inside(widget, box), f"NameScreen: {widget}")

    async def test_more_menu_lists_every_hidden_key(self):
        from wowtools.tools.ace3_profile_manager.popups import ACTIONS
        ids = {action for action, _ in ACTIONS}
        for action in ("rename", "copy", "blacklist", "unlock", "switch_view", "filter", "discard"):
            self.assertIn(action, ids)
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("m")
            await settle(app, pilot)
            app.screen.dismiss("rename")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, NameScreen)

    async def test_search_opens_the_groups_it_leaves(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("slash")
            for ch in "mierin":
                await pilot.press(ch)
            await pilot.press("enter")
            await settle(app, pilot)
            tree = review.query_one("#profiles", Tree)
            shown = [str(tree.get_node_at_line(i).label) for i in range(tree.last_line + 1)]
            self.assertTrue(any("Mierin" in line for line in shown), shown)
            submit_filter(review, "")
            await settle(app, pilot)
            addon = find_addon(tree, "ElvUI")
            self.assertFalse(addon.is_expanded)  # back to how it was before the search


class FinalReviewFixesTest(AceAppBase):
    """M4 review: Apply with an unfinished earlier change, the backup folder checked before use, and the
    running-WoW check of only the flavors with changes."""

    async def stage_elv(self, app, pilot, review):
        key = next(k for k in review.staging.states if k.sv_name == "ElvDB")
        review.staging.delete({key: ["Healer"]}, "Default")
        review.refresh_view()
        await settle(app, pilot)
        return key.path

    async def test_apply_offers_the_earlier_unfinished_change_first(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            kick = next(k for k in review.staging.states if k.sv_name == "KickCDDB").path
            flavor = WowInstall(self.root).flavor("_retail_")
            rel = kick.relative_to(flavor.path).as_posix()
            root = self.root / "wow-tools" / "ace3-profile-manager"
            earlier = editor.Marker("_retail_", flavor.path, root / "edited" / "edited-retail-all-x.zip",
                                    {rel: "a"}, "2026-10-03T12:00:00+00:00", 1, "1.0.0", {rel: "b"})
            editor.write_marker(root, earlier)
            await pilot.press("r")
            await settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "ProfileRecoveryScreen")
            await pilot.press("escape")  # closed without a choice
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            path = await self.stage_elv(app, pilot, review)
            before = path.read_bytes()
            await pilot.press("w")
            await settle(app, pilot)
            self.assertEqual(type(app.screen).__name__, "ProfileRecoveryScreen")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(editor.read_marker(root), earlier)

    async def test_apply_and_undo_refuse_a_backup_folder_not_allowed(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            path = await self.stage_elv(app, pilot, review)
            before = path.read_bytes()
            inside_wtf = self.root / "_retail_" / "WTF" / "bk"
            review.tool_cfg.set_path("ace3_profile_manager", "backup_dir", inside_wtf)  # edited by hand in the cfg
            await pilot.press("w")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(inside_wtf.exists())
            self.assertTrue(any(n.title == "Backup folder not allowed" for n in app._notifications))
            app._notifications.clear()
            review.undoable = self.root / "journal-x.jsonl"
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertTrue(any(n.title == "Backup folder not allowed" for n in app._notifications))

    async def test_apply_checks_only_the_flavors_it_changes(self):
        from unittest.mock import patch

        from wowtools.core import process
        from wowtools.core.process import WowProcess
        procs = [WowProcess("WowClassic.exe", str(self.root / "_classic_era_" / "WowClassic.exe"))]
        asked: list[list[str]] = []

        def check_for(folders, **_):
            asked.append(list(folders))
            return process.wow_check_for(folders, lister=lambda: list(procs))
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)
        with patch("wowtools.tools.ace3_profile_manager.review_screen.wow_check_for", side_effect=check_for):
            async with app.run_test(size=(140, 50)) as pilot:
                review = await self.open_review(app, pilot)  # All flavors
                self.assertGreater(len(review.flavors), 1)
                path = await self.stage_elv(app, pilot, review)  # a Retail file only
                before = path.read_bytes()
                await pilot.press("w")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)  # Classic Era running does not matter
                app.screen.dismiss(True)
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ProfileResultScreen)
                self.assertIn(["_retail_"], asked)
                self.assertNotEqual(path.read_bytes(), before)


class GuidanceTest(AceAppBase):
    """Feedback round 1, item 5: the review explains itself (guidance line, action bar, "pending changes")."""

    def guide(self, review):
        return str(review.query_one("#guide").render())

    async def test_guide_follows_the_state(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            self.assertTrue(self.guide(review).startswith("1 Tick profiles or characters (Space) → 2 pick an action"),
                            self.guide(review))
            # the steps wrap between steps only: the rows put back together are the text
            self.assertEqual(review.guide_text, self.guide(review).replace("→\n", "→ "))
            await self.highlight(app, pilot, review, "profile", "Healer")
            self.assertEqual(self.guide(review), 'Profile "Healer": Delete, Rename or Copy it')
            tree = review.query_one("#profiles", Tree)
            tree.focus()
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(self.guide(review), "1 ticked: pick an action below (Delete, Assign, …)")
            await pilot.press("n")
            await settle(app, pilot)
            await self.highlight_addon(app, pilot, review, "ElvUI")
            self.assertTrue(self.guide(review).startswith("ElvUI: Only Default"), self.guide(review))
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("d")
            await settle(app, pilot)
            app.screen.dismiss("Default")
            await settle(app, pilot)
            total = review.staging.summary().total
            self.assertTrue(self.guide(review).startswith(f"{total} pending changes, not written: Apply, "
                                                          "Dry run or Discard them"), self.guide(review))
            self.assertNotIn("staged", (self.guide(review) + review.summary_text).casefold())

    async def test_action_bar_buttons_have_their_kind_of_colour(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            buttons = list(review.query_one("#tree-actions").query(Button))
            self.assertEqual([b.label.plain for b in buttons],
                             ["Assign (p)", "Rename (e)", "Copy (k)", "Everyone → Default (E)", "Delete (d)",
                              "Only Default (D)", "Leftovers (o)", "Blacklist…", "More… (m)", "Discard (⌫)"])
            # staged changes first (amber; Copy only adds a profile: green), then staged deletes (red), the rest
            self.assertEqual([action_kind(b) for b in buttons],
                             ["overwrite", "overwrite", "create", "overwrite"] + ["destructive"] * 3
                             + ["navigate"] * 2 + ["cancel"])
            self.assertFalse(any(b.disabled for b in buttons))

    async def press(self, app, pilot, review, button_id):
        review.query_one(f"#{button_id}", Button).press()
        await settle(app, pilot)
        return app.screen

    async def test_every_action_button_triggers_its_action(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            for button_id, kind in (("act-delete", TargetScreen), ("act-rename", NameScreen),
                                    ("act-copy", NameScreen), ("act-more", ActionsScreen),
                                    ("act-blacklist", BlacklistScreen)):
                screen = await self.press(app, pilot, review, button_id)
                self.assertIsInstance(screen, kind, button_id)
                screen.dismiss(None)
                await settle(app, pilot)
                self.assertIs(app.screen, review)
            await self.highlight(app, pilot, review, "char", "Kaelys - Realm1")
            screen = await self.press(app, pilot, review, "act-assign")
            self.assertIsInstance(screen, TargetScreen)
            screen.dismiss(None)
            await settle(app, pilot)
            await self.highlight(app, pilot, review, "char", "Gone - Realm1")
            screen = await self.press(app, pilot, review, "act-leftovers")
            self.assertIsInstance(screen, ConfirmScreen)
            self.assertIn("leftover", screen.title_text)
            screen.dismiss(True)
            await settle(app, pilot)
            self.assertGreater(review.staging.summary().removed, 0)
            screen = await self.press(app, pilot, review, "act-discard")
            self.assertIsInstance(screen, ConfirmScreen)
            self.assertIn("Discard the pending changes?", screen.title_text)
            screen.dismiss(True)
            await settle(app, pilot)
            self.assertEqual(review.staging.summary().total, 0)

    async def test_a_button_with_nothing_to_act_on_says_what_to_do(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight_addon(app, pilot, review, "ElvUI")
            with patch.object(review, "notify") as notify:
                for button_id in ("act-rename", "act-discard"):
                    screen = await self.press(app, pilot, review, button_id)
                    self.assertIs(screen, review, button_id)
            messages = [c.args[0] for c in notify.call_args_list]
            self.assertEqual(messages, ["Highlight a profile", "No pending changes"])


class BlacklistScreenTest(AceAppBase):
    """Feedback round 1: the blacklist as a flavor → addon tree; nothing ticked but what is blacklisted."""

    async def open_screen(self, app, pilot, pairs):
        await pilot.pause()
        install = WowInstall(self.root)
        results: list = []
        app.push_screen(BlacklistScreen(self.cfg, install.flavors(), pairs), results.append)
        await settle(app, pilot)
        self.assertIsInstance(app.screen, BlacklistScreen)
        return app.screen, results

    def ticked_labels(self, tree):
        return [lbl for lbl in labels(tree) if lbl.startswith("✔")]

    async def test_opens_with_nothing_ticked_and_saves_the_ticked_pair(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            screen, results = await self.open_screen(app, pilot, [])
            tree = screen.query_one("#blacklist-tree", Tree)
            tree.root.expand_all()
            await settle(app, pilot)
            text = "\n".join(labels(tree))
            for expected in ("Retail", "Classic Era", "ElvUI", "KickCD", "Questie"):
                self.assertIn(expected, text)
            self.assertNotIn("Memento", text)  # no Ace3 data
            self.assertEqual(screen.ticked, set())
            self.assertEqual(self.ticked_labels(tree), [])
            await self.tick_pair(app, pilot, tree, "_retail_", "ElvUI")
            screen.query_one("#save", Button).press()
            await settle(app, pilot)
            self.assertEqual(results, [[("_retail_", "ElvUI")]])

    async def test_the_filter_waits_for_the_scan(self):
        """While the scan runs, typing in the filter builds nothing from the blacklist pairs alone (their spelling and
        ticks come from the scan) and Save does nothing."""
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            with patch.object(BlacklistScreen, "_scan_worker", lambda self, flavors: None):  # never finishes
                await pilot.pause()
                results: list = []
                app.push_screen(BlacklistScreen(self.cfg, WowInstall(self.root).flavors(), [("_retail_", "elvui")]),
                                results.append)
                await settle(app, pilot)
                screen = app.screen
                self.assertTrue(screen._scanning)
                submit_filter(screen, "elv")
                await settle(app, pilot)
                self.assertEqual(screen.names, {})
                screen.action_save()
                await settle(app, pilot)
                self.assertEqual(results, [])

    async def test_cancel_and_escape_return_none(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            screen, results = await self.open_screen(app, pilot, [("_retail_", "ElvUI")])
            await self.tick_pair(app, pilot, screen.query_one("#blacklist-tree", Tree), "_retail_", "KickCD")
            screen.query_one("#cancel", Button).press()
            await settle(app, pilot)
            self.assertEqual(results, [None])
            screen, results = await self.open_screen(app, pilot, [])
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertEqual(results, [None])

    async def test_select_none_and_all_and_tree_keys(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            screen, results = await self.open_screen(app, pilot, [("_retail_", "ElvUI")])
            tree = screen.query_one("#blacklist-tree", Tree)
            tree.focus()
            await pilot.press("x")
            await settle(app, pilot)
            self.assertTrue(all(n.is_expanded for n in tree.root.children if n.allow_expand))
            await pilot.press("c")
            await settle(app, pilot)
            self.assertFalse(any(n.is_expanded for n in tree.root.children))
            await pilot.press("a")
            await settle(app, pilot)
            self.assertIn(("_classic_era_", "questie"), screen.ticked)
            screen.query_one("#select-none", Button).press()
            await settle(app, pilot)
            self.assertEqual(screen.ticked, set())
            screen.query_one("#save", Button).press()
            await settle(app, pilot)
            self.assertEqual(results, [[]])

    async def test_legacy_wildcard_and_missing_pairs(self):
        """A bare name is ticked under every flavor that has it, and saved as explicit pairs; a pair no longer
        found is shown "(not found)" and kept while ticked; a flavor not shown keeps its pairs."""
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            install = WowInstall(self.root)
            results: list = []
            pairs = [("*", "KickCD"), ("_retail_", "Gone"), ("_classic_era_", "Questie")]
            app.push_screen(BlacklistScreen(self.cfg, [install.flavor("_retail_")], pairs), results.append)
            await settle(app, pilot)
            screen = app.screen
            tree = screen.query_one("#blacklist-tree", Tree)
            tree.root.expand_all()
            await settle(app, pilot)
            self.assertIn(("_retail_", "kickcd"), screen.ticked)
            self.assertTrue(any("Gone" in lbl and "(not found)" in lbl for lbl in labels(tree)))
            screen.query_one("#save", Button).press()
            await settle(app, pilot)
            # KickCD: the wildcard becomes explicit (Retail shown and ticked; Classic Era not shown, so kept).
            self.assertEqual(results, [[("_retail_", "Gone"), ("_classic_era_", "KickCD"), ("_retail_", "KickCD"),
                                        ("_classic_era_", "Questie")]])

    async def test_filter_narrows_and_keeps_hidden_ticks(self):
        """Spec D7/D8: the filter narrows the addons, a / n act on what it shows, a hidden tick stays, is counted on
        the bottom line and is said before Save; Esc clears the filter."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            screen, results = await self.open_screen(app, pilot, [])
            tree = screen.query_one("#blacklist-tree", Tree)
            tree.focus()
            await pilot.press("a")
            everything = set(screen.ticked)
            self.assertGreater(len(everything), 1)
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press(*"kick", "enter")
            await settle(app, pilot)
            addons = {n.data[2] for n in tree.root.children for n in n.children if n.data[0] == "addon"}
            self.assertTrue(addons)
            self.assertTrue(all("kick" in a.casefold() for a in addons), addons)
            await pilot.press("n")
            kept = {k for k in everything if "kick" not in k[1]}
            self.assertEqual(screen.ticked, kept)
            note = f"{len(kept)} selected addons are hidden by the filter"
            self.assertIn(note, str(screen.query_one("#summary", Static).render()))
            screen.query_one("#save", Button).press()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn(f"{note}: they are saved too.", app.screen.body_text)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertEqual(len(results[0]), len(kept))

    async def test_save_without_hidden_ticks_asks_nothing(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            screen, results = await self.open_screen(app, pilot, [])
            submit_filter(screen, "kick")
            await settle(app, pilot)
            screen.query_one("#save", Button).press()
            await settle(app, pilot)
            self.assertEqual(results, [[]])

    async def test_fits_at_base(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            screen, _ = await self.open_screen(app, pilot, [])
            pane = screen.query_one("#filters")
            for widget in (*screen.query("#filters Button"), screen.query_one("NavHint")):
                self.assertTrue(inside(widget, pane), widget)
            hint = screen.query_one("NavHint").hint
            self.assertIn(FILTER_HINT + "x expand all · c collapse all", hint)


class FeedbackReviewFixesTest(AceAppBase):
    """Feedback round 1 review: legacy wildcards survive the blacklist screen, `s` never stacks a second settings
    screen, Delete/Assign on the root ask for a tick, and the guidance line knows a blacklisted addon."""

    async def save_unchanged(self, app, pilot, pairs):
        install = WowInstall(self.root)
        results: list = []
        app.push_screen(BlacklistScreen(self.cfg, install.flavors(), pairs), results.append)
        await settle(app, pilot)
        screen = app.screen
        self.assertIsInstance(screen, BlacklistScreen)
        text = "\n".join(labels(screen.query_one("#blacklist-tree", Tree)))
        screen.query_one("#save", Button).press()
        await settle(app, pilot)
        return text, results

    async def test_wildcards_are_kept_for_every_flavor(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            pairs = [("*", "KickCD"), ("*", "NotInstalledYet"), ("_retail_", "Explicit")]
            text, results = await self.save_unchanged(app, pilot, pairs)
            self.assertEqual(sorted(results[0]), sorted([
                ("_classic_era_", "KickCD"), ("_retail_", "KickCD"), ("_classic_era_", "NotInstalledYet"),
                ("_retail_", "NotInstalledYet"), ("_retail_", "Explicit")]))
            self.assertIn("KickCD (not found)", text)  # Classic Era has no KickCD

    async def test_wildcards_are_kept_when_the_scan_fails(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            pairs = [("*", "KickCD"), ("_retail_", "Explicit")]
            with patch("wowtools.tools.ace3_profile_manager.blacklist_screen.scan_flavors",
                       side_effect=OSError("boom")):
                _, results = await self.save_unchanged(app, pilot, pairs)
            self.assertEqual(sorted(results[0]), sorted([
                ("_classic_era_", "KickCD"), ("_retail_", "KickCD"), ("_retail_", "Explicit")]))

    async def test_settings_key_does_nothing_over_the_blacklist_screen(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            review.query_one("#act-blacklist", Button).press()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BlacklistScreen)
            app.action_settings()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BlacklistScreen)
            app.screen.dismiss(None)
            await settle(app, pilot)
            app.action_settings()  # from the review: general settings, then the tool's
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileSettingsScreen)
            app.screen.query_one("#edit-blacklist", Button).press()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BlacklistScreen)
            app.action_settings()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BlacklistScreen)
            self.assertEqual(sum(isinstance(s, ProfileSettingsScreen) for s in app.screen_stack), 1)

    async def test_delete_and_assign_on_the_root_ask_for_a_tick(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            for node in (tree.root, find(tree, "flavor"), find(tree, "account")):
                tree.move_cursor(node)
                await settle(app, pilot)
                with patch.object(review, "notify") as notify:
                    for button_id in ("act-delete", "act-assign"):
                        review.query_one(f"#{button_id}", Button).press()
                        await settle(app, pilot)
                        self.assertIs(app.screen, review, (node.data[0], button_id))
                self.assertEqual([c.args[0] for c in notify.call_args_list],
                                 ["Tick or highlight a profile first", "Tick or highlight a character first"])
            await self.highlight(app, pilot, review, "profile", "Healer")  # a highlighted profile still works
            review.query_one("#act-delete", Button).press()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, TargetScreen)

    async def test_guide_on_a_blacklisted_addon_says_it_is_locked(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight_addon(app, pilot, review, "ElvUI")
            review.action_blacklist()
            await settle(app, pilot)
            tree = review.query_one("#profiles", Tree)
            for kind in ("addon", "db", "profile", "char"):
                await self.highlight_addon(app, pilot, review, "ElvUI")
                node = next(n for n in walk(tree.cursor_node) if n.data and n.data[0] == kind)
                tree.move_cursor(node)
                await settle(app, pilot)
                guide = str(review.query_one("#guide").render())
                self.assertIn("ElvUI is blacklisted", guide, kind)
                self.assertIn("u unlocks", guide, kind)
                self.assertNotIn("Delete, Rename", guide, kind)
            await pilot.press("u")
            await settle(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            self.assertIn("Delete, Rename or Copy", str(review.query_one("#guide").render()))


class PopupFeedbackTest(AceAppBase):
    """Popup feedback: the leftover confirm lists its characters in a tree, a staged operation's notes open a popup
    (not a notification), and ↑/↓ reach every field and button of the target and name popups."""

    async def test_leftover_confirm_lists_characters_in_a_tree(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "char", "Gone - Realm1")
            review.action_remove_leftovers()
            await settle(app, pilot)
            screen = app.screen
            self.assertIsInstance(screen, ConfirmScreen)
            tree = screen.query_one("#details", Tree)
            branch = tree.root.children[0]
            self.assertIn("KickCD", str(branch.label))
            self.assertTrue(branch.is_expanded)  # few lines: open
            self.assertEqual([str(c.label) for c in branch.children], ["Gone - Realm1"])
            self.assertIs(screen.focused, screen.query_one("#yes", Button))
            self.assertEqual(action_kind(screen.focused), "destructive")
            await pilot.press("up")  # from Yes to the tree
            self.assertIs(screen.focused, tree)
            await pilot.press("c")
            self.assertFalse(branch.is_expanded)

    async def test_notes_open_a_popup_grouped_by_message(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            with patch.object(review, "notify") as notify:
                review._staged(review_module.OpResult(notes=[
                    'AddonA: "Default" will be created by the addon at its next login, with its defaults.',
                    'AddonB: "Default" will be created by the addon at its next login, with its defaults.',
                    "a note with no addon"]))
                await settle(app, pilot)
            notify.assert_not_called()
            screen = app.screen
            self.assertIsInstance(screen, InfoScreen)
            nodes = screen.query_one("#details", Tree).root.children
            self.assertEqual([str(n.label) for n in nodes],
                             ['"Default" will be created by the addon at its next login, with its defaults (2)',
                              "a note with no addon"])
            self.assertEqual([str(c.label) for c in nodes[0].children], ["AddonA", "AddonB"])
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertIs(app.screen, review)

    async def test_arrow_keys_reach_every_field_and_button(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            screen = TargetScreen("Assign a profile", "Body", ["Default", "Healer"])
            app.push_screen(screen)
            await settle(app, pilot)
            order = ["target", "new-name", "ok"]
            self.assertEqual(screen.focused.id, "target")
            for expected in order[1:]:
                await pilot.press("down")
                self.assertEqual(screen.focused.id, expected)
            await pilot.press("right")
            self.assertEqual(screen.focused.id, "cancel")
            await pilot.press("up", "up", "up")
            self.assertEqual(screen.focused.id, "target")
            await pilot.press("enter")  # Enter still opens the list
            await settle(app, pilot)
            self.assertTrue(screen.query_one("#target").expanded)
            screen.dismiss(None)
            await settle(app, pilot)
            screen = NameScreen("Rename a profile", "Body", "Healer")
            app.push_screen(screen)
            await settle(app, pilot)
            await pilot.press("down")
            self.assertEqual(screen.focused.id, "ok")
            await pilot.press("right")
            self.assertEqual(screen.focused.id, "cancel")

    async def test_quick_actions_are_grouped_under_headings(self):
        from wowtools.tools.ace3_profile_manager.popups import ACTION_GROUPS
        self.assertEqual([heading for heading, _ in ACTION_GROUPS], ["Selection", "Modification"])
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("m")
            await settle(app, pilot)
            menu = app.screen.query_one("#actions-list")
            headings = [o for o in menu._options if o.disabled]
            self.assertEqual([str(o.prompt) for o in headings], ["Selection", "Modification"])
            self.assertEqual(menu.highlighted_option.id, "tick_leftovers")
            await pilot.press("up")  # the heading above is skipped: nothing to choose there
            self.assertFalse(menu.highlighted_option.disabled)
            await pilot.press("escape")
            await settle(app, pilot)
            await pilot.press("m")
            await settle(app, pilot)
            app.screen.dismiss("select_all")
            await settle(app, pilot)
            self.assertTrue(review.ticked)


class ActionBarFeedbackTest(AceAppBase):
    """Action bar feedback: ↓ from the tree's last line reaches the bar (↑ goes back), D and E run Only Default and
    Everyone → Default, the focused button's tip says what it would do, and toasts show above the tip and the bar."""

    async def test_down_from_the_last_tree_line_reaches_the_bar(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#profiles", Tree)
            tree.focus()
            tree.move_cursor(tree.get_node_at_line(tree.last_line))
            await pilot.press("down")
            self.assertEqual(review.focused.id, "act-assign")
            await pilot.press("right", "right", "right", "right", "right", "right", "right", "right")
            self.assertEqual(review.focused.id, "act-more")  # on the second row
            await pilot.press("up")
            self.assertIs(review.focused, tree)

    async def test_shift_keys_run_only_default_and_everyone_default(self):
        app = self.make_app()
        async with app.run_test(size=(140, 50)) as pilot:
            review = await self.open_review(app, pilot)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("E")
            await settle(app, pilot)
            if isinstance(app.screen, InfoScreen):
                app.screen.dismiss(None)
                await settle(app, pilot)
            self.assertGreater(review.staging.summary().reassigned, 0)
            self.assertEqual(review.staging.summary().deleted, 0)
            await self.highlight(app, pilot, review, "profile", "Healer")
            await pilot.press("D")
            await settle(app, pilot)
            self.assertGreater(review.staging.summary().deleted, 0)

    async def test_focused_button_shows_what_it_would_do_with_toasts_above(self):
        app = self.make_app()
        async with app.run_test(size=BASE, notifications=True) as pilot:
            review = await self.open_review(app, pilot)
            rack = review.query_one("#tip-rack")
            self.assertFalse(rack.display)
            await self.highlight(app, pilot, review, "profile", "Healer")
            review.query_one("#act-delete", Button).focus()
            await settle(app, pilot)
            self.assertTrue(rack.display)
            tip = review.query_one("#action-tip")
            text = str(tip.render())
            self.assertIn("Delete (d)", text)
            self.assertIn("Delete 1 profile in ElvUI", text)
            bar = review.query_one("#tree-actions").region
            guide = review.query_one("#guide").region
            self.assertEqual(tip.region.bottom, guide.y)  # just above the guidance line over the bar
            review.notify("A toast")
            await settle(app, pilot)
            toasts = review.query_one("#textual-toastrack").region
            self.assertLessEqual(toasts.bottom, tip.region.y)
            review.query_one("#act-discard", Button).focus()
            await settle(app, pilot)
            self.assertIn("no pending changes", str(tip.render()))
            review.query_one("#profiles", Tree).focus()
            await settle(app, pilot)
            self.assertFalse(rack.display)
            self.assertLessEqual(review.query_one("#textual-toastrack").region.bottom, guide.y)  # above the guide
            self.assertLess(guide.y, bar.y)
