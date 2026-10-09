"""Saved Variables Browser compile and verify (spec D19): a file's plan becomes byte splices re-located from each
edit's path in the bytes Apply read (value spans re-encoded, keys always in bracket form, deletes by remove span),
every untouched byte stays as it was (CRLF, escapes, comments), and verify re-reads the result: the same
assignments and text between them, each touched table exactly the expected ordered (key, value) list, and nothing
changed outside the edits. Plus the plans fed through the shared pipeline's dry run."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.fixtures import SVB_DETAILS, SVB_ELVUI, SVB_FONT, _write_lua, ace_lua, build_sv_tree, cpu_seconds
from wowtools.core import sv_apply
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.luasv import decode_string, key_id, parse
from wowtools.core.svfiles import SvFile, sha256_of
from wowtools.tools.sv_browser.bulk import MATCHED, new_value, stage_values
from wowtools.tools.sv_browser.compile import compile_file
from wowtools.tools.sv_browser.events import SV_TOOL
from wowtools.tools.sv_browser.model import SvDocument
from wowtools.tools.sv_browser.ops import FieldEdit, FilePlan, Staging
from wowtools.tools.sv_browser.scanner import scan_flavors
from wowtools.tools.sv_browser.search import SearchSpec, run_search
from wowtools.tools.sv_browser.verify import verify_edit


def by_key(nodes, key):
    return next(n for n in nodes if key_id(n.key) == key_id(key))


class CompileTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.flavor = Flavor("_retail_", self.tmp / "wow" / "_retail_")
        self.staging = Staging()

    def doc(self, text: str, name: str = "Addon.lua") -> SvDocument:
        path = _write_lua(self.flavor.account_dir / "ACCT" / "SavedVariables" / name, text)
        data = path.read_bytes()
        return SvDocument(SvFile(path, self.flavor, "ACCT", None, len(data), 0.0, ""))

    def node(self, doc, *keys):
        nodes = doc.roots()
        node = None
        for key in keys:
            node = by_key(nodes, key)
            nodes = doc.children(node) if node.is_table else []
        return node

    def stage(self, doc, op, keys, *args):
        result = getattr(self.staging, op)(doc, self.node(doc, *keys), *args)
        self.assertTrue(result.ok, result.message)

    def run_plan(self, doc):
        """Compile the doc's plan against its bytes now; assert it verifies; return (old, edit)."""
        plan = self.staging.plans()
        (file, file_plan), = [(f, p) for f, p in plan.files.items() if f.path == doc.file.path]
        old = file.path.read_bytes()
        edit = compile_file(file, file_plan, old)
        self.assertEqual(edit.problems, [])
        self.assertEqual(verify_edit(edit, old), [])
        return old, edit


