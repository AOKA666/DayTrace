"""Qt diary theme: paper background, rounded controls, restrained accent."""
from ..diary_theme import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_SOFT,
    BG,
    BORDER,
    FAINT,
    GAP_BORDER,
    GAP_FILL,
    INK,
    MUTED,
    NAV_ITEMS,
    PENDING_BG,
    PENDING_BORDER,
    PENDING_INK,
    SHADOW,
    SURFACE,
)

FONT_UI = '"Segoe UI", "Microsoft YaHei UI", sans-serif'

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {INK};
    font-family: {FONT_UI};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}
QScrollArea {{
    border: none;
    background: {BG};
}}
QScrollBar:vertical {{
    background: {BG};
    width: 10px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: {SHADOW};
    border-radius: 5px;
    min-height: 40px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    selection-background-color: {ACCENT_SOFT};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox {{
    padding: 6px 12px;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 16px;
    color: {INK};
}}
QPushButton:hover {{
    border-color: #C8D0DC;
    background: #FDFDFE;
}}
QPushButton:pressed {{
    background: #EEF1F5;
}}
QPushButton#accent {{
    background: {ACCENT};
    color: white;
    border: none;
    font-weight: 600;
}}
QPushButton#accent:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#accent:pressed {{
    background: #2756C4;
}}
QPushButton#ghost {{
    background: transparent;
    border: 1px solid transparent;
    color: {MUTED};
}}
QPushButton#ghost:hover {{
    background: {ACCENT_SOFT};
    color: {INK};
    border-color: {BORDER};
}}
QPushButton#nav {{
    background: transparent;
    border: none;
    border-radius: 10px;
    text-align: left;
    padding: 10px 14px;
    color: {MUTED};
}}
QPushButton#nav:hover {{
    background: {ACCENT_SOFT};
    color: {INK};
}}
QPushButton#navActive {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    text-align: left;
    padding: 10px 14px;
    color: {INK};
    font-weight: 600;
}}
QCheckBox {{
    spacing: 8px;
}}
QLabel#caption {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#title {{
    font-size: 20px;
    font-weight: 600;
}}
QFrame#summaryCard {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#dateCapsule {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
"""

__all__ = [
    'STYLESHEET',
    'NAV_ITEMS',
    'ACCENT',
    'BG',
    'SURFACE',
    'INK',
    'MUTED',
    'FAINT',
    'GAP_FILL',
    'GAP_BORDER',
    'PENDING_BG',
    'PENDING_BORDER',
    'PENDING_INK',
    'SHADOW',
    'BORDER',
]
