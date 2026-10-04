from __future__ import annotations

import unittest
from pathlib import Path

from wowtools.core.install import Flavor
from wowtools.core.journal import Journal
from wowtools.tools.interface_backup import report
from wowtools.tools.interface_backup.backup import BackupOutcome
from wowtools.tools.interface_backup.catalog import BackupInfo
from wowtools.tools.interface_backup.restore import BackupContents, PartOutcome, RestorePlan, RestoreResult
from wowtools.tools.interface_backup.scanner import FileInfo, FlavorScan, PartScan

RETAIL = Flavor("_retail_", Path("/wow/_retail_"))


def scan(sizes: bool = True) -> FlavorScan:
    size = 100 if sizes else None
    parts = {"Interface": PartScan("Interface", RETAIL.path / "Interface", True, False,
                                   [FileInfo("AddOns/A/a.lua", size, 1.0)], ["AddOns/Dev"]),
             "WTF": PartScan("WTF", RETAIL.path / "WTF")}
    return FlavorScan(RETAIL, parts, [RETAIL.path / "WTF.replaced"])


def plan(removed=(), newer=(), kept=(), dropped=(), free=None, unreadable=(), current=None) -> RestorePlan:
    contents = BackupContents(Path("/bk/backup-retail-20261004-153012.zip"), "backup", "retail", "_retail_", "",
                              ("Interface", "WTF"), {"Interface": {}, "WTF": {}})
    return RestorePlan(contents, RETAIL, ("Interface",), list(removed), list(newer), list(kept), list(dropped),
                       1000, free, [], list(unreadable), current)


def info(stamp: str, kind: str = "backup", size: int = 2048) -> BackupInfo:
    return BackupInfo(Path(f"/bk/{kind}-retail-{stamp}.zip"), kind, "retail", stamp, 1, size)


