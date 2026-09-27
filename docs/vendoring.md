# Vendored libraries

Third-party code lives in `vendor/` and is committed, so the tools run without pip or a virtualenv.
`wowtools/__main__.py` (and `tests/__init__.py`) put `vendor/` first on `sys.path`.

Rules:
- **Pure Python only.** The same folder must work on Windows, Linux and WSL. `scripts/update_vendor.py`
  fails if a `.so`, `.pyd`, `.dll` or `.dylib` is installed.
- **Pin everything**, including transitive dependencies, in `requirements.txt`. The script installs with
  `--no-deps`, so the list must be complete.
- Python floor is 3.10. Check each package's `Requires-Python`.

Updating or adding a library:
1. Edit `requirements.txt` (bump pins, or add the package *and* its dependencies. Find them with
   `pip install --dry-run --report - <pkg>` or by installing it into a scratch folder with `--target`).
2. Run `python3 scripts/update_vendor.py`.
3. Run the full test suite, then commit `requirements.txt` and `vendor/` together.
