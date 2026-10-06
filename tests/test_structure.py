"""Structure rules from CLAUDE.md and the 2026-10-04 review (F-009, F-023, F-024), checked on the source itself so
they cannot drift again: no tool imports another tool, shared dialogs and helpers live in one place, dead code
stays gone, one definition of the data folder name, and every module has the future import."""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGES = ("wowtools", "scripts", "tests")


def modules(*roots: str) -> list[Path]:
    return sorted(p for root in roots for p in (REPO / root).rglob("*.py") if "__pycache__" not in p.parts)


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def imported_modules(module: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def resolved_imports(module: ast.Module, package: str) -> set[str]:
    """Every module an import may load, as absolute names: relative imports resolved against `package` (the
    importing file's package), and `from X import a` also as `X.a` (a may be a submodule)."""
    names = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parent = ".".join(parts[:len(parts) - node.level + 1])
                base = f"{parent}.{base}" if base else parent
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def package_of(path: Path) -> str:
    """The dotted package a module file is in (an __init__.py is its own package)."""
    return ".".join(path.relative_to(REPO).with_suffix("").parts[:-1])


def defined_functions(module: ast.Module) -> set[str]:
    return {node.name for node in ast.walk(module) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


class StructureTest(unittest.TestCase):
    def test_no_tool_imports_another_tool(self):
        tools = sorted(p.name for p in (REPO / "wowtools" / "tools").iterdir()
                       if p.is_dir() and (p / "__init__.py").exists())
        self.assertIn("wtf_cleaner", tools)
        offenders = []
        for name in tools:
            for path in modules(f"wowtools/tools/{name}"):
                imported = resolved_imports(tree(path), package_of(path))
                for other in tools:
                    if other != name and any(m == f"wowtools.tools.{other}" or m.startswith(f"wowtools.tools.{other}.")
                                             for m in imported):
                        offenders.append(f"{rel(path)} imports wowtools.tools.{other}")
        self.assertEqual(offenders, [])

    def test_the_import_check_sees_every_form(self):
        """The check above resolves `from wowtools.tools import x` and relative imports too."""
        package = "wowtools.tools.wtf_cleaner"
        for source in ("import wowtools.tools.interface_backup.scanner",
                       "from wowtools.tools.interface_backup.scanner import scan_flavors",
                       "from wowtools.tools import interface_backup",
                       "from ..interface_backup.scanner import scan_flavors",
                       "from .. import interface_backup"):
            with self.subTest(source=source):
                self.assertIn("wowtools.tools.interface_backup", {
                    m if m.count(".") < 3 else ".".join(m.split(".")[:3])
                    for m in resolved_imports(ast.parse(source), package)})
        self.assertEqual(package_of(REPO / "wowtools" / "tools" / "wtf_cleaner" / "cleaner.py"), package)
        self.assertEqual(package_of(REPO / "wowtools" / "tools" / "wtf_cleaner" / "__init__.py"), package)

    def test_shared_helpers_are_defined_once(self):
        names = {"_safe_progress", "safe_progress", "_remove", "_discard", "remove_quietly"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & names}
        self.assertEqual(where, {("wowtools/core/fsutil.py", "safe_progress"),
                                 ("wowtools/core/fsutil.py", "remove_quietly")})
        # The suite polish's shared helpers (spec D9): one definition in core, none copied into a tool. The names
        # in `gone` were the tools' own copies; latest_undoable / prune_journals / resolve_journal_dir are a tool's
        # ToolJournals methods, never a def of its own.
        once = {"plural": "text.py", "human_size": "text.py", "flavor_name": "install.py",
                "validate_backup_dir": "install.py", "latest_undoable": "journal.py", "prune_journals": "journal.py",
                "safe_destination": "undo.py"}
        gone = {"format_size", "clean_journal_dir", "resolve_journal_dir"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & (set(once) | gone)}
        self.assertEqual(where, {(f"wowtools/core/{module}", name) for name, module in once.items()})
        classes = {"ThrottledProgress": "progress.py", "ToolJournals": "journal.py", "UndoResultBase": "undo.py"}
        where = {(rel(p), node.name) for p in modules("wowtools") for node in ast.walk(tree(p))
                 if isinstance(node, ast.ClassDef) and node.name in classes}
        self.assertEqual(where, {(f"wowtools/core/{module}", name) for name, module in classes.items()})

    def test_saved_variables_reader_lives_in_core(self):
        """The SavedVariables reader (SV Browser spec D20) is wowtools/core/luasv.py's: Ace3 and SV Browser import it,
        no tool keeps a luasv module or defines its parser, codecs or parse classes."""
        self.assertEqual([rel(p) for p in modules("wowtools") if p.name == "luasv.py"], ["wowtools/core/luasv.py"])
        functions = {"parse", "parse_at", "iter_scalars", "decode_string", "encode_string", "encode_value",
                     "encode_key", "key_id", "splice", "newline_of", "line_start", "is_blank_table"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & functions}
        self.assertEqual(where, {("wowtools/core/luasv.py", n) for n in functions})
        classes = {"LuaParseError", "RawNumber", "Scalar", "Opaque", "Field", "Table", "Assignment", "Chunk"}
        where = {(rel(p), node.name) for p in modules("wowtools") for node in ast.walk(tree(p))
                 if isinstance(node, ast.ClassDef) and node.name in classes}
        self.assertEqual(where, {("wowtools/core/luasv.py", n) for n in classes})

    def test_saved_variables_files_and_tool_root_live_in_core(self):
        """The SavedVariables file model and walk (SV Browser spec D20) are core/svfiles.py's, tool_root is
        core/journal.py's; only the WTF Cleaner, whose backup folder holds no tool subfolder, builds its own root
        from TOOLS_SUBDIR."""
        functions = {"sha256_of", "is_sv_file", "is_addon_sv_file", "candidate_files", "under_link", "_under_link",
                     "walk_sv_files"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & functions}
        self.assertEqual(where, {("wowtools/core/svfiles.py", n) for n in functions - {"_under_link"}})
        where = {rel(p) for p in modules("wowtools") for node in ast.walk(tree(p))
                 if isinstance(node, ast.ClassDef) and node.name == "SvFile"}
        self.assertEqual(where, {"wowtools/core/svfiles.py"})
        where = {rel(p) for p in modules("wowtools") if "tool_root" in defined_functions(tree(p))}
        self.assertEqual(where, {"wowtools/core/journal.py"})
        users = {rel(p) for p in modules("wowtools/tools") for node in ast.walk(tree(p))
                 if isinstance(node, ast.Name) and node.id == "TOOLS_SUBDIR"}
        self.assertEqual(users, {"wowtools/tools/wtf_cleaner/settings.py"})

    def test_saved_variables_write_pipeline_lives_in_core(self):
        """The SavedVariables write pipeline (SV Browser spec D20) is core's: apply, the edit journal, undo and
        recovery, the verify helpers, the result rows and the one WowRunning. A tool keeps only thin wrappers that
        pass its SvTool (name, event prefix) and its compile / verify callbacks."""
        functions = {"_prepare": "sv_apply.py", "_roll_back": "sv_apply.py", "restore_original": "sv_apply.py",
                     "edited_zip_path": "sv_apply.py", "prune_edited_zips": "sv_apply.py",
                     "refuse_running": "sv_apply.py", "read_edit_journal": "sv_journal.py",
                     "record_recovered": "sv_journal.py", "referenced_zips": "sv_journal.py",
                     "destination": "sv_undo.py", "_put_back": "sv_undo.py", "_moved_zip": "sv_undo.py",
                     "_snapshots": "sv_undo.py", "gaps": "sv_verify.py", "_gaps": "sv_verify.py",
                     "check_assignments": "sv_verify.py", "rest_outside": "sv_verify.py",
                     "same_outside": "sv_verify.py", "in_backup_folder": "sv_report.py",
                     "apply_summary_rows": "sv_report.py", "apply_detail_rows": "sv_report.py",
                     "undo_detail_rows": "sv_report.py", "sv_events": "sv_events.py"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & set(functions)
                 if not (n == "_roll_back" and rel(p) == "wowtools/tools/interface_backup/restore.py")}
        self.assertEqual(where, {(f"wowtools/core/{module}", name) for name, module in functions.items()
                                 if name != "_gaps"})
        classes = {"ApplyResult": "sv_apply.py", "MultiApplyResult": "sv_apply.py", "ApplyError": "sv_apply.py",
                   "UndoError": "sv_apply.py", "WowRunning": "sv_apply.py", "EditJournal": "sv_journal.py",
                   "ProfileJournal": None, "SvTool": "sv_events.py"}
        where = {(rel(p), node.name) for p in modules("wowtools") for node in ast.walk(tree(p))
                 if isinstance(node, ast.ClassDef) and node.name in classes}
        self.assertEqual(where, {(f"wowtools/core/{module}", name) for name, module in classes.items() if module})
        from wowtools.core import sv_apply, sv_journal, sv_undo
        from wowtools.tools.ace3_profile_manager import editor, journal, multi, undo
        from wowtools.tools.ace3_profile_manager.events import SV_TOOL
        self.assertIs(editor.Marker, sv_apply.Marker)
        self.assertIs(multi.WowRunning, undo.WowRunning)
        self.assertIs(journal.read_profile_journal, sv_journal.read_edit_journal)
        self.assertIs(journal.JOURNALS, SV_TOOL.journals)
        self.assertIs(undo.UndoResult, sv_undo.UndoResult)
        self.assertEqual((SV_TOOL.name, SV_TOOL.prefix), ("ace3-profile-manager", "ace"))

    def test_tools_use_the_shared_helpers(self):
        """Each tool's journals, undo results and markers go through core (no copy of the bodies)."""
        from wowtools.core import journal, undo
        from wowtools.tools.ace3_profile_manager import journal as ace_journal
        from wowtools.tools.ace3_profile_manager import undo as ace_undo
        from wowtools.tools.interface_backup import journal as ib_journal
        from wowtools.tools.screenshot_organizer import journal as shots_journal
        from wowtools.tools.wtf_cleaner import journal as wtf_journal
        from wowtools.tools.wtf_cleaner import undo as wtf_undo
        for module in (ace_journal, ib_journal, shots_journal, wtf_journal):
            self.assertIsInstance(module.JOURNALS, journal.ToolJournals)
            self.assertEqual(module.resolve_journal_dir, module.JOURNALS.dir)
            self.assertEqual(module.latest_undoable, module.JOURNALS.latest_undoable)
        for module in (ace_undo, wtf_undo):
            self.assertTrue(issubclass(module.UndoResult, undo.UndoResultBase))
        for path in ("wowtools/tools/wtf_cleaner/safety.py", "wowtools/core/sv_apply.py"):
            self.assertIn("wowtools.core.marker", imported_modules(tree(REPO / path)) | {
                f"{n.module}.{a.name}" for n in ast.walk(tree(REPO / path))
                if isinstance(n, ast.ImportFrom) and n.module for a in n.names})

    def test_review_machinery_lives_in_ui(self):
        """Ticks, Space, select all / none, leaving, the running-programs check, the debounced rebuild and the scan
        progress are wowtools/ui/review.py's (spec D9): no tool defines its own, and every review tree is a
        ReviewTree."""
        shared = {"action_toggle", "action_select_all", "action_select_none", "action_flavors", "action_tools",
                  "action_quit_tool", "run_preflight", "_run_preflight", "_preflight_worker", "_preflight_done",
                  "_schedule_rebuild", "_run_scheduled_rebuild", "_scan_progress"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & shared}
        # Interface Backup's run_preflight only wraps the shared one (it logs a running WoW first).
        self.assertEqual(where, {("wowtools/ui/review.py", n) for n in shared - {"action_flavors", "action_tools",
                                                                               "action_quit_tool", "_run_preflight"}}
                         | {("wowtools/tools/interface_backup/review_screen.py", "run_preflight")})
        trees = sorted(f"{rel(p)}:{node.name}" for p in modules("wowtools/tools") for node in ast.walk(tree(p))
                       if isinstance(node, ast.ClassDef)
                       and any(isinstance(b, ast.Name) and b.id == "Tree" for b in node.bases))
        self.assertEqual(trees, [])
        classes = {(rel(p), node.name) for p in modules("wowtools") for node in ast.walk(tree(p))
                   if isinstance(node, ast.ClassDef) and node.name in ("NotTicked", "ReviewTree", "TickModel")}
        self.assertEqual(classes, {("wowtools/ui/review.py", n) for n in ("NotTicked", "ReviewTree", "TickModel")})

    def test_lock_refusal_and_progress_close_are_shared(self):
        """Functionality two tools need lives in the shared library: the lock refusal (core/svfiles.py: the probe
        loop and its message) and closing a review's progress popup (ui/review.py, Ace3's included)."""
        where = {(rel(p), n) for p in modules("wowtools")
                 for n in defined_functions(tree(p)) & {"find_locked", "locked_message"}}
        self.assertEqual(where, {("wowtools/core/svfiles.py", n) for n in ("find_locked", "locked_message")})
        texts = [rel(p) for p in modules("wowtools") if "Close it and" in p.read_text(encoding="utf-8")]
        self.assertEqual(texts, ["wowtools/core/svfiles.py"])
        closes = {rel(p) for p in modules("wowtools") if "_close_progress" in defined_functions(tree(p))}
        self.assertEqual(closes, {"wowtools/ui/review.py"})

    def test_saved_variables_ui_helpers_live_in_ui(self):
        """The UI a SavedVariables tool shares (SV Browser spec D20): the form popup look and error line, the text
        prompt and the unfinished-run warning are ui/dialogs.py's; the apply / undo / recover plumbing (WoW check,
        refusals, the progress popup, the worker, its result or failure) is ui/review.py's RunActions. Ace3's name
        popup, recovery warning and review are built on them."""
        functions = {"popup_css": "dialogs.py", "show_error": "dialogs.py", "recovery_text": None,
                     "_check_wow": "review.py", "_refused_while_running": "review.py",
                     "_backup_dir_refused": "review.py", "start_run": "review.py", "_run_worker": "review.py",
                     "_run_done": "review.py", "_run_failed": "review.py", "_end_run": "review.py"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & set(functions)}
        self.assertEqual(where, {(f"wowtools/ui/{module}", name) for name, module in functions.items() if module}
                         | {("wowtools/core/sv_report.py", "recovery_text")})
        classes = {(rel(p), node.name) for p in modules("wowtools") for node in ast.walk(tree(p))
                   if isinstance(node, ast.ClassDef) and node.name in ("TextPromptScreen", "UnfinishedRunScreen",
                                                                       "RunActions")}
        self.assertEqual(classes, {("wowtools/ui/dialogs.py", "TextPromptScreen"),
                                   ("wowtools/ui/dialogs.py", "UnfinishedRunScreen"),
                                   ("wowtools/ui/review.py", "RunActions")})
        from wowtools.tools.ace3_profile_manager import popups, review_screen
        from wowtools.ui.dialogs import TextPromptScreen, UnfinishedRunScreen
        from wowtools.ui.review import RunActions
        self.assertTrue(issubclass(popups.NameScreen, TextPromptScreen))
        self.assertTrue(issubclass(review_screen.ProfileRecoveryScreen, UnfinishedRunScreen))
        self.assertTrue(issubclass(review_screen.ProfileReviewScreen, RunActions))
        # Ace3's screen runs nothing in a worker of its own: no activity.running() outside RunActions.
        self.assertNotIn("activity", (REPO / "wowtools/tools/ace3_profile_manager/review_screen.py").read_text(
            encoding="utf-8"))

    def test_tree_filter_lives_in_ui(self):
        """The tree filter (spec D7) is wowtools/ui/tree_filter.py's: no tool defines its own match, model filter,
        filter box or `/` action."""
        names = ("TextFilter", "ModelFilter", "FilterInput", "FilterBox", "TreeFilter")
        classes = {(rel(p), node.name) for p in modules("wowtools") for node in ast.walk(tree(p))
                   if isinstance(node, ast.ClassDef) and node.name in names}
        self.assertEqual(classes, {("wowtools/ui/tree_filter.py", n) for n in names})
        shared = {"action_focus_filter", "clear_filter", "hidden_by_filter", "shown_tick_mark",
                  "hidden_ticked_note"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & shared}
        self.assertEqual(where, {("wowtools/ui/tree_filter.py", n) for n in shared})
        # A tick screen with the filter lists every key of its model: the default reads the filtered tree's root.
        forgot = [(rel(p), node.name) for p in modules("wowtools/tools") for node in ast.walk(tree(p))
                  if isinstance(node, ast.ClassDef)
                  and any(isinstance(b, ast.Name) and b.id == "TreeFilter" for b in node.bases)
                  and "all_tick_keys" not in {f.name for f in node.body if isinstance(f, ast.FunctionDef)}]
        self.assertEqual(forgot, [])
        # Ace3's own search went onto the shared filter (T4.2): no focus_search action or match of its own, no tree
        # screen handles a filter box's changes itself, and the tree builder's Filters has no search text.
        tools = {n for p in modules("wowtools/tools") for n in defined_functions(tree(p))}
        self.assertEqual(tools & {"action_focus_search", "matches"}, set())
        screens = [rel(p) for p in modules("wowtools/tools")
                   if p.name in ("review_screen.py", "restore_screen.py", "blacklist_screen.py")]
        self.assertEqual(len(screens), 7)
        self.assertEqual([p for p in screens if "on_input_changed" in defined_functions(tree(REPO / p))], [])
        from wowtools.tools.ace3_profile_manager.tree_view import Filters
        self.assertFalse({"search", "matches"} & set(dir(Filters())))

    def test_shared_dialogs_live_in_ui(self):
        from wowtools.tools.screenshot_organizer.review_screen import ShotProgressScreen
        from wowtools.tools.wtf_cleaner import review_screen
        from wowtools.ui import dialogs
        self.assertEqual(dialogs.ConfirmScreen.__module__, "wowtools.ui.dialogs")
        self.assertTrue(issubclass(review_screen.CleanProgressScreen, dialogs.ProgressScreen))
        self.assertTrue(issubclass(ShotProgressScreen, dialogs.ProgressScreen))
        classes = {(rel(p), node.name) for p in modules("wowtools") for node in ast.walk(tree(p))
                   if isinstance(node, ast.ClassDef) and node.name in ("ConfirmScreen", "ProgressScreen")}
        self.assertEqual(classes, {("wowtools/ui/dialogs.py", "ConfirmScreen"),
                                   ("wowtools/ui/dialogs.py", "ProgressScreen")})

    def test_result_choice_settings_and_flow_live_in_ui(self):
        """Result screens, warning popups with a choice, settings forms and the flow steps every tool takes are
        wowtools/ui's (spec D9): each tool screen subclasses the shared one, and no tool copies a flow step."""
        from wowtools.tools import TOOLS
        from wowtools.tools.ace3_profile_manager import result_screen as ace_result
        from wowtools.tools.ace3_profile_manager import review_screen as ace_review
        from wowtools.tools.interface_backup import restore_screen
        from wowtools.tools.interface_backup import review_screen as ib_review
        from wowtools.tools.screenshot_organizer import review_screen as shots_review
        from wowtools.tools.wtf_cleaner import review_screen as wtf_review
        from wowtools.ui.dialogs import ChoiceScreen
        from wowtools.ui.result_screen import ResultBase, ResultScreen
        from wowtools.ui.settings_form import ToolSettingsScreen
        from wowtools.ui.suite_app import LockScreen
        from wowtools.ui.tool_flow import ToolFlow
        for screen in (wtf_review.ResultScreen, shots_review.ShotResultScreen, ib_review.BackupResultScreen,
                       restore_screen.RestoreResultScreen):
            self.assertTrue(issubclass(screen, ResultBase), screen)
        self.assertTrue(issubclass(ace_result.ProfileResultScreen, ResultScreen))
        for screen in (wtf_review.RecoveryScreen, ace_review.ProfileRecoveryScreen, LockScreen):
            self.assertTrue(issubclass(screen, ChoiceScreen), screen)
        for tool in TOOLS.values():
            flow = tool.flow()
            self.assertTrue(issubclass(flow, ToolFlow))
            self.assertTrue(issubclass(flow.SETTINGS_SCREEN, ToolSettingsScreen), tool.name)
            self.assertEqual(flow.SECTION, tool.section)
        classes = {(rel(p), node.name) for p in modules("wowtools") for node in ast.walk(tree(p))
                   if isinstance(node, ast.ClassDef) and node.name in ("ResultBase", "ChoiceScreen", "ToolSettingsScreen")}
        self.assertEqual(classes, {("wowtools/ui/result_screen.py", "ResultBase"),
                                   ("wowtools/ui/dialogs.py", "ChoiceScreen"),
                                   ("wowtools/ui/settings_form.py", "ToolSettingsScreen")})
        # The flow steps and form plumbing: ToolFlow's / ToolSettingsScreen's only. Interface Backup's
        # _settings_done wraps the shared one (a changed WoW folder says nothing).
        shared = {"start", "open_settings", "_after_review", "remember_flavor", "pick_account", "fill_notes",
                  "_after_account", "_default_backup_hint", "_count_worker", "_notes_worker", "_settings_done",
                  "_error", "action_cancel", "_save"}
        where = {(rel(p), n) for p in modules("wowtools/tools") if p.name == "app.py"
                 for n in defined_functions(tree(p)) & shared}
        self.assertEqual(where, {("wowtools/tools/interface_backup/app.py", "_settings_done")})

    def test_literals_are_defined_once(self):
        found: dict[str, list[str]] = {}
        for path in modules("wowtools"):
            for node in ast.walk(tree(path)):
                if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                        and node.value.value in ("#4CC38A", 86400.0)):
                    found.setdefault(str(node.value.value), []).append(rel(path))
                if isinstance(node, ast.Constant) and node.value == "wow-tools":
                    found.setdefault("wow-tools", []).append(rel(path))
        self.assertEqual(found.get("wow-tools"), ["wowtools/core/journal.py"])
        self.assertNotIn("#4CC38A", found)  # the theme's success colour comes from KA0S_THEME
        self.assertEqual(len(found.get("86400.0", [])), 1)

    def test_every_button_is_built_with_an_action_kind(self):
        """Only action_button constructs a Button, so every button carries an action kind (spec D12)."""
        offenders = []
        for path in modules("wowtools"):
            module = tree(path)
            builders = {id(n) for f in ast.walk(module)
                        if isinstance(f, ast.FunctionDef) and f.name == "action_button" for n in ast.walk(f)}
            offenders += [f"{rel(path)}:{n.lineno}" for n in ast.walk(module)
                          if isinstance(n, ast.Call) and id(n) not in builders
                          and ((isinstance(n.func, ast.Name) and n.func.id == "Button")
                               or (isinstance(n.func, ast.Attribute) and n.func.attr == "Button"))]
        self.assertEqual(offenders, [])

    def test_footer_and_brand_bar_only_in_the_bottom_bar(self):
        """Screens yield a BottomBar; only it builds the Footer and the BrandBar, in one row (spec D5: docked on
        their own the two overlapped and the brand bar never showed)."""
        offenders = [f"{rel(path)}:{n.lineno}" for path in modules("wowtools") if rel(path) != "wowtools/ui/branding.py"
                     for n in ast.walk(tree(path))
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("Footer", "BrandBar")]
        self.assertEqual(offenders, [])

    def test_same_label_same_colour(self):
        """Every button label in wowtools has one action kind, and the key actions have the kind spec D12 gives
        them. Labels come from action_button(label, kind) calls and from the (…, label, kind, …) tuples that
        result screens, ChoiceScreen and the Ace3 action bar are built from (the label sits just before the kind)."""
        from wowtools.ui.widgets import ACTION_VARIANTS
        kinds: dict[str, set[str]] = {}
        for path in modules("wowtools"):
            for node in ast.walk(tree(path)):
                pairs = []
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "action_button":
                    pairs = [node.args[:2]]
                elif isinstance(node, ast.Tuple):
                    pairs = list(zip(node.elts, node.elts[1:]))
                for label, kind in pairs:
                    if (isinstance(label, ast.Constant) and isinstance(kind, ast.Constant)
                            and kind.value in ACTION_VARIANTS):
                        kinds.setdefault(label.value, set()).add(kind.value)
        # Interface Backup's review screen has a Restore that only opens the restore screen (navigate, grey); the
        # restore screen's Restore overwrites (amber). The left pane has no room for a longer label.
        self.assertEqual({label: k for label, k in kinds.items() if len(k) > 1},
                         {"Restore": {"navigate", "overwrite"}})
        expected = {
            "Clean": "destructive", "Apply": "destructive", "Delete": "destructive", "Leftovers": "destructive",
            "Organize": "overwrite", "Update now": "overwrite", "Assign": "overwrite",
            "Override and continue": "overwrite", "Back up": "create",
            "Undo last clean": "revert", "Undo last run": "revert", "Undo last restore": "revert",
            "Undo last change": "revert", "Undo": "revert", "Put the originals back": "revert",
            "Dry run": "simulate", "Save": "confirm", "OK": "confirm",
            "Rescan": "navigate", "Other flavor": "navigate",
            "Tools": "navigate", "More…": "navigate", "Edit blacklist…": "navigate",
            "Cancel": "cancel", "No": "cancel", "Later": "cancel", "Quit": "cancel", "Back": "cancel",
            "Discard": "cancel", "Back to review": "cancel",
        }
        self.assertEqual({label: next(iter(kinds.get(label, {"missing"}))) for label in expected}, expected)

    def test_button_labels_never_spell_their_key(self):
        """Spec D17: a button's key is given to action_button (`key=`), which shows it on the button and drops it from
        the footer; a label never carries it by hand ("Assign (p)", "Back to review (Esc)"). Labels are found as in
        test_same_label_same_colour."""
        import re
        from wowtools.ui.widgets import ACTION_VARIANTS
        keyed = re.compile(r"\((?:[^()\s]{1,6}|Esc|Space)\)\s*$")
        offenders = []
        for path in modules("wowtools"):
            for node in ast.walk(tree(path)):
                pairs = []
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "action_button":
                    pairs = [node.args[:2]]
                elif isinstance(node, ast.Tuple):
                    pairs = list(zip(node.elts, node.elts[1:]))
                for label, kind in pairs:
                    if (isinstance(label, ast.Constant) and isinstance(label.value, str)
                            and isinstance(kind, ast.Constant) and kind.value in ACTION_VARIANTS
                            and keyed.search(label.value)):
                        offenders.append(f"{rel(path)}:{node.lineno}: {label.value}")
        self.assertEqual(offenders, [])

    def test_every_confirm_names_its_kind(self):
        """Every ConfirmScreen says what its Yes does (spec D13): Yes is focused at the start, so its colour is the
        warning (destructive red for a delete, overwrite, undo or discard; simulate for a dry run)."""
        offenders = []
        for path in modules("wowtools"):
            for node in ast.walk(tree(path)):
                if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ConfirmScreen"
                        and not any(k.arg == "kind" for k in node.keywords)):
                    offenders.append(f"{rel(path)}:{node.lineno}")
                if isinstance(node, ast.keyword) and node.arg == "default_yes":
                    offenders.append(f"{rel(path)}: default_yes")
        self.assertEqual(offenders, [])

    def test_dead_code_is_gone(self):
        from wowtools.core import install
        from wowtools.core.journal import JournalWriter
        from wowtools.core.migrate import FolderMerge
        from wowtools.tools.wtf_cleaner import review_screen, safety
        from wowtools.tools.wtf_cleaner.rules import ProposalItem
        self.assertFalse(hasattr(JournalWriter, "is_open"))
        self.assertFalse(hasattr(FolderMerge, "changed"))
        self.assertFalse(hasattr(ProposalItem, "scope"))
        self.assertFalse(hasattr(install, "InstallError"))
        self.assertFalse(hasattr(safety, "SNAPSHOT_NAME"))
        self.assertFalse(hasattr(safety, "re"))
        self.assertNotIn("ConfirmScreen", review_screen.__all__)  # import it from wowtools.ui.dialogs

    def test_core_never_imports_textual(self):
        """Directly (textual), through a front end (wowtools.ui, wowtools.tools) or through a relative import."""
        banned = ("textual", "wowtools.ui", "wowtools.tools")
        offenders = []
        for path in modules("wowtools/core"):
            module = tree(path)
            offenders += [f"{rel(path)} imports {m}" for m in imported_modules(module)
                          if any(m == b or m.startswith(f"{b}.") for b in banned)]
            offenders += [f"{rel(path)}:{n.lineno} has a relative import" for n in ast.walk(module)
                          if isinstance(n, ast.ImportFrom) and n.level > 0]
        self.assertEqual(sorted(offenders), [])

    def test_importing_core_loads_no_textual(self):
        names = sorted(f"wowtools.core.{p.stem}" for p in modules("wowtools/core") if p.stem != "__init__")
        code = (f"import importlib, sys\nfor n in {names!r}: importlib.import_module(n)\n"
                "print(sorted(m for m in sys.modules if m.split('.')[0] == 'textual' or m.startswith('wowtools.ui')))")
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "[]")

    def test_every_module_has_the_future_import(self):
        missing = []
        for path in modules(*PACKAGES):
            module = tree(path)
            if not any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
                       and any(a.name == "annotations" for a in n.names) for n in module.body):
                missing.append(rel(path))
        self.assertEqual(missing, [])

    def test_wowtools_imports_are_in_order(self):
        """Top-level `from wowtools... import` lines are sorted by module name (isort's order)."""
        unsorted = []
        for path in modules(*PACKAGES):
            names = [n.module for n in tree(path).body
                     if isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "wowtools"]
            if names != sorted(names):
                unsorted.append(rel(path))
        self.assertEqual(unsorted, [])
