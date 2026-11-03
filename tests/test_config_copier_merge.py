"""Config Copier's config-cache.wtf merge: the source's preference CVars, the target's own state CVars (config tools
spec CC5; Review Focus 5)."""
from __future__ import annotations

import unittest

from tests.fixtures import cvar_file_bytes
from wowtools.core.cvarfile import parse_cvars
from wowtools.tools.config_copier.merge import merge_config


def cvars(data: bytes) -> list[tuple[str, str]]:
    return [(line.name, line.value) for line in parse_cvars(data).lines]


SOURCE = cvar_file_bytes([
    ("assistedCombatHighlight", "1"), ("nameplateSelectedAlpha", "1"), ("autoLootDefault", "1"),
    ("savedClassConfigOne", "src-one"), ("hardTrackedQuests", "1,2,3"), ("closedInfoFrames", "src-closed"),
    ("newPvpSeason", "40"), ("cameraSavedDistance", "15")])
TARGET = cvar_file_bytes([
    ("enableMultiActionBars", "15"), ("savedClassConfigOne", "tgt-one"), ("autoLootDefault", "0"),
    ("hardTrackedQuests", "78463"), ("closedInfoFrames", "tgt-closed"), ("cameraSavedDistance", "9")])


class MergeTest(unittest.TestCase):
    def test_merge_takes_source_preferences_exactly(self):
        merged = cvars(merge_config(SOURCE, TARGET))
        names = [name for name, _ in merged]
        self.assertNotIn("enableMultiActionBars", names)  # a preference only the target had is removed
        self.assertIn(("assistedCombatHighlight", "1"), merged)  # one only the source had is added
        self.assertIn(("nameplateSelectedAlpha", "1"), merged)
        self.assertIn(("autoLootDefault", "1"), merged)  # one both had takes the source's value
        preferences = {"assistedCombatHighlight", "nameplateSelectedAlpha", "autoLootDefault"}
        self.assertEqual({(n, v) for n, v in merged if n in preferences},
                         {(n, v) for n, v in cvars(SOURCE) if n in preferences})

    def test_merge_keeps_target_state(self):
        merged = cvars(merge_config(SOURCE, TARGET))
        for name, value in (("savedClassConfigOne", "tgt-one"), ("hardTrackedQuests", "78463"),
                            ("closedInfoFrames", "tgt-closed"), ("cameraSavedDistance", "9")):
            self.assertIn((name, value), merged)
        names = [name for name, _ in merged]
        self.assertNotIn("newPvpSeason", names)  # the source's state is never copied
        self.assertEqual(len(names), len(set(names)))

    def test_merge_line_order_and_bytes(self):
        """Kept lines stay in the target's order and bytes; the source's new preferences are appended (CC5)."""
        merged = merge_config(SOURCE, TARGET)
        self.assertEqual(cvars(merged), [
            ("savedClassConfigOne", "tgt-one"), ("autoLootDefault", "1"), ("hardTrackedQuests", "78463"),
            ("closedInfoFrames", "tgt-closed"), ("cameraSavedDistance", "9"),
            ("assistedCombatHighlight", "1"), ("nameplateSelectedAlpha", "1")])
        self.assertTrue(merged.startswith(b'SET savedClassConfigOne "tgt-one"\r\nSET autoLootDefault "1"\r\n'))
        self.assertNotIn(b"\n\n", merged.replace(b"\r", b""))

    def test_merge_without_target_file(self):
        merged = merge_config(SOURCE, None)
        self.assertEqual(cvars(merged), [("assistedCombatHighlight", "1"), ("nameplateSelectedAlpha", "1"),
                                         ("autoLootDefault", "1")])
        self.assertEqual(merged, cvar_file_bytes([("assistedCombatHighlight", "1"), ("nameplateSelectedAlpha", "1"),
                                                  ("autoLootDefault", "1")]))

    def test_merge_into_an_empty_target_file(self):
        self.assertEqual(cvars(merge_config(SOURCE, b"")), cvars(merge_config(SOURCE, None)))

    def test_merge_of_an_empty_source(self):
        """An empty source has no preferences: the target keeps only its state."""
        self.assertEqual(cvars(merge_config(b"", TARGET)), [
            ("savedClassConfigOne", "tgt-one"), ("hardTrackedQuests", "78463"), ("closedInfoFrames", "tgt-closed"),
            ("cameraSavedDistance", "9")])
        self.assertEqual(merge_config(b"", None), b"")

    def test_merge_is_identity_when_same_preferences(self):
        source = cvar_file_bytes([("autoLootDefault", "1"), ("Sound_MasterVolume", "0.4"),
                                  ("hardTrackedQuests", "1,2")])
        target = cvar_file_bytes([("hardTrackedQuests", "78463"), ("sound_mastervolume", "0.4"),
                                  ("autoLootDefault", "1")], newline=b"\n")
        self.assertEqual(merge_config(source, target), target)

    def test_identity_keeps_a_duplicated_line_whose_value_the_client_reads_the_same(self):
        target = b'SET autoLootDefault "0"\r\nSET autoLootDefault "1"\r\n'
        self.assertEqual(merge_config(cvar_file_bytes([("autoLootDefault", "1")]), target), target)

    def test_target_line_endings_and_other_lines_kept(self):
        target = b'# kept\nSET autoLootDefault "0"\nSET enableMultiActionBars "15"\nSET hardTrackedQuests "7"'
        merged = merge_config(cvar_file_bytes([("autoLootDefault", "1"), ("Ünïcode", "Dænerys")]), target)
        self.assertEqual(merged, '# kept\nSET autoLootDefault "1"\nSET hardTrackedQuests "7"\n'
                                 'SET Ünïcode "Dænerys"\n'.encode())

    def test_source_names_matched_case_insensitively(self):
        merged = merge_config(cvar_file_bytes([("AUTOLOOTDEFAULT", "1")]),
                              cvar_file_bytes([("autoLootDefault", "0")]))
        self.assertEqual(cvars(merged), [("autoLootDefault", "1")])  # the target's spelling kept

    def test_source_duplicate_reads_the_last(self):
        merged = merge_config(b'SET autoLootDefault "0"\r\nSET autoLootDefault "1"\r\n', None)
        self.assertEqual(parse_cvars(merged).get("autoLootDefault"), "1")

    def test_source_name_with_non_ascii_whitespace_is_merged(self):
        merged = merge_config(b'SET foo\xc2\xa0bar "1"\r\n', b'SET x "1"\r\n')
        self.assertEqual(merged, b'SET foo\xc2\xa0bar "1"\r\n')


if __name__ == "__main__":
    unittest.main()
