# wow-tools: notes for Claude

Out-of-game WoW companion tools (Ka0s branded). First tool: WTF Cleaner. Spec and plan: `docs/superpowers/`.

- Tests: `python3 -m unittest discover -s tests -t . -v`
- Run: `python3 -m wowtools [wtf-cleaner|update] [args]` (no args opens the tool menu)
- Rebuild vendored libs: `python3 scripts/update_vendor.py`. Event docs: `python3 scripts/gen_event_docs.py`

Conventions:
- Python 3.10 floor; `from __future__ import annotations` in every module; stdlib + `vendor/` only.
- `wowtools/core/*` and tool logic modules never import `textual`. Front ends are thin.
- Config paths go through `core/paths.py` (stored in Windows form); config lives in the repo root.
- Every log event is registered with a fixed level (`core/events.py` or `<tool>/events.py`); regenerate
  `docs/events.md` after changing any registry.
- Textual apps subclass `Ka0sApp` and override `after_mount()`, not `on_mount()`.
- Tests use `tests/fixtures.py` temp trees; never a real WoW install, never the network.
- Adding a tool: `docs/adding-a-tool.md`.
