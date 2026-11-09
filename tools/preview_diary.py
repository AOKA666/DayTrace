"""Run a desktop preview with isolated synthetic data; never collects."""
from pathlib import Path
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from daytrace.personalization.store import Memory
from daytrace.personalization.classifier import Classifier
from daytrace.engine import Engine
from daytrace.domain import Observation


def seed_database(path: Path) -> None:
    memory = Memory(path)
    day = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    start = int(day.timestamp() * 1000)
    engine = Engine(memory.repo, start, 0, simulated=True)
    entries = [
        (0, 'Code.exe', 'DayTrace Windows collector'),
        (35, 'chrome.exe', 'DayTrace Windows API reference'),
        (85, 'chrome.exe', 'Micro SaaS research'),
        (130, 'chat.exe', 'Team design review'),
        (155, 'chrome.exe', 'Unclear foreground page'),
        (172, 'Code.exe', 'Diary UI components'),
    ]
    for offset in range(0, 215 * 60000, 5000):
        minute, app, title = next(entry for entry in reversed(entries) if entry[0] * 60000 <= offset)
        engine.sample(offset, start + offset, Observation('active', app, app, title, minute + 1))
    engine.stop(215 * 60000, start + 215 * 60000)
    Classifier(memory).analyze()
    labels = [
        ('开发 Windows 活动采集功能', '工作', 'DayTrace', '围绕前台窗口变化和内容证据，调整采集流程。'),
        ('开发 Windows 活动采集功能', '工作', 'DayTrace', '查阅 Windows API 文档，核对事件处理方式。'),
        ('研究 Micro-SaaS 产品机会', '工作', '独立开发', '阅读产品资料，整理需求与竞品信息。'),
        ('讨论时间日记的交互设计', '沟通', 'DayTrace', '围绕活动卡片和确认流程交换设计意见。'),
        None,
        ('调整时间线卡片的布局', '工作', 'DayTrace', '编辑卡片组件，核对日期导航和阅读层次。'),
    ]
    for identifier, value in zip(memory.intervals(), labels):
        if value:
            memory.feedback(identifier, *value[:3], remember=False)
            with memory.repo.transaction():
                memory.db.execute(
                    "UPDATE task_results SET source='ai',manual=0,reliability='tentative',reason=? WHERE interval_id=?",
                    (value[3], identifier),
                )
    for identifier, value in zip(memory.intervals(), labels):
        if value:
            with memory.repo.transaction():
                task = memory.task(*value[:3])
                memory.db.execute(
                    "UPDATE task_results SET task_id=?,source='ai',manual=0,reliability='tentative',reason=? WHERE interval_id=?",
                    (task, value[3], identifier),
                )
    memory.close()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=0, help='Close automatically for a GUI smoke check')
    parser.add_argument('--size', default='1280x800', help='Window size WIDTHxHEIGHT (Qt only)')
    parser.add_argument('--tk-diary', action='store_true', help='Use Tk diary shell instead of default Qt')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='daytrace-preview-') as folder:
        path = Path(folder) / 'synthetic.sqlite3'
        seed_database(path)
        if args.tk_diary:
            import tkinter as tk
            from daytrace.personalization.diary_ui import DiaryApp

            root = tk.Tk()
            app = DiaryApp(root, path)
            app.preview_mode = True
            root.title('DayTrace · 界面验收 · 合成示例数据')
            root.geometry(args.size)
            app.heading.set('今天的故事 · 示例')
            app.capture_button.configure(state='disabled')
            if args.seconds:
                root.after(args.seconds * 1000, app.close)
            root.mainloop()
            return
        from daytrace.personalization.diary_qt import preview

        def ready(app, window):
            window.setWindowTitle('DayTrace · 界面验收 · 合成示例数据')
            try:
                w, h = args.size.lower().split('x')
                window.resize(int(w), int(h))
            except ValueError:
                window.resize(1280, 800)
            window.heading.setText('今天 · 示例')
            if args.seconds:
                from PySide6.QtCore import QTimer

                QTimer.singleShot(args.seconds * 1000, app.quit)

        app, window = preview(path, on_ready=ready)
        sys.exit(app.exec())


if __name__ == '__main__':
    main()
