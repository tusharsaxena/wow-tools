"""Saved Variables Browser lazy tree model (spec D5, D17, D18): a file is read once and parsed one level at a time,
nodes carry typed keys, spans, paths and what may be edited, a table shows at most CHILD_CAP children, and a file that
can't be read becomes an error node. Plus the display text of keys, scalars and tables."""
from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import SVB_FONT, build_sv_tree
from wowtools.core import luasv
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.luasv import Opaque, RawNumber, Scalar, Table
from wowtools.core.svfiles import SvFile
from wowtools.tools.sv_browser import model
from wowtools.tools.sv_browser.model import CHILD_CAP, SvDocument, key_text, node_text, scalar_text, table_text
from wowtools.tools.sv_browser.scanner import scan_flavors


def by_key(nodes, key):
    return next(n for n in nodes if n.key == key and type(n.key) is type(key))


class ModelTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_sv_tree(self.tmp / "wow")
        self.retail = WowInstall(self.root).flavor("_retail_")
        self.files = scan_flavors([self.retail]).files()

    def doc(self, name, owner="Account-wide", account="ACCT1"):
        sv = next(f for f in self.files if f.path.name == name and f.owner == owner and f.account == account)
        return SvDocument(sv)

    def walk(self, doc, *keys):
        nodes = doc.roots()
        node = None
        for key in keys:
            node = by_key(nodes, key)
            nodes = doc.children(node) if node.is_table else []
        return node

    def test_nothing_is_read_until_the_roots_are_asked_for(self):
        doc = self.doc("ElvUI.lua")
        self.assertFalse(doc.loaded)
        self.assertIsNone(doc.data)
        self.assertIsNone(doc.sha256)

    def test_top_level_assignments_in_file_order(self):
        doc = self.doc("ElvUI.lua")
        roots = doc.roots()
        self.assertEqual([n.key for n in roots], ["ElvDB", "ElvPrivateDB", "ElvVersion"])
        self.assertTrue(all(n.top_level and n.parent is None for n in roots))
        self.assertEqual([n.path for n in roots], [("ElvDB",), ("ElvPrivateDB",), ("ElvVersion",)])
        self.assertEqual([n.count for n in roots], [1, 1, None])
        version = roots[2]
        self.assertIsInstance(version.value, Scalar)
        self.assertIsNone(version.value.value)
        self.assertEqual(doc.data[version.key_span[0]:version.key_span[1]], b"ElvVersion")

    def test_file_is_read_once_and_its_hash_recorded(self):
        doc = self.doc("ElvUI.lua")
        real = Path.read_bytes
        calls = []

        def counting(path):
            calls.append(path)
            return real(path)

        with mock.patch.object(Path, "read_bytes", counting):
            self.walk(doc, "ElvDB", "profiles", "Default", "unitframe", "Font")
            self.walk(doc, "ElvPrivateDB", "install_complete")
        self.assertEqual(len(calls), 1)
        self.assertEqual(doc.sha256, hashlib.sha256(doc.file.path.read_bytes()).hexdigest())

    def test_tables_load_lazily_one_span_at_a_time(self):
        doc = self.doc("ElvUI.lua")
        elv = doc.roots()[0]
        self.assertIsNone(elv.children)
        self.assertIsInstance(elv.value.fields[0].value, Opaque)  # its children's contents are not parsed yet
        tables = sum(isinstance(f.value, Opaque) for f in elv.value.fields)
        with mock.patch.object(model, "parse_at", wraps=luasv.parse_at) as parse_at:
            profiles = by_key(doc.children(elv), "profiles")
            doc.children(elv)  # cached: no second parse
        # the table's span, then each child table's span (for its size)
        self.assertEqual(parse_at.call_count, 1 + tables)
        self.assertEqual(parse_at.call_args_list[0].args[1:3], (elv.value.start, ("ElvDB",)))
        self.assertEqual(parse_at.call_args_list[1].args[2], ("ElvDB", "profiles"))
        self.assertEqual((profiles.path, profiles.count, profiles.children), (("ElvDB", "profiles"), 1, None))
        self.assertIs(profiles.parent, elv)

    def test_typed_keys_spans_and_paths(self):
        doc = self.doc("ElvUI.lua")
        unitframe = self.walk(doc, "ElvDB", "profiles", "Default", "unitframe")
        kids = doc.children(unitframe)
        self.assertEqual([n.typed_key for n in kids], [("str", "Font"), ("str", "barFont"), ("int", 1), ("int", 2),
                                                    ("bool", True), ("bool", False)])
        font = kids[0]
        self.assertEqual(font.path, ("ElvDB", "profiles", "Default", "unitframe", "Font"))
        self.assertEqual(doc.data[font.key_span[0]:font.key_span[1]], b'["Font"]')
        self.assertEqual(doc.data[font.value.start:font.value.end], f'"{SVB_FONT}"'.encode())
        self.assertEqual(font.value.value, SVB_FONT)
        self.assertEqual(by_key(kids, 2).value.value, 2.5)
        self.assertEqual(by_key(kids, True).value.value, "yes")
        self.assertEqual(by_key(kids, False).value.value, 0)
        start, end = font.remove_span
        self.assertEqual(doc.data[start:end], f'["Font"] = "{SVB_FONT}",\r\n'.encode())

    def test_editable_per_d5(self):
        doc = self.doc("Details.lua")
        top_table, top_scalar = by_key(doc.roots(), "_detalhes_global"), by_key(doc.roots(), "DetailsVersion")
        self.assertEqual((top_table.can_edit_value, top_table.can_rename, top_table.can_delete), (False,) * 3)
        self.assertEqual((top_scalar.can_edit_value, top_scalar.can_rename, top_scalar.can_delete),
                         (True, False, False))
        font = self.walk(doc, "_detalhes_global", "font_face")
        self.assertEqual((font.can_edit_value, font.can_rename, font.can_delete), (True, True, True))
        tooltip = self.walk(doc, "_detalhes_global", "tooltip")
        self.assertEqual((tooltip.can_edit_value, tooltip.can_rename, tooltip.can_delete), (False, True, True))
        bars = doc.children(self.walk(doc, "_detalhes_global", "bars"))
        self.assertEqual([n.key for n in bars], [1, 2, 3])
        self.assertTrue(all(n.positional and n.key_span is None for n in bars))
        self.assertIsNone(bars[1].value.value)  # the nil slot
        self.assertEqual((bars[0].can_edit_value, bars[0].can_rename, bars[0].can_delete), (True, False, True))
        written = self.walk(self.doc("ElvUI.lua"), "ElvDB", "profiles", "Default", "unitframe", 1)
        self.assertFalse(written.positional)
        self.assertTrue(written.can_rename)

    def test_top_level_nil_is_value_editable(self):
        version = by_key(self.doc("ElvUI.lua").roots(), "ElvVersion")
        self.assertTrue(version.can_edit_value)
        self.assertFalse(version.can_delete)

    def test_broken_file_is_one_error_node_and_never_raises(self):
        doc = self.doc("Broken.lua")
        with capture_events() as events:
            roots = doc.roots()
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].kind, "error")
        self.assertIsNotNone(doc.error)
        self.assertIn("not readable Lua", roots[0].error)
        self.assertEqual((roots[0].can_edit_value, roots[0].can_rename, roots[0].can_delete), (False,) * 3)
        self.assertIsNotNone(doc.sha256)
        self.assertIn("svb.file_unreadable", [e["event"] for e in events])
        self.assertIs(doc.roots(), roots)

    def test_missing_file_is_an_error_node(self):
        doc = self.doc("Details.lua")
        doc.file.path.unlink()
        with capture_events() as events:
            roots = doc.roots()
        self.assertEqual(roots[0].kind, "error")
        self.assertIn("could not read", roots[0].error)
        self.assertIsNone(doc.sha256)
        self.assertIn("svb.file_unreadable", [e["event"] for e in events])

    def test_a_fault_inside_a_table_is_an_error_child(self):
        path = self.retail.account_dir / "ACCT1" / "SavedVariables" / "Inner.lua"
        path.write_bytes(b'Inner = {\r\n["a"] = {\r\n["b"] = = 1,\r\n},\r\n["ok"] = 1,\r\n}\r\nAfter = 2\r\n')
        doc = SvDocument(SvFile(path, self.retail, "ACCT1", None, path.stat().st_size, 0.0, ""))
        inner = doc.roots()[0]
        self.assertIsNone(doc.error)
        with capture_events():
            kids = doc.children(inner)
        self.assertEqual([n.kind for n in kids], ["error"])
        self.assertEqual(doc.roots()[1].key, "After")

    def test_children_of_a_scalar_or_error_are_empty(self):
        doc = self.doc("ElvUI.lua")
        self.assertEqual(doc.children(by_key(doc.roots(), "ElvVersion")), [])


class CapAndSizeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = build_sv_tree(Path(tmp.name) / "wow")
        self.retail = WowInstall(self.root).flavor("_retail_")

    def write(self, name, data):
        path = self.retail.account_dir / "ACCT1" / "SavedVariables" / name
        path.write_bytes(data)
        return SvDocument(SvFile(path, self.retail, "ACCT1", None, len(data), 0.0, ""))

    def test_more_than_cap_children_show_the_first_and_a_more_leaf(self):
        lines = [b"Big = {"] + [b'"v%d", -- [%d]' % (i, i) for i in range(1, CHILD_CAP + 1501)] + [b"}"]
        doc = self.write("Big.lua", b"\r\n".join(lines) + b"\r\n")
        big = doc.roots()[0]
        self.assertEqual(big.count, CHILD_CAP + 1500)
        kids = doc.children(big)
        self.assertEqual(len(kids), CHILD_CAP + 1)
        self.assertEqual([n.key for n in kids[:3]], [1, 2, 3])
        more = kids[-1]
        self.assertEqual((more.kind, more.more), ("more", 1500))
        self.assertEqual(node_text(more, doc.data), "… 1,500 more")
        self.assertEqual((more.can_edit_value, more.can_rename, more.can_delete, more.is_table), (False,) * 4)

    def test_only_the_shown_children_tables_are_built(self):
        # M2 review: opening a table builds the tables of the CHILD_CAP children it shows, never the rest
        lines = [b"Big = {"] + [b'["k%d"] = {"a", {"b"}},' % i for i in range(1, 11)] + [b"}"]
        doc = self.write("Kids.lua", b"\r\n".join(lines) + b"\r\n")
        big = doc.roots()[0]
        with mock.patch.object(model, "CHILD_CAP", 3):
            kids = doc.children(big)
        self.assertEqual([n.kind for n in kids], ["value"] * 3 + ["more"])
        self.assertEqual(kids[-1].more, 7)
        self.assertEqual([n.count for n in kids[:3]], [2, 2, 2])
        self.assertTrue(all(isinstance(n.value.fields[1].value, Opaque) for n in kids[:3]))
        self.assertEqual(big.count, 10)
        self.assertTrue(all(isinstance(f.value, Opaque) for f in big.value.fields[3:]))
        self.assertEqual([n.count for n in doc.children(kids[0])], [None, 1])

    def test_huge_file_loads_its_top_level_fast(self):
        entry = (b'[%d] = {\r\n["name"] = "Aura number %d",\r\n["load"] = {\r\n["class"] = {\r\n["WARRIOR"] = true,'
                 b'\r\n},\r\n["size"] = 12.5,\r\n},\r\n["text"] = "' + b"x" * 120 + b'",\r\n},\r\n')
        body = b"".join(entry % (i, i) for i in range(20000))
        data = b"WeakAurasSaved = {\r\n[\"displays\"] = {\r\n" + body + b"},\r\n}\r\nOther = 1\r\n"
        self.assertGreater(len(data), 5_000_000)
        doc = self.write("WeakAuras.lua", data)
        started = time.monotonic()
        roots = doc.roots()
        loaded = time.monotonic() - started
        self.assertEqual([n.key for n in roots], ["WeakAurasSaved", "Other"])
        self.assertIsInstance(roots[0].value.fields[0].value, Opaque)  # displays not built at load
        self.assertLess(loaded, 3.0)
        displays = doc.children(roots[0])[0]
        self.assertEqual(displays.count, 20000)
        kids = doc.children(displays)
        self.assertEqual(len(kids), CHILD_CAP + 1)
        self.assertIsInstance(kids[0].value, Table)
        self.assertIsInstance(kids[0].value.fields[1].value, Opaque)  # an aura's own tables wait for their expand


