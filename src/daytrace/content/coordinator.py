"""Nonblocking scheduler; only the collector thread commits evidence."""
import multiprocessing
import time

from .policy import normalize,digest,similar
from .worker import execute,gated_execute,memory_limit,close_job


class Worker:
    def __init__(self,request,target=execute):
        ctx=multiprocessing.get_context('spawn')
        self.receive,send=ctx.Pipe(duplex=False)
        gate=ctx.Event()
        self.process=ctx.Process(target=gated_execute,args=(send,request,gate,target),daemon=True)
        self.job=None
        self.source=request['source']
        self.deadline=time.monotonic()+(30 if self.source=='ocr' else 2.5)
        try:
            self.process.start()
            self.job=memory_limit(1024 if self.source=='ocr' else 384,self.process.sentinel,True)
            gate.set()
        except Exception:
            if self.process.pid:
                self.close()
            else:
                self.receive.close()
            raise
        finally:
            send.close()

    def poll(self):
        if self.receive.poll():
            try:
                return self.receive.recv()
            except (EOFError,OSError):
                return {'source':self.source,'status':'worker_failed'}
        if time.monotonic()>self.deadline:
            return {'source':self.source,'status':'timeout'}
        if not self.process.is_alive():
            return {'source':self.source,'status':'worker_failed'}
        return None

    def close(self):
        if self.job:
            close_job(self.job)
            self.job=None
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(.1)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(.1)
        self.receive.close()
        if not self.process.is_alive():
            self.process.close()


class Coordinator:
    def __init__(self,repo,engine,exclude=(),exclude_windows=(),permit=None,worker_factory=Worker,context_reader=None):
        from .desktop import context
        self.repo,self.engine=repo,engine
        self.exclude,self.exclude_windows=list(exclude),list(exclude_windows)
        self.permit=permit
        self.factory=worker_factory
        self.context_reader=context_reader or context
        self.worker=None
        self.key=None
        self.stable_since=0
        self.last_launch=-10**12
        self.last_sample_key=None
        self.last_ocr=-10**12
        self.generation=0
        self.recent={}  # Bounded per-window evidence cache; cleared on pause/stop.
        self.request=None
        self.grant_window=None
        self.grant_invalid=False
        self.dirty=False

    def hint(self,mono):
        if not self.dirty:
            self.stable_since=mono
        self.dirty=True

    def geometry_changed(self,hwnd):
        if self.grant_window and self.grant_window[0]==hwnd:
            self.grant_invalid=True
            self.invalidate()
            print('CONTENT: ocr / region_invalid; window geometry changed',flush=True)

    def invalidate(self,clear=False):
        self.generation+=1
        if self.worker:
            self.worker.close()
            self.worker=None
        self.request=None
        if clear:
            self.recent.clear()

    def close(self):
        self.invalidate(clear=True)

    def launch(self,source,context,now):
        self.request={'source':source,'context':context,'exclude':self.exclude,
            'exclude_windows':self.exclude_windows,'permit':self.permit,
            'generation':self.generation,'event':self.engine.event_id}
        self.last_launch=now
        self.dirty=False
        self.last_sample_key=self.key
        if source=='ocr':
            self.last_ocr=now
        try:
            self.worker=self.factory(self.request)
        except Exception:
            self.save({'source':source,'status':'worker_failed'},now)
            self.worker=None

    def save(self,result,now):
        if not self.request or self.request['generation']!=self.generation:
            return
        text=normalize(result.get('text',''))
        if result['status'] not in ('success','partial','low_quality','no_text'):
            text=''
        result={**result,'text':text or None,'char_count':len(text)}
        key=(self.request['context']['app'],self.request['context']['hwnd'])
        old=self.recent.get(key)
        if text:
            result['content_hash']=digest(text)
            if old and not self.repo.db.execute('SELECT 1 FROM content_samples WHERE id=?',(old[0],)).fetchone():
                old=None
            if old and old[2]>now-7*86_400_000 and similar(old[1],text):
                result.update(status='duplicate',text=None,duplicate_of=old[0])
        identifier=self.repo.content(self.engine.session,self.request['event'],now,result,
            self.generation,digest(str((self.engine.session,*key))))
        if identifier and text and result['status']!='duplicate':
            if len(self.recent)>=64:
                self.recent.pop(next(iter(self.recent)))
            self.recent[key]=(identifier,text,now)
        print('CONTENT: '+result['source']+' / '+result['status'],flush=True)

    def tick(self,mono,wall):
        from .desktop import matches
        obs=self.engine.current
        key=(self.engine.event_id,obs) if obs else None
        if key!=self.key:
            self.invalidate(clear=not obs or obs.state!='active')
            self.key=key
            self.stable_since=mono
            if obs and obs.state=='excluded' and self.engine.event_id:
                self.repo.content(self.engine.session,self.engine.event_id,wall,
                    {'source':'policy','status':'excluded'},self.generation)
        if self.engine.paused or self.engine.stopped or not obs or obs.state!='active':
            self.invalidate(clear=True)
            return
        if self.worker:
            result=self.worker.poll()
            if result is None:
                return
            self.worker.close()
            self.worker=None
            current=self.context_reader(self.exclude,self.exclude_windows)
            if not matches(self.request['context'],current):
                self.invalidate()
                return
            self.save(result,wall)
            if self.should_ocr(result,mono,current):
                self.launch('ocr',current,mono)
            elif self.permit and current['process'].casefold()==self.permit['app'].casefold() and result['source']=='uia' and len(normalize(result.get('text','')))<20:
                if self.grant_invalid:
                    self.save({'source':'ocr','status':'region_invalid'},wall)
                elif result['status'] in ('success','no_text') and not result.get('ocr_safe'):
                    self.save({'source':'ocr','status':'unsafe_region'},wall)
            return
        interval=15000 if self.last_sample_key==self.key and not self.dirty else 2000
        if mono-self.stable_since<800 or mono-self.last_launch<interval:
            return
        current=self.context_reader(self.exclude,self.exclude_windows)
        if not current or current['hwnd']!=obs.window or current['app']!=obs.app_id or current['title']!=obs.title:
            return
        self.launch('uia',current,mono)

    def should_ocr(self,result,mono,current):
        if not self.permit or self.grant_invalid or mono-self.last_ocr<60000:
            return False
        if result['source']!='uia' or result['status'] not in ('success','no_text') or not result.get('ocr_safe') or len(normalize(result.get('text','')))>=20:
            return False
        if current['process'].casefold()!=self.permit['app'].casefold():
            return False
        rect=current['rect']
        window=(current['hwnd'],current['pid'])
        size=(rect[2]-rect[0],rect[3]-rect[1])
        if self.grant_window is None:
            self.grant_window=window
        if window!=self.grant_window or size!=tuple(self.permit['size']):
            self.grant_invalid=True
            print('CONTENT: ocr / region_invalid; restart with a new explicit grant',flush=True)
            return False
        return True
