BEGIN IMMEDIATE;
DROP TRIGGER IF EXISTS browser_private;
DROP TRIGGER IF EXISTS browser_trim;
DROP TABLE IF EXISTS browser_pages;
DELETE FROM schema_extensions WHERE name='browser_pages';
COMMIT;
