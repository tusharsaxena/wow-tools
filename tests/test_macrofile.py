"""macrofile: the byte-exact macros-cache.txt reader and writer (config tools spec V4, V5, ME6, ME13, ME14)."""
from __future__ import annotations

import unittest

from tests.fixtures import macro_file_bytes
from wowtools.core import macrofile
from wowtools.core.macrofile import (ACCOUNT_PREFIX, BODY_LIMIT, CHARACTER_PREFIX, NAME_LIMIT, MacroChange,
                                     apply_macro_changes, next_macro_id, parse_macros)

# The V4 sample: a file id icon, a texture name icon (either case) and a multi-line body.
RETAIL = macro_file_bytes([
    ("0100000000000005", "D Up", "132360", "#showtooltip\n/cast [@mouseover,help,nodead][] Flash Heal"),
    ("0100000000000001", "Celestial Condui", "INV_Misc_QuestionMark", "/use 13"),
    ("010000000000001B", "Auto", "inv_misc_questionmark", "/cast [mod:shift] Shield Wall; Shield Block\n/startattack\n"),
    ("0100000000000002", "Empty", "134400", ""),
])


class ParseTest(unittest.TestCase):
    def test_parse_retail_layout(self):
        parsed = parse_macros(RETAIL)
        self.assertTrue(parsed.known_layout)
        self.assertIsNone(parsed.problem)
        self.assertEqual(parsed.newline, b"\r\n")
        self.assertEqual([m.id for m in parsed.macros],
                         ["0100000000000005", "0100000000000001", "010000000000001B", "0100000000000002"])
        first = parsed.macros[0]
        self.assertEqual((first.name, first.icon), ("D Up", "132360"))
        self.assertEqual(first.body, "#showtooltip\n/cast [@mouseover,help,nodead][] Flash Heal")
        self.assertEqual(parsed.macros[1].icon, "INV_Misc_QuestionMark")
        self.assertEqual(parsed.macros[2].icon, "inv_misc_questionmark")
        self.assertEqual(parsed.macros[2].body, "/cast [mod:shift] Shield Wall; Shield Block\n/startattack\n")
        self.assertEqual(parsed.macros[3].body, "")
        # Spans tile the file: each block from its VER line through END's own newline.
        self.assertEqual(first.span[0], 0)
        self.assertTrue(RETAIL[first.span[0]:first.span[1]].startswith(b'VER 3 0100000000000005 "D Up"'))
        self.assertTrue(RETAIL[first.span[0]:first.span[1]].endswith(b"END\r\n"))
        for one, two in zip(parsed.macros, parsed.macros[1:]):
            self.assertEqual(one.span[1], two.span[0])
        self.assertEqual(parsed.macros[-1].span[1], len(RETAIL))

    def test_empty_file_is_known_and_empty(self):
        parsed = parse_macros(b"")
        self.assertTrue(parsed.known_layout)
        self.assertEqual(parsed.macros, ())
        self.assertEqual(parsed.newline, b"\r\n")

    def test_name_with_quotes_and_lowercase_id(self):
        data = b'VER 3 01000000000000ab "say "hi"" "134400"\r\n/say hi\r\nEND\r\n'
        parsed = parse_macros(data)
        self.assertTrue(parsed.known_layout)
        self.assertEqual((parsed.macros[0].id, parsed.macros[0].name), ("01000000000000ab", 'say "hi"'))

    def test_unknown_layout_read_only(self):
        good = macro_file_bytes([("0000000000000001", "A", "134400", "/dance")])
        cases = {
            "LF-only": good.replace(b"\r\n", b"\n"),
            "mixed line endings": good + b'VER 3 0000000000000002 "B" "134400"\n/wave\r\nEND\r\n',
            "missing final END": good + b'VER 3 0000000000000002 "B" "134400"\r\n/wave\r\n',
            "MACRO layout": b'MACRO 1 "A" INV_Misc_QuestionMark\r\n/dance\r\nEND\r\n',
            "another VER": b'VER 2 0000000000000001 "A" "134400"\r\n/dance\r\nEND\r\n',
            "trailing junk": good + b"garbage\r\n",
            "a blank line between macros": good + b"\r\n" + good.replace(b"0001", b"0002"),
            "no final newline": good[:-2],
            "a bad id": good.replace(b"0000000000000001", b"000000000000001"),
            "a duplicated id": good + good,
            "a byte-order mark": b"\xef\xbb\xbf" + good,
        }
        for label, data in cases.items():
            with self.subTest(label):
                parsed = parse_macros(data)
                self.assertFalse(parsed.known_layout)
                self.assertTrue(parsed.problem)
                with self.assertRaises(ValueError):
                    apply_macro_changes(data, parsed, [MacroChange("delete", "0000000000000001")])
                with self.assertRaises(ValueError):
                    apply_macro_changes(data, parsed, [])  # never rewritten, even with nothing to change

    def test_limits_and_prefixes(self):
        self.assertEqual((ACCOUNT_PREFIX, CHARACTER_PREFIX, NAME_LIMIT, BODY_LIMIT), ("00", "01", 16, 255))
        self.assertEqual(macrofile.ICON_DEFAULT, "134400")


