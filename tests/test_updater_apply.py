import io
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from wowtools.core import updater
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.updater import ReleaseInfo, UpdateError, apply_update, install_kind, run_update_command

HAS_GIT = shutil.which("git") is not None
TOP = "tusharsaxena-wow-tools-abc123"


def make_install(root: Path, version: str) -> None:
    (root / "wowtools").mkdir(parents=True)
    (root / "wowtools" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (root / "vendor").mkdir()
    (root / "vendor" / "lib.py").write_text(f"# {version}\n")
    (root / "docs").mkdir()
    (root / "docs" / f"only-in-{version}.md").write_text("doc\n")
    (root / "README.md").write_text(f"readme {version}\n")
    (root / "requirements.txt").write_text("textual\n")


def make_zipball(path: Path, version: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{TOP}/wowtools/__init__.py", f'__version__ = "{version}"\n')
        zf.writestr(f"{TOP}/vendor/lib.py", f"# {version}\n")
        zf.writestr(f"{TOP}/docs/only-in-{version}.md", "doc\n")
        zf.writestr(f"{TOP}/scripts/x.py", "print('x')\n")
        zf.writestr(f"{TOP}/README.md", f"readme {version}\n")
        zf.writestr(f"{TOP}/requirements.txt", "textual\n")


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", *args],
                   cwd=cwd, check=True, capture_output=True)


class ZipUpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "suite"
        make_install(self.root, "0.1.0")
        (self.root / "wow-tools.cfg").write_text("[general]\n")
        (self.root / "logs").mkdir()
        (self.root / "logs" / "events-2026-09-27.jsonl").write_text("{}\n")
        (self.root / "my-notes.txt").write_text("mine")
        self.zipball = self.tmp / "release.zip"

    def download(self, url, dest):
        shutil.copy(self.zipball, dest)

    def version_on_disk(self):
        return (self.root / "wowtools" / "__init__.py").read_text()

    def test_install_kind(self):
        self.assertEqual(install_kind(self.root), "zip")
        (self.root / ".git").mkdir()
        self.assertEqual(install_kind(self.root), "git")

    def test_replaces_managed_paths_and_keeps_user_files(self):
        make_zipball(self.zipball, "0.2.0")
        with capture_events() as records:
            message = apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                                   download=self.download)
        self.assertIn("Restart", message)
        self.assertIn("0.2.0", self.version_on_disk())
        self.assertEqual((self.root / "README.md").read_text(), "readme 0.2.0\n")
        self.assertFalse((self.root / "docs" / "only-in-0.1.0.md").exists())
        self.assertTrue((self.root / "scripts" / "x.py").exists())
        self.assertEqual((self.root / "wow-tools.cfg").read_text(), "[general]\n")
        self.assertTrue((self.root / "logs" / "events-2026-09-27.jsonl").exists())
        self.assertEqual((self.root / "my-notes.txt").read_text(), "mine")
        self.assertIn("0.1.0", (self.root / ".update-backup" / "0.1.0" / "wowtools" / "__init__.py").read_text())
        applied = [r for r in records if r["event"] == "update.applied"][0]["data"]
        self.assertEqual((applied["from"], applied["to"], applied["method"]), ("0.1.0", "0.2.0", "zip"))

    def test_wrong_version_in_zip_is_rejected(self):
        make_zipball(self.zipball, "0.3.0")
        with capture_events() as records:
            with self.assertRaises(UpdateError):
                apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                             download=self.download)
        self.assertIn("0.1.0", self.version_on_disk())
        self.assertIn("update.failed", [r["event"] for r in records])

    def test_bad_zip_is_rejected(self):
        self.zipball.write_bytes(b"not a zip")
        with self.assertRaises(UpdateError):
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=self.download)
        self.assertIn("0.1.0", self.version_on_disk())

    def test_failure_mid_apply_rolls_back(self):
        make_zipball(self.zipball, "0.2.0")
        real_copy = updater._copy

        def failing_copy(src, dst):
            if TOP in str(src) and src.name == "vendor":
                raise OSError("disk full")
            real_copy(src, dst)

        with patch.object(updater, "_copy", failing_copy):
            with self.assertRaises(UpdateError) as ctx:
                apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                             download=self.download)
        self.assertIn("rolled back", str(ctx.exception))
        self.assertIn("0.1.0", self.version_on_disk())
        self.assertTrue((self.root / "docs" / "only-in-0.1.0.md").exists())
        self.assertEqual((self.root / "README.md").read_text(), "readme 0.1.0\n")
        self.assertTrue((self.root / "vendor" / "lib.py").exists())
        self.assertFalse((self.root / "scripts").exists())


@unittest.skipUnless(HAS_GIT, "git not installed")
class GitUpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin = self.tmp / "origin"
        make_install(self.origin, "0.1.0")
        git(self.origin, "init", "-q")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "v0.1.0")
        self.clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.clone))

    def test_refuses_dirty_tree(self):
        (self.clone / "README.md").write_text("my edit\n")
        with self.assertRaises(UpdateError) as ctx:
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.clone, current="0.1.0")
        self.assertIn("local changes", str(ctx.exception))

    def test_fast_forwards_to_tag(self):
        (self.origin / "wowtools" / "__init__.py").write_text('__version__ = "0.2.0"\n')
        git(self.origin, "commit", "-q", "-am", "v0.2.0")
        git(self.origin, "tag", "v0.2.0")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.clone, current="0.1.0")
        self.assertIn("0.2.0", (self.clone / "wowtools" / "__init__.py").read_text())


class UpdateCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = Config(Path(tmp.name) / "c.cfg")

    def run_cmd(self, argv, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        code = run_update_command(argv, self.cfg, stdout=out, stderr=err, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def test_check_only(self):
        code, out, _ = self.run_cmd(["--check"], check=lambda cfg, **kw: ReleaseInfo.from_version("9.9.9"))
        self.assertEqual(code, 10)
        self.assertIn("9.9.9", out)

    def test_up_to_date(self):
        code, out, _ = self.run_cmd([], check=lambda cfg, **kw: None)
        self.assertEqual(code, 0)
        self.assertIn("up to date", out)

    def test_apply(self):
        code, out, _ = self.run_cmd([], check=lambda cfg, **kw: ReleaseInfo.from_version("9.9.9"),
                                    apply=lambda release: "Updated. Restart.")
        self.assertEqual(code, 0)
        self.assertIn("Updated", out)

    def test_apply_failure(self):
        def broken(release):
            raise UpdateError("nope")
        code, _, err = self.run_cmd([], check=lambda cfg, **kw: ReleaseInfo.from_version("9.9.9"), apply=broken)
        self.assertEqual(code, 1)
        self.assertIn("nope", err)

    def test_check_failure(self):
        def offline(cfg, **kw):
            raise UpdateError("could not reach GitHub")
        code, _, err = self.run_cmd(["--check"], check=offline)
        self.assertEqual(code, 1)
        self.assertIn("Could not check", err)
