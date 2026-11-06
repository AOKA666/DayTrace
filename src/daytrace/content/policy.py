import hashlib
import re
from difflib import SequenceMatcher

from ..privacy import SECRET, EMAIL, URL_QUERY

SENSITIVE_APPS = ('1password.exe', 'bitwarden.exe', 'keepass.exe', 'keepassxc.exe',
                  'dashlane.exe', 'lastpass.exe', 'enpass.exe')
SENSITIVE = re.compile(r'(?i)(incognito|inprivate|private browsing|private window|隐身|无痕|隐私浏览|隐私窗口|密码管理|password manager|支付宝|微信支付|财付通|网上银行|网银|支付|付款|收银|银行|banking|checkout|payment|paypal|alipay)')


def sensitive_window(title, patterns=()):
    return bool(SENSITIVE.search(title)) or any(p.casefold() in title.casefold() for p in patterns)


def normalize(text):
    text = ' '.join(''.join(c if c.isprintable() else ' ' for c in text[:16000]).split())[:8000]
    text = SECRET.sub(lambda m: m.group(1) + '=[REDACTED]', text)
    text = EMAIL.sub('[EMAIL]', text)
    text = URL_QUERY.sub(r'\1?[REDACTED]', text)
    text = re.sub(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)', '[LONG_NUMBER]', text)
    return text


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def similar(left, right):
    # Bounded comparison; short UI labels must match exactly.
    return left == right or (min(len(left),len(right)) >= 100 and
        abs(len(left)-len(right)) <= max(len(left),len(right)) * .03 and
        SequenceMatcher(None,left[:8000],right[:8000],autojunk=True).ratio() >= .98)