class SpliceTest(CompileTestBase):
    def test_a_value_edit_changes_only_its_literal_and_keeps_crlf(self):
        doc = self.doc(SVB_ELVUI)
        self.stage(doc, "set_value", ("ElvDB", "profiles", "Default", "general", "font"), "Arial Narrow")
        old, edit = self.run_plan(doc)
        self.assertEqual(edit.data, old.replace(f'["font"] = "{SVB_FONT}"'.encode(), b'["font"] = "Arial Narrow"'))
        self.assertEqual(edit.data.count(b"\r\n"), old.count(b"\r\n"))
        self.assertNotIn(b"\n", edit.data.replace(b"\r\n", b""))
        self.assertEqual(edit.changes,
                         [f'ElvDB › profiles › Default › general › font: "{SVB_FONT}" → "Arial Narrow"'])
        self.assertIs(edit.file, edit.plan.file)

    def test_type_changes(self):
        doc = self.doc(SVB_ELVUI)
        keys = ("ElvDB", "profiles", "Default", "general")
        self.stage(doc, "set_value", keys + ("font",), 12)
        self.stage(doc, "set_value", keys + ("fontSize",), "12")
        self.stage(doc, "set_value", keys + ("scale",), True)
        self.stage(doc, "set_value", keys + ("autoRepair",), 0.1)
        _, edit = self.run_plan(doc)
        general = parse(edit.data).assignments[0].value.get("profiles").value.get("Default").value \
            .get("general").value
        values = {f.key: f.value.value for f in general.fields}
        self.assertEqual(values, {"font": 12, "fontSize": "12", "scale": True, "autoRepair": 0.1})
        self.assertIn(b'["scale"] = true,\r\n', edit.data)
        self.assertIn(b'["autoRepair"] = 0.1,\r\n', edit.data)
        self.assertEqual(len(edit.changes), 4)

    def test_a_rename_writes_bracket_form(self):
        doc = self.doc(ace_lua("Db = {", "font = 'x',", "size = 3,", 'other = { a = 1 },', "}"))
        self.stage(doc, "rename", ("Db", "font"), "end")
        self.stage(doc, "rename", ("Db", "size"), 5)
        self.stage(doc, "rename", ("Db", "other"), 'a "quoted"\\key')
        _, edit = self.run_plan(doc)
        self.assertIn(b"[\"end\"] = 'x',\r\n", edit.data)
        self.assertIn(b"[5] = 3,\r\n", edit.data)
        self.assertIn(b'["a \\"quoted\\"\\\\key"] = { a = 1 },\r\n', edit.data)
        self.assertEqual(parse(edit.data).assignments[0].value.keys(), ["end", 5, 'a "quoted"\\key'])
        self.assertIn('Db › font: renamed to end', edit.changes)

    def test_rename_and_set_on_one_key(self):
        doc = self.doc(ace_lua("Db = {", "font = 'x',", "}"))
        self.stage(doc, "rename", ("Db", "font"), "Font")
        self.stage(doc, "set_value", ("Db", "font"), "y")
        _, edit = self.run_plan(doc)
        self.assertIn(b'["Font"] = "y",', edit.data)  # an edited single-quoted string becomes double-quoted
        self.assertEqual(edit.changes, ['Db › font: renamed to Font, "x" → "y"'])

    def test_deleting_an_array_entry_takes_its_line_and_comment(self):
        doc = self.doc(SVB_DETAILS)
        self.stage(doc, "delete", ("_detalhes_global", "bars", 2))
        old, edit = self.run_plan(doc)
        self.assertEqual(edit.data, old.replace(b"nil, -- [2]\r\n", b""))
        self.assertIn(b'"three", -- [3]\r\n', edit.data)  # the comment is stale now (D5 warning)
        bars = parse(edit.data).assignments[0].value.get("bars").value
        self.assertEqual([(f.key, f.value.value) for f in bars.fields], [(1, "one"), (2, "three")])
        self.assertEqual(edit.changes, ["_detalhes_global › bars › [2]: deleted (later entries move down)"])

    def test_deleting_a_whole_table(self):
        doc = self.doc(SVB_DETAILS)
        self.stage(doc, "delete", ("_detalhes_global", "tooltip"))
        _, edit = self.run_plan(doc)
        top = parse(edit.data).assignments[0].value
        self.assertEqual(top.keys(), ["font_face", "bars"])
        self.assertNotIn(b"tooltip", edit.data)
        self.assertNotIn(b"fontface", edit.data)

    def test_deleting_entries_written_on_one_line(self):
        doc = self.doc(ace_lua("Db = { a = 1, b = 2, c = 3 }"))
        self.stage(doc, "delete", ("Db", "b"))
        self.stage(doc, "delete", ("Db", "c"))
        _, edit = self.run_plan(doc)
        self.assertEqual(parse(edit.data).assignments[0].value.keys(), ["a"])

    def test_many_edits_in_one_file_including_under_a_renamed_table(self):
        doc = self.doc(SVB_ELVUI)
        base = ("ElvDB", "profiles", "Default")
        self.stage(doc, "rename", base + ("general",), "General")
        self.stage(doc, "set_value", base + ("general", "font"), "A")
        self.stage(doc, "delete", base + ("general", "fontSize"))
        self.stage(doc, "rename", base + ("unitframe", "barFont"), "bar")
        self.stage(doc, "delete", base + ("unitframe", 1))
        self.stage(doc, "set_value", base + ("unitframe", True), False)
        self.stage(doc, "set_value", ("ElvPrivateDB", "install_complete"), 14)
        self.stage(doc, "set_value", ("ElvVersion",), "13.0")
        _, edit = self.run_plan(doc)
        self.assertEqual(len(edit.changes), 8)
        chunk = parse(edit.data)
        self.assertEqual([a.name for a in chunk.assignments], ["ElvDB", "ElvPrivateDB", "ElvVersion"])
        self.assertEqual(chunk.assignments[2].value.value, "13.0")
        default = chunk.assignments[0].value.get("profiles").value.get("Default").value
        self.assertEqual(default.keys(), ["General", "unitframe"])
        general = default.get("General").value
        self.assertEqual([(f.key, f.value.value) for f in general.fields],
                         [("font", "A"), ("scale", 0.6000000000000001), ("autoRepair", True)])
        self.assertIn(b"0.6000000000000001", edit.data)  # untouched numbers keep their text
        unit = default.get("unitframe").value
        self.assertEqual(unit.keys(), ["Font", "bar", 2, True, False])
        self.assertIs(unit.get(True).value.value, False)

    def test_contains_replacement_inside_a_string_with_escapes(self):
        tree = build_sv_tree(self.tmp / "tree")
        files = scan_flavors([WowInstall(tree).flavor("_retail_")]).files()
        spec = SearchSpec(value='"b\\c', value_mode="contains")
        hits = [h for h in run_search(files, spec).hits if h.file.account == "ACCT1"]
        (hit,) = hits
        new = new_value(spec, MATCHED, "[X]", hit)
        self.assertEqual(new, 'a[X]\n—')
        stage_values(self.staging, hits, lambda h: new)
        plan = self.staging.plans()
        (file, file_plan), = plan.files.items()
        old = file.path.read_bytes()
        edit = compile_file(file, file_plan, old)
        self.assertEqual(verify_edit(edit, old), [])
        self.assertIn(b'["text"] = "a[X]\\n\xe2\x80\x94",\r\n', edit.data)
        self.assertEqual(decode_string(b'"a[X]\\n\xe2\x80\x94"'), new)

    def test_whole_value_hits_across_a_file(self):
        tree = build_sv_tree(self.tmp / "tree")
        files = scan_flavors([WowInstall(tree).flavor("_retail_")]).files()
        stage_values(self.staging, run_search(files, SearchSpec(value=SVB_FONT)).hits, lambda h: "Arial")
        plan = self.staging.plans()
        for file, file_plan in plan.files.items():
            old = file.path.read_bytes()
            edit = compile_file(file, file_plan, old)
            self.assertEqual(verify_edit(edit, old), [], file.rel)
            self.assertEqual(len(edit.changes), len(file_plan.edits))
            self.assertNotIn(SVB_FONT.casefold().encode(), edit.data.lower())

    def test_new_spans_line_up_with_the_old(self):
        doc = self.doc(ace_lua("Db = {", '["a"] = "short",', '["b"] = "a much longer value",', "}"))
        self.stage(doc, "set_value", ("Db", "a"), "a far longer replacement")
        self.stage(doc, "set_value", ("Db", "b"), 1)
        old, edit = self.run_plan(doc)
        for (old_start, old_end), (new_start, new_end) in edit.spans:
            self.assertEqual(old[:old_start][-6:], edit.data[:new_start][-6:])
            self.assertEqual(old[old_end:old_end + 3], edit.data[new_end:new_end + 3])


