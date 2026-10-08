"""L9 (STD-7.24): one toast anchor and one stack on every screen. Every toast starts from the same anchor: bottom
right, just above the screen's bars (the bottom bar, the bottom line, an action bar under a tree and, on the Ace3
review, the guidance line over it). A popup takes the anchor of the screen under it, raised above its own controls
(buttons, fields, boxes, lists) that reach the toasts' column, so a toast never covers what is pressed or typed
into. Several toasts stack upward without overlapping, and the Ace3 action tip is the stack's lowest box, so a tip
and a toast never overlap (user feedback 2026-10-08: the tip and a "Not done" toast overlapped at two heights).

One shared helper places them (`ui/toasts.py`, installed by `Ka0sApp`); no screen places its own. The walk raises
three toasts on every screen of every tool (the menu, changelog, help and settings, the pickers, the risk popup,
the review, its warnings, the Ace3 blacklist, the run confirm, the result and Interface Backup's restore screen),
plus the action tip on the Ace3 review, at 120x30 and 160x45; `PopupStackTest` does the same on every other popup
(progress, prompts, the Ace3 and Saved Variables Browser popups, notes, recovery, lock, update, a popup over a
popup). Both measure the boxes against bars and controls found here, not by the helper."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from textual.geometry import Region
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Tree
from textual.widgets._toast import Toast

from tests.fixtures import (BASE, LARGE, TuiTestCase, accept_disclaimer, build_ace_tree, build_interface_tree,
                            build_screenshot_tree, build_wow_tree, make_config, settle, stage_sv_edit)
from wowtools.core.install import Flavor
from wowtools.core.lock import LockInfo
from wowtools.core.updater import ReleaseInfo
from wowtools.tools import TOOLS
from wowtools.tools.ace3_profile_manager.editor import Marker as AceMarker
from wowtools.tools.ace3_profile_manager.popups import ActionsScreen, NameScreen, TargetScreen
from wowtools.tools.ace3_profile_manager.review_screen import ProfileProgressScreen, ProfileRecoveryScreen
from wowtools.tools.interface_backup.review_screen import BackupProgressScreen
from wowtools.tools.screenshot_organizer.review_screen import ShotProgressScreen
from wowtools.tools.sv_browser.popups import EditValueScreen, RenameKeyScreen, SearchProgressScreen, SearchScreen
from wowtools.tools.sv_browser.review_screen import RunProgressScreen
from wowtools.tools.wtf_cleaner.review_screen import CleanProgressScreen
from wowtools.tools.wtf_cleaner.review_screen import RecoveryScreen as WtfRecoveryScreen
from wowtools.tools.wtf_cleaner.safety import Marker as WtfMarker
from wowtools.ui.base import UpdateProgressScreen, UpdateScreen
from wowtools.ui.dialogs import (ConfirmScreen, DiscardScreen, InfoScreen, ProgressScreen, TextPromptScreen,
                                 UnfinishedRunScreen)
from wowtools.ui.disclaimer import DisclaimerScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.result_screen import ResultBase
from wowtools.ui.suite_app import LockScreen, WowToolsApp
from wowtools.ui.toasts import StackTip
from wowtools.ui.warnings_view import WarningItem, WarningsScreen

# What a toast must never cover, found by type and id here (the helper has its own list).
BARS = "BottomBar, SummaryBar, Footer, ActionBar, #guide"
# What is pressed, typed into or chosen from on a popup: a toast stays clear of these too.
CONTROLS = "Button, Input, TextArea, Checkbox, Switch, Select, RadioSet, OptionList"
ACCOUNT_TOOLS = ("wtf-cleaner", "ace3-profile-manager")
RUN_ACTION = {"wtf-cleaner": "dry_run", "screenshot-organizer": "dry_run", "interface-backup": "back_up",
              "ace3-profile-manager": "dry_run", "sv-browser": "dry_run"}
PREPARE = {"ace3-profile-manager": lambda review: (review.staging.everyone_to_default(list(review.staging.states)),
                                                   review.refresh_view()),
           "sv-browser": stage_sv_edit}


def bars(app) -> list[Region]:
    """The regions of the bars toasts stand on: the shown screen's, or, for a popup without bars of its own, the
    screen's under it (a popup covers the whole screen, so the coordinates are the same)."""
    for screen in reversed(app.screen_stack):
        found = [w.region for w in screen.query(BARS) if w.display and w.region.height]
        if found or not isinstance(screen, ModalScreen):
            return found
    return []


class ToastStackTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        wow = build_wow_tree(tmp / "World of Warcraft")
        self.root = build_ace_tree(build_interface_tree(build_screenshot_tree(wow)))
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "interface-backup": {"wow_check": list}, "ace3-profile-manager": {"wow_check": list},
                   "sv-browser": {"wow_check": list}}
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options=options)

    async def assert_stack(self, app, pilot, where: str, *, tip: bool = False) -> None:
        """Three toasts (and the tip, when asked) on the shown screen: one right edge, the same on every screen of
        the size; the lowest box just above the bars; no two boxes overlap; none covers a bar."""
        app.clear_notifications()
        await settle(app, pilot)
        for n in range(3):
            app.notify(f"Toast {n + 1} of 3 on {where}: a line long enough to need its room.", title="Stack",
                       timeout=600)
        await settle(app, pilot)
        await pilot.pause()
        screen = app.screen
        boxes = [t.region for t in screen.query(Toast)]
        self.assertEqual(len(boxes), 3, where)
        if tip:
            tips = [t for t in screen.query(StackTip) if t.region.height]
            self.assertEqual(len(tips), 1, f"{where}: the action tip is shown")
            boxes.append(tips[0].region)
        self.assertTrue(all(b.height for b in boxes), (where, boxes))
        rights = {b.right for b in boxes}
        self.assertEqual(len(rights), 1, (where, boxes))
        self.rights.add(rights.pop())
        self.assertEqual(len(self.rights), 1, f"{where}: one right edge on every screen ({self.rights})")
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a.overlaps(b), f"{where}: {a} overlaps {b}")
        found = bars(app)
        self.assertTrue(found, f"{where}: a screen with bars")
        for box in boxes:
            for bar in found:
                self.assertFalse(box.overlaps(bar), f"{where}: {box} covers the bar at {bar}")
        floor = min(b.y for b in found)
        if isinstance(screen, ModalScreen):  # a popup: its own controls, where the toasts' column reaches them
            left = min(b.x for b in boxes)
            controls = [w.region for w in screen.query(CONTROLS) if w.display and w.region.height]
            for box in boxes:
                for control in controls:
                    self.assertFalse(box.overlaps(control), f"{where}: {box} covers the control at {control}")
            floor = min([floor, *(c.y for c in controls if c.right > left)])
        lowest = max(boxes, key=lambda b: b.bottom)
        self.assertEqual(lowest.bottom, floor, f"{where}: the stack starts just above the bars and controls")
        app.clear_notifications()
        await settle(app, pilot)

    async def open_flavors(self, app, pilot, tool):
        await pilot.pause()
        app.open_tool(tool)
        await settle(app, pilot)
        if not isinstance(app.screen, FlavorScreen):
            await self.assert_stack(app, pilot, f"{tool} first settings")
            app.screen._save()
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        return app.screen

    async def test_one_anchor_and_stack_on_the_menu_changelog_help_and_settings(self):
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                self.rights: set[int] = set()
                app = self.make_app()
                async with app.run_test(size=size, notifications=True) as pilot:
                    await settle(app, pilot)
                    await self.assert_stack(app, pilot, "menu")
                    await pilot.press("c")
                    await settle(app, pilot)
                    await self.assert_stack(app, pilot, "changelog")
                    await pilot.press("escape")
                    await settle(app, pilot)
                    await pilot.press("h")
                    await settle(app, pilot)
                    await self.assert_stack(app, pilot, "help")
                    await pilot.press("escape")
                    await settle(app, pilot)
                    await pilot.press("s")
                    await settle(app, pilot)
                    self.assertIsInstance(app.focused, Input)
                    await self.assert_stack(app, pilot, "setup")

    async def test_one_anchor_and_stack_on_every_screen_of_every_tool(self):
        await self.walk_every_tool(BASE)

    async def test_one_anchor_and_stack_on_every_screen_of_every_tool_large(self):
        await self.walk_every_tool(LARGE)

    async def walk_every_tool(self, size):
        for name in TOOLS:
            with self.subTest(tool=name, size=size):
                self.rights = set()
                app = self.make_app()
                async with app.run_test(size=size, notifications=True) as pilot:
                    picker = await self.open_flavors(app, pilot, name)
                    await self.assert_stack(app, pilot, f"{name} flavor picker")
                    if name in ACCOUNT_TOOLS:
                        picker.dismiss(next(f for f in picker.flavors if f.folder == "_retail_"))
                        await settle(app, pilot)
                        await self.assert_stack(app, pilot, f"{name} account picker")
                        await pilot.press("escape")
                        await settle(app, pilot)
                        picker = app.screen
                    picker.dismiss(ALL_FLAVORS)
                    await settle(app, pilot)
                    if isinstance(app.screen, DisclaimerScreen):
                        await self.assert_stack(app, pilot, f"{name} risk popup")
                        await accept_disclaimer(app, pilot)
                    review = app.screen
                    await self.assert_stack(app, pilot, f"{name} review")
                    if name == "ace3-profile-manager":
                        tree = review.query_one("#profiles", Tree)
                        tree.root.expand_all()
                        await settle(app, pilot)
                        tree.move_cursor(tree.get_node_at_line(2))
                        review.query_one("#act-delete", Button).focus()
                        await settle(app, pilot)
                        await self.assert_stack(app, pilot, f"{name} review with the action tip", tip=True)
                        tree.focus()
                        await settle(app, pilot)
                    await pilot.press("h")
                    await settle(app, pilot)
                    await self.assert_stack(app, pilot, f"{name} help")
                    await pilot.press("escape")
                    await settle(app, pilot)
                    app.push_screen(app.flow.settings_screen("settings"))
                    await settle(app, pilot)
                    await self.assert_stack(app, pilot, f"{name} settings")
                    app.screen.dismiss(False)
                    await settle(app, pilot)
                    app.push_screen(WarningsScreen("Scan warnings", [WarningItem("Interface", "denied")]))
                    await settle(app, pilot)
                    await self.assert_stack(app, pilot, f"{name} warnings")
                    app.pop_screen()
                    await settle(app, pilot)
                    if name == "ace3-profile-manager":
                        review.action_edit_blacklist()
                        await settle(app, pilot)
                        await self.assert_stack(app, pilot, f"{name} blacklist")
                        app.screen.dismiss(None)
                        await settle(app, pilot)
                    self.assertIs(app.screen, review)
                    PREPARE.get(name, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[name]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    await self.assert_stack(app, pilot, f"{name} confirm")
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ResultBase)
                    await self.assert_stack(app, pilot, f"{name} result")
                    if name == "interface-backup":  # Restore (e) on the result, then e on the backup just made
                        await pilot.press("e")
                        await settle(app, pilot)
                        await pilot.press("e")
                        await settle(app, pilot)
                        await self.assert_stack(app, pilot, f"{name} restore")


