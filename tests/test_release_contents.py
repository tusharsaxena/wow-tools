"""The release manifest (STD-11.5, spec P2/P5): the release zip holds exactly the "Ships" table of docs/releasing.md.

The "Ships" and "Stays out" tables in docs/releasing.md are the single source of truth: these tests parse them, then
check every tracked path against them, `.gitattributes`'s `export-ignore` lines against "Stays out", a `git archive`
of HEAD against "Ships", and every link in a shipped Markdown file against what ships. Read-only: `git ls-files`,
`git ls-tree` and `git archive` to a pipe; nothing is written to the repository."""
from __future__ import annotations

import io
import posixpath
import re
import shutil
import subprocess
import tarfile
import unittest

from wowtools.core import updater
from wowtools.core.bootstrap import REPO_ROOT

RELEASING = REPO_ROOT / "docs" / "releasing.md"
MANIFEST_HINT = ("add it to the 'Ships' or the 'Stays out' table in docs/releasing.md (What a release contains), "
                 "and a 'Stays out' path to .gitattributes as export-ignore")

_LINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_REF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.MULTILINE)
_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
_CODE_RE = re.compile(r"`[^`\n]*`")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, check=False)


def _in_git_checkout() -> bool:
    if shutil.which("git") is None:
        return False
    probe = _git("rev-parse", "--show-toplevel")
    return probe.returncode == 0


HAS_REPO = _in_git_checkout()


def manifest_table(heading: str, text: str | None = None) -> list[str]:
    """The backticked paths in the first column of the table under `### <heading>` in docs/releasing.md."""
    text = RELEASING.read_text(encoding="utf-8") if text is None else text
    match = re.search(rf"^### {re.escape(heading)}\n(.*?)(?=^#{{1,3}} |\Z)", text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"docs/releasing.md has no '### {heading}' table")
    paths: list[str] = []
    for line in match.group(1).splitlines():
        cells = line.strip().strip("|").split("|")
        if not line.lstrip().startswith("|") or re.fullmatch(r"[\s:-]*", cells[0]) or cells[0].strip() == "Path":
            continue
        paths.extend(re.findall(r"`([^`]+)`", cells[0]))
    return paths


def covers(entry: str, path: str) -> bool:
    """A manifest entry covers a path: a folder entry (`x/`) everything under it, a file entry only itself."""
    return path.startswith(entry) if entry.endswith("/") else path == entry


def covering(entries: list[str], path: str) -> list[str]:
    return [entry for entry in entries if covers(entry, path)]


def markdown_links(text: str) -> list[str]:
    """Every link target in Markdown text (inline links and images, reference definitions, <img src>), outside code."""
    text = _CODE_RE.sub("", _FENCE_RE.sub("", text))
    return [*_LINK_RE.findall(text), *_REF_RE.findall(text), *_IMG_RE.findall(text)]


def local_target(doc: str, target: str) -> str | None:
    """The repo path a link in `doc` points at, or None for a web link, a mail link or an anchor in the page."""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith(("#", "//")):
        return None
    path = target.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return None
    return posixpath.normpath(posixpath.join(posixpath.dirname(doc), path))


def tracked_paths(ref: str | None = None) -> list[str]:
    """Every file git tracks: in the index (ref None) or in the tree of `ref`."""
    args = ("ls-files", "-z") if ref is None else ("ls-tree", "-r", "-z", "--name-only", ref)
    listed = _git(*args)
    if listed.returncode != 0:
        raise AssertionError(listed.stderr.decode("utf-8", "replace"))
    return [p for p in listed.stdout.decode("utf-8").split("\0") if p]


def archive_of_head() -> dict[str, bytes]:
    """`git archive` of HEAD with the working tree's .gitattributes (so an uncommitted export-ignore line counts):
    each archived file's path and content."""
    archived = _git("archive", "--worktree-attributes", "--format=tar", "HEAD")
    if archived.returncode != 0:
        raise AssertionError(archived.stderr.decode("utf-8", "replace"))
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                files[member.name] = tar.extractfile(member).read()
            elif member.issym():
                files[member.name] = b""
    return files


