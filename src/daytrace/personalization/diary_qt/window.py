"""PySide6 diary main window."""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..classifier import Classifier
from ..diary_model import DEFAULT_CATEGORIES, build_display_cards, cards, overview
from ..diary_worker import review, tick
from ...preferences import diary_display_ms, options, save_dwell, save_options, show_short_dwells, validate_dwell
from ..profile import propose_profile
from ..provider import DEEPSEEK_ENDPOINT, DEEPSEEK_MODEL, TextProvider, Vault
from ..store import Memory, PersonalizationUpgradeBlocked
from ..category_palette import PALETTE, bootstrap_category_colors
from .capture_sync import read_capture_state, repo_root
from .categories import CategoriesPanel
from .dialogs import ConfirmDialog, DetailDialog, FragmentDialog
from .jobs import CaptureBridge, JobBridge
from .theme import ACCENT, BG, BORDER, MUTED, NAV_ITEMS, SURFACE
from .timeline import TimelineWidget


class DiaryMainWindow(QMainWindow):
    def __init__(self, database: Path, preview_mode=False):
        super().__init__()
        self.database = database
        self.preview_mode = preview_mode
        self.page = '今日'
        self.only_review = False
        self.all_cards: list = []
        self.rows: dict = {}
        self.tasks: list = []
        self.rules: list = []
        self.category_colors: dict = {}
        self.busy = False
        self.closed = False
        self.recording = 'stopped'
        self.ai_future = None
        self.ai_cancel = None
        self.review_cache = None
        self.next_ai = 0
        self.collector_process = None
        self.hover_id = ''
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='daytrace-qt')
        self._capture_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='daytrace-qt-capture')
        self.ai_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='daytrace-qt-ai')
        self._job_bridge = JobBridge(self)
        self._job_bridge.finished.connect(self._complete_job)
        self._capture_bridge = CaptureBridge(self)
        self._capture_bridge.state_ready.connect(self._apply_capture_state)
        self._capture_sync_pending = False
        self.preview_popup = None

        self.setWindowTitle('DayTrace · AI 时间日记' + (' · 合成示例' if preview_mode else ''))
        self.setMinimumSize(1080, 680)
        self.resize(1320, 820)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QFrame()
        side.setFixedWidth(168)
        side.setStyleSheet(f'background:{BG}; border-right:1px solid {BORDER};')
        side_col = QVBoxLayout(side)
        side_col.setContentsMargins(12, 18, 12, 18)
        side_col.setSpacing(6)
        brand = QLabel('DayTrace')
        brand.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        side_col.addWidget(brand)
        sub = QLabel('时间日记')
        sub.setObjectName('caption')
        side_col.addWidget(sub)
        side_col.addSpacing(18)
        self.nav_buttons: dict[str, QPushButton] = {}
        for name, symbol in NAV_ITEMS:
            btn = QPushButton(f'  {symbol}   {name}')
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, n=name: self.navigate(n))
            side_col.addWidget(btn)
            self.nav_buttons[name] = btn
        side_col.addStretch()
        side_col.addWidget(QLabel('本地保存\n随时纠正'))
        outer.addWidget(side)

        main = QVBoxLayout()
        main.setContentsMargins(22, 16, 22, 18)
        main.setSpacing(10)
        main_col = QWidget()
        main_col.setLayout(main)
        outer.addWidget(main_col, stretch=1)

        top = QHBoxLayout()
        self.heading = QLabel('今天')
        self.heading.setObjectName('title')
        top.addWidget(self.heading)
        top.addStretch()
        self.capture_state = QLabel('未开始记录')
        self.capture_state.setObjectName('caption')
        top.addWidget(self.capture_state)
        self.capture_button = QPushButton('开始记录')
        self.capture_button.setObjectName('accent')
        self.capture_button.clicked.connect(self.toggle_capture)
        top.addWidget(self.capture_button)
        main.addLayout(top)

        tool = QHBoxLayout()
        date_capsule = QFrame()
        date_capsule.setObjectName('dateCapsule')
        date_row = QHBoxLayout(date_capsule)
        date_row.setContentsMargins(8, 4, 8, 4)
        prev = QPushButton('‹')
        prev.setObjectName('ghost')
        prev.setFixedWidth(36)
        prev.clicked.connect(lambda: self.shift_day(-1))
        self.date = QLineEdit(datetime.now().strftime('%Y-%m-%d'))
        self.date.setFixedWidth(108)
        self.date.returnPressed.connect(self.refresh)
        nxt = QPushButton('›')
        nxt.setObjectName('ghost')
        nxt.setFixedWidth(36)
        nxt.clicked.connect(lambda: self.shift_day(1))
        date_row.addWidget(prev)
        date_row.addWidget(self.date)
        date_row.addWidget(nxt)
        tool.addWidget(date_capsule)
        tool.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText('筛选活动、分类、项目')
        self.search.setFixedWidth(176)
        self.search.textChanged.connect(self.filter_cards)
        tool.addWidget(self.search)
        self.pending_btn = QPushButton('待确认 0')
        self.pending_btn.setObjectName('ghost')
        self.pending_btn.clicked.connect(self.toggle_review)
        tool.addWidget(self.pending_btn)
        main.addLayout(tool)

        self.stack = QStackedWidget()
        main.addWidget(self.stack, stretch=1)

        timeline_page = QWidget()
        tl = QVBoxLayout(timeline_page)
        tl.setSpacing(10)
        summary = QFrame()
        summary.setObjectName('summaryCard')
        sum_col = QVBoxLayout(summary)
        sum_col.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        head.addWidget(QLabel('今日概览'))
        head.addStretch()
        self.summary_toggle = QPushButton('收起')
        self.summary_toggle.setObjectName('ghost')
        self.summary_toggle.clicked.connect(self.collapse_summary)
        head.addWidget(self.summary_toggle)
        sum_col.addLayout(head)
        self.summary_label = QLabel('活动还在整理中。')
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName('caption')
        sum_col.addWidget(self.summary_label)
        tl.addWidget(summary)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timeline = TimelineWidget()
        scroll.setWidget(self.timeline)
        tl.addWidget(scroll, stretch=1)
        self.stack.addWidget(timeline_page)

        settings_page = QWidget()
        set_outer = QVBoxLayout(settings_page)
        set_outer.setContentsMargins(0, 8, 0, 12)
        set_outer.setSpacing(14)
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(4, 0, 4, 0)
        tab_row.setSpacing(8)
        self.settings_stack = QStackedWidget()
        self.settings_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.settings_tabs: dict[str, QPushButton] = {}
        labels = ['我的日常', '当前项目', '分类颜色', '识别与学习', '采集与隐私', '模型与高级']
        self.settings_pages: dict[str, QVBoxLayout] = {}
        for label in labels:
            btn = QPushButton(label)
            btn.setObjectName('ghost')
            btn.clicked.connect(lambda checked=False, name=label: self.show_settings(name))
            tab_row.addWidget(btn)
            self.settings_tabs[label] = btn
            page = QWidget()
            scroll_s = QScrollArea()
            scroll_s.setWidgetResizable(True)
            scroll_s.setFrameShape(QFrame.Shape.NoFrame)
            scroll_s.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll_s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            inner = QWidget()
            body = QVBoxLayout(inner)
            body.setContentsMargins(20, 16, 24, 28)
            body.setSpacing(16)
            inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            scroll_s.setWidget(inner)
            wrap = QVBoxLayout(page)
            wrap.setContentsMargins(0, 0, 0, 0)
            wrap.setSpacing(0)
            wrap.addWidget(scroll_s)
            self.settings_stack.addWidget(page)
            self.settings_pages[label] = body
        tab_row.addStretch(1)
        set_outer.addLayout(tab_row)
        set_outer.addWidget(self.settings_stack, 1)
        self.stack.addWidget(settings_page)
        self._build_settings()
        self.show_settings('我的日常')

        self.timeline.card_clicked.connect(self.open_card)
        self.timeline.card_confirm.connect(self.quick_confirm)
        self.timeline.card_hovered.connect(self.on_hover_id)

        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self.sync_capture_state)
        self._capture_timer.start(2000)
        self._ai_timer = QTimer(self)
        self._ai_timer.timeout.connect(self._run_ai_tick)
        self._ai_timer.start(2000)

        if preview_mode:
            self.capture_button.setEnabled(False)
        else:
            QTimer.singleShot(0, self.sync_capture_state)

        self.refresh(load_profile=True)
        self.navigate('今日', refresh=False)

    def _settings_panel(self, page_key: str, title: str) -> QVBoxLayout:
        page = self.settings_pages[page_key]
        panel = QFrame()
        panel.setObjectName('settingsPanel')
        panel.setMinimumWidth(280)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        inner = QVBoxLayout(panel)
        inner.setContentsMargins(24, 22, 24, 24)
        inner.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName('sectionTitle')
        inner.addWidget(heading)
        page.addWidget(panel, 1)
        page.addStretch(1)
        return inner

    def _settings_field(self, parent: QVBoxLayout, label: str) -> QLineEdit:
        cap = QLabel(label)
        cap.setObjectName('fieldLabel')
        parent.addWidget(cap)
        entry = QLineEdit()
        entry.setObjectName('settingsField')
        entry.setMinimumWidth(280)
        entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        parent.addWidget(entry)
        return entry

    def _build_settings(self):
        daily = self._settings_panel('我的日常', '个人档案')
        hint = QLabel('用几句话描述日常，帮助识别活动。字段不必一次填完。')
        hint.setObjectName('caption')
        hint.setWordWrap(True)
        daily.addWidget(hint)
        self.description = QTextEdit()
        self.description.setObjectName('settingsArea')
        self.description.setMaximumHeight(96)
        self.description.setMinimumWidth(280)
        self.description.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        daily.addWidget(self.description)
        btn_row = QHBoxLayout()
        propose = QPushButton('生成日常建议')
        propose.setObjectName('ghost')
        propose.clicked.connect(self.propose)
        btn_row.addWidget(propose)
        btn_row.addStretch()
        daily.addLayout(btn_row)
        self.fields: dict[str, QLineEdit] = {}
        for key, label in [
            ('activities', '活动分类（逗号分隔）'),
            ('hours', '常用时间（可选）'),
            ('workflow', '活动说明（可选）'),
        ]:
            self.fields[key] = self._settings_field(daily, label)
        actions = QHBoxLayout()
        save_d = QPushButton('保存个人档案')
        save_d.setObjectName('accent')
        save_d.clicked.connect(self.save_profile)
        actions.addWidget(save_d)
        actions.addStretch()
        daily.addLayout(actions)

        projects = self._settings_panel('当前项目', '项目与环境')
        for key, label in [('projects', '项目名称（逗号分隔）'), ('software', '常用软件'), ('websites', '常用网站')]:
            self.fields[key] = self._settings_field(projects, label)
        save_p = QPushButton('保存个人档案')
        save_p.setObjectName('accent')
        save_p.clicked.connect(self.save_profile)
        projects.addWidget(save_p)

        cats = self._settings_panel('分类颜色', '分类与颜色')
        self.categories_panel = CategoriesPanel(self)
        self.categories_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        cats.addWidget(self.categories_panel)

        learning = self._settings_panel('识别与学习', 'AI 与记忆')
        sub = QLabel('默认不联网；开启后在本窗口内分批整理新活动。')
        sub.setObjectName('caption')
        sub.setWordWrap(True)
        learning.addWidget(sub)
        self.auto_ai = QCheckBox('允许后台 AI 分析新活动')
        self.auto_ai.toggled.connect(self.toggle_ai)
        learning.addWidget(self.auto_ai)
        self.ai_note = QLabel('未开启 · 无云端发送')
        self.ai_note.setObjectName('caption')
        self.ai_note.setWordWrap(True)
        learning.addWidget(self.ai_note)
        learning.addSpacing(4)
        tool_col = QVBoxLayout()
        tool_col.setSpacing(8)
        for text, slot in [
            ('重试待识别活动', self.retry_ai),
            ('管理学习规则', self.rule_dialog),
            ('查看纠正记录', self.show_history),
            ('查看规则建议', self.suggest_rules),
            ('导出个人记忆', self.export),
            ('删除个人记忆', self.forget),
        ]:
            btn = QPushButton(text)
            btn.setObjectName('ghost')
            btn.clicked.connect(slot)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            tool_col.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        tool_col.addStretch(1)
        learning.addLayout(tool_col)

        privacy = self._settings_panel('采集与隐私', '采集与截图')
        note = QLabel('停留阈值在下次启动采集时生效；截图遵循排除与 7 天本地保留。')
        note.setObjectName('caption')
        note.setWordWrap(True)
        privacy.addWidget(note)
        privacy.addWidget(QLabel('短暂停留阈值（秒）'))
        self.dwell = QLineEdit('5')
        self.dwell.setObjectName('settingsField')
        self.dwell.setMaximumWidth(88)
        privacy.addWidget(self.dwell)
        t = QPushButton('保存采集与日记显示')
        t.setObjectName('ghost')
        t.clicked.connect(self.save_capture_preferences)
        privacy.addWidget(t)
        self.capture_enabled = QCheckBox('开启本地截图证据')
        self.capture_enabled.toggled.connect(self.save_screenshots)
        privacy.addWidget(self.capture_enabled)
        privacy.addSpacing(8)
        privacy.addWidget(QLabel('日记合并间隔（秒）'))
        self.merge_gap = QLineEdit('180')
        self.merge_gap.setObjectName('settingsField')
        self.merge_gap.setMaximumWidth(88)
        privacy.addWidget(self.merge_gap)
        privacy.addWidget(QLabel('折叠短空隙（秒）'))
        self.fold_gap = QLineEdit('120')
        self.fold_gap.setObjectName('settingsField')
        self.fold_gap.setMaximumWidth(88)
        privacy.addWidget(self.fold_gap)
        self.show_short_dwells = QCheckBox('显示短暂停留（默认关，仅看主要活动）')
        self.show_short_dwells.toggled.connect(self._save_show_short_dwells)
        privacy.addWidget(self.show_short_dwells)

        advanced = self._settings_panel('模型与高级', '模型连接')
        adv = QLabel('密钥仅存于 Windows Credential Manager。')
        adv.setObjectName('caption')
        advanced.addWidget(adv)
        self.endpoint = self._settings_field(advanced, '服务地址')
        self.endpoint.setText(DEEPSEEK_ENDPOINT)
        self.model = self._settings_field(advanced, '模型名称')
        self.model.setText(DEEPSEEK_MODEL)
        for text, slot in [
            ('保存模型配置', self.save_model),
            ('设置密钥', self.set_key),
            ('删除密钥', self.delete_key),
        ]:
            b = QPushButton(text)
            b.setObjectName('ghost')
            b.clicked.connect(slot)
            advanced.addWidget(b)

    def _style_nav(self):
        for name, btn in self.nav_buttons.items():
            btn.setObjectName('navActive' if name == self.page else 'nav')
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def show_settings(self, name):
        index = list(self.settings_pages).index(name)
        self.settings_stack.setCurrentIndex(index)
        for label, btn in self.settings_tabs.items():
            btn.setObjectName('navActive' if label == name else 'ghost')
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def navigate(self, page, refresh=True):
        self.page = page
        self.only_review = False
        self._style_nav()
        self.stack.setCurrentIndex(0 if page != '设置' else 1)
        self.heading.setText({'今日': '今天', '历史记录': '历史', 'AI 复盘': '复盘'}.get(page, '今天'))
        if page == '今日':
            self.date.setText(datetime.now().strftime('%Y-%m-%d'))
        if page == 'AI 复盘':
            self.summary_label.show()
        if refresh:
            self.refresh()

    def shift_day(self, delta):
        try:
            day = datetime.strptime(self.date.text(), '%Y-%m-%d') + timedelta(days=delta)
        except ValueError:
            return
        self.date.setText(day.strftime('%Y-%m-%d'))
        self.refresh()

    def collapse_summary(self):
        hidden = not self.summary_label.isVisible()
        self.summary_label.setVisible(hidden)
        self.summary_toggle.setText('展开' if not hidden else '收起')

    def toggle_review(self):
        self.only_review = not self.only_review
        extra = ' · 仅看待确认' if self.only_review else ''
        count = sum(c['review'] for c in self.all_cards)
        self.pending_btn.setText(f'待确认 {count}{extra}')
        self.filter_cards()

    def run_job(self, fn, callback=None, quiet=False):
        if self.busy:
            if not quiet:
                QMessageBox.information(self, '正在处理', '请等待当前操作完成。')
            return

        def work():
            memory = Memory(self.database, cleanup=not quiet)
            try:
                return fn(memory)
            finally:
                memory.close()

        self.busy = True
        future = self.executor.submit(work)
        future.add_done_callback(lambda f: self._job_bridge.finished.emit(f, callback, quiet))

    def _complete_job(self, future, callback, quiet):
        """Runs on the GUI thread via JobBridge.finished (never call QTimer from a worker)."""
        self.busy = False
        try:
            value = future.result()
            if callback:
                callback(value)
        except PersonalizationUpgradeBlocked as error:
            QMessageBox.warning(self, '需要先停止采集', str(error))
        except Exception:
            if not quiet:
                QMessageBox.critical(self, '操作未完成', '请检查数据库状态；隐私操作前请停止采集。')

    def refresh(self, load_profile=False, quiet=False):
        try:
            day = datetime.strptime(self.date.text(), '%Y-%m-%d')
        except ValueError:
            if not quiet:
                QMessageBox.critical(self, '日期', '请输入 YYYY-MM-DD')
            return
        start = int(day.timestamp() * 1000)
        end = int((day + timedelta(days=1)).timestamp() * 1000)

        def read(memory):
            raw = [dict(r, start_ms=max(start, r['start_ms']), end_ms=min(end, r['end_ms'])) for r in memory.timeline(start, end)]
            dwell_ms, merge_ms, fold_ms = diary_display_ms(self.database)
            items = build_display_cards(
                raw,
                dwell_ms,
                merge_ms,
                fold_ms,
                show_short_dwells=show_short_dwells(self.database),
            )
            return raw, items, memory.profile(), memory.tasks(), memory.rules(), options(self.database)

        def show(data):
            raw, items, profile, self.tasks, self.rules, config = data
            self.rows = {r['interval_id']: r for r in raw}
            activities = profile.get('activities') or list(DEFAULT_CATEGORIES)
            self.category_colors = bootstrap_category_colors(self.database, activities)
            self.all_cards = items
            text = overview(items)
            if self.review_cache:
                current = {
                    r['interval_id']: (r['label'], r['category'], r['project'], (r['end_ms'] - r['start_ms']) // 1000, r['reliability'], r['revision'])
                    for r in rows
                    if r['state'] == 'active'
                }
                if all(current.get(i) == v for i, v in self.review_cache['facts'].items()):
                    text = 'AI 复盘 · 已授权活动（最多 100 段）\n' + self.review_cache['text']
                else:
                    self.review_cache = None
            self.summary_label.setText(text)
            count = sum(c['review'] for c in items)
            self.pending_btn.setText(f'待确认 {count}' + (' · 仅看待确认' if self.only_review else ''))
            self.filter_cards()
            if load_profile:
                if not profile['activities']:
                    profile = dict(profile, activities=list(DEFAULT_CATEGORIES))
                self.fill_profile(profile)
                self.dwell.setText(str(config.get('min_dwell_seconds', 5)))
                self.merge_gap.setText(str(config.get('diary_merge_gap_seconds', 180)))
                self.fold_gap.setText(str(config.get('diary_fold_gap_seconds', 120)))
                self.show_short_dwells.blockSignals(True)
                self.show_short_dwells.setChecked(config.get('show_short_dwells') is True)
                self.show_short_dwells.blockSignals(False)
                self.capture_enabled.setChecked(config.get('screenshots_enabled') is True)
                self.auto_ai.setChecked(config.get('auto_ai') is True)
                if config.get('ai_endpoint'):
                    self.endpoint.setText(config['ai_endpoint'])
                if config.get('ai_model'):
                    self.model.setText(config['ai_model'])
            self.categories_panel.set_categories(
                profile.get('activities') or list(DEFAULT_CATEGORIES),
                self.category_colors,
            )

        self.run_job(read, show, quiet=quiet)

    def filter_cards(self):
        query = self.search.text().strip().casefold()
        shown = [
            c
            for c in self.all_cards
            if (not self.only_review or c['review'])
            and (not query or query in (c['title'] + ' ' + c['category'] + ' ' + c['project']).casefold())
        ]
        self.timeline.set_cards(shown, self.category_colors)

    def quick_confirm(self, card):
        if card['rows'][0]['state'] != 'active':
            return
        self.confirm_cards([card])

    def open_card(self, card):
        if len(card['rows']) == 1:
            row = card['rows'][0]
            if row['state'] != 'active':
                QMessageBox.information(self, '时间记录', card['description'])
                return
            self.run_job(lambda m: m.evidence(row['interval_id']), lambda ev: self._detail(row, ev))
            return
        dialog = FragmentDialog(self, card)
        code = dialog.exec()
        if code == 2 and dialog.selected_row:
            row = dialog.selected_row
            self.run_job(lambda m: m.evidence(row['interval_id']), lambda ev: self._detail(row, ev))
        elif code == QDialog.DialogCode.Accepted:
            self.confirm_cards([card])

    def confirm_cards(self, items):
        dialog = ConfirmDialog(self, items[0]['title'], items[0]['category'], items[0]['project'])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        label, category, project = dialog.values()
        if not label:
            return
        ids = [r['interval_id'] for item in items for r in item['rows']]

        def work(memory):
            Classifier(memory).analyze(ids)
            memory.feedback_many(ids, label, category, project, remember=True)

        self.ai_cancel and self.ai_cancel.set()
        self.review_cache = None
        self.run_job(work, lambda _: self.refresh())

    def _detail(self, row, evidence):
        if not evidence:
            QMessageBox.information(self, '证据不可用', '活动尚未结束或证据已删除。')
            return

        def submit(action, label, category, project, remember):
            def work(memory):
                if action == 'delete':
                    memory.delete_interval(row['interval_id'])
                    memory.repo.cleanup(memory.now())
                    return
                Classifier(memory).analyze([row['interval_id']])
                memory.feedback(row['interval_id'], label, category, project, action, remember)
                memory.repo.cleanup(memory.now())

            self.ai_cancel and self.ai_cancel.set()
            self.review_cache = None
            self.run_job(work, lambda _: self.refresh())

        DetailDialog(self, row, evidence, self.tasks, submit).exec()

    def fill_profile(self, profile):
        self.description.setPlainText(profile.get('description', ''))
        for key, entry in self.fields.items():
            value = profile.get(key, '')
            entry.setText('，'.join(value) if isinstance(value, list) else str(value))

    def propose(self):
        self.fill_profile(propose_profile(self.description.toPlainText()))

    def save_profile(self):
        profile = {'description': self.description.toPlainText()}
        for key, entry in self.fields.items():
            value = entry.text()
            profile[key] = (
                [x.strip() for x in value.replace('，', ',').split(',') if x.strip()]
                if key in ('activities', 'projects', 'software', 'websites')
                else value
            )
        self.run_job(lambda m: m.save_profile(profile), lambda _: self.refresh())

    def _save_show_short_dwells(self, enabled):
        if self.busy:
            self.show_short_dwells.blockSignals(True)
            self.show_short_dwells.setChecked(not enabled)
            self.show_short_dwells.blockSignals(False)
            return
        self.run_job(
            lambda _m: save_options(self.database, show_short_dwells=enabled),
            lambda _: self.refresh(),
        )

    def save_capture_preferences(self):
        try:
            dwell = validate_dwell(self.dwell.text())
            merge = max(0, min(600, int(self.merge_gap.text().strip() or 180)))
            fold = max(0, min(600, int(self.fold_gap.text().strip() or 120)))
        except (TypeError, ValueError):
            QMessageBox.critical(self, '采集与日记显示', '停留阈值须在 0–300 秒；合并/折叠间隔须为 0–600 的整数。')
            return

        def work(_memory):
            save_dwell(self.database, dwell)
            save_options(
                self.database,
                min_dwell_seconds=dwell,
                diary_merge_gap_seconds=merge,
                diary_fold_gap_seconds=fold,
            )

        def done(_):
            self.refresh(load_profile=True)
            QMessageBox.information(self, '已保存', '偏好已写入；当前日期时间线已按新阈值重新展示。\n下次启动采集时，停留阈值同时作用于采集器。')

        self.run_job(work, done)

    def save_screenshots(self):
        self.run_job(lambda m: save_options(self.database, screenshots_enabled=self.capture_enabled.isChecked()))

    def save_model(self):
        endpoint, model = self.endpoint.text().strip(), self.model.text().strip()
        try:
            TextProvider(endpoint, model)
        except Exception:
            QMessageBox.critical(self, '模型配置', '请输入有效的 HTTPS 地址和模型名称。')
            return
        self.auto_ai.setChecked(False)
        self.run_job(
            lambda m: save_options(self.database, ai_endpoint=endpoint, ai_model=model, auto_ai=False),
            lambda _: self.ai_note.setText('模型配置已保存，请重新开启后台分析。'),
        )

    def toggle_ai(self, enabled):
        if self.preview_mode:
            self.auto_ai.setChecked(False)
            return
        if self.busy:
            self.auto_ai.setChecked(not enabled)
            return
        if enabled and QMessageBox.question(
            self,
            '开启后台 AI 分析',
            f'发送到：{self.endpoint.text().strip()}\n模型：{self.model.text().strip()}\n'
            '将发送开启后产生的活动标题与脱敏正文；不发送截图。\n是否开启？',
        ) != QMessageBox.StandardButton.Yes:
            self.auto_ai.setChecked(False)
            return
        since = time.time_ns() // 1_000_000
        self.run_job(
            lambda m: save_options(
                self.database,
                auto_ai=enabled,
                ai_since_ms=since,
                ai_endpoint=self.endpoint.text().strip(),
                ai_model=self.model.text().strip(),
            ),
            lambda _: self.ai_note.setText('已开启 · 后台批量整理新活动' if enabled else '已关闭 · 无云端发送'),
        )
        self.next_ai = 0
        self.review_cache = None

    def retry_ai(self):
        self.next_ai = 0
        self.ai_note.setText('将在下一轮重试授权范围内的待识别活动。')

    def category_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('添加分类')
        lay = QVBoxLayout(dialog)
        name = QLineEdit()
        lay.addWidget(QLabel('分类名称'))
        lay.addWidget(name)
        chosen = {'color': PALETTE[0]}
        row = QHBoxLayout()
        for color in PALETTE:
            b = QPushButton('●')
            b.setStyleSheet(f'background:{color}; color:white; border-radius:8px;')
            b.clicked.connect(lambda checked=False, c=color: chosen.update(color=c))
            row.addWidget(b)
        lay.addLayout(row)
        ok = QPushButton('保存分类')
        ok.setObjectName('accent')

        def save():
            label = name.text().strip()
            if not label:
                return
            dialog.accept()
            self.run_job(lambda m: m.add_category(label, chosen['color']), lambda _: self.refresh())

        ok.clicked.connect(save)
        lay.addWidget(ok)
        dialog.exec()

    def rule_dialog(self):
        QMessageBox.information(
            self,
            '学习规则',
            '完整规则编辑界面仍可通过 `daytrace.py ui --tk-diary` 打开 Tk 壳。\n'
            '此处仅列出已有规则数量：' + str(len(self.rules)),
        )

    def show_history(self):
        def show(rows):
            text = '\n\n'.join(
                f"{datetime.fromtimestamp(r['created_ms']/1000):%Y-%m-%d %H:%M} · {r['action']} · {r['label'] or '—'}\n片段 {r['interval_id']}"
                for r in rows
            ) or '暂无纠正记录'
            QMessageBox.information(self, '近期人工纠正', text)

        self.run_job(lambda m: m.history(), show)

    def suggest_rules(self):
        def show(suggestions):
            if not suggestions:
                QMessageBox.information(self, '规则建议', '还没有足够多、内容相似的已保存纠正。')
                return
            tasks = {t['id']: t for t in self.tasks}
            text = '\n\n'.join(
                tasks[s['task_id']]['label'] + '\n' + json.dumps(s['conditions'], ensure_ascii=False)
                for s in suggestions
            )
            if QMessageBox.question(self, '保存为未批准规则？', text[:1200]) == QMessageBox.StandardButton.Yes:

                def work(memory):
                    for s in suggestions:
                        memory.save_rule(s['task_id'], s['conditions'], approved=False, origins=s['origins'])

                self.run_job(work, lambda _: self.refresh())

        self.run_job(lambda m: m.suggestions(), show)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出个人记忆', '', 'JSON (*.json)')
        if not path:
            return
        self.run_job(lambda m: Path(path).write_text(json.dumps(m.export(), ensure_ascii=False, indent=2), encoding='utf-8'))

    def forget(self):
        if QMessageBox.question(self, '删除个人记忆', '删除档案、任务、案例和规则；原始采集保留。') == QMessageBox.StandardButton.Yes:
            self.review_cache = None
            self.run_job(lambda m: m.forget(), lambda _: self.refresh())

    def set_key(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('设置服务密钥')
        lay = QVBoxLayout(dialog)
        entry = QLineEdit()
        entry.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(QLabel('密钥仅写入 Windows Credential Manager'))
        lay.addWidget(entry)
        ok = QPushButton('保存密钥')
        ok.setObjectName('accent')
        endpoint = self.endpoint.text().strip()

        def save():
            key = entry.text()
            entry.clear()
            dialog.accept()
            self.run_job(lambda m: Vault(endpoint).put(key))

        ok.clicked.connect(save)
        lay.addWidget(ok)
        dialog.exec()

    def delete_key(self):
        self.review_cache = None
        self.run_job(lambda m: Vault(self.endpoint.text().strip()).delete())

    def _update_capture_chrome(self, state: str) -> None:
        self.recording = state
        self.capture_state.setText({'running': '正在记录', 'paused': '已暂停', 'stopped': '未开始记录'}[state])
        self.capture_button.setText({'running': '暂停', 'paused': '恢复', 'stopped': '开始记录'}[state])

    def _apply_capture_state(self, state: str) -> None:
        self._update_capture_chrome(state)
        if state != 'stopped' and self.collector_process and self.collector_process.poll() is not None:
            self.collector_process = None
        self._capture_sync_pending = False

    def sync_capture_state(self) -> None:
        if self.preview_mode or self.closed or self.busy or self._capture_sync_pending:
            return
        self._capture_sync_pending = True

        future = self._capture_executor.submit(read_capture_state, self.database)

        def done(fut) -> None:
            try:
                self._capture_bridge.state_ready.emit(fut.result())
            except Exception:
                self._capture_sync_pending = False

        future.add_done_callback(done)

    def _sync_capture_state_blocking(self) -> str:
        state = read_capture_state(self.database)
        self._update_capture_chrome(state)
        return state

    def toggle_capture(self) -> None:
        if self.preview_mode:
            return
        self.review_cache = None
        state = self._sync_capture_state_blocking()
        if state == 'running':
            command = 'pause'
        elif state == 'paused':
            command = 'resume'
        else:
            if QMessageBox.question(
                self, '开始记录', '记录前台应用、窗口标题和可读正文。现在开始？'
            ) != QMessageBox.StandardButton.Yes:
                return
            state = self._sync_capture_state_blocking()
            if state != 'stopped':
                QMessageBox.information(
                    self,
                    '已在记录',
                    '检测到该数据库已有采集进程在运行（例如在终端中 daytrace.py start）。\n'
                    '界面已同步为当前状态，不会启动第二个实例。',
                )
                return
            import subprocess

            source_root = repo_root()
            script = source_root / 'daytrace.py'
            entry = [str(script)] if script.is_file() else ['-m', 'daytrace']
            launch = dict(cwd=str(source_root), stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            if sys.platform == 'win32':
                launch['creationflags'] = subprocess.CREATE_NO_WINDOW
            self.collector_process = subprocess.Popen(
                [sys.executable, *entry, '--db', str(self.database), 'start', '--content'],
                **launch,
            )
            time.sleep(0.35)
            code = self.collector_process.poll()
            if code is not None:
                err = (self.collector_process.stderr.read() if self.collector_process.stderr else '') or ''
                out = (self.collector_process.stdout.read() if self.collector_process.stdout else '') or ''
                detail = (err + out).strip()[:600] or f'进程已退出，代码 {code}'
                QMessageBox.critical(
                    self,
                    '无法启动采集',
                    '采集未启动，常见原因是该数据库已被另一个 start 占用。\n\n' + detail,
                )
                self.collector_process = None
            self._sync_capture_state_blocking()
            return

        from ...cli import control

        def work(_memory):
            control(self.database, command)

        self.run_job(work, lambda _: self._sync_capture_state_blocking())

    def on_hover_id(self, interval_id):
        self.hover_id = interval_id

    def _run_ai_tick(self) -> None:
        if self.closed or self.preview_mode:
            return
        if self.ai_future and self.ai_future.done():
            try:
                result = self.ai_future.result()
                if result.get('note'):
                    self.ai_note.setText(result['note'])
                if result.get('cooldown'):
                    self.next_ai = time.monotonic() + result['cooldown']
                if result.get('review') and result['review'].get('text'):
                    self.review_cache = result['review']
                    if not self.busy:
                        self.refresh(quiet=True)
                if not hasattr(self, 'loaded_preferences') and result.get('options'):
                    config = result['options']
                    self.loaded_preferences = True
                    self.auto_ai.setChecked(config.get('auto_ai') is True)
                    if config.get('ai_endpoint'):
                        self.endpoint.setText(config['ai_endpoint'])
                    if config.get('ai_model'):
                        self.model.setText(config['ai_model'])
            except Exception:
                self.ai_note.setText('后台整理暂不可用，原始记录已保留。')
            self.ai_future = None
        if self.ai_future is None and not self.busy and not self.preview_mode:
            self.ai_cancel = threading.Event()
            analyze = time.monotonic() >= self.next_ai
            if analyze:
                self.next_ai = time.monotonic() + 60
            try:
                day = datetime.strptime(self.date.text(), '%Y-%m-%d')
            except ValueError:
                day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            start = int(day.timestamp() * 1000)
            end = int((day + timedelta(days=1)).timestamp() * 1000)
            previous = self.review_cache['key'] if self.review_cache else None
            cancel = self.ai_cancel

            def work():
                result = tick(self.database, cancel, analyze)
                if analyze and not result.get('cooldown'):
                    result['review'] = review(self.database, cancel, start, end, previous)
                return result

            self.ai_future = self.ai_executor.submit(work)

    def closeEvent(self, event):
        self.closed = True
        self._capture_timer.stop()
        self._ai_timer.stop()
        if self.collector_process and self.collector_process.poll() is None:
            from ...cli import control

            try:
                control(self.database, 'stop')
            except Exception:
                QMessageBox.warning(self, '尚未退出', '停止采集未成功，请稍后重试退出。')
                event.ignore()
                return
        self.ai_executor.shutdown(wait=False, cancel_futures=True)
        self._capture_executor.shutdown(wait=False, cancel_futures=True)
        self.executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


def run_app(database: Path, preview_mode=False):
    app = QApplication.instance() or QApplication(sys.argv)
    from .theme import STYLESHEET

    app.setStyleSheet(STYLESHEET)
    window = DiaryMainWindow(database, preview_mode=preview_mode)
    window.show()
    return app, window
