"""The UI-free helpers the tools share (core/text, core/progress, core/marker, core/undo, the journal and install
helpers): one definition each, tested here once instead of per tool."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core import marker
from wowtools.core.events import capture_events
from wowtools.core.install import Flavor, WowInstall, flavor_name, validate_backup_dir
from wowtools.core.journal import ToolJournals, read_journal, tool_root
from wowtools.core.progress import PROGRESS_INTERVAL, ThrottledProgress
from wowtools.core.text import MISSING, human_size, plural
from wowtools.core.undo import FAILED, RESTORED, SKIPPED, UndoResultBase, safe_destination
from wowtools.tools.wtf_cleaner.events import TOOL_NAME as CLEANER


class TextTest(unittest.TestCase):
    def test_plural(self):
        self.assertEqual(plural(1, "file"), "1 file")
        self.assertEqual(plural(0, "file"), "0 files")
        self.assertEqual(plural(2, "copy", "copies"), "2 copies")
        self.assertEqual(plural(1, "copy", "copies"), "1 copy")

    def test_human_size(self):
        self.assertEqual(human_size(None), MISSING)
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(1023), "1023 B")
        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_size(5 * 1024 * 1024), "5.0 MB")
        self.assertEqual(human_size(3 * 1024 ** 3), "3.0 GB")
        self.assertEqual(human_size(5 * 1024 ** 5), "5120.0 TB")

    def test_flavor_name_is_the_flavor_display_name(self):
        for folder in ("_retail_", "_classic_era_", "_xptr_", "_some_new_one_"):
            self.assertEqual(flavor_name(folder), Flavor(folder, Path(folder)).display_name)
        self.assertEqual(flavor_name("_retail_"), "Retail")
        self.assertEqual(flavor_name("_some_new_one_"), "Some New One")


class ValidateBackupDirTest(unittest.TestCase):
    def test_backup_folder_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_wow_tree(Path(tmp) / "WoW")
            install = WowInstall(root)
            self.assertIsNone(validate_backup_dir(None, install))
            self.assertIsNone(validate_backup_dir(Path(tmp) / "bk", install))
            self.assertIn("backup folder", validate_backup_dir(root, install) or "")
            self.assertIn("WTF", validate_backup_dir(root / "_retail_" / "WTF" / "x", install) or "")
            self.assertIn("D:\\WoW backups", validate_backup_dir(Path("relative"), install) or "")


class ThrottledProgressTest(unittest.TestCase):
    def test_forwards_stage_changes_ends_and_one_per_interval(self):
        now = [0.0]
        sent = []
        progress = ThrottledProgress(lambda *a: sent.append(a), 0.1, clock=lambda: now[0])
        for i in range(1, 6):
            progress("backup", i, 10, f"f{i}")  # first one forwarded, then nothing until the interval
        now[0] = 0.15
        progress("backup", 6, 10, "f6")  # interval passed
        progress("backup", 7, 10, "f7")
        progress("backup", 10, 10, "f10")  # end of the stage
        progress("verify", 1, 10, "v1")  # new stage
        progress("swap", 0, 0, "Interface")  # no count
        progress("swap", 0, 0, "WTF")  # no count again
        progress("verify", 2, 10, "v2")  # stage changed again
        self.assertEqual([a[3] for a in sent], ["f1", "f6", "f10", "v1", "Interface", "WTF", "v2"])

    def test_default_interval(self):
        self.assertEqual(ThrottledProgress(print).interval, PROGRESS_INTERVAL)

    def test_several_threads_are_throttled_each_on_its_own(self):
        # The clock never moves: each thread gets its first report and its stage's end through, nothing else, even
        # with the four stages interleaving (a shared single stage slot let every report through).
        sent = []
        progress = ThrottledProgress(lambda *a: sent.append(a), 3600.0, clock=lambda: 0.0)

        def work(stage):
            for i in range(1, 501):
                progress(stage, i, 500, f"{stage}{i}")

        threads = [threading.Thread(target=work, args=(f"s{n}",)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(sent), 4 * 2)
        for n in range(4):
            mine = [a for a in sent if a[0] == f"s{n}"]
            self.assertEqual(mine, [(f"s{n}", 1, 500, f"s{n}1"), (f"s{n}", 500, 500, f"s{n}500")])

    def test_interleaved_stages_from_two_threads_stay_throttled(self):
        now = [0.0]
        sent = []
        progress = ThrottledProgress(lambda *a: sent.append(a[3]), 0.1, clock=lambda: now[0])
        workers = {name: ThreadPoolExecutor(max_workers=1) for name in "ABC"}  # one thread per stage
        self.addCleanup(lambda: [w.shutdown() for w in workers.values()])

        def report(name, current, total=100):
            workers[name].submit(progress, name, current, total, f"{name}{current}").result()

        for i in range(1, 50):
            report("A", i)
            report("B", i)
        now[0] = 0.15
        report("A", 50)
        report("B", 50)
        report("C", 0, 0)  # a third thread: its first report goes through
        self.assertEqual(sent, ["A1", "B1", "A50", "B50", "C0"])

    def test_a_report_decided_first_is_never_forwarded_after_a_later_stage_end(self):
        # Worker A's report is let through and its forward is slow; worker B then ends the stage. B's end must
        # reach the UI last, not A's stale 5/10.
        sent = []
        in_forward = threading.Event()

        def forward(*args):
            if args[1] == 5:
                in_forward.set()
                time.sleep(0.2)
            sent.append(args[:3])

        progress = ThrottledProgress(forward, 3600.0, clock=lambda: 0.0)
        a = threading.Thread(target=progress, args=("backup", 5, 10, "x"))
        a.start()
        self.assertTrue(in_forward.wait(5))
        b = threading.Thread(target=progress, args=("backup", 10, 10, "y"))
        b.start()
        a.join()
        b.join()
        self.assertEqual(sent, [("backup", 5, 10), ("backup", 10, 10)])


class MarkerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "out"

    def test_write_read_clear(self):
        marker.write_marker(self.folder, "run.json", {"zip": Path("/x/y.zip"), "files": ["a"], "pid": 7})
        path = self.folder / "run.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                         {"zip": str(Path("/x/y.zip")), "files": ["a"], "pid": 7})
        self.assertFalse(path.with_name("run.json.partial").exists())
        self.assertEqual(marker.read_marker(self.folder, "run.json")["pid"], 7)
        marker.clear_marker(self.folder, "run.json")
        self.assertFalse(path.exists())
        marker.clear_marker(self.folder, "run.json")  # already gone: no error

    def test_unreadable_marker_is_none(self):
        self.assertIsNone(marker.read_marker(None, "run.json"))
        self.assertIsNone(marker.read_marker(self.folder, "run.json"))
        self.folder.mkdir()
        for raw in (b"{not json", b"[1, 2]", b"\xff\xfe\x00garbage"):
            (self.folder / "run.json").write_bytes(raw)
            self.assertIsNone(marker.read_marker(self.folder, "run.json"))


@dataclass
class _Outcome:
    status: str


@dataclass
class _Result(UndoResultBase):
    outcomes: list[_Outcome] = field(default_factory=list)


class UndoTest(unittest.TestCase):
    def test_result_lists_by_status(self):
        result = _Result([_Outcome(RESTORED), _Outcome(SKIPPED), _Outcome(FAILED), _Outcome(RESTORED)])
        self.assertEqual(len(result.restored), 2)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(len(result.failed), 1)

    def test_safe_destination(self):
        wow = Path("/wow")
        self.assertEqual(safe_destination(wow, "_retail_", "WTF/Config.wtf"), wow / "_retail_" / "WTF" / "Config.wtf")
        for flavor in ("", ".", "..", "a/b", "a\\b", "C:"):
            self.assertIsNone(safe_destination(wow, flavor, "WTF/Config.wtf"), flavor)
        for rel in ("WTF", "/WTF/x", "WTF/../x", "Interface/x", "WTF/a\\b", "WTF/C:x"):
            self.assertIsNone(safe_destination(wow, "_retail_", rel), rel)

    def test_safe_destination_shape(self):
        wow = Path("/wow")
        shape = {"prefix": ("WTF", "Account"), "min_parts": 5, "parent": "SavedVariables"}
        good = "WTF/Account/A/SavedVariables/x.lua"
        self.assertEqual(safe_destination(wow, "_retail_", good, **shape), wow.joinpath("_retail_", *good.split("/")))
        for rel in ("WTF/Account/A/x.lua", "WTF/Account/A/Other/x.lua", "WTF/Config/A/SavedVariables/x.lua"):
            self.assertIsNone(safe_destination(wow, "_retail_", rel, **shape), rel)


class ToolJournalsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wow = Path(tmp.name) / "WoW"

    def write(self, folder, name, *records):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return folder / name

    def test_tool_root(self):
        self.assertEqual(tool_root(None, self.wow, CLEANER), self.wow / "wow-tools" / CLEANER)
        self.assertEqual(tool_root(self.wow / "b", self.wow, CLEANER), self.wow / "b" / CLEANER)
        self.assertEqual(tool_root(self.wow / "b", None, CLEANER), self.wow / "b" / CLEANER)
        self.assertIsNone(tool_root(None, None, CLEANER))

    def test_dir_latest_and_prune_with_event(self):
        journals = ToolJournals(CLEANER, read_journal, "clean.journal_pruned")
        folder = journals.dir(self.wow)
        self.assertEqual(folder, self.wow / "wow-tools" / CLEANER / "journal")
        self.assertIsNone(journals.dir(None))
        for day in range(1, 4):
            self.write(folder, f"journal-2026010{day}-000000.jsonl", {"version": 1}, {"action": "deleted"})
        self.assertEqual(journals.latest_undoable(folder).name, "journal-20260103-000000.jsonl")
        with capture_events() as records:
            removed = journals.prune(folder, 1)
        self.assertEqual(len(removed), 2)
        pruned = [r["data"] for r in records if r["event"] == "clean.journal_pruned"]
        self.assertEqual(pruned, [{"removed": [p.name for p in removed], "keep": 1}])

    def test_reader_decides_what_is_undoable_and_no_event_logs_nothing(self):
        def nothing_undoable(path):
            journal = read_journal(path)
            journal.entries = []
            return journal

        journals = ToolJournals("some-tool", nothing_undoable)
        folder = journals.dir(self.wow)
        for day in range(1, 3):
            self.write(folder, f"journal-2026010{day}-000000.jsonl", {"version": 1}, {"action": "x"})
        self.assertIsNone(journals.latest_undoable(folder))
        with capture_events() as records:
            self.assertEqual(len(journals.prune(folder, 1)), 1)
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
