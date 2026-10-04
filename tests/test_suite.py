from __future__ import annotations

import io
import json
import tempfile
import threading
import time
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import ClassVar

from tests.fixtures import build_wow_tree, make_config
from wowtools import __version__
from wowtools.core import activity, events
from wowtools.core.config import Config
from wowtools.core.lock import InstanceLock
from wowtools.suite import run
from wowtools.tools import TOOLS


class FakeApp:
    """Stands in for WowToolsApp: records how run() built it."""

    made: ClassVar[list[FakeApp]] = []

    def __init__(self, cfg, **kwargs):
        self.cfg = cfg
        self.kwargs = kwargs
        FakeApp.made.append(self)

    def run(self):
        self.lock_held_while_running = self.kwargs["lock"].held


class WorkerApp(FakeApp):
    """Leaves a file-changing worker running when run() returns, as a quit during a clean would."""

    started = None

    def run(self):
        def work():
            with activity.running():
                time.sleep(0.2)

        entered = threading.Event()
        thread = threading.Thread(target=lambda: (entered.set(), work()))
        WorkerApp.started = time.monotonic()
        thread.start()
        entered.wait()
        time.sleep(0.02)  # let the worker enter running()


class CrashedApp(FakeApp):
    """Textual sets return_code = 1 after an unhandled exception, and run() still returns normally."""

    def run(self):
        self.return_code = 1


class ActivityTest(unittest.TestCase):
    def test_running_marks_busy_until_every_run_ends(self):
        self.assertTrue(activity.wait_idle(0))
        with activity.running():
            with activity.running():
                self.assertFalse(activity.wait_idle(0))
            self.assertFalse(activity.wait_idle(0))
        self.assertTrue(activity.wait_idle(0))

    def test_running_ends_even_when_the_work_raises(self):
        with self.assertRaises(RuntimeError), activity.running():
            raise RuntimeError("boom")
        self.assertTrue(activity.wait_idle(0))


class SuiteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.config_dir = self.tmp / "config"
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.cfg = make_config(self.config_dir, self.root)
        self.log_dir = self.tmp / "logs"
        self.lock_path = self.tmp / "wow-tools.lock"
        FakeApp.made = []
        # run() installs a process-wide log pointing at this temp dir; put the old one back afterwards.
        self.addCleanup(setattr, events, "_current", events.get_event_log())

    def run_suite(self, argv, *, cfg="default", answer="n", **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run(argv, cfg=self.cfg if cfg == "default" else cfg, log_dir=self.log_dir,
                       config_dir=self.config_dir, legacy_config=self.tmp / "wow-tools.cfg",
                       lock_path=self.lock_path, app_factory=kwargs.pop("app_factory", FakeApp), input_fn=lambda prompt: answer, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def records(self, tool="suite"):
        return [json.loads(line) for path in self.log_dir.glob(f"{tool}/events-*.log")
                for line in path.read_text(encoding="utf-8").splitlines()]

    def test_registry(self):
        self.assertIn("wtf-cleaner", TOOLS)
        self.assertEqual(TOOLS["wtf-cleaner"].flow().__name__, "WtfCleanerFlow")

    def test_version_and_help_do_not_log(self):
        code, out, _ = self.run_suite(["--version"])
        self.assertEqual((code, out.strip()), (0, __version__))
        code, out, _ = self.run_suite(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("WTF Cleaner", out)
        self.assertIn("wow-tools.sh", out)
        self.assertFalse(self.log_dir.exists())

    def test_run_closes_its_log_files(self):
        code, _, _ = self.run_suite([])
        self.assertEqual(code, 0)
        self.assertTrue(self.records())
        self.assertEqual(events.get_event_log()._handles, {})  # Windows could not delete or prune them otherwise

    def test_tools_cannot_be_started_directly(self):
        code, _, err = self.run_suite(["wtf-cleaner", "--flavor", "retail"])
        self.assertEqual(code, 1)
        self.assertIn("Tools open from the menu", err)
        code, _, err = self.run_suite(["bogus"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown command", err)
        self.assertEqual(FakeApp.made, [])

    def test_no_args_opens_the_suite_app_with_the_lock_held(self):
        code, _, _ = self.run_suite([])
        self.assertEqual(code, 0)
        app = FakeApp.made[0]
        self.assertIsNone(app.kwargs["conflict"])
        self.assertTrue(app.lock_held_while_running)
        self.assertFalse(self.lock_path.exists())  # released on exit
        names = [r["event"] for r in self.records()]
        self.assertEqual((names[0], names[-1]), ("session.start", "session.end"))

    def test_lock_released_only_after_worker_finishes(self):
        released = []
        real_release = InstanceLock.release

        def release(lock):
            released.append(time.monotonic())
            return real_release(lock)

        with unittest.mock.patch.object(InstanceLock, "release", release):
            code, _, _ = self.run_suite([], app_factory=WorkerApp)
        self.assertEqual(code, 0)
        self.assertTrue(activity.wait_idle(0))
        self.assertGreaterEqual(released[-1] - WorkerApp.started, 0.2)
        end = [r for r in self.records() if r["event"] == "session.end"][-1]
        self.assertIs(end["data"]["waited_for_worker"], True)

    def test_app_return_code_is_propagated(self):
        code, _, _ = self.run_suite([], app_factory=CrashedApp)
        self.assertEqual(code, 1)
        end = [r for r in self.records() if r["event"] == "session.end"][-1]
        self.assertEqual((end["level"], end["data"]["exit_code"]), ("warning", 1))

    def test_clean_app_exit_returns_zero(self):
        code, _, _ = self.run_suite([])  # FakeApp has no return_code at all
        self.assertEqual(code, 0)

    def test_existing_lock_is_passed_to_the_app(self):
        self.lock_path.write_text(json.dumps({"pid": 1, "host": "pc", "started": "", "platform": "", "token": "x"}))
        self.run_suite([])
        conflict = FakeApp.made[0].kwargs["conflict"]
        self.assertEqual((conflict.pid, conflict.host), (1, "pc"))
        self.assertTrue(self.lock_path.exists())  # never removed by a copy that did not take it over
        self.assertIn("lock.conflict", [r["event"] for r in self.records()])

    def test_update_with_existing_lock_asks_on_the_terminal(self):
        self.lock_path.write_text(json.dumps({"pid": 1, "host": "pc", "started": "", "platform": "", "token": "x"}))
        code, _, err = self.run_suite(["update", "--check"], answer="n")
        self.assertEqual(code, 1)
        self.assertIn("may already be running", err)
        self.assertEqual(json.loads(self.lock_path.read_text())["token"], "x")

    def test_legacy_config_is_migrated_on_start(self):
        legacy = self.tmp / "wow-tools.cfg"
        legacy.write_text(f"[general]\nwow_path = {self.root}\ncheck_for_updates = false\n\n"
                          "[wtf_cleaner]\nmax_age_days = 45\n", encoding="utf-8")
        (self.config_dir / "wow-tools.cfg").unlink()
        code, _, _ = self.run_suite([], cfg=None)
        self.assertEqual(code, 0)
        self.assertFalse(legacy.exists())
        self.assertEqual(Config(self.config_dir / "wtf-cleaner.cfg").load().get("wtf_cleaner", "max_age_days"), "45")
        self.assertEqual(FakeApp.made[0].cfg.wow_path, self.root)
        self.assertIn("config.migrated", [r["event"] for r in self.records()])

    def test_renamed_tool_config_and_folders_move_on_start(self):
        (self.config_dir / "screenshots.cfg").write_text("[screenshots]\ncopy_mode = true\n", encoding="utf-8")
        _write_file(self.log_dir / "screenshots" / "events-2026-10-01.log", "old")
        _write_file(self.root / "wow-tools" / "screenshots" / "journal" / "journal-1.jsonl", "j")
        code, _, _ = self.run_suite([])
        self.assertEqual(code, 0)
        self.assertFalse((self.config_dir / "screenshots.cfg").exists())
        self.assertEqual(Config(self.config_dir / "screenshot-organizer.cfg").load()
                         .get("screenshot_organizer", "copy_mode"), "true")
        self.assertFalse((self.log_dir / "screenshots").exists())
        self.assertTrue((self.log_dir / "screenshot-organizer" / "events-2026-10-01.log").is_file())
        self.assertFalse((self.root / "wow-tools" / "screenshots").exists())
        self.assertTrue((self.root / "wow-tools" / "screenshot-organizer" / "journal" / "journal-1.jsonl").is_file())
        records = self.records()
        self.assertEqual([r["event"] for r in records].count("folder.renamed"), 2)
        config_event = next(r for r in records if r["event"] == "config.renamed")
        self.assertEqual(config_event["data"]["new"], str(self.config_dir / "screenshot-organizer.cfg"))

    def test_renamed_tool_with_legacy_config_section(self):
        legacy = self.tmp / "wow-tools.cfg"
        legacy.write_text(f"[general]\nwow_path = {self.root}\ncheck_for_updates = false\n\n"
                          "[screenshots]\nkeep_journals = 4\n", encoding="utf-8")
        (self.config_dir / "wow-tools.cfg").unlink()
        code, _, _ = self.run_suite([], cfg=None)
        self.assertEqual(code, 0)
        cfg = Config(self.config_dir / "screenshot-organizer.cfg").load()
        self.assertEqual(cfg.get("screenshot_organizer", "keep_journals"), "4")
        self.assertIsNone(Config(self.config_dir / "wow-tools.cfg").load().get("screenshots", "keep_journals"))

    def test_folder_clash_is_logged_as_a_warning_and_start_carries_on(self):
        _write_file(self.root / "wow-tools" / "screenshots" / "journal" / "a.jsonl", "old")
        _write_file(self.root / "wow-tools" / "screenshot-organizer" / "journal" / "a.jsonl", "new")
        code, _, _ = self.run_suite([])
        self.assertEqual(code, 0)
        event = next(r for r in self.records() if r["event"] == "folder.renamed")
        self.assertEqual((event["level"], event["data"]["clashes"]), ("warning", ["journal/a.jsonl"]))
        self.assertEqual((self.root / "wow-tools" / "screenshot-organizer" / "journal" / "a.jsonl")
                         .read_text(encoding="utf-8"), "new")

    def test_no_renamed_data_logs_nothing(self):
        self.run_suite([])
        self.assertFalse({"config.renamed", "folder.renamed"} & {r["event"] for r in self.records()})

    def test_unreadable_old_tool_config_stops_start(self):
        (self.config_dir / "screenshots.cfg").write_text("not ini\n", encoding="utf-8")
        code, _, err = self.run_suite([])
        self.assertEqual(code, 1)
        self.assertIn("screenshots.cfg", err)
        self.assertEqual(FakeApp.made, [])
        self.assertFalse(self.lock_path.exists())  # the lock taken first is released again

    def test_renames_wait_while_another_copy_holds_the_lock(self):
        self.lock_path.write_text(json.dumps({"pid": 1, "host": "pc", "started": "", "platform": "", "token": "x"}))
        (self.config_dir / "screenshots.cfg").write_text("[screenshots]\ncopy_mode = true\n", encoding="utf-8")
        _write_file(self.log_dir / "screenshots" / "events-2026-10-01.log", "old")
        _write_file(self.root / "wow-tools" / "screenshots" / "journal" / "journal-1.jsonl", "j")
        code, _, _ = self.run_suite([])
        self.assertEqual(code, 0)
        self.assertTrue((self.config_dir / "screenshots.cfg").is_file())
        self.assertFalse((self.config_dir / "screenshot-organizer.cfg").exists())
        self.assertTrue((self.log_dir / "screenshots" / "events-2026-10-01.log").is_file())
        self.assertTrue((self.root / "wow-tools" / "screenshots" / "journal" / "journal-1.jsonl").is_file())
        events_seen = {r["event"] for r in self.records()}
        self.assertIn("lock.conflict", events_seen)
        self.assertFalse({"config.renamed", "folder.renamed"} & events_seen)
        self.assertEqual(json.loads(self.lock_path.read_text())["token"], "x")
        # Once that copy is gone, the next start moves everything.
        self.lock_path.unlink()
        self.run_suite([])
        self.assertFalse((self.config_dir / "screenshots.cfg").exists())
        self.assertTrue((self.root / "wow-tools" / "screenshot-organizer" / "journal" / "journal-1.jsonl").is_file())


def _write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
