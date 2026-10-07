"""Saved Variables Browser flow and review (spec D1-D3, D12, D18, §5): first-run settings, flavor picker with All
flavors, the USE AT YOUR OWN RISK warning once per opening of the tool, and the review's Browse view (the file tree,
lazy loading, the child cap, x / c, the filter on loaded labels, the buttons, leaving with staged edits)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Button, Tree

from tests.fixtures import (BASE, TINY, TuiTestCase, accept_disclaimer, assert_keys_on_buttons, build_sv_tree,
                            make_config, settle, submit_filter)
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools.sv_browser.app import SvBrowserSettingsScreen
from wowtools.tools.sv_browser.model import CHILD_CAP
from wowtools.tools.sv_browser.popups import ACCEPT, BACK, DISCLAIMER_TITLE, DisclaimerScreen
from wowtools.tools.sv_browser.review_screen import READING, SvReviewScreen
from wowtools.tools.sv_browser.settings import load_settings
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.tree_filter import NO_MATCH_TEXT
from wowtools.ui.widgets import RISK_TEXT, RiskBanner, action_kind

TOOL = "sv-browser"


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def labels(node) -> list[str]:
    return [child.label.plain for child in node.children]


def child(node, start: str):
    """The child of node whose label starts with `start`."""
    found = [c for c in node.children if c.label.plain.startswith(start)]
    assert len(found) == 1, (start, labels(node))
    return found[0]


class SvBrowserTestBase(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.root = build_sv_tree(self.tmp / "World of Warcraft")
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={TOOL: {"wow_check": list}})

    def tool_cfg(self) -> Config:
        return Config(self.config_dir / "sv-browser.cfg").load()

    async def open_picker(self, app, pilot):
        await pilot.pause()
        app.open_tool(TOOL)
        await settle(app, pilot)
        if isinstance(app.screen, SvBrowserSettingsScreen):  # first open: the tool's settings
            app.screen._save()
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        return app.screen

    async def open_review(self, app, pilot, flavor: str | None = None) -> SvReviewScreen:
        picker = await self.open_picker(app, pilot)
        picker.dismiss(ALL_FLAVORS if flavor is None else next(f for f in picker.flavors if f.folder == flavor))
        await settle(app, pilot)
        await accept_disclaimer(app, pilot)
        self.assertIsInstance(app.screen, SvReviewScreen)
        return app.screen

    async def open_node(self, review, pilot, node):
        node.expand()
        await settle(review.app, pilot)
        return review._tree_nodes.get(review_ident(node))


def select(tree, node) -> None:
    tree.get_node_at_line(0)  # lay the lines out first: nodes a load just added have no line yet
    tree.move_cursor(node)


def review_ident(node):
    from wowtools.tools.sv_browser.review_screen import ident
    return ident(node.data)


class SvBrowserFlowTest(SvBrowserTestBase):
    async def test_first_open_asks_settings_then_the_warning_then_the_review(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            app.open_tool(TOOL)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvBrowserSettingsScreen)
            app.screen._save()
            await settle(app, pilot)
            picker = app.screen
            self.assertIsInstance(picker, FlavorScreen)
            self.assertTrue(picker.include_all)
            self.assertEqual(sorted(f.folder for f in picker.flavors), ["_classic_era_", "_retail_"])
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            warning = app.screen
            self.assertIsInstance(warning, DisclaimerScreen)
            self.assertEqual(warning.title_text, DISCLAIMER_TITLE)
            self.assertIn("you are responsible for what you change", warning.message_text)
            self.assertEqual(warning.focused.id, ACCEPT)  # I understand is the default
            buttons = {b.id: b for b in warning.query(Button)}
            self.assertEqual((buttons[ACCEPT].label_text, action_kind(buttons[ACCEPT])), ("I understand", "confirm"))
            self.assertEqual((buttons[BACK].label_text, action_kind(buttons[BACK]), buttons[BACK].shortcut),
                             ("Back", "cancel", "escape"))
            assert_keys_on_buttons(self, warning)
            with capture_events() as events:
                warning.choose(ACCEPT)
                await settle(app, pilot)
            names = [e["event"] for e in events]
            self.assertIn("svb.disclaimer_accepted", names)
            self.assertIn("svb.started", names)
            self.assertIn("svb.scan_completed", names)
            review = app.screen
            self.assertIsInstance(review, SvReviewScreen)
            self.assertEqual(len(review.flavors), 2)
            self.assertEqual(review.sub_title, "Saved Variables Browser · All flavors · Browse")
            self.assertEqual(load_settings(self.tool_cfg()).last_flavor_choice, "")
            await pilot.press("escape")  # Esc: back to the flavor picker
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            self.assertEqual(app.screen.last, "")  # All flavors highlighted again
            app.screen.dismiss(ALL_FLAVORS)  # accepted once in this opening of the tool: not asked again
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvReviewScreen)

    async def test_back_or_esc_on_the_warning_goes_back_to_the_flavors_and_reading_nothing(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            for answer in ("button", "escape"):
                with self.subTest(answer=answer):
                    picker = await self.open_picker(app, pilot) if answer == "button" else app.screen
                    picker.dismiss(ALL_FLAVORS)
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, DisclaimerScreen)
                    with capture_events() as events:
                        if answer == "button":
                            await pilot.click("#back")
                        else:
                            await pilot.press("escape")
                        await settle(app, pilot)
                    names = [e["event"] for e in events]
                    self.assertIn("svb.disclaimer_declined", names)
                    self.assertNotIn("svb.scan_completed", names)
                    self.assertIsInstance(app.screen, FlavorScreen)

    async def test_the_warning_comes_back_each_time_the_tool_is_opened(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            review.action_leave("tools")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)
            picker = await self.open_picker(app, pilot)
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, DisclaimerScreen)

    async def test_a_rescan_does_not_ask_again(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIsNotNone(review.scan)

    async def test_one_flavor_has_no_account_picker_and_t_goes_to_the_menu(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")  # two accounts, no account picker (D3)
            self.assertEqual([f.folder for f in review.flavors], ["_retail_"])
            self.assertEqual(load_settings(self.tool_cfg()).last_flavor_choice, "_retail_")
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)
            self.assertIsNone(app.flow)


class SvBrowseViewTest(SvBrowserTestBase):
    async def test_left_pane_has_the_banner_filter_pending_line_and_buttons(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            pane = review.query_one("#filters")
            self.assertEqual(review.query_one(RiskBanner).render().plain, RISK_TEXT)
            self.assertEqual(review.query_one("#pending").render().plain,
                             "Staged: 0 edits · Ticked: 0 results in 0 files")
            self.assertEqual([(b.label_text, b.shortcut) for b in review.query_one("#search-row").query(Button)],
                             [("Search", "S")])
            self.assertEqual([(b.label_text, b.shortcut) for b in review.query_one("#actions").query(Button)],
                             [("Apply", "w"), ("Dry run", "y"), ("Rescan", "r"), ("Undo last change", "z")])
            self.assertEqual([(b.label_text, b.shortcut, action_kind(b))
                              for b in review.query_one("#tree-actions").query(Button)],
                             [("Edit value", "e", "overwrite"), ("Rename key", "k", "overwrite"),
                              ("Delete key", "d", "destructive"), ("Unstage", "backspace", "cancel"),
                              ("View", "v", "navigate")])
            controls = [w for w in pane.query("*") if w.focusable and review.query_one("#actions") not in w.ancestors]
            rows = [w.region.y for w in controls]
            self.assertEqual(len(rows), len(set(rows)))
            for widget in (*review.query("#filters Button"), review.query_one(RiskBanner)):
                r, box = widget.region, pane.region
                self.assertTrue(r.width > 0 and box.x <= r.x and r.right <= box.right - 1, (widget, r, box))
            assert_keys_on_buttons(self, review)
            self.assertTrue(review.summary_text.startswith("Selected: "), review.summary_text)
            self.assertIn("9 files in 2 flavors", review.summary_text)  # Broken.lua included, the .bak not

    async def test_tree_lists_flavors_accounts_owners_and_files_without_reading_them(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            root = review.query_one("#browse", Tree).root
            self.assertEqual([n.split("  ")[0] for n in labels(root)], ["Classic Era", "Retail"]
                             if labels(root)[0].startswith("Classic") else ["Retail", "Classic Era"])
            retail = child(root, "Retail")
            self.assertEqual([n.split("  ")[0] for n in labels(retail)], ["ACCT1", "ACCT2"])
            acct1 = child(retail, "ACCT1")
            self.assertEqual([n.split("  ")[0] for n in labels(acct1)], ["Account-wide", "Realm1"])
            wide = child(acct1, "Account-wide")
            names = [n.split("  ")[0] for n in labels(wide)]
            self.assertEqual(sorted(names), ["Blizzard_Console.lua", "Broken.lua", "Details.lua", "ElvUI.lua"])
            self.assertRegex(child(wide, "ElvUI.lua").label.plain, r"^ElvUI\.lua  \d+(\.\d)? (B|KB)$")
            realm = child(acct1, "Realm1")
            self.assertEqual([n.split("  ")[0] for n in labels(realm)], ["Kaelys"])
            self.assertEqual([n.split("  ")[0] for n in labels(child(realm, "Kaelys"))], ["ElvUI.lua"])
            self.assertEqual(review.docs, {})  # the scan reads no file (D18)

    async def test_opening_a_file_and_a_table_loads_them_in_a_worker(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            root = review.query_one("#browse", Tree).root
            wide = child(child(child(root, "Retail"), "ACCT1"), "Account-wide")
            elv = child(wide, "ElvUI.lua")
            self.assertTrue(elv.allow_expand)
            elv = await self.open_node(review, pilot, elv)
            self.assertEqual(labels(elv), ["ElvDB {1}", "ElvPrivateDB {1}", "ElvVersion = nil"])
            self.assertNotIn(READING, labels(elv))
            db = await self.open_node(review, pilot, child(elv, "ElvDB"))
            profiles = await self.open_node(review, pilot, child(db, "profiles"))
            default = await self.open_node(review, pilot, child(profiles, "Default"))
            general = await self.open_node(review, pilot, child(default, "general"))
            self.assertEqual(labels(general), ['font = "Friz Quadrata TT"', "fontSize = 12",
                                               "scale = 0.6000000000000001", "autoRepair = true"])
            unit = await self.open_node(review, pilot, child(default, "unitframe"))
            self.assertIn("[true] = \"yes\"", labels(unit))
            self.assertIn("[1] = \"first\"", labels(unit))
            # the bottom line names the highlighted node's place
            tree = review.query_one("#browse", Tree)
            select(tree, child(general, "font ="))
            await settle(app, pilot)
            self.assertIn("ElvUI.lua", review.summary_text)
            self.assertIn('general › font = "Friz Quadrata TT"', review.summary_text)

    async def test_a_file_that_is_not_lua_is_a_red_row(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            root = review.query_one("#browse", Tree).root
            wide = child(child(child(root, "Retail"), "ACCT1"), "Account-wide")
            with capture_events() as events:
                broken = await self.open_node(review, pilot, child(wide, "Broken.lua"))
            self.assertIn("svb.file_unreadable", [e["event"] for e in events])
            self.assertTrue(broken.label.plain.endswith("can't read"), broken.label.plain)
            self.assertTrue(labels(broken)[0].startswith("can't read: Broken.lua is not readable Lua"),
                            labels(broken))
            tree = review.query_one("#browse", Tree)
            select(tree, broken.children[0])
            await settle(app, pilot)
            for button in ("#act-edit", "#act-rename", "#act-delete"):
                self.assertTrue(review.query_one(button, Button).disabled, button)

    async def test_a_big_table_shows_its_first_children_and_how_many_more(self):
        sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT2" / "SavedVariables"
        (sv / "Big.lua").write_bytes(("BigDB = {\r\n" + "".join(f'["k{i}"] = {i},\r\n' for i in range(CHILD_CAP + 7))
                                      + "}\r\n").encode())
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            root = review.query_one("#browse", Tree).root
            wide = child(child(child(root, "Retail"), "ACCT2"), "Account-wide")
            big = await self.open_node(review, pilot, child(wide, "Big.lua"))
            db = await self.open_node(review, pilot, child(big, "BigDB"))
            self.assertEqual(len(db.children), CHILD_CAP + 1)
            self.assertEqual(labels(db)[-1], "… 7 more")
            self.assertFalse(db.children[-1].allow_expand)

    async def test_x_opens_down_to_the_files_only_and_c_collapses(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#browse", Tree)
            tree.focus()
            await pilot.press("x")
            await settle(app, pilot)
            files = [n for n in walk(tree.root) if n.data is not None and n.data[0] == "file"]
            self.assertEqual(len(files), 9)
            self.assertEqual([n for n in files if n.is_expanded], [])
            groups = [n for n in walk(tree.root) if n.children]
            self.assertEqual([n.label.plain for n in groups if not n.is_expanded], [])
            self.assertEqual(review.docs, {})  # x reads nothing
            await pilot.press("c")
            await settle(app, pilot)
            self.assertEqual([n for n in walk(tree.root) if n.is_expanded], [tree.root])

    async def test_the_filter_matches_what_has_been_read(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#browse", Tree)
            submit_filter(review, "autorepair")
            await settle(app, pilot)
            self.assertEqual(labels(tree.root), [NO_MATCH_TEXT])  # ElvUI.lua is not read yet
            submit_filter(review, "")
            await settle(app, pilot)
            wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
            elv = await self.open_node(review, pilot, child(wide, "ElvUI.lua"))
            db = await self.open_node(review, pilot, child(elv, "ElvDB"))
            profiles = await self.open_node(review, pilot, child(db, "profiles"))
            default = await self.open_node(review, pilot, child(profiles, "Default"))
            await self.open_node(review, pilot, child(default, "general"))
            submit_filter(review, "autorepair")
            await settle(app, pilot)
            shown = [n.label.plain for n in walk(tree.root) if n.data is not None and n.data[0] == "node"]
            self.assertEqual(shown, ["ElvDB {1}", "profiles {1}", "Default {2}", "general {4}", "autoRepair = true"])
            submit_filter(review, "kaelys")  # a group's name: everything in it shows
            await settle(app, pilot)
            files = [n.label.plain.split("  ")[0] for n in walk(tree.root) if n.data and n.data[0] == "file"]
            self.assertEqual(files, ["ElvUI.lua"])

    async def test_the_buttons_follow_the_highlighted_node(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#browse", Tree)
            wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
            elv = await self.open_node(review, pilot, child(wide, "ElvUI.lua"))
            db = await self.open_node(review, pilot, child(elv, "ElvDB"))

            def enabled() -> list[str]:
                return [b.id for b in review.query("#tree-actions Button").results(Button) if not b.disabled]

            for node, expected in ((elv, []), (child(elv, "ElvVersion"), ["act-edit"]), (child(elv, "ElvDB"), []),
                                   (child(db, "profiles"), ["act-rename", "act-delete"])):
                select(tree, node)
                await settle(app, pilot)
                self.assertEqual(enabled(), expected, node.label.plain)
            for button in ("#btn-apply", "#btn-dry-run", "#btn-undo"):  # nothing staged, nothing to undo
                self.assertTrue(review.query_one(button, Button).disabled, button)
            self.assertFalse(review.query_one("#btn-search", Button).disabled)
            self.assertFalse(review.query_one("#btn-rescan", Button).disabled)

    async def test_leaving_with_staged_edits_asks_first(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#browse", Tree)
            wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
            elv = await self.open_node(review, pilot, child(wide, "ElvUI.lua"))
            doc = review.docs[elv.data[1].path]
            self.assertTrue(review.staging.set_value(doc, child(elv, "ElvVersion").data[2], 5).ok)
            review._update_summary()
            await settle(app, pilot)
            self.assertEqual(review.query_one("#pending").render().plain,
                             "Staged: 1 edit · Ticked: 0 results in 1 file")
            for key in ("f", "r"):  # leaving, and a rescan, drop it: both ask
                await pilot.press(key)
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertEqual(app.screen.kind, "destructive")
                await pilot.press("n")
                await settle(app, pilot)
                self.assertIs(app.screen, review)
            await pilot.press("f")
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)

    async def test_review_works_at_tiny(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot)
            for selector in ("#tree-filter", "#btn-search", "#btn-rescan", "#browse"):
                widget = review.query_one(selector)
                widget.focus()
                await pilot.pause()
                self.assertIs(review.focused, widget, selector)
