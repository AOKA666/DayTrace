"""Settings UI for user-defined activity categories and colors."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..category_palette import PALETTE, contrasting_text


class CategoriesPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.names: list[str] = []
        self.colors: dict[str, str] = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        hint = QLabel('为活动分类指定颜色，时间线以色块标签展示。删除分类不会改写历史记录上的旧分类名。')
        hint.setObjectName('caption')
        hint.setWordWrap(True)
        outer.addWidget(hint)
        self.list_col = QVBoxLayout()
        self.list_col.setSpacing(8)
        outer.addLayout(self.list_col)
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.new_name = QLineEdit()
        self.new_name.setObjectName('settingsField')
        self.new_name.setPlaceholderText('新分类名称')
        self.new_name.setMinimumWidth(200)
        self.new_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_row.addWidget(self.new_name, 1)
        self.new_color = {'value': PALETTE[0]}
        swatches = QHBoxLayout()
        swatches.setSpacing(4)
        for color in PALETTE:
            button = QPushButton()
            button.setFixedSize(22, 22)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f'background:{color}; border:1px solid rgba(0,0,0,0.12); border-radius:6px;'
            )
            button.clicked.connect(lambda checked=False, c=color: self._pick_new_color(c, swatches))
            swatches.addWidget(button)
        add_row.addLayout(swatches)
        add_btn = QPushButton('添加分类')
        add_btn.setObjectName('accent')
        add_btn.clicked.connect(self._add)
        add_row.addWidget(add_btn)
        outer.addLayout(add_row)

    def _pick_new_color(self, color, _layout):
        self.new_color['value'] = color

    def set_categories(self, names: list[str], colors: dict[str, str]):
        self.names = list(names)
        self.colors = dict(colors)
        while self.list_col.count():
            item = self.list_col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for name in self.names:
            self.list_col.addWidget(self._build_row(name, colors.get(name) or PALETTE[0]))

    def _build_row(self, name: str, color: str) -> QWidget:
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        chip = QLabel(f'  {name}  ')
        chip.setMinimumWidth(72)
        text = contrasting_text(color)
        chip.setStyleSheet(
            f'background:{color}; color:{text}; border-radius:8px; padding:4px 10px; font-weight:600;'
        )
        lay.addWidget(chip, 0)
        name_edit = QLineEdit(name)
        name_edit.setObjectName('settingsField')
        name_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(name_edit, 1)
        color_btn = QPushButton('选色')
        color_btn.setObjectName('ghost')
        color_btn.clicked.connect(lambda: self._choose_color(name, color_btn, chip))
        lay.addWidget(color_btn)
        save = QPushButton('保存')
        save.setObjectName('ghost')
        save.clicked.connect(lambda: self._save_row(name, name_edit, color_btn, chip))
        lay.addWidget(save)
        delete = QPushButton('删除')
        delete.setObjectName('ghost')
        delete.clicked.connect(lambda: self._delete(name))
        lay.addWidget(delete)
        color_btn.setProperty('color', color)
        color_btn.setProperty('orig_name', name)
        chip.setProperty('color', color)
        return row

    def _choose_color(self, name, button, chip):
        current = button.property('color') or PALETTE[0]
        picked = QColorDialog.getColor(QColor(current), self.window, f'选择「{name}」颜色')
        if not picked.isValid():
            return
        color = picked.name(QColor.NameFormat.HexRgb)
        button.setProperty('color', color)
        text = contrasting_text(color)
        chip.setStyleSheet(
            f'background:{color}; color:{text}; border-radius:8px; padding:4px 10px; font-weight:600;'
        )
        chip.setProperty('color', color)

    def _save_row(self, orig_name, name_edit, color_btn, chip):
        new_name = name_edit.text().strip()
        color = color_btn.property('color') or chip.property('color') or PALETTE[0]
        if not new_name:
            QMessageBox.warning(self.window, '分类', '请输入分类名称。')
            return

        def work(memory):
            if new_name != orig_name:
                memory.rename_category(orig_name, new_name, color=color)
            else:
                memory.set_category_color(orig_name, color)

        self.window.run_job(work, lambda _: self.window.refresh(load_profile=True))

    def _delete(self, name):
        if QMessageBox.question(self.window, '删除分类', f'确定删除分类「{name}」？') != QMessageBox.StandardButton.Yes:
            return
        self.window.run_job(lambda m: m.remove_category(name), lambda _: self.window.refresh(load_profile=True))

    def _add(self):
        name = self.new_name.text().strip()
        color = self.new_color['value']
        if not name:
            QMessageBox.warning(self.window, '分类', '请输入新分类名称。')
            return

        def work(memory):
            memory.add_category(name, color)

        def done(_):
            self.new_name.clear()
            self.window.refresh(load_profile=True)

        self.window.run_job(work, done)
