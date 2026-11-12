"""Small layout-friendly presentation widgets shared across pages."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy
import re


def activity_heading(card):
    """User-requested display name; leave source titles and task identities untouched."""
    title = card['title']
    rows = card.get('rows', [])
    if not rows or any(row.get('manual') for row in rows):
        return title
    row = rows[0]
    raw = row.get('title') or title
    chrome = (row.get('process_name') or '').lower() == 'chrome.exe' or raw.endswith('Google Chrome')
    trends = row.get('browser_domain') == 'trends.google.com' or bool(
        re.search(r'(?:Google 趋势|谷歌趋势|Google Trends)\s*[-–—]\s*Google Chrome$', raw, re.IGNORECASE))
    if chrome and trends:
        return '搜索-谷歌趋势-Google Chrome'
    if row.get('browser_domain') and row.get('title'):
        return row['title']
    return title


class ElidedLabel(QLabel):
    def __init__(self, text='', parent=None, lines=1):
        super().__init__(text, parent)
        self.lines = lines
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def sizeHint(self):
        return QSize(100, self.fontMetrics().height() * self.lines + 2)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
        self.updateGeometry()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        lines = self.text().splitlines() or ['']
        height = self.fontMetrics().height()
        for index, line in enumerate(lines[:self.lines]):
            if index == self.lines - 1 and len(lines) > self.lines:
                line += '…'
            text = self.fontMetrics().elidedText(line, Qt.TextElideMode.ElideRight, max(0, self.width()))
            painter.drawText(0, index * height, self.width(), height, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


def concise_overview(cards):
    """Two factual lines, computed locally; no invented AI prose or raw title wall."""
    from ..diary_model import duration
    active = [c for c in cards if c['rows'][0]['state'] == 'active']
    if not active:
        return '所选日期暂无活动记录。'
    # Count source intervals, not display spans which may include folded gaps.
    intervals = {r['interval_id']: r for c in active for r in c['rows'] if r['state'] == 'active'}
    total = sum(r['end_ms'] - r['start_ms'] for r in intervals.values())
    pending = sum(bool(c.get('review')) for c in active)
    return f'已记录 {len(active)} 段活动 · 活动时长 {duration(total)}\n' + (
        f'还有 {pending} 段活动需要确认。' if pending else '当前活动均已归类，可随时查看依据和纠正。')
