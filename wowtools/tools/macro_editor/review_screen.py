"""The Macro Editor's browse screen (config tools spec ME2-ME7, ME13, ME14; X1-X5): every macro set of the chosen
flavors (a scan in a worker, scanner.scan_sets) as the shared character tree, (flavor ›) account › "Account macros"
and realm › character, each set with its slot use (`12/30`, `30/30 FULL`) and its macros under it, one line each:
`name · first line · n/255`. A set in a layout the reader does not know (ME14) is read-only: greyed, never ticked or
written, and listed in the warnings view (`!`).

Ticks: a macro's tick picks it for Copy, Delete and Replace text…; a set's tick (Space on a character or on Account
macros ticks the set and its macros, X2) makes it a target of Paste…. The left pane has the search (the shared
filter box, matched on the macros' names and/or bodies, showing only the matching macros or all of them with the
matches marked), the staged line and Apply / Dry run / Rescan / Undo last change; the bar under the tree acts on the
highlighted or ticked macros (edit_actions.py). Staged changes are marked before their line (✎ changed, + new, ✗
deleted) and nothing is written until Apply, which runs every staged change across files and flavors as one
run of the shared client-file pipeline (RunActions: WoW check, confirm, progress popup, result screen); one Undo puts
it all back. Leaving with staged changes asks first. Dismisses with "flavors", "tools" or "quit"."""
from __future__ import annotations

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
from wowtools.core.install import Account, Character, Flavor, flavor_name
from wowtools.core.macrofile import Macro
from wowtools.core.process import wow_check_for
from wowtools.core.sv_apply import Marker, MultiApplyResult
from wowtools.core.text import plural
from wowtools.tools.macro_editor.edit_actions import TREE_ACTIONS, MacroEditActions
from wowtools.tools.macro_editor.events import SV_TOOL
from wowtools.tools.macro_editor.journal import latest_undoable, read_journal, resolve_journal_dir
from wowtools.tools.macro_editor.model import MACRO_FILE, MacroSet
from wowtools.tools.macro_editor.ops import Staged, build_changes, effective_macros
from wowtools.tools.macro_editor.report import (ACCOUNT_MACROS, FILE_COLUMNS, STAGE_TITLES, STATUS_COLOURS,
                                                UNDO_COLUMNS, apply_confirm, apply_groups, file_rows, macro_text,
                                                recovery_text, slots_text, summary_rows, undo_confirm,
                                                undo_detail_rows, undo_summary_rows)
from wowtools.tools.macro_editor.runner import ApplyError, run_apply
from wowtools.tools.macro_editor.scanner import scan_sets
from wowtools.tools.macro_editor.settings import load_settings, resolve_root
from wowtools.tools.macro_editor.undo import (UndoError, UndoResult, leave, pending_recovery, recover, undo_flavors,
                                              undo_run)
from wowtools.ui.branding import BottomBar
from wowtools.ui.character_tree import CharacterNode, character_label, node_keys, populate_characters
from wowtools.ui.dialogs import (ACCENT, REVIEW_HINT, TREE_BINDINGS, TREE_HINT, ConfirmScreen, ProgressScreen,
                                 UnfinishedRunScreen, relabel_branch, theme_colour, two_pane_css)
from wowtools.ui.result_screen import ResultScreen
from wowtools.ui.review import ActionBar, BarTree, ReviewBase, RunActions, SvRecoveryActions, TickModel, WowCheck
from wowtools.ui.tree_filter import FILTER_BINDINGS, FILTER_HINT, FilterBar, TreeFilter
from wowtools.ui.warnings_view import WARNINGS_BINDING, SummaryBar, SummaryLine, WarningItem, WarningsHost, where_text
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, RiskBanner, action_button

TITLE = "Macro Editor"
NAV_HINT = REVIEW_HINT + "a all · n none · " + FILTER_HINT + TREE_HINT + "f flavors · t tools"
READ_ONLY = "read-only"
NO_MARK = "  "
# The marks of a staged macro (the Saved Variables Browser's symbols, D12), before its line.
CHANGED_MARK, NEW_MARK, DELETED_MARK = "✎", "+", "✗"
MATCH_STYLE = "bold underline"  # a macro the search matches, while every macro is shown


class SetKey(NamedTuple):
    """The tick key of a set: a Paste… target."""
    path: Path


class MacroKey(NamedTuple):
    """The tick key of a macro: its set's file and its id."""
    path: Path
    id: str


class SetNode(NamedTuple):
    """The data of an account's "Account macros" line: its set and the tick keys under it."""
    kind: str
    mset: MacroSet
    keys: tuple[Hashable, ...]


