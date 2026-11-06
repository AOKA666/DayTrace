"""Foreground identity, physical geometry and conservative occlusion guards."""
import ctypes as c
from ctypes import wintypes as w

from ..windows import WindowsAPI


def geometry(api,hwnd):
    api._bind(api.u,'GetWindowRect',[w.HWND,c.POINTER(w.RECT)],w.BOOL)
    rect = w.RECT()
    if not api.u.GetWindowRect(hwnd,c.byref(rect)):
        raise OSError('window_unavailable')
    return (rect.left,rect.top,rect.right,rect.bottom)


def context(rules=(),windows=()):
    try:
        return _context(rules,windows)
    except OSError:
        return None


def _context(rules,windows):
    api = WindowsAPI()
    # Per-thread PMv2 avoids mixed-DPI virtualized coordinates, no process-global change.
    api._bind(api.u,'SetThreadDpiAwarenessContext',[c.c_void_p],c.c_void_p)
    api.u.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    api.excluded_windows = windows
    obs = api.snapshot(list(rules))
    if obs.state != 'active':
        return None
    pid = w.DWORD()
    api.u.GetWindowThreadProcessId(obs.window,c.byref(pid))
    return {'hwnd':obs.window,'pid':pid.value,'app':obs.app_id,'process':obs.process_name,
            'title':obs.title,'rect':geometry(api,obs.window)}


def matches(expected,current):
    return current is not None and all(expected[k]==current[k] for k in ('hwnd','pid','app','title','rect'))


def unobscured(hwnd,rect):
    api = WindowsAPI()
    api._bind(api.u,'GetWindow',[w.HWND,w.UINT],w.HWND)
    api._bind(api.u,'IsWindowVisible',[w.HWND],w.BOOL)
    api._bind(api.u,'IsIconic',[w.HWND],w.BOOL)
    api._bind(api.u,'GetWindowLongW',[w.HWND,c.c_int],w.LONG)
    if api.u.GetWindowLongW(hwnd,-20) & (0x80000 | 0x20):
        return False  # Layered/transparent windows could expose another app underneath.
    if api.u.IsIconic(hwnd):
        return False
    # Any visible higher-z rectangle intersecting the target is treated as occlusion.
    above = api.u.GetWindow(hwnd,3)  # GW_HWNDPREV
    count = 0
    while above:
        count += 1
        if count>512:
            return False
        if api.u.IsWindowVisible(above) and not api.u.IsIconic(above):
            r = geometry(api,above)
            if max(r[0],rect[0])<min(r[2],rect[2]) and max(r[1],rect[1])<min(r[3],rect[3]):
                return False
        above = api.u.GetWindow(above,3)
    return api.u.GetForegroundWindow()==hwnd and api.desktop_available()
