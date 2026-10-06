"""Saved Variables Browser search (spec D6-D11): SearchSpec validation, key and value matching with the case and mode
switches, scope filters, typed replacements, the byte pre-filter (never skipping a file that has a hit), unreadable
files reported instead of raised, the result cap, and a streaming guard over a multi-MB file."""
from __future__ import annotations

import hashlib
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import SVB_FONT, _write_lua, ace_lua, build_sv_tree
from wowtools.core import luasv
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.luasv import RawNumber
from wowtools.core.svfiles import OWNER_ACCOUNT_WIDE
from wowtools.tools.sv_browser import search
from wowtools.tools.sv_browser.scanner import scan_flavors
from wowtools.tools.sv_browser.search import (KEY_CONTAINS, KEY_EXACT, REPLACE_BOOLEAN, REPLACE_NUMBER,
                                              REPLACE_STRING, VALUE_CONTAINS, VALUE_WHOLE, SearchScope, SearchSpec,
                                              parse_replacement, run_search, search_file)


def where(hit):
    """(flavor, account, owner, file, path) of a hit."""
    return hit.file.flavor.folder, hit.file.account, hit.file.owner, hit.file.path.name, hit.path


class SearchTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_sv_tree(self.tmp / "wow")
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("_retail_")
        self.era = self.install.flavor("_classic_era_")
        self.extra_sv = self.retail.account_dir / "ACCT1" / "SavedVariables"

    def add_file(self, name, *lines):
        """A file of the given lines in ACCT1's account-wide SavedVariables (retail)."""
        return _write_lua(self.extra_sv / name, ace_lua(*lines))

    def files(self):
        return scan_flavors([self.retail, self.era]).files()

    def find(self, **spec):
        return run_search(self.files(), SearchSpec(**spec))

    def paths(self, result):
        return sorted((h.file.path.name, h.path) for h in result.hits)


class SpecTest(unittest.TestCase):
    def test_defaults_are_exact_key_whole_value_any_case_everything(self):
        spec = SearchSpec(key="font")
        self.assertEqual((spec.key_mode, spec.value_mode, spec.match_case, spec.scope, spec.replacement),
                         (KEY_EXACT, VALUE_WHOLE, False, SearchScope(), None))

    def test_a_key_or_a_value_is_needed(self):
        self.assertEqual(SearchSpec().problems(), ["Enter a key, a value or both."])
        self.assertEqual(SearchSpec(key="  ").problems(), ["Enter a key, a value or both."])
        self.assertEqual(SearchSpec(key="font").problems(), [])
        self.assertEqual(SearchSpec(value="Friz").problems(), [])
        with self.assertRaises(ValueError):
            SearchSpec().check()

    def test_contains_value_needs_text_to_put_in(self):
        spec = SearchSpec(value="Friz", value_mode=VALUE_CONTAINS, replacement=5)
        self.assertEqual(len(spec.problems()), 1)
        self.assertIn("text", spec.problems()[0])
        self.assertEqual(SearchSpec(value="Friz", value_mode=VALUE_CONTAINS, replacement="Arial").problems(), [])
        self.assertEqual(SearchSpec(value="Friz", value_mode=VALUE_CONTAINS, replacement="").problems(), [])
        # Without a value the value mode plays no part: a key search replaces whole values.
        self.assertEqual(SearchSpec(key="font", value_mode=VALUE_CONTAINS, replacement=5).problems(), [])

    def test_whole_value_replacement_is_any_scalar_type(self):
        for value in ("Arial", 12, 2.5, True, False):
            self.assertEqual(SearchSpec(key="font", replacement=value).problems(), [], value)

    def test_number_replacement_must_read_back_as_the_same_number(self):
        for value in (float("inf"), float("-inf"), float("nan"), 2 ** 53 + 1, -(2 ** 60)):
            self.assertTrue(SearchSpec(key="x", replacement=value).problems(), value)
        for value in (RawNumber("1.#INF"), object(), [1]):
            self.assertTrue(SearchSpec(key="x", replacement=value).problems(), value)
        self.assertEqual(SearchSpec(key="x", replacement=2 ** 53).problems(), [])

    def test_no_replacement_is_a_find_only_search(self):
        self.assertEqual(SearchSpec(key="font").problems(), [])
        self.assertFalse(SearchSpec(key="font").replaces)
        self.assertTrue(SearchSpec(key="font", replacement="").replaces)

    def test_unknown_modes_are_refused(self):
        self.assertTrue(SearchSpec(key="x", key_mode="regex").problems())
        self.assertTrue(SearchSpec(value="x", value_mode="regex").problems())


