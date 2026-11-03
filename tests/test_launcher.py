"""wow-tools.cmd must be safe to replace while it runs (F-020): cmd.exe reads a batch file by byte offset, so after
Python returns it must not read another line from the (possibly updated) file. It also checks for a usable Python,
logs every launch to logs/suite/launcher.log and keeps a double-clicked window open on failure (LN1, LN2, LN4).
wow-tools.sh does the same check and logging, and its whole body is parsed before Python starts (LN2, LN4, LN8)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from wowtools.core.bootstrap import REPO_ROOT, _line_dates

LAUNCHER = REPO_ROOT / "wow-tools.cmd"
SH_LAUNCHER = REPO_ROOT / "wow-tools.sh"
PAUSE_PROMPT = "Press any key to close this window."  # the launcher's own prompt (pause's own text is localised)

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
        _start, _, rest = line.partition("-m wowtools %*")
        self.assertTrue(rest, "the arguments must be passed on")
        # The exit is on the same (already parsed) line, with the code read when it runs: %ERRORLEVEL% would be
        # expanded when the line is parsed, before Python ran.
        self.assertIn("& exit /b ", rest)
        self.assertNotIn("%ERRORLEVEL%", rest.replace("%%ERRORLEVEL%%", ""))
        exit_code = rest.rsplit("exit /b", 1)[1].strip()
        self.assertTrue(exit_code.startswith("!") and exit_code.endswith("!"), exit_code)
        self.assertIn("EnableDelayedExpansion", rest)

    def test_last_line_logs_the_exit_and_pauses_before_exiting(self):
        lines = [line for line in _lines() if not line.lower().startswith(("rem ", "@rem "))]
        rest = lines[-1].partition("-m wowtools %*")[2]
        self.assertIn("launcher.exited code=!WOWTOOLS_RC!", rest)
        self.assertIn("if defined WOWTOOLS_DBLCLICK", rest)
        self.assertLess(rest.index("launcher.exited"), rest.index("pause"))
        self.assertLess(rest.index("pause"), rest.rindex("& exit /b "))
        # The log path holds the app folder, which may contain "!": it must be read with delayed expansion, never
        # %expanded% into a command that runs with delayed expansion on.
        self.assertNotIn("%WOWTOOLS_LOG%", rest)

    def test_python_is_checked_before_the_run(self):
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertLess(text.index("sys.version_info >= (3, 10)"), text.index("-m wowtools %*"))
        for event in ("launcher.started", "launcher.python_missing", "launcher.python_too_old"):
            self.assertLess(text.index(event), text.index("-m wowtools %*"), event)
        self.assertIn("Installing Python", text)

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

    def run_launcher(self, *args: str, command: list[str] | None = None, path: str | None = None,
                     extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        """Run the copy as Explorer does (cmd /c with the script's name), or `command` when given. stdin is a key
        press, so a pause never waits."""
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        if path is not None:
            env["PATH"] = path
        env.update(extra_env or {})
        command = command or ["cmd.exe", "/d", "/c", str(self.dir / "wow-tools.cmd"), *args]
        return subprocess.run(command, cwd=self.dir, input="x\n", capture_output=True, text=True, timeout=120,
                              env=env, check=False)

    def launcher_log(self) -> list[str]:
        log = self.dir / "logs" / "suite" / "launcher.log"
        return log.read_text(encoding="utf-8", errors="replace").splitlines() if log.is_file() else []

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

    def test_double_click_pauses_on_failure(self):
        proc = self.run_launcher("3")
        self.assertIn("fake app ran", proc.stdout)
        self.assertIn(PAUSE_PROMPT, proc.stdout)
        self.assertEqual(proc.returncode, 3, proc.stderr)

    def test_double_click_success_does_not_pause(self):
        proc = self.run_launcher("0")
        self.assertIn("fake app ran", proc.stdout)
        self.assertNotIn(PAUSE_PROMPT, proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_terminal_run_does_not_pause(self):
        # From an open terminal, cmd.exe's command line does not name the script: here it only holds a variable.
        proc = self.run_launcher(command=["cmd.exe", "/d", "/c", "call %WOWTOOLS_TEST_SCRIPT% 3"],
                                 extra_env={"WOWTOOLS_TEST_SCRIPT": str(self.dir / "wow-tools.cmd")})
        self.assertIn("fake app ran", proc.stdout)
        self.assertNotIn(PAUSE_PROMPT, proc.stdout)
        self.assertEqual(proc.returncode, 3, proc.stderr)

    def test_launch_and_exit_logged(self):
        self.run_launcher("3")
        lines = self.launcher_log()
        started = [line for line in lines if " launcher.started " in line]
        exited = [line for line in lines if " launcher.exited " in line]
        self.assertEqual(len(started), 1, lines)
        self.assertEqual(len(exited), 1, lines)
        self.assertIn("python=", started[0])
        self.assertIn("platform=windows", started[0])
        self.assertTrue(started[0].endswith("args=3"), started[0])
        self.assertTrue(exited[0].rstrip().endswith("launcher.exited code=3"), exited[0])
        # The trim (core/bootstrap.py) must be able to read the date cmd.exe wrote.
        for line in started + exited:
            self.assertIsNotNone(_line_dates(line.encode()), line)

    def test_unwritable_log_folder_is_silent(self):
        (self.dir / "logs").write_text("a file where the folder should be")
        proc = self.run_launcher("3")
        self.assertIn("fake app ran", proc.stdout)
        self.assertEqual(proc.stderr.strip(), "")
        self.assertEqual(proc.returncode, 3)

    def test_missing_python_message(self):
        system32 = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
        proc = self.run_launcher("0", path=system32)
        self.assertNotIn("fake app ran", proc.stdout)
        self.assertIn("Installing Python", proc.stdout)
        self.assertIn(PAUSE_PROMPT, proc.stdout)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "")
        lines = self.launcher_log()
        self.assertTrue(any(" launcher.python_missing" in line for line in lines), lines)
        self.assertTrue(any(f"launcher.exited code={proc.returncode}" in line for line in lines), lines)

    def test_old_python_message(self):
        # A stand-in "python" that is too old: it fails the version check (exit 3) and reports 3.8 when asked.
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "python.bat").write_bytes(b"@echo 3.8\r\n@exit /b 3\r\n")
        system32 = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
        proc = self.run_launcher("0", path=f"{system32};{bin_dir}")
        self.assertNotIn("fake app ran", proc.stdout)
        self.assertIn("is Python 3.8.", proc.stdout)
        self.assertIn("Installing Python", proc.stdout)
        self.assertIn(PAUSE_PROMPT, proc.stdout)
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertEqual(proc.stderr.strip(), "")
        lines = self.launcher_log()
        self.assertTrue(any(" launcher.python_too_old found=3.8 " in line for line in lines), lines)
        self.assertTrue(any(line.rstrip().endswith("launcher.exited code=3") for line in lines), lines)


# The POSIX launcher's stand-in: optionally replaces wow-tools.sh with lines that would show up if the shell read on
# from its old offset after Python returned, then exits with the code given as its last argument.
FAKE_SH_MAIN = """
import pathlib, sys
launcher = pathlib.Path(__file__).resolve().parents[1] / "wow-tools.sh"
if "rewrite" in sys.argv:
    launcher.write_bytes(b"echo REREAD; exit 99\\n" * 400)
print("fake app ran")
sys.exit(int(sys.argv[-1]))
"""


def _sh_lines() -> list[str]:
    return [line.strip() for line in SH_LAUNCHER.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")]


class ShLauncherStructureTest(unittest.TestCase):
    def test_sh_body_parsed_before_running(self):
        """The commands sit in one function called on the last line, with the exit on that same line: the shell
        has parsed the whole body before Python starts, so an update may replace the file meanwhile (LN8)."""
        lines = _sh_lines()
        self.assertEqual(lines[0], "main() {")
        self.assertEqual(lines[-2], "}")
        self.assertEqual(lines[-1], 'main "$@"; exit $?')
        self.assertEqual(sum("-m wowtools" in line for line in lines), 1)
        # No exec: the launcher must still be there after Python returns, to log the exit code.
        self.assertFalse(any(line.startswith("exec ") or " exec " in line for line in lines), lines)

    def test_sh_checks_python_and_logs(self):
        text = SH_LAUNCHER.read_text(encoding="utf-8")
        self.assertLess(text.index("sys.version_info >= (3, 10)"), text.index("-m wowtools"))
        for event in ("launcher.started", "launcher.python_missing", "launcher.python_too_old"):
            self.assertLess(text.index(event), text.index("-m wowtools"), event)
        self.assertIn("launcher.exited", text)
        self.assertIn("Installing Python", text)

    def test_sh_lf_line_endings(self):
        self.assertNotIn(b"\r", SH_LAUNCHER.read_bytes())


@unittest.skipIf(sys.platform == "win32" or shutil.which("sh") is None, "runs sh (POSIX only)")
class ShLauncherTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        shutil.copy(SH_LAUNCHER, self.dir / "wow-tools.sh")
        (self.dir / "wowtools").mkdir()
        (self.dir / "wowtools" / "__init__.py").write_text("")
        (self.dir / "wowtools" / "__main__.py").write_text(FAKE_SH_MAIN)

    def tool_dir(self, *, python3: str | None = None) -> str:
        """A PATH folder holding only the tools the launcher uses, plus `python3` when given (a script's text)."""
        bin_dir = self.dir / "bin"
        bin_dir.mkdir(exist_ok=True)
        for tool in ("dirname", "date", "mkdir", "uname"):
            found = shutil.which(tool)
            self.assertIsNotNone(found, tool)
            os.symlink(found, bin_dir / tool)
        if python3 is not None:
            fake = bin_dir / "python3"
            fake.write_text(python3)
            fake.chmod(0o755)
        return str(bin_dir)

    def run_launcher(self, *args: str, path: str | None = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        if path is not None:
            env["PATH"] = path
        sh = shutil.which("sh")
        return subprocess.run([sh, str(self.dir / "wow-tools.sh"), *args], cwd=self.dir, capture_output=True,
                              text=True, timeout=120, env=env, check=False)

    def launcher_log(self) -> list[str]:
        log = self.dir / "logs" / "suite" / "launcher.log"
        return log.read_text(encoding="utf-8", errors="replace").splitlines() if log.is_file() else []

    def test_sh_exit_code_is_passed_on(self):
        for code in ("0", "1", "10"):
            proc = self.run_launcher(code)
            self.assertIn("fake app ran", proc.stdout)
            self.assertEqual(proc.returncode, int(code), proc.stderr)

    def test_sh_logs_start_and_exit(self):
        proc = self.run_launcher("3")
        self.assertEqual(proc.returncode, 3, proc.stderr)
        lines = self.launcher_log()
        started = [line for line in lines if " launcher.started " in line]
        exited = [line for line in lines if " launcher.exited " in line]
        self.assertEqual(len(started), 1, lines)
        self.assertEqual(len(exited), 1, lines)
        self.assertIn("python=python3", started[0])
        self.assertIn("platform=", started[0])
        self.assertTrue(started[0].endswith("args=3"), started[0])
        self.assertTrue(exited[0].endswith("launcher.exited code=3"), exited[0])
        for line in started + exited:
            self.assertIsNotNone(_line_dates(line.encode()), line)

    def test_sh_rewritten_while_running(self):
        proc = self.run_launcher("rewrite", "3")
        self.assertIn("fake app ran", proc.stdout)
        self.assertNotIn("REREAD", proc.stdout)
        self.assertEqual(proc.stderr.strip(), "")
        self.assertEqual(proc.returncode, 3)
        self.assertTrue((self.dir / "wow-tools.sh").read_bytes().startswith(b"echo REREAD"))

    def test_sh_unwritable_log_folder_is_silent(self):
        (self.dir / "logs").write_text("a file where the folder should be")
        proc = self.run_launcher("3")
        self.assertIn("fake app ran", proc.stdout)
        self.assertEqual(proc.stderr.strip(), "")
        self.assertEqual(proc.returncode, 3)

    def test_sh_missing_python3(self):
        proc = self.run_launcher("0", path=self.tool_dir())
        self.assertNotIn("fake app ran", proc.stdout)
        self.assertIn("Installing Python", proc.stdout + proc.stderr)
        self.assertEqual(proc.returncode, 127)
        lines = self.launcher_log()
        self.assertTrue(any(" launcher.python_missing" in line for line in lines), lines)
        self.assertTrue(any(line.endswith("launcher.exited code=127") for line in lines), lines)

    def test_sh_old_python3(self):
        # A stand-in python3 that is too old: it fails the version check (exit 3) and reports 3.8 when asked.
        proc = self.run_launcher("0", path=self.tool_dir(python3="#!/bin/sh\necho 3.8\nexit 3\n"))
        self.assertNotIn("fake app ran", proc.stdout)
        self.assertIn("is Python 3.8.", proc.stdout + proc.stderr)
        self.assertIn("Installing Python", proc.stdout + proc.stderr)
        self.assertEqual(proc.returncode, 3)
        lines = self.launcher_log()
        self.assertTrue(any(" launcher.python_too_old found=3.8 " in line for line in lines), lines)
        self.assertTrue(any(line.endswith("launcher.exited code=3") for line in lines), lines)
