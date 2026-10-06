"""The Saved Variables Browser's review (spec §5, D11, D12, D18): every SavedVariables file of the chosen flavors as a
tree, flavor › account › Account-wide / Realm › Character › Addon.lua (size) › keys, loaded lazily: the scan only
lists the files, a file is read and parsed when it is opened and a table when it is opened (in a worker, model.py).
The left pane has the USE AT YOUR OWN RISK banner, the filter, the staged/ticked summary and the run buttons; the
bar under the tree acts on the highlighted key. Dismisses with "flavors", "tools" or "quit"
(ToolFlow._after_review)."""
from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterator
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
from wowtools.core.events import log_exception
from wowtools.core.install import Flavor
from wowtools.core.process import wow_check_for
from wowtools.core.sv_apply import Marker
from wowtools.core.svfiles import SvFile
from wowtools.core.text import human_size, plural
from wowtools.tools.sv_browser.journal import latest_undoable, resolve_journal_dir
from wowtools.tools.sv_browser.model import ERROR, MORE, Node, SvDocument, key_text, node_text, scalar_text
from wowtools.tools.sv_browser.ops import FieldEdit, Staging, key_input, parse_key, path_text, typed_path
from wowtools.tools.sv_browser.popups import NOT_TYPABLE, EditValueScreen, RenameKeyScreen, delete_confirm
from wowtools.tools.sv_browser.scanner import FlavorFiles, ScanResult, scan_flavors
from wowtools.tools.sv_browser.search import REPLACE_BOOLEAN, REPLACE_NUMBER, REPLACE_STRING
from wowtools.tools.sv_browser.settings import load_settings, resolve_root
from wowtools.tools.sv_browser.undo import pending_recovery
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import (ACCENT, ALERT_STYLE, REVIEW_HINT, TREE_BINDINGS, TREE_HINT, ConfirmScreen,
                                 relabel_branch, theme_colour, two_pane_css)
from wowtools.ui.review import ActionBar, BarTree, ReviewBase, TickModel, WowCheck
from wowtools.ui.tree_filter import (FILTER_BINDINGS, FILTER_HINT, FilterInput, ModelFilter, ModelNode, TextFilter,
                                     TreeFilter)
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

TITLE = "Saved Variables Browser"
BROWSE, RESULTS = "Browse", "Results"  # the tree's two views (v); Results comes with the search (plan T3.3)
RISK_BANNER = "⚠ USE AT YOUR OWN RISK: you change addon data"
READING = "Reading…"
NAV_HINT = REVIEW_HINT + "a all · n none · " + FILTER_HINT + TREE_HINT + "f flavors · t tools"
GROUP_KINDS = ("root", "flavor", "account", "realm", "owner")  # what x opens: everything down to the files
OPEN_KINDS = ("root", "flavor", "account", "owner")  # open when first shown (realms and files start closed)
# The bar under the tree, acting on the highlighted key: (id, label, kind of action, action, key).
TREE_ACTIONS = (
    ("act-edit", "Edit value", "overwrite", "edit_value", "e"),
    ("act-rename", "Rename key", "overwrite", "rename_key", "k"),
    ("act-delete", "Delete key", "destructive", "delete_key", "d"),
    ("act-unstage", "Unstage", "cancel", "unstage", "backspace"),
    ("act-view", "View", "navigate", "switch_view", "v"),
)
LATER = "{} comes in the next build of this tool."  # an action not wired yet (plan T3.3-T3.4)
# The marks of a staged key (D12), after its label: its new name, its new value, or deleted.
RENAME_MARK, VALUE_MARK, DELETE_MARK = "→", "✎", "✗ deleted"


def ident(data) -> Hashable:
    """A node's identity across rebuilds and rescans (to keep what is open and the cursor)."""
    kind = data[0]
    if kind == "root":
        return ("root",)
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


