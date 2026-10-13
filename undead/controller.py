"""Tech-fiend controller: macro and semantic unit commands, no desktop input."""
from math import hypot,cos,sin,pi,atan2
from .economy import Economy,HALLS
from .battle_shop import BattleShop
from .army_recovery import ArmyRecovery
from .home_defense import HomeDefense
from .formation import Formation
from .micro import Micro,COIL_MANA
from .hazards import LightningShield
from .loot import Loot
from .equipment import Equipment,can_receive
from .consumables import Consumables,ScrollSupply
from .creeping import Creeping
from .start_search import StartSearch
from .attack_search import AttackSearch
from .debug_console import camp_name,region
from .scouting import SkeletonScouts,SKELETONS,CritterSearch
from .coil import can_damage
from .nc_combo import NCCombo,spell_data,DISABLED_CASTERS,aoe_threat
from .targeting import in_weapon_range,priority,enemy_player,HeroPressure,webbed_air,can_engage
from .structures import is_structure
from .siege import SiegeFocus,attackable as siege_attackable,reachable as siege_reachable
from .creep_aggro import CreepAggro
from .sleep_wake import SleepWake
from .retreat import escape_point
from .combat_progress import CombatProgress
import json
from bootstrap import UPSTREAM
from openwar3 import combat
from functools import lru_cache
from .policy import Action,ScoutMemory,Situation,choose_rule,attack_ready

@lru_cache(maxsize=256)
def airborne(code):
    stats=combat.stats(code) # static local unit data only, no enemy technology queries
    return bool(stats and stats.is_air)

@lru_cache(maxsize=256)
def ground_attack_range(code):
    stats=combat.stats(code) # public static base ranges; never query enemy upgrades
    return max((w.range for w in stats.weapons if 'ground' in w.targets),default=0) if stats else 600

@lru_cache(maxsize=1)
def rod_skeleton_lifetime():
    # Local public spell data, not a hidden unit timer or an appearance timestamp.
    from w3slk import read_slk
    import w3paths
    try:
        row=next(r for r in read_slk(w3paths.game_data('AbilityData.slk')) if r.get('alias')=='AIrd')
        return float(row['Dur1']) if row.get('UnitID1')=='uske' else 0
    except (OSError,ValueError,KeyError,StopIteration):return 0

