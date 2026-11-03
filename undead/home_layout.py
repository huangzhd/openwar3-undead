"""Reserve generous building envelopes and an outward lane at the home base."""
from math import cos,sin,pi,hypot
from time import perf_counter
from .replay_opening import fixed_slot,LR_HALF

# Planning envelopes, not claims about exact engine collision footprints.
ENVELOPES={'unpl':192,'unp1':192,'unp2':192,'ugol':192,
           'uzig':96,'uzg1':96,'uzg2':96,'uaod':128,'utom':128,
           'usep':160,'ugrv':160,'uslh':160,'ubon':160}

# NI southwest, observed in 20261020-184054. Preserve successful command
# coordinates: the engine snapped the shop's center to (-2240, -3520).
NI_SW_OPENING={'utom':(-2272,-3520),'ugrv':(-2112,-3072)}
# AL southwest, successful command in 20261021-185036; center snapped to
# (-2368, -4160). The northeast spawn has not been verified.
AL_SW_OPENING={'utom':(-2368,-4192)}


def clear_of_buildings(point,buildings,padding=48,half=0):
    return all(max(abs(point[0]-b.x),abs(point[1]-b.y))>=
               ENVELOPES.get(b.type,160)+half+padding for b in buildings)


class HomeLayout:
    def __init__(self,log=lambda *a,**k:None):
        self.cursors={};self.pending={};self.log=log;self.failed_spots={}
        self.map_alias=None
        self.opening_profile=None
        self.opening_issued=set()
        self.opening_foundations=set()
        self.new_foundations=set()

    def opening_due(self,code,now):
        # Graveyard uses the normal affordability check as soon as the shop is underway.
        return code=='ugrv' or now*1000>=self.opening_profile[code][0]-400

    def opening_order(self,g,code,issue):
        target=self.opening_profile[code][0]
        before=g.snapshot(max_age=0)
        if not before or not self.opening_due(code,before.clock):return False
        result=issue()
        after=g.snapshot(max_age=0)
        self.log('reference_order',code=code,target_ms=target,clock=before.clock,
                 after=after.clock if after and after.epoch==before.epoch else None,accepted=bool(result))
        if result:self.opening_issued.add(code)
        return result

    @property
    def reserved(self):
        return {p['worker'] for p in self.pending.values()}

    def observe(self,g,now):
        self.new_foundations.clear()
        buildings=g.my_buildings()
        for code,p in list(self.pending.items()):
            foundation=next((u for u in buildings if u.type==code and u.handle not in p['before']
                             and max(abs(u.x-p['point'][0]),abs(u.y-p['point'][1]))<128),None)
            if foundation:
                self.pending.pop(code,None)
                self.new_foundations.add(foundation.handle)
                if self.opening_profile and code in self.opening_profile:self.opening_foundations.add(code)
                self.log('home_foundation_observed',clock=now,code=code,point=(foundation.x,foundation.y),handle=foundation.handle)
                continue
            worker=next((u for u in g.units('me',{'uaco'}) if u.handle==p['worker']),None)
            if worker is None:
                self.pending.pop(code,None);continue
            gap=hypot(worker.x-p['point'][0],worker.y-p['point'][1])
            if gap<p['gap']-32:p.update(gap=gap,progress=now)
            if now-p['started']>=2:
                order=g.order_of(worker) or 0
                # A dropped order is failure, not a reason to wait 24 seconds.
                # Preserve real travel; a motionless build order is cancelled
                # after three seconds without observed movement or foundation.
                if order<0x20202020 or now-p['progress']>=3:
                    if order>=0x20202020:g.hold(worker)
                    self.pending.pop(code,None)
                    fixed=fixed_slot(self.map_alias,p.get('home'),code,buildings) if p.get('home') is not None else None
                    self.failed_spots[(code,p['point'])]=now+(3 if fixed==p['point'] or fixed and self.opening_profile else 45)
                    self.log('home_foundation_unconfirmed',clock=now,code=code,point=p['point'],
                             worker=p['worker'],order=order,reason='order_lost' if order<0x20202020 else 'no_worker_progress')
                    home=p.get('home')
                    if home is not None and g.can_afford(code):
                        self.build(g,worker,code,home,now)
                        return True # Economy must not spend the same snapshot twice.
                    continue
                continue
            # The initial snapshot grace also applies to towers and production.

    def candidates(self,code,home,buildings):
        fixed=fixed_slot(self.map_alias,home,code,buildings)
        if fixed is not None:
            # Use the same-side rule layout as a set; mixing towers from one
            # layout with the shop from another can obstruct the shop.
            if clear_of_buildings(fixed,buildings,0,LR_HALF[code]):yield fixed
            if self.opening_profile:
                alternatives={self.opening_profile[code][1]}
                if code=='utom':
                    x,y=fixed
                    alternatives.update((x+dx,y+dy) for dx in range(-384,385,64) for dy in range(-384,385,64)
                                        if dx*dx+dy*dy<=384*384)
                for nearby in sorted(alternatives-{fixed},key=lambda p:((p[0]-fixed[0])**2+(p[1]-fixed[1])**2,p)):
                    if clear_of_buildings(nearby,buildings,0,LR_HALF[code]):yield nearby
            return
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
        preferred=[]
        crypt=min((b for b in buildings if b.type=='usep'),
                  key=lambda b:hypot(b.x-home.x,b.y-home.y),default=None)
        if code=='utom' and crypt is not None:
            # Put the shop to the right of the actual crypt, preserving the
            # old shop slot beside the hall for the graveyard. Wider offsets
            # are considered when the closer point crosses the outward lane.
            preferred=[(round((crypt.x+dx)/32)*32,round(crypt.y/32)*32)
                       for dx in (512,640,768,896)]
        elif code=='ugrv':
            preferred=[(round((home.x+512)/32)*32,round(home.y/32)*32)]
        # A measured slot precedes the old speculative crypt-side choices.
        # Do not mirror unverified terrain or apply NI coordinates on other maps.
        if (self.map_alias=='NI' and (home.x,home.y)==(-2752,-3328)
                and code in NI_SW_OPENING and not any(b.type==code for b in buildings)):
            preferred=[NI_SW_OPENING[code]]
        if (self.map_alias=='AL' and (home.x,home.y)==(-2176,-4672)
                and code in AL_SW_OPENING and not any(b.type==code for b in buildings)):
            preferred=[AL_SW_OPENING[code]]
        ordered=preferred+sorted(points-set(preferred),key=lambda p:(hypot(p[0]-home.x,p[1]-home.y),p))
        for point in ordered:
            if code=='utom' and crypt is not None and point==(round((home.x+512)/32)*32,round(home.y/32)*32):
                continue # Keep the previous shop position available for the graveyard.
            dx,dy=point[0]-home.x,point[1]-home.y
            along=dx*direction[0]+dy*direction[1]
            across=abs(dx*direction[1]-dy*direction[0])
            if along>0 and across<half+128:continue
            if clear_of_buildings(point,buildings,128,half):yield point

    def build(self,g,worker,code,home,now=None):
        # Generic sites retain SDK tracking. Fixed sites use our foundation
        # tracker, avoiding the SDK's 45 wall-second failed-site blacklist.
        if code in self.pending:return self.pending[code]['point']
        started=perf_counter()
        buildings=g.my_buildings()
        fixed=fixed_slot(self.map_alias,home,code,buildings)
        points=list(self.candidates(code,home,buildings))
        grid=g.map() if hasattr(g,'map') else None
        # Visibility is a synchronous engine query. Check only trees touching
        # the candidate being tried, with a hard per-tick query budget.
        trees=g.trees(home.x,home.y,limit=400) if hasattr(g,'trees') and hasattr(g,'visible') else []
        half=LR_HALF[code] if fixed is not None else ENVELOPES.get(code,160)
        if not points:return None
        visibility={};queries=0;attempts=0
        def finish(spot):
            self.log('home_layout_timing',clock=now,code=code,visible_queries=queries,
                     build_attempts=attempts,wall_ms=round((perf_counter()-started)*1000,3))
            return spot
        key=(code,home.x,home.y);start=self.cursors.get(key,0)%len(points)
        for offset in range(min(24,len(points))):
            index=(start+offset)%len(points);point=points[index]
            self.cursors[key]=(index+1)%len(points)
            if now is not None and now<self.failed_spots.get((code,point),-1):continue
            # Inspect interior cell centers, not cells just outside the fixed footprint.
            sample=half-16 if fixed is not None else half
            if grid and hasattr(grid,'buildable') and not all(grid.buildable(point[0]+x,point[1]+y)
                    for x in (-sample,0,sample) for y in (-sample,0,sample)):continue
            blocked=False
            for tree in trees:
                if max(abs(tree.x-point[0]),abs(tree.y-point[1]))>=half+64:continue
                loc=(tree.x,tree.y)
                if loc not in visibility:
                    if queries>=16:
                        # Skip this unverified candidate for this pass, and
                        # continue scanning next tick without blocking control.
                        return finish(None)
                    visibility[loc]=g.visible(*loc);queries+=1
                if visibility[loc] is None:
                    blocked=True;break
                if visibility[loc]:blocked=True;break
            if blocked:continue
            attempts+=1
            if fixed is not None:
                if not g.can_afford(code):return finish(None)
                if self.opening_profile and code not in self.opening_issued:
                    if now is not None and not self.opening_due(code,now):return finish(None)
                    issued=self.opening_order(g,code,lambda:g.build(worker,code,*point))
                else:issued=g.build(worker,code,*point)
                spot=point if issued else None
            else:
                spot=g.build_near(worker,code,*point,min_r=0,max_r=0,max_tries=1)
            if fixed is not None and not spot and now is not None:
                self.failed_spots[(code,point)]=now+3
                self.log('home_fixed_slot_retry',clock=now,code=code,point=point,retry_at=now+3)
                return finish(None)
            if spot and now is not None and now<self.failed_spots.get((code,tuple(spot)),-1):
                return finish(None) # Wait for SDK to observe the cancellation, not another 24s hold.
            # An existing SDK walking order returns its earlier point. Keep it
            # intact; advance the cursor only for a newly tried location.
            if spot and tuple(spot)!=point:self.cursors[key]=start
            if spot:
                if now is not None and worker is not None:
                    self.pending[code]=dict(point=tuple(spot),worker=worker.handle,started=now,progress=now,home=home,
                        gap=hypot(worker.x-spot[0],worker.y-spot[1]),before={u.handle for u in buildings if u.type==code})
                    self.log('home_build_order_pending',clock=now,code=code,point=tuple(spot),worker=worker.handle)
                return finish(spot)
        return finish(None)
