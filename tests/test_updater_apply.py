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
        (self.root / "config").mkdir()
        (self.root / "config" / "wow-tools.cfg").write_text("[general]\n")
        (self.root / "wtf-cleaner.sh").write_text("old wrapper\n")
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
        self.assertEqual((self.root / "config" / "wow-tools.cfg").read_text(), "[general]\n")
        self.assertFalse((self.root / "wtf-cleaner.sh").exists())  # retired wrapper removed, but backed up
        self.assertTrue((self.root / ".update-backup" / "0.1.0" / "wtf-cleaner.sh").exists())
        self.assertTrue((self.root / "logs" / "events-2026-09-27.jsonl").exists())
        self.assertEqual((self.root / "my-notes.txt").read_text(), "mine")
        self.assertIn("0.1.0", (self.root / ".update-backup" / "0.1.0" / "wowtools" / "__init__.py").read_text())
        applied = [r for r in records if r["event"] == "update.applied"][0]["data"]
        self.assertEqual((applied["from"], applied["to"], applied["method"]), ("0.1.0", "0.2.0", "zip"))

    def test_update_backup_keeps_newest_two(self):
        # F-018: one .update-backup/<version> per update would grow forever.
        for version in ("0.0.7", "0.0.8", "0.0.9"):
            (self.root / ".update-backup" / version).mkdir(parents=True)
        (self.root / ".update-backup" / "my-stuff").mkdir()
        make_zipball(self.zipball, "0.2.0")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=self.download)
        self.assertEqual(sorted(p.name for p in (self.root / ".update-backup").iterdir()),
                         ["0.0.9", "0.1.0", "my-stuff"])

    def test_failed_update_prunes_no_backups(self):
        for version in ("0.0.7", "0.0.8", "0.0.9"):
            (self.root / ".update-backup" / version).mkdir(parents=True)
        make_zipball(self.zipball, "0.3.0")
        with self.assertRaises(UpdateError):
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=self.download)
        self.assertEqual(len(list((self.root / ".update-backup").iterdir())), 3)

    def test_user_markdown_in_root_survives_zip_update(self):
        # F-019: only the root *.md files the release ships are program files.
        (self.root / "my-notes.md").write_text("my notes\n")
        make_zipball(self.zipball, "0.2.0")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=self.download)
        self.assertEqual((self.root / "my-notes.md").read_text(), "my notes\n")
        self.assertEqual((self.root / "README.md").read_text(), "readme 0.2.0\n")

    def test_rollback_leaves_user_markdown_alone(self):
        (self.root / "my-notes.md").write_text("my notes\n")
        make_zipball(self.zipball, "0.2.0")
        real_copy = updater._copy

        def failing_copy(src, dst):
            if TOP in str(src) and src.name == "vendor":
                raise OSError("disk full")
            real_copy(src, dst)

        with patch.object(updater, "_copy", failing_copy):
            with self.assertRaises(UpdateError):
                apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                             download=self.download)
        self.assertEqual((self.root / "my-notes.md").read_text(), "my notes\n")
        self.assertEqual((self.root / "README.md").read_text(), "readme 0.1.0\n")

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

    def test_failed_rollback_names_the_backup(self):
        make_zipball(self.zipball, "0.2.0")

        def always_fail(src, dst):
            if ".update-backup" in str(dst):
                shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
                return
            raise OSError("disk full")

        with patch.object(updater, "_copy", always_fail):
            with self.assertRaises(UpdateError) as ctx:
                apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                             download=self.download)
        self.assertIn("rollback also failed", str(ctx.exception))
        self.assertIn(".update-backup", str(ctx.exception))


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

    def test_untracked_file_does_not_block(self):
        (self.origin / "wowtools" / "__init__.py").write_text('__version__ = "0.2.0"\n')
        git(self.origin, "commit", "-q", "-am", "v0.2.0")
        git(self.origin, "tag", "v0.2.0")
        (self.clone / "my-notes.txt").write_text("mine\n")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.clone, current="0.1.0")
        self.assertIn("0.2.0", (self.clone / "wowtools" / "__init__.py").read_text())
        self.assertEqual((self.clone / "my-notes.txt").read_text(), "mine\n")

    def test_fast_forwards_to_tag(self):
        (self.origin / "wowtools" / "__init__.py").write_text('__version__ = "0.2.0"\n')
        git(self.origin, "commit", "-q", "-am", "v0.2.0")
        git(self.origin, "tag", "v0.2.0")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.clone, current="0.1.0")
        self.assertIn("0.2.0", (self.clone / "wowtools" / "__init__.py").read_text())


class GitRunnerTest(unittest.TestCase):
    """The git path with a fake runner: bounded, never prompts, ignores untracked files (F-011)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".git").mkdir()
        self.calls = []

    def ok_runner(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def test_git_runner_gets_timeout_and_no_prompt_env(self):
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", runner=self.ok_runner)
        self.assertEqual([c[0][1] for c in self.calls], ["status", "fetch", "merge"])
        for _args, kwargs in self.calls:
            self.assertEqual(kwargs["timeout"], updater.GIT_TIMEOUT_S)
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertIn("BatchMode=yes", kwargs["env"]["GIT_SSH_COMMAND"])
        self.assertEqual(updater.GIT_TIMEOUT_S, 120)

    def test_user_ssh_command_is_kept(self):
        with patch.dict("os.environ", {"GIT_SSH_COMMAND": "ssh -i mykey"}):
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                         runner=self.ok_runner)
        self.assertEqual(self.calls[0][1]["env"]["GIT_SSH_COMMAND"], "ssh -i mykey")

    def test_git_timeout_becomes_update_error(self):
        def hanging(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
        with capture_events() as records:
            with self.assertRaises(UpdateError) as ctx:
                apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", runner=hanging)
        self.assertIn("timed out", str(ctx.exception))
        self.assertIn("update.failed", [r["event"] for r in records])

    def test_untracked_files_do_not_block_update(self):
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", runner=self.ok_runner)
        self.assertIn("--untracked-files=no", self.calls[0][0])


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
