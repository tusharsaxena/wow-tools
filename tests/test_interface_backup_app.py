from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Checkbox, DataTable, Input, OptionList, Static

from tests.fixtures import TuiTestCase, build_interface_tree, build_wow_tree, make_config, settle
from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools import TOOLS
from wowtools.tools.interface_backup import app as app_module
from wowtools.tools.interface_backup import summary_screen as summary_module
from wowtools.tools.interface_backup import report as report_module
from wowtools.tools.interface_backup import restore_screen as restore_module
from wowtools.tools.interface_backup.app import BackupSettingsScreen
from wowtools.tools.interface_backup.restore import PartOutcome, RestoreError, RestoreResult, RestoreStopped
from wowtools.tools.interface_backup.restore_screen import BackupListScreen, RestoreResultScreen, RestoreScreen
from wowtools.tools.interface_backup.settings import load_settings
from wowtools.tools.interface_backup.summary_screen import (BackupProgressScreen, BackupResultScreen,
                                                            BackupSummaryScreen)
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.widgets import ACTION_VARIANTS, NavHint

SIZE = (140, 50)
SMALL = (80, 24)  # the default terminal size: everything must fit


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

    async def open_summary(self, app, pilot, keys=("enter",)):
        await self.open_tool(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press(*keys)  # Enter: "All flavors"
        await settle(app, pilot)
        self.assertIsInstance(app.screen, BackupSummaryScreen)
        return app.screen

    def zips(self):
        return sorted(p.name for p in (self.bk / "interface-backup").glob("backup-*.zip"))

    def assert_on_screen(self, widget, size=SMALL):
        r = widget.region
        self.assertTrue(r.width > 0 and r.height > 0, f"{widget!r} is not shown: {r}")
        self.assertTrue(r.x >= 0 and r.y >= 0 and r.right <= size[0] and r.bottom <= size[1],
                        f"{widget!r} is cut off at {size}: {r}")

    def notified(self, app, text, title=None):
        return any(text in str(n.message) and (title is None or n.title == title) for n in app._notifications)

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
            app.screen.query_one("#keep_backups", Input).value = "0"
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            await settle(app, pilot)
        s = load_settings(Config(self.config_dir / "interface-backup.cfg").load())
        self.assertEqual((s.backup_dir, s.keep_backups, s.keep_journals), (self.bk, 0, 10))

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

    async def test_settings_refuse_bad_counts(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            screen = app.screen
            screen.query_one("#keep_backups", Input).value = "-1"
            screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIn("Backups to keep", screen.error_text)
            screen.query_one("#keep_backups", Input).value = "3"
            screen.query_one("#keep_journals", Input).value = "0"
            screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertIn("at least 1 journal", screen.error_text)
        self.assertFalse((self.config_dir / "interface-backup.cfg").exists())

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
            await self.open_summary(app, pilot)
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
            summary = await self.open_summary(app, pilot, keys=("down", "enter"))
            self.assertEqual(summary.query_one("#flavors", DataTable).row_count, 1)
            self.assertTrue(summary.sub_title.startswith("Interface Backup · "))
            await pilot.press("f")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
        stored = load_settings(Config(self.config_dir / "interface-backup.cfg").load()).last_flavor_choice
        self.assertTrue(stored.startswith("_") and stored.endswith("_"), stored)

    # --- summary ----------------------------------------------------------------------------------
    async def test_summary_lists_every_flavor_and_where_zips_go(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            summary = await self.open_summary(app, pilot)
            self.assertEqual(summary.sub_title, "Interface Backup · All flavors")
            table = summary.query_one("#flavors", DataTable)
            self.assertEqual(table.row_count, 4)  # retail, classic era, anniversary, ptr
            details = str(summary.query_one("#details", Static).render())
            self.assertIn("interface-backup", details)
            self.assertFalse(summary.query_one("#btn-backup", Button).disabled)
            self.assertTrue(summary.query_one("#btn-undo", Button).disabled)  # nothing restored yet
            for screen_hint in summary.query(NavHint):
                self.assertIn("b back up", str(screen_hint.render()))
            variants = {i: summary.query_one(f"#{i}", Button).variant
                        for i in ("btn-backup", "btn-restore", "btn-undo", "btn-rescan")}
        self.assertEqual(variants, {"btn-backup": ACTION_VARIANTS["confirm"],
                                    "btn-restore": ACTION_VARIANTS["neutral"],
                                    "btn-undo": ACTION_VARIANTS["revert"],
                                    "btn-rescan": ACTION_VARIANTS["neutral"]})

    async def test_scan_runs_in_a_worker(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        real = summary_module.scan_flavors
        threads = []

        def scan(*args, **kwargs):
            threads.append(threading.current_thread() is threading.main_thread())
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(summary_module, "scan_flavors", scan):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
        self.assertEqual(threads, [False])

    async def test_tools_key_returns_to_menu(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)

    # --- back up ----------------------------------------------------------------------------------
    async def test_back_up_all_flavors(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                summary = await self.open_summary(app, pilot)
                table = summary.query_one("#flavors", DataTable)
                self.assertGreaterEqual(table.row_count, 3)
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
                self.assertEqual(result_table.row_count, 4)  # Retail PTR (neither part) is there, Skipped
                rows = {str(result_table.get_row_at(i)[0]): [str(c) for c in result_table.get_row_at(i)]
                        for i in range(result_table.row_count)}
                self.assertEqual(rows["Retail PTR"][1:3], ["Skipped", "no Interface or WTF folder"])
                self.assertIn("3 of 4 flavors backed up", str(app.screen.query_one("#result-head", Static).render()))
                self.assertFalse(app.busy)
                await pilot.press("r")
                await settle(app, pilot)
                self.assertIs(app.screen, summary)
                newest = [str(c) for c in table.get_row_at(0)]
                self.assertEqual(newest[4], "1")  # retail now has one backup
        zips = self.zips()
        self.assertTrue(any(n.startswith("backup-retail-") for n in zips))
        self.assertFalse(any(n.startswith("backup-ptr-") for n in zips))  # neither part: skipped
        with zipfile.ZipFile(self.bk / "interface-backup" / next(n for n in zips if "retail" in n)) as zf:
            self.assertIn("WTF/Config.wtf", zf.namelist())
        selections = [(r["data"].get("screen"), r["data"].get("control"), r["data"].get("value"))
                      for r in records if r["event"] == "ui.selection"]
        self.assertIn(("ibackup_summary", "back_up", True), selections)
        self.assertIn(("confirm", "back_up_confirm", True), selections)
        self.assertIn(("ibackup_result", "next", "review"), selections)
        self.assertTrue(activity.wait_idle(0))

    async def test_link_only_flavor_is_skipped_with_its_reason(self):
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
                await self.open_summary(app, pilot)
                await pilot.press("b")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIn("Back up 2 flavors?", app.screen.title_text)
                body = str(app.screen.body_text)
                self.assertIn("Skipped", body)
                self.assertIn("WTF is a link", body)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, BackupResultScreen)
                table = app.screen.query_one("#result-table", DataTable)
                rows = {str(table.get_row_at(i)[0]): [str(c) for c in table.get_row_at(i)]
                        for i in range(table.row_count)}
                self.assertEqual(rows["Anniversary"][1:3], ["Skipped", "WTF is a link (not followed)"])
                self.assertEqual(rows["Retail"][1], "Backed up")
        skipped = [r["data"] for r in records if r["event"] == "ibackup.backup_skipped"]
        self.assertIn({"flavor": "_anniversary_", "reason": "WTF is a link (not followed)", "links": ["WTF"]}, skipped)
        self.assertFalse(any("anniversary" in n for n in self.zips()))

    def test_throttled_progress_forwards_stage_changes_ends_and_one_per_interval(self):
        now = [0.0]
        sent = []
        progress = summary_module.ThrottledProgress(lambda *a: sent.append(a), 0.1, clock=lambda: now[0])
        for i in range(1, 6):
            progress("backup", i, 10, f"f{i}")  # first one forwarded, then nothing until the interval
        now[0] = 0.15
        progress("backup", 6, 10, "f6")  # interval passed
        progress("backup", 7, 10, "f7")
        progress("backup", 10, 10, "f10")  # end of the stage
        progress("verify", 1, 10, "v1")  # new stage
        progress("swap", 0, 0, "Interface")  # no count
        progress.reset()
        progress("swap", 0, 0, "WTF")
        progress("verify", 2, 10, "v2")  # stage changed again
        self.assertEqual([a[3] for a in sent], ["f1", "f6", "f10", "v1", "Interface", "WTF", "v2"])

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
        with patch.object(summary_module, "PROGRESS_INTERVAL", 3600.0, create=True), \
                patch.object(BackupProgressScreen, "update_progress", record):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
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
            await self.open_summary(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)
        self.assertFalse((self.bk / "interface-backup").exists())

    async def test_wow_running_is_an_alert(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app(running=["Wow.exe"])
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
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
            await self.open_summary(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
        self.assertEqual(threads, [False])

    async def test_folder_edited_into_wtf_refuses_the_backup(self):
        self.save_tool_cfg(backup_dir=str(self.root / "_retail_" / "WTF" / "bk"))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            summary = await self.open_summary(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIs(app.screen, summary)
        self.assertFalse((self.root / "_retail_" / "WTF" / "bk").exists())

    async def test_busy_while_backing_up_guards_leaving(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        release = threading.Event()
        self.addCleanup(release.set)
        real = summary_module.back_up_all
        seen = []

        def slow(*args, **kwargs):
            seen.append(activity.wait_idle(0))
            release.wait(5)
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(summary_module, "back_up_all", slow):
            async with app.run_test(size=SIZE) as pilot:
                summary = await self.open_summary(app, pilot)
                await pilot.press("b")
                await settle(app, pilot)
                await pilot.press("y")
                await pilot.pause()
                self.assertTrue(app.busy)
                self.assertIsInstance(app.screen, BackupProgressScreen)
                summary.action_leave("tools")
                summary.action_back_up()
                summary.action_rescan()
                await pilot.pause()
                self.assertIsInstance(app.screen, BackupProgressScreen)
                self.assertTrue(summary.query_one("#btn-backup", Button).disabled)
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
            await self.open_summary(app, pilot)
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
        with patch.object(summary_module, "back_up_all", boom):
            async with app.run_test(size=SIZE) as pilot:
                summary = await self.open_summary(app, pilot)
                await pilot.press("b")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIs(app.screen, summary)
                self.assertFalse(app.busy)
                self.assertFalse(summary.query_one("#btn-backup", Button).disabled)
                self.assertTrue(self.notified(app, "disk gone", title="Stopped"))

    # --- restore and undo -------------------------------------------------------------------------
    async def make_backup(self, app, pilot):
        await pilot.press("b")
        await settle(app, pilot)
        await pilot.press("y")
        await settle(app, pilot)
        self.assertIsInstance(app.screen, BackupResultScreen)

    async def open_restore(self, app, pilot, name="Retail"):
        """From the summary: e, then the newest backup of the flavor called `name` in the list."""
        await pilot.press("e")
        await settle(app, pilot)
        self.assertIsInstance(app.screen, BackupListScreen)
        table = app.screen.query_one("#backups", DataTable)
        table.move_cursor(row=next(i for i in range(table.row_count) if str(table.get_row_at(i)[1]) == name))
        await pilot.press("enter")
        await settle(app, pilot)
        self.assertIsInstance(app.screen, RestoreScreen)
        return app.screen

    async def test_restore_with_warnings_then_undo(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        retail = self.root / "_retail_"
        extra = retail / "Interface" / "AddOns" / "WeakAuras" / "wa.lua"
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                extra.parent.mkdir(parents=True)
                extra.write_text("wa", encoding="utf-8")
                screen = await self.open_restore(app, pilot)
                self.assertEqual(screen.sub_title, "Interface Backup · restore")
                info = str(screen.query_one("#backup-info", Static).render())
                self.assertIsNone(re.search(r"\d{4}-\d\d-\d\dT\d\d", info), info)  # never the raw ISO stamp
                self.assertIn("Interface/AddOns/WeakAuras", str(screen.query_one("#warnings", Static).render()))
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
                self.assertEqual(app.screen.query_one("#undo", Button).variant, ACTION_VARIANTS["revert"])
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
                self.assertIsInstance(app.screen, BackupSummaryScreen)
                self.assertTrue(app.screen.query_one("#btn-undo", Button).disabled)  # undone: nothing left
        self.assertEqual(extra.read_text(encoding="utf-8"), "wa")
        selections = [(r["data"].get("screen"), r["data"].get("control"), r["data"].get("value"))
                      for r in records if r["event"] == "ui.selection"]
        self.assertIn(("ibackup_summary", "restore", True), selections)
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
            await self.open_summary(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            (retail / "Interface" / "keep.txt").write_text("k", encoding="utf-8")
            (retail / "WTF" / "Config.wtf").write_bytes(b"mine")
            screen = await self.open_restore(app, pilot)
            self.assertIn("keep.txt", str(screen.query_one("#warnings", Static).render()))
            screen.query_one("#part-Interface", Checkbox).value = False
            await settle(app, pilot)
            self.assertNotIn("keep.txt", str(screen.query_one("#warnings", Static).render()))
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
            await self.open_summary(app, pilot)
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
            await self.open_summary(app, pilot)
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
            await self.open_summary(app, pilot)
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
            self.assertIn("interrupted restore", str(screen.query_one("#warnings", Static).render()))
            await pilot.press("o")
            await settle(app, pilot)
            self.assertIs(app.screen, screen)

    async def test_restore_list_escape_returns_to_summary(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await pilot.press("e")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupListScreen)
            self.assertEqual(app.screen.sub_title, "Interface Backup · choose a backup")
            self.assertIn("No backups", str(app.screen.query_one("#list-title", Static).render()))
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)

    async def test_restore_screen_back_and_decline_change_nothing(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        extra = self.root / "_retail_" / "Interface" / "new.lua"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            extra.write_text("x", encoding="utf-8")
            await self.open_restore(app, pilot)
            await pilot.press("b")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)
            await self.open_restore(app, pilot)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)
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
        with patch.object(restore_module, "list_backups", spy(restore_module.list_backups)), \
                patch.object(restore_module, "open_backup", spy(restore_module.open_backup)), \
                patch.object(restore_module, "scan_flavor", spy(restore_module.scan_flavor)), \
                patch.object(restore_module, "plan_restore", spy(restore_module.plan_restore)):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
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
            await self.open_summary(app, pilot)
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
            await self.open_summary(app, pilot)
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
        with patch.object(summary_module, "restore", refuse):
            async with app.run_test(size=SIZE) as pilot:
                summary = await self.open_summary(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                await self.open_restore(app, pilot)
                await pilot.press("o")
                await settle(app, pilot)
                await pilot.press("y")
                await settle(app, pilot)
                self.assertIs(app.screen, summary)
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
        with patch.object(summary_module, "restore", stop):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
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

    async def test_undo_from_summary_starts_on_no(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        extra = self.root / "_retail_" / "WTF" / "new.wtf"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
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
            summary = app.screen
            self.assertIsInstance(summary, BackupSummaryScreen)
            self.assertFalse(summary.query_one("#btn-undo", Button).disabled)
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIs(app.screen.focused, app.screen.query_one("#no", Button))
            self.assertIn("Undo the restore from", app.screen.title_text)
            await pilot.press("enter")  # No
            await settle(app, pilot)
            self.assertIs(app.screen, summary)
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
        with patch.object(summary_module, "restore", stop):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
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
        with patch.object(summary_module, "restore", stop):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
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
            await self.open_summary(app, pilot)
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
        with patch.object(summary_module, "wow_check_for", check_for):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
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

    # --- the default terminal size (80x24) ---------------------------------------------------------
    async def test_summary_actions_fit_80_columns(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SMALL) as pilot:
            summary = await self.open_summary(app, pilot)
            buttons = list(summary.query_one("#actions").query(Button))
            self.assertEqual(len(buttons), 4)
            for button in buttons:
                self.assert_on_screen(button)
            await self.make_backup(app, pilot)
            for button in app.screen.query(Button):  # the backup result screen
                self.assert_on_screen(button)
            await pilot.press("r")
            await settle(app, pilot)
            for button in summary.query_one("#actions").query(Button):
                self.assert_on_screen(button)

    async def test_summary_notices_fit_80x24(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        (self.root / "_classic_era_" / "Interface.restoring").mkdir()
        try:
            os.symlink(self.tmp, self.root / "_retail_" / "Interface" / "AddOns" / "Linked", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        app = self.make_app()
        async with app.run_test(size=SMALL) as pilot:
            summary = await self.open_summary(app, pilot)
            notices = summary.query_one("#notices", Static)
            text = str(notices.render())
            self.assertIn("Restore is blocked for this flavor", text)
            self.assertIn("not backed up; a restore keeps them", text)
            self.assert_on_screen(notices)
            self.assertLessEqual(notices.region.bottom, summary.query_one("#body").region.bottom)

    async def test_restore_screens_fit_80_columns(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SMALL) as pilot:
            await self.open_summary(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            await self.open_restore(app, pilot)
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

    async def test_restore_confirm_fits_80x24_with_long_warnings(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        retail = self.root / "_retail_"
        app = self.make_app(running=["Wow.exe"])
        async with app.run_test(size=SMALL) as pilot:
            await self.open_summary(app, pilot)
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
            self.assertIn("and 5 more", str(screen.query_one("#warnings", Static).render()))  # the full list
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

    async def test_settings_labels_wrap_at_80_columns(self):
        app = self.make_app()
        async with app.run_test(size=SMALL) as pilot:
            await self.open_tool(app, pilot)
            screen = app.screen
            self.assertIsInstance(screen, BackupSettingsScreen)
            for label in screen.query("Label"):
                self.assertLessEqual(label.region.right, SMALL[0])
                text = str(label.render())
                self.assertGreaterEqual(label.region.height * label.region.width, len(text), text)
            destination = str(screen.query_one("#destination", Static).render())
            self.assertIn(str(Path("World of Warcraft") / "wow-tools" / "interface-backup"), destination)
            screen.query_one("#backup_dir", Input).value = str(self.bk)
            await pilot.pause()
            self.assertIn(str(self.bk / "interface-backup"), str(screen.query_one("#destination", Static).render()))

    # --- the backup list ----------------------------------------------------------------------------
    async def test_backup_list_shows_flavor_names(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("e")  # Restore straight from the backup result: rescans, then opens the list
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupListScreen)
            table = app.screen.query_one("#backups", DataTable)
            names = {str(table.get_row_at(i)[1]) for i in range(table.row_count)}
            self.assertEqual(names, {"Retail", "Classic Era", "Anniversary"})

    async def test_backup_list_shows_parts(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await self.make_backup(app, pilot)  # Retail and Classic Era in full; Anniversary has WTF only
            damaged = self.bk / "interface-backup" / "backup-retail-20000101-000000.zip"
            damaged.write_bytes(b"not a zip")
            await pilot.press("r")
            await settle(app, pilot)
            await pilot.press("e")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupListScreen)
            table = app.screen.query_one("#backups", DataTable)
            self.assertEqual(tuple(str(c.label) for c in table.ordered_columns), report_module.LIST_COLUMNS)
            rows = {info.path.name: tuple(str(c) for c in table.get_row_at(i))
                    for i, info in enumerate(app.screen.infos)}
            self.assertEqual(rows.pop(damaged.name)[1:4], ("Retail", "backup", "?"))  # unreadable: still listed
            self.assertEqual(sorted((r[1], r[3]) for r in rows.values()),
                             [("Anniversary", "WTF"), ("Classic Era", "Interface, WTF"), ("Retail", "Interface, WTF")])

    async def test_backup_list_parts_read_in_a_worker(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        threads = []
        gate = threading.Event()
        self.addCleanup(gate.set)
        real = restore_module.read_parts

        def gated(path):
            threads.append(threading.current_thread() is threading.main_thread())
            gate.wait(5)
            return real(path)

        app = self.make_app()
        with patch.object(restore_module, "read_parts", gated):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
                await self.make_backup(app, pilot)
                await pilot.press("r")
                await settle(app, pilot)
                await pilot.press("e")
                for _ in range(50):
                    await pilot.pause()
                    if isinstance(app.screen, BackupListScreen) and threads:
                        break
                screen = app.screen
                self.assertIsInstance(screen, BackupListScreen)
                table = screen.query_one("#backups", DataTable)
                self.assertEqual(str(table.get_row_at(0)[3]), "…")  # listed before the parts are read
                await pilot.press("escape")  # leave while the worker is still reading
                await pilot.pause()
                self.assertIsInstance(app.screen, BackupSummaryScreen)
                gate.set()
                await settle(app, pilot)
                self.assertIsInstance(app.screen, BackupSummaryScreen)
        self.assertTrue(threads)
        self.assertFalse(any(threads), threads)

    # --- queued actions and other screens --------------------------------------------------------
    async def test_queued_restore_is_not_opened_over_settings(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        gate = threading.Event()
        gate.set()
        self.addCleanup(gate.set)
        real = summary_module.scan_flavors

        def gated(*args, **kwargs):
            gate.wait(5)
            return real(*args, **kwargs)

        app = self.make_app()
        with patch.object(summary_module, "scan_flavors", gated):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_summary(app, pilot)
                await self.make_backup(app, pilot)
                gate.clear()
                await pilot.press("e")  # rescans, then would open the backup list
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
                self.assertIsInstance(app.screen, SetupScreen)
                gate.set()
                await settle(app, pilot)
                self.assertIsInstance(app.screen, SetupScreen)
                self.assertFalse(any(isinstance(s, BackupListScreen) for s in app.screen_stack))
                self.assertTrue(self.notified(app, "Press e on the summary"))

    async def test_undo_from_result_refused_when_journal_gone(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await self.make_backup(app, pilot)
            await pilot.press("escape")  # Esc on the backup result: back to the summary
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)
            await self.open_restore(app, pilot)
            await pilot.press("o")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, RestoreResultScreen)
            app.screen.result.journal_path.unlink()
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, BackupSummaryScreen)
            self.assertTrue(self.notified(app, "can no longer be undone"))

    async def test_unreadable_journal_is_notified_not_confirmed(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
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
            summary = app.screen
            self.assertEqual(summary.undoable, journal)
            journal.unlink()
            journal.mkdir()  # found by the scan, cannot be read now
            await pilot.press("z")
            await settle(app, pilot)
            self.assertIs(app.screen, summary)
            self.assertTrue(self.notified(app, "could not be read", title="Undo not possible"))

    async def test_escape_on_summary_goes_to_flavors(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
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

    async def test_new_wow_folder_closes_the_summary(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        other = self.other_install()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
            await self.change_wow_folder(app, pilot, other)
            self.assertIsInstance(app.screen, FlavorScreen)
            self.assertTrue(self.notified(app, "The WoW folder changed"))
            await pilot.press("enter")
            await settle(app, pilot)
            summary = app.screen
            self.assertIsInstance(summary, BackupSummaryScreen)
            self.assertTrue(all(f.path.parent == other for f in summary.flavors))

    async def test_new_wow_folder_while_on_restore_screen_restores_nothing(self):
        self.save_tool_cfg(backup_dir=str(self.bk))
        other = self.other_install()
        extra = self.root / "_retail_" / "Interface" / "new.lua"
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_summary(app, pilot)
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
            self.assertIsInstance(app.screen, BackupSummaryScreen)
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
