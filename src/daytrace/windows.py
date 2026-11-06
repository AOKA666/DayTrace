"""Read-only Win32 adapter. No UIA, screenshots, input hooks or clipboard APIs."""
import ctypes as c
from ctypes import wintypes as w
import ntpath
import os
import queue
import threading
import time

from .domain import Observation
from .privacy import app_identity, excluded, redact_title
from .content.policy import SENSITIVE_APPS, sensitive_window


class WindowsAPI:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Live collection requires Windows.")
        self.u = c.WinDLL("user32", use_last_error=True)
        self.k = c.WinDLL("kernel32", use_last_error=True)
        self.wts = c.WinDLL("wtsapi32", use_last_error=True)
        self._bind(self.u, "GetForegroundWindow", [], w.HWND)
        self._bind(self.u, "GetWindowThreadProcessId", [w.HWND, c.POINTER(w.DWORD)], w.DWORD)
        self._bind(self.u, "GetWindowTextW", [w.HWND, w.LPWSTR, c.c_int], c.c_int)
        self._bind(self.k, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
        self._bind(self.k, "CloseHandle", [w.HANDLE], w.BOOL)
        self._bind(self.k, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL)
        self._bind(self.k, "GetTickCount64", [], c.c_ulonglong)
        self._bind(self.u, "OpenInputDesktop", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
        self._bind(self.u, "CloseDesktop", [w.HANDLE], w.BOOL)
        self._bind(self.u, "GetUserObjectInformationW", [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL)
        class LASTINPUTINFO(c.Structure):
            _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]
        self.input_type = LASTINPUTINFO
        self._bind(self.u, "GetLastInputInfo", [c.POINTER(LASTINPUTINFO)], w.BOOL)

    @staticmethod
    def _bind(dll, name, args, result):
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = args, result
        return fn

    def desktop_available(self):
        desktop = self.u.OpenInputDesktop(0, False, 1)  # DESKTOP_READOBJECTS only.
        if not desktop:
            return False
        try:
            name, needed = c.create_unicode_buffer(256), w.DWORD()
            return bool(self.u.GetUserObjectInformationW(desktop, 2, name, c.sizeof(name), c.byref(needed))) and name.value.casefold() == "default"
        finally:
            self.u.CloseDesktop(desktop)

    def idle_for_ms(self):
        value = self.input_type(c.sizeof(self.input_type), 0)
        if not self.u.GetLastInputInfo(c.byref(value)):
            raise OSError("GetLastInputInfo failed")
        delta = (self.k.GetTickCount64() - value.dwTime) & 0xFFFFFFFF
        # Some synthetic input timestamps are in the future; do not report 49 days idle.
        return 0 if delta > 0x7FFFFFFF else delta

    def snapshot(self, rules, expected_hwnd=None, read_title=True):
        if not self.desktop_available():
            return Observation("locked")
        hwnd = self.u.GetForegroundWindow()
        if not hwnd or (expected_hwnd and hwnd != expected_hwnd):
            return Observation("unknown")
        pid = w.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, c.byref(pid))
        if not pid.value:
            return Observation("unknown")
        handle = self.k.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION.
        if not handle:
            return Observation("unknown")
        try:
            path, length = c.create_unicode_buffer(32768), w.DWORD(32768)
            if not self.k.QueryFullProcessImageNameW(handle, 0, path, c.byref(length)):
                return Observation("unknown")
            executable = path.value
        finally:
            self.k.CloseHandle(handle)
        # This check MUST precede GetWindowTextW.
        if excluded(executable, [*SENSITIVE_APPS, *rules]):
            return Observation("excluded")
        if self.u.GetForegroundWindow() != hwnd:
            return Observation("unknown")
        title = c.create_unicode_buffer(2049)
        if read_title:
            self.u.GetWindowTextW(hwnd, title, len(title))
            if sensitive_window(title.value, getattr(self, 'excluded_windows', ())):
                return Observation("excluded")
        after_pid = w.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, c.byref(after_pid))
        if self.u.GetForegroundWindow() != hwnd or after_pid.value != pid.value or not self.desktop_available():
            return Observation("unknown")
        return Observation("active", ntpath.basename(executable), app_identity(executable), redact_title(title.value), hwnd)


