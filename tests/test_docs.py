import importlib.util
import unittest

from wowtools.core.bootstrap import REPO_ROOT
from wowtools.tools import TOOLS


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_event_docs", REPO_ROOT / "scripts" / "gen_event_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocsTest(unittest.TestCase):
    def test_event_reference_is_up_to_date(self):
        generated = load_generator().render()
        on_disk = (REPO_ROOT / "docs" / "events.md").read_text(encoding="utf-8")
        self.assertEqual(on_disk, generated, "Run: python3 scripts/gen_event_docs.py")

    def test_every_event_is_documented(self):
        text = (REPO_ROOT / "docs" / "events.md").read_text(encoding="utf-8")
        for name in ("session.start", "config.changed", "sv.deleted", "backup.created", "update.available"):
            self.assertIn(f"`{name}`", text)

    def test_readme_covers_the_entry_point_tools_and_safety(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for tool in TOOLS.values():
            self.assertIn(tool.title, readme)
        for needle in ("wow-tools.cmd", "./wow-tools.sh", "wow-tools update", "config\\wtf-cleaner.cfg",
                       "wow-tools.lock", "Override and continue", "stray_copies", "Restoring a backup",
                       "backup\\backup-<YYYYMMDD-HHMMSS>.zip", "cleaned\\cleaned-<account>-", "keep_backups", "Dry run"):
            self.assertIn(needle, readme)
        for gone in ("wtf-cleaner.cmd", "wtf-cleaner.sh", "--flavor", "python -m wowtools"):
            self.assertNotIn(gone, readme)
