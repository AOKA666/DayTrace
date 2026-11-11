"""Shared selection controls and the My page. Database work uses the window queue."""
from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QListView,
)
from PySide6.QtGui import QColor, QIcon, QPixmap, QPainter
from ..category_palette import PALETTE, default_tag_color
from .dialog_kit import add_field, add_footer, field_label, make_dialog


def color_square(color):
    """Small rounded swatch; 2x backing stays crisp on high-DPI screens."""
    pixmap = QPixmap(32, 32)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(2, 2, 12, 12), 3, 3)
    painter.end()
    return QIcon(pixmap)


class ColorPicker(QWidget):
    """Visible swatches only: no color-code input fields."""
    def __init__(self, color=PALETTE[0], parent=None):
        super().__init__(parent)
        self.color = color
        self.locked = False
        self.buttons = {}
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        for value, name in zip(PALETTE, ('紫色', '青色', '橙色', '蓝色', '粉色', '绿色', '浅紫色', '棕色')):
            self.add_swatch(value, name)
        self.set_color(color)

    def add_swatch(self, color, name):
        button = QPushButton()
        button.setCheckable(True)
        button.setFixedSize(30, 30)
        button.setToolTip(name)
        button.setAccessibleName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f'QPushButton {{background:{color}; border:2px solid transparent; border-radius:15px; padding:0;}}'
            'QPushButton:checked {border-color:#1D1D1F;}'
        )
        button.clicked.connect(lambda: self.set_color(color))
        self.buttons[color] = button
        self.row.addWidget(button)

    def set_color(self, color):
        if color not in self.buttons:
            self.add_swatch(color, '当前颜色')
        self.color = color
        for value, button in self.buttons.items():
            button.setChecked(value == color)
            button.setVisible(not self.locked or value == color)
            button.setEnabled(not self.locked)

    def inherit(self, color=None):
        self.locked = color is not None
        self.set_color(color or self.color)


