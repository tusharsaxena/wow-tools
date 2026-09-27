# Releasing

The updater reads the latest **published, non-prerelease** GitHub Release of `tusharsaxena/wow-tools`,
and its tag must be `vX.Y.Z` matching `wowtools/__init__.py`. Zip installs download that tag's zipball,
and git installs fast-forward to the tag.

1. Make sure `main`/`master` is green: `python3 -m unittest discover -s tests -t .`
   and `python3 scripts/gen_event_docs.py --check`.
2. Bump `__version__` in `wowtools/__init__.py`, following semver.
3. Commit: `git commit -am "release: vX.Y.Z"`.
4. Tag and push: `git tag vX.Y.Z && git push origin HEAD --tags`.
5. Publish: `gh release create vX.Y.Z --title "Ka0s WoW Tools vX.Y.Z" --notes "..."`.
   The notes appear in the in-app update prompt.

Never re-use or move a tag. Git installs would fail to fast-forward.
