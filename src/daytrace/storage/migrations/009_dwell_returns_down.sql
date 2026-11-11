BEGIN IMMEDIATE;
DROP TABLE IF EXISTS dwell_members;
DELETE FROM schema_extensions WHERE name='dwell_returns';
COMMIT;
