"""Interface Backup inside the suite app: (first run: settings) → flavor (or All flavors) → review → back up or
restore."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from wowtools.core.config import Config
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.paths import to_native, to_stored
from wowtools.tools.interface_backup.catalog import BackupInfo, list_backups
from wowtools.tools.interface_backup.report import picker_note
from wowtools.tools.interface_backup.review_screen import BackupReviewScreen
from wowtools.tools.interface_backup.settings import (SECTION, BackupSettings, load_settings, resolve_backup_root,
                                                      save_settings, validate_backup_dir)
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import settings_css
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.tool_flow import ToolFlow
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, FormScroll, NavHint, action_button

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp

COUNTING = "checking…"


class BackupSettingsScreen(Screen[bool]):
    DEFAULT_CSS = settings_css("BackupSettingsScreen") + """
    BackupSettingsScreen #destination { color: $text-muted; height: auto; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"), *NAV_BINDINGS]

    def __init__(self, tool_cfg: Config, install: WowInstall | None, *, source: str) -> None:
        super().__init__()
        self.tool_cfg = tool_cfg
        self.install = install
        self.source = source
        self.settings = load_settings(tool_cfg)
        self.error_text = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with FormScroll(id="settings", can_focus=False):
            yield Static("Interface Backup settings", classes="title")
            yield Label("Backup folder. Zips go to <backup folder>\\interface-backup\\backup-<flavor>-<date>.zip. "
                        "Leave it empty to use <WoW folder>\\wow-tools.")
            yield Input(to_stored(self.settings.backup_dir) if self.settings.backup_dir else "",
                        placeholder="Empty = <WoW folder>\\wow-tools", id="backup_dir")
            yield Static("", id="destination")
            yield Label("Backups to keep per flavor (0 = never delete old backups)")
            yield Input(str(self.settings.keep_backups), type="integer", id="keep_backups")
            yield Label("Restore journals to keep (each names its safety backup; Undo uses the newest)")
            yield Input(str(self.settings.keep_journals), type="integer", id="keep_journals")
            yield Static("", id="settings-error")
            with ButtonRow(classes="buttons"):
                yield action_button("Save", "confirm", id="save")
                yield action_button("Cancel", "neutral", id="cancel")
            yield NavHint("↑↓/Tab move · ←→ buttons · Enter/Space press · Esc cancel")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Interface Backup settings"
        self.query_one("#backup_dir", Input).focus()
        self._show_destination()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "backup_dir":
            self._show_destination()

    def _show_destination(self) -> None:
        """Where the zips would go with the folder as typed (no disk access: just the path)."""
        raw = self.query_one("#backup_dir", Input).value.strip()
        root = resolve_backup_root(BackupSettings(to_native(raw) if raw else None),
                                   self.install.root if self.install is not None else None)
        self.query_one("#destination", Static).update(
            Text(f"Zips go to: {to_stored(root)}" if root is not None else "Zips go to: (set the WoW folder first)"))

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

    def _int(self, widget_id: str) -> int | None:
        try:
            return int(self.query_one(f"#{widget_id}", Input).value)
        except ValueError:
            return None

    def _save(self) -> None:
        keep, journals = self._int("keep_backups"), self._int("keep_journals")
        if keep is None or keep < 0:
            self._error("Backups to keep must be 0 (never delete) or more.")
            return
        if journals is None or journals < 1:
            self._error("Keep at least 1 journal.")
            return
        raw = self.query_one("#backup_dir", Input).value.strip()
        folder = to_native(raw) if raw else None
        if self.install is not None:
            problem = validate_backup_dir(folder, self.install)
            if problem:
                self._error(problem)
                return
        save_settings(self.tool_cfg, BackupSettings(folder, keep, journals,
                                                    load_settings(self.tool_cfg).last_flavor_choice),
                      source=self.source)
        self.dismiss(True)


