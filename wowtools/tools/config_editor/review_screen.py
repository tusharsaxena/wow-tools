"""The Config Editor's browse screen (config tools spec CE2-CE8; X1-X5, X8): every CVar file of the chosen flavors
(a scan in a worker, scanner.scan_targets, with the flavor's CVar data and recommendations from core.kb) as the
shared character tree, (flavor ›) Config.wtf, account › Account config and realm › character (the character's
config-cache.wtf). A file opens to its CVar rows, loaded when it is opened (a file can set hundreds, and Show all
known adds the knowledge base's): five aligned columns, name, value, default, state and category (feedback spec
CF1-CF3; report.row_cells fitted by the shared ui.columns, CVAR_COLUMNS), each as wide as the file's widest cell up to a cap, cut with … to fit
the tree pane (columns dropped when even the minimums don't fit; fitted again when the window is resized), the
state and category in their theme colours. A file that can't be read is read-only: greyed, never ticked or
written, and listed in the warnings view (`!`).

The left pane has the search (the shared filter box: a CVar's name, Blizzard's help and our note, or its file's
group), the category select and the Changed only / Show all known boxes (CE6), the staged line and Apply / Dry run /
Rescan / Undo last change. Ticks pick files: Set, Remove and Reset act on the highlighted CVar in every ticked file
and Add puts a CVar into each (edit_actions.py); with none ticked they act on the highlighted file. Space on a CVar
whose value is 0 or 1 toggles it; on a file or a group it ticks. The help panel shows the highlighted CVar's
details (CE4), under the tree, or beside it from 160 columns. Staged CVars are marked ✎ before their line and
nothing is written until Apply, which runs every staged change across files and flavors as one run of the shared
client-file pipeline (RunActions: WoW check, confirm with the scope warnings, progress popup, result screen); one
Undo puts it all back. Leaving with staged changes asks first. Dismisses with "flavors", "tools" or "quit"."""
from __future__ import annotations

from collections.abc import Collection, Hashable, Iterable, Sequence
from pathlib import Path
from typing import ClassVar, NamedTuple

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Header, Label, ProgressBar, Select, Static, Tree
from textual.widgets.tree import TreeNode

from wowtools.core.config import Config
from wowtools.core.events import log_event, log_exception
from wowtools.core.install import Account, Character, Flavor, flavor_name
from wowtools.core.kb import CvarInfo, Recommendation, load_cvars, load_recommendations
from wowtools.core.process import wow_check_for
from wowtools.core.sv_apply import Marker, MultiApplyResult
from wowtools.core.text import plural
from wowtools.tools.config_editor.edit_actions import TREE_ACTIONS, ConfigEditActions
from wowtools.tools.config_editor.events import SV_TOOL
from wowtools.tools.config_editor.journal import latest_undoable, read_journal, resolve_journal_dir
from wowtools.tools.config_editor.model import CATEGORIES, CONFIG_CACHE, CONFIG_WTF, ConfigTarget, Row
from wowtools.tools.config_editor.ops import ConfigStaged, build_changes, rows
from wowtools.tools.config_editor.report import (ACCOUNT_CONFIG, COLUMN_CAPS, COLUMN_MINIMUMS, DROP_ORDER,
                                                 FILE_COLUMNS, STAGE_TITLES, STATUS_COLOURS, HelpPanel, UNDO_COLUMNS,
                                                 apply_confirm, apply_groups, file_label, file_rows, help_panel,
                                                 recovery_text, row_cells, scope_listed, summary_rows, undo_confirm,
                                                 undo_detail_rows, undo_summary_rows)
from wowtools.tools.config_editor.runner import ApplyError, run_apply
from wowtools.tools.config_editor.scanner import scan_targets
from wowtools.tools.config_editor.settings import load_settings, resolve_root
from wowtools.tools.config_editor.undo import (UndoError, UndoResult, leave, pending_recovery, recover, undo_flavors,
                                               undo_run)
from wowtools.ui.branding import BottomBar
from wowtools.ui.character_tree import CharacterNode, character_label, node_keys, populate_characters
from wowtools.ui.columns import ColumnLayout, column_text, fit_columns, natural_widths
from wowtools.ui.dialogs import (ACCENT, REVIEW_HINT, TREE_BINDINGS, TREE_HINT, ConfirmScreen, ProgressScreen,
                                 UnfinishedRunScreen, relabel_branch, theme_colour, two_pane_css)
from wowtools.ui.result_screen import ResultScreen
from wowtools.ui.review import ActionBar, BarTree, ReviewBase, RunActions, SvRecoveryActions, TickModel, WowCheck
from wowtools.ui.theme import CVAR_CATEGORY_COLOURS, CVAR_STATE_COLOURS
from wowtools.ui.tree_filter import FILTER_BINDINGS, FILTER_HINT, FilterBar, TreeFilter
from wowtools.ui.warnings_view import WARNINGS_BINDING, SummaryBar, SummaryLine, WarningItem, WarningsHost, where_text
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, NavSelect, RiskBanner, action_button

