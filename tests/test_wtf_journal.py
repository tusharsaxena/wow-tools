import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.journal import list_journals
from wowtools.tools.wtf_cleaner import journal as journal_mod
from wowtools.tools.wtf_cleaner.cleaner import CleanError
from wowtools.tools.wtf_cleaner.journal import (A_DELETED, clean_journal_dir, latest_undoable, prune_journals,
                                                read_journal)
from wowtools.tools.wtf_cleaner.multi import execute_flavors, scan_flavors
from wowtools.tools.wtf_cleaner.rules import Criteria, evaluate
from wowtools.tools.wtf_cleaner.settings import DEFAULT_KEEP_JOURNALS, SECTION, load_settings

from wowtools.core.config import Config


class CleanJournalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.era_sv = self.root / "_classic_era_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        (self.era_sv / "Gone.lua").write_text("x")  # something to clean in Classic Era too
        self.retail_sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.install = WowInstall(self.root)
        self.backup_dir = self.tmp / "bk"
        self.journals = clean_journal_dir(self.root)

    def plan(self, flavors=None):
        scans = scan_flavors(flavors or self.install.flavors())
        return [(s.flavor, evaluate(s.result, Criteria(), log=False).items) for s in scans if s.result]

    def clean(self, plan=None, **kw):
        kw.setdefault("backup", True)
        return execute_flavors(plan or self.plan(), dry_run=kw.pop("dry_run", False), backup_dir=self.backup_dir,
                               journal_dir=self.journals, **kw)

    def test_journal_dir_is_the_suite_standard(self):
        self.assertEqual(self.journals, self.root / "wow-tools" / "wtf-cleaner" / "journal")

    def test_single_flavor_clean_writes_one_journal_with_an_entry_per_delete(self):
        result = self.clean(self.plan([self.install.flavor("retail")]))
        self.assertEqual(len(result.deleted), 8)
        self.assertEqual(list_journals(self.journals), [result.journal_path])
        journal = read_journal(result.journal_path)
        self.assertEqual(journal.header["flavors"], ["_retail_"])
        self.assertEqual(journal.header["tool"], "wtf-cleaner")
        self.assertIn("suite_version", journal.header)
        self.assertEqual(journal.header["backup_dir"], self.backup_dir)
        self.assertIsNotNone(journal.finished)
        self.assertEqual(len(journal.entries), 8)
        run = result.runs[0].result
        deleted = {o.path: o for o in run.deleted}
        for entry in journal.entries:
            self.assertEqual(entry["action"], A_DELETED)
            self.assertEqual(entry["flavor"], "_retail_")
            self.assertIn(entry["path"], deleted)
            self.assertEqual(entry["rel"], entry["path"].relative_to(self.root / "_retail_").as_posix())
            self.assertTrue(entry["rel"].startswith("WTF/Account/"))
            self.assertEqual(entry["size"], deleted[entry["path"]].size)
            self.assertIsInstance(entry["mtime"], float)
            self.assertEqual(entry["zip"], run.backup_path)
            self.assertEqual(entry["snapshot"], run.snapshot_path)
        self.assertEqual(latest_undoable(self.journals), result.journal_path)

    def test_all_flavors_clean_writes_one_journal(self):
        result = self.clean()
        self.assertEqual(len(result.deleted), 9)
        self.assertEqual(len(list_journals(self.journals)), 1)
        journal = read_journal(result.journal_path)
        self.assertEqual(journal.header["flavors"], ["_classic_era_", "_retail_"])
        self.assertEqual(sorted({e["flavor"] for e in journal.entries}), ["_classic_era_", "_retail_"])
        self.assertEqual(len(journal.entries), 9)
        era = next(e for e in journal.entries if e["flavor"] == "_classic_era_")
        self.assertEqual(era["rel"], "WTF/Account/ACCT1/SavedVariables/Gone.lua")
        self.assertIn("backup-classic_era-", era["snapshot"].name)

    def test_dry_run_writes_no_journal(self):
        result = self.clean(dry_run=True)
        self.assertIsNone(result.journal_path)
        self.assertFalse(self.journals.exists())

    def test_clean_without_backups_records_no_zip(self):
        result = self.clean(backup=False)
        entries = read_journal(result.journal_path).entries
        self.assertTrue(entries)
        self.assertTrue(all(e["zip"] is None for e in entries))
        self.assertTrue(all(e["snapshot"] is not None for e in entries))

    def test_unwritable_journal_deletes_nothing(self):
        self.journals.parent.mkdir(parents=True)
        self.journals.write_text("a file where the journal folder should go")
        result = self.clean()
        self.assertEqual(result.deleted, [])
        self.assertIsInstance(result.stopped.error, CleanError)
        self.assertIn("journal", str(result.stopped.error))
        self.assertIsNone(result.journal_path)
        self.assertTrue((self.era_sv / "Gone.lua").exists())
        self.assertTrue((self.retail_sv / "Uninstalled.lua").exists())
        self.assertFalse(list(self.backup_dir.glob("backup/*.zip")))  # stopped before the WTF backup

    def test_journal_write_failure_mid_clean_puts_that_flavors_files_back(self):
        real = journal_mod.CleanJournal.add_deleted
        calls = []

        def flaky(writer, *a, **k):
            calls.append(1)
            if len(calls) == 3:
                raise OSError(28, "No space left on device")
            return real(writer, *a, **k)

        with unittest.mock.patch.object(journal_mod.CleanJournal, "add_deleted", flaky):
            result = self.clean()
        # Classic Era (1 file) finished and is journaled; Retail stopped and its deleted files were restored.
        self.assertEqual([r.status for r in result.runs], ["done", "stopped"])
        self.assertTrue((self.retail_sv / "Uninstalled.lua").exists())
        self.assertFalse((self.era_sv / "Gone.lua").exists())
        # Retail's journaled delete was rolled back: only Classic Era's entry is left to undo.
        entries = read_journal(result.journal_path).entries
        self.assertEqual([e["flavor"] for e in entries], ["_classic_era_"])
        self.assertIn('"rolled_back"', result.journal_path.read_text(encoding="utf-8"))

    def _second_clean_rolled_back(self, flavors):
        """A first clean of Retail, then a clean of `flavors` whose 3rd delete hits an unexpected error."""
        (self.retail_sv / "Another.lua").write_text("x")
        first_plan = self.plan([self.install.flavor("retail")])
        keep = next(item for item in first_plan[0][1] if any(sv.path.name == "Another.lua" for sv in item.files))
        first = self.clean([(first_plan[0][0], [i for i in first_plan[0][1] if i is not keep])])
        self.assertEqual(latest_undoable(self.journals), first.journal_path)
        real = Path.unlink
        calls = []

        def flaky(path, *a, **k):
            if path.parent == self.retail_sv:
                calls.append(path)
                if len(calls) == 1:
                    return real(path, *a, **k)
                raise RuntimeError("boom")
            return real(path, *a, **k)

        (self.retail_sv / "Third.lua").write_text("x")
        with unittest.mock.patch.object(Path, "unlink", flaky):
            second = self.clean(self.plan(flavors))
        self.assertEqual(second.stopped.flavor.folder, "_retail_")
        self.assertTrue((self.retail_sv / "Another.lua").exists())
        self.assertTrue((self.retail_sv / "Third.lua").exists())
        return first, second

    def test_a_rolled_back_clean_does_not_hide_the_clean_before_it(self):
        first, second = self._second_clean_rolled_back([self.install.flavor("retail")])
        self.assertIsNone(second.journal_path)  # every delete was put back: no journal kept
        self.assertEqual(list_journals(self.journals), [first.journal_path])
        self.assertEqual(latest_undoable(self.journals), first.journal_path)

    def test_a_partly_rolled_back_clean_offers_only_what_stayed_deleted(self):
        first, second = self._second_clean_rolled_back(self.install.flavors())
        self.assertEqual(latest_undoable(self.journals), second.journal_path)
        entries = read_journal(second.journal_path).entries
        self.assertEqual([e["rel"] for e in entries], ["WTF/Account/ACCT1/SavedVariables/Gone.lua"])

    def test_nothing_deleted_leaves_no_journal(self):
        plan = self.plan([self.install.flavor("retail")])
        for item in plan[0][1]:
            for sv in item.files:
                sv.path.write_text("changed since the scan, so it is skipped")
        result = self.clean(plan)
        self.assertEqual(result.deleted, [])
        self.assertIsNone(result.journal_path)
        self.assertEqual(list_journals(self.journals), [])

    def test_pruning_keeps_the_newest_journals(self):
        self.journals.mkdir(parents=True)
        for i in range(4):
            (self.journals / f"journal-2020010{i}-000000.jsonl").write_text('{"version": 1}\n')
        with capture_events() as records:
            result = self.clean(keep_journals=2)
        names = [p.name for p in list_journals(self.journals)]
        self.assertEqual(names, [result.journal_path.name, "journal-20200103-000000.jsonl"])
        self.assertEqual(len(result.journals_pruned), 3)
        self.assertIn("clean.journal_pruned", [r["event"] for r in records])
        self.assertEqual(prune_journals(self.journals, 5), [])

    def test_keep_journals_setting(self):
        cfg = Config(self.tmp / "wtf-cleaner.cfg")
        self.assertEqual(load_settings(cfg).keep_journals, DEFAULT_KEEP_JOURNALS)
        self.assertEqual(DEFAULT_KEEP_JOURNALS, 10)
        cfg.set(SECTION, "keep_journals", "0", log=False)
        self.assertEqual(load_settings(cfg).keep_journals, 1)
        cfg.set(SECTION, "keep_journals", "4", log=False)
        self.assertEqual(load_settings(cfg).keep_journals, 4)


if __name__ == "__main__":
    unittest.main()
