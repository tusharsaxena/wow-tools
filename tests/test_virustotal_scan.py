"""scripts/virustotal_scan.py (the VirusTotal scan of a published release) and .github/workflows/virustotal.yml.

A fake opener stands in for VirusTotal and a fake clock for time (STD-10.4): no test touches the network, needs a
real API key or waits."""
from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from itertools import pairwise
from pathlib import Path

from tests.test_release_scripts import load_script
from wowtools.core.bootstrap import REPO_ROOT

KEY = "test-key-0123456789abcdef"
STATS = {"malicious": 0, "suspicious": 0, "undetected": 60, "harmless": 12, "timeout": 1, "type-unsupported": 3}


class FakeResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeVirusTotal:
    """Answers each request with the next scripted reply: a dict (JSON, HTTP 200) or an int (that HTTP error).
    Records every request with the fake time it was made at."""

    def __init__(self, replies: list, clock: FakeClock):
        self.replies = list(replies)
        self.clock = clock
        self.requests: list[tuple[float, str, str, dict, bytes | None]] = []

    def __call__(self, request, timeout=None):
        headers = {name.lower(): value for name, value in request.header_items()}
        self.requests.append((self.clock.now, request.get_method(), request.full_url, headers, request.data))
        if not self.replies:
            raise AssertionError(f"unexpected request {request.get_method()} {request.full_url}")
        reply = self.replies.pop(0)
        if isinstance(reply, int):
            body = io.BytesIO(json.dumps({"error": {"code": "Err", "message": "scripted"}}).encode("utf-8"))
            raise urllib.error.HTTPError(request.full_url, reply, "scripted", {}, body)
        return FakeResponse(reply)

    def calls(self) -> list[tuple[str, str]]:
        return [(method, url.rsplit("/api/v3", 1)[1]) for _, method, url, _, _ in self.requests]


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def file_report(stats: dict) -> dict:
    return {"data": {"attributes": {"last_analysis_date": 1760000000, "last_analysis_stats": stats,
                                    "last_analysis_results": {"EngineA": {"category": "undetected"}}}}}


def analysis(status: str, stats: dict | None = None, sha256: str | None = None) -> dict:
    reply = {"data": {"id": "an-1", "attributes": {"status": status, "stats": stats or {}}}}
    if sha256:
        reply["meta"] = {"file_info": {"sha256": sha256}}
    return reply


