"""Saved Variables Browser Apply, Undo and recovery end to end on build_sv_tree temp trees (spec D13-D17): the
staged edits and ticked hits go through the shared pipeline per flavor under one journal; the bytes written are
exactly the splices, the WTF snapshot and the originals zip hold the right members, Undo puts the files back
byte-for-byte (a file saved since is left alone), a dry run writes nothing, WoW running refuses, a file changed
since it was read is skipped, and a run that died while writing is put back (or left) from its marker. Plus the
journal / undo wrappers and the result screen's rows."""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import SVB_FONT, build_sv_tree
from wowtools.core import sv_apply, sv_journal, sv_undo
from wowtools.core.events import capture_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.core.luasv import key_id
from wowtools.core.svfiles import sha256_of
from wowtools.core.undo import UndoResultBase
from wowtools.tools.sv_browser import editor, journal, report, undo
from wowtools.tools.sv_browser.events import SV_TOOL
from wowtools.tools.sv_browser.model import SvDocument
from wowtools.tools.sv_browser.ops import Staging
from wowtools.tools.sv_browser.scanner import scan_flavors
from wowtools.tools.sv_browser.search import SearchSpec, run_search
from wowtools.tools.sv_browser.settings import SvBrowserSettings, resolve_root

WHEN = datetime(2026, 10, 7, 12, 0, 0)
ELVUI_FONT = ("ElvDB", "profiles", "Default", "general", "font")
QUESTIE_FONT = ("QuestieConfig", "global", "font")
OLD_FONT = f'["font"] = "{SVB_FONT}",'.encode()


def by_key(nodes, key):
    return next(n for n in nodes if key_id(n.key) == key_id(key))


class ApplyTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_sv_tree(self.tmp / "wow")
        install = WowInstall(self.wow)
        self.retail, self.era = install.flavor("_retail_"), install.flavor("_classic_era_")
        self.files = scan_flavors([self.retail, self.era]).files()
        self.root = resolve_root(SvBrowserSettings(), self.wow)
        self.journal_dir = journal.resolve_journal_dir(self.wow)
        self.staging = Staging()
        self.before = self.snapshot_tree()

    def snapshot_tree(self) -> dict[Path, bytes]:
        """Every file of the install outside the tool's own folder."""
        return {p: p.read_bytes() for p in self.wow.rglob("*") if p.is_file() and "wow-tools" not in p.parts}

    def file(self, flavor, name, account="ACCT1", character=False):
        return next(f for f in self.files if f.flavor == flavor and f.path.name == name and f.account == account
                    and (f.character is not None) == character)

    def stage(self, file, op, keys, *args) -> SvDocument:
        doc = SvDocument(file)
        nodes, node = doc.roots(), None
        for key in keys:
            node = by_key(nodes, key)
            nodes = doc.children(node) if node.is_table else []
        result = getattr(self.staging, op)(doc, node, *args)
        self.assertTrue(result.ok, result.message)
        return doc

    def stage_two_flavors(self):
        """A font set in retail ElvUI.lua and in era Questie.lua: (elvui, questie) paths."""
        elvui, questie = self.file(self.retail, "ElvUI.lua"), self.file(self.era, "Questie.lua")
        self.stage(elvui, "set_value", ELVUI_FONT, "Arial Narrow")
        self.stage(questie, "set_value", QUESTIE_FONT, "Morpheus")
        return elvui.path, questie.path

    def apply(self, plan=None, **options):
        settings = {"root": self.root, "journal_dir": self.journal_dir, "keep_journals": 5, "keep_snapshots": 2,
                    "dry_run": False, "now": WHEN}
        settings.update(options)
        return editor.apply_plan(self.staging.plans() if plan is None else plan, **settings)


