"""Saved Variables Browser runs from the review (spec D13-D16, D21, §5): Apply (w) and Dry run (y) with their confirm
(counts per flavor and file, the USE AT YOUR OWN RISK disclaimer as red alert lines on Apply, the alert when the
WoW check could not run), the refusal while WoW runs, the result screen (summary with the zips and the journal, one
row per file; Back to review after a dry run), Undo last change (z) with the disclaimer and the staged work it drops,
the rescan after a run, and the unfinished-run popup on a scan (put back or leave). End to end: search, Apply, the
files, the snapshot, the originals zip and the journal, then Undo back to the same bytes."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, DataTable

from tests.fixtures import BASE, SVB_FONT, TINY, accept_disclaimer, settle, stage_sv_edit
from tests.test_sv_browser_app import TOOL
from tests.test_sv_browser_search_ui import SearchTestBase
from wowtools.core import sv_journal
from wowtools.core.events import capture_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.core.luasv import key_id
from wowtools.core.sv_apply import ApplyError
from wowtools.tools.sv_browser import editor, undo
from wowtools.tools.sv_browser.events import SV_TOOL
from wowtools.tools.sv_browser.journal import latest_undoable, resolve_journal_dir
from wowtools.tools.sv_browser.model import SvDocument
from wowtools.tools.sv_browser.ops import Staging
from wowtools.tools.sv_browser.report import DISCLAIMER
from wowtools.tools.sv_browser.result_screen import SvResultScreen
from wowtools.tools.sv_browser.review_screen import BROWSE, SvReviewScreen
from wowtools.tools.sv_browser.scanner import scan_flavors
from wowtools.tools.sv_browser.settings import SvBrowserSettings, resolve_root, save_settings
from wowtools.ui.dialogs import ConfirmScreen, UnfinishedRunScreen
from wowtools.ui.help_screen import HelpScreen
from wowtools.ui.suite_app import WowToolsApp

NEW_FONT = "Skurri Bold"  # in no fixture file: finding it after Apply proves the replace
UNKNOWN = "Could not check whether WoW is running"


def stage(staging: Staging, file, keys, value) -> None:
    doc = SvDocument(file)
    nodes, node = doc.roots(), None
    for key in keys:
        node = next(n for n in nodes if key_id(n.key) == key_id(key))
        nodes = doc.children(node) if node.is_table else []
    assert staging.set_value(doc, node, value).ok


def crash_retail(wow: Path) -> None:
    """An Apply of two retail files that died while writing the second, the first not put back: its marker stays
    (as after a power cut)."""
    retail = WowInstall(wow).flavor("_retail_")
    files = scan_flavors([retail]).files()
    elvui, details = (next(f for f in files if f.path.name == name and f.account == "ACCT1" and f.character is None)
                      for name in ("ElvUI.lua", "Details.lua"))
    staging = Staging()
    stage(staging, elvui, ("ElvDB", "profiles", "Default", "general", "font"), NEW_FONT)
    stage(staging, details, ("_detalhes_global", "font_face"), "Morpheus")

    def write(path, data):
        if path == details.path:
            raise OSError("killed")
        atomic_write_bytes(path, data)
    journal_dir = resolve_journal_dir(wow)
    record = sv_journal.EditJournal(journal_dir / "journal-20261007-120000.jsonl",
                                    {"tool": SV_TOOL.name, "kind": "apply"})
    flavor, units = editor.flavor_plan(staging.plans())[0]
    try:
        with patch("wowtools.core.sv_apply.restore_original", side_effect=OSError("no")):
            editor.apply_flavor(flavor, units, root=resolve_root(SvBrowserSettings(), wow), journal=record,
                                dry_run=False, keep_snapshots=2, write=write)
    except ApplyError:
        pass
    finally:
        record.close()
    assert undo.pending_recovery(resolve_root(SvBrowserSettings(), wow)) is not None


class RunTestBase(SearchTestBase):
    def tree_bytes(self) -> dict[Path, bytes]:
        """Every file of the install outside the tool's own folder."""
        return {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file() and "wow-tools" not in p.parts}

    def make_app(self, wow_check=list):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options={TOOL: {"wow_check": wow_check}})

    @property
    def tool_root(self) -> Path:
        return resolve_root(SvBrowserSettings(), self.root)

    async def search_friz(self, review, pilot) -> None:
        await self.search(review, pilot, search_value=SVB_FONT, new_text=NEW_FONT)
        self.assertTrue(review.ticked)

    async def press(self, app, pilot, *keys) -> None:
        await pilot.press(*keys)
        await settle(app, pilot)

    async def applied_review(self, app, pilot) -> SvReviewScreen:
        """Retail with one edit applied (an Undo is offered), the review read again after the result."""
        review = await self.open_review(app, pilot, "_retail_")
        stage_sv_edit(review)
        await self.press(app, pilot, "w")
        self.assertIsInstance(app.screen, ConfirmScreen)
        app.screen.dismiss(True)
        await settle(app, pilot)
        self.assertIsInstance(app.screen, SvResultScreen)
        await self.press(app, pilot, "r")
        self.assertIs(app.screen, review)
        self.assertEqual(review.pending, 0)
        return review

    async def open_to_recovery(self, app, pilot) -> UnfinishedRunScreen:
        """Retail, the warning accepted: the scan finds the marker and offers the unfinished run."""
        picker = await self.open_picker(app, pilot)
        picker.dismiss(next(f for f in picker.flavors if f.folder == "_retail_"))
        await settle(app, pilot)
        await accept_disclaimer(app, pilot)
        popup = app.screen
        self.assertIsInstance(popup, UnfinishedRunScreen)
        return popup

    def rows(self, result: SvResultScreen) -> dict[str, str]:
        table = result.query_one("#result-summary", DataTable)
        return {str(table.get_row_at(i)[0]): str(table.get_row_at(i)[1]) for i in range(table.row_count)}

    def details(self, result: SvResultScreen) -> list[list[str]]:
        table = result.query_one("#result-detail", DataTable)
        return [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)]


