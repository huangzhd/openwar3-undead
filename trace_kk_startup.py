"""Bounded, read-only KK/game startup observation. No game commands or injection."""
import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import psutil

from bridge_diagnostics import FILE_MAP_READ, mapping_access

GAME = re.compile(r'^(war3(?:-\d+)?|warcraft iii)\.exe$', re.I)
PLATFORM_DIR = os.path.normcase(r'C:\Program Files (x86)\kkduizhan')
SECRET = re.compile(r'pass(?:word|wd)?|token|ticket|secret|auth|cookie|session|credential', re.I)


def safe_args(args):
    result = []
    hide_next = False
    for arg in args:
        if hide_next:
            result.append('<redacted>'); hide_next = False; continue
        if SECRET.search(arg):
            key, sep, _ = arg.partition('=')
            if sep:
                result.append(key + '=<redacted>')
            else:
                result.append(arg if arg.startswith(('-', '/')) else '<redacted>')
                hide_next = arg.startswith(('-', '/'))
        else:
            result.append(arg)
    return result


def now():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def platform_path(exe):
    try:
        return os.path.commonpath([PLATFORM_DIR, os.path.normcase(exe)]) == PLATFORM_DIR
    except ValueError:
        return False


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def game_liveness(row):
    """AccessDenied is unknown, never evidence of process exit."""
    try:
        p = psutil.Process(row['pid'])
        return 'alive' if p.create_time() == row['create_time'] else 'pid_reused'
    except psutil.NoSuchProcess:
        return 'exited'
    except psutil.AccessDenied:
        return 'unknown'


def sample_game(row, emit, seen_images):
    key = (row['pid'], row['create_time'])
    if game_liveness(row) != 'alive':
        emit('game_sample_identity_unavailable', pid=row['pid'])
        return
    # Module enumeration and IPC have independent permissions; one failing must
    # not suppress the other or be mistaken for game exit.
    try:
        paths = sorted({m.path for m in psutil.Process(row['pid']).memory_maps()
                        if m.path.lower().endswith(('.dll', '.exe'))})
        if paths != seen_images.get(key):
            previous = set(seen_images.get(key, [])); seen_images[key] = paths
            emit('mapped_images', pid=row['pid'], paths=paths, added=sorted(set(paths)-previous))
    except psutil.Error as exc:
        emit('module_sample_error', pid=row['pid'], error=type(exc).__name__)
    if game_liveness(row) == 'alive':
        bridge = mapping_access(f"Local\\War3World_{row['pid']}", FILE_MAP_READ)
        emit('bridge_access', pid=row['pid'], **bridge)


def run(out, wait_seconds=600, capture_seconds=180):
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    deadline = start + wait_seconds
    observed = {}; related = {}; seen_images = {}; sample_due = {}; games = {}
    first_game = None; last_status = 0
    state = dict(observer_pid=os.getpid(), observer_created=psutil.Process().create_time(),
                 started=now(), state='waiting_for_game', game_pids=[],
                 wait_seconds=wait_seconds, capture_seconds=capture_seconds,
                 interval_seconds=0.25, game_commands_sent=False)
    write_json(out/'status.json', state)
    with (out/'events.jsonl').open('w', encoding='utf-8', buffering=1) as stream:
        def emit(event, **data):
            stream.write(json.dumps(dict(at=now(), event=event, **data), ensure_ascii=False)+'\n')

        emit('observer_started', **state)
        reason = 'wait_timeout'
        try:
            while time.monotonic() < deadline:
                if (out/'STOP').exists():
                    reason = 'observer_stop_requested'; break
                rows = {}
                for proc in psutil.process_iter(['pid','ppid','name','exe','create_time']):
                    row = proc.info
                    if row['create_time'] is None:
                        continue
                    key = (row['pid'], row['create_time'])
                    rows[row['pid']] = row
                    # A short-lived intermediate parent may exit before the game is sampled.
                    observed[key] = row
                for row in rows.values():
                    key = (row['pid'], row['create_time'])
                    is_game = bool(GAME.fullmatch(row['name'] or ''))
                    is_related = is_game or platform_path(row['exe'] or '')
                    if not is_related:
                        parent = rows.get(row['ppid'])
                        is_related = parent is not None and (parent['pid'],parent['create_time']) in related
                    if not is_related:
                        continue
                    if key not in related:
                        related[key] = row
                        detail = dict(row)
                        # Do not collect account-bearing platform helper command lines.
                        if is_game:
                            try:
                                proc = psutil.Process(row['pid'])
                                if proc.create_time() != row['create_time']:
                                    continue
                                detail['cmdline'] = safe_args(proc.cmdline())
                                detail['cwd'] = proc.cwd()
                            except psutil.Error as exc:
                                detail['metadata_error'] = type(exc).__name__
                        ancestors = []; child = row
                        for _ in range(8):
                            matches = [p for p in observed.values() if p['pid']==child['ppid'] and p['create_time']<=child['create_time']]
                            if not matches: break
                            parent = max(matches, key=lambda p:p['create_time'])
                            if parent in ancestors: break
                            ancestors.append(parent); child = parent
                        emit('game_observed' if is_game else 'related_process_observed', process=detail, ancestors=ancestors)
                        if is_game:
                            games[key] = row
                            if first_game is None:
                                first_game = time.monotonic(); deadline = first_game + capture_seconds
                                state['state'] = 'capturing_game'
                    if not is_game or time.monotonic() < sample_due.get(key, 0):
                        continue
                    sample_due[key] = time.monotonic() + 3
                    sample_game(row, emit, seen_images)
                liveness = {row['pid']:game_liveness(row) for row in games.values()}
                live_games = [pid for pid,status in liveness.items() if status=='alive']
                uncertain_games = [pid for pid,status in liveness.items() if status=='unknown']
                state['game_pids'] = live_games
                state['uncertain_game_pids'] = uncertain_games
                if first_game is not None and not live_games and not uncertain_games:
                    reason = 'observed_game_exited'; break
                if time.monotonic()-last_status >= 2:
                    state['updated'] = now(); write_json(out/'status.json', state); last_status = time.monotonic()
                time.sleep(0.25)
            else:
                reason = 'capture_complete' if first_game is not None else 'wait_timeout'
        except Exception as exc:
            reason = 'observer_error'; emit('observer_error', error=repr(exc))
        finally:
            state.update(state='finished', reason=reason, updated=now(),
                         observed_game_pids=sorted({key[0] for key in games}),
                         elapsed_seconds=round(time.monotonic()-start, 2))
            emit('observer_finished', **state); write_json(out/'status.json', state)
    return 1 if reason=='observer_error' else 0


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--wait-seconds', type=float, default=600)
    parser.add_argument('--capture-seconds', type=float, default=180)
    args = parser.parse_args()
    if args.wait_seconds <= 0 or args.capture_seconds <= 0:
        parser.error('durations must be positive')
    raise SystemExit(run(args.out, args.wait_seconds, args.capture_seconds))
