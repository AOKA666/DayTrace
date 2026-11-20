import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from daytrace.personalization.diary_qt.statistics import (
    Statistics,
    aggregate_clock,
    half_totals,
    legend_items,
    summarize,
)


class StatisticsTests(unittest.TestCase):
    def test_clear_clock_uses_five_minute_dominance(self):
        base = int(datetime(2026, 1, 1).timestamp() * 1000)

        def row(identifier, start, end, category):
            return {
                'state': 'active',
                'interval_id': identifier,
                'start_ms': base + start * 60_000,
                'end_ms': base + end * 60_000,
                'category': category,
            }

        rows = [row('a', 0, 3, 'Work'), row('b', 3, 4, 'Chat'), row('c', 4, 10, 'Work')]
        spans = aggregate_clock(rows, 0)
        self.assertEqual(spans, [{'category': 'Work', 'start': 0, 'end': 10}])
        self.assertEqual(half_totals(rows, 0)[0], ('Work', 9 * 60_000))

    def test_all_day_legend_is_bounded_and_groups_remainder(self):
        totals = [(f'Category {index}', 100-index) for index in range(10)]
        items = legend_items(totals)
        self.assertEqual(len(items), 8)
        self.assertEqual(items[-1], ('其他 3 类', sum(value for _, value in totals[7:]), True))

    def test_totals_switch_and_hover(self):
        app = QApplication.instance() or QApplication([])
        widget = Statistics()
        widget.resize(1200, 800)
        rows = [{'state': 'active', 'interval_id': 'a', 'start_ms': 0, 'end_ms': 60000, 'category': 'Work'}]
        cards = [{'rows': rows}]
        self.assertEqual(summarize(cards + cards)[1], [('Work', 60000)])
        widget.set_cards(cards, {})
        before = widget.totals[:]
        widget.buttons[1].click()
        self.assertEqual(widget.half, 1)
        self.assertEqual(widget.totals, before)
        _, x, y, r = widget.geometry_values()
        self.assertEqual(widget.hit_sector(QPointF(x + r - 20, y)), 0)
        self.assertEqual(widget.hit_sector(QPointF(x, y)), -1)
        widget.hover = 0
        widget.offset = 7
        widget.set_cards(cards, {})
        self.assertEqual(widget.offset, 7)
        rows[0]['end_ms'] += 60000
        widget.set_cards(cards, {})
        self.assertEqual(widget.hover, 0)
        self.assertEqual(widget.offset, 7)
        widget.show()
        app.processEvents()
        self.assertFalse(widget.grab().isNull())
        widget.set_cards([], {})
        self.assertEqual(widget.hit_sector(QPointF(x + r - 20, y)), -1)
        widget.close()


if __name__ == '__main__':
    unittest.main()
