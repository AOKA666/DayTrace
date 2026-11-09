"""Read models for the diary. Source intervals are never rewritten or stretched."""
from datetime import datetime

DEFAULT_CATEGORIES = ['工作', '学习', '沟通', '娱乐', '生活', '其他']


def foreground_heading(row) -> str:
    """Use captured window identity when no task label exists yet."""
    title = (row.get('title') or '').strip()
    if title:
        return title
    process = (row.get('process_name') or '').strip()
    if process:
        return process
    return '待确认的活动'


def duration(ms):
    seconds = max(0, round(ms / 1000))
    if seconds < 60:
        return f'{seconds} 秒'
    minutes = seconds // 60
    return f'{minutes // 60} 小时 {minutes % 60} 分钟' if minutes >= 60 else f'{minutes} 分钟'


def cards(rows):
    """Only contiguous equal semantic tasks coalesce; never bridge B in A→B→A."""
    result = []
    for row in sorted(rows, key=lambda r: (r['start_ms'], r['end_ms'])):
        active = row['state'] == 'active'
        # An upper category is not a task identity.
        meaningful = active and row.get('label') and row.get('label') != row.get('category')
        identity = ('task', row.get('task_id')) if meaningful and row.get('task_id') else (
            ('evidence', row.get('title'), row.get('app_id')) if active and row.get('title') else
            ('state', row['state']) if not active else ('single', row['interval_id']))
        key = (row.get('session_id'), identity, row.get('manual'), row.get('disposition'), row.get('reliability'))
        if result and result[-1]['key'] == key and result[-1]['end_ms'] == row['start_ms']:
            card = result[-1]
            card['end_ms'] = row['end_ms']
            card['rows'].append(row)
            continue
        if not active:
            label = {'idle': '无输入空闲', 'excluded': '私人活动', 'paused': '记录已暂停', 'locked': '设备已锁定'}.get(
                row['state'], '未记录时间'
            )
            description = '仅保留时间边界，不推断这段时间做了什么。'
        elif meaningful:
            label = row.get('label') or foreground_heading(row)
            description = row.get('reason') or ''
        else:
            label = foreground_heading(row)
            description = row.get('reason') or '记录中的窗口标题；可点开确认活动名称或等待 AI 整理。'
        result.append(dict(key=key, start_ms=row['start_ms'], end_ms=row['end_ms'], rows=[row],
            title=label, category=row.get('category') or ('待确认' if active else ''), project=row.get('project') or '',
            description=description,
            review=active and row.get('reliability') != 'supported' and row.get('disposition') != 'ignore',
            status='已确认' if row.get('manual') else 'AI 建议 · 待确认' if row.get('source') == 'ai' else '规则识别' if row.get('source') == 'rule' else '待确认' if active else ''))
    return result


def overview(items):
    totals = {}
    for card in items:
        if card['rows'][0]['state'] != 'active':
            continue
        row = card['rows'][0]
        if card['title'] == '待确认的活动' and not (row.get('title') or row.get('process_name')):
            continue
        totals[card['title']] = totals.get(card['title'], 0) + card['end_ms'] - card['start_ms']
    top = sorted(totals.items(), key=lambda x: -x[1])[:3]
    pending = sum(c['review'] for c in items)
    text = '；'.join(f'{name}（{duration(ms)}）' for name, ms in top)
    return (text or '活动还在整理中，确认后的记录会呈现在这里。') + (f'\n还有 {pending} 段活动需要确认。' if pending else '')
