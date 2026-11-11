"""One bounded operation per spawned process; no database access or network."""
import os
import sys
import time


def deny_network(event,args):
    if event in ('socket.connect','socket.getaddrinfo','socket.bind'):
        raise PermissionError('Content workers are offline')


def resources():
    import ctypes as c
    from ctypes import wintypes as w
    class COUNTERS(c.Structure):
        _fields_=[('cb',w.DWORD),('faults',w.DWORD)]+[(n,c.c_size_t) for n in
            ('peak_ws','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
    k=c.WinDLL('kernel32'); p=c.WinDLL('psapi')
    k.GetCurrentProcess.restype=w.HANDLE
    p.GetProcessMemoryInfo.argtypes=[w.HANDLE,c.c_void_p,w.DWORD]
    value=COUNTERS(); value.cb=c.sizeof(value)
    if not p.GetProcessMemoryInfo(k.GetCurrentProcess(),c.byref(value),value.cb):
        return {}
    return {'peak_working_set_mb':round(value.peak_ws/1048576,1),'cpu_seconds':round(time.process_time(),3)}


def memory_limit(megabytes,process_handle=None,kill_on_close=False):
    import ctypes as c
    from ctypes import wintypes as w
    class BASIC(c.Structure):
        _fields_=[('process_time',c.c_longlong),('job_time',c.c_longlong),('flags',w.DWORD),
            ('min_ws',c.c_size_t),('max_ws',c.c_size_t),('active',w.DWORD),('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class IO(c.Structure):
        _fields_=[(x,c.c_ulonglong) for x in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class EXTENDED(c.Structure):
        _fields_=[('basic',BASIC),('io',IO),('process_memory',c.c_size_t),('job_memory',c.c_size_t),('peak_process',c.c_size_t),('peak_job',c.c_size_t)]
    k=c.WinDLL('kernel32',use_last_error=True)
    k.CreateJobObjectW.argtypes=[c.c_void_p,w.LPCWSTR]; k.CreateJobObjectW.restype=w.HANDLE
    k.SetInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD]
    k.GetCurrentProcess.restype=w.HANDLE
    k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    handle=k.CreateJobObjectW(None,None)
    info=EXTENDED(); info.basic.flags=0x100 | (0x2000 if kill_on_close else 0); info.process_memory=megabytes*1024*1024
    if not handle or not k.SetInformationJobObject(handle,9,c.byref(info),c.sizeof(info)) or not k.AssignProcessToJobObject(handle,process_handle or k.GetCurrentProcess()):
        if handle:
            close_job(handle)
        raise OSError('resource_limit_unavailable')
    return handle


def close_job(handle):
    import ctypes as c
    from ctypes import wintypes as w
    k=c.WinDLL('kernel32')
    k.CloseHandle.argtypes=[w.HANDLE]
    k.CloseHandle(handle)


def gated_execute(connection,request,gate,target):
    # Parent assigns the kill-on-close Job before authorizing any collection.
    if gate.wait(5):
        target(connection,request)
    else:
        connection.close()


def execute(connection,request):
    started=time.monotonic()
    try:
        # Suppress library/native diagnostics: they must never leak captured text.
        with open(os.devnull,'w') as sink:
            os.dup2(sink.fileno(),1); os.dup2(sink.fileno(),2)
        sys.coinit_flags=0
        sys.addaudithook(deny_network)
        from .desktop import context,matches
        if not matches(request['context'],context(request['exclude'],request['exclude_windows'])):
            result={'source':request['source'],'status':'stale'}
        elif request['source']=='browser':
            from ..browser import extract
            result=extract(request['context']['hwnd'])
        elif request['source']=='uia':
            from .uia import extract
            result=extract(request['context']['hwnd'])
        else:
            from .ocr import capture
            result=capture(request)
        if not matches(request['context'],context(request['exclude'],request['exclude_windows'])):
            result={'source':request['source'],'status':'stale'}
    except ImportError:
        result={'source':request['source'],'status':'dependency_missing'}
    except Exception:
        result={'source':request['source'],'status':'ocr_failed' if request['source']=='ocr' else 'unavailable'}
    result['elapsed_ms']=round((time.monotonic()-started)*1000)
    result['resources']=resources()
    try:
        connection.send(result)
    finally:
        connection.close()
