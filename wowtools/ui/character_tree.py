"""The account › realm › character tree the config tools tick in (config tools spec X2, X3), built once here so the
Config Copier, the Macro Editor and the Config Editor show it alike. populate_characters adds the nodes under any
parent (the tree's root, or a flavor's node when "All flavors" is chosen) from `Account.real_characters()`, so a
folder that can't be a character (`Bob - Copy`) never shows. Every account, realm and character node's data is a
`CharacterNode`, a NamedTuple whose `kind` is data[0] (as `relabel_branch` reads it) and whose `keys` are the tick
keys under it: a screen's `node_tick_keys(node)` is `node_keys(node)` (ticking an account or a realm ticks every
character in it), its labels `character_label(data, mark)`. It works with `ReviewTree`, `TickModel` and
`TreeFilter` like the other trees: the screen passes `shown=` to narrow a filtered rebuild and
`character_filter_texts(character)` as a key's `filter_texts`."""
from __future__ import annotations

from collections.abc import Callable, Collection
from typing import NamedTuple

from rich.text import Text
from textual.widgets.tree import TreeNode

from wowtools.core.install import Account, Character, ErrorHandler, Flavor

__all__ = ["NO_CHARACTERS", "CharacterNode", "character_filter_texts", "character_label", "node_keys",
           "populate_characters"]

NO_CHARACTERS = "no characters"
NO_MARK = "  "  # a line nothing can tick: the mark's width, so names line up
Mark = Callable[[Collection[str]], "tuple[str, str]"]


class CharacterNode(NamedTuple):
    """The data of an account, realm or character node. `keys` are the tick keys it covers (an account's or a
    realm's: every tickable character in it, in tree order; a disabled character's: none). `reason` is why a
    character can't be ticked (None when it can)."""

    kind: str  # "account", "realm" or "character"
    text: str
    keys: tuple[str, ...]
    account: Account
    realm: str = ""
    character: Character | None = None
    reason: str | None = None


def node_keys(node: TreeNode | None) -> tuple[str, ...]:
    """The tick keys a tick on this node covers: its CharacterNode's keys, none for any other node. A screen that
    puts its own tickable nodes under an account (`account_extra`) adds their keys itself."""
    data = None if node is None else node.data
    return data.keys if isinstance(data, CharacterNode) else ()


def character_filter_texts(character: Character) -> tuple[str, str, str]:
    """What a character's tick key is matched on by a TreeFilter: its account, its realm, its name."""
    return character.account, character.realm, character.name


def character_label(data: CharacterNode, mark: Mark | None = None) -> Text:
    """A node's label: the tick mark over its keys (`mark(keys)`, e.g. the screen's `shown_tick_mark`) then its text,
    bold for an account or a realm. A line with nothing to tick keeps the mark's room blank; a disabled character is
    dim, with its reason after it. No mark at all when `mark` is None."""
    parts: list[tuple[str, str]] = []
    if mark is not None:
        parts.append(mark(data.keys) if data.keys else (NO_MARK, ""))
    if data.reason is not None:
        parts += [(data.text, "dim"), (f"  {data.reason}", "dim italic")]
    else:
        parts.append((data.text, "" if data.kind == "character" else "bold"))
    return Text.assemble(*parts)


def populate_characters(parent: TreeNode, flavor: Flavor, *, key: Callable[[Character], str],
                        label: Callable[[Character], str],
                        disabled: Callable[[Character], str | None] = lambda c: None,
                        account_extra: Callable[[Account, TreeNode], None] | None = None,
                        shown: Callable[[Character], bool] | None = None,
                        mark: Mark | None = None,
                        on_error: ErrorHandler | None = None) -> list[str]:
    """Add account › realm › character nodes for `flavor` under `parent`, expanded, and return the tick keys added
    (`key(character)` of each tickable one, in tree order). `label(character)` is a character's text;
    `disabled(character)` a reason it can't be ticked (shown greyed, no tick key) or None. `account_extra(account,
    node)` adds a tool's own nodes under an account before its realms (the Macro Editor's account macros); an account
    keeps its node with those alone. `shown(character)` leaves the others out (a filtered rebuild), and a realm or
    account left empty with them; without it, an account with no characters shows a dim NO_CHARACTERS line. `mark`
    is as for character_label; `on_error` is passed to the folder listing."""
    added: list[str] = []
    for account in flavor.accounts(on_error):
        characters = [c for c in account.real_characters(on_error) if shown is None or shown(c)]
        realms: dict[str, list[tuple[Character, str | None]]] = {}
        for character in characters:
            realms.setdefault(character.realm, []).append((character, disabled(character)))
        account_keys = tuple(key(c) for group in realms.values() for c, reason in group if reason is None)
        node = parent.add(Text(account.name), data=CharacterNode("account", account.name, account_keys, account),
                          expand=True)
        if account_extra is not None:
            account_extra(account, node)
        for realm, group in realms.items():
            realm_keys = tuple(key(c) for c, reason in group if reason is None)
            realm_node = node.add(Text(realm), data=CharacterNode("realm", realm, realm_keys, account, realm),
                                  expand=True)
            for character, reason in group:
                keys = () if reason is not None else (key(character),)
                data = CharacterNode("character", label(character), keys, account, realm, character, reason)
                realm_node.add_leaf(character_label(data, mark), data=data)
            realm_node.set_label(character_label(realm_node.data, mark))
        added += account_keys
        if not node.children:
            if shown is not None:
                node.remove()
                continue
            node.add_leaf(Text(NO_CHARACTERS, style="dim"))
        node.set_label(character_label(node.data, mark))
    return added
