import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))

from daytrace.engine import Engine
from daytrace.domain import Observation
from daytrace.storage.repository import Repository
from daytrace.content.uia import extract_tree
from daytrace.content.policy import normalize, similar, sensitive_window
import time
from daytrace.content.coordinator import Coordinator
from unittest.mock import patch
import contextlib
import io
from types import SimpleNamespace


def stalled_worker(connection,request):
    time.sleep(30)


class IsolationTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Windows Job Object integration')
    def test_parent_crash_terminates_content_child(self):
        import subprocess
        import ctypes as c
        from ctypes import wintypes as w
        python=getattr(sys,'_base_executable',sys.executable)
        result=subprocess.run([python,str(Path(__file__).parent/'fixtures/content_parent.py')],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        pid=int(result.stdout.strip())
        k=c.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]; k.OpenProcess.restype=w.HANDLE
        k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
        k.CloseHandle.argtypes=[w.HANDLE]
        handle=k.OpenProcess(0x100000,False,pid)
        if handle:
            try:
                self.assertEqual(k.WaitForSingleObject(handle,2000),0)
            finally:
                k.CloseHandle(handle)

    @unittest.skipUnless(sys.platform=='win32','Windows Job Object integration')
    def test_timeout_terminates_child_promptly(self):
        from daytrace.content.coordinator import Worker
        worker=Worker({'source':'uia'},target=stalled_worker)
        started=time.monotonic()
        try:
            worker.deadline=0
            self.assertEqual(worker.poll()['status'],'timeout')
        finally:
            worker.close()
        self.assertLess(time.monotonic()-started,2)

    def test_network_requests_are_rejected(self):
        from daytrace.content.worker import deny_network
        with self.assertRaises(PermissionError):
            deny_network('socket.connect',())


class OCRGuardTests(unittest.TestCase):
    def test_transparent_window_is_not_safe(self):
        with patch('daytrace.content.desktop.WindowsAPI') as factory:
            factory.return_value.u.GetWindowLongW.return_value=0x80000
            self.assertFalse(self.original_unobscured(1,(0,0,100,100)))

    def setUp(self):
        from daytrace.content.desktop import unobscured
        self.original_unobscured=unobscured
        self.request={'context':dict(CONTEXT),'exclude':[],'exclude_windows':[],
            'permit':{'app':'test.exe','region':(0,0,100,100),'size':(800,600)}}
        self.stack=contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.engine=self.stack.enter_context(patch('daytrace.content.ocr.create_engine'))
        self.ctx=self.stack.enter_context(patch('daytrace.content.desktop.context',return_value=dict(CONTEXT)))
        self.ui=self.stack.enter_context(patch('daytrace.content.uia.extract',return_value={'status':'no_text','ocr_safe':True}))
        self.clear=self.stack.enter_context(patch('daytrace.content.desktop.unobscured',return_value=True))
        self.screen=SimpleNamespace(__enter__=None)
        from unittest.mock import MagicMock
        self.screen=MagicMock()
        self.array=MagicMock()
        self.array.__getitem__.return_value.copy.return_value=self.array
        self.stack.enter_context(patch.dict(sys.modules,{'mss':SimpleNamespace(mss=self.screen),
            'numpy':SimpleNamespace(asarray=lambda shot:self.array)}))

    def capture(self):
        from daytrace.content.ocr import capture
        return capture(self.request)

    def test_no_permission_or_invalid_region_never_captures(self):
        self.request['permit']=None
        self.assertEqual(self.capture()['status'],'not_authorized')
        self.screen.assert_not_called()
        self.engine.assert_not_called()

    def test_password_unknown_or_timeout_never_captures(self):
        for value in ({'status':'success','ocr_safe':False},{'status':'timeout'},{'status':'unavailable'}):
            self.ui.return_value=value
            self.assertEqual(self.capture()['status'],'unsafe_region')
        self.screen.assert_not_called()

    def test_occlusion_never_captures(self):
        self.clear.return_value=False
        self.assertEqual(self.capture()['status'],'stale')
        self.screen.assert_not_called()

    def test_resize_never_captures(self):
        self.request['context']['rect']=(0,0,801,600)
        self.assertEqual(self.capture()['status'],'region_invalid')
        self.screen.assert_not_called()

    def test_switch_after_capture_discards_and_clears_pixels(self):
        self.ctx.side_effect=[dict(CONTEXT),dict(CONTEXT),None]
        self.assertEqual(self.capture()['status'],'stale')
        self.array.fill.assert_called_once_with(0)

    def test_ocr_exception_still_clears_pixels(self):
        with patch('daytrace.content.ocr.recognize',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):
                self.capture()
        self.array.fill.assert_called_once_with(0)