class ApplyConfirmTest(RunTestBase):
    async def test_apply_asks_with_counts_per_flavor_and_file_and_the_disclaimer(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search_friz(review, pilot)
            ticked = set(review.ticked)
            await self.press(app, pilot, "w")
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.kind, "destructive")
            self.assertIn("Retail", confirm.body_text)
            self.assertIn("Classic", confirm.body_text)
            self.assertIn(DISCLAIMER, confirm.alerts)
            self.assertNotIn(UNKNOWN, confirm.body_text)
            self.assertEqual(sorted(confirm.groups), ["Classic Era", "Retail"])
            retail = confirm.groups["Retail"]
            self.assertIn("ACCT1 › Account-wide › ElvUI.lua: 2 edits", retail)
            self.assertIn("ACCT2 › Realm2/Chârb › Bartender4.lua: 1 edit", retail)
            await self.press(app, pilot, "n")
            self.assertIs(app.screen, review)
            self.assertEqual(review.ticked, ticked)  # nothing dropped, nothing written
            self.assertEqual(self.tree_bytes(), before)

    async def test_apply_says_when_the_wow_check_could_not_run(self):
        app = self.make_app(wow_check=lambda: None)
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            stage_sv_edit(review)
            await self.press(app, pilot, "w")
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn(UNKNOWN, app.screen.body_text)
            await self.press(app, pilot, "n")

    async def test_apply_and_undo_are_refused_while_wow_runs(self):
        running: list[str] = []
        app = self.make_app(wow_check=lambda: list(running))
        async with app.run_test(size=BASE) as pilot:
            review = await self.applied_review(app, pilot)
            journal = review.undoable
            self.assertIsNotNone(journal)
            running.append("Wow.exe")
            before = self.tree_bytes()
            stage_sv_edit(review)
            with capture_events() as events:
                await self.press(app, pilot, "w")
            self.assertIs(app.screen, review)
            self.assertIn("svb.wow_running", [e["event"] for e in events])
            self.assertTrue(review.staging.count)  # kept for later
            with capture_events() as events:
                await self.press(app, pilot, "z")  # the journal is read, then WoW is checked: refused
            self.assertIs(app.screen, review)
            self.assertIn("svb.wow_running", [e["event"] for e in events])
            self.assertEqual(review.undoable, journal)
            self.assertTrue(review.staging.count)
            await self.press(app, pilot, "y")  # a dry run writes nothing: allowed
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertEqual(app.screen.kind, "simulate")
            await self.press(app, pilot, "n")
        self.assertEqual(self.tree_bytes(), before)


class DryRunTest(RunTestBase):
    async def test_dry_run_writes_nothing_and_back_keeps_the_work(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search_friz(review, pilot)
            ticked = set(review.ticked)
            await self.press(app, pilot, "y")
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.kind, "simulate")
            self.assertNotIn(DISCLAIMER, confirm.alerts)  # nothing is written
            confirm.dismiss(True)
            await settle(app, pilot)
            result = app.screen
            self.assertIsInstance(result, SvResultScreen)
            self.assertTrue(result.sub_title.startswith("Saved Variables Browser · "), result.sub_title)
            self.assertTrue(result.sub_title.endswith("Dry run result"), result.sub_title)
            rows = self.rows(result)
            self.assertEqual(rows["Would change"], "6 files")
            self.assertEqual(rows["Edits checked"], "7 edits")
            self.assertNotIn("Journal", rows)
            self.assertEqual({row[-1] for row in self.details(result)}, {"would change"})
            self.assertIn("back", {b.id for b in result.query(Button)})
            await self.press(app, pilot, "escape")
            self.assertIs(app.screen, review)
            self.assertEqual(review.ticked, ticked)
        self.assertEqual(self.tree_bytes(), before)


