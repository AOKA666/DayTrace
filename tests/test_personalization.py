import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from daytrace.personalization.profile import propose_profile
from daytrace.personalization.store import Memory
from daytrace.storage.repository import Repository
from daytrace.engine import Engine
from daytrace.domain import Observation
from daytrace.personalization.classifier import Classifier
import threading

NOW = 1_798_761_600_000


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.memory = Memory(self.path, now=lambda: NOW + 100_000)
        engine = Engine(self.memory.repo, NOW, 0, simulated=True)
        titles = [('chrome.exe', 'Python Windows API tutorial DayTrace'),
                  ('chrome.exe', 'Comedy movie entertainment unrelated'),
                  ('Code.exe', 'Python Windows API tutorial DayTrace'),
                  ('chrome.exe', 'Python Windows API tutorial OtherProject')]
        for index, (app, title) in enumerate(titles):
            engine.sample(index * 2000, NOW + index * 2000, Observation('active', app, app, title, index + 1))
        engine.stop(8000, NOW + 8000)
        self.ids = self.memory.intervals()
        self.classifier = Classifier(self.memory)

    def tearDown(self):
        self.memory.close()
        self.temp.cleanup()

    def test_user_categories_limit_ai_candidates_and_forget_colors(self):
        self.memory.add_category('学习', '#7566D9')
        self.memory.add_category('生活', '#3C9B92')
        with self.memory.repo.transaction():
            self.memory.task('无关任务', '其他', '')
        payload = Classifier(self.memory, category_only=True).payload([])
        self.assertEqual({t['label'] for t in payload['candidates']}, {'学习', '生活'})
        self.assertEqual(self.memory.export()['category_colors']['学习'], '#7566D9')
        self.memory.forget()
        self.assertEqual(self.memory.export()['category_colors'], {})

    def test_feedback_reuse_cross_app_without_unrelated_generalization(self):
        self.classifier.analyze()
        self.assertTrue(all(r['reliability'] == 'unknown' for r in self.memory.timeline()))
        self.memory.feedback(self.ids[0], '学习 Windows API', '学习', 'DayTrace', remember=True)
        self.classifier.analyze()
        rows = self.memory.timeline()
        self.assertEqual(rows[0]['source'], 'human')
        self.assertEqual(rows[2]['source'], 'history')
        self.assertEqual(rows[2]['label'], '学习 Windows API')
        self.assertIsNone(rows[1]['label'])
        self.assertIsNone(rows[3]['label'])
        self.assertEqual(sum(r['end_ms'] - r['start_ms'] for r in rows), 8000)
        self.memory.close()
        self.memory = Memory(self.path, now=lambda: NOW + 100_000)
        Classifier(self.memory).analyze()
        self.assertEqual(self.memory.timeline()[0]['source'], 'human')

    def test_confirmation_preserves_unrelated_rules_and_ai_results(self):
        category = self.memory.create_category('学习')
        with self.memory.repo.transaction():
            task = self.memory.task('娱乐', '生活', '')
        self.memory.save_rule(task, {'title_exact': 'Comedy movie entertainment unrelated'}, True)
        self.classifier.analyze()
        with self.memory.repo.transaction():
            self.memory.db.execute("UPDATE task_results SET source='ai',task_id=? WHERE interval_id=?", (task, self.ids[3]))
        def results():
            return {r['interval_id']: dict(r) for r in self.memory.db.execute('SELECT * FROM task_results')}
        before = results()
        generation = self.memory.generation()
        self.memory.confirm_selection([self.ids[0]], category)
        after = results()
        for index in (1, 3):
            self.assertEqual(after[self.ids[index]], before[self.ids[index]])
        self.assertEqual(after[self.ids[0]]['manual'], 1)
        self.assertEqual(after[self.ids[2]]['source'], 'rule')
        self.assertGreater(self.memory.generation(), generation)
        self.memory.create_category('新增分类')
        self.assertEqual(results(), after)

    def test_removed_confirmation_rule_only_requeues_dependents(self):
        category = self.memory.create_category('学习')
        self.classifier.analyze()
        self.memory.confirm_selection([self.ids[0]], category)
        prior = dict(self.memory.db.execute('SELECT * FROM task_results WHERE interval_id=?', (self.ids[1],)).fetchone())
        self.memory.feedback(self.ids[0], action='undo')
        dependent = self.memory.db.execute('SELECT * FROM task_results WHERE interval_id=?', (self.ids[2],)).fetchone()
        self.assertEqual(dependent['source'], 'pending')
        self.assertIsNotNone(dependent['task_id'])
        self.assertEqual(dict(self.memory.db.execute('SELECT * FROM task_results WHERE interval_id=?', (self.ids[1],)).fetchone()), prior)
        self.classifier.analyze([self.ids[2]])
        self.assertIsNone(self.memory.db.execute('SELECT task_id FROM task_results WHERE interval_id=?', (self.ids[2],)).fetchone()[0])

    def test_rules_conflicts_disable_delete_and_negative_scope(self):
        with self.memory.repo.transaction():
            task = self.memory.task('学习 API', '学习', 'DayTrace')
            other = self.memory.task('其他任务')
        with self.assertRaises(ValueError):
            self.memory.save_rule(task, {'app': 'chrome.exe'}, True)
        first = self.memory.save_rule(task, {'keywords': ['Python', 'DayTrace'], 'exclude': ['entertainment']}, True)
        self.classifier.analyze()
        self.assertEqual(self.memory.timeline()[0]['reliability'], 'supported')
        self.assertIsNone(self.memory.timeline()[1]['label'])
        second = self.memory.save_rule(other, {'title': 'Python', 'project': 'DayTrace'}, True)
        self.classifier.analyze()
        self.assertEqual(self.memory.timeline()[0]['source'], 'conflict')
        self.memory.change_rule(second, False)
        self.classifier.analyze()
        self.assertEqual(self.memory.timeline()[0]['label'], '学习 API')
        self.memory.change_rule(first)
        self.classifier.analyze()
        self.assertIsNone(self.memory.timeline()[0]['label'])

    def test_private_forget_and_delete_restart(self):
        self.classifier.analyze()
        self.memory.feedback(self.ids[0], '学习 API', remember=True)
        self.memory.feedback(self.ids[0], action='private')
        self.classifier.analyze()
        self.assertIsNone(self.memory.evidence(self.ids[0]))
        self.assertEqual(self.memory.timeline()[0]['state'], 'excluded')
        self.assertEqual(self.memory.history(), [])
        self.memory.delete_interval(self.ids[1])
        self.memory.close()
        self.memory = Memory(self.path, now=lambda: NOW + 100_000)
        self.assertNotIn(self.ids[1], [r['interval_id'] for r in self.memory.timeline()])
        self.memory.forget()
        self.assertEqual(self.memory.tasks(), [])

    def test_expired_evidence_does_not_train(self):
        self.classifier.analyze()
        self.memory.feedback(self.ids[0], '学习 API', remember=True)
        self.memory.now = lambda: NOW + 8 * 86_400_000
        self.memory.repo.cleanup(self.memory.now())
        self.classifier.analyze()
        self.assertIsNone(self.memory.timeline()[2]['label'])

    def test_ai_failure_invalid_ids_and_default_zero_send(self):
        class Fake:
            cancelled = threading.Event()
            calls = 0
            def classify(self, payload):
                self.calls += 1
                raise OSError('sensitive text must not be logged')
        provider = Fake()
        classifier = Classifier(self.memory, provider)
        classifier.analyze()
        self.assertEqual(provider.calls, 0)
        classifier.analyze(approved_payload=classifier.preview())
        self.assertEqual(provider.calls, 1)
        self.assertTrue(all(r['reliability'] == 'unknown' for r in self.memory.timeline()))
        with self.assertRaises(ValueError):
            classifier.validate([{'interval_id': self.ids[0], 'task_id': 'made-up', 'evidence_ids': ['fake']}], classifier.preview())

    def test_stale_ai_result_rejected_after_feedback(self):
        memory = self.memory
        with memory.repo.transaction():
            task = memory.task('阅读资料')
        self.classifier.analyze()
        class Fake:
            cancelled = threading.Event()
            def classify(self, payload):
                memory.feedback(payload['evidence'][0]['interval_id'], '人工指定')
                e = payload['evidence'][0]
                return [{'interval_id': e['interval_id'], 'task_id': task, 'evidence_ids': e['evidence_ids']}]
        classifier = Classifier(memory, Fake())
        self.assertEqual(classifier.analyze(approved_payload=classifier.preview()), 0)
        self.assertEqual(memory.timeline()[0]['label'], '人工指定')

    def test_undo_preserves_revision_chain_and_reanalysis(self):
        self.classifier.analyze()
        self.memory.feedback(self.ids[0], 'First', remember=True)
        self.memory.feedback(self.ids[0], 'Second', remember=True)
        self.memory.feedback(self.ids[0], action='undo')
        self.classifier.analyze()
        history = self.memory.history()
        self.assertEqual(len(history), 3)
        self.assertEqual(sum(r['previous_id'] is not None for r in history), 2)
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM activity_cases').fetchone()[0], 0)

    def test_suggested_rules_require_approval_and_follow_source_deletion(self):
        self.classifier.analyze()
        self.memory.feedback(self.ids[0], '学习 API', remember=True)
        self.memory.feedback(self.ids[2], '学习 API', remember=True)
        suggestion = self.memory.suggestions()[0]
        rule = self.memory.save_rule(suggestion['task_id'], suggestion['conditions'], origins=suggestion['origins'])
        self.assertFalse(self.memory.rules()[0]['approved'])
        self.memory.feedback(self.ids[0], action='private')
        self.assertEqual(self.memory.rules(), [])
        self.assertEqual(self.memory.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_body_adapter_latest_exclusion_and_unanalyzed_delete(self):
        event = self.memory.evidence(self.ids[0])['event_id']
        session = self.memory.evidence(self.ids[0])['session_id']
        with self.memory.repo.transaction():
            self.memory.db.execute('''INSERT INTO content_samples(id,event_id,session_id,captured_ms,source,status,text,policy_version,expires_ms)
                VALUES ('body',?,?,?,'uia','success','Synthetic visible body',1,?)''', (event, session, NOW+500, NOW+86_400_000))
        self.assertEqual(self.memory.evidence(self.ids[0])['text'], 'Synthetic visible body')
        with self.memory.repo.transaction():
            self.memory.db.execute('''INSERT INTO content_samples(id,event_id,session_id,captured_ms,source,status,policy_version,expires_ms)
                VALUES ('excluded',?,?,?,'policy','excluded',1,?)''', (event, session, NOW+1000, NOW+86_400_000))
        self.assertEqual(self.memory.evidence(self.ids[0])['text'], '')
        self.memory.delete_interval(self.ids[0])
        self.assertEqual(self.memory.db.execute('SELECT COUNT(*) FROM content_samples').fetchone()[0], 0)
        self.assertIsNone(self.memory.db.execute('SELECT id FROM activity_events WHERE id=?', (event,)).fetchone())

    def test_forget_rejects_inflight_result_even_with_same_empty_configuration(self):
        memory = self.memory
        class Fake:
            cancelled = threading.Event()
            def classify(self, payload):
                memory.forget()
                return []
        classifier = Classifier(memory, Fake())
        self.assertEqual(classifier.analyze(approved_payload=classifier.preview()), 0)
        self.assertEqual(memory.db.execute('SELECT COUNT(*) FROM task_results').fetchone()[0], 0)


class ProfileTests(unittest.TestCase):
    def test_profile_confirmation_edit_redaction_and_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.sqlite3'
            old = Repository(path)
            self.assertEqual(old.db.execute('PRAGMA user_version').fetchone()[0], 3)
            old.close()
            memory = Memory(path)
            proposal = propose_profile('我用 VS Code 开发，Chrome 查竞品，password=secretvalue')
            self.assertEqual(memory.profile()['activities'], [])
            self.assertIn('编程开发', proposal['activities'])
            self.assertNotIn('secretvalue', json.dumps(proposal))
            proposal['projects'] = ['DayTrace']
            memory.save_profile(proposal)
            memory.close()
            memory = Memory(path)
            self.assertEqual(memory.profile()['projects'], ['DayTrace'])
            memory.save_profile({'projects': ['Other']})
            self.assertEqual(memory.profile()['projects'], ['Other'])
            self.assertEqual(memory.db.execute('PRAGMA foreign_key_check').fetchall(), [])
            migration = Path(__file__).resolve().parents[1] / 'src/daytrace/storage/migrations/003_personalization_down.sql'
            memory.db.executescript((migration.parent / '007_ai_corrections_down.sql').read_text('utf-8'))
            memory.db.executescript((migration.parent / '006_taxonomy_colors_down.sql').read_text('utf-8'))
            memory.db.executescript((migration.parent / '005_taxonomy_down.sql').read_text('utf-8'))
            memory.db.executescript((migration.parent / '004_screenshots_down.sql').read_text('utf-8'))
            memory.db.executescript(migration.read_text('utf-8'))
            self.assertEqual(memory.db.execute('PRAGMA user_version').fetchone()[0], 2)
            memory.close()


if __name__ == '__main__':
    unittest.main()
