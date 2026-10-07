from __future__ import annotations

import importlib.util
import unittest

from wowtools import __version__
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.changelog import entry_for, parse_changelog
from wowtools.tools import TOOLS
from wowtools.ui.branding import TERMS


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_event_docs", REPO_ROOT / "scripts" / "gen_event_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocsTest(unittest.TestCase):
    def test_event_reference_is_up_to_date(self):
        generated = load_generator().render()
        on_disk = (REPO_ROOT / "docs" / "events.md").read_text(encoding="utf-8")
        self.assertEqual(on_disk, generated, "Run: python3 scripts/gen_event_docs.py")

    def test_every_event_is_documented(self):
        text = (REPO_ROOT / "docs" / "events.md").read_text(encoding="utf-8")
        for name in ("session.start", "config.changed", "sv.deleted", "backup.created", "update.available"):
            self.assertIn(f"`{name}`", text)

    def test_readme_links_a_guide_for_every_tool(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for tool in TOOLS.values():
            self.assertIn(tool.title, readme)
            guide = f"docs/{tool.name}.md"
            self.assertIn(f"]({guide})", readme)
            self.assertTrue((REPO_ROOT / guide).is_file(), guide)
        self.assertIn("## version history", readme.lower())
        self.assertNotIn("## For developers", readme)

    def test_version_badge_and_changelog_match_the_version(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"badge/Version-{__version__}-blue", readme)
        self.assertIn("](CHANGELOG.md)", readme)
        self.assertNotIn("| Version | Date | Highlights |", readme)  # the history lives in CHANGELOG.md
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertTrue(changelog.startswith("# Changelog\n"))
        # Every tagged release needs an entry (build_release.py refuses a tag without one); the app shows them.
        self.assertIsNotNone(entry_for(parse_changelog(changelog), __version__),
                             f"CHANGELOG.md has no '## [{__version__}] - YYYY-MM-DD' entry")

    def test_readme_has_the_menus_terms_of_use(self):
        """Spec D6: the README carries the tool menu's terms word for word (however the lines are wrapped)."""
        readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
        self.assertTrue(TERMS in readme, "README.md lacks the terms of use (wowtools.ui.branding.TERMS)")
        self.assertIn("## Terms of use", readme)

    def test_user_docs_cover_the_entry_point_tools_and_safety(self):
        readme = "\n".join((REPO_ROOT / p).read_text(encoding="utf-8")
                           for p in ["README.md", *(f"docs/{t.name}.md" for t in TOOLS.values())])
        for needle in ("wow-tools.cmd", "./wow-tools.sh", "wow-tools update", "config\\wtf-cleaner.cfg",
                       "wow-tools.lock", "Override and continue", "stray_copies", "Restoring a backup",
                       "backup\\backup-<flavor>-<YYYYMMDD-HHMMSS>.zip", "cleaned\\cleaned-<flavor>-<account>-", "keep_backups", "Dry run",
                       "config\\screenshot-organizer.cfg", "Undo last run", "journal"):
            self.assertIn(needle, readme)
        for gone in ("wtf-cleaner.cmd", "wtf-cleaner.sh", "--flavor", "python -m wowtools"):
            self.assertNotIn(gone, readme)

    def test_ace3_profile_manager_guide_and_readme(self):
        guide = (REPO_ROOT / "docs" / "ace3-profile-manager.md").read_text(encoding="utf-8")
        for needle in ("Close WoW", "## Step by step", "## The review screen", "## Keys on the review screen",
                       "Only Default", "Everyone → Default", "blacklist", "unlock", "## What the tool never touches",
                       "## Dry run", "## Undo last change", "changed since", "snapshots\\snapshot-<flavor>-",
                       "edited\\edited-<flavor>-<account>-", "journal\\journal-", "edit-in-progress.json",
                       "Put the originals back", "## Settings", "keep_backups", "## FAQ", "LibDualSpec",
                       "missing", "no character folder", "## Troubleshooting", "<!-- screenshots:",
                       "## How it works", "pending change", "guidance line", "action bar", "Blacklist…",
                       "blacklist screen"):
            self.assertIn(needle, guide)
        self.assertNotIn("staged", guide.casefold())  # feedback round 1: "pending changes" everywhere
        for key in ("Space", "`a`", "`n`", "`d`", "`p`", "`e`", "`k`", "`o`", "`m`", "`Backspace`", "`x`", "`c`", "`b`", "`u`", "`v`",
                    "`/`", "`w`", "`y`", "`r`", "`z`", "`f`", "`t`", "`s`", "`q`"):
            self.assertIn(key, guide)
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("config\\ace3-profile-manager.cfg", readme)
        claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Ace3 Profile Manager (`ace3-profile-manager`, package `tools/ace3_profile_manager`)", claude)

    def test_sv_browser_guide_readme_and_notes(self):
        guide = (REPO_ROOT / "docs" / "sv-browser.md").read_text(encoding="utf-8")
        self.assertTrue(guide.index("USE AT YOUR OWN RISK") < guide.index("## Step by step"))
        for needle in ("Close WoW", "## Step by step", "## The review screen", "## Editing", "Top-level",
                       "array entry", "already has", "## Search", "Exact", "Contains", "Whole value",
                       "Match case", "Account-wide only", "Addon file", "10,000", "left out",
                       "## Editing the results in bulk", "every ticked result", "Replace only the matched text",
                       "Edit 37", "⚠ USE AT YOUR OWN RISK",
                       "## Apply", "## Dry run", "## Undo last change", "changed since", "Put the originals back",
                       "snapshots\\snapshot-<flavor>-", "edited\\edited-<flavor>-all-", "journal\\journal-",
                       "edit-in-progress.json", "keep_backups", "keep_journals", "config\\sv-browser.cfg",
                       "## Settings", "## Keys on the review screen", "## FAQ", "## Troubleshooting",
                       "<!-- screenshots:", "I understand", "Unstage", "Back to review"):
            self.assertIn(needle, guide)
        self.assertNotIn("still being built", guide)
        for gone in ("## Search and replace", "Replace with", "Find only", "New value", "staged and ticked",
                     "When a ticked result is left out"):  # D38/D39: search finds only, ticks only select
            self.assertNotIn(gone, guide)
        for key in ("`Space`", "`a`", "`n`", "`S`", "`e`", "`k`", "`d`", "`Backspace`", "`v`", "`x`", "`c`",
                    "`/`", "`w`", "`y`", "`r`", "`z`", "`f`", "`t`", "`s`", "`h`", "`q`"):
            self.assertIn(key, guide)
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("config\\sv-browser.cfg", readme)
        self.assertNotIn("four tools", readme.casefold())
        claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Saved Variables Browser (`sv-browser`, package `tools/sv_browser`)", claude)
        for module in ("luasv", "sv_apply", "sv_journal", "sv_undo", "sv_verify", "sv_report", "sv_events"):
            self.assertIn(f"`{module}`", claude)
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("- **Saved Variables Browser**", changelog)
        architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        self.assertIn("## Saved Variables Browser data flow", architecture)
        self.assertIn("| `luasv` |", architecture)

    def test_guides_filter_on_submit_and_risk_banner(self):
        """Feedback round 1 (D37, D40, D41): every tree filter applies on Enter or its Filter button, never as you
        type; the destructive screens' guides name the red banner; the changelog says so too."""
        for tool in TOOLS.values():
            guide = (REPO_ROOT / "docs" / f"{tool.name}.md").read_text(encoding="utf-8")
            self.assertIn("**Filter**", guide, tool.name)
            self.assertNotIn("keeps the filter", guide, tool.name)  # the old live filter's Enter
        for name in ("wtf-cleaner", "ace3-profile-manager", "interface-backup", "sv-browser"):
            guide = (REPO_ROOT / "docs" / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("`⚠ USE AT YOUR OWN RISK`", guide, name)
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("`Enter` keeps the filter", readme)
        self.assertNotIn("find and replace", readme)
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for needle in ("**Filter**", "⚠ USE AT YOUR OWN RISK", "Ka0s WoW Tools** in bold gold"):
            self.assertIn(needle, changelog)
        self.assertNotIn("Find only", changelog)
        claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("`FilterBar`", claude)
        self.assertIn("`RiskBanner`", claude)

    def test_warnings_view_and_blacklist_key_are_documented(self):
        """Spec W1, B1-B4: every guide opens its warnings with `!` (no "(see the log)" left), the WTF Cleaner guide
        explains its blacklist (`b`, greyed rows, the hand-edited setting, the wildcard), and the changelog,
        architecture and CLAUDE.md name the shared pieces."""
        for tool in TOOLS.values():
            guide = (REPO_ROOT / "docs" / f"{tool.name}.md").read_text(encoding="utf-8")
            self.assertNotIn("see the log)", guide, tool.name)
            self.assertIn("| `!` | Open the", guide, tool.name)
            self.assertIn("**warnings view**", guide, tool.name)
        wtf = (REPO_ROOT / "docs" / "wtf-cleaner.md").read_text(encoding="utf-8")
        for needle in ("### The blacklist", "| `b` | Put the highlighted addon", "**blacklisted**",
                       "blacklist = _retail_:ElkBuffBars", "`*:WeakAuras`", "### Scan warnings"):
            self.assertIn(needle, wtf)
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for needle in ("warnings view", "`!`", "`b`", "`[wtf_cleaner] blacklist`"):
            self.assertIn(needle, changelog)
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("`!`", readme)
        self.assertIn("config\\wtf-cleaner.cfg", readme)
        architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        for needle in ("`WarningsScreen`", "`SummaryBar`", "`BlacklistAction`", "`core/blacklist.py`",
                       "`Proposal.blacklisted`"):
            self.assertIn(needle, architecture)
        claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        for needle in ("`blacklist`", "`BlacklistAction`", "`WarningsScreen`"):
            self.assertIn(needle, claude)