class VirusTotalScanTest(unittest.TestCase):
    def setUp(self):
        self.vt = load_script("virustotal_scan")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.zip = self.dir / "wow-tools-v1.2.3.zip"
        self.zip.write_bytes(b"PK\x05\x06" + b"\0" * 18)
        self.sha = hashlib.sha256(self.zip.read_bytes()).hexdigest()
        self.notes = self.dir / "notes.md"
        self.clock = FakeClock()

    def run_main(self, replies: list, *argv: str, env: dict | None = None) -> tuple[int, str, str, FakeVirusTotal]:
        fake = FakeVirusTotal(replies, self.clock)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.vt.main([str(self.zip), *argv], env={"VT_API_KEY": KEY} if env is None else env,
                                opener=fake, clock=self.clock, sleep=self.clock.sleep)
        self.assertNotIn(KEY, out.getvalue() + err.getvalue(), "the API key is never printed")
        return code, out.getvalue(), err.getvalue(), fake

    def test_an_existing_finished_report_is_used_without_an_upload(self):
        code, out, _, fake = self.run_main([file_report(STATS)])
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls(), [("GET", f"/files/{self.sha}")])
        self.assertEqual(fake.requests[0][3]["x-apikey"], KEY)
        self.assertIn("0 of 72 engines flagged", out)
        self.assertIn("malicious 0, suspicious 0, undetected 60, harmless 12 (72 engines)", out)
        self.assertIn(f"https://www.virustotal.com/gui/file/{self.sha}", out)

    def test_a_report_without_a_finished_analysis_is_uploaded(self):
        unfinished = {"data": {"attributes": {"last_analysis_stats": {}, "last_analysis_results": {}}}}
        code, _, _, fake = self.run_main([unfinished, {"data": {"id": "an-1"}}, analysis("completed", STATS)])
        self.assertEqual(code, 0)
        self.assertEqual([method for method, _ in fake.calls()], ["GET", "POST", "GET"])

    def test_upload_then_polls_until_completed_15_s_apart(self):
        replies = [404, {"data": {"id": "an-1"}}, analysis("queued"), analysis("completed", STATS, self.sha)]
        code, out, _, fake = self.run_main(replies)
        self.assertEqual(code, 0, out)
        self.assertEqual(fake.calls(), [("GET", f"/files/{self.sha}"), ("POST", "/files"),
                                        ("GET", "/analyses/an-1"), ("GET", "/analyses/an-1")])
        times = [stamp for stamp, *_ in fake.requests]
        self.assertTrue(all(b - a >= 15 for a, b in pairwise(times)), times)
        _, _, _, headers, body = fake.requests[1]
        boundary = re.fullmatch(r"multipart/form-data; boundary=(\S+)", headers["content-type"]).group(1)
        self.assertTrue(body.startswith(f"--{boundary}\r\n".encode()))
        self.assertIn(b'name="file"; filename="wow-tools-v1.2.3.zip"', body)
        self.assertIn(self.zip.read_bytes(), body)
        self.assertTrue(body.endswith(f"\r\n--{boundary}--\r\n".encode()))
        self.assertIn("0 of 72 engines flagged", out)

    def test_a_429_backs_off_and_retries(self):
        code, _, err, fake = self.run_main([429, file_report(STATS)])
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.requests), 2)
        self.assertIn(60.0, self.clock.slept)
        self.assertIn("rate limited", err)

    def test_a_refused_key_is_an_error(self):
        for status in (401, 403):
            with self.subTest(status=status):
                code, _, err, _ = self.run_main([status])
                self.assertEqual(code, 1)
                self.assertIn(f"refused the API key (HTTP {status})", err)
                self.assertNotIn("Traceback", err)

    def test_a_413_is_an_error(self):
        code, _, err, _ = self.run_main([404, 413])
        self.assertEqual(code, 1)
        self.assertIn("too large (HTTP 413)", err)

    def test_another_http_error_is_an_error(self):
        code, _, err, _ = self.run_main([500])
        self.assertEqual(code, 1)
        self.assertIn("HTTP 500 (Err: scripted)", err)

    def test_a_missing_key_is_an_error_without_a_traceback_or_a_request(self):
        for env in ({}, {"VT_API_KEY": "  "}):
            with self.subTest(env=env):
                code, _, err, fake = self.run_main([], env=env)
                self.assertEqual(code, 2)
                self.assertIn("VT_API_KEY is not set", err)
                self.assertNotIn("Traceback", err)
                self.assertEqual(fake.requests, [])

    def test_a_file_over_32_mb_is_not_uploaded(self):
        with self.zip.open("r+b") as handle:
            handle.truncate(32 * 1024 * 1024 + 1)
        code, _, err, fake = self.run_main([404])
        self.assertEqual(code, 1)
        self.assertIn("over the 32 MB upload limit", err)
        self.assertEqual([method for method, _ in fake.calls()], ["GET"])

    def test_the_notes_block_is_appended_then_replaced(self):
        self.notes.write_text("Release notes.\n\n- One.\n", encoding="utf-8")
        self.assertEqual(self.run_main([file_report(STATS)], "--notes-file", str(self.notes))[0], 0)
        first = self.notes.read_text(encoding="utf-8")
        url = f"https://www.virustotal.com/gui/file/{self.sha}"
        self.assertEqual(first, "Release notes.\n\n- One.\n\n<!-- virustotal -->\n"
                                f"VirusTotal: 0 of 72 engines flagged this zip ([report]({url})).\n"
                                "<!-- /virustotal -->\n")
        self.assertEqual(self.run_main([file_report(STATS)], "--notes-file", str(self.notes))[0], 0)
        self.assertEqual(self.notes.read_text(encoding="utf-8"), first, "a second run changes nothing")
        flagged = dict(STATS, malicious=1, undetected=59)
        self.assertEqual(self.run_main([file_report(flagged)], "--notes-file", str(self.notes))[0], 0)
        third = self.notes.read_text(encoding="utf-8")
        self.assertEqual(third.count("<!-- virustotal -->"), 1)
        self.assertTrue(third.startswith("Release notes.\n\n- One.\n\n<!-- virustotal -->\n"))
        self.assertIn("1 of 72 engines flagged this zip", third)

    def test_an_empty_or_missing_notes_file_gets_just_the_block(self):
        self.assertEqual(self.run_main([file_report(STATS)], "--notes-file", str(self.notes))[0], 0)
        text = self.notes.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!-- virustotal -->\nVirusTotal: 0 of 72"))

    def test_detections_are_explained_and_still_exit_0(self):
        flagged = dict(STATS, malicious=1, suspicious=1, undetected=58)
        code, out, _, _ = self.run_main([file_report(flagged)], "--notes-file", str(self.notes))
        self.assertEqual(code, 0)
        self.assertIn("2 of 72 engines flagged", out)
        text = self.notes.read_text(encoding="utf-8")
        self.assertIn("2 engines flagged it; heuristic hits on bundled libraries and launchers are a known false "
                      "positive.", text)
        one = self.vt.notes_block(self.vt.ScanResult(self.sha, dict(STATS, malicious=1)))
        self.assertIn("\n1 engine flagged it;", one)
        self.assertNotIn("false positive", self.vt.notes_block(self.vt.ScanResult(self.sha, STATS)))

    def test_an_analysis_that_never_completes_times_out(self):
        replies = [404, {"data": {"id": "an-1"}}] + [analysis("in-progress")] * 10
        self.notes.write_text("Notes.\n", encoding="utf-8")
        code, _, err, fake = self.run_main(replies, "--timeout", "100", "--notes-file", str(self.notes))
        self.assertEqual(code, 1)
        self.assertIn("did not finish within 100 s", err)
        self.assertLessEqual(self.clock.now - 1000.0, 100)
        self.assertLessEqual(len(fake.requests), 7)
        self.assertEqual(self.notes.read_text(encoding="utf-8"), "Notes.\n", "a failed scan leaves the notes alone")

    def test_a_completed_analysis_of_another_file_is_an_error(self):
        replies = [404, {"data": {"id": "an-1"}}, analysis("completed", STATS, "0" * 64)]
        code, _, err, _ = self.run_main(replies)
        self.assertEqual(code, 1)
        self.assertIn("analysed 000", err)


