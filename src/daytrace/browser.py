"""Foreground address-bar metadata only. Never browser history or page input fields."""
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit, unquote, quote
import re
import time

from .content.policy import sensitive_window, normalize

BROWSERS = {'chrome.exe', 'msedge.exe', 'brave.exe', 'vivaldi.exe', 'firefox.exe'}
ADDRESS_NAMES = {'address and search bar', 'address and search', 'search or enter address',
                 'search with google or enter address', '地址和搜索栏', '地址与搜索栏',
                 '搜索或输入地址', '搜索或输入网址', '地址栏'}


def safe_url(value):
    value = value.strip()
    if not value or len(value)>2048 or any(c.isspace() or ord(c)<32 for c in value):
        return None
    try:
        explicit_scheme = '://' in value
        parsed = urlsplit(value if explicit_scheme else 'https://' + value)
        host = (parsed.hostname or '').encode('idna').decode('ascii').lower().rstrip('.')
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            return None
        if '.' not in host or not re.fullmatch(r'[a-z0-9.-]+', host):
            return None
        if sensitive_window(unquote(host + parsed.path)):
            return None
        port = parsed.port
        path = normalize(unquote(parsed.path))
        # Path components can also hold credentials; redact long opaque identifiers.
        path = re.sub(r'[A-Za-z0-9_-]{32,}', '[REDACTED]', path)
        authority = host + (f':{port}' if port else '')
        path = quote(path, safe="/:@!$&'()*+,;=-._~[]")
        return (urlunsplit((parsed.scheme, authority, path, '', '')) if explicit_scheme else authority+path), host
    except (ValueError, UnicodeError):
        return None


def same_site(a, b):
    return bool(a and b and a.state == b.state == 'active' and a.domain and a.domain == b.domain
                and a.process_name and a.process_name.lower() in BROWSERS
                and (a.app_id, a.window) == (b.app_id, b.window))


def extract_address(root, adapter, deadline):
    stack = [(root, 0)]
    count = 0
    while stack and count < 160 and time.monotonic() < deadline:
        node, depth = stack.pop()
        count += 1
        if adapter.password(node) or adapter.hidden(node):
            continue
        # Never walk web document content, where a page can imitate address controls.
        kind = node.CurrentControlType
        if kind == 50030:
            continue
        if kind == 50004:
            name = (node.CurrentName or '').strip().casefold()
            if name in ADDRESS_NAMES:
                if node.CurrentHasKeyboardFocus:
                    return {'source': 'browser', 'status': 'editing'}
                value = node.GetCurrentPattern(10002).QueryInterface(adapter.mod.IUIAutomationValuePattern).CurrentValue
                if sensitive_window(unquote((value or '').split('?')[0])):
                    return {'source':'browser','status':'excluded'}
                result = safe_url(value or '')
                return {'source': 'browser', 'status': 'success', 'url': result[0], 'domain': result[1]} if result else {'source': 'browser', 'status': 'unavailable'}
        if depth < 16:
            stack.extend((child, depth+1) for child in reversed(adapter.children(node, 161-count)))
    return {'source': 'browser', 'status': 'unavailable'}


def extract(hwnd):
    import comtypes
    from .content.uia import ComAdapter
    comtypes.CoInitializeEx(0)
    try:
        adapter = ComAdapter()
        return extract_address(adapter.client.ElementFromHandle(hwnd), adapter, time.monotonic()+1.4)
    finally:
        comtypes.CoUninitialize()


class BrowserProbe:
    """Bounded asynchronous lookup, invalidated on every foreground/title boundary."""
    def __init__(self, exclude=(), windows=(), factory=None, context_reader=None):
        from .content.coordinator import Worker
        from .content.desktop import context
        self.factory = factory or Worker
        self.context_reader = context_reader or context
        self.exclude, self.windows = list(exclude), list(windows)
        self.worker = None
        self.key = None
        self.result = None
        self.next_read = 0
        self.last_launch = -10**12

    def close(self):
        if self.worker:
            self.worker.close()
        self.worker = None
        self.key = self.result = None

    def resolve(self, observation, mono):
        if observation.state != 'active' or (observation.process_name or '').lower() not in BROWSERS:
            self.close()
            return observation
        key = (observation.app_id, observation.window, observation.title)
        if key != self.key:
            self.close()
            self.key, self.next_read = key, 0
        if self.worker:
            result = self.worker.poll()
            if result is None:
                return None
            self.worker.close()
            self.worker = None
            self.result = result
            self.next_read = mono + 1000
        if mono >= self.next_read:
            if mono-self.last_launch < 500:
                return None
            ctx = self.context_reader(self.exclude, self.windows)
            if not ctx or (ctx['app'],ctx['hwnd'],ctx['title']) != key:
                self.close()
                return observation.anonymous('unknown')
            try:
                self.last_launch = mono
                self.worker = self.factory({'source':'browser','context':ctx,'exclude':self.exclude,'exclude_windows':self.windows})
                return None
            except Exception:
                self.result = {'status':'unavailable'}
                self.next_read = mono+5000
        if self.result and self.result.get('status') in ('excluded','editing','stale'):
            return observation.anonymous('excluded' if self.result['status']=='excluded' else 'unknown')
        if self.result and self.result.get('status') == 'success':
            checked = safe_url(self.result.get('url', ''))
            if checked:
                return replace(observation, url=checked[0], domain=checked[1])
        return observation
