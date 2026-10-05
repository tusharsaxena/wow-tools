"""Review the AceDB profiles of the chosen flavors as a tree (by addon or by character), tick profiles and
characters, pick deletes, renames, copies and reassignments (pending changes, shown in the tree until written), then
apply them, try them in a dry run, or undo the last change. A guidance line and an action bar under the tree say
what can be done next."""
from __future__ import annotations

import time
from collections.abc import Callable, Hashable, Iterable, Iterator
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, ProgressBar, Static, Tree
from textual.widgets.tree import TreeNode

from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.journal import Journal, friendly_stamp
from wowtools.core.process import wow_check_for
from wowtools.tools.ace3_profile_manager.blacklist_screen import BlacklistScreen
from wowtools.tools.ace3_profile_manager.editor import ApplyError, Marker, clear_marker, read_marker
from wowtools.tools.ace3_profile_manager.journal import latest_undoable, read_profile_journal
from wowtools.tools.ace3_profile_manager.model import DEFAULT
from wowtools.tools.ace3_profile_manager.multi import MultiApplyResult, apply_flavors
from wowtools.tools.ace3_profile_manager.ops import DbKey, DbState, OpResult, Staging, valid_name
from wowtools.tools.ace3_profile_manager.popups import ActionsScreen, NameScreen, TargetScreen
from wowtools.tools.ace3_profile_manager.report import (CHARACTER_KINDS, DETAIL_COLUMNS, NO_PENDING, STAGE_TITLES,
                                                        STEPS, UNDO_COLUMNS, apply_confirm, apply_detail_rows,
                                                        apply_summary_rows, flavor_name, guidance, pending_text, plural,
                                                        selection_text, shorten, undo_confirm, undo_detail_rows,
                                                        undo_summary_rows)
from wowtools.tools.ace3_profile_manager.result_screen import ProfileResultScreen
from wowtools.tools.ace3_profile_manager.scanner import ScanResult, SvFile, scan_flavors
from wowtools.tools.ace3_profile_manager.settings import (Pair, format_blacklist, is_blacklisted, load_settings,
                                                          resolve_journal_dir, resolve_root, save_settings, toggle_pair,
                                                          validate_backup_dir)
from wowtools.tools.ace3_profile_manager.tree_view import READ_ONLY, Filters, TreeBuilder, counts, ident
from wowtools.tools.ace3_profile_manager.undo import UndoError, UndoResult, recover, undo_run
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import (BUSY_STYLE, POPUP_WIDTH, REVIEW_HINT, TREE_BINDINGS, TREE_HINT, ConfirmScreen,
                                InfoScreen, ProgressScreen, TwoPaneFocus, relabel_branch, theme_colour, tick_mark,
                                two_pane_css)
from wowtools.ui.widgets import (NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, WrapButtonRow, action_button,
                                 wrap_items)

NAV_HINT = (REVIEW_HINT + "a all · n none · d delete · p assign · m more · w apply · y dry run · " + TREE_HINT +
            "r rescan · z undo · f flavors · t tools")
WowCheck = Callable[[], "list[str] | None"]
SHOW_FILTERS = {"only-multi": "only_multi", "only-unused": "only_unused", "show-leftovers": "leftovers",
                "show-blacklisted": "blacklisted"}
PROGRESS_EVERY = 0.05  # seconds between two scan progress reports sent to the UI thread
GUIDE_MAX_ROWS = 2  # the guidance line leaves its per-node hint out rather than take more rows than this
GROUP_KINDS = ("root", "flavor", "account")  # nodes too broad to stand for a selection when nothing is ticked
# The action bar under the tree: (id, label, kind of action, action). Each button does what its key does; one with
# nothing to act on stays enabled and says what to tick or highlight. The labels are short enough for two rows at
# 160x45 (and three at 120x30): tests/test_look_and_feel.py.
TREE_ACTIONS = (
    ("act-delete", "Delete (d)", "delete", "delete"),
    ("act-assign", "Assign (p)", "apply", "assign"),
    ("act-rename", "Rename (e)", "apply", "rename"),
    ("act-copy", "Copy (k)", "apply", "copy"),
    ("act-keep-default", "Only Default", "delete", "keep_default"),
    ("act-everyone-default", "Everyone → Default", "apply", "everyone_default"),
    ("act-leftovers", "Leftovers (o)", "delete", "remove_leftovers"),
    ("act-blacklist", "Blacklist…", "neutral", "edit_blacklist"),
    ("act-more", "More… (m)", "neutral", "more"),
    ("act-discard", "Discard (⌫)", "neutral", "discard"),
)


class NotTicked:
    """The keys not ticked, as tick_mark's `unchecked` collection (without listing every key)."""

    def __init__(self, ticked: set[tuple]) -> None:
        self.ticked = ticked

    def __contains__(self, key: object) -> bool:
        return key not in self.ticked

    def __iter__(self) -> Iterator:
        return iter(())

    def __len__(self) -> int:
        return 0


class ProfileProgressScreen(ProgressScreen):
    """Shown while an Apply, a dry run, an Undo or a recovery runs."""

    ID_PREFIX = "ace"
    STAGE_TITLES = STAGE_TITLES
    SIMULATED_STAGE = "check"


class ProfileRecoveryScreen(ModalScreen[str]):
    """An earlier Apply did not finish: put the originals back from its zip, or leave the files as they are.
    Dismisses with "put_back" or "leave" (None when closed with Esc: offered again at the next scan)."""

    DEFAULT_CSS = f"""
    ProfileRecoveryScreen {{ align: center middle; }}
    ProfileRecoveryScreen #recovery-box {{ {POPUP_WIDTH} height: auto; max-height: 100%; overflow-y: auto;
                                          border: thick $warning; background: $panel; padding: 1 2; }}
    ProfileRecoveryScreen #recovery-title {{ color: $warning; text-style: bold; margin-bottom: 1; }}
    ProfileRecoveryScreen #recovery-buttons {{ height: auto; align-horizontal: right; margin-top: 1; }}
    ProfileRecoveryScreen Button {{ margin-left: 2; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "dismiss", "Close", show=False)]

    def __init__(self, marker: Marker) -> None:
        super().__init__()
        self.marker = marker

    def message(self) -> str:
        marker = self.marker
        return "\n".join([
            (f"A change to {flavor_name(marker.flavor)} started {friendly_stamp(marker.started)} did not finish "
             f"({plural(len(marker.files), 'file')})."),
            "The original files are in:",
            str(marker.zip),
            ("Put the originals back: each file the change wrote is restored from that zip; a file saved since "
             "(by WoW) is left as it is."),
            "Leave as is: the files stay as they are now; the zip and the WTF backup are kept.",
        ])

    def compose(self) -> ComposeResult:
        with Vertical(id="recovery-box"):
            yield Static(Text("An earlier change did not finish"), id="recovery-title")
            yield Static(Text(self.message()))
            with ButtonRow(id="recovery-buttons"):
                yield action_button("Leave as is", "neutral", id="leave")
                yield action_button("Put the originals back", "revert", id="put_back")

    def on_mount(self) -> None:
        self.query_one("#put_back", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id)


class ProfileTree(Tree):
    """The profiles tree. ← jumps to the left panel (instead of scrolling sideways)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Filters", show=False)]


