# Release contents: status ledger

Plan: `2026-10-08-release-contents.md`. Spec: `../specs/2026-10-08-release-contents-design.md`.
Branch: `docs/release-guidelines`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| P0 | guidelines, spec, plan, ledger | done | (this commit) | user review 2026-10-08: requirements.txt and events.md stay out; README "Developing" removed |
| P1 | manifest enforcement + README + standard | done | (this commit) | `.gitattributes` export-ignores the 22 "stays out" paths; `tests/test_release_contents.py` (10 tests) + `test_the_zip_leaves_out_export_ignored_paths`; README "Developing" removed; STD-11.5; `build_release.py` run on a throwaway `v0.1.0` tag in a temp clone: one `wow-tools-v0.1.0/` folder, 1095 files, only the ships table; full suite 1918 tests, 0 failures, 2 skipped |
| P2 | updater matches the manifest | done | (this commit) | P1 review dropped `scripts`, `requirements.txt`, `requirements.lock`, `.gitattributes` from `MANAGED_*` (P2-a); this commit: `RELEASE_SHIPS` / `RELEASE_STAYS_OUT` in `core/updater.py` mirror the two tables (checked by `test_the_updaters_manifest_is_the_one_in_releasing_md`), `MANAGED_*` derived from them, `DEVELOPER_PATHS` never carried into `update-leftovers/`; 3 zip-update tests (full-repo install to trimmed release, pruned backup, rollback); full suite 1925 tests, 0 failures, 2 skipped |
| PR | review, push, CI | done | (this commit) | whole-branch review: no defect found; README test badge 1918 -> 1925; release archive of HEAD: 1095 files (`wowtools/` 136, `vendor/` 918, `docs/` 36: five guides + 31 screenshots, launchers, `LICENSE`, `CHANGELOG.md`, `README.md`); full suite 1925 tests, 0 failures, 2 skipped; before merge: user confirms P2-e (top-level developer names left in place, narrowing spec P6) |

## Decisions taken during the build

- P1-a: the `export-ignore` lines are anchored paths, `/tests export-ignore` (a folder without its trailing slash):
  `git archive` skips a matched folder whole, and a trailing-slash pattern never matches in `.gitattributes`. The
  test requires exactly one such line per "stays out" entry and no other `export-ignore` line.
- P1-b: the archive test runs `git archive --worktree-attributes HEAD`, so an uncommitted `.gitattributes` edit
  counts locally; CI checks out HEAD, so it is the same there. The tracked-path check reads the index (`git
  ls-files`), so a staged new file fails before it is committed. The tables are parsed from `docs/releasing.md`
  (single source of truth), not pinned in the test.
- P1-c: the link check reads the shipped Markdown files from the working tree against the shipped tracked paths,
  covering inline links, images, reference definitions and `<img src>`, outside code spans and fences; web links
  and in-page anchors are skipped.
- P1-d: the README "Updates" section still names `scripts` and `docs` among the app's own folders a zip update
  replaces; that text follows `MANAGED_DIRS`, so it changes with the updater in P2.
- P2-a (P1 review, major): an update backs up and deletes every managed name the install has, so a managed name no
  release ships (`scripts/`, `requirements.txt`, `requirements.lock`, `.gitattributes`) could only be the user's
  file, and the root files were lost for good once the backup was pruned. They are dropped from `MANAGED_*`, not
  moved to `RETIRED_FILES`: no release was ever published, so no zip install got them from us. This narrows spec P6
  ("files a previous release shipped ... are removed like `RETIRED_FILES`") to nothing until a release drops a
  shipped name. `test_the_updater_manages_exactly_what_ships` keeps `MANAGED_*` equal to the top-level "Ships" names
  (root `*.md` aside: `_shipped_names` takes those from the release); the zip-update test covers a full-repo-shaped
  install updating to a trimmed release, the developer names left untouched and not backed up. Done here rather
  than as a separate commit, folded into P1.
- P2-b (P1 review, minor): README "Updates" now names `wowtools`, `vendor` and `docs`, as does the
  `_carry_user_files` docstring (resolves P1-d). The add-a-tool and rename recipes (`adding-a-tool.md`,
  `common-tasks.md` sections 1 and 10) add the guide's "Ships" entry and cite STD-11.5.
- P2-c: the manifest lives in code as `RELEASE_SHIPS` / `RELEASE_STAYS_OUT` in `wowtools/core/updater.py` (UI-free,
  no new module), copied entry for entry from `docs/releasing.md`: the updater cannot read that doc at run time, as
  it does not ship. `test_the_updaters_manifest_is_the_one_in_releasing_md` fails when a table and its constant
  differ, and `MANAGED_DIRS` / `MANAGED_FILES` are derived from `RELEASE_SHIPS` rather than kept by hand; the
  add-a-tool and rename recipes name the constant.
- P2-d: the developer files a full-repo zip leaves inside a managed folder (`DEVELOPER_PATHS`, the "Stays out"
  entries under `docs/`: `docs/standards.md`, `docs/internals/`, `docs/superpowers/`, `docs/assets/ka0s-logo.png`
  ...) are already removed and backed up, because `docs/` is replaced whole. The fix is in `_carry_user_files`: it
  skips them, so a pruned backup no longer drops them into `update-leftovers/` as if the user had added them. Any
  other file the user added in `docs/` (or `wowtools/`, `vendor/`) is still carried (#7). What now goes with a
  pruned backup is wider than a user file named like a developer doc (`docs/standards.md`): a folder entry
  (`docs/internals/`, `docs/superpowers/`, `docs/ideas/`) matches by prefix, so every file under those folders,
  a user's `docs/ideas/my-idea.md` included, is treated as the repository's and deleted with the backup (P2
  review, minor). Accepted and said plainly in the README "Updates" section and the code, rather than narrowing
  the folder entries to the tracked files: `docs/superpowers/` and `docs/ideas/` gain files with every spec and
  idea, so a pinned file list would go stale on each commit, and the README already tells users not to keep files
  in `docs`. `test_a_pruned_backup_drops_everything_under_a_developer_docs_folder` pins the behaviour.
- P2-e: the top-level "Stays out" names (`scripts/`, `tests/`, `.github/`, `reviews/`, `CLAUDE.md`, `ruff.toml` ...)
  stay untouched by a zip update, as P2-a decided: they are not removed or backed up, and because they are never
  in a backup they are never carried either. Removing them like `RETIRED_FILES` (the computed P2 brief) would
  permanently delete a user's same-named file once the backup is pruned (data safety, STD-5). No release zip ever
  shipped them, so the only installs that have them came from a GitHub "Download ZIP" of a branch; there they are
  harmless clutter the app never reads. This narrows spec P6 ("removed (and backed up) like `RETIRED_FILES`") for
  the top-level names: a departure from a spec decision, not only an implementation detail (P2 review, minor), so
  the user confirms P2-e before the merge (PR task); if they reject it, those names join `RETIRED_FILES`-style
  removal instead.
- P2-f: no `CHANGELOG.md` line. No zip install of a published release exists yet, so no player can notice the
  change; the README "Updates" sentence on `update-leftovers` now says it never gets a developer document.
