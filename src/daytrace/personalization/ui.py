"""Small native desktop UI. All database/network work runs off the Tk thread."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as daytime, timedelta
import json
from pathlib import Path
import queue
import base64
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .store import Memory
from .display import activity_label, group_rows
from ..preferences import dwell_seconds, save_dwell, screenshots_enabled, save_options, options
from .timeline_view import DayCanvas, category_color, PALETTE
from .profile import propose_profile
from .classifier import Classifier
from .provider import TextProvider, Vault, DEEPSEEK_ENDPOINT, DEEPSEEK_MODEL


def sync_tree(tree, desired):
    """Update changed cells only, preserving existing rows and expansion state."""
    wanted = {iid for iid, _, _ in desired}
    existing = set(tree.get_children())
    for parent in list(existing):
        existing.update(tree.get_children(parent))
    positions = {}
    for iid, parent, values in desired:
        index = positions.get(parent, 0)
        positions[parent] = index + 1
        if not tree.exists(iid):
            tree.insert(parent, index, iid=iid, values=values)
        else:
            if tuple(map(str, tree.item(iid, 'values'))) != tuple(map(str, values)):
                tree.item(iid, values=values)
            if tree.parent(iid) != parent or tree.index(iid) != index:
                tree.move(iid, parent, index)
    for iid in existing - wanted:
        if tree.exists(iid):
            tree.delete(iid)


class App:
    def __init__(self, root, database):
        self.root, self.database = root, database
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='daytrace-review')
        self.completed = queue.Queue()
        self.provider = None
        self.busy = False
        self.closed = False
        self.rows, self.tasks, self.rules = {}, [], []
        self.display_ids = []
        self.hover_id = None
        self.hover_timer = None
        self.preview_window = None
        root.title('DayTrace · 了解你的一天')
        root.geometry('1180x860')
        root.minsize(1000, 850)
        root.configure(bg='#F5F6FA')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10), background='#F5F6FA', foreground='#273044')
        style.configure('Accent.TButton',background='#7566D9',foreground='white',padding=(20,10),borderwidth=0)
        style.map('Accent.TButton',background=[('active','#6555C5')])
        style.configure('Card.TFrame',background='white')
        style.configure('TButton', padding=(12, 7))
        style.configure('TNotebook.Tab', padding=(25, 12))
        style.configure('Treeview', rowheight=32, background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 10, 'bold'))
        header = ttk.Frame(root, padding=20)
        header.pack(fill='x')
        ttk.Label(header, text='DayTrace', font=('Segoe UI', 25, 'bold'),foreground='#3B345B').pack(side='left')
        ttk.Label(header, text='   YOUR DAY, AT A GLANCE',font=('Segoe UI',9),foreground='#9693A7').pack(side='left',padx=18)
        self.status = tk.StringVar(value='本窗口不启动监测 · 云端默认关闭；采集状态以采集终端为准')
        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill='both', expand=True, padx=20, pady=12)
        self.profile_tab = ttk.Frame(self.tabs, padding=18)
        self.timeline_tab = ttk.Frame(self.tabs, padding=14)
        self.review_tab = ttk.Frame(self.tabs, padding=14)
        for page, title in ((self.timeline_tab, '时间线'), (self.review_tab, '待复核'), (self.profile_tab, '个人设置')):
            self.tabs.add(page, text=title)
        self.build_profile()
        self.build_timeline()
        self.build_review()
        controls = ttk.Frame(self.profile_tab)
        controls.pack(fill='x', padx=22)
        ttk.Label(controls, text='最短停留（秒）').pack(side='left')
        self.dwell = ttk.Entry(controls, width=8)
        self.dwell.insert(0, '5')
        self.dwell.pack(side='left', padx=6)
        ttk.Button(controls, text='保存（下次启动监测生效）', command=self.save_capture_preferences).pack(side='left')
        self.capture_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text='开启截图留存',variable=self.capture_enabled,command=self.save_screenshots).pack(side='left',padx=8)
        ttk.Label(controls,text='前台窗口 · 本地7天 · 不上传；开启后重启监测').pack(side='left')
        ttk.Label(self.profile_tab, text='使用 start 命令开始监测；AI 分类前请停止采集。', padding=(0,8)).pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)
        self.refresh(load_profile=True)
        root.after(5000, self.auto_refresh)

    def job(self, function, callback=None, quiet=False):
        if self.busy:
            if quiet:
                return
            messagebox.showinfo('正在处理', '请等待当前操作完成，或取消云端请求。')
            return
        self.busy = True
        self.status.set('正在处理… · 不启动采集')
        def work():
            memory = None
            try:
                memory = Memory(self.database, cleanup=not quiet)
                return function(memory)
            finally:
                if memory:
                    memory.close()
        future = self.executor.submit(work)
        future.add_done_callback(lambda done: self.completed.put((done, callback, quiet)))

    def poll(self):
        if self.closed:
            return
        try:
            future, callback, quiet = self.completed.get_nowait()
            self.busy = False
            try:
                value = future.result()
                self.status.set('操作完成 · 本窗口不采集 · 云端仅发送明确授权的批次')
                if callback:
                    callback(value)
            except Exception as error:
                self.status.set('操作未完成 · 数据未自动发送')
                # Do not echo exception strings which may contain SQL, model text or keys.
                messagebox.showerror('操作未完成', type(error).__name__ + '：请检查输入、数据库状态；首次升级或隐私操作前请停止采集。')
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def build_profile(self):
        ttk.Label(self.profile_tab, text='你平时主要做什么？', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(self.profile_tab, text='先写几句话，再检查下面的建议。档案只是参考，不会把所有软件活动归入同一个项目。').pack(anchor='w', pady=6)
        self.description = tk.Text(self.profile_tab, height=3, wrap='word', font=('Microsoft YaHei UI', 11), relief='solid', bd=1)
        self.description.pack(fill='x')
        ttk.Button(self.profile_tab, text='生成本地建议（不联网）', command=self.propose).pack(anchor='w', pady=8)
        form = ttk.Frame(self.profile_tab)
        form.pack(fill='x')
        self.fields = {}
        names = [('activities', '日常活动（逗号分隔）'), ('projects', '当前项目'), ('software', '常用软件'), ('websites', '常用网站'), ('hours', '工作时间（可选）'), ('workflow', '工作流程 / 活动说明')]
        for index, (key, title) in enumerate(names):
            ttk.Label(form, text=title).grid(row=index, column=0, sticky='w', pady=4)
            entry = ttk.Entry(form)
            entry.grid(row=index, column=1, sticky='ew', padx=12, pady=4)
            self.fields[key] = entry
        form.columnconfigure(1, weight=1)
        buttons = ttk.Frame(self.profile_tab)
        buttons.pack(fill='x', pady=10)
        ttk.Button(buttons, text='确认并保存档案', command=self.save_profile).pack(side='left')
        ttk.Button(buttons, text='候选任务 / 规则管理', command=self.rule_dialog).pack(side='left', padx=8)
        ttk.Button(buttons, text='导出个人记忆', command=self.export).pack(side='left')
        ttk.Button(buttons, text='删除全部个人记忆', command=self.forget).pack(side='right')
        ttk.Separator(self.profile_tab).pack(fill='x', pady=8)
        ttk.Label(self.profile_tab, text='可选云端文本模型 · 默认不发送', font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        cloud = ttk.Frame(self.profile_tab)
        cloud.pack(fill='x', pady=6)
        self.endpoint, self.model = ttk.Entry(cloud, width=55), ttk.Entry(cloud, width=22)
        self.endpoint.insert(0, DEEPSEEK_ENDPOINT)
        self.model.insert(0, DEEPSEEK_MODEL)
        self.endpoint.pack(side='left', fill='x', expand=True)
        ttk.Label(cloud, text=' 模型 ').pack(side='left')
        self.model.pack(side='left')
        ttk.Button(cloud, text='设置密钥', command=self.set_key).pack(side='left', padx=6)
        ttk.Button(cloud, text='删除密钥', command=self.delete_key).pack(side='left')
        ttk.Label(self.profile_tab, text='密钥仅保存在 Windows Credential Manager；地址、模型本次窗口有效。发送前可查看完整脱敏批次。').pack(anchor='w')

    def save_capture_preferences(self):
        value = self.dwell.get()
        self.job(lambda memory: save_dwell(self.database, value))

    def save_screenshots(self):
        value=self.capture_enabled.get()
        if self.busy:
            self.capture_enabled.set(not value)
            messagebox.showinfo('正在处理','请等待当前操作完成后再切换。')
            return
        self.hide_preview()
        self.job(lambda memory: save_options(self.database,screenshots_enabled=value))

    def propose(self):
        self.fill_profile(propose_profile(self.description.get('1.0', 'end-1c')))
        self.status.set('本地建议已生成，请补充项目并确认保存；尚未写入档案')

    def fill_profile(self, profile):
        self.description.delete('1.0', 'end')
        self.description.insert('1.0', profile['description'])
        for key, entry in self.fields.items():
            entry.delete(0, 'end')
            value = profile[key]
            entry.insert(0, '，'.join(value) if isinstance(value, list) else value)

    def save_profile(self):
        profile = {'description': self.description.get('1.0', 'end-1c')}
        for key, entry in self.fields.items():
            value = entry.get()
            profile[key] = [x.strip() for x in value.replace('，', ',').split(',') if x.strip()] if key in ('activities', 'projects', 'software', 'websites') else value
        self.job(lambda memory: memory.save_profile(profile), lambda _: self.refresh())

    def build_timeline(self):
        toolbar = ttk.Frame(self.timeline_tab)
        toolbar.pack(fill='x', pady=(0, 18))
        ttk.Label(toolbar,text='一天的轨迹',font=('Microsoft YaHei UI',20,'bold'),foreground='#34304B').pack(side='left',padx=(0,24))
        self.date = ttk.Entry(toolbar, width=14)
        self.date.insert(0, datetime.now().strftime('%Y-%m-%d'))
        self.date.pack(side='left')
        self.date.bind('<Return>',lambda _:self.refresh())
        ttk.Button(toolbar,text='查看',command=self.refresh).pack(side='left',padx=6)
        ttk.Button(toolbar,text='AI 分类',style='Accent.TButton',command=self.preview_cloud).pack(side='right')
        ttk.Button(toolbar,text='添加分类',command=self.category_dialog).pack(side='right',padx=10)
        self.day_summary=tk.StringVar(value='暂无记录')
        ttk.Label(self.timeline_tab,textvariable=self.day_summary,foreground='#8B94A5').pack(anchor='w',pady=(0,12))
        card=ttk.Frame(self.timeline_tab,style='Card.TFrame',padding=12)
        card.pack(fill='both',expand=True)
        self.day_canvas=DayCanvas(card,self.select_fragment,height=430)
        self.day_canvas.pack(fill='both',expand=True)
        self.day_canvas.bind('<Motion>',self.canvas_hover)
        self.day_canvas.bind('<Leave>',lambda _:self.hide_preview())
        self.legend=tk.Canvas(self.timeline_tab,height=78,background='#F5F6FA',highlightthickness=0)
        self.legend.pack(fill='x',pady=(16,0))
        ttk.Label(self.timeline_tab,text='点击色块查看详情与纠正 · 灰色表示尚未分类或记录间隙',foreground='#979EAC',font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=8)
        # A non-visible backing selection model preserves existing review operations.
        self.timeline=ttk.Treeview(self.timeline_tab,columns=('time','duration','task','category','project','state','source'))
        self.category_colors={};self.legend_signature=None

    def select_fragment(self,identifier):
        if self.timeline.exists(identifier):
            self.timeline.selection_set(identifier)
            self.open_selected(self.timeline)

    def canvas_hover(self,event):
        self.day_canvas.hit(event)
        self.hover_image(self.day_canvas,event)

    def category_dialog(self):
        win=tk.Toplevel(self.root);win.title('添加分类');win.geometry('440x310')
        frame=ttk.Frame(win,padding=24);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='按你自己的方式分类',font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w',pady=(0,14))
        name=ttk.Entry(frame,font=('Microsoft YaHei UI',12));name.pack(fill='x');name.focus_set()
        ttk.Label(frame,text='例如：工作、学习、创作、生活',foreground='#939BAA').pack(anchor='w',pady=8)
        color=tk.StringVar(value=PALETTE[0])
        swatches=ttk.Frame(frame);swatches.pack(fill='x',pady=8)
        for value in PALETTE:
            tk.Radiobutton(swatches,variable=color,value=value,indicatoron=False,width=3,background=value,selectcolor=value,text='●',foreground='white',relief='flat',borderwidth=3).pack(side='left',padx=2)
        def save():
            label=name.get().strip();chosen=color.get()
            if not label:return
            win.destroy()
            self.job(lambda memory: memory.add_category(label,chosen),lambda _:self.refresh())
        ttk.Button(frame,text='保存分类',style='Accent.TButton',command=save).pack(anchor='e',pady=18)

    def update_overview(self,visible,day):
        self.day_canvas.update_rows(visible,day,self.category_colors)
        totals={}
        for row in visible:
            if row['state']=='active':
                key=row.get('category') or '待分类'
                totals[key]=totals.get(key,0)+row['end_ms']-row['start_ms']
        total=sum(totals.values())//60000
        text=f'{total//60} 小时 {total%60} 分钟活动记录   ·   {len(visible)} 个片段'
        if self.day_summary.get()!=text:self.day_summary.set(text)
        signature=(tuple(sorted(totals.items())),tuple(sorted(self.category_colors.items())))
        if signature!=self.legend_signature:
            self.legend_signature=signature;self.legend.delete('all')
            for index,(name,duration) in enumerate(sorted(totals.items(),key=lambda x:-x[1])):
                x=12+(index%5)*205;y=12+(index//5)*34
                color=category_color('' if name=='待分类' else name,self.category_colors)
                self.legend.create_rectangle(x,y,x+10,y+10,fill=color,outline='')
                self.legend.create_text(x+18,y+5,anchor='w',text=f'{name[:10]}  {duration/60000:.0f} 分钟',fill='#667085',font=('Microsoft YaHei UI',10))
            self.legend.configure(height=max(44,((len(totals)+4)//5)*34+12))

    def build_review(self):
        ttk.Label(self.review_tab, text='集中确认，不打断工作', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w', pady=6)
        ttk.Label(self.review_tab, text='待确认与未知活动会出现在这里。一次纠正可保存为案例，规则须另外批准。').pack(anchor='w', pady=6)
        self.review = self.make_tree(self.review_tab)
        self.review.bind('<Double-1>', lambda _: self.open_selected(self.review))
        buttons = ttk.Frame(self.review_tab)
        buttons.pack(fill='x', pady=10)
        ttk.Button(buttons, text='确认 / 纠正选中活动', command=lambda: self.open_selected(self.review)).pack(side='left')
        ttk.Button(buttons, text='近期纠正历史', command=self.show_history).pack(side='left', padx=8)
        ttk.Button(buttons, text='已学习规则', command=self.rule_dialog).pack(side='left')
        ttk.Button(buttons, text='从重复纠正建议规则', command=self.suggest_rules).pack(side='left', padx=8)
        ttk.Button(buttons,text='本地重新分析',command=self.analyze).pack(side='left',padx=6)
        ttk.Button(buttons,text='取消 AI 请求',command=self.cancel_cloud).pack(side='left')

    def make_tree(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill='both', expand=True)
        keys = ('time', 'duration', 'task', 'category', 'project', 'state', 'source')
        tree = ttk.Treeview(container, columns=keys, show='tree headings', selectmode='browse')
        tree.column('#0', width=28, minwidth=28, stretch=False)
        for key, title, width in zip(keys, ('时间', '时长', '活动', '类别', '项目', '状态', '依据来源'), (155, 65, 260, 95, 120, 100, 90)):
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=55)
        scroll = ttk.Scrollbar(container, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        tree.bind('<Motion>', lambda event: self.hover_image(tree,event))
        tree.bind('<Leave>', lambda _: self.hide_preview())
        return tree

    def hide_preview(self):
        self.hover_id = None
        if self.hover_timer:
            self.root.after_cancel(self.hover_timer)
            self.hover_timer = None
        if self.preview_window:
            self.preview_window.destroy()
            self.preview_window = None

    def hover_image(self, tree, event):
        identifier = tree.identify_row(event.y)
        if identifier == self.hover_id:
            return
        self.hide_preview()
        if not identifier or identifier.startswith('group:'):
            return
        self.hover_id = identifier
        x,y = event.x_root+18,event.y_root+18
        def read(memory):
            from ..storage.screenshots import read
            result = read(memory.repo,identifier,memory.now())
            if not result:
                return None
            import io
            from PIL import Image
            with Image.open(io.BytesIO(result['png'])) as original:
                original.thumbnail((600,340))
                buffer = io.BytesIO()
                original.save(buffer,format='PNG')
            return buffer.getvalue()
        def show(png):
            if self.hover_id!=identifier or not png or self.closed:
                return
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.geometry(f'+{min(x,max(0,self.root.winfo_screenwidth()-620))}+{min(y,max(0,self.root.winfo_screenheight()-380))}')
            photo = tk.PhotoImage(data=base64.b64encode(png))
            label = ttk.Label(win,image=photo)
            label.image = photo
            label.pack()
            ttk.Label(win,text='授权区域截图 · 仅本地证据').pack()
            self.preview_window = win
            self.hover_timer = self.root.after(2000,self.hide_preview)
        def launch():
            self.hover_timer = None
            if not self.busy:
                self.job(read,show,quiet=True)
        self.hover_timer = self.root.after(450,launch)

    def auto_refresh(self):
        if self.closed:
            return
        # Never interrupt an editor, confirmation dialog, or an ongoing request.
        if not self.busy and not any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()):
            self.refresh(quiet=True)
        self.root.after(5000, self.auto_refresh)

    def refresh(self, load_profile=False, quiet=False):
        try:
            day = datetime.strptime(self.date.get(), '%Y-%m-%d')
        except ValueError:
            if not quiet:
                messagebox.showerror('日期', '请输入 YYYY-MM-DD')
            return
        start = int(day.timestamp() * 1000)
        end = int((day + timedelta(days=1)).timestamp() * 1000)
        def read(memory):
            return memory.timeline(), memory.profile(), memory.tasks(), memory.rules(), dwell_seconds(self.database), screenshots_enabled(self.database), options(self.database).get('category_colors',{})
        def show(data):
            rows, profile, self.tasks, self.rules, dwell, capture_enabled, self.category_colors = data
            self.rows = {r['interval_id']: r for r in rows}
            if load_profile:
                self.fill_profile(profile)
                self.dwell.delete(0, 'end')
                self.dwell.insert(0, f'{dwell:g}')
                self.capture_enabled.set(capture_enabled)
            visible = []
            for row in rows:
                if row['end_ms'] > start and row['start_ms'] < end:
                    visible.append(dict(row, start_ms=max(start,row['start_ms']), end_ms=min(end,row['end_ms'])))
            self.display_ids = [r['interval_id'] for r in visible]
            self.update_overview(visible,day)
            sources = {'human': '人工', 'rule': '规则', 'history': '历史案例', 'ai': 'AI', 'fallback': '待识别', 'conflict': '冲突'}
            def values(row):
                a, b = row['start_ms'], row['end_ms']
                state = {'supported': '已识别', 'tentative': '待确认', 'unknown': '未知'}.get(row['reliability'], '未分析')
                if row['state'] != 'active':
                    state = activity_label(row)
                return [datetime.fromtimestamp(a/1000).strftime('%H:%M:%S')+'–'+datetime.fromtimestamp(b/1000).strftime('%H:%M:%S'),
                        f'{(b-a)/1000:.0f} 秒', activity_label(row), row['category'] or '', row['project'] or '', state, sources.get(row['source'], '标题 / 应用' if row.get('title') else '—')]
            for tree in (self.timeline,self.review):
                selection = tree.selection()
                scroll = tree.yview()
                desired = []
                # Group before filtering review items so privacy/idle boundaries survive.
                for group in group_rows(visible):
                    if tree is self.review:
                        group = [r for r in group if r['state']=='active' and r['reliability']!='supported' and r['disposition'] not in ('ignore','confirmed')]
                    if not group:
                        continue
                    parent = ''
                    if len(group)>1:
                        parent = 'group:'+group[0]['interval_id']
                        summary = values(group[0])
                        summary[0] = f'{len(group)} 个独立片段'
                        summary[1] = f"{sum(r['end_ms']-r['start_ms'] for r in group)/1000:.0f} 秒"
                        summary[2] += '（汇总，展开查看）'
                        desired.append((parent, '', summary))
                    for row in group:
                        desired.append((row['interval_id'], parent, values(row)))
                sync_tree(tree, desired)
                for iid in selection:
                    if tree.exists(iid) and tree.selection() != (iid,):
                        tree.selection_set(iid)
                if scroll:
                    tree.yview_moveto(scroll[0])
        self.job(read, show, quiet=quiet)

    def visible_ids(self):
        return list(self.display_ids)

    def analyze(self):
        ids = self.visible_ids()
        self.job(lambda memory: Classifier(memory).analyze(ids), lambda _: self.refresh())

    def text_dialog(self, title, text):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry('850x620')
        box = tk.Text(win, wrap='word', font=('Microsoft YaHei UI', 10))
        box.pack(fill='both', expand=True, padx=12, pady=12)
        box.insert('1.0', text)
        box.configure(state='disabled')
        return win

    def open_selected(self, tree):
        selection = tree.selection()
        if not selection:
            return
        identifier = selection[0]
        if identifier.startswith('group:'):
            tree.item(identifier, open=True)
            return
        row = self.rows[identifier]
        if row['state'] != 'active':
            messagebox.showinfo('记录状态', '这是匿名、空闲或暂停区间，没有可用于任务识别的活动证据。')
            return
        self.job(lambda memory: memory.evidence(identifier), lambda evidence: self.detail(row, evidence))

    def detail(self, row, evidence):
        if not evidence:
            messagebox.showinfo('证据不可用', '活动尚未结束或证据已删除。')
            return
        win = tk.Toplevel(self.root)
        win.title('确认实际活动')
        win.geometry('820x680')
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=row['reason'] or '请先运行本地分析', font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=f"应用：{evidence['process_name']}  ·  原始事件：{evidence['event_id']}").pack(anchor='w', pady=6)
        box = tk.Text(frame, height=10, wrap='word', font=('Microsoft YaHei UI', 10))
        box.pack(fill='both', expand=True)
        content_status = {'no_text': '应用未提供可读正文', 'partial': '仅取得部分正文', 'success': '已取得正文', 'unavailable': '正文不可用 / 未采集'}.get(evidence['content_status'], evidence['content_status'])
        image_status = '已保存许可区域截图，可在时间线具体片段上悬停预览。' if evidence['has_screenshot'] else '未保存有效截图，无法还原当时屏幕。'
        box.insert('1.0', f"标题：{evidence['title'] or '原始标题已过期 / 不可用'}\n正文状态：{content_status}\n\n{evidence['text'] or '无可用正文，可根据自己的记忆纠正。'}\n\n{image_status}")
        box.configure(state='disabled')
        values = []
        for name, value in [('实际活动名称', row['label']), ('活动类别', row['category']), ('所属项目', row['project'])]:
            ttk.Label(frame, text=name).pack(anchor='w', pady=(8, 0))
            entry = ttk.Entry(frame)
            entry.pack(fill='x')
            entry.insert(0, value or '')
            values.append(entry)
        existing = ttk.Combobox(frame, state='readonly', values=[t['label'] + ' / ' + t['project'] for t in self.tasks])
        existing.pack(fill='x', pady=8)
        def choose(_):
            task = self.tasks[existing.current()]
            for entry, key in zip(values, ('label', 'category', 'project')):
                entry.delete(0, 'end'); entry.insert(0, task[key])
        existing.bind('<<ComboboxSelected>>', choose)
        remember = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='记住这次纠正，作为历史案例（不会自动建立全局规则）', variable=remember).pack(anchor='w', pady=8)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        def submit(action):
            if action == 'private' and not messagebox.askyesno('私人活动', '将删除此活动的应用、标题、正文和纠正记录，只保留匿名时间。请先停止采集。', parent=win):
                return
            label, category, project = [entry.get() for entry in values]
            saved = remember.get()
            self.cancel_cloud()
            def work(memory):
                Classifier(memory).analyze([row['interval_id']])
                memory.feedback(row['interval_id'], label, category, project, action, saved)
                memory.repo.cleanup(memory.now())
            win.destroy()
            self.job(work, lambda _: self.refresh())
        for text, action in [('确认并保存', 'confirm'), ('不知道', 'unknown'), ('忽略', 'ignore'), ('私人活动', 'private'), ('撤销人工结果', 'undo')]:
            ttk.Button(buttons, text=text, command=lambda a=action: submit(a)).pack(side='left', padx=3)
        def delete():
            if messagebox.askyesno('删除活动', '删除该片段及关联证据、修订。请先停止采集。', parent=win):
                self.cancel_cloud(); win.destroy()
                self.job(lambda memory: memory.delete_interval(row['interval_id']), lambda _: self.refresh())
        ttk.Button(frame, text='删除此活动及关联记录', command=delete).pack(anchor='e', pady=8)
        def delete_image():
            from ..storage.screenshots import delete_interval
            self.hide_preview()
            self.job(lambda memory: delete_interval(memory.repo,row['interval_id']))
        ttk.Button(frame,text='仅删除该活动截图（请先停止监测）',command=delete_image).pack(anchor='e')

    def rule_dialog(self):
        win = tk.Toplevel(self.root)
        win.title('候选任务与明确规则')
        win.geometry('820x700')
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='候选任务可供 AI 选择；规则只有明确批准后才启用。').pack(anchor='w')
        fields = {}
        for key, title in [('label', '任务名称'), ('category', '活动类别'), ('task_project', '任务所属项目'), ('app', '软件（精确进程名，可空）'), ('title', '标题包含'), ('keywords', '同时包含关键词（逗号分隔）'), ('exclude', '反例关键词（任一命中则排除）'), ('project', '证据必须包含的项目名'), ('context', '证据上下文包含')]:
            line = ttk.Frame(frame); line.pack(fill='x', pady=3)
            ttk.Label(line, text=title, width=32).pack(side='left')
            fields[key] = ttk.Entry(line); fields[key].pack(side='left', fill='x', expand=True)
        approved = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='我确认此规则的适用范围，并批准启用', variable=approved).pack(anchor='w', pady=8)
        selected_rule = [None]
        def save(rule):
            value = {k: entry.get() for k, entry in fields.items()}
            approval = approved.get()
            def work(memory):
                with memory.repo.transaction():
                    task = memory.task(value['label'], value['category'], value['task_project'])
                if rule:
                    condition = {k: v for k, v in value.items() if k not in ('label', 'category', 'task_project') and v}
                    for key in ('keywords', 'exclude'):
                        if key in condition:
                            condition[key] = [x.strip() for x in condition[key].replace('，', ',').split(',') if x.strip()]
                    memory.save_rule(task, condition, approval, selected_rule[0])
            win.destroy(); self.job(work, lambda _: self.refresh())
        bar = ttk.Frame(frame); bar.pack(fill='x', pady=6)
        ttk.Button(bar, text='只保存候选任务', command=lambda: save(False)).pack(side='left')
        ttk.Button(bar, text='保存规则', command=lambda: save(True)).pack(side='left', padx=8)
        listing = tk.Listbox(frame, font=('Microsoft YaHei UI', 10), height=6)
        listing.pack(fill='both', expand=True)
        tasks = {t['id']: t for t in self.tasks}
        for rule in self.rules:
            listing.insert('end', ('启用' if rule['enabled'] and rule['approved'] else '未启用') + ' · ' + tasks[rule['task_id']]['label'] + ' · ' + json.dumps(rule['conditions'], ensure_ascii=False))
        def edit(_):
            if not listing.curselection():
                return
            rule = self.rules[listing.curselection()[0]]
            selected_rule[0] = rule['id']
            task = tasks[rule['task_id']]
            value = {**rule['conditions'], 'label': task['label'], 'category': task['category'], 'task_project': task['project']}
            for key, entry in fields.items():
                entry.delete(0, 'end')
                v = value.get(key, '')
                entry.insert(0, '，'.join(v) if isinstance(v, list) else v)
            approved.set(bool(rule['approved']))
        listing.bind('<<ListboxSelect>>', edit)
        def change(delete=False):
            if not listing.curselection():
                return
            rule = self.rules[listing.curselection()[0]]
            win.destroy()
            self.job(lambda memory: memory.change_rule(rule['id'], None if delete else not rule['enabled']), lambda _: self.refresh())
        bar = ttk.Frame(frame); bar.pack(fill='x', pady=8)
        ttk.Button(bar, text='启用 / 禁用选中规则', command=change).pack(side='left')
        ttk.Button(bar, text='删除选中规则', command=lambda: change(True)).pack(side='left', padx=8)

    def show_history(self):
        self.job(lambda memory: memory.history(), lambda rows: self.text_dialog('近期人工纠正', '\n\n'.join(f"{datetime.fromtimestamp(r['created_ms']/1000):%Y-%m-%d %H:%M} · {r['action']} · {r['label'] or '—'}\n片段 {r['interval_id']}" for r in rows) or '暂无纠正记录'))

    def suggest_rules(self):
        def show(suggestions):
            if not suggestions:
                messagebox.showinfo('规则建议', '还没有至少两次、内容有共同特征的已保存纠正。')
                return
            tasks = {t['id']: t for t in self.tasks}
            win = self.text_dialog('规则建议 · 默认不启用', '\n\n'.join(tasks[s['task_id']]['label'] + '\n' + json.dumps(s['conditions'], ensure_ascii=False) + f"\n依据：{s['examples']} 个已确认案例" for s in suggestions))
            def save():
                win.destroy()
                def work(memory):
                    for suggestion in suggestions:
                        memory.save_rule(suggestion['task_id'], suggestion['conditions'], approved=False, origins=suggestion['origins'])
                self.job(work, lambda _: self.refresh())
            ttk.Button(win, text='保存为未批准规则，稍后在规则管理中审阅', command=save).pack(pady=8)
        self.job(lambda memory: memory.suggestions(), show)

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON', '*.json')], title='导出个人记忆（可能含私人标签，请妥善保存）')
        if path:
            def work(memory):
                Path(path).write_text(json.dumps(memory.export(), ensure_ascii=False, indent=2), encoding='utf-8')
            self.job(work)

    def forget(self):
        if messagebox.askyesno('删除个人记忆', '删除档案、任务、案例、规则、识别和修订。原始采集记录保留。'):
            self.cancel_cloud()
            self.job(lambda memory: memory.forget(), lambda _: self.refresh(load_profile=True))

    def set_key(self):
        win = tk.Toplevel(self.root); win.title('设置服务密钥')
        ttk.Label(win, text='密钥仅写入 Windows Credential Manager', padding=12).pack()
        entry = ttk.Entry(win, show='•', width=55); entry.pack(padx=12, pady=8)
        endpoint = self.endpoint.get().strip()
        def save():
            key = entry.get(); entry.delete(0, 'end'); win.destroy()
            self.job(lambda _: Vault(endpoint).put(key))
        ttk.Button(win, text='保存密钥', command=save).pack(pady=12)

    def delete_key(self):
        endpoint = self.endpoint.get().strip()
        self.cancel_cloud()
        self.job(lambda _: Vault(endpoint).delete())

    def preview_cloud(self):
        ids = self.visible_ids()
        endpoint, model = self.endpoint.get().strip(), self.model.get().strip()
        def show(payload):
            if not payload['candidates']:
                messagebox.showinfo('需要分类', '请先点击“添加分类”；AI 只会选择你提供的分类。')
                return
            if not payload['evidence']:
                messagebox.showinfo('无需发送', '当前批次没有需要云端分析的活动。')
                return
            win = self.text_dialog('本次发送范围 · 确认后才发送', f'服务：{endpoint}\n模型：{model}\n只发送以下档案、候选标签与脱敏文本；不发送截图。每次最多 100 个片段，最多 2 次尝试。\n\n' + json.dumps(payload, ensure_ascii=False, indent=2))
            def send():
                win.destroy()
                try:
                    self.provider = TextProvider(endpoint, model, budget=2)
                except Exception:
                    messagebox.showerror('配置无效', '请填写 HTTPS 接口完整地址与模型名称。'); return
                provider = self.provider
                self.job(lambda memory: Classifier(memory, provider, category_only=True).analyze(ids, payload), lambda _: self.refresh())
            ttk.Button(win, text='仅授权这个批次并发送', command=send).pack(pady=8)
        self.job(lambda memory: Classifier(memory, category_only=True).preview(ids), show)

    def cancel_cloud(self):
        self.hide_preview()
        if self.provider:
            self.provider.cancel()
        self.status.set('云端已取消；已发送的内容无法撤回，迟到结果不接收')

    def close(self):
        self.closed = True
        self.hide_preview()
        self.cancel_cloud()
        self.executor.shutdown(wait=False, cancel_futures=True)
        for timer in self.root.tk.splitlist(self.root.tk.call('after','info')):
            self.root.after_cancel(timer)
        self.root.destroy()


def launch(database):
    root = tk.Tk()
    App(root, database)
    root.mainloop()