class ProfileReviewScreen(TwoPaneFocus, Screen[str]):
    """The AceDB databases of the chosen flavors (and account) as a tree. Dismisses with "flavors", "tools" or
    "quit". `unlocked` is the flow's set of casefolded blacklisted (flavor folder, addon) pairs unlocked this
    session (shared, not copied)."""

    TREE_SELECTOR = "#profiles"
    # Designed for 120x30 (tests/test_look_and_feel.py): the left pane has one control per row under its View and
    # Show headings, and still fits its hint when the pending line takes three rows (every kind of change) and the
    # bottom line two (scan warnings). The tree pane holds the tree, the guidance line and the action bar (at most
    # two rows) and the guidance line (at most GUIDE_MAX_ROWS: it drops its per-node hint rather than take more).
    DEFAULT_CSS = two_pane_css("ProfileReviewScreen", "#profiles") + """
    ProfileReviewScreen #tree-pane { width: 1fr; }
    ProfileReviewScreen #profiles { height: 1fr; }
    ProfileReviewScreen #guide { height: auto; color: $text-muted; padding: 0 1; }
    ProfileReviewScreen #tree-actions { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        # d, p and m are on the action bar's buttons (with their keys): the footer leaves them out, so the rest
        # fits at 120 columns
        Binding("d", "delete", "Delete", show=False),
        Binding("p", "assign", "Assign", show=False),
        Binding("e", "rename", "Rename", show=False),
        Binding("k", "copy", "Copy", show=False),
        Binding("o", "remove_leftovers", "Remove leftovers", show=False),
        Binding("m", "more", "More", show=False),
        Binding("backspace", "discard", "Discard", show=False),
        Binding("b", "blacklist", "Blacklist", show=False),
        Binding("u", "unlock", "Unlock", show=False),
        Binding("v", "switch_view", "View", show=False),
        Binding("slash", "focus_search", "Search", show=False),
        Binding("w", "apply", "Apply"),
        Binding("y", "dry_run", "Dry run"),
        Binding("r", "rescan", "Rescan"),
        Binding("z", "undo", "Undo"),
        Binding("f", "leave('flavors')", "Flavors"),
        Binding("t", "leave('tools')", "Tools"),
        Binding("q", "leave('quit')", "Quit"),
        Binding("escape", "back", "Flavors", show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *TREE_BINDINGS,
        *NAV_BINDINGS,
    ]

    def __init__(self, cfg: Config, tool_cfg: Config, flavors: list[Flavor], scope_label: str, *,
                 account: str | None, unlocked: set[tuple[str, str]], wow_check: WowCheck | None = None) -> None:
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/ace3-profile-manager.cfg
        self.flavors = list(flavors)
        self.scope_label = scope_label
        self.account = account
        self.unlocked = unlocked
        self._injected_check = wow_check  # tests inject one; it then stands for every flavor
        self.wow_check = self.check_for([f.folder for f in self.flavors])
        # The WoW folder these flavors were read from (see wow_folder_changed).
        self.wow_root = cfg.wow_path
        self._leaving_for_new_folder = False
        self.settings = load_settings(tool_cfg)
        self.scan: ScanResult | None = None
        self.staging: Staging | None = None
        self.ticked: set[tuple] = set()  # ("p", DbKey, profile) and ("c", DbKey, char)
        self.view = "addon"
        self.filters = Filters()
        self.undoable: Path | None = None  # the newest undoable journal, found by the scan worker
        self.marker: Marker | None = None  # an Apply that did not finish, found by the scan worker
        self.summary_text = f"Selected: 0 profiles · 0 characters · {NO_PENDING}"
        self.guide_text = guidance(None, "", 0, 0, 0)
        self._guide_shown = self.guide_text  # guide_text as the guide shows it (the steps wrapped between steps)
        self._builder: TreeBuilder | None = None
        self._expanded: dict[Hashable, bool] = {}
        self._scanning = False
        self._checking = False  # a running-WoW check is in its worker
        self._rebuild_pending = False
        self._last_filter: Widget | None = None
        self._stale = False  # an Apply or Undo changed the files: rescan when the review is shown again

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("View", classes="section")
                yield Ka0sCheckbox("By addon", True, id="view-addon", compact=True)
                yield Ka0sCheckbox("By character", False, id="view-character", compact=True)
                yield Label("Show", classes="section")
                yield Ka0sCheckbox("Only addons with 2+ profiles", False, id="only-multi", compact=True)
                yield Ka0sCheckbox("Only unused profiles", False, id="only-unused", compact=True)
                yield Ka0sCheckbox("Leftover characters", True, id="show-leftovers", compact=True)
                yield Ka0sCheckbox("Blacklisted addons", True, id="show-blacklisted", compact=True)
                yield Input(placeholder="Search addon, profile or character", id="search", compact=True)
                yield Static(self._pending_line(NO_PENDING), id="pending")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Apply", "delete", id="btn-apply")
                    yield action_button("Dry run", "simulate", id="btn-dry-run")
                    yield action_button("Rescan", "neutral", id="btn-rescan")
                    yield action_button("Undo last change", "revert", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Vertical(id="tree-pane"):
                with Vertical(id="scan-box"):
                    yield ProgressBar(id="scan-progress", show_eta=False)
                    yield Static("", id="scan-label")
                yield ProfileTree(Text(self.scope_label), id="profiles")
                yield Static(Text(self.guide_text), id="guide")
                with WrapButtonRow(id="tree-actions"):
                    for button_id, label, kind, _ in TREE_ACTIONS:
                        yield action_button(label, kind, id=button_id, compact=True)
        yield Static(Text(self.summary_text), id="summary")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"Ace3 Profile Manager · {self.scope_label}"
        self.query_one("#scan-box").display = False
        self.query_one("#profiles", Tree).focus()
        self._refresh_buttons()
        self._scan()

    # --- panes (←/→): TwoPaneFocus ------------------------------------------------------------------
    def first_filter(self) -> Widget | None:
        return next((w for w in self.query("#filters Ka0sCheckbox").results(Ka0sCheckbox) if w.focusable), None)

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
        elif self.scan is not None:
            self._reload_settings()

    # --- state ---------------------------------------------------------------------------------
    @property
    def idle(self) -> bool:
        """Nothing is scanning, checking or running: the actions are open."""
        return not (self._scanning or self._checking or self.app.busy)

    def _refresh_buttons(self) -> None:
        if not self.is_attached:
            return
        idle = self.idle
        pending = self.staging is not None and self.staging.summary().total > 0
        self.query_one("#btn-apply", Button).disabled = not idle or not pending
        self.query_one("#btn-dry-run", Button).disabled = not idle or not pending
        self.query_one("#btn-rescan", Button).disabled = not idle
        self.query_one("#btn-undo", Button).disabled = not idle or self.undoable is None

    def locked(self, flavor: str, addon: str) -> bool:
        """(flavor folder, addon) is blacklisted and not unlocked this session: shown, never changed."""
        return (is_blacklisted(self.settings.blacklist, flavor, addon)
                and (flavor.casefold(), addon.casefold()) not in self.unlocked)

    def check_for(self, folders: Iterable[str]) -> WowCheck:
        """The running-WoW check of these flavor folders (an Undo or a recovery may touch a flavor that is not
        being reviewed)."""
        return self._injected_check if self._injected_check is not None else wow_check_for(sorted(set(folders)))

    def _blacklisted(self, flavor: str, addon: str) -> bool:
        return is_blacklisted(self.settings.blacklist, flavor, addon)

    # --- scan ----------------------------------------------------------------------------------
    def action_rescan(self) -> None:
        if not self.idle or self.wow_folder_changed():
            return
        if self.staging is not None and self.staging.summary().total:
            self.app.push_screen(ConfirmScreen("Discard the pending changes?",
                                               "A rescan reads the files again and drops every pending change."),
                                 lambda ok: self._scan() if ok else None)
            return
        self._scan()

    def _scan(self) -> None:
        if not self.idle:
            return
        self._stale = False
        self.settings = load_settings(self.tool_cfg)
        self._show_scan_progress(True)
        self._refresh_buttons()
        flavors, account = list(self.flavors), self.account
        root, journal_dir = resolve_root(self.settings, self.cfg.wow_path), resolve_journal_dir(self.cfg.wow_path)
        self.run_worker(lambda: self._scan_worker(flavors, account, root, journal_dir), thread=True,
                        exclusive=True, group="scan")

    def _show_scan_progress(self, scanning: bool) -> None:
        """While scanning, the tree is replaced by a progress bar and the file being read."""
        self._scanning = scanning
        if scanning:
            self.query_one("#scan-progress", ProgressBar).update(total=None, progress=0)
            self.query_one("#scan-label", Static).update(Text("Reading SavedVariables"))
        self.query_one("#scan-box").display = scanning
        self.query_one("#profiles", Tree).display = not scanning

    def _scan_worker(self, flavors: list[Flavor], account: str | None, root: Path | None,
                     journal_dir: Path | None) -> None:
        last = [0.0]

        def progress(flavor: Flavor, current: int, total: int, name: str) -> None:
            now = time.monotonic()
            if current < total and now - last[0] < PROGRESS_EVERY:
                return
            last[0] = now
            self.app.call_from_thread(self._scan_progress, current, total, name)

        try:
            scan = scan_flavors(flavors, account=account, progress=progress)
            undoable = latest_undoable(journal_dir)
            marker = read_marker(root)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("ace.scan", exc)
            self.app.call_from_thread(self._scan_failed, f"The scan failed: {exc}")
            return
        self.app.call_from_thread(self._scanned, scan, undoable, marker)

    def _scan_progress(self, current: int, total: int, name: str) -> None:
        if not self.is_attached:
            return
        self.query_one("#scan-progress", ProgressBar).update(total=total or None, progress=current)
        self.query_one("#scan-label", Static).update(Text(f"Reading SavedVariables: {name}" if name else
                                                          "Reading SavedVariables"))

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        if not self.is_attached:
            return
        self._show_scan_progress(False)
        self.summary_text = message
        self.query_one("#summary", Static).update(Text(message))
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, scan: ScanResult, undoable: Path | None, marker: Marker | None) -> None:
        self._scanning = False
        self.scan, self.undoable, self.marker = scan, undoable, marker
        self.staging = Staging.from_scan(scan, locked=self.locked)
        self.ticked.clear()
        if not self.is_attached:
            return
        self._show_scan_progress(False)
        self.refresh_view()
        self._refresh_buttons()
        self.query_one("#profiles", Tree).focus()
        if marker is not None:
            self.offer_recovery(marker)

    # --- tree ------------------------------------------------------------------------------------
    def _schedule_rebuild(self) -> None:
        """Show that the list is being rebuilt, then rebuild once that has been drawn. Changes made before the
        rebuild runs are folded into it."""
        if self.scan is None:
            return
        self.query_one("#profiles", Tree).loading = True
        self.query_one("#summary", Static).update(Text("Updating the list…", style=BUSY_STYLE))
        if not self._rebuild_pending:
            self._rebuild_pending = True
            self.call_after_refresh(self._run_scheduled_rebuild)

    def _run_scheduled_rebuild(self) -> None:
        self._rebuild_pending = False
        try:
            self.refresh_view()
        finally:
            self.query_one("#profiles", Tree).loading = False

    def _walk_tree(self) -> Iterator[TreeNode]:
        stack = [self.query_one("#profiles", Tree).root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children)

    def refresh_view(self) -> None:
        """Rebuild the tree and the bottom line from the scan, the pending changes and the filters, keeping ticks,
        expansion and the highlighted node."""
        if self.scan is None or self.staging is None or not self.is_attached:
            return
        tree = self.query_one("#profiles", Tree)
        if self._builder is not None and not self._builder.searching:  # remember what the user opened and closed
            for node in self._walk_tree():
                if node.data is not None and node.allow_expand:
                    self._expanded[ident(node.data)] = node.is_expanded
        cursor = tree.cursor_node
        cursor_id = ident(cursor.data) if cursor is not None and cursor.data is not None else None
        self.filters.view = self.view
        self._builder = TreeBuilder(self.scan, self.staging, self.filters, scope_label=self.scope_label,
                                    locked=self.locked, blacklisted=self._blacklisted, expanded=self._expanded,
                                    warning_style=theme_colour(self.app, "warning"))
        self._builder.build(tree)
        for node in self._walk_tree():
            node.set_label(self._label(node.data))
        tree.get_node_at_line(0)  # lay the lines out now, so the cursor (and move_cursor) find the new nodes
        if cursor_id is not None:
            target = next((n for n in self._walk_tree() if n.data is not None and ident(n.data) == cursor_id), None)
            if target is not None and target.line >= 0:
                tree.move_cursor(target)
        self._update_summary()

    def _tick_keys(self, node: TreeNode | None) -> tuple:
        if node is None or node.data is None or self._builder is None:
            return ()
        return self._builder.keys.get(id(node.data), ())

    def _label(self, data) -> Text:
        builder = self._builder
        if builder is None or data is None:
            return Text("")
        body = builder.bodies.get(id(data), Text(""))
        keys = builder.keys.get(id(data), ())
        if not keys:
            return Text.assemble("  ", body)
        mark = tick_mark(keys, NotTicked(self.ticked), success=theme_colour(self.app, "success"))
        return Text.assemble(mark, body)

    def _refresh_labels(self, node: TreeNode | None = None) -> None:
        relabel_branch(self.query_one("#profiles", Tree), node, self._label, skip=READ_ONLY)
        self._update_summary()

    def _update_summary(self) -> None:
        if self.scan is None or self.staging is None or not self.is_attached:
            return
        summary = self.staging.summary()
        profiles, chars = counts(self.ticked)
        self.summary_text = selection_text(profiles, chars, summary, len(self.scan.warnings))
        self.query_one("#summary", Static).update(Text(self.summary_text))
        self.query_one("#pending", Static).update(self._pending_line(pending_text(summary)))
        self._refresh_buttons()
        self._update_guide()

    @staticmethod
    def _pending_line(text: str) -> Text:
        return Text.assemble(("Pending changes: ", "bold"), text)

    def _node_name(self, data) -> str:
        """The name the guidance line gives the highlighted node."""
        kind = data[0]
        if kind == "addon":
            return data[1].file.addon
        if kind == "db" and self.staging is not None:
            return self.staging.state(data[1]).file.addon
        if kind == "profile" or kind in CHARACTER_KINDS:
            return data[2]
        return ""

    def _update_guide(self) -> None:
        """The guidance line: the pending changes, then what can be done with the ticks or the highlighted node
        (left out when there is no room for it: see _guide_fits)."""
        if self.staging is None or not self.is_attached:
            return
        node = self.query_one("#profiles", Tree).cursor_node
        data = node.data if node is not None else None
        kind, name = (data[0], self._node_name(data)) if data else (None, "")
        file = self._file_of(node)
        locked = file.addon if file is not None and self.locked(file.flavor.folder, file.addon) else ""
        summary = self.staging.summary()
        profiles, chars = counts(self.ticked)
        text = guidance(kind, name, profiles, chars, summary.total, locked=locked)
        if summary.total and not self._guide_fits(text):  # a long name: the hint would wrap
            text = self._shortened_guidance(kind, name, profiles, chars, summary.total, locked)
        guide = self.query_one("#guide", Static)
        # The steps wrap between steps only ("→ 4" never ends a row with "Apply (w)" on the next).
        shown = wrap_items(text, guide.content_size.width, " → ") if text == STEPS else text
        if text != self.guide_text or shown != self._guide_shown:
            self.guide_text, self._guide_shown = text, shown
            guide.update(Text(shown))

    def _shortened_guidance(self, kind, name: str, profiles: int, chars: int, total: int, locked: str) -> str:
        """The guidance with the node's (or locked addon's) name shortened with "…" until the guide fits in
        GUIDE_MAX_ROWS rows, so the hint stays next to the pending line; without the hint only if even that fails."""
        for keep in range(max(len(name), len(locked)) - 1, 0, -1):
            text = guidance(kind, shorten(name, keep), profiles, chars, total, locked=shorten(locked, keep))
            if self._guide_fits(text):
                return text
        return guidance(kind, name, profiles, chars, total, hint=False)

    def _guide_fits(self, text: str) -> bool:
        """The guide, wrapped to its width, takes at most GUIDE_MAX_ROWS rows. True until it is laid out."""
        guide = self.query_one("#guide", Static)
        if guide.size.width <= 0:
            return True
        return len(Text(text).wrap(self.app.console, guide.size.width)) <= GUIDE_MAX_ROWS

    def on_resize(self) -> None:
        self.call_after_refresh(self._update_guide)  # once the guide has its new width

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.control.id == "profiles":
            self._update_guide()

    # --- selection -----------------------------------------------------------------------------------
    def _selected(self, kind: str) -> dict[DbKey, list[str]]:
        """The ticked keys of this kind, else the highlighted node's; never every key of a flavor, an account or the
        whole tree when nothing is ticked (that needs ticks, a for all)."""
        keys = self.ticked
        if not keys:
            node = self.query_one("#profiles", Tree).cursor_node
            broad = node is None or node.data is None or node.data[0] in GROUP_KINDS
            keys = set() if broad else set(self._tick_keys(node))
        out: dict[DbKey, list[str]] = {}
        for key in sorted((k for k in keys if k[0] == kind), key=lambda k: (str(k[1].path), k[1].sv_name, k[2])):
            out.setdefault(key[1], []).append(key[2])
        return out

    def selected_profiles(self) -> dict[DbKey, list[str]]:
        """The ticked profiles, or the highlighted node's (an addon, a database or a profile) when nothing is
        ticked."""
        return self._selected("p")

    def selected_chars(self) -> dict[DbKey, list[str]]:
        """The ticked characters, or the highlighted node's when nothing is ticked."""
        return self._selected("c")

    # --- ticks -----------------------------------------------------------------------------------
    def action_toggle(self) -> None:
        focused = self.focused
        if isinstance(focused, Checkbox):
            focused.toggle()
            return
        if isinstance(focused, Button):  # Space activates the focused button, never the tree
            focused.press()
            return
        if isinstance(focused, Input):  # Space is priority-bound: type it into the search box
            focused.insert_text_at_cursor(" ")
            return
        if not isinstance(focused, Tree) or not self.idle:
            return
        node = self.query_one("#profiles", Tree).cursor_node
        keys = self._tick_keys(node)
        if node is None or not keys:
            return
        check = any(k not in self.ticked for k in keys)
        if check:
            self.ticked.update(keys)
        else:
            self.ticked.difference_update(keys)
        log_event("ui.item_toggled", screen="ace_review", key=str(ident(node.data)), checked=check)
        self._refresh_labels(node)

    def action_select_all(self) -> None:
        tree = self.query_one("#profiles", Tree)
        self.ticked.update(self._tick_keys(tree.root))  # visible keys only: hidden ones stay as they are
        log_event("ui.selection", screen="ace_review", control="select_all", value=True)
        self._refresh_labels()

    def action_select_none(self) -> None:
        self.ticked.clear()
        log_event("ui.selection", screen="ace_review", control="select_none", value=True)
        self._refresh_labels()

    # --- filters ---------------------------------------------------------------------------------
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        widget_id = event.checkbox.id or ""
        if widget_id in ("view-addon", "view-character"):
            self._set_view("addon" if (widget_id == "view-addon") == event.value else "character")
            return
        name = SHOW_FILTERS.get(widget_id)
        if name is None:
            return
        setattr(self.filters, name, event.value)
        log_event("ui.selection", screen="ace_review", control=name, value=event.value)
        self._schedule_rebuild()

    def _set_view(self, view: str) -> None:
        """The two View boxes act as a pair: exactly one is ticked."""
        self.query_one("#view-addon", Ka0sCheckbox).value = view == "addon"
        self.query_one("#view-character", Ka0sCheckbox).value = view == "character"
        if view == self.view:
            return
        self.view = view
        log_event("ui.selection", screen="ace_review", control="view", value=view)
        self._schedule_rebuild()

    def action_switch_view(self) -> None:
        self._set_view("character" if self.view == "addon" else "addon")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.filters.search = event.value
            self._schedule_rebuild()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#profiles", Tree).focus()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    # --- blacklist -------------------------------------------------------------------------------
    def _file_of(self, node: TreeNode | None) -> SvFile | None:
        """The SavedVariables file (flavor and addon) of this addon node, or of the addon it is in (None above
        one)."""
        while node is not None and node.data is not None:
            data = node.data
            if data[0] == "addon":
                return data[1].file
            if len(data) > 1 and isinstance(data[1], DbKey) and self.staging is not None:
                return self.staging.state(data[1]).file
            node = node.parent
        return None

    def _file_at_cursor(self) -> SvFile | None:
        """The SavedVariables file (flavor and addon) of the highlighted addon, or of what is highlighted in one."""
        file = self._file_of(self.query_one("#profiles", Tree).cursor_node)
        if file is None:
            self.notify("Highlight an addon (or something inside one) first.")
        return file

    def _flavor_folders(self) -> list[str]:
        """Every flavor folder of the install (a wildcard pair taken off in one flavor stays in the others)."""
        try:
            folders = [f.folder for f in WowInstall(self.cfg.wow_path).flavors()] if self.cfg.wow_path else []
        except OSError:
            folders = []
        return folders or [f.folder for f in self.flavors]

    def action_blacklist(self) -> None:
        """b: blacklist the highlighted addon in its flavor, or take it off."""
        if not self.idle or self.scan is None:
            return
        file = self._file_at_cursor()
        if file is None:
            return
        flavor, addon = file.flavor.folder, file.addon
        self.settings = load_settings(self.tool_cfg)
        self.settings.blacklist, listed = toggle_pair(self.settings.blacklist, flavor, addon, self._flavor_folders())
        save_settings(self.tool_cfg, self.settings, source="review")
        log_event("ace.blacklist_changed", flavor=flavor, addon=addon, blacklisted=listed)
        where = flavor_name(flavor)
        self.notify(f"{addon} ({where}) is {'now' if listed else 'no longer'} on the blacklist.")
        self._drop_locked()
        self._schedule_rebuild()

    def action_edit_blacklist(self) -> None:
        """The blacklist tree for the reviewed flavors; what it saves is written at once."""
        if not self.idle or self.wow_folder_changed():
            return
        self.settings = load_settings(self.tool_cfg)
        self.app.push_screen(BlacklistScreen(self.cfg, self.flavors, self.settings.blacklist),
                             self._blacklist_edited)

    def _blacklist_edited(self, pairs: list[Pair] | None) -> None:
        if pairs is None:
            return
        self.settings = load_settings(self.tool_cfg)
        self.settings.blacklist = pairs
        save_settings(self.tool_cfg, self.settings, source="review")
        log_event("ace.blacklist_changed", pairs=format_blacklist(pairs))
        self.notify("Blacklist saved.")
        self._drop_locked()
        self._schedule_rebuild()

    def action_unlock(self) -> None:
        if not self.idle or self.scan is None:
            return
        file = self._file_at_cursor()
        if file is None:
            return
        flavor, addon = file.flavor.folder, file.addon
        if not self._blacklisted(flavor, addon):
            self.notify(f"{addon} is not blacklisted.")
            return
        pair = (flavor.casefold(), addon.casefold())
        unlocked = pair not in self.unlocked
        if unlocked:
            self.unlocked.add(pair)
        else:
            self.unlocked.discard(pair)
        log_event("ace.unlocked", flavor=flavor, addon=addon, unlocked=unlocked)
        self.notify(f"{addon} is {'unlocked for this session' if unlocked else 'locked again'}.")
        self._drop_locked()
        self._schedule_rebuild()

    def _drop_locked(self) -> bool:
        """A blacklisted (locked) addon is never changed: drop its pending changes and its ticks, and say so.
        True when something was dropped."""
        if self.staging is None:
            return False
        files = {k: self.staging.state(k[1]).file for k in self.ticked}
        locked = {k for k, f in files.items() if self.locked(f.flavor.folder, f.addon)}
        self.ticked -= locked
        dropped = self.staging.drop_locked()
        if dropped:
            self.notify(f"Dropped the pending changes of {', '.join(dropped)}: blacklisted addons are never "
                        "changed.", title="Blacklisted", severity="warning", timeout=10)
        return bool(dropped or locked)

    def _reload_settings(self) -> None:
        """Read the settings again (changed with `s`): a newly blacklisted addon loses its pending changes."""
        self.settings = load_settings(self.tool_cfg)
        if self._drop_locked() and self.is_attached:
            self.refresh_view()

    # --- staging -------------------------------------------------------------------------------------
    def _ready(self) -> bool:
        return self.idle and self.staging is not None and not self.wow_folder_changed()

    def _addon_name(self, key: DbKey) -> str:
        """The addon, with its database when its file has several, and its flavor and account when the same
        addon is in another one too (All flavors, or a flavor with several accounts)."""
        assert self.staging is not None
        state = self.staging.state(key)
        name = state.file.addon
        if sum(1 for k in self.staging.states if k.path == key.path) > 1:
            name += f" ({key.sv_name})"
        others = [s.file for s in self.staging.states.values()
                  if s.file.addon.casefold() == state.file.addon.casefold() and s.file.path != key.path]
        if others:
            where = [state.file.account] + ([state.file.owner] if state.file.character is not None else [])
            if any(f.flavor != state.file.flavor for f in others):
                where.insert(0, flavor_name(state.file.flavor.folder))
            name += f" [{' · '.join(where)}]"
        return name

    def _targets(self, keys: Iterable[DbKey], exclude: dict[DbKey, list[str]] | None = None) -> list[str]:
        """"Default" first, then every profile name of these databases, minus the ones being deleted (a profile
        deleted in any of them can't take their characters)."""
        assert self.staging is not None
        gone = {n for names in (exclude or {}).values() for n in names}
        names: list[str] = [] if DEFAULT in gone else [DEFAULT]
        for key in keys:
            names += [n for n in self.staging.state(key).names() if n not in gone and n not in names]
        return names

    def _staged(self, result: OpResult) -> None:
        """After an operation: say what was refused and noted (one notification each, however many databases),
        clear the ticks of the databases it changed and show the new pending changes."""
        assert self.staging is not None
        if result.refused:
            lines = [f"{self._addon_name(key)}: {reason}" for key, reason in result.refused]
            self.notify(self._lines(lines), title=f"Not done ({len(lines)})", severity="warning", timeout=15)
        changed = set(result.applied)
        self.ticked = {k for k in self.ticked if k[1] not in changed}
        self.refresh_view()
        if result.notes:
            self.app.push_screen(InfoScreen("Notes", self._notes_by_message(result.notes)))

    @staticmethod
    def _notes_by_message(notes: list[str]) -> dict[str, list[str]]:
        """Notes ("<addon>: <message>") grouped by message, with the addons it concerns under it."""
        groups: dict[str, list[str]] = {}
        for note in dict.fromkeys(notes):
            addon, sep, message = note.partition(": ")
            if not sep:
                groups.setdefault(note, [])
                continue
            message = message.rstrip(".")
            groups.setdefault(message[:1].upper() + message[1:], []).append(addon)
        return groups

    @staticmethod
    def _lines(lines: list[str], most: int = 8) -> str:
        shown = lines[:most]
        if len(lines) > most:
            shown.append(f"… and {len(lines) - most} more")
        return "\n".join(shown)

    def action_delete(self) -> None:
        if not self._ready():
            return
        assert self.staging is not None
        selection = self.selected_profiles()
        if not selection:
            self.notify("Tick or highlight a profile first")
            return
        lines = []
        for key, names in selection.items():
            state = self.staging.state(key)
            moved = sum(len(state.users(n)) for n in names)
            lines.append(f"{self._addon_name(key)}: {', '.join(names)} ({plural(moved, 'character')} move)")
        body = "\n".join(["Delete these profiles and move their characters to the profile chosen below:", *lines])

        def done(target: str | None) -> None:
            if target is not None and self.staging is not None:
                self._staged(self.staging.delete(selection, target))
        self.app.push_screen(TargetScreen("Delete profiles", body, self._targets(selection, selection)), done)

    def action_assign(self) -> None:
        if not self._ready():
            return
        assert self.staging is not None
        selection = self.selected_chars()
        if not selection:
            self.notify("Tick or highlight a character first")
            return
        lines = [f"{self._addon_name(key)}: {plural(len(chars), 'character')}" for key, chars in selection.items()]
        body = "\n".join(["Move these characters to the profile chosen below:", *lines])

        def done(target: str | None) -> None:
            if target is not None and self.staging is not None:
                self._staged(self.staging.assign(selection, target))
        self.app.push_screen(TargetScreen("Assign a profile", body, self._targets(selection)), done)

    def _highlighted_profile(self) -> tuple[DbKey, str] | None:
        node = self.query_one("#profiles", Tree).cursor_node
        data = node.data if node is not None else None
        if data is None or data[0] != "profile":
            self.notify("Highlight a profile")
            return None
        return data[1], data[2]

    def _name_check(self, key: DbKey) -> Callable[[str], str | None]:
        def check(name: str) -> str | None:
            problem = valid_name(name)
            if problem is None and self.staging is not None and self.staging.state(key).taken(name):
                problem = f'"{name}" is already a profile of this database.'
            return problem
        return check

    def action_rename(self) -> None:
        if not self._ready():
            return
        picked = self._highlighted_profile()
        if picked is None:
            return
        key, name = picked

        def done(new: str | None) -> None:
            if new is not None and self.staging is not None:
                self._staged(self.staging.rename(key, name, new))
        body = f'{self._addon_name(key)}: rename "{name}". Its characters follow it.'
        self.app.push_screen(NameScreen("Rename a profile", body, name, self._name_check(key)), done)

    def action_copy(self) -> None:
        if not self._ready():
            return
        picked = self._highlighted_profile()
        if picked is None:
            return
        key, name = picked

        def done(new: str | None) -> None:
            if new is not None and self.staging is not None:
                self._staged(self.staging.copy(key, name, new))
        body = f'{self._addon_name(key)}: copy "{name}" (its settings) under a new name.'
        self.app.push_screen(NameScreen("Copy a profile", body, f"{name} copy", self._name_check(key)), done)

    def action_remove_leftovers(self) -> None:
        if not self._ready():
            return
        assert self.staging is not None
        staging = self.staging
        selection = {key: [c for c in chars if c in staging.state(key).leftovers]
                     for key, chars in self.selected_chars().items()}
        selection = {key: chars for key, chars in selection.items() if chars}
        if not selection:
            self.notify("Tick or highlight a leftover character first")
            return
        groups = {self._addon_name(key): chars for key, chars in selection.items()}
        body = "These characters have no folder in WTF any more. Remove their entries from these addons:"

        def done(ok: bool | None) -> None:
            if ok and self.staging is not None:
                self._staged(self.staging.remove_leftovers(selection))
        self.app.push_screen(ConfirmScreen("Remove leftover characters?", body, groups=groups), done)

    def _databases(self) -> list[DbKey]:
        """The databases of the ticked keys, else of the highlighted node's addon or database."""
        if self.ticked:
            return sorted({k[1] for k in self.ticked}, key=lambda k: (str(k.path), k.sv_name))
        node = self.query_one("#profiles", Tree).cursor_node
        data = node.data if node is not None else None
        if data is not None and data[0] == "addon":
            return [DbKey(data[1].file.path, db.sv_name) for db in data[1].dbs]
        if data is not None and len(data) > 1 and isinstance(data[1], DbKey):
            return [data[1]]
        return []

    def _tick_leftovers(self) -> None:
        assert self.staging is not None
        staging = self.staging
        visible = self._tick_keys(self.query_one("#profiles", Tree).root)
        leftovers = {k for k in visible if k[0] == "c" and k[2] in staging.state(k[1]).leftovers}
        if not leftovers:
            self.notify("No leftover characters are shown.")
            return
        self.ticked.update(leftovers)
        log_event("ui.selection", screen="ace_review", control="tick_leftovers", value=len(leftovers))
        self._refresh_labels()

    def action_more(self) -> None:
        if not self._ready():
            return

        def done(choice: str | None) -> None:
            if choice is None or self.staging is None:
                return
            keys = {"discard": self.action_discard, "rename": self.action_rename, "copy": self.action_copy,
                    "blacklist": self.action_blacklist, "edit_blacklist": self.action_edit_blacklist,
                    "unlock": self.action_unlock, "switch_view": self.action_switch_view,
                    "search": self.action_focus_search, "tick_leftovers": self._tick_leftovers,
                    "select_all": self.action_select_all, "select_none": self.action_select_none}
            if choice in keys:
                keys[choice]()
        self.app.push_screen(ActionsScreen(), done)

    def _whole_databases(self, operation: str) -> None:
        """Run a Staging operation (keep_only_default, everyone_to_default) on whole databases: the ticked ones,
        else the highlighted addon's or database."""
        if not self._ready():
            return
        assert self.staging is not None
        keys = self._databases()
        if not keys:
            self.notify("Tick or highlight an addon first")
            return
        self._staged(getattr(self.staging, operation)(keys))

    def action_keep_default(self) -> None:
        self._whole_databases("keep_only_default")

    def action_everyone_default(self) -> None:
        self._whole_databases("everyone_to_default")

    def action_discard(self) -> None:
        if not self._ready():
            return
        assert self.staging is not None
        summary = self.staging.summary()
        if not summary.total:
            self.notify(NO_PENDING)
            return

        def done(ok: bool | None) -> None:
            if ok and self.staging is not None:
                self.staging.discard()
                log_event("ui.selection", screen="ace_review", control="discard", value=True)
                self.refresh_view()
        self.app.push_screen(ConfirmScreen("Discard the pending changes?",
                                           f"{pending_text(summary)}. Nothing has been written; the files stay as "
                                           "they are."), done)

    # --- runs: apply, dry run, undo ---------------------------------------------------------------------
    def _progress_cb(self, screen: ProfileProgressScreen) -> Callable[..., None]:
        def progress(flavor: Flavor, stage: str, current: int, total: int, detail: str) -> None:
            def show() -> None:
                if screen.is_attached:
                    screen.set_flavor(flavor.display_name)
                    screen.update_progress(stage, current, total, detail)
            self.app.call_from_thread(show)
        return progress

    def _run_preflight(self, then: Callable[[list[str] | None], None], check: WowCheck | None = None) -> None:
        """Run the running-WoW check (`check`, else the reviewed flavors') in a worker (it can take seconds), then
        call `then` with its answer on the UI thread: process names, [] when none run, None when it could not
        run."""
        self._checking = True
        self._refresh_buttons()
        self.query_one("#summary", Static).update(Text("Checking whether WoW is running…", style=BUSY_STYLE))
        check = check or self.wow_check
        self.run_worker(lambda: self._preflight_worker(check, then), thread=True, group="preflight")

    def _preflight_worker(self, check: WowCheck, then: Callable[[list[str] | None], None]) -> None:
        running = None
        try:
            running = check()
        except Exception as exc:  # noqa: BLE001 - a failed check is "unknown"
            log_exception("preflight", exc)
        self.app.call_from_thread(self._preflight_done, running, then)

    def _preflight_done(self, running: list[str] | None, then: Callable[[list[str] | None], None]) -> None:
        self._checking = False
        if not self.is_attached:
            return
        self._update_summary()
        if self.app.screen is not self:
            return  # the user left the screen while the check ran
        then(running)

    def _refused_while_running(self, running: list[str] | None, alerts: list[str]) -> bool:
        """True (and say so) when WoW runs; adds an alert when the check could not run."""
        if running:
            log_event("ace.wow_running", action="preflight", running=running)
            self.notify(f"WoW is running ({', '.join(running)}). Close it first: it would overwrite the changes.",
                        title="WoW is running", severity="error", timeout=15)
            return True
        if running is None:
            alerts.append("Could not check whether WoW is running; close it before you go on.")
        return False

    def action_apply(self) -> None:
        self._start(dry_run=False)

    def action_dry_run(self) -> None:
        self._start(dry_run=True)

    def _backup_dir_refused(self) -> bool:
        """True (and say so) when the backup folder in the settings is not allowed (it may have been edited by
        hand in the cfg): checked before anything is written to it, as on save."""
        wow_path = self.cfg.wow_path
        if wow_path is None:
            return False
        problem = validate_backup_dir(load_settings(self.tool_cfg).backup_dir, WowInstall(wow_path))
        if problem:
            self.notify(f"{problem} Fix the folder in settings (s).", title="Backup folder not allowed",
                        severity="error", timeout=15)
        return bool(problem)

    def apply_check(self) -> WowCheck:
        """The running-WoW check of the flavors with pending changes (only their files are written)."""
        changed = self.staging.changed() if self.staging is not None else []
        return self.check_for({s.file.flavor.folder for s in changed})

    def _start(self, dry_run: bool) -> None:
        if not self._ready():
            return
        assert self.staging is not None
        log_event("ui.selection", screen="ace_review", control="dry_run" if dry_run else "apply", value=True)
        self._reload_settings()
        if not self.staging.summary().total:
            self.notify(NO_PENDING)
            return
        if dry_run:  # writes nothing: WoW running and the backup folder do not matter
            self._show_apply_confirm(dry_run, [])
            return
        if self.marker is not None:  # an earlier Apply did not finish: settle that first (Apply would refuse)
            self.offer_recovery(self.marker)
            return
        if self._backup_dir_refused():
            return
        check = self.apply_check()
        self._run_preflight(lambda running: self._after_apply_preflight(running), check)

    def _after_apply_preflight(self, running: list[str] | None) -> None:
        alerts: list[str] = []
        if not self._refused_while_running(running, alerts):
            self._show_apply_confirm(False, alerts)

    def _show_apply_confirm(self, dry_run: bool, extra: list[str]) -> None:
        if self.staging is None or not self.staging.summary().total:
            self.notify(NO_PENDING)
            return
        states = self.staging.changed()
        title, body, alerts = apply_confirm(self.staging.summary(), states, dry_run=dry_run)
        self.app.push_screen(ConfirmScreen(title, body, (*alerts, *extra), default_yes=dry_run),
                             lambda ok: self._apply_confirmed(ok, dry_run))

    def _apply_confirmed(self, ok: bool | None, dry_run: bool) -> None:
        log_event("ui.selection", screen="confirm", control="apply_confirm", value=bool(ok), dry_run=dry_run)
        if not ok or self.staging is None or self.cfg.wow_path is None:
            return
        self.settings = load_settings(self.tool_cfg)
        root = resolve_root(self.settings, self.cfg.wow_path)
        journal_dir = resolve_journal_dir(self.cfg.wow_path)
        if root is None or journal_dir is None:
            return
        changed = self.staging.changed()
        plan = [(flavor, [s for s in changed if s.file.flavor == flavor]) for flavor in self.flavors]
        plan = [(flavor, states) for flavor, states in plan if states]
        self.app.busy = True
        self._refresh_buttons()
        screen = ProfileProgressScreen(dry_run=dry_run)
        self.app.push_screen(screen)
        keep = (self.cfg.keep_backups, self.cfg.keep_journals)
        check = None if dry_run else self.apply_check()
        self.run_worker(lambda: self._apply_worker(plan, root, journal_dir, keep, dry_run, screen, check),
                        thread=True, exclusive=True, group="run")

    def _apply_worker(self, plan: list[tuple[Flavor, list[DbState]]], root: Path, journal_dir: Path,
                      keep: tuple[int, int], dry_run: bool, screen: ProfileProgressScreen,
                      check: WowCheck | None = None) -> None:
        """keep: (backups, journals) to keep, from [general]."""
        try:
            with activity.running():
                result = apply_flavors(plan, root=root, journal_dir=journal_dir,
                                       keep_journals=keep[1], keep_snapshots=keep[0],
                                       dry_run=dry_run, account=self.account,
                                       wow_check=check,
                                       progress=self._progress_cb(screen))
        except ApplyError as exc:  # WowRunning included: refused before anything was written
            log_exception("ace.apply", exc)
            self.app.call_from_thread(self._run_failed, screen, str(exc), False)
            return
        except Exception as exc:  # noqa: BLE001 - shown and logged, never a crash
            log_exception("ace.apply", exc)
            self.app.call_from_thread(self._run_failed, screen, f"The run stopped unexpectedly: "
                                      f"{type(exc).__name__}: {exc}", not dry_run)
            return
        self.app.call_from_thread(self._applied, screen, result)

    def _close_progress(self, screen: ModalScreen) -> None:
        self.app.busy = False
        if self.app.screen is screen:
            self.app.pop_screen()

    def _run_failed(self, screen: ModalScreen, message: str, stale: bool) -> None:
        self._close_progress(screen)
        if stale:  # files may have changed: the scan no longer matches them
            self._mark_stale()
        self._refresh_buttons()
        self.notify(message, severity="error", timeout=15)

    def _mark_stale(self) -> None:
        """The files changed under this scan: drop the staging and rescan when the review is shown again."""
        self._stale = True
        self.ticked.clear()
        if self.staging is not None:
            self.staging.discard()

    def _applied(self, screen: ModalScreen, result: MultiApplyResult) -> None:
        self._close_progress(screen)
        if not result.dry_run:
            self._mark_stale()
        self._refresh_buttons()
        if result.stopped is not None:
            self.notify(f"{result.stopped.flavor.display_name}: {result.stopped.error}", title="Apply stopped",
                        severity="error", timeout=20)
        self.app.push_screen(ProfileResultScreen("Dry run" if result.dry_run else "Apply",
                                                 apply_summary_rows(result), DETAIL_COLUMNS,
                                                 apply_detail_rows(result), self.scope_label,
                                                 back=result.dry_run), self._after_result)

    def _after_result(self, choice: str | None) -> None:
        if choice in ("flavors", "tools", "quit"):
            self.action_leave(choice)
        elif choice == "back":  # after a dry run: back to the review, the pending changes kept
            return
        elif self._stale:
            self._scan()
        else:
            self.action_rescan()

    def action_undo(self) -> None:
        if not self.idle or self.wow_folder_changed():
            return
        log_event("ui.selection", screen="ace_review", control="undo", value=True)
        path = self.undoable
        if path is None:
            self.notify("Nothing to undo")
            return
        if self._backup_dir_refused():
            return
        try:
            journal = read_profile_journal(path)
        except (OSError, ValueError) as exc:
            self.notify(f"The journal could not be read: {exc}", severity="error")
            return
        # the journal may be another flavor's (the newest of the whole tool): check the flavors it changed
        folders = {e["flavor"] for e in journal.entries}
        check = self.check_for(folders)
        self._run_preflight(lambda running: self._after_undo_preflight(path, journal, check, running), check)

    def _after_undo_preflight(self, path: Path, journal: Journal, check: WowCheck,
                              running: list[str] | None) -> None:
        extra: list[str] = []
        if self._refused_while_running(running, extra):
            return
        pending = self.staging.summary().total if self.staging is not None else 0
        if pending:
            extra.append(f"The {plural(pending, 'pending change')} not applied yet will be dropped.")
        title, body, alerts = undo_confirm(journal)
        self.app.push_screen(ConfirmScreen(title, body, (*alerts, *extra)),
                             lambda ok: self._undo_confirmed(ok, path, check))

    def _undo_confirmed(self, ok: bool | None, path: Path, check: WowCheck) -> None:
        log_event("ui.selection", screen="confirm", control="undo_confirm", value=bool(ok))
        wow_root = self.cfg.wow_path
        if not ok or wow_root is None:
            return
        self.settings = load_settings(self.tool_cfg)
        root = resolve_root(self.settings, wow_root)
        if root is None:
            return
        self.app.busy = True
        self._refresh_buttons()
        screen = ProfileProgressScreen(dry_run=False, first_stage="undo")
        self.app.push_screen(screen)
        keep = self.cfg.keep_backups
        self.run_worker(lambda: self._undo_worker(path, wow_root, root, keep, check, screen), thread=True,
                        exclusive=True, group="run")

    def _undo_worker(self, path: Path, wow_root: Path, root: Path, keep_snapshots: int, check: WowCheck,
                     screen: ProfileProgressScreen) -> None:
        def progress(stage: str, current: int, total: int, detail: str) -> None:
            self.app.call_from_thread(lambda: screen.update_progress(stage, current, total, detail)
                                      if screen.is_attached else None)

        try:
            with activity.running():
                result = undo_run(path, wow_root=wow_root, root=root, keep_snapshots=keep_snapshots,
                                  wow_check=check, progress=progress)
        except UndoError as exc:  # WoW running, locked files, the backup failed: nothing was changed
            log_exception("ace.undo", exc)
            self.app.call_from_thread(self._run_failed, screen, str(exc), False)
            return
        except Exception as exc:  # noqa: BLE001 - e.g. an unreadable journal: shown, never a crash
            log_exception("ace.undo", exc)
            self.app.call_from_thread(self._run_failed, screen, f"Undo stopped unexpectedly: "
                                      f"{type(exc).__name__}: {exc}", True)
            return
        self.app.call_from_thread(self._undone, screen, result)

    def _undone(self, screen: ModalScreen, result: UndoResult) -> None:
        self._close_progress(screen)
        self._mark_stale()
        self._refresh_buttons()
        self.app.push_screen(ProfileResultScreen("Undo", undo_summary_rows(result), UNDO_COLUMNS,
                                                 undo_detail_rows(result), self.scope_label), self._after_result)

    # --- recovery ----------------------------------------------------------------------------------
    def offer_recovery(self, marker: Marker) -> None:
        """An Apply did not finish: offer to put the originals back."""
        log_event("ace.recovery_offered", flavor=marker.flavor, files=len(marker.files), started=marker.started)
        self.app.push_screen(ProfileRecoveryScreen(marker), lambda choice: self._recovery_chosen(marker, choice))

    def _recovery_chosen(self, marker: Marker, choice: str | None) -> None:
        root = resolve_root(load_settings(self.tool_cfg), self.cfg.wow_path)
        if root is None or choice not in ("put_back", "leave"):
            return  # closed without a choice: offered again at the next scan
        if choice == "leave":
            clear_marker(root)
            log_event("ace.recovery_done", choice="leave")
            self.marker = None
            return
        if self._backup_dir_refused():
            return  # the marker stays: offered again at the next scan
        check = self.check_for([marker.flavor])  # the marker's flavor, which may not be the one reviewed
        self._run_preflight(lambda running: self._after_recover_preflight(marker, root, check, running), check)

    def _after_recover_preflight(self, marker: Marker, root: Path, check: WowCheck,
                                 running: list[str] | None) -> None:
        if self._refused_while_running(running, []):
            return  # the marker stays: offered again at the next scan
        self.app.busy = True
        self._refresh_buttons()
        screen = ProfileProgressScreen(dry_run=False, first_stage="undo")
        self.app.push_screen(screen)
        keep = self.cfg.keep_backups
        self.run_worker(lambda: self._recover_worker(marker, root, check, screen, keep), thread=True,
                        exclusive=True, group="run")

    def _recover_worker(self, marker: Marker, root: Path, check: WowCheck, screen: ProfileProgressScreen,
                        keep_snapshots: int | None = None) -> None:
        def progress(stage: str, current: int, total: int, detail: str) -> None:
            self.app.call_from_thread(lambda: screen.update_progress(stage, current, total, detail)
                                      if screen.is_attached else None)

        try:
            with activity.running():
                result = recover(marker, root=root, journal_dir=resolve_journal_dir(self.cfg.wow_path),
                                 keep_snapshots=keep_snapshots, wow_check=check, progress=progress)
        except UndoError as exc:  # WoW running, locked files, the backup failed: nothing was changed
            log_exception("ace.recover", exc)
            self.app.call_from_thread(self._run_failed, screen, str(exc), False)
            return
        except Exception as exc:  # noqa: BLE001 - shown and logged, never a crash
            log_exception("ace.recover", exc)
            self.app.call_from_thread(self._run_failed, screen, f"Putting the originals back stopped: "
                                      f"{type(exc).__name__}: {exc}", True)
            return
        self.app.call_from_thread(self._recovered, screen, result)

    def _recovered(self, screen: ModalScreen, result: UndoResult) -> None:
        self._close_progress(screen)
        self.marker = None
        message = (f"Put back {plural(len(result.restored), 'file')}; left {plural(len(result.skipped), 'file')} "
                   f"as they are")
        if result.failed:
            message += f"; {plural(len(result.failed), 'file')} could not be put back (see the log)"
        self.notify(message + ".", title="Unfinished change", severity="error" if result.failed else "information",
                    timeout=15)
        self._stale = False
        self._scan()

    # --- leaving -------------------------------------------------------------------------------
    def action_back(self) -> None:
        """Esc: out of the search box back to the tree; else back to the flavor picker."""
        if isinstance(self.focused, Input):
            self.query_one("#profiles", Tree).focus()
            return
        self.action_leave("flavors")

    def action_leave(self, choice: str) -> None:
        if self.app.busy:
            return
        pending = self.staging.summary().total if self.staging is not None else 0
        if not pending:
            self.dismiss(choice)
            return
        self.app.push_screen(ConfirmScreen("Leave and discard the pending changes?",
                                           f"{plural(pending, 'pending change')} not applied yet will be dropped; "
                                           "nothing has been written."),
                             lambda ok: self.dismiss(choice) if ok else None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {"btn-apply": self.action_apply, "btn-dry-run": self.action_dry_run,
                   "btn-rescan": self.action_rescan, "btn-undo": self.action_undo}
        actions.update({button_id: getattr(self, f"action_{name}") for button_id, _, _, name in TREE_ACTIONS})
        action = actions.get(event.button.id or "")
        if action is not None:
            event.stop()
            action()
