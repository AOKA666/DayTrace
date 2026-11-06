"""Best-effort title redaction; never claims arbitrary secrets are detectable."""
import hashlib
import ntpath
import re

SECRET = re.compile(r"(?i)\b(password|passwd|pwd|token|api[_-]?key|secret|authorization)\s*[:=]\s*[^\s&;]+")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
URL_QUERY = re.compile(r"(https?://[^\s?#]+)[?#][^\s]*", re.I)


def redact_title(title: str) -> str:
    title = "".join(ch if ch.isprintable() else " " for ch in title[:2048])
    title = SECRET.sub(lambda m: m.group(1) + "=[REDACTED]", title)
    title = EMAIL.sub("[EMAIL]", title)
    return URL_QUERY.sub(r"\1?[REDACTED]", title)


def excluded(path: str, rules: list[str]) -> bool:
    path = ntpath.normcase(path)
    return any(ntpath.normcase(rule) in (path, ntpath.basename(path)) for rule in rules)


def app_identity(path: str) -> str:
    # Avoid persisting home-directory names in executable paths.
    return hashlib.sha256(ntpath.normcase(path).encode("utf-8")).hexdigest()
