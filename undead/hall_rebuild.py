"""Bounded replacement of a lost home hall from previously observed own data."""


class HallRebuild:
    def __init__(self, log):
        self.log=log;self.home=None;self.pending=False;self.next_at=0;self.attempts=0
        self.observed=None

    def observe(self,g,home,now):
        self.home=(home.x,home.y)
        if not self.pending:return
        if self.observed!=home.handle:
            self.observed=home.handle
            self.log('hall_rebuild_observed',clock=now,handle=home.handle,point=self.home)
        production=g.production(home)
        if home.hp>=home.hp_max*.999 and not (production and production.kind=='construction'):
            self.log('hall_rebuild_complete',clock=now,handle=home.handle)
            self.pending=False;self.attempts=0;self.next_at=0;self.observed=None

    def tick(self,g,e,now,threat):
        if self.home is None or threat or now<self.next_at or not hasattr(g,'enemies'):return
        # Fail closed for the entire build search area and approach. Use only
        # currently fair-visible enemies; receipt alone never proves completion.
        enemies=[u for u in g.enemies() if u.hp>0]
        if any(g.dist(u,self.home)<2200 for u in enemies):return
        if self.pending and any(g.is_constructing(u) for u in g.units('me',{'uaco'})):return
        workers=[u for u in g.units('me',{'uaco'}) if u.handle!=e.scout
                 and u.handle not in e.expansion.reserved and u.handle not in e.repairs.reserved
                 and u.hp>=u.hp_max*.8 and not g.is_constructing(u)
                 and g.dist(u,self.home)<1200 and not any(g.dist(u,v)<900 for v in enemies)]
        if not workers or not g.can_afford('unpl'):return
        worker=min(workers,key=lambda u:g.dist(u,self.home))
        self.attempts+=1
        self.next_at=now+(120 if self.attempts>=3 else 15)
        attempt=self.attempts
        if self.attempts>=3:self.attempts=0
        point=g.build_near(worker,'unpl',*self.home,min_r=0,max_r=384,max_tries=24)
        if point:self.pending=True
        self.log('hall_rebuild_attempt',clock=now,worker=worker.handle,point=point,
                 accepted=bool(point),attempt=attempt,retry_at=self.next_at)
