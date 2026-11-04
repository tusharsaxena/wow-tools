"""The Macro Editor browse screen's macro actions (config tools spec ME3-ME8), mixed into MacroReviewScreen: the bar
under the tree. New (on the highlighted set) and Edit (the highlighted macro) open the macro form; Delete asks
first, with the ME6 action bar warning; Copy takes the ticked macros (else the highlighted one) as they are staged;
Paste… pastes them into the ticked sets after the paste review (clashes, slots, cross-flavor warnings); Replace
text… acts on the ticked (else the highlighted) macros' bodies. Each stages on the review's Staged (ops.py): nothing
is written until Apply. The screen supplies `staged`, `sets`, `clipboard`, `ticked`, `idle`, highlighted_set(),
highlighted_macro(), picked_macros(), ticked_sets() and staging_changed()."""
from __future__ import annotations

from wowtools.core.events import log_event
from wowtools.core.text import plural
from wowtools.tools.macro_editor.model import MacroSet
from wowtools.tools.macro_editor.ops import (Staged, check_macro, cut_name, free_slots, preview_paste,
                                             preview_replace, stage_delete, stage_edit, stage_new,
                                             stage_replace_text)
from wowtools.tools.macro_editor.popups import MacroFormScreen, PasteScreen, ReplaceTextScreen
from wowtools.tools.macro_editor.report import DELETE_WARNING, paste_warnings, set_text
from wowtools.ui.dialogs import ConfirmScreen

__all__ = ["NOTHING_COPIED", "NOTHING_PICKED", "NO_TARGETS", "TREE_ACTIONS", "MacroEditActions"]

# The bar under the tree: (id, label, kind of action, action, key).
TREE_ACTIONS = (
    ("act-new", "New", "create", "new_macro", "N"),
    ("act-edit", "Edit", "overwrite", "edit_macro", "e"),
    ("act-delete", "Delete", "destructive", "delete_macros", "d"),
    ("act-copy", "Copy", "create", "copy_macros", "k"),
    ("act-paste", "Paste…", "create", "paste_macros", "p"),
    ("act-replace", "Replace text…", "overwrite", "replace_text", "R"),
)
NOTHING_PICKED = "Tick macros (or highlight one) first."
NOTHING_COPIED = "Copy (k) some macros first."
NO_TARGETS = "Tick the sets to paste into first: a character, or an account's Account macros."
NO_SET = "Highlight a character or Account macros first."