class CompileProblemTest(CompileTestBase):
    def plan(self, *edits):
        doc = self.doc(ace_lua("Db = {", '["a"] = 1,', '["a"] = 2,', '["t"] = {', "1,", "},", "}", "Top = 3"))
        doc.roots()
        file = replace(doc.file, sha256=doc.sha256)
        return file, FilePlan(file, list(edits)), doc.data

    def problems(self, *edits):
        file, plan, data = self.plan(*edits)
        edit = compile_file(file, plan, data)
        self.assertEqual(edit.data, data)
        self.assertEqual(verify_edit(edit, data), edit.problems)
        return edit.problems

    def test_targets_that_are_not_there_or_not_unique(self):
        self.assertIn("is not in the file", self.problems(FieldEdit(("Db", "zz"), set_value=True, value=1))[0])
        self.assertIn("is not in the file", self.problems(FieldEdit(("Nope", "a"), set_value=True, value=1))[0])
        self.assertIn("twice", self.problems(FieldEdit(("Db", "a"), set_value=True, value=3))[0])
        self.assertIn("not a table", self.problems(FieldEdit(("Top", "a"), set_value=True, value=3))[0])

    def test_what_a_target_does_not_allow(self):
        self.assertIn("is a table", self.problems(FieldEdit(("Db", "t"), set_value=True, value=3))[0])
        self.assertIn("top-level", self.problems(FieldEdit(("Top",), delete=True))[0])
        self.assertIn("top-level", self.problems(FieldEdit(("Top",), rename=True, new_key="x"))[0])
        self.assertIn("array", self.problems(FieldEdit(("Db", "t", 1), rename=True, new_key="x"))[0])
        self.assertIn("deleted", self.problems(FieldEdit(("Db", "t"), delete=True),
                                               FieldEdit(("Db", "t", 1), set_value=True, value=2))[0])

    def test_a_rename_onto_an_existing_key_is_caught(self):
        doc = self.doc(ace_lua("Db = {", '["a"] = 1,', '["b"] = 2,', "}"))
        doc.roots()
        file = replace(doc.file, sha256=doc.sha256)
        edit = compile_file(file, FilePlan(file, [FieldEdit(("Db", "a"), rename=True, new_key="b")]), doc.data)
        self.assertEqual(len(edit.problems), 1)
        self.assertIn("twice", edit.problems[0])

    def test_a_file_that_is_not_lua(self):
        doc = self.doc(ace_lua("Db = {"))
        file = replace(doc.file, sha256="x")
        edit = compile_file(file, FilePlan(file, [FieldEdit(("Db", "a"), set_value=True, value=1)]),
                            file.path.read_bytes())
        self.assertIn("not readable Lua", edit.problems[0])

    def test_a_parse_fault_deep_in_another_table_refuses_the_whole_file(self):
        """Spec D4: a file that isn't readable Lua is never changed, even when the fault is in a table no edit
        touches (the lazy tree and a parse limited to the edited tables never reach it)."""
        doc = self.doc(ace_lua("XDB = {", '["good"] = "a",', '["deep"] = {', '["inner"] = {', '["bad"] = @@@,',
                               "},", "},", "}"))
        self.stage(doc, "set_value", ("XDB", "good"), "b")
        plan = self.staging.plans()
        (file, file_plan), = plan.files.items()
        data = file.path.read_bytes()
        edit = compile_file(file, file_plan, data)
        self.assertEqual(edit.data, data)
        self.assertEqual(len(edit.problems), 1)
        self.assertIn("not readable Lua", edit.problems[0])
        self.assertEqual(verify_edit(edit, data), edit.problems)


