#!/usr/bin/env python3
"""Rebuild vendor/ from requirements.txt. Run from anywhere: python3 scripts/update_vendor.py"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
NATIVE_SUFFIXES = {".so", ".pyd", ".dll", ".dylib"}


def main() -> int:
    if VENDOR.exists():
        shutil.rmtree(VENDOR)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--target", str(VENDOR), "--no-compile",
         "--no-deps", "--only-binary=:all:", "-r", str(ROOT / "requirements.txt")],
        check=True,
    )
    shutil.rmtree(VENDOR / "bin", ignore_errors=True)
    for cache in list(VENDOR.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
    native = [p for p in VENDOR.rglob("*") if p.suffix.lower() in NATIVE_SUFFIXES]
    if native:
        print("vendor/ must be pure Python, but native files were installed:", file=sys.stderr)
        for path in native:
            print(f"  {path}", file=sys.stderr)
        return 1
    print(f"vendor/ rebuilt from {ROOT / 'requirements.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