class MacroNode(NamedTuple):
    """The data of a macro's line: `key` None when it can't be ticked (deleted, or in a read-only set); `state` is
    "", "changed", "new" or "deleted"."""
    kind: str
    mset: MacroSet
    macro: Macro
    key: MacroKey | None
    state: str


def macro_rows(staged: Staged, mset: MacroSet) -> list[tuple[Macro, str]]:
    """The set's macros as the tree lists them: the file's in its order (a staged edit shown with its new text,
    "changed"; a staged delete kept, "deleted"), then the staged new ones ("new")."""
    changes = {c.id.upper(): c for c in staged.changes.get(mset.path, ())}
    shown = {m.id.upper(): m for m in effective_macros(staged, mset)}
    rows: list[tuple[Macro, str]] = []
    for macro in mset.parsed.macros:
        change = changes.pop(macro.id.upper(), None)
        if change is None:
            rows.append((macro, ""))
        elif change.kind == "delete":
            rows.append((macro, "deleted"))
        else:
            rows.append((shown[macro.id.upper()], "changed"))
    rows += [(shown[key], "new") for key, change in changes.items() if change.kind == "add" and key in shown]
    return rows


class MacroProgressScreen(ProgressScreen):
    """Shown while an Apply, a dry run, an Undo or a recovery runs: one row per flavor."""

    ID_PREFIX = "macro"
    STAGE_TITLES: ClassVar[dict[str, str]] = STAGE_TITLES
    SIMULATED_STAGE = "check"

    def __init__(self, title: str, *, dry_run: bool = False, first_stage: str = "",
                 flavors: Sequence[Flavor] = (), parallelism: int = 1) -> None:
        super().__init__(title, dry_run=dry_run, first_stage=first_stage, units=flavors, parallelism=parallelism,
                         label=lambda flavor: flavor.display_name)


class MacroResultScreen(ResultScreen):
    """`title` is "Apply", "Dry run" or "Undo". With `back` (a dry run: nothing was written, the staged changes are
    still there) it opens on "Back to review", and Esc dismisses with "back"."""

    LOG_SCREEN = "macro_result"
    STATUS_COLOURS: ClassVar = STATUS_COLOURS

    def __init__(self, title: str, summary: list[tuple[str, str]], columns: tuple[str, ...], detail: list[tuple],
                 scope_label: str, *, back: bool = False) -> None:
        super().__init__(f"{TITLE} · {scope_label} · {title} result", summary, columns, detail, back=back)
        self.title_text = title