class ManifestTablesTest(unittest.TestCase):
    """The two tables parse, and no path is in both."""

    def test_the_tables_name_the_program_and_the_developer_files(self):
        ships, stays_out = manifest_table("Ships"), manifest_table("Stays out")
        for entry in ("wowtools/", "vendor/", "wow-tools.sh", "wow-tools.cmd", "LICENSE", "CHANGELOG.md",
                      "README.md", "docs/assets/screenshots/"):
            self.assertIn(entry, ships)
        for entry in ("tests/", "scripts/", ".github/", "docs/superpowers/", "reviews/", "CLAUDE.md",
                      "docs/standards.md", "docs/events.md", "requirements.txt", ".gitattributes"):
            self.assertIn(entry, stays_out)

    def test_the_updater_manages_exactly_what_ships(self):
        """An update replaces (backs up, then deletes) every managed name the install has, so a managed name no release
        ships could only be the user's file (P1 review). The managed names are the top-level "Ships" entries; the root
        *.md files are matched by name from the release itself (`_shipped_names`)."""
        top = {entry.split("/", 1)[0] for entry in manifest_table("Ships")}
        names = {name for name in top if not name.endswith(".md")}
        self.assertEqual(set(updater.MANAGED_DIRS) | set(updater.MANAGED_FILES), names,
                         "MANAGED_DIRS + MANAGED_FILES in wowtools/core/updater.py must match the top-level "
                         "'Ships' entries of docs/releasing.md (root *.md files aside)")
        self.assertEqual(set(updater.MANAGED_DIRS), {entry.split("/", 1)[0] for entry in manifest_table("Ships")
                                                     if "/" in entry})

    def test_the_updaters_manifest_is_the_one_in_releasing_md(self):
        """The updater cannot read docs/releasing.md at run time (it does not ship), so it carries the two tables as
        constants; they must be the tables, entry for entry (P2)."""
        self.assertEqual(list(updater.RELEASE_SHIPS), manifest_table("Ships"),
                         "RELEASE_SHIPS in wowtools/core/updater.py must list the 'Ships' table of docs/releasing.md")
        self.assertEqual(list(updater.RELEASE_STAYS_OUT), manifest_table("Stays out"),
                         "RELEASE_STAYS_OUT in wowtools/core/updater.py must list the 'Stays out' table of "
                         "docs/releasing.md")

    def test_no_entry_is_in_both_tables(self):
        ships, stays_out = manifest_table("Ships"), manifest_table("Stays out")
        for a in ships:
            for b in stays_out:
                self.assertFalse(covers(a, b) or covers(b, a), f"{a} and {b} overlap in docs/releasing.md")

    def test_the_table_parser_reads_backticked_paths_of_the_first_column(self):
        text = ("### Ships\n\n| Path | Why |\n|---|---|\n| `a/`, `b.md` | the `c` |\n\n"
                "### Stays out\n\n| Path | What |\n|---|---|\n| `d` | x |\n\n## Steps\n\n| `e` | y |\n")
        self.assertEqual(manifest_table("Ships", text), ["a/", "b.md"])
        self.assertEqual(manifest_table("Stays out", text), ["d"])

    def test_link_targets_skip_web_links_anchors_and_code(self):
        text = ("[a](docs/a.md) ![b](img/b.png \"t\") [c](https://x.y/z) [d](#here) [e](mailto:x@y)\n"
                "`[f](f.md)`\n```\n[g](g.md)\n```\n[h]: ../h.md\n<img src=\"i.png\">\n")
        targets = [local_target("docs/x.md", t) for t in markdown_links(text)]
        self.assertEqual([t for t in targets if t], ["docs/docs/a.md", "docs/img/b.png", "h.md", "docs/i.png"])
        self.assertEqual(local_target("README.md", "docs/a.md#part"), "docs/a.md")


