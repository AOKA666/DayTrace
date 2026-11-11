"""Consistent 24-unit SVG icons; no font-dependent symbol glyphs."""
from functools import lru_cache
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    'pending': '<circle cx="12" cy="12" r="8"/>',
    'clock': '<circle cx="12" cy="12" r="8"/><path d="M12 8v4.5l3 1.5"/>',
    'sparkles': '<path d="M9 3.5 11 8l4.5 2L11 12 9 16.5 7 12 2.5 10 7 8Z"/><path d="M17.5 13.5 19 17l3.5 1.5L19 20l-1.5 3.5L16 20l-3.5-1.5L16 17Z"/>',
    'settings': '<path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z"/><path d="M19.16 13.04a1.4 1.4 0 0 0 .28 1.54l.05.05a1.7 1.7 0 1 1-2.4 2.4l-.05-.05a1.4 1.4 0 0 0-1.54-.28 1.4 1.4 0 0 0-.85 1.28v.14a1.7 1.7 0 1 1-3.4 0v-.14a1.4 1.4 0 0 0-.85-1.28 1.4 1.4 0 0 0-1.54.28l-.05.05a1.7 1.7 0 1 1-2.4-2.4l.05-.05a1.4 1.4 0 0 0 .28-1.54 1.4 1.4 0 0 0-1.28-.85H4.9a1.7 1.7 0 1 1 0-3.4h.14a1.4 1.4 0 0 0 1.28-.85 1.4 1.4 0 0 0-.28-1.54l-.05-.05a1.7 1.7 0 1 1 2.4-2.4l.05.05a1.4 1.4 0 0 0 1.54.28h.01A1.4 1.4 0 0 0 11.15 5.2V5.06a1.7 1.7 0 1 1 3.4 0v.14a1.4 1.4 0 0 0 .85 1.28 1.4 1.4 0 0 0 1.54-.28l.05-.05a1.7 1.7 0 1 1 2.4 2.4l-.05.05a1.4 1.4 0 0 0-.28 1.54v.01a1.4 1.4 0 0 0 1.28.85h.14a1.7 1.7 0 1 1 0 3.4h-.14a1.4 1.4 0 0 0-1.28.85Z"/>',
    'left': '<path d="M14.5 5 8 12l6.5 7"/>',
    'right': '<path d="M9.5 5 16 12l-6.5 7"/>',
    'calendar': '<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M8 3.5v4m8-4v4M4 11h16"/>',
    'search': '<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/>',
    'leaf': '<path d="M7 17C5 9 11 5 20 4c0 9-4 16-12 14M6 20 16.5 8.5"/>',
}


@lru_cache(maxsize=64)
def icon(name, color='#86868B', size=20):
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round">{PATHS[name]}</svg>'
    )
    dpr = 2
    pixmap = QPixmap(size * dpr, size * dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return QIcon(pixmap)
