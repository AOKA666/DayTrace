import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from daytrace.personalization.diary_qt.theme import STYLESHEET, SURFACE, PENDING_CARD_BG, GAP_FILL
from daytrace.personalization.diary_qt.timeline import ActivityCard, TimelineWidget


def _card(title, category, index):
    start = 1_700_000_000_000 + index * 120_000
    return {
        'title': title,
        'description': '人工确认',
        'category': category,
        'start_ms': start,
        'end_ms': start + 60_000,
        'project': '',
        'tags': [],
        'review': category == '待确认',
        'status': '待确认' if category == '待确认' else '已确认',
        'rows': [{'state': 'active', 'interval_id': f'i{index}'}],
    }


def _rgb(image, x, y):
    color = image.pixelColor(int(x), int(y))
    return (color.red(), color.green(), color.blue())


class TimelinePaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLESHEET)

    def test_pending_fill_and_recycled_confirmed_card(self):
        card = _card('Synthetic', '工作', 0)
        widget = ActivityCard()
        widget.resize(700,112)
        def fill():
            self.app.processEvents()
            image = QImage(widget.size(), QImage.Format.Format_ARGB32)
            image.fill(QColor('#FFFFFF'))
            widget.render(image)
            return _rgb(image,350,55)
        card['review'] = True
        widget.bind(card, {'工作':'#7566D9'})
        self.assertEqual(fill(), QColor(PENDING_CARD_BG).getRgb()[:3])
        self.assertIsNone(widget.marker_color)
        self.assertFalse(widget.confirm.icon().isNull())
        card['rows'][0]['manual'] = 1
        card['review'] = False
        widget.bind(card, {'工作':'#7566D9'})
        self.assertEqual(fill(), (255,255,255))
        self.assertEqual(widget.marker_color.name(), '#7566d9')
        image = QImage(widget.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor('#FFFFFF'))
        widget.render(image)
        self.assertEqual(_rgb(image,9,55), QColor('#7566D9').getRgb()[:3])
        self.assertIn('✓',widget.status.text())
        widget.bind(card, {'工作':'#3C9B92'})
        self.assertEqual(fill(), (255,255,255))
        self.assertEqual(widget.marker_color.name(), '#3c9b92')
        card['rows'][0]['manual'] = 0
        card['rows'][0].update(source='rule', reliability='supported')
        card['status'] = '规则识别'
        widget.bind(card, {'工作':'#3C9B92'})
        self.assertEqual(fill(), (255,255,255))
        self.assertEqual(widget.marker_color.name(), '#3c9b92')
        self.assertEqual(widget.status.text(), '规则识别')
        card['review'] = True
        widget.bind(card, {'工作':'#3C9B92'})
        self.assertEqual(fill(), QColor(PENDING_CARD_BG).getRgb()[:3])
        self.assertIsNone(widget.marker_color)
        card['rows'][0]['state'] = 'idle'
        widget.bind(card,{})
        self.assertEqual(fill(), QColor(GAP_FILL).getRgb()[:3])
        widget.close()

    def test_later_cards_keep_neutral_surface_instead_of_previous_chip_color(self):
        colors = {'事业 / AI编程': '#7566D9', '牛马': '#3C9B92'}
        widget = TimelineWidget()
        widget.setFixedSize(900, 450)
        widget.set_cards(
            [
                _card('README.md - DayTrace', '事业 / AI编程', 0),
                _card('AGENTS.md - DayTrace', '事业 / AI编程', 1),
                _card('美团经营宝', '牛马', 2),
                _card('OKR-2', '待确认', 3),
            ],
            colors,
        )
        widget._sync_rows()
        self.app.processEvents()
        cards = [row.frame for row in widget._pool[:4]]
        self.assertEqual(len(cards), 4)

        image = QImage(widget.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor('#FFFFFF'))
        widget.render(image)

        surface = QColor(SURFACE)
        expected = (surface.red(), surface.green(), surface.blue())
        for index, card in enumerate(cards):
            point = card.mapTo(widget, card.rect().center())
            sample = _rgb(image, point.x(), point.y())
            self.assertEqual(sample, QColor(PENDING_CARD_BG).getRgb()[:3] if index == 3 else expected)
            self.assertNotEqual(sample, QColor('#7566D9').getRgb()[:3])
            self.assertNotEqual(sample, QColor('#3C9B92').getRgb()[:3])


if __name__ == '__main__':
    unittest.main()
