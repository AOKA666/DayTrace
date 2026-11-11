"""Synthetic browser addresses only; never reads the desktop."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from daytrace.browser import safe_url, extract_address, BrowserProbe
from daytrace.domain import Observation
from daytrace.engine import Engine
from daytrace.storage.repository import Repository
from daytrace.personalization.diary_model import build_display_cards


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'test.db'
        self.repo=Repository(self.path)
        self.engine=Engine(self.repo,100000,0,min_active_ms=5000)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def sample(self,ms,title='Page',host='trends.google.com',window=1):
        self.engine.sample(ms,100000+ms,Observation('active','chrome.exe','chrome',title,window,
                           'https://'+host+'/'+title,host))

    def active(self):
        return self.repo.db.execute("SELECT * FROM activity_intervals WHERE state='active' AND end_ms>start_ms ORDER BY start_ms").fetchall()

    def pages(self):
        return self.repo.db.execute('SELECT * FROM browser_pages ORDER BY captured_ms').fetchall()

    def test_title_changes_under_threshold_qualify_site_and_preserve_pages(self):
        for ms in range(0,12001,1000):
            self.sample(ms, str(ms//2000))
        self.engine.stop(12000,112000)
        self.assertEqual(len(self.active()),1)
        self.assertEqual(self.active()[0]['duration_ms'],12000)
        self.assertEqual([p['title'] for p in self.pages()],list(map(str,range(7))))
        self.assertEqual({p['event_id'] for p in self.pages()},{self.pages()[0]['event_id']})

    def test_short_total_site_not_persisted(self):
        self.sample(0,'one');self.sample(2000,'two');self.engine.stop(4000,104000)
        self.assertFalse(self.active());self.assertFalse(self.pages())

    def test_short_cross_domain_return_cannot_accumulate_threshold(self):
        self.sample(0,'first')
        self.sample(3000,'other',host='example.com')
        self.sample(4000,'second')
        self.sample(6000,'second')
        self.engine.stop(6000,106000)
        self.assertFalse(self.active())
        self.assertFalse(self.pages())

    def test_domain_switch_and_return_not_merged(self):
        for ms in range(0,6001,1000): self.sample(ms)
        for ms in range(7000,13001,1000): self.sample(ms,host='example.com')
        for ms in range(14000,20001,1000): self.sample(ms)
        self.engine.stop(21000,121000)
        self.assertEqual(len(self.active()),3)
        self.assertEqual(sum(r['duration_ms'] for r in self.active()),21000)

    def test_boundaries_reset_pending_and_clear_in_memory_pages(self):
        for state in ('excluded','unknown','locked','idle'):
            self.sample(self.engine.last_mono+1000,'a')
            self.sample(self.engine.last_mono+1000,'b')
            self.engine.sample(self.engine.last_mono+1000,110000,Observation(state))
            self.assertIsNone(self.engine.pending)
            self.assertEqual(self.engine.pending_pages,[])
        self.assertFalse(self.pages())

    def test_different_window_not_same_site(self):
        self.sample(0);self.sample(3000,'b',window=2);self.sample(6000,'c',window=1)
        self.assertFalse(self.pages())

    def test_private_delete_expiry_and_restart(self):
        for ms in range(0,6001,1000): self.sample(ms)
        identifier=self.active()[0]['id']
        with self.repo.db:
            self.repo.db.execute("UPDATE activity_intervals SET state='excluded' WHERE id=?",(identifier,))
        self.assertFalse(self.pages())
        self.engine.stop(7000,107000)
        self.repo.close();self.repo=Repository(self.path)
        self.assertFalse(self.pages())
        other=Engine(self.repo,110000,0,min_active_ms=0)
        other.sample(0,110000,Observation('active','chrome.exe','chrome','x',1,'https://example.com/a','example.com'))
        other.stop(1000,111000)
        self.assertEqual(len(self.pages()),1)
        self.repo.cleanup(110000+7*86400000)
        self.assertFalse(self.pages())
        self.assertEqual(self.repo.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_idle_backtrack_removes_later_pages(self):
        for ms in range(0,10001,1000):self.sample(ms,str(ms))
        self.engine.idle_ms=5000
        self.engine.sample(11000,111000,self.engine.current,5000)
        self.assertTrue(all(p['captured_ms']<106000 for p in self.pages()))
        self.assertEqual(self.active()[0]['end_ms'],106000)

    def test_safe_url(self):
        self.assertEqual(safe_url('https://Trends.Google.com/trends/explore?q=secret#token'),
                         ('https://trends.google.com/trends/explore','trends.google.com'))
        for value in ('search words','javascript:alert(1)','file:///C:/secret','https://a:b@example.com',
                      'https://banking.example.com/pay','https://example.com:bad/'):
            self.assertIsNone(safe_url(value))

    def test_address_reader_never_enters_document_or_password(self):
        def node(kind=50033,name='',children=(),password=False,hidden=False,focus=False):
            return SimpleNamespace(CurrentControlType=kind,CurrentName=name,children=children,
                password=password,hidden=hidden,CurrentHasKeyboardFocus=focus)
        edit=node(50004,'Address and search bar')
        value=SimpleNamespace(CurrentValue='https://trends.google.com/trends/?q=secret')
        edit.GetCurrentPattern=lambda _:SimpleNamespace(QueryInterface=lambda _:value)
        adapter=SimpleNamespace(password=lambda n:n.password,hidden=lambda n:n.hidden,
             children=lambda n,limit:n.children[:limit],mod=SimpleNamespace(IUIAutomationValuePattern=object))
        root=node(children=[node(50030,children=[edit])])
        self.assertEqual(extract_address(root,adapter,time.monotonic()+1)['status'],'unavailable')
        root.children=[edit]
        self.assertEqual(extract_address(root,adapter,time.monotonic()+1)['domain'],'trends.google.com')
        edit.CurrentHasKeyboardFocus=True
        self.assertEqual(extract_address(root,adapter,time.monotonic()+1)['status'],'editing')
        edit.password=True
        self.assertEqual(extract_address(root,adapter,time.monotonic()+1)['status'],'unavailable')

    def test_probe_rejects_result_on_title_change_pause_and_error(self):
        workers=[]
        class Worker:
            def __init__(self,request):self.closed=False;workers.append(self)
            def poll(self):return {'status':'success','url':'https://example.com/page'}
            def close(self):self.closed=True
        ctx={'app':'chrome','hwnd':1,'title':'A'}
        probe=BrowserProbe(factory=Worker,context_reader=lambda *args:dict(ctx))
        a=Observation('active','chrome.exe','chrome','A',1)
        self.assertIsNone(probe.resolve(a,0))
        self.assertEqual(probe.resolve(a,100).domain,'example.com')
        ctx['title']='B'
        b=Observation('active','chrome.exe','chrome','B',1)
        self.assertIsNone(probe.resolve(b,600))
        probe.resolve(Observation('paused'),700)
        self.assertTrue(all(w.closed for w in workers))
        self.assertIsNone(probe.result)

    def test_local_details_display_and_cloud_scope(self):
        from daytrace.personalization.store import Memory
        from daytrace.personalization.classifier import Classifier
        for ms in range(0,10001,1000):self.sample(ms,str(ms//2000))
        self.engine.stop(11000,111000)
        memory=Memory(self.path,cleanup=False)
        try:
            memory.now=lambda:112000
            rows=memory.timeline()
            active=[r for r in rows if r['state']=='active']
            self.assertEqual(len(active),1)
            self.assertEqual(active[0]['browser_domain'],'trends.google.com')
            cards=build_display_cards(rows,5000,0,0)
            self.assertEqual(cards[0]['title'],'0')
            self.assertNotIn('trends.google.com', cards[0]['title'])
            self.assertNotIn('浏览', cards[0]['title'])
            evidence=memory.evidence(active[0]['interval_id'])
            self.assertEqual(len(evidence['browser_pages']),6)
            payload=Classifier(memory).payload([evidence])
            self.assertNotIn('browser_pages',payload['evidence'][0])
            self.assertNotIn('url',payload['evidence'][0])
            memory.delete_interval(active[0]['interval_id'])
            self.assertFalse(self.pages())
        finally:memory.close()

    def test_extension_migration_preserves_existing_rows(self):
        self.sample(0);self.sample(5000);self.engine.stop(6000,106000)
        before=[tuple(r) for r in self.repo.db.execute('SELECT * FROM activity_intervals')]
        sql=(Path(__file__).parents[1]/'src/daytrace/storage/migrations/008_browser_extension_down.sql').read_text()
        self.repo.db.executescript(sql)
        self.repo.close();self.repo=Repository(self.path)
        self.assertEqual(before,[tuple(r) for r in self.repo.db.execute('SELECT * FROM activity_intervals')])
        self.assertEqual(self.repo.db.execute("SELECT version FROM schema_extensions WHERE name='browser_pages'").fetchone()[0],1)


if __name__=='__main__':unittest.main()
