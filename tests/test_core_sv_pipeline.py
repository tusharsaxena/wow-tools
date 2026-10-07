"""The shared SavedVariables write pipeline (SV Browser spec D14-D16, D19, D20): core/sv_apply.py, sv_journal.py,
sv_undo.py, sv_verify.py and sv_report.py driven by a made-up tool, with its own event prefix and callbacks."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core import sv_apply, sv_journal, sv_undo
from wowtools.core.backup import BackupEntry, create_backup
from wowtools.core.events import TOOL_REGISTRIES, capture_events, register_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.core.luasv import parse
from wowtools.core.sv_events import SvTool, sv_events
from wowtools.core.sv_report import (apply_summary_rows, leave_notice, recovered_notice, recovery_text, undo_detail_rows,
                                    undo_summary_rows)
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

    def run_apply(self, apply_one=None, **kwargs):
        options = {"root": self.root, "journal_dir": self.journals, "keep_journals": 5, "keep_snapshots": 2,
                   "dry_run": False, "now": WHEN}
        options.update(kwargs)
        return sv_apply.apply_flavors(TOOL, [(self.flavor, self.units())], apply_one or self.apply_one, **options)

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
            result = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                     now=WHEN)
        self.assertIn("tsv.recovery_done", [e["event"] for e in events])
        self.assertEqual(len(result.restored), 1)
        self.assertEqual({p: p.read_bytes() for p in self.paths}, self.originals)
        self.assertIsNone(sv_apply.read_marker(self.root))
        self.assertIsNone(TOOL.journals.latest_undoable(self.journals))

    def test_a_marker_that_cannot_be_removed_is_reported(self):
        real_remove = os.remove

        def remove(path, *args, **kwargs):
            if Path(path).name == sv_apply.MARKER_NAME:
                raise PermissionError(13, "held by another program", str(path))
            return real_remove(path, *args, **kwargs)
        with patch("wowtools.core.marker.os.remove", side_effect=remove), \
                patch("wowtools.core.marker.time.sleep") as slept, capture_events() as events:
            result = self.run_apply()
        run = result.runs[0].result
        self.assertTrue(run.marker_left)
        self.assertTrue(result.marker_left)
        self.assertTrue(slept.called)  # retried before giving up
        left = [e for e in events if e["event"] == "tsv.marker_left"]
        self.assertEqual(len(left), 1)
        self.assertEqual(TOOL_REGISTRIES[TOOL.name]["tsv.marker_left"].level, "warning")
        self.assertEqual(len(result.edited), 2)
        self.assertIsNotNone(sv_apply.read_marker(self.root))
        self.assertIn("Crash marker", dict(apply_summary_rows(result)))

    def test_a_marker_removed_after_a_retry_is_not_reported(self):
        real_remove, calls = os.remove, []

        def remove(path, *args, **kwargs):
            if Path(path).name == sv_apply.MARKER_NAME and not calls:
                calls.append(path)
                raise PermissionError(13, "held for a moment", str(path))
            return real_remove(path, *args, **kwargs)
        with patch("wowtools.core.marker.os.remove", side_effect=remove), \
                patch("wowtools.core.marker.time.sleep"), capture_events() as events:
            result = self.run_apply()
        self.assertFalse(result.marker_left)
        self.assertNotIn("tsv.marker_left", [e["event"] for e in events])
        self.assertIsNone(sv_apply.read_marker(self.root))
        self.assertNotIn("Crash marker", dict(apply_summary_rows(result)))

    def finished_run_with_its_marker(self):
        """A successful Apply whose crash marker is written back by hand, as if removing it had failed."""
        captured = []
        real_write = sv_apply.write_marker

        def keep(root, marker):
            captured.append(marker)
            real_write(root, marker)
        with patch("wowtools.core.sv_apply.write_marker", side_effect=keep):
            result = self.run_apply()
        self.assertIsNone(sv_apply.read_marker(self.root))
        sv_apply.write_marker(self.root, captured[0])
        return result, sv_apply.read_marker(self.root)

    def test_recovery_of_a_finished_run_changes_nothing(self):
        result, marker = self.finished_run_with_its_marker()
        after = {p: p.read_bytes() for p in self.paths}
        self.assertTrue(all(sha256_of(after[p]) == marker.after[p.relative_to(self.flavor.path).as_posix()]
                            for p in self.paths))
        journal_before = result.journal_path.read_bytes()
        with capture_events() as events:
            recovered = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                        now=WHEN, wow_check=lambda: ["Wow.exe"])
        names = [e["event"] for e in events]
        self.assertIn("tsv.marker_stale", names)
        self.assertNotIn("tsv.file_restored", names)
        self.assertTrue(recovered.stale_marker)
        self.assertEqual((recovered.outcomes, recovered.snapshots), ([], []))
        self.assertEqual({p: p.read_bytes() for p in self.paths}, after)
        self.assertIsNone(sv_apply.read_marker(self.root))
        self.assertEqual(result.journal_path.read_bytes(), journal_before)  # no rolled_back record
        self.assertEqual(TOOL.journals.latest_undoable(self.journals), result.journal_path)
        self.assertIn("Already finished", dict(undo_summary_rows(recovered)))
        self.assertEqual(recovered_notice(recovered)[1], "information")
        self.assertTrue(recovered_notice(recovered)[0].startswith("That change had finished"))

    def test_recovery_still_puts_back_a_run_whose_journal_misses_a_file(self):
        result, marker = self.finished_run_with_its_marker()
        rel = self.paths[1].relative_to(self.flavor.path).as_posix()
        sv_journal.core.append_record(result.journal_path, {"action": "rolled_back", "flavor": "_retail_",
                                                            "rels": [rel]})
        recovered = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                    now=WHEN)
        self.assertFalse(recovered.stale_marker)
        self.assertEqual(len(recovered.restored), 2)
        self.assertEqual({p: p.read_bytes() for p in self.paths}, self.originals)

    def test_recovery_of_a_finished_run_that_skipped_a_file_changes_nothing(self):
        """A file that changed between the check and the write loop is skipped (no edited entry); a finished run
        is still recognised when that file is not at what the run would have written, so nothing is put back."""
        captured, real_write = [], sv_apply.write_marker

        def keep(root, marker):
            captured.append(marker)
            real_write(root, marker)
            self.paths[1].write_bytes(b'DB = {\n\t["x"] = 9,\n}\n')  # WoW saves it before the loop reaches it
        with patch("wowtools.core.sv_apply.write_marker", side_effect=keep):
            result = self.run_apply()
        self.assertEqual((len(result.edited), len(result.skipped)), (1, 1))
        sv_apply.write_marker(self.root, captured[0])  # as if removing it had failed
        marker = sv_apply.read_marker(self.root)
        after = {p: p.read_bytes() for p in self.paths}
        with capture_events() as events:
            recovered = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                        now=WHEN)
        self.assertTrue(recovered.stale_marker)
        self.assertNotIn("tsv.file_restored", [e["event"] for e in events])
        self.assertEqual({p: p.read_bytes() for p in self.paths}, after)
        self.assertIsNone(sv_apply.read_marker(self.root))

    def test_recovery_of_a_finished_run_whose_skipped_file_is_at_its_after_is_put_back(self):
        """The skipped file reads as what the run would have written: the journal cannot tell, so recover as before."""
        captured, real_write = [], sv_apply.write_marker

        def keep(root, marker):
            captured.append(marker)
            real_write(root, marker)
            self.paths[1].write_bytes(b'DB = {\n\t["x"] = 3,\n}\n')
        with patch("wowtools.core.sv_apply.write_marker", side_effect=keep):
            self.run_apply()
        marker = captured[0]
        self.paths[1].write_bytes(self.originals[self.paths[1]].replace(b"1", b"2"))  # now at marker.after
        sv_apply.write_marker(self.root, marker)
        recovered = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                    now=WHEN)
        self.assertFalse(recovered.stale_marker)
        self.assertEqual(len(recovered.restored), 2)

    def stopped_run(self, write):
        """A real apply_flavors run that stops while writing, and whose roll-back fails: the journal ends with
        "finished" (the run is over) but the flavor did not complete, so its marker is kept."""
        def apply_one(flavor, units, **kwargs):
            return sv_apply.apply_flavor(TOOL, flavor, units, compile_swap, no_problems, write=write, **kwargs)
        with patch("wowtools.core.sv_apply.restore_original", side_effect=OSError("no")):
            result = self.run_apply(apply_one=apply_one)
        self.assertIsNotNone(result.stopped)
        self.assertTrue(sv_journal.read_edit_journal(result.journal_path).finished)
        marker = sv_apply.read_marker(self.root)
        self.assertIsNotNone(marker)
        return marker

    def test_recovery_after_a_stopped_run_whose_roll_back_failed_puts_back(self):
        def write(path, data):
            if path == self.paths[0]:
                atomic_write_bytes(path, data)
            else:
                raise OSError("killed")
        marker = self.stopped_run(write)
        with capture_events() as events:
            recovered = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                        now=WHEN)
        self.assertNotIn("tsv.marker_stale", [e["event"] for e in events])
        self.assertFalse(recovered.stale_marker)
        self.assertEqual(len(recovered.restored), 1)
        self.assertEqual({p: p.read_bytes() for p in self.paths}, self.originals)
        self.assertIsNone(sv_apply.read_marker(self.root))

    def test_recovery_after_a_failed_read_back_is_not_taken_as_finished(self):
        def write(path, data):
            atomic_write_bytes(path, data if path == self.paths[0] else b"garbage")
        marker = self.stopped_run(write)
        recovered = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                    now=WHEN)
        self.assertFalse(recovered.stale_marker)
        self.assertEqual(self.paths[0].read_bytes(), self.originals[self.paths[0]])  # at its after: put back
        self.assertEqual(self.paths[1].read_bytes(), b"garbage")  # neither original nor after: never overwritten
        self.assertEqual([o.rel for o in recovered.skipped],
                         [self.paths[1].relative_to(self.flavor.path).as_posix()])

    def failing_marker_remove(self):
        real_remove = os.remove

        def remove(path, *args, **kwargs):
            if Path(path).name == sv_apply.MARKER_NAME:
                raise PermissionError(13, "held by another program", str(path))
            return real_remove(path, *args, **kwargs)
        return patch("wowtools.core.marker.os.remove", side_effect=remove)

    def test_stale_recovery_reports_a_marker_it_could_not_remove(self):
        _, marker = self.finished_run_with_its_marker()
        with self.failing_marker_remove(), patch("wowtools.core.marker.time.sleep"), capture_events() as events:
            recovered = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                        now=WHEN)
        self.assertTrue(recovered.stale_marker)
        self.assertTrue(recovered.marker_left)
        self.assertIsNotNone(sv_apply.read_marker(self.root))
        stale = [e for e in events if e["event"] == "tsv.marker_stale"]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["level"], "warning")
        self.assertTrue(stale[0]["data"]["marker_left"])
        message, severity = recovered_notice(recovered)
        self.assertEqual(severity, "warning")
        self.assertNotIn("marker was removed", message)
        self.assertIn("could not be removed", message)
        self.assertIn("Crash marker", dict(undo_summary_rows(recovered)))

    def test_recovery_reports_a_marker_it_could_not_remove_after_putting_back(self):
        def write(path, data):
            if path == self.paths[0]:
                atomic_write_bytes(path, data)
            else:
                raise OSError("killed")
        journal = sv_journal.EditJournal(self.journals / "journal-20261007-120000.jsonl", {"kind": "apply"})
        self.addCleanup(journal.close)
        with patch("wowtools.core.sv_apply.restore_original", side_effect=OSError("no")), \
                self.assertRaises(sv_apply.ApplyError):
            sv_apply.apply_flavor(TOOL, self.flavor, self.units(), compile_swap, no_problems, root=self.root,
                                  journal=journal, dry_run=False, keep_snapshots=2, now=WHEN, write=write)
        journal.close()
        marker = sv_apply.read_marker(self.root)
        with self.failing_marker_remove(), patch("wowtools.core.marker.time.sleep"), capture_events() as events:
            result = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                     now=WHEN)
        self.assertEqual(len(result.restored), 1)
        self.assertTrue(result.marker_left)
        done = [e for e in events if e["event"] == "tsv.recovery_done"]
        self.assertEqual(done[0]["level"], "warning")
        self.assertTrue(done[0]["data"]["marker_left"])
        message, severity = recovered_notice(result)
        self.assertEqual(severity, "warning")
        self.assertIn("could not be removed", message)

    def test_leave_reports_a_marker_it_could_not_remove(self):
        _, marker = self.finished_run_with_its_marker()
        with self.failing_marker_remove(), patch("wowtools.core.marker.time.sleep"), capture_events() as events:
            self.assertFalse(sv_undo.leave(TOOL, marker, root=self.root))
        done = [e for e in events if e["event"] == "tsv.recovery_done"]
        self.assertEqual((done[0]["data"]["choice"], done[0]["data"]["marker_left"], done[0]["level"]),
                         ("leave", True, "warning"))
        self.assertIsNotNone(sv_apply.read_marker(self.root))
        self.assertIn("could not be removed", leave_notice()[0])
        self.assertEqual(leave_notice()[1], "warning")
        with capture_events() as events:
            self.assertTrue(sv_undo.leave(TOOL, marker, root=self.root))
        self.assertFalse(events[0]["data"]["marker_left"])
        self.assertIsNone(sv_apply.read_marker(self.root))

    def test_recovery_text_names_the_run_and_its_zip(self):
        marker = sv_apply.Marker("_retail_", self.flavor.path, self.root / "edited.zip", {"a": "0", "b": "1"},
                                 "2026-10-07T12:00:00", 1, "0.1.0")
        lines = recovery_text(marker).splitlines()
        self.assertIn("did not finish (2 files)", lines[0])
        self.assertIn(str(self.root / "edited.zip"), lines)
        self.assertTrue(lines[-2].startswith("Put the originals back:"))
        self.assertTrue(lines[-1].startswith("Leave as is:"))

    def test_undo_never_snapshots_a_flavor_outside_the_install(self):
        outside = self.tmp / "elsewhere" / "WTF"
        outside.mkdir(parents=True)
        (outside / "secret.lua").write_bytes(b"secret")
        rel = "WTF/Account/ACCT1/SavedVariables/A.lua"
        path = self.journals / "journal-20261007-120000.jsonl"
        journal = sv_journal.EditJournal(path, {"kind": "apply"})
        journal.add_edited(flavor="../elsewhere", path=self.paths[0], rel=rel, zip_path=self.root / "edited.zip",
                           sha_before="0", sha_after="1", size_before=1, size_after=1, changes=[])
        journal.close()
        before = sorted(p for p in self.tmp.rglob("*"))
        result = sv_undo.undo_run(TOOL, path, wow_root=self.wow, root=self.root, keep_snapshots=2, now=WHEN)
        self.assertEqual(result.snapshots, [])
        self.assertFalse(list(self.tmp.rglob("*.zip")))
        self.assertEqual([p for p in sorted(self.tmp.rglob("*")) if p not in before and p != path], [])
        self.assertEqual([(o.status, o.detail) for o in result.outcomes], [(sv_undo.SKIPPED,
                                                                            "it is outside the WTF folder")])

    def test_undo_flavors_keeps_only_flavors_with_an_entry_inside_the_install(self):
        good = "WTF/Account/ACCT1/SavedVariables/A.lua"
        entries = [{"flavor": "_retail_", "rel": good}, {"flavor": "../elsewhere", "rel": good},
                   {"flavor": "_classic_", "rel": "../../outside.lua"}, {"flavor": "_retail_", "rel": good},
                   {"flavor": "_beta_", "rel": "../../outside.lua"}, {"flavor": "_beta_", "rel": good}]
        self.assertEqual([(f.folder, f.path) for f in sv_undo.undo_flavors(self.wow, entries)],
                         [("_beta_", self.wow / "_beta_"), ("_retail_", self.wow / "_retail_")])

    def foreign_marker(self, flavor: str = "_retail_", flavor_path: str = "G:\\World of Warcraft\\_retail_"):
        """An edit-in-progress.json as written on Windows (paths in Windows form) for A.lua, which holds what the
        run wrote; its originals zip is in <root>/edited/ under the same name. Returns (marker, rel)."""
        rel = self.paths[0].relative_to(self.flavor.path).as_posix()
        (self.root / "edited" / "edited-x.zip").unlink(missing_ok=True)
        create_backup([BackupEntry(self.paths[0])], self.flavor.path, self.root / "edited" / "edited-x.zip", {})
        after = b'DB = {\n\t["x"] = 2,\n}\n'
        self.paths[0].write_bytes(after)
        data = {"flavor": flavor, "flavor_path": flavor_path, "zip": "G:\\wow-tools\\out\\edited\\edited-x.zip",
                "files": {rel: sha256_of(self.originals[self.paths[0]])}, "started": "2026-10-07T12:00:00",
                "pid": 1, "suite_version": "0.1.0", "after": {rel: sha256_of(after)}}
        (self.root / sv_apply.MARKER_NAME).write_text(json.dumps(data), encoding="utf-8")
        marker = sv_apply.read_marker(self.root)
        self.assertIsNotNone(marker)
        return marker, rel

    def test_recover_uses_the_configured_wow_folder_not_the_markers(self):
        marker, rel = self.foreign_marker()
        result = sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                 now=WHEN)
        self.assertEqual([(o.rel, o.status) for o in result.outcomes], [(rel, sv_undo.RESTORED)])
        self.assertEqual({p: p.read_bytes() for p in self.paths}, self.originals)
        self.assertIsNone(sv_apply.read_marker(self.root))

    def test_recover_never_touches_the_folder_the_marker_names(self):
        decoy = self.tmp / "x" / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "A.lua"
        decoy.parent.mkdir(parents=True)
        marker, _rel = self.foreign_marker(flavor_path=str(self.tmp / "x" / "_retail_"))
        decoy.write_bytes(self.paths[0].read_bytes())  # what the run wrote: recovery would put it back
        sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals, now=WHEN)
        self.assertEqual(decoy.read_bytes(), b'DB = {\n\t["x"] = 2,\n}\n')
        self.assertEqual([p for p in (self.tmp / "x").rglob("*") if p.is_file()], [decoy])
        self.assertEqual(self.paths[0].read_bytes(), self.originals[self.paths[0]])

    def test_recover_refuses_a_flavor_not_in_the_wow_folder_and_keeps_the_marker(self):
        for flavor in ("_ptr_", "../elsewhere", "_retail_/WTF"):
            with self.subTest(flavor=flavor):
                marker, _rel = self.foreign_marker(flavor=flavor)
                with self.assertRaises(sv_undo.UndoError) as caught:
                    sv_undo.recover(TOOL, marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                    now=WHEN)
                self.assertTrue(str(caught.exception).endswith("Nothing was changed."), str(caught.exception))
                self.assertIsNotNone(sv_apply.read_marker(self.root))
                self.assertFalse((self.root / sv_apply.SNAPSHOT_SUBDIR).exists())
                self.paths[0].write_bytes(self.originals[self.paths[0]])

    @unittest.skipIf(os.name == "nt", "simulates WSL: /mnt/g paths only exist on POSIX")
    def test_marker_paths_are_stored_in_windows_form_and_read_natively(self):
        marker = sv_apply.Marker("_retail_", Path("/mnt/g/World of Warcraft/_retail_"),
                                 Path("/mnt/d/wow-tools/out/edited/edited-x.zip"), {"a": "0"}, "now", 1, "0.1.0")
        with patch("wowtools.core.paths.is_wsl", return_value=True):
            sv_apply.write_marker(self.root, marker)
            data = json.loads((self.root / sv_apply.MARKER_NAME).read_text(encoding="utf-8"))
            self.assertEqual((data["flavor_path"], data["zip"]),
                             ("G:\\World of Warcraft\\_retail_", "D:\\wow-tools\\out\\edited\\edited-x.zip"))
            self.assertEqual(sv_apply.read_marker(self.root), marker)

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
