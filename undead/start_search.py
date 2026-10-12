"""Four-start reconnaissance: candidates are public, occupied starts need vision."""
from math import hypot
from .structures import is_structure

class StartSearch:
    def __init__(self,log):
        self.log=log;self.points=None;self.checked={};self.failures={};self.job=None;self.confirmed=None
    def update(self,g,home,now):
        mp=g.map()
        if self.points is None and mp:
            self.points=sorted({tuple(p) for p in mp.starts if tuple(p)!=(0,0) and g.dist(home,p)>1500})
        if not self.points:return None
        # Two starts determine the other start without consulting hidden placements.
        if len(self.points)==1:return self.points[0]
        for u in g.enemies():
            if not u.alive or not u.visible_to(g.me()) or not is_structure(u):continue
            point=min(self.points,key=lambda p:g.dist(u,p))
            if g.dist(u,point)<1500:
                if self.confirmed!=point:
                    self.confirmed=point;self.log('enemy_start_confirmed',clock=now,point=point,unit=u.type,handle=u.handle)
                return point
        return self.confirmed
    def choose(self,g,scout,now):
        if not self.points:return None
        if self.job:
            job=self.job;p=job['point'];d=g.path_distance(scout,p)
            if d is not None and d<job['distance']-80:job.update(distance=d,progress=now)
            if g.dist(scout,p)<550 and g.visible(*p) is True:
                self.checked[p]=now;self.job=None
                self.log('start_area_scouted',clock=now,point=p,evidence='visible_point_not_complete_area')
            elif d is None or now-job['progress']>15:
                self.failures[p]=now;self.job=None
                self.log('start_route_deferred',clock=now,point=p)
            else:return p
        rows=[]
        for p in self.points:
            if now-self.checked.get(p,-1000)<120 or now-self.failures.get(p,-1000)<30:continue
            d=g.path_distance(scout,p)
            if d is not None:rows.append((d,p))
        if not rows:return None
        d,p=min(rows);self.job=dict(point=p,distance=d,progress=now)
        self.log('start_scout_goal',clock=now,point=p,ground_distance=d)
        return p
