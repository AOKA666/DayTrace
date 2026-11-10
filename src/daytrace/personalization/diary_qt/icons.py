"""Consistent 24-unit SVG icons; no font-dependent symbol glyphs."""
from functools import lru_cache
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
 'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
 'sparkles': '<path d="m9 3 2 5 5 2-5 2-2 5-2-5-5-2 5-2Z M18 13l1.5 3.5L23 18l-3.5 1.5L18 23l-1.5-3.5L13 18l3.5-1.5Z"/>',
 'settings': '<path d="m9 3 1-2h4l1 2 2 1 2-.2 2 3-1 2v3l1 2-2 3-2-.2-2 1-1 2h-4l-1-2-2-1-2 .2-2-3 1-2V9L3 7l2-3 2 .2Z" transform="translate(0 1)"/><circle cx="12" cy="11" r="3"/>',
 'left': '<path d="m14 6-6 6 6 6"/>', 'right': '<path d="m10 6 6 6-6 6"/>',
 'calendar': '<rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v5m8-5v5M4 11h16"/>',
 'search': '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
 'leaf': '<path d="M6 18C3 9 10 5 20 3c0 10-4 17-12 15M5 21 16 8"/>',
}


@lru_cache(maxsize=64)
def icon(name, color='#86868B', size=20):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return QIcon(pixmap)
