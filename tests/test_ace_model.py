"""model: which top-level SavedVariables are AceDB databases, and what they hold (spec §2, §5.2)."""
from __future__ import annotations

import unittest

from wowtools.core import luasv
from wowtools.tools.ace3_profile_manager import model

NL = b"\r\n"


def lua(*lines: str) -> bytes:
    return NL + NL.join(line.encode("utf-8") for line in lines) + NL


ELV = lua(
    'ElvDB = {',
    '["profileKeys"] = {', '["Kaelys - Mug\'thol"] = "Default",', '["Alt - Khaz Modan"] = "Default",', '},',
    '["profiles"] = {', '["Default"] = {', '["scale"] = 1,', '},', '["Old"] = {', '},', '},',
    '["namespaces"] = {',
    '["Bags"] = {', '["profiles"] = {', '["Default"] = {', '["x"] = 1,', '},', '["Old"] = {', '},', '},', '},',
    '["LibDualSpec-1.0"] = {', '["char"] = {',
    '["Kaelys - Mug\'thol"] = {', '["enabled"] = true,', '[1] = "Default",', '[2] = "Old",', '},',
    '},', '},',
    '},',
    '["global"] = {', '["schemaVersion"] = 3,', '},',
    '}',
    'ElvPrivateDB = {',
    '["profileKeys"] = {', '["Kaelys - Mug\'thol"] = "Kaelys - Mug\'thol",', '},',
    '["profiles"] = {', '["Kaelys - Mug\'thol"] = {', '["a"] = 1,', '},', '},',
    '}',
    'ElvPerfDB = {', '["runs"] = 1,', '}',
    'Memento = {', '["profileKeys"] = {', '["Player-3725-0A"] = {', '},', '},', '}',
    'HidingBar = {', '["profileKeys"] = {', '["A - B"] = "x",', '},', '["profiles"] = {', '"one",', '},', '}',
    'Stock = {', '["profileKeys"] = {', '["A - B"] = "Gone",', '},', '}',
)


def dbs(data: bytes):
    return model.find_dbs(luasv.parse(data, model.ace_descend), data)


class FindDbsTest(unittest.TestCase):
    def test_finds_only_acedb_databases(self):
        found, notes = dbs(ELV)
        self.assertEqual([db.sv_name for db in found], ["ElvDB", "ElvPrivateDB", "Stock"])
        self.assertEqual(len(notes), 2)
        self.assertTrue(any("Memento" in n for n in notes))
        self.assertTrue(any("HidingBar" in n for n in notes))

    def test_mapping_profiles_users(self):
        elv = dbs(ELV)[0][0]
        self.assertEqual(elv.profile_keys, {"Kaelys - Mug'thol": "Default", "Alt - Khaz Modan": "Default"})
        self.assertEqual(list(elv.profiles), ["Default", "Old"])
        self.assertEqual(elv.users("Default"), ["Kaelys - Mug'thol", "Alt - Khaz Modan"])
        self.assertEqual(elv.users("Old"), [])
        self.assertFalse(elv.profiles["Default"].empty)
        self.assertTrue(elv.profiles["Old"].empty)

    def test_namespaces_and_libdualspec(self):
        elv = dbs(ELV)[0][0]
        self.assertEqual(set(elv.namespaces), {"Bags"})  # LibDualSpec has no profiles table
        self.assertEqual(list(elv.namespaces["Bags"].entries), ["Default", "Old"])
        lds = elv.lds["Kaelys - Mug'thol"]
        self.assertTrue(lds.enabled)
        self.assertEqual({i: f.value.value for i, f in lds.specs.items()}, {1: "Default", 2: "Old"})
        self.assertTrue(elv.lds_enabled("Kaelys - Mug'thol"))
        self.assertFalse(elv.lds_enabled("Alt - Khaz Modan"))

    def test_missing_profile(self):
        stock = dbs(ELV)[0][2]
        self.assertIsNone(stock.profiles_table)
        self.assertTrue(stock.missing("Gone"))
        self.assertEqual(stock.profile_names(), ["Gone"])

    def test_profile_names_order(self):
        data = lua('X = {', '["profileKeys"] = {', '["A - R"] = "Zed",', '["B - R"] = "Beta",', '},',
                   '["profiles"] = {', '["Gamma"] = {', '},', '["Beta"] = {', '},', '},', '}')
        self.assertEqual(dbs(data)[0][0].profile_names(), ["Gamma", "Beta", "Zed"])

    def test_empty_profile_keys_is_still_acedb(self):
        data = lua('X = {', '["profileKeys"] = {', '},', '["profiles"] = {', '["Default"] = {', '},', '},', '}')
        found, _ = dbs(data)
        self.assertEqual([db.sv_name for db in found], ["X"])

    def test_global_is_never_descended(self):
        descended = []

        def spy(path):
            ok = model.ace_descend(path)
            if ok:
                descended.append(path)
            return ok
        luasv.parse(ELV, spy)
        self.assertFalse(any("global" in path[1:2] for path in descended))
        self.assertIn(("ElvDB", "namespaces", "LibDualSpec-1.0", "char", "Kaelys - Mug'thol"), descended)

    def test_split_char_key(self):
        self.assertEqual(model.split_char_key("Kaelys - Mug'thol"), ("Kaelys", "Mug'thol"))
        self.assertEqual(model.split_char_key("X - Azjol-Nerub"), ("X", "Azjol-Nerub"))
        self.assertEqual(model.split_char_key("A - Khaz - Modan"), ("A", "Khaz - Modan"))
        self.assertIsNone(model.split_char_key("NoRealm"))

    def test_prefilter(self):
        self.assertTrue(model.has_profile_keys(ELV))
        self.assertFalse(model.has_profile_keys(b"X = {\n}\n"))
