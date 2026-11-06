"""Saved Variables Browser flow and review (spec D1-D3, D12, D18, §5): first-run settings, flavor picker with All
flavors, the USE AT YOUR OWN RISK warning once per app session (L4), and the review's Browse view (the file tree,
lazy loading, the child cap, x / c, the filter on loaded labels, the buttons, leaving with staged edits)."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from unittest import mock

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.widgets import Button, Tree

from tests.fixtures import (BASE, COUNT_AFTER, LARGE, TINY, TuiTestCase, accept_disclaimer,
                            assert_fits_or_keeps_minimum, assert_keys_on_buttons, build_sv_tree, make_config, settle,
                            submit_filter)
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools.sv_browser.app import SvBrowserSettingsScreen
from wowtools.tools.sv_browser.model import CHILD_CAP
from wowtools.tools.sv_browser.review_screen import READING, RESULT_GROUPS, SvReviewScreen
from wowtools.tools.sv_browser.settings import load_settings
from wowtools.ui.columns import GROUP_NAME_MINIMUM, cut_middle
from wowtools.ui.counts import COUNT_GAP
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.disclaimer import ACCEPT, BACK, DISCLAIMER_TITLE, DisclaimerScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.review import TOGGLE_WIDTH
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.tree_filter import NO_MATCH_TEXT
from wowtools.ui.widgets import RISK_TEXT, RiskBanner
from tests.fixtures import action_kind

TOOL = "sv-browser"


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def one_piece(node) -> str:
    """A node's label with a key or hit row's column padding taken out (`key = value  ✎ new`, the row as the filter
    and the bottom line read it): the pad where a sibling's ▶ is goes, the gap before the value is one space and
    the one before the marks two. The columns themselves are pinned in NodeCountsAndColumnsTest."""
    text = node.label.plain
    if node.data is None or node.data[0] not in ("node", "hit"):
        return text
    text = re.sub(r" {2,}(?=[={])", " ", text.lstrip(" "), count=1)
    return re.sub(r" +(?=[→✎✗])", "  ", text, count=1)


def labels(node) -> list[str]:
    return [one_piece(child) for child in node.children]


def child(node, start: str):
    """The child of node whose label (in one piece) starts with `start`; else, where the pane cut the labels (80
    columns), the one whose file or key is `start`, or the group whose name is `start` cut in its middle."""
    found = [c for c in node.children if one_piece(c).startswith(start)]
    if not found:
        found = [c for c in node.children if c.data is not None and c.data[0] in ("file", "node")
                 and (c.data[1].path.name if c.data[0] == "file" else c.data[2].key) == start]
    if not found:
        cuts = {cut_middle(start, width) for width in range(2, len(start))}
        found = [c for c in node.children if one_piece(c).split(COUNT_GAP)[0] in cuts]
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
            app.screen.dismiss(ALL_FLAVORS)  # accepted once in this app session: not asked again
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

    async def test_the_warning_is_not_asked_again_when_the_tool_is_opened_again(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            review.action_leave("tools")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)
            picker = await self.open_picker(app, pilot)
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvReviewScreen)  # L4: once per app session

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
                             "Staged: 0 edits in 0 files")
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

    async def test_toasts_sit_above_the_action_bar(self):
        """A toast ("Nothing found.") covered the action bar and touched the bottom bar (user feedback
        2026-10-07): toasts go just above the bar, at the base size and the small one."""
        for size in (BASE, TINY):
            app = self.make_app()
            async with app.run_test(size=size, notifications=True) as pilot:
                review = await self.open_review(app, pilot)
                review.notify("Nothing found.", title="Search")
                await settle(app, pilot)
                toast = review.query_one("Toast").region
                bar = review.query_one("#tree-actions").region
                self.assertGreater(toast.height, 0, size)
                self.assertLessEqual(toast.bottom, bar.y, (size, toast, bar))

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
            self.assertRegex(one_piece(child(wide, "ElvUI.lua")), r"^ElvUI\.lua {2,}\d+(\.\d)? (B|KB)$")
            realm = child(acct1, "Realm1")
            self.assertEqual([n.split("  ")[0] for n in labels(realm)], ["Kaelys"])
            self.assertEqual([n.split("  ")[0] for n in labels(child(realm, "Kaelys"))], ["ElvUI.lua"])
            self.assertEqual(review.docs, {})  # the scan reads no file (D18)

    async def test_opening_a_file_and_a_table_loads_them_in_a_worker(self):
        app = self.make_app()
        async with app.run_test(size=LARGE) as pilot:
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
            self.assertTrue(one_piece(broken).endswith("can't read"), one_piece(broken))
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
            self.assertEqual([one_piece(n) for n in groups if not n.is_expanded], [])
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
            shown = [one_piece(n) for n in walk(tree.root) if n.data is not None and n.data[0] == "node"]
            self.assertEqual(shown, ["ElvDB {1}", "profiles {1}", "Default {2}", "general {4}", "autoRepair = true"])
            submit_filter(review, "kaelys")  # a group's name: everything in it shows
            await settle(app, pilot)
            files = [one_piece(n).split("  ")[0] for n in walk(tree.root) if n.data and n.data[0] == "file"]
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
                self.assertEqual(enabled(), expected, one_piece(node))
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
                             "Staged: 1 edit in 1 file")
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


GROUP_DATA = ("root", "flavor", "account", "realm", "owner", "r-flavor", "r-account", "r-owner", "r-file")


def drawn(node) -> str:
    """A node's line as the tree draws it behind its guides: its ▶ / ▼ (none on a leaf), then its label."""
    return ("▼ " if node.is_expanded else "▶ ") * node.allow_expand + node.label.plain


