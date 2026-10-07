"""The Saved Variables Browser's review (spec §5, D11, D12, D18): every SavedVariables file of the chosen flavors as a
tree, flavor › account › Account-wide / Realm › Character › Addon.lua (size) › keys, loaded lazily: the scan only
lists the files, a file is read and parsed when it is opened and a table when it is opened (in a worker, model.py).
The left pane has the shared risk banner (D37), the filter, the staged/ticked summary and the run buttons; the
bar under the tree acts on the highlighted key. Search (S) opens the search popup (it only finds, D38) and runs the
search in a worker with the shared progress popup; its hits fill the Results view (v switches views): flavor ›
account › owner › file › one leaf per hit, `path = old`, all ticked. There Edit value and Rename key act on every
ticked hit (else the highlighted one) and stage one edit per hit (D39, bulk.py), shown with the same marks as in
Browse; Unstage drops a hit's edit. Ticks only select: Apply (w), Dry run (y) and Undo last change (z) run the shared
SavedVariables pipeline (RunActions: WoW check, confirm with the USE AT YOUR OWN RISK disclaimer, progress popup,
result screen), then the files are read again; a scan that finds an Apply that did not finish offers to put the
originals back. Dismisses with "flavors", "tools" or "quit" (ToolFlow._after_review)."""
from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Header, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode

from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor
from wowtools.core.luasv import encode_value
from wowtools.core.process import wow_check_for
from wowtools.core.sv_apply import Marker
from wowtools.core.svfiles import SvFile
from wowtools.core.text import human_size, plural
from wowtools.tools.sv_browser.bulk import (BulkResult, new_value, read_tables, stage_renames, stage_values,
                                            table_key)
from wowtools.tools.sv_browser.editor import ApplyError, MultiApplyResult, apply_plan
from wowtools.tools.sv_browser.events import SV_TOOL
from wowtools.tools.sv_browser.journal import latest_undoable, read_journal, resolve_journal_dir
from wowtools.tools.sv_browser.model import ERROR, MORE, Node, SvDocument, key_text, node_text, scalar_text
from wowtools.tools.sv_browser.ops import (FieldEdit, Plan, Staging, key_input, key_problem, parse_key, path_text,
                                           typed_path, value_problem)
from wowtools.tools.sv_browser.popups import (NOT_TYPABLE, EditValueScreen, RenameKeyScreen, SearchScreen,
                                              delete_confirm)
from wowtools.tools.sv_browser.report import (FILE_COLUMNS, STAGE_TITLES, UNDO_COLUMNS, apply_confirm, apply_groups,
                                              file_rows, recovery_text, summary_rows, undo_confirm, undo_detail_rows,
                                              undo_summary_rows)
from wowtools.tools.sv_browser.result_screen import TITLE, SvResultScreen
from wowtools.tools.sv_browser.scanner import FlavorFiles, ScanResult, scan_flavors
from wowtools.tools.sv_browser.search import (REPLACE_BOOLEAN, REPLACE_NUMBER, REPLACE_STRING, Hit, SearchResult,
                                              SearchSpec, run_search)
from wowtools.tools.sv_browser.settings import load_settings, resolve_root
from wowtools.tools.sv_browser.undo import UndoError, UndoResult, leave, pending_recovery, recover, undo_run
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import (ACCENT, REVIEW_HINT, TREE_BINDINGS, TREE_HINT, ConfirmScreen,
                                 ProgressScreen, UnfinishedRunScreen, relabel_branch, theme_colour, two_pane_css)
from wowtools.ui.review import ActionBar, BarTree, ReviewBase, RunActions, TickModel, WowCheck
from wowtools.ui.tree_filter import (FILTER_BINDINGS, FILTER_HINT, FilterBar, ModelFilter, ModelNode, TextFilter,
                                     TreeFilter)
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, RiskBanner, action_button

BROWSE, RESULTS = "Browse", "Results"  # the tree's two views (v): the files, and the hits of the last search
READING = "Reading…"
NAV_HINT = REVIEW_HINT + "a all · n none · " + FILTER_HINT + TREE_HINT + "f flavors · t tools"
# Space / a / n where nothing can be ticked (they stay keys, as on every review): why not.
NO_TICKS_BROWSE = "Nothing to tick here: the results of a search are ticked (S, then v)."
# The Results view's groups (flavor › account › owner › file, each with the hits under it) and its leaves ("hit").
RESULT_GROUPS = ("r-flavor", "r-account", "r-owner", "r-file")
GROUP_KINDS = ("root", "flavor", "account", "realm", "owner", *RESULT_GROUPS)  # what x opens (no file is read)
OPEN_KINDS = ("root", "flavor", "account", "owner", *RESULT_GROUPS)  # open when first shown (realms, files closed)
NOTHING_FOUND = "Nothing found."
READ_TABLES = "Reading the tables of the keys to rename"
READ_UNSTAGE_TABLE = "Reading the table of the key to unstage"
# The bar under the tree, acting on the highlighted key: (id, label, kind of action, action, key).
TREE_ACTIONS = (
    ("act-edit", "Edit value", "overwrite", "edit_value", "e"),
    ("act-rename", "Rename key", "overwrite", "rename_key", "k"),
    ("act-delete", "Delete key", "destructive", "delete_key", "d"),
    ("act-unstage", "Unstage", "cancel", "unstage", "backspace"),
    ("act-view", "View", "navigate", "switch_view", "v"),
)
# The marks of a staged key (D12), after its label: its new name, its new value, or deleted.
RENAME_MARK, VALUE_MARK, DELETE_MARK = "→", "✎", "✗ deleted"


class SearchProgressScreen(ProgressScreen):
    """Shown while a search runs: one row, the files searched of those in scope, and the file last searched."""

    ID_PREFIX = "svb-search"
    STAGE_TITLES: ClassVar[dict[str, str]] = {"search": "Searching", "tables": "Reading"}


class RunProgressScreen(ProgressScreen):
    """Shown while an Apply, a dry run, an Undo or a recovery runs. An Apply has one row per flavor in turn (its
    reports name the flavor: report_unit); an Undo of several flavors backs them up up to `parallelism` at once,
    one row each."""

    ID_PREFIX = "svb"
    STAGE_TITLES: ClassVar[dict[str, str]] = STAGE_TITLES
    SIMULATED_STAGE = "check"

    def __init__(self, title: str, *, dry_run: bool = False, first_stage: str = "",
                 flavors: Sequence[Flavor] = (), parallelism: int = 1) -> None:
        super().__init__(title, dry_run=dry_run, first_stage=first_stage, units=flavors, parallelism=parallelism,
                         label=lambda flavor: flavor.display_name)


def ident(data) -> Hashable:
    """A node's identity across rebuilds and rescans (to keep what is open and the cursor)."""
    kind = data[0]
    if kind == "root":
        return ("root",)
    if kind == "hit":
        return kind, data[1]
    if kind == "r-file":
        return kind, data[1].path
    if kind in RESULT_GROUPS:
        return kind, data[1].folder, *data[2:-1]
    if kind == "file":
        return kind, data[1].path
    if kind == "node":
        file, node = data[1], data[2]
        if node.kind in (MORE, ERROR):
            return kind, file.path, node.kind, typed_path(node.parent.path) if node.parent is not None else ()
        return kind, file.path, node.kind, typed_path(node.path)
    folder = data[1].flavor.folder
    if kind == "flavor":
        return kind, folder
    if kind == "problem":
        return kind, folder, data[2]
    account = data[2].name
    if kind == "account":
        return kind, folder, account
    if kind == "realm":
        return kind, folder, account, data[3]
    return kind, folder, account, data[3].label  # owner


