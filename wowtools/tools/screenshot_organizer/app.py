"""The Screenshot Organizer inside the suite app: (first run: settings) → flavor (or All flavors) → review →
confirm → result."""
from __future__ import annotations

from typing import TYPE_CHECKING, Union

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.paths import to_native, to_stored
from wowtools.tools.screenshot_organizer.planner import waiting_count
from wowtools.tools.screenshot_organizer.review_screen import ShotReviewScreen
from wowtools.tools.screenshot_organizer.settings import (SECTION, ShotSettings, load_settings, save_settings,
                                                          validate_dest)
from wowtools.ui.branding import BrandBar
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp


class ScreenshotSettingsScreen(Screen[bool]):
    DEFAULT_CSS = """
    ScreenshotSettingsScreen #settings { padding: 0 2; }
    ScreenshotSettingsScreen .title { color: $accent; text-style: bold; margin: 1 0; }
    ScreenshotSettingsScreen Ka0sCheckbox { margin: 1 0; }
    ScreenshotSettingsScreen #settings-error { color: $error; height: auto; }
    ScreenshotSettingsScreen .buttons { height: auto; margin-top: 1; }
    ScreenshotSettingsScreen Button { margin-right: 2; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, tool_cfg: Config, install: WowInstall | None, *, source: str) -> None:
        super().__init__()
        self.tool_cfg = tool_cfg
        self.install = install
        self.source = source
        self.settings = load_settings(tool_cfg)
        self.error_text = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="settings", can_focus=False):
            yield Static("Screenshot Organizer settings", classes="title")
            yield Label("Destination folder (the archive root). Screenshots are filed into "
                        "<destination>\\<flavor folder>\\YYYY\\MM\\DD, e.g. ...\\_retail_\\2019\\07\\31. "
                        "Leave it empty to organise each flavor's Screenshots folder in place.")
            yield Input(to_stored(self.settings.dest_dir) if self.settings.dest_dir else "",
                        placeholder="Empty = in place: <flavor>\\Screenshots\\YYYY\\MM\\DD", id="dest_dir")
            yield Label("Run journals to keep (each real run writes one; Undo uses the newest)")
            yield Input(str(self.settings.keep_journals), type="integer", id="keep_journals")
            yield Ka0sCheckbox("Copy instead of move (the screenshots stay in the Screenshots folder too)",
                               self.settings.copy_mode, id="sw_copy")
            yield Static("", id="settings-error")
            with ButtonRow(classes="buttons"):
                yield action_button("Save", "confirm", id="save")
                yield action_button("Cancel", "neutral", id="cancel")
            yield NavHint("↑↓/Tab move · ←→ buttons · Space/Enter tick · Enter/Space press · Esc cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Screenshot Organizer settings"
        self.query_one("#dest_dir", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _error(self, text: str) -> None:
        self.error_text = text
        self.query_one("#settings-error", Static).update(Text(text))

    def _save(self) -> None:
        try:
            keep = int(self.query_one("#keep_journals", Input).value)
        except ValueError:
            keep = 0
        if keep < 1:
            self._error("Keep at least 1 journal.")
            return
        raw = self.query_one("#dest_dir", Input).value.strip()
        dest = to_native(raw) if raw else None
        if self.install is not None:
            problem = validate_dest(dest, self.install)
            if problem:
                self._error(problem)
                return
        save_settings(self.tool_cfg, ShotSettings(dest, self.query_one("#sw_copy", Ka0sCheckbox).value,
                                                  load_settings(self.tool_cfg).last_flavor_choice, keep),
                      source=self.source)
        self.dismiss(True)


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

    def __init__(self, app: WowToolsApp, tool_cfg: Config) -> None:
        super().__init__(app, tool_cfg)
        self.flavors: list[Flavor] = []

    def start(self) -> None:
        self.require_install(self._ready)

    def _ready(self, install: WowInstall, first_run: bool) -> None:
        if not self.tool_cfg.exists:  # first time this tool is opened: ask for its settings once
            self.app.push_screen(ScreenshotSettingsScreen(self.tool_cfg, install, source="wizard"),
                                 lambda _: self._pick_flavor())
        else:
            self._pick_flavor()

    def _pick_flavor(self) -> None:
        install = self.install()
        if install is None:
            self.start()
            return
        self.flavors = install.flavors()
        settings = load_settings(self.tool_cfg)
        # Counting lists every flavor's Screenshots folder: the picker opens at once and a worker fills the counts
        # in (F-005).
        picker = FlavorScreen(self.cfg, install, include_all=True, last=settings.last_flavor_choice,
                              flavors=self.flavors, note=lambda f: COUNTING, all_note=COUNTING)
        self.app.push_screen(picker, self._after_flavor)
        flavors = list(self.flavors)
        picker.run_worker(lambda: self._count_worker(picker, install, flavors), thread=True, group="counts")

    def _count_worker(self, picker: FlavorScreen, install: WowInstall, flavors: list[Flavor]) -> None:
        counts = {f.folder: waiting_count(f) for f in flavors}  # never raises: an unreadable folder is None
        self.app.call_from_thread(self._counts_ready, picker, install, counts)

    def _counts_ready(self, picker: FlavorScreen, install: WowInstall, counts: dict[str, int | None]) -> None:
        if self.app.screen is not picker:
            return  # a flavor was already chosen (or Esc pressed) before the counts were ready
        if all(count is None for count in counts.values()):
            self.app.notify(f"No Screenshots folders found in {to_stored(install.root)}.", severity="warning")
            picker.dismiss(None)  # back to the tool menu
            return
        picker.set_notes(lambda f: waiting_text(counts.get(f.folder)),
                         waiting_text(sum(c or 0 for c in counts.values())))

    def _after_flavor(self, choice: Union[Flavor, str, None]) -> None:
        if choice is None:
            self.close()
            return
        if choice == ALL_FLAVORS:
            chosen, label, stored = list(self.flavors), "All flavors", ""
        else:
            assert isinstance(choice, Flavor)
            chosen, label, stored = [choice], choice.display_name, choice.folder
        if self.tool_cfg.get(SECTION, "last_flavor_choice", "") != stored:
            self.tool_cfg.set(SECTION, "last_flavor_choice", stored)
            self.tool_cfg.save_if_exists()
        self.app.push_screen(ShotReviewScreen(self.cfg, self.tool_cfg, chosen, label), self._after_review)

    def _after_review(self, choice: str | None) -> None:
        if choice == "flavors":
            self._pick_flavor()
        elif choice == "tools":
            self.close()
        else:
            self.app.exit()

    def open_settings(self) -> None:
        """`s`: the shared WoW folder first, then this tool's own settings."""
        if isinstance(self.app.screen, ScreenshotSettingsScreen):
            return
        self.app.open_general_settings(
            lambda _: self.app.push_screen(ScreenshotSettingsScreen(self.tool_cfg, self.install(), source="settings"),
                                           self._settings_done))

    def _settings_done(self, saved: bool | None) -> None:
        if saved:
            self.app.notify("Settings saved. Press r on the review screen to rescan with them.")


FLOW = ScreenshotsFlow
