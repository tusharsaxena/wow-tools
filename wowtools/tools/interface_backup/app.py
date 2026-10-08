"""Interface Backup inside the suite app: (first run: settings) → flavor (or All flavors) → review → back up or
restore."""
from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Input, Label, Static

from wowtools.core.config import Config
from wowtools.core.install import Flavor, validate_backup_dir
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.catalog import BackupInfo, list_backups, zips_dir
from wowtools.tools.interface_backup.report import picker_note
from wowtools.tools.interface_backup.review_screen import BackupReviewScreen
from wowtools.tools.interface_backup.settings import (SECTION, BackupSettings, load_settings, resolve_backup_root,
                                                      save_settings)
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import ToolSettingsScreen
from wowtools.ui.tool_flow import ToolFlow

if TYPE_CHECKING:
    from wowtools.ui.suite_app import WowToolsApp

COUNTING = "checking…"


class BackupSettingsScreen(ToolSettingsScreen):
    DEFAULT_CSS = """
    BackupSettingsScreen #destination { color: $text-muted; height: auto; }
    """
    FORM_TITLE = "Interface Backup settings"
    FIRST_FIELD = "backup_dir"

    def load(self, tool_cfg: Config) -> BackupSettings:
        return load_settings(tool_cfg)

    def fields(self) -> Iterable[Widget]:
        yield Label("Backup folder. Zips go to "
                    "<backup folder>\\interface-backup\\backup\\backup-<flavor>-<date>.zip. "
                    "Leave it empty to use <WoW folder>\\wow-tools.")
        yield self.folder_input(self.settings.backup_dir, id="backup_dir",
                                placeholder="Empty = <WoW folder>\\wow-tools")
        yield Static("", id="destination")

    def on_mount(self) -> None:  # ToolSettingsScreen.on_mount runs too (Textual calls both)
        self._show_destination()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "backup_dir":
            self._show_destination()

    def _show_destination(self) -> None:
        """Where the zips would go with the folder as typed (no disk access: just the path)."""
        install = self.wow_install
        root = resolve_backup_root(BackupSettings(self.folder_value("backup_dir")),
                                   install.root if install is not None else None)
        self.query_one("#destination", Static).update(
            Text(f"Zips go to: {to_stored(zips_dir(root))}" if root is not None
                 else "Zips go to: (set the WoW folder first)"))

    def save(self) -> bool:
        folder = self.folder_value("backup_dir")
        if self.wow_install is not None:
            problem = validate_backup_dir(folder, self.wow_install)
            if problem:
                self._error(problem)
                return False
        save_settings(self.tool_cfg, BackupSettings(folder, load_settings(self.tool_cfg).last_flavor_choice),
                      source=self.source)
        return True


class InterfaceBackupFlow(ToolFlow):
    """Interface Backup's workflow. Its settings live in config/interface-backup.cfg; the WoW folder is shared."""

    SECTION = SECTION
    SETTINGS_SCREEN = BackupSettingsScreen

    def __init__(self, app: WowToolsApp, tool_cfg: Config, *,
                 wow_check: Callable[[], list[str] | None] | None = None,
                 disk_usage: Callable = shutil.disk_usage) -> None:
        super().__init__(app, tool_cfg)
        self._wow_check = wow_check  # tests inject it; None: built per run for the flavors involved
        self._disk_usage = disk_usage
        self.flavors: list[Flavor] = []
        self.wow_root: Path | None = None  # the WoW folder self.flavors were read from

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
        self.fill_notes(picker, lambda: list_backups(root), lambda backups: self._notes_ready(picker, backups))

    def _notes_ready(self, picker: FlavorScreen, backups: list[BackupInfo]) -> None:
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
        self.remember_flavor(choice)
        if choice == ALL_FLAVORS:
            chosen, label = list(self.flavors), "All flavors"
        else:
            assert isinstance(choice, Flavor)
            chosen, label = [choice], choice.display_name
        self.app.push_screen(BackupReviewScreen(self.cfg, self.tool_cfg, chosen, label, wow_check=self._wow_check,
                                                 disk_usage=self._disk_usage, wow_root=self.wow_root),
                             self._after_review)

    def _settings_done(self, saved: bool | None) -> None:
        if self.wow_root is not None and self.cfg.wow_path != self.wow_root:
            return  # a new WoW folder: the review (or the picker, on a choice) goes back to the flavor picker
        super()._settings_done(saved)


FLOW = InterfaceBackupFlow
