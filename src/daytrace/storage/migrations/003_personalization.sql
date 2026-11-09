BEGIN IMMEDIATE;
CREATE TABLE personal_state (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL);
INSERT INTO personal_state VALUES (1,0);
CREATE TABLE personal_profile (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
CREATE TABLE personal_tasks (id TEXT PRIMARY KEY, label TEXT NOT NULL, category TEXT NOT NULL, project TEXT NOT NULL, created_ms INTEGER NOT NULL DEFAULT (unixepoch()*1000));
CREATE TABLE task_results (
 interval_id TEXT PRIMARY KEY REFERENCES activity_intervals(id) ON DELETE CASCADE,
 event_id TEXT NOT NULL REFERENCES activity_events(id) ON DELETE CASCADE,
 task_id TEXT REFERENCES personal_tasks(id) ON DELETE SET NULL,
 reliability TEXT NOT NULL CHECK(reliability IN ('supported','tentative','unknown')),
 source TEXT NOT NULL, reason TEXT NOT NULL, manual INTEGER NOT NULL DEFAULT 0,
 disposition TEXT NOT NULL DEFAULT 'review', revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE activity_feedback (
 id TEXT PRIMARY KEY, interval_id TEXT NOT NULL REFERENCES task_results(interval_id) ON DELETE CASCADE,
 task_id TEXT REFERENCES personal_tasks(id) ON DELETE SET NULL,
 action TEXT NOT NULL, created_ms INTEGER NOT NULL, previous_id TEXT REFERENCES activity_feedback(id) ON DELETE SET NULL
);
CREATE TABLE activity_cases (
 interval_id TEXT PRIMARY KEY REFERENCES task_results(interval_id) ON DELETE CASCADE,
 task_id TEXT NOT NULL REFERENCES personal_tasks(id) ON DELETE CASCADE
);
CREATE TABLE learned_rules (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES personal_tasks(id) ON DELETE CASCADE,
 conditions TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, approved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE analysis_runs (id TEXT PRIMARY KEY, created_ms INTEGER NOT NULL, count INTEGER NOT NULL, source TEXT NOT NULL);
CREATE TABLE rule_origins (
 rule_id TEXT NOT NULL REFERENCES learned_rules(id) ON DELETE CASCADE,
 interval_id TEXT NOT NULL REFERENCES activity_intervals(id) ON DELETE CASCADE,
 PRIMARY KEY(rule_id,interval_id)
);
CREATE TRIGGER remove_derived_rules BEFORE DELETE ON task_results
BEGIN
 DELETE FROM learned_rules WHERE id IN (SELECT rule_id FROM rule_origins WHERE interval_id=OLD.interval_id);
END;
CREATE TRIGGER remove_interval_rules BEFORE DELETE ON activity_intervals
BEGIN
 DELETE FROM learned_rules WHERE id IN (SELECT rule_id FROM rule_origins WHERE interval_id=OLD.id);
END;
PRAGMA user_version=3;
COMMIT;
