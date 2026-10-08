# Release contents: status ledger

Plan: `2026-10-08-release-contents.md`. Spec: `../specs/2026-10-08-release-contents-design.md`.
Branch: `docs/release-guidelines`. Resume at the first task not marked `done`. Never merge without the user's
go-ahead.

| Task | Title | Status | Commit | Notes |
|---|---|---|---|---|
| P0 | guidelines, spec, plan, ledger | done | (this commit) | user review 2026-10-08: requirements.txt and events.md stay out; README "Developing" removed |
| P1 | manifest enforcement + README + standard | done | (this commit) | `.gitattributes` export-ignores the 22 "stays out" paths; `tests/test_release_contents.py` (10 tests) + `test_the_zip_leaves_out_export_ignored_paths`; README "Developing" removed; STD-11.5; `build_release.py` run on a throwaway `v0.1.0` tag in a temp clone: one `wow-tools-v0.1.0/` folder, 1095 files, only the ships table; full suite 1918 tests, 0 failures, 2 skipped |
| P2 | updater matches the manifest | done | (folded into P1) | P1 review: `MANAGED_DIRS` / `MANAGED_FILES` drop `scripts`, `requirements.txt`, `requirements.lock`, `.gitattributes`; `test_the_updater_manages_exactly_what_ships`, `test_developer_file_names_in_the_install_are_the_users`; README and recipes updated |
| PR | review, push, CI | todo | | |

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
