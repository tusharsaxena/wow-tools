"""luasv: the SavedVariables reader with byte spans (spec §5.1)."""
from __future__ import annotations

import time
import unittest

from wowtools.core import luasv
from wowtools.core.luasv import LuaParseError, Opaque, Table

CRLF_FILE = (b'\r\nKickCDDB = {\r\n["profileKeys"] = {\r\n["Ka\xc3\xa2los - Mug\'thol"] = "Default",\r\n'
             b'["Alt - Khaz Modan"] = "Default",\r\n},\r\n["profiles"] = {\r\n["Default"] = {\r\n'
             b'["scale"] = 0.6000000000000001,\r\n["tiny"] = 8e-05,\r\n["text"] = "a\\"b\\\\c\\n\\000",\r\n'
             b'[114052] = true,\r\n["arr"] = {\r\n"TOP",\r\nnil,\r\n"TOP",\r\n},\r\n},\r\n["Empty"] = {\r\n},\r\n},\r\n'
             b'}\r\nKickCDPerfDB = {\r\n["runs"] = 3,\r\n}\r\n')


class ParseTest(unittest.TestCase):
    def test_top_level_assignments(self):
        chunk = luasv.parse(CRLF_FILE)
        self.assertEqual([a.name for a in chunk.assignments], ["KickCDDB", "KickCDPerfDB"])
        db = chunk.get("KickCDDB")
        self.assertEqual(CRLF_FILE[db.start:db.start + 8], b"KickCDDB")
        self.assertEqual(CRLF_FILE[db.end - 1:db.end], b"}")

    def test_keys_values_and_spans(self):
        db = luasv.parse(CRLF_FILE).get("KickCDDB").value
        keys = db.get("profileKeys").value
        self.assertIsInstance(keys, Table)
        self.assertEqual(keys.keys(), ["Kaâlos - Mug'thol", "Alt - Khaz Modan"])
        field = keys.get("Alt - Khaz Modan")
        self.assertEqual(CRLF_FILE[field.key_span[0]:field.key_span[1]], b'["Alt - Khaz Modan"]')
        self.assertEqual(CRLF_FILE[field.value.start:field.value.end], b'"Default"')
        self.assertEqual(field.value.value, "Default")
        start, end = field.remove_span
        self.assertEqual(CRLF_FILE[start:end], b'["Alt - Khaz Modan"] = "Default",\r\n')

    def test_scalars(self):
        default = luasv.parse(CRLF_FILE).get("KickCDDB").value.get("profiles").value.get("Default").value
        self.assertEqual(default.get("scale").value.value, 0.6000000000000001)
        self.assertEqual(default.get("tiny").value.value, 8e-05)
        self.assertEqual(default.get("text").value.value, 'a"b\\c\n\x00')
        self.assertIs(default.get(114052).value.value, True)
        arr = default.get("arr").value
        self.assertEqual([f.key for f in arr.fields], [1, 2, 3])
        self.assertEqual([f.value.value for f in arr.fields], ["TOP", None, "TOP"])
        self.assertIsNone(arr.fields[0].key_span)

    def test_selective_depth_makes_opaque_values(self):
        def descend(path):
            return len(path) <= 2
        profiles = luasv.parse(CRLF_FILE, descend).get("KickCDDB").value.get("profiles").value
        default = profiles.get("Default").value
        self.assertIsInstance(default, Opaque)
        self.assertEqual(CRLF_FILE[default.start:default.start + 1], b"{")
        self.assertEqual(CRLF_FILE[default.end - 1:default.end], b"}")
        self.assertTrue(luasv.is_blank_table(CRLF_FILE, profiles.get("Empty").value))
        self.assertFalse(luasv.is_blank_table(CRLF_FILE, default))

    def test_opaque_skip_ignores_braces_in_strings_and_comments(self):
        data = b'X = {\n["a"] = {\n["s"] = "}{\\"}",\n-- }\n--[[ } ]]\n["t"] = \'}\',\n},\n["b"] = 1,\n}\n'
        x = luasv.parse(data, lambda path: len(path) == 1).get("X").value
        self.assertEqual(x.keys(), ["a", "b"])
        self.assertEqual(x.get("b").value.value, 1)

    def test_name_keys_semicolons_comments_and_single_quotes(self):
        data = b"-- header\nX = { a = 1; ['b'] = 'q\\'s', [-2] = -3.5e2, c = 0x1F, d = 1.#INF } -- tail\n"
        x = luasv.parse(data).get("X").value
        self.assertEqual(x.keys(), ["a", "b", -2, "c", "d"])
        self.assertEqual(x.get("b").value.value, "q's")
        self.assertEqual(x.get(-2).value.value, -350.0)
        self.assertEqual(x.get("c").value.value, 31)
        self.assertEqual(x.get("d").value.value, luasv.RawNumber("1.#INF"))

    def test_decimal_and_hex_escapes_and_utf8(self):
        self.assertEqual(luasv.decode_string(b'"\\104\\x69 \\195\\162"'), "hi â")
        self.assertEqual(luasv.decode_string(b'"Tr\xc3\xa2xex"'), "Trâxex")

    def test_invalid_utf8_round_trips(self):
        text = luasv.decode_string(b'"\xff\xfe"')
        self.assertEqual(luasv.encode_string(text), b'"\xff\xfe"')

    def test_errors_have_offsets(self):
        for bad in (b"X = {", b"X = {[1 = 2}", b'X = "open', b"X = {} Y", b"= 1", b"X = {a 1}"):
            with self.subTest(bad=bad), self.assertRaises(LuaParseError) as caught:
                luasv.parse(bad)
            self.assertGreaterEqual(caught.exception.offset, 0)

    def test_remove_span_covers_indented_line(self):
        data = b"X = {\n    [\"a\"] = 1,\n    [\"b\"] = 2,\n}\n"
        field = luasv.parse(data).get("X").value.get("a")
        start, end = field.remove_span
        self.assertEqual(data[start:end], b'    ["a"] = 1,\n')

    def test_remove_span_of_entry_sharing_a_line(self):
        data = b'X = { ["a"] = 1, ["b"] = 2 }\n'
        field = luasv.parse(data).get("X").value.get("a")
        start, end = field.remove_span
        self.assertEqual(data[start:end], b'["a"] = 1,')


