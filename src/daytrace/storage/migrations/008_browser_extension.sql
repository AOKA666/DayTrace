-- Independently versioned additive extension; compatible with base schemas 2–7.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS schema_extensions(name TEXT PRIMARY KEY, version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS browser_pages(
 id TEXT PRIMARY KEY,
 interval_id TEXT NOT NULL REFERENCES activity_intervals(id) ON DELETE CASCADE,
 event_id TEXT NOT NULL REFERENCES activity_events(id) ON DELETE CASCADE,
 captured_ms INTEGER NOT NULL,
 title TEXT,
 url TEXT NOT NULL,
 domain TEXT NOT NULL,
 expires_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS browser_pages_interval ON browser_pages(interval_id,captured_ms);
CREATE TRIGGER IF NOT EXISTS browser_private AFTER UPDATE OF state ON activity_intervals
 WHEN NEW.state!='active' BEGIN DELETE FROM browser_pages WHERE interval_id=NEW.id; END;
CREATE TRIGGER IF NOT EXISTS browser_trim AFTER UPDATE OF end_ms ON activity_intervals
 WHEN NEW.end_ms<OLD.end_ms BEGIN DELETE FROM browser_pages WHERE interval_id=NEW.id AND captured_ms>=NEW.end_ms; END;
INSERT OR REPLACE INTO schema_extensions VALUES('browser_pages',1);
COMMIT;
