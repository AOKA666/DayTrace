import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from daytrace.personalization.diary_model import DEFAULT_CATEGORIES
from daytrace.personalization.store import Memory
from daytrace.personalization.category_palette import (
    DEFAULT_CATEGORY_COLORS,
    bootstrap_category_colors,
    category_color,
    contrasting_text,
)


class CategoryColorTests(unittest.TestCase):
    def test_default_presets_cover_categories(self):
        for name in DEFAULT_CATEGORIES:
            self.assertIn(name, DEFAULT_CATEGORY_COLORS)

    def test_contrasting_text_readable_pairs(self):
        self.assertEqual(contrasting_text('#5B8FCB'), '#FFFFFF')
        self.assertEqual(contrasting_text('#F4F6FA'), '#243041')

    def test_category_color_prefers_user_map(self):
        self.assertEqual(category_color('学习', {'学习': '#111111'}), '#111111')

    def test_bootstrap_writes_preferences_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'db.sqlite3'
            memory = Memory(path)
            try:
                colors = bootstrap_category_colors(path, DEFAULT_CATEGORIES)
                self.assertEqual(colors['工作'], DEFAULT_CATEGORY_COLORS['工作'])
                prefs = json.loads(Path(str(path) + '.preferences.json').read_text('utf-8'))
                self.assertEqual(prefs['category_colors']['学习'], DEFAULT_CATEGORY_COLORS['学习'])
                again = bootstrap_category_colors(path, DEFAULT_CATEGORIES)
                self.assertEqual(again, colors)
                memory.remove_category('其他')
                self.assertNotIn('其他', memory.profile()['activities'])
            finally:
                memory.close()


if __name__ == '__main__':
    unittest.main()
