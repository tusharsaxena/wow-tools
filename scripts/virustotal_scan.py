#!/usr/bin/env python3
"""Scan a release zip on VirusTotal and, with --notes-file, write the result into the release notes.

Run: VT_API_KEY=... python3 scripts/virustotal_scan.py ZIP [--notes-file F] [--timeout S]
The key is read only from the VT_API_KEY environment variable and is never printed. It looks up the zip's SHA-256
first (a finished report is reused), else uploads it (32 MB at most) and polls the analysis until it completes,
waiting at least 15 s between requests (the free tier allows 4 a minute). Exit 0 on a completed scan, detections
or not (a person reads the report); 1 on an API or HTTP error or a timeout; 2 on a usage error. Stdlib only. The
release workflow .github/workflows/virustotal.yml runs it on each published release; see docs/releasing.md."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from collections.abc import Callable

API = "https://www.virustotal.com/api/v3"
REPORT_URL = "https://www.virustotal.com/gui/file/{sha256}"
KEY_ENV = "VT_API_KEY"
MAX_UPLOAD = 32 * 1024 * 1024  # the plain /files upload; bigger files need an upload URL, which a release never needs
REQUEST_GAP = 15.0  # seconds between requests: the free tier's 4 requests a minute
RATE_LIMIT_WAIT = 60.0  # after an HTTP 429, wait out the whole minute
RATE_LIMIT_RETRIES = 5  # then give up: a daily quota does not come back within the timeout
DEFAULT_TIMEOUT = 900.0
HTTP_TIMEOUT = 120.0  # one request (the upload is the slow one)
NOTES_START = "<!-- virustotal -->"
NOTES_END = "<!-- /virustotal -->"
_BLOCK_RE = re.compile(re.escape(NOTES_START) + r".*?" + re.escape(NOTES_END), re.DOTALL)
VERDICTS = ("malicious", "suspicious", "undetected", "harmless")


class ScanError(Exception):
    """An API or HTTP error, or the scan did not finish in time; the message is safe to print (never the key)."""


class ScanResult:
    """A finished analysis: the file's SHA-256 and its verdict counts (malicious, suspicious, undetected ...)."""

    def __init__(self, sha256: str, stats: dict[str, int]) -> None:
        self.sha256 = sha256
        self.stats = stats

    @property
    def flagged(self) -> int:
        return self.stats.get("malicious", 0) + self.stats.get("suspicious", 0)

    @property
    def engines(self) -> int:
        """The engines that gave a verdict (not those that timed out or do not support the file type)."""
        return sum(self.stats.get(name, 0) for name in VERDICTS)

    @property
    def url(self) -> str:
        return REPORT_URL.format(sha256=self.sha256)


