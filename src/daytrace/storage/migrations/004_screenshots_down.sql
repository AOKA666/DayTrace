BEGIN IMMEDIATE;
DROP TRIGGER screenshot_delete;
DROP TABLE screenshots;
DROP TABLE screenshot_deletions;
PRAGMA user_version=3;
COMMIT;
