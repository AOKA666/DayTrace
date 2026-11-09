"""Five-second admission uses only synthetic observations."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from daytrace.domain import Observation
from daytrace.engine import Engine
from daytrace.storage.repository import Repository


class DwellTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.repo=Repository(Path(self.temp.name)/'test.db')
        self.engine=Engine(self.repo,100000,0,min_active_ms=5000)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def sample(self,ms,title='A',state='active',idle=0,wall=None):
        observation=Observation('active','chrome.exe','chrome',title,1) if state=='active' else Observation(state)
        self.engine.sample(ms,wall or 100000+ms,observation,idle)

    def active(self):
        return self.repo.db.execute("SELECT * FROM activity_intervals WHERE state='active' ORDER BY start_ms").fetchall()

    def test_custom_threshold_and_gap_marker(self):
        self.engine.min_active_ms=8000
        self.sample(0); self.sample(4000); self.sample(7999)
        self.assertFalse(self.active())
        self.assertTrue(self.repo.db.execute("SELECT 1 FROM activity_events WHERE kind='dwell_gap'").fetchone())
        self.sample(8000)
        self.assertEqual(len(self.active()),1)

    def test_idle_backtrack_removes_subthreshold_prefix(self):
        self.sample(0);self.sample(4000);self.sample(5000)
        self.assertEqual(len(self.active()),1)
        self.engine.idle_ms=5000
        self.sample(6000,idle=5000)
        self.assertFalse(self.active())
        self.assertEqual(self.repo.db.execute("SELECT COUNT(*) FROM activity_events WHERE title IS NOT NULL").fetchone()[0],0)

    def test_under_five_seconds_has_no_page_or_content_event(self):
        self.sample(0)
        self.sample(4999)
        self.engine.stop(4999,104999)
        self.assertFalse(self.active())
        self.assertEqual(self.repo.db.execute('SELECT COUNT(*) FROM activity_events WHERE title IS NOT NULL OR process_name IS NOT NULL').fetchone()[0],0)

    def test_exactly_five_seconds_preserves_original_start(self):
        self.sample(0)
        self.sample(4000)
        self.sample(5000)
        row=self.active()[0]
        self.assertEqual((row['start_ms'],row['end_ms']),(100000,105000))
        self.assertEqual(self.engine.current.title,'A')

    def test_stop_at_threshold_keeps_completed_visit(self):
        self.sample(0)
        self.sample(4000)
        self.engine.stop(5000,105000)
        self.assertEqual(self.active()[0]['duration_ms'],5000)

    def test_short_tab_switch_resets_timer(self):
        self.sample(0,'A')
        self.sample(3000,'B')
        self.sample(6000,'A')
        self.sample(10000,'A')
        self.assertFalse(self.active())
        self.sample(11000,'A')
        self.assertEqual(self.active()[0]['start_ms'],106000)

    def test_qualifies_previous_page_on_switch_after_threshold(self):
        self.sample(0,'A')
        self.sample(4000,'A')
        self.sample(5000,'B')
        self.assertEqual(self.active()[0]['duration_ms'],5000)
        self.assertEqual(self.engine.current.state,'unknown')

    def test_short_interruption_is_not_absorbed_into_previous_app(self):
        for ms in (0,4000,5000): self.sample(ms)
        self.sample(6000,'B')
        self.sample(8000,'A')
        self.sample(12000,'A')
        self.sample(13000,'A')
        self.assertEqual([(r['start_ms'],r['end_ms']) for r in self.active()],[(100000,106000),(108000,113000)])
        self.assertFalse(self.repo.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_pause_and_idle_cancel_pending(self):
        self.sample(0)
        self.engine.pause(3000,103000)
        self.engine.resume(4000,104000)
        self.sample(4500)
        self.sample(5000,idle=300000)
        self.assertFalse(self.active())
        self.assertEqual(self.engine.current.state,'idle')

    def test_clock_adjustment_does_not_qualify_early(self):
        self.sample(0)
        self.sample(1000,wall=999999)
        self.assertFalse(self.active())
        self.sample(5000,wall=1003999)
        self.assertEqual(self.active()[0]['duration_ms'],5000)

    def test_stall_does_not_qualify_unobserved_time(self):
        self.sample(0)
        self.sample(10000)
        self.assertFalse(self.active())
        self.sample(14000)
        self.sample(15000)
        self.assertEqual(self.active()[0]['start_ms'],110000)

    def test_unavailable_window_at_threshold_does_not_admit_candidate(self):
        self.sample(0)
        self.sample(4000)
        self.sample(5000,state='unknown')
        self.assertFalse(self.active())
