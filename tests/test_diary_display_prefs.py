import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from daytrace.preferences import diary_display_ms, save_dwell, save_options


class DiaryDisplayPrefsTests(unittest.TestCase):
    def test_diary_display_ms_reads_saved_values(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'demo.sqlite3'
            db.write_text('', encoding='utf-8')
            save_dwell(db, 8)
            save_options(db, diary_merge_gap_seconds=90, diary_fold_gap_seconds=45)
            dwell_ms, merge_ms, fold_ms = diary_display_ms(db)
            self.assertEqual(dwell_ms, 8000)
            self.assertEqual(merge_ms, 90_000)
            self.assertEqual(fold_ms, 45_000)
            prefs = json.loads(Path(str(db) + '.preferences.json').read_text('utf-8'))
            self.assertEqual(prefs['min_dwell_seconds'], 8)

    def test_colors_only_update_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'demo.sqlite3'
            db.write_text('', encoding='utf-8')
            save_options(
                db,
                min_dwell_seconds=12,
                show_short_dwells=True,
                screenshots_enabled=True,
            )
            save_options(db, category_colors={'工作': '#5B8FCB'})
            prefs = json.loads(Path(str(db) + '.preferences.json').read_text('utf-8'))
            self.assertEqual(prefs['min_dwell_seconds'], 12)
            self.assertTrue(prefs['show_short_dwells'])
            self.assertTrue(prefs['screenshots_enabled'])
            self.assertEqual(prefs['category_colors'], {'工作': '#5B8FCB'})


if __name__ == '__main__':
    unittest.main()
