"""Saved Variables Browser staging (spec D5, D12): set value, rename key and delete key on the lazy tree's nodes with
every D5 refusal (top level, positional rename, duplicate keys by Lua identity, nil), unstage, and the per-file plans
Apply writes (the staged edits only), and staging search hits (D39: one edit per hit, refused when already staged,
under a staged delete, from other bytes, or against D5)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import SVB_FONT, build_sv_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.luasv import encode_value, key_id
from wowtools.tools.sv_browser import ops
from wowtools.tools.sv_browser.bulk import MATCHED, new_value, stage_values
from wowtools.tools.sv_browser.model import SvDocument
from wowtools.tools.sv_browser.ops import FieldEdit, Staging, new_keys, path_text, typed_path
from wowtools.tools.sv_browser.scanner import scan_flavors
from wowtools.tools.sv_browser.search import SearchScope, SearchSpec, run_search


def by_key(nodes, key):
    return next(n for n in nodes if key_id(n.key) == key_id(key))


class StagingTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = build_sv_tree(Path(tmp.name) / "wow")
        install = WowInstall(self.root)
        self.files = scan_flavors([install.flavor("_retail_"), install.flavor("_classic_era_")]).files()
        self.docs = {}
        self.staging = Staging()

    def doc(self, name, owner="Account-wide", account="ACCT1", flavor="_retail_"):
        sv = next(f for f in self.files if f.path.name == name and f.owner == owner and f.account == account
                  and f.flavor.folder == flavor)
        return self.docs.setdefault(sv.path, SvDocument(sv))

    def node(self, doc, *keys):
        nodes = doc.roots()
        node = None
        for key in keys:
            node = by_key(nodes, key)
            nodes = doc.children(node) if node.is_table else []
        return node

    def elv(self, *keys):
        doc = self.doc("ElvUI.lua")
        return doc, self.node(doc, "ElvDB", "profiles", "Default", *keys)

    def search(self, **spec):
        return run_search(self.files, SearchSpec(**spec)).hits


class SetValueTest(StagingTestBase):
    def test_a_value_is_staged_with_the_documents_hash(self):
        doc, node = self.elv("general", "font")
        result = self.staging.set_value(doc, node, "Arial")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.staging.edit_for(doc, node),
                         FieldEdit(("ElvDB", "profiles", "Default", "general", "font"), set_value=True,
                                   value="Arial"))
        self.assertEqual(self.staging.count, 1)
        plan = self.staging.plans()
        (file, file_plan), = plan.files.items()
        self.assertEqual(file.path, doc.file.path)
        self.assertEqual(file.sha256, doc.sha256)
        self.assertEqual(file_plan.file, file)

    def test_the_type_may_change(self):
        doc, node = self.elv("general", "font")
        for value in (12, 2.5, True, False, "x"):
            self.assertTrue(self.staging.set_value(doc, node, value).ok, value)
            self.assertEqual(self.staging.edit_for(doc, node).value, value)
            self.assertIs(type(self.staging.edit_for(doc, node).value), type(value))

    def test_nil_and_tables_and_bad_numbers_are_refused(self):
        doc, node = self.elv("general", "font")
        result = self.staging.set_value(doc, node, None)
        self.assertFalse(result.ok)
        self.assertIn("delete", result.message)
        for value in (float("inf"), float("nan"), 2 ** 53 + 1, [1], b"x"):
            self.assertFalse(self.staging.set_value(doc, node, value).ok, value)
        doc, table = self.elv("general")
        self.assertFalse(self.staging.set_value(doc, table, "x").ok)
        top = self.node(doc, "ElvDB")
        self.assertFalse(self.staging.set_value(doc, top, "x").ok)
        self.assertEqual(self.staging.count, 0)

    def test_a_top_level_scalar_and_a_nil_slot_may_be_set(self):
        doc = self.doc("Details.lua")
        self.assertTrue(self.staging.set_value(doc, self.node(doc, "DetailsVersion"), 5).ok)
        elv = self.doc("ElvUI.lua")
        self.assertTrue(self.staging.set_value(elv, self.node(elv, "ElvVersion"), "13.0").ok)
        self.assertTrue(self.staging.set_value(doc, self.node(doc, "_detalhes_global", "bars", 2), "two").ok)
        self.assertEqual(self.staging.count, 3)

    def test_setting_the_value_already_written_stages_nothing(self):
        doc, node = self.elv("general", "fontSize")
        result = self.staging.set_value(doc, node, 12)
        self.assertTrue(result.ok)
        self.assertIsNone(self.staging.edit_for(doc, node))
        self.staging.set_value(doc, node, 13)
        self.staging.set_value(doc, node, 12)
        self.assertIsNone(self.staging.edit_for(doc, node))

    def test_staging_logs_an_event(self):
        doc, node = self.elv("general", "font")
        with capture_events() as events:
            self.staging.set_value(doc, node, "Arial")
            self.staging.unstage(doc, node)
        names = [e["event"] for e in events]
        self.assertEqual(names, ["svb.staged", "svb.unstaged"])
        self.assertEqual(events[0]["data"]["operation"], "set")
        self.assertEqual(events[0]["data"]["path"], doc.file.rel)
        self.assertEqual(events[0]["data"]["key"], "ElvDB › profiles › Default › general › font")


    def test_an_equal_value_written_differently_stages_nothing(self):
        doc = self.doc("Details.lua")
        node = self.node(doc, "_detalhes_global", "tooltip", "text")  # written with \\226\\128\\148
        self.assertNotEqual(ops.encode_value(node.value.value), doc.data[node.value.start:node.value.end])
        result = self.staging.set_value(doc, node, node.value.value)
        self.assertEqual((result.ok, result.message), (True, "unchanged"))
        self.assertIsNone(self.staging.edit_for(doc, node))
        elv, scale = self.elv("general", "fontSize")
        self.assertTrue(self.staging.set_value(elv, scale, 12.0).ok)  # 12.0 is the number 12 in Lua
        self.assertIsNone(self.staging.edit_for(elv, scale))
        self.assertTrue(self.staging.set_value(elv, scale, "12").ok)  # a string is not the number
        self.assertIsNotNone(self.staging.edit_for(elv, scale))


class ProblemTest(StagingTestBase):
    """set_problem / rename_problem / delete_problem say what set_value / rename / delete would refuse, staging
    nothing (the popups check with them)."""

    def test_problems_match_the_refusals_and_stage_nothing(self):
        doc, font = self.elv("unitframe", "Font")
        self.assertIsNone(self.staging.set_problem(doc, font, "Arial"))
        self.assertIn("delete", self.staging.set_problem(doc, font, None))
        self.assertIsNone(self.staging.rename_problem(doc, font, "font"))
        self.assertIn("already", self.staging.rename_problem(doc, font, "barFont"))
        self.assertEqual(self.staging.rename_problem(doc, font, ""), ops.EMPTY_KEY)
        self.assertIsNone(self.staging.delete_problem(doc, font))
        self.assertEqual(self.staging.count, 0)
        details = self.doc("Details.lua")
        self.assertEqual(self.staging.rename_problem(details, self.node(details, "DetailsVersion"), "x"),
                         ops.TOP_LEVEL)
        self.assertEqual(self.staging.rename_problem(details, self.node(details, "_detalhes_global", "bars", 1),
                                                     "x"), ops.ARRAY_RENAME)
        self.assertEqual(self.staging.delete_problem(details, self.node(details, "DetailsVersion")), ops.TOP_LEVEL)
        _, unit = self.elv("unitframe")
        self.staging.delete(doc, unit)
        self.assertEqual(self.staging.set_problem(doc, font, "x"), ops.INSIDE_DELETE)
        self.assertEqual(self.staging.rename_problem(doc, font, "x"), ops.INSIDE_DELETE)
        self.assertEqual(self.staging.delete_problem(doc, font), ops.INSIDE_DELETE)
        self.assertEqual(self.staging.delete_problem(doc, unit), ops.INSIDE_DELETE)  # the deleted key itself


class ParseKeyTest(unittest.TestCase):
    def test_keys_are_read_as_the_tree_shows_them(self):
        for text, key in (("font", "font"), ("[5]", 5), ("[-2]", -2), ("[2.5]", 2.5), ("[true]", True),
                          ("[false]", False), ('["[5]"]', "[5]"), ('[""]', ""), ("[x]", "[x]"), (" a ", " a "),
                          ("[ 7 ]", 7)):
            parsed = ops.parse_key(text)
            self.assertEqual(parsed, key, text)
            self.assertIs(type(parsed), type(key), text)

    def test_a_bad_number_key_is_refused(self):
        for text in ("[1e999]", "[0.1000000000000000055511151231257827]"):
            with self.assertRaises(ValueError):
                ops.parse_key(text)

    def test_key_input_is_the_inverse_of_parse_key(self):
        for key in ("font", 5, 2.5, True, False, "[5]", ""):
            self.assertEqual(ops.parse_key(ops.key_input(key)), key)
            self.assertIs(type(ops.parse_key(ops.key_input(key))), type(key))


class RenameTest(StagingTestBase):
    def test_a_rename_is_staged(self):
        doc, node = self.elv("general", "font")
        self.assertTrue(self.staging.rename(doc, node, "end").ok)
        edit = self.staging.edit_for(doc, node)
        self.assertTrue(edit.rename)
        self.assertEqual(edit.new_key, "end")
        self.assertFalse(edit.set_value)

    def test_top_level_and_positional_keys_are_never_renamed(self):
        doc = self.doc("Details.lua")
        result = self.staging.rename(doc, self.node(doc, "_detalhes_global"), "x")
        self.assertFalse(result.ok)
        self.assertIn("top-level", result.message)
        result = self.staging.rename(doc, self.node(doc, "_detalhes_global", "bars", 1), "x")
        self.assertFalse(result.ok)
        self.assertIn("array", result.message)

    def test_a_key_already_in_the_table_is_refused_by_lua_identity(self):
        doc, node = self.elv("unitframe", "Font")
        for key in ("barFont", 1, 1.0, 2, True, False):
            result = self.staging.rename(doc, node, key)
            self.assertFalse(result.ok, key)
            self.assertIn("already", result.message)
        for key in ("font", "FONT", 3, "1", "true"):
            self.assertTrue(self.staging.rename(doc, node, key).ok, key)

    def test_empty_and_unwritable_keys_are_refused(self):
        doc, node = self.elv("unitframe", "Font")
        for key in ("", None, float("nan"), float("inf"), [1]):
            self.assertFalse(self.staging.rename(doc, node, key).ok, key)

    def test_staged_renames_and_deletes_count_for_duplicates(self):
        doc, font = self.elv("unitframe", "Font")
        _, bar = self.elv("unitframe", "barFont")
        self.assertTrue(self.staging.rename(doc, bar, "x").ok)
        self.assertFalse(self.staging.rename(doc, font, "x").ok)
        self.assertTrue(self.staging.rename(doc, font, "barFont").ok)  # barFont is renamed away
        result = self.staging.unstage(doc, bar)  # would bring barFont back next to the renamed Font
        self.assertFalse(result.ok)
        self.assertIn("barFont", result.message)
        self.assertTrue(self.staging.delete(doc, bar).ok)
        self.assertTrue(self.staging.edit_for(doc, bar).delete)

    def test_renaming_to_its_own_key_drops_the_rename(self):
        doc, node = self.elv("unitframe", "Font")
        self.staging.rename(doc, node, "x")
        self.assertTrue(self.staging.rename(doc, node, "Font").ok)
        self.assertIsNone(self.staging.edit_for(doc, node))

    def test_rename_and_set_on_one_key_combine(self):
        doc, node = self.elv("unitframe", "Font")
        self.staging.rename(doc, node, "font")
        self.staging.set_value(doc, node, "Arial")
        edit = self.staging.edit_for(doc, node)
        self.assertEqual((edit.rename, edit.new_key, edit.set_value, edit.value), (True, "font", True, "Arial"))
        self.assertEqual(self.staging.count, 1)


class DeleteTest(StagingTestBase):
    def test_top_level_is_never_deleted(self):
        doc = self.doc("Details.lua")
        result = self.staging.delete(doc, self.node(doc, "DetailsVersion"))
        self.assertFalse(result.ok)
        self.assertIn("top-level", result.message)

    def test_an_array_entry_may_be_deleted_with_a_warning(self):
        doc = self.doc("Details.lua")
        node = self.node(doc, "_detalhes_global", "bars", 2)
        result = self.staging.delete(doc, node)
        self.assertTrue(result.ok)
        self.assertEqual(result.warning, ops.SHIFT_WARNING)
        self.assertTrue(self.staging.edit_for(doc, node).positional)
        keyed = self.staging.delete(doc, self.node(doc, "_detalhes_global", "font_face"))
        self.assertIsNone(keyed.warning)

    def test_a_delete_drops_the_edits_inside_it_and_refuses_new_ones(self):
        doc, font = self.elv("general", "font")
        _, size = self.elv("general", "fontSize")
        _, general = self.elv("general")
        self.staging.set_value(doc, font, "Arial")
        self.staging.rename(doc, size, "size")
        result = self.staging.delete(doc, general)
        self.assertTrue(result.ok)
        self.assertEqual(result.dropped, 2)
        self.assertEqual(self.staging.count, 1)
        refused = self.staging.set_value(doc, font, "Arial")
        self.assertFalse(refused.ok)
        self.assertIn("delete", refused.message)
        self.assertFalse(self.staging.rename(doc, general, "x").ok)
        self.assertTrue(self.staging.deleted_above(doc, font))

    def test_a_delete_replaces_a_set_and_rename_on_the_same_key(self):
        doc, node = self.elv("general", "font")
        self.staging.set_value(doc, node, "Arial")
        self.staging.rename(doc, node, "x")
        self.staging.delete(doc, node)
        self.assertEqual(self.staging.edit_for(doc, node), FieldEdit(node.path, delete=True))

    def test_unstage_and_clear(self):
        doc, node = self.elv("general", "font")
        self.staging.delete(doc, node)
        self.assertTrue(self.staging.unstage(doc, node).ok)
        self.assertEqual(self.staging.count, 0)
        self.assertFalse(self.staging.unstage(doc, node).ok)  # nothing staged there
        self.staging.delete(doc, node)
        self.staging.clear()
        self.assertEqual(self.staging.count, 0)
        self.assertEqual(self.staging.plans().files, {})


class HitStagingTest(StagingTestBase):
    """D39: a bulk edit on search hits stages one edit per hit, in the same staging as Browse."""

    def font_hits(self, **spec):
        return self.search(value=SVB_FONT, **spec)

    def test_a_hit_value_is_staged_with_the_search_hash_and_browse_sees_it(self):
        hit = next(h for h in self.font_hits() if h.file.path.name == "ElvUI.lua" and h.key == "font")
        result = self.staging.stage_hit_value(hit, "Arial")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(self.staging.hit_edit(hit), FieldEdit(hit.path, set_value=True, value="Arial"))
        doc, node = self.elv("general", "font")
        self.assertEqual(self.staging.edit_for(doc, node), self.staging.hit_edit(hit))
        (file, file_plan), = self.staging.plans().files.items()
        self.assertEqual((file.path, file.sha256), (hit.file.path, hit.sha256))
        self.assertEqual(file_plan.edits, [FieldEdit(hit.path, set_value=True, value="Arial")])

    def test_the_value_already_there_stages_nothing(self):
        hit = self.font_hits()[0]
        result = self.staging.stage_hit_value(hit, hit.old)
        self.assertEqual((result.ok, result.message), (True, "unchanged"))
        self.assertEqual(self.staging.count, 0)

    def test_a_hit_written_with_other_escapes_but_the_same_value_stages_nothing(self):
        """D29: Details' text is written with escapes (\\226\\128\\148) that encode_value writes otherwise; replacing
        b with b is the value already there, so nothing is staged (no rewrite of the escapes)."""
        spec = SearchSpec(value="b", value_mode="contains", match_case=True, scope=SearchScope(addon="details"))
        hits = run_search(self.files, spec).hits
        self.assertTrue(hits)
        for hit in hits:
            self.assertNotEqual(encode_value(hit.old), hit.old_bytes)  # only the value compare keeps it unchanged
        result = stage_values(self.staging, hits, lambda hit: new_value(spec, MATCHED, "b", hit))
        self.assertEqual((result.staged, result.unchanged), (0, len(hits)))
        self.assertEqual(self.staging.count, 0)

    def test_already_staged_and_under_a_delete_are_refused(self):
        doc, node = self.elv("general", "font")
        self.staging.set_value(doc, node, "Mine")
        _, unitframe = self.elv("unitframe")
        self.staging.delete(doc, unitframe)
        hits = {h.key: h for h in self.font_hits() if h.file.path == doc.file.path}
        self.assertEqual(self.staging.stage_hit_value(hits["font"], "Arial").message, ops.ALREADY_STAGED)
        self.assertEqual(self.staging.stage_hit_value(hits["Font"], "Arial").message, ops.UNDER_DELETE)
        self.assertEqual(self.staging.edit_for(doc, node).value, "Mine")
        self.assertTrue(self.staging.hit_deleted_above(hits["Font"]))

    def test_a_hit_from_bytes_other_than_the_staged_or_loaded_ones_is_refused(self):
        doc, node = self.elv("unitframe", "barFont")
        self.staging.set_value(doc, node, "Mine")
        path = doc.file.path
        path.write_bytes(path.read_bytes().replace(b"Expressway", b"Expresswax"))
        hit = next(h for h in self.font_hits() if h.file.path == path)
        # a new search reads the same changed bytes, so the reason must not stop at "search again" (rescan)
        self.assertEqual(self.staging.stage_hit_value(hit, "Arial").message, ops.BYTES_DIFFER)
        self.assertIn("rescan", ops.BYTES_DIFFER)
        other = next(h for h in self.font_hits() if h.file.path.name == "Questie.lua")
        self.assertEqual(self.staging.stage_hit_value(other, "Arial", doc_sha="0" * 64).message, ops.BYTES_DIFFER)

    def test_a_bad_value_is_refused(self):
        hit = self.font_hits()[0]
        self.assertEqual(self.staging.stage_hit_value(hit, None).message, ops.NIL_VALUE)
        self.assertTrue(self.staging.stage_hit_value(hit, float("inf")).message)
        self.assertEqual(self.staging.count, 0)

    def test_hit_renames_follow_d5(self):
        hits = self.search(key="font", match_case=True)
        elv = next(h for h in hits if h.file.path.name == "ElvUI.lua")
        table = ops_table(elv)
        self.assertTrue(self.staging.stage_hit_rename(elv, "face", table).ok)
        self.assertEqual(self.staging.hit_edit(elv), FieldEdit(elv.path, rename=True, new_key="face"))
        top = self.search(key="ElvVersion")[0]
        self.assertEqual(self.staging.stage_hit_rename(top, "x", None).message, ops.TOP_LEVEL)
        array = next(h for h in self.search(value="one", match_case=True) if h.file.path.name == "Details.lua")
        self.assertEqual(self.staging.stage_hit_rename(array, "x", ops_table(array)).message, ops.ARRAY_RENAME)
        self.assertEqual(self.staging.stage_hit_rename(elv, "zzz", table).message, ops.ALREADY_STAGED)
        other = next(h for h in self.search(key="fontSize") if h.file.path.name == "ElvUI.lua")
        self.assertEqual(self.staging.stage_hit_rename(other, "", table).message, ops.EMPTY_KEY)
        # a key the table holds, or one another staged rename takes, is a duplicate
        self.assertIn("already has the key", self.staging.stage_hit_rename(other, "autoRepair", table).message)
        self.assertIn("already has the key", self.staging.stage_hit_rename(other, "face", table).message)
        self.assertEqual(self.staging.stage_hit_rename(other, "fontSize", table).message, "unchanged")
        self.assertEqual(self.staging.count, 1)

    def test_unstage_a_hit(self):
        hit = self.font_hits()[0]
        self.assertEqual(self.staging.unstage_hit(hit).message, ops.NOTHING_STAGED)
        self.staging.stage_hit_value(hit, "Arial")
        self.assertTrue(self.staging.unstage_hit(hit).ok)
        self.assertEqual(self.staging.count, 0)

    def test_unstaging_a_hit_rename_whose_table_can_not_be_read_gives_the_reason(self):
        cap = next(h for h in self.search(key="Font", match_case=True) if h.file.path.name == "ElvUI.lua")
        self.assertTrue(self.staging.stage_hit_rename(cap, "face", ops_table(cap)).ok)
        result = self.staging.unstage_hit(cap, ops.FILE_CHANGED)
        self.assertEqual((result.ok, result.message), (False, ops.FILE_CHANGED))
        self.assertEqual(self.staging.count, 1)

    def test_unstaging_a_hit_rename_that_would_leave_a_duplicate_is_refused(self):
        cap = next(h for h in self.search(key="Font", match_case=True) if h.file.path.name == "ElvUI.lua")
        self.assertTrue(self.staging.stage_hit_rename(cap, "face", ops_table(cap)).ok)
        doc, bar = self.elv("unitframe", "barFont")
        self.assertTrue(self.staging.rename(doc, bar, "Font").ok)  # Font is free once renamed away
        result = self.staging.unstage_hit(cap, ops_table(cap))
        self.assertFalse(result.ok)
        self.assertIn("twice", result.message)
        self.assertTrue(self.staging.unstage(doc, bar).ok)
        self.assertTrue(self.staging.unstage_hit(cap, ops_table(cap)).ok)


class PlanTest(StagingTestBase):
    def test_the_plan_is_the_staged_edits_only(self):
        doc, node = self.elv("general", "font")
        self.staging.set_value(doc, node, "Mine")
        for hit in self.search(value=SVB_FONT):
            self.staging.stage_hit_value(hit, "Arial")
        plan = self.staging.plans()
        self.assertEqual(plan.staged, 7)
        self.assertEqual(sum(len(p.edits) for p in plan.files.values()), 7)
        self.assertEqual(len(plan.units()), len(plan.files))
        values = {e.path: e.value for p in plan.files.values() for e in p.edits}
        self.assertEqual(values[node.path], "Mine")
        self.assertEqual(set(values.values()), {"Mine", "Arial"})


def ops_table(hit):
    """The table holding a hit's key (what bulk.read_tables gives the rename)."""
    from wowtools.tools.sv_browser.bulk import read_tables
    return read_tables([hit])[bulk_key(hit)]


def bulk_key(hit):
    from wowtools.tools.sv_browser.bulk import table_key
    return table_key(hit)


class HelpersTest(unittest.TestCase):
    def test_path_text_and_typed_path(self):
        self.assertEqual(path_text(("Db", "a b", 5, True, 2.5)), "Db › a b › [5] › [true] › [2.5]")
        self.assertEqual(typed_path(("Db", 1.0, True)), (("str", "Db"), ("int", 1), ("bool", True)))

    def test_new_keys_shift_positional_entries_after_a_delete(self):
        from wowtools.core.luasv import parse
        data = b'T = {\n"a", -- [1]\n"b", -- [2]\n["k"] = 1,\n"c", -- [3]\n}\n'
        table = parse(data).assignments[0].value
        edits = {("int", 1): FieldEdit(("T", 1), delete=True, positional=True),
                 ("str", "k"): FieldEdit(("T", "k"), rename=True, new_key=9)}
        self.assertEqual(new_keys(table.fields, edits), [None, ("int", 1), ("int", 9), ("int", 2)])


if __name__ == "__main__":
    unittest.main()
