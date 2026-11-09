import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from daytrace.personalization.display import activity_label, group_rows


def row(i, title='A', state='active', session='session'):
    return dict(interval_id=str(i), start_ms=i*1000, end_ms=(i+1)*1000,
                title=title, state=state, session_id=session, app_id='browser',
                process_name='chrome.exe', task_id=None, reliability='unknown',
                manual=0, disposition='review', label=None)


class DisplayTests(unittest.TestCase):
    def test_title_is_visible_without_ai_or_body(self):
        self.assertEqual(activity_label(row(0, 'Example - Google Chrome')), 'Example')
        self.assertEqual(activity_label(row(0, None)), 'chrome.exe')
        self.assertEqual(activity_label(row(0, 'private', 'excluded')), '隐私排除')

    def test_a_b_a_groups_display_only_and_sums_actual_durations(self):
        rows = [row(0), row(1,'B'), row(2)]
        groups = group_rows(rows)
        self.assertEqual([[r['interval_id'] for r in g] for g in groups], [['0','2'],['1']])
        self.assertEqual(sum(r['end_ms']-r['start_ms'] for r in groups[0]), 2000)
        self.assertEqual(len(rows), 3)

    def test_no_grouping_across_privacy_idle_unknown_gaps_or_sessions(self):
        for state in ('idle','excluded','unknown','paused'):
            self.assertEqual(len(group_rows([row(0),row(1,None,state),row(2)])),3)
        self.assertEqual(len(group_rows([row(0),row(2)])),2)
        self.assertEqual(len(group_rows([row(0),row(1,session='another')])),2)
        self.assertEqual(len(group_rows([row(0,None),row(1,None)])),2)

    def test_same_title_does_not_override_distinct_tasks_or_reviews(self):
        a,b=row(0),row(1)
        a['task_id']='task-a'; b['task_id']='task-b'
        self.assertEqual(len(group_rows([a,b])),2)
        b['task_id']='task-a'; b['manual']=1
        self.assertEqual(len(group_rows([a,b])),2)
