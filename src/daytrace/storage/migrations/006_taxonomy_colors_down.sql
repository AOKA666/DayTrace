BEGIN IMMEDIATE;
DROP TRIGGER category_parent_color;
DROP TRIGGER category_child_color_insert;
DROP TRIGGER category_child_color_update;
ALTER TABLE personal_tags DROP COLUMN color;
PRAGMA user_version=5;
COMMIT;
