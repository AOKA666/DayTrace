import hashlib
import json
import re

from ..storage.repository import uid, InstanceLock


def words(text):
    return set(re.findall(r'[a-z0-9_]{3,}|[\u4e00-\u9fff]{2,}', text.casefold()))


def text_of(evidence):
    return (evidence['title'] + ' ' + evidence['text']).casefold()


def matches(conditions, evidence):
    text = text_of(evidence)
    if conditions.get('app') and conditions['app'].casefold() != (evidence['process_name'] or '').casefold():
        return False
    if conditions.get('title') and conditions['title'].casefold() not in evidence['title'].casefold():
        return False
    if conditions.get('url_prefix') and not evidence['url'].startswith(conditions['url_prefix']):
        return False
    if any(w.casefold() not in text for w in conditions.get('keywords', [])):
        return False
    if any(w.casefold() in text for w in conditions.get('exclude', [])):
        return False
    # Project/context constraints require direct evidence, never just profile membership.
    return all(not conditions.get(k) or conditions[k].casefold() in text for k in ('project', 'context'))


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class Classifier:
    def __init__(self, memory, provider=None, category_only=False):
        self.memory = memory
        self.provider = provider
        self.category_only = category_only

    def predict(self, evidence):
        if not text_of(evidence).strip():
            return None, 'unknown', 'fallback', '没有可用文本证据'
        rules = [r for r in self.memory.rules() if r['enabled'] and r['approved'] and matches(r['conditions'], evidence)]
        tasks = {r['task_id'] for r in rules}
        cases = set()
        current = words(text_of(evidence))
        for row in self.memory.db.execute('SELECT c.*,t.project FROM activity_cases c JOIN personal_tasks t ON t.id=c.task_id'):
            if row['interval_id'] == evidence['id']:
                continue
            old = self.memory.evidence(row['interval_id'])
            if not old:
                continue
            if row['project'] and row['project'].casefold() in text_of(old) and row['project'].casefold() not in text_of(evidence):
                continue
            previous = words(text_of(old))
            # Exact meaningful content or conservative overlap; never app-only matching.
            exact = text_of(old).strip() == text_of(evidence).strip() and len(text_of(evidence).strip()) >= 12
            similar = len(current & previous) >= 3 and len(current & previous) / max(1, len(current | previous)) >= .8
            if exact or similar:
                cases.add(row['task_id'])
        if len(tasks) > 1 or (tasks and cases and tasks != cases) or len(cases) > 1:
            return None, 'tentative', 'conflict', '规则或人工案例冲突，需要确认'
        if tasks:
            return next(iter(tasks)), 'supported', 'rule', '命中已批准的组合规则'
        if cases:
            return next(iter(cases)), 'tentative', 'history', '匹配人工确认案例；相似不等于确定'
        return None, 'unknown', 'fallback', '尚无足够依据，请确认实际活动'

    def prepare(self, identifiers):
        items = []
        for identifier in identifiers:
            prior = self.memory.db.execute('SELECT manual FROM task_results WHERE interval_id=?', (identifier,)).fetchone()
            if prior and prior[0]:
                continue
            evidence = self.memory.evidence(identifier)
            if evidence:
                items.append(evidence)
        return items

    def analyze(self, identifiers=None, approved_payload=None):
        # Explicit cloud batches only run with the collector stopped. This also
        # serializes against CLI delete/start and invalidates consent on restart.
        if self.provider and approved_payload is not None:
            with InstanceLock(self.memory.repo.path):
                return self._analyze(identifiers, approved_payload)
        return self._analyze(identifiers, approved_payload)

    def _analyze(self, identifiers=None, approved_payload=None):
        if approved_payload is not None:
            identifiers = [e['interval_id'] for e in approved_payload['evidence']]
        items = self.prepare(identifiers if identifiers is not None else self.memory.intervals())
        memory_version = signature(self.memory.export())
        generation = self.memory.generation()
        initial = {e['id']: self.predict(e) for e in items}
        unresolved = [e for e in items if initial[e['id']][2] == 'fallback']
        ai = {}
        if self.provider and unresolved and approved_payload is not None:
            payload = self.payload(unresolved)
            if payload == approved_payload:
                try:
                    ai = self.validate(self.provider.classify(payload), payload)
                except Exception:
                    # No provider exception text, request body or model response is logged.
                    ai = {}
        count = 0
        with self.memory.repo.transaction():
            if generation != self.memory.generation() or memory_version != signature(self.memory.export()) or (self.provider and self.provider.cancelled.is_set()):
                return 0
            for evidence in items:
                fresh = self.memory.evidence(evidence['id'])
                if not fresh or signature(fresh) != signature(evidence):
                    continue
                prior = self.memory.db.execute('SELECT manual FROM task_results WHERE interval_id=?', (evidence['id'],)).fetchone()
                if prior and prior[0]:
                    continue
                task, reliability, source, reason = initial[evidence['id']]
                if evidence['id'] in ai:
                    task = ai[evidence['id']]
                    reliability, source, reason = 'tentative', 'ai', '模型建议，需人工确认；引用已校验'
                self.memory.db.execute('''INSERT INTO task_results(interval_id,event_id,task_id,reliability,source,reason)
                  VALUES (?,?,?,?,?,?) ON CONFLICT(interval_id) DO UPDATE SET
                  task_id=excluded.task_id,reliability=excluded.reliability,source=excluded.source,
                  reason=excluded.reason,revision=task_results.revision+1''',
                  (evidence['id'], evidence['event_id'], task, reliability, source, reason))
                count += 1
            self.memory.db.execute('INSERT INTO analysis_runs VALUES (?,?,?,?)', (uid(), self.memory.now(), count, 'layered'))
        return count

    def payload(self, evidence):
        tasks=self.memory.tasks()
        if self.category_only:
            categories=self.memory.profile()['activities']
            tasks=[t for t in tasks if t['label']==t['category'] and not t['project'] and t['category'] in categories]
        return {'profile': self.memory.profile(), 'candidates': [
            {key: task[key] for key in ('id', 'label', 'category', 'project')} for task in tasks], 'evidence': [
            {'interval_id': e['id'], 'evidence_ids': e['evidence_ids'], 'app': e['process_name'],
             'title': e['title'], 'text': e['text'][:2000]} for e in evidence]}

    def preview(self, identifiers=None):
        items = self.prepare(identifiers if identifiers is not None else self.memory.intervals())
        return self.payload([e for e in items if self.predict(e)[2] == 'fallback'][:100])

    @staticmethod
    def validate(response, payload):
        if not isinstance(response, list) or len(response) > len(payload['evidence']):
            raise ValueError('Invalid AI response')
        candidates = {t['id'] for t in payload['candidates']}
        allowed = {e['interval_id']: set(e['evidence_ids']) for e in payload['evidence']}
        result = {}
        for item in response:
            if not isinstance(item, dict) or set(item) != {'interval_id', 'task_id', 'evidence_ids'}:
                raise ValueError('Invalid AI fields')
            interval, task, refs = item['interval_id'], item['task_id'], item['evidence_ids']
            if interval not in allowed or interval in result or task not in candidates:
                raise ValueError('Invalid AI identifiers')
            if not isinstance(refs, list) or not refs or not all(isinstance(x, str) for x in refs) or not set(refs) <= allowed[interval]:
                raise ValueError('Invalid AI evidence')
            result[interval] = task
        return result
