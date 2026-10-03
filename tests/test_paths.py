from __future__ import annotations

import unittest
from pathlib import Path

from wowtools.core.paths import to_native, to_stored, win_to_wsl, wsl_to_win


class TranslateTest(unittest.TestCase):
    def test_win_to_wsl(self):
        self.assertEqual(win_to_wsl(r"G:\Games\Blizzard\World of Warcraft"), "/mnt/g/Games/Blizzard/World of Warcraft")
        self.assertEqual(win_to_wsl("c:/Program Files (x86)/World of Warcraft/"), "/mnt/c/Program Files (x86)/World of Warcraft")
        self.assertEqual(win_to_wsl("D:\\"), "/mnt/d")
        self.assertIsNone(win_to_wsl("/home/user/wow"))
        self.assertIsNone(win_to_wsl(r"\\server\share"))

    def test_wsl_to_win(self):
        self.assertEqual(wsl_to_win("/mnt/g/Games/Blizzard/World of Warcraft"), r"G:\Games\Blizzard\World of Warcraft")
        self.assertEqual(wsl_to_win("/mnt/d/"), "D:\\")
        self.assertIsNone(wsl_to_win("/home/user/wow"))
        self.assertIsNone(wsl_to_win("/mnt/data/x"))

    def test_to_native_under_wsl(self):
        self.assertEqual(to_native(r"G:\WoW", wsl=True), Path("/mnt/g/WoW"))
        self.assertEqual(to_native("/home/me/wow", wsl=True), Path("/home/me/wow"))

    def test_to_stored_under_wsl(self):
        self.assertEqual(to_stored("/mnt/g/WoW", wsl=True), r"G:\WoW")
        self.assertEqual(to_stored("/home/me/wow", wsl=True), "/home/me/wow")

    def test_no_translation_off_wsl(self):
        self.assertEqual(to_stored("/mnt/g/WoW", wsl=False), "/mnt/g/WoW")
        self.assertEqual(to_native("/home/me/wow", wsl=False), Path("/home/me/wow"))
