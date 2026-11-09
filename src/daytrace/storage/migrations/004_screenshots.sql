BEGIN IMMEDIATE;
CREATE TABLE screenshots (
 id TEXT PRIMARY KEY,
 event_id TEXT NOT NULL REFERENCES activity_events(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL REFERENCES capture_sessions(id) ON DELETE CASCADE,
 captured_ms INTEGER NOT NULL, expires_ms INTEGER NOT NULL,
 filename TEXT NOT NULL UNIQUE, width INTEGER NOT NULL, height INTEGER NOT NULL
);
CREATE TABLE screenshot_deletions (filename TEXT PRIMARY KEY);
CREATE TRIGGER screenshot_delete AFTER DELETE ON screenshots
BEGIN INSERT OR IGNORE INTO screenshot_deletions VALUES (OLD.filename); END;
PRAGMA user_version=4;
COMMIT;
