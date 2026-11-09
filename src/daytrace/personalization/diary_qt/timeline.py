"""Virtualized timeline painted on a Qt canvas."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..diary_model import duration
from .theme import (
    ACCENT,
    BG,
    BORDER,
    FAINT,
    GAP_BORDER,
    GAP_FILL,
    INK,
    MUTED,
    PENDING_BG,
    PENDING_BORDER,
    PENDING_INK,
    SHADOW,
    SURFACE,
)
from ..timeline_view import category_color


class TimelineWidget(QWidget):
    card_clicked = Signal(object)
    card_confirm = Signal(object)
    card_hovered = Signal(str)

    pitch = 100
    rail = 84

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards: list = []
        self.colors: dict = {}
        self.hover_index: int | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_cards(self, cards, colors):
        self.cards = cards
        self.colors = colors
        h = 24 + max(1, len(cards)) * self.pitch
        self.setMinimumHeight(h)
        self.update()

    def _geom(self, index):
        y = 6 + index * self.pitch
        left = self.rail + 8
        right = max(520, self.width()) - 16
        bottom = y + self.pitch - 8
        return left, right, y, bottom

    def _index_at(self, pos):
        if pos.y() < 8:
            return None
        index = int((pos.y() - 8) // self.pitch)
        return index if 0 <= index < len(self.cards) else None

    def _chip_rect(self, index):
        card = self.cards[index]
        if not card.get('review'):
            return None
        left, right, y, bottom = self._geom(index)
        chip_w = min(120, 24 + len(card['status']) * 10)
        return QRectF(right - chip_w - 12, bottom - 22, chip_w, 20)

    def sizeHint(self):
        return super().sizeHint()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(BG))
        width = self.width()
        rail_x = self.rail - 18
        if self.cards:
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(rail_x, 8, rail_x, len(self.cards) * self.pitch + 16)

        first = 0
        last = len(self.cards)
        vis = self.visibleRegion().boundingRect()
        first = max(0, int(max(0, vis.top()) // self.pitch) - 2)
        last = min(len(self.cards), int(max(vis.bottom(), self.height()) // self.pitch) + 3)

        title_font = QFont('Microsoft YaHei UI', 10)
        title_font.setBold(True)
        meta_font = QFont('Microsoft YaHei UI', 8)
        time_font = QFont('Segoe UI', 10)
        time_font.setBold(True)
        time_end = QFont('Segoe UI', 8)

        for index in range(first, last):
            card = self.cards[index]
            left, right, y, bottom = self._geom(index)
            active = card['rows'][0]['state'] == 'active'
            hovered = index == self.hover_index
            h_card = bottom - y

            path = QPainterPath()
            path.addRoundedRect(QRectF(left, y, right - left, h_card), 8, 8)
            fill = QColor(SURFACE if active else GAP_FILL)
            painter.fillPath(path, fill)
            border = QColor(ACCENT if hovered and active else GAP_BORDER if not active else BORDER)
            painter.setPen(QPen(border, 1.5 if hovered else 1))
            painter.drawPath(path)
            painter.setPen(QPen(QColor(SHADOW), 1))
            painter.drawLine(int(left + 2), int(bottom + 1), int(right + 1), int(bottom + 1))

            dot = QColor(ACCENT if active and card.get('category') else FAINT)
            painter.setBrush(dot)
            painter.setPen(QPen(QColor(BG), 2))
            painter.drawEllipse(QPointF(rail_x, y + (bottom - y) // 2), 4, 4)

            start = datetime.fromtimestamp(card['start_ms'] / 1000)
            end = datetime.fromtimestamp(card['end_ms'] / 1000)
            painter.setFont(time_font)
            painter.setPen(QColor(INK if active else MUTED))
            painter.drawText(QRectF(rail_x - 54, y + 6, 48, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, start.strftime('%H:%M'))
            painter.setFont(time_end)
            painter.setPen(QColor(FAINT))
            painter.drawText(QRectF(rail_x - 54, y + 22, 48, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, end.strftime('%H:%M'))

            painter.setFont(title_font)
            painter.setPen(QColor(INK if active else MUTED))
            title_w = int(right - left - 96)
            title = painter.fontMetrics().elidedText(card['title'], Qt.TextElideMode.ElideRight, title_w)
            painter.drawText(QRectF(left + 10, y + 6, title_w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

            painter.setFont(meta_font)
            painter.setPen(QColor(FAINT))
            dur = duration(card['end_ms'] - card['start_ms'])
            painter.drawText(QRectF(right - 84, y + 8, 72, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dur)

            painter.setPen(QColor(MUTED if active else FAINT))
            desc_w = int(right - left - 24)
            desc = painter.fontMetrics().elidedText(card['description'], Qt.TextElideMode.ElideRight, desc_w)
            painter.drawText(QRectF(left + 10, y + 26, desc_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, desc)

            foot = bottom - 17
            cx = left + 10
            category = card.get('category') or ''
            if category:
                color = category_color(category, self.colors)
                pill_w = min(96, 14 + len(category) * 11)
                pill = QRectF(cx, foot, pill_w, 17)
                painter.setPen(QPen(QColor(BORDER), 1))
                painter.setBrush(QColor('#F4F6FA'))
                painter.drawRoundedRect(pill, 6, 6)
                painter.setPen(QColor(color))
                painter.drawText(pill.adjusted(8, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, category[:12])
                cx += pill_w + 10
            if card.get('project'):
                painter.setPen(QColor(FAINT))
                painter.drawText(QRectF(cx, foot, 200, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, card['project'][:24])

            if card.get('review'):
                chip = self._chip_rect(index)
                if chip:
                    painter.setPen(QPen(QColor(PENDING_BORDER), 1))
                    painter.setBrush(QColor(PENDING_BG))
                    painter.drawRoundedRect(chip, 8, 8)
                    painter.setPen(QColor(PENDING_INK))
                    painter.drawText(chip.adjusted(0, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, card['status'])
            elif card.get('status'):
                painter.setPen(QColor(FAINT))
                painter.drawText(QRectF(right - 130, foot, 120, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, card['status'])

        if not self.cards:
            painter.setPen(QColor(MUTED))
            painter.setFont(QFont('Microsoft YaHei UI', 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '今天还没有可展示的活动\n稍后再来，或切换日期查看历史')

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position())
        if index != self.hover_index:
            self.hover_index = index
            self.update()
        if index is not None:
            self.card_hovered.emit(self.cards[index]['rows'][0]['interval_id'])
            chip = self._chip_rect(index)
            if chip and chip.contains(event.position()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.PointingHandCursor if index is not None else Qt.CursorShape.ArrowCursor)
        else:
            self.card_hovered.emit('')
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, _event):
        self.hover_index = None
        self.card_hovered.emit('')
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self._index_at(event.position())
        if index is None:
            return
        chip = self._chip_rect(index)
        if chip and chip.contains(event.position()):
            self.card_confirm.emit(self.cards[index])
        else:
            self.card_clicked.emit(self.cards[index])