class ParseReplacementTest(unittest.TestCase):
    def test_string_is_the_text_as_typed(self):
        self.assertEqual(parse_replacement(REPLACE_STRING, " Friz Quadrata TT "), " Friz Quadrata TT ")
        self.assertEqual(parse_replacement(REPLACE_STRING, ""), "")

    def test_numbers(self):
        cases = {"12": 12, "-3": -3, " 7 ": 7, "2.5": 2.5, "-0.25": -0.25, ".5": 0.5, "1e3": 1000.0, "1.50": 1.5,
                 "0.6000000000000001": 0.6000000000000001, "9007199254740992": 2 ** 53}
        for text, value in cases.items():
            parsed = parse_replacement(REPLACE_NUMBER, text)
            self.assertEqual(parsed, value, text)
            self.assertIs(type(parsed), type(value), text)

    def test_numbers_lua_would_not_read_back_identically_are_refused(self):
        for text in ("", "abc", "inf", "-inf", "nan", "1e400", "1_000", "0x10", "1.#INF", "12abc", "1,5",
                     "0.1000000000000000000001", "9007199254740993", "+5", "true"):
            with self.assertRaises(ValueError, msg=text):
                parse_replacement(REPLACE_NUMBER, text)

    def test_booleans(self):
        self.assertIs(parse_replacement(REPLACE_BOOLEAN, "true"), True)
        self.assertIs(parse_replacement(REPLACE_BOOLEAN, " False "), False)
        for text in ("yes", "1", ""):
            with self.assertRaises(ValueError, msg=text):
                parse_replacement(REPLACE_BOOLEAN, text)

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            parse_replacement("table", "{}")


class KeySearchTest(SearchTestBase):
    def test_exact_key_ignores_case_by_default(self):
        result = self.find(key="font")
        names = {(h.file.path.name, h.path[-1]) for h in result.hits}
        self.assertEqual(names, {("ElvUI.lua", "font"), ("ElvUI.lua", "Font"), ("Questie.lua", "font"),
                                 ("Bartender4.lua", "font")})
        self.assertEqual(len(result.hits), 5)  # ElvUI: general.font, unitframe.Font, per character font

    def test_exact_key_with_match_case(self):
        result = self.find(key="Font", match_case=True)
        self.assertEqual(self.paths(result),
                         [("ElvUI.lua", ("ElvDB", "profiles", "Default", "unitframe", "Font"))])

    def test_contains_key(self):
        result = self.find(key="FONT", key_mode=KEY_CONTAINS)
        keys = sorted({h.path[-1] for h in result.hits})
        self.assertEqual(keys, ["Font", "barFont", "font", "fontHeight", "fontSize", "font_face", "fontface"])
        result = self.find(key="Font", key_mode=KEY_CONTAINS, match_case=True)
        self.assertEqual(sorted({h.path[-1] for h in result.hits}), ["Font", "barFont"])

    def test_numeric_keys_match_their_written_text_and_positional_entries_their_index(self):
        result = self.find(key="2")
        self.assertEqual(self.paths(result), [
            ("Details.lua", ("_detalhes_global", "bars", 2)),
            ("Details.lua", ("_detalhes_global", "bars", 2)),
            ("ElvUI.lua", ("ElvDB", "profiles", "Default", "unitframe", 2)),
        ])
        nil_slot = next(h for h in result.hits if h.file.path.name == "Details.lua")
        self.assertIsNone(nil_slot.old)
        self.assertIsNone(nil_slot.key_span)

    def test_float_keys_match_as_written(self):
        self.add_file("Keys.lua", "KeysDB = {", "[2.50] = 1,", "[0x10] = 2,", "}")
        self.assertEqual(self.paths(self.find(key="2.50")), [("Keys.lua", ("KeysDB", 2.5))])
        self.assertEqual(self.paths(self.find(key="2.5")), [])
        self.assertEqual(self.paths(self.find(key="0X10")), [("Keys.lua", ("KeysDB", 16))])

    def test_boolean_keys(self):
        result = self.find(key="TRUE")
        self.assertEqual(self.paths(result), [("ElvUI.lua", ("ElvDB", "profiles", "Default", "unitframe", True))])
        self.assertIs(type(result.hits[0].path[-1]), bool)
        self.assertEqual(result.hits[0].typed_path[-1], ("bool", True))

    def test_top_level_scalars_are_hits_tables_never_are(self):
        self.assertEqual(self.paths(self.find(key="DetailsVersion")),
                         [("Details.lua", ("DetailsVersion",))] * 2)
        self.assertEqual(self.paths(self.find(key="ElvVersion")), [("ElvUI.lua", ("ElvVersion",))])
        self.assertEqual(self.find(key="general").hits, [])
        self.assertEqual(self.find(key="ElvDB").hits, [])


