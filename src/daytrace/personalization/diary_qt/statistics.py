"""Local daily statistics, source intervals only; no inferred gap duration."""
from collections import defaultdict
from datetime import datetime
from math import sin, cos, pi, atan2, hypot
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QButtonGroup, QToolTip
from ..category_palette import category_color
from ..diary_model import duration


def summarize(cards):
    rows = {}
    for card in cards:
        for row in card['rows']:
            if row['state'] == 'active':
                rows[row['interval_id']] = row
    totals = defaultdict(int)
    for row in rows.values():
        totals[row.get('category') or '待确认'] += max(0, row['end_ms']-row['start_ms'])
    return list(rows.values()), sorted(((k,v) for k,v in totals.items() if v>0), key=lambda item: -item[1])


class Statistics(QWidget):
    def __init__(self):
        super().__init__()
        self.rows, self.totals, self.colors = [], [], {}
        self.half = 0
        self.hover = -1
        self.offset = 0.
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(140)
        self.animation.valueChanged.connect(self._animate)
        self.setMouseTracking(True)
        self.setMinimumSize(760, 700)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        top = QHBoxLayout()
        left = QHBoxLayout()
        left.addStretch()
        self.buttons = []
        group = QButtonGroup(self)
        for index, label in enumerate(('上午', '下午')):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setFixedSize(110, 38)
            button.setStyleSheet('QPushButton {border:1px solid #EDEEF2;border-radius:10px;background:#F8F9FB;color:#1D1D1F;font-size:16px;} QPushButton:checked {background:#2563EB;color:white;border:0;}')
            group.addButton(button)
            button.clicked.connect(lambda checked=False, n=index: self.set_half(n))
            left.addWidget(button)
            self.buttons.append(button)
        self.buttons[0].setChecked(True)
        left.addStretch()
        top.addLayout(left, 1)
        top.addStretch(1)
        layout.addLayout(top)
        layout.addStretch()

    def _animate(self, value):
        self.offset = float(value)
        self.update()

    def set_half(self, half):
        self.half = half
        self.buttons[half].setChecked(True)
        self.update()

    def geometry_values(self):
        # Reserve space outside the clock for hour labels in both columns.
        radius = min(150., (self.width()/2-130)/2)
        return self.width()*.25, self.width()*.75, 110+radius, radius

    def set_cards(self, cards, colors):
        rows, totals = summarize(cards)
        if rows == self.rows and totals == self.totals and colors == self.colors:
            return
        hovered = self.totals[self.hover][0] if 0 <= self.hover < len(self.totals) else None
        self.rows, self.totals = rows, totals
        self.colors = dict(colors)
        self.hover = next((i for i,(name,_) in enumerate(totals) if name == hovered), -1)
        if self.hover < 0:
            self.animation.stop()
            self.offset = 0
            QToolTip.hideText()
        self.setMinimumHeight(max(700, 570+len(self.totals)*62))
        self.update()

    def hit_sector(self, point):
        _, cx, cy, radius = self.geometry_values()
        dx,dy = point.x()-cx,point.y()-cy
        if not radius-50 <= hypot(dx,dy) <= radius+16:
            return -1
        total=sum(v for _,v in self.totals)
        angle=(atan2(dx,-dy)*180/pi)%360
        end=0
        for i,(_,value) in enumerate(self.totals):
            end+=360*value/total if total else 0
            if angle<end:
                return i
        return -1

    def mouseMoveEvent(self, event):
        index=self.hit_sector(event.position())
        if index!=self.hover:
            self.hover=index
            self.animation.stop()
            self.animation.setStartValue(0.)
            self.animation.setEndValue(7. if index>=0 else 0.)
            self.animation.start()
        if index>=0:
            category,value=self.totals[index]
            QToolTip.showText(event.globalPosition().toPoint(), f'{category}\n{duration(value)} · {value/sum(v for _,v in self.totals):.1%}',self)
        else:
            QToolTip.hideText()
        self.update()

    def leaveEvent(self,event):
        self.hover=-1
        self.animation.stop()
        self.offset=0
        QToolTip.hideText()
        self.update()

    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#FFFFFF'))
        w=self.width()
        lx,rx,cy,r=self.geometry_values()
        def text(rect,value,size=14,color='#1D1D1F',align=Qt.AlignmentFlag.AlignLeft,bold=False):
            font=QFont('Microsoft YaHei UI');font.setPixelSize(size);font.setBold(bold)
            p.setFont(font);p.setPen(QColor(color));p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawText(rect,align|Qt.AlignmentFlag.AlignVCenter,p.fontMetrics().elidedText(value,Qt.TextElideMode.ElideRight,int(rect.width())))
        def color(category):
            return QColor('#A1A1AA' if category=='待确认' else category_color(category,self.colors))
        p.setPen(QPen(QColor('#EDEEF2'),1))
        p.drawLine(QPointF(w/2,12),QPointF(w/2,cy+r+25))
        text(QRectF(w/2+32,12,w/2-60,38),'全天统计',18,'#86868B')
        clock=QRectF(lx-r+6,cy-r+6,2*r-12,2*r-12)
        p.setPen(QPen(QColor('#E5E7EB'),2));p.drawEllipse(clock)
        for row in self.rows:
            a=datetime.fromtimestamp(row['start_ms']/1000);b=datetime.fromtimestamp(row['end_ms']/1000)
            start=a.hour*60+a.minute+a.second/60
            end=1440 if b.date()>a.date() else b.hour*60+b.minute+b.second/60
            lo=max(self.half*720,start);hi=min((self.half+1)*720,end)
            if hi>lo:
                p.setPen(Qt.PenStyle.NoPen)
                shade=color(row.get('category') or '待确认')
                shade.setAlpha(150)
                p.setBrush(shade)
                p.drawPie(clock,round((90-(lo%720)/2)*16),round(-(hi-lo)/2*16))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for tick in range(60):
            angle=tick*pi/30
            outer=r-16;inner=outer-(9 if tick%5==0 else 4)
            p.setPen(QPen(QColor('#86868B'),1))
            p.drawLine(QPointF(lx+sin(angle)*inner,cy-cos(angle)*inner),QPointF(lx+sin(angle)*outer,cy-cos(angle)*outer))
        for hour in range(12):
            a=hour*pi/6
            x=lx+sin(a)*(r+23);y=cy-cos(a)*(r+23)
            text(QRectF(x-18,y-14,36,28),str(hour or 12),20,align=Qt.AlignmentFlag.AlignCenter)
        text(QRectF(lx-r,cy+r+42,r*2,30),'00:00–12:00' if self.half==0 else '12:00–24:00',12,'#86868B',Qt.AlignmentFlag.AlignCenter)
        total=sum(v for _,v in self.totals)
        donut=QRectF(rx-r+21,cy-r+21,2*r-42,2*r-42)
        p.setPen(QPen(QColor('#F0F1F4'),42));p.drawEllipse(donut)
        angle=90.
        for i,(category,value) in enumerate(self.totals):
            span=360*value/total if total else 0
            rect=QRectF(donut)
            shade=color(category)
            if i==self.hover:
                middle=(angle-span/2)*pi/180
                rect.translate(cos(middle)*self.offset,-sin(middle)*self.offset)
                shade=shade.lighter(110)
            pen=QPen(shade,42);pen.setCapStyle(Qt.PenCapStyle.FlatCap);p.setPen(pen);p.drawArc(rect,round(angle*16),-round(span*16));angle-=span
        text(QRectF(rx-r+46,cy-25,2*r-92,50),duration(total),24,align=Qt.AlignmentFlag.AlignCenter,bold=True)
        y=cy+r+85
        p.setPen(QPen(QColor('#EDEEF2'),1));p.drawLine(QPointF(12,y),QPointF(w-12,y))
        text(QRectF(16,y+16,150,36),'时间排行',22,bold=True)
        text(QRectF(160,y+16,w-180,36),'全天 · 按记录时长从高到低排序',13,'#86868B')
        if not total:
            text(QRectF(16,y+75,w-32,40),'当天暂无有效活动',14,'#86868B')
        for i,(category,value) in enumerate(self.totals):
            top=y+76+i*62
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(color(category));p.drawRoundedRect(QRectF(20,top+8,16,16),5,5)
            text(QRectF(50,top,190,34),category,15)
            bx=250;bw=max(80,w-510)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#F0F1F4'));p.drawRoundedRect(QRectF(bx,top+13,bw,9),4,4)
            p.setBrush(color(category));p.drawRoundedRect(QRectF(bx,top+13,bw*value/total,9),4,4)
            text(QRectF(w-240,top,160,34),duration(value),16,align=Qt.AlignmentFlag.AlignRight,bold=True)
            text(QRectF(w-75,top,65,34),f'{value/total:.1%}',14,'#86868B',Qt.AlignmentFlag.AlignRight)
        p.end()
