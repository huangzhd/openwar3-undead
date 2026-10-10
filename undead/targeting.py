"""Local targeting from public tables, fair snapshots and observed spell events."""
from functools import lru_cache
from math import inf
from openwar3 import combat
from .structures import is_structure
from .coil import can_damage
from .nc_combo import spell_data, DISABLED_CASTERS

@lru_cache(maxsize=256)
def unit_stats(code):return combat.stats(code)

def in_weapon_range(g,attacker,target):
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

    def observe_events(self,events):
        # The runner already filtered this stream through OpenWar3AI fair=True.
        self.events.extend(e for e in events if e.kind=='spell.cast')
        self.events=self.events[-128:]

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
        trapped=[e for e in reachable if webbed_air(g,e)]
        if trapped:
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
