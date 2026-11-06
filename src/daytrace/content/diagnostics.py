"""Synthetic diagnostics: never take a screenshot or inspect user windows."""
import json
import time


def collect_diagnostics(ocr=False):
    started=time.monotonic()
    result={'python_target':'3.12+ x64','screenshots_taken':0,'network_allowed':False}
    try:
        import sys
        sys.coinit_flags=0
        from .worker import deny_network
        sys.addaudithook(deny_network)
        from .uia import ComAdapter
        adapter=ComAdapter()
        result['uia_com']='available'
        if ocr:
            from .ocr import create_engine,recognize
            from PIL import Image,ImageDraw,ImageFont
            import numpy as np
            image=Image.new('RGB',(900,160),'white')
            font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',36)
            ImageDraw.Draw(image).text((20,40),'DayTrace 本地文字测试 12345',font=font,fill='black')
            output=recognize(create_engine(),np.array(image))
            result['ocr_status']=output['status']
            result['synthetic_text_match']='DayTrace' in output.get('text','') and '12345' in output.get('text','') and '本地' in output.get('text','')
            if not result['synthetic_text_match']:
                raise RuntimeError('synthetic_ocr_mismatch')
        result['elapsed_ms']=round((time.monotonic()-started)*1000)
        from .worker import resources
        result.update(resources())
        result['status']='success'
        return result
    except Exception as exc:
        result['error_code']=type(exc).__name__
        result['status']='failed'
        return result


def probe_worker(connection,request):
    try:
        connection.send(collect_diagnostics(request['source']=='ocr'))
    finally:
        connection.close()


def diagnose(ocr=False):
    from .coordinator import Worker
    worker=Worker({'source':'ocr' if ocr else 'uia'},target=probe_worker)
    try:
        while True:
            result=worker.poll()
            if result is not None:
                print(json.dumps(result,ensure_ascii=True))
                return 0 if result.get('status')=='success' else 1
            time.sleep(.05)
    finally:
        worker.close()


def structure_worker(connection,request):
    """Read properties only: never Name, Value, TextPattern text or screenshots."""
    import sys
    sys.coinit_flags=0
    from .worker import deny_network
    sys.addaudithook(deny_network)
    from .desktop import context,matches
    try:
        if not matches(request['context'],context()):
            connection.send({'status':'stale'}); return
        from .uia import ComAdapter
        adapter=ComAdapter()
        stack=[(adapter.client.ElementFromHandle(request['context']['hwnd']),0)]
        result={'status':'success','nodes':0,'offscreen':0,'empty_rect':0,'password':0,
            'text_patterns':0,'static_text':0,'depth_limit':0,'max_depth_seen':0,'types':{}}
        deadline=time.monotonic()+1.4
        while stack and result['nodes']<300 and time.monotonic()<deadline:
            node,depth=stack.pop(); result['nodes']+=1
            result['max_depth_seen']=max(depth,result['max_depth_seen'])
            if node.CurrentIsPassword:
                result['password']+=1; continue
            if node.CurrentIsOffscreen:
                result['offscreen']+=1; continue
            r=node.CurrentBoundingRectangle
            if r.right<=r.left or r.bottom<=r.top:
                result['empty_rect']+=1
            kind=node.CurrentControlType
            result['types'][str(kind)]=result['types'].get(str(kind),0)+1
            result['static_text']+=int(kind in (50020,50005))
            result['text_patterns']+=int(bool(node.GetCurrentPropertyValue(30040)))
            children=adapter.children(node,301-result['nodes'])
            if depth>=32 and children:
                result['depth_limit']+=1
            elif children:
                stack.extend((child,depth+1) for child in reversed(children))
        result['budget_exhausted']=bool(stack)
        if request.get('check_text') and matches(request['context'],context()):
            from .uia import extract
            sample=extract(request['context']['hwnd'])
            result['extraction_status']=sample['status']
            result['char_count']=len(sample.get('text',''))
        if not matches(request['context'],context()):
            result={'status':'stale'}
        connection.send(result)
    except Exception as exc:
        connection.send({'status':'unavailable','error_code':type(exc).__name__,
            'hresult':hex(getattr(exc,'hresult',0)&0xffffffff)})
    finally:
        connection.close()


def diagnose_window(delay=5,check_text=False):
    from .desktop import context
    from .coordinator import Worker
    print('Switch to the target window. '+('Checking visible text length; body is discarded.' if check_text else 'Inspecting UIA structure only; no body read.')+' No screenshots or database writes.',flush=True)
    time.sleep(delay)
    current=context()
    if current is None:
        print('{"status":"excluded_or_unavailable"}'); return 1
    worker=Worker({'source':'uia','context':current,'check_text':check_text},target=structure_worker)
    try:
        while True:
            result=worker.poll()
            if result is not None:
                print(json.dumps({'app':current['process'],**result},ensure_ascii=True))
                return 0 if result.get('status')=='success' else 1
            time.sleep(.05)
    finally:
        worker.close()
