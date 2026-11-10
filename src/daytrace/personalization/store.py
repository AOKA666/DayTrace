import json
import time
from pathlib import Path

from ..content.policy import normalize
from ..storage.repository import Repository, InstanceLock, uid
from .profile import clean_profile
from .taxonomy import TaxonomyMixin, migrate as migrate_taxonomy

DAY = 86_400_000
MIGRATION_003 = Path(__file__).parents[1] / 'storage/migrations/003_personalization.sql'


class PersonalizationUpgradeBlocked(RuntimeError):
    """v2 database needs 003 migration but collector holds the instance lock."""


def personalization_schema_ready(db) -> bool:
    row = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='personal_profile'").fetchone()
    return row is not None


class Memory(TaxonomyMixin):
    def __init__(self, path, now=None, cleanup=True):
        self.repo = Repository(Path(path))
        self.db = self.repo.db
        self.now = now or (lambda: time.time_ns() // 1_000_000)
        try:
            self._upgrade_personalization_if_needed(Path(path))
            migrate_taxonomy(self)
            if cleanup:
                self.repo.cleanup(self.now())
        except BaseException:
            self.db.rollback()
            self.repo.close()
            raise

    def _upgrade_personalization_if_needed(self, path: Path) -> None:
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version >= 3:
            return
        if version != 2:
            return
        if personalization_schema_ready(self.db):
            with self.db:
                self.db.execute('PRAGMA user_version=3')
            return
        try:
            with InstanceLock(path):
                self.db.executescript(MIGRATION_003.read_text('utf-8'))
        except RuntimeError as error:
            if 'Collector is running' in str(error):
                raise PersonalizationUpgradeBlocked(
                    '数据库需要升级到个性化版本才能打开日记。请先在采集终端停止记录（Ctrl+C 或 daytrace stop），再打开界面。'
                ) from None
            raise

    def close(self):
        self.repo.close()

    def profile(self):
        row = self.db.execute('SELECT data FROM personal_profile WHERE id=1').fetchone()
        return json.loads(row[0]) if row else clean_profile({})

    def save_profile(self, value):
        value = clean_profile(value)
        with self.repo.transaction():
            self.db.execute('INSERT INTO personal_profile VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (json.dumps(value, ensure_ascii=False),))
            existing = {r['path']: r for r in self.catalog()['categories']}
            for name, row in existing.items():
                if name not in value['activities'] and not any(x.startswith(name + ' / ') for x in value['activities']):
                    self.db.execute('UPDATE personal_categories SET active=0 WHERE id=?', (row['id'],))
            for name in value['activities']:
                if name not in existing:
                    self.db.execute('INSERT INTO personal_categories VALUES (?,?,NULL,?,1) ON CONFLICT DO UPDATE SET active=1', (uid(), name, '#7566D9'))
            self.invalidate_automatic()
        return value

    def task(self, label, category='', project=''):
        values = tuple(normalize(x)[:160] for x in (label, category, project))
        if not values[0]:
            raise ValueError('Task name is required')
        row = self.db.execute('SELECT id FROM personal_tasks WHERE label=? AND category=? AND project=?', values).fetchone()
        if row:
            return row[0]
        identifier = uid()
        self.db.execute('INSERT INTO personal_tasks(id,label,category,project,created_ms) VALUES (?,?,?,?,?)', (identifier, *values, self.now()))
        return identifier

    def tasks(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM personal_tasks ORDER BY label')]

    def add_category(self,name,color):
        import re
        from ..preferences import options,save_options
        from .category_palette import PALETTE
        name=normalize(name).strip()[:40]
        if not name or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
            raise ValueError('Invalid category')
        profile=self.profile()
        created = name not in profile['activities']
        if created:
            profile['activities'].append(name)
            self.save_profile(profile)
            with self.repo.transaction():
                self.task(name, name, '')
        colors=options(self.repo.path).get('category_colors',{})
        save_options(self.repo.path,category_colors={**colors,name:color})
        return name

    def set_category_color(self, name, color):
        import re
        from ..preferences import options, save_options
        name = normalize(name).strip()[:40]
        if name not in self.profile()['activities']:
            raise ValueError('Unknown category')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('Invalid color')
        colors = options(self.repo.path).get('category_colors', {})
        save_options(self.repo.path, category_colors={**colors, name: color})

    def rename_category(self, old_name, new_name, color=None):
        import re
        from ..preferences import options, save_options
        from .category_palette import PALETTE
        old_name = normalize(old_name).strip()[:40]
        new_name = normalize(new_name).strip()[:40]
        profile = self.profile()
        if old_name not in profile['activities']:
            raise ValueError('Unknown category')
        if not new_name:
            raise ValueError('Invalid category')
        if new_name != old_name and new_name in profile['activities']:
            raise ValueError('Duplicate category')
        if color is not None and not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('Invalid color')
        index = profile['activities'].index(old_name)
        if new_name != old_name:
            profile['activities'][index] = new_name
            self.save_profile(profile)
        colors = dict(options(self.repo.path).get('category_colors', {}))
        current = color or colors.get(old_name) or PALETTE[index % len(PALETTE)]
        colors.pop(old_name, None)
        colors[new_name] = current
        save_options(self.repo.path, category_colors=colors)
        return new_name

    def remove_category(self, name):
        from ..preferences import options, save_options
        name = normalize(name).strip()[:40]
        profile = self.profile()
        if name in profile['activities']:
            profile['activities'] = [item for item in profile['activities'] if item != name]
            self.save_profile(profile)
        colors = dict(options(self.repo.path).get('category_colors', {}))
        colors.pop(name, None)
        save_options(self.repo.path, category_colors=colors)

    def evidence(self, interval_id):
        row = self.db.execute('''SELECT i.*,s.device_id,s.platform,s.timezone,s.ended_ms,s.status AS capture_status,s.heartbeat_ms,
            e.id AS event_id,e.at_ms AS event_ms
            FROM activity_intervals i JOIN capture_sessions s ON s.id=i.session_id
            JOIN activity_events e ON e.session_id=i.session_id AND e.at_ms=i.start_ms
             AND e.state='active' AND e.kind IN ('foreground_switch','title_change')
            WHERE i.id=? AND i.state='active' AND i.end_ms>i.start_ms
             AND i.end_ms<=s.heartbeat_ms
             AND (s.ended_ms IS NOT NULL OR i.end_ms<s.heartbeat_ms)
            ORDER BY e.rowid DESC LIMIT 1''', (interval_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        if data['start_ms'] < self.now() - 7 * DAY:
            data['title'] = None
        # Only the latest valid sample; an excluded latest sample must not reveal older text.
        sample = self.db.execute('''SELECT * FROM content_samples WHERE event_id=?
            AND captured_ms>=? AND captured_ms<? AND expires_ms>? ORDER BY captured_ms DESC,rowid DESC LIMIT 1''',
            (data['event_id'], data['start_ms'], data['end_ms'], self.now())).fetchone()
        data['text'] = ''
        data['content_status'] = sample['status'] if sample else 'unavailable'
        data['evidence_ids'] = [data['event_id']]
        if sample and sample['status'] in ('success', 'partial', 'duplicate'):
            source = sample
            if sample['duplicate_of']:
                source = self.db.execute('SELECT * FROM content_samples WHERE id=? AND expires_ms>?', (sample['duplicate_of'], self.now())).fetchone()
            if source and source['text']:
                data['text'] = normalize(source['text'])
                data['evidence_ids'].append(sample['id'])
        data['title'] = normalize(data['title'] or '')
        # No URL adapter exists. Do not infer one from an arbitrary document string.
        data['url'] = ''
        data['has_screenshot'] = False
        if self.db.execute('PRAGMA user_version').fetchone()[0]>=4:
            data['has_screenshot'] = bool(self.db.execute('SELECT 1 FROM screenshots WHERE event_id=? AND expires_ms>? LIMIT 1',(data['event_id'],self.now())).fetchone())
        return data

    def intervals(self):
        return [r[0] for r in self.db.execute("SELECT id FROM activity_intervals WHERE state='active' AND end_ms>start_ms ORDER BY start_ms")]

    def timeline(self, start_ms=None, end_ms=None):
        rows = [dict(r) for r in self.db.execute('''SELECT i.id AS interval_id,i.start_ms,i.end_ms,i.state,
          CASE WHEN i.state='active' AND i.start_ms>=? THEN i.title END AS title,i.app_id,
          EXISTS(SELECT 1 FROM activity_events ge WHERE ge.session_id=i.session_id AND ge.at_ms=i.start_ms AND ge.kind='dwell_gap') AS short_gap,
          i.process_name,s.timezone,s.device_id,s.platform,i.session_id,
          r.event_id,r.reliability,r.source,r.reason,r.manual,r.disposition,r.revision,r.task_id,
          t.label,t.category,t.project
          FROM activity_intervals i JOIN capture_sessions s ON s.id=i.session_id
          LEFT JOIN task_results r ON r.interval_id=i.id LEFT JOIN personal_tasks t ON t.id=r.task_id
          WHERE i.end_ms>i.start_ms AND i.end_ms>? AND i.start_ms<? ORDER BY i.start_ms''',
          (self.now()-7*DAY,max(self.now()-90*DAY,start_ms or 0),end_ms if end_ms is not None else 2**63-1))]
        tags = {}
        for tag in self.db.execute('SELECT a.interval_id,t.id,t.name,t.color FROM activity_tags a JOIN personal_tags t ON t.id=a.tag_id ORDER BY t.name'):
            tags.setdefault(tag['interval_id'], []).append({'id': tag['id'], 'name': tag['name'], 'color': tag['color']})
        for row in rows:
            row['tags'] = tags.get(row['interval_id'], [])
        return rows

    def feedback(self, interval_id, label='', category='', project='', action='confirm', remember=False):
        if action == 'private':
            with InstanceLock(self.repo.path):
                self._feedback(interval_id, label, category, project, action, remember)
                from ..storage.screenshots import cleanup
                cleanup(self.repo)
                self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            return
        return self._feedback(interval_id, label, category, project, action, remember)

    def feedback_many(self, identifiers, label, category='', project='', remember=True):
        """One user decision for contiguous source fragments, with atomic revisions."""
        rows=[dict(r) for r in self.db.execute('SELECT id,session_id,start_ms,end_ms,state FROM activity_intervals WHERE id IN ('+','.join('?' for _ in identifiers)+') ORDER BY start_ms',identifiers)]
        if not rows or len(rows)!=len(set(identifiers)) or any(r['state']!='active' for r in rows):
            raise ValueError('Only active fragments can be confirmed together')
        if any(a['end_ms']!=b['start_ms'] or a['session_id']!=b['session_id'] for a,b in zip(rows,rows[1:])):
            raise ValueError('Cannot merge across a gap or another session')
        with self.repo.transaction():
            for row in rows:self._feedback(row['id'],label,category,project,'confirm',remember,transaction=False)

    def _feedback(self, interval_id, label='', category='', project='', action='confirm', remember=False, transaction=True, correction_from=None):
        if action not in ('confirm', 'unknown', 'ignore', 'private', 'undo'):
            raise ValueError('Invalid feedback action')
        from contextlib import nullcontext
        with self.repo.transaction() if transaction else nullcontext():
            result = self.db.execute('SELECT * FROM task_results WHERE interval_id=?', (interval_id,)).fetchone()
            if not result:
                raise ValueError('Analyze this interval first')
            self.db.execute('DELETE FROM activity_tags WHERE interval_id=?', (interval_id,))
            self.db.execute('DELETE FROM learned_rules WHERE id IN (SELECT rule_id FROM rule_origins WHERE interval_id=?)', (interval_id,))
            self.db.execute('DELETE FROM activity_cases WHERE interval_id=?', (interval_id,))
            if action == 'private':
                self._private(interval_id, result['event_id'])
                return
            task = self.task(label, category, project) if action == 'confirm' else None
            previous = self.db.execute('SELECT id FROM activity_feedback WHERE interval_id=? ORDER BY rowid DESC LIMIT 1', (interval_id,)).fetchone()
            feedback_id = uid()
            self.db.execute('INSERT INTO activity_feedback VALUES (?,?,?,?,?,?)', (feedback_id, interval_id, task, action, self.now(), previous[0] if previous else None))
            if correction_from is not None:
                self.db.execute('INSERT INTO ai_corrections VALUES (?,?)', (feedback_id, correction_from))
            self.db.execute('''UPDATE task_results SET task_id=?,reliability=?,source=?,reason=?,manual=?,disposition=?,revision=revision+1 WHERE interval_id=?''',
                (task, 'supported' if task else 'unknown', 'human' if action != 'undo' else 'pending',
                 '人工确认' if task else '用户选择：' + action, int(action != 'undo'),
                 'confirmed' if task else ('review' if action in ('undo', 'unknown') else action), interval_id))
            if task and remember:
                self.db.execute('INSERT INTO activity_cases VALUES (?,?)', (interval_id, task))
            self.invalidate_automatic()

    def _private(self, interval, event):
        # Erase rather than retaining a revision containing the former label/evidence.
        if self.db.execute('PRAGMA user_version').fetchone()[0]>=4:
            self.db.execute('DELETE FROM screenshots WHERE event_id=?',(event,))
        self.db.execute('DELETE FROM content_samples WHERE event_id=?', (event,))
        self.db.execute('DELETE FROM task_results WHERE interval_id=?', (interval,))
        self.db.execute("UPDATE activity_intervals SET state='excluded',title=NULL,app_id=NULL,process_name=NULL WHERE id=?", (interval,))
        self.db.execute("UPDATE activity_events SET state='excluded',title=NULL,app_id=NULL,process_name=NULL WHERE id=?", (event,))
        self.invalidate_automatic()
        self._remove_orphan_tasks()

    def _remove_orphan_tasks(self):
        self.db.execute('DELETE FROM personal_tasks WHERE id NOT IN (SELECT task_id FROM task_results WHERE task_id IS NOT NULL) AND id NOT IN (SELECT task_id FROM learned_rules) AND id NOT IN (SELECT task_id FROM activity_feedback WHERE task_id IS NOT NULL)')

    def delete_interval(self, interval):
        # Never erase an in-flight collector event.
        with InstanceLock(self.repo.path):
            with self.repo.transaction():
                row = self.db.execute('''SELECT e.id FROM activity_intervals i JOIN activity_events e
                    ON e.session_id=i.session_id AND e.at_ms=i.start_ms
                    AND e.kind IN ('foreground_switch','title_change') WHERE i.id=?''', (interval,)).fetchone()
                if row:
                    self.db.execute('DELETE FROM activity_events WHERE id=?', (row[0],))
                self.db.execute('DELETE FROM activity_intervals WHERE id=?', (interval,))
                self.invalidate_automatic()
                self._remove_orphan_tasks()
            self.repo.cleanup(self.now())

    def save_rule(self, task, conditions, approved=False, rule_id=None, origins=()):
        allowed = {'app', 'title', 'title_exact', 'keywords', 'exclude', 'project', 'context', 'url_prefix'}
        if not isinstance(conditions, dict) or set(conditions) - allowed:
            raise ValueError('Invalid rule fields')
        cleaned = {}
        for key, value in conditions.items():
            if key in ('keywords', 'exclude'):
                if not isinstance(value, list) or any(not isinstance(x, str) for x in value) or len(value) > 20:
                    raise ValueError('Invalid keywords')
                cleaned[key] = [normalize(x)[:100] for x in value if x.strip()]
            elif isinstance(value, str):
                cleaned[key] = normalize(value)[:200]
            else:
                raise ValueError('Invalid rule condition')
        if not any(cleaned.get(k) for k in ('title', 'title_exact', 'keywords', 'project', 'context', 'url_prefix')):
            raise ValueError('An application alone cannot define a task')
        identifier = rule_id or uid()
        with self.repo.transaction():
            self.db.execute('''INSERT INTO learned_rules VALUES (?,?,?,1,?) ON CONFLICT(id) DO UPDATE
                SET task_id=excluded.task_id,conditions=excluded.conditions,approved=excluded.approved''',
                (identifier, task, json.dumps(cleaned, ensure_ascii=False), int(approved)))
            for origin in origins:
                self.db.execute('INSERT OR IGNORE INTO rule_origins VALUES (?,?)', (identifier, origin))
            self.invalidate_automatic()
        return identifier

    def invalidate_automatic(self):
        self.db.execute("UPDATE task_results SET task_id=NULL,reliability='unknown',source='pending',reason='依据已改变，请重新分析',disposition='review',revision=revision+1 WHERE manual=0")
        self.db.execute('UPDATE personal_state SET generation=generation+1 WHERE id=1')

    def generation(self):
        return self.db.execute('SELECT generation FROM personal_state WHERE id=1').fetchone()[0]

    def rules(self):
        rows = [dict(r) for r in self.db.execute('SELECT * FROM learned_rules')]
        for row in rows:
            row['conditions'] = json.loads(row['conditions'])
        return rows

    def change_rule(self, identifier, enabled=None):
        with self.repo.transaction():
            if enabled is None:
                self.db.execute('DELETE FROM learned_rules WHERE id=?', (identifier,))
            else:
                self.db.execute('UPDATE learned_rules SET enabled=? WHERE id=?', (int(enabled), identifier))
            self.invalidate_automatic()

    def history(self):
        return [dict(r) for r in self.db.execute('SELECT f.*,t.label FROM activity_feedback f LEFT JOIN personal_tasks t ON t.id=f.task_id ORDER BY f.created_ms DESC LIMIT 100')]

    def correction_history(self):
        return [dict(r) for r in self.db.execute('''SELECT f.created_ms,t.label,t.category,c.previous_category
            FROM ai_corrections c JOIN activity_feedback f ON f.id=c.feedback_id
            JOIN personal_tasks t ON t.id=f.task_id ORDER BY f.created_ms DESC,f.rowid DESC LIMIT 100''')]

    def export(self):
        from ..preferences import options
        return {'schema_version': 1, 'profile': self.profile(), 'tasks': self.tasks(), 'rules': self.rules(),
                'taxonomy': self.catalog(),
                'ai_corrections': [dict(r) for r in self.db.execute('SELECT * FROM ai_corrections')],
                'activity_tags': [dict(r) for r in self.db.execute('SELECT * FROM activity_tags')],
                'feedback_tags': [dict(r) for r in self.db.execute('SELECT * FROM feedback_tags')],
                'category_colors': options(self.repo.path).get('category_colors', {}),
                'feedback': [dict(r) for r in self.db.execute('SELECT * FROM activity_feedback ORDER BY created_ms')],
                'rule_origins': [dict(r) for r in self.db.execute('SELECT * FROM rule_origins')],
                'cases': [dict(r) for r in self.db.execute('SELECT * FROM activity_cases')]}

    def suggestions(self):
        from .classifier import words, text_of
        grouped = {}
        for row in self.db.execute('SELECT * FROM activity_cases'):
            evidence = self.evidence(row['interval_id'])
            if evidence:
                grouped.setdefault(row['task_id'], []).append((row['interval_id'], words(text_of(evidence))))
        result = []
        for task, sets in grouped.items():
            if len(sets) >= 2:
                shared = set.intersection(*(s[1] for s in sets))
                if len(shared) >= 3:
                    result.append({'task_id': task, 'conditions': {'keywords': sorted(shared)[:8]}, 'examples': len(sets), 'origins': [s[0] for s in sets]})
        return result

    def forget(self):
        from ..preferences import save_options
        save_options(self.repo.path, category_colors={})
        with self.repo.transaction():
            for table in ('activity_tags', 'feedback_tags', 'personal_tags', 'personal_categories', 'activity_cases', 'activity_feedback', 'task_results', 'learned_rules', 'personal_tasks', 'personal_profile', 'analysis_runs'):
                self.db.execute('DELETE FROM ' + table)
            self.db.execute('UPDATE personal_state SET generation=generation+1 WHERE id=1')
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
