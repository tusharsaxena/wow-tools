import json
import tempfile
import time
import unittest
from pathlib import Path

from textual.app import App
from textual.widgets import Button, DataTable, Input, ProgressBar, Static, Tree

from tests.fixtures import build_wow_tree, make_config
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools.wtf_cleaner.app import CleanerSettingsScreen, WtfCleanerApp
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.cleaner import CleanResult, FileOutcome
from wowtools.tools.wtf_cleaner.report import CRITERION_COLORS, RESULT_COLUMNS, result_rows
from wowtools.tools.wtf_cleaner.review_screen import (CleanProgressScreen, ConfirmScreen, RecoveryScreen,
                                                      ResultScreen, ReviewScreen)
from wowtools.tools.wtf_cleaner.rules import CRITERIA, criterion_counts
from wowtools.tools.wtf_cleaner.safety import MARKER_NAME
from wowtools.tools.wtf_cleaner.scanner import scan
from wowtools.tools.wtf_cleaner.settings import load_settings
from wowtools.ui.widgets import ButtonRow, Ka0sCheckbox, NavHint
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen

SIZE = (140, 50)


class AppTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.backup_dir = self.tmp / "bk"
        self.cfg = make_config(self.tmp, self.root)
        self.cfg.set("wtf_cleaner", "backup_dir", str(self.backup_dir), log=False)
        self.cfg.save()

    def make_app(self, cfg=None, running=()):
        return WtfCleanerApp(cfg or self.cfg, check_updates=False, wow_check=lambda: list(running),
                             detect=lambda: [])

    async def open_review(self, app, pilot):
        await pilot.pause()
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")
        await pilot.pause()
        # Retail in the fixture has two accounts, so the account picker comes next;
        # Enter keeps the default highlight ("All accounts").
        self.assertIsInstance(app.screen, AccountScreen)
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        review = app.screen
        self.assertIsInstance(review, ReviewScreen)
        self.assertIsNotNone(review.proposal)
        return review


