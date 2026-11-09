import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import unittest

from daytrace.personalization.diary_model import (
    build_display_cards,
    cards,
    compact_cards,
    filter_short_dwell_cards,
    overview,
    prepare_diary_rows,
    project_dwell_threshold,
)


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
        process_name='Code.exe',
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

    def test_active_without_task_label_shows_window_title(self):
        rows = [
            _row(
                interval_id='raw',
                label='',
                category='',
                task_id=None,
                title='DayTrace · README — Google Chrome',
                process_name='chrome.exe',
                reliability='tentative',
                source='pending',
                disposition='',
                reason='',
            )
        ]
        items = cards(rows)
        self.assertEqual(items[0]['title'], 'DayTrace · README — Google Chrome')
        self.assertEqual(items[0]['category'], '待确认')
        self.assertTrue(items[0]['review'])
        self.assertIn('前台窗口', items[0]['description'])

    def test_project_dwell_hides_short_active_segments(self):
        rows = [_row(start_ms=0, end_ms=3_000, title='弹窗', label='', task_id=None)]
        projected = project_dwell_threshold(rows, 5_000)
        self.assertEqual(projected[0]['state'], 'unknown')
        items = cards(prepare_diary_rows(rows, 5_000))
        self.assertEqual(items[0]['title'], '短暂停留')

    def test_short_dwell_filter_default_hidden(self):
        rows = [
            _row(interval_id='long', start_ms=0, end_ms=120_000, title='Chrome', label='', category='', task_id=None),
            _row(interval_id='short', start_ms=120_000, end_ms=128_000, title='通知', label='', category='', task_id=None),
        ]
        hidden = build_display_cards(rows, dwell_ms=60_000, show_short_dwells=False)
        visible = build_display_cards(rows, dwell_ms=60_000, show_short_dwells=True)
        self.assertEqual([c['title'] for c in hidden], ['Chrome'])
        self.assertIn('短暂停留', [c['title'] for c in visible])

    def test_filter_short_dwell_cards_respects_flag(self):
        brief = cards(prepare_diary_rows([_row(start_ms=0, end_ms=2_000, label='', task_id=None)], 5_000))
        self.assertEqual(len(filter_short_dwell_cards(brief, False, 5_000)), 0)
        self.assertEqual(len(filter_short_dwell_cards(brief, True, 5_000)), 1)

    def test_named_and_titled_short_active_hidden_by_default(self):
        rows = [
            _row(
                interval_id='mail',
                start_ms=0,
                end_ms=4_000,
                label='写邮件',
                category='沟通',
                task_id='t1',
                title='Outlook — 收件箱',
                reliability='supported',
            ),
            _row(
                interval_id='popup',
                start_ms=10_000,
                end_ms=13_000,
                label='',
                category='',
                task_id=None,
                title='系统通知 — Windows',
                reliability='tentative',
            ),
        ]
        hidden = build_display_cards(rows, dwell_ms=5_000, show_short_dwells=False)
        visible = build_display_cards(rows, dwell_ms=5_000, show_short_dwells=True)
        self.assertEqual(hidden, [])
        self.assertGreaterEqual(len(visible), 1)
        self.assertTrue(all(c['title'] == '短暂停留' for c in visible))

    def test_dwell_threshold_changes_card_count(self):
        rows = [
            _row(interval_id='long', start_ms=0, end_ms=120_000, title='Chrome', label='', category='', task_id=None),
            _row(interval_id='short', start_ms=120_000, end_ms=128_000, title='通知', label='', category='', task_id=None),
            _row(
                interval_id='gap',
                state='unknown',
                start_ms=128_000,
                end_ms=140_000,
                label=None,
                category='',
                project='',
                task_id=None,
                title=None,
                source='fallback',
            ),
        ]
        loose = build_display_cards(rows, dwell_ms=1_000, merge_gap_ms=180_000, fold_gap_ms=120_000)
        strict = build_display_cards(rows, dwell_ms=60_000, merge_gap_ms=180_000, fold_gap_ms=120_000, show_short_dwells=True)
        loose_titles = [c['title'] for c in loose]
        strict_titles = [c['title'] for c in strict]
        self.assertIn('通知', loose_titles)
        self.assertIn('短暂停留', strict_titles)
        self.assertNotIn('通知', strict_titles)

    def test_compact_merges_same_window_with_short_gap(self):
        rows = [
            _row(interval_id='a', start_ms=0, end_ms=60_000, title='VS Code', label='', category='', task_id=None),
            _row(interval_id='b', start_ms=150_000, end_ms=240_000, title='VS Code', label='', category='', task_id=None),
        ]
        merged = compact_cards(cards(rows), merge_gap_ms=180_000)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]['rows']), 2)

    def test_compact_folds_micro_unknown_gap(self):
        rows = [
            _row(interval_id='a', start_ms=0, end_ms=120_000, title='Chrome', label='', category='', task_id=None),
            _row(
                interval_id='gap',
                state='unknown',
                start_ms=120_000,
                end_ms=150_000,
                label=None,
                category='',
                project='',
                task_id=None,
                title=None,
                source='fallback',
            ),
            _row(interval_id='b', start_ms=150_000, end_ms=300_000, title='Chrome', label='', category='', task_id=None),
        ]
        merged = compact_cards(cards(rows), merge_gap_ms=180_000, fold_gap_ms=120_000)
        self.assertEqual(len(merged), 1)
        self.assertTrue(all(r['state'] == 'active' for r in merged[0]['rows']))

    def test_overview_includes_window_titled_active_segments(self):
        rows = [
            _row(
                label='工作',
                category='工作',
                task_id=None,
                title='VS Code - diary_model.py',
                reliability='unknown',
                source='fallback',
            )
        ]
        summary = overview(cards(rows))
        self.assertIn('VS Code', summary)
        self.assertNotIn('活动还在整理中', summary)


if __name__ == '__main__':
    unittest.main()
