import queue
import time

from .domain import Observation
from .engine import Engine
from .storage.repository import InstanceLock, Repository


def clock():
    return time.monotonic_ns() // 1_000_000, time.time_ns() // 1_000_000


def run(database, idle_seconds=300, exclude=None, duration=None, content=False, exclude_windows=(), permit=None, min_dwell_seconds=None):
    from .preferences import dwell_seconds, validate_dwell
    dwell = dwell_seconds(database) if min_dwell_seconds is None else validate_dwell(min_dwell_seconds)
    from .preferences import screenshots_enabled
    if content and permit is None and screenshots_enabled(database):
        permit={'auto':True,'retain':True,'days':7,'from_preferences':True}
    from .windows import WindowsSource
    with InstanceLock(database):
        source = WindowsSource()
        source.api.excluded_windows = exclude_windows
        source.content_events = content
        source.geometry_events = bool(permit)
        if not source.api.desktop_available() or not source.api.u.GetForegroundWindow():
            raise RuntimeError("No accessible interactive desktop. Run start in your signed-in desktop PowerShell.")
        source.start()
        repo = None
        engine = None
        collector = None
        try:
            repo = Repository(database)
            if permit and permit.get('retain'):
                from .storage.screenshots import migrate
                migrate(repo)
            mono, wall = clock()
            repo.recover(wall)
            repo.cleanup(wall)
            engine = Engine(repo, wall, mono, int(idle_seconds * 1000),min_active_ms=round(dwell*1000))
            if content:
                from .content.coordinator import Coordinator
                collector = Coordinator(repo,engine,exclude or [],exclude_windows,permit)
            deadline = mono + int(duration * 1000) if duration else None
            print("MONITORING | content="+str(content)+" | screenshots="+str(bool(permit))+" | local only; no keys, clipboard or network", flush=True)
            print(f"Database: {database.resolve()} | session: {engine.session}", flush=True)
            print("Use another terminal: pause / resume / stop. Ctrl+C stops. Idle means no input, not absence.", flush=True)
            print(f'Minimum page dwell: {dwell:g} seconds; shorter visits retain anonymous gap timing only.',flush=True)
            next_poll = mono
            next_cleanup = mono + 3_600_000
            while not engine.stopped:
                mono, wall = clock()
                if collector and collector.permit and collector.permit.get('from_preferences') and not screenshots_enabled(database):
                    collector.invalidate(clear=True)
                    collector.permit=None
                    print('SCREENSHOTS: disabled',flush=True)
                commands = repo.db.execute("SELECT * FROM control_commands WHERE session_id=? AND acknowledged_ms IS NULL ORDER BY rowid", (engine.session,)).fetchall()
                for command in commands:
                    if collector:
                        collector.invalidate(clear=True)
                    if command["command"] == "pause":
                        engine.pause(mono, wall)
                    elif command["command"] == "resume":
                        engine.resume(mono, wall)
                        # Reject pre-resume events; no stale title can enter the new state.
                        while True:
                            try:
                                source.events.get_nowait()
                            except queue.Empty:
                                break
                        next_poll = mono
                    else:
                        engine.stop(mono, wall)
                    with repo.db:
                        repo.db.execute("UPDATE control_commands SET acknowledged_ms=?,result='ok' WHERE id=?", (wall, command["id"]))
                        if engine.stopped:
                            repo.db.execute("UPDATE control_commands SET acknowledged_ms=?,result='abandoned' WHERE session_id=? AND acknowledged_ms IS NULL", (wall, engine.session))
                    print("STATE: " + ("stopped" if engine.stopped else "paused" if engine.paused else "monitoring"), flush=True)
                    if engine.stopped:
                        break
                if engine.stopped:
                    break
                if deadline and mono >= deadline:
                    engine.stop(mono, wall, "duration")
                    break
                if source.error or not source.thread.is_alive():
                    raise RuntimeError("Windows event thread stopped; collection stopped safely.")
                if mono >= next_cleanup:
                    repo.cleanup(wall)
                    next_cleanup = mono + 3_600_000
                try:
                    kind, hwnd, observed_mono = source.events.get(timeout=0.1)
                except queue.Empty:
                    kind, hwnd = "poll", None
                mono, wall = clock()
                if kind=='content' and collector:
                    collector.hint(mono)
                if kind=='geometry' and collector:
                    collector.geometry_changed(hwnd)
                if kind == "poll" and mono < next_poll and not source.overflow.is_set():
                    if collector:
                        collector.tick(mono,wall)
                    continue
                if source.overflow.is_set():
                    source.overflow.clear()
                    if collector and collector.permit:
                        collector.grant_invalid=True
                        collector.invalidate()
                    engine.sample(mono, wall, Observation("unknown"), source="queue_overflow")
                if engine.paused:
                    observation, idle = Observation("paused"), 0
                else:
                    try:
                        idle = source.api.idle_for_ms()
                        # Session notifications are applied even if a subsequent unlock is queued.
                        if kind in ("locked", "suspended"):
                            observation = Observation(kind)
                        else:
                            # Resolve exclusion/permission state first, never read idle titles.
                            observation = source.snapshot(exclude or [], hwnd, read_title=idle < engine.idle_ms)
                    except OSError:
                        observation, idle = Observation("unknown"), 0
                engine.sample(mono, wall, observation, idle, source="winevent" if kind != "poll" else "poll")
                if collector:
                    collector.tick(mono,wall)
                next_poll = mono + 1000
        except KeyboardInterrupt:
            if collector:
                collector.close()
            if engine:
                engine.stop(*clock(), reason="interrupt")
        except BaseException:
            # A failing database must not be overwritten with an invented successful stop.
            # OS lock releases; next start repairs the session at the last committed checkpoint.
            raise
        finally:
            if collector:
                collector.close()
            source.close()
            if repo:
                repo.close()
            print("STOPPED | collection inactive", flush=True)


def simulate(database):
    """Replay 30 logical minutes instantly; never invokes Windows APIs or reads the desktop."""
    with InstanceLock(database):
        repo = Repository(database)
        try:
            if repo.db.execute("SELECT 1 FROM capture_sessions").fetchone():
                raise RuntimeError("Simulation requires an empty database; choose a separate --db path.")
            wall = 1_798_761_600_000
            engine = Engine(repo, wall, 0, simulated=True)
            for second in range(1801):
                if second == 1200:
                    engine.pause(second * 1000, wall + second * 1000)
                if second == 1260:
                    engine.resume(second * 1000, wall + second * 1000)
                app = "Code.exe" if second < 600 or second >= 1260 else "msedge.exe"
                idle = (second - 600) * 1000 if 600 <= second < 1020 else 0
                engine.sample(second * 1000, wall + second * 1000, Observation("active", app, app, "Synthetic DayTrace fixture", 1 if app == "Code.exe" else 2), idle, "simulation")
            engine.stop(1_800_000, wall + 1_800_000)
            print("Simulated 1800 seconds: active=1320s idle=420s paused=60s. No real collection.")
        finally:
            repo.close()
