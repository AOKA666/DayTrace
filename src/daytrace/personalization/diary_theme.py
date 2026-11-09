"""Visual tokens for the diary shell — light, restrained, readable."""

# Surfaces
BG = '#F6F7F9'
SURFACE = '#FFFFFF'
SIDEBAR = '#FAFBFC'
SIDEBAR_LINE = '#ECEEF2'

# Text
INK = '#181C27'
INK_SOFT = '#2E3544'
MUTED = '#8C95A6'
FAINT = '#B4BBC8'

# Accent & chrome
ACCENT = '#3B6FE8'
ACCENT_HOVER = '#2F5FD4'
ACCENT_SOFT = '#EAF0FC'
ACCENT_MUTED = '#6B8FD9'

BORDER = '#E6E9EF'
BORDER_STRONG = '#D5DAE4'
SHADOW = '#DDE1E9'

# Cards
GAP_FILL = '#F2F4F7'
GAP_BORDER = '#E4E8EE'
PENDING_BG = '#FBF4EC'
PENDING_BORDER = '#EBDDD0'
PENDING_INK = '#9A6A42'

# Typography (family, size, weight)
FONT_BRAND = ('Segoe UI', 15, 'bold')
FONT_NAV = ('Microsoft YaHei UI', 10)
FONT_PAGE_TITLE = ('Microsoft YaHei UI', 20, 'bold')
FONT_SECTION = ('Microsoft YaHei UI', 15, 'bold')
FONT_BODY = ('Microsoft YaHei UI', 10)
FONT_BODY_STRONG = ('Microsoft YaHei UI', 10, 'bold')
FONT_CAPTION = ('Microsoft YaHei UI', 9)
FONT_TIME = ('Segoe UI', 12, 'bold')
FONT_TIME_END = ('Segoe UI', 10)
FONT_CARD_TITLE = ('Microsoft YaHei UI', 12, 'bold')
FONT_CARD_META = ('Microsoft YaHei UI', 9)

# Legacy aliases used by canvas imports
BLUE = ACCENT

NAV_ITEMS = (
    ('今日', '◷'),
    ('历史记录', '▤'),
    ('AI 复盘', '◇'),
    ('设置', '⚙'),
)


def apply_ttk_style(style, root_bg=BG):
    style.theme_use('clam')
    style.configure('.', background=root_bg, foreground=INK_SOFT, font=FONT_BODY)
    style.configure('TFrame', background=root_bg)
    style.configure('TLabel', background=root_bg, foreground=INK_SOFT, font=FONT_BODY)
    style.configure('Card.TFrame', background=SURFACE)
    style.configure('TEntry', fieldbackground=SURFACE, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure('TButton', padding=(12, 7), borderwidth=0, background=SURFACE, foreground=INK_SOFT)
    style.map('TButton', background=[('active', BG), ('pressed', BORDER)])
    style.configure('Ghost.TButton', padding=(10, 6), background=root_bg, foreground=MUTED)
    style.map('Ghost.TButton', foreground=[('active', INK_SOFT)])
    style.configure('Accent.TButton', background=ACCENT, foreground='white', padding=(16, 9), borderwidth=0)
    style.map('Accent.TButton', background=[('active', ACCENT_HOVER), ('disabled', FAINT)])
    style.configure('Diary.TNotebook', borderwidth=0, background=root_bg)
    style.layout('Diary.TNotebook.Tab', [])
    style.configure('Vertical.TScrollbar', background=root_bg, troughcolor=BG, borderwidth=0, arrowsize=0)
