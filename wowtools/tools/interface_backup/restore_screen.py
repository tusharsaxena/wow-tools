"""Choose what to restore from a backup and see, as a tree, what the restore changes; the result screen of a restore
or undo."""
from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, DataTable, Header, Label, Static, Tree

from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor
from wowtools.core.paths import to_stored
from wowtools.core.text import human_size, plural
from wowtools.tools.interface_backup.catalog import BackupInfo
from wowtools.tools.interface_backup.report import (RESTORE_RESULT_COLUMNS, friendly_created, group_items,
                                                    ordered_parts, restore_lost_nothing, restore_result_rows,
                                                    restore_summary, restore_summary_rows)
from wowtools.tools.interface_backup.restore import (BackupContents, RestoreError, RestorePlan, RestoreResult,
                                                     case_key, open_backup, plan_restore)
from wowtools.tools.interface_backup.scanner import PARTS, FlavorScan, scan_flavor
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import ACCENT, TREE_BINDINGS, TREE_HINT, TwoPaneFocus, review_hint, theme_colour, two_pane_css
from wowtools.ui.result_screen import ResultBase, ResultButton, result_bindings, status_colour, status_style
from wowtools.ui.review import ButtonActions, ReviewTree
from wowtools.ui.tree_filter import FILTER_BINDINGS, FILTER_HINT, FilterBar, FilterBox, ModelFilter, ModelNode
from wowtools.ui.warnings_view import WARNINGS_BINDING, SummaryBar, WarningItem, WarningsHost
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, RiskBanner, action_button

# The review's hint shape, then the keys of this screen. Space here ticks a part or opens a node of the effects tree.
NAV_HINT = review_hint("tick or open") + FILTER_HINT + TREE_HINT + "Esc back"
# The tree's top nodes: (kind, title, note). Their children are loaded on expand (groups of files, links, lines).
EFFECTS = (
    ("removed", "Will be removed", "on disk now, not in the backup"),
    ("newer", "Newer now than in the backup", "these changes are lost"),
    ("links_kept", "Links kept", "left as they are"),
    ("links_removed", "Links replaced", "the backup has files there: only the link goes, Undo makes it again"),
    ("unreadable", "Could not be read", "whatever is there is replaced without being listed"),
)
GROUPED = ("removed", "newer")  # listed as folder groups, then files
WARN = ("removed", "newer", "links_removed", "unreadable")  # shown in the warning colour


def flavor_warning_items(scans: Sequence[FlavorScan]) -> list[WarningItem]:
    """The scan errors of these flavors as the warnings view lists them: under the flavor, the part as where (the
    review's and the restore screen's)."""
    return [WarningItem(name, error, scan.flavor.display_name)
            for scan in scans for name, part in scan.parts.items() for error in part.errors]


def _error_text(exc: Exception) -> str:
    return str(exc) if isinstance(exc, RestoreError) else f"{type(exc).__name__}: {exc}"


def group_label(name: str, files: int | None) -> Text:
    """A folder group's tree label, the part that tells groups apart first (the tree is narrow at 80 columns):
    "WeakAuras  Interface/AddOns · 2 files"; `files` None for a group that is one file."""
    parent, _, last = name.rpartition("/")
    return Text.assemble((last, "bold"), (f"  {parent}" if parent else "", "dim"),
                         (f" · {plural(files, 'file')}" if files is not None else "", "dim"))


