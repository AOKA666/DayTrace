import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QPushButton
from daytrace.personalization.store import Memory
from daytrace.personalization.diary_qt.window import run_app
from daytrace.personalization.diary_qt.dialogs import ConfirmDialog
from daytrace.personalization.diary_qt.taxonomy_widgets import create_category, create_tag, edit_category, edit_tag, ColorPicker
from daytrace.engine import Engine
from daytrace.domain import Observation


class TaxonomyUiTests(unittest.TestCase):
    def test_unified_timeline_history_and_return_today(self):
        from datetime import datetime, timedelta
        self.assertEqual(list(self.window.nav_buttons), ['时间线', '我的', '设置'])
        self.assertFalse(self.window.today_button.isVisible())
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        with patch.object(self.window, 'refresh') as refresh:
            self.window.shift_day(-1)
            self.assertEqual(self.window.date.text(), yesterday)
            self.assertTrue(self.window.today_button.isVisible())
            self.assertEqual(self.window.summary_title.text(), '当日概览')
            self.window.navigate('设置', refresh=False)
            self.assertFalse(self.window.today_button.isVisible())
            self.window.navigate('时间线', refresh=False)
            self.assertEqual(self.window.date.text(), yesterday)
            self.window.preview_mode = False
            refresh.reset_mock()
            self.window._refresh_live_timeline()
            refresh.assert_not_called()
            self.window.today_button.click()
            self.assertEqual(self.window.date.text(), datetime.now().strftime('%Y-%m-%d'))
            self.assertFalse(self.window.today_button.isVisible())
            refresh.assert_called_once()
            self.window.preview_mode = True

    def test_stale_live_read_does_not_replace_new_day(self):
        jobs = []
        with patch.object(self.window, 'run_job', side_effect=lambda fn, callback, **kwargs: jobs.append((fn, callback))):
            self.window.refresh(quiet=True, live=True)
        memory = Memory(self.path)
        try:
            data = jobs[0][0](memory)
        finally:
            memory.close()
        self.window.date.setText('2000-01-01')
        self.window.all_cards = []
        jobs[0][1](data)
        self.assertEqual(self.window.all_cards, [])

    def test_live_timeline_updates_while_ai_is_unfinished(self):
        from concurrent.futures import Future
        self.window._ai_timer.stop()
        self.window._capture_timer.stop()
        self.window.preview_mode = False
        self.window.ai_future = Future()  # Simulate a slow AI without a network call.
        memory = Memory(self.path)
        try:
            start = time.time_ns() // 1_000_000 - 10_000
            engine = Engine(memory.repo, start, 0, simulated=True, min_active_ms=5000)
            for offset in range(0, 7000, 1000):
                engine.sample(offset, start + offset, Observation('active', 'new.exe', 'new', 'Live synthetic', 2))
            deadline = time.monotonic() + 3
            while not any(r['process_name'] == 'new.exe' for r in self.window.rows.values()) and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertTrue(any(r['process_name'] == 'new.exe' for r in self.window.rows.values()))
            self.assertFalse(self.window.ai_future.done())
            self.assertEqual(self.window._timeline_timer.interval(), 1000)
            engine.stop(7000, start + 7000)
        finally:
            self.window._timeline_timer.stop()
            memory.close()

    def test_unknown_pending_is_drawn_once_and_review_nav_removed(self):
        pending = [row.frame.confirm for row in self.window.timeline._pool if row.card and row.frame.confirm.isVisible()]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].text(), '待确认')
        self.assertNotIn('AI 复盘', self.window.nav_buttons)

    def test_rules_dialog_toggles_and_deletes_with_plain_labels(self):
        from daytrace.personalization.diary_qt.learning_widgets import RulesDialog, rule_rows
        memory = Memory(self.path)
        try:
            with memory.repo.transaction():
                task = memory.task('编程', '工作')
            identifier = memory.save_rule(task, {'title_exact': 'Synthetic activity'}, approved=True)
            rows = rule_rows(memory)
        finally:
            memory.close()
        dialog = RulesDialog(self.window, rows)
        self.assertIn('窗口标题相同', dialog.table.item(0, 0).text())
        dialog.table.selectRow(0)
        dialog.toggle_rule()
        self.wait_jobs()
        self.assertEqual(dialog.table.item(0, 2).text(), '已停用')
        with patch('daytrace.personalization.diary_qt.learning_widgets.QMessageBox.question', return_value=__import__('PySide6.QtWidgets', fromlist=['QMessageBox']).QMessageBox.StandardButton.Yes):
            dialog.table.selectRow(0)
            dialog.delete_rule()
        self.wait_jobs()
        self.assertEqual(dialog.table.rowCount(), 0)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'synthetic.sqlite3'
        memory = Memory(self.path)
        self.root = memory.create_category('工作')
        self.child = memory.create_category('编程', self.root)
        self.tag = memory.create_tag('AI编程出海')
        start = time.time_ns() // 1_000_000 - 60_000
        engine = Engine(memory.repo, start, 0, simulated=True)
        for offset in range(0, 6000, 1000):
            engine.sample(offset, start + offset, Observation('active', 'Code.exe', 'synthetic', 'Synthetic activity', 1))
        engine.stop(6000, start + 6000)
        memory.close()
        self.app, self.window = run_app(self.path, preview_mode=True)
        self.wait_jobs()

    def wait_jobs(self):
        deadline = time.monotonic() + 8
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(self.window.busy)

    def tearDown(self):
        self.wait_jobs()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def test_my_navigation_capture_badge_and_category_tree(self):
        self.assertNotIn('分类颜色', self.window.settings_tabs)
        self.window.navigate('我的', refresh=False)
        self.assertIs(self.window.stack.currentWidget(), self.window.my_page)
        self.assertIs(self.window.my_page.currentWidget(), self.window.my_panel)
        self.assertFalse(self.window.date_capsule.isVisible())
        self.assertEqual(self.window.my_panel.tree.topLevelItem(0).child(0).text(0), '编程')
        self.assertEqual(self.window.my_panel.tags.item(0).text(), '#AI编程出海')
        for state in ('running', 'paused', 'stopped'):
            self.window._update_capture_chrome(state)
            self.assertEqual(self.window.capture_state.property('recordingState'), state)
        self.window.navigate('时间线', refresh=False)
        self.assertTrue(self.window.date_capsule.isVisible())

    def test_confirmation_requires_selection_and_tags_are_optional(self):
        dialog = ConfirmDialog(self.window, 'Synthetic activity', '待确认')
        self.assertEqual(dialog.findChildren(QLineEdit), [])
        self.assertFalse(dialog.picker.category.isEditable())
        save = next(b for b in dialog.findChildren(QPushButton) if b.text() == '确认')
        self.assertFalse(save.isEnabled())
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.picker.select_category(self.child)
        self.assertTrue(save.isEnabled())
        self.assertEqual(dialog.values(), (self.child, []))
        dialog.picker.select_tag(self.tag)
        self.assertEqual(dialog.values(), (self.child, [self.tag]))
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_created_in_confirmation_syncs_to_my_and_selects(self):
        dialog = ConfirmDialog(self.window, 'Synthetic activity')

        def enter_category(edit_dialog):
            edit_dialog.findChild(QLineEdit).setText('调研')
            combo = edit_dialog.findChild(QComboBox)
            combo.setCurrentIndex(combo.findData(self.root))
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, 'exec', enter_category):
            create_category(self.window, on_created=dialog.picker.select_category)
        self.wait_jobs()
        self.assertEqual(dialog.picker.category.currentText(), '工作 / 调研')
        self.assertEqual(self.window.my_panel.tree.topLevelItem(0).childCount(), 2)
        def enter_tag(edit_dialog):
            edit_dialog.findChild(QLineEdit).setText('#产品出海')
            edit_dialog.findChild(ColorPicker).buttons['#3C9B92'].click()
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, 'exec', enter_tag):
            create_tag(self.window, dialog.picker.select_tag)
        self.wait_jobs()
        self.assertEqual(len(dialog.values()[1]), 1)
        self.assertEqual(self.window.my_panel.tags.count(), 2)
        memory = Memory(self.path)
        try:
            self.assertEqual(len(memory.catalog()['tags']), 2)
            self.assertEqual(next(t['color'] for t in memory.catalog()['tags'] if t['name'] == '产品出海'), '#3C9B92')
            self.assertIn('工作 / 调研', memory.profile()['activities'])
        finally:
            memory.close()

    def test_quick_confirmation_persists_selected_category_and_tags(self):
        def choose(dialog):
            dialog.picker.select_category(self.child)
            dialog.picker.select_tag(self.tag)
            return QDialog.DialogCode.Accepted

        with patch.object(ConfirmDialog, 'exec', choose):
            self.window.confirm_cards(self.window.all_cards)
        self.wait_jobs()
        self.assertEqual(self.window.all_cards[0]['category'], '工作 / 编程')
        self.assertEqual(self.window.all_cards[0]['tags'][0]['id'], self.tag)
        self.assertFalse(self.window.all_cards[0]['review'])
        self.window.search.setText('#AI编程出海')
        self.assertEqual(len(self.window.timeline.cards), 1)
        self.window.search.setText('#missing')
        self.assertEqual(self.window.timeline.cards, [])

    def test_creation_palette_and_parent_inheritance_controls(self):
        def choose_root(dialog):
            dialog.findChild(QLineEdit).setText('学习')
            picker = dialog.findChild(ColorPicker)
            picker.buttons['#5B8FCB'].click()
            self.assertEqual(picker.color, '#5B8FCB')
            self.assertEqual(len(dialog.findChildren(QLineEdit)), 1)
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog, 'exec', choose_root):
            create_category(self.window)
        self.wait_jobs()
        root = next(c for c in self.window.taxonomy['categories'] if c['name'] == '学习')
        self.assertEqual(root['color'], '#5B8FCB')

        def choose_child(dialog):
            dialog.findChild(QLineEdit).setText('阅读')
            picker = dialog.findChild(ColorPicker)
            self.assertTrue(picker.locked)
            self.assertEqual(picker.color, '#5B8FCB')
            self.assertTrue(all(not b.isEnabled() for b in picker.buttons.values()))
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog, 'exec', choose_child):
            create_category(self.window, root['id'])
        self.wait_jobs()
        child = next(c for c in self.window.taxonomy['categories'] if c['name'] == '阅读')
        self.assertEqual(child['color'], root['color'])


    def test_edit_dialogs_update_category_and_tag(self):
        root = next(c for c in self.window.taxonomy['categories'] if c['name'] == '工作')

        def change_parent(dialog):
            dialog.findChild(QLineEdit).setText('工作事务')
            picker = dialog.findChild(ColorPicker)
            picker.buttons['#3C9B92'].click()
            self.assertFalse(picker.locked)
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, 'exec', change_parent):
            edit_category(self.window, root)
        self.wait_jobs()
        updated = next(c for c in self.window.taxonomy['categories'] if c['id'] == self.root)
        self.assertEqual(updated['name'], '工作事务')
        self.assertEqual(updated['color'], '#3C9B92')
        child = next(c for c in self.window.taxonomy['categories'] if c['id'] == self.child)
        self.assertEqual(child['color'], '#3C9B92')
        self.assertEqual(child['path'], '工作事务 / 编程')

        tag = next(t for t in self.window.taxonomy['tags'] if t['id'] == self.tag)

        def change_tag(dialog):
            dialog.findChild(QLineEdit).setText('#AI出海')
            dialog.findChild(ColorPicker).buttons['#CA7298'].click()
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, 'exec', change_tag):
            edit_tag(self.window, tag)
        self.wait_jobs()
        updated_tag = next(t for t in self.window.taxonomy['tags'] if t['id'] == self.tag)
        self.assertEqual(updated_tag['name'], 'AI出海')
        self.assertEqual(updated_tag['color'], '#CA7298')
        self.assertEqual(self.window.my_panel.tags.item(0).text(), '#AI出海')

    def test_run_job_queues_instead_of_dropping(self):
        order = []

        def first(_memory):
            order.append('first')
            time.sleep(0.15)

        def second(_memory):
            order.append('second')

        self.window.run_job(first, lambda _: order.append('first-done'))
        self.window.run_job(second, lambda _: order.append('second-done'))
        self.assertTrue(self.window.busy)
        self.assertEqual(len(self.window._job_queue), 1)
        self.wait_jobs()
        self.assertEqual(order, ['first', 'first-done', 'second', 'second-done'])


if __name__ == '__main__':
    unittest.main()
