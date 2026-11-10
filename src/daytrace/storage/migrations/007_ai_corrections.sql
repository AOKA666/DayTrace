BEGIN IMMEDIATE;
CREATE TABLE ai_corrections (
 feedback_id TEXT PRIMARY KEY REFERENCES activity_feedback(id) ON DELETE CASCADE,
 previous_category TEXT NOT NULL
);
PRAGMA user_version=7;
COMMIT;
