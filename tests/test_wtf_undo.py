from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.journal import clean_journal_dir, latest_undoable, read_journal
from wowtools.tools.wtf_cleaner.multi import execute_flavors, scan_flavors
from wowtools.tools.wtf_cleaner.rules import Criteria, evaluate
from wowtools.tools.wtf_cleaner.undo import undo_clean


def contents(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


class UndoCleanTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.era_sv = self.root / "_classic_era_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        (self.era_sv / "Gone.lua").write_text("x")
        self.retail_sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.install = WowInstall(self.root)
        self.backup_dir = self.tmp / "bk"
        self.journals = clean_journal_dir(self.root)
        self.before = {f: contents(self.root / f / "WTF") for f in ("_classic_era_", "_retail_")}

    def clean(self, backup=True):
        scans = scan_flavors(self.install.flavors())
        plan = [(s.flavor, evaluate(s.result, Criteria(), log=False).items) for s in scans if s.result]
        result = execute_flavors(plan, dry_run=False, backup=backup, backup_dir=self.backup_dir,
                                 journal_dir=self.journals)
        self.assertEqual(len(result.deleted), 9)
        return result

    def assert_restored(self):
        for folder, before in self.before.items():
            self.assertEqual(contents(self.root / folder / "WTF"), before, folder)

    def test_undo_restores_from_the_cleaned_files_zip(self):
        result = self.clean()
        with capture_events() as records:
            back = undo_clean(result.journal_path, wow_root=self.root)
        self.assertEqual(len(back.restored), 9)
        self.assertTrue(all(o.source == "zip" for o in back.restored))
        self.assert_restored()
        entry = read_journal(result.journal_path).entries[0]
        self.assertAlmostEqual(os.stat(entry["path"]).st_mtime, entry["mtime"], places=3)  # the file's own time is put back
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "clean.undo_started")
        self.assertEqual(names.count("clean.undo_restored"), 9)
        self.assertEqual(names[-1], "clean.undo_completed")
        self.assertIsNotNone(read_journal(result.journal_path).undone)
        self.assertIsNone(latest_undoable(self.journals))

    def test_undo_restores_newest_entry_first(self):
        result = self.clean()
        order = []
        undo_clean(result.journal_path, wow_root=self.root,
                   progress=lambda stage, i, n, detail: detail and order.append(detail))
        rels = [e["rel"] for e in read_journal(result.journal_path).entries]
        self.assertEqual(order, list(reversed(rels)))

    def test_undo_falls_back_to_the_wtf_backup_when_backups_were_off(self):
        result = self.clean(backup=False)
        self.assertFalse(list(self.backup_dir.glob("cleaned/*.zip")))
        back = undo_clean(result.journal_path, wow_root=self.root)
        self.assertEqual(len(back.restored), 9)
        self.assertTrue(all(o.source == "backup" for o in back.restored))
        self.assert_restored()

    def test_undo_falls_back_to_the_wtf_backup_when_the_zip_is_gone(self):
        result = self.clean()
        for zip_path in self.backup_dir.glob("cleaned/*.zip"):
            zip_path.unlink()
        back = undo_clean(result.journal_path, wow_root=self.root)
        self.assertEqual(len(back.restored), 9)
        self.assert_restored()

    def test_undo_skips_a_file_that_came_back(self):
        result = self.clean()
        (self.era_sv / "Gone.lua").write_text("WoW wrote a new one")
        back = undo_clean(result.journal_path, wow_root=self.root)
        self.assertEqual(len(back.restored), 8)
        self.assertEqual([o.rel for o in back.skipped], ["WTF/Account/ACCT1/SavedVariables/Gone.lua"])
        self.assertIn("a file is back at this path", back.skipped[0].detail)
        self.assertEqual((self.era_sv / "Gone.lua").read_text(), "WoW wrote a new one")  # never overwritten

    def test_undo_fails_a_file_no_zip_holds(self):
        result = self.clean(backup=False)
        for zip_path in self.backup_dir.glob("backup/*.zip"):
            zip_path.unlink()
        back = undo_clean(result.journal_path, wow_root=self.root)
        self.assertEqual(len(back.failed), 9)
        self.assertFalse((self.era_sv / "Gone.lua").exists())
        # Nothing came back: the journal stays undoable, so the user can retry once the source is back.
        self.assertFalse(back.marked_undone)
        self.assertIsNone(read_journal(result.journal_path).undone)
        self.assertEqual(latest_undoable(self.journals), result.journal_path)

    def test_undo_can_be_retried_after_the_backup_drive_comes_back(self):
        result = self.clean()
        moved = self.tmp / "unplugged"
        self.backup_dir.rename(moved)
        first = undo_clean(result.journal_path, wow_root=self.root)
        self.assertEqual((len(first.restored), len(first.failed)), (0, 9))
        moved.rename(self.backup_dir)
        self.assertEqual(latest_undoable(self.journals), result.journal_path)
        second = undo_clean(result.journal_path, wow_root=self.root)
        self.assertEqual(len(second.restored), 9)
        self.assertTrue(second.marked_undone)
        self.assert_restored()
        self.assertIsNone(latest_undoable(self.journals))

    def test_undo_fails_on_a_size_mismatch_and_leaves_nothing_behind(self):
        result = self.clean(backup=False)
        path = result.journal_path
        lines = path.read_text(encoding="utf-8").splitlines()
        entries = [json.loads(line) for line in lines]
        for record in entries:
            if record.get("rel", "").endswith("Gone.lua"):
                record["size"] = 999
        path.write_text("".join(json.dumps(r) + "\n" for r in entries), encoding="utf-8")
        back = undo_clean(path, wow_root=self.root)
        self.assertEqual([o.rel for o in back.failed], ["WTF/Account/ACCT1/SavedVariables/Gone.lua"])
        self.assertIn("size", back.failed[0].detail)
        self.assertFalse((self.era_sv / "Gone.lua").exists())

    def test_undo_refuses_entries_outside_the_wtf_folder(self):
        result = self.clean()
        path = result.journal_path
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        evil = dict(next(r for r in records if "rel" in r))
        bad_rels = ["Interface/AddOns/Evil.lua", "WTF/../Interface/Evil.lua", "/etc/Evil.lua", "WTF"]
        extra = [{**evil, "rel": rel} for rel in bad_rels] + [{**evil, "flavor": ".."}, {**evil, "flavor": "a/b"}]
        path.write_text("".join(json.dumps(r) + "\n" for r in records + extra), encoding="utf-8")
        back = undo_clean(path, wow_root=self.root)
        self.assertEqual(len(back.skipped), 6)
        self.assertTrue(all("outside" in o.detail for o in back.skipped))
        self.assertFalse((self.root / "_retail_" / "Interface" / "AddOns" / "Evil.lua").exists())
        self.assertFalse((self.root / "_retail_" / "Interface" / "Evil.lua").exists())
        self.assertEqual(len(back.restored), 9)

    def test_only_the_newest_journal_is_undoable_and_not_after_undo(self):
        first = self.clean()
        (self.retail_sv / "Another.lua").write_text("new")
        scans = scan_flavors([self.install.flavor("retail")])
        plan = [(s.flavor, evaluate(s.result, Criteria(), log=False).items) for s in scans]
        second = execute_flavors(plan, dry_run=False, backup=True, backup_dir=self.backup_dir,
                                 journal_dir=self.journals)
        self.assertNotEqual(first.journal_path, second.journal_path)
        self.assertEqual(latest_undoable(self.journals), second.journal_path)
        undo_clean(second.journal_path, wow_root=self.root)
        self.assertTrue((self.retail_sv / "Another.lua").exists())
        self.assertIsNone(latest_undoable(self.journals))
        self.assertFalse((self.retail_sv / "Uninstalled.lua").exists())  # the first clean stays done

    def test_undo_never_touches_the_zips(self):
        result = self.clean()
        zips = {p: p.read_bytes() for p in self.backup_dir.rglob("*.zip")}
        undo_clean(result.journal_path, wow_root=self.root)
        self.assertEqual({p: p.read_bytes() for p in self.backup_dir.rglob("*.zip")}, zips)
        for p in zips:
            with zipfile.ZipFile(p) as zf:
                self.assertIsNone(zf.testzip())


if __name__ == "__main__":
    unittest.main()