class Client:
    """The few VirusTotal v3 calls the scan needs. `opener(request, timeout=...)` is urllib.request.urlopen by
    default; tests pass a fake one, and a fake clock and sleep, so no test touches the network or waits."""

    def __init__(self, key: str, *, opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self._key = key
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._deadline = clock() + timeout
        self._timeout = timeout
        self._last: float | None = None

    def _wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self._clock() + seconds > self._deadline:
            raise ScanError(f"the scan did not finish within {self._timeout:g} s; rerun it later "
                            "(an upload already made is found by its SHA-256)")
        self._sleep(seconds)

    def _safe(self, text: str) -> str:
        return text.replace(self._key, "***") if self._key else text

    def request(self, method: str, path: str, *, body: bytes | None = None,
                content_type: str | None = None, missing_ok: bool = False) -> dict | None:
        """The JSON reply of one call, spaced REQUEST_GAP after the previous one and retried after an HTTP 429.
        None for an HTTP 404 when missing_ok; ScanError for anything else that is not a 2xx."""
        headers = {"x-apikey": self._key, "accept": "application/json"}
        if content_type:
            headers["content-type"] = content_type
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            if self._last is not None:
                self._wait(self._last + REQUEST_GAP - self._clock())
            self._last = self._clock()
            req = urllib.request.Request(f"{API}{path}", data=body, headers=headers, method=method)
            try:
                with self._opener(req, timeout=HTTP_TIMEOUT) as response:
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < RATE_LIMIT_RETRIES:
                    print(f"rate limited (HTTP 429); waiting {RATE_LIMIT_WAIT:g} s", file=sys.stderr)
                    self._wait(RATE_LIMIT_WAIT)
                    continue
                if exc.code == 404 and missing_ok:
                    return None
                raise ScanError(self._safe(_http_message(method, path, exc))) from None
            except (urllib.error.URLError, OSError) as exc:
                raise ScanError(self._safe(f"{method} {path} failed: {exc}")) from None
            try:
                return json.loads(raw.decode("utf-8"))
            except ValueError:
                raise ScanError(f"{method} {path} did not return JSON") from None
        raise AssertionError("unreachable: the last attempt returns or raises")


def _http_message(method: str, path: str, exc: urllib.error.HTTPError) -> str:
    try:
        error = json.loads(exc.read().decode("utf-8")).get("error") or {}
        parts = [str(error[name]) for name in ("code", "message") if error.get(name)]
        detail = f" ({': '.join(parts)})" if parts else ""
    except (OSError, ValueError, AttributeError, TypeError):  # the body is only detail; the status is the message
        detail = ""
    detail = detail[:300]
    if exc.code in (401, 403):
        return (f"VirusTotal refused the API key (HTTP {exc.code}){detail}: check the {KEY_ENV} secret or "
                "variable holds a valid key")
    if exc.code == 413:
        return f"VirusTotal refused the upload as too large (HTTP 413){detail}"
    if exc.code == 429:
        return (f"still rate limited (HTTP 429) after {RATE_LIMIT_RETRIES} retries{detail}: the daily quota may "
                "be used up")
    return f"{method} {path} failed: HTTP {exc.code}{detail}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def multipart(field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    """A multipart/form-data body with one file field, and its content type."""
    boundary = f"----wowtools{secrets.token_hex(16)}"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/zip\r\n\r\n").encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + data + tail, f"multipart/form-data; boundary={boundary}"


def _stats(stats: dict) -> dict[str, int]:
    return {str(name): int(count) for name, count in stats.items() if isinstance(count, int)}


def existing_report(client: Client, sha256: str) -> ScanResult | None:
    """The file's last finished analysis, or None if VirusTotal has no report for it yet."""
    reply = client.request("GET", f"/files/{sha256}", missing_ok=True)
    attributes = ((reply or {}).get("data") or {}).get("attributes") or {}
    stats = attributes.get("last_analysis_stats")
    if not attributes.get("last_analysis_date") or not attributes.get("last_analysis_results") or not stats:
        return None
    return ScanResult(sha256, _stats(stats))


def scan(zip_path: Path, client: Client) -> ScanResult:
    """Reuse a finished report for the zip's SHA-256, else upload it and poll its analysis until completed."""
    size = zip_path.stat().st_size
    sha256 = sha256_of(zip_path)
    print(f"{zip_path.name}: {size} bytes, SHA-256 {sha256}")
    found = existing_report(client, sha256)
    if found is not None:
        print("VirusTotal already has a finished report for this file")
        return found
    if size > MAX_UPLOAD:
        raise ScanError(f"{zip_path.name} is {size} bytes, over the {MAX_UPLOAD // (1024 * 1024)} MB upload limit")
    body, content_type = multipart("file", zip_path.name, zip_path.read_bytes())
    reply = client.request("POST", "/files", body=body, content_type=content_type) or {}
    analysis_id = (reply.get("data") or {}).get("id")
    if not analysis_id:
        raise ScanError("the upload's reply has no analysis id")
    print("uploaded; waiting for the analysis")
    while True:
        reply = client.request("GET", f"/analyses/{analysis_id}") or {}
        data = reply.get("data") or {}
        attributes = data.get("attributes") or {}
        status = attributes.get("status")
        if status == "completed":
            scanned = ((reply.get("meta") or {}).get("file_info") or {}).get("sha256")
            if scanned and scanned != sha256:
                raise ScanError(f"VirusTotal analysed {scanned}, not {sha256}")
            return ScanResult(sha256, _stats(attributes.get("stats") or {}))
        print(f"analysis {status or 'pending'}")


def notes_block(result: ScanResult) -> str:
    lines = [f"VirusTotal: {result.flagged} of {result.engines} engines flagged this zip ([report]({result.url}))."]
    if result.flagged:
        engines = "engine" if result.flagged == 1 else "engines"
        lines.append(f"{result.flagged} {engines} flagged it; heuristic hits on bundled libraries and launchers are a "
                     "known false positive.")
    return "\n".join([NOTES_START, *lines, NOTES_END])


def update_notes(text: str, result: ScanResult) -> str:
    """The notes with their VirusTotal block replaced, or appended at the end if they have none."""
    block = notes_block(result)
    if _BLOCK_RE.search(text):
        return _BLOCK_RE.sub(lambda _match: block, text, count=1)
    text = text.rstrip()
    return f"{text}\n\n{block}\n" if text else f"{block}\n"


def main(argv: list[str] | None = None, *, env: dict | None = None, opener: Callable = urllib.request.urlopen,
         clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description="Scan a release zip on VirusTotal (the key from $VT_API_KEY).")
    parser.add_argument("zip", type=Path, help="the release zip, e.g. dist/wow-tools-vX.Y.Z.zip")
    parser.add_argument("--notes-file", type=Path, help="release notes to write the VirusTotal line into")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"give up after this many seconds (default {DEFAULT_TIMEOUT:g})")
    args = parser.parse_args(argv)
    key = (os.environ if env is None else env).get(KEY_ENV, "").strip()
    if not key:
        print(f"error: {KEY_ENV} is not set. Set it in your shell (never commit it); in CI it is the repository's "
              f"Actions secret {KEY_ENV}.", file=sys.stderr)
        return 2
    if not args.zip.is_file():
        print(f"error: {args.zip} is not a file", file=sys.stderr)
        return 2
    if args.notes_file is not None and args.notes_file.exists() and not args.notes_file.is_file():
        print(f"error: {args.notes_file} is not a file", file=sys.stderr)
        return 2
    client = Client(key, opener=opener, clock=clock, sleep=sleep, timeout=args.timeout)
    try:
        result = scan(args.zip, client)
    except ScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    counts = ", ".join(f"{name} {result.stats.get(name, 0)}" for name in VERDICTS)
    print(f"VirusTotal: {result.flagged} of {result.engines} engines flagged {args.zip.name}")
    print(f"  {counts} ({result.engines} engines)")
    print(f"  report: {result.url}")
    if args.notes_file is not None:
        old = args.notes_file.read_text(encoding="utf-8") if args.notes_file.exists() else ""
        args.notes_file.write_text(update_notes(old, result), encoding="utf-8", newline="\n")
        print(f"wrote the VirusTotal line into {args.notes_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
