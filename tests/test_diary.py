import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from datetime import datetime
from daytrace.personalization.diary_model import cards
from daytrace.personalization.diary_worker import tick,review,validate,validate_review
from daytrace.personalization.store import Memory
from daytrace.engine import Engine
from daytrace.domain import Observation
from daytrace.preferences import save_options


class DiaryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name)/'synthetic.sqlite3'
        self.now=time.time_ns()//1_000_000
        self.start=self.now-600_000
        memory=Memory(self.path)
        engine=Engine(memory.repo,self.start,0,simulated=True)
        for offset in range(0,180_000,5000):
            index=offset//60_000
            title=['DayTrace API implementation','Different project reading','DayTrace API implementation'][index]
            engine.sample(offset,self.start+offset,Observation('active','Code.exe','Code.exe',title,index+1))
        engine.stop(180_000,self.start+180_000)
        self.ids=memory.intervals()
        memory.close()

    def tearDown(self):
        self.folder.cleanup()

    def enable(self,since=None):
        save_options(self.path,auto_ai=True,ai_since_ms=self.start if since is None else since)

    def fake(self,hook=None):
        class Provider:
            def __init__(inner,*args,**kw):pass
            def classify(inner,payload):
                if hook:hook()
                return [dict(interval_id=e['interval_id'],label='研究接口实现',category='工作',project='',description='阅读接口相关内容。',evidence_ids=e['evidence_ids']) for e in payload['evidence']]
        return Provider

    def test_default_and_prior_history_never_send(self):
        provider=unittest.mock.Mock(side_effect=AssertionError('must not send'))
        tick(self.path,threading.Event(),provider_factory=provider)
        self.enable(self.now)
        tick(self.path,threading.Event(),provider_factory=provider)
        provider.assert_not_called()

    def test_auto_analysis_preserves_times_and_manual_results(self):
        self.enable()
        tick(self.path,threading.Event(),provider_factory=self.fake())
        memory=Memory(self.path)
        rows=memory.timeline()
        self.assertEqual({r['source'] for r in rows},{'ai'})
        self.assertEqual(sum(r['end_ms']-r['start_ms'] for r in rows),180_000)
        memory.feedback(self.ids[0],'人工选择','生活','',remember=True)
        memory.close()
        tick(self.path,threading.Event(),provider_factory=self.fake())
        memory=Memory(self.path)
        self.assertEqual(memory.timeline()[0]['label'],'人工选择')
        self.assertEqual(memory.timeline()[0]['manual'],1)
        memory.close()

    def test_disable_during_request_rejects_results(self):
        self.enable()
        tick(self.path,threading.Event(),provider_factory=self.fake(lambda:save_options(self.path,auto_ai=False)))
        memory=Memory(self.path)
        self.assertTrue(all(r['source']!='ai' for r in memory.timeline()))
        memory.close()

    def test_delete_during_request_and_restart_do_not_restore(self):
        self.enable()
        def remove():
            memory=Memory(self.path)
            memory.delete_interval(self.ids[0]);memory.close()
        tick(self.path,threading.Event(),provider_factory=self.fake(remove))
        memory=Memory(self.path)
        self.assertNotIn(self.ids[0],memory.intervals())
        self.assertTrue(all(r['source']!='ai' for r in memory.timeline()))
        memory.close()

    def test_cancel_and_pause_request_reject_results(self):
        self.enable()
        cancel=threading.Event()
        tick(self.path,cancel,provider_factory=self.fake(cancel.set))
        def pause():
            memory=Memory(self.path)
            session=memory.db.execute('SELECT id FROM capture_sessions LIMIT 1').fetchone()[0]
            with memory.repo.transaction():memory.db.execute("INSERT INTO control_commands(id,session_id,command,requested_ms) VALUES ('pause-test',?,'pause',?)",(session,self.now))
            memory.close()
        tick(self.path,threading.Event(),provider_factory=self.fake(pause))
        memory=Memory(self.path)
        self.assertTrue(all(r['source']!='ai' for r in memory.timeline()))
        memory.close()

    def test_task_boundaries_and_category_not_task(self):
        memory=Memory(self.path);rows=memory.timeline();memory.close()
        for row in rows:row.update(label='开发接口',category='工作',task_id='A',reliability='tentative')
        rows[1].update(task_id='B',label='其他任务')
        self.assertEqual(len(cards(rows)),3)
        rows[1].update(task_id='A',label='开发接口')
        self.assertEqual(len(cards(rows)),1)
        rows[1]['state']='idle'
        self.assertEqual(len(cards(rows)),3)
        rows[1]['state']='active'
        for row in rows:row['label']='工作'
        self.assertEqual(len(cards(rows)),3)

    def test_review_scope_and_changed_source_rejection(self):
        self.enable()
        tick(self.path,threading.Event(),provider_factory=self.fake())
        test=self
        class Reviewer:
            def __init__(inner,*args,**kwargs):pass
            def classify(inner,payload):
                test.assertEqual(payload['mode'],'review')
                test.assertNotIn('text',payload['records'][0])
                return [{'text':'主要在阅读接口资料，活动归属仍需确认。','interval_ids':[payload['records'][0]['interval_id']]}]
        result=review(self.path,threading.Event(),self.start,self.now,provider_factory=Reviewer)
        self.assertIn('text',result)
        repeated=review(self.path,threading.Event(),self.start,self.now,result['key'],provider_factory=unittest.mock.Mock(side_effect=AssertionError()))
        self.assertEqual(repeated,{'key':result['key']})
        class DeletingReviewer(Reviewer):
            def classify(inner,payload):
                memory=Memory(test.path);memory.delete_interval(test.ids[0]);memory.close()
                return super().classify(payload)
        self.assertIsNone(review(self.path,threading.Event(),self.start,self.now,provider_factory=DeletingReviewer))

    def test_invalid_model_fields_are_rejected(self):
        payload={'evidence':[{'interval_id':'1','evidence_ids':['e1']}],'categories':['工作'],'projects':[]}
        entry=dict(interval_id='1',label='阅读资料',category='工作',project='',description='阅读相关资料',evidence_ids=['e1'])
        self.assertEqual(validate([dict(entry)],payload)[0]['label'],'阅读资料')
        for updates in [{'evidence_ids':['other']},{'interval_id':'other'},{'category':'invented'},{'project':'invented'},{'start_ms':1}]:
            with self.assertRaises(ValueError):validate([{**entry,**updates}],payload)
        with self.assertRaises(ValueError):validate_review([{'text':'总结','interval_ids':['other']}],{'records':[{'interval_id':'1'}]})

    def test_bulk_confirmation_and_boundary_refusal(self):
        tick(self.path,threading.Event())
        memory=Memory(self.path)
        try:
            with self.assertRaises(ValueError):memory.feedback_many([self.ids[0],self.ids[2]],'工作','工作')
            memory.feedback_many(self.ids,'研究接口','工作',remember=True)
            self.assertEqual(len(cards(memory.timeline())),1)
            self.assertEqual(memory.db.execute('SELECT count(*) FROM activity_cases').fetchone()[0],3)
            memory.feedback(self.ids[1],'不同任务','学习')
            self.assertEqual(len(cards(memory.timeline())),3)
        finally:memory.close()
    @unittest.skipUnless(__import__('importlib').util.find_spec('tkinter'), 'tkinter required for UI smoke')
    def test_virtualized_canvas_and_navigation_without_collection(self):
        import tkinter as tk
        from daytrace.personalization.diary_ui import DiaryApp
        root=tk.Tk();root.withdraw()
        app=DiaryApp(root,self.path)
        try:
            deadline=time.monotonic()+5
            while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
            self.assertFalse(app.busy)
            self.assertEqual(list(app.nav),['今日','历史记录','AI 复盘','设置'])
            memory=Memory(self.path);rows=memory.timeline();memory.close()
            items=cards(rows)*3000
            app.diary.set_cards(items,{})
            self.assertLess(len(app.diary.find_all()),100)
            ids=app.diary.find_all()
            app.diary.set_cards(items,{})
            self.assertEqual(ids,app.diary.find_all())
            app.navigate('设置',refresh=False)
            self.assertEqual(app.tabs.select(),str(app.profile_tab))
            app.navigate('历史记录',refresh=False)
            self.assertEqual(app.tabs.select(),str(app.timeline_tab))
            self.assertIsNone(app.provider)
        finally:app.close()


if __name__=='__main__':unittest.main()
