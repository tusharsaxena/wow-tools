"""Build the review screen's tree (By addon or By character) from a scan and the pending changes, with the Show
boxes and the tree filter (ui.tree_filter's TextFilter) applied. Every node is built up front (a whole install has well under a thousand), and the builder
records, per node, the tick keys it covers and the text of its label (the screen adds the tick mark)."""
from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass

from rich.text import Text
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from wowtools.tools.ace3_profile_manager.ops import DbKey, DbState, Staging
from wowtools.tools.ace3_profile_manager.report import char_tags, profile_rows
from wowtools.tools.ace3_profile_manager.scanner import AccountScan, AddonFile, FlavorScan, ScanResult, SvFile
from wowtools.ui.dialogs import ACCENT
from wowtools.ui.tree_filter import TextFilter

READ_ONLY = ("deleted", "removed", "note", "warnings")
LEFTOVER_TAG = "no character folder"
EXPANDED = ("root", "flavor", "account", "db")  # open when first shown; addons, profiles, characters start closed


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
    read-only or locked node) and its label without the tick mark. `locked` and `blacklisted` take the file's
    flavor folder and its addon."""

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
        self.bodies: dict[int, Text] = {}
        self._own: set[int] = set()  # nodes whose keys are their own (a profile), not the union of their children
        # The filter opens every group it leaves, so its matches show; what the user opens and closes then is not
        # remembered (the tree goes back to how it was when the filter is cleared).
        self.searching = self.text_filter.active
        self._path: tuple[str, ...] = ()  # the labels above the node being built (flavor, account): the filter's

    # --- nodes -----------------------------------------------------------------------------------
    def _add(self, parent: TreeNode, data, body: Text, keys: tuple | None = None, *, leaf: bool = False) -> TreeNode:
        self.bodies[id(data)] = body
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
        self.bodies[id(root.data)] = Text(self.scope_label, style=ACCENT)
        multi = len(self.scan.flavors) > 1
        for flavor_scan in self.scan.flavors:
            self._flavor(root, flavor_scan, multi)
        warnings = self.scan.warnings
        title = f"⚠ Scan warnings ({len(warnings)})"
        # The filter keeps the group when its title matches (all of it) or the warnings that match, as any group
        shown = warnings if self.text_filter.matches(title) else \
            [w for w in warnings if self.text_filter.matches(w.message)]
        if shown:
            node = self._add(root, ("warnings", warnings), Text(title, style=f"bold {self.warning_style}"))
            for warning in shown:
                self._add(node, ("note", warning.message), Text(warning.message, style="dim"), leaf=True)
        root.expand()
        self._gather(root)

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
        parent = self._add(root, data, Text(name, style=ACCENT)) if multi else root
        for account in flavor_scan.accounts:
            self._path = (name, account.account) if multi else (account.account,)
            self._account(parent, account)
        if multi:
            self._drop_if_empty(parent)

    def _account(self, parent: TreeNode, account: AccountScan) -> None:
        body = Text(account.account, style=ACCENT)
        if not account.files:
            body.append("  no Ace3 data", style="dim")
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
        body = Text(addon, style="dim" if locked else "bold")
        if file.character is not None:
            body.append(f" ({file.character.label})", style="dim")
        if locked:
            body.append(" · blacklisted", style=self.warning_style)
        elif self.blacklisted(file.flavor.folder, addon):
            body.append(" · unlocked", style=self.warning_style)
        node = self._add(parent, ("addon", addon_file), body)
        several = len(addon_file.dbs) > 1
        for state in self._states(addon_file):
            if several:
                db_node = self._add(node, ("db", state.key), Text(state.key.sv_name, style="dim" if locked else ""))
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
            if row.deleted:
                node = self._add(parent, ("deleted", key, row.name), Text(row.label, style="dim"))
            else:
                node = self._add(parent, ("profile", key, row.name), Text(row.label, style=style),
                                 () if locked else (("p", key, row.name),))
            for char in chars:
                if char.removed:
                    self._add(node, ("removed", key, char.char), Text(char.label, style="dim"), leaf=True)
                else:
                    self._add(node, ("char", key, char.char), Text(char.label, style=style),
                              () if locked else (("c", key, char.char),), leaf=True)
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
            body = Text(char, style="bold")
            if leftover:
                body.append(f" · {LEFTOVER_TAG}", style="dim")
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
        body = Text(" · ".join([f"{name}: {shown}", *tags]), style="dim" if locked or removed else "")
        if removed:
            self._add(parent, ("removed", key, char), body, leaf=True)
        else:
            self._add(parent, ("pair", key, char), body, () if locked else (("c", key, char),), leaf=True)


def counts(ticked: set[tuple]) -> tuple[int, int]:
    """(profiles, characters) ticked."""
    profiles = sum(1 for k in ticked if k[0] == "p")
    return profiles, len(ticked) - profiles

