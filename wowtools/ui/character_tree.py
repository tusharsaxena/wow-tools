"""The account › realm › character tree the config tools tick in (config tools spec X2, X3), built once here so the
Config Copier, the Macro Editor and the Config Editor show it alike. populate_characters adds the nodes under any
parent (the tree's root, or a flavor's node when "All flavors" is chosen) from `Account.real_characters()`, so a
folder that can't be a character (`Bob - Copy`) never shows. Every account, realm and character node's data is a
`CharacterNode`, a NamedTuple whose `kind` is data[0] (as `relabel_branch` reads it) and whose `keys` are the tick
keys under it: a screen's `node_tick_keys(node)` is `node_keys(node)` (ticking an account or a realm ticks every
character in it), its labels `character_label(data, mark)`. It works with `ReviewTree`, `TickModel` and
`TreeFilter` like the other trees: the screen passes `shown=` to narrow a filtered rebuild and
`character_filter_texts(character)` as a key's `filter_texts`. A tool hangs its own nodes under an account
(`account_extra`, the Macro Editor's account macros) or under a character (`character_extra`, its character macros
or the Config Editor's character config); the tick keys a hook returns fold into the keys of every node above them,
so a parent's mark and Space cover them too."""
from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
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
    """The data of an account, realm or character node. `keys` are the tick keys it covers, in tree order: a
    character's own key (none when disabled) then those its `character_extra` nodes returned; a realm's, its
    characters'; an account's, its `account_extra` nodes' then its realms'. `reason` is why a character can't be
    ticked (None when it can)."""

    kind: str  # "account", "realm" or "character"
    text: str
    keys: tuple[str, ...]
    account: Account
    realm: str = ""
    character: Character | None = None
    reason: str | None = None


def node_keys(node: TreeNode | None) -> tuple[str, ...]:
    """The tick keys a tick on this node covers: its CharacterNode's keys (with the keys its extra nodes returned),
    none for any other node. A tool's own nodes answer for themselves in its `node_tick_keys`."""
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
                        account_extra: Callable[[Account, TreeNode], Iterable[str] | None] | None = None,
                        character_extra: Callable[[Character, TreeNode], Iterable[str] | None] | None = None,
                        shown: Callable[[Character], bool] | None = None,
                        mark: Mark | None = None,
                        on_error: ErrorHandler | None = None) -> list[str]:
    """Add account › realm › character nodes for `flavor` under `parent`, expanded, and return the tick keys added
    in tree order (`key(character)` of each tickable one, and every key a hook returned). `label(character)` is a
    character's text; `disabled(character)` a reason it can't be ticked (shown greyed, no tick key of its own) or
    None. `account_extra(account, node)` adds a tool's own nodes under an account before its realms (the Macro
    Editor's account macros); an account keeps its node with those alone. `character_extra(character, node)` adds
    them under a character, whose node then expands (collapsed at first; a leaf again when the hook added nothing).
    Each hook returns the tick keys of what it added (or None), folded into the keys of the nodes above them.
    `shown(character)` leaves the others out (a filtered rebuild), and a realm or account left empty with them;
    without it, an account with no characters shows a dim NO_CHARACTERS line. `mark` is as for character_label;
    `on_error` is passed to the folder listing."""
    added: list[str] = []
    for account in flavor.accounts(on_error):
        characters = [c for c in account.real_characters(on_error) if shown is None or shown(c)]
        realms: dict[str, list[tuple[Character, str | None]]] = {}
        for character in characters:
            realms.setdefault(character.realm, []).append((character, disabled(character)))
        node = parent.add(Text(account.name), data=CharacterNode("account", account.name, (), account), expand=True)
        account_keys = tuple(account_extra(account, node) or ()) if account_extra is not None else ()
        for realm, group in realms.items():
            realm_node = node.add(Text(realm), data=CharacterNode("realm", realm, (), account, realm), expand=True)
            realm_keys: tuple[str, ...] = ()
            for character, reason in group:
                realm_keys += _add_character(realm_node, character, reason, key=key, label=label,
                                             character_extra=character_extra, mark=mark)
            realm_node.data = realm_node.data._replace(keys=realm_keys)
            realm_node.set_label(character_label(realm_node.data, mark))
            account_keys += realm_keys
        node.data = node.data._replace(keys=account_keys)
        added += account_keys
        if not node.children:
            if shown is not None:
                node.remove()
                continue
            node.add_leaf(Text(NO_CHARACTERS, style="dim"))
        node.set_label(character_label(node.data, mark))
    return added


def _add_character(realm_node: TreeNode, character: Character, reason: str | None, *,
                   key: Callable[[Character], str], label: Callable[[Character], str],
                   character_extra: Callable[[Character, TreeNode], Iterable[str] | None] | None,
                   mark: Mark | None) -> tuple[str, ...]:
    """One character's node under its realm (with the tool's own nodes under it); returns the keys it covers."""
    own = () if reason is not None else (key(character),)
    data = CharacterNode("character", label(character), own, realm_node.data.account, character.realm, character,
                         reason)
    if character_extra is None:
        realm_node.add_leaf(character_label(data, mark), data=data)
        return own
    node = realm_node.add(Text(data.text), data=data, allow_expand=True)
    keys = own + tuple(character_extra(character, node) or ())
    node.data = data._replace(keys=keys)
    node.allow_expand = bool(node.children)
    node.set_label(character_label(node.data, mark))
    return keys
