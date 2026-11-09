"""Optional CPU OCR, with explicit local models and memory-only images."""
from pathlib import Path
import os
import sys
import hashlib

_dll_directory = None
MODEL_HASHES = {
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx':'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
    'PP-OCRv6_det_small.onnx':'090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    'PP-OCRv6_rec_small.onnx':'6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
}


def create_engine():
    global _dll_directory
    if os.name == 'nt' and _dll_directory is None:
        _dll_directory = os.add_dll_directory(sys.prefix)
    import rapidocr
    import cv2
    cv2.setNumThreads(1)
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from rapidocr import RapidOCR
    root = Path(rapidocr.__file__).parent / 'models'
    models = {'Det.model_path':root/'PP-OCRv6_det_small.onnx',
              'Cls.model_path':root/'ch_ppocr_mobile_v2.0_cls_mobile.onnx',
              'Rec.model_path':root/'PP-OCRv6_rec_small.onnx'}
    if not all(p.is_file() for p in models.values()):
        raise FileNotFoundError('local_models_missing')
    for path in models.values():
        with path.open('rb') as model:
            if hashlib.file_digest(model,'sha256').hexdigest()!=MODEL_HASHES[path.name]:
                raise ValueError('local_model_hash_mismatch')
    return RapidOCR(params={**{k:str(v) for k,v in models.items()},
        'EngineConfig.onnxruntime.intra_op_num_threads':2,
        'EngineConfig.onnxruntime.inter_op_num_threads':1,
        'Det.limit_type':'max',
        'Det.limit_side_len':960,
        'Global.log_level':'critical'})


def recognize(engine,image):
    output = engine(image)
    texts = output.txts or ()
    scores = output.scores if output.scores is not None else ()
    text = '\n'.join(texts)[:8000]
    quality = float(sum(scores)/len(scores)) if len(scores) else None
    return {'source':'ocr','status':('low_quality' if quality is not None and quality<.7 else 'success') if text else 'no_text',
            'text':text,'quality':quality}


def capture(request):
    from .desktop import context,matches,unobscured
    from .uia import extract
    import mss
    import numpy as np
    expected = request['context']
    permit = request['permit']
    if not permit or expected['process'].casefold()!=permit['app'].casefold():
        return {'source':'ocr','status':'not_authorized'}
    left,top,right,bottom = expected['rect']
    x,y,width,height = permit['region']
    max_pixels = 16_000_000 if permit.get('auto') else 4_000_000
    if (right-left,bottom-top)!=tuple(permit['size']) or min(x,y)<0 or min(width,height)<=0 or x+width>right-left or y+height>bottom-top or width*height>max_pixels:
        return {'source':'ocr','status':'region_invalid'}
    engine = create_engine()  # Load before final checks; no image retained during loading.
    if not matches(expected,context(request['exclude'],request['exclude_windows'])):
        return {'source':'ocr','status':'stale'}
    check = extract(expected['hwnd'])
    if check['status'] not in ('success','no_text') or not check.get('ocr_safe'):
        return {'source':'ocr','status':'unsafe_region'}
    rect = (left+x,top+y,left+x+width,top+y+height)
    if not matches(expected,context(request['exclude'],request['exclude_windows'])) or not unobscured(expected['hwnd'],rect):
        return {'source':'ocr','status':'stale'}
    with mss.mss() as screen:
        shot = screen.grab({'left':rect[0],'top':rect[1],'width':width,'height':height})
        pixels = np.asarray(shot)[:,:,:3].copy()
        del shot
    try:
        if not matches(expected,context(request['exclude'],request['exclude_windows'])) or not unobscured(expected['hwnd'],rect):
            return {'source':'ocr','status':'stale'}
        result = recognize(engine,pixels)
        if permit.get('retain') and result['status'] in ('success','no_text'):
            # Only retain a fully OCR-processed image without detected sensitive text.
            # This is best-effort; explicit safe-region permission remains mandatory.
            from .policy import normalize, sensitive_window
            original = ' '.join((result.get('text') or '').split())
            if normalize(original) == original and not sensitive_window(original):
                import mss.tools
                if matches(expected,context(request['exclude'],request['exclude_windows'])) and unobscured(expected['hwnd'],rect):
                    result['image_png'] = mss.tools.to_png(pixels[:,:,::-1].tobytes(), (width,height))
                    result['image_size'] = (width,height)
        return result
    finally:
        pixels.fill(0)
        del pixels