class ApplyTest(ApplyTestBase):
    def test_apply_writes_exactly_the_planned_bytes_in_each_flavor(self):
        elvui, questie = self.stage_two_flavors()
        with capture_events() as events:
            result = self.apply()
        self.assertEqual([run.status for run in result.runs], ["done", "done"])
        self.assertEqual([run.flavor.folder for run in result.runs], ["_retail_", "_classic_era_"])
        self.assertEqual(len(result.edited), 2)
        expected = dict(self.before)
        expected[elvui] = self.before[elvui].replace(OLD_FONT, b'["font"] = "Arial Narrow",')
        expected[questie] = self.before[questie].replace(OLD_FONT, b'["font"] = "Morpheus",')
        self.assertEqual(self.snapshot_tree(), expected)
        self.assertIsNone(editor.read_marker(self.root))
        names = [e["event"] for e in events]
        for name in ("svb.apply_started", "svb.snapshot_taken", "svb.files_backed_up", "svb.file_edited",
                     "svb.apply_completed"):
            self.assertIn(name, names)
        self.assertFalse([n for n in names if n.startswith("ace.")])
        started = [e for e in events if e["event"] == "svb.apply_started"]
        self.assertEqual([(e["data"]["files"], e["data"]["edits"]) for e in started], [(1, 1), (1, 1)])

    def test_staged_edits_and_ticked_hits_go_in_one_run(self):
        hits = run_search(self.files, SearchSpec(value=SVB_FONT, replacement="Arial")).hits
        elvui = self.file(self.retail, "ElvUI.lua")
        self.stage(elvui, "set_value", ELVUI_FONT, "Arial Narrow")
        plan = self.staging.plans(hits)
        self.assertEqual(len(plan.dropped), 1)  # the staged edit wins over the hit on the same value
        result = self.apply(plan)
        self.assertEqual(len(result.edited), len(plan.files))
        self.assertEqual(sum(len(o.changes) for o in result.edited), plan.staged + plan.hits)
        written = elvui.path.read_bytes()
        self.assertIn(b'["font"] = "Arial Narrow",', written)
        self.assertIn(b'["Font"] = "Arial",', written)
        for path, data in self.snapshot_tree().items():
            if path.suffix == ".lua":  # the .bak is never listed, so never searched
                self.assertNotIn(SVB_FONT.encode(), data, path)

    def test_the_snapshot_and_the_originals_zip_hold_the_right_members(self):
        elvui, questie = self.stage_two_flavors()
        result = self.apply()
        for run, path in zip(result.runs, (elvui, questie)):
            flavor, rel = run.flavor, path.relative_to(run.flavor.path).as_posix()
            self.assertEqual(run.result.snapshot.parent, self.root / "snapshots")
            with zipfile.ZipFile(run.result.snapshot) as zf:
                members = set(zf.namelist())
                self.assertIn(rel, members)
                self.assertEqual(zf.read(rel), self.before[path])  # taken before the write
                wtf = {p.relative_to(flavor.path).as_posix() for p in flavor.wtf_dir.rglob("*") if p.is_file()}
                self.assertEqual(members, wtf)
            self.assertEqual(run.result.backup_zip.parent, self.root / "edited")
            with zipfile.ZipFile(run.result.backup_zip) as zf:
                self.assertEqual(sorted(zf.namelist()), sorted([rel, "manifest.json"]))
                self.assertEqual(zf.read(rel), self.before[path])
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["tool"], "sv-browser")
                self.assertEqual(manifest["sha256"], {rel: sha256_of(self.before[path])})

    def test_the_run_journal_records_every_file(self):
        elvui, questie = self.stage_two_flavors()
        result = self.apply()
        self.assertEqual(result.journal_path.parent, self.wow / "wow-tools" / "sv-browser" / "journal")
        record = journal.read_journal(result.journal_path)
        self.assertEqual(record.header["tool"], "sv-browser")
        self.assertEqual(record.header["flavors"], ["_retail_", "_classic_era_"])
        entries = {e["rel"]: e for e in record.entries}
        for path in (elvui, questie):
            flavor = self.retail if path == elvui else self.era
            entry = entries[path.relative_to(flavor.path).as_posix()]
            self.assertEqual(entry["flavor"], flavor.folder)
            self.assertEqual(entry["sha_before"], sha256_of(self.before[path]))
            self.assertEqual(entry["sha_after"], sha256_of(path.read_bytes()))
            self.assertEqual(len(entry["changes"]), 1)
        self.assertEqual(journal.latest_undoable(self.journal_dir), result.journal_path)

    def test_journals_are_kept_to_keep_journals(self):
        for minute in range(3):
            self.staging = Staging()
            self.files = scan_flavors([self.retail]).files()
            self.stage(self.file(self.retail, "ElvUI.lua"), "set_value", ELVUI_FONT, f"Font {minute}")
            self.apply(keep_journals=2, now=WHEN.replace(minute=minute))
        self.assertEqual(len(list(self.journal_dir.glob("journal-*.jsonl"))), 2)
        self.assertEqual(len(list((self.root / "snapshots").glob("*.zip"))), 2)  # keep_snapshots
        self.assertEqual(len(list((self.root / "edited").glob("*.zip"))), 2)  # pruned with the journals

    def test_a_backup_folder_puts_the_zips_there_and_the_journal_under_wow(self):
        root = resolve_root(SvBrowserSettings(backup_dir=self.tmp / "backups"), self.wow)
        self.assertEqual(root, self.tmp / "backups" / "sv-browser")
        self.stage_two_flavors()
        result = self.apply(root=root)
        self.assertTrue(all(run.result.snapshot.is_relative_to(root) for run in result.runs))
        self.assertTrue(result.journal_path.is_relative_to(self.wow / "wow-tools" / "sv-browser"))

    def test_dry_run_writes_nothing(self):
        self.stage_two_flavors()
        result = self.apply(dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual(len(result.would_edit), 2)
        self.assertTrue(all(o.changes for o in result.would_edit))
        self.assertEqual(self.snapshot_tree(), self.before)
        self.assertFalse((self.wow / "wow-tools").exists())
        self.assertIsNone(result.journal_path)

    def test_dry_run_is_allowed_while_wow_runs(self):
        self.stage_two_flavors()
        result = self.apply(dry_run=True, wow_check=lambda: ["Wow.exe"])
        self.assertEqual(len(result.would_edit), 2)

    def test_refused_while_wow_runs(self):
        self.stage_two_flavors()
        with capture_events() as events, self.assertRaises(editor.WowRunning) as caught:
            self.apply(wow_check=lambda: ["Wow.exe"])
        self.assertIn("overwrite the changes", str(caught.exception))
        self.assertIn("svb.wow_running", [e["event"] for e in events])
        self.assertEqual(self.snapshot_tree(), self.before)
        self.assertFalse((self.wow / "wow-tools").exists())

    def test_a_file_changed_since_it_was_read_is_skipped(self):
        elvui, questie = self.stage_two_flavors()
        changed = self.before[elvui] + b"-- saved by WoW\r\n"
        elvui.write_bytes(changed)
        with capture_events() as events:
            result = self.apply()
        self.assertEqual([o.file.path for o in result.skipped], [elvui])
        self.assertEqual(result.skipped[0].detail, sv_apply.CHANGED)
        self.assertEqual([o.file.path for o in result.edited], [questie])
        self.assertEqual(elvui.read_bytes(), changed)
        self.assertIn("svb.file_changed", [e["event"] for e in events])

    def test_a_verify_problem_stops_the_flavor_before_writing(self):
        self.stage_two_flavors()
        with patch("wowtools.tools.sv_browser.editor.verify_edit", return_value=["broken"]):
            result = self.apply()
        self.assertEqual([run.status for run in result.runs], ["stopped", "not_started"])
        self.assertIn("broken", result.stopped.error)
        self.assertEqual(self.snapshot_tree(), self.before)

    def test_a_file_with_a_parse_fault_deep_inside_is_never_written(self):
        """Spec D4: browsable around the fault (D27) but never changed, like search, which calls it unreadable."""
        bad = self.retail.account_dir / "ACCT1" / "SavedVariables" / "X.lua"
        bad.write_bytes(b'XDB = {\n["good"] = "a",\n["deep"] = {\n["inner"] = {\n["bad"] = @@@,\n},\n},\n}\n')
        self.files = scan_flavors([self.retail, self.era]).files()
        before = self.snapshot_tree()
        self.stage(self.file(self.retail, "X.lua"), "set_value", ("XDB", "good"), "b")
        result = self.apply()
        self.assertEqual(result.runs[0].status, "stopped")
        self.assertIn("not readable Lua", result.stopped.error)
        self.assertEqual(result.edited, [])
        self.assertEqual(self.snapshot_tree(), before)

    def test_a_write_failure_rolls_back_the_files_already_written(self):
        sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        elvui, details = self.file(self.retail, "ElvUI.lua"), self.file(self.retail, "Details.lua")
        self.stage(elvui, "set_value", ELVUI_FONT, "Arial Narrow")
        self.stage(details, "set_value", ("_detalhes_global", "font_face"), "Morpheus")
        with self.assertRaises(editor.ApplyError) as caught:
            self.apply_one_flavor(fail=sv / "Details.lua")
        self.assertEqual(caught.exception.files_left, [])
        self.assertEqual(len(caught.exception.rolled_back), 1)
        self.assertEqual(self.snapshot_tree(), self.before)
        self.assertIsNone(editor.read_marker(self.root))

    def apply_one_flavor(self, *, fail: Path):
        """apply_flavor for retail with a write that fails on `fail` (the files are written in plan order)."""
        def write(path, data):
            if path == fail:
                raise OSError("killed")
            atomic_write_bytes(path, data)
        record = sv_journal.EditJournal(self.journal_dir / "journal-20261007-120000.jsonl",
                                        {"tool": SV_TOOL.name, "kind": "apply"})
        self.addCleanup(record.close)
        flavor, units = editor.flavor_plan(self.staging.plans())[0]
        try:
            return editor.apply_flavor(flavor, units, root=self.root, journal=record, dry_run=False,
                                       keep_snapshots=2, now=WHEN, write=write)
        finally:
            record.close()

    def test_flavor_plan_groups_the_files_by_flavor_in_plan_order(self):
        self.stage(self.file(self.era, "Questie.lua"), "set_value", QUESTIE_FONT, "Morpheus")
        self.stage(self.file(self.retail, "ElvUI.lua"), "set_value", ELVUI_FONT, "Arial Narrow")
        self.stage(self.file(self.retail, "Details.lua"), "set_value", ("_detalhes_global", "font_face"), "Morpheus")
        grouped = editor.flavor_plan(self.staging.plans())
        self.assertEqual([(f.folder, [u.path.name for u, _ in units]) for f, units in grouped],
                         [("_classic_era_", ["Questie.lua"]), ("_retail_", ["ElvUI.lua", "Details.lua"])])
        self.assertTrue(all(file is plan.file for _, units in grouped for file, plan in units))


class UndoTest(ApplyTestBase):
    def test_undo_puts_every_file_back_byte_for_byte(self):
        self.stage_two_flavors()
        result = self.apply()
        with capture_events() as events:
            undone = undo.undo_run(result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2,
                                   now=WHEN.replace(minute=5))
        self.assertIsInstance(undone, UndoResultBase)
        self.assertEqual(len(undone.restored), 2)
        self.assertEqual(self.snapshot_tree(), self.before)
        self.assertEqual(len(undone.snapshots), 2)  # one WTF snapshot per flavor before putting back
        self.assertIn("svb.undo_completed", [e["event"] for e in events])
        self.assertIsNone(journal.latest_undoable(self.journal_dir))

    def test_undo_leaves_a_file_saved_since(self):
        elvui, questie = self.stage_two_flavors()
        result = self.apply()
        saved = elvui.read_bytes() + b"-- saved by WoW\r\n"
        elvui.write_bytes(saved)
        undone = undo.undo_run(result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2,
                               now=WHEN.replace(minute=5))
        self.assertEqual([o.path for o in undone.skipped], [elvui])
        self.assertEqual(undone.skipped[0].detail, undo.CHANGED_SINCE)
        self.assertEqual([o.path for o in undone.restored], [questie])
        self.assertEqual(elvui.read_bytes(), saved)
        self.assertEqual(questie.read_bytes(), self.before[questie])

    def test_undo_is_refused_while_wow_runs(self):
        self.stage_two_flavors()
        result = self.apply()
        after = self.snapshot_tree()
        with self.assertRaises(undo.WowRunning) as caught:
            undo.undo_run(result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2,
                          wow_check=lambda: ["Wow.exe"])
        self.assertIsInstance(caught.exception, undo.UndoError)
        self.assertIn("overwrite the files", str(caught.exception))
        self.assertEqual(self.snapshot_tree(), after)

    def crash(self):
        """An Apply of two retail files killed while writing the second, with the first not put back: the marker
        stays (the state after a power cut). Returns (elvui path, details path)."""
        elvui, details = self.file(self.retail, "ElvUI.lua"), self.file(self.retail, "Details.lua")
        self.stage(elvui, "set_value", ELVUI_FONT, "Arial Narrow")
        self.stage(details, "set_value", ("_detalhes_global", "font_face"), "Morpheus")
        with patch("wowtools.core.sv_apply.restore_original", side_effect=OSError("no")), \
                self.assertRaises(editor.ApplyError) as caught:
            ApplyTest.apply_one_flavor(self, fail=details.path)
        self.assertEqual(caught.exception.files_left, [elvui.rel])
        self.assertNotEqual(elvui.path.read_bytes(), self.before[elvui.path])
        return elvui.path, details.path

    def test_a_crash_while_writing_leaves_a_marker_and_recover_puts_back(self):
        elvui, details = self.crash()
        marker = undo.pending_recovery(self.root)
        self.assertIsNotNone(marker)
        self.assertEqual(marker.flavor, "_retail_")
        self.assertEqual(sorted(marker.files), sorted(p.relative_to(self.retail.path).as_posix()
                                                      for p in (elvui, details)))
        with capture_events() as events:
            result = undo.recover(marker, root=self.root, journal_dir=self.journal_dir, keep_snapshots=2,
                                  now=WHEN.replace(minute=5))
        self.assertEqual([o.path for o in result.restored], [elvui])
        self.assertEqual(self.snapshot_tree(), self.before)
        self.assertIsNone(undo.pending_recovery(self.root))
        self.assertIn(("svb.recovery_done", "put_back"),
                      [(e["event"], e["data"].get("choice")) for e in events])
        self.assertIsNone(journal.latest_undoable(self.journal_dir))

    def test_a_new_apply_is_refused_while_a_marker_waits(self):
        self.crash()
        self.staging = Staging()
        self.files = scan_flavors([self.retail]).files()
        self.stage(self.file(self.retail, "Blizzard_Console.lua"), "set_value",
                   ("Blizzard_Console_SavedVars", "fontHeight"), 16)
        result = self.apply()
        self.assertIn("did not finish", result.stopped.error)

    def test_leave_keeps_the_files_and_drops_the_marker(self):
        self.crash()
        written = self.snapshot_tree()
        marker = undo.pending_recovery(self.root)
        with capture_events() as events:
            undo.leave(marker, root=self.root)
        self.assertEqual(self.snapshot_tree(), written)
        self.assertIsNone(undo.pending_recovery(self.root))
        self.assertTrue(marker.zip.exists())  # the originals stay
        self.assertIn(("svb.recovery_done", "leave"), [(e["event"], e["data"].get("choice")) for e in events])

    def test_the_wrappers_are_the_shared_pipeline(self):
        self.assertIs(undo.UndoResult, sv_undo.UndoResult)
        self.assertTrue(issubclass(undo.UndoResult, UndoResultBase))
        self.assertIs(editor.WowRunning, undo.WowRunning)
        self.assertIs(journal.JOURNALS, SV_TOOL.journals)
        self.assertIs(journal.read_journal, sv_journal.read_edit_journal)
        self.assertEqual(journal.resolve_journal_dir(self.wow), self.wow / "wow-tools" / "sv-browser" / "journal")


class ReportTest(ApplyTestBase):
    def test_apply_confirm_counts_per_flavor_and_carries_the_disclaimer(self):
        self.stage_two_flavors()
        self.stage(self.file(self.retail, "Details.lua"), "delete", ("_detalhes_global", "bars", 1))
        title, body, alerts = report.apply_confirm(self.staging.plans(), dry_run=False)
        self.assertEqual(title, "Apply the pending changes?")
        self.assertIn("3 edits in 3 files", body)
        self.assertIn("Retail: 2 files", body)
        self.assertIn("Classic Era: 1 file", body)
        self.assertIn(report.DISCLAIMER, alerts)
        self.assertTrue(any("move down" in a for a in alerts))  # an array entry deleted
        title, body, alerts = report.apply_confirm(self.staging.plans(), dry_run=True)
        self.assertEqual(title, "Dry run")
        self.assertIn("no file is written", body)

    def test_apply_confirm_names_the_dropped_hits(self):
        hits = run_search(self.files, SearchSpec(value=SVB_FONT, replacement="Arial")).hits
        self.stage(self.file(self.retail, "ElvUI.lua"), "set_value", ELVUI_FONT, "Arial Narrow")
        _, _, alerts = report.apply_confirm(self.staging.plans(hits), dry_run=False)
        self.assertTrue(any(a.startswith("1 ticked result is left out") for a in alerts), alerts)

    def test_undo_confirm_carries_the_disclaimer(self):
        self.stage_two_flavors()
        result = self.apply()
        title, body, alerts = report.undo_confirm(journal.read_journal(result.journal_path))
        self.assertEqual(title, "Undo the last change?")
        self.assertIn("Put back 2 files", body)
        self.assertEqual(alerts, [report.DISCLAIMER])

    def test_result_rows(self):
        hits = run_search(self.files, SearchSpec(value=SVB_FONT, replacement="Arial")).hits
        self.stage(self.file(self.retail, "ElvUI.lua"), "set_value", ELVUI_FONT, "Arial Narrow")
        plan = self.staging.plans(hits)
        result = self.apply(plan)
        rows = dict(report.summary_rows(result, plan))
        self.assertEqual(rows["Flavors"], "Retail, Classic Era")
        self.assertEqual(rows["Changed"], f"{len(plan.files)} files")
        self.assertEqual(rows["Edits written"], f"{plan.staged + plan.hits} edits")
        self.assertEqual(rows["Ticked results left out"], "1 result")
        self.assertIn("Backup folder", rows)
        self.assertIn("Journal", rows)
        files = report.file_rows(result)
        self.assertEqual(len(files), len(plan.files))
        self.assertTrue(all(len(row) == len(report.FILE_COLUMNS) for row in files))
        elvui = next(row for row in files if row[3] == "ElvUI.lua" and row[2] == "Account-wide")
        self.assertEqual(elvui, ("Retail", "ACCT1", "Account-wide", "ElvUI.lua", "2 edits", "changed"))

    def test_dry_run_rows_say_would(self):
        self.stage_two_flavors()
        result = self.apply(dry_run=True)
        rows = dict(report.summary_rows(result))
        self.assertEqual(rows["Would change"], "2 files")
        self.assertEqual(rows["Edits checked"], "2 edits")
        self.assertNotIn("Journal", rows)
        self.assertEqual({row[-1] for row in report.file_rows(result)}, {"would change"})

    def test_skipped_and_stopped_rows(self):
        elvui, _ = self.stage_two_flavors()
        elvui.write_bytes(self.before[elvui] + b"-- saved\r\n")
        result = self.apply()
        row = next(r for r in report.file_rows(result) if r[3] == "ElvUI.lua")
        self.assertEqual(row[-2:], ("", f"skipped: {sv_apply.CHANGED}"))
        self.assertEqual(dict(report.summary_rows(result))["Skipped"], "1 file")


if __name__ == "__main__":
    unittest.main()
