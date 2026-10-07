"""The Saved Variables Browser's popups (spec §5), styled like ConfirmScreen (ui.dialogs.popup_css; its USE AT YOUR
OWN RISK warning, D2, is the shared ui.disclaimer popup): Edit value (D5, D10: a type select, then a text field or a
checkbox), Rename key (the shared text prompt) and Delete key (a destructive confirm, with D5's array-shift warning)
and Search (D6-D9, D38: the key and value texts, their modes, Match case and the scope; it only finds: Find checks
them with the search's own rules and dismisses with a SearchSpec). Edit value and Rename key also serve the bulk edit
of the search results (D39: titled with the count; Edit value then may offer "Replace only the matched text"). The
edit popups check what is typed with the checks they are given (the review passes the staging's own,
ops.Staging.*_problem) and dismiss with the value, the key text or the answer; the review stages it."""
from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from wowtools.core.svfiles import OWNER_ACCOUNT_WIDE
from wowtools.core.text import plural
from wowtools.tools.sv_browser.bulk import MATCHED, MODES, WHOLE
from wowtools.tools.sv_browser.ops import SHIFT_WARNING, parse_key
from wowtools.tools.sv_browser.search import (KEY_CONTAINS, KEY_EXACT, REPLACE_BOOLEAN, REPLACE_NUMBER,
                                              REPLACE_STRING, VALUE_CONTAINS, VALUE_WHOLE, Replacement, SearchScope,
                                              SearchSpec, parse_replacement)
from wowtools.ui.dialogs import ConfirmScreen, ProgressScreen, TextPromptScreen, popup_css, show_error
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, NavHint, NavSelect, action_button

VALUE_TYPES = ((REPLACE_STRING, "String"), (REPLACE_NUMBER, "Number"), (REPLACE_BOOLEAN, "Boolean"))
NOT_TYPABLE = "It has line breaks or other characters that can't be typed here: type the whole new value."
KEY_HELP = ("Type the new key. [5], [2.5], [true] or [false] make a number or boolean key; anything else is a "
            'string key (["[5]"] for the text [5]).')


