"""Layout-based activity cards, recycled for the visible portion of the timeline."""
from datetime import datetime
from math import ceil

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget,
)
from ..category_palette import category_color
from ..diary_model import duration
from .primitives import ElidedLabel
from .theme import ACCENT, BG, BORDER, CARD_GAP, CARD_HEIGHT, FAINT, pill_style


class ActivityCard(QFrame):
    clicked = Signal()
    confirmed = Signal()
    hovered = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('activityCard')
        self.setFixedHeight(CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        grid = QGridLayout(self)
        grid.setContentsMargins(20, 10, 18, 10)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 1)
        self.duration = QLabel()
        self.duration.setObjectName('activityDuration')
        self.title = ElidedLabel()
        self.title.setObjectName('activityTitle')
        self.description = ElidedLabel()
        self.description.setObjectName('activityDescription')
        self.footer = ElidedLabel()
        self.footer.setObjectName('activityFooter')
        self.category = QLabel()
        self.category.setMaximumWidth(220)
        self.category.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel()
        self.status.setObjectName('confirmedState')
        self.confirm = QPushButton('待确认')
        self.confirm.setObjectName('pendingChip')
        self.confirm.clicked.connect(self.confirmed)
        grid.addWidget(self.duration, 0, 0)
        grid.addWidget(self.category, 0, 1, alignment=Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.title, 1, 0)
        grid.addWidget(self.description, 2, 0)
        grid.addWidget(self.footer, 3, 0)
        grid.addWidget(self.status, 2, 1, 2, 1, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        grid.addWidget(self.confirm, 2, 1, 2, 1, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        for label in (self.duration, self.title, self.description, self.footer, self.category, self.status):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def bind(self, card, colors):
        active = card['rows'][0]['state'] == 'active'
        self.setProperty('gap', not active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.duration.setText(duration(card['end_ms'] - card['start_ms']))
        self.title.setText(card['title'])
        self.description.setText(card.get('description') or '')
        footer = []
        if card.get('project'):
            footer.append('项目 · ' + card['project'])
        footer.extend('#' + t['name'] for t in card.get('tags', []))
        self.footer.setText('   '.join(footer))
        self.footer.setVisible(bool(footer))
        category = card.get('category') or ''
        self.category.setVisible(bool(category and category != '待确认'))
        self.category.setText(self.category.fontMetrics().elidedText(category, Qt.TextElideMode.ElideRight, 190))
        self.category.setToolTip(category)
        self.category.setStyleSheet(pill_style(category_color(category, colors)))
        pending = active and bool(card.get('review'))
        self.confirm.setVisible(pending)
        self.status.setVisible(not pending and bool(card.get('status')))
        self.status.setText(card.get('status') or '')
        self.setToolTip(card['title'])
        self.setAccessibleName(card['title'])

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)


class TimeRail(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(84)
        self.active = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 9, 23, 0)
        layout.setSpacing(2)
        self.start = QLabel()
        self.start.setObjectName('timeStart')
        self.end = QLabel()
        self.end.setObjectName('timeEnd')
        layout.addWidget(self.start)
        layout.addWidget(self.end)
        layout.addStretch()

    def bind(self, card):
        self.start.setText(datetime.fromtimestamp(card['start_ms'] / 1000).strftime('%H:%M'))
        self.end.setText(datetime.fromtimestamp(card['end_ms'] / 1000).strftime('%H:%M'))
        self.active = card['rows'][0]['state'] == 'active'
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(BORDER), 1.5))
        painter.drawLine(77, 0, 77, self.height())
        painter.setPen(QPen(QColor(BG), 2))
        painter.setBrush(QColor(ACCENT if self.active else FAINT))
        painter.drawEllipse(QPointF(77, 22), 4.5, 4.5)


class TimelineRow(QWidget):
    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline
        self.card = None
        self.setFixedHeight(timeline.pitch)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, CARD_GAP)
        row.setSpacing(20)
        self.rail = TimeRail()
        self.frame = ActivityCard()
        row.addWidget(self.rail)
        row.addWidget(self.frame, 1)
        self.frame.clicked.connect(lambda: timeline.card_clicked.emit(self.card))
        self.frame.confirmed.connect(lambda: timeline.card_confirm.emit(self.card))
        self.frame.hovered.connect(lambda entered: timeline.card_hovered.emit(self.card['rows'][0]['interval_id'] if entered and self.card else ''))

    def bind(self, card, colors):
        if card == self.card and colors == getattr(self, '_colors', None):
            return
        self.card = card
        self._colors = dict(colors)
        self.rail.bind(card)
        self.frame.bind(card, colors)


class TimelineWidget(QWidget):
    card_clicked = Signal(object)
    card_confirm = Signal(object)
    card_hovered = Signal(str)
    pitch = CARD_HEIGHT + CARD_GAP
    rail = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards, self.colors = [], {}
        self._pool = []
        self._scroll = None
        self._pending = False
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(4, 6, 4, 6)
        self._column.setSpacing(0)
        self._top = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._bottom = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._column.addItem(self._top)
        self._column.addItem(self._bottom)
        self.empty = QLabel('所选日期暂无活动记录\n可以切换日期查看其他记录')
        self.empty.setObjectName('caption')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(220)
        self._column.addWidget(self.empty)
        self._column.addStretch()

    def set_cards(self, cards, colors):
        self.cards, self.colors = cards, colors
        self.setMinimumHeight(12 + len(cards) * self.pitch if cards else 240)
        self.empty.setVisible(not cards)
        self._sync_rows()

    def _attach(self):
        if self._scroll:
            return
        parent = self.parentWidget()
        while parent and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent:
            self._scroll = parent
            parent.verticalScrollBar().valueChanged.connect(self._sync_rows)
            parent.viewport().installEventFilter(self)

    def _sync_rows(self, *_):
        self._pending = False
        self._attach()
        offset = self._scroll.verticalScrollBar().value() if self._scroll else 0
        height = self._scroll.viewport().height() if self._scroll else min(self.height(), 1000)
        first = max(0, offset // self.pitch - 1)
        first = min(first, max(0, len(self.cards) - 1))
        count = min(max(0, len(self.cards) - first), ceil(max(1, height) / self.pitch) + 3)
        while len(self._pool) < count:
            widget = TimelineRow(self)
            self._column.insertWidget(1 + len(self._pool), widget)
            self._pool.append(widget)
        for index, row in enumerate(self._pool):
            row.setVisible(index < count)
            if index < count:
                row.bind(self.cards[first + index], self.colors)
        self._top.changeSize(0, first * self.pitch, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        remaining = max(0, len(self.cards) - first - count)
        self._bottom.changeSize(0, remaining * self.pitch, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._column.invalidate()

    def _schedule(self):
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._sync_rows)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self._schedule()
        return super().eventFilter(watched, event)

    def sizeHint(self):
        return QSize(700, max(240, 12 + len(self.cards) * self.pitch))
