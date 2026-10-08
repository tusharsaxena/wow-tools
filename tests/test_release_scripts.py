"""scripts/build_release.py (the zip + SHA256SUMS assets the updater verifies), the hashed vendor lock in
scripts/update_vendor.py (F-010), the per-shard timeout in scripts/run_tests.py (F-014) and its --windows /
--all runs (spec F1) and its shards balanced by recorded test time (spec F2). Temp git repos only; no network; no
test starts cmd.exe, and no test writes the checkout's own test-time cache."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
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


def load_run_tests(case: unittest.TestCase, ids: list[str] | None = None):
    """scripts/run_tests.py with its test-time cache in a temp folder (never the checkout's own) and, given ids,
    a faked discovery, so main() neither imports the whole suite nor writes outside the test's temp folder."""
    module = load_script("run_tests")
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    module.TIMES_DIR = Path(tmp.name)
    if ids is not None:
        patcher = mock.patch.object(module, "_discover_ids", side_effect=lambda pattern: [
            test_id for test_id in ids if pattern is None or pattern in test_id])
        patcher.start()
        case.addCleanup(patcher.stop)
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

    def test_the_zip_leaves_out_export_ignored_paths(self):
        """STD-11.5: the zip is a git archive of the tag, so .gitattributes' export-ignore lines (the "Stays out"
        table of docs/releasing.md) keep the developer files out of it."""
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_x.py").write_text("# test\n")
        (self.repo / "CLAUDE.md").write_text("dev\n")
        (self.repo / ".gitattributes").write_text("/tests export-ignore\n/CLAUDE.md export-ignore\n"
                                                  "/.gitattributes export-ignore\n")
        self.retag(CHANGELOG)
        zip_path, _ = self.build_release.build(self.repo, "0.2.0", self.out)
        with zipfile.ZipFile(zip_path) as zf:
            names = sorted(n for n in zf.namelist() if not n.endswith("/"))
        self.assertEqual(names, [f"wow-tools-v0.2.0/{p}" for p in
                                 ("CHANGELOG.md", "README.md", "vendor/lib.py", "wowtools/__init__.py")])

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
        self.run_tests = load_run_tests(self, ["tests.test_x.T.test_fine"])

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

    def test_a_shard_names_each_test_as_it_starts_and_runs_exactly_its_list(self):
        """The real shard child (spec F2): it runs the ids in its list file, no others, names each as it starts
        and reports how long each took."""
        wanted = [("tests.test_release_scripts.RunTestsTimeoutTest."
                   "test_default_timeout_scales_below_four_shards_and_zero_turns_it_off"),
                  "tests.test_release_scripts.RunTestsBalanceTest.test_the_median_of_no_times_is_zero"]
        ids_file = Path(self.run_tests.TIMES_DIR) / "ids.txt"
        ids_file.write_text("\n".join(wanted) + "\n", encoding="utf-8")
        proc = subprocess.run(self.run_tests._shard_command(ids_file), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=REPO_ROOT, timeout=120, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        started = [line[len(self.run_tests.RUNNING_PREFIX):] for line in proc.stdout.splitlines()
                   if line.startswith(self.run_tests.RUNNING_PREFIX)]
        self.assertEqual(started, sorted(wanted))
        (result,) = [json.loads(line[len(self.run_tests.RESULT_PREFIX):]) for line in proc.stdout.splitlines()
                     if line.startswith(self.run_tests.RESULT_PREFIX)]
        self.assertEqual(result["run"], 2)
        self.assertEqual(sorted(result["times"]), sorted(wanted))
        self.assertTrue(all(seconds >= 0 for seconds in result["times"].values()))

    def test_a_shard_fails_when_a_listed_test_is_not_found(self):
        """A listed id the child does not discover again is not silently dropped: the child names it and fails."""
        found = "tests.test_release_scripts.RunTestsBalanceTest.test_the_median_of_no_times_is_zero"
        gone = "tests.test_x.T.test_that_does_not_exist"
        ids_file = Path(self.run_tests.TIMES_DIR) / "ids.txt"
        ids_file.write_text(f"{found}\n{gone}\n", encoding="utf-8")
        proc = subprocess.run(self.run_tests._shard_command(ids_file), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=REPO_ROOT, timeout=120, check=False)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn(gone, proc.stderr)
        (result,) = [json.loads(line[len(self.run_tests.RESULT_PREFIX):]) for line in proc.stdout.splitlines()
                     if line.startswith(self.run_tests.RESULT_PREFIX)]
        self.assertEqual((result["run"], result["listed"], result["missing"]), (1, 2, [gone]))

    def test_the_runner_fails_a_shard_that_did_not_get_or_find_its_whole_list(self):
        """The parent checks each summary against the ids it dealt: a list the child read short, or ids it did not
        find, fail the run even if the child exited 0."""
        self.run_tests._discover_ids.side_effect = lambda pattern: ["tests.test_x.T.test_a", "tests.test_x.T.test_b"]
        for gap in ({"listed": 1, "missing": []}, {"listed": 2, "missing": ["tests.test_x.T.test_b"]}):
            def fake_launch(ids, timeout, gap=gap):
                return 0, {"run": 1, "failures": 0, "errors": 0, "skipped": 0, **gap}, "", None, 0.1

            with mock.patch.object(self.run_tests, "_launch", side_effect=fake_launch):
                code, out, err = self.run_main("-j", "1")
            self.assertEqual(code, 1, gap)
            self.assertIn("===== shard 1/1 did not run its whole list", err)
            self.assertTrue(out.rstrip().endswith("FAILED"), out)

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

        def fake_launch(ids, timeout):
            seen.append(timeout)
            return 0, {"run": 1, "failures": 0, "errors": 0, "skipped": 0}, "", None, 0.1

        self.run_tests._discover_ids.side_effect = lambda pattern: [f"tests.test_x.T.test_{n}" for n in range(8)]
        with mock.patch.object(self.run_tests, "_launch", side_effect=fake_launch):
            for argv in (["-j", "8"], ["-j", "4"], ["-j", "2"], ["-j", "1"], ["-j", "1", "--timeout", "0"],
                         ["-j", "1", "--timeout", "90"]):
                self.assertEqual(self.run_main(*argv)[0], 0, argv)
        self.assertEqual(seen, [600] * 8 + [600] * 4 + [1200] * 2 + [2400, None, 90])


class RunTestsBalanceTest(unittest.TestCase):
    """scripts/run_tests.py deals the tests into shards by recorded time (spec F2): longest first, each to the
    least-loaded shard; a test with no recorded time counts as the median; with no usable cache, round-robin."""

    def setUp(self):
        self.IDS = [f"tests.test_x.T.test_{name}" for name in "abcdefg"]
        self.run_tests = load_run_tests(self, self.IDS)

    def loads(self, shards, times):
        return [round(sum(times[test_id] for test_id in shard), 3) for shard in shards]

    def test_longest_first_to_the_least_loaded_shard(self):
        times = dict(zip(self.IDS, [1.0, 9.0, 4.0, 4.0, 3.0, 2.0, 8.0]))
        shards = self.run_tests.balance(self.IDS, times, 3)
        # b 9 -> s0; g 8 -> s1; c 4 -> s2; d 4 -> s2; e 3 -> s1 (8 = 8, the lower index); f 2 -> s2; a 1 -> s0
        self.assertEqual(self.loads(shards, times), [10.0, 11.0, 10.0])
        self.assertEqual(shards[0], [self.IDS[0], self.IDS[1]])
        self.assertEqual(sorted(test_id for shard in shards for test_id in shard), self.IDS,
                         "every test in exactly one shard")
        for shard in shards:
            self.assertEqual(shard, sorted(shard), "a shard runs its tests in id order, a class's tests together")

    def test_a_test_with_no_recorded_time_counts_as_the_median(self):
        times = {self.IDS[0]: 10.0, self.IDS[1]: 1.0, self.IDS[2]: 2.0, self.IDS[3]: 3.0}
        self.assertEqual(self.run_tests.median(times.values()), 2.5)
        shards = self.run_tests.balance(self.IDS[:6], times, 2)
        weights = {**{test_id: 2.5 for test_id in self.IDS[4:6]}, **times}
        self.assertEqual(self.loads(shards, weights), [11.0, 10.0])
        self.assertEqual(shards[0], [self.IDS[0], self.IDS[1]])

    def test_the_median_of_no_times_is_zero(self):
        self.assertEqual(self.run_tests.median([]), 0.0)
        self.assertEqual(self.run_tests.median([3.0, 1.0, 2.0]), 2.0)

    def test_no_cache_is_round_robin_by_id(self):
        for times in (None, {}):
            self.assertEqual(self.run_tests.balance(self.IDS, times, 3), [self.IDS[0::3], self.IDS[1::3],
                                                                          self.IDS[2::3]])

    def test_the_same_cache_always_gives_the_same_shards(self):
        times = {test_id: 1.0 for test_id in self.IDS}  # all ties: the order must still be fixed
        first = self.run_tests.balance(self.IDS, times, 3)
        self.assertEqual(self.run_tests.balance(list(reversed(self.IDS)), dict(reversed(times.items())), 3), first)
        self.assertEqual(first, [self.IDS[0::3], self.IDS[1::3], self.IDS[2::3]])

    def test_more_shards_than_tests_leaves_none_empty(self):
        self.assertEqual(self.run_tests.balance(self.IDS[:2], None, 5), [[self.IDS[0]], [self.IDS[1]]])
        self.assertEqual(self.run_tests.balance([], None, 5), [[]])

    def test_the_cache_is_one_file_per_platform_in_the_checkout(self):
        path = self.run_tests.times_path
        self.assertEqual(path("wsl"), self.run_tests.TIMES_DIR / ".test-times-wsl.json")
        self.assertNotEqual(path("wsl"), path("windows"))
        ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".test-times-*.json", ignored, "the cache is never committed (and so never released)")

    def test_cache_write_then_read(self):
        path = self.run_tests.times_path("wsl")
        self.run_tests.write_times(path, {"a": 1.25, "b": 2.0}, keep=None)
        self.assertEqual(self.run_tests.read_times(path), {"a": 1.25, "b": 2.0})
        self.run_tests.write_times(path, {"b": 3.0, "c": 0.5}, keep=None)  # a -k run: the others stay
        self.assertEqual(self.run_tests.read_times(path), {"a": 1.25, "b": 3.0, "c": 0.5})
        self.run_tests.write_times(path, {"c": 0.75}, keep={"b", "c"})  # a full run: tests gone are dropped
        self.assertEqual(self.run_tests.read_times(path), {"b": 3.0, "c": 0.75})
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), [path.name], "no temp file left")

    def test_a_missing_or_corrupt_cache_reads_as_none(self):
        path = self.run_tests.times_path("wsl")
        self.assertIsNone(self.run_tests.read_times(path))
        for data in (b"{not json", b"[1, 2]", b'{"version": 1, "times": [1]}', b'{"version": 99, "times": {}}',
                     b"\xff\xfe\x00"):
            path.write_bytes(data)
            self.assertIsNone(self.run_tests.read_times(path), data)
        path.write_text(json.dumps({"version": 1, "times": {"a": 1.0, "b": "slow", "c": -1, "d": float("inf"),
                                                            "e": True}}), encoding="utf-8")
        self.assertEqual(self.run_tests.read_times(path), {"a": 1.0}, "only the usable entries")

    def test_a_cache_that_cannot_be_written_is_ignored(self):
        path = self.run_tests.TIMES_DIR / "missing-folder" / ".test-times-wsl.json"
        self.run_tests.write_times(path, {"a": 1.0}, keep=None)  # no exception
        self.assertFalse(path.exists())

    def run_main(self, *argv, durations=None):
        """main() with each shard faked: it 'runs' its ids, reports durations (default 1 s each) and the shard
        took the sum of them."""
        durations = durations or {}
        seen = []

        def fake_launch(ids, timeout):
            seen.append(list(ids))
            times = {test_id: durations.get(test_id, 1.0) for test_id in ids}
            summary = {"run": len(ids), "failures": 0, "errors": 0, "skipped": 0, "times": times}
            return 0, summary, "", None, sum(times.values())

        out = io.StringIO()
        with mock.patch.object(self.run_tests, "host_kind", return_value="wsl"), \
                mock.patch.object(self.run_tests, "_launch", side_effect=fake_launch), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = self.run_tests.main(list(argv))
        return code, out.getvalue(), seen

    def test_a_run_records_its_times_and_the_next_run_is_balanced_by_them(self):
        durations = dict(zip(self.IDS, [1.0, 9.0, 4.0, 4.0, 3.0, 2.0, 8.0]))
        code, out, seen = self.run_main("-j", "3", durations=durations)
        self.assertEqual(code, 0)
        self.assertEqual(seen, [self.IDS[0::3], self.IDS[1::3], self.IDS[2::3]], "no cache yet: round-robin")
        self.assertIn("round-robin", out)
        self.assertEqual(self.run_tests.read_times(self.run_tests.times_path("wsl")), durations)
        code, out, seen = self.run_main("-j", "3", durations=durations)
        self.assertEqual(sorted(seen), sorted(self.run_tests.balance(self.IDS, durations, 3)))
        self.assertIn("Shard times: fastest 10.0 s, slowest 11.0 s (balanced by recorded test times)", out)
        self.assertIn("Ran 7 tests in ", out)

    def test_a_k_run_uses_the_cache_and_keeps_the_other_tests_times(self):
        cache = {test_id: 1.0 for test_id in self.IDS}
        cache[self.IDS[0]] = 5.0
        self.run_tests.write_times(self.run_tests.times_path("wsl"), cache, keep=None)
        code, _, seen = self.run_main("-j", "2", "-k", "test_a", durations={self.IDS[0]: 6.0})
        self.assertEqual((code, seen), (0, [[self.IDS[0]]]))
        self.assertEqual(self.run_tests.read_times(self.run_tests.times_path("wsl")), {**cache, self.IDS[0]: 6.0})

    def test_a_corrupt_cache_falls_back_to_round_robin_silently(self):
        self.run_tests.times_path("wsl").write_text("{corrupt", encoding="utf-8")
        code, out, seen = self.run_main("-j", "2")
        self.assertEqual((code, seen), (0, [self.IDS[0::2], self.IDS[1::2]]))
        self.assertNotIn("corrupt", out.lower())
        self.assertEqual(len(self.run_tests.read_times(self.run_tests.times_path("wsl"))), len(self.IDS))

    def test_verbose_shards_prints_each_shards_time(self):
        code, out, _ = self.run_main("-j", "2", "--verbose-shards")
        self.assertEqual(code, 0)
        self.assertIn("shard 1/2: 4.0 s, 4 tests", out)
        self.assertIn("shard 2/2: 3.0 s, 3 tests", out)


