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
    '["/dance"] = "EMOTE35",\r\n'
    '["/dbm"] = "DEADLYBOSSMODS",\r\n'
    '},\r\n'
    '["addonCommands"] = {\r\n'
    '["DEADLYBOSSMODS"] = true,\r\n'
    '},\r\n'
    '["macroLimits"] = {\r\n'
    '["account"] = 120,\r\n'
    '["character"] = 18,\r\n'
    '},\r\n'
    '["dumpVersion"] = 2,\r\n'
    '}\r\n'
)

# A dump written by the first version of the addon (T4): no dumpVersion, so no addonCommands, emotes or macroLimits.
OLD_DUMP = (RETAIL_DUMP.replace('["dumpVersion"] = 2,\r\n', "")
            .replace('["/dance"] = "EMOTE35",\r\n', "")
            .replace('["addonCommands"] = {\r\n["DEADLYBOSSMODS"] = true,\r\n},\r\n', "")
            .replace('["macroLimits"] = {\r\n["account"] = 120,\r\n["character"] = 18,\r\n},\r\n', ""))

NO_INFO_CVAR = (
    '["enableCombatText"] = {\r\n'
    '["help"] = "",\r\n'
    '["category"] = "Default",\r\n'
    '["account"] = false,\r\n'
    '["character"] = false,\r\n'
    '["locked"] = false,\r\n'
    '["secure"] = false,\r\n'
    '["readonly"] = false,\r\n'
    '},\r\n'
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
        # The emote is kept (a macro may use it); the addon's own command is left out (T20b).
        self.assertEqual(data["commands"], {"/cast": "CAST", "/castsequence": "CASTSEQUENCE", "/use": "USE",
                                            "/dance": "EMOTE35"})

    def test_old_dump_writes_cvars_but_no_slash_commands(self):
        """T20b: a dump from the first addon version can't tell an addon's command from the client's and has no
        emotes, so its slash list is not written (an older list is kept) and the run says why."""
        self.write_dump("_retail_", OLD_DUMP)
        self.out.joinpath("slash_commands").mkdir(parents=True)
        kept = self.out / "slash_commands" / "_retail_.json"
        kept.write_text('{"flavor": "_retail_"}\n', encoding="utf-8")
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertTrue((self.out / "cvars" / "_retail_.json").is_file())
        self.assertEqual(kept.read_text(encoding="utf-8"), '{"flavor": "_retail_"}\n')
        self.assertIn("slash commands not written", output)
        self.assertFalse((self.out / "macro_limits.json").exists())

    def test_cvar_without_client_info_reads_unknown(self):
        """T20a: GetCVarInfo gave nothing for some CVars (no default, no flags): default and scope are unknown
        (null), never "" and "machine"."""
        self.write_dump("_retail_", RETAIL_DUMP.replace('["gxWindow"] = {', NO_INFO_CVAR + '["gxWindow"] = {'))
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        entry = self.read_json("cvars", "_retail_.json")["cvars"]["enableCombatText"]
        self.assertIsNone(entry["default"])
        self.assertIsNone(entry["scope"])
        self.assertFalse(entry["synced"])

    def test_macro_limits_from_the_dump(self):
        """T20c: the client's own macro limits go into macro_limits.json with the dump as source; other flavors'
        entries and the comment stay."""
        self.out.mkdir(parents=True)
        (self.out / "macro_limits.json").write_text(json.dumps({"comment": "c", "flavors": {
            "_retail_": {"account": 120, "character": 30, "build": "b", "source": "https://x.example/r"}}}),
            encoding="utf-8")
        self.write_dump("_classic_")
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        data = self.read_json("macro_limits.json")
        self.assertEqual(data["comment"], "c")
        self.assertEqual(data["flavors"]["_retail_"]["source"], "https://x.example/r")
        self.assertEqual(data["flavors"]["_classic_"], {"account": 120, "character": 18, "build": "12.0.5 61234",
                                                        "source": "client dump _classic_ 12.0.5 61234"})

    def test_provisional_copy_for_a_flavor_without_a_dump(self):
        """U1, T20d: --provisional _forever_=_retail_ writes Forever's files as a marked copy of Retail's; a flavor
        with its own dump is never overwritten by a copy."""
        self.write_dump("_retail_")
        (self.wow / "_forever_").mkdir(parents=True)
        code, output = self.run_main("--provisional", "_forever_=_retail_")
        self.assertEqual(code, 0, output)
        marker = "copied from _retail_ until a _forever_ dump exists"
        for folder in ("cvars", "slash_commands"):
            retail, forever = self.read_json(folder, "_retail_.json"), self.read_json(folder, "_forever_.json")
            self.assertEqual(forever["provisional"], marker)
            self.assertEqual(forever["flavor"], "_forever_")
            self.assertEqual(forever["source"], retail["source"], "the copy keeps naming the dump it comes from")
            body = "cvars" if folder == "cvars" else "commands"
            self.assertEqual(forever[body], retail[body])
        limits = self.read_json("macro_limits.json")["flavors"]
        self.assertEqual(limits["_forever_"]["provisional"], marker)
        self.assertEqual((limits["_forever_"]["account"], limits["_forever_"]["character"]), (120, 18))
        self.write_dump("_forever_", RETAIL_DUMP.replace("12.0.5 61234", "1.60.1 70000"))
        code, output = self.run_main("--provisional", "_forever_=_retail_")
        self.assertEqual(code, 0, output)
        self.assertNotIn("provisional", self.read_json("cvars", "_forever_.json"))
        self.assertEqual(self.read_json("cvars", "_forever_.json")["build"], "1.60.1 70000")

    def test_bad_provisional_argument_is_refused(self):
        self.write_dump("_retail_")
        for value in ("_forever_", "_forever_=_forever_", "../x=_retail_", "_forever_=retail"):
            with self.subTest(value=value):
                code, output = self.run_main("--provisional", value)
                self.assertEqual(code, 1, output)
        self.assertFalse(self.out.exists())

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
        for api in ("C_Console.GetAllCommands", "C_CVar.GetCVarInfo", "SLASH_", "/kbdump", "GetBuildInfo",
                    "issecurevariable", "EMOTE", "MAX_ACCOUNT_MACROS", "MAX_CHARACTER_MACROS", "dumpVersion = 2"):
            self.assertIn(api, lua)
        self.assertTrue((REPO_ROOT / "scripts" / "kb_dump" / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
