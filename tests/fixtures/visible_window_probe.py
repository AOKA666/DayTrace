"""Manual opt-in real Windows probe. Synthetic text only; no screenshots or DB.

Run directly, not discovered by unittest. Briefly displays a test window.
"""
from pathlib import Path
import ctypes as c
from ctypes import wintypes as w
import sys
import time
import json
import tempfile
import subprocess
import sqlite3


def integration(api,hwnd):
    root=Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix='daytrace-content-probe-') as folder:
        database=Path(folder)/'synthetic.sqlite3'
        process=subprocess.Popen([sys.executable,str(root/'daytrace.py'),'--db',str(database),
            'start','--content','--duration','20','--idle-seconds','3000'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+30
        msg=w.MSG()
        try:
            while process.poll() is None and time.monotonic()<deadline:
                while api.u.PeekMessageW(c.byref(msg),None,0,0,1):
                    api.u.TranslateMessage(c.byref(msg));api.u.DispatchMessageW(c.byref(msg))
                time.sleep(.01)
            if process.poll() is None:
                process.kill();process.wait()
                raise RuntimeError('integration_timeout')
            db=sqlite3.connect(database)
            try:
                rows=db.execute('SELECT source,status,text,event_id FROM content_samples').fetchall()
                passed=process.returncode==0 and any(r[1]=='success' and 'DayTrace visible fixture' in (r[2] or '') for r in rows) and all('DO_NOT_CAPTURE' not in (r[2] or '') for r in rows)
                print(json.dumps({'passed':passed,'content_statuses':[r[1] for r in rows],
                    'fixture_events':db.execute("SELECT COUNT(*) FROM activity_events WHERE title='DayTrace synthetic UIA verification'").fetchone()[0],
                    'foreground_still_fixture':api.u.GetForegroundWindow()==hwnd,
                    'events_linked':all(r[3] for r in rows),'foreign_key_errors':len(db.execute('PRAGMA foreign_key_check').fetchall()),
                    'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],
                    'screenshots':sum(r[0]=='ocr' for r in rows),'duration_seconds':20}))
                return 0 if passed else 1
            finally:
                db.close()
        finally:
            if process.poll() is None:
                process.kill();process.wait()

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))


def main():
    from daytrace.windows import WindowsAPI
    from daytrace.content.desktop import context
    from daytrace.content.coordinator import Worker
    api=WindowsAPI(); u=api.u
    api._bind(u,'CreateWindowExW',[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p],w.HWND)
    api._bind(u,'DestroyWindow',[w.HWND],w.BOOL)
    api._bind(u,'SetForegroundWindow',[w.HWND],w.BOOL)
    api._bind(u,'PeekMessageW',[c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT,w.UINT],w.BOOL)
    api._bind(u,'TranslateMessage',[c.POINTER(w.MSG)],w.BOOL)
    api._bind(u,'DispatchMessageW',[c.POINTER(w.MSG)],c.c_ssize_t)
    hwnd=u.CreateWindowExW(0,'STATIC','DayTrace synthetic UIA verification',0x10CF0000,120,120,740,320,None,None,None,None)
    if not hwnd:
        raise RuntimeError('fixture_window_failed')
    worker=None
    try:
        rich=c.WinDLL('Msftedit.dll')
        u.CreateWindowExW(0,'RICHEDIT50W','DayTrace visible fixture 12345',0x50000004,20,40,650,90,hwnd,None,None,None)
        u.CreateWindowExW(0,'EDIT','DO_NOT_CAPTURE_PASSWORD',0x50000020,20,150,300,30,hwnd,None,None,None)
        u.CreateWindowExW(0,'STATIC','DO_NOT_CAPTURE_HIDDEN',0x40000000,20,200,300,30,hwnd,None,None,None)
        u.SetForegroundWindow(hwnd)
        if '--integration' in sys.argv:
            return integration(api,hwnd)
        started=time.monotonic()
        result=None
        msg=w.MSG()
        while time.monotonic()-started<8:
            while u.PeekMessageW(c.byref(msg),None,0,0,1):
                u.TranslateMessage(c.byref(msg));u.DispatchMessageW(c.byref(msg))
            if worker is None and time.monotonic()-started>.5:
                target=context()
                if target is None or target['hwnd']!=hwnd:
                    print(json.dumps({'result':'foreground_not_available','screenshots':0})); return 2
                worker=Worker({'source':'uia','context':target,'exclude':[],'exclude_windows':[],'permit':None})
            if worker:
                result=worker.poll()
                if result is not None:
                    break
            time.sleep(.01)
        text=(result or {}).get('text','')
        passed=bool(result and result['status']=='success' and 'DayTrace visible fixture' in text and 'DO_NOT_CAPTURE' not in text and not result.get('ocr_safe'))
        print(json.dumps({'status':(result or {}).get('status'),'visible_text_matched':'DayTrace visible fixture' in text,
            'password_and_hidden_absent':'DO_NOT_CAPTURE' not in text,'ocr_blocked':not (result or {}).get('ocr_safe'),
            'elapsed_ms':(result or {}).get('elapsed_ms'),'resources':(result or {}).get('resources'),'passed':passed,'screenshots':0}))
        return 0 if passed else 1
    finally:
        if worker:
            worker.close()
        u.DestroyWindow(hwnd)


if __name__=='__main__':
    raise SystemExit(main())
