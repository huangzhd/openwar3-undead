"""One bounded UD training round, separate from the melee runner and matrix."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import time
import traceback
from types import SimpleNamespace
from math import hypot

from bootstrap import ROOT, UPSTREAM
import farm
from game_preferences import apply_defaults, confirm_ally_colors
from machine_start import active_processes
from session import Session
from training_map import build, digest, MATCHUPS, VERSION
import training_control
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


def board_signal(source):
    """Read the map-published marker from our own public resource snapshot."""
    if hasattr(source, 'resources'):
        resources = source.resources()
        if resources is None:
            raise RuntimeError('Own training resources unavailable')
        state = resources['lumber']
    else:
        # Compatibility for standalone audit fixtures; live play uses the
        # fair snapshot, avoiding a blocking JASS call every frame.
        j = source.jass
        state = j.GetPlayerState(j.Player(0), j.ConvertPlayerState(1))
    if 100 <= state < 200:
        return 1, state - 100
    # The pinned countdown calls MeleeStartingResources after Main marks
    # waiting; it replaces the small marker with the normal 500 lumber.
    if state == 500:
        return 1, None
    if state not in (0, 1, 2, 3, 4, 10, 11, 12, 20):
        raise RuntimeError('Unexpected training stage: ' + repr(state))
    return state, None


def board_state(audit):
    return board_signal(audit)[0]


class TrainingSession(Session):
    def __init__(self, path, manifest, speed):
        super().__init__(speed, MATCHUPS[manifest['matchup']], 3)
        self.training_path, self.manifest = path, manifest
        self.audit = None

    def stop(self):
        try:
            if self.audit is not None:
                self.audit.close()
                self.audit = None
        finally:
            super().stop()

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
        deadline = time.monotonic() + getattr(self, 'startup_seconds', 120)
        last_error = ''
        zero_since, pressed_at = None, 0.
        last_stage = None
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
                now = time.monotonic()
                if snap and snap.in_game and not snap.clock:
                    zero_since = zero_since or now
                    if now - zero_since > 3 and now - pressed_at > 5:
                        pressed_at = now
                        if self.game.press_to_continue():
                            print(json.dumps({'event': 'training_loading_continued', 'pid': pid}), flush=True)
                else:
                    zero_since = None
                if snap and snap.in_game and snap.clock > 1:
                    if self.game.me() != 0:
                        raise RuntimeError('Training requires player slot 0')
                    if self.audit is None:
                        self.audit = Game(pid=pid, fair=False)
                    j = self.audit.jass
                    controllers = [j.GetPlayerController(j.Player(i)) for i in (0, 1)]
                    if controllers != [0, 1]:
                        raise RuntimeError('Expected human-controlled UD slot 0 and computer slot 1')
                    state = board_state(self.game)
                    if state != last_stage:
                        print(json.dumps({'event': 'training_startup_stage', 'stage': state,
                                          'clock': snap.clock, 'own_heroes': len(self.game.my_heroes())}), flush=True)
                        last_stage = state
                    if state in (1, 2, 3, 4) and self.game.my_heroes():
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
        # Arena waypoints are public terrain positions. After losing sight of the
        # last foe, search for survivors instead of returning to the start.
        self.last_foe_position = None
        self.search_route = []
        self.search_index = 0
        self.search_since = None
        self.start_potion_since = None

    def search_target(self, army, foes, now):
        if foes:
            # On the final contact this is the last visible opponent, even if
            # it survives by running out of sight.
            last = min(foes, key=lambda u: u.hp)
            self.last_foe_position = (last.x, last.y)
            self.search_route = []
            self.search_since = None
            return None
        if not self.search_route:
            self.search_route = [self.last_foe_position or self.enemy_main,
                                 (320., 160.), (1600., 384.), (4200., 1800.),
                                 (-1600., 160.), (-4700., 1800.),
                                 (-2800., -900.), (0., -900.), (3000., -900.)]
            self.search_index = 0
            self.search_since = now
            self.log('training_survivor_search_started', clock=now,
                     last_seen=self.last_foe_position)
        point = self.search_route[self.search_index]
        mobile = [u for u in army if u.type not in {'uobs', 'ubsp'}] or army
        reached = any(hypot(u.x-point[0], u.y-point[1]) < 320 for u in mobile)
        if reached or now-self.search_since > 28:
            self.search_index = (self.search_index + 1) % len(self.search_route)
            self.search_since = now
            point = self.search_route[self.search_index]
            self.log('training_survivor_search_waypoint', clock=now,
                     index=self.search_index, point=point,
                     reason='reached' if reached else 'time_budget')
        return point


    def collect_start_potion(self,now,army,foes,blocked=()):
        """Arena-only opening pickup; never send a hero through a live fight."""
        if not hasattr(self.g,'items_on_ground'):return set()
        if self.start_potion_since is None:self.start_potion_since=now
        if now-self.start_potion_since>20:
            self.loot.pending=None
            return set()
        available=[u for u in army if u.handle not in blocked and now>=self.cast_until.get(u.handle,0)]
        # Both item codes come from the public item catalogue. Ordinary melee
        # keeps its normal drop policy; only this adapter requests this filter.
        pickup=self.loot.tick(self.g,available,foes,now,self.g.my_heroes(),allowed_codes={'phea','pghe'})
        return {pickup[0].handle} if pickup else set()

    def prepare(self,now):
        army=[u for u in self.g.my_units() if u.alive and not is_structure(u)]
        self.equipment.tick(self.g,army,self.g.enemies(),now,self.cast_until,potions_only=True)
        picking=self.collect_start_potion(now,army,self.g.enemies())
        return self.prepare_battle(now,army=army,blocked=picking)

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
        self.observe_rod_corpses([*army, *g.enemies()], now)
        self.observe_rod_skeletons(now)
        foes = [u for u in g.enemies() if can_engage(u)]
        burrowing=self.fiend_burrow.tick(self,[u for u in army if u.type in {'ucry','ucrm'}],heroes,foes,now)
        self.micro.previous-=burrowing
        army=[u for u in army if u.type!='ucrm' and u.handle not in burrowing]
        self.equipment.tick(g,heroes,foes,now,self.cast_until,potions_only=True)
        search_point = self.search_target(army, foes, now)
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
                                coil_ready=self.rescue_coil_ready(dk, now),
                                aggressive_battle=bool(foes))
        self.shield_moves = self.shields.plan(army, foes, now, g.buffs,
                                             mp.walkable if mp else lambda *p: False, g.path_distance)
        pulls.update(self.shield_moves)
        self.consumables.tick(g, army, foes, now, self.cast_until,
                              attacking=True, urgent={u.handle for u in heroes if u.hp/u.hp_max <= .25})
        picking=self.collect_start_potion(now,army,foes,set(pulls))
        self.battle_actions(army, foes, now, pulls,blocked=picking,search_point=search_point)
        self.frost_armor([u for u in army if u.handle not in picking], foes, now)
        self.statue_support.tick(self, army, foes, now, set(pulls))
        for u in army:
            if u.handle in pulls:
                self.go_raw([u], pulls[u.handle], now)
        fighting = [u for u in army if u.handle not in pulls and u.handle not in picking]
        self.engage_battle(fighting, foes, now)
        for hero in heroes:
            if hero.handle in picking or hero.type not in {'Udea', 'Ulic'} or now < self.cast_until.get(hero.handle, 0):
                continue
            bag = g.inventory(hero) or []
            if 'rnec' in bag:
                self.maintain_skeletons(hero, bag.index('rnec'), now)
        for u in fighting if not foes else ():
            if (u.type in {'uobs','ubsp'} or u.handle in self.battle_focus_handles or
                    u.handle in self.battle_formation.pending or now < self.cast_until.get(u.handle, 0)):
                continue
            # Preserve active attacks; approach only when outside weapon range.
            if g.current_target(u) or any(in_weapon_range(g, u, e) for e in foes):
                continue
            target = min(foes, key=lambda e: g.dist(u, e)) if foes else search_point
            if self.due(('training_advance', u.handle), now, 2):
                x, y = (target.x, target.y) if hasattr(target, 'x') else target
                receipt = g.attack_move(u, x, y)
                self.log('training_advance', clock=now, handle=u.handle, accepted=bool(receipt))


def unit_row(g, u):
    target = g.current_target(u)
    row=dict(handle=u.handle, type=u.type, x=round(u.x, 2), y=round(u.y, 2),
                hp=round(u.hp, 2), mana=round(u.mana, 2),
                target=target.handle if target else None)
    if u.is_hero:
        row['has_detail']=getattr(u,'has_detail',False)
        row['buffs']=sorted(g.buffs(u)) if row['has_detail'] else None
        if u.owner==g.me():row['inventory']=g.inventory(u)
    return row


def contact_reason(g, own, foes):
    """Use fair observations when the map's countdown marker is overwritten."""
    handles = {u.handle for u in own if u.alive and not is_structure(u)}
    if any((target := g.current_target(e)) is not None and target.handle in handles
           for e in foes):
        return 'enemy_targeting_army'
    if any(u.alive and not is_structure(u) and u.hp < u.hp_max - 1 for u in own):
        return 'army_took_damage'
    return None


