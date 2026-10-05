"""The changelog (spec D3): every version in CHANGELOG.md on the left, newest first, and the highlighted version's
notes on the right. Opened with c from the tool menu; Esc or q goes back to it."""
from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Header, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from wowtools import __version__
from wowtools.core.changelog import Changelog, ChangelogEntry, load_changelog
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import TwoPaneFocus, two_pane_css
from wowtools.ui.theme import KA0S_THEME
from wowtools.ui.widgets import LIST_CURSOR_BACKGROUND, LIST_NAME_STYLE, NAV_BINDINGS, NavHint

VERSIONS_WIDTH = 36  # the left pane: a version, its date and the "current" mark on one row
CURRENT_MARK = "current"
YANKED_MARK = "yanked"
CHANGELOG_HINT = "↑↓ version · →/Tab notes · ← versions · Esc/q back"


def version_name(entry: ChangelogEntry) -> str:
    return entry.version if entry.unreleased else f"v{entry.version}"


def version_label(entry: ChangelogEntry, width: int, current: str = __version__) -> Text:
    """A version row: the version (v0.1.0, or Unreleased) padded to `width`, its date, "yanked" on a pulled
    release and "current" on the running version."""
    yanked = ("  " + YANKED_MARK, f"bold {KA0S_THEME.error}") if entry.yanked else ""
    mark = ("  " + CURRENT_MARK, f"bold {KA0S_THEME.success}") if entry.version == current else ""
    return Text.assemble((version_name(entry).ljust(width), LIST_NAME_STYLE), entry.date or "", yanked, mark)


def notes_title(entry: ChangelogEntry) -> str:
    title = f"{version_name(entry)} · {entry.date}" if entry.date else version_name(entry)
    return f"{title} · {YANKED_MARK}" if entry.yanked else title


class NotesScroll(VerticalScroll):
    """The notes pane: ↑/↓/PgUp/PgDn scroll it, ← goes back to the version list (instead of scrolling sideways)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("left", "screen.focus_filters", "Versions", show=False)]


class ChangelogScreen(TwoPaneFocus, Screen[None]):
    """The suite's two-pane look with an OptionList of versions (one per row) instead of filters, and the notes
    (Markdown) in a scrollable pane instead of a tree. `changelog` defaults to the install's CHANGELOG.md; when it
    has no entries the right pane says why (load_changelog has logged it)."""

    TREE_SELECTOR = "#notes"
    DEFAULT_CSS = two_pane_css("ChangelogScreen", "#notes", width=VERSIONS_WIDTH) + f"""
    ChangelogScreen #versions {{ height: auto; max-height: 1fr; margin: 1 0 0 0; border: tall $primary; }}
    ChangelogScreen #versions > .option-list--option-highlighted {{ background: {LIST_CURSOR_BACKGROUND}; }}
    ChangelogScreen #versions:focus > .option-list--option-highlighted {{ background: {LIST_CURSOR_BACKGROUND}; }}
    ChangelogScreen #notes-title {{ color: $accent; text-style: bold; margin: 1 0 0 1; }}
    ChangelogScreen #notes Markdown {{ margin: 0; padding: 0 1; }}
    ChangelogScreen #notes:focus {{ background-tint: $foreground 4%; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,q", "close", "Back"),
        Binding("left", "focus_filters", "Versions", show=False),
        Binding("right", "focus_tree", "Notes", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, changelog: Changelog | None = None, *, current: str = __version__) -> None:
        super().__init__()
        self.changelog = load_changelog() if changelog is None else changelog
        self.current = current
        self.entries = self.changelog.entries

    def compose(self) -> ComposeResult:
        # The released versions' names in one column, then their dates (Unreleased has no date to line up).
        width = max((len(version_name(entry)) for entry in self.entries if not entry.unreleased), default=0) + 2
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Static("Versions", classes="section")
                yield OptionList(*[Option(version_label(entry, width, self.current), id=entry.version)
                                   for entry in self.entries], id="versions")
                yield NavHint(CHANGELOG_HINT)
            with NotesScroll(id="notes"):
                yield Static("", id="notes-title")
                yield Markdown("", id="notes-text")
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = "Changelog"
        versions = self.query_one("#versions", OptionList)
        if not self.entries:
            versions.display = False
            self.query_one("#notes-title", Static).update("No changelog to show")
            self.query_one("#notes-text", Markdown).update(self.changelog.problem or "")
            self.query_one("#notes", NotesScroll).focus()
            return
        ids = [entry.version for entry in self.entries]
        versions.highlighted = ids.index(self.current) if self.current in ids else 0
        versions.focus()

    def first_filter(self) -> Widget | None:
        versions = self.query_one("#versions", OptionList)
        return versions if versions.display else None

    def action_focus_tree(self) -> None:
        notes = self.query_one("#notes", NotesScroll)
        if self.focused is not notes:
            notes.focus()

    @property
    def shown(self) -> ChangelogEntry | None:
        """The entry whose notes are on the right."""
        index = self.query_one("#versions", OptionList).highlighted
        return self.entries[index] if index is not None and self.entries else None

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        entry = self.entries[event.option_index]
        self.query_one("#notes-title", Static).update(notes_title(entry))
        self.query_one("#notes-text", Markdown).update(entry.body or "_No notes for this version._")
        self.query_one("#notes", NotesScroll).scroll_home(animate=False)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_focus_tree()  # Enter on a version: read its notes

    def action_close(self) -> None:
        self.dismiss(None)
