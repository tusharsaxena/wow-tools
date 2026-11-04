"""Macro Editor syntax help: the tokenizer, the plain-English explainer, the flavor check, suggestions, templates and
the macro reference data (config tools spec ME5, ME8, ME11, X6, X7; plan T14). Every test reads the shipped KB or a
temp KB folder; nothing touches a real WoW install or the network."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from wowtools.core import kb
from wowtools.core.events import capture_events
from wowtools.core.macrofile import BODY_LIMIT
from wowtools.tools.macro_editor.explain import explain_block, unknown_terms
from wowtools.tools.macro_editor.syntax import suggestions, token_at, tokenize
from wowtools.tools.macro_editor.templates import MacroTemplate, fill_template, load_templates

CLICK_CAST = "#showtooltip\n/cast [@mouseover,help,nodead][] Flash Heal\n/stopcasting [mod:alt]"
URL = "https://"


class KbCase(unittest.TestCase):
    def setUp(self):
        kb.clear_cache()
        self.addCleanup(kb.clear_cache)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def temp_kb(self, slash: dict[str, str] | None, flavor: str = "_retail_") -> Path:
        """A temp KB with the shipped reference and, if given, a slash dump for the flavor."""
        shutil.copy(kb.KB_ROOT / "macro_reference.json", self.root / "macro_reference.json")
        if slash is not None:
            (self.root / "slash_commands").mkdir(exist_ok=True)
            (self.root / "slash_commands" / f"{flavor}.json").write_text(json.dumps(
                {"flavor": flavor, "build": "1", "source": f"client dump {flavor} 1", "commands": slash}),
                encoding="utf-8")
        return self.root


class TokenizeTest(unittest.TestCase):
    def test_tokenize_click_cast_macro(self):
        tokens = tokenize(CLICK_CAST)
        self.assertEqual([(t.kind, t.text) for t in tokens], [
            ("directive", "#showtooltip"),
            ("command", "/cast"),
            ("condition_block", "[@mouseover,help,nodead]"), ("unit", "@mouseover"), ("condition", "help"),
            ("condition", "nodead"),
            ("condition_block", "[]"),
            ("text", "Flash Heal"),
            ("command", "/stopcasting"),
            ("condition_block", "[mod:alt]"), ("condition", "mod:alt"),
        ])
        for token in tokens:  # every span is the token's own text
            self.assertEqual(CLICK_CAST[token.start:token.end], token.text)

    def test_tokenize_target_equals_spaces_and_clauses(self):
        body = "/cast [ target=focus , harm ] Polymorph; [@player] Frost Nova"
        kinds = [(t.kind, t.text) for t in tokenize(body)]
        self.assertIn(("unit", "target=focus"), kinds)
        self.assertIn(("condition", "harm"), kinds)
        self.assertIn(("text", "Polymorph"), kinds)
        self.assertIn(("text", "Frost Nova"), kinds)
        for token in tokenize(body):
            self.assertEqual(body[token.start:token.end], token.text)

    def test_chat_text_and_comments_are_not_conditions(self):
        tokens = tokenize("/say [help] me; now\n# my note\n/run print(1)")
        self.assertEqual([(t.kind, t.text) for t in tokens], [
            ("command", "/say"), ("text", "[help] me; now"), ("comment", "# my note"), ("command", "/run"),
            ("text", "print(1)")])

    def test_token_at_returns_the_innermost_token(self):
        offset = CLICK_CAST.index("help")
        self.assertEqual(token_at(CLICK_CAST, offset).text, "help")
        self.assertEqual(token_at(CLICK_CAST, offset + 4).text, "help")  # cursor just after the word
        self.assertEqual(token_at(CLICK_CAST, CLICK_CAST.index("[]") + 1).kind, "condition_block")
        self.assertEqual(token_at(CLICK_CAST, 3).text, "#showtooltip")
        self.assertIsNone(token_at("", 0))
        self.assertIsNone(token_at("/cast  x", 6))  # between the command and its argument


class ExplainTest(KbCase):
    def setUp(self):
        super().setUp()
        self.ref = kb.load_macro_reference("_retail_")

    def test_explain_mouseover_help_nodead(self):
        self.assertEqual(explain_block("[@mouseover,help,nodead]", self.ref),
                         "Cast on the unit under the mouse, if it's friendly and not dead.")

    def test_explain_other_blocks(self):
        self.assertEqual(explain_block("[]", self.ref), "Always.")
        self.assertEqual(explain_block("[target=focus]", self.ref), "Cast on your focus.")
        self.assertEqual(explain_block("[harm,nodead]", self.ref), "Cast, if your target is hostile and not dead.")
        self.assertEqual(explain_block("[mod:shift,nocombat]", self.ref),
                         "Cast, if Shift is held and you're not in combat.")
        self.assertEqual(explain_block("[@focustarget,exists]", self.ref), "Cast on your focus's target, if it exists.")
        self.assertEqual(explain_block("[@party2]", self.ref), "Cast on party member 2.")
        self.assertIn("frobnicate (not in the reference)", explain_block("[frobnicate]", self.ref))

    def test_unknown_terms_flags_missing_command(self):
        ref = kb.load_macro_reference("_retail_", root=self.temp_kb({"/cast": "CAST", "/stopcasting": "STOPCASTING"}))
        self.assertEqual(unknown_terms("/cast X\n/castnope Y\n/STOPCASTING\n/castnope Z", ref), ["/castnope"])

    def test_unknown_terms_silent_when_flavor_not_stated(self):
        # No slash dump: commands are unknown, not flagged. `help` names no flavors: never flagged.
        ref = kb.load_macro_reference("_classic_era_", root=self.temp_kb(None))
        self.assertIsNone(ref.slash_commands)
        self.assertEqual(unknown_terms("/castnope [help,nodead] Y", ref), [])

    def test_unknown_terms_flags_a_conditional_the_flavor_lacks(self):
        ref = kb.load_macro_reference("_classic_era_", root=self.temp_kb(None))
        self.assertEqual(unknown_terms("/cast [advflyable] Swift Mount; [noadvflyable] Slow Mount", ref),
                         ["advflyable"])
        retail = kb.load_macro_reference("_retail_", root=self.root)
        self.assertEqual(unknown_terms("/cast [advflyable] Swift Mount", retail), [])

    def test_suggestions_after_at(self):
        body = "/cast [@mo"
        got = dict(suggestions(body, len(body), self.ref))
        self.assertIn("mouseover", got)
        self.assertTrue(got["mouseover"])
        self.assertNotIn("player", got)

    def test_suggestions_for_commands_and_conditionals(self):
        commands = dict(suggestions("/stopc", 6, self.ref))
        self.assertIn("/stopcasting", commands)
        conditions = dict(suggestions("/cast [help,nod", 15, self.ref))
        self.assertIn("nodead", conditions)
        self.assertNotEqual(conditions["nodead"], dict(suggestions("/cast [help,d", 13, self.ref))["dead"])
        self.assertEqual(conditions["nodead"], "The unit is not dead.")  # the `no` form's own reading
        self.assertEqual(suggestions("/say hel", 8, self.ref), [])  # chat text gets nothing


class ReferenceDataTest(KbCase):
    def test_reference_entries_have_sources(self):
        data = json.loads((kb.KB_ROOT / "macro_reference.json").read_text(encoding="utf-8"))
        flavors = {"_retail_", "_classic_", "_classic_era_", "_anniversary_", "_forever_"}
        for section in ("commands", "conditionals", "units"):
            self.assertTrue(data[section], section)
            for name, entry in data[section].items():
                with self.subTest(section=section, name=name):
                    self.assertTrue(entry["source"].startswith(URL), entry)
                    self.assertTrue(entry["help"], entry)
                    self.assertIn("flavors", entry)
                    self.assertTrue(entry["flavors"] is None or set(entry["flavors"]) <= flavors, entry)
        for name, entry in data["conditionals"].items():
            with self.subTest(conditional=name):
                self.assertTrue(entry["explain"] and entry["explain_no"], entry)

    def test_reference_loads_with_aliases(self):
        ref = kb.load_macro_reference("_retail_")
        self.assertEqual(ref.flavor, "_retail_")
        self.assertIs(ref.conditionals["mod"], ref.conditionals["modifier"])
        self.assertTrue(ref.commands["/cast"].options)
        self.assertFalse(ref.commands["/say"].options)
        self.assertIn("mouseover", ref.units)
        for group in ("targets", "unit", "states"):
            self.assertTrue(ref.builder[group], group)
        self.assertIn("@mouseover", ref.builder["targets"])

    def test_unsourced_entries_are_not_loaded(self):
        (self.root / "macro_reference.json").write_text(json.dumps({"commands": {
            "/cast": {"help": "Cast it.", "source": "", "flavors": None},
            "/use": {"help": "Use it.", "source": "https://example.org", "flavors": None}}}), encoding="utf-8")
        ref = kb.load_macro_reference("_retail_", root=self.root)
        self.assertNotIn("/cast", ref.commands)
        self.assertIn("/use", ref.commands)

    def test_missing_or_bad_reference_reads_empty(self):
        self.assertEqual(kb.load_macro_reference("_retail_", root=self.root).commands, {})
        (self.root / "macro_reference.json").write_text("{nope", encoding="utf-8")
        kb.clear_cache()
        with capture_events() as records:
            ref = kb.load_macro_reference("_retail_", root=self.root)
        self.assertEqual(ref.conditionals, {})
        self.assertEqual([r["event"] for r in records], ["kb.unreadable"])
        self.assertEqual(explain_block("[help]", ref), "Cast, if help (not in the reference).")


class TemplatesTest(KbCase):
    def test_templates_have_sources_and_placeholders(self):
        templates = load_templates()
        self.assertGreaterEqual(len(templates), 10)
        ids = [t.id for t in templates]
        self.assertEqual(len(ids), len(set(ids)))
        for wanted in ("mouseover-heal", "cursor-ground", "focus-interrupt", "self-cast-fallback",
                       "stopcasting-interrupt", "modifier-alternate", "trinket-and-spell", "pet-attack",
                       "target-of-target-help", "mount"):
            self.assertIn(wanted, ids)
        for t in templates:
            with self.subTest(template=t.id):
                self.assertTrue(t.source.startswith(URL) and t.title)
                self.assertTrue(t.placeholders)
                for name in t.placeholders:
                    self.assertIn("{" + name + "}", t.body)
                filled = fill_template(t, {name: "X" * 20 for name in t.placeholders})
                self.assertNotIn("{", filled)
                self.assertLessEqual(len(filled), BODY_LIMIT)

    def test_fill_template_needs_every_value(self):
        t = MacroTemplate("x", "X", "/cast [@mouseover] {Heal spell}", ("Heal spell",), URL)
        self.assertEqual(fill_template(t, {"Heal spell": "Flash Heal"}), "/cast [@mouseover] Flash Heal")
        with self.assertRaises(ValueError):
            fill_template(t, {})
        with self.assertRaises(ValueError):
            fill_template(t, {"Heal spell": "a\nb"})

    def test_templates_without_sources_are_dropped(self):
        (self.root / "macro_templates.json").write_text(json.dumps({"templates": [
            {"id": "a", "title": "A", "body": "/cast {S}", "placeholders": ["S"], "source": ""},
            {"id": "b", "title": "B", "body": "/cast {S}", "placeholders": ["S"], "source": URL + "x"}]}),
            encoding="utf-8")
        self.assertEqual([t.id for t in kb.load_templates(root=self.root)], ["b"])


if __name__ == "__main__":
    unittest.main()
