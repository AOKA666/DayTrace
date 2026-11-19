"""Foreground media playback state without reading media titles or history."""
from __future__ import annotations

import asyncio
import ntpath
import re
import threading
import time

from .domain import Observation


def source_matches_process(source: str, process_name: str | None) -> bool:
    """Conservatively associate a system media session with the foreground app."""
    if not source or not process_name:
        return False
    process = ntpath.basename(process_name).casefold()
    source = source.casefold().replace('/', '\\')
    if ntpath.basename(source) == process or source.endswith('!' + process):
        return True
    stem = process[:-4] if process.endswith('.exe') else process
    # Packaged players expose an AUMID rather than an executable name.
    tokens = {value for value in re.split(r'[^a-z0-9]+', source) if value}
    return len(stem) >= 4 and stem in tokens


class MediaPlaybackMonitor:
    """Poll GSMTC on a worker thread; collection never waits for WinRT."""
    def __init__(self, autostart: bool = True):
        self._lock = threading.Lock()
        self._playing: set[str] = set()
        self._updated = 0.0
        self._stop = threading.Event()
        self.available = False
        self.thread = None
        if autostart:
            self.thread = threading.Thread(target=self._run, name='daytrace-media', daemon=True)
            self.thread.start()

    def _replace(self, sources):
        with self._lock:
            self._playing = {str(value) for value in sources if value}
            self._updated = time.monotonic()

    async def _watch(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )
        manager = await Manager.request_async()
        self.available = True
        while not self._stop.is_set():
            playing = []
            try:
                for session in manager.get_sessions():
                    if session.get_playback_info().playback_status == Status.PLAYING:
                        playing.append(session.source_app_user_model_id)
            except (OSError, RuntimeError):
                playing = []
            self._replace(playing)
            await asyncio.sleep(.75)

    def _run(self):
        try:
            asyncio.run(self._watch())
        except (ImportError, OSError, RuntimeError):
            self.available = False
            self._replace(())

    def playing_for(self, process_name: str | None) -> bool:
        with self._lock:
            if time.monotonic() - self._updated > 3:
                return False
            return any(source_matches_process(source, process_name) for source in self._playing)

    def close(self):
        self._stop.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(2)


class MediaIdleGuard:
    """Prevent playback time from being backdated to the last user input."""
    def __init__(self):
        self.key = None
        self.last_playing_ms = None

    def clear(self):
        self.key = self.last_playing_ms = None

    def resolve(self, source, observation, raw_idle, idle_ms, media, now_ms, exclude):
        if observation.state != 'active':
            self.clear()
            return observation, raw_idle, False
        key = (observation.process_name, observation.window)
        playing = media.playing_for(observation.process_name)
        if playing:
            if raw_idle >= idle_ms:
                # The idle probe omitted a title. Re-check the same foreground
                # window and all exclusion rules before treating it as activity.
                refreshed = source.snapshot(exclude or [], observation.window, read_title=True)
                if refreshed.state != 'active':
                    self.clear()
                    return refreshed, 0, False
                if (refreshed.process_name, refreshed.window) != key:
                    self.clear()
                    return Observation('unknown'), 0, False
                observation = refreshed
                playing = media.playing_for(refreshed.process_name)
            if playing:
                self.key, self.last_playing_ms = key, now_ms
                return observation, 0, True
        if self.key == key and self.last_playing_ms is not None:
            since_playback = max(0, now_ms - self.last_playing_ms)
            if raw_idle < since_playback:
                # Input happened after the last playback observation.
                self.clear()
                return observation, raw_idle, False
            return observation, since_playback, False
        if raw_idle < idle_ms:
            self.clear()
            return observation, raw_idle, False
        self.clear()
        return observation, raw_idle, False