class ValueSearchTest(SearchTestBase):
    def test_whole_value_ignores_case_by_default(self):
        result = self.find(value=SVB_FONT.upper())
        self.assertEqual(len(result.hits), 7)
        self.assertEqual({where(h)[:4] for h in result.hits}, {
            ("_retail_", "ACCT1", OWNER_ACCOUNT_WIDE, "ElvUI.lua"),
            ("_retail_", "ACCT1", OWNER_ACCOUNT_WIDE, "Details.lua"),
            ("_retail_", "ACCT1", "Realm1/Kaelys", "ElvUI.lua"),
            ("_retail_", "ACCT2", OWNER_ACCOUNT_WIDE, "Details.lua"),
            ("_retail_", "ACCT2", "Realm2/Chârb", "Bartender4.lua"),
            ("_classic_era_", "ACCT1", OWNER_ACCOUNT_WIDE, "Questie.lua"),
        })

    def test_whole_value_with_match_case(self):
        result = self.find(value=SVB_FONT, match_case=True)
        self.assertEqual(len(result.hits), 6)
        self.assertNotIn("Bartender4.lua", {h.file.path.name for h in result.hits})
        self.assertEqual(self.find(value="friz quadrata", match_case=False).hits, [])  # whole, not part

    def test_whole_value_numbers_and_booleans_by_written_text(self):
        self.assertEqual(self.paths(self.find(value="12")),
                         [("ElvUI.lua", ("ElvDB", "profiles", "Default", "general", "fontSize"))])
        self.assertEqual(self.paths(self.find(value="0.6000000000000001")),
                         [("ElvUI.lua", ("ElvDB", "profiles", "Default", "general", "scale"))])
        self.assertEqual(self.find(value="0.6").hits, [])
        self.assertEqual(self.paths(self.find(value="FALSE")), [("Questie.lua", ("QuestieConfig", "global", "enabled"))])
        self.assertEqual(self.paths(self.find(value="4")), [("Details.lua", ("DetailsVersion",))] * 2)
        self.assertEqual(self.find(value="nil").hits, [])

    def test_whole_value_string_number_text_matches_a_string_too(self):
        self.add_file("Mixed.lua", "MixedDB = {", '["a"] = "12",', '["b"] = 12,', '["c"] = 12.0,', "}")
        hits = [h for h in self.find(value="12").hits if h.file.path.name == "Mixed.lua"]
        self.assertEqual([(h.path[-1], h.old) for h in hits], [("a", "12"), ("b", 12)])

    def test_contains_matches_strings_only(self):
        self.add_file("Mixed.lua", "MixedDB = {", '["a"] = "x12y",', '["b"] = 312,', '["c"] = true,', "}")
        hits = [h for h in self.find(value="12", value_mode=VALUE_CONTAINS, replacement="!").hits
                if h.file.path.name == "Mixed.lua"]
        self.assertEqual([(h.path[-1], h.new) for h in hits], [("a", "x!y")])
        self.assertEqual(self.find(value="ru", value_mode=VALUE_CONTAINS).hits, [])

    def test_contains_replaces_every_occurrence(self):
        self.add_file("Rep.lua", "RepDB = {", '["a"] = "abcABCabc",', '["b"] = "a.b axb",', "}")
        hits = {h.path[-1]: h for h in self.find(value="abc", value_mode=VALUE_CONTAINS, replacement="X").hits}
        self.assertEqual(hits["a"].new, "XXX")
        self.assertEqual(hits["a"].new_bytes, b'"XXX"')
        hits = {h.path[-1]: h for h in self.find(value="abc", value_mode=VALUE_CONTAINS, replacement="X",
                                                 match_case=True).hits}
        self.assertEqual(hits["a"].new, "XABCX")
        # the needle is text, never a pattern; the replacement is text, never a template
        hits = {h.path[-1]: h for h in self.find(value="A.B", value_mode=VALUE_CONTAINS, replacement=r"\1$&").hits}
        self.assertEqual(list(hits), ["b"])
        self.assertEqual(hits["b"].new, r"\1$& axb")

    def test_contains_keeps_the_rest_of_the_string(self):
        hits = self.find(value="quadrata", value_mode=VALUE_CONTAINS, replacement="Q").hits
        self.assertEqual(len(hits), 7)
        self.assertEqual({h.new for h in hits}, {"Friz Q TT", "friz Q tt"})

    def test_whole_value_replacement_is_typed(self):
        hit = self.find(value=SVB_FONT, match_case=True, replacement=14, scope=SearchScope(addon="questie")).hits[0]
        self.assertEqual((hit.old, hit.new, hit.new_bytes), (SVB_FONT, 14, b"14"))
        hit = self.find(value="12", replacement="twelve").hits[0]
        self.assertEqual((hit.old, hit.new, hit.new_bytes), (12, "twelve", b'"twelve"'))
        hit = self.find(value="false", replacement=True).hits[0]
        self.assertEqual((hit.old, hit.new_bytes), (False, b"true"))

    def test_find_only_hits_have_no_new_value(self):
        hit = self.find(value="12").hits[0]
        self.assertIsNone(hit.new)
        self.assertIsNone(hit.new_bytes)

    def test_escaped_strings_match_their_decoded_text(self):
        result = self.find(value='a"b\\c\n\u2014', match_case=True)
        self.assertEqual(self.paths(result), [("Details.lua", ("_detalhes_global", "tooltip", "text"))] * 2)


    def test_a_needle_of_blanks_is_a_needle(self):
        # M2 review: a value of spaces is text to find, never "no value" (a key-only overwrite of every value)
        self.add_file("Sp.lua", "SpDB = {", '["name"] = "Foo  Bar",', '["x"] = {', '["name"] = 12,', "},",
                      '["y"] = {', '["name"] = "Baz",', "},", '["z"] = {', '["name"] = " ",', "},", "}")
        self.assertEqual(SearchSpec(key="name", value="  ", value_mode=VALUE_CONTAINS, replacement=5).problems()[:1],
                         ["A Contains value search puts text inside strings: the replacement must be text."])
        hits = self.find(key="name", value="  ", value_mode=VALUE_CONTAINS, replacement=" ",
                         scope=SearchScope(addon="sp")).hits
        self.assertEqual([(h.path, h.new) for h in hits], [(("SpDB", "name"), "Foo Bar")])
        hits = self.find(key="name", value=" ", replacement="-", scope=SearchScope(addon="sp")).hits
        self.assertEqual([(h.path, h.old, h.new) for h in hits], [(("SpDB", "z", "name"), " ", "-")])
        self.assertEqual(SearchSpec(value=" ").problems(), [])


