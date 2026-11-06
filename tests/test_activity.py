from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from daytrace.cli import main, records
from daytrace.domain import Observation
from daytrace.engine import Engine
from daytrace.privacy import excluded, redact_title, app_identity
from daytrace.service import simulate
from daytrace.storage.repository import InstanceLock, Repository, readonly, is_running

WALL = 1_798_761_600_000
A = Observation("active", "Code.exe", "project-code", "Synthetic file.py", 10)
B = Observation("active", "msedge.exe", "browser", "Synthetic reference", 20)


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "activity.sqlite3"
        self.repo = Repository(self.path)
        self.engine = Engine(self.repo, WALL, 0, idle_ms=5000)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def sample(self, second, obs=A, idle=0, wall=None):
        self.engine.sample(second * 1000, wall if wall is not None else WALL + second * 1000, obs, idle * 1000)

    def totals(self):
        return dict(self.repo.db.execute("SELECT state,SUM(duration_ms) FROM activity_intervals GROUP BY state").fetchall())

    def events(self, kind=None):
        if kind:
            return self.repo.db.execute("SELECT * FROM activity_events WHERE kind=?", (kind,)).fetchall()
        return self.repo.db.execute("SELECT * FROM activity_events").fetchall()

    def assert_invariants(self):
        rows = self.repo.db.execute("SELECT * FROM activity_intervals WHERE end_ms>start_ms ORDER BY start_ms").fetchall()
        for row in rows:
            self.assertGreaterEqual(row["duration_ms"], 0)
        for left, right in zip(rows, rows[1:]):
            self.assertLessEqual(left["end_ms"], right["start_ms"])
        self.assertEqual(self.repo.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.repo.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_repeated_samples_do_not_duplicate_events_or_intervals(self):
        for i in range(100):
            self.sample(i)
        self.assertEqual(len(self.events("foreground_switch")), 1)
        self.assertEqual(self.repo.db.execute("SELECT COUNT(*) FROM activity_intervals").fetchone()[0], 1)
        self.assertEqual(self.totals()["active"], 99000)

    def test_a_b_a_and_title_change(self):
        self.sample(0)
        self.sample(2, B)
        self.sample(4, A)
        self.sample(5, Observation("active", A.process_name, A.app_id, "Other document", A.window))
        self.engine.stop(7000, WALL + 7000)
        self.assertEqual(len(self.events("foreground_switch")), 3)
        self.assertEqual(len(self.events("title_change")), 1)
        totals = dict(self.repo.db.execute("SELECT process_name,SUM(duration_ms) FROM activity_intervals WHERE state='active' GROUP BY process_name").fetchall())
        self.assertEqual(totals, {"Code.exe": 5000, "msedge.exe": 2000})
        self.assert_invariants()

    def test_idle_retroactive_across_application_intervals(self):
        self.sample(0)
        self.sample(1, A, 1)
        self.sample(2, B, 2)
        for i in range(3, 11):
            self.sample(i, B, i)
        self.assertEqual(self.totals().get("active", 0), 0)
        self.assertEqual(self.totals()["idle"], 10000)
        self.assertEqual(len(self.events("idle_detected")), 1)
        self.sample(11, A, 0)
        self.sample(12, A, 0)
        self.assertEqual(self.totals()["active"], 1000)
        self.assert_invariants()

    def test_idle_splits_existing_active_interval(self):
        for i in range(10):
            self.sample(i, A, max(0, i - 3))
        self.assertEqual(self.totals()["active"], 3000)
        self.assertEqual(self.totals()["idle"], 6000)
        self.assert_invariants()

    def test_idle_start_does_not_backdate_before_monitoring(self):
        self.sample(0, A, 300)
        self.sample(1, A, 301)
        self.assertEqual(self.totals()["idle"], 1000)
        self.assertEqual(min(r[0] for r in self.repo.db.execute("SELECT start_ms FROM activity_intervals")), WALL)

    def test_paused_and_excluded_not_overwritten_by_idle(self):
        self.sample(0)
        self.sample(1, Observation("excluded", "secret.exe", "secret", "secret"))
        self.sample(2, Observation("excluded"))
        self.engine.pause(3000, WALL + 3000)
        self.sample(4, Observation("active", "secret.exe", "secret", "PRIVATE"))
        self.engine.resume(5000, WALL + 5000)
        self.sample(5, A, 5)
        self.sample(6, A, 6)
        self.assertEqual(self.totals()["excluded"], 2000)
        self.assertEqual(self.totals()["paused"], 2000)
        all_rows = str([tuple(r) for r in self.repo.db.execute("SELECT * FROM activity_events")])
        self.assertNotIn("PRIVATE", all_rows)
        self.assertNotIn("secret.exe", all_rows)
        self.assert_invariants()

    def test_locked_and_suspended_remain_anonymous(self):
        self.sample(0)
        self.sample(1, Observation("locked", "secret.exe", "id", "SECRET"))
        self.sample(2, Observation("suspended"))
        self.sample(300, Observation("suspended"))
        self.sample(301)
        self.assertEqual(self.totals()["locked"], 1000)
        self.assertEqual(self.totals()["suspended"], 299000)
        self.assertFalse(any(r["title"] == "SECRET" for r in self.events()))
        self.assert_invariants()

    def test_stall_is_unknown_not_active(self):
        self.sample(0)
        self.sample(1)
        self.sample(60)
        self.assertEqual(self.totals()["active"], 1000)
        self.assertEqual(self.totals()["unknown"], 59000)
        self.assertEqual(len(self.events("observation_gap")), 1)

    def test_clock_jumps_do_not_create_negative_or_overlapping_time(self):
        self.sample(0)
        self.sample(1, wall=WALL - 3_600_000)
        self.sample(2, wall=WALL + 9_000_000)
        self.assertEqual(self.totals()["active"], 2000)
        self.assertEqual(len(self.events("clock_adjustment")), 2)
        self.assert_invariants()

    def test_monotonic_regression_rejected(self):
        self.sample(1)
        with self.assertRaises(ValueError):
            self.sample(0)

    def test_crash_recovery_caps_last_app_and_records_unknown_gap(self):
        self.sample(0)
        self.sample(3)
        old_session = self.engine.session
        self.repo.recover(WALL + 10_000)
        self.assertEqual(self.totals()["active"], 3000)
        self.assertEqual(self.totals()["unknown"], 7000)
        session = self.repo.db.execute("SELECT * FROM capture_sessions WHERE id=?", (old_session,)).fetchone()
        self.assertEqual(session["ended_ms"], WALL + 3000)
        self.assertEqual(session["exit_reason"], "crash")
        self.engine = Engine(self.repo, WALL + 10_000, 10000)
        self.sample(10, B)
        self.sample(11, B)
        self.assert_invariants()

    def test_restart_with_backward_wall_clock_uses_nonoverlapping_anchor(self):
        self.sample(0)
        self.sample(3)
        self.repo.recover(WALL - 10000)
        self.engine = Engine(self.repo, WALL - 10000, 10000)
        self.sample(10, B, wall=WALL - 10000)
        self.sample(11, B, wall=WALL - 9000)
        self.assert_invariants()

    def test_stop_idempotent_and_rejects_late_samples(self):
        self.sample(0)
        self.engine.stop(1000, WALL + 1000)
        self.engine.stop(2000, WALL + 2000)
        self.assertEqual(len(self.events("stop")), 1)
        with self.assertRaises(RuntimeError):
            self.sample(3)
        self.assert_invariants()

    def test_title_redacted_before_persistence(self):
        self.sample(0, Observation("active", "app.exe", "app", "password=supersecret user@example.com https://test.invalid/?token=bad", 1))
        value = self.events("foreground_switch")[0]["title"]
        for secret in ("supersecret", "user@example.com", "token=bad"):
            self.assertNotIn(secret, value)

    def test_title_retention_and_foreign_keys(self):
        self.sample(0)
        self.sample(1)
        self.engine.stop(2000, WALL + 2000)
        self.repo.cleanup(WALL + 8 * 86_400_000)
        self.assertFalse(any(r[0] for r in self.repo.db.execute("SELECT title FROM activity_events")))
        self.assertFalse(any(r[0] for r in self.repo.db.execute("SELECT title FROM activity_intervals")))
        self.assertEqual(self.totals()["active"], 2000)
        self.repo.cleanup(WALL + 91 * 86_400_000)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.totals(), {})
        self.assert_invariants()

    def test_overlap_rejected_by_database(self):
        self.sample(0)
        self.sample(3)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.repo.transaction():
                self.repo.interval(self.engine.session, WALL + 1, WALL + 2000, "active")

    def test_atomic_rollback_on_failed_sample(self):
        self.sample(0)
        before = self.repo.db.execute("SELECT heartbeat_ms FROM capture_sessions").fetchone()[0]
        with patch.object(self.repo, "event", side_effect=sqlite3.OperationalError("synthetic failure")):
            with self.assertRaises(sqlite3.OperationalError):
                self.sample(2, B)
        self.assertEqual(self.repo.db.execute("SELECT heartbeat_ms FROM capture_sessions").fetchone()[0], before)
        self.assertEqual(self.totals()["active"], 0)

    def test_same_window_title_new_document_is_not_app_switch(self):
        self.sample(0)
        self.sample(1, Observation("active", A.process_name, A.app_id, "another.py", A.window))
        self.assertEqual(len(self.events("foreground_switch")), 1)
        self.assertEqual(len(self.events("title_change")), 1)

    def test_cross_midnight_remains_one_elapsed_interval(self):
        from datetime import datetime, timezone
        self.engine.stop(0, WALL)
        midnight = int(datetime(2027, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
        self.engine = Engine(self.repo, midnight - 1000, 0)
        self.engine.sample(0, midnight - 1000, A)
        self.engine.sample(2000, midnight + 1000, A)
        self.assertEqual(self.totals()["active"], 2000)
        self.assertEqual(self.repo.db.execute("SELECT COUNT(*) FROM activity_intervals").fetchone()[0], 1)


class PrivacyAndCLITests(unittest.TestCase):
    def test_records_hides_expired_titles_without_mutating_database(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.sqlite3"
            repo = Repository(path)
            engine = Engine(repo, 1000, 0)
            engine.sample(0, 1000, A)
            engine.stop(1000, 2000)
            output = io.StringIO()
            with redirect_stdout(output):
                records(path, "events", 100, True)
            self.assertNotIn("Synthetic file.py", output.getvalue())
            self.assertTrue(repo.db.execute("SELECT title FROM activity_events WHERE title IS NOT NULL").fetchone())
            repo.close()

    def test_prune_requires_no_live_collector(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.sqlite3"
            repo = Repository(path)
            engine = Engine(repo, 1000, 0)
            engine.sample(0, 1000, A)
            engine.stop(1000, 2000)
            repo.close()
            with InstanceLock(path), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--db", str(path), "prune"]), 1)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--db", str(path), "prune"]), 0)
            db = readonly(path)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0], 0)
            db.close()

    def test_exclusions_casefold_name_and_path(self):
        self.assertTrue(excluded(r"C:\Apps\Secret.exe", ["secret.EXE"]))
        self.assertTrue(excluded(r"C:\Apps\Secret.exe", [r"c:\apps\SECRET.exe"]))
        self.assertFalse(excluded(r"C:\Apps\Other.exe", ["secret.exe"]))
        self.assertEqual(app_identity(r"C:\App.exe"), app_identity(r"c:\APP.EXE"))

    def test_title_redaction_preserves_unicode_and_removes_control_characters(self):
        self.assertEqual(redact_title("资料\x1b[31m\n测试"), "资料 [31m 测试")
        self.assertNotIn("abcd", redact_title("API_KEY:abcd"))

    def test_default_tests_and_simulation_have_no_windows_dependency(self):
        from daytrace import engine, service
        self.assertNotIn("WindowsAPI", vars(engine))
        self.assertNotIn("WindowsAPI", vars(service))

    def test_instance_lock_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.sqlite3"
            with InstanceLock(path):
                self.assertTrue(is_running(path))
                with self.assertRaises(RuntimeError):
                    with InstanceLock(path):
                        pass
            self.assertFalse(is_running(path))

    def test_readonly_missing_database_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.sqlite3"
            with self.assertRaises(sqlite3.OperationalError):
                readonly(path)
            self.assertFalse(path.exists())

    def test_thirty_minute_simulation_and_cli_queries(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sim.sqlite3"
            with redirect_stdout(io.StringIO()):
                simulate(path)
            db = readonly(path)
            try:
                totals = dict(db.execute("SELECT state,SUM(duration_ms) FROM activity_intervals GROUP BY state"))
                self.assertEqual(totals, {"active": 1320000, "idle": 420000, "paused": 60000})
                self.assertEqual(db.execute("SELECT simulated FROM capture_sessions").fetchone()[0], 1)
                self.assertLess(db.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0], 20)
            finally:
                db.close()
            output = io.StringIO()
            with redirect_stdout(output):
                records(path, "events", 100, False)
            self.assertNotIn("Synthetic DayTrace fixture", output.getvalue())
            with self.assertRaises(RuntimeError):
                simulate(path)

    def test_delete_requires_stopped_collector_and_removes_sidecars(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "delete.sqlite3"
            repo = Repository(path)
            repo.close()
            with InstanceLock(path), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--db", str(path), "delete", "--yes"]), 1)
                self.assertTrue(path.exists())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--db", str(path), "delete", "--yes"]), 0)
            for suffix in ("", "-wal", "-shm"):
                self.assertFalse(Path(str(path) + suffix).exists())

    def test_commands_without_collector_fail_without_new_db(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.sqlite3"
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--db", str(path), "pause"]), 1)
            self.assertFalse(path.exists())

    def test_cli_entrypoint_help(self):
        result = subprocess.run([sys.executable, str(ROOT / "daytrace.py"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("simulate", result.stdout)


if __name__ == "__main__":
    unittest.main()