class ManyEditsTest(CompileTestBase):
    def many_edits(self, count: int):
        """A WeakAuras file with `count` auras and one font edit per aura: (file, plan, data)."""
        lines = ["WeakAurasSaved = {", '["displays"] = {']
        for i in range(count):
            lines += [f'["aura{i}"] = {{', '["text"] = {', f'["font"] = "{SVB_FONT}",', "},", "},"]
        lines += ["},", "}"]
        doc = self.doc(ace_lua(*lines), f"WeakAuras{count}.lua")
        doc.roots()
        file = replace(doc.file, sha256=doc.sha256)
        edits = [FieldEdit(("WeakAurasSaved", "displays", f"aura{i}", "text", "font"), set_value=True,
                           value="Expressway") for i in range(count)]
        return file, FilePlan(file, edits), doc.data

    def compile_and_verify(self, count: int, file, plan, data) -> float:
        """Compile and verify the edits; the CPU seconds that took."""
        with cpu_seconds() as cpu:
            edit = compile_file(file, plan, data)
            problems = verify_edit(edit, data)
        self.assertEqual(edit.problems, [])
        self.assertEqual(problems, [])
        self.assertEqual(edit.data.count(b'"Expressway"'), count)
        return cpu.seconds

    def test_thousands_of_edits_in_one_file_compile_and_verify_quickly(self):
        # M2 review: locate and the expected rows were linear per edit (quadratic per file). Asserted on how the CPU
        # cost grows from 1000 to 4000 edits, not on a time: 4x is linear (0.15 s and 0.6 s here), the quadratic
        # code took 15x (0.95 s and 14 s). An absolute 4 s budget broke under the --all gate even on CPU time:
        # under WSL a vCPU the Windows side holds back still counts as CPU time (11.5 s once). The runs alternate
        # sizes so sustained load hits both, and each size keeps its fastest of three: one burst can neither fail
        # the test (it needs all three large runs) nor pass a regression (it needs all three small runs).
        # Trade-off: a ratio catches quadratic growth (it passes only while the quadratic cost at 1000 edits stays
        # under about half the linear cost, where the old 4 s budget allowed about 1.4x), not a constant-factor
        # slowdown that stays linear.
        small, large = self.many_edits(1000), self.many_edits(4000)
        small_runs, large_runs = [], []
        for _ in range(3):
            small_runs.append(self.compile_and_verify(1000, *small))
            large_runs.append(self.compile_and_verify(4000, *large))
        ratio = min(large_runs) / max(min(small_runs), 0.001)
        # 10: linear is 4, the old quadratic code was 15; a loaded Windows CI runner once read 9.0 for linear code.
        self.assertLess(ratio, 10.0, f"CPU cost of 4000 edits over 1000: {ratio:.1f} ({small_runs}, {large_runs})")


