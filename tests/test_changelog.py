"""core/changelog.py (spec D2: CHANGELOG.md parsed into entries, newest first) and the changelog screen (spec D3:
c on the tool menu, versions on the left, notes on the right, Esc back; q quits, as everywhere)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from textual.widgets import Markdown, OptionList, Static
from textual.widgets._footer import FooterKey

from tests.fixtures import BASE, TuiTestCase, build_wow_tree, make_config, settle
from wowtools import __version__
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.changelog import (CHANGELOG_PATH, UNRELEASED, Changelog, ChangelogError, entry_for, load_changelog,
                                     parse_changelog)
from wowtools.core.events import capture_events
from wowtools.ui.changelog_screen import VERSIONS_WIDTH, ChangelogScreen, NotesScroll, notes_title, version_label
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.suite_app import MENU_HINT, ToolMenuScreen, WowToolsApp

SAMPLE = """# Changelog

Intro text, not an entry.

## [0.2.0] - 2026-11-01

### Added

- Two.

## [Unreleased]

- Coming soon.

## [0.10.0] - 2027-01-02

- Ten.

```markdown
## not a heading inside a fence
```

## [0.1.0] - 2026-10-05

- One.
"""


class ParseChangelogTest(unittest.TestCase):
    def test_entries_newest_first_with_unreleased_on_top(self):
        entries = parse_changelog(SAMPLE)
        self.assertEqual([e.version for e in entries], [UNRELEASED, "0.10.0", "0.2.0", "0.1.0"])
        self.assertEqual([e.date for e in entries], [None, "2027-01-02", "2026-11-01", "2026-10-05"])
        self.assertTrue(entries[0].unreleased)
        self.assertFalse(entries[1].unreleased)

    def test_body_is_the_markdown_under_the_heading(self):
        entries = parse_changelog(SAMPLE)
        self.assertEqual(entry_for(entries, "0.2.0").body, "### Added\n\n- Two.")
        self.assertEqual(entry_for(entries, "0.1.0").body, "- One.")
        ten = entry_for(entries, "0.10.0").body
        self.assertIn("## not a heading inside a fence", ten)  # a fenced "## " line stays in the notes
        self.assertNotIn("Intro", "".join(e.body for e in entries))

    def test_entry_for_a_missing_version_is_none(self):
        self.assertIsNone(entry_for(parse_changelog(SAMPLE), "9.9.9"))

    def test_unreleased_heading_is_case_insensitive(self):
        self.assertEqual(parse_changelog("## [unreleased]\n- x\n")[0].version, UNRELEASED)

    def test_malformed_input_is_refused(self):
        bad = {
            "": "no version entries",
            "# Changelog\n\nJust text.\n": "no version entries",
            "## [0.1.0]\n": "no date",
            "## [0.1.0] - 05-10-2026\n": "not a date",
            "## [0.1.0] - 2026-13-01\n": "not a date",
            "## [0.1.0] - 20261005\n": "not a date",
            "## [1.0] - 2026-10-05\n": "not a version",
            "## [v1.0.0] - 2026-10-05\n": "not a version",
            "## 0.1.0 - 2026-10-05\n": "expected",
            "## Notes\n": "expected",
            "## [Unreleased] - 2026-10-05\n": "takes no date",
            "## [0.1.0] - 2026-10-05\n## [0.1.0] - 2026-10-06\n": "appears twice",
            "## [Unreleased] [YANKED]\n": "takes no date",
            "## [0.1.0] - 2026-10-05 [PULLED]\n": "expected",
            # an unclosed fence would swallow every later heading
            "## [0.2.0] - 2026-10-06\n- x\n```\ncode\n## [0.1.0] - 2026-10-05\n- y\n": "line 3: code fence",
            # ~~~ does not close a ``` fence
            "## [0.2.0] - 2026-10-06\n```\n~~~\n## [0.1.0] - 2026-10-05\n": "never closed",
        }
        for text, reason in bad.items():
            with self.subTest(text=text), self.assertRaises(ChangelogError) as ctx:
                parse_changelog(text)
            self.assertIn(reason, str(ctx.exception))

    def test_a_fence_closes_only_on_its_own_marker(self):
        text = ("## [0.1.0] - 2026-10-05\n````\nexample:\n```\n## [9.9.9] - 2026-01-01\n```\n````\n"
                "~~~\n```\n## [8.8.8] - 2026-01-01\n~~~~\n## [0.2.0] - 2026-10-06\n- two\n")
        entries = parse_changelog(text)
        self.assertEqual([e.version for e in entries], ["0.2.0", "0.1.0"])
        self.assertIn("## [9.9.9] - 2026-01-01", entries[1].body)
        self.assertIn("## [8.8.8] - 2026-01-01", entries[1].body)

    def test_a_yanked_release_parses_and_is_marked(self):
        entries = parse_changelog("## [0.2.0] - 2026-10-06 [YANKED]\n- bad\n## [0.1.0] - 2026-10-05\n- ok\n")
        self.assertEqual([(e.version, e.date, e.yanked) for e in entries],
                         [("0.2.0", "2026-10-06", True), ("0.1.0", "2026-10-05", False)])
        self.assertEqual(entries[0].body, "- bad")
        self.assertEqual(version_label(entries[0], 8, current="0.1.0").plain, "v0.2.0  2026-10-06  yanked")
        self.assertEqual(notes_title(entries[0]), "v0.2.0 · 2026-10-06 · yanked")
        self.assertEqual(notes_title(entries[1]), "v0.1.0 · 2026-10-05")

    def test_a_bad_heading_names_its_line(self):
        with self.assertRaises(ChangelogError) as ctx:
            parse_changelog("# Changelog\n\n## [0.1.0] - 2026-10-05\n- x\n## [oops]\n")
        self.assertIn("line 5", str(ctx.exception))


class LoadChangelogTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "CHANGELOG.md"

    def test_reads_the_file(self):
        self.path.write_text(SAMPLE, encoding="utf-8")
        changelog = load_changelog(self.path)
        self.assertIsNone(changelog.problem)
        self.assertEqual(len(changelog.entries), 4)

    def test_missing_unreadable_and_malformed_files_degrade_and_log(self):
        cases = {"missing": None, "malformed": "## [x]\n", "not utf-8": b"\xff\xfe## [0.1.0]"}
        for name, content in cases.items():
            with self.subTest(name), capture_events() as records:
                if isinstance(content, bytes):
                    self.path.write_bytes(content)
                elif content is not None:
                    self.path.write_text(content, encoding="utf-8")
                elif self.path.exists():
                    self.path.unlink()
                changelog = load_changelog(self.path)
                self.assertEqual(changelog.entries, [])
                self.assertIn("CHANGELOG.md", changelog.problem)
                logged = [r for r in records if r["event"] == "changelog.unreadable"]
                self.assertEqual(len(logged), 1, records)
                self.assertEqual(logged[0]["level"], "warning")
                self.assertEqual(logged[0]["data"]["reason"], changelog.problem)

    def test_the_installs_changelog_is_the_root_file_the_updater_ships(self):
        """CHANGELOG.md sits at the install root as a root *.md file: _shipped_names ships every one of those, so
        a zip update brings the new notes with the new program."""
        from wowtools.core.updater import _shipped_names
        self.assertEqual(CHANGELOG_PATH, REPO_ROOT / "CHANGELOG.md")
        self.assertIn("CHANGELOG.md", _shipped_names(REPO_ROOT))

    def test_the_real_changelog_parses_and_has_this_version(self):
        changelog = load_changelog()
        self.assertIsNone(changelog.problem)
        entry = entry_for(changelog.entries, __version__)
        self.assertIsNotNone(entry, f"CHANGELOG.md has no entry for {__version__}")
        self.assertRegex(entry.date, r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(entry.body.strip())


def sample_changelog() -> Changelog:
    return Changelog(parse_changelog(SAMPLE))


class ChangelogScreenTest(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_wow_tree(Path(tmp.name) / "World of Warcraft")
        self.config_dir = Path(tmp.name) / "config"
        self.cfg = make_config(self.config_dir, root)

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)

    def lines(self, app) -> list[str]:
        return [strip.text for strip in app.screen._compositor.render_strips()]

    async def open_changelog(self, app, pilot, changelog: Changelog | None = None, current: str = "0.2.0"):
        await settle(app, pilot)
        if changelog is None:
            with capture_events() as records:
                await pilot.press("c")
                await settle(app, pilot)
            self.assertIn({"screen": "tool_menu", "control": "changelog", "value": "open"},
                          [r["data"] for r in records if r["event"] == "ui.selection"])
        else:
            app.push_screen(ChangelogScreen(changelog, current=current))
            await settle(app, pilot)
        self.assertIsInstance(app.screen, ChangelogScreen)
        return app.screen

    async def test_c_on_the_menu_opens_the_real_changelog_and_esc_goes_back(self):
        for key in ("escape",):  # q quits from the changelog too (L7, tests/test_quit_key.py)
            with self.subTest(key=key):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    screen = await self.open_changelog(app, pilot)
                    self.assertEqual(screen.shown.version, __version__)  # the running version first
                    self.assertIn(f"v{__version__} · ", str(screen.query_one("#notes-title", Static).render()))
                    await pilot.press(key)
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ToolMenuScreen)

    async def test_versions_newest_first_one_per_row_with_the_current_one_marked(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            screen = await self.open_changelog(app, pilot, sample_changelog())
            versions = screen.query_one("#versions", OptionList)
            self.assertEqual([versions.get_option_at_index(i).id for i in range(versions.option_count)],
                             [UNRELEASED, "0.10.0", "0.2.0", "0.1.0"])
            text = "\n".join(self.lines(app))
            rows = [line[:VERSIONS_WIDTH] for line in self.lines(app) if line.startswith(" ▊ ")]
            self.assertEqual(len(rows), 4, rows)
            self.assertIn("v0.2.0", text)
            self.assertEqual(sum("current" in row for row in rows), 1)
            self.assertIn("current", next(row for row in rows if "v0.2.0" in row))
            self.assertEqual(versions.highlighted, 2)  # the running version
            self.assertIs(app.focused, versions)

    async def test_up_down_change_the_notes(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            screen = await self.open_changelog(app, pilot, sample_changelog())
            notes = screen.query_one("#notes-text", Markdown)
            self.assertIn("Two.", notes.source)
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(screen.shown.version, "0.1.0")
            self.assertEqual(notes.source, "- One.")
            self.assertIn("v0.1.0 · 2026-10-05", str(screen.query_one("#notes-title", Static).render()))
            await pilot.press("home")
            await pilot.pause()
            self.assertEqual(screen.shown.version, UNRELEASED)
            self.assertEqual(str(screen.query_one("#notes-title", Static).render()), UNRELEASED)

    async def test_right_and_tab_go_to_the_notes_and_left_comes_back(self):
        long = Changelog(parse_changelog("## [0.1.0] - 2026-10-05\n" + "".join(f"- line {i}\n" for i in range(80))))
        for key in ("right", "tab", "enter"):
            with self.subTest(key=key):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    screen = await self.open_changelog(app, pilot, long, current="0.1.0")
                    notes = screen.query_one("#notes", NotesScroll)
                    await pilot.press(key)
                    await pilot.pause()
                    self.assertIs(app.focused, notes)
                    self.assertGreater(notes.max_scroll_y, 0)
                    await pilot.press("down", "down", "pagedown")
                    await pilot.pause()
                    self.assertGreater(notes.scroll_y, 0)  # ↓ scrolls the notes, not the version
                    self.assertEqual(screen.shown.version, "0.1.0")
                    await pilot.press("left")
                    await pilot.pause()
                    self.assertIs(app.focused, screen.query_one("#versions", OptionList))

    async def test_a_missing_changelog_says_so(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            problem = "CHANGELOG.md is missing from /x."
            screen = await self.open_changelog(app, pilot, Changelog([], problem))
            self.assertFalse(screen.query_one("#versions", OptionList).display)
            self.assertIsNone(screen.shown)
            self.assertEqual(screen.query_one("#notes-text", Markdown).source, problem)
            text = "\n".join(self.lines(app))
            self.assertIn("No changelog to show", text)
            self.assertIn("CHANGELOG.md is missing", text)
            await pilot.press("left", "right", "down")
            await pilot.pause()
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)

    async def test_s_does_nothing_over_the_changelog_and_is_not_in_its_footer(self):
        """Critic b6: the app-level s (settings) would open the general settings on top of the changelog. With no
        tool open, s works on the tool menu only: over the changelog it is hidden from the footer and inert."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            self.assertIn("Settings", [k.description for k in app.screen.query(FooterKey)])
            await self.open_changelog(app, pilot, sample_changelog())
            descriptions = [k.description for k in app.screen.query(FooterKey)]
            self.assertNotIn("Settings", descriptions)
            self.assertIn("Back", descriptions)
            await pilot.press("s")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ChangelogScreen)
            app.action_settings()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ChangelogScreen)
            await pilot.press("escape")
            await settle(app, pilot)
            await pilot.press("s")  # back on the menu, s works again
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SetupScreen)

    async def test_c_is_on_the_menu_footer_and_hint(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            self.assertIn("Changelog", [k.description for k in app.screen.query(FooterKey)])
            self.assertIn("c changelog", MENU_HINT)
