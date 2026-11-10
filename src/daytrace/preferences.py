"""Non-sensitive, per-database capture preferences. Never stores credentials."""
import json
import math
import os
import secrets
from pathlib import Path


def validate_dwell(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 300:
        raise ValueError('Minimum dwell must be between 0 and 300 seconds')
    return value


def dwell_seconds(database):
    path = Path(str(database) + '.preferences.json')
    try:
        return validate_dwell(json.loads(path.read_text('utf-8'))['min_dwell_seconds'])
    except (OSError, ValueError, KeyError, TypeError):
        return 5.0


def save_dwell(database, seconds):
    save_options(database, min_dwell_seconds=validate_dwell(seconds))


def _preferences_path(database):
    return Path(str(database) + '.preferences.json')


def _read_options_dict(path):
    try:
        if not path.is_file():
            return {}
        text = path.read_text('utf-8')
        if not text.strip():
            return {}
        value = json.loads(text)
        return dict(value) if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def options(database):
    return _read_options_dict(_preferences_path(database))


def screenshots_enabled(database):
    return options(database).get('screenshots_enabled') is True


def show_short_dwells(database):
    return options(database).get('show_short_dwells') is True


def diary_display_ms(database):
    """Read dwell + diary compaction thresholds as milliseconds (presentation layer)."""
    dwell_ms = int(round(dwell_seconds(database) * 1000))
    merge_ms, fold_ms = diary_gap_ms(database)
    return dwell_ms, merge_ms, fold_ms


def diary_gap_ms(database):
    opts = options(database)
    try:
        merge = int(opts.get('diary_merge_gap_seconds', 180))
    except (TypeError, ValueError):
        merge = 180
    try:
        fold = int(opts.get('diary_fold_gap_seconds', 120))
    except (TypeError, ValueError):
        fold = 120
    merge = max(0, min(600, merge)) * 1000
    fold = max(0, min(600, fold)) * 1000
    return merge, fold


def save_options(database, **changes):
    path = _preferences_path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        value = _read_options_dict(path)
        if attempt == 0 and not value and path.is_file():
            try:
                if path.stat().st_size > 2:
                    value = _read_options_dict(path)
            except OSError:
                pass
        value.update(changes)
        temporary = path.with_name(
            f'{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}'
        )
        try:
            temporary.write_text(
                json.dumps(value, ensure_ascii=False),
                encoding='utf-8',
            )
            temporary.replace(path)
            return
        finally:
            temporary.unlink(missing_ok=True)
