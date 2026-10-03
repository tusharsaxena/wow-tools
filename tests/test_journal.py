import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from wowtools.core import journal as journal_mod
from wowtools.core.journal import (JOURNAL_VERSION, JournalWriter, friendly_stamp, journal_dir, latest_undoable,
                                   list_journals, mark_undone, new_journal_path, prune_journals, read_journal)


class JournalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "journal"

    def write(self, name, *records, raw=b""):
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / name
        path.write_bytes(b"".join(json.dumps(r).encode() + b"\n" for r in records) + raw)
        return path

    def test_journal_dir(self):
        self.assertIsNone(journal_dir(None, "wtf-cleaner"))
        self.assertEqual(journal_dir(Path("/w"), "wtf-cleaner"), Path("/w/wow-tools/wtf-cleaner/journal"))

    def test_friendly_stamp(self):
        self.assertEqual(friendly_stamp("2026-10-03T18:21:17+05:30"), "2026-10-03 18:21")
        self.assertEqual(friendly_stamp("not a time"), "not a time")
        self.assertEqual(friendly_stamp(""), "an unknown time")

    def test_new_journal_path_avoids_clashes(self):
        now = datetime(2026, 10, 3, 14, 3, 11)
        first = new_journal_path(self.dir, now)
        self.assertEqual(first.name, "journal-20261003-140311.jsonl")
        self.write(first.name, {"version": 1})
        self.assertEqual(new_journal_path(self.dir, now).name, "journal-20261003-140311-2.jsonl")

    def test_writer_round_trip_with_paths(self):
        writer = JournalWriter(self.dir / "journal-20260101-000000.jsonl", {"tool": "t", "where": Path("/x/y")})
        writer.open()
        writer.add_entry({"action": "deleted", "path": Path("/x/y/a.lua"), "size": 3})
        writer.finish()
        writer.discard_if_empty()
        self.assertTrue(writer.opened)
        journal = read_journal(writer.path, path_fields=("path",))
        self.assertEqual(journal.header["version"], JOURNAL_VERSION)
        self.assertEqual(journal.header["tool"], "t")
        self.assertTrue(journal.started)
        self.assertEqual(journal.entries, [{"action": "deleted", "path": Path("/x/y/a.lua"), "size": 3}])
        self.assertIsNotNone(journal.finished)
        self.assertIsNone(journal.undone)

    def test_paths_are_stored_in_windows_form_under_wsl(self):
        original = journal_mod.to_stored
        journal_mod.to_stored = lambda value: original(value, wsl=True)
        self.addCleanup(setattr, journal_mod, "to_stored", original)
        writer = JournalWriter(self.dir / "journal-20260101-000000.jsonl", {})
        writer.add_entry({"action": "deleted", "path": Path("/mnt/g/WoW/a.lua")})
        writer.close()
        self.assertIn("G:\\\\WoW\\\\a.lua", writer.path.read_text(encoding="utf-8"))

    def test_open_is_exclusive_and_header_only_journal_is_discarded(self):
        path = self.write("journal-20260101-000000.jsonl", {"version": 1})
        with self.assertRaises(FileExistsError):
            JournalWriter(path, {}).open()
        other = JournalWriter(self.dir / "journal-20260102-000000.jsonl", {})
        other.open()
        other.open()  # a second open is a no-op
        self.assertTrue(other.path.exists())
        other.discard_if_empty()
        self.assertFalse(other.path.exists())

    def test_open_fails_when_the_folder_cannot_be_made(self):
        self.dir.parent.mkdir(parents=True, exist_ok=True)
        self.dir.write_text("a file where the journal folder should go")
        with self.assertRaises(OSError):
            JournalWriter(self.dir / "journal-20260101-000000.jsonl", {}).open()

    def test_torn_lines_are_skipped(self):
        path = self.write("journal-20260101-000000.jsonl", {"version": 1}, {"action": "a", "path": "C:\\x"},
                          raw=b'{"action": "a", "path": "C:\\\\Jeux\\\\\xc3')
        self.assertEqual(len(read_journal(path).entries), 1)

    def test_list_journals_newest_first_and_ignores_other_files(self):
        self.write("journal-20260101-000000.jsonl", {"version": 1})
        self.write("journal-20260101-000000-2.jsonl", {"version": 1})
        self.write("journal-20260102-000000.jsonl", {"version": 1})
        self.write("notes.txt", {"version": 1})
        self.assertEqual([p.name for p in list_journals(self.dir)],
                         ["journal-20260102-000000.jsonl", "journal-20260101-000000-2.jsonl",
                          "journal-20260101-000000.jsonl"])
        self.assertEqual(list_journals(None), [])
        self.assertEqual(list_journals(self.dir / "missing"), [])

    def test_latest_undoable_skips_empty_and_never_reaches_past_an_undone_run(self):
        entry = {"action": "a"}
        old = self.write("journal-20260101-000000.jsonl", {"version": 1}, entry)
        self.assertEqual(latest_undoable(self.dir), old)
        newer = self.write("journal-20260102-000000.jsonl", {"version": 1}, entry)
        self.write("journal-20260103-000000.jsonl", {"version": 1})  # header only: not offered
        self.assertEqual(latest_undoable(self.dir), newer)
        mark_undone(newer, 1, 0)
        self.assertIsNotNone(read_journal(newer).undone)
        self.assertIsNone(latest_undoable(self.dir))  # the older run is never offered after an undo

    def test_mark_undone_after_a_torn_last_line(self):
        path = self.write("journal-20260101-000000.jsonl", {"version": 1}, {"action": "a"}, raw=b'{"fini')
        mark_undone(path, 1, 0)
        self.assertIsNotNone(read_journal(path).undone)

    def test_pruning_keeps_the_newest_and_never_other_files(self):
        for i in range(5):
            self.write(f"journal-2020010{i}-000000.jsonl", {"version": 1})
        self.write("keep-me.txt", {})
        removed = prune_journals(self.dir, 2)
        self.assertEqual(len(removed), 3)
        self.assertEqual([p.name for p in list_journals(self.dir)],
                         ["journal-20200104-000000.jsonl", "journal-20200103-000000.jsonl"])
        self.assertTrue((self.dir / "keep-me.txt").exists())
        self.assertEqual(len(prune_journals(self.dir, 0)), 1)  # at least one is always kept
        self.assertEqual(prune_journals(None, 1), [])


if __name__ == "__main__":
    unittest.main()
