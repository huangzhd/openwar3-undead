"""Local targeting from public tables, fair snapshots and observed spell events."""
from functools import lru_cache
from math import inf
from openwar3 import combat
from .structures import is_structure
from .coil import can_damage
from .nc_combo import spell_data, DISABLED_CASTERS, aoe_threat

ORC_HERO_PRIORITY = {'Obla': 0, 'Otch': 1, 'Ofar': 2, 'Oshd': 3}
DEFENSIVE_ITEMS = {'pnvl','pnvu','phea','pghe','reju','ankh','shea','sres'}

@lru_cache(maxsize=256)
def unit_stats(code):return combat.stats(code)

@lru_cache(maxsize=1)
def collision_table():
    from w3slk import read_slk
    import w3paths
    return {r['unitBalanceID']:float(r.get('collision') or 0)
            for r in read_slk(w3paths.game_data('UnitBalance.slk'))
            if r.get('unitBalanceID') and r.get('collision') not in (None,'','-')}

def unit_collision(code):
    return collision_table().get(code,0)

def can_engage(target):
    # Local 1.27a Abur transforms ucry into ucrm. Terrain visibility in the
    # fair SDK does not establish detection. Pass buried fiends until they
    # surface instead of using unrestricted JASS to query hidden state.
    # Passive observation wards must not interrupt marching or creeping.
    # Serpent/healing wards remain ordinary attack targets.
    return target.hp>0 and getattr(target,'alive',True) and target.type not in {'ucrm','nwad'}


def in_weapon_range(g,attacker,target):
    if not can_engage(target):return False
    a=unit_stats(attacker.type);t=unit_stats(target.type)
    if not a or not t:return False
    kind='ground' if webbed_air(g,target) else 'air' if t.is_air else 'structure' if is_structure(target) else 'ground'
    distance=g.dist(attacker,target)
    return any(kind in w.targets and w.min_range<=distance<=w.range for w in a.weapons)

def priority(target):
    stats=unit_stats(target.type)
    siege=not is_structure(target) and stats and any(w.attack_type=='siege' for w in stats.weapons)
    return (0 if siege else 1 if target.is_hero else 3 if is_structure(target) else 2,target.hp)

def enemy_player(g,target):
    return 0<=getattr(target,'owner',15)<12 and getattr(target,'owner',15)!=getattr(g,'me',lambda:0)()

