"""Reserve generous building envelopes and an outward lane at the home base."""
from math import cos,sin,pi,hypot

# Planning envelopes, not claims about exact engine collision footprints.
ENVELOPES={'unpl':192,'unp1':192,'unp2':192,'ugol':192,
           'uzig':96,'uzg1':96,'uzg2':96,'uaod':128,'utom':128,
           'usep':160,'ugrv':160,'uslh':160,'ubon':160}


def clear_of_buildings(point,buildings,padding=48,half=0):
    return all(max(abs(point[0]-b.x),abs(point[1]-b.y))>=
               ENVELOPES.get(b.type,160)+half+padding for b in buildings)


class HomeLayout:
    def __init__(self,log=lambda *a,**k:None):
        self.cursors={};self.pending={};self.log=log

    @property
    def reserved(self):
        return {p['worker'] for p in self.pending.values()}

    def observe(self,g,now):
        buildings=g.my_buildings()
        for code,p in list(self.pending.items()):
            foundation=next((u for u in buildings if u.type==code and u.handle not in p['before']
                             and max(abs(u.x-p['point'][0]),abs(u.y-p['point'][1]))<128),None)
            if foundation:
                self.pending.pop(code,None)
                self.log('home_foundation_observed',clock=now,code=code,point=(foundation.x,foundation.y),handle=foundation.handle)
                continue
            worker=next((u for u in g.units('me',{'uaco'}) if u.handle==p['worker']),None)
            if worker is None:
                self.pending.pop(code,None);continue
            gap=hypot(worker.x-p['point'][0],worker.y-p['point'][1])
            if gap<p['gap']-32:p.update(gap=gap,progress=now)
            # An accepted build can still be travelling through the order queue.
            # Do not redirect that worker to mining or another building while
            # waiting for the fair snapshot's actual foundation.
            if now-p['started']<24:continue
            order=g.order_of(worker) or 0
            if order>=0x20202020 and now-p['progress']<16:continue
            if order>=0x20202020:g.hold(worker)
            self.pending.pop(code,None)
            self.log('home_foundation_unconfirmed',clock=now,code=code,point=p['point'],worker=p['worker'],order=order)

    def candidates(self,code,home,buildings):
        half=ENVELOPES.get(code,160)
        length=hypot(home.x,home.y)
        direction=(-home.x/length,-home.y/length) if length else (1,0)
        points=set()
        for radius in range(512,1537,192):
            for k in range(16):
                angle=2*pi*k/16
                points.add((round((home.x+radius*cos(angle))/32)*32,
                            round((home.y+radius*sin(angle))/32)*32))
        # Sparse radial spokes miss usable gaps on cramped bases such as LR.
        # Densify the search, keeping exactly the same spacing and exit lane.
        points.update((round(home.x/32)*32+x,round(home.y/32)*32+y)
                      for x in range(-1024,1025,128) for y in range(-1024,1025,128))
        for point in sorted(points,key=lambda p:(hypot(p[0]-home.x,p[1]-home.y),p)):
            dx,dy=point[0]-home.x,point[1]-home.y
            along=dx*direction[0]+dy*direction[1]
            across=abs(dx*direction[1]-dy*direction[0])
            if along>0 and across<half+128:continue
            if clear_of_buildings(point,buildings,128,half):yield point

    def build(self,g,worker,code,home,now=None):
        # Keep SDK pending-foundation tracking, failure blacklisting and receipts.
        if code in self.pending:return self.pending[code]['point']
        buildings=g.my_buildings()
        points=list(self.candidates(code,home,buildings))
        grid=g.map() if hasattr(g,'map') else None
        trees=[t for t in g.trees(home.x,home.y,limit=400) if g.visible(t.x,t.y)] if hasattr(g,'trees') and hasattr(g,'visible') else []
        half=ENVELOPES.get(code,160)
        def plausible(p):
            if grid and hasattr(grid,'buildable') and not all(grid.buildable(p[0]+x,p[1]+y)
                    for x in (-half,0,half) for y in (-half,0,half)):return False
            return not any(max(abs(t.x-p[0]),abs(t.y-p[1]))<half+64 for t in trees)
        points=[p for p in points if plausible(p)]
        if not points:return None
        key=(code,home.x,home.y);start=self.cursors.get(key,0)%len(points)
        for offset in range(min(24,len(points))):
            index=(start+offset)%len(points);point=points[index]
            spot=g.build_near(worker,code,*point,min_r=0,max_r=0,max_tries=1)
            # An existing SDK walking order returns its earlier point. Keep it
            # intact; advance the cursor only for a newly tried location.
            if not spot or tuple(spot)==point:self.cursors[key]=(index+1)%len(points)
            if spot:
                if now is not None and worker is not None:
                    self.pending[code]=dict(point=tuple(spot),worker=worker.handle,started=now,progress=now,
                        gap=hypot(worker.x-spot[0],worker.y-spot[1]),before={u.handle for u in buildings if u.type==code})
                return spot
        return None
