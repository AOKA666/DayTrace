import ast
import sys
import unittest
from importlib.util import find_spec
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

DIARY_QT = Path(__file__).resolve().parents[1] / 'src' / 'daytrace' / 'personalization' / 'diary_qt'


class DiaryQtTests(unittest.TestCase):
    @unittest.skipUnless(find_spec('PySide6'), 'PySide6 required')
    def test_theme_and_timeline_import(self):
        from daytrace.personalization.diary_qt.theme import STYLESHEET

        self.assertIn('border-radius', STYLESHEET)
        try:
            from daytrace.personalization.diary_qt.timeline import TimelineWidget
        except ImportError as exc:
            if 'libEGL' in str(exc) or 'libxkbcommon' in str(exc):
                self.skipTest('Qt platform libraries unavailable in this environment')
            raise
        self.assertEqual(TimelineWidget.pitch, 152)

    def test_install_hint_module(self):
        from daytrace.personalization.diary_qt import INSTALL_HINT

        self.assertIn('PySide6', INSTALL_HINT)

    def test_preferences_resolves_to_daytrace_root(self):
        import daytrace.preferences as preferences

        self.assertTrue(str(preferences.__file__).endswith('preferences.py'))
        from daytrace.preferences import options, save_dwell, save_options

        self.assertTrue(callable(options))
        self.assertTrue(callable(save_dwell))
        self.assertTrue(callable(save_options))

    def test_repo_root_resolves_to_repository(self):
        from daytrace.personalization.diary_qt.capture_sync import repo_root

        root = repo_root()
        self.assertTrue((root / 'daytrace.py').is_file())
        self.assertTrue((root / 'src' / 'daytrace').is_dir())

    def test_read_capture_state_stopped_without_lock(self):
        import tempfile
        from unittest.mock import patch

        from daytrace.personalization.diary_qt.capture_sync import read_capture_state
        from daytrace.personalization.store import Memory

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'empty.sqlite3'
            Memory(path).close()
            with patch('daytrace.personalization.diary_worker.is_running', return_value=False):
                self.assertEqual(read_capture_state(path), 'stopped')

    def test_job_bridge_uses_qt_signal_not_worker_qtimer(self):
        from PySide6.QtCore import QObject
        from daytrace.personalization.diary_qt import jobs

        self.assertTrue(issubclass(jobs.JobBridge, QObject))
        text = (DIARY_QT / 'window.py').read_text(encoding='utf-8')
        self.assertIn('_job_bridge.finished.emit', text)
        self.assertNotIn('QTimer.singleShot(0, lambda: done', text)

    def test_diary_qt_no_wrong_parent_preferences_imports(self):
        """diary_qt lives one level deeper than personalization; preferences/cli sit under daytrace."""
        offenders = []
        for path in DIARY_QT.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module in ('preferences', 'cli') and node.level == 2:
                    offenders.append(f'{path.name}:{node.lineno}')
        self.assertEqual(offenders, [], f'bad relative imports: {offenders}')


if __name__ == '__main__':
    unittest.main()
