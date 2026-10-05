"""luasv: the SavedVariables reader with byte spans (spec §5.1)."""
from __future__ import annotations

import time
import unittest

from wowtools.tools.ace3_profile_manager import luasv
from wowtools.tools.ace3_profile_manager.luasv import LuaParseError, Opaque, Table

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