class VerifyTest(CompileTestBase):
    def compiled(self):
        doc = self.doc(SVB_ELVUI)
        self.stage(doc, "set_value", ("ElvDB", "profiles", "Default", "general", "font"), "Arial")
        self.stage(doc, "delete", ("ElvDB", "profiles", "Default", "unitframe", 2))
        return self.run_plan(doc)

    def test_a_changed_byte_outside_the_edits_is_caught(self):
        old, edit = self.compiled()
        edit.data = edit.data.replace(b"Expressway", b"Expresswax")
        problems = verify_edit(edit, old)
        self.assertTrue(any("unitframe" in p for p in problems), problems)
        self.assertIn("bytes outside the edits changed", problems)
        edit2 = replace(edit, data=edit.data.replace(b"13.52", b"13.53"))
        problems = verify_edit(edit2, old)
        self.assertIn("ElvPrivateDB changed but nothing was planned for it", problems)

    def test_a_value_that_is_not_the_planned_one_is_caught(self):
        old, edit = self.compiled()
        edit.data = edit.data.replace(b'"Arial"', b'"Arian"')
        problems = verify_edit(edit, old)
        self.assertTrue(any("general" in p and "planned" in p for p in problems), problems)

    def test_an_entry_that_should_be_gone_is_caught(self):
        old, edit = self.compiled()
        bad = replace(edit, data=old.replace(f'["font"] = "{SVB_FONT}"'.encode(), b'["font"] = "Arial"'),
                      spans=edit.spans[:1])
        problems = verify_edit(bad, old)
        self.assertTrue(any("unitframe" in p for p in problems), problems)

    def test_other_assignments_or_broken_lua_are_caught(self):
        old, edit = self.compiled()
        self.assertIn("does not hold the same", verify_edit(replace(edit, data=edit.data.replace(
            b"ElvPrivateDB", b"ElvPrivateDX")), old)[0])
        self.assertIn("does not read back", verify_edit(replace(edit, data=edit.data[:-10]), old)[0])

    def test_a_top_level_value_is_checked(self):
        doc = self.doc(SVB_DETAILS)
        self.stage(doc, "set_value", ("DetailsVersion",), 5)
        old, edit = self.run_plan(doc)
        self.assertTrue(edit.data.endswith(b"DetailsVersion = 5\r\n"))
        bad = replace(edit, data=edit.data.replace(b"= 5\r\n", b"= 6\r\n"))
        problems = verify_edit(bad, old)
        self.assertTrue(any("DetailsVersion" in p for p in problems), problems)


class PipelineTest(CompileTestBase):
    def test_a_plan_goes_through_the_shared_dry_run(self):
        tree = build_sv_tree(self.tmp / "tree")
        flavor = WowInstall(tree).flavor("_retail_")
        files = scan_flavors([flavor]).files()
        staging = Staging()
        details = next(f for f in files if f.path.name == "Details.lua" and f.account == "ACCT1")
        doc = SvDocument(details)
        staging.delete(doc, self.node(doc, "_detalhes_global", "bars", 1))
        stage_values(staging, run_search(files, SearchSpec(value=SVB_FONT)).hits, lambda h: "Arial")
        plan = staging.plans()
        units = [(f, p) for f, p in plan.files.items() if f.flavor == flavor]
        result = sv_apply.apply_flavor(SV_TOOL, flavor, units, compile_file, verify_edit, root=self.tmp / "root",
                                       journal=None, dry_run=True, keep_snapshots=1)
        self.assertEqual(len(result.would_edit), len(units))
        self.assertEqual(sum(len(o.changes) for o in result.would_edit),
                         sum(len(p.edits) for _, p in units))
        self.assertEqual(sha256_of(details.path.read_bytes()), doc.sha256)  # nothing written


if __name__ == "__main__":
    unittest.main()