class CodecTest(unittest.TestCase):
    def test_encode_escapes(self):
        self.assertEqual(luasv.encode_string('a"b\\c\nd\re\x01'), b'"a\\"b\\\\c\\nd\\re\\001"')
        self.assertEqual(luasv.encode_string("Kaâlos - Mug'thol"), b'"Ka\xc3\xa2los - Mug\'thol"')

    def test_round_trip(self):
        for text in ("", "Default", 'x"y', "tab\tnew\nline", "\x00\x7f", "Ishtâr - Khaz Modan"):
            with self.subTest(text=text):
                self.assertEqual(luasv.decode_string(luasv.encode_string(text)), text)


class SpliceTest(unittest.TestCase):
    def test_no_edits_is_identity(self):
        self.assertEqual(luasv.splice(CRLF_FILE, []), CRLF_FILE)

    def test_replace_remove_insert(self):
        data = b"0123456789"
        self.assertEqual(luasv.splice(data, [(1, 3, b"AB"), (5, 7, b""), (9, 9, b"!")]), b"0AB3478!9")

    def test_insert_at_end_of_removed_span(self):
        self.assertEqual(luasv.splice(b"abcdef", [(1, 3, b""), (3, 3, b"X")]), b"aXdef")

    def test_overlap_is_refused(self):
        with self.assertRaises(ValueError):
            luasv.splice(b"abcdef", [(1, 4, b""), (3, 5, b"")])

    def test_newline_and_line_start(self):
        self.assertEqual(luasv.newline_of(CRLF_FILE), b"\r\n")
        self.assertEqual(luasv.newline_of(b"X = {\n}\n"), b"\n")
        data = b"ab\ncd"
        self.assertEqual(luasv.line_start(data, 4), 3)
        self.assertEqual(luasv.line_start(data, 1), 0)