def row_name(review, node) -> tuple[str, int] | None:
    """A row's name in full and the cells it keeps however narrow the pane (STD-7.28, U1): a column row's first cell
    and its layout's minimum, a group's name and GROUP_NAME_MINIMUM; None for any other line."""
    data = node.data
    row = review._row(data)
    if row is not None:
        name = row[0][0]
        return (name.plain if isinstance(name, Text) else name), row[2].minimums[0]
    kind = data[0]
    if kind == "root":
        name = review.scope_label
    elif kind in RESULT_GROUPS:
        name = review._result_name(data)
    elif kind == "flavor":
        name = data[1].flavor.display_name
    elif kind in ("account", "realm", "owner"):
        name = review._place_name(data)
    else:
        return None
    return name, GROUP_NAME_MINIMUM


def assert_row_fits(test, review, row, room: int) -> None:
    """A row fits the pane, or keeps its name's minimum and scrolls sideways (U1); a `… N more` or problem line
    fits unless its guides and ▶ already fill the pane."""
    guides = depth(row) * row.tree.guide_depth
    lead = guides + (TOGGLE_WIDTH if row.allow_expand else 0)
    named = row_name(review, row)
    if named is not None:  # a group keeps its count (STD-7.27)
        after = COUNT_AFTER if review._row(row.data) is None else ""
        assert_fits_or_keeps_minimum(test, row, lead, room, *named, after=after)
    elif guides + 2 < room:
        test.assertLessEqual(guides + cell_len(drawn(row)), room, drawn(row))


def depth(node) -> int:
    """How many levels below the root a node is (its guides)."""
    levels = 0
    while node.parent is not None:
        node, levels = node.parent, levels + 1
    return levels


def leaves_below(node, kind: str) -> int:
    return sum(1 for n in walk(node) if n is not node and n.data is not None and n.data[0] == kind)


def assert_counts(test, tree, leaf: str) -> None:
    """Every group's label ends with the number of `leaf` rows the tree shows below it (STD-7.27)."""
    groups = [n for n in walk(tree.root) if n.data is not None and n.data[0] in GROUP_DATA]
    test.assertTrue(groups)
    for node in groups:
        n = leaves_below(node, leaf)
        test.assertTrue(node.label.plain.endswith(f"  {n} item" + ("s" if n != 1 else "")), node.label.plain)


