"""Shared Apple-style dialog chrome for DayTrace popups."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


def make_dialog(parent, title, width=460, subtitle=''):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setObjectName('appleDialog')
    dialog.setMinimumWidth(width)
    root = QVBoxLayout(dialog)
    root.setContentsMargins(28, 24, 28, 20)
    root.setSpacing(16)
    heading = QLabel(title)
    heading.setObjectName('dialogTitle')
    heading.setWordWrap(True)
    root.addWidget(heading)
    if subtitle:
        caption = QLabel(subtitle)
        caption.setObjectName('caption')
        caption.setWordWrap(True)
        root.addWidget(caption)
    body = QVBoxLayout()
    body.setSpacing(14)
    root.addLayout(body, 1)
    footer = QHBoxLayout()
    footer.setContentsMargins(0, 6, 0, 0)
    footer.setSpacing(10)
    footer.addStretch()
    root.addLayout(footer)
    return dialog, body, footer


def field_label(text):
    label = QLabel(text)
    label.setObjectName('fieldLabel')
    return label


def add_field(body, label, widget):
    wrap = QVBoxLayout()
    wrap.setSpacing(6)
    wrap.addWidget(field_label(label))
    wrap.addWidget(widget)
    body.addLayout(wrap)
    return widget


def add_footer(footer, accept_text, dialog, accept_slot=None, cancel_text='取消'):
    cancel = QPushButton(cancel_text)
    cancel.setObjectName('ghost')
    cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel.clicked.connect(dialog.reject)
    accept = QPushButton(accept_text)
    accept.setObjectName('accent')
    accept.setDefault(True)
    accept.setCursor(Qt.CursorShape.PointingHandCursor)
    accept.clicked.connect(accept_slot or dialog.accept)
    footer.addWidget(cancel)
    footer.addWidget(accept)
    return accept, cancel
