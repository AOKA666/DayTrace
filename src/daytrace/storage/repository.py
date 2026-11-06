from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
import uuid


def uid():
    return str(uuid.uuid4())


class InstanceLock:
    """OS-owned lock: releases automatically on a killed collector, no stale PID guessing."""
    def __init__(self, database: Path):
        self.path = Path(str(database.resolve()) + ".lock")
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.file.seek(0, 2) == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError("Collector is running for this database.") from None
        return self

    def __exit__(self, *args):
        if self.file:
            self.file.close()
            self.file = None


def is_running(database: Path) -> bool:
    try:
        with InstanceLock(database):
            return False
    except RuntimeError:
        return True


class Repository:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA secure_delete=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.db.executescript((Path(__file__).parent / "migrations/001_activity.sql").read_text("utf-8"))
            version = 1
        if version == 1:
            self.db.executescript((Path(__file__).parent / "migrations/002_content.sql").read_text("utf-8"))
        elif version != 2:
            self.db.close()
            raise RuntimeError("Unsupported database schema version.")
        with self.db:
            if not self.db.execute("SELECT 1 FROM devices").fetchone():
                self.db.execute("INSERT INTO devices VALUES (?,?)", (uid(), "windows"))
        self.device_id = self.db.execute("SELECT id FROM devices").fetchone()[0]

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def close(self):
        self.db.close()

    def recover(self, now: int):
        """Only call with InstanceLock held. Last checkpoint already bounds intervals."""
        with self.transaction():
            for row in self.db.execute("SELECT * FROM capture_sessions WHERE ended_ms IS NULL").fetchall():
                end = row["heartbeat_ms"]
                self.db.execute("UPDATE capture_sessions SET ended_ms=?,status='stopped',exit_reason='crash' WHERE id=?", (end, row["id"]))
                self.db.execute("UPDATE control_commands SET acknowledged_ms=?,result='abandoned' WHERE session_id=? AND acknowledged_ms IS NULL", (now, row["id"]))
                if now > end:
                    self.interval(row["id"], end, now, "unknown")
                self.event(row["id"], max(now, end), now, "crash_recovery", "unknown", source="recovery")

    def interval(self, session, start, end, state, process=None, app=None, title=None):
        identifier = uid()
        self.db.execute("INSERT INTO activity_intervals(id,session_id,start_ms,end_ms,state,process_name,app_id,title) VALUES (?,?,?,?,?,?,?,?)",
                        (identifier, session, start, end, state, process, app, title))
        return identifier

    def event(self, session, at, wall, kind, state, process=None, app=None, title=None, source="poll"):
        identifier = uid()
        self.db.execute("INSERT INTO activity_events(id,device_id,session_id,platform,at_ms,observed_wall_ms,kind,state,process_name,app_id,title,source) VALUES (?,?,?,'windows',?,?,?,?,?,?,?,?)",
                        (identifier, self.device_id, session, at, wall, kind, state, process, app, title, source))
        return identifier

    def content(self, session, event, captured, result, policy_version, window_token=None):
        identifier = uid()
        with self.transaction():
            valid = self.db.execute("SELECT 1 FROM activity_events e JOIN capture_sessions s ON s.id=e.session_id WHERE e.id=? AND e.session_id=? AND s.ended_ms IS NULL AND s.status='running'", (event, session)).fetchone()
            if not valid:
                return None
            self.db.execute("INSERT INTO content_samples(id,event_id,session_id,captured_ms,source,status,text,content_hash,duplicate_of,char_count,elapsed_ms,quality,policy_version,window_token,expires_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (identifier,event,session,captured,result['source'],result['status'],result.get('text'),result.get('content_hash'),result.get('duplicate_of'),result.get('char_count',0),result.get('elapsed_ms',0),result.get('quality'),policy_version,window_token,captured+7*86_400_000))
        return identifier

    def reclassify_idle(self, session, cutoff):
        # Never rewrite excluded/paused/locked/unknown. Preserve foreground event facts.
        rows = self.db.execute("SELECT * FROM activity_intervals WHERE session_id=? AND state='active' AND end_ms>? ORDER BY start_ms", (session, cutoff)).fetchall()
        for row in rows:
            if row["start_ms"] >= cutoff:
                self.db.execute("UPDATE activity_intervals SET state='idle',process_name=NULL,app_id=NULL,title=NULL WHERE id=?", (row["id"],))
            else:
                self.db.execute("UPDATE activity_intervals SET end_ms=? WHERE id=?", (cutoff, row["id"]))
                self.interval(session, cutoff, row["end_ms"], "idle")

    def cleanup(self, now):
        day = 86_400_000
        with self.transaction():
            self.db.execute("DELETE FROM content_samples WHERE expires_ms<=?", (now,))
            self.db.execute("UPDATE activity_events SET title=NULL WHERE at_ms<?", (now - 7 * day,))
            self.db.execute("UPDATE activity_intervals SET title=NULL WHERE start_ms<?", (now - 7 * day,))
            cutoff = now - 90 * day
            self.db.execute("DELETE FROM activity_events WHERE at_ms<?", (cutoff,))
            self.db.execute("DELETE FROM activity_intervals WHERE end_ms<=?", (cutoff,))
            self.db.execute("UPDATE activity_intervals SET start_ms=? WHERE start_ms<? AND end_ms>?", (cutoff, cutoff, cutoff))
            self.db.execute("DELETE FROM control_commands WHERE acknowledged_ms IS NOT NULL AND acknowledged_ms<?", (now - day,))
            self.db.execute("DELETE FROM capture_sessions WHERE ended_ms IS NOT NULL AND ended_ms<? AND NOT EXISTS (SELECT 1 FROM activity_intervals WHERE session_id=capture_sessions.id)", (cutoff,))
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def readonly(path: Path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db
