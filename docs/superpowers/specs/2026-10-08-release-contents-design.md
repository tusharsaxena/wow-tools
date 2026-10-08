# Release contents: design

Date: 2026-10-08. Branch: `docs/release-guidelines`. Plan: `../plans/2026-10-08-release-contents.md`, ledger
`../plans/2026-10-08-release-contents.status.md`. The guidelines themselves are `docs/releasing.md`, section
"What a release contains" (drafted and reviewed with the user on 2026-10-08).

User brief 2026-10-08, preparing v1.0.0: everything wow-tools needs ships; developer documentation does not; user
documentation does.

## Decisions

| # | Topic | Decision |
|---|---|---|
| P1 | Rules | Anything the app or its launchers read at run time ships; user docs (README, the five guides, their images) ship; everything for developing the suite stays out. A file that fits no rule clearly stays out until the manifest names it. |
| P2 | Manifest | The "Ships" and "Stays out" tables in `docs/releasing.md` are the manifest. Ships: `wowtools/`, `vendor/`, `wow-tools.sh`, `wow-tools.cmd`, `LICENSE`, `CHANGELOG.md`, `README.md`, the five `docs/<tool>.md` guides, `docs/assets/screenshots/`. Stays out: `tests/`, `scripts/`, `.github/`, every developer doc (standards, architecture, internals, testing, common-tasks, adding-a-tool, releasing, vendoring, events), `docs/superpowers/`, `reviews/`, `docs/ideas/`, `docs/assets/ka0s-logo.png`, `CLAUDE.md`, `ruff.toml`, `requirements.txt`, `requirements.lock`, `.gitignore`, `.gitattributes`. |
| P3 | requirements.txt, events.md | Both stay out (user decision 2026-10-08). |
| P4 | README developer section | The README's "Developing" section is removed (user decision 2026-10-08), so no shipped doc links to a file that does not ship. |
| P5 | Mechanism | `.gitattributes` marks every "stays out" path `export-ignore`, so `git archive` (`scripts/build_release.py`) and GitHub's automatic source archives leave them out. A test archives `HEAD` (`git archive` in a temp dir; the test needs git, which CI has) and checks the file list against the "ships" table; a new top-level path fails until it is in one table. A second check: no shipped Markdown file links to a path that does not ship. |
| P6 | Updater | `core/updater.py`'s `MANAGED_DIRS` / `MANAGED_FILES` (what a zip update replaces, backs up and treats as program files) match the "ships" table, so a zip update never carries dropped developer files into `update-leftovers/` as if a user had added them. Files a previous release shipped that this one does not are removed (and backed up) like `RETIRED_FILES`. No zip install exists yet (no published release), but this must hold from v1.0.0 on. Tests cover an update from a full-repo zip to a trimmed one. |
| P7 | Standard | A new STD-11 rule: the release zip contains exactly the manifest in `docs/releasing.md`; enforced by the archive test. |
