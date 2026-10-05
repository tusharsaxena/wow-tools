from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Checkbox, DataTable, Input, OptionList, Static, Tree

from tests.fixtures import BASE, TuiTestCase, build_interface_tree, build_wow_tree, make_config, settle
from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools import TOOLS
from wowtools.tools.interface_backup import app as app_module
from wowtools.tools.interface_backup import restore_screen as restore_module
from wowtools.tools.interface_backup import review_screen as review_module
from wowtools.tools.interface_backup.app import BackupSettingsScreen
from wowtools.tools.interface_backup.restore import PartOutcome, RestoreError, RestoreResult, RestoreStopped
from wowtools.tools.interface_backup.restore_screen import RestoreResultScreen, RestoreScreen
from wowtools.tools.interface_backup.review_screen import (BackupProgressScreen, BackupResultScreen,
                                                           BackupReviewScreen)
from wowtools.tools.interface_backup.settings import load_settings
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.widgets import NavHint, action_kind

SIZE = (140, 50)


class InterfaceBackupAppTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.root = build_interface_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        self.bk = self.tmp / "bk"

    def save_tool_cfg(self, **values):
        tool_cfg = Config(self.config_dir / "interface-backup.cfg")
        for key, value in values.items():
            tool_cfg.set("interface_backup", key, value, log=False)
        tool_cfg.save()

    def make_app(self, running=()):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={"interface-backup": {"wow_check": lambda: list(running)}})

    async def open_tool(self, app, pilot):
        await pilot.pause()
        self.assertIsInstance(app.screen, ToolMenuScreen)
        await pilot.press("down", "down", "enter")  # third tool in the menu
        await pilot.pause()

    async def open_review(self, app, pilot, keys=("enter",)):
        await self.open_tool(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press(*keys)  # Enter: "All flavors"
        await settle(app, pilot)
        self.assertIsInstance(app.screen, BackupReviewScreen)
        return app.screen

    def zips(self):
        return sorted(p.name for p in (self.bk / "interface-backup").glob("backup-*.zip"))

    def assert_on_screen(self, widget, size=BASE):
        r = widget.region
        self.assertTrue(r.width > 0 and r.height > 0, f"{widget!r} is not shown: {r}")
        self.assertTrue(r.x >= 0 and r.y >= 0 and r.right <= size[0] and r.bottom <= size[1],
                        f"{widget!r} is cut off at {size}: {r}")

    def notified(self, app, text, title=None):
        return any(text in str(n.message) and (title is None or n.title == title) for n in app._notifications)

    @staticmethod
    def flavor_nodes(review):
        return {node.data[1].flavor.display_name: node for node in review.query_one("#flavors", Tree).root.children}

    @staticmethod
    def child(node, kind):
        return next(c for c in node.children if c.data[0] == kind)

    @staticmethod
    def table_rows(table):
        return {str(table.get_row_at(i)[0]): [str(c) for c in table.get_row_at(i)[1:]] for i in range(table.row_count)}

    @staticmethod
    def screen_text(app):
        """What the terminal shows, one line per row."""
        return [strip.text for strip in app.screen._compositor.render_strips()]

    @staticmethod
    def effect(screen, kind):
        """The restore screen's top tree node of that kind (removed, newer, links_kept, ...)."""
        return next(n for n in screen.query_one("#effects", Tree).root.children if n.data[:2] == ("effect", kind))

    @staticmethod
    def effects_text(screen):
        """Every label in the restore screen's tree, one per line."""
        lines, stack = [], [screen.query_one("#effects", Tree).root]
        while stack:
            node = stack.pop()
            lines.append(str(node.label))
            stack.extend(reversed(node.children))
        return "\n".join(lines)

    async def open_backups(self, app, pilot, review, name):
        """Expand the flavor called `name` and its Backups node; returns that node once its zips are listed."""
        node = self.flavor_nodes(review)[name]
        node.expand()
        group = self.child(node, "backups")
        group.expand()
        await settle(app, pilot)
        return group

    async def highlight(self, pilot, review, node):
        tree = review.query_one("#flavors", Tree)
        tree.focus()
        tree.move_cursor(node)
        await pilot.pause()

    # --- registration -----------------------------------------------------------------------------
    def test_registered_as_third_tool(self):
        self.assertEqual(list(TOOLS)[2], "interface-backup")
        tool = TOOLS["interface-backup"]
        self.assertEqual((tool.title, tool.section), ("Interface Backup", "interface_backup"))
        self.assertEqual(tool.flow().__name__, "InterfaceBackupFlow")

    # --- settings ---------------------------------------------------------------------------------
    async def test_first_open_asks_for_settings(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            self.assertIsInstance(app.screen, BackupSettingsScreen)
            self.assertEqual(app.screen.sub_title, "Interface Backup settings")
            app.screen.query_one("#backup_dir", Input).value = str(self.bk)
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            await settle(app, pilot)
        s = load_settings(Config(self.config_dir / "interface-backup.cfg").load())
        self.assertEqual(s.backup_dir, self.bk)

    async def test_settings_refuse_folder_inside_wtf(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            app.screen.query_one("#backup_dir", Input).value = str(self.root / "_retail_" / "WTF" / "bk")
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, BackupSettingsScreen)
            self.assertIn("WTF", app.screen.error_text)
        self.assertFalse((self.config_dir / "interface-backup.cfg").exists())

    async def test_settings_have_no_retention_inputs(self):
        """Feedback round 1: backups and journals to keep are global ([general], the `s` screen)."""
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            self.assertIsInstance(app.screen, BackupSettingsScreen)
            for box in ("#keep_backups", "#keep_journals", "#keep-backups", "#keep-journals"):
                self.assertFalse(app.screen.query(box), box)

    async def test_cancel_first_settings_still_opens_the_picker(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)

    async def test_s_opens_wow_folder_then_tool_settings(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("s")
            await pilot.pause()
            self.assertIsInstance(app.screen, SetupScreen)
            app.screen.dismiss(False)
            await pilot.pause()
            self.assertIsInstance(app.screen, BackupSettingsScreen)
            self.assertEqual(app.screen.query_one("#backup_dir", Input).value, str(self.bk))

    # --- flavor picker ----------------------------------------------------------------------------
    async def test_picker_notes_fill_in_from_a_worker(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        release = threading.Event()
        self.addCleanup(release.set)
        real = app_module.list_backups
        threads = []

        def slow_list(*args, **kwargs):
            threads.append(threading.current_thread() is threading.main_thread())
            release.wait(5)
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(app_module, "list_backups", slow_list):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_tool(app, pilot)
                options = app.screen.query_one("#flavors", OptionList)
                labels = [str(options.get_option_at_index(n).prompt) for n in range(options.option_count)]
                self.assertTrue(all("checking" in label for label in labels), labels)
                release.set()
                await settle(app, pilot)
                labels = [str(options.get_option_at_index(n).prompt) for n in range(options.option_count)]
                self.assertTrue(all("no backups yet" in label for label in labels), labels)
        self.assertEqual(threads, [False])

    async def test_single_flavor_and_choice_remembered(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot, keys=("down", "enter"))
            self.assertEqual(len(self.flavor_nodes(review)), 1)
            self.assertTrue(review.sub_title.startswith("Interface Backup · "))
            await pilot.press("f")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
        stored = load_settings(Config(self.config_dir / "interface-backup.cfg").load()).last_flavor_choice
        self.assertTrue(stored.startswith("_") and stored.endswith("_"), stored)

    # --- review ----------------------------------------------------------------------------------
    async def test_nothing_to_back_up_line_fits_the_tree_at_base(self):
        """At 120x30 a flavor with nothing to back up says why on one line the tree shows whole."""
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#flavors", Tree)
            ptr = self.flavor_nodes(review)["Retail PTR"]
            self.assertIn("nothing to back up: no Interface or WTF folder", str(ptr.label))
            # "├── ▼ " in front of the label
            self.assertLessEqual(6 + ptr.label.cell_len, tree.scrollable_content_region.width, ptr.label)

    async def test_review_lists_every_flavor_and_where_zips_go(self):
        self.save_tool_cfg(backup_dir=str(self.bk), keep_backups="5")  # stale per-tool key: ignored
        self.cfg.set("general", "keep_backups", "3", log=False)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            self.assertEqual(review.sub_title, "Interface Backup · All flavors")
            nodes = self.flavor_nodes(review)
            self.assertEqual(set(nodes), {"Retail", "Classic Era", "Anniversary", "Retail PTR"})
            self.assertIn("interface-backup", str(review.query_one("#folder-label", Static).render()))
            self.assertEqual(str(review.query_one("#keep-label", Static).render()), "newest 3 per flavor")
            self.cfg.set("general", "keep_backups", "0", log=False)  # 0 = keep all, through the global setting
            review._show_settings()
            self.assertEqual(str(review.query_one("#keep-label", Static).render()), "all backups")
            tree = review.query_one("#flavors", Tree)
            self.assertIs(review.focused, tree)
            self.assertIn("All flavors", str(tree.root.label))
            retail = nodes["Retail"]
            self.assertIn("no backups yet", str(retail.label))
            self.assertTrue(str(retail.label).startswith("✔"))  # every flavor starts ticked
            kinds = [c.data[0] for c in retail.children]
            self.assertEqual(kinds, ["part", "part", "backups"])
            self.assertRegex(str(retail.children[0].label), r"^Interface  \d+ files")
            self.assertIn("WTF  missing", str(nodes["Retail PTR"].children[1].label))
            ptr = str(nodes["Retail PTR"].label)
            self.assertIn("nothing to back up: no Interface or WTF folder", ptr)
            self.assertTrue(ptr.startswith("  Retail PTR"), ptr)  # no tick, as in the other tools
            self.assertIn("none yet", str(self.child(retail, "backups").label))
            summary = str(review.query_one("#summary", Static).render())
            self.assertIn("Selected: 3 flavors", summary)  # Retail PTR is not counted
            self.assertIn("press e to restore", summary)
            self.assertFalse(review.query_one("#btn-backup", Button).disabled)
            self.assertTrue(review.query_one("#btn-undo", Button).disabled)  # nothing restored yet
            for screen_hint in review.query(NavHint):
                self.assertIn("b back up", screen_hint.hint)
            labels = [str(b.label) for b in review.query_one("#actions").query(Button)]
            self.assertEqual(labels, ["Back up", "Restore", "Rescan", "Undo last restore"])
            kinds = {i: action_kind(review.query_one(f"#{i}", Button))
                     for i in ("btn-backup", "btn-restore", "btn-undo", "btn-rescan")}
        self.assertEqual(kinds, {"btn-backup": "create", "btn-restore": "navigate", "btn-undo": "revert",
                                 "btn-rescan": "navigate"})

    async def test_ticks_space_all_and_none(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                tree = review.query_one("#flavors", Tree)
                retail = self.flavor_nodes(review)["Retail"]
                await self.highlight(pilot, review, retail)
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(review.unchecked, {"_retail_"})
                self.assertTrue(str(retail.label).startswith("✘"))
                self.assertTrue(str(tree.root.label).startswith("◩"))
                self.assertIn("Selected: 2 flavors", review.summary_text)  # of the 3 with something to back up
                await self.highlight(pilot, review, retail.children[0])  # a part: read-only
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(review.unchecked, {"_retail_"})
                await self.highlight(pilot, review, tree.root)
                await pilot.press("space")  # partly ticked root: ticks everything
                await pilot.pause()
                self.assertEqual(review.unchecked, set())
                await pilot.press("n")
                await pilot.pause()
                self.assertTrue(str(tree.root.label).startswith("✘"))
                self.assertIn("Selected: 0 flavors", review.summary_text)
                await pilot.press("b")
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                self.assertTrue(self.notified(app, "Nothing is selected."))
                await pilot.press("a")
                await pilot.pause()
                self.assertTrue(str(tree.root.label).startswith("✔"))
                self.assertEqual(review.unchecked, set())
        toggles = [r["data"] for r in records if r["event"] == "ui.item_toggled"]
        self.assertIn({"screen": "ibackup_review", "key": "_retail_", "checked": False}, toggles)
        controls = [r["data"].get("control") for r in records if r["event"] == "ui.selection"]
        self.assertIn("select_none", controls)
        self.assertIn("select_all", controls)

    async def test_back_up_only_the_ticked_flavors(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("n")
            await self.highlight(pilot, review, self.flavor_nodes(review)["Classic Era"])
            await pilot.press("space")
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("Back up 1 flavor?", app.screen.title_text)
            self.assertIn("Classic Era", app.screen.body_text)
            self.assertNotIn("Retail", app.screen.body_text)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupResultScreen)
            self.assertEqual(app.screen.query_one("#result-table", DataTable).row_count, 1)
            await pilot.press("r")
            await settle(app, pilot)
            self.assertEqual(review.unchecked, {f.folder for f in review.flavors} - {"_classic_era_"})  # kept
        self.assertEqual([n.split("-2")[0] for n in self.zips()], ["backup-classic_era"])

    async def test_flavor_with_nothing_to_back_up_has_no_tick(self):
        """As in the organizer and the cleaner: a flavor with nothing to act on has no tick, Space there does
        nothing, and it is never in the Selected count, the confirm or the result."""
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            ptr = self.flavor_nodes(review)["Retail PTR"]
            await pilot.press("n")
            await self.highlight(pilot, review, ptr)
            await pilot.press("space")
            await pilot.pause()
            self.assertFalse(str(ptr.label).lstrip().startswith(("✔", "✘", "◩")), str(ptr.label))
            self.assertIn("Selected: 0 flavors", review.summary_text)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertTrue(self.notified(app, "Nothing is selected."))
            await pilot.press("a")
            await pilot.pause()
            self.assertIn("Selected: 3 flavors", review.summary_text)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertEqual(app.screen.title_text, "Back up 3 flavors?")  # as the Selected line says
            self.assertNotIn("Retail PTR", app.screen.body_text)
        self.assertFalse((self.bk / "interface-backup").exists())

    async def test_only_flavors_with_nothing_to_back_up(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        for folder in ("_retail_", "_classic_era_", "_anniversary_"):
            for part in ("Interface", "WTF"):
                target = self.root / folder / part
                if target.exists():
                    os.rename(target, self.root / folder / f"{part}-moved")
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            self.assertFalse(str(review.query_one("#flavors", Tree).root.label).startswith("✔"))
            self.assertTrue(review.query_one("#btn-backup", Button).disabled)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertTrue(self.notified(app, "Nothing to back up"))
        self.assertFalse((self.bk / "interface-backup").exists())

    async def test_left_and_right_move_between_panes(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#flavors", Tree)
            self.assertIs(review.focused, tree)
            await pilot.press("left")
            self.assertIn(review.focused, list(review.query_one("#actions").query(Button)))
            review.query_one("#btn-backup", Button).focus()
            await pilot.press("right")
            self.assertIs(review.focused, review.query_one("#btn-restore", Button))
            for _ in range(3):
                await pilot.press("right")  # past the last button: to the tree
            self.assertIs(review.focused, tree)
            await pilot.press("left")
            self.assertIs(review.focused, review.query_one("#btn-rescan", Button))  # the last one used

    async def test_scan_runs_in_a_worker(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        real = review_module.scan_flavors
        threads = []

        def scan(*args, **kwargs):
            threads.append(threading.current_thread() is threading.main_thread())
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(review_module, "scan_flavors", scan):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
        self.assertEqual(threads, [False])

    async def test_tools_key_returns_to_menu(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)

    # --- back up ----------------------------------------------------------------------------------
    async def test_back_up_all_flavors(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                await pilot.press("b")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIs(app.screen.focused, app.screen.query_one("#yes", Button))  # nothing is changed
                self.assertIn("Back up 3 flavors?", app.screen.title_text)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, BackupResultScreen)
                self.assertEqual(app.screen.sub_title, "Interface Backup · result")
                result_table = app.screen.query_one("#result-table", DataTable)
                rows = {str(result_table.get_row_at(i)[0]) for i in range(result_table.row_count)}
                self.assertEqual(rows, {"Retail", "Classic Era", "Anniversary"})  # Retail PTR has no tick
                summary = self.table_rows(app.screen.query_one("#result-summary", DataTable))
                self.assertEqual(summary["Backed up"], ["3 of 3 flavors"])
                self.assertNotIn("Skipped", summary)
                self.assertFalse(app.screen.query_one("#result-summary", DataTable).can_focus)
                self.assertFalse(app.busy)
                await pilot.press("r")
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                retail = self.flavor_nodes(review)["Retail"]
                self.assertIn("1 backup, last", str(retail.label))
                self.assertIn("Backups (1)", str(self.child(retail, "backups").label))
        zips = self.zips()
        self.assertTrue(any(n.startswith("backup-retail-") for n in zips))
        self.assertFalse(any(n.startswith("backup-ptr-") for n in zips))  # neither part: skipped
        with zipfile.ZipFile(self.bk / "interface-backup" / next(n for n in zips if "retail" in n)) as zf:
            self.assertIn("WTF/Config.wtf", zf.namelist())
        selections = [(r["data"].get("screen"), r["data"].get("control"), r["data"].get("value"))
                      for r in records if r["event"] == "ui.selection"]
        self.assertIn(("ibackup_review", "back_up", True), selections)
        self.assertIn(("confirm", "back_up_confirm", True), selections)
        self.assertIn(("ibackup_result", "next", "review"), selections)
        self.assertTrue(activity.wait_idle(0))

    async def test_link_only_flavor_has_no_tick_and_says_why(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        wtf = self.root / "_anniversary_" / "WTF"
        elsewhere = self.tmp / "synced-wtf"
        os.rename(wtf, elsewhere)
        try:
            os.symlink(elsewhere, wtf, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted here")
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                anniversary = str(self.flavor_nodes(review)["Anniversary"].label)
                self.assertIn("nothing to back up: WTF is a link (not followed)", anniversary)  # the reason, no tick
                self.assertTrue(anniversary.startswith("  Anniversary"), anniversary)
                await pilot.press("b")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIn("Back up 2 flavors?", app.screen.title_text)
                self.assertNotIn("Anniversary", str(app.screen.body_text))
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, BackupResultScreen)
                table = app.screen.query_one("#result-table", DataTable)
                rows = {str(table.get_row_at(i)[0]): [str(c) for c in table.get_row_at(i)]
                        for i in range(table.row_count)}
                self.assertNotIn("Anniversary", rows)
                self.assertEqual(rows["Retail"][1], "Backed up")
        self.assertFalse(any(r["event"] == "ibackup.backup_skipped" for r in records))
        self.assertFalse(any("anniversary" in n for n in self.zips()))

    async def test_progress_reaches_the_screen_throttled(self):
        # Per-file reports go to the UI thread only on a stage change, at a stage's end, or once per interval:
        # forwarding every file of a big Interface folder made a backup through the UI ~13x slower than the logic.
        self.save_tool_cfg(backup_dir=str(self.bk))
        addons = self.root / "_retail_" / "Interface" / "AddOns" / "Big"
        addons.mkdir(parents=True)
        for i in range(300):
            (addons / f"f{i:03}.lua").write_bytes(b"x")
        shown = []
        real = BackupProgressScreen.update_progress

        def record(screen, *args):
            shown.append(args)
            real(screen, *args)

        app = self.make_app()
        with patch.object(review_module, "PROGRESS_INTERVAL", 3600.0, create=True), \
                patch.object(BackupProgressScreen, "update_progress", record):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
        self.assertTrue(any(z.startswith("backup-retail-") for z in self.zips()))
        self.assertLess(len(shown), 40, shown[:10])  # 300+ files zipped and verified per pass before the fix
        stages = [args[0] for args in shown]
        for stage in ("backup", "verify", "prune"):
            self.assertIn(stage, stages)
        retail_total = max(args[2] for args in shown if args[0] == "backup")
        self.assertIn(("backup", retail_total), [(a[0], a[1]) for a in shown])  # each stage's end is shown

    async def test_decline_confirm_writes_nothing(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupReviewScreen)
        self.assertFalse((self.bk / "interface-backup").exists())

    async def test_wow_running_is_an_alert(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app(running=["Wow.exe"])
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertTrue(any("Wow.exe" in alert for alert in app.screen.alerts))

    async def test_wow_check_runs_in_a_worker(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        threads = []

        def check():
            threads.append(threading.current_thread() is threading.main_thread())
            return []

        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                          tool_options={"interface-backup": {"wow_check": check}})
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
        self.assertEqual(threads, [False])

    async def test_folder_edited_into_wtf_refuses_the_backup(self):
        self.save_tool_cfg(backup_dir=str(self.root / "_retail_" / "WTF" / "bk"))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
        self.assertFalse((self.root / "_retail_" / "WTF" / "bk").exists())

    async def test_ticks_are_frozen_while_the_check_runs(self):
        """As in every review screen: a / n / Space change nothing while the running-programs check runs."""
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            review.query_one(Tree).focus()
            review._checking = True
            await pilot.press("n")
            self.assertEqual(review.unchecked, set())
            review._checking = False
            await pilot.press("n")
            self.assertTrue(review.unchecked)

    async def test_busy_while_backing_up_guards_leaving(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        release = threading.Event()
        self.addCleanup(release.set)
        real = review_module.back_up_all
        seen = []

        def slow(*args, **kwargs):
            seen.append(activity.wait_idle(0))
            release.wait(5)
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(review_module, "back_up_all", slow):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                await pilot.press("b")
                await settle(app, pilot)
                await pilot.press("y")
                await pilot.pause()
                self.assertTrue(app.busy)
                self.assertIsInstance(app.screen, BackupProgressScreen)
                review.action_leave("tools")
                review.action_back_up()
                review.action_rescan()
                await pilot.pause()
                self.assertIsInstance(app.screen, BackupProgressScreen)
                self.assertTrue(review.query_one("#btn-backup", Button).disabled)
                release.set()
                await settle(app, pilot)
                self.assertIsInstance(app.screen, BackupResultScreen)
                self.assertFalse(app.busy)
        self.assertEqual(seen, [False])
        self.assertEqual(len(self.zips()), 3)

    async def test_result_screen_leads_back_to_flavors(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupResultScreen)
            await pilot.press("f")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            options = app.screen.query_one("#flavors", OptionList)
            labels = [str(options.get_option_at_index(n).prompt) for n in range(options.option_count)]
            self.assertIn("3 backups", labels[0])

    async def test_failed_job_is_reported_and_clears_busy(self):
        self.save_tool_cfg(backup_dir=str(self.bk))

        def boom(*args, **kwargs):
            raise OSError("disk gone")

        app = self.make_app()
        with patch.object(review_module, "back_up_all", boom):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                await pilot.press("b")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                self.assertFalse(app.busy)
                self.assertFalse(review.query_one("#btn-backup", Button).disabled)
                self.assertTrue(self.notified(app, "disk gone", title="Stopped"))

    # --- restore and undo -------------------------------------------------------------------------
    async def make_backup(self, app, pilot):
        await pilot.press("b")
        await settle(app, pilot)
        await pilot.press("y")
        await settle(app, pilot)
        self.assertIsInstance(app.screen, BackupResultScreen)

    async def open_restore(self, app, pilot, name="Retail", key="e"):
        """From the review: open the Backups of the flavor called `name`, highlight its newest backup, press `key`
        (e or Enter)."""
        review = app.screen
        self.assertIsInstance(review, BackupReviewScreen)
        group = await self.open_backups(app, pilot, review, name)
        await self.highlight(pilot, review, group.children[0])
        await pilot.press(key)
        await settle(app, pilot)
        self.assertIsInstance(app.screen, RestoreScreen)
        return app.screen

    async def test_restore_tree_expands_and_collapses_all(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        extra = self.root / "_retail_" / "Interface" / "AddOns" / "WeakAuras" / "wa.lua"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            extra.parent.mkdir(parents=True)
            extra.write_text("wa", encoding="utf-8")
            screen = await self.open_restore(app, pilot)
            self.assertIn("x expand all · c collapse all", screen.query_one(NavHint).hint)
            tree = screen.query_one("#effects", Tree)
            tree.focus()
            await pilot.press("x")
            await settle(app, pilot)
            group = self.effect(screen, "removed").children[0]
            self.assertTrue(group.is_expanded)
            self.assertEqual([str(c.label) for c in group.children], ["wa.lua"])  # loaded by expand-all
            await pilot.press("c")
            await settle(app, pilot)
            self.assertIs(app.screen, screen)
            expanded, stack = [], [tree.root]
            while stack:
                node = stack.pop()
                if node.is_expanded:
                    expanded.append(node)
                stack.extend(node.children)
            self.assertEqual(expanded, [tree.root])

    async def test_restore_with_warnings_then_undo(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        retail = self.root / "_retail_"
        extra = retail / "Interface" / "AddOns" / "WeakAuras" / "wa.lua"
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                extra.parent.mkdir(parents=True)
                extra.write_text("wa", encoding="utf-8")
                screen = await self.open_restore(app, pilot)
                self.assertEqual(screen.sub_title, "Interface Backup · restore")
                info = str(screen.query_one("#backup-info", Static).render())
                self.assertIsNone(re.search(r"\d{4}-\d\d-\d\dT\d\d", info), info)  # never the raw ISO stamp
                removed = self.effect(screen, "removed")
                self.assertIn("Will be removed (1 file)", str(removed.label))
                self.assertTrue(removed.is_expanded)
                group = removed.children[0]
                self.assertEqual(str(group.label), "WeakAuras  Interface/AddOns · 1 file")  # the name first, then the parent
                self.assertFalse(group.children)  # files load on expand
                group.expand()
                await settle(app, pilot)
                self.assertEqual([str(c.label) for c in group.children], ["wa.lua"])
                self.assertIn("1 removed · 0 newer · needs", screen.summary_text)
                self.assertTrue(screen.summary_text.startswith("Restore Interface and WTF of Retail from "))
                self.assertFalse(screen.query_one("#btn-restore", Button).disabled)
                await pilot.press("o")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertFalse(app.screen.default_yes)
                self.assertIs(app.screen.focused, app.screen.query_one("#no", Button))
                self.assertTrue(any("WeakAuras" in alert for alert in app.screen.alerts))
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, RestoreResultScreen)
                self.assertEqual(app.screen.sub_title, "Interface Backup · restore result")
                self.assertTrue(app.screen.result.ok)
                self.assertIsNotNone(app.screen.result.safety_zip)
                self.assertEqual(action_kind(app.screen.query_one("#undo", Button)), "revert")
                self.assertIn("z", app.screen.active_bindings)
                self.assertFalse(app.busy)
                self.assertFalse(extra.exists())
                await pilot.press("z")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertFalse(app.screen.default_yes)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, RestoreResultScreen)
                self.assertTrue(app.screen.result.undo)
                self.assertEqual(app.screen.sub_title, "Interface Backup · undo result")
                self.assertFalse(app.screen.query("#undo"))
                self.assertNotIn("z", app.screen.active_bindings)  # no Undo here: not in the footer either
                table = app.screen.query_one("#result-table", DataTable)
                self.assertEqual([str(table.get_row_at(i)[0]) for i in range(table.row_count)],
                                 ["Interface", "WTF"])  # the restore result's order, not the undo's
                await pilot.press("escape")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, BackupReviewScreen)
                self.assertTrue(app.screen.query_one("#btn-undo", Button).disabled)  # undone: nothing left
        self.assertEqual(extra.read_text(encoding="utf-8"), "wa")
        selections = [(r["data"].get("screen"), r["data"].get("control"), r["data"].get("value"))
                      for r in records if r["event"] == "ui.selection"]
        self.assertTrue(any(s[:2] == ("ibackup_review", "restore") and s[2].startswith("backup-retail-")
                            for s in selections), selections)
        self.assertIn(("ibackup_restore", "restore", ["Interface", "WTF"]), selections)
        self.assertIn(("confirm", "restore_confirm", True), selections)
        self.assertIn(("ibackup_restore_result", "next", "undo"), selections)
        self.assertIn(("confirm", "undo_confirm", True), selections)
        events = [r["event"] for r in records]
        self.assertIn("ibackup.restore_completed", events)
        self.assertIn("ibackup.undo_completed", events)
        self.assertTrue(activity.wait_idle(0))

    async def test_restore_wtf_only(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        retail = self.root / "_retail_"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            (retail / "Interface" / "keep.txt").write_text("k", encoding="utf-8")
            (retail / "WTF" / "Config.wtf").write_bytes(b"mine")
            screen = await self.open_restore(app, pilot)
            self.assertIn("keep.txt  Interface", self.effects_text(screen))
            screen.query_one("#part-Interface", Checkbox).value = False
            await settle(app, pilot)
            self.assertNotIn("keep.txt", self.effects_text(screen))
            self.assertIn("Restore WTF of Retail", screen.summary_text)
            self.assertEqual(screen.plan.parts, ("WTF",))
            await pilot.press("o")
            await settle(app, pilot)
            self.assertIn("Replace WTF of", app.screen.title_text)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            self.assertEqual([p.part for p in app.screen.result.parts], ["WTF"])
        self.assertTrue((retail / "Interface" / "keep.txt").exists())
        self.assertEqual((retail / "WTF" / "Config.wtf").read_bytes(), b"SET a 1\n")

    async def test_no_part_ticked_disables_restore(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            screen = await self.open_restore(app, pilot)
            for part in ("Interface", "WTF"):
                screen.query_one(f"#part-{part}", Checkbox).value = False
            await settle(app, pilot)
            self.assertTrue(screen.query_one("#btn-restore", Button).disabled)
            self.assertIsNone(screen.plan)
            await pilot.press("o")
            await settle(app, pilot)
            self.assertIs(app.screen, screen)

    async def test_part_missing_from_backup_cannot_be_ticked(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            screen = await self.open_restore(app, pilot, name="Anniversary")  # WTF only
            box = screen.query_one("#part-Interface", Checkbox)
            self.assertTrue(box.disabled)
            self.assertFalse(box.value)
            self.assertFalse(screen.query_one("#part-WTF", Checkbox).disabled)
            self.assertEqual(screen.plan.parts, ("WTF",))

    async def test_leftover_blocks_the_restore(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            (self.root / "_retail_" / "Interface.restoring").mkdir()
            screen = await self.open_restore(app, pilot)
            self.assertTrue(screen.query_one("#btn-restore", Button).disabled)
            self.assertTrue(screen.query_one("#part-WTF", Checkbox).disabled)
            # Blocked: neither box reads as "will be restored", and focus is on something that acts.
            self.assertEqual([screen.query_one(f"#part-{p}", Checkbox).value for p in ("Interface", "WTF")],
                             [False, False])
            self.assertIs(screen.focused, screen.query_one("#btn-back", Button))
            self.assertIn("interrupted restore", self.effects_text(screen))
            self.assertIn("interrupted restore", screen.summary_text)
            await pilot.press("o")
            await settle(app, pilot)
            self.assertIs(app.screen, screen)

    async def test_restore_without_a_highlighted_backup_says_how(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                await pilot.press("e")  # the cursor is on the root
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                self.assertTrue(self.notified(app, "highlight a backup", title="No backup highlighted"))
                review.query_one("#btn-restore", Button).press()
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                await self.highlight(pilot, review, self.child(self.flavor_nodes(review)["Retail"], "backups"))
                await pilot.press("enter")  # "Backups (0)": nothing to open
                await settle(app, pilot)
                self.assertIs(app.screen, review)
        selections = [(r["data"].get("control"), r["data"].get("value")) for r in records
                      if r["event"] == "ui.selection"]
        self.assertIn(("restore", None), selections)

    async def test_restore_screen_back_and_decline_change_nothing(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        extra = self.root / "_retail_" / "Interface" / "new.lua"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            extra.write_text("x", encoding="utf-8")
            await self.open_restore(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupReviewScreen)
            await self.open_restore(app, pilot, key="enter")  # Enter on a backup node opens it too
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupReviewScreen)
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupReviewScreen)
        self.assertTrue(extra.exists())
        self.assertFalse(list((self.bk / "interface-backup").glob("pre-restore-*.zip")))

    async def test_list_and_plan_built_in_workers(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        threads = []

        def spy(real):
            def call(*args, **kwargs):
                threads.append((real.__name__, threading.current_thread() is threading.main_thread()))
                return real(*args, **kwargs)
            return call

        app = self.make_app()
        with patch.object(review_module, "list_backups", spy(review_module.list_backups)), \
                patch.object(restore_module, "open_backup", spy(restore_module.open_backup)), \
                patch.object(restore_module, "scan_flavor", spy(restore_module.scan_flavor)), \
                patch.object(restore_module, "plan_restore", spy(restore_module.plan_restore)):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                await self.open_restore(app, pilot)
        self.assertEqual({name for name, _ in threads}, {"list_backups", "open_backup", "scan_flavor", "plan_restore"})
        self.assertFalse(any(on_main for _, on_main in threads), threads)

    async def test_wow_running_is_an_alert_on_restore(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app(running=["Wow.exe"])
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertTrue(any("Wow.exe" in alert for alert in app.screen.alerts))
            self.assertFalse(app.screen.default_yes)

    async def test_restore_confirm_warns_when_the_backup_drive_is_short(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        bk = str(self.bk)

        class Usage:
            def __init__(self, free):
                self.free = free

        def disk_usage(path):
            # The backup drive is nearly full; the WoW drive has room.
            return Usage(5 if str(path).startswith(bk) else 10 ** 12)

        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                          tool_options={"interface-backup": {"wow_check": list, "disk_usage": disk_usage}})
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            space = [a for a in app.screen.alerts if "short of space" in a]
            self.assertEqual(len(space), 1, app.screen.alerts)
            self.assertIn("safety backup: 5 B free", space[0])
            self.assertFalse(any("Low disk space" in a for a in app.screen.alerts))  # the WoW drive is fine

    async def test_refused_restore_is_notified(self):
        self.save_tool_cfg(backup_dir=str(self.bk))

        def refuse(*args, **kwargs):
            raise RestoreError("the backup did not verify, nothing was changed")

        app = self.make_app()
        with patch.object(review_module, "restore", refuse):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                await self.open_restore(app, pilot)
                await pilot.press("o")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                self.assertFalse(app.busy)
                self.assertTrue(self.notified(app, "did not verify", title="Nothing was changed"))

    async def test_stopped_restore_shows_what_was_done(self):
        self.save_tool_cfg(backup_dir=str(self.bk))

        def stop(plan, **kwargs):
            # A real stopped restore always has a journal: Undo is hidden only because no part changed.
            result = RestoreResult(plan.flavor, plan.contents.path, [PartOutcome("Interface", "rolled_back", "locked")],
                                   journal_path=self.tmp / "j.jsonl")
            raise RestoreStopped("KeyboardInterrupt", result)

        app = self.make_app()
        with patch.object(review_module, "restore", stop):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                await self.open_restore(app, pilot)
                await pilot.press("o")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, RestoreResultScreen)
                self.assertFalse(app.busy)
                self.assertFalse(app.screen.query("#undo"))  # nothing changed: nothing to undo
                self.assertFalse(self.notified(app, "Undo (z)"))
                await pilot.press("z")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, RestoreResultScreen)
                await pilot.press("t")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ToolMenuScreen)

    async def test_undo_from_review_starts_on_no(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        extra = self.root / "_retail_" / "WTF" / "new.wtf"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            extra.write_text("x", encoding="utf-8")
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertFalse(extra.exists())
            await pilot.press("r")
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, BackupReviewScreen)
            self.assertFalse(review.query_one("#btn-undo", Button).disabled)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIs(app.screen.focused, app.screen.query_one("#no", Button))
            self.assertIn("Undo the restore from", app.screen.title_text)
            await pilot.press("enter")  # No
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertFalse(extra.exists())
            await pilot.press("z")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
        self.assertEqual(extra.read_text(encoding="utf-8"), "x")

    async def test_stopped_restore_that_replaced_a_part_offers_undo(self):
        self.save_tool_cfg(backup_dir=str(self.bk))

        def stop(plan, **kwargs):
            result = RestoreResult(plan.flavor, plan.contents.path,
                                   [PartOutcome("Interface", "restored"), PartOutcome("WTF", "rolled_back", "locked")],
                                   journal_path=self.tmp / "j.jsonl")
            raise RestoreStopped("KeyboardInterrupt", result)

        app = self.make_app()
        with patch.object(review_module, "restore", stop):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                await self.open_restore(app, pilot)
                await pilot.press("o")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, RestoreResultScreen)
                self.assertTrue(app.screen.query("#undo"))
                self.assertIn("z", app.screen.active_bindings)
                self.assertTrue(self.notified(app, "Undo (z) puts back what was replaced", title="Restore stopped"))

    async def test_stopped_restore_whose_swap_was_not_recorded_offers_no_undo(self):
        self.save_tool_cfg(backup_dir=str(self.bk))

        def stop(plan, **kwargs):
            # SwapNotRecorded: the swap stands, but the journal has no `replaced` entry, so Undo cannot put it back.
            reason = "Interface was replaced, but the restore journal could not record it (disk full), so Undo cannot"
            result = RestoreResult(plan.flavor, plan.contents.path, [PartOutcome("Interface", "failed", reason)],
                                   journal_path=self.tmp / "j.jsonl")
            raise RestoreStopped(reason, result)

        app = self.make_app()
        with patch.object(review_module, "restore", stop):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                await self.open_restore(app, pilot)
                await pilot.press("o")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, RestoreResultScreen)
                self.assertFalse(app.screen.query("#undo"))
                self.assertNotIn("z", app.screen.active_bindings)
                self.assertTrue(self.notified(app, "Undo cannot", title="Restore stopped"))
                self.assertFalse(self.notified(app, "Undo (z) puts back"))

    async def test_wow_running_is_an_alert_on_undo(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        extra = self.root / "_retail_" / "WTF" / "new.wtf"
        app = self.make_app(running=["Wow.exe"])
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            extra.write_text("x", encoding="utf-8")
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("y")  # the restore goes ahead despite the alert
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            self.assertFalse(extra.exists())
            await pilot.press("r")
            await settle(app, pilot)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("Undo the restore from", app.screen.title_text)
            self.assertTrue(any("Wow.exe" in alert for alert in app.screen.alerts))
            self.assertIs(app.screen.focused, app.screen.query_one("#no", Button))
            await pilot.press("y")  # warn and allow
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            self.assertTrue(app.screen.result.undo)
            self.assertTrue(app.screen.result.ok)
        self.assertEqual(extra.read_text(encoding="utf-8"), "x")

    async def test_undo_wow_check_uses_the_journals_flavor(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        asked = []

        def check_for(flavors):
            asked.append([getattr(f, "folder", f) for f in flavors])
            return lambda: ["WowClassic.exe"]

        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                          tool_options={"interface-backup": {"wow_check": None}})
        with patch.object(review_module, "wow_check_for", check_for):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                await self.open_restore(app, pilot)
                await pilot.press("o")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                asked.clear()
                await pilot.press("z")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertTrue(any("WowClassic.exe" in alert for alert in app.screen.alerts))
        self.assertEqual(asked, [["_retail_"]])  # the journal's flavor, not every flavor shown

    # --- the default terminal size (BASE, 120x30) ----------------------------------------------------
    async def test_review_actions_fit_at_base(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            buttons = list(review.query_one("#actions").query(Button))
            self.assertEqual(len(buttons), 4)
            for button in buttons:
                self.assert_on_screen(button)
            await self.make_backup(app, pilot)
            for button in app.screen.query(Button):  # the backup result screen
                self.assert_on_screen(button)
            await pilot.press("r")
            await settle(app, pilot)
            for button in review.query_one("#actions").query(Button):
                self.assert_on_screen(button)

    async def test_review_tree_shows_links_and_leftovers_at_base(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        (self.root / "_classic_era_" / "Interface.restoring").mkdir()
        try:
            os.symlink(self.tmp, self.root / "_retail_" / "Interface" / "AddOns" / "Linked", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            nodes = self.flavor_nodes(review)
            leftover = self.child(nodes["Classic Era"], "leftover")
            self.assertIn("Restore is blocked for this flavor", str(leftover.label))
            links = self.child(nodes["Retail"], "links")
            self.assertIn("Links (1)", str(links.label))
            self.assertIn("not backed up; a restore keeps them", str(links.label))
            self.assertFalse(links.children)  # paths load on expand
            links.expand()
            await settle(app, pilot)
            self.assertEqual([str(c.label) for c in links.children], ["Interface/AddOns/Linked"])
            summary = review.query_one("#summary", Static)
            text = str(summary.render())
            self.assertIn("1 link not backed up", text)
            self.assertIn("Restore blocked for Classic Era", text)
            self.assert_on_screen(summary)
            for button in review.query_one("#actions").query(Button):
                self.assert_on_screen(button)
            self.assert_on_screen(review.query_one("#flavors", Tree))

    async def test_scan_warnings_node(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        real = review_module.scan_flavors

        def scan(*args, **kwargs):
            scans = real(*args, **kwargs)
            scans[0].parts["Interface"].errors += [f"X{i}: denied" for i in range(3)]
            return scans

        app = self.make_app()
        with patch.object(review_module, "scan_flavors", scan):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                first = review.query_one("#flavors", Tree).root.children[0]
                node = self.child(first, "warnings")
                self.assertIn("Scan warnings (3)", str(node.label))
                node.expand()
                await settle(app, pilot)
                self.assertEqual([str(c.label) for c in node.children], ["X0: denied", "X1: denied", "X2: denied"])
                self.assertIn("3 scan warnings", review.summary_text)

    async def test_restore_screens_fit_at_base(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            screen = await self.open_restore(app, pilot)
            for selector in ("#part-Interface", "#part-WTF", "#btn-restore", "#btn-back", "#effects", "#summary",
                             "NavHint"):
                self.assert_on_screen(screen.query_one(selector))
            hint = screen.query_one(NavHint).hint  # Space opens the effects tree's nodes here too
            self.assertTrue(hint.startswith("↑↓/Tab move · ←→ panes and buttons · Space tick or open · "), hint)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            self.assertTrue(app.screen.can_undo)
            buttons = list(app.screen.query(Button))
            self.assertEqual(len(buttons), 5)
            for button in buttons:
                self.assert_on_screen(button)
            self.assert_on_screen(app.screen.query_one("#result-table", DataTable))
            hint = app.screen.query_one(NavHint).hint
            self.assertTrue(hint.startswith("↑↓/Tab move · ←→ buttons"), hint)  # as on the organizer's result
            summary = self.table_rows(app.screen.query_one("#result-summary", DataTable))
            self.assertEqual(summary["Restore"], ["finished"])
            self.assertIn("Safety backup", summary)
            self.assertIn("Journal", summary)
            # The zip names are whole on screen (a whole path can be cut, with no way to scroll it).
            result, rows = app.screen.result, self.screen_text(app)
            table = app.screen.query_one("#result-summary", DataTable).region
            shown = "\n".join(row[table.x:table.right] for row in rows[table.y:table.bottom])
            for name in (result.safety_zip.name, result.backup.name, result.journal_path.name):
                self.assertIn(name, shown)

    async def test_restore_tree_names_groups_at_base(self):
        """Each group's row starts with the name that tells it apart (not the shared Interface/AddOns prefix), the
        root is whole and the left pane's hint is not clipped."""
        self.save_tool_cfg(backup_dir=str(self.bk))
        addons = self.root / "_retail_" / "Interface" / "AddOns"
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            for i in range(12):
                (addons / f"New{i}").mkdir(parents=True)
                (addons / f"New{i}" / "a.lua").write_text("a", encoding="utf-8")
            (addons / "WeakAuras").mkdir(parents=True)
            for name in ("a.lua", "b.lua"):
                (addons / "WeakAuras" / name).write_text("w", encoding="utf-8")
            screen = await self.open_restore(app, pilot)
            removed = self.effect(screen, "removed")
            labels = [str(c.label) for c in removed.children]
            self.assertEqual(labels[:4], ["WeakAuras  Interface/AddOns · 2 files", "New0  Interface/AddOns · 1 file",
                                          "New1  Interface/AddOns · 1 file", "New2  Interface/AddOns · 1 file"])
            tree = screen.query_one("#effects", Tree)
            shown = "\n".join(tree.render_line(y).text for y in range(tree.scrollable_content_region.height))
            self.assertIn(screen.flavor.display_name + " · " + screen.info.when, shown)  # the root, not cut
            for name in ("WeakAuras", "New0", "New1", "New2"):
                self.assertRegex(shown, rf"\b{name}\b", shown)
            filters, hint = screen.query_one("#filters"), screen.query_one(NavHint)
            self.assertLessEqual(hint.region.bottom, filters.content_region.bottom, hint.region)  # not clipped
            self.assertIn("Will be removed (14 files)", shown)
            box = screen.query_one("#part-Interface", Checkbox)
            box.label = "Interface (link: restore by hand)"  # the longest label a box gets
            await settle(app, pilot)
            self.assertEqual(box.region.height, 1, box.region)  # compact, as in every left pane: one line, not wrapped
            self.assertLessEqual(box.region.right, filters.content_region.right)

    async def test_restore_tree_lists_links_and_unreadable_on_expand(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        real = restore_module.plan_restore

        def plan(*args, **kwargs):
            p = real(*args, **kwargs)
            p.links_kept.append(("Interface", "AddOns/Dev"))
            p.links_removed.append(("WTF", "Account"))
            p.unreadable.append("/wow/Interface/X: denied")
            return p

        app = self.make_app()
        with patch.object(restore_module, "plan_restore", plan):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                screen = await self.open_restore(app, pilot)
                expected = {"links_kept": ("Links kept (1)", "Interface/AddOns/Dev"),
                            "links_removed": ("Links replaced (1)", "WTF/Account"),
                            "unreadable": ("Could not be read (1)", "/wow/Interface/X: denied")}
                for kind, (title, child) in expected.items():
                    node = self.effect(screen, kind)
                    self.assertIn(title, str(node.label))
                    self.assertFalse(node.children)
                    node.expand()
                    await settle(app, pilot)
                    self.assertEqual([str(c.label) for c in node.children], [child])
                self.assertNotIn("Nothing on disk would be lost", self.effects_text(screen))

    async def test_restore_notes_fit_the_tree_at_base(self):
        """At 120x30 the restore tree's note rows (nothing lost, low disk space) show whole: no sideways scroll."""
        self.save_tool_cfg(backup_dir=str(self.bk))
        bk = str(self.bk)

        class Usage:
            def __init__(self, free):
                self.free = free

        def disk_usage(path):  # the WoW drive is nearly full, with sizes as wide as they get
            return Usage(10 ** 12 if str(path).startswith(bk) else 123_400_000)

        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                          tool_options={"interface-backup": {"wow_check": list, "disk_usage": disk_usage}})
        async with app.run_test(size=BASE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            screen = await self.open_restore(app, pilot)
            tree = screen.query_one("#effects", Tree)
            notes = [str(n.label) for n in tree.root.children if n.data == ("note",)]
            self.assertIn("Nothing on disk would be lost  everything is in the backup", notes)
            self.assertEqual(tree.max_scroll_x, 0, notes)
            screen.plan.free_bytes, screen.plan.bytes_needed = 123_400_000, 999_900_000_000  # low on space
            screen._show_plan(screen.plan)
            await settle(app, pilot)
            notes = [str(n.label) for n in tree.root.children if n.data == ("note",)]
            self.assertTrue(any("Low disk space" in n for n in notes), notes)
            self.assertEqual(tree.max_scroll_x, 0, notes)

    async def test_restore_screen_two_panes_and_nothing_lost(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            screen = await self.open_restore(app, pilot)
            self.assertEqual(action_kind(screen.query_one("#btn-restore", Button)), "overwrite")
            self.assertEqual(action_kind(screen.query_one("#btn-back", Button)), "cancel")
            info = str(screen.query_one("#backup-info", Static).render())
            self.assertIn("Retail", info)
            self.assertIn("Interface, WTF", info)
            nodes = screen.query_one("#effects", Tree).root.children
            self.assertEqual(len(nodes), 1)
            self.assertIn("Nothing on disk would be lost", str(nodes[0].label))
            self.assertIn("0 removed · 0 newer", screen.summary_text)
            first = screen.query_one("#part-Interface", Checkbox)
            self.assertIs(screen.focused, first)
            await pilot.press("right")
            self.assertIs(screen.focused, screen.query_one("#effects", Tree))
            await pilot.press("left")
            self.assertIs(screen.focused, first)
            screen.query_one("#btn-back", Button).focus()
            await pilot.press("right")  # past the last button: to the tree
            self.assertIs(screen.focused, screen.query_one("#effects", Tree))
            await pilot.press("left")
            self.assertIs(screen.focused, screen.query_one("#btn-back", Button))  # back where it was
            for part in ("Interface", "WTF"):
                screen.query_one(f"#part-{part}", Checkbox).value = False
            await settle(app, pilot)
            self.assertIn("Tick Interface, WTF or both", self.effects_text(screen))
            self.assertIn("Nothing is ticked", screen.summary_text)

    async def test_restore_confirm_fits_at_base_with_long_warnings(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        retail = self.root / "_retail_"
        app = self.make_app(running=["Wow.exe"])
        async with app.run_test(size=BASE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            for n in range(20):
                path = retail / "Interface" / "AddOns" / f"Added{n:02}" / "a.lua"
                path.parent.mkdir(parents=True)
                path.write_text("x", encoding="utf-8")
            later = time.time() + 3600
            for path in (retail / "WTF").rglob("*"):
                if path.is_file():
                    path.write_bytes(path.read_bytes() + b"\n-- changed\n")
                    os.utime(path, (later, later))
            screen = await self.open_restore(app, pilot)
            self.assertEqual(len(self.effect(screen, "removed").children), 20)  # the full list, a group per folder
            self.assertIn("Newer now than in the backup", str(self.effect(screen, "newer").label))
            await pilot.press("o")
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertTrue(any(a.startswith("Will be removed: 20 files") for a in confirm.alerts), confirm.alerts)
            self.assertTrue(any(a.startswith("Newer now than in the backup") for a in confirm.alerts), confirm.alerts)
            self.assertTrue(any("Wow.exe" in a for a in confirm.alerts))
            self.assert_on_screen(confirm.query_one("#confirm-title"))
            self.assert_on_screen(confirm.query_one("#yes", Button))
            self.assert_on_screen(confirm.query_one("#no", Button))
            self.assertIs(confirm.focused, confirm.query_one("#no", Button))

    async def test_settings_labels_wrap_at_base(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_tool(app, pilot)
            screen = app.screen
            self.assertIsInstance(screen, BackupSettingsScreen)
            for label in screen.query("Label"):
                self.assertLessEqual(label.region.right, BASE[0])
                text = str(label.render())
                self.assertGreaterEqual(label.region.height * label.region.width, len(text), text)
            destination = str(screen.query_one("#destination", Static).render())
            self.assertIn(str(Path("World of Warcraft") / "wow-tools" / "interface-backup"), destination)
            screen.query_one("#backup_dir", Input).value = str(self.bk)
            await pilot.pause()
            self.assertIn(str(self.bk / "interface-backup"), str(screen.query_one("#destination", Static).render()))

    # --- the Backups nodes ----------------------------------------------------------------------------
    async def test_restore_from_backup_result_shows_the_newest_backup(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("e")  # Restore straight from the backup result: rescans, then shows the backups
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            nodes = self.flavor_nodes(review)
            opened = {name for name, node in nodes.items() if self.child(node, "backups").is_expanded}
            self.assertEqual(opened, {"Retail", "Classic Era", "Anniversary"})
            tree = review.query_one("#flavors", Tree)
            self.assertIs(review.focused, tree)
            self.assertEqual(tree.cursor_node.data[0], "backup")
            self.assertIs(review.highlighted_backup(), tree.cursor_node.data[1])
            await pilot.press("e")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreScreen)

    async def test_restore_from_backup_result_goes_to_the_backup_just_made(self):
        """Every flavor already has a backup; a new one of a later flavor only: Restore (e) on its result puts the
        cursor on that new zip, not on the first flavor's older one."""
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await self.make_backup(app, pilot)  # Anniversary, Classic Era and Retail
            await pilot.press("r")
            await settle(app, pilot)
            await pilot.press("n")
            await self.highlight(pilot, review, self.flavor_nodes(review)["Classic Era"])
            await pilot.press("space")
            await self.make_backup(app, pilot)
            made = next(o.path for o in app.screen.outcomes if o.kind == "created")
            await pilot.press("e")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            first = review.query_one("#flavors", Tree).root.children[0].data[1].flavor.short_name
            self.assertNotEqual(first, "classic_era")  # else this test proves nothing
            info = review.highlighted_backup()
            self.assertIsNotNone(info)
            self.assertEqual(info.flavor_short, "classic_era")
            self.assertEqual(info.path, made)

    async def test_backup_and_its_safety_zip_differ_at_base(self):
        """A backup and the safety zip of a restore from it are seconds apart: at BASE each tree line shows the
        kind and the whole date and time, and the bottom line names the highlighted one in full."""
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            await pilot.press("r")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            retail = self.flavor_nodes(review)["Retail"]
            self.assertIn("1 backup, last", str(retail.label))
            group = self.child(retail, "backups")
            self.assertIn("Backups (1 + 1 safety)", str(group.label))  # counted as on the flavor's line
            group = await self.open_backups(app, pilot, review, "Retail")
            self.assertEqual(len(group.children), 2)
            await self.highlight(pilot, review, group.children[-1])
            await settle(app, pilot)
            tree = review.query_one("#flavors", Tree)
            region = tree.region
            rows = self.screen_text(app)
            visible = []
            for node in group.children:
                line = node.line - tree.scroll_offset.y
                self.assertTrue(0 <= line < region.height, f"{node.label} is scrolled out of view")
                visible.append(rows[region.y + line][region.x:region.right].rstrip())
            kinds = [v.split("─ ")[-1].split(" ")[0] for v in visible]
            self.assertEqual(sorted(kinds), ["backup", "safety"], visible)
            self.assertEqual(len(set(visible)), 2, visible)
            for node, kind, line in zip(group.children, kinds, visible):
                self.assertIn(f"{kind} {node.data[1].when} · ", line)  # the whole date and time
            info = review.highlighted_backup()
            self.assertIs(info, group.children[-1].data[1])
            kind = "Safety backup (before a restore)" if info.is_safety else "Backup"
            self.assertIn(f"{kind} from {info.when} · ", review.summary_text)
            self.assertIn(": e restores it", review.summary_text)
            summary = review.query_one("#summary", Static)
            self.assert_on_screen(summary)
            text = " ".join(row[summary.region.x:summary.region.right].strip()
                            for row in rows[summary.region.y:summary.region.bottom])
            self.assertIn(info.when, text)  # the whole date, seconds and all, on screen

    async def test_restore_screen_shows_low_disk_space_in_the_tree(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        bk = str(self.bk)

        class Usage:
            def __init__(self, free):
                self.free = free

        def disk_usage(path):
            # The WoW drive is nearly full; the backup drive has room.
            return Usage(10 ** 12 if str(path).startswith(bk) else 5)

        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                          tool_options={"interface-backup": {"wow_check": list, "disk_usage": disk_usage}})
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            screen = await self.open_restore(app, pilot)
            self.assertTrue(screen.plan.low_space)
            notes = [str(n.label) for n in screen.query_one("#effects", Tree).root.children if n.data == ("note",)]
            self.assertTrue(any(n.startswith("⚠ Low disk space on the WoW drive: 5 B free, ~") for n in notes),
                            notes)
            self.assertTrue(screen.summary_text.endswith("⚠ low disk space on the WoW drive"), screen.summary_text)

    async def test_backups_node_shows_parts(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await self.make_backup(app, pilot)  # Retail and Classic Era in full; Anniversary has WTF only
            damaged = self.bk / "interface-backup" / "backup-retail-20000101-000000.zip"
            damaged.write_bytes(b"not a zip")
            await pilot.press("r")
            await settle(app, pilot)
            labels = {}
            for name in ("Retail", "Classic Era", "Anniversary"):
                group = await self.open_backups(app, pilot, review, name)
                labels[name] = [str(c.label) for c in group.children]
            self.assertEqual(len(labels["Retail"]), 2)
            self.assertIn("Backups (2)", str(self.child(self.flavor_nodes(review)["Retail"], "backups").label))
            self.assertRegex(labels["Retail"][0], r"^backup \d{4}-\d\d-\d\d \d\d:\d\d:\d\d · Interface, WTF · ")  # newest first
            self.assertTrue(labels["Retail"][1].startswith("backup 2000-01-01 00:00:00 · ? · "), labels)  # unreadable
            self.assertIn(" · Interface, WTF · ", labels["Classic Era"][0])
            self.assertIn(" · WTF · ", labels["Anniversary"][0])

    async def test_backup_parts_read_in_a_worker(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        threads = []
        gate = threading.Event()
        self.addCleanup(gate.set)
        real = review_module.read_parts

        def gated(path):
            threads.append(threading.current_thread() is threading.main_thread())
            gate.wait(5)
            return real(path)

        app = self.make_app()
        with patch.object(review_module, "read_parts", gated):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                node = self.flavor_nodes(review)["Retail"]
                node.expand()
                group = self.child(node, "backups")
                group.expand()
                for _ in range(50):
                    await pilot.pause()
                    if threads:
                        break
                self.assertEqual(len(group.children), 1)
                self.assertIn(" · …", str(group.children[0].label))  # listed before the parts are read
                await pilot.press("t")  # leave while the worker is still reading
                await pilot.pause()
                self.assertIsInstance(app.screen, ToolMenuScreen)
                gate.set()
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ToolMenuScreen)
        self.assertTrue(threads)
        self.assertFalse(any(threads), threads)

    # --- queued actions and other screens --------------------------------------------------------
    async def test_queued_restore_is_not_opened_over_settings(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        gate = threading.Event()
        gate.set()
        self.addCleanup(gate.set)
        real = review_module.scan_flavors

        def gated(*args, **kwargs):
            gate.wait(5)
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(review_module, "scan_flavors", gated):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await self.make_backup(app, pilot)
                gate.clear()
                await pilot.press("e")  # rescans, then would show the backups
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
                self.assertIsInstance(app.screen, SetupScreen)
                gate.set()
                await settle(app, pilot)
                self.assertIsInstance(app.screen, SetupScreen)
                self.assertFalse(any(isinstance(s, RestoreScreen) for s in app.screen_stack))
                self.assertTrue(self.notified(app, "Press e on the review screen"))

    async def test_undo_from_result_refused_when_journal_gone(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("escape")  # Esc on the backup result: back to the review
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupReviewScreen)
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            app.screen.result.journal_path.unlink()
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupReviewScreen)
            self.assertTrue(self.notified(app, "can no longer be undone"))

    async def test_unreadable_journal_is_notified_not_confirmed(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            journal = app.screen.result.journal_path
            await pilot.press("r")
            await settle(app, pilot)
            review = app.screen
            self.assertEqual(review.undoable, journal)
            journal.unlink()
            journal.mkdir()  # found by the scan, cannot be read now
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertTrue(self.notified(app, "could not be read", title="Undo not possible"))

    async def test_escape_on_review_goes_to_flavors(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)

    # --- the WoW folder changed with s ------------------------------------------------------------
    def other_install(self):
        return build_interface_tree(build_wow_tree(self.tmp / "Other WoW"))

    async def change_wow_folder(self, app, pilot, other):
        await pilot.press("s")
        await pilot.pause()
        self.assertIsInstance(app.screen, SetupScreen)
        app.cfg.set_path("general", "wow_path", other)
        app.cfg.save()
        app.screen.dismiss(True)
        await pilot.pause()
        self.assertIsInstance(app.screen, BackupSettingsScreen)
        await pilot.press("escape")
        await settle(app, pilot)

    async def test_new_wow_folder_closes_the_review(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        other = self.other_install()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.change_wow_folder(app, pilot, other)
            self.assertIsInstance(app.screen, FlavorScreen)
            self.assertTrue(self.notified(app, "The WoW folder changed"))
            await pilot.press("enter")
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, BackupReviewScreen)
            self.assertTrue(all(f.path.parent == other for f in review.flavors))

    async def test_new_wow_folder_while_on_restore_screen_restores_nothing(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        other = self.other_install()
        extra = self.root / "_retail_" / "Interface" / "new.lua"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            extra.write_text("x", encoding="utf-8")
            await self.open_restore(app, pilot)
            await self.change_wow_folder(app, pilot, other)
            self.assertIsInstance(app.screen, RestoreScreen)
            await pilot.press("o")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
        self.assertTrue(extra.exists())
        self.assertFalse(list((self.bk / "interface-backup").glob("pre-restore-*.zip")))

    async def test_new_wow_folder_while_picking_asks_again(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        other = self.other_install()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            await settle(app, pilot)
            await self.change_wow_folder(app, pilot, other)
            self.assertIsInstance(app.screen, FlavorScreen)
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)  # the old install's list: picked again
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupReviewScreen)
            self.assertTrue(all(f.path.parent == other for f in app.screen.flavors))

    async def test_picker_notes_arrive_while_settings_cover_it(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        release = threading.Event()
        self.addCleanup(release.set)
        real = app_module.list_backups

        def slow_list(*args, **kwargs):
            release.wait(5)
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(app_module, "list_backups", slow_list):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_tool(app, pilot)
                picker = app.screen
                self.assertIsInstance(picker, FlavorScreen)
                await pilot.press("s")
                await pilot.pause()
                self.assertIsInstance(app.screen, SetupScreen)
                release.set()
                await settle(app, pilot)
                await pilot.press("escape")
                await settle(app, pilot)
                await pilot.press("escape")
                await settle(app, pilot)
                self.assertIs(app.screen, picker)
                options = picker.query_one("#flavors", OptionList)
                labels = [str(options.get_option_at_index(n).prompt) for n in range(options.option_count)]
                self.assertTrue(all("no backups yet" in label for label in labels), labels)
