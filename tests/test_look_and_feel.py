"""One look and feel across the tools: the review screens share the left pane, its one-row action buttons and the
hint shape; the result screens share their layout and hint; Esc on a review goes back to the flavor picker. Each
check runs at BASE (120x30, Windows Terminal's default window), the size the screens are designed for; the LARGE
(160x45) checks make sure the trees grow while the left pane and the popups keep their widths, and one TINY (80x24)
smoke test makes sure every screen still opens and every control can still be focused there."""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from unittest import mock

from textual.widgets import Button, Checkbox, DataTable, OptionList, Tree
from textual.widgets._footer import FooterKey

from tests.fixtures import (BASE, LARGE, TINY, TuiTestCase, accept_disclaimer, assert_keys_on_buttons, build_ace_tree,
                            build_interface_tree, build_screenshot_tree, build_wow_tree, make_config, settle,
                            stage_sv_edit, submit_filter)
from wowtools import __version__
from wowtools.core.changelog import Changelog, parse_changelog
from wowtools.core.lock import LockInfo
from wowtools.core.updater import ReleaseInfo
from wowtools.tools import TOOLS as TOOL_INFO
from wowtools.tools.ace3_profile_manager.editor import Marker as AceMarker
from wowtools.tools.ace3_profile_manager.popups import ACTIONS_ROWS, ActionsScreen, NameScreen, TargetScreen
from wowtools.tools.ace3_profile_manager.review_screen import ProfileRecoveryScreen
from wowtools.tools.wtf_cleaner.review_screen import RecoveryScreen as WtfRecoveryScreen
from wowtools.tools.wtf_cleaner.safety import Marker as WtfMarker
from wowtools.ui.base import UpdateScreen
from wowtools.ui.branding import BANNER_NAME, TERMS, Banner, BottomBar, BrandBar, TermsText, VersionLine
from wowtools.ui.changelog_screen import CHANGELOG_HINT, VERSIONS_WIDTH, ChangelogScreen
from wowtools.ui.dialogs import (FILTERS_WIDTH, RESULT_HINT, REVIEW_HINT, TREE_HINT, ConfirmScreen, InfoScreen,
                                 ProgressScreen)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import MENU_HINT, LockScreen, WowToolsApp
from wowtools.ui.tree_filter import FILTER_BUTTON_ID, FILTER_HINT, FILTER_PLACEHOLDER, NO_MATCH_TEXT, FilterInput
from wowtools.ui.widgets import CHECK_OFF, RISK_TEXT, NavHint, RiskBanner, action_kind

POPUP_MAX_WIDTH = 100  # a popup or confirm at LARGE: a readable width, never stretched edge to edge
FORM_MAX_WIDTH = 100  # a settings form, at any size
# The tools whose screens are checked (the menu checks below cover every registered tool, TOOL_INFO).
TOOLS = ("wtf-cleaner", "screenshot-organizer", "interface-backup", "ace3-profile-manager", "sv-browser")
# The action that leads to a result screen without a running-WoW popup in between (dry runs, a backup).
RUN_ACTION = {"wtf-cleaner": "dry_run", "screenshot-organizer": "dry_run", "interface-backup": "back_up",
              "ace3-profile-manager": "dry_run", "sv-browser": "dry_run"}
# The reviews that can destroy data: the risk banner tops their left pane (spec D37).
DESTRUCTIVE_REVIEWS = ("wtf-cleaner", "ace3-profile-manager", "sv-browser")
# What a review needs before its run action has something to do (the Ace3 Profile Manager runs staged changes).
PREPARE = {"ace3-profile-manager": lambda review: (review.staging.everyone_to_default(list(review.staging.states)),
                                           review.refresh_view()),
           "sv-browser": stage_sv_edit}


