"""The Config Copier's review (config tools spec CC2-CC8, X1-X3, X5): the source's files planned onto every other
real character of its flavor (a scan in a worker, planner.plan_copy), shown as the shared character tree, (flavor ›)
account › realm › character › one line per file pair with its status (new, replaced, unchanged, source has no file,
can't be read; ⚠ for the CC7 macro warning). Other flavors' characters are greyed "other flavor", the source
"source". Nothing is ticked at first: Space on a target ticks every file it can get, on a pair that pair only (CC4:
dropping a pair is unticking it); the left pane's file boxes (all ticked) leave a file out for every target. Only a
ticked pair of a ticked file whose status writes something (new, replace) is copied.

The left pane has the source (Change source, p: back to the source picker of the same flavor choice, CP1), the file boxes, the filter and Copy / Dry run / Rescan / Undo last change; Diff under
the tree opens the diff of the highlighted replaced pair (diff_screen.py). Copy and Dry run run the shared client-file
pipeline (RunActions: WoW check, confirm listing the CC7 warnings, progress popup, result screen), then the files are
read again; a scan that finds a Copy that did not finish offers to put the originals back. Ticks are a selection,
not staged work: leaving asks nothing, as on the WTF Cleaner. Dismisses with "flavors", "source", "tools" or "quit"."""
from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Hashable, Iterable, Sequence
from pathlib import Path
from typing import ClassVar, NamedTuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Header, Label, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode

from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Character, Flavor, flavor_name
from wowtools.core.process import wow_check_for
from wowtools.core.sv_apply import Marker, MultiApplyResult
from wowtools.core.text import plural
from wowtools.tools.config_copier.diff_screen import DiffScreen
from wowtools.tools.config_copier.events import SV_TOOL
from wowtools.tools.config_copier.journal import latest_undoable, read_journal, resolve_journal_dir
from wowtools.tools.config_copier.model import COPY_FILES, PairPlan
from wowtools.tools.config_copier.planner import plan_copy
from wowtools.tools.config_copier.report import (FILE_COLUMNS, PAIR_CAPS, PAIR_MINIMUMS, STAGE_TITLES,
                                                 STATUS_COLOURS, UNDO_COLUMNS, character_text, copy_confirm,
                                                 copy_groups, copy_listed, file_rows, pair_cells, recovery_text,
                                                 summary_rows, undo_confirm, undo_detail_rows, undo_summary_rows)
from wowtools.tools.config_copier.runner import COPYABLE, ApplyError, run_copy
from wowtools.tools.config_copier.settings import load_settings, resolve_root
from wowtools.tools.config_copier.undo import (UndoError, UndoResult, leave, pending_recovery, recover, undo_flavors,
                                               undo_run)
from wowtools.ui.branding import BottomBar
from wowtools.ui.character_tree import CharacterNode, character_filter_texts, node_keys, populate_characters
from wowtools.ui.columns import ColumnLayout, GROUP_NAME_MINIMUM, column_text, fit_columns, group_text, natural_widths
from wowtools.ui.counts import count_text
from wowtools.ui.dialogs import (ACCENT, REVIEW_HINT, TREE_BINDINGS, TREE_HINT, ConfirmScreen, ProgressScreen,
                                 UnfinishedRunScreen, relabel_branch, theme_colour, two_pane_css)
from wowtools.ui.result_screen import ResultScreen
from wowtools.ui.review import (MARK_WIDTH, ActionBar, BarTree, FittedRows, ReviewBase, RunActions, SvRecoveryActions,
                                TickModel, WowCheck, tree_room)
from wowtools.ui.tree_filter import FILTER_BINDINGS, FILTER_HINT, FilterBar, TreeFilter
from wowtools.ui.warnings_view import WARNINGS_BINDING, SummaryBar, SummaryLine, WarningItem, WarningsHost, where_text
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, RiskBanner, action_button

TITLE = "Config Copier"
NAV_HINT = REVIEW_HINT + "a all · n none · " + FILTER_HINT + TREE_HINT + "f flavors · t tools"
SOURCE_REASON = "source"
OTHER_FLAVOR_REASON = "other flavor"  # X1: one flavor per run, the source's
NO_DIFF = "Highlight a replaced file first: Diff compares a target's file with what it gets."
NO_MARK = "  "
PAIR_COLUMNS = ColumnLayout(caps=PAIR_CAPS, minimums=PAIR_MINIMUMS, shrink=((1,), (0,)), drop=(2,))
# A greyed character's name · reason (R4): the name gives way, cut in its middle; the reason is never cut, only dropped.
REASON_COLUMNS = ColumnLayout(caps=(None, None), minimums=(GROUP_NAME_MINIMUM, 0), shrink=((0,),))


