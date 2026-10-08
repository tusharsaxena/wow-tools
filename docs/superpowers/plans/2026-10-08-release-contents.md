# Release contents: plan

Spec: `../specs/2026-10-08-release-contents-design.md`. Ledger: `2026-10-08-release-contents.status.md`.

| Task | What |
|---|---|
| P0 | the guidelines section in `docs/releasing.md`, spec, plan, ledger |
| P1 | `.gitattributes` export-ignore + archive manifest test + link check + README "Developing" removed + STD-11 rule |
| P2 | updater managed lists match the manifest; a zip update from a full-repo zip to a trimmed one removes dropped dev files cleanly (tests first) |
| PR | review, green gate, push, CI; then ask the user for the merge go-ahead |
