# Releasing

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

## Steps

1. Make sure `main`/`master` is green: the `tests` workflow on GitHub Actions (`.github/workflows/tests.yml`)
   passes on all four jobs (Linux and Windows, Python 3.10 and 3.13). Locally: `python3 scripts/run_tests.py`
   and `python3 scripts/gen_event_docs.py --check`.
2. Bump `__version__` in `wowtools/__init__.py`, following semver.
3. Commit: `git commit -am "release: vX.Y.Z"`.
4. Tag and push: `git tag vX.Y.Z && git push origin HEAD --tags`.
5. Build the assets from the tag: `python3 scripts/build_release.py`. It writes `dist/wow-tools-vX.Y.Z.zip` and
   `dist/SHA256SUMS` (`dist/` is not committed), refuses if the tag is missing or holds another version, and
   prints the command for the next step. To check the sum by hand: `cd dist && sha256sum -c SHA256SUMS`.
6. Publish the release with both assets:

   ```sh
   gh release create vX.Y.Z dist/wow-tools-vX.Y.Z.zip dist/SHA256SUMS \
     --title "Ka0s WoW Tools vX.Y.Z" --notes "..."
   ```

   The notes appear in the in-app update prompt. If you forgot the assets, add them before anyone updates:
   `gh release upload vX.Y.Z dist/wow-tools-vX.Y.Z.zip dist/SHA256SUMS`.
7. Check: on a zip install of the previous version, `./wow-tools.sh update` should say
   "Updated Ka0s WoW Tools to vX.Y.Z", and the log should have an `update.verified` event.

Never re-use or move a tag, and never replace a published asset. Git installs would fail to fast-forward, and a
zip that no longer matches its `SHA256SUMS` is refused.
