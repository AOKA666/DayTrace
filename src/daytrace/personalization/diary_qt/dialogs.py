"""Qt dialogs for evidence review and confirmation."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..classifier import Classifier
from ..diary_model import duration


class ConfirmDialog(QDialog):
    def __init__(self, parent, title, category, project):
        super().__init__(parent)
        self.setWindowTitle('确认活动')
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('这些片段属于同一件事'))
        form = QFormLayout()
        self.name = QLineEdit(title)
        self.cat = QLineEdit(category)
        self.proj = QLineEdit(project)
        form.addRow('活动名称', self.name)
        form.addRow('分类', self.cat)
        form.addRow('项目', self.proj)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        save = buttons.addButton('确认并记住', QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName('accent')
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def values(self):
        return self.name.text().strip(), self.cat.text().strip(), self.proj.text().strip()


class FragmentDialog(QDialog):
    def __init__(self, parent, card):
        super().__init__(parent)
        self.setWindowTitle(card['title'] + ' · 依据')
        self.card = card
        self.selected_row = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(card['title']))
        layout.addWidget(QLabel('选择片段查看、纠正，或确认整个活动。'))
        self.list = QListWidget()
        for row in card['rows']:
            self.list.addItem(
                f"{datetime.fromtimestamp(row['start_ms']/1000):%H:%M}  "
                f"{duration(row['end_ms']-row['start_ms'])}  "
                f"{row.get('process_name') or '未知'}  {(row.get('title') or '')[:48]}"
            )
        layout.addWidget(self.list)
        row = QHBoxLayout()
        view = QPushButton('查看选中片段')
        view.setObjectName('ghost')
        view.clicked.connect(self._pick)
        confirm = QPushButton('确认整个活动')
        confirm.setObjectName('accent')
        confirm.clicked.connect(self.accept)
        row.addWidget(view)
        row.addStretch()
        row.addWidget(confirm)
        layout.addLayout(row)

    def _pick(self):
        row = self.list.currentRow()
        if row < 0:
            return
        self.selected_row = self.card['rows'][row]
        self.done(2)


class DetailDialog(QDialog):
    def __init__(self, parent, row, evidence, tasks, on_submit):
        super().__init__(parent)
        self.row = row
        self.on_submit = on_submit
        label = row.get('label') or row.get('title') or '待确认'
        self.setWindowTitle(f'活动详情 · {label[:32]}')
        self.setMinimumSize(720, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(row.get('reason') or '请先运行本地分析'))
        layout.addWidget(QLabel(f"应用：{evidence['process_name']}  ·  事件：{evidence['event_id']}"))
        body = QTextEdit()
        body.setReadOnly(True)
        content_status = {
            'no_text': '应用未提供可读正文',
            'partial': '仅取得部分正文',
            'success': '已取得正文',
            'unavailable': '正文不可用 / 未采集',
        }.get(evidence['content_status'], evidence['content_status'])
        image_status = '已保存许可区域截图，可在卡片上悬停预览。' if evidence['has_screenshot'] else '未保存有效截图，无法还原当时屏幕。'
        body.setPlainText(
            f"标题：{evidence['title'] or '原始标题已过期 / 不可用'}\n"
            f"正文状态：{content_status}\n\n{evidence['text'] or '无可用正文，可根据自己的记忆纠正。'}\n\n{image_status}"
        )
        layout.addWidget(body)
        form = QFormLayout()
        self.name = QLineEdit(row.get('label') or '')
        self.cat = QLineEdit(row.get('category') or '')
        self.proj = QLineEdit(row.get('project') or '')
        form.addRow('活动名称', self.name)
        form.addRow('分类', self.cat)
        form.addRow('项目', self.proj)
        layout.addLayout(form)
        self.tasks = QComboBox()
        self.tasks.addItem('从候选任务选择…')
        for task in tasks:
            self.tasks.addItem(task['label'] + ' / ' + task['project'], task)
        self.tasks.currentIndexChanged.connect(self._pick_task)
        layout.addWidget(self.tasks)
        self.remember = QCheckBox('记住这次纠正，作为历史案例（不会自动建立全局规则）')
        layout.addWidget(self.remember)
        bar = QHBoxLayout()
        for text, action in [
            ('确认并保存', 'confirm'),
            ('不知道', 'unknown'),
            ('忽略', 'ignore'),
            ('私人活动', 'private'),
            ('撤销人工结果', 'undo'),
        ]:
            btn = QPushButton(text)
            btn.setObjectName('ghost')
            btn.clicked.connect(lambda checked=False, a=action: self._submit(a))
            bar.addWidget(btn)
        layout.addLayout(bar)
        delete = QPushButton('删除此活动及关联记录')
        delete.setObjectName('ghost')
        delete.clicked.connect(self._delete)
        layout.addWidget(delete, alignment=Qt.AlignmentFlag.AlignRight)

    def _pick_task(self, index):
        if index <= 0:
            return
        task = self.tasks.itemData(index)
        self.name.setText(task['label'])
        self.cat.setText(task['category'])
        self.proj.setText(task['project'])

    def _submit(self, action):
        if action == 'private' and QMessageBox.question(self, '私人活动', '将删除此活动的应用、标题和纠正记录，只保留匿名时间。') != QMessageBox.StandardButton.Yes:
            return
        label, category, project = self.name.text(), self.cat.text(), self.proj.text()
        self.on_submit(action, label, category, project, self.remember.isChecked())
        self.accept()

    def _delete(self):
        if QMessageBox.question(self, '删除活动', '删除该片段及关联证据、修订。') == QMessageBox.StandardButton.Yes:
            self.on_submit('delete', '', '', '', False)
            self.accept()
