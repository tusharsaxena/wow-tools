import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wowtools.core import events
from wowtools.core.events import (EventLog, EventSpec, UnknownEventError, capture_events,
                                  log_event, register_events)

FIXED = datetime(2026, 9, 27, 14, 3, 11, 482000, tzinfo=timezone(timedelta(hours=10)))


class EnvelopeTest(unittest.TestCase):
    def test_record_has_envelope_fields_and_registry_level(self):
        log = EventLog(memory=True, tool="wtf-cleaner", mode="tui", clock=lambda: FIXED)
        record = log.emit("wow.running_warning", executables=["Wow.exe"])
        self.assertEqual(record["v"], 1)
        self.assertEqual(record["ts"], "2026-09-27T14:03:11.482+10:00")
        self.assertEqual(len(record["session"]), 8)
        self.assertEqual(record["suite_version"], "0.1.0")
        self.assertEqual((record["tool"], record["mode"]), ("wtf-cleaner", "tui"))
        self.assertEqual(record["event"], "wow.running_warning")
        self.assertEqual(record["level"], "warning")
        self.assertIsNone(record["dry_run"])
        self.assertEqual(record["data"], {"executables": ["Wow.exe"]})
        self.assertEqual(log.records, [record])

    def test_unregistered_event_raises_when_strict(self):
        with self.assertRaises(UnknownEventError):
            EventLog(strict=True).emit("nope.nothing")

    def test_unregistered_event_becomes_error_when_not_strict(self):
        record = EventLog(memory=True).emit("nope.nothing", a=1)
        self.assertEqual(record["event"], "error")
        self.assertEqual(record["data"], {"unregistered_event": "nope.nothing", "a": 1})

    def test_level_can_only_be_raised(self):
        log = EventLog(memory=True)
        self.assertEqual(log.emit("session.end", level="warning", exit_code=3)["level"], "warning")
        self.assertEqual(log.emit("wow.running_warning", level="debug")["level"], "warning")

    def test_register_conflicting_spec_raises(self):
        register_events("test-a", {"test.same": EventSpec("info", "x")})
        register_events("test-b", {"test.same": EventSpec("info", "x")})
        with self.assertRaises(ValueError):
            register_events("test-c", {"test.same": EventSpec("error", "y")})

    def test_every_registered_level_is_valid(self):
        for name, spec in events.REGISTRY.items():
            self.assertIn(spec.level, events.LEVELS, name)


class SinkTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_jsonl_keeps_debug_text_respects_level(self):
        log = EventLog(self.dir, text_level="info", clock=lambda: FIXED)
        log.emit("update.checked", current="0.1.0", latest=None, throttled=False)
        log.emit("config.created", path="x.cfg")
        lines = (self.dir / "events-2026-09-27.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["event"] for line in lines], ["update.checked", "config.created"])
        text = (self.dir / "wow-tools-2026-09-27.log").read_text(encoding="utf-8")
        self.assertNotIn("update.checked", text)
        self.assertIn("2026-09-27 14:03:11 INFO    [suite] config.created  path=x.cfg", text)

    def test_text_line_marks_dry_run_and_joins_lists(self):
        record = EventLog(memory=True, clock=lambda: FIXED).emit(
            "wow.running_warning", dry_run=True, executables=["Wow.exe", "WowClassic.exe"])
        self.assertTrue(events.format_text(record).endswith(
            "wow.running_warning  DRY-RUN executables=Wow.exe,WowClassic.exe"))

    def test_paths_and_sets_serialise(self):
        log = EventLog(self.dir, clock=lambda: FIXED)
        log.emit("config.created", path=Path("/x/y.cfg"))
        line = (self.dir / "events-2026-09-27.jsonl").read_text(encoding="utf-8").strip()
        self.assertEqual(json.loads(line)["data"]["path"], str(Path("/x/y.cfg")))

    def test_prune_removes_only_old_log_files(self):
        old = self.dir / "events-2026-01-01.jsonl"
        old.write_text("{}\n")
        keep = self.dir / "wow-tools-2026-09-20.log"
        keep.write_text("x\n")
        other = self.dir / "notes-2020-01-01.txt"
        other.write_text("x")
        removed = EventLog(self.dir, retention_days=90, clock=lambda: FIXED).prune()
        self.assertEqual(removed, [old])
        self.assertTrue(keep.exists())
        self.assertTrue(other.exists())

    def test_io_failure_disables_sinks_without_raising(self):
        blocker = self.dir / "logs"
        blocker.write_text("a file where the log folder should be")
        warnings = []
        log = EventLog(blocker, on_sink_error=warnings.append)
        log.emit("config.created", path="a")
        self.assertEqual(len(warnings), 2)
        log.emit("config.created", path="b")
        self.assertEqual(len(warnings), 2)


class GlobalLogTest(unittest.TestCase):
    def test_capture_events_swaps_global_log(self):
        before = events.get_event_log()
        with capture_events() as records:
            log_event("config.created", path="p")
        self.assertEqual([r["event"] for r in records], ["config.created"])
        self.assertIs(events.get_event_log(), before)

    def test_log_exception_records_traceback(self):
        with capture_events() as records:
            try:
                raise RuntimeError("boom")
            except RuntimeError as exc:
                events.log_exception("test", exc)
        data = records[0]["data"]
        self.assertEqual((data["where"], data["type"], data["message"]), ("test", "RuntimeError", "boom"))
        self.assertIn("RuntimeError: boom", data["traceback"])