TITLE = "Config Editor"
NAV_HINT = (REVIEW_HINT + "Space on a 0/1 CVar toggle · a all · n none · " + FILTER_HINT + TREE_HINT
            + "f flavors · t tools")
READ_ONLY = "read-only"
NO_FILE = "no file"
NO_MARK = "  "
MARK_WIDTH = 4  # NO_MARK and the staged mark (or two spaces) in front of a CVar's columns
# The CVar row's five columns as the shared fit takes them (CF2, FB2r): the name, value and default capped and cut
# (the value and the default first, then the name), the state and category never cut, only dropped (DROP_ORDER).
CVAR_COLUMNS = ColumnLayout(caps=(*COLUMN_CAPS, None, None), minimums=(*COLUMN_MINIMUMS, 0, 0),
                            shrink=((1, 2), (0,)), drop=DROP_ORDER)
STAGED_MARK = "✎"  # a CVar with a staged change, before its line (the Saved Variables Browser's symbol, D12)
WIDE = 160  # from this many columns the help panel sits beside the tree
GROUP_HELP = "Open a file to see its CVars; highlight one for its help. Space ticks files: Set, Remove, Reset and " \
             "Add then act on every ticked file."


def help_panel_text(panel: HelpPanel, warning: str) -> Text:
    """The help panel as Rich Text (CF5): the title bold, a blank line before each section, each label bold and its
    text in normal weight, the state and the category in their row colours (CF3), a warning in bold `warning`, a
    source as a `•` bullet."""
    text = Text()
    text.append(panel.title, style="bold")
    for section in panel.sections:
        text.append("\n")
        for line in section:
            text.append("\n")
            if line.bullet:
                text.append("  • ")
            if line.label:
                text.append(f"{line.label}:", style="bold")
                if line.text or line.tail:
                    text.append(" ")
            style = {"state": CVAR_STATE_COLOURS.get(line.text, ""),
                     "category": CVAR_CATEGORY_COLOURS.get(line.text, ""),
                     "warning": f"bold {warning}"}.get(line.kind, "")
            text.append(line.text, style=style)
            text.append(line.tail)
    return text


class FileKey(NamedTuple):
    """The tick key of a file: Set, Remove, Reset and Add act on the ticked files."""
    path: Path


class FileNode(NamedTuple):
    """The data of the Config.wtf line and of an account's "Account config" line (a character's file is its
    CharacterNode): the file and the tick keys under it."""
    kind: str
    target: ConfigTarget
    keys: tuple[Hashable, ...]


class CvarNode(NamedTuple):
    """The data of a CVar's line: its file and its row (as staged)."""
    kind: str
    target: ConfigTarget
    row: Row


class ConfigProgressScreen(ProgressScreen):
    """Shown while an Apply, a dry run, an Undo or a recovery runs: one row per flavor."""

    ID_PREFIX = "cvar"
    STAGE_TITLES: ClassVar[dict[str, str]] = STAGE_TITLES
    SIMULATED_STAGE = "check"

    def __init__(self, title: str, *, dry_run: bool = False, first_stage: str = "",
                 flavors: Sequence[Flavor] = (), parallelism: int = 1) -> None:
        super().__init__(title, dry_run=dry_run, first_stage=first_stage, units=flavors, parallelism=parallelism,
                         label=lambda flavor: flavor.display_name)


class ConfigResultScreen(ResultScreen):
    """`title` is "Apply", "Dry run" or "Undo". With `back` (a dry run: nothing was written, the staged changes are
    still there) it opens on "Back to review", and Esc dismisses with "back"."""

    LOG_SCREEN = "cvar_result"
    STATUS_COLOURS: ClassVar = STATUS_COLOURS

    def __init__(self, title: str, summary: list[tuple[str, str]], columns: tuple[str, ...], detail: list[tuple],
                 scope_label: str, *, back: bool = False) -> None:
        super().__init__(f"{TITLE} · {scope_label} · {title} result", summary, columns, detail, back=back)
        self.title_text = title


