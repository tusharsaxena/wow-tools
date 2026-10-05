"""The Screenshot Organizer inside the suite app: (first run: settings) → flavor (or All flavors) → review →
confirm → result."""
from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Label

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.paths import to_stored
from wowtools.tools.screenshot_organizer.planner import count_waiting
from wowtools.tools.screenshot_organizer.review_screen import ShotReviewScreen
from wowtools.tools.screenshot_organizer.settings import (SECTION, ShotSettings, load_settings, save_settings,
                                                          source_dir, validate_dest)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import Ka0sCheckbox

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class ScreenshotSettingsScreen(ToolSettingsScreen):
    FORM_TITLE = "Screenshot Organizer settings"
    FIRST_FIELD = "dest_dir"
    TICKS = True

    def load(self, tool_cfg: Config) -> ShotSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        yield Label("Destination folder (the archive root). Screenshots are filed into "
                    "<destination>\\<flavor folder>\\YYYY\\MM\\DD, e.g. ...\\_retail_\\2019\\07\\31. "
                    "Leave it empty to organise each flavor's Screenshots folder in place.")
        yield self.folder_input(self.settings.dest_dir, id="dest_dir",
                                placeholder="Empty = in place: <flavor>\\Screenshots\\YYYY\\MM\\DD")
        yield Ka0sCheckbox("Copy instead of move (the originals stay in Screenshots)",
                           self.settings.copy_mode, id="sw_copy", compact=True)

    def save(self) -> bool:
        dest = self.folder_value("dest_dir")
        if self.wow_install is not None:
            problem = validate_dest(dest, self.wow_install)
            if problem:
                self._error(problem)
                return False
        save_settings(self.tool_cfg, ShotSettings(dest, self.query_one("#sw_copy", Ka0sCheckbox).value,
                                                  load_settings(self.tool_cfg).last_flavor_choice),
                      source=self.source)
        return True


COUNTING = "counting…"


def waiting_text(count: int | None) -> str:
    """The flavor picker's third column: how many screenshots are waiting to be filed."""
    if count is None:
        return "no Screenshots folder"
    if count == 0:
        return "nothing to file"
    return f"{count} screenshot{'' if count == 1 else 's'} to file"


class ScreenshotsFlow(ToolFlow):
    """The organizer's own workflow. Its settings live in config/screenshot-organizer.cfg; the WoW folder and the last
    single flavor are shared suite settings."""

    SECTION = SECTION
    SETTINGS_SCREEN = ScreenshotSettingsScreen

    def __init__(self, app: WowToolsApp, tool_cfg: Config) -> None:
        super().__init__(app, tool_cfg)
        self.flavors: list[Flavor] = []

    def _pick_flavor(self) -> None:
        install = self.install()
        if install is None:
            self.start()
            return
        self.flavors = install.flavors()
        if not any(source_dir(f).is_dir() for f in self.flavors):  # a few stats: cheap enough for the UI thread
            # Decided before the picker opens: pushing it and dismissing it at once races the picker's Header.
            self._no_screenshots(install)
            return
        settings = load_settings(self.tool_cfg)
        # Counting lists every flavor's Screenshots folder: the picker opens at once and a worker fills the counts
        # in (F-005).
        picker = FlavorScreen(self.cfg, install, include_all=True, last=settings.last_flavor_choice,
                              flavors=self.flavors, note=lambda f: COUNTING, all_note=COUNTING)
        self.app.push_screen(picker, self._after_flavor)
        flavors, parallelism = list(self.flavors), self.cfg.parallelism
        self.fill_notes(picker, lambda: count_waiting(flavors, settings.dest_dir, copy=settings.copy_mode,
                                                      parallelism=parallelism),
                        lambda counts: self._counts_ready(picker, install, counts), group="counts")

    def _counts_ready(self, picker: FlavorScreen, install: WowInstall, counts: dict[str, int | None]) -> None:
        if all(count is None for count in counts.values()) and self.app.screen is picker:
            # every Screenshots folder is unreadable
            self.app.notify(f"No Screenshots folders found in {to_stored(install.root)}.", severity="warning")
            picker.dismiss(None)  # back to the tool menu
            return
        picker.set_notes(lambda f: waiting_text(counts.get(f.folder)),
                         waiting_text(sum(c or 0 for c in counts.values())))

    def _no_screenshots(self, install: WowInstall) -> None:
        self.app.notify(f"No Screenshots folders found in {to_stored(install.root)}.", severity="warning")
        self.close()

    def _after_flavor(self, choice: Flavor | str | None) -> None:
        if choice is None:
            self.close()
            return
        self.remember_flavor(choice)
        if choice == ALL_FLAVORS:
            chosen, label = list(self.flavors), "All flavors"
        else:
            assert isinstance(choice, Flavor)
            chosen, label = [choice], choice.display_name
        self.app.push_screen(ShotReviewScreen(self.cfg, self.tool_cfg, chosen, label), self._after_review)


FLOW = ScreenshotsFlow
