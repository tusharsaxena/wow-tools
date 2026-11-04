"""Macro Editor model and staging: scan, paste, edit, new, delete, Replace text and the bytes they build (config
tools spec ME3, ME4, ME5, ME6, ME7, ME13; Review Focus 1 and 2)."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_character_tree, macro_file_bytes
from wowtools.core.events import capture_events
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.macrofile import BODY_LIMIT, ICON_DEFAULT, NAME_LIMIT, Macro, parse_macros
from wowtools.tools.macro_editor.model import MACRO_FILE, MacroSet
from wowtools.tools.macro_editor.ops import (Staged, build_changes, effective_macros, free_slots, preview_replace,
                                             rename_for_clash, stage_delete, stage_edit, stage_new, stage_paste,
                                             stage_replace_text)
from wowtools.tools.macro_editor.scanner import scan_sets

AELLA = macro_file_bytes([("0100000000000001", "Heal Dænerys", "134400", "/cast [@mouseover] Flash Heal"),
                          ("0100000000000002", "D Up", "132360", "/cast Divine Protection"),
                          ("01000000000000ED", "Bubble", "INV_Misc_QuestionMark", "#showtooltip\n/cast Divine Shield")])
BOB = macro_file_bytes([("0100000000000001", "Bob", "134400", "/sit"),
                        ("0100000000000003", "D Up", "134400", "/cast Flash of Light")])
ACCOUNT = macro_file_bytes([("00000000000000ED", "Mount", "134400", "/cast Swift Horse")])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MacroEditorOpsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = build_character_tree(Path(self._tmp.name))
        self.accounts = self.root / "_retail_" / "WTF" / "Account"
        self.put("MAIN/Realm1/Aellâ", AELLA)
        self.put("MAIN/Realm1/Bob", BOB)
        self.put("MAIN", ACCOUNT)
        self.put("MAIN/Realm1/Bob - Copy", AELLA)  # not a character (X3): never a set
        self.flavor = WowInstall(self.root).flavor("_retail_")
        self.sets = scan_sets(self.flavor)

    def put(self, rel: str, data: bytes, flavor: str = "_retail_") -> Path:
        path = self.root / flavor / "WTF" / "Account" / rel / MACRO_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def set_of(self, label: str, sets: list[MacroSet] | None = None) -> MacroSet:
        for mset in sets if sets is not None else self.sets:
            name = mset.character.name if mset.character else "Account macros"
            if f"{mset.account.name}/{name}" == label:
                return mset
        raise AssertionError(f"no set {label}")

    def macro(self, mset: MacroSet, name: str) -> Macro:
        return next(m for m in mset.parsed.macros if m.name == name)

    def written(self, staged: Staged, sets: list[MacroSet] | None = None) -> dict[Path, bytes]:
        return {change.path: change.new for change in build_changes(staged, sets if sets is not None else self.sets)}

    # scan ---------------------------------------------------------------------------------------------------------

    def test_scan_lists_account_and_real_characters(self):
        labels = [(s.account.name, s.character.name if s.character else None, s.scope) for s in self.sets]
        self.assertEqual(labels, [("ALT", None, "account"), ("ALT", "Dænerys", "character"),
                                  ("BARE", None, "account"),
                                  ("MAIN", None, "account"), ("MAIN", "Aellâ", "character"),
                                  ("MAIN", "Bob", "character"), ("MAIN", "Trâxex", "character")])
        account = self.set_of("MAIN/Account macros")
        self.assertEqual((account.limit, account.path, account.sha256), (120, self.accounts / "MAIN" / MACRO_FILE,
                                                                         sha(ACCOUNT)))
        aella = self.set_of("MAIN/Aellâ")
        self.assertEqual((aella.limit, aella.data, [m.name for m in aella.parsed.macros]),
                         (30, AELLA, ["Heal Dænerys", "D Up", "Bubble"]))
        traxex = self.set_of("MAIN/Trâxex")  # missing file = empty set, created by a run
        self.assertEqual((traxex.data, traxex.sha256, traxex.parsed.macros, traxex.parsed.known_layout),
                         (b"", None, (), True))
        self.assertFalse(traxex.read_only)

    def test_scan_unknown_layout_is_read_only(self):
        self.put("ALT/Realm1/Dænerys", AELLA.replace(b"\r\n", b"\n"))
        dae = self.set_of("ALT/Dænerys", scan_sets(self.flavor))
        self.assertTrue(dae.read_only)
        self.assertIn("CRLF", dae.parsed.problem)
        staged = Staged()
        with self.assertRaises(ValueError):
            stage_new(staged, dae, name="X", body="/sit")
        self.assertEqual(stage_paste(staged, self.set_of("MAIN/Bob").parsed.macros[:1], dae,
                                     lambda new, old: "overwrite"),
                         [f"{dae.label}: read-only ({dae.parsed.problem}); Bob was not pasted."])
        self.assertEqual(staged.changes, {})

    def test_scan_unreadable_file_is_read_only_and_logged(self):
        bad = self.accounts / "ALT" / "Realm1" / "Dænerys" / MACRO_FILE
        bad.mkdir()  # a folder by that name cannot be read as a file
        with capture_events() as events:
            dae = self.set_of("ALT/Dænerys", scan_sets(self.flavor))
        self.assertTrue(dae.read_only)
        self.assertIn("could not be read", dae.parsed.problem)
        self.assertEqual([e["event"] for e in events if e["event"] == "macro.file_unreadable"],
                         ["macro.file_unreadable"])

    # paste --------------------------------------------------------------------------------------------------------

    def test_paste_new_gets_next_id_and_prefix(self):
        aella, bob, account = self.set_of("MAIN/Aellâ"), self.set_of("MAIN/Bob"), self.set_of("MAIN/Account macros")
        staged = Staged()
        heal, bubble = self.macro(aella, "Heal Dænerys"), self.macro(aella, "Bubble")
        never = lambda new, old: self.fail("no clash expected")
        self.assertEqual(stage_paste(staged, [heal, bubble], bob, never), [])
        self.assertEqual(stage_paste(staged, [heal], account, never), [])
        self.assertEqual([(m.id, m.name) for m in effective_macros(staged, bob)],
                         [("0100000000000001", "Bob"), ("0100000000000003", "D Up"),
                          ("0100000000000004", "Heal Dænerys"), ("0100000000000005", "Bubble")])
        self.assertEqual([(m.id, m.name, m.icon, m.body) for m in effective_macros(staged, account)][-1],
                         ("00000000000000EE", "Heal Dænerys", "134400", "/cast [@mouseover] Flash Heal"))
        written = self.written(staged)
        self.assertEqual(written[bob.path], BOB + macro_file_bytes([
            ("0100000000000004", "Heal Dænerys", "134400", "/cast [@mouseover] Flash Heal"),
            ("0100000000000005", "Bubble", "INV_Misc_QuestionMark",
             "#showtooltip\n/cast Divine Shield")]))
        self.assertEqual(written[account.path], ACCOUNT + macro_file_bytes([
            ("00000000000000EE", "Heal Dænerys", "134400", "/cast [@mouseover] Flash Heal")]))

    def test_paste_into_empty_set_creates_the_file(self):
        aella, traxex = self.set_of("MAIN/Aellâ"), self.set_of("MAIN/Trâxex")
        staged = Staged()
        self.assertEqual(stage_paste(staged, [self.macro(aella, "D Up")], traxex, lambda n, o: "skip"), [])
        (change,) = build_changes(staged, self.sets)
        self.assertEqual((change.path, change.expected_sha256), (traxex.path, None))
        self.assertEqual(change.new, macro_file_bytes([("0100000000000001", "D Up", "132360",
                                                        "/cast Divine Protection")]))
        self.assertEqual(change.changes, ('macros-cache.txt: added "D Up"',))

    def test_paste_overwrite_keeps_target_id(self):
        aella, bob = self.set_of("MAIN/Aellâ"), self.set_of("MAIN/Bob")
        clashes = []

        def on_clash(new: Macro, old: Macro) -> str:
            clashes.append((new.name, old.id))
            return "overwrite"

        staged = Staged()
        self.assertEqual(stage_paste(staged, [self.macro(aella, "D Up")], bob, on_clash), [])
        self.assertEqual(clashes, [("D Up", "0100000000000003")])
        self.assertEqual([(m.id, m.name, m.icon, m.body) for m in effective_macros(staged, bob)],
                         [("0100000000000001", "Bob", "134400", "/sit"),
                          ("0100000000000003", "D Up", "132360", "/cast Divine Protection")])
        written = self.written(staged)[bob.path]
        self.assertEqual(written, macro_file_bytes([("0100000000000001", "Bob", "134400", "/sit"),
                                                    ("0100000000000003", "D Up", "132360",
                                                     "/cast Divine Protection")]))

    def test_paste_skip_changes_nothing(self):
        aella, bob = self.set_of("MAIN/Aellâ"), self.set_of("MAIN/Bob")
        staged = Staged()
        self.assertEqual(stage_paste(staged, [self.macro(aella, "D Up")], bob, lambda n, o: "skip"), [])
        self.assertEqual(build_changes(staged, self.sets), [])

    def test_paste_rename_cuts_to_16(self):
        self.assertEqual(rename_for_clash("D Up", {"D Up"}), "D Up 2")
        self.assertEqual(rename_for_clash("D Up", {"D Up", "D Up 2", "D Up 3"}), "D Up 4")
        self.assertEqual(rename_for_clash("Celestial Condui", {"Celestial Condui"}), "Celestial Cond 2")
        self.assertEqual(rename_for_clash("Celestial Cond 2", {"Celestial Cond 2"}), "Celestial Cond 3")
        long = "A" * 15 + " "
        self.assertEqual(len(rename_for_clash(long, {long})), NAME_LIMIT)
        aella, bob = self.set_of("MAIN/Aellâ"), self.set_of("MAIN/Bob")
        staged = Staged()
        self.assertEqual(stage_paste(staged, [self.macro(aella, "D Up")], bob, lambda n, o: "rename"), [])
        self.assertEqual([(m.id, m.name) for m in effective_macros(staged, bob)][-1], ("0100000000000004", "D Up 2"))
        # the same macro pasted again: "D Up" and "D Up 2" are both taken now
        self.assertEqual(stage_paste(staged, [self.macro(aella, "D Up")], bob, lambda n, o: "rename"), [])
        self.assertEqual([m.name for m in effective_macros(staged, bob)][-1], "D Up 3")

    def test_paste_refused_when_slots_full(self):
        full = macro_file_bytes([(f"01{n:014X}", f"M{n}", "134400", "/sit") for n in range(1, 30)])  # 29 of 30
        self.put("MAIN/Realm2/Trâxex", full)
        sets = scan_sets(self.flavor)
        traxex, aella = self.set_of("MAIN/Trâxex", sets), self.set_of("MAIN/Aellâ", sets)
        self.assertEqual(free_slots(Staged(), traxex), 1)
        staged = Staged()
        refusals = stage_paste(staged, aella.parsed.macros, traxex, lambda n, o: "rename")
        self.assertEqual(refusals, [f"{traxex.label}: no free macro slot (30/30); D Up was not pasted.",
                                    f"{traxex.label}: no free macro slot (30/30); Bubble was not pasted."])
        self.assertEqual([m.name for m in effective_macros(staged, traxex)][-1], "Heal Dænerys")
        self.assertEqual(free_slots(staged, traxex), 0)
        # a paste without a clash needs a slot; an overwrite does not
        refused = f"{traxex.label}: no free macro slot (30/30); D Up was not pasted."
        self.assertEqual(stage_paste(staged, [self.macro(aella, "D Up")], traxex, lambda n, o: self.fail("no clash")),
                         [refused])
        m1 = Macro("0100000000000099", "M1", "1", "/dance", (0, 0))
        self.assertEqual(stage_paste(staged, [m1], traxex, lambda n, o: "overwrite"), [])
        with self.assertRaises(ValueError):
            stage_new(staged, traxex, name="More", body="/sit")

    def test_cross_flavor_paste_allowed(self):
        self.put("ACCT/Realm1/Other", b"", flavor="_classic_era_")
        classic = Flavor("_classic_era_", self.root / "_classic_era_")
        csets = scan_sets(classic)
        other = self.set_of("ACCT/Other", csets)
        self.assertEqual(other.limit, 30)  # no sourced entry for Classic Era: Retail's values (ME3, T8)
        aella = self.set_of("MAIN/Aellâ")
        staged = Staged()
        self.assertEqual(stage_paste(staged, [self.macro(aella, "Heal Dænerys")], other, lambda n, o: "skip"), [])
        (change,) = build_changes(staged, [*self.sets, *csets])
        self.assertEqual((change.path, change.expected_sha256), (other.path, sha(b"")))
        self.assertEqual(change.new, macro_file_bytes([("0100000000000001", "Heal Dænerys", "134400",
                                                        "/cast [@mouseover] Flash Heal")]))

    # edit, new, delete --------------------------------------------------------------------------------------------

    def test_edit_keeps_id(self):
        aella = self.set_of("MAIN/Aellâ")
        staged = Staged()
        stage_edit(staged, aella, "0100000000000002", name="Shield Up", icon="132361", body="/cast Shield\n/say up")
        stage_edit(staged, aella, "0100000000000002", name="Shield Up", icon="132361", body="/cast Shield")
        self.assertEqual([(m.id, m.name) for m in effective_macros(staged, aella)],
                         [("0100000000000001", "Heal Dænerys"), ("0100000000000002", "Shield Up"),
                          ("01000000000000ED", "Bubble")])
        expected = macro_file_bytes([("0100000000000001", "Heal Dænerys", "134400", "/cast [@mouseover] Flash Heal"),
                                     ("0100000000000002", "Shield Up", "132361", "/cast Shield"),
                                     ("01000000000000ED", "Bubble", "INV_Misc_QuestionMark",
                                      "#showtooltip\n/cast Divine Shield")])
        (change,) = build_changes(staged, self.sets)
        self.assertEqual((change.new, change.expected_sha256, change.changes),
                         (expected, sha(AELLA), ('macros-cache.txt: changed "Shield Up"',)))
        with self.assertRaises(ValueError):
            stage_edit(staged, aella, "0100000000000002", name="X", icon="1", body="x" * (BODY_LIMIT + 1))
        with self.assertRaises(ValueError):
            stage_edit(staged, aella, "0100000000000002", name="X", icon="1", body="/say a\nEND")
        with self.assertRaises(ValueError):
            stage_edit(staged, aella, "01000000000000AA", name="X", icon="1", body="/sit")
        with self.assertRaises(ValueError):
            stage_edit(staged, aella, "0100000000000002", name="", icon="1", body="/sit")

    def test_edit_back_to_the_original_writes_nothing(self):
        aella = self.set_of("MAIN/Aellâ")
        staged = Staged()
        stage_edit(staged, aella, "0100000000000002", name="Other", icon="132360", body="/cast Divine Protection")
        stage_edit(staged, aella, "0100000000000002", name="D Up", icon="132360", body="/cast Divine Protection")
        self.assertEqual(build_changes(staged, self.sets), [])

    def test_new_edit_and_delete_of_a_staged_macro(self):
        bob = self.set_of("MAIN/Bob")
        staged = Staged()
        new_id = stage_new(staged, bob, name="A" * 20, body="/wave")
        self.assertEqual(new_id, "0100000000000004")
        added = effective_macros(staged, bob)[-1]
        self.assertEqual((added.name, added.icon), ("A" * NAME_LIMIT, ICON_DEFAULT))
        stage_edit(staged, bob, new_id, name="Wave", icon="134400", body="/wave\n/cheer")
        self.assertEqual(staged.changes[bob.path][-1].kind, "add")
        self.assertEqual(self.written(staged)[bob.path],
                         BOB + macro_file_bytes([(new_id, "Wave", "134400", "/wave\n/cheer")]))
        stage_delete(staged, bob, new_id)
        self.assertEqual(build_changes(staged, self.sets), [])
        # the dropped add never reached the file, so its id is free again
        self.assertEqual(stage_new(staged, bob, name="Next", body=""), "0100000000000004")

    def test_delete_and_its_id_is_not_reused(self):
        aella = self.set_of("MAIN/Aellâ")
        staged = Staged()
        stage_delete(staged, aella, "01000000000000ED")
        with self.assertRaises(ValueError):
            stage_delete(staged, aella, "01000000000000ED")
        with self.assertRaises(ValueError):
            stage_edit(staged, aella, "01000000000000ED", name="X", icon="1", body="")
        self.assertEqual(stage_new(staged, aella, name="New", body="/sit"), "01000000000000EE")
        (change,) = build_changes(staged, self.sets)
        self.assertEqual(change.new, AELLA[:aella.parsed.macros[2].span[0]] + macro_file_bytes(
            [("01000000000000EE", "New", ICON_DEFAULT, "/sit")]))
        self.assertEqual(change.changes, ('macros-cache.txt: deleted "Bubble"', 'macros-cache.txt: added "New"'))

    # Replace text -------------------------------------------------------------------------------------------------

    def test_replace_text_counts_and_previews(self):
        aella, bob = self.set_of("MAIN/Aellâ"), self.set_of("MAIN/Bob")
        picks = [(aella, self.macro(aella, "Heal Dænerys")), (aella, self.macro(aella, "D Up")),
                 (bob, self.macro(bob, "D Up")), (bob, self.macro(bob, "Bob"))]
        staged = Staged()
        rows = preview_replace(staged, picks, "flash", "Holy", case=False)
        self.assertEqual([(r.macro.name, r.before, r.after, r.count, r.refusal) for r in rows],
                         [("Heal Dænerys", "/cast [@mouseover] Flash Heal", "/cast [@mouseover] Holy Heal", 1, None),
                          ("D Up", "/cast Flash of Light", "/cast Holy of Light", 1, None)])
        self.assertEqual(preview_replace(staged, picks, "flash", "Holy", case=True), [])
        self.assertEqual(staged.changes, {})  # a preview stages nothing
        self.assertEqual(stage_replace_text(staged, picks, "flash", "Holy", case=False), 2)
        self.assertEqual([m.body for m in effective_macros(staged, bob)], ["/sit", "/cast Holy of Light"])
        # a second replace works on the staged text
        self.assertEqual(stage_replace_text(staged, picks, "Holy Heal", "Heal", case=True), 1)
        written = self.written(staged)
        self.assertIn(b"/cast [@mouseover] Heal\r\n", written[aella.path])
        self.assertEqual(stage_replace_text(staged, picks, "", "x", case=True), 0)

    def test_replace_over_255_is_refused_for_that_macro(self):
        aella = self.set_of("MAIN/Aellâ")
        picks = [(aella, m) for m in aella.parsed.macros]
        staged = Staged()
        rows = preview_replace(staged, picks, "Divine", "D" * 240, case=True)
        self.assertEqual([(r.macro.name, r.refusal is None) for r in rows], [("D Up", False), ("Bubble", False)])
        self.assertIn("255", rows[0].refusal)
        self.assertEqual(stage_replace_text(staged, picks, "Divine", "D" * 240, case=True), 0)
        rows = preview_replace(staged, picks, "Divine", "D" * 230, case=True)  # 247 and 256 characters
        self.assertEqual([(r.macro.name, r.refusal is None) for r in rows], [("D Up", True), ("Bubble", False)])
        self.assertEqual(stage_replace_text(staged, picks, "Divine", "D" * 230, case=True), 1)
        self.assertEqual(len(effective_macros(staged, aella)[1].body), len("/cast  Protection") + 230)
        self.assertEqual(effective_macros(staged, aella)[2].body, "#showtooltip\n/cast Divine Shield")

    # bytes --------------------------------------------------------------------------------------------------------

    def test_build_changes_byte_exact_elsewhere(self):
        aella, bob = self.set_of("MAIN/Aellâ"), self.set_of("MAIN/Bob")
        staged = Staged()
        stage_edit(staged, aella, "0100000000000002", name="D Up", icon="132360", body="/cast Divine Protection\n/y")
        changes = build_changes(staged, self.sets)
        self.assertEqual([c.path for c in changes], [aella.path])
        new = changes[0].new
        _heal, dup, bubble = aella.parsed.macros
        self.assertEqual(new[:dup.span[0]], AELLA[:dup.span[0]])
        self.assertEqual(new[-(bubble.span[1] - bubble.span[0]):], AELLA[bubble.span[0]:bubble.span[1]])
        self.assertEqual(parse_macros(new).macros[1].body, "/cast Divine Protection\n/y")
        self.assertNotIn(bob.path, [c.path for c in changes])
        with self.assertRaises(ValueError):  # a set the caller did not pass
            build_changes(staged, [bob])

    def test_bytes_that_are_not_utf8_survive_a_paste(self):
        latin = b'VER 3 0100000000000001 "Caf\xe9" "134400"\r\n/say caf\xe9\r\nEND\r\n'
        self.put("ALT/Realm1/Dænerys", latin)
        sets = scan_sets(self.flavor)
        dae, traxex = self.set_of("ALT/Dænerys", sets), self.set_of("MAIN/Trâxex", sets)
        self.assertFalse(dae.read_only)
        staged = Staged()
        self.assertEqual(stage_paste(staged, dae.parsed.macros, traxex, lambda n, o: "skip"), [])
        (change,) = build_changes(staged, sets)
        self.assertEqual(change.new, latin)

    def test_staged_count_and_clear(self):
        aella, bob = self.set_of("MAIN/Aellâ"), self.set_of("MAIN/Bob")
        staged = Staged()
        self.assertEqual(staged.count(), 0)
        stage_delete(staged, aella, "0100000000000001")
        stage_new(staged, bob, name="X", body="")
        self.assertEqual(staged.count(), 2)
        staged.clear()
        self.assertEqual((staged.count(), staged.changes), (0, {}))


if __name__ == "__main__":
    unittest.main()