class RestoreScreen(WarningsHost, FilterBox, ButtonActions, TwoPaneFocus, Screen[RestorePlan | None]):
    """Two panes, like the review: on the left the backup's details, a box per part, the tree filter (nothing to
    tick in the tree: the filter only narrows it) and Restore / Back; on the right a tree of what the restore
    changes (worked out in a worker each time a box changes); a summary line below. Dismisses with the plan to
    restore, or None."""

    TREE_SELECTOR = "#effects"
    LOG_SCREEN = "ibackup_restore"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {"btn-restore": "restore", "btn-back": "cancel"}
    # Narrower than the review (FILTERS_WIDTH): two buttons only, and at 80 columns the tree must show its root
    # and the effect titles ("Newer now than in the backup (N files)") without clipping.
    DEFAULT_CSS = two_pane_css("RestoreScreen", "#effects", width=46)
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("o", "restore", "Restore"),
        Binding("b", "cancel", "Back"),
        Binding("escape", "cancel", "Back", show=False),
        WARNINGS_BINDING,
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        *NAV_BINDINGS,
    ]

    def __init__(self, info: BackupInfo, flavor: Flavor, *, disk_usage: Callable = shutil.disk_usage) -> None:
        super().__init__()
        self.info = info
        self.flavor = flavor
        self.disk_usage = disk_usage
        self.contents: BackupContents | None = None
        self.scan: FlavorScan | None = None
        self.plan: RestorePlan | None = None
        self.problem = ""
        self.summary_text = ""
        self._generation = 0  # bumped per replan: a plan worked out for older boxes is dropped
        self._kept: ModelFilter | None = None  # what the filter keeps of the plan (files load on expand)
        self._last_filter: Widget | None = None

    @property
    def kind_text(self) -> str:
        return "Safety backup (before a restore)" if self.info.is_safety else "Backup"

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield RiskBanner()
                yield Label("Backup", classes="section")
                yield Static(self._info_text(), id="backup-info")
                yield Label("Restore", classes="section")
                for part in PARTS:
                    yield Ka0sCheckbox(part, True, id=f"part-{part}", disabled=True, compact=True)
                yield FilterBar()
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Restore", "overwrite", "o", id="btn-restore", disabled=True)
                    yield action_button("Back", "cancel", "b", id="btn-back")
                yield NavHint(NAV_HINT)
            # Short: the tree is narrow at 80 columns; the left pane has the kind and the zip.
            yield ReviewTree(Text(f"{self.flavor.display_name} · {self.info.when}", style=ACCENT), id="effects")
        yield SummaryBar()
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = "Interface Backup · restore"
        self._tree_message("Comparing the backup with your folders…", "dim")
        self._set_summary("Comparing the backup with your folders…")
        info, flavor = self.info, self.flavor
        self.run_worker(lambda: self._load_worker(info, flavor), thread=True, group="restore-load")

    def _info_text(self) -> Text:
        """The left pane's "Backup" section: flavor, kind and date; size, then (once read) parts and files. No zip
        path: the review shows the folder, the result the zip, and the pane must keep its hint on screen at 80x24."""
        lines = [f"{self.flavor.display_name} · {self.kind_text} from {self.info.when}", human_size(self.info.size)]
        contents = self.contents
        if contents is not None:
            files = sum(len(f) for f in contents.files.values())
            lines[-1] += f" · {', '.join(contents.parts) or 'nothing'} · {plural(files, 'file')}"
            made = friendly_created(contents.created) if contents.created else ""
            if made and made != self.info.when:
                lines.append(f"made {made}")
        return Text("\n".join(lines))

    # --- panes (←/→): TwoPaneFocus ------------------------------------------------------------------
    def first_filter(self) -> Widget | None:
        boxes = [b for b in self.query(Ka0sCheckbox).results(Ka0sCheckbox) if b.focusable]
        buttons = [b for b in self.query("#actions Button").results(Button) if b.focusable]
        return next(iter([*boxes, self.filter_input(), *buttons]), None)

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
        self.query_one("#backup-info", Static).update(self._info_text())
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
                box.label = f"{part} (link: restore by hand)"
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

    def _set_summary(self, text: str, style: str = "") -> None:
        self.summary_text = text
        self.query_one("#summary", Static).update(Text(text, style=style))
        self.refresh_warnings()

    def warning_items(self) -> list[WarningItem]:
        """What this screen's scan of the flavor skipped (a restore replaces whatever is there unlisted)."""
        return flavor_warning_items([self.scan] if self.scan is not None else [])

    def _tree_message(self, text: str, style: str) -> None:
        """The tree holds one line: waiting, a problem or what to do."""
        tree = self.query_one("#effects", Tree)
        tree.clear()
        tree.root.add_leaf(Text(text, style=style), data=("note",))
        tree.root.expand()

    def _replan(self) -> None:
        self._generation += 1
        self.plan = None
        self.query_one("#btn-restore", Button).disabled = True
        if self.problem:
            style = f"bold {theme_colour(self.app, 'error')}"
            self._tree_message(self.problem, style)
            self._set_summary(self.problem, style)
            return
        if self.contents is None or self.scan is None:
            return
        parts = self._chosen()
        if not parts:
            self._tree_message("Tick Interface, WTF or both.", "dim")
            self._set_summary("Nothing is ticked: tick Interface, WTF or both.")
            return
        self._tree_message("Comparing the backup with your folders…", "dim")
        self._set_summary("Comparing the backup with your folders…")
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
            style = f"bold {theme_colour(self.app, 'error')}"
            self._tree_message(error, style)
            self._set_summary(error, style)
            return
        self.plan = plan
        self._show_plan(plan)
        self._set_summary(restore_summary(plan, self.info.when),
                          f"bold {theme_colour(self.app, 'warning')}" if plan.low_space else "")
        self.query_one("#btn-restore", Button).disabled = False

    # --- the tree ----------------------------------------------------------------------------------
    def _effect_items(self, kind: str) -> list:
        plan = self.plan
        return list(getattr(plan, kind)) if plan is not None else []

    def _model(self, plan: RestorePlan) -> list[ModelNode]:
        """The effects as model nodes, with the files a group or an effect loads on expand (the filter matches
        them)."""
        effects = []
        for kind, _title, _note in EFFECTS:
            items = list(getattr(plan, kind))
            if not items:
                continue
            node = ModelNode(("effect", kind))
            if kind in GROUPED:
                for name, members in group_items(items):
                    if len(members) == 1 and "/".join(members[0]) == name:
                        node.children.append(ModelNode(("file", kind, name)))  # a group that is one file
                    else:
                        node.children.append(ModelNode(("group", kind, name),
                                                       [ModelNode(("file", kind, f"{part}/{rel}"[len(name) + 1:],
                                                                   name)) for part, rel in members]))
            else:
                node.children = [ModelNode(("file", kind, item if isinstance(item, str) else "/".join(item)))
                                 for item in items]
            effects.append(node)
        return effects

    @staticmethod
    def _filter_name(data) -> str:
        if data[0] == "effect":
            return next(title for kind, title, _ in EFFECTS if kind == data[1])
        return data[2]

    def _model_filter(self, effects: list[ModelNode]) -> ModelFilter:
        # A file's identity is its effect and text (and, in a group, the group's name: two groups may hold the same
        # embeds.xml), a group's its effect and name: the same for what an expand adds.
        return self.model_filter(effects, lambda n: n.children, lambda n: (self._filter_name(n.data),),
                                 key=lambda n: n.data)

    def filter_changed(self) -> None:
        """The filter text changed: show the plan through it (nothing to rebuild before a plan is worked out)."""
        if self.plan is not None:
            self._show_plan(self.plan)

    def _show_plan(self, plan: RestorePlan) -> None:
        tree = self.query_one("#effects", Tree)
        tree.clear()
        warning = f"bold {theme_colour(self.app, 'warning')}"
        effects = self._model(plan)
        kept = self._kept = self._model_filter(effects)
        for effect in effects:
            if not kept.shows(effect):
                continue
            kind = effect.data[1]
            title, note = next((t, n) for k, t, n in EFFECTS if k == kind)
            items = self._effect_items(kind)
            count = plural(len(items), "file") if kind in GROUPED else str(len(items))
            label = Text.assemble((f"{title} ({count})", warning if kind in WARN else "bold"), (f"  {note}", "dim"))
            if kind in GROUPED:
                node = tree.root.add(label, data=effect.data, expand=True)
                for child in effect.children:
                    if not kept.shows(child):
                        continue
                    name = child.data[2]
                    if child.data[0] == "file":
                        node.add_leaf(group_label(name, None), data=child.data)
                    else:
                        group = node.add(group_label(name, len(child.children)), data=child.data,
                                         allow_expand=True)  # files load on expand
                        self._open_if(group, kept.opens(child))
            else:
                lines = tree.root.add(label, data=effect.data, allow_expand=True)  # lines load on expand
                self._open_if(lines, kept.opens(effect))
        self.note_no_match(tree.root)  # before the notes, which are not items: the filter never hides them
        if plan.low_space:  # the notes are not items: the filter never hides them
            tree.root.add_leaf(Text(f"⚠ Low disk space on the WoW drive: {human_size(plan.free_bytes)} free, "
                                    f"~{human_size(plan.bytes_needed)} needed", style=warning), data=("note",))
        if restore_lost_nothing(plan):
            success = f"bold {theme_colour(self.app, 'success')}"
            tree.root.add_leaf(Text.assemble(("Nothing on disk would be lost", success),
                                             ("  everything is in the backup", "dim")), data=("note",))
        tree.root.expand()

    def _open_if(self, node, opens: bool) -> None:
        """Open a node whose files load on expand when the filter opens it (its matches show)."""
        if opens:
            self._load_files(node)
            node.expand()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        self._load_files(event.node)

    def _load_files(self, node) -> None:
        """A group's files or an effect's lines, those the filter keeps, the first time it opens."""
        if node.data is None or node.children or node.data[0] not in ("group", "effect"):
            return
        if node.data[0] == "effect" and node.data[1] in GROUPED:
            return
        kept = self._kept
        model = next((m for effect in self._model(self.plan) for m in (effect, *effect.children)
                      if m.data == node.data), None) if self.plan is not None else None
        for child in model.children if model is not None else []:
            if kept is None or kept.shows(child):
                node.add_leaf(Text(child.data[2], style="dim"), data=child.data)

    # --- actions ---------------------------------------------------------------------------------
    def action_restore(self) -> None:
        if self.plan is None or self.query_one("#btn-restore", Button).disabled:
            return
        log_event("ui.selection", screen="ibackup_restore", control="restore", value=list(self.plan.parts))
        self.dismiss(self.plan)

    def action_cancel(self) -> None:
        log_event("ui.selection", screen="ibackup_restore", control="back", value=True)
        self.dismiss(None)


