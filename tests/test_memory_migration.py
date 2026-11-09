import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from daytrace.personalization.store import Memory, PersonalizationUpgradeBlocked
from daytrace.storage.repository import InstanceLock, Repository


class MemoryMigrationTests(unittest.TestCase):
    def test_fresh_repository_is_version_3(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new.sqlite3'
            repo = Repository(path)
            try:
                self.assertEqual(repo.db.execute('PRAGMA user_version').fetchone()[0], 3)
                self.assertTrue(
                    repo.db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='personal_profile'"
                    ).fetchone()
                )
            finally:
                repo.close()

    def test_memory_opens_under_collector_lock_when_v3(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'live.sqlite3'
            Repository(path).close()
            lock = InstanceLock(path)
            lock.__enter__()
            try:
                memory = Memory(path, cleanup=False)
                memory.close()
            finally:
                lock.__exit__(None, None, None)

    def test_v2_without_personalization_blocked_with_friendly_error(self):
        migrations = Path(__file__).resolve().parents[1] / 'src/daytrace/storage/migrations'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.sqlite3'
            db = sqlite3.connect(path)
            db.executescript((migrations / '001_activity.sql').read_text('utf-8'))
            db.executescript((migrations / '002_content.sql').read_text('utf-8'))
            db.close()
            self.assertEqual(
                sqlite3.connect(path).execute('PRAGMA user_version').fetchone()[0],
                2,
            )
            lock = InstanceLock(path)
            lock.__enter__()
            try:
                with self.assertRaises(PersonalizationUpgradeBlocked) as ctx:
                    Memory(path, cleanup=False)
                self.assertIn('停止', str(ctx.exception))
            finally:
                lock.__exit__(None, None, None)


if __name__ == '__main__':
    unittest.main()
