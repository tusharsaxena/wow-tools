from __future__ import annotations

import unittest
from unittest.mock import patch

from wowtools.core import lock


class PlatformTest(unittest.TestCase):
    """The lock records the platform with the same WSL check the rest of the suite uses (paths.is_wsl)."""

    def test_platform_uses_is_wsl(self):
        with patch("wowtools.core.lock.is_wsl", return_value=True, create=True), \
                patch("platform.release", return_value="6.6-generic"), \
                patch("platform.system", return_value="Linux"):
            self.assertEqual(lock._platform(), "wsl")

    def test_kernel_name_alone_does_not_mean_wsl(self):
        with patch("wowtools.core.lock.is_wsl", return_value=False, create=True), \
                patch("platform.release", return_value="5.15.90.1-microsoft-standard-WSL2"), \
                patch("platform.system", return_value="Linux"):
            self.assertEqual(lock._platform(), "linux")

    def test_other_systems(self):
        with patch("wowtools.core.lock.is_wsl", return_value=False, create=True), \
                patch("platform.system", return_value="Windows"):
            self.assertEqual(lock._platform(), "windows")
