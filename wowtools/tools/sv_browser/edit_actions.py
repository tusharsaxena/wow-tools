"""The Saved Variables Browser review's key edits (D5, D10, D39; F-007, decision R5), mixed into SvReviewScreen: Edit
value, Rename key, Delete key and Unstage on the highlighted key in Browse, and in Results the bulk Edit value and
Rename key on the ticked (else highlighted) hits, whose tables are read in a worker under the progress popup. Each
asks in a popup (popups.py) and stages on the review's Staging (ops.py, bulk.py): nothing is written until Apply. The
screen supplies `staging`, `docs`, `search_result`, `view`, `idle`, highlighted(), highlighted_hit(), bulk_targets(),
start_run() (RunActions) and _refresh_labels()."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from wowtools.core.luasv import encode_value
from wowtools.core.text import plural
from wowtools.tools.sv_browser.bulk import BulkResult, new_value, read_tables, stage_renames, stage_values, table_key
from wowtools.tools.sv_browser.model import Node, SvDocument, scalar_text
from wowtools.tools.sv_browser.ops import Staging, key_input, key_problem, parse_key, path_text, value_problem
from wowtools.tools.sv_browser.popups import (NOT_TYPABLE, EditValueScreen, RenameKeyScreen, SearchProgressScreen,
                                              delete_confirm)
from wowtools.tools.sv_browser.report import RESULTS
from wowtools.tools.sv_browser.search import REPLACE_BOOLEAN, REPLACE_NUMBER, REPLACE_STRING, Hit

__all__ = ["READ_TABLES", "READ_UNSTAGE_TABLE", "SvEditActions"]

READ_TABLES = "Reading the tables of the keys to rename"
READ_UNSTAGE_TABLE = "Reading the table of the key to unstage"


class SvEditActions:
    """The action bar's key edits (e, k, d, Backspace), on the review's staged edits."""

    staging: Staging

    def _key_target(self, problem: Callable[[SvDocument, Node], str | None]) -> tuple[SvDocument, Node] | None:
        """The highlighted key, when the action may act on it; else None, saying why when the staging refuses it
        (inside a deleted table, ...)."""
        doc, node = self.highlighted()
        if not self.idle or doc is None or node is None:
            return None
        why = problem(doc, node)
        if why is not None:
            self.notify(why, severity="warning")
            return None
        return doc, node

    def _where_key(self, doc: SvDocument, node: Node) -> str:
        return f"{doc.file.path.name} › {path_text(node.path)}"

    def _staged(self, result, what: str) -> None:
        """After a staging call: the marks and the pending line, or the refusal."""
        if not result.ok:
            self.notify(result.message, title=f"{what} refused", severity="error")
            return
        if result.dropped:
            self.notify(f"{plural(result.dropped, 'edit')} staged inside it dropped.")
        self._refresh_labels()

    def action_edit_value(self) -> None:
        if self.view == RESULTS:
            self._bulk_edit_value()
            return
        target = self._key_target(lambda doc, node: self.staging.set_problem(doc, node, ""))
        if target is None:
            return
        doc, node = target
        old = node.value.value
        raw = doc.data[node.value.start:node.value.end]
        # the popup starts from the value staged on the key, if any (as Rename starts from a staged name); Now: is
        # the file's
        edit = self.staging.edit_for(doc, node)
        start, start_raw = (edit.value, encode_value(edit.value)) if edit is not None and edit.set_value else (old, raw)
        kind, text, note = REPLACE_STRING, "", ""
        if isinstance(start, bool):
            kind = REPLACE_BOOLEAN
        elif isinstance(start, str):
            if any(c < " " or c == "\x7f" or "\udc80" <= c <= "\udcff" for c in start):
                note = NOT_TYPABLE
            else:
                text = start
        elif start is not None:
            kind, text = REPLACE_NUMBER, start_raw.decode("ascii", "replace")
        popup = EditValueScreen(self._where_key(doc, node), scalar_text(old, raw), kind, text, start is True,
                                check=lambda value: self.staging.set_problem(doc, node, value), note=note)

        def done(value) -> None:
            if value is not None:
                self._staged(self.staging.set_value(doc, node, value), "Edit value")
        self.app.push_screen(popup, done)

    def action_rename_key(self) -> None:
        if self.view == RESULTS:
            self._bulk_rename()
            return
        target = self._key_target(lambda doc, node: self.staging.rename_problem(doc, node, node.key))
        if target is None:
            return
        doc, node = target
        edit = self.staging.edit_for(doc, node)
        current = edit.new_key if edit is not None and edit.rename else node.key

        def done(text) -> None:
            if text is not None:
                self._staged(self.staging.rename(doc, node, parse_key(text)), "Rename key")
        self.app.push_screen(RenameKeyScreen(self._where_key(doc, node), key_input(current),
                                             lambda key: self.staging.rename_problem(doc, node, key)), done)

    def action_delete_key(self) -> None:
        if self.view == RESULTS:
            return  # Delete key stays single-key, in Browse (D39)
        target = self._key_target(self.staging.delete_problem)
        if target is None:
            return
        doc, node = target
        popup = delete_confirm(self._where_key(doc, node), count=node.count, table=node.is_table,
                               positional=node.positional, staged_inside=self.staging.staged_inside(doc, node))

        def done(ok: bool | None) -> None:
            if ok:
                self._staged(self.staging.delete(doc, node), "Delete key")
        self.app.push_screen(popup, done)

    def action_unstage(self) -> None:
        """Backspace: drop what is staged on the highlighted key (or hit, in Results)."""
        if self.view == RESULTS:
            hit = self.highlighted_hit()
            edit = self.staging.hit_edit(hit) if hit is not None and self.idle else None
            if edit is None:
                return
            if not edit.rename:
                self._staged(self.staging.unstage_hit(hit), "Unstage")
                return
            # a rename needs its table (no key left twice): read in a worker, as the bulk rename reads it
            self._read_tables_then([hit], lambda tables: self._staged(
                self.staging.unstage_hit(hit, tables.get(table_key(hit))), "Unstage"), name="unstage_hit", title=READ_UNSTAGE_TABLE)
            return
        doc, node = self.highlighted()
        if not self.idle or doc is None or node is None or self.staging.edit_for(doc, node) is None:
            return
        self._staged(self.staging.unstage(doc, node), "Unstage")

    # --- bulk edits on the results (D39) ------------------------------------------------------------
    def _loaded_shas(self) -> dict[Path, str]:
        """The SHA-256 of each file opened in Browse (a hit read from other bytes is left out)."""
        return {path: doc.sha256 for path, doc in self.docs.items() if doc.sha256}

    def _bulk_where(self, hits: list[Hit]) -> str:
        if len(hits) == 1:
            return f"{hits[0].file.path.name} › {path_text(hits[0].path)}"
        files = len({h.file.path for h in hits})
        return f"{plural(len(hits), 'ticked result')} in {plural(files, 'file')}"

    def _bulk_staged(self, result: BulkResult, what: str) -> None:
        """After a bulk edit: the marks, the pending line and the notice (what was left out and why)."""
        self._refresh_labels()
        self.notify(result.text(), title=what, severity="warning" if result.left else "information",
                    timeout=15 if result.left else 5)

    def _bulk_edit_value(self) -> None:
        """Edit value on the ticked (else highlighted) hits: one popup, one staged set per hit. After a value
        Contains search it may replace only the matched text (the default)."""
        hits = self.bulk_targets()
        if not self.idle or not hits:
            return
        spec = self.search_result.spec if self.search_result is not None else None
        matched = spec is not None and spec.contains_value
        olds = {(type(h.old), h.old_bytes) for h in hits}
        first = hits[0]
        kind, text, flag = REPLACE_STRING, "", False
        if len(olds) == 1 and not matched:  # one value on every hit: start from it
            if isinstance(first.old, bool):
                kind, flag = REPLACE_BOOLEAN, first.old
            elif isinstance(first.old, str):
                text = first.old if not any(c < " " or c == "\x7f" or "\udc80" <= c <= "\udcff"
                                            for c in first.old) else ""
            elif first.old is not None:
                kind, text = REPLACE_NUMBER, first.old_bytes.decode("ascii", "replace")
        title = "Edit value" if len(hits) == 1 else f"Edit {plural(len(hits), 'value')}"
        current = scalar_text(first.old, first.old_bytes) if len(hits) == 1 else ""
        popup = EditValueScreen(self._bulk_where(hits), current, kind, text, flag, check=value_problem, title=title,
                                matched=matched)

        def done(value) -> None:
            if value is None:
                return
            mode = popup.mode
            result = stage_values(self.staging, hits, lambda hit: new_value(spec, mode, value, hit),
                                  self._loaded_shas())
            self._bulk_staged(result, title)
        self.app.push_screen(popup, done)

    def _bulk_rename(self) -> None:
        """Rename key on the ticked (else highlighted) hits: one popup, then the keys' tables are read in a worker
        (the duplicate check) and one rename per hit is staged."""
        hits = self.bulk_targets()
        if not self.idle or not hits:
            return
        keys = {key_input(h.key) for h in hits}
        initial = keys.pop() if len(keys) == 1 else ""
        title = "Rename key" if len(hits) == 1 else f"Rename {plural(len(hits), 'key')}"

        def done(text) -> None:
            if text is not None:
                shas = self._loaded_shas()
                self._read_tables_then(hits, lambda tables: self._bulk_staged(
                    stage_renames(self.staging, hits, parse_key(text), tables, shas), title), name="bulk_rename")
        self.app.push_screen(RenameKeyScreen(self._bulk_where(hits), initial, key_problem, title=title), done)

    def _read_tables_then(self, hits: list[Hit], then: Callable[[dict], None], *, name: str,
                          title: str = READ_TABLES) -> None:
        """Read the tables holding the hits' keys (bulk.read_tables) in a worker under the progress popup, then
        then(tables) on the UI thread: a large file is never read or parsed on the event loop."""
        progress = SearchProgressScreen(title, first_stage="tables")

        def report(done: int, total: int, file: str) -> None:
            progress.report("tables", done, total, file)
        self.start_run(progress, lambda: read_tables(hits, report), then, name=name,
                       failure="Reading the tables stopped", stale_on_crash=False, writes=False)
