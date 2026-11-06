"""COM adapter loaded only in an isolated worker; never DocumentRange/ValuePattern."""
import time

from .policy import sensitive_window


def extract_tree(root, adapter, deadline, max_nodes=300, max_depth=32):
    """Inspect properties before names/text; read safe TextPattern visible ranges.

    Container text is allowed only after all descendants were inspected, with no
    hidden/password descendants. Truncated trees cannot authorize OCR.
    """
    stack = [(root,0,())]
    entries, unsafe, nodes = [], set(), 0
    truncated, password = False, False
    while stack:
        if time.monotonic() >= deadline:
            return {'source':'uia','status':'timeout'}
        if nodes >= max_nodes:
            truncated = True
            for _,_,ancestors in stack:
                unsafe.update(ancestors)
            break
        node, depth, ancestors = stack.pop()
        identifier = nodes
        nodes += 1
        if adapter.password(node):
            password = True
            unsafe.update(ancestors)
            continue
        if adapter.hidden(node):
            unsafe.update(ancestors)
            continue
        children = adapter.children(node,max_nodes-nodes+1)
        entries.append((identifier,node,ancestors,bool(children)))
        if children:
            if depth >= max_depth:
                truncated = True
                unsafe.update((*ancestors,identifier))
            else:
                stack.extend((child,depth+1,(*ancestors,identifier)) for child in reversed(children))
    pieces, covered, size, read_errors = [], set(), 0, 0
    # Children first. A container can expose TextPattern only after its descendants
    # were checked and no password/hidden/truncated subtree can be aggregated.
    for identifier,node,ancestors,has_children in reversed(entries):
        if time.monotonic() >= deadline:
            return {'source':'uia','status':'timeout'}
        if size >= 8000:
            truncated = True
            break
        if identifier in unsafe or identifier in covered:
            continue
        try:
            text = adapter.visible_text(node,8000-size)
        except Exception as exc:
            # Dynamic providers may invalidate one range while other nodes remain
            # readable. Never turn a failed range read into an OCR-safe empty scan.
            if not isinstance(exc,OSError) and not hasattr(exc,'hresult'):
                raise
            read_errors += 1
            continue
        if sensitive_window(text):
            return {'source':'uia','status':'excluded','nodes':nodes}
        if text:
            pieces.append(text)
            covered.update(ancestors)
            size += len(text)
    text = '\n'.join(dict.fromkeys(reversed(pieces)))[:8000]
    return {'source':'uia','status':('partial' if truncated or read_errors else 'success') if text else ('scan_limited' if truncated else 'unavailable' if read_errors else 'no_text'), 'text':text,
            'nodes':nodes,'truncated':truncated,'read_errors':read_errors, 'ocr_safe':not truncated and not password and not read_errors}


class ComAdapter:
    def __init__(self):
        import comtypes.client
        self.mod = comtypes.client.GetModule('UIAutomationCore.dll')
        self.client = comtypes.client.CreateObject(self.mod.CUIAutomation, interface=self.mod.IUIAutomation)
        self.walker = self.client.RawViewWalker

    def password(self,node):
        return bool(node.CurrentIsPassword)

    def hidden(self,node):
        # Virtual containers may have no rectangle while their children are visible.
        # Their geometry cannot be used to prune the entire subtree.
        return bool(node.CurrentIsOffscreen)

    def children(self,node,limit):
        result = []
        child = self.walker.GetFirstChildElement(node)
        while child and len(result)<limit:
            result.append(child)
            child = self.walker.GetNextSiblingElement(child)
        return result

    def visible_text(self,node,limit):
        if node.CurrentIsPassword or node.CurrentIsOffscreen:
            return ''
        # IsTextPatternAvailable avoids using exceptions for unsupported controls.
        if node.GetCurrentPropertyValue(30040):
            pattern = node.GetCurrentPattern(10014).QueryInterface(self.mod.IUIAutomationTextPattern)
            ranges = pattern.GetVisibleRanges()
            parts = []
            for i in range(min(ranges.Length,64)):
                if limit <= 0:
                    break
                visible_range=ranges.GetElement(i)
                rectangles=visible_range.GetBoundingRectangles()
                if not rectangles or not any(rectangles[j+2]>0 and rectangles[j+3]>0 for j in range(0,len(rectangles)-3,4)):
                    continue
                value = visible_range.GetText(limit)
                parts.append(value)
                limit -= len(value)
            return '\n'.join(parts)
        # Static text / hyperlink only: do not read editable values or button labels.
        if node.CurrentControlType in (50020,50005):
            r=node.CurrentBoundingRectangle
            if r.right<=r.left or r.bottom<=r.top:
                return ''
            return (node.CurrentName or '')[:limit]
        return ''


def extract(hwnd):
    import sys
    sys.coinit_flags = 0
    import comtypes
    comtypes.CoInitializeEx(0)  # MTA; worker is isolated from the desktop message thread.
    try:
        adapter = ComAdapter()
        root = adapter.client.ElementFromHandle(hwnd)
        return extract_tree(root,adapter,time.monotonic()+1.4)
    finally:
        comtypes.CoUninitialize()
