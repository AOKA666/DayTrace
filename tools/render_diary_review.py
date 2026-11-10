"""Render the real Qt window against a temporary, explicitly synthetic SQLite DB.

No desktop collection, screenshots of other apps, network calls or user DB reads.
Run separately with QT_SCALE_FACTOR=1/1.5/2 to validate logical-pixel layouts.
"""
import argparse
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from daytrace.domain import Observation
from daytrace.engine import Engine
from daytrace.personalization.store import Memory
from daytrace.personalization.classifier import Classifier


def seed(path):
    memory = Memory(path)
    root = memory.create_category('事业', color='#7566D9')
    memory.create_category('AI 编程', root)
    memory.create_category('工作', color='#5B8FCB')
    start = int(datetime.now().replace(hour=9, minute=51, second=0, microsecond=0).timestamp() * 1000)
    titles = ['README.md - DayTrace - Visual Studio Code', 'AGENTS.md - DayTrace - Visual Studio Code',
              '项目文档 - Google Chrome', 'DayTrace 界面开发', 'AI Room Design - Google Chrome']
    engine = Engine(memory.repo, start, 0, simulated=True)
    for offset in range(0, 300_000, 5000):
        index = offset // 60000
        process = 'Code.exe' if index < 2 else 'chrome.exe'
        engine.sample(offset, start + offset, Observation('active', process, process, titles[index], index + 1))
    engine.stop(300_000, start + 300_000)
    Classifier(memory).analyze()
    for index, identifier in enumerate(memory.intervals()[:4]):
        memory.feedback(identifier, titles[index], '工作' if index == 2 else '事业 / AI 编程')
    memory.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('artifacts/ui-review'))
    parser.add_argument('--size', default='1440x900')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from daytrace.personalization.diary_qt.window import run_app
    from PySide6.QtWidgets import QApplication
    with tempfile.TemporaryDirectory(prefix='daytrace-design-') as folder:
        path = Path(folder) / 'synthetic.sqlite3'
        seed(path)
        app, window = run_app(path, preview_mode=True)
        window.setWindowTitle('DayTrace · UI 验收 · 合成数据')
        window.resize(*(int(value) for value in args.size.split('x')))
        deadline = time.monotonic() + 10
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        for name, page in [('timeline', '时间线'), ('my', '我的'), ('settings', '设置')]:
            window.navigate(page, refresh=False)
            app.processEvents()
            app.processEvents()
            window.grab().save(str(args.output / f'{name}.png'))
        window.close()
        app.processEvents()
        print('Rendered synthetic SQLite-backed Qt pages:', args.output.resolve())


if __name__ == '__main__':
    main()
