from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from textual.app import App
from textual.widgets import Button, DataTable, Input, OptionList, ProgressBar, Static, Tree

from tests.fixtures import BASE, TuiTestCase, build_wow_tree, make_config, settle
from wowtools.core import activity
from wowtools.core.backup import BackupError
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.paths import to_stored
from wowtools.tools.wtf_cleaner import multi
from wowtools.tools.wtf_cleaner import review_screen as review_module
from wowtools.tools.wtf_cleaner.app import CleanerSettingsScreen
from wowtools.tools.wtf_cleaner.cleaner import CleanError, CleanResult, FileOutcome
from wowtools.tools.wtf_cleaner.journal import resolve_journal_dir, latest_undoable
from wowtools.tools.wtf_cleaner.report import CRITERION_COLORS, RESULT_COLUMNS, result_rows
from wowtools.tools.wtf_cleaner.review_screen import CleanProgressScreen, RecoveryScreen, ResultScreen, ReviewScreen
from wowtools.tools.wtf_cleaner.rules import CRITERIA, criterion_counts
from wowtools.tools.wtf_cleaner.safety import MARKER_NAME
from wowtools.tools.wtf_cleaner.scanner import scan
from wowtools.tools.wtf_cleaner.settings import load_settings
from wowtools.tools.wtf_cleaner.undo import UndoResult
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.widgets import ButtonRow, Ka0sCheckbox, NavHint, action_kind

SIZE = (140, 50)


