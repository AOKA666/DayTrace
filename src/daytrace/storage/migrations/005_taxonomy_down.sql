BEGIN IMMEDIATE;
DROP TABLE feedback_tags;
DROP TABLE activity_tags;
DROP TABLE personal_tags;
DROP TABLE personal_categories;
PRAGMA user_version=4;
COMMIT;