class MacroReviewScreen(WarningsHost, MacroEditActions, TreeFilter, SvRecoveryActions, RunActions, ReviewBase,
                        Screen[str]):
    """The macro sets of `flavors` (the flavor picked, or all of them). `wow_check` (tests inject one) stands for
    the running-WoW check."""

    WARNINGS_TITLE = "Warnings"
    WARNINGS_NOUN = "warning"
    SV_TOOL = SV_TOOL  # RunActions: macro.wow_running, the macro.apply / undo / recover error contexts
    RUN_PROGRESS = MacroProgressScreen  # SvRecoveryActions: the progress popup of a recovery
    TREE_SELECTOR = "#macros"
    LOG_SCREEN = "macro_review"
    HIDDEN_NOUN = "item"
    PREFLIGHT_TEXT = "Checking whether WoW is running…"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {
        "btn-apply": "apply", "btn-dry-run": "dry_run", "btn-rescan": "rescan", "btn-undo": "undo",
        **{button_id: name for button_id, _, _, name, _ in TREE_ACTIONS}}
    DEFAULT_CSS = two_pane_css("MacroReviewScreen", "#macros") + """
    MacroReviewScreen #pending { height: auto; margin-top: 1; }
    MacroReviewScreen #tree-pane { width: 1fr; }
    MacroReviewScreen #macros { height: 1fr; }
    MacroReviewScreen #tree-actions { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        # the keys of the buttons (left pane and the bar under the tree) are on them (D17)
        Binding("w", "apply", "Apply"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
        *(Binding(key, name, label, show=False) for _, label, _, name, key in TREE_ACTIONS),
        WARNINGS_BINDING,
        Binding("f", "leave('flavors')", "Flavors"),
        Binding("t", "leave('tools')", "Tools"),
        Binding("q", "app.quit", "Quit"),
        Binding("escape", "leave('flavors')", "Flavors", show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: list[Flavor], scope_label: str, *,
                 wow_check: WowCheck | None = None) -> None:
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/macro-editor.cfg
        self.flavors = list(flavors)
        self.scope_label = scope_label
        self._injected_check = wow_check
        self.wow_root = cfg.wow_path  # the WoW folder these flavors were read from (see wow_folder_changed)
        self._leaving_for_new_folder = False
        self.sets: dict[Path, MacroSet] = {}  # every set of every flavor, from the last scan, in scan order
        self.scanned = False
        self.scan_warnings: list[WarningItem] = []
        self.staged = Staged()
        self.ticked: set[Hashable] = set()
        self.clipboard: list[tuple[MacroSet, Macro]] = []  # what Copy took: the macros as they were then
        self.search_names = True
        self.search_bodies = True
        self.only_matching = True
        self.undoable: Path | None = None
        self.marker: Marker | None = None
        self.marker_root: Path | None = None
        self._offer_on_resume = False
        self.summary_text = ""
        self._stale = False  # an Apply or Undo changed the files: read them again when the review is shown

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield RiskBanner()
                yield FilterBar()
                yield Label("Search in", classes="section")
                yield Ka0sCheckbox("Names", True, id="search-names", compact=True)
                yield Ka0sCheckbox("Bodies", True, id="search-bodies", compact=True)
                yield Ka0sCheckbox("Only matching macros", True, id="only-matching", compact=True)
                yield Static(self._pending_line(), id="pending")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Apply", "destructive", "w", id="btn-apply")
                    yield action_button("Dry run", "simulate", "y", id="btn-dry-run")
                    yield action_button("Rescan", "refresh", "r", id="btn-rescan")
                    yield action_button("Undo last change", "revert", "z", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="tree-pane"):
                with Vertical(id="scan-box"):
                    yield ProgressBar(id="scan-progress", show_eta=False)
                    yield Static("", id="scan-label")
                yield BarTree(Text(self.scope_label, style=ACCENT), id="macros")
                with ActionBar(id="tree-actions"):
                    for button_id, label, kind, _, key in TREE_ACTIONS:
                        yield action_button(label, kind, key, id=button_id, compact=True)
        yield SummaryBar(Text(self.summary_text))
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = f"{TITLE} · {self.scope_label}"
        self.query_one("#scan-box").display = False
        self.query_one("#macros", Tree).focus()
        self._refresh_buttons()
        self._scan()

    def first_filter(self) -> Widget | None:
        return self.filter_input()

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

    @property
    def pending(self) -> int:
        """Staged changes: what an Apply would write (and leaving would drop). Ticks only select."""
        return self.staged.count()

    def all_sets(self) -> list[MacroSet]:
        return list(self.sets.values())

    def set_for(self, account: Account, character: Character | None) -> MacroSet | None:
        return self.sets.get((account.path if character is None else character.path) / MACRO_FILE)

    def _refresh_buttons(self) -> None:
        if not self.is_attached:
            return
        idle = self.idle
        self.query_one("#btn-apply", Button).disabled = not idle or not self.pending
        self.query_one("#btn-dry-run", Button).disabled = not idle or not self.pending
        self.query_one("#btn-rescan", Button).disabled = not idle
        self.query_one("#btn-undo", Button).disabled = not idle or self.undoable is None
        target_set = self.highlighted_set()
        macro = self.highlighted_macro()
        picked = bool(self.ticked_macros()) or macro is not None
        self.query_one("#act-new", Button).disabled = not idle or target_set is None or target_set.read_only
        self.query_one("#act-edit", Button).disabled = not idle or macro is None
        self.query_one("#act-delete", Button).disabled = not idle or not picked
        self.query_one("#act-copy", Button).disabled = not idle or not picked
        self.query_one("#act-paste", Button).disabled = not idle or not self.clipboard
        self.query_one("#act-replace", Button).disabled = not idle or not picked
        for box in self.query(Ka0sCheckbox).results(Ka0sCheckbox):
            box.disabled = not idle

    def ticks_frozen(self) -> bool:
        return not self.idle

    def _checking_changed(self) -> None:
        self._refresh_buttons()

    def check_for(self, folders: Iterable[str]) -> WowCheck:
        """The running-WoW check of these flavor folders."""
        return self._injected_check if self._injected_check is not None else wow_check_for(sorted(set(folders)))

    # --- scan ----------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if not self.idle or self.wow_folder_changed():
            return
        if self.pending:
            self.app.push_screen(ConfirmScreen("Discard the staged edits?",
                                               f"A rescan reads the files again and drops {self._pending_words()}; "
                                               "nothing has been written.", kind="destructive"),
                                 lambda ok: self._rescan_confirmed() if ok else None)
            return
        self._scan()

    def _rescan_confirmed(self) -> None:
        self.staged.clear()
        self._scan()

    def _scan(self) -> None:
        if not self.idle:
            return
        self._scanning = True
        self._stale = False
        self.show_scan_box(True, f"Reading the macros of {self.scope_label}")
        self._refresh_buttons()
        root = resolve_root(load_settings(self.tool_cfg), self.cfg.wow_path)
        journal_dir = resolve_journal_dir(self.cfg.wow_path)
        flavors = list(self.flavors)
        self.run_worker(lambda: self._scan_worker(flavors, root, journal_dir), thread=True, exclusive=True,
                        group="scan")

    def _scan_worker(self, flavors: list[Flavor], root: Path | None, journal_dir: Path | None) -> None:
        warnings: list[WarningItem] = []
        sets: list[MacroSet] = []
        try:
            for flavor in flavors:
                def on_error(path: Path, exc: OSError, flavor: Flavor = flavor) -> None:
                    warnings.append(WarningItem(where_text(path, flavor.path), exc.strerror or str(exc),
                                                flavor.display_name))
                sets += scan_sets(flavor, on_error)
            undoable = latest_undoable(journal_dir)
            marker = pending_recovery(root)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("macro.scan", exc)
            self.app.call_from_thread(self._scan_failed, f"The scan failed: {exc}")
            return
        for mset in sets:
            if mset.read_only:
                warnings.append(WarningItem(where_text(mset.path, mset.flavor.path),
                                            f"{READ_ONLY}: {mset.parsed.problem}", mset.flavor.display_name))
        self.app.call_from_thread(self._scanned, sets, warnings, undoable, marker, root)

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self.summary_text = message
        self.query_one("#summary", SummaryLine).show_one_line(message)
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, sets: list[MacroSet], warnings: list[WarningItem], undoable: Path | None,
                 marker: Marker | None, marker_root: Path | None) -> None:
        self._scanning = False
        self.sets = {mset.path: mset for mset in sets}
        for path in [p for p in self.staged.changes if p not in self.sets]:
            del self.staged.changes[path]  # a set gone since (a character folder removed)
        self.scanned = True
        self.scan_warnings = list(dict.fromkeys(warnings))
        self.ticked.intersection_update(self.all_tick_keys())
        self.undoable, self.marker, self.marker_root = undoable, marker, marker_root
        self._offer_on_resume = False
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self._rebuild()
        self._refresh_buttons()
        self.query_one("#macros", Tree).focus()
        if marker is not None:
            if self.app.screen is self:
                self.offer_recovery(marker)
            else:
                self._offer_on_resume = True

    def staging_changed(self) -> None:
        """After a paste, edit, new, delete or Replace text: ticks of macros gone drop out, the tree is built again."""
        self.ticked.intersection_update(self.all_tick_keys())
        self._schedule_rebuild()
        self._update_summary()

    # --- search ------------------------------------------------------------------------------------
    @property
    def narrowing(self) -> bool:
        """The search hides what does not match (Only matching macros ticked)."""
        return self.filtering and self.only_matching

    def filter_keys(self, keys: Collection[Hashable]) -> Collection[Hashable]:
        return super().filter_keys(keys) if self.narrowing else keys

    def tree_narrowed(self) -> bool:
        return self.narrowing

    def group_texts(self, mset: MacroSet) -> tuple[str, ...]:
        """What a set and its macros are matched on as a group: game version, account, realm, character (or
        Account macros)."""
        if mset.character is None:
            return mset.flavor.display_name, mset.account.name, ACCOUNT_MACROS
        return mset.flavor.display_name, mset.account.name, mset.character.realm, mset.character.name

    def macro_texts(self, macro: Macro) -> tuple[str, ...]:
        """A macro's own texts for the search: its name and/or its body (the left pane's boxes)."""
        return (*((macro.name,) if self.search_names else ()), *((macro.body,) if self.search_bodies else ()))

    def macro_matches(self, macro: Macro) -> bool:
        texts = self.macro_texts(macro)
        return self.filtering and bool(texts) and self.text_filter.matches(*texts)

    def filter_texts(self, key) -> tuple[str, ...]:
        mset = self.sets.get(key.path)
        if mset is None:
            return ()
        if isinstance(key, SetKey):
            return self.group_texts(mset)
        macro = next((m for m in effective_macros(self.staged, mset) if m.id.upper() == key.id.upper()), None)
        return (*self.group_texts(mset), *(self.macro_texts(macro) if macro is not None else ()))

    def _set_shown(self, mset: MacroSet | None) -> bool:
        if mset is None or not self.narrowing:
            return True
        return self.text_filter.path_matches(self.group_texts(mset)) or any(
            self.macro_matches(m) for m in effective_macros(self.staged, mset))

    # --- the tree ------------------------------------------------------------------------------
    def mark(self, keys: Iterable[Hashable]) -> tuple[str, str]:
        keys = list(keys)
        return self.shown_tick_mark(keys) if keys else (NO_MARK, "")

    def all_tick_keys(self) -> list[Hashable]:
        """Every set that can be pasted into and every macro that can be picked (read-only sets have none)."""
        keys: list[Hashable] = []
        for mset in self.sets.values():
            if mset.read_only:
                continue
            keys.append(SetKey(mset.path))
            keys += [MacroKey(mset.path, m.id) for m in effective_macros(self.staged, mset)]
        return keys

    def _character_key(self, character: Character) -> SetKey:
        return SetKey(character.path / MACRO_FILE)

    def _character_label(self, character: Character) -> str:
        mset = self.sets.get(character.path / MACRO_FILE)
        if mset is None or mset.read_only:
            return character.name
        return f"{character.name}  {slots_text(len(effective_macros(self.staged, mset)), mset.limit)}"

    def _disabled(self, character: Character) -> str | None:
        mset = self.sets.get(character.path / MACRO_FILE)
        return READ_ONLY if mset is not None and mset.read_only else None

    def _add_macros(self, mset: MacroSet, node: TreeNode) -> list[Hashable]:
        """The macro lines of a set under `node`; returns their tick keys. With the search narrowing, only the
        matching macros (all of them when the set's group matches), and the node opens."""
        whole = not self.narrowing or self.text_filter.path_matches(self.group_texts(mset))
        keys: list[Hashable] = []
        for macro, state in macro_rows(self.staged, mset):
            if not whole and not self.macro_matches(macro):
                continue
            key = MacroKey(mset.path, macro.id) if state != "deleted" and not mset.read_only else None
            data = MacroNode("macro", mset, macro, key, state)
            node.add_leaf(self._macro_label(data), data=data)
            if key is not None:
                keys.append(key)
        if self.narrowing and node.children:
            node.expand()
        return keys

    def _character_extra(self, character: Character, node: TreeNode) -> list[Hashable] | None:
        mset = self.sets.get(character.path / MACRO_FILE)
        return None if mset is None else self._add_macros(mset, node)

    def _account_extra(self, account: Account, node: TreeNode) -> list[Hashable] | None:
        mset = self.set_for(account, None)
        if mset is None or not self._set_shown(mset):
            return None
        own = () if mset.read_only else (SetKey(mset.path),)
        set_node = node.add(Text(ACCOUNT_MACROS), data=SetNode("set", mset, own), allow_expand=True)
        keys = (*own, *self._add_macros(mset, set_node))
        set_node.data = SetNode("set", mset, keys)
        set_node.allow_expand = bool(set_node.children)
        set_node.set_label(self._label(set_node.data))
        return list(keys)

    def _shown(self, flavor: Flavor):
        if not self.narrowing:
            return None
        return lambda c: self._set_shown(self.sets.get(c.path / MACRO_FILE)) or \
            self.text_filter.path_matches((flavor.display_name, c.account, c.realm, c.name))

    def _rebuild(self) -> None:
        tree = self.query_one("#macros", Tree)
        cursor = tree.cursor_node.data if tree.cursor_node is not None else None
        opened = self._opened(tree)
        tree.clear()
        many = len(self.flavors) > 1
        for flavor in self.flavors:
            parent = tree.root.add(Text(flavor.display_name), data=["flavor", flavor.folder, ()],
                                   expand=True) if many else tree.root
            scanned = self.scanned
            keys = populate_characters(parent, flavor, key=self._character_key, label=self._character_label,
                                       disabled=self._disabled,
                                       account_extra=self._account_extra if scanned else None,
                                       character_extra=self._character_extra if scanned else None,
                                       shown=self._shown(flavor), mark=self.mark)
            if many:
                if self.narrowing and not parent.children:
                    parent.remove()
                    continue
                parent.data = ["flavor", flavor.folder, tuple(keys)]
                parent.set_label(self._label(parent.data))
        self.note_no_match(tree.root)
        tree.root.expand()
        self._reopen(tree, opened)
        self._restore_cursor(tree, cursor)
        self._update_summary()

    @staticmethod
    def _node_ident(data) -> Hashable | None:
        if isinstance(data, SetNode):
            return ("set", data.mset.path)
        if isinstance(data, MacroNode):
            return ("macro", data.mset.path, data.macro.id.upper())
        if isinstance(data, CharacterNode):
            return (data.kind, data.account.path, data.realm, data.character.path if data.character else None)
        return None

    def _walk(self, tree: Tree) -> Iterable[TreeNode]:
        stack = list(tree.root.children)
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children)

    def _opened(self, tree: Tree) -> set[Hashable]:
        """The sets the user opened (kept across a rebuild)."""
        return {self._node_ident(n.data) for n in self._walk(tree)
                if n.is_expanded and isinstance(n.data, (SetNode, CharacterNode)) and
                (isinstance(n.data, SetNode) or n.data.kind == "character")}

    def _reopen(self, tree: Tree, opened: set[Hashable]) -> None:
        for node in self._walk(tree):
            if node.children and self._node_ident(node.data) in opened:
                node.expand()

    def _restore_cursor(self, tree: Tree, data) -> None:
        wanted = self._node_ident(data)
        if wanted is None:
            return
        for node in self._walk(tree):
            if self._node_ident(node.data) == wanted:
                self.call_after_refresh(lambda n=node: tree.move_cursor(n) if n.tree is tree else None)
                return

    def _macro_label(self, data: MacroNode) -> Text:
        """The tick, the staged mark (short, before the line: a macro line is often wider than the tree) and
        `name · first line · n/255`."""
        parts: list[tuple[str, str]] = [self.shown_tick_mark([data.key]) if data.key is not None else (NO_MARK, "")]
        if data.state == "deleted":
            parts.append((f"{DELETED_MARK} ", f"bold {theme_colour(self.app, 'error')}"))
        elif data.state:
            parts.append((f"{CHANGED_MARK if data.state == 'changed' else NEW_MARK} ",
                          f"bold {theme_colour(self.app, 'warning')}"))
        style = "dim strike" if data.state == "deleted" else "dim" if data.mset.read_only else ""
        if data.state != "deleted" and not self.narrowing and self.macro_matches(data.macro):
            style = MATCH_STYLE
        parts.append((macro_text(data.macro), style))
        return Text.assemble(*parts)

    def _label(self, data) -> Text:
        if isinstance(data, MacroNode):
            return self._macro_label(data)
        if isinstance(data, SetNode):
            mset = data.mset
            if mset.read_only:
                return Text.assemble((NO_MARK, ""), (ACCOUNT_MACROS, "dim"), (f"  {READ_ONLY}", "dim italic"))
            count = len(effective_macros(self.staged, mset))
            return Text.assemble(self.mark(data.keys), (ACCOUNT_MACROS, "bold"),
                                 (f"  {slots_text(count, mset.limit)}", ""))
        if isinstance(data, CharacterNode):
            return character_label(data, self.mark)
        mark = self.mark(data[2]) if data[2] else (NO_MARK, "")
        return Text.assemble(mark, (flavor_name(data[1]), "bold"))

    def _refresh_labels(self, node: TreeNode | None = None) -> None:
        relabel_branch(self.query_one("#macros", Tree), node, self._label)
        self._update_summary()

    # --- the highlighted node ------------------------------------------------------------------------
    def _cursor_data(self):
        if not self.is_attached:
            return None
        node = self.query_one("#macros", Tree).cursor_node
        return None if node is None else node.data

    def highlighted_set(self) -> MacroSet | None:
        """The set of the highlighted line: a macro's, Account macros, or a character's."""
        data = self._cursor_data()
        if isinstance(data, (SetNode, MacroNode)):
            return data.mset
        if isinstance(data, CharacterNode) and data.character is not None:
            return self.sets.get(data.character.path / MACRO_FILE)
        return None

    def highlighted_macro(self) -> tuple[MacroSet, Macro] | None:
        """The highlighted macro, when it can be edited (not deleted, not in a read-only set)."""
        data = self._cursor_data()
        if isinstance(data, MacroNode) and data.key is not None:
            return data.mset, data.macro
        return None

    def ticked_macros(self) -> list[tuple[MacroSet, Macro]]:
        """The ticked macros as staged, in scan order (ticks the search hides included)."""
        picked: list[tuple[MacroSet, Macro]] = []
        for mset in self.sets.values():
            for macro in effective_macros(self.staged, mset):
                if MacroKey(mset.path, macro.id) in self.ticked:
                    picked.append((mset, macro))
        return picked

    def ticked_sets(self) -> list[MacroSet]:
        return [mset for mset in self.sets.values() if SetKey(mset.path) in self.ticked and not mset.read_only]

    def picked_macros(self) -> list[tuple[MacroSet, Macro]]:
        """What Copy, Delete and Replace text act on: the ticked macros, else the highlighted one."""
        ticked = self.ticked_macros()
        if ticked:
            return ticked
        macro = self.highlighted_macro()
        return [macro] if macro is not None else []

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.control.id == "macros":
            self._update_summary()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        names = {"search-names": "search_names", "search-bodies": "search_bodies", "only-matching": "only_matching"}
        attribute = names.get(event.checkbox.id or "")
        if attribute is None:
            return
        event.stop()
        setattr(self, attribute, event.value)
        log_event("ui.selection", screen=self.LOG_SCREEN, control=attribute, value=event.value)
        if self.filtering:
            self._schedule_rebuild()

    # --- summaries -------------------------------------------------------------------------------
    def warning_items(self) -> list[WarningItem]:
        return list(self.scan_warnings)

    def _pending_words(self) -> str:
        return plural(self.pending, "staged edit")

    def _pending_line(self) -> Text:
        """`Staged: N changes in F files` (what Apply writes) and, after Copy, what Paste… pastes."""
        files = len(self.staged.changes)
        line = Text.assemble(("Staged: ", "bold"), f"{plural(self.pending, 'edit')} in {plural(files, 'file')}")
        if self.clipboard:
            line.append_text(Text.assemble("\n", ("Copied: ", "bold"), plural(len(self.clipboard), "macro")))
        return line

    def _where(self, node: TreeNode | None) -> str:
        names = []
        while node is not None and node.data is not None:
            data = node.data
            if isinstance(data, MacroNode):
                names.append(data.macro.name)
            elif isinstance(data, SetNode):
                names.append(ACCOUNT_MACROS)
            elif isinstance(data, CharacterNode):
                names.append(data.character.name if data.character is not None else data.text)
            else:
                names.append(flavor_name(data[1]))
            node = node.parent
        return " › ".join(reversed(names)) or self.scope_label

    def _update_summary(self) -> None:
        if not self.is_attached or not self.scanned:
            return
        tree = self.query_one("#macros", Tree)
        macros, sets = len(self.ticked_macros()), len(self.ticked_sets())
        self.summary_text = (f"Selected: {self._where(tree.cursor_node)}    Ticked: {plural(macros, 'macro')}, "
                             f"{plural(sets, 'set')}")
        hidden = self.hidden_ticked_note()
        if hidden:
            self.summary_text += f"    {hidden}"
        self.query_one("#summary", Static).update(Text(self.summary_text))
        self.query_one("#pending", Static).update(self._pending_line())
        self.refresh_warnings()
        self._refresh_buttons()

    # --- ticks -----------------------------------------------------------------------------------
    def tick_model(self) -> TickModel:
        return TickModel.of_ticked(self.ticked)

    def node_tick_keys(self, node) -> tuple[Hashable, ...]:
        data = node.data
        if isinstance(data, MacroNode):
            return (data.key,) if data.key is not None else ()
        if isinstance(data, SetNode):
            return tuple(data.keys)
        if isinstance(data, CharacterNode):
            return tuple(node_keys(node))
        if isinstance(data, list) and data and data[0] == "flavor":
            return tuple(data[2])
        return ()

    def tick_log_key(self, node, keys) -> str:
        return self._where(node)

    # --- runs: apply, dry run, undo (RunActions) --------------------------------------------------------
    def run_backup_dir(self) -> Path | None:
        return load_settings(self.tool_cfg).backup_dir

    def _set_stale(self) -> None:
        """The files changed under this scan: drop what is staged and the ticks; they are read again when the
        review is shown."""
        self.staged.clear()
        self.ticked.clear()
        self._stale = True

    def _mark_stale(self) -> None:
        self._set_stale()
        if self.idle and self.is_attached and self.app.screen is self:
            self._scan()

    def action_apply(self) -> None:
        self._start(dry_run=False)

    def action_dry_run(self) -> None:
        self._start(dry_run=True)

    def _start(self, dry_run: bool) -> None:
        """Apply / Dry run of everything staged. A dry run writes nothing, so it needs no WoW check, backup folder
        or settled unfinished run."""
        if not self.idle or not self.pending or self.wow_folder_changed():
            return
        log_event("ui.selection", screen=self.LOG_SCREEN, control="dry_run" if dry_run else "apply", value=True)
        if dry_run:
            self._show_confirm(True, [])
            return
        if self.marker is not None:
            self.offer_recovery(self.marker)
            return
        if self._backup_dir_refused():
            return
        check = self.check_for(self.sets[path].flavor.folder for path in self.staged.changes)
        self._check_wow(check, lambda running: self._after_apply_preflight(check, running))

    def _after_apply_preflight(self, check: WowCheck, running: list[str] | None) -> None:
        alerts: list[str] = []
        if not self._refused_while_running(running, alerts):
            self._show_confirm(False, alerts, check)

    def _show_confirm(self, dry_run: bool, extra: list[str], check: WowCheck | None = None) -> None:
        sets = self.all_sets()
        title, body, alerts = apply_confirm(self.staged, sets, dry_run=dry_run)
        self.app.push_screen(ConfirmScreen(title, body, (*extra, *alerts), kind="simulate" if dry_run else "destructive",
                                           groups=apply_groups(self.staged, sets)),
                             lambda ok: self._apply_confirmed(ok, dry_run, check))

    def _apply_confirmed(self, ok: bool | None, dry_run: bool, check: WowCheck | None) -> None:
        log_event("ui.selection", screen="confirm", control="apply_confirm", value=bool(ok), dry_run=dry_run)
        wow_root = self.cfg.wow_path
        if not ok or wow_root is None or not self.idle:
            return
        root, journal_dir = resolve_root(load_settings(self.tool_cfg), wow_root), resolve_journal_dir(wow_root)
        if root is None or journal_dir is None:
            return
        sets = self.all_sets()
        staged = Staged({path: list(changes) for path, changes in self.staged.changes.items()})
        flavors = list(dict.fromkeys(self.sets[change.path].flavor for change in build_changes(staged, sets)))
        screen = MacroProgressScreen("Simulating the changes" if dry_run else "Applying the changes",
                                     dry_run=dry_run, flavors=flavors)
        keep_snapshots, keep_journals = self.cfg.keep_backups, self.cfg.keep_journals
        self.start_run(screen, lambda: run_apply(staged, sets, root=root, journal_dir=journal_dir,
                                                 keep_journals=keep_journals, keep_snapshots=keep_snapshots,
                                                 dry_run=dry_run, wow_check=check, progress=screen.report_unit),
                       self._applied, name="apply", failure="The run stopped unexpectedly",
                       stale_on_crash=not dry_run, expected=(ApplyError,))

    def _applied(self, result: MultiApplyResult) -> None:
        kept = result.dry_run or not (result.edited or result.rolled_back or result.failed)
        if not kept:
            self._set_stale()
        self._refresh_buttons()
        if result.stopped is not None:
            self.notify(f"{result.stopped.flavor.display_name}: {result.stopped.error}", title="Apply stopped",
                        severity="error", timeout=20)
        self.app.push_screen(MacroResultScreen("Dry run" if result.dry_run else "Apply", summary_rows(result),
                                               FILE_COLUMNS, file_rows(result), self.scope_label, back=kept),
                             self._after_result)

    def _after_result(self, choice: str | None) -> None:
        if choice in ("flavors", "tools", "quit"):
            self.action_leave(choice)
        elif choice == "back":
            return
        elif self._stale:
            self._scan()
        else:
            self.action_rescan()

    def action_undo(self) -> None:
        """z: put back the files the newest Apply changed and remove those it created, after the WoW check and a
        confirm that says what staged work it drops."""
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
        parallelism = self.cfg.parallelism
        screen = MacroProgressScreen("Undoing the last change", first_stage="undo",
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
        self.app.push_screen(MacroResultScreen("Undo", undo_summary_rows(result), UNDO_COLUMNS,
                                               undo_detail_rows(result), self.scope_label), self._after_result)

    # --- recovery (SvRecoveryActions) -----------------------------------------------------------------
    def recovery_screen(self, marker: Marker) -> Screen:
        message = recovery_text(marker)
        if self.pending:
            message += (f"\n\nPutting the originals back reads the files again: the {self._pending_words()} not "
                        "applied yet will be dropped.")
        return UnfinishedRunScreen(message, marker)

    def recovery_root(self) -> Path | None:
        return self.marker_root if self.marker_root is not None else \
            resolve_root(load_settings(self.tool_cfg), self.cfg.wow_path)

    def run_leave(self, marker: Marker, *, root: Path) -> bool:
        return leave(marker, root=root)

    def run_recover(self, marker: Marker, **kwargs) -> UndoResult:
        return recover(marker, **kwargs)

    def recovery_done(self) -> None:
        self._mark_stale()

    # --- leaving -------------------------------------------------------------------------------
    def discard_question(self) -> tuple[str, str] | None:
        """Leaving or quitting drops the staged changes: ask first."""
        if not self.pending:
            return None
        return ("Leave and discard the staged edits?",
                f"{self._pending_words().capitalize()} not applied yet will be dropped; nothing has been written.")
