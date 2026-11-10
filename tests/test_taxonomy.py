import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from daytrace.personalization.store import Memory
from daytrace.personalization.classifier import Classifier
from daytrace.personalization.diary_model import cards, build_display_cards
from daytrace.storage.repository import Repository, InstanceLock
from daytrace.domain import Observation
from daytrace.engine import Engine


class TaxonomyTests(unittest.TestCase):
    def test_only_changed_ai_category_is_a_correction(self):
        root = self.memory.create_category('工作')
        self.memory.confirm_selection([self.ids[0]], root)
        self.assertEqual(self.memory.correction_history(), [])
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM activity_cases').fetchone()[0], 0)
        with self.memory.repo.transaction():
            task = self.memory.task('阅读资料', '学习')
            self.memory.db.execute("UPDATE task_results SET task_id=?,source='ai',manual=0,reliability='tentative' WHERE interval_id=?", (task, self.ids[1]))
        self.memory.confirm_selection([self.ids[1]], root)
        history = self.memory.correction_history()
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]['previous_category'], history[0]['category']), ('学习', '工作'))
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM activity_cases').fetchone()[0], 1)
        self.memory.confirm_selection([self.ids[1]], root)
        self.assertEqual(len(self.memory.correction_history()), 1)
        self.memory.feedback(self.ids[1], action='private')
        self.assertEqual(self.memory.correction_history(), [])

    def test_accepting_ai_result_and_tag_changes_are_not_corrections(self):
        root = self.memory.create_category('工作')
        tag = self.memory.create_tag('AI')
        with self.memory.repo.transaction():
            task = self.memory.task('编程', '工作')
            self.memory.db.execute("UPDATE task_results SET task_id=?,source='ai',manual=0,reliability='tentative' WHERE interval_id=?", (task, self.ids[0]))
        self.memory.confirm_selection([self.ids[0]], root, [tag])
        self.assertEqual(self.memory.correction_history(), [])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'synthetic.sqlite3'
        self.now = time.time_ns() // 1_000_000
        self.memory = Memory(self.path, now=lambda: self.now)
        engine = Engine(self.memory.repo, self.now - 100_000, 0, simulated=True)
        for offset in range(0, 20_000, 1000):
            observation = Observation('active', 'Code.exe', 'code', 'Synthetic A', 1) if offset < 10_000 else Observation('active', 'chrome.exe', 'web', 'Synthetic B', 2)
            engine.sample(offset, self.now - 100_000 + offset, observation)
        engine.stop(20_000, self.now - 80_000)
        self.ids = self.memory.intervals()
        Classifier(self.memory).analyze()

    def tearDown(self):
        self.memory.close()
        self.folder.cleanup()

    def test_hierarchy_tags_persist_and_validate(self):
        root = self.memory.create_category('工作')
        child = self.memory.create_category('编程', root)
        tag = self.memory.create_tag('#AI编程出海')
        self.assertEqual(self.memory.profile()['activities'], ['工作', '工作 / 编程'])
        for fn in (lambda: self.memory.create_category('编程', root),
                   lambda: self.memory.create_category('三级', child),
                   lambda: self.memory.create_tag('AI编程出海')):
            with self.assertRaises(ValueError):
                fn()
        self.memory.close()
        self.memory = Memory(self.path, now=lambda: self.now)
        catalog = self.memory.catalog()
        self.assertEqual(catalog['categories'][1]['parent_id'], root)
        self.assertEqual(catalog['tags'][0]['id'], tag)
        self.assertEqual(catalog['tags'][0]['name'], 'AI编程出海')
        self.assertTrue(catalog['tags'][0]['color'].startswith('#'))

    def test_parent_color_inheritance_update_and_tag_restart(self):
        root = self.memory.create_category('工作', color='#5B8FCB')
        child = self.memory.create_category('编程', root, '#DC9B4B')
        self.assertEqual(self.memory.catalog()['categories'][1]['color'], '#5B8FCB')
        self.memory.update_category(child, '编程', '#CA7298')
        self.assertEqual(self.memory.catalog()['categories'][1]['color'], '#5B8FCB')
        self.memory.update_category(root, '工作', '#3C9B92')
        self.assertEqual({c['color'] for c in self.memory.catalog()['categories']}, {'#3C9B92'})
        tag = self.memory.create_tag('出海', '#DC9B4B')
        with self.assertRaises(ValueError):
            self.memory.create_tag('bad', 'invalid')
        self.memory.close()
        self.memory = Memory(self.path, now=lambda: self.now)
        self.assertEqual(self.memory.catalog()['tags'][0], {'id': tag, 'name': '出海', 'color': '#DC9B4B'})
        self.assertEqual({c['color'] for c in self.memory.catalog()['categories']}, {'#3C9B92'})

    def test_update_tag_renames_and_recolors(self):
        first = self.memory.create_tag('出海', '#DC9B4B')
        second = self.memory.create_tag('调研', '#5B8FCB')
        self.memory.update_tag(first, '#产品出海', '#3C9B92')
        tags = {row['id']: row for row in self.memory.catalog()['tags']}
        self.assertEqual(tags[first]['name'], '产品出海')
        self.assertEqual(tags[first]['color'], '#3C9B92')
        with self.assertRaises(ValueError):
            self.memory.update_tag(first, '调研', '#DC9B4B')
        with self.assertRaises(ValueError):
            self.memory.update_tag('missing', '新标签', '#DC9B4B')
        with self.assertRaises(ValueError):
            self.memory.update_tag(second, '仍叫调研', 'bad')
        self.assertEqual(self.memory.catalog()['tags'][1]['name'], '调研')

    def test_v5_upgrade_keeps_associations_and_repairs_old_child_colors(self):

        root = self.memory.create_category('工作', color='#5B8FCB')
        child = self.memory.create_category('编程', root)
        tag = self.memory.create_tag('旧标签')
        self.memory.confirm_selection([self.ids[0]], child, [tag])
        migration = Path(__file__).resolve().parents[1] / 'src/daytrace/storage/migrations/006_taxonomy_colors_down.sql'
        self.memory.db.executescript((migration.parent / '007_ai_corrections_down.sql').read_text('utf-8'))
        self.memory.db.executescript(migration.read_text('utf-8'))
        with self.memory.repo.transaction():
            self.memory.db.execute('UPDATE personal_categories SET color=? WHERE id=?', ('#CA7298', child))
        self.memory.close()
        self.memory = Memory(self.path, now=lambda: self.now)
        self.assertEqual(len(self.memory.catalog()['categories']), 2)
        self.assertEqual({c['color'] for c in self.memory.catalog()['categories']}, {'#5B8FCB'})
        self.assertEqual(self.memory.timeline()[0]['tags'][0]['id'], tag)
        self.assertEqual(self.memory.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_required_category_optional_tags_and_atomic_failure(self):
        root = self.memory.create_category('工作')
        for category, tags in ((None, []), (root, ['missing'])):
            with self.assertRaises(ValueError):
                self.memory.confirm_selection(self.ids, category, tags)
        self.assertEqual(self.memory.history(), [])
        self.memory.confirm_selection(self.ids, root)
        self.assertTrue(all(r['manual'] and not r['tags'] for r in self.memory.timeline()))
        self.assertTrue(all(r['label'] == '工作' for r in self.memory.timeline()))
        self.assertNotIn('Synthetic', str(self.memory.tasks()))

    def test_confirm_keeps_each_name_time_and_tags_across_reanalysis(self):
        root = self.memory.create_category('工作')
        child = self.memory.create_category('编程', root)
        tag = self.memory.create_tag('AI编程出海')
        self.memory.feedback(self.ids[0], 'First name', '旧分类', 'P1')
        self.memory.feedback(self.ids[1], 'Second name', '旧分类', 'P2')
        before = [(r['start_ms'], r['end_ms']) for r in self.memory.timeline()]
        self.memory.confirm_selection(self.ids, child, [tag])
        Classifier(self.memory).analyze()
        rows = self.memory.timeline()
        self.assertEqual([(r['start_ms'], r['end_ms']) for r in rows], before)
        self.assertEqual([r['label'] for r in rows], ['First name', 'Second name'])
        self.assertEqual([r['project'] for r in rows], ['P1', 'P2'])
        self.assertTrue(all(r['category'] == '工作 / 编程' and r['tags'][0]['id'] == tag and r['manual'] for r in rows))
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM feedback_tags').fetchone()[0], 2)

    def test_private_delete_and_forget_remove_associations(self):
        root = self.memory.create_category('工作')
        tag = self.memory.create_tag('AI')
        self.memory.confirm_selection(self.ids, root, [tag])
        self.memory.feedback(self.ids[0], action='private')
        self.assertEqual(self.memory.timeline()[0]['tags'], [])
        self.memory.delete_interval(self.ids[1])
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM activity_tags').fetchone()[0], 0)
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM feedback_tags').fetchone()[0], 0)
        self.memory.forget()
        self.assertEqual(self.memory.catalog(), {'categories': [], 'tags': []})
        self.assertEqual(self.memory.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_tag_deletion_undo_retention_and_revision(self):
        root = self.memory.create_category('工作')
        tag = self.memory.create_tag('AI')
        self.memory.confirm_selection(self.ids, root, [tag])
        self.memory.feedback(self.ids[0], action='undo')
        self.assertEqual(self.memory.timeline()[0]['tags'], [])
        self.memory.delete_tag(tag)
        self.assertTrue(all(not r['tags'] for r in self.memory.timeline()))
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM feedback_tags').fetchone()[0], 0)
        tag = self.memory.create_tag('新的')
        self.memory.confirm_selection([self.ids[1]], root, [tag])
        self.memory.repo.cleanup(self.now + 91 * 86_400_000)
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM activity_tags').fetchone()[0], 0)
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM feedback_tags').fetchone()[0], 0)

    def test_deleted_category_cannot_confirm_but_history_remains(self):
        root = self.memory.create_category('工作')
        child = self.memory.create_category('编程', root)
        self.memory.confirm_selection([self.ids[0]], child)
        self.memory.update_category(root, '学习', '#112233')
        self.assertEqual(self.memory.catalog()['categories'][1]['path'], '学习 / 编程')
        self.assertEqual(self.memory.timeline()[0]['category'], '学习 / 编程')
        from daytrace.preferences import options
        colors = options(self.path).get('category_colors', {})
        self.assertEqual(colors.get('学习'), '#112233')
        self.assertEqual(colors.get('学习 / 编程'), '#112233')
        self.memory.delete_category(root)
        with self.assertRaises(ValueError):
            self.memory.confirm_selection([self.ids[1]], child)
        self.assertEqual(self.memory.timeline()[0]['category'], '学习 / 编程')
        self.assertEqual(self.memory.catalog()['categories'], [])

    def test_confirm_applies_same_title_category_and_tags(self):
        with self.memory.repo.transaction():
            for identifier in self.ids:
                self.memory.db.execute('UPDATE activity_intervals SET title=? WHERE id=?', ('DayTrace 开发', identifier))
        root = self.memory.create_category('工作')
        tag = self.memory.create_tag('开发')
        self.memory.confirm_selection([self.ids[0]], root, [tag])
        rows = {row['interval_id']: row for row in self.memory.timeline()}
        first, second = rows[self.ids[0]], rows[self.ids[1]]
        self.assertEqual(first['category'], '工作')
        self.assertTrue(first['manual'])
        self.assertEqual([item['id'] for item in first['tags']], [tag])
        self.assertEqual(second['category'], '工作')
        self.assertFalse(second['manual'])
        self.assertEqual(second['reliability'], 'supported')
        self.assertEqual(second['source'], 'rule')
        self.assertEqual([item['id'] for item in second['tags']], [tag])
        Classifier(self.memory).analyze([self.ids[1]])
        again = {row['interval_id']: row for row in self.memory.timeline()}[self.ids[1]]
        self.assertEqual(again['category'], '工作')
        self.assertEqual(again['source'], 'rule')
        self.assertFalse(again['manual'])
        self.assertEqual([item['id'] for item in again['tags']], [tag])

    def test_different_tags_never_coalesce(self):
        root = self.memory.create_category('工作')
        tag = self.memory.create_tag('AI')
        self.memory.confirm_selection(self.ids, root)
        rows = self.memory.timeline()
        rows[1].update(title=rows[0]['title'], label=rows[0]['label'], app_id=rows[0]['app_id'],
                       process_name=rows[0]['process_name'], task_id=rows[0]['task_id'])
        self.assertEqual(len(cards(rows)), 1)
        rows[1]['tags'] = [{'id': tag, 'name': 'AI'}]
        self.assertEqual(len(cards(rows)), 2)
        self.assertEqual(len(build_display_cards(rows, 0, 180_000, 0)), 2)

    def test_late_invalid_interval_rolls_back_entire_confirmation(self):
        root = self.memory.create_category('工作')
        tag = self.memory.create_tag('AI')
        with self.assertRaises(ValueError):
            self.memory.confirm_selection([self.ids[0], 'deleted'], root, [tag])
        self.assertFalse(self.memory.timeline()[0]['manual'])
        self.assertEqual(self.memory.history(), [])
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM activity_tags').fetchone()[0], 0)

    def test_tags_not_added_to_cloud_payload_and_migration_down(self):
        self.memory.create_tag('LocalOnlyTag')
        payload = Classifier(self.memory).payload([])
        import json
        self.assertNotIn('LocalOnlyTag', json.dumps(payload))
        migrations = Path(__file__).resolve().parents[1] / 'src/daytrace/storage/migrations'
        self.memory.db.executescript((migrations / '007_ai_corrections_down.sql').read_text('utf-8'))
        self.memory.db.executescript((migrations / '006_taxonomy_colors_down.sql').read_text('utf-8'))
        self.memory.db.executescript((migrations / '005_taxonomy_down.sql').read_text('utf-8'))
        self.assertEqual(self.memory.db.execute('PRAGMA user_version').fetchone()[0], 4)
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM activity_intervals WHERE state="active"').fetchone()[0], 2)
        self.assertEqual(self.memory.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_migration_preserves_v3_profile_events_with_live_lock(self):
        legacy = Path(self.folder.name) / 'legacy.sqlite3'
        repo = Repository(legacy)
        with repo.transaction():
            repo.db.execute('INSERT INTO personal_profile VALUES (1,?)', ('{"activities":["Legacy"]}',))
        repo.close()
        with InstanceLock(legacy):
            memory = Memory(legacy, cleanup=False)
            try:
                self.assertEqual(memory.db.execute('PRAGMA user_version').fetchone()[0], 7)
                self.assertEqual(memory.catalog()['categories'][0]['path'], 'Legacy')
                self.assertEqual(memory.db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertFalse(Path(str(legacy) + '.screenshots').exists())
                self.assertEqual(memory.db.execute('SELECT COUNT(*) FROM screenshots').fetchone()[0], 0)
            finally:
                memory.close()


if __name__ == '__main__':
    unittest.main()
