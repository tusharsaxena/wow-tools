"""Saved Variables Browser search (spec D6-D12, §5): the Search popup (key, value, their modes, Match case, the
scope, the replacement), its checks, the search job with the shared progress popup, the Results view (flavor ›
account › owner › file › one ticked leaf per hit, `path = old → new`), ticks and the filter there, v between the
views, a new search over ticked results, the cap note and ticked results a staged edit wins over."""
from __future__ import annotations

from unittest import mock

from textual.widgets import Button, Input, Select, Static, Tree

from tests.fixtures import BASE, TINY, assert_keys_on_buttons, settle
from tests.test_sv_browser_app import SvBrowserTestBase, child, labels, select, walk
from tests.test_sv_browser_edit import SvEditTestBase, error_text
from wowtools.core.events import capture_events
from wowtools.core.svfiles import OWNER_ACCOUNT_WIDE
from wowtools.tools.sv_browser import review_screen
from wowtools.tools.sv_browser.ops import HAS_STAGED_EDIT
from wowtools.tools.sv_browser.popups import FIND_ONLY, SearchScreen
from wowtools.tools.sv_browser.review_screen import BROWSE, RESULTS, SvReviewScreen
from wowtools.tools.sv_browser.search import (KEY_CONTAINS, NEED_TEXT, REPLACE_BOOLEAN, REPLACE_NUMBER,
                                              VALUE_CONTAINS)
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.widgets import Ka0sCheckbox, action_kind

FRIZ = "Friz Quadrata TT"


def hits_of(node) -> list[str]:
    """The labels of the hit leaves under node."""
    return [n.label.plain for n in walk(node) if n.data is not None and n.data[0] == "hit"]


class SearchTestBase(SvBrowserTestBase):
    async def open_search(self, review, pilot) -> SearchScreen:
        review.query_one("#browse", Tree).focus()
        await pilot.press("S")
        await settle(review.app, pilot)
        self.assertIsInstance(review.app.screen, SearchScreen)
        return review.app.screen

    async def fill(self, popup, pilot, **fields) -> None:
        """Set the popup's fields: ids with - written as _ (search_value="x", new_type=REPLACE_NUMBER, ...)."""
        for name, value in fields.items():
            widget = popup.query_one(f"#{name.replace('_', '-')}")
            widget.value = value
            await settle(popup.app, pilot)

    async def search(self, review, pilot, **fields) -> None:
        """Open the popup, fill it and press Find; the review is shown again with the results."""
        popup = await self.open_search(review, pilot)
        await self.fill(popup, pilot, **fields)
        await pilot.click("#find")
        await settle(review.app, pilot)
        if review.app.screen is popup:
            self.fail(f"the popup stayed open: {error_text(popup, '#search-error')}")
        self.assertIs(review.app.screen, review)

    def pending(self, review) -> str:
        return review.query_one("#pending").render().plain

    def tree_root(self, review):
        return review.query_one("#browse", Tree).root


