"""The client-file write pipeline (config tools spec X5): core/client_apply.py on top of the shared SavedVariables
pipeline (core/sv_apply.py, sv_undo.py, sv_journal.py), driven by a made-up tool with its own event prefix. Every
client file is synthesized here in a tests/fixtures.py temp tree."""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core import client_apply, sv_apply, sv_journal
from wowtools.core.client_apply import (ClientChange, ClientFileGuard, apply_client_changes, apply_client_flavors,
                                        client_destination, client_undo_flavors, recover_client_run, undo_client_run)
from wowtools.core.events import TOOL_REGISTRIES, capture_events, register_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.core.sv_events import SvTool, client_events, sv_events
from wowtools.core.svfiles import SvFileError, sha256_of

TOOL = SvTool("test-client-pipeline", "tcl")
register_events(TOOL.name, client_events(TOOL.prefix))
WHEN = datetime(2026, 11, 4, 12, 0, 0)
NAMES = frozenset({"macros-cache.txt", "chat-cache.txt", "config-cache.wtf", "AddOns.txt", "Config.wtf"})
MACROS = b'VER 3 0100000000000001 "D Up" "132360"\r\n/cast Divine Shield\r\nEND\r\n'
NEW_MACROS = b'VER 3 0100000000000001 "D Up" "134400"\r\n/cast [@mouseover] Divine Shield\r\nEND\r\n'
CHAT = b'VERSION 5\r\n\r\nWINDOW 1\r\nNAME "General"\r\nEND\r\n'


class ClientApplyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_wow_tree(self.tmp / "wow")
        self.flavor = WowInstall(self.wow).flavor("_retail_")
        self.root = self.tmp / "out" / TOOL.name
        self.journals = self.tmp / "journal"
        self.char = self.flavor.account_dir / "ACCT1" / "Realm1" / "CharA"
        self.macros = self.char / "macros-cache.txt"
        self.macros.write_bytes(MACROS)
        self.chat = self.char / "chat-cache.txt"  # does not exist yet: the run creates it

    def change(self, path: Path, new: bytes, expected: bytes | None = None, *, absent: bool = False) -> ClientChange:
        if absent:
            return ClientChange(path, new, None)
        return ClientChange(path, new, sha256_of(path.read_bytes() if expected is None else expected))

    def run_apply(self, changes, **kwargs):
        options = {"names": NAMES, "root": self.root, "journal_dir": self.journals, "keep_journals": 5,
                   "keep_snapshots": 2, "dry_run": False, "wow_check": None, "now": WHEN}
        options.update(kwargs)
        return apply_client_changes(TOOL, self.flavor, changes, **options)

    def undo(self, journal_path, **kwargs):
        return undo_client_run(TOOL, journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2,
                               names=NAMES, now=WHEN, **kwargs)

    def rel(self, path: Path) -> str:
        return path.relative_to(self.flavor.path).as_posix()

    # --- the events -------------------------------------------------------------------------------------------

    def test_client_events_add_created_and_removed_to_the_pipeline_events(self):
        events = client_events("xyz")
        self.assertEqual(set(events) - set(sv_events("xyz")), {"xyz.file_created", "xyz.file_removed"})
        self.assertNotIn("SavedVariables", events["xyz.file_edited"].description)
        self.assertEqual(TOOL_REGISTRIES[TOOL.name]["tcl.file_created"].level, "info")

    # --- apply and undo ---------------------------------------------------------------------------------------

    def test_replace_and_create_then_undo(self):
        with capture_events() as events:
            result = self.run_apply([self.change(self.macros, NEW_MACROS), self.change(self.chat, CHAT, absent=True)])
        names = [e["event"] for e in events]
        for name in ("tcl.apply_started", "tcl.snapshot_taken", "tcl.files_backed_up", "tcl.file_edited",
                     "tcl.file_created", "tcl.apply_completed"):
            self.assertIn(name, names)
        self.assertIsNone(result.stopped)
        self.assertEqual(len(result.edited), 2)
        self.assertEqual(self.macros.read_bytes(), NEW_MACROS)
        self.assertEqual(self.chat.read_bytes(), CHAT)
        self.assertEqual(sorted(o.detail for o in result.edited), ["", "created"])
        self.assertIsNone(sv_apply.read_marker(self.root))
        run = result.runs[0].result
        with zipfile.ZipFile(run.snapshot) as zf:
            self.assertIn(self.rel(self.macros), zf.namelist())
        with zipfile.ZipFile(run.backup_zip) as zf:  # the originals of the replaced file only
            self.assertEqual(sorted(n for n in zf.namelist() if n != "manifest.json"), [self.rel(self.macros)])
            self.assertEqual(zf.read(self.rel(self.macros)), MACROS)
        journal = sv_journal.read_edit_journal(result.journal_path)
        actions = {e["rel"]: e["action"] for e in journal.entries}
        self.assertEqual(actions, {self.rel(self.macros): "edited", self.rel(self.chat): "created"})
        self.assertEqual(TOOL.journals.latest_undoable(self.journals), result.journal_path)
        self.assertEqual([f.folder for f in client_undo_flavors(self.wow, journal.entries, NAMES)], ["_retail_"])
        with capture_events() as events:
            undone = self.undo(result.journal_path)
        names = [e["event"] for e in events]
        self.assertIn("tcl.file_restored", names)
        self.assertIn("tcl.file_removed", names)
        self.assertEqual(len(undone.restored), 2)
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertFalse(self.chat.exists())
        self.assertIsNone(TOOL.journals.latest_undoable(self.journals))

    def test_a_run_that_only_creates_still_has_an_originals_zip(self):
        result = self.run_apply([self.change(self.chat, CHAT, absent=True)])
        run = result.runs[0].result
        with zipfile.ZipFile(run.backup_zip) as zf:
            self.assertEqual(zf.namelist(), ["manifest.json"])
        undone = self.undo(result.journal_path)
        self.assertEqual(len(undone.restored), 1)
        self.assertFalse(self.chat.exists())

    def test_dry_run_writes_nothing(self):
        result = self.run_apply([self.change(self.macros, NEW_MACROS), self.change(self.chat, CHAT, absent=True)],
                                dry_run=True)
        self.assertEqual(len(result.would_edit), 2)
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertFalse(self.chat.exists())
        self.assertFalse(self.root.exists())
        self.assertFalse(self.journals.exists())

    def test_refuses_when_wow_running(self):
        with capture_events() as events, self.assertRaises(sv_apply.WowRunning):
            self.run_apply([self.change(self.macros, NEW_MACROS), self.change(self.chat, CHAT, absent=True)],
                           wow_check=lambda: ["Wow.exe"])
        self.assertIn("tcl.wow_running", [e["event"] for e in events])
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertFalse(self.chat.exists())
        self.assertFalse(self.root.exists())
        self.assertFalse(self.journals.exists())

    def test_wow_check_runs_at_apply_time(self):
        """The check is called when Apply runs, not when the review was built (Review Focus 3)."""
        calls = []
        changes = [self.change(self.macros, NEW_MACROS)]
        self.assertEqual(calls, [])
        with self.assertRaises(sv_apply.WowRunning):
            self.run_apply(changes, wow_check=lambda: calls.append(1) or ["Wow.exe"])
        self.assertEqual(calls, [1])

    def test_changed_on_disk_is_refused(self):
        stale = self.change(self.macros, NEW_MACROS, expected=b"what the review saw")
        with capture_events() as events:
            result = self.run_apply([stale])
        self.assertIn("tcl.file_changed", [e["event"] for e in events])
        self.assertEqual([o.detail for o in result.skipped], [sv_apply.CHANGED])
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertIsNone(result.journal_path)
        self.assertFalse(self.journals.exists() and any(self.journals.iterdir()))
        self.assertFalse((self.root / sv_apply.EDITED_SUBDIR).exists())

    def test_a_stale_file_is_skipped_and_the_rest_written(self):
        """The pipeline's rules: a file changed since the review is skipped, the others are written."""
        result = self.run_apply([self.change(self.macros, NEW_MACROS, expected=b"stale"),
                                 self.change(self.chat, CHAT, absent=True)])
        self.assertEqual((len(result.edited), len(result.skipped)), (1, 1))
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertEqual(self.chat.read_bytes(), CHAT)

    def test_created_file_already_exists_is_refused(self):
        self.chat.write_bytes(b"made by the client meanwhile")
        result = self.run_apply([self.change(self.chat, CHAT, absent=True)])
        self.assertEqual([o.detail for o in result.skipped], [client_apply.EXISTS])
        self.assertEqual(self.chat.read_bytes(), b"made by the client meanwhile")
        self.assertIsNone(result.journal_path)

    def test_a_file_that_appears_just_before_the_write_is_never_replaced(self):
        """It appears after the check, before the write loop: the write refuses it, never replaces it."""
        real_write = sv_apply.write_marker

        def appear(root, marker):
            real_write(root, marker)
            self.chat.write_bytes(b"client")
        with patch("wowtools.core.sv_apply.write_marker", side_effect=appear):
            result = self.run_apply([self.change(self.chat, CHAT, absent=True)])
        self.assertEqual([o.detail for o in result.skipped], [client_apply.EXISTS])
        self.assertEqual(self.chat.read_bytes(), b"client")
        self.assertIsNone(sv_apply.read_marker(self.root))

    def test_guard_refuses_unlisted_and_outside(self):
        guard = ClientFileGuard(self.flavor, NAMES)
        acct = self.flavor.account_dir / "ACCT1"
        refused = [
            self.char / "macros-cache - Copy.txt",  # not a client-named file
            self.char / "SavedVariables" / "Auctionator.lua",  # a SavedVariables file
            acct / "SavedVariables" / "macros-cache.txt",  # listed name, but inside SavedVariables
            self.char / "cache.md5",  # never touched (V2)
            self.char / "macros-cache.txt.old",
            self.flavor.wtf_dir / "macros-cache.txt",  # outside WTF/Account
            self.tmp / "elsewhere" / "macros-cache.txt",  # outside the flavor
            self.flavor.path / "macros-cache.txt",
            acct / "Realm1" / "CharA - Copy" / "macros-cache.txt",  # not a real character (X3)
            acct / "Realm1" / "CharA" / "Sub" / "macros-cache.txt",  # too deep
            acct / "Realm1" / "macros-cache.txt",  # a realm folder
            acct / "Config.wtf",  # Config.wtf only in WTF itself
            self.char / ".." / "CharA" / "macros-cache.txt",
        ]
        for path in refused:
            with self.subTest(path=path), self.assertRaises(SvFileError):
                guard.check(path)
        for path in (self.macros, acct / "config-cache.wtf", self.flavor.wtf_dir / "Config.wtf",
                     acct / "Realm1" / "Aellâ" / "macros-cache.txt"):
            with self.subTest(path=path):
                self.assertEqual(guard.check(path).name, path.name)
        with self.assertRaises(SvFileError):
            ClientFileGuard(self.flavor, frozenset({"macros-cache.txt"})).check(self.flavor.wtf_dir / "Config.wtf")
        with self.assertRaises(SvFileError):  # a listed name is still refused where a SavedVariables file sits
            ClientFileGuard(self.flavor, frozenset({"Auctionator.lua"})).check(
                self.char / "SavedVariables" / "Auctionator.lua")

    def test_guard_refuses_a_link(self):
        target = self.tmp / "elsewhere"
        target.mkdir()
        (target / "macros-cache.txt").write_bytes(MACROS)
        link = self.flavor.account_dir / "ACCT1" / "Realm1" / "Linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        with self.assertRaises(SvFileError):
            ClientFileGuard(self.flavor, NAMES).check(link / "macros-cache.txt")

    def test_apply_stops_on_a_guarded_path_before_writing(self):
        bad = self.char / "macros-cache - Copy.txt"
        bad.write_bytes(MACROS)
        result = self.run_apply([self.change(self.macros, NEW_MACROS), self.change(bad, NEW_MACROS)])
        self.assertIsNotNone(result.stopped)
        self.assertIn("Refusing", result.stopped.error)
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertEqual(bad.read_bytes(), MACROS)

    def test_client_destination(self):
        dest = client_destination(NAMES)
        self.assertEqual(dest(self.wow, "_retail_", "WTF/Account/A/R/Char/macros-cache.txt"),
                         self.wow / "_retail_" / "WTF" / "Account" / "A" / "R" / "Char" / "macros-cache.txt")
        self.assertEqual(dest(self.wow, "_retail_", "WTF/Config.wtf"), self.wow / "_retail_" / "WTF" / "Config.wtf")
        self.assertIsNotNone(dest(self.wow, "_retail_", "WTF/Account/A/config-cache.wtf"))
        for rel in ("WTF/Account/A/R/Char/cache.md5", "WTF/Account/A/SavedVariables/x.lua",
                    "WTF/Account/A/R/Char - Copy/macros-cache.txt", "WTF/Account/../../x/macros-cache.txt",
                    "WTF/macros-cache.txt", "Interface/AddOns/macros-cache.txt", "WTF/Account/A/Config.wtf"):
            with self.subTest(rel=rel):
                self.assertIsNone(dest(self.wow, "_retail_", rel))
        self.assertIsNone(dest(self.wow, "../x", "WTF/Config.wtf"))

    # --- failure, undo skips, recovery -------------------------------------------------------------------------

    def test_a_failure_rolls_back_and_removes_the_created_file(self):
        def write(path, data):
            raise OSError("disk full")
        result = self.run_apply([self.change(self.chat, CHAT, absent=True), self.change(self.macros, NEW_MACROS)],
                                write=write)
        self.assertIsNotNone(result.stopped)
        self.assertIn("put back", result.stopped.error)
        self.assertFalse(self.chat.exists())
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertIsNone(sv_apply.read_marker(self.root))
        self.assertIsNone(TOOL.journals.latest_undoable(self.journals))

    def test_a_created_file_left_after_a_failure_is_not_sent_to_the_zip(self):
        """Only a created file could not be undone: the message says to delete it, not to unzip it."""
        def write(path, data):
            raise OSError("disk full")
        with patch("wowtools.core.sv_apply.remove_created", side_effect=OSError("locked")):
            result = self.run_apply([self.change(self.chat, CHAT, absent=True), self.change(self.macros, NEW_MACROS)],
                                    write=write)
        error = result.stopped.error
        self.assertNotIn("unzip", error)
        self.assertNotIn("could not be put back", error)
        self.assertIn("this run created could not be removed", error)
        self.assertTrue(self.chat.exists())
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertIsNotNone(sv_apply.read_marker(self.root))  # recovery can still remove it

    def test_undo_skips_file_changed_since(self):
        result = self.run_apply([self.change(self.macros, NEW_MACROS), self.change(self.chat, CHAT, absent=True)])
        self.macros.write_bytes(b"WoW saved it at logout")
        self.chat.write_bytes(b"and this one")
        undone = self.undo(result.journal_path)
        self.assertEqual(len(undone.restored), 0)
        self.assertEqual(len(undone.skipped), 2)
        self.assertEqual(self.macros.read_bytes(), b"WoW saved it at logout")
        self.assertEqual(self.chat.read_bytes(), b"and this one")

    def test_undo_skips_a_created_file_already_gone(self):
        result = self.run_apply([self.change(self.chat, CHAT, absent=True)])
        self.chat.unlink()
        undone = self.undo(result.journal_path)
        self.assertEqual([o.detail for o in undone.skipped], ["the file is gone"])
        self.assertFalse(self.chat.exists())

    def test_undo_refuses_while_wow_runs(self):
        result = self.run_apply([self.change(self.chat, CHAT, absent=True)])
        with self.assertRaises(sv_apply.WowRunning):
            self.undo(result.journal_path, wow_check=lambda: ["Wow.exe"])
        self.assertEqual(self.chat.read_bytes(), CHAT)

    def test_undo_never_touches_an_entry_outside_the_names(self):
        """A hand-edited journal entry naming another file is skipped (STD-5.25)."""
        result = self.run_apply([self.change(self.chat, CHAT, absent=True)])
        other = self.char / "cache.md5"
        other.write_bytes(CHAT)
        text = result.journal_path.read_text(encoding="utf-8").replace("chat-cache.txt", "cache.md5")
        result.journal_path.write_text(text, encoding="utf-8")
        undone = self.undo(result.journal_path)
        self.assertEqual([o.detail for o in undone.skipped], ["it is outside the WTF folder"])
        self.assertTrue(other.exists())

    def test_recover_after_crash_marker(self):
        """The run created one file and replaced another, then died writing the third with no roll-back: the
        marker is left, and recovery removes the created file and puts the replaced one back."""
        config = self.flavor.account_dir / "ACCT1" / "config-cache.wtf"
        original_config = config.read_bytes()

        def write(path, data):
            if path == config:
                raise OSError("killed")
            atomic_write_bytes(path, data)
        with patch("wowtools.core.sv_apply.restore_original", side_effect=OSError("no")), \
                patch("wowtools.core.sv_apply.remove_created", side_effect=OSError("no")):
            result = self.run_apply([self.change(self.chat, CHAT, absent=True), self.change(self.macros, NEW_MACROS),
                                     self.change(config, b'SET x "2"\r\n')], write=write)
        self.assertIsNotNone(result.stopped)
        self.assertEqual(self.chat.read_bytes(), CHAT)
        self.assertEqual(self.macros.read_bytes(), NEW_MACROS)
        # A created file has no original in the zip: its advice is to delete it, never to unzip it (T6r).
        error = result.stopped.error
        self.assertIn("1 file(s) could not be put back", error)
        self.assertIn("1 file(s) this run created could not be removed", error)
        self.assertIn("delete them by hand", error)
        details = {o.file.rel: o.detail for o in result.stopped.result.outcomes if o.status == "failed"}
        self.assertIn("could not be removed", details[self.rel(self.chat)])
        self.assertNotIn(".zip", details[self.rel(self.chat)])
        self.assertIn("its original is in", details[self.rel(self.macros)])
        marker = sv_apply.read_marker(self.root)
        self.assertIsNotNone(marker)
        self.assertEqual(marker.created, [self.rel(self.chat)])
        self.assertNotIn(self.rel(self.chat), marker.files)
        with capture_events() as events:
            recovered = recover_client_run(TOOL, marker, wow_root=self.wow, root=self.root, names=NAMES,
                                           journal_dir=self.journals, now=WHEN)
        names = [e["event"] for e in events]
        self.assertIn("tcl.file_removed", names)
        self.assertIn("tcl.recovery_done", names)
        self.assertEqual(len(recovered.restored), 2)
        self.assertFalse(self.chat.exists())
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertEqual(config.read_bytes(), original_config)
        self.assertIsNone(sv_apply.read_marker(self.root))
        self.assertIsNone(TOOL.journals.latest_undoable(self.journals))

    def test_recover_leaves_a_created_file_the_client_rewrote(self):
        def write(path, data):
            if path == self.macros:
                raise OSError("killed")
            atomic_write_bytes(path, data)
        with patch("wowtools.core.sv_apply.remove_created", side_effect=OSError("no")):
            self.run_apply([self.change(self.chat, CHAT, absent=True), self.change(self.macros, NEW_MACROS)],
                           write=write)
        marker = sv_apply.read_marker(self.root)
        self.chat.write_bytes(b"the client wrote it since")
        recovered = recover_client_run(TOOL, marker, wow_root=self.wow, root=self.root, names=NAMES,
                                       journal_dir=self.journals, now=WHEN)
        self.assertEqual([o.rel for o in recovered.skipped], [self.rel(self.chat)])
        self.assertEqual(self.chat.read_bytes(), b"the client wrote it since")

    def test_recovery_of_a_finished_run_changes_nothing(self):
        captured, real_write = [], sv_apply.write_marker

        def keep(root, marker):
            captured.append(marker)
            real_write(root, marker)
        with patch("wowtools.core.sv_apply.write_marker", side_effect=keep):
            self.run_apply([self.change(self.macros, NEW_MACROS), self.change(self.chat, CHAT, absent=True)])
        sv_apply.write_marker(self.root, captured[0])  # as if removing it had failed
        recovered = recover_client_run(TOOL, sv_apply.read_marker(self.root), wow_root=self.wow, root=self.root,
                                       names=NAMES, journal_dir=self.journals, now=WHEN)
        self.assertTrue(recovered.stale_marker)
        self.assertEqual(self.chat.read_bytes(), CHAT)
        self.assertEqual(self.macros.read_bytes(), NEW_MACROS)

    def test_non_ascii_character_path_round_trip(self):
        char = self.flavor.account_dir / "ACCT1" / "Realm1" / "Aellâ"
        char.mkdir(parents=True)
        macros = char / "macros-cache.txt"
        body = 'VER 3 0100000000000002 "Dænerys" "INV_Misc_QuestionMark"\r\n/say Trâxex\r\nEND\r\n'.encode()
        macros.write_bytes(body)
        new = body.replace(b"/say", b"/yell")
        result = self.run_apply([self.change(macros, new), self.change(char / "chat-cache.txt", CHAT, absent=True)])
        self.assertEqual(len(result.edited), 2)
        self.assertEqual(macros.read_bytes(), new)
        with zipfile.ZipFile(result.runs[0].result.backup_zip) as zf:
            self.assertEqual(zf.read(self.rel(macros)), body)
        undone = self.undo(result.journal_path)
        self.assertEqual(len(undone.restored), 2)
        self.assertEqual(macros.read_bytes(), body)
        self.assertFalse((char / "chat-cache.txt").exists())

    def test_several_flavors_in_one_run_and_one_undo(self):
        """The Macro Editor's Apply across flavors (ME13): every flavor's changes in one journal, one Undo; each
        flavor's guard only takes its own folder, and the WoW check runs once for them all."""
        era = WowInstall(self.wow).flavor("_classic_era_")
        era_macros = era.account_dir / "ACCT1" / "macros-cache.txt"
        checked = []
        progress = []
        result = apply_client_flavors(
            TOOL, [(self.flavor, [self.change(self.macros, NEW_MACROS)]),
                   (era, [self.change(era_macros, MACROS, absent=True)])],
            names=NAMES, root=self.root, journal_dir=self.journals, keep_journals=5, keep_snapshots=2,
            dry_run=False, wow_check=lambda: checked.append(1) or [], now=WHEN,
            progress=lambda flavor, stage, *rest: progress.append(flavor.folder))
        self.assertEqual(checked, [1])
        self.assertIsNone(result.stopped)
        self.assertEqual([run.flavor.folder for run in result.runs], ["_retail_", "_classic_era_"])
        self.assertEqual(len(result.edited), 2)
        self.assertEqual(set(progress), {"_retail_", "_classic_era_"})
        self.assertEqual((self.macros.read_bytes(), era_macros.read_bytes()), (NEW_MACROS, MACROS))
        journal = sv_journal.read_edit_journal(result.journal_path)
        self.assertEqual(sorted({e["flavor"] for e in journal.entries}), ["_classic_era_", "_retail_"])
        undone = self.undo(result.journal_path)
        self.assertEqual(len(undone.restored), 2)
        self.assertEqual(self.macros.read_bytes(), MACROS)
        self.assertFalse(era_macros.exists())

    def test_a_flavor_guard_refuses_another_flavors_file(self):
        era = WowInstall(self.wow).flavor("_classic_era_")
        result = apply_client_flavors(
            TOOL, [(era, [self.change(self.macros, NEW_MACROS)])], names=NAMES, root=self.root,
            journal_dir=self.journals, keep_journals=5, keep_snapshots=2, dry_run=False, wow_check=None, now=WHEN)
        self.assertIsNotNone(result.stopped)
        self.assertEqual(self.macros.read_bytes(), MACROS)

    def test_never_writes_cache_md5_or_old_files(self):
        self.run_apply([self.change(self.macros, NEW_MACROS), self.change(self.chat, CHAT, absent=True)])
        self.assertEqual(sorted(p.name for p in self.char.iterdir() if p.is_file()),
                         ["AddOns.txt", "chat-cache.txt", "macros-cache.txt"])


if __name__ == "__main__":
    unittest.main()
