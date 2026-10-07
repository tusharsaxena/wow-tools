"""scripts/build_release.py (the zip + SHA256SUMS assets the updater verifies), the hashed vendor lock in
scripts/update_vendor.py (F-010) and the per-shard timeout in scripts/run_tests.py (F-014). Temp git repos only; no
network."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from pathlib import Path

from wowtools.core import updater
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.updater import ReleaseInfo, UpdateError, apply_update

HAS_GIT = shutil.which("git") is not None
CHANGELOG = "# Changelog\n\n## [0.2.0] - 2026-11-01\n\n- Two.\n\n## [0.1.0] - 2026-10-05\n\n- One.\n"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", *args],
                   cwd=cwd, check=True, capture_output=True)


@unittest.skipUnless(HAS_GIT, "git not installed")
class BuildReleaseTest(unittest.TestCase):
    def setUp(self):
        self.build_release = load_script("build_release")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo = self.tmp / "repo"
        (self.repo / "wowtools").mkdir(parents=True)
        (self.repo / "wowtools" / "__init__.py").write_text('__version__ = "0.2.0"\n')
        (self.repo / "README.md").write_text("readme 0.2.0\n")
        (self.repo / "CHANGELOG.md").write_text(CHANGELOG)
        (self.repo / "vendor").mkdir()
        (self.repo / "vendor" / "lib.py").write_text("# lib\n")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "release: v0.2.0")
        git(self.repo, "tag", "v0.2.0")
        self.out = self.tmp / "dist"

    def test_builds_zip_and_sums(self):
        zip_path, sums_path = self.build_release.build(self.repo, "0.2.0", self.out)
        self.assertEqual(zip_path.name, "wow-tools-v0.2.0.zip")
        self.assertEqual(sums_path.name, "SHA256SUMS")
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        self.assertEqual(sums_path.read_text(), f"{digest}  wow-tools-v0.2.0.zip\n")
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertIn("wow-tools-v0.2.0/wowtools/__init__.py", names)
        self.assertTrue(all(n.startswith("wow-tools-v0.2.0/") for n in names))

    def test_refuses_a_missing_tag(self):
        with self.assertRaises(SystemExit) as ctx:
            self.build_release.build(self.repo, "0.3.0", self.out)
        self.assertIn("v0.3.0", str(ctx.exception))

    def test_refuses_a_tag_whose_version_differs(self):
        git(self.repo, "tag", "v0.4.0")
        with self.assertRaises(SystemExit) as ctx:
            self.build_release.build(self.repo, "0.4.0", self.out)
        self.assertIn("0.2.0", str(ctx.exception))

    def retag(self, changelog: str | None) -> None:
        """Move v0.2.0 onto a commit whose CHANGELOG.md is `changelog` (None: deleted)."""
        path = self.repo / "CHANGELOG.md"
        if changelog is None:
            path.unlink()
        else:
            path.write_text(changelog, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "changelog")
        git(self.repo, "tag", "-f", "v0.2.0")

    def test_refuses_a_tag_without_a_changelog_entry_for_its_version(self):
        self.retag("# Changelog\n\n## [0.1.0] - 2026-10-05\n\n- One.\n")
        with self.assertRaises(SystemExit) as ctx:
            self.build_release.build(self.repo, "0.2.0", self.out)
        self.assertIn("no entry for 0.2.0", str(ctx.exception))
        self.assertFalse((self.out / "wow-tools-v0.2.0.zip").exists())

    def test_an_unreleased_section_is_not_the_versions_entry(self):
        self.retag("# Changelog\n\n## [Unreleased]\n\n- Two.\n\n## [0.1.0] - 2026-10-05\n\n- One.\n")
        with self.assertRaises(SystemExit) as ctx:
            self.build_release.build(self.repo, "0.2.0", self.out)
        self.assertIn("no entry for 0.2.0", str(ctx.exception))

    def test_refuses_a_tag_without_a_changelog_or_with_a_malformed_one(self):
        for changelog, message in ((None, "has no CHANGELOG.md"), ("## [0.2.0]\n", "malformed")):
            with self.subTest(message=message):
                self.retag(changelog)
                with self.assertRaises(SystemExit) as ctx:
                    self.build_release.build(self.repo, "0.2.0", self.out)
                self.assertIn(message, str(ctx.exception))

    def test_the_tags_changelog_is_read_as_utf8_whatever_the_locale(self):
        # cp1252 (Windows) cannot decode 0x81/0x8D/0x8F/0x90/0x9D, bytes of e.g. U+2010, Á and č in UTF-8
        notes = "- Non-ASCII: \u2010 \u00c1 \u010d \u2191\u2193.\n"
        self.retag(f"# Changelog\n\n## [0.2.0] - 2026-11-01\n\n{notes}")
        shown = self.build_release._git(self.repo, "show", "v0.2.0:CHANGELOG.md")
        self.assertIn(notes, shown.stdout)
        with mock.patch.object(self.build_release.subprocess, "run", wraps=subprocess.run) as run:
            self.build_release.check_changelog(self.repo, "v0.2.0", "0.2.0")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")

    def test_the_changelog_is_read_at_the_tag_not_the_working_tree(self):
        (self.repo / "CHANGELOG.md").write_text("broken\n")  # uncommitted: the tag's file is what ships
        zip_path, _ = self.build_release.build(self.repo, "0.2.0", self.out)
        self.assertTrue(zip_path.is_file())

    def test_updater_accepts_the_built_assets_and_refuses_a_changed_zip(self):
        zip_path, sums_path = self.build_release.build(self.repo, "0.2.0", self.out)
        root = self.tmp / "install"
        (root / "wowtools").mkdir(parents=True)
        (root / "wowtools" / "__init__.py").write_text('__version__ = "0.1.0"\n')
        release = ReleaseInfo("0.2.0", "v0.2.0", assets={zip_path.name: "zip-url", "SHA256SUMS": "sums-url"})
        served = {"zip-url": zip_path, "sums-url": sums_path}

        def download(url, dest):
            shutil.copy(served[url], dest)

        tampered = self.tmp / "tampered.zip"
        shutil.copy(zip_path, tampered)
        with zipfile.ZipFile(tampered, "a") as zf:
            zf.writestr("wow-tools-v0.2.0/extra.py", "print('not in the release')\n")
        served_tampered = dict(served, **{"zip-url": tampered})
        with self.assertRaises(UpdateError):
            apply_update(release, root=root, current="0.1.0",
                         download=lambda url, dest: shutil.copy(served_tampered[url], dest))
        self.assertIn("0.1.0", (root / "wowtools" / "__init__.py").read_text())

        apply_update(release, root=root, current="0.1.0", download=download)
        self.assertIn("0.2.0", (root / "wowtools" / "__init__.py").read_text())
        self.assertEqual((root / "README.md").read_text(), "readme 0.2.0\n")

    def test_release_zip_name_matches_the_updater(self):
        self.assertEqual(self.build_release.zip_name("1.2.3"), updater.release_zip_name("1.2.3"))


class VendorLockTest(unittest.TestCase):
    def setUp(self):
        self.update_vendor = load_script("update_vendor")

    def test_parse_pins(self):
        pins = self.update_vendor.parse_pins("# comment\ntextual==8.2.8\n\nPygments==2.21.0  # note\n")
        self.assertEqual(pins, [("textual", "8.2.8"), ("Pygments", "2.21.0")])

    def test_unpinned_requirement_is_refused(self):
        with self.assertRaises(SystemExit):
            self.update_vendor.parse_pins("textual>=8\n")

    def test_render_lock_uses_pure_python_wheel_hashes(self):
        def fake_files(name, version):
            return [{"filename": f"{name}-{version}-py3-none-any.whl", "packagetype": "bdist_wheel",
                     "digests": {"sha256": "a" * 64}},
                    {"filename": f"{name}-{version}.tar.gz", "packagetype": "sdist", "digests": {"sha256": "b" * 64}},
                    {"filename": f"{name}-{version}-cp312-cp312-win_amd64.whl", "packagetype": "bdist_wheel",
                     "digests": {"sha256": "c" * 64}}]

        text = self.update_vendor.render_lock([("mdurl", "0.1.2")], fake_files)
        self.assertIn("mdurl==0.1.2 \\\n    --hash=sha256:" + "a" * 64 + "\n", text)
        self.assertNotIn("b" * 64, text)
        self.assertNotIn("c" * 64, text)

    def test_package_without_a_pure_wheel_is_refused(self):
        with self.assertRaises(SystemExit):
            self.update_vendor.render_lock([("x", "1.0")], lambda n, v: [])

    def test_lock_must_match_requirements(self):
        lock = "textual==8.2.8 \\\n    --hash=sha256:" + "a" * 64 + "\n"
        self.assertEqual(self.update_vendor.lock_pins(lock), [("textual", "8.2.8")])
        self.update_vendor.check_lock([("textual", "8.2.8")], lock)
        with self.assertRaises(SystemExit) as ctx:
            self.update_vendor.check_lock([("textual", "8.3.0")], lock)
        self.assertIn("--lock", str(ctx.exception))

    def test_committed_lock_matches_requirements(self):
        pins = self.update_vendor.parse_pins((REPO_ROOT / "requirements.txt").read_text(encoding="utf-8"))
        self.update_vendor.check_lock(pins, (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8"))
        self.assertIn("--hash=sha256:", (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8"))


class RunTestsTimeoutTest(unittest.TestCase):
    """scripts/run_tests.py bounds each shard, so one hung test fails the run with its output instead of
    blocking it until CI's job timeout (F-014)."""

    def setUp(self):
        self.run_tests = load_script("run_tests")

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.run_tests.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_a_hung_shard_is_killed_and_reported_with_the_test_it_hung_in(self):
        script = ("import sys, time\n"
                  f"print({self.run_tests.RUNNING_PREFIX!r} + 'tests.test_x.T.test_fine', flush=True)\n"
                  f"print({self.run_tests.RUNNING_PREFIX!r} + 'tests.test_x.T.test_hangs', flush=True)\n"
                  "print('partial shard output', file=sys.stderr, flush=True)\n"
                  "time.sleep(60)\n")
        sleeper = [sys.executable, "-c", script]
        started = time.monotonic()
        with mock.patch.object(self.run_tests, "_shard_command", return_value=sleeper):
            code, out, err = self.run_main("-j", "1", "--timeout", "1")
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(code, 1)
        self.assertIn("===== shard 1/1 timed out after 1 s in tests.test_x.T.test_hangs =====", err)
        self.assertIn("partial shard output", err)
        self.assertTrue(out.rstrip().endswith("FAILED"), out)

    def test_a_shard_names_each_test_as_it_starts(self):
        command = self.run_tests._shard_command(0, 1, "RunTestsTimeoutTest.test_default_timeout")
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              cwd=REPO_ROOT, timeout=120, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(self.run_tests.RUNNING_PREFIX + "tests.test_release_scripts.RunTestsTimeoutTest."
                      "test_default_timeout_scales_below_four_shards_and_zero_turns_it_off", proc.stdout)

    def test_a_shard_that_hangs_after_its_tests_finished_is_not_blamed_on_its_last_test(self):
        summary = '{"run": 2, "failures": 0, "errors": 0, "skipped": 0}'
        script = ("import time\n"
                  f"print({self.run_tests.RUNNING_PREFIX!r} + 'tests.test_x.T.test_last', flush=True)\n"
                  f"print({self.run_tests.RESULT_PREFIX!r} + {summary!r}, flush=True)\n"
                  "time.sleep(60)\n")
        sleeper = [sys.executable, "-c", script]
        with mock.patch.object(self.run_tests, "_shard_command", return_value=sleeper):
            code, out, err = self.run_main("-j", "1", "--timeout", "1")
        self.assertEqual(code, 1)
        self.assertIn("===== shard 1/1 timed out after 1 s after its tests finished =====", err)
        self.assertNotIn("test_last", err)
        self.assertIn("Ran 2 tests", out)
        self.assertTrue(out.rstrip().endswith("FAILED"), out)

    def test_a_timeout_kills_what_the_shard_started_and_does_not_wait_for_its_output(self):
        # The hung shard starts a child that inherits its stdout and stderr and keeps writing to a file: on Windows,
        # subprocess.run would wait for that child to close the pipes after the timeout; the child must die too.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ticks = Path(tmp.name) / "ticks.txt"
        child = ("import time\n"
                 "for _ in range(600):\n"
                 f"    open({str(ticks)!r}, 'a').write('.')\n"
                 "    time.sleep(0.1)\n")
        script = ("import subprocess, sys, time\n"
                  f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                  f"print({self.run_tests.RUNNING_PREFIX!r} + 'tests.test_x.T.test_spawns', flush=True)\n"
                  "time.sleep(60)\n")
        sleeper = [sys.executable, "-c", script]
        started = time.monotonic()
        with mock.patch.object(self.run_tests, "_shard_command", return_value=sleeper):
            code, _, err = self.run_main("-j", "1", "--timeout", "2")
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(code, 1)
        self.assertIn("timed out after 2 s in tests.test_x.T.test_spawns", err)
        self.assertTrue(ticks.exists(), "the child never started")
        time.sleep(0.5)
        size = ticks.stat().st_size
        time.sleep(1.0)
        self.assertEqual(ticks.stat().st_size, size, "the shard's child is still running after the timeout")

    def test_default_timeout_scales_below_four_shards_and_zero_turns_it_off(self):
        seen = []

        def fake_launch(index, count, pattern, timeout):
            seen.append(timeout)
            return 0, {"run": 1, "failures": 0, "errors": 0, "skipped": 0}, "", None

        with mock.patch.object(self.run_tests, "_launch", side_effect=fake_launch):
            for argv in (["-j", "8"], ["-j", "4"], ["-j", "2"], ["-j", "1"], ["-j", "1", "--timeout", "0"],
                         ["-j", "1", "--timeout", "90"]):
                self.assertEqual(self.run_main(*argv)[0], 0, argv)
        self.assertEqual(seen, [600] * 8 + [600] * 4 + [1200] * 2 + [2400, None, 90])
