"""Independent observer dashboard: existing match logs plus bounded local controls."""
import json
import time
from pathlib import Path

import psutil
from bootstrap import ROOT
from practice_control import read_json
from undead.speed_control import SPEEDS

PROFILES = {'human-fast-expand': '人族 · 一本开矿', 'human-rifle': '人族 · 单矿火枪', 'kfai-human': 'KFAI · 人族'}


class EventTail:
    """Incremental reads preserve split UTF-8/JSON lines; never reread a full match."""
    def __init__(self):
        self.path = None
        self.offset = 0
        self.rest = b''
        self.latest = {}

    def read(self, path):
        if path != self.path or path.stat().st_size < self.offset:
            self.path, self.offset, self.rest, self.latest = path, 0, b'', {}
        with path.open('rb') as stream:
            stream.seek(self.offset)
            data = stream.read(4 * 1024 * 1024)
            self.offset = stream.tell()
        lines = (self.rest + data).split(b'\n')
        self.rest = lines.pop()
        for line in lines:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    self.latest[row.get('event')] = row
            except (ValueError, UnicodeError):
                continue
        return self.latest


def match_settings(path):
    try:
        with path.open('rb') as stream:
            for line in stream.read(65536).splitlines():
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if row.get('event') == 'match_settings':
                    return row.get('settings', {})
    except OSError:
        pass
    return {}


class ObserverBackend:
    def __init__(self, pid):
        from openwar3 import Game
        self.game = Game(pid=pid, observer=True, fair=True)

    def read(self):
        from human_practice import helper
        g = self.game
        s = g.snapshot(max_age=0)
        if s is None or not s.in_game or s.me != 0:
            raise RuntimeError('当前不在 P0 观战对局中')
        r = g.lane.commands([g._w3fast.command('cam_state')])[0]
        cam = g._w3fast.parse_cam_state(r.data) if r.ok else None
        return dict(epoch=s.epoch, clock=s.clock, speed=s.speed_pct,
                    camera=round(cam['fields']['distance']) if cam else None,
                    background=not helper('w3window').game_active(g.pid))

    def set(self, kind, value):
        g = self.game
        if kind == 'speed':
            return bool(g.set_speed(value))
        commands = [g._w3fast.command('cam_field', code=0, x=float(value), y=0.0),
                    g._w3fast.command('cam_field', code=1, x=min(10000.0, max(5000.0, value * 3.0)), y=0.0)]
        return all(r.ok for r in g.lane.commands(commands))

    def close(self):
        self.game.close()


def process_matches(row):
    try:
        p = psutil.Process(row['pid'])
        return p.name().lower() == 'war3-73.exe' and abs(p.create_time() - row['created']) < .01
    except (psutil.Error, KeyError, TypeError):
        return False


class DashboardModel:
    def __init__(self, root=ROOT, backend=ObserverBackend, matches=process_matches, clock=time.monotonic):
        self.artifacts = Path(root) / 'artifacts'
        self.backend_factory, self.matches, self.clock = backend, matches, clock
        self.backend = None
        self.identity = None
        self.token = None
        self.run = None
        self.tail = EventTail()
        self.pending = None
        self.message = ''
        self.scan_at = -100
        self.runs = []
        self.history = []

    def close(self):
        if self.backend:
            self.backend.close()
        self.backend = self.identity = self.token = None
        self.pending = None

    def scan(self):
        if self.clock() - self.scan_at < 3:
            return
        self.scan_at = self.clock()
        self.runs, self.history = [], []
        for p in sorted(self.artifacts.glob('20*/events.jsonl'), reverse=True)[:100]:
            settings = match_settings(p)
            if settings.get('mode') != 'bot_vs_bot':
                continue
            self.runs.append((p.parent, settings))
            result = read_json(p.parent / 'result.json')
            if result:
                self.history.append(dict(run=p.parent.name, profile=settings.get('opponent_profile'),
                                         result=result.get('result'), reason=result.get('reason'),
                                         seconds=result.get('game_seconds')))

    def current_process(self):
        s = read_json(self.artifacts / 'session.json')
        if s.get('closed'):
            return None
        rows = [r for r in s.get('processes', []) if r.get('name', '').lower() == 'war3-73.exe' and self.matches(r)]
        return rows[0] if len(rows) == 1 else None

    def poll(self):
        self.scan()
        state = dict(status='等待观战对局', token=None, history=self.history[:8], message=self.message)
        row = self.current_process()
        if row is None:
            self.close()
            return state
        identity = (row['pid'], row['created'])
        # The run directory is created before launching. Restrict binding to this launch.
        candidates = [(p, s) for p, s in self.runs if not (p / 'result.json').exists()
                      and 0 <= row['created'] - (p / 'source-manifest.json').stat().st_mtime <= 150]
        if len(candidates) != 1:
            self.close()
            state['status'] = '等待确认本局身份'
            return state
        run, settings = candidates[0]
        if identity != self.identity or run != self.run:
            self.close()
            self.backend = self.backend_factory(row['pid'])
            self.identity, self.run = identity, run
            self.message = ''
        live = self.backend.read()
        token = (*identity, live['epoch'], run.name)
        if self.token is not None and token != self.token:
            self.close()
            raise RuntimeError('对局已切换，请等待重新连接')
        self.token = token
        if self.pending:
            kind, value, started = self.pending
            if live[kind] == value:
                self.message = '已生效'
                self.audit(kind, value, 'confirmed', live)
                self.pending = None
            elif self.clock() - started > 5:
                self.message = '尚未确认生效；请切回游戏后重试'
                self.audit(kind, value, 'unconfirmed', live)
                self.pending = None
        events = self.tail.read(run / 'events.jsonl')
        state.update(live, token=token, run=run.name, profile=settings.get('opponent_profile'),
                     status='失焦暂停 · 切回游戏继续' if live['background'] else '对局进行中',
                     dayuan=events.get('summary', {}), opponent=events.get('human_summary', {}),
                     decision=events.get('decision', {}).get('actual', '—'),
                     pending=self.pending, message=self.message)
        return state

    def audit(self, kind, value, status, live):
        with (self.run / 'spectator-controls.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(wall_time=time.time(), token=self.token, kind=kind,
                                         value=value, status=status, clock=live.get('clock'),
                                         actual=live.get(kind))) + '\n')

    def request(self, token, kind, value):
        if kind not in {'speed', 'camera'} or type(value) is not int:
            raise ValueError('无效的观战设置')
        if (kind == 'speed' and value not in SPEEDS) or (kind == 'camera' and not 500 <= value <= 6000):
            raise ValueError('设置超出支持范围')
        live = self.poll()
        if token is None or token != live.get('token'):
            raise RuntimeError('对局已结束或切换，请刷新后重试')
        if self.pending:
            raise RuntimeError('上一项设置正在确认，请稍候')
        accepted = self.backend.set(kind, value)
        self.audit(kind, value, 'accepted' if accepted else 'rejected', live)
        if not accepted:
            raise RuntimeError('游戏尚未接受设置；请切回游戏后重试')
        self.pending = (kind, value, self.clock())
        self.message = '已发送，等待游戏读回确认'
        return self.poll()