class KeyAndValueTest(SearchTestBase):
    def test_both_must_hold(self):
        result = self.find(key="font", value="Friz", value_mode=VALUE_CONTAINS)
        self.assertEqual(sorted((h.file.path.name, h.path[-1]) for h in result.hits),
                         [("Bartender4.lua", "font"), ("ElvUI.lua", "Font"), ("ElvUI.lua", "font"),
                          ("Questie.lua", "font")])

    def test_key_contains_and_whole_value(self):
        result = self.find(key="bar", key_mode=KEY_CONTAINS, value=SVB_FONT)
        self.assertEqual(self.paths(result), [("ElvUI.lua", ("ElvCharacterDB", "nested", "deeper", "barFont"))])


class ScopeTest(SearchTestBase):
    def scoped(self, **scope):
        return self.find(value=SVB_FONT, scope=SearchScope(**scope))

    def test_flavor(self):
        self.assertEqual({h.file.flavor.folder for h in self.scoped(flavor="_classic_era_").hits}, {"_classic_era_"})
        self.assertEqual(len(self.scoped(flavor="_retail_").hits), 6)

    def test_account(self):
        hits = self.scoped(account="ACCT2").hits
        self.assertEqual(sorted(h.file.path.name for h in hits), ["Bartender4.lua", "Details.lua"])
        self.assertEqual(len(self.scoped(flavor="_retail_", account="ACCT1").hits), 4)

    def test_character_and_account_wide_only(self):
        hits = self.scoped(character="Realm1/Kaelys").hits
        self.assertEqual([(h.file.flavor.folder, h.file.path.name) for h in hits], [("_retail_", "ElvUI.lua")])
        hits = self.scoped(character=OWNER_ACCOUNT_WIDE).hits
        self.assertEqual(len(hits), 5)
        self.assertTrue(all(h.file.character is None for h in hits))

    def test_addon_contains_ignoring_case(self):
        hits = self.scoped(addon="elv").hits
        self.assertEqual({h.file.path.name for h in hits}, {"ElvUI.lua"})
        self.assertEqual(len(hits), 3)
        self.assertEqual(self.scoped(addon="ELVUI.lua").hits, [])  # the addon name, not the file name

    def test_files_out_of_scope_are_not_read(self):
        files = self.files()
        with mock.patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as read:
            result = run_search(files, SearchSpec(value=SVB_FONT, scope=SearchScope(addon="questie")))
        self.assertEqual(result.files, 2)
        self.assertEqual(sorted(call.args[0].name for call in read.call_args_list), ["Questie.lua", "Questie.lua"])

    def test_scope_in_files(self):
        files = self.files()
        self.assertEqual(SearchScope().files(files), files)
        self.assertEqual([f.path.name for f in SearchScope(flavor="_classic_era_", character=OWNER_ACCOUNT_WIDE)
                         .files(files)], ["Questie.lua"])