class RunTestsShardCountTest(unittest.TestCase):
    """scripts/run_tests.py's default shard count was chosen by measurement (spec F3): 1.5 shards per CPU, at most
    MAX_DEFAULT_JOBS, since the tests spend much of their time waiting (pilots, workers, file I/O)."""

    def setUp(self):
        self.IDS = [f"tests.test_x.T.test_{index:02d}" for index in range(40)]
        self.run_tests = load_run_tests(self, self.IDS)

    def test_the_default_is_one_and_a_half_shards_per_cpu_with_a_cap(self):
        default_jobs = self.run_tests.default_jobs
        self.assertEqual(self.run_tests.MAX_DEFAULT_JOBS, 24)
        self.assertEqual([default_jobs(cpus) for cpus in (1, 2, 3, 4, 8, 16, 32, 64)], [1, 3, 4, 6, 12, 24, 24, 24])

    def test_no_cpu_count_counts_as_two_cpus(self):
        with mock.patch.object(self.run_tests.os, "cpu_count", return_value=None):
            self.assertEqual(self.run_tests.default_jobs(), 3)

    def test_the_plain_run_deals_the_default_number_of_shards(self):
        seen = []

        def fake_launch(ids, timeout):
            seen.append(ids)
            return 0, {"run": len(ids), "failures": 0, "errors": 0, "skipped": 0, "listed": len(ids)}, "", None, 0.1

        out = io.StringIO()
        with mock.patch.object(self.run_tests.os, "cpu_count", return_value=16), \
                mock.patch.object(self.run_tests, "_launch", side_effect=fake_launch), redirect_stdout(out):
            code = self.run_tests.main([])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(len(seen), 24)
        self.assertIn("across 24 processes", out.getvalue())

    def test_the_ci_shard_count_in_the_docs_is_the_default_on_a_4_vcpu_runner(self):
        """CI passes no -j, so a 4-vCPU GitHub runner runs default_jobs(4) shards; testing.md names that number."""
        shards = self.run_tests.default_jobs(4)
        testing = (REPO_ROOT / "docs" / "testing.md").read_text(encoding="utf-8")
        self.assertIn(f"{shards} shards on a 4-vCPU runner", testing)
        workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertNotIn("four shards", workflow + testing)


