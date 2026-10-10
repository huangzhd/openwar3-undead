"""Continuous creeping from public map locations and fair visible observations."""
import hashlib,json
from functools import lru_cache
from math import hypot
from bootstrap import ROOT,UPSTREAM

@lru_cache(maxsize=1)
def public_camps():
    config=json.loads((UPSTREAM/'openwar3.json').read_text(encoding='utf-8'))
    catalog=json.loads((ROOT/'data/echo_isles_camps.json').read_text(encoding='utf-8'))
    path=__import__('pathlib').Path(config['game_dir'])/'Maps'/config['default_map']
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==catalog['map_sha256']:
        return catalog['camps']
    return []

class Creeping:
    def __init__(self,log,camps=None):
        self.log=log;self.catalog=list(public_camps() if camps is None else camps)
        self.cleared=set();self.deferred={};self.active=None
        self.failures={};self.exhausted=set()
        self.progress_at=0;self.best_distance=None;self.last_hp=None
        self.paused=False;self.combat_hp={}
        self.tier=1
        self.opening_gnoll=False
        self.enemy_main=None
        self.enemy_structures=[]

    @staticmethod
    def strength(army):
        return sum(((3+2*u.level) if u.is_hero else
                    {'ucry':3,'uobs':3,'uske':.5,'uskm':.5}.get(u.type,0))*min(1,u.hp/u.hp_max) for u in army)

    def candidates(self,g,army,home,now):
        camps=self.catalog if g.map() else []
        if not camps:
            camps=[dict(c,id=f"visible-{round(c['x']/256)}-{round(c['y']/256)}",kind='visible') for c in g.creep_camps()]
            if self.active and all(c['id']!=self.active['id'] for c in camps):
                camps.append(self.active) # losing vision does not erase a known camp
        lich=any(u.type=='Ulic' for u in army)
        health=sum(u.hp for u in army)
        healthy=health/max(1,sum(u.hp_max for u in army))>=.55
        strength=self.strength(army)
        supported=self.tier>=2 and any(u.type=='uobs' for u in army)
        result=[]
        for c in camps:
            if c['id'] in self.cleared or c['id'] in self.exhausted or now<self.deferred.get(c['id'],0):continue
            if not healthy:continue
            if c['kind'] in {'murloc','mercenary','turtle'} and not supported:continue
            if c.get('difficulty',0)>strength:continue
            if not lich and (c['max_level']>5 or hypot(c['x']-home.x,c['y']-home.y)>6500):continue
            # Lich/nova and more ranged units open higher-level camps; avoid suicidal pulls.
            if c['hp']>health*(1.6 if lich else 1.3):continue
            result.append(c)
        return result

    def safe_route(self,g,start,end):
        """Avoid enemy start and fairly observed structures, while allowing outward escape."""
        zones=([(self.enemy_main,1800)] if self.enemy_main is not None else [])
        zones += [((u.x,u.y),1200) for u in self.enemy_structures]
        if not zones:return True
        route=g.walk_path(start,end)
        if not route:return False
        for main,radius in zones:
            if g.dist(end,main)<radius:return False
            margin=min(radius,g.dist(start,main))-64
            a=start
            for b in route:
                dx,dy=b[0]-a[0],b[1]-a[1];length=dx*dx+dy*dy
                t=max(0,min(1,((main[0]-a[0])*dx+(main[1]-a[1])*dy)/length)) if length else 0
                if hypot(a[0]+t*dx-main[0],a[1]+t*dy-main[1])<margin:return False
                a=b
        return True

    def has_work(self,g,army,home,now):
        return self.active is not None or bool(self.candidates(g,army,home,now))

    def defer(self,now,reason):
        if self.active:
            self.deferred[self.active['id']]=now+90
            self.log('creep_target_deferred',clock=now,camp=self.active['id'],reason=reason)
            if reason in {'no_movement_or_damage_progress','unreachable'}:
                camp=self.active['id']
                self.failures[camp]=self.failures.get(camp,0)+1
                if self.failures[camp]>=2:
                    self.exhausted.add(camp)
                    self.log('creep_target_exhausted',clock=now,camp=camp,reason=reason,attempts=self.failures[camp])
        self.active=None

    def pause(self,now,reason):
        if self.active and not self.paused:
            self.log('creep_paused',clock=now,camp=self.active['id'],reason=reason)
        self.paused=True

    def choose(self,g,army,center,home,now,hostiles=()):
        visible=g.creeps()
        if self.active:
            health=sum(u.hp for u in army)/max(1,sum(u.hp_max for u in army))
            support_lost=self.active['kind'] in {'murloc','mercenary','turtle'} and not (
                self.tier>=2 and any(u.type=='uobs' for u in army))
            # Once engaged, actual remaining camp HP below owns the strength check.
            # Reapplying the full initial level sum after every hit would cause oscillation.
            if health<.55 or support_lost:self.defer(now,'army_not_ready')
            elif not self.safe_route(g,center,(self.active['x'],self.active['y'])):
                self.defer(now,'enemy_main_route')
        if self.paused:
            self.paused=False;self.progress_at=now;self.best_distance=None;self.last_hp=None
            self.combat_hp={}
            if self.active:self.log('creep_resumed',clock=now,camp=self.active['id'])
        # Track damage to the same visible blocker, including encounters outside the goal camp.
        combat={tuple(u.handle):u.hp for u in [*visible,*hostiles] if g.dist(u,center)<1000}
        damage=any(h in self.combat_hp and hp<self.combat_hp[h]-1 for h,hp in combat.items())
        self.combat_hp=combat
        if self.active:
            point=(self.active['x'],self.active['y'])
            nearby=[u for u in visible if g.dist(u,point)<700]
            remaining=sum(u.hp for u in nearby)
            distance=g.path_distance(center,point)
            if not nearby and g.dist(center,point)<450 and g.visible(*point):
                self.cleared.add(self.active['id'])
                self.log('creep_area_cleared',clock=now,point=point,camp=self.active['id'])
                self.active=None
            else:
                if damage or (distance is not None and (self.best_distance is None or distance<self.best_distance-80)) or (self.last_hp is not None and remaining<self.last_hp-10):
                    self.progress_at=now;self.best_distance=distance
                self.last_hp=remaining
                if now-self.progress_at>25:
                    self.defer(now,'no_movement_or_damage_progress')
                elif nearby and remaining>sum(u.hp for u in army)*1.8:
                    self.defer(now,'camp_too_strong')
        if self.active is None:
            def score(c):
                distance=g.path_distance(center,(c['x'],c['y']))
                if distance is None:return float('inf')
                own_side=(c['x']<-256)==(home.x<-256)
                central=c['kind'] in {'marketplace','shop'}
                # Soft route cost, not a fixed sequence: a nearby cheap camp can win.
                preference={'ogre':0,'gnoll':0,'expansion':100,'marketplace':200,'murloc':400,'mercenary':600}.get(c['kind'],500)
                return distance+120*c.get('difficulty',0)+preference+(0 if own_side or central else 2000)
            def opening_score(c):
                own_gnoll=c['kind']=='gnoll' and (c['x']<-256)==(home.x<-256)
                return (int(self.opening_gnoll and not own_gnoll),score(c))
            for c in sorted(self.candidates(g,army,home,now),key=opening_score):
                point=(c['x'],c['y'])
                if g.path_distance(center,point) is None:
                    self.active=c
                    self.defer(now,'unreachable')
                    continue
                if not self.safe_route(g,center,point):
                    self.active=c
                    self.defer(now,'enemy_main_route')
                    continue
                self.active=c;self.progress_at=now;self.best_distance=g.path_distance(center,point);self.last_hp=None
                self.log('creep_goal',clock=now,point=point,camp=c['id'],kind=c['kind'],
                         level_sum=c.get('level_sum'),poison_units=c.get('poison_units'),
                         difficulty=c.get('difficulty'),army_strength=round(self.strength(army),2),
                         tier=self.tier,statue_present=any(u.type=='uobs' for u in army))
                break
        if self.active:
            point=(self.active['x'],self.active['y'])
            return point,[u for u in visible if g.dist(u,point)<700]
        return None,[]
