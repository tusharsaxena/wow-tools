from __future__ import annotations

import unittest
from datetime import date

from wowtools.tools.screenshot_organizer.naming import day_parts, parse_shot_name


class NamingTest(unittest.TestCase):
    def test_valid_names(self):
        self.assertEqual(parse_shot_name("WoWScrnShot_073119_232713.jpg"), date(2019, 7, 31))
        self.assertEqual(parse_shot_name("WoWScrnShot_010224_000001.tga"), date(2024, 1, 2))
        self.assertEqual(parse_shot_name("wowscrnshot_080119_101010.PNG"), date(2019, 8, 1))
        self.assertEqual(parse_shot_name("WoWScrnShot_123199_235959.jpeg"), date(2099, 12, 31))

    def test_invalid_names(self):
        for name in ("WoWScrnShot_023119_120000.jpg",   # 31 February
                     "WoWScrnShot_133119_120000.jpg",   # month 13
                     "WoWScrnShot_073119_232713.gif",
                     "WoWScrnShot_073119.jpg", "WoWScrnShot_07311_232713.jpg",
                     "copy of WoWScrnShot_073119_232713.jpg", "WoWScrnShot_073119_232713.jpg.bak",
                     "notes.txt", ""):
            self.assertIsNone(parse_shot_name(name), name)

    def test_day_parts(self):
        self.assertEqual(day_parts(date(2019, 7, 3)), ("2019", "07", "03"))