class PairKey(NamedTuple):
    """The tick key of one (target, file) pair: the target's key (account/realm/name) and the file name."""
    target: str
    name: str


class PairNode(NamedTuple):
    """The data of a pair's tree line: `key` is None when the pair writes nothing (nothing to tick)."""
    kind: str
    key: PairKey | None
    plan: PairPlan


def target_key(character: Character) -> str:
    return f"{character.account}/{character.realm}/{character.name}"


def file_id(name: str) -> str:
    """The left pane box of a file: `file-AddOns-txt`."""
    return "file-" + name.replace(".", "-")


class CopyProgressScreen(ProgressScreen):
    """Shown while a Copy, a dry run, an Undo or a recovery runs."""

    ID_PREFIX = "copier"
    STAGE_TITLES: ClassVar[dict[str, str]] = STAGE_TITLES
    SIMULATED_STAGE = "check"

    def __init__(self, title: str, *, dry_run: bool = False, first_stage: str = "",
                 flavors: Sequence[Flavor] = (), parallelism: int = 1) -> None:
        super().__init__(title, dry_run=dry_run, first_stage=first_stage, units=flavors, parallelism=parallelism,
                         label=lambda flavor: flavor.display_name)


class CopierResultScreen(ResultScreen):
    """`title` is "Copy", "Dry run" or "Undo". With `back` (a dry run: nothing was written) it opens on "Back to
    review", and Esc dismisses with "back"."""

    LOG_SCREEN = "copier_result"
    STATUS_COLOURS: ClassVar = STATUS_COLOURS

    def __init__(self, title: str, summary: list[tuple[str, str]], columns: tuple[str, ...], detail: list[tuple],
                 scope_label: str, *, back: bool = False) -> None:
        super().__init__(f"{TITLE} · {scope_label} · {title} result", summary, columns, detail, back=back)
        self.title_text = title


