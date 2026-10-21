"""Separate actual lightning-shield carriers using visible state only."""
from .scouting import SKELETONS
from math import hypot,cos,sin,pi,atan2

# Local 1.27a Alsh/ACls/AIls Area1=160; add room for movement.
SHIELD_BUFFS={'Blsh','Blsa'}
SAFE_GAP=260


class LightningShield:
    def __init__(self,log):
        self.log=log
        self.active=set()
        self.separated=set()
        self.blocked=set()

    def plan(self,army,hostiles,now,buffs,walkable,ground_distance):
        shields=[u for u in army if (u.type not in SKELETONS or not hostiles) and SHIELD_BUFFS & set(buffs(u))]
        active={u.handle for u in shields}
        self.separated &= active
        self.blocked &= active
        moves={}
        projected={u.handle:(u.x,u.y) for u in army}
        for u in shields:
            allies=[v for v in army if v.handle!=u.handle]
            if u.handle not in self.active:
                self.log('lightning_shield_detected',clock=now,unit=u.type,handle=u.handle)
            if not allies:continue
            def gap(p):
                return min(hypot(p[0]-projected[v.handle][0],p[1]-projected[v.handle][1]) for v in allies)
            origin=(u.x,u.y)
            actual_gap=min(hypot(u.x-v.x,u.y-v.y) for v in allies)
            if min(actual_gap,gap(origin))>=SAFE_GAP:
                if u.handle not in self.separated:
                    self.separated.add(u.handle)
                    self.log('lightning_shield_separated',clock=now,unit=u.type,handle=u.handle,gap=round(actual_gap))
                moves[u.handle]=origin
                continue
            self.separated.discard(u.handle)
            ax=sum(v.x for v in allies)/len(allies);ay=sum(v.y for v in allies)/len(allies)
            angle=atan2(u.y-ay,u.x-ax)
            danger=min((hypot(u.x-e.x,u.y-e.y) for e in hostiles),default=99999)
            candidates=[]
            for step in (320,480,160):
                for i in range(16):
                    p=(u.x+step*cos(angle+i*pi/8),u.y+step*sin(angle+i*pi/8))
                    if gap(p)<=gap(origin)+40 or not walkable(*p):continue
                    if min((hypot(p[0]-e.x,p[1]-e.y) for e in hostiles),default=99999)<danger-50:continue
                    route=ground_distance(origin,p)
                    if route is not None and route<=step*1.6:
                        candidates.append((gap(p)<SAFE_GAP,route,-gap(p),p))
            point=min(candidates)[-1] if candidates else origin
            if not candidates and u.handle not in self.blocked:
                self.blocked.add(u.handle)
                self.log('lightning_shield_blocked',clock=now,unit=u.type,handle=u.handle)
            elif candidates:self.blocked.discard(u.handle)
            moves[u.handle]=point
            projected[u.handle]=point
        self.active=active
        return moves
