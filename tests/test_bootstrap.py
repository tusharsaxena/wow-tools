from __future__ import annotations

import sys
import unittest

from wowtools.core import bootstrap


class CheckPythonTest(unittest.TestCase):
    def test_rejects_old_python(self):
        message = bootstrap.check_python((3, 9, 18))
        self.assertIn("3.10", message)
        self.assertIn("3.9", message)

    def test_accepts_supported_python(self):
        self.assertIsNone(bootstrap.check_python((3, 10, 0)))
        self.assertIsNone(bootstrap.check_python((3, 13, 1)))


class VendorPathTest(unittest.TestCase):
    def test_paths_are_anchored_to_the_repo_not_the_cwd(self):
        self.assertEqual(bootstrap.VENDOR_DIR, bootstrap.REPO_ROOT / "vendor")
        self.assertTrue((bootstrap.REPO_ROOT / "wowtools" / "__init__.py").is_file())

    def test_add_vendor_path_is_idempotent(self):
        bootstrap.add_vendor_path()
        bootstrap.add_vendor_path()
        self.assertEqual(sys.path.count(str(bootstrap.VENDOR_DIR)), 1)

    def test_textual_imports_from_vendor(self):
        import textual

        self.assertTrue(str(textual.__file__).startswith(str(bootstrap.VENDOR_DIR)))
