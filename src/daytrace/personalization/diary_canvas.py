"""Virtualized vertical diary timeline."""
import tkinter as tk
from datetime import datetime

from .diary_model import duration
from .diary_theme import (
    ACCENT,
    ACCENT_MUTED,
    BG,
    BORDER,
    BORDER_STRONG,
    FAINT,
    FONT_CARD_META,
    FONT_CARD_TITLE,
    FONT_TIME,
    FONT_TIME_END,
    GAP_BORDER,
    GAP_FILL,
    INK,
    INK_SOFT,
    MUTED,
    PENDING_BG,
    PENDING_BORDER,
    PENDING_INK,
    SHADOW,
    SURFACE,
)
from .timeline_view import category_color

# Re-export for diary_ui compatibility
BLUE = ACCENT


class DiaryCanvas(tk.Canvas):
    pitch = 152
    rail = 96
    pad = 20

    def __init__(self, master, select, hover=None, confirm=None, **kw):
        super().__init__(master, bg=BG, highlightthickness=0, bd=0, **kw)
        self.select_callback, self.hover_callback, self.confirm_callback = select, hover, confirm
        self.cards, self.colors = [], {}
        self.fingerprint = None
        self.hover_index = None
        self.hover_row = ''
        self.bind('<Configure>', lambda _: self.render())
        self.bind('<MouseWheel>', self.wheel)
        self.bind('<Button-1>', self.click)
        self.bind('<Motion>', self.motion)
        self.bind('<Leave>', self.leave)

    def set_cards(self, cards, colors):
        key = (
            tuple(sorted(colors.items())),
            tuple(
                (
                    c['start_ms'],
                    c['end_ms'],
                    c['title'],
                    c['description'],
                    c['category'],
                    c['project'],
                    c['status'],
                    c['review'],
                    len(c['rows']),
                )
                for c in cards
            ),
        )
        if key == self.fingerprint:
            return
        self.fingerprint = key
        self.cards, self.colors = cards, colors
        self.configure(scrollregion=(0, 0, 1, max(48, len(cards) * self.pitch + 40)))
        self.render()

    def yview(self, *args):
        result = super().yview(*args)
        if args:
            self.render()
        return result

    def wheel(self, event):
        self.yview_scroll(-int(event.delta / 120) * 3, 'units')
        self.render()
        return 'break'

    def index_at(self, event):
        index = int((self.canvasy(event.y) - 8) // self.pitch)
        return index if 0 <= index < len(self.cards) else None

    def identify_row(self, y):
        return self.hover_row

    def _card_geom(self, index, width):
        y = 12 + index * self.pitch
        left = self.rail + 8
        right = width - self.pad
        bottom = y + self.pitch - 14
        return left, right, y, bottom

    def _chip_hit(self, event, index):
        card = self.cards[index]
        if not card['review']:
            return False
        width = max(520, self.winfo_width())
        left, right, y, bottom = self._card_geom(index, width)
        chip_w = min(120, 24 + len(card['status']) * 10)
        return right - chip_w - 8 <= event.x <= right and bottom - 28 <= event.y <= bottom - 4

    def motion(self, event):
        index = self.index_at(event)
        if index != self.hover_index:
            self.hover_index = index
            self.render()
        self.hover_row = self.cards[index]['rows'][0]['interval_id'] if index is not None else ''
        on_chip = index is not None and self._chip_hit(event, index)
        self.configure(cursor='hand2' if on_chip or self.hover_row else '')
        if self.hover_callback:
            self.hover_callback(self, event)

    def leave(self, _event=None):
        if self.hover_index is not None:
            self.hover_index = None
            self.render()
        self.hover_row = ''
        self.configure(cursor='')

    def click(self, event):
        index = self.index_at(event)
        if index is None:
            return
        card = self.cards[index]
        if card['review'] and self.confirm_callback and self._chip_hit(event, index):
            self.confirm_callback(card)
            return
        self.select_callback(card)

    def render(self):
        width = max(520, self.winfo_width())
        top = self.canvasy(0)
        first = max(0, int(top // self.pitch) - 1)
        last = min(len(self.cards), int((top + self.winfo_height()) // self.pitch) + 2)
        wanted = set()

        def item(tag, kind, coords, **config):
            wanted.add(tag)
            found = self.find_withtag(tag)
            if found:
                identifier = found[0]
                if self.coords(identifier) != list(coords):
                    self.coords(identifier, *coords)
                self.itemconfigure(identifier, **config)
            else:
                getattr(self, 'create_' + kind)(*coords, tags=(tag,), **config)

        rail_x = self.rail - 18
        if self.cards:
            item('rail', 'line', (rail_x, 8, rail_x, len(self.cards) * self.pitch + 20), fill=BORDER, width=1)

        for index in range(first, last):
            card = self.cards[index]
            left, right, y, bottom = self._card_geom(index, width)
            prefix = f'card-{index}'
            active = card['rows'][0]['state'] == 'active'
            hovered = index == self.hover_index

            fill = SURFACE if active else GAP_FILL
            outline = ACCENT_MUTED if hovered and active else GAP_BORDER if not active else BORDER_STRONG if hovered else BORDER

            r = 10
            points = (
                left + r,
                y,
                right - r,
                y,
                right,
                y,
                right,
                y + r,
                right,
                bottom - r,
                right,
                bottom,
                right - r,
                bottom,
                left + r,
                bottom,
                left,
                bottom,
                left,
                bottom - r,
                left,
                y + r,
                left,
                y,
            )
            item(prefix + 'shadow', 'line', (left + 1, bottom + 1, right + 1, bottom + 1), fill=SHADOW, width=2)
            item(prefix, 'polygon', points, smooth=True, splinesteps=12, fill=fill, outline=outline, width=1)

            dot = ACCENT if active and card['category'] else FAINT
            item(prefix + 'dot', 'oval', (rail_x - 4, y + 18, rail_x + 4, y + 26), fill=dot, outline=BG, width=2)

            start = datetime.fromtimestamp(card['start_ms'] / 1000)
            end = datetime.fromtimestamp(card['end_ms'] / 1000)
            item(
                prefix + 'time',
                'text',
                (rail_x - 10, y + 14),
                text=start.strftime('%H:%M'),
                anchor='e',
                font=FONT_TIME,
                fill=INK if active else MUTED,
            )
            item(
                prefix + 'end',
                'text',
                (rail_x - 10, y + 34),
                text=end.strftime('%H:%M'),
                anchor='e',
                font=FONT_TIME_END,
                fill=FAINT,
            )

            title_fill = INK if active else MUTED
            item(
                prefix + 'title',
                'text',
                (left + 18, y + 16),
                text=card['title'][:48],
                anchor='nw',
                font=FONT_CARD_TITLE,
                fill=title_fill,
                width=max(180, right - left - 120),
            )

            dur = duration(card['end_ms'] - card['start_ms'])
            item(
                prefix + 'duration',
                'text',
                (right - 16, y + 18),
                text=dur,
                anchor='e',
                font=FONT_CARD_META,
                fill=FAINT,
            )

            item(
                prefix + 'description',
                'text',
                (left + 18, y + 44),
                text=card['description'][:100],
                anchor='nw',
                font=FONT_CARD_META,
                fill=MUTED if active else FAINT,
                width=right - left - 36,
            )

            foot = bottom - 26
            category = card['category']
            cursor_x = left + 18
            if category:
                color = category_color(category, self.colors)
                pill_w = min(96, 14 + len(category) * 11)
                item(
                    prefix + 'pill',
                    'rectangle',
                    (cursor_x, foot, cursor_x + pill_w, foot + 20),
                    fill='#F4F6FA',
                    outline=BORDER,
                )
                item(
                    prefix + 'category',
                    'text',
                    (cursor_x + 8, foot + 10),
                    text=category[:12],
                    anchor='w',
                    font=FONT_CARD_META,
                    fill=color,
                )
                cursor_x += pill_w + 10
            if card['project']:
                item(
                    prefix + 'project',
                    'text',
                    (cursor_x, foot + 10),
                    text=card['project'][:24],
                    anchor='w',
                    font=FONT_CARD_META,
                    fill=FAINT,
                )

            if card['review']:
                chip_w = min(120, 24 + len(card['status']) * 10)
                item(
                    prefix + 'chip',
                    'rectangle',
                    (right - chip_w - 14, foot - 2, right - 14, foot + 22),
                    fill=PENDING_BG,
                    outline=PENDING_BORDER,
                )
                item(
                    prefix + 'status',
                    'text',
                    (right - 16, foot + 10),
                    text=card['status'],
                    anchor='e',
                    font=FONT_CARD_META,
                    fill=PENDING_INK,
                )
            elif card['status']:
                item(
                    prefix + 'status',
                    'text',
                    (right - 16, foot + 10),
                    text=card['status'],
                    anchor='e',
                    font=FONT_CARD_META,
                    fill=FAINT,
                )

        if not self.cards:
            item(
                'empty',
                'text',
                (width / 2, 120),
                text='今天还没有可展示的活动\n稍后再来，或切换日期查看历史',
                font=('Microsoft YaHei UI', 12),
                fill=MUTED,
                justify='center',
            )

        for identifier in self.find_all():
            tags = self.gettags(identifier)
            if tags and tags[0] not in wanted:
                self.delete(identifier)
