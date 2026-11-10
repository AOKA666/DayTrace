"""Managed local evidence files. No image content is logged or uploaded."""
from pathlib import Path
import re
from .repository import uid


def enabled(repo):
    return repo.db.execute('PRAGMA user_version').fetchone()[0] >= 4


def directory(repo):
    return Path(str(repo.path) + '.screenshots')


def file_path(repo, name):
    if not re.fullmatch(r'[0-9a-f-]{36}\.png', name):
        raise ValueError('Invalid screenshot name')
    base = directory(repo)
    if base.is_symlink() or (base.exists() and base.resolve() != base.absolute()):
        raise ValueError('Screenshot directory must not redirect')
    path = base / name
    if path.is_symlink():
        raise ValueError('Screenshot must not redirect')
    return path


def migrate(repo):
    version = repo.db.execute('PRAGMA user_version').fetchone()[0]
    root = Path(__file__).parent / 'migrations'
    if version == 2:
        repo.db.executescript((root/'003_personalization.sql').read_text('utf-8'))
        version = 3
    if version == 3:
        repo.db.executescript((root/'004_screenshots.sql').read_text('utf-8'))


def save(repo, event, session, captured, png, width, height, days):
    if not enabled(repo) or not isinstance(png, bytes) or not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png)>16_000_000:
        return None
    if not 0 < days <= 7 or not 0 < width*height <= 16_000_000:
        return None
    identifier = uid()
    path = file_path(repo, identifier+'.png')
    try:
        with repo.transaction():
            if not repo.db.execute("SELECT 1 FROM activity_events e JOIN capture_sessions s ON s.id=e.session_id WHERE e.id=? AND e.session_id=? AND e.state='active' AND s.status='running' AND s.ended_ms IS NULL", (event,session)).fetchone():
                return None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png)
            repo.db.execute('INSERT INTO screenshots VALUES (?,?,?,?,?,?,?,?)', (identifier,event,session,captured,captured+int(days*86_400_000),path.name,width,height))
        return identifier
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def cleanup(repo):
    if not enabled(repo):
        return
    # Serialize file reconciliation against writers to avoid deleting in-flight files.
    with repo.transaction():
        for row in repo.db.execute('SELECT filename FROM screenshot_deletions').fetchall():
            file_path(repo, row[0]).unlink(missing_ok=True)
            repo.db.execute('DELETE FROM screenshot_deletions WHERE filename=?', (row[0],))
        base = directory(repo)
        if base.exists():
            known = {r[0] for r in repo.db.execute('SELECT filename FROM screenshots')}
            for path in base.glob('*.png'):
                if path.name not in known:
                    file_path(repo, path.name).unlink(missing_ok=True)


def read(repo, interval, now):
    if not enabled(repo):
        return None
    row = repo.db.execute('''SELECT p.* FROM screenshots p JOIN activity_events e ON e.id=p.event_id
        JOIN activity_intervals i ON i.session_id=e.session_id AND i.start_ms=e.at_ms
        WHERE i.id=? AND i.state='active' AND p.expires_ms>? AND p.captured_ms<i.end_ms
        ORDER BY p.captured_ms DESC LIMIT 1''', (interval,now)).fetchone()
    if row:
        path = file_path(repo,row['filename'])
        if path.is_file():
            return dict(row, png=path.read_bytes())
    return None


def delete_interval(repo, interval):
    from .repository import InstanceLock
    # Exclude a live collector so an already-running capture cannot restore a
    # screenshot immediately after the user deletes it.
    with InstanceLock(repo.path):
        _delete_interval(repo, interval)


def _delete_interval(repo, interval):
    if enabled(repo):
        with repo.transaction():
            repo.db.execute('''DELETE FROM screenshots WHERE event_id IN (
                SELECT e.id FROM activity_events e JOIN activity_intervals i
                ON e.session_id=i.session_id AND e.at_ms=i.start_ms WHERE i.id=?)''', (interval,))
        cleanup(repo)


def rollback(repo):
    """Call only while stopped; remove files before dropping their registry."""
    from .repository import InstanceLock
    with InstanceLock(repo.path):
        if repo.db.execute('PRAGMA user_version').fetchone()[0] > 4:
            raise ValueError('Roll back newer migrations before the screenshot schema.')
        if enabled(repo):
            with repo.transaction():
                repo.db.execute('DELETE FROM screenshots')
            cleanup(repo)
            repo.db.executescript((Path(__file__).parent/'migrations/004_screenshots_down.sql').read_text('utf-8'))
