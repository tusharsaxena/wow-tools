"""Review the plan as a flavor → year → month → day tree, tick/untick, then organize, dry run or undo the last
run (with a progress screen and a result screen)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Header, Label, ProgressBar, Static, Tree

from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.journal import friendly_stamp
from wowtools.core.text import plural
from wowtools.tools.screenshot_organizer.journal import latest_undoable, read_journal, resolve_journal_dir
from wowtools.tools.screenshot_organizer.naming import day_parts
from wowtools.tools.screenshot_organizer.organizer import OrganizeError, OrganizeResult, execute
from wowtools.tools.screenshot_organizer.planner import MAYBE_DUPLICATE, Plan, ShotItem, scan
from wowtools.tools.screenshot_organizer.report import (RESULT_COLUMNS, STAGE_TITLES, confirm_text, destination_label,
                                                        kind_class, result_rows, stopped_text, summary_rows)
from wowtools.tools.screenshot_organizer.settings import load_settings, validate_dest
from wowtools.tools.screenshot_organizer.undo import undo
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import (ACCENT, REVIEW_HINT, TREE_BINDINGS, TREE_HINT, ConfirmScreen, ProgressScreen,
                                relabel_branch, two_pane_css)
from wowtools.ui.result_screen import ResultBase, result_bindings, status_style
from wowtools.ui.review import ReviewBase, ReviewTree, TickModel
from wowtools.ui.tree_filter import FILTER_BINDINGS, FILTER_HINT, FilterBar, ModelFilter, ModelNode, TreeFilter
from wowtools.ui.warnings_view import WARNINGS_BINDING, SummaryBar, WarningItem, WarningsHost, scan_warning_items
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

NAV_HINT = REVIEW_HINT + "a all · n none · " + FILTER_HINT + TREE_HINT + "f flavors · t tools"
READ_ONLY = ("conflicts", "skipped", "conflict", "skip")  # tree nodes that cannot be ticked
FILED_TITLE = "Already filed"


class ShotProgressScreen(ProgressScreen):
    """Shown while a run, dry run or undo runs (the widget ids keep their shots- prefix)."""

    ID_PREFIX = "shots"
    STAGE_TITLES = STAGE_TITLES
    SIMULATED_STAGE = "organize"

    def __init__(self, dry_run: bool = False, first_stage: str = "organize") -> None:
        title = ("Undoing the last run" if first_stage == "undo" else
                 "Simulating a run" if dry_run else "Organizing screenshots")
        super().__init__(title, dry_run=dry_run, first_stage=first_stage)


class ShotResultScreen(ResultBase):
    """The outcome of a run, dry run or undo: a summary table, a per-file table and what to do next."""

    LOG_SCREEN = "shots_result"
    RESCAN = "review"
    DETAIL_ID = "result-files"
    BINDINGS: ClassVar[list[Binding]] = result_bindings(RESCAN)

    def __init__(self, result: OrganizeResult) -> None:
        super().__init__()
        self.result = result

    def result_title(self) -> str:
        if self.result.undo:
            return "Screenshot Organizer · undo result"
        if self.result.dry_run:
            return "Screenshot Organizer · dry run result"
        return "Screenshot Organizer · result"

    def summary_rows(self) -> list[tuple[str, str]]:
        return summary_rows(self.result)

    def fill_detail(self, files: DataTable) -> None:
        files.add_columns(*RESULT_COLUMNS)
        for outcome, row in zip(self.result.outcomes, result_rows(self.result)):
            label, *rest = row
            files.add_row(Text(label, style=status_style(self.app, kind_class(outcome.kind), plain="")),
                          *(Text(c) for c in rest))


class ShotReviewScreen(WarningsHost, TreeFilter, ReviewBase, Screen[str]):
    TREE_SELECTOR = "#shots"
    WARNINGS_TITLE = "Folders not read"
    WARNINGS_NOUN = "unreadable folder"
    LOG_SCREEN = "shots_review"
    HIDDEN_NOUN = "shot"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {"btn-organize": "organize", "btn-dry": "dry_run",
                                                "btn-rescan": "rescan", "btn-undo": "undo"}
    DEFAULT_CSS = two_pane_css("ShotReviewScreen", "#shots")
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        Binding("o", "organize", "Organize"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
        WARNINGS_BINDING,
        Binding("f", "leave('flavors')", "Flavors"),
        Binding("t", "leave('tools')", "Tools"),
        Binding("q", "leave('quit')", "Quit"),
        Binding("escape", "leave('flavors')", "Flavors", show=False),
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
        self._filter_texts: dict[Path, tuple[str, ...]] = {}  # a shot's labels from its flavor down: the filter's
        self._kept: ModelFilter | None = None  # what the filter keeps of the plan (files load on expand)
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
                yield FilterBar()
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Organize", "overwrite", "o", id="btn-organize")
                    yield action_button("Dry run", "simulate", "y", id="btn-dry")
                    yield action_button("Rescan", "navigate", "r", id="btn-rescan")
                    yield action_button("Undo last run", "revert", "z", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield ReviewTree(Text(self.scope_label), id="shots")
        yield SummaryBar()
        yield BottomBar()

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
        # Never offered while a scan is reading the same folders the undo would move files in, or while busy.
        busy = self._scanning or getattr(self.app, "busy", False)
        self.query_one("#btn-undo", Button).disabled = busy or latest_undoable(self._journal_dir()) is None

    # --- panes (←/→): TwoPaneFocus ------------------------------------------------------------------
    def first_filter(self) -> Widget | None:
        """The left pane's first control: the filter box (then the buttons)."""
        return self.filter_input()

    # --- scanning ------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if self.app.busy:
            return
        self.settings = load_settings(self.tool_cfg)
        self.query_one("#dest-label", Static).update(Text(destination_label(self.settings.dest_dir)))
        self.query_one("#mode-label", Static).update(Text(self._mode_text()))
        self.plan = None
        self.unchecked.clear()  # a new scan means new items
        problem = self._dest_problem()
        if problem:  # checked again before use: the file may have been edited by hand
            self._show_scan_progress(False)
            tree = self.query_one("#shots", Tree)
            tree.clear()
            message = f"{problem} Fix the folder in settings (s)."
            self.summary_text = message
            self.query_one("#summary", Static).update(Text(message))
            for button_id in ("#btn-organize", "#btn-dry"):
                self.query_one(button_id, Button).disabled = True
            self._refresh_undo()
            self.notify(message, title="Destination not allowed", severity="error", timeout=15)
            return
        self._show_scan_progress(True)
        self.run_worker(self._scan_worker, thread=True, exclusive=True, group="scan")

    def _dest_problem(self) -> str | None:
        wow_path = self.cfg.wow_path
        if wow_path is None:
            return None
        return validate_dest(self.settings.dest_dir, WowInstall(wow_path))

    def _show_scan_progress(self, scanning: bool) -> None:
        """While scanning, the tree is replaced by a progress bar and the folder being read."""
        self.show_scan_box(scanning, "Reading Screenshots folders")
        for button_id in ("#btn-organize", "#btn-dry"):
            self.query_one(button_id, Button).disabled = scanning
        if scanning:
            self.query_one("#btn-undo", Button).disabled = True

    def _scan_worker(self) -> None:
        dest_dir, copy = self.settings.dest_dir, self.settings.copy_mode

        def progress(current: int, total: int, label: str) -> None:
            self.app.call_from_thread(self._scan_progress, current, total, label)

        try:
            plan = scan(self.flavors, dest_dir, progress, copy=copy)
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
        self.unchecked = {i.src for i in plan.filed}  # copy mode: already filed, so they start unticked
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
        if kind == "filed":
            return ("filed", folder)
        return ("day", folder, data[2])

    def _index(self, plan: Plan) -> None:
        """Precompute the items to file under every flavor, year, month and day, and each flavor's already-filed
        group (copy mode), so marks stay cheap."""
        index: dict[tuple, list[ShotItem]] = {("root",): []}
        for fp in plan.flavors:
            folder = fp.flavor.folder
            index.setdefault(("flavor", folder), [])
            index[("filed", folder)] = sorted(fp.filed, key=lambda i: (i.day, i.src.name.casefold()))
            for item in sorted(fp.to_file, key=lambda i: (i.day, i.src.name.casefold())):
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

    def _model(self, plan: Plan) -> list[ModelNode]:
        """The plan as model nodes, one per flavor (the files of a day or of Already filed too: they load on expand
        in the tree but the filter matches them), and each shot's labels for filter_texts()."""
        self._filter_texts = {}
        flavors = []
        for fp in plan.flavors:
            name = fp.flavor.display_name
            flavor = ModelNode(("flavor", fp))
            years: dict[str, dict[str, list[date]]] = {}
            for item in self._items_by_key.get(("flavor", fp.flavor.folder), []):
                year, month, _ = day_parts(item.day)
                days = years.setdefault(year, {}).setdefault(month, [])
                if not days or days[-1] != item.day:
                    days.append(item.day)
            for year in sorted(years):
                year_node = ModelNode(("year", fp, year))
                for month in sorted(years[year]):
                    month_node = ModelNode(("month", fp, year, month))
                    for day in years[year][month]:
                        data = ("day", fp, day)
                        items = self._items(data)
                        month_node.children.append(ModelNode(data, [ModelNode(("file", i)) for i in items]))
                        for i in items:
                            self._filter_texts[i.src] = (name, year, month, day.isoformat(), i.src.name)
                    year_node.children.append(month_node)
                flavor.children.append(year_node)
            if fp.filed:
                data = ("filed", fp)
                items = self._items(data)
                flavor.children.append(ModelNode(data, [ModelNode(("file", i)) for i in items]))
                for i in items:
                    self._filter_texts[i.src] = (name, FILED_TITLE, i.src.name)
            if fp.conflicts:
                flavor.children.append(ModelNode(("conflicts", fp), [ModelNode(("conflict", i))
                                                                     for i in fp.conflicts]))
            if fp.skipped:
                flavor.children.append(ModelNode(("skipped", fp), [ModelNode(("skip", s)) for s in fp.skipped]))
            flavors.append(flavor)
        return flavors

    @staticmethod
    def _ident(node: ModelNode) -> tuple:
        """A model node's identity, the same for the node a day's expand builds (the filter's key)."""
        data = node.data
        kind = data[0]
        if kind in ("file", "conflict"):
            return kind, data[1].src
        if kind == "skip":
            return kind, data[1].path
        if kind in ("conflicts", "skipped"):
            return kind, data[1].flavor.folder
        return ShotReviewScreen._key(data)

    @staticmethod
    def _filter_name(data) -> str:
        """What the filter matches a node on: the name its label shows."""
        kind = data[0]
        if kind == "flavor":
            return data[1].flavor.display_name
        if kind == "day":
            return data[2].isoformat()
        if kind in ("file", "conflict"):
            return data[1].src.name
        if kind == "skip":
            return data[1].path.name
        return {"filed": FILED_TITLE, "conflicts": "Conflicts", "skipped": "Skipped"}.get(kind, data[-1])

    def _can_rebuild(self) -> bool:
        return self.plan is not None  # before a scan, or after a failed one, the bottom line keeps what it says

    def _rebuild(self) -> None:
        plan = self.plan
        if plan is None:
            return
        self._index(plan)
        flavors = self._model(plan)
        kept = self._kept = self.model_filter(flavors, lambda n: n.children, lambda n: (self._filter_name(n.data),),
                                              key=self._ident)
        tree = self.query_one("#shots", Tree)
        tree.clear()
        tree.root.data = ("root",)
        tree.root.set_label(self._label(tree.root.data))
        for flavor in flavors:
            if kept.shows(flavor):
                self._add_node(tree.root, flavor, kept)
        self.note_no_match(tree.root)
        tree.root.expand()
        self._update_summary()

    def _add_node(self, parent, node: ModelNode, kept: ModelFilter) -> None:
        """Add node and what the filter keeps below it. Flavors, years and months open; a day and Already filed
        get their files on expand (open when the filter opens them); conflicts and skipped start closed."""
        data = node.data
        kind = data[0]
        if kind in ("day", "filed"):
            added = parent.add(self._label(data), data=data, allow_expand=True)  # files load on expand
            if kept.opens(node):
                self._load_files(added)
                added.expand()
            return
        if kind in ("conflict", "skip"):
            name = data[1].src.name if kind == "conflict" else data[1].path.name
            note = f"  → {data[1].dst.parent}" if kind == "conflict" else ""
            parent.add_leaf(Text.assemble((name, "dim"), (note, "dim")), data=data)
            return
        added = parent.add(self._label(data), data=data,
                           expand=kind in ("flavor", "year", "month") or kept.opens(node))
        for child in node.children:
            if kept.shows(child):
                self._add_node(added, child, kept)
        if kind == "flavor" and not added.children:
            added.allow_expand = False  # nothing under it: no expand arrow

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        self._load_files(event.node)

    def _load_files(self, node) -> None:
        """A day's or Already filed's files, those the filter keeps, the first time it opens."""
        if node.data is None or node.data[0] not in ("day", "filed") or node.children:
            return
        kept = self._kept
        for item in self._items(node.data):
            data = ("file", item)
            if kept is None or kept.shows(ModelNode(data)):
                node.add_leaf(self._label(data), data=data)

    def _mark(self, items: list[ShotItem]) -> tuple[str, str]:
        return self.shown_tick_mark(items, lambda i: i.src)

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
        if kind == "filed":
            return Text.assemble(mark, (f"{FILED_TITLE} ({len(items)})", ACCENT),
                                 ("  an identical copy is already in its date folder", "dim"))
        if kind == "root":
            name = self.scope_label
        elif kind == "flavor":
            fp = data[1]
            name = fp.flavor.display_name
            if not items:  # nothing selectable: say why instead of a tick and "0 shots"
                why = ("no Screenshots folder" if fp.missing else "could not be read (see Warnings)" if fp.error
                       else "nothing to file")
                return Text.assemble("  ", (name, ACCENT), (f"  {why}", "dim"))
        elif kind == "day":
            name = data[2].isoformat()
        else:
            name = data[-1]
        return Text.assemble(mark, (name, ACCENT), (f"  {plural(len(items), 'shot')}", "dim"))

    def _refresh_labels(self, node=None) -> None:
        """Relabel node's branch and its ancestors (everything a tick there can change), or the whole tree."""
        relabel_branch(self.query_one("#shots", Tree), node, self._label, skip=READ_ONLY)
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
        if plan.filed:
            text += f" · {len(plan.filed)} already filed"
        if not plan.to_file:
            # Only worth saying when none of the chosen flavors has a Screenshots folder at all.
            reason = "" if any(not fp.missing for fp in plan.flavors) else " (no Screenshots folder)"
            text = f"Nothing to file{reason}.    " + text
        for button_id in ("#btn-organize", "#btn-dry"):  # already-filed copies can still be ticked by hand
            self.query_one(button_id, Button).disabled = not plan.selectable
        hidden = self.hidden_ticked_note()
        if hidden:
            text += f"    {hidden}"
        self.summary_text = text
        self.query_one("#summary", Static).update(Text(text))
        self.refresh_warnings()

    def warning_items(self) -> list[WarningItem]:
        """The folders the scan could not read, under their flavor's name (inside its folder when they are)."""
        plan = self.plan
        if plan is None:
            return []
        bases = {fp.flavor.display_name: fp.flavor.path for fp in plan.flavors}
        return [item for w in plan.warnings for item in scan_warning_items([w], w.flavor, bases.get(w.flavor))]

    # --- ticks (Space, a, n: ReviewBase) ------------------------------------------------------------
    def tick_model(self) -> TickModel:
        return TickModel.of_unchecked(self.unchecked)  # everything to file starts ticked

    def node_tick_keys(self, node) -> list[Path]:
        if node is None or node.data is None:
            return []
        return [i.src for i in self._items(node.data)]  # none for a read-only node

    def all_tick_keys(self) -> list[Path]:
        """Day and already-filed files load on expand: the keys come from the plan."""
        return [i.src for i in self.plan.selectable] if self.plan is not None else []

    def filter_texts(self, key: Path) -> tuple[str, ...]:
        return self._filter_texts.get(key, ())

    def select_all_keys(self) -> list[Path]:
        # Everything to file; already-filed copies (copy mode) keep whatever the user chose for them.
        filed = {i.src for i in self.plan.filed} if self.plan is not None else set()
        return [k for k in self.shown_tick_keys() if k not in filed]

    def tick_log_key(self, node, keys) -> str:
        return ":".join(str(p) for p in self._node_key(node.data))

    def _node_key(self, data) -> tuple:
        return (str(data[1].src),) if data[0] == "file" else self._key(data)

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
        hidden = self.hidden_ticked_note()
        alerts = (f"{hidden}: they are {'simulated' if dry_run else 'organized'} too.",) if hidden else ()
        self.app.push_screen(ConfirmScreen(title, body, alerts, kind="simulate" if dry_run else "destructive"),
                             lambda ok: self._confirmed(ok, selection, dry_run))

    def _confirmed(self, ok: bool | None, selection: list[ShotItem], dry_run: bool) -> None:
        log_event("ui.selection", screen="confirm", control="confirm", value=bool(ok), dry_run=dry_run)
        if not ok or self.plan is None:
            return
        # The scanned plan's destination, not the current settings: the plan's targets were computed from it.
        dest_dir, settings, journal_dir = self.plan.dest_dir, self.settings, self._journal_dir()
        keep_journals = self.cfg.keep_journals
        self._run(ShotProgressScreen(dry_run=dry_run),
                  lambda progress: execute(selection, dest_dir=dest_dir, copy=settings.copy_mode, dry_run=dry_run,
                                           journal_dir=journal_dir, keep_journals=keep_journals,
                                           progress=progress))

    def _run(self, progress_screen: ShotProgressScreen, job) -> None:
        """Run job(progress) in a worker thread behind the progress screen, then show its result."""
        self.app.busy = True
        self._refresh_undo()
        self._progress_screen = progress_screen
        self.app.push_screen(progress_screen)
        self.run_worker(lambda: self._job_worker(job, progress_screen), thread=True, exclusive=True,
                        group="organize")

    def _job_worker(self, job, progress_screen: ShotProgressScreen) -> None:
        # Runs in a worker thread: progress lands on the screen's board (locked), which the UI thread draws.
        try:
            with activity.running():
                result = job(progress_screen.report)
        except OrganizeError as exc:
            self.app.call_from_thread(self._job_stopped, exc)
            return
        except Exception as exc:  # noqa: BLE001 - e.g. an unreadable journal during undo
            log_exception("shots.ui", exc)
            self.app.call_from_thread(self._job_failed, exc)
            return
        progress_screen.finish_all()  # the run ended: the board ends at m of m
        self.app.call_from_thread(self._job_done, result)

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
        self.app.push_screen(ConfirmScreen(title, body, kind="destructive"),
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
