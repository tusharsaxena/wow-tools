"""Saved Variables Browser staging (spec D5, D12): set value, rename key and delete key on the lazy tree's nodes with
every D5 refusal (top level, positional rename, duplicate keys by Lua identity, nil), unstage, and the per-file plans
Apply writes: staged edits plus ticked search hits, with the overlap rules (a staged edit wins over a hit, a hit
under a staged delete is dropped, a rename and a set on one key combine)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import SVB_FONT, build_sv_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.luasv import key_id
from wowtools.tools.sv_browser import ops
from wowtools.tools.sv_browser.model import SvDocument
from wowtools.tools.sv_browser.ops import FieldEdit, Staging, new_keys, path_text, typed_path
from wowtools.tools.sv_browser.scanner import scan_flavors
from wowtools.tools.sv_browser.search import SearchSpec, run_search


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


class PlanTest(StagingTestBase):
    def test_ticked_hits_become_set_value_edits_keyed_by_file_with_the_search_hash(self):
        hits = self.search(value=SVB_FONT, replacement="Arial")
        plan = self.staging.plans(hits)
        self.assertEqual(sum(len(p.edits) for p in plan.files.values()), len(hits))
        self.assertEqual(plan.dropped, [])
        for file, file_plan in plan.files.items():
            self.assertTrue(file.sha256)
            self.assertTrue(all(e.set_value and e.value == "Arial" and e.hit for e in file_plan.edits))
        self.assertEqual({f.path for f in plan.files}, {h.file.path for h in hits})

    def test_a_contains_hit_sets_the_whole_new_string(self):
        hits = self.search(value="Quadrata", value_mode="contains", replacement="Q")
        plan = self.staging.plans(hits)
        values = {e.value for p in plan.files.values() for e in p.edits}
        self.assertEqual(values, {"Friz Q TT", "friz Q tt"})

    def test_find_only_hits_are_ignored(self):
        hits = self.search(value=SVB_FONT)
        self.assertTrue(hits)
        self.assertEqual(self.staging.plans(hits).files, {})

    def test_a_staged_edit_wins_over_a_hit_on_the_same_value(self):
        doc, node = self.elv("general", "font")
        self.staging.set_value(doc, node, "Mine")
        hits = self.search(value=SVB_FONT, replacement="Arial")
        plan = self.staging.plans(hits)
        (dropped,), = [plan.dropped]
        self.assertEqual(dropped.hit.path, node.path)
        self.assertEqual(dropped.reason, ops.HAS_STAGED_EDIT)
        edits = {e.path: e for e in plan.files[next(f for f in plan.files if f.path == doc.file.path)].edits}
        self.assertEqual(edits[node.path].value, "Mine")
        self.assertFalse(edits[node.path].hit)
        self.assertEqual(edits[("ElvDB", "profiles", "Default", "unitframe", "Font")].value, "Arial")

    def test_a_hit_under_or_on_a_staged_delete_is_dropped(self):
        doc, general = self.elv("general")
        _, font = self.elv("unitframe", "Font")
        self.staging.delete(doc, general)
        self.staging.delete(doc, font)
        hits = [h for h in self.search(value=SVB_FONT, replacement="Arial") if h.file.path == doc.file.path]
        plan = self.staging.plans(hits)
        self.assertEqual(sorted(d.reason for d in plan.dropped), [ops.UNDER_DELETE, ops.UNDER_DELETE])
        (file_plan,) = plan.files.values()
        self.assertTrue(all(e.delete for e in file_plan.edits))

    def test_a_hit_on_a_renamed_key_combines_with_the_rename(self):
        doc, node = self.elv("unitframe", "Font")
        self.staging.rename(doc, node, "font")
        hits = [h for h in self.search(key="Font", match_case=True, value=SVB_FONT, replacement="Arial")
                if h.file.path == doc.file.path]
        plan = self.staging.plans(hits)
        (file_plan,) = plan.files.values()
        (edit,) = file_plan.edits
        self.assertEqual((edit.rename, edit.new_key, edit.set_value, edit.value, edit.hit),
                         (True, "font", True, "Arial", True))
        self.assertIsNone(self.staging.edit_for(doc, node).value)  # staging itself is unchanged

    def test_hits_from_a_file_that_changed_since_it_was_loaded_are_dropped(self):
        doc, node = self.elv("unitframe", "Font")
        self.staging.set_value(doc, node, "Mine")
        path = doc.file.path
        path.write_bytes(path.read_bytes().replace(b"Expressway", b"Expresswax"))
        hits = [h for h in self.search(value=SVB_FONT, replacement="Arial") if h.file.path == path]
        plan = self.staging.plans(hits)
        self.assertEqual({d.reason for d in plan.dropped}, {ops.FILE_CHANGED})
        (file, file_plan), = plan.files.items()
        self.assertEqual(file.sha256, doc.sha256)
        self.assertEqual(len(file_plan.edits), 1)

    def test_the_same_hit_twice_is_dropped_once(self):
        hits = [h for h in self.search(value=SVB_FONT, replacement="Arial") if h.file.path.name == "Questie.lua"]
        plan = self.staging.plans(hits + hits)
        self.assertEqual([d.reason for d in plan.dropped], [ops.DUPLICATE_HIT] * len(hits))

    def test_counts(self):
        doc, node = self.elv("general", "font")
        self.staging.set_value(doc, node, "Mine")
        plan = self.staging.plans(self.search(value=SVB_FONT, replacement="Arial"))
        self.assertEqual(plan.staged, 1)
        self.assertEqual(plan.hits, 6)
        self.assertEqual(len(plan.dropped), 1)
        self.assertEqual(len(plan.units()), len(plan.files))


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
