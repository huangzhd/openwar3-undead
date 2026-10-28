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
from undead.game_view import Game, TrainingGame
from undead.controller import Controller, ground_attack_range
from undead.policy import Action
from undead.version import VERSION as BOT_VERSION, RULES_VERSION, DISPLAY_NAME
from undead.debug_console import ActionMeter
from undead.structures import is_structure
from undead.targeting import can_engage, in_weapon_range, buffs, abilities, unit_stats, webbed_air

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
    if 200 <= state < 300:
        return 2, state - 200
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
                    self.game = TrainingGame(pid=pid, fair=True)
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
    # This arena starts in an open clearing; advancing enters a narrow forest.
    # Ordinary melee keeps advancing; neither controller reshapes during fire.
    wait_for_enemy_opening = True

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
        self.altar_choice = dict(attempts=0,next_at=0,done=False,requested=False)
        self.training_endgame=False
        self.training_peak_enemies=0
        self.training_contact=False
        self.survivor_retry_at={}
        self.survivor_retries=set()

    def update_training_phase(self,now,enemy_count,combat_started):
        self.training_contact=self.training_contact or combat_started
        # Countdown lumber can mimic a count (e.g. 150 -> 50). Establish the
        # baseline only after actual combat, never from startup resources.
        if enemy_count is not None and self.training_contact:
            self.training_peak_enemies=max(self.training_peak_enemies,enemy_count)
            if (self.training_contact and not self.training_endgame and
                    0<enemy_count<self.training_peak_enemies and
                    enemy_count<=max(3,self.training_peak_enemies//3)):
                self.training_endgame=True
                self.wait_for_enemy_opening=False
                self.blight_opened=True;self.blight_waiting=False
                self.log('training_endgame_started',clock=now,remaining=enemy_count,
                         peak=self.training_peak_enemies,source='public_map_count')

    def survivor_targets(self,foes,now):
        return [e for e in foes if can_engage(e) and self.combat_progress.allowed(e,now)
                and not buffs(self.g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(self.g,e)]

    def refresh_survivors(self,army,foes,now):
        # A rejected nearby target must not pin every unit in "already in range".
        anchor=min(army,key=lambda u:sum(self.g.dist(u,v) for v in army))
        self.combat_progress.observe(army,[e for e in foes if self.g.dist(anchor,e)<600],now,
            enabled=self.training_endgame,visible=foes,current_target=self.g.current_target)
        targets=self.survivor_targets(foes,now)
        self.survivor_retries.intersection_update(e.handle for e in foes)
        # A quarantined survivor is not a death. Retry at bounded intervals,
        # while retaining the search route so an untargetable unit cannot reset it.
        if self.training_endgame and not targets:
            for e in foes:
                if (e.handle in self.combat_progress.quarantined and
                        now>=self.survivor_retry_at.get(e.handle,now+20)):
                    self.combat_progress.release(e,now,'training_survivor_retry')
                    self.survivor_retry_at[e.handle]=now+30;self.survivor_retries.add(e.handle)
                    break
                if e.handle in self.combat_progress.quarantined:
                    self.survivor_retry_at.setdefault(e.handle,now+20)
            targets=self.survivor_targets(foes,now)
        return targets

    def release_air_search_positions(self,army,foes,now,pulls,blocked=()):
        if (not self.training_endgame or foes or self.teleport or self.action==Action.RETREAT
                or self.army_recovery.active):return
        protected=set(blocked)|self.micro.pulling|set(self.shield_moves)|self.shopping|self.battle_shop.reserved
        for u in army:
            if (u.type=='ubsp' and u.hp>u.hp_max*.6 and u.handle not in protected
                    and now>=self.cast_until.get(u.handle,0) and u.handle not in self.destroyer.dispel):
                pulls.pop(u.handle,None) # Release only generic rear positioning, not danger/skill locks.

    def follow_search_dk(self,army,foes,now,blocked=()):
        dk=next((u for u in army if u.type=='Udea'),None)
        main=[u for u in army if u.type not in {'Udea','uobs','uban','ubsp'} and u.hp>u.hp_max*.45]
        if (not self.training_endgame or not dk or not main or self.teleport or self.action==Action.RETREAT
                or self.army_recovery.active or dk.hp<=dk.hp_max*.5 or dk.handle in set(blocked)|self.micro.pulling|self.shopping|self.backline_guards
                or now<self.cast_until.get(dk.handle,0)):return
        if any(self.g.dist(dk,e)<900 for e in foes):return
        anchor=min(main,key=lambda u:sum(self.g.dist(u,v) for v in main))
        gap=self.g.dist(dk,anchor)
        if gap<=450:return
        distance=min(400,gap-300)
        point=(dk.x+(anchor.x-dk.x)*distance/gap,dk.y+(anchor.y-dk.y)*distance/gap)
        if self.army_recovery.safe_path(self,(dk.x,dk.y),point,foes,combat=True) is None:return
        if self.due(('training_dk_follow',dk.handle),now,1.5):
            self.go_raw([dk],point,now)
            self.log('training_search_dk_follow',clock=now,handle=dk.handle,point=point)

    def pursue_survivors(self,army,foes,now,blocked=(),search_point=None):
        """Arena-only pursuit: visible survivors or last sighting/public route."""
        if not self.training_endgame or self.teleport or self.action==Action.RETREAT or self.army_recovery.active:return
        g=self.g;grid=g.map()
        if not grid:return
        targets=self.survivor_targets(foes,now)
        summons=self.attack_skeletons(army,foes,now)
        for u in army:
            if u.type=='Udea' and (u.hp<=u.hp_max*.6 or not self.dk_cleanup_allowed(army,foes)):continue
            if (u.type in {'uobs','uban'} or u.hp<=u.hp_max*.45 or u.handle in summons or u.handle in blocked or u.handle in self.shopping or
                    u.handle in self.battle_shop.reserved or u.handle in self.micro.pulling or
                    u.handle in self.backline_guards or now<self.cast_until.get(u.handle,0)):continue
            # Retain a current in-range attack; never interrupt the damage cycle.
            eligible=[e for e in targets if (s:=unit_stats(u.type)) and (v:=unit_stats(e.type))
                      and any(('air' if v.is_air and not webbed_air(g,e) else 'ground') in w.targets for w in s.weapons)]
            if any(in_weapon_range(g,u,e) for e in eligible):continue
            target=min(eligible,key=lambda e:g.dist(u,e)) if eligible else None
            point=(target.x,target.y) if target else search_point
            if point is None:continue
            gap=g.dist(u,point)
            if gap<=80:continue
            step=min(400,gap)
            dest=(u.x+(point[0]-u.x)*step/gap,u.y+(point[1]-u.y)*step/gap)
            flying=u.type=='ubsp'
            if flying and (self.destroyer_focused(u,foes) or u.hp<=u.hp_max*.6):continue
            if not flying and hasattr(g,'walk_path'):
                step=400 # The route may detour farther than the straight-line gap.
                path=g.walk_path((u.x,u.y),point)
                if not path:continue
                previous=(u.x,u.y);budget=400
                for waypoint in path:
                    length=g.dist(previous,waypoint)
                    if length>budget:
                        dest=(previous[0]+(waypoint[0]-previous[0])*budget/length,
                              previous[1]+(waypoint[1]-previous[1])*budget/length)
                        break
                    budget-=length;previous=waypoint;dest=waypoint
            if flying:
                threats=self.destroyer_air_threats(u,army,foes)
                if any(g.dist((u.x+(dest[0]-u.x)*i/12,u.y+(dest[1]-u.y)*i/12),e)<reach+140
                       for e,reach in threats for i in range(1,13)):continue
            else:
                route=g.path_distance((u.x,u.y),dest)
                if not grid.walkable(*dest) or route is None or route>step+128:continue
            if self.due(('training_pursuit',u.handle),now,1.5):
                receipt=g.attack_move(u,*dest)
                self.log('training_survivor_pursuit',clock=now,handle=u.handle,
                         target=target.handle if target else None,point=dest,accepted=bool(receipt))

    def search_target(self, army, foes, now):
        if hasattr(self,'combat_progress'):
            foes=[e for e in self.survivor_targets(foes,now) if e.handle not in self.survivor_retries]
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
            grid=self.g.map() if hasattr(self,'g') else None
            bounds=getattr(grid,'bounds',None)
            if bounds and len(bounds)==4:
                xmin,xmax,ymin,ymax=bounds
                # Serpentine public-terrain sweep, repeated until the map verdict.
                rows=range(int(ymin+320),int(ymax-160),700)
                xs=list(range(int(xmin+320),int(xmax-160),700))
                for i,y in enumerate(rows):
                    self.search_route.extend((float(x),float(y)) for x in (xs if i%2==0 else xs[::-1])
                                             if grid.walkable(x,y))
            self.search_index = 0
            self.search_since = now
            self.log('training_survivor_search_started', clock=now,
                     last_seen=self.last_foe_position)
        point = self.search_route[self.search_index]
        mobile = [u for u in army if u.type not in {'Udea','uobs','uban'}] or army
        reached = any(hypot(u.x-point[0], u.y-point[1]) < 320 for u in mobile)
        if reached or now-self.search_since > 28:
            self.search_index = (self.search_index + 1) % len(self.search_route)
            self.search_since = now
            point = self.search_route[self.search_index]
            self.log('training_survivor_search_waypoint', clock=now,
                     index=self.search_index, point=point,
                     reason='reached' if reached else 'time_budget')
        return point


    def choose_opening_hero(self,now):
        """Use the original u003 altar's N004 training option (Naga)."""
        g=self.g;state=self.altar_choice
        if state['done'] or not hasattr(g,'train'):return
        units=g.my_units()
        if state['requested'] and any(u.type=='Nngs' and u.alive for u in units):
            state['done']=True;self.start_potion_since=now
            self.log('training_altar_choice_confirmed',clock=now,choice='Nngs')
            return
        altars=[u for u in units if u.type=='u003' and u.alive and u.owner==g.me()]
        if not altars or state['attempts']>=3 or now<state['next_at']:return
        if self.battle_started or any(g.dist(e,altars[0])<900 for e in g.enemies()):return
        receipt=g.train(altars[0],'N004')
        state.update(attempts=state['attempts']+1,next_at=now+3,requested=True)
        self.log('training_altar_choice_attempt',clock=now,choice='Nngs',order='N004',
                 accepted=bool(receipt),attempt=state['attempts'])

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
        self.choose_opening_hero(now)
        army=[u for u in self.g.my_units() if u.alive and not is_structure(u)]
        self.equipment.tick(self.g,army,self.g.enemies(),now,self.cast_until)
        picking=self.collect_start_potion(now,army,self.g.enemies())
        return self.prepare_battle(now,army=army,blocked=picking)

    def tick(self):
        g = self.g
        now = g.clock()
        self.choose_opening_hero(now)
        army = [u for u in g.my_units() if u.alive and not is_structure(u)
                and u.type not in {'uaco', 'hpea', 'opeo', 'ewsp'}]
        if not army:
            return
        heroes = g.my_heroes()
        g.observe_coil(heroes, now, self.log)
        self.skills(now)
        self.observe_rod_corpses([*army, *g.enemies()], now)
        self.observe_rod_skeletons(now)
        visible_foes = [u for u in g.enemies() if can_engage(u)]
        foes = self.refresh_survivors(army,visible_foes,now)
        burrowing=self.fiend_burrow.tick(self,[u for u in army if u.type in {'ucry','ucrm'}],heroes,foes,now)
        self.micro.previous-=burrowing
        army=[u for u in army if u.type!='ucrm' and u.handle not in burrowing]
        self.equipment.tick(g,heroes,foes,now,self.cast_until,potions_only=self.battle_contact(army,foes,now))
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
                              attacking=True, urgent={u.handle for u in heroes if u.hp/u.hp_max <= .25},pending_heals=self.heal_checks,controller=self)
        picking=self.collect_start_potion(now,army,foes,set(pulls))
        self.battle_actions(army, foes, now, pulls,blocked=picking,search_point=search_point)
        self.frost_armor([u for u in army if u.handle not in picking], foes, now)
        self.statue_support.tick(self, army, foes, now, set(pulls))
        self.release_air_search_positions(army,foes,now,pulls,picking)
        for u in army:
            if u.handle in pulls:
                self.go_raw([u], pulls[u.handle], now)
        fighting = [u for u in army if u.handle not in pulls and u.handle not in picking]
        self.engage_battle(fighting, foes, now)
        pursuit_blocked=set(pulls)|set(picking)|set(self.shield_moves)
        self.pursue_survivors(fighting,foes,now,pursuit_blocked,search_point)
        self.follow_search_dk(army,foes,now,pursuit_blocked)
        if self.blight_waiting:return
        for hero in heroes:
            if hero.handle in picking or hero.type not in {'Udea', 'Ulic'} or now < self.cast_until.get(hero.handle, 0):
                continue
            if hero.type=='Udea' and foes:continue # Shared battle_rod already runs after rescue spells.
            bag = g.inventory(hero) or []
            if 'rnec' in bag:
                self.maintain_skeletons(hero, bag.index('rnec'), now)
        for u in fighting if not foes and not self.training_endgame else ():
            if (u.type in {'uobs','ubsp','uban'} or u.handle in self.battle_focus_handles or
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
        row['raw_type']=getattr(u,'raw_type',u.type)
        row['level']=u.level
        row['skill_points']=u.skill_points
        row['has_detail']=getattr(u,'has_detail',False)
        row['buffs']=sorted(g.buffs(u)) if row['has_detail'] else None
        if u.owner==g.me():
            row['inventory']=g.inventory(u)
            row['abilities']=g.abilities(u) if row['has_detail'] else None
    if u.type in {'uban','ubsp','ucry','uobs'}:
        row['has_detail']=getattr(u,'has_detail',False)
        row['buffs']=sorted(g.buffs(u)) if row['has_detail'] else None
        if u.owner==g.me() and u.type in {'uban','ubsp'}:
            row['abilities']=g.abilities(u) if row['has_detail'] else None
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
    result = dict(version=VERSION, melee_rules=RULES_VERSION, bot_version=BOT_VERSION,
                  bot_name=DISPLAY_NAME, result='error', reason='not_started',
                  selection=manifest, matrix_eligible=False, probe=args.probe,
                  max_game_seconds=args.seconds if args.probe else None,
                  max_wall_seconds=args.wall_seconds if args.probe else None,
                  training_attempt=round_no)
    started = time.monotonic()
    meter=None;speed_control=None;mode_control=None
    with (out / 'events.jsonl').open('w', encoding='utf-8') as stream:
        def log(event, **data):
            stream.write(json.dumps(dict(event=event, **data), ensure_ascii=False) + '\n')
            stream.flush()
        try:
            g = session.start()
            meter=ActionMeter(g)
            speed_control=training_control.RoundSpeed(g,log,control_id,round_no,args.speed,started)
            mode_control=training_control.RoundControl(control_id,round_no,log)
            if control_id:
                training_control.status(control_id, phase='running', round=round_no,
                                        bot_name=DISPLAY_NAME,bot_version=BOT_VERSION,apm=0,
                                        mode_control_available=True,control_mode='auto',
                                        metrics_updated=time.time())
            result['launch_settings'] = session.settings
            initial = [unit_row(g, u) for u in g.my_units()]
            result['initial_units'] = dict(Counter(u['type'] for u in initial))
            log('training_initial', clock=g.clock(), units=initial)
            bot = TrainingController(g, log, MATCHUPS[args.matchup])
            start_clock = g.clock()
            sampled = -100
            last_clock, moved = None, time.monotonic()
            combat_started = False
            peak_enemy_count = 0
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
                    result['next_speed']=command.get('speed') or speed_control.preferred
                    log('training_panel_command', clock=snap.clock, action=action,
                        selection=command.get('selection'))
                    break
                changed=mode_control.observe(snap.clock)
                if changed=='manual':
                    bot=None
                    # Release SDK leases, leaving game orders for the player to replace.
                    for u in g.my_units():g.claims.give_back(u.addr)
                speed_control.observe(snap,override=100 if changed=='manual' else None)
                args.speed=speed_control.preferred
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
                if args.probe and speed_control.budget_used >= args.wall_seconds:
                    result.update(result='timeout', reason='wall_time_limit'); break
                if args.probe and snap.clock - start_clock >= args.seconds:
                    result.update(result='probe_complete',reason='bounded_integration_probe'); break
                if snap.clock == last_clock:
                    if time.monotonic() - moved > 15:
                        raise RuntimeError('Training clock stalled for 15 wall seconds')
                    time.sleep(.2); continue
                last_clock, moved = snap.clock, time.monotonic()
                events=g.events()  # Drain during takeover too; do not replay stale events on resume.
                reason = contact_reason(g, own, foes) if state == 1 and not combat_started else None
                if state == 2 or reason:
                    if not combat_started:
                        combat_started = True
                        log('training_combat_engaged', clock=snap.clock,
                            signal='map_stage' if state == 2 else reason)
                # The original countdown resets lumber and can erase stage 2.
                # Once actual contact is visible, keep controlling the round.
                if combat_started and enemy_count is not None:
                    peak_enemy_count=max(peak_enemy_count,enemy_count)
                if mode_control.mode=='auto':
                    if bot is None:
                        # Re-evaluate live units; discard old movement, rescue and item plans.
                        bot=TrainingController(g,log,MATCHUPS[args.matchup])
                        bot.training_peak_enemies=peak_enemy_count
                        bot.battle_started=combat_started
                        bot.blight_opened=combat_started
                        bot.blight_waiting=False
                    bot.observe_events(events)
                    bot.update_training_phase(snap.clock,enemy_count,combat_started)
                    if combat_started:
                        bot.tick()
                    elif state == 1:
                        bot.skills(snap.clock)
                        bot.prepare(snap.clock)
                    else:
                        raise RuntimeError('Unexpected training scoreboard: ' + str(state))
                if snap.clock - sampled >= 1:
                    sampled = snap.clock
                    metrics=meter.summary(snap.clock)
                    if control_id:
                        training_control.status(control_id,**metrics,game_clock=snap.clock,metrics_updated=time.time())
                    log('training_sample', clock=snap.clock, state=state,
                        control_mode=mode_control.mode,
                        **metrics,
                        own=[unit_row(g, u) for u in own],
                        visible_enemies=[unit_row(g, u) for u in foes])
                time.sleep(.2)
            result['game_seconds'] = g.clock()
            result['final_units'] = dict(Counter(u.type for u in g.my_units()))
        except Exception as exc:
            result.update(result='error', reason=repr(exc))
            traceback.print_exc()
        finally:
            if mode_control is not None:
                result['control_history']=mode_control.history
                result['final_control_mode']=mode_control.mode
                result['human_takeover_used']=any(h['mode']=='manual' for h in mode_control.history)
            if speed_control is not None:
                result['speed_history']=speed_control.history
                result['final_speed']=speed_control.actual
                result['wall_budget_used']=round(speed_control.budget_used,2)
            if meter is not None:
                result.update(meter.summary(max(meter.last,result.get('game_seconds',meter.last))))
                meter.close()
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
                                        speed=args.speed)
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
            training_control.status(session_id, phase='loading', round=attempt, result=None,apm=None,
                                    speed=args.speed,speed_actual=None,speed_pending=None,speed_message='',
                                    mode_control_available=True,control_mode='auto',
                                    metrics_updated=None,bot_name=DISPLAY_NAME,bot_version=BOT_VERSION)
            result = run(args, session_id, attempt)
            training_control.status(session_id,last_round=training_control.round_summary(result))
            if result['result'] in ('restart_requested', 'selection_requested') and result['cleanup_confirmed']:
                args.speed=result.get('next_speed',args.speed)
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
    parser.add_argument('--speed', type=int, choices=training_control.SPEEDS, default=100)
    parser.add_argument('--seconds', type=int, default=180, help='Probe only; ordinary rounds have no time limit')
    parser.add_argument('--wall-seconds', type=int, default=240, help='Probe only; ordinary rounds have no time limit')
    parser.add_argument('--probe', action='store_true', help='Time-limited integration check, not a round pass')
    parser.add_argument('--control-id', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe and (not 1 <= args.seconds <= 1800 or not 120 <= args.wall_seconds <= 2100):
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
