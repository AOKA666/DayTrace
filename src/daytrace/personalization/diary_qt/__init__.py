"""PySide6 diary shell — default desktop UI for `daytrace.py ui`."""
from __future__ import annotations

import sys
from pathlib import Path

INSTALL_HINT = (
    '日记界面需要 PySide6。\n'
    '请运行：pip install "daytrace[ui]"  或  pip install "PySide6>=6.7,<6.9"\n'
    '也可使用 Tk 日记壳回退：daytrace.py ui --tk-diary\n'
    '或使用旧版界面：daytrace.py ui --legacy'
)


def launch(database):
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit(INSTALL_HINT) from exc
    from .window import run_app

    app, _window = run_app(Path(database))
    sys.exit(app.exec())


def preview(database, on_ready=None):
    """Start preview window; optional callback receives (app, window)."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit(INSTALL_HINT) from exc
    from .window import run_app

    app, window = run_app(Path(database), preview_mode=True)
    if on_ready:
        on_ready(app, window)
    return app, window
