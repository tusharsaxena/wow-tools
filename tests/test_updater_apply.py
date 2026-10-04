from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
        self.downloaded = []

    def download(self, url, dest):
        """Serves the release's assets: the zip, and a SHA256SUMS that matches it."""
        self.downloaded.append(url)
        if url.endswith("/SHA256SUMS"):
            tag = url.rsplit("/", 2)[-2]
            digest = hashlib.sha256(self.zipball.read_bytes()).hexdigest()
            Path(dest).write_text(f"{digest}  wow-tools-{tag}.zip\n")
        else:
            shutil.copy(self.zipball, dest)

    def tree_digest(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.root.rglob("*")) if p.is_file()}

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

    def test_zip_with_matching_checksum_applies(self):
        make_zipball(self.zipball, "0.2.0")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=self.download)
        self.assertIn("0.2.0", self.version_on_disk())
        self.assertEqual(self.downloaded, [
            "https://github.com/tusharsaxena/wow-tools/releases/download/v0.2.0/SHA256SUMS",
            "https://github.com/tusharsaxena/wow-tools/releases/download/v0.2.0/wow-tools-v0.2.0.zip"])

    def test_zip_with_wrong_checksum_is_refused_and_tree_untouched(self):
        # F-010: a tampered asset must never replace the program files.
        make_zipball(self.zipball, "0.2.0")
        before = self.tree_digest()

        def tampered(url, dest):
            self.download(url, dest)
            if url.endswith("/SHA256SUMS"):
                text = Path(dest).read_text()
                Path(dest).write_text(("1" if text[0] != "1" else "2") + text[1:])

        with capture_events() as records:
            with self.assertRaises(UpdateError) as ctx:
                apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=tampered)
        self.assertIn("does not match its published checksum", str(ctx.exception))
        self.assertEqual(self.tree_digest(), before)
        self.assertFalse((self.root / ".update-backup").exists())
        self.assertIn("update.failed", [r["event"] for r in records])

    def test_sums_without_a_line_for_the_zip_is_refused(self):
        make_zipball(self.zipball, "0.2.0")

        def other_file(url, dest):
            self.download(url, dest)
            if url.endswith("/SHA256SUMS"):
                Path(dest).write_text("0" * 64 + "  something-else.zip\n")

        with self.assertRaises(UpdateError) as ctx:
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=other_file)
        self.assertIn("SHA256SUMS", str(ctx.exception))
        self.assertIn("0.1.0", self.version_on_disk())

    def test_missing_assets_refused_unless_allowed(self):
        make_zipball(self.zipball, "0.2.0")
        bare = ReleaseInfo("0.2.0", "v0.2.0", "", "https://api.github.com/zipball/v0.2.0",
                           "https://github.com/r/releases/tag/v0.2.0")
        with self.assertRaises(UpdateError) as ctx:
            apply_update(bare, root=self.root, current="0.1.0", download=self.download)
        self.assertIn("allow_unverified_updates", str(ctx.exception))
        self.assertIn("https://github.com/r/releases/tag/v0.2.0", str(ctx.exception))
        self.assertEqual(self.downloaded, [])
        self.assertIn("0.1.0", self.version_on_disk())
        with capture_events() as records:
            apply_update(bare, root=self.root, current="0.1.0", download=self.download, allow_unverified=True)
        self.assertIn("0.2.0", self.version_on_disk())
        self.assertEqual(self.downloaded, ["https://api.github.com/zipball/v0.2.0"])
        self.assertIn("update.unverified", [r["event"] for r in records])

    def test_unpublished_sums_asset_counts_as_missing(self):
        # A cached release (from_version) guesses the asset URLs; a 404 on SHA256SUMS means none was published.
        make_zipball(self.zipball, "0.2.0")

        def no_sums(url, dest):
            if url.endswith("/SHA256SUMS"):
                raise updater.AssetMissing(url)
            self.download(url, dest)

        with self.assertRaises(UpdateError) as ctx:
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=no_sums)
        self.assertIn("allow_unverified_updates", str(ctx.exception))
        self.assertIn("0.1.0", self.version_on_disk())
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=no_sums,
                     allow_unverified=True)
        self.assertIn("0.2.0", self.version_on_disk())

    def test_update_backup_keeps_newest_two(self):
        # F-018: one .update-backup/<version> per update would grow forever.
        for version in ("0.0.7", "0.0.8", "0.0.9"):
            (self.root / ".update-backup" / version).mkdir(parents=True)
        (self.root / ".update-backup" / "my-stuff").mkdir()
        make_zipball(self.zipball, "0.2.0")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=self.download)
        self.assertEqual(sorted(p.name for p in (self.root / ".update-backup").iterdir()),
                         ["0.0.9", "0.1.0", "my-stuff"])

    def test_backup_of_this_update_is_kept_after_a_downgrade(self):
        # R2: pruning by version number deleted the backup the update had just made of an older version.
        for version in ("0.1.2", "0.1.1"):
            (self.root / ".update-backup" / version).mkdir(parents=True)
        make_zipball(self.zipball, "0.2.0")
        apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", download=self.download)
        self.assertEqual(sorted(p.name for p in (self.root / ".update-backup").iterdir()), ["0.1.0", "0.1.2"])

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
        self.assertEqual([c[0][1] for c in self.calls], ["config", "status", "fetch", "merge"])
        for _args, kwargs in self.calls:
            self.assertEqual(kwargs["timeout"], updater.GIT_TIMEOUT_S)
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertIn("BatchMode=yes", kwargs["env"]["GIT_SSH_COMMAND"])
        self.assertEqual(updater.GIT_TIMEOUT_S, 120)

    def test_user_ssh_command_is_kept(self):
        with patch.dict("os.environ", {"GIT_SSH_COMMAND": "ssh -i mykey"}):
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0",
                         runner=self.ok_runner)
        for _args, kwargs in self.calls:
            self.assertEqual(kwargs["env"]["GIT_SSH_COMMAND"], "ssh -i mykey")

    def test_configured_ssh_program_is_not_overridden(self):
        # R2: GIT_SSH_COMMAND outranks GIT_SSH and core.sshCommand; only add BatchMode when neither is set.
        def configured(args, **kwargs):
            self.calls.append((args, kwargs))
            out = "ssh -i mykey" if args[1:4] == ["config", "--get", "core.sshCommand"] else ""
            return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("GIT_SSH_COMMAND", None)
            os.environ.pop("GIT_SSH", None)
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", runner=configured)
        for args, kwargs in self.calls:
            self.assertNotIn("GIT_SSH_COMMAND", kwargs["env"], args)
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.calls.clear()
        with patch.dict("os.environ", {"GIT_SSH": "plink.exe"}):
            os.environ.pop("GIT_SSH_COMMAND", None)
            apply_update(ReleaseInfo.from_version("0.2.0"), root=self.root, current="0.1.0", runner=self.ok_runner)
        for _args, kwargs in self.calls:
            self.assertNotIn("GIT_SSH_COMMAND", kwargs["env"])
            self.assertEqual(kwargs["env"]["GIT_SSH"], "plink.exe")

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
        self.assertIn("--untracked-files=no", self.calls[1][0])


