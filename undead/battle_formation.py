"""Small, safe flank adjustments while the rest of the firing line attacks."""
from math import hypot,atan2,cos,sin,pi,ceil
from .retreat import clearance
from .structures import is_structure


class BattleFormation:
    def __init__(self,log):
        self.log=log;self.pending={};self.retry={};self.checked=-100

    def step(self,b,army,foes,target,now,protected=()):
        from .controller import ground_attack_range
        g=b.g;reserved=set(protected)|set(b.micro.pulling)|set(b.shield_moves)|set(b.shopping)
        ranged=[u for u in army if u.type in {'ucry','Ulic','Nbrn','Nngs'}]
        by_handle={u.handle:u for u in ranged};moving=set()
        for handle,p in list(self.pending.items()):
            u=by_handle.get(handle)
            if u is None or handle in reserved or now<b.cast_until.get(handle,0):
                self.pending.pop(handle,None);continue
            if g.dist(u,p['origin'])>64 and g.dist(u,p['point'])<g.dist(p['origin'],p['point'])-64 and not p.get('observed'):
                p['observed']=True
                self.log('battle_fan_movement_observed',clock=now,handle=handle,point=(u.x,u.y),goal=p['point'])
            if now-p['at']>=2.5 or g.dist(u,p['point'])<70:
                self.pending.pop(handle,None)
            else:moving.add(handle)
        if len(ranged)<4 or len(moving)>=2 or now-self.checked<1.5:return moving
        self.checked=now
        anchor=min(ranged,key=lambda u:sum(g.dist(u,v) for v in ranged))
        ranged=[u for u in ranged if g.dist(u,anchor)<650]
        if len(ranged)<4:return moving
        dk=next(iter(g.units('me',{'Udea'})),None)
        dx,dy=target.x-anchor.x,target.y-anchor.y;length=hypot(dx,dy)
        if length<100:return moving
        dx,dy=dx/length,dy/length
        def lane(point):
            if dk is None:return False
            x,y=point[0]-dk.x,point[1]-dk.y
            return -500<x*dx+y*dy<160 and abs(x*dy-y*dx)<140
        congested=[u for u in ranged if lane((u.x,u.y)) or
                   any(v.handle!=u.handle and g.dist(u,v)<130 for v in ranged) or
                   sum(v.handle!=u.handle and g.dist(u,v)<210 for v in ranged)>=2]
        congested.sort(key=lambda u:(not lane((u.x,u.y)),u.handle))
        grid=g.map() if hasattr(g,'map') else None
        if not grid:return moving
        # A battle at the enemy base must not inherit the creeping exclusion
        # circle. Still include visible structures in the actual fire checks.
        visible=g.enemies() if hasattr(g,'enemies') else foes
        threats=list({e.handle:e for e in [*foes,*visible] if e.hp>0 and ground_attack_range(e.type)>0}.values())
        towers=[e for e in threats if is_structure(e)]
        angle=atan2(anchor.y-target.y,anchor.x-target.x)
        occupied=[p['point'] for p in self.pending.values()]
        for u in congested:
            if len(moving)>=2:break
            if u.handle in reserved|moving or now<b.cast_until.get(u.handle,0) or now<self.retry.get(u.handle,0):continue
            radius=min(500,max(220,ground_attack_range(u.type)-60))
            points=[(target.x+radius*cos(angle+offset*pi/180),target.y+radius*sin(angle+offset*pi/180))
                    for offset in (-28,28,-48,48,-68,68)]
            points.sort(key=lambda p:g.dist(u,p))
            before=clearance((u.x,u.y),threats,ground_attack_range)
            for point in points:
                gap=g.dist(u,point)
                if gap<90 or gap>340 or lane(point) or not grid.walkable(*point):continue
                if any(g.dist(point,p)<170 for p in occupied):continue
                if any(v.handle!=u.handle and g.dist(v,point)<160 for v in army):continue
                if any(g.dist(point,e)<min(ground_attack_range(e.type),g.dist(u,e)) for e in towers):continue
                route=g.path_distance((u.x,u.y),point)
                if route is None or route>gap+128:continue
                path=g.walk_path((u.x,u.y),point)
                if not path or g.dist(path[-1],point)>96:continue
                safe=True;a=(u.x,u.y)
                for z in path:
                    n=max(1,ceil(g.dist(a,z)/80))
                    if any(clearance((a[0]+(z[0]-a[0])*j/n,a[1]+(z[1]-a[1])*j/n),threats,ground_attack_range)<before-40 for j in range(1,n+1)):
                        safe=False;break
                    if any(g.dist((a[0]+(z[0]-a[0])*j/n,a[1]+(z[1]-a[1])*j/n),e)<min(ground_attack_range(e.type),g.dist(u,e))-8
                           for e in towers for j in range(1,n+1)):
                        safe=False;break
                    a=z
                if not safe:continue
                if g.move(u,*point):
                    self.pending[u.handle]=dict(origin=(u.x,u.y),point=point,at=now)
                    self.retry[u.handle]=now+7;moving.add(u.handle);occupied.append(point)
                    self.log('battle_fan_move_attempt',clock=now,handle=u.handle,unit=u.type,point=point,accepted=True,dk_lane=bool(dk))
                break
        return moving
