"""Four-start reconnaissance: candidates are public, occupied starts need vision."""
from math import hypot, cos, sin, pi
from types import SimpleNamespace
from .structures import is_structure

class StartSearch:
    def __init__(self,log):
        self.log=log;self.points=None;self.checked={};self.failures={};self.job=None;self.confirmed=None
        self.neutral_memory={}
        self.detour=None;self.detour_history=[]
        self.camps=[] # Fingerprint-verified public layout, never hidden live units.
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

    def safe_step(self,g,scout,point,now,public_layout=True,step_limit=350):
        """Bounded local detour around fairly visible neutrals; never order into a camp."""
        # Retain only observed positions, not inferred current hidden units.
        # Losing vision during a detour must not send the scout back through the camp.
        for u in self.neutrals(g):
            self.neutral_memory[u.handle]=(now,SimpleNamespace(x=u.x,y=u.y,handle=u.handle))
        self.neutral_memory={h:row for h,row in self.neutral_memory.items() if now-row[0]<60}
        foes=[u for _,u in self.neutral_memory.values() if g.dist(u,scout)<1600]
        # Trees can hide guards until the worker is already in acquisition range.
        # Treat unseen public placements as route risks, not scouting evidence.
        risks=[]
        for camp in self.camps if public_layout else []:
            for i,spawn in enumerate(camp.get('spawns',[])):
                p=(spawn['x'],spawn['y'])
                if g.dist(scout,p)>=1600:continue
                if hasattr(g,'visible') and g.visible(*p) is True:continue
                risks.append(SimpleNamespace(x=p[0],y=p[1],handle=('public',camp['id'],i)))
        foes+=risks
        if not foes:
            self.detour=None
            return point
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
        def first_step(goal):
            # Checking an SDK route then issuing its final destination lets the
            # engine take a different route through the very camp we avoided.
            path=g.walk_path(origin,goal) or []
            turn=next((p for p in path if g.dist(origin,p)>32),origin)
            length=g.dist(origin,turn)
            scale=min(1,step_limit/length) if length and step_limit is not None else 1 if length else 0
            return (origin[0]+(turn[0]-origin[0])*scale,origin[1]+(turn[1]-origin[1])*scale)
        if safe(point):
            self.detour=None
            return first_step(point)
        # Commit to the safe local waypoint, rather than selecting the opposite
        # side on every tick after only traversing its first 350-unit segment.
        if self.detour:
            job=self.detour
            if job['goal']==point and now-job['started']<12 and g.dist(origin,job['point'])>100 and safe(job['point']):
                return first_step(job['point'])
            self.detour=None
        self.detour_history=[(at,p) for at,p in self.detour_history if now-at<90]
        self.detour_history.append((now,origin))
        choices=[]
        for i in range(16):
            p=(scout.x+650*cos(i*pi/8),scout.y+650*sin(i*pi/8))
            if safe(p):choices.append(p)
        if choices:
            waypoint=min(choices,key=lambda p:g.dist(p,point)+sum(
                max(0,650-g.dist(p,visited))*2 for _,visited in self.detour_history))
            self.detour=dict(goal=point,point=waypoint,started=now)
            target=first_step(waypoint)
        else:target=origin
        if now-getattr(self,'avoid_logged',-100)>=3:
            self.avoid_logged=now
            self.log('scout_neutral_detour',clock=now,origin=origin,goal=point,point=target,
                     threats=[u.handle for u in foes if u not in risks],public_layout_risks=[u.handle for u in risks],
                     blocked=not bool(choices))
        return target
