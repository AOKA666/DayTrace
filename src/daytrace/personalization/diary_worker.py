"""Opt-in batched diary analysis, isolated from UI and collector threads.

No schema changes. Network runs outside transactions; policy, session controls,
manual revisions and input fingerprints are checked again before committing.
"""
from .store import Memory
from .classifier import Classifier, signature
from .provider import TextProvider, Vault, DEEPSEEK_ENDPOINT, DEEPSEEK_MODEL, IncompleteResponseError
from .diary_model import DEFAULT_CATEGORIES
from ..preferences import options
from ..storage.repository import is_running
from ..content.policy import normalize

DIARY_BATCH_SIZE=8
SUCCESS_BATCH_DELAY_SECONDS=3
IDLE_AI_POLL_SECONDS=60
FAILURE_RETRY_SECONDS=300


def _canonical_choice(value, choices, *, leaf=False):
    value=normalize(value).strip()
    exact={normalize(choice).strip().casefold():choice for choice in choices}
    if value.casefold() in exact:return exact[value.casefold()]
    if leaf:
        matches=[choice for choice in choices if normalize(choice).split('/')[-1].strip().casefold()==value.casefold()]
        if len(matches)==1:return matches[0]
    raise ValueError('Invalid diary classification')


def validate(response,payload,partial=False):
    if not isinstance(response,list) or len(response)>len(payload['evidence']):raise ValueError('Invalid diary response')
    allowed={e['interval_id']:set(e['evidence_ids']) for e in payload['evidence']}
    seen=set()
    valid=[]
    for item in response:
        try:
            if not isinstance(item,dict) or set(item)!={'interval_id','label','category','project','description','evidence_ids','certainty','uncertainty_reason'}:raise ValueError('Invalid diary fields')
            item=dict(item)
            identifier=item['interval_id']
            if not isinstance(identifier,str) or identifier not in allowed or identifier in seen:raise ValueError('Invalid diary ID')
            for key,limit in [('label',60),('category',160),('project',160),('description',160),('uncertainty_reason',160)]:
                if not isinstance(item[key],str) or len(item[key])>limit:raise ValueError('Invalid diary text')
                item[key]=normalize(item[key])
            if not item['label'].strip():raise ValueError('Invalid diary classification')
            item['category']=_canonical_choice(item['category'],payload['categories'],leaf=True)
            item['project']='' if not item['project'].strip() else _canonical_choice(item['project'],payload['projects'])
            if item['certainty'] not in ('supported','tentative','unknown'):raise ValueError('Invalid diary certainty')
            if item['certainty']!='supported' and not item['uncertainty_reason'].strip():raise ValueError('Missing uncertainty reason')
            refs=item['evidence_ids']
            if not isinstance(refs,list) or not refs or any(not isinstance(r,str) for r in refs) or not set(refs)<=allowed[identifier]:raise ValueError('Invalid diary evidence')
            seen.add(identifier)
            valid.append(item)
        except (KeyError,TypeError,ValueError):
            if not partial:raise
    return valid


def capture_state(memory):
    if not is_running(memory.repo.path):return 'stopped'
    session=memory.db.execute('SELECT status FROM capture_sessions WHERE ended_ms IS NULL ORDER BY rowid DESC LIMIT 1').fetchone()
    return session[0] if session and session[0] in ('paused', 'idle') else 'running'


def controls(memory):
    # New pause/resume/stop requests invalidate in-flight analysis, even if resumed.
    row=memory.db.execute('SELECT count(*),max(requested_ms) FROM control_commands').fetchone()
    return tuple(row)


def policy(config):
    return tuple(config.get(k) for k in ('auto_ai','ai_since_ms','ai_endpoint','ai_model'))


def evidence_hash(evidence):
    return signature({k:evidence[k] for k in ('id','start_ms','end_ms','state','event_id','title','text','evidence_ids')})


