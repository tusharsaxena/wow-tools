"""Review the plan as a flavor → year → month → day tree, tick/untick, then organize, dry run or undo the last
run (with a progress screen and a result screen)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Header, Label, ProgressBar, Static, Tree

from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor
from wowtools.core.journal import friendly_stamp
from wowtools.tools.screenshot_organizer.journal import latest_undoable, read_journal
from wowtools.tools.screenshot_organizer.naming import day_parts
from wowtools.tools.screenshot_organizer.organizer import OrganizeError, OrganizeResult, execute
from wowtools.tools.screenshot_organizer.planner import MAYBE_DUPLICATE, FlavorPlan, Plan, ShotItem, scan
from wowtools.tools.screenshot_organizer.report import (RESULT_COLUMNS, STAGE_TITLES, confirm_text, destination_label,
                                                        kind_class, plural, result_rows, stopped_text,
                                                        summary_rows)
from wowtools.tools.screenshot_organizer.settings import load_settings, resolve_journal_dir
from wowtools.tools.screenshot_organizer.undo import undo
from wowtools.tools.wtf_cleaner.review_screen import ConfirmScreen
from wowtools.ui.branding import BrandBar
from wowtools.ui.widgets import CHECK_OFF, CHECK_ON, NAV_BINDINGS, ButtonRow, NavHint, action_button

ACCENT = "bold #5CC8FF"
SUCCESS_FALLBACK = "#4CC38A"
CLASS_FALLBACK = {"success": SUCCESS_FALLBACK, "accent": "#5CC8FF", "warning": "#E8C547", "error": "#E5534B"}
NAV_HINT = ("↑↓/Tab move · ←→ panes and buttons · Space tick · Enter/Space press · a all · n none · "
            "o organize · y dry run · r rescan · z undo · f flavors · t tools")
READ_ONLY = ("conflicts", "skipped", "conflict", "skip")  # tree nodes that cannot be ticked


class ShotProgressScreen(ModalScreen[None]):
    """Shown while a run, dry run or undo runs: the stage, a progress bar and the current file."""

    DEFAULT_CSS = """
    ShotProgressScreen { align: center middle; }
    ShotProgressScreen #shots-box { width: 80; height: auto; border: thick $accent; background: $panel;
                                    padding: 1 2; }
    ShotProgressScreen #shots-stage { color: $accent; text-style: bold; margin-bottom: 1; }
    ShotProgressScreen #shots-progress { width: 1fr; }
    ShotProgressScreen #shots-file { color: $text-muted; margin-top: 1; height: 2; overflow: hidden hidden; }
    """

    def __init__(self, stage_titles: dict[str, str] = STAGE_TITLES, dry_run: bool = False,
                 first_stage: str = "organize") -> None:
        super().__init__()
        self.stage_titles = stage_titles
        self.dry_run = dry_run
        self.stage = first_stage

    def compose(self) -> ComposeResult:
        with Vertical(id="shots-box"):
            yield Static(Text(self.stage_title(self.stage)), id="shots-stage")
            yield ProgressBar(id="shots-progress", show_eta=False)
            yield Static("", id="shots-file")

    def stage_title(self, stage: str) -> str:
        if stage == "organize" and self.dry_run:
            return "Simulating"
        return self.stage_titles.get(stage, stage)

    def update_progress(self, stage: str, current: int, total: int, detail: str = "") -> None:
        self.stage = stage
        self.query_one("#shots-stage", Static).update(Text(self.stage_title(stage)))
        # A total of 0 means "not known" (pruning): the bar runs as indeterminate.
        self.query_one("#shots-progress", ProgressBar).update(total=total if total > 0 else None, progress=current)
        self.query_one("#shots-file", Static).update(Text(detail))


class ShotResultScreen(Screen[str]):
    """The outcome of a run, dry run or undo: a summary table, a per-file table and what to do next."""

    DEFAULT_CSS = """
    ShotResultScreen #result { height: 1fr; padding: 1 2; }
    ShotResultScreen #result-summary { height: auto; margin-bottom: 1; }
    ShotResultScreen #result-files { height: 1fr; }
    ShotResultScreen .buttons { height: auto; padding: 0 2; }
    ShotResultScreen Button { margin-right: 2; }
    ShotResultScreen NavHint { padding: 0 2; margin-top: 0; }
    """
    BINDINGS = [Binding("r", "choose('review')", "Rescan"), Binding("f", "choose('flavors')", "Flavors"),
                Binding("t", "choose('tools')", "Tools"), Binding("q", "choose('quit')", "Quit"),
                Binding("escape", "choose('review')", "Back", show=False),
                *NAV_BINDINGS]

    def __init__(self, result: OrganizeResult) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="result"):
            summary = DataTable(id="result-summary", cursor_type="none", zebra_stripes=True)
            summary.can_focus = False  # read-only summary: not a focus stop
            yield summary
            yield DataTable(id="result-files", cursor_type="row", zebra_stripes=True)
        with ButtonRow(classes="buttons"):
            yield action_button("Rescan (r)", "neutral", id="review")
            yield action_button("Other flavor (f)", "neutral", id="flavors")
            yield action_button("Tools (t)", "neutral", id="tools")
            yield action_button("Quit (q)", "neutral", id="quit")
        yield NavHint("↑↓/Tab move · ←→ buttons · Enter/Space press · Esc back · r rescan · f other flavor · "
                      "t tools · q quit")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        if self.result.undo:
            self.sub_title = "Screenshot Organizer · undo result"
        elif self.result.dry_run:
            self.sub_title = "Screenshot Organizer · dry run result"
        else:
            self.sub_title = "Screenshot Organizer · result"
        summary = self.query_one("#result-summary", DataTable)
        summary.add_columns("Item", "Value")
        summary.add_rows((Text(item), Text(value)) for item, value in summary_rows(self.result))
        files = self.query_one("#result-files", DataTable)
        files.add_columns(*RESULT_COLUMNS)
        for outcome, row in zip(self.result.outcomes, result_rows(self.result)):
            label, *rest = row
            files.add_row(Text(label, style=self._kind_style(outcome.kind)), *(Text(c) for c in rest))
        self.query_one("#review", Button).focus()

    def _kind_style(self, kind: str) -> str:
        name = kind_class(kind)
        if not name:
            return ""
        try:
            colour = getattr(self.app.current_theme, name, None)
        except Exception:  # noqa: BLE001 - no theme yet: use the Ka0s colours
            colour = None
        return f"bold {colour or CLASS_FALLBACK[name]}"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "quit")

    def action_choose(self, choice: str) -> None:
        log_event("ui.selection", screen="shots_result", control="next", value=choice)
        self.dismiss(choice)


class ShotTree(Tree):
    """The plan tree. ← jumps to the left panel (instead of scrolling sideways)."""

    BINDINGS = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class ShotReviewScreen(Screen[str]):
    DEFAULT_CSS = """
    ShotReviewScreen #body { height: 1fr; }
    ShotReviewScreen #filters { width: 50; padding: 1; border-right: solid $primary; }
    ShotReviewScreen #actions { margin-top: 1; height: auto; }
    ShotReviewScreen #actions Button { min-width: 0; width: auto; margin-right: 1; margin-bottom: 1; }
    ShotReviewScreen .section { color: $accent; text-style: bold; margin: 1 0 0 0; }
    ShotReviewScreen #shots { width: 1fr; padding: 0 1; }
    ShotReviewScreen #scan-box { width: 1fr; height: auto; padding: 1 2; }
    ShotReviewScreen #scan-progress { width: 1fr; }
    ShotReviewScreen #scan-label { color: $text-muted; margin-top: 1; }
    ShotReviewScreen #summary { height: auto; padding: 0 1; background: $surface; }
    """
    BINDINGS = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("o", "organize", "Organize"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
        Binding("f", "flavors", "Flavors"),
        Binding("t", "tools", "Tools"),
        Binding("q", "quit_tool", "Quit"),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: list[Flavor], scope_label: str) -> None:
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/screenshot-organizer.cfg
        self.flavors = list(flavors)
        self.scope_label = scope_label
        self.settings = load_settings(tool_cfg)
        self.plan: Plan | None = None
        self.unchecked: set[Path] = set()
        self.summary_text = ""
        self._items_by_key: dict[tuple, list[ShotItem]] = {}
        self._progress_screen: ShotProgressScreen | None = None
        self._last_filter: Widget | None = None
        self._scanning = False

    # --- layout -------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("Destination", classes="section")
                yield Static(Text(destination_label(self.settings.dest_dir)), id="dest-label")
                yield Label("Mode", classes="section")
                yield Static(Text(self._mode_text()), id="mode-label")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Organize", "apply", id="btn-organize")
                    yield action_button("Dry run", "simulate", id="btn-dry")
                    yield action_button("Rescan", "neutral", id="btn-rescan")
                    yield action_button("Undo last run", "revert", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield ShotTree(Text(self.scope_label), id="shots")
        yield Static("", id="summary")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"Screenshot Organizer · {self.scope_label}"
        self.query_one("#shots", Tree).focus()
        self._refresh_undo()
        self.action_rescan()

    def _mode_text(self) -> str:
        if self.settings.copy_mode:
            return "Copy (the screenshots stay in the Screenshots folder too)"
        return "Move"

    def _journal_dir(self) -> Path | None:
        return resolve_journal_dir(self.cfg.wow_path)

    def _refresh_undo(self) -> None:
        # Never offered while a scan is reading the same folders the undo would move files in.
        self.query_one("#btn-undo", Button).disabled = self._scanning or latest_undoable(self._journal_dir()) is None

    # --- panes (←/→) --------------------------------------------------------------------------------
    def on_descendant_focus(self, event) -> None:
        widget = event.widget
        if any(ancestor.id == "filters" for ancestor in widget.ancestors):
            self._last_filter = widget

    def action_focus_filters(self) -> None:
        focused = self.focused
        if focused is not None and any(a.id == "filters" for a in focused.ancestors):
            return  # already in the left panel
        target = self._last_filter
        if target is None or not target.is_attached or not target.focusable:
            target = next((b for b in self.query("#actions Button").results(Button) if b.focusable), None)
        if target is not None:
            target.focus()

    def action_focus_tree(self) -> None:
        tree = self.query_one("#shots", Tree)
        if tree.display and self.focused is not tree:
            tree.focus()

    # --- scanning ------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if self.app.busy:
            return
        self.settings = load_settings(self.tool_cfg)
        self.query_one("#dest-label", Static).update(Text(destination_label(self.settings.dest_dir)))
        self.query_one("#mode-label", Static).update(Text(self._mode_text()))
        self.plan = None
        self.unchecked.clear()  # a new scan means new items
        self._show_scan_progress(True)
        self.run_worker(self._scan_worker, thread=True, exclusive=True, group="scan")

    def _show_scan_progress(self, scanning: bool) -> None:
        """While scanning, the tree is replaced by a progress bar and the folder being read."""
        self._scanning = scanning
        bar = self.query_one("#scan-progress", ProgressBar)
        if scanning:
            bar.update(total=None, progress=0)
            self.query_one("#scan-label", Static).update(Text("Reading Screenshots folders"))
        for selector in ("#scan-box", "#scan-progress", "#scan-label"):
            self.query_one(selector).display = scanning
        self.query_one("#shots", Tree).display = not scanning
        for button_id in ("#btn-organize", "#btn-dry"):
            self.query_one(button_id, Button).disabled = scanning
        if scanning:
            self.query_one("#btn-undo", Button).disabled = True

    def _scan_progress(self, current: int, total: int, label: str) -> None:
        self.query_one("#scan-progress", ProgressBar).update(total=total or None, progress=current)
        self.query_one("#scan-label", Static).update(Text(label))

    def _scan_worker(self) -> None:
        dest_dir = self.settings.dest_dir

        def progress(current: int, total: int, label: str) -> None:
            self.app.call_from_thread(self._scan_progress, current, total, label)

        try:
            plan = scan(self.flavors, dest_dir, progress)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("shots.scan", exc)
            self.app.call_from_thread(self._scan_failed, f"The scan failed: {exc}")
            return
        self.app.call_from_thread(self._scanned, plan)

    def _scan_failed(self, message: str) -> None:
        self._show_scan_progress(False)
        self._refresh_undo()
        self.summary_text = message
        self.query_one("#summary", Static).update(Text(message))
        self.notify(message, title="Scan failed", severity="error", timeout=15)

    def _scanned(self, plan: Plan) -> None:
        self.plan = plan
        self._show_scan_progress(False)
        self._rebuild()
        self._refresh_undo()
        self.query_one("#shots", Tree).focus()

    # --- tree ------------------------------------------------------------------------------------
    @staticmethod
    def _key(data) -> tuple:
        kind = data[0]
        if kind == "root":
            return ("root",)
        folder = data[1].flavor.folder
        if kind == "flavor":
            return ("flavor", folder)
        if kind == "year":
            return ("year", folder, data[2])
        if kind == "month":
            return ("month", folder, data[2], data[3])
        return ("day", folder, data[2])

    def _index(self, plan: Plan) -> None:
        """Precompute the selectable items under every flavor, year, month and day, so marks stay cheap."""
        index: dict[tuple, list[ShotItem]] = {("root",): []}
        for fp in plan.flavors:
            folder = fp.flavor.folder
            index.setdefault(("flavor", folder), [])
            for item in sorted(fp.selectable, key=lambda i: (i.day, i.src.name.casefold())):
                year, month, _ = day_parts(item.day)
                for key in (("root",), ("flavor", folder), ("year", folder, year), ("month", folder, year, month),
                            ("day", folder, item.day)):
                    index.setdefault(key, []).append(item)
        self._items_by_key = index

    def _items(self, data) -> list[ShotItem]:
        if data[0] == "file":
            return [data[1]]
        if data[0] in READ_ONLY:
            return []
        return self._items_by_key.get(self._key(data), [])

    def _rebuild(self) -> None:
        plan = self.plan
        if plan is None:
            return
        self._index(plan)
        tree = self.query_one("#shots", Tree)
        tree.clear()
        tree.root.data = ("root",)
        tree.root.set_label(self._label(tree.root.data))
        for fp in plan.flavors:
            data = ("flavor", fp)
            flavor_node = tree.root.add(self._label(data), data=data, expand=True)
            years: dict[str, dict[str, list[date]]] = {}
            for item in self._items_by_key.get(("flavor", fp.flavor.folder), []):
                year, month, _ = day_parts(item.day)
                days = years.setdefault(year, {}).setdefault(month, [])
                if not days or days[-1] != item.day:
                    days.append(item.day)
            for year in sorted(years):
                data = ("year", fp, year)
                year_node = flavor_node.add(self._label(data), data=data, expand=True)
                for month in sorted(years[year]):
                    data = ("month", fp, year, month)
                    month_node = year_node.add(self._label(data), data=data, expand=True)
                    for day in years[year][month]:
                        data = ("day", fp, day)
                        month_node.add(self._label(data), data=data, allow_expand=True)  # files load on expand
            if fp.conflicts:
                data = ("conflicts", fp)
                node = flavor_node.add(self._label(data), data=data)
                for item in fp.conflicts:
                    node.add_leaf(Text.assemble((item.src.name, "dim"), (f"  → {item.dst.parent}", "dim")),
                                  data=("conflict", item))
            if fp.skipped:
                data = ("skipped", fp)
                node = flavor_node.add(self._label(data), data=data)
                for skipped in fp.skipped:
                    node.add_leaf(Text(skipped.path.name, style="dim"), data=("skip", skipped))
            if not flavor_node.children:
                flavor_node.allow_expand = False  # nothing under it: no expand arrow
        tree.root.expand()
        self._update_summary()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if node.data is None or node.data[0] != "day" or node.children:
            return
        for item in self._items(node.data):
            data = ("file", item)
            node.add_leaf(self._label(data), data=data)

    def _mark(self, items: list[ShotItem]) -> tuple[str, str]:
        unchecked = sum(1 for i in items if i.src in self.unchecked)
        if items and unchecked == len(items):
            return f"{CHECK_OFF} ", "dim"
        if unchecked:
            return "◩ ", "bold"
        try:
            success = self.app.current_theme.success or SUCCESS_FALLBACK
        except Exception:  # noqa: BLE001 - no theme yet: use the Ka0s colour
            success = SUCCESS_FALLBACK
        return f"{CHECK_ON} ", f"bold {success}"

    def _label(self, data) -> Text:
        kind = data[0]
        if kind == "conflicts":
            n = len(data[1].conflicts)
            return Text(f"Conflicts ({n}): a different file with the same name is already filed",
                        style="bold #E8C547")
        if kind == "skipped":
            return Text(f"Skipped ({len(data[1].skipped)}): name not recognised", style="dim")
        items = self._items(data)
        mark = self._mark(items)
        if kind == "file":
            item = data[1]
            extra = ("  possible duplicate", "dim") if item.state == MAYBE_DUPLICATE else ""
            return Text.assemble(mark, item.src.name, extra)
        if kind == "root":
            name = self.scope_label
        elif kind == "flavor":
            fp = data[1]
            name = fp.flavor.display_name
            if not items:  # nothing selectable: say why instead of a tick and "0 shots"
                why = ("no Screenshots folder" if fp.missing else "could not be read (see the log)" if fp.error
                       else "nothing to file")
                return Text.assemble("  ", (name, ACCENT), (f"  {why}", "dim"))
        elif kind == "day":
            name = data[2].isoformat()
        else:
            name = data[-1]
        return Text.assemble(mark, (name, ACCENT), (f"  {plural(len(items), 'shot')}", "dim"))

    def _refresh_labels(self, node=None) -> None:
        """Relabel node's branch and its ancestors (everything a tick there can change), or the whole tree."""
        tree = self.query_one("#shots", Tree)
        if node is not None:
            parent = node.parent
            while parent is not None:
                if parent.data is not None:
                    parent.set_label(self._label(parent.data))
                parent = parent.parent
        stack = [node or tree.root]
        while stack:
            current = stack.pop()
            if current.data is not None and current.data[0] not in READ_ONLY:
                current.set_label(self._label(current.data))
            stack.extend(current.children)
        self._update_summary()

    def selection(self) -> list[ShotItem]:
        if self.plan is None:
            return []
        return [i for i in self.plan.selectable if i.src not in self.unchecked]

    def _update_summary(self) -> None:
        plan = self.plan
        if plan is None:
            return
        selection = self.selection()
        dupes = sum(1 for i in selection if i.state == MAYBE_DUPLICATE)
        conflicts = sum(len(fp.conflicts) for fp in plan.flavors)
        text = (f"Selected: {plural(len(selection), 'shot')} · {plural(dupes, 'possible duplicate')} · "
                f"{plural(conflicts, 'conflict')} · {len(plan.skipped)} skipped (name not recognised)")
        nothing = not plan.selectable
        if nothing:
            # Only worth saying when none of the chosen flavors has a Screenshots folder at all.
            reason = "" if any(not fp.missing for fp in plan.flavors) else " (no Screenshots folder)"
            text = f"Nothing to file{reason}.    " + text
        for button_id in ("#btn-organize", "#btn-dry"):
            self.query_one(button_id, Button).disabled = nothing
        if plan.warnings:
            text += f"    ⚠ {plural(len(plan.warnings), 'folder')} could not be read (see the log)"
        self.summary_text = text
        self.query_one("#summary", Static).update(Text(text))

    # --- actions ---------------------------------------------------------------------------------
    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Button):  # Space activates the focused button, never the tree
            focused.press()
            return
        if not isinstance(focused, Tree):
            return
        node = self.query_one("#shots", Tree).cursor_node
        if node is None or node.data is None or node.data[0] in READ_ONLY:
            return
        paths = [i.src for i in self._items(node.data)]
        if not paths:
            return
        check = any(p in self.unchecked for p in paths)
        if check:
            self.unchecked.difference_update(paths)
        else:
            self.unchecked.update(paths)
        log_event("ui.item_toggled", screen="shots_review", key=":".join(str(p) for p in self._node_key(node.data)),
                  checked=check)
        self._refresh_labels(node)

    def _node_key(self, data) -> tuple:
        return (str(data[1].src),) if data[0] == "file" else self._key(data)

    def action_select_all(self) -> None:
        self.unchecked.clear()
        log_event("ui.selection", screen="shots_review", control="select_all", value=True)
        self._refresh_labels()

    def action_select_none(self) -> None:
        if self.plan is not None:
            self.unchecked = {i.src for i in self.plan.selectable}
        log_event("ui.selection", screen="shots_review", control="select_none", value=True)
        self._refresh_labels()

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
        actions = {"btn-organize": self.action_organize, "btn-dry": self.action_dry_run,
                   "btn-rescan": self.action_rescan, "btn-undo": self.action_undo}
        action = actions.get(event.button.id or "")
        if action is not None:
            event.stop()
            action()

    # --- organize --------------------------------------------------------------------------------
    def action_organize(self) -> None:
        self._start(dry_run=False)

    def action_dry_run(self) -> None:
        self._start(dry_run=True)

    def _start(self, dry_run: bool) -> None:
        if self.plan is None or self.app.busy:
            return
        log_event("ui.selection", screen="shots_review", control="dry_run" if dry_run else "organize", value=True)
        selection = self.selection()
        if not selection:
            self.notify("Nothing is selected.")
            return
        title, body = confirm_text(selection, self.plan, self.settings, dry_run)
        self.app.push_screen(ConfirmScreen(title, body, default_yes=dry_run),
                             lambda ok: self._confirmed(ok, selection, dry_run))

    def _confirmed(self, ok: bool | None, selection: list[ShotItem], dry_run: bool) -> None:
        log_event("ui.selection", screen="confirm", control="confirm", value=bool(ok), dry_run=dry_run)
        if not ok or self.plan is None:
            return
        # The scanned plan's destination, not the current settings: the plan's targets were computed from it.
        dest_dir, settings, journal_dir = self.plan.dest_dir, self.settings, self._journal_dir()
        self._run(ShotProgressScreen(dry_run=dry_run),
                  lambda progress: execute(selection, dest_dir=dest_dir, copy=settings.copy_mode, dry_run=dry_run,
                                           journal_dir=journal_dir, keep_journals=settings.keep_journals,
                                           progress=progress))

    def _run(self, progress_screen: ShotProgressScreen, job) -> None:
        """Run job(progress) in a worker thread behind the progress screen, then show its result."""
        self.app.busy = True
        self._progress_screen = progress_screen
        self.app.push_screen(progress_screen)
        self.run_worker(lambda: self._job_worker(job, progress_screen), thread=True, exclusive=True,
                        group="organize")

    def _job_worker(self, job, progress_screen: ShotProgressScreen) -> None:
        # Runs in a worker thread: the progress screen is only ever touched on the UI thread.
        def progress(*args) -> None:
            self.app.call_from_thread(progress_screen.update_progress, *args)

        try:
            result = job(progress)
        except OrganizeError as exc:
            self.app.call_from_thread(self._job_stopped, exc)
            return
        except Exception as exc:  # noqa: BLE001 - e.g. an unreadable journal during undo
            log_exception("shots.ui", exc)
            self.app.call_from_thread(self._job_failed, exc)
            return
        self.app.call_from_thread(self._job_done, result)

    def _close_progress(self) -> None:
        progress_screen, self._progress_screen = self._progress_screen, None
        if progress_screen is not None and self.app.screen is progress_screen:
            self.app.pop_screen()

    def _job_stopped(self, exc: OrganizeError) -> None:
        self.app.busy = False
        self._close_progress()
        self.notify(stopped_text(str(exc), exc.result, latest_undoable(self._journal_dir())),
                    title="Run stopped", severity="error", timeout=20)
        self._refresh_undo()
        self.app.push_screen(ShotResultScreen(exc.result), self._after_result)

    def _job_failed(self, exc: Exception) -> None:
        self.app.busy = False
        self._close_progress()
        self._refresh_undo()
        self.notify(f"{type(exc).__name__}: {exc}", title="Stopped", severity="error", timeout=20)

    def _job_done(self, result: OrganizeResult) -> None:
        self.app.busy = False
        self._close_progress()
        self.unchecked.clear()
        self._refresh_undo()
        self.app.push_screen(ShotResultScreen(result), self._after_result)

    def _after_result(self, choice: str | None) -> None:
        if choice in ("flavors", "tools", "quit"):
            self.dismiss(choice)
        else:
            self.action_rescan()

    # --- undo ------------------------------------------------------------------------------------
    def action_undo(self) -> None:
        if self.app.busy or self._scanning:
            return
        log_event("ui.selection", screen="shots_review", control="undo", value=True)
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
        body = (f"Put back {plural(len(journal.entries), 'file')}? Moved files go back to their "
                "Screenshots folders, copies are removed, removed duplicates are restored. Anything that changed "
                "since is left alone.")
        title = f"Undo the run from {friendly_stamp(journal.started)}?"
        self.app.push_screen(ConfirmScreen(title, body, default_yes=False),
                             lambda ok: self._undo_confirmed(ok, path))

    def _undo_confirmed(self, ok: bool | None, path: Path) -> None:
        log_event("ui.selection", screen="confirm", control="undo_confirm", value=bool(ok))
        if not ok:
            return
        wow_root = self.cfg.wow_path
        if wow_root is None:
            return
        self._run(ShotProgressScreen(first_stage="undo"),
                  lambda progress: undo(path, wow_root=wow_root, progress=progress))