class MacroEditActions:
    """The action bar's macro edits (N, e, d, k, p, R), on the review's staged changes."""

    staged: Staged

    def _refused(self, problem: str, what: str) -> None:
        self.notify(problem, title=f"{what} refused", severity="error")

    # --- New and Edit ----------------------------------------------------------------------------
    def action_new_macro(self) -> None:
        mset = self.highlighted_set()
        if not self.idle:
            return
        if mset is None:
            self.notify(NO_SET)
            return
        if mset.read_only:
            self._refused(f"{mset.label} is read-only: {mset.parsed.problem}", "New")
            return
        if not free_slots(self.staged, mset):
            self._refused(f"{mset.label} has no free macro slot ({mset.limit}/{mset.limit}).", "New")
            return

        def check(name: str, icon: str, body: str) -> str | None:
            return check_macro(cut_name(name), icon, body)

        def done(values: tuple[str, str, str] | None) -> None:
            if values is None:
                return
            name, icon, body = values
            try:
                stage_new(self.staged, mset, name=name, body=body, icon=icon)
            except ValueError as exc:
                self._refused(str(exc), "New")
                return
            log_event("ui.selection", screen=self.LOG_SCREEN, control="new_macro", value=set_text(mset))
            self.staging_changed()
        self.app.push_screen(MacroFormScreen("New macro", set_text(mset), check=check), done)

    def action_edit_macro(self) -> None:
        picked = self.highlighted_macro()
        if not self.idle:
            return
        if picked is None:
            self.notify("Highlight a macro first.")
            return
        mset, macro = picked

        def check(name: str, icon: str, body: str) -> str | None:
            return check_macro(name if name == macro.name else cut_name(name), icon, body)

        def done(values: tuple[str, str, str] | None) -> None:
            if values is None:
                return
            name, icon, body = values
            try:
                stage_edit(self.staged, mset, macro.id, name=name, icon=icon, body=body)
            except ValueError as exc:
                self._refused(str(exc), "Edit")
                return
            log_event("ui.selection", screen=self.LOG_SCREEN, control="edit_macro",
                      value=f"{set_text(mset)} › {macro.name}")
            self.staging_changed()
        self.app.push_screen(MacroFormScreen("Edit macro", f"{set_text(mset)} (the macro keeps its id)",
                                             macro.name, macro.icon, macro.body, check), done)

    # --- Delete --------------------------------------------------------------------------------
    def action_delete_macros(self) -> None:
        picked = self.picked_macros()
        if not self.idle:
            return
        if not picked:
            self.notify(NOTHING_PICKED)
            return
        names = "\n".join(f"{set_text(mset)} › {macro.name}" for mset, macro in picked)
        body = f"{names}\n\nNothing is written until Apply."

        def done(ok: bool | None) -> None:
            log_event("ui.selection", screen="confirm", control="delete_confirm", value=bool(ok))
            if not ok:
                return
            for mset, macro in picked:
                try:
                    stage_delete(self.staged, mset, macro.id)
                except ValueError as exc:
                    self._refused(str(exc), "Delete")
            self.ticked.clear()
            self.staging_changed()
        self.app.push_screen(ConfirmScreen(f"Delete {plural(len(picked), 'macro')}?", body, (DELETE_WARNING,),
                                           kind="destructive"), done)

    # --- Copy and Paste… ------------------------------------------------------------------------------
    def action_copy_macros(self) -> None:
        picked = self.picked_macros()
        if not self.idle:
            return
        if not picked:
            self.notify(NOTHING_PICKED)
            return
        self.clipboard = list(picked)
        self.ticked.clear()  # the next ticks pick where to paste
        log_event("ui.selection", screen=self.LOG_SCREEN, control="copy_macros", value=len(picked))
        self.notify(f"Copied {plural(len(picked), 'macro')}: tick the sets to paste into, then Paste… (p).")
        self._refresh_labels()

    def action_paste_macros(self) -> None:
        if not self.idle:
            return
        if not self.clipboard:
            self.notify(NOTHING_COPIED)
            return
        targets: list[MacroSet] = self.ticked_sets()
        if not targets:
            self.notify(NO_TARGETS)
            return
        macros = [macro for _, macro in self.clipboard]
        staged = self.staged
        title = f"Paste {plural(len(macros), 'macro')} into {plural(len(targets), 'set')}"
        body = "\n".join(set_text(target) for target in targets)

        def preview(choices: dict):
            return preview_paste(staged, macros, targets, choices)

        def done(choices: dict | None) -> None:
            log_event("ui.selection", screen="paste", control="paste_confirm", value=choices is not None)
            if choices is None:
                return
            result = preview(choices)
            self.staged.changes.clear()
            self.staged.changes.update(result.staged.changes)
            for line in result.refusals:
                log_event("ui.selection", screen="paste", control="refused", value=line)
            self.ticked.clear()
            self.staging_changed()
        self.app.push_screen(PasteScreen(title, body, preview, paste_warnings(self.clipboard, targets)), done)

    # --- Replace text… --------------------------------------------------------------------------------
    def action_replace_text(self) -> None:
        picked = self.picked_macros()
        if not self.idle:
            return
        if not picked:
            self.notify(NOTHING_PICKED)
            return

        def preview(find: str, new: str, case: bool):
            return preview_replace(self.staged, picked, find, new, case=case)

        def done(values: tuple[str, str, bool] | None) -> None:
            if values is None:
                return
            find, new, case = values
            count = stage_replace_text(self.staged, picked, find, new, case=case)
            log_event("ui.selection", screen=self.LOG_SCREEN, control="replace_text", value=count)
            self.notify(f"Replaced in {plural(count, 'macro')}.")
            self.staging_changed()
        self.app.push_screen(ReplaceTextScreen(f"Replace text in {plural(len(picked), 'macro')}",
                                               "Changes the macros' bodies; names stay as they are.", preview), done)