class ConfigReviewScreen(WarningsHost, ConfigEditActions, TreeFilter, SvRecoveryActions, RunActions, ReviewBase,
                         Screen[str]):
    """The CVar files of `flavors` (the flavor picked, or all of them). `wow_check` (tests inject one) stands for the
    running-WoW check; `kb_root` (tests) is the knowledge base folder (None: the one shipped in wowtools/kb)."""

    WARNINGS_TITLE = "Warnings"
    WARNINGS_NOUN = "warning"
    SV_TOOL = SV_TOOL  # RunActions: cvar.wow_running, the cvar.apply / undo / recover error contexts
    RUN_PROGRESS = ConfigProgressScreen  # SvRecoveryActions: the progress popup of a recovery
    TREE_SELECTOR = "#cvars"
    LOG_SCREEN = "cvar_review"
    HIDDEN_NOUN = "file"
    PREFLIGHT_TEXT = "Checking whether WoW is running…"
    HORIZONTAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] = [(0, "-narrow"), (WIDE, "-wide")]
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {
        "btn-apply": "apply", "btn-dry-run": "dry_run", "btn-rescan": "rescan", "btn-undo": "undo",
        **{button_id: name for button_id, _, _, name, _ in TREE_ACTIONS}}
    DEFAULT_CSS = two_pane_css("ConfigReviewScreen", "#cvars") + """
    ConfigReviewScreen #pending { height: auto; margin-top: 1; }
    ConfigReviewScreen #main { width: 1fr; }
    ConfigReviewScreen #tree-pane { width: 2fr; }
    ConfigReviewScreen #cvars { height: 1fr; }
    ConfigReviewScreen #cvar-help { height: 40%; min-height: 5; padding: 0 1; border-top: solid $accent 40%; }
    ConfigReviewScreen #side-help { width: 1fr; padding: 0 1; border-left: solid $accent 40%; display: none; }
    ConfigReviewScreen #tree-actions { padding: 0 1; }
    ConfigReviewScreen #category { margin-top: 1; }
    ConfigReviewScreen.-wide #cvar-help { display: none; }
    ConfigReviewScreen.-wide #side-help { display: block; }
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
                 wow_check: WowCheck | None = None, kb_root: Path | None = None) -> None:
        super().__init__()
        self.cfg = cfg  # the suite config (WoW folder)
        self.tool_cfg = tool_cfg  # config/config-editor.cfg
        self.flavors = list(flavors)
        self.scope_label = scope_label
        self._injected_check = wow_check
        self.kb_root = kb_root
        self.wow_root = cfg.wow_path  # the WoW folder these flavors were read from (see wow_folder_changed)
        self._leaving_for_new_folder = False
        self.targets: dict[Path, ConfigTarget] = {}  # every file of every flavor, from the last scan, in scan order
        self.cvars: dict[str, dict[str, CvarInfo]] = {}  # by flavor folder
        self.recommendations: dict[str, list[Recommendation]] = {}  # by flavor folder
        self.scanned = False
        self.scan_warnings: list[WarningItem] = []
        self.staged = ConfigStaged()
        self.ticked: set[Hashable] = set()
        self.category: str | None = None
        self.changed_only = False
        self.show_all = False
        self.undoable: Path | None = None
        self.marker: Marker | None = None
        self.marker_root: Path | None = None
        self._offer_on_resume = False
        self.summary_text = ""
        self._stale = False  # an Apply or Undo changed the files: read them again when the review is shown
        self._keep_open: set[Hashable] = set()  # the files a rebuild opens again (their rows are loaded at once)
        # CF1, CF2: per file, its rows' widest cells (the natural column widths) and the tree guides' width in
        # front of its rows; the tree width the rows were last fitted to
        self._columns: dict[Path, tuple[int, ...]] = {}
        self._indents: dict[Path, int] = {}
        self._fitted_width: int | None = None

    # --- layout ------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield RiskBanner()
                yield FilterBar()
                yield Label("Show", classes="section")
                yield NavSelect([(name.capitalize(), name) for name in CATEGORIES], prompt="All categories",
                                id="category", compact=True)
                yield Ka0sCheckbox("Changed only", False, id="changed-only", compact=True)
                yield Ka0sCheckbox("Show all known", False, id="show-all", compact=True)
                yield Static(self._pending_line(), id="pending")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Apply", "destructive", "w", id="btn-apply")
                    yield action_button("Dry run", "simulate", "y", id="btn-dry-run")
                    yield action_button("Rescan", "refresh", "r", id="btn-rescan")
                    yield action_button("Undo last change", "revert", "z", id="btn-undo")
                yield NavHint(NAV_HINT)
            with Horizontal(id="main"):
                with Vertical(id="tree-pane"):
                    with Vertical(id="scan-box"):
                        yield ProgressBar(id="scan-progress", show_eta=False)
                        yield Static("", id="scan-label")
                    yield BarTree(Text(self.scope_label, style=ACCENT), id="cvars")
                    with VerticalScroll(id="cvar-help", can_focus=False):
                        yield Static("", id="cvar-help-text")
                    with ActionBar(id="tree-actions"):
                        for button_id, label, kind, _, key in TREE_ACTIONS:
                            yield action_button(label, kind, key, id=button_id, compact=True)
                with VerticalScroll(id="side-help", can_focus=False):
                    yield Static("", id="side-help-text")
        yield SummaryBar(Text(self.summary_text))
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = f"{TITLE} · {self.scope_label}"
        self.query_one("#scan-box").display = False
        self.query_one("#cvars", Tree).focus()
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

    def all_targets(self) -> list[ConfigTarget]:
        return list(self.targets.values())

    def cvars_for(self, folder: str) -> dict[str, CvarInfo]:
        return self.cvars.get(folder, {})

    def recommendations_for(self, folder: str) -> list[Recommendation]:
        return self.recommendations.get(folder, [])

    def character_target(self, character: Character) -> ConfigTarget | None:
        return self.targets.get(character.path / CONFIG_CACHE)

    def _refresh_buttons(self) -> None:
        if not self.is_attached:
            return
        idle = self.idle
        self.query_one("#btn-apply", Button).disabled = not idle or not self.pending
        self.query_one("#btn-dry-run", Button).disabled = not idle or not self.pending
        self.query_one("#btn-rescan", Button).disabled = not idle
        self.query_one("#btn-undo", Button).disabled = not idle or self.undoable is None
        target = self.highlighted_target()
        row = self.highlighted_row()
        writable = target is not None and not target.read_only
        self.query_one("#act-set", Button).disabled = not idle or row is None or row[0].read_only
        self.query_one("#act-add", Button).disabled = not idle or not (writable or self.ticked_targets())
        self.query_one("#act-remove", Button).disabled = not idle or row is None or row[0].read_only
        self.query_one("#act-reset", Button).disabled = not idle or row is None or row[0].read_only
        self.query_one("#act-recommend", Button).disabled = not idle or not writable
        for box in self.query(Ka0sCheckbox).results(Ka0sCheckbox):
            box.disabled = not idle
        self.query_one("#category", Select).disabled = not idle

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
        self.show_scan_box(True, f"Reading the CVar files of {self.scope_label}")
        self._refresh_buttons()
        root = resolve_root(load_settings(self.tool_cfg), self.cfg.wow_path)
        journal_dir = resolve_journal_dir(self.cfg.wow_path)
        flavors = list(self.flavors)
        self.run_worker(lambda: self._scan_worker(flavors, root, journal_dir), thread=True, exclusive=True,
                        group="scan")

    def _scan_worker(self, flavors: list[Flavor], root: Path | None, journal_dir: Path | None) -> None:
        warnings: list[WarningItem] = []
        targets: list[ConfigTarget] = []
        cvars: dict[str, dict[str, CvarInfo]] = {}
        recommendations: dict[str, list[Recommendation]] = {}
        try:
            for flavor in flavors:
                def on_error(path: Path, exc: OSError, flavor: Flavor = flavor) -> None:
                    warnings.append(WarningItem(where_text(path, flavor.path), exc.strerror or str(exc),
                                                flavor.display_name))
                targets += scan_targets(flavor, on_error)
                cvars[flavor.folder] = load_cvars(flavor.folder, root=self.kb_root)
                recommendations[flavor.folder] = load_recommendations(flavor.folder, root=self.kb_root)
            undoable = latest_undoable(journal_dir)
            marker = pending_recovery(root)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never a crash
            log_exception("cvar.scan", exc)
            self.app.call_from_thread(self._scan_failed, f"The scan failed: {exc}")
            return
        for target in targets:
            if target.read_only:
                warnings.append(WarningItem(where_text(target.path, target.flavor.path),
                                            f"{READ_ONLY}: {target.problem}", target.flavor.display_name))
        self.app.call_from_thread(self._scanned, targets, cvars, recommendations, warnings, undoable, marker, root)

    def _scan_failed(self, message: str) -> None:
        self._scanning = False
        if not self.is_attached:
            return
        self.show_scan_box(False)
        self.summary_text = message
        self.query_one("#summary", SummaryLine).show_one_line(message)
        self.notify(message, title="Scan failed", severity="error", timeout=15)
        self._refresh_buttons()

    def _scanned(self, targets: list[ConfigTarget], cvars: dict[str, dict[str, CvarInfo]],
                 recommendations: dict[str, list[Recommendation]], warnings: list[WarningItem],
                 undoable: Path | None, marker: Marker | None, marker_root: Path | None) -> None:
        self._scanning = False
        self.targets = {target.path: target for target in targets}
        self.cvars, self.recommendations = cvars, recommendations
        for path in [p for p in (*self.staged.sets, *self.staged.removes) if p not in self.targets]:
            self.staged.sets.pop(path, None)  # a file gone since (a character folder removed)
            self.staged.removes.pop(path, None)
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
        self.query_one("#cvars", Tree).focus()
        if marker is not None:
            if self.app.screen is self:
                self.offer_recovery(marker)
            else:
                self._offer_on_resume = True

    def staging_changed(self) -> None:
        """After a set, toggle, add, remove, reset or recommendation: the tree is built again."""
        self._schedule_rebuild()
        self._update_summary()

    # --- filters -----------------------------------------------------------------------------------
    def group_texts(self, target: ConfigTarget) -> tuple[str, ...]:
        """What a file and its CVars are matched on as a group: game version, Config.wtf or account, Account
        config or realm and character."""
        flavor = target.flavor.display_name
        if target.level == "machine" or target.account is None:
            return flavor, CONFIG_WTF
        if target.character is None:
            return flavor, target.account.name, ACCOUNT_CONFIG
        return flavor, target.account.name, target.character.realm, target.character.name

    def row_matches(self, row: Row) -> bool:
        texts = [row.name] if row.info is None else [row.name, row.info.help, row.info.description]
        return self.text_filter.matches(*texts)

    def rows_for(self, target: ConfigTarget) -> list[Row]:
        """The file's CVar rows as the filters show them (CE6): category, changed only, show all known and, unless
        the file's group matches the search, only the CVars it matches."""
        found = rows(target, self.cvars_for(target.flavor.folder), show_all_known=self.show_all,
                     category=self.category, changed_only=self.changed_only, search="", staged=self.staged)
        if not self.filtering or self.text_filter.path_matches(self.group_texts(target)):
            return found
        return [row for row in found if self.row_matches(row)]

    def target_shown(self, target: ConfigTarget | None) -> bool:
        if target is None or not self.filtering:
            return True
        return self.text_filter.path_matches(self.group_texts(target)) or bool(self.rows_for(target))

    def filter_texts(self, key) -> tuple[str, ...]:
        target = self.targets.get(key.path)
        return self.group_texts(target) if target is not None else ()

    def filter_keys(self, keys: Collection[Hashable]) -> Collection[Hashable]:
        """A file shows when its group or one of its CVars matches the search."""
        if not self.filtering:
            return keys
        return [key for key in keys if self.targets.get(key.path) is not None
                and self.target_shown(self.targets[key.path])]

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "category":
            return
        event.stop()
        value = event.value
        self.category = value if isinstance(value, str) and value in CATEGORIES else None
        log_event("ui.selection", screen=self.LOG_SCREEN, control="category", value=self.category or "all")
        if self.scanned:
            self._schedule_rebuild()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        names = {"changed-only": "changed_only", "show-all": "show_all"}
        attribute = names.get(event.checkbox.id or "")
        if attribute is None:
            return
        event.stop()
        setattr(self, attribute, event.value)
        log_event("ui.selection", screen=self.LOG_SCREEN, control=attribute, value=event.value)
        if self.scanned:
            self._schedule_rebuild()

    # --- the tree ------------------------------------------------------------------------------
    def mark(self, keys: Iterable[Hashable]) -> tuple[str, str]:
        keys = list(keys)
        return self.shown_tick_mark(keys) if keys else (NO_MARK, "")

    def all_tick_keys(self) -> list[Hashable]:
        """Every file that can be written (read-only ones have none)."""
        return [FileKey(path) for path, target in self.targets.items() if not target.read_only]

    def _character_key(self, character: Character) -> FileKey:
        return FileKey(character.path / CONFIG_CACHE)

    def _file_note(self, target: ConfigTarget | None) -> str:
        if target is None:
            return ""
        notes = []
        touched = len(self.staged.sets.get(target.path, {})) + len(self.staged.removes.get(target.path, ()))
        if touched:
            notes.append(f"{STAGED_MARK} {touched}")
        if not target.exists and not target.read_only:
            notes.append(NO_FILE)
        return ("  " + "  ".join(notes)) if notes else ""

    def _character_label(self, character: Character) -> str:
        return character.name + self._file_note(self.character_target(character))

    def _disabled(self, character: Character) -> str | None:
        target = self.character_target(character)
        return READ_ONLY if target is not None and target.read_only else None

    def _attach_rows(self, target: ConfigTarget, node: TreeNode, ident: Hashable) -> None:
        """A file's CVar rows: added now when the search opens it or a rebuild keeps it open, else when it is
        opened (on_tree_node_expanded)."""
        found = self.rows_for(target)
        if not found:
            return
        if (self.filtering and not self.text_filter.path_matches(self.group_texts(target))) or \
                ident in self._keep_open:
            self._add_rows(target, node, found)
            node.expand()

    def _add_rows(self, target: ConfigTarget, node: TreeNode, found: list[Row] | None = None) -> None:
        found = self.rows_for(target) if found is None else found
        self._columns[target.path] = natural_widths(map(row_cells, found))
        depth, parent = 0, node
        while parent is not None:
            depth, parent = depth + 1, parent.parent
        self._indents[target.path] = depth * node.tree.guide_depth  # the guides in front of a row (show_root)
        for row in found:
            data = CvarNode("cvar", target, row)
            node.add_leaf(self._cvar_label(data), data=data)

    def _character_extra(self, character: Character, node: TreeNode) -> list[Hashable] | None:
        target = self.character_target(character)
        if target is not None:
            self._lazy.append((node, target))
        return None

    def _account_extra(self, account: Account, node: TreeNode) -> list[Hashable] | None:
        target = self.targets.get(account.path / CONFIG_CACHE)
        if target is None or not self.target_shown(target):
            return None
        return list(self._add_file(node, target))

    def _add_file(self, parent: TreeNode, target: ConfigTarget) -> tuple[Hashable, ...]:
        """A Config.wtf or Account config line under `parent`; returns its tick keys."""
        keys = () if target.read_only else (FileKey(target.path),)
        data = FileNode("file", target, keys)
        node = parent.add(self._label(data), data=data, allow_expand=False)
        self._lazy.append((node, target))
        return keys

    def _shown(self):
        if not self.filtering:
            return None
        return lambda c: self.target_shown(self.character_target(c))

    def _rebuild(self) -> None:
        tree = self.query_one("#cvars", Tree)
        cursor = tree.cursor_node.data if tree.cursor_node is not None else None
        self._keep_open = self._opened(tree)
        tree.clear()
        many = len(self.flavors) > 1
        for flavor in self.flavors:
            parent = tree.root.add(Text(flavor.display_name), data=["flavor", flavor.folder, ()],
                                   expand=True) if many else tree.root
            self._lazy: list[tuple[TreeNode, ConfigTarget]] = []
            keys: list[Hashable] = []
            if self.scanned:
                machine = self.targets.get(flavor.wtf_dir / CONFIG_WTF)
                if machine is not None and self.target_shown(machine):
                    keys += self._add_file(parent, machine)
            keys += populate_characters(parent, flavor, key=self._character_key, label=self._character_label,
                                        disabled=self._disabled,
                                        account_extra=self._account_extra if self.scanned else None,
                                        character_extra=self._character_extra if self.scanned else None,
                                        shown=self._shown(), mark=self.mark)
            for node, target in self._lazy:
                node.allow_expand = bool(self.rows_for(target))
                self._attach_rows(target, node, self._node_ident(node.data))
            if many:
                if self.filtering and not parent.children:
                    parent.remove()
                    continue
                parent.data = ["flavor", flavor.folder, tuple(keys)]
                parent.set_label(self._label(parent.data))
        self.note_no_match(tree.root)
        tree.root.expand()
        self._restore_cursor(tree, cursor)
        self._update_summary()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        target = self._node_target(node.data)
        if target is not None and not node.children and node.allow_expand:
            self._add_rows(target, node)

    def _node_target(self, data) -> ConfigTarget | None:
        if isinstance(data, (FileNode, CvarNode)):
            return data.target
        if isinstance(data, CharacterNode) and data.kind == "character" and data.character is not None:
            return self.character_target(data.character)
        return None

    @staticmethod
    def _node_ident(data) -> Hashable | None:
        if isinstance(data, FileNode):
            return ("file", data.target.path)
        if isinstance(data, CvarNode):
            return ("cvar", data.target.path, data.row.name.casefold())
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
        """The files the user opened (kept open across a rebuild)."""
        return {self._node_ident(n.data) for n in self._walk(tree)
                if n.is_expanded and (isinstance(n.data, FileNode) or
                                      (isinstance(n.data, CharacterNode) and n.data.kind == "character"))}

    def _restore_cursor(self, tree: Tree, data) -> None:
        wanted = self._node_ident(data)
        if wanted is None:
            return
        for node in self._walk(tree):
            if self._node_ident(node.data) == wanted:
                self.call_after_refresh(lambda n=node: tree.move_cursor(n) if n.tree is tree else None)
                return

    def _row_room(self, path: Path) -> int | None:
        """The cells a row of the file may take in the tree pane (None before the tree is laid out)."""
        tree = self.query_one("#cvars", Tree)
        width = tree.size.width - tree.styles.scrollbar_size_vertical  # a scrollbar may come with more rows
        if tree.size.width <= 0:
            return None
        return max(0, width - self._indents.get(path, 0) - MARK_WIDTH)

    def _cvar_label(self, data: CvarNode) -> Text:
        """The staged mark, then the five columns (CF1-CF3): name, value and default (a CVar not set dim, an
        unknown one italic; the default always dim), cut with … to the file's column widths as they fit the pane
        (the name in its middle), the state and category in their colours; a column the pane has no room for is
        left out (fit_columns)."""
        row = data.row
        cells = row_cells(row)
        natural = self._columns.get(data.target.path) or tuple(map(cell_len, cells))
        widths, gap = fit_columns(natural, self._row_room(data.target.path), CVAR_COLUMNS)
        style = "dim" if row.value is None or data.target.read_only else ""
        if row.info is None:
            style = f"{style} italic".strip()
        state, category = cells[3], cells[4]
        styles = (style, style, "dim", CVAR_STATE_COLOURS[state], CVAR_CATEGORY_COLOURS.get(category, ""))
        text = Text.assemble((NO_MARK, ""), (f"{STAGED_MARK} ", f"bold {theme_colour(self.app, 'warning')}")
                             if row.staged else ("  ", ""))
        text.append_text(column_text(cells, widths, styles, gap, middle=(0,)))
        return text

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._fit_rows)

    def _fit_rows(self) -> None:
        """Fit the CVar rows again to the tree pane's new width (CF2)."""
        if not self.is_attached:
            return
        tree = self.query_one("#cvars", Tree)
        if tree.size.width == self._fitted_width:
            return
        self._fitted_width = tree.size.width
        for node in self._walk(tree):
            if isinstance(node.data, CvarNode):
                node.set_label(self._cvar_label(node.data))

    def _label(self, data) -> Text:
        if isinstance(data, CvarNode):
            return self._cvar_label(data)
        if isinstance(data, FileNode):
            target = data.target
            if target.read_only:
                return Text.assemble((NO_MARK, ""), (file_label(target), "dim"), (f"  {READ_ONLY}", "dim italic"))
            return Text.assemble(self.mark(data.keys), (file_label(target), "bold"),
                                 (self._file_note(target), "dim"))
        if isinstance(data, CharacterNode):
            return character_label(data, self.mark)
        mark = self.mark(data[2]) if data[2] else (NO_MARK, "")
        return Text.assemble(mark, (flavor_name(data[1]), "bold"))

    def _refresh_labels(self, node: TreeNode | None = None) -> None:
        relabel_branch(self.query_one("#cvars", Tree), node, self._label)
        self._update_summary()

    # --- the highlighted node ------------------------------------------------------------------------
    def _cursor_data(self):
        if not self.is_attached:
            return None
        node = self.query_one("#cvars", Tree).cursor_node
        return None if node is None else node.data

    def highlighted_target(self) -> ConfigTarget | None:
        """The file of the highlighted line: a CVar's, Config.wtf, an Account config or a character's."""
        return self._node_target(self._cursor_data())

    def highlighted_row(self) -> tuple[ConfigTarget, Row] | None:
        data = self._cursor_data()
        if isinstance(data, CvarNode):
            return data.target, data.row
        return None

    def ticked_targets(self) -> list[ConfigTarget]:
        """The ticked files, in scan order (ticks the search hides included)."""
        return [t for t in self.targets.values() if FileKey(t.path) in self.ticked and not t.read_only]

    def picked_targets(self) -> list[ConfigTarget]:
        """What Add acts on: the ticked files, else the highlighted one."""
        ticked = self.ticked_targets()
        if ticked:
            return ticked
        target = self.highlighted_target()
        return [target] if target is not None else []

    def space_on_node(self, node) -> bool:
        """Space on a CVar row switches it when it is 0 or 1 (CE5); anywhere else it ticks."""
        if isinstance(node.data, CvarNode):
            self.toggle_cvar()
            return True
        return False

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.control.id == "cvars":
            self._update_summary()

    # --- the help panel ----------------------------------------------------------------------------
    def _nothing_shown(self) -> bool:
        """True when the search leaves the tree empty (it shows only NO_MATCH_TEXT)."""
        if not self.filtering:
            return False
        return not any(node.data is not None for node in self.query_one("#cvars", Tree).root.children)

    def narrowed_help(self) -> str:
        """Why the tree is empty (CF4a): the search and the Show choices narrow it together, so a search applied
        earlier still applies when a category is picked. Names each and how to clear it."""
        shown = []
        if self.category is not None:
            shown.append(f"in the {self.category.capitalize()} category")
        if self.changed_only:
            shown.append("with Changed only ticked")
        lines = [" ".join([f'Nothing matches the search "{self.text_filter.text.strip()}"', *shown]) + "."]
        if shown:
            lines.append("The search and the Show choices narrow the list together.")
        lines.append("Esc in the filter box clears the search" + ("; All categories shows every category"
                                                                  if self.category is not None else "") + ".")
        if not self.show_all:
            lines.append("Show all known adds the CVars the files don't set.")
        return "\n".join(lines)

    def help_text(self) -> Text:
        """The help panel's Text: the highlighted CVar's or file's panel (CF5), else the hint or why nothing shows."""
        data = self._cursor_data()
        target = self._node_target(data)
        if target is None:
            if self.scanned and self._nothing_shown():
                return Text(self.narrowed_help())
            return Text(GROUP_HELP if self.scanned else "")
        folder = target.flavor.folder
        row = data.row if isinstance(data, CvarNode) else None
        rec = None
        if row is not None:
            rec = next((r for r in self.recommendations_for(folder) if r.cvar.casefold() == row.name.casefold()),
                       None)
        panel = help_panel(target, row, recommendation=rec, has_data=bool(self.cvars_for(folder)))
        return help_panel_text(panel, theme_colour(self.app, "warning"))

    def _update_help(self) -> None:
        text = self.help_text()
        self.query_one("#cvar-help-text", Static).update(text)
        self.query_one("#side-help-text", Static).update(text)

    # --- summaries -------------------------------------------------------------------------------
    def warning_items(self) -> list[WarningItem]:
        return list(self.scan_warnings)

    def _pending_words(self) -> str:
        return plural(self.pending, "staged edit")

    def _pending_line(self) -> Text:
        """`Staged: N edits in F files` (what Apply writes)."""
        files = len({*self.staged.sets, *self.staged.removes})
        return Text.assemble(("Staged: ", "bold"), f"{plural(self.pending, 'edit')} in {plural(files, 'file')}")

    def _where(self, node: TreeNode | None) -> str:
        names = []
        while node is not None and node.data is not None:
            data = node.data
            if isinstance(data, CvarNode):
                names.append(data.row.name)
            elif isinstance(data, FileNode):
                names.append(file_label(data.target))
            elif isinstance(data, CharacterNode):
                names.append(data.character.name if data.character is not None else data.text)
            else:
                names.append(flavor_name(data[1]))
            node = node.parent
        return " › ".join(reversed(names)) or self.scope_label

    def _update_summary(self) -> None:
        if not self.is_attached or not self.scanned:
            return
        tree = self.query_one("#cvars", Tree)
        self.summary_text = (f"Selected: {self._where(tree.cursor_node)}    Ticked: "
                             f"{plural(len(self.ticked_targets()), 'file')}")
        hidden = self.hidden_ticked_note()
        if hidden:
            self.summary_text += f"    {hidden}"
        self.query_one("#summary", Static).update(Text(self.summary_text))
        self.query_one("#pending", Static).update(self._pending_line())
        self._update_help()
        self.refresh_warnings()
        self._refresh_buttons()

    # --- ticks -----------------------------------------------------------------------------------
    def tick_model(self) -> TickModel:
        return TickModel.of_ticked(self.ticked)

    def node_tick_keys(self, node) -> tuple[Hashable, ...]:
        data = node.data
        if isinstance(data, FileNode):
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

    def _staged_flavors(self) -> list[str]:
        return [self.targets[path].flavor.folder for path in {*self.staged.sets, *self.staged.removes}
                if path in self.targets]

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
        check = self.check_for(self._staged_flavors())
        self._check_wow(check, lambda running: self._after_apply_preflight(check, running))

    def _after_apply_preflight(self, check: WowCheck, running: list[str] | None) -> None:
        alerts: list[str] = []
        if not self._refused_while_running(running, alerts):
            self._show_confirm(False, alerts, check)

    def _show_confirm(self, dry_run: bool, extra: list[str], check: WowCheck | None = None) -> None:
        targets = self.all_targets()
        title, body, alerts = apply_confirm(self.staged, targets, dry_run=dry_run)
        self.app.push_screen(ConfirmScreen(title, body, (*extra, *alerts), kind="simulate" if dry_run else "destructive",
                                           groups=apply_groups(self.staged, targets),
                                           listed=scope_listed(self.staged, targets, self.cvars)),
                             lambda ok: self._apply_confirmed(ok, dry_run, check))

    def _apply_confirmed(self, ok: bool | None, dry_run: bool, check: WowCheck | None) -> None:
        log_event("ui.selection", screen="confirm", control="apply_confirm", value=bool(ok), dry_run=dry_run)
        wow_root = self.cfg.wow_path
        if not ok or wow_root is None or not self.idle:
            return
        root, journal_dir = resolve_root(load_settings(self.tool_cfg), wow_root), resolve_journal_dir(wow_root)
        if root is None or journal_dir is None:
            return
        targets = self.all_targets()
        staged = ConfigStaged({p: dict(v) for p, v in self.staged.sets.items()},
                              {p: set(v) for p, v in self.staged.removes.items()})
        flavors = list(dict.fromkeys(self.targets[change.path].flavor for change in build_changes(staged, targets)))
        screen = ConfigProgressScreen("Simulating the changes" if dry_run else "Applying the changes",
                                      dry_run=dry_run, flavors=flavors)
        keep_snapshots, keep_journals = self.cfg.keep_backups, self.cfg.keep_journals
        self.start_run(screen, lambda: run_apply(staged, targets, root=root, journal_dir=journal_dir,
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
        self.app.push_screen(ConfigResultScreen("Dry run" if result.dry_run else "Apply", summary_rows(result),
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
        screen = ConfigProgressScreen("Undoing the last change", first_stage="undo",
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
        self.app.push_screen(ConfigResultScreen("Undo", undo_summary_rows(result), UNDO_COLUMNS,
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