class SpeedTest(unittest.TestCase):
    def test_large_file_with_selective_depth_is_fast(self):
        profile = b'["x"] = {\n' + b''.join(b'["k%d"] = {\n["v"] = "s}",\n[1] = 0.5,\n},\n' % i
                                         for i in range(400)) + b'},\n'
        body = b"".join(b'["P%d"] = {\n%s},\n' % (i, profile) for i in range(250))
        data = b"BigDB = {\n[\"profileKeys\"] = {\n[\"A - B\"] = \"P1\",\n},\n[\"profiles\"] = {\n" + body + b"},\n}\n"
        self.assertGreater(len(data), 3_000_000)

        def descend(path):
            return len(path) <= 2
        started = time.perf_counter()
        chunk = luasv.parse(data, descend)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(chunk.get("BigDB").value.get("profiles").value.fields), 250)
        self.assertLess(elapsed, 5.0)


WOW_FILE = (b'\r\nMyAddonDB = {\r\n\t["name"] = "Ka\\"0s\\\\ \\104i",\r\n\t["count"] = 3,\r\n\t["scale"] = 0.1,\r\n'
            b'\t["inf"] = 1.#INF,\r\n\t["off"] = false,\r\n\t[5] = true,\r\n\t[true] = "t",\r\n\t[1.5] = "f",\r\n'
            b'\tbare = \'single\',\r\n\t--[[ a long\r\n comment with "quotes" and { braces ]]\r\n'
            b'\t["list"] = {\r\n\t\t"a", -- [1]\r\n\t\tnil, -- [2]\r\n\t\t"c", -- [3]\r\n\t},\r\n'
            b'\t["nested"] = {\r\n\t\t["deep"] = {\r\n\t\t\t["leaf"] = -2e-05,\r\n\t\t},\r\n\t\t["empty"] = {\r\n\t\t},\r\n'
            b'\t},\r\n}\r\nMyAddonVersion = 12\r\nMyAddonNil = nil\r\n')


def from_parse(data, descend=lambda path: True):
    """What iter_scalars should yield, built from parse()."""
    out = []

    def walk(table, path):
        for item in table.fields:
            if isinstance(item.value, Table):
                walk(item.value, path + (item.key,))
            elif isinstance(item.value, luasv.Scalar):
                out.append((path, item.key, item.key_span, item.value))
    for assignment in luasv.parse(data, descend).assignments:
        if isinstance(assignment.value, Table):
            walk(assignment.value, (assignment.name,))
        elif isinstance(assignment.value, luasv.Scalar):
            name_end = assignment.start + len(assignment.name)
            out.append(((), assignment.name, (assignment.start, name_end), assignment.value))
    return out


class ParseAtTest(unittest.TestCase):
    def test_parses_a_table_at_its_offset(self):
        x = luasv.parse(WOW_FILE, lambda path: len(path) <= 1).get("MyAddonDB").value
        opaque = x.get("nested").value
        self.assertIsInstance(opaque, Opaque)
        value, end = luasv.parse_at(WOW_FILE, opaque.start, ("MyAddonDB", "nested"))
        self.assertIsInstance(value, Table)
        self.assertEqual((value.start, value.end, end), (opaque.start, opaque.end, opaque.end))
        self.assertEqual(value.get("deep").value.get("leaf").value.value, -2e-05)
        self.assertEqual(value.keys(), ["deep", "empty"])

    def test_descend_gets_full_paths(self):
        seen = []
        opaque = luasv.parse(WOW_FILE, lambda path: len(path) <= 1).get("MyAddonDB").value.get("nested").value

        def descend(path):
            seen.append(path)
            return len(path) <= 2
        value, _ = luasv.parse_at(WOW_FILE, opaque.start, ("MyAddonDB", "nested"), descend)
        self.assertEqual(seen, [("MyAddonDB", "nested"), ("MyAddonDB", "nested", "deep"),
                                ("MyAddonDB", "nested", "empty")])
        self.assertIsInstance(value.get("deep").value, Opaque)

    def test_scalar_and_leading_whitespace(self):
        start = WOW_FILE.index(b"= 12") + 1
        value, end = luasv.parse_at(WOW_FILE, start)
        self.assertEqual((value.value, WOW_FILE[value.start:end]), (12, b"12"))

    def test_bad_offset_raises(self):
        with self.assertRaises(LuaParseError):
            luasv.parse_at(WOW_FILE, WOW_FILE.index(b"}\r\nMyAddonVersion"))


