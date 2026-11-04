"""Macro Editor optimizer: each rule in wowtools/kb/optimizer_rules.json, with the input and output the rule's stated
reason makes the same in game (config tools spec ME10; plan T14)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wowtools.core import kb
from wowtools.tools.macro_editor.explain import explain_block
from wowtools.tools.macro_editor.optimizer import RULES, Rewrite, optimize
from wowtools.tools.macro_editor.syntax import lines


def texts(body: str) -> list[str]:
    """The text of every command and chat line (spell and item names, chat text, code), in order: what no rule may
    change. A #showtooltip's own argument is left out: showtooltip_same drops it."""
    return [t.text for line in lines(body) if line.head is None or line.head.kind != "directive"
            for t in line.tokens if t.kind in ("text", "comment")]


class OptimizerCase(unittest.TestCase):
    def setUp(self):
        kb.clear_cache()
        self.addCleanup(kb.clear_cache)

    def assertRule(self, before: str, after: str, rule: str):
        got, rewrites = optimize(before)
        self.assertEqual(got, after)
        self.assertTrue(rewrites, rewrites)
        self.assertEqual({r.rule for r in rewrites}, {rule})
        info = kb.load_optimizer_rules()[rule]
        for r in rewrites:
            self.assertIsInstance(r, Rewrite)
            self.assertEqual((r.reason, r.source), (info.reason, info.source))
            self.assertNotEqual(r.before, r.after)
        self.assertEqual(texts(got), texts(before))
        self.assertEqual(optimize(got), (got, []))  # a second pass finds nothing


class RulesDataTest(OptimizerCase):
    def test_every_rule_has_a_source_and_an_implementation(self):
        data = json.loads((kb.KB_ROOT / "optimizer_rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data["rules"]), set(RULES))
        for rule_id, info in kb.load_optimizer_rules().items():
            with self.subTest(rule=rule_id):
                self.assertEqual(info.id, rule_id)
                self.assertTrue(info.title and info.reason)
                self.assertTrue(info.source.startswith("https://"))

    def test_only_rules_in_the_kb_are_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "optimizer_rules.json").write_text(json.dumps({"rules": {
                "target_to_at": {"title": "t", "reason": "r", "source": "https://x", "automatic": True}}}),
                encoding="utf-8")
            body = "/cast [target=focus, harm] Polymorph"
            got, rewrites = optimize(body, rules=kb.load_optimizer_rules(root=Path(tmp)))
        self.assertEqual(got, "/cast [@focus, harm] Polymorph")
        self.assertEqual([r.rule for r in rewrites], ["target_to_at"])
        self.assertEqual(optimize(body, rules={}), (body, []))


class RuleTest(OptimizerCase):
    def test_rule_target_to_at(self):
        # target= is the old spelling of @ (Macro conditionals: "target= ... Alias for @").
        self.assertRule("/cast [target=mouseover,help] Renew\n/focus [target=mouseover]",
                        "/cast [@mouseover,help] Renew\n/focus [@mouseover]", "target_to_at")

    def test_rule_strip_spaces(self):
        # The parser ignores spaces between conditionals, inside [] and after ; (the wiki's own example
        # `[@mouseover, help] [ ] Flash of Light` works as written).
        self.assertRule("/cast [ @mouseover, help ] [ ] Flash of Light; Renew",
                        "/cast [@mouseover,help][] Flash of Light;Renew", "strip_spaces")

    def test_rule_duplicate_conditions(self):
        # Conditionals in one [] are joined by AND, so a repeated one adds nothing.
        self.assertRule("/cast [help,nodead,help] Renew", "/cast [help,nodead] Renew", "duplicate_conditions")

    def test_duplicate_units_are_kept(self):
        # Of several units in one [] one wins; dropping a repeat could change which, so units are never dropped.
        ref = kb.load_macro_reference("_retail_")
        for body in ("/cast [@focus,@target,@focus] Polymorph", "/cast [target=focus,@target,@focus] Polymorph"):
            with self.subTest(body=body):
                got, _ = optimize(body)
                self.assertIn("[@focus,@target,@focus]", got)
                block = got[got.index("["):got.index("]") + 1]
                self.assertEqual(explain_block(block, ref), explain_block(body[body.index("["):body.index("]") + 1], ref))
        self.assertEqual(optimize("/cast [@focus,help,@focus,help] Renew")[0], "/cast [@focus,help,@focus] Renew")

    def test_rule_showtooltip_same_spell(self):
        # With no argument #showtooltip shows the macro's first spell, which is the one named.
        self.assertRule("#showtooltip Flash Heal\n/cast [@mouseover,help][] Flash Heal",
                        "#showtooltip\n/cast [@mouseover,help][] Flash Heal", "showtooltip_same")

    def test_showtooltip_kept_when_it_names_another_spell(self):
        for body in ("#showtooltip Renew\n/cast Flash Heal",
                     "#showtooltip Flash Heal\n/cast [mod] Renew;Flash Heal",
                     "#showtooltip Flash Heal\n/cast [help] Flash Heal",           # no fallback clause
                     "#showtooltip Flash Heal\n/use 13\n/cast Flash Heal",          # the first line uses an item
                     "#showtooltip Flash Heal\n/castsequence Flash Heal, Renew"):
            with self.subTest(body=body):
                self.assertEqual(optimize(body), (body, []))

    def test_rule_cast_to_use_is_never_applied(self):
        # Blizzard's /cast prefers a spell and /use an item when a name is both, so the swap is not provably the
        # same: the rule is in the KB with automatic false, and optimize leaves the line alone.
        info = kb.load_optimizer_rules()["cast_to_use"]
        self.assertFalse(info.automatic)
        self.assertIn("/use", info.reason)
        body = "/cast Hearthstone"
        self.assertEqual(optimize(body), (body, []))

    def test_rules_together(self):
        body = "#showtooltip Renew\n/cast [ target=mouseover, help, help ] [ ] Renew"
        got, rewrites = optimize(body)
        self.assertEqual(got, "#showtooltip\n/cast [@mouseover,help][] Renew")
        self.assertEqual([r.rule for r in rewrites],
                         ["target_to_at", "duplicate_conditions", "strip_spaces", "showtooltip_same"])

    def test_optimize_never_changes_spell_text(self):
        bodies = ("/cast [@focus] Holy Light , Rank 2; target=x",
                  "/say [target=focus, help] go ;  now",
                  "/run print('target=focus, help')",
                  "/castsequence reset=target Berserking, Icy Veins",
                  "# a note [target=focus , help]",
                  "/cast [ help ]  Flash  Heal ;  Renew  ")
        for body in bodies:
            with self.subTest(body=body):
                got, _ = optimize(body)
                self.assertEqual(texts(got), texts(body))
        self.assertEqual(optimize(bodies[1]), (bodies[1], []))  # chat text untouched
        self.assertEqual(optimize(bodies[2]), (bodies[2], []))
        self.assertEqual(optimize(bodies[4]), (bodies[4], []))
        self.assertEqual(optimize("")[0], "")


if __name__ == "__main__":
    unittest.main()
