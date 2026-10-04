"""Choose what to restore from a backup and see what would be lost; the result screen of a restore or undo."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Static

from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.catalog import BackupInfo
from wowtools.tools.interface_backup.report import (RESTORE_RESULT_COLUMNS, friendly_created, human_size,
                                                    ordered_parts, plural, restore_result_rows, restore_warnings)
from wowtools.tools.interface_backup.restore import (BackupContents, RestoreError, RestorePlan, RestoreResult,
                                                     case_key, open_backup, plan_restore)
from wowtools.tools.interface_backup.scanner import PARTS, FlavorScan, scan_flavor
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import theme_colour
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button


def _error_text(exc: Exception) -> str:
    return str(exc) if isinstance(exc, RestoreError) else f"{type(exc).__name__}: {exc}"


class RestoreScreen(Screen[RestorePlan | None]):
    """The backup's details, a box per part and what the restore would lose (worked out in a worker each time a
    box changes). Dismisses with the plan to restore, or None."""

    DEFAULT_CSS = """
    RestoreScreen #restore { padding: 1 2; height: 1fr; }
    RestoreScreen .title { color: $accent; text-style: bold; }
    RestoreScreen #backup-info { height: auto; margin-bottom: 1; }
    RestoreScreen #warnings { height: auto; margin-top: 1; }
    RestoreScreen .buttons { height: auto; padding: 0 2; }
    RestoreScreen Button { margin-right: 2; }
    RestoreScreen NavHint { padding: 0 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("o", "restore", "Restore"), Binding("b", "cancel", "Back"),
                                         Binding("escape", "cancel", "Back", show=False), *NAV_BINDINGS]

    def __init__(self, info: BackupInfo, flavor: Flavor, *, disk_usage: Callable = shutil.disk_usage) -> None:
        super().__init__()
        self.info = info
        self.flavor = flavor
        self.disk_usage = disk_usage
        self.contents: BackupContents | None = None
        self.scan: FlavorScan | None = None
        self.plan: RestorePlan | None = None
        self.problem = ""
        self._generation = 0  # bumped per replan: a plan worked out for older boxes is dropped

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="restore"):
            kind = "Safety backup (before a restore)" if self.info.is_safety else "Backup"
            yield Static(Text(f"{self.flavor.display_name}: {kind} from {self.info.when} "
                              f"({human_size(self.info.size)})"), classes="title")
            yield Static(Text(to_stored(self.info.path)), id="backup-info")
            for part in PARTS:
                yield Ka0sCheckbox(part, True, id=f"part-{part}", disabled=True)
            yield Static(Text("Comparing the backup with your folders…"), id="warnings")
        with ButtonRow(classes="buttons"):
            yield action_button("Restore (o)", "confirm", id="btn-restore", disabled=True)
            yield action_button("Back (b)", "neutral", id="btn-back")
        yield NavHint("↑↓/Tab move · Space tick · ←→ buttons · Enter/Space press · o restore · b/Esc back")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Interface Backup · restore"
        info, flavor = self.info, self.flavor
        self.run_worker(lambda: self._load_worker(info, flavor), thread=True, group="restore-load")

    # --- loading the backup and the folders (worker) ---------------------------------------------
    def _load_worker(self, info: BackupInfo, flavor: Flavor) -> None:
        try:
            contents = open_backup(info.path)
            scan = scan_flavor(flavor, with_stats=True)
        except Exception as exc:  # noqa: BLE001 - shown on the screen, never a crash
            if not isinstance(exc, RestoreError):
                log_exception("ibackup.ui", exc)
            self.app.call_from_thread(self._loaded, None, None, f"This backup cannot be restored: {_error_text(exc)}")
            return
        self.app.call_from_thread(self._loaded, contents, scan, "")

    def _loaded(self, contents: BackupContents | None, scan: FlavorScan | None, problem: str) -> None:
        self.contents, self.scan, self.problem = contents, scan, problem
        if not self.is_attached:
            return
        if contents is not None and case_key(contents.flavor_folder) != case_key(self.flavor.folder):
            self.problem = f"This backup belongs to {contents.flavor_folder}, not {self.flavor.folder}."
        if scan is not None and scan.leftovers:
            self.problem = ("Restore is blocked: a folder from an interrupted restore is still there: "
                            + ", ".join(to_stored(p) for p in scan.leftovers)
                            + ". Move or delete it first (see the guide).")
        if contents is not None:
            parts = ", ".join(contents.parts) or "nothing"
            made = friendly_created(contents.created) if contents.created else ""
            self.query_one("#backup-info", Static).update(Text(
                f"{to_stored(self.info.path)}\nHolds: {parts} · "
                f"{plural(sum(len(f) for f in contents.files.values()), 'file')}"
                + (f" · made {made}" if made and made != self.info.when else "")))
        first = None
        for part in PARTS:
            box = self.query_one(f"#part-{part}", Ka0sCheckbox)
            in_backup = contents is not None and part in contents.parts
            linked = scan is not None and scan.parts[part].linked
            available = in_backup and not linked and not self.problem
            box.disabled = not available
            if self.problem:
                box.value = False  # blocked: a ticked box would read as "this will be restored"
            elif not in_backup:
                box.value = False
                box.label = f"{part} (not in this backup)"
            elif linked:
                box.value = False
                box.label = f"{part} (a link to another folder: restore it by hand)"
            if available and first is None:
                first = box
        # Focus starts on something that acts: the first box that can be ticked, else Back.
        (first or self.query_one("#btn-back", Button)).focus()
        self._replan()

    # --- the plan (worker) -----------------------------------------------------------------------
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        if self.contents is None or event.checkbox.disabled:
            return
        part = (event.checkbox.id or "").removeprefix("part-")
        log_event("ui.selection", screen="ibackup_restore", control=part, value=event.value)
        self._replan()

    def _chosen(self) -> tuple[str, ...]:
        boxes = [self.query_one(f"#part-{p}", Ka0sCheckbox) for p in PARTS]
        return tuple(p for p, box in zip(PARTS, boxes) if box.value and not box.disabled)

    def _show(self, text: str, style: str = "") -> None:
        self.query_one("#warnings", Static).update(Text(text, style=style))

    def _replan(self) -> None:
        self._generation += 1
        self.plan = None
        self.query_one("#btn-restore", Button).disabled = True
        if self.problem:
            self._show(self.problem, f"bold {theme_colour(self.app, 'error')}")
            return
        if self.contents is None or self.scan is None:
            return
        parts = self._chosen()
        if not parts:
            self._show("Tick Interface, WTF or both.")
            return
        self._show("Comparing the backup with your folders…")
        generation, contents, scan, disk_usage = self._generation, self.contents, self.scan, self.disk_usage
        self.run_worker(lambda: self._plan_worker(generation, contents, scan, parts, disk_usage), thread=True,
                        group="restore-plan")

    def _plan_worker(self, generation: int, contents: BackupContents, scan: FlavorScan, parts: tuple[str, ...],
                     disk_usage: Callable) -> None:
        try:
            plan = plan_restore(contents, scan, parts, disk_usage=disk_usage)
        except Exception as exc:  # noqa: BLE001 - shown on the screen
            if not isinstance(exc, RestoreError):
                log_exception("ibackup.ui", exc)
            self.app.call_from_thread(self._planned, generation, None, _error_text(exc))
            return
        self.app.call_from_thread(self._planned, generation, plan, "")

    def _planned(self, generation: int, plan: RestorePlan | None, error: str) -> None:
        if generation != self._generation or not self.is_attached:
            return  # the boxes changed since: a newer plan is on its way
        if plan is None:
            self._show(error, f"bold {theme_colour(self.app, 'error')}")
            return
        self.plan = plan
        lines = restore_warnings(plan)
        text = "\n".join(lines) if lines else ("Nothing on disk would be lost: your folders hold nothing the backup "
                                               "lacks.")
        if plan.links_kept:
            text += f"\nLinks kept as they are: {len(plan.links_kept)}"
        self._show(text, theme_colour(self.app, "warning") if lines else "")
        self.query_one("#btn-restore", Button).disabled = False

    # --- actions ---------------------------------------------------------------------------------
    def action_restore(self) -> None:
        if self.plan is None or self.query_one("#btn-restore", Button).disabled:
            return
        log_event("ui.selection", screen="ibackup_restore", control="restore", value=list(self.plan.parts))
        self.dismiss(self.plan)

    def action_cancel(self) -> None:
        log_event("ui.selection", screen="ibackup_restore", control="back", value=True)
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "btn-restore":
            self.action_restore()
        else:
            self.action_cancel()


