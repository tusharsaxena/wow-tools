"""Review the chosen flavors as a tree (what Interface and WTF hold, links, warnings, each flavor's backups), tick
flavors to back up, highlight a backup to restore, or undo the last restore; plus the progress and result screens
of a backup. The restore screens are in restore_screen.py."""
from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Header, Label, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode
from textual.worker import get_current_worker

from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.journal import Journal
from wowtools.core.paths import to_stored
from wowtools.core.process import wow_check_for
from wowtools.tools.interface_backup.backup import BackupOutcome, back_up_all
from wowtools.tools.interface_backup.catalog import BackupInfo, list_backups, read_parts
from wowtools.tools.interface_backup.journal import latest_undoable, read_restore_journal
from wowtools.tools.interface_backup.report import (BACKUP_RESULT_COLUMNS, PARTS_PENDING, STAGE_TITLES,
                                                    backup_confirm, backup_detail, backup_result_rows,
                                                    backup_summary_rows, backup_text, backups_title, flavor_text, held_text, leftover_text, part_text,
                                                    plural, restore_confirm, selection_text, undo_confirm,
                                                    warnings_text)
from wowtools.tools.interface_backup.restore import RestoreError, RestorePlan, RestoreResult, RestoreStopped, restore
from wowtools.tools.interface_backup.restore_screen import RestoreResultScreen, RestoreScreen
from wowtools.tools.interface_backup.scanner import CHEAP_STATS, PARTS, FlavorScan, scan_flavors
from wowtools.tools.interface_backup.settings import (load_settings, resolve_backup_root, resolve_journal_dir,
                                                      validate_backup_dir)
from wowtools.tools.interface_backup.undo import undo_restore
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import (ACCENT, BUSY_STYLE, RESULT_HINT, REVIEW_HINT, ConfirmScreen, ProgressScreen, TwoPaneFocus,
                                relabel_branch, result_css, theme_colour, tick_mark, two_pane_css)
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

NAV_HINT = REVIEW_HINT + "a all · n none · b back up · e restore · r rescan · z undo · f flavors · t tools"
# Tree nodes that cannot be ticked: a backup always holds a flavor's whole Interface and WTF.
READ_ONLY = ("part", "links", "link", "leftover", "warnings", "warning", "backups", "backup")
WowCheck = Callable[[], "list[str] | None"]
# Seconds between two per-file progress reports sent to the UI thread. Each costs a blocking call_from_thread
# (~0.6 ms); an Interface folder of tens of thousands of files, reported per file in several stages, spent most of
# a backup or restore in those round trips.
PROGRESS_INTERVAL = 0.1


class ThrottledProgress:
    """progress(stage, current, total, detail) for a job's worker: forwards a report when the stage changes, when
    it has no count (total 0) or ends a stage (current >= total), or when `interval` seconds passed since the last
    one forwarded; the others are dropped. reset() forwards the next report whatever it is (a new flavor)."""

    def __init__(self, forward: Callable[..., None], interval: float, clock: Callable[[], float] = time.monotonic):
        self.forward = forward
        self.interval = interval
        self.clock = clock
        self._stage: object = None
        self._last = 0.0
        self._fresh = True

    def reset(self) -> None:
        self._fresh = True

    def __call__(self, *args: Any) -> None:
        stage = args[0] if args else None
        current, total = (args[1], args[2]) if len(args) >= 3 else (0, 0)
        now = self.clock()
        due = (self._fresh or stage != self._stage or not total or current >= total
               or now - self._last >= self.interval)
        if not due:
            return
        self._fresh, self._stage, self._last = False, stage, now
        self.forward(*args)


def free_bytes(path: Path | None, disk_usage: Callable = shutil.disk_usage) -> int | None:
    """Free bytes on the drive that holds path (or its nearest existing parent); None when unknown."""
    while path is not None and not path.exists() and path.parent != path:
        path = path.parent
    if path is None:
        return None
    try:
        return int(disk_usage(path).free)
    except (OSError, ValueError):
        return None


class BackupProgressScreen(ProgressScreen):
    """Shown while a backup, a restore or an undo runs."""

    ID_PREFIX = "ibackup"
    STAGE_TITLES = STAGE_TITLES

    def __init__(self, first_stage: str = "backup") -> None:
        super().__init__(first_stage=first_stage)


