from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from wowtools.core.install import Flavor
from wowtools.core.process import (WowProcess, names_in_tasklist, processes_for_flavor, running_wow_executables,
                                   running_wow_processes, wow_check_for, wow_name)

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


MAC_PS = ("/sbin/launchd\n"
          "/Applications/World of Warcraft/_retail_/World of Warcraft.app/Contents/MacOS/World of Warcraft\n"
          "/Applications/World of Warcraft/_classic_era_/World of Warcraft Classic.app/Contents/MacOS/"
          "World of Warcraft Classic\n"
          "  /Volumes/Games/WoW/_beta_/World of Warcraft Beta.app/Contents/MacOS/World of Warcraft Beta  \n"
          "/Applications/World of Warcraft/World of Warcraft Launcher.app/Contents/MacOS/World of Warcraft Launcher\n"
          "World of Warcraft\n"
          "/Users/u/wine/_retail_/Wow.exe\n"
          "/usr/bin/bash\n")
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

    def test_mac_ps_listing(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return ok(MAC_PS)
        procs = running_wow_processes(platform="mac", runner=runner)
        self.assertEqual(procs, [
            WowProcess("World of Warcraft", "/Applications/World of Warcraft/_retail_/World of Warcraft.app"),
            WowProcess("World of Warcraft Classic",
                       "/Applications/World of Warcraft/_classic_era_/World of Warcraft Classic.app"),
            WowProcess("World of Warcraft Beta", "/Volumes/Games/WoW/_beta_/World of Warcraft Beta.app"),
            WowProcess("World of Warcraft", None),
            WowProcess("Wow.exe", "/Users/u/wine/_retail_/Wow.exe"),
        ])
        cmd, kwargs = calls[0]
        self.assertEqual(cmd, ["ps", "-axww", "-o", "comm="])
        self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)
        self.assertEqual(kwargs.get("timeout"), 5)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(processes_for_flavor(procs, "_retail_"), (
            [procs[0], procs[4]], [procs[3]]))
        self.assertEqual(processes_for_flavor(procs, "_classic_era_")[0], [procs[1]])
        retail = Flavor("_retail_", Path("/Applications/World of Warcraft/_retail_"))
        self.assertEqual(wow_check_for(retail, lister=lambda: procs)(),
                         ["World of Warcraft", "Wow.exe", "World of Warcraft (flavor unknown)"])

    def test_mac_truncated_path_is_missed_hence_ww(self):
        # Why the command passes -ww: a path cut to ps's default 79 columns no longer names the executable.
        path = "/Applications/World of Warcraft/_retail_/World of Warcraft.app/Contents/MacOS/World of Warcraft"
        self.assertEqual(len(path), 95)
        self.assertEqual(running_wow_processes(platform="mac", runner=lambda *a, **k: ok(path[:79] + "\n")), [])
        self.assertEqual(len(running_wow_processes(platform="mac", runner=lambda *a, **k: ok(path + "\n"))), 1)

    def test_mac_wine_exe_inside_wrapper_app(self):
        path = ("/Users/u/Applications/Wineskin/WoW.app/Contents/Resources/drive_c/Program Files/World of Warcraft/"
                "_retail_/Wow.exe")
        procs = running_wow_processes(platform="mac", runner=lambda *a, **k: ok(path + "\n"))
        self.assertEqual(procs, [WowProcess("Wow.exe", path)])
        self.assertEqual(processes_for_flavor(procs, "_retail_"), (procs, []))

    def test_mac_no_wow_running(self):
        listing = "/sbin/launchd\n/Applications/Battle.net.app/Contents/MacOS/Battle.net\n"
        self.assertEqual(running_wow_processes(platform="mac", runner=lambda *a, **k: ok(listing)), [])

    def test_mac_ps_failure_is_unknown(self):
        def missing(*a, **k):
            raise FileNotFoundError("ps")

        def timeout(*a, **k):
            raise subprocess.TimeoutExpired("ps", 5)
        for runner in (missing, timeout, lambda *a, **k: SimpleNamespace(returncode=1, stdout="")):
            self.assertIsNone(running_wow_processes(platform="mac", runner=runner))

    def test_one_name_rule(self):
        self.assertEqual(wow_name("wow.exe"), "Wow.exe")
        self.assertEqual(wow_name("World of Warcraft"), "World of Warcraft")
        self.assertEqual(wow_name("World of Warcraft Classic PTR"), "World of Warcraft Classic PTR")
        # an unlisted variant still counts: better a needless warning than a missed client
        for variant in ("World of Warcraft Experimental", "World of Warcraft Anniversary"):
            self.assertEqual(wow_name(variant), variant)
        for other in ("World of Warcraft Launcher", "World of Warcraft Helper", "World of Warcraft Crash Reporter",
                      "World of WarcraftX", "WowClassicHelper.exe", "Battle.net", ""):
            self.assertIsNone(wow_name(other), other)

    def test_wow_check_for(self):
        retail = Flavor("_retail_", Path("/wow/_retail_"))
        beta = running_wow_processes(platform="wsl", runner=lambda *a, **k: ok(BETA_PS))
        self.assertEqual(wow_check_for(retail, lister=lambda: beta)(), [])
        mixed = beta + [WowProcess("WowClassic.exe", None), WowProcess("Wow.exe", "C:\\x\\_retail_\\Wow.exe")]
        self.assertEqual(wow_check_for(retail, lister=lambda: mixed)(),
                         ["Wow.exe", "WowClassic.exe (flavor unknown)"])
        self.assertIsNone(wow_check_for(retail, lister=lambda: None)())

    def test_wow_check_for_several_flavors_lists_processes_once(self):
        retail = Flavor("_retail_", Path("/wow/_retail_"))
        era = Flavor("_classic_era_", Path("/wow/_classic_era_"))
        procs = [WowProcess("Wow.exe", "C:\\x\\_retail_\\Wow.exe"),
                 WowProcess("WowClassic.exe", "C:\\x\\_classic_era_\\WowClassic.exe"),
                 WowProcess("WowClassic.exe", "C:\\x\\_classic_\\WowClassic.exe"),
                 WowProcess("WowB.exe", None)]
        calls = []

        def lister():
            calls.append(1)
            return procs
        self.assertEqual(wow_check_for([retail, era], lister=lister)(),
                         ["Wow.exe", "WowClassic.exe", "WowB.exe (flavor unknown)"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(wow_check_for([era], lister=lambda: procs)(),
                         ["WowClassic.exe", "WowB.exe (flavor unknown)"])

    def test_unknown_processes_listed_once_for_many_flavors(self):
        retail = Flavor("_retail_", Path("/wow/_retail_"))
        era = Flavor("_classic_era_", Path("/wow/_classic_era_"))
        procs = [WowProcess("Wow.exe", None)]
        self.assertEqual(wow_check_for([retail, era], lister=lambda: procs)(), ["Wow.exe (flavor unknown)"])

    def test_unknown_processes_do_not_depend_on_the_flavors(self):
        # F-025: unknown used to be whatever the last folder's call returned, so no folders meant none.
        procs = [WowProcess("Wow.exe", None)]
        self.assertEqual(wow_check_for([], lister=lambda: procs)(), ["Wow.exe (flavor unknown)"])
