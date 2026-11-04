"""Config Editor model and staging: the three file levels, CVar rows, set, remove, reset, toggle and the bytes they
build (config tools spec CE3-CE6, CE8, X3, X4, X8)."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import CONFIG_AELLA, CONFIG_TRAXEX, build_config_tree
from wowtools.core.cvarfile import parse_cvars
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.kb import CvarInfo
from wowtools.tools.config_editor.model import CATEGORIES, CONFIG_CACHE, ConfigTarget, category_of
from wowtools.tools.config_editor.ops import (ConfigStaged, build_changes, rows, stage_remove, stage_reset,
                                              stage_set, stage_toggle)
from wowtools.tools.config_editor.scanner import scan_targets


def info(name: str, default: str | None, scope: str | None = "character", category: str = "other",
         help_text: str = "", description: str = "") -> CvarInfo:
    return CvarInfo(name=name, default=default, help=help_text, description=description,
                    description_source="https://warcraft.wiki.gg/wiki/CVar_" + name if description else "",
                    category=category, scope=scope, synced=scope in ("account", "character"),
                    source="client dump _retail_ 1")


CVARS = {c.name: c for c in (
    info("nameplateShowFriends", "0", category="nameplates", help_text="Show friendly nameplates"),
    info("nameplateShowAll", "0", scope="account", category="nameplates"),
    info("cameraDistanceMaxZoomFactor", "1.9", category="camera", description="How far the camera can zoom out."),
    info("assistedCombatHighlight", "1", category="interface"),
    info("autoLootDefault", "0", scope="account", category="interface"),
    info("floatingCombatTextCombatDamage", "1", category="combat text"),
    info("gxMaximize", "0", scope="machine", category="graphics"),
    info("Sound_MasterVolume", "1.0", scope="machine", category="sound"),
    info("Sound_EnableAllSound", "1", scope="machine", category="sound"),
    info("lastSelectedClubId", None, category="other"),
)}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ConfigEditorOpsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = build_config_tree(Path(self._tmp.name))
        self.wtf = self.root / "_retail_" / "WTF"
        self.flavor = WowInstall(self.root).flavor("_retail_")
        self.targets = scan_targets(self.flavor)

    def target(self, label: str, targets: list[ConfigTarget] | None = None) -> ConfigTarget:
        for target in targets if targets is not None else self.targets:
            if target.label == label:
                return target
        raise AssertionError(f"no target {label}")

    def row(self, target: ConfigTarget, name: str, staged: ConfigStaged | None = None, **filters):
        args = {"show_all_known": True, "category": None, "changed_only": False, "search": ""} | filters
        found = [r for r in rows(target, CVARS, staged=staged, **args) if r.name == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def test_scan_three_levels(self):
        self.assertEqual([(t.level, t.label) for t in self.targets], [
            ("machine", "Config.wtf"),
            ("account", "ALT"), ("character", "ALT/Realm1/Dænerys"),
            ("account", "BARE"),
            ("account", "MAIN"), ("character", "MAIN/Realm1/Aellâ"), ("character", "MAIN/Realm1/Bob"),
            ("character", "MAIN/Realm2/Trâxex")])  # `Bob - Copy`, `Bob2` and SavedVariables are not characters
        machine = self.targets[0]
        self.assertEqual(machine.path, self.wtf / "Config.wtf")
        self.assertIsNone(machine.account)
        self.assertIsNone(machine.character)
        aella = self.target("MAIN/Realm1/Aellâ")
        self.assertEqual(aella.path, self.wtf / "Account" / "MAIN" / "Realm1" / "Aellâ" / CONFIG_CACHE)
        self.assertEqual((aella.account.name, aella.character.name), ("MAIN", "Aellâ"))
        self.assertEqual(aella.data, CONFIG_AELLA)
        self.assertEqual(aella.sha256, sha(CONFIG_AELLA))
        self.assertEqual(aella.parsed.get("myAddonThing"), "Dænerys")
        self.assertTrue(aella.exists)
        self.assertFalse(aella.read_only)
        bob = self.target("MAIN/Realm1/Bob")  # no file yet: an empty target a run would create
        self.assertEqual((bob.data, bob.parsed, bob.sha256, bob.exists, bob.read_only), (None, None, None, False, False))
        self.assertEqual(self.target("MAIN").account.name, "MAIN")
        self.assertIsNone(self.target("MAIN").character)

    def test_scan_unreadable_file_is_read_only_and_logged(self):
        (self.wtf / "Account" / "ALT" / CONFIG_CACHE).mkdir()  # a folder where the file should be: can't be read
        with capture_events() as records:
            targets = scan_targets(self.flavor)
        alt = self.target("ALT", targets)
        self.assertTrue(alt.read_only)
        self.assertIn("could not be read", alt.problem)
        self.assertIsNone(alt.data)
        events = [r["event"] for r in records]
        self.assertIn("cvar.file_unreadable", events)
        self.assertIn("cvar.scanned", events)
        with self.assertRaises(ValueError):
            stage_set(ConfigStaged(), alt, "autoLootDefault", "1")

    def test_rows_set_and_known(self):
        aella = self.target("MAIN/Realm1/Aellâ")
        set_only = rows(aella, CVARS, show_all_known=False, category=None, changed_only=False, search="")
        self.assertEqual([r.name for r in set_only],  # by name, case ignored
                         ["assistedCombatHighlight", "cameraDistanceMaxZoomFactor", "myAddonThing",
                          "nameplateShowFriends"])
        self.assertEqual(set_only[1].value, "2.6")
        self.assertIs(set_only[1].info, CVARS["cameraDistanceMaxZoomFactor"])
        known = rows(aella, CVARS, show_all_known=True, category=None, changed_only=False, search="")
        names = [r.name for r in known]
        # every known character-scope CVar joins, not set; account and machine ones and unknown-scope ones do not
        self.assertIn("floatingCombatTextCombatDamage", names)
        self.assertIn("lastSelectedClubId", names)
        self.assertNotIn("autoLootDefault", names)
        self.assertNotIn("gxMaximize", names)
        self.assertEqual(names, sorted(names, key=str.casefold))
        unset = self.row(aella, "floatingCombatTextCombatDamage")
        self.assertEqual((unset.value, unset.default, unset.changed), (None, "1", False))
        machine = rows(self.targets[0], CVARS, show_all_known=True, category=None, changed_only=False, search="")
        self.assertEqual([r.name for r in machine], ["gxMaximize", "Sound_EnableAllSound", "Sound_MasterVolume"])
        missing = rows(self.target("MAIN/Realm1/Bob"), CVARS, show_all_known=False, category=None,
                       changed_only=False, search="")
        self.assertEqual(missing, [])
        # search: name, Blizzard help and our description, case ignored
        found = rows(aella, CVARS, show_all_known=True, category=None, changed_only=False, search="ZOOM OUT")
        self.assertEqual([r.name for r in found], ["cameraDistanceMaxZoomFactor"])
        found = rows(aella, CVARS, show_all_known=True, category=None, changed_only=False, search="friendly")
        self.assertEqual([r.name for r in found], ["nameplateShowFriends"])
        found = rows(aella, CVARS, show_all_known=False, category="nameplates", changed_only=False, search="")
        self.assertEqual([r.name for r in found], ["nameplateShowFriends"])

    def test_changed_from_default(self):
        aella = self.target("MAIN/Realm1/Aellâ")
        self.assertTrue(self.row(aella, "cameraDistanceMaxZoomFactor").changed)    # 2.6, default 1.9
        self.assertTrue(self.row(aella, "nameplateShowFriends").changed)          # 1, default 0
        self.assertFalse(self.row(aella, "assistedCombatHighlight").changed)      # 1, default 1
        self.assertIsNone(self.row(aella, "lastSelectedClubId").default)
        self.assertFalse(self.row(aella, "lastSelectedClubId").changed)           # not set: the client default
        machine = self.targets[0]
        self.assertTrue(self.row(machine, "Sound_MasterVolume").changed)          # 0.5, default 1.0
        self.assertFalse(self.row(machine, "Sound_EnableAllSound").changed)       # not set
        changed = rows(aella, CVARS, show_all_known=True, category=None, changed_only=True, search="")
        self.assertEqual([r.name for r in changed], ["cameraDistanceMaxZoomFactor", "nameplateShowFriends"])
        staged = ConfigStaged()
        stage_set(staged, aella, "lastSelectedClubId", "7")
        self.assertIsNone(self.row(aella, "lastSelectedClubId", staged).changed)  # set, but the default is unknown
        stage_set(staged, aella, "assistedCombatHighlight", "1.0")
        self.assertFalse(self.row(aella, "assistedCombatHighlight", staged).changed)  # the same number

    def test_unknown_cvar_row(self):
        aella = self.target("MAIN/Realm1/Aellâ")
        row = self.row(aella, "myAddonThing")
        self.assertEqual((row.value, row.default, row.changed, row.info, row.scope_mismatch),
                         ("Dænerys", None, None, None, False))
        self.assertEqual(row.category, "other")
        staged = ConfigStaged()
        stage_set(staged, aella, "someNewThing", "5")  # unknown CVars can be added and edited (CE5)
        added = self.row(aella, "someNewThing", staged)
        self.assertEqual((added.value, added.info, added.staged), ("5", None, True))
        changed_only = rows(aella, CVARS, show_all_known=False, category=None, changed_only=True, search="",
                            staged=staged)
        self.assertNotIn("myAddonThing", [r.name for r in changed_only])  # unknown default: not "changed"

    def test_toggle_boolean(self):
        aella = self.target("MAIN/Realm1/Aellâ")
        staged = ConfigStaged()
        self.assertEqual(stage_toggle(staged, aella, "nameplateShowFriends", CVARS["nameplateShowFriends"]), "0")
        self.assertEqual(staged.sets, {aella.path: {"nameplateShowFriends": "0"}})
        row = self.row(aella, "nameplateShowFriends", staged)
        self.assertEqual((row.value, row.changed, row.staged), ("0", False, True))
        self.assertEqual(stage_toggle(staged, aella, "nameplateShowFriends", CVARS["nameplateShowFriends"]), "1")
        self.assertEqual(staged.count(), 0)  # back to what the file says: nothing staged
        # not set: toggles from the default, and toggling back drops the staged line again
        info_ = CVARS["floatingCombatTextCombatDamage"]
        self.assertEqual(stage_toggle(staged, aella, "floatingCombatTextCombatDamage", info_), "0")
        self.assertEqual(stage_toggle(staged, aella, "floatingCombatTextCombatDamage", info_), "1")
        self.assertEqual(staged.count(), 0)
        with self.assertRaises(ValueError):  # not a boolean
            stage_toggle(staged, aella, "cameraDistanceMaxZoomFactor", CVARS["cameraDistanceMaxZoomFactor"])
        with self.assertRaises(ValueError):  # not set and no default: nothing to toggle from
            stage_toggle(staged, aella, "lastSelectedClubId", CVARS["lastSelectedClubId"])
        stage_toggle(staged, aella, "assistedCombatHighlight", CVARS["assistedCombatHighlight"])
        new = build_changes(staged, self.targets)[0].new
        self.assertEqual(parse_cvars(new).get("assistedCombatHighlight"), "0")

    def test_reset_removes_line(self):
        aella = self.target("MAIN/Realm1/Aellâ")
        staged = ConfigStaged()
        stage_reset(staged, aella, "cameraDistanceMaxZoomFactor")
        self.assertEqual(staged.removes, {aella.path: {"cameraDistanceMaxZoomFactor"}})
        row = self.row(aella, "cameraDistanceMaxZoomFactor", staged)
        self.assertEqual((row.value, row.changed, row.staged), (None, False, True))
        [change] = build_changes(staged, self.targets)
        self.assertEqual(change.new, CONFIG_AELLA.replace(b'SET cameraDistanceMaxZoomFactor "2.6"\r\n', b""))
        self.assertEqual(change.expected_sha256, sha(CONFIG_AELLA))
        self.assertEqual(change.changes, ("config-cache.wtf: removed cameraDistanceMaxZoomFactor",))
        # set then remove: only the removal is left; remove then set: only the set
        stage_set(staged, aella, "cameraDistanceMaxZoomFactor", "3")
        self.assertEqual((staged.sets, staged.removes), ({aella.path: {"cameraDistanceMaxZoomFactor": "3"}}, {}))
        stage_remove(staged, aella, "CAMERADISTANCEMAXZOOMFACTOR")  # names in any case, as the client reads them
        self.assertEqual((staged.sets, staged.removes), ({}, {aella.path: {"cameraDistanceMaxZoomFactor"}}))
        # removing a CVar the file doesn't set, or one only staged, stages nothing
        other = ConfigStaged()
        stage_remove(other, aella, "floatingCombatTextCombatDamage")
        stage_set(other, aella, "someNewThing", "1")
        stage_reset(other, aella, "someNewThing")
        self.assertEqual(other.count(), 0)
        self.assertEqual(build_changes(other, self.targets), [])

    def test_scope_mismatch_flag(self):
        aella = self.target("MAIN/Realm1/Aellâ")
        staged = ConfigStaged()
        stage_set(staged, aella, "autoLootDefault", "1")  # an account CVar in a character file: a warning, not refused
        stage_set(staged, aella, "gxMaximize", "1")
        self.assertTrue(self.row(aella, "autoLootDefault", staged).scope_mismatch)
        self.assertTrue(self.row(aella, "gxMaximize", staged).scope_mismatch)
        self.assertFalse(self.row(aella, "nameplateShowFriends", staged).scope_mismatch)
        self.assertFalse(self.row(aella, "myAddonThing", staged).scope_mismatch)  # unknown: no scope to compare
        account = self.target("MAIN")
        self.assertTrue(self.row(account, "nameplateShowAll").scope_mismatch is False)
        stage_set(staged, account, "nameplateShowFriends", "1")
        self.assertTrue(self.row(account, "nameplateShowFriends", staged).scope_mismatch)
        self.assertEqual(len(build_changes(staged, self.targets)), 2)

    def test_category_mapping(self):
        self.assertEqual(CATEGORIES, ("graphics", "sound", "interface", "camera", "nameplates", "combat text",
                                      "network", "other"))
        for name, expected in (("nameplateShowAll", "nameplates"), ("NamePlateHorizontalScale", "nameplates"),
                               ("cameraSmoothStyle", "camera"), ("test_cameraOverShoulder", "camera"),
                               ("floatingCombatTextCombatHealing", "combat text"),
                               ("CombatTextFloatMode", "combat text"), ("enableFloatingCombatText", "combat text"),
                               ("whatever", "other")):
            with self.subTest(name=name):
                self.assertEqual(category_of(None, name), expected)
        self.assertEqual(category_of(CVARS["gxMaximize"], "gxMaximize"), "graphics")
        self.assertEqual(category_of(CVARS["Sound_MasterVolume"], "Sound_MasterVolume"), "sound")
        self.assertEqual(category_of(info("x", "0", category="no such group"), "x"), "other")

    def test_build_changes_byte_exact_elsewhere(self):
        traxex = self.target("MAIN/Realm2/Trâxex")  # LF endings, a non-SET line, no final newline
        aella = self.target("MAIN/Realm1/Aellâ")
        bob = self.target("MAIN/Realm1/Bob")  # no file: created
        staged = ConfigStaged()
        stage_set(staged, traxex, "nameplateShowFriends", "1")
        stage_set(staged, traxex, "cameraDistanceMaxZoomFactor", "2.6")
        stage_set(staged, aella, "myAddonThing", "Trâxex")
        stage_remove(staged, aella, "assistedCombatHighlight")
        stage_set(staged, bob, "nameplateShowFriends", "1")
        stage_set(staged, aella, "nameplateShowFriends", "1")  # the file's own value: nothing staged
        self.assertEqual(staged.count(), 5)
        changes = build_changes(staged, self.targets)
        self.assertEqual([c.path for c in changes], [aella.path, bob.path, traxex.path])  # in scan order
        by_path = {c.path: c for c in changes}
        self.assertEqual(by_path[traxex.path].new,
                         b'SET nameplateShowFriends "1"\n# not a SET line\nSET floatingCombatTextCombatDamage "1"\n'
                         b'SET cameraDistanceMaxZoomFactor "2.6"\n')
        self.assertEqual(by_path[traxex.path].expected_sha256, sha(CONFIG_TRAXEX))
        self.assertEqual(by_path[traxex.path].changes,
                         ('config-cache.wtf: nameplateShowFriends "0" -> "1"',
                          'config-cache.wtf: added cameraDistanceMaxZoomFactor "2.6"'))
        self.assertEqual(by_path[aella.path].new,
                         CONFIG_AELLA.replace(b'SET assistedCombatHighlight "1"\r\n', b"")
                         .replace('"Dænerys"'.encode(), '"Trâxex"'.encode()))
        self.assertEqual(by_path[bob.path].new, b'SET nameplateShowFriends "1"\r\n')
        self.assertIsNone(by_path[bob.path].expected_sha256)
        with self.assertRaises(ValueError):  # staged for a target that was not passed
            build_changes(staged, [aella])
        with self.assertRaises(ValueError):
            stage_set(staged, aella, "bad name", "1")
        with self.assertRaises(ValueError):
            stage_set(staged, aella, "fine", "two\nlines")


if __name__ == "__main__":
    unittest.main()
