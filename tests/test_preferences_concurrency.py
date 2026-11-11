"""Synthetic preference writes; never changes the user's settings."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from daytrace.preferences import options,save_options


class PreferencesConcurrencyTests(unittest.TestCase):
    def test_parallel_ui_and_background_changes_keep_all_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.sqlite3'
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda i:save_options(path,**{f'field_{i}':i}),range(40)))
            self.assertEqual(options(path),{f'field_{i}':i for i in range(40)})
