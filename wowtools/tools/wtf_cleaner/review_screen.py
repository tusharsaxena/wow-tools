"""Review the proposal as a tree, tick/untick, toggle criteria, then clean or dry run (with a progress screen)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Sequence, Union

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, ProgressBar, Static, Tree

from wowtools.core.backup import BackupError
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import ACCOUNT_WIDE, Flavor
from wowtools.core.process import running_wtf_lockers, wow_check_for
from wowtools.tools.wtf_cleaner.cleaner import CLEANED_SUBDIR, CleanError
from wowtools.tools.wtf_cleaner.multi import (FlavorScan, MultiCleanResult, execute_flavors, nothing_deleted,
                                              scan_flavors)
from wowtools.tools.wtf_cleaner.report import (CRITERION_COLORS, CRITERION_SHORT, STAGE_TITLES, age_days,
                                               format_size, locker_warning)
from wowtools.tools.wtf_cleaner.result_screen import SUCCESS_FALLBACK, ResultScreen, reasons_text
from wowtools.tools.wtf_cleaner.rules import CRITERIA, Proposal, ProposalItem, criterion_counts, evaluate
from wowtools.tools.wtf_cleaner.safety import SNAPSHOT_SUBDIR, Marker, clear_marker, read_marker, recovery_message
from wowtools.tools.wtf_cleaner.settings import load_settings, resolve_backup_dir
from wowtools.ui.branding import BrandBar
from wowtools.ui.widgets import CHECK_OFF, CHECK_ON, NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button

ACCENT = "bold #5CC8FF"
WARNING_STYLE = "#E8B04B"
ALL_FLAVORS_LABEL = "All flavors"
__all__ = ["CleanProgressScreen", "ConfirmScreen", "RecoveryScreen", "ResultScreen", "ReviewScreen"]
NAV_HINT = ("↑↓/Tab move · ←→ panes and buttons · Space tick · Enter/Space press · 1-4 criteria · c clean · "
            "y dry run · r rescan · t tools")


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen #confirm-box { width: 80; height: auto; border: thick $accent; background: $panel; padding: 1 2; }
    ConfirmScreen #confirm-title { color: $accent; text-style: bold; margin-bottom: 1; }
    ConfirmScreen #confirm-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    ConfirmScreen Button { margin-left: 2; }
    """
    BINDINGS = [Binding("y", "answer(True)", "Yes"), Binding("n,escape", "answer(False)", "No"), *NAV_BINDINGS]

    def __init__(self, title: str, body: str, alerts: tuple[str, ...] = (), *, default_yes: bool = False) -> None:
        super().__init__()
        self.default_yes = default_yes
        self.title_text = title
        self.alerts = alerts
        self.body_text = "\n".join([body, *alerts]) if alerts else body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(Text(self.title_text), id="confirm-title")
            body = Text(self.body_text)
            for alert in self.alerts:
                body.highlight_words([alert], style="bold #E5534B")
            yield Static(body)
            with ButtonRow(id="confirm-buttons"):
                yield action_button("Yes (y)", "confirm", id="yes")
                yield action_button("No (n)", "neutral", id="no")
            yield NavHint("←→ choose · Enter/Space press · y yes · n/Esc no")

    def on_mount(self) -> None:
        self.query_one("#yes" if self.default_yes else "#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class CleanProgressScreen(ModalScreen[None]):
    """Shown while a clean or dry run runs: the stage, a progress bar and the current file."""

    DEFAULT_CSS = """
    CleanProgressScreen { align: center middle; }
    CleanProgressScreen #clean-box { width: 80; height: auto; border: thick $accent; background: $panel;
                                     padding: 1 2; }
    CleanProgressScreen #clean-stage { color: $accent; text-style: bold; margin-bottom: 1; }
    CleanProgressScreen #clean-progress { width: 1fr; }
    CleanProgressScreen #clean-file { color: $text-muted; margin-top: 1; height: 2; overflow: hidden hidden; }
    """

    def __init__(self, dry_run: bool) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.stage = ""
        self.flavor_label = ""  # set while cleaning several flavors: the stage title names the flavor

    def compose(self) -> ComposeResult:
        with Vertical(id="clean-box"):
            yield Static(Text(self.stage_title("check")), id="clean-stage")
            yield ProgressBar(id="clean-progress", show_eta=False)
            yield Static("", id="clean-file")

    def stage_title(self, stage: str) -> str:
        title = "Simulating" if stage == "delete" and self.dry_run else STAGE_TITLES.get(stage, stage)
        return f"{self.flavor_label}: {title}" if self.flavor_label else title

    def set_flavor(self, label: str) -> None:
        self.flavor_label = label

    def update_progress(self, stage: str, current: int, total: int, detail: str = "") -> None:
        self.stage = stage
        self.query_one("#clean-stage", Static).update(Text(self.stage_title(stage)))
        # A total of 0 means "not known yet" (listing a folder): the bar runs as indeterminate.
        self.query_one("#clean-progress", ProgressBar).update(total=total if total > 0 else None, progress=current)
        self.query_one("#clean-file", Static).update(Text(detail))


class RecoveryScreen(ModalScreen[str]):
    """An earlier clean did not finish: say where its WTF backup is. Never restores anything itself."""

    DEFAULT_CSS = """
    RecoveryScreen { align: center middle; }
    RecoveryScreen #recovery-box { width: 90; height: auto; border: thick $warning; background: $panel;
                                   padding: 1 2; }
    RecoveryScreen #recovery-title { color: $warning; text-style: bold; margin-bottom: 1; }
    RecoveryScreen #recovery-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    RecoveryScreen Button { margin-left: 2; }
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

    BINDINGS = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class ReviewScreen(Screen[str]):
    DEFAULT_CSS = """
    ReviewScreen #body { height: 1fr; }
    ReviewScreen #filters { width: 46; padding: 1; border-right: solid $primary; }
    ReviewScreen #actions { margin-top: 1; }
    ReviewScreen #actions Button { min-width: 0; width: auto; margin-right: 1; }
    ReviewScreen .section { color: $accent; text-style: bold; margin: 1 0 0 0; }
    ReviewScreen #proposal { width: 1fr; padding: 0 1; }
    ReviewScreen #scan-box { width: 1fr; height: auto; padding: 1 2; }
    ReviewScreen #scan-progress { width: 1fr; }
    ReviewScreen #scan-label { color: $text-muted; margin-top: 1; }
    ReviewScreen #summary { height: auto; padding: 0 1; background: $surface; }
    """
    BINDINGS = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("c", "clean", "Clean"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("f", "flavors", "Flavors"),
        Binding("t", "tools", "Tools"),
        Binding("q", "quit_tool", "Quit"),
        Binding("1", "criterion(0)", CRITERION_SHORT["not_installed"], show=False),
        Binding("2", "criterion(1)", CRITERION_SHORT["not_enabled"], show=False),
        Binding("3", "criterion(2)", CRITERION_SHORT["older_than"], show=False),
        Binding("4", "criterion(3)", CRITERION_SHORT["stray_copies"], show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: Union[Flavor, Sequence[Flavor]], *,
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

    # --- layout -------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("Criteria (keys 1-4)", classes="section")
                for index, name in enumerate(CRITERIA, start=1):
                    yield Ka0sCheckbox(self._criterion_label(index, name), getattr(self.criteria, name),
                                       id=f"crit_{name}")
                yield Label("Max age in days (Enter)", classes="section")
                yield Input(str(self.criteria.max_age_days), type="integer", id="max_age")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Clean", "delete", id="btn-clean")
                    yield action_button("Dry run", "simulate", id="btn-dry")
                    yield action_button("Rescan", "neutral", id="btn-rescan")
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
        self.action_rescan()
        self._check_recovery()

    # --- panes (←/→) --------------------------------------------------------------------------------
    def on_descendant_focus(self, event) -> None:
        widget = event.widget
        if any(ancestor.id == "filters" for ancestor in widget.ancestors):
            self._last_filter = widget

    def action_focus_filters(self) -> None:
        focused = self.focused
        if focused is not None and any(a.id == "filters" for a in focused.ancestors):
            return  # already in the filters panel
        target = self._last_filter
        if target is None or not target.is_attached or not target.focusable:
            target = self.query_one(f"#crit_{CRITERIA[0]}", Ka0sCheckbox)
        target.focus()

    def action_focus_tree(self) -> None:
        tree = self.query_one("#proposal", Tree)
        if tree.display and self.focused is not tree:
            tree.focus()

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
        self.settings = load_settings(self.tool_cfg)
        self.scans = []
        self._show_scan_progress(True)
        self.run_worker(self._scan_worker, thread=True, exclusive=True, group="scan")

    def _show_scan_progress(self, scanning: bool) -> None:
        """While scanning, the tree is replaced by a progress bar and the folder being read."""
        bar = self.query_one("#scan-progress", ProgressBar)
        if scanning:
            bar.update(total=None, progress=0)
            self.query_one("#scan-label", Static).update(Text("Reading AddOns"))
        for selector in ("#scan-box", "#scan-progress", "#scan-label"):
            self.query_one(selector).display = scanning
        self.query_one("#proposal", Tree).display = not scanning

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
        self._show_scan_progress(False)
        self._update_criterion_labels()
        self._schedule_rebuild()
        self.query_one("#proposal", Tree).focus()

    # --- criteria -------------------------------------------------------------------------------------
    @staticmethod
    def _criterion_label(index: int, name: str, files: int | None = None) -> Text:
        text = f"{index} {CRITERION_SHORT[name]}"
        if files is not None:
            text += f" ({files} files)"
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
        self.query_one("#summary", Static).update(Text("Updating the list…", style="bold #E8B04B"))
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
        self.proposals = [(s.flavor, evaluate(s.result, self.criteria)) for s in self._scanned_ok()]  # type: ignore[arg-type]
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
        unchecked = sum(1 for p in paths if p in self.unchecked)
        if paths and unchecked == len(paths):
            return f"{CHECK_OFF} ", "dim"
        if unchecked:
            return "◩ ", "bold"
        try:
            success = self.app.current_theme.success or SUCCESS_FALLBACK
        except Exception:  # noqa: BLE001 - no theme yet: use the Ka0s colour
            success = SUCCESS_FALLBACK
        return f"{CHECK_ON} ", f"bold {success}"

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
                                 (f"  {len(item.files)} files · {format_size(item.total_size)} · "
                                  f"{age_days(item.newest_mtime, now)}d", "dim"))
        items, name = data[1], data[2]
        if not items and data is not self.query_one("#proposal", Tree).root.data:
            return Text.assemble("  ", (name, ACCENT), ("  nothing to clean", "dim"))  # an account or flavor
        return Text.assemble(mark, (name, ACCENT), (f"  {len(items)} items", "dim"))

    def _refresh_labels(self, node=None) -> None:
        """Relabel node's branch and its ancestors (everything a tick there can change), or the whole tree."""
        tree = self.query_one("#proposal", Tree)
        if node is not None:
            parent = node.parent
            while parent is not None:
                if parent.data is not None:
                    parent.set_label(self._label(parent.data))
                parent = parent.parent
        stack = [node or tree.root]
        while stack:
            node = stack.pop()
            if node.data is not None:
                node.set_label(self._label(node.data))
            stack.extend(node.children)
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
        text = (f"Selected: {len(selection)} items · {files} files · {format_size(size)}    "
                f"Criteria: {self.criteria.describe()}")
        if self.proposal is not None and not self.proposal.items:
            text = "Nothing to clean with the current criteria.    " + text
        if self.proposal is not None and self.proposal.warnings:
            text += f"    ⚠ {len(self.proposal.warnings)} scan warnings (see the log)"
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
        if not isinstance(focused, Tree):
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
        self.unchecked.clear()
        log_event("ui.selection", screen="review", control="select_all", value=True)
        self._refresh_labels()

    def action_select_none(self) -> None:
        if self.proposal is not None:
            self.unchecked = {f.path for item in self.proposal.items for f in item.files}
        log_event("ui.selection", screen="review", control="select_none", value=True)
        self._refresh_labels()

    def action_criterion(self, index: int) -> None:
        self.query_one(f"#crit_{CRITERIA[index]}", Checkbox).toggle()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        name = (event.checkbox.id or "").removeprefix("crit_")
        if name not in CRITERIA:
            return
        setattr(self.criteria, name, event.value)
        log_event("ui.selection", screen="review", control=f"criterion.{name}", value=event.value)
        self._schedule_rebuild()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "max_age":
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
        actions = {"btn-clean": self.action_clean, "btn-dry": self.action_dry_run, "btn-rescan": self.action_rescan}
        action = actions.get(event.button.id or "")
        if action is not None:
            event.stop()
            action()

    # --- cleaning --------------------------------------------------------------------------------
    def action_clean(self) -> None:
        self._start(dry_run=False)

    def action_dry_run(self) -> None:
        self._start(dry_run=True)

    def _start(self, dry_run: bool) -> None:
        if self.proposal is None or self.app.busy:
            return
        log_event("ui.selection", screen="review", control="dry_run" if dry_run else "clean", value=True)
        plan = self._selection_by_flavor()
        if not plan:
            self.notify("Nothing is selected.")
            return
        selection = [item for _, items in plan for item in items]
        check = self.wow_check or wow_check_for([flavor for flavor, _ in plan])
        running = check()  # every flavor in the selection, one process listing
        if running:
            log_event("wow.running_warning", executables=running)
        self.settings = load_settings(self.tool_cfg)
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
        if not dry_run:
            what = "Each flavor's whole WTF folder is backed up first" if self.multi else \
                "The whole WTF folder is backed up first"
            lines.append(f"{what} to: {backup_dir / SNAPSHOT_SUBDIR if backup_dir else '?'} "
                         f"(the newest {self.settings.keep_backups} of {'each' if self.multi else 'this'} "
                         f"flavor are kept)")
        if dry_run:
            lines.append(("DRY RUN: the cleaned-files zip is written, nothing is deleted." if backup
                          else "DRY RUN: nothing will be written or deleted."))
        if running:
            alerts.append(f"WoW appears to be running ({', '.join(running)}). Close it first: WoW rewrites "
                          "SavedVariables when you log out.")
        lockers = None if dry_run else self.locker_check()
        if lockers:
            log_event("locker.running_warning", executables=lockers)
            alerts.append(locker_warning(lockers))
        title = "Simulate this clean?" if dry_run else "Back up and delete these files?"
        self.app.push_screen(ConfirmScreen(title, "\n".join(lines), tuple(alerts), default_yes=dry_run),
                             lambda ok: self._confirmed(ok, plan, backup, backup_dir, dry_run))

    @staticmethod
    def _counts(items: list[ProposalItem]) -> str:
        files = sum(len(i.files) for i in items)
        return f"{len(items)} addon groups, {files} files, {format_size(sum(i.total_size for i in items))}"

    def _confirmed(self, ok: bool | None, plan: list[tuple[Flavor, list[ProposalItem]]], backup: bool,
                   backup_dir: Path | None, dry_run: bool) -> None:
        log_event("ui.selection", screen="confirm", control="confirm", value=bool(ok), dry_run=dry_run)
        if not ok:
            return
        self.app.busy = True
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

        result = execute_flavors(plan, dry_run=dry_run, backup=backup, backup_dir=backup_dir,
                                 account=self.account, keep_backups=self.settings.keep_backups,
                                 progress=progress, on_flavor=on_flavor)
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
        message = f"Nothing was deleted: {exc}" if nothing_deleted(exc) else str(exc)
        if self.multi and result is not None and result.stopped is not None:
            message = f"{result.stopped.flavor.display_name}: {message}"
            if result.not_started:
                message += f"\nNot started: {', '.join(r.flavor.display_name for r in result.not_started)}."
        self.notify(message, title="Clean stopped", severity="error", timeout=20)

    def _cleaned(self, result: MultiCleanResult) -> None:
        self.app.busy = False
        self._close_progress()
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
