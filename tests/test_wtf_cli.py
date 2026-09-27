import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree, make_config
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import Config
from wowtools.tools.wtf_cleaner.cli import main


class CliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.cfg = make_config(self.tmp, self.root)
        self.sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.backup_dir = self.tmp / "bk"

    def cli(self, *argv, answer="n", cfg=None, wow_running=()):
        out, err = io.StringIO(), io.StringIO()

        def ask(prompt):
            if answer is None:
                raise AssertionError("must not prompt")
            return answer

        code = main(list(argv), cfg=cfg or self.cfg, stdout=out, stderr=err, input_fn=ask,
                    wow_check=lambda: list(wow_running))
        return code, out.getvalue(), err.getvalue()

    def test_proposal_text_is_read_only(self):
        code, out, _ = self.cli("--flavor", "retail", answer=None)
        self.assertEqual(code, 0)
        self.assertIn("Total: 6 items, 8 files", out)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    def test_last_flavor_is_used_with_json(self):
        code, out, _ = self.cli("--json", answer=None)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["flavor"], "_retail_")

    def test_clean_prompt_declined(self):
        code, out, _ = self.cli("--flavor", "retail", "--clean", answer="n")
        self.assertEqual(code, 0)
        self.assertIn("Aborted", out)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    def test_clean_with_yes(self):
        code, out, _ = self.cli("--flavor", "retail", "--clean", "--yes", "--backup-dir", str(self.backup_dir),
                                answer=None)
        self.assertEqual(code, 0)
        self.assertFalse((self.sv / "Uninstalled.lua").exists())
        self.assertTrue((self.sv / "Auctionator.lua").exists())
        self.assertEqual(len(list(self.backup_dir.glob("wtf-cleaner_retail_*.zip"))), 1)
        self.assertIn("Deleted: 8 files", out)

    def test_dry_run_clean_needs_no_prompt(self):
        code, out, _ = self.cli("--flavor", "retail", "--clean", "--dry-run", answer=None)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    def test_no_backup_requires_yes(self):
        code, _, err = self.cli("--flavor", "retail", "--clean", "--no-backup")
        self.assertEqual(code, 1)
        self.assertIn("--no-backup", err)

    def test_json_clean_requires_yes_or_dry_run(self):
        code, _, _ = self.cli("--flavor", "retail", "--clean", "--json", answer=None)
        self.assertEqual(code, 1)

    def test_criteria_override(self):
        code, out, _ = self.cli("--flavor", "retail", "--json", "--criteria", "not_installed", answer=None)
        self.assertEqual(code, 0)
        self.assertEqual({i["addon"] for i in json.loads(out)["items"]}, {"Uninstalled"})

    def test_bad_criteria_and_max_age(self):
        code, _, err = self.cli("--flavor", "retail", "--criteria", "bogus")
        self.assertEqual(code, 1)
        self.assertIn("unknown criteria", err)
        code, _, err = self.cli("--flavor", "retail", "--max-age", "0")
        self.assertEqual(code, 1)

    def test_unknown_flavor(self):
        code, _, err = self.cli("--flavor", "wotlk")
        self.assertEqual(code, 1)
        self.assertIn("anniversary, classic_era, retail", err)

    def test_missing_config(self):
        code, _, err = self.cli("--flavor", "retail", cfg=Config(self.tmp / "none.cfg"))
        self.assertEqual(code, 1)
        self.assertIn("Run the TUI once", err)

    def test_wow_path_override_without_config(self):
        code, out, _ = self.cli("--flavor", "retail", "--json", "--wow-path", str(self.root),
                                cfg=Config(self.tmp / "none.cfg"), answer=None)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["totals"]["items"], 6)

    def test_scan_error_exit_code(self):
        code, _, err = self.cli("--flavor", "anniversary")
        self.assertEqual(code, 2)
        self.assertIn("No addons found", err)

    def test_backup_failure_exit_code_keeps_files(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("x")
        code, _, err = self.cli("--flavor", "retail", "--clean", "--yes", "--backup-dir", str(blocker / "sub"))
        self.assertEqual(code, 4)
        self.assertIn("nothing was deleted", err)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    def test_nothing_to_clean(self):
        code, out, _ = self.cli("--flavor", "classic_era", "--clean", "--yes", "--backup-dir", str(self.backup_dir))
        self.assertEqual(code, 0)
        self.assertIn("Nothing to clean.", out)
        self.assertFalse(self.backup_dir.exists())

    def test_wow_running_warning(self):
        code, _, err = self.cli("--flavor", "retail", "--clean", "--dry-run", answer=None, wow_running=["Wow.exe"])
        self.assertEqual(code, 0)
        self.assertIn("WoW appears to be running", err)

    def test_partial_failure_exit_code(self):
        original = Path.unlink

        def flaky(path, *a, **k):
            if path.name == "DisabledAddon.lua":
                raise PermissionError("locked")
            return original(path, *a, **k)

        with patch.object(Path, "unlink", flaky):
            code, out, _ = self.cli("--flavor", "retail", "--clean", "--yes", "--no-backup")
        self.assertEqual(code, 3)
        self.assertIn("Failed: 1 files", out)


@unittest.skipIf(os.name == "nt", "shell wrapper test runs on POSIX")
class WrapperTest(unittest.TestCase):
    def test_sh_wrapper_runs_from_another_cwd(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            proc = subprocess.run(["sh", str(REPO_ROOT / "wow-tools.sh"), "--version"], cwd=elsewhere,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "0.1.0")

    def test_module_help(self):
        proc = subprocess.run([sys.executable, "-m", "wowtools", "wtf-cleaner", "--help"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--dry-run", proc.stdout)
