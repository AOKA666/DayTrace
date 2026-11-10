"""Opt-in batched diary analysis, isolated from UI and collector threads.

No schema changes. Network runs outside transactions; policy, session controls,
manual revisions and input fingerprints are checked again before committing.
"""
from .store import Memory
from .classifier import Classifier, signature
from .provider import TextProvider, DEEPSEEK_ENDPOINT, DEEPSEEK_MODEL
from .diary_model import DEFAULT_CATEGORIES
from ..preferences import options
from ..storage.repository import is_running
from ..content.policy import normalize


def validate(response,payload):
    if not isinstance(response,list) or len(response)>len(payload['evidence']):raise ValueError('Invalid diary response')
    allowed={e['interval_id']:set(e['evidence_ids']) for e in payload['evidence']}
    seen=set()
    for item in response:
        if not isinstance(item,dict) or set(item)!={'interval_id','label','category','project','description','evidence_ids'}:raise ValueError('Invalid diary fields')
        identifier=item['interval_id']
        if not isinstance(identifier,str) or identifier not in allowed or identifier in seen:raise ValueError('Invalid diary ID')
        seen.add(identifier)
        for key,limit in [('label',60),('category',160),('project',160),('description',160)]:
            if not isinstance(item[key],str) or len(item[key])>limit:raise ValueError('Invalid diary text')
            item[key]=normalize(item[key])
        if not item['label'].strip() or item['category'] not in payload['categories'] or item['project'] not in ['',*payload['projects']]:raise ValueError('Invalid diary classification')
        refs=item['evidence_ids']
        if not isinstance(refs,list) or not refs or any(not isinstance(r,str) for r in refs) or not set(refs)<=allowed[identifier]:raise ValueError('Invalid diary evidence')
    return response


def capture_state(memory):
    if not is_running(memory.repo.path):return 'stopped'
    session=memory.db.execute('SELECT status FROM capture_sessions WHERE ended_ms IS NULL ORDER BY rowid DESC LIMIT 1').fetchone()
    return 'paused' if session and session[0]=='paused' else 'running'


def controls(memory):
    # New pause/resume/stop requests invalidate in-flight analysis, even if resumed.
    row=memory.db.execute('SELECT count(*),max(requested_ms) FROM control_commands').fetchone()
    return tuple(row)


def policy(config):
    return tuple(config.get(k) for k in ('auto_ai','ai_since_ms','ai_endpoint','ai_model'))


def evidence_hash(evidence):
    return signature({k:evidence[k] for k in ('id','start_ms','end_ms','state','event_id','title','text','evidence_ids')})


def tick(database,cancel,analyze=True,provider_factory=TextProvider):
    memory=Memory(database,cleanup=False)
    try:
        config=options(database)
        state=capture_state(memory)
        result={'state':state,'options':config,'note':''}
        if not analyze or cancel.is_set():return result
        # Rule/history classification remains local and works with cloud disabled.
        pending=[r[0] for r in memory.db.execute("SELECT i.id FROM activity_intervals i LEFT JOIN task_results r ON r.interval_id=i.id WHERE i.state='active' AND (r.interval_id IS NULL OR r.source='pending') ORDER BY i.start_ms DESC LIMIT 100")]
        if pending:Classifier(memory).analyze(pending)
        if config.get('auto_ai') is not True or state=='paused':return result
        since=config.get('ai_since_ms')
        if not isinstance(since,int):return result
        # Do not resend old AI results or manual decisions. At most 20 closed events.
        ids=[r[0] for r in memory.db.execute("""SELECT i.id FROM activity_intervals i
            LEFT JOIN task_results r ON r.interval_id=i.id
            WHERE i.state='active' AND i.start_ms>=? AND i.end_ms<=?
            AND (r.interval_id IS NULL OR (r.manual=0 AND r.source IN ('fallback','pending')))
            ORDER BY i.start_ms LIMIT 20""",(since,memory.now()-60_000))]
        evidence=Classifier(memory).prepare(ids)
        if not evidence:return result
        profile=memory.profile()
        payload={'mode':'diary','profile':profile,'categories':profile['activities'] or DEFAULT_CATEGORIES,
            'projects':profile['projects'],'evidence':[{'interval_id':e['id'],'evidence_ids':e['evidence_ids'],
            'app':e['process_name'],'title':e['title'],'text':e['text'][:2000]} for e in evidence]}
        generation=memory.generation();control_version=controls(memory)
        profile_version=signature(memory.export())
        hashes={e['id']:evidence_hash(e) for e in evidence}
        if cancel.is_set() or policy(options(database))!=policy(config):return result
        provider=provider_factory(config.get('ai_endpoint') or DEEPSEEK_ENDPOINT,config.get('ai_model') or DEEPSEEK_MODEL,budget=2)
        provider.cancelled=cancel
        def still_authorized():
            if cancel.is_set() or policy(options(database))!=policy(config) or controls(memory)!=control_version or memory.generation()!=generation:return False
            for identifier,digest in hashes.items():
                current=memory.evidence(identifier)
                if not current or evidence_hash(current)!=digest:return False
            return True
        provider.send_guard=still_authorized
        if not still_authorized():return result
        try:response=validate(provider.classify(payload),payload)
        except Exception:
            result['note']='AI 暂时未能整理，保留原始记录；5 分钟后重试。'
            result['cooldown']=300
            return result
        with memory.repo.transaction():
            if cancel.is_set() or policy(options(database))!=policy(config) or controls(memory)!=control_version or memory.generation()!=generation or signature(memory.export())!=profile_version:return result
            for item in response:
                identifier=item['interval_id']
                fresh=memory.evidence(identifier)
                prior=memory.db.execute('SELECT manual FROM task_results WHERE interval_id=?',(identifier,)).fetchone()
                if not fresh or evidence_hash(fresh)!=hashes[identifier] or (prior and prior[0]):continue
                task=memory.task(item['label'],item['category'],item['project'])
                memory.db.execute("""INSERT INTO task_results(interval_id,event_id,task_id,reliability,source,reason)
                    VALUES (?,?,?,'tentative','ai',?) ON CONFLICT(interval_id) DO UPDATE SET
                    task_id=excluded.task_id,reliability='tentative',source='ai',reason=excluded.reason,revision=task_results.revision+1""",
                    (identifier,fresh['event_id'],task,item['description']))
        result['note']='后台 AI 已整理新活动；不确定的判断等待你确认。'
        if not response:result['cooldown']=300
        return result
    finally:memory.close()
