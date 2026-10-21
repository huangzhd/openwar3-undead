"""One bounded UD training round, separate from the melee runner and matrix."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import time
import traceback
from types import SimpleNamespace

from bootstrap import ROOT, UPSTREAM
import farm
from game_preferences import apply_defaults, confirm_ally_colors
from machine_start import active_processes
from session import Session
from training_map import build, digest, MATCHUPS, VERSION
from undead.game_view import Game
from undead.controller import Controller, ground_attack_range
from undead.policy import Action
from undead.structures import is_structure
from undead.targeting import can_engage, in_weapon_range

STOP = ROOT / 'artifacts/TRAINING_STOP'


def install_map(path, manifest):
    config = json.loads((UPSTREAM / 'openwar3.json').read_text(encoding='utf-8'))
    installed = Path(config['game_dir']) / 'Maps/OpenWar3Training' / path.name
    installed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, installed)
    if digest(installed.read_bytes()) != manifest['map_sha256']:
        raise ValueError('Installed training map fingerprint mismatch')
    return installed


def board_state(g):
    board = g.jass.PlayerGetLeaderboard(g.jass.Player(0))
    return g.jass.LeaderboardGetLabelText(board) if board else ''


class TrainingSession(Session):
    def __init__(self, path, manifest, speed):
        super().__init__(speed, MATCHUPS[manifest['matchup']], 3)
        self.training_path, self.manifest = path, manifest

    def start(self):
        if active_processes():
            raise RuntimeError('Existing game/session blocks training launch')
        if digest(self.training_path.read_bytes()) != self.manifest['map_sha256']:
            raise ValueError('Training map changed before launch')
        apply_defaults()
        args = farm.parse_args(['--first', '72', '--count', '72', '--race', '3',
                               '--enemy-race', str(self.enemy_race), '--difficulty', '3',
                               '--speed', str(self.speed), '--no-director',
                               '--window', '30,30,1024,768'])
        args.map = str(self.training_path)
        launcher = farm.Farm(args)
        base = launcher.base()
        self.settings = farm.next_game(farm.w3paths.inst_dir(72), base, launcher.maps_dir())
        if self.settings != base:
            raise RuntimeError('Instance 72 next_game.json overrides training settings')
        self.remember(launcher.launch(72))
        deadline = time.monotonic() + 120
        last_error = ''
        while time.monotonic() < deadline:
            if STOP.exists():
                raise RuntimeError('Training stop requested during launch')
            if not self.matches(self.owned[0]):
                raise RuntimeError('Training launcher exited: ' + farm.read_text(farm.out_path(72))[-1800:])
            pid = farm.war3_pid(farm.read_text(farm.out_path(72)))
            if pid and not any(row['pid'] == pid for row in self.owned):
                self.remember(pid)
            if pid and self.game is None:
                try:
                    self.game = Game(pid=pid, fair=True)
                except Exception as exc:
                    last_error = repr(exc)
            if self.game:
                snap = self.game.snapshot(max_age=0)
                if snap and snap.in_game and snap.clock > 1:
                    if self.game.me() != 0:
                        raise RuntimeError('Training requires player slot 0')
                    j = self.game.jass
                    controllers = [j.GetPlayerController(j.Player(i)) for i in (0, 1)]
                    if controllers != [0, 1]:
                        raise RuntimeError('Expected human-controlled UD slot 0 and computer slot 1')
                    state = board_state(self.game)
                    if state.startswith('OWT:') and self.game.my_heroes():
                        self.settings.update(adapter_version=VERSION, map_sha256=self.manifest['map_sha256'],
                                             controllers=controllers, fair=True, board=state,
                                             ally_color=confirm_ally_colors(pid))
                        return self.game
            time.sleep(.2)
        raise TimeoutError('Training not ready within 120 seconds: ' + last_error)


class TrainingController(Controller):
    """Reuse combat components without economy, creeping, shopping or recruitment."""
    def __init__(self, g, log, race):
        super().__init__(g, log, race)
        self.action = self.requested = Action.ATTACK
        self.attack_committed = True
        self.situation.tier = 3
        self.home = SimpleNamespace(x=-1792., y=320.)
        self.enemy_main = (832., 384.)  # Public static start, not hidden enemy units.

    def tick(self):
        g = self.g
        now = g.clock()
        army = [u for u in g.my_units() if u.alive and not is_structure(u)
                and u.type not in {'uaco', 'hpea', 'opeo', 'ewsp'}]
        if not army:
            return
        heroes = g.my_heroes()
        g.observe_coil(heroes, now, self.log)
        self.skills(now)
        foes = [u for u in g.enemies() if can_engage(u)]
        self.player_contact = self.battle_enemies = foes
        self.creep_strength = army
        self.situation.clock = now
        mp = g.map()
        dk = next((h for h in heroes if h.type == 'Udea'), None)
        def target_of(u):
            target = g.current_target(u)
            return target.handle if target else None
        pulls = self.micro.plan(army, foes, now, target_of, g.path_distance,
                                mp.walkable if mp else lambda *p: False,
                                (self.home.x, self.home.y), lambda u: ground_attack_range(u.type),
                                coil_ready=self.rescue_coil_ready(dk, now))
        self.shield_moves = self.shields.plan(army, foes, now, g.buffs,
                                             mp.walkable if mp else lambda *p: False, g.path_distance)
        pulls.update(self.shield_moves)
        self.combat_spells(army, foes, now, set(pulls))
        self.frost_armor(army, foes, now)
        self.destroyer.tick(self, army, foes, now, set(pulls))
        self.statue_support.tick(self, army, foes, now, set(pulls))
        for u in army:
            if u.handle in pulls:
                self.go_raw([u], pulls[u.handle], now)
        fighting = [u for u in army if u.handle not in pulls]
        self.fight(fighting, foes, now)
        for u in fighting:
            if u.type == 'uobs' or now < self.cast_until.get(u.handle, 0):
                continue
            # Preserve active attacks; approach only when outside weapon range.
            if g.current_target(u) or any(in_weapon_range(g, u, e) for e in foes):
                continue
            target = min(foes, key=lambda e: g.dist(u, e)) if foes else self.enemy_main
            if self.due(('training_advance', u.handle), now, 2):
                x, y = (target.x, target.y) if hasattr(target, 'x') else target
                receipt = g.attack_move(u, x, y)
                self.log('training_advance', clock=now, handle=u.handle, accepted=bool(receipt))


def unit_row(g, u):
    target = g.current_target(u)
    return dict(handle=u.handle, type=u.type, x=round(u.x, 2), y=round(u.y, 2),
                hp=round(u.hp, 2), mana=round(u.mana, 2),
                target=target.handle if target else None)


def run(args):
    if active_processes():
        raise RuntimeError('An active game/session blocks training')
    path, manifest = build(args.matchup, args.level, args.mode, download=True)
    out = ROOT / 'artifacts' / ('training-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / 'training.py', ROOT / 'training_map.py', ROOT / 'session.py',
               ROOT / 'game_preferences.py', *sorted((ROOT / 'undead').glob('*.py'))]
    hashes = {}
    for src in sources:
        name = src.relative_to(ROOT).as_posix()
        dest = out / 'source' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        hashes[name] = digest(src.read_bytes())
    (out / 'source-manifest.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    (out / 'map-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    if STOP.exists():
        STOP.unlink()  # Only an explicit train command consumes this training stop.
    session = TrainingSession(install_map(path, manifest), manifest, args.speed)
    result = dict(version=VERSION, melee_rules='0.1.174', result='error', reason='not_started',
                  selection=manifest, matrix_eligible=False, probe=args.probe,
                  max_game_seconds=args.seconds, max_wall_seconds=args.wall_seconds)
    started = time.monotonic()
    with (out / 'events.jsonl').open('w', encoding='utf-8') as stream:
        def log(event, **data):
            stream.write(json.dumps(dict(event=event, **data), ensure_ascii=False) + '\n')
            stream.flush()
        try:
            g = session.start()
            result['launch_settings'] = session.settings
            initial = [unit_row(g, u) for u in g.my_units()]
            result['initial_units'] = dict(Counter(u['type'] for u in initial))
            log('training_initial', clock=g.clock(), units=initial)
            bot = TrainingController(g, log, MATCHUPS[args.matchup])
            start_clock = g.clock()
            sampled = -100
            last_clock, moved = None, time.monotonic()
            while True:
                snap = g.snapshot(max_age=0)
                if snap is None or not snap.in_game:
                    raise RuntimeError('Training snapshot missing or game ended without map result')
                state = board_state(g)
                if state.startswith('OWT:result:'):
                    winner = int(state.rsplit(':', 1)[1]) - 1
                    if winner not in (0, 1):
                        raise RuntimeError('Invalid map winner')
                    result.update(result='win' if winner == g.me() else 'loss',
                                  reason='original_map_round_result', winner_slot=winner)
                    break
                if STOP.exists():
                    result.update(result='aborted', reason='training_stop'); break
                if time.monotonic() - started >= args.wall_seconds:
                    result.update(result='timeout', reason='wall_time_limit'); break
                if snap.clock - start_clock >= args.seconds:
                    result.update(result='probe_complete' if args.probe else 'timeout',
                                  reason='bounded_integration_probe' if args.probe else 'game_time_limit'); break
                if snap.clock == last_clock:
                    if time.monotonic() - moved > 15:
                        raise RuntimeError('Training clock stalled for 15 wall seconds')
                    time.sleep(.2); continue
                last_clock, moved = snap.clock, time.monotonic()
                bot.observe_events(g.events())
                # Native countdown owns the enemy force until it is released.
                if state == 'OWT:battle':
                    bot.tick()
                elif state == 'OWT:waiting':
                    bot.skills(snap.clock)
                else:
                    raise RuntimeError('Unexpected training scoreboard: ' + state)
                if snap.clock - sampled >= 1:
                    sampled = snap.clock
                    log('training_sample', clock=snap.clock, state=state,
                        own=[unit_row(g, u) for u in g.my_units()],
                        visible_enemies=[unit_row(g, u) for u in g.enemies()])
                time.sleep(.2)
            result['game_seconds'] = g.clock()
            result['final_units'] = dict(Counter(u.type for u in g.my_units()))
        except Exception as exc:
            result.update(result='error', reason=repr(exc))
            traceback.print_exc()
        finally:
            try:
                session.stop()
                result['cleanup_confirmed'] = True
            except Exception as exc:
                result.update(cleanup_confirmed=False, cleanup_error=repr(exc))
            result['source_unchanged'] = all(digest((ROOT / name).read_bytes()) == h for name, h in hashes.items())
            result['wall_seconds'] = round(time.monotonic() - started, 2)
            result['artifact_dir'] = str(out)
            (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['result'] in ('error', 'timeout') or not result['cleanup_confirmed'] else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'play', 'stop'))
    parser.add_argument('--matchup', choices=tuple(MATCHUPS), default='orc')
    parser.add_argument('--level', type=int, choices=range(1, 11), default=2)
    parser.add_argument('--mode', choices=('easy', 'hard'), default='easy')
    parser.add_argument('--speed', type=int, choices=(25, 50, 100, 200, 400), default=100)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--wall-seconds', type=int, default=240)
    parser.add_argument('--probe', action='store_true', help='Time-limited integration check, not a round pass')
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 1800 or not 120 <= args.wall_seconds <= 2100:
        parser.error('seconds must be 1..1800; wall-seconds 120..2100')
    if args.command == 'stop':
        STOP.parent.mkdir(parents=True, exist_ok=True)
        STOP.write_text('user requested training stop', encoding='utf-8')
        return 0
    if args.command == 'check':
        if active_processes():
            raise RuntimeError('Cannot rebuild training map while a game is active')
        print(json.dumps(build(args.matchup, args.level, args.mode, download=True)[1], indent=2))
        return 0
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
