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

    def test_short_return_cannot_qualify_by_accumulating_time(self):
        self.sample(0,'A')
        self.sample(3000,'B')
        self.sample(6000,'A')
        self.sample(7000,'A')
        self.assertFalse(self.active())
        self.sample(8000,'A')
        self.assertFalse(self.active())
        self.sample(11000,'A')
        self.assertEqual(sum(r['duration_ms'] for r in self.active()),5000)

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

    def test_return_after_threshold_is_a_new_visit(self):
        self.sample(0,'A');self.sample(3000,'B');self.sample(7000,'B')
        self.sample(8000,'A');self.sample(10000,'A')
        self.assertFalse(any(r['title']=='A' for r in self.active()))
        self.sample(13000,'A')
        self.assertEqual([(r['start_ms'],r['end_ms']) for r in self.active() if r['title']=='A'],[(108000,113000)])

    def test_multiple_short_returns_are_all_filtered(self):
        for ms in range(0,13001,1000): self.sample(ms,'A' if (ms//2000)%2==0 else 'B')
        self.engine.stop(13000,113000)
        rows=sorted(self.active(),key=lambda r:r['start_ms'])
        self.assertEqual(sum(r['duration_ms'] for r in rows),0)
        self.assertTrue(all(a['end_ms']<=b['start_ms'] for a,b in zip(rows,rows[1:])))
        self.assertFalse(rows)

    def test_privacy_boundary_discards_return_memory(self):
        self.sample(0,'A');self.sample(3000,'B');self.sample(4000,state='excluded')
        self.sample(4500,'A');self.sample(6500,'A')
        self.assertFalse(self.active())
        self.assertFalse(self.repo.db.execute('SELECT 1 FROM activity_events WHERE title IS NOT NULL').fetchone())

    def test_three_one_two_seconds_all_filtered(self):
        self.sample(0,'A');self.sample(3000,'B');self.sample(4000,'A')
        self.engine.stop(6000,106000)
        self.assertFalse(self.active())

    def test_idle_recomputes_cumulative_threshold(self):
        self.sample(0,'A');self.sample(3000,'B');self.sample(4000,'A');self.sample(6000,'A')
        self.engine.idle_ms=5000
        self.sample(10000,'A',idle=5000)
        self.assertFalse(self.active())
        self.assertFalse(self.repo.db.execute('SELECT 1 FROM activity_events WHERE title IS NOT NULL').fetchone())

    def test_idle_never_keeps_subthreshold_members_by_sum(self):
        self.sample(0,'A');self.sample(3000,'B');self.sample(4000,'A');self.sample(8000,'A')
        self.engine.idle_ms=5000
        self.sample(11000,'A',idle=5000)
        self.assertFalse(self.active())

    def test_ten_two_ten_seconds_merge_display_only_after_filtering(self):
        from daytrace.personalization.store import Memory
        from daytrace.personalization.diary_model import build_display_cards,card_duration_ms
        for ms in range(0,22001,1000):self.sample(ms,'B' if 10000<=ms<12000 else 'A')
        self.engine.stop(22000,122000)
        memory=Memory(self.repo.path,now=lambda:123000,cleanup=False)
        try:
            rows=memory.timeline()
            cards=build_display_cards(rows,5000)
            self.assertEqual(len(cards),1)
            self.assertEqual(card_duration_ms(cards[0]),20000)
            self.assertEqual(len(cards[0]['rows']),2)
            self.assertEqual({r['title'] for r in cards[0]['rows']},{'A'})
        finally:memory.close()

    def test_one_minute_threshold_requires_individual_visit(self):
        self.engine.min_active_ms=60000
        for ms in range(0,70001,1000):
            self.sample(ms,'B' if 35000<=ms<45000 else 'A')
            if ms<70000:self.assertFalse(self.active())
        self.assertFalse(self.active())

    def test_random_replay_never_assigns_interruption_time_to_another_page(self):
        import random
        randomizer=random.Random(41)
        observed=[]
        for second in range(100):
            title=randomizer.choice(['A','A','B','C','unknown'])
            observed.append(title)
            self.sample(second*1000,title,state='unknown' if title=='unknown' else 'active')
        self.engine.stop(100000,200000)
        rows=sorted(self.active(),key=lambda r:r['start_ms'])
        self.assertTrue(all(a['end_ms']<=b['start_ms'] for a,b in zip(rows,rows[1:])))
        for row in rows:
            for ms in range(row['start_ms']-100000,row['end_ms']-100000,1000):
                self.assertEqual(row['title'],observed[ms//1000])
        with self.repo.db:
            self.repo.db.execute('DELETE FROM activity_intervals WHERE session_id=?',(self.engine.session,))
        self.assertFalse(self.active())
