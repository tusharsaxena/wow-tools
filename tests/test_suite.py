import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.fixtures import build_wow_tree, make_config
from wowtools import __version__
from wowtools.core import events
from wowtools.suite import run
from wowtools.tools import TOOLS


class SuiteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = make_config(self.tmp, build_wow_tree(self.tmp / "World of Warcraft"))
        self.log_dir = self.tmp / "logs"
        # run() installs a process-wide log pointing at this temp dir; put the old one back afterwards.
        self.addCleanup(setattr, events, "_current", events.get_event_log())

    def run_suite(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run(argv, cfg=self.cfg, log_dir=self.log_dir)
        return code, out.getvalue(), err.getvalue()

    def test_registry(self):
        self.assertIn("wtf-cleaner", TOOLS)
        self.assertTrue(callable(TOOLS["wtf-cleaner"].main()))

    def test_version_and_help_do_not_log(self):
        code, out, _ = self.run_suite(["--version"])
        self.assertEqual((code, out.strip()), (0, __version__))
        code, out, _ = self.run_suite(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("wtf-cleaner", out)
        self.assertFalse(self.log_dir.exists())

    def test_unknown_tool(self):
        code, _, err = self.run_suite(["bogus"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown tool", err)

    def test_dispatches_to_tool_and_logs_session(self):
        code, out, _ = self.run_suite(["wtf-cleaner", "--flavor", "retail", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["totals"]["items"], 6)
        records = [json.loads(line) for path in self.log_dir.glob("wtf-cleaner/events-*.log")
                   for line in path.read_text(encoding="utf-8").splitlines()]
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "session.start")
        self.assertEqual(names[-1], "session.end")
        self.assertEqual(records[-1]["data"]["exit_code"], 0)
        self.assertTrue(all(r["tool"] == "wtf-cleaner" for r in records))
        self.assertIn("scan.completed", names)
        self.assertTrue(list(self.log_dir.glob("wtf-cleaner/logfile-*.log")))
