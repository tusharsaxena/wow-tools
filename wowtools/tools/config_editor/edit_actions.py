"""The Config Editor browse screen's CVar edits (config tools spec CE5, CE7), mixed into ConfigReviewScreen: the bar
under the tree and Space on a boolean row. Set (the highlighted CVar), Remove and Reset act on the highlighted CVar
in every ticked file, else in the file of the highlighted row; Add puts a CVar into the ticked files, else the
highlighted one; Recommend… lists the recommendations for the highlighted file and stages the ticked ones as a
batch; Space on a CVar whose value is 0 or 1 toggles it there. Each stages on the review's ConfigStaged (ops.py):
nothing is written until Apply. A scope mismatch (CE5) is a warning, never a refusal; an unknown CVar can be set,
removed and added like any other. The screen supplies `staged`, `ticked`, `idle`, cvars_for(flavor),
recommendations_for(flavor), highlighted_target(), highlighted_row(), picked_targets() and staging_changed()."""
from __future__ import annotations

from wowtools.core.events import log_event
from wowtools.core.text import plural
from wowtools.tools.config_editor.model import ConfigTarget, Row
from wowtools.tools.config_editor.ops import (ConfigStaged, applicable_recommendations, stage_remove, stage_reset,
                                              stage_set, stage_toggle)
from wowtools.tools.config_editor.popups import AddCvarScreen, RecommendScreen
from wowtools.tools.config_editor.report import UNKNOWN, scope_text, target_text
from wowtools.ui.dialogs import TextPromptScreen

__all__ = ["NO_CVAR", "NO_FILE", "TREE_ACTIONS", "ConfigEditActions"]

# The bar under the tree: (id, label, kind of action, action, key).
TREE_ACTIONS = (
    ("act-set", "Set", "overwrite", "set_cvar", "e"),
    ("act-add", "Add", "create", "add_cvar", "N"),
    ("act-remove", "Remove", "destructive", "remove_cvar", "d"),
    ("act-reset", "Reset", "revert", "reset_cvar", "R"),
    ("act-recommend", "Recommend…", "overwrite", "recommend", "m"),
)
NO_CVAR = "Open a file and highlight a CVar first."
NO_FILE = "Highlight a file first: Config.wtf, an Account config or a character."


def stage_problem(target: ConfigTarget, name: str, value: str) -> str | None:
    """Why `SET name "value"` can't be staged in the target (read-only, a name or value the file can't hold), or
    None: ops.stage_set's own check, on a throwaway staging."""
    try:
        stage_set(ConfigStaged(), target, name, value)
    except ValueError as exc:
        return str(exc)
    return None


def files_text(targets: list[ConfigTarget]) -> str:
    return f"{plural(len(targets), 'file')}: " + ", ".join(target_text(t) for t in targets)


