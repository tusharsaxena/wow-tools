"""journal: the Ace3 Profile Manager's run journals over core/journal.py."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wowtools.tools.ace_profiles import journal as j


class JournalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "journal"

    def write(self, rels, rolled=()):
        self.count = getattr(self, "count", 0) + 1
        writer = j.ProfileJournal(self.folder / f"journal-20261004-12000{self.count}.jsonl", {"kind": "apply"})
        for rel in rels:
            writer.add_edited(flavor="_retail_", path=Path("/w") / rel, rel=rel, zip_path=Path("/z/edited-a.zip"),
                              sha_before="a", sha_after="b", size_before=1, size_after=2, changes=["x"])
        if rolled:
            writer.add_rolled_back(flavor="_retail_", rels=list(rolled))
        writer.finish()
        writer.discard_if_empty()
        return writer.path

    def test_round_trip(self):
        path = self.write(["WTF/Account/A/SavedVariables/K.lua"])
        journal = j.read_profile_journal(path)
        self.assertEqual(len(journal.entries), 1)
        entry = journal.entries[0]
        self.assertEqual((entry["action"], entry["sha_before"], entry["sha_after"]), ("edited", "a", "b"))
        self.assertIsInstance(entry["zip"], Path)

    def test_rolled_back_entries_are_dropped_and_not_undoable(self):
        path = self.write(["WTF/Account/A/SavedVariables/K.lua"], rolled=["WTF/Account/A/SavedVariables/K.lua"])
        self.assertFalse(path.exists())  # every edit rolled back: nothing to keep
        self.assertIsNone(j.latest_undoable(self.folder))

    def test_referenced_zips(self):
        self.write(["WTF/Account/A/SavedVariables/K.lua"])
        self.assertEqual(j.referenced_zips(self.folder), {"edited-a.zip"})

    def test_record_recovered_marks_only_that_zips_entries(self):
        rel_a, rel_b = "WTF/Account/A/SavedVariables/K.lua", "WTF/Account/A/SavedVariables/L.lua"
        path = self.write([rel_a, rel_b])
        self.assertEqual(j.record_recovered(self.folder, "_retail_", "edited-other.zip", [rel_a]), [])
        self.assertEqual(j.record_recovered(self.folder, "_classic_", "edited-a.zip", [rel_a]), [])
        self.assertEqual(j.record_recovered(self.folder, "_retail_", "edited-a.zip", [rel_a]), [path])
        self.assertEqual([e["rel"] for e in j.read_profile_journal(path).entries], [rel_b])
        j.record_recovered(self.folder, "_retail_", "edited-a.zip", [rel_b])
        self.assertIsNone(j.latest_undoable(self.folder))