@unittest.skipUnless(HAS_REPO, "needs git and a git checkout (the release zip is a git archive)")
class ReleaseContentsTest(unittest.TestCase):
    """STD-11.5: what git tracks, what .gitattributes leaves out and what `git archive` ships match the manifest."""

    @classmethod
    def setUpClass(cls):
        cls.ships = manifest_table("Ships")
        cls.stays_out = manifest_table("Stays out")
        cls.archive = archive_of_head()

    def test_every_tracked_path_is_in_one_table(self):
        unlisted = [p for p in tracked_paths() if not covering(self.ships + self.stays_out, p)]
        tops = sorted({p.split("/", 1)[0] + ("/" if "/" in p else "") for p in unlisted})
        self.assertEqual(tops, [], f"tracked paths in neither table of docs/releasing.md: {sorted(unlisted)[:10]}; "
                         + MANIFEST_HINT)

    def test_gitattributes_export_ignores_exactly_the_stays_out_table(self):
        ignored = []
        for line in (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) >= 2 and "export-ignore" in fields[1:]:
                ignored.append(fields[0])
        wanted = ["/" + entry.rstrip("/") for entry in self.stays_out]
        self.assertEqual(sorted(ignored), sorted(wanted),
                         "each 'Stays out' path of docs/releasing.md needs one '/<path> export-ignore' line in "
                         ".gitattributes (a folder without its trailing slash), and nothing else")

    def test_the_archive_holds_only_what_ships(self):
        extra = sorted(p for p in self.archive if not covering(self.ships, p))
        self.assertEqual(extra, [], "the release archive holds paths outside the 'Ships' table of docs/releasing.md; "
                         + MANIFEST_HINT)
        dev = sorted(p for p in self.archive if covering(self.stays_out, p))
        self.assertEqual(dev, [], "the release archive holds 'Stays out' paths (docs/releasing.md)")

    def test_the_archive_holds_everything_that_ships(self):
        for entry in self.ships:
            self.assertTrue(any(covers(entry, p) for p in self.archive),
                            f"{entry} is in the 'Ships' table of docs/releasing.md but not in the release archive")
        committed = {p for p in tracked_paths("HEAD") if covering(self.ships, p)}
        self.assertEqual(sorted(committed - set(self.archive)), [],
                         "shipped files that .gitattributes leaves out of the release archive")

    def test_the_archive_has_the_launchers_the_program_and_the_changelog(self):
        for path in ("wow-tools.sh", "wow-tools.cmd", "wowtools/__init__.py", "wowtools/__main__.py",
                     "CHANGELOG.md", "LICENSE", "README.md"):
            self.assertIn(path, self.archive)
        self.assertTrue(any(p.startswith("vendor/textual/") for p in self.archive))

    def test_no_shipped_markdown_links_to_a_path_that_does_not_ship(self):
        # The index and the working tree, not HEAD: what the next commit ships (CI checks out HEAD, so the same).
        shipped = {p for p in tracked_paths() if covering(self.ships, p) and (REPO_ROOT / p).is_file()}
        folders = {"/".join(p.split("/")[:depth]) for p in shipped for depth in range(1, p.count("/") + 1)}
        docs = sorted(p for p in shipped if p.endswith(".md") and not p.startswith("vendor/"))
        self.assertIn("README.md", docs)
        checked = 0
        for doc in docs:
            for target in markdown_links((REPO_ROOT / doc).read_text(encoding="utf-8")):
                path = local_target(doc, target)
                if path is None:
                    continue
                checked += 1
                self.assertTrue(path in shipped or path in folders,
                                f"{doc} links to {target}, which the release zip does not hold (docs/releasing.md); "
                                "link to GitHub instead or ship it")
        self.assertGreater(checked, 20, "the link check found almost no local links: is the pattern broken?")


if __name__ == "__main__":
    unittest.main()
