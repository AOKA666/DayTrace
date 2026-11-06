BEGIN IMMEDIATE;
CREATE TABLE content_samples (
 id TEXT PRIMARY KEY,
 schema_version INTEGER NOT NULL DEFAULT 1,
 event_id TEXT NOT NULL REFERENCES activity_events(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL REFERENCES capture_sessions(id) ON DELETE CASCADE,
 captured_ms INTEGER NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('uia','ocr','policy')),
 status TEXT NOT NULL,
 text TEXT,
 content_hash TEXT,
 duplicate_of TEXT REFERENCES content_samples(id) ON DELETE SET NULL,
 char_count INTEGER NOT NULL DEFAULT 0,
 elapsed_ms INTEGER NOT NULL DEFAULT 0,
 quality REAL,
 policy_version INTEGER NOT NULL,
 window_token TEXT,
 expires_ms INTEGER NOT NULL,
 CHECK(text IS NULL OR length(text)<=8000)
);
CREATE INDEX content_event ON content_samples(event_id);
CREATE INDEX content_expiry ON content_samples(expires_ms);
CREATE INDEX content_session ON content_samples(session_id,captured_ms);
PRAGMA user_version=2;
COMMIT;