class TagCloud(QListWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()

    def fit_height(self):
        available = max(1, self.viewport().width() - 12)
        rows, used = 1, 0
        for index in range(self.count()):
            width = self.item(index).sizeHint().width() + 12
            if used and used + width > available:
                rows, used = rows + 1, 0
            used += width
        height = min(180, max(48, rows * 48))
        if self.height() != height or self.minimumHeight() != height:
            self.setFixedHeight(height)


def create_category(host, parent_id=None, on_created=None):
    dialog, body, footer = make_dialog(host, '新建分类', 460)
    parent = QComboBox()
    parent.addItem('一级分类', None)
    for item in host.taxonomy['categories']:
        if not item['parent_id']:
            parent.addItem(item['name'] + ' 下的子分类', item['id'])
    parent.setCurrentIndex(max(0, parent.findData(parent_id)))
    name = QLineEdit()
    name.setMaxLength(40)
    name.setPlaceholderText('例如 工作、学习')
    colors = ColorPicker()
    note = QLabel()
    note.setObjectName('caption')
    note.setWordWrap(True)
    add_field(body, '上级分类', parent)
    add_field(body, '新分类名称', name)
    add_field(body, '颜色', colors)
    body.addWidget(note)

    def inherit_color():
        selected = next((c for c in host.taxonomy['categories'] if c['id'] == parent.currentData()), None)
        colors.inherit(selected['color'] if selected else None)
        note.setText('子分类颜色与父分类保持一致。' if selected else '点击色块选择分类颜色。')
    parent.currentIndexChanged.connect(inherit_color)
    inherit_color()
    save, _cancel = add_footer(footer, '创建', dialog)
    save.setEnabled(False)
    name.textChanged.connect(lambda text: save.setEnabled(bool(text.strip())))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    value, parent_value, color = name.text().strip(), parent.currentData(), colors.color

    def work(memory):
        identifier = memory.create_category(value, parent_value, color)
        return identifier, memory.catalog()

    def done(result):
        identifier, catalog = result
        host.set_catalog(catalog)
        if on_created:
            on_created(identifier)
    host.run_job(work, done)


def create_tag(host, on_created=None):
    dialog, body, footer = make_dialog(host, '新建标签', 460)
    name = QLineEdit()
    name.setMaxLength(41)
    name.setPlaceholderText('例如 AI编程出海（可省略 #）')
    colors = ColorPicker()
    add_field(body, '标签名称', name)
    add_field(body, '颜色', colors)
    save, _cancel = add_footer(footer, '创建', dialog)
    save.setEnabled(False)
    name.textChanged.connect(lambda text: save.setEnabled(bool(text.lstrip('#').strip())))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    value, color = name.text(), colors.color

    def work(memory):
        identifier = memory.create_tag(value, color)
        return identifier, memory.catalog()

    def done(result):
        identifier, catalog = result
        host.set_catalog(catalog)
        if on_created:
            on_created(identifier)
    host.run_job(work, done)



def edit_category(host, category, on_saved=None):
    dialog, body, footer = make_dialog(host, '修改分类', 460)
    name = QLineEdit(category['name'])
    name.setMaxLength(40)
    colors = ColorPicker(category['color'])
    note = QLabel()
    note.setObjectName('caption')
    note.setWordWrap(True)
    add_field(body, '分类名称', name)
    add_field(body, '颜色', colors)
    body.addWidget(note)
    if category.get('parent_id'):
        colors.inherit(category['color'])
        note.setText('子分类颜色与父分类保持一致，请在父分类中修改颜色。')
    else:
        note.setText('点击色块选择分类颜色；修改后子分类会同步。')
    save, _cancel = add_footer(footer, '保存', dialog)
    save.setEnabled(bool(name.text().strip()))
    name.textChanged.connect(lambda value: save.setEnabled(bool(value.strip())))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    value, color = name.text().strip(), colors.color

    def work(memory):
        memory.update_category(category['id'], value, color)
        return memory.catalog()

    def done(catalog):
        host.set_catalog(catalog)
        host.refresh()
        if on_saved:
            on_saved(category['id'])
    host.run_job(work, done)


def edit_tag(host, tag, on_saved=None):
    dialog, body, footer = make_dialog(host, '修改标签', 460)
    name = QLineEdit(tag['name'])
    name.setMaxLength(41)
    name.setPlaceholderText('例如 AI编程出海（可省略 #）')
    colors = ColorPicker(tag.get('color') or default_tag_color(tag['name']))
    add_field(body, '标签名称', name)
    add_field(body, '颜色', colors)
    save, _cancel = add_footer(footer, '保存', dialog)
    save.setEnabled(bool(name.text().lstrip('#').strip()))
    name.textChanged.connect(lambda value: save.setEnabled(bool(value.lstrip('#').strip())))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    value, color = name.text(), colors.color

    def work(memory):
        memory.update_tag(tag['id'], value, color)
        return memory.catalog()

    def done(catalog):
        host.set_catalog(catalog)
        host.refresh()
        if on_saved:
            on_saved(tag['id'])
    host.run_job(work, done)


class ClassificationPicker(QWidget):
    """Non-editable category selection and optional multi-select tags."""
    def __init__(self, host, category='', tags=(), parent=None):
        super().__init__(parent)
        self.host = host
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(field_label('分类（必选）'))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.category = QComboBox()
        self.category.setEditable(False)
        row.addWidget(self.category, 1)
        add = QPushButton('＋ 新建分类')
        add.setObjectName('ghost')
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(lambda: create_category(host, on_created=self.select_category))
        row.addWidget(add)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(field_label('标签（可选，可多选）'))
        row.addStretch()
        add_tag = QPushButton('＋ 新建标签')
        add_tag.setObjectName('ghost')
        add_tag.setCursor(Qt.CursorShape.PointingHandCursor)
        add_tag.clicked.connect(lambda: create_tag(host, self.select_tag))
        row.addWidget(add_tag)
        layout.addLayout(row)
        self.tags = QListWidget()
        self.tags.setObjectName('tagPicker')
        self.tags.setMinimumHeight(130)
        self.tags.setMaximumHeight(200)
        layout.addWidget(self.tags)
        self.reload(host.taxonomy)
        index = self.category.findText(category)
        self.category.setCurrentIndex(max(0, index))
        for identifier in tags:
            self.select_tag(identifier)
        host.taxonomy_changed.connect(self.reload)

    def reload(self, catalog):
        selected = self.category.currentData()
        tags = set(self.tag_ids())
        self.category.clear()
        self.category.addItem('请选择分类…', None)
        for item in catalog['categories']:
            self.category.addItem(color_square(item['color']), item['path'], item['id'])
        self.select_category(selected)
        self.tags.clear()
        for tag in catalog['tags']:
            item = QListWidgetItem('#' + tag['name'])
            item.setForeground(QColor(tag.get('color') or default_tag_color(tag['name'])))
            item.setData(Qt.ItemDataRole.UserRole, tag['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if tag['id'] in tags else Qt.CheckState.Unchecked)
            self.tags.addItem(item)

    def select_category(self, identifier):
        self.category.setCurrentIndex(max(0, self.category.findData(identifier)))

    def select_tag(self, identifier):
        for index in range(self.tags.count()):
            item = self.tags.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == identifier:
                item.setCheckState(Qt.CheckState.Checked)

    def tag_ids(self):
        return [self.tags.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.tags.count())
                if self.tags.item(i).checkState() == Qt.CheckState.Checked]

    def values(self):
        return self.category.currentData(), self.tag_ids()


class MyPanel(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.catalog = {'categories': [], 'tags': []}
        outer = QVBoxLayout(self)
        title = QLabel('我的分类')
        title.setObjectName('sectionTitle')
        outer.addWidget(title)
        hint = QLabel('分类支持一级分类和子分类。修改名称或颜色后，时间线上已使用该分类的活动会一起更新；删除分类仍保留历史记录上的分类文字。')
        hint.setWordWrap(True)
        hint.setObjectName('caption')
        outer.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setObjectName('categoryList')
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setMinimumHeight(72)
        outer.addWidget(self.tree, 2)
        bar = QHBoxLayout()
        for text, callback in [('＋ 新建分类', lambda: create_category(host)),
                               ('＋ 新建子分类', self.add_child), ('修改名称 / 颜色', self.edit), ('删除分类', self.delete_category)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            bar.addWidget(button)
        bar.addStretch()
        outer.addLayout(bar)
        title = QLabel('我的标签')
        title.setObjectName('sectionTitle')
        outer.addWidget(title)
        self.tags = TagCloud()
        self.tags.setObjectName('tagCloud')
        self.tags.setViewMode(QListView.ViewMode.IconMode)
        self.tags.setFlow(QListView.Flow.LeftToRight)
        self.tags.setWrapping(True)
        self.tags.setResizeMode(QListView.ResizeMode.Adjust)
        self.tags.setMovement(QListView.Movement.Static)
        self.tags.setSpacing(6)
        self.tags.setMinimumHeight(48)
        self.tags.setMaximumHeight(180)
        outer.addWidget(self.tags, 1)
        bar = QHBoxLayout()
        add = QPushButton('＋ 新建标签')
        add.clicked.connect(lambda: create_tag(host))
        edit = QPushButton('修改名称 / 颜色')
        edit.clicked.connect(self.edit_tag)
        remove = QPushButton('删除标签')
        remove.clicked.connect(self.delete_tag)
        bar.addWidget(add)
        bar.addWidget(edit)
        bar.addWidget(remove)
        bar.addStretch()
        outer.addLayout(bar)
        outer.addStretch(1)

    def reload(self, catalog):
        self.catalog = catalog
        selected = self.selected_category()
        selected_id = selected['id'] if selected else None
        self.tree.clear()
        roots = {}
        for category in catalog['categories']:
            item = QTreeWidgetItem([category['name']])
            item.setData(0, Qt.ItemDataRole.UserRole, category['id'])
            item.setIcon(0, color_square(category['color']))
            if category['parent_id'] in roots:
                roots[category['parent_id']].addChild(item)
            else:
                self.tree.addTopLevelItem(item)
                roots[category['id']] = item
            if category['id'] == selected_id:
                self.tree.setCurrentItem(item)
        self.tree.expandAll()
        self.tree.setMaximumHeight(min(320, max(72, len(catalog['categories']) * 38 + 8)))
        self.tags.clear()
        for tag in catalog['tags']:
            item = QListWidgetItem('#' + tag['name'])
            item.setForeground(QColor(tag.get('color') or default_tag_color(tag['name'])))
            item.setSizeHint(QSize(min(480, self.tags.fontMetrics().horizontalAdvance(item.text()) + 30), 36))
            item.setData(Qt.ItemDataRole.UserRole, tag['id'])
            self.tags.addItem(item)
        self.tags.fit_height()

    def selected_category(self):
        item = self.tree.currentItem()
        return next((c for c in self.catalog['categories'] if item and c['id'] == item.data(0, Qt.ItemDataRole.UserRole)), None)

    def add_child(self):
        category = self.selected_category()
        if not category:
            QMessageBox.information(self, '新建子分类', '请先选择一个一级分类。')
            return
        create_category(self.host, category['parent_id'] or category['id'])

    def edit(self):
        category = self.selected_category()
        if not category:
            QMessageBox.information(self, '修改分类', '请先选择一个分类。')
            return
        edit_category(self.host, category)

    def edit_tag(self):
        item = self.tags.currentItem()
        if not item:
            QMessageBox.information(self, '修改标签', '请先选择一个标签。')
            return
        identifier = item.data(Qt.ItemDataRole.UserRole)
        tag = next((row for row in self.catalog['tags'] if row['id'] == identifier), None)
        if tag:
            edit_tag(self.host, tag)

    def delete_category(self):
        category = self.selected_category()
        if category and QMessageBox.question(self, '删除分类', '删除该分类及其子分类？已记录的活动会保留当时的分类文字。') == QMessageBox.StandardButton.Yes:
            self.mutate(lambda m: m.delete_category(category['id']))

    def delete_tag(self):
        item = self.tags.currentItem()
        if item and QMessageBox.question(self, '删除标签', '删除该标签，并清除活动及纠正记录上的标签关联？') == QMessageBox.StandardButton.Yes:
            identifier = item.data(Qt.ItemDataRole.UserRole)
            self.mutate(lambda m: m.delete_tag(identifier))

    def mutate(self, fn):
        def work(memory):
            fn(memory)
            return memory.catalog()
        self.host.run_job(work, lambda result: (self.host.set_catalog(result), self.host.refresh()))
