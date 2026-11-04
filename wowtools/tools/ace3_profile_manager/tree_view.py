"""Build the review screen's tree (By addon or By character) from a scan and the pending changes, with the Show
boxes and the tree filter (ui.tree_filter's TextFilter) applied. Every node is built up front (a whole install has
well under a thousand), and the builder records, per node, the tick keys it covers, its label without the tick mark
(a `Row` of cells, or a fixed `Text`), whether it is a row of a locked (blacklisted) addon (the screen shows the
blacklist mark there instead), its leaf count (feedback round 2 R2, STD-7.27) and its siblings' natural column
widths (R4, STD-7.28); the screen fits the columns to the pane and draws them."""
from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass

from rich.text import Text
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from wowtools.core.svfiles import SvFile
from wowtools.tools.ace3_profile_manager.ops import DbKey, DbState, Staging
from wowtools.tools.ace3_profile_manager.report import char_tags, pair_cells, profile_rows
from wowtools.tools.ace3_profile_manager.scanner import AccountScan, AddonFile, FlavorScan, ScanResult
from wowtools.ui.columns import ColumnLayout, natural_widths
from wowtools.ui.counts import COUNT_STYLE, count_text
from wowtools.ui.dialogs import ACCENT
from wowtools.ui.tree_filter import TextFilter

READ_ONLY = ("deleted", "removed", "note", "warnings")
LEFTOVER_TAG = "no character folder"
EXPANDED = ("root", "flavor", "account", "db")  # open when first shown; addons, profiles, characters start closed
WARNINGS_TITLE = "⚠ Scan warnings"
# The leaf each view counts (R2, STD-7.27): By addon a profile row (a pending delete too: it is a row of its addon
# until Apply), By character a character's addon row (a removed one too). A profile row is a leaf itself: its
# characters are its characters column, not a count.
LEAF_KINDS = {"addon": ("profile", "deleted"), "character": ("pair", "removed")}
GROUP = "group"  # a node of a name and its count (root, flavor, account, database, Scan warnings): not columns
# The column rows (R4, STD-7.28) and how each fits a narrow pane. An addon: name · count · its character (a
# per-character file) · blacklisted / unlocked. A profile: name · characters · tags. A character under a profile:
# name · tags. By character, a character: name · count · no character folder; its addon row: addon · profile ·
# tags. The tags and the character give way first, then the name (cut in its middle); a count or a status is never
# cut, only dropped, and a row with a count keeps it (ui.columns.fit_keeping_count).
LAYOUTS = {
    "addon": ColumnLayout(caps=(32, None, 28, None), minimums=(6, 0, 8, 0), shrink=((2,),), drop=(2, 3)),
    "profile": ColumnLayout(caps=(32, None, 40), minimums=(6, 0, 8), shrink=((2,), (0,)), drop=(2, 1)),
    "char": ColumnLayout(caps=(32, 40), minimums=(8, 8), shrink=((1,), (0,)), drop=(1,)),
    "character": ColumnLayout(caps=(32, None, None), minimums=(6, 0, 0), shrink=(), drop=(2,)),
    "pair": ColumnLayout(caps=(32, 24, 40), minimums=(8, 6, 8), shrink=((2,), (1, 0)), drop=(2, 1)),
}
COUNTED = ("addon", "character")  # column rows whose column 1 is their count


@dataclass
class Row:
    """A node's label without its tick mark: its cells, each cell's style and how they lay out (GROUP, or a key of
    LAYOUTS). A GROUP row's count, and the count column of an addon or a character, are filled in once the tree
    is built."""
    cells: list[str]
    styles: tuple[str, ...]
    layout: str = GROUP


@dataclass
class Filters:
    view: str = "addon"  # "addon" or "character"
    only_multi: bool = False
    only_unused: bool = False
    leftovers: bool = True
    blacklisted: bool = True

    @property
    def narrowing(self) -> bool:
        """A Show box hides items: an empty group is then left out rather than shown empty."""
        return self.only_multi or self.only_unused or not self.leftovers or not self.blacklisted


def ident(data) -> Hashable:
    """A node's identity across rebuilds (to keep expansion and the cursor)."""
    kind = data[0]
    if kind == "flavor":
        return kind, data[1].flavor.folder
    if kind == "account":
        return kind, data[1].flavor.folder, data[1].account
    if kind == "addon":
        return kind, data[1].file.path
    if kind == "warnings":
        return (kind,)
    return data


