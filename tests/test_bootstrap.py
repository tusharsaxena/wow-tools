from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from wowtools.core import bootstrap


class CheckPythonTest(unittest.TestCase):
    def test_rejects_old_python(self):
        message = bootstrap.check_python((3, 9, 18))
        self.assertIn("3.10", message)
        self.assertIn("3.9", message)

    def test_accepts_supported_python(self):
        self.assertIsNone(bootstrap.check_python((3, 10, 0)))
        self.assertIsNone(bootstrap.check_python((3, 13, 1)))


class VendorPathTest(unittest.TestCase):
    def test_paths_are_anchored_to_the_repo_not_the_cwd(self):
        self.assertEqual(bootstrap.VENDOR_DIR, bootstrap.REPO_ROOT / "vendor")
        self.assertTrue((bootstrap.REPO_ROOT / "wowtools" / "__init__.py").is_file())

    def test_add_vendor_path_is_idempotent(self):
        bootstrap.add_vendor_path()
        bootstrap.add_vendor_path()
        self.assertEqual(sys.path.count(str(bootstrap.VENDOR_DIR)), 1)

    def test_textual_imports_from_vendor(self):
        import textual

        self.assertTrue(str(textual.__file__).startswith(str(bootstrap.VENDOR_DIR)))


class LauncherLogTest(unittest.TestCase):
    """LN5, LN6: pre-log failures go to logs/suite/launcher.log; the suite trims it at start."""

    NOW = datetime(2026, 11, 4, 14, 3, 22)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.log = self.tmp / "logs" / "suite" / "launcher.log"

    def test_launcher_log_sits_beside_the_suite_log(self):
        self.assertEqual(bootstrap.LAUNCHER_LOG, bootstrap.REPO_ROOT / "logs" / "suite" / "launcher.log")

    def test_bootstrap_failure_appends_a_line(self):
        bootstrap.log_bootstrap_failure("python_check", "needs Python 3.10", path=self.log, now=self.NOW)
        bootstrap.log_bootstrap_failure("python_check", "again", path=self.log, now=self.NOW)
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} ")
        self.assertIn("bootstrap.failed where=python_check message=needs Python 3.10", lines[0])

    def test_bootstrap_failure_of_an_exception_adds_type_and_traceback(self):
        try:
            raise ValueError("bad\nthing")
        except ValueError as exc:
            bootstrap.log_bootstrap_failure("startup", exc, path=self.log, now=self.NOW)
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertIn("bootstrap.failed where=startup type=ValueError message=bad | thing", lines[0])
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(len(lines), 11)
        self.assertTrue(all(line.startswith(" ") for line in lines[1:]))

    def test_bootstrap_failure_never_raises(self):
        blocker = self.tmp / "a-file"
        blocker.write_text("x", encoding="utf-8")
        self.assertIsNone(bootstrap.log_bootstrap_failure("lock", "x", path=blocker / "suite" / "launcher.log"))

    def _write(self, *lines):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_bytes("".join(line + "\r\n" for line in lines).encode("utf-8"))

    def test_trim_drops_old_lines_keeps_recent(self):
        self._write("2026-01-01T10:00:00 bootstrap.failed where=lock message=old",
                    "    Traceback line of the old record",
                    "Thu 01/02/2026 10:00:00.00 launcher.started args= python=py -3",
                    "20.07.2026 10:00:00,00 launcher.exited code=0",
                    "2026-11-01T10:00:00 bootstrap.failed where=lock message=recent",
                    "    Traceback line of the recent record",
                    "Wed 11/04/2026 14:00:00.00 launcher.started args= python=py -3",
                    "04.11.2026 14:00:00,00 launcher.exited code=0",
                    "2026/11/03 09:00:00.00 launcher.exited code=1")
        bootstrap.trim_launcher_log(self.log, 30, self.NOW)
        kept = self.log.read_bytes().decode("utf-8").split("\r\n")[:-1]
        self.assertEqual(kept, ["2026-11-01T10:00:00 bootstrap.failed where=lock message=recent",
                                "    Traceback line of the recent record",
                                "Wed 11/04/2026 14:00:00.00 launcher.started args= python=py -3",
                                "04.11.2026 14:00:00,00 launcher.exited code=0",
                                "2026/11/03 09:00:00.00 launcher.exited code=1"])

    def test_trim_keeps_a_day_month_order_that_could_be_recent(self):
        # 03/11/2026 is 3 November (recent) or 11 March (old): kept, since one reading is inside retention.
        self._write("03/11/2026 10:00:00.00 launcher.started args=")
        bootstrap.trim_launcher_log(self.log, 30, self.NOW)
        self.assertIn(b"03/11/2026", self.log.read_bytes())

    def test_trim_without_dates_keeps_last_2000(self):
        self._write(*[f"Line {n} launcher.started" for n in range(2500)])
        bootstrap.trim_launcher_log(self.log, 30, self.NOW)
        kept = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(kept), 2000)
        self.assertEqual(kept[0], "Line 500 launcher.started")
        self.assertEqual(kept[-1], "Line 2499 launcher.started")

    def test_trim_leaves_an_unchanged_file_alone_and_never_raises(self):
        self._write("2026-11-01T10:00:00 launcher.exited code=0")
        before = self.log.stat().st_mtime_ns
        bootstrap.trim_launcher_log(self.log, 30, self.NOW)
        self.assertEqual(self.log.stat().st_mtime_ns, before)
        self.assertIsNone(bootstrap.trim_launcher_log(self.tmp / "missing.log", 30, self.NOW))
        self.assertIsNone(bootstrap.trim_launcher_log(self.tmp, 30, self.NOW))  # a folder, not a file
