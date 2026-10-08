# Releasing

Part of the developer docs: see the [Documentation map](architecture.md#documentation-map); the rules are STD-11.1,
STD-11.2, STD-11.5 and STD-12.3 in [standards.md](standards.md).

The updater reads the latest **published, non-prerelease** GitHub Release of `tusharsaxena/wow-tools`,
and its tag must be `vX.Y.Z` matching `wowtools/__init__.py`. Git installs fast-forward to the tag. Zip installs
download two files attached to the release, and every release must have both:

| Asset | What it is |
|---|---|
| `wow-tools-vX.Y.Z.zip` | The program: `git archive` of the tag, everything under one `wow-tools-vX.Y.Z/` folder |
| `SHA256SUMS` | One line, `<sha256>  wow-tools-vX.Y.Z.zip`, in the format `sha256sum` writes |

A zip install checks the zip's SHA-256 against `SHA256SUMS` before it changes anything, and refuses on a mismatch.
If the release has no `SHA256SUMS`, zip installs refuse to update (and point the user at the release page) unless
they set `[general] allow_unverified_updates = true`. So a release without the assets strands zip users.

## What a release contains

The release zip holds what a player needs to run the suite and read about it, and nothing else. A git install is a
clone and always has the whole repository; these rules apply to the release zip (and so to GitHub's automatic
"Source code" archives, which follow the same `export-ignore` rules in `.gitattributes`).

Three rules decide where a file goes:

1. **Anything the app or its launchers read at run time ships.** If removing it would break starting, running,
   updating or the in-app screens (the changelog on `c`, the help), it is in the release.
2. **User documentation ships.** The README, each tool's guide and the images they show.
3. **Everything for developing the suite stays out.** Tests, build and maintenance scripts, CI, developer docs,
   design records, review bundles and tool configuration.

When a new file does not fit one rule clearly, it stays out until the release manifest (below) names it.

### Ships

| Path | Why |
|---|---|
| `wowtools/` | The program |
| `vendor/` | The libraries the program imports (`PYTHONPATH`), with their `*.dist-info` licence files |
| `wow-tools.sh`, `wow-tools.cmd` | The launchers |
| `LICENSE` | The suite's MIT licence |
| `CHANGELOG.md` | Read by the app (`c` on the tool menu); every release must have its entry |
| `README.md` | Install, run, update, settings, terms of use |
| `docs/wtf-cleaner.md`, `docs/screenshot-organizer.md`, `docs/interface-backup.md`, `docs/ace3-profile-manager.md`, `docs/sv-browser.md` | The user guides |
| `docs/assets/screenshots/` | The images in the README and the guides |

### Stays out

| Path | What it is |
|---|---|
| `tests/` | The test suite |
| `scripts/` | `run_tests.py`, `build_release.py`, `update_vendor.py`, `gen_event_docs.py` |
| `.github/` | CI |
| `docs/standards.md`, `docs/architecture.md`, `docs/internals/`, `docs/testing.md`, `docs/common-tasks.md`, `docs/adding-a-tool.md`, `docs/releasing.md`, `docs/vendoring.md`, `docs/events.md` | Developer documentation |
| `docs/superpowers/`, `reviews/`, `docs/ideas/` | Design specs, plans, ledgers, review bundles and tool ideas |
| `docs/assets/ka0s-logo.png` | The repository logo, which no shipped doc shows |
| `CLAUDE.md`, `ruff.toml`, `requirements.txt`, `requirements.lock`, `.gitignore`, `.gitattributes` | Developer and tooling files; `vendor/` already holds the libraries |

Files that are never in git (`config/`, `logs/`, `dist/`, caches) are never in a release either.

### The release manifest

The two tables above are the manifest (STD-11.5). `.gitattributes` marks every "stays out" path `export-ignore`
(one `/<path> export-ignore` line each, a folder without its trailing slash), so `git archive` (and
`scripts/build_release.py`) leaves them out. `tests/test_release_contents.py` parses the two tables and checks that
every tracked path is in one of them, that the `export-ignore` lines are exactly the "stays out" table, that an
archive of `HEAD` holds exactly the "ships" paths, and that no shipped Markdown file links (a link or an image) to a
path that does not ship. A new file or folder fails that test until it is added to one of the two tables (and, if
it stays out, to `.gitattributes`). The README and the guides link developer docs only on GitHub, if at all.

A zip update works from the same manifest. This file does not ship, so `wowtools/core/updater.py` holds the two
tables as `RELEASE_SHIPS` and `RELEASE_STAYS_OUT`, and `test_the_updaters_manifest_is_the_one_in_releasing_md`
checks that they match the tables entry for entry: change a table, change its constant. The updater replaces the
top-level "ships" names (`MANAGED_DIRS` / `MANAGED_FILES`, derived from `RELEASE_SHIPS`). The "stays out" paths
inside those folders (`DEVELOPER_PATHS`: `docs/standards.md`, `docs/superpowers/` ...) are replaced with their
folder, so an install made from a full-repo zip loses them on its next update, kept in `.update-backup` like
any other replaced file, and they are never carried into `update-leftovers/` as files the user added. A top-level
"stays out" name (`scripts/`, `tests/`, `CLAUDE.md` ...) is never touched: no release ships it, so in a zip
install it can only be the user's.

## Steps

1. Make sure `main`/`master` is green: the `tests` workflow on GitHub Actions (`.github/workflows/tests.yml`)
   passes on all four jobs (Linux and Windows, Python 3.10 and 3.13). Locally: the
   [green gate](testing.md#the-green-gate) (`run_tests.py --all`, `ruff check --no-cache .`,
   `gen_event_docs.py --check`).
2. Bump `__version__` in `wowtools/__init__.py`, following semver.
3. Add the [`CHANGELOG.md`](../CHANGELOG.md) entry for vX.Y.Z: a `## [X.Y.Z] - YYYY-MM-DD` heading (today's date) above the previous
   one, with what changed (move anything under `## [Unreleased]` into it). Every tagged release must have an entry:
   the app shows it (`c` on the tool menu), a test fails while `__version__` has none, and step 6 refuses a tag
   without one. It goes in before the release commit, so the tagged archive carries it. To pull a release later,
   append ` [YANKED]` to its heading (the app marks it "yanked"); never delete its entry. Close every code fence:
   an unclosed one makes the whole file malformed.
4. Commit: `git commit -am "release: vX.Y.Z"`.
5. Tag and push: `git tag vX.Y.Z && git push origin HEAD --tags`.
6. Build the assets from the tag: `python3 scripts/build_release.py`. It writes `dist/wow-tools-vX.Y.Z.zip` and
   `dist/SHA256SUMS` (`dist/` is not committed), refuses if the tag is missing, holds another version or its
   `CHANGELOG.md` has no entry for the version, and prints the command for the next step. To check the sum by
   hand: `cd dist && sha256sum -c SHA256SUMS`.
7. Publish the release with both assets:

   ```sh
   gh release create vX.Y.Z dist/wow-tools-vX.Y.Z.zip dist/SHA256SUMS \
     --title "Ka0s WoW Tools vX.Y.Z" --notes "..."
   ```

   The notes appear in the in-app update prompt. If you forgot the assets, add them before anyone updates:
   `gh release upload vX.Y.Z dist/wow-tools-vX.Y.Z.zip dist/SHA256SUMS`.
8. Check: on a zip install of the previous version, `./wow-tools.sh update` should say
   "Updated Ka0s WoW Tools to vX.Y.Z", and the log should have an `update.verified` event.

Never re-use or move a tag, and never replace a published asset. Git installs would fail to fast-forward, and a
zip that no longer matches its `SHA256SUMS` is refused.
