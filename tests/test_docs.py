import importlib.util
import unittest

from wowtools.core.bootstrap import REPO_ROOT


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

    def test_readme_mentions_every_tool_and_cli_flag(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for needle in ("wtf-cleaner", "--dry-run", "--clean", "--no-backup", "--criteria", "--max-age",
                       "--json", "python -m wowtools update", "stray_copies", "Restoring a backup",
                       "--account", "wtf-snapshot", "Dry run"):
            self.assertIn(needle, readme)