class RunTestsWindowsTest(unittest.TestCase):
    """scripts/run_tests.py --windows and --all (spec F1): from WSL the suite also runs under the native Windows
    Python in the same checkout through cmd.exe. The cmd.exe call (_relay) is faked here: no test starts Windows."""

    def setUp(self):
        self.run_tests = load_run_tests(self, ["tests.test_x.T.test_a", "tests.test_x.T.test_b"])
        self.calls = []
        self.codes = {"wsl": 0, "windows": 0}
        self.windows_starts = True
        self.windows_raises = None  # an exception the Windows side's start raises (cmd.exe gone, say)

    def fake_relay(self, command, cwd, env, sink, windows):
        self.calls.append({"command": command, "cwd": cwd, "env": env, "windows": windows})
        side = "windows" if windows else "wsl"
        if windows and self.windows_raises is not None:
            raise self.windows_raises
        if windows and not self.windows_starts:
            sink("'py' is not recognized as an internal or external command,\n")
            return 1
        sink(f"{side} output\n")
        sink("Ran 5 tests in 1.0s across 2 processes (0 failures, 0 errors, 0 skipped)\n")
        sink("OK\n" if self.codes[side] == 0 else "FAILED\n")
        return self.codes[side]

    def run_main(self, *argv: str, host: str = "wsl") -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(self.run_tests, "host_kind", return_value=host), \
                mock.patch.object(self.run_tests, "_windows_path", return_value=r"D:\GIT\wow-tools"), \
                mock.patch.object(self.run_tests, "_require_cmd_exe"), \
                mock.patch.object(self.run_tests, "_relay", side_effect=self.fake_relay), \
                redirect_stdout(out), redirect_stderr(err):
            code = self.run_tests.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def windows_line(self) -> str:
        (call,) = [c for c in self.calls if c["windows"]]
        return call["env"][self.run_tests.WINDOWS_RUN_VAR]

    def test_windows_runs_the_suite_through_cmd_exe_with_the_flags_passed_through(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop(self.run_tests.WINDOWS_PYTHON_ENV, None)
            self.codes["windows"] = 3
            code, out, _ = self.run_main("--windows", "-j", "4", "-k", "tree view", "--timeout", "90")
        self.assertEqual(code, 3, "the Windows run's exit code is returned")
        (call,) = self.calls
        self.assertTrue(call["windows"])
        self.assertEqual(call["command"], ["cmd.exe", "/d", "/c", f"%{self.run_tests.WINDOWS_RUN_VAR}%"])
        self.assertEqual(self.windows_line(), r'pushd "D:\GIT\wow-tools" && py -3 scripts\run_tests.py '
                                              r'--announce-pid "-j" "4" "-k" "tree view" "--timeout" "90"')
        self.assertIn(f"{self.run_tests.WINDOWS_RUN_VAR}:PYTHONIOENCODING", call["env"]["WSLENV"])
        self.assertEqual(call["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertRegex(Path(call["cwd"]).as_posix(), r"^/mnt/[a-z](/|$)", "a Windows-drive cwd: no UNC warning")
        self.assertIn("windows output", out)

    def test_verbose_shards_is_passed_on_to_the_windows_run_and_both_sides_of_all(self):
        self.run_main("--windows", "--verbose-shards")
        self.assertTrue(self.windows_line().endswith('"--verbose-shards"'), self.windows_line())
        self.calls.clear()
        self.run_main("--all", "-j", "2", "--verbose-shards")
        wsl, = [c for c in self.calls if not c["windows"]]
        self.assertEqual(wsl["command"][-3:], ["-j", "2", "--verbose-shards"])
        self.assertTrue(self.windows_line().endswith('"-j" "2" "--verbose-shards"'), self.windows_line())

    def test_windows_without_flags_lets_the_windows_side_pick_its_shards(self):
        self.assertEqual(self.run_main("--windows")[0], 0)
        self.assertTrue(self.windows_line().endswith("--announce-pid"), self.windows_line())

    def test_the_windows_python_command_can_be_overridden(self):
        with mock.patch.dict("os.environ", {self.run_tests.WINDOWS_PYTHON_ENV: "py -3.14"}):
            self.run_main("--windows")
        self.assertIn(r" && py -3.14 scripts\run_tests.py ", self.windows_line())

    def test_a_double_quote_in_a_passed_flag_is_refused(self):
        code, _, err = self.run_main("--windows", "-k", 'a"b')
        self.assertEqual(code, 2)
        self.assertIn('"', err)
        self.assertEqual(self.calls, [])

    def test_a_trailing_backslash_in_a_passed_flag_reaches_windows_unchanged(self):
        """Windows reads a lone \\" as an escaped quote: backslashes before the closing quote are doubled."""
        self.run_main("--windows", "-k", "tests\\")
        self.assertTrue(self.windows_line().endswith(r'"-k" "tests\\"'), self.windows_line())
        self.assertEqual(self.run_tests._cmd_quote(r"a\b\\"), r'"a\b\\\\"', "only the trailing run is doubled")

    def test_a_quoted_windows_python_path_is_passed_verbatim(self):
        python = r'"C:\Program Files\Python314\python.exe"'
        with mock.patch.dict("os.environ", {self.run_tests.WINDOWS_PYTHON_ENV: python}):
            self.run_main("--windows")
        self.assertIn(f" && {python} scripts\\run_tests.py ", self.windows_line())

    def test_windows_unreachable_from_wsl_fails_with_a_clear_message(self):
        """No cmd.exe on PATH (interop off), a failed wslpath, or cmd.exe failing to start: exit 2 and a message,
        not a traceback; under --all the WSL run is stopped at once, not waited for."""
        unreachable = self.run_tests.WindowsUnreachable("cmd.exe is not on PATH")
        for flag in ("--windows", "--all"):
            with mock.patch.object(self.run_tests, "_windows_invocation", side_effect=unreachable):
                code, _, err = self.run_main(flag)
            self.assertEqual(code, 2, flag)
            self.assertIn("cmd.exe is not on PATH", err)
            self.assertIn("WSL interop", err)
        self.assertEqual(self.calls, [], "nothing started")
        self.windows_raises = FileNotFoundError(2, "No such file or directory", "cmd.exe")
        for flag in ("--windows", "--all"):
            with mock.patch.object(self.run_tests, "_kill_relays") as kill:
                code, _, err = self.run_main(flag)
            self.assertEqual(code, 2, flag)
            self.assertIn("No such file or directory", err)
            self.assertEqual(kill.called, flag == "--all", flag)

    def test_windows_path_and_cmd_exe_failures_become_windows_unreachable(self):
        failed = subprocess.CalledProcessError(1, ["wslpath"], stderr="bad path")
        with mock.patch.object(self.run_tests.subprocess, "run", side_effect=failed), \
                self.assertRaises(self.run_tests.WindowsUnreachable):
            self.run_tests._windows_path(Path("/home/me/wow-tools"))
        with mock.patch.object(self.run_tests.shutil, "which", return_value=None), \
                self.assertRaises(self.run_tests.WindowsUnreachable):
            self.run_tests._require_cmd_exe()

    def test_a_missing_windows_python_says_how_to_fix_it(self):
        self.windows_starts = False
        for flag in ("--windows", "--all"):
            code, _, err = self.run_main(flag)
            self.assertEqual(code, 1, flag)
            self.assertIn(self.run_tests.WINDOWS_PYTHON_ENV, err)
        self.windows_starts, self.codes["windows"] = True, 1
        self.assertNotIn(self.run_tests.WINDOWS_PYTHON_ENV, self.run_main("--windows")[2], "a run that failed")

    def test_windows_and_all_on_linux_that_is_not_wsl_fail_with_a_clear_message(self):
        for flag in ("--windows", "--all"):
            code, _, err = self.run_main(flag, host="linux")
            self.assertEqual(code, 2, flag)
            self.assertIn("WSL", err)
        self.assertEqual(self.calls, [])

    def test_windows_on_native_windows_is_the_normal_run(self):
        seen = []

        def fake_launch(ids, timeout):
            seen.append(ids)
            return 0, {"run": 1, "failures": 0, "errors": 0, "skipped": 0}, "", None, 0.1

        with mock.patch.object(self.run_tests, "_launch", side_effect=fake_launch):
            code, out, _ = self.run_main("--windows", "-j", "2", "-k", "test_", host="windows")
        self.assertEqual(code, 0)
        self.run_tests._discover_ids.assert_called_once_with("test_")
        self.assertEqual(sorted(seen), [["tests.test_x.T.test_a"], ["tests.test_x.T.test_b"]])
        self.assertEqual(self.calls, [])
        self.assertTrue(out.rstrip().endswith("OK"))

    def test_all_runs_both_suites_on_half_the_default_shards_each_with_labelled_summaries(self):
        with mock.patch.object(self.run_tests.os, "cpu_count", return_value=16):
            code, out, _ = self.run_main("--all", "-k", "tree")
        self.assertEqual(code, 0)
        wsl, = [c for c in self.calls if not c["windows"]]
        self.assertEqual(wsl["command"][-4:], ["-j", "12", "-k", "tree"], "16 CPUs: 24 shards, 12 a side (F3)")
        self.assertNotIn("--all", wsl["command"])
        self.assertIn('"-j" "12" "-k" "tree"', self.windows_line())
        self.assertIn("===== WSL", out)
        self.assertIn("===== Windows", out)
        self.assertLess(out.index("wsl output"), out.index("===== Windows"))
        self.assertIn("WSL: OK", out)
        self.assertIn("Windows: OK", out)
        self.assertTrue(out.rstrip().endswith("OK"))

    def test_all_with_jobs_gives_each_suite_that_many_shards(self):
        self.run_main("--all", "-j", "5")
        self.assertEqual(len(self.calls), 2)
        wsl, = [c for c in self.calls if not c["windows"]]
        self.assertEqual(wsl["command"][-2:], ["-j", "5"])
        self.assertIn('"-j" "5"', self.windows_line())

    def test_all_fails_if_either_suite_fails(self):
        for failing in ("wsl", "windows"):
            self.calls.clear()
            self.codes = {"wsl": 0, "windows": 0, failing: 1}
            code, out, _ = self.run_main("--all")
            self.assertEqual(code, 1, failing)
            self.assertIn(("WSL" if failing == "wsl" else "Windows") + ": FAILED", out)
            self.assertTrue(out.rstrip().endswith("FAILED"), out)

    def test_ctrl_c_during_windows_or_all_kills_the_runs(self):
        def interrupted(*_args):
            raise KeyboardInterrupt

        for flag in ("--windows", "--all"):
            with mock.patch.object(self.run_tests, "host_kind", return_value="wsl"), \
                    mock.patch.object(self.run_tests, "_windows_path", return_value=r"D:\x"), \
                    mock.patch.object(self.run_tests, "_require_cmd_exe"), \
                    mock.patch.object(self.run_tests, "_relay", side_effect=interrupted), \
                    mock.patch.object(self.run_tests, "_kill_relays") as kill, redirect_stdout(io.StringIO()), \
                    self.assertRaises(KeyboardInterrupt):
                self.run_tests.main([flag])
            kill.assert_called()

    def test_cmd_exe_starts_on_a_windows_drive(self):
        cwd = self.run_tests._windows_cwd
        self.assertEqual(cwd(Path("/mnt/d/GIT/wow-tools")), Path("/mnt/d/GIT/wow-tools"))
        self.assertEqual(cwd(Path("/home/me/wow-tools")), Path("/mnt/c"))

    def test_host_kind(self):
        kind = self.run_tests.host_kind
        self.assertEqual(kind(os_name="nt", osrelease=""), "windows")
        self.assertEqual(kind(os_name="posix", osrelease="6.6.87.2-microsoft-standard-WSL2"), "wsl")
        self.assertEqual(kind(os_name="posix", osrelease="6.8.0-45-generic"), "linux")

    def test_relay_streams_output_and_hides_the_pid_line(self):
        """The real _relay on a plain Python child (not cmd.exe): the runner's pid line is kept for Ctrl+C, every
        other line reaches the sink, and the child's exit code comes back."""
        script = (f"print({self.run_tests.PID_PREFIX!r} + '4242', flush=True)\n"
                  "print('line one', flush=True)\n"
                  "import sys; print('line two', file=sys.stderr, flush=True); sys.exit(4)\n")
        lines = []
        code = self.run_tests._relay([sys.executable, "-c", script], REPO_ROOT, None, lines.append, False)
        self.assertEqual(code, 4)
        self.assertEqual([line.rstrip() for line in lines], ["line one", "line two"])

    def test_kill_relays_kills_each_run_its_own_way(self):
        """The real _kill_relays: a Windows runner whose pid is known goes with taskkill.exe /T /F; one whose pid
        line has not arrived yet is waited for (its relay thread is still reading) and then killed the same way;
        one that never announces is given up on; a WSL runner gets SIGINT. Each WSL-side process is then killed."""
        relays = self.run_tests._RELAYS

        def fake_proc(running=True):
            proc = mock.Mock()
            proc.poll.return_value = None if running else 0
            return proc

        def info(windows, pid=None):
            entry = {"windows": windows, "pid": pid, "announced": threading.Event()}
            if pid:
                entry["announced"].set()
            return entry

        known, late, silent, gone, wsl = (fake_proc(), fake_proc(), fake_proc(), fake_proc(False), fake_proc())
        late_info = info(True)
        entries = {known: info(True, "77"), late: late_info, silent: info(True), gone: info(True),
                   wsl: info(False)}

        def announce():
            late_info["pid"] = "88"
            late_info["announced"].set()

        timer = threading.Timer(0.2, announce)
        with mock.patch.dict(relays, entries, clear=True), mock.patch.object(self.run_tests, "PID_WAIT", 1), \
                mock.patch.object(self.run_tests.subprocess, "run") as run, \
                mock.patch.object(self.run_tests, "_kill_tree") as kill_tree:
            timer.start()
            self.run_tests._kill_relays()
        timer.join()
        taskkilled = [call.args[0] for call in run.call_args_list]
        self.assertEqual(taskkilled, [["taskkill.exe", "/T", "/F", "/PID", "77"],
                                      ["taskkill.exe", "/T", "/F", "/PID", "88"]])
        wsl.send_signal.assert_called_once_with(signal.SIGINT)
        for proc in (known, late, silent, gone):
            proc.send_signal.assert_not_called()
        self.assertEqual({call.args[0] for call in kill_tree.call_args_list}, {known, late, silent, gone, wsl})

    def test_relay_stops_waiting_for_a_pid_once_its_run_ends(self):
        """A run that ends without announcing (say, no Windows Python) must not keep a later Ctrl+C waiting."""
        lines, infos = [], []

        def sink(line):
            lines.append(line)
            infos.extend(self.run_tests._RELAYS.values())

        self.run_tests._relay([sys.executable, "-c", "print('no pid')"], REPO_ROOT, None, sink, True)
        self.assertEqual([line.rstrip() for line in lines], ["no pid"])
        (info,) = infos
        self.assertIsNone(info["pid"])
        self.assertTrue(info["announced"].is_set())
        self.assertEqual(self.run_tests._RELAYS, {})
