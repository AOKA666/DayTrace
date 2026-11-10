BEGIN IMMEDIATE;
ALTER TABLE personal_tags ADD COLUMN color TEXT NOT NULL DEFAULT '#6550B5';
UPDATE personal_categories SET color=(SELECT p.color FROM personal_categories p WHERE p.id=personal_categories.parent_id) WHERE parent_id IS NOT NULL;
CREATE TRIGGER category_parent_color AFTER UPDATE OF color ON personal_categories
WHEN NEW.parent_id IS NULL
BEGIN UPDATE personal_categories SET color=NEW.color WHERE parent_id=NEW.id; END;
CREATE TRIGGER category_child_color_insert AFTER INSERT ON personal_categories
WHEN NEW.parent_id IS NOT NULL
BEGIN UPDATE personal_categories SET color=(SELECT color FROM personal_categories WHERE id=NEW.parent_id) WHERE id=NEW.id; END;
CREATE TRIGGER category_child_color_update AFTER UPDATE OF color,parent_id ON personal_categories
WHEN NEW.parent_id IS NOT NULL AND NEW.color != (SELECT color FROM personal_categories WHERE id=NEW.parent_id)
BEGIN UPDATE personal_categories SET color=(SELECT color FROM personal_categories WHERE id=NEW.parent_id) WHERE id=NEW.id; END;
PRAGMA user_version=6;
COMMIT;
