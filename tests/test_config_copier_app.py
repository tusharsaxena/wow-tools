"""The Config Copier in the suite app (config tools spec CC2-CC8, X1-X3): flavor (All flavors allowed) → source
picker (the shared character tree, one choice) → review (files ticked in the left pane; targets in the tree, each with
its file pairs and their status; other flavors' characters and the source greyed) → Copy / Dry run (confirm with the
CC7 warnings) → result, Diff on a replaced pair (config pairs mark the state lines kept), and Undo. Every client file
is synthesized in a tests/fixtures.py temp tree (build_copier_tree), never a real install."""
from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

from rich.cells import cell_len
from textual.widgets import Button, Checkbox, Tree

from tests.fixtures import (BASE, COUNT_AFTER, COPIER_ADDONS, COPIER_CHAT, COPIER_MACROS, TINY, TuiTestCase,
                            assert_fits_or_keeps_minimum, assert_siblings_distinct, build_copier_tree, make_config,
                            settle, submit_filter)
from wowtools.core.events import capture_events
from wowtools.core.install import flavor_name
from wowtools.core.text import plural
from wowtools.tools import TOOLS
from wowtools.tools.config_copier.diff_screen import DiffScreen
from wowtools.tools.config_copier.help import HELP
from wowtools.tools.config_copier.model import COPY_FILES, MACRO_WARNING
from wowtools.tools.config_copier.report import BYTES_ONLY, PAIR_MINIMUMS, WARNING_MARK, WARNING_SHORT, pair_cells, pair_text
from wowtools.tools.config_copier.review_screen import (DIFF_REASON, OTHER_FLAVOR_REASON, CopierResultScreen,
                                                        CopierReviewScreen, PairKey, PairNode, ReasonLine,
                                                        fit_reason)
from wowtools.tools.config_copier.source_screen import SourceScreen
from wowtools.ui.branding import footer_bindings
from wowtools.ui.character_tree import CharacterNode
from wowtools.ui.columns import GROUP_NAME_MINIMUM
from wowtools.ui.dialogs import ConfirmScreen, theme_colour
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.review import ActionBar
from wowtools.ui.suite_app import WowToolsApp
from wowtools.ui.theme import ACTION_COLOURS
from wowtools.ui.widgets import action_kind

TOOL = "config-copier"


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(current.children)))


def character_node(tree: Tree, name: str):
    return next(n for n in walk(tree.root) if isinstance(n.data, CharacterNode) and n.data.kind == "character"
                and n.data.character.name == name)


def pair_node(tree: Tree, character: str, file: str):
    owner = character_node(tree, character)
    owner.expand()
    return next(n for n in owner.children if isinstance(n.data, PairNode) and n.data.plan.name == file)


async def goto(pilot, tree: Tree, node) -> None:
    """Highlight `node` (once an expand above it has been laid out)."""
    await pilot.pause()
    tree.move_cursor(node)
    await pilot.pause()


