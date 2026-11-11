BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS dwell_members(
 interval_id TEXT PRIMARY KEY REFERENCES activity_intervals(id) ON DELETE CASCADE,
 group_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dwell_group ON dwell_members(group_id);
INSERT OR REPLACE INTO schema_extensions VALUES('dwell_returns',1);
COMMIT;