class ConfigEditActions:
    """The action bar's CVar edits (e, N, d, R, m) and Space on a boolean row, on the review's staged changes."""

    staged: ConfigStaged

    def _refused(self, problem: str, what: str) -> None:
        self.notify(problem, title=f"{what} refused", severity="error")

    def _row_targets(self) -> tuple[ConfigTarget, Row, list[ConfigTarget]] | None:
        """The highlighted CVar row, its file, and the files an edit of it acts on: the ticked ones, else its own."""
        picked = self.highlighted_row()
        if picked is None:
            self.notify(NO_CVAR)
            return None
        target, row = picked
        ticked = self.ticked_targets()
        return target, row, ticked if ticked else [target]

    # --- Space on a boolean ------------------------------------------------------------------------
    def toggle_cvar(self) -> None:
        """Space on a CVar row: flip it between 0 and 1 in its file (CE5, in place)."""
        picked = self.highlighted_row()
        if not self.idle or picked is None:
            return
        target, row = picked
        if target.read_only:
            self._refused(f"{target.label} is read-only: {target.problem}", "Toggle")
            return
        try:
            value = stage_toggle(self.staged, target, row.name, row.info)
        except ValueError:
            self.notify(f"{row.name} is not 0 or 1: Set (e) changes it.")
            return
        log_event("ui.selection", screen=self.LOG_SCREEN, control="toggle_cvar",
                  value=f"{target_text(target)} › {row.name} = {value}")
        self.staging_changed()

    # --- Set, Remove, Reset ------------------------------------------------------------------------
    def action_set_cvar(self) -> None:
        if not self.idle:
            return
        found = self._row_targets()
        if found is None:
            return
        _, row, targets = found
        name = row.name
        body = [files_text(targets)]
        if row.info is not None and row.default is not None:
            body.append(f"Default: {row.default}.")
        elif row.info is None:
            body.append(f"{name} is {UNKNOWN}: it is written as you type it.")

        def check(value: str) -> str | None:
            return next((p for p in (stage_problem(t, name, value) for t in targets) if p), None)

        def done(value: str | None) -> None:
            if value is None:
                return
            for each in targets:
                stage_set(self.staged, each, name, value)
            log_event("ui.selection", screen=self.LOG_SCREEN, control="set_cvar", value=f"{name} = {value}",
                      files=len(targets))
            self.staging_changed()
        initial = row.value if row.value is not None else (row.default or "")
        self.app.push_screen(TextPromptScreen(f"Set {name}", "\n".join(body), initial, check, placeholder="value"),
                             done)

    def _stage_removal(self, reset: bool) -> None:
        if not self.idle:
            return
        found = self._row_targets()
        if found is None:
            return
        _, row, targets = found
        what = "Reset" if reset else "Remove"
        if reset and (row.info is None or row.default is None):
            self.notify(f"{row.name} has no known default: Remove (d) takes its line out.", title="Reset")
            return
        for each in targets:
            try:
                (stage_reset if reset else stage_remove)(self.staged, each, row.name)
            except ValueError as exc:
                self._refused(str(exc), what)
        log_event("ui.selection", screen=self.LOG_SCREEN, control="reset_cvar" if reset else "remove_cvar",
                  value=row.name, files=len(targets))
        self.staging_changed()

    def action_remove_cvar(self) -> None:
        """Take the CVar's SET lines out (any CVar, known or not)."""
        self._stage_removal(reset=False)

    def action_reset_cvar(self) -> None:
        """Reset to default (CE5): the line goes, so the game uses its default; only for a known default."""
        self._stage_removal(reset=True)

    # --- Add -----------------------------------------------------------------------------------
    def action_add_cvar(self) -> None:
        if not self.idle:
            return
        targets = self.picked_targets()
        if not targets:
            self.notify(NO_FILE)
            return
        writable = [t for t in targets if not t.read_only]
        if not writable:
            self._refused(f"{targets[0].label} is read-only: {targets[0].problem}", "Add")
            return

        def describe(name: str) -> str:
            notes = []
            for flavor in dict.fromkeys(t.flavor for t in writable):
                index = {n.casefold(): i for n, i in self.cvars_for(flavor.folder).items()}
                info = index.get(name.casefold())
                if info is None:
                    notes.append(f"{name}: {UNKNOWN} in {flavor.display_name}; it is added as you type it.")
                    continue
                default = f"default {info.default}" if info.default is not None else "default not known"
                notes.append(f"{info.name} ({flavor.display_name}): {default}. {scope_text(info)}")
                levels = sorted({t.level for t in writable if t.flavor == flavor and info.scope is not None
                                 and t.level != info.scope})
                if levels:
                    notes.append(f"⚠ The game keeps it at the {info.scope} level; set at the {' and '.join(levels)} "
                                 "level it may be ignored.")
            return "\n".join(notes)

        def check(name: str, value: str) -> str | None:
            if not name:
                return "Type the CVar's name."
            return next((p for p in (stage_problem(t, name, value) for t in writable) if p), None)

        def done(values: tuple[str, str] | None) -> None:
            if values is None:
                return
            name, value = values
            for each in writable:
                stage_set(self.staged, each, name, value)
            log_event("ui.selection", screen=self.LOG_SCREEN, control="add_cvar", value=f"{name} = {value}",
                      files=len(writable))
            self.staging_changed()
        self.app.push_screen(AddCvarScreen("Add a CVar", files_text(writable), describe, check), done)

    # --- Recommend… ------------------------------------------------------------------------------
    def action_recommend(self) -> None:
        if not self.idle:
            return
        target = self.highlighted_target()
        if target is None:
            self.notify(NO_FILE)
            return
        if target.read_only:
            self._refused(f"{target.label} is read-only: {target.problem}", "Recommend…")
            return
        folder = target.flavor.folder
        found = applicable_recommendations(target, self.recommendations_for(folder), self.cvars_for(folder),
                                           self.staged)

        def done(picked) -> None:
            log_event("ui.selection", screen="recommend", control="recommend_confirm", value=picked is not None)
            if not picked:
                return
            for row in picked:
                try:
                    stage_set(self.staged, target, row.recommendation.cvar, row.recommendation.value)
                except ValueError as exc:
                    self._refused(str(exc), "Recommend…")
            self.notify(f"Staged {plural(len(picked), 'recommendation')} for {target.label}.")
            self.staging_changed()
        self.app.push_screen(RecommendScreen(f"Recommendations for {target_text(target)}",
                                             "Tick the ones to stage; nothing is written until Apply.", found), done)
