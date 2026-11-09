from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from daytrace.personalization.ui import App, sync_tree
import tkinter as tk


class DesktopSmokeTests(unittest.TestCase):
    def test_three_pages_profile_save_and_empty_analysis_without_collection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            app = App(root, Path(folder) / 'synthetic.sqlite3')
            def finish():
                end = time.monotonic() + 10
                while app.busy and time.monotonic() < end:
                    root.update()
                    time.sleep(.01)
                self.assertFalse(app.busy)
            try:
                finish()
                self.assertEqual(len(app.tabs.tabs()), 3)
                self.assertEqual(app.timeline.winfo_manager(), '')
                from datetime import datetime
                day=datetime(2026,11,8)
                start=int(day.timestamp()*1000)
                fragments=[dict(interval_id=str(i),start_ms=start+i*3600000,end_ms=start+(i+1)*3600000,category=category,state='active') for i,category in enumerate(['学习','生活','学习'])]
                app.day_canvas.update_rows(fragments,day,{'学习':'#7566D9'})
                canvas_ids=app.day_canvas.find_all()
                self.assertEqual(set(app.day_canvas.items.values()), {'0','1','2'})
                app.day_canvas.update_rows(fragments,day,{'学习':'#7566D9'})
                self.assertEqual(canvas_ids,app.day_canvas.find_all())
                self.assertIsNone(app.provider)
                self.assertEqual(app.endpoint.get(), 'https://api.deepseek.com/chat/completions')
                self.assertEqual(app.model.get(), 'deepseek-flash')
                app.description.insert('1.0', '我用 VS Code 编程开发')
                app.propose()
                app.fields['projects'].insert(0, 'Synthetic Project')
                app.save_profile()
                finish()
                app.refresh(load_profile=True)
                finish()
                self.assertEqual(app.fields['projects'].get(), 'Synthetic Project')
                app.analyze()
                finish()
                self.assertEqual(app.timeline.get_children(), ())
                self.assertEqual(app.review.get_children(), ())
                app.description.insert('end', ' 未保存的修改')
                from unittest.mock import patch
                with patch.object(app, 'refresh', wraps=app.refresh) as refresh:
                    app.auto_refresh()
                    refresh.assert_called_once_with(quiet=True)
                    finish()
                self.assertIn('未保存的修改', app.description.get('1.0','end'))
                desired=[('synthetic','',['12:00–12:01','60 秒','活动','','','未知','标题'])]
                sync_tree(app.timeline,desired)
                with patch.object(app.timeline,'delete',wraps=app.timeline.delete) as delete, patch.object(app.timeline,'insert',wraps=app.timeline.insert) as insert:
                    sync_tree(app.timeline,desired)
                    delete.assert_not_called();insert.assert_not_called()
                self.assertEqual(app.timeline.item('synthetic','values')[1],'60 秒')
            finally:
                app.close()
