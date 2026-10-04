"""compile_file + verify_edit: staged changes become exact byte edits (spec §8)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import luasv, model, ops, scanner, verify


class CompileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_ace_tree(Path(tmp.name) / "wow")
        self.scan = scanner.ScanResult([scanner.scan_flavor(WowInstall(root).flavor("_retail_"), account="ACCT1")])
        self.staging = ops.Staging.from_scan(self.scan)

    def key(self, sv_name):
        return next(k for k in self.staging.states if k.sv_name == sv_name)

    def compile(self, sv_name):
        key = self.key(sv_name)
        states = [s for s in self.staging.states.values() if s.file.path == key.path and s.changed]
        data = key.path.read_bytes()
        edit = ops.compile_file(states, data)
        self.assertEqual(verify.verify_edit(edit, data), [])
        return data, edit

    def reparse(self, data, sv_name):
        dbs, _ = model.find_dbs(luasv.parse(data, model.ace_descend), data)
        return next(db for db in dbs if db.sv_name == sv_name)

    def test_no_change_is_byte_identical(self):
        key = self.key("KickCDDB")
        data = key.path.read_bytes()
        edit = ops.compile_file([], data)
        self.assertEqual(edit.data, data)
        self.assertEqual(verify.verify_edit(edit, data), [])

    def test_one_reassign_changes_exactly_one_span(self):
        self.staging.assign({self.key("ElvDB"): ["Kaelys - Realm1"]}, "Healer")
        old, edit = self.compile("ElvDB")
        self.assertEqual(edit.data, old.replace(b'["Kaelys - Realm1"] = "Default",\r\n["Mierin',
                                                b'["Kaelys - Realm1"] = "Healer",\r\n["Mierin', 1))
        self.assertEqual(edit.changes, ['ElvDB: "Kaelys - Realm1": "Default" to "Healer"'])

    def test_delete_removes_main_and_namespace_entries_and_fixes_lds(self):
        self.staging.delete({self.key("ElvDB"): ["Healer"]}, "Default")
        old, edit = self.compile("ElvDB")
        db = self.reparse(edit.data, "ElvDB")
        self.assertEqual(list(db.profiles), ["Default"])
        self.assertEqual(list(db.namespaces["Bags"].entries), ["Default"])
        self.assertEqual(db.profile_keys["Mierin - Khaz Modan"], "Default")
        self.assertEqual(db.lds["Kaelys - Realm1"].specs[2].value.value, "Default")
        self.assertNotIn(b'["Healer"]', edit.data)
        private_old = old[old.index(b"ElvPrivateDB"):]
        self.assertTrue(edit.data.endswith(private_old))  # the other database is byte-identical

    def test_rename_rewrites_keys_everywhere(self):
        self.staging.rename(self.key("ElvDB"), "Healer", 'My "Heals"')
        _, edit = self.compile("ElvDB")
        self.assertIn(b'["My \\"Heals\\""] = {', edit.data)
        db = self.reparse(edit.data, "ElvDB")
        self.assertEqual(list(db.profiles), ["Default", 'My "Heals"'])
        self.assertEqual(list(db.namespaces["Bags"].entries), ["Default", 'My "Heals"'])

    def test_copy_inserts_verbatim_bytes_in_main_and_namespaces(self):
        self.staging.copy(self.key("ElvDB"), "Healer", "Tank")
        old, edit = self.compile("ElvDB")
        db = self.reparse(edit.data, "ElvDB")
        new_value = db.profiles["Tank"].field.value
        old_db = self.reparse(old, "ElvDB")
        source = old_db.profiles["Healer"].field.value
        self.assertEqual(edit.data[new_value.start:new_value.end], old[source.start:source.end])
        self.assertIn("Tank", db.namespaces["Bags"].entries)
        self.assertIn(b'["Tank"] = {\r\n["x"] = 2,\r\n},\r\n}', edit.data)

    def test_composed_copy_rename_delete(self):
        k = self.key("ElvDB")
        self.staging.copy(k, "Healer", "A")
        self.staging.rename(k, "A", "C")
        self.staging.delete({k: ["Healer"]}, "C")
        old, edit = self.compile("ElvDB")
        db = self.reparse(edit.data, "ElvDB")
        self.assertEqual(list(db.profiles), ["Default", "C"])
        self.assertEqual(db.profile_keys["Mierin - Khaz Modan"], "C")
        old_db = self.reparse(old, "ElvDB")
        src = old_db.profiles["Healer"].field.value
        new = db.profiles["C"].field.value
        self.assertEqual(edit.data[new.start:new.end], old[src.start:src.end])

    def test_remove_leftover_removes_the_line(self):
        self.staging.remove_leftovers({self.key("KickCDDB"): ["Gone - Realm1"]})
        old, edit = self.compile("KickCDDB")
        self.assertEqual(edit.data, old.replace(b'["Gone - Realm1"] = "Default",\r\n', b"", 1))

    def test_untouched_bytes_survive(self):
        self.staging.delete({self.key("KickCDDB"): ["Backup"]}, "Default")
        _, edit = self.compile("KickCDDB")
        self.assertIn(b'["scale"] = 0.6000000000000001,\r\n["text"] = "a\\"b\\\\c\\n\\000",\r\n[114052] = true,',
                      edit.data)
        self.assertIn(b'KickCDPerfDB = {\r\n["runs"] = 3,\r\n}', edit.data)
        self.assertIn(b'["schemaVersion"] = 3,', edit.data)

    def test_two_databases_in_one_file(self):
        self.staging.everyone_to_default([self.key("HandyNotesDB")])
        self.staging.copy(self.key("HandyNotes_MapNotesDB"), "Default", "Spare")
        _, edit = self.compile("HandyNotesDB")
        self.assertEqual(set(edit.expected), {"HandyNotesDB", "HandyNotes_MapNotesDB"})

    def test_copy_into_a_table_without_trailing_comma(self):
        data = b'X = {\n["profileKeys"] = {\n["A - R"] = "P"\n},\n["profiles"] = { ["P"] = { ["v"] = 1 } }\n}\n'
        path = Path(self.scan.flavors[0].flavor.account_dir / "ACCT1" / "SavedVariables" / "X.lua")
        path.write_bytes(data)
        dbs, _ = model.find_dbs(luasv.parse(data, model.ace_descend), data)
        file = scanner.SvFile(path, self.scan.flavors[0].flavor, "ACCT1", None, len(data), 0.0,
                              scanner.sha256_of(data))
        state = ops.DbState.fresh(file, dbs[0], frozenset())
        staging = ops.Staging({state.key: state})
        staging.copy(state.key, "P", "Q")
        edit = ops.compile_file([state], data)
        self.assertEqual(verify.verify_edit(edit, data), [])
        self.assertEqual(list(self.reparse(edit.data, "X").profiles), ["P", "Q"])


class VerifyTest(unittest.TestCase):
    def test_catches_a_wrong_mapping_and_a_changed_neighbour(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_ace_tree(Path(tmp.name) / "wow")
        scan = scanner.ScanResult([scanner.scan_flavor(WowInstall(root).flavor("_retail_"), account="ACCT1")])
        staging = ops.Staging.from_scan(scan)
        key = next(k for k in staging.states if k.sv_name == "KickCDDB")
        staging.assign({key: ["Kaelys - Realm1"]}, "Backup")
        data = key.path.read_bytes()
        edit = ops.compile_file([staging.state(key)], data)
        bad = ops.FileEdit(edit.file, edit.data.replace(b'"Backup",', b'"Other",', 1), edit.changes, edit.expected)
        self.assertTrue(verify.verify_edit(bad, data))
        bad = ops.FileEdit(edit.file, edit.data.replace(b'["runs"] = 3', b'["runs"] = 4'), edit.changes, edit.expected)
        self.assertTrue(any("KickCDPerfDB" in p for p in verify.verify_edit(bad, data)))
        bad = ops.FileEdit(edit.file, edit.data.replace(b'["schemaVersion"] = 3', b'["schemaVersion"] = 9'),
                           edit.changes, edit.expected)
        self.assertTrue(any("global" in p for p in verify.verify_edit(bad, data)))
        bad = ops.FileEdit(edit.file, edit.data[:-10], edit.changes, edit.expected)
        self.assertTrue(verify.verify_edit(bad, data))
