import re

from ..content.policy import normalize


def clean_profile(value):
    if not isinstance(value, dict):
        raise ValueError('Profile must be an object')
    result = {}
    for field in ('activities', 'projects', 'software', 'websites'):
        items = value.get(field, [])
        if not isinstance(items, list) or len(items) > 100 or any(not isinstance(x, str) for x in items):
            raise ValueError('Invalid profile list')
        result[field] = list(dict.fromkeys(normalize(x)[:200] for x in items if x.strip()))
    for field in ('description', 'hours', 'workflow'):
        if not isinstance(value.get(field, ''), str):
            raise ValueError('Invalid profile description')
        result[field] = normalize(value.get(field, ''))[:2000]
    return result


def propose_profile(text):
    """Local, explicitly labelled suggestions; user reviews before persistence."""
    text = normalize(text)
    categories = {'编程开发': ('开发', '编程', '代码'), '产品调研': ('调研', '竞品'),
                  '写作': ('写作', '文章'), '学习': ('学习', '教程', '研究'),
                  '娱乐': ('娱乐', '游戏'), '视频剪辑': ('剪辑', '视频制作')}
    return clean_profile({
        'activities': [k for k, words in categories.items() if any(w in text for w in words)],
        'software': [s for s in ('Chrome', 'Edge', 'VS Code', 'Codex', 'ChatGPT', '剪映') if s.casefold() in text.casefold()],
        'websites': re.findall(r'https?://[^\s，。；]+', text),
        'projects': [], 'description': text,
    })
