"""Category color palette and helpers (no UI toolkit dependencies)."""
from __future__ import annotations

import hashlib

PALETTE = ('#7566D9', '#3C9B92', '#DC9B4B', '#5B8FCB', '#CA7298', '#849448', '#A17DD0', '#C87C60')

DEFAULT_CATEGORY_COLORS = {
    '工作': '#5B8FCB',
    '学习': '#7566D9',
    '沟通': '#3C9B92',
    '娱乐': '#DC9B4B',
    '生活': '#CA7298',
    '其他': '#849448',
}


def default_tag_color(name):
    colors = ('#6550B5', '#23776D', '#96601F', '#3568A6', '#A04774', '#586B28')
    return colors[int(hashlib.sha256(name.encode('utf-8')).hexdigest()[:8], 16) % len(colors)]


def category_color(name, colors):
    if not name:
        return '#BEC7D3'
    return colors.get(name) or PALETTE[int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) % len(PALETTE)]


def contrasting_text(hex_color: str) -> str:
    raw = (hex_color or '').lstrip('#')
    if len(raw) != 6:
        return '#243041'
    red, green, blue = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return '#FFFFFF' if luminance < 150 else '#243041'


def bootstrap_category_colors(database, activities):
    from ..preferences import options, save_options

    colors = dict(options(database).get('category_colors', {}))
    changed = False
    for index, name in enumerate(activities or []):
        if name not in colors:
            colors[name] = DEFAULT_CATEGORY_COLORS.get(name) or PALETTE[index % len(PALETTE)]
            changed = True
    if changed:
        save_options(database, category_colors=colors)
    return colors
