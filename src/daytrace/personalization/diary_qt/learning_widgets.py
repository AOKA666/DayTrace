"""Plain-language local rule management and AI correction history."""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)



def describe_conditions(conditions):
    names = {'app': '应用是', 'title_exact': '窗口标题相同', 'title': '标题包含',
             'keywords': '内容包含', 'exclude': '排除内容', 'project': '项目包含',
             'context': '上下文包含', 'url_prefix': '网址开头是'}
    parts = []
    for key, value in conditions.items():
        if value:
            parts.append(names.get(key, '条件') + '：' + ('、'.join(value) if isinstance(value, list) else str(value)))
    return '；'.join(parts)


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return widget


def rule_rows(memory):
    tasks = {t['id']: t for t in memory.tasks()}
    return [dict(rule, category=tasks.get(rule['task_id'], {}).get('category') or '未分类') for rule in memory.rules()]


class RulesDialog(QDialog):
    def __init__(self, host, rows):
        super().__init__(host)
        self.host = host
        self.setWindowTitle('自动分类规则')
        self.setObjectName('appleDialog')
        self.resize(840, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        heading = QLabel('自动分类规则')
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        hint = QLabel('规则用于在条件相同时自动沿用分类。例如：某个窗口标题再次出现时，归到你之前选择的分类。\n它与“纠正 AI 错误”是两回事。选中一条规则可启用、停用或删除。')
        hint.setObjectName('caption')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.empty = QLabel('还没有保存的规则。给活动确认分类后，可在这里管理标题匹配规则。')
        self.empty.setObjectName('caption')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.table = table(['匹配条件', '自动归到', '状态'])
        self.table.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.toggle = QPushButton('停用规则')
        self.toggle.setObjectName('ghost')
        self.toggle.clicked.connect(self.toggle_rule)
        self.delete = QPushButton('删除规则')
        self.delete.setObjectName('danger')
        self.delete.clicked.connect(self.delete_rule)
        close = QPushButton('关闭')
        close.setObjectName('accent')
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        bar.addWidget(self.toggle)
        bar.addWidget(self.delete)
        bar.addStretch()
        bar.addWidget(close)
        layout.addLayout(bar)
        self.reload(rows)

    def reload(self, rows):
        self.rows = rows
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [describe_conditions(row['conditions']), row['category'],
                      '待批准' if not row['approved'] else '已启用' if row['enabled'] else '已停用']
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, column, item)
        self.empty.setVisible(not rows)
        self.selection_changed()

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def selection_changed(self):
        row = self.selected()
        self.toggle.setEnabled(row is not None)
        self.delete.setEnabled(row is not None)
        if row:
            self.toggle.setText('批准并启用' if not row['approved'] else '停用规则' if row['enabled'] else '启用规则')

    def apply(self, action):
        def work(memory):
            action(memory)
            return rule_rows(memory)
        def done(rows):
            self.reload(rows)
            self.host.refresh()
        self.host.run_job(work, done)

    def toggle_rule(self):
        row = self.selected()
        if not row:
            return
        def change(memory):
            if not row['approved']:
                with memory.repo.transaction():
                    memory.db.execute('UPDATE learned_rules SET approved=1,enabled=1 WHERE id=?', (row['id'],))
                    memory.invalidate_automatic()
            else:
                memory.change_rule(row['id'], enabled=not row['enabled'])
        self.apply(change)

    def delete_rule(self):
        row = self.selected()
        if row and QMessageBox.question(self, '删除规则', '删除此规则？已由你确认的活动不会被修改。') == QMessageBox.StandardButton.Yes:
            self.apply(lambda memory: memory.change_rule(row['id']))


class CorrectionsDialog(QDialog):
    def __init__(self, host, rows):
        super().__init__(host)
        self.setWindowTitle('AI 纠正记录')
        self.setObjectName('appleDialog')
        self.resize(840, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        heading = QLabel('AI 纠正记录')
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        hint = QLabel('这里只记录：AI 已给出分类，你把它改成另一个分类。\n给未识别活动选择分类、确认 AI 原分类或添加标签，都不算 AI 纠正。')
        hint.setObjectName('caption')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        if not rows:
            empty = QLabel('目前没有可确认的 AI 纠正记录。旧记录未保存修改前的判断，不计入这里。')
            empty.setObjectName('caption')
            empty.setWordWrap(True)
            layout.addWidget(empty)
        self.table = table(['纠正时间', '活动', 'AI 原分类', '你改为'])
        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            values = [datetime.fromtimestamp(row['created_ms'] / 1000).strftime('%m-%d %H:%M'),
                      row['label'], row['previous_category'], row['category']]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        bar.addStretch()
        close = QPushButton('关闭')
        close.setObjectName('accent')
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        layout.addLayout(bar)
