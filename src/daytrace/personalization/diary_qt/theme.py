"""Single design system for the reference-driven Qt desktop interface.

All dimensions are Qt logical pixels; Windows scales them for the display DPI.
"""
BG = SURFACE = '#FFFFFF'
SIDEBAR = '#F8F9FB'
INK = '#1D1D1F'
MUTED = '#86868B'
FAINT = '#A1A1AA'
BORDER = '#EDEEF2'
ACCENT = '#2563EB'
ACCENT_HOVER = '#1D4ED8'
ACCENT_SOFT = '#EAF1FF'
PENDING_BG = '#FFF4E9'
PENDING_INK = '#C76B20'
PENDING_BORDER = PENDING_BG
GAP_FILL = '#FAFAFC'
GAP_BORDER = BORDER
SHADOW = '#08000000'
SIDEBAR_WIDTH = 230
PAGE_MARGIN = 32
CARD_RADIUS = 16
CARD_HEIGHT = 112
CARD_GAP = 12
NAV_ITEMS = (('时间线', 'clock'), ('我的', 'sparkles'), ('设置', 'settings'))
FONT_UI = '"Segoe UI", "Microsoft YaHei UI"'


def pill_colors(color):
    """Use the user's category hue as a quiet tint, not a solid card color."""
    from PySide6.QtGui import QColor
    base = QColor(color)
    if not base.isValid():
        base = QColor('#7566D9')
    light = QColor(*[round(c * .13 + 255 * .87) for c in (base.red(), base.green(), base.blue())])
    return light.name(), base.darker(140).name()


def pill_style(color):
    background, foreground = pill_colors(color)
    return f'background:{background}; color:{foreground}; border:none; border-radius:12px; padding:3px 12px; font-size:13px; font-weight:600;'