CONTEXT={'hwnd':1,'pid':2,'app':'app','process':'test.exe','title':'fixture','rect':(0,0,800,600)}


class FakeWorker:
    instances=[]
    def __init__(self,request):
        self.request=request
        self.result=None
        self.closed=False
        self.instances.append(self)
    def poll(self): return self.result
    def close(self): self.closed=True


class CoordinatorTests(unittest.TestCase):
    def test_auto_permission_uses_each_foreground_window_and_cancels_resize(self):
        self.collector.permit={'auto':True,'retain':True,'days':7}
        result={'source':'uia','status':'no_text','ocr_safe':True}
        self.assertTrue(self.collector.should_ocr(result,1000,self.context))
        self.collector.launch('ocr',self.context,1000)
        permit=FakeWorker.instances[-1].request['permit']
        self.assertEqual(permit['app'],'test.exe')
        self.assertEqual(permit['region'],(0,0,800,600))
        worker=self.collector.worker
        self.collector.geometry_changed(self.context['hwnd'])
        self.assertTrue(worker.closed)
        changed=dict(self.context,process='chrome.exe',rect=(0,0,3840,2160))
        self.assertTrue(self.collector.should_ocr(result,62000,changed))
        self.assertFalse(self.collector.should_ocr(dict(result,ocr_safe=False),62000,changed))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.repo=Repository(Path(self.temp.name)/'test.db')
        self.engine=Engine(self.repo,100000,0)
        self.engine.sample(0,100000,Observation('active','test.exe','app','fixture',1))
        self.context=dict(CONTEXT)
        FakeWorker.instances=[]
        self.collector=Coordinator(self.repo,self.engine,worker_factory=FakeWorker,
            context_reader=lambda *args:self.context)
        self.output=io.StringIO()
        self.redirect=contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()

    def tearDown(self):
        self.collector.close()
        self.repo.close()
        self.redirect.__exit__(None,None,None)
        self.temp.cleanup()

    def begin(self):
        self.collector.tick(0,100000)
        self.collector.tick(800,100800)
        return FakeWorker.instances[-1]

    def count(self):
        return self.repo.db.execute('SELECT COUNT(*) FROM content_samples').fetchone()[0]

    def test_debounce_periodic_limit_dedup_and_no_body_logs(self):
        self.collector.tick(0,100000)
        self.collector.tick(799,100799)
        self.assertFalse(FakeWorker.instances)
        self.collector.tick(800,100800)
        FakeWorker.instances[-1].result={'source':'uia','status':'success','text':'synthetic evidence password=secretvalue'}
        self.collector.tick(1000,101000)
        self.collector.tick(15000,115000)
        self.assertEqual(len(FakeWorker.instances),1)
        self.collector.tick(15800,115800)
        FakeWorker.instances[-1].result={'source':'uia','status':'success','text':'synthetic evidence password=secretvalue'}
        self.collector.tick(16000,116000)
        rows=self.repo.db.execute('SELECT * FROM content_samples ORDER BY captured_ms').fetchall()
        self.assertEqual([r['status'] for r in rows],['success','duplicate'])
        self.assertEqual(rows[1]['duplicate_of'],rows[0]['id'])
        self.assertIsNone(rows[1]['text'])
        self.assertNotIn('secretvalue',rows[0]['text'])
        self.assertNotIn('synthetic evidence',self.output.getvalue())
        self.assertTrue(all(w.request['source']=='uia' for w in FakeWorker.instances))

    def test_pause_cancels_result_and_resume_requires_new_sample(self):
        worker=self.begin()
        worker.result={'source':'uia','status':'success','text':'stale'}
        self.engine.pause(900,100900)
        self.collector.tick(900,100900)
        self.assertTrue(worker.closed)
        self.assertEqual(self.count(),0)
        self.engine.resume(1000,101000)
        self.engine.sample(1100,101100,Observation('active','test.exe','app','fixture',1))
        self.collector.tick(1100,101100)
        self.collector.tick(3000,103000)
        self.assertEqual(len(FakeWorker.instances),2)

    def test_switch_after_read_discards_result(self):
        worker=self.begin()
        worker.result={'source':'uia','status':'success','text':'stale'}
        self.context={**CONTEXT,'hwnd':99}
        self.collector.tick(1000,101000)
        self.assertEqual(self.count(),0)

    def test_excluded_is_anonymous_and_idle_cancels(self):
        worker=self.begin()
        self.engine.sample(900,100900,Observation('idle'))
        self.collector.tick(900,100900)
        self.assertTrue(worker.closed)
        self.engine.sample(1000,101000,Observation('excluded'))
        self.collector.tick(1000,101000)
        row=self.repo.db.execute('SELECT c.*,e.process_name,e.title FROM content_samples c JOIN activity_events e ON e.id=c.event_id').fetchone()
        self.assertEqual(row['status'],'excluded')
        for field in ('text','window_token','process_name','title'):
            self.assertIsNone(row[field])

    def test_ocr_requires_safe_success_and_rate_limit(self):
        self.collector.permit={'app':'test.exe','region':(0,0,100,100),'size':(800,600)}
        for status in ('timeout','unavailable','excluded','dependency_missing'):
            self.assertFalse(self.collector.should_ocr({'source':'uia','status':status,'ocr_safe':True},0,CONTEXT))
        self.assertFalse(self.collector.should_ocr({'source':'uia','status':'no_text'},0,CONTEXT))
        result={'source':'uia','status':'no_text','ocr_safe':True}
        self.assertTrue(self.collector.should_ocr(result,0,CONTEXT))
        self.collector.last_ocr=0
        self.assertFalse(self.collector.should_ocr(result,59999,CONTEXT))
        self.assertTrue(self.collector.should_ocr(result,60000,CONTEXT))
        self.assertFalse(self.collector.should_ocr(result,60000,{**CONTEXT,'rect':(0,0,801,600)}))
        self.assertFalse(self.collector.should_ocr(result,120000,CONTEXT))

    def test_worker_failure_is_status_not_collector_crash(self):
        worker=self.begin()
        worker.result={'source':'uia','status':'timeout'}
        self.collector.tick(1000,101000)
        self.assertEqual(self.repo.db.execute('SELECT status FROM content_samples').fetchone()[0],'timeout')
        self.assertFalse(self.engine.stopped)

    def test_geometry_event_irrevocably_revokes_grant(self):
        worker=self.begin()
        self.collector.grant_window=(1,2)
        self.collector.geometry_changed(1)
        self.assertTrue(worker.closed)
        self.assertTrue(self.collector.grant_invalid)

    def test_old_event_result_rejected_after_stop(self):
        worker=self.begin()
        self.engine.stop(900,100900)
        self.collector.save({'source':'uia','status':'success','text':'stale'},101000)
        self.assertEqual(self.count(),0)


