BEGIN IMMEDIATE;
CREATE TABLE devices (
 id TEXT PRIMARY KEY, platform TEXT NOT NULL
);
CREATE TABLE capture_sessions (
 id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id),
 platform TEXT NOT NULL, started_ms INTEGER NOT NULL, ended_ms INTEGER,
 heartbeat_ms INTEGER NOT NULL, timezone TEXT NOT NULL, pid INTEGER NOT NULL,
 status TEXT NOT NULL, exit_reason TEXT, simulated INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX single_open_session ON capture_sessions((1)) WHERE ended_ms IS NULL;
CREATE TABLE activity_events (
 id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL DEFAULT 1,
 device_id TEXT NOT NULL REFERENCES devices(id),
 session_id TEXT NOT NULL REFERENCES capture_sessions(id) ON DELETE CASCADE,
 platform TEXT NOT NULL, at_ms INTEGER NOT NULL, observed_wall_ms INTEGER NOT NULL,
 kind TEXT NOT NULL, state TEXT NOT NULL, process_name TEXT, app_id TEXT, title TEXT,
 source TEXT NOT NULL
);
CREATE INDEX event_time ON activity_events(at_ms);
CREATE TABLE activity_intervals (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES capture_sessions(id) ON DELETE CASCADE,
 start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
 duration_ms INTEGER GENERATED ALWAYS AS (end_ms-start_ms) VIRTUAL,
 state TEXT NOT NULL CHECK(state IN ('active','idle','paused','locked','suspended','excluded','unknown')),
 process_name TEXT, app_id TEXT, title TEXT,
 CHECK(end_ms >= start_ms)
);
CREATE INDEX interval_time ON activity_intervals(start_ms,end_ms);
CREATE TRIGGER interval_insert_overlap BEFORE INSERT ON activity_intervals
WHEN NEW.end_ms > NEW.start_ms AND EXISTS (
 SELECT 1 FROM activity_intervals WHERE start_ms < NEW.end_ms AND end_ms > NEW.start_ms
)
BEGIN SELECT RAISE(ABORT, 'overlapping interval'); END;
CREATE TRIGGER interval_update_overlap BEFORE UPDATE OF start_ms,end_ms ON activity_intervals
WHEN NEW.end_ms > NEW.start_ms AND EXISTS (
 SELECT 1 FROM activity_intervals WHERE id != NEW.id AND start_ms < NEW.end_ms AND end_ms > NEW.start_ms
)
BEGIN SELECT RAISE(ABORT, 'overlapping interval'); END;
CREATE TABLE control_commands (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES capture_sessions(id) ON DELETE CASCADE,
 command TEXT NOT NULL CHECK(command IN ('pause','resume','stop')),
 requested_ms INTEGER NOT NULL, acknowledged_ms INTEGER, result TEXT
);
PRAGMA user_version=1;
COMMIT;