class WindowsSource:
    """Dedicated WinEvent/message thread. Callbacks only enqueue metadata."""
    def __init__(self):
        self.api = WindowsAPI()
        self.events = queue.Queue(maxsize=2048)
        self.overflow = threading.Event()
        self.ready = threading.Event()
        self.closing = threading.Event()
        self.error = None
        self.locked = False
        self.suspended = False
        self.hwnd = None
        self.thread_id = 0
        self.hook_active = False
        self.content_events = False
        self.geometry_events = False
        self.last_content_hint = 0.0
        self.thread = threading.Thread(target=self._run, name="daytrace-winevent", daemon=True)

    def enqueue(self, kind, hwnd=0):
        try:
            self.events.put_nowait((kind, hwnd, time.monotonic_ns() // 1_000_000))
        except queue.Full:
            self.overflow.set()

    def start(self):
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            self.close()
            raise RuntimeError(self.error or "Windows event thread did not start.")
        return self

    def _run(self):
        u, k, wts = self.api.u, self.api.k, self.api.wts
        bind = self.api._bind
        wndproc_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        event_type = c.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND, w.LONG, w.LONG, w.DWORD, w.DWORD)
        class WNDCLASS(c.Structure):
            _fields_ = [("style", w.UINT), ("lpfnWndProc", wndproc_type), ("cbClsExtra", c.c_int), ("cbWndExtra", c.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]
        bind(u, "DefWindowProcW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], c.c_ssize_t)
        bind(u, "RegisterClassW", [c.POINTER(WNDCLASS)], w.ATOM)
        bind(u, "UnregisterClassW", [w.LPCWSTR, w.HINSTANCE], w.BOOL)
        bind(u, "CreateWindowExW", [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p], w.HWND)
        bind(u, "DestroyWindow", [w.HWND], w.BOOL)
        bind(u, "GetMessageW", [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT], c.c_int)
        bind(u, "TranslateMessage", [c.POINTER(w.MSG)], w.BOOL)
        bind(u, "DispatchMessageW", [c.POINTER(w.MSG)], c.c_ssize_t)
        bind(u, "PostThreadMessageW", [w.DWORD, w.UINT, w.WPARAM, w.LPARAM], w.BOOL)
        bind(k, "GetCurrentThreadId", [], w.DWORD)
        bind(k, "GetModuleHandleW", [w.LPCWSTR], w.HMODULE)
        bind(u, "SetWinEventHook", [w.DWORD, w.DWORD, w.HMODULE, event_type, w.DWORD, w.DWORD, w.DWORD], w.HANDLE)
        bind(u, "UnhookWinEvent", [w.HANDLE], w.BOOL)
        bind(u, "GetAncestor", [w.HWND,w.UINT], w.HWND)
        bind(wts, "WTSRegisterSessionNotification", [w.HWND, w.DWORD], w.BOOL)
        bind(wts, "WTSUnRegisterSessionNotification", [w.HWND], w.BOOL)

        @wndproc_type
        def wndproc(hwnd, message, wp, lp):
            if message == 0x02B1:  # WM_WTSSESSION_CHANGE, this session only.
                if wp in (2, 4, 7):  # console/remote disconnect or lock
                    self.locked = True
                    self.enqueue("locked")
                elif wp in (1, 3, 8):
                    self.locked = False
                    self.enqueue("unlocked")
            elif message == 0x0218:  # WM_POWERBROADCAST
                if wp == 4:
                    self.suspended = True
                    self.enqueue("suspended")
                elif wp in (7, 18):
                    self.suspended = False
                    self.enqueue("resumed")
            return u.DefWindowProcW(hwnd, message, wp, lp)

        @event_type
        def callback(hook, event, hwnd, obj, child, thread, timestamp):
            if event == 3 and hwnd:
                self.enqueue("foreground", hwnd)
            elif event==0x800B and self.geometry_events and hwnd==u.GetForegroundWindow() and obj==0 and child==0:
                self.enqueue('geometry',hwnd)
            elif event == 0x800C and obj == 0 and child == 0 and hwnd == u.GetForegroundWindow():
                self.enqueue("title", hwnd)
            elif self.content_events and event in (0x800C,0x800E) and hwnd and u.GetAncestor(hwnd,2)==u.GetForegroundWindow():
                now=time.monotonic()
                if now-self.last_content_hint>=2:
                    self.last_content_hint=now
                    self.enqueue('content',u.GetForegroundWindow())

        hooks, registered = [], False
        instance = k.GetModuleHandleW(None)
        classname = "DayTraceEvents_" + str(os.getpid())
        cls = WNDCLASS(0, wndproc, 0, 0, instance, None, None, None, None, classname)
        atom = 0
        try:
            self.thread_id = k.GetCurrentThreadId()
            atom = u.RegisterClassW(c.byref(cls))
            if not atom:
                raise OSError("RegisterClassW failed")
            # Invisible top-level message sink (not a user interface). Receives power broadcasts.
            self.hwnd = u.CreateWindowExW(0, classname, "DayTrace event receiver", 0, 0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW failed")
            registered = bool(wts.WTSRegisterSessionNotification(self.hwnd, 0))
            if not registered:
                raise OSError("Session notifications unavailable")
            event_ids=[3,0x800C]
            if self.content_events:
                event_ids.append(0x800E)
            if self.geometry_events:
                event_ids.append(0x800B)
            for event in event_ids:
                handle = u.SetWinEventHook(event, event, None, callback, 0, 0, 0)  # OUTOFCONTEXT, no injection.
                if not handle:
                    raise OSError("SetWinEventHook failed")
                hooks.append(handle)
            self.hook_active = True
            self.ready.set()
            msg = w.MSG()
            while not self.closing.is_set():
                result = u.GetMessageW(c.byref(msg), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise OSError("GetMessageW failed")
                u.TranslateMessage(c.byref(msg))
                u.DispatchMessageW(c.byref(msg))
        except Exception as exc:
            self.error = type(exc).__name__ + ": Windows event source unavailable"
        finally:
            self.hook_active = False
            for hook in hooks:
                u.UnhookWinEvent(hook)
            if registered:
                wts.WTSUnRegisterSessionNotification(self.hwnd)
            if self.hwnd:
                u.DestroyWindow(self.hwnd)
            if atom:
                u.UnregisterClassW(classname, instance)
            self.ready.set()

    def close(self):
        self.closing.set()
        if self.thread_id:
            self.api.u.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
        if self.thread.is_alive():
            self.thread.join(3)

    def snapshot(self, rules, expected_hwnd=None, read_title=True):
        if self.suspended:
            return Observation("suspended")
        if self.locked:
            return Observation("locked")
        return self.api.snapshot(rules, expected_hwnd, read_title)
