"""Saved Variables Browser bulk edits on search results (spec D39): one staged edit per hit, the whole value or only
the matched text, renames checked against each key's table, and the hits left out counted by reason."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import SVB_FONT, build_sv_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.luasv import Table
from wowtools.tools.sv_browser import bulk, ops
from wowtools.tools.sv_browser.bulk import (MATCHED, WHOLE, BulkResult, new_value, read_tables, stage_renames,
                                            stage_values, table_key)
from wowtools.tools.sv_browser.model import SvDocument
from wowtools.tools.sv_browser.ops import Staging
from wowtools.tools.sv_browser.scanner import scan_flavors
from wowtools.tools.sv_browser.search import VALUE_CONTAINS, SearchSpec, run_search


class BulkTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = build_sv_tree(Path(tmp.name) / "wow")
        install = WowInstall(self.root)
        self.files = scan_flavors([install.flavor("_retail_"), install.flavor("_classic_era_")]).files()
        self.staging = Staging()

    def search(self, **spec):
        spec = SearchSpec(**spec)
        return spec, run_search(self.files, spec).hits


class ValueTest(BulkTestBase):
    def test_whole_value_on_every_hit(self):
        spec, hits = self.search(value=SVB_FONT)
        result = stage_values(self.staging, hits, lambda hit: new_value(spec, WHOLE, "Arial", hit))
        self.assertEqual((result.staged, result.unchanged, result.left), (len(hits), 0, 0))
        self.assertEqual(self.staging.count, len(hits))
        self.assertEqual({e.value for p in self.staging.plans().files.values() for e in p.edits}, {"Arial"})

    def test_matched_text_replaces_every_occurrence_in_each_string(self):
        spec, hits = self.search(value="quadrata", value_mode=VALUE_CONTAINS)
        stage_values(self.staging, hits, lambda hit: new_value(spec, MATCHED, "Q", hit))
        self.assertEqual({e.value for p in self.staging.plans().files.values() for e in p.edits},
                         {"Friz Q TT", "friz Q tt"})

    def test_matched_mode_needs_a_contains_search(self):
        spec, hits = self.search(value=SVB_FONT)
        self.assertEqual(new_value(spec, MATCHED, "Q", hits[0]), "Q")
        self.assertEqual(new_value(None, MATCHED, "Q", hits[0]), "Q")

    def test_already_staged_and_unchanged_are_counted(self):
        _, hits = self.search(value=SVB_FONT)
        stage_values(self.staging, hits[:2], lambda hit: "Arial")
        with capture_events() as events:
            result = stage_values(self.staging, hits, lambda hit: SVB_FONT)
        same = sum(1 for h in hits[2:] if h.old == SVB_FONT)
        self.assertEqual(result.left_out, {ops.ALREADY_STAGED: 2})
        self.assertEqual(result.unchanged, same)
        self.assertEqual(result.staged, len(hits) - 2 - same)
        (event,) = [e for e in events if e["event"] == "svb.bulk_staged"]
        self.assertEqual(event["data"]["left_out"], 2)
        self.assertEqual(event["data"]["operation"], "set")

    def test_a_loaded_document_read_from_other_bytes_refuses_its_hits(self):
        _, hits = self.search(value=SVB_FONT)
        path = hits[0].file.path
        result = stage_values(self.staging, hits, lambda hit: "Arial", {path: "0" * 64})
        mine = sum(1 for h in hits if h.file.path == path)
        self.assertEqual(result.left_out, {ops.FILE_CHANGED: mine})


class RenameTest(BulkTestBase):
    def test_renames_checked_against_each_table(self):
        _, hits = self.search(key="font")  # font / Font in ElvUI, font in Questie, ...
        tables = read_tables(hits)
        self.assertTrue(all(isinstance(t, Table) for t in tables.values()))
        result = stage_renames(self.staging, hits, "face", tables)
        self.assertEqual(result.left, 0)
        self.assertEqual(result.staged, len(hits))

    def test_two_hits_of_one_table_cannot_take_the_same_key(self):
        _, hits = self.search(key="Font", match_case=True)
        font = [h for h in hits if h.file.path.name == "ElvUI.lua"]
        _, bar = self.search(key="barFont", match_case=True)
        both = font + [h for h in bar if h.file.path == font[0].file.path]  # Font and barFont in unitframe
        self.assertEqual({h.path[:-1] for h in both}, {("ElvDB", "profiles", "Default", "unitframe")})
        result = stage_renames(self.staging, both, "face", read_tables(both))
        self.assertEqual(result.staged, 1)
        self.assertEqual(list(result.left_out), ["The table already has the key face."])

    def test_top_level_and_array_entries_are_left_out(self):
        _, top = self.search(key="DetailsVersion")
        _, array = self.search(value="three", match_case=True)
        hits = top + array
        result = stage_renames(self.staging, hits, "x", read_tables(hits))
        self.assertEqual(result.left_out, {ops.TOP_LEVEL: len(top), ops.ARRAY_RENAME: len(array)})
        self.assertEqual(self.staging.count, 0)

    def test_a_file_changed_since_the_search_leaves_its_hits_out(self):
        _, hits = self.search(key="font", match_case=True)
        path = next(h.file.path for h in hits if h.file.path.name == "ElvUI.lua")
        path.write_bytes(path.read_bytes().replace(b"Expressway", b"Expresswax"))
        tables = read_tables(hits)
        mine = [h for h in hits if h.file.path == path]
        self.assertEqual({tables[table_key(h)] for h in mine}, {ops.FILE_CHANGED})
        result = stage_renames(self.staging, hits, "face", tables)
        self.assertEqual(result.left_out, {ops.FILE_CHANGED: len(mine)})

    def test_read_tables_reports_progress_per_file(self):
        _, hits = self.search(value=SVB_FONT)
        calls = []
        read_tables(hits, lambda done, total, name: calls.append((done, total)))
        files = len({h.file.path for h in hits})
        self.assertEqual(calls, [(n, files) for n in range(1, files + 1)])

    def test_browse_sees_a_hit_rename(self):
        _, hits = self.search(key="Font", match_case=True)
        elv = [h for h in hits if h.file.path.name == "ElvUI.lua"]
        stage_renames(self.staging, elv, "face", read_tables(elv))
        doc = SvDocument(elv[0].file)
        node = doc.roots()[0]
        for key in elv[0].path[1:]:
            node = next(n for n in doc.children(node) if n.key == key)
        self.assertEqual(self.staging.edit_for(doc, node).new_key, "face")


class ResultTextTest(unittest.TestCase):
    def test_text_says_what_was_staged_and_left_out(self):
        result = BulkResult("set", staged=3, unchanged=1)
        result.left_out.update({ops.ALREADY_STAGED: 2, ops.UNDER_DELETE: 1})
        text = result.text()
        self.assertIn("Staged 3 edits.", text)
        self.assertIn("1 result already had it", text)
        self.assertIn("3 results left out:", text)
        self.assertIn(f"2 · {ops.ALREADY_STAGED}", text)
        self.assertEqual(bulk.MODES[0][0], MATCHED)


if __name__ == "__main__":
    unittest.main()