class NodeCountsAndColumnsTest(SvBrowserTestBase):
    """Feedback round 2 R2, R4 (STD-7.27, STD-7.28): in Browse every group (the root, a flavor, an account, a realm,
    a character or Account-wide) counts the SavedVariables files the tree shows below it, before any is read; in
    Results every group counts its hits. File, key and hit rows are columns aligned between siblings and fitted to
    the pane (the Results view: test_sv_browser_search_ui.ResultsCountsAndColumnsTest)."""

    async def test_every_group_counts_the_files_below_it_before_any_is_read(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#browse", Tree)
            tree.focus()
            await pilot.press("x")
            await settle(app, pilot)
            self.assertEqual(review.docs, {})
            self.assertEqual(tree.root.label.plain, "All flavors  9 items")
            retail = child(tree.root, "Retail")
            self.assertEqual(retail.label.plain, "Retail  7 items")
            self.assertEqual(child(tree.root, "Classic Era").label.plain, "Classic Era  2 items")
            acct1 = child(retail, "ACCT1")
            self.assertEqual(acct1.label.plain, "ACCT1  5 items")
            self.assertEqual(child(acct1, "Account-wide").label.plain, "Account-wide  4 items")
            realm = child(acct1, "Realm1")
            self.assertEqual(realm.label.plain, "Realm1  1 item")
            self.assertEqual(child(realm, "Kaelys").label.plain, "Kaelys  1 item")
            assert_counts(self, tree, "file")
            wide = child(acct1, "Account-wide")
            await self.open_node(review, pilot, child(wide, "ElvUI.lua"))  # reading a file changes no count
            self.assertEqual(child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide").label.plain,
                             "Account-wide  4 items")
            assert_counts(self, tree, "file")

    async def test_counts_follow_the_filter(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#browse", Tree)
            submit_filter(review, "kaelys")
            await settle(app, pilot)
            self.assertEqual(tree.root.label.plain, "All flavors  2 items")
            self.assertEqual(child(tree.root, "Retail").label.plain, "Retail  1 item")
            self.assertEqual(child(tree.root, "Classic Era").label.plain, "Classic Era  1 item")
            assert_counts(self, tree, "file")
            submit_filter(review, "details")
            await settle(app, pilot)
            self.assertEqual(labels(tree.root), ["Retail  2 items"])
            self.assertEqual(child(child(tree.root, "Retail"), "ACCT2").label.plain, "ACCT2  1 item")
            assert_counts(self, tree, "file")

    async def test_file_and_key_rows_are_aligned_columns(self):
        app = self.make_app()
        async with app.run_test(size=LARGE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            tree = review.query_one("#browse", Tree)
            wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
            sizes = {drawn(n).index(n.label.plain.split()[-2]) for n in wide.children}  # the size column
            self.assertEqual(len(sizes), 1, [drawn(n) for n in wide.children])
            elv = await self.open_node(review, pilot, child(wide, "ElvUI.lua"))
            # the scalar row does not open: padded where its siblings' ▶ is, so the value column lines up
            self.assertEqual([n.label.plain for n in elv.children], ["ElvDB         {1}", "ElvPrivateDB  {1}", "  ElvVersion    = nil"])
            self.assertEqual({re.search("[{=]", drawn(n)).start() for n in elv.children}, {16})
            db = await self.open_node(review, pilot, child(elv, "ElvDB"))
            profiles = await self.open_node(review, pilot, child(db, "profiles"))
            default = await self.open_node(review, pilot, child(profiles, "Default"))
            general = await self.open_node(review, pilot, child(default, "general"))
            self.assertEqual([n.label.plain for n in general.children], ['font        = "Friz Quadrata TT"', "fontSize    = 12",
                                               "scale       = 0.6000000000000001", "autoRepair  = true"])
            doc = review.docs[elv.data[1].path]
            self.assertTrue(review.staging.set_value(doc, child(general, "fontSize").data[2], 14).ok)
            review._refresh_labels()
            await settle(app, pilot)
            # the staged mark is a third column, after the widest value
            self.assertEqual(child(general, "fontSize").label.plain, "fontSize    = 12                  ✎ 14")
            self.assertEqual(child(general, "font ").label.plain, 'font        = "Friz Quadrata TT"')

    async def test_rows_fit_the_pane(self):
        def by_name(node, name: str):
            """The child whose file or key is `name` (at 80 columns the labels are cut to the pane)."""
            found = [c for c in node.children if c.data is not None
                     and (c.data[1].path.name if c.data[0] == "file" else c.data[2].key) == name]
            assert len(found) == 1, (name, labels(node))
            return found[0]

        for size in (BASE, TINY):
            app = self.make_app()
            async with app.run_test(size=size) as pilot:
                review = await self.open_review(app, pilot, "_retail_")
                tree = review.query_one("#browse", Tree)
                tree.focus()
                await pilot.press("x")
                await settle(app, pilot)
                wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
                node = await self.open_node(review, pilot, by_name(wide, "ElvUI.lua"))
                for key in ("ElvDB", "profiles", "Default"):
                    node = await self.open_node(review, pilot, by_name(node, key))
                general = await self.open_node(review, pilot, by_name(node, "general"))
                await self.open_node(review, pilot, by_name(node, "unitframe"))
                room = tree.size.width - tree.styles.scrollbar_size_vertical
                for row in walk(tree.root):
                    if row.data is not None:
                        with self.subTest(size=size, row=drawn(row)):
                            if size == BASE:
                                self.assertLessEqual(depth(row) * tree.guide_depth + cell_len(drawn(row)), room)
                            assert_row_fits(self, review, row, room)  # 80 columns: deep keys scroll (U1)
                if size == TINY:  # a key deep in the tree keeps its 8 cells, never a bare `…` (G7r)
                    self.assertNotIn("…", [c.label.plain for c in general.children])
                if size == BASE:  # the value is cut to the pane there
                    self.assertEqual(general.children[0].label.plain, 'font       = "Friz Quadrata T…')
                # the bottom line names the highlighted key and its value in full, whatever the row shows
                select(tree, by_name(general, "font"))
                await settle(app, pilot)
                self.assertIn('general › font = "Friz Quadrata TT"', review.summary_text)

    async def test_rows_are_fitted_when_the_tree_is_laid_out_after_the_build(self):
        """G9bf, the G10 review: a build made while the tree has no width yet, whose after-refresh fit runs before
        the tree is laid out (the screen idles first, under load), is fitted when the tree takes its width. Textual
        sends that Resize to the tree alone; the tree tells its screen (ReviewTree.Resized, ui.review.FittedRows)."""
        real = SvReviewScreen._rebuild
        builds = []

        def rebuild(screen):
            builds.append(screen)
            if len(builds) > 1:
                return real(screen)
            tree = screen.query_one("#browse", Tree)
            with mock.patch.object(type(tree), "size", new=property(lambda _: Size(0, 0))), \
                    mock.patch.object(screen, "call_after_refresh", lambda callback, *args: callback(*args)):
                return real(screen)

        with mock.patch.object(SvReviewScreen, "_rebuild", rebuild):
            app = self.make_app()
            async with app.run_test(size=TINY) as pilot:
                review = await self.open_review(app, pilot, "_retail_")
                tree = review.query_one("#browse", Tree)
                tree.focus()
                await pilot.press("x")  # every group open (a toggle, no rebuild)
                await settle(app, pilot)
                tree.post_message(events.Resize(tree.size, tree.virtual_size))  # the tree's own first layout
                await settle(app, pilot)
                self.assertEqual(len(builds), 1)
                room = tree.size.width - tree.styles.scrollbar_size_vertical
                rows = [row for row in walk(tree.root) if row.data is not None]
                self.assertTrue(rows)
                for row in rows:
                    with self.subTest(row=drawn(row)):
                        assert_row_fits(self, review, row, room)