class PopupStackTest(ToastStackTest):
    """Every popup the review walk does not reach, over the menu (a popup over a popup: the discard question over
    a prompt), at 120x30 and 160x45: toasts start above the popup's controls and never cover one."""

    def popups(self):
        holder = LockInfo(12345, "other-pc", "2026-10-03T10:00:00", "windows", "abc")
        wtf_marker = WtfMarker(self.root / "backup.zip", "_retail_", self.root / "_retail_", "2026-01-01T00:00:00", 1,
                               "0.1.0", ["WTF/x.lua"])
        ace_marker = AceMarker("_retail_", self.root / "_retail_", self.root / "edited.zip", {"WTF/x.lua": "0"},
                               "2026-10-04T12:00:00+00:00", 1, "0.1.0", {"WTF/x.lua": "1"})
        flavors = [Flavor(f"_{name}_", Path(name)) for name in ("retail", "classic", "classic_era")]
        return (lambda: ProgressScreen("Working", first_stage="check"),
                lambda: CleanProgressScreen(False, flavors=flavors), ShotProgressScreen,
                lambda: BackupProgressScreen("Backing up", "backup", [f.display_name for f in flavors]),
                lambda: ProfileProgressScreen("Applying", flavors=flavors),
                lambda: RunProgressScreen("Applying", first_stage="check"),
                lambda: SearchProgressScreen("Searching", first_stage="search"),
                lambda: TextPromptScreen("Title", "Body"), lambda: NameScreen("Title", "Body"),
                lambda: RenameKeyScreen("ElvDB › x", "x", lambda key: None),
                lambda: TargetScreen("Title", "Body", ["Default", "Healer"]), ActionsScreen,
                lambda: EditValueScreen("ElvDB › x", "1"), lambda: SearchScreen(accounts=["ACCOUNT"]),
                lambda: InfoScreen("Notes", {"KickCD": ["Kaelys - Realm1"]}, "Body"),
                lambda: ConfirmScreen("Title", "Body"), lambda: UnfinishedRunScreen("An earlier run"),
                lambda: WtfRecoveryScreen(wtf_marker, self.root), lambda: ProfileRecoveryScreen(ace_marker),
                lambda: LockScreen(holder, self.root / "wow-tools.lock"),
                lambda: UpdateScreen(ReleaseInfo.from_version("9.9.9")), lambda: UpdateProgressScreen("9.9.9"))

    async def test_toasts_stay_clear_of_every_popups_controls(self):
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                self.rights = set()
                app = self.make_app()
                async with app.run_test(size=size, notifications=True) as pilot:
                    await settle(app, pilot)
                    await self.assert_stack(app, pilot, "menu")
                    for make in self.popups():
                        popup = make()
                        app.push_screen(popup)
                        await settle(app, pilot)
                        await self.assert_stack(app, pilot, type(popup).__name__)
                        app.pop_screen()
                        await settle(app, pilot)
                    app.push_screen(NameScreen("Title", "Body"))
                    await settle(app, pilot)
                    app.push_screen(DiscardScreen("Discard?", "Body"))
                    await settle(app, pilot)
                    await self.assert_stack(app, pilot, "DiscardScreen over NameScreen")

    test_one_anchor_and_stack_on_the_menu_changelog_help_and_settings = None
    test_one_anchor_and_stack_on_every_screen_of_every_tool = None
    test_one_anchor_and_stack_on_every_screen_of_every_tool_large = None


class OneHelperTest(unittest.TestCase):
    def test_only_the_shared_helper_places_toasts(self):
        """No screen places toasts or a tip of its own: Textual's toast rack is named in `ui/toasts.py` only, and
        no module but it sets a rack's margin (the per-screen `lift_toasts` / `place_toasts` / `_place_overlays`
        are gone)."""
        package = Path(__file__).resolve().parent.parent / "wowtools"
        own = package / "ui" / "toasts.py"
        offenders = [str(path.relative_to(package)) for path in sorted(package.rglob("*.py")) if path != own
                     and any(name in path.read_text(encoding="utf-8")
                             for name in ("textual-toastrack", "ToastRack", "lift_toasts", "place_toasts",
                                          "_place_overlays"))]
        self.assertEqual(offenders, [])