class HitTest(SearchTestBase):
    def test_hit_carries_file_hash_spans_and_values(self):
        result = self.find(key="font", match_case=True, scope=SearchScope(addon="questie"), replacement="Arial")
        hit = result.hits[0]
        data = hit.file.path.read_bytes()
        self.assertEqual(hit.file.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(hit.sha256, hit.file.sha256)
        self.assertEqual(hit.path, ("QuestieConfig", "global", "font"))
        self.assertEqual(hit.typed_path, (("str", "QuestieConfig"), ("str", "global"), ("str", "font")))
        self.assertEqual(hit.key, "font")
        self.assertEqual(data[slice(*hit.key_span)], b'["font"]')
        self.assertEqual(data[slice(*hit.value_span)], b'"Friz Quadrata TT"')
        self.assertEqual(hit.old_bytes, b'"Friz Quadrata TT"')
        self.assertEqual((hit.old, hit.new, hit.new_bytes), (SVB_FONT, "Arial", b'"Arial"'))

    def test_top_level_hit_key_span_is_the_name(self):
        hit = self.find(key="DetailsVersion").hits[0]
        data = hit.file.path.read_bytes()
        self.assertEqual(data[slice(*hit.key_span)], b"DetailsVersion")
        self.assertEqual(data[slice(*hit.value_span)], b"4")

    def test_hits_of_one_file_share_one_file_object_and_come_in_file_order(self):
        hits = self.find(value=SVB_FONT, scope=SearchScope(addon="elv", character=OWNER_ACCOUNT_WIDE)).hits
        self.assertEqual(len(hits), 2)
        self.assertIs(hits[0].file, hits[1].file)
        self.assertLess(hits[0].value_span[0], hits[1].value_span[0])

    def test_hits_come_in_file_list_order_whatever_the_parallelism(self):
        files = self.files()
        spec = SearchSpec(key="font", key_mode=KEY_CONTAINS)
        one = run_search(files, spec, parallelism=1)
        four = run_search(files, spec, parallelism=4)
        self.assertEqual([where(h) for h in one.hits], [where(h) for h in four.hits])
        order = [f.path for f in files]
        self.assertEqual([h.file.path for h in one.hits],
                         sorted((h.file.path for h in one.hits), key=order.index))


class PrefilterTest(SearchTestBase):
    def test_files_without_the_needle_are_never_parsed(self):
        with mock.patch.object(search, "iter_scalars", wraps=luasv.iter_scalars) as walk:
            result = self.find(value="nowhere to be found")
        self.assertEqual(result.hits, [])
        # only the two Details.lua: their \226\128\148 escape could hide any text, so they are always parsed
        self.assertEqual(sorted(c.args[0].count(b"\\226") for c in walk.call_args_list), [1, 1])
        self.assertEqual(walk.call_count, 2)
        self.assertEqual(result.files, 9)
        self.assertEqual(result.unreadable, [])  # a skipped file is not parsed, so not found broken either

    def test_file_with_the_needle_is_parsed(self):
        with mock.patch.object(search, "iter_scalars", wraps=luasv.iter_scalars) as walk:
            self.find(value="Expressway")
        self.assertEqual(walk.call_count, 4)  # ElvUI.lua account-wide and per character, and the Details.lua

    def test_match_case_pre_filter_compares_the_bytes_as_they_are(self):
        with mock.patch.object(search, "iter_scalars", wraps=luasv.iter_scalars) as walk:
            result = self.find(value="EXPRESSWAY", match_case=True)
        self.assertEqual(result.hits, [])
        self.assertEqual(walk.call_count, 2)  # the two Details.lua only (escapes)

    def test_escaped_backslashes_do_not_turn_the_pre_filter_off(self):
        # M2 review: WoW writes paths with escaped backslashes; such a pair is one escape, never a hiding one
        data = b'X = {["icon"] = "Interface\\\\Icons\\\\INV",}'
        self.assertFalse(search.may_hold(data, SearchSpec(value="Expressway")))
        self.assertFalse(search.may_hold(data, SearchSpec(value="Expressway", match_case=True)))
        self.assertTrue(search.may_hold(data.replace(b"INV", b"Expressway"), SearchSpec(value="Expressway")))
        self.assertTrue(search.may_hold(b'X = {"a\\\\\\070",}', SearchSpec(value="F")))  # a pair, then a \\070
        self.add_file("Path.lua", "PathDB = {", '["icon"] = "Interface\\\\Icons\\\\INV_Misc",', "}")
        with mock.patch.object(search, "iter_scalars", wraps=luasv.iter_scalars) as walk:
            self.find(value="Expressway", scope=SearchScope(addon="path"))
        self.assertEqual(walk.call_count, 0)

    def test_digits_key_never_skips_a_file(self):
        with mock.patch.object(search, "iter_scalars", wraps=luasv.iter_scalars) as walk:
            self.find(key="7")
        self.assertEqual(walk.call_count, 9)  # an array index is never written: every file is parsed
        self.assertEqual(len(self.find(key="7").unreadable), 1)

    def test_needle_only_in_a_decimal_escape_is_found(self):
        self.add_file("Esc.lua", 'EscDB = {', '["name"] = "\\070riz",', '["k"] = "\\x46oo",', "}")
        self.assertEqual(self.paths(self.find(value="Friz", match_case=True)), [("Esc.lua", ("EscDB", "name"))])
        # WoW runs Lua 5.1: `\\x46oo` reads "x46oo" (5.2's hex escape is not one)
        self.assertEqual(self.find(value="Foo", match_case=True, scope=SearchScope(addon="esc")).hits, [])
        self.assertEqual(self.paths(self.find(value="x46oo", match_case=True)), [("Esc.lua", ("EscDB", "k"))])
        self.assertEqual(self.paths(self.find(key="name", value="F", value_mode=VALUE_CONTAINS, match_case=True)),
                         [("Esc.lua", ("EscDB", "name"))])

    def test_a_contains_replace_keeps_what_lua_5_1_reads(self):
        # M2 review: `\\x41BC` is "x41BC" in WoW, so replacing BC must give "x41ZZ", never "AZZ"
        self.add_file("Hex.lua", 'HexDB = {', '["a"] = "\\x41BC",', "}")
        hit, = self.find(value="BC", value_mode=VALUE_CONTAINS, replacement="ZZ", scope=SearchScope(addon="hex")).hits
        self.assertEqual((hit.old, hit.new, hit.new_bytes), ("x41BC", "x41ZZ", b'"x41ZZ"'))

    def test_escaped_keys_are_found(self):
        self.add_file("Esc.lua", 'EscDB = {', '["\\102ont"] = 1,', "}")
        self.assertEqual(self.paths(self.find(key="font", match_case=True, scope=SearchScope(addon="esc"))),
                         [("Esc.lua", ("EscDB", "font"))])

    def test_needles_with_quotes_backslashes_or_control_characters(self):
        self.add_file("Q.lua", 'QDB = {', '["a"] = "say \\"hi\\"",', "[\"b\"] = 'it\\'s',", '["c"] = "C:\\\\x",',
                      '["d"] = "tab\\there",', '["e"] = "two\\nlines",', "}")
        for needle, key in (('say "hi"', "a"), ("it's", "b"), ("C:\\x", "c"), ("tab\there", "d"),
                            ("two\nlines", "e")):
            self.assertEqual(self.paths(self.find(value=needle, match_case=True)), [("Q.lua", ("QDB", key))],
                             needle)

    def test_non_ascii_text_that_folds_to_ascii_is_found_without_match_case(self):
        self.add_file("Fold.lua", 'FoldDB = {', '["a"] = "\u212aelvin",', '["b"] = "Stra\u00dfe",', "}")
        self.assertEqual(self.paths(self.find(value="kelvin")), [("Fold.lua", ("FoldDB", "a"))])
        self.assertEqual(self.paths(self.find(value="STRASSE")), [("Fold.lua", ("FoldDB", "b"))])
        self.assertEqual(self.paths(self.find(value="KEL", value_mode=VALUE_CONTAINS)),
                         [("Fold.lua", ("FoldDB", "a"))])

    def test_non_ascii_needle(self):
        self.assertEqual(len(self.find(key="font", value="friz", value_mode=VALUE_CONTAINS).hits), 4)
        self.add_file("Uni.lua", 'UniDB = {', '["a"] = "Ch\u00e2rb",', "}")
        self.assertEqual(self.paths(self.find(value="CH\u00c2RB")), [("Uni.lua", ("UniDB", "a"))])
        self.assertEqual(self.paths(self.find(value="Ch\u00e2rb", match_case=True)), [("Uni.lua", ("UniDB", "a"))])

    def test_positional_index_keys_are_found_though_never_written(self):
        self.add_file("Arr.lua", 'ArrDB = {', '"a",', '"b",', "}")
        self.assertEqual(self.paths(self.find(key="2", scope=SearchScope(addon="arr"))), [("Arr.lua", ("ArrDB", 2))])

    def test_folds_to_ascii_table_is_complete(self):
        ascii_i = re.compile(r"[\x00-\x7f]", re.IGNORECASE)
        found = "".join(c for c in map(chr, range(0x80, 0x20000))
                        if ascii_i.match(c) or any(ord(x) < 0x80 for x in c.casefold()))
        self.assertEqual(found, search.FOLDS_TO_ASCII)


class UnreadableTest(SearchTestBase):
    def test_broken_file_is_reported_not_raised(self):
        with capture_events() as events:
            result = self.find(value="Friz", value_mode=VALUE_CONTAINS)
        self.assertEqual([f.path.name for f, _ in result.unreadable], ["Broken.lua"])
        self.assertIn("not readable Lua", result.unreadable[0][1])
        self.assertNotIn("Broken.lua", {h.file.path.name for h in result.hits})
        logged = [e for e in events if e["event"] == "svb.file_unreadable"]
        self.assertEqual([e["data"]["path"] for e in logged], ["WTF/Account/ACCT1/SavedVariables/Broken.lua"])

    def test_file_gone_since_the_scan_is_reported(self):
        files = self.files()
        (self.extra_sv / "Details.lua").unlink()
        result = run_search(files, SearchSpec(value=SVB_FONT))
        self.assertEqual([f.rel for f, _ in result.unreadable], ["WTF/Account/ACCT1/SavedVariables/Details.lua"])
        self.assertIn("could not read", result.unreadable[0][1])
        self.assertEqual(len(result.hits), 6)

    def test_hits_before_a_fault_are_dropped(self):
        self.add_file("Half.lua", 'HalfDB = {', f'["font"] = "{SVB_FONT}",', '["x"] = ', "}")
        result = self.find(value=SVB_FONT, scope=SearchScope(addon="half"))
        self.assertEqual(result.hits, [])
        self.assertEqual([f.path.name for f, _ in result.unreadable], ["Half.lua"])


class RunTest(SearchTestBase):
    def test_invalid_spec_raises(self):
        with self.assertRaises(ValueError):
            run_search(self.files(), SearchSpec())

    def test_hit_cap_keeps_the_first_hits_and_counts_the_rest(self):
        with mock.patch.object(search, "HIT_CAP", 3):
            result = self.find(key="font", key_mode=KEY_CONTAINS)
        full = self.find(key="font", key_mode=KEY_CONTAINS)
        self.assertEqual(len(result.hits), 3)
        self.assertEqual(result.dropped, len(full.hits) - 3)
        self.assertEqual([where(h) for h in result.hits], [where(h) for h in full.hits[:3]])
        self.assertTrue(result.capped)
        self.assertFalse(full.capped)
        self.assertEqual(full.dropped, 0)

    def test_hits_past_the_cap_are_counted_not_kept(self):
        # M2 review: the cap bounds what a search holds, not just what it returns
        for parallelism in (1, 4):
            kept = []

            def recording(*args, _kept=kept):
                found = search_file(*args)
                _kept.append(found)
                return found

            full = run_search(self.files(), SearchSpec(key="font", key_mode=KEY_CONTAINS), parallelism=parallelism)
            with mock.patch.object(search, "HIT_CAP", 3), \
                    mock.patch.object(search, "search_file", side_effect=recording):
                result = run_search(self.files(), SearchSpec(key="font", key_mode=KEY_CONTAINS),
                                    parallelism=parallelism)
            self.assertEqual([where(h) for h in result.hits], [where(h) for h in full.hits[:3]])
            self.assertEqual(result.dropped, len(full.hits) - 3)
            self.assertLessEqual(sum(len(f.hits) for f in kept), 3, parallelism)

    def test_a_file_with_no_room_builds_no_hit(self):
        file = next(f for f in self.files() if f.path.name == "ElvUI.lua")
        found = search_file(file, SearchSpec(key="font", key_mode=KEY_CONTAINS), room=0)
        self.assertEqual(found.hits, [])
        self.assertGreater(found.extra, 0)
        some = search_file(file, SearchSpec(key="font", key_mode=KEY_CONTAINS), room=1)
        self.assertEqual((len(some.hits), some.extra), (1, found.extra - 1))

    def test_progress_follows_every_file(self):
        calls = []
        files = self.files()
        run_search(files, SearchSpec(key="font"), parallelism=3, progress=lambda *a: calls.append(a))
        self.assertEqual(sorted(c[0] for c in calls), list(range(1, len(files) + 1)))
        self.assertTrue(all(c[1] == len(files) for c in calls))
        self.assertEqual({c[2] for c in calls}, set(files))

    def test_counts_and_events(self):
        with capture_events() as events:
            result = self.find(key="font", value=SVB_FONT, match_case=True, replacement="Arial",
                               scope=SearchScope(flavor="_retail_"))
        self.assertEqual((result.files, len(result.hits), result.dropped), (7, 1, 0))
        self.assertEqual(result.files_with_hits, 1)
        started = [e for e in events if e["event"] == "svb.search_started"]
        completed = [e for e in events if e["event"] == "svb.search_completed"]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["data"]["key"], "font")
        self.assertEqual(started[0]["data"]["files"], 7)
        self.assertEqual(started[0]["data"]["scope"]["flavor"], "_retail_")
        self.assertEqual(len(completed), 1)
        data = completed[0]["data"]
        self.assertEqual((data["files"], data["hits"], data["dropped"], data["unreadable"]), (7, 1, 0, 0))
        self.assertIn("seconds", data)


class StreamingGuardTest(SearchTestBase):
    def test_multi_mb_file_is_searched_quickly(self):
        lines = ["BigDB = {"]
        for i in range(20000):
            lines += [f'["entry{i}"] = {{', f'["font"] = "{SVB_FONT if i % 1000 == 0 else "Arial"}",',
                      f'["text"] = "{"x" * 200}",', f'["size"] = {i},', '["nested"] = {', '"a", -- [1]', "},",
                      "},"]
        lines.append("}")
        path = self.add_file("Big.lua", *lines)
        self.assertGreater(path.stat().st_size, 5_000_000)
        files = [f for f in self.files() if f.path.name == "Big.lua"]
        started = time.monotonic()
        result = run_search(files, SearchSpec(key="font", value=SVB_FONT, replacement="Arial"))
        seconds = time.monotonic() - started
        self.assertEqual(len(result.hits), 20)
        self.assertLess(seconds, 15)


if __name__ == "__main__":
    unittest.main()
