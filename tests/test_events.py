from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from wowtools import __version__
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
        self.assertEqual(record["suite_version"], __version__)
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
        self.addCleanup(events.close_all_logs)  # runs first: Windows cannot delete a file that is still open
        self.dir = Path(tmp.name)

    def test_append_reuses_one_handle_per_file(self):
        opened = []
        real_open = Path.open

        def counting_open(path, *args, **kwargs):
            opened.append(path)
            return real_open(path, *args, **kwargs)

        log = EventLog(self.dir, clock=lambda: FIXED)
        with mock.patch.object(Path, "open", counting_open):
            for index in range(100):
                log.emit("config.created", path=f"x{index}")
        self.assertLessEqual(len(opened), 2)  # one events file, one readable file
        log.close()
        lines = (self.dir / "suite" / "events-2026-09-27.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 100)
        self.assertEqual(len((self.dir / "suite" / "logfile-2026-09-27.log").read_text().splitlines()), 100)

    def test_each_line_is_on_disk_before_close(self):
        log = EventLog(self.dir, clock=lambda: FIXED)
        log.emit("config.created", path="a")
        self.assertIn("path=a", (self.dir / "suite" / "logfile-2026-09-27.log").read_text(encoding="utf-8"))

    def test_day_rollover_closes_old_handles(self):
        now = [FIXED.replace(hour=23, minute=59)]
        handles = []
        real_open = Path.open

        def tracking_open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            handles.append((path.name, handle))
            return handle

        log = EventLog(self.dir, clock=lambda: now[0])
        with mock.patch.object(Path, "open", tracking_open):
            log.emit("config.created", path="before")
            now[0] = now[0] + timedelta(minutes=2)
            log.emit("config.created", path="after")
        closed = {name: handle.closed for name, handle in handles}
        self.assertEqual(closed, {"events-2026-09-27.log": True, "logfile-2026-09-27.log": True,
                                  "events-2026-09-28.log": False, "logfile-2026-09-28.log": False})
        log.close()
        self.assertTrue(all(handle.closed for _, handle in handles))
        old = (self.dir / "suite" / "logfile-2026-09-27.log").read_text(encoding="utf-8")
        new = (self.dir / "suite" / "logfile-2026-09-28.log").read_text(encoding="utf-8")
        self.assertIn("path=before", old)
        self.assertNotIn("path=after", old)
        self.assertIn("path=after", new)

    def test_close_then_emit_reopens(self):
        log = EventLog(self.dir, clock=lambda: FIXED)
        log.emit("config.created", path="a")
        log.close()
        log.emit("config.created", path="b")
        log.close()
        text = (self.dir / "suite" / "logfile-2026-09-27.log").read_text(encoding="utf-8")
        self.assertIn("path=a", text)
        self.assertIn("path=b", text)

    def test_init_event_log_closes_the_previous_log(self):
        previous = events.get_event_log()
        self.addCleanup(setattr, events, "_current", previous)
        first = events.init_event_log(self.dir, clock=lambda: FIXED)
        first.emit("config.created", path="a")
        self.assertTrue(first._handles)
        events.init_event_log(self.dir, clock=lambda: FIXED)
        self.assertEqual(first._handles, {})

    def test_write_failure_after_open_disables_the_sink(self):
        warnings = []
        log = EventLog(self.dir, clock=lambda: FIXED, on_sink_error=warnings.append)
        log.emit("config.created", path="a")
        for handle in log._handles.values():
            handle.close()  # a write to a closed file raises ValueError, not OSError
        log.emit("config.created", path="b")
        self.assertEqual(len(warnings), 2)
        log.emit("config.created", path="c")
        self.assertEqual(len(warnings), 2)

    def test_jsonl_keeps_debug_text_respects_level(self):
        log = EventLog(self.dir, text_level="info", clock=lambda: FIXED)
        log.emit("update.checked", current="0.1.0", latest=None, throttled=False)
        log.emit("config.created", path="x.cfg")
        lines = (self.dir / "suite" / "events-2026-09-27.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["event"] for line in lines], ["update.checked", "config.created"])
        text = (self.dir / "suite" / "logfile-2026-09-27.log").read_text(encoding="utf-8")
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
        line = (self.dir / "suite" / "events-2026-09-27.log").read_text(encoding="utf-8").strip()
        self.assertEqual(json.loads(line)["data"]["path"], str(Path("/x/y.cfg")))

    def test_each_tool_logs_to_its_own_folder(self):
        log = EventLog(self.dir, tool="wtf-cleaner", clock=lambda: FIXED)
        log.emit("config.created", path="a")
        log.set_context(tool="suite")
        log.emit("config.created", path="b")
        self.assertEqual(sorted(p.relative_to(self.dir).as_posix() for p in self.dir.rglob("*.log")),
                         ["suite/events-2026-09-27.log", "suite/logfile-2026-09-27.log",
                          "wtf-cleaner/events-2026-09-27.log", "wtf-cleaner/logfile-2026-09-27.log"])
        self.assertIn("path=a", (self.dir / "wtf-cleaner" / "logfile-2026-09-27.log").read_text(encoding="utf-8"))

    def test_odd_tool_name_logs_to_suite(self):
        EventLog(self.dir, tool="../x", clock=lambda: FIXED).emit("config.created", path="a")
        self.assertTrue((self.dir / "suite" / "events-2026-09-27.log").exists())

    def test_prune_removes_only_old_log_files(self):
        (self.dir / "wtf-cleaner").mkdir()
        old = self.dir / "wtf-cleaner" / "events-2026-01-01.log"
        old.write_text("{}\n")
        keep = self.dir / "wtf-cleaner" / "logfile-2026-09-20.log"
        keep.write_text("x\n")
        other = self.dir / "wtf-cleaner" / "notes-2020-01-01.txt"
        other.write_text("x")
        removed = EventLog(self.dir, retention_days=90, clock=lambda: FIXED).prune()
        self.assertEqual(removed, [old])
        self.assertTrue(keep.exists())
        self.assertTrue(other.exists())

    def test_flat_logs_are_split_into_tool_folders(self):
        suite_rec = json.dumps({"tool": "suite", "event": "session.start"})
        tool_rec = json.dumps({"tool": "wtf-cleaner", "event": "scan.started"})
        (self.dir / "events-2026-09-20.jsonl").write_text(f"{suite_rec}\n{tool_rec}\nnot json\n", encoding="utf-8")
        (self.dir / "wow-tools-2026-09-20.log").write_text(
            "2026-09-20 10:00:00 INFO    [suite] session.start  argv=\n"
            "2026-09-20 10:00:01 INFO    [wtf-cleaner] scan.started  flavor=_retail_\n", encoding="utf-8")
        newer = self.dir / "wtf-cleaner" / "logfile-2026-09-20.log"
        newer.parent.mkdir()
        newer.write_text("already here\n", encoding="utf-8")
        moved = events.migrate_flat_logs(self.dir)
        self.assertEqual(len(moved), 2)
        self.assertFalse(any(self.dir.glob("*.jsonl")))
        self.assertEqual((self.dir / "suite" / "events-2026-09-20.log").read_text(encoding="utf-8"),
                         f"{suite_rec}\nnot json\n")
        self.assertEqual((self.dir / "wtf-cleaner" / "events-2026-09-20.log").read_text(encoding="utf-8"),
                         f"{tool_rec}\n")
        self.assertIn("[suite] session.start", (self.dir / "suite" / "logfile-2026-09-20.log").read_text())
        self.assertEqual(newer.read_text(encoding="utf-8").splitlines(),
                         ["2026-09-20 10:00:01 INFO    [wtf-cleaner] scan.started  flavor=_retail_", "already here"])

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