def recognition_progress(memory, since):
    """Return aggregate recognition counts without exposing activity content."""
    if not isinstance(since, int):
        return {'total': 0, 'ai': 0, 'ai_supported': 0, 'ai_classified': 0, 'local': 0, 'pending': 0, 'queued': 0}
    row = memory.db.execute("""SELECT COUNT(*) AS total,
        COALESCE(SUM(CASE WHEN r.source='ai' THEN 1 ELSE 0 END),0) AS ai,
        COALESCE(SUM(CASE WHEN r.source='ai' AND r.reliability='supported' THEN 1 ELSE 0 END),0) AS ai_supported,
        COALESCE(SUM(CASE WHEN r.source='ai' AND r.task_id IS NOT NULL AND r.reliability IN ('supported','tentative')
            AND r.disposition IN ('auto','auto_tentative') THEN 1 ELSE 0 END),0) AS ai_classified,
        COALESCE(SUM(CASE WHEN r.source IN ('rule','history') THEN 1 ELSE 0 END),0) AS local,
        COALESCE(SUM(CASE WHEN COALESCE(r.reliability,'unknown')!='supported'
            AND COALESCE(r.disposition,'review') NOT IN ('ignore','auto_tentative') THEN 1 ELSE 0 END),0) AS pending,
        COALESCE(SUM(CASE WHEN r.interval_id IS NULL OR r.source IN ('fallback','pending','conflict')
            OR (r.source='history' AND r.reliability='tentative')
            OR (r.source='ai' AND r.reliability='tentative' AND r.revision=0) THEN 1 ELSE 0 END),0) AS queued
        FROM activity_intervals i LEFT JOIN task_results r ON r.interval_id=i.id
        WHERE i.state='active' AND i.start_ms>=? AND i.end_ms<=? AND COALESCE(r.manual,0)=0""",
        (since, memory.now()-60_000)).fetchone()
    return {key: int(row[key] or 0) for key in ('total', 'ai', 'ai_supported', 'ai_classified', 'local', 'pending', 'queued')}


def set_recognition_progress(result, memory, since, stage, batch_count=0):
    progress = recognition_progress(memory, since)
    progress.update(stage=stage, batch_count=int(batch_count))
    result['recognition'] = progress
    return progress


