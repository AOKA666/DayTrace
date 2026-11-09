"""Deterministic interval state machine; Windows-independent and replayable."""
from datetime import datetime
import os

from .domain import Observation, STATES
from .privacy import redact_title
from .storage.repository import uid


class Engine:
    def __init__(self, repo, wall_ms, mono_ms, idle_ms=300_000, simulated=False, min_active_ms=0):
        self.repo = repo
        self.session = uid()
        self.origin_mono = mono_ms
        last = repo.db.execute("SELECT MAX(end_ms) FROM activity_intervals").fetchone()[0]
        self.origin_wall = max(wall_ms, last or wall_ms)
        self.last_mono = mono_ms
        self.at = self.origin_wall
        self.idle_ms = idle_ms
        self.min_active_ms = min_active_ms
        self.pending = None
        self.current = None
        self.event_id = None
        self.interval_id = None
        self.paused = False
        self.stopped = False
        self.last_wall_offset = wall_ms - self.at
        with repo.transaction():
            repo.db.execute("INSERT INTO capture_sessions VALUES (?,?, 'windows',?,NULL,?,?,?,'running',NULL,?)",
                            (self.session, repo.device_id, self.at, self.at, datetime.now().astimezone().tzname(), os.getpid(), int(simulated)))
            repo.event(self.session, self.at, wall_ms, "start", "unknown", source="command")

    def _time(self, mono):
        if mono < self.last_mono:
            raise ValueError("Monotonic time moved backwards")
        return self.origin_wall + mono - self.origin_mono

    def _transition(self, observation, at, wall, source, kind=None):
        if observation == self.current:
            return
        if self.interval_id:
            self.repo.db.execute("UPDATE activity_intervals SET end_ms=? WHERE id=?", (at, self.interval_id))
        if kind is None:
            if observation.state == "active":
                same_window = self.current and self.current.state == "active" and (self.current.app_id, self.current.window) == (observation.app_id, observation.window)
                kind = "title_change" if same_window else "foreground_switch"
            else:
                kind = 'dwell_gap' if source == 'dwell' else "state_change"
        self.interval_id = self.repo.interval(self.session, at, at, observation.state, observation.process_name, observation.app_id, observation.title)
        self.event_id = self.repo.event(self.session, at, wall, kind, observation.state, observation.process_name, observation.app_id, observation.title, source)
        self.current = observation

    def _admit_pending(self):
        observation,mono,wall,source=self.pending
        start=self._time(mono) if mono>=self.last_mono else self.origin_wall+mono-self.origin_mono
        with self.repo.transaction():
            self._transition(observation,start,wall,source)
        self.pending=None

    def sample(self, mono_ms, wall_ms, observation, idle_for_ms=0, source="poll"):
        if not self.min_active_ms:
            return self._sample(mono_ms,wall_ms,observation,idle_for_ms,source)
        if self.stopped or mono_ms<self.last_mono or idle_for_ms<0 or observation.state not in STATES:
            raise ValueError('Invalid observation or session state')
        if observation.state=='active':
            observation=Observation('active',observation.process_name,observation.app_id,redact_title(observation.title or ''),observation.window)
        blocked=self.paused or observation.state!='active' or idle_for_ms>=self.idle_ms
        # Never qualify a candidate across an unobserved stall or privacy boundary.
        if mono_ms-self.last_mono>5000 or idle_for_ms>=self.idle_ms or (blocked and source!='command'):
            self.pending=None
        if self.pending and mono_ms-self.pending[1]>=self.min_active_ms:
            self._admit_pending()
        if blocked:
            self.pending=None
            return self._sample(mono_ms,wall_ms,observation,idle_for_ms,source)
        if observation==self.current:
            self.pending=None
            return self._sample(mono_ms,wall_ms,observation,idle_for_ms,source)
        if not self.pending or observation!=self.pending[0]:
            self.pending=(observation,mono_ms,wall_ms,source)
        # Only anonymous timing is durable until this page reaches the threshold.
        return self._sample(mono_ms,wall_ms,Observation('unknown'),0,'dwell')

    def _sample(self, mono_ms, wall_ms, observation, idle_for_ms=0, source="poll"):
        if self.stopped:
            raise RuntimeError("Session already stopped")
        if observation.state not in STATES or idle_for_ms < 0:
            raise ValueError("Invalid observation")
        at = self._time(mono_ms)
        # Paused/blocked observations cannot carry application or title data.
        if self.paused:
            observation = Observation("paused")
        elif observation.state != "active":
            observation = Observation(observation.state)
        else:
            observation = Observation("active", observation.process_name, observation.app_id, redact_title(observation.title or ""), observation.window)
        with self.repo.transaction():
            if abs((wall_ms - at) - self.last_wall_offset) > 2000:
                self.repo.event(self.session, at, wall_ms, "clock_adjustment", "unknown", source="clock")
                self.last_wall_offset = wall_ms - at
            # Never bridge unobserved stalls/sleep as productive time.
            if mono_ms - self.last_mono > 5000 and self.current and self.current.state not in ("paused", "suspended", "locked"):
                self._transition(Observation("unknown"), self.at, wall_ms, "gap", "observation_gap")
            if self.interval_id:
                self.repo.db.execute("UPDATE activity_intervals SET end_ms=? WHERE id=?", (at, self.interval_id))
            if observation.state == "active" and idle_for_ms >= self.idle_ms:
                observation = Observation("idle")
                if self.current != observation:
                    cutoff = max(self.origin_wall, at - idle_for_ms)
                    self.repo.reclassify_idle(self.session, cutoff, self.min_active_ms)
                    # Current interval may have been split: never extend the old active part.
                    self.repo.event(self.session, at, wall_ms, "idle_detected", "idle", source=source)
                    self.current = observation
                    self.interval_id = self.repo.interval(self.session, at, at, "idle")
            else:
                self._transition(observation, at, wall_ms, source)
            self.repo.db.execute("UPDATE capture_sessions SET heartbeat_ms=?,status=? WHERE id=?", (at, "paused" if self.paused else "running", self.session))
        self.at, self.last_mono = at, mono_ms

    def pause(self, mono, wall):
        self.paused = True
        self.sample(mono, wall, Observation("paused"), source="command")

    def resume(self, mono, wall):
        if self.paused:
            self.paused = False
            self.sample(mono, wall, Observation("unknown"), source="command")

    def stop(self, mono, wall, reason="stop"):
        if self.stopped:
            return
        # Close at stop; sample() converts a long unobserved tail to unknown.
        self.sample(mono, wall, Observation("unknown"), source="command")
        with self.repo.transaction():
            self.repo.event(self.session, self.at, wall, "stop", self.current.state, source="command")
            self.repo.db.execute("UPDATE capture_sessions SET ended_ms=?,status='stopped',exit_reason=? WHERE id=?", (self.at, reason, self.session))
            self.repo.db.execute("DELETE FROM activity_intervals WHERE session_id=? AND start_ms=end_ms", (self.session,))
        self.stopped = True