class VirusTotalWorkflowTest(unittest.TestCase):
    """.github/workflows/virustotal.yml: only on a published release or by hand, write access only to the release,
    the key from the Actions secret, and the zip checked against SHA256SUMS before it is scanned."""

    def setUp(self):
        self.workflow = (REPO_ROOT / ".github" / "workflows" / "virustotal.yml").read_text(encoding="utf-8")

    def test_it_runs_only_on_a_published_release_or_by_hand(self):
        on = self.workflow.split("\non:\n", 1)[1].split("\n\n", 1)[0]
        triggers = re.findall(r"^  (\w+):", on, re.MULTILINE)
        self.assertEqual(triggers, ["release", "workflow_dispatch"])
        self.assertIn("types: [published]", on)
        self.assertRegex(on, r"inputs:\n\s+tag:")
        self.assertNotRegex(self.workflow, r"^\s*(push|pull_request|schedule):", "never on a push")

    def test_permissions_are_contents_write_only(self):
        permissions = self.workflow.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(permissions.strip(), "contents: write")
        self.assertEqual(self.workflow.count("permissions:"), 1)

    def test_the_key_comes_from_the_secret_and_is_checked(self):
        self.assertIn("VT_API_KEY: ${{ secrets.VT_API_KEY }}", self.workflow)
        self.assertIn('if [ -z "$VT_API_KEY" ]', self.workflow)
        self.assertNotRegex(self.workflow, r"echo[^\n]*\$\{?VT_API_KEY", "the key is never echoed")

    def test_the_zip_is_verified_before_it_is_scanned_and_the_notes_edited_after(self):
        steps = ["gh release download", "sha256sum -c SHA256SUMS", 'gh release view "$TAG" --json body',
                 "scripts/virustotal_scan.py", "--notes-file notes.md", 'gh release edit "$TAG" --notes-file notes.md']
        positions = [self.workflow.find(step) for step in steps]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        self.assertIn("-p 'wow-tools-*.zip' -p SHA256SUMS", self.workflow)
        self.assertIn("timeout-minutes: 20", self.workflow)
