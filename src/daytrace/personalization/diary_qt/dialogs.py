"""Qt dialogs for evidence review and confirmation."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..diary_model import duration
from .dialog_kit import add_footer
from .taxonomy_widgets import ClassificationPicker


class ConfirmDialog(QDialog):
    def __init__(self, parent, title, category='', tags=()):
        super().__init__(parent)
        self.setWindowTitle('确认活动')
        self.setObjectName('appleDialog')
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        heading = QLabel('确认活动')
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        name = QLabel(title)
        name.setObjectName('dialogHeading')
        name.setWordWrap(True)
        layout.addWidget(name)
        hint = QLabel('选择分类后即可确认。标签可选；以后遇到相同窗口标题时，会自动套用这次的分类和标签。')
        hint.setObjectName('caption')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.picker = ClassificationPicker(parent, category, tags, self)
        layout.addWidget(self.picker)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 6, 0, 0)
        footer.setSpacing(10)
        footer.addStretch()
        save, _cancel = add_footer(footer, '确认', self)
        layout.addLayout(footer)
        save.setEnabled(bool(self.picker.category.currentData()))
        self.picker.category.currentIndexChanged.connect(lambda: save.setEnabled(bool(self.picker.category.currentData())))

    def values(self):
        return self.picker.values()

    def accept(self):
        if self.picker.category.currentData():
            super().accept()


class FragmentDialog(QDialog):
    def __init__(self, parent, card):
        super().__init__(parent)
        self.setWindowTitle(card['title'] + ' · 依据')
        self.setObjectName('appleDialog')
        self.setMinimumWidth(560)
        self.card = card
        self.selected_row = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        heading = QLabel(card['title'])
        heading.setObjectName('dialogTitle')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        hint = QLabel('选择片段查看、纠正，或确认整个活动。')
        hint.setObjectName('caption')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.list = QListWidget()
        for row in card['rows']:
            self.list.addItem(
                f"{datetime.fromtimestamp(row['start_ms']/1000):%H:%M}  "
                f"{duration(row['end_ms']-row['start_ms'])}  "
                f"{row.get('process_name') or '未知'}  {(row.get('title') or '')[:48]}"
            )
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.setSpacing(10)
        view = QPushButton('查看选中片段')
        view.setObjectName('ghost')
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        view.clicked.connect(self._pick)
        confirm = QPushButton('确认整个活动')
        confirm.setObjectName('accent')
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self.setObjectName('appleDialog')
        self.setMinimumSize(680, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        heading = QLabel(label)
        heading.setObjectName('dialogTitle')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        meta = QLabel(
            (row.get('reason') or '请先运行本地分析')
            + f"\n应用：{evidence['process_name']}  ·  事件：{evidence['event_id']}"
        )
        meta.setObjectName('caption')
        meta.setWordWrap(True)
        layout.addWidget(meta)
        body = QTextEdit()
        body.setObjectName('evidenceBody')
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
        layout.addWidget(body, 1)
        self.picker = ClassificationPicker(parent, row.get('category') or '',
                                            [t['id'] for t in row.get('tags', [])], self)
        layout.addWidget(self.picker)
        secondary = QHBoxLayout()
        secondary.setSpacing(10)
        for text, action in [
            ('不知道', 'unknown'),
            ('忽略', 'ignore'),
            ('私人活动', 'private'),
            ('撤销人工结果', 'undo'),
        ]:
            btn = QPushButton(text)
            btn.setObjectName('ghost')
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, a=action: self._submit(a))
            secondary.addWidget(btn)
        secondary.addStretch()
        layout.addLayout(secondary)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        delete = QPushButton('删除此活动及关联记录')
        delete.setObjectName('danger')
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(self._delete)
        confirm = QPushButton('确认并保存')
        confirm.setObjectName('accent')
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm.clicked.connect(lambda: self._submit('confirm'))
        confirm.setEnabled(bool(self.picker.category.currentData()))
        self.picker.category.currentIndexChanged.connect(
            lambda _index, button=confirm: button.setEnabled(bool(self.picker.category.currentData()))
        )
        bar.addWidget(delete)
        bar.addStretch()
        bar.addWidget(confirm)
        layout.addLayout(bar)

    def _submit(self, action):
        if action == 'confirm' and not self.picker.category.currentData():
            return
        if action == 'private' and QMessageBox.question(self, '私人活动', '将删除此活动的应用、标题和纠正记录，只保留匿名时间。') != QMessageBox.StandardButton.Yes:
            return
        self.on_submit(action, *self.picker.values())
        self.accept()

    def _delete(self):
        if QMessageBox.question(self, '删除活动', '删除该片段及关联证据、修订。') == QMessageBox.StandardButton.Yes:
            self.on_submit('delete', None, [])
            self.accept()
