"""Compact 24-hour canvas; colored fragments preserve exact source intervals."""
from datetime import datetime, timedelta
import hashlib
import tkinter as tk

PALETTE = ('#7566D9','#3C9B92','#DC9B4B','#5B8FCB','#CA7298','#849448','#A17DD0','#C87C60')


def category_color(name, colors):
    if not name:
        return '#BEC7D3'
    return colors.get(name) or PALETTE[int(hashlib.sha256(name.encode()).hexdigest()[:8],16)%len(PALETTE)]


class DayCanvas(tk.Canvas):
    def __init__(self, parent, on_select, **kwargs):
        super().__init__(parent,background='white',highlightthickness=0,**kwargs)
        self.on_select=on_select
        self.rows=[];self.colors={};self.day=None;self.fingerprint=None;self.hover_row=''
        self.bind('<Configure>',lambda _: self.render(force=True))
        self.bind('<Button-1>',self.select)
        self.items={}

    def identify_row(self, y):
        return self.hover_row

    def hit(self,event):
        self.hover_row=''
        for item in reversed(self.find_overlapping(event.x,event.y,event.x,event.y)):
            if item in self.items:
                self.hover_row=self.items[item];break
        return self.hover_row

    def select(self,event):
        identifier=self.hit(event)
        if identifier:
            self.on_select(identifier)

    def update_rows(self,rows,day,colors):
        key=(day,tuple(sorted(colors.items())),tuple((r['interval_id'],r['start_ms'],r['end_ms'],r.get('category'),r.get('label'),r['state'],r.get('title')) for r in rows))
        self.rows,self.day,self.colors=rows,day,colors
        if key!=self.fingerprint:
            self.fingerprint=key;self.render(force=True)

    def render(self,force=False):
        if not self.day:
            return
        # Retain each fragment's canvas objects; only changed coordinates/cells update.
        width=max(300,self.winfo_width());height=max(360,self.winfo_height())
        left,right=62,width-24
        lane=(height-46)/6
        wanted=set();self.items={}
        def item(tag,kind,coords,**config):
            wanted.add(tag)
            found=self.find_withtag(tag)
            if found:
                ident=found[0]
                if list(self.coords(ident))!=list(coords): self.coords(ident,*coords)
                for k,v in config.items():
                    if str(self.itemcget(ident,k))!=str(v): self.itemconfigure(ident,**{k:v})
            else:
                ident=getattr(self,'create_'+kind)(*coords,tags=(tag,),**config)
            return ident
        for index in range(6):
            start=self.day+timedelta(hours=index*4)
            end=self.day+timedelta(hours=(index+1)*4)
            a,b=int(start.timestamp()*1000),int(end.timestamp()*1000)
            y=30+index*lane
            item(f'label{index}','text',(18,y+20),text=f'{index*4:02d}',anchor='w',fill='#8B94A5',font=('Segoe UI',10))
            item(f'base{index}','rectangle',(left,y,right,y+38),fill='#F1F3F7',outline='')
            self.tag_lower(f'base{index}')
            for hour in range(5):
                x=left+(right-left)*hour/4
                item(f'tick{index}-{hour}','text',(x,y-11),text=f'{index*4+hour:02d}:00',fill='#A1A8B5',font=('Segoe UI',8))
            for row in self.rows:
                lo,hi=max(a,row['start_ms']),min(b,row['end_ms'])
                if hi<=lo: continue
                x1=left+(lo-a)/(b-a)*(right-left);x2=left+(hi-a)/(b-a)*(right-left)
                color=category_color(row.get('category'),self.colors) if row['state']=='active' else '#E2E6EC'
                tag=f"segment:{index}:{row['interval_id']}"
                ident=item(tag,'rectangle',(x1,y,max(x1+1,x2),y+38),fill=color,outline='white',width=1)
                self.items[ident]=row['interval_id'];self.tag_raise(tag)
                if x2-x1>75:
                    title=row.get('category') or row.get('label') or ('待分类' if row['state']=='active' else 'gap / 空闲')
                    ident=item(tag+':text','text',((x1+x2)/2,y+19),text=title[:max(3,int((x2-x1)/14))],fill='white' if row['state']=='active' else '#8792A3',font=('Microsoft YaHei UI',9))
                    self.items[ident]=row['interval_id'];self.tag_raise(tag+':text')
        if not self.rows:
            item('empty','text',(width/2,height/2),text='这一天还没有记录',fill='#8B94A5',font=('Microsoft YaHei UI',14))
        for ident in self.find_all():
            tags=self.gettags(ident)
            if tags and tags[0] not in wanted:self.delete(ident)
