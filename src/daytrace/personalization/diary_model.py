"""Read models for the diary. Source intervals are never rewritten or stretched."""
from datetime import datetime

DEFAULT_CATEGORIES = ['工作', '学习', '沟通', '娱乐', '生活', '其他']
DEFAULT_MERGE_GAP_MS = 180_000
DEFAULT_FOLD_GAP_MS = 120_000


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
            if row.get('short_gap'):
                label = '短暂停留'
                description = '低于当前停留阈值的片段；与相邻空隙一并折叠，不单独推断活动。'
            else:
                label = {'idle': '无输入空闲', 'excluded': '私人活动', 'paused': '记录已暂停', 'locked': '设备已锁定'}.get(
                    row['state'], '未记录时间'
                )
                description = '仅保留时间边界，不推断这段时间做了什么。'
        elif meaningful:
            label = row.get('label') or foreground_heading(row)
            description = row.get('reason') or ''
        else:
            label = foreground_heading(row)
            if row.get('title'):
                description = row.get('reason') or '前台窗口记录；可确认活动名称或等待整理。'
            else:
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


def _gap_card(card):
    return card['rows'][0]['state'] != 'active'


def _active_signature(card):
    row = card['rows'][0]
    return (
        card['title'].strip().casefold(),
        (row.get('title') or '').strip().casefold(),
        (row.get('process_name') or '').strip().casefold(),
        (card.get('category') or '').strip(),
        row.get('task_id') or '',
    )


def _join_cards(left, right):
    merged = dict(left)
    merged['end_ms'] = right['end_ms']
    merged['rows'] = left['rows'] + right['rows']
    merged['review'] = bool(left.get('review')) or bool(right.get('review'))
    if right.get('review'):
        merged['status'] = right.get('status') or left.get('status')
    return merged


def _merge_active_runs(items, merge_gap_ms):
    if not items:
        return []
    merged = [items[0]]
    for card in items[1:]:
        previous = merged[-1]
        if _gap_card(previous) or _gap_card(card):
            merged.append(card)
            continue
        gap = card['start_ms'] - previous['end_ms']
        same = _active_signature(previous) == _active_signature(card)
        if 0 <= gap <= merge_gap_ms and same:
            merged[-1] = _join_cards(previous, card)
            continue
        merged.append(card)
    return merged


def _gap_has_short_dwell(card):
    return any(r.get('short_gap') for r in card.get('rows', []))


def _absorb_micro_gaps(items, merge_gap_ms, fold_gap_ms):
    if len(items) < 2:
        return items
    changed = True
    work = list(items)
    while changed:
        changed = False
        next_pass = []
        index = 0
        while index < len(work):
            card = work[index]
            if (
                index + 2 < len(work)
                and _gap_card(work[index + 1])
                and not _gap_card(card)
                and not _gap_card(work[index + 2])
            ):
                gap = work[index + 1]
                gap_len = gap['end_ms'] - gap['start_ms']
                bridge = work[index + 2]['start_ms'] - card['end_ms']
                if (
                    not _gap_has_short_dwell(gap)
                    and gap_len <= fold_gap_ms
                    and bridge <= merge_gap_ms
                    and _active_signature(card) == _active_signature(work[index + 2])
                ):
                    joined = _join_cards(card, work[index + 2])
                    joined['start_ms'] = card['start_ms']
                    next_pass.append(joined)
                    index += 3
                    changed = True
                    continue
            if _gap_card(card) and (card['end_ms'] - card['start_ms']) <= fold_gap_ms:
                if _gap_has_short_dwell(card):
                    next_pass.append(card)
                    index += 1
                    continue
                if next_pass and not _gap_card(next_pass[-1]):
                    next_pass[-1]['end_ms'] = card['end_ms']
                    index += 1
                    changed = True
                    continue
                if index + 1 < len(work) and not _gap_card(work[index + 1]):
                    work[index + 1] = dict(work[index + 1], start_ms=card['start_ms'])
                    index += 1
                    changed = True
                    continue
            next_pass.append(card)
            index += 1
        work = next_pass
    return work


def _merge_gap_cards(items):
    merged = []
    for card in items:
        if merged and _gap_card(merged[-1]) and _gap_card(card) and merged[-1]['rows'][0]['state'] == card['rows'][0]['state']:
            joined = _join_cards(merged[-1], card)
            if _gap_has_short_dwell(joined):
                joined['title'] = '短暂停留'
                joined['description'] = '低于当前停留阈值的片段；与相邻空隙一并折叠，不单独推断活动。'
            merged[-1] = joined
            continue
        merged.append(card)
    return merged


def project_dwell_threshold(rows, dwell_ms):
    """Any active interval shorter than dwell becomes brief dwell (display-only)."""
    dwell_ms = max(0, int(dwell_ms))
    projected = []
    for row in rows:
        item = dict(row)
        span = item['end_ms'] - item['start_ms']
        if item['state'] == 'active' and span < dwell_ms:
            item.update(
                state='unknown',
                title=None,
                label=None,
                category='',
                project='',
                task_id=None,
                short_gap=1,
                reliability='unknown',
                source='dwell_display',
                reason='',
            )
        projected.append(item)
    return projected


def collapse_short_gap_rows(rows):
    """Merge consecutive non-active gap rows so brief dwell does not spam the timeline."""
    if not rows:
        return []
    merged = []
    for row in rows:
        item = dict(row)
        gapish = item['state'] != 'active' and item['state'] != 'excluded'
        if (
            merged
            and gapish
            and merged[-1]['state'] != 'active'
            and merged[-1]['state'] != 'excluded'
            and merged[-1]['end_ms'] == item['start_ms']
        ):
            merged[-1]['end_ms'] = item['end_ms']
            merged[-1]['short_gap'] = merged[-1].get('short_gap') or item.get('short_gap')
            continue
        merged.append(item)
    return merged


def prepare_diary_rows(rows, dwell_ms):
    return collapse_short_gap_rows(project_dwell_threshold(rows, dwell_ms))


def _is_brief_dwell_card(card, dwell_ms):
    dwell_ms = max(0, int(dwell_ms))
    span = card['end_ms'] - card['start_ms']
    if dwell_ms and span < dwell_ms:
        return True
    return _gap_card(card) and (card.get('title') == '短暂停留' or _gap_has_short_dwell(card))


def filter_short_dwell_cards(items, show_short_dwells=False, dwell_ms=0):
    if show_short_dwells:
        return items
    return [card for card in items if not _is_brief_dwell_card(card, dwell_ms)]


def build_display_cards(
    rows,
    dwell_ms,
    merge_gap_ms=DEFAULT_MERGE_GAP_MS,
    fold_gap_ms=DEFAULT_FOLD_GAP_MS,
    show_short_dwells=False,
):
    """Presentation pipeline: dwell projection → cards → compaction → optional brief-dwell filter."""
    items = compact_cards(cards(prepare_diary_rows(rows, dwell_ms)), merge_gap_ms, fold_gap_ms)
    return filter_short_dwell_cards(items, show_short_dwells, dwell_ms)


def compact_cards(items, merge_gap_ms=DEFAULT_MERGE_GAP_MS, fold_gap_ms=DEFAULT_FOLD_GAP_MS):
    """Presentation-only compaction: merge fragmented active cards and fold short gaps."""
    if not items:
        return []
    merge_gap_ms = max(0, merge_gap_ms)
    fold_gap_ms = max(0, fold_gap_ms)
    work = _merge_active_runs(items, merge_gap_ms)
    work = _absorb_micro_gaps(work, merge_gap_ms, fold_gap_ms)
    return _merge_gap_cards(work)
