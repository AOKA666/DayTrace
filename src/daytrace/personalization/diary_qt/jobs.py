"""Thread-pool completion hooks that must reach the Qt GUI thread via Signal."""

from PySide6.QtCore import QObject, Signal


class JobBridge(QObject):
    """Emit when a worker future completes; slot runs on the GUI thread (queued)."""

    finished = Signal(object, object, bool)


class CaptureBridge(QObject):
    state_ready = Signal(str)


__all__ = ['CaptureBridge', 'JobBridge']
