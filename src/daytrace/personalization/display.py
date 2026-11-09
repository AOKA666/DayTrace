"""Display-only grouping. Never changes source intervals or task assignments."""


def activity_label(row):
    if row.get('label'):
        return row['label']
    if row['state'] != 'active':
        if row.get('short_gap'):
            return 'gap · 短暂停留'
        return {'excluded': '隐私排除', 'idle': '无输入空闲', 'paused': '已暂停',
                'unknown': 'gap · 记录缺口', 'locked': '已锁屏'}.get(row['state'], row['state'])
    title = row.get('title') or ''
    for suffix in (' - Google Chrome', ' — Google Chrome', ' - Microsoft Edge'):
        if title.endswith(suffix):
            title = title[:-len(suffix)]
            break
    return title or row.get('process_name') or '标题不可用'


def group_rows(rows):
    groups, lookup = [], {}
    previous = None
    for row in rows:
        if previous and (previous['end_ms'] != row['start_ms'] or previous['session_id'] != row['session_id']):
            lookup = {}
        previous = row
        if row['state'] != 'active':
            lookup = {}
            groups.append([row])
            continue
        # A shared application alone never groups unrelated activity.
        identity = ('task', row['task_id']) if row.get('task_id') else (
            ('title', row.get('app_id'), row.get('process_name'), row['title']) if row.get('title') else ('single', row['interval_id']))
        key = (identity, row.get('reliability'), row.get('manual'), row.get('disposition'))
        if key not in lookup:
            lookup[key] = []
            groups.append(lookup[key])
        lookup[key].append(row)
    return groups