class IterScalarsTest(unittest.TestCase):
    def test_matches_parse_on_a_wow_file(self):
        got = list(luasv.iter_scalars(WOW_FILE))
        self.assertEqual(got, from_parse(WOW_FILE))
        by_key = {(path, key): scalar.value for path, key, _, scalar in got}
        self.assertEqual(by_key[(("MyAddonDB",), "name")], 'Ka"0s\\ hi')
        self.assertEqual(by_key[(("MyAddonDB",), "inf")], luasv.RawNumber("1.#INF"))
        self.assertEqual(by_key[(("MyAddonDB",), "bare")], "single")
        self.assertEqual(by_key[(("MyAddonDB",), True)], "t")
        self.assertEqual(by_key[(("MyAddonDB", "list"), 2)], None)
        self.assertEqual(by_key[(("MyAddonDB", "nested", "deep"), "leaf")], -2e-05)
        self.assertEqual(by_key[((), "MyAddonVersion")], 12)
        self.assertIn(((), "MyAddonNil"), by_key)

    def test_keys_keep_their_types_and_spans(self):
        got = {(path, key): (span, type(key)) for path, key, span, _ in luasv.iter_scalars(WOW_FILE)}
        span, kind = got[(("MyAddonDB",), 5)]
        self.assertEqual((WOW_FILE[span[0]:span[1]], kind), (b"[5]", int))
        span, kind = got[(("MyAddonDB",), True)]
        self.assertEqual((WOW_FILE[span[0]:span[1]], kind), (b"[true]", bool))
        self.assertEqual(WOW_FILE[slice(*got[(("MyAddonDB",), "bare")][0])], b"bare")
        self.assertEqual(got[(("MyAddonDB", "list"), 1)][0], None)
        self.assertEqual(WOW_FILE[slice(*got[((), "MyAddonVersion")][0])], b"MyAddonVersion")

    def test_descend_skips_tables(self):
        def descend(path):
            return path != ("MyAddonDB", "nested")
        got = list(luasv.iter_scalars(WOW_FILE, descend))
        self.assertEqual(got, from_parse(WOW_FILE, descend))
        self.assertFalse([p for p, *_ in got if p[:2] == ("MyAddonDB", "nested")])

    def test_matches_parse_on_the_ace_file(self):
        self.assertEqual(list(luasv.iter_scalars(CRLF_FILE)), from_parse(CRLF_FILE))

    def test_odd_syntax(self):
        data = (b"X = { 1, 2; [\"a\"] = 'it''s', 0x1F, -.5, 1e3, -nan(ind), b = { { 7 } }, }; Y = -3\n"
                b"Z = {--[==[ ]] } ]==] [\"k\"] = \"--[[ not a comment\", -- {\n}\n")
        data = data.replace(b"'it''s'", b"'it\\'s'")
        self.assertEqual(list(luasv.iter_scalars(data)), from_parse(data))
        values = [s.value for *_, s in luasv.iter_scalars(data)]
        self.assertIn("it's", values)
        self.assertIn(luasv.RawNumber("-nan(ind)"), values)
        self.assertIn("--[[ not a comment", values)

    def test_errors_like_parse(self):
        for bad in (b"X = {", b"X = {[1 = 2}", b'X = "open', b"X = {} Y", b"= 1", b"X = {a 1}", b"X = {[{}] = 1}"):
            with self.subTest(bad=bad), self.assertRaises(LuaParseError):
                list(luasv.iter_scalars(bad))

    def test_is_lazy(self):
        data = b"A = 1\nB = {\n"  # broken after the first scalar
        stream = luasv.iter_scalars(data)
        self.assertEqual(next(stream)[1], "A")
        with self.assertRaises(LuaParseError):
            next(stream)

    def test_streams_a_big_file_quickly(self):
        rows = b"".join(b'["k%d"] = {\n["v"] = "s}",\n[1] = 0.5,\n"x", -- [2]\n},\n' % i for i in range(60000))
        data = b"BigDB = {\n" + rows + b"}\n"
        started = time.perf_counter()
        count = sum(1 for _ in luasv.iter_scalars(data))
        self.assertEqual(count, 180000)
        self.assertLess(time.perf_counter() - started, 10.0)


