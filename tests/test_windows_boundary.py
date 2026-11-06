"""Fake Win32 boundaries: no desktop access during automatic tests."""
import ctypes as c
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from daytrace.windows import WindowsAPI


class FakeKernel:
    def __init__(self, path=r"C:\Apps\Editor.exe"):
        self.path = path
        self.closed = 0
        self.denied = False

    def OpenProcess(self, access, inherit, pid):
        assert access == 0x1000 and not inherit
        return None if self.denied else 44

    def QueryFullProcessImageNameW(self, handle, flags, buffer, size):
        buffer.value = self.path
        return True

    def CloseHandle(self, handle):
        self.closed += 1


class FakeUser:
    def __init__(self):
        self.title_reads = 0
        self.current = 12
        self.switch_during_title = False
        self.reuse_pid = False
        self.pid_reads = 0

    def GetForegroundWindow(self):
        return self.current

    def GetWindowThreadProcessId(self, hwnd, pointer):
        self.pid_reads += 1
        pointer._obj.value = 23 if self.reuse_pid and self.pid_reads > 1 else 22
        return 1

    def GetWindowTextW(self, hwnd, buffer, length):
        self.title_reads += 1
        buffer.value = "Synthetic password=hidden"
        if self.switch_during_title:
            self.current = 13
        return len(buffer.value)


class WindowsBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.api = WindowsAPI.__new__(WindowsAPI)
        self.api.u = FakeUser()
        self.api.k = FakeKernel()
        self.api.desktop_available = lambda: True

    def test_excluded_application_never_reads_title(self):
        result = self.api.snapshot(["editor.exe"])
        self.assertEqual(result.state, "excluded")
        self.assertIsNone(result.process_name)
        self.assertEqual(self.api.u.title_reads, 0)
        self.assertEqual(self.api.k.closed, 1)

    def test_permission_denied_is_unknown_without_title(self):
        self.api.k.denied = True
        self.assertEqual(self.api.snapshot([]).state, "unknown")
        self.assertEqual(self.api.u.title_reads, 0)

    def test_secure_desktop_not_read(self):
        self.api.desktop_available = lambda: False
        self.assertEqual(self.api.snapshot([]).state, "locked")
        self.assertEqual(self.api.u.title_reads, 0)

    def test_stale_foreground_event_does_not_read_background_window(self):
        self.assertEqual(self.api.snapshot([], expected_hwnd=99).state, "unknown")
        self.assertEqual(self.api.u.title_reads, 0)

    def test_window_changed_mid_read_discards_title(self):
        self.api.u.switch_during_title = True
        result = self.api.snapshot([])
        self.assertEqual(result.state, "unknown")
        self.assertIsNone(result.title)

    def test_recycled_window_handle_discards_result(self):
        self.api.u.reuse_pid = True
        self.assertEqual(self.api.snapshot([]).state, "unknown")

    def test_idle_checks_exclusion_but_never_reads_title(self):
        self.assertEqual(self.api.snapshot([], read_title=False).state, "active")
        self.assertEqual(self.api.snapshot(["Editor.exe"], read_title=False).state, "excluded")
        self.assertEqual(self.api.u.title_reads, 0)

    def test_result_is_redacted_and_path_is_hashed(self):
        result = self.api.snapshot([])
        self.assertEqual(result.process_name, "Editor.exe")
        self.assertNotIn("hidden", result.title)
        self.assertNotIn("C:", result.app_id)
        self.assertEqual(len(result.app_id), 64)

    def test_default_password_manager_excluded_before_title(self):
        self.api.k.path=r'C:\Apps\Bitwarden.exe'
        self.assertEqual(self.api.snapshot([]).state,'excluded')
        self.assertEqual(self.api.u.title_reads,0)

    def test_window_exclusion_drops_title_and_identity(self):
        self.api.excluded_windows=['Synthetic']
        result=self.api.snapshot([])
        self.assertEqual(result.state,'excluded')
        self.assertIsNone(result.title)
        self.assertIsNone(result.process_name)


if __name__ == "__main__":
    unittest.main()