class AppTestCase(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.backup_dir = self.tmp / "bk"
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        self.tool_cfg = Config(self.config_dir / "wtf-cleaner.cfg")
        self.tool_cfg.set("wtf_cleaner", "backup_dir", str(self.backup_dir), log=False)
        self.tool_cfg.save()

    def make_app(self, cfg=None, running=(), lockers=()):
        cfg = cfg or self.cfg
        return WowToolsApp(cfg, config_dir=cfg.path.parent, check_updates=False, detect=list,
                           tool_options={"wtf-cleaner": {"wow_check": lambda: list(running),
                                                         "locker_check": lambda: list(lockers)}})

    def assert_reasons_shown_whole(self, files: DataTable) -> None:
        """Every column up to Reasons ends inside the table: why each file goes reads without scrolling."""
        columns = files.ordered_columns
        labels = [str(c.label) for c in columns]
        end = sum(c.get_render_width(files) for c in columns[:labels.index("Reasons") + 1])
        self.assertLessEqual(end, files.scrollable_content_region.width, labels)

    async def enter_tool(self, app, pilot):
        """The menu is the first screen; Enter opens the only tool, the WTF Cleaner."""
        await pilot.pause()
        self.assertIsInstance(app.screen, ToolMenuScreen)
        await pilot.press("enter")
        await pilot.pause()

    async def open_review(self, app, pilot):
        await self.enter_tool(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")
        await pilot.pause()
        # Retail in the fixture has two accounts, so the account picker comes next;
        # Enter keeps the default highlight ("All accounts").
        self.assertIsInstance(app.screen, AccountScreen)
        await pilot.press("enter")
        await pilot.pause()
        await settle(app, pilot)
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
                await settle(app, pilot)  # the running-programs check runs in a worker
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.press("y")
                await pilot.pause()
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ResultScreen)
                self.assertTrue(app.screen.result.dry_run)
                self.assertEqual(len(app.screen.result.would_delete), 8)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertEqual(len(list(self.backup_dir.glob("cleaned/*.zip"))), 1)
        names = [r["event"] for r in records]
        self.assertIn("sv.would_delete", names)
        self.assertIn({"screen": "review", "control": "dry_run", "value": True},
                      [r["data"] for r in records if r["event"] == "ui.selection"])

    async def test_clean_is_on_w_and_c_collapses(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            self.assertIn("w clean", review.query_one(NavHint).hint)
            await pilot.press("c")
            await settle(app, pilot)
            self.assertIs(app.screen, review)  # c collapses the tree, it never cleans
            tree = review.query_one("#proposal", Tree)
            self.assertTrue(all(not n.is_expanded for n in tree.root.children))
            await pilot.press("w")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertEqual(app.screen.title_text, "Back up and delete these files?")

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
            await pilot.press("w")
            await settle(app, pilot)  # the running-programs check runs in a worker
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ResultScreen)
            self.assertEqual(len(app.screen.result.deleted), 8)
            self.assertFalse(any(isinstance(s, CleanProgressScreen) for s in app.screen_stack))
        progress = [s for s in pushed if isinstance(s, CleanProgressScreen)]
        self.assertEqual(len(progress), 1)
        self.assertFalse(progress[0].dry_run)
        self.assertEqual(progress[0].stage, "validate")  # the post-clean check is the last stage
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())
        self.assertFalse((self.sv / "Uninstalled.lua").exists())
        self.assertTrue((self.sv / "Auctionator.lua").exists())
        self.assertEqual(len(list(self.backup_dir.glob("cleaned/*.zip"))), 1)

    async def test_clean_and_undo_run_inside_activity_running(self):
        seen = []
        real_execute, real_undo = multi.execute, review_module.undo_clean

        def execute(*args, **kwargs):
            seen.append(("clean", activity.wait_idle(0)))
            return real_execute(*args, **kwargs)

        def undo_clean(*args, **kwargs):
            seen.append(("undo", activity.wait_idle(0)))
            return real_undo(*args, **kwargs)

        multi.execute = execute
        review_module.undo_clean = undo_clean
        self.addCleanup(setattr, multi, "execute", real_execute)
        self.addCleanup(setattr, review_module, "undo_clean", real_undo)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("w")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ResultScreen)
            await pilot.press("r")  # back to the review (rescans)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ReviewScreen)
            await pilot.press("z")
            await settle(app, pilot)  # the running-programs check runs in a worker
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            await settle(app, pilot)
        self.assertEqual(seen, [("clean", False), ("undo", False)])
        self.assertTrue(activity.wait_idle(0))

    async def test_unexpected_clean_error_is_shown_not_fatal(self):
        def boom(*args, **kwargs):
            raise RuntimeError("disk vanished")

        real = review_module.execute_flavors
        review_module.execute_flavors = boom
        self.addCleanup(setattr, review_module, "execute_flavors", real)
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                messages = []
                review.notify = lambda message, **kwargs: messages.append(message)
                await pilot.press("w")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertTrue(app.is_running)
                self.assertFalse(app.busy)
                self.assertIs(app.screen, review)
                self.assertIsNone(app.return_code)
        self.assertEqual(len(messages), 1)
        self.assertIn("stopped unexpectedly", messages[0])
        self.assertIn("disk vanished", messages[0])
        self.assertIn(str(self.backup_dir / "backup"), messages[0])
        self.assertNotIn("Nothing was deleted", messages[0])
        errors = [r["data"] for r in records if r["event"] == "error"]
        self.assertEqual([(e["where"], e["message"]) for e in errors], [("clean", "disk vanished")])

    async def test_unexpected_dry_run_error_says_nothing_was_deleted(self):
        def boom(*args, **kwargs):
            raise RuntimeError("disk vanished")

        real = review_module.execute_flavors
        review_module.execute_flavors = boom
        self.addCleanup(setattr, review_module, "execute_flavors", real)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            messages = []
            review.notify = lambda message, **kwargs: messages.append(message)
            await pilot.press("y")  # dry run
            await settle(app, pilot)  # the running-programs check runs in a worker
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
        self.assertEqual(len(messages), 1)
        self.assertIn("stopped unexpectedly", messages[0])
        self.assertIn("Nothing was deleted", messages[0])

    async def test_declining_confirm_changes_nothing(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("w")
            await settle(app, pilot)
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

    async def test_select_all_and_none_leave_files_a_rule_hides_alone(self):
        """a / n act on the files shown: a file a switched-off rule hides keeps its tick, as under a filter."""
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            hidden = {f.path for i in review.proposal.items if i.addon == "Uninstalled" for f in i.files}
            self.assertTrue(hidden)
            review.unchecked.update(hidden)
            await pilot.press("1")  # the "not installed" rule off: its files are hidden
            await settle(app, pilot)
            self.assertNotIn("Uninstalled", {i.addon for i in review.proposal.items})
            review.query_one("#proposal", Tree).focus()
            await pilot.press("a")
            self.assertEqual(review.unchecked, hidden)
            await pilot.press("n")
            await pilot.press("1")  # back on: still unticked
            await settle(app, pilot)
            self.assertTrue(hidden <= review.unchecked)
            self.assertNotIn("Uninstalled", {i.addon for i in review._selection()})

    async def test_wow_running_warning_is_shown_and_logged(self):
        app = self.make_app(running=["Wow.exe"])
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await pilot.press("w")
                await settle(app, pilot)  # the running-programs check runs in a worker
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIn("Wow.exe", app.screen.body_text)
                await pilot.press("n")
        self.assertIn("wow.running_warning", [r["event"] for r in records])

    async def test_confirm_uses_saved_backup_setting_and_flags_no_backup(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            app.flow.tool_cfg.set("wtf_cleaner", "backup_before_delete", False)
            await pilot.press("w")
            await settle(app, pilot)  # the running-programs check runs in a worker
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("will not be zipped", app.screen.alerts[0])
            await pilot.press("n")

    async def test_dry_run_key_runs_a_simulation(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)  # the running-programs check runs in a worker
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("Simulate", app.screen.title_text)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            self.assertTrue(app.screen.result.dry_run)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    async def test_account_with_nothing_to_clean_is_listed(self):
        (self.root / "_retail_" / "WTF" / "Account" / "ACCT3" / "SavedVariables").mkdir(parents=True)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#proposal", Tree)
            accounts = {n.data[2]: str(n.label) for n in tree.root.children}
            self.assertEqual(sorted(accounts), ["ACCT1", "ACCT2", "ACCT3"])
            self.assertIn("nothing to clean", accounts["ACCT3"])
            self.assertIn("items", accounts["ACCT1"])
            tree.focus()
            tree.move_cursor(next(n for n in tree.root.children if n.data[2] == "ACCT3"))
            await pilot.press("space")  # ticking an empty account does nothing
            await pilot.pause()
            self.assertEqual(review.unchecked, set())

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
                files = counts[name]
                self.assertIn(f"({files} file{'' if files == 1 else 's'})", label.plain)  # "(1 file)", never "1 files"
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
            self.assertIn("Not installed", spans)  # the criterion's short name, as in the left pane
            self.assertIn("✔", label.plain)
            labels = [str(n.label) for n in _walk(review.query_one(Tree).root)]
            for raw in CRITERIA:
                self.assertFalse([t for t in labels if raw in t], raw)  # never a raw criterion key
            self.assertFalse([t for t in labels if re.search(r"\b1 (files|items)\b", t)], labels)  # singular
            self.assertTrue([t for t in labels if re.search(r"\b1 (file|item)\b", t)], labels)

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
            self.assertEqual(review.query_one("#btn-rescan", Button).variant, "default")  # neutral: same colour as Rescan everywhere
            self.assertFalse(review.query("#status"))
            self.assertFalse(hasattr(review, "dry_run"))
            review.query_one("#btn-clean", Button).focus()
            await pilot.press("right")
            self.assertEqual(review.focused.id, "btn-dry")
            await pilot.press("right")
            self.assertEqual(review.focused.id, "btn-rescan")
            await pilot.press("left", "left")
            self.assertEqual(review.focused.id, "btn-clean")
            await pilot.press("left")  # no wrap round: stays in the row
            self.assertEqual(review.focused.id, "btn-clean")


class RecoveryDialogTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.backup_dir.mkdir(parents=True)
        self.snapshot = self.backup_dir / "backup" / "backup-retail-20260101-000000.zip"
        self.snapshot.parent.mkdir(parents=True)
        self.snapshot.write_bytes(b"zip")
        (self.backup_dir / MARKER_NAME).write_text(json.dumps({
            "snapshot": str(self.snapshot), "flavor": "_retail_", "flavor_path": str(self.root / "_retail_"),
            "started": "2026-01-01T00:00:00", "pid": 1, "suite_version": "0.1.0", "files": ["WTF/x.lua"]}),
            encoding="utf-8")

    async def open_recovery(self, app, pilot):
        await self.enter_tool(app, pilot)
        await pilot.press("enter")  # flavor
        await pilot.pause()
        await pilot.press("enter")  # all accounts
        await pilot.pause()
        await settle(app, pilot)
        self.assertIsInstance(app.screen, RecoveryScreen)
        self.assertIn(str(self.snapshot), app.screen.message_text)
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
                await pilot.press("w")
                await settle(app, pilot)
                await pilot.press("y")
                await pilot.pause()
                await settle(app, pilot)
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
            await self.enter_tool(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, AccountScreen)
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, ReviewScreen)
            self.assertEqual(review.account, "ACCT2")
            self.assertTrue(review.proposal.items)
            self.assertEqual({i.account for i in review.proposal.items}, {"ACCT2"})
            self.assertIn("Retail · ACCT2", review.sub_title)
        self.assertEqual(load_settings(Config(self.tool_cfg.path).load()).last_account, "ACCT2")

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
            await self.enter_tool(app, pilot)
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
            await self.enter_tool(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            await pilot.press("enter")
            await pilot.pause()
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, ReviewScreen)
            self.assertIsNone(review.account)
            self.assertIn("Classic Era · all accounts", review.sub_title)


class FirstRunTest(AppTestCase):
    async def test_setup_then_settings_then_flavor(self):
        cfg = Config(self.tmp / "fresh" / "wow-tools.cfg")
        app = self.make_app(cfg=cfg)
        async with app.run_test(size=SIZE) as pilot:
            await self.enter_tool(app, pilot)
            self.assertIsInstance(app.screen, SetupScreen)
            app.screen.query_one("#wow_path", Input).value = str(self.root)
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsInstance(app.screen, CleanerSettingsScreen)
            app.screen.query_one("#max_age", Input).value = "30"
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
        self.assertEqual(Config(cfg.path).load().wow_path, self.root)
        saved = Config(cfg.path.parent / "wtf-cleaner.cfg").load()  # the tool's own file
        self.assertEqual(saved.get("wtf_cleaner", "max_age_days"), "30")
        self.assertIsNone(Config(cfg.path).load().get("wtf_cleaner", "max_age_days"))

    async def test_settings_rejects_bad_max_age(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            screen = CleanerSettingsScreen(self.tool_cfg, self.root, source="settings")
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
            screen = CleanerSettingsScreen(self.tool_cfg, self.root, source="settings")
            app.push_screen(screen)
            await pilot.pause()
            self.assertEqual(screen.query_one("#backup_dir", Input).value, str(self.backup_dir))
            screen.query_one("#backup_dir", Input).value = str(target)
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsNot(app.screen, screen)
        self.assertEqual(load_settings(Config(self.tool_cfg.path).load()).backup_dir, target)


    async def test_settings_labels_wrap_at_base(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            screen = CleanerSettingsScreen(self.tool_cfg, self.root, source="settings")
            app.push_screen(screen)
            await pilot.pause()
            for label in screen.query("Label"):
                text = str(label.render())
                self.assertLessEqual(label.region.right, BASE[0], text)
                self.assertGreaterEqual(label.region.width * label.region.height, len(text), text)

class BackupFolderValidationTest(AppTestCase):
    async def test_settings_reject_backup_dir_inside_wtf_or_relative(self):
        app = self.make_app()
        before = self.tool_cfg.path.read_bytes()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            screen = CleanerSettingsScreen(self.tool_cfg, self.root, source="settings")
            app.push_screen(screen)
            await pilot.pause()
            for raw, expected in ((str(self.root / "_retail_" / "WTF" / "bk"), "WTF"), ("backups", "full path")):
                screen.query_one("#backup_dir", Input).value = raw
                screen.query_one("#save", Button).press()
                await pilot.pause()
                self.assertIs(app.screen, screen)
                self.assertIn(expected, screen.error_text)
                self.assertIn(expected, str(screen.query_one("#settings-error", Static).render()))
        self.assertEqual(self.tool_cfg.path.read_bytes(), before)

    async def test_clean_and_dry_run_refuse_invalid_stored_backup_dir(self):
        self.tool_cfg.set("wtf_cleaner", "backup_dir", str(self.root / "_retail_" / "WTF" / "bk"), log=False)
        self.tool_cfg.save()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            for key in ("w", "y"):
                app._notifications.clear()
                await pilot.press(key)
                await pilot.pause()
                self.assertIs(app.screen, review)
                self.assertTrue(any("Fix the folder in settings" in n.message for n in app._notifications))
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertFalse((self.root / "_retail_" / "WTF" / "bk").exists())


class KeyboardNavigationTest(AppTestCase):
    async def test_confirm_keyboard_navigation(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)  # the running-programs check runs in a worker
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
            await pilot.press("w")
            await settle(app, pilot)  # the running-programs check runs in a worker
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.focused.id, "yes")  # every confirm starts on Yes, red for a clean
            self.assertEqual(action_kind(confirm.query_one("#yes", Button)), "destructive")
            await pilot.press("right")
            self.assertEqual(confirm.focused.id, "no")
            await pilot.press("left")
            self.assertEqual(confirm.focused.id, "yes")
            await pilot.press("escape")
            await pilot.pause()
            self.assertIs(app.screen, review)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertFalse(list(self.backup_dir.glob("cleaned/*.zip")))

    async def test_space_presses_buttons_and_esc_leaves_results(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("w")
            await settle(app, pilot)
            self.assertEqual(app.screen.focused.id, "yes")
            await pilot.press("right", "space")  # Space on the focused No button: cancel
            await pilot.pause()
            self.assertIs(app.screen, review)
            await pilot.press("y")
            await settle(app, pilot)
            await pilot.press("space")  # Space on the focused Yes button: run the dry run
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ResultScreen)
            self.assertFalse(app.screen.query_one("#result-summary").can_focus)
            await pilot.press("escape")
            await pilot.pause()
            await settle(app, pilot)
            self.assertIs(app.screen, review)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    async def test_confirm_dismisses_false_on_enter_over_no(self):
        results = []

        class Probe(App):
            def on_mount(self):
                self.push_screen(ConfirmScreen("t", "b"), results.append)

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
            await settle(app, pilot)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            screen = app.screen
            self.assertIsInstance(screen, ResultScreen)
            summary = screen.query_one("#result-summary", DataTable)
            self.assertEqual([str(c.label) for c in summary.ordered_columns], ["Item", "Value"])
            rows = {str(summary.get_row_at(i)[0]): str(summary.get_row_at(i)[1]) for i in range(summary.row_count)}
            self.assertIn("Would delete", rows)
            self.assertIn("8", rows["Would delete"])
            self.assertEqual(rows["Mode"], "Dry run")
            self.assertEqual(rows["WTF backup"], "not taken (dry run)")
            for key in ("Cleaned files zip", "Size", "Skipped", "Failed"):
                self.assertIn(key, rows)
            # Names inside the backup folder, which has a row of its own: a whole path does not fit at 120x30.
            self.assertTrue(rows["Cleaned files zip"].startswith(str(Path("cleaned", "dryrun-retail-"))),
                            rows["Cleaned files zip"])
            self.assertEqual(rows["Backup folder"], to_stored(self.backup_dir))
            files = screen.query_one("#result-files", DataTable)
            self.assertEqual(files.row_count, 8)
            self.assertEqual([str(c.label) for c in files.ordered_columns],
                             ["Status", "Account", "Character", "Addon", "Reasons", "Size", "File"])
            self.assertTrue(screen.query(ButtonRow))
            self.assertTrue(screen.query(NavHint))
            self.assertEqual(screen.focused.id, "review")
            await pilot.press("right", "right", "right")
            self.assertEqual(screen.focused.id, "quit")

    async def test_real_clean_result_summary(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("w")
            await settle(app, pilot)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            summary = app.screen.query_one("#result-summary", DataTable)
            rows = {str(summary.get_row_at(i)[0]): str(summary.get_row_at(i)[1]) for i in range(summary.row_count)}
            self.assertEqual(rows["Mode"], "Clean")
            self.assertIn("8", rows["Deleted"])
            self.assertTrue(rows["WTF backup"].endswith(".zip"))
            self.assertTrue(rows["WTF backup"].startswith(str(Path("backup", "backup-retail-"))), rows["WTF backup"])
            self.assertTrue(rows["Cleaned files zip"].startswith(str(Path("cleaned", "cleaned-retail-"))),
                            rows["Cleaned files zip"])
            self.assertEqual(rows["Backup folder"], to_stored(self.backup_dir))
            journal = app.screen.result.journal_path
            # The journal is in <WoW>/wow-tools/wtf-cleaner/journal, not in this backup folder: its whole path,
            # with the Undo note on a row of its own.
            self.assertFalse(journal.is_relative_to(self.backup_dir))
            self.assertEqual(rows["Run journal"], to_stored(journal))
            self.assertEqual(rows[""], "(Undo last clean (z) puts these files back)")
            self.assertEqual(rows["Post-clean check"], "passed")

    def test_multi_summary_names_the_journal_by_where_it_is(self):
        """Several flavors: the run journal's row names it inside the backup folder when it is there, else whole."""
        from wowtools.core.install import Flavor
        from wowtools.tools.wtf_cleaner.multi import FlavorRun, MultiCleanResult
        from wowtools.tools.wtf_cleaner.result_screen import multi_summary_rows
        flavor = Flavor("_retail_", self.root / "_retail_")
        journal = self.root / "wow-tools" / "wtf-cleaner" / "journal" / "journal-20261004-153304.jsonl"
        for folder, expected in ((self.backup_dir, to_stored(journal)),
                                 (self.root / "wow-tools" / "wtf-cleaner", str(Path("journal", journal.name)))):
            clean = CleanResult(dry_run=False, backup_path=folder / "cleaned" / "cleaned-retail-x.zip",
                                journal_path=journal)
            result = MultiCleanResult(dry_run=False, runs=[FlavorRun(flavor, [], result=clean)], journal_path=journal)
            rows = multi_summary_rows(result)
            self.assertEqual(rows[0], ("Run journal", expected, False))  # on top, before the flavor's block

    async def test_real_clean_result_names_the_journal_inside_the_default_backup_folder(self):
        """With no backup folder set, the default one (<WoW>/wow-tools/wtf-cleaner) holds journal/: the journal
        is named inside it, and the summary still fits at 120x30."""
        self.tool_cfg.remove("wtf_cleaner", "backup_dir", log=False)
        self.tool_cfg.save()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("w")
            await settle(app, pilot)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            summary = app.screen.query_one("#result-summary", DataTable)
            rows = {str(summary.get_row_at(i)[0]): str(summary.get_row_at(i)[1]) for i in range(summary.row_count)}
            folder = self.root / "wow-tools" / "wtf-cleaner"
            self.assertEqual(rows["Backup folder"], to_stored(folder))
            journal = app.screen.result.journal_path
            self.assertEqual(rows["Run journal"],
                             f"{journal.relative_to(folder)} (Undo last clean (z) puts these files back)")
            self.assertTrue(rows["Run journal"].startswith(str(Path("journal", ""))))
            self.assertEqual(summary.row_count, 10)
            self.assertEqual((summary.max_scroll_x, summary.max_scroll_y), (0, 0))

    async def test_result_reasons_show_at_base_for_one_flavor(self):
        acct = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        (acct / "Auctionator.lua.pre-schema8-20260926-103400").write_text("x = 1\n", encoding="utf-8")
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ResultScreen)
            self.assert_reasons_shown_whole(app.screen.query_one("#result-files", DataTable))

    async def test_real_clean_result_summary_fits_at_base(self):
        """At 120x30 a clean's summary shows every row, each value whole (no scrolling either way)."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("w")
            await settle(app, pilot)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ResultScreen)
            summary = app.screen.query_one("#result-summary", DataTable)
            self.assertEqual(summary.row_count, 11)  # the journal's whole path, then the Undo note
            self.assertEqual((summary.max_scroll_x, summary.max_scroll_y), (0, 0))

    async def test_setup_and_settings_keyboard_only(self):
        cfg = Config(self.tmp / "fresh" / "wow-tools.cfg")
        app = self.make_app(cfg=cfg)
        async with app.run_test(size=SIZE) as pilot:
            await self.enter_tool(app, pilot)
            setup = app.screen
            self.assertIsInstance(setup, SetupScreen)
            self.assertEqual(setup.focused.id, "wow_path")
            self.assertTrue(setup.query(ButtonRow))
            self.assertTrue(setup.query(NavHint))
            # Type the end of the path by key (typing every character of a long temp path took seconds).
            box = setup.query_one("#wow_path", Input)
            box.value = str(self.root)[:-3]
            box.cursor_position = len(box.value)
            await pilot.press(*str(self.root)[-3:])
            self.assertEqual(box.value, str(self.root))
            await pilot.press("down")
            self.assertEqual(setup.focused.id, "keep-backups")
            await pilot.press("down")
            self.assertEqual(setup.focused.id, "keep-journals")
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
            self.assertEqual(order, ["max_age", "backup_dir", *[f"sw_{n}" for n in CRITERIA],
                                     "sw_backup", "save"])
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
        saved = load_settings(Config(cfg.path.parent / "wtf-cleaner.cfg").load())
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


    async def test_left_and_right_switch_panes(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#proposal", Tree)
            self.assertIs(review.focused, tree)
            await pilot.press("left")
            self.assertEqual(review.focused.id, f"crit_{CRITERIA[0]}")
            await pilot.press("down")
            self.assertEqual(review.focused.id, f"crit_{CRITERIA[1]}")
            await pilot.press("right")
            self.assertIs(review.focused, tree)
            await pilot.press("left")  # back to the filter used last
            self.assertEqual(review.focused.id, f"crit_{CRITERIA[1]}")
            review.query_one("#btn-rescan", Button).focus()
            await pilot.press("right")  # past the last button: on to the tree
            self.assertIs(review.focused, tree)
            review.query_one("#max_age", Input).focus()
            await pilot.press("right")  # the input keeps its arrows
            self.assertEqual(review.focused.id, "max_age")


class RebuildIndicatorTest(AppTestCase):
    async def test_criterion_change_shows_indicator_then_rebuilds_once(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#proposal", Tree)
            calls = []
            original = review._rebuild
            review._rebuild = lambda: (calls.append(tree.loading), original())
            review.criteria.not_installed = False
            review._schedule_rebuild()
            review._schedule_rebuild()  # a second change before the rebuild runs is folded into it
            self.assertTrue(tree.loading)
            self.assertIn("Updating the list", str(review.query_one("#summary", Static).render()))
            await pilot.pause()
            await pilot.pause()
            self.assertEqual(calls, [True])  # one rebuild, run while the indicator was showing
            self.assertFalse(tree.loading)
            self.assertNotIn("Uninstalled", {i.addon for i in review.proposal.items})

    async def test_toggle_relabels_only_the_branch_and_ancestors(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#proposal", Tree)
            node = next(n for n in _walk(tree.root) if n.data and n.data[0] == "item")
            tree.move_cursor(node)
            await pilot.press("space")
            self.assertTrue(str(node.label).startswith("✘"))
            self.assertTrue(str(tree.root.label).startswith("◩"))


class ProposalLoggingTest(AppTestCase):
    """F-006: interactive rebuilds log nothing per item; the scan logs one summary, a confirmed run the items."""

    async def test_scan_logs_one_proposal_summary_and_no_items(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
        built = [r for r in records if r["event"] == "proposal.built"]
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["data"]["items"], 6)
        self.assertEqual([r for r in records if r["event"] == "proposal.item"], [])

    async def test_criterion_toggle_logs_no_proposal_items(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                records.clear()
                await pilot.press("1")
                await settle(app, pilot)
                self.assertFalse(review.criteria.not_installed)
                review.query_one("#max_age", Input).value = "30"
                review.query_one("#max_age", Input).focus()
                await pilot.press("enter")
                await settle(app, pilot)
        names = [r["event"] for r in records]
        self.assertNotIn("proposal.item", names)
        self.assertNotIn("proposal.built", names)

    async def test_confirmed_clean_logs_selected_items(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                tree = review.query_one(Tree)
                node = next(n for n in _walk(tree.root)
                            if n.data and n.data[0] == "item" and n.data[1].addon == "DisabledAddon")
                tree.focus()
                tree.move_cursor(node)
                await pilot.press("space")
                await pilot.press("y")  # dry run
                await settle(app, pilot)  # the running-programs check runs in a worker
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertEqual([r for r in records if r["event"] == "proposal.item"], [])
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ResultScreen)
        items = [r for r in records if r["event"] == "proposal.item"]
        self.assertEqual(len(items), 5)  # one per selected addon group, the unticked one left out
        self.assertNotIn("DisabledAddon", {r["data"]["addon"] for r in items})
        self.assertTrue(all(r["dry_run"] is True for r in items))

    async def test_declined_confirm_logs_no_items(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await pilot.press("w")
                await settle(app, pilot)
                await pilot.press("n")
                await pilot.pause()
        self.assertEqual([r for r in records if r["event"] == "proposal.item"], [])


class PreflightWorkerTest(AppTestCase):
    """F-005: the running-programs checks run in a worker; the screen keeps drawing meanwhile."""

    def make_slow_app(self, release):
        def slow_check():
            release.wait(5)
            return []
        return WowToolsApp(self.cfg, config_dir=self.cfg.path.parent, check_updates=False, detect=list,
                           tool_options={"wtf-cleaner": {"wow_check": slow_check, "locker_check": list}})

    async def test_preflight_runs_in_a_worker(self):
        release = threading.Event()
        self.addCleanup(release.set)
        app = self.make_slow_app(release)
        pushed = []
        push_screen = app.push_screen
        app.push_screen = lambda screen, *a, **k: (pushed.append(screen), push_screen(screen, *a, **k))[1]
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            started = time.monotonic()
            await pilot.press("w")
            await pilot.pause()
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertIs(app.screen, review)
            self.assertIn("Checking for running programs", str(review.query_one("#summary", Static).render()))
            await pilot.press("w")  # ignored while the check runs
            await pilot.press("y")
            await pilot.pause()
            release.set()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertEqual(len([s for s in pushed if isinstance(s, ConfirmScreen)]), 1)
            self.assertIn("Back up and delete", app.screen.title_text)
            await pilot.press("n")
            await pilot.pause()
            self.assertIs(app.screen, review)
            self.assertNotIn("Checking", str(review.query_one("#summary", Static).render()))

    async def test_undo_check_runs_in_a_worker(self):
        release = threading.Event()
        release.set()
        app = self.make_slow_app(release)
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("w")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ResultScreen)
            await pilot.press("r")
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, ReviewScreen)
            release.clear()
            started = time.monotonic()
            await pilot.press("z")
            await pilot.pause()
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertIs(app.screen, review)
            await pilot.press("z")  # ignored while the check runs
            release.set()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("Undo the clean", app.screen.title_text)
            await pilot.press("n")

    async def test_selection_cannot_change_while_the_check_runs(self):
        """R2: the confirm and the clean use what the tree shows; unticking during the check must not be ignored."""
        release = threading.Event()
        self.addCleanup(release.set)
        app = self.make_slow_app(release)
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            before = review._selection_by_flavor()
            self.assertTrue(before)
            await pilot.press("w")
            await pilot.pause()
            for key in ("n", "space", "1", "3"):  # select none, untick, two criteria: all ignored meanwhile
                await pilot.press(key)
                await pilot.pause()
            self.assertEqual(review._selection_by_flavor(), before)
            self.assertTrue(review.query_one("#max_age", Input).disabled)
            release.set()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn(review._counts([i for _, items in before for i in items]), app.screen.body_text)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertFalse(review.query_one("#max_age", Input).disabled)
            await pilot.press("n")  # select none works again after the check
            await pilot.pause()
            self.assertEqual(review._selection_by_flavor(), [])

    async def test_leaving_during_the_check_shows_no_confirm(self):
        release = threading.Event()
        self.addCleanup(release.set)
        app = self.make_slow_app(release)
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("f")  # back to the flavor picker
            await pilot.pause()
            release.set()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)


class ProgressPopupTest(AppTestCase):
    async def test_every_stage_has_a_title_and_unknown_totals_are_indeterminate(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            screen = CleanProgressScreen(dry_run=False)
            await app.push_screen(screen)
            await pilot.pause()
            self.assertEqual(str(screen.query_one("#clean-stage", Static).render()), "Checking selected files")
            for stage in ("check", "lock_check", "snapshot_list", "snapshot", "snapshot_verify", "backup",
                          "verify", "delete", "validate"):
                screen.update_progress(stage, 1, 2, "x")
                self.assertNotEqual(screen.stage_title(stage), stage)
            screen.update_progress("snapshot_list", 300, 0, "300 files found")
            self.assertIsNone(screen.query_one("#clean-progress", ProgressBar).total)
            screen.update_progress("delete", 1, 1, "WTF/" + "a" * 300)
            await pilot.pause()
            self.assertEqual(screen.query_one("#clean-file", Static).size.height, 2)
            screen.update_progress("delete", 1, 1, "short")
            await pilot.pause()
            self.assertEqual(screen.query_one("#clean-file", Static).size.height, 2)


class LockerWarningTest(AppTestCase):
    async def test_clean_confirm_warns_about_raider_io_but_dry_run_does_not(self):
        app = self.make_app(lockers=("RaiderIO.exe",))
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            with capture_events() as records:
                await pilot.press("y")
                await settle(app, pilot)
                self.assertNotIn("RaiderIO", app.screen.body_text)
                await pilot.press("n")
                await pilot.pause()
                await pilot.press("w")
                await settle(app, pilot)
                self.assertIn("RaiderIO.exe appears to be running", app.screen.body_text)
            self.assertIn("locker.running_warning", [r["event"] for r in records])


class AllFlavorsTest(AppTestCase):
    def setUp(self):
        super().setUp()
        self.era_sv = self.root / "_classic_era_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        (self.era_sv / "Gone.lua").write_text("x")  # not installed in Classic Era: something to clean there

    async def open_all(self, app, pilot):
        await self.enter_tool(app, pilot)
        picker = app.screen
        self.assertIsInstance(picker, FlavorScreen)
        picker.query_one("#flavors", OptionList).highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        await settle(app, pilot)
        review = app.screen
        self.assertIsInstance(review, ReviewScreen)  # no account picker with All flavors
        self.assertIsNotNone(review.proposal)
        return review

    async def run_mode(self, app, pilot, key):
        await pilot.press(key)
        await settle(app, pilot)  # the running-programs check runs in a worker
        self.assertIsInstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()
        await settle(app, pilot)

    async def test_undo_after_a_clean_across_flavors(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_all(app, pilot)
            await self.run_mode(app, pilot, "w")
            await pilot.press("r")
            await pilot.pause()
            await settle(app, pilot)
            await pilot.press("z")
            await settle(app, pilot)  # the running-programs check runs in a worker
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("9 files deleted from Classic Era, Retail?", app.screen.body_text)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen.result, UndoResult)
            self.assertEqual(len(app.screen.result.restored), 9)
        self.assertTrue((self.era_sv / "Gone.lua").exists())
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    async def test_all_flavors_option_is_first_and_remembered(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.enter_tool(app, pilot)
            options = app.screen.query_one("#flavors", OptionList)
            self.assertEqual(options.get_option_at_index(0).id, ALL_FLAVORS)
            self.assertIn("All flavors", str(options.get_option_at_index(0).prompt))
            # never chosen before: [general] last_flavor (the current habit) is preselected
            self.assertEqual(options.get_option_at_index(options.highlighted).id, "_retail_")
            await pilot.press("escape")
            await pilot.pause()
            review = await self.open_all(app, pilot)
            self.assertIsNone(review.account)
            self.assertIn("All flavors · all accounts", review.sub_title)
            await pilot.press("f")
            await pilot.pause()
            options = app.screen.query_one("#flavors", OptionList)
            self.assertEqual(options.highlighted, 0)
        self.assertEqual(Config(self.tool_cfg.path).load().get("wtf_cleaner", "last_flavor_choice"), "")
        self.assertEqual(load_settings(Config(self.tool_cfg.path).load()).last_flavor_choice, "")
        self.assertEqual(Config(self.cfg.path).load().last_flavor, "_retail_")

    async def test_one_flavor_is_remembered_and_updates_last_flavor(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.enter_tool(app, pilot)
            options = app.screen.query_one("#flavors", OptionList)
            options.highlighted = 2  # Classic Era (All, Anniversary, Classic Era, Retail)
            await pilot.press("enter")
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ReviewScreen)
        self.assertEqual(load_settings(Config(self.tool_cfg.path).load()).last_flavor_choice, "_classic_era_")
        self.assertEqual(Config(self.cfg.path).load().last_flavor, "_classic_era_")

    async def test_tree_has_a_node_per_flavor_and_failed_scans_say_why(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_all(app, pilot)
            tree = review.query_one("#proposal", Tree)
            self.assertIn("All flavors", str(tree.root.label))
            flavors = {str(n.label).strip().lstrip("✔◩✘ ").split("  ")[0]: n for n in tree.root.children}
            self.assertEqual(sorted(flavors), ["Anniversary", "Classic Era", "Retail"])
            # In a few words (the whole message, with its path, is in the log): the line fits the tree at 120x30.
            self.assertEqual(str(flavors["Anniversary"].label).split("  ", 2)[-1],
                             "not scanned: no addons installed")
            self.assertFalse(flavors["Anniversary"].children)
            self.assertEqual([n.data[2] for n in flavors["Classic Era"].children], ["ACCT1"])
            self.assertEqual([n.data[2] for n in flavors["Retail"].children], ["ACCT1", "ACCT2"])
            self.assertEqual(len(review.proposal.items), 7)
            self.assertEqual({f.folder for f, _ in review._selection_by_flavor()}, {"_classic_era_", "_retail_"})
            await pilot.press("n")
            self.assertEqual(review._selection(), [])
            self.assertIn("✘", str(flavors["Retail"].label))
            await pilot.press("a")
            self.assertEqual(sum(len(i.files) for i in review._selection()), 9)

    async def test_flavor_with_nothing_to_clean_says_so(self):
        (self.era_sv / "Gone.lua").unlink()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_all(app, pilot)
            tree = review.query_one("#proposal", Tree)
            era = next(n for n in tree.root.children if "Classic Era" in str(n.label))
            self.assertIn("nothing to clean", str(era.label))

    async def test_every_flavor_failing_shows_the_error(self):
        for folder in ("_classic_era_", "_retail_"):
            for addon in (self.root / folder / "Interface" / "AddOns").iterdir():
                for f in addon.iterdir():
                    f.unlink()
                addon.rmdir()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.enter_tool(app, pilot)
            app.screen.query_one("#flavors", OptionList).highlighted = 0
            await pilot.press("enter")
            await pilot.pause()
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, ReviewScreen)
            self.assertIsNone(review.proposal)
            self.assertIn("No addons found", review.summary_text)

    async def test_confirm_lists_each_flavor_and_checks_wow_for_all(self):
        app = self.make_app(running=["WowClassic.exe"])
        async with app.run_test(size=SIZE) as pilot:
            await self.open_all(app, pilot)
            await pilot.press("w")
            await settle(app, pilot)  # the running-programs check runs in a worker
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertIn("Classic Era: 1 addon group, 1 file", confirm.body_text)
            self.assertIn("Retail: 6 addon groups, 8 files", confirm.body_text)
            self.assertIn("WowClassic.exe", confirm.body_text)
            self.assertNotIn("Anniversary", confirm.body_text)
            await pilot.press("n")

    async def test_not_scanned_flavor_lines_fit_the_tree_at_base(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_all(app, pilot)
            tree = review.query_one("#proposal", Tree)
            lines = [n for n in tree.root.children if "not scanned" in str(n.label)]
            self.assertTrue(lines)
            for node in lines:  # the label after the tree's "├── " guide
                self.assertLessEqual(4 + node.label.cell_len, tree.scrollable_content_region.width, node.label)

    async def test_result_reasons_show_at_base(self):
        """At 120x30 the per-file table's Reasons column shows whole, for one flavor and for All flavors (the
        Flavor column): a long stray-copy file name ends at the window's edge instead."""
        acct = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        (acct / "Auctionator.lua.pre-schema8-20260926-103400").write_text("x = 1\n", encoding="utf-8")
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_all(app, pilot)
            await self.run_mode(app, pilot, "y")
            self.assertIsInstance(app.screen, ResultScreen)
            files = app.screen.query_one("#result-files", DataTable)
            labels = [str(c.label) for c in files.ordered_columns]
            self.assertIn("Flavor", labels)
            names = [str(files.get_row_at(i)[labels.index("File")]) for i in range(files.row_count)]
            self.assertTrue(any("pre-schema8" in name for name in names), names)
            self.assert_reasons_shown_whole(files)

    async def test_dry_run_across_flavors_deletes_nothing(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_all(app, pilot)
            await self.run_mode(app, pilot, "y")
            screen = app.screen
            self.assertIsInstance(screen, ResultScreen)
            self.assertTrue(screen.result.dry_run)
            self.assertEqual(len(screen.result.would_delete), 9)
            files = screen.query_one("#result-files", DataTable)
            self.assertEqual([str(c.label) for c in files.ordered_columns][:2], ["Status", "Flavor"])
            self.assertEqual(files.row_count, 9)
            summary = screen.query_one("#result-summary", DataTable)
            cells = [str(summary.get_row_at(i)[0]) for i in range(summary.row_count)]
            self.assertIn("Classic Era", cells)
            self.assertIn("Retail", cells)
            self.assertEqual(cells.count("Cleaned files zip"), 2)
        self.assertTrue((self.era_sv / "Gone.lua").exists())
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertFalse(list(self.backup_dir.glob("backup/*.zip")))
        self.assertEqual(len(list(self.backup_dir.glob("cleaned/*.zip"))), 2)

    async def test_real_clean_across_flavors_backs_up_each_flavor(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_all(app, pilot)
            await self.run_mode(app, pilot, "w")
            screen = app.screen
            self.assertIsInstance(screen, ResultScreen)
            self.assertEqual(len(screen.result.deleted), 9)
            summary = screen.query_one("#result-summary", DataTable)
            values = [str(summary.get_row_at(i)[1]) for i in range(summary.row_count)]
            self.assertEqual(values.count("passed"), 2)
        self.assertEqual(len(list(self.backup_dir.glob("backup/backup-classic_era-*.zip"))), 1)
        self.assertEqual(len(list(self.backup_dir.glob("backup/backup-retail-*.zip"))), 1)
        self.assertFalse((self.era_sv / "Gone.lua").exists())
        self.assertFalse((self.sv / "Uninstalled.lua").exists())
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())

    async def test_backup_error_in_first_flavor_stops_before_the_second(self):
        calls = []

        def fake(items, flavor, **kwargs):
            calls.append(flavor.folder)
            raise BackupError("disk full")

        real = multi.execute
        multi.execute = fake
        self.addCleanup(setattr, multi, "execute", real)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_all(app, pilot)
            await self.run_mode(app, pilot, "w")
            self.assertIs(app.screen, review)
        self.assertEqual(calls, ["_classic_era_"])
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertTrue((self.era_sv / "Gone.lua").exists())

    async def test_stop_in_a_later_flavor_keeps_earlier_results(self):
        real = multi.execute

        def fake(items, flavor, **kwargs):
            if flavor.folder == "_retail_":
                raise BackupError("disk full")
            return real(items, flavor, **kwargs)

        multi.execute = fake
        self.addCleanup(setattr, multi, "execute", real)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_all(app, pilot)
            await self.run_mode(app, pilot, "w")
            screen = app.screen
            self.assertIsInstance(screen, ResultScreen)
            self.assertEqual(len(screen.result.deleted), 1)
            summary = screen.query_one("#result-summary", DataTable)
            rows = {str(summary.get_row_at(i)[0]): str(summary.get_row_at(i)[1]) for i in range(summary.row_count)}
            self.assertIn("Classic Era", rows["Done"])
            self.assertIn("Retail", rows["Stopped"])
            self.assertIn("disk full", rows["Stopped"])
        self.assertFalse((self.era_sv / "Gone.lua").exists())
        self.assertTrue((self.sv / "Uninstalled.lua").exists())


    async def test_stop_with_files_missing_does_not_claim_nothing_deleted(self):
        real = multi.execute

        def fake(items, flavor, **kwargs):
            if flavor.folder == "_retail_":
                error = CleanError("Clean stopped (boom) and restoring the 3 deleted files failed (bad zip)")
                error.files_missing = True
                raise error
            return real(items, flavor, **kwargs)

        multi.execute = fake
        self.addCleanup(setattr, multi, "execute", real)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_all(app, pilot)
            await self.run_mode(app, pilot, "w")
            screen = app.screen
            self.assertIsInstance(screen, ResultScreen)
            summary = screen.query_one("#result-summary", DataTable)
            rows = {str(summary.get_row_at(i)[0]): str(summary.get_row_at(i)[1]) for i in range(summary.row_count)}
            self.assertIn("restoring the 3 deleted files failed", rows["Stopped"])
            self.assertNotIn("nothing deleted", rows["Stopped"])

    async def test_first_flavor_stop_names_the_flavor_and_what_was_not_started(self):
        def fake(items, flavor, **kwargs):
            error = CleanError("Clean stopped (boom) and restoring the 2 deleted files failed (bad zip)")
            error.files_missing = True
            raise error

        real = multi.execute
        multi.execute = fake
        self.addCleanup(setattr, multi, "execute", real)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_all(app, pilot)
            messages = []
            review.notify = lambda message, **kwargs: messages.append(message)
            await self.run_mode(app, pilot, "w")
            self.assertIs(app.screen, review)
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].startswith("Classic Era: Clean stopped"), messages[0])
        self.assertNotIn("Nothing was deleted", messages[0])
        self.assertIn("Not started: Retail.", messages[0])

    async def test_first_flavor_backup_error_still_says_nothing_deleted(self):
        def fake(items, flavor, **kwargs):
            raise BackupError("disk full")

        real = multi.execute
        multi.execute = fake
        self.addCleanup(setattr, multi, "execute", real)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_all(app, pilot)
            messages = []
            review.notify = lambda message, **kwargs: messages.append(message)
            await self.run_mode(app, pilot, "w")
        self.assertEqual(messages, ["Classic Era: Nothing was deleted: disk full\nNot started: Retail."])

    async def test_summary_scrolls_from_the_keyboard_with_several_flavors(self):
        app = self.make_app()
        async with app.run_test(size=(140, 24)) as pilot:
            await self.open_all(app, pilot)
            await self.run_mode(app, pilot, "y")
            screen = app.screen
            self.assertIsInstance(screen, ResultScreen)
            summary = screen.query_one("#result-summary", DataTable)
            self.assertTrue(summary.can_focus)
            self.assertGreater(summary.max_scroll_y, 0)  # clipped at this height
            summary.focus()
            await pilot.pause()
            self.assertIs(app.focused, summary)
            await pilot.press(*["down"] * 30)
            await pilot.pause(0.5)
            self.assertIs(app.focused, summary)  # the arrows scroll the summary, not move focus
            self.assertEqual(summary.scroll_y, summary.max_scroll_y)

    async def test_wow_check_covers_only_the_flavors_in_the_selection(self):
        seen = []

        def fake_check_for(flavors):
            seen.append([f.folder for f in flavors])
            return lambda: ["WowClassic.exe"] if any(f.folder != "_retail_" for f in flavors) else []

        real = review_module.wow_check_for
        review_module.wow_check_for = fake_check_for
        self.addCleanup(setattr, review_module, "wow_check_for", real)
        app = WowToolsApp(self.cfg, config_dir=self.cfg.path.parent, check_updates=False, detect=list,
                          tool_options={"wtf-cleaner": {"locker_check": list}})
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_all(app, pilot)
            full = review._selection_by_flavor()
            review._selection_by_flavor = lambda: [(f, items) for f, items in full if f.folder == "_retail_"]
            await pilot.press("w")
            await settle(app, pilot)  # the running-programs check runs in a worker
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertNotIn("WowClassic.exe", confirm.body_text)
            await pilot.press("n")
        self.assertEqual(seen, [["_retail_"]])


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
        self.assertEqual(RESULT_COLUMNS, ("Status", "Account", "Character", "Addon", "Reasons", "Size", "File"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], ("Deleted", "ACCT1", "account-wide", "Uninstalled", "not_installed", "2.0 KB",
                                   "Uninstalled.lua.bak"))
        self.assertEqual(rows[1], ("Skipped: changed since the scan", "ACCT1", "Realm1/CharA", "Uninstalled",
                                   "not_installed, older_than", "10 B", "Uninstalled.lua"))
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
            await settle(app, pilot)  # the running-programs check runs in a worker
            self.assertEqual(review.unchecked, before)
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("n")


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