class TreeBuilder:
    """Fills a Tree. `keys` and `bodies` are keyed by id(node.data): the tick keys a node covers (empty for a
    read-only or locked node) and its label without the tick mark; `held` the nodes of a locked addon's rows (the
    blacklist mark, L15). `locked` and `blacklisted` take the file's flavor folder and its addon."""

    def __init__(self, scan: ScanResult, staging: Staging, filters: Filters, *, scope_label: str,
                 locked: Callable[[str, str], bool], blacklisted: Callable[[str, str], bool],
                 expanded: dict[Hashable, bool], warning_style: str, text_filter: TextFilter | None = None) -> None:
        self.scan = scan
        self.staging = staging
        self.filters = filters
        self.text_filter = text_filter or TextFilter()
        self.scope_label = scope_label
        self.locked = locked
        self.blacklisted = blacklisted
        self.expanded = expanded
        self.warning_style = warning_style
        self.keys: dict[int, tuple] = {}
        self.bodies: dict[int, Text] = {}  # a fixed label (a warning line, a note, a flavor that could not be read)
        self.rows: dict[int, Row] = {}  # a label of cells (the rest)
        self.widths: dict[int, tuple[int, ...]] = {}  # a column row's siblings' natural widths
        self.depths: dict[int, int] = {}  # the root is 0
        self.toggle: set[int] = set()  # rows behind a ▶ / ▼: their own, or a sibling's (`padded` then)
        self.padded: set[int] = set()  # rows that don't open beside siblings that do: two spaces in its place
        self.held: set[int] = set()
        self._own: set[int] = set()  # nodes whose keys are their own (a profile), not the union of their children
        # The filter opens every group it leaves, so its matches show; what the user opens and closes then is not
        # remembered (the tree goes back to how it was when the filter is cleared).
        self.searching = self.text_filter.active
        self._path: tuple[str, ...] = ()  # the labels above the node being built (flavor, account): the filter's

    # --- nodes -----------------------------------------------------------------------------------
    def _add(self, parent: TreeNode, data, body: Text | Row, keys: tuple | None = None, *, leaf: bool = False,
             held: bool = False) -> TreeNode:
        if isinstance(body, Row):
            self.rows[id(data)] = body
        else:
            self.bodies[id(data)] = body
        self.depths[id(data)] = self.depths.get(id(parent.data), 0) + 1
        if held:
            self.held.add(id(data))
        if keys is not None:
            self.keys[id(data)] = keys
            self._own.add(id(data))
        if leaf:
            return parent.add_leaf(Text(""), data=data)
        if self.searching and data[0] != "warnings":
            expand = True
        else:
            expand = self.expanded.get(ident(data), data[0] in EXPANDED)
        return parent.add(Text(""), data=data, expand=expand)

    def _drop_if_empty(self, node: TreeNode) -> None:
        if not node.children and (self.filters.narrowing or self.searching):
            node.remove()

    def build(self, tree: Tree) -> None:
        tree.clear()
        root = tree.root
        root.data = ("root",)
        self.rows[id(root.data)] = Row([self.scope_label], (ACCENT,))
        self.depths[id(root.data)] = 0
        multi = len(self.scan.flavors) > 1
        for flavor_scan in self.scan.flavors:
            self._flavor(root, flavor_scan, multi)
        warnings = self.scan.warnings
        # The filter keeps the group when its title matches (all of it) or the warnings that match, as any group
        shown = warnings if self.text_filter.matches(WARNINGS_TITLE) else \
            [w for w in warnings if self.text_filter.matches(w.message)]
        if shown:
            node = self._add(root, ("warnings", warnings), Row([WARNINGS_TITLE], (f"bold {self.warning_style}",)))
            for warning in shown:
                self._add(node, ("note", warning.message), Text(warning.message, style="dim"), leaf=True)
        root.expand()
        self._gather(root)
        self._count(root)
        self._align(root)

    def _count(self, node: TreeNode) -> int:
        """Post-order: the leaves below `node` as the tree shows them (R2), put in its label. A Scan warnings group
        counts its own lines and is left out of its parent's count."""
        kind = node.data[0]
        if kind in LEAF_KINDS[self.filters.view]:
            return 1
        below = [(child, self._count(child)) for child in node.children]
        if kind == "warnings":
            n = len(node.children)
        else:
            n = sum(count for child, count in below if child.data[0] != "warnings")
        row = self.rows.get(id(node.data))
        if row is not None and (row.layout == GROUP or row.layout in COUNTED):
            if row.layout == GROUP:
                row.cells.append(count_text(n))
                row.styles = (*row.styles, COUNT_STYLE)
            else:
                row.cells[1] = count_text(n)
        return n

    def _align(self, node: TreeNode) -> None:
        """Each group of sibling column rows of one layout: their natural widths (R4), and whether a ▶ / ▼ is in
        front of them (a row that doesn't open is padded to line up with one that does)."""
        groups: dict[str, list[TreeNode]] = {}
        for child in node.children:
            row = self.rows.get(id(child.data))
            if row is not None and row.layout != GROUP:
                groups.setdefault(row.layout, []).append(child)
            elif child.allow_expand:
                self.toggle.add(id(child.data))
            self._align(child)
        for siblings in groups.values():
            natural = natural_widths(self.rows[id(s.data)].cells for s in siblings)
            opens = any(s.allow_expand for s in siblings)
            for sibling in siblings:
                key = id(sibling.data)
                self.widths[key] = natural
                if opens:
                    self.toggle.add(key)
                    if not sibling.allow_expand:
                        self.padded.add(key)
        if node.parent is None:
            self.toggle.add(id(node.data))  # the root's ▼

    def _gather(self, node: TreeNode) -> tuple:
        """Post-order: a group covers every key below it. Returns the node's keys and every key below it (a
        profile ticks only itself, but the addon above it covers its characters too)."""
        below = tuple(k for child in node.children for k in self._gather(child))
        key = id(node.data)
        if key in self._own:
            return self.keys[key] + below
        self.keys[key] = () if node.data[0] in READ_ONLY else below
        return self.keys[key]

    def _flavor(self, root: TreeNode, flavor_scan: FlavorScan, multi: bool) -> None:
        name = flavor_scan.flavor.display_name
        data = ("flavor", flavor_scan)
        if flavor_scan.error:
            if not self.text_filter.matches(name, flavor_scan.error):
                return  # filtered on its name and its error, like any other row
            self._add(root, data, Text.assemble((name, ACCENT), (f"  {flavor_scan.error}", self.warning_style)),
                      (), leaf=True)
            return
        parent = self._add(root, data, Row([name], (ACCENT,))) if multi else root
        for account in flavor_scan.accounts:
            self._path = (name, account.account) if multi else (account.account,)
            self._account(parent, account)
        if multi:
            self._drop_if_empty(parent)

    def _account(self, parent: TreeNode, account: AccountScan) -> None:
        body = Row([account.account], (ACCENT,)) if account.files else \
            Text.assemble((account.account, ACCENT), ("  no Ace3 data", "dim"))
        node = self._add(parent, ("account", account), body)
        if self.filters.view == "character":
            self._characters(node, account)
        else:
            for addon_file in sorted(account.files, key=lambda f: (f.file.character is not None,
                                                                   f.file.addon.casefold(), f.file.owner.casefold())):
                self._addon(node, addon_file)
        self._drop_if_empty(node)

    def _states(self, addon_file: AddonFile) -> list[DbState]:
        states = [self.staging.state(DbKey(addon_file.file.path, db.sv_name)) for db in addon_file.dbs]
        if self.filters.only_multi:
            states = [s for s in states if len(s.names()) >= 2]
        return states

    def _shown(self, file: SvFile) -> bool:
        return self.filters.blacklisted or not self.blacklisted(file.flavor.folder, file.addon)

    # --- By addon ------------------------------------------------------------------------------
    def _addon(self, parent: TreeNode, addon_file: AddonFile) -> None:
        file = addon_file.file
        addon = file.addon
        if not self._shown(file):
            return
        locked = self.locked(file.flavor.folder, addon)
        status = "blacklisted" if locked else "unlocked" if self.blacklisted(file.flavor.folder, addon) else ""
        owner = file.character.label if file.character is not None else ""
        body = Row([addon, "", owner, status], ("dim" if locked else "bold", COUNT_STYLE, "dim", self.warning_style),
                   "addon")
        node = self._add(parent, ("addon", addon_file), body, held=locked)
        several = len(addon_file.dbs) > 1
        for state in self._states(addon_file):
            if several:
                db_node = self._add(node, ("db", state.key), Row([state.key.sv_name], ("dim" if locked else "",)),
                                    held=locked)
                self._profiles(db_node, state, locked)
                self._drop_if_empty(db_node)
            else:
                self._profiles(node, state, locked)
        self._drop_if_empty(node)

    def _profiles(self, parent: TreeNode, state: DbState, locked: bool) -> None:
        key, addon = state.key, state.file.addon
        style = "dim" if locked else ""
        for row in profile_rows(state):
            if self.filters.only_unused and (row.deleted or "unused" not in row.tags):
                continue
            context = (*self._path, addon, key.sv_name, row.name)
            chars = [c for c in row.chars if (self.filters.leftovers or c.char not in state.leftovers)
                     and self.text_filter.matches(*context, c.char)]
            if not chars and not self.text_filter.matches(*context):
                continue
            cells = list(row.shown_cells(chars))  # the count of the characters shown below it (R2)
            if row.deleted:
                node = self._add(parent, ("deleted", key, row.name), Row(cells, ("dim",) * 3, "profile"),
                                 held=locked)
            else:
                node = self._add(parent, ("profile", key, row.name), Row(cells, (style, "dim", "dim"), "profile"),
                                 () if locked else (("p", key, row.name),), held=locked)
            for char in chars:
                if char.removed:
                    self._add(node, ("removed", key, char.char), Row(list(char.cells), ("dim", "dim"), "char"),
                              leaf=True, held=locked)
                else:
                    self._add(node, ("char", key, char.char), Row(list(char.cells), (style, "dim"), "char"),
                              () if locked else (("c", key, char.char),), leaf=True, held=locked)
            if not node.children:
                node.allow_expand = False

    # --- By character -------------------------------------------------------------------------
    def _characters(self, parent: TreeNode, account: AccountScan) -> None:
        pairs: dict[str, list[tuple[AddonFile, DbState]]] = {}
        for addon_file in account.files:
            if not self._shown(addon_file.file):
                continue
            for state in self._states(addon_file):
                for char in state.keys:
                    pairs.setdefault(char, []).append((addon_file, state))
        label = f"{account.flavor.folder}/{account.account}"
        for char in sorted(pairs, key=str.casefold):
            leftover = account.is_leftover(char)
            if leftover and not self.filters.leftovers:
                continue
            body = Row([char, "", LEFTOVER_TAG if leftover else ""], ("bold", COUNT_STYLE, "dim"), "character")
            node = self._add(parent, ("character", label, char), body)
            for addon_file, state in sorted(pairs[char], key=lambda p: (p[0].file.addon.casefold(),
                                                                         p[1].key.sv_name.casefold())):
                self._pair(node, addon_file, state, char)
            self._drop_if_empty(node)

    def _pair(self, parent: TreeNode, addon_file: AddonFile, state: DbState, char: str) -> None:
        addon, key = addon_file.file.addon, state.key
        profile = state.keys.get(char)
        removed = profile is None
        shown = profile if profile is not None else state.db.profile_keys.get(char, "")
        if not self.text_filter.matches(*self._path, char, addon, key.sv_name, shown):
            return
        name = f"{addon} ({key.sv_name})" if len(addon_file.dbs) > 1 else addon
        locked = self.locked(addon_file.file.flavor.folder, addon)
        tags = [t for t in char_tags(state, char) if t != LEFTOVER_TAG]
        style = "dim" if locked or removed else ""
        body = Row(list(pair_cells(name, shown, tags)), (style, style, "dim"), "pair")
        if removed:
            self._add(parent, ("removed", key, char), body, leaf=True, held=locked)
        else:
            self._add(parent, ("pair", key, char), body, () if locked else (("c", key, char),), leaf=True,
                      held=locked)


def counts(ticked: set[tuple]) -> tuple[int, int]:
    """(profiles, characters) ticked."""
    profiles = sum(1 for k in ticked if k[0] == "p")
    return profiles, len(ticked) - profiles

