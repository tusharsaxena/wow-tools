"""One look and feel across the tools: the review screens share the left pane, its one-row action buttons and the
hint shape; the result screens share their layout and hint; Esc on a review goes back to the flavor picker. Each
check runs at BASE (120x30, Windows Terminal's default window), the size the screens are designed for; the LARGE
(160x45) checks make sure the trees grow while the left pane and the popups keep their widths, and one TINY (80x24)
smoke test makes sure every screen still opens and every control can still be focused there."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Button, Checkbox, DataTable, Tree
from textual.widgets._footer import FooterKey

from tests.fixtures import (BASE, LARGE, TINY, TuiTestCase, build_ace_tree, build_interface_tree, build_screenshot_tree,
                            build_wow_tree, make_config, settle)
from wowtools.tools import TOOLS as TOOL_INFO
from wowtools.tools.ace3_profile_manager.popups import ActionsScreen, NameScreen, TargetScreen
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import (FILTERS_WIDTH, RESULT_HINT, REVIEW_HINT, TREE_HINT, ConfirmScreen, InfoScreen,
                                 ProgressScreen)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp
from wowtools.ui.widgets import NavHint

POPUP_MAX_WIDTH = 100  # a popup or confirm at LARGE: a readable width, never stretched edge to edge
FORM_MAX_WIDTH = 100  # a settings form, at any size
TOOLS = ("wtf-cleaner", "screenshot-organizer", "interface-backup", "ace3-profile-manager")
# The action that leads to a result screen without a running-WoW popup in between (dry runs, a backup).
RUN_ACTION = {"wtf-cleaner": "dry_run", "screenshot-organizer": "dry_run", "interface-backup": "back_up",
              "ace3-profile-manager": "dry_run"}
# What a review needs before its run action has something to do (the Ace3 Profile Manager runs staged changes).
PREPARE = {"ace3-profile-manager": lambda review: (review.staging.everyone_to_default(list(review.staging.states)),
                                           review.refresh_view())}


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
                   "interface-backup": {"wow_check": list}, "ace3-profile-manager": {"wow_check": list}}
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options=options)

    async def open_review(self, app, pilot, tool):
        await pilot.pause()
        app.open_tool(tool)
        await settle(app, pilot)
        app.screen._save()  # first open: the tool's settings, saved as they are
        await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        app.screen.dismiss(ALL_FLAVORS)
        await settle(app, pilot)
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
                    self.assertEqual(buttons[2].label.plain, "Rescan")
                    hint = review.query_one(NavHint)
                    pane = filters.region
                    inside = pane._replace(width=pane.width - 1)  # anything but the border: not cut off
                    for widget in (*buttons, hint):
                        self.assert_inside(widget, inside)
                    text = hint.hint
                    self.assertTrue(text.startswith(REVIEW_HINT), text)
                    self.assertIn("r rescan · z undo · f flavors · t tools", text)
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

    async def test_review_tree_expands_and_collapses_all(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    self.assertIn(TREE_HINT + "r rescan", review.query_one(NavHint).hint)
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
        """Feedback round 1 review: several kinds of pending change and a scan warning (the bottom line takes two
        rows) still leave the whole hint in the left pane at BASE."""
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
            self.assertIn("scan warning", review.summary_text)
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
                    self.assertTrue(hint.startswith(RESULT_HINT), hint)
                    self.assertTrue(hint.endswith("f other flavor · t tools · q quit"), hint)
                    buttons = list(result.query(Button))
                    labels = [b.label.plain for b in buttons]
                    self.assertEqual(labels[0], "Rescan (r)")
                    self.assertEqual(labels[-3:], ["Other flavor (f)", "Tools (t)", "Quit (q)"])
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

    def assert_footer_whole(self, app) -> None:
        line = app.screen._compositor.render_strips()[-1].text
        keys = [key for key in app.screen.query(FooterKey) if key.display]
        self.assertTrue(keys, line)
        self.assertNotIn("palette", line)
        for key in keys:
            self.assertIn(f"{key.key_display} {key.description}", line)

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
        chain = list(screen.focus_chain)
        self.assertTrue(chain, name)
        reached = set()
        for _ in range(len(chain) + 1):
            await pilot.press("tab")
            await pilot.pause()
            self.assertIs(app.screen, screen, name)  # Tab never leaves the screen
            reached.add(screen.focused)
        self.assertEqual([w for w in chain if w not in reached], [], name)