class ReportTest(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(report.human_size(None), "—")
        self.assertEqual(report.human_size(512), "512 B")
        self.assertEqual(report.human_size(1536), "1.5 KB")
        self.assertEqual(report.human_size(3 * 1024 ** 3), "3.0 GB")
        self.assertEqual(report.human_size(5 * 1024 ** 5), "5120.0 TB")

    def test_plural(self):
        self.assertEqual(report.plural(1, "file"), "1 file")
        self.assertEqual(report.plural(0, "file"), "0 files")

    def test_tree_texts(self):
        retail = scan()
        backups = [info("20261005-101010", "pre-restore"), info("20261004-153012")]
        self.assertEqual(report.part_text(retail.parts["Interface"]), "1 file · 100 B")
        self.assertEqual(report.part_text(retail.parts["WTF"]), "missing")
        self.assertEqual(report.part_text(PartScan("WTF", RETAIL.path / "WTF", linked=True)), "link, skipped")
        self.assertEqual(report.part_text(scan(False).parts["Interface"]), "1 file")  # sizes unknown
        self.assertEqual(report.flavor_text(retail, backups), "1 file · 100 B · 1 backup, last 2026-10-04 15:30")
        empty = FlavorScan(RETAIL, {"Interface": PartScan("Interface", RETAIL.path / "Interface"),
                                    "WTF": PartScan("WTF", RETAIL.path / "WTF")})
        self.assertEqual(report.flavor_text(empty, []), "nothing to back up: no Interface or WTF folder · no backups yet")
        self.assertIn("WTF.replaced", report.leftover_text(retail))
        self.assertIn("Restore is blocked", report.leftover_text(retail))
        self.assertEqual(report.held_text([retail, empty]), "1 file · 100 B")
        self.assertEqual(report.selection_text([retail, empty]), "Selected: 2 flavors · 1 file · 100 B · 1 link not backed up")
        self.assertEqual(report.selection_text([]), "Selected: 0 flavors · 0 files · 0 B")
        self.assertEqual(report.selection_text([scan(False)]), "Selected: 1 flavor · 1 file · 1 link not backed up")

    def test_warnings_text(self):
        busy = PartScan("Interface", RETAIL.path / "Interface", True, errors=[f"err {i}" for i in range(5)])
        s = FlavorScan(RETAIL, {"Interface": busy, "WTF": PartScan("WTF", RETAIL.path / "WTF", errors=["x"])})
        self.assertEqual(report.warnings_text(s),
                         "Scan warnings (6): skipped, not backed up (the log lists up to 20 per folder)")

    def test_picker_note_and_backup_text(self):
        self.assertEqual(report.picker_note([]), "no backups yet")
        self.assertEqual(report.picker_note([info("20261005-101010", "pre-restore")]), "no backups yet")
        self.assertEqual(report.picker_note([info("20261004-153012")]), "1 backup, last 2026-10-04 15:30")
        b = info("20261004-153012")
        self.assertEqual(report.backup_text(b), "2026-10-04 15:30:12 · backup · … · 2.0 KB")
        self.assertEqual(report.backup_text(b, ("Interface", "WTF")), "2026-10-04 15:30:12 · backup · Interface, WTF · 2.0 KB")
        self.assertEqual(report.backup_text(b, None), "2026-10-04 15:30:12 · backup · ? · 2.0 KB")
        self.assertEqual(report.backup_text(info("20261003-010203", "pre-restore", 100), ()),
                         "2026-10-03 01:02:03 · safety (pre-restore) · none · 100 B")

    def test_friendly_created(self):
        self.assertEqual(report.friendly_created("2026-10-04T12:57:33+05:30"), "2026-10-04 12:57:33")
        self.assertEqual(report.friendly_created("not a date"), "not a date")

    def test_group_paths(self):
        items = [("Interface", "AddOns/WeakAuras/a.lua"), ("Interface", "AddOns/WeakAuras/b/c.lua"),
                 ("WTF", "Account/ME/x.lua"), ("WTF", "Config.wtf")]
        self.assertEqual(report.group_paths(items), [("Interface/AddOns/WeakAuras", 2), ("WTF/Account/ME", 1),
                                                     ("WTF/Config.wtf", 1)])

    def test_group_items(self):
        items = [("WTF", "Config.wtf"), ("Interface", "AddOns/WeakAuras/a.lua"), ("Interface", "AddOns/WeakAuras/b/c.lua")]
        self.assertEqual(report.group_items(items),
                         [("Interface/AddOns/WeakAuras", [("Interface", "AddOns/WeakAuras/a.lua"),
                                                          ("Interface", "AddOns/WeakAuras/b/c.lua")]),
                          ("WTF/Config.wtf", [("WTF", "Config.wtf")])])
        self.assertEqual(report.group_items([]), [])

    def test_restore_summary(self):
        p = plan(removed=[("Interface", "AddOns/A/x.lua")], newer=[("Interface", "AddOns/B/y.lua")] * 2, free=5000)
        self.assertEqual(report.restore_summary(p, "2026-10-04 15:30:12"),
                         "Restore Interface of Retail from 2026-10-04 15:30:12 · 1 removed · 2 newer · needs 1000 B, "
                         "4.9 KB free")
        low = report.restore_summary(plan(free=10), "x")
        self.assertTrue(low.endswith("needs 1000 B, 10 B free    ⚠ low disk space on the WoW drive"), low)
        self.assertTrue(report.restore_summary(plan(), "x").endswith("needs 1000 B"))  # free space unknown

    def test_restore_lost_nothing(self):
        self.assertTrue(report.restore_lost_nothing(plan(kept=[("Interface", "AddOns/Dev")], free=10)))
        for p in (plan(removed=[("WTF", "a")]), plan(newer=[("WTF", "a")]), plan(dropped=[("WTF", "a")]),
                  plan(unreadable=["x: denied"])):
            self.assertFalse(report.restore_lost_nothing(p))

    def test_confirms(self):
        title, body, alerts = report.restore_confirm(plan(removed=[("Interface", "AddOns/A/x.lua")],
                                                          kept=[("Interface", "AddOns/Dev")]),
                                                     "2026-10-04 15:30:12", ["Wow.exe"])
        self.assertIn("Interface", title)
        self.assertIn("Retail", title)
        self.assertIn("2026-10-04 15:30:12", title)
        self.assertIn("1 link", body)
        self.assertTrue(any("Wow.exe" in a for a in alerts))
        self.assertTrue(any("Will be removed" in a for a in alerts))
        # The confirm counts, one line per kind; the restore screen shows the grouped lists.
        many = [("Interface", f"AddOns/A{i:02}/x.lua") for i in range(20)]
        _, _, alerts = report.restore_confirm(plan(removed=many, newer=many[:3], dropped=[("Interface", "AddOns/Dev")],
                                                   free=10, unreadable=["X: denied", "Y: denied"]),
                                              "2026-10-04 15:30:12", ["Wow.exe"])
        self.assertEqual(alerts, ("Will be removed: 20 files (Interface/AddOns/A00 and 19 more)",
                                  ("Newer now than in the backup (these changes are lost): 3 files "
                                   "(Interface/AddOns/A00 and 2 more)"),
                                  "2 places could not be read; whatever is there is replaced too.",
                                  "Links replaced by the backup's files: 1 (only the link goes).",
                                  "Low disk space: 10 B free on the WoW drive, about 1000 B needed.",
                                  alerts[-1]))
        self.assertIn("Wow.exe", alerts[-1])
        title, body, alerts = report.backup_confirm([scan()], Path("/bk"), 0, None, None)
        self.assertIn("never", body)
        self.assertIn("1 flavor", title)
        self.assertEqual(alerts, ())
        title, body, alerts = report.backup_confirm([scan()], Path("/bk"), 5, ["Wow.exe"], 10)
        self.assertIn("newest 5", body)
        self.assertEqual(len(alerts), 2)
        _, _, alerts = report.backup_confirm([scan(False)], Path("/bk"), 5, None, 10)
        self.assertEqual(alerts, ())  # sizes unknown: no space alert

    def test_restore_confirm_warns_when_the_safety_backup_may_not_fit(self):
        # The safety zip of the current folders goes to the backup drive, which may not be the WoW drive.
        _, _, alerts = report.restore_confirm(plan(current=5000), "2026-10-04 15:30:12", None, backup_free=100)
        self.assertEqual(alerts, (("The backup drive may be short of space for the safety backup: 100 B free, up to "
                                   "4.9 KB needed."),))
        for current, free in ((5000, None), (None, 100), (50, 100)):
            _, _, alerts = report.restore_confirm(plan(current=current), "2026-10-04 15:30:12", None,
                                                  backup_free=free)
            self.assertEqual(alerts, ())

    def test_backup_confirm_names_skipped_flavors(self):
        ptr = Flavor("_ptr_", Path("/wow/_ptr_"))
        empty = FlavorScan(ptr, {"Interface": PartScan("Interface", ptr.path / "Interface"),
                                 "WTF": PartScan("WTF", ptr.path / "WTF", linked=True)})
        title, body, _ = report.backup_confirm([scan(), empty], Path("/bk"), 0, None, None)
        self.assertEqual(title, "Back up 1 flavor?")
        self.assertIn("Skipped: Retail PTR (WTF is a link (not followed)).", body)
        _, body, _ = report.backup_confirm([scan()], Path("/bk"), 0, None, None)
        self.assertNotIn("Skipped", body)

    def test_undo_confirm(self):
        journal = Journal(Path("/j.jsonl"), {"flavor": "_retail_", "started": "2026-10-04T15:30:12+02:00"},
                          [{"action": "safety_backup"}, {"action": "replaced", "part": "Interface", "existed": True},
                           {"action": "replaced", "part": "WTF", "existed": True}])
        title, body = report.undo_confirm(journal)
        self.assertIn("2026-10-04 15:30", title)
        self.assertIn("Interface and WTF", body)
        self.assertIn("Retail", body)

    def test_result_rows(self):
        out = BackupOutcome(RETAIL, "created", Path("/bk/backup-retail-x.zip"), 3, 300, 100,
                            missing=["WTF/a.lua"], pruned=[Path("/bk/old.zip")])
        row = report.backup_result_rows([out])[0]
        self.assertEqual(len(row), len(report.BACKUP_RESULT_COLUMNS))
        self.assertEqual(row[1], "Backed up")
        self.assertIn("backup-retail-x.zip", row[2])
        self.assertIn("1 file", row[2])
        self.assertEqual(row[6], "1")
        skipped = report.backup_result_rows([BackupOutcome(RETAIL, "skipped", reason="no Interface or WTF folder")])[0]
        self.assertEqual(skipped[1:3], ("Skipped", "no Interface or WTF folder"))
        result = RestoreResult(RETAIL, Path("/bk/x.zip"), [PartOutcome("WTF", "rolled_back", "locked")])
        self.assertEqual(report.restore_result_rows(result)[0], ("WTF", "Left as it was", "locked"))
        undone = RestoreResult(RETAIL, Path("/bk/x.zip"), [PartOutcome("WTF", "restored"),
                                                           PartOutcome("Interface", "restored")], undo=True)
        self.assertEqual([r[0] for r in report.restore_result_rows(undone)], ["Interface", "WTF"])  # PARTS order

    def test_summary_rows(self):
        made = BackupOutcome(RETAIL, "created", Path("/bk/backup-retail-x.zip"), 3, 3072, 1024,
                             pruned=[Path("/bk/old.zip")])
        rows = dict(report.backup_summary_rows([made, BackupOutcome(RETAIL, "skipped", reason="none")]))
        self.assertEqual(rows["Backed up"], "1 of 2 flavors")
        self.assertEqual(rows["Skipped"], "1 flavor")
        self.assertNotIn("Failed", rows)
        self.assertEqual(rows["Files"], "3 (3.0 KB)")
        self.assertEqual(rows["Zip size"], "1.0 KB")
        self.assertIn("bk", rows["Zips in"])
        self.assertEqual(rows["Old backups removed"], "1")
        rows = dict(report.backup_summary_rows([BackupOutcome(RETAIL, "failed", reason="disk")]))
        self.assertEqual(rows, {"Backed up": "0 of 1 flavor", "Failed": "1 flavor"})
        done = RestoreResult(RETAIL, Path("/bk/x.zip"), [PartOutcome("WTF", "restored")],
                             safety_zip=Path("/bk/pre.zip"), journal_path=Path("/j/r.jsonl"))
        rows = dict(report.restore_summary_rows(done))
        self.assertEqual(rows["Flavor"], "Retail")
        self.assertEqual(rows["Restore"], "finished")
        self.assertIn("x.zip", rows["Restored from"])
        self.assertIn("pre.zip", rows["Safety backup"])
        self.assertIn("r.jsonl", rows["Journal"])
        undone = RestoreResult(RETAIL, Path("/bk/pre.zip"), [PartOutcome("WTF", "failed", "locked")], undo=True)
        rows = dict(report.restore_summary_rows(undone))
        self.assertEqual(rows["Undo"], "did not finish for every part (see below)")
        self.assertIn("pre.zip", rows["Put back from"])
        self.assertNotIn("Journal", rows)

    def test_every_progress_stage_has_a_title(self):
        for stage in ("scan", "backup", "verify", "prune", "safety", "safety_verify", "extract", "swap", "cleanup"):
            self.assertIn(stage, report.STAGE_TITLES)


if __name__ == "__main__":
    unittest.main()
