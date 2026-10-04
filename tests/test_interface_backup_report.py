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


def plan(removed=(), newer=(), kept=(), dropped=(), free=None, unreadable=()) -> RestorePlan:
    contents = BackupContents(Path("/bk/backup-retail-20261004-153012.zip"), "backup", "retail", "_retail_", "",
                              ("Interface", "WTF"), {"Interface": {}, "WTF": {}})
    return RestorePlan(contents, RETAIL, ("Interface",), list(removed), list(newer), list(kept), list(dropped),
                       1000, free, [], list(unreadable))


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

    def test_summary_rows_and_notices(self):
        rows = report.summary_rows([scan()], {"retail": [info("20261004-153012"), info("20261005-101010", "pre-restore")]})
        self.assertEqual(len(rows[0]), len(report.SUMMARY_COLUMNS))
        self.assertEqual(rows[0][0], "Retail")
        self.assertIn("1 file", rows[0][1])
        self.assertIn("100 B", rows[0][1])
        self.assertEqual(rows[0][2], "—")
        self.assertEqual(rows[0][3], "1")
        self.assertEqual(rows[0][4], "1")  # safety zips are not counted
        self.assertEqual(rows[0][5], "2026-10-04 15:30:12")
        unknown = report.summary_rows([scan(False)], {})[0]
        self.assertIn("1 file", unknown[1])
        self.assertNotIn("B", unknown[1].replace("1 file", ""))
        self.assertEqual(unknown[5], "none yet")
        lines = report.notices([scan()])
        self.assertTrue(any("WTF.replaced" in n for n in lines))
        self.assertTrue(any("1 link" in n for n in lines))

    def test_linked_part_and_many_errors(self):
        linked = PartScan("WTF", RETAIL.path / "WTF", linked=True, errors=["WTF is a link"])
        busy = PartScan("Interface", RETAIL.path / "Interface", True, errors=[f"err {i}" for i in range(5)])
        s = FlavorScan(RETAIL, {"Interface": busy, "WTF": linked})
        self.assertEqual(report.summary_rows([s], {})[0][2], "link (skipped)")
        lines = report.notices([s])
        self.assertIn("Retail: err 0", lines)
        self.assertNotIn("Retail: err 3", lines)
        self.assertTrue(any("2 more" in n for n in lines))

    def test_picker_note_and_list_rows(self):
        self.assertEqual(report.picker_note([]), "no backups yet")
        self.assertEqual(report.picker_note([info("20261005-101010", "pre-restore")]), "no backups yet")
        self.assertEqual(report.picker_note([info("20261004-153012")]), "1 backup, last 2026-10-04 15:30")
        rows = report.list_rows([info("20261004-153012"), info("20261003-010203", "pre-restore", 100)])
        self.assertEqual(rows[0], ("2026-10-04 15:30:12", "retail", "backup", "2.0 KB"))
        self.assertEqual(rows[1][2], "safety (pre-restore)")
        self.assertEqual(len(rows[0]), len(report.LIST_COLUMNS))

    def test_group_paths(self):
        items = [("Interface", "AddOns/WeakAuras/a.lua"), ("Interface", "AddOns/WeakAuras/b/c.lua"),
                 ("WTF", "Account/ME/x.lua"), ("WTF", "Config.wtf")]
        self.assertEqual(report.group_paths(items), [("Interface/AddOns/WeakAuras", 2), ("WTF/Account/ME", 1),
                                                     ("WTF/Config.wtf", 1)])

    def test_restore_warnings(self):
        many = [("Interface", f"AddOns/A{i}/x.lua") for i in range(20)]
        lines = report.restore_warnings(plan(removed=many, newer=[("Interface", "AddOns/B/y.lua")],
                                             dropped=[("Interface", "AddOns/Dev")], free=10), limit=15)
        text = "\n".join(lines)
        self.assertIn("Will be removed: 20 files", text)
        self.assertIn("and 5 more", text)
        self.assertIn("Newer now than in the backup", text)
        self.assertIn("AddOns/Dev", text)
        self.assertIn("space", text.lower())
        self.assertEqual(report.restore_warnings(plan()), [])
        self.assertEqual(report.restore_warnings(plan(free=5000)), [])

    def test_restore_warnings_unreadable(self):
        lines = report.restore_warnings(plan(unreadable=[f"/wow/_retail_/Interface/X{i}: denied" for i in range(4)]),
                                        limit=2)
        text = "\n".join(lines)
        self.assertIn("could not be read", text)
        self.assertIn("X0", text)
        self.assertNotIn("X2", text)
        self.assertIn("and 2 more", text)

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
        title, body, alerts = report.backup_confirm([scan()], Path("/bk"), 0, None, None)
        self.assertIn("never", body)
        self.assertIn("1 flavor", title)
        self.assertEqual(alerts, ())
        title, body, alerts = report.backup_confirm([scan()], Path("/bk"), 5, ["Wow.exe"], 10)
        self.assertIn("newest 5", body)
        self.assertEqual(len(alerts), 2)
        _, _, alerts = report.backup_confirm([scan(False)], Path("/bk"), 5, None, 10)
        self.assertEqual(alerts, ())  # sizes unknown: no space alert

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

    def test_every_progress_stage_has_a_title(self):
        for stage in ("scan", "backup", "verify", "prune", "safety", "safety_verify", "extract", "swap", "cleanup"):
            self.assertIn(stage, report.STAGE_TITLES)


if __name__ == "__main__":
    unittest.main()