class UndoLastCleanTest(AppTestCase):
    async def run_key(self, app, pilot, key, answer="y"):
        await pilot.press(key)
        await settle(app, pilot)  # the running-programs check runs in a worker
        self.assertIsInstance(app.screen, ConfirmScreen)
        await pilot.press(answer)
        await pilot.pause()
        await settle(app, pilot)

    async def back_to_review(self, app, pilot):
        await pilot.press("r")  # result screen -> review: rescans
        await pilot.pause()
        await settle(app, pilot)
        self.assertIsInstance(app.screen, ReviewScreen)
        return app.screen

    async def test_undo_last_clean_puts_the_files_back(self):
        journals = resolve_journal_dir(self.root)
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                button = review.query_one("#btn-undo", Button)
                self.assertEqual(str(button.label), "Undo last clean")
                self.assertEqual(button.variant, "warning")  # amber: puts a change back
                self.assertTrue(button.disabled)  # nothing to undo yet
                await pilot.press("z")
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                await self.run_key(app, pilot, "w")
                self.assertIsInstance(app.screen, ResultScreen)
                rows = app.screen.summary_rows()
                at = [item for item, _ in rows].index("Run journal")
                # the journal is outside this backup folder: its whole path, the Undo note on the next row
                self.assertIn("Undo last clean (z)", rows[at + 1][1])
                review = await self.back_to_review(app, pilot)
                self.assertFalse(review.query_one("#btn-undo", Button).disabled)
                await pilot.press("z")
                await settle(app, pilot)  # the running-programs check runs in a worker
                confirm = app.screen
                self.assertIsInstance(confirm, ConfirmScreen)
                self.assertRegex(confirm.title_text, r"^Undo the clean from \d{4}-\d\d-\d\d \d\d:\d\d\?$")
                self.assertIn("Put back 8 files deleted from Retail?", confirm.body_text)
                self.assertEqual(confirm.focused.id, "yes")  # starts on Yes, in the destructive colour
                self.assertEqual(action_kind(confirm.query_one("#yes", Button)), "destructive")
                await pilot.press("y")
                await pilot.pause()
                await settle(app, pilot)
                result_screen = app.screen
                self.assertIsInstance(result_screen, ResultScreen)
                self.assertIsInstance(result_screen.result, UndoResult)
                self.assertEqual(result_screen.sub_title, "WTF Cleaner · undo result")
                self.assertEqual(len(result_screen.result.restored), 8)
                self.assertEqual(result_screen.query_one("#result-files", DataTable).row_count, 8)
                self.assertEqual(dict(result_screen.summary_rows())["Restored"], "8 files")
                review = await self.back_to_review(app, pilot)
                self.assertTrue(review.query_one("#btn-undo", Button).disabled)  # undone: nothing left to undo
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertIsNone(latest_undoable(journals))
        names = [r["event"] for r in records]
        self.assertIn("clean.undo_completed", names)
        self.assertIn({"screen": "review", "control": "undo", "value": True},
                      [r["data"] for r in records if r["event"] == "ui.selection"])

    async def test_undo_confirm_no_changes_nothing(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_key(app, pilot, "w")
            await self.back_to_review(app, pilot)
            await self.run_key(app, pilot, "z", answer="n")
            self.assertIsInstance(app.screen, ReviewScreen)
        self.assertFalse((self.sv / "Uninstalled.lua").exists())
        self.assertIsNotNone(latest_undoable(resolve_journal_dir(self.root)))

    async def test_dry_run_offers_no_undo(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_key(app, pilot, "y")
            self.assertNotIn("Run journal", dict(app.screen.summary_rows()))
            review = await self.back_to_review(app, pilot)
            self.assertTrue(review.query_one("#btn-undo", Button).disabled)
        self.assertFalse(resolve_journal_dir(self.root).exists())

    async def test_undo_is_disabled_while_scanning_or_busy(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_key(app, pilot, "w")
            review = await self.back_to_review(app, pilot)
            button = review.query_one("#btn-undo", Button)
            self.assertFalse(button.disabled)
            review._show_scan_progress(True)
            self.assertTrue(button.disabled)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIs(app.screen, review)  # no confirm while scanning
            review._show_scan_progress(False)
            self.assertFalse(button.disabled)
            app.busy = True
            review._refresh_undo()
            self.assertTrue(button.disabled)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            app.busy = False
            review._refresh_undo()
            self.assertFalse(button.disabled)

    async def test_undo_confirm_warns_when_wow_is_running(self):
        app = self.make_app(running=["Wow.exe (pid 1)"])
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_key(app, pilot, "w")
            await self.back_to_review(app, pilot)
            await pilot.press("z")
            await settle(app, pilot)  # the running-programs check runs in a worker
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("WoW appears to be running", app.screen.body_text)

    async def test_settings_have_no_retention_inputs(self):
        """Feedback round 1: backups and journals to keep are global ([general], the `s` screen)."""
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            screen = CleanerSettingsScreen(self.tool_cfg, self.root, source="settings")
            app.push_screen(screen)
            await pilot.pause()
            for box in ("#keep_backups", "#keep_journals", "#keep-backups", "#keep-journals"):
                self.assertFalse(screen.query(box), box)

    async def test_retention_comes_from_general_not_the_tool_file(self):
        """Feedback round 1: a stale per-tool keep_backups is ignored; the global value is used (0 = keep all)."""
        self.tool_cfg.set("wtf_cleaner", "keep_backups", "3", log=False)
        self.tool_cfg.save()
        for keep, wanted in (("7", "the newest 7 of this flavor are kept"), ("0", "all of this flavor are kept")):
            self.cfg.set("general", "keep_backups", keep, log=False)
            app = self.make_app()
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                review.query_one("#btn-dry", Button).focus()
                await pilot.pause()
                await pilot.press("enter")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIn(wanted, app.screen.body_text)


class TreeFilterTest(AppTestCase):
    """Spec D7/D8 on the WTF Cleaner review: the filter narrows the proposal (on top of the criteria), a / n act on
    what it shows, hidden ticks stay, count and are said in the summary and the confirm; Esc clears it."""

    def addons(self, review) -> set[str]:
        return {n.data[1].addon for n in _walk(review.query_one("#proposal", Tree).root)
                if n.data and n.data[0] == "item"}

    async def test_filter_narrows_and_keeps_hidden_ticks(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            every = set(review.all_tick_keys())
            self.assertGreater(len(self.addons(review)), 1)
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press(*"UNINST")
            await settle(app, pilot)
            self.assertEqual(self.addons(review), {"Uninstalled"})
            shown = {f.path for i in review.proposal.items if i.addon == "Uninstalled" for f in i.files}
            self.assertEqual(set(review.shown_tick_keys()), shown)
            await pilot.press("enter")  # keeps the filter, back to the tree
            await pilot.pause()
            await pilot.press("n")
            self.assertEqual(review.unchecked, shown)  # only what the filter shows
            note = f"{len(every - shown)} selected files are hidden by the filter"
            self.assertIn(note, review.summary_text)
            self.assertTrue(review.summary_text.startswith("Selected: "))
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn(f"{note}: they are simulated too.", app.screen.body_text)
            app.screen.dismiss(False)
            await settle(app, pilot)
            await pilot.press("a")
            self.assertEqual(review.unchecked, set())
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press("escape")  # clears the filter: everything again, nothing hidden
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertGreater(len(self.addons(review)), 1)
            self.assertNotIn("hidden by the filter", review.summary_text)

    async def test_filter_matches_accounts_and_files_and_opens_the_addon(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            item = review.proposal.items[0]
            review.filter_input().value = item.files[0].name
            await settle(app, pilot)
            tree = review.query_one("#proposal", Tree)
            node = next(n for n in _walk(tree.root) if n.data and n.data[0] == "item"
                        and n.data[1].key == item.key)
            self.assertTrue(node.is_expanded)  # a file in it matches: the addon opens
            self.assertEqual([str(c.label).split("  ")[0][2:] for c in node.children], [item.files[0].name])
            review.filter_input().value = item.account
            await settle(app, pilot)
            self.assertEqual({n.data[2] for n in tree.root.children if n.data}, {item.account})  # its account