class SvReviewScreen(TreeFilter, RunActions, ReviewBase, Screen[str]):
    """The SavedVariables files of the chosen flavors. `wow_check` (tests inject one) stands for the running-WoW
    check of every flavor."""

    SV_TOOL = SV_TOOL  # RunActions: svb.wow_running, the svb.search / apply / undo / recover error contexts
    TREE_SELECTOR = "#browse"
    LOG_SCREEN = "svb_review"
    HIDDEN_NOUN = "result"
    PREFLIGHT_TEXT = "Checking whether WoW is running…"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {
        "btn-search": "search", "btn-apply": "apply", "btn-dry-run": "dry_run", "btn-rescan": "rescan",
        "btn-undo": "undo", **{button_id: name for button_id, _, _, name, _ in TREE_ACTIONS}}
    DEFAULT_CSS = two_pane_css("SvReviewScreen", "#browse") + """
    SvReviewScreen #pending { height: auto; margin-top: 1; }
    SvReviewScreen #search-row { margin-top: 1; height: auto; }
    SvReviewScreen #search-row Button { min-width: 0; width: auto; }
    SvReviewScreen #tree-pane { width: 1fr; }
    SvReviewScreen #browse { height: 1fr; }
    SvReviewScreen #tree-actions { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        # the keys of the buttons (left pane and the bar under the tree) are on them (D17)
        Binding("S", "search", "Search"),
        Binding("w", "apply", "Apply"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
        Binding("e", "edit_value", "Edit value", show=False),
        Binding("k", "rename_key", "Rename key", show=False),
        Binding("d", "delete_key", "Delete key", show=False),
        Binding("backspace", "unstage", "Unstage", show=False),
        Binding("v", "switch_view", "View", show=False),
        Binding("f", "leave('flavors')", "Flavors"),
        Binding("t", "leave('tools')", "Tools"),
        Binding("q", "leave('quit')", "Quit"),
        Binding("escape", "leave('flavors')", "Flavors", show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: list[Flavor], scope_label: str, *,
                 wow_check: WowCheck | None = None) -> None:
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/sv-browser.cfg
        self.flavors = list(flavors)
        self.scope_label = scope_label
        self._injected_check = wow_check
        self.wow_check = wow_check if wow_check is not None else wow_check_for([f.folder for f in self.flavors])
        self.wow_root = cfg.wow_path  # the WoW folder these flavors were read from (see wow_folder_changed)
        self._leaving_for_new_folder = False
        self.settings = load_settings(tool_cfg)
        self.scan: ScanResult | None = None
        self.docs: dict[Path, SvDocument] = {}  # the files opened since the scan
        self.staging = Staging()
        self.hits: list[Hit] | None = None  # the last search's hits; None: no search since the scan
        self.search_result: SearchResult | None = None
        self.last_spec: SearchSpec | None = None  # the search popup starts with it
        self.ticked: set[int] = set()  # the ticked results (indexes into hits): what a bulk edit acts on (D39)
        self.view = BROWSE
        self.undoable: Path | None = None  # the newest undoable journal, found by the scan worker
        self.marker: Marker | None = None  # an Apply that did not finish, found by the scan worker
        self.marker_root: Path | None = None  # the tool folder the marker was read from (settled there)
        self._offer_on_resume = False  # the scan found the marker while another screen was shown
        self.summary_text = ""
        self._expanded: dict[Hashable, bool] = {}  # what the user opened and closed (kept across rebuilds)
        self._tree_nodes: dict[Hashable, TreeNode] = {}  # the tree's nodes by ident, for a load that finishes
        self._loading: set[Hashable] = set()  # nodes whose file or table is being read in a worker
        self._generation = 0  # a rescan drops what a load still running would add
        self._scanning = False
        self._checking = False
        self._stale = False  # an Apply or Undo changed the files: read them again when the review is shown

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield RiskBanner()
                yield FilterBar()
                yield Static(self._pending_line(), id="pending")
                with ButtonRow(id="search-row", wrap=False):
                    yield action_button("Search", "navigate", "S", id="btn-search")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Apply", "destructive", "w", id="btn-apply")
                    yield action_button("Dry run", "simulate", "y", id="btn-dry-run")
                    yield action_button("Rescan", "navigate", "r", id="btn-rescan")
                    yield action_button("Undo last change", "revert", "z", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="tree-pane"):
                with Vertical(id="scan-box"):
                    yield ProgressBar(id="scan-progress", show_eta=False)
                    yield Static("", id="scan-label")
                yield BarTree(Text(self.scope_label), id="browse")
                with ActionBar(id="tree-actions"):
                    for button_id, label, kind, _, key in TREE_ACTIONS:
                        yield action_button(label, kind, key, id=button_id, compact=True)
        yield Static(Text(self.summary_text), id="summary")
        yield BottomBar()

    def on_mount(self) -> None:
        self._set_sub_title()
        self.query_one("#scan-box").display = False
        self.query_one("#browse", Tree).focus()
        self._refresh_buttons()
        self._scan()

    def _set_sub_title(self) -> None:
        self.sub_title = f"{TITLE} · {self.scope_label} · {self.view}"

    # --- panes (←/→): TwoPaneFocus ------------------------------------------------------------------
    def first_filter(self) -> Widget | None:
        return self.filter_input()

    # --- the WoW folder ------------------------------------------------------------------------
    def wow_folder_changed(self) -> bool:
        """True when the shared WoW folder is no longer the one these flavors came from (changed with `s`). The
        review then goes back to the flavor picker as soon as it is the screen shown."""
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
        self.settings = load_settings(self.tool_cfg)
        if self._offer_on_resume and self.marker is not None and self.idle and self.app.screen is self:
            self._offer_on_resume = False
            self.offer_recovery(self.marker)

    # --- state ---------------------------------------------------------------------------------
    @property
    def idle(self) -> bool:
        """Nothing is scanning, checking or running: the actions are open."""
        return not (self._scanning or self._checking or self.app.busy)

    @property
    def pending(self) -> int:
        """Staged edits: what an Apply would write (and leaving would drop). Ticks only select (D39)."""
        return self.staging.count

    @property
    def tickable(self) -> bool:
        """The tree shows results that can be ticked: the Results view of a search that found something."""
        return self.view == RESULTS and bool(self.hits)

    def _refresh_buttons(self) -> None:
        if not self.is_attached:
            return
        idle = self.idle
        self.query_one("#btn-search", Button).disabled = not idle or self.scan is None
        self.query_one("#btn-apply", Button).disabled = not idle or not self.pending
        self.query_one("#btn-dry-run", Button).disabled = not idle or not self.pending
        self.query_one("#btn-rescan", Button).disabled = not idle
        self.query_one("#btn-undo", Button).disabled = not idle or self.undoable is None
        self.query_one("#act-view", Button).disabled = self.hits is None
        if self.view == RESULTS:  # D39: Edit value and Rename key act on the ticked (else highlighted) hits
            hit = self.highlighted_hit()
            off = not idle or not (self.ticked or hit is not None)  # bulk_targets(), without building the list
            self.query_one("#act-edit", Button).disabled = off
            self.query_one("#act-rename", Button).disabled = off
            self.query_one("#act-delete", Button).disabled = True  # Delete key stays single-key, in Browse
            self.query_one("#act-unstage", Button).disabled = not idle or hit is None or \
                self.staging.hit_edit(hit) is None
            return
        doc, node = self.highlighted()
        off = not idle or node is None
        self.query_one("#act-edit", Button).disabled = off or self.staging.set_problem(doc, node, "") is not None
        self.query_one("#act-rename", Button).disabled = off or \
            self.staging.rename_problem(doc, node, node.key) is not None
        self.query_one("#act-delete", Button).disabled = off or self.staging.delete_problem(doc, node) is not None
        self.query_one("#act-unstage", Button).disabled = off or self.staging.edit_for(doc, node) is None

    def ticks_frozen(self) -> bool:
        return not self.idle

    def _checking_changed(self) -> None:
        self._refresh_buttons()

    def check_for(self, folders: Iterable[str]) -> WowCheck:
        """The running-WoW check of these flavor folders (an Undo or a recovery may touch a flavor that is not
        being reviewed)."""
        return self._injected_check if self._injected_check is not None else wow_check_for(sorted(set(folders)))

    # --- scan ----------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if not self.idle or self.wow_folder_changed():
            return
        if self.pending:
            self.app.push_screen(ConfirmScreen("Discard the staged edits?",
                                               f"A rescan reads the files again and drops {self._pending_words()}; "
                                               "nothing has been written.", kind="destructive"),
                                 lambda ok: self._scan() if ok else None)
            return
        self._scan()

    def _scan(self) -> None:
        if not self.idle:
            return
        self.settings = load_settings(self.tool_cfg)
        self._scanning = True
        self._stale = False
        self._generation += 1
        self.show_scan_box(True, "Listing the SavedVariables files")
        self._refresh_buttons()
        flavors = list(self.flavors)
        root, journal_dir = resolve_root(self.settings, self.cfg.wow_path), resolve_journal_dir(self.cfg.wow_path)
        self.run_worker(lambda: self._scan_worker(flavors, root, journal_dir), thread=True, exclusive=True,
                        group="scan")

    def _scan_worker(self, flavors: list[Flavor], root: Path | None, journal_dir: Path | None) -> None:
        def progress(flavor: Flavor, current: int, total: int, label: str) -> None:
            self.app.call_from_thread(self._scan_progress, current, total, f"Listed {label}")

        try:
            scan = scan_flavors(flavors, progress=progress)
            undoable = latest_undoable(journal_dir)
            marker = pending_recovery(root)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("svb.scan", exc)
            self.app.call_from_thread(self._scan_failed, f"The scan failed: {exc}")
            return
        self.app.call_from_thread(self._scanned, scan, undoable, marker, root)

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self.summary_text = message
        self.query_one("#summary", Static).update(Text(message))
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, scan: ScanResult, undoable: Path | None, marker: Marker | None,
                 marker_root: Path | None = None) -> None:
        self._scanning = False
        self.scan, self.undoable, self.marker, self.marker_root = scan, undoable, marker, marker_root
        self._offer_on_resume = False
        self.docs = {}
        self.staging.clear()
        self.hits, self.search_result, self.view = None, None, BROWSE
        self.ticked.clear()
        self._loading.clear()
        self._set_sub_title()
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self._rebuild()
        self._refresh_buttons()
        self.query_one("#browse", Tree).focus()
        if marker is not None:
            if self.app.screen is self:
                self.offer_recovery(marker)
            else:  # help or the settings are shown: their answer could not run there (Preflight), offer it on return
                self._offer_on_resume = True

    # --- the model the tree shows ------------------------------------------------------------------
    def document(self, file: SvFile) -> SvDocument:
        doc = self.docs.get(file.path)
        if doc is None:
            doc = self.docs[file.path] = SvDocument(file)
        return doc

    def _model(self) -> list[ModelNode]:
        """The tree as model nodes: in Browse the files and what has been read of them (the filter matches only
        that); in Results the hits."""
        if self.view == RESULTS:
            return self._results_model()
        flavors = []
        for flavor in self.scan.flavors if self.scan is not None else ():
            node = ModelNode(("flavor", flavor))
            if flavor.error:
                node.children.append(ModelNode(("problem", flavor, flavor.error)))
            node.children += [ModelNode(("problem", flavor, w.message)) for w in flavor.warnings]
            for account in flavor.accounts:
                account_node = ModelNode(("account", flavor, account))
                realms: dict[str, ModelNode] = {}
                for owner in account.owners:
                    owner_node = ModelNode(("owner", flavor, account, owner),
                                           [self._file_model(f) for f in owner.files])
                    if owner.character is None:
                        account_node.children.append(owner_node)
                        continue
                    realm = owner.character.realm
                    if realm not in realms:
                        realms[realm] = ModelNode(("realm", flavor, account, realm))
                        account_node.children.append(realms[realm])
                    realms[realm].children.append(owner_node)
                node.children.append(account_node)
            flavors.append(node)
        return flavors

    def _results_model(self) -> list[ModelNode]:
        """The Results view: flavor › account › owner › file › one leaf per hit, in the order the search found them.
        A group's data ends with the indexes of the hits under it (its tick keys)."""
        tree: dict = {}
        for index, hit in enumerate(self.hits or ()):
            file = hit.file
            accounts = tree.setdefault(file.flavor.folder, (file.flavor, {}))[1]
            owners = accounts.setdefault(file.account, {})
            files = owners.setdefault(file.owner, {})
            files.setdefault(file.path, (file, []))[1].append(index)
        flavors = []
        for flavor, accounts in tree.values():
            account_nodes = []
            for account, owners in accounts.items():
                owner_nodes = []
                for owner, files in owners.items():
                    file_nodes = [ModelNode(("r-file", file, tuple(hits)), [ModelNode(("hit", i)) for i in hits])
                                  for file, hits in files.values()]
                    owner_nodes.append(ModelNode(("r-owner", flavor, account, owner, _under(file_nodes)),
                                                 file_nodes))
                account_nodes.append(ModelNode(("r-account", flavor, account, _under(owner_nodes)), owner_nodes))
            flavors.append(ModelNode(("r-flavor", flavor, _under(account_nodes)), account_nodes))
        return flavors

    def _file_model(self, file: SvFile) -> ModelNode:
        doc = self.docs.get(file.path)
        roots = doc.roots() if doc is not None and doc.loaded else []
        return ModelNode(("file", file), [self._key_model(file, n) for n in roots])

    def _key_model(self, file: SvFile, node: Node) -> ModelNode:
        return ModelNode(("node", file, node), [self._key_model(file, c) for c in node.children or ()])

    def _children_model(self, data) -> list[ModelNode]:
        """The model children of a file or table node (what a finished load adds)."""
        if data[0] == "file":
            return self._file_model(data[1]).children
        return self._key_model(data[1], data[2]).children

    def _filter_text(self, data) -> str:
        """The label a node is matched on by the filter (in Results: names and the hit, no ticks or counts)."""
        if data[0] == "hit" or data[0] in RESULT_GROUPS:
            return self._result_name(data)
        return self._body(data).plain

    def _model_filter(self) -> ModelFilter:
        return self.model_filter(self._model(), lambda n: n.children, lambda n: (self._filter_text(n.data),),
                                 key=lambda n: ident(n.data))

    # --- the tree --------------------------------------------------------------------------------
    def _walk_tree(self) -> Iterator[TreeNode]:
        stack = [self.query_one("#browse", Tree).root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children)

    def _can_rebuild(self) -> bool:
        return self.scan is not None

    def _rebuild(self) -> None:
        """Rebuild the tree from the scan and what has been read, keeping what is open and the cursor (the filter
        opens what holds a match while it is set)."""
        if self.scan is None or not self.is_attached:
            return
        tree = self.query_one("#browse", Tree)
        if not self.filtering:  # remember what the user opened and closed (the filter's opening is not theirs)
            for node in self._walk_tree():
                if node.data is not None and node.allow_expand:
                    self._expanded[ident(node.data)] = node.is_expanded
        cursor = tree.cursor_node
        cursor_id = ident(cursor.data) if cursor is not None and cursor.data is not None else None
        kept = self._model_filter()
        tree.clear()
        tree.root.data = ("root",)
        tree.root.set_label(self._label(tree.root.data))
        self._tree_nodes = {}
        for flavor in self._model():
            self._add(tree.root, flavor, kept)
        self.note_no_match(tree.root)
        if self.view == RESULTS and not self.hits and not self.filtering:
            tree.root.add_leaf(Text(NOTHING_FOUND, style="dim"))
        tree.root.expand()
        tree.get_node_at_line(0)  # lay the lines out now, so move_cursor finds the new nodes
        target = self._tree_nodes.get(cursor_id) if cursor_id is not None else None
        if target is not None and target.line >= 0:
            tree.move_cursor(target)
        self._update_summary()

    def _expandable(self, model: ModelNode) -> bool:
        data = model.data
        kind = data[0]
        if kind == "file":
            doc = self.docs.get(data[1].path)
            return doc is None or not doc.loaded or bool(model.children)
        if kind == "node":
            node = data[2]
            return node.is_table and node.count != 0
        return kind != "problem" and bool(model.children)

    def _add(self, parent: TreeNode, model: ModelNode, kept: ModelFilter) -> None:
        if not kept.shows(model):
            return
        data, key = model.data, ident(model.data)
        if self._expandable(model):
            node = parent.add(self._label(data), data=data, allow_expand=True)
        else:
            node = parent.add_leaf(self._label(data), data=data)
        self._tree_nodes[key] = node
        for child in model.children:
            self._add(node, child, kept)
        if key in self._loading:
            node.add_leaf(Text(READING, style="dim"))
        opens = kept.opens(model) if kept.active else self._expanded.get(key, data[0] in OPEN_KINDS)
        if node.allow_expand and opens:
            node.expand()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        if event.control.id == "browse":
            self._load(event.node)

    def _load(self, node: TreeNode) -> None:
        """Read the file, or parse the table, the first time its node opens: in a worker (a file can be tens of
        MB), with a "Reading…" line under it meanwhile."""
        data = node.data
        if data is None or data[0] not in ("file", "node"):
            return
        doc = self.document(data[1])
        if data[0] == "file":
            if doc.loaded:
                return
            work: Callable[[], object] = doc.roots
        else:
            table = data[2]
            if not table.is_table or table.children is not None:
                return
            work = lambda: doc.children(table)
        key = ident(data)
        if key in self._loading:
            return
        self._loading.add(key)
        node.add_leaf(Text(READING, style="dim"))
        generation = self._generation
        self.run_worker(lambda: self._load_worker(key, work, generation), thread=True, group="load")

    def _load_worker(self, key: Hashable, work: Callable[[], object], generation: int) -> None:
        try:
            work()  # the model never raises: what it can't read becomes an error node
        except Exception as exc:  # noqa: BLE001 - logged, the node shows what it has
            log_exception("svb.load", exc)
        self.app.call_from_thread(self._loaded, key, generation)

    def _loaded(self, key: Hashable, generation: int) -> None:
        if generation != self._generation:
            return  # rescanned since: the old documents are gone (and _loading is the new scan's)
        self._loading.discard(key)
        if not self.is_attached:
            return
        if self.filtering:  # the new labels may match: let the filter place them
            self._schedule_rebuild()
            return
        node = self._tree_nodes.get(key)
        if node is None or node.tree is None or node.data is None:
            return
        node.remove_children()
        everything = ModelFilter(TextFilter(), [], lambda n: n.children, lambda n: ())
        for child in self._children_model(node.data):
            self._add(node, child, everything)
        node.set_label(self._label(node.data))  # a file that can't be read is red now
        if not node.children:
            node.allow_expand = False
        self._update_summary()

    def action_expand_all(self) -> None:
        """x: open everything down to the files (spec D18: no file is read by it)."""
        tree = self._tree_for_keys()
        if tree is None:
            return
        cursor = tree.cursor_node
        for node in list(self._walk_tree()):
            if node.data is not None and node.data[0] in GROUP_KINDS and node.allow_expand and not node.is_expanded:
                node.expand()
        self._keep_cursor(tree, cursor)

    # --- labels ----------------------------------------------------------------------------------
    def _files_text(self, files: int) -> tuple[str, str]:
        return f"  {plural(files, 'file')}", "dim"

    def _result_name(self, data) -> str:
        """A Results node's name: the flavor, account, owner or file; a hit's `path = old`."""
        kind = data[0]
        if kind == "hit":
            hit = self.hits[data[1]]
            return f"{path_text(hit.path)} = {scalar_text(hit.old, hit.old_bytes)}"
        if kind == "r-flavor":
            return data[1].display_name
        if kind == "r-file":
            return data[1].path.name
        return data[-2]  # an account's or owner's name

    def _result_body(self, data) -> Text:
        """A Results node's label: its tick mark, its name, how many hits a group holds; a hit's staged edit with
        Browse's marks (D39), or struck through under a staged delete."""
        kind, keys = data[0], self.node_tick_keys_of(data)
        mark = self.shown_tick_mark(keys) if keys else ("", "")
        name = self._result_name(data)
        if kind == "hit":
            hit = self.hits[data[1]]
            edit = self.staging.hit_edit(hit)
            if edit is not None:
                return Text.assemble(mark, name, *self._marks(edit))
            return Text.assemble(mark, (name, "dim strike" if self.staging.hit_deleted_above(hit) else ""))
        count = (f"  {plural(len(data[-1]), 'result')}", "dim")
        if kind == "r-flavor":
            return Text.assemble(mark, (name, ACCENT), count)
        return Text.assemble(mark, (name, "" if kind == "r-file" else "bold"), count)

    def _body(self, data) -> Text:
        """A node's label (ticks only in the Results view)."""
        kind = data[0]
        error = f"bold {theme_colour(self.app, 'error')}"
        if kind == "root":
            return Text(self.scope_label)
        if kind == "hit" or kind in RESULT_GROUPS:
            return self._result_body(data)
        if kind == "flavor":
            flavor: FlavorFiles = data[1]
            return Text.assemble((flavor.flavor.display_name, ACCENT), self._files_text(len(flavor.files())))
        if kind == "problem":
            return Text(f"⚠ {data[2]}", style=error)
        if kind == "account":
            return Text.assemble((data[2].name, "bold"), self._files_text(len(data[2].files())))
        if kind == "realm":
            return Text(data[3], style="bold")
        if kind == "owner":
            owner = data[3]
            name = owner.label if owner.character is None else owner.character.name
            return Text.assemble((name, "bold"), self._files_text(len(owner.files)))
        if kind == "file":
            file: SvFile = data[1]
            doc = self.docs.get(file.path)
            if doc is not None and doc.error:
                return Text.assemble((file.path.name, error), ("  can't read", error))
            return Text.assemble(file.path.name, (f"  {human_size(file.size)}", "dim"))
        doc, node = self.docs.get(data[1].path), data[2]
        text = node_text(node, doc.data if doc is not None else None)
        if node.kind == ERROR:
            return Text(text, style=error)
        if node.kind == MORE:
            return Text(text, style="dim")
        edit = self.staging.edit_for(doc, node) if doc is not None else None
        if edit is None:
            return Text(text, style="dim strike" if doc is not None and self.staging.deleted_above(doc, node) else "")
        return Text.assemble(text, *self._marks(edit))

    def _marks(self, edit: FieldEdit) -> list[tuple[str, str]]:
        """What is staged on a key, after its label (D12): `→ new name`, `✎ new value`, `✗ deleted`."""
        if edit.delete:
            return [(f"  {DELETE_MARK}", f"bold {theme_colour(self.app, 'error')}")]
        style = f"bold {theme_colour(self.app, 'warning')}"
        marks = []
        if edit.rename:
            marks.append((f"  {RENAME_MARK} {key_text(edit.new_key)}", style))
        if edit.set_value:
            marks.append((f"  {VALUE_MARK} {scalar_text(edit.value)}", style))
        return marks

    def _label(self, data) -> Text:
        if data is None:
            return Text("")
        return self._body(data)

    def _refresh_labels(self, node: TreeNode | None = None) -> None:
        """After a tick (node's branch) or a staging change (None: every label, a staged delete strikes keys
        anywhere below it)."""
        relabel_branch(self.query_one("#browse", Tree), node, self._label)
        self._update_summary()

    # --- the highlighted node ------------------------------------------------------------------------
    def highlighted(self) -> tuple[SvDocument | None, Node | None]:
        """The document and model node of the highlighted key ((None, None) on a group, a file or nothing)."""
        if not self.is_attached:
            return None, None
        node = self.query_one("#browse", Tree).cursor_node
        data = node.data if node is not None else None
        if data is None or data[0] != "node" or data[1].path not in self.docs:
            return None, None
        return self.docs[data[1].path], data[2]

    def highlighted_hit(self) -> Hit | None:
        """The highlighted hit in the Results view (None on a group or nothing)."""
        if not self.is_attached or self.view != RESULTS or not self.hits:
            return None
        node = self.query_one("#browse", Tree).cursor_node
        data = node.data if node is not None else None
        return self.hits[data[1]] if data is not None and data[0] == "hit" else None

    def bulk_targets(self) -> list[Hit]:
        """What Edit value and Rename key act on in Results (D39): every ticked hit, else the highlighted one."""
        if self.ticked:
            return self.ticked_hits()
        hit = self.highlighted_hit()
        return [hit] if hit is not None else []

    def highlighted_key(self) -> Node | None:
        """The model node of the highlighted key (None on a group, a file or nothing)."""
        if not self.is_attached:
            return None
        node = self.query_one("#browse", Tree).cursor_node
        data = node.data if node is not None else None
        return data[2] if data is not None and data[0] == "node" else None

    def _place_name(self, data) -> str:
        """A node's name in a place (_where): the flavor, account, realm, owner or file; a key's key."""
        kind = data[0]
        if kind == "flavor":
            return data[1].flavor.display_name
        if kind == "account":
            return data[2].name
        if kind == "realm":
            return data[3]
        if kind == "owner":
            owner = data[3]
            return owner.label if owner.character is None else owner.character.name
        if kind == "file":
            return data[1].path.name
        if kind == "node" and data[2].kind not in (MORE, ERROR):
            return key_text(data[2].key)
        if kind == "hit" or kind in RESULT_GROUPS:
            return self._result_name(data)
        return self._body(data).plain

    def _where(self, node: TreeNode | None) -> str:
        """The highlighted node's place: the names from the flavor down to it, then its own label when it is a
        key (`Retail › ACCT1 › Account-wide › ElvUI.lua › ElvDB › font = "Expressway"`)."""
        if node is None or node.data is None or node.data[0] == "root":
            return self.scope_label
        names = [self._body(node.data).plain if node.data[0] == "node" else self._place_name(node.data)]
        parent = node.parent
        while parent is not None and parent.data is not None and parent.data[0] != "root":
            names.append(self._place_name(parent.data))
            parent = parent.parent
        return " › ".join(reversed(names))

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.control.id == "browse":
            self._update_summary()

    # --- summaries -------------------------------------------------------------------------------
    def _pending_words(self) -> str:
        return plural(self.staging.count, "staged edit")

    def _pending_line(self) -> Text:
        """`Staged: N edits in F files` (what Apply writes), then after a search what it found and `Ticked: M
        results` (what a bulk edit acts on, D39), how many hits the cap dropped and the files it could not read
        (D11)."""
        files = len(self.staging.files())
        line = Text.assemble(("Staged: ", "bold"), f"{plural(self.staging.count, 'edit')} in {plural(files, 'file')}")
        result = self.search_result
        if result is None:
            return line
        warning = f"bold {theme_colour(self.app, 'warning')}"
        found = f"{plural(len(result.hits), 'hit')} in {plural(result.files_with_hits, 'file')}"
        lines: list = [line, "\n", ("Results: ", "bold"), found, "\n", ("Ticked: ", "bold"),
                       plural(len(self.ticked), "result")]
        if result.dropped:
            cap = (f"{plural(result.dropped, 'more hit')} left out (the results stop at {len(result.hits):,}): "
                   "narrow the search.")
            lines += ["\n", (cap, warning)]
        if result.unreadable:
            lines += ["\n", (f"{plural(len(result.unreadable), 'file')} can't be read.", warning)]
        return Text.assemble(*lines)

    def _update_summary(self) -> None:
        if self.scan is None or not self.is_attached:
            return
        tree = self.query_one("#browse", Tree)
        files, warnings = len(self.scan.files()), len(self.scan.warnings)
        counts = f"{plural(files, 'file')} in {plural(len(self.scan.flavors), 'flavor')}"
        if warnings:
            counts += f" · {plural(warnings, 'scan warning')}"
        self.summary_text = f"Selected: {self._where(tree.cursor_node)}    {counts}"
        hidden = self.hidden_ticked_note()
        if hidden:
            self.summary_text += f"    {hidden}"
        self.query_one("#summary", Static).update(Text(self.summary_text))
        self.query_one("#pending", Static).update(self._pending_line())
        self._refresh_buttons()

    # --- ticks (the Results view; Browse has none) ----------------------------------------------------
    def tick_model(self) -> TickModel:
        return TickModel.of_ticked(self.ticked)

    def node_tick_keys_of(self, data) -> tuple[int, ...]:
        """The hits a tick on a node with this data covers (none in Browse)."""
        if data is None or not self.hits:
            return ()
        if data[0] == "hit":
            return (data[1],)
        return data[-1] if data[0] in RESULT_GROUPS else ()

    def node_tick_keys(self, node) -> tuple[int, ...]:
        return self.node_tick_keys_of(node.data) if self.view == RESULTS else ()

    def tick_log_key(self, node, keys) -> str:
        return str(ident(node.data))

    def all_tick_keys(self) -> Collection[Hashable]:
        return range(len(self.hits)) if self.view == RESULTS and self.hits else ()

    def filter_texts(self, key) -> tuple[str, ...]:
        """A hit is matched on its groups' names and its own `path = old → new`, as the Results tree is."""
        file = self.hits[key].file
        return (file.flavor.display_name, file.account, file.owner, file.path.name, self._result_name(("hit", key)))

    def no_ticks_here(self) -> bool:
        """TickActions: True (and say why) when Space / a / n on the tree have nothing to tick: Browse, or a search
        that found nothing."""
        if self.tickable:
            return False
        if self.view != RESULTS:
            self.notify(NO_TICKS_BROWSE)
        return True

    def ticked_hits(self) -> list[Hit]:
        """The ticked hits, in the order the search found them (what a bulk edit acts on, D39)."""
        return [self.hits[i] for i in sorted(self.ticked)] if self.hits else []

    # --- actions ----------------------------------------------------------------------------------
    def action_search(self) -> None:
        """S: the search popup (a new search replaces the results and their ticks; staged edits stay)."""
        if not self.idle or self.scan is None or self.wow_folder_changed():
            return
        self._open_search()

    def _open_search(self) -> None:
        scan = self.scan
        if scan is None:
            return
        accounts = [a for f in scan.flavors for a in f.accounts]
        popup = SearchScreen(flavors=[(f.flavor.folder, f.flavor.display_name) for f in scan.flavors],
                             accounts=[a.name for a in accounts],
                             characters=[o.label for a in accounts for o in a.owners if o.character is not None],
                             last=self.last_spec)
        self.app.push_screen(popup, self._search_chosen)

    def _search_chosen(self, spec: SearchSpec | None) -> None:
        """Find in the popup: search every file in scope in a worker (parallel per file, [general] parallelism),
        with the progress popup."""
        if spec is None or self.scan is None or not self.idle:
            return
        self.last_spec = spec
        files = self.scan.files()
        progress = SearchProgressScreen("Searching the SavedVariables files", first_stage="search")
        parallelism = self.cfg.parallelism

        def report(done: int, total: int, file: SvFile) -> None:
            progress.report("search", done, total, f"{file.flavor.display_name}: {file.rel}")
        self.start_run(progress, lambda: run_search(files, spec, parallelism=parallelism, progress=report),
                       self._searched, name="search", failure="The search stopped", stale_on_crash=False,
                       expected=(ValueError,), writes=False)

    def _searched(self, result: SearchResult) -> None:
        """The search ended: its hits replace the results, all ticked, in the Results view."""
        self.search_result, self.hits = result, list(result.hits)
        self.ticked.clear()
        self.ticked.update(range(len(self.hits)))
        if not self.is_attached:
            return
        self._show_view(RESULTS)
        found = plural(len(result.hits), "hit")
        self.notify(f"{found} in {plural(result.files_with_hits, 'file')} ({result.seconds:g} s)."
                    if result.hits else NOTHING_FOUND, title="Search")

    def _key_target(self, problem: Callable[[SvDocument, Node], str | None]) -> tuple[SvDocument, Node] | None:
        """The highlighted key, when the action may act on it; else None, saying why when the staging refuses it
        (inside a deleted table, ...)."""
        doc, node = self.highlighted()
        if not self.idle or doc is None or node is None:
            return None
        why = problem(doc, node)
        if why is not None:
            self.notify(why, severity="warning")
            return None
        return doc, node

    def _where_key(self, doc: SvDocument, node: Node) -> str:
        return f"{doc.file.path.name} › {path_text(node.path)}"

    def _staged(self, result, what: str) -> None:
        """After a staging call: the marks and the pending line, or the refusal."""
        if not result.ok:
            self.notify(result.message, title=f"{what} refused", severity="error")
            return
        if result.dropped:
            self.notify(f"{plural(result.dropped, 'edit')} staged inside it dropped.")
        self._refresh_labels()

    def action_edit_value(self) -> None:
        if self.view == RESULTS:
            self._bulk_edit_value()
            return
        target = self._key_target(lambda doc, node: self.staging.set_problem(doc, node, ""))
        if target is None:
            return
        doc, node = target
        old = node.value.value
        raw = doc.data[node.value.start:node.value.end]
        # the popup starts from the value staged on the key, if any (as Rename starts from a staged name); Now: is
        # the file's
        edit = self.staging.edit_for(doc, node)
        start, start_raw = (edit.value, encode_value(edit.value)) if edit is not None and edit.set_value else (old, raw)
        kind, text, note = REPLACE_STRING, "", ""
        if isinstance(start, bool):
            kind = REPLACE_BOOLEAN
        elif isinstance(start, str):
            if any(c < " " or c == "\x7f" or "\udc80" <= c <= "\udcff" for c in start):
                note = NOT_TYPABLE
            else:
                text = start
        elif start is not None:
            kind, text = REPLACE_NUMBER, start_raw.decode("ascii", "replace")
        popup = EditValueScreen(self._where_key(doc, node), scalar_text(old, raw), kind, text, start is True,
                                check=lambda value: self.staging.set_problem(doc, node, value), note=note)

        def done(value) -> None:
            if value is not None:
                self._staged(self.staging.set_value(doc, node, value), "Edit value")
        self.app.push_screen(popup, done)

    def action_rename_key(self) -> None:
        if self.view == RESULTS:
            self._bulk_rename()
            return
        target = self._key_target(lambda doc, node: self.staging.rename_problem(doc, node, node.key))
        if target is None:
            return
        doc, node = target
        edit = self.staging.edit_for(doc, node)
        current = edit.new_key if edit is not None and edit.rename else node.key

        def done(text) -> None:
            if text is not None:
                self._staged(self.staging.rename(doc, node, parse_key(text)), "Rename key")
        self.app.push_screen(RenameKeyScreen(self._where_key(doc, node), key_input(current),
                                             lambda key: self.staging.rename_problem(doc, node, key)), done)

    def action_delete_key(self) -> None:
        if self.view == RESULTS:
            return  # Delete key stays single-key, in Browse (D39)
        target = self._key_target(self.staging.delete_problem)
        if target is None:
            return
        doc, node = target
        popup = delete_confirm(self._where_key(doc, node), count=node.count, table=node.is_table,
                               positional=node.positional, staged_inside=self.staging.staged_inside(doc, node))

        def done(ok: bool | None) -> None:
            if ok:
                self._staged(self.staging.delete(doc, node), "Delete key")
        self.app.push_screen(popup, done)

    def action_unstage(self) -> None:
        """Backspace: drop what is staged on the highlighted key (or hit, in Results)."""
        if self.view == RESULTS:
            hit = self.highlighted_hit()
            edit = self.staging.hit_edit(hit) if hit is not None and self.idle else None
            if edit is None:
                return
            if not edit.rename:
                self._staged(self.staging.unstage_hit(hit), "Unstage")
                return
            # a rename needs its table (no key left twice): read in a worker, as the bulk rename reads it
            self._read_tables_then([hit], lambda tables: self._staged(
                self.staging.unstage_hit(hit, tables.get(table_key(hit))), "Unstage"), name="unstage_hit", title=READ_UNSTAGE_TABLE)
            return
        doc, node = self.highlighted()
        if not self.idle or doc is None or node is None or self.staging.edit_for(doc, node) is None:
            return
        self._staged(self.staging.unstage(doc, node), "Unstage")

    # --- bulk edits on the results (D39) ------------------------------------------------------------
    def _loaded_shas(self) -> dict[Path, str]:
        """The SHA-256 of each file opened in Browse (a hit read from other bytes is left out)."""
        return {path: doc.sha256 for path, doc in self.docs.items() if doc.sha256}

    def _bulk_where(self, hits: list[Hit]) -> str:
        if len(hits) == 1:
            return f"{hits[0].file.path.name} › {path_text(hits[0].path)}"
        files = len({h.file.path for h in hits})
        return f"{plural(len(hits), 'ticked result')} in {plural(files, 'file')}"

    def _bulk_staged(self, result: BulkResult, what: str) -> None:
        """After a bulk edit: the marks, the pending line and the notice (what was left out and why)."""
        self._refresh_labels()
        self.notify(result.text(), title=what, severity="warning" if result.left else "information",
                    timeout=15 if result.left else 5)

    def _bulk_edit_value(self) -> None:
        """Edit value on the ticked (else highlighted) hits: one popup, one staged set per hit. After a value
        Contains search it may replace only the matched text (the default)."""
        hits = self.bulk_targets()
        if not self.idle or not hits:
            return
        spec = self.search_result.spec if self.search_result is not None else None
        matched = spec is not None and spec.contains_value
        olds = {(type(h.old), h.old_bytes) for h in hits}
        first = hits[0]
        kind, text, flag = REPLACE_STRING, "", False
        if len(olds) == 1 and not matched:  # one value on every hit: start from it
            if isinstance(first.old, bool):
                kind, flag = REPLACE_BOOLEAN, first.old
            elif isinstance(first.old, str):
                text = first.old if not any(c < " " or c == "\x7f" or "\udc80" <= c <= "\udcff"
                                            for c in first.old) else ""
            elif first.old is not None:
                kind, text = REPLACE_NUMBER, first.old_bytes.decode("ascii", "replace")
        title = "Edit value" if len(hits) == 1 else f"Edit {plural(len(hits), 'value')}"
        current = scalar_text(first.old, first.old_bytes) if len(hits) == 1 else ""
        popup = EditValueScreen(self._bulk_where(hits), current, kind, text, flag, check=value_problem, title=title,
                                matched=matched)

        def done(value) -> None:
            if value is None:
                return
            mode = popup.mode
            result = stage_values(self.staging, hits, lambda hit: new_value(spec, mode, value, hit),
                                  self._loaded_shas())
            self._bulk_staged(result, title)
        self.app.push_screen(popup, done)

    def _bulk_rename(self) -> None:
        """Rename key on the ticked (else highlighted) hits: one popup, then the keys' tables are read in a worker
        (the duplicate check) and one rename per hit is staged."""
        hits = self.bulk_targets()
        if not self.idle or not hits:
            return
        keys = {key_input(h.key) for h in hits}
        initial = keys.pop() if len(keys) == 1 else ""
        title = "Rename key" if len(hits) == 1 else f"Rename {plural(len(hits), 'key')}"

        def done(text) -> None:
            if text is not None:
                shas = self._loaded_shas()
                self._read_tables_then(hits, lambda tables: self._bulk_staged(
                    stage_renames(self.staging, hits, parse_key(text), tables, shas), title), name="bulk_rename")
        self.app.push_screen(RenameKeyScreen(self._bulk_where(hits), initial, key_problem, title=title), done)

    def _read_tables_then(self, hits: list[Hit], then: Callable[[dict], None], *, name: str,
                          title: str = READ_TABLES) -> None:
        """Read the tables holding the hits' keys (bulk.read_tables) in a worker under the progress popup, then
        then(tables) on the UI thread: a large file is never read or parsed on the event loop."""
        progress = SearchProgressScreen(title, first_stage="tables")

        def report(done: int, total: int, file: str) -> None:
            progress.report("tables", done, total, file)
        self.start_run(progress, lambda: read_tables(hits, report), then, name=name,
                       failure="Reading the tables stopped", stale_on_crash=False, writes=False)

    def action_switch_view(self) -> None:
        """v: Browse and Results (once a search has run)."""
        if self.hits is None or self.app.busy:
            return
        self._show_view(RESULTS if self.view == BROWSE else BROWSE)

    def _show_view(self, view: str) -> None:
        self.view = view
        self._set_sub_title()
        self._rebuild()
        self._refresh_buttons()
        self.query_one("#browse", Tree).focus()

    # --- runs: apply, dry run, undo (RunActions) -------------------------------------------------------
    def run_backup_dir(self) -> Path | None:
        return load_settings(self.tool_cfg).backup_dir

    def _drop_pending(self) -> None:
        """Drop the staged edits and the ticks (the files changed under them, or are about to)."""
        self.staging.clear()
        self.ticked.clear()

    def _set_stale(self) -> None:
        """The files changed under this scan: drop what is pending; they are read again when the review is shown
        (after the result screen: on_screen_resume, _after_result)."""
        self._drop_pending()
        self._stale = True

    def _mark_stale(self) -> None:
        """RunActions: a run stopped half way, or put files back; read the files again now (the review is shown)."""
        self._set_stale()
        if self.idle and self.is_attached and self.app.screen is self:
            self._scan()

    def action_apply(self) -> None:
        self._start(dry_run=False)

    def action_dry_run(self) -> None:
        self._start(dry_run=True)

    def _start(self, dry_run: bool) -> None:
        """Apply / Dry run: what is staged, one plan (D39: ticks only select). A dry run writes nothing, so it needs
        no WoW check, backup folder or settled unfinished run."""
        if not self.idle or not self.pending or self.wow_folder_changed():
            return
        log_event("ui.selection", screen=self.LOG_SCREEN, control="dry_run" if dry_run else "apply", value=True)
        plan = self.staging.plans()
        if dry_run:
            self._show_apply_confirm(plan, True, [])
            return
        if self.marker is not None:  # an earlier Apply did not finish: settle that first (Apply would refuse)
            self.offer_recovery(self.marker)
            return
        if self._backup_dir_refused():
            return
        check = self.check_for(file.flavor.folder for file in plan.files)
        self._check_wow(check, lambda running: self._after_apply_preflight(plan, check, running))

    def _after_apply_preflight(self, plan: Plan, check: WowCheck, running: list[str] | None) -> None:
        alerts: list[str] = []
        if not self._refused_while_running(running, alerts):
            self._show_apply_confirm(plan, False, alerts, check)

    def _show_apply_confirm(self, plan: Plan, dry_run: bool, extra: list[str], check: WowCheck | None = None) -> None:
        """The confirm (D13): the edits per flavor, one line per file in its detail tree, and as red alert lines the
        array entries that move, the WoW check that could not run and (Apply) the disclaimer."""
        title, body, alerts = apply_confirm(plan, dry_run=dry_run)
        self.app.push_screen(ConfirmScreen(title, body, (*extra, *alerts), kind="simulate" if dry_run else "destructive",
                                           groups=apply_groups(plan)),
                             lambda ok: self._apply_confirmed(ok, plan, dry_run, check))

    def _apply_confirmed(self, ok: bool | None, plan: Plan, dry_run: bool, check: WowCheck | None) -> None:
        log_event("ui.selection", screen="confirm", control="apply_confirm", value=bool(ok), dry_run=dry_run)
        wow_root = self.cfg.wow_path
        if not ok or wow_root is None or not self.idle:
            return
        root, journal_dir = resolve_root(load_settings(self.tool_cfg), wow_root), resolve_journal_dir(wow_root)
        if root is None or journal_dir is None:
            return
        flavors = list(dict.fromkeys(file.flavor for file in plan.files))
        screen = RunProgressScreen("Simulating the changes" if dry_run else "Applying the changes", dry_run=dry_run,
                                   flavors=flavors)
        keep_snapshots, keep_journals = self.cfg.keep_backups, self.cfg.keep_journals
        self.start_run(screen, lambda: apply_plan(plan, root=root, journal_dir=journal_dir, keep_journals=keep_journals,
                                                  keep_snapshots=keep_snapshots, dry_run=dry_run, wow_check=check,
                                                  progress=screen.report_unit),
                       self._applied, name="apply",
                       failure="The run stopped unexpectedly", stale_on_crash=not dry_run, expected=(ApplyError,))

    def _applied(self, result: MultiApplyResult) -> None:
        # A run refused before it wrote a byte (a locked file, the snapshot failed, ...: "Nothing was changed")
        # keeps the staged edits and ticks, as a dry run does: its result goes back to the review.
        kept = result.dry_run or not (result.edited or result.rolled_back or result.failed)
        if not kept:
            self._set_stale()  # the files changed: read again after the result
        self._refresh_buttons()
        if result.stopped is not None:
            self.notify(f"{result.stopped.flavor.display_name}: {result.stopped.error}", title="Apply stopped",
                        severity="error", timeout=20)
        self.app.push_screen(SvResultScreen("Dry run" if result.dry_run else "Apply", summary_rows(result),
                                            FILE_COLUMNS, file_rows(result), self.scope_label, back=kept),
                             self._after_result)

    def _after_result(self, choice: str | None) -> None:
        if choice in ("flavors", "tools", "quit"):
            self.action_leave(choice)
        elif choice == "back":  # after a dry run (or a refused Apply): the staged edits and ticks kept
            return
        elif self._stale:
            self._scan()
        else:
            self.action_rescan()

    def action_undo(self) -> None:
        """z: put back the files the newest Apply changed (D15), after the WoW check and a confirm that carries the
        disclaimer and says what staged work it drops."""
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
        # the journal may be another flavor's (the newest of the whole tool): check the flavors it changed
        check = self.check_for(e["flavor"] for e in journal.entries)
        self._check_wow(check, lambda running: self._after_undo_preflight(path, journal, check, running))

    def _after_undo_preflight(self, path: Path, journal, check: WowCheck, running: list[str] | None) -> None:
        extra: list[str] = []
        if self._refused_while_running(running, extra):
            return
        if self.pending:
            extra.append(f"The {self._pending_words()} not applied yet will be dropped.")
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
        # The staged work is dropped once Undo has changed the files (_undone, or a crash: _mark_stale), as said in
        # the confirm; an Undo refused before it starts (WoW running, a locked file, the backup failed) keeps it.
        # One row per flavor whose WTF folder is backed up first (up to [general] parallelism at once), as undo_run
        # names them; the files are then put back in one more row.
        folders = sorted({e["flavor"] for e in journal.entries})
        parallelism = self.cfg.parallelism
        screen = RunProgressScreen("Undoing the last change", first_stage="undo",
                                   flavors=[Flavor(folder, wow_root / folder) for folder in folders],
                                   parallelism=parallelism)
        keep_snapshots = self.cfg.keep_backups
        self.start_run(screen, lambda: undo_run(path, wow_root=wow_root, root=root, keep_snapshots=keep_snapshots,
                                                wow_check=check, progress=screen.report, parallelism=parallelism,
                                                on_flavor=screen.start_unit, on_flavor_done=screen.finish_unit),
                       self._undone, name="undo", failure="Undo stopped unexpectedly", stale_on_crash=True,
                       expected=(UndoError,))  # WoW running, locked files, the backup failed: nothing was changed

    def _undone(self, result: UndoResult) -> None:
        self._set_stale()
        self._refresh_buttons()
        self.app.push_screen(SvResultScreen("Undo", undo_summary_rows(result), UNDO_COLUMNS,
                                            undo_detail_rows(result), self.scope_label), self._after_result)

    # --- recovery ----------------------------------------------------------------------------------
    def offer_recovery(self, marker: Marker) -> None:
        """An Apply did not finish (its marker was found by the scan): put the originals back, or leave the files."""
        log_event(SV_TOOL.event("recovery_offered"), flavor=marker.flavor, files=len(marker.files),
                  started=marker.started)
        message = recovery_text(marker)
        if self.pending:  # putting the originals back reads the files again (_recovered)
            message += (f"\n\nPutting the originals back reads the files again: the {self._pending_words()} not "
                        "applied yet will be dropped.")
        self.app.push_screen(UnfinishedRunScreen(message, marker),
                             lambda choice: self._recovery_chosen(marker, choice))

    def _recovery_chosen(self, marker: Marker, choice: str | None) -> None:
        # settled where it was found (the backup folder may have been changed with s since the scan)
        root = self.marker_root if self.marker_root is not None else \
            resolve_root(load_settings(self.tool_cfg), self.cfg.wow_path)
        if root is None or choice not in ("put_back", "leave"):
            return  # closed without a choice: offered again at the next scan or Apply
        if choice == "leave":
            leave(marker, root=root)
            self.marker = None
            return
        if self._backup_dir_refused():
            return  # the marker stays: offered again
        check = self.check_for([marker.flavor])  # the marker's flavor, which may not be one reviewed
        self._check_wow(check, lambda running: self._after_recover_preflight(marker, root, check, running))

    def _after_recover_preflight(self, marker: Marker, root: Path, check: WowCheck,
                                 running: list[str] | None) -> None:
        if self._refused_while_running(running, []):
            return  # the marker stays: offered again
        screen = RunProgressScreen("Putting the originals back", first_stage="undo")
        keep_snapshots = self.cfg.keep_backups
        journal_dir = resolve_journal_dir(self.cfg.wow_path)
        self.start_run(screen, lambda: recover(marker, root=root, journal_dir=journal_dir,
                                               keep_snapshots=keep_snapshots, wow_check=check,
                                               progress=screen.report),
                       self._recovered, name="recover", failure="Putting the originals back stopped",
                       stale_on_crash=True, expected=(UndoError,))

    def _recovered(self, result: UndoResult) -> None:
        self.marker = None
        message = (f"Put back {plural(len(result.restored), 'file')}; left {plural(len(result.skipped), 'file')} "
                   f"as they are")
        if result.failed:
            message += f"; {plural(len(result.failed), 'file')} could not be put back (see the log)"
        self.notify(message + ".", title="Unfinished change", severity="error" if result.failed else "information",
                    timeout=15)
        self._mark_stale()

    # --- leaving -------------------------------------------------------------------------------
    def action_leave(self, choice: str) -> None:
        """Leaving drops the staged edits: ask first (D12)."""
        if self.app.busy:
            return
        if not self.pending:
            self.dismiss(choice)
            return
        self.app.push_screen(ConfirmScreen("Leave and discard the staged edits?",
                                           f"{self._pending_words().capitalize()} not applied yet will be dropped; "
                                           "nothing has been written.", kind="destructive"),
                             lambda ok: self.dismiss(choice) if ok else None)


def _under(nodes: list[ModelNode]) -> tuple[int, ...]:
    """The hit indexes under these Results groups (each group's data ends with its own)."""
    return tuple(i for node in nodes for i in node.data[-1])
