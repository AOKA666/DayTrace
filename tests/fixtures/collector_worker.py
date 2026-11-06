"""Subprocess test harness only: replace native source with synthetic data."""
from pathlib import Path
import queue
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from daytrace.domain import Observation
from daytrace.service import run
import daytrace.windows


class Source:
    def __init__(self):
        import threading
        self.api = SimpleNamespace(desktop_available=lambda: True, idle_for_ms=lambda: 0,
                                   u=SimpleNamespace(GetForegroundWindow=lambda: 1))
        self.events = queue.Queue()
        self.overflow = threading.Event()
        self.thread = SimpleNamespace(is_alive=lambda: True)
        self.error = None
        self.locked = self.suspended = False

    def start(self):
        return self

    def snapshot(self, rules, expected_hwnd=None, read_title=True):
        return Observation("active", "Synthetic.exe", "synthetic", "password=fixturesecret", 1)

    def close(self):
        pass


if __name__ == "__main__":
    daytrace.windows.WindowsSource = Source
    run(Path(sys.argv[1]), duration=30)
