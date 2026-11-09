"""Diary shell over the existing review, evidence and learning workflows."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox
import time

from .ui import App
from .diary_canvas import DiaryCanvas, BG, INK, MUTED, BLUE
import sys
from .diary_model import cards, overview, duration, DEFAULT_CATEGORIES
from .store import Memory
from .classifier import Classifier
from .provider import DEEPSEEK_ENDPOINT, DEEPSEEK_MODEL, TextProvider
from ..preferences import options, save_options


def window_scaling(root):
    try:
        scale = max(1.0, min(2.0, root.winfo_fpixels('1i') / 96.0))
        root.tk.call('tk', 'scaling', scale)
    except tk.TclError:
        pass


def scrolling_section(book,label):
    page=ttk.Frame(book)
    book.add(page,text=label)
    canvas=tk.Canvas(page,bg=BG,highlightthickness=0)
    scrollbar=ttk.Scrollbar(page,orient='vertical',command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
    inner=ttk.Frame(canvas,padding=24)
    window=canvas.create_window((0,0),window=inner,anchor='nw')
    inner.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
    def wheel(event):
        if str(event.widget).startswith(str(page)):
            canvas.yview_scroll(-int(event.delta/120)*3,'units')
            return 'break'
    canvas.bind_all('<MouseWheel>',wheel,add='+')
    return inner


class DiaryApp(App):
    def __init__(self, root, database):
        self.page = '今日'
        self.only_review = False
        self.all_cards = []
        self.recording = 'stopped'
        self.ai_future = None
        self.next_ai = 0
        self.ai_cancel = None
        self.review_cache = None
        self.collector_process = None
        super().__init__(root, database)
        root.title('DayTrace · AI 时间日记')
        root.geometry('1280x800')
        root.minsize(1040, 700)
        root.configure(bg=BG)
        window_scaling(root)
        style = ttk.Style(root)
        style.configure('.', background=BG, foreground=INK)
        style.configure('Accent.TButton', background=BLUE, foreground='white', padding=(16,8))
        style.map('Accent.TButton', background=[('active','#365BBE')])
        style.layout('Diary.TNotebook.Tab', [])
        style.configure('Diary.TNotebook', borderwidth=0, background=BG)
        self.tabs.configure(style='Diary.TNotebook')
        # Keep existing dialogs and backing tables, replace only the visible shell.
        for child in root.winfo_children():
            if child != self.tabs: child.pack_forget()
        self.tabs.pack_forget()
        sidebar = tk.Frame(root, bg='#EDF1F7', width=190)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        tk.Label(sidebar,text='DayTrace',bg='#EDF1F7',fg=INK,font=('Segoe UI',21,'bold')).pack(anchor='w',padx=24,pady=(32,0))
        tk.Label(sidebar,text='让每一天，有迹可循',bg='#EDF1F7',fg=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w',padx=24,pady=(6,34))
        self.nav = {}
        for title, symbol in [('今日','◷'),('历史记录','▤'),('AI 复盘','◇'),('设置','⚙')]:
            button=tk.Button(sidebar,text=f'{symbol}   {title}',anchor='w',bd=0,relief='flat',font=('Microsoft YaHei UI',11),padx=18,pady=12,bg='#EDF1F7',fg='#637188',activebackground='#E1E9F8',command=lambda name=title:self.navigate(name))
            button.pack(fill='x',padx=12,pady=3)
            self.nav[title]=button
        tk.Label(sidebar,text='你的时间，由你定义\n本地保存 · 随时纠正',justify='left',bg='#EDF1F7',fg=MUTED,font=('Microsoft YaHei UI',9)).pack(side='bottom',anchor='w',padx=24,pady=26)
        self.tabs.pack(side='left',fill='both',expand=True,padx=24,pady=20)
        self.tabs.select(self.timeline_tab)
        # The inherited footer belongs in the privacy section, not on the page.
        for child in self.profile_tab.winfo_children():
            if child is not self.settings_book: child.pack_forget()
        controls=ttk.Frame(self.privacy_section,padding=16);controls.pack(fill='x')
        ttk.Label(controls,text='短暂停留阈值（秒）').pack(anchor='w')
        self.dwell=ttk.Entry(controls,width=10);self.dwell.insert(0,'5');self.dwell.pack(anchor='w',pady=8)
        ttk.Button(controls,text='保存阈值',command=self.save_capture_preferences).pack(anchor='w')
        ttk.Checkbutton(controls,text='开启本地截图证据',variable=self.capture_enabled,command=self.save_screenshots).pack(anchor='w',pady=(24,8))
        ttk.Label(controls,text='仅前台窗口，排除规则优先。保存在数据库旁的截图目录，最多 7 天，不上传。\n截图开启后下次启动采集生效；关闭会撤销在途截图。\n短暂停留只保留匿名时间。默认不采集、不截图、不发送云端。',wraplength=650,foreground=MUTED).pack(anchor='w')
        self.ai_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='daytrace-diary-ai')
        root.after(1500,self.background)
        self.navigate('今日', refresh=False)

    def build_profile(self):
        self.settings_book=ttk.Notebook(self.profile_tab)
        self.settings_book.pack(fill='both',expand=True)
        sections=[]
        for label in ['我的日常','当前项目','识别与学习','采集与隐私','模型与高级']:
            sections.append(scrolling_section(self.settings_book,label))
        daily,projects,learning,self.privacy_section,advanced=sections
        ttk.Label(daily,text='让 DayTrace 更了解你',font=('Microsoft YaHei UI',20,'bold')).pack(anchor='w',pady=(0,10))
        ttk.Label(daily,text='用几句话介绍日常工作与兴趣，帮助识别活动的上下文。',foreground=MUTED).pack(anchor='w',pady=(0,16))
        self.description=tk.Text(daily,height=5,wrap='word',font=('Microsoft YaHei UI',11),bd=1,relief='solid');self.description.pack(fill='x')
        ttk.Button(daily,text='生成日常建议',command=self.propose).pack(anchor='w',pady=12)
        self.fields={}
        for key,label,parent in [('activities','活动分类（逗号分隔）',daily),('hours','常用时间（可选）',daily),('workflow','活动说明（可选）',daily),('projects','项目名称（逗号分隔）',projects),('software','常用软件',projects),('websites','常用网站',projects)]:
            ttk.Label(parent,text=label).pack(anchor='w',pady=(12,6))
            entry=ttk.Entry(parent);entry.pack(fill='x');self.fields[key]=entry
        for parent in [daily,projects]:ttk.Button(parent,text='保存个人档案',style='Accent.TButton',command=self.save_profile).pack(anchor='w',pady=20)
        ttk.Button(daily,text='分类颜色',command=self.category_dialog).pack(anchor='w')
        ttk.Label(learning,text='AI 自动整理',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w',pady=(0,12))
        ttk.Label(learning,text='开启后，在本窗口打开期间分批整理新活动，并生成简短复盘。\n人工确认优先，规则建议仍需你批准。',foreground=MUTED).pack(anchor='w',pady=(0,18))
        self.auto_ai=tk.BooleanVar(value=False)
        ttk.Checkbutton(learning,text='允许后台 AI 分析新活动',variable=self.auto_ai,command=self.toggle_ai).pack(anchor='w')
        self.ai_note=tk.StringVar(value='未开启 · 无云端发送')
        ttk.Label(learning,textvariable=self.ai_note,foreground=MUTED,wraplength=650).pack(anchor='w',pady=12)
        for label,command in [('重试待识别活动',self.retry_ai),('管理学习规则',self.rule_dialog),('查看纠正记录',self.show_history),('查看规则建议',self.suggest_rules),('导出个人记忆',self.export),('删除个人记忆',self.forget)]:
            ttk.Button(learning,text=label,command=command).pack(anchor='w',pady=5)
        ttk.Label(advanced,text='模型连接',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w',pady=(0,20))
        ttk.Label(advanced,text='服务地址').pack(anchor='w')
        self.endpoint=ttk.Entry(advanced);self.endpoint.insert(0,DEEPSEEK_ENDPOINT);self.endpoint.pack(fill='x',pady=8)
        ttk.Label(advanced,text='模型名称').pack(anchor='w')
        self.model=ttk.Entry(advanced);self.model.insert(0,DEEPSEEK_MODEL);self.model.pack(fill='x',pady=8)
        for label,command in [('保存模型配置',self.save_model),('设置密钥',self.set_key),('删除密钥',self.delete_key)]:ttk.Button(advanced,text=label,command=command).pack(anchor='w',pady=7)
        ttk.Label(advanced,text='密钥仅保存于 Windows Credential Manager。\n修改模型连接后，需要重新开启后台分析。',foreground=MUTED).pack(anchor='w',pady=18)

    def build_timeline(self):
        header=ttk.Frame(self.timeline_tab);header.pack(fill='x',pady=(4,20))
        self.heading=tk.StringVar(value='今天的故事')
        ttk.Label(header,textvariable=self.heading,font=('Microsoft YaHei UI',24,'bold')).pack(side='left')
        self.capture_state=tk.StringVar(value='未开始记录')
        self.capture_button=ttk.Button(header,text='开始记录',command=self.toggle_capture)
        self.capture_button.pack(side='right')
        ttk.Label(header,textvariable=self.capture_state,foreground=MUTED).pack(side='right',padx=12)
        toolbar=ttk.Frame(self.timeline_tab);toolbar.pack(fill='x',pady=(0,18))
        ttk.Button(toolbar,text='‹',width=3,command=lambda:self.shift_day(-1)).pack(side='left')
        self.date=ttk.Entry(toolbar,width=13);self.date.insert(0,datetime.now().strftime('%Y-%m-%d'));self.date.pack(side='left',padx=8)
        self.date.bind('<Return>',lambda _:self.refresh())
        ttk.Button(toolbar,text='›',width=3,command=lambda:self.shift_day(1)).pack(side='left')
        self.pending=tk.StringVar(value='待确认 0')
        ttk.Button(toolbar,textvariable=self.pending,command=self.toggle_review).pack(side='right')
        self.search=tk.StringVar()
        search=ttk.Entry(toolbar,textvariable=self.search,width=20);search.pack(side='right',padx=12)
        ttk.Label(toolbar,text='搜索',foreground=MUTED).pack(side='right')
        self.search.trace_add('write',lambda *_:self.filter_cards())
        self.summary_box=ttk.Frame(self.timeline_tab,padding=(20,14),style='Card.TFrame');self.summary_box.pack(fill='x',pady=(0,16))
        self.summary=tk.StringVar(value='活动还在整理中。')
        ttk.Button(self.summary_box,text='今日概览 · 收起 / 展开',command=self.collapse_summary).pack(anchor='w')
        self.summary_label=ttk.Label(self.summary_box,textvariable=self.summary,wraplength=790,foreground='#66758C',background='white')
        self.summary_label.pack(anchor='w',pady=(8,0))
        body=ttk.Frame(self.timeline_tab);body.pack(fill='both',expand=True)
        self.diary=DiaryCanvas(body,self.open_card,self.hover_image,self.quick_confirm)
        bar=ttk.Scrollbar(body,orient='vertical',command=self.diary.yview)
        self.diary.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');self.diary.pack(fill='both',expand=True)
        self.diary.bind('<Leave>',lambda _:self.hide_preview())
        self.timeline=ttk.Treeview(self.timeline_tab,columns=('time','duration','task','category','project','state','source'))
        self.category_colors={}

    def build_review(self):
        self.review=ttk.Treeview(self.review_tab,columns=('time','duration','task','category','project','state','source'))

    def navigate(self,page,refresh=True):
        self.page=page;self.only_review=False
        for name,button in self.nav.items():button.configure(bg='#DFE8FA' if name==page else '#EDF1F7',fg=BLUE if name==page else '#637188')
        self.tabs.select(self.profile_tab if page=='设置' else self.timeline_tab)
        self.heading.set({'今日':'今天的故事','历史记录':'时光档案','AI 复盘':'回看这一天'}.get(page,'今天的故事'))
        if page=='今日':
            self.date.delete(0,'end');self.date.insert(0,datetime.now().strftime('%Y-%m-%d'))
        if page == 'AI 复盘' and not self.summary_label.winfo_manager():
            self.summary_label.pack(anchor='w', pady=(8, 0))
        if refresh:
            self.refresh()

    def shift_day(self,delta):
        try:day=datetime.strptime(self.date.get(),'%Y-%m-%d')+timedelta(days=delta)
        except ValueError:return
        self.date.delete(0,'end');self.date.insert(0,day.strftime('%Y-%m-%d'));self.refresh()

    def collapse_summary(self):
        if self.summary_label.winfo_manager():self.summary_label.pack_forget()
        else:self.summary_label.pack(anchor='w',pady=(8,0))

    def toggle_review(self):
        self.only_review=not self.only_review;self.filter_cards()

    def update_overview(self,visible,day):
        self.all_cards=cards(visible)
        self.summary.set(overview(self.all_cards))
        self.pending.set(f"待确认 {sum(c['review'] for c in self.all_cards)}"+(' · 仅看待确认' if self.only_review else ''))
        self.filter_cards()

    def refresh(self,load_profile=False,quiet=False):
        try:day=datetime.strptime(self.date.get(),'%Y-%m-%d')
        except ValueError:
            if not quiet:messagebox.showerror('日期','请输入 YYYY-MM-DD')
            return
        start=int(day.timestamp()*1000);end=int((day+timedelta(days=1)).timestamp()*1000)
        def read(memory):
            rows=[dict(r,start_ms=max(start,r['start_ms']),end_ms=min(end,r['end_ms'])) for r in memory.timeline(start,end)]
            return rows,cards(rows),memory.profile(),memory.tasks(),memory.rules(),options(self.database)
        def show(data):
            rows,items,profile,self.tasks,self.rules,config=data
            self.rows={r['interval_id']:r for r in rows}
            self.display_ids=list(self.rows)
            self.category_colors=config.get('category_colors',{})
            self.all_cards=items
            self.summary.set(overview(items))
            if self.review_cache:
                current={r['interval_id']:(r['label'],r['category'],r['project'],(r['end_ms']-r['start_ms'])//1000,r['reliability'],r['revision']) for r in rows if r['state']=='active'}
                valid=all(current.get(identifier)==value for identifier,value in self.review_cache['facts'].items())
                if valid:self.summary.set('AI 复盘 · 已授权活动（最多 100 段）\n'+self.review_cache['text'])
                else:self.review_cache=None
            self.pending.set(f"待确认 {sum(c['review'] for c in items)}")
            self.filter_cards()
            if load_profile:
                if not profile['activities']:profile=dict(profile,activities=list(DEFAULT_CATEGORIES))
                self.fill_profile(profile)
                self.dwell.delete(0,'end');self.dwell.insert(0,str(config.get('min_dwell_seconds',5)))
                self.capture_enabled.set(config.get('screenshots_enabled') is True)
        self.job(read,show,quiet=quiet)

    def filter_cards(self):
        query=self.search.get().strip().casefold()
        shown=[c for c in self.all_cards if (not self.only_review or c['review']) and (not query or query in (c['title']+' '+c['category']+' '+c['project']).casefold())]
        self.diary.set_cards(shown,self.category_colors)

    def quick_confirm(self, card):
        if card['rows'][0]['state'] != 'active':
            return
        self.confirm_cards([card])

    def open_card(self,card):
        if len(card['rows'])==1:
            row=card['rows'][0]
            if row['state']!='active':
                messagebox.showinfo('时间记录',card['description']);return
            self.job(lambda memory:memory.evidence(row['interval_id']),lambda evidence:self.detail(row,evidence));return
        win=tk.Toplevel(self.root);win.title(card['title']+' · 活动依据');win.geometry('760x580')
        frame=ttk.Frame(win,padding=24);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=card['title'],font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(frame,text='这些连续片段具有相同任务或相同内容依据。选择片段查看、纠正或拆分归属。',wraplength=680,foreground=MUTED).pack(anchor='w',pady=12)
        listing=tk.Listbox(frame,font=('Microsoft YaHei UI',11),bd=0,highlightthickness=0)
        listing.pack(fill='both',expand=True)
        for row in card['rows']:
            listing.insert('end',f"{datetime.fromtimestamp(row['start_ms']/1000):%H:%M:%S}  {duration(row['end_ms']-row['start_ms'])}   {row.get('process_name') or '未知应用'}   {(row.get('title') or '')[:55]}")
        def choose(_=None):
            if not listing.curselection():return
            row=card['rows'][listing.curselection()[0]]
            self.job(lambda memory:memory.evidence(row['interval_id']),lambda e:self.detail(row,e))
        listing.bind('<Double-Button-1>',choose)
        ttk.Button(frame,text='查看选中片段',command=choose).pack(anchor='e',pady=12)
        ttk.Button(frame,text='确认整个活动',style='Accent.TButton',command=lambda:self.confirm_cards([card],win)).pack(anchor='e')

    def confirm_cards(self,items,parent=None):
        win=tk.Toplevel(parent or self.root);win.title('确认活动归属');win.geometry('520x400')
        frame=ttk.Frame(win,padding=24);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='这些片段属于同一件事',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=(0,16))
        entries=[]
        for label,value in [('活动名称',items[0]['title']),('分类',items[0]['category']),('项目',items[0]['project'])]:
            ttk.Label(frame,text=label).pack(anchor='w')
            entry=ttk.Entry(frame);entry.insert(0,value);entry.pack(fill='x',pady=(5,12));entries.append(entry)
        ids=[r['interval_id'] for item in items for r in item['rows']]
        def save():
            values=[e.get().strip() for e in entries]
            if not values[0]:return
            self.cancel_cloud()
            def work(memory):
                Classifier(memory).analyze(ids)
                memory.feedback_many(ids,*values,remember=True)
            win.destroy()
            if parent:parent.destroy()
            self.job(work,lambda _:self.refresh())
        ttk.Button(frame,text='确认并记住',style='Accent.TButton',command=save).pack(anchor='e',pady=12)

    def detail(self,row,evidence):
        # Reuse original evidence / correction / deletion and feedback semantics.
        super().detail(row,evidence)
        if not evidence:return
        windows=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]
        if not windows:return
        win=windows[-1]
        win.configure(bg=BG)
        win.title(f"活动详情 · {(row.get('label') or row.get('title') or '待确认')[:32]}")
        # Merge is an explicit human decision at a contiguous active boundary.
        current=next((c for c in self.all_cards if row['interval_id'] in [r['interval_id'] for r in c['rows']]),None)
        if current:
            index=self.all_cards.index(current)
            following=self.all_cards[index+1] if index+1<len(self.all_cards) else None
            if following and current['end_ms']==following['start_ms'] and following['rows'][0]['state']=='active' and following['rows'][0]['session_id']==row['session_id']:
                ttk.Button(win,text='与下一段合并为同一活动…',command=lambda:self.confirm_cards([current,following],win)).pack(pady=6)

    def save_model(self):
        endpoint,model=self.endpoint.get().strip(),self.model.get().strip()
        try:TextProvider(endpoint,model)
        except Exception:messagebox.showerror('模型配置','请输入有效的 HTTPS 地址和模型名称。');return
        self.cancel_cloud();self.auto_ai.set(False)
        self.job(lambda _:save_options(self.database,ai_endpoint=endpoint,ai_model=model,auto_ai=False),lambda _:self.ai_note.set('模型配置已保存，请重新开启后台分析。'))

    def toggle_ai(self):
        if getattr(self,'preview_mode',False):
            self.auto_ai.set(False);return
        if self.busy:self.auto_ai.set(not self.auto_ai.get());return
        enabled=self.auto_ai.get()
        if enabled and not messagebox.askyesno('开启后台 AI 分析',f'发送到：{self.endpoint.get().strip()}\n模型：{self.model.get().strip()}\n将自动发送开启后产生的活动标题、最多 2000 字脱敏正文、个人档案和候选分类；复盘会发送授权范围内的活动名称、分类和时长。\n例如：“阅读 Python 文档” → “学习”。\n每批最多 20 段，至少间隔 60 秒；复盘最多 100 段。不发送截图，不补发开启前的历史正文。\n可以随时关闭；已发送内容无法撤回。是否开启？'):
            self.auto_ai.set(False);return
        self.cancel_cloud()
        since=time.time_ns()//1_000_000
        endpoint,model=self.endpoint.get().strip(),self.model.get().strip()
        self.job(lambda _:save_options(self.database,auto_ai=enabled,ai_since_ms=since,ai_endpoint=endpoint,ai_model=model),lambda _:self.ai_note.set('已开启 · 后台批量整理新活动' if enabled else '已关闭 · 无云端发送'))
        self.next_ai=0

    def retry_ai(self):
        self.next_ai=0
        self.ai_note.set('将在下一轮重试授权范围内的待识别活动。')

    def toggle_capture(self):
        if getattr(self,'preview_mode',False):return
        self.cancel_cloud()
        if self.recording=='stopped':
            import subprocess,sys
            from pathlib import Path
            # Start is an explicit UI action; content has its own visible prompt.
            if not messagebox.askyesno('开始记录','记录前台应用、窗口标题和可读正文。截图是否开启遵循“采集与隐私”设置。现在开始？'):return
            source_root=Path(__file__).parents[3]
            entry=[str(source_root/'daytrace.py')] if (source_root/'daytrace.py').is_file() else ['-m','daytrace']
            launch = dict(cwd=str(source_root))
            if sys.platform == 'win32':
                launch['creationflags'] = subprocess.CREATE_NO_WINDOW
            self.collector_process=subprocess.Popen([sys.executable,*entry,'--db',str(self.database),'start','--content'],**launch)
        else:
            from ..cli import control
            command='resume' if self.recording=='paused' else 'pause'
            self.job(lambda _:control(self.database,command))

    def cancel_cloud(self):
        super().cancel_cloud()
        if self.ai_cancel:self.ai_cancel.set()
        self.review_cache=None

    def background(self):
        if self.closed:return
        if self.ai_future and self.ai_future.done():
            try:
                result=self.ai_future.result()
                self.recording=result['state']
                self.capture_state.set({'running':'正在记录','paused':'已暂停','stopped':'未开始记录'}[self.recording])
                self.capture_button.configure(text={'running':'暂停','paused':'恢复','stopped':'开始记录'}[self.recording])
                if result.get('note'):self.ai_note.set(result['note'])
                if result.get('cooldown'):self.next_ai=time.monotonic()+result['cooldown']
                if result.get('review') and result['review'].get('text'):
                    self.review_cache=result['review']
                    if not self.busy:self.refresh(quiet=True)
                if not hasattr(self,'loaded_preferences'):
                    config=result['options'];self.loaded_preferences=True
                    self.auto_ai.set(config.get('auto_ai') is True)
                    for entry,key in [(self.endpoint,'ai_endpoint'),(self.model,'ai_model')]:
                        if config.get(key):entry.delete(0,'end');entry.insert(0,config[key])
            except Exception:self.ai_note.set('后台整理暂不可用，原始记录已保留。')
            self.ai_future=None
        if self.ai_future is None and not self.busy:
            from .diary_worker import tick,review
            import threading
            self.ai_cancel=threading.Event()
            analyze=time.monotonic()>=self.next_ai
            if analyze:self.next_ai=time.monotonic()+60
            try:day=datetime.strptime(self.date.get(),'%Y-%m-%d')
            except ValueError:day=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
            start=int(day.timestamp()*1000);end=int((day+timedelta(days=1)).timestamp()*1000)
            previous=self.review_cache['key'] if self.review_cache else None
            cancel=self.ai_cancel
            def work():
                result=tick(self.database,cancel,analyze)
                if analyze and not result.get('cooldown'):
                    result['review']=review(self.database,cancel,start,end,previous)
                return result
            self.ai_future=self.ai_executor.submit(work)
        self.root.after(2000,self.background)

    def close(self):
        self.cancel_cloud()
        if self.collector_process and self.collector_process.poll() is None:
            from ..cli import control
            future=self.executor.submit(control,self.database,'stop')
            self.capture_state.set('正在停止记录…')
            def finish():
                if not future.done():self.root.after(100,finish);return
                try:future.result()
                except Exception:
                    messagebox.showerror('尚未退出','停止采集未成功，请稍后重试退出。');return
                self.collector_process=None;self.close()
            self.root.after(100,finish)
            return
        self.ai_executor.shutdown(wait=False,cancel_futures=True)
        super().close()


def launch(database):
    root=tk.Tk()
    DiaryApp(root,database)
    root.mainloop()
