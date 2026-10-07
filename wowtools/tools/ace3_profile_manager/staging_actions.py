"""The Ace3 review's staging actions (F-007, decision R5), mixed into ProfileReviewScreen: delete, assign, rename,
copy, remove leftovers, only Default, everyone to Default, the quick actions menu (m) and discard. Each picks its
target from the ticks (else the highlighted node; Leftovers first ticks every leftover character shown), asks in a
popup, and stages the change on the review's Staging (ops.py): nothing is written until Apply. The screen supplies
`staging`, `ticked`, `idle`, wow_folder_changed(), selected_profiles() / selected_chars(), _tick_keys(),
_hidden_line(), refresh_view() and _refresh_labels()."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from textual.widgets import Tree

from wowtools.core.events import log_event
from wowtools.core.install import flavor_name
from wowtools.core.text import plural
from wowtools.tools.ace3_profile_manager.model import DEFAULT
from wowtools.tools.ace3_profile_manager.ops import DbKey, OpResult, Staging, valid_name
from wowtools.tools.ace3_profile_manager.popups import ActionsScreen, NameScreen, TargetScreen
from wowtools.tools.ace3_profile_manager.report import NO_PENDING, pending_text
from wowtools.ui.dialogs import ConfirmScreen, InfoScreen

__all__ = ["ProfileStagingActions"]


class ProfileStagingActions:
    """The action bar's staging actions (and their keys), on the review's pending changes."""

    staging: Staging | None
    ticked: set[tuple]

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
        body = "\n".join(["Delete these profiles and move their characters to the profile chosen below:", *lines,
                          *self._hidden_line("p", "profile")])

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
        body = "\n".join(["Move these characters to the profile chosen below:", *lines,
                          *self._hidden_line("c", "character")])

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
        """Tick every leftover character shown (as More… → "Tick all leftover characters" does), then ask to remove
        exactly the ticked leftovers (decision L1). No keeps the ticks."""
        if not self._ready():
            return
        assert self.staging is not None
        staging = self.staging
        if not self._tick_leftovers():
            return
        selection = {key: [c for c in chars if c in staging.state(key).leftovers]
                     for key, chars in self.selected_chars().items()}
        selection = {key: chars for key, chars in selection.items() if chars}
        groups = {self._addon_name(key): chars for key, chars in selection.items()}
        body = "These characters have no folder in WTF any more. Remove their entries from these addons:"

        def done(ok: bool | None) -> None:
            if ok and self.staging is not None:
                self._staged(self.staging.remove_leftovers(selection))
        hidden = self._hidden_line("c", "leftover character", lambda k: k[2] in staging.state(k[1]).leftovers)
        self.app.push_screen(ConfirmScreen("Remove leftover characters?", body, tuple(hidden), kind="destructive",
                                           groups=groups), done)

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

    def _shown_leftovers(self) -> set[tuple]:
        """The tick keys of the leftover characters the tree shows (the View, the Show boxes and the filter)."""
        assert self.staging is not None
        staging = self.staging
        visible = self._tick_keys(self.query_one("#profiles", Tree).root)
        return {k for k in visible if k[0] == "c" and k[2] in staging.state(k[1]).leftovers}

    def _tick_leftovers(self) -> bool:
        """Tick every leftover character shown; False (and a notice) when none is shown."""
        leftovers = self._shown_leftovers()
        if not leftovers:
            self.notify("No leftover characters are shown.")
            return False
        self.ticked.update(leftovers)
        log_event("ui.selection", screen="ace_review", control="tick_leftovers", value=len(leftovers))
        self._refresh_labels()
        return True

    def action_more(self) -> None:
        if not self._ready():
            return

        def done(choice: str | None) -> None:
            if choice is None or self.staging is None:
                return
            keys = {"discard": self.action_discard, "rename": self.action_rename, "copy": self.action_copy,
                    "blacklist": self.action_blacklist, "edit_blacklist": self.action_edit_blacklist,
                    "unlock": self.action_unlock, "switch_view": self.action_switch_view,
                    "filter": self.action_focus_filter, "tick_leftovers": self._tick_leftovers,
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
        for line in self._hidden_line():  # staged at once, no popup: said in a toast
            self.notify(line, severity="warning")
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
                                           "they are.", kind="destructive"), done)
