import base64
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from daytrace.storage.repository import Repository
from daytrace.storage import screenshots
from daytrace.engine import Engine
from daytrace.domain import Observation
from daytrace.preferences import save_dwell, dwell_seconds, save_options, screenshots_enabled

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


class ScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.repo=Repository(Path(self.temp.name)/'test.db')
        self.engine=Engine(self.repo,100000,0,simulated=True)
        self.engine.sample(0,100000,Observation('active','test.exe','test','synthetic',1))
        self.event=self.engine.event_id
        self.interval=self.engine.interval_id

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def save(self):
        return screenshots.save(self.repo,self.event,self.engine.session,100001,PNG,1,1,1)

    def test_default_zero_files_and_stopped_result_rejected(self):
        self.assertIsNone(self.save())
        self.assertFalse(screenshots.directory(self.repo).exists())
        screenshots.migrate(self.repo)
        self.engine.stop(2000,102000)
        self.assertIsNone(self.save())

    def test_retention_read_delete_and_restart(self):
        screenshots.migrate(self.repo)
        self.assertIsNotNone(self.save())
        self.engine.stop(2000,102000)
        self.assertEqual(screenshots.read(self.repo,self.interval,102000)['png'],PNG)
        self.repo.cleanup(100001+86_400_000)
        self.assertFalse(list(screenshots.directory(self.repo).glob('*.png')))
        path=self.repo.path
        self.repo.close(); self.repo=Repository(path)
        self.assertIsNone(screenshots.read(self.repo,self.interval,102000))

    def test_cascade_orphan_cleanup_and_rollback(self):
        screenshots.migrate(self.repo)
        self.save()
        self.engine.stop(2000,102000)
        with self.repo.transaction():
            self.repo.db.execute('DELETE FROM activity_events WHERE id=?',(self.event,))
        screenshots.cleanup(self.repo)
        self.assertEqual(list(screenshots.directory(self.repo).glob('*.png')),[])
        screenshots.rollback(self.repo)
        self.assertEqual(self.repo.db.execute('PRAGMA user_version').fetchone()[0],3)

    def test_configurable_dwell_and_validation(self):
        self.assertEqual(dwell_seconds(self.repo.path),5)
        save_dwell(self.repo.path,8)
        self.assertEqual(dwell_seconds(self.repo.path),8)
        for value in (-1,301,float('nan')):
            with self.assertRaises(ValueError):
                save_dwell(self.repo.path,value)

    def test_single_switch_persists_without_overwriting_dwell(self):
        self.assertFalse(screenshots_enabled(self.repo.path))
        save_dwell(self.repo.path,8)
        save_options(self.repo.path,screenshots_enabled=True)
        self.assertTrue(screenshots_enabled(self.repo.path))
        self.assertEqual(dwell_seconds(self.repo.path),8)
        save_dwell(self.repo.path,9)
        self.assertTrue(screenshots_enabled(self.repo.path))
        save_options(self.repo.path,screenshots_enabled=False)
        self.assertFalse(screenshots_enabled(self.repo.path))

    def test_private_deletes_screenshot_files(self):
        from daytrace.personalization.store import Memory
        from daytrace.personalization.classifier import Classifier
        screenshots.migrate(self.repo)
        self.save(); self.engine.stop(2000,102000)
        memory=Memory(self.repo.path,now=lambda:102000)
        try:
            Classifier(memory).analyze()
            memory.feedback(self.interval,action='private')
            self.assertEqual(list(screenshots.directory(self.repo).glob('*.png')),[])
        finally:
            memory.close()

    def test_paused_result_and_invalid_paths_rejected(self):
        screenshots.migrate(self.repo)
        self.engine.pause(1000,101000)
        self.assertIsNone(self.save())
        with self.assertRaises(ValueError):
            screenshots.file_path(self.repo,'../escape.png')

    def test_single_image_delete_keeps_activity(self):
        screenshots.migrate(self.repo); self.save()
        self.engine.stop(2000,102000)
        screenshots.delete_interval(self.repo,self.interval)
        self.assertIsNone(screenshots.read(self.repo,self.interval,102000))
        self.assertIsNotNone(self.repo.db.execute('SELECT id FROM activity_events WHERE id=?',(self.event,)).fetchone())

    def test_image_deletion_requires_stopped_collector(self):
        from daytrace.storage.repository import InstanceLock
        screenshots.migrate(self.repo); self.save()
        with InstanceLock(self.repo.path):
            with self.assertRaises(RuntimeError):
                screenshots.delete_interval(self.repo,self.interval)
        self.engine.stop(2000,102000)
        screenshots.delete_interval(self.repo,self.interval)
        self.assertIsNone(self.save())
        self.assertEqual(list(screenshots.directory(self.repo).glob('*.png')),[])


class SyntheticCaptureTests(unittest.TestCase):
    def test_only_authorized_nonsensitive_pixels_are_returned(self):
        import numpy as np
        from unittest.mock import patch, MagicMock
        from daytrace.content.ocr import capture
        ctx={'hwnd':1,'pid':1,'app':'app','process':'chrome.exe','title':'synthetic','rect':(0,0,10,10)}
        request={'context':ctx,'exclude':[],'exclude_windows':[], 'permit':{'app':'chrome.exe','region':(0,0,10,10),'size':(10,10)}}
        screen=MagicMock()
        screen.__enter__.return_value.grab.return_value=np.zeros((10,10,4),dtype=np.uint8)
        with patch('mss.mss',return_value=screen),patch('daytrace.content.ocr.create_engine'),patch('daytrace.content.ocr.recognize') as recognize,patch('daytrace.content.desktop.context',return_value=ctx),patch('daytrace.content.desktop.unobscured',return_value=True),patch('daytrace.content.uia.extract',return_value={'status':'no_text','ocr_safe':True}):
            recognize.return_value={'source':'ocr','status':'success','text':'synthetic'}
            self.assertNotIn('image_png',capture(request))
            request['permit']['retain']=True
            recognize.return_value={'source':'ocr','status':'success','text':'synthetic'}
            self.assertTrue(capture(request)['image_png'].startswith(b'\x89PNG'))
            recognize.return_value={'source':'ocr','status':'success','text':'password=synthetic'}
            self.assertNotIn('image_png',capture(request))
