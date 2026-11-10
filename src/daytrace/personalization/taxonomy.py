"""Local category hierarchy and tags; never added to cloud request payloads."""
import re
import sqlite3

from ..content.policy import normalize
from ..storage.repository import uid
from .category_palette import PALETTE, default_tag_color


def migrate(memory):
    """Additive migrations serialized with all writers, safe with a live collector."""
    if memory.db.execute('PRAGMA user_version').fetchone()[0] >= 7:
        return
    from pathlib import Path
    root = Path(__file__).parents[1] / 'storage/migrations'
    with memory.repo.transaction():
        version = memory.db.execute('PRAGMA user_version').fetchone()[0]
        if version >= 7:
            return
        import_categories = version < 5
        import_tag_colors = version < 6
        for number, filename in ((4, '004_screenshots.sql'), (5, '005_taxonomy.sql'), (6, '006_taxonomy_colors.sql'), (7, '007_ai_corrections.sql')):
            if version >= number:
                continue
            # execute(), unlike executescript(), preserves the outer transaction.
            statement = ''
            for line in (root / filename).read_text('utf-8').splitlines():
                statement += line + '\n'
                if sqlite3.complete_statement(statement):
                    sql = statement.strip()
                    if sql not in ('BEGIN IMMEDIATE;', 'COMMIT;'):
                        memory.db.execute(sql)
                    statement = ''
            version = number
        from ..preferences import options
        colors = options(memory.repo.path).get('category_colors', {})
        for index, name in enumerate(memory.profile()['activities'] if import_categories else []):
            memory.db.execute('INSERT INTO personal_categories VALUES (?,?,NULL,?,1)',
                              (uid(), name, colors.get(name) or PALETTE[index % len(PALETTE)]))
        for tag in memory.db.execute('SELECT id,name FROM personal_tags').fetchall() if import_tag_colors else []:
            memory.db.execute('UPDATE personal_tags SET color=? WHERE id=?', (default_tag_color(tag['name']), tag['id']))


