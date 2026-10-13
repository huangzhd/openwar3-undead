"""One cleared expansion: fair mine memory, dedicated builder and five miners."""

class Expansion:
    def __init__(self,log):
        self.log=log;self.camps=[];self.safe_route=None;self.mines={}
        self.point=None;self.builder=None;self.miners=set();self.rounds=0
        self.started=0;self.retry_at=0;self.orders={};self.attempts={};self.ready=False
        self.retired_scout=False;self.completed=set();self.gathered={}

    @property
    def reserved(self):return self.miners | ({self.builder} if self.builder else set())

    def observe(self,g):
        for m in g.gold_mines():
            if m.type=='ngol' and m.alive and m.visible_to(g.me()):
                self.mines[m.handle]=(m.x,m.y)

    def danger(self,g,point,radius=1000):
        return any(u.alive and u.hp>0 and u.visible_to(g.me()) and g.dist(u,point)<radius
                   for u in [*g.enemies(),*g.creeps()])

    def nearby(self,g,codes):
        return [b for b in g.my_buildings(codes) if g.dist(b,self.point)<800]

    def finished(self,g,b):
        p=g.production(b)
        if p and p.kind=='construction':return False
        if b.hp>=b.hp_max*.999:self.completed.add(b.handle)
        return b.handle in self.completed

    def abort(self,g,home,now,reason):
        if self.builder:
            w=next((w for w in g.units('me',{'uaco'}) if w.handle==self.builder),None)
            if w:g.move(w,home.x,home.y)
        self.log('expansion_deferred',clock=now,point=self.point,reason=reason,round=self.rounds)
        self.builder=None;self.retry_at=now+120;self.orders={};self.attempts={}

    def upkeep(self,g,home,now):
        if self.point is None:return
        mine=next(iter(self.nearby(g,{'ugol'})),None)
        hall=next(iter(self.nearby(g,{'unpl','unp1','unp2'})),None)
        complete=bool(mine and hall and self.finished(g,mine) and self.finished(g,hall))
        if complete and not self.ready:
            self.log('expansion_complete',clock=now,point=self.point,mine=mine.handle,hall=hall.handle)
            self.builder=None
        if self.ready and not complete:
            for w in g.units('me',{'uaco'}):
                if w.handle in self.miners:g.move(w,home.x,home.y)
            self.miners.clear();self.gathered.clear()
            self.log('expansion_lost',clock=now,point=self.point)
        self.ready=complete
        if not complete:return
        workers=[w for w in g.units('me',{'uaco'}) if w.alive]
        if self.danger(g,self.point):
            for w in workers:
                if w.handle in self.miners and now-self.orders.get(w.handle,-100)>5:
                    g.move(w,home.x,home.y);self.orders[w.handle]=now
            return
        alive={w.handle for w in workers};self.miners &= alive
        # Keep assignments stable; only refill vacancies, leaving five workers at home.
        unassigned=sorted([w for w in workers if w.handle not in self.miners],key=lambda w:g.dist(w,home))
        for w in unassigned[5:]:
            if len(self.miners)>=5:break
            self.miners.add(w.handle)
        idle={w.handle for w in g.idle_workers()}
        for w in workers:
            if w.handle not in self.miners:continue
            if (self.gathered.get(w.handle)!=mine.handle or w.handle in idle) and now-self.orders.get(w.handle,-100)>3:
                r=g.gather(w,mine);self.orders[w.handle]=now
                if r:self.gathered[w.handle]=mine.handle
                self.log('expansion_gather',clock=now,worker=w.handle,mine=mine.handle,accepted=bool(r))

    def tick(self,g,e,home,now,threat=False):
        if self.ready:
            if not threat and not self.danger(g,self.point) and e.count(g,'uaco')<10:
                halls=e.ready(g,'unpl')+e.ready(g,'unp1')+e.ready(g,'unp2')
                for hall in sorted(halls,key=lambda h:g.dist(h,self.point)):
                    if e.train(g,hall,'uaco',now):return True
            return False
        if threat or (self.point is not None and self.danger(g,self.point)):
            if self.builder:self.abort(g,home,now,'site_or_home_threatened')
            return False
        if now<self.retry_at:return False
        if self.point is None:
            if g.resources()['gold']<850 or g.resources()['lumber']<300:return False
            candidates=[]
            for point in self.mines.values():
                if g.dist(point,home)<1600 or not any(g.dist(point,(c['x'],c['y']))<1000 for c in self.camps):continue
                if any(g.dist(m,point)<300 and m.type in {'ugol','egol'} for m in g.gold_mines()):continue
                if self.danger(g,point) or not self.safe_route or not self.safe_route((home.x,home.y),point):continue
                distance=g.path_distance((home.x,home.y),point)
                if distance is not None:candidates.append((distance,point))
            if not candidates:return False
            self.point=min(candidates)[1]
            self.log('expansion_planned',clock=now,point=self.point)
        if self.rounds>=2 and self.builder is None:return False
        if self.danger(g,self.point):return False
        workers=g.units('me',{'uaco'})
        if self.builder is None:
            if len(workers)<6:
                if e.count(g,'uaco')<6:return e.train(g,home,'uaco',now)
                return False
            # The extra worker (including the former scout) is dedicated to this site.
            spare=[w for w in sorted(workers,key=lambda w:g.dist(w,home))[5:]
                   if w.handle not in e.repairs.reserved]
            w=next((w for w in spare if w.hp/w.hp_max>=.8 and not g.is_constructing(w)
                    and self.safe_route and self.safe_route((w.x,w.y),self.point)
                    and not self.danger(g,(w.x,w.y),800)),None)
            if w is None:return False
            self.builder=w.handle;self.rounds+=1;self.started=now
            self.retired_scout=True;e.scout=None
            self.log('expansion_builder',clock=now,handle=w.handle,point=self.point,round=self.rounds)
        w=next((w for w in workers if w.handle==self.builder),None)
        if not w or w.hp/w.hp_max<.5 or (w and self.danger(g,(w.x,w.y),800)) or now-self.started>420:
            self.abort(g,home,now,'builder_missing_unsafe_or_timeout');return False
        if g.dist(w,self.point)>400:
            if not self.safe_route or not self.safe_route((w.x,w.y),self.point):
                self.abort(g,home,now,'unsafe_route');return False
            if not self.nearby(g,{'ugol'}):
                if now-self.orders.get('move',-100)>3:
                    g.move(w,*self.point);self.orders['move']=now
                return False
        if not g.visible(*self.point):return False
        mines=self.nearby(g,{'ugol'})
        code='ugol' if not mines else 'unpl'
        if code=='unpl' and self.nearby(g,{'unpl','unp1','unp2'}):return False
        if code=='ugol' and (not any(m.type=='ngol' and g.dist(m,self.point)<128 for m in g.gold_mines()) or
                any(m.type in {'ugol','egol'} and m.owner!=g.me() and g.dist(m,self.point)<300 for m in g.gold_mines())):
            self.abort(g,home,now,'mine_not_available');return False
        if now-self.orders.get(code,-100)<15:return False
        if self.attempts.get(code,0)>=3:
            self.abort(g,home,now,'foundation_not_observed');return False
        if not g.can_afford(code):return False
        self.orders[code]=now;self.attempts[code]=self.attempts.get(code,0)+1
        r=g.build(w,code,*self.point) if code=='ugol' else g.build_near(w,code,*self.point,min_r=384,max_r=768,max_tries=24)
        self.log('expansion_build_attempt',clock=now,code=code,point=self.point,accepted=bool(r),attempt=self.attempts[code])
        # A pending summon has not paid yet. Pause other purchases briefly until observed.
        return bool(r)

    def pending_budget(self,now):
        return self.builder is not None and any(0<=now-self.orders.get(c,-100)<5 for c in ('ugol','unpl'))
