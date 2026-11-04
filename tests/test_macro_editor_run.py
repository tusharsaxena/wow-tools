"""Macro Editor runs (config tools spec ME3-ME7, ME13, X5; Review Focus 1 and 2): staged changes written through the
shared client-file pipeline across files and flavors as one run and one Undo, the dry run, the WoW check, a file
changed since the scan, the paste review (clashes, slots, cross-flavor warnings) and the text of the confirm and
the result. Every client file is synthesized in a tests/fixtures.py temp tree (build_macro_tree)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.fixtures import MACRO_ACCOUNT, MACRO_AELLA, MACRO_BOB, MACRO_ERA, MACRO_UNKNOWN, build_macro_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.macrofile import parse_macros
from wowtools.tools.macro_editor import journal, report, undo
from wowtools.tools.macro_editor.model import MACRO_FILE, MacroSet
from wowtools.tools.macro_editor.ops import (Staged, effective_macros, preview_paste, stage_delete, stage_edit,
                                             stage_new)
from wowtools.tools.macro_editor.runner import NAMES, WowRunning, changes_by_flavor, run_apply
from wowtools.tools.macro_editor.scanner import scan_sets

WHEN = datetime(2026, 11, 4, 12, 0, 0)


class MacroRunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_macro_tree(self.tmp / "wow")
        install = WowInstall(self.wow)
        self.retail, self.era = install.flavor("_retail_"), install.flavor("_classic_era_")
        self.sets = scan_sets(self.retail) + scan_sets(self.era)
        self.root = self.tmp / "out" / "macro-editor"
        self.journals = self.tmp / "journal"
        self.staged = Staged()

    def set_of(self, label: str, flavor: str = "_retail_") -> MacroSet:
        return next(s for s in self.sets if s.label == label and s.flavor.folder == flavor)

    def macro(self, mset: MacroSet, name: str):
        return next(m for m in mset.parsed.macros if m.name == name)

    def run_it(self, **kwargs):
        options = {"root": self.root, "journal_dir": self.journals, "keep_journals": 5, "keep_snapshots": 2,
                   "dry_run": False, "wow_check": None, "now": WHEN}
        options.update(kwargs)
        return run_apply(self.staged, self.sets, **options)

    def tree_bytes(self) -> dict[str, bytes]:
        return {p.relative_to(self.wow).as_posix(): p.read_bytes() for p in sorted(self.wow.rglob("*"))
                if p.is_file()}

    def stage_three_files(self) -> None:
        aella, bob, traxex = (self.set_of(n) for n in ("MAIN/Realm1/Aellâ", "MAIN/Realm1/Bob", "MAIN/Realm2/Trâxex"))
        stage_edit(self.staged, aella, "0100000000000002", name="D Up", icon="132360", body="/cast Divine Shield")
        stage_delete(self.staged, bob, "0100000000000001")
        stage_new(self.staged, traxex, name="Hi", body="/wave")

    def test_names_is_the_macro_file(self):
        self.assertEqual(NAMES, frozenset({MACRO_FILE}))

    def test_one_run_across_files_then_undo(self):
        before = self.tree_bytes()
        self.stage_three_files()
        with capture_events() as events:
            result = self.run_it()
        self.assertIsNone(result.stopped)
        self.assertEqual(len(result.edited), 3)
        self.assertIn("macro.apply_completed", [e["event"] for e in events])
        accounts = self.retail.account_dir
        aella = (accounts / "MAIN/Realm1/Aellâ" / MACRO_FILE).read_bytes()
        self.assertEqual(aella, MACRO_AELLA.replace(b"/cast Divine Protection", b"/cast Divine Shield"))
        bob = parse_macros((accounts / "MAIN/Realm1/Bob" / MACRO_FILE).read_bytes())
        self.assertEqual([m.name for m in bob.macros], ["D Up"])
        traxex = parse_macros((accounts / "MAIN/Realm2/Trâxex" / MACRO_FILE).read_bytes())
        self.assertEqual([(m.id, m.name, m.body) for m in traxex.macros], [("0100000000000001", "Hi", "/wave")])
        # untouched: the account macros, the copy folder, the read-only file, the other flavor
        self.assertEqual((accounts / "MAIN" / MACRO_FILE).read_bytes(), MACRO_ACCOUNT)
        self.assertEqual((accounts / "MAIN/Realm1/Bob - Copy" / MACRO_FILE).read_bytes(), MACRO_AELLA)
        self.assertEqual((accounts / "ALT/Realm1/Dænerys" / MACRO_FILE).read_bytes(), MACRO_UNKNOWN)
        self.assertFalse(list(self.wow.rglob("cache.md5")))
        self.assertTrue(undo.undo_flavors(self.wow, journal.read_journal(result.journal_path).entries))
        undone = undo.undo_run(result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2, now=WHEN)
        self.assertEqual(len(undone.restored), 3)
        self.assertEqual(self.tree_bytes(), before)  # the created file is gone again

    def test_one_run_across_flavors(self):
        stage_new(self.staged, self.set_of("MAIN/Realm1/Bob"), name="Hi", body="/wave")
        stage_edit(self.staged, self.set_of("ACCT/Realm1/Other", "_classic_era_"), "0100000000000001", name="Era",
                   icon="134400", body="/say hello")
        plan = changes_by_flavor(self.staged, self.sets)
        self.assertEqual([(f.folder, len(c)) for f, c in plan], [("_retail_", 1), ("_classic_era_", 1)])
        checked = []
        result = self.run_it(wow_check=lambda: checked.append(1) or [])
        self.assertEqual(checked, [1])
        self.assertEqual(len(result.edited), 2)
        self.assertEqual(len({o.file.flavor.folder for o in result.edited}), 2)
        era = self.era.account_dir / "ACCT/Realm1/Other" / MACRO_FILE
        self.assertEqual(era.read_bytes(), MACRO_ERA.replace(b"/say hi", b"/say hello"))
        undo.undo_run(result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2, now=WHEN)
        self.assertEqual(era.read_bytes(), MACRO_ERA)

    def test_dry_run_writes_nothing(self):
        before = self.tree_bytes()
        self.stage_three_files()
        result = self.run_it(dry_run=True)
        self.assertEqual(len(result.would_edit), 3)
        self.assertEqual(self.tree_bytes(), before)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.journals.exists())

    def test_refused_while_wow_runs(self):
        before = self.tree_bytes()
        self.stage_three_files()
        with self.assertRaises(WowRunning):
            self.run_it(wow_check=lambda: ["Wow.exe"])
        self.assertEqual(self.tree_bytes(), before)

    def test_a_file_changed_since_the_scan_is_skipped(self):
        self.stage_three_files()
        bob = self.retail.account_dir / "MAIN/Realm1/Bob" / MACRO_FILE
        bob.write_bytes(MACRO_BOB + b'VER 3 0100000000000009 "New" "134400"\r\nEND\r\n')
        result = self.run_it()
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(len(result.edited), 2)
        self.assertIn(b'"New"', bob.read_bytes())

    def test_unknown_layout_is_never_written(self):
        daenerys = self.set_of("ALT/Realm1/Dænerys")
        self.assertTrue(daenerys.read_only)
        with self.assertRaises(ValueError):
            stage_new(self.staged, daenerys, name="X", body="/sit")
        preview = preview_paste(self.staged, [self.macro(self.set_of("MAIN/Realm1/Bob"), "Bob")], [daenerys], {})
        self.assertEqual(len(preview.refusals), 1)
        self.assertIn("read-only", preview.refusals[0])
        self.assertEqual(preview.staged.count(), 0)

    # --- the paste review ----------------------------------------------------------------------------------------

    def test_paste_preview_clashes_choices_and_refusals(self):
        aella, bob = self.set_of("MAIN/Realm1/Aellâ"), self.set_of("MAIN/Realm1/Bob")
        picked = [self.macro(aella, "D Up"), self.macro(aella, "Fly")]
        preview = preview_paste(self.staged, picked, [bob], {})
        self.assertEqual([(c.target.label, c.pasted.name, c.existing.name, c.choice) for c in preview.clashes],
                         [("MAIN/Realm1/Bob", "D Up", "D Up", "skip")])
        self.assertEqual([m.name for m in effective_macros(preview.staged, bob)], ["Bob", "D Up", "Fly"])
        self.assertEqual(self.staged.count(), 0)  # a preview stages nothing on the review's own staging
        overwrite = preview_paste(self.staged, picked, [bob], {(bob.path, "D Up"): "overwrite"})
        after = {m.name: m for m in effective_macros(overwrite.staged, bob)}
        self.assertEqual(after["D Up"].id, "0100000000000007")  # ME6: the target's id is kept
        self.assertEqual(after["D Up"].body, "/cast Divine Protection")
        renamed = preview_paste(self.staged, picked, [bob], {(bob.path, "D Up"): "rename"})
        self.assertIn("D Up 2", [m.name for m in effective_macros(renamed.staged, bob)])
        full = MacroSet(bob.flavor, bob.account, bob.character, bob.path, bob.parsed, bob.data, bob.sha256)
        staged = Staged()
        for number in range(full.limit - 2):
            stage_new(staged, full, name=f"M{number}", body="/sit")
        refused = preview_paste(staged, picked, [full], {})
        self.assertEqual(len(refused.refusals), 1)
        self.assertIn("no free macro slot", refused.refusals[0])

    def test_cross_flavor_warnings_name_unknown_terms(self):
        aella = self.set_of("MAIN/Realm1/Aellâ")
        other = self.set_of("ACCT/Realm1/Other", "_classic_era_")
        picked = [(aella, self.macro(aella, "Fly")), (aella, self.macro(aella, "D Up"))]
        lines = report.paste_warnings(picked, [other])
        self.assertTrue(lines[0].startswith("From Retail into Classic Era: "), lines)
        self.assertTrue(any("Fly" in line and "advflyable" in line for line in lines), lines)
        self.assertFalse(any("D Up" in line for line in lines[1:]), lines)
        self.assertEqual(report.paste_warnings(picked, [self.set_of("MAIN/Realm1/Bob")]), [])

    # --- texts -----------------------------------------------------------------------------------------------------

    def test_set_and_macro_texts(self):
        aella = self.set_of("MAIN/Realm1/Aellâ")
        self.assertEqual(report.slots_text(3, 30), "3/30")
        self.assertEqual(report.slots_text(30, 30), "30/30 FULL")
        heal = self.macro(aella, "Heal Dænerys")
        self.assertEqual(report.macro_text(heal),
                         "Heal Dænerys · /cast [@mouseover,help,nodead] Flash Heal · 41/255")

    def test_confirm_and_result_rows(self):
        self.stage_three_files()
        title, body, alerts = report.apply_confirm(self.staged, self.sets, dry_run=False)
        self.assertEqual(title, "Apply the staged changes?")
        self.assertIn("3 changes in 3 files", body)
        self.assertIn(report.DELETE_WARNING, alerts)  # Bob's macro is deleted (ME6)
        groups = report.apply_groups(self.staged, self.sets)
        self.assertEqual(groups["Retail › MAIN/Realm1/Bob"], ['macros-cache.txt: deleted "Bob"'])
        title, body, alerts = report.apply_confirm(self.staged, self.sets, dry_run=True)
        self.assertEqual(title, "Dry run")
        result = self.run_it()
        rows = report.file_rows(result)
        self.assertIn(("Retail", "MAIN", "Realm2/Trâxex", "changed: created"), rows)
        self.assertEqual(report.summary_rows(result)[0], ("Changed", "3 files"))


if __name__ == "__main__":
    unittest.main()
