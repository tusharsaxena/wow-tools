"""Review the proposal as a tree, tick/untick, toggle criteria, then clean, dry run or undo the last clean (with a
progress screen and a result screen)."""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, ProgressBar, Static, Tree

from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import ACCOUNT_WIDE, Flavor, WowInstall, validate_output_dir
from wowtools.core.journal import friendly_stamp
from wowtools.core.process import running_wtf_lockers, wow_check_for
from wowtools.tools.wtf_cleaner.cleaner import CLEANED_SUBDIR, CleanError
from wowtools.tools.wtf_cleaner.journal import clean_journal_dir, latest_undoable, read_journal
from wowtools.tools.wtf_cleaner.multi import (FlavorScan, MultiCleanResult, execute_flavors, nothing_deleted,
                                              scan_flavors)
from wowtools.tools.wtf_cleaner.report import (CRITERION_COLORS, CRITERION_SHORT, STAGE_TITLES, age_days,
                                               flavor_name, format_size, locker_warning, plural)
from wowtools.tools.wtf_cleaner.result_screen import ResultScreen, reasons_text
from wowtools.tools.wtf_cleaner.rules import (CRITERIA, Proposal, ProposalItem, criterion_counts, evaluate,
                                             log_proposal_built, log_proposal_items)
from wowtools.tools.wtf_cleaner.safety import SNAPSHOT_SUBDIR, Marker, clear_marker, read_marker, recovery_message
from wowtools.tools.wtf_cleaner.settings import load_settings, resolve_backup_dir
from wowtools.tools.wtf_cleaner.undo import UndoResult, undo_clean
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import (ACCENT, BUSY_STYLE, POPUP_WIDTH, REVIEW_HINT, TREE_BINDINGS, TREE_HINT, ConfirmScreen,
                                ProgressScreen, TwoPaneFocus, relabel_branch, theme_colour, tick_mark, two_pane_css)
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button

WARNING_STYLE = "#E8B04B"
ALL_FLAVORS_LABEL = "All flavors"
# ConfirmScreen now lives in wowtools.ui.dialogs; it stays importable from here for one release.
__all__ = ["CleanProgressScreen", "ConfirmScreen", "RecoveryScreen", "ResultScreen", "ReviewScreen"]
NAV_HINT = REVIEW_HINT + ("a all · n none · w clean · y dry run · " + TREE_HINT +
                          "r rescan · z undo · f flavors · t tools · 1-4 criteria")


class CleanProgressScreen(ProgressScreen):
    """Shown while a clean, dry run or undo runs (the widget ids keep their clean- prefix)."""

    ID_PREFIX = "clean"
    STAGE_TITLES = STAGE_TITLES
    SIMULATED_STAGE = "delete"

    def __init__(self, dry_run: bool, first_stage: str = "check") -> None:
        super().__init__(dry_run=dry_run, first_stage=first_stage)