class ApplyTest(unittest.TestCase):
    def test_round_trip_unchanged_is_identical(self):
        for data in (RETAIL, b""):
            self.assertEqual(apply_macro_changes(data, parse_macros(data), []), data)

    def test_add_replace_delete_touch_only_their_blocks(self):
        parsed = parse_macros(RETAIL)
        blocks = [RETAIL[m.span[0]:m.span[1]] for m in parsed.macros]
        changes = [
            MacroChange("replace", "0100000000000001", "Trinket", "INV_Jewelry_Talisman_01", "/use 14\n/use 13"),
            MacroChange("delete", "010000000000001B"),
            MacroChange("add", "010000000000001C", "New", "134400", "/wave"),
        ]
        out = apply_macro_changes(RETAIL, parsed, changes)
        self.assertEqual(out, blocks[0]
                         + b'VER 3 0100000000000001 "Trinket" "INV_Jewelry_Talisman_01"\r\n/use 14\r\n/use 13\r\nEND\r\n'
                         + blocks[3]
                         + b'VER 3 010000000000001C "New" "134400"\r\n/wave\r\nEND\r\n')
        again = parse_macros(out)
        self.assertTrue(again.known_layout)
        self.assertEqual([m.id for m in again.macros],
                         ["0100000000000005", "0100000000000001", "0100000000000002", "010000000000001C"])

    def test_add_to_empty_file_and_empty_body(self):
        out = apply_macro_changes(b"", parse_macros(b""), [MacroChange("add", "0100000000000001", "E", "134400", "")])
        self.assertEqual(out, b'VER 3 0100000000000001 "E" "134400"\r\nEND\r\n')
        self.assertEqual(parse_macros(out).macros[0].body, "")

    def test_bad_changes_raise(self):
        parsed = parse_macros(RETAIL)
        bad = {
            "replace an unknown id": [MacroChange("replace", "0100000000000099", "X", "134400", "")],
            "delete an unknown id": [MacroChange("delete", "0100000000000099")],
            "add an id in use": [MacroChange("add", "0100000000000005", "X", "134400", "")],
            "add a malformed id": [MacroChange("add", "1", "X", "134400", "")],
            "two changes to one id": [MacroChange("delete", "0100000000000005"),
                                      MacroChange("replace", "0100000000000005", "X", "134400", "")],
            "a newline in the name": [MacroChange("add", "0100000000000099", "X\nY", "134400", "")],
            "a quote in the icon": [MacroChange("add", "0100000000000099", "X", '13"4', "")],
            "a body line END": [MacroChange("add", "0100000000000099", "X", "134400", "/wave\nEND")],
            "a VER line in the body": [MacroChange("add", "0100000000000099", "X", "134400",
                                                    '/wave\nVER 3 0100000000000098 "Y" "134400"')],
            "a CR in the body": [MacroChange("add", "0100000000000099", "X", "134400", "/wave\r")],
        }
        for label, changes in bad.items():
            with self.subTest(label), self.assertRaises(ValueError):
                apply_macro_changes(RETAIL, parsed, changes)

    def test_non_ascii_body_round_trip(self):
        data = macro_file_bytes([("0000000000000001", "Dænerys", "134400", "/w Dænerys-Trâxex hi\n/say Aellâ")])
        parsed = parse_macros(data)
        self.assertEqual(parsed.macros[0].name, "Dænerys")
        self.assertEqual(parsed.macros[0].body, "/w Dænerys-Trâxex hi\n/say Aellâ")
        self.assertEqual(apply_macro_changes(data, parsed, []), data)
        out = apply_macro_changes(data, parsed, [MacroChange("replace", "0000000000000001", "Dænerys", "134400",
                                                             "/w Dænerys-Trâxex hi\n/say Aellâ")])
        self.assertEqual(out, data)

    def test_invalid_utf8_bytes_survive(self):
        data = b'VER 3 0000000000000001 "Bad\xff" "134400"\r\n/say \xfe\r\nEND\r\n'
        parsed = parse_macros(data)
        self.assertTrue(parsed.known_layout)
        macro = parsed.macros[0]
        out = apply_macro_changes(data, parsed, [MacroChange("replace", macro.id, macro.name, macro.icon, macro.body)])
        self.assertEqual(out, data)


class NextIdTest(unittest.TestCase):
    def test_next_id_account_and_character(self):
        account = parse_macros(macro_file_bytes([("00000000000000ED", "A", "134400", ""),
                                                 ("0000000000000003", "B", "134400", "")]))
        self.assertEqual(next_macro_id(account, "account"), "00000000000000EE")
        self.assertEqual(next_macro_id(parse_macros(b""), "character"), "0100000000000001")
        self.assertEqual(next_macro_id(parse_macros(b""), "account"), "0000000000000001")
        character = parse_macros(RETAIL)
        self.assertEqual(next_macro_id(character, "character"), "010000000000001C")

    def test_next_id_ignores_the_other_prefix_and_reads_lowercase(self):
        mixed = parse_macros(macro_file_bytes([("01000000000000fe", "A", "134400", ""),
                                               ("0000000000000500", "B", "134400", "")]))
        self.assertEqual(next_macro_id(mixed, "character"), "01000000000000FF")
        self.assertEqual(next_macro_id(mixed, "account"), "0000000000000501")

    def test_next_id_refuses_overflow_and_unknown_layout(self):
        full = parse_macros(macro_file_bytes([("00FFFFFFFFFFFFFF", "A", "134400", "")]))
        with self.assertRaises(ValueError):
            next_macro_id(full, "account")
        with self.assertRaises(ValueError):
            next_macro_id(parse_macros(b"junk\r\n"), "account")


if __name__ == "__main__":
    unittest.main()
