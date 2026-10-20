"""Shared terrain turns and individual correction without stopping the main body."""
from math import hypot, ceil


def xy(u): return (u.x,u.y)
def distance(a,b): return hypot(a[0]-b[0],a[1]-b[1])

def subdivide(start,turns,step=384):
    points=[]
    for end in turns:
        n=max(1,ceil(distance(start,end)/step))
        points.extend((start[0]+(end[0]-start[0])*i/n,start[1]+(end[1]-start[1])*i/n) for i in range(1,n+1))
        start=end
    return points

class Formation:
    def __init__(self,log):
        self.log=log
        self.stage='idle'
        self.rally=None
        self.rally_retries=0
        self.route=[]
        self.objective=None
        self.last_plan=-100
        self.last_report=-100
        self.last_progress=-100
        self.last_center=None
        self.anchor=None
        self.metrics={}
        self.known=set()
        self.joiners=set()
        self.rally_distance=None
        self.cursors={}
        self.aura_wait=False
        self.route_distance=None
        self.catching_up=set()
        self.forward_fiends=set()
        self.unit_progress={}

    def reset(self):
        self.rally=None;self.rally_retries=0;self.rally_distance=None
        self.route=[];self.objective=None;self.last_plan=-100
        self.cursors={};self.aura_wait=False;self.route_distance=None
        self.catching_up=set()
        self.forward_fiends=set();self.unit_progress={}

    def cursor_at(self,u):
        index=min(self.cursors.get(u.handle,0),max(0,len(self.route)-1))
        while index<len(self.route)-1 and distance(xy(u),self.route[index])<240:
            index+=1
        return index

    def plan(self,units,target,now,ground_distance,path,retreat=False):
        """Return (unit, point, hold). No desktop or hidden-world access."""
        if not units: return []
        core=[u for u in units if u.type not in {'uske','uskm','nsce','nsca'}] or units
        veterans=[u for u in core if u.handle in self.known and u.handle not in self.joiners] or core
        leader=min(veterans,key=lambda u:sum(distance(xy(u),xy(v)) for v in veterans))
        for u in core:
            route_distance=ground_distance(xy(u),xy(leader))
            if self.known and u.handle not in self.known and not u.is_hero and (route_distance is None or route_distance>700):
                self.joiners.add(u.handle)
            if route_distance is not None and route_distance<500:self.joiners.discard(u.handle)
        self.known={u.handle for u in core}
        self.joiners &= self.known
        core=[u for u in core if u.handle not in self.joiners] or core
        anchor=min(core,key=lambda u:sum(distance(xy(u),xy(v)) for v in core))
        self.anchor=xy(anchor)
        distances=[ground_distance(xy(u),self.anchor) for u in core]
        spread=max((d if d is not None else 100000 for d in distances),default=0)
        heroes=[u for u in core if u.is_hero]
        hero_spread=max((distance(xy(a),xy(b)) for a in heroes for b in heroes),default=0)
        self.metrics=dict(clock=now,stage=self.stage,ground_spread=round(spread),hero_spread=round(hero_spread),members=len(core))
        # Keep the main body moving. Terrain separation corrects only the outlier.
        # The 128-cell grid can project adjacent units into disconnected pockets.
        # Missing coarse paths alone are not evidence that nearby units split around woods.
        divided={u.handle for u,d in zip(core,distances) if
                    (d is None and distance(xy(u),self.anchor)>900) or
                    (d is not None and d>max(800,distance(xy(u),self.anchor)*1.5+256))
                    }
        self.rally=None
        # A trailing veteran can keep acquiring roadside enemies on attack-move.
        # Let that unit catch the moving main body without stopping everyone.
        changed=self.objective is None or distance(self.objective,target)>192
        previous=set() if changed else self.catching_up
        self.catching_up=set() if retreat else divided
        main_left=ground_distance(self.anchor,target)
        if not retreat:
            for u,d in zip(core,distances):
                gap=d if d is not None else distance(xy(u),self.anchor)
                left=ground_distance(xy(u),target)
                behind=left is not None and main_left is not None and left>main_left+200
                if self.route and self.objective is not None and distance(self.objective,target)<=192:
                    # A unit around the next shared turn is ahead even when its
                    # straight-line distance to the final destination is larger.
                    behind=behind and self.cursor_at(u)<=self.cursor_at(anchor)
                if gap>(550 if u.handle in previous else 900) and (behind or u.handle in previous):
                    self.catching_up.add(u.handle)
        if self.route and not changed and previous-self.catching_up:
            for u in core:
                if u.handle in self.catching_up:continue
                # Rejoin this unit on the existing route; rebuilding everyone's route
                # sends leaders back to a new first turn behind their position.
                candidates=[];projections=[]
                for i,(a,b) in enumerate(zip(self.route,self.route[1:])):
                    dx,dy=b[0]-a[0],b[1]-a[1];length=dx*dx+dy*dy
                    t=max(0,min(1,((u.x-a[0])*dx+(u.y-a[1])*dy)/length)) if length else 1
                    projection=(a[0]+t*dx,a[1]+t*dy)
                    projections.append((distance(xy(u),projection),-i,projection))
                for _,negative_i,projection in sorted(projections)[:4]:
                    route=ground_distance(xy(u),projection)
                    if route is not None and route<=550:candidates.append((route,negative_i,1-negative_i))
                index=max(self.cursors.get(u.handle,0),min(candidates)[2]) if candidates else self.cursors.get(u.handle,0)
                self.cursors[u.handle]=index
                self.log('formation_rejoined',clock=now,handle=u.handle,cursor=index,
                         point=self.route[index],route_preserved=True)
        changed=self.objective is None or distance(self.objective,target)>192
        remaining=ground_distance(self.anchor,target)
        if remaining is not None and (self.route_distance is None or remaining<self.route_distance-80):
            self.last_progress=now;self.route_distance=remaining
        stalled=now-self.last_progress>25
        if changed or not self.route or (stalled and now-self.last_plan>10):
            turns=path(self.anchor,target)
            self.objective=target
            self.last_plan=now
            self.last_progress=now
            self.route_distance=remaining
            # Keep real terrain turns, not 384-unit interpolation points that stop every unit.
            self.route=list(turns) if turns else []
            self.cursors={}
        if not self.route:
            self.stage='blocked'
            self.report(now,spread,hero_spread,len(core))
            return [(u,xy(u),True) for u in units]
        self.stage='retreat' if retreat else 'advance'
        dk=next((u for u in core if u.type=='Udea'),None)
        companions=[u for u in core if u is not dk]
        self.aura_gap=0
        brake=False
        if dk and companions and not retreat:
            main=min(companions,key=lambda u:sum(distance(xy(u),xy(v)) for v in companions))
            self.aura_gap=distance(xy(dk),xy(main))
            dk_left=ground_distance(xy(dk),target)
            main_left=ground_distance(xy(main),target)
            ahead=dk_left is not None and main_left is not None and dk_left+200<main_left
            # Local 1.27a AUau has Area=900. Use margin and hysteresis; only DK returns to the moving main body.
            brake=ahead and self.aura_gap>(550 if self.aura_wait else 900)
        self.aura_wait=brake
        if brake:self.catching_up.add(dk.handle)
        previous_forward=self.forward_fiends
        self.forward_fiends=set()
        if not retreat:
            main_left=ground_distance(self.anchor,target)
            for u in core:
                left=ground_distance(xy(u),target)
                if (u.type=='ucry' and distance(xy(u),self.anchor)>(550 if u.handle in previous_forward else 900)
                        and left is not None and main_left is not None and left+200<main_left):
                    self.forward_fiends.add(u.handle)
        orders=[]
        for u in units:
            if u.handle in self.forward_fiends:
                orders.append((u,self.anchor,False))
                continue
            if u.handle in self.joiners or u.handle in self.catching_up:
                if retreat:
                    # LR 0.1.89 sent a newly produced home-side fiend toward
                    # the forward anchor while its main army was fleeing.
                    turns=path(xy(u),target)
                    point=next((p for p in turns if distance(xy(u),p)>=240),turns[-1]) if turns else xy(u)
                    orders.append((u,point,not bool(turns)))
                else:
                    orders.append((u,self.anchor,False))
                continue
            index=self.cursor_at(u)
            if index>self.cursors.get(u.handle,0):
                self.last_progress=now
            self.cursors[u.handle]=index
            point=self.route[index]
            # A crowded 128-grid corner can be unreachable in the engine even
            # while its projected route is valid. Advance just this stalled unit
            # to the next reachable shared turn, preserving everyone else's route.
            progress=self.unit_progress.get(u.handle)
            gap=distance(xy(u),point)
            if progress is None or progress['point']!=point or gap<progress['gap']-48:
                progress=dict(point=point,gap=gap,clock=now);self.unit_progress[u.handle]=progress
            elif now-progress['clock']>=5 and index<len(self.route)-1:
                next_point=self.route[index+1]
                leg=ground_distance(xy(u),next_point)
                if leg is not None and leg<=distance(xy(u),next_point)+384:
                    index+=1;self.cursors[u.handle]=index;point=next_point
                    self.unit_progress.pop(u.handle,None)
                    self.log('formation_local_unstuck',clock=now,handle=u.handle,point=point)
            hero_ahead=bool(u.is_hero and not retreat and
                distance(xy(u),self.anchor)>900 and
                ground_distance(xy(u),target) is not None and remaining is not None and
                ground_distance(xy(u),target)+200<remaining)
            if hero_ahead:
                self.catching_up.add(u.handle)
                orders.append((u,self.anchor,False))
            else:
                # Units pass the same turns independently; nobody waits for the last straggler.
                orders.append((u,point,index==len(self.route)-1 and distance(xy(u),point)<100 and not retreat))
        self.report(now,spread,hero_spread,len(core))
        return orders

    def report(self,now,spread,hero_spread,members):
        self.metrics=dict(clock=now,stage=self.stage,ground_spread=round(spread),hero_spread=round(hero_spread),members=members,
                          rally=self.rally,next_waypoint=self.route[min(self.cursors.values(),default=0)] if self.route else None,
                          dk_aura_gap=round(getattr(self,'aura_gap',0)),dk_waiting=False,dk_returning=self.aura_wait)
        self.metrics['catching_up']=sorted(self.catching_up)
        if now-self.last_report>=5:
            self.last_report=now
            self.log('formation',**self.metrics)
