import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.fixtures import build_wow_tree, make_config
from wowtools import __version__
from wowtools.core import events
from wowtools.core.config import Config
from wowtools.suite import run
from wowtools.tools import TOOLS


class FakeApp:
    """Stands in for WowToolsApp: records how run() built it."""

    made = []

    def __init__(self, cfg, **kwargs):
        self.cfg = cfg
        self.kwargs = kwargs
        FakeApp.made.append(self)

    def run(self):
        self.lock_held_while_running = self.kwargs["lock"].held


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
                       lock_path=self.lock_path, app_factory=FakeApp, input_fn=lambda prompt: answer, **kwargs)
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