class CopierReviewScreen(WarningsHost, TreeFilter, SvRecoveryActions, RunActions, FittedRows, ReviewBase, Screen[str]):
    """The targets of a copy from `source` (a character of `source_flavor`), over `flavors` (the flavor picked, or
    all of them). `wow_check` (tests inject one) stands for the running-WoW check."""

    WARNINGS_TITLE = "Warnings"
    WARNINGS_NOUN = "warning"
    SV_TOOL = SV_TOOL  # RunActions: copier.wow_running, the copier.apply / undo / recover error contexts
    RUN_PROGRESS = CopyProgressScreen  # SvRecoveryActions: the progress popup of a recovery
    TREE_SELECTOR = "#targets"
    LOG_SCREEN = "copier_review"
    HIDDEN_NOUN = "file"
    PREFLIGHT_TEXT = "Checking whether WoW is running…"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {"btn-copy": "copy", "btn-dry-run": "dry_run",
                                                "btn-rescan": "rescan", "btn-undo": "undo", "act-diff": "diff",
                                                "btn-source": "change_source"}
    DEFAULT_CSS = two_pane_css("CopierReviewScreen", "#targets") + """
    CopierReviewScreen #source { height: auto; }
    CopierReviewScreen #tree-pane { width: 1fr; }
    CopierReviewScreen #targets { height: 1fr; }
    CopierReviewScreen #tree-actions { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        # the keys of the buttons (left pane and the bar under the tree) are on them (D17)
        Binding("w", "copy", "Write"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
        Binding("d", "diff", "Diff", show=False),
        WARNINGS_BINDING,
        Binding("f", "leave('flavors')", "Flavors"),
        Binding("t", "leave('tools')", "Tools"),
        Binding("p", "change_source", "Change source"),  # CP1: on its button, so out of the footer (D17)
        Binding("q", "app.quit", "Quit"),
        Binding("escape", "leave('flavors')", "Flavors", show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: list[Flavor], scope_label: str,
                 source_flavor: Flavor, source: Character, *, wow_check: WowCheck | None = None) -> None:
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/config-copier.cfg
        self.flavors = list(flavors)
        self.scope_label = scope_label
        self.source_flavor = source_flavor
        self.source = source
        self._injected_check = wow_check
        self.wow_root = cfg.wow_path  # the WoW folder these flavors were read from (see wow_folder_changed)
        self._leaving_for_new_folder = False
        self.plans: dict[PairKey, PairPlan] = {}  # every pair of every target, from the last scan
        self.scanned = False
        self.scan_warnings: list[WarningItem] = []
        self.files: set[str] = set(COPY_FILES)  # the left pane's ticked files (CC3: all of them)
        self.ticked: set[PairKey] = set()  # CC2: no target ticked at first
        self.undoable: Path | None = None  # the newest undoable journal, found by the scan worker
        self.marker: Marker | None = None  # a Copy that did not finish, found by the scan worker
        self.marker_root: Path | None = None
        self._offer_on_resume = False
        self.summary_text = ""
        self._stale = False  # a Copy or Undo changed the files: read them again when the review is shown
        self._counts: Counter[Hashable] = Counter()  # the pair lines the tree shows under each node (R2), per build
        self._pair_widths: dict[Path, tuple[int, ...]] = {}  # a target's pair columns (R4), per build
        self._reason_widths: dict[Path, tuple[int, ...]] = {}  # a realm's greyed characters' columns (R4), per build

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield RiskBanner()
                yield Static(Text.assemble(("Source: ", "bold"), self.source_text()), id="source")
                with ButtonRow(id="source-row", wrap=False):
                    yield action_button("Change source", "navigate", "p", id="btn-source", compact=True)
                yield Label("Files", classes="section")
                for name in COPY_FILES:
                    yield Ka0sCheckbox(name, True, id=file_id(name), compact=True)
                yield FilterBar()
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Write", "overwrite", "w", id="btn-copy")
                    yield action_button("Dry run", "simulate", "y", id="btn-dry-run")
                    yield action_button("Rescan", "refresh", "r", id="btn-rescan")
                    yield action_button("Undo last change", "revert", "z", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="tree-pane"):
                with Vertical(id="scan-box"):
                    yield ProgressBar(id="scan-progress", show_eta=False)
                    yield Static("", id="scan-label")
                yield BarTree(Text(self.scope_label, style=ACCENT), id="targets")
                with ActionBar(id="tree-actions"):
                    yield action_button("Diff", "navigate", "d", id="act-diff", compact=True)
        yield SummaryBar(Text(self.summary_text))
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = f"{TITLE} · {self.scope_label}"
        self.query_one("#scan-box").display = False
        self.query_one("#targets", Tree).focus()
        self._refresh_buttons()
        self._scan()

    def source_text(self) -> str:
        return f"{self.source_flavor.display_name} › {character_text(self.source)}"

    def action_change_source(self) -> None:
        """p, Change source (CP1): back to the source picker of the same flavor choice, through the review's own
        way out (refused while a run writes). The flow opens a fresh review for the new source."""
        self.action_leave("source")

    def first_filter(self) -> Widget | None:
        return self.query_one(f"#{file_id(COPY_FILES[0])}", Checkbox)

    # --- the WoW folder ------------------------------------------------------------------------
    def wow_folder_changed(self) -> bool:
        """True when the shared WoW folder is no longer the one this review read (changed with `s`): back to the
        flavor picker as soon as the review is the screen shown."""
        if self.cfg.wow_path == self.wow_root:
            return False
        if not self._leaving_for_new_folder and self.app.screen is self and not self.app.busy:
            self._leaving_for_new_folder = True
            self.notify("The WoW folder changed: pick the flavor again.", severity="warning")
            self.dismiss("flavors")
        return True

    def on_screen_resume(self) -> None:
        if self.wow_folder_changed():
            return
        if self._stale and self.idle and self.app.screen is self:
            self._scan()
            return
        if self._offer_on_resume and self.marker is not None and self.idle and self.app.screen is self:
            self._offer_on_resume = False
            self.offer_recovery(self.marker)

    # --- state ---------------------------------------------------------------------------------
    @property
    def idle(self) -> bool:
        return not (self._scanning or self._checking or self.app.busy)

    def tickable_keys(self) -> list[PairKey]:
        """Every pair that can be ticked now: it writes something (new, replace) and its file is ticked."""
        return [key for key, plan in self.plans.items() if plan.status in COPYABLE and key.name in self.files]

    def selected_plans(self) -> list[PairPlan]:
        """What Copy writes: the ticked pairs of the ticked files that write something, in plan order (the ticks
        the filter hides included)."""
        return [self.plans[key] for key in self.tickable_keys() if key in self.ticked]

    def _refresh_buttons(self) -> None:
        if not self.is_attached:
            return
        idle = self.idle
        selected = bool(self.selected_plans())
        self.query_one("#btn-copy", Button).disabled = not idle or not selected
        self.query_one("#btn-dry-run", Button).disabled = not idle or not selected
        self.query_one("#btn-rescan", Button).disabled = not idle
        self.query_one("#btn-undo", Button).disabled = not idle or self.undoable is None
        self.query_one("#act-diff", Button).disabled = not idle or self.highlighted_replace() is None
        for box in self.query(Ka0sCheckbox).results(Ka0sCheckbox):
            box.disabled = not idle

    def ticks_frozen(self) -> bool:
        return not self.idle

    def _checking_changed(self) -> None:
        self._refresh_buttons()

    def check_for(self, folders: Iterable[str]) -> WowCheck:
        """The running-WoW check of these flavor folders (an Undo or a recovery may touch another flavor)."""
        return self._injected_check if self._injected_check is not None else wow_check_for(sorted(set(folders)))

    # --- scan ----------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if not self.idle or self.wow_folder_changed():
            return
        self._scan()

    def _scan(self) -> None:
        if not self.idle:
            return
        self._scanning = True
        self._stale = False
        self.show_scan_box(True, f"Reading the files of {self.source_flavor.display_name}")
        self._refresh_buttons()
        root = resolve_root(load_settings(self.tool_cfg), self.cfg.wow_path)
        journal_dir = resolve_journal_dir(self.cfg.wow_path)
        flavor, source = self.source_flavor, self.source
        self.run_worker(lambda: self._scan_worker(flavor, source, root, journal_dir), thread=True, exclusive=True,
                        group="scan")

    def _scan_worker(self, flavor: Flavor, source: Character, root: Path | None, journal_dir: Path | None) -> None:
        warnings: list[WarningItem] = []

        def on_error(path: Path, exc: OSError) -> None:
            warnings.append(WarningItem(where_text(path, flavor.path), exc.strerror or str(exc), flavor.display_name))
        try:
            targets = [c for account in flavor.accounts(on_error) for c in account.real_characters(on_error)
                       if c.path != source.path]
            plans = plan_copy(source, targets, COPY_FILES)
            undoable = latest_undoable(journal_dir)
            marker = pending_recovery(root)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("copier.scan", exc)
            self.app.call_from_thread(self._scan_failed, f"The scan failed: {exc}")
            return
        for plan in plans:
            if plan.status == "unreadable":
                warnings.append(WarningItem(where_text(plan.target.path / plan.name, flavor.path),
                                            plan.problem or "can't be read", flavor.display_name))
        self.app.call_from_thread(self._scanned, plans, warnings, undoable, marker, root)

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self.summary_text = message
        self.query_one("#summary", SummaryLine).show_one_line(message)
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, plans: list[PairPlan], warnings: list[WarningItem], undoable: Path | None,
                 marker: Marker | None, marker_root: Path | None) -> None:
        self._scanning = False
        self.plans = {PairKey(target_key(p.target), p.name): p for p in plans}
        self.scanned = True
        self.scan_warnings = list(dict.fromkeys(warnings))
        self.ticked.intersection_update(self.tickable_keys())  # a pair copied since is unchanged now
        self.undoable, self.marker, self.marker_root = undoable, marker, marker_root
        self._offer_on_resume = False
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self._rebuild()
        self._refresh_buttons()
        self.query_one("#targets", Tree).focus()
        if marker is not None:
            if self.app.screen is self:
                self.offer_recovery(marker)
            else:
                self._offer_on_resume = True

    # --- the tree ------------------------------------------------------------------------------
    def mark(self, keys: Iterable[Hashable]) -> tuple[str, str]:
        """The tick mark over the pairs among `keys` (a character's own key is never ticked: its pairs are)."""
        pairs = [k for k in keys if isinstance(k, PairKey)]
        return self.shown_tick_mark(pairs) if pairs else (NO_MARK, "")

    def _disabled(self, flavor: Flavor):
        if flavor.path != self.source_flavor.path:
            return lambda c: OTHER_FLAVOR_REASON
        return lambda c: SOURCE_REASON if c.path == self.source.path else None

    def _target_texts(self, character: Character) -> tuple[str, ...]:
        """A source-flavor target's filter texts: its flavor first, as for the greyed flavors and the source picker."""
        return (self.source_flavor.display_name, *character_filter_texts(character))

    def _pair_texts(self, key: PairKey) -> tuple[str, ...]:
        plan = self.plans[key]
        return (*self._target_texts(plan.target), key.name)

    def _pairs_of(self, character: Character) -> list[PairKey]:
        ckey = target_key(character)
        return [PairKey(ckey, name) for name in COPY_FILES if name in self.files and PairKey(ckey, name) in self.plans]

    def _shown(self, flavor: Flavor):
        if not self.filtering:
            return None
        if flavor.path != self.source_flavor.path:
            return lambda c: self.text_filter.path_matches((flavor.display_name, *character_filter_texts(c)))
        return lambda c: self.text_filter.path_matches(self._target_texts(c)) or any(
            self.text_filter.path_matches(self._pair_texts(k)) for k in self._pairs_of(c))

    def _add_pairs(self, character: Character, node: TreeNode) -> list[PairKey]:
        """A target's pair lines (the ones the search shows), their columns as wide as their widest cells (R4), and
        their number added to the counts of the target and every node above it (R2)."""
        whole = not self.filtering or self.text_filter.path_matches(self._target_texts(character))
        shown = [key for key in self._pairs_of(character)
                 if whole or self.text_filter.path_matches(self._pair_texts(key))]
        self._pair_widths[character.path] = natural_widths(pair_cells(self.plans[key]) for key in shown)
        account = character.path.parent.parent
        for ident in (("character", character.path), ("realm", account, character.realm), ("account", account),
                      ("flavor", self.source_flavor.folder), ("root",)):
            self._counts[ident] += len(shown)
        keys = []
        for key in shown:
            plan = self.plans[key]
            tick = key if plan.status in COPYABLE else None
            data = PairNode("pair", tick, plan)
            node.add_leaf(self._pair_label(data), data=data)
            if tick is not None:
                keys.append(tick)
        return keys

    def _rebuild(self) -> None:
        tree = self.query_one("#targets", Tree)
        cursor = tree.cursor_node.data if tree.cursor_node is not None else None
        tree.clear()
        self._counts.clear()
        self._pair_widths.clear()
        self.rows_built(tree)  # fitted again once the tree is laid out
        many = len(self.flavors) > 1
        for flavor in self.flavors:
            source_flavor = flavor.path == self.source_flavor.path
            parent = tree.root.add(Text(flavor.display_name), data=["flavor", flavor.folder, ()],
                                   expand=True) if many else tree.root
            keys = populate_characters(parent, flavor, key=target_key, label=lambda c: c.name,
                                       disabled=self._disabled(flavor),
                                       character_extra=self._add_pairs if source_flavor and self.scanned else None,
                                       shown=self._shown(flavor), mark=self.mark)
            if many:
                if self.filtering and not parent.children:
                    parent.remove()
                    continue
                parent.data = ["flavor", flavor.folder, tuple(keys)]
        self._reason_widths = self._greyed_widths(tree)
        self._relabel_all(tree)  # populate_characters labels its nodes before their counts are known
        self.note_no_match(tree.root)
        tree.root.expand()
        self._restore_cursor(tree, cursor)
        self._update_summary()

    @staticmethod
    def _greyed_widths(tree: Tree) -> dict[Path, tuple[int, ...]]:
        """The name · reason columns of the greyed characters the tree shows, per realm folder (R4): siblings of
        another flavor all say `other flavor`, so their reasons line up."""
        rows: dict[Path, list[tuple[str, str]]] = {}
        stack = list(tree.root.children)
        while stack:
            node = stack.pop()
            data = node.data
            if isinstance(data, CharacterNode) and data.reason is not None and data.character is not None:
                rows.setdefault(data.character.path.parent, []).append((data.text, data.reason))
            stack.extend(node.children)
        return {realm: natural_widths(cells) for realm, cells in rows.items()}

    def _greyed_label(self, data: CharacterNode, depth: int, *, opens: bool) -> Text:
        """A greyed character's name · reason, aligned with its realm's other greyed characters and fitted to the
        pane (R4, STD-7.28)."""
        cells = (data.text, data.reason or "")
        natural = (self._reason_widths.get(data.character.path.parent) if data.character is not None else None) \
            or natural_widths([cells])
        room = self._room(depth, opens=opens)
        widths, gap = fit_columns(natural, room, REASON_COLUMNS)
        text = column_text(cells, widths, ("dim", "dim italic"), gap, middle=(0,))
        text.rstrip()
        return text

    def _relabel_all(self, tree: Tree) -> None:
        relabel_branch(tree, None, self._label)
        tree.root.set_label(group_text(self.scope_label, ACCENT, self._count_note(("root",)),
                                       self._room(0, opens=True, mark=0)))

    def refit_rows(self, tree: Tree) -> None:
        """Fit every line again to the tree pane's width (R4, FittedRows)."""
        self._relabel_all(tree)

    def _depth(self, kind: str) -> int:
        """How deep a node of `kind` sits below the root (a flavor's level only with All flavors)."""
        return {"flavor": 1, "account": 1, "realm": 2, "character": 3, "pair": 4}[kind] + \
            (kind != "flavor" and len(self.flavors) > 1)

    def _room(self, depth: int, *, opens: bool, mark: int = MARK_WIDTH) -> int | None:
        """The cells a line may take behind its guides, its ▶ / ▼ when it `opens` and its tick mark (None before
        the tree is laid out)."""
        return tree_room(self.query_one("#targets", Tree), depth, opens=opens, mark=mark) if self.is_attached else None

    def _count_note(self, ident: Hashable) -> str:
        return count_text(self._counts[ident])

    def _restore_cursor(self, tree: Tree, data) -> None:
        if data is None:
            return
        same = (lambda d: isinstance(d, PairNode) and d.plan.target.path == data.plan.target.path
                and d.plan.name == data.plan.name) if isinstance(data, PairNode) else \
            (lambda d: isinstance(d, CharacterNode) and d.kind == data.kind and d.text == data.text
             and d.account.path == data.account.path and d.realm == data.realm) \
            if isinstance(data, CharacterNode) else None
        if same is None:
            return
        stack = list(tree.root.children)
        while stack:
            node = stack.pop()
            if same(node.data):
                if isinstance(node.data, PairNode) and node.parent is not None:
                    node.parent.expand()
                self.call_after_refresh(lambda n=node: tree.move_cursor(n) if n.tree is tree else None)
                return
            stack.extend(node.children)

    def _pair_label(self, data: PairNode) -> Text:
        """A pair line (the leaf, R2): its tick mark, then file · status · warning in columns as wide as its
        siblings' widest cells, fitted to the pane (R4). A pair that writes nothing has no mark and is dim (a
        file that can't be read: its problem in the warning colour); the CC7 mark is in the warning colour."""
        plan = data.plan
        warning = theme_colour(self.app, "warning")
        if data.key is not None:
            mark, styles = self.shown_tick_mark([data.key]), ("", "", warning)
        else:
            mark = (NO_MARK, "")
            styles = ("dim", warning if plan.status == "unreadable" else "dim", warning)
        cells = pair_cells(plan)
        natural = self._pair_widths.get(plan.target.path) or natural_widths([cells])
        room = self._room(self._depth("pair"), opens=False)
        widths, gap = fit_columns(natural, room, PAIR_COLUMNS)
        text = Text.assemble(mark)
        text.append_text(column_text(cells, widths, styles, gap, middle=(0,)))
        text.rstrip()  # a line with no warning beside one with it leaves no padding behind
        return text

    def _character_ident(self, data: CharacterNode) -> Hashable:
        if data.kind == "character" and data.character is not None:
            return "character", data.character.path
        if data.kind == "realm":
            return "realm", data.account.path, data.realm
        return "account", data.account.path

    def _character_label(self, data: CharacterNode) -> Text:
        """An account, realm or character line: its tick mark, its name (bold but a character's) and its count
        (R2), or a greyed character's reason; a character with no pair lines (the source, another flavor's) has
        no count."""
        mark = self.mark(data.keys) if data.keys else (NO_MARK, "")
        depth = self._depth(data.kind)
        opens = data.kind != "character" or self._counts[self._character_ident(data)] > 0
        if data.reason is not None:
            name = self._greyed_label(data, depth, opens=opens)
        else:
            style = "" if data.kind == "character" else "bold"
            name = group_text(data.text, style, self._count_note(self._character_ident(data)) if opens else None,
                              self._room(depth, opens=opens))
        text = Text.assemble(mark)
        text.append_text(name)
        return text

    def _label(self, data) -> Text:
        if isinstance(data, PairNode):
            return self._pair_label(data)
        if isinstance(data, CharacterNode):
            return self._character_label(data)
        mark = self.mark(data[2]) if data[2] else (NO_MARK, "")
        text = Text.assemble(mark)
        text.append_text(group_text(flavor_name(data[1]), "bold", self._count_note(("flavor", data[1])),
                                    self._room(1, opens=True)))
        return text

    def _refresh_labels(self, node: TreeNode | None = None) -> None:
        relabel_branch(self.query_one("#targets", Tree), node, self._label)
        self._update_summary()

    def highlighted_replace(self) -> PairPlan | None:
        if not self.is_attached:
            return None
        node = self.query_one("#targets", Tree).cursor_node
        data = None if node is None else node.data
        return data.plan if isinstance(data, PairNode) and data.plan.status == "replace" else None

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.control.id == "targets":
            self._update_summary()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        name = next((n for n in COPY_FILES if file_id(n) == event.checkbox.id), None)
        if name is None:
            return
        event.stop()
        (self.files.add if event.value else self.files.discard)(name)
        log_event("ui.selection", screen=self.LOG_SCREEN, control="file", value=name, checked=event.value)
        self._schedule_rebuild()
        self._refresh_buttons()

    # --- summaries -------------------------------------------------------------------------------
    def warning_items(self) -> list[WarningItem]:
        return list(self.scan_warnings)

    def _where(self, node: TreeNode | None) -> str:
        names = []
        while node is not None and node.data is not None:
            data = node.data
            names.append(data.plan.name if isinstance(data, PairNode) else
                         data.text if isinstance(data, CharacterNode) else flavor_name(data[1]))
            node = node.parent
        return " › ".join(reversed(names)) or self.scope_label

    def _update_summary(self) -> None:
        if not self.is_attached or not self.scanned:
            return
        selected = self.selected_plans()
        targets = len({p.target.path for p in selected})
        tree = self.query_one("#targets", Tree)
        self.summary_text = (f"Selected: {self._where(tree.cursor_node)}    Ticked: "
                             f"{plural(len(selected), 'file')} for {plural(targets, 'character')}")
        hidden = self.hidden_ticked_note()
        if hidden:
            self.summary_text += f"    {hidden}"
        self.query_one("#summary", Static).update(Text(self.summary_text))
        self.refresh_warnings()
        self._refresh_buttons()

    # --- ticks -----------------------------------------------------------------------------------
    def tick_model(self) -> TickModel:
        return TickModel.of_ticked(self.ticked)

    def node_tick_keys(self, node) -> tuple[PairKey, ...]:
        data = node.data
        if isinstance(data, PairNode):
            return (data.key,) if data.key is not None else ()
        if isinstance(data, CharacterNode):
            return tuple(k for k in node_keys(node) if isinstance(k, PairKey))
        if isinstance(data, list) and data and data[0] == "flavor":
            return tuple(k for k in data[2] if isinstance(k, PairKey))  # not the characters' own keys
        return ()

    def tick_log_key(self, node, keys) -> str:
        return self._where(node)

    def all_tick_keys(self) -> Collection[Hashable]:
        return self.tickable_keys()

    def filter_texts(self, key) -> tuple[str, ...]:
        return self._pair_texts(key)

    # --- Diff ------------------------------------------------------------------------------------
    def action_diff(self) -> None:
        if not self.idle:
            return
        plan = self.highlighted_replace()
        if plan is None:
            self.notify(NO_DIFF)
            return
        log_event("ui.selection", screen=self.LOG_SCREEN, control="diff", value=f"{plan.target.label}/{plan.name}")
        self.app.push_screen(DiffScreen(plan, character_text(self.source)))

    # --- runs: copy, dry run, undo (RunActions) --------------------------------------------------------
    def run_backup_dir(self) -> Path | None:
        return load_settings(self.tool_cfg).backup_dir

    def _set_stale(self) -> None:
        self._stale = True

    def _mark_stale(self) -> None:
        self._set_stale()
        if self.idle and self.is_attached and self.app.screen is self:
            self._scan()

    def action_copy(self) -> None:
        self._start(dry_run=False)

    def action_dry_run(self) -> None:
        self._start(dry_run=True)

    def _start(self, dry_run: bool) -> None:
        """Copy / Dry run of the ticked pairs. A dry run writes nothing, so it needs no WoW check, backup folder or
        settled unfinished run."""
        plans = self.selected_plans()
        if not self.idle or not plans or self.wow_folder_changed():
            return
        log_event("ui.selection", screen=self.LOG_SCREEN, control="dry_run" if dry_run else "copy", value=True)
        if dry_run:
            self._show_confirm(plans, True, [])
            return
        if self.marker is not None:
            self.offer_recovery(self.marker)
            return
        if self._backup_dir_refused():
            return
        check = self.check_for([self.source_flavor.folder])
        self._check_wow(check, lambda running: self._after_copy_preflight(plans, check, running))

    def _after_copy_preflight(self, plans: list[PairPlan], check: WowCheck, running: list[str] | None) -> None:
        alerts: list[str] = []
        if not self._refused_while_running(running, alerts):
            self._show_confirm(plans, False, alerts, check)

    def _show_confirm(self, plans: list[PairPlan], dry_run: bool, extra: list[str],
                      check: WowCheck | None = None) -> None:
        """The confirm: what goes where, one group per target in its detail tree, the CC7 warnings as a counted
        list (STD-7.26)."""
        title, body, alerts = copy_confirm(self.source, self.source_flavor.folder, plans, dry_run=dry_run)
        hidden = self.hidden_ticked_note()
        if hidden:
            extra = [*extra, f"{hidden}; they are copied too."]
        self.app.push_screen(ConfirmScreen(title, body, (*extra, *alerts),
                                           kind="simulate" if dry_run else "overwrite",
                                           groups=copy_groups(plans), listed=copy_listed(plans)),
                             lambda ok: self._copy_confirmed(ok, plans, dry_run, check))

    def _copy_confirmed(self, ok: bool | None, plans: list[PairPlan], dry_run: bool, check: WowCheck | None) -> None:
        log_event("ui.selection", screen="confirm", control="copy_confirm", value=bool(ok), dry_run=dry_run)
        wow_root = self.cfg.wow_path
        if not ok or wow_root is None or not self.idle:
            return
        root, journal_dir = resolve_root(load_settings(self.tool_cfg), wow_root), resolve_journal_dir(wow_root)
        if root is None or journal_dir is None:
            return
        flavor, source = self.source_flavor, self.source
        screen = CopyProgressScreen("Simulating the copy" if dry_run else "Copying the files", dry_run=dry_run,
                                    flavors=[flavor])
        keep_snapshots, keep_journals = self.cfg.keep_backups, self.cfg.keep_journals
        self.start_run(screen, lambda: run_copy(flavor, source, plans, root=root, journal_dir=journal_dir,
                                                keep_journals=keep_journals, keep_snapshots=keep_snapshots,
                                                dry_run=dry_run, wow_check=check, progress=screen.report),
                       self._copied, name="apply", failure="The copy stopped unexpectedly",
                       stale_on_crash=not dry_run, expected=(ApplyError,))

    def _copied(self, result: MultiApplyResult) -> None:
        kept = result.dry_run or not (result.edited or result.rolled_back or result.failed)
        if not kept:
            self._set_stale()
        self._refresh_buttons()
        if result.stopped is not None:
            self.notify(f"{result.stopped.flavor.display_name}: {result.stopped.error}", title="Copy stopped",
                        severity="error", timeout=20)
        self.app.push_screen(CopierResultScreen("Dry run" if result.dry_run else "Copy",
                                                summary_rows(result, self.source), FILE_COLUMNS, file_rows(result),
                                                self.scope_label, back=kept), self._after_result)

    def _after_result(self, choice: str | None) -> None:
        if choice in ("flavors", "tools", "quit"):
            self.action_leave(choice)
        elif choice == "back":
            return
        else:
            self._scan()

    def action_undo(self) -> None:
        """z: put back the files the newest Copy replaced and remove those it created, after the WoW check and a
        confirm."""
        if not self.idle or self.wow_folder_changed():
            return
        log_event("ui.selection", screen=self.LOG_SCREEN, control="undo", value=True)
        path = self.undoable
        if path is None:
            self.notify("Nothing to undo")
            return
        if self._backup_dir_refused():
            return
        try:
            journal = read_journal(path)
        except (OSError, ValueError) as exc:
            self.notify(f"The journal could not be read: {exc}", severity="error")
            return
        check = self.check_for(e["flavor"] for e in journal.entries)
        self._check_wow(check, lambda running: self._after_undo_preflight(path, journal, check, running))

    def _after_undo_preflight(self, path: Path, journal, check: WowCheck, running: list[str] | None) -> None:
        extra: list[str] = []
        if self._refused_while_running(running, extra):
            return
        title, body, alerts = undo_confirm(journal)
        self.app.push_screen(ConfirmScreen(title, body, (*extra, *alerts), kind="destructive"),
                             lambda ok: self._undo_confirmed(ok, path, check, journal))

    def _undo_confirmed(self, ok: bool | None, path: Path, check: WowCheck, journal) -> None:
        log_event("ui.selection", screen="confirm", control="undo_confirm", value=bool(ok))
        wow_root = self.cfg.wow_path
        if not ok or wow_root is None or not self.idle:
            return
        root = resolve_root(load_settings(self.tool_cfg), wow_root)
        if root is None:
            return
        parallelism = self.cfg.parallelism
        screen = CopyProgressScreen("Undoing the last change", first_stage="undo",
                                    flavors=undo_flavors(wow_root, journal.entries), parallelism=parallelism)
        keep_snapshots = self.cfg.keep_backups
        self.start_run(screen, lambda: undo_run(path, wow_root=wow_root, root=root, keep_snapshots=keep_snapshots,
                                                wow_check=check, progress=screen.report, parallelism=parallelism,
                                                on_flavor=screen.start_unit, on_flavor_done=screen.finish_unit),
                       self._undone, name="undo", failure="Undo stopped unexpectedly", stale_on_crash=True,
                       expected=(UndoError,))

    def _undone(self, result: UndoResult) -> None:
        self._set_stale()
        self._refresh_buttons()
        self.app.push_screen(CopierResultScreen("Undo", undo_summary_rows(result), UNDO_COLUMNS,
                                                undo_detail_rows(result), self.scope_label), self._after_result)

    # --- recovery (SvRecoveryActions) -----------------------------------------------------------------
    def recovery_screen(self, marker: Marker) -> Screen:
        return UnfinishedRunScreen(recovery_text(marker), marker)

    def recovery_root(self) -> Path | None:
        return self.marker_root if self.marker_root is not None else \
            resolve_root(load_settings(self.tool_cfg), self.cfg.wow_path)

    def run_leave(self, marker: Marker, *, root: Path) -> bool:
        return leave(marker, root=root)

    def run_recover(self, marker: Marker, **kwargs) -> UndoResult:
        return recover(marker, **kwargs)

    def recovery_done(self) -> None:
        self._mark_stale()
