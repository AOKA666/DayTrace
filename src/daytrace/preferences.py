"""Non-sensitive, per-database capture preferences. Never stores credentials."""
import json
import math
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


def options(database):
    try:
        value=json.loads(Path(str(database)+'.preferences.json').read_text('utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}


def screenshots_enabled(database):
    return options(database).get('screenshots_enabled') is True


def save_options(database, **changes):
    path = Path(str(database) + '.preferences.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    try:
        value=options(database)
        value.update(changes)
        temporary.write_text(json.dumps(value), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
