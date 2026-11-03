"""cvarfile: the byte-exact config-cache.wtf / Config.wtf reader and writer (config tools spec CC5, CE5, CE8)."""
from __future__ import annotations

import unittest

from tests.fixtures import cvar_file_bytes
from wowtools.core.cvarfile import apply_cvar_changes, parse_cvars

SAMPLE = cvar_file_bytes([("cameraDistanceMaxZoomFactor", "2.6"), ("nameplateShowEnemies", "1"),
                          ("hardTrackedQuests", "78463,78464"), ("Sound_MasterVolume", "0.4")])


class ParseTest(unittest.TestCase):
    def test_parse_lines_and_spans(self):
        parsed = parse_cvars(SAMPLE)
        self.assertEqual(parsed.newline, b"\r\n")
        self.assertEqual([(c.name, c.value) for c in parsed.lines],
                         [("cameraDistanceMaxZoomFactor", "2.6"), ("nameplateShowEnemies", "1"),
                          ("hardTrackedQuests", "78463,78464"), ("Sound_MasterVolume", "0.4")])
        first = parsed.lines[0]
        self.assertEqual(SAMPLE[first.span[0]:first.span[1]], b'SET cameraDistanceMaxZoomFactor "2.6"\r\n')
        self.assertEqual(parsed.get("nameplateShowEnemies"), "1")
        self.assertEqual(parsed.get("NAMEPLATESHOWENEMIES"), "1")  # the client reads CVar names in any case
        self.assertIsNone(parsed.get("missing"))

    def test_other_lines_kept_not_listed(self):
        data = b'# comment\nSET a "1"\n\nSETX b "2"\nSET broken\nSET c "3"'
        parsed = parse_cvars(data)
        self.assertEqual(parsed.newline, b"\n")
        self.assertEqual([(c.name, c.value) for c in parsed.lines], [("a", "1"), ("c", "3")])
        self.assertEqual(parsed.lines[-1].span, (len(data) - 9, len(data)))  # an unterminated last line
        self.assertEqual(apply_cvar_changes(data, parsed, {}, ()), data)

    def test_duplicate_reads_the_last(self):
        parsed = parse_cvars(cvar_file_bytes([("a", "1"), ("A", "2")]))
        self.assertEqual(parsed.get("a"), "2")

    def test_empty_file(self):
        parsed = parse_cvars(b"")
        self.assertEqual((parsed.lines, parsed.newline), ((), b"\r\n"))


class ApplyTest(unittest.TestCase):
    def test_round_trip_unchanged_is_identical(self):
        for data in (SAMPLE, b"", SAMPLE.replace(b"\r\n", b"\n"), b'SET a "1"\r\nSET b "2"\n# x'):
            self.assertEqual(apply_cvar_changes(data, parse_cvars(data), {}, ()), data)

    def test_cvar_set_replace_remove_append(self):
        parsed = parse_cvars(SAMPLE)
        out = apply_cvar_changes(SAMPLE, parsed, {"nameplateShowEnemies": "0", "newOne": "5",
                                                  "Sound_MasterVolume": "0.4"}, {"hardTrackedQuests"})
        self.assertEqual(out, b'SET cameraDistanceMaxZoomFactor "2.6"\r\n'
                              b'SET nameplateShowEnemies "0"\r\n'
                              b'SET Sound_MasterVolume "0.4"\r\n'
                              b'SET newOne "5"\r\n')

    def test_set_keeps_the_files_spelling_and_line_ending(self):
        data = b'SET gxWindow "1"\nSET other "x"\r\n'
        out = apply_cvar_changes(data, parse_cvars(data), {"GXWINDOW": "0", "other": "y"}, ())
        self.assertEqual(out, b'SET gxWindow "0"\nSET other "y"\r\n')

    def test_set_and_remove_every_duplicate(self):
        data = cvar_file_bytes([("a", "1"), ("b", "x"), ("A", "2"), ("c", "y"), ("c", "z")])
        out = apply_cvar_changes(data, parse_cvars(data), {"a": "3"}, {"C"})
        self.assertEqual(out, b'SET a "3"\r\nSET b "x"\r\n')

    def test_append_after_an_unterminated_last_line(self):
        data = b'SET a "1"\nSET b "2"'
        out = apply_cvar_changes(data, parse_cvars(data), {"c": "3"}, ())
        self.assertEqual(out, b'SET a "1"\nSET b "2"\nSET c "3"\n')
        self.assertEqual(apply_cvar_changes(b"", parse_cvars(b""), {"c": "3"}, ()), b'SET c "3"\r\n')

    def test_remove_a_missing_cvar_changes_nothing(self):
        self.assertEqual(apply_cvar_changes(SAMPLE, parse_cvars(SAMPLE), {}, {"notThere"}), SAMPLE)

    def test_cvar_value_with_quotes_kept(self):
        data = 'SET chatText "say "hi" to Dæn"\r\nSET b "2"\r\n'.encode()
        parsed = parse_cvars(data)
        self.assertEqual(parsed.get("chatText"), 'say "hi" to Dæn')
        self.assertEqual(apply_cvar_changes(data, parsed, {}, ()), data)
        out = apply_cvar_changes(data, parsed, {"b": 'a "q"'}, ())
        self.assertEqual(out, 'SET chatText "say "hi" to Dæn"\r\nSET b "a "q""\r\n'.encode())
        self.assertEqual(parse_cvars(out).get("b"), 'a "q"')

    def test_invalid_utf8_value_survives(self):
        data = b'SET a "\xff\xfe"\r\n'
        parsed = parse_cvars(data)
        self.assertEqual(apply_cvar_changes(data, parsed, {"a": parsed.get("a")}, ()), data)

    def test_any_name_the_parser_reads_can_be_set(self):
        data = b'SET foo\xc2\xa0bar "1"\r\nSET x\x1cy "2"\r\n'  # U+00A0 and \x1c are not ASCII whitespace
        parsed = parse_cvars(data)
        self.assertEqual([line.name for line in parsed.lines], ["foo\xa0bar", "x\x1cy"])
        changed = apply_cvar_changes(data, parsed, {"foo\xa0bar": "3", "x\x1cy": "4"}, ())
        self.assertEqual(changed, b'SET foo\xc2\xa0bar "3"\r\nSET x\x1cy "4"\r\n')

    def test_bad_changes_raise(self):
        parsed = parse_cvars(SAMPLE)
        for sets, removes in (({"a": "1\n2"}, ()), ({"a b": "1"}, ()), ({"": "1"}, ()), ({'a"': "1"}, ()), ({"a\tb": "1"}, ()),
                              ({"a": "1"}, {"A"})):
            with self.subTest(sets=sets, removes=removes), self.assertRaises(ValueError):
                apply_cvar_changes(SAMPLE, parsed, sets, removes)


if __name__ == "__main__":
    unittest.main()