class RecoveryScreen(ModalScreen[str]):
    """An earlier clean did not finish: say where its WTF backup is. Never restores anything itself."""

    DEFAULT_CSS = f"""
    RecoveryScreen {{ align: center middle; }}
    RecoveryScreen #recovery-box {{ {POPUP_WIDTH} height: auto; border: thick $warning; background: $panel;
                                   padding: 1 2; }}
    RecoveryScreen #recovery-title {{ color: $warning; text-style: bold; margin-bottom: 1; }}
    RecoveryScreen #recovery-buttons {{ height: auto; align-horizontal: right; margin-top: 1; }}
    RecoveryScreen Button {{ margin-left: 2; }}
    """

    def __init__(self, marker: Marker, backup_dir: Path) -> None:
        super().__init__()
        self.marker = marker
        self.backup_dir = backup_dir
        self.message = recovery_message(marker)

    def compose(self) -> ComposeResult:
        with Vertical(id="recovery-box"):
            yield Static(Text("An earlier clean did not finish"), id="recovery-title")
            yield Static(Text(self.message))
            with ButtonRow(id="recovery-buttons"):
                yield action_button("Dismiss (keep the backup)", "neutral", id="recovery-dismiss")
                yield action_button("Remind me next time", "confirm", id="recovery-remind")

    def on_mount(self) -> None:
        self.query_one("#recovery-remind", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recovery-dismiss":
            clear_marker(self.backup_dir)  # the snapshot stays where it is
            self.dismiss("dismissed")
        else:
            self.dismiss("remind")


class ProposalTree(Tree):
    """The proposal tree. ← jumps to the filters panel (instead of scrolling sideways)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class ReviewScreen(TwoPaneFocus, Screen[str]):
    TREE_SELECTOR = "#proposal"
    DEFAULT_CSS = two_pane_css("ReviewScreen", "#proposal")
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("w", "clean", "Clean"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
        Binding("f", "flavors", "Flavors"),
        Binding("t", "tools", "Tools"),
        Binding("q", "quit_tool", "Quit"),
        Binding("escape", "flavors", "Flavors", show=False),
        Binding("1", "criterion(0)", CRITERION_SHORT["not_installed"], show=False),
        Binding("2", "criterion(1)", CRITERION_SHORT["not_enabled"], show=False),
        Binding("3", "criterion(2)", CRITERION_SHORT["older_than"], show=False),
        Binding("4", "criterion(3)", CRITERION_SHORT["stray_copies"], show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *TREE_BINDINGS,
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: Flavor | Sequence[Flavor], *,
                 account: str | None = None, wow_check: Callable[[], list[str] | None] | None = None,
                 locker_check: Callable[[], list[str] | None] | None = None) -> None:
        """flavors is one Flavor or several (All flavors: one tree node per flavor, every account in scope).
        wow_check returns the WoW processes running (default: built per clean for the flavors in the selection)."""
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/wtf-cleaner.cfg
        self.flavors = [flavors] if isinstance(flavors, Flavor) else list(flavors)
        self.flavor = self.flavors[0]
        self.multi = len(self.flavors) > 1
        self.account = None if self.multi else (account or None)
        self.wow_check = wow_check  # None: built per clean from the flavors in the selection
        self.locker_check = locker_check or running_wtf_lockers
        self.settings = load_settings(tool_cfg)
        self.criteria = self.settings.criteria.copy()
        self.scans: list[FlavorScan] = []  # every flavor, scanned or not (error set)
        self.proposals: list[tuple[Flavor, Proposal]] = []  # one per flavor that scanned
        self.proposal: Proposal | None = None  # every flavor's items together
        self.unchecked: set[Path] = set()
        self.summary_text = ""
        self._progress_screen: CleanProgressScreen | None = None
        self._rebuild_pending = False
        self._last_filter: Widget | None = None
        self._scanning = False
        self._log_next_build = False  # the first rebuild after a scan logs proposal.built
        self._checking = False  # the running-programs check before a confirm is in a worker

    # --- layout -------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("Criteria (keys 1-4)", classes="section")
                for index, name in enumerate(CRITERIA, start=1):
                    yield Ka0sCheckbox(self._criterion_label(index, name), getattr(self.criteria, name),
                                       id=f"crit_{name}", compact=True)
                yield Label("Max age in days (Enter)", classes="section")
                yield Input(str(self.criteria.max_age_days), type="integer", id="max_age", compact=True)
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Clean", "delete", id="btn-clean")
                    yield action_button("Dry run", "simulate", id="btn-dry")
                    yield action_button("Rescan", "neutral", id="btn-rescan")
                    yield action_button("Undo last clean", "revert", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield ProposalTree(Text(self._root_name()), id="proposal")
        yield Static("", id="summary")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"WTF Cleaner · {self._scope()}"
        self.query_one("#proposal", Tree).focus()
        self._refresh_undo()
        self.action_rescan()
        self._check_recovery()

    # --- panes (←/→): TwoPaneFocus ------------------------------------------------------------------
    def first_filter(self) -> Widget:
        return self.query_one(f"#crit_{CRITERIA[0]}", Ka0sCheckbox)

    # --- recovery notice (spec A.4.5: never restores on its own) -------------------------------------
    def _check_recovery(self) -> None:
        backup_dir = resolve_backup_dir(self.settings, self.cfg.wow_path)
        marker = read_marker(backup_dir)
        if marker is None or backup_dir is None:
            return
        log_event("recovery.incomplete_clean", flavor=marker.flavor, started=marker.started,
                  snapshot=str(marker.snapshot), files=len(marker.files))
        self.app.push_screen(RecoveryScreen(marker, backup_dir), self._recovery_chosen)

    def _recovery_chosen(self, choice: str | None) -> None:
        log_event("ui.selection", screen="recovery", control="recovery", value=choice or "remind")

    # --- scanning ------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if self._checking:
            return
        self.settings = load_settings(self.tool_cfg)
        self.scans = []
        self._show_scan_progress(True)
        self.run_worker(self._scan_worker, thread=True, exclusive=True, group="scan")

    def _show_scan_progress(self, scanning: bool) -> None:
        """While scanning, the tree is replaced by a progress bar and the folder being read."""
        self._scanning = scanning
        bar = self.query_one("#scan-progress", ProgressBar)
        if scanning:
            bar.update(total=None, progress=0)
            self.query_one("#scan-label", Static).update(Text("Reading AddOns"))
        for selector in ("#scan-box", "#scan-progress", "#scan-label"):
            self.query_one(selector).display = scanning
        self.query_one("#proposal", Tree).display = not scanning
        if scanning:
            self.query_one("#btn-undo", Button).disabled = True
        else:
            self._refresh_undo()

    def _journal_dir(self) -> Path | None:
        return clean_journal_dir(self.cfg.wow_path)

    def _refresh_undo(self) -> None:
        """Undo last clean is offered only when there is a clean to undo, and never while scanning or busy."""
        busy = self._scanning or getattr(self.app, "busy", False)
        self.query_one("#btn-undo", Button).disabled = busy or latest_undoable(self._journal_dir()) is None

    def _scan_progress(self, current: int, total: int, label: str) -> None:
        self.query_one("#scan-progress", ProgressBar).update(total=total, progress=current)
        self.query_one("#scan-label", Static).update(Text(label))

    def _scan_worker(self) -> None:
        def progress(current: int, total: int, label: str) -> None:
            self.app.call_from_thread(self._scan_progress, current, total, label)

        scans = scan_flavors(self.flavors, account=self.account, progress=progress)
        if not any(s.result for s in scans):
            message = scans[0].error or "" if not self.multi else "No flavor could be scanned. " + " ".join(
                f"{s.flavor.display_name}: {s.error}" for s in scans)
            self.app.call_from_thread(self._scan_failed, message)
            return
        self.app.call_from_thread(self._scanned, scans)

    def _scan_failed(self, message: str) -> None:
        self._show_scan_progress(False)
        self.summary_text = message
        self.query_one("#summary", Static).update(Text(message))
        self.notify(message, title="Scan failed", severity="error", timeout=15)

    def _scanned(self, scans: list[FlavorScan]) -> None:
        self.scans = scans
        self._log_next_build = True
        self._show_scan_progress(False)
        self._update_criterion_labels()
        self._schedule_rebuild()
        self.query_one("#proposal", Tree).focus()

    # --- criteria -------------------------------------------------------------------------------------
    @staticmethod
    def _criterion_label(index: int, name: str, files: int | None = None) -> Text:
        text = f"{index} {CRITERION_SHORT[name]}"
        if files is not None:
            text += f" ({plural(files, 'file')})"
        return Text(text, style=CRITERION_COLORS[name])

    def _scanned_ok(self) -> list[FlavorScan]:
        return [s for s in self.scans if s.result is not None]

    def _update_criterion_labels(self) -> None:
        if not self._scanned_ok():
            return
        counts = dict.fromkeys(CRITERIA, 0)
        for flavor_scan in self._scanned_ok():
            for name, files in criterion_counts(flavor_scan.result,  # type: ignore[arg-type]
                                                max_age_days=self.criteria.max_age_days).items():
                counts[name] += files
        for index, name in enumerate(CRITERIA, start=1):
            self.query_one(f"#crit_{name}", Ka0sCheckbox).label = self._criterion_label(index, name, counts[name])

    # --- tree ------------------------------------------------------------------------------------
    def _schedule_rebuild(self) -> None:
        """Show that the list is being rebuilt, then rebuild once that has been drawn. Toggles made before the
        rebuild runs are folded into it."""
        if not self._scanned_ok():
            return
        self.query_one("#proposal", Tree).loading = True
        self.query_one("#summary", Static).update(Text("Updating the list…", style=BUSY_STYLE))
        if not self._rebuild_pending:
            self._rebuild_pending = True
            self.call_after_refresh(self._run_scheduled_rebuild)

    def _run_scheduled_rebuild(self) -> None:
        self._rebuild_pending = False
        try:
            self._rebuild()
        finally:
            self.query_one("#proposal", Tree).loading = False

    def _rebuild(self) -> None:
        if not self._scanned_ok():
            return
        # Interactive rebuilds (criterion toggles, max age) log nothing: proposal.built once per scan, and the
        # proposal.item events only for a run the user confirms (F-006).
        self.proposals = [(s.flavor, evaluate(s.result, self.criteria, log=False))  # type: ignore[arg-type]
                          for s in self._scanned_ok()]
        if self._log_next_build:
            self._log_next_build = False
            for flavor, proposal in self.proposals:
                log_proposal_built(proposal, flavor.folder)
        if self.multi:
            self.proposal = Proposal([i for _, p in self.proposals for i in p.items], self.criteria.copy(),
                                     [w for _, p in self.proposals for w in p.warnings])
        else:
            self.proposal = self.proposals[0][1]
        by_folder = {flavor.folder: proposal for flavor, proposal in self.proposals}
        tree = self.query_one("#proposal", Tree)
        tree.clear()
        tree.root.data = ("group", self.proposal.items, self._root_name())
        tree.root.set_label(self._label(tree.root.data))
        for flavor_scan in self.scans:
            if flavor_scan.result is None:  # several flavors only: say why this one is not offered
                tree.root.add_leaf(Text.assemble("  ", (flavor_scan.flavor.display_name, ACCENT),
                                                 (f"  not scanned: {flavor_scan.error}", WARNING_STYLE)))
                continue
            items = by_folder[flavor_scan.flavor.folder].items
            parent = tree.root
            if self.multi:
                data = ("group", items, flavor_scan.flavor.display_name)
                parent = tree.root.add(self._label(data), data=data, expand=True)
            self._add_accounts(parent, flavor_scan.result.account_names, items)
        tree.root.expand()
        self._update_summary()

    def _add_accounts(self, parent, account_names: tuple[str, ...], proposal_items: list[ProposalItem]) -> None:
        """account → account-wide / character → addon → files, under parent (the root or a flavor node)."""
        owners: dict[str, dict[str, list[ProposalItem]]] = {name: {} for name in account_names}
        for item in proposal_items:
            owners.setdefault(item.account, {}).setdefault(item.owner_label, []).append(item)
        for account in sorted(owners, key=str.casefold):
            account_items = [i for items in owners[account].values() for i in items]
            data = ("group", account_items, account)
            account_node = parent.add(self._label(data), data=data, expand=True)
            for owner in sorted(owners[account], key=lambda o: (o != ACCOUNT_WIDE, o.casefold())):
                items = sorted(owners[account][owner], key=lambda i: i.addon.casefold())
                data = ("group", items, owner)
                owner_node = account_node.add(self._label(data), data=data, expand=True)
                for item in items:
                    data = ("item", item)
                    item_node = owner_node.add(self._label(data), data=data)
                    for sv in item.files:
                        data = ("file", item, sv)
                        item_node.add_leaf(self._label(data), data=data)
            if not account_node.children:
                account_node.allow_expand = False  # an account with nothing to clean

    @staticmethod
    def _paths(data) -> list[Path]:
        kind = data[0]
        if kind == "file":
            return [data[2].path]
        if kind == "item":
            return [f.path for f in data[1].files]
        return [f.path for item in data[1] for f in item.files]

    def _mark(self, paths: list[Path]) -> tuple[str, str]:
        return tick_mark(paths, self.unchecked, success=theme_colour(self.app, "success"))

    @staticmethod
    def _reasons(reasons: list[str]) -> Text:
        return reasons_text(reasons)

    def _label(self, data) -> Text:
        now = time.time()
        mark = self._mark(self._paths(data))
        kind = data[0]
        if kind == "file":
            sv = data[2]
            return Text.assemble(mark, sv.name,
                                 (f"  {format_size(sv.size)} · {age_days(sv.mtime, now)}d", "dim"))
        if kind == "item":
            item = data[1]
            return Text.assemble(mark, (item.addon, "bold"), "  ", self._reasons(item.reasons),
                                 ((f"  {plural(len(item.files), 'file')} · {format_size(item.total_size)} · "
                                   f"{age_days(item.newest_mtime, now)}d"), "dim"))
        items, name = data[1], data[2]
        if not items and data is not self.query_one("#proposal", Tree).root.data:
            return Text.assemble("  ", (name, ACCENT), ("  nothing to clean", "dim"))  # an account or flavor
        return Text.assemble(mark, (name, ACCENT), (f"  {plural(len(items), 'item')}", "dim"))

    def _refresh_labels(self, node=None) -> None:
        """Relabel node's branch and its ancestors (everything a tick there can change), or the whole tree."""
        relabel_branch(self.query_one("#proposal", Tree), node, self._label)
        self._update_summary()

    def _selection(self) -> list[ProposalItem]:
        return [item for _, items in self._selection_by_flavor() for item in items]

    def _selection_by_flavor(self) -> list[tuple[Flavor, list[ProposalItem]]]:
        """The ticked files of each flavor that has any, in flavor order."""
        plan = []
        for flavor, proposal in self.proposals:
            selected = []
            for item in proposal.items:
                files = [f for f in item.files if f.path not in self.unchecked]
                if files:
                    selected.append(item.with_files(files))
            if selected:
                plan.append((flavor, selected))
        return plan

    def _update_summary(self) -> None:
        selection = self._selection()
        files = sum(len(i.files) for i in selection)
        size = sum(i.total_size for i in selection)
        # The criteria are not repeated here: the left pane shows them.
        text = f"Selected: {plural(len(selection), 'item')} · {plural(files, 'file')} · {format_size(size)}"
        if self.proposal is not None and not self.proposal.items:
            text = "Nothing to clean with the current criteria.    " + text
        if self.proposal is not None and self.proposal.warnings:
            count = len(self.proposal.warnings)
            text += f"    ⚠ {count} scan warning{'' if count == 1 else 's'} (see the log)"
        not_scanned = [s.flavor.display_name for s in self.scans if s.result is None]
        if not_scanned:
            text += f"    ⚠ not scanned: {', '.join(not_scanned)}"
        self.summary_text = text
        self.query_one("#summary", Static).update(Text(text))

    def _root_name(self) -> str:
        return ALL_FLAVORS_LABEL if self.multi else self.flavor.display_name

    def _scope(self) -> str:
        return f"{self._root_name()} · {self.account or 'all accounts'}"

    # --- actions ---------------------------------------------------------------------------------
    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Checkbox):
            focused.toggle()
            return
        if isinstance(focused, Button):  # Space activates the focused button (§A.8), never the tree
            focused.press()
            return
        if not isinstance(focused, Tree) or self._checking:  # the selection is frozen while the check runs
            return
        node = self.query_one("#proposal", Tree).cursor_node
        if node is None or node.data is None:
            return
        paths = self._paths(node.data)
        check = any(p in self.unchecked for p in paths)
        if check:
            self.unchecked.difference_update(paths)
        else:
            self.unchecked.update(paths)
        key = str(paths[0]) if node.data[0] == "file" else (
            node.data[1].key if node.data[0] == "item" else node.data[2])
        log_event("ui.item_toggled", screen="review", key=key, checked=check)
        self._refresh_labels(node)

    def action_select_all(self) -> None:
        if self._checking:
            return
        self.unchecked.clear()
        log_event("ui.selection", screen="review", control="select_all", value=True)
        self._refresh_labels()

    def action_select_none(self) -> None:
        if self._checking:
            return
        if self.proposal is not None:
            self.unchecked = {f.path for item in self.proposal.items for f in item.files}
        log_event("ui.selection", screen="review", control="select_none", value=True)
        self._refresh_labels()

    def action_criterion(self, index: int) -> None:
        if self._checking:
            return
        self.query_one(f"#crit_{CRITERIA[index]}", Checkbox).toggle()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        name = (event.checkbox.id or "").removeprefix("crit_")
        if name not in CRITERIA:
            return
        setattr(self.criteria, name, event.value)
        log_event("ui.selection", screen="review", control=f"criterion.{name}", value=event.value)
        self._schedule_rebuild()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "max_age" or self._checking:
            return
        try:
            days = int(event.value)
        except ValueError:
            days = 0
        if days < 1:
            self.notify("Max age must be a whole number of days, at least 1.", severity="warning")
            return
        self.criteria.max_age_days = days
        log_event("ui.selection", screen="review", control="max_age_days", value=days)
        self._update_criterion_labels()
        self._schedule_rebuild()
        self.query_one("#proposal", Tree).focus()

    def action_flavors(self) -> None:
        if not self.app.busy:
            self.dismiss("flavors")

    def action_tools(self) -> None:
        if not self.app.busy:
            self.dismiss("tools")

    def action_quit_tool(self) -> None:
        if not self.app.busy:
            self.dismiss("quit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {"btn-clean": self.action_clean, "btn-dry": self.action_dry_run, "btn-rescan": self.action_rescan,
                   "btn-undo": self.action_undo}
        action = actions.get(event.button.id or "")
        if action is not None:
            event.stop()
            action()

    # --- cleaning --------------------------------------------------------------------------------
    def action_clean(self) -> None:
        self._start(dry_run=False)

    def action_dry_run(self) -> None:
        self._start(dry_run=True)

    def _backup_dir_problem(self) -> str | None:
        """The saved backup folder is checked again before it is used: the file may have been edited by hand."""
        wow_path = self.cfg.wow_path
        if wow_path is None:
            return None
        return validate_output_dir(self.settings.backup_dir, WowInstall(wow_path), what="backup folder")

    def _start(self, dry_run: bool) -> None:
        if self.proposal is None or self.app.busy or self._checking:
            return
        log_event("ui.selection", screen="review", control="dry_run" if dry_run else "clean", value=True)
        self.settings = load_settings(self.tool_cfg)
        problem = self._backup_dir_problem()
        if problem:
            self.notify(f"{problem} Fix the folder in settings (s).", title="Backup folder not allowed",
                        severity="error", timeout=15)
            return
        plan = self._selection_by_flavor()
        if not plan:
            self.notify("Nothing is selected.")
            return
        check = self.wow_check or wow_check_for([flavor for flavor, _ in plan])
        locker_check = None if dry_run else self.locker_check
        self._run_preflight(check, locker_check, lambda running, lockers: self._after_preflight(dry_run, running,
                                                                                               lockers))

    def _after_preflight(self, dry_run: bool, running: list[str] | None, lockers: list[str] | None) -> None:
        # The selection is frozen while the check runs; it is read again here so the confirm and the clean always
        # use what the tree shows.
        plan = self._selection_by_flavor()
        if not plan:
            self.notify("Nothing is selected.")
            return
        self._show_confirm(plan, dry_run, running, lockers)

    # --- running-programs check (PowerShell/tasklist can take seconds: never on the UI thread) ----------------
    def _run_preflight(self, check: Callable[[], list[str] | None],
                       locker_check: Callable[[], list[str] | None] | None,
                       then: Callable[[list[str] | None, list[str] | None], None]) -> None:
        self._set_checking(True)
        self.query_one("#summary", Static).update(Text("Checking for running programs…", style=BUSY_STYLE))
        self.run_worker(lambda: self._preflight_worker(check, locker_check, then), thread=True, group="preflight")

    def _set_checking(self, checking: bool) -> None:
        """While the check runs the selection cannot change: the criteria and max age are disabled, and the
        tick/untick keys are ignored."""
        self._checking = checking
        if not self.is_attached:
            return
        for widget in [*self.query(Ka0sCheckbox), *self.query("#max_age")]:
            widget.disabled = checking

    def _preflight_worker(self, check: Callable[[], list[str] | None],
                          locker_check: Callable[[], list[str] | None] | None,
                          then: Callable[[list[str] | None, list[str] | None], None]) -> None:
        running = lockers = None
        try:
            running = check()  # every flavor in the selection, one process listing
            lockers = locker_check() if locker_check is not None else None
        except Exception as exc:  # noqa: BLE001 - a failed check is "unknown", as when PowerShell is missing
            log_exception("preflight", exc)
        self.app.call_from_thread(self._preflight_done, running, lockers, then)

    def _preflight_done(self, running: list[str] | None, lockers: list[str] | None,
                        then: Callable[[list[str] | None, list[str] | None], None]) -> None:
        self._set_checking(False)
        if not self.is_attached or self.app.screen is not self:
            return  # the user left the screen while the check ran
        self._update_summary()
        then(running, lockers)

    def _show_confirm(self, plan: list[tuple[Flavor, list[ProposalItem]]], dry_run: bool,
                      running: list[str] | None, lockers: list[str] | None) -> None:
        selection = [item for _, items in plan for item in items]
        if running:
            log_event("wow.running_warning", executables=running)
        backup = self.settings.backup_before_delete
        backup_dir = resolve_backup_dir(self.settings, self.cfg.wow_path)
        lines = [self._counts(selection) + "."]
        if self.multi:
            lines[0] = f"{self._counts(selection)} in {len(plan)} flavor{'' if len(plan) == 1 else 's'}:"
            lines += [f"  {flavor.display_name}: {self._counts(items)}" for flavor, items in plan]
        alerts: list[str] = []
        if backup:
            lines.append(f"The files to clean are zipped to: {backup_dir / CLEANED_SUBDIR if backup_dir else '?'}")
        else:
            alerts.append("The files to clean will not be zipped (turned off in settings).")
        keep = self.cfg.keep_backups
        kept = (f"{'the newest ' + str(keep) if keep > 0 else 'all'} of {'each' if self.multi else 'this'} "
                "flavor are kept")
        if not dry_run:
            what = "Each flavor's whole WTF folder is backed up first" if self.multi else \
                "The whole WTF folder is backed up first"
            lines.append(f"{what} to: {backup_dir / SNAPSHOT_SUBDIR if backup_dir else '?'} ({kept})")
        if dry_run:
            lines.append(f"DRY RUN: a dryrun-... zip of the files is written ({kept}), nothing is deleted."
                         if backup else "DRY RUN: nothing will be written or deleted.")
        else:
            lines.append("A run journal is written, so Undo last clean (z) can put the files back.")
        if running:
            alerts.append(f"WoW appears to be running ({', '.join(running)}). Close it first: WoW rewrites "
                          "SavedVariables when you log out.")
        if lockers:
            log_event("locker.running_warning", executables=lockers)
            alerts.append(locker_warning(lockers))
        title = "Simulate this clean?" if dry_run else "Back up and delete these files?"
        self.app.push_screen(ConfirmScreen(title, "\n".join(lines), tuple(alerts), default_yes=dry_run),
                             lambda ok: self._confirmed(ok, plan, backup, backup_dir, dry_run))

    @staticmethod
    def _counts(items: list[ProposalItem]) -> str:
        files = sum(len(i.files) for i in items)
        return (f"{plural(len(items), 'addon group')}, {plural(files, 'file')}, "
                f"{format_size(sum(i.total_size for i in items))}")

    def _confirmed(self, ok: bool | None, plan: list[tuple[Flavor, list[ProposalItem]]], backup: bool,
                   backup_dir: Path | None, dry_run: bool) -> None:
        log_event("ui.selection", screen="confirm", control="confirm", value=bool(ok), dry_run=dry_run)
        if not ok:
            return
        log_proposal_items([item for _, items in plan for item in items], dry_run=dry_run)
        self.app.busy = True
        self._refresh_undo()
        progress_screen = CleanProgressScreen(dry_run)
        self._progress_screen = progress_screen
        self.app.push_screen(progress_screen)
        self.run_worker(lambda: self._clean_worker(plan, backup, backup_dir, dry_run, progress_screen),
                        thread=True, exclusive=True, group="clean")

    def _clean_worker(self, plan: list[tuple[Flavor, list[ProposalItem]]], backup: bool, backup_dir: Path | None,
                      dry_run: bool, progress_screen: CleanProgressScreen) -> None:
        # Runs in a worker thread: the progress screen is only ever touched on the UI thread.
        def progress(*args) -> None:
            self.app.call_from_thread(progress_screen.update_progress, *args)

        def on_flavor(flavor: Flavor, index: int, count: int) -> None:
            if self.multi:
                self.app.call_from_thread(progress_screen.set_flavor,
                                          f"{flavor.display_name} ({index + 1}/{count})")

        try:
            with activity.running():
                result = execute_flavors(plan, dry_run=dry_run, backup=backup, backup_dir=backup_dir,
                                         account=self.account, keep_backups=self.cfg.keep_backups,
                                         progress=progress, on_flavor=on_flavor, journal_dir=self._journal_dir(),
                                         keep_journals=self.cfg.keep_journals)
        except Exception as exc:  # noqa: BLE001 - anything unexpected is shown and logged, never a crash
            log_exception("clean", exc)
            self.app.call_from_thread(self._clean_crashed, exc, dry_run, backup_dir if backup else None)
            return
        stopped = result.stopped
        if stopped is not None and isinstance(stopped.error, CleanError):
            log_exception("clean", stopped.error)
        if stopped is not None and not result.done:
            self.app.call_from_thread(self._clean_failed, stopped.error, result)
            return
        self.app.call_from_thread(self._cleaned, result)

    def _close_progress(self) -> None:
        progress_screen, self._progress_screen = self._progress_screen, None
        if progress_screen is not None and self.app.screen is progress_screen:
            self.app.pop_screen()

    def _clean_failed(self, exc: Exception, result: MultiCleanResult | None = None) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_undo()
        message = f"Nothing was deleted: {exc}" if nothing_deleted(exc) else str(exc)
        if self.multi and result is not None and result.stopped is not None:
            message = f"{result.stopped.flavor.display_name}: {message}"
            if result.not_started:
                message += f"\nNot started: {', '.join(r.flavor.display_name for r in result.not_started)}."
        self.notify(message, title="Clean stopped", severity="error", timeout=20)

    def _clean_crashed(self, exc: Exception, dry_run: bool, backup_dir: Path | None) -> None:
        """An error execute_flavors() does not handle. Unlike _clean_failed, nothing is known about what was
        deleted, so the message never claims "Nothing was deleted" for a real clean."""
        self.app.busy = False
        self._close_progress()
        self._refresh_undo()
        what = "simulation" if dry_run else "clean"
        message = f"The {what} stopped unexpectedly: {type(exc).__name__}: {exc}"
        if dry_run:
            message += "\nNothing was deleted (it was a dry run)."
        else:
            restore = "Undo last clean (z)"
            if backup_dir is not None:
                restore += f" or the WTF backup in {backup_dir / SNAPSHOT_SUBDIR}"
            message += f"\nCheck the result with Rescan (r). If files are missing, {restore} can put them back."
        self.notify(message, title="Clean stopped", severity="error", timeout=30)

    def _cleaned(self, result: MultiCleanResult) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_undo()
        self.unchecked.clear()
        stopped = result.stopped
        if stopped is not None:  # a later flavor stopped: the earlier ones are done
            self.notify(f"{stopped.flavor.display_name}: {stopped.error}", title="Clean stopped",
                        severity="error", timeout=20)
        if self.multi:
            self.app.push_screen(ResultScreen(result), self._after_result)
        else:
            self.app.push_screen(ResultScreen(result.runs[0].result, self.flavor), self._after_result)  # type: ignore[arg-type]

    def _after_result(self, choice: str | None) -> None:
        if choice in ("flavors", "tools"):
            self.dismiss(choice)
        elif choice == "quit":
            self.dismiss("quit")
        else:
            self.action_rescan()

    # --- undo last clean --------------------------------------------------------------------------
    def action_undo(self) -> None:
        if self.app.busy or self._scanning or self._checking:
            return
        log_event("ui.selection", screen="review", control="undo", value=True)
        path = latest_undoable(self._journal_dir())
        if path is None:
            self.notify("Nothing to undo.")
            self._refresh_undo()
            return
        try:
            journal = read_journal(path)
        except (OSError, ValueError) as exc:
            self.notify(f"The journal could not be read: {exc}", severity="error")
            return
        folders = [str(f) for f in journal.header.get("flavors") or []]
        names = ", ".join(flavor_name(folder) for folder in folders) or "unknown flavors"
        files = len(journal.entries)
        body = (f"Put back {files} file{'' if files == 1 else 's'} deleted from {names}? Each comes back from the "
                "cleaned-files zip, or from the WTF backup when there is no zip. A file that is back at its path "
                "is left alone; nothing is overwritten.")
        title = f"Undo the clean from {friendly_stamp(journal.started)}?"
        check = self.wow_check or wow_check_for(folders)
        self._run_preflight(check, None, lambda running, _: self._show_undo_confirm(path, title, body, running))

    def _show_undo_confirm(self, path: Path, title: str, body: str, running: list[str] | None) -> None:
        alerts: list[str] = []
        if running:
            log_event("wow.running_warning", executables=running)
            alerts.append(f"WoW appears to be running ({', '.join(running)}). Close it first: WoW rewrites "
                          "SavedVariables when you log out.")
        self.app.push_screen(ConfirmScreen(title, body, tuple(alerts), default_yes=False),
                             lambda ok: self._undo_confirmed(ok, path))

    def _undo_confirmed(self, ok: bool | None, path: Path) -> None:
        log_event("ui.selection", screen="confirm", control="undo_confirm", value=bool(ok))
        wow_root = self.cfg.wow_path
        if not ok or wow_root is None:
            return
        self.app.busy = True
        self._refresh_undo()
        progress_screen = CleanProgressScreen(False, first_stage="undo")
        self._progress_screen = progress_screen
        self.app.push_screen(progress_screen)
        self.run_worker(lambda: self._undo_worker(path, wow_root, progress_screen), thread=True, exclusive=True,
                        group="clean")

    def _undo_worker(self, path: Path, wow_root: Path, progress_screen: CleanProgressScreen) -> None:
        def progress(*args) -> None:
            self.app.call_from_thread(progress_screen.update_progress, *args)

        try:
            with activity.running():
                result = undo_clean(path, wow_root=wow_root, progress=progress)
        except Exception as exc:  # noqa: BLE001 - e.g. an unreadable journal: shown, never a crash
            log_exception("clean.undo", exc)
            self.app.call_from_thread(self._undo_failed, exc)
            return
        self.app.call_from_thread(self._undone, result)

    def _undo_failed(self, exc: Exception) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_undo()
        self.notify(f"{type(exc).__name__}: {exc}", title="Undo stopped", severity="error", timeout=20)

    def _undone(self, result: UndoResult) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_undo()
        self.app.push_screen(ResultScreen(result), self._after_result)
