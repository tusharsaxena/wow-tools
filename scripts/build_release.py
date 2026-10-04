#!/usr/bin/env python3
"""Build a release's two assets from its tag: dist/wow-tools-vX.Y.Z.zip and dist/SHA256SUMS.

Zip installs update only from these (the updater checks the zip against SHA256SUMS). See docs/releasing.md.
Run from anywhere: python3 scripts/build_release.py [X.Y.Z] [--out DIR]   (the version defaults to the one in
wowtools/__init__.py; the tag vX.Y.Z must exist)."""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMS_NAME = "SHA256SUMS"
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def zip_name(version: str) -> str:
    return f"wow-tools-v{version}.zip"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def build(repo: Path, version: str, out_dir: Path) -> tuple[Path, Path]:
    """git archive the tag vX.Y.Z into out_dir/wow-tools-vX.Y.Z.zip (one top folder, like GitHub's source zip)
    and write out_dir/SHA256SUMS for it. Exits with a message if the tag is missing or holds another version."""
    tag = f"v{version}"
    if _git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode != 0:
        raise SystemExit(f"tag {tag} not found. Tag the release first: git tag {tag}")
    shown = _git(repo, "show", f"{tag}:wowtools/__init__.py")
    match = _VERSION_RE.search(shown.stdout) if shown.returncode == 0 else None
    if not match or match.group(1) != version:
        found = match.group(1) if match else "no version"
        raise SystemExit(f"tag {tag} holds {found} in wowtools/__init__.py, not {version}")
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / zip_name(version)
    archived = _git(repo, "archive", "--format=zip", f"--prefix=wow-tools-{tag}/", "-o", str(zip_path), tag)
    if archived.returncode != 0:
        raise SystemExit(f"git archive failed: {archived.stderr.strip()}")
    with zipfile.ZipFile(zip_path) as zf:
        if zf.testzip() is not None:
            raise SystemExit(f"{zip_path} is damaged")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sums_path = out_dir / SUMS_NAME
    sums_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8", newline="\n")
    return zip_path, sums_path


def _current_version() -> str:
    match = _VERSION_RE.search((ROOT / "wowtools" / "__init__.py").read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("no __version__ in wowtools/__init__.py")
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the release zip and SHA256SUMS from the tag.")
    parser.add_argument("version", nargs="?", help="X.Y.Z (default: wowtools/__init__.py)")
    parser.add_argument("--out", type=Path, default=ROOT / "dist", help="output folder (default: dist/)")
    args = parser.parse_args(argv)
    version = args.version or _current_version()
    zip_path, sums_path = build(ROOT, version, args.out)
    print(f"Built {zip_path}\n      {sums_path}\n")
    print("Publish both assets with the release:")
    print(f'  gh release create v{version} "{zip_path}" "{sums_path}" '
          f'--title "Ka0s WoW Tools v{version}" --notes "..."')
    return 0


if __name__ == "__main__":
    sys.exit(main())