class RestoreResultScreen(Screen[str]):
    """The outcome of a restore or an undo, per part. Dismisses with "undo", "review", "flavors", "tools" or
    "quit"."""

    DEFAULT_CSS = """
    RestoreResultScreen #result { height: 1fr; padding: 1 2; }
    RestoreResultScreen #result-head { height: auto; margin-bottom: 1; }
    RestoreResultScreen #result-table { height: auto; }
    RestoreResultScreen .buttons { height: auto; padding: 0 2; }
    RestoreResultScreen .buttons Button { min-width: 0; width: auto; margin-right: 1; }
    RestoreResultScreen NavHint { padding: 0 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("z", "choose('undo')", "Undo"), Binding("r", "choose('review')", "Rescan"),
        Binding("f", "choose('flavors')", "Flavors"), Binding("t", "choose('tools')", "Tools"),
        Binding("q", "choose('quit')", "Quit"), Binding("escape", "choose('review')", "Back", show=False),
        *NAV_BINDINGS]

    def __init__(self, result: RestoreResult) -> None:
        super().__init__()
        self.result = result

    @property
    def can_undo(self) -> bool:
        """Undo is offered for a restore whose journal recorded a swapped part (RestoreResult.swapped). Without one
        it has nothing Undo can put back, and Undo would pick an older restore."""
        r = self.result
        return not r.undo and r.journal_path is not None and r.swapped

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """z is not a key here (nor in the footer) when there is no Undo."""
        return not (action == "choose" and parameters == ("undo",) and not self.can_undo)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="result"):
            yield Static(id="result-head")
            yield DataTable(id="result-table", cursor_type="row", zebra_stripes=True)
        with ButtonRow(classes="buttons"):
            if self.can_undo:
                yield action_button("Undo (z)", "revert", id="undo")
            yield action_button("Rescan (r)", "neutral", id="review")
            yield action_button("Other flavor (f)", "neutral", id="flavors")
            yield action_button("Tools (t)", "neutral", id="tools")
            yield action_button("Quit (q)", "neutral", id="quit")
        hint = "←→ buttons · Enter/Space press · Esc back · " + ("z undo · " if self.can_undo else "")
        yield NavHint(hint + "r rescan · f other flavor · t tools · q quit")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        r = self.result
        self.sub_title = "Interface Backup · undo result" if r.undo else "Interface Backup · restore result"
        what = "undo" if r.undo else "restore"
        state = "finished." if r.ok and r.parts else "did not finish for every part; see below."
        head = [f"{r.flavor.display_name}: {what} {state}",
                f"{'Put back from the safety backup' if r.undo else 'Restored from'}: {to_stored(r.backup)}"]
        if r.safety_zip is not None:
            head.append(f"Safety backup of the folders as they were: {to_stored(r.safety_zip)}")
        if r.journal_path is not None:
            head.append(f"Journal: {to_stored(r.journal_path)}")
        self.query_one("#result-head", Static).update(Text("\n".join(head)))
        table = self.query_one("#result-table", DataTable)
        table.add_columns(*RESTORE_RESULT_COLUMNS)
        styles = {"restored": "success", "replaced_left": "warning", "rolled_back": "warning", "failed": "error"}
        for outcome, (part, kind, reason) in zip(ordered_parts(r), restore_result_rows(r)):
            style = f"bold {theme_colour(self.app, styles.get(outcome.kind, 'warning'))}"
            table.add_row(Text(part), Text(kind, style=style), Text(reason))
        self.query_one("#review", Button).focus()

    def action_choose(self, choice: str) -> None:
        if choice == "undo" and not self.can_undo:
            return
        log_event("ui.selection", screen="ibackup_restore_result", control="next", value=choice)
        self.dismiss(choice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_choose(event.button.id or "quit")