def run(args, control_id=None, round_no=1):
    if active_processes():
        raise RuntimeError('An active game/session blocks training')
    path, manifest = build(args.matchup, args.level, args.mode, download=True)
    out = ROOT / 'artifacts' / ('training-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / 'training.py', ROOT / 'training_map.py', ROOT / 'training_control.py', ROOT / 'session.py',
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
    session.startup_seconds = 45 if args.probe else 120
    result = dict(version=VERSION, melee_rules='0.1.174', result='error', reason='not_started',
                  selection=manifest, matrix_eligible=False, probe=args.probe,
                  max_game_seconds=args.seconds, max_wall_seconds=args.wall_seconds,
                  training_attempt=round_no)
    started = time.monotonic()
    with (out / 'events.jsonl').open('w', encoding='utf-8') as stream:
        def log(event, **data):
            stream.write(json.dumps(dict(event=event, **data), ensure_ascii=False) + '\n')
            stream.flush()
        try:
            g = session.start()
            if control_id:
                training_control.status(control_id, phase='running', round=round_no)
            result['launch_settings'] = session.settings
            initial = [unit_row(g, u) for u in g.my_units()]
            result['initial_units'] = dict(Counter(u['type'] for u in initial))
            log('training_initial', clock=g.clock(), units=initial)
            bot = TrainingController(g, log, MATCHUPS[args.matchup])
            start_clock = g.clock()
            sampled = -100
            last_clock, moved = None, time.monotonic()
            combat_started = False
            last_enemy_clock, wipe_since = -100, None
            last_enemy_count = None
            while True:
                snap = g.snapshot(max_age=0)
                if snap is None or not snap.in_game:
                    raise RuntimeError('Training snapshot missing or game ended without map result')
                state, enemy_count = board_signal(g)
                if enemy_count != last_enemy_count:
                    log('training_map_enemy_count', clock=snap.clock,
                        living_nonstructures=enemy_count)
                    last_enemy_count = enemy_count
                if state in (3, 4):
                    winner = state - 3
                    result.update(result='win' if winner == g.me() else 'loss',
                                  reason='original_map_round_result', winner_slot=winner)
                    break
                command = training_control.take(control_id) if control_id else None
                if command:
                    action = command['action']
                    outcome = {'forfeit': 'forfeit', 'restart': 'restart_requested',
                               'switch': 'selection_requested'}[action]
                    result.update(result=outcome, reason='user_panel_' + action)
                    if action == 'switch':
                        result['next_selection'] = command['selection']
                    log('training_panel_command', clock=snap.clock, action=action,
                        selection=command.get('selection'))
                    break
                own = g.my_units()
                foes = g.enemies()
                if foes:
                    last_enemy_clock = snap.clock
                if combat_started and not own and snap.clock-last_enemy_clock < 15:
                    wipe_since = wipe_since or snap.clock
                    if snap.clock-wipe_since >= 3:
                        result.update(result='loss', reason='fair_army_wiped_map_signal_missing',
                                      winner_slot=1, result_source='fair_observation')
                        log('training_army_wiped', clock=snap.clock,
                            last_enemy_seen=last_enemy_clock, map_state=state)
                        break
                else:
                    wipe_since = None
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
                reason = contact_reason(g, own, foes) if state == 1 and not combat_started else None
                if state == 2 or reason:
                    if not combat_started:
                        combat_started = True
                        log('training_combat_engaged', clock=snap.clock,
                            signal='map_stage' if state == 2 else reason)
                # The original countdown resets lumber and can erase stage 2.
                # Once actual contact is visible, keep controlling the round.
                if combat_started:
                    bot.tick()
                elif state == 1:
                    bot.skills(snap.clock)
                    bot.prepare(snap.clock)
                else:
                    raise RuntimeError('Unexpected training scoreboard: ' + state)
                if snap.clock - sampled >= 1:
                    sampled = snap.clock
                    log('training_sample', clock=snap.clock, state=state,
                        own=[unit_row(g, u) for u in own],
                        visible_enemies=[unit_row(g, u) for u in foes])
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
    return result


def play(args):
    if args.probe:
        result = run(args)
        return 1 if result['result'] in ('error', 'timeout') or not result['cleanup_confirmed'] else 0
    session_id = training_control.begin(dict(matchup=args.matchup, level=args.level, mode=args.mode),
                                        speed=args.speed, seconds=args.seconds,
                                        wall_seconds=args.wall_seconds)
    try:
        control = training_control.launch(session_id)
        print(json.dumps({'event': 'training_panel_opened', 'pid': control.pid if control else None,
                          'status': str(training_control.STATUS)}), flush=True)
    except Exception as exc:
        print(json.dumps({'event': 'training_panel_launch_failed', 'reason': repr(exc),
                          'manual_command': 'training.py panel'}), flush=True)
    attempt = 1
    try:
        while True:
            training_control.status(session_id, phase='loading', round=attempt, result=None)
            result = run(args, session_id, attempt)
            if result['result'] in ('restart_requested', 'selection_requested') and result['cleanup_confirmed']:
                if result['result'] == 'selection_requested':
                    selection = result['next_selection']
                    args.matchup, args.level, args.mode = (selection['matchup'],
                                                           selection['level'], selection['mode'])
                    training_control.status(session_id, selection=selection)
                attempt += 1
                training_control.status(session_id, phase='restarting', result=result['result'])
                continue
            training_control.status(session_id, phase='finished', result=result['result'],
                                    artifact_dir=result['artifact_dir'])
            return 1 if result['result'] in ('error', 'timeout') or not result['cleanup_confirmed'] else 0
    except Exception as exc:
        training_control.status(session_id, phase='finished', result='error', reason=repr(exc))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'play', 'stop', 'panel'))
    parser.add_argument('--matchup', choices=tuple(MATCHUPS), default='orc')
    parser.add_argument('--level', type=int, choices=range(1, 11), default=2)
    parser.add_argument('--mode', choices=('easy', 'hard'), default='easy')
    parser.add_argument('--speed', type=int, choices=(25, 50, 100, 200, 400), default=100)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--wall-seconds', type=int, default=240)
    parser.add_argument('--probe', action='store_true', help='Time-limited integration check, not a round pass')
    parser.add_argument('--control-id', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 1800 or not 120 <= args.wall_seconds <= 2100:
        parser.error('seconds must be 1..1800; wall-seconds 120..2100')
    if args.command == 'stop':
        STOP.parent.mkdir(parents=True, exist_ok=True)
        STOP.write_text('user requested training stop', encoding='utf-8')
        return 0
    if args.command == 'panel':
        return training_control.panel(args.control_id)
    if args.command == 'check':
        if active_processes():
            raise RuntimeError('Cannot rebuild training map while a game is active')
        print(json.dumps(build(args.matchup, args.level, args.mode, download=True)[1], indent=2))
        return 0
    return play(args)


if __name__ == '__main__':
    raise SystemExit(main())
