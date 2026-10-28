"""Two fair, state-driven human sparring policies; no hidden opponent economy."""
from collections import Counter
from undead.targeting import in_weapon_range, can_engage, buffs, abilities

PROFILES = {
    'human-fast-expand': '人族一本开矿',
    'human-rifle': '人族单矿火枪',
}
HALLS = {'htow', 'hkee', 'hcas'}
WORKERS = {'hpea', 'hmil'}


class HumanOpponent:
    """Common economy and combat, with explicit expansion/rifle priorities."""
    def __init__(self, game, log, profile, catalog):
        if profile not in PROFILES:raise ValueError('Unknown human opponent: '+profile)
        self.g,self.log,self.profile,self.catalog=game,log,profile,catalog
        self.player=game.player if game.player is not None else game.me()
        self.home=None;self.last={};self.complete=set();self.ever_hero=False
        self.workers={};self.jobs={};self.pending=None;self.build_failures={}
        self.expansion=None;self.expanded=False;self.expansion_abandoned=False
        self.cleared=set();self.camp=None;self.search_index=0
        self.recovering=set();self.attacking=False;self.phase=None
        self.milestones=set();self.last_summary=-100

    def emit(self,event,**data):self.log('human_'+event,profile=self.profile,player=self.player,**data)

    def due(self,key,now,seconds):
        if now-self.last.get(key,-1e9)<seconds:return False
        self.last[key]=now;return True

    def ready(self,code):
        result=[]
        for u in self.g.my_buildings({code} if isinstance(code,str) else code):
            p=self.g.production(u)
            if (p and p.kind=='construction'):continue
            if u.hp>=u.hp_max*.999:self.complete.add(u.handle)
            if u.handle in self.complete:result.append(u)
        return result

    def count(self,code):
        return len(self.g.units('me',{code}))+sum(p.queue.count(code) for _,p in self.g.all_production('me') if p.kind=='queue')

    def available_workers(self):
        return [w for w in self.g.my_workers() if not self.g.is_constructing(w) and
                (not self.pending or w.handle!=self.pending['worker']) and w.handle not in self.recovering]

    def safe(self,point,enemies,radius=850):
        return not any(self.g.dist(point,e)<radius for e in enemies if can_engage(e))

    def move(self,u,point,now,attack=False):
        if not self.due(('move',u.handle),now,3):return
        if self.g.path_distance((u.x,u.y),point) is None:return
        fn=self.g.attack_move if attack else self.g.move
        fn(u,*point)

    def observe_build(self,now):
        if not self.pending:return
        p=self.pending
        foundations=[b for b in self.g.my_buildings({p['code']}) if b.handle not in p['before']]
        if foundations:
            self.emit('foundation_observed',clock=now,code=p['code'],handle=foundations[0].handle)
            self.build_failures.pop(p['key'],None)
            self.pending=None
        elif now-p['at']>35:
            self.build_failures[p['key']]=self.build_failures.get(p['key'],0)+1
            self.emit('foundation_missing',clock=now,code=p['code'],attempt=self.build_failures[p['key']])
            self.pending=None

    def build(self,code,point,now,near_mine=False):
        g=self.g
        if self.pending:return False
        key=(code,tuple(round(v/128) for v in point))
        if self.build_failures.get(key,0)>=3:return False
        if not g.can_afford(code) or not self.due(('build',key),now,3):return False
        workers=self.available_workers()
        workers=[w for w in workers if g.path_distance((w.x,w.y),point) is not None]
        if not workers:return False
        w=min(workers,key=lambda u:g.dist(u,point))
        before={b.handle for b in g.my_buildings({code})}
        spot=g.build_near(w,code,*point,min_r=320 if near_mine else 400,
                          max_r=650 if near_mine else 1000,max_tries=12)
        self.jobs.pop(w.handle,None)
        if spot:
            self.pending=dict(code=code,worker=w.handle,before=before,at=now,key=key)
        else:self.build_failures[key]=self.build_failures.get(key,0)+1
        self.emit('build_attempt',clock=now,code=code,point=spot,accepted=bool(spot))
        return bool(spot)

    def train(self,building,code,now):
        g=self.g
        if g.queue(building) or not self.due(('train',building.handle,code),now,2):return False
        if g.can_do(building,code) not in (0,220):return False
        accepted=bool(g.train(building,code))
        self.emit('train_attempt',clock=now,code=code,accepted=accepted)
        return accepted

    def labor(self,now,enemies):
        g=self.g
        for w in g.my_workers():self.workers[w.handle]=(w,now)
        # Mining workers disappear briefly; never replace them from one missing frame.
        self.workers={h:v for h,v in self.workers.items() if now-v[1]<30}
        self.jobs={h:j for h,j in self.jobs.items() if h in self.workers}
        halls=self.ready(HALLS)
        mines=[m for m in g.gold_mines() if m.type=='ngol' and any(g.dist(m,h)<1100 for h in halls)]
        crew=Counter(self.jobs.values())
        for w in g.my_workers():
            if w.hp/w.hp_max<.45 and not self.safe(w,enemies,650):
                self.recovering.add(w.handle);self.jobs.pop(w.handle,None)
                self.move(w,self.home,now)
            elif w.handle in self.recovering and self.safe(w,enemies,850):self.recovering.discard(w.handle)
        for w in g.idle_workers():
            if w.handle in self.recovering or self.pending and w.handle==self.pending['worker']:continue
            old=self.jobs.pop(w.handle,None)
            if old is not None:crew[old]-=1
            choices=[m for m in mines if crew[m.handle]<5 and self.safe(m,enemies)]
            if choices:
                mine=min(choices,key=lambda m:g.dist(w,m))
                if g.gather(w,mine):self.jobs[w.handle]=mine.handle;crew[mine.handle]+=1
            else:
                hall=min(halls,key=lambda h:g.dist(w,h),default=None)
                if hall is None:continue
                for tree in g.trees(hall.x,hall.y,limit=12):
                    if self.safe(tree,enemies) and g.gather(w,tree):self.jobs[w.handle]='lumber';break

    def repair(self,now,enemies):
        g=self.g
        for b in g.my_buildings():
            if b.hp>=b.hp_max*.98 or not self.safe(b,enemies,700):continue
            if any(g.is_constructing(w) and g.dist(w,b)<250 for w in g.my_workers()):continue
            if not self.due(('repair',b.handle),now,5):continue
            workers=self.available_workers()
            if workers:
                w=min(workers,key=lambda w:g.dist(w,b))
                if g.repair(w,b):self.jobs.pop(w.handle,None)
                return

    def expansion_point(self):
        g=self.g
        choices=[]
        for row in self.catalog.get('neutral_buildings',[]):
            if row['code']!='ngol':continue
            p=(row['x'],row['y'])
            if g.dist(p,self.home)<1400:continue
            other_starts=[(s['x'],s['y']) for s in self.catalog['starts'] if g.dist((s['x'],s['y']),self.home)>1800]
            if any(g.dist(p,s)<1200 for s in other_starts):continue
            distance=g.path_distance(self.home,p)
            if distance is not None:choices.append((distance,p))
        return min(choices)[1] if choices else None

    def economy(self,now,enemies):
        g=self.g;res=g.resources()
        if res is None:return
        halls=g.my_buildings(HALLS);ready_halls=self.ready(HALLS)
        if not halls:
            self.build('htow',self.home,now);return
        expanded=len(ready_halls)>=2
        if expanded and not self.expanded:
            self.expanded=True;self.emit('expansion_completed',clock=now,tier_one=all(h.type=='htow' for h in ready_halls))
        opening_expand=self.profile=='human-fast-expand' and not self.expanded and not self.expansion_abandoned
        if opening_expand and self.expansion is None:self.expansion=self.expansion_point()
        if opening_expand and self.expansion is None:
            self.expansion_abandoned=True;self.emit('expansion_abandoned',clock=now,reason='no_reachable_site')
            opening_expand=False
        # Only one economic purchase per tick. No speculative batch overspending.
        self.ready('hhou')
        building_farm=any(b.handle not in self.complete for b in g.my_buildings({'hhou'}))
        if res['food_cap']-res['food_used']<=4 and res['food_cap']<100 and not building_farm:
            if self.build('hhou',self.home,now):return
        for code in ('halt','hbar'):
            if not g.my_buildings({code}):
                self.build(code,self.home,now);return
        altars=self.ready('halt')
        heroes=g.my_heroes()
        if heroes:self.ever_hero=True
        if not heroes and altars and not g.queue(altars[0]):
            if self.ever_hero:
                if self.due('revive',now,3) and g.revive(altars[0]):return
            elif self.train(altars[0],'Hamg',now):return
            if not self.ever_hero and self.count('Hamg')==0:return
        worker_count=len(self.workers)+sum(p.queue.count('hpea') for _,p in g.all_production('me') if p.kind=='queue')
        worker_target=10 if len(ready_halls)<2 else 16
        if worker_count<worker_target:
            for hall in ready_halls:
                if self.train(hall,'hpea',now):return
        bar=self.ready('hbar')
        # Four footmen escort the expansion; rifles open with two footmen.
        footmen_goal=4 if opening_expand else 2
        if self.count('hfoo')<footmen_goal:
            for b in bar:
                if self.train(b,'hfoo',now):return
        if opening_expand:
            point=self.expansion
            blocked=not self.safe(point,[*enemies,*g.units('creep')])
            if self.due('expand_status',now,10):self.emit('expansion_status',clock=now,point=point,visible=g.visible(*point),blocked=blocked)
            if not blocked and g.visible(*point) and len(halls)<2:
                key=('htow',tuple(round(v/128) for v in point))
                if self.build_failures.get(key,0)>=3:
                    self.expansion_abandoned=True
                    self.emit('expansion_abandoned',clock=now,reason='three_failed_foundations')
                else:self.build('htow',point,now,near_mine=True)
            if self.count('hfoo')>=4:return # Reserve the expansion cost, stay at tier one.
        for code in ('hbla','hlum'):
            if not g.my_buildings({code}):self.build(code,self.home,now);return
        if self.profile=='human-fast-expand' and self.expanded and len(halls)<2 and self.expansion:
            if self.safe(self.expansion,[*enemies,*g.units('creep')]) and g.visible(*self.expansion):
                if self.build('htow',self.expansion,now,near_mine=True):return
        if expanded and not g.my_buildings({'hgtw','hwtw'}):
            if not g.my_buildings({'hwtw'}):
                if self.build('hwtw',self.expansion,now):return
        for tower in self.ready('hwtw'):
            if self.train(tower,'hgtw',now):return
        if len(g.my_buildings({'hbar'}))<2 and self.count('hrif')>=3:
            self.build('hbar',self.home,now);return
        if self.count('hrif')>=4 and not g.my_buildings({'hkee','hcas'}):
            for h in self.ready('htow'):
                if self.train(h,'hkee',now):return
            return # Save for tier two; otherwise rifle queues consume every income tick.
        if self.ready('hbla'):
            for b in bar:
                if self.train(b,'hrif',now):return
        for sm in self.ready('hbla'):
            for code in ('Rhra','Rhla'):
                if self.train(sm,code,now):return

    def spells(self,army,foes,now,protected):
        g=self.g
        for h in g.my_heroes():
            if h.type!='Hamg':continue
            info=g.hero_info(h)
            if info and info['skill_points'] and self.due(('learn',h.handle),now,2):
                rows={a['code']:a['level'] for a in g.abilities(h)}
                learned=sum(rows.get(c,0) for c in ('AHwe','AHab','AHmt','AHbz'))
                plan=('AHwe','AHab','AHwe','AHab','AHwe','AHmt','AHab','AHbz','AHbz','AHbz')
                if learned<len(plan):g.learn(h,plan[learned])
            if h.handle in protected or buffs(g,h)&{'BPSE','BSTN','Bstn','BOhx','BNsi'}:continue
            skills=abilities(g,h)
            if any(g.dist(h,e)<800 for e in foes) and skills.get('AHwe',{}).get('level',0)>0 and h.mana>=125 and g.cooldown(h,'AHwe')==0 and self.due(('water',h.handle),now,2):
                if g.cast(h,'waterelemental'):self.last[('cast_lock',h.handle)]=now+1

    def destination(self,army,enemies,now):
        g=self.g
        bases=g.my_buildings(HALLS)
        invaders=[e for e in enemies if any(g.dist(e,b)<1000 for b in bases)]
        if invaders:return 'defend',(invaders[0].x,invaders[0].y)
        if self.profile=='human-fast-expand' and not self.expanded and not self.expansion_abandoned and self.expansion:
            if any(u.is_hero for u in army) and sum(u.type=='hfoo' for u in army)>=3:
                return 'clear_expansion',self.expansion
            return 'assemble',self.home
        fighters=[u for u in army if not u.is_hero and u.type!='hwat']
        threshold=8 if self.profile=='human-fast-expand' else 6
        ready=len(fighters)>=threshold if self.profile=='human-fast-expand' else sum(u.type=='hrif' for u in fighters)>=6
        if ready and any(u.is_hero for u in army):self.attacking=True
        if len(fighters)<3:self.attacking=False
        if self.attacking:
            buildings=[e for e in enemies if g.is_building(e)]
            if buildings:
                e=min(buildings,key=lambda e:g.dist(e,self.home));return 'attack',(e.x,e.y)
            starts=[(s['x'],s['y']) for s in self.catalog['starts'] if g.dist((s['x'],s['y']),self.home)>1800]
            if starts:
                goal=starts[self.search_index%len(starts)]
                if g.visible(*goal) and not any(g.dist(e,goal)<1000 for e in enemies) and self.due('search',now,15):self.search_index+=1
                return 'search',goal
        if any(u.is_hero for u in army) and len(fighters)>=2:
            camps=[c for c in self.catalog['camps'] if c['id'] not in self.cleared and c['max_level']<=4 and c['hp']<2200]
            if self.camp:
                p=(self.camp['x'],self.camp['y'])
                if g.visible(*p) and any(g.dist(u,p)<450 for u in army) and not any(g.dist(e,p)<650 for e in g.units('creep')):
                    self.cleared.add(self.camp['id']);self.camp=None
            if not self.camp and camps:self.camp=min(camps,key=lambda c:g.dist(self.home,(c['x'],c['y'])))
            if self.camp:return 'creep',(self.camp['x'],self.camp['y'])
        return 'assemble',self.home

    def combat(self,now,enemies):
        g=self.g;army=[u for u in g.my_army() if u.type not in WORKERS]
        mode,goal=self.destination(army,enemies,now)
        if mode!=self.phase:self.phase=mode;self.emit('phase',clock=now,phase=mode,goal=goal)
        foes=enemies+[e for e in g.units('creep') if mode in {'creep','clear_expansion'} and g.dist(e,goal)<850]
        foes=[e for e in foes if can_engage(e) and e.visible_to(g.me()) and not buffs(g,e)&{'Bvul','BHds'}]
        protected=set()
        for u in army:
            if u.hp/u.hp_max<(.4 if u.is_hero else .3):self.recovering.add(u.handle)
            if u.hp/u.hp_max>.65:self.recovering.discard(u.handle)
            if u.handle in self.recovering:
                protected.add(u.handle);self.move(u,self.home,now)
                bag=g.inventory(u) if u.is_hero else None
                if bag and 'phea' in bag and self.due(('potion',u.handle),now,3):g.use_item(u,bag.index('phea'))
        self.spells(army,foes,now,protected)
        fighting=[u for u in army if u.handle not in protected]
        local=[e for e in foes if any(in_weapon_range(g,u,e) for u in fighting)]
        target=min(local,key=lambda e:(g.is_building(e),e.is_hero,e.hp),default=None)
        for u in fighting:
            if now<self.last.get(('cast_lock',u.handle),0):continue
            current=g.current_target(u)
            nearby=[e for e in local if in_weapon_range(g,u,e)]
            victim=target if target in nearby else min(nearby,key=lambda e:e.hp,default=None)
            if victim:
                if (not current or current.handle!=victim.handle) and self.due(('attack',u.handle),now,1.5):g.attack(u,victim)
            elif not current or not can_engage(current) or not in_weapon_range(g,u,current):
                if g.dist(u,goal)>200:self.move(u,goal,now,attack=mode!='assemble')

    def tick(self):
        g=self.g;now=g.clock()
        if g.me()!=self.player:raise RuntimeError('Human opponent player identity changed')
        if not self.due('tick',now,1):return
        if self.home is None:
            halls=g.my_buildings(HALLS)
            if not halls:raise RuntimeError('Human opponent requires a human starting town hall')
            self.home=(halls[0].x,halls[0].y)
        enemies=[e for e in g.enemies() if e.visible_to(self.player)]
        self.observe_build(now)
        if self.due('labor',now,3):self.labor(now,enemies);self.repair(now,enemies)
        self.economy(now,enemies)
        self.combat(now,enemies)
        if now-self.last_summary>=15:
            self.last_summary=now
            self.emit('summary',clock=now,phase=self.phase,resources=g.resources(),
                      units=dict(Counter(u.type for u in g.my_units())),expanded=self.expanded,
                      expansion_abandoned=self.expansion_abandoned)
