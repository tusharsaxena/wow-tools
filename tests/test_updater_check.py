import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.updater import (ReleaseInfo, UpdateError, check_for_update, fetch_latest,
                                   is_newer, parse_version)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def opener_for(payload):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return lambda request, timeout: Response(json.dumps(payload).encode("utf-8"))


class VersionTest(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        with self.assertRaises(ValueError):
            parse_version("1.2")
        self.assertTrue(is_newer("0.2.0", "0.1.9"))
        self.assertTrue(is_newer("0.10.0", "0.9.0"))
        self.assertFalse(is_newer("0.1.0", "0.1.0"))
        self.assertFalse(is_newer("garbage", "0.1.0"))


class FetchTest(unittest.TestCase):
    def test_parses_release(self):
        release = fetch_latest(opener=opener_for({
            "tag_name": "v0.2.0", "body": "Notes", "draft": False, "prerelease": False,
            "zipball_url": "https://api.github.com/zip", "html_url": "https://github.com/r"}))
        self.assertEqual((release.version, release.tag, release.notes), ("0.2.0", "v0.2.0", "Notes"))

    def test_404_means_no_release(self):
        def not_found(request, timeout):
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        self.assertIsNone(fetch_latest(opener=not_found))

    def test_prerelease_ignored(self):
        self.assertIsNone(fetch_latest(opener=opener_for({"tag_name": "v9.0.0", "prerelease": True})))


class CheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = Config(self.tmp / "c.cfg")
        self.cfg.save()

    def test_newer_release_is_returned_and_cached(self):
        with capture_events() as records:
            release = check_for_update(self.cfg, current="0.1.0", now=NOW,
                                       fetch=lambda: ReleaseInfo.from_version("0.2.0"))
        self.assertEqual(release.version, "0.2.0")
        saved = Config(self.cfg.path).load()
        self.assertEqual(saved.latest_seen_version, "0.2.0")
        self.assertEqual(saved.last_update_check, NOW)
        self.assertIn("update.available", [r["event"] for r in records])
        self.assertNotIn("config.changed", [r["event"] for r in records])

    def test_throttled_within_24h_uses_cache(self):
        check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=lambda: ReleaseInfo.from_version("0.2.0"))
        never = Mock(side_effect=AssertionError("must not fetch while throttled"))
        cached = check_for_update(self.cfg, current="0.1.0", now=NOW + timedelta(hours=12), fetch=never)
        self.assertEqual(cached.version, "0.2.0")
        later = Mock(return_value=ReleaseInfo.from_version("0.3.0"))
        self.assertEqual(check_for_update(self.cfg, current="0.1.0", now=NOW + timedelta(hours=25),
                                          fetch=later).version, "0.3.0")
        later.assert_called_once()

    def test_force_ignores_throttle(self):
        check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=lambda: None)
        fetch = Mock(return_value=ReleaseInfo.from_version("0.2.0"))
        self.assertIsNotNone(check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=fetch, force=True))

    def test_same_version_returns_none(self):
        self.assertIsNone(check_for_update(self.cfg, current="0.2.0", now=NOW,
                                           fetch=lambda: ReleaseInfo.from_version("0.2.0")))

    def test_failure_is_silent_unless_asked(self):
        def offline():
            raise urllib.error.URLError("offline")
        with capture_events() as records:
            self.assertIsNone(check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=offline))
        self.assertIn("update.check_failed", [r["event"] for r in records])
        with self.assertRaises(UpdateError):
            check_for_update(self.cfg, current="0.1.0", now=NOW, fetch=offline, force=True, raise_errors=True)

    def test_does_not_create_config_before_setup(self):
        fresh = Config(self.tmp / "new.cfg")
        check_for_update(fresh, current="0.1.0", now=NOW, fetch=lambda: ReleaseInfo.from_version("0.2.0"))
        self.assertFalse(fresh.path.exists())
