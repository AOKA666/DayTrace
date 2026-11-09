"""Read collector session state for the diary shell (same DB as CLI start)."""
from __future__ import annotations

from pathlib import Path

from ..diary_worker import capture_state
from ..store import Memory


def repo_root() -> Path:
    """Repository root (contains daytrace.py); diary_qt is four levels below src."""
    return Path(__file__).resolve().parents[4]


def read_capture_state(database: Path) -> str:
    """Return running | paused | stopped based on instance lock and open session."""
    memory = Memory(database, cleanup=False)
    try:
        return capture_state(memory)
    finally:
        memory.close()
