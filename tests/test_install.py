import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.install import Account, Flavor, WowInstall, detect_installs, validate_output_dir


class InstallTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.install = WowInstall(self.root)

    def test_discovers_flavor_folders_only(self):
        self.assertEqual([f.folder for f in self.install.flavors()],
                         ["_anniversary_", "_classic_era_", "_retail_"])

    def test_any_flavor_folder_counts_even_when_empty(self):
        (self.root / "_classic_beta_").mkdir()  # installed but never launched: no WTF or Interface yet
        self.assertIn("_classic_beta_", [f.folder for f in self.install.flavors()])

    def test_display_and_short_names(self):
        self.assertEqual(Flavor("_classic_era_", self.root).display_name, "Classic Era")
        self.assertEqual(Flavor("_retail_", self.root).display_name, "Retail")
        self.assertEqual(Flavor("_weird_new_", self.root).display_name, "Weird New")
        self.assertEqual(Flavor("_classic_era_", self.root).short_name, "classic_era")

    def test_flavor_lookup_accepts_short_and_folder_names(self):
        self.assertEqual(self.install.flavor("retail").folder, "_retail_")
        self.assertEqual(self.install.flavor("_Classic_Era_").folder, "_classic_era_")
        self.assertIsNone(self.install.flavor("wotlk"))

    def test_accounts_and_characters(self):
        retail = self.install.flavor("retail")
        accounts = retail.accounts()
        self.assertEqual([a.name for a in accounts], ["ACCT1", "ACCT2"])
        characters = [c for a in accounts for c in a.characters()]
        self.assertEqual([c.label for c in characters], ["Realm1/CharA", "Realm2/Chârb"])
        self.assertTrue(characters[0].addons_txt.is_file())
        self.assertEqual(characters[0].saved_variables_dir, characters[0].path / "SavedVariables")
        self.assertEqual(accounts[0].saved_variables_dir, accounts[0].path / "SavedVariables")

    def test_is_valid(self):
        self.assertTrue(self.install.is_valid())
        self.assertFalse(WowInstall(self.root / "nope").is_valid())
        self.assertFalse(WowInstall(self.root / "_retail_").is_valid())

    def test_missing_folder_is_silent(self):
        errors = []
        self.assertEqual(Account("X", self.root / "missing").characters(on_error=lambda p, e: errors.append(p)), [])
        self.assertEqual(errors, [])

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs POSIX permissions")
    def test_unreadable_folder_is_reported(self):
        locked = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "Realm1"
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        errors = []
        account = self.install.flavor("retail").accounts()[0]
        self.assertEqual(account.characters(on_error=lambda p, e: errors.append(p)), [])
        self.assertEqual(errors, [locked])

    def test_detect_installs(self):
        self.assertEqual(detect_installs([self.tmp]), [self.root])
        self.assertEqual(detect_installs([self.tmp / "empty"]), [])


class ValidateOutputDirTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.install = WowInstall(self.root)

    def test_allowed(self):
        for path in (None, self.root / "wow-tools" / "wtf-cleaner", self.tmp / "elsewhere"):
            with self.subTest(path=path):
                self.assertIsNone(validate_output_dir(path, self.install))

    def test_relative_path_needs_a_full_path(self):
        self.assertIn("full path", validate_output_dir(Path("backups"), self.install) or "")

    def test_wow_folder_and_game_folders_are_refused(self):
        retail = self.root / "_retail_"
        for path in (self.root, retail / "WTF", retail / "WTF" / "x", retail / "Interface" / "AddOns" / "x",
                     retail / "Screenshots" / "x", self.root / "_classic_era_" / "wtf" / "x"):
            with self.subTest(path=path):
                self.assertIsNotNone(validate_output_dir(path, self.install))

    def test_message_names_the_folder(self):
        problem = validate_output_dir(self.root / "_retail_" / "WTF" / "x", self.install, what="backup folder")
        self.assertIn("backup folder", problem)
        self.assertIn("_retail_\\WTF", problem)
