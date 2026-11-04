"""Config Copier planning: which (target, file) pairs are new, replaced, unchanged or have no source file (config
tools spec CC3, CC4, CC6, CC7; Review Focus 2 and 5)."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_character_tree, cvar_file_bytes, macro_file_bytes
from wowtools.core.events import capture_events
from wowtools.core.install import Character
from wowtools.tools.config_copier.merge import merge_config
from wowtools.tools.config_copier.model import COPY_FILES, MACRO_WARNING, PairPlan
from wowtools.tools.config_copier.planner import plan_copy

ADDONS = "Auctionator: enabled\r\nDetails: enabled\r\nDænerysPack: disabled\r\n".encode()
CHAT = b"VERSION 5\r\n\r\nWINDOW 1\r\nNAME General\r\nEND\r\n"
LAYOUT = b"LAYOUT 1\r\n"
MACROS = macro_file_bytes([("0100000000000001", "Heal Dænerys", "134400", "/cast [@mouseover] Flash Heal"),
                           ("0100000000000002", "D Up", "132360", "/cast Divine Protection")])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        accounts = build_character_tree(Path(self._tmp.name)) / "_retail_" / "WTF" / "Account"

        def char(account: str, realm: str, name: str) -> Character:
            return Character(account, realm, name, accounts / account / realm / name)

        self.source = char("MAIN", "Realm1", "Aellâ")
        self.bob = char("MAIN", "Realm1", "Bob")
        self.traxex = char("MAIN", "Realm2", "Trâxex")
        self.daenerys = char("ALT", "Realm1", "Dænerys")

    def put(self, character: Character, name: str, data: bytes) -> Path:
        path = character.path / name
        path.write_bytes(data)
        return path

    def pairs(self, plans: list[PairPlan]) -> list[tuple[str, str, str]]:
        return [(p.target.name, p.name, p.status) for p in plans]

    def test_copy_files_order(self):
        self.assertEqual(COPY_FILES, ("macros-cache.txt", "AddOns.txt", "chat-cache.txt", "config-cache.wtf",
                                      "layout-local.txt"))

    def test_plain_files_copied_byte_for_byte(self):
        for name, data in (("AddOns.txt", ADDONS), ("chat-cache.txt", CHAT), ("layout-local.txt", LAYOUT)):
            self.put(self.source, name, data)
        old_addons = b"Auctionator: disabled\r\n"
        self.put(self.bob, "AddOns.txt", old_addons)
        # names in any order: the plan follows COPY_FILES' order, targets in the order given
        plans = plan_copy(self.source, [self.bob, self.traxex], ["layout-local.txt", "AddOns.txt", "chat-cache.txt"])
        self.assertEqual(self.pairs(plans), [
            ("Bob", "AddOns.txt", "replace"), ("Bob", "chat-cache.txt", "new"), ("Bob", "layout-local.txt", "new"),
            ("Trâxex", "AddOns.txt", "new"), ("Trâxex", "chat-cache.txt", "new"), ("Trâxex", "layout-local.txt", "new")])
        replaced = plans[0]
        self.assertEqual((replaced.new, replaced.old, replaced.old_sha256), (ADDONS, old_addons, sha(old_addons)))
        self.assertIs(replaced.target, self.bob)
        created = plans[3]
        self.assertEqual((created.new, created.old, created.old_sha256), (ADDONS, None, None))
        self.assertEqual([p.new for p in plans[3:]], [ADDONS, CHAT, LAYOUT])
        self.assertTrue(all(p.warnings == () and p.problem is None for p in plans))

    def test_unchanged_when_identical(self):
        self.put(self.source, "chat-cache.txt", CHAT)
        self.put(self.bob, "chat-cache.txt", CHAT)
        [plan] = plan_copy(self.source, [self.bob], ["chat-cache.txt"])
        self.assertEqual(plan.status, "unchanged")
        self.assertEqual((plan.new, plan.old, plan.old_sha256), (CHAT, CHAT, sha(CHAT)))

    def test_no_source_file_pair(self):
        self.put(self.bob, "layout-local.txt", LAYOUT)
        plans = plan_copy(self.source, [self.bob, self.traxex], ["layout-local.txt"])
        self.assertEqual(self.pairs(plans), [("Bob", "layout-local.txt", "no-source"),
                                             ("Trâxex", "layout-local.txt", "no-source")])
        self.assertTrue(all(p.new is None and p.old is None and p.old_sha256 is None for p in plans))
        self.assertEqual((self.bob.path / "layout-local.txt").read_bytes(), LAYOUT)

    def test_empty_source_file_is_copied_as_empty(self):
        self.put(self.source, "layout-local.txt", b"")
        self.put(self.bob, "layout-local.txt", LAYOUT)
        self.put(self.daenerys, "layout-local.txt", b"")
        plans = plan_copy(self.source, [self.bob, self.traxex, self.daenerys], ["layout-local.txt"])
        self.assertEqual(self.pairs(plans), [("Bob", "layout-local.txt", "replace"),
                                             ("Trâxex", "layout-local.txt", "new"),
                                             ("Dænerys", "layout-local.txt", "unchanged")])
        self.assertEqual([p.new for p in plans], [b"", b"", b""])
        self.assertEqual(plans[2].old_sha256, sha(b""))

    def test_macro_warning_only_when_target_has_macros(self):
        self.put(self.source, "macros-cache.txt", MACROS)
        self.put(self.bob, "macros-cache.txt", macro_file_bytes([("0100000000000001", "Old", "134400", "/sit")]))
        self.put(self.daenerys, "macros-cache.txt", b"")  # a file with no macros: nothing on a bar to lose
        plans = plan_copy(self.source, [self.bob, self.traxex, self.daenerys], ["macros-cache.txt"])
        self.assertEqual(self.pairs(plans), [("Bob", "macros-cache.txt", "replace"),
                                             ("Trâxex", "macros-cache.txt", "new"),
                                             ("Dænerys", "macros-cache.txt", "replace")])
        self.assertEqual([p.warnings for p in plans], [(MACRO_WARNING,), (), ()])
        self.assertEqual(MACRO_WARNING, "Action bar buttons that use macros may need placing again.")
        self.assertEqual(plans[0].new, MACROS)  # Review Focus 2: the non-ASCII body is copied byte for byte

    def test_macro_warning_for_a_target_file_in_an_unknown_layout(self):
        """A target file the reader can't parse may still hold macros, so the warning is shown."""
        self.put(self.source, "macros-cache.txt", MACROS)
        self.put(self.bob, "macros-cache.txt", b'MACRO 1 "Old" INV_Misc_QuestionMark\n/sit\nEND\n')
        [plan] = plan_copy(self.source, [self.bob], ["macros-cache.txt"])
        self.assertEqual((plan.status, plan.warnings), ("replace", (MACRO_WARNING,)))

    def test_no_macro_warning_when_unchanged(self):
        self.put(self.source, "macros-cache.txt", MACROS)
        self.put(self.bob, "macros-cache.txt", MACROS)
        [plan] = plan_copy(self.source, [self.bob], ["macros-cache.txt"])
        self.assertEqual((plan.status, plan.warnings), ("unchanged", ()))

    def test_config_pair_is_the_merge(self):
        source = cvar_file_bytes([("assistedCombatHighlight", "1"), ("savedClassConfigOne", "src")])
        target = cvar_file_bytes([("enableMultiActionBars", "15"), ("savedClassConfigOne", "tgt")])
        self.put(self.source, "config-cache.wtf", source)
        self.put(self.bob, "config-cache.wtf", target)
        plans = plan_copy(self.source, [self.bob, self.traxex], ["config-cache.wtf"])
        self.assertEqual(self.pairs(plans), [("Bob", "config-cache.wtf", "replace"),
                                             ("Trâxex", "config-cache.wtf", "new")])
        self.assertEqual(plans[0].new, merge_config(source, target))
        self.assertEqual(plans[1].new, merge_config(source, None))

    def test_config_unchanged_when_only_state_differs(self):
        self.put(self.source, "config-cache.wtf", cvar_file_bytes([("autoLootDefault", "1"),
                                                                   ("hardTrackedQuests", "1,2")]))
        target = cvar_file_bytes([("hardTrackedQuests", "9"), ("autoLootDefault", "1")])
        self.put(self.bob, "config-cache.wtf", target)
        [plan] = plan_copy(self.source, [self.bob], ["config-cache.wtf"])
        self.assertEqual((plan.status, plan.new), ("unchanged", target))

    def test_unreadable_files(self):
        self.put(self.source, "chat-cache.txt", CHAT)
        (self.bob.path / "chat-cache.txt").mkdir()  # not a file: it can't be read or replaced
        (self.source.path / "layout-local.txt").mkdir()
        with capture_events() as events:
            plans = plan_copy(self.source, [self.bob, self.traxex], ["chat-cache.txt", "layout-local.txt"])
        self.assertEqual(self.pairs(plans), [
            ("Bob", "chat-cache.txt", "unreadable"), ("Bob", "layout-local.txt", "unreadable"),
            ("Trâxex", "chat-cache.txt", "new"), ("Trâxex", "layout-local.txt", "unreadable")])
        self.assertIn("could not be read", plans[0].problem)
        self.assertTrue(all(p.new is None for p in plans if p.status == "unreadable"))
        unreadable = [e for e in events if e["event"] == "copier.file_unreadable"]
        self.assertEqual(sorted(Path(e["data"]["path"]).name for e in unreadable),
                         ["chat-cache.txt", "layout-local.txt"])  # the source's once, not per target
        [planned] = [e for e in events if e["event"] == "copier.planned"]
        self.assertEqual(planned["data"]["counts"], {"new": 1, "unreadable": 3})

    def test_config_value_the_merge_cannot_write_is_unreadable(self):
        # A lone CR inside a source value can't be written back into a target's file: that pair is unreadable and
        # every other pair still plans (T23w4).
        self.put(self.source, "config-cache.wtf", b'SET foo "a\rb"\r\n')
        self.put(self.bob, "config-cache.wtf", b'SET foo "x"\r\n')
        self.put(self.source, "AddOns.txt", ADDONS)
        with capture_events() as events:
            plans = plan_copy(self.source, [self.bob, self.traxex], ["AddOns.txt", "config-cache.wtf"])
        self.assertEqual(self.pairs(plans), [
            ("Bob", "AddOns.txt", "new"), ("Bob", "config-cache.wtf", "unreadable"),
            ("Trâxex", "AddOns.txt", "new"), ("Trâxex", "config-cache.wtf", "new")])
        self.assertIn("line break", plans[1].problem)
        self.assertIsNone(plans[1].new)
        self.assertEqual([Path(e["data"]["path"]).parent.name for e in events
                          if e["event"] == "copier.file_unreadable"], ["Bob"])

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            plan_copy(self.source, [self.bob], ["bindings-cache.wtf"])  # X4 / CC3: only the five files
        with self.assertRaises(ValueError):
            plan_copy(self.source, [self.bob], ["macros-cache - Copy.txt"])
        with self.assertRaises(ValueError):
            plan_copy(self.source, [self.bob, self.source], ["AddOns.txt"])  # CC2: the source is never a target

    def test_nothing_is_written(self):
        self.put(self.source, "AddOns.txt", ADDONS)
        self.put(self.bob, "AddOns.txt", b"old\r\n")
        before = sorted(p.relative_to(self._tmp.name) for p in Path(self._tmp.name).rglob("*"))
        plan_copy(self.source, [self.bob, self.traxex], COPY_FILES)
        self.assertEqual(sorted(p.relative_to(self._tmp.name) for p in Path(self._tmp.name).rglob("*")), before)
        self.assertEqual((self.bob.path / "AddOns.txt").read_bytes(), b"old\r\n")


if __name__ == "__main__":
    unittest.main()
