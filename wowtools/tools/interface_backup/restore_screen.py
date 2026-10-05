"""Choose what to restore from a backup and see, as a tree, what the restore changes; the result screen of a restore
or undo."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Label, Static, Tree

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
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import ACCENT, RESULT_HINT, TREE_BINDINGS, TREE_HINT, TwoPaneFocus, result_css, review_hint, theme_colour, two_pane_css
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, action_button

# The review's hint shape, then the keys of this screen. Space here ticks a part or opens a node of the effects tree.
NAV_HINT = review_hint("tick or open") + TREE_HINT + "o restore · b/Esc back"
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


def _error_text(exc: Exception) -> str:
    return str(exc) if isinstance(exc, RestoreError) else f"{type(exc).__name__}: {exc}"


def group_label(name: str, files: int | None) -> Text:
    """A folder group's tree label, the part that tells groups apart first (the tree is narrow at 80 columns):
    "WeakAuras  Interface/AddOns · 2 files"; `files` None for a group that is one file."""
    parent, _, last = name.rpartition("/")
    return Text.assemble((last, "bold"), (f"  {parent}" if parent else "", "dim"),
                         (f" · {plural(files, 'file')}" if files is not None else "", "dim"))


class RestoreTree(Tree):
    """What the restore changes. ← jumps to the left panel (instead of scrolling sideways)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class RestoreScreen(TwoPaneFocus, Screen[RestorePlan | None]):
    """Two panes, like the review: on the left the backup's details, a box per part and Restore / Back; on the
    right a tree of what the restore changes (worked out in a worker each time a box changes); a summary line
    below. Dismisses with the plan to restore, or None."""

    TREE_SELECTOR = "#effects"
    # Narrower than the review (FILTERS_WIDTH): two buttons only, and at 80 columns the tree must show its root
    # and the effect titles ("Newer now than in the backup (N files)") without clipping.
    DEFAULT_CSS = two_pane_css("RestoreScreen", "#effects", width=46)
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("o", "restore", "Restore"),
        Binding("b", "cancel", "Back"),
        Binding("escape", "cancel", "Back", show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
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
        self._last_filter: Widget | None = None

    @property
    def kind_text(self) -> str:
        return "Safety backup (before a restore)" if self.info.is_safety else "Backup"

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("Backup", classes="section")
                yield Static(self._info_text(), id="backup-info")
                yield Label("Restore", classes="section")
                for part in PARTS:
                    yield Ka0sCheckbox(part, True, id=f"part-{part}", disabled=True, compact=True)
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Restore", "apply", id="btn-restore", disabled=True)
                    yield action_button("Back", "neutral", id="btn-back")
                yield NavHint(NAV_HINT)
            # Short: the tree is narrow at 80 columns; the left pane has the kind and the zip.
            yield RestoreTree(Text(f"{self.flavor.display_name} · {self.info.when}", style=ACCENT), id="effects")
        yield Static("", id="summary")
        yield BrandBar()
        yield Footer()

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
        return next(iter(boxes + buttons), None)

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

    def _show_plan(self, plan: RestorePlan) -> None:
        tree = self.query_one("#effects", Tree)
        tree.clear()
        warning = f"bold {theme_colour(self.app, 'warning')}"
        for kind, title, note in EFFECTS:
            items = self._effect_items(kind)
            if not items:
                continue
            count = plural(len(items), "file") if kind in GROUPED else str(len(items))
            label = Text.assemble((f"{title} ({count})", warning if kind in WARN else "bold"), (f"  {note}", "dim"))
            if kind in GROUPED:
                node = tree.root.add(label, data=("effect", kind), expand=True)
                for name, members in group_items(items):
                    single = len(members) == 1 and "/".join(members[0]) == name
                    text = group_label(name, None if single else len(members))
                    if single:
                        node.add_leaf(text, data=("file",))
                    else:
                        node.add(text, data=("group", kind, name), allow_expand=True)  # files load on expand
            else:
                tree.root.add(label, data=("effect", kind), allow_expand=True)  # lines load on expand
        if plan.low_space:
            tree.root.add_leaf(Text(f"⚠ Low disk space on the WoW drive: {human_size(plan.free_bytes)} free, "
                                    f"~{human_size(plan.bytes_needed)} needed", style=warning), data=("note",))
        if restore_lost_nothing(plan):
            success = f"bold {theme_colour(self.app, 'success')}"
            tree.root.add_leaf(Text.assemble(("Nothing on disk would be lost", success),
                                             ("  everything is in the backup", "dim")), data=("note",))
        tree.root.expand()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if node.data is None or node.children:
            return
        if node.data[0] == "group":
            _, kind, name = node.data
            members = next((m for n, m in group_items(self._effect_items(kind)) if n == name), [])
            for part, rel in members:
                node.add_leaf(Text(f"{part}/{rel}"[len(name) + 1:], style="dim"), data=("file",))
        elif node.data[0] == "effect" and node.data[1] not in GROUPED:
            for item in self._effect_items(node.data[1]):
                node.add_leaf(Text(item if isinstance(item, str) else "/".join(item), style="dim"), data=("file",))

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

    DEFAULT_CSS = result_css("RestoreResultScreen")
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
            summary = DataTable(id="result-summary", cursor_type="none", zebra_stripes=True)
            summary.can_focus = False  # read-only summary: not a focus stop
            yield summary
            yield DataTable(id="result-table", classes="result-detail", cursor_type="row", zebra_stripes=True)
        with ButtonRow(classes="buttons"):
            if self.can_undo:
                yield action_button("Undo (z)", "revert", id="undo")
            yield action_button("Rescan (r)", "neutral", id="review")
            yield action_button("Other flavor (f)", "neutral", id="flavors")
            yield action_button("Tools (t)", "neutral", id="tools")
            yield action_button("Quit (q)", "neutral", id="quit")
        hint = RESULT_HINT + ("z undo · " if self.can_undo else "")
        yield NavHint(hint + "r rescan · f other flavor · t tools · q quit")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        r = self.result
        self.sub_title = "Interface Backup · undo result" if r.undo else "Interface Backup · restore result"
        summary = self.query_one("#result-summary", DataTable)
        summary.add_columns("Item", "Value")
        summary.add_rows((Text(item), Text(value)) for item, value in restore_summary_rows(r))
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
