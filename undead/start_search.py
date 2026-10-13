"""Four-start reconnaissance: candidates are public, occupied starts need vision."""
from math import hypot, cos, sin, pi
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
            guarded=any(g.dist(u,p)<800 and g.dist(u,scout)<1200 for u in self.neutrals(g))
            if guarded:
                self.checked[p]=now;self.job=None
                self.log('start_area_scouted',clock=now,point=p,evidence='visible_neutral_guard_not_complete_area')
            elif g.dist(scout,p)<550 and g.visible(*p) is True:
                self.checked[p]=now;self.job=None
                self.log('start_area_scouted',clock=now,point=p,evidence='visible_point_not_complete_area')
            elif d is None or now-job['progress']>15:
                self.failures[p]=now;self.job=None
                self.log('start_route_deferred',clock=now,point=p)
            else:return p
        rows=[]
        # Finish all never-observed starts before revisiting an expired empty one.
        unchecked={p for p in self.points if p not in self.checked}
        for p in self.points:
            if unchecked and p not in unchecked:continue
            if now-self.checked.get(p,-1000)<120 or now-self.failures.get(p,-1000)<30:continue
            d=g.path_distance(scout,p)
            if d is not None:rows.append((d,p))
        if not rows:return None
        d,p=min(rows);self.job=dict(point=p,distance=d,progress=now)
        self.log('start_scout_goal',clock=now,point=p,ground_distance=d)
        return p

    @staticmethod
    def neutrals(g):
        return [u for u in (g.creeps() if hasattr(g,'creeps') else [])
                if u.hp>0 and (not hasattr(u,'visible_to') or u.visible_to(g.me()))]

    def safe_step(self,g,scout,point,now):
        """Bounded local detour around fairly visible neutrals; never order into a camp."""
        foes=[u for u in self.neutrals(g) if g.dist(u,scout)<1600]
        if not foes:return point
        origin=(scout.x,scout.y)
        def safe(goal):
            path=g.walk_path(origin,goal)
            if not path:return False
            for e in foes:
                initial=g.dist(scout,e)
                # Inside the safety margin, permit only outward escape.
                margin=min(800,initial)
                if g.dist(goal,e)<margin or initial<800 and g.dist(goal,e)<=initial+50:return False
                a=origin
                for z in path:
                    dx,dy=z[0]-a[0],z[1]-a[1];length=dx*dx+dy*dy
                    t=max(0,min(1,((e.x-a[0])*dx+(e.y-a[1])*dy)/length)) if length else 0
                    if hypot(a[0]+t*dx-e.x,a[1]+t*dy-e.y)<margin-1:return False
                    a=z
            return True
        if safe(point):return point
        choices=[]
        for i in range(16):
            p=(scout.x+650*cos(i*pi/8),scout.y+650*sin(i*pi/8))
            if safe(p):choices.append(p)
        target=min(choices,key=lambda p:g.dist(p,point)) if choices else origin
        if now-getattr(self,'avoid_logged',-100)>=3:
            self.avoid_logged=now
            self.log('scout_neutral_detour',clock=now,origin=origin,goal=point,point=target,
                     threats=[u.handle for u in foes],blocked=not bool(choices))
        return target
