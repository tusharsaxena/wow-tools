# Saved Variables Browser feedback round 1: plan

Spec: `../specs/2026-10-06-sv-browser-design.md`, Addendum B (D37-D41). Ledger:
`2026-10-07-sv-browser-feedback-1.status.md`. Branch: `feat/sv-browser` (not merged yet). Same rules as the main
plan: tests first, full suite green, one commit per task, ledger updated, push after the round, no merge without the
user's go-ahead.

- **F1** Header (D41) and the shared risk banner (D37) on the four destructive screens.
- **F2** Filter on submit for every tool (D40): shared `TreeFilter`/`FilterBox`, Filter button, hints, tests in
  `tests/test_look_and_feel.py` for every tree screen.
- **F3** Search find-only + spacing (D38); bulk Edit value / Rename key on ticked results into staging (D39); Apply
  writes staged edits only.
- **F4** Help, guides (`docs/sv-browser.md`, other guides for D37/D40), README, CHANGELOG, architecture; review
  workflow, fixes, push.