class TaxonomyMixin:
    def catalog(self):
        rows = [dict(r) for r in self.db.execute('SELECT * FROM personal_categories WHERE active=1 ORDER BY rowid')]
        by_id = {r['id']: r for r in rows}
        ordered = []
        for root in (r for r in rows if not r['parent_id']):
            ordered.append(dict(root, path=root['name']))
            ordered.extend(dict(r, path=root['name'] + ' / ' + r['name'])
                           for r in rows if r['parent_id'] == root['id'] and r['parent_id'] in by_id)
        return {'categories': ordered, 'tags': [dict(r) for r in self.db.execute('SELECT * FROM personal_tags ORDER BY name')]}

    @staticmethod
    def _taxonomy_name(value, tag=False):
        if not isinstance(value, str):
            raise ValueError('请输入名称。')
        value = normalize(value).strip()
        if tag:
            value = value.lstrip('#').strip()
        if not value or len(value) > 40 or '/' in value or '\n' in value or (tag and '#' in value):
            raise ValueError('名称需为 1–40 个字符，不能包含 / 或换行；标签无需重复输入 #。')
        return value

    def _sync_category_colors(self, catalog=None, drop_paths=()):
        from ..preferences import options, save_options
        rows = catalog if catalog is not None else self.catalog()['categories']
        colors = dict(options(self.repo.path).get('category_colors', {}))
        for path in drop_paths:
            colors.pop(path, None)
        for row in rows:
            colors[row['path']] = row['color']
        save_options(self.repo.path, category_colors=colors)

    def _sync_category_profile(self, drop_paths=()):
        catalog = self.catalog()['categories']
        profile = self.profile()
        profile['activities'] = [r['path'] for r in catalog]
        # Bypass save_profile's legacy import path.
        import json
        self.db.execute('INSERT INTO personal_profile VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        (json.dumps(profile, ensure_ascii=False),))
        self._sync_category_colors(catalog, drop_paths)
        self.invalidate_automatic()

    def create_category(self, name, parent_id=None, color=PALETTE[0]):
        name = self._taxonomy_name(name)
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('请选择有效颜色。')
        with self.repo.transaction():
            categories = self.catalog()['categories']
            if len(categories) >= 100:
                raise ValueError('分类最多 100 个。')
            if parent_id:
                parent = next((r for r in categories if r['id'] == parent_id), None)
                if not parent or parent['parent_id']:
                    raise ValueError('子分类只能建在已有的一级分类下。')
                color = parent['color']
            if any(r['parent_id'] == parent_id and r['name'].casefold() == name.casefold() for r in categories):
                raise ValueError('该分类已存在。')
            old = self.db.execute('SELECT id FROM personal_categories WHERE parent_id IS ? AND name=?', (parent_id, name)).fetchone()
            identifier = old[0] if old else uid()
            if old:
                self.db.execute('UPDATE personal_categories SET active=1,color=? WHERE id=?', (color, identifier))
            else:
                self.db.execute('INSERT INTO personal_categories VALUES (?,?,?,?,1)', (identifier, name, parent_id, color))
            self._sync_category_profile()
        return identifier

    def update_category(self, identifier, name, color):
        name = self._taxonomy_name(name)
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('请选择有效颜色。')
        with self.repo.transaction():
            rows = self.catalog()['categories']
            current = next((r for r in rows if r['id'] == identifier), None)
            if not current:
                raise ValueError('分类已删除，请重新选择。')
            if current['parent_id']:
                color = next(r['color'] for r in rows if r['id'] == current['parent_id'])
            if any(r['id'] != identifier and r['parent_id'] == current['parent_id'] and r['name'].casefold() == name.casefold() for r in rows):
                raise ValueError('该分类已存在。')
            old_paths = {row['id']: row['path'] for row in rows}
            self.db.execute('UPDATE personal_categories SET name=?,color=? WHERE id=?', (name, color, identifier))
            new_rows = self.catalog()['categories']
            drop_paths = []
            for row in new_rows:
                old = old_paths.get(row['id'])
                if old and old != row['path']:
                    self.db.execute(
                        'UPDATE personal_tasks SET label=CASE WHEN label=? THEN ? ELSE label END, category=? WHERE category=?',
                        (old, row['path'], row['path'], old),
                    )
                    drop_paths.append(old)
            self._sync_category_profile(drop_paths)

    def delete_category(self, identifier):
        with self.repo.transaction():
            self.db.execute('UPDATE personal_categories SET active=0 WHERE id=? OR parent_id=?', (identifier, identifier))
            self._sync_category_profile()

    def create_tag(self, name, color=None):
        name = self._taxonomy_name(name, tag=True)
        color = default_tag_color(name) if color is None else color
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('请选择有效颜色。')
        with self.repo.transaction():
            rows = self.catalog()['tags']
            if any(r['name'].casefold() == name.casefold() for r in rows):
                raise ValueError('该标签已存在。')
            if len(rows) >= 200:
                raise ValueError('标签最多 200 个。')
            identifier = uid()
            self.db.execute('INSERT INTO personal_tags(id,name,color) VALUES (?,?,?)', (identifier, name, color))
        return identifier

    def update_tag(self, identifier, name, color):
        name = self._taxonomy_name(name, tag=True)
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('请选择有效颜色。')
        with self.repo.transaction():
            rows = self.catalog()['tags']
            current = next((r for r in rows if r['id'] == identifier), None)
            if not current:
                raise ValueError('标签已删除，请重新选择。')
            if any(r['id'] != identifier and r['name'].casefold() == name.casefold() for r in rows):
                raise ValueError('该标签已存在。')
            self.db.execute('UPDATE personal_tags SET name=?,color=? WHERE id=?', (name, color, identifier))

    def delete_tag(self, identifier):
        with self.repo.transaction():
            self.db.execute('DELETE FROM personal_tags WHERE id=?', (identifier,))

    def confirm_selection(self, identifiers, category_id, tag_ids=(), remember=True):
        """Confirm labels atomically, retaining each interval's name, project and time."""
        identifiers = list(dict.fromkeys(identifiers))
        tag_ids = list(dict.fromkeys(tag_ids))
        if not identifiers or len(identifiers) > 1000:
            raise ValueError('请选择有效活动。')
        with self.repo.transaction():
            catalog = self.catalog()
            category = next((r['path'] for r in catalog['categories'] if r['id'] == category_id), None)
            if not category:
                raise ValueError('必须选择有效分类。')
            if not set(tag_ids) <= {t['id'] for t in catalog['tags']}:
                raise ValueError('标签已删除，请重新选择。')
            snapshots = []
            for identifier in identifiers:
                row = self.db.execute('''SELECT i.state,i.title,i.process_name,t.label,t.project,t.category,r.source
                    FROM activity_intervals i JOIN task_results r ON r.interval_id=i.id
                    LEFT JOIN personal_tasks t ON t.id=r.task_id WHERE i.id=?''', (identifier,)).fetchone()
                if not row or row['state'] != 'active':
                    raise ValueError('活动已删除或不可确认。')
                snapshots.append((identifier, row))
            for identifier, row in snapshots:
                # Category-only confirmation must not copy a seven-day raw title
                # into a ninety-day task label. Existing semantic names remain.
                label = row['label'] or category
                correction = row['source'] == 'ai' and bool(row['category']) and row['category'] != category
                self._feedback(identifier, label, category, row['project'] or '', 'confirm', remember and correction,
                               transaction=False, correction_from=row['category'] if correction else None)
                feedback = self.db.execute('SELECT id FROM activity_feedback WHERE interval_id=? ORDER BY rowid DESC LIMIT 1', (identifier,)).fetchone()[0]
                self.db.executemany('INSERT INTO activity_tags VALUES (?,?)', ((identifier, tag) for tag in tag_ids))
                self.db.executemany('INSERT INTO feedback_tags VALUES (?,?)', ((feedback, tag) for tag in tag_ids))
            if remember:
                self._learn_titles(snapshots, category, tag_ids)

    def _learn_titles(self, snapshots, category, tag_ids):
        """Remember exact window titles so later same-title activities get this classification."""
        import json
        groups = {}
        for identifier, row in snapshots:
            title = normalize(row['title'] or '').strip()
            if title:
                groups.setdefault(title.casefold(), {'title': title, 'origins': []})['origins'].append(identifier)
        if not groups:
            return
        task = self.task(category, category, '')
        confirmed = {identifier for identifier, _ in snapshots}
        for group in groups.values():
            conditions = json.dumps({'title_exact': group['title']}, ensure_ascii=False)
            existing = self.db.execute('SELECT id FROM learned_rules WHERE conditions=?', (conditions,)).fetchone()
            rule_id = existing[0] if existing else uid()
            self.db.execute(
                """INSERT INTO learned_rules VALUES (?,?,?,1,1) ON CONFLICT(id) DO UPDATE
                SET task_id=excluded.task_id,conditions=excluded.conditions,approved=1,enabled=1""",
                (rule_id, task, conditions),
            )
            for origin in group['origins']:
                self.db.execute('INSERT OR IGNORE INTO rule_origins VALUES (?,?)', (rule_id, origin))
            self._apply_title_classification(group['title'], task, tag_ids, skip=confirmed)

    def _apply_title_classification(self, title, task, tag_ids, skip=()):
        rows = self.db.execute(
            """SELECT i.id, i.title, r.manual, r.event_id
            FROM activity_intervals i
            LEFT JOIN task_results r ON r.interval_id=i.id
            WHERE i.state='active' AND i.end_ms>i.start_ms"""
        ).fetchall()
        wanted = title.casefold()
        for row in rows:
            if row['id'] in skip or normalize(row['title'] or '').strip().casefold() != wanted or row['manual']:
                continue
            event_id = row['event_id']
            if not event_id:
                event = self.db.execute(
                    """SELECT e.id FROM activity_events e
                    JOIN activity_intervals i ON e.session_id=i.session_id AND e.at_ms=i.start_ms
                    AND e.state='active' AND e.kind IN ('foreground_switch','title_change')
                    WHERE i.id=? ORDER BY e.rowid DESC LIMIT 1""",
                    (row['id'],),
                ).fetchone()
                if not event:
                    continue
                event_id = event[0]
            self.db.execute(
                """INSERT INTO task_results(interval_id,event_id,task_id,reliability,source,reason,manual,disposition)
                VALUES (?,?,?,'supported','rule','与已确认的同标题活动一致',0,'review')
                ON CONFLICT(interval_id) DO UPDATE SET
                  task_id=excluded.task_id, reliability='supported', source='rule',
                  reason=excluded.reason, manual=0, disposition='review',
                  revision=task_results.revision+1
                WHERE task_results.manual=0""",
                (row['id'], event_id, task),
            )
            self.db.execute('DELETE FROM activity_tags WHERE interval_id=?', (row['id'],))
            if tag_ids:
                self.db.executemany('INSERT INTO activity_tags VALUES (?,?)', ((row['id'], tag) for tag in tag_ids))