class ApplyUndoEndToEndTest(RunTestBase):
    async def test_search_apply_then_undo_puts_back_the_same_bytes(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search_friz(review, pilot)
            await self.press(app, pilot, "w")
            self.assertIsInstance(app.screen, ConfirmScreen)
            app.screen.dismiss(True)
            await settle(app, pilot)
            result = app.screen
            self.assertIsInstance(result, SvResultScreen)
            self.assertTrue(result.sub_title.endswith("Apply result"), result.sub_title)
            rows = self.rows(result)
            self.assertEqual(rows["Changed"], "6 files")
            self.assertEqual(rows["Edits written"], "7 edits")
            for item in ("Backup folder", "WTF backup (Retail)", "Original files (Retail)",
                         "WTF backup (Classic Era)", "Original files (Classic Era)", "Journal"):
                self.assertIn(item, rows)
            details = self.details(result)
            self.assertEqual(len(details), 6)  # one row per file
            self.assertIn(["Retail", "ACCT1", "Account-wide", "ElvUI.lua", "2 edits", "changed"], details)
            # the files, the snapshots, the originals and the journal
            after = self.tree_bytes()
            changed = [p for p in before if after[p] != before[p]]
            self.assertEqual(len(changed), 6)
            for path in changed:
                self.assertNotIn(NEW_FONT.encode(), before[path])
                self.assertIn(NEW_FONT.encode(), after[path])
                self.assertNotIn(SVB_FONT.casefold().encode(), after[path].lower())
            self.assertEqual(len(list((self.tool_root / "snapshots").glob("*.zip"))), 2)
            self.assertEqual(len(list((self.tool_root / "edited").glob("*.zip"))), 2)
            journal = latest_undoable(resolve_journal_dir(self.root))
            self.assertIsNotNone(journal)
            self.assertTrue(journal.is_file())
            # Rescan from the result: what was applied is gone, the tree is read again
            await self.press(app, pilot, "r")
            self.assertIs(app.screen, review)
            self.assertEqual((review.pending, review.hits, review.view), (0, None, BROWSE))
            self.assertEqual(review.undoable, journal)
            # Undo, with an edit staged since: the confirm says it is dropped
            stage_sv_edit(review)
            await self.press(app, pilot, "z")
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertEqual(confirm.kind, "destructive")
            self.assertIn(DISCLAIMER, confirm.alerts)
            self.assertIn("1 staged edit and 0 ticked results not applied yet will be dropped", confirm.body_text)
            confirm.dismiss(True)
            await settle(app, pilot)
            result = app.screen
            self.assertIsInstance(result, SvResultScreen)
            self.assertTrue(result.sub_title.endswith("Undo result"), result.sub_title)
            self.assertEqual(self.rows(result)["Put back"], "6 files")
            self.assertEqual(self.tree_bytes(), before)  # byte-identical, the staged edit never written
            await self.press(app, pilot, "escape")  # Esc on a result: rescan
            self.assertIs(app.screen, review)
            self.assertEqual(review.pending, 0)
            self.assertIsNone(review.undoable)

    async def test_the_run_works_at_80x24(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            review = await self.open_review(app, pilot, "_retail_")
            stage_sv_edit(review)
            await self.press(app, pilot, "w")
            confirm = app.screen
            self.assertIsInstance(confirm, ConfirmScreen)
            self.assertIs(confirm.focused, confirm.query_one("#yes", Button))
            confirm.dismiss(True)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvResultScreen)
            for button in app.screen.query(Button):
                self.assertTrue(app.screen.region.contains_region(button.region), button)


class RecoveryTest(RunTestBase):
    async def test_an_unfinished_run_is_offered_and_put_back(self):
        before = self.tree_bytes()
        crash_retail(self.root)
        self.assertNotEqual(self.tree_bytes(), before)
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            popup = await self.open_to_recovery(app, pilot)
            self.assertIn("did not finish", popup.message_text)
            with capture_events() as events:
                popup.choose("put_back")
                await settle(app, pilot)
            self.assertIsInstance(app.screen, SvReviewScreen)
            self.assertIn(("svb.recovery_done", "put_back"), [(e["event"], e["data"].get("choice")) for e in events])
            self.assertIsNone(app.screen.marker)
        self.assertEqual(self.tree_bytes(), before)
        self.assertIsNone(undo.pending_recovery(self.tool_root))

    async def test_leave_keeps_the_files_and_esc_offers_it_again_on_apply(self):
        crash_retail(self.root)
        written = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_to_recovery(app, pilot)
            await self.press(app, pilot, "escape")  # no choice: asked again
            review = app.screen
            self.assertIsInstance(review, SvReviewScreen)
            self.assertIsNotNone(review.marker)
            stage_sv_edit(review)
            await self.press(app, pilot, "w")  # Apply would refuse: settle the unfinished run first
            popup = app.screen
            self.assertIsInstance(popup, UnfinishedRunScreen)
            self.assertIn("1 staged edit and 0 ticked results not applied yet will be dropped", popup.message_text)
            with capture_events() as events:
                popup.choose("leave")
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIsNone(review.marker)
            self.assertIn(("svb.recovery_done", "leave"), [(e["event"], e["data"].get("choice")) for e in events])
        self.assertEqual(self.tree_bytes(), written)
        self.assertIsNone(undo.pending_recovery(self.tool_root))


class KeptPendingTest(RunTestBase):
    """A run refused before it wrote anything keeps the staged edits and ticks, and the review still shows them."""

    async def test_an_apply_refused_before_writing_keeps_the_staged_edits(self):
        before = self.tree_bytes()
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            await self.search_friz(review, pilot)
            stage_sv_edit(review)
            ticked, staged = set(review.ticked), review.staging.count
            refusal = ApplyError("ElvUI.lua is open in another program. Nothing was changed.")
            with patch("wowtools.tools.sv_browser.editor.apply_flavor", side_effect=refusal):
                await self.press(app, pilot, "w")
                self.assertIsInstance(app.screen, ConfirmScreen)
                app.screen.dismiss(True)
                await settle(app, pilot)
            result = app.screen
            self.assertIsInstance(result, SvResultScreen)
            self.assertIn("back", {b.id for b in result.query(Button)})
            await self.press(app, pilot, "escape")
            self.assertIs(app.screen, review)
            self.assertEqual((review.ticked, review.staging.count), (ticked, staged))
            self.assertFalse(review._stale)
            self.assertFalse(review.query_one("#btn-apply", Button).disabled)
        self.assertEqual(self.tree_bytes(), before)

    async def test_an_undo_refused_before_it_starts_keeps_the_staged_edits(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.applied_review(app, pilot)
            before = self.tree_bytes()
            stage_sv_edit(review)
            pending = review.query_one("#pending").render().plain
            self.assertIn("Staged: 1 edit", pending)
            with patch("wowtools.tools.sv_browser.review_screen.undo_run",
                       side_effect=undo.UndoError("ElvUI.lua is locked. Nothing was changed.")):
                await self.press(app, pilot, "z")
                self.assertIsInstance(app.screen, ConfirmScreen)
                app.screen.dismiss(True)
                await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.staging.count, 1)  # nothing was changed: the work is kept
            self.assertEqual(review.query_one("#pending").render().plain, pending)
            self.assertFalse(review.query_one("#btn-apply", Button).disabled)
        self.assertEqual(self.tree_bytes(), before)


class RecoveryPlacesTest(RunTestBase):
    async def test_a_recovery_found_under_help_is_offered_when_the_review_is_back(self):
        before = self.tree_bytes()
        crash_retail(self.root)
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_to_recovery(app, pilot)
            await self.press(app, pilot, "escape")
            review = app.screen
            self.assertIsInstance(review, SvReviewScreen)
            await self.press(app, pilot, "h")
            help_screen = app.screen
            self.assertIsInstance(help_screen, HelpScreen)
            review._scanning = True  # a scan that ends while the help is shown
            review._scanned(review.scan, review.undoable, review.marker, review.marker_root)
            await settle(app, pilot)
            self.assertIs(app.screen, help_screen)  # not offered over the help: Put back would do nothing there
            await self.press(app, pilot, "escape")
            popup = app.screen
            self.assertIsInstance(popup, UnfinishedRunScreen)
            popup.choose("put_back")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertIsNone(review.marker)
        self.assertEqual(self.tree_bytes(), before)

    async def test_the_marker_is_settled_in_the_folder_it_was_found_in(self):
        crash_retail(self.root)
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_to_recovery(app, pilot)
            await self.press(app, pilot, "escape")
            review = app.screen
            elsewhere = self.root.parent / "other-backups"
            elsewhere.mkdir()
            save_settings(review.tool_cfg, SvBrowserSettings(backup_dir=elsewhere))  # changed with s since
            review.on_screen_resume()
            stage_sv_edit(review)
            await self.press(app, pilot, "w")
            popup = app.screen
            self.assertIsInstance(popup, UnfinishedRunScreen)
            popup.choose("leave")
            await settle(app, pilot)
            self.assertIsNone(review.marker)
        self.assertIsNone(undo.pending_recovery(self.tool_root))  # the marker that was found is gone
