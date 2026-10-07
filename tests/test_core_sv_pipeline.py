"""The shared SavedVariables write pipeline (SV Browser spec D14-D16, D19, D20): core/sv_apply.py, sv_journal.py,
sv_undo.py, sv_verify.py and sv_report.py driven by a made-up tool, with its own event prefix and callbacks."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core import sv_apply, sv_journal, sv_undo
from wowtools.core.events import TOOL_REGISTRIES, capture_events, register_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.core.luasv import parse
from wowtools.core.sv_events import SvTool, sv_events
from wowtools.core.sv_report import apply_summary_rows, recovery_text, undo_detail_rows, undo_summary_rows
from wowtools.core.sv_verify import check_assignments, gaps, rest_outside, same_outside
from wowtools.core.svfiles import SvFile, sha256_of

TOOL = SvTool("test-sv-pipeline", "tsv")
register_events(TOOL.name, sv_events(TOOL.prefix))
WHEN = datetime(2026, 10, 7, 12, 0, 0)


@dataclass
class Edit:
    data: bytes
    changes: list[str] = field(default_factory=list)


def compile_swap(file: SvFile, payload: tuple[bytes, bytes], data: bytes) -> Edit:
    old, new = payload
    return Edit(data.replace(old, new), [f"{old.decode()} -> {new.decode()}"])


def no_problems(edit: Edit, data: bytes) -> list[str]:
    return []


class PipelineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_wow_tree(self.tmp / "wow")
        self.flavor = WowInstall(self.wow).flavor("_retail_")
        self.root = self.tmp / "out" / TOOL.name
        self.journals = self.tmp / "journal"
        sv = self.flavor.account_dir / "ACCT1" / "SavedVariables"
        self.paths = [sv / "A.lua", sv / "B.lua"]
        for path in self.paths:
            path.write_bytes(b'DB = {\n\t["x"] = 1,\n}\n')
        self.originals = {p: p.read_bytes() for p in self.paths}

    def svfile(self, path: Path) -> SvFile:
        data = path.read_bytes()
        return SvFile(path, self.flavor, "ACCT1", None, len(data), 0.0, sha256_of(data))

    def units(self):
        return [(self.svfile(p), (b"1", b"2")) for p in self.paths]

    def apply_one(self, flavor, units, **kwargs):
        return sv_apply.apply_flavor(TOOL, flavor, units, compile_swap, no_problems, **kwargs)

    def run_apply(self, **kwargs):
        options = {"root": self.root, "journal_dir": self.journals, "keep_journals": 5, "keep_snapshots": 2,
                   "dry_run": False, "now": WHEN}
        options.update(kwargs)
        return sv_apply.apply_flavors(TOOL, [(self.flavor, self.units())], self.apply_one, **options)

    def test_events_are_named_from_the_prefix(self):
        names = set(sv_events("xyz"))
        self.assertTrue(all(n.startswith("xyz.") for n in names))
        self.assertEqual({n.split(".", 1)[1] for n in names}, {n.split(".", 1)[1] for n in sv_events("tsv")})
        self.assertIn("xyz.apply_started", names)
        self.assertIn("xyz.journal_pruned", names)
        self.assertEqual(TOOL.event("file_edited"), "tsv.file_edited")
        self.assertEqual(TOOL_REGISTRIES[TOOL.name]["tsv.file_edited"].level, "info")

    def test_apply_then_undo(self):
        with capture_events() as events:
            result = self.run_apply()
        names = [e["event"] for e in events]
        for name in ("tsv.apply_started", "tsv.snapshot_taken", "tsv.files_backed_up", "tsv.file_edited",
                     "tsv.apply_completed"):
            self.assertIn(name, names)
        self.assertFalse([n for n in names if n.startswith("ace.")])
        self.assertEqual(len(result.edited), 2)
        self.assertTrue(all(b'["x"] = 2' in p.read_bytes() for p in self.paths))
        self.assertIsNone(sv_apply.read_marker(self.root))
        run = result.runs[0].result
        self.assertTrue(run.snapshot.exists())
        self.assertTrue(run.backup_zip.exists())
        journal = sv_journal.read_edit_journal(result.journal_path)
        self.assertEqual(journal.header["tool"], TOOL.name)
        self.assertEqual(sorted(e["rel"] for e in journal.entries),
                         sorted(p.relative_to(self.flavor.path).as_posix() for p in self.paths))
        self.assertEqual(TOOL.journals.latest_undoable(self.journals), result.journal_path)
        rows = dict(apply_summary_rows(result))
        self.assertEqual(rows["Changed"], "2 files")
        with capture_events() as events:
            undone = sv_undo.undo_run(TOOL, result.journal_path, wow_root=self.wow, root=self.root,
                                      keep_snapshots=2, now=WHEN)
        self.assertIn("tsv.undo_completed", [e["event"] for e in events])
        self.assertEqual(len(undone.restored), 2)
        self.assertEqual({p: p.read_bytes() for p in self.paths}, self.originals)
        self.assertEqual(dict(undo_summary_rows(undone))["Put back"], "2 files")
        self.assertEqual(len(undo_detail_rows(undone)), 2)

    def test_dry_run_writes_nothing(self):
        result = self.run_apply(dry_run=True)
        self.assertEqual(len(result.would_edit), 2)
        self.assertEqual({p: p.read_bytes() for p in self.paths}, self.originals)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.journals.exists())

    def test_a_verify_problem_stops_before_anything_is_written(self):
        def apply_one(flavor, units, **kwargs):
            return sv_apply.apply_flavor(TOOL, flavor, units, compile_swap, lambda e, d: ["broken"], **kwargs)
        with capture_events() as events:
            result = sv_apply.apply_flavors(TOOL, [(self.flavor, self.units())], apply_one, root=self.root,
                                            journal_dir=self.journals, keep_journals=5, keep_snapshots=2,
                                            dry_run=False, now=WHEN)
        self.assertIn("tsv.verify_failed", [e["event"] for e in events])
        self.assertIn("broken", result.stopped.error)
        self.assertEqual({p: p.read_bytes() for p in self.paths}, self.originals)

    def test_one_wow_running_for_apply_and_undo(self):
        self.assertTrue(issubclass(sv_apply.WowRunning, sv_apply.ApplyError))
        self.assertTrue(issubclass(sv_apply.WowRunning, sv_undo.UndoError))
        self.assertIs(sv_undo.WowRunning, sv_apply.WowRunning)
        with self.assertRaises(sv_apply.WowRunning) as caught:
            self.run_apply(wow_check=lambda: ["Wow.exe"])
        self.assertIn("overwrite the changes", str(caught.exception))
        result = self.run_apply()
        with self.assertRaises(sv_undo.UndoError) as caught:
            sv_undo.undo_run(TOOL, result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2,
                             wow_check=lambda: ["Wow.exe"])
        self.assertIsInstance(caught.exception, sv_apply.WowRunning)
        self.assertIn("overwrite the files", str(caught.exception))

    def test_unfinished_run_is_recovered(self):
        def write(path, data):
            if path == self.paths[0]:
                atomic_write_bytes(path, data)
            else:
                raise OSError("killed")
        journal = sv_journal.EditJournal(self.journals / "journal-20261007-120000.jsonl", {"kind": "apply"})
        self.addCleanup(journal.close)
        with patch("wowtools.core.sv_apply.restore_original", side_effect=OSError("no")), \
                self.assertRaises(sv_apply.ApplyError) as caught:
            sv_apply.apply_flavor(TOOL, self.flavor, self.units(), compile_swap, no_problems, root=self.root,
                                  journal=journal, dry_run=False, keep_snapshots=2, now=WHEN, write=write)
        journal.close()
        self.assertTrue(caught.exception.files_left)
        marker = sv_apply.read_marker(self.root)
        self.assertIsNotNone(marker)
        with capture_events() as events:
            result = sv_undo.recover(TOOL, marker, root=self.root, journal_dir=self.journals, now=WHEN)
        self.assertIn("tsv.recovery_done", [e["event"] for e in events])
        self.assertEqual(len(result.restored), 1)
        self.assertEqual({p: p.read_bytes() for p in self.paths}, self.originals)
        self.assertIsNone(sv_apply.read_marker(self.root))
        self.assertIsNone(TOOL.journals.latest_undoable(self.journals))

    def test_recovery_text_names_the_run_and_its_zip(self):
        marker = sv_apply.Marker("_retail_", self.flavor.path, self.root / "edited.zip", {"a": "0", "b": "1"},
                                 "2026-10-07T12:00:00", 1, "0.1.0")
        lines = recovery_text(marker).splitlines()
        self.assertIn("did not finish (2 files)", lines[0])
        self.assertIn(str(self.root / "edited.zip"), lines)
        self.assertTrue(lines[-2].startswith("Put the originals back:"))
        self.assertTrue(lines[-1].startswith("Leave as is:"))

    def test_referenced_zips_none_when_a_journal_cannot_be_read(self):
        self.run_apply()
        self.assertTrue(sv_journal.referenced_zips(self.journals))
        with patch("wowtools.core.sv_journal.read_edit_journal", side_effect=PermissionError("held")):
            self.assertIsNone(sv_journal.referenced_zips(self.journals))


class VerifyHelpersTest(unittest.TestCase):
    OLD = b'-- head\nA = {\n\t["x"] = 1,\n}\n-- mid\nB = 2\n'

    def test_gaps_are_the_bytes_around_the_assignments(self):
        self.assertEqual(gaps(self.OLD, parse(self.OLD)), [b"-- head\n", b"\n-- mid\n", b"\n"])

    def test_check_assignments(self):
        old_chunk = parse(self.OLD)
        new = self.OLD.replace(b"= 1", b"= 5")
        self.assertEqual(check_assignments(self.OLD, old_chunk, new, parse(new), {"A"}), [])
        self.assertEqual(check_assignments(self.OLD, old_chunk, new, parse(new), set()),
                         ["A changed but nothing was planned for it"])
        renamed = self.OLD.replace(b"B = 2", b"C = 2")
        self.assertEqual(check_assignments(self.OLD, old_chunk, renamed, parse(renamed), {"A", "B"}),
                         ["the edited file does not hold the same SavedVariables"])
        comment = self.OLD.replace(b"-- mid", b"-- MID")
        self.assertEqual(check_assignments(self.OLD, old_chunk, comment, parse(comment), set()),
                         ["text between the SavedVariables changed"])
        seen = []
        check_assignments(self.OLD, old_chunk, new, parse(new), {"A"},
                          on_planned=lambda before, after: seen.append(before.name) or ["x"])
        self.assertEqual(seen, ["A"])

    def test_bytes_outside_the_spans(self):
        old, new = b"abcXdefYghi", b"abcLONGdefghi"
        self.assertTrue(same_outside(old, [(3, 4), (7, 8)], new, [(3, 7), (10, 10)]))
        self.assertFalse(same_outside(old, [(3, 4)], new, [(3, 7)]))
        self.assertEqual(rest_outside(b"0123456789", 1, 9, [(2, 4), (6, 7)]), b"1\x0045\x0078")


if __name__ == "__main__":
    unittest.main()