GRANDCHILD = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)"
CHILD = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); "
         "time.sleep(30)")


class BoundedRunTest(unittest.TestCase):
    """R2: a timed-out git is stopped with everything it started (git-remote-https holds the output pipes, so on
    Windows subprocess.run waited for it long after the timeout)."""

    def test_timeout_stops_the_whole_process_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "grandchild.pid"
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                updater._run_bounded([sys.executable, "-c", CHILD, GRANDCHILD, str(pid_file)], cwd=tmp,
                                     capture_output=True, text=True, check=False, timeout=3, env=dict(os.environ))
            self.assertLess(time.monotonic() - started, 15)
            self.assertTrue(pid_file.exists())
            if os.name != "nt":  # on Windows the timing above is the point (no pipes left to drain)
                pid = int(pid_file.read_text())
                for _ in range(50):
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.1)
                else:
                    os.kill(pid, 9)
                    self.fail("the grandchild outlived the timeout")

    def test_output_and_return_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = updater._run_bounded([sys.executable, "-c", "import sys; print('out'); "
                                         "print('err', file=sys.stderr); sys.exit(3)"], cwd=tmp,
                                        capture_output=True, text=True, check=False, timeout=30,
                                        env=dict(os.environ))
        self.assertEqual((proc.returncode, proc.stdout.strip(), proc.stderr.strip()), (3, "out", "err"))

    def test_git_updates_use_the_bounded_runner_by_default(self):
        calls = []

        def fake(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp, patch.object(updater, "_run_bounded", fake):
            (Path(tmp) / ".git").mkdir()
            apply_update(ReleaseInfo.from_version("0.2.0"), root=Path(tmp), current="0.1.0")
        self.assertIn(["git", "merge", "--ff-only", "v0.2.0"], calls)


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
        seen = []
        code, out, _ = self.run_cmd([], check=lambda cfg, **kw: ReleaseInfo.from_version("9.9.9"),
                                    apply=lambda release, **kw: seen.append(kw) or "Updated. Restart.")
        self.assertEqual(code, 0)
        self.assertIn("Updated", out)
        self.assertEqual(seen, [{"allow_unverified": False}])
        self.cfg.set("general", "allow_unverified_updates", "true", log=False)
        self.run_cmd([], check=lambda cfg, **kw: ReleaseInfo.from_version("9.9.9"),
                     apply=lambda release, **kw: seen.append(kw) or "Updated. Restart.")
        self.assertEqual(seen[-1], {"allow_unverified": True})

    def test_apply_failure(self):
        def broken(release, **kw):
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