class InterfaceBackupFlow(ToolFlow):
    """Interface Backup's workflow. Its settings live in config/interface-backup.cfg; the WoW folder is shared."""

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None,
                 disk_usage: Callable = shutil.disk_usage) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check  # tests inject it; None: built per run for the flavors involved
        self._disk_usage = disk_usage
        self.flavors: list[Flavor] = []
        self.wow_root: Path | None = None  # the WoW folder self.flavors were read from

    def start(self) -> None:
        self.require_install(self._ready)

    def _ready(self, install: WowInstall, first_run: bool) -> None:
        if not self.tool_cfg.exists:  # first time this tool is opened: ask for its settings once
            self.app.push_screen(BackupSettingsScreen(self.tool_cfg, install, source="wizard"),
                                 lambda _: self._pick_flavor())
        else:
            self._pick_flavor()

    def _pick_flavor(self) -> None:
        install = self.install()
        if install is None:
            self.start()
            return
        self.flavors = install.flavors()
        self.wow_root = install.root
        settings = load_settings(self.tool_cfg)
        # Listing the backup folder can be slow (a network drive): the picker opens at once and a worker fills in
        # each flavor's backups.
        picker = FlavorScreen(self.cfg, install, include_all=True, last=settings.last_flavor_choice,
                              flavors=self.flavors, note=lambda f: COUNTING, all_note=COUNTING)
        self.app.push_screen(picker, self._after_flavor)
        root = resolve_backup_root(settings, self.cfg.wow_path)
        picker.run_worker(lambda: self._notes_worker(picker, root), thread=True, group="notes")

    def _notes_worker(self, picker: FlavorScreen, root: Path | None) -> None:
        backups = list_backups(root)  # never raises
        self.app.call_from_thread(self._notes_ready, picker, backups)

    def _notes_ready(self, picker: FlavorScreen, backups: list[BackupInfo]) -> None:
        if picker not in self.app.screen_stack:
            return  # a flavor was already chosen (or Esc pressed) before the list was ready
        # A picker only covered (settings opened with s) still gets its notes: it shows them when it is back.
        by_flavor = {f.short_name: [b for b in backups if b.flavor_short == f.short_name] for f in self.flavors}
        mine = [b for flavor_backups in by_flavor.values() for b in flavor_backups]
        mine.sort(key=lambda b: (b.stamp, b.n), reverse=True)
        picker.set_notes(lambda f: picker_note(by_flavor.get(f.short_name, [])), picker_note(mine))

    def _after_flavor(self, choice: Flavor | str | None) -> None:
        if choice is None:
            self.close()
            return
        if self.cfg.wow_path != self.wow_root:  # s changed the WoW folder while the picker was open
            self.app.notify("The WoW folder changed: pick the flavor again.", severity="warning")
            self._pick_flavor()
            return
        if choice == ALL_FLAVORS:
            chosen, label, stored = list(self.flavors), "All flavors", ""
        else:
            assert isinstance(choice, Flavor)
            chosen, label, stored = [choice], choice.display_name, choice.folder
        if self.tool_cfg.get(SECTION, "last_flavor_choice", "") != stored:
            self.tool_cfg.set(SECTION, "last_flavor_choice", stored)
            self.tool_cfg.save_if_exists()
        self.app.push_screen(BackupReviewScreen(self.cfg, self.tool_cfg, chosen, label, wow_check=self._wow_check,
                                                 disk_usage=self._disk_usage, wow_root=self.wow_root),
                             self._after_review)

    def _after_review(self, choice: str | None) -> None:
        if choice == "flavors":
            self._pick_flavor()
        elif choice == "tools":
            self.close()
        else:
            self.app.exit()

    def open_settings(self) -> None:
        """`s`: the shared WoW folder first, then this tool's own settings."""
        if isinstance(self.app.screen, BackupSettingsScreen):
            return
        self.app.open_general_settings(
            lambda _: self.app.push_screen(BackupSettingsScreen(self.tool_cfg, self.install(), source="settings"),
                                           self._settings_done))

    def _settings_done(self, saved: bool | None) -> None:
        if self.wow_root is not None and self.cfg.wow_path != self.wow_root:
            return  # a new WoW folder: the review (or the picker, on a choice) goes back to the flavor picker
        if saved:
            self.app.notify("Settings saved. Press r on the review screen to rescan with them.")


FLOW = InterfaceBackupFlow
