"""Structure rules from CLAUDE.md and the 2026-10-04 review (F-009, F-023, F-024), checked on the source itself so
they cannot drift again: no tool imports another tool, shared dialogs and helpers live in one place, dead code
stays gone, one definition of the data folder name, and every module has the future import."""
from __future__ import annotations

import ast
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
                for other in tools:
                    if other != name and any(m.startswith(f"wowtools.tools.{other}")
                                             for m in imported_modules(tree(path))):
                        offenders.append(f"{rel(path)} imports wowtools.tools.{other}")
        self.assertEqual(offenders, [])

    def test_shared_helpers_are_defined_once(self):
        names = {"_safe_progress", "safe_progress", "_remove", "_discard", "remove_quietly"}
        where = {(rel(p), n) for p in modules("wowtools") for n in defined_functions(tree(p)) & names}
        self.assertEqual(where, {("wowtools/core/fsutil.py", "safe_progress"),
                                 ("wowtools/core/fsutil.py", "remove_quietly")})

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
        offenders = sorted(f"{rel(p)} imports {m}" for p in modules("wowtools/core") for m in imported_modules(tree(p))
                           if m == "textual" or m.startswith("textual."))
        self.assertEqual(offenders, [])

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
