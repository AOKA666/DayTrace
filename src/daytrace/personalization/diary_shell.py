"""Diary chrome: canvas sidebar and settings section switcher."""
import tkinter as tk

from .diary_theme import (
    ACCENT,
    ACCENT_SOFT,
    BG,
    BORDER,
    FAINT,
    FONT_BRAND,
    FONT_CAPTION,
    FONT_NAV,
    INK,
    INK_SOFT,
    MUTED,
    NAV_ITEMS,
    SIDEBAR,
    SIDEBAR_LINE,
    SURFACE,
)


class DiarySidebar(tk.Canvas):
    width = 168
    item_h = 44

    def __init__(self, master, on_navigate):
        super().__init__(
            master,
            width=self.width,
            bg=SIDEBAR,
            highlightthickness=0,
            bd=0,
        )
        self.on_navigate = on_navigate
        self.active = '今日'
        self._regions = []
        self.bind('<Configure>', lambda _: self._paint())
        self.bind('<Button-1>', self._click)
        self.bind('<Motion>', self._motion)
        self.bind('<Leave>', lambda _: self._paint(hover=None))

    def set_active(self, name):
        self.active = name
        self._paint()

    def _paint(self, hover=None):
        w = self.width
        h = max(400, self.winfo_height())
        self.delete('all')
        self.create_line(w - 1, 0, w - 1, h, fill=SIDEBAR_LINE, tags=('chrome',))
        self.create_text(22, 28, text='DayTrace', anchor='nw', font=FONT_BRAND, fill=INK, tags=('chrome',))
        self.create_text(22, 52, text='时间日记', anchor='nw', font=FONT_CAPTION, fill=MUTED, tags=('chrome',))
        self._regions = []
        y = 88
        for name, symbol in NAV_ITEMS:
            selected = name == self.active
            hot = hover == name and not selected
            if selected:
                self.create_rectangle(10, y, w - 14, y + self.item_h, fill=SURFACE, outline=BORDER, tags=('chrome',))
                self.create_rectangle(10, y + 10, 12, y + self.item_h - 10, fill=ACCENT, outline='', tags=('chrome',))
                fg = INK
            elif hot:
                self.create_rectangle(10, y, w - 14, y + self.item_h, fill=ACCENT_SOFT, outline='', tags=('chrome',))
                fg = INK_SOFT
            else:
                fg = MUTED
            self.create_text(24, y + self.item_h // 2, text=symbol, anchor='w', font=FONT_NAV, fill=fg, tags=('chrome',))
            self.create_text(46, y + self.item_h // 2, text=name, anchor='w', font=FONT_NAV, fill=fg, tags=('chrome',))
            self._regions.append((name, 10, y, w - 14, y + self.item_h))
            y += self.item_h + 4
        self.create_text(
            22,
            h - 48,
            text='本地保存\n随时纠正',
            anchor='nw',
            font=FONT_CAPTION,
            fill=FAINT,
            tags=('chrome',),
        )

    def _row_at(self, event):
        for name, x1, y1, x2, y2 in self._regions:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                return name
        return None

    def _click(self, event):
        name = self._row_at(event)
        if name:
            self.on_navigate(name)

    def _motion(self, event):
        self._paint(hover=self._row_at(event))
        row = self._row_at(event)
        self.configure(cursor='hand2' if row else '')


def settings_scroll_page(parent):
    """Scrollable settings section body."""
    outer = tk.Frame(parent, bg=BG)
    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
    scroll = tk.Scrollbar(outer, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    inner = tk.Frame(canvas, bg=BG, padx=28, pady=24)
    window = canvas.create_window((0, 0), window=inner, anchor='nw')
    inner.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))

    def wheel(event):
        canvas.yview_scroll(-int(event.delta / 120) * 3, 'units')
        return 'break'

    canvas.bind('<Enter>', lambda _: canvas.bind_all('<MouseWheel>', wheel, add='+'))
    canvas.bind('<Leave>', lambda _: canvas.unbind_all('<MouseWheel>'))
    return outer, inner
