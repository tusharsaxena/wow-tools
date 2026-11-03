"""scripts/refresh_kb.py: the knowledge-base refresh from the KaosKbDump addon's SavedVariables (spec X7, X8; plan
T4). Every dump is synthesized in a temp tree; no test reads a real install or the network."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from wowtools.core.bootstrap import REPO_ROOT

RETAIL_DUMP = (
    'KaosKbDumpDB = {\r\n'
    '["build"] = "12.0.5 61234",\r\n'
    '["flavor"] = 1,\r\n'
    '["cvars"] = {\r\n'
    '["nameplateMaxDistance"] = {\r\n'
    '["help"] = "The max distance to show nameplates",\r\n'
    '["category"] = "Graphics",\r\n'
    '["default"] = "41",\r\n'
    '["value"] = "60",\r\n'
    '["account"] = true,\r\n'
    '["character"] = false,\r\n'
    '["locked"] = false,\r\n'
    '["secure"] = false,\r\n'
    '["readonly"] = false,\r\n'
    '},\r\n'
    '["autoLootDefault"] = {\r\n'
    '["help"] = "Automatically loot items when the loot window opens",\r\n'
    '["category"] = "Game",\r\n'
    '["default"] = "0",\r\n'
    '["value"] = "1",\r\n'
    '["account"] = false,\r\n'
    '["character"] = true,\r\n'
    '["locked"] = false,\r\n'
    '["secure"] = false,\r\n'
    '["readonly"] = false,\r\n'
    '},\r\n'
    '["gxWindow"] = {\r\n'
    '["category"] = 1,\r\n'
    '["default"] = "1",\r\n'
    '["value"] = "1",\r\n'
    '["account"] = false,\r\n'
    '["character"] = false,\r\n'
    '["locked"] = true,\r\n'
    '["secure"] = true,\r\n'
    '["readonly"] = true,\r\n'
    '},\r\n'
    '},\r\n'
    '["commands"] = {\r\n'
    '["/cast"] = "CAST",\r\n'
    '["/CASTSEQUENCE"] = "CASTSEQUENCE",\r\n'
    '["/use"] = "USE",\r\n'
    '},\r\n'
    '}\r\n'
)


def load_refresh_kb():
    spec = importlib.util.spec_from_file_location("refresh_kb", REPO_ROOT / "scripts" / "refresh_kb.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RefreshKbTest(unittest.TestCase):
    def setUp(self):
        self.module = load_refresh_kb()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.wow = self.root / "World of Warcraft"
        self.out = self.root / "kb"

    def write_dump(self, flavor: str, text: str = RETAIL_DUMP, account: str = "ACCOUNT1", mtime: float | None = None,
                   ) -> Path:
        path = self.wow / flavor / "WTF" / "Account" / account / "SavedVariables" / "KaosKbDump.lua"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def run_main(self, *args: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.module.main(["--wow", str(self.wow), "--out", str(self.out), *args])
        return code, out.getvalue() + err.getvalue()

    def read_json(self, *parts: str) -> dict:
        return json.loads((self.out.joinpath(*parts)).read_text(encoding="utf-8"))

    def test_dump_to_cvar_json(self):
        self.write_dump("_retail_")
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        data = self.read_json("cvars", "_retail_.json")
        self.assertEqual(data["flavor"], "_retail_")
        self.assertEqual(data["build"], "12.0.5 61234")
        self.assertEqual(data["source"], "client dump _retail_ 12.0.5 61234")
        cvars = data["cvars"]
        self.assertEqual(sorted(cvars), ["autoLootDefault", "gxWindow", "nameplateMaxDistance"])
        self.assertEqual(cvars["nameplateMaxDistance"], {
            "default": "41", "help": "The max distance to show nameplates", "category": "graphics",
            "scope": "account", "synced": True, "locked": False, "readonly": False})
        self.assertEqual(cvars["autoLootDefault"]["scope"], "character")
        self.assertTrue(cvars["autoLootDefault"]["synced"])
        self.assertEqual(cvars["autoLootDefault"]["default"], "0")
        self.assertEqual(cvars["autoLootDefault"]["help"], "Automatically loot items when the loot window opens")
        machine = cvars["gxWindow"]
        self.assertEqual((machine["scope"], machine["synced"]), ("machine", False))
        self.assertEqual(machine["help"], "")
        self.assertEqual(machine["category"], "1")
        self.assertTrue(machine["locked"] and machine["readonly"])
        for entry in cvars.values():
            self.assertNotIn("value", entry, "the user's own values never go into the KB")

    def test_dump_to_slash_json(self):
        self.write_dump("_retail_")
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        data = self.read_json("slash_commands", "_retail_.json")
        self.assertEqual(data["flavor"], "_retail_")
        self.assertEqual(data["build"], "12.0.5 61234")
        self.assertEqual(data["source"], "client dump _retail_ 12.0.5 61234")
        self.assertEqual(data["commands"], {"/cast": "CAST", "/castsequence": "CASTSEQUENCE", "/use": "USE"})

    def test_missing_dump_flavor_skipped_with_message(self):
        self.write_dump("_retail_")
        (self.wow / "_classic_" / "WTF" / "Account" / "ACCOUNT1" / "SavedVariables").mkdir(parents=True)
        self.out.joinpath("cvars").mkdir(parents=True)
        kept = self.out / "cvars" / "_classic_.json"
        kept.write_text('{"flavor": "_classic_"}\n', encoding="utf-8")
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertIn("_classic_", output)
        self.assertIn("no KaosKbDump", output)
        self.assertTrue((self.out / "cvars" / "_retail_.json").is_file())
        self.assertEqual(kept.read_text(encoding="utf-8"), '{"flavor": "_classic_"}\n', "an older file is kept")
        self.assertFalse((self.out / "slash_commands" / "_classic_.json").exists())

    def test_no_dump_at_all_fails(self):
        (self.wow / "_retail_" / "WTF").mkdir(parents=True)
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("no KaosKbDump", output)
        self.assertFalse(self.out.exists())

    def test_newest_dump_of_several_accounts_wins(self):
        self.write_dump("_retail_", RETAIL_DUMP.replace("12.0.5 61234", "12.0.1 60000"), account="OLD", mtime=1000)
        self.write_dump("_retail_", account="NEW", mtime=2000)
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.read_json("cvars", "_retail_.json")["build"], "12.0.5 61234")
        self.assertIn("NEW", output)

    def test_unreadable_dump_is_reported_and_skipped(self):
        self.write_dump("_retail_")
        self.write_dump("_classic_", "KaosKbDumpDB = {\r\n[\"build\"] = \r\n")
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertIn("_classic_", output)
        self.assertFalse((self.out / "cvars" / "_classic_.json").exists())

    def test_non_utf8_dump_string_is_reported_and_skipped(self):
        """T4 review: a dump string with a byte that is not UTF-8 skips that flavor with a message; the others are
        still written and neither of the bad flavor's files is touched."""
        self.write_dump("_classic_")
        bad = self.write_dump("_retail_")
        bad.write_bytes(RETAIL_DUMP.encode("utf-8").replace(b"The max distance", b"The max \xff distance"))
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertIn("_retail_: skipped", output)
        self.assertIn("not valid UTF-8", output)
        self.assertTrue((self.out / "cvars" / "_classic_.json").is_file())
        self.assertTrue((self.out / "slash_commands" / "_classic_.json").is_file())
        self.assertFalse((self.out / "cvars" / "_retail_.json").exists())
        self.assertFalse((self.out / "slash_commands" / "_retail_.json").exists())

    def test_output_is_stable_and_utf8(self):
        self.write_dump("_retail_", RETAIL_DUMP.replace("Automatically loot", "Dænerys loots"))
        self.run_main()
        first = (self.out / "cvars" / "_retail_.json").read_bytes()
        self.run_main()
        self.assertEqual((self.out / "cvars" / "_retail_.json").read_bytes(), first)
        self.assertIn("Dænerys".encode(), first)
        self.assertNotIn(b"\r\n", first)
        self.assertTrue(first.endswith(b"}\n"))

    def test_wiki_notes_layered_with_their_source(self):
        self.write_dump("_retail_")
        notes = self.root / "wiki_notes.json"
        url = "https://warcraft.wiki.gg/wiki/CVar_gxWindow"
        notes.write_text(json.dumps({"cvars": {
            "gxWindow": {"text": "Runs the game in a window instead of full screen.", "source": url},
            "notADumpedCVar": {"text": "Ignored.", "source": "https://warcraft.wiki.gg/wiki/X"},
        }}), encoding="utf-8")
        code, output = self.run_main("--wiki", "--wiki-notes", str(notes))
        self.assertEqual(code, 0, output)
        cvars = self.read_json("cvars", "_retail_.json")["cvars"]
        self.assertEqual(cvars["gxWindow"]["wiki"], {"text": "Runs the game in a window instead of full screen.",
                                                     "source": url})
        self.assertNotIn("wiki", cvars["autoLootDefault"])
        self.assertNotIn("notADumpedCVar", cvars)

    def test_wiki_note_without_a_source_is_refused(self):
        self.write_dump("_retail_")
        notes = self.root / "wiki_notes.json"
        notes.write_text(json.dumps({"cvars": {"gxWindow": {"text": "No source."}}}), encoding="utf-8")
        code, output = self.run_main("--wiki", "--wiki-notes", str(notes))
        self.assertEqual(code, 1)
        self.assertIn("gxWindow", output)
        self.assertFalse(self.out.exists())

    def test_without_wiki_flag_notes_are_not_read(self):
        self.write_dump("_retail_")
        code, output = self.run_main("--wiki-notes", str(self.root / "missing.json"))
        self.assertEqual(code, 0, output)
        self.assertNotIn("wiki", self.read_json("cvars", "_retail_.json")["cvars"]["gxWindow"])


class DumpAddonTest(unittest.TestCase):
    """The Lua is not unit-tested (plan T4): these pin its shape so it stays small and library-free."""
    ADDON = REPO_ROOT / "scripts" / "kb_dump" / "KaosKbDump"

    def test_addon_files_and_size(self):
        lua = (self.ADDON / "KaosKbDump.lua").read_text(encoding="utf-8")
        toc = (self.ADDON / "KaosKbDump.toc").read_text(encoding="utf-8")
        self.assertLess(len(lua.splitlines()), 150)
        self.assertIn("## SavedVariables: KaosKbDumpDB", toc)
        self.assertIn("KaosKbDump.lua", toc)
        self.assertNotIn("LibStub", lua)
        for api in ("C_Console.GetAllCommands", "C_CVar.GetCVarInfo", "SLASH_", "/kbdump", "GetBuildInfo"):
            self.assertIn(api, lua)
        self.assertTrue((REPO_ROOT / "scripts" / "kb_dump" / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
