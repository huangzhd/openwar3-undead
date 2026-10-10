"""Finite fair search after the observed main area has no known enemy structures."""

class AttackSearch:
    def __init__(self,log):
        self.log=log;self.pending=[];self.goal=None;self.rounds=0
        self.progress_at=0;self.best=None;self.last_call=None;self.reported=False
        self.observed_at=-100

    def observe_pending(self,g,center,now):
        # Query a bounded nearby batch, using only our current vision. Seeing a
        # sample point is not proof that its surrounding square is fully covered.
        if now-self.observed_at<2:return
        self.observed_at=now
        nearby=sorted((c for c in self.pending if g.dist(center,c['point'])<1400),
                      key=lambda c:g.dist(center,c['point']))[:12]
        for candidate in nearby:
            if g.visible(*candidate['point']):
                self.pending.remove(candidate)
                self.log('attack_search_checked',clock=now,round=self.rounds,
                         evidence='visible_point',opportunistic=True,**candidate)

    def candidates(self,g,home,main,sites):
        candidates={}
        def add(point,kind):
            point=tuple(point)
            if g.dist(point,home)<1400 or g.dist(point,main)<900:return
            key=(round(point[0]/128),round(point[1]/128))
            if key not in candidates:candidates[key]={'point':point,'kind':kind}
        for point in sites:add(point,'expansion')
        mp=g.map()
        if mp and all(hasattr(mp,k) for k in ('cols','rows','cell','min_x','min_y')):
            stride=max(1,round(1000/mp.cell))
            for row in range(stride//2,mp.rows,stride):
                for col in range(stride//2,mp.cols,stride):
                    point=(mp.min_x+(col+.5)*mp.cell,mp.min_y+(row+.5)*mp.cell)
                    if mp.walkable(*point):add(point,'area')
        return list(candidates.values())

    def choose(self,g,center,home,main,sites,now,combat=False):
        resumed=self.last_call is None or now-self.last_call>5
        self.last_call=now
        if self.goal:
            point=self.goal['point'];remaining=g.path_distance(center,point)
            if resumed or combat or (remaining is not None and (self.best is None or remaining<self.best-80)):
                self.progress_at=now;self.best=remaining
            if g.dist(center,point)<1400 and g.visible(*point):
                self.log('attack_search_checked',clock=now,round=self.rounds,
                         evidence='visible_point',opportunistic=False,**self.goal)
                self.goal=None
            elif remaining is None or now-self.progress_at>45:
                self.log('attack_search_deferred',clock=now,reason='unreachable' if remaining is None else 'no_route_progress',**self.goal)
                self.goal=None
        self.observe_pending(g,center,now)
        while self.goal is None:
            if not self.pending:
                if self.rounds>=2:
                    if not self.reported:
                        self.reported=True;self.log('attack_search_exhausted',clock=now,rounds=self.rounds)
                    return None
                self.rounds+=1
                self.pending=self.candidates(g,home,main,sites)
                self.log('attack_search_round',clock=now,round=self.rounds,candidates=len(self.pending))
                if not self.pending:continue
            # Keep expansion priority; compare ground travel for a local batch
            # instead of repeatedly choosing the closest point across a wall.
            kind='expansion' if any(c['kind']=='expansion' for c in self.pending) else 'area'
            batch=sorted((c for c in self.pending if c['kind']==kind),
                         key=lambda c:g.dist(center,c['point']))[:8]
            reachable=[]
            for candidate in batch:
                remaining=g.path_distance(center,candidate['point'])
                if remaining is None:
                    self.pending.remove(candidate)
                    self.log('attack_search_deferred',clock=now,reason='unreachable',**candidate)
                else:reachable.append((remaining,candidate))
            if not reachable:continue
            remaining,candidate=min(reachable,key=lambda pair:pair[0])
            self.pending.remove(candidate)
            self.goal=candidate;self.progress_at=now;self.best=remaining
            self.log('attack_search_goal',clock=now,round=self.rounds,ground_distance=remaining,**candidate)
        return self.goal['point']
