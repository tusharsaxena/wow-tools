"""Config Copier runs (config tools spec CC6, CC8, X5; Review Focus 2): the planned pairs written through the shared
client-file pipeline, the dry run, Undo and recovery, and the text of the confirm and the result. Every client file is
synthesized in a tests/fixtures.py temp tree (build_copier_tree)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import COPIER_ADDONS, COPIER_CHAT, COPIER_LAYOUT, COPIER_MACROS, build_copier_tree

from wowtools.core import client_apply, sv_apply
from wowtools.core.events import capture_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.tools.config_copier import journal, report, undo
from wowtools.tools.config_copier.events import SV_TOOL
from wowtools.tools.config_copier.model import COPY_FILES, MACRO_WARNING
from wowtools.tools.config_copier.planner import plan_copy
from wowtools.tools.config_copier.runner import NAMES, WowRunning, copy_changes, run_copy

WHEN = datetime(2026, 11, 4, 12, 0, 0)


class CopierRunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_copier_tree(self.tmp / "wow")
        self.flavor = WowInstall(self.wow).flavor("_retail_")
        self.root = self.tmp / "out" / "config-copier"
        self.journals = self.tmp / "journal"
        characters = {c.name: c for a in self.flavor.accounts() for c in a.real_characters()}
        self.source, self.bob, self.traxex, self.daenerys = (characters[n] for n in ("Aellâ", "Bob", "Trâxex",
                                                                                     "Dænerys"))

    def run_it(self, plans, **kwargs) -> sv_apply.MultiApplyResult:
        options = {"root": self.root, "journal_dir": self.journals, "keep_journals": 5, "keep_snapshots": 2,
                   "dry_run": False, "wow_check": None, "now": WHEN}
        options.update(kwargs)
        return run_copy(self.flavor, self.source, plans, **options)

    def tree_bytes(self) -> dict[str, bytes]:
        return {p.relative_to(self.wow).as_posix(): p.read_bytes() for p in sorted(self.wow.rglob("*"))
                if p.is_file()}

    def test_names_are_the_five_files(self):
        self.assertEqual(NAMES, frozenset(COPY_FILES))
        self.assertNotIn("cache.md5", NAMES)

    def test_copy_to_two_targets_byte_identical(self):
        plans = plan_copy(self.source, [self.bob, self.traxex], COPY_FILES)
        result = self.run_it(plans)
        self.assertIsNone(result.stopped)
        self.assertEqual(len(result.edited), 10)  # Bob: five replaced or new; Trâxex: five new
        for target in (self.bob, self.traxex):
            for name, data in (("macros-cache.txt", COPIER_MACROS), ("AddOns.txt", COPIER_ADDONS),
                               ("chat-cache.txt", COPIER_CHAT), ("layout-local.txt", COPIER_LAYOUT)):
                self.assertEqual((target.path / name).read_bytes(), data, (target.name, name))
        # config-cache.wtf is merged (CC5): Bob keeps his state CVar, loses his own preference
        bob_config = (self.bob.path / "config-cache.wtf").read_bytes()
        self.assertEqual(bob_config, next(p.new for p in plans if p.target == self.bob
                                          and p.name == "config-cache.wtf"))
        self.assertIn(b'SET hardTrackedQuests "222"', bob_config)
        self.assertNotIn(b"enableMultiActionBars", bob_config)
        self.assertIn(b'SET assistedCombatHighlight "1"', bob_config)
        traxex_config = (self.traxex.path / "config-cache.wtf").read_bytes()
        self.assertNotIn(b"hardTrackedQuests", traxex_config)  # the source's state is never copied
        self.assertNotIn(b"savedClassConfigOne", traxex_config)
        self.assertEqual(sorted(o.detail for o in result.edited).count("created"), 7)
        # the copies of real characters only; nothing else in the tree changed
        self.assertEqual((self.flavor.account_dir / "MAIN" / "Realm1" / "Bob - Copy" / "macros-cache.txt")
                         .read_bytes(), COPIER_MACROS)
        self.assertFalse(list(self.wow.rglob("cache.md5")))
        self.assertFalse(list(self.wow.rglob("*.old")))
        self.assertIsNotNone(result.journal_path)

    def test_non_ascii_bytes_and_paths_round_trip(self):
        """Review Focus 2: Dænerys in a macro body and in a path, Aellâ as the source."""
        plans = plan_copy(self.source, [self.daenerys], ["macros-cache.txt", "chat-cache.txt"])
        self.assertEqual([p.status for p in plans], ["new", "unchanged"])
        self.run_it(plans)
        self.assertEqual((self.daenerys.path / "macros-cache.txt").read_bytes(), COPIER_MACROS)
        self.assertIn("Dænerys".encode(), (self.daenerys.path / "macros-cache.txt").read_bytes())

    def test_unknown_macro_layout_is_copied_byte_for_byte_with_the_warning(self):
        """Review Focus 1: a macros-cache.txt in a layout the reader doesn't know (LF-only, no final END) is never
        parsed into a rewrite: the source's is copied byte for byte, and a target's such file carries the CC7
        warning (it may hold macros)."""
        odd = b'VER 3 0100000000000001 "Odd" "134400"\n/sit\n'
        (self.source.path / "macros-cache.txt").write_bytes(odd)
        (self.bob.path / "macros-cache.txt").write_bytes(b"MACRO 1 \"Old\" INV_Misc_QuestionMark\r\n/sit\r\n")
        plans = plan_copy(self.source, [self.bob, self.traxex], ["macros-cache.txt"])
        self.assertEqual([p.warnings for p in plans], [(MACRO_WARNING,), ()])
        self.run_it(plans)
        self.assertEqual((self.bob.path / "macros-cache.txt").read_bytes(), odd)
        self.assertEqual((self.traxex.path / "macros-cache.txt").read_bytes(), odd)

    def test_unticked_pair_left_alone(self):
        before = self.tree_bytes()
        plans = plan_copy(self.source, [self.bob], COPY_FILES)
        kept = [p for p in plans if p.name != "macros-cache.txt"]  # the user dropped Bob's macros
        self.run_it(kept)
        self.assertEqual((self.bob.path / "macros-cache.txt").read_bytes(),
                         before["_retail_/WTF/Account/MAIN/Realm1/Bob/macros-cache.txt"])
        self.assertEqual((self.bob.path / "AddOns.txt").read_bytes(), COPIER_ADDONS)

    def test_unchanged_and_no_source_pairs_are_never_written(self):
        (self.source.path / "layout-local.txt").unlink()
        (self.daenerys.path / "layout-local.txt").write_bytes(b"MINE\r\n")
        plans = plan_copy(self.source, [self.daenerys], ["chat-cache.txt", "layout-local.txt"])
        self.assertEqual([p.status for p in plans], ["unchanged", "no-source"])
        self.assertEqual(copy_changes(self.source, plans), [])
        result = self.run_it(plans)
        self.assertEqual(result.outcomes, [])
        self.assertEqual((self.daenerys.path / "layout-local.txt").read_bytes(), b"MINE\r\n")

    def test_changes_carry_the_review_hash_and_a_line(self):
        plans = plan_copy(self.source, [self.bob, self.traxex], ["AddOns.txt", "config-cache.wtf"])
        changes = copy_changes(self.source, plans)
        self.assertEqual([c.path for c in changes], [self.bob.path / "AddOns.txt", self.bob.path / "config-cache.wtf",
                                                     self.traxex.path / "AddOns.txt",
                                                     self.traxex.path / "config-cache.wtf"])
        self.assertEqual(changes[0].expected_sha256, plans[0].old_sha256)
        self.assertIsNone(changes[2].expected_sha256)  # created by the run
        self.assertEqual(changes[0].changes, ("AddOns.txt: copied from MAIN/Realm1/Aellâ",))
        self.assertEqual(changes[1].changes, ("config-cache.wtf: merged from MAIN/Realm1/Aellâ",))

    def test_dry_run_changes_nothing(self):
        before = self.tree_bytes()
        plans = plan_copy(self.source, [self.bob, self.traxex], COPY_FILES)
        result = self.run_it(plans, dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertEqual(len(result.would_edit), 10)
        self.assertEqual(self.tree_bytes(), before)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.journals.exists())

    def test_refuses_while_wow_runs(self):
        before = self.tree_bytes()
        plans = plan_copy(self.source, [self.bob], COPY_FILES)
        with self.assertRaises(WowRunning):
            self.run_it(plans, wow_check=lambda: ["Wow.exe"])
        self.assertEqual(self.tree_bytes(), before)

    def test_target_changed_since_the_review_is_skipped(self):
        plans = plan_copy(self.source, [self.bob], ["macros-cache.txt", "AddOns.txt"])
        (self.bob.path / "AddOns.txt").write_bytes(b"changed by WoW\r\n")
        result = self.run_it(plans)
        self.assertEqual([o.file.path.name for o in result.skipped], ["AddOns.txt"])
        self.assertEqual((self.bob.path / "AddOns.txt").read_bytes(), b"changed by WoW\r\n")
        self.assertEqual((self.bob.path / "macros-cache.txt").read_bytes(), COPIER_MACROS)

    def test_undo_restores_and_removes_created(self):
        before = self.tree_bytes()
        result = self.run_it(plan_copy(self.source, [self.bob, self.traxex], COPY_FILES))
        self.assertEqual(journal.latest_undoable(self.journals), result.journal_path)
        log = journal.read_journal(result.journal_path)
        self.assertEqual([f.folder for f in undo.undo_flavors(self.wow, log.entries)], ["_retail_"])
        with capture_events() as events:
            outcome = undo.undo_run(result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2,
                                    now=WHEN)
        self.assertEqual(len(outcome.restored), 10)
        self.assertEqual(self.tree_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.traxex.path.iterdir()), [])
        names = [e["event"] for e in events]
        self.assertIn("copier.file_removed", names)
        self.assertIn("copier.file_restored", names)
        self.assertIsNone(journal.latest_undoable(self.journals))

    def crash(self):
        """A run that created Trâxex's AddOns.txt and replaced Bob's, then died writing Bob's macros with no
        roll-back: its marker stays."""
        plans = plan_copy(self.source, [self.bob, self.traxex], ["macros-cache.txt", "AddOns.txt"])
        plans = [plans[1], plans[3], plans[0]]  # Bob's AddOns.txt, Trâxex's AddOns.txt, then Bob's macros

        def write(path: Path, data: bytes) -> None:
            if path.name == "macros-cache.txt":
                raise OSError("killed")
            atomic_write_bytes(path, data)
        with patch("wowtools.core.sv_apply.restore_original", side_effect=OSError("no")), \
                patch("wowtools.core.sv_apply.remove_created", side_effect=OSError("no")):
            result = client_apply.apply_client_changes(
                SV_TOOL, self.flavor, copy_changes(self.source, plans), names=NAMES, root=self.root,
                journal_dir=self.journals, keep_journals=5, keep_snapshots=2, dry_run=False, wow_check=None,
                now=WHEN, write=write)
        self.assertIsNotNone(result.stopped)
        self.assertEqual((self.traxex.path / "AddOns.txt").read_bytes(), COPIER_ADDONS)
        marker = undo.pending_recovery(self.root)
        self.assertIsNotNone(marker)
        return marker

    def test_recover_after_a_crash_puts_the_originals_back(self):
        before = self.tree_bytes()
        marker = self.crash()
        with capture_events() as events:
            outcome = undo.recover(marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                   keep_snapshots=2, now=WHEN)
        self.assertFalse(outcome.failed)
        self.assertEqual(self.tree_bytes(), before)
        self.assertIsNone(undo.pending_recovery(self.root))
        self.assertIn("copier.file_removed", [e["event"] for e in events])

    def test_leave_keeps_the_files_and_drops_the_marker(self):
        marker = self.crash()
        kept = self.tree_bytes()
        self.assertTrue(undo.leave(marker, root=self.root))
        self.assertIsNone(undo.pending_recovery(self.root))
        self.assertEqual(self.tree_bytes(), kept)


class CopierReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wow = build_copier_tree(Path(tmp.name) / "wow")
        self.flavor = WowInstall(self.wow).flavor("_retail_")
        characters = {c.name: c for a in self.flavor.accounts() for c in a.real_characters()}
        self.source, self.bob, self.traxex = characters["Aellâ"], characters["Bob"], characters["Trâxex"]

    def test_pair_text(self):
        plans = {(p.target.name, p.name): p for p in plan_copy(self.source, [self.bob, self.traxex], COPY_FILES)}
        self.assertEqual(report.pair_text(plans["Bob", "macros-cache.txt"]), "replaced")
        self.assertEqual(report.pair_text(plans["Bob", "config-cache.wtf"]), "replaced (merged)")
        self.assertEqual(report.pair_text(plans["Trâxex", "config-cache.wtf"]), "new (merged)")
        self.assertEqual(report.pair_text(plans["Trâxex", "AddOns.txt"]), "new")
        (self.source.path / "layout-local.txt").unlink()
        [none] = plan_copy(self.source, [self.bob], ["layout-local.txt"])
        self.assertEqual(report.pair_text(none), "source has no file")

    def test_confirm_lists_targets_files_and_the_macro_warning(self):
        plans = plan_copy(self.source, [self.bob, self.traxex], COPY_FILES)
        title, body, alerts = report.copy_confirm(self.source, "_retail_", plans, dry_run=False)
        self.assertEqual(title, "Copy the ticked files?")
        self.assertIn("From MAIN › Realm1/Aellâ (Retail) to 2 characters: 3 files replaced, 7 new.", body)
        self.assertTrue(alerts)
        groups = report.copy_groups(plans)
        self.assertEqual(list(groups), ["MAIN › Realm1/Bob", "MAIN › Realm2/Trâxex"])
        self.assertIn("macros-cache.txt: replaced", groups["MAIN › Realm1/Bob"])
        listed = report.copy_listed(plans)
        self.assertEqual([(entry.message, entry.where, entry.item) for entry in listed],
                         [(MACRO_WARNING, "MAIN › Realm1/Bob", "macros-cache.txt")])
        title, body, alerts = report.copy_confirm(self.source, "_retail_", plans, dry_run=True)
        self.assertEqual((title, alerts), ("Dry run", []))
        self.assertIn("no file is written", body)

    def test_result_rows(self):
        tmp = Path(self.wow).parent
        plans = plan_copy(self.source, [self.traxex], ["AddOns.txt"])
        result = run_copy(self.flavor, self.source, plans, root=tmp / "out", journal_dir=tmp / "journal",
                          keep_journals=5, keep_snapshots=2, dry_run=False, wow_check=None, now=WHEN)
        rows = report.summary_rows(result, self.source)
        self.assertEqual(rows[0], ("Source", "MAIN › Realm1/Aellâ (Retail)"))
        self.assertIn(("Changed", "1 file"), rows)
        self.assertEqual(report.file_rows(result), [("MAIN", "Realm2/Trâxex", "AddOns.txt", "changed: created")])


if __name__ == "__main__":
    unittest.main()
