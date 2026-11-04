"""Config Editor runs (config tools spec CE3-CE8, X5): staged CVar changes written through the shared client-file
pipeline across files and flavors as one run and one Undo, created files, the dry run, the WoW check, a file
changed since the scan, Recommend…'s list and the text of the tree rows, the help panel, the confirm and the result.
Every client file is synthesized in a tests/fixtures.py temp tree (build_config_tree), never a real install."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import (CONFIG_ACCOUNT, CONFIG_AELLA, CONFIG_MACHINE, CONFIG_TRAXEX, build_config_tree,
                            cvar_file_bytes)
from wowtools.core import client_apply
from wowtools.core.events import capture_events
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import WowInstall
from wowtools.core.kb import CvarInfo, Recommendation
from wowtools.tools.config_editor import journal, report, undo
from wowtools.tools.config_editor.events import SV_TOOL
from wowtools.tools.config_editor.model import CONFIG_CACHE, CONFIG_WTF, ConfigTarget
from wowtools.tools.config_editor.ops import (ConfigStaged, applicable_recommendations, rows, stage_remove,
                                              stage_reset, stage_set, stage_toggle)
from wowtools.tools.config_editor.runner import NAMES, WowRunning, changes_by_flavor, run_apply
from wowtools.tools.config_editor.scanner import scan_targets

WHEN = datetime(2026, 11, 4, 12, 0, 0)


def info(name: str, default: str | None, scope: str | None = "character", category: str = "other",
         help_text: str = "", description: str = "") -> CvarInfo:
    return CvarInfo(name=name, default=default, help=help_text, description=description,
                    description_source="https://warcraft.wiki.gg/wiki/CVar_" + name if description else "",
                    category=category, scope=scope, synced=scope in ("account", "character"),
                    source="client dump _retail_ 1")


CVARS = {c.name: c for c in (
    info("nameplateShowFriends", "0", category="nameplates", help_text="Show friendly nameplates"),
    info("nameplateShowAll", "0", scope="account", category="nameplates"),
    info("cameraDistanceMaxZoomFactor", "1.9", category="camera", description="How far the camera can zoom out."),
    info("assistedCombatHighlight", "1", category="interface"),
    info("autoLootDefault", "0", scope="account", category="interface"),
    info("gxMaximize", "0", scope="machine", category="graphics"),
    info("Sound_MasterVolume", "1.0", scope="machine", category="sound"),
)}


class ConfigRunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_config_tree(self.tmp / "wow")
        era = self.wow / "_classic_era_" / "WTF"
        (era / "Account" / "ACCT" / "Realm1" / "Other").mkdir(parents=True)
        (era / CONFIG_WTF).write_bytes(cvar_file_bytes([("gxMaximize", "0")]))
        install = WowInstall(self.wow)
        self.retail, self.era = install.flavor("_retail_"), install.flavor("_classic_era_")
        self.targets = scan_targets(self.retail) + scan_targets(self.era)
        self.root = self.tmp / "out" / "config-editor"
        self.journals = self.tmp / "journal"
        self.staged = ConfigStaged()

    def target(self, label: str, flavor: str = "_retail_") -> ConfigTarget:
        return next(t for t in self.targets if t.label == label and t.flavor.folder == flavor)

    def run_it(self, **kwargs):
        options = {"root": self.root, "journal_dir": self.journals, "keep_journals": 5, "keep_snapshots": 2,
                   "dry_run": False, "wow_check": None, "now": WHEN}
        options.update(kwargs)
        return run_apply(self.staged, self.targets, **options)

    def tree_bytes(self) -> dict[str, bytes]:
        return {p.relative_to(self.wow).as_posix(): p.read_bytes() for p in sorted(self.wow.rglob("*"))
                if p.is_file()}

    def stage_three_levels(self) -> None:
        stage_set(self.staged, self.target(CONFIG_WTF), "gxMaximize", "0")
        stage_toggle(self.staged, self.target("MAIN"), "autoLootDefault", CVARS["autoLootDefault"])
        stage_reset(self.staged, self.target("MAIN/Realm1/Aellâ"), "cameraDistanceMaxZoomFactor")
        stage_set(self.staged, self.target("MAIN/Realm1/Bob"), "nameplateShowFriends", "1")  # no file: created

    def test_names_are_the_two_cvar_files(self):
        self.assertEqual(NAMES, frozenset({CONFIG_WTF, CONFIG_CACHE}))

    def test_one_run_across_levels_then_undo(self):
        before = self.tree_bytes()
        self.stage_three_levels()
        with capture_events() as events:
            result = self.run_it()
        self.assertIsNone(result.stopped)
        self.assertEqual(len(result.edited), 4)
        self.assertIn("cvar.apply_completed", [e["event"] for e in events])
        wtf = self.retail.wtf_dir
        self.assertEqual((wtf / CONFIG_WTF).read_bytes(), CONFIG_MACHINE.replace(b'gxMaximize "1"', b'gxMaximize "0"'))
        self.assertEqual((wtf / "Account" / "MAIN" / CONFIG_CACHE).read_bytes(),
                         CONFIG_ACCOUNT.replace(b'autoLootDefault "1"', b'autoLootDefault "0"'))
        aella = (wtf / "Account" / "MAIN" / "Realm1" / "Aellâ" / CONFIG_CACHE).read_bytes()
        self.assertEqual(aella, CONFIG_AELLA.replace(b'SET cameraDistanceMaxZoomFactor "2.6"\r\n', b""))
        bob = wtf / "Account" / "MAIN" / "Realm1" / "Bob" / CONFIG_CACHE
        self.assertEqual(bob.read_bytes(), b'SET nameplateShowFriends "1"\r\n')
        # untouched: the copy folder, Trâxex, the other flavor; no cache.md5 or .old (V2)
        self.assertEqual((wtf / "Account" / "MAIN" / "Realm1" / "Bob - Copy" / CONFIG_CACHE).read_bytes(),
                         CONFIG_AELLA)
        self.assertEqual((wtf / "Account" / "MAIN" / "Realm2" / "Trâxex" / CONFIG_CACHE).read_bytes(), CONFIG_TRAXEX)
        self.assertFalse(list(self.wow.rglob("cache.md5")) + list(self.wow.rglob("*.old")))
        self.assertTrue(undo.undo_flavors(self.wow, journal.read_journal(result.journal_path).entries))
        undone = undo.undo_run(result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2, now=WHEN)
        self.assertEqual(len(undone.restored), 4)
        self.assertEqual(self.tree_bytes(), before)  # Bob's created file is gone again

    def test_one_run_across_flavors(self):
        stage_set(self.staged, self.target(CONFIG_WTF), "gxMaximize", "0")
        stage_set(self.staged, self.target(CONFIG_WTF, "_classic_era_"), "gxMaximize", "1")
        plan = changes_by_flavor(self.staged, self.targets)
        self.assertEqual([(f.folder, len(c)) for f, c in plan], [("_retail_", 1), ("_classic_era_", 1)])
        checked = []
        result = self.run_it(wow_check=lambda: checked.append(1) or [])
        self.assertEqual(checked, [1])
        self.assertEqual(len(result.edited), 2)
        era = self.era.wtf_dir / CONFIG_WTF
        self.assertEqual(era.read_bytes(), cvar_file_bytes([("gxMaximize", "1")]))
        undo.undo_run(result.journal_path, wow_root=self.wow, root=self.root, keep_snapshots=2, now=WHEN)
        self.assertEqual(era.read_bytes(), cvar_file_bytes([("gxMaximize", "0")]))

    def test_dry_run_writes_nothing(self):
        before = self.tree_bytes()
        self.stage_three_levels()
        result = self.run_it(dry_run=True)
        self.assertEqual(len(result.would_edit), 4)
        self.assertEqual(self.tree_bytes(), before)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.journals.exists())

    def test_refused_while_wow_runs(self):
        before = self.tree_bytes()
        self.stage_three_levels()
        with self.assertRaises(WowRunning):
            self.run_it(wow_check=lambda: ["Wow.exe"])
        self.assertEqual(self.tree_bytes(), before)

    def test_a_file_changed_since_the_scan_is_skipped(self):
        stage_set(self.staged, self.target(CONFIG_WTF), "gxMaximize", "0")
        stage_set(self.staged, self.target("MAIN"), "autoLootDefault", "0")
        account = self.retail.account_dir / "MAIN" / CONFIG_CACHE
        account.write_bytes(CONFIG_ACCOUNT + b'SET newOne "1"\r\n')  # WoW saved it after the scan
        result = self.run_it()
        self.assertEqual(len(result.edited), 1)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(account.read_bytes(), CONFIG_ACCOUNT + b'SET newOne "1"\r\n')

    def test_lf_file_keeps_its_line_endings_and_other_lines(self):
        traxex = self.target("MAIN/Realm2/Trâxex")
        stage_set(self.staged, traxex, "nameplateShowFriends", "1")
        stage_set(self.staged, traxex, "cameraDistanceMaxZoomFactor", "2.6")
        self.run_it()
        self.assertEqual(traxex.path.read_bytes(),
                         b'SET nameplateShowFriends "1"\n# not a SET line\nSET floatingCombatTextCombatDamage "1"\n'
                         b'SET cameraDistanceMaxZoomFactor "2.6"\n')

    def test_recover_after_a_crash_puts_the_originals_back(self):
        """A run that replaced Config.wtf and created Bob's file, then died writing Aellâ's with no roll-back: the
        next scan offers recovery, which puts every file back and removes the created one."""
        before = self.tree_bytes()
        self.stage_three_levels()
        (flavor, changes), = changes_by_flavor(self.staged, self.targets)
        aella = self.target("MAIN/Realm1/Aellâ").path
        changes = [c for c in changes if c.path != aella] + [c for c in changes if c.path == aella]

        def write(path: Path, data: bytes) -> None:
            if path == aella:
                raise OSError("killed")
            atomic_write_bytes(path, data)
        with patch("wowtools.core.sv_apply.restore_original", side_effect=OSError("no")), \
                patch("wowtools.core.sv_apply.remove_created", side_effect=OSError("no")):
            result = client_apply.apply_client_changes(SV_TOOL, flavor, changes, names=NAMES, root=self.root,
                                                       journal_dir=self.journals, keep_journals=5, keep_snapshots=2,
                                                       dry_run=False, wow_check=None, now=WHEN, write=write)
        self.assertIsNotNone(result.stopped)
        marker = undo.pending_recovery(self.root)
        self.assertIsNotNone(marker)
        with capture_events() as events:
            outcome = undo.recover(marker, wow_root=self.wow, root=self.root, journal_dir=self.journals,
                                   keep_snapshots=2, now=WHEN)
        self.assertFalse(outcome.failed)
        self.assertEqual(self.tree_bytes(), before)
        self.assertIsNone(undo.pending_recovery(self.root))
        self.assertIn("cvar.file_removed", [e["event"] for e in events])

    # --- text ---------------------------------------------------------------------------------
    def test_row_text(self):
        aella = self.target("MAIN/Realm1/Aellâ")
        found = {r.name: report.row_text(r) for r in rows(aella, CVARS, show_all_known=True, category=None,
                                                          changed_only=False, search="")}
        self.assertEqual(found["cameraDistanceMaxZoomFactor"],
                         f"cameraDistanceMaxZoomFactor = 2.6 (default 1.9)  {report.CHANGED}")
        self.assertEqual(found["assistedCombatHighlight"], "assistedCombatHighlight = 1 (default 1)")
        self.assertEqual(found["myAddonThing"], f"myAddonThing = Dænerys  {report.UNKNOWN}")
        self.assertEqual(found["nameplateShowFriends"], f"nameplateShowFriends = 1 (default 0)  {report.CHANGED}")
        self.assertNotIn("gxMaximize", found)  # machine scope: not a character's CVar to show
        bob = self.target("MAIN/Realm1/Bob")
        found = {r.name: report.row_text(r) for r in rows(bob, CVARS, show_all_known=True, category=None,
                                                          changed_only=False, search="")}
        self.assertEqual(found["nameplateShowFriends"], f"nameplateShowFriends  {report.NOT_SET} (default 0)")

    def test_help_lines(self):
        aella = self.target("MAIN/Realm1/Aellâ")
        by_name = {r.name: r for r in rows(aella, CVARS, show_all_known=False, category=None, changed_only=False,
                                           search="")}
        rec = Recommendation("nameplateShowFriends", "1", ("_retail_",), "See your group.", "https://example.org/x")
        text = "\n".join(report.help_lines(aella, by_name["nameplateShowFriends"], recommendation=rec))
        for needle in ("nameplateShowFriends (nameplates): 1 here; default 0 (changed from the default)",
                       "Blizzard: Show friendly nameplates  (client dump _retail_ 1)", "Type: on or off",
                       "per character", "Blizzard's servers", "Recommended: 1. See your group.  (https://example.org/x)"):
            self.assertIn(needle, text)
        text = "\n".join(report.help_lines(aella, by_name["cameraDistanceMaxZoomFactor"]))
        self.assertIn("Note: How far the camera can zoom out.  (https://warcraft.wiki.gg/wiki/CVar_camera", text)
        text = "\n".join(report.help_lines(aella, by_name["myAddonThing"]))
        self.assertIn("Unknown CVar", text)
        self.assertIn("You can still set or remove it", text)
        stage_set(self.staged, aella, "nameplateShowAll", "1")  # an account CVar in a character file
        row = next(r for r in rows(aella, CVARS, show_all_known=False, category=None, changed_only=False, search="",
                                   staged=self.staged) if r.name == "nameplateShowAll")
        self.assertIn("the game keeps this CVar at the account level", "\n".join(report.help_lines(aella, row)))
        text = "\n".join(report.help_lines(self.target("MAIN/Realm1/Bob"), None, has_data=False))
        self.assertIn("No file yet", text)
        self.assertIn("every CVar shows as unknown", text)

    def test_confirm_groups_and_scope_listed(self):
        self.stage_three_levels()
        stage_set(self.staged, self.target("MAIN/Realm1/Aellâ"), "nameplateShowAll", "1")
        title, body, alerts = report.apply_confirm(self.staged, self.targets, dry_run=False)
        self.assertEqual(title, "Apply the staged changes?")
        self.assertIn("5 changes in 4 files (Retail).", body)
        self.assertTrue(alerts and "Close WoW first" in alerts[0])
        groups = report.apply_groups(self.staged, self.targets)
        self.assertEqual(groups["Retail › Config.wtf"], ['Config.wtf: gxMaximize "1" -> "0"'])
        self.assertEqual(groups["Retail › MAIN account config"], ['config-cache.wtf: autoLootDefault "1" -> "0"'])
        self.assertIn("config-cache.wtf: removed cameraDistanceMaxZoomFactor", groups["Retail › MAIN/Realm1/Aellâ"])
        listed = report.scope_listed(self.staged, self.targets, {"_retail_": CVARS})
        self.assertEqual([(e.where, e.item) for e in listed], [("Retail › MAIN/Realm1/Aellâ", "nameplateShowAll")])
        self.assertIn("keeps it at the account level", listed[0].message)
        _, body, alerts = report.apply_confirm(self.staged, self.targets, dry_run=True)
        self.assertIn("no file is written", body)
        self.assertEqual(alerts, [])

    def test_result_rows(self):
        self.stage_three_levels()
        result = self.run_it(dry_run=True)
        self.assertEqual([row[1] for row in report.file_rows(result)],
                         ["Config.wtf", "MAIN account config", "MAIN/Realm1/Aellâ", "MAIN/Realm1/Bob"])
        self.assertTrue(all(row[0] == "Retail" and row[2].startswith("would change") for row in
                            report.file_rows(result)))
        self.assertEqual(report.summary_rows(result)[0], ("Would change", "4 files"))

    def test_applicable_recommendations(self):
        recs = [Recommendation("nameplateShowFriends", "1", ("_retail_",), "r1", "https://a"),
                Recommendation("nameplateShowAll", "1", ("_retail_",), "r2", "https://b"),
                Recommendation("gxMaximize", "1", ("_retail_",), "r3", "https://c"),
                Recommendation("someNewCVar", "1", ("_retail_",), "r4", "https://d")]
        aella = self.target("MAIN/Realm1/Aellâ")
        found = applicable_recommendations(aella, recs, CVARS)
        # account and machine CVars belong elsewhere; a CVar the KB lacks is the user's call
        self.assertEqual([(r.recommendation.cvar, r.current, r.done) for r in found],
                         [("nameplateShowFriends", "1", True), ("someNewCVar", None, False)])
        stage_remove(self.staged, aella, "nameplateShowFriends")
        found = applicable_recommendations(aella, recs, CVARS, self.staged)
        self.assertEqual((found[0].current, found[0].done), (None, False))
        machine = applicable_recommendations(self.target(CONFIG_WTF), recs, CVARS)
        self.assertEqual([r.recommendation.cvar for r in machine], ["gxMaximize", "someNewCVar"])
        self.assertEqual((machine[0].current, machine[0].done), ("1", True))


if __name__ == "__main__":
    unittest.main()
