"""Stable dual-statue supply; only travel to catch the army or escape danger."""
from math import hypot
from .retreat import escape_point


class StatueSupport:
    def __init__(self,log):
        self.log=log;self.moves={};self.held=set();self.last_plan={}

    def tick(self,b,army,hostiles,now,protected=()):
        g=b.g
        # Wounded units remain supply recipients. Excluding every pulling unit
        # can strand replacements at home or anchor them on an unsafe front.
        # The medoid and local majority keep one distant straggler from leading.
        core=[u for u in army if u.type in {'ucry','Udea','Ulic','Nbrn','Nngs'}
              and u.handle not in b.shopping]
        if not core:return
        anchor=min(core,key=lambda u:sum(g.dist(u,v) for v in core))
        local=[u for u in core if g.dist(u,anchor)<800]
        statues=sorted((u for u in army if u.type=='uobs'),key=lambda u:u.handle)
        live={u.handle for u in statues};self.held &= live
        for i,u in enumerate(statues):
            if u.handle in protected or now<b.cast_until.get(u.handle,0):
                self.held.discard(u.handle);continue
            threats=[e for e in hostiles if b.army_recovery.threat_range(e.type)>0 and
                     g.dist(e,u)<b.army_recovery.threat_range(e.type)+100]
            threatened=bool(threats) or now-b.micro.hit.get(u.handle,-100)<3
            # Public Arpl/Arpm radius is 700. A 600 margin avoids chasing every
            # small army movement or a single injured straggler.
            covered=g.dist(u,anchor)<=520 and sum(g.dist(u,v)<=600 for v in local)>=max(1,(len(local)+1)//2)
            pending=self.moves.get(u.handle)
            if pending and g.dist(u,pending['origin'])>64 and g.dist(u,pending['point'])<g.dist(pending['origin'],pending['point'])-64:
                self.log('statue_support_movement_observed',clock=now,handle=u.handle,reason=pending['reason'],point=(u.x,u.y))
                self.moves.pop(u.handle,None)
            if covered and not threatened:
                if u.handle not in self.held and g.hold(u):
                    self.held.add(u.handle);self.moves.pop(u.handle,None)
                    b.last.pop(('go',u.handle),None)
                    self.log('statue_support_stationed',clock=now,handle=u.handle,point=(u.x,u.y),covered=sum(g.dist(u,v)<=600 for v in local))
                continue
            self.held.discard(u.handle)
            if now-self.last_plan.get(u.handle,-100)<2:continue
            self.last_plan[u.handle]=now
            if threatened:
                point=escape_point(g,u,hostiles,b.army_recovery.threat_range,home=(anchor.x,anchor.y))
                candidates=[point]
                reason='threat_pullback'
            else:
                # Two rear flank points, not the DK's central approach lane.
                enemy=min(hostiles,key=lambda e:g.dist(e,anchor),default=None)
                dx,dy=(anchor.x-enemy.x,anchor.y-enemy.y) if enemy else (b.home.x-anchor.x,b.home.y-anchor.y)
                length=hypot(dx,dy) or 1;dx,dy=dx/length,dy/length
                side=1 if i%2==0 else -1
                candidates=[(anchor.x+dx*rear-dy*side*160,anchor.y+dy*rear+dx*side*160)
                            for rear in (220,380,540)]
                reason='army_out_of_supply_range'
            point=next((p for p in candidates if p is not None and g.dist(u,p)>=80 and
                        b.army_recovery.safe_path(b,(u.x,u.y),p,hostiles) is not None),None)
            if point is None:continue
            if g.move(u,*point):
                self.moves[u.handle]=dict(origin=(u.x,u.y),point=point,reason=reason)
                self.log('statue_support_move_attempt',clock=now,handle=u.handle,point=point,reason=reason,accepted=True)
