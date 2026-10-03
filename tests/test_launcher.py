"""wow-tools.cmd must be safe to replace while it runs (F-020): cmd.exe reads a batch file by byte offset, so after
Python returns it must not read another line from the (possibly updated) file."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from wowtools.core.bootstrap import REPO_ROOT

LAUNCHER = REPO_ROOT / "wow-tools.cmd"

# A stand-in for the real package: optionally rewrites the launcher while "running" (as a zip update does),
# then exits with the code given as its last argument.
FAKE_MAIN = '''
import pathlib, sys
launcher = pathlib.Path(__file__).resolve().parents[1] / "wow-tools.cmd"
if "rewrite" in sys.argv:
    launcher.write_bytes(b"@rem " + b"x" * 200 + b"\\r\\n" + launcher.read_bytes())
print("fake app ran")
sys.exit(int(sys.argv[-1]))
'''


def _lines() -> list[str]:
    return [line.strip() for line in LAUNCHER.read_text(encoding="utf-8").splitlines() if line.strip()]


class LauncherStructureTest(unittest.TestCase):
    def test_python_runs_on_the_last_line_with_its_exit(self):
        lines = [line for line in _lines() if not line.lower().startswith(("rem ", "@rem "))]
        runs = [i for i, line in enumerate(lines) if "-m wowtools" in line]
        self.assertEqual(len(runs), 1, "Python must be started from exactly one line")
        self.assertEqual(runs[0], len(lines) - 1, "nothing may follow the line that starts Python")
        line = lines[runs[0]]
        start, _, rest = line.partition("-m wowtools %*")
        self.assertTrue(rest, "the arguments must be passed on")
        # The exit is on the same (already parsed) line, with the code read when it runs: %ERRORLEVEL% would be
        # expanded when the line is parsed, before Python ran.
        self.assertIn("& exit /b ", rest)
        self.assertNotIn("%ERRORLEVEL%", rest.replace("%%ERRORLEVEL%%", ""))
        exit_code = rest.rsplit("exit /b", 1)[1].strip()
        self.assertTrue(exit_code.startswith("!") and exit_code.endswith("!"), exit_code)
        self.assertIn("EnableDelayedExpansion", rest)

    def test_crlf_line_endings(self):
        data = LAUNCHER.read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))


@unittest.skipUnless(sys.platform == "win32", "runs cmd.exe (Windows only; the Windows CI job runs it)")
class LauncherOnWindowsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        shutil.copy(LAUNCHER, self.dir / "wow-tools.cmd")
        (self.dir / "wowtools").mkdir()
        (self.dir / "wowtools" / "__init__.py").write_text("")
        (self.dir / "wowtools" / "__main__.py").write_text(FAKE_MAIN)

    def run_launcher(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run(["cmd.exe", "/d", "/c", str(self.dir / "wow-tools.cmd"), *args], cwd=self.dir,
                              capture_output=True, text=True, timeout=120, env=env)

    def test_exit_code_is_passed_on(self):
        for code in ("0", "1", "10"):
            proc = self.run_launcher(code)
            self.assertIn("fake app ran", proc.stdout)
            self.assertEqual(proc.returncode, int(code), proc.stderr)

    def test_rewritten_while_running(self):
        proc = self.run_launcher("rewrite", "3")
        self.assertIn("fake app ran", proc.stdout)
        self.assertEqual(proc.stderr.strip(), "")
        self.assertEqual(proc.returncode, 3)
        self.assertTrue((self.dir / "wow-tools.cmd").read_bytes().startswith(b"@rem xxx"))
