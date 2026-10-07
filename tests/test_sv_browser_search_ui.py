"""Saved Variables Browser search (spec D6-D11, D38, D39, §5): the Search popup (key, a blank row, value, their modes,
Match case, the scope; it only finds), its checks, the search job with the shared progress popup, the Results view
(flavor › account › owner › file › one ticked leaf per hit, `path = old`), ticks and the filter there, v between the
views, a new search, the cap note, and the bulk Edit value / Rename key on the ticked hits into the staging."""
from __future__ import annotations

from unittest import mock

from textual.widgets import Button, Input, Select, Static, Tree

from tests.fixtures import BASE, TINY, assert_keys_on_buttons, settle, submit_filter
from tests.test_sv_browser_app import SvBrowserTestBase, child, labels, select, walk
from tests.test_sv_browser_edit import SvEditTestBase, error_text
from wowtools.core.events import capture_events
from wowtools.core.svfiles import OWNER_ACCOUNT_WIDE
from wowtools.tools.sv_browser import review_screen
from wowtools.tools.sv_browser.bulk import MATCHED, WHOLE
from wowtools.tools.sv_browser.ops import ALREADY_STAGED, BYTES_DIFFER, FILE_CHANGED, FieldEdit
from wowtools.tools.sv_browser.popups import EditValueScreen, RenameKeyScreen, SearchScreen
from wowtools.tools.sv_browser.review_screen import BROWSE, RESULTS, SvReviewScreen
from wowtools.tools.sv_browser.search import KEY_CONTAINS, NEED_TEXT, REPLACE_NUMBER, VALUE_CONTAINS
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.widgets import Ka0sCheckbox, NavHint, action_kind

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
        """Set the popup's fields: ids with - written as _ (search_value="x", value_mode=VALUE_CONTAINS, ...)."""
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

    async def bulk_value(self, review, pilot, text: str, mode: str | None = None, kind: str | None = None):
        """In Results: e, then the value (the mode and type when given), OK; returns the popup."""
        tree = review.query_one("#browse", Tree)
        tree.focus()
        await settle(review.app, pilot)
        await pilot.press("e")
        await settle(review.app, pilot)
        popup = review.app.screen
        self.assertIsInstance(popup, EditValueScreen)
        if mode is not None:
            popup.query_one("#edit-mode", Select).value = mode
            await settle(review.app, pilot)
        if kind is not None:
            popup.query_one("#value-type", Select).value = kind
            await settle(review.app, pilot)
        popup.query_one("#value-text", Input).value = text
        await settle(review.app, pilot)
        await pilot.click("#ok")
        await settle(review.app, pilot)
        if review.app.screen is not review:
            self.fail(f"the popup stayed open: {error_text(popup, '#value-error')}")
        return popup

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
                             "#scope-flavor", "#scope-account", "#scope-character", "#scope-addon"):
                self.assertTrue(popup.query_one(selector).display, selector)
            for gone in ("#new-type", "#new-text", "#new-bool"):  # D38: the search only finds
                self.assertFalse(popup.query(gone), gone)
            # D38: one blank row between Key + Key match and Value + Value match
            self.assertEqual(popup.query_one("#search-value").region.y - popup.query_one("#key-mode").region.y, 2)
            self.assertEqual(popup.query_one("#value-mode").region.y - popup.query_one("#search-value").region.y, 1)
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
            await self.fill(popup, pilot, search_value="")
            popup.query_one("#search-value", Input).focus()
            await settle(app, pilot)
            await pilot.press("enter")  # Enter in a field is Find
            await settle(app, pilot)
            self.assertIs(app.screen, popup)
            self.assertEqual(error_text(popup, "#search-error"), NEED_TEXT)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsNone(review.hits)

    async def test_the_popup_returns_the_spec(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            popup = await self.open_search(review, pilot)
            await self.fill(popup, pilot, search_key="font", key_mode=KEY_CONTAINS, match_case=True,
                            scope_flavor="_retail_", scope_account="ACCT1", scope_character=OWNER_ACCOUNT_WIDE,
                            scope_addon="elv")
            spec = popup.spec()
            self.assertEqual((spec.key, spec.key_mode, spec.value, spec.match_case),
                             ("font", KEY_CONTAINS, "", True))
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
                await self.search(review, pilot, search_value=FRIZ)
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
                f'✔ ElvDB › profiles › Default › general › font = "{FRIZ}"',
                f'✔ ElvDB › profiles › Default › unitframe › Font = "{FRIZ}"'])
            kaelys = child(child(child(retail, "✔ ACCT1"), "✔ Realm1/Kaelys"), "✔ ElvUI.lua")
            self.assertEqual(hits_of(kaelys), [f'✔ ElvCharacterDB › nested › deeper › barFont = "{FRIZ}"'])
            self.assertEqual(len(hits_of(child(root, "✔ Classic Era"))), 1)
            self.assertEqual(self.pending(review).splitlines(),
                             ["Staged: 0 edits in 0 files", "Results: 7 hits in 6 files", "Ticked: 7 results"])
            self.assertTrue(review.query_one("#btn-apply", Button).disabled)  # ticks only select (D39)
            self.assertFalse(review.query_one("#act-view", Button).disabled)
            self.assertFalse(review.query_one("#act-edit", Button).disabled)
            self.assertFalse(review.query_one("#act-rename", Button).disabled)
            self.assertTrue(review.query_one("#act-delete", Button).disabled)

    async def test_match_case_and_contains(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value="friz quadrata tt")
            self.assertEqual(len(review.hits), 7)
            await self.search(review, pilot, match_case=True)  # the popup keeps the last search
            self.assertEqual(hits_of(self.tree_root(review)), ['✔ Bartender4DB › font = "friz quadrata tt"'])
            await self.search(review, pilot, search_value="Quadrata", value_mode=VALUE_CONTAINS, match_case=False)
            self.assertEqual(len(review.hits), 7)

    async def test_the_scope_narrows_the_files_searched(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            for fields, count in (({"scope_flavor": "_classic_era_"}, 1),
                                  ({"scope_flavor": "", "scope_character": OWNER_ACCOUNT_WIDE}, 5),
                                  ({"scope_character": "", "scope_account": "ACCT2"}, 2),
                                  ({"scope_account": "", "scope_addon": "ELV"}, 3)):
                await self.search(review, pilot, search_value=FRIZ, **fields)
                self.assertEqual(len(review.hits), count, fields)

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
            await self.search(review, pilot, search_key="font")
            self.assertIn("1 file can't be read", self.pending(review))


class ResultsTicksTest(SearchTestBase):
    async def test_space_a_n_and_the_filter(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ)
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
            self.assertEqual(self.pending(review).splitlines()[2], "Ticked: 6 results")
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
            self.assertTrue(review.query_one("#act-edit", Button).disabled)  # nothing ticked, a group highlighted
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
            submit_filter(review, "unitframe")
            await settle(app, pilot)
            self.assertEqual(hits_of(self.tree_root(review)),
                             [f'✔ ElvDB › profiles › Default › unitframe › Font = "{FRIZ}"'])

    async def test_v_switches_views_and_a_n_do_nothing_in_browse(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ)
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

    async def test_a_new_search_does_not_ask_and_keeps_the_staged_edits(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ)
            await self.bulk_value(review, pilot, "Arial")
            popup = await self.open_search(review, pilot)  # ticks only select: no confirm
            self.assertEqual(popup.query_one("#search-value", Input).value, FRIZ)  # the last search
            await pilot.press("escape")  # Cancel keeps the results
            await settle(app, pilot)
            self.assertEqual(len(review.ticked), 7)
            await self.search(review, pilot, search_value="Expressway")
            self.assertEqual(review.staging.count, 7)
            self.assertEqual(len(review.ticked), len(review.hits))

    async def test_leaving_with_only_ticked_results_does_not_ask(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ)
            await pilot.press("t")
            await settle(app, pilot)
            self.assertNotIsInstance(app.screen, ConfirmScreen)
            self.assertIsNot(app.screen, review)

    async def test_the_cap_note_says_how_many_were_dropped(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            with mock.patch("wowtools.tools.sv_browser.search.HIT_CAP", 3):
                await self.search(review, pilot, search_value=FRIZ)
            self.assertEqual(len(review.hits), 3)
            self.assertIn("4 more hits left out", self.pending(review))
            self.assertIn("narrow the search", self.pending(review))


class BulkEditTest(SvEditTestBase, SearchTestBase):
    """D39: Edit value and Rename key on the ticked results stage one edit per hit."""

    def values(self, review) -> set:
        return {e.value for p in review.staging.plans().files.values() for e in p.edits}

    async def test_edit_value_on_the_ticked_hits_stages_one_edit_each(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ)
            with mock.patch.object(review, "notify") as notify, capture_events() as events:
                popup = await self.bulk_value(review, pilot, "Arial")
            self.assertEqual(popup.title_text, "Edit 7 values")
            self.assertIn("7 ticked results in 6 files", popup.where)
            self.assertFalse(popup.query("#edit-mode"))  # a whole value search: no matched-text choice
            self.assertIn("Staged 7 edits.", notify.call_args.args[0])
            self.assertIn("svb.bulk_staged", [e["event"] for e in events])
            self.assertEqual(review.staging.count, 7)
            self.assertEqual(self.values(review), {"Arial"})
            # the Results view stays, ticks kept, the hits marked as Browse marks them
            self.assertEqual(review.view, RESULTS)
            self.assertEqual(len(review.ticked), 7)
            self.assertTrue(all(h.endswith('✎ "Arial"') for h in hits_of(self.tree_root(review))))
            self.assertEqual(self.pending(review).splitlines()[0], "Staged: 7 edits in 6 files")
            self.assertFalse(review.query_one("#btn-apply", Button).disabled)
            # again: every hit already has a staged edit
            with mock.patch.object(review, "notify") as notify:
                await self.bulk_value(review, pilot, "Other")
            self.assertIn(f"7 · {ALREADY_STAGED}", notify.call_args.args[0])
            self.assertEqual(self.values(review), {"Arial"})

    async def test_browse_shows_the_marks_of_a_bulk_edit(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            await self.search(review, pilot, search_value=FRIZ)
            await self.bulk_value(review, pilot, "Arial")
            await pilot.press("v")
            await settle(app, pilot)
            tree = review.query_one("#browse", Tree)
            wide = child(child(child(tree.root, "Retail"), "ACCT1"), "Account-wide")
            elv = await self.open_node(review, pilot, child(wide, "ElvUI.lua"))
            db = await self.open_node(review, pilot, child(elv, "ElvDB"))
            default = await self.open_node(review, pilot, child(await self.open_node(review, pilot,
                                                                                     child(db, "profiles")),
                                                                "Default"))
            general = await self.open_node(review, pilot, child(default, "general"))
            self.assertTrue(child(general, "font =").label.plain.endswith('✎ "Arial"'))

    async def test_matched_text_or_whole_value_after_a_contains_search(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value="quadrata", value_mode=VALUE_CONTAINS)
            tree = review.query_one("#browse", Tree)
            tree.focus()
            await pilot.press("e")
            await settle(app, pilot)
            popup = app.screen
            self.assertEqual(popup.query_one("#edit-mode", Select).value, MATCHED)  # the default
            self.assertFalse(popup.query_one("#value-type", Select).display)  # matched text is text
            assert_keys_on_buttons(self, popup)
            await pilot.press("escape")
            await settle(app, pilot)
            await self.bulk_value(review, pilot, "Q")
            self.assertEqual(self.values(review), {"Friz Q TT", "friz Q tt"})
            review.staging.clear()
            await self.bulk_value(review, pilot, "5", mode=WHOLE, kind=REPLACE_NUMBER)
            self.assertEqual(self.values(review), {5})

    async def test_with_nothing_ticked_the_highlighted_hit_is_edited(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ)
            tree = review.query_one("#browse", Tree)
            tree.focus()
            await pilot.press("n")
            await settle(app, pilot)
            leaf = next(n for n in walk(tree.root) if n.data is not None and n.data[0] == "hit")
            select(tree, leaf)
            await settle(app, pilot)
            popup = await self.bulk_value(review, pilot, "Arial")
            self.assertEqual(popup.title_text, "Edit value")
            self.assertEqual(popup.current, f'"{FRIZ}"')
            self.assertEqual(review.staging.count, 1)
            hit = review.hits[leaf.data[1]]
            self.assertEqual(review.staging.hit_edit(hit), FieldEdit(hit.path, set_value=True, value="Arial"))
            # Backspace (Unstage) on the hit drops it
            self.assertFalse(review.query_one("#act-unstage", Button).disabled)
            await pilot.press("backspace")
            await settle(app, pilot)
            self.assertEqual(review.staging.count, 0)
            self.assertNotIn("✎", leaf.label.plain)

    async def test_a_hit_with_an_edit_staged_in_browse_is_left_out(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, general = await self.general(app, pilot)
            popup = await self.press_on(review, pilot, child(general, "font ="), "e")
            popup.query_one("#value-text", Input).value = "Expressway"
            await pilot.press("enter")
            await settle(app, pilot)
            await self.search(review, pilot, search_value=FRIZ)
            with mock.patch.object(review, "notify") as notify:
                await self.bulk_value(review, pilot, "Arial")
            text = notify.call_args.args[0]
            self.assertIn("Staged 5 edits.", text)
            self.assertIn(f"1 · {ALREADY_STAGED}", text)
            self.assertEqual(notify.call_args.kwargs["severity"], "warning")
            self.assertEqual(self.values(review), {"Expressway", "Arial"})
            leaf = next(n for n in walk(self.tree_root(review))
                        if n.data is not None and n.data[0] == "hit" and "general › font" in n.label.plain)
            self.assertTrue(leaf.label.plain.endswith('✎ "Expressway"'))

    async def test_a_file_opened_in_browse_then_changed_on_disk_leaves_its_hits_out(self):
        """D39: the review passes the loaded documents' hashes, so a hit read from newer bytes than the document Browse
        shows is left out (and the reason says a rescan is needed: a new search reads the same newer bytes)."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review, _ = await self.general(app, pilot)
            (path,) = [p for p, d in review.docs.items() if d.loaded]
            path.write_bytes(path.read_bytes().replace(b"Expressway", b"Expresswax"))
            await self.search(review, pilot, search_value=FRIZ)
            mine = sum(1 for h in review.hits if h.file.path == path)
            self.assertTrue(mine)
            with mock.patch.object(review, "notify") as notify:
                await self.bulk_value(review, pilot, "Arial")
            self.assertIn(f"{mine} · {BYTES_DIFFER}", notify.call_args.args[0])
            self.assertEqual(review.staging.count, len(review.hits) - mine)

    async def test_unstage_on_a_renamed_hit_reads_its_table_in_a_worker_and_gives_the_reason(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            await self.search(review, pilot, search_key="Font", match_case=True)
            tree = review.query_one("#browse", Tree)
            tree.focus()
            await pilot.press("k")
            await settle(app, pilot)
            app.screen.query_one(Input).value = "face"
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            await settle(app, pilot)
            count = review.staging.count
            self.assertTrue(count)
            leaf = next(n for n in walk(tree.root) if n.data is not None and n.data[0] == "hit")
            select(tree, leaf)
            await settle(app, pilot)
            hit = review.hits[leaf.data[1]]
            hit.file.path.write_bytes(hit.file.path.read_bytes() + b"\n")
            with mock.patch.object(review, "start_run", wraps=review.start_run) as run, \
                    mock.patch.object(review, "notify") as notify:
                await pilot.press("backspace")
                await settle(app, pilot)
                await settle(app, pilot)
            run.assert_called_once()  # the file is read in a worker, under the progress popup
            self.assertIs(app.screen, review)
            self.assertFalse(app.busy)
            self.assertEqual(notify.call_args.args[0], FILE_CHANGED)
            self.assertEqual(review.staging.count, count)

    async def test_rename_on_the_ticked_hits(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            await self.search(review, pilot, search_key="font", value_mode=VALUE_CONTAINS)
            count = len(review.hits)
            tree = review.query_one("#browse", Tree)
            tree.focus()
            await pilot.press("k")
            await settle(app, pilot)
            popup = app.screen
            self.assertIsInstance(popup, RenameKeyScreen)
            self.assertEqual(popup.query_one(".title", Static).render().plain, f"Rename {count} keys")
            field = popup.query_one(Input)
            self.assertEqual(field.value, "")  # font and Font: no one key to start from
            field.value = "face"
            await settle(app, pilot)
            with mock.patch.object(review, "notify") as notify:
                await pilot.press("enter")
                await settle(app, pilot)
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertFalse(app.busy)
            self.assertIn(f"Staged {count} edits.", notify.call_args.args[0])
            self.assertEqual(review.staging.count, count)
            self.assertTrue(all("→ face" in h for h in hits_of(self.tree_root(review))))
            # Unstage on a renamed hit reads its table again (no key left twice) and drops it
            leaf = next(n for n in walk(tree.root) if n.data is not None and n.data[0] == "hit")
            select(tree, leaf)
            await settle(app, pilot)
            await pilot.press("backspace")
            await settle(app, pilot)
            self.assertEqual(review.staging.count, count - 1)

    async def test_delete_stays_single_key(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search(review, pilot, search_value=FRIZ)
            tree = review.query_one("#browse", Tree)
            leaf = next(n for n in walk(tree.root) if n.data is not None and n.data[0] == "hit")
            select(tree, leaf)
            tree.focus()
            await settle(app, pilot)
            self.assertTrue(review.query_one("#act-delete", Button).disabled)
            await pilot.press("d")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.staging.count, 0)


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
            self.assertIn("scope-addon", seen)
            self.assertEqual(seen[-2:], ["find", "cancel"])
            await self.fill(popup, pilot, search_value=FRIZ)
            popup.action_find()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvReviewScreen)
            self.assertEqual(len(review.hits), 7)
            self.assertGreater(review.query_one("#pending", Static).region.height, 1)


class ReviewKeysTest(SearchTestBase):
    """The M3 review's key fixes: Enter in the search popup's checkboxes, → on the Search button, Space / a / n only
    where there is something to tick, and a load that ends after a rescan."""

    async def test_enter_on_match_case_finds_and_space_ticks(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            popup = await self.open_search(review, pilot)
            self.assertIn("Space tick", popup.query_one(NavHint).hint)
            await self.fill(popup, pilot, search_value=FRIZ)
            box = popup.query_one("#match-case", Ka0sCheckbox)
            box.focus()
            await settle(app, pilot)
            await pilot.press("space")
            await settle(app, pilot)
            self.assertTrue(box.value)
            await pilot.press("enter")  # Find, as the hint says
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertTrue(review.last_spec.match_case)
            self.assertEqual(review.view, RESULTS)

    async def test_right_on_the_search_button_goes_to_the_tree(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            review.query_one("#btn-search", Button).focus()
            await settle(app, pilot)
            await pilot.press("right")
            await settle(app, pilot)
            self.assertIs(review.focused, review.query_one("#browse", Tree))

    async def test_space_a_n_say_why_where_nothing_can_be_ticked(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#browse", Tree)
            tree.focus()
            await settle(app, pilot)

            async def said(key: str) -> list[str]:
                with mock.patch.object(review, "notify") as notify:
                    await pilot.press(key)
                    await settle(app, pilot)
                return [c.args[0] for c in notify.call_args_list]
            for key in ("space", "a", "n"):  # Browse: nothing to tick
                self.assertEqual(await said(key), [review_screen.NO_TICKS_BROWSE], key)
            await self.search(review, pilot, search_value=FRIZ)
            tree.focus()
            self.assertEqual(await said("n"), [])
            self.assertEqual(review.ticked, set())
            self.assertEqual(await said("a"), [])
            self.assertEqual(len(review.ticked), 7)

    async def test_a_load_that_ends_after_a_rescan_keeps_the_new_loads_guard(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            key = ("file", "a file being read again")
            review._loading.add(key)  # the new scan's load of it runs
            review._loaded(key, review._generation - 1)  # the old scan's load ends
            self.assertIn(key, review._loading)
            review._loaded(key, review._generation)
            self.assertNotIn(key, review._loading)