class BackupResultScreen(Screen[str]):
    """The outcome of a backup: a summary table, one row per flavor and what to do next."""

    DEFAULT_CSS = result_css("BackupResultScreen")
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("r", "choose('review')", "Rescan"), Binding("e", "choose('restore')", "Restore"),
        Binding("f", "choose('flavors')", "Flavors"), Binding("t", "choose('tools')", "Tools"),
        Binding("q", "choose('quit')", "Quit"), Binding("escape", "choose('review')", "Back", show=False),
        *NAV_BINDINGS]

    def __init__(self, outcomes: list[BackupOutcome]) -> None:
        super().__init__()
        self.outcomes = outcomes

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="result"):
            summary = DataTable(id="result-summary", cursor_type="none", zebra_stripes=True)
            summary.can_focus = False  # read-only summary: not a focus stop
            yield summary
            yield DataTable(id="result-table", classes="result-detail", cursor_type="row", zebra_stripes=True)
        with ButtonRow(classes="buttons"):
            yield action_button("Rescan (r)", "neutral", id="review")
            yield action_button("Restore (e)", "neutral", id="restore")
            yield action_button("Other flavor (f)", "neutral", id="flavors")
            yield action_button("Tools (t)", "neutral", id="tools")
            yield action_button("Quit (q)", "neutral", id="quit")
        yield NavHint(RESULT_HINT + "r rescan · e restore · f other flavor · t tools · q quit")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Interface Backup · result"
        summary = self.query_one("#result-summary", DataTable)
        summary.add_columns("Item", "Value")
        summary.add_rows((Text(item), Text(value)) for item, value in backup_summary_rows(self.outcomes))
        table = self.query_one("#result-table", DataTable)
        table.add_columns(*BACKUP_RESULT_COLUMNS)
        styles = {"created": "success", "failed": "error", "skipped": "warning"}
        for outcome, (flavor, kind, *rest) in zip(self.outcomes, backup_result_rows(self.outcomes)):
            style = f"bold {theme_colour(self.app, styles[outcome.kind])}" if outcome.kind in styles else ""
            table.add_row(Text(flavor), Text(kind, style=style), *(Text(c) for c in rest))
        self.query_one("#review", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "quit")

    def action_choose(self, choice: str) -> None:
        log_event("ui.selection", screen="ibackup_result", control="next", value=choice)
        self.dismiss(choice)