def tc_pressure_target(g,army,foes):
    """Drive off a visible TC with supporting ranged fire, without chasing."""
    shooters=[u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'} and u.hp>0]
    targets=[e for e in foes if e.type=='Otch' and enemy_player(g,e) and can_engage(e)
             and getattr(e,'has_detail',False) and not buffs(g,e)&{'Bvul','BHds'}
             and 'Avul' not in abilities(g,e)
             and sum(in_weapon_range(g,u,e) for u in shooters)>=2]
    return min(targets,key=lambda e:e.hp) if targets else None


def abilities(g,u):
    return {a['code']:a for a in g.abilities(u)} if getattr(u,'has_detail',False) and hasattr(g,'abilities') else {}

def buffs(g,u):
    return set(g.buffs(u)) if getattr(u,'has_detail',False) and hasattr(g,'buffs') else set()

def webbed_air(g,target):
    stats=unit_stats(target.type)
    return bool(target.hp>0 and stats and stats.is_air and buffs(g,target) & {'Bwea','Bweb'})

class HeroPressure:
    def __init__(self,log):
        self.log=log;self.target=None;self.preferred=None;self.history={};self.rises={}
        self.events=[];self.downgraded={};self.last_sample=-100;self.tech={}
        self.chiefs=set();self.dead_chiefs={}
        self.orc_seen=False
        self.orc_melee_active=False;self.orc_battle_heroes=set()
        self.tc_burst=None
        self.strategy=None;self.strategy_since=-100;self.strategy_at=-100
        self.strategy_evidence={}
        self.opportunity=None
        self.tc_sequence=False;self.tc_phase=None;self.sequence_target=None
        self.sequence_seen=-100
        self.prefer_key_heroes=True
        self.key_heroes_seen=set()
        self.wyvern_priority=False

    def wyvern_focus(self,g,army,foes):
        shooters=[u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'} and can_engage(u)]
        targets=[e for e in foes if e.type=='owyv' and enemy_player(g,e) and can_engage(e)
                 and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)
                 and any(in_weapon_range(g,u,e) for u in shooters)]
        target=min(targets,key=lambda e:(not webbed_air(g,e),e.handle!=self.preferred,
                                         self.rank(g,shooters,e)),default=None)
        if target:self.preferred=target.handle
        return target

    def hero_threat(self,g,army,hero):
        """Rank visible threat, never read enemy cooldowns or hidden inventory."""
        score={'Otch':100,'Obla':95,'Oshd':65,'Ofar':60}.get(hero.type,70)
        score+=3*max(0,getattr(hero,'level',1)-1)
        effects=buffs(g,hero)
        if effects&{'BNsi','BNso','BOhx','BSTN','Bstn','BPSE','BUsl'}:score-=20
        if hero.type!='Obla' and getattr(hero,'mana',0)<75:score-=15
        if any(u.is_hero and g.dist(u,hero)<=350 for u in army):score+=10
        victim=getattr(g,'current_target',lambda _:None)(hero)
        if victim and any(u.handle==victim.handle for u in army):
            score+=30 if victim.is_hero and victim.hp<=victim.hp_max*.5 else 15
        if aoe_threat(g,hero):score+=10
        return score

    def advance_key_pressure(self,g,army,enemies,now):
        """Default: drive off key heroes, clear troops, punish exposed heroes."""
        if now-self.sequence_seen>20:
            self.tc_sequence=False;self.tc_phase=None;self.sequence_target=None;self.key_heroes_seen.clear()
        if not enemies:return None
        self.sequence_seen=now
        heroes=[e for e in enemies if e.is_hero and getattr(e,'has_detail',False)]
        if heroes and sum(u.hp>0 and u.type not in {'uobs','ubsp'} for u in army)>=3:self.tc_sequence=True
        if not self.tc_sequence:return None
        self.key_heroes_seen.update(e.handle for e in heroes if e.type in {'Otch','Obla'})
        legal=[e for e in enemies if can_engage(e) and getattr(e,'has_detail',False) and
               not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)]
        shooters=[u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'} and u.hp>0]
        casters=[u for u in army if u.is_hero and u.hp>0]
        reachable=[e for e in legal if sum(in_weapon_range(g,u,e) for u in shooters)>=2 or
                   sum(g.dist(u,e)<=750 for u in casters)>=2]
        keys=[e for e in reachable if e.is_hero and
              (not self.key_heroes_seen or e.handle in self.key_heroes_seen or e.type not in ORC_HERO_PRIORITY or
               not any(not v.is_hero and not is_structure(v) for v in legal))]
        opportunities=[e for e in reachable if e.is_hero and self.estimate(g,army,e)<=2.5 and
                       not self.defensive_items(g,e) and not self.support(g,e,enemies,now,2.5)]
        troops=[e for e in reachable if not e.is_hero and not is_structure(e)]
        phase='key_heroes' if keys else 'opportunity' if opportunities else 'headhunters' if any(e.type in {'ohun','otbk'} for e in troops) else 'cleanup'
        if keys:
            target=max(keys,key=lambda e:(self.hero_threat(g,army,e)+(8 if e.handle==self.sequence_target else 0),-e.hp))
        elif opportunities:target=min(opportunities,key=lambda e:self.estimate(g,army,e))
        else:target=min(troops,key=lambda e:(e.type not in {'ohun','otbk'},e.handle!=self.sequence_target,self.rank(g,army,e)),default=None)
        handle=target.handle if target else None
        if phase!=self.tc_phase or handle!=self.sequence_target:
            self.log('battle_key_hero_plan',clock=now,phase=phase,previous=self.tc_phase,target=handle,
                     type=target.type if target else None,
                     threats=[dict(handle=e.handle,type=e.type,score=self.hero_threat(g,army,e)) for e in keys])
        self.tc_phase=phase;self.sequence_target=handle
        return 'hero_first' if keys or opportunities else 'army_first'

    def advance_tc_sequence(self,g,army,enemies,now):
        """Ghoul/hero army: force TC out, clear headhunters, then finish units."""
        if now-self.sequence_seen>20:
            self.tc_sequence=False;self.tc_phase=None;self.sequence_target=None
        if not enemies:return None
        self.sequence_seen=now
        if (sum(u.type=='ugho' and u.hp>0 for u in army)>=3 and
                any(e.type=='Otch' and can_engage(e) for e in enemies)):
            self.tc_sequence=True
        if not self.tc_sequence:return None
        legal=[e for e in enemies if can_engage(e) and getattr(e,'has_detail',False)
               and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)]
        def approach(u,e):
            if u.type!='ugho' or g.dist(u,e)>750:return False
            route=getattr(g,'path_distance',lambda *a:None)((u.x,u.y),(e.x,e.y))
            return route is not None and route<=g.dist(u,e)+200
        casters=[u for u in army if u.type in {'Udea','Ulic','Nbrn','Nngs'} and u.hp>0]
        shooters=[u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'} and u.hp>0]
        chiefs=[e for e in legal if e.type=='Otch' and
                (sum(in_weapon_range(g,u,e) for u in shooters)>=2 or
                 sum(g.dist(u,e)<=750 for u in casters)>=2 or
                 sum(approach(u,e) and g.dist(u,e)<=450 for u in army)>=2)]
        heads=[e for e in legal if e.type in {'ohun','otbk'}]
        phase='tauren' if chiefs else 'headhunters' if heads else 'cleanup'
        pool=chiefs or heads or [e for e in legal if not e.is_hero and not is_structure(e)] or legal
        reachable=[e for e in pool if any(in_weapon_range(g,u,e) or approach(u,e) for u in army)
                   or any(g.dist(u,e)<=750 for u in casters)]
        target=min(reachable,key=lambda e:(e.handle!=self.sequence_target,self.rank(g,army,e)),default=None)
        handle=target.handle if target else None
        if phase!=self.tc_phase or handle!=self.sequence_target:
            self.log('battle_tc_sequence',clock=now,phase=phase,previous=self.tc_phase,
                     target=handle,type=target.type if target else None,
                     reason='tauren_in_local_reach' if chiefs else 'tauren_dead_unavailable_or_out_of_reach')
        self.tc_phase=phase;self.sequence_target=handle
        return 'hero_first' if phase=='tauren' else 'army_first'

    def defensive_items(self,g,hero):
        # Only the fair visible inventory is available; unknown is not exhausted.
        bag=getattr(g,'inventory',lambda u:None)(hero) if getattr(hero,'has_detail',False) else None
        return set(bag or ()) & DEFENSIVE_ITEMS

    def select_strategy(self,g,army,foes,now):
        """Two shared Orc battle plans, selected from local observed strength."""
        if now==self.strategy_at:return self.strategy
        self.strategy_at=now
        if not army:return self.strategy
        anchor=min(army,key=lambda u:sum(g.dist(u,v) for v in army))
        own=[u for u in army if can_engage(u) and
             not is_structure(u) and g.dist(u,anchor)<=1600 and
             (u.is_hero or u.type in {'ugho','ucry','ucrm','uobs','ubsp'} or
              (unit_stats(u.type) and unit_stats(u.type).weapons))]
        enemies=[e for e in getattr(g,'enemies',lambda:foes)() if enemy_player(g,e) and
                 can_engage(e) and not is_structure(e) and g.dist(e,anchor)<=1600]
        wyverns=[e for e in enemies if e.type=='owyv']
        troops=[e for e in enemies if not e.is_hero]
        anti_air=(sum(u.type=='ucry' for u in own)>=2 and len(wyverns)>=2
                  and len(wyverns)*2>=len(troops))
        self.wyvern_priority=bool(wyverns and (anti_air or self.wyvern_priority))
        if self.wyvern_priority:
            if self.strategy!='army_first' or self.tc_sequence:
                self.log('battle_strategy_selected',clock=now,strategy='army_first',reason='fiends_vs_wyvern_mass')
            self.strategy='army_first';self.strategy_since=now
            self.tc_sequence=False;self.tc_phase=None;self.sequence_target=None
            self.opportunity=None;self.target=None
            return self.strategy
        sequence=(self.advance_key_pressure(g,own,enemies,now) if self.prefer_key_heroes else
                  self.advance_tc_sequence(g,own,enemies,now))
        if (not sequence and not any(e.type in ORC_HERO_PRIORITY or e.type in {'ohun','otbk','ogru','orai'} for e in enemies)
                or (not sequence or not self.prefer_key_heroes) and any(e.is_hero for e in enemies) and not any(e.type in ORC_HERO_PRIORITY for e in enemies)):
            self.tc_sequence=False;self.tc_phase=None;self.sequence_target=None
            self.strategy=None;return None
        from openwar3.game import unit_table
        table=unit_table()
        food=lambda units:sum(float(table.get(u.type,{}).get('food',0)) for u in units)
        effective=lambda units:sum(float(table.get(u.type,{}).get('food',0))*min(1,u.hp/max(1,u.hp_max)) for u in units)
        heads=[e for e in enemies if e.type in {'ohun','otbk'}]
        heroes=[e for e in enemies if e.is_hero]
        # A lone scout/raider does not reveal the battle composition. Wait for
        # a hero or at least two headhunters before committing the first plan.
        if not sequence and not heroes and len(heads)<2:return self.strategy
        ghouls=sum(u.type=='ugho' for u in own);fiends=sum(u.type=='ucry' for u in own)
        destroyers=sum(u.type=='ubsp' for u in own)
        hero_score=2;army_score=0;reasons=[]
        dk=next((u for u in own if u.type=='Udea'),None)
        lich=next((u for u in own if u.type=='Ulic'),None)
        burst=bool(dk and lich and dk.mana>=150 and lich.mana>=125 and
                   abilities(g,dk).get('AUdc',{}).get('level',0)>0 and
                   abilities(g,lich).get('AUfn',{}).get('level',0)>0 and
                   not (buffs(g,dk)|buffs(g,lich))&DISABLED_CASTERS and
                   getattr(g,'cooldown',lambda *a:None)(dk,'AUdc')==0 and
                   getattr(g,'cooldown',lambda *a:None)(lich,'AUfn')==0)
        if burst:hero_score+=2;reasons.append('ready_dk_lich_burst')
        elif dk and lich:army_score+=2;reasons.append('limited_hero_burst')
        if fiends>=4:hero_score+=2;reasons.append('ranged_focus_mass')
        if ghouls>=3 and heads:army_score+=4;reasons.append('ghouls_vs_headhunters')
        if len(heads)>=3:army_score+=2;reasons.append('headhunter_mass')
        if destroyers and len(heads)>=2:army_score+=2;reasons.append('protect_destroyers_from_aa')
        if enemies and effective(enemies)>=effective(own)*.9:
            army_score+=2;reasons.append('enemy_local_strength')
        if heroes and any(self.defensive_items(g,e) or self.support(g,e,enemies,now,3) or
                          buffs(g,e)&{'Bvul','BHds'} for e in heroes):
            army_score+=3;reasons.append('enemy_hero_survival_resources')
        if any(e.type in {'Oshd','Hpal'} and getattr(e,'mana',0)>=100 for e in heroes):
            army_score+=2;reasons.append('enemy_healing_hero')
        own_items=set().union(*(set(getattr(g,'inventory',lambda u:None)(u) or ()) for u in own if u.is_hero))
        if burst and 'ocor' in own_items:hero_score+=1;reasons.append('orb_with_burst')
        if {'Ofar','Otch'}<={e.type for e in heroes} and self.melee_orc(g,enemies):
            army_score+=5;reasons.append('fs_tc_melee_front')
        troops=[e for e in enemies if not e.is_hero]
        desired='army_first' if troops and army_score>hero_score else 'hero_first'
        # Normally keep a plan six seconds, but do not let the anti-thrashing
        # delay hide newly revealed overwhelming anti-air/infantry pressure.
        previous=self.strategy
        if previous and troops and army_score==hero_score:desired=previous
        urgent_clear=desired=='army_first' and army_score>=hero_score+4
        if previous and desired!=previous and troops and now-self.strategy_since<6 and not urgent_clear:desired=previous
        if sequence:
            desired=sequence;reasons.append('key_hero_pressure_default' if self.prefer_key_heroes else 'ghoul_tc_then_headhunters')
        evidence=dict(own_food=food(own),visible_enemy_food=food(enemies),
                      own_effective_food=round(effective(own),1),enemy_effective_food=round(effective(enemies),1),
                      own_heroes=[u.type for u in own if u.is_hero],enemy_heroes=[e.type for e in heroes],
                      ghouls=ghouls,fiends=fiends,destroyers=destroyers,headhunters=len(heads),
                      hero_score=hero_score,army_score=army_score,reasons=reasons,
                      population_basis='local_visible_units_public_food_cost; not hidden enemy population')
        self.strategy_evidence=evidence
        if desired!=previous:
            self.strategy=desired;self.strategy_since=now
            self.log('battle_strategy_selected',clock=now,strategy=desired,previous=previous,**evidence)
        return self.strategy

    def melee_orc(self,g,foes):
        """Recognize a visible FS/TC melee army, independent of map or level."""
        live=[e for e in foes if enemy_player(g,e) and can_engage(e) and getattr(e,'has_detail',False)]
        if not live:
            self.orc_melee_active=False;self.orc_battle_heroes.clear()
            return False
        self.orc_battle_heroes.update(e.type for e in live if e.is_hero)
        troops=[e for e in live if not e.is_hero and not is_structure(e)]
        melee=[e for e in troops if e.type in {'ogru','orai'}]
        if {'Ofar','Otch'}<=self.orc_battle_heroes and len(melee)>=3 and len(melee)*2>=len(troops):
            self.orc_melee_active=True
        if not melee and not any(e.type=='owyv' and webbed_air(g,e) for e in troops):self.orc_melee_active=False
        return self.orc_melee_active

    def observe_events(self,events):
        # The runner already filtered this stream through OpenWar3AI fair=True.
        for e in events:
            if e.kind in {'killed','unit.died'} and e.handle in self.chiefs:
                self.dead_chiefs[e.handle]=e.clock
                self.log('tc_death_observed',clock=e.clock,target=e.handle,source='fair_event')
        self.events.extend(e for e in events if e.kind=='spell.cast')
        self.events=self.events[-128:]

    def orc_focus(self,g,army,foes,now):
        """Melee-army response first; otherwise reachable Orc heroes in priority order."""
        melee_battle=self.melee_orc(g,foes)
        visible=list(getattr(g,'enemies',lambda:foes)())
        self.orc_seen=self.orc_seen or any(e.type in ORC_HERO_PRIORITY and enemy_player(g,e)
                                         and getattr(e,'has_detail',False) for e in visible)
        known={e.handle for e in visible}
        for handle in self.chiefs-known:
            corpse=getattr(g,'unit',lambda h:None)(handle)
            if (corpse is not None and not can_engage(corpse) and
                    getattr(corpse,'visible_to',lambda p:False)(g.me())):visible.append(corpse)
        for e in visible:
            if e.type!='Otch' or not enemy_player(g,e) or not getattr(e,'has_detail',False):continue
            self.chiefs.add(e.handle)
            if not can_engage(e):
                if e.handle not in self.dead_chiefs:
                    self.dead_chiefs[e.handle]=now
                    self.log('tc_death_observed',clock=now,target=e.handle,source='visible_snapshot')
            elif e.handle in self.dead_chiefs and now>self.dead_chiefs[e.handle]+1:
                self.dead_chiefs.pop(e.handle) # Observed revival, never guessed from absence.
        shooters=[u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'} and u.hp>0]
        reachable=[e for e in foes if enemy_player(g,e) and can_engage(e)
                   and getattr(e,'has_detail',False) and not buffs(g,e)&{'Bvul','BHds'}
                   and 'Avul' not in abilities(g,e)
                   and sum(in_weapon_range(g,u,e) for u in shooters)>=2]
        strategy=self.select_strategy(g,army,foes,now)
        if self.wyvern_priority:return self.wyvern_focus(g,army,foes)
        if self.tc_sequence:
            return next((e for e in foes if e.handle==self.sequence_target and can_engage(e)
                         and not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)),None)
        if strategy=='army_first':
            if self.opportunity and now<self.opportunity[1]:
                pending=next((e for e in reachable if e.handle==self.opportunity[0]),None)
                if pending:return pending
            finishers=[e for e in reachable if e.is_hero and self.estimate(g,army,e)<=2.5
                       and not self.defensive_items(g,e) and not self.support(g,e,foes,now,2.5)]
            if finishers:return min(finishers,key=lambda e:self.estimate(g,army,e))
            heads=[e for e in reachable if e.type in {'ohun','otbk'}]
            if heads:return min(heads,key=lambda e:(e.handle!=self.preferred,self.rank(g,army,e)))
            troops=[e for e in reachable if not e.is_hero and not is_structure(e)]
            if troops and not melee_battle:return min(troops,key=lambda e:(e.handle!=self.preferred,self.rank(g,army,e)))
        if melee_battle:
            finishers=[e for e in reachable if e.type=='Otch' and
                       (self.estimate(g,shooters,e)<=2.5 or self.tc_burst and
                        self.tc_burst[0]==e.handle and now<self.tc_burst[1]) and
                       not self.support(g,e,foes,now,2.5)]
            if finishers:return min(finishers,key=lambda e:self.estimate(g,shooters,e))
            trapped=[e for e in reachable if e.type=='owyv' and webbed_air(g,e)]
            if trapped:return min(trapped,key=lambda e:(e.handle!=self.preferred,self.rank(g,shooters,e)))
            front=[e for e in reachable if e.type in {'ogru','orai'}]
            if front:return min(front,key=lambda e:(e.type!='ogru',e.handle!=self.preferred,self.rank(g,shooters,e)))
        if strategy=='army_first' and any(can_engage(e) and not e.is_hero and not is_structure(e) for e in foes):
            return None # An out-of-range troop must not restart nonlethal TC pressure.
        heroes=[e for e in reachable if e.type in ORC_HERO_PRIORITY]
        if heroes:
            self.orc_seen=True
            return min(heroes,key=lambda e:(ORC_HERO_PRIORITY[e.type],e.handle!=self.target,e.hp))
        if not self.orc_seen:return None
        heads=[e for e in reachable if e.type in {'ohun','otbk'}]
        return min(heads,key=lambda e:(e.handle!=self.preferred,self.rank(g,shooters,e))) if heads else None

    def estimate(self,g,army,target):
        if buffs(g,target) & {'Bvul','BHds'} or abilities(g,target).keys() & {'Avul'}:return inf
        defense=combat.stats(target.type,hero_level=getattr(target,'level',1))
        if not defense:return inf
        total=0
        for u in army:
            if u.type=='uobs' or not in_weapon_range(g,u,target) or buffs(g,u) & DISABLED_CASTERS:continue
            stats=combat.stats(u.type,tech=self.tech,hero_level=getattr(u,'level',1))
            if stats:total+=stats.dps_vs(defense)
        return target.hp/total if total>0 else inf

    def rank(self,g,army,target):
        cost=self.estimate(g,army,target);stats=unit_stats(target.type)
        # Half-second cost bands: near ties prefer siege, then casters/high output.
        role=0 if priority(target)[0]==0 else 1 if stats and (stats.mana>0 or any(w.dps>=20 for w in stats.weapons)) else 2
        return (is_structure(target),int(cost*2) if cost<inf else inf,role,cost,target.hp)

    def support(self,g,target,visible,now,kill_time):
        rows,_=spell_data();sources=[]
        for u in visible:
            if u.hp<=0 or u.owner!=target.owner or not getattr(u,'has_detail',False):continue
            known=abilities(g,u)
            if 'Ambt' in known and u.mana>=float(rows['Ambt']['DataC1']) and g.dist(u,target)<=float(rows['Ambt']['Area1']):
                sources.append(('moonwell',u.handle))
            heal=known.get('AHhb');level=heal.get('level',0) if heal else 0
            if (level in (1,2,3) and u.handle!=target.handle and can_damage(target.type) and
                not buffs(g,u) & DISABLED_CASTERS):
                row=rows['AHhb'];suffix=str(level);cool=g.cooldown(u,'AHhb')
                if cool is None:
                    casts=[e for e in self.events if e.handle==u.handle and e.spell=='AHhb' and 0<=now-e.clock<=5]
                    if casts:cool=max(0,float(row['Cool'+suffix])-(now-max(e.clock for e in casts)))
                if (cool is not None and cool<kill_time and u.mana>=float(row['Cost'+suffix]) and
                    g.dist(u,target)<=float(row['Rng'+suffix])):sources.append(('holy_light',u.handle))
        # An active visible regeneration effect is still support after the item vanished.
        if buffs(g,target) & {'BIrl','Brej'}:sources.append(('active_regeneration',target.handle))
        return sources

    def finite_pulse(self,target,start,end):
        rows,_=spell_data()
        for e in self.events:
            if not start<e.clock<=end:continue
            row=rows.get(e.spell,{})
            if row.get('item')!='1' or row.get('code') not in {'AIhe','AIre','AIha','AIra'}:continue
            if e.handle==target.handle or getattr(e,'target_handle_lo',0)==target.handle[0]:return True
        return False

    def sample(self,g,army,hero,now):
        key=hero.handle;history=self.history.setdefault(key,[])
        attackers={u.handle for u in army if u.type!='uobs' and not buffs(g,u) & DISABLED_CASTERS and in_weapon_range(g,u,hero) and
                   (t:=g.current_target(u)) is not None and t.handle==key}
        if history:
            prev=history[-1]
            if now-prev[0]>1.6 or len(attackers)<2 or not prev[2].issubset(attackers):
                history.clear();self.rises[key]=[]
            elif hero.hp-prev[1]>=max(5,hero.hp_max*.01):
                finite=self.finite_pulse(hero,prev[0],now)
                self.log('hero_recovery_observed',clock=now,target=key,gain=hero.hp-prev[1],
                         source='consumable_cast' if finite else 'unknown',exhausted=None)
                if finite:
                    history.clear();self.rises[key]=[] # Fresh slope, real healed HP remains.
                else:self.rises.setdefault(key,[]).append(now)
        history.append((now,hero.hp,attackers))
        history[:]=[p for p in history if now-p[0]<=4]
        self.rises[key]=[t for t in self.rises.get(key,[]) if now-t<=4]
        return history

    def choose(self,g,army,foes,now):
        fighters=[u for u in army if u.type!='uobs' and u.hp>0]
        reachable=[e for e in foes if e.hp>0 and enemy_player(g,e) and any(in_weapon_range(g,u,e) for u in fighters)]
        heroes=[e for e in reachable if e.is_hero]
        current=next((e for e in heroes if e.handle==self.target),None)
        if self.target and current is None:
            self.log('hero_pressure_released',clock=now,target=self.target,reason='out_of_range_or_vision')
            self.history.pop(self.target,None);self.rises.pop(self.target,None);self.target=None
        visible=g.enemies() if hasattr(g,'enemies') else foes
        sampling=now-self.last_sample>=1
        if sampling:
            self.last_sample=now
            if hasattr(g,'tech_many'):self.tech=g.tech_many(['Rura','Rume','Rufr']) # Own upgrades only.
            self.events=[e for e in self.events if 0<=now-e.clock<=10]
            visible_keys={e.handle for e in heroes}
            for key in list(self.history):
                if key not in visible_keys:self.history.pop(key);self.rises.pop(key,None)
            for hero in heroes:self.sample(g,fighters,hero,now)
        chief=self.orc_focus(g,fighters,foes,now)
        if chief:
            if self.target!=chief.handle:
                self.log('hero_pressure_started',clock=now,target=chief.handle,
                         reason='orc_melee_priority' if chief.type in {'ogru','orai'} else 'orc_hero_priority' if chief.is_hero else 'headhunters_after_hero')
            self.target=chief.handle if chief.is_hero else None;self.preferred=None if chief.is_hero else chief.handle
            return chief
        if self.strategy=='army_first':
            troops=[e for e in reachable if not e.is_hero and not is_structure(e) and
                    not buffs(g,e)&{'Bvul','BHds'} and 'Avul' not in abilities(g,e)]
            target=min(troops,key=lambda e:(e.type not in {'ohun','otbk'},e.handle!=self.preferred,
                                           self.rank(g,fighters,e)),default=None)
            self.target=None;self.preferred=target.handle if target else None
            return target
        # Training evidence: remove exposed ranged damage dealers together,
        # rather than spending the entire fight chasing a healthy hero.
        # Require observed fire on our army and actual firing-range support.
        own={u.handle for u in fighters}
        ranged=[]
        for e in reachable:
            stats=unit_stats(e.type)
            victim=g.current_target(e)
            if (not e.is_hero and not is_structure(e) and stats and
                    any(w.range>=400 for w in stats.weapons) and victim and victim.handle in own
                    and sum(in_weapon_range(g,u,e) for u in fighters)>=2
                    and self.estimate(g,fighters,e)<=6):
                ranged.append(e)
        finishers=[e for e in heroes if self.estimate(g,fighters,e)<=2.5
                   and not self.support(g,e,visible,now,2.5)]
        if ranged and not finishers:
            target=next((e for e in ranged if e.handle==self.preferred),None) or min(ranged,key=lambda e:self.rank(g,fighters,e))
            if self.preferred!=target.handle:
                self.log('ranged_threat_focus',clock=now,target=target.handle,type=target.type)
            self.target=None;self.preferred=target.handle
            return target
        dangerous=[e for e in heroes if aoe_threat(g,e) and e.handle not in self.downgraded
                   and self.estimate(g,fighters,e)<inf]
        if dangerous:
            current=min(dangerous,key=lambda e:(e.handle!=self.target,self.estimate(g,fighters,e)))
        trapped=[e for e in reachable if webbed_air(g,e)]
        if trapped and not dangerous:
            previous=next((e for e in trapped if e.handle==self.preferred),None)
            target=previous or min(trapped,key=lambda e:self.rank(g,fighters,e))
            self.preferred=target.handle
            return target # Ordinary attacks/spells share web priority; lethal combos remain independent.
        alternatives=[e for e in reachable if not e.is_hero]
        previous=next((e for e in alternatives if e.handle==self.preferred),None)
        alternative=previous or (min(alternatives,key=lambda e:self.rank(g,fighters,e)) if alternatives else None)
        if previous and sampling:
            best=min(alternatives,key=lambda e:self.rank(g,fighters,e))
            best_cost=self.estimate(g,fighters,best)
            if best_cost<=3 and best_cost+2<self.estimate(g,fighters,previous):alternative=best
        if current is None and heroes:
            available=[e for e in heroes if e.handle not in self.downgraded]
            if available:current=min(available,key=lambda e:e.hp)
        # Downgraded heroes do not automatically regain priority at timeout.
        if current is None:
            for hero in sorted(heroes,key=lambda e:e.hp):
                old=self.downgraded.get(hero.handle)
                cost=self.estimate(g,fighters,hero)
                source=self.support(g,hero,visible,now,cost)
                force=sum(in_weapon_range(g,u,hero) for u in fighters)
                changed=old and (hero.hp<=hero.hp_max*.25 or (old['support'] and not source) or force>=old['force']+2)
                better=alternative is None or cost+2<=self.estimate(g,fighters,alternative)
                if not old or alternative is None or ((changed or now>=old['until']) and better):
                    current=hero;self.downgraded.pop(hero.handle,None);self.preferred=None;break
        if current:
            if self.target!=current.handle:
                self.target=current.handle;self.log('hero_pressure_started',clock=now,target=self.target)
            history=self.history.get(current.handle,[]);base=self.estimate(g,fighters,current)
            sources=self.support(g,current,visible,now,base)
            span=history[-1][0]-history[0][0] if len(history)>1 else 0
            effective=span>=2 and all(len(p[2])>=2 for p in history)
            if sampling and effective and alternative:
                loss=history[0][1]-current.hp;rate=max(0,loss/span);cost=current.hp/rate if rate>0 else inf
                # Potential sources count only together with observed recovery. A single
                # unidentified burst without ongoing support never downgrades the hero.
                recoveries=len(self.rises.get(current.handle,[]))
                sustained=(bool(sources) and recoveries>=1) or recoveries>=2
                slow=(span>=4 and loss<current.hp_max*.08) or cost>6
                alt_cost=self.estimate(g,fighters,alternative)
                if sustained and slow and alt_cost<=3 and alt_cost+2<=cost:
                    self.downgraded[current.handle]=dict(until=now+6,support=bool(sources),
                        force=sum(in_weapon_range(g,u,current) for u in fighters))
                    self.preferred=alternative.handle;self.target=None
                    self.log('hero_pressure_downgraded',clock=now,target=current.handle,replacement=alternative.handle,
                             sources=sources or [('repeated_observed_recovery',current.handle)],
                             hero_ttk=cost if cost<inf else None,alternative_ttk=alt_cost,until=now+6)
                    return alternative
            self.preferred=None
            return current
        if alternative:self.preferred=alternative.handle
        return alternative
