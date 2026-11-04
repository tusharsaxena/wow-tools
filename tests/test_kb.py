"""The knowledge-base loader, core/kb.py (config tools spec X6, X8, CC5, ME3; plan T8). Every test reads a temp KB
folder (`root=`) or the shipped seed data; nothing touches a real WoW install or the network."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wowtools.core import kb
from wowtools.core.events import capture_events

# The spec appendix's state reading (CC5 seed), names and patterns, plus the patterns CC5 itself names.
APPENDIX_STATE_NAMES = (
    "EJSelectedTier", "clubFinderPlayerSettings", "eventSchedulerLastUpdate", "highestUnlockedTieredEntranceTier",
    "lastSelectedClubId", "maxLevelSpecsUsed", "seenPurchasableClassCapstone", "hardTrackedQuests",
    "trackedAchievements", "reputationsCollapsed", "currencyCategoriesCollapsed", "unlockedMajorFactions",
    "lfgSelectedRoles", "pvpSelectedRoles")
APPENDIX_STATE_PATTERNS = ("closed*", "*Tutorial*", "garrison*", "lastRenownForCovenant*", "latest*", "new*Season",
                           "savedClassConfig*", "cameraSaved*", "last*", "saved*Config*", "*Collapsed",
                           "highestUnlocked*")
# Every appendix CVar the reading puts on the state list, matched by a name or a pattern.
APPENDIX_STATE_CVARS = (
    "closedExtraAbiltyTutorials", "covenantMissionTutorial", "eventSchedulerLastUpdate", "garrisonCompleteTalent",
    "garrisonCompleteTalentType", "highestUnlockedTieredEntranceTier", "lastRenownForCovenant1",
    "lastSelectedClubId", "latestSplashScreen", "latestTransmogSetSource", "maxLevelSpecsUsed", "newDelvesSeason",
    "newMythicPlusSeason", "newPvpSeason", "savedClassConfigOne", "savedClassConfigTwo", "savedClassConfigThree",
    "seenPurchasableClassCapstone", "soulbindsActivatedTutorial", "soulbindsLandingPageTutorial",
    "soulbindsViewedTutorial", "cameraSavedDistance", "cameraSavedPitch", "cameraSavedVehicleDistance",
    "closedInfoFrames", "clubFinderPlayerSettings", "lfgSelectedRoles", "pvpSelectedRoles", "EJSelectedTier",
    "hardTrackedQuests", "trackedAchievements", "reputationsCollapsed", "currencyCategoriesCollapsed",
    "unlockedMajorFactions")
# Every appendix CVar the reading calls a preference (copied by the Config Copier).
APPENDIX_PREFERENCES = (
    "EJDungeonDifficulty", "EJRaidDifficulty", "TTSUseCharacterSettings", "assistAttack", "assistedCombatHighlight",
    "autoQuestPopUps", "calendarShowResets", "dragonRidingRacesFilter", "nameplateMaxScaleDistance",
    "nameplateMinScaleDistance", "nameplatePlayerMaxDistance", "nameplateSelectedAlpha", "showArenaEnemyFrames",
    "transmogCurrentSpecOnly", "enableMultiActionBars", "EJLootClass")


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class KbTestCase(unittest.TestCase):
    def setUp(self):
        kb.clear_cache()
        self.addCleanup(kb.clear_cache)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


class StateListTest(KbTestCase):
    def test_state_list_matches_spec_appendix(self):
        data = json.loads((kb.KB_ROOT / "cvar_state.json").read_text(encoding="utf-8"))
        self.assertTrue(set(APPENDIX_STATE_NAMES) <= set(data["names"]), data["names"])
        self.assertTrue(set(APPENDIX_STATE_PATTERNS) <= set(data["patterns"]), data["patterns"])
        self.assertTrue(data["source"])
        for name in (*APPENDIX_STATE_NAMES, *APPENDIX_STATE_CVARS):
            self.assertTrue(kb.is_state_cvar(name), name)
        for name in APPENDIX_PREFERENCES:
            self.assertFalse(kb.is_state_cvar(name), name)

    def test_state_match_ignores_case_as_the_client_does(self):
        self.assertTrue(kb.is_state_cvar("HARDTRACKEDQUESTS"))
        self.assertTrue(kb.is_state_cvar("ClosedInfoFrames"))
        self.assertTrue(kb.is_state_cvar("someTUTORIALflag"))
        self.assertFalse(kb.is_state_cvar(""))

    def test_shipped_patterns_cover_siblings_and_spare_known_preferences(self):
        # CC5 names highestUnlocked* as a pattern: a sibling progress CVar stays the target's own.
        self.assertTrue(kb.is_state_cvar("highestUnlockedMythicPlusTier"))
        # showTutorials is the Retail Tutorials toggle, a preference that *Tutorial* would otherwise catch.
        data = json.loads((kb.KB_ROOT / "cvar_state.json").read_text(encoding="utf-8"))
        self.assertIn("showTutorials", data["exceptions"])
        self.assertFalse(kb.is_state_cvar("showTutorials"))
        self.assertFalse(kb.is_state_cvar("SHOWTUTORIALS"))

    def test_patterns_checked_against_every_dumped_flavor(self):
        """CC5, T20e: each pattern's matches in the shipped dumps were read; the preferences it caught are exceptions
        (the tutorials toggles), everything else it matches is state."""
        for name in ("showTutorials", "showNPETutorials", "housingTutorialsEnabled"):
            self.assertFalse(kb.is_state_cvar(name), name)
        for name in ("flaggedTutorials", "closedInfoFramesAccountWide", "friendInvitesCollapsed", "lastTalkedToGM",
                     "lastRenownForMajorFaction2590", "highestUnlockedDelvesTier", "newPvpSeason",
                     "cameraSavedPetBattleDistance"):
            self.assertTrue(kb.is_state_cvar(name), name)

    def test_exceptions_win_over_patterns(self):
        write_json(self.root / "cvar_state.json", {"source": "test", "names": ["keepMe"], "patterns": ["last*"],
                                                   "exceptions": ["lastPreference"]})
        self.assertTrue(kb.is_state_cvar("lastThing", root=self.root))
        self.assertTrue(kb.is_state_cvar("KEEPME", root=self.root))
        self.assertFalse(kb.is_state_cvar("LastPreference", root=self.root))

    def test_unreadable_state_list_is_logged_and_lists_nothing(self):
        (self.root / "cvar_state.json").write_text("{not json", encoding="utf-8")
        with capture_events() as records:
            self.assertFalse(kb.is_state_cvar("hardTrackedQuests", root=self.root))
            self.assertFalse(kb.is_state_cvar("closedInfoFrames", root=self.root))
        logged = [r for r in records if r["event"] == "kb.unreadable"]
        self.assertEqual(len(logged), 1, records)  # cached: one warning per file and process
        self.assertEqual(logged[0]["level"], "warning")


class CvarsTest(KbTestCase):
    def flavor_file(self, cvars: dict, flavor: str = "_retail_") -> None:
        write_json(self.root / "cvars" / f"{flavor}.json",
                   {"flavor": flavor, "build": "12.1.5 70688", "source": f"client dump {flavor} 12.1.5 70688",
                    "cvars": cvars})

    def test_missing_flavor_data_is_empty(self):
        with capture_events() as records:
            self.assertEqual(kb.load_cvars("_retail_", root=self.root), {})
            self.assertEqual(kb.load_cvars("_classic_era_", root=self.root), {})
        self.assertEqual([r for r in records if r["event"] == "kb.unreadable"], [])  # no data is not an error

    def test_bad_json_is_logged_not_raised(self):
        for content in ("{not json", "[1, 2]", json.dumps({"cvars": [1]}), b"\xff\xfe{}"):
            with self.subTest(content=content):
                kb.clear_cache()
                path = self.root / "cvars" / "_retail_.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, bytes):
                    path.write_bytes(content)
                else:
                    path.write_text(content, encoding="utf-8")
                with capture_events() as records:
                    self.assertEqual(kb.load_cvars("_retail_", root=self.root), {})
                logged = [r for r in records if r["event"] == "kb.unreadable"]
                self.assertEqual(len(logged), 1, records)
                self.assertEqual(logged[0]["level"], "warning")
                self.assertIn("_retail_.json", logged[0]["data"]["path"])
                self.assertTrue(logged[0]["data"]["reason"])

    def test_reads_the_refresh_script_schema(self):
        self.flavor_file({
            "nameplateMaxDistance": {"default": "41", "help": "Max distance", "category": "game", "scope": "account",
                                     "synced": True, "locked": False, "readonly": False,
                                     "wiki": {"text": "How far away plates show.",
                                              "source": "https://warcraft.wiki.gg/wiki/CVar_nameplateMaxDistance"}},
            "gxMaximize": {"default": "0", "help": "", "category": "graphics", "scope": "machine", "synced": False},
        })
        cvars = kb.load_cvars("_retail_", root=self.root)
        self.assertEqual(set(cvars), {"nameplateMaxDistance", "gxMaximize"})
        plate = cvars["nameplateMaxDistance"]
        self.assertEqual(plate, kb.CvarInfo(
            name="nameplateMaxDistance", default="41", help="Max distance", description="How far away plates show.",
            description_source="https://warcraft.wiki.gg/wiki/CVar_nameplateMaxDistance", category="nameplates",
            scope="account", synced=True, source="client dump _retail_ 12.1.5 70688"))
        gx = cvars["gxMaximize"]
        self.assertEqual((gx.description, gx.description_source, gx.category, gx.scope, gx.synced),
                         ("", "", "graphics", "machine", False))

    def test_odd_entries_read_as_unknown_fields(self):
        self.flavor_file({"oddOne": {"scope": "galaxy", "category": 7}, "notATable": 5,
                          "wikiWithoutSource": {"wiki": {"text": "guess"}}})
        cvars = kb.load_cvars("_retail_", root=self.root)
        self.assertEqual(set(cvars), {"oddOne", "wikiWithoutSource"})
        odd = cvars["oddOne"]
        self.assertEqual((odd.default, odd.help, odd.scope, odd.synced, odd.category), (None, "", None, False, "other"))
        self.assertEqual(cvars["wikiWithoutSource"].description, "")  # a description never ships without its source

    def test_unsafe_flavor_names_read_nothing(self):
        write_json(self.root / "evil.json", {"cvars": {"x": {}}})
        for flavor in ("../evil", "", "_retail_/../x", "a b"):
            self.assertEqual(kb.load_cvars(flavor, root=self.root), {}, flavor)

    def test_loads_are_cached_per_process(self):
        self.flavor_file({"a": {"default": "1"}})
        first = kb.load_cvars("_retail_", root=self.root)
        self.flavor_file({"b": {"default": "2"}})
        self.assertEqual(set(kb.load_cvars("_retail_", root=self.root)), set(first))
        kb.clear_cache()
        self.assertEqual(set(kb.load_cvars("_retail_", root=self.root)), {"b"})

    def test_category_groups(self):
        cases = {("nameplateShowEnemies", "game"): "nameplates", ("NamePlateHorizontalScale", "default"): "nameplates",
                 ("cameraDistanceMaxZoomFactor", "game"): "camera", ("test_cameraOverShoulder", "debug"): "camera",
                 ("floatingCombatTextCombatDamage", "combat"): "combat text",
                 ("enableFloatingCombatText", "game"): "combat text", ("graphicsQuality", "graphics"): "graphics",
                 ("Sound_MasterVolume", "sound"): "sound", ("disableServerNagle", "net"): "network",
                 ("autoLootDefault", "game"): "interface", ("scriptErrors", "debug"): "other",
                 ("assistAttack", "combat"): "other", ("x", ""): "other", ("y", "17"): "other",
                 # T20f: the client files many graphics and sound CVars under no real category ("default").
                 ("graphicsQuality", "default"): "graphics", ("RAIDfarclip", "default"): "graphics",
                 ("raidGraphicsSSAO", "default"): "graphics", ("gxMaximize", "default"): "graphics",
                 ("shadowMode", "default"): "graphics", ("vsync", "none"): "graphics",
                 ("Sound_MasterVolume", "default"): "sound", ("readEULA", "default"): "other",
                 ("raidFramesDisplayClassColor", "game"): "interface", ("shadowMode", "game"): "interface"}
        for (name, raw), group in cases.items():
            self.assertEqual(kb.category_group(name, raw), group, (name, raw))
            self.assertIn(group, kb.CATEGORY_GROUPS)
        self.assertEqual(kb.CATEGORY_GROUPS, ("graphics", "sound", "interface", "camera", "nameplates",
                                              "combat text", "network", "other"))


class ShippedCvarsTest(KbTestCase):
    """The CVar base built from the client dumps (X7, T20)."""

    def shipped(self, flavor: str) -> dict:
        return json.loads((kb.KB_ROOT / "cvars" / f"{flavor}.json").read_text(encoding="utf-8"))

    def test_retail_base_covers_the_client_list(self):
        data = self.shipped("_retail_")
        self.assertTrue(data["source"].startswith("client dump _retail_ "), data["source"])
        self.assertEqual(data["source"], f"client dump _retail_ {data['build']}")
        cvars = data["cvars"]
        self.assertGreater(len(cvars), 1000)
        known = 0
        for name, entry in cvars.items():
            with self.subTest(cvar=name):
                self.assertIn("default", entry)
                self.assertIn(entry["scope"], ("machine", "account", "character", None))
                # Default and scope come from one GetCVarInfo call: both known, or both unknown (T20a).
                self.assertEqual(entry["default"] is None, entry["scope"] is None)
                self.assertNotIn("value", entry, "the dumping character's own values never ship")
                if entry["default"] is not None:
                    self.assertIsInstance(entry["default"], str)
                    self.assertEqual(entry["synced"], entry["scope"] != "machine")
                    known += 1
                if "wiki" in entry:
                    self.assertTrue(entry["wiki"]["text"].strip())
                    self.assertTrue(entry["wiki"]["source"].startswith("https://warcraft.wiki.gg/wiki/"))
        self.assertGreater(known / len(cvars), 0.85)
        loaded = kb.load_cvars("_retail_")
        self.assertEqual(set(loaded), set(cvars))
        for info in loaded.values():
            self.assertEqual(info.source, data["source"])
            self.assertEqual(bool(info.description), bool(info.description_source))
        # The notes reach the CVars the recommendations and the issue's groups touch.
        for name in ("cameraDistanceMaxZoomFactor", "cameraSmoothStyle", "nameplateMotion", "synchronizeConfig"):
            self.assertTrue(loaded[name].description, name)

    def test_every_dumped_flavor_ships(self):
        for flavor in ("_retail_", "_classic_", "_classic_era_", "_anniversary_"):
            with self.subTest(flavor=flavor):
                data = self.shipped(flavor)
                self.assertEqual(data["flavor"], flavor)
                self.assertNotIn("provisional", data)
                self.assertEqual(data["source"], f"client dump {flavor} {data['build']}")

    def test_forever_is_a_marked_copy_of_retail(self):
        """U1: Forever has no dump yet; it ships Retail's CVars, marked provisional, until its own dump exists."""
        retail, forever = self.shipped("_retail_"), self.shipped("_forever_")
        self.assertEqual(forever["provisional"], "copied from _retail_ until a _forever_ dump exists")
        self.assertEqual(forever["flavor"], "_forever_")
        self.assertEqual(forever["source"], retail["source"])
        self.assertEqual(forever["cvars"], retail["cvars"])
        self.assertEqual(set(kb.load_cvars("_forever_")), set(retail["cvars"]))

    def test_wiki_notes_file_is_sourced(self):
        from wowtools.core.bootstrap import REPO_ROOT
        notes = json.loads((REPO_ROOT / "scripts" / "kb_dump" / "wiki_notes.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(notes["cvars"]), 20)
        retail = self.shipped("_retail_")["cvars"]
        for name, note in notes["cvars"].items():
            with self.subTest(cvar=name):
                self.assertEqual(set(note), {"text", "source"})
                self.assertTrue(note["source"].startswith("https://warcraft.wiki.gg/wiki/"), note["source"])
                self.assertTrue(note["text"].strip().endswith("."), note["text"])
                if name in retail:
                    self.assertEqual(retail[name].get("wiki"), note)


class MacroLimitsTest(KbTestCase):
    def test_macro_limits_retail(self):
        self.assertEqual(kb.macro_limits("_retail_"), (120, 30))
        self.assertTrue(kb.limits_known("_retail_"))
        data = json.loads((kb.KB_ROOT / "macro_limits.json").read_text(encoding="utf-8"))
        source = data["flavors"]["_retail_"]["source"]
        self.assertTrue(source.startswith(("https://", "client dump _retail_ ")), source)

    def test_unknown_flavor_gets_retail_values_flagged(self):
        self.assertEqual(kb.macro_limits("_no_such_flavor_"), (120, 30))
        self.assertFalse(kb.limits_known("_no_such_flavor_"))

    def test_every_shipped_flavor_has_a_source(self):
        data = json.loads((kb.KB_ROOT / "macro_limits.json").read_text(encoding="utf-8"))
        for flavor, entry in data["flavors"].items():
            self.assertTrue(entry.get("source"), flavor)
            self.assertTrue(kb.limits_known(flavor), flavor)
            self.assertEqual(kb.macro_limits(flavor), (entry["account"], entry["character"]))

    def test_bad_limits_fall_back_and_log(self):
        write_json(self.root / "macro_limits.json",
                   {"flavors": {"_classic_": {"account": "lots", "character": 18, "source": "x"},
                                "_classic_era_": {"account": 120, "character": 18}}})
        self.assertEqual(kb.macro_limits("_classic_", root=self.root), (120, 30))
        self.assertFalse(kb.limits_known("_classic_", root=self.root))
        self.assertFalse(kb.limits_known("_classic_era_", root=self.root))  # no source: not shipped as known
        (self.root / "macro_limits.json").write_text("nope", encoding="utf-8")
        kb.clear_cache()
        with capture_events() as records:
            self.assertEqual(kb.macro_limits("_retail_", root=self.root), (120, 30))
            self.assertFalse(kb.limits_known("_retail_", root=self.root))
        self.assertEqual(len([r for r in records if r["event"] == "kb.unreadable"]), 1, records)


class RecommendationsTest(KbTestCase):
    def shipped(self) -> list[dict]:
        data = json.loads((kb.KB_ROOT / "recommendations.json").read_text(encoding="utf-8"))
        self.assertTrue(data.get("comment"))
        return data["recommendations"]

    def test_recommendations_all_sourced_and_known_cvars(self):
        from wowtools.core.install import FLAVOR_NAMES
        entries = self.shipped()
        self.assertGreaterEqual(len(entries), 24)  # "a few dozen" (CE7)
        groups = set()
        for entry in entries:
            with self.subTest(cvar=entry.get("cvar")):
                self.assertEqual(set(entry), {"cvar", "value", "flavors", "reason", "source"})
                self.assertTrue(entry["cvar"] and isinstance(entry["cvar"], str))
                self.assertIsInstance(entry["value"], str)
                self.assertTrue(entry["reason"].strip())
                self.assertTrue(entry["source"].startswith("https://"), entry["source"])
                self.assertTrue(entry["flavors"] and set(entry["flavors"]) <= set(FLAVOR_NAMES), entry["flavors"])
                groups.add(kb.category_group(entry["cvar"], ""))
                for flavor in entry["flavors"]:
                    known = kb.load_cvars(flavor)
                    if known:  # the flavor's CVar data exists (T20): the CVar must be in it
                        names = {name.lower() for name in known}
                        self.assertIn(entry["cvar"].lower(), names, flavor)
        self.assertTrue({"nameplates", "camera", "combat text"} <= groups, groups)
        # Every shipped entry loads: nothing is dropped by the loader's own checks.
        for flavor in FLAVOR_NAMES:
            expected = [e for e in entries if flavor in e["flavors"]]
            loaded = kb.load_recommendations(flavor)
            self.assertEqual([(r.cvar, r.value) for r in loaded], [(e["cvar"], e["value"]) for e in expected], flavor)

    def test_shipped_recommendations_one_per_cvar_and_flavor(self):
        seen = set()
        for entry in self.shipped():
            for flavor in entry["flavors"]:
                key = (entry["cvar"].lower(), flavor)
                self.assertNotIn(key, seen, key)
                seen.add(key)

    def test_load_recommendations_reads_the_schema(self):
        write_json(self.root / "recommendations.json", {"recommendations": [
            {"cvar": "nameplateMotion", "value": "1", "flavors": ["_retail_", "_classic_"], "reason": "Stack plates.",
             "source": "https://warcraft.wiki.gg/wiki/CVar_nameplateMotion"},
            {"cvar": "ffxGlow", "value": "0", "flavors": ["_classic_"], "reason": "Less glow.",
             "source": "https://warcraft.wiki.gg/wiki/CVar_ffxGlow"},
        ]})
        retail = kb.load_recommendations("_retail_", root=self.root)
        self.assertEqual(retail, [kb.Recommendation(
            cvar="nameplateMotion", value="1", flavors=("_retail_", "_classic_"), reason="Stack plates.",
            source="https://warcraft.wiki.gg/wiki/CVar_nameplateMotion")])
        self.assertEqual([r.cvar for r in kb.load_recommendations("_classic_", root=self.root)],
                         ["nameplateMotion", "ffxGlow"])
        self.assertEqual(kb.load_recommendations("_classic_era_", root=self.root), [])

    def test_unsourced_or_odd_recommendations_are_not_loaded(self):
        good = {"cvar": "a", "value": "1", "flavors": ["_retail_"], "reason": "r", "source": "https://x.example/a"}
        write_json(self.root / "recommendations.json", {"recommendations": [
            {**good, "source": ""}, {**good, "source": "my own idea"}, {**good, "reason": " "},
            {**good, "cvar": ""}, {**good, "value": 1}, {**good, "flavors": None}, {**good, "flavors": "_retail_"},
            {k: v for k, v in good.items() if k != "source"}, "not a table", good,
            {**good, "cvar": "A", "value": "0"},  # the same CVar again (names match in any case): the first wins
        ]})
        self.assertEqual([(r.cvar, r.value) for r in kb.load_recommendations("_retail_", root=self.root)], [("a", "1")])

    def test_missing_or_bad_recommendations_file(self):
        with capture_events() as records:
            self.assertEqual(kb.load_recommendations("_retail_", root=self.root), [])
        self.assertEqual([r for r in records if r["event"] == "kb.unreadable"], [])
        for content in ("nope", json.dumps({"recommendations": {"a": 1}})):
            with self.subTest(content=content):
                kb.clear_cache()
                (self.root / "recommendations.json").write_text(content, encoding="utf-8")
                self.assertEqual(kb.load_recommendations("_retail_", root=self.root), [])
        self.assertEqual(kb.load_recommendations("../evil", root=self.root), [])


class KbShipsTest(unittest.TestCase):
    def test_kb_folder_ships_inside_wowtools_with_its_readme(self):
        self.assertEqual(kb.KB_ROOT, Path(kb.__file__).resolve().parents[1] / "kb")
        readme = (kb.KB_ROOT / "README.md").read_text(encoding="utf-8")
        for needle in ("cvar_state.json", "macro_limits.json", "cvars/<flavor>.json", "source", "macro_reference.json",
                       "macro_templates.json", "optimizer_rules.json", "recommendations.json"):
            self.assertIn(needle, readme)

    def test_kb_unreadable_is_registered_as_a_warning(self):
        from wowtools.core.events import REGISTRY
        self.assertEqual(REGISTRY["kb.unreadable"].level, "warning")


if __name__ == "__main__":
    unittest.main()
