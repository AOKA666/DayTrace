import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from .storage.repository import InstanceLock, Repository, is_running, readonly, uid


def default_database():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "DayTrace" / "activity.sqlite3"


def positive(value):
    number = float(value)
    if not 0 < number <= 31_536_000:
        raise argparse.ArgumentTypeError("must be positive and at most one year")
    return number


def control(database, command):
    if not database.exists() or not is_running(database):
        raise RuntimeError("No collector is running for this database.")
    db = sqlite3.connect(database, timeout=5)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        session = db.execute("SELECT id FROM capture_sessions WHERE ended_ms IS NULL").fetchone()
        if not session:
            raise RuntimeError("Collector has not started a session yet.")
        identifier = uid()
        with db:
            db.execute("INSERT INTO control_commands(id,session_id,command,requested_ms) VALUES (?,?,?,?)", (identifier, session[0], command, time.time_ns() // 1_000_000))
        until = time.monotonic() + 10
        while time.monotonic() < until:
            row = db.execute("SELECT result FROM control_commands WHERE id=?", (identifier,)).fetchone()
            if row and row[0]:
                if row[0] != "ok":
                    raise RuntimeError("Command abandoned with the previous session.")
                if command == "stop" and is_running(database):
                    time.sleep(0.05)
                    continue
                print(command + ": acknowledged")
                return
            time.sleep(0.05)
        raise RuntimeError("Command not acknowledged within 10 seconds; it may still be pending. Check status.")
    finally:
        db.close()


def records(database, table, limit, show_titles):
    db = readonly(database)
    try:
        if table == 'browser':
            rows = db.execute('SELECT * FROM browser_pages WHERE expires_ms>? ORDER BY captured_ms DESC LIMIT ?',
                              (time.time_ns()//1_000_000,limit)).fetchall()
        elif table == "summary":
            rows = db.execute("SELECT state, COUNT(*) AS intervals, ROUND(SUM(duration_ms)/1000.0,3) AS seconds FROM activity_intervals WHERE duration_ms>0 GROUP BY state ORDER BY state").fetchall()
        else:
            mapping = {"events": ("activity_events", "at_ms"), "intervals": ("activity_intervals", "start_ms"), "sessions": ("capture_sessions", "started_ms")}
            name, order = mapping[table]
            rows = db.execute(f"SELECT * FROM {name} ORDER BY {order} DESC,rowid DESC LIMIT ?", (limit,)).fetchall()
        for row in rows:
            item = dict(row)
            if "title" in item and not show_titles:
                item.pop("title")
            elif "title" in item and item.get("at_ms", item.get("start_ms", 0)) < time.time_ns() // 1_000_000 - 7 * 86_400_000:
                item["title"] = None
            print(json.dumps(item, ensure_ascii=False))
    finally:
        db.close()


def content_records(database,limit,show_text,json_output,raw=False):
    db=readonly(database)
    try:
        now=time.time_ns()//1_000_000
        rows=db.execute("SELECT c.*,e.process_name,e.kind,e.device_id,e.platform,CASE WHEN e.at_ms>=? THEN e.title END AS title FROM content_samples c JOIN activity_events e ON e.id=c.event_id WHERE c.expires_ms>? ORDER BY c.captured_ms DESC,c.rowid DESC",(now-7*86_400_000,now))
        groups=[]
        previous=None
        for row in rows:
            item=dict(row)
            # Same event is required: never collapse across a tab/application switch,
            # pause, idle boundary or another session, even if the text is identical.
            key=item['event_id']
            if not json_output and not raw and item['duplicate_of']:
                original=db.execute('SELECT text,status FROM content_samples WHERE id=? AND expires_ms>?',(item['duplicate_of'],now)).fetchone()
                if original:
                    item['text']=original['text']
                    item['status']=original['status']
            if not json_output and not raw and groups and key==previous:
                groups[-1]['sample_count']+=1
                groups[-1]['first_sample_ms']=item['captured_ms']
                groups[-1]['statuses'].add(item['status'])
                groups[-1]['sources'].add(item['source'])
                continue
            if len(groups)>=limit:
                break
            previous=key
            if not json_output:
                item['sample_count']=1
                item['first_sample_ms']=item['captured_ms']
                item['statuses']={item['status']}
                item['sources']={item['source']}
            groups.append(item)
        from datetime import datetime
        for item in groups:
            if not show_text:
                item.pop('text')
            if json_output:
                # ASCII JSON avoids Windows PowerShell 5 pipeline encoding corruption.
                print(json.dumps(item,ensure_ascii=True))
            else:
                stamp=datetime.fromtimestamp(item['captured_ms']/1000).strftime('%m-%d %H:%M:%S')
                if item['sample_count']>1:
                    first=datetime.fromtimestamp(item['first_sample_ms']/1000).strftime('%m-%d %H:%M:%S')
                    stamp=first+' ~ '+datetime.fromtimestamp(item['captured_ms']/1000).strftime('%H:%M:%S')
                label=item['process_name'] or '-'
                if label.casefold()=='chrome.exe':
                    title=item.get('title') or '[title unavailable]'
                    for suffix in (' - Google Chrome',' — Google Chrome'):
                        if title.endswith(suffix):
                            title=title[:-len(suffix)]
                    label+=' | '+title
                print(f"{stamp}  {label}  [{'+'.join(sorted(item['sources']))}/{'+'.join(sorted(item['statuses']))}]")
                if show_text and item.get('text'):
                    print('  '+item['text'])
    finally:
        db.close()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="DayTrace local activity collector and opt-in personal activity review")
    parser.add_argument("--db", type=Path, default=default_database(), help="SQLite path; put this option before the command")
    sub = parser.add_subparsers(dest="command", required=True)
    ui_parser=sub.add_parser('ui', help='Open the daily diary; does not start collection')
    ui_parser.add_argument('--legacy',action='store_true',help='Open the previous grid-style Tk UI for rollback / comparison')
    ui_parser.add_argument('--tk-diary',action='store_true',help='Open the Tk diary shell (pre-Qt) instead of the default Qt shell')
    sub.add_parser('evaluate', help='Run synthetic learning evaluation in a temporary database; no desktop/network')
    start = sub.add_parser("start", help="Explicitly begin collection in this terminal; Ctrl+C stops")
    start.add_argument("--idle-seconds", type=positive, default=300)
    from .preferences import validate_dwell
    start.add_argument('--min-dwell-seconds', type=validate_dwell, help='Minimum page dwell, 0–300 seconds; default uses UI preference (initially 5)')
    start.add_argument("--duration", type=positive, help="Stop automatically after this many seconds")
    start.add_argument("--exclude", action="append", default=[], help="Exclude executable basename or full path; repeatable")
    start.add_argument('--exclude-window',action='append',default=[],help='Exclude window titles containing this text; repeatable')
    start.add_argument('--content',action='store_true',help='Explicitly enable local visible UIA text evidence')
    start.add_argument('--screenshots',action='store_true',help='Enable OCR only with all region permission options')
    start.add_argument('--retain-screenshots',action='store_true',help='Explicitly retain safe permitted-region screenshots for evidence review; never upload')
    start.add_argument('--screenshot-days',type=positive,default=7,help='Screenshot retention, at most 7 days')
    start.add_argument('--ocr-app',help='One permitted executable basename')
    start.add_argument('--ocr-region',help='Explicit safe region x,y,width,height in physical pixels relative to window')
    start.add_argument('--ocr-window-size',help='Expected physical window width,height; resizing invalidates grant')
    start.add_argument('--acknowledge-safe-region',action='store_true',help='Confirm the chosen region contains no sensitive content')
    evidence=sub.add_parser('content',help='View content status; no body printed unless --show-text')
    evidence.add_argument('--limit',type=int,default=30)
    evidence.add_argument('--show-text',action='store_true')
    evidence.add_argument('--json',action='store_true')
    evidence.add_argument('--raw',action='store_true',help='Show individual samples without display grouping; JSON is always ungrouped')
    probe=sub.add_parser('content-doctor',help='Local dependency/UIA/OCR synthetic diagnostic, no desktop capture')
    probe.add_argument('--ocr',action='store_true')
    structure=sub.add_parser('uia-structure',help='Inspect foreground accessibility counts only; no body or image')
    structure.add_argument('--delay',type=positive,default=5)
    structure.add_argument('--check-text',action='store_true',help='Also extract visible text transiently; print only status and character count')
    info=sub.add_parser('window-info',help='After a delay, print foreground app and physical size only; no content or image')
    info.add_argument('--delay',type=positive,default=5)
    for name in ("pause", "resume", "stop", "status", "doctor", "simulate", "prune"):
        sub.add_parser(name)
    show = sub.add_parser("records")
    show.add_argument("--table", choices=("events", "intervals", "sessions", "summary", "browser"), default="intervals")
    show.add_argument("--limit", type=int, default=100)
    show.add_argument("--show-titles", action="store_true", help="Explicitly print saved titles (may contain private information)")
    delete = sub.add_parser("delete", help="Delete all local records only when collector has stopped")
    delete.add_argument("--yes", action="store_true", required=True)
    args = parser.parse_args(argv)
    args.db = args.db.expanduser().resolve()
    try:
        if sys.version_info < (3, 12):
            raise RuntimeError("Use Python 3.12 or newer.")
        if args.command == 'ui':
            if args.legacy:
                from .personalization.ui import launch
            elif getattr(args, 'tk_diary', False):
                from .personalization.diary_ui import launch
            else:
                from .personalization.diary_qt import launch
            launch(args.db)
        elif args.command == 'evaluate':
            from .personalization.evaluate import evaluate
            print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
        elif args.command == "start":
            permit=None
            if args.screenshots:
                if not (args.content and args.ocr_app and args.ocr_region and args.ocr_window_size and args.acknowledge_safe_region):
                    raise RuntimeError('Screenshots require --content, --ocr-app, --ocr-region, --ocr-window-size and --acknowledge-safe-region.')
                region=tuple(map(int,args.ocr_region.split(',')))
                size=tuple(map(int,args.ocr_window_size.split(',')))
                if len(region)!=4 or len(size)!=2 or min(region)<0 or min(region[2:])<=0 or min(size)<=0 or region[0]+region[2]>size[0] or region[1]+region[3]>size[1] or region[2]*region[3]>4_000_000:
                    raise RuntimeError('Invalid OCR region or window dimensions; maximum region is 4 million pixels.')
                permit={'app':args.ocr_app,'region':region,'size':size}
                if args.screenshot_days>7:
                    raise RuntimeError('Screenshot retention must be at most 7 days.')
                if args.retain_screenshots:
                    permit.update(retain=True,days=args.screenshot_days)
                    print(f'LOCAL SCREENSHOT RETENTION | purpose=review | application={args.ocr_app} | region={region} | days={args.screenshot_days:g} | directory={args.db}.screenshots | no upload',flush=True)
            elif args.ocr_app or args.ocr_region or args.ocr_window_size or args.acknowledge_safe_region:
                raise RuntimeError('OCR permission options require explicit --screenshots.')
            if args.retain_screenshots and not args.screenshots:
                raise RuntimeError('Screenshot retention requires independent --screenshots and region permissions.')
            from .service import run
            run(args.db, args.idle_seconds, args.exclude, args.duration,args.content,args.exclude_window,permit,min_dwell_seconds=args.min_dwell_seconds)
        elif args.command=='content':
            if not 1<=args.limit<=100000:
                raise RuntimeError('--limit must be between 1 and 100000')
            content_records(args.db,args.limit,args.show_text,args.json,args.raw)
        elif args.command=='content-doctor':
            from .content.diagnostics import diagnose
            return diagnose(args.ocr)
        elif args.command=='uia-structure':
            if args.delay>60:
                raise RuntimeError('Delay must be at most 60 seconds.')
            from .content.diagnostics import diagnose_window
            return diagnose_window(args.delay,args.check_text)
        elif args.command=='window-info':
            if args.delay>60:
                raise RuntimeError('Window-info delay must be at most 60 seconds.')
            print('Switch to the intended window now. No screenshot will be taken.',flush=True)
            time.sleep(args.delay)
            from .content.desktop import context
            target=context()
            if not target:
                raise RuntimeError('Foreground window is unavailable or excluded.')
            r=target['rect']
            print(json.dumps({'app':target['process'],'width':r[2]-r[0],'height':r[3]-r[1]},ensure_ascii=True))
        elif args.command in ("pause", "resume", "stop"):
            control(args.db, args.command)
        elif args.command == "records":
            if not 1 <= args.limit <= 100000:
                raise RuntimeError("--limit must be between 1 and 100000")
            records(args.db, args.table, args.limit, args.show_titles)
        elif args.command == "status":
            running = args.db.exists() and is_running(args.db)
            print(json.dumps({"collector_running": running, "database_exists": args.db.exists()}))
            if args.db.exists():
                records(args.db, "sessions", 1, False)
                if not running:
                    print("Collector inactive. An unfinished session, if present, is recovered on next start.")
        elif args.command == "doctor":
            from .windows import WindowsSource
            source = WindowsSource()
            try:
                source.start()
                print(json.dumps({"python": sys.version.split()[0], "desktop_accessible": source.api.desktop_available(), "foreground_present": bool(source.api.u.GetForegroundWindow()), "winevent_hooks": source.hook_active, "idle_api_available": source.api.idle_for_ms() >= 0}))
            finally:
                source.close()
        elif args.command == "simulate":
            if args.db == default_database().resolve():
                raise RuntimeError("Use --db with a separate simulation database.")
            from .service import simulate
            simulate(args.db)
        elif args.command == "prune":
            if not args.db.exists():
                raise RuntimeError("Database does not exist.")
            with InstanceLock(args.db):
                repo = Repository(args.db)
                try:
                    repo.cleanup(time.time_ns() // 1_000_000)
                finally:
                    repo.close()
            print("Expired titles and records removed.")
        elif args.command == "delete":
            with InstanceLock(args.db):
                if args.db.exists():
                    repo = Repository(args.db)
                    try:
                        from .storage.screenshots import enabled, cleanup
                        if enabled(repo):
                            with repo.transaction():
                                repo.db.execute('DELETE FROM screenshots')
                            cleanup(repo)
                    finally:
                        repo.close()
                for path in (args.db, Path(str(args.db) + "-wal"), Path(str(args.db) + "-shm")):
                    path.unlink(missing_ok=True)
            print("Local database removed; next start creates an empty database. No physical-erasure claim.")
        return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        # Never print raw SQLite/OS messages that could embed titles or private content.
        if isinstance(exc, RuntimeError):
            print("Error: " + str(exc), file=sys.stderr)
        else:
            print("Error: " + type(exc).__name__ + "; check database path, permissions and schema.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