class PopupCheckbox(Ka0sCheckbox):
    """A checkbox in a popup with OK or Find: Space ticks or unticks it, Enter falls through to the popup (its
    `enter` binding presses OK / Find, as the hint says), so Enter never flips the value."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("enter", "pass_enter", show=False)]

    def action_pass_enter(self) -> None:
        raise SkipAction()


class EditValueScreen(ModalScreen[Replacement | None]):
    """Edit value (D5, D10): `where` names the key (or the results, D39), `current` its value as the tree shows it
    ("" for many: no Now line). The type select (string, number, boolean; it starts on `kind`) shows a text field
    (#value-text, starting with `text`) for a string or a number, or a checkbox (#value-bool, ticked = true, starting
    as `flag`) for a boolean. With `matched` (a bulk edit after a value Contains search) a first select (#edit-mode)
    offers Replace only the matched text (the default: the text field only, put in place of every match) or Whole
    value; `mode` holds the choice once OK is pressed. OK reads the value (a number must read back in Lua as itself:
    search.parse_replacement) and asks `check` (the staging's refusal, or None; never for matched text); a problem
    shows under the fields until they change. Dismisses with the value, or None."""

    DEFAULT_CSS = popup_css("EditValueScreen", list_rows=len(VALUE_TYPES)) + """
    EditValueScreen Ka0sCheckbox { margin-top: 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"),
                                         Binding("enter", "submit", show=False), *NAV_BINDINGS]

    def __init__(self, where: str, current: str, kind: str = REPLACE_STRING, text: str = "", flag: bool = False,
                 check: Callable[[Replacement], str | None] | None = None, note: str = "", *,
                 title: str = "Edit value", matched: bool = False) -> None:
        super().__init__()
        self.title_text = title
        self.matched = matched
        self.mode = MATCHED if matched else WHOLE
        self.where = where
        self.current = current
        self.kind = kind
        self.text = text
        self.flag = flag
        self.check = check or (lambda value: None)
        self.note = note

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup-box"):
            yield Static(Text(self.title_text), classes="title")
            body = f"{self.where}\nNow: {self.current}" if self.current else self.where
            yield Static(Text(f"{body}\n{self.note}" if self.note else body), classes="popup-body")
            if self.matched:
                yield NavSelect([(label, mode) for mode, label in MODES], value=MATCHED, allow_blank=False,
                                id="edit-mode", compact=True)
            yield NavSelect([(label, kind) for kind, label in VALUE_TYPES], value=self.kind, allow_blank=False,
                            id="value-type", compact=True)
            yield Input(self.text, placeholder="new value", id="value-text", compact=True)
            yield PopupCheckbox("true", self.flag, id="value-bool", compact=True)
            yield Static("", id="value-error", classes="popup-error")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("Enter OK · ↑↓/Tab move · Enter/Space open the list · Space tick · ←→ buttons")

    def on_mount(self) -> None:
        self._show_fields()
        self.query_one("#value-bool" if self.chosen_kind() == REPLACE_BOOLEAN else "#value-text").focus()

    def chosen_mode(self) -> str:
        """MATCHED or WHOLE (WHOLE when the popup offers no choice)."""
        if not self.matched:
            return WHOLE
        value = self.query_one("#edit-mode", Select).value
        return value if value in (MATCHED, WHOLE) else MATCHED

    def chosen_kind(self) -> str:
        if self.chosen_mode() == MATCHED:
            return REPLACE_STRING  # the matched text is replaced by text
        value = self.query_one("#value-type", Select).value
        return value if isinstance(value, str) else REPLACE_STRING

    def _show_fields(self) -> None:
        boolean = self.chosen_kind() == REPLACE_BOOLEAN
        self.query_one("#value-type", Select).display = self.chosen_mode() == WHOLE
        text = self.query_one("#value-text", Input)
        text.display = not boolean
        text.placeholder = "text to put in place of each match" if self.chosen_mode() == MATCHED else "new value"
        self.query_one("#value-bool", Ka0sCheckbox).display = boolean

    def _error(self, problem: str | None) -> None:
        show_error(self.query_one("#value-error", Static), problem)

    def value(self) -> Replacement:
        """The value entered; ValueError (its message for the user) when it is not one."""
        kind = self.chosen_kind()
        if kind == REPLACE_BOOLEAN:
            return self.query_one("#value-bool", Ka0sCheckbox).value
        return parse_replacement(kind, self.query_one("#value-text", Input).value)

    def action_submit(self) -> None:
        """Enter where the focused control does not take it (the checkbox): OK."""
        self._ok()

    def _ok(self) -> None:
        try:
            value = self.value()
        except ValueError as exc:
            self._error(str(exc))
            return
        self.mode = self.chosen_mode()
        problem = None if self.mode == MATCHED else self.check(value)
        if problem is not None:
            self._error(problem)
            return
        self.dismiss(value)

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        self._show_fields()
        self._error(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._error(None)

    def on_checkbox_changed(self, event: Ka0sCheckbox.Changed) -> None:
        event.stop()
        self._error(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._ok()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self._ok()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def key_check(check: Callable[[object], str | None]) -> Callable[[str], str | None]:
    """The rename prompt's check: the typed text read as a key (ops.parse_key), then `check` (the staging's
    refusal: an empty key, one the table already holds, ...)."""
    def problem(text: str) -> str | None:
        try:
            key = parse_key(text)
        except ValueError as exc:
            return str(exc)
        return check(key)
    return problem


class RenameKeyScreen(TextPromptScreen):
    """Rename key (D5; D39 for the search results, titled with the count): the shared text prompt, starting with the
    key as ops.key_input writes it and checked with key_check(check). Dismisses with the text (ops.parse_key reads
    the key), or None."""

    def __init__(self, where: str, initial: str, check: Callable[[object], str | None], *,
                 title: str = "Rename key") -> None:
        super().__init__(title, f"{where}\n{KEY_HELP}", initial, key_check(check), placeholder="new key")


def delete_confirm(where: str, *, count: int | None = None, table: bool = False, positional: bool = False,
                   staged_inside: int = 0) -> ConfirmScreen:
    """Delete key (D5): a destructive confirm naming the key. A table says how many entries go with it (`count`,
    None when not read yet); an array entry carries the shift warning; edits staged inside it are dropped."""
    lines = [f"{where} is deleted when you apply."]
    if table:
        lines.append("It is a table: " + ("everything in it goes with it." if count is None else
                                          f"its {plural(count, 'entry', 'entries')} {'goes' if count == 1 else 'go'} with it."))
    if staged_inside:
        lines.append(f"The {plural(staged_inside, 'edit')} staged inside it {'is' if staged_inside == 1 else 'are'} "
                     "dropped.")
    alerts = (SHIFT_WARNING,) if positional else ()
    return ConfirmScreen("Delete key?", "\n".join(lines), alerts, kind="destructive")


KEY_MODES = ((KEY_EXACT, "Exact"), (KEY_CONTAINS, "Contains"))
VALUE_MODES = ((VALUE_WHOLE, "Whole value"), (VALUE_CONTAINS, "Contains"))
EVERY = ""  # a scope select's "every flavor / account / character"
SEARCH_LABEL_WIDTH = 13


class SearchScreen(ModalScreen[SearchSpec | None]):
    """Search (D6-D9, D38: it only finds), one control per row, each after its label: the key text and Exact /
    Contains, a blank row, the value text and Whole value / Contains, Match case, then the scope (Flavor, only when
    there are several; Account; Character, with Account-wide only; Addon file, text the file name contains). It
    starts with `last` (the previous search) or the defaults. Find (or Enter in a text field) builds the SearchSpec
    and checks it (SearchSpec.problems); a problem shows under the fields until one changes. Dismisses with the
    spec, or None. The box scrolls when the window is short (80x24): ↑/↓ move through the fields, each scrolled
    into view."""

    DEFAULT_CSS = popup_css("SearchScreen", list_rows=8) + f"""
    SearchScreen .search-row {{ height: 1; }}
    SearchScreen .search-row Select, SearchScreen .search-row Input {{ margin-top: 0; width: 1fr; }}
    SearchScreen .search-label {{ width: {SEARCH_LABEL_WIDTH}; color: $text-muted; }}
    SearchScreen .search-gap {{ margin-top: 1; }}
    SearchScreen #search-error {{ margin-top: 1; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"),
                                         Binding("enter", "submit", show=False), *NAV_BINDINGS]

    def __init__(self, *, flavors: list[tuple[str, str]] = (), accounts: list[str] = (),
                 characters: list[str] = (), last: SearchSpec | None = None) -> None:
        """flavors: (folder, name) of each flavor scanned (a Flavor select only when there are several);
        accounts: the account names; characters: the owner labels (`Realm/Name`)."""
        super().__init__()
        self.flavors = list(flavors)
        self.accounts = list(dict.fromkeys(accounts))
        self.characters = list(dict.fromkeys(characters))
        self.last = last or SearchSpec()

    def _row(self, label: str, widget, gap: bool = False) -> Horizontal:
        return Horizontal(Static(label, classes="search-label"), widget,
                          classes="search-row search-gap" if gap else "search-row")

    def _select(self, options, value, select_id: str) -> NavSelect:
        values = [v for _, v in options]
        return NavSelect([(Text(label), v) for label, v in options], value=value if value in values else values[0],
                         allow_blank=False, id=select_id, compact=True)

    def compose(self) -> ComposeResult:
        last = self.last
        scope = last.scope
        with Vertical(classes="popup-box"):
            yield Static(Text("Search"), classes="title")
            yield self._row("Key", Input(last.key, placeholder="key name (or leave empty)", id="search-key",
                                         compact=True))
            yield self._row("Key match", self._select([(label, v) for v, label in KEY_MODES], last.key_mode,
                                                      "key-mode"))
            yield self._row("Value", Input(last.value, placeholder="value (or leave empty)", id="search-value",
                                           compact=True), gap=True)
            yield self._row("Value match", self._select([(label, v) for v, label in VALUE_MODES], last.value_mode,
                                                        "value-mode"))
            yield self._row("", PopupCheckbox("Match case", last.match_case, id="match-case", compact=True))
            if len(self.flavors) > 1:
                yield self._row("Flavor", self._select([("Every flavor", EVERY), *((n, f) for f, n in self.flavors)],
                                                       scope.flavor or EVERY, "scope-flavor"), gap=True)
            yield self._row("Account", self._select([("Every account", EVERY), *((a, a) for a in self.accounts)],
                                                    scope.account or EVERY, "scope-account"),
                            gap=len(self.flavors) <= 1)
            yield self._row("Character", self._select(
                [("Every character and account-wide", EVERY), ("Account-wide only", OWNER_ACCOUNT_WIDE),
                 *((c, c) for c in self.characters)], scope.character or EVERY, "scope-character"))
            yield self._row("Addon file", Input(scope.addon, placeholder="any (the file name contains)",
                                                id="scope-addon", compact=True))
            yield Static("", id="search-error", classes="popup-error")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("Find", "confirm", id="find")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("Enter Find · ↑↓/Tab move · Enter/Space open a list · Space tick · ←→ buttons")

    def on_mount(self) -> None:
        self.query_one("#search-key", Input).focus()

    def _value(self, select_id: str) -> str:
        value = self.query_one(f"#{select_id}", Select).value
        return value if isinstance(value, str) else ""

    def _error(self, problem: str | None) -> None:
        show_error(self.query_one("#search-error", Static), problem)

    def spec(self) -> SearchSpec:
        """The search entered. Its problems are not checked here (SearchSpec.problems)."""
        flavor = self._value("scope-flavor") if self.query("#scope-flavor") else EVERY
        scope = SearchScope(flavor=flavor or None, account=self._value("scope-account") or None,
                            character=self._value("scope-character") or None,
                            addon=self.query_one("#scope-addon", Input).value.strip())
        return SearchSpec(key=self.query_one("#search-key", Input).value, key_mode=self._value("key-mode"),
                          value=self.query_one("#search-value", Input).value, value_mode=self._value("value-mode"),
                          match_case=self.query_one("#match-case", Ka0sCheckbox).value, scope=scope)

    def action_submit(self) -> None:
        """Enter where the focused control does not take it (a checkbox): Find."""
        self.action_find()

    def action_find(self) -> None:
        spec = self.spec()
        problems = spec.problems()
        if problems:
            self._error(" ".join(problems))
            return
        self.dismiss(spec)

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        self._error(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._error(None)

    def on_checkbox_changed(self, event: Ka0sCheckbox.Changed) -> None:
        event.stop()
        self._error(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_find()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "find":
            self.action_find()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SearchProgressScreen(ProgressScreen):
    """Shown while a search runs: one row, the files searched of those in scope, and the file last searched."""

    ID_PREFIX = "svb-search"
    STAGE_TITLES: ClassVar[dict[str, str]] = {"search": "Searching", "tables": "Reading"}