class RestoreResultScreen(ResultBase):
    """The outcome of a restore or an undo, per part. Dismisses with "undo", "review", "flavors", "tools" or
    "quit"."""

    LOG_SCREEN = "ibackup_restore_result"
    RESCAN = "review"
    DETAIL_ID = "result-table"
    BINDINGS: ClassVar[list[Binding]] = result_bindings(RESCAN, before=[Binding("z", "choose('undo')", "Undo")])
    STATUS_COLOURS: ClassVar[dict[str, str]] = {"restored": "success", "replaced_left": "warning",
                                                "rolled_back": "warning", "failed": "error"}

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

    def lead_buttons(self) -> list[ResultButton]:
        return [("Undo", "revert", "undo", "z")] if self.can_undo else []

    def result_title(self) -> str:
        return "Interface Backup · undo result" if self.result.undo else "Interface Backup · restore result"

    def summary_rows(self) -> list[tuple[str, str]]:
        return restore_summary_rows(self.result)

    def fill_detail(self, table: DataTable) -> None:
        r = self.result
        table.add_columns(*RESTORE_RESULT_COLUMNS)
        for outcome, (part, kind, reason) in zip(ordered_parts(r), restore_result_rows(r)):
            style = status_style(self.app, status_colour(outcome.kind, self.STATUS_COLOURS) or "warning")
            table.add_row(Text(part), Text(kind, style=style), Text(reason))

    def action_choose(self, choice: str) -> None:
        if choice == "undo" and not self.can_undo:
            return
        super().action_choose(choice)
