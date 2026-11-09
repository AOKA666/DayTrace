"""Deterministic synthetic labels, independent of the classifier's own output."""
from pathlib import Path
import tempfile
import time

from ..domain import Observation
from ..engine import Engine
from .store import Memory
from .classifier import Classifier


def evaluate():
    with tempfile.TemporaryDirectory(prefix='daytrace-evaluation-') as folder:
        now = time.time_ns() // 1_000_000
        memory = Memory(Path(folder) / 'synthetic.sqlite3', now=lambda: now + 500_000)
        try:
            engine = Engine(memory.repo, now, 0, simulated=True)
            samples = []
            # 20 training exemplars; 100 held-out repeats/negative cases.
            for i in range(20):
                samples.append(('Code.exe', f'Project{i} Python Windows API tutorial module{i}', f'研究 Project{i} API'))
            for i in range(100):
                project = i % 20
                if i % 5 == 0:
                    samples.append(('chrome.exe', f'Project{project} music entertainment concert unrelated', None))
                else:
                    samples.append(('chrome.exe', f'Project{project} Python Windows API tutorial module{project}', f'研究 Project{project} API'))
            for i, (app, title, _) in enumerate(samples):
                engine.sample(i * 2000, now + i * 2000, Observation('active', app, app, title, i + 1))
            engine.stop(len(samples) * 2000, now + len(samples) * 2000)
            classifier = Classifier(memory)
            ids = memory.intervals()
            classifier.analyze()
            baseline = sum(r['label'] == expected for r, (_, _, expected) in zip(memory.timeline()[20:], samples[20:]) if expected) / 80
            for i in range(20):
                classifier.analyze([ids[i]])
                memory.feedback(ids[i], samples[i][2], '学习', f'Project{i}', remember=True)
            started = time.perf_counter()
            classifier.analyze()
            elapsed = time.perf_counter() - started
            results = memory.timeline()[20:]
            labelled = [(r, s[2]) for r, s in zip(results, samples[20:])]
            correct = sum(r['label'] == expected for r, expected in labelled)
            similar_correct = sum(r['label'] == expected for r, expected in labelled if expected)
            wrong_generalization = sum(r['label'] is not None for r, expected in labelled if expected is None)
            named = [(r, expected) for r, expected in labelled if r['label']]
            return {
                'dataset': 'synthetic, 20 exemplars + 100 held-out repeats/negative cases; not real-world accuracy',
                'test_count': 100, 'classification_accuracy_including_unknown': correct / 100,
                'named_accuracy': sum(r['label'] == expected for r, expected in named) / max(1, len(named)),
                'named_coverage': len(named) / 100,
                'review_ratio': sum(r['reliability'] != 'supported' for r in results) / 100,
                'similar_accuracy_before_feedback': baseline,
                'similar_accuracy_after_feedback': similar_correct / 80,
                'wrong_generalization_count': wrong_generalization,
                'analysis_seconds': round(elapsed, 3),
                'screenshots': 0, 'cloud_requests': 0,
            }
        finally:
            memory.close()