class DisplayTextTest(unittest.TestCase):
    def test_key_text(self):
        self.assertEqual([key_text(k) for k in ("font", 5, True, False, 2.5, "")],
                         ["font", "[5]", "[true]", "[false]", "[2.5]", '[""]'])
        self.assertEqual(key_text("a\nb"), "a\\nb")

    def test_scalar_text(self):
        self.assertEqual(scalar_text(SVB_FONT), f'"{SVB_FONT}"')
        self.assertEqual(scalar_text('a"b\\c\n—'), '"a\\"b\\\\c\\n—"')
        self.assertEqual(scalar_text("bad \udcff byte"), '"bad \\255 byte"')
        self.assertEqual([scalar_text(v) for v in (True, False, None, 4, 2.5)], ["true", "false", "nil", "4", "2.5"])
        self.assertEqual(scalar_text(0.6000000000000001, raw=b"0.6000000000000001"), "0.6000000000000001")
        self.assertEqual(scalar_text(1.0, raw=b"1.00"), "1.00")  # numbers as written
        self.assertEqual(scalar_text(RawNumber("1.#INF")), "1.#INF")

    def test_long_strings_are_cut_with_an_ellipsis(self):
        text = scalar_text("x" * 100, width=20)
        self.assertEqual(len(text), 20)
        self.assertEqual(text, '"' + "x" * 17 + '…"')
        self.assertEqual(scalar_text("x" * 18, width=20), '"' + "x" * 18 + '"')
        self.assertLessEqual(len(scalar_text("y" * 10_000)), model.VALUE_WIDTH)

    def test_table_text(self):
        self.assertEqual((table_text(3), table_text(0), table_text(1234), table_text(None)),
                         ("{3}", "{0}", "{1,234}", "{…}"))

    def test_node_text(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_sv_tree(Path(tmp.name) / "wow")
        retail = WowInstall(root).flavor("_retail_")
        files = scan_flavors([retail]).files()
        doc = SvDocument(next(f for f in files if f.path.name == "ElvUI.lua" and f.character is None))
        roots = doc.roots()
        self.assertEqual([node_text(n, doc.data) for n in roots], ["ElvDB {1}", "ElvPrivateDB {1}", "ElvVersion = nil"])
        private = doc.children(roots[1])[0]
        self.assertEqual(node_text(private, doc.data), "install_complete = 13.52")
        general = doc.children(doc.children(doc.children(roots[0])[0])[0])[0]
        self.assertEqual([node_text(n, doc.data) for n in doc.children(general)],
                         [f'font = "{SVB_FONT}"', "fontSize = 12", "scale = 0.6000000000000001", "autoRepair = true"])
        broken = SvDocument(next(f for f in files if f.path.name == "Broken.lua"))
        with capture_events():
            self.assertTrue(node_text(broken.roots()[0], broken.data).startswith("can't read: "))


if __name__ == "__main__":
    unittest.main()