def walk(node):
    """node and every node below it."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children)


class LookAndFeelTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_ace_tree(build_interface_tree(build_screenshot_tree(build_wow_tree(tmp / "World of Warcraft"))))
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "interface-backup": {"wow_check": list}, "ace3-profile-manager": {"wow_check": list},
                   "sv-browser": {"wow_check": list}}
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options=options)

    async def open_review(self, app, pilot, tool):
        await pilot.pause()
        app.open_tool(tool)
        await settle(app, pilot)
        if not isinstance(app.screen, FlavorScreen):
            app.screen._save()  # first open: the tool's settings, saved as they are
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        app.screen.dismiss(ALL_FLAVORS)
        await settle(app, pilot)
        await accept_disclaimer(app, pilot)
        return app.screen

    def assert_inside(self, widget, box):
        r = widget.region
        self.assertTrue(r.width > 0 and r.height > 0, f"{widget!r} is not shown: {r}")
        self.assertTrue(box.x <= r.x and box.y <= r.y and r.right <= box.right and r.bottom <= box.bottom,
                        f"{widget!r} is cut off: {r} not inside {box}")

    async def test_review_left_pane_is_the_same_in_every_tool(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    filters = review.query_one("#filters")
                    self.assertEqual(filters.outer_size.width, FILTERS_WIDTH)
                    buttons = list(review.query_one("#actions").query(Button))
                    self.assertEqual(len(buttons), 4)
                    self.assertEqual({b.region.y for b in buttons}, {buttons[0].region.y})  # one row
                    self.assertTrue(buttons[-1].label.plain.startswith("Undo last "), buttons[-1].label)
                    self.assertEqual(buttons[-1].variant, "warning")  # revert
                    self.assertEqual(buttons[2].label_text, "Rescan")
                    self.assertEqual([b.shortcut for b in buttons][1:], ["y" if tool != "interface-backup" else "e",
                                                                          "r", "z"])
                    for button in buttons:  # spec D17: the key on a second line, centred under the label
                        self.assertEqual(button.label.plain, f"{button.label_text}\n({button.shortcut})")
                        self.assertEqual(button.region.height, 4, button)
                    hint = review.query_one(NavHint)
                    pane = filters.region
                    inside = pane._replace(width=pane.width - 1)  # anything but the border: not cut off
                    for widget in (*buttons, hint):
                        self.assert_inside(widget, inside)
                    text = hint.hint
                    self.assertTrue(text.startswith(REVIEW_HINT), text)
                    self.assertIn(TREE_HINT + "f flavors · t tools", text)
                    for key in ("r rescan", "z undo", "y dry run", "w ", "b back up"):  # on the buttons (D17)
                        self.assertNotIn(key, text)
                    self.assertTrue(review.summary_text.startswith(("Selected: ", "Nothing to")),
                                    review.summary_text)
                    self.assertTrue(review.sub_title.startswith(f"{TOOL_INFO[tool].title} · All flavors"),
                                    review.sub_title)
                    await pilot.press("escape")  # Esc: back to the flavor picker, as f
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, FlavorScreen)

    async def test_review_hint_wraps_between_items_at_base(self):
        """At 120x30 the left pane's hint takes several rows; it breaks only between its " · " items, so a key
        never ends one row with its action on the next ("· r" / "rescan")."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    hint = review.query_one(NavHint)
                    rendered = str(hint.render())
                    lines = rendered.splitlines()
                    self.assertGreater(len(lines), 1, rendered)
                    self.assertEqual(hint.region.height, len(lines), rendered)
                    for line in lines[:-1]:
                        self.assertTrue(line.endswith(" ·"), lines)
                    self.assertEqual(rendered.replace("\n", " "), hint.hint)
                    items = set(hint.hint.split(" · "))
                    self.assertEqual({item for line in lines for item in line.removesuffix(" ·").split(" · ")}, items)

    async def test_review_left_pane_has_one_control_per_row(self):
        """Every focusable control of the left pane sits on its own row, so up/down reaches each one; only the
        action buttons share a row (left/right moves there)."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    actions = review.query_one("#actions")
                    controls = [w for w in review.query_one("#filters").query("*")
                                if w.focusable and actions not in w.ancestors]
                    rows = [w.region.y for w in controls]
                    self.assertEqual(len(rows), len(set(rows)), [(w.id, w.region) for w in controls])

    async def test_destructive_reviews_open_with_the_risk_banner(self):
        """Spec D37: the reviews that can destroy data start their left pane with the shared banner (red, bold,
        not focusable, inside the pane); the others have none."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    filters = review.query_one("#filters")
                    banners = list(review.query(RiskBanner))
                    if tool not in DESTRUCTIVE_REVIEWS:
                        self.assertEqual(banners, [])
                        continue
                    self.assertEqual(len(banners), 1)
                    banner = banners[0]
                    self.assertIs(filters.children[0], banner)
                    self.assertEqual(banner.render().plain, RISK_TEXT)
                    # two spaces: a terminal that draws the triangle as a two-cell emoji covers the first one
                    self.assertEqual(RISK_TEXT, "\u26a0  USE AT YOUR OWN RISK")
                    self.assertFalse(banner.focusable)
                    self.assertTrue(banner.styles.text_style.bold)
                    self.assertEqual(banner.styles.color.hex, app.get_css_variables()["error"])
                    pane = filters.region
                    self.assert_inside(banner, pane._replace(width=pane.width - 1))

    async def test_every_tree_screen_has_the_filter_box(self):
        """Spec D7 at BASE and TINY: every review and the Ace3 blacklist have the tree filter in the left pane, one
        row of its own with the same label; the hint names `/ filter` right before the tree keys; `/` reaches it,
        and Esc in it clears it and stays on the screen (the Interface Backup restore screen: its own tests)."""
        for size in (BASE, TINY):
            for tool in (*TOOLS, "blacklist"):
                with self.subTest(size=size, tool=tool):
                    app = self.make_app()
                    async with app.run_test(size=size) as pilot:
                        await pilot.pause()
                        app.open_tool("ace3-profile-manager" if tool == "blacklist" else tool)
                        await settle(app, pilot)
                        if not isinstance(app.screen, FlavorScreen):  # first open: the settings, saved as they are
                            app.screen._save()
                            await settle(app, pilot)
                        app.screen.dismiss(ALL_FLAVORS)
                        await settle(app, pilot)
                        await accept_disclaimer(app, pilot)
                        screen = app.screen
                        if tool == "blacklist":
                            screen.action_edit_blacklist()
                            await settle(app, pilot)
                            screen = app.screen
                        field = screen.filter_input()
                        self.assertIsInstance(field, FilterInput)
                        self.assertEqual(field.placeholder, FILTER_PLACEHOLDER)
                        self.assertEqual(field.outer_size.height, 1)
                        pane = screen.query_one("#filters")
                        self.assertIn(pane, field.ancestors)
                        others = [w for w in pane.query("*") if w.focusable and w is not field]
                        self.assertNotIn(field.region.y, [w.region.y for w in others])
                        button = screen.query_one(f"#{FILTER_BUTTON_ID}", Button)  # D40: beside the box
                        self.assertEqual((button.label_text, button.shortcut, action_kind(button)),
                                         ("Filter", "enter", "navigate"))
                        self.assertEqual(button.region.y, field.region.y)
                        self.assertFalse(button.focusable)
                        hint = screen.query_one(NavHint)
                        self.assertIn(FILTER_HINT + TREE_HINT.removesuffix(" · "), hint.hint)
                        if size == BASE:
                            inside = pane.region._replace(width=pane.region.width - 1)
                            for widget in (field, button, hint):
                                self.assert_inside(widget, inside)
                        tree = screen.query_one(screen.TREE_SELECTOR, Tree)
                        tree.focus()
                        await pilot.press("slash")
                        await pilot.pause()
                        await pilot.press("z", "z")
                        await settle(app, pilot)
                        self.assertIs(screen.focused, field)
                        self.assertEqual(field.value, "zz")
                        await pilot.press("escape")
                        await settle(app, pilot)
                        self.assertEqual(field.value, "")
                        self.assertIs(app.screen, screen)
                        self.assertIs(screen.focused, tree)

    async def test_bars_keep_their_place_while_a_scan_runs(self):
        """STD-7.25 (spec L2, L3) at BASE and LARGE: while a scan stands in for the tree (the scan box), and once it
        is done or has failed, the rows under the tree (the Ace3 guide and action bar, the Saved Variables Browser's
        action bar), the left pane's #actions button row and the bottom line are where they were before it, and the
        scan box takes the tree's space. The general check is the last one (box == tree): on a screen with nothing
        under the tree the rows cannot move. The scan worker is held on a gate, so the scan is open while the screen
        is measured: every review on a rescan, which succeeds or fails with a message far wider than the screen,
        the Ace3 blacklist on its first scan (a failed blacklist scan only notifies)."""
        cases = [(tool, outcome) for tool in TOOLS for outcome in ("done", "failed")] + [("blacklist", "done")]
        for size in (BASE, LARGE):
            for tool, outcome in cases:
                with self.subTest(size=size, tool=tool, outcome=outcome):
                    await self.check_bars_during_a_scan(size, tool, outcome)

    async def check_bars_during_a_scan(self, size, tool, outcome):
        app = self.make_app()
        async with app.run_test(size=size) as pilot:
            screen = await self.open_review(app, pilot, "ace3-profile-manager" if tool == "blacklist" else tool)
            gate = threading.Event()
            self.addCleanup(gate.set)  # a failed check never leaves a worker waiting
            if tool == "blacklist":
                from wowtools.tools.ace3_profile_manager.blacklist_screen import BlacklistScreen
                cls = BlacklistScreen
            else:
                cls = type(screen)
                before = self.bar_rows(screen)
            scan_worker = cls._scan_worker
            failure = "The scan failed: [Errno 13] Permission denied: '" + "/World of Warcraft/_retail_/WTF" * 12 + "'"

            def held(self_, *args, _worker=scan_worker, _gate=gate, **kwargs):
                _gate.wait(10)
                if outcome == "failed":
                    self_.app.call_from_thread(self_._scan_failed, failure)
                    return None
                return _worker(self_, *args, **kwargs)

            with mock.patch.object(cls, "_scan_worker", held):
                if tool == "blacklist":
                    screen.action_edit_blacklist()
                else:
                    screen.action_rescan()
                for _ in range(3):
                    await pilot.pause()
                screen = app.screen
                self.assertIsInstance(screen, cls)
                self.assertTrue(screen.query_one("#scan-box").display, "the scan is not shown")
                during = self.bar_rows(screen)
                box = screen.query_one("#scan-box").region
                gate.set()
                await settle(app, pilot)
            self.assertFalse(screen.query_one("#scan-box").display)
            if outcome == "failed":
                self.assertIn("Permission denied", screen.summary_text)
            self.assertEqual(during, self.bar_rows(screen))
            if tool != "blacklist":
                self.assertEqual(before, during)
            tree = screen.query_one(screen.TREE_SELECTOR, Tree).region
            self.assertEqual((box.y, box.height), (tree.y, tree.height), "the scan box is not the tree's space")

    @staticmethod
    def bar_rows(screen) -> dict[str, int]:
        """Where the left pane's button row, the rows under the tree (if any) and the bottom line start: id ->
        screen y."""
        rows = {"actions": screen.query_one("#actions").region.y, "summary": screen.query_one("#summary").region.y}
        for selector in ("#guide", "#tree-actions"):
            for widget in screen.query(selector):
                rows[selector] = widget.region.y
        return rows

    async def test_the_filter_waits_for_enter_or_its_button(self):
        """Spec D40 on every tree screen: typing in the box never rebuilds the tree; Enter applies it, the Filter
        button too, and an empty box submitted shows everything again."""
        for tool in (*TOOLS, "blacklist"):
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    screen = await self.open_review(app, pilot, "ace3-profile-manager" if tool == "blacklist"
                                                    else tool)
                    if tool == "blacklist":
                        screen.action_edit_blacklist()
                        await settle(app, pilot)
                        screen = app.screen
                    tree = screen.query_one(screen.TREE_SELECTOR, Tree)
                    before = [str(n.label) for n in tree.root.children]
                    tree.focus()
                    await pilot.press("slash", "z", "z", "z", "q")
                    await settle(app, pilot)
                    self.assertFalse(screen.filtering)
                    self.assertEqual([str(n.label) for n in tree.root.children], before)
                    await pilot.press("enter")
                    await settle(app, pilot)
                    self.assertTrue(screen.filtering)
                    self.assertEqual([str(n.label) for n in tree.root.children], [NO_MATCH_TEXT])
                    self.assertIs(screen.focused, tree)
                    screen.filter_input().value = ""
                    await pilot.click(f"#{FILTER_BUTTON_ID}")
                    await settle(app, pilot)
                    self.assertFalse(screen.filtering)
                    self.assertEqual([str(n.label) for n in tree.root.children], before)

    async def test_a_group_mark_counts_what_the_filter_shows(self):
        """One rule in every tick tree: with the filter set, a group's and the root's mark count only the items the
        filter shows (what Space on them ticks); the ticks it hides are said on the bottom line. Tick everything,
        filter to part of it, untick what is shown: the root is unticked (✘) in every tool, not part-ticked."""
        texts = {"wtf-cleaner": "auctionator", "screenshot-organizer": "classic", "interface-backup": "classic",
                 "ace3-profile-manager": "kickcd", "blacklist": "elv"}
        for tool, text in texts.items():
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    if tool == "blacklist":
                        review = await self.open_review(app, pilot, "ace3-profile-manager")
                        review.action_edit_blacklist()
                        await settle(app, pilot)
                        screen = app.screen
                    else:
                        screen = await self.open_review(app, pilot, tool)
                    tree = screen.query_one(screen.TREE_SELECTOR, Tree)
                    tree.focus()
                    await pilot.press("a")
                    await settle(app, pilot)
                    submit_filter(screen, text)
                    await settle(app, pilot)
                    tree.focus()
                    await pilot.press("n")
                    await settle(app, pilot)
                    self.assertTrue(tree.root.label.plain.startswith(CHECK_OFF), tree.root.label.plain)
                    self.assertIn("hidden by", str(screen.query_one("#summary").render()))

    async def test_a_filter_that_matches_nothing_says_so(self):
        """Every tick tree: a filter that matches nothing leaves one dim line saying so (status rows such as a
        flavor that was not scanned are filtered on their names too, so nothing else stays)."""
        for tool in (*TOOLS, "blacklist"):
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    screen = await self.open_review(app, pilot, "ace3-profile-manager" if tool == "blacklist"
                                                    else tool)
                    if tool == "blacklist":
                        screen.action_edit_blacklist()
                        await settle(app, pilot)
                        screen = app.screen
                    tree = screen.query_one(screen.TREE_SELECTOR, Tree)
                    submit_filter(screen, "zzzq")
                    await settle(app, pilot)
                    self.assertEqual([str(n.label) for n in tree.root.children], [NO_MATCH_TEXT])
                    submit_filter(screen, "")
                    await settle(app, pilot)
                    self.assertNotIn(NO_MATCH_TEXT, [str(n.label) for n in tree.root.children])

    async def test_the_filter_keeps_a_failed_scans_message(self):
        """Typing in the filter after a failed scan leaves the failure on the bottom line (nothing to rebuild)."""
        for tool, model in (("screenshot-organizer", "plan"), ("interface-backup", "scans")):
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    setattr(review, model, None)
                    review._scan_failed("The scan failed: disk gone")
                    await settle(app, pilot)
                    submit_filter(review, "re")
                    await settle(app, pilot)
                    self.assertIn("disk gone", str(review.query_one("#summary").render()))

    async def test_review_tree_expands_and_collapses_all(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    self.assertIn(TREE_HINT + "f flavors", review.query_one(NavHint).hint)
                    self.assertTrue(TREE_HINT.startswith("x expand all · c collapse all"))
                    tree = review.query_one(review.TREE_SELECTOR, Tree)
                    tree.focus()
                    await pilot.press("x")
                    await settle(app, pilot)
                    parents = [n for n in walk(tree.root) if n.children]
                    self.assertGreater(len(parents), 1)
                    self.assertEqual([n for n in parents if not n.is_expanded], [])
                    await pilot.press("c")
                    await settle(app, pilot)
                    self.assertEqual([n for n in walk(tree.root) if n.is_expanded], [tree.root])
                    self.assertIs(app.screen, review)  # c collapses: it never starts a run

    async def test_ace_tree_pane_fits_with_its_guide_and_action_bar(self):
        """The Ace3 review's tree pane holds the tree, the guidance line and the action bar: at BASE each button and
        the guide are drawn whole, the action bar takes at most 3 rows, the guide at most 2 and the tree keeps at
        least 12, with and without pending changes."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "ace3-profile-manager")
            for prepared in (False, True):
                if prepared:
                    PREPARE["ace3-profile-manager"](review)
                    await settle(app, pilot)
                    self.assertIn("pending change", str(review.query_one("#guide").render()))
                pane = review.query_one("#tree-pane").region
                buttons = list(review.query_one("#tree-actions").query(Button))
                self.assertEqual(len(buttons), 10)
                for widget in (*buttons, review.query_one("#guide")):
                    self.assert_inside(widget, pane)
                    self.assert_inside(widget, app.screen.region)
                self.assert_ace_tree_pane_rows(review, prepared)
                left = review.query_one("#filters").region
                for widget in (review.query_one("#pending"), review.query_one(NavHint)):
                    self.assert_inside(widget, left._replace(width=left.width - 1))

    def assert_ace_tree_pane_rows(self, review, note) -> None:
        """Review Focus 5 of the terminal size plan, at BASE: action bar <= 3 rows, guide <= 2, tree >= 12."""
        buttons = list(review.query_one("#tree-actions").query(Button))
        self.assertLessEqual(len({b.region.y for b in buttons}), 3, note)
        self.assertLessEqual(review.query_one("#tree-actions").region.height, 3, note)
        self.assertLessEqual(review.query_one("#guide").region.height, 2, note)
        self.assertGreaterEqual(review.query_one("#profiles", Tree).region.height, 12, note)

    async def test_ace_tree_keeps_12_rows_with_a_node_highlighted(self):
        """With pending changes and a node highlighted, the guide shows the pending line and the node's hint, one
        row each, and with the action bar still leaves the tree at least 12 rows at BASE."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "ace3-profile-manager")
            tree = review.query_one("#profiles", Tree)
            for prepared in (False, True):
                if prepared:
                    PREPARE["ace3-profile-manager"](review)
                    await settle(app, pilot)
                tree.root.expand_all()
                await settle(app, pilot)
                for kind in ("addon", "profile", "char"):
                    node = next(n for n in walk(tree.root) if n.data and n.data[0] == kind)
                    tree.move_cursor(node)
                    await settle(app, pilot)
                    guide = str(review.query_one("#guide").render())
                    self.assertEqual("pending change" in guide, prepared, guide)
                    self.assert_ace_tree_pane_rows(review, (prepared, kind, guide))
                    self.assert_inside(review.query_one("#guide"), review.query_one("#tree-pane").region)
                    # the pending line and the hint each take one row: both show (the hint is dropped only for
                    # a name too long to fit, GUIDE_MAX_ROWS)
                    self.assertEqual(len(guide.splitlines()), 2 if prepared else 1, guide)
                    self.assertEqual(review.query_one("#guide").region.height, len(guide.splitlines()), guide)
            await pilot.resize_terminal(*LARGE)  # plenty of room: the hint follows the pending line
            await settle(app, pilot)
            guide = str(review.query_one("#guide").render())
            self.assertIn("pending change", guide)
            self.assertEqual(len(guide.splitlines()), 2, guide)

    async def test_ace_guide_keeps_the_hint_with_many_changes_and_a_long_name(self):
        """At BASE, 100+ pending changes (a whole account's Everyone -> Default) and a long name ("Name - Realm")
        still show the pending line and the hint, one row each: the name is shortened with "…", not the hint
        dropped."""
        from wowtools.tools.ace3_profile_manager.ops import Summary
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "ace3-profile-manager")
            review.staging.summary = lambda: Summary(reassigned=150, files=12)
            long_name = "Shadowpriestess - Argent Dawn (EU)"  # 35 characters
            review._node_name = lambda data: long_name
            tree = review.query_one("#profiles", Tree)
            tree.root.expand_all()
            await settle(app, pilot)
            for kind in ("profile", "char", "addon"):
                node = next(n for n in walk(tree.root) if n.data and n.data[0] == kind)
                tree.move_cursor(node)
                await settle(app, pilot)
                guide = str(review.query_one("#guide").render())
                lines = guide.splitlines()
                self.assertEqual(len(lines), 2, guide)
                self.assertTrue(lines[0].startswith("150 pending changes, not written: "), guide)
                self.assertIn(long_name[:10], lines[1])
                self.assertIn("…", lines[1])
                self.assertEqual(review.query_one("#guide").region.height, 2, guide)
            tree.focus()
            await pilot.press("space")
            await settle(app, pilot)
            guide = str(review.query_one("#guide").render())
            self.assertEqual(len(guide.splitlines()), 2, guide)
            self.assertIn(" ticked: pick an action below", guide.splitlines()[1])

    async def test_ace_steps_wrap_between_steps(self):
        """The guide's four steps take two rows at BASE and LARGE and break only between steps, so "→ 4" never
        ends a row with "Apply (w)" on the next."""
        from wowtools.tools.ace3_profile_manager.report import STEPS
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "ace3-profile-manager")
            for size in (BASE, LARGE):
                with self.subTest(size=size):
                    await pilot.resize_terminal(*size)
                    await settle(app, pilot)
                    guide = review.query_one("#guide")
                    lines = str(guide.render()).splitlines()
                    self.assertEqual(review.guide_text, STEPS)
                    self.assertEqual(len(lines), 2, lines)
                    self.assertEqual(guide.region.height, 2, lines)
                    self.assertTrue(lines[0].endswith(" →"), lines)
                    self.assertRegex(lines[1], r"^\d ")
                    self.assertEqual(" ".join(lines), STEPS)

    async def test_ace_action_bar_is_two_rows_at_large(self):
        """Review Focus 5: at LARGE the whole action bar under the tree takes at most two rows, each button drawn
        whole."""
        app = self.make_app()
        async with app.run_test(size=LARGE) as pilot:
            review = await self.open_review(app, pilot, "ace3-profile-manager")
            bar = review.query_one("#tree-actions")
            buttons = list(bar.query(Button))
            self.assertLessEqual(len({b.region.y for b in buttons}), 2, [b.region for b in buttons])
            self.assertLessEqual(bar.region.height, 2)
            for button in buttons:
                self.assert_inside(button, review.query_one("#tree-pane").region)
                self.assertGreaterEqual(button.region.width, len(button.label.plain) + 2, button.label)

    async def test_ace_left_pane_hint_fits_with_several_kinds_of_pending_change(self):
        """Feedback round 1 review: several kinds of pending change and a scan warning (the Warnings button on the
        bottom line) still leave the whole hint in the left pane at BASE."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "ace3-profile-manager")
            staging = review.staging
            elv = next(k for k, s in staging.states.items() if s.file.addon == "ElvUI" and "Healer" in s.names())
            staging.delete({elv: ["Healer"]}, "Default")
            staging.copy(elv, "Default", "Default copy")
            staging.everyone_to_default(list(staging.states))
            leftovers = {k: sorted(s.leftovers) for k, s in staging.states.items() if s.leftovers}
            staging.remove_leftovers(leftovers)
            review.refresh_view()
            await settle(app, pilot)
            summary = staging.summary()
            self.assertTrue(summary.deleted and summary.copied and summary.reassigned and summary.removed)
            warnings = review.query_one("#btn-warnings")  # the scan warning, on the bottom line (spec W1)
            self.assertTrue(warnings.display)
            self.assertIn("scan warning", warnings.label.plain)
            self.assertEqual(warnings.region.y, review.query_one("#summary").region.y)
            left = review.query_one("#filters").region
            hint = review.query_one(NavHint)
            for widget in (review.query_one("#pending"), hint):
                self.assert_inside(widget, left._replace(width=left.width - 1))
            self.assertTrue(hint.hint.endswith("f flavors · t tools"))

    async def test_result_screens_share_one_layout(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    PREPARE.get(tool, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[tool]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    body = app.screen.title_text + "\n" + app.screen.body_text
                    self.assertIn("Retail", body)  # flavors by name, as in the result tables
                    self.assertNotRegex(body, r"(?<![/\\\w])_[a-z]+(_[a-z]+)*_(?![/\\\w])", body)  # never a bare folder
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    result = app.screen
                    self.assertTrue(result.sub_title.startswith(f"{TOOL_INFO[tool].title} · "), result.sub_title)
                    self.assertTrue(result.sub_title.endswith("result"), result.sub_title)
                    summary = result.query_one("#result-summary", DataTable)
                    self.assertEqual([c.label.plain for c in summary.columns.values()], ["Item", "Value"])
                    self.assertEqual(len(result.query(".result-detail")), 1)
                    result.query_one(BrandBar)
                    hint = result.query_one(NavHint).hint
                    buttons = list(result.query(Button))
                    # the buttons' keys are on the buttons (D17): with "Back to review (Esc)", Esc is too
                    esc_button = any(b.shortcut == "escape" for b in buttons)
                    self.assertEqual(hint, RESULT_HINT.removesuffix(" · Esc back") if esc_button else RESULT_HINT)
                    labels = [(b.label_text, b.shortcut) for b in buttons]
                    self.assertEqual(labels[0], ("Rescan", "r"))
                    self.assertEqual(labels[-3:], [("Other flavor", "f"), ("Tools", "t"), ("Quit", "q")])
                    for button in buttons:
                        self.assert_inside(button, app.screen.region)
                    self.assertEqual({b.region.y for b in buttons}, {buttons[0].region.y})

    async def test_settings_screens_open_at_the_title_and_fit(self):
        """Each settings form opens showing its title (not scrolled down to the focused field) and no checkbox
        label runs past the right edge at BASE."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    await pilot.pause()
                    app.open_tool(tool)
                    await settle(app, pilot)
                    screen = app.screen
                    form = screen.query_one("#settings")
                    self.assertEqual(form.scroll_y, 0)
                    self.assert_inside(screen.query_one(".title"), form.region)
                    self.assert_inside(screen.focused, form.region)
                    for box in screen.query(Checkbox):
                        self.assertLessEqual(box.region.right, form.content_region.right, box.id)
                        self.assertGreaterEqual(box.content_size.width, box.get_content_width(box.size, box.size),
                                                box.id)  # the whole label, not cut with an ellipsis

    async def test_settings_forms_fit_at_base_and_keep_a_readable_width(self):
        """A settings form is at most FORM_MAX_WIDTH columns wide and centred, at BASE and at LARGE (never
        stretched edge to edge); at BASE the whole form, its Save button included, shows without scrolling."""
        for tool in TOOLS:
            for size in (BASE, LARGE):
                with self.subTest(tool=tool, size=size):
                    app = self.make_app()
                    async with app.run_test(size=size) as pilot:
                        await pilot.pause()
                        app.open_tool(tool)
                        await settle(app, pilot)
                        form = app.screen.query_one("#settings")
                        box = form.region
                        self.assertLessEqual(box.width, FORM_MAX_WIDTH, box)
                        self.assertLessEqual(abs(box.x - (size[0] - box.right)), 1, box)  # centred
                        if size == BASE:
                            self.assertEqual(form.max_scroll_y, 0)
                            self.assert_inside(app.screen.query_one("#save", Button), box)

    async def test_general_settings_form_fits_at_base_and_keeps_a_readable_width(self):
        """The general settings (s on the tool menu) and the first-time setup are laid out as a tool's settings
        form: at most FORM_MAX_WIDTH columns, centred, and at BASE the whole form, Save included, shows."""
        from wowtools.ui.setup_screen import SetupScreen
        for first_run in (False, True):
            for size in (BASE, LARGE):
                with self.subTest(first_run=first_run, size=size):
                    app = self.make_app()
                    async with app.run_test(size=size) as pilot:
                        await pilot.pause()
                        app.push_screen(SetupScreen(self.cfg, first_run=first_run, detect=list))
                        await settle(app, pilot)
                        form = app.screen.query_one("#setup")
                        box = form.region
                        self.assertLessEqual(box.width, FORM_MAX_WIDTH, box)
                        self.assertLessEqual(abs(box.x - (size[0] - box.right)), 1, box)  # centred
                        if size == BASE:
                            self.assertEqual(form.max_scroll_y, 0)
                            self.assert_inside(app.screen.query_one("#save", Button), box)

    async def test_footer_shows_every_key_at_base(self):
        """At BASE the footer of the review and result screens shows each of its keys whole (the command palette
        key, which nothing documents, is not shown; Ctrl+P still opens it)."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    self.assert_footer_whole(app)
                    PREPARE.get(tool, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[tool]}")()
                    await settle(app, pilot)
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    self.assertIsNot(app.screen, review)
                    self.assert_footer_whole(app)

    async def test_keys_are_on_the_buttons_and_off_the_footer(self):
        """Spec D17 on every screen of every tool (review, confirm, result; the Ace3 blacklist and the Interface
        Backup restore screen; the tool's and the general settings): a button whose action has a key shows that key, and the footer lists
        no key a shown button carries (nor another key of that action, Esc for No). The reviews' footers keep the
        keys no button has: Space, a, n, /, x, c, f, t, q."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    assert_keys_on_buttons(self, review)
                    app.push_screen(app.flow.settings_screen("settings"))  # the tool's own settings form
                    await settle(app, pilot)
                    assert_keys_on_buttons(self, app.screen)
                    app.screen.dismiss(False)
                    await settle(app, pilot)
                    self.assertIs(app.screen, review)
                    footer = {key.key for key in review.query(FooterKey)}
                    self.assertLessEqual({"space", "a", "n", "slash", "x", "c", "f", "t", "q"}, footer, footer)
                    if tool == "ace3-profile-manager":
                        review.action_edit_blacklist()
                        await settle(app, pilot)
                        assert_keys_on_buttons(self, app.screen)
                        app.screen.dismiss(None)
                        await settle(app, pilot)
                    if tool == "interface-backup":
                        review.action_back_up()
                        await settle(app, pilot)
                        assert_keys_on_buttons(self, app.screen)  # the result, with Restore (e)
                        continue  # the restore screen: tests/test_interface_backup_app.py
                    PREPARE.get(tool, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[tool]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    assert_keys_on_buttons(self, app.screen)
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    self.assertIsNot(app.screen, review)
                    assert_keys_on_buttons(self, app.screen)
                    app.screen.dismiss("tools")
                    await settle(app, pilot)
                    app.action_settings()
                    await settle(app, pilot)
                    assert_keys_on_buttons(self, app.screen)

    async def test_no_keys_in_the_footer_under_a_popup(self):
        """Under a popup (a confirm here) the screen's keys do nothing, so its footer lists none of them; the bar keeps
        its two rows at 80 columns, so the screen does not move, and the keys come back when the popup closes."""
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot, "wtf-cleaner")
            before = [key.key for key in review.query(FooterKey)]
            self.assertIn("h", before)
            self.assertEqual(review.query_one(BottomBar).region.height, 2)
            review.action_dry_run()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertEqual(list(review.query(FooterKey)), [])
            self.assertEqual(review.query_one(BottomBar).region.height, 2)
            app.screen.dismiss(False)
            await settle(app, pilot)
            self.assertEqual([key.key for key in review.query(FooterKey)], before)

    async def test_keys_are_on_the_popup_buttons(self):
        """Spec D17 on the popups no review run reaches: the lock warning, the update offer, the Notes InfoScreen,
        the Ace3 Target and Name popups and both recovery warnings."""
        holder = LockInfo(12345, "other-pc", "2026-10-03T10:00:00", "windows", "abc")
        wtf_marker = WtfMarker(self.root / "backup.zip", "_retail_", self.root / "_retail_", "2026-01-01T00:00:00", 1,
                               "0.1.0", ["WTF/x.lua"])
        ace_marker = AceMarker("_retail_", self.root / "_retail_", self.root / "edited.zip", {"WTF/x.lua": "0"},
                               "2026-10-04T12:00:00+00:00", 1, "0.1.0", {"WTF/x.lua": "1"})
        popups = (lambda: LockScreen(holder, self.root / "wow-tools.lock"),
                  lambda: UpdateScreen(ReleaseInfo.from_version("9.9.9")),
                  lambda: InfoScreen("Notes", {"KickCD": ["Kaelys - Realm1"]}),
                  lambda: TargetScreen("Title", "Body", ["Default", "Healer"]), lambda: NameScreen("Title", "Body"),
                  lambda: WtfRecoveryScreen(wtf_marker, self.root), lambda: ProfileRecoveryScreen(ace_marker))
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            for make in popups:
                screen = make()
                with self.subTest(popup=type(screen).__name__):
                    app.push_screen(screen)
                    await settle(app, pilot)
                    assert_keys_on_buttons(self, screen)
                    screen.dismiss(None)
                    await settle(app, pilot)

    def assert_footer_whole(self, app) -> None:
        line = app.screen._compositor.render_strips()[-1].text
        keys = [key for key in app.screen.query(FooterKey) if key.display]
        self.assertTrue(keys, line)
        self.assertNotIn("palette", line)
        for key in keys:
            self.assertIn(f"{key.key_display} {key.description}", line)

    def bottom_line(self, app) -> str:
        return app.screen._compositor.render_strips()[-1].text

    def assert_brand_shown(self, app, text: str) -> None:
        """The BrandBar is on screen, on the last row next to the footer's keys (not under them), and `text` is in
        what the terminal shows on that row."""
        bar = app.screen.query_one(BrandBar)
        line = self.bottom_line(app)
        self.assertEqual(bar.region.bottom, app.screen.size.height, bar.region)
        self.assertGreater(bar.region.width, 0, bar.region)
        self.assertIn(text, line)
        for key in app.screen.query(FooterKey):
            if key.display:
                self.assertLessEqual(key.region.right, bar.region.x, (key, bar.region))

    async def test_brand_bar_shows_the_version_on_the_menu_and_every_review(self):
        """Spec D5: the version shares the footer's row (one BottomBar), so it shows on the tool menu (whole, at
        BASE and TINY), on every review and on a result screen (at least "v<version>" next to a compact footer),
        while the footer still shows each of its keys at BASE."""
        for size in (BASE, TINY):
            with self.subTest(screen="menu", size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    self.assert_brand_shown(app, f"Ka0s WoW Tools v{__version__}")
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    self.assert_brand_shown(app, f"v{__version__}")
                    self.assert_footer_whole(app)
                    PREPARE.get(tool, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[tool]}")()
                    await settle(app, pilot)
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    self.assert_brand_shown(app, f"Ka0s WoW Tools v{__version__}")

    def screen_lines(self, app) -> list[str]:
        return [strip.text for strip in app.screen._compositor.render_strips()]

    def assert_terms_whole(self, app, max_rows: int | None = None) -> None:
        """The terms of use show whole, right above the bottom row, in at most max_rows rows."""
        terms = app.screen.query_one(TermsText)
        rows = self.screen_lines(app)[terms.region.y:terms.region.bottom]
        self.assertEqual(terms.region.bottom, app.screen.size.height - 1, terms.region)
        self.assertEqual(" ".join(" ".join(rows).split()), TERMS)
        if max_rows is not None:
            self.assertLessEqual(len(rows), max_rows, rows)

    async def test_menu_shows_everything_at_base(self):
        """Spec D4/D6 at BASE: the version line right under the banner's name, every tool, the hint, the terms (two
        rows) and every footer key show at once, nothing scrolls; with an update found the version line says so."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            screen, lines = app.screen, self.screen_lines(app)
            self.assertEqual(screen.max_scroll_y, 0)
            name_row = next(i for i, line in enumerate(lines) if BANNER_NAME in line)
            self.assertEqual(lines[name_row + 1].strip(), f"v{__version__}")
            self.assertEqual(screen.query_one(VersionLine).region.y, name_row + 1)
            options = screen.query_one("#tools", OptionList)
            self.assertEqual(options.max_scroll_y, 0)
            text = "\n".join(lines)
            for tool in TOOL_INFO.values():
                self.assertIn(f"{tool.title}   ", text)
                self.assertIn(tool.description, text)
            self.assertIn(MENU_HINT, text)
            self.assert_terms_whole(app, max_rows=2)
            self.assert_footer_whole(app)
            app.release = ReleaseInfo.from_version("9.9.9")
            await settle(app, pilot)
            self.assertEqual(self.screen_lines(app)[name_row + 1].strip(),
                             f"v{__version__} · v9.9.9 available, press u to update")

    async def test_menu_keeps_terms_and_footer_and_reaches_every_tool_when_small(self):
        """At TINY (and shorter) the terms and the footer stay on screen; the tool list scrolls instead, and every
        tool can be highlighted and is then on screen. Below about 115 columns the D6 wording takes three rows (it
        cannot fit two at 80), pinned here as accepted."""
        for size in (TINY, (80, 18)):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    self.assertEqual(app.screen.max_scroll_y, 0)
                    self.assert_terms_whole(app, max_rows=3)
                    self.assert_footer_whole(app)
                    self.assert_hint_shown(app)
                    self.assertIn(f"v{__version__}", "\n".join(self.screen_lines(app)))
                    options = app.screen.query_one("#tools", OptionList)
                    for index, tool in enumerate(TOOL_INFO.values()):
                        if index:
                            await pilot.press("down")
                            await pilot.pause()
                        self.assertEqual(options.highlighted, index)
                        self.assertIn(tool.title, "\n".join(self.screen_lines(app)), size)
                    self.assert_terms_whole(app, max_rows=3)
                    await pilot.press("enter")
                    await settle(app, pilot)
                    self.assertIsNotNone(app.flow)

    def assert_hint_shown(self, app) -> None:
        """The menu hint shows whole, below the tool list and above the terms."""
        screen = app.screen
        hint = screen.query_one(NavHint)
        options = screen.query_one("#tools", OptionList)
        self.assertTrue(hint.display)
        self.assertGreaterEqual(hint.region.y, options.region.bottom, (hint.region, options.region))
        self.assertLessEqual(hint.region.bottom, screen.query_one(TermsText).region.y, hint.region)
        self.assertIn(MENU_HINT, self.screen_lines(app)[hint.region.y])

    async def test_menu_drops_the_art_before_the_tool_list_scrolls(self):
        """A 30-row window narrower than 120 columns wraps each description onto two rows; the shield art then gives
        way to its name line so every tool still shows without the list scrolling, and comes back at full width."""
        app = self.make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await settle(app, pilot)
            screen = app.screen
            options = screen.query_one("#tools", OptionList)
            self.assertEqual(options.max_scroll_y, 0)
            self.assertFalse(screen.query_one(Banner).art)
            self.assert_hint_shown(app)
            await pilot.resize_terminal(*BASE)
            await settle(app, pilot)
            self.assertTrue(screen.query_one(Banner).art)
            self.assertEqual(options.max_scroll_y, 0)

    async def test_menu_hides_the_hint_below_tiny_rather_than_overlap(self):
        """Below the TINY floor the list keeps one tool row: the hint is hidden on purpose, and the list, the terms
        and the footer do not overlap."""
        for size in ((80, 16), (80, 14)):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    screen = app.screen
                    options = screen.query_one("#tools", OptionList)
                    self.assertFalse(screen.query_one(NavHint).display)
                    self.assertGreaterEqual(options.region.height, 3)
                    self.assertLessEqual(options.region.bottom, screen.query_one(TermsText).region.y)
                    self.assert_terms_whole(app, max_rows=3)

    async def test_changelog_screen_at_base_and_tiny(self):
        """Spec D3: the changelog in the suite's two-pane look at BASE and still whole at TINY: the version list and
        its hint inside the left pane (VERSIONS_WIDTH wide), one whole row per version, newest first, the current one
        marked, the notes filling the right, the footer's keys whole and the version on the bottom row."""
        changelog = Changelog(parse_changelog(
            "## [Unreleased]\n- Soon.\n## [0.10.0] - 2027-01-02\n- Ten.\n## [0.2.0] - 2026-11-01\n- Two.\n"
            "## [0.1.0] - 2026-10-05\n- One.\n"))
        for size in (BASE, TINY):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    app.push_screen(ChangelogScreen(changelog, current="0.2.0"))
                    await settle(app, pilot)
                    screen = app.screen
                    pane = screen.query_one("#filters")
                    self.assertEqual(pane.outer_size.width, VERSIONS_WIDTH)
                    versions = screen.query_one("#versions", OptionList)
                    hint = screen.query_one(NavHint)
                    self.assertEqual(hint.hint, CHANGELOG_HINT)
                    inside = pane.region._replace(width=pane.region.width - 1)  # anything but the border
                    for widget in (versions, hint):
                        self.assert_inside(widget, inside)
                    self.assertEqual((versions.max_scroll_x, versions.max_scroll_y), (0, 0))
                    lines = self.screen_lines(app)
                    rows = [line for line in lines if line.startswith(" ▊ ")]
                    self.assertEqual(len(rows), 4, rows)  # one row each
                    for row, text in zip(rows, ("Unreleased", "v0.10.0  2027-01-02", "v0.2.0   2026-11-01  current",
                                                "v0.1.0   2026-10-05")):
                        self.assertIn(text, row)
                    notes = screen.query_one("#notes")
                    self.assertEqual((notes.region.x, notes.region.right), (pane.region.right, size[0]))
                    self.assertIn("v0.2.0 · 2026-11-01", "\n".join(lines))
                    self.assert_footer_whole(app)
                    self.assertIn(f"v{__version__}", lines[-1])

    async def test_every_review_still_renders_at_tiny_with_an_update(self):
        """Pinned as accepted (T3.1): at 80x24 a review's compact footer overflows 80 columns and the brand bar
        gets no room, but the review opens and renders with an update found."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=TINY) as pilot:
                    app.release = ReleaseInfo.from_version("9.9.9")
                    review = await self.open_review(app, pilot, tool)
                    self.assertIs(app.screen, review)
                    self.assertTrue(app.screen.query_one(BrandBar).text.startswith("⬆ v9.9.9"))

    async def test_brand_bar_shows_the_update_notice(self):
        """Once a release is found the bottom row says so: whole on the tool menu, in a shorter wording that still
        names the key on every review (the footer keeps each of its keys at BASE). Spec D15: the Ace3 review binds
        u to Unlock, so there the notice sends the user to the tool menu and never says "press u" alone."""
        release = ReleaseInfo.from_version("9.9.9")
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            app.release = release
            await settle(app, pilot)
            self.assert_brand_shown(app, f"⬆ v9.9.9 available, press u to update · Ka0s WoW Tools v{__version__}")
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    app.release = release
                    await self.open_review(app, pilot, tool)
                    bar = app.screen.query_one(BrandBar)
                    shown = bar.shown_text
                    self.assert_brand_shown(app, shown)
                    self.assert_footer_whole(app)
                    if tool == "ace3-profile-manager":
                        self.assertIn("v9.9.9 available, press u on the tool menu to update", bar.text)
                        self.assertIn(shown, ("⬆ v9.9.9: menu, u", "⬆ v9.9.9 (menu)"))
                    else:
                        self.assertIn("v9.9.9 available, press u to update", bar.text)
                        self.assertIn(shown, ("⬆ v9.9.9: press u", "⬆ v9.9.9 (u)"))

    async def test_ace_left_pane_has_view_and_show_headings(self):
        """Addendum B: at 120x30 the Ace3 left pane has room for its View and Show section headings again, and the
        checkboxes carry short labels under them, one per row."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "ace3-profile-manager")
            filters = review.query_one("#filters")
            headings = [str(w.render()) for w in filters.query(".section")]
            self.assertEqual(headings[:2], ["View", "Show"])
            labels = [b.label.plain for b in filters.query(Checkbox)]
            self.assertEqual(labels, ["By addon", "By character", "Only addons with 2+ profiles",
                                      "Only unused profiles", "Leftover characters", "Blacklisted addons"])
            view, show = list(filters.query(".section"))[:2]
            boxes = list(filters.query(Checkbox))
            self.assertTrue(view.region.y < boxes[0].region.y and boxes[1].region.y < show.region.y
                            < boxes[2].region.y, [view.region, show.region, [b.region for b in boxes]])

    async def test_review_tree_grows_at_large_while_the_left_pane_keeps_its_width(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    tree = review.query_one(review.TREE_SELECTOR, Tree)
                    filters = review.query_one("#filters")
                    base_tree, base_filters = tree.region, filters.outer_size.width
                    await pilot.resize_terminal(*LARGE)
                    await settle(app, pilot)
                    self.assertGreater(tree.region.width, base_tree.width)
                    self.assertGreater(tree.region.height, base_tree.height)
                    self.assertEqual(filters.outer_size.width, base_filters)

    async def test_popups_keep_a_readable_width_at_large(self):
        """At LARGE each tool's run confirm, the progress popup and the Ace3 popups stay at most POPUP_MAX_WIDTH
        columns wide and centred; at BASE they fit with room around them."""
        groups = {f"Addon{i}": [f"Char{j} - Realm" for j in range(i)] for i in range(20)}
        popups = (lambda: ConfirmScreen("Title", "Body"), lambda: ConfirmScreen("Title", "Body", groups=groups),
                  lambda: InfoScreen("Title", groups), lambda: ProgressScreen(first_stage="check"),
                  lambda: TargetScreen("Title", "Body", ["Default", "Healer"]), lambda: NameScreen("Title", "Body"),
                  ActionsScreen)
        for size in (BASE, LARGE):
            app = self.make_app()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                for make in popups:
                    screen = make()
                    with self.subTest(size=size, popup=type(screen).__name__):
                        app.push_screen(screen)
                        await settle(app, pilot)
                        self.assert_popup_width(screen, size)
                        screen.dismiss(None)
                        await settle(app, pilot)
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=LARGE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    PREPARE.get(tool, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[tool]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    self.assert_popup_width(app.screen, LARGE)

    async def test_ace_popups_show_everything_at_base(self):
        """At BASE the quick actions menu lists every action without scrolling, and a target popup shows a
        12-line body whole (one line per addon of a delete) with its buttons and hint, with room around it."""
        body = "\n".join(f"Addon{i}: Default, Healer (1 character move)" for i in range(12))
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            for screen in (ActionsScreen(), TargetScreen("Delete profiles", body, ["Default", "Healer"])):
                with self.subTest(popup=type(screen).__name__):
                    app.push_screen(screen)
                    await settle(app, pilot)
                    box = screen.query_one(".popup-box")
                    self.assertEqual(box.max_scroll_y, 0)
                    shown = [w for w in screen.query("Button, Input, NavHint, OptionList, .popup-body")
                             if w.display]  # not the Select's closed overlay
                    for widget in shown:
                        self.assert_inside(widget, box.region)
                    for scroller in screen.query("OptionList, .popup-body"):
                        if scroller.display:
                            self.assertEqual(scroller.max_scroll_y, 0, scroller)  # nothing scrolled out of view
                    self.assertTrue(box.region.y >= 1 and box.region.bottom <= BASE[1] - 1, box.region)
                    self.assert_popup_width(screen, BASE)
                    screen.dismiss(None)
                    await settle(app, pilot)

    async def test_ace_target_dropdown_shows_as_many_rows_as_the_actions_menu(self):
        """The delete/assign target dropdown (the Select's overlay, an OptionList) shows up to ACTIONS_ROWS
        profiles without scrolling, like the quick actions menu, not Select's default of 10."""
        app = self.make_app()
        async with app.run_test(size=LARGE) as pilot:
            await pilot.pause()
            screen = TargetScreen("Delete profiles", "Body", [f"Profile{i}" for i in range(30)])
            app.push_screen(screen)
            await settle(app, pilot)
            overlay = screen.query_one("SelectOverlay")
            self.assertEqual(overlay.styles.max_height.value, ACTIONS_ROWS + 2)

    def assert_popup_width(self, screen, size) -> None:
        box = screen.children[0].region
        if size == LARGE:
            self.assertLessEqual(box.width, POPUP_MAX_WIDTH, box)
            self.assertLessEqual(abs(box.x - (size[0] - box.right)), 1, box)  # centred
        else:
            self.assertTrue(box.x >= 2 and box.right <= size[0] - 2, box)  # room around it

    async def test_tiny_terminal_still_works(self):
        """80x24 is not a design target but must keep working: every tool's settings, review and result screens
        open, nothing raises, and Tab reaches every focusable control. Nothing about the layout is asserted."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=TINY) as pilot:
                    await pilot.pause()
                    app.open_tool(tool)
                    await settle(app, pilot)
                    await self.tab_through(app, pilot, "settings")
                    app.screen._save()
                    await settle(app, pilot)
                    app.screen.dismiss(ALL_FLAVORS)
                    await settle(app, pilot)
                    await accept_disclaimer(app, pilot)
                    review = app.screen
                    await self.tab_through(app, pilot, "review")
                    PREPARE.get(tool, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[tool]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    await self.tab_through(app, pilot, "confirm")
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    self.assertIsNot(app.screen, review)
                    await self.tab_through(app, pilot, "result")

    async def tab_through(self, app, pilot, name: str) -> None:
        screen = app.screen
        self.assert_buttons_coloured(app, screen, name)
        chain = list(screen.focus_chain)
        self.assertTrue(chain, name)
        reached = set()
        for _ in range(len(chain) + 1):
            await pilot.press("tab")
            await pilot.pause()
            self.assertIs(app.screen, screen, name)  # Tab never leaves the screen
            reached.add(screen.focused)
        self.assertEqual([w for w in chain if w not in reached], [], name)

    def assert_buttons_coloured(self, app, screen, name: str) -> None:
        """Every button was built by action_button and shows its kind's theme colour (ACTION_CSS applies)."""
        variables = app.get_css_variables()
        for button in screen.query(Button):
            kind = action_kind(button)
            self.assertIsNotNone(kind, f"{name}: {button.id} has no action kind")
            if not button.disabled and not button.mouse_hover:
                self.assertEqual(button.styles.background.hex, variables[f"act-{kind}"], f"{name}: {button.id}")
                self.assertEqual(button.styles.color.hex, variables[f"act-{kind}-text"], f"{name}: {button.id}")