class SvReviewScreen(TreeFilter, ReviewBase, Screen[str]):
    """The SavedVariables files of the chosen flavors. `wow_check` (tests inject one) stands for the running-WoW
    check of every flavor."""

    TREE_SELECTOR = "#browse"
    LOG_SCREEN = "svb_review"
    HIDDEN_NOUN = "result"
    PREFLIGHT_TEXT = "Checking whether WoW is running…"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {
        "btn-search": "search", "btn-apply": "apply", "btn-dry-run": "dry_run", "btn-rescan": "rescan",
        "btn-undo": "undo", **{button_id: name for button_id, _, _, name, _ in TREE_ACTIONS}}
    DEFAULT_CSS = two_pane_css("SvReviewScreen", "#browse") + """
    SvReviewScreen #risk { height: auto; margin-top: 1; }
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
        self.wow_check = wow_check if wow_check is not None else wow_check_for([f.folder for f in self.flavors])
        self.wow_root = cfg.wow_path  # the WoW folder these flavors were read from (see wow_folder_changed)
        self._leaving_for_new_folder = False
        self.settings = load_settings(tool_cfg)
        self.scan: ScanResult | None = None
        self.docs: dict[Path, SvDocument] = {}  # the files opened since the scan
        self.staging = Staging()
        self.hits: list | None = None  # the search results (plan T3.3); None: no search yet
        self.ticked: set = set()  # the ticked results
        self.view = BROWSE
        self.undoable: Path | None = None  # the newest undoable journal, found by the scan worker
        self.marker: Marker | None = None  # an Apply that did not finish, found by the scan worker
        self.summary_text = ""
        self._expanded: dict[Hashable, bool] = {}  # what the user opened and closed (kept across rebuilds)
        self._tree_nodes: dict[Hashable, TreeNode] = {}  # the tree's nodes by ident, for a load that finishes
        self._loading: set[Hashable] = set()  # nodes whose file or table is being read in a worker
        self._generation = 0  # a rescan drops what a load still running would add
        self._scanning = False
        self._checking = False

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Static(Text(RISK_BANNER, style=ALERT_STYLE), id="risk")
                yield FilterInput()
                yield Static(self._pending_line(), id="pending")
                with ButtonRow(id="search-row"):
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
        if not self.wow_folder_changed():
            self.settings = load_settings(self.tool_cfg)

    # --- state ---------------------------------------------------------------------------------
    @property
    def idle(self) -> bool:
        """Nothing is scanning, checking or running: the actions are open."""
        return not (self._scanning or self._checking or self.app.busy)

    @property
    def pending(self) -> int:
        """Staged edits plus ticked results: what an Apply would write (and leaving would drop)."""
        return self.staging.count + len(self.ticked)

    def _refresh_buttons(self) -> None:
        if not self.is_attached:
            return
        idle = self.idle
        self.query_one("#btn-search", Button).disabled = not idle or self.scan is None
        self.query_one("#btn-apply", Button).disabled = not idle or not self.pending
        self.query_one("#btn-dry-run", Button).disabled = not idle or not self.pending
        self.query_one("#btn-rescan", Button).disabled = not idle
        self.query_one("#btn-undo", Button).disabled = not idle or self.undoable is None
        doc, node = self.highlighted()
        off = not idle or node is None
        self.query_one("#act-edit", Button).disabled = off or self.staging.set_problem(doc, node, "") is not None
        self.query_one("#act-rename", Button).disabled = off or \
            self.staging.rename_problem(doc, node, node.key) is not None
        self.query_one("#act-delete", Button).disabled = off or self.staging.delete_problem(doc, node) is not None
        self.query_one("#act-unstage", Button).disabled = off or self.staging.edit_for(doc, node) is None
        self.query_one("#act-view", Button).disabled = self.hits is None

    def ticks_frozen(self) -> bool:
        return not self.idle

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
        self.app.call_from_thread(self._scanned, scan, undoable, marker)

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self.summary_text = message
        self.query_one("#summary", Static).update(Text(message))
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, scan: ScanResult, undoable: Path | None, marker: Marker | None) -> None:
        self._scanning = False
        self.scan, self.undoable, self.marker = scan, undoable, marker
        self.docs = {}
        self.staging.clear()
        self.hits = None
        self.ticked.clear()
        self._loading.clear()
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self._rebuild()
        self._refresh_buttons()
        self.query_one("#browse", Tree).focus()

    # --- the model the tree shows ------------------------------------------------------------------
    def document(self, file: SvFile) -> SvDocument:
        doc = self.docs.get(file.path)
        if doc is None:
            doc = self.docs[file.path] = SvDocument(file)
        return doc

    def _model(self) -> list[ModelNode]:
        """The tree as model nodes: the files, and what has been read of them (the filter matches only that)."""
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
        """The label a node is matched on by the filter."""
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
        self._loading.discard(key)
        if generation != self._generation or not self.is_attached:
            return  # rescanned since: the old documents are gone
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

    def _body(self, data) -> Text:
        """A node's label (the tree has no ticks in the Browse view)."""
        kind = data[0]
        error = f"bold {theme_colour(self.app, 'error')}"
        if kind == "root":
            return Text(self.scope_label)
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
        return f"{plural(self.staging.count, 'staged edit')} and {plural(len(self.ticked), 'ticked result')}"

    def _pending_line(self) -> Text:
        files = {f.path for f in self.staging.files()}
        return Text.assemble(("Staged: ", "bold"), plural(self.staging.count, "edit"), " · ", ("Ticked: ", "bold"),
                             f"{plural(len(self.ticked), 'result')} in {plural(len(files), 'file')}")

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

    # --- ticks (the Results view, plan T3.3; the Browse view has none) ---------------------------------
    def tick_model(self) -> TickModel:
        return TickModel.of_ticked(self.ticked)

    def node_tick_keys(self, node) -> tuple:
        return ()

    def tick_log_key(self, node, keys) -> str:
        return str(ident(node.data))

    def all_tick_keys(self) -> Collection[Hashable]:
        return set()

    def filter_texts(self, key) -> tuple[str, ...]:
        return ()

    # --- actions (wired in plan T3.2-T3.4) -----------------------------------------------------------
    def _later(self, what: str) -> None:
        self.notify(LATER.format(what))

    def action_search(self) -> None:
        if self.idle and self.scan is not None:
            self._later("Search")

    def action_apply(self) -> None:
        if self.idle and self.pending:
            self._later("Apply")

    def action_dry_run(self) -> None:
        if self.idle and self.pending:
            self._later("Dry run")

    def action_undo(self) -> None:
        if self.idle and self.undoable is not None:
            self._later("Undo")

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
        target = self._key_target(lambda doc, node: self.staging.set_problem(doc, node, ""))
        if target is None:
            return
        doc, node = target
        old = node.value.value
        raw = doc.data[node.value.start:node.value.end]
        kind, text, note = REPLACE_STRING, "", ""
        if isinstance(old, bool):
            kind = REPLACE_BOOLEAN
        elif isinstance(old, str):
            if any(c < " " or c == "\x7f" or "\udc80" <= c <= "\udcff" for c in old):
                note = NOT_TYPABLE
            else:
                text = old
        elif old is not None:
            kind, text = REPLACE_NUMBER, raw.decode("ascii", "replace")
        popup = EditValueScreen(self._where_key(doc, node), scalar_text(old, raw), kind, text, old is True,
                                check=lambda value: self.staging.set_problem(doc, node, value), note=note)

        def done(value) -> None:
            if value is not None:
                self._staged(self.staging.set_value(doc, node, value), "Edit value")
        self.app.push_screen(popup, done)

    def action_rename_key(self) -> None:
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
        """Backspace: drop what is staged on the highlighted key."""
        doc, node = self.highlighted()
        if not self.idle or doc is None or node is None or self.staging.edit_for(doc, node) is None:
            return
        self._staged(self.staging.unstage(doc, node), "Unstage")

    def action_switch_view(self) -> None:
        """v: Browse and Results (the Results view comes with the search, plan T3.3)."""
        if self.hits is None:
            return
        self.view = RESULTS if self.view == BROWSE else BROWSE
        self._set_sub_title()

    # --- leaving -------------------------------------------------------------------------------
    def action_leave(self, choice: str) -> None:
        """Leaving drops the staged edits and ticked results: ask first (D12)."""
        if self.app.busy:
            return
        if not self.pending:
            self.dismiss(choice)
            return
        self.app.push_screen(ConfirmScreen("Leave and discard the staged edits?",
                                           f"{self._pending_words().capitalize()} not applied yet will be dropped; "
                                           "nothing has been written.", kind="destructive"),
                             lambda ok: self.dismiss(choice) if ok else None)