class EncodeTest(unittest.TestCase):
    def test_encode_value(self):
        cases = [("a\"b", b'"a\\"b"'), (True, b"true"), (False, b"false"), (5, b"5"), (-12, b"-12"),
                 (0.1, b"0.1"), (0.6000000000000001, b"0.6000000000000001"), (1e300, b"1e+300"), (2.0, b"2.0"),
                 (luasv.RawNumber("1.#INF"), b"1.#INF")]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(luasv.encode_value(value), expected)

    def test_encoded_values_read_back(self):
        for value in ("x\ny", True, False, 7, -3, 0.1, 1e-05, 123456789.123, luasv.RawNumber("-nan(ind)")):
            with self.subTest(value=value):
                got = luasv.parse(b"X = " + luasv.encode_value(value)).get("X").value.value
                self.assertEqual((got, type(got)), (value, type(value)))

    def test_refuses_what_lua_cannot_read_back(self):
        for value in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                luasv.encode_value(value)
        with self.assertRaises(ValueError):
            luasv.encode_value(None)
        with self.assertRaises(TypeError):
            luasv.encode_value([1])

    def test_encode_key_is_always_bracketed(self):
        cases = [("s", b'["s"]'), ("end", b'["end"]'), ("a b", b'["a b"]'), (5, b"[5]"), (1.5, b"[1.5]"),
                 (True, b"[true]"), (False, b"[false]")]
        for key, expected in cases:
            with self.subTest(key=key):
                self.assertEqual(luasv.encode_key(key), expected)
                table = luasv.parse(b"X = {" + expected + b" = 1}").get("X").value
                self.assertEqual(table.keys(), [key])
                self.assertIs(type(table.keys()[0]), type(key))
        for bad in (None, float("nan"), float("inf")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                luasv.encode_key(bad)

    def test_key_id_keeps_types_apart(self):
        ids = {luasv.key_id(k) for k in (1, True, "1", 1.5)}
        self.assertEqual(len(ids), 4)
        self.assertNotEqual(luasv.key_id(1), luasv.key_id(True))
        self.assertNotEqual(luasv.key_id(0), luasv.key_id(False))
        self.assertEqual(luasv.key_id(1.0), luasv.key_id(1))  # Lua folds [1.0] into [1]
        self.assertEqual(luasv.key_id("a"), ("str", "a"))


class RemoveSpanCommentTest(unittest.TestCase):
    def test_array_entry_takes_its_index_comment(self):
        data = b'X = {\r\n\t"a", -- [1]\r\n\t"b", -- [2]\r\n\t"c", -- [3]\r\n}\r\n'
        field = luasv.parse(data).get("X").value.get(2)
        new = luasv.splice(data, [(*field.remove_span, b"")])
        self.assertEqual(new, b'X = {\r\n\t"a", -- [1]\r\n\t"c", -- [3]\r\n}\r\n')
        self.assertEqual(luasv.parse(new).get("X").value.keys(), [1, 2])

    def test_lf_and_nil_entry(self):
        data = b'X = {\n  nil, -- [1]\n  "b", -- [2]\n}\n'
        field = luasv.parse(data).get("X").value.get(1)
        self.assertEqual(data[slice(*field.remove_span)], b"  nil, -- [1]\n")

    def test_a_long_comment_is_never_cut(self):
        data = b'X = {\n  "a", --[[ starts\n ends ]]\n  "b",\n}\n'
        field = luasv.parse(data).get("X").value.get(1)
        self.assertEqual(data[slice(*field.remove_span)], b'"a",')
        luasv.parse(luasv.splice(data, [(*field.remove_span, b"")]))

    def test_entry_sharing_its_line_keeps_the_comment(self):
        data = b'X = { "a", "b", -- [2]\n}\n'
        field = luasv.parse(data).get("X").value.get(2)
        self.assertEqual(data[slice(*field.remove_span)], b'"b",')


class SlotsTest(unittest.TestCase):
    def test_parse_objects_have_slots(self):
        for cls in (luasv.Scalar, luasv.Opaque, luasv.Field, luasv.Table, luasv.Assignment, luasv.Chunk):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(hasattr(cls, "__slots__"))
                self.assertFalse(hasattr(cls(*([0] * _arity(cls))), "__dict__"))


def _arity(cls):
    return {"Scalar": 3, "Opaque": 2, "Field": 6, "Table": 2, "Assignment": 4, "Chunk": 0}[cls.__name__]
