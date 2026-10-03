"""scripts/build_release.py (the zip + SHA256SUMS assets the updater verifies) and the hashed vendor lock in
scripts/update_vendor.py (F-010). Temp git repos only; no network."""
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from wowtools.core import updater
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.updater import ReleaseInfo, UpdateError, apply_update

HAS_GIT = shutil.which("git") is not None


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
