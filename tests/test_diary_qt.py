import sys
import unittest
from importlib.util import find_spec
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


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


if __name__ == '__main__':
    unittest.main()