class FakeTree:
    def password(self,n): return n.get('password',False)
    def hidden(self,n): return n.get('hidden',False)
    def children(self,n,limit): return n.get('children',[])[:limit]
    def visible_text(self,n,limit):
        if n.get('password') or n.get('hidden'):
            raise AssertionError('Private content accessed')
        return n.get('text','')[:limit]


class ExtractionTests(unittest.TestCase):
    def test_text_beyond_old_eight_level_limit(self):
        node={'text':'visible nested document'}
        for _ in range(12):
            node={'children':[node]}
        result=self.extract(node)
        self.assertEqual(result['text'],'visible nested document')
        self.assertEqual(result['status'],'success')

    def test_partial_scan_does_not_discard_complete_sibling(self):
        root={'text':'unsafe parent aggregate','children':[
            {'text':'visible complete text','children':[{}]},
            {'text':'uninspected aggregate','children':[{}]*10}]}
        result=self.extract(root,max_nodes=5)
        self.assertEqual(result['text'],'visible complete text')
        self.assertEqual(result['status'],'partial')
        self.assertFalse(result['ocr_safe'])

    def test_empty_truncated_scan_has_distinct_status(self):
        result=self.extract({'children':[{}]*10},max_nodes=2)
        self.assertEqual(result['status'],'scan_limited')

    def test_zero_rectangle_container_is_not_hidden(self):
        from daytrace.content.uia import ComAdapter
        adapter=ComAdapter.__new__(ComAdapter)
        node=SimpleNamespace(CurrentIsOffscreen=False,CurrentBoundingRectangle=SimpleNamespace(left=0,right=0,top=0,bottom=0))
        self.assertFalse(adapter.hidden(node))
        node.CurrentIsOffscreen=True
        self.assertTrue(adapter.hidden(node))

    def test_empty_range_geometry_never_reads_text(self):
        from daytrace.content.uia import ComAdapter
        from unittest.mock import Mock
        adapter=ComAdapter.__new__(ComAdapter)
        adapter.mod=SimpleNamespace(IUIAutomationTextPattern=object())
        visible=SimpleNamespace(GetBoundingRectangles=lambda:(),GetText=Mock())
        pattern=SimpleNamespace(GetVisibleRanges=lambda:SimpleNamespace(Length=1,GetElement=lambda i:visible))
        node=SimpleNamespace(CurrentIsPassword=False,CurrentIsOffscreen=False,
            GetCurrentPropertyValue=lambda _:True,
            GetCurrentPattern=lambda _:SimpleNamespace(QueryInterface=lambda _:pattern))
        self.assertEqual(adapter.visible_text(node,100),'')
        visible.GetText.assert_not_called()

    def test_failed_range_does_not_erase_other_visible_text_or_allow_ocr(self):
        class Adapter(FakeTree):
            def visible_text(self,node,limit):
                if node.get('broken'):
                    raise OSError('synthetic provider failure')
                return super().visible_text(node,limit)
        result=extract_tree({'children':[{'text':'visible'},{'broken':True}]},Adapter(),time.monotonic()+1)
        self.assertEqual(result['text'],'visible')
        self.assertEqual(result['status'],'partial')
        self.assertFalse(result['ocr_safe'])

    def extract(self,node,**kw):
        return extract_tree(node,FakeTree(),time.monotonic()+1,**kw)

    def test_password_hidden_and_container_text_never_read(self):
        result = self.extract({'text':'parent secret','children':[
            {'text':'visible fixture'}, {'password':True,'text':'secret','children':[{'text':'secret'}]},
            {'hidden':True,'text':'hidden','children':[{'text':'hidden'}]}]})
        self.assertEqual(result['text'],'visible fixture')
        self.assertFalse(result['ocr_safe'])

    def test_limits_disable_ocr(self):
        result = self.extract({'children':[{'text':'x'}]*1000},max_nodes=3)
        self.assertTrue(result['truncated'])
        self.assertFalse(result['ocr_safe'])

    def test_timeout_and_sensitive_leaf(self):
        self.assertEqual(extract_tree({},FakeTree(),0)['status'],'timeout')
        self.assertEqual(self.extract({'text':'Private browsing'})['status'],'excluded')

    def test_redaction_and_similarity(self):
        self.assertNotIn('secretvalue',normalize('password=secretvalue'))
        self.assertTrue(similar('abc'*100,'abc'*99+'abd'))
        self.assertFalse(similar('document one','document two'))
        self.assertTrue(sensitive_window('支付宝 - Chrome'))


class ContentStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_v1_migration_preserves_existing_activity(self):
        db = sqlite3.connect(self.path)
        db.executescript((Path(__file__).parents[1] / 'src/daytrace/storage/migrations/001_activity.sql').read_text())
        db.execute("INSERT INTO devices VALUES ('existing','windows')")
        db.commit()
        db.close()
        repo = Repository(self.path)
        try:
            self.assertEqual(repo.device_id, 'existing')
            self.assertEqual(repo.db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(repo.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            repo.close()

    def test_link_retention_and_stopped_rejection(self):
        repo = Repository(self.path)
        try:
            engine = Engine(repo, 1000, 0)
            engine.sample(1, 1001, Observation('active','test.exe','app','fixture',1))
            event = repo.db.execute("SELECT id FROM activity_events WHERE state='active'").fetchone()[0]
            result = {'source':'uia','status':'success','text':'synthetic visible content'}
            self.assertIsNotNone(repo.content(engine.session,event,1001,result,1))
            engine.stop(2,1002)
            self.assertIsNone(repo.content(engine.session,event,1002,result,1))
            repo.cleanup(1001+7*86_400_000)
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM content_samples').fetchone()[0],0)
            self.assertFalse(repo.db.execute('PRAGMA foreign_key_check').fetchall())
        finally:
            repo.close()

    def test_cli_json_unicode_and_body_opt_in(self):
        from daytrace.cli import content_records
        import json
        now=time.time_ns()//1_000_000
        repo=Repository(self.path)
        try:
            engine=Engine(repo,now,0)
            engine.sample(0,now,Observation('active','test.exe','app','fixture',1))
            repo.content(engine.session,engine.event_id,now,{'source':'uia','status':'success','text':'合成中文证据'},1)
        finally:
            repo.close()
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            content_records(self.path,30,True,True)
        encoded=output.getvalue()
        self.assertTrue(encoded.isascii())
        self.assertEqual(json.loads(encoded)['text'],'合成中文证据')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            content_records(self.path,30,False,True)
        self.assertNotIn('text',json.loads(output.getvalue()))

    def test_compact_records_group_duplicates_but_preserve_tab_changes(self):
        from daytrace.cli import content_records
        now=time.time_ns()//1_000_000
        repo=Repository(self.path)
        try:
            engine=Engine(repo,now,0)
            engine.sample(0,now,Observation('active','Code.exe','code','fixture',1))
            original=repo.content(engine.session,engine.event_id,now,{'source':'uia','status':'partial','text':'synthetic editor','char_count':16},1)
            for offset in (1,2):
                repo.content(engine.session,engine.event_id,now+offset,{'source':'uia','status':'duplicate','duplicate_of':original,'char_count':16},1)
            for offset,title in ((3,'Python 文档'),(4,'GitHub')):
                engine.sample(offset,now+offset,Observation('active','chrome.exe','chrome',title+' - Google Chrome',2))
                repo.content(engine.session,engine.event_id,now+offset,{'source':'uia','status':'no_text'},1)
        finally:
            repo.close()
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            content_records(self.path,10,True,False)
        text=output.getvalue()
        self.assertEqual(text.count('Code.exe'),1)
        self.assertEqual(text.count('chrome.exe'),2)
        self.assertIn('Python 文档',text)
        self.assertIn('GitHub',text)
        self.assertIn('synthetic editor',text)
        self.assertNotIn('Google Chrome',text)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            content_records(self.path,10,False,False,raw=True)
        self.assertEqual(output.getvalue().count('Code.exe'),3)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            content_records(self.path,2,False,False)
        self.assertNotIn('Code.exe',output.getvalue())

    def test_cli_screenshots_require_all_permissions(self):
        from daytrace.cli import main
        with patch('daytrace.service.run') as run, contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--db',str(self.path),'start']),0)
            self.assertFalse(run.call_args.args[4])
            self.assertIsNone(run.call_args.args[-1])
            run.reset_mock()
            self.assertEqual(main(['--db',str(self.path),'start','--content','--screenshots']),1)
            run.assert_not_called()

    def test_same_visit_merges_changed_text_and_status_but_not_return_visit(self):
        from daytrace.cli import content_records
        now=time.time_ns()//1_000_000
        repo=Repository(self.path)
        try:
            engine=Engine(repo,now,0)
            engine.sample(0,now,Observation('active','chrome.exe','chrome','BetaList - Google Chrome',1))
            for offset,body,status in ((0,'first version','partial'),(1,'changed version','partial'),(2,None,'excluded')):
                repo.content(engine.session,engine.event_id,now+offset,{'source':'uia','status':status,'text':body},1)
            engine.sample(3,now+3,Observation('active','Code.exe','code','editor',2))
            # No content sample from the interruption: event identity still prevents merging.
            engine.sample(4,now+4,Observation('active','chrome.exe','chrome','BetaList - Google Chrome',1))
            repo.content(engine.session,engine.event_id,now+4,{'source':'uia','status':'partial','text':'return visit'},1)
        finally:
            repo.close()
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            content_records(self.path,20,True,False)
        self.assertEqual(output.getvalue().count('chrome.exe | BetaList'),2)
        self.assertIn('excluded+partial',output.getvalue())
        self.assertNotIn('first version',output.getvalue())
        self.assertNotIn('changed version',output.getvalue())
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            content_records(self.path,20,False,False,raw=True)
        self.assertEqual(output.getvalue().count('chrome.exe | BetaList'),4)

    def test_delete_removes_content_and_restart_is_empty(self):
        from daytrace.cli import main
        repo=Repository(self.path)
        engine=Engine(repo,1000,0)
        engine.sample(0,1000,Observation('active','test.exe','app','fixture',1))
        repo.content(engine.session,engine.event_id,1000,{'source':'uia','status':'success','text':'fixture'},1)
        engine.stop(1,1001)
        repo.close()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--db',str(self.path),'delete','--yes']),0)
        self.assertFalse(self.path.exists())
        self.assertFalse(Path(str(self.path)+'-wal').exists())
        repo=Repository(self.path)
        try:
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM content_samples').fetchone()[0],0)
        finally:
            repo.close()
