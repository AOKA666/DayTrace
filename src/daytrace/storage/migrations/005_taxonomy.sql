BEGIN IMMEDIATE;
CREATE TABLE personal_categories (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 parent_id TEXT REFERENCES personal_categories(id) ON DELETE CASCADE,
 color TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE UNIQUE INDEX category_siblings ON personal_categories(COALESCE(parent_id,''),name);
CREATE TABLE personal_tags (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE activity_tags (
 interval_id TEXT NOT NULL REFERENCES task_results(interval_id) ON DELETE CASCADE,
 tag_id TEXT NOT NULL REFERENCES personal_tags(id) ON DELETE CASCADE,
 PRIMARY KEY(interval_id,tag_id)
);
CREATE TABLE feedback_tags (
 feedback_id TEXT NOT NULL REFERENCES activity_feedback(id) ON DELETE CASCADE,
 tag_id TEXT NOT NULL REFERENCES personal_tags(id) ON DELETE CASCADE,
 PRIMARY KEY(feedback_id,tag_id)
);
PRAGMA user_version=5;
COMMIT;
