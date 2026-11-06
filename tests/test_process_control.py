"""Real subprocess/SQLite control tests using only a fake desktop source."""
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = getattr(sys, "_base_executable", sys.executable)
sys.path.insert(0, str(ROOT / "src"))
from daytrace.storage.repository import readonly


class ProcessControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "control.sqlite3"
        self.processes = []

    def tearDown(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=10)
        self.temp.cleanup()

    def query(self, sql):
        db = readonly(self.db)
        try:
            return db.execute(sql).fetchall()
        finally:
            db.close()

    def start(self):
        # Windows venv python.exe is a redirector with a different child PID.
        # Use the actual interpreter so kill() targets our worker, not its launcher.
        proc = subprocess.Popen([PYTHON, str(ROOT / "tests/fixtures/collector_worker.py"), str(self.db)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.processes.append(proc)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.assertIsNone(proc.poll(), "Synthetic collector failed to start")
            try:
                rows = self.query(f"SELECT id FROM capture_sessions WHERE pid={proc.pid} AND ended_ms IS NULL")
                if rows:
                    return proc
            except sqlite3.Error:
                pass
            time.sleep(0.05)
        self.fail("Collector startup timed out")

    def command(self, command):
        return subprocess.run([sys.executable, str(ROOT / "daytrace.py"), "--db", str(self.db), command], capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_pause_resume_stop_acknowledgements_and_no_title_logs(self):
        proc = self.start()
        self.assertEqual(self.command("pause").returncode, 0)
        self.assertEqual(self.query("SELECT status FROM capture_sessions")[0][0], "paused")
        count = self.query("SELECT COUNT(*) FROM activity_events WHERE title IS NOT NULL")[0][0]
        time.sleep(1.2)
        self.assertEqual(self.query("SELECT COUNT(*) FROM activity_events WHERE title IS NOT NULL")[0][0], count)
        self.assertEqual(self.command("resume").returncode, 0)
        time.sleep(1.2)
        self.assertEqual(self.command("stop").returncode, 0)
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, err)
        self.assertNotIn("fixturesecret", out + err)
        self.assertEqual(self.query("SELECT status FROM capture_sessions")[0][0], "stopped")
        self.assertGreater(self.query("SELECT SUM(duration_ms) FROM activity_intervals WHERE state='paused'")[0][0], 0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM control_commands WHERE result='ok'")[0][0], 3)

    def test_killed_process_releases_lock_and_recovers_without_false_active_tail(self):
        proc = self.start()
        time.sleep(1.2)
        before_kill = self.query("SELECT heartbeat_ms FROM capture_sessions")[0][0]
        proc.kill()  # Only this test's own synthetic worker, never a user's process.
        proc.communicate(timeout=5)
        # A commit can race the kill request. The durable checkpoint after exit is
        # authoritative, not a sample taken while the writer was still alive.
        checkpoint = self.query("SELECT heartbeat_ms FROM capture_sessions")[0][0]
        self.assertGreaterEqual(checkpoint, before_kill)
        time.sleep(0.15)
        restarted = self.start()
        self.assertEqual(self.command("stop").returncode, 0)
        restarted.communicate(timeout=5)
        old = self.query("SELECT ended_ms,exit_reason FROM capture_sessions ORDER BY started_ms LIMIT 1")[0]
        self.assertEqual(old[0], checkpoint)
        self.assertEqual(old[1], "crash")
        self.assertGreater(self.query("SELECT SUM(duration_ms) FROM activity_intervals WHERE state='unknown'")[0][0], 0)
        self.assertEqual(self.query("PRAGMA integrity_check")[0][0], "ok")

    def test_second_collector_rejected_without_disturbing_first(self):
        first = self.start()
        second = subprocess.run([PYTHON, str(ROOT / "tests/fixtures/collector_worker.py"), str(self.db)], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(second.returncode, 0)
        self.assertIsNone(first.poll())
        self.assertEqual(self.query("SELECT COUNT(*) FROM capture_sessions")[0][0], 1)
        self.assertEqual(self.command("stop").returncode, 0)
        first.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
