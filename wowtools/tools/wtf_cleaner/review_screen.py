"""Review the proposal as a tree, tick/untick, toggle criteria, then clean or dry run (with a progress screen)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, ProgressBar, Static, Tree

from wowtools.core.backup import BackupError
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import ACCOUNT_WIDE, Flavor
from wowtools.core.process import wow_check_for
from wowtools.tools.wtf_cleaner.cleaner import CleanError, CleanResult, execute
from wowtools.tools.wtf_cleaner.report import (CRITERION_COLORS, CRITERION_SHORT, age_days, format_result_text,
                                               format_size)
from wowtools.tools.wtf_cleaner.rules import CRITERIA, ProposalItem, criterion_counts, evaluate
from wowtools.tools.wtf_cleaner.safety import Marker, clear_marker, read_marker, recovery_message
from wowtools.tools.wtf_cleaner.scanner import ScanError, ScanResult, scan
from wowtools.tools.wtf_cleaner.settings import load_settings, resolve_backup_dir
from wowtools.ui.branding import BrandBar
from wowtools.ui.widgets import CHECK_OFF, CHECK_ON, NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint

ACCENT = "bold #5CC8FF"
SUCCESS_FALLBACK = "#4CC38A"
NAV_HINT = ("↑↓/Tab move · ←→ buttons · Space tick · Enter press · 1-4 criteria · c clean · y dry run · "
            "r rescan")
STAGE_TITLES = {"snapshot": "Taking safety snapshot", "backup": "Writing backup", "verify": "Verifying backup",
                "delete": "Deleting"}


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen #confirm-box { width: 80; height: auto; border: thick $accent; background: $panel; padding: 1 2; }
    ConfirmScreen #confirm-title { color: $accent; text-style: bold; margin-bottom: 1; }
    ConfirmScreen #confirm-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    ConfirmScreen Button { margin-left: 2; }
    """
    BINDINGS = [Binding("y", "answer(True)", "Yes"), Binding("n,escape", "answer(False)", "No")]

    def __init__(self, title: str, body: str, alerts: tuple[str, ...] = ()) -> None:
        super().__init__()
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
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes (y)", variant="primary", id="yes")
                yield Button("No (n)", id="no")

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
    CleanProgressScreen #clean-file { color: $text-muted; margin-top: 1; }
    """

    def __init__(self, dry_run: bool) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.stage = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="clean-box"):
            yield Static(Text("Simulating" if self.dry_run else "Starting"), id="clean-stage")
            yield ProgressBar(id="clean-progress", show_eta=False)
            yield Static("", id="clean-file")

    def stage_title(self, stage: str) -> str:
        if stage == "delete" and self.dry_run:
            return "Simulating"
        return STAGE_TITLES.get(stage, stage)

    def update_progress(self, stage: str, current: int, total: int, detail: str = "") -> None:
        self.stage = stage
        self.query_one("#clean-stage", Static).update(Text(self.stage_title(stage)))
        self.query_one("#clean-progress", ProgressBar).update(total=total, progress=current)
        self.query_one("#clean-file", Static).update(Text(detail))


class RecoveryScreen(ModalScreen[str]):
    """An earlier clean did not finish: say where its safety snapshot is. Never restores anything itself."""

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
                yield Button("Dismiss (keep the snapshot)", id="recovery-dismiss")
                yield Button("Remind me next time", variant="primary", id="recovery-remind")

    def on_mount(self) -> None:
        self.query_one("#recovery-remind", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recovery-dismiss":
            clear_marker(self.backup_dir)  # the snapshot stays where it is
            self.dismiss("dismissed")
        else:
            self.dismiss("remind")


class ResultScreen(Screen[str]):
    DEFAULT_CSS = """
    ResultScreen #result { padding: 1 2; }
    ResultScreen .buttons { height: auto; padding: 0 2; }
    ResultScreen Button { margin-right: 2; }
    """
    BINDINGS = [Binding("r", "choose('review')", "Rescan"), Binding("f", "choose('flavors')", "Flavors"),
                Binding("q", "choose('quit')", "Quit")]

    def __init__(self, result: CleanResult) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="result"):
            yield Static(Text(format_result_text(self.result)))
        with Horizontal(classes="buttons"):
            yield Button("Rescan (r)", variant="primary", id="review")
            yield Button("Other flavor (f)", id="flavors")
            yield Button("Quit (q)", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "WTF Cleaner · dry run result" if self.result.dry_run else "WTF Cleaner · result"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "quit")

    def action_choose(self, choice: str) -> None:
        log_event("ui.selection", screen="result", control="next", value=choice)
        self.dismiss(choice)


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
        Binding("q", "quit_tool", "Quit"),
        Binding("1", "criterion(0)", CRITERION_SHORT["not_installed"], show=False),
        Binding("2", "criterion(1)", CRITERION_SHORT["not_enabled"], show=False),
        Binding("3", "criterion(2)", CRITERION_SHORT["older_than"], show=False),
        Binding("4", "criterion(3)", CRITERION_SHORT["stray_copies"], show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, flavor: Flavor, *, account: str | None = None,
                 wow_check: Callable[[], list[str] | None] | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavor = flavor
        self.account = account or None
        self.wow_check = wow_check or wow_check_for(flavor)
        self.settings = load_settings(cfg)
        self.criteria = self.settings.criteria.copy()
        self.scan_result: ScanResult | None = None
        self.proposal = None
        self.unchecked: set[Path] = set()
        self.summary_text = ""
        self._progress_screen: CleanProgressScreen | None = None

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
                with ButtonRow(id="actions"):
                    yield Button("Clean", variant="error", id="btn-clean")
                    yield Button("Dry run", variant="primary", id="btn-dry")
                    yield Button("Rescan", id="btn-rescan")
                yield NavHint(NAV_HINT)
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield Tree(Text(self.flavor.display_name), id="proposal")
        yield Static("", id="summary")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"WTF Cleaner · {self._scope()}"
        self.query_one("#proposal", Tree).focus()
        self.action_rescan()
        self._check_recovery()

    # --- recovery notice (spec A.4.5: never restores on its own) -------------------------------------
    def _check_recovery(self) -> None:
        backup_dir = resolve_backup_dir(self.cfg, self.settings)
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
        self.settings = load_settings(self.cfg)
        self.scan_result = None
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

        try:
            result = scan(self.flavor, account=self.account, progress=progress)
        except ScanError as exc:
            log_exception("scan", exc)
            self.app.call_from_thread(self._scan_failed, str(exc))
            return
        self.app.call_from_thread(self._scanned, result)

    def _scan_failed(self, message: str) -> None:
        self._show_scan_progress(False)
        self.summary_text = message
        self.query_one("#summary", Static).update(Text(message))
        self.notify(message, title="Scan failed", severity="error", timeout=15)

    def _scanned(self, result: ScanResult) -> None:
        self.scan_result = result
        self._show_scan_progress(False)
        self._update_criterion_labels()
        self._rebuild()
        self.query_one("#proposal", Tree).focus()

    # --- criteria -------------------------------------------------------------------------------------
    @staticmethod
    def _criterion_label(index: int, name: str, files: int | None = None) -> Text:
        text = f"{index} {CRITERION_SHORT[name]}"
        if files is not None:
            text += f" ({files} files)"
        return Text(text, style=CRITERION_COLORS[name])

    def _update_criterion_labels(self) -> None:
        if self.scan_result is None:
            return
        counts = criterion_counts(self.scan_result, max_age_days=self.criteria.max_age_days)
        for index, name in enumerate(CRITERIA, start=1):
            self.query_one(f"#crit_{name}", Ka0sCheckbox).label = self._criterion_label(index, name, counts[name])

    # --- tree ------------------------------------------------------------------------------------
    def _rebuild(self) -> None:
        if self.scan_result is None:
            return
        self.proposal = evaluate(self.scan_result, self.criteria)
        tree = self.query_one("#proposal", Tree)
        tree.clear()
        tree.root.data = ("group", self.proposal.items, self.flavor.display_name)
        owners: dict[str, dict[str, list[ProposalItem]]] = {}
        for item in self.proposal.items:
            owners.setdefault(item.account, {}).setdefault(item.owner_label, []).append(item)
        for account in sorted(owners, key=str.casefold):
            account_items = [i for items in owners[account].values() for i in items]
            account_node = tree.root.add("", data=("group", account_items, account), expand=True)
            for owner in sorted(owners[account], key=lambda o: (o != ACCOUNT_WIDE, o.casefold())):
                items = sorted(owners[account][owner], key=lambda i: i.addon.casefold())
                owner_node = account_node.add("", data=("group", items, owner), expand=True)
                for item in items:
                    item_node = owner_node.add("", data=("item", item))
                    for sv in item.files:
                        item_node.add_leaf("", data=("file", item, sv))
        tree.root.expand()
        self._refresh_labels()

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
        text = Text()
        for index, reason in enumerate(reasons):
            if index:
                text.append(", ")
            text.append(reason, style=CRITERION_COLORS.get(reason, ""))
        return text

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
        return Text.assemble(mark, (name, ACCENT), (f"  {len(items)} items", "dim"))

    def _refresh_labels(self) -> None:
        tree = self.query_one("#proposal", Tree)
        stack = [tree.root]
        while stack:
            node = stack.pop()
            if node.data is not None:
                node.set_label(self._label(node.data))
            stack.extend(node.children)
        self._update_summary()

    def _selection(self) -> list[ProposalItem]:
        if self.proposal is None:
            return []
        selected = []
        for item in self.proposal.items:
            files = [f for f in item.files if f.path not in self.unchecked]
            if files:
                selected.append(item.with_files(files))
        return selected

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
        self.summary_text = text
        self.query_one("#summary", Static).update(Text(text))

    def _scope(self) -> str:
        return f"{self.flavor.display_name} · {self.account or 'all accounts'}"

    # --- actions ---------------------------------------------------------------------------------
    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Checkbox):
            focused.toggle()
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
        self._refresh_labels()

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
        self._rebuild()

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
        self._rebuild()
        self.query_one("#proposal", Tree).focus()

    def action_flavors(self) -> None:
        if not self.app.busy:
            self.dismiss("flavors")

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
        selection = self._selection()
        if not selection:
            self.notify("Nothing is selected.")
            return
        running = self.wow_check()
        if running:
            log_event("wow.running_warning", executables=running)
        self.settings = load_settings(self.cfg)
        backup = self.settings.backup_before_delete
        backup_dir = resolve_backup_dir(self.cfg, self.settings)
        files = sum(len(i.files) for i in selection)
        size = format_size(sum(i.total_size for i in selection))
        lines = [f"{len(selection)} addon groups, {files} files, {size}."]
        alerts: list[str] = []
        if backup:
            lines.append(f"Backup zip goes to: {backup_dir}")
        else:
            alerts.append("No backup will be made (backup is off in settings).")
        if dry_run:
            lines.append(("DRY RUN: the backup zip is written, nothing is deleted." if backup
                          else "DRY RUN: nothing will be written or deleted."))
        if running:
            alerts.append(f"WoW appears to be running ({', '.join(running)}). Close it first: WoW rewrites "
                          "SavedVariables when you log out.")
        title = "Simulate this clean?" if dry_run else "Back up and delete these files?"
        self.app.push_screen(ConfirmScreen(title, "\n".join(lines), tuple(alerts)),
                             lambda ok: self._confirmed(ok, selection, backup, backup_dir, dry_run))

    def _confirmed(self, ok: bool | None, selection: list[ProposalItem], backup: bool,
                   backup_dir: Path | None, dry_run: bool) -> None:
        log_event("ui.selection", screen="confirm", control="confirm", value=bool(ok), dry_run=dry_run)
        if not ok:
            return
        self.app.busy = True
        progress_screen = CleanProgressScreen(dry_run)
        self._progress_screen = progress_screen
        self.app.push_screen(progress_screen)
        self.run_worker(lambda: self._clean_worker(selection, backup, backup_dir, dry_run, progress_screen),
                        thread=True, exclusive=True, group="clean")

    def _clean_worker(self, selection: list[ProposalItem], backup: bool, backup_dir: Path | None,
                      dry_run: bool, progress_screen: CleanProgressScreen) -> None:
        # Runs in a worker thread: the progress screen is only ever touched on the UI thread.
        def progress(*args) -> None:
            self.app.call_from_thread(progress_screen.update_progress, *args)

        try:
            result = execute(selection, self.flavor, dry_run=dry_run, backup=backup, backup_dir=backup_dir,
                             progress=progress)
        except (BackupError, CleanError) as exc:
            if isinstance(exc, CleanError):
                log_exception("clean", exc)
            self.app.call_from_thread(self._clean_failed, exc)
            return
        self.app.call_from_thread(self._cleaned, result)

    def _close_progress(self) -> None:
        progress_screen, self._progress_screen = self._progress_screen, None
        if progress_screen is not None and self.app.screen is progress_screen:
            self.app.pop_screen()

    def _clean_failed(self, exc: Exception) -> None:
        self.app.busy = False
        self._close_progress()
        self.notify(f"Nothing was deleted: {exc}", title="Clean stopped", severity="error", timeout=20)

    def _cleaned(self, result: CleanResult) -> None:
        self.app.busy = False
        self._close_progress()
        self.unchecked.clear()
        self.app.push_screen(ResultScreen(result), self._after_result)

    def _after_result(self, choice: str | None) -> None:
        if choice == "flavors":
            self.dismiss("flavors")
        elif choice == "quit":
            self.dismiss("quit")
        else:
            self.action_rescan()
