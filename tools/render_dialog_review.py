"""Render styled DayTrace dialogs against a temporary synthetic database."""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
from tools.render_diary_review import seed
from daytrace.personalization.diary_qt.window import run_app
from daytrace.personalization.diary_qt.dialogs import ConfirmDialog, DetailDialog, FragmentDialog
from daytrace.personalization.diary_qt.taxonomy_widgets import create_category, create_tag, edit_category, edit_tag
from daytrace.personalization.diary_qt.learning_widgets import RulesDialog, CorrectionsDialog
from PySide6.QtWidgets import QDialog


def grab(dialog, path):
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    dialog.repaint()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    for _ in range(8):
        app.processEvents()
    dialog.grab().save(str(path))
    dialog.hide()
    app.processEvents()


def main():
    output = Path('artifacts/ui-review/dialogs')
    output.mkdir(parents=True, exist_ok=True)
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix='daytrace-dialogs-') as folder:
        path = Path(folder) / 'synthetic.sqlite3'
        seed(path)
        app, window = run_app(path, preview_mode=True)
        deadline = time.monotonic() + 10
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        confirm = ConfirmDialog(window, 'README.md - DayTrace - Visual Studio Code')
        grab(confirm, output / 'confirm.png')
        card = window.all_cards[0] if window.all_cards else {
            'title': 'README.md - DayTrace - Visual Studio Code',
            'rows': [{'start_ms': 0, 'end_ms': 60000, 'process_name': 'Code.exe', 'title': 'README.md', 'state': 'active'}],
        }
        fragment = FragmentDialog(window, card)
        grab(fragment, output / 'fragment.png')
        evidence = {
            'process_name': 'Code.exe',
            'event_id': 'evt-preview',
            'content_status': 'partial',
            'has_screenshot': False,
            'title': 'README.md - DayTrace - Visual Studio Code',
            'text': '这是合成的活动依据预览，用于验收详情窗口样式。',
        }
        row = {
            'label': 'README.md - DayTrace - Visual Studio Code',
            'title': 'README.md - DayTrace - Visual Studio Code',
            'reason': '根据窗口标题归类',
            'category': '事业 / AI 编程',
            'tags': [],
        }
        detail = DetailDialog(window, row, evidence, [], lambda *args: None)
        grab(detail, output / 'detail.png')

        captured = {}
        def fake_exec(self):
            name = {'新建分类': 'create_category', '新建标签': 'create_tag',
                    '修改分类': 'edit_category', '修改标签': 'edit_tag'}.get(self.windowTitle(), self.windowTitle())
            grab(self, output / f'{name}.png')
            captured[name] = True
            return QDialog.DialogCode.Rejected
        with patch.object(QDialog, 'exec', fake_exec):
            create_category(window)
            create_tag(window)
            category = next((c for c in window.taxonomy['categories'] if not c.get('parent_id')), None)
            if category:
                edit_category(window, category)
            tag = (window.taxonomy.get('tags') or [None])[0]
            if tag:
                edit_tag(window, tag)
        rules = RulesDialog(window, [])
        grab(rules, output / 'rules.png')
        corrections = CorrectionsDialog(window, [])
        grab(corrections, output / 'corrections.png')
        window.close()
        app.processEvents()
        print('Rendered dialogs:', output.resolve(), 'files:', sorted(p.name for p in output.glob('*.png')))


if __name__ == '__main__':
    main()