class Controller:
    def __init__(self,g,log,enemy_race=3):
        self.g,self.log=g,log
        self.enemy_race=enemy_race
        self.start_search=StartSearch(log)
        self.third_hero="Nngs" if enemy_race==4 else "Nbrn"
        self.economy=Economy(log,self.third_hero)
        self.battle_shop=BattleShop(log)
        self.army_recovery=ArmyRecovery(log)
        self.player_contact=[];self.contact_active=False
        self.rod_corpses={};self.rod_seen={};self.rod_used=set();self.rod_attempts={};self.rod_retry=0
        self.home_defense=HomeDefense(log)
        self.formation=Formation(log)
        self.formation_at=-100
        self.formation_orders=[]
        self.shop_goal=None
        self.micro=Micro(log)
        self.equipment=Equipment(log)
        self.consumables=Consumables(log)
        self.scroll_supply=ScrollSupply(log)
        self.shields=LightningShield(log)
        self.shield_moves={}
        self.loot=Loot(json.loads((UPSTREAM/'data/game/items.json').read_text(encoding='utf-8')),log)
        self.battle_enemies=[]
        self.combat_progress=CombatProgress(log)
        self.teleport=None
        self.portal_handoff=None
        self.portal_pulls={}
        self.portal_escaping=set()
        self.escape_history={}
        self.escape_started={}
        self.rescue_coils={}
        self.pull_checks={}
        self.cast_until={}
        self.heal_checks=[]
        self.nc_combo=NCCombo(log)
        self.nc_combo.healing_sources=lambda g,target,now:self.hero_pressure.support(g,target,g.enemies(),now,1)
        self.hero_attack_targets={}
        self.hero_pressure=HeroPressure(log)
        self.siege=SiegeFocus(log)
        self.ever_rod=False
        self.rod_purchase_closed=False
        self.scout_critter=None
        self.scout_critter_point=None
        self.scout_critter_seen=-100
        self.scout_corpse=None
        self.scout_corpse_abandoned=False
        self.critter_search=CritterSearch(log)
        self.opening_rod_finished=False
        self.opening_rod_attempts=0
        self.opening_rod_at=-100
        self.opening_rod_started=None
        self.graveyard_rod_started=None;self.graveyard_ready_at=None;self.graveyard_rod_at=-100
        self.graveyard_rod_attempts=0;self.graveyard_rod_abandoned=False
        self.tp_waiting=False
        self.tp_attempts=0
        self.tp_retry_at=0
        self.tp_bought=False
        self.memory=ScoutMemory()
        self.last={}
        self.attack_committed=False
        self.recovery_pending=False
        self.retreat_active=False
        self.retreat_safe_since=None
        self.attack_goal=None
        self.attack_target=None
        self.main_searched=False
        self.attack_search=AttackSearch(log)
        self.skeleton_scouts=SkeletonScouts(log)
        self.attacking_main=False
        self.action=Action.CREEP
        self.requested=self.action
        self.home=None
        self.enemy_main=None
        self.explore=0
        self.goal=None
        self.camp_goal=None
        self.creeping=Creeping(log)
        self.creep_strength=[]
        self.shopping=set()
        self.shop_attempts={}
        self.shop_retry_at={}
        self.shop_room_attempts={}
        self.rod_birth_windows=[]
        self.skeleton_expiry={}
        self.tavern_mission=None
        self.tavern_joiners=set()
        self.tavern_seen=set()
        self.tavern_trips=0
        self.tavern_sites=[] # Public placements, bound only after map fingerprint validation.
        self.tavern_retry_at=0
        self.seen_types=set()
        self.air_types=set()
        self.web_effects=set()
        self.black_arrow_enabled=set()
        self.black_arrow_attempts={}
        self.black_arrow_effects=set()
        self.autocast_states={}
        self.frost_armor_checks=[]
        self.frost_arrow_effects=set()
        self.creep_opened=set()
        self.creep_open_until=0
        self.creep_tank_observed=set()
        self.creep_aggro=CreepAggro(log)
        self.sleep_wake=SleepWake(log)
        self.situation=Situation(0)
        self.last_decide=-100
        self.pre_attack_retreat_until=-100
        self.intent="基地发展 · 等待英雄出发"
        self.shop_code=None

    def set_intent(self,text):
        self.intent=text+("；食尸鬼守家" if self.home_defense.active else "；食尸鬼返家" if self.home_defense.returning else "")

    def due(self,key,now,seconds):
        if now-self.last.get(key,-1000)<seconds:
            return False
        self.last[key]=now
        return True

    def retreat_rule(self,rule):
        s=self.situation
        threat=max(s.local_enemy_hp,s.base_enemy_hp if s.threatened else 0)
        if rule==Action.RETREAT and s.attack_committed:
            if not self.retreat_active:
                self.log('retreat_committed',clock=s.now,enemy_hp=threat,army_hp=s.army_hp)
            self.retreat_active=True
            self.retreat_safe_since=None
        if not self.retreat_active:return rule
        # LR 0.1.88: the visible force dipped below the entry threshold for one
        # tick, issuing attack orders only 0.95s into a retreat. Require a lower
        # exit threshold for five continuous seconds; recovery still follows.
        if rule==Action.RETREAT or threat>max(400,s.army_hp*.8):
            self.retreat_safe_since=None
        elif self.retreat_safe_since is None:
            self.retreat_safe_since=s.now
        elif s.now-self.retreat_safe_since>=5:
            self.retreat_active=False
            self.retreat_safe_since=None
            self.log('retreat_released',clock=s.now,enemy_hp=threat,army_hp=s.army_hp,
                     reason='sustained_lower_visible_threat')
            return rule
        return Action.RETREAT

    def active_foes(self,foes,now):
        ignored={e.handle for e in foes if e.type=='ucrm' and e.hp>0}
        previous=getattr(self,'buried_foes',set())
        for handle in ignored-previous:
            self.log('burrow_target_deferred',clock=now,handle=handle,
                     reason='buried_form_without_fair_detection_evidence')
        self.buried_foes=ignored
        return [e for e in foes if can_engage(e)]

    def third_hero_ready(self,heroes,center):
        # Initial departure waits for the tavern hero. After departure,
        # formation handles separation; death still removes readiness.
        return any(h.type==self.third_hero and h.hp>0 and
                   h.handle not in self.tavern_joiners and
                   (self.attack_committed or self.g.dist(h,center)<1200) for h in heroes)

    def go(self,units,point,now,attack=False):
        # Creeping uses explicit creep targets; attack-move must not acquire a player base.
        if self.action==Action.CREEP and not attack_ready(self.situation):attack=False
        units=[u for u in units if u.handle not in self.shield_moves and u.handle not in self.creep_aggro.protected and (u.handle not in self.shopping or self.action in (Action.RETREAT,Action.DEFEND) or self.battle_enemies)]
        combat={'Udea','Ulic','Nbrn','Nngs','ucry','uobs','uske','uskm','nsce','nsca'}
        battle=[e for e in self.battle_enemies if can_engage(e) and self.combat_progress.allowed(e,now)]
        if attack and len(units)>=2 and self.action not in (Action.RETREAT,Action.DEFEND):
            anchor=min(units,key=lambda u:sum(self.g.dist(u,v) for v in units))
            local=[u for u in units if self.g.dist(u,anchor)<700]
            handles={u.handle for u in local}
            for e in (self.g.creeps() if hasattr(self.g,'creeps') else []):
                if e in battle or not can_engage(e) or self.g.dist(e,anchor)>=900:continue
                target=self.g.current_target(e)
                engaged=target is not None and target.handle in handles
                engaged=engaged or any((t:=self.g.current_target(u)) is not None and t.handle==e.handle for u in local)
                if engaged and self.combat_progress.allowed(e,now):battle.append(e)
        if attack and not battle and self.combat_progress.deferred:
            attack=False # Resume the route without reacquiring the same ineffective target.
        if attack and battle and len(units)>=2 and self.action!=Action.RETREAT:
            anchor=min(units,key=lambda u:sum(self.g.dist(u,v) for v in units))
            for u in units:
                if self.g.dist(u,anchor)>700:
                    self.go_raw([u],(anchor.x,anchor.y),now,False)
            self.fight(units,battle,now)
            return
        if len(units)>=2 and all(u.type in combat for u in units):
            key=(tuple(sorted(u.handle for u in units)),round(point[0]/128),round(point[1]/128),attack)
            if now-self.formation_at>=1.5 or getattr(self,'formation_key',None)!=key:
                self.formation_at=now
                self.formation_key=key
                self.formation_orders=self.formation.plan(units,point,now,self.g.path_distance,self.g.walk_path,
                                                          retreat=self.action==Action.RETREAT)
            by_handle={u.handle:u for u in units}
            for old,p,hold in self.formation_orders:
                u=by_handle.get(old.handle)
                if u is None: continue
                if hold:
                    if now<self.cast_until.get(u.handle,0):continue
                    if self.due(('formation_hold',u.handle),now,4):
                        self.g.hold(u)
                        self.last.pop(('go',u.handle),None)
                else:
                    self.go_raw([u],p,now,attack and u.handle not in self.formation.joiners and u.handle not in self.formation.catching_up)
            if self.due('march_state',now,5):
                self.log('march_state',clock=now,target=point,stage=self.formation.stage,
                         army=[dict(handle=u.handle,type=u.type,x=round(u.x),y=round(u.y),
                                    point=p,hold=hold,catching_up=u.handle in self.formation.catching_up)
                               for old,p,hold in self.formation_orders if (u:=by_handle.get(old.handle)) is not None])
            return
        self.go_raw(units,point,now,attack)

    def go_raw(self,units,point,now,attack=False):
        for u in units:
            if now<self.cast_until.get(u.handle,0):continue
            key=('go',u.handle)
            dest=(round(point[0]/128),round(point[1]/128),attack)
            last=self.last.get(key)
            if last and last[0]==dest and now-last[1]<2:
                continue
            r=self.g.attack_move(u,*point) if attack else self.g.move(u,*point)
            if r:
                self.last[key]=(dest,now)

    def tick(self,forced=None):
        g=self.g
        snap=g.snapshot(max_age=0)
        if not snap or not snap.in_game:
            raise RuntimeError('Live game snapshot unavailable')
        now=snap.clock
        self.sleep_wake.observe(g,now,self.cast_until)
        self.observe_rod_corpses(snap.units,now)
        self.intent_clock=now
        self.set_intent("基地发展 · 等待英雄出发")
        halls=g.my_buildings(HALLS)
        if halls:
            self.home=next((h for h in halls if h.handle==getattr(self.home,'handle',None)),halls[0])
        else:
            remaining=g.my_buildings()
            if remaining:
                self.home=min(remaining,key=lambda b:g.dist(b,self.home)) if self.home else remaining[0]
            elif self.home is None:
                return # referee owns terminal classification; no fabricated base location
            if self.due('base_hall_missing',now,60):
                self.log('base_hall_missing',clock=now,rally=(self.home.x,self.home.y),remaining_buildings=len(remaining))
        mp=g.map()
        if mp:
            point=self.start_search.update(g,self.home,now)
            if point is not None:self.enemy_main=point
        self.observe_race(g.enemies(),now)
        self.memory.update(snap.units,now,g.me(),is_structure)
        heroes=g.my_heroes()
        fiends=g.units('me',{'ucry'})
        army=g.units('me',{'Udea','Ulic','Nbrn','Nngs','ucry','uobs','uske','uskm','nsce','nsca'})
        army=[u for u in army if u.handle not in self.skeleton_scouts.assignments]
        self.observe_rod_skeletons(now)
        foes=self.active_foes(g.enemies(),now)
        self.observe_air(foes,now)
        local_defended=self.home_defense.tick(g,self.home,foes,now,airborne)
        self.economy.ghoul_reserved=self.home_defense.reserved
        self.economy.home_tower_needed=self.home_defense.tower_needed
        self.economy.home_tower_point=(min(self.home_defense.raiders,key=lambda e:g.dist(e,self.home)).x,
                                       min(self.home_defense.raiders,key=lambda e:g.dist(e,self.home)).y) if self.home_defense.raiders else None
        raid=[] if local_defended else self.home_defense.raiders
        tier=(3 if self.home.type=='unp2' else 2 if self.home.type=='unp1' else 1) if halls else 0
        self.creeping.enemy_main=self.enemy_main
        self.creeping.enemy_structures=[u for u in self.memory.units.values() if u.building and 0<=u.owner<12 and u.owner!=g.me()]
        if halls and hasattr(g,'production'):
            hp=g.production(self.home)
            if hp and hp.kind in {'upgrade','construction'}:tier=min(tier,2)
        self.creeping.tier=tier
        dk=next((h for h in heroes if h.type=='Udea'),None)
        lich=next((h for h in heroes if h.type=='Ulic'),None)
        anchor=min(army,key=lambda u:sum(g.dist(u,v) for v in army)) if army else self.home
        main=[u for u in army if u.handle not in self.tavern_joiners and (not self.tavern_mission or u.handle!=self.tavern_mission['courier'])]
        if main:anchor=min(main,key=lambda u:sum(g.dist(u,v) for v in main))
        center=(anchor.x,anchor.y)
        self.clear_attack_sites(foes,center,now)
        visible_creeps=g.creeps()
        self.creeping.observe_drop_carriers(g,visible_creeps,now)
        hostiles=foes+visible_creeps
        self.combat_progress.observe(army,[e for e in hostiles if g.dist(e,center)<600],now,
                                     self.action in (Action.ATTACK,Action.HARASS))
        self.player_contact=self.detect_player_contact(army,foes,center)
        for enemy in self.player_contact:self.combat_progress.deferred.pop(enemy.handle,None)
        foes=[e for e in foes if self.combat_progress.allowed(e,now)]
        hostiles=[e for e in hostiles if self.combat_progress.allowed(e,now)]
        self.battle_enemies=[e for e in hostiles if g.dist(e,center)<600 or e in self.player_contact]
        local_army=[u for u in army if g.dist(u,center)<1200]
        self.creep_strength=local_army
        target_of=lambda e:(g.current_target(e).handle if g.current_target(e) else None)
        if self.battle_shop.orb and dk and not any(g.dist(e,dk)<950 for e in foes):
            self.micro.dk_recovering=None
        recovering_dk=self.micro.dk_recovering
        pulls=self.micro.plan(army,hostiles,now,target_of,g.path_distance,mp.walkable if mp else lambda *p:False,
                              (self.home.x,self.home.y),lambda e:ground_attack_range(e.type),
                              coil_ready=self.rescue_coil_ready(dk,now),
                              creeping=not self.attack_committed and not any(g.dist(e,center)<1200 for e in foes))
        if dk and dk.handle in self.micro.pulling and self.micro.damage.urgent(dk) and not self.player_contact:
            nearby=[e for e in hostiles if g.dist(e,dk)<1200]
            allies=[u for u in local_army if u.handle!=dk.handle and u.type not in SKELETONS]
            if nearby and allies and all(getattr(e,'owner',None)==12 for e in nearby):
                rear=min(allies,key=lambda u:sum(g.dist(u,v) for v in allies))
                point=escape_point(g,dk,nearby,ground_attack_range,pulls.get(dk.handle),home=(rear.x,rear.y))
                if point is not None and g.dist(point,rear)<=750:pulls[dk.handle]=point
        if raid and lich and lich.handle in self.micro.pulling:
            point=escape_point(g,lich,hostiles,ground_attack_range,pulls.get(lich.handle),home=(self.home.x,self.home.y))
            pulls[lich.handle]=point if point is not None else (lich.x,lich.y)
        self.portal_pulls=pulls
        if dk is not None and recovering_dk==dk.handle and self.micro.dk_recovering is None:
            # Micro moved DK outside his old per-unit waypoint sequence. Rebuild
            # from today's main body, otherwise he can run back to a passed turn.
            self.formation.reset();self.formation_at=-100
            self.log('dk_rejoined',clock=now,handle=recovering_dk)
        if self.black_arrow_enabled and self.due('black_arrow_effect',now,1):
            for e in hostiles:
                if e.handle not in self.black_arrow_effects and {'BNba','BNdm'} & set(g.buffs(e)):
                    self.black_arrow_effects.add(e.handle)
                    self.log('black_arrow_effect_observed',clock=now,target=e.type,handle=e.handle)
        expansion=self.memory.expansions(self.enemy_main,now)
        self.situation=Situation(now,min((h.hp/h.hp_max for h in heroes),default=1),bool(raid),bool(expansion),
            sum(e.hp for e in hostiles if not is_structure(e) and e.type not in {'hpea','opeo','uaco','ewsp'} and (g.dist(e,center)<1000 or e in self.player_contact)),sum(u.hp for u in local_army),len(fiends),tier,
            bool(lich),bool(lich and 'ocor' in (g.inventory(lich) or [])),len(g.units('me',{'uobs'})),dk.level if dk else 1,
            sum(u.hp for u in local_army)/max(1,sum(u.hp_max for u in local_army)),len(self.micro.losses))
        self.situation.base_enemy_hp=sum(e.hp for e in raid if not is_structure(e) and e.type not in {'hpea','opeo','uaco','ewsp'})
        self.situation.third_hero=self.third_hero_ready(heroes,center)
        self.situation.dk=bool(dk and dk.hp>0)
        if not self.attack_committed and attack_ready(self.situation):
            self.attack_committed=True
            self.log('attack_phase_started',clock=now,reason='tier_three_orb_three_heroes_confirmed')
        self.situation.attack_committed=self.attack_committed
        if any(g.dist(e,center)<1200 for e in hostiles) and self.due('combat_state',now,2):
            self.log('combat_state',clock=now,center=center,
                army_hp=self.situation.army_hp,enemy_hp=self.situation.local_enemy_hp,
                army_health=self.situation.army_health,recent_losses=len(self.micro.losses),
                army=[dict(handle=u.handle,type=u.type,x=round(u.x),y=round(u.y),hp=round(u.hp),
                           hp_max=u.hp_max,mana=round(getattr(u,'mana',0)),
                           pulling=u.handle in self.micro.pulling,pull= pulls.get(u.handle)) for u in army],
                enemies=[dict(handle=e.handle,type=e.type,x=round(e.x),y=round(e.y),hp=round(e.hp),
                              target=target_of(e)) for e in hostiles if g.dist(e,center)<1500])
        self.situation.creep_targets_available=self.creeping.has_work(g,army,self.home,now) if army and mp else False
        types={u.type for u in g.my_units()}
        if types-self.seen_types:
            self.log('new_units',types=sorted(types-self.seen_types),clock=now)
            self.seen_types |= types
        wants_attack=choose_rule(self.situation) in (Action.ATTACK,Action.HARASS) or self.action in (Action.ATTACK,Action.HARASS)
        # LR 0.1.76: optional missing TP blocked fiend recovery until a raid.
        frontline=bool(not raid and g.dist(center,self.home)>1600 and (self.player_contact or any(
            enemy_player(g,e) and any(in_weapon_range(g,u,e) for u in local_army)
            for e in foes)))
        if frontline!=self.economy.frontline_combat:
            self.log('frontline_budget',clock=now,active=frontline,portal_reserved=not frontline)
        self.economy.frontline_combat=frontline
        self.economy.save_for_tp=bool(not attack_ready(self.situation) and dk and tier>=2 and wants_attack and all(g.inventory(h) is not None for h in heroes) and not any('stwp' in (g.inventory(h) or []) for h in heroes))
        self.battle_shop.observe(g,now)
        self.army_recovery.observe(self,army,hostiles,now,bool(raid))
        self.economy.save_for_trade=bool(self.army_recovery.reserve or self.battle_shop.pending or not raid and choose_rule(self.situation)!=Action.RETREAT and self.battle_shop.orb_reserve(g))
        self.economy.bank_item_reserve=sum(job[3] for job in self.bank_supply_jobs(now))
        if self.due('economy',now,.8):
            self.economy.expansion.camps=[c for c in self.creeping.catalog if c['kind']=='expansion' and c['id'] in self.creeping.cleared]
            self.economy.expansion.safe_route=lambda start,end:self.creeping.safe_route(g,start,end)
            self.economy.tick(g,now,bool(raid))
        rule=self.retreat_rule(choose_rule(self.situation))
        safety=rule==Action.RETREAT or bool(raid)
        urgent=safety and self.action!=rule
        if now-self.last_decide>=5 or urgent or forced is None and rule==Action.ATTACK and self.action!=rule:
            self.last_decide=now
            self.requested=Action(forced) if forced is not None else rule
            self.action=rule if safety else self.requested
            if self.action==Action.ATTACK and not attack_ready(self.situation):self.action=Action.CREEP
            self.log('decision',clock=now,requested=self.requested.name,actual=self.action.name,
                expansion=bool(expansion),fiends=len(fiends),tier=tier,heroes=[(h.type,h.level,round(h.hp)) for h in heroes],
                safety_interrupt=urgent,base_enemy_hp=self.situation.base_enemy_hp,
                local_enemy_hp=self.situation.local_enemy_hp,army_hp=self.situation.army_hp,
                retreat_active=self.retreat_active)
        if self.action==Action.RETREAT and self.attack_committed:self.recovery_pending=True
        if self.action==Action.ATTACK and not attack_ready(self.situation):
            self.action=Action.CREEP
        self.set_intent({Action.CREEP:"准备练级",Action.ATTACK:"准备进攻",Action.HARASS:"准备骚扰分矿",
                         Action.DEFEND:"回防基地",Action.RETREAT:"撤退回家"}[self.action])
        if self.action==Action.RETREAT or self.teleport:
            self.sleep_wake.cancel(g,now,self.cast_until,'safety_priority')
        self.defense_shopping=self.battle_shop.defend_tick(self,hostiles,now,tier) if raid else set()
        self.consumables.tick(g,army,hostiles,now,self.cast_until,
                              (self.teleport['hero'],) if self.teleport else (),self.coil_needed(dk),self.action==Action.ATTACK,
                              {h.handle for h in heroes if self.micro.damage.urgent(h)},
                              self.action in (Action.ATTACK,Action.HARASS) and not self.battle_enemies)
        if not self.teleport and self.emergency_portal(army,now):
            self.sleep_wake.cancel(g,now,self.cast_until,'emergency_portal')
            self.creeping.defer(now,'emergency_portal')
            self.protect_portal_allies(army,pulls,now)
            return
        self.scout(now)
        self.skills(now)
        self.shopping=set(self.defense_shopping)
        self.shop_goal=None
        self.shop_code=None
        if not self.army_recovery.active:self.items(now,tier)
        if self.action in (Action.RETREAT,Action.DEFEND) and self.skeleton_scouts.assignments:
            scouts=[u for u in g.units('me',SKELETONS) if u.handle in self.skeleton_scouts.assignments]
            self.go_raw(scouts,(self.home.x,self.home.y),now)
            self.skeleton_scouts.assignments.clear()
        fighters=army
        if not fighters:
            self.set_intent("基地发展 · 等待英雄出发")
            return
        if self.teleport:
            self.creep_aggro.step(g,fighters,hostiles,now,False,{h for h,t in self.cast_until.items() if now<t})
            caster=g.unit(self.teleport['hero'])
            if caster and g.dist(caster,self.home)<900:
                self.log('teleport_confirmed',clock=now,hero=caster.type)
                self.recovery_pending=True
                self.teleport=None
                self.formation.reset();self.formation_at=-100
            elif now-self.teleport['started']<7:
                self.set_intent('紧急回城 · 引导中')
                self.creeping.pause(now,'teleport')
                self.protect_portal_allies(fighters,pulls,now)
                return
            else:
                self.log('teleport_unconfirmed',clock=now,hero=caster.type if caster else None,
                         point=(caster.x,caster.y) if caster else None,
                         inventory=g.inventory(caster) if caster else None,
                         buffs=g.buffs(caster) if caster and hasattr(g,'buffs') else None)
                self.teleport=None
        self.shield_moves=self.shields.plan(fighters,hostiles,now,getattr(g,'buffs',lambda u:[]),
                                            mp.walkable if mp else lambda *p:False,g.path_distance)
        if self.sleep_wake.active and self.sleep_wake.active['actor'] in (set(pulls)|set(self.shield_moves)):
            self.sleep_wake.cancel(g,now,self.cast_until,'pullback_priority')
        if self.pre_attack_retreat(fighters,foes,now):return
        self.combat_spells(fighters,foes,now,set(pulls)|set(self.shield_moves))
        for u in fighters:
            if u.handle in self.shield_moves:self.go_raw([u],self.shield_moves[u.handle],now)
        pulls.update(self.shield_moves)
        if self.action!=Action.RETREAT and not self.teleport and self.player_contact:
            self.sleep_wake.start(g,fighters,now,self.cast_until,
                set(pulls)|set(self.shield_moves)|self.shopping|self.creep_aggro.protected|
                self.skeleton_scouts.assignments.keys())
        self.frost_armor(fighters,hostiles,now)
        blocked=set(pulls)|{h for h,until in self.cast_until.items() if now<until}
        self.creep_aggro.step(g,fighters,hostiles,now,
            self.action==Action.CREEP and not self.attack_committed and not self.micro.dk_support and
            not any(g.dist(e,center)<1200 for e in foes),blocked)
        tavern_reserved=self.recruit_tavern(fighters,hostiles,now,tier,blocked)
        if self.action!=Action.DEFEND and self.army_recovery.tick(self,fighters,hostiles,now,pulls):return
        if self.action==Action.RETREAT:
            self.creeping.defer(now,'safety_retreat')
            self.collective_retreat(fighters,now)
            return
        for handle,check in list(self.pull_checks.items()):
            u=g.unit(handle)
            others_attacking=any(v.handle!=handle and v.handle not in pulls and g.current_target(v) is not None for v in fighters)
            if u and now-check['started']>=1 and g.dist(u,check['origin'])>80 and g.dist(u,check['target'])+50<g.dist(check['origin'],check['target']) and others_attacking:
                self.log('pullback_verified',clock=now,unit=u.type,moved=round(g.dist(u,check['origin'])),others_attacking=True)
                self.pull_checks.pop(handle,None)
            elif now-check['started']>8 or u is None:
                self.pull_checks.pop(handle,None)
        for u in fighters:
            if u.handle in pulls and u.handle not in self.defense_shopping:
                if u.handle not in self.pull_checks:
                    self.pull_checks[u.handle]={'origin':(u.x,u.y),'target':pulls[u.handle],'started':now}
                self.go_raw([u],pulls[u.handle],now)
        healthy=[u for u in fighters if u.handle not in self.defense_shopping and u.handle not in pulls and u.handle not in tavern_reserved and now>=self.cast_until.get(u.handle,0)]
        if not healthy:
            self.set_intent('部队脱险 · 恢复阵形')
            self.creeping.pause(now,'all_units_pulling_back')
            return
        self.hero_attack_targets={h:t for h,t in self.hero_attack_targets.items() if any(u.handle==h for u in fighters)}
        self.stop_hero_chases(healthy,now)
        if self.action==Action.DEFEND:
            self.defend_base(healthy,raid,now)
            return
        if self.respond_player_contact(healthy,now):return
        if self.recover_missing_heroes(fighters,now):return
        courier=self.battle_shop.orb_tick(self,healthy,hostiles,now,tier)
        if courier:
            self.shopping.update(courier)
            self.shop_goal=None;self.shop_code=None
            healthy=[u for u in healthy if u.handle not in courier]
            self.creep_strength=[u for u in self.creep_strength if u.handle not in courier]
            if healthy:center=(min(healthy,key=lambda u:sum(g.dist(u,v) for v in healthy)).x,
                               min(healthy,key=lambda u:sum(g.dist(u,v) for v in healthy)).y)
        if not healthy:return
        if not courier and self.support_dk(healthy,now):return
        self.battle_shop.sell_nearby(self,heroes,hostiles,now)
        if self.action!=Action.ATTACK and self.equipment.tick(g,healthy,hostiles,now,self.cast_until):
            self.set_intent('战后整备 · 分配装备')
            self.creeping.pause(now,'equipment_transfer')
            return
        if self.action in (Action.ATTACK,Action.HARASS):
            self.creeping.pause(now,'opponent_objective')
            if not self.prepare_attack(healthy,now):return
            self.battle_shop.prepare_potion(self,healthy,hostiles,now,opportunistic=True)
        if self.action not in (Action.DEFEND,Action.ATTACK):
            pickup=self.loot.tick(g,healthy,hostiles,now,heroes,self.action==Action.CREEP and bool(g.creeps()) and not self.player_contact)
            if pickup:
                self.set_intent('沿途收集战利品')
                self.creeping.pause(now,'loot')
                picker,point=pickup
                others=[u for u in healthy if u.handle!=picker.handle]
                if any(g.dist(u,point)>500 for u in others):
                    self.go(others,point,now)
                elif self.due('loot_wait',now,3):
                    for u in others:g.hold(u)
                return
        if self.shop_goal:
            self.set_intent('前往商店 · 购买'+{'ocor':'腐蚀之球','rnec':'骷髅棒'}.get(self.shop_code,'补给'))
            self.creeping.pause(now,'shopping')
            self.go(healthy,self.shop_goal,now,attack=False)
            self.fight(healthy,[e for e in foes+g.creeps() if g.dist(e,center)<650],now)
            return
        if self.action==Action.HARASS and expansion and dk:
            target=min(expansion,key=lambda e:g.dist(e,dk))
            towers=[e for e in foes if is_structure(e) and e.type in {'hgtw','hctw','hatw'} and g.dist(e,target)<850]
            if len(towers)>=2:
                self.action=Action.CREEP
                self.log('harass_aborted',reason='defended_expansion',clock=now)
            else:
                self.set_intent("骚扰敌方分矿")
                raiders=healthy
                peasants=[e for e in foes if e.type in {'hpea','hmil'} and g.dist(e,target)<1000]
                self.go(raiders,(target.x,target.y),now,attack=True)
                self.fight(raiders,peasants,now)
                return
        if self.action==Action.ATTACK:
            self.advance_attack(healthy,foes,center,now)
            return
        self.creep(healthy,center,now)

    def detect_player_contact(self,army,foes,center):
        g=self.g
        main=[u for u in army if g.dist(u,center)<1200 and u.type not in SKELETONS]
        handles={u.handle for u in main}
        contact=[]
        for e in foes:
            if not enemy_player(g,e) or is_structure(e) or not can_engage(e):continue
            target=g.current_target(e)
            attacking=target is not None and target.handle in handles and g.dist(e,target)<ground_attack_range(e.type)+250
            nearby=any(g.dist(e,u)<700 for u in main)
            if attacking or nearby:contact.append(e)
        return contact

    def defend_base(self,army,raid,now):
        # A home-defense order must leave the camp, even while neutrals attack.
        self.set_intent('回防基地')
        self.creeping.pause(now,'base_defense')
        local=[e for e in raid if enemy_player(self.g,e) and any(self.g.dist(e,u)<900 for u in army)]
        if local:
            previous=self.player_contact
            self.player_contact=local
            self.respond_player_contact(army,now)
            self.player_contact=previous
            self.set_intent('回防基地 · 迎击来袭敌军')
        else:
            self.go_raw(army,(self.home.x,self.home.y),now,attack=False)
        if self.due('base_defense_response',now,3):
            self.log('base_defense_response',clock=now,destination=(self.home.x,self.home.y),
                     stage='engage' if local else 'return',units=[u.handle for u in army],
                     targets=[e.handle for e in local])

    def respond_player_contact(self,army,now):
        if not self.player_contact:
            self.contact_active=False
            return False
        army=[u for u in army if u.handle not in self.micro.pulling and u.handle not in self.shield_moves and u.handle not in self.creep_aggro.protected and now>=self.cast_until.get(u.handle,0)]
        self.set_intent('遭遇敌军 · 暂停练级并反击')
        self.creeping.defer(now,'player_contact')
        if self.battle_shop.orb:self.battle_shop.end_orb(now,'player_contact')
        if not self.contact_active:
            self.formation.reset();self.formation_at=-100
            self.log('player_contact_interrupt',clock=now,action=self.action.name,
                     targets=[dict(type=e.type,handle=e.handle) for e in self.player_contact])
        for u in army:
            if now<self.cast_until.get(u.handle,0):continue
            current=self.g.current_target(u)
            if not self.contact_active or current is not None and not enemy_player(self.g,current):
                self.g.hold(u);self.last.pop(('go',u.handle),None)
        self.contact_active=True
        fighters=[u for u in army if u.type!='uobs']
        ranged=[u for u in fighters if u.type in {'ucry','Ulic','Nbrn','Nngs'}] or fighters
        engaged=[u for u in ranged if any(in_weapon_range(self.g,u,e) for e in self.player_contact)]
        if ranged:
            front=min(engaged,key=lambda u:sum(self.g.dist(u,v) for v in engaged)) if engaged else min(ranged,key=lambda u:min(self.g.dist(u,e) for e in self.player_contact))
            point=(front.x,front.y)
            if not engaged:
                # Close on ordinary enemy units, while retaining the no-hero-chase rule.
                targets=[e for e in self.player_contact if not e.is_hero]
                if targets:
                    target=min(targets,key=lambda e:self.g.dist(front,e))
                    distance=self.g.dist(front,target)
                    step=min(300,max(0,distance-max(100,ground_attack_range(front.type)-50)))
                    if distance>0:point=(front.x+(target.x-front.x)*step/distance,front.y+(target.y-front.y)*step/distance)
            reinforcements=[]
            for u in army:
                if now<self.cast_until.get(u.handle,0) or any(in_weapon_range(self.g,u,e) for e in self.player_contact):continue
                # DK and statues support the firing line without charging through it.
                margin=400 if u.type in {'Udea','uobs'} else 100 if engaged else 40
                if self.g.dist(u,point)>margin:reinforcements.append(u)
            if reinforcements:
                self.go(reinforcements,point,now,attack=False)
                if self.due('combat_reinforce',now,2):
                    self.log('combat_reinforce',clock=now,point=point,units=[dict(type=u.type,handle=u.handle) for u in reinforcements])
        self.fight(army,self.player_contact,now)
        return True

    def pre_attack_retreat(self,army,foes,now):
        if attack_ready(self.situation) or self.action in (Action.DEFEND,Action.HARASS):return False
        g=self.g
        main=[u for u in army if u.handle not in self.tavern_joiners and
              (not self.tavern_mission or u.handle!=self.tavern_mission['courier'])]
        if not main or self.home is None:return False
        anchor=min(main,key=lambda u:sum(g.dist(u,v) for v in main))
        buildings=[e for e in self.memory.units.values() if e.building and 0<=e.owner<12 and e.owner!=g.me()]
        buildings += [e for e in foes if is_structure(e) and enemy_player(g,e) and e.hp>0]
        unsafe=any(g.dist(e,anchor)<1400 or any(u.is_hero and g.dist(e,u)<1100 for u in main) for e in buildings)
        if unsafe:self.pre_attack_retreat_until=now+12
        if not unsafe and now>=self.pre_attack_retreat_until:return False
        self.action=Action.RETREAT
        self.creeping.defer(now,'pre_attack_enemy_base')
        # Release allied creep-aggro orders before withdrawing; preserve active casts.
        self.creep_aggro.step(g,army,foes,now,False,{h for h,t in self.cast_until.items() if now<t})
        for u in main:
            if u.handle in self.shield_moves:self.go_raw([u],self.shield_moves[u.handle],now)
        self.set_intent('成型前避战 · 撤离敌方基地')
        self.go(main,(self.home.x,self.home.y),now,attack=False)
        if self.due('pre_attack_base_retreat',now,3):
            self.log('pre_attack_base_retreat',clock=now,tier=self.situation.tier,
                     orb=self.situation.orb,third_hero=self.situation.third_hero,dk=self.situation.dk,
                     center=(anchor.x,anchor.y),destination=(self.home.x,self.home.y))
        return True

    def support_dk(self,army,now):
        request=self.micro.dk_support
        if not request:return False
        dk=self.g.unit(request['handle']) if self.situation and self.situation.threatened else None
        if self.situation and self.situation.threatened and dk and dk.hp/dk.hp_max>=.6 and not self.micro.damage.urgent(dk):
            return False # Healthy DK rejoins; the defensive line keeps fighting.
        self.set_intent('部队集结 · 接应死亡骑士')
        self.creeping.pause(now,'dk_support')
        # Distant escorts move straight to support instead of stopping to fight
        # unrelated blockers; nearby escorts can attack at the rendezvous.
        escorts=[u for u in army if u.handle!=request['handle'] and u.handle not in self.shield_moves]
        for u in escorts:
            self.go_raw([u],request['point'],now,attack=self.g.dist(u,request['point'])<=650)
        if self.due('dk_support',now,2):
            self.log('dk_support',clock=now,**request,escorts=[u.handle for u in escorts])
        return True

    def clear_attack_sites(self,foes,center,now):
        g=self.g
        removed=self.memory.clear_visible_empty_sites(
            [e for e in foes if is_structure(e)],lambda x,y:g.visible(x,y),
            lambda e:0<=e.owner<12 and e.owner!=g.me() and g.dist(e,center)<1000)
        for site in removed:
            self.log('enemy_site_empty',clock=now,code=site.type,handle=site.handle,point=(site.x,site.y))

    def advance_attack(self,army,foes,center,now):
        g=self.g
        self.clear_attack_sites(foes,center,now)
        buildings=[e for e in self.memory.units.values() if 0<=e.owner<12 and e.owner!=g.me() and e.building]
        main_buildings=[e for e in buildings if self.enemy_main and g.dist(e,self.enemy_main)<1800]
        if self.attacking_main and not main_buildings and self.enemy_main and g.visible(*self.enemy_main):
            self.attacking_main=False
        preferred=main_buildings if self.attacking_main and main_buildings else buildings
        # Keep an observed structure until it is removed by fair evidence.
        # New foundations and a moving army must not flip the destination each tick.
        target=next((e for e in preferred if e.handle==self.attack_target),None)
        if target is None:target=min(preferred,key=lambda e:g.dist(e,center)) if preferred else None
        next_target=target.handle if target else None
        point=(target.x,target.y) if target else self.enemy_main
        reason='known_structure' if target else 'enemy_main'
        if point is None:
            point=self.start_search.choose(g,center,now)
            reason='scout_unknown_start'
        if self.attack_committed and target is not None and self.enemy_main and point and g.dist(point,self.enemy_main)<1800 and g.dist(center,self.enemy_main)<1800:
            self.attacking_main=True
        if self.attacking_main or self.skeleton_scouts.assignments:
            sites=[(c['x'],c['y']) for c in self.creeping.catalog if c['kind']=='expansion']
            sites += [(u.x,u.y) for u in self.memory.units.values() if u.type in {'ngol','egol','ugol'}]
            reserved=set(self.tavern_joiners)
            if self.tavern_mission:reserved.add(self.tavern_mission['courier'])
            orders=self.skeleton_scouts.plan(g,center,(self.home.x,self.home.y),self.enemy_main,sites,foes,now,self.attacking_main,reserved=reserved)
            for scout,goal in orders:self.go_raw([scout],goal,now)
            army=[u for u in army if u.handle not in self.skeleton_scouts.assignments]
        if self.focus_siege(army,foes,now):return
        if target is None and self.enemy_main:
            if not self.main_searched and g.dist(center,self.enemy_main)<650 and g.visible(*self.enemy_main):
                self.main_searched=True
                self.log('enemy_main_area_observed_empty',clock=now,point=self.enemy_main)
            if self.main_searched:
                sites=[(c['x'],c['y']) for c in self.creeping.catalog if c['kind']=='expansion']
                sites += [(u.x,u.y) for u in self.memory.units.values() if u.type in {'ngol','egol','ugol'}]
                point=self.attack_search.choose(g,center,(self.home.x,self.home.y),self.enemy_main,sites,now,bool(self.battle_enemies))
                reason='search_remaining_structures'
        if reason=='scout_unknown_start':
            self.set_intent('侦察敌方出生点')
        elif reason=='search_remaining_structures':
            self.set_intent('搜索残余建筑 · '+(region(point) if point else '本轮搜索结束'))
        else:
            self.set_intent('进攻敌方主基地' if self.enemy_main and point and g.dist(point,self.enemy_main)<1800 else '进攻'+(region(point) if point else '')+'已知敌建筑')
        if point:
            if next_target!=self.attack_target or self.attack_goal is None or g.dist(self.attack_goal,point)>192:
                self.attack_goal=point
                self.formation.reset();self.formation_at=-100
                self.attack_target=next_target
                self.log('attack_goal',clock=now,point=point,reason=reason,handle=next_target,code=target.type if target else None)
            # go fights visible roadside blockers; it never selects an off-route camp.
            self.go(army,point,now,attack=True)
        self.fight(army,[e for e in foes if g.dist(e,center)<950],now)

    def prepare_recovery(self,army,now):
        g=self.g
        if self.battle_enemies:return True # Combat and base defense must remain responsive.
        # Mana supply belongs to an existing home stop, never a reason to recall a healthy field army.
        observed=[u for u in (self.creep_strength or army) if u.type not in SKELETONS]
        anchor=min(observed,key=lambda u:sum(g.dist(u,v) for v in observed)) if observed else None
        at_home=anchor is not None and g.dist(anchor,self.home)<=1200
        heroes=g.my_heroes()
        dk=next((h for h in heroes if h.type=='Udea'),None)
        lich=next((h for h in heroes if h.type=='Ulic'),None)
        # Order eligibility excludes casting/pulling units; health checks must not.
        core=[u for u in (self.creep_strength or army) if u.type not in SKELETONS]
        reasons=[]
        if at_home and dk and dk.mana<75:reasons.append('dk_mana')
        if self.recovery_pending:
            if sum(u.hp for u in core)<.8*sum(u.hp_max for u in core):reasons.append('army_health')
            if any(u.hp<.7*u.hp_max for u in heroes):reasons.append('hero_health')
            if at_home and lich and lich.mana<125:reasons.append('lich_mana')
            if sum(u.type=='ucry' for u in core)<6:reasons.append('fiends')
            if not any(u.type=='uobs' for u in core):reasons.append('statue')
        if not reasons:
            if self.recovery_pending:self.log('attack_recovery_ready',clock=now,dk_mana=dk.mana if dk else None)
            self.recovery_pending=False
            return True
        self.set_intent('出征整备 · 恢复血蓝与补兵')
        self.creeping.pause(now,'attack_recovery')
        if self.due('attack_recovery_wait',now,5):
            self.log('attack_recovery_wait',clock=now,reasons=reasons,dk_mana=dk.mana if dk else None,
                     lich_mana=lich.mana if lich else None)
        if dk and 'dk_mana' in reasons and self.battle_shop.prepare_mana(self,army,dk,now):return False
        self.go(army,(self.home.x,self.home.y),now)
        return False

    def prepare_attack(self,army,now):
        """One observed team scroll suffices; never buy to duplicate a teammate's."""
        optional=attack_ready(self.situation)
        if (self.recovery_pending or not optional) and not self.prepare_recovery(army,now):return False
        g=self.g
        dk=next((h for h in g.my_heroes() if h.type=='Udea'),None)
        inv=g.inventory(dk) if dk else None
        heroes=g.my_heroes()
        lich=next((h for h in heroes if h.type=='Ulic'),None)
        holder=next((h for h in heroes if 'stwp' in (g.inventory(h) or [])),None)
        if dk and holder:
            if not self.battle_enemies and dk and lich and g.dist(dk,lich)>1000:
                self.set_intent('采购后集结 · 等待死亡骑士归队')
                self.go([*army,*([dk] if dk not in army else [])],(lich.x,lich.y),now)
                return False
            if self.tp_waiting:
                self.log('attack_portal_ready',clock=now,hero=holder.type)
            self.tp_waiting=False;self.tp_attempts=0;self.tp_bought=False;self.tp_retry_at=0
            return True
        if optional and (inv is None or any(g.inventory(h) is None for h in heroes)):
            if self.due('attack_supply_unknown',now,15):self.log('attack_supply_unknown',clock=now,reason='inventory_unavailable_continue_attack')
            return True
        if not optional:self.set_intent('等待死亡骑士复活' if dk is None else '出征准备 · 补购回城卷轴')
        if not optional and not self.tp_waiting:
            self.tp_waiting=True
            self.log('attack_waiting_portal',clock=now,reason='dk_missing' if dk is None else 'scroll_missing')
        # Safety/micro has already run. Nearby combat is fought in place, not interrupted by shopping.
        if self.battle_enemies:
            self.set_intent('就地迎敌 · 暂缓补购回城')
            self.fight(army,self.battle_enemies,now)
            return False
        shops=self.economy.ready(g,'utom')
        shop=g.nearest(shops,dk or self.home) if shops else None
        point=(shop.x,shop.y) if shop else (self.home.x,self.home.y)
        if optional and (dk is None or shop is None or g.dist(dk,shop)>300 or None not in inv):return True
        blocked=bool(not optional and dk and shop and inv is not None and None in inv and
                     self.clear_full_shop_heroes(g.my_heroes(),dk,shop,now))
        if not optional:self.go(army,point,now)
        if blocked:return False
        if dk is None or inv is None or shop is None or g.dist(dk,shop)>300:return False
        heroes=g.my_heroes()
        if None not in inv:
            # Preserve collected items: make room by giving one to another hero, never silently discard it.
            choice=next(((i,h) for i,code in enumerate(inv) if code not in {'stwp','rnec'}
                         for h in heroes if h.handle!=dk.handle and can_receive(h,g.inventory(h),code) and g.dist(h,dk)<400),None)
            if choice and self.due('tp_make_room',now,3):
                slot,receiver=choice
                r=g.give_item(dk,slot,receiver)
                self.log('portal_make_room',clock=now,code=inv[slot],accepted=bool(r))
                if r:self.cast_until[dk.handle]=now+1.2
            elif self.due('tp_inventory_blocked',now,15):
                self.log('portal_blocked',clock=now,reason='inventory_full')
            return False
        # Unknown inventory cannot establish absence of the team's scroll.
        if any(g.inventory(h) is None for h in heroes):return False
        if self.economy.revival_pending(g):return False
        if g.resources()['gold']<350 or now<self.tp_retry_at:return optional
        if self.due('tp_buy',now,3):
            r=g.buy(shop,'stwp')
            self.tp_attempts+=1
            self.tp_bought=self.tp_bought or bool(r)
            self.log('portal_purchase',clock=now,accepted=bool(r),reason=r.reason,attempt=self.tp_attempts)
            if self.tp_attempts>=3:
                # Shop stock regenerates in 120 game seconds; bound each burst of retries.
                self.tp_retry_at=now+120
                self.tp_attempts=0
                self.log('portal_wait_stock',clock=now,retry_at=self.tp_retry_at)
        return optional # Incidental restocking never gates a formed army.

    def recover_missing_heroes(self,army,now):
        if self.action==Action.DEFEND or not self.economy.missing_heroes(self.g):return False
        self.creeping.defer(now,'hero_revival')
        self.collective_retreat(army,now)
        self.set_intent('英雄复活中 · 回补部队')
        return True

    def protect_portal_allies(self,army,pulls,now):
        # Protect only the caster/donor order; wounded teammates still need to move.
        protected={self.teleport['hero']} if self.teleport else set()
        if self.portal_handoff:protected.add(self.portal_handoff['donor'])
        active=[u for u in army if u.handle not in protected and now>=self.cast_until.get(u.handle,0)]
        caster=self.g.unit(self.teleport['hero']) if self.teleport else None
        waiting=set()
        for u in active:
            if u.handle in pulls:
                self.go_raw([u],pulls[u.handle],now)
            elif (caster and u.hp>=u.hp_max*.65 and self.g.dist(u,caster)<=900
                  and not any(in_weapon_range(self.g,e,u) for e in self.battle_enemies)):
                # AZ 023714: healthy heroes kept an old retreat order and walked
                # out while Lich channeled. AItp Area1 is 1100 in local 1.27a;
                # hold safely inside it, without pulling distant allies back.
                waiting.add(u.handle)
                if self.due(('portal_hold',u.handle),now,1):
                    accepted=bool(self.g.hold(u))
                    if accepted:self.last.pop(('go',u.handle),None)
                    self.log('portal_ally_hold',clock=now,unit=u.type,handle=u.handle,
                             caster=caster.handle,distance=round(self.g.dist(u,caster)),accepted=accepted)
        self.fight([u for u in active if u.handle not in pulls and u.handle not in waiting],self.battle_enemies,now)

    def rescue_coil_ready(self,dk,now):
        g=self.g
        return bool(dk and dk.mana>=COIL_MANA and now>=self.cast_until.get(dk.handle,0) and
                    g.cooldown(dk,'AUdc')==0 and hasattr(g,'abilities') and
                    any(a['code']=='AUdc' and a['level']>0 for a in g.abilities(dk)) and
                    not (hasattr(g,'buffs') and set(g.buffs(dk)) & DISABLED_CASTERS))

    def escape_available(self,hero,enemies,now):
        """Allow a bounded retreat when observed motion and damage permit reaching safety."""
        g=self.g;point=self.portal_pulls.get(hero.handle)
        history=self.escape_history.get(hero.handle,[])
        if point is None:return False
        if hasattr(g,'buffs') and set(g.buffs(hero)) & {'BEer','Bens','Bweb','Bwea','BSTN','Bstn','BUsl','Bcyc'}:return False
        route=g.path_distance((hero.x,hero.y),point)
        if route is None or route<40 or g.dist(hero,point)<40 or any(g.dist(point,e)<ground_attack_range(e.type)+120 for e in enemies):return False
        started=self.escape_started.setdefault(hero.handle,now)
        start=history[0] if history else (now,hero.x,hero.y,hero.hp,0)
        span=now-start[0]
        clearance=min((g.dist(hero,e)-ground_attack_range(e.type) for e in enemies),default=9999)
        progress=g.dist((start[1],start[2]),hero)
        if span>=.5:
            if clearance-start[4]<30 or progress<30:return False
            speed=progress/span;loss=max(0,start[3]-hero.hp)/span
        else:
            if now-started>=1:return False # One initial movement trial, never an endless wait.
            stats=combat.stats(hero.type,hero_level=hero.level)
            if not stats or stats.speed<=0:return False
            speed=stats.speed;loss=0
            for e in enemies:
                if in_weapon_range(g,e,hero) or (t:=g.current_target(e)) is not None and t.handle==hero.handle:
                    attacker=combat.stats(e.type,hero_level=getattr(e,'level',1))
                    if attacker:loss+=attacker.dps_vs(stats)
        escape_time=route/speed
        limit=3 if self.action==Action.CREEP and enemies and all(getattr(e,'owner',None)==12 for e in enemies) else 2
        if escape_time>limit or (loss>0 and hero.hp/loss<=escape_time+.75):return False
        if self.due(('portal_escape',hero.handle),now,2):
            self.log('teleport_deferred_escape',clock=now,hero=hero.type,hp=hero.hp,point=point,
                     clearance_gain=clearance-start[4] if span>=.5 else None,estimated_escape_seconds=escape_time,
                     evidence='observed_motion' if span>=.5 else 'bounded_initial_retreat')
        return True

    def emergency_portal(self,army,now):
        g=self.g;s=self.situation
        if self.teleport:return False
        enemies=list({e.handle:e for e in [*self.battle_enemies,*g.enemies()] if can_engage(e)}.values())
        targets={e.handle:g.current_target(e) for e in enemies}
        def threatened(u):
            return any(in_weapon_range(g,e,u) or
                       (targets[e.handle] is not None and targets[e.handle].handle==u.handle
                        and g.dist(e,u)<max(900,ground_attack_range(e.type)+100)) for e in enemies)
        heroes=[u for u in army if u.is_hero and u.hp>0]
        for u in heroes:
            history=self.escape_history.setdefault(u.handle,[])
            if not history or history[-1][0]!=now:
                clearance=min((g.dist(u,e)-ground_attack_range(e.type) for e in enemies),default=9999)
                signature=tuple(sorted(e.handle for e in enemies))
                if history and history[-1][5]!=signature:history.clear()
                history.append((now,u.x,u.y,u.hp,clearance,signature))
                history[:]=[p for p in history if now-p[0]<=2]
        endangered=sum(u.hp/u.hp_max<.3 and threatened(u) for u in army if u.type not in SKELETONS)
        low=[u for u in heroes if (u.hp/u.hp_max<.20 or self.micro.damage.urgent(u)) and threatened(u)
             and not (hasattr(g,'buffs') and 'Bvul' in g.buffs(u))]
        for u in low:
            if self.micro.damage.urgent(u) and self.due(('hero_damage_risk',u.handle),now,2):
                rate=self.micro.damage.rates[u.handle]
                self.log('hero_damage_risk',clock=now,hero=u.type,hp=u.hp,damage_per_second=rate,estimated_seconds=u.hp/rate)
        self.escape_started={h:t for h,t in self.escape_started.items() if any(u.handle==h for u in low)}
        dk=next((u for u in heroes if u.type=='Udea'),None)
        healable=[u for u in low if u.type in {'Ulic','Nbrn'} and dk and g.dist(dk,u)<750]
        # Prefer a real legal Death Coil rescue before walking or handing over the TP.
        self.rescue_coils={h:t for h,t in self.rescue_coils.items() if any(u.handle==h for u in low)}
        untreated=[u for u in healable if u.handle not in self.rescue_coils]
        if untreated and self.rescue_coil_ready(dk,now):
            self.heal_allies(army,now,untreated)
            for c in self.heal_checks:
                if c['started']==now:self.rescue_coils[c['target']]=now
        if any(c['target']==u.handle and now-c['started']<1.5 for c in self.heal_checks for u in healable):
            self.set_intent('英雄急救 · 死亡缠绕')
            return True # Accepted heal gets a bounded effect window, not permanent immunity from TP.
        self.portal_escaping={u.handle for u in low if self.escape_available(u,enemies,now)}
        critical=[u for u in low if u.handle not in self.portal_escaping]
        if critical and all((p:=self.consumables.pending.get(u.handle)) and p['code'] in {'pnvl','pnvu'} and now-p['started']<1.5 for u in critical):
            return True
        emergency=endangered>=5 or bool(critical)
        bags={u.handle:g.inventory(u) for u in heroes}
        carriers=[u for u in heroes if now>=self.cast_until.get(u.handle,0) and 'stwp' in (bags[u.handle] or []) and g.dist(u,self.home)>2200]
        pending=self.portal_handoff
        if pending:
            donor=next((u for u in heroes if u.handle==pending['donor']),None)
            receiver=next((u for u in heroes if u.handle==pending['receiver']),None)
            a=bags.get(pending['donor']);b=bags.get(pending['receiver'])
            confirmed=a is not None and b is not None and 'stwp' not in a and 'stwp' in b
            if confirmed:
                self.log('portal_transfer_confirmed',clock=now,from_hero=donor.type if donor else None,to_hero=receiver.type)
                self.portal_handoff=None
                # Re-evaluate danger; a successful handoff alone must not force a cast.
                if emergency and receiver in carriers:carriers=[receiver]
            elif not emergency or not receiver or now-pending['started']>=2:
                self.log('portal_transfer_unconfirmed',clock=now,reason='danger_cleared' if not emergency else 'receiver_missing' if not receiver else 'time_limit')
                self.portal_handoff=None
                if donor and not emergency and hasattr(g,'hold'):g.hold(donor)
            else:
                self.set_intent('紧急回城 · 递交卷轴')
                return True # Preserve the in-flight give order for at most two seconds.
        if not emergency or not carriers:return False
        endangered_carriers=[u for u in critical if u in carriers]
        h=min(endangered_carriers,key=lambda u:u.hp/u.hp_max) if endangered_carriers else max(carriers,key=lambda u:u.hp)
        receiver=min(critical,key=lambda u:u.hp/u.hp_max) if critical else h
        if receiver.handle!=h.handle and pending is None and now-self.last.get('tp_attempt',-1000)>=30:
            bag=bags[receiver.handle];route=g.path_distance((h.x,h.y),(receiver.x,receiver.y))
            available=now>=self.cast_until.get(receiver.handle,0) and bag is not None and None in bag
            if available and route is not None and route<=700 and g.dist(h,receiver)<=700 and hasattr(g,'give_item'):
                accepted=bool(g.give_item(h,bags[h.handle].index('stwp'),receiver))
                self.log('portal_transfer_attempt',clock=now,from_hero=h.type,to_hero=receiver.type,accepted=accepted)
                if accepted:
                    self.portal_handoff=dict(donor=h.handle,receiver=receiver.handle,started=now)
                    self.set_intent('紧急回城 · 递交卷轴')
                    return True
            else:
                self.log('portal_transfer_skipped',clock=now,from_hero=h.type,to_hero=receiver.type,
                         reason='inventory_or_cast_protection' if not available else 'out_of_reach')
        if self.due('tp_attempt',now,30):
            r=g.use_item(h,bags[h.handle].index('stwp'),x=self.home.x,y=self.home.y)
            self.log('teleport_attempt',clock=now,hero=h.type,accepted=bool(r),action=self.action.name,
                     army_health=s.army_health,enemy_hp=s.local_enemy_hp,endangered=endangered,critical_heroes=[u.type for u in critical])
            if r:
                self.set_intent('紧急回城 · 引导中');self.teleport={'hero':h.handle,'started':now}
                return True
        return False

    def collective_retreat(self,army,now):
        self.set_intent("撤退回家 · 恢复部队")
        if not self.emergency_portal(army,now):
            enemies=[e for e in self.g.enemies() if can_engage(e)]
            if any(self.g.dist(e,self.home)<1200 for e in enemies):
                self.set_intent('基地受围 · 脱离敌军射程')
                # Formation's home rally used to overwrite pullbacks inside the enemy army.
                for u in army:
                    if now<self.cast_until.get(u.handle,0) or u.handle in self.creep_aggro.protected or u.handle in getattr(self,'defense_shopping',set()):continue
                    if u.handle in self.shield_moves:
                        self.go_raw([u],self.shield_moves[u.handle],now);continue
                    if not self.due(('retreat_escape',u.handle),now,1.5):continue
                    point=escape_point(self.g,u,enemies,ground_attack_range,self.portal_pulls.get(u.handle),home=(self.home.x,self.home.y) if u.type=='Ulic' else None)
                    if point is not None and self.g.dist(u,point)>40:
                        self.go_raw([u],point,now)
                    elif self.due(('retreat_hold',u.handle),now,3):
                        self.g.hold(u);self.last.pop(('go',u.handle),None)
                    self.log('retreat_escape_order',clock=now,unit=u.type,handle=u.handle,
                             origin=(u.x,u.y),point=point,reason='safe_point' if point else 'no_safe_route')
                return
            escaping=[u for u in army if u.handle in self.portal_escaping]
            for u in escaping:self.go_raw([u],self.portal_pulls[u.handle],now)
            self.go([u for u in army if u.handle not in self.portal_escaping],(self.home.x,self.home.y),now)

    def observe_events(self,events):
        for event in events:
            if event.kind=='spell.cast' and event.spell in {'AHfs','AHbz'}:
                caster=self.g.unit(event.handle)
                # Fair SDK events infer casts from cooldown transitions. Their
                # x/y may fall back to the caster, so retain current order too;
                # this observation alone must never create a dodge destination.
                order=self.g.current_order(caster) if caster and hasattr(self.g,'current_order') else None
                self.log('ground_spell_observed',clock=event.clock,spell=event.spell,
                         caster=event.handle,level=event.b,event_point=(event.x,event.y),
                         caster_point=(caster.x,caster.y) if caster else None,current_order=order,
                         basis='fair_cooldown_transition_target_best_effort')
            known=self.rod_seen.get(event.handle)
            if known and event.kind in {'killed','unit.died'} and 0<=event.clock-known['clock']<4:
                point=(event.x,event.y)
                if self.g.visible(*point):
                    self.rod_corpses.setdefault(event.handle,dict(clock=event.clock,point=point,code=known['code']))
        self.hero_pressure.observe_events(events)
        scout=self.g.unit(self.economy.scout) if self.economy.scout else None
        if scout is None or self.scout_corpse is not None:return
        for event in events:
            if event.kind=='killed' and event.handle==self.scout_critter and event.source_addr==scout.addr:
                self.scout_corpse=dict(handle=event.handle,point=(event.x,event.y),clock=event.clock)
                self.log('scout_corpse_observed',clock=event.clock,handle=event.handle,
                         point=(event.x,event.y),source='fair_killed_event',killer=scout.handle)
                break

    def scout(self,now):
        g=self.g
        # Remember an observed death, never infer a corpse merely from lost vision.
        if self.scout_critter and self.scout_corpse is None:
            target=g.unit(self.scout_critter)
            if target and not target.alive and target.visible_to(g.me()):
                self.scout_corpse=dict(handle=target.handle,point=(target.x,target.y),clock=now)
                self.log('scout_corpse_observed',clock=now,handle=target.handle,point=(target.x,target.y))
        scout=g.unit(self.economy.scout) if self.economy.scout else None
        if not scout:
            return
        if scout.hp/scout.hp_max<.40:
            self.go([scout],(self.home.x,self.home.y),now)
            return
        # Enemy start is public map geometry. Mine locations enter this list only after observation.
        if now<150 and self.scout_corpse is None:
            target=self.critter_search.target(g,scout,self.home,now,safe_route=lambda a,b:self.creeping.safe_route(g,a,b))
            if target is not None:
                if target.handle!=self.scout_critter:
                    self.scout_critter=target.handle
                    self.log('scout_critter_target',clock=now,handle=target.handle,point=(target.x,target.y))
                self.scout_critter_point=(target.x,target.y);self.scout_critter_seen=now
                self.fight([scout],[target],now)
                return
            if self.scout_critter_point and self.scout_critter not in self.critter_search.hunt_failed and now-self.scout_critter_seen<6:
                self.go([scout],self.scout_critter_point,now)
            else:
                point=self.critter_search.choose(g,scout,self.home,now,safe_route=lambda a,b:self.creeping.safe_route(g,a,b))
                if point is not None:
                    self.go([scout],point,now)
                    return
                if not self.critter_search.reported:
                    self.go([scout],(self.home.x,self.home.y),now)
                    return
            if not self.critter_search.reported:return
        if not self.enemy_main:
            point=self.start_search.choose(g,scout,now)
            if point:self.go([scout],point,now)
            return
        mines=[u for u in self.memory.units.values() if u.type in {'ngol','ugol','egol'}
               and hypot(u.x-self.enemy_main[0],u.y-self.enemy_main[1])<3000]
        targets=[self.enemy_main]+[(m.x,m.y) for m in mines]
        idx=int(now//25)%len(targets)
        self.go([scout],targets[idx],now)

    def observe_race(self,foes,now):
        if self.enemy_race:return
        from .race_data import unit_races
        for u in foes:
            if not (u.alive and u.visible_to(self.g.me()) and 0<=u.owner<12 and u.owner!=self.g.me()):continue
            race=unit_races().get(u.type)
            if race:
                self.enemy_race=race
                if not self.tavern_mission and not (self.economy.ever_heroes & {'Nbrn','Nngs'}):
                    self.third_hero='Nngs' if race==4 else 'Nbrn'
                    self.economy.third_hero=self.third_hero
                self.log('enemy_race_observed',clock=now,race=race,unit=u.type,third_hero=self.third_hero)
                break

    def observe_air(self,foes,now):
        g=self.g
        for enemy in foes:
            if not airborne(enemy.type):continue
            if not (0<=enemy.owner<12 and enemy.owner!=g.me() and enemy.alive and enemy.visible_to(g.me())):continue
            self.economy.enemy_air_seen=True
            if enemy.type not in self.air_types:
                self.air_types.add(enemy.type)
                self.log('enemy_air_sighted',clock=now,code=enemy.type)
            if self.economy.web_level and self.due(('web_effect',enemy.handle),now,2):
                if {'Bwea','Bweb'} & set(g.buffs(enemy)) and enemy.handle not in self.web_effects:
                    self.web_effects.add(enemy.handle)
                    self.log('web_effect_observed',clock=now,target=enemy.type,handle=enemy.handle)

    def skills(self,now):
        g=self.g
        own_handles={h.handle for h in g.my_heroes()}
        self.autocast_states={k:v for k,v in self.autocast_states.items() if k[0] in own_handles}
        dark_handles={h.handle for h in g.my_heroes() if h.type=='Nbrn'}
        self.black_arrow_enabled={key for key in self.black_arrow_enabled if key[0] in dark_handles}
        self.black_arrow_attempts={key:value for key,value in self.black_arrow_attempts.items() if key[0] in dark_handles}
        orders={'Udea':['AUdc','AUau','AUdc','AUau','AUdc','AUan','AUau','AUdp','AUdp','AUdp'],
                'Ulic':['AUfn','AUfu','AUfn','AUdr','AUfn','AUdd','AUdr','AUdr','AUfu','AUfu'],
                'Nngs':['ANfa','ANfl','ANfl','ANfa','ANfl','ANto','ANfa','ANms','ANms','ANms'],
                'Nbrn':['ANba','ANsi','ANba','ANsi','ANba','ANch','ANsi','ANdr','ANdr','ANdr']}
        for h in g.my_heroes():
            if self.teleport and h.handle==self.teleport['hero']:continue
            if now<self.cast_until.get(h.handle,0):continue
            if h.skill_points and self.due(('learn',h.handle),now,1):
                seq=orders.get(h.type,[])
                idx=max(0,h.level-h.skill_points)
                if idx<len(seq):
                    r=g.learn(h,seq[idx])
                    self.log('hero_skill_learn_attempt',clock=now,hero=h.type,hero_level=h.level,
                             spent_points=idx,ability=seq[idx],accepted=bool(r))
            if h.type in {'Ulic','Nngs'} and now>=self.cast_until.get(h.handle,0):
                code,order=('AUfu','frostarmoroff') if h.type=='Ulic' else ('ANfa','coldarrows')
                level=next((a['level'] for a in g.abilities(h) if a['code']==code),0)
                key=(h.handle,code,level)
                state=self.autocast_states.setdefault(key,dict(failures=0,at=-100))
                if level>0 and state['failures']<3 and now-state['at']>=20:
                    r=g.cast(h,order);state['at']=now
                    state['failures']=0 if r else state['failures']+1
                    self.log('hero_autocast_order',clock=now,hero=h.type,ability=code,level=level,
                             order=order,accepted=bool(r),consecutive_failures=state['failures'])
            if h.type=='Nbrn':
                level=next((a['level'] for a in g.abilities(h) if a['code']=='ANba'),0)
                key=(h.handle,level)
                attempts=self.black_arrow_attempts.get(key,0)
                if level>0 and key not in self.black_arrow_enabled and attempts<3 and self.due(('black_arrow',h.handle),now,5):
                    r=g.cast(h,'blackarrowon')
                    self.black_arrow_attempts[key]=attempts+1
                    self.log('black_arrow_autocast_attempt',clock=now,level=level,accepted=bool(r),attempt=attempts+1)
                    if r:self.black_arrow_enabled.add(key)
        self.army_recovery.statues(self,now)

    def items(self,now,tier):
        # After tier three, Black Arrow supplies skeletons; do not restock rods.
        self.rod_purchase_closed = self.rod_purchase_closed or tier >= 3
        g=self.g
        heroes=g.my_heroes()
        dk=next((h for h in heroes if h.type=='Udea'),None)
        if not attack_ready(self.situation) and dk and not any('stwp' in (g.inventory(h) or []) for h in heroes) and (self.action in (Action.ATTACK,Action.HARASS) or choose_rule(self.situation) in (Action.ATTACK,Action.HARASS)):
            return # portal preparation owns shopping until a team inventory confirms it
        shops=self.economy.ready(g,'utom')
        for h in heroes:
            if self.teleport and h.handle==self.teleport['hero']:continue
            if now<self.cast_until.get(h.handle,0):continue
            inv=g.inventory(h)
            if inv is None:
                continue
            self.ever_rod=self.ever_rod or 'rnec' in inv
            code='rnec' if not self.rod_purchase_closed and self.economy.opening_rod_allowed and h.type=='Udea' and 'rnec' not in inv and (not self.ever_rod or g.dist(h,self.home)<900) else None
            if code and self.action!=Action.ATTACK and shops and None in inv and h.hp/h.hp_max>.5 and not self.situation.threatened and not self.battle_enemies:
                shop=g.nearest(shops,h)
                if self.shop_item(heroes,h,shop,code,now):
                    self.shop_goal=(shop.x,shop.y)
                    self.shop_code=code
            if h.type=='Udea' and 'rnec' in inv and not self.opening_corpse_pending(now):
                self.maintain_skeletons(h,inv.index('rnec'),now)
        jobs=self.bank_supply_jobs(now)
        if jobs:
            hero,shop,code,cost=jobs[0]
            if g.resources()['gold']>=cost+self.economy.optional_reserve(g,now):
                self.battle_shop.transact(g,hero,code,'buy',now,self.cast_until,shop)
        else:self.restock_scrolls(now,heroes,shops)
        for h in heroes:
            for code in ('rnec','ocor'):
                if code in (g.inventory(h) or []) and self.due(('item_seen',h.handle,code),now,600):
                    self.log('item_confirmed',hero=h.type,code=code,clock=now)

    def observe_rod_corpses(self,units,now):
        self.rod_seen={h:v for h,v in self.rod_seen.items() if now-v['clock']<4}
        self.rod_corpses={h:v for h,v in self.rod_corpses.items() if now-v['clock']<60 and h not in self.rod_used}
        for u in units:
            if is_structure(u) or u.is_hero or u.type in SKELETONS or airborne(u.type):continue
            if not (getattr(u,'owner',None)==self.g.me() or getattr(u,'visible_to',lambda me:False)(self.g.me())):continue
            if getattr(u,'alive',u.hp>0):
                self.rod_seen[u.handle]=dict(clock=now,point=(u.x,u.y),code=u.type)
            elif u.handle not in self.rod_used:
                self.rod_corpses.setdefault(u.handle,dict(clock=now,point=(u.x,u.y),code=u.type))

    def maintain_skeletons(self,dk,slot,now):
        g=self.g
        if now<self.rod_retry or now<self.cast_until.get(dk.handle,0) or dk.handle in self.micro.pulling:return False
        if g.cooldown(dk,'AIrd')!=0:return False
        # Local combat summons matter; a distant scout must not suppress reinforcement.
        if sum(g.dist(dk,u)<1200 for u in g.units('me',SKELETONS))>=4:return False
        corpses=[(g.dist(dk,c['point']),h,c) for h,c in self.rod_corpses.items()
                 if h not in self.rod_used and now-c['clock']<60 and g.dist(dk,c['point'])<=850
                 and self.rod_attempts.get((dk.handle,h),0)<3]
        if not corpses:return False
        _,handle,corpse=min(corpses)
        self.rod_attempts[(dk.handle,handle)]=self.rod_attempts.get((dk.handle,handle),0)+1
        self.rod_retry=now+3
        result=self.use_rod(dk,slot,now)
        if result:self.rod_birth_windows[-1]['corpse']=handle
        self.log('rod',clock=now,accepted=bool(result),corpse=handle,corpse_distance=round(g.dist(dk,corpse['point'])),
                 cooldown=0,attempt=self.rod_attempts[(dk.handle,handle)])
        return bool(result)

    def use_rod(self,hero,slot,now):
        before={u.handle for u in self.g.units('me',{'uske'})}
        result=self.g.use_item(hero,slot)
        if result:
            self.cast_until[hero.handle]=max(self.cast_until.get(hero.handle,0),now+1.2)
            self.rod_birth_windows.append(dict(clock=now,origin=(hero.x,hero.y),before=before,confirmed=set()))
        return result

    def observe_rod_skeletons(self,now):
        live={u.handle:u for u in self.g.units('me',{'uske'})}
        self.skeleton_expiry={h:t for h,t in self.skeleton_expiry.items() if h in live and t>now}
        for w in self.rod_birth_windows:
            if now-w['clock']>3 and not w['confirmed']:
                self.log('rod_summon_unconfirmed',clock=now,cast_clock=w['clock'],corpse=w.get('corpse'))
        self.rod_birth_windows=[w for w in self.rod_birth_windows if 0<=now-w['clock']<=3]
        for w in self.rod_birth_windows:
            for h,u in live.items():
                if h in w['before'] or h in w['confirmed'] or h in self.skeleton_expiry or len(w['confirmed'])>=2:continue
                if self.g.dist(u,w['origin'])>1200:continue
                duration=rod_skeleton_lifetime()
                if duration<=0:continue
                # The accepted cast precedes the observed spawn: this is a conservative
                # expiry bound. An old/unknown skeleton never gets a fresh 65 seconds.
                self.skeleton_expiry[h]=w['clock']+duration
                w['confirmed'].add(h)
                if w.get('corpse') is not None:self.rod_used.add(w['corpse'])
                self.log('rod_skeleton_lifetime_observed',clock=now,handle=h,cast_clock=w['clock'],
                         expiry_lower_bound=self.skeleton_expiry[h],duration=duration)

    def tavern_lifetime_budget(self,u,now,length,known_tavern):
        remaining=self.skeleton_expiry.get(u.handle,now)-now
        # Conservative 180 movement speed plus 50% detour allowance, 12s for hiring,
        # and 10s for discovering the unseen tavern after reaching the public centre.
        required=length/180*1.5+12+(0 if known_tavern else 10)
        return remaining,required

    def tavern_destination(self,courier,taverns):
        points=[(t.x,t.y) for t in taverns] or self.tavern_sites or [(0,0)]
        reachable=[]
        for point in points:
            length=self.g.path_distance((courier.x,courier.y),point)
            if length is not None:reachable.append((length,point))
        return min(reachable)[1] if reachable else None

    def recruit_tavern(self,army,hostiles,now,tier,blocked):
        """One long-lived skeleton or healthy fiend buys independently."""
        if tier!=3 and not self.tavern_mission and not self.tavern_joiners:return set()
        g=self.g;own={u.handle:u for u in army}
        third=[u for u in army if u.type==self.third_hero]
        for hero in third:
            if hero.handle not in self.tavern_seen:
                self.tavern_seen.add(hero.handle);self.tavern_joiners.add(hero.handle)
                self.log('tavern_hero_observed',clock=now,hero=hero.type,handle=hero.handle,point=(hero.x,hero.y))
        mission=self.tavern_mission
        unsafe=bool(self.player_contact) or bool(self.economy.revival_pending(g)) or self.action in (Action.RETREAT,Action.DEFEND) or self.situation.threatened or bool(self.teleport) or bool(self.micro.dk_support)
        if unsafe and not mission and not self.tavern_joiners:return set()
        def cancel(reason):
            self.tavern_joiners.add(mission['courier'])
            self.tavern_mission=None;self.tavern_retry_at=now+30
            self.log('tavern_dispatch_end',clock=now,reason=reason,courier=mission['courier'])
        if mission:
            courier=own.get(mission['courier'])
            if third or self.third_hero in self.economy.ever_heroes:cancel('hero_observed')
            elif courier is None:cancel('courier_missing')
            elif unsafe or courier.handle in blocked or courier.hp/courier.hp_max<.65 or any(g.dist(courier,e)<700 for e in hostiles):cancel('unsafe')
            elif now-mission['started']>120 or now-mission['progress_at']>25:cancel('travel_timeout')
        res=g.resources()
        affordable=res['gold']>=425+self.battle_shop.orb_reserve(g) and res['lumber']>=135 and res['food_cap']-res['food_used']>=5
        if not self.tavern_mission and not self.tavern_joiners and not unsafe and not self.battle_enemies and not third and self.third_hero not in self.economy.ever_heroes and tier==3 and self.situation.fiends>=4 and self.situation.statues>=1 and affordable and self.tavern_trips<3 and now>=self.tavern_retry_at:
            taverns=g.units('all',{'ntav'})
            # Static map placements guide scouting; only a fair visible shop can be bought from.
            choices=[]
            spare_skeletons=sum(u.type=='uske' and u.handle not in self.skeleton_scouts.assignments for u in army)
            for u in army:
                if u.type not in {'uske','ucry'} or u.handle in self.skeleton_scouts.assignments or u.handle in blocked or u.hp/u.hp_max<.8 or any(g.dist(u,e)<700 for e in hostiles):continue
                target=self.tavern_destination(u,taverns)
                if target is None:continue
                length=g.path_distance((u.x,u.y),target)
                if length is None:continue
                if u.type=='uske':
                    if self.attacking_main and spare_skeletons<=2:continue
                    remaining,required=self.tavern_lifetime_budget(u,now,length,bool(taverns))
                    if remaining<max(30,required):continue
                    choices.append((0,-remaining,length,u.handle,u,target))
                else:choices.append((1,0,length,u.handle,u,target))
            if choices:
                _,_,_,_,courier,target=min(choices)
                self.tavern_trips+=1
                self.tavern_mission=dict(courier=courier.handle,started=now,progress_at=now,best=None,target=None,scout_target=target,buys=0,buy_at=-100,accepted_at=None)
                self.log('tavern_dispatch',clock=now,courier=courier.handle,type=courier.type,target=target,trip=self.tavern_trips,
                         lifetime_remaining=self.skeleton_expiry.get(courier.handle,now)-now if courier.type=='uske' else None,
                         lifetime_required=self.tavern_lifetime_budget(courier,now,g.path_distance((courier.x,courier.y),target),bool(taverns))[1] if courier.type=='uske' else None)
        mission=self.tavern_mission
        if mission:
            courier=own[mission['courier']]
            taverns=g.units('all',{'ntav'})
            visible_target=self.tavern_destination(courier,taverns) if taverns else None
            tavern=next((t for t in taverns if (t.x,t.y)==visible_target),None)
            target=visible_target if tavern else mission['scout_target']
            length=g.path_distance((courier.x,courier.y),target)
            if target!=mission['target']:
                mission.update(target=target,best=None,progress_at=now)
            if length is None:cancel('unreachable')
            elif courier.type=='uske' and self.tavern_lifetime_budget(courier,now,length,bool(tavern))[0]<self.tavern_lifetime_budget(courier,now,length,bool(tavern))[1]:cancel('lifetime_insufficient')
            elif mission['accepted_at'] is not None and now-mission['accepted_at']<8:
                pass # Receipt is not proof of a new hero; allow the fair snapshot to confirm.
            elif mission['buys']>=3:cancel('hire_unconfirmed')
            else:
                if mission['best'] is None or length<mission['best']-80:
                    mission.update(best=length,progress_at=now)
                if tavern and g.dist(courier,tavern)<=300:
                    if affordable and now-mission['buy_at']>=5:
                        result=g.buy(tavern,self.third_hero)
                        mission['buys']+=1;mission['buy_at']=now
                        mission['accepted_at']=now if result else None
                        self.log('hire',clock=now,hero=self.third_hero,courier=courier.handle,accepted=bool(result),reason=result.reason,attempt=mission['buys'])
                else:self.go_raw([courier],target,now,False)
                if self.due('tavern_travel',now,3):
                    self.log('tavern_travel',clock=now,courier=courier.handle,point=(courier.x,courier.y),target=target,distance=length)
        self.tavern_joiners.intersection_update(own)
        reserved=set(self.tavern_joiners)
        if self.tavern_mission:reserved.add(self.tavern_mission['courier'])
        main=[u for u in army if u.handle not in reserved and u.type not in SKELETONS]
        anchor=min(main,key=lambda u:sum(g.dist(u,v) for v in main)) if main else self.home
        point=(self.home.x,self.home.y) if unsafe else (anchor.x,anchor.y)
        for handle in list(self.tavern_joiners):
            u=own[handle];length=g.path_distance((u.x,u.y),point)
            if g.dist(u,point)<=500 and length is not None and length<=700:
                self.tavern_joiners.remove(handle)
                self.log('tavern_rejoined',clock=now,handle=handle,type=u.type,point=(u.x,u.y),main=point,distance=length)
            elif handle not in blocked:
                self.go_raw([u],point,now,False)
                if self.due(('tavern_return',handle),now,3):
                    self.log('tavern_return',clock=now,handle=handle,type=u.type,point=(u.x,u.y),main=point,distance=length)
        # Reserve for this tick even on arrival, avoiding a second movement order.
        return reserved

    def bank_supply_jobs(self,now):
        """Budget only currently reachable, needed supplies; never recall the army."""
        g=self.g;res=g.resources()
        if not (self.situation.tier==3 and self.situation.orb) or res.get('food_used',0)<48 or self.economy.upkeep_released or now<440 or self.teleport or self.situation.threatened or self.battle_enemies:return []
        heroes=g.my_heroes();bags={h.handle:g.inventory(h) for h in heroes}
        if any(bag is None for bag in bags.values()) or self.economy.revival_pending(g):return []
        shops=self.economy.ready(g,'utom');jobs=[]
        dk=next((h for h in heroes if h.type=='Udea'),None)
        wants=[]
        if dk and dk.mana<75 and not any(c in {'pman','pgma','mnst','pres'} for bag in bags.values() for c in bag):wants.append((dk,'pman',200))
        if not any(c in {'shea','sres'} for bag in bags.values() for c in bag):
            receiver=next((h for h in heroes if can_receive(h,bags[h.handle],'shea') and any(g.dist(h,s)<=280 for s in shops)),None)
            if receiver:wants.append((receiver,'shea',250))
        for hero,code,cost in wants:
            if not can_receive(hero,bags[hero.handle],code) or hero.hp/hero.hp_max<.6:continue
            shop=next((s for s in shops if g.dist(hero,s)<=280),None)
            if shop is None:continue
            key=('buy',hero.handle,code,tuple(bags[hero.handle]),shop.handle,int(now//120))
            if self.battle_shop.attempts.get(key,0)<3:jobs.append((hero,shop,code,cost))
        return jobs

    def restock_scrolls(self,now,heroes,shops):
        # Only incidental resupply at home. Never set shop_goal or move the army
        # for optional scrolls; leaving home, lack of space or stock simply skips.
        g=self.g
        if not self.home or g.resources().get('food_used',0)<50:return
        if g.resources()['food_used']<=50 and not self.economy.upkeep_released:return
        home_shops=[s for s in shops if s.type=='utom' and g.dist(s,self.home)<1200]
        at_home=any(g.dist(h,self.home)<1200 and any(g.dist(h,s)<=300 for s in home_shops) for h in heroes)
        safe=at_home and not self.teleport and not self.situation.threatened and not self.battle_enemies
        reserve=self.economy.optional_reserve(g,now) if safe else float('inf')
        self.scroll_supply.tick(g,heroes,home_shops,now,reserve,self.cast_until,safe)

    def shop_item(self,heroes,hero,shop,code,now):
        """Shop chooses a nearby recipient, not necessarily the requested hero."""
        g=self.g;key=(hero.handle,code)
        inventory=g.inventory(hero)
        if inventory is None or None not in inventory:return False
        holder=next((h for h in heroes if h.handle!=hero.handle and code in (g.inventory(h) or [])),None)
        if holder:
            if self.due(('transfer',hero.handle,code),now,3):
                r=g.give_item(holder,g.inventory(holder).index(code),hero)
                self.log('shop_item_transfer',clock=now,code=code,from_hero=holder.type,to_hero=hero.type,accepted=bool(r))
                if r:self.cast_until[holder.handle]=now+1.2
            return True
        if self.economy.revival_pending(g):return False
        if now<self.shop_retry_at.get(key,0):return False
        # ItemData.slk: rod 150g/60s stock, orb 375g/120s stock. Do not spam unaffordable buys.
        if g.resources()['gold']<{'rnec':150,'ocor':375}[code]:return False
        blockers=[h for h in heroes if g.dist(h,shop)<900 and (g.inventory(h) is not None and None not in g.inventory(h))]
        for donor in blockers:
            bag=g.inventory(donor)
            slot=next((i for i,c in enumerate(bag) if c not in {'stwp','rnec','ocor'}),None)
            receiver=next((h for h in heroes if h.handle!=donor.handle and slot is not None and
                           can_receive(h,g.inventory(h),bag[slot]) and
                           (g.inventory(h) or []).count(None)>=(2 if h.handle==hero.handle else 1)),None)
            signature=(donor.handle,tuple(bag))
            attempts=self.shop_room_attempts.get(signature,0)
            if receiver is None or slot is None:
                self.clear_full_shop_heroes(heroes,hero,shop,now)
                return True
            if attempts>=3:
                self.shop_retry_at[key]=now+120
                self.log('shop_wait',clock=now,code=code,reason='recipient_inventory_blocked',retry_at=now+120)
                return False
            if g.dist(donor,receiver)<400 and self.due(('shop_make_room',donor.handle),now,3):
                self.shop_room_attempts[signature]=attempts+1
                r=g.give_item(donor,slot,receiver)
                self.log('shop_make_room',clock=now,code=bag[slot],from_hero=donor.type,to_hero=receiver.type,accepted=bool(r))
                if r:self.cast_until[donor.handle]=now+1.2
            return True # wait for observed free slot before purchasing
        if g.dist(hero,shop)>300:return True
        if self.due(('buy',hero.handle,code),now,3):
            r=g.buy(shop,code)
            attempts=self.shop_attempts.get(key,0)+1;self.shop_attempts[key]=attempts
            self.log('buy',clock=now,code=code,hero=hero.type,accepted=bool(r),reason=r.reason,inventory=inventory,attempt=attempts)
            if attempts>=3:
                self.shop_attempts[key]=0;self.shop_retry_at[key]=now+120
                self.log('shop_wait',clock=now,code=code,reason='unconfirmed_purchase_limit',retry_at=now+120)
        return True

    def clear_full_shop_heroes(self,heroes,buyer,shop,now):
        """Keep full inventories intact while removing unintended shop recipients."""
        g=self.g
        full=[h for h in heroes if h.handle!=buyer.handle and g.inventory(h) is not None and None not in g.inventory(h)]
        self.shopping.update(h.handle for h in full)
        nearby=[h for h in full if g.dist(h,shop)<1050]
        if not nearby:return False
        mp=getattr(g,'map',lambda:None)()
        angle=atan2(self.home.y-shop.y,self.home.x-shop.x) if self.home else pi
        for h in nearby:
            if mp is None or h.handle in self.shield_moves:continue
            points=[(shop.x+1200*cos(angle+offset),shop.y+1200*sin(angle+offset))
                    for offset in (0,pi/4,-pi/4,pi/2,-pi/2,pi)]
            point=next((p for p in points if mp.walkable(*p) and
                        (route:=g.path_distance((h.x,h.y),p)) is not None and route<2400),None)
            if point:
                self.go_raw([h],point,now)
                if self.due(('shop_clearance',h.handle),now,5):
                    self.log('shop_inventory_clearance',clock=now,hero=h.type,point=point)
            elif self.due(('shop_clearance_blocked',h.handle),now,15):
                self.log('shop_wait',clock=now,reason='full_recipient_no_safe_route',hero=h.type)
        return True

    def frost_armor(self,army,hostiles,now):
        g=self.g
        for check in list(self.frost_armor_checks):
            hero=g.unit(check['handle'])
            if hero and 'BUfa' in g.buffs(hero):
                self.log('frost_armor_observed',clock=now,hero=hero.type,handle=hero.handle,
                         cast_clock=check['started'])
                self.frost_armor_checks.remove(check)
            elif hero is None or now-check['started']>3:
                self.log('frost_armor_unconfirmed',clock=now,handle=check['handle'])
                self.frost_armor_checks.remove(check)
        lich=next((u for u in army if u.type=='Ulic'),None)
        if (not lich or self.action==Action.RETREAT or self.teleport or lich.mana<40 or
            lich.handle in self.micro.pulling or lich.handle in self.shield_moves or
            now<self.cast_until.get(lich.handle,0) or g.cooldown(lich,'AUfu')!=0):return
        if not any(a['code']=='AUfu' and a['level']>0 for a in g.abilities(lich)):return
        candidates=[]
        for hero in army:
            if not hero.is_hero or g.dist(lich,hero)>800 or 'BUfa' in g.buffs(hero):continue
            attackers=[]
            for enemy in hostiles:
                if is_structure(enemy):continue
                reach=ground_attack_range(enemy.type)
                if not 0<reach<=200 or g.dist(enemy,hero)>reach+160:continue
                target=g.current_target(enemy)
                if target and target.handle==hero.handle:attackers.append(enemy)
            if attackers:candidates.append((hero,attackers))
        if not candidates or not self.due('frost_armor',now,1):return
        hero,attackers=min(candidates,key=lambda pair:(pair[0].hp/pair[0].hp_max,-len(pair[1])))
        r=g.cast(lich,'frostarmor',target=hero)
        self.log('frost_armor_attempt',clock=now,hero=hero.type,handle=hero.handle,accepted=bool(r),
                 hp=hero.hp,melee_attackers=[dict(type=e.type,handle=e.handle) for e in attackers])
        if r:
            self.cast_until[lich.handle]=now+.8
            self.frost_armor_checks.append(dict(handle=hero.handle,started=now))

    def coil_needed(self,dk):
        g=self.g
        if not dk or dk.mana>=COIL_MANA or g.cooldown(dk,'AUdc')!=0:return False
        if not any(a['code']=='AUdc' and a['level']>0 for a in g.abilities(dk)):return False
        if self.heal_candidates(dk):return True
        if self.action==Action.RETREAT:return False
        target=g.current_target(dk)
        return bool(target and any(e.handle==target.handle for e in self.battle_enemies)
                    and not is_structure(target) and can_damage(target.type) and g.dist(dk,target)<750)

    def heal_candidates(self,dk):
        # UnitBalance.slk marks Nbrn undead and uobs Mechanical; coil cannot heal statues.
        return [u for u in self.g.units('me',{'Ulic','Nbrn','ucry','ugho'})
                if (u.hp_max-u.hp>=100 or u.hp/u.hp_max<.45) and self.g.dist(dk,u)<750]

    def combat_spells(self,army,foes,now,blocked=()):
        self.nc_combo.observe(self.g,now)
        dk=next((u for u in army if u.type=='Udea'),None)
        critical=[u for u in self.heal_candidates(dk) if u.is_hero and u.hp/u.hp_max<=.25] if dk else []
        if critical:
            self.heal_allies(army,now,critical)
            return
        if self.action!=Action.RETREAT and not self.teleport and not self.army_recovery.active:
            excluded=set(blocked)|set(self.micro.pulling)|set(self.shield_moves)|self.creep_aggro.protected
            target=self.nc_combo.try_cast(self.g,army,foes,now,self.cast_until,excluded)
            # Pressure NC requires supporting attacks; real healing remains first.
            if target is None and not (dk and self.heal_candidates(dk)):
                dangerous=[e for e in foes if aoe_threat(self.g,e) and
                           sum(u.handle not in excluded and u.type!='uobs' and in_weapon_range(self.g,u,e)
                               for u in army)>=2]
                self.nc_combo.try_cast(self.g,army,dangerous,now,self.cast_until,excluded,pressure=True)
        self.heal_allies(army,now)

    def heal_allies(self,army,now,candidates=None):
        g=self.g
        for check in list(self.heal_checks):
            victim=g.unit(check['target'])
            if victim and victim.hp>check['hp']+50:
                self.log('coil_heal_observed',clock=now,unit=victim.type,hp_gain=round(victim.hp-check['hp']))
                self.heal_checks.remove(check)
            elif now-check['started']>3 or victim is None:
                self.heal_checks.remove(check)
        dk=next((u for u in army if u.type=='Udea'),None)
        if not dk or dk.mana<COIL_MANA or now<self.cast_until.get(dk.handle,0) or g.cooldown(dk,'AUdc')!=0:
            return
        hurt=self.heal_candidates(dk) if candidates is None else candidates
        if hurt and self.due('coil',now,1):
            victim=min(hurt,key=lambda u:({'Ulic':0,'Nbrn':1,'ucry':2}.get(u.type,3),u.hp/u.hp_max))
            r=g.cast(dk,'deathcoil',target=victim)
            self.log('coil_heal_attempt',clock=now,target=victim.type,accepted=bool(r),mana=dk.mana)
            if r:
                self.cast_until[dk.handle]=now+.8
                self.heal_checks.append({'target':victim.handle,'hp':victim.hp,'started':now})

    def stop_hero_chases(self,army,now):
        g=self.g
        if not self.hero_attack_targets and not any(e.is_hero and enemy_player(g,e) for e in self.battle_enemies):return
        for u in army:
            if u.type=='uobs' or now<self.cast_until.get(u.handle,0):continue
            current=g.current_target(u)
            remembered=self.hero_attack_targets.get(u.handle)
            hero=current if current and current.is_hero and enemy_player(g,current) else None
            lost=remembered is not None and current is None and g.unit(remembered) is None
            if (hero and not in_weapon_range(g,u,hero)) or lost:
                if self.due(('release_hero',u.handle),now,1):
                    accepted=bool(g.hold(u))
                    self.log('hero_chase_released',clock=now,unit=u.type,handle=u.handle,
                             target=hero.handle if hero else remembered,accepted=accepted)
                    if accepted:
                        self.hero_attack_targets.pop(u.handle,None)
                        self.last.pop(('go',u.handle),None)
            elif current and not hero:
                self.hero_attack_targets.pop(u.handle,None)

    def focus_siege(self,army,foes,now):
        if self.action not in (Action.ATTACK,Action.HARASS):return False
        g=self.g
        # Refresh the full fair enemy list: a caller's melee subset must not hide
        # a defender or a higher-priority tower on the other side of this base.
        visible=[e for e in (g.enemies() if hasattr(g,'enemies') else foes)
                 if can_engage(e) and self.combat_progress.allowed(e,now)]
        army=[u for u in army if u.handle not in self.shield_moves and
              u.handle not in self.creep_aggro.protected and u.handle not in self.micro.pulling and
              (u.handle not in self.shopping or self.battle_enemies) and
              u.handle not in self.tavern_joiners and (not self.tavern_mission or u.handle!=self.tavern_mission['courier']) and
              u.handle not in self.skeleton_scouts.assignments]
        target=self.siege.choose(g,army,visible,now)
        if target is None:return False
        core=[u for u in army if u.type not in SKELETONS and u.type!='uobs'] or army
        anchor=min(core,key=lambda u:sum(g.dist(u,v) for v in core))
        self.set_intent('集中消灭维修工人' if not is_structure(target) else '集中攻击敌方建筑')
        self.creeping.pause(now,'siege')
        for u in army:
            if now<self.cast_until.get(u.handle,0):continue
            if g.dist(u,anchor)>=700 or u.type=='uobs':
                if g.dist(u,anchor)>400:self.go_raw([u],(anchor.x,anchor.y),now)
                continue
            if not siege_attackable(g,u,target) or not siege_reachable(g,u,target):continue
            current=g.current_target(u)
            if (not current or current.handle!=target.handle) and self.due(('attack',u.handle),now,1.2):
                accepted=bool(g.attack(u,target))
                if accepted:
                    self.hero_attack_targets.pop(u.handle,None)
                    self.last.pop(('go',u.handle),None)
                self.log('siege_focus',clock=now,handle=u.handle,type=u.type,target=target.handle,
                         target_type=target.type,accepted=accepted,distance=round(g.dist(u,target)))
        return True

    def fight(self,army,foes,now):
        g=self.g
        foes=[e for e in foes if can_engage(e) and self.combat_progress.allowed(e,now)]
        if self.action==Action.DEFEND:foes=[e for e in foes if enemy_player(g,e)]
        army=[u for u in army if u.handle not in self.shield_moves and u.handle not in self.creep_aggro.protected and (u.handle not in self.shopping or self.action in (Action.RETREAT,Action.DEFEND) or self.battle_enemies)]
        self.stop_hero_chases(army,now)
        if self.action==Action.CREEP and not attack_ready(self.situation):
            foes=[e for e in foes if not (enemy_player(self.g,e) and is_structure(e))]
        players=[e for e in foes if enemy_player(g,e) and not is_structure(e)]
        if players:foes=players
        if not army or not foes:
            return
        if self.focus_siege(army,foes,now):return
        if not players:
            anchor=min(army,key=lambda u:sum(g.dist(u,v) for v in army))
            foes=[e for e in self.creeping.include_drop_carriers(g,foes,anchor)
                  if can_engage(e) and self.combat_progress.allowed(e,now)]
        if self.skeleton_opening(army,foes,now):return
        combat=[u for u in army if u.type in {'Udea','Ulic','Nbrn','Nngs','ucry','uobs'}]
        if len(combat)>1 and not self.player_contact:
            anchor=min(combat,key=lambda u:sum(g.dist(u,v) for v in combat))
            limit=650
            foes=[e for e in foes if g.dist(e,anchor)<limit or
                  (not players and self.creeping.carries_drop(e) and g.dist(e,anchor)<900)]
            army=[u for u in army if g.dist(u,anchor)<700]
            if not foes: return
        player_fight=any(enemy_player(g,e) for e in foes)
        pressure=self.hero_pressure.choose(g,army,foes,now) if player_fight else None
        target=self.nc_combo.focus(foes,now) or pressure or min(foes,key=lambda u:(not self.creeping.carries_drop(u) if not player_fight else False,u.hp+(400 if is_structure(u) else 0)))
        single_finishing=bool(self.nc_combo.pending) or self.nc_combo.single_attempt_at==now or (player_fight and pressure is None)
        protected=set()
        dk=next((u for u in army if u.type=='Udea'),None)
        lich=next((u for u in army if u.type=='Ulic'),None)
        if not single_finishing and dk and dk.mana>=COIL_MANA and now>=self.cast_until.get(dk.handle,0) and g.cooldown(dk,'AUdc')==0 and self.due('coil',now,1):
            wounded=self.heal_candidates(dk)
            if (not wounded and can_damage(target.type) and not is_structure(target) and g.dist(dk,target)<750
                    and (player_fight or dk.mana>=2*COIL_MANA)):
                receipt=g.cast(dk,'deathcoil',target=target)
                self.log('coil_damage_attempt',clock=now,target=target.type,accepted=bool(receipt),mana=dk.mana,reason=getattr(receipt,'reason',None))
                if receipt:
                    self.cast_until[dk.handle]=now+.8
                    protected.add(dk.handle)
        if not single_finishing and lich and now>=self.cast_until.get(lich.handle,0) and lich.mana>=125 and g.cooldown(lich,'AUfn')==0 and g.dist(lich,target)<750 and self.due('nova',now,1):
            if g.cast(lich,'frostnova',target=target):
                self.cast_until[lich.handle]=now+.8
                protected.add(lich.handle)
        naga=next((u for u in army if u.type=='Nngs'),None)
        if naga:
            # Observe a real cold-arrow buff; an autocast receipt alone is not an effect.
            if self.due('frost_arrow_effect',now,1):
                arrow_target=g.current_target(naga)
                if arrow_target and arrow_target.handle not in self.frost_arrow_effects and g.dist(naga,arrow_target)<700:
                    buffs=set(g.buffs(arrow_target)) & {'BHca','Bcsd','Bcsi'}
                    if 'BHca' in buffs:
                        self.frost_arrow_effects.add(arrow_target.handle)
                        self.log('frost_arrow_effect_observed',clock=now,target=arrow_target.type,
                                 handle=arrow_target.handle,buffs=sorted(buffs))
            if (not single_finishing and naga.mana>=float(spell_data()[0]['ANfl']['Cost1']) and now>=self.cast_until.get(naga.handle,0) and
                g.cooldown(naga,'ANfl')==0 and any(a['code']=='ANfl' and a['level']>0 for a in g.abilities(naga)) and
                not is_structure(target) and
                g.dist(naga,target)<=float(spell_data()[0]['ANfl']['Rng1']) and self.due('forked_lightning',now,1)):
                r=g.cast(naga,'forkedlightning',target=target)
                self.log('forked_lightning_attempt',clock=now,target=target.type,accepted=bool(r))
                if r:self.cast_until[naga.handle]=now+.8;protected.add(naga.handle)
        for u in army:
            if u.handle in protected or u.type=='uobs' or now<self.cast_until.get(u.handle,0):
                continue
            selected=target
            if player_fight:
                nc_focus=self.nc_combo.focus(foes,now)
                allowed={e.handle for e in (pressure,nc_focus) if e is not None}
                local=[e for e in foes if in_weapon_range(g,u,e) and (not e.is_hero or e.handle in allowed)]
                if not local:
                    current=g.current_target(u)
                    if current and current.is_hero and enemy_player(g,current) and self.due(('release_hero',u.handle),now,1):
                        if g.hold(u):
                            self.hero_attack_targets.pop(u.handle,None)
                            self.last.pop(('go',u.handle),None)
                    continue
                selected=self.nc_combo.focus(local,now) or next((e for e in local if pressure and e.handle==pressure.handle),None) or min([e for e in local if webbed_air(g,e)] or local,key=lambda e:self.hero_pressure.rank(g,army,e))
            current=g.current_target(u)
            if (not current or current.handle!=selected.handle) and self.due(('attack',u.handle),now,1.2):
                receipt=g.attack(u,selected,force=getattr(selected,'owner',0)>=13)
                accepted=bool(receipt)
                if not player_fight and not accepted and self.due(('creep_attack_rejected',u.handle,selected.handle),now,5):
                    self.log('creep_attack_rejected',clock=now,unit=u.type,handle=u.handle,target=selected.type,
                             target_handle=selected.handle,reason=getattr(receipt,'reason',None),
                             point=(u.x,u.y),target_point=(selected.x,selected.y),distance=round(g.dist(u,selected)))
                if not player_fight and accepted and self.creeping.carries_drop(selected):
                    self.log('creep_drop_focus',clock=now,unit=u.type,handle=u.handle,target=selected.type,target_handle=selected.handle)
                if player_fight and accepted:
                    if selected.is_hero:self.hero_attack_targets[u.handle]=selected.handle
                    else:self.hero_attack_targets.pop(u.handle,None)
                    self.log('combat_focus',clock=now,unit=u.type,handle=u.handle,target=selected.type,
                             target_handle=selected.handle,priority=-2 if webbed_air(g,selected) else -1 if pressure and selected.handle==pressure.handle else priority(selected)[0],distance=round(g.dist(u,selected)))

    def skeleton_opening(self,army,foes,now):
        g=self.g
        if self.attack_committed or any(getattr(e,'owner',0)<12 for e in foes):return False
        skeletons=[u for u in army if u.type in {'uske','uskm','nsce','nsca'}]
        if not skeletons:return False
        creeps=[e for e in foes if getattr(e,'owner',0)==12 and ground_attack_range(e.type)>0]
        if not creeps:return False
        handles={u.handle for u in skeletons}
        targets=[g.current_target(e) for e in creeps]
        for e,target in zip(creeps,targets):
            if target and target.handle in handles and e.handle not in self.creep_tank_observed:
                self.creep_tank_observed.add(e.handle)
                self.log('skeleton_tank_observed',clock=now,creep=e.type,creep_handle=e.handle,skeleton=target.handle)
        if any(target is not None for target in targets):return False
        if all(e.handle not in self.creep_opened for e in creeps):
            target=min(creeps,key=lambda e:(not self.creeping.carries_drop(e),min(g.dist(e,u) for u in skeletons)))
            distance=min(g.dist(target,u) for u in skeletons)
            if distance>1400 or min(g.dist(target,u) for u in army)>900:return False
            self.creep_opened.update(e.handle for e in creeps)
            self.creep_open_until=now+min(6,max(2,distance/270+1))
            self.log('skeleton_tank_started',clock=now,target=target.type,handle=target.handle)
            for u in skeletons:g.attack(u,target)
            for u in army:
                if u.handle not in handles and now>=self.cast_until.get(u.handle,0):
                    g.hold(u)
                    self.last.pop(('go',u.handle),None)
        return now<self.creep_open_until

    def use_graveyard_corpse(self,army,dk,now):
        """Try the owned Graveyard's public corpse source; confirm actual summons."""
        if self.opening_rod_finished or self.graveyard_rod_abandoned or now>=240 or self.attack_committed or self.creeping.active or self.creeping.cleared:return False
        g=self.g
        skeletons=[u for u in g.units('me',{'uske'}) if g.dist(u,dk)<900]
        if len(skeletons)>=2:
            self.opening_rod_finished=True
            self.log('opening_skeletons_ready',clock=now,handles=[u.handle for u in skeletons],
                     cast_clock=self.graveyard_rod_at,fiends=len(g.units('me',{'ucry'})),source='graveyard' if self.graveyard_rod_attempts else 'observed')
            return False
        if self.battle_enemies or dk.handle in self.micro.pulling or dk.hp/dk.hp_max<.7:return False
        inv=g.inventory(dk) or []
        if 'rnec' not in inv or not hasattr(g,'my_buildings'):return False
        yards=[u for u in g.my_buildings({'ugrv'}) if u.hp>0 and g.dist(u,self.home)<1200]
        if not yards:return False
        yard=min(yards,key=lambda u:g.dist(u,dk));point=(yard.x,yard.y)
        if self.graveyard_rod_started is None:self.graveyard_rod_started=now
        construction=(p:=g.production(yard)) is not None and p.kind=='construction'
        if not construction and self.graveyard_ready_at is None:self.graveyard_ready_at=now
        cycle=float(spell_data()[0]['Agyd']['Cool1'])
        reason=None
        if now-self.graveyard_rod_started>90 or self.graveyard_ready_at is not None and now-self.graveyard_ready_at>3*cycle+5:reason='opening_timeout'
        elif self.graveyard_rod_attempts>=3 and now-self.graveyard_rod_at>=3:reason='attempt_limit'
        elif not self.creeping.safe_route(g,(dk.x,dk.y),point):reason='unsafe_route'
        elif g.path_distance((dk.x,dk.y),point) is None:reason='unreachable'
        if reason:
            self.graveyard_rod_abandoned=True
            self.log('opening_graveyard_abandoned',clock=now,reason=reason,point=point)
            return False
        self.creeping.pause(now,'graveyard_corpses')
        self.set_intent('开局招骷髅 · 坟场准备首组骷髅')
        if now<self.cast_until.get(dk.handle,0):return True
        if g.dist(dk,yard)>400:self.go(army,point,now)
        elif not construction and now-self.graveyard_ready_at>=cycle and now-self.graveyard_rod_at>=cycle and self.graveyard_rod_attempts<3 and g.cooldown(dk,'AIrd')==0:
            self.graveyard_rod_at=now;self.graveyard_rod_attempts+=1
            receipt=self.use_rod(dk,inv.index('rnec'),now)
            self.log('opening_graveyard_rod_attempt',clock=now,point=point,accepted=bool(receipt),attempt=self.graveyard_rod_attempts,
                     reason=getattr(receipt,'reason',None),ready_at=self.graveyard_ready_at,corpse_cycle=cycle)
        return True

    def opening_corpse_pending(self,now):
        return (self.scout_corpse is not None and not self.opening_rod_finished
                and not self.scout_corpse_abandoned
                and now<240 and not self.attack_committed and not self.creeping.active
                and not self.creeping.cleared)

    def use_scout_corpse(self,army,dk,now):
        """Opening only; all corpse information comes from the scout's fair view."""
        if not self.opening_corpse_pending(now):return False
        g=self.g
        skeletons=g.units('me',SKELETONS)
        if len(skeletons)>=2:
            self.opening_rod_finished=True
            self.log('opening_skeletons_ready',clock=now,handles=[u.handle for u in skeletons],
                     cast_clock=self.opening_rod_at,fiends=len(g.units('me',{'ucry'})))
            return False
        corpse=self.scout_corpse;point=corpse['point']
        reason=None
        if now-corpse['clock']>85:reason='corpse_too_old'
        elif self.opening_rod_started is not None and now-self.opening_rod_started>25:reason='opening_timeout'
        elif self.opening_rod_attempts>=3 and now-self.opening_rod_at>=3:reason='attempt_limit'
        elif not self.creeping.safe_route(g,(dk.x,dk.y),point):reason='unsafe_route'
        elif g.path_distance((dk.x,dk.y),point) is None:reason='unreachable'
        if reason:
            self.scout_corpse_abandoned=True
            self.log('opening_corpse_abandoned',clock=now,reason=reason,point=point)
            return False
        if self.battle_enemies or dk.handle in self.micro.pulling or dk.hp/dk.hp_max<.7:return False
        inv=g.inventory(dk) or []
        self.creeping.pause(now,'scout_corpse')
        if 'rnec' not in inv:
            self.set_intent('开局准备 · 等待骷髅棒')
            self.go(army,(self.home.x,self.home.y),now)
            return True
        if self.opening_rod_started is None:
            self.opening_rod_started=now
            self.log('opening_corpse_approach',clock=now,point=point,handle=corpse['handle'])
        self.set_intent('开局招骷髅 · 利用侦察尸体')
        if now<self.cast_until.get(dk.handle,0):return True
        if g.dist(dk,point)>400:
            self.go(army,point,now)
        elif now-self.opening_rod_at>=3 and self.opening_rod_attempts<3 and g.cooldown(dk,'AIrd')==0:
            self.opening_rod_at=now;self.opening_rod_attempts+=1
            accepted=bool(self.use_rod(dk,inv.index('rnec'),now))
            self.log('opening_rod_attempt',clock=now,point=point,accepted=accepted,attempt=self.opening_rod_attempts)
        return True

    def creep(self,army,center,now):
        g=self.g
        dk=next((u for u in army if u.type=='Udea'),None)
        if dk and self.use_scout_corpse(army,dk,now):return
        if dk and self.use_graveyard_corpse(army,dk,now):return
        if (dk and self.economy.opening_started and dk.level==1 and now<240
                and not self.opening_rod_finished and not self.graveyard_rod_abandoned
                and not self.creeping.active and not self.creeping.cleared
                and not self.battle_enemies and dk.handle not in self.micro.pulling
                and dk.hp/dk.hp_max>=.7 and len(g.units('me',SKELETONS))<2):
            self.set_intent('开局准备 · 等待首组骷髅')
            self.go(army,(self.home.x,self.home.y),now)
            return
        self.creeping.opening_gnoll=bool(dk and dk.level==1 and now<240 and not self.creeping.cleared
                                         and len(g.units('me',SKELETONS))>=2)
        if dk and now<240 and not g.units('me',{'uske','uskm','nsce','nsca'}):
            critters=[u for u in g.units(15) if not is_structure(u) and u.hp_max<=100 and g.dist(u,dk)<1500]
            if critters:
                self.set_intent('练级准备 · 获取骷髅尸体')
                self.creeping.pause(now,'rod_corpses')
                target=g.nearest(critters,dk)
                self.go(army,(target.x,target.y),now,attack=True)
                self.fight(army,[target],now)
                return
        self.creeping.resupply_home=bool(self.creeping.tier>=2 and (self.battle_shop.orb or not getattr(self.situation,'orb',False)))
        self.creeping.local_origin=None if self.creeping.resupply_home else (center if self.battle_shop.orb else None)
        if self.battle_shop.orb and self.creeping.active and g.dist(center,(self.creeping.active['x'],self.creeping.active['y']))>2200:
            self.creeping.defer(now,'orb_courier_nearby')
        old_goal=self.camp_goal
        self.camp_goal,nearby=self.creeping.choose(g,self.creep_strength or army,center,self.home,now,self.battle_enemies)
        if self.camp_goal!=old_goal:
            self.formation.reset()
            self.formation_at=-100
        if self.camp_goal:
            self.set_intent(('DK采购腐球 · 己方营地练级：' if self.battle_shop.orb else '练级：')+camp_name(self.creeping.active,self.camp_goal))
            if nearby and self.skeleton_opening(army,nearby,now):return
            if nearby and any(g.dist(u,e)<650 for u in army for e in nearby):
                front=min(army,key=lambda u:min(g.dist(u,e) for e in nearby))
                for u in army:
                    if g.dist(u,front)>700:self.go_raw([u],(front.x,front.y),now)
                self.fight(army,nearby,now)
            else:
                self.go(army,self.camp_goal,now,attack=True)
                self.fight(army,nearby,now)
            return
        if self.creeping.catalog:
            self.set_intent("回家恢复 · 暂无安全营地")
            # Known camps are currently unsafe/finished; recover while macro continues.
            self.go(army,(self.home.x,self.home.y),now)
            return
        # Explore rings around the base to reveal camps instead of reading full-map creeps.
        if self.goal is None or hypot(center[0]-self.goal[0],center[1]-self.goal[1])<250 or self.due('explore_timeout',now,25):
            mp=g.map()
            for _ in range(24):
                i=self.explore
                self.explore+=1
                radius=1200+800*((i//3)%4)
                a=atan2(-self.home.y,-self.home.x)+(0,-.6,.6)[i%3]
                p=(self.home.x+radius*cos(a),self.home.y+radius*sin(a))
                if mp and mp.walkable(*p):
                    self.goal=p
                    break
        if self.goal:
            self.set_intent('探索'+region(self.goal)+'野怪营地')
            self.go(army,self.goal,now,attack=True)