class ReviewFlowTest(AppTestCase):
    async def test_dry_run_flow_changes_nothing(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                self.assertEqual(len(review.proposal.items), 6)
                review.query_one("#btn-dry", Button).focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.press("y")
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertIsInstance(app.screen, ResultScreen)
                self.assertTrue(app.screen.result.dry_run)
                self.assertEqual(len(app.screen.result.would_delete), 8)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertEqual(len(list(self.backup_dir.glob("*.zip"))), 1)
        names = [r["event"] for r in records]
        self.assertIn("sv.would_delete", names)
        self.assertIn({"screen": "review", "control": "dry_run", "value": True},
                      [r["data"] for r in records if r["event"] == "ui.selection"])

    async def test_real_clean_backs_up_and_deletes(self):
        app = self.make_app()
        pushed = []
        push_screen = app.push_screen

        def spy(screen, *args, **kwargs):
            pushed.append(screen)
            return push_screen(screen, *args, **kwargs)

        app.push_screen = spy
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIsInstance(app.screen, ResultScreen)
            self.assertEqual(len(app.screen.result.deleted), 8)
            self.assertFalse(any(isinstance(s, CleanProgressScreen) for s in app.screen_stack))
        progress = [s for s in pushed if isinstance(s, CleanProgressScreen)]
        self.assertEqual(len(progress), 1)
        self.assertFalse(progress[0].dry_run)
        self.assertEqual(progress[0].stage, "delete")
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())
        self.assertFalse((self.sv / "Uninstalled.lua").exists())
        self.assertTrue((self.sv / "Auctionator.lua").exists())
        self.assertEqual(len(list(self.backup_dir.glob("*.zip"))), 1)

    async def test_declining_confirm_changes_nothing(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            self.assertIs(app.screen, review)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    async def test_toggle_excludes_item_and_criterion_keys_rebuild(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one(Tree)
            node = next(n for n in _walk(tree.root)
                        if n.data and n.data[0] == "item" and n.data[1].addon == "DisabledAddon")
            tree.focus()
            tree.move_cursor(node)
            await pilot.press("space")
            self.assertNotIn("DisabledAddon", {i.addon for i in review._selection()})
            self.assertIn("5 items", review.summary_text)
            await pilot.press("1")
            await pilot.pause()
            self.assertNotIn("Uninstalled", {i.addon for i in review.proposal.items})
            self.assertFalse(review.criteria.not_installed)

    async def test_wow_running_warning_is_shown_and_logged(self):
        app = self.make_app(running=["Wow.exe"])
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await pilot.press("c")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIn("Wow.exe", app.screen.body_text)
                await pilot.press("n")
        self.assertIn("wow.running_warning", [r["event"] for r in records])

    async def test_confirm_uses_saved_backup_setting_and_flags_no_backup(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            self.cfg.set("wtf_cleaner", "backup_before_delete", False)
            await pilot.press("c")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("No backup will be made", app.screen.alerts[0])
            await pilot.press("n")

    async def test_dry_run_key_runs_a_simulation(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("y")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("Simulate", app.screen.title_text)
            await pilot.press("y")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertTrue(app.screen.result.dry_run)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    async def test_odd_names_render_without_markup(self):
        (self.sv / "[Weird] Addon.lua").write_text("x")
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            labels = [str(n.label) for n in _walk(review.query_one(Tree).root)]
            self.assertTrue(any("[Weird] Addon" in label for label in labels))

    async def test_scan_progress_bar_hidden_after_scan(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            bar = review.query_one("#scan-progress", ProgressBar)
            label = review.query_one("#scan-label", Static)
            tree = review.query_one("#proposal", Tree)
            self.assertFalse(bar.display)
            self.assertFalse(label.display)
            self.assertTrue(tree.display)
            self.assertFalse(tree.loading)
            self.assertEqual((bar.progress, bar.total), (4, 4))


    async def test_criterion_labels_show_counts(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            retail = WowInstall(self.root).flavor("retail")
            counts = criterion_counts(scan(retail), max_age_days=review.criteria.max_age_days, now=time.time())
            self.assertEqual(counts, {"not_installed": 3, "not_enabled": 1, "older_than": 2, "stray_copies": 2})
            for index, name in enumerate(CRITERIA, start=1):
                label = review.query_one(f"#crit_{name}", Ka0sCheckbox).label
                self.assertIn(f"({counts[name]} files)", label.plain)
                self.assertTrue(label.plain.startswith(f"{index} "))
            max_age = review.query_one("#max_age", Input)
            max_age.focus()
            max_age.value = "250"
            await pilot.press("enter")
            await pilot.pause()
            self.assertIn("(0 files)", review.query_one("#crit_older_than", Ka0sCheckbox).label.plain)

    async def test_checkbox_glyphs(self):
        class Probe(App):
            def compose(self):
                yield Ka0sCheckbox("on", True, id="on")
                yield Ka0sCheckbox("off", False, id="off")

        app = Probe()
        async with app.run_test() as pilot:
            on = app.query_one("#on", Ka0sCheckbox)
            off = app.query_one("#off", Ka0sCheckbox)
            self.assertIn("✔", on.render().plain)
            self.assertNotIn("✘", on.render().plain)
            self.assertIn("✘", off.render().plain)
            on.toggle()
            await pilot.pause()
            self.assertIn("✘", on.render().plain)
            self.assertNotIn("✔", on.render().plain)

    async def test_tree_reason_colours(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            node = next(n for n in _walk(review.query_one(Tree).root)
                        if n.data and n.data[0] == "item" and n.data[1].addon == "Uninstalled")
            label = node.label
            colour = CRITERION_COLORS["not_installed"].lower()
            spans = [label.plain[sp.start:sp.end] for sp in label.spans if colour in str(sp.style).lower()]
            self.assertIn("not_installed", spans)
            self.assertIn("✔", label.plain)

    async def test_tree_marks_follow_selection(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one(Tree)
            item = next(n for n in _walk(tree.root)
                        if n.data and n.data[0] == "item" and n.data[1].addon == "OldAddon")
            item.expand()
            await pilot.pause()
            leaf = item.children[0]
            tree.focus()
            tree.move_cursor(leaf)
            await pilot.pause()
            await pilot.press("space")
            self.assertIn("◩", item.label.plain)
            self.assertIn("✘", leaf.label.plain)
            await pilot.press("n")
            self.assertIn("✘", tree.root.label.plain)

    async def test_buttons_and_keys_exist(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            self.assertEqual(review.query_one("#btn-clean", Button).variant, "error")
            self.assertEqual(review.query_one("#btn-dry", Button).variant, "primary")
            review.query_one("#btn-rescan", Button)
            self.assertFalse(review.query("#status"))
            self.assertFalse(hasattr(review, "dry_run"))
            review.query_one("#btn-clean", Button).focus()
            await pilot.press("right")
            self.assertEqual(review.focused.id, "btn-dry")
            await pilot.press("right")
            self.assertEqual(review.focused.id, "btn-rescan")
            await pilot.press("left", "left")
            self.assertEqual(review.focused.id, "btn-clean")


class RecoveryDialogTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.backup_dir.mkdir(parents=True)
        self.snapshot = self.backup_dir / "wtf-snapshot-retail-20260101-000000.zip"
        self.snapshot.write_bytes(b"zip")
        (self.backup_dir / MARKER_NAME).write_text(json.dumps({
            "snapshot": str(self.snapshot), "flavor": "_retail_", "flavor_path": str(self.root / "_retail_"),
            "started": "2026-01-01T00:00:00", "pid": 1, "suite_version": "0.1.0", "files": ["WTF/x.lua"]}),
            encoding="utf-8")

    async def open_recovery(self, app, pilot):
        await pilot.pause()
        await pilot.press("enter")  # flavor
        await pilot.pause()
        await pilot.press("enter")  # all accounts
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        self.assertIsInstance(app.screen, RecoveryScreen)
        self.assertIn(str(self.snapshot), app.screen.message)
        return app.screen

    async def test_recovery_dialog_dismiss_clears_marker_keeps_snapshot(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_recovery(app, pilot)
                await pilot.click("#recovery-dismiss")
                await pilot.pause()
                self.assertIsInstance(app.screen, ReviewScreen)
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())
        self.assertTrue(self.snapshot.exists())
        self.assertIn("recovery.incomplete_clean", [r["event"] for r in records])
        self.assertIn({"screen": "recovery", "control": "recovery", "value": "dismissed"},
                      [r["data"] for r in records if r["event"] == "ui.selection"])

    async def test_recovery_dialog_remind_keeps_both(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                screen = await self.open_recovery(app, pilot)
                self.assertEqual(screen.focused.id, "recovery-remind")
                await pilot.press("enter")
                await pilot.pause()
                self.assertIsInstance(app.screen, ReviewScreen)
                # A real clean is refused while the marker exists: nothing is deleted.
                await pilot.press("c")
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertIsInstance(app.screen, ReviewScreen)
        self.assertTrue((self.backup_dir / MARKER_NAME).exists())
        self.assertTrue(self.snapshot.exists())
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertIn({"screen": "recovery", "control": "recovery", "value": "remind"},
                      [r["data"] for r in records if r["event"] == "ui.selection"])


class AccountScopeFlowTest(AppTestCase):
    async def test_account_screen_scopes_the_review(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, AccountScreen)
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            review = app.screen
            self.assertIsInstance(review, ReviewScreen)
            self.assertEqual(review.account, "ACCT2")
            self.assertTrue(review.proposal.items)
            self.assertEqual({i.account for i in review.proposal.items}, {"ACCT2"})
            self.assertIn("Retail · ACCT2", review.sub_title)
        self.assertEqual(load_settings(Config(self.cfg.path).load()).last_account, "ACCT2")

    async def test_all_accounts_scope_in_sub_title(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            self.assertIsNone(review.account)
            self.assertEqual({i.account for i in review.proposal.items}, {"ACCT1"})
            self.assertIn("Retail · all accounts", review.sub_title)

    async def test_escape_on_account_screen_goes_back_to_flavors(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, AccountScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)

    async def test_single_account_flavor_skips_account_screen(self):
        self.cfg.set("general", "last_flavor", "_classic_era_", log=False)
        self.cfg.save()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            review = app.screen
            self.assertIsInstance(review, ReviewScreen)
            self.assertIsNone(review.account)
            self.assertIn("Classic Era · all accounts", review.sub_title)


class FirstRunTest(AppTestCase):
    async def test_setup_then_settings_then_flavor(self):
        cfg = Config(self.tmp / "fresh.cfg")
        app = self.make_app(cfg=cfg)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, SetupScreen)
            app.screen.query_one("#wow_path", Input).value = str(self.root)
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsInstance(app.screen, CleanerSettingsScreen)
            app.screen.query_one("#max_age", Input).value = "30"
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
        saved = Config(cfg.path).load()
        self.assertEqual(saved.wow_path, self.root)
        self.assertEqual(saved.get("wtf_cleaner", "max_age_days"), "30")

    async def test_settings_rejects_bad_max_age(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            screen = CleanerSettingsScreen(self.cfg, source="settings")
            app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#max_age", Input).value = "0"
            await pilot.click("#save")
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertIn("whole number", screen.error_text)

    async def test_settings_saves_backup_folder(self):
        app = self.make_app()
        target = self.tmp / "my backups"
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            screen = CleanerSettingsScreen(self.cfg, source="settings")
            app.push_screen(screen)
            await pilot.pause()
            self.assertEqual(screen.query_one("#backup_dir", Input).value, str(self.backup_dir))
            screen.query_one("#backup_dir", Input).value = str(target)
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsNot(app.screen, screen)
        self.assertEqual(load_settings(Config(self.cfg.path).load()).backup_dir, target)


class KeyboardNavigationTest(AppTestCase):
    async def test_confirm_keyboard_navigation(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("y")
            await pilot.pause()
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertTrue(confirm.query(ButtonRow))
            self.assertTrue(confirm.query(NavHint))
            self.assertEqual(confirm.focused.id, "yes")
            await pilot.press("right")
            self.assertEqual(confirm.focused.id, "no")
            await pilot.press("enter")
            await pilot.pause()
            self.assertIs(app.screen, review)
            await pilot.press("c")
            await pilot.pause()
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.focused.id, "no")
            await pilot.press("left")
            self.assertEqual(confirm.focused.id, "yes")
            await pilot.press("escape")
            await pilot.pause()
            self.assertIs(app.screen, review)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertFalse(list(self.backup_dir.glob("*.zip")))

    async def test_confirm_dismisses_false_on_enter_over_no(self):
        results = []

        class Probe(App):
            def on_mount(self):
                self.push_screen(ConfirmScreen("t", "b", default_yes=True), results.append)

        app = Probe()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("right", "enter")
            await pilot.pause()
        self.assertEqual(results, [False])

    async def test_result_screen_tables(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("y")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            screen = app.screen
            self.assertIsInstance(screen, ResultScreen)
            summary = screen.query_one("#result-summary", DataTable)
            self.assertEqual([str(c.label) for c in summary.ordered_columns], ["Item", "Value"])
            rows = {str(summary.get_row_at(i)[0]): str(summary.get_row_at(i)[1]) for i in range(summary.row_count)}
            self.assertIn("Would delete", rows)
            self.assertIn("8", rows["Would delete"])
            self.assertEqual(rows["Mode"], "Dry run")
            self.assertEqual(rows["Safety snapshot"], "not taken (dry run)")
            for key in ("Backup zip", "Size", "Skipped", "Failed"):
                self.assertIn(key, rows)
            files = screen.query_one("#result-files", DataTable)
            self.assertEqual(files.row_count, 8)
            self.assertEqual([str(c.label) for c in files.ordered_columns],
                             ["Status", "Account", "Character", "Addon", "File", "Size", "Reasons"])
            self.assertTrue(screen.query(ButtonRow))
            self.assertTrue(screen.query(NavHint))
            self.assertEqual(screen.focused.id, "review")
            await pilot.press("right", "right")
            self.assertEqual(screen.focused.id, "quit")

    async def test_real_clean_result_summary(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            summary = app.screen.query_one("#result-summary", DataTable)
            rows = {str(summary.get_row_at(i)[0]): str(summary.get_row_at(i)[1]) for i in range(summary.row_count)}
            self.assertEqual(rows["Mode"], "Clean")
            self.assertIn("8", rows["Deleted"])
            self.assertEqual(rows["Safety snapshot"], "taken and removed after success")

    async def test_setup_and_settings_keyboard_only(self):
        cfg = Config(self.tmp / "fresh.cfg")
        app = self.make_app(cfg=cfg)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            setup = app.screen
            self.assertIsInstance(setup, SetupScreen)
            self.assertEqual(setup.focused.id, "wow_path")
            self.assertTrue(setup.query(ButtonRow))
            self.assertTrue(setup.query(NavHint))
            await pilot.press(*str(self.root))
            self.assertEqual(setup.query_one("#wow_path", Input).value, str(self.root))
            await pilot.press("down")
            self.assertEqual(setup.focused.id, "save")
            await pilot.press("enter")
            await pilot.pause()
            settings = app.screen
            self.assertIsInstance(settings, CleanerSettingsScreen)
            self.assertTrue(settings.query(ButtonRow))
            self.assertTrue(settings.query(NavHint))
            self.assertFalse(settings.query("Switch"))
            order = [settings.focused.id]
            for _ in range(7):
                await pilot.press("down")
                order.append(settings.focused.id)
            self.assertEqual(order, ["max_age", "backup_dir", *[f"sw_{n}" for n in CRITERIA], "sw_backup", "save"])
            for name in (*[f"sw_{n}" for n in CRITERIA], "sw_backup"):
                self.assertIsInstance(settings.query_one(f"#{name}"), Ka0sCheckbox)
            await pilot.press("up")  # back to the backup toggle
            self.assertEqual(settings.focused.id, "sw_backup")
            self.assertTrue(settings.focused.value)
            await pilot.press("space")
            self.assertFalse(settings.focused.value)
            await pilot.press("down", "enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
        saved = load_settings(Config(cfg.path).load())
        self.assertFalse(saved.backup_before_delete)
        self.assertEqual(Config(cfg.path).load().wow_path, self.root)

    async def test_arrow_keys_stay_with_tree(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#proposal", Tree)
            self.assertIs(review.focused, tree)
            before = tree.cursor_line
            await pilot.press("down")
            await pilot.pause()
            self.assertIs(review.focused, tree)
            self.assertEqual(tree.cursor_line, before + 1)


class ResultRowsTest(unittest.TestCase):
    def test_result_rows(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_wow_tree(Path(tmp.name) / "World of Warcraft")
        retail = WowInstall(root).flavor("retail")
        acct = retail.account_dir / "ACCT1"
        result = CleanResult(dry_run=False, backup_path=None, outcomes=[
            FileOutcome(acct / "SavedVariables" / "Uninstalled.lua.bak", 2048, "deleted", "",
                        ("not_installed",)),
            FileOutcome(acct / "Realm1" / "CharA" / "SavedVariables" / "Uninstalled.lua", 10, "skipped",
                        "changed since the scan", ("not_installed", "older_than")),
            FileOutcome(acct / "SavedVariables" / "Details.lua - Copy.bak", 5, "failed", "denied",
                        ("stray_copies",)),
        ])
        rows = result_rows(result, retail)
        self.assertEqual(RESULT_COLUMNS, ("Status", "Account", "Character", "Addon", "File", "Size", "Reasons"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], ("Deleted", "ACCT1", "account-wide", "Uninstalled", "Uninstalled.lua.bak",
                                   "2.0 KB", "not_installed"))
        self.assertEqual(rows[1], ("Skipped: changed since the scan", "ACCT1", "Realm1/CharA", "Uninstalled",
                                   "Uninstalled.lua", "10 B", "not_installed, older_than"))
        self.assertEqual(rows[2][0], "Failed: denied")
        self.assertEqual(rows[2][3], "Details")
        self.assertTrue(all(len(row) == len(RESULT_COLUMNS) for row in rows))
        self.assertTrue(all(isinstance(cell, str) for row in rows for cell in row))


class SpaceKeyTest(AppTestCase):
    async def test_space_on_button_presses_it_and_leaves_selection_alone(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            before = set(review.unchecked)
            review.query_one("#btn-dry").focus()
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(review.unchecked, before)
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("n")


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)
