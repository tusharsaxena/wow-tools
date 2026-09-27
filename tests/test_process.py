import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from wowtools.core.process import names_in_tasklist, running_wow_executables

TASKLIST = ('"System Idle Process","0","Services","0","8 K"\n'
            '"Wow.exe","1234","Console","1","1,234,567 K"\n'
            '"WowClassicHelper.exe","99","Console","1","10 K"\n')


class ProcessTest(unittest.TestCase):
    def test_parses_tasklist_csv(self):
        self.assertEqual(names_in_tasklist(TASKLIST), ["Wow.exe"])
        self.assertEqual(names_in_tasklist('"explorer.exe","1","Console","1","5 K"\n'), [])

    def test_tasklist_runner(self):
        runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=TASKLIST)
        self.assertEqual(running_wow_executables(use_tasklist=True, runner=runner), ["Wow.exe"])

    def test_tasklist_failure_is_unknown(self):
        def broken(*a, **k):
            raise FileNotFoundError("tasklist.exe")
        self.assertIsNone(running_wow_executables(use_tasklist=True, runner=broken))

        def timeout(*a, **k):
            raise subprocess.TimeoutExpired("tasklist", 5)
        self.assertIsNone(running_wow_executables(use_tasklist=True, runner=timeout))

    def test_proc_scan_for_wine(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / "123").mkdir()
            (proc / "123" / "comm").write_text("WowClassic.exe\n")
            (proc / "456").mkdir()
            (proc / "456" / "comm").write_text("bash\n")
            self.assertEqual(running_wow_executables(use_tasklist=False, proc_root=proc), ["WowClassic.exe"])