class SearchPopupTest(SearchTestBase):
    async def test_the_popup_has_one_control_per_row_and_keys_on_its_buttons(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            popup = await self.open_search(review, pilot)
            self.assertIs(popup.focused, popup.query_one("#search-key", Input))
            for selector in ("#search-key", "#key-mode", "#search-value", "#value-mode", "#match-case",
                             "#scope-flavor", "#scope-account", "#scope-character", "#scope-addon", "#new-type",
                             "#new-text"):
                self.assertTrue(popup.query_one(selector).display, selector)
            self.assertFalse(popup.query_one("#new-bool", Ka0sCheckbox).display)
            controls = [w for w in popup.query("*") if w.focusable and w.display]
            rows = [w.region.y for w in controls if not isinstance(w, Button)]
            self.assertEqual(len(rows), len(set(rows)))
            box = popup.query_one(".popup-box").region
            self.assertLessEqual(box.bottom, BASE[1])
            for widget in controls:  # everything shows at 120x30 without scrolling
                self.assertTrue(box.contains_region(widget.region), widget)
            buttons = {b.id: b for b in popup.query(Button)}
            self.assertEqual((buttons["find"].label_text, action_kind(buttons["find"])), ("Find", "confirm"))
            self.assertEqual((buttons["cancel"].shortcut, action_kind(buttons["cancel"])), ("escape", "cancel"))
            assert_keys_on_buttons(self, popup)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIsNone(review.hits)

    async def test_one_flavor_has_no_flavor_select_and_the_scope_lists_what_was_scanned(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            popup = await self.open_search(review, pilot)
            self.assertFalse(popup.query("#scope-flavor"))
            accounts = popup.query_one("#scope-account", Select)
            self.assertEqual([value for _, value in accounts._options],
                             ["", "ACCT1", "ACCT2"])
            characters = popup.query_one("#scope-character", Select)
            self.assertEqual([value for _, value in characters._options],
                             ["", OWNER_ACCOUNT_WIDE, "Realm1/Kaelys", "Realm2/Chârb"])
            await pilot.press("escape")
            await settle(app, pilot)

    async def test_find_shows_what_is_wrong_in_the_popup(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            popup = await self.open_search(review, pilot)
            await pilot.click("#find")
            await settle(app, pilot)
            self.assertIs(app.screen, popup)
            self.assertEqual(error_text(popup, "#search-error"), NEED_TEXT)
            await self.fill(popup, pilot, search_value="Friz")
            self.assertEqual(error_text(popup, "#search-error"), "")  # a change clears the problem
            for fields, problem in (({"new_type": REPLACE_NUMBER, "new_text": "abc"}, "Enter a number"),
                                    ({"new_type": REPLACE_NUMBER, "new_text": "1e999"}, "Can't use"),
                                    ({"value_mode": VALUE_CONTAINS, "new_text": "5"}, "must be text")):
                await self.fill(popup, pilot, **fields)
                popup.query_one("#search-value", Input).focus()
                await settle(app, pilot)
                await pilot.press("enter")  # Enter in a field is Find
                await settle(app, pilot)
                self.assertIs(app.screen, popup, fields)
                self.assertIn(problem, error_text(popup, "#search-error"), fields)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsNone(review.hits)

    async def test_a_boolean_replacement_is_a_checkbox_and_the_popup_returns_the_spec(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            popup = await self.open_search(review, pilot)
            await self.fill(popup, pilot, search_key="font", key_mode=KEY_CONTAINS, match_case=True,
                            scope_flavor="_retail_", scope_account="ACCT1", scope_character=OWNER_ACCOUNT_WIDE,
                            scope_addon="elv", new_type=REPLACE_BOOLEAN)
            self.assertTrue(popup.query_one("#new-bool", Ka0sCheckbox).display)
            self.assertFalse(popup.query_one("#new-text", Input).display)
            popup.query_one("#new-bool", Ka0sCheckbox).value = True
            spec = popup.spec()
            self.assertEqual((spec.key, spec.key_mode, spec.value, spec.match_case, spec.replacement),
                             ("font", KEY_CONTAINS, "", True, True))
            self.assertEqual((spec.scope.flavor, spec.scope.account, spec.scope.character, spec.scope.addon),
                             ("_retail_", "ACCT1", OWNER_ACCOUNT_WIDE, "elv"))
            await pilot.press("escape")
            await settle(app, pilot)


class SearchResultsTest(SearchTestBase):
    async def test_find_runs_with_the_progress_popup_and_fills_the_results_all_ticked(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            progress = []
            real = review_screen.SearchProgressScreen

            def make(*args, **kwargs):
                progress.append(real(*args, **kwargs))
                return progress[-1]
            run = mock.Mock(wraps=review_screen.run_search)
            with capture_events() as events, mock.patch.object(review_screen, "SearchProgressScreen", make), \
                    mock.patch.object(review_screen, "run_search", run):
                await self.search(review, pilot, search_value=FRIZ, new_text="Arial")
            names = [e["event"] for e in events]
            self.assertIn("svb.search_started", names)
            self.assertIn("svb.search_completed", names)
            self.assertEqual(len(progress), 1)
            self.assertEqual(run.call_args.kwargs["parallelism"], self.cfg.parallelism)
            self.assertFalse(app.busy)
            self.assertEqual(review.view, RESULTS)
            self.assertEqual(review.sub_title, "Saved Variables Browser · All flavors · Results")
            self.assertEqual(len(review.hits), 7)
            self.assertEqual(review.ticked, set(range(7)))
            root = self.tree_root(review)
            retail = child(root, "✔ Retail")
            self.assertIn("6 results", retail.label.plain)
            elv = child(child(child(retail, "✔ ACCT1"), "✔ Account-wide"), "✔ ElvUI.lua")
            self.assertEqual(labels(elv), [
                f'✔ ElvDB › profiles › Default › general › font = "{FRIZ}" → "Arial"',
                f'✔ ElvDB › profiles › Default › unitframe › Font = "{FRIZ}" → "Arial"'])
            kaelys = child(child(child(retail, "✔ ACCT1"), "✔ Realm1/Kaelys"), "✔ ElvUI.lua")
            self.assertEqual(hits_of(kaelys), [
                f'✔ ElvCharacterDB › nested › deeper › barFont = "{FRIZ}" → "Arial"'])
            self.assertEqual(len(hits_of(child(root, "✔ Classic Era"))), 1)
            self.assertEqual(self.pending(review).splitlines(),
                             ["Staged: 0 edits · Ticked: 7 results in 6 files", "Results: 7 hits in 6 files"])
            self.assertFalse(review.query_one("#btn-apply", Button).disabled)
            self.assertFalse(review.query_one("#act-view", Button).disabled)
            self.assertTrue(review.query_one("#act-edit", Button).disabled)

    async def test_match_case_and_contains(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value="friz quadrata tt", new_text="x")
            self.assertEqual(len(review.hits), 7)
            await pilot.press("n")  # nothing ticked: a new search does not ask
            await self.search(review, pilot, match_case=True)  # the popup keeps the last search
            self.assertEqual(hits_of(self.tree_root(review)), ['✔ Bartender4DB › font = "friz quadrata tt" → "x"'])
            await pilot.press("n")
            await self.search(review, pilot, search_value="Quadrata", value_mode=VALUE_CONTAINS, match_case=False,
                              new_text="Q.")
            self.assertEqual(len(review.hits), 7)
            self.assertTrue(any(f'font = "{FRIZ}" → "Friz Q. TT"' in h for h in hits_of(self.tree_root(review))))

    async def test_the_scope_narrows_the_files_searched(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            for fields, count in (({"scope_flavor": "_classic_era_"}, 1),
                                  ({"scope_flavor": "", "scope_character": OWNER_ACCOUNT_WIDE}, 5),
                                  ({"scope_character": "", "scope_account": "ACCT2"}, 2),
                                  ({"scope_account": "", "scope_addon": "ELV"}, 3)):
                await pilot.press("n")
                await self.search(review, pilot, search_value=FRIZ, **fields)
                self.assertEqual(len(review.hits), count, fields)

    async def test_find_only_shows_the_hits_without_ticks(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ, new_type=FIND_ONLY)
            self.assertEqual(review.ticked, set())
            hits = hits_of(self.tree_root(review))
            self.assertEqual(len(hits), 7)
            self.assertTrue(all("→" not in h and not h.startswith("✔") for h in hits), hits)
            await pilot.press("a")
            self.assertEqual(review.ticked, set())
            self.assertEqual(self.pending(review).splitlines(),
                             ["Staged: 0 edits · Ticked: 0 results in 0 files",
                              "Results: 7 hits in 6 files (find only)"])
            self.assertTrue(review.query_one("#btn-apply", Button).disabled)

    async def test_nothing_found_says_so(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_key="no such key")
            self.assertEqual(review.hits, [])
            self.assertEqual(review.view, RESULTS)
            self.assertEqual(labels(self.tree_root(review)), [review_screen.NOTHING_FOUND])
            self.assertIn("Results: 0 hits", self.pending(review))

    async def test_a_file_that_is_not_lua_is_reported(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_key="font", new_text="x")
            self.assertIn("1 file can't be read", self.pending(review))


class ResultsTicksTest(SearchTestBase):
    async def test_space_a_n_and_the_filter(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ, new_text="Arial")
            tree = review.query_one("#browse", Tree)
            root = self.tree_root(review)
            elv = child(child(child(child(root, "✔ Retail"), "✔ ACCT1"), "✔ Account-wide"), "✔ ElvUI.lua")
            select(tree, elv.children[1])
            tree.focus()
            await pilot.press("space")
            await settle(app, pilot)
            self.assertEqual(len(review.ticked), 6)
            self.assertTrue(elv.children[1].label.plain.startswith("✘"))
            self.assertTrue(elv.label.plain.startswith("◩"))
            self.assertEqual(self.pending(review).splitlines()[0], "Staged: 0 edits · Ticked: 6 results in 6 files")
            await pilot.press("space")  # ticked again
            await settle(app, pilot)
            select(tree, elv)  # on a file: unticks what it holds
            await pilot.press("space")
            await settle(app, pilot)
            self.assertTrue(elv.label.plain.startswith("✘"))
            self.assertEqual(len(review.ticked), 5)
            await pilot.press("a")
            await settle(app, pilot)
            self.assertEqual(len(review.ticked), 7)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertEqual(review.ticked, set())
            self.assertTrue(review.query_one("#btn-apply", Button).disabled)
            await pilot.press("a")
            # the filter matches every hit (its path, its file, its groups); a and n act on what it shows
            await pilot.press("slash")
            await pilot.press(*"details")
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertEqual(len(hits_of(self.tree_root(review))), 2)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertEqual(len(review.ticked), 5)
            self.assertIn("5 selected results are hidden by the filter", review.summary_text)
            review.filter_input().value = "unitframe"
            await settle(app, pilot)
            self.assertEqual(hits_of(self.tree_root(review)),
                             [f'✔ ElvDB › profiles › Default › unitframe › Font = "{FRIZ}" → "Arial"'])

    async def test_v_switches_views_and_a_n_do_nothing_in_browse(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ, new_text="Arial")
            await pilot.press("v")
            await settle(app, pilot)
            self.assertEqual(review.view, BROWSE)
            self.assertEqual(review.sub_title, "Saved Variables Browser · All flavors · Browse")
            self.assertEqual(hits_of(self.tree_root(review)), [])
            self.assertTrue(child(self.tree_root(review), "Retail").label.plain.startswith("Retail"))
            await pilot.press("n")
            await settle(app, pilot)
            self.assertEqual(len(review.ticked), 7)  # the ticks are the Results view's
            await pilot.press("v")
            await settle(app, pilot)
            self.assertEqual(review.view, RESULTS)
            self.assertEqual(len(hits_of(self.tree_root(review))), 7)

    async def test_a_new_search_over_ticked_results_asks_first(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ, new_text="Arial")
            await pilot.press("S")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertEqual(app.screen.kind, "destructive")
            self.assertIn("7 ticked results", app.screen.body_text)
            await pilot.press("n")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            await pilot.press("S")
            await settle(app, pilot)
            await pilot.press("y")
            await settle(app, pilot)
            popup = app.screen
            self.assertIsInstance(popup, SearchScreen)
            self.assertEqual(popup.query_one("#search-value", Input).value, FRIZ)  # the last search
            await pilot.press("escape")  # Cancel keeps the results
            await settle(app, pilot)
            self.assertEqual(len(review.ticked), 7)

    async def test_leaving_with_ticked_results_asks(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ, new_text="Arial")
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("7 ticked results", app.screen.body_text)
            await pilot.press("n")
            await settle(app, pilot)

    async def test_the_cap_note_says_how_many_were_dropped(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            with mock.patch("wowtools.tools.sv_browser.search.HIT_CAP", 3):
                await self.search(review, pilot, search_value=FRIZ, new_text="Arial")
            self.assertEqual(len(review.hits), 3)
            self.assertIn("4 more hits left out", self.pending(review))
            self.assertIn("narrow the search", self.pending(review))


class StagedEditWinsTest(SvEditTestBase, SearchTestBase):
    async def test_a_ticked_result_on_a_staged_value_is_left_out(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "font ="), "e")
            popup.query_one("#value-text", Input).value = "Expressway"
            await pilot.press("enter")
            await settle(app, pilot)
            await self.search(review, pilot, search_value=FRIZ, new_text="Arial")
            lines = self.pending(review).splitlines()
            self.assertEqual(lines[0], "Staged: 1 edit · Ticked: 6 results in 5 files")
            self.assertIn("1 ticked result left out: a staged edit wins", lines)
            leaf = next(n for n in walk(self.tree_root(review))
                        if n.data is not None and n.data[0] == "hit" and "general › font" in n.label.plain)
            self.assertIn(HAS_STAGED_EDIT, leaf.label.plain)
            plan = review.staging.plans(review.ticked_hits())
            self.assertEqual((plan.staged, plan.hits, len(plan.dropped)), (1, 5, 1))


class SearchAtTinyTest(SearchTestBase):
    async def test_the_popup_scrolls_at_80x24_and_every_field_is_reachable(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot)
            popup = await self.open_search(review, pilot)
            box = popup.query_one(".popup-box").region
            self.assertLessEqual(box.bottom, TINY[1])
            self.assertLessEqual(box.right, TINY[0])
            seen = []
            for _ in range(20):  # ↓ walks every field and the buttons, each scrolled into view
                focused = popup.focused
                seen.append(focused.id)
                region = focused.region
                self.assertTrue(region.height > 0 and box.contains_region(region), (focused.id, region, box))
                if focused.id == "cancel":
                    break
                await pilot.press("down")
                await settle(app, pilot)
            self.assertEqual(seen[:2], ["search-key", "key-mode"])
            self.assertIn("new-text", seen)
            self.assertEqual(seen[-2:], ["find", "cancel"])
            await self.fill(popup, pilot, search_value=FRIZ)
            popup.action_find()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvReviewScreen)
            self.assertEqual(len(review.hits), 7)
            self.assertGreater(review.query_one("#pending", Static).region.height, 1)
