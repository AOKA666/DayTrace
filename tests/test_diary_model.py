import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import unittest

from daytrace.personalization.diary_model import cards, overview


def _row(**overrides):
    base = dict(
        interval_id='i1',
        session_id='s1',
        state='active',
        start_ms=0,
        end_ms=60_000,
        label='撰写接口',
        category='工作',
        project='DayTrace',
        task_id='t1',
        title='api.py',
        app_id='code',
        manual=0,
        disposition='',
        reliability='supported',
        reason='整理调用路径。',
        source='rule',
    )
    base.update(overrides)
    return base


class DiaryModelTests(unittest.TestCase):
    def test_unknown_gap_never_invents_activity(self):
        rows = [
            _row(end_ms=60_000),
            _row(interval_id='gap', state='unknown', start_ms=60_000, end_ms=120_000, label=None, category='', project='', task_id=None, title=None, source='fallback', reliability='unknown'),
        ]
        items = cards(rows)
        gap = next(c for c in items if c['rows'][0]['state'] == 'unknown')
        self.assertEqual(gap['title'], '未记录时间')
        self.assertNotIn('睡眠', gap['description'])
        self.assertNotIn('休息', gap['description'])
        summary = overview(items)
        self.assertNotIn('睡眠', summary)

    def test_pending_chip_cards_flag_review(self):
        rows = [_row(label='待核实页面', task_id=None, reliability='tentative', source='ai', disposition='')]
        items = cards(rows)
        self.assertTrue(items[0]['review'])
        self.assertIn('待确认', items[0]['status'])


if __name__ == '__main__':
    unittest.main()
