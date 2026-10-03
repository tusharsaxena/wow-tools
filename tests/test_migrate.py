import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.migrate import ToolRename, merge_folder, migrate_tool_config, tool_folder_pairs
from wowtools.tools import RENAMED_TOOLS, TOOLS

RENAME = ToolRename("old-tool", "new-tool", "old_tool", "new_tool")


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class MergeFolderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.old, self.new = self.tmp / "old", self.tmp / "new"

    def test_nothing_to_do_without_the_old_folder(self):
        self.assertIsNone(merge_folder(self.old, self.new))
        write(self.old)  # a file, not a folder
        self.assertIsNone(merge_folder(self.old, self.new))
        self.assertFalse(self.new.exists())

    def test_only_old_is_renamed(self):
        write(self.old / "journal" / "a.jsonl", "a")
        result = merge_folder(self.old, self.new)
        self.assertTrue(result.renamed and result.old_removed and result.changed)
        self.assertFalse(self.old.exists())
        self.assertEqual((self.new / "journal" / "a.jsonl").read_text(encoding="utf-8"), "a")

    def test_rename_creates_missing_parents(self):
        write(self.old / "a")
        new = self.tmp / "deep" / "er" / "new"
        self.assertTrue(merge_folder(self.old, new).renamed)
        self.assertTrue((new / "a").is_file())

    def test_both_exist_without_clashes_merges_recursively_and_removes_old(self):
        write(self.old / "journal" / "a.jsonl", "a")
        write(self.old / "top.txt", "t")
        write(self.new / "journal" / "b.jsonl", "b")
        result = merge_folder(self.old, self.new)
        self.assertFalse(result.renamed)
        self.assertEqual(sorted(result.moved), ["journal/a.jsonl", "top.txt"])
        self.assertEqual(result.clashes, [])
        self.assertTrue(result.old_removed)
        self.assertFalse(self.old.exists())
        self.assertEqual(sorted(p.name for p in (self.new / "journal").iterdir()), ["a.jsonl", "b.jsonl"])

    def test_clashes_are_left_and_never_overwritten(self):
        write(self.old / "journal" / "same.jsonl", "old")
        write(self.old / "journal" / "only-old.jsonl", "o")
        write(self.new / "journal" / "same.jsonl", "new")
        result = merge_folder(self.old, self.new)
        self.assertEqual(result.moved, ["journal/only-old.jsonl"])
        self.assertEqual(result.clashes, ["journal/same.jsonl"])
        self.assertFalse(result.old_removed)
        self.assertEqual((self.new / "journal" / "same.jsonl").read_text(encoding="utf-8"), "new")
        self.assertEqual((self.old / "journal" / "same.jsonl").read_text(encoding="utf-8"), "old")
        self.assertFalse((self.old / "journal" / "only-old.jsonl").exists())

    def test_file_against_folder_is_a_clash(self):
        write(self.old / "journal", "a file")
        (self.new / "journal").mkdir(parents=True)
        result = merge_folder(self.old, self.new)
        self.assertEqual(result.clashes, ["journal"])
        self.assertTrue((self.old / "journal").is_file())

    def test_new_name_taken_by_a_file_leaves_old_alone(self):
        write(self.old / "a")
        write(self.new, "file")
        result = merge_folder(self.old, self.new)
        self.assertEqual((result.clashes, result.changed), (["."], False))
        self.assertTrue((self.old / "a").is_file())

    def test_failed_move_is_recorded_and_others_carry_on(self):
        write(self.old / "a")
        write(self.old / "b")
        self.new.mkdir()
        real_rename = os.rename

        def flaky(src, dst):
            if Path(src).name == "a":
                raise PermissionError("locked")
            real_rename(src, dst)

        with unittest.mock.patch("wowtools.core.migrate.os.rename", flaky):
            result = merge_folder(self.old, self.new)
        self.assertEqual(result.moved, ["b"])
        self.assertEqual(len(result.errors), 1)
        self.assertTrue(result.errors[0].startswith("a: "))
        self.assertTrue((self.old / "a").is_file())


class MigrateToolConfigTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.old = self.dir / "old-tool.cfg"
        self.new = self.dir / "new-tool.cfg"

    def test_nothing_to_do_without_the_old_file(self):
        self.assertIsNone(migrate_tool_config(self.dir, RENAME))
        self.assertFalse(self.new.exists())

    def test_only_old_is_renamed_with_its_section(self):
        write(self.old, "[old_tool]\na = 1\nb = C:\\x\n\n[other]\nk = v\n")
        result = migrate_tool_config(self.dir, RENAME)
        self.assertFalse(result.merged)
        self.assertIsNone(result.kept_old)
        self.assertFalse(self.old.exists())
        cfg = Config(self.new).load()
        self.assertEqual((cfg.get("new_tool", "a"), cfg.get("new_tool", "b"), cfg.get("other", "k")),
                         ("1", "C:\\x", "v"))
        self.assertIsNone(cfg.get("old_tool", "a"))
        self.assertEqual(sorted(result.added), ["new_tool.a", "new_tool.b", "other.k"])

    def test_both_exist_adds_missing_keys_and_keeps_new_values(self):
        write(self.old, "[old_tool]\na = old\nb = 2\n")
        write(self.new, "[new_tool]\na = new\n")
        result = migrate_tool_config(self.dir, RENAME)
        self.assertTrue(result.merged)
        self.assertEqual(result.added, ["new_tool.b"])
        cfg = Config(self.new).load()
        self.assertEqual((cfg.get("new_tool", "a"), cfg.get("new_tool", "b")), ("new", "2"))
        # a = old differs from the new file: the old file is kept so nothing is lost.
        self.assertFalse(self.old.exists())
        self.assertEqual(result.kept_old, self.dir / "old-tool.cfg.migrated")
        self.assertIn("a = old", result.kept_old.read_text(encoding="utf-8"))

    def test_both_exist_with_nothing_different_removes_old(self):
        write(self.old, "[old_tool]\na = 1\n")
        write(self.new, "[new_tool]\na = 1\nz = 9\n")
        before = self.new.read_text(encoding="utf-8")
        result = migrate_tool_config(self.dir, RENAME)
        self.assertEqual((result.added, result.kept_old), ([], None))
        self.assertFalse(self.old.exists())
        self.assertEqual(self.new.read_text(encoding="utf-8"), before)

    def test_kept_old_never_overwrites_an_earlier_one(self):
        write(self.dir / "old-tool.cfg.migrated", "earlier")
        write(self.old, "[old_tool]\na = old\n")
        write(self.new, "[new_tool]\na = new\n")
        result = migrate_tool_config(self.dir, RENAME)
        self.assertEqual(result.kept_old, self.dir / "old-tool.cfg.migrated-2")
        self.assertEqual((self.dir / "old-tool.cfg.migrated").read_text(encoding="utf-8"), "earlier")

    def test_unreadable_old_file_raises_and_changes_nothing(self):
        from wowtools.core.config import ConfigError

        write(self.old, "no section header\n")
        with self.assertRaises(ConfigError):
            migrate_tool_config(self.dir, RENAME)
        self.assertTrue(self.old.exists())
        self.assertFalse(self.new.exists())


class RenameTableTest(unittest.TestCase):
    def test_every_rename_points_at_a_registered_tool(self):
        for rename in RENAMED_TOOLS:
            self.assertIn(rename.new, TOOLS)
            self.assertEqual(TOOLS[rename.new].section, rename.new_section)
            self.assertNotIn(rename.old, TOOLS)

    def test_screenshots_became_screenshot_organizer(self):
        self.assertIn(ToolRename("screenshots", "screenshot-organizer", "screenshots", "screenshot_organizer"),
                      RENAMED_TOOLS)

    def test_folder_pairs(self):
        logs, wow = Path("/l"), Path("/w")
        self.assertEqual(tool_folder_pairs(RENAME, logs, wow),
                         [(logs / "old-tool", logs / "new-tool"),
                          (wow / "wow-tools" / "old-tool", wow / "wow-tools" / "new-tool")])
        self.assertEqual(tool_folder_pairs(RENAME, None, None), [])


if __name__ == "__main__":
    unittest.main()