class CopierTestCase(TuiTestCase):
    """A copier tree in a temp folder, the suite app over it, and the steps to its review."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_copier_tree(tmp / "World of Warcraft")
        self.accounts = self.root / "_retail_" / "WTF" / "Account"
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self, wow_check=list):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={TOOL: {"wow_check": wow_check}})

    def tree_bytes(self) -> dict[str, bytes]:
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob("*"))
                if p.is_file() and "wow-tools" not in p.parts}

    async def open_sources(self, app, pilot, flavor=ALL_FLAVORS) -> SourceScreen:
        await pilot.pause()
        app.open_tool(TOOL)
        await settle(app, pilot)
        if not isinstance(app.screen, FlavorScreen):
            app.screen._save()  # first open: the tool's settings, saved as they are
            await settle(app, pilot)
        picker = app.screen
        self.assertIsInstance(picker, FlavorScreen)
        picker.dismiss(flavor if flavor == ALL_FLAVORS else next(f for f in picker.flavors if f.folder == flavor))
        await settle(app, pilot)
        self.assertIsInstance(app.screen, SourceScreen)
        return app.screen

    async def open_review(self, app, pilot, flavor=ALL_FLAVORS, source="Aellâ") -> CopierReviewScreen:
        sources = await self.open_sources(app, pilot, flavor)
        tree = sources.query_one("#sources", Tree)
        tree.focus()
        tree.move_cursor(character_node(tree, source))
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        review = app.screen
        self.assertIsInstance(review, CopierReviewScreen)
        return review

    async def tick(self, app, pilot, review, *names) -> None:
        tree = review.query_one("#targets", Tree)
        tree.focus()
        for name in names:
            tree.move_cursor(character_node(tree, name))
            await pilot.pause()
            await pilot.press("space")
            await settle(app, pilot)


class CopierAppTest(CopierTestCase):
    async def test_registered_in_the_menu(self):
        tool = TOOLS[TOOL]
        self.assertEqual((tool.title, tool.section), ("Config Copier", "config_copier"))
        # shorter than the plan's line: it fits one row of the tool menu at 120 columns (T11)
        self.assertEqual(tool.description, "Copy one character's macros, chat, layout, CVars and addons to others.")

    async def test_flow_source_targets_review_copy(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            sources = await self.open_sources(app, pilot)
            labels = [n.data.character.name for n in walk(sources.query_one("#sources", Tree).root)
                      if isinstance(n.data, CharacterNode) and n.data.kind == "character"]
            self.assertEqual(sorted(labels), sorted(["Aellâ", "Bob", "Trâxex", "Dænerys", "Other"]))  # no copies
            await pilot.press("escape")  # back to the flavor picker
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            app.screen.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            sources = app.screen
            tree = sources.query_one("#sources", Tree)
            tree.focus()
            tree.move_cursor(character_node(tree, "Aellâ"))
            await pilot.pause()
            with capture_events() as events:
                await pilot.press("enter")
                await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, CopierReviewScreen)
            self.assertIn("copier.started", [e["event"] for e in events])
            self.assertTrue(all(box.value for box in review.query(Checkbox)))  # every file ticked (CC3)
            self.assertEqual(review.selected_plans(), [])  # no target ticked yet (CC2)
            self.assertTrue(review.query_one("#btn-copy").disabled)
            await self.tick(app, pilot, review, "Bob", "Trâxex")
            selected = review.selected_plans()
            self.assertEqual({(p.target.name, p.status) for p in selected},
                             {("Bob", "replace"), ("Bob", "new"), ("Trâxex", "new")})
            self.assertEqual(len(selected), 10)
            self.assertFalse(review.query_one("#btn-copy").disabled)
            await pilot.press("w")
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.kind, "overwrite")
            confirm.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, CopierResultScreen)
            for target in ("MAIN/Realm1/Bob", "MAIN/Realm2/Trâxex"):
                for name, data in (("macros-cache.txt", COPIER_MACROS), ("AddOns.txt", COPIER_ADDONS),
                                   ("chat-cache.txt", COPIER_CHAT)):
                    self.assertEqual((self.accounts / target / name).read_bytes(), data, (target, name))
            self.assertEqual((self.accounts / "MAIN" / "Realm1" / "Bob - Copy" / "macros-cache.txt").read_bytes(),
                             COPIER_MACROS)
            self.assertFalse((self.accounts / "ALT" / "Realm1" / "Dænerys" / "macros-cache.txt").exists())
            app.screen.dismiss("rescan")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.selected_plans(), [])  # everything copied is now unchanged
            self.assertIsNotNone(review.undoable)

    async def test_unticked_pair_and_file_left_alone(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.tick(app, pilot, review, "Bob")
            tree = review.query_one("#targets", Tree)
            await goto(pilot, tree, pair_node(tree, "Bob", "macros-cache.txt"))
            await pilot.press("space")  # drop one pair (CC4)
            await settle(app, pilot)
            box = review.query_one("#file-AddOns-txt", Checkbox)
            box.value = False  # and one file for every target
            await settle(app, pilot)
            self.assertEqual([p.name for p in review.selected_plans()],
                             ["chat-cache.txt", "config-cache.wtf", "layout-local.txt"])
            review.action_copy()
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            bob = "_retail_/WTF/Account/MAIN/Realm1/Bob/"
            after = self.tree_bytes()
            self.assertEqual(after[bob + "macros-cache.txt"], before[bob + "macros-cache.txt"])
            self.assertEqual(after[bob + "AddOns.txt"], before[bob + "AddOns.txt"])
            self.assertEqual(after[bob + "chat-cache.txt"], COPIER_CHAT)

    async def test_dry_run_then_undo(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.tick(app, pilot, review, "Bob", "Trâxex")
            await pilot.press("y")
            await settle(app, pilot)
            self.assertEqual(app.screen.kind, "simulate")
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, CopierResultScreen)
            self.assertEqual(self.tree_bytes(), before)
            await pilot.press("escape")  # Back to review: the ticks are kept
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(len(review.selected_plans()), 10)
            review.action_copy()
            await settle(app, pilot)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertNotEqual(self.tree_bytes(), before)
            app.screen.dismiss("rescan")
            await settle(app, pilot)
            await pilot.press("z")
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.kind, "destructive")
            confirm.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, CopierResultScreen)
            self.assertEqual(self.tree_bytes(), before)  # replaced files back, created ones gone
            self.assertFalse(any((self.accounts / "MAIN" / "Realm2" / "Trâxex").iterdir()))

    async def test_refused_while_wow_runs(self):
        before = self.tree_bytes()
        app = self.make_app(wow_check=lambda: ["Wow.exe"])
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.tick(app, pilot, review, "Bob")
            with capture_events() as events:
                review.action_copy()
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIn("copier.wow_running", [e["event"] for e in events])
            self.assertEqual(self.tree_bytes(), before)

    async def test_diff_screen_for_replaced_pair(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            tree.focus()
            await goto(pilot, tree, pair_node(tree, "Trâxex", "AddOns.txt"))  # new: nothing to compare
            await pilot.press("d")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            await goto(pilot, tree, pair_node(tree, "Bob", "macros-cache.txt"))
            await pilot.press("d")
            await settle(app, pilot)
            diff = app.screen
            self.assertIsInstance(diff, DiffScreen)
            text = diff.diff_text().plain
            self.assertIn("- /sit", text)
            self.assertIn("+ /cast [@mouseover] Flash Heal", text)
            self.assertIn("Heal Dænerys", text)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            await goto(pilot, tree, pair_node(tree, "Bob", "config-cache.wtf"))
            await pilot.press("d")
            await settle(app, pilot)
            text = app.screen.diff_text().plain
            kept = next(line for line in text.splitlines() if "hardTrackedQuests" in line)
            self.assertTrue(kept.startswith("  "), kept)
            self.assertIn("kept", kept)
            self.assertIn('- SET enableMultiActionBars "15"', text)
            self.assertIn('+ SET assistedCombatHighlight "1"', text)
            self.assertNotIn("savedClassConfigOne", text)  # the source's state is never copied

    async def test_diff_screen_names_a_line_ending_only_change(self):
        """T11 review: a replaced pair whose files differ only in line endings says so, not "the same"; a
        config-cache.wtf one keeps its rows and adds the line."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            plans = {(p.target.name, p.name): p for p in review.plans.values()}
            for name in ("macros-cache.txt", "config-cache.wtf"):
                with self.subTest(name=name):
                    plan = plans["Bob", name]
                    crlf = (plan.old or b"").replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                    pair = dataclasses.replace(plan, new=crlf.replace(b"\r\n", b"\n"), old=crlf)
                    app.push_screen(DiffScreen(pair, "MAIN › Realm1/Aellâ"))
                    await settle(app, pilot)
                    text = app.screen.diff_text().plain
                    self.assertIn("Only line endings or bytes that are not text differ.", text)
                    self.assertNotIn("The files are the same.", text)
                    self.assertIn("0 lines removed, 0 lines added", app.screen.head_text().plain)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertIs(app.screen, review)

    async def test_other_flavor_targets_greyed(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            other = character_node(tree, "Other")
            self.assertEqual(other.data.reason, "other flavor")
            self.assertEqual(other.data.keys, ())
            source = character_node(tree, "Aellâ")
            self.assertEqual(source.data.reason, "source")
            self.assertIn("other flavor", other.label.plain)
            tree.focus()
            tree.move_cursor(other)
            await pilot.pause()
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(review.selected_plans(), [])
            await pilot.press("a")  # select all: the source's flavor only
            await settle(app, pilot)
            self.assertEqual({p.target.name for p in review.selected_plans()}, {"Bob", "Trâxex", "Dænerys"})
            self.assertFalse(any(p.target.name == "Other" for p in review.selected_plans()))

    async def test_space_on_a_flavor_node_ticks_only_pairs(self):
        # The source flavor's node holds its characters' own keys too: Space ticks only the pairs, and with a filter
        # applied it must not crash on a character key (T23w2).
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            flavor = next(n for n in tree.root.children if isinstance(n.data, list) and n.data[1] == "_retail_")
            tree.focus()
            await goto(pilot, tree, flavor)
            await pilot.press("space")
            await settle(app, pilot)
            self.assertTrue(review.ticked)
            self.assertTrue(all(isinstance(k, PairKey) for k in review.ticked), review.ticked)
            await pilot.press("space")
            await settle(app, pilot)
            submit_filter(review, "Bob")
            await settle(app, pilot)
            flavor = next(n for n in tree.root.children if isinstance(n.data, list) and n.data[1] == "_retail_")
            await goto(pilot, tree, flavor)
            await pilot.press("space")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertTrue(all(isinstance(k, PairKey) for k in review.ticked), review.ticked)
            self.assertEqual({p.target.name for p in review.selected_plans()}, {"Bob"})

    async def test_filter_matches_the_source_flavor_name(self):
        # The source flavor's name matches its targets, as the other flavors' names match theirs (T23w3).
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            name = next(f.display_name for f in review.flavors if f.folder == "_retail_")
            submit_filter(review, name)
            await settle(app, pilot)
            folders = [n.data[1] for n in tree.root.children if isinstance(n.data, list)]
            self.assertIn("_retail_", folders)
            self.assertEqual(character_node(tree, "Bob").data.character.name, "Bob")
            await pilot.press("a")
            await settle(app, pilot)
            self.assertEqual({p.target.name for p in review.selected_plans()}, {"Bob", "Trâxex", "Dænerys"})

    async def test_pair_statuses_in_the_tree(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            chat = pair_node(tree, "Dænerys", "chat-cache.txt")
            self.assertEqual(chat.data.key, None)  # unchanged: nothing to tick
            self.assertIn("unchanged", chat.label.plain)
            macros = pair_node(tree, "Bob", "macros-cache.txt")
            self.assertIn("replaced", macros.label.plain)
            self.assertIn("⚠", macros.label.plain)
            self.assertIn("new (merged)", pair_node(tree, "Trâxex", "config-cache.wtf").label.plain)
            self.assertEqual([n.data.plan.name for n in character_node(tree, "Bob").children], list(COPY_FILES))

    async def test_macro_warning_in_confirm(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.tick(app, pilot, review, "Bob", "Trâxex")
            review.action_copy()
            await settle(app, pilot)
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual([(e.message, e.where, e.item) for e in confirm.listed],
                             [(MACRO_WARNING, "MAIN › Realm1/Bob", "macros-cache.txt")])
            self.assertIn("MAIN › Realm1/Bob", confirm.groups)
            confirm.dismiss(False)
            await settle(app, pilot)
            self.assertIs(app.screen, review)

    async def test_one_flavor_and_tiny(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot, flavor="_retail_")
            tree = review.query_one("#targets", Tree)
            self.assertFalse(any(isinstance(n.data, CharacterNode) and n.data.character is not None
                                 and n.data.character.name == "Other" for n in walk(tree.root)))
            self.assertTrue(review.sub_title.startswith("Config Copier · Retail"), review.sub_title)
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsNone(app.flow)


class ChangeSourceTest(CopierTestCase):
    """Feedback round 1 CP1: `p` (and the compact Change source button by the Source line) leaves the review for the
    source picker of the same flavor choice; the review of the new source starts fresh (no target ticked, every file
    box ticked). Refused while a run writes, as every way out of the review; Rescan keeps the source."""

    async def pick(self, app, pilot, sources: SourceScreen, name: str) -> CopierReviewScreen:
        tree = sources.query_one("#sources", Tree)
        tree.focus()
        tree.move_cursor(character_node(tree, name))
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        self.assertIsInstance(app.screen, CopierReviewScreen)
        return app.screen

    async def test_p_returns_to_the_source_picker_of_all_flavors(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            flavors = [f.folder for f in review.flavors]
            await self.tick(app, pilot, review, "Bob")
            review.query_one("#file-AddOns-txt", Checkbox).value = False
            await settle(app, pilot)
            self.assertTrue(review.selected_plans())
            await pilot.press("p")
            await settle(app, pilot)
            sources = app.screen
            self.assertIsInstance(sources, SourceScreen)
            self.assertEqual(([f.folder for f in sources.flavors], sources.scope_label), (flavors, "All flavors"))
            self.assertNotIn(review, app.screen_stack)
            # a new source other than the ticked target, so a tick carried over from the old review would show
            fresh = await self.pick(app, pilot, sources, "Dænerys")
            self.assertIsNot(fresh, review)
            self.assertEqual(fresh.source.name, "Dænerys")
            self.assertEqual(fresh.scope_label, "All flavors")
            self.assertEqual(fresh.selected_plans(), [])  # ticks belonged to the old source
            self.assertEqual(fresh.ticked, set())
            self.assertEqual(fresh.files, set(COPY_FILES))  # every file ticked again, in the model ...
            self.assertTrue(all(box.value for box in fresh.query(Checkbox)))  # ... and on screen
            self.assertIn("Dænerys", fresh.source_text())

    async def test_p_keeps_the_one_flavor_choice(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot, flavor="_retail_")
            label = review.scope_label
            await pilot.press("p")
            await settle(app, pilot)
            sources = app.screen
            self.assertIsInstance(sources, SourceScreen)
            self.assertEqual(([f.folder for f in sources.flavors], sources.scope_label), (["_retail_"], label))
            fresh = await self.pick(app, pilot, sources, "Bob")
            self.assertEqual((fresh.source.name, fresh.scope_label, [f.folder for f in fresh.flavors]),
                             ("Bob", label, ["_retail_"]))
            await pilot.press("escape")  # Esc on the new review still goes back to the flavor picker
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)

    async def test_the_button_changes_the_source(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            button = review.query_one("#btn-source", Button)
            self.assertEqual((str(button.label), action_kind(button), button.shortcut),
                             ("Change source (p)", "navigate", "p"))
            self.assertNotIn("p", {b.key for b, _, _ in footer_bindings(review)})  # the button carries the key
            button.press()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SourceScreen)

    async def test_p_refused_while_a_run_writes(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            app.busy = True
            try:
                await pilot.press("p")
                await pilot.pause()
                self.assertIs(app.screen, review)
            finally:
                app.busy = False
            await pilot.press("p")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SourceScreen)

    async def test_rescan_keeps_the_source(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("r")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.source.name, "Aellâ")

    def test_help_names_change_source(self):
        self.assertIn("**Change source** (`p`)", HELP)


class DiffReasonTest(CopierTestCase):
    """Feedback round 1 CP3: the Diff button under the tree is a `confirm` (blue) button, and while it is disabled a
    dim line beside it says why, cut at its end with … to the room after the button (hidden under 10 cells), empty
    while a scan or a run is going on."""

    def line(self, review):
        return review.query_one("#diff-reason", ReasonLine)

    def assert_fits_beside_the_button(self, review) -> None:
        line, button = self.line(review), review.query_one("#act-diff", Button)
        self.assertEqual(line.region.y, button.region.y)  # on the button's row ...
        self.assertEqual(line.region.x, button.region.right + ActionBar.GUTTER)  # ... right after its gap
        self.assertEqual(button.region.width, cell_len(str(button.label)) + 2)  # the button's whole label, never cut
        self.assertEqual(button.region.x, review.query_one("#diff-row").content_region.x)  # it never moves
        self.assertLessEqual(line.region.right, review.query_one("#tree-pane").region.right)
        width = line.content_size.width
        self.assertLessEqual(cell_len(line.shown), width)
        if width < ReasonLine.MIN_ROOM:
            self.assertEqual(line.shown, "")
        elif cell_len(DIFF_REASON) > width:
            self.assertTrue(line.shown.endswith("…"), line.shown)
            self.assertTrue(DIFF_REASON.startswith(line.shown[:-1]), line.shown)
        else:
            self.assertEqual(line.shown, DIFF_REASON)

    async def test_the_button_is_a_confirm_button(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            tree.focus()
            await goto(pilot, tree, pair_node(tree, "Bob", "macros-cache.txt"))
            await settle(app, pilot)
            button = review.query_one("#act-diff", Button)
            self.assertFalse(button.disabled)
            self.assertEqual((str(button.label), action_kind(button)), ("Diff (d)", "confirm"))
            self.assertEqual(button.styles.background.hex.upper(), ACTION_COLOURS["confirm"][0].upper())

    async def test_the_reason_shows_until_a_replaced_pair_is_highlighted(self):
        for size in (BASE, TINY):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    review = await self.open_review(app, pilot)
                    tree = review.query_one("#targets", Tree)
                    tree.focus()
                    await goto(pilot, tree, character_node(tree, "Bob"))
                    await settle(app, pilot)
                    self.assertTrue(review.query_one("#act-diff", Button).disabled)
                    self.assertTrue(self.line(review).shown)  # 80x24 still has room for a cut line
                    self.assert_fits_beside_the_button(review)
                    await goto(pilot, tree, pair_node(tree, "Bob", "macros-cache.txt"))
                    await settle(app, pilot)
                    self.assertFalse(review.query_one("#act-diff", Button).disabled)
                    self.assertEqual(self.line(review).shown, "")
                    await goto(pilot, tree, pair_node(tree, "Trâxex", "AddOns.txt"))  # new: nothing to compare
                    await settle(app, pilot)
                    self.assertEqual(self.line(review).shown[:4], DIFF_REASON[:4])

    async def test_the_reason_refits_on_resize(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await settle(app, pilot)
            self.assertEqual(self.line(review).shown, DIFF_REASON)
            for size in (TINY, (100, 30), BASE):  # 80x24 is the floor (STD-7.23)
                with self.subTest(size=size):
                    await pilot.resize_terminal(*size)
                    await settle(app, pilot)
                    self.assert_fits_beside_the_button(review)
            self.assertEqual(self.line(review).shown, DIFF_REASON)

    async def test_the_reason_is_empty_while_busy(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await settle(app, pilot)
            self.assertEqual(self.line(review).shown, DIFF_REASON)
            review._scanning = True  # a scan going on
            try:
                review._refresh_buttons()
                self.assertEqual(self.line(review).shown, "")
            finally:
                review._scanning = False
            review._refresh_buttons()
            self.assertEqual(self.line(review).shown, DIFF_REASON)
            app.busy = True  # a run writing
            try:
                review._refresh_buttons()
                self.assertEqual(self.line(review).shown, "")
            finally:
                app.busy = False

    def test_fit_reason(self):
        """The cut: whole when it fits, cut at its end with … to the room, nothing under 10 cells."""
        self.assertEqual(fit_reason(DIFF_REASON, 80), DIFF_REASON)
        self.assertEqual(fit_reason(DIFF_REASON, cell_len(DIFF_REASON)), DIFF_REASON)
        self.assertEqual(fit_reason(DIFF_REASON, 12), DIFF_REASON[:11] + "…")
        self.assertEqual(fit_reason(DIFF_REASON, 10), DIFF_REASON[:9] + "…")
        self.assertEqual(fit_reason(DIFF_REASON, 9), "")
        self.assertEqual(fit_reason(DIFF_REASON, 0), "")
        self.assertEqual(fit_reason("", 40), "")


class SideBySideDiffTest(CopierTestCase):
    """Feedback round 1 CP4 (rows and screen): the diff screen draws report.side_by_side_rows as two aligned
    columns, the target's file as it is on the left and what the copy gives it on the right, each with its line
    numbers; removed lines red on the left, added green on the right, a long line cut with … so the rows stay
    aligned, and the head's counts as the inline view's."""

    def lines(self, app) -> list[str]:
        return [strip.text for strip in app.screen._compositor.render_strips()]

    def segment_colour(self, app, text: str) -> str | None:
        """The foreground colour the screen draws `text` in (the first segment holding it)."""
        for strip in app.screen._compositor.render_strips():
            for segment in strip:
                if text in segment.text and segment.style and segment.style.color:
                    return segment.style.color.triplet.hex if segment.style.color.triplet else None
        return None

    async def open_diff(self, app, pilot, character: str, file: str) -> DiffScreen:
        review = await self.open_review(app, pilot)
        tree = review.query_one("#targets", Tree)
        tree.focus()
        await goto(pilot, tree, pair_node(tree, character, file))
        await pilot.press("d")
        await settle(app, pilot)
        self.assertIsInstance(app.screen, DiffScreen)
        return app.screen

    async def test_both_sides_aligned_with_their_line_numbers_at_base(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            diff = await self.open_diff(app, pilot, "Bob", "macros-cache.txt")
            lines = self.lines(app)
            row = next(line for line in lines if "/sit" in line)
            self.assertIn("/cast [@mouseover] Flash Heal", row)  # old line 2 beside new line 2
            self.assertLess(row.index("/sit"), row.index("/cast"))
            self.assertRegex(row, r"\b2 /sit .*\b2 /cast")
            header = next(line for line in lines if '"Bob"' in line)
            self.assertRegex(header, r'\b1 VER 3 0100000000000001 "Bob" .*\b1 VER 3 0100000000000001 "Heal')
            end = next(line for line in lines if "END" in line)
            self.assertRegex(end, r"\b3 END .*\b3 END")  # a kept line on both sides
            extra = next(line for line in lines if '"D Up"' in line)
            left, right = extra.split("│")
            self.assertEqual(left.strip(" ▊"), "")  # the new side's extra line beside a blank
            self.assertIn("4 VER 3 0100000000000002", right)
            self.assertEqual(diff.query_one("#diff").size.height, len(diff.side_rows))  # one screen row each
            self.assertEqual(self.segment_colour(app, "/sit"), theme_colour(app, "error").lower())
            self.assertEqual(self.segment_colour(app, "Flash Heal"), theme_colour(app, "success").lower())
            self.assertIn("2 lines removed, 5 lines added.", diff.head_text().plain)  # the inline view's counts

    async def test_the_config_file_notes_its_kept_state_lines(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            diff = await self.open_diff(app, pilot, "Bob", "config-cache.wtf")
            kept = next(line for line in self.lines(app) if "hardTrackedQuests" in line)
            self.assertEqual(kept.count("hardTrackedQuests"), 2)
            self.assertIn("kept", kept)
            changed = next(line for line in self.lines(app) if "enableMultiActionBars" in line)
            self.assertIn("assistedCombatHighlight", changed)
            self.assertIn("1 state line kept as they are, the target's own (marked kept).", diff.head_text().plain)

    async def test_a_changed_config_value_shows_on_both_sides_at_100_columns(self):
        """P3 review: the kept note is a short mark, so it takes little width from the two sides and a changed
        value at the end of a `SET name "value"` line stays in view on both."""
        app = self.make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            review = await self.open_review(app, pilot)
            plan = next(p for p in review.plans.values() if (p.target.name, p.name) == ("Bob", "config-cache.wtf"))
            state = 'SET hardTrackedQuests "222"\n'
            old = (state + 'SET cameraSavedDistance "15.000000"\nSET Sound_MusicVolume "0.400000"\n').encode()
            new = (state + 'SET cameraSavedDistance "28.500000"\nSET Sound_MusicVolume "0.100000"\n').encode()
            app.push_screen(DiffScreen(dataclasses.replace(plan, old=old, new=new), "MAIN › Realm1/Aellâ"))
            await settle(app, pilot)
            lines = self.lines(app)
            self.assertTrue(any("hardTrackedQuests" in line and "kept" in line for line in lines))
            for before, after in (('"15.000000"', '"28.500000"'), ('"0.400000"', '"0.100000"')):
                with self.subTest(value=after):
                    row = next(line for line in lines if before in line)
                    self.assertIn(after, row)

    async def test_changed_rows_carry_their_mark_without_colour(self):
        """P3 review: a removed or added side shows - / + beside its line number, so a changed row reads apart from
        a kept one without colour; a kept line has no mark."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_diff(app, pilot, "Bob", "macros-cache.txt")
            lines = self.lines(app)
            row = next(line for line in lines if "/sit" in line)
            self.assertRegex(row, r"-2 /sit .*\+2 /cast")
            end = next(line for line in lines if "END" in line)
            self.assertNotRegex(end, r"[-+]3 END")
            extra = next(line for line in lines if '"D Up"' in line)
            self.assertIn("+4 VER 3 0100000000000002", extra)

    async def test_a_config_file_with_only_line_endings_changed_shows_its_rows_and_says_so(self):
        """P3 review: side by side, a config-cache.wtf that differs only in line endings draws its rows and the
        bytes-only line under them, never "the same"."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            plan = next(p for p in review.plans.values() if (p.target.name, p.name) == ("Bob", "config-cache.wtf"))
            crlf = (plan.old or b"").replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            app.push_screen(DiffScreen(dataclasses.replace(plan, new=crlf.replace(b"\r\n", b"\n"), old=crlf),
                                       "MAIN › Realm1/Aellâ"))
            await settle(app, pilot)
            lines = self.lines(app)
            self.assertTrue(any(line.count("hardTrackedQuests") == 2 for line in lines))
            self.assertTrue(any(BYTES_ONLY in line for line in lines))
            self.assertFalse(any("The files are the same." in line for line in lines))

    async def test_a_long_line_is_cut_and_the_rows_stay_aligned(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            plan = next(p for p in review.plans.values() if (p.target.name, p.name) == ("Bob", "AddOns.txt"))
            long_old, long_new = "Old" + "o" * 200, "New" + "n" * 200
            pair = dataclasses.replace(plan, old=f"{long_old}\nK\n".encode(), new=f"{long_new}\nK\n".encode())
            app.push_screen(DiffScreen(pair, "MAIN › Realm1/Aellâ"))
            await settle(app, pilot)
            diff = app.screen
            self.assertEqual(diff.query_one("#diff").size.height, 2)  # never wrapped
            row = next(line for line in self.lines(app) if "Oldooo" in line)
            self.assertIn("Newnnn", row)
            self.assertEqual(row.count("…"), 2)
            kept = next(line for line in self.lines(app) if "2 K " in line)
            self.assertRegex(kept, r" 2 K +│ +2 K ")  # the kept line on its own row, both sides

    async def test_bytes_only_and_the_same_files_say_so(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            plan = next(p for p in review.plans.values() if (p.target.name, p.name) == ("Bob", "AddOns.txt"))
            for old, new, text in ((b"A\n", b"A\r\n", BYTES_ONLY), (b"A\n", b"A\n", "The files are the same.")):
                with self.subTest(text=text):
                    app.push_screen(DiffScreen(dataclasses.replace(plan, old=old, new=new), "MAIN › Realm1/Aellâ"))
                    await settle(app, pilot)
                    self.assertTrue(any(text in line for line in self.lines(app)))
                    await pilot.press("escape")
                    await settle(app, pilot)


def indent(node) -> int:
    """The cells in front of a node's label: the tree guides, and the ▶ / ▼ of a node that opens."""
    depth, parent = 0, node.parent
    while parent is not None:
        depth, parent = depth + 1, parent.parent
    return depth * node.tree.guide_depth + (2 if node.allow_expand else 0)


class NodeCountsAndColumnsTest(CopierTestCase):
    """Feedback round 2 R2 / R4 (STD-7.27, STD-7.28) on the Config Copier review: every node with children (the
    root, a flavor, an account, a realm, a target character) counts the file pairs below it that the tree shows
    (after the search and the left pane's file boxes; every pair line, whatever its status); a pair line is the leaf
    and its name · status · warning are aligned columns cut to the pane."""

    def shown_pairs(self, node) -> int:
        return sum(1 for n in walk(node) if isinstance(n.data, PairNode))

    def assert_counts(self, tree) -> None:
        for node in walk(tree.root):
            if not node.children or isinstance(node.data, PairNode):
                continue
            with self.subTest(node=str(node.label)):
                expected = plural(self.shown_pairs(node), "item")
                self.assertTrue(str(node.label).endswith(f"  {expected}"), str(node.label))
                count = node.label.spans[-1]
                self.assertEqual((str(node.label)[count.start:].strip(), str(count.style)), (expected, "dim"))

    async def test_every_node_counts_the_pairs_below_it(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            self.assertTrue(str(tree.root.label).endswith("  15 items"), str(tree.root.label))  # 3 targets x 5
            flavors = {n.data[1]: str(n.label) for n in tree.root.children if isinstance(n.data, list)}
            self.assertTrue(flavors["_retail_"].endswith("  15 items"), flavors)
            self.assertTrue(flavors["_classic_era_"].endswith("  0 items"), flavors)  # other flavor: nothing copied
            self.assertTrue(str(character_node(tree, "Bob").label).endswith("  5 items"))
            for name in ("Aellâ", "Other"):  # the source and another flavor's character: no pairs, no count
                plain = str(character_node(tree, name).label)
                self.assertNotIn("item", plain)
            for node in walk(tree.root):  # a pair line is the leaf: no count of its own
                if isinstance(node.data, PairNode):
                    self.assertNotIn("item", str(node.label))
            self.assert_counts(tree)

    async def test_counts_follow_the_search_and_the_file_boxes(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            submit_filter(review, "Bob")
            await settle(app, pilot)
            self.assertTrue(str(tree.root.label).endswith("  5 items"), str(tree.root.label))
            self.assert_counts(tree)
            submit_filter(review, "chat-cache")
            await settle(app, pilot)
            self.assertTrue(str(tree.root.label).endswith("  3 items"), str(tree.root.label))
            self.assertTrue(str(character_node(tree, "Bob").label).endswith("  1 item"))
            self.assert_counts(tree)
            submit_filter(review, "")
            await settle(app, pilot)
            review.query_one("#file-AddOns-txt", Checkbox).value = False
            await settle(app, pilot)
            self.assertTrue(str(tree.root.label).endswith("  12 items"), str(tree.root.label))
            self.assertTrue(str(character_node(tree, "Trâxex").label).endswith("  4 items"))
            self.assert_counts(tree)

    async def test_pair_rows_are_aligned_columns(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            for owner in ("Bob", "Trâxex", "Dænerys"):
                rows = [pair_node(tree, owner, name) for name in COPY_FILES]
                starts = {str(n.label).rindex(pair_text(n.data.plan)) for n in rows}
                self.assertEqual(len(starts), 1, [str(n.label) for n in rows])  # the statuses line up
                for node in rows:
                    plain = str(node.label)
                    self.assertFalse(plain.endswith(" "), plain)  # no padding after the last column
                    if node.data.key is None:  # a pair that writes nothing is dim, its status too
                        spans = {plain[s.start:s.end].strip(): str(s.style) for s in node.label.spans}
                        self.assertEqual(spans.get(node.data.plan.name), "dim", plain)
            macros = pair_node(tree, "Bob", "macros-cache.txt")
            plain = str(macros.label)
            self.assertRegex(plain, rf"^. macros\S*\.txt +replaced +{WARNING_MARK} {WARNING_SHORT}$")

    async def test_greyed_reasons_are_aligned_columns(self):
        # Another flavor's characters are all greyed (`other flavor`): name · reason are columns, so a realm with
        # a short and a long name starts both reasons at the same cell (R4, STD-7.28).
        realm = self.root / "_classic_era_" / "WTF" / "Account" / "ACCT" / "Realm1"
        (realm / "Bobbington").mkdir()
        (realm / "Bobbington" / "AddOns.txt").write_bytes(b"Questie: enabled\r\n")
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            rows = [character_node(tree, name) for name in ("Other", "Bobbington")]
            labels = [str(n.label) for n in rows]
            self.assertEqual(len({label.rindex(OTHER_FLAVOR_REASON) for label in labels}), 1, labels)
            self.assertRegex(labels[0], rf"^ +Other +{OTHER_FLAVOR_REASON}$")
            self.assertTrue(labels[1].endswith(f"Bobbington  {OTHER_FLAVOR_REASON}"), labels)
            for node in rows:
                spans = {str(node.label)[s.start:s.end].strip(): str(s.style) for s in node.label.spans}
                self.assertEqual(spans.get(OTHER_FLAVOR_REASON), "dim italic", spans)
            await pilot.resize_terminal(*TINY)
            await settle(app, pilot)
            room = tree.size.width - tree.styles.scrollbar_size_vertical
            for node in rows:  # narrow: the name gives way first, the reason is never cut, only dropped
                plain = str(node.label)
                self.assertLessEqual(indent(node) + node.label.cell_len, room, plain)
                self.assertTrue(plain.endswith(OTHER_FLAVOR_REASON) or "other " not in plain and "fl" not in plain,
                                plain)

    async def test_rows_fit_the_pane(self):
        """Every line fits the pane at 120x30; at 80x24 a pair line 20 cells deep keeps its file name's 10 cells
        (and a realm or character its name's 4) and scrolls sideways instead (STD-7.28, user decision U1), and the
        five file names of a character still read apart."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#targets", Tree)
            for name in ("Bob", "Trâxex", "Dænerys"):
                character_node(tree, name).expand()
            await settle(app, pilot)
            for size in (BASE, TINY):
                await pilot.resize_terminal(*size)
                await settle(app, pilot)
                room = tree.size.width - tree.styles.scrollbar_size_vertical
                for node in walk(tree.root):
                    if node.data is None:
                        continue
                    data = node.data
                    if isinstance(data, PairNode):
                        name, minimum = pair_cells(data.plan)[0], PAIR_MINIMUMS[0]
                    else:
                        name = data.text if isinstance(data, CharacterNode) else flavor_name(data[1])
                        minimum = GROUP_NAME_MINIMUM
                    with self.subTest(size=size, row=str(node.label)):
                        if size == BASE:
                            self.assertLessEqual(indent(node) + node.label.cell_len, room)
                        assert_fits_or_keeps_minimum(self, node, indent(node), room, name, minimum,
                                                     after=COUNT_AFTER if node.allow_expand else "")
                assert_siblings_distinct(self, [n for n in walk(tree.root) if isinstance(n.data, PairNode)])
                if size == BASE:  # at 120 columns every status and warning reads in full, the names stay apart
                    for owner in ("Bob", "Trâxex", "Dænerys"):
                        rows = character_node(tree, owner).children
                        for node in rows:
                            plain = str(node.label)
                            self.assertIn(f" {pair_text(node.data.plan)}", plain)
                            if node.data.plan.warnings:
                                self.assertTrue(plain.endswith(f"{WARNING_MARK} {WARNING_SHORT}"), plain)
                        names = [str(n.label).split()[1] for n in rows]
                        self.assertEqual(len(set(names)), len(names), names)
                    self.assertIn("macros…e.txt", str(pair_node(tree, "Bob", "macros-cache.txt").label))


if __name__ == "__main__":
    import unittest
    unittest.main()