class BackupTree(Tree):
    """The flavors tree. ← jumps to the left panel (instead of scrolling sideways)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class BackupReviewScreen(TwoPaneFocus, Screen[str]):
    """The chosen flavors as a tree (what Interface and WTF hold, links, warnings, the flavor's backups) with
    flavor ticks for Back up, a highlighted backup for Restore, and Undo. Dismisses with "flavors", "tools" or
    "quit"."""

    TREE_SELECTOR = "#flavors"
    DEFAULT_CSS = two_pane_css("BackupReviewScreen", "#flavors")
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("b", "back_up", "Back up"),
        Binding("e", "restore", "Restore"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
        Binding("f", "leave('flavors')", "Flavors"),
        Binding("t", "leave('tools')", "Tools"),
        Binding("q", "leave('quit')", "Quit"),
        Binding("escape", "leave('flavors')", "Flavors", show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: list[Flavor], scope_label: str, *,
                 wow_check: WowCheck | None = None, disk_usage: Callable = shutil.disk_usage,
                 wow_root: Path | None = None) -> None:
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/interface-backup.cfg
        self.flavors = list(flavors)
        # The WoW folder these flavors were read from. If `s` changes the shared WoW folder, they belong to another
        # install: the review goes back to the flavor picker rather than mix the two (see wow_folder_changed).
        self.wow_root = wow_root if wow_root is not None else cfg.wow_path
        self._leaving_for_new_folder = False
        self.scope_label = scope_label
        self.wow_check = wow_check  # None: built per run from the flavors involved
        self.disk_usage = disk_usage
        self.settings = load_settings(tool_cfg)
        self.scans: list[FlavorScan] | None = None
        self.backups: list[BackupInfo] = []
        self.undoable: Path | None = None  # the newest undoable restore journal, found by the scan worker
        self.unchecked: set[str] = set()  # flavor folders not ticked (kept across rescans: the flavors stay)
        self.parts: dict[Path, tuple[str, ...] | None] = {}  # a backup's parts, read per zip by a worker
        self.summary_text = ""
        self._backup_nodes: dict[Path, TreeNode] = {}
        self._scanning = False
        self._checking = False  # the running-WoW check is in its worker
        # What a result screen asked for once its rescan is done: ("restore", None) for Restore (e), or ("undo",
        # journal) for Undo (z), which undoes that journal only if the scan still finds it the undoable one.
        self._after_scan: tuple[str, Path | None] | None = None
        self._progress_screen: ProgressScreen | None = None
        self._last_filter: Widget | None = None

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("Backup folder", classes="section")
                yield Static("", id="folder-label")
                yield Label("Keep", classes="section")
                yield Static("", id="keep-label")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Back up", "apply", id="btn-backup")
                    yield action_button("Restore", "neutral", id="btn-restore")
                    yield action_button("Rescan", "neutral", id="btn-rescan")
                    yield action_button("Undo last restore", "revert", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield BackupTree(Text(self.scope_label), id="flavors")
        yield Static("", id="summary")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"Interface Backup · {self.scope_label}"
        self.query_one("#flavors", Tree).focus()
        self.action_rescan()

    def _show_settings(self) -> None:
        root = self._root()
        keep = self.settings.keep_backups
        self.query_one("#folder-label", Static).update(Text(to_stored(root) if root else "?"))
        self.query_one("#keep-label", Static).update(Text("all backups" if keep == 0 else
                                                          f"newest {keep} per flavor"))

    # --- panes (←/→): TwoPaneFocus ------------------------------------------------------------------
    def first_filter(self) -> Widget | None:
        return next((b for b in self.query("#actions Button").results(Button) if b.focusable), None)

    # --- the WoW folder ------------------------------------------------------------------------
    def wow_folder_changed(self) -> bool:
        """True when the shared WoW folder is no longer the one these flavors came from (changed with `s`). The
        review then goes back to the flavor picker as soon as it is the screen shown: a scan, backup, restore or
        undo would otherwise read one install while the backup folder, journals and Undo use the other."""
        if self.cfg.wow_path == self.wow_root:
            return False
        if not self._leaving_for_new_folder and self.app.screen is self and not self.app.busy:
            self._leaving_for_new_folder = True
            self.notify("The WoW folder changed: pick the flavor again.", severity="warning")
            self.dismiss("flavors")
        return True

    def on_screen_resume(self) -> None:
        self.wow_folder_changed()

    # --- paths ---------------------------------------------------------------------------------
    def _root(self) -> Path | None:
        return resolve_backup_root(self.settings, self.cfg.wow_path)

    def _journal_dir(self) -> Path | None:
        return resolve_journal_dir(self.cfg.wow_path)

    def _folder_problem(self) -> str | None:
        """The saved backup folder is checked again before it is used: the file may have been edited by hand."""
        wow = self.cfg.wow_path
        if wow is None:
            return "No WoW folder is set."
        return validate_backup_dir(self.settings.backup_dir, WowInstall(wow))

    @property
    def idle(self) -> bool:
        """Nothing is scanning, checking or running: the actions are open."""
        return not (self._scanning or self._checking or self.app.busy)

    def _refresh_buttons(self) -> None:
        if not self.is_attached:
            return
        idle = self.idle
        has_data = bool(self.scans) and any(s.has_data for s in self.scans or ())
        self.query_one("#btn-backup", Button).disabled = not idle or not has_data
        self.query_one("#btn-restore", Button).disabled = not idle
        self.query_one("#btn-undo", Button).disabled = not idle or self.undoable is None
        self.query_one("#btn-rescan", Button).disabled = not idle

    def _set_summary(self, text: Text | str) -> None:
        self.query_one("#summary", Static).update(text if isinstance(text, Text) else Text(text))

    # --- scan ----------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if not self.idle or self.wow_folder_changed():
            return
        self.settings = load_settings(self.tool_cfg)
        self._show_settings()
        self.scans = None
        self._show_scan_progress(True)
        self._refresh_buttons()
        flavors, root, journal_dir = list(self.flavors), self._root(), self._journal_dir()
        self.run_worker(lambda: self._scan_worker(flavors, root, journal_dir), thread=True, exclusive=True,
                        group="scan")

    def _show_scan_progress(self, scanning: bool) -> None:
        """While scanning, the tree is replaced by a progress bar and the folder being read."""
        self._scanning = scanning
        if scanning:
            self.query_one("#scan-progress", ProgressBar).update(total=None, progress=0)
            self.query_one("#scan-label", Static).update(Text("Reading the Interface and WTF folders"))
        self.query_one("#scan-box").display = scanning
        self.query_one("#flavors", Tree).display = not scanning

    def _scan_worker(self, flavors: list[Flavor], root: Path | None, journal_dir: Path | None) -> None:
        def progress(stage: str, current: int, total: int, detail: str) -> None:
            self.app.call_from_thread(self._scan_progress, current, total, detail)

        try:
            scans = scan_flavors(flavors, with_stats=CHEAP_STATS, progress=progress)
            backups = list_backups(root, {f.short_name for f in flavors})  # never raises
            undoable = latest_undoable(journal_dir)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("ibackup.scan", exc)
            self.app.call_from_thread(self._scan_failed, f"The scan failed: {exc}")
            return
        self.app.call_from_thread(self._scanned, scans, backups, undoable)

    def _scan_progress(self, current: int, total: int, detail: str) -> None:
        if not self.is_attached:
            return
        self.query_one("#scan-progress", ProgressBar).update(total=total or None, progress=current)
        self.query_one("#scan-label", Static).update(Text(detail))

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        self._after_scan = None
        if not self.is_attached:
            return
        self._show_scan_progress(False)
        self.summary_text = message
        self._set_summary(message)
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, scans: list[FlavorScan], backups: list[BackupInfo], undoable: Path | None) -> None:
        self._scanning = False
        self.scans, self.backups, self.undoable = scans, backups, undoable
        self.parts = {}  # read again on expand: a zip may have been replaced since
        if not self.is_attached:
            return
        self._show_scan_progress(False)
        self._rebuild()
        self._refresh_buttons()
        self.query_one("#flavors", Tree).focus()
        pending, self._after_scan = self._after_scan, None
        if pending is None:
            return
        what, journal = pending
        if self.app.screen is not self:
            # Another screen (settings, say) opened while the scan ran: never open Restore or Undo on top of it.
            key = "e" if what == "restore" else "z"
            self.notify(f"{'Restore' if what == 'restore' else 'Undo'} was not opened. Press {key} on the review "
                        "screen.", severity="warning")
            return
        if what == "restore":
            self._show_newest_backup()
        elif journal is not None and journal == undoable:
            self.action_undo()
        else:
            self.notify("That restore can no longer be undone.", severity="warning")

    # --- tree ------------------------------------------------------------------------------------
    def _flavor_backups(self, scan: FlavorScan) -> list[BackupInfo]:
        return [b for b in self.backups if b.flavor_short == scan.flavor.short_name]

    def _rebuild(self) -> None:
        scans = self.scans
        if scans is None:
            return
        tree = self.query_one("#flavors", Tree)
        tree.clear()
        self._backup_nodes = {}
        tree.root.data = ("root",)
        tree.root.set_label(self._label(tree.root.data))
        for scan in scans:
            data = ("flavor", scan)
            node = tree.root.add(self._label(data), data=data, expand=True)
            for name in PARTS:
                part = scan.parts[name]
                node.add_leaf(Text.assemble((name, "bold"), (f"  {part_text(part)}", "dim")), data=("part", scan))
            if scan.link_count:
                node.add(Text.assemble((f"Links ({scan.link_count})", "bold"),
                                       ("  not backed up; a restore keeps them", "dim")),
                         data=("links", scan), allow_expand=True)  # paths load on expand
            if scan.leftovers:
                node.add_leaf(Text(f"⚠ {leftover_text(scan)}", style=f"bold {theme_colour(self.app, 'warning')}"),
                              data=("leftover", scan))
            if any(p.errors for p in scan.parts.values()):
                node.add(Text(f"⚠ {warnings_text(scan)}", style=f"bold {theme_colour(self.app, 'warning')}"),
                         data=("warnings", scan), allow_expand=True)  # lines load on expand
            backups = self._flavor_backups(scan)
            if backups:
                node.add(Text.assemble((backups_title(backups), "bold"),
                                       ("  highlight one and press e to restore it", "dim")),
                         data=("backups", scan), allow_expand=True)  # zips load on expand, parts in a worker
            else:
                node.add_leaf(Text.assemble(("Backups (0)", "bold"), ("  none yet", "dim")), data=("backups", scan))
        tree.root.expand()
        self._update_summary()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if node.data is None or node.children:
            return
        kind, scan = node.data[0], node.data[-1]
        if kind == "links":
            for name in PARTS:
                for rel in scan.parts[name].links:
                    node.add_leaf(Text(f"{name}/{rel}", style="dim"), data=("link", scan))
        elif kind == "warnings":
            for part in scan.parts.values():
                for error in part.errors:
                    node.add_leaf(Text(error, style="dim"), data=("warning", scan))
        elif kind == "backups":
            self._add_backups(node, scan)

    def _add_backups(self, node: TreeNode, scan: FlavorScan) -> None:
        backups = self._flavor_backups(scan)
        for info in backups:
            parts = self.parts.get(info.path, PARTS_PENDING)
            self._backup_nodes[info.path] = node.add_leaf(Text(backup_text(info, parts)), data=("backup", info))
        unread = [b.path for b in backups if b.path not in self.parts]
        if unread:
            self.run_worker(lambda: self._parts_worker(unread), thread=True, group="backup-parts")

    def _parts_worker(self, paths: list[Path]) -> None:
        worker = get_current_worker()
        for path in paths:
            if worker.is_cancelled:
                return
            parts = read_parts(path)  # never raises
            if worker.is_cancelled:
                return
            self.app.call_from_thread(self._parts_read, path, parts)

    def _parts_read(self, path: Path, parts: tuple[str, ...] | None) -> None:
        node = self._backup_nodes.get(path)
        if node is None or not self.is_attached:
            return  # rebuilt (a rescan) since the worker started: its parts are read again on expand
        self.parts[path] = parts
        node.set_label(Text(backup_text(node.data[1], parts)))
        if self.highlighted_backup() is node.data[1]:
            self._update_summary()  # the bottom line names the highlighted backup's parts too

    def _show_newest_backup(self) -> None:
        """Restore (e) from a result screen: open the Backups of the flavors and put the cursor on the newest
        backup of them all (not a safety zip): the one just made, whichever flavor it is in."""
        tree = self.query_one("#flavors", Tree)
        opened = False
        for flavor_node in tree.root.children:
            group = next((c for c in flavor_node.children if c.data and c.data[0] == "backups"
                          and c.allow_expand), None)
            if group is None:
                continue
            if not group.children:
                self._add_backups(group, group.data[1])  # now, so the cursor can go there below
            flavor_node.expand()
            group.expand()
            opened = True
        if not opened:
            self.notify("No backups of these flavors yet.")
            return
        shown = [b for b in self.backups if b.path in self._backup_nodes]
        newest = max((b for b in shown if not b.is_safety), key=lambda b: (b.stamp, b.n), default=None)
        if newest is None:
            newest = max(shown, key=lambda b: (b.stamp, b.n), default=None)
        self.call_after_refresh(self._cursor_to_backup, newest)

    def _cursor_to_backup(self, info: BackupInfo | None) -> None:
        tree = self.query_one("#flavors", Tree)
        node = self._backup_nodes.get(info.path) if info is not None else None
        if node is not None:
            tree.move_cursor(node)
        tree.focus()
        self.notify("Highlight a backup and press e (or Enter) to restore it.")

    def _mark(self, scans: list[FlavorScan]) -> tuple[str, str]:
        if not scans:
            return "  ", ""  # nothing to back up: no tick, as in the other tools
        return tick_mark(scans, self.unchecked, lambda s: s.flavor.folder, success=theme_colour(self.app, "success"))

    def _scans_of(self, data) -> list[FlavorScan]:
        """The flavors a tick on this node covers: those with something to back up (the others have no tick)."""
        if data[0] == "root":
            return [s for s in self.scans or [] if s.has_data]
        return [data[1]] if data[0] == "flavor" and data[1].has_data else []

    def _label(self, data) -> Text:
        scans = self._scans_of(data)
        mark = self._mark(scans)
        if data[0] == "root":
            return Text.assemble(mark, (self.scope_label, ACCENT), (f"  {held_text(scans)}", "dim"))
        scan = data[1]
        return Text.assemble(mark, (scan.flavor.display_name, ACCENT),
                             (f"  {flavor_text(scan, self._flavor_backups(scan))}", "dim"))

    def _refresh_labels(self, node=None) -> None:
        """Relabel node's branch and its ancestors (everything a tick there can change), or the whole tree."""
        relabel_branch(self.query_one("#flavors", Tree), node, self._label, skip=READ_ONLY)
        self._update_summary()

    def selection(self) -> list[FlavorScan]:
        """The ticked flavors (only a flavor with something to back up has a tick)."""
        return [s for s in self.scans or [] if s.has_data and s.flavor.folder not in self.unchecked]

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if not self._checking:  # the bottom line says "Checking…" until the check is done
            self._update_summary()

    def _update_summary(self) -> None:
        if self.scans is None or not self.is_attached:
            return
        info = self.highlighted_backup()
        # The tree shows only the start of a backup's line at 80 columns: the bottom line names it in full.
        hint = (f"{backup_detail(info, self.parts.get(info.path, PARTS_PENDING))}: e restores it" if info is not None
                else "Highlight a backup and press e to restore it.")
        text = f"{selection_text(self.selection())}    {hint}"
        blocked = [s.flavor.display_name for s in self.scans if s.leftovers]
        if blocked:
            text += f"    ⚠ Restore blocked for {', '.join(blocked)} (interrupted restore)"
        warnings = sum(len(p.errors) for s in self.scans for p in s.parts.values())
        if warnings:
            text += f"    ⚠ {plural(warnings, 'scan warning')} (see the tree)"
        self.summary_text = text
        self._set_summary(text)

    # --- ticks -----------------------------------------------------------------------------------
    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Button):  # Space activates the focused button, never the tree
            focused.press()
            return
        if not isinstance(focused, Tree):
            return
        node = self.query_one("#flavors", Tree).cursor_node
        if node is None or node.data is None or node.data[0] in READ_ONLY:
            return
        folders = [s.flavor.folder for s in self._scans_of(node.data)]
        if not folders:
            return
        check = any(f in self.unchecked for f in folders)
        if check:
            self.unchecked.difference_update(folders)
        else:
            self.unchecked.update(folders)
        log_event("ui.item_toggled", screen="ibackup_review",
                  key="root" if node.data[0] == "root" else folders[0], checked=check)
        self._refresh_labels(node)

    def action_select_all(self) -> None:
        self.unchecked.clear()
        log_event("ui.selection", screen="ibackup_review", control="select_all", value=True)
        self._refresh_labels()

    def action_select_none(self) -> None:
        self.unchecked = {f.folder for f in self.flavors}
        log_event("ui.selection", screen="ibackup_review", control="select_none", value=True)
        self._refresh_labels()

    # --- running-WoW check (PowerShell/tasklist can take seconds: never on the UI thread) ---------------
    def run_preflight(self, check: WowCheck, then: Callable[[list[str] | None, Any], None],
                      extra: Callable[[], Any] | None = None) -> None:
        """Run check() (and extra(), e.g. free space) in a worker, then call then(running, extra_result) on the UI
        thread if this screen is still the one shown. A failing check is "unknown" (None)."""
        self._checking = True
        self._refresh_buttons()
        self._set_summary(Text("Checking for running programs…", style=BUSY_STYLE))
        self.run_worker(lambda: self._preflight_worker(check, extra, then), thread=True, group="preflight")

    def _preflight_worker(self, check: WowCheck, extra: Callable[[], Any] | None,
                          then: Callable[[list[str] | None, Any], None]) -> None:
        running = result = None
        try:
            running = check()
        except Exception as exc:  # noqa: BLE001 - a failed check is "unknown", as when PowerShell is missing
            log_exception("preflight", exc)
        if extra is not None:
            try:
                result = extra()
            except Exception as exc:  # noqa: BLE001 - unknown as well
                log_exception("preflight", exc)
        self.app.call_from_thread(self._preflight_done, running, result, then)

    def _preflight_done(self, running: list[str] | None, result: Any,
                        then: Callable[[list[str] | None, Any], None]) -> None:
        self._checking = False
        if not self.is_attached:
            return
        self._update_summary()
        self._refresh_buttons()
        if self.app.screen is not self:
            return  # the user left the screen while the check ran
        if running:
            log_event("wow.running_warning", executables=running)
        then(running, result)

    # --- back up -------------------------------------------------------------------------------
    def action_back_up(self) -> None:
        if self.scans is None or not self.idle or self.wow_folder_changed():
            return
        log_event("ui.selection", screen="ibackup_review", control="back_up", value=True)
        # The ticked flavors go to the backup. A flavor with nothing to back up (no folders, or links) has no tick:
        # the tree says why.
        scans = self.selection()
        if not scans:
            nothing = not any(s.has_data for s in self.scans)
            self.notify("Nothing to back up: no Interface or WTF folder in these flavors." if nothing
                        else "Nothing is selected.")
            return
        self.settings = load_settings(self.tool_cfg)
        problem = self._folder_problem()
        root = self._root()
        if problem or root is None:
            self.notify(f"{problem or 'No backup folder.'} Fix the folder in settings (s).",
                        title="Backup folder not allowed", severity="error", timeout=15)
            return
        check = self.wow_check or wow_check_for([s.flavor for s in scans if s.has_data])
        disk_usage = self.disk_usage
        self.run_preflight(check, lambda running, free: self._confirm_backup(scans, root, running, free),
                           extra=lambda: free_bytes(root, disk_usage))

    def _confirm_backup(self, scans: list[FlavorScan], root: Path, running: list[str] | None,
                        free: int | None) -> None:
        keep = self.settings.keep_backups
        title, body, alerts = backup_confirm(scans, root, keep, running, free)
        self.app.push_screen(ConfirmScreen(title, body, alerts, default_yes=True),
                             lambda ok: self._backup_confirmed(ok, scans, root, keep))

    def _backup_confirmed(self, ok: bool | None, scans: list[FlavorScan], root: Path, keep: int) -> None:
        log_event("ui.selection", screen="confirm", control="back_up_confirm", value=bool(ok))
        if not ok or not self.idle or self.wow_folder_changed():
            return
        self.run_job(BackupProgressScreen("backup"),
                     lambda progress, on_flavor: back_up_all(scans, root, keep=keep, progress=progress,
                                                             on_flavor=on_flavor),
                     self._backup_done)

    def _backup_done(self, outcomes: list[BackupOutcome]) -> None:
        self.app.push_screen(BackupResultScreen(outcomes), self._after_result)

    # --- running a job -------------------------------------------------------------------------
    def run_job(self, screen: ProgressScreen, job: Callable[[Callable, Callable], Any],
                done: Callable[[Any], None]) -> None:
        """Run job(progress, on_flavor) in a worker behind the progress screen, then call done(result). The app's
        busy flag stays up until it ends: quitting, leaving and every other action wait."""
        self.app.busy = True
        self._refresh_buttons()
        self._progress_screen = screen
        self.app.push_screen(screen)
        self.run_worker(lambda: self._job_worker(job, screen, done), thread=True, exclusive=True, group="job")

    def _job_worker(self, job: Callable[[Callable, Callable], Any], screen: ProgressScreen,
                    done: Callable[[Any], None]) -> None:
        # Runs in a worker thread: the progress screen is only ever touched on the UI thread, and per-file reports
        # reach it throttled (ThrottledProgress).
        progress = ThrottledProgress(lambda *args: self.app.call_from_thread(screen.update_progress, *args),
                                     PROGRESS_INTERVAL)

        def on_flavor(label: str) -> None:
            progress.reset()
            self.app.call_from_thread(screen.set_flavor, label)

        try:
            with activity.running():
                result = job(progress, on_flavor)
        except Exception as exc:  # noqa: BLE001 - shown by the UI
            self.app.call_from_thread(self._job_failed, exc)
            return
        self.app.call_from_thread(self._job_done, done, result)

    def _close_progress(self) -> None:
        screen, self._progress_screen = self._progress_screen, None
        if screen is not None and self.app.screen is screen:
            self.app.pop_screen()

    def _job_done(self, done: Callable[[Any], None], result: Any) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_buttons()
        done(result)

    def _job_failed(self, exc: Exception) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_buttons()
        self.job_failed(exc)

    def job_failed(self, exc: Exception) -> None:
        """An error out of a job: a refused restore or undo (RestoreError, nothing changed), one that stopped
        part-way (RestoreStopped: its result screen shows what was done) or anything unexpected. Then a rescan."""
        if isinstance(exc, RestoreError):
            self.notify(str(exc), title="Nothing was changed", severity="error", timeout=20)
        elif isinstance(exc, RestoreStopped):
            what = "Undo" if exc.result.undo else "Restore"
            hint = " Undo (z) puts back what was replaced." if exc.result.swapped and not exc.result.undo else ""
            self.notify(f"{exc}{hint}", title=f"{what} stopped", severity="error", timeout=20)
            self.app.push_screen(RestoreResultScreen(exc.result),
                                 lambda choice: self._after_restore_result(choice, exc.result))
        else:
            log_exception("ibackup.ui", exc)
            self.notify(f"{type(exc).__name__}: {exc}", title="Stopped", severity="error", timeout=20)
        self.action_rescan()

    def _after_result(self, choice: str | None) -> None:
        if choice in ("flavors", "tools", "quit"):
            self.dismiss(choice)
            return
        self._after_scan = ("restore", None) if choice == "restore" else None
        self.action_rescan()

    # --- restore ------------------------------------------------------------------------------
    def highlighted_backup(self) -> BackupInfo | None:
        """The backup under the tree's cursor, or None."""
        node = self.query_one("#flavors", Tree).cursor_node
        if node is not None and node.data is not None and node.data[0] == "backup":
            return node.data[1]
        return None

    def action_restore(self) -> None:
        if not self.idle or self.app.screen is not self or self.wow_folder_changed():
            return
        info = self.highlighted_backup()
        log_event("ui.selection", screen="ibackup_review", control="restore",
                  value=info.path.name if info is not None else None)
        if info is None:
            self.notify("Open a flavor's Backups in the tree, highlight a backup and press e (or Enter) to restore "
                        "it.", title="No backup highlighted")
            return
        self._backup_chosen(info)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if data is not None and data[0] == "backup":
            event.stop()
            self.action_restore()

    def _backup_chosen(self, info: BackupInfo | None) -> None:
        if info is None or not self.idle or self.wow_folder_changed():
            return
        flavor = next((f for f in self.flavors if f.short_name == info.flavor_short), None)
        if flavor is None:  # the tree holds only the chosen flavors' backups
            self.notify(f"No flavor here matches {info.flavor_short}.", severity="error")
            return
        self.app.push_screen(RestoreScreen(info, flavor, disk_usage=self.disk_usage),
                             lambda plan: self._restore_chosen(plan, info))

    def _restore_chosen(self, plan: RestorePlan | None, info: BackupInfo) -> None:
        if plan is None or not self.idle or self.wow_folder_changed():
            return
        check = self.wow_check or wow_check_for([plan.flavor])
        root, disk_usage = self._root(), self.disk_usage
        # The safety backup goes to the backup folder, maybe on another drive than WoW: its free space is checked too.
        self.run_preflight(check, lambda running, free: self._confirm_restore(plan, info, running, free),
                           extra=lambda: free_bytes(root, disk_usage))

    def _confirm_restore(self, plan: RestorePlan, info: BackupInfo, running: list[str] | None,
                         backup_free: int | None) -> None:
        title, body, alerts = restore_confirm(plan, info.when, running, backup_free=backup_free)
        self.app.push_screen(ConfirmScreen(title, body, alerts, default_yes=False),
                             lambda ok: self._restore_confirmed(ok, plan))

    def _restore_confirmed(self, ok: bool | None, plan: RestorePlan) -> None:
        log_event("ui.selection", screen="confirm", control="restore_confirm", value=bool(ok))
        self.settings = load_settings(self.tool_cfg)
        root, journal_dir, keep = self._root(), self._journal_dir(), self.settings.keep_journals
        if not ok or not self.idle or self.wow_folder_changed():
            return
        problem = self._folder_problem()
        if problem or root is None or journal_dir is None:
            self.notify(f"{problem or 'No backup folder.'} Fix the folder in settings (s).",
                        title="Backup folder not allowed", severity="error", timeout=15)
            return

        def job(progress: Callable, on_flavor: Callable) -> RestoreResult:
            on_flavor(plan.flavor.display_name)
            return restore(plan, root=root, journal_dir=journal_dir, keep_journals=keep, progress=progress)

        self.run_job(BackupProgressScreen("verify"), job, self._restore_done)

    def _restore_done(self, result: RestoreResult) -> None:
        self.app.push_screen(RestoreResultScreen(result), lambda choice: self._after_restore_result(choice, result))

    def _after_restore_result(self, choice: str | None, result: RestoreResult) -> None:
        if choice == "undo":
            # Undo this restore: once the rescan has found the newest undoable journal, and only if it is this one.
            self._after_scan = ("undo", result.journal_path)
            self.action_rescan()
            return
        self._after_result(choice)

    # --- undo ----------------------------------------------------------------------------------
    def action_undo(self) -> None:
        if not self.idle or self.app.screen is not self or self.wow_folder_changed():
            return
        log_event("ui.selection", screen="ibackup_review", control="undo", value=True)
        path = self.undoable
        if path is None:
            self.notify("Nothing to undo.")
            return
        read: dict[str, Journal | Exception] = {}

        def check() -> list[str] | None:
            # The journal is read in the worker too: it names the flavor whose WoW process matters.
            try:
                read["journal"] = journal = read_restore_journal(path)
            except (OSError, ValueError) as exc:
                read["journal"] = exc
                return None
            if self.wow_check is not None:
                return self.wow_check()
            folder = journal.header.get("flavor")
            return wow_check_for([folder] if isinstance(folder, str) and folder else self.flavors)()

        self.run_preflight(check, lambda running, _extra: self._confirm_undo(path, read.get("journal"), running))

    def _confirm_undo(self, path: Path, journal: Journal | Exception | None, running: list[str] | None) -> None:
        if not isinstance(journal, Journal):
            self.notify(f"The restore journal could not be read: {journal}", title="Undo not possible",
                        severity="error", timeout=15)
            return
        title, body = undo_confirm(journal)
        alerts = ((f"WoW appears to be running ({', '.join(running)}). Close it first: an open game can lock "
                   "Interface files and rewrites WTF when you log out."),) if running else ()
        self.app.push_screen(ConfirmScreen(title, body, alerts, default_yes=False),
                             lambda ok: self._undo_confirmed(ok, path))

    def _undo_confirmed(self, ok: bool | None, path: Path) -> None:
        log_event("ui.selection", screen="confirm", control="undo_confirm", value=bool(ok))
        self.settings = load_settings(self.tool_cfg)
        wow, root = self.cfg.wow_path, self._root()
        if not ok or not self.idle or wow is None or root is None or self.wow_folder_changed():
            return
        self.run_job(BackupProgressScreen("verify"),
                     lambda progress, _on_flavor: undo_restore(path, wow_root=wow, root=root, progress=progress),
                     self._restore_done)

    # --- leaving -------------------------------------------------------------------------------
    def action_leave(self, choice: str) -> None:
        if not self.app.busy:
            self.dismiss(choice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {"btn-backup": self.action_back_up, "btn-restore": self.action_restore,
                   "btn-undo": self.action_undo, "btn-rescan": self.action_rescan}
        action = actions.get(event.button.id or "")
        if action is not None:
            event.stop()
            action()
