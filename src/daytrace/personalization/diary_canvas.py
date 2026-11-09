"""Virtualized timeline: only viewport cards have canvas objects."""
import tkinter as tk
from datetime import datetime
from .diary_model import duration
from .timeline_view import category_color

BG = '#F7F8FA'
INK = '#202C40'
MUTED = '#8190A3'
BLUE = '#426BD9'


class DiaryCanvas(tk.Canvas):
    pitch = 184

    def __init__(self, master, select, hover=None, confirm=None, **kw):
        super().__init__(master, bg=BG, highlightthickness=0, **kw)
        self.select_callback, self.hover_callback, self.confirm_callback = select, hover, confirm
        self.cards, self.colors, self.objects = [], {}, {}
        self.fingerprint = None
        self.hover_index = None
        self.bind('<Configure>', lambda _: self.render())
        self.bind('<MouseWheel>', self.wheel)
        self.bind('<Button-1>', self.click)
        self.bind('<Motion>', self.motion)
        self.bind('<Leave>', self.leave)
        self.hover_row = ''

    def set_cards(self, cards, colors):
        key = (tuple(sorted(colors.items())),tuple((c['start_ms'],c['end_ms'],c['title'],c['description'],c['category'],c['project'],c['status'],c['review'],len(c['rows'])) for c in cards))
        if key == self.fingerprint:
            return
        self.fingerprint = key
        self.cards, self.colors = cards, colors
        self.configure(scrollregion=(0, 0, 1, max(1, len(cards)*self.pitch+36)))
        self.render()

    def yview(self, *args):
        result = super().yview(*args)
        if args: self.render()
        return result

    def wheel(self, event):
        self.yview_scroll(-int(event.delta/120)*3, 'units')
        self.render()
        return 'break'

    def index_at(self, event):
        index = int((self.canvasy(event.y)-12)//self.pitch)
        return index if 0 <= index < len(self.cards) else None

    def identify_row(self, y):
        return self.hover_row

    def motion(self, event):
        index = self.index_at(event)
        if index != self.hover_index:
            self.hover_index = index
            self.render()
        self.hover_row = self.cards[index]['rows'][0]['interval_id'] if index is not None else ''
        on_chip = False
        if index is not None:
            card = self.cards[index]
            y = 16 + index * self.pitch
            right = max(500, self.winfo_width()) - 24
            on_chip = card['review'] and right - 190 <= event.x <= right and y + 112 <= event.y <= y + 156
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
        y = 16 + index * self.pitch
        right = max(500, self.winfo_width()) - 24
        if card['review'] and self.confirm_callback and right - 190 <= event.x <= right and y + 112 <= event.y <= y + 156:
            self.confirm_callback(card)
            return
        self.select_callback(card)

    def render(self):
        width = max(500, self.winfo_width())
        top = self.canvasy(0)
        first = max(0, int(top//self.pitch)-1)
        last = min(len(self.cards), int((top+self.winfo_height())//self.pitch)+2)
        wanted = set()
        def item(tag, kind, coords, **config):
            wanted.add(tag)
            found = self.find_withtag(tag)
            if found:
                identifier = found[0]
                if self.coords(identifier) != list(coords): self.coords(identifier, *coords)
                self.itemconfigure(identifier, **config)
            else:
                getattr(self, 'create_'+kind)(*coords, tags=(tag,), **config)
        for index in range(first, last):
            card = self.cards[index]
            y = 16 + index*self.pitch
            prefix = f'card-{index}'
            x, right, bottom, r = 135, width-24, y+160, 12
            active = card['rows'][0]['state'] == 'active'
            fill = 'white' if active else '#F1F4F8'
            outline = '#4A72DD' if index == self.hover_index and active else '#DCE2EA' if not active else '#D6DEEB' if index == self.hover_index else '#E9EDF3'
            width_line = 2 if index == self.hover_index else 1
            points = (x+r,y,right-r,y,right,y,right,y+r,right,bottom-r,right,bottom,right-r,bottom,x+r,bottom,x,bottom,x,bottom-r,x,y+r,x,y)
            shadow = (x+r+2,y+3,right-r+2,y+3,right+2,y+3,right+2,y+r+3,right+2,bottom-r+3,right+2,bottom+3,right-r+2,bottom+3,x+r+2,bottom+3,x+2,bottom+3,x+2,bottom-r+3,x+2,y+r+3,x+2,y+3)
            item(prefix+'shadow', 'polygon', shadow, smooth=True, splinesteps=16, fill='#E4E9F0', outline='')
            item(prefix, 'polygon', points, smooth=True, splinesteps=16, fill=fill, outline=outline, width=width_line)
            item(prefix+'line','line',(112,y+8,112,y+self.pitch+8),fill='#E3E8EF',width=2)
            item(prefix+'dot','oval',(108,y+5,116,y+13),fill=BLUE if card['category'] else '#B9C3CF',outline=BG,width=2)
            start = datetime.fromtimestamp(card['start_ms']/1000)
            end = datetime.fromtimestamp(card['end_ms']/1000)
            item(prefix+'time','text',(91,y+9),text=start.strftime('%H:%M'),anchor='e',font=('Segoe UI',13,'bold'),fill=INK)
            item(prefix+'end','text',(91,y+35),text=end.strftime('%H:%M'),anchor='e',font=('Segoe UI',10),fill=MUTED)
            title_fill = INK if active else '#6B7A8F'
            item(prefix+'title','text',(x+22,y+27),text=card['title'][:42],anchor='w',font=('Microsoft YaHei UI',13,'bold'),fill=title_fill,width=max(200,right-x-190))
            item(prefix+'duration','text',(right-20,y+27),text=duration(card['end_ms']-card['start_ms']),anchor='e',font=('Microsoft YaHei UI',10),fill=MUTED)
            item(prefix+'description','text',(x+22,y+67),text=card['description'][:94],anchor='nw',font=('Microsoft YaHei UI',10),fill='#738196',width=right-x-44)
            category = card['category']
            if category:
                color = category_color(category,self.colors)
                w = min(200,20+len(category)*13)
                item(prefix+'badge','rectangle',(x+22,y+121,x+22+w,y+145),fill='#EFF3FA',outline='')
                item(prefix+'category','text',(x+32,y+133),text=category[:14],anchor='w',font=('Microsoft YaHei UI',9),fill=color)
                item(prefix+'project','text',(x+36+w,y+133),text=card['project'][:28],anchor='w',font=('Microsoft YaHei UI',9),fill=MUTED)
            if card['review']:
                chip_w = min(128, 28 + len(card['status']) * 11)
                item(prefix+'chip','rectangle',(right-20-chip_w,y+118,right-14,y+148),fill='#FFF4E8',outline='#F0D8B8')
                item(prefix+'status','text',(right-17,y+133),text=card['status'],anchor='e',font=('Microsoft YaHei UI',9),fill='#A66B2C')
            else:
                item(prefix+'status','text',(right-20,y+133),text=card['status'],anchor='e',font=('Microsoft YaHei UI',9),fill=MUTED)
        if not self.cards:
            item('empty','text',(width/2,140),text='留一点空间，给今天的故事\n\n还没有符合条件的活动记录',font=('Microsoft YaHei UI',14),fill=MUTED,justify='center')
        for identifier in self.find_all():
            if self.gettags(identifier)[0] not in wanted: self.delete(identifier)
