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
        self.cleared=set();self.deferred={};self.deferred_reasons={};self.active=None
        self.failures={};self.exhausted=set()
        self.progress_at=0;self.best_distance=None;self.last_hp=None
        self.paused=False;self.combat_hp={}
        self.tier=1
        self.opening_gnoll=False
        self.map_alias=None
        self.ch_orb_ready=False;self.ch_center_started=None;self.ch_center_done=False
        self.ch_route_skipped=set();self.ch_route_wait=None;self.ch_home_returned=False
        self.ni_orb_ready=False;self.ni_route_skipped=set();self.ni_route_wait=None
        self.ni_attack_started=False;self.ni_contested=False;self.repath=False
        self.local_origin=None
        self.home_only=False
        self.resupply_home=False
        self.drop_bindings={};self.drop_spawns=set()
        self.resupply_home=False
        self.drop_bindings={};self.drop_spawns=set()
        self.drop_camps={}
        self.enemy_main=None
        self.enemy_structures=[]

    def observe_drop_carriers(self,g,visible,now=None):
        # Bind only a fair visible unit near a unique static placement; never infer hidden live units.
        spawns=[(camp,s) for camp,c in enumerate(self.catalog) for s in c.get('spawns',[])]
        for u in visible:
            if u.handle in self.drop_bindings:continue
            choices=sorted((g.dist(u,(s['x'],s['y'])),i,camp,s) for i,(camp,s) in enumerate(spawns)
                           if s['code']==u.type and i not in self.drop_spawns)
            if not choices or choices[0][0]>350:continue
            if len(choices)>1 and choices[1][0]-choices[0][0]<64:continue
            distance,i,camp,spawn=choices[0]
            if any(v.handle!=u.handle and v.type==u.type and g.dist(v,(spawn['x'],spawn['y']))<distance for v in visible):continue
            self.drop_bindings[u.handle]=bool(spawn.get('drops_items'));self.drop_spawns.add(i)
            self.drop_camps[u.handle]=camp
            if spawn.get('drops_items'):
                self.log('creep_drop_carrier_seen',clock=now,code=u.type,handle=u.handle,spawn=(spawn['x'],spawn['y']),distance=round(distance))

    def carries_drop(self,u):return self.drop_bindings.get(u.handle,False)

    def include_drop_carriers(self,g,foes,anchor):
        # A short-range combat subset must not hide the visible back-row carrier.
        camps={self.drop_camps[e.handle] for e in foes
               if getattr(e,'owner',None)==12 and e.handle in self.drop_camps}
        handles={e.handle for e in foes}
        return [*foes,*[e for e in (g.creeps() if hasattr(g,'creeps') else [])
                       if e.hp>0 and e.handle not in handles and self.carries_drop(e)
                       and self.drop_camps.get(e.handle) in camps and g.dist(e,anchor)<900]]

    @staticmethod
    def strength(army):
        return sum(((3+2*u.level) if u.is_hero else
                    {'ucry':3,'uobs':3,'ubsp':5,'uske':.5,'uskm':.5}.get(u.type,0))*min(1,u.hp/u.hp_max) for u in army)

    @staticmethod
    def small_turtle(c):
        # Only the public 4/1/1 camp, not the larger thorn/poison turtle camps.
        return (c.get('kind')=='turtle' and sorted(s.get('level',0) for s in c.get('spawns',[]))==[1,1,4]
                and not c.get('poison_units') and set(c.get('hazards',[]))<={'thorns'}
                and c.get('difficulty',float('inf'))<=6 and c.get('hp',float('inf'))<=815)

    @staticmethod
    def central_green_gnoll(c):
        # TM's central green 3/3/1 camps, explicitly requested for the first rod.
        # The closer level-five home camp remains excluded from this opening.
        return (c.get('kind')=='gnoll' and sorted(s['code'] for s in c.get('spawns',[]))==['ngna','ngnb','ngnw']
                and c.get('max_level')==3 and c.get('difficulty',float('inf'))<=7
                and c.get('hp',float('inf'))<=970 and not c.get('poison_units') and not c.get('hazards'))

    @classmethod
    def needs_support(cls,c):
        # Fish camps use actual army strength/health, not a mandatory statue.
        if c['kind']=='murloc':return False
        control_chain='stun' in c.get('hazards',[]) and bool({'slow','ensnare'} & set(c.get('hazards',[])))
        return (c.get('requires_support') or control_chain or c['kind'] in {'murloc','mercenary','turtle'}) and not cls.small_turtle(c)

    def ch_midgame_support(self,g,c,army,home):
        # These two mirrored CH routes need sufficient actual troops, not a mandatory statue.
        if self.map_alias!='CH' or self.tier<2 or not self.home_half(g,c,home):return False
        lich=next((u for u in army if u.type=='Ulic' and u.hp>=.65*u.hp_max),None)
        if lich is None:return False
        ratio=sum(u.hp for u in army)/max(1,sum(u.hp_max for u in army))
        if (c['kind']=='murloc' and c.get('difficulty',99)<=8 and c.get('max_level',99)<=3
                and not c.get('poison_units') and set(c.get('hazards',[]))<={'ensnare'}):
            return ratio>=.65 and sum(u.type=='ucry' and u.hp>=.5*u.hp_max for u in army)>=2
        if c['id'] in {'ch-4','ch-12'}:
            return (ratio>=.8 and sum(u.type=='ucry' and u.hp>=.65*u.hp_max for u in army)>=3
                    and any(u.type=='Udea' and u.hp>=.65*u.hp_max and u.mana>=75 for u in army))
        return False

    def tm_green_chain(self,army,now):
        return (self.map_alias=='TM' and now<360 and not self.resupply_home
                and any(self.central_green_gnoll(c) and c['id'] in self.cleared for c in self.catalog)
                and any(u.type=='Udea' and u.level<=2 and u.hp>=.7*u.hp_max for u in army)
                # Remaining skeletons carry the next green; do not wait for a
                # second healthy summon. Arriving fiends can replace expiring
                # summons without recalling an otherwise ready army home.
                # Candidate HP/strength, hero health and route checks still apply.
                and any(u.type in {'uske','uskm','ucry'} and u.hp>=.5*u.hp_max for u in army))

    def ch_home_opening(self,home):
        """The user's CH opening, mirrored by own spawn; never a global turtle exemption."""
        if self.map_alias!='CH' or self.tier>=3 or self.resupply_home:return []
        turtles=[c for c in self.catalog if c['kind']=='turtle'
                 and sorted(s.get('level',0) for s in c.get('spawns',[]))==[2,2,4]
                 and c.get('difficulty',99)<=8 and c.get('hp',9999)<=875
                 and not c.get('poison_units') and set(c.get('hazards',[]))<={'thorns'}]
        ogres=[c for c in self.catalog if c['kind']=='ogre' and c.get('max_level',99)<=4
               and c.get('difficulty',99)<=10 and not c.get('poison_units')
               and set(c.get('hazards',[]))<={'ensnare'}]
        if not turtles or not ogres:return []
        route=[min(rows,key=lambda c:hypot(c['x']-home.x,c['y']-home.y)) for rows in (turtles,ogres)]
        return route if all(hypot(c['x']-home.x,c['y']-home.y)<3500 for c in route) else []

    def ch_route_stage(self,home):
        """Own shop -> one side camp -> home laboratory -> central mine, mirrored by spawn."""
        if self.map_alias!='CH' or self.ch_center_done:return None,[]
        by_id={c['id']:c for c in self.catalog}
        north=hypot(home.x-2176,home.y-4224)<hypot(home.x+2304,home.y+4736)
        opening,shop,side,lab=(('ch-9','ch-13'),'ch-6',('ch-0','ch-5'),'ch-14') if north else (
            ('ch-8','ch-3'),'ch-10',('ch-15','ch-11'),'ch-2')
        # Partial/fallback catalogs retain generic fair-visible selection.
        if not all(k in by_id for k in (*opening,shop,*side,lab,'ch-7')):return None,[]
        if not set(opening)<=self.cleared and 'opening' not in self.ch_route_skipped:
            return 'opening',[next(k for k in opening if k not in self.cleared)]
        for stage,ids in (('shop',[shop]),('side',list(side)),('laboratory',[lab]),('center',['ch-7'])):
            if stage not in self.ch_route_skipped and not any(k in self.cleared for k in ids):
                return stage,ids
        return None,[]

    def ch_route_allows(self,c,home):
        stage,ids=self.ch_route_stage(home)
        if not stage or c['id'] in ids:return True
        # A safe unvisited side camp keeps the army working while lab support arrives.
        north=hypot(home.x-2176,home.y-4224)<hypot(home.x+2304,home.y+4736)
        fallback={'ch-0','ch-5'} if north else {'ch-15','ch-11'}
        return (stage=='laboratory' or stage=='center' and not self.ch_orb_ready) and c['id'] in fallback

    def ch_route_waypoint(self,g,army,center,home,now):
        stage,ids=self.ch_route_stage(home)
        if not stage:return None
        if self.ch_route_wait is None or self.ch_route_wait['stage']!=stage:
            self.ch_route_wait=dict(stage=stage,started=now)
            self.log('ch_route_stage',clock=now,stage=stage,camps=ids)
        # Explicit skips preserve the evidence; never mark an unsafe camp cleared.
        if stage!='center' and now-self.ch_route_wait['started']>180:
            self.ch_route_skipped.add(stage)
            self.log('ch_route_stage_skipped',clock=now,stage=stage,reason='bounded_wait',camps=ids)
            if self.active and self.active['id'] in ids:self.defer(now,'ch_route_timeout')
            return None
        if (stage=='laboratory' and not self.ch_home_returned and self.active is None
                and any(c['id'] in ids for c in self.candidates(g,army,home,now))):
            point=(home.x,home.y)
            if g.dist(center,point)<=900:
                self.ch_home_returned=True
                self.log('ch_route_home_rejoined',clock=now,point=center)
            elif g.path_distance(center,point) is not None and self.safe_route(g,center,point):
                return point
        return None

    def ch_center(self,c):
        # CH's public central 7/5/4/3/3 gold-mine camp, for either starting side.
        return self.map_alias=='CH' and c['id']=='ch-7'

    def prepare_ch_center(self,g,army,home,now,orb,attack_committed):
        self.ch_orb_ready=bool(self.tier==3 and orb)
        if self.map_alias!='CH' or attack_committed or self.ch_center_done:return False
        camp=next((c for c in self.catalog if self.ch_center(c)),None)
        if not camp:return False
        if camp['id'] in self.cleared:
            self.ch_center_done=True
            self.log('ch_center_staging_end',clock=now,reason='cleared',camp=camp['id'])
            return False
        if not self.ch_orb_ready:return False
        stage,_=self.ch_route_stage(home)
        if stage and stage!='center':return True
        if self.ch_center_started is None:
            self.ch_center_started=now
            self.log('ch_center_staging_started',clock=now,camp=camp['id'])
        if (now-self.ch_center_started>180 or camp['id'] in self.exhausted
                or now<self.deferred.get(camp['id'],0)):
            self.ch_center_done=True
            self.log('ch_center_staging_end',clock=now,reason='bounded_timeout_or_unsafe',camp=camp['id'])
            if self.active and self.ch_center(self.active):self.defer(now,'ch_staging_timeout')
            return False
        return True

    def ni_central(self,c):
        return self.map_alias=='NI' and c['id'] in {'ni-7','ni-10'}

    def ni_opening(self,home):
        if self.map_alias!='NI' or self.ni_attack_started:return []
        north=hypot(home.x-6912,home.y-3264)<hypot(home.x+2752,home.y+3328)
        route=['ni-15','ni-11','ni-13','ni-8'] if north else ['ni-2','ni-6','ni-4','ni-9']
        return route if set(route+['ni-7','ni-10'])<={c['id'] for c in self.catalog} else []

    def ni_midgame(self,home):
        """Own-side 5/4/4 then laboratory; the first four camps stay unchanged."""
        opening=self.ni_opening(home)
        if not opening:return []
        route=['ni-17','ni-14'] if opening[0]=='ni-15' else ['ni-0','ni-3']
        return route if set(route)<={c['id'] for c in self.catalog} else []

    def ni_route_stage(self,home):
        opening=self.ni_opening(home)
        if not opening:return None
        # Tier two continues through the home camps while tech and orb arrive.
        # Finish engaged camps rather than abandoning them on tier/orb changes.
        route=opening+(self.ni_midgame(home) if self.tier>=2 else [])
        route+=['ni-7','ni-10'] if self.ni_orb_ready else []
        return next((k for k in route if k not in self.cleared),None)

    def ni_continuous(self,home):
        return bool(not self.ni_contested and self.ni_route_stage(home))

    def ni_route_allows(self,c,home):
        if not self.ni_opening(home):return True
        # Only the prescribed opening, tier-two home camps and central pair.
        return c['id']==self.ni_route_stage(home)

    def ni_route_update(self,home,now):
        stage=self.ni_route_stage(home)
        if not stage:return
        if self.ni_route_wait is None or self.ni_route_wait['camp']!=stage:
            self.ni_route_wait=dict(camp=stage,started=now)
            self.log('ni_route_stage',clock=now,camp=stage)
        # A timer, temporary weak subgroup or summon expiry never skips a
        # prescribed camp. Only observed clearance advances the route.

    def prepare_ni_center(self,g,army,home,now,orb,attack_committed):
        if self.map_alias!='NI':return False
        self.ni_orb_ready=bool(self.tier==3 and orb)
        self.ni_attack_started=attack_committed
        if self.ni_orb_ready:self.ni_route_update(home,now)
        return bool(not attack_committed and self.ni_orb_ready and self.ni_route_stage(home))

    def pre_attack_safe(self,c):
        if self.ni_central(c):return self.ni_orb_ready
        if self.ch_center(c):return self.ch_orb_ready and not self.ch_center_done
        if self.map_alias=='TM' and self.home_only and self.tier>=2 and c['kind'] in {'shop','mercenary'} and c.get('difficulty',99)<=18:
            return True
        return not ((self.resupply_home or self.home_only and self.tier>=3) and
                    (c.get('level_sum',c.get('difficulty',0))>15 or c.get('max_level',0)>7))

    def tm_staging_camp(self,c,home):
        if c['kind'] not in {'shop','mercenary'}:return False
        peers=[x for x in self.catalog if x['kind']==c['kind']]
        return bool(peers) and c['id']==min(peers,key=lambda x:hypot(x['x']-home.x,x['y']-home.y))['id']

    def tm_staging_allows(self,c,home):
        if self.map_alias!='TM' or not self.home_only or self.tier<2:return True
        return (hypot(c['x']-home.x,c['y']-home.y)<=5500 and
                (self.tm_staging_camp(c,home) or c['kind']=='gnoll' and c.get('difficulty',99)<=9))

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
        chain=self.tm_green_chain(army,now)
        ch_route=self.ch_home_opening(home)
        ch_next=next((c['id'] for c in ch_route if c['id'] not in self.cleared),None)
        result=[]
        for c in camps:
            ch_first=bool(ch_route and c['id']==ch_route[0]['id'])
            ch_open=(c['id']==ch_next and any(u.type=='Udea' and u.level<=2 and u.hp>=u.hp_max*(.8 if ch_first else .55) for u in army)
                     and (sum(u.type in {'uske','uskm'} and u.hp>=u.hp_max*.7 for u in army)>=2
                          if ch_first else
                          any(u.type in {'uske','uskm','ucry'} and u.hp>=u.hp_max*.5 for u in army)))
            fixed=self.ni_continuous(home) and c['id']==self.ni_route_stage(home)
            if fixed:
                retry_reason=self.deferred_reasons.get(c['id'])
                resumes=retry_reason in {'army_not_ready','camp_too_strong','no_movement_or_damage_progress',
                    'player_contact','safety_retreat','orb_contact_disengage'}
                if army and c['id'] not in self.cleared and (resumes or now>=self.deferred.get(c['id'],0)):result.append(c)
                continue
            if not self.pre_attack_safe(c) or not self.ch_route_allows(c,home) or not self.ni_route_allows(c,home):continue
            if not self.tm_staging_allows(c,home):continue
            if c.get('difficulty',0)>=15 and (health/max(1,sum(u.hp_max for u in army))<.75 or
                any(u.is_hero and u.hp/u.hp_max<.5 for u in army)):continue
            ch_staging=self.ch_center(c) and self.ch_orb_ready and not self.ch_center_done
            if ch_staging:
                dk=next((u for u in army if u.type=='Udea'),None)
                leader=next((u for u in army if u.type=='Ulic'),None)
                if not dk or not leader or g.dist(dk,leader)>1000:continue
            ni_staging=self.ni_central(c) and self.ni_orb_ready
            if ni_staging:
                dk=next((u for u in army if u.type=='Udea'),None)
                leader=next((u for u in army if u.type=='Ulic'),None)
                if not dk or not leader or g.dist(dk,leader)>1000:continue
            staging=ch_staging or ni_staging or self.map_alias=='TM' and self.home_only and self.tier>=2 and self.tm_staging_camp(c,home)
            if (self.resupply_home or self.home_only) and not (chain and self.central_green_gnoll(c) or staging) and not self.home_half(g,c,home):continue
            if self.local_origin is not None and g.dist((c['x'],c['y']),self.local_origin)>2200:continue
            if c['id'] in self.cleared or c['id'] in self.exhausted or now<self.deferred.get(c['id'],0):continue
            if not healthy:continue
            if c['kind']=='murloc' and any(u.is_hero and u.hp<.5*u.hp_max for u in army):continue
            if self.needs_support(c) and not supported and not ch_open and not self.ch_midgame_support(g,c,army,home):continue
            opening_small=(self.opening_gnoll and not self.cleared and self.own_side(g,c,home)
                and (self.small_turtle(c) or (c['kind'] in {'ogre','gnoll'} and c['max_level']<=3 and c.get('difficulty',0)<=9
                     and not c.get('poison_units') and set(c.get('hazards',[]))<={'ensnare'}))
                and g.dist((c['x'],c['y']),home)<(5500 if self.central_green_gnoll(c) else 3500)
                and any(u.type=='Udea' and u.level==1 and u.hp/u.hp_max>=.8 for u in army)
                and sum(u.type in {'uske','uskm'} and u.hp/u.hp_max>=.7 for u in army)>=2)
            chain_green=chain and self.central_green_gnoll(c)
            if c.get('difficulty',0)>(max(strength,c['difficulty']) if ch_open else max(strength,9) if opening_small else max(strength,7) if chain_green else strength):continue
            if not lich and (c['max_level']>5 or not chain_green and hypot(c['x']-home.x,c['y']-home.y)>6500):continue
            # Lich/nova and more ranged units open higher-level camps; avoid suicidal pulls.
            if c['hp']>health*(1.6 if lich else 1.3):continue
            result.append(c)
        return result

    @staticmethod
    def own_side(g,c,home):
        mp=g.map()
        starts=[tuple(p) for p in getattr(mp,'starts',[]) if tuple(p)!=(0,0)]
        if starts:
            own=min(starts,key=lambda p:g.dist(home,p))
            nearest=min(starts,key=lambda p:hypot(c['x']-p[0],c['y']-p[1]))
            return nearest==own
        return True

    def home_half(self,g,c,home):
        # Four-start maps: the empty allied-side spawn is still in our half.
        if self.enemy_main is None:return self.own_side(g,c,home) if self.resupply_home else True
        point=(c['x'],c['y'])
        starts=[tuple(p) for p in getattr(g.map(),'starts',[]) if tuple(p)!=(0,0)]
        own=(home.x,home.y);enemy=self.enemy_main
        if starts:
            own=min(starts,key=lambda p:g.dist(home,p))
            enemy=min(starts,key=lambda p:g.dist(self.enemy_main,p))
        dx,dy=abs(enemy[0]-own[0]),abs(enemy[1]-own[1])
        # Adjacent starts have small alignment offsets: use a horizontal or
        # vertical midline, not a slanted nearest-base Voronoi boundary.
        # Diagonal spawns keep the existing distance rule.
        axis=1 if dy>0 and dy>=2*dx else 0 if dx>0 and dx>=2*dy else None
        if axis is not None:
            midpoint=(own[axis]+enemy[axis])/2
            return point[axis]<=midpoint if own[axis]<enemy[axis] else point[axis]>=midpoint
        return g.dist(point,home)<=g.dist(point,self.enemy_main)

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
            # Temporary injuries/support separation can recover in seconds.
            # Recheck actual eligibility soon; hostile/path failures retain backoff.
            retry=5 if reason=='army_not_ready' else 90
            self.deferred[self.active['id']]=now+retry
            self.deferred_reasons[self.active['id']]=reason
            self.log('creep_target_deferred',clock=now,camp=self.active['id'],reason=reason,retry_at=now+retry)
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

    def observe_clear(self,g,center,now,visible):
        # Observe before shopping/retreat can bypass choose() and leave a stale goal.
        if self.active is None:return False
        point=(self.active['x'],self.active['y'])
        if g.dist(center,point)>=450 or not g.visible(*point):return False
        if any(g.dist(u,point)<700 for u in visible):return False
        self.cleared.add(self.active['id'])
        self.log('creep_area_cleared',clock=now,point=point,camp=self.active['id'])
        self.active=None
        return True

    def choose(self,g,army,center,home,now,hostiles=()):
        visible=g.creeps()
        self.observe_clear(g,center,now,visible)
        self.ni_route_update(home,now)
        if self.active and not self.ni_route_allows(self.active,home):self.defer(now,'ni_route_order')
        waypoint=self.ch_route_waypoint(g,army,center,home,now)
        if self.active and not self.ch_route_allows(self.active,home):self.defer(now,'ch_route_order')
        if waypoint is not None:return waypoint,[]
        continuous=self.ni_continuous(home)
        if self.active and not continuous and not self.pre_attack_safe(self.active):
            self.defer(now,'preserve_attack_readiness')
        if self.active and not self.tm_staging_allows(self.active,home):
            self.defer(now,'tm_orb_staging_route')
        if self.active and not continuous and (self.resupply_home or self.home_only) and not (
                self.tm_green_chain(army,now) and self.central_green_gnoll(self.active) or
                self.ch_center(self.active) and self.ch_orb_ready or
                self.ni_central(self.active) and self.ni_orb_ready or
                self.map_alias=='TM' and self.home_only and self.tier>=2 and self.tm_staging_camp(self.active,home)) and not self.home_half(g,self.active,home):
            self.defer(now,'home_half_regroup')
        if self.active:
            health=sum(u.hp for u in army)/max(1,sum(u.hp_max for u in army))
            support_lost=self.needs_support(self.active) and not (
                self.tier>=2 and any(u.type=='uobs' for u in army)) and not any(
                    c['id']==self.active['id'] for c in self.ch_home_opening(home))
            # Once engaged, actual remaining camp HP below owns the strength check.
            # Reapplying the full initial level sum after every hit would cause oscillation.
            support_lost=support_lost and not self.ch_midgame_support(g,self.active,army,home)
            if not continuous and (health<.55 or support_lost):self.defer(now,'army_not_ready')
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
            if damage or (distance is not None and (self.best_distance is None or distance<self.best_distance-80)) or (self.last_hp is not None and remaining<self.last_hp-10):
                self.progress_at=now;self.best_distance=distance
            self.last_hp=remaining
            if now-self.progress_at>25:
                if continuous:
                    self.repath=True;self.progress_at=now;self.best_distance=None
                    self.log('ni_camp_repath',clock=now,camp=self.active['id'],reason='no_progress_keep_objective')
                else:self.defer(now,'no_movement_or_damage_progress')
            elif not continuous and nearby and remaining>sum(u.hp for u in army)*1.8:
                self.defer(now,'camp_too_strong')
        if self.active is None:
            def score(c):
                distance=g.path_distance(center,(c['x'],c['y']))
                if distance is None:return float('inf')
                own_side=self.home_half(g,c,home) if self.enemy_main is not None else self.own_side(g,c,home)
                central=c['kind'] in {'marketplace','shop'}
                # Soft route cost, not a fixed sequence: a nearby cheap camp can win.
                preference={'ogre':0,'gnoll':0,'expansion':100,'marketplace':200,'murloc':400,'mercenary':600}.get(c['kind'],500)
                return distance+120*c.get('difficulty',0)+preference+(0 if own_side or central else 2000)
            def opening_score(c):
                stage,ids=self.ch_route_stage(home)
                if stage:return (int(c['id'] not in ids),0,score(c))
                if self.ch_orb_ready and not self.ch_center_done:
                    return (int(not self.ch_center(c)),0,score(c))
                ch_next=next((p['id'] for p in self.ch_home_opening(home) if p['id'] not in self.cleared),None)
                if ch_next:return (int(c['id']!=ch_next),0,score(c))
                if self.tm_green_chain(army,now):
                    return (int(not self.central_green_gnoll(c)),0,score(c))
                if self.map_alias=='TM' and self.home_only and self.tier>=2:
                    return (int(not self.tm_staging_camp(c,home)),0,score(c))
                own_gnoll=c['kind']=='gnoll' and self.own_side(g,c,home)
                entrance_turtle=self.small_turtle(c) and self.own_side(g,c,home) and g.dist((c['x'],c['y']),home)<3500
                return (
                        int(self.opening_gnoll and not entrance_turtle),
                        int(self.opening_gnoll and not own_gnoll),score(c))
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
                         tier=self.tier,statue_present=any(u.type=='uobs' for u in army),
                         fiends=sum(u.type=='ucry' for u in army),skeletons=sum(u.type in {'uske','uskm'} for u in army),opening_small=self.opening_gnoll)
                break
        if self.active:
            point=(self.active['x'],self.active['y'])
            return point,[u for u in visible if g.dist(u,point)<700]
        return None,[]
