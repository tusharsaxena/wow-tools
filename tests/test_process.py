import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from wowtools.core.install import Flavor
from wowtools.core.process import (WowProcess, names_in_tasklist, processes_for_flavor, running_wow_executables,
                                   running_wow_processes, wow_check_for)

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


BETA_PS = "WowB.exe|G:\\Games\\Blizzard\\World of Warcraft\\_classic_beta_\\WowB.exe\r\n"


def ok(stdout):
    return SimpleNamespace(returncode=0, stdout=stdout)


class WowProcessTest(unittest.TestCase):
    def test_parses_powershell_output(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return ok(BETA_PS)
        procs = running_wow_processes(platform="wsl", runner=runner)
        self.assertEqual(len(procs), 1)
        self.assertEqual(procs[0].name, "WowB.exe")
        self.assertTrue(procs[0].path.endswith("_classic_beta_\\WowB.exe"), procs[0].path)
        cmd, kwargs = calls[0]
        self.assertEqual(cmd[0], "powershell.exe")
        self.assertIn("-NoProfile", cmd)
        self.assertIn("-NonInteractive", cmd)
        self.assertIn("Win32_Process", cmd[-1])
        self.assertEqual(kwargs.get("timeout"), 10)

    def test_windows_uses_plain_powershell(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            return ok("")
        self.assertEqual(running_wow_processes(platform="windows", runner=runner), [])
        self.assertEqual(calls[0][0], "powershell")

    def test_matching_by_parent_folder(self):
        beta = running_wow_processes(platform="wsl", runner=lambda *a, **k: ok(BETA_PS))
        self.assertEqual(processes_for_flavor(beta, "_classic_beta_"), (beta, []))
        self.assertEqual(processes_for_flavor(beta, "_classic_era_"), ([], []))
        self.assertEqual(processes_for_flavor(beta, "_CLASSIC_BETA_"), (beta, []))
        linux = [WowProcess("Wow.exe", "/home/u/Games/wow/_retail_/Wow.exe")]
        self.assertEqual(processes_for_flavor(linux, "_retail_"), (linux, []))
        unknown = [WowProcess("WowClassic.exe", None)]
        self.assertEqual(processes_for_flavor(unknown + linux, "_retail_"), (linux, unknown))

    def test_powershell_failure_falls_back_to_tasklist(self):
        def runner(cmd, **kwargs):
            if cmd[0].startswith("powershell"):
                raise FileNotFoundError(cmd[0])
            return ok(TASKLIST)
        self.assertEqual(running_wow_processes(platform="wsl", runner=runner), [WowProcess("Wow.exe", None)])

        def nonzero(cmd, **kwargs):
            if cmd[0].startswith("powershell"):
                return SimpleNamespace(returncode=1, stdout="")
            return ok(TASKLIST)
        self.assertEqual(running_wow_processes(platform="windows", runner=nonzero), [WowProcess("Wow.exe", None)])

        def broken(*a, **k):
            raise subprocess.TimeoutExpired("x", 10)
        self.assertIsNone(running_wow_processes(platform="wsl", runner=broken))

    def test_linux_proc_cmdline(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / "123").mkdir()
            (proc / "123" / "cmdline").write_bytes(b"Z:\\wow\\_retail_\\Wow.exe\x00-arg\x00")
            (proc / "456").mkdir()
            (proc / "456" / "cmdline").write_bytes(b"/usr/bin/bash\x00")
            (proc / "self").mkdir()
            procs = running_wow_processes(platform="linux", proc_root=proc)
            self.assertEqual(procs, [WowProcess("Wow.exe", "Z:\\wow\\_retail_\\Wow.exe")])
            self.assertEqual(processes_for_flavor(procs, "_retail_"), (procs, []))

    def test_mac_is_unknown(self):
        self.assertIsNone(running_wow_processes(platform="mac"))

    def test_wow_check_for(self):
        retail = Flavor("_retail_", Path("/wow/_retail_"))
        beta = running_wow_processes(platform="wsl", runner=lambda *a, **k: ok(BETA_PS))
        self.assertEqual(wow_check_for(retail, lister=lambda: beta)(), [])
        mixed = beta + [WowProcess("WowClassic.exe", None), WowProcess("Wow.exe", "C:\\x\\_retail_\\Wow.exe")]
        self.assertEqual(wow_check_for(retail, lister=lambda: mixed)(),
                         ["Wow.exe", "WowClassic.exe (flavor unknown)"])
        self.assertIsNone(wow_check_for(retail, lister=lambda: None)())