def tick(database,cancel,analyze=True,provider_factory=TextProvider,credential_checker=None):
    memory=Memory(database,cleanup=False)
    try:
        config=options(database)
        state=capture_state(memory)
        result={'state':state,'options':config,'note':''}
        if not analyze or cancel.is_set():return result
        # Rule/history classification remains local and works with cloud disabled.
        pending=[r[0] for r in memory.db.execute("SELECT i.id FROM activity_intervals i LEFT JOIN task_results r ON r.interval_id=i.id WHERE i.state='active' AND (r.interval_id IS NULL OR r.source='pending') ORDER BY i.start_ms DESC LIMIT 100")]
        if pending:Classifier(memory).analyze(pending)
        since=config.get('ai_since_ms')
        if config.get('auto_ai') is not True:
            set_recognition_progress(result,memory,since,'disabled')
            return result
        if state in ('paused', 'idle'):
            set_recognition_progress(result,memory,since,'paused')
            return result
        if not isinstance(since,int):
            set_recognition_progress(result,memory,since,'disabled')
            return result
        # Do not resend old AI results or manual decisions. At most 20 closed events.
        ids=[r[0] for r in memory.db.execute("""SELECT i.id FROM activity_intervals i
            LEFT JOIN task_results r ON r.interval_id=i.id
            WHERE i.state='active' AND i.start_ms>=? AND i.end_ms<=?
            AND (r.interval_id IS NULL OR (r.manual=0 AND (r.source IN ('fallback','pending','conflict')
                OR (r.source='history' AND r.reliability='tentative')
                OR (r.source='ai' AND r.reliability='tentative' AND r.revision=0))))
            ORDER BY CASE WHEN r.source='ai' THEN 1 ELSE 0 END,i.start_ms LIMIT ?""",(since,memory.now()-60_000,DIARY_BATCH_SIZE))]
        evidence=Classifier(memory).prepare(ids)
        if not evidence:
            progress=set_recognition_progress(result,memory,since,'ready')
            progress['stage']='complete' if progress['queued']==0 else 'unavailable'
            return result
        endpoint=config.get('ai_endpoint') or DEEPSEEK_ENDPOINT
        credential_checker = credential_checker or (
            (lambda value: Vault(value).available()) if provider_factory is TextProvider else (lambda value: True)
        )
        if not credential_checker(endpoint):
            result['note']='缺少模型服务密钥，请在“模型与高级”中设置密钥后重试。'
            result['cooldown']=FAILURE_RETRY_SECONDS
            set_recognition_progress(result,memory,since,'blocked')
            return result
        profile=memory.profile()
        payload={'mode':'diary','profile':profile,'categories':profile['activities'] or DEFAULT_CATEGORIES,
            'projects':profile['projects'],'evidence':[{'interval_id':e['id'],'evidence_ids':e['evidence_ids'],
            'app':e['process_name'],'title':e['title'],'text':e['text'][:2000]} for e in evidence]}
        generation=memory.generation();control_version=controls(memory)
        profile_version=signature(memory.export())
        hashes={e['id']:evidence_hash(e) for e in evidence}
        if cancel.is_set() or policy(options(database))!=policy(config):return result
        provider=provider_factory(endpoint,config.get('ai_model') or DEEPSEEK_MODEL,budget=2)
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
        except IncompleteResponseError:
            result['note']='模型响应被截断，已缩小后续批次；保留原始记录，5 分钟后重试。'
            result['cooldown']=FAILURE_RETRY_SECONDS
            progress=set_recognition_progress(result,memory,since,'error')
            progress['message']=result['note']
            return result
        except ValueError:
            result['note']='AI 返回格式未通过安全校验，保留原始记录；5 分钟后重试。'
            result['cooldown']=FAILURE_RETRY_SECONDS
            progress=set_recognition_progress(result,memory,since,'error')
            progress['message']=result['note']
            return result
        except Exception:
            result['note']='模型服务请求失败，保留原始记录；5 分钟后重试。'
            result['cooldown']=FAILURE_RETRY_SECONDS
            progress=set_recognition_progress(result,memory,since,'error')
            progress['message']=result['note']
            return result
        with memory.repo.transaction():
            if cancel.is_set() or policy(options(database))!=policy(config) or controls(memory)!=control_version or memory.generation()!=generation or signature(memory.export())!=profile_version:return result
            returned=set()
            for item in response:
                identifier=item['interval_id']
                returned.add(identifier)
                fresh=memory.evidence(identifier)
                prior=memory.db.execute('SELECT manual FROM task_results WHERE interval_id=?',(identifier,)).fetchone()
                if not fresh or evidence_hash(fresh)!=hashes[identifier] or (prior and prior[0]):continue
                task=memory.task(item['label'],item['category'],item['project'])
                reason=item['description']
                if item['certainty']!='supported':reason += '；不确定：' + item['uncertainty_reason']
                disposition=('auto' if item['certainty']=='supported' else
                    'auto_tentative' if item['certainty']=='tentative' else 'review')
                memory.db.execute("""INSERT INTO task_results(interval_id,event_id,task_id,reliability,source,reason,disposition,revision)
                    VALUES (?,?,?,?,?,?,?,1) ON CONFLICT(interval_id) DO UPDATE SET
                    task_id=excluded.task_id,reliability=excluded.reliability,source='ai',reason=excluded.reason,
                    disposition=excluded.disposition,revision=task_results.revision+1""",
                    (identifier,fresh['event_id'],task,item['certainty'],'ai',reason,disposition))
            for identifier in set(hashes)-returned:
                fresh=memory.evidence(identifier)
                prior=memory.db.execute('SELECT manual FROM task_results WHERE interval_id=?',(identifier,)).fetchone()
                if not fresh or evidence_hash(fresh)!=hashes[identifier] or (prior and prior[0]):continue
                memory.db.execute("""INSERT INTO task_results(interval_id,event_id,task_id,reliability,source,reason,disposition,revision)
                    VALUES (?,?,NULL,'unknown','ai','AI 未能从当前证据确定活动分类','review',1)
                    ON CONFLICT(interval_id) DO UPDATE SET task_id=NULL,reliability='unknown',source='ai',
                    reason=excluded.reason,disposition='review',revision=task_results.revision+1""",
                    (identifier,fresh['event_id']))
        progress=set_recognition_progress(result,memory,since,'waiting',len(response))
        rejected=int(getattr(provider,'last_rejected_count',0))
        progress['rejected_count']=rejected
        if progress['queued']==0:progress['stage']='complete'
        result['note']=('后台 AI 已整理新活动；部分返回未匹配现有分类，已保留待确认。' if rejected
            else '后台 AI 已整理新活动；不确定的判断等待你确认。')
        if not response:result['cooldown']=FAILURE_RETRY_SECONDS
        return result
    finally:memory.close()