STYLESHEET = f'''
QWidget {{ color:{INK}; font-family:{FONT_UI}; font-size:14px; background:transparent; }}
QMainWindow, QDialog, QWidget#mainSurface {{ background:{BG}; }}
QDialog {{ padding:12px; }}
QFrame#sidebar {{ background:{SIDEBAR}; border-right:1px solid {BORDER}; }}
QLabel#brand {{ font-size:21px; font-weight:600; }}
QLabel#brandLogo {{ background:{ACCENT}; border-radius:12px; }}
QLabel#brandSubtitle {{ color:{MUTED}; font-size:14px; }}
QLabel#title {{ font-size:28px; font-weight:600; }}
QLabel#sectionTitle, QLabel#summaryTitle {{ font-size:18px; font-weight:600; }}
QLabel#caption, QLabel#fieldLabel {{ color:{MUTED}; font-size:13px; }}
QLabel#fieldLabel {{ padding-top:6px; }}
QScrollArea {{ border:none; background:{BG}; }}
QScrollBar:vertical {{ background:transparent; width:10px; margin:4px 0; }}
QScrollBar::handle:vertical {{ background:#DADCE2; border-radius:4px; min-height:44px; margin:1px; }}
QScrollBar::handle:vertical:hover {{ background:#B9BDC6; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; border:none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:none; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QListWidget, QTreeWidget, QTableWidget {{
 background:{SURFACE}; border:1px solid {BORDER}; border-radius:11px; padding:8px 12px;
 selection-background-color:{ACCENT_SOFT}; selection-color:{INK};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color:#A8C1FA; }}
QLineEdit:disabled {{ color:{MUTED}; background:{SIDEBAR}; }}
QComboBox::drop-down {{ border:none; width:26px; }}
QComboBox QAbstractItemView {{ background:{SURFACE}; border:1px solid {BORDER}; padding:6px; selection-background-color:{ACCENT_SOFT}; }}
QHeaderView::section {{ background:{SIDEBAR}; color:{MUTED}; border:none; border-bottom:1px solid {BORDER}; padding:10px; font-size:13px; }}
QTableWidget {{ gridline-color:{BORDER}; }}
QPushButton, QToolButton {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:11px; padding:8px 14px; }}
QPushButton:hover, QToolButton:hover {{ background:#F8FAFF; border-color:#D8E2F5; }}
QPushButton:pressed, QToolButton:pressed {{ background:{ACCENT_SOFT}; }}
QPushButton:disabled {{ color:{FAINT}; background:{SIDEBAR}; }}
QPushButton:focus, QToolButton:focus {{ border-color:#A8C1FA; }}
QPushButton#accent {{ background:{ACCENT}; color:white; border:1px solid {ACCENT}; padding:8px 20px; font-weight:500; }}
QPushButton#accent:hover {{ background:{ACCENT_HOVER}; }}
QPushButton#accent:disabled {{ background:#AEC4F4; border-color:#AEC4F4; }}
QPushButton#ghost {{ background:transparent; color:{MUTED}; border:1px solid transparent; }}
QPushButton#ghost:hover {{ background:{SIDEBAR}; color:{INK}; }}
QPushButton#nav, QPushButton#navActive {{ border:none; border-radius:11px; text-align:left; padding:12px 18px; font-size:16px; }}
QPushButton#nav {{ color:#34343B; background:transparent; }}
QPushButton#nav:hover {{ background:#F0F2F7; }}
QPushButton#navActive {{ background:{ACCENT_SOFT}; color:{ACCENT}; font-weight:600; }}
QPushButton#sectionTab, QPushButton#sectionTabActive {{ border:none; padding:9px 14px; border-radius:9px; }}
QPushButton#sectionTab {{ color:{MUTED}; background:transparent; }}
QPushButton#sectionTabActive {{ color:{ACCENT}; background:{ACCENT_SOFT}; }}
QFrame#settingsPanel, QFrame#summaryCard {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:16px; }}
QFrame#dateCapsule {{ background:transparent; border:none; }}
QLineEdit#dateField {{ font-weight:500; padding-left:4px; }}
QLineEdit#searchField {{ padding-left:4px; }}
QLabel#captureBadge {{ border:none; border-radius:12px; padding:6px 16px; font-size:14px; font-weight:600; color:{MUTED}; background:{SIDEBAR}; }}
QLabel#captureBadge[recordingState="running"] {{ background:#E5F5EC; color:#15803D; }}
QLabel#captureBadge[recordingState="paused"] {{ background:{PENDING_BG}; color:{PENDING_INK}; }}
QFrame#activityCard {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:16px; }}
QFrame#activityCard:hover {{ border-color:#D5DEEF; }}
QFrame#activityCard[gap="true"] {{ background:{GAP_FILL}; }}
QLabel#activityTitle {{ font-size:16px; font-weight:600; }}
QLabel#activityDuration {{ font-size:14px; font-weight:400; }}
QLabel#activityDescription {{ font-size:13px; color:{MUTED}; }}
QLabel#activityFooter {{ font-size:12px; color:{FAINT}; }}
QLabel#timeStart {{ font-size:15px; font-weight:600; }}
QLabel#timeEnd {{ font-size:13px; color:{MUTED}; }}
QPushButton#pendingChip {{ border:none; border-radius:12px; background:{PENDING_BG}; color:{PENDING_INK}; padding:4px 12px; font-size:13px; }}
QLabel#confirmedState {{ color:{MUTED}; font-size:13px; padding:4px 0; }}
QPushButton#learningAction {{ text-align:left; padding:11px 16px; }}
QCheckBox {{ spacing:9px; }}
QCheckBox::indicator {{ width:18px; height:18px; border:1px solid #D2D5DD; border-radius:5px; background:white; }}
QCheckBox::indicator:checked {{ background:{ACCENT}; border:3px solid #D9E5FF; }}
QCheckBox::indicator:hover {{ border-color:{ACCENT}; }}
QTreeWidget#categoryList, QListWidget#tagCloud {{ background:transparent; border:none; padding:0; }}
QTreeWidget#categoryList::item {{ min-height:32px; padding:4px 6px; border-radius:7px; }}
QListWidget#tagCloud::item {{ border-radius:10px; padding:4px 8px; }}
QTreeWidget#categoryList::item:selected, QListWidget#tagCloud::item:selected {{ background:{ACCENT_SOFT}; color:{INK}; }}
QTabWidget::pane {{ border:none; background:white; }}
QTabBar::tab {{ background:transparent; color:{MUTED}; padding:10px 16px; margin-right:8px; border-radius:10px; }}
QTabBar::tab:selected {{ background:{ACCENT_SOFT}; color:{ACCENT}; }}
QToolTip {{ background:{SURFACE}; color:{INK}; border:1px solid {BORDER}; padding:8px; }}
'''
